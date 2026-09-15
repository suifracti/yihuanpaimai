from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(CORE))

from venue_box_catalog import (  # noqa: E402
    CatalogContractError,
    canonical_catalog_provenance,
    canonical_sha256,
    evidence_bundle_sha256,
    manual_options,
    normalize_vision_venue,
    solver_context_translation,
    validate_catalog,
    validate_environment,
    validate_evidence,
)


def _load_audit_module():
    spec = importlib.util.spec_from_file_location(
        "venue_box_catalog_audit", TOOLS / "venue_box_catalog_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VenueBoxCatalogContractV1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp.name)
        source = self.repo_root / "evidence" / "venue.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"fixed-current-game-capture")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        self.evidence = {
            "schemaVersion": "venue-box-catalog-evidence.v1",
            "evidenceId": "current-build-venue-options",
            "gameBuild": "fixture-build-1",
            "capturedAt": "2026-08-22T12:00:00+08:00",
            "evidenceType": "CURRENT_GAME_FULL_UI",
            "sourcePath": "evidence/venue.png",
            "sourceSha256": source_hash,
            "reviewer": "fixture-reviewer",
            "reviewStatus": "APPROVED",
            "classification": "CURRENT_GAME_VALID",
            "claims": [
                {
                    "claimType": "VENUE_DISPLAY_NAME",
                    "rawGameText": "海贝场",
                    "venueDisplayName": "海贝场",
                },
                {
                    "claimType": "VENUE_ENTRY_COST",
                    "rawGameText": "0",
                    "venueDisplayName": "海贝场",
                    "value": 0,
                },
                {
                    "claimType": "VENUE_BOX_MEMBERSHIP",
                    "rawGameText": "海贝场 / 浸水的包裹",
                    "venueDisplayName": "海贝场",
                    "boxDisplayName": "浸水的包裹",
                },
            ],
        }
        evidence_hash = evidence_bundle_sha256([self.evidence])
        fact_unknown = {"status": "NOT_GAME_AUTHORITY", "value": None, "evidenceRefs": []}
        self.catalog = {
            "schemaVersion": "venue-box-catalog.v1",
            "catalogVersion": "fixture-catalog-1",
            "catalogStatus": "APPROVED_FOR_PRODUCTION",
            "gameBuild": "fixture-build-1",
            "generatedAt": "2026-08-22T12:05:00+08:00",
            "evidenceBundleSha256": evidence_hash,
            "venues": [
                {
                    "venueId": "venue-haibei",
                    "displayName": "海贝场",
                    "selectable": True,
                    "tier": copy.deepcopy(fact_unknown),
                    "assetRequirement": {
                        "status": "VERIFIED",
                        "value": 0,
                        "evidenceRefs": ["current-build-venue-options"],
                    },
                    "entryCost": {
                        "status": "VERIFIED",
                        "value": 0,
                        "evidenceRefs": ["current-build-venue-options"],
                    },
                    "evidenceRefs": ["current-build-venue-options"],
                    "observationAliases": ["haibei"],
                    "boxes": [
                        {
                            "boxId": "box-waterlogged-package",
                            "displayName": "浸水的包裹",
                            "effect": {
                                "rawGameText": "低级藏品概率提升",
                                "normalizedSemantic": None,
                                "normalizationEvidenceRefs": [],
                            },
                            "evidenceRefs": ["current-build-venue-options"],
                            "observationAliases": [],
                            "membershipEvidenceClass": "CURRENT_GAME_VALID",
                            "textEvidenceClass": "CURRENT_GAME_VALID",
                            "operatorConfidence": None,
                        }
                    ],
                }
            ],
            "compatibilityTranslations": [
                {
                    "consumer": "v06_solver",
                    "catalogVenueId": "venue-haibei",
                    "status": "EXPLICIT",
                    "compatibilityValue": "haibei",
                }
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_approved_catalog_and_evidence_pass(self):
        self.assertTrue(validate_evidence(self.evidence, repo_root=self.repo_root, require_current=True).ok)
        result = validate_catalog(
            self.catalog, [self.evidence], repo_root=self.repo_root, require_production=True
        )
        self.assertTrue(result.ok, result.errors)

    def test_evidence_requires_game_build_timezone_and_refs(self):
        broken = copy.deepcopy(self.evidence)
        broken["gameBuild"] = "UNKNOWN"
        broken["capturedAt"] = "2026-08-22T12:00:00"
        broken["claims"] = []
        result = validate_evidence(broken, repo_root=self.repo_root, require_current=True)
        self.assertFalse(result.ok)
        self.assertIn("EVIDENCE_GAME_BUILD_UNKNOWN", result.errors)
        self.assertIn("EVIDENCE_CAPTURED_AT_NOT_TIMEZONE_AWARE", result.errors)
        self.assertIn("EVIDENCE_CLAIMS_EMPTY", result.errors)

    def test_catalog_and_bundle_hash_are_deterministic(self):
        first = evidence_bundle_sha256([self.evidence])
        second = evidence_bundle_sha256([copy.deepcopy(self.evidence)])
        self.assertEqual(first, second)
        self.assertEqual(canonical_sha256(self.catalog), canonical_sha256(copy.deepcopy(self.catalog)))

    def test_manual_options_derive_venues_and_boxes_from_catalog(self):
        options = manual_options(self.catalog)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["displayName"], "海贝场")
        self.assertEqual(options[0]["boxes"][0]["displayName"], "浸水的包裹")
        self.assertNotIn("venueTier", options[0])

    def test_unapproved_catalog_cannot_reach_consumers(self):
        draft = copy.deepcopy(self.catalog)
        draft["catalogStatus"] = "DRAFT"
        with self.assertRaisesRegex(CatalogContractError, "CATALOG_NOT_APPROVED"):
            manual_options(draft)
        result = validate_catalog(draft, [self.evidence], repo_root=self.repo_root, require_production=True)
        self.assertFalse(result.ok)

    def test_environment_fails_closed_and_preserves_unknown(self):
        unknown = validate_environment(self.catalog, venue_id=None, box_id=None)
        self.assertTrue(unknown["ok"])
        self.assertEqual(unknown["status"], "UNKNOWN")
        self.assertFalse(validate_environment(
            self.catalog, venue_id="missing", box_id=None
        )["ok"])
        self.assertEqual(
            validate_environment(self.catalog, venue_id="venue-haibei", box_id="orphan")["status"],
            "INVALID_VENUE_BOX_PAIR",
        )
        self.assertEqual(
            validate_environment(self.catalog, venue_id=None, box_id="box-waterlogged-package")["status"],
            "BOX_WITHOUT_VENUE",
        )

    def test_exact_zero_entry_cost_and_null_tier_survive(self):
        venue = self.catalog["venues"][0]
        self.assertEqual(venue["entryCost"]["value"], 0)
        self.assertIsNone(venue["tier"]["value"])
        result = validate_catalog(self.catalog, [self.evidence], repo_root=self.repo_root)
        self.assertTrue(result.ok, result.errors)

    def test_vision_normalization_is_explicit(self):
        self.assertEqual(normalize_vision_venue(self.catalog, "haibei")["venueId"], "venue-haibei")
        self.assertEqual(normalize_vision_venue(self.catalog, "zhenzhu")["status"], "REJECTED")
        self.assertEqual(normalize_vision_venue(self.catalog, None)["status"], "UNKNOWN")

    def test_solver_translation_is_compatibility_not_authority(self):
        translated = solver_context_translation(
            self.catalog, venue_id="venue-haibei", box_id="box-waterlogged-package"
        )
        self.assertEqual(translated["status"], "COMPATIBILITY_TRANSLATION")
        self.assertEqual(translated["venue"], "haibei")
        unresolved = copy.deepcopy(self.catalog)
        unresolved["compatibilityTranslations"][0]["status"] = "UNRESOLVED"
        unresolved["compatibilityTranslations"][0]["compatibilityValue"] = None
        self.assertEqual(
            solver_context_translation(
                unresolved, venue_id="venue-haibei", box_id="box-waterlogged-package"
            )["status"],
            "SOLVER_CONTEXT_MAPPING_UNRESOLVED",
        )

    def test_canonical_provenance_contains_version_and_hash(self):
        provenance = canonical_catalog_provenance(self.catalog)
        self.assertEqual(provenance["catalogVersion"], "fixture-catalog-1")
        self.assertEqual(provenance["gameBuild"], "fixture-build-1")
        self.assertEqual(len(provenance["catalogSha256"]), 64)

    def test_nonverified_facts_cannot_hide_defaults(self):
        broken = copy.deepcopy(self.catalog)
        broken["venues"][0]["tier"] = {
            "status": "UNKNOWN", "value": "初级", "evidenceRefs": []
        }
        result = validate_catalog(broken, [self.evidence], repo_root=self.repo_root)
        self.assertFalse(result.ok)
        self.assertTrue(any("NONVERIFIED_VALUE_MUST_BE_NULL" in item for item in result.errors))

    def test_normalized_effect_requires_independent_current_evidence(self):
        broken = copy.deepcopy(self.catalog)
        effect = broken["venues"][0]["boxes"][0]["effect"]
        effect["normalizedSemantic"] = "purple_probability_boost"
        effect["normalizationEvidenceRefs"] = []
        result = validate_catalog(broken, [self.evidence], repo_root=self.repo_root)
        self.assertFalse(result.ok)
        self.assertIn(
            "CATALOG_BOX_NORMALIZATION_EVIDENCE_MISSING:box-waterlogged-package",
            result.errors,
        )

    def test_legacy_audit_is_read_only_and_never_claims_current_truth(self):
        audit = _load_audit_module()
        history = self.repo_root / "history.json"
        history.write_text(json.dumps({"records": [
            {"id": "legacy", "venue": "shanhu", "box": "完整的包裹"},
            {"id": "unknown", "venue": None, "box": None},
            {"id": "conflict", "venue": "haibei", "environment": {"venue": "shanhu"}},
        ]}, ensure_ascii=False), encoding="utf-8")
        before = history.read_bytes()
        result = audit.audit_history(history)
        self.assertEqual(result["counts"]["CATALOG_VALID_CURRENT"], 0)
        self.assertEqual(result["counts"]["LEGACY_ALIAS"], 1)
        self.assertEqual(result["counts"]["UNKNOWN"], 1)
        self.assertEqual(result["counts"]["CONFLICT"], 1)
        self.assertEqual(history.read_bytes(), before)

    def test_contract_module_has_no_business_runtime_imports(self):
        source = (CORE / "venue_box_catalog.py").read_text(encoding="utf-8")
        for forbidden in (
            "current_match", "auction_engine", "solver_core", "vision_pipeline", "live_shadow"
        ):
            self.assertNotIn(f"import {forbidden}", source)
            self.assertNotIn(f"from {forbidden}", source)

    def test_schema_files_are_json_and_require_authority_fields(self):
        evidence_schema = json.loads((ROOT / "docs/contracts/venue-box-catalog-evidence-v1.schema.json").read_text(encoding="utf-8"))
        catalog_schema = json.loads((ROOT / "docs/contracts/venue-box-catalog-v1.schema.json").read_text(encoding="utf-8"))
        self.assertIn("gameBuild", evidence_schema["required"])
        self.assertIn("sourceSha256", evidence_schema["required"])
        self.assertIn("evidenceBundleSha256", catalog_schema["required"])
        self.assertIn("compatibilityTranslations", catalog_schema["required"])

    def test_current_venue_evidence_and_candidate_freeze_exact_screen_facts(self):
        evidence_path = ROOT / "assets/venue_box_catalog_v1/current_game_evidence/2026-08-22/venue-selection-full.evidence.json"
        candidate_path = ROOT / "assets/venue_box_catalog_v1/venue_box_catalog_candidate_v1.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        source = ROOT / evidence["sourcePath"]
        self.assertEqual(
            hashlib.sha256(source.read_bytes()).hexdigest(),
            "b397a7bd921aeba6ed165f8ba972641d864672dd9b43c5d04d39179bb1d3d8da",
        )
        self.assertTrue(validate_evidence(evidence, repo_root=ROOT, require_current=True).ok)
        venue_claims = {
            claim["venueDisplayName"]: claim["rawGameText"]
            for claim in evidence["claims"] if claim["claimType"] == "VENUE_DISPLAY_NAME"
        }
        self.assertEqual(set(venue_claims), {"海贝场", "珊瑚场", "真珠场"})
        requirements = {
            claim["venueDisplayName"]: claim["value"]
            for claim in evidence["claims"] if claim["claimType"] == "VENUE_ASSET_REQUIREMENT"
        }
        costs = {
            claim["venueDisplayName"]: claim["value"]
            for claim in evidence["claims"] if claim["claimType"] == "VENUE_ENTRY_COST"
        }
        self.assertEqual(requirements, {"海贝场": 0, "珊瑚场": 1000000, "真珠场": 5000000})
        self.assertEqual(costs, {"海贝场": 0, "珊瑚场": 5000, "真珠场": 20000})
        self.assertTrue(validate_catalog(candidate, [evidence], repo_root=ROOT).ok)
        self.assertEqual({venue["displayName"] for venue in candidate["venues"]}, {"海贝场", "珊瑚场", "真珠场"})
        self.assertTrue(all(venue["tier"]["status"] == "NOT_GAME_AUTHORITY" for venue in candidate["venues"]))
        serialized = json.dumps(candidate, ensure_ascii=False)
        for unsupported in ("顶级场", "海沫", "haimo", "dingji"):
            self.assertNotIn(unsupported, serialized)

    def test_candidate_fails_production_gate_until_box_evidence_is_complete(self):
        evidence = json.loads((ROOT / "assets/venue_box_catalog_v1/current_game_evidence/2026-08-22/venue-selection-full.evidence.json").read_text(encoding="utf-8"))
        candidate = json.loads((ROOT / "assets/venue_box_catalog_v1/venue_box_catalog_candidate_v1.json").read_text(encoding="utf-8"))
        result = validate_catalog(candidate, [evidence], repo_root=ROOT, require_production=True)
        self.assertFalse(result.ok)
        self.assertIn("CATALOG_NOT_APPROVED_FOR_PRODUCTION", result.errors)
        self.assertEqual(
            {error for error in result.errors if error.startswith("CATALOG_PRODUCTION_BOX_SET_EMPTY")},
            {
                "CATALOG_PRODUCTION_BOX_SET_EMPTY:venue-haibei",
                "CATALOG_PRODUCTION_BOX_SET_EMPTY:venue-shanhu",
                "CATALOG_PRODUCTION_BOX_SET_EMPTY:venue-zhenzhu",
            },
        )
        with self.assertRaisesRegex(CatalogContractError, "CATALOG_NOT_APPROVED"):
            manual_options(candidate)


if __name__ == "__main__":
    unittest.main()
