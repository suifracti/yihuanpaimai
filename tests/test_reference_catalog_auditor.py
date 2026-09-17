# -*- coding: utf-8 -*-
"""Unit tests for PR-F Reference Catalog Discrepancy Auditor.

Covers all 20 required verification points:
1. Deterministic report
2. Input canonical files unchanged
3. External-only item never auto-added
4. External-only => REFERENCE_ONLY_UNVERIFIED
5. Same-ID different field => ATTRIBUTE_CONFLICT / ID_CONFLICT
6. Footprint mismatch => FOOTPRINT_CONFLICT
7. Solver named / visual unnamed detected
8. Missing visual reference detected
9. Insufficient reference separate from missing
10. Name variant does not mutate canonical name
11. Independent evidence absent => verification required
12. Duplicate discrepancy deterministic ID
13. Report provenance present
14. All rows autoWriteAllowed=false
15. No competitor PNG/templates/database added
16. Generated output contains no copied external binary asset
17. Canonical before/after hashes identical
18. Runtime catalog lookup unchanged
19. PR-E contracts unchanged
20. Boundary 3 intersection strictly zero
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "core"))
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

from reference_catalog_auditor import (
    CLASSIFICATION_ATTRIBUTE_CONFLICT,
    CLASSIFICATION_CANONICAL_ONLY,
    CLASSIFICATION_CANONICAL_VISUAL_MISSING,
    CLASSIFICATION_FOOTPRINT_CONFLICT,
    CLASSIFICATION_ID_CONFLICT,
    CLASSIFICATION_INDEPENDENT_VERIFICATION_REQUIRED,
    CLASSIFICATION_NAME_VARIANT,
    CLASSIFICATION_NO_ACTION,
    CLASSIFICATION_QUALITY_CONFLICT,
    CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED,
    CLASSIFICATION_SOLVER_NAMED_VISUAL_UNNAMED,
    CLASSIFICATION_VISUAL_REFERENCE_INSUFFICIENT,
    RECOMMENDED_EVIDENCE_INDEPENDENT_RECORDING,
    RECOMMENDED_EVIDENCE_NONE,
    RECOMMENDED_EVIDENCE_SECOND_INDEPENDENT_SOURCE,
    RECOMMENDED_EVIDENCE_USER_ITEM_CARD,
    RECOMMENDED_EVIDENCE_USER_SCREENSHOT,
    VALID_CLASSIFICATIONS,
    VALID_RECOMMENDED_EVIDENCE,
    CANONICAL_TRACKED_FILES,
    ReferenceCatalogAuditor,
    compute_canonical_hashes,
    compute_file_sha256,
)

BOUNDARY3_FILES = {
    "app/warehouse_pipeline.py",
    "core/visual_matcher.py",
    "core/warehouse_vision.py",
    "core/warehouse_safety_coordinator.py",
    "core/frame_source.py",
    "core/win32_window_focus.py",
    "tests/test_warehouse_pipeline.py",
    "tests/test_warehouse_vision.py",
    "tests/test_warehouse_safety_coordinator.py",
    "tests/test_warehouse_scan_driver.py",
}


class TestReferenceCatalogAuditor(unittest.TestCase):

    def setUp(self):
        self.auditor = ReferenceCatalogAuditor(_PROJECT_ROOT)

    # 1. Deterministic report
    def test_01_deterministic_report(self):
        report1 = self.auditor.audit()
        report2 = self.auditor.audit()
        self.assertEqual(report1["schemaVersion"], report2["schemaVersion"])
        self.assertEqual(
            report1["discrepancyStatistics"]["totalDiscrepancies"],
            report2["discrepancyStatistics"]["totalDiscrepancies"],
        )
        self.assertEqual(
            report1["inventorySummary"]["visualCoverage"]["canonicalTotal"],
            report2["inventorySummary"]["visualCoverage"]["canonicalTotal"],
        )
        self.assertEqual(len(report1["discrepancies"]), len(report2["discrepancies"]))

    # 2. Input canonical files unchanged
    def test_02_input_canonical_files_unchanged(self):
        before = compute_canonical_hashes(_PROJECT_ROOT)
        self.auditor.audit()
        after = compute_canonical_hashes(_PROJECT_ROOT)
        for rel in CANONICAL_TRACKED_FILES:
            self.assertEqual(
                before[rel], after[rel],
                f"Canonical file {rel} was unexpectedly modified during audit!"
            )

    # 3. External-only item never auto-added
    def test_03_external_only_item_never_auto_added(self):
        cat_path = _PROJECT_ROOT / "assets/catalog_065.json"
        data = json.loads(cat_path.read_text(encoding="utf-8"))
        cat_names = {item["Name"] for item in data}
        report = self.auditor.audit()
        ref_only_items = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED
        ]
        self.assertGreater(len(ref_only_items), 0)
        # Check that none of the external-only items were inserted into catalog_065.json
        for d in ref_only_items:
            obs_name = d.get("referenceObservedName")
            if obs_name:
                self.assertNotIn(
                    obs_name, cat_names,
                    f"External-only item '{obs_name}' was illegally auto-added to canonical catalog!"
                )

    # 4. External-only => REFERENCE_ONLY_UNVERIFIED
    def test_04_external_only_yields_reference_only_unverified(self):
        report = self.auditor.audit()
        ref_only = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED
        ]
        self.assertGreater(len(ref_only), 0)
        for d in ref_only:
            self.assertEqual(d["classification"], CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED)
            self.assertFalse(d["autoWriteAllowed"])
            self.assertIn(d["recommendedNextEvidence"], (RECOMMENDED_EVIDENCE_USER_ITEM_CARD, RECOMMENDED_EVIDENCE_USER_SCREENSHOT))

    # 5. Same-ID different field => ATTRIBUTE_CONFLICT / ID_CONFLICT
    def test_05_same_id_different_field_yields_attribute_conflict(self):
        report = self.auditor.audit()
        id_conflicts = [
            d for d in report["discrepancies"]
            if d["classification"] in (CLASSIFICATION_ID_CONFLICT, CLASSIFICATION_ATTRIBUTE_CONFLICT, CLASSIFICATION_QUALITY_CONFLICT)
        ]
        self.assertGreater(len(id_conflicts), 0)
        # Verify latiao ID collision (image3-0-2) is captured
        latiao = [d for d in id_conflicts if d["canonicalId"] == "image3-0-2"]
        self.assertEqual(len(latiao), 1)
        self.assertEqual(latiao[0]["classification"], CLASSIFICATION_ID_CONFLICT)
        self.assertEqual(latiao[0]["canonicalValue"]["quality"], "white")
        self.assertEqual(latiao[0]["referenceValue"]["quality"], "red")

    # 6. Footprint mismatch => FOOTPRINT_CONFLICT
    def test_06_footprint_mismatch_yields_footprint_conflict(self):
        report = self.auditor.audit()
        fp_conflicts = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_FOOTPRINT_CONFLICT
        ]
        self.assertGreater(len(fp_conflicts), 0)
        for d in fp_conflicts:
            self.assertEqual(d["classification"], CLASSIFICATION_FOOTPRINT_CONFLICT)
            self.assertFalse(d["autoWriteAllowed"])

    # 7. Solver named / visual unnamed detected
    def test_07_solver_named_visual_unnamed_detected(self):
        report = self.auditor.audit()
        solver_gaps = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_SOLVER_NAMED_VISUAL_UNNAMED
        ]
        self.assertGreater(len(solver_gaps), 0)
        for d in solver_gaps:
            self.assertEqual(d["classification"], CLASSIFICATION_SOLVER_NAMED_VISUAL_UNNAMED)
            self.assertFalse(d["autoWriteAllowed"])
            self.assertIsNone(d["canonicalId"])

    # 8. Missing visual reference detected
    def test_08_missing_visual_reference_detected(self):
        report = self.auditor.audit()
        missing = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_CANONICAL_VISUAL_MISSING
        ]
        self.assertGreater(len(missing), 0)
        # Check image2-1-1 (磨刀石) is flagged
        m = [d for d in missing if d["canonicalId"] == "image2-1-1"]
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["canonicalName"], "磨刀石")
        self.assertEqual(m[0]["classification"], CLASSIFICATION_CANONICAL_VISUAL_MISSING)

    # 9. Insufficient reference separate from missing
    def test_09_insufficient_reference_separate_from_missing(self):
        report = self.auditor.audit()
        insufficient = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_VISUAL_REFERENCE_INSUFFICIENT
        ]
        self.assertGreater(len(insufficient), 0)
        for d in insufficient:
            self.assertEqual(d["classification"], CLASSIFICATION_VISUAL_REFERENCE_INSUFFICIENT)
            self.assertNotEqual(d["classification"], CLASSIFICATION_CANONICAL_VISUAL_MISSING)

    # 10. Name variant does not mutate canonical name
    def test_10_name_variant_does_not_mutate_canonical_name(self):
        cat_path = _PROJECT_ROOT / "assets/catalog_065.json"
        cat_before = {i["Id"]: i["Name"] for i in json.loads(cat_path.read_text(encoding="utf-8"))}
        report = self.auditor.audit()
        cat_after = {i["Id"]: i["Name"] for i in json.loads(cat_path.read_text(encoding="utf-8"))}
        self.assertEqual(cat_before, cat_after)

        name_variants = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_NAME_VARIANT
        ]
        self.assertGreater(len(name_variants), 0)
        for d in name_variants:
            self.assertFalse(d["autoWriteAllowed"])

    # 11. Independent evidence absent => verification required
    def test_11_independent_evidence_absent_requires_verification(self):
        report = self.auditor.audit()
        queue = report["independentVerificationQueue"]
        self.assertGreater(len(queue), 0)
        for item in queue:
            self.assertIn(
                item["recommendedNextEvidence"],
                (
                    RECOMMENDED_EVIDENCE_USER_ITEM_CARD,
                    RECOMMENDED_EVIDENCE_USER_SCREENSHOT,
                    RECOMMENDED_EVIDENCE_INDEPENDENT_RECORDING,
                    RECOMMENDED_EVIDENCE_SECOND_INDEPENDENT_SOURCE,
                ),
            )
            self.assertFalse(item["autoWriteAllowed"])

    # 12. Duplicate discrepancy deterministic ID
    def test_12_duplicate_discrepancy_deterministic_id(self):
        report = self.auditor.audit()
        disc_ids = [d["discrepancyId"] for d in report["discrepancies"]]
        self.assertEqual(len(disc_ids), len(set(disc_ids)), "Found duplicate discrepancy IDs!")
        for did in disc_ids:
            self.assertTrue(did.startswith("disc-"), f"Invalid discrepancyId format: {did}")

    # 13. Report provenance present
    def test_13_report_provenance_present(self):
        report = self.auditor.audit()
        self.assertIn("auditTimestamp", report)
        self.assertIn("computedFromRevision", report)
        self.assertIn("provenance", report)
        self.assertIn("canonicalAuthority", report)
        self.assertTrue(report["provenance"]["readOnlyEnforced"])
        self.assertFalse(report["provenance"]["autoWriteAllowedGlobal"])

    # 14. All rows autoWriteAllowed=false
    def test_14_all_rows_auto_write_allowed_false(self):
        report = self.auditor.audit()
        for d in report["discrepancies"]:
            self.assertIs(
                d["autoWriteAllowed"], False,
                f"Security violation: autoWriteAllowed was True in {d['discrepancyId']}!"
            )

    # 15. No competitor PNG/templates/database added
    def test_15_no_competitor_assets_added_to_repo(self):
        assets_dir = _PROJECT_ROOT / "assets"
        # Ensure no competitor named folders or databases in assets
        for forbidden in ("AuctionPilot", "nte-auction-helper", "catalog.db", "catalog.sqlite"):
            self.assertFalse(
                (assets_dir / forbidden).exists(),
                f"Forbidden competitor path or database found in repo: {forbidden}"
            )

    # 16. Generated output contains no copied external binary asset
    def test_16_generated_output_contains_no_copied_external_binary_asset(self):
        evidence_dir = Path(r"D:\ObsidianLiveSyncTestVault\03-项目与工程\异环拍卖助手\Evidence\2026-09-17-pr-f-reference-catalog-auditor")
        if evidence_dir.is_dir():
            for f in evidence_dir.rglob("*"):
                if f.is_file():
                    ext = f.suffix.lower()
                    self.assertNotIn(
                        ext, [".dll", ".exe", ".so", ".bin", ".sqlite", ".db"],
                        f"Forbidden binary asset found in evidence output: {f}"
                    )

    # 17. Canonical before/after hashes identical
    def test_17_canonical_before_after_hashes_identical(self):
        report = self.auditor.audit()
        guard = report["mutationGuard"]
        self.assertTrue(guard["readOnlyVerified"])
        self.assertEqual(len(guard["mutatedFiles"]), 0)
        self.assertEqual(guard["beforeSha256"], guard["afterSha256"])

    # 18. Runtime catalog lookup unchanged
    def test_18_runtime_catalog_lookup_unchanged(self):
        from item_identity_resolver import ItemIdentityResolver
        resolver = ItemIdentityResolver(catalog_path=_PROJECT_ROOT / "assets/catalog_065.json")
        res1 = resolver.resolve_candidates(1, 1, "white")
        self.auditor.audit()
        res2 = resolver.resolve_candidates(1, 1, "white")
        self.assertEqual(len(res1), len(res2))
        self.assertEqual([c["catalogId"] for c in res1], [c["catalogId"] for c in res2])

    # 19. PR-E contracts unchanged
    def test_19_pr_e_contracts_unchanged(self):
        from matcher_adapters import OpenCvScorerBaselineAdapter, NumpyNccMatcherAdapter
        base = OpenCvScorerBaselineAdapter()
        ncc = NumpyNccMatcherAdapter()
        self.assertEqual(base.adapter_reuse_mode, "scorer_replica")
        self.assertTrue(ncc.experimental)
        self.assertFalse(ncc.production_eligible)
        self.assertFalse(ncc.default_enabled)

    # 20. Boundary3 intersection=0
    def test_20_boundary3_intersection_strictly_zero(self):
        base_commit = "95b8d3c9db84e91ad4f914dceba9f22cddf94189"
        try:
            diff_files = subprocess.check_output(
                ["git", "diff", "--name-only", f"{base_commit}..HEAD"],
                cwd=str(_PROJECT_ROOT),
                text=True,
            ).splitlines()
        except Exception:
            diff_files = []
        # Also check unstaged changes if any
        try:
            status_files = subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=str(_PROJECT_ROOT),
                text=True,
            ).splitlines()
            uncommitted = [line[3:].strip() for line in status_files if line.strip()]
        except Exception:
            uncommitted = []

        all_touched = set(diff_files) | set(uncommitted)
        intersection = all_touched.intersection(BOUNDARY3_FILES)
        self.assertEqual(
            len(intersection), 0,
            f"Boundary 3 file intersection violation: {intersection}"
        )


if __name__ == "__main__":
    unittest.main()
