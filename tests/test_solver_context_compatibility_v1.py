# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))

from venue_box_catalog import (  # noqa: E402
    canonical_sha256,
    load_catalog,
    load_solver_compatibility,
    solver_context_translation,
    validate_catalog,
    validate_solver_compatibility,
)


class SolverContextCompatibilityV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog()
        cls.compatibility = load_solver_compatibility()
        evidence_root = ROOT / "assets" / "venue_box_catalog_v1"
        cls.evidence = [
            json.loads((evidence_root / "current_game_evidence/2026-08-22/venue-selection-full.evidence.json").read_text(encoding="utf-8")),
            json.loads((evidence_root / "operator_assertions/operator-confirmed-box-bootstrap.evidence.json").read_text(encoding="utf-8")),
            json.loads((evidence_root / "operator_assertions/operator-probable-insurance-bootstrap.evidence.json").read_text(encoding="utf-8")),
        ]

    def test_catalog_and_compatibility_artifact_validate(self) -> None:
        catalog_result = validate_catalog(self.catalog, self.evidence, repo_root=ROOT)
        self.assertTrue(catalog_result.ok, catalog_result.errors)
        result = validate_solver_compatibility(self.catalog, self.compatibility, repo_root=ROOT)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(
            canonical_sha256(self.compatibility),
            canonical_sha256(json.loads(json.dumps(self.compatibility, ensure_ascii=False))),
        )
        self.assertIn(
            "v06_solver_compatibility_v1.json",
            (ROOT / "app/异环拍卖助手.spec").read_text(encoding="utf-8"),
        )

    def test_exact_three_venue_translations_and_priors(self) -> None:
        expected = {
            "venue-haibei": ("初级场 · 海贝场", 8000),
            "venue-shanhu": ("中级场 · 珊瑚场", 12000),
            "venue-zhenzhu": ("高级场 · 真珠场", 30000),
        }
        contexts = {}
        for venue_id, (legacy, prior) in expected.items():
            translated = solver_context_translation(self.catalog, venue_id=venue_id, box_id=None)
            self.assertEqual(translated["status"], "COMPATIBILITY_TRANSLATION")
            self.assertEqual(translated["venue"], legacy)
            self.assertEqual(translated["boxStatus"], "UNKNOWN_NO_BOX_EFFECT")
            contexts[venue_id] = {"venue": translated["venue"], "expectedPrior": prior}
        script = (
            "const e=require('./core/auction_engine_v06.js');"
            "const rows=" + json.dumps(contexts, ensure_ascii=False) + ";"
            "for(const row of Object.values(rows)) row.actual=e.lowTierValue({venue:row.venue}).mid;"
            "process.stdout.write(JSON.stringify(rows));"
        )
        output = json.loads(subprocess.check_output(
            ["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8"
        ))
        self.assertTrue(all(row["actual"] == row["expectedPrior"] for row in output.values()))

    def test_all_approved_alpha_boxes_have_explicit_legacy_semantics(self) -> None:
        catalog_boxes = {
            box["boxId"]: venue["venueId"]
            for venue in self.catalog["venues"]
            for box in venue["boxes"]
        }
        artifact_boxes = {row["currentId"]: row for row in self.compatibility["boxTranslations"]}
        self.assertEqual(set(artifact_boxes), set(catalog_boxes))
        self.assertEqual(len(artifact_boxes), 16)
        for box_id, venue_id in catalog_boxes.items():
            translated = solver_context_translation(self.catalog, venue_id=venue_id, box_id=box_id)
            self.assertEqual(translated["status"], "COMPATIBILITY_TRANSLATION", box_id)
            self.assertEqual(translated["boxStatus"], "COMPATIBILITY_TRANSLATION", box_id)
            self.assertTrue(translated["box"])
            self.assertTrue(translated["boxSemantic"])

    def test_unknown_and_invalid_pairs_fail_closed(self) -> None:
        unknown = solver_context_translation(self.catalog, venue_id="venue-haibei", box_id=None)
        self.assertIsNone(unknown["box"])
        self.assertEqual(unknown["boxSemantic"], "NO_BOX_EFFECT")
        self.assertEqual(unknown["boxStatus"], "UNKNOWN_NO_BOX_EFFECT")

        invalid = solver_context_translation(
            self.catalog,
            venue_id="venue-haibei",
            box_id="box-shanhu-glass",
        )
        self.assertEqual(invalid["status"], "SOLVER_CONTEXT_MAPPING_UNRESOLVED")
        unsupported = solver_context_translation(self.catalog, venue_id="venue-missing", box_id=None)
        self.assertEqual(unsupported["status"], "SOLVER_CONTEXT_MAPPING_UNRESOLVED")

    def test_raw_game_truth_and_tier_are_unchanged_by_legacy_semantics(self) -> None:
        expected_raw = {
            "box-haibei-damaged-package": "低级提升",
            "box-haibei-complete-package": "中级提升",
            "box-haibei-waterlogged-package": "低级藏品概率提升",
            "box-haibei-unnamed-package": "高级提升",
        }
        for venue in self.catalog["venues"]:
            self.assertEqual(venue["tier"], {
                "status": "NOT_GAME_AUTHORITY",
                "value": None,
                "evidenceRefs": ["current-game-2026-08-22-venue-selection-full"],
            })
            for box in venue["boxes"]:
                if box["boxId"] in expected_raw:
                    self.assertEqual(box["effect"]["rawGameText"], expected_raw[box["boxId"]])
                self.assertIsNone(box["effect"]["normalizedSemantic"])

    def test_v06_production_path_parity_for_three_venues(self) -> None:
        fixtures = [
            ("venue-haibei", "box-haibei-waterlogged-package"),
            ("venue-shanhu", "box-shanhu-glass"),
            ("venue-zhenzhu", "box-zhenzhu-brilliant-safe"),
        ]
        pairs = []
        for venue_id, box_id in fixtures:
            translated = solver_context_translation(self.catalog, venue_id=venue_id, box_id=box_id)
            artifact_venue = next(row for row in self.compatibility["venueTranslations"] if row["currentId"] == venue_id)
            artifact_box = next(row for row in self.compatibility["boxTranslations"] if row["currentId"] == box_id)
            pairs.append({
                "old": {"venue": artifact_venue["legacyIdentifier"], "box": artifact_box["legacyIdentifier"]},
                "translated": {"venue": translated["venue"], "box": translated["box"]},
            })
        script = r"""
const engine=require('./core/auction_engine_v06.js');
const pairs=JSON.parse(process.argv[1]);
const base={q:9,avg:33538,goldAvg:33538,purpleCount:5,p:5,knownGold:'万有星仪',knownPurple:'拈花小像+金角月芒',fieldCondition:'standard'};
const slim=(x,input)=>({
  solverStatus:x.solverStatus,
  states:(x.states||[]).map(s=>[s.G,s.P,s.R,s.totalMin,s.totalMax]),
  p20:x.formalValue?.p20??null,
  p50:x.formalValue?.p50??null,
  p80:x.formalValue?.p80??null,
  structuralCenter:x.decision?.structuralCenter??null,
  lowTierPrior:engine.lowTierValue(input).mid
});
const out=pairs.map(pair=>{
  const oldInput={...base,...pair.old};
  const translatedInput={...base,...pair.translated};
  return {old:slim(engine.solveAuctionPipeline(oldInput),oldInput),translated:slim(engine.solveAuctionPipeline(translatedInput),translatedInput)};
});
process.stdout.write(JSON.stringify(out));
"""
        output = json.loads(subprocess.check_output(
            ["node", "-e", script, json.dumps(pairs, ensure_ascii=False)],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        ))
        for row in output:
            self.assertEqual(row["translated"], row["old"])

    def test_corrupt_or_stale_artifact_is_rejected(self) -> None:
        corrupt = copy.deepcopy(self.compatibility)
        corrupt["boxTranslations"][0]["catalogVenueId"] = "venue-shanhu"
        result = validate_solver_compatibility(self.catalog, corrupt, repo_root=ROOT)
        self.assertFalse(result.ok)
        translated = solver_context_translation(
            self.catalog,
            venue_id="venue-haibei",
            box_id="box-haibei-damaged-package",
            compatibility=corrupt,
        )
        self.assertEqual(translated["status"], "SOLVER_CONTEXT_COMPATIBILITY_INVALID")

    def test_integrity_hashes_and_current_facts(self) -> None:
        expected = {
            "core/auction_engine_v06.js": "205b04c9b7af7094cc27b91003cbbff47d7b437d99e0ef4a5beecb78e3f35142",
            "core/solver_core_v06.js": "1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f",
            "core/shadow_profile_v06.js": "9967f269f5c5b66dc8a010e3077ce014700c0b94333d93acf25a4021f9c886a5",
        }
        for relative, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest)
        facts = {
            venue["venueId"]: (
                venue["displayName"], venue["entryCost"]["value"], venue["assetRequirement"]["value"]
            )
            for venue in self.catalog["venues"]
        }
        self.assertEqual(facts, {
            "venue-haibei": ("海贝场", 0, 0),
            "venue-shanhu": ("珊瑚场", 5000, 1000000),
            "venue-zhenzhu": ("真珠场", 20000, 5000000),
        })


if __name__ == "__main__":
    unittest.main()
