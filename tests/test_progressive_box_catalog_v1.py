from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from current_match import CurrentMatch  # noqa: E402
from venue_box_catalog import (  # noqa: E402
    canonical_sha256,
    catalog_selection,
    load_catalog,
    manual_options,
    normalize_vision_box,
    progressive_evidence_class,
    validate_box_observation,
    validate_catalog,
    validate_evidence,
)
import live_shadow  # noqa: E402


class ProgressiveBoxCatalogV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "assets/venue_box_catalog_v1/venue_box_catalog_v1.json")
        cls.evidence_paths = [
            ROOT / "assets/venue_box_catalog_v1/current_game_evidence/2026-08-22/venue-selection-full.evidence.json",
            ROOT / "assets/venue_box_catalog_v1/operator_assertions/operator-confirmed-box-bootstrap.evidence.json",
            ROOT / "assets/venue_box_catalog_v1/operator_assertions/operator-probable-insurance-bootstrap.evidence.json",
        ]
        cls.evidence = [json.loads(path.read_text(encoding="utf-8")) for path in cls.evidence_paths]

    def test_alpha_catalog_is_valid_but_production_gate_rejects(self):
        result = validate_catalog(self.catalog, self.evidence, repo_root=ROOT)
        self.assertTrue(result.ok, result.errors)
        production = validate_catalog(self.catalog, self.evidence, repo_root=ROOT, require_production=True)
        self.assertFalse(production.ok)
        self.assertIn("CATALOG_NOT_APPROVED_FOR_PRODUCTION", production.errors)
        self.assertTrue(any("MEMBERSHIP_NOT_CURRENT" in error for error in production.errors))

    def test_operator_assertion_cannot_masquerade_as_current_capture(self):
        operator = self.evidence[1]
        self.assertEqual(operator["classification"], "OPERATOR_ASSERTED_CURRENT")
        self.assertEqual(operator["evidenceType"], "OPERATOR_ASSERTION")
        self.assertFalse(validate_evidence(operator, repo_root=ROOT, require_current=True).ok)
        self.assertEqual(self.evidence[0]["classification"], "CURRENT_GAME_VALID")

    def test_exact_three_venues_and_unknown_option_derive_from_catalog(self):
        options = manual_options(self.catalog)
        self.assertEqual([item["displayName"] for item in options], ["海贝场", "珊瑚场", "真珠场"])
        self.assertTrue(all(item["boxes"][-1]["boxId"] is None for item in options))
        self.assertTrue(all(item["boxes"][-1]["displayName"] == "未知 / 其他" for item in options))
        serialized = json.dumps(options, ensure_ascii=False, default=lambda value: dict(value))
        for forbidden in ("顶级场", "纸箱", "铁皮箱", "金库保险箱"):
            self.assertNotIn(forbidden, serialized)

    def test_entry_cost_and_unknown_box_semantics(self):
        values = {
            venue_id: catalog_selection(self.catalog, venue_id, None)["entryCost"]
            for venue_id in ("venue-haibei", "venue-shanhu", "venue-zhenzhu")
        }
        self.assertEqual(values, {"venue-haibei": 0, "venue-shanhu": 5000, "venue-zhenzhu": 20000})
        unknown = catalog_selection(self.catalog, "venue-haibei", None)
        self.assertEqual(unknown["boxEvidenceClass"], "UNRECOGNIZED_CURRENT_BOX")
        self.assertIsNone(unknown["boxId"])

    def test_cross_venue_box_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "INVALID_VENUE_BOX_PAIR"):
            catalog_selection(self.catalog, "venue-haibei", "box-shanhu-glass")

    def test_progressive_observation_is_passive_and_no_count_promotion(self):
        observation = {
            "schemaVersion": "box-observation.v1",
            "observedAt": "2026-08-22T19:00:00+08:00",
            "venueId": "venue-haibei",
            "rawDisplayName": "浸水的包裹",
            "rawEffectText": "低级藏品概率提升",
            "screenshotPath": None,
            "screenshotSha256": None,
            "matchId": "natural-match-1",
            "reviewer": "operator",
            "catalogVersion": self.catalog["catalogVersion"],
            "collectionMode": "PASSIVE_NATURAL_COLLECTION",
            "reviewStatus": "APPROVED",
        }
        self.assertTrue(validate_box_observation(observation).ok)
        self.assertEqual(progressive_evidence_class("OPERATOR_ASSERTED_CURRENT", approved_observation=True), "CURRENT_GAME_OBSERVED")
        self.assertEqual(progressive_evidence_class("CURRENT_GAME_OBSERVED", approved_observation=True), "CURRENT_GAME_OBSERVED")
        self.assertEqual(progressive_evidence_class("CURRENT_GAME_OBSERVED", approved_observation=True, explicit_validation=True), "CURRENT_GAME_VALID")

    def test_vision_normalization_preserves_observation_provenance(self):
        normalized = normalize_vision_box(
            self.catalog,
            venue_id="venue-shanhu",
            observation="琉璃宝箱 · 宝石类概率提升",
        )
        self.assertEqual(normalized["boxId"], "box-shanhu-glass")
        self.assertEqual(normalized["provenance"], "VISION_OBSERVATION")
        unknown = normalize_vision_box(self.catalog, venue_id="venue-shanhu", observation="新箱子")
        self.assertEqual(unknown["status"], "UNKNOWN")

    def test_future_manual_canonical_preserves_catalog_provenance_and_zero_cost(self):
        selection = catalog_selection(self.catalog, "venue-haibei", "box-haibei-waterlogged-package")
        match = CurrentMatch()
        match.apply_facts({
            **selection,
            "catalogVersion": self.catalog["catalogVersion"],
            "catalogApprovalStatus": self.catalog["catalogStatus"],
            "catalogSha256": canonical_sha256(self.catalog),
            "gameEvidenceCohort": "CURRENT_VENUE_OPERATOR_BOX_BOOTSTRAP_2026_08_22",
        })
        canonical = match.to_canonical()
        self.assertEqual(canonical["costs"]["entry"], 0)
        self.assertEqual(canonical["environment"]["boxEvidenceClass"], "OPERATOR_ASSERTED_CURRENT")
        self.assertEqual(canonical["environment"]["catalogApprovalStatus"], "APPROVED_FOR_ALPHA")

    def test_shadow_guard_excludes_only_explicit_operator_assertions(self):
        records = [
            {"id": "legacy"},
            {"id": "operator", "environment": {"boxEvidenceClass": "OPERATOR_ASSERTED_CURRENT"}},
            {"id": "observed", "environment": {"boxEvidenceClass": "CURRENT_GAME_OBSERVED"}},
        ]
        self.assertEqual(live_shadow._shadow_history_allowed_ids(records), ["legacy", "observed"])

    def test_production_files_have_no_independent_manual_catalog_hardcodes(self):
        overlay = (ROOT / "core/overlay_alpha.html").read_text(encoding="utf-8")
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        self.assertNotIn("VENUE_TIERS", overlay)
        self.assertNotIn("BOXES_BY_TIER", overlay)
        for forbidden in ("顶级场", "纸箱", "铁皮箱", "金库保险箱"):
            self.assertNotIn(forbidden, overlay)
            self.assertNotIn(forbidden, main)
        self.assertIn("venue_box_catalog_v1.json", (ROOT / "app/异环拍卖助手.spec").read_text(encoding="utf-8"))

    def test_algorithm_and_history_hashes_match_checkpoint(self):
        expected = {
            "core/auction_engine_v06.js": "205b04c9b7af7094cc27b91003cbbff47d7b437d99e0ef4a5beecb78e3f35142",
            "core/solver_core_v06.js": "1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f",
            "core/shadow_profile_v06.js": "9967f269f5c5b66dc8a010e3077ce014700c0b94333d93acf25a4021f9c886a5",
        }
        for relative, digest in expected.items():
            content = (ROOT / relative).read_bytes()
            if relative == "core/auction_engine_v06.js":
                # The frozen result now carries the already computed decision.
                # Keep the original algorithm checkpoint; allow only this exact
                # serialization addition, not arbitrary changes to the Solver.
                transport_line = b"      decision: d.decision ? JSON.parse(JSON.stringify(d.decision)) : null,\n"
                self.assertEqual(content.count(transport_line), 1)
                content = content.replace(transport_line, b"", 1)
            self.assertEqual(hashlib.sha256(content).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
