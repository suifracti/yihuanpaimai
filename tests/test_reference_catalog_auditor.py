# -*- coding: utf-8 -*-
"""Unit tests for PR-F Reference Catalog Discrepancy Auditor.

Covers all review remediation requirements:
- Review Item A: 碧波天垂 held as INDEPENDENT_VERIFICATION_REQUIRED, not promoted to genuine missing. Genuine missing = strictly confirmed 9.
- Review Item B: External cross-audit reuses local identity resolution; solver gaps have external corroboration, not duplicate REFERENCE_ONLY_UNVERIFIED; variants reuse resolution.
- Review Item C: External provenance emits sourcePathOrProvenanceRef without copying external files.
- Review Item D: Semantic Chinese character '一' preserved by normalization (not replaced with hyphen).
- Review Item E & Invariants: Cross-report identity exclusivity invariant, determinism, mutation guard, Boundary 3 intersection == 0, autoWriteAllowed = false.
"""

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
    KNOWN_SAME_ID_CONFLICTS,
    PRIOR_20260914_AUDIT_MISSING_9,
    REGRESSION_EXPECTED_20260914_MISSING_9,
    ReferenceCatalogAuditor,
    compute_canonical_hashes,
    compute_canonical_report_sha256,
    compute_file_sha256,
    get_actual_boundary3_touched_files,
    normalize_item_name,
    parse_nte_helper_source,
)


class TestReferenceCatalogAuditor(unittest.TestCase):

    def setUp(self):
        self.auditor = ReferenceCatalogAuditor(_PROJECT_ROOT)

    # 1. Content-based Deterministic Report and Hash (Review Item F)
    def test_01_deterministic_report_and_hash(self):
        report1 = self.auditor.audit()
        report2 = self.auditor.audit()
        self.assertEqual(report1["schemaVersion"], report2["schemaVersion"])
        self.assertEqual(
            report1["canonicalReportSha256"],
            report2["canonicalReportSha256"],
            "canonicalReportSha256 must be strictly deterministic across repeated audit runs",
        )
        self.assertEqual(
            report1["discrepancyStatistics"]["totalDiscrepancies"],
            report2["discrepancyStatistics"]["totalDiscrepancies"],
        )
        self.assertEqual(
            report1["inventorySummary"]["visualCoverage"]["canonicalTotal"],
            report2["inventorySummary"]["visualCoverage"]["canonicalTotal"],
        )
        self.assertEqual(len(report1["discrepancies"]), len(report2["discrepancies"]))

    # 2. Input canonical files unchanged / Mutation Guard
    def test_02_canonical_mutation_guard_identical_hashes(self):
        before = compute_canonical_hashes(_PROJECT_ROOT)
        report = self.auditor.audit()
        after = compute_canonical_hashes(_PROJECT_ROOT)
        for rel in CANONICAL_TRACKED_FILES:
            self.assertEqual(
                before[rel], after[rel],
                f"Canonical file {rel} was unexpectedly modified during audit!"
            )
        guard = report["mutationGuard"]
        self.assertTrue(guard["readOnlyVerified"])
        self.assertEqual(len(guard["mutatedFiles"]), 0)
        self.assertEqual(guard["beforeSha256"], guard["afterSha256"])

    # 3. Security invariant: all rows autoWriteAllowed=false
    def test_03_all_rows_auto_write_allowed_false(self):
        report = self.auditor.audit()
        self.assertFalse(report["provenance"]["autoWriteAllowedGlobal"])
        self.assertTrue(report["provenance"]["readOnlyEnforced"])
        for d in report["discrepancies"]:
            self.assertIs(
                d["autoWriteAllowed"], False,
                f"Security violation: autoWriteAllowed was True in {d['discrepancyId']}!"
            )
        for q in report["independentVerificationQueue"]:
            self.assertIs(
                q["autoWriteAllowed"], False,
                f"Security violation: autoWriteAllowed was True in queue item {q['discrepancyId']}!"
            )

    # 4. External-only item yields REFERENCE_ONLY_UNVERIFIED and never auto-added
    def test_04_external_only_yields_reference_only_unverified(self):
        cat_path = _PROJECT_ROOT / "assets/catalog_065.json"
        data = json.loads(cat_path.read_text(encoding="utf-8"))
        cat_names = {item["Name"] for item in data}

        report = self.auditor.audit()
        ref_only = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED
        ]
        self.assertGreater(len(ref_only), 0)
        for d in ref_only:
            self.assertEqual(d["classification"], CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED)
            self.assertFalse(d["autoWriteAllowed"])
            obs_name = d.get("referenceObservedName")
            if obs_name:
                self.assertNotIn(
                    obs_name, cat_names,
                    f"External-only item '{obs_name}' was illegally auto-added to canonical catalog!"
                )

    # 5. Footprint conflicts isolated with provenance
    def test_05_footprint_conflicts_isolated_with_provenance(self):
        report = self.auditor.audit()
        fp_conflicts = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_FOOTPRINT_CONFLICT
        ]
        self.assertGreater(len(fp_conflicts), 0)
        for d in fp_conflicts:
            self.assertEqual(d["classification"], CLASSIFICATION_FOOTPRINT_CONFLICT)
            self.assertFalse(d["autoWriteAllowed"])
            self.assertIn(d["referenceSource"], ("AuctionPilot", "nte-auction-helper"))
            self.assertIsNotNone(d["referenceValue"])

    # 6. Delete unprovenanced hardcoded historical footprint shifts (Review Item C)
    def test_06_hardcoded_historical_footprint_without_provenance_rejected(self):
        report = self.auditor.audit()
        for d in report["discrepancies"]:
            notes = d.get("notes", "")
            self.assertNotIn(
                "3x2 -> 3x3 footprint transition", notes,
                "Unprovenanced historical transition hypothesis must not be asserted as fact!"
            )
            self.assertTrue(d["referenceSource"], "Discrepancy missing reference source provenance")

    # 7. Solver alias and name conflict NOT promoted to missing (Review Item A)
    def test_07_solver_alias_and_name_conflict_not_promoted_to_missing(self):
        report = self.auditor.audit()
        unmapped_names = set(report["inventorySummary"]["solverGaps"]["unmappedNames"])

        aliases_to_check = ["咚咚锤", "储钱小啰", "巡哨一干练精英"]
        for name in aliases_to_check:
            self.assertNotIn(
                name, unmapped_names,
                f"Solver alias '{name}' was wrongly promoted to unmapped missing solver gap!"
            )

        same_id_conflicts_to_check = ["条纹椰", "浅绯祈手办", "酥酥酥天丼", "梦中萤", "圣聆晶石", "鎏金盏"]
        for name in same_id_conflicts_to_check:
            self.assertNotIn(
                name, unmapped_names,
                f"Same-ID name conflict '{name}' was wrongly promoted to unmapped missing solver gap!"
            )

        reconcil_map = {r["solverName"]: r for r in report["solverGapReconciliation"]}
        for name in aliases_to_check:
            if name in reconcil_map:
                rec = reconcil_map[name]
                self.assertIn(
                    rec["currentClassification"],
                    (CLASSIFICATION_NAME_VARIANT, "EXACT_MATCH"),
                    f"Alias '{name}' should be resolved via ladder as variant/match, got {rec['currentClassification']}",
                )

        for name in same_id_conflicts_to_check:
            if name in reconcil_map:
                rec = reconcil_map[name]
                self.assertEqual(
                    rec["currentClassification"],
                    CLASSIFICATION_ATTRIBUTE_CONFLICT,
                    f"Same-ID conflict '{name}' must be classified as ATTRIBUTE_CONFLICT, got {rec['currentClassification']}",
                )
                self.assertFalse(
                    rec.get("independentEvidenceAvailable"),
                    f"Same-ID conflict '{name}' must not claim independent evidence available",
                )
                self.assertEqual(
                    rec.get("recommendedNextEvidence"),
                    RECOMMENDED_EVIDENCE_USER_ITEM_CARD,
                    f"Same-ID conflict '{name}' recommended next evidence must be USER_ITEM_CARD",
                )

    # 8. Known 9 regression comparison explains additions/removals (Review Item A)
    def test_08_known_9_regression_comparison_explains_additions_removals(self):
        report = self.auditor.audit()
        reconcil_map = {r["solverName"]: r for r in report["solverGapReconciliation"]}

        # All 9 items from 2026-09-14 audit must be classified as SOLVER_NAMED_VISUAL_UNNAMED
        for name, expected_cat_id in PRIOR_20260914_AUDIT_MISSING_9.items():
            self.assertIn(name, reconcil_map, f"Missing known 9 audit item in reconciliation: {name}")
            rec = reconcil_map[name]
            self.assertEqual(
                rec["currentClassification"],
                CLASSIFICATION_SOLVER_NAMED_VISUAL_UNNAMED,
                f"Known 9 item '{name}' must remain classified as SOLVER_NAMED_VISUAL_UNNAMED",
            )
            self.assertEqual(
                rec["priorAuditClassification"],
                "确实缺运行时条目",
                f"Known 9 item '{name}' must be marked as '确实缺运行时条目'",
            )

    # 9. Preserve accepted latiao truth: not reopened (Review Item B)
    def test_09_accepted_latiao_truth_not_reopened(self):
        report = self.auditor.audit()
        latiao_records = [
            d for d in report["discrepancies"]
            if d.get("canonicalId") == "visual-latiao-1x2" or d.get("canonicalName") == "酷辣辣辣条"
        ]
        self.assertEqual(len(latiao_records), 1, "Expected exactly 1 accepted truth preservation record for latiao")
        latiao = latiao_records[0]
        self.assertEqual(latiao["canonicalId"], "visual-latiao-1x2")
        self.assertEqual(latiao["classification"], CLASSIFICATION_NO_ACTION)
        self.assertEqual(latiao["recommendedNextEvidence"], RECOMMENDED_EVIDENCE_NONE)
        self.assertFalse(latiao["autoWriteAllowed"])
        self.assertTrue(latiao["independentVerificationAvailable"])

        queue_ids = [q["discrepancyId"] for q in report["independentVerificationQueue"]]
        self.assertNotIn(
            latiao["discrepancyId"], queue_ids,
            "Accepted latiao canonical truth must NOT be reopened into verification queue!"
        )

    # 10. External source SHA256 included in provenance (Review Item D)
    def test_10_external_source_sha_included(self):
        report = self.auditor.audit()
        ref_sources = report["canonicalAuthority"]["referenceOnlySources"]
        self.assertGreater(len(ref_sources), 0)
        for src in ref_sources:
            if src.get("sourceAvailable"):
                sha = src.get("sourceSha256")
                self.assertIsNotNone(sha, f"Available source '{src['source']}' must have sourceSha256")
                self.assertEqual(len(sha), 64, f"Invalid SHA256 length for '{src['source']}': {sha}")

    # 11. Unavailable external source marked explicitly (Review Item D)
    def test_11_unavailable_external_source_explicit(self):
        mock_external = {
            "AuctionPilot": (
                [],
                {
                    "status": "REFERENCE_SOURCE_UNAVAILABLE",
                    "sourceAvailable": False,
                    "sourceVersion": "v0.12.7",
                    "sourcePathOrProvenanceRef": "C:/nonexistent/path/catalog.json",
                    "sourceSha256": None,
                    "parsedRecordCount": 0,
                },
            ),
            "nte-auction-helper": (
                [],
                {
                    "status": "REFERENCE_SOURCE_UNAVAILABLE",
                    "sourceAvailable": False,
                    "sourceVersion": "v1.3",
                    "sourcePathOrProvenanceRef": "C:/nonexistent/path/app.py",
                    "sourceSha256": None,
                    "parsedRecordCount": 0,
                },
            ),
        }
        report = self.auditor.audit(custom_external_sources=mock_external)
        ref_sources = {s["source"]: s for s in report["canonicalAuthority"]["referenceOnlySources"]}
        ap_src = ref_sources["AuctionPilot"]
        self.assertFalse(ap_src["sourceAvailable"])
        self.assertEqual(ap_src["status"], "REFERENCE_SOURCE_UNAVAILABLE")
        self.assertIsNone(ap_src["sourceSha256"])
        self.assertEqual(ap_src["observedItems"], 0)

    # 12. External counts dynamically parsed, not hardcoded (Review Item D)
    def test_12_external_counts_not_hardcoded(self):
        mock_items = [
            {"catalogId": "test-1", "name": "测试物品1", "quality": "white", "width": 1, "height": 1, "cells": 1, "shape": "", "value": 10},
            {"catalogId": "test-2", "name": "测试物品2", "quality": "red", "width": 2, "height": 2, "cells": 4, "shape": "", "value": 20},
        ]
        mock_external = {
            "AuctionPilot": (
                mock_items,
                {
                    "status": "AVAILABLE",
                    "sourceAvailable": True,
                    "sourceVersion": "v0.12.7-mock",
                    "sourcePathOrProvenanceRef": "mock://catalog.json",
                    "sourceSha256": "abcdef" * 10 + "abcd",
                    "parsedRecordCount": len(mock_items),
                },
            ),
        }
        report = self.auditor.audit(custom_external_sources=mock_external)
        ref_sources = {s["source"]: s for s in report["canonicalAuthority"]["referenceOnlySources"]}
        ap_src = ref_sources["AuctionPilot"]
        self.assertEqual(ap_src["observedItems"], 2)

    # 13. Content-based determinism strips volatile fields (Review Item F)
    def test_13_deterministic_full_report_hash(self):
        sample_report = {
            "schemaVersion": "v1",
            "auditTimestamp": "2026-09-17T12:00:00Z",
            "generatedAt": "2026-09-17T12:00:00Z",
            "data": [1, 2, 3],
        }
        hash1 = compute_canonical_report_sha256(sample_report)

        sample_report_time2 = copy.deepcopy(sample_report)
        sample_report_time2["auditTimestamp"] = "2026-09-17T15:30:00Z"
        sample_report_time2["generatedAt"] = "2026-09-17T15:30:00Z"
        hash2 = compute_canonical_report_sha256(sample_report_time2)
        self.assertEqual(hash1, hash2, "compute_canonical_report_sha256 must be invariant to timestamp changes")

    # 14. External source change alters audit identity (Review Item F)
    def test_14_external_source_change_changes_audit_identity(self):
        report_normal = self.auditor.audit()
        mock_items = [
            {"catalogId": "mock-diff-id", "name": "测试差异项", "quality": "gold", "width": 1, "height": 1, "cells": 1, "shape": "", "value": 99999}
        ]
        mock_external = {
            "AuctionPilot": (
                mock_items,
                {
                    "status": "AVAILABLE",
                    "sourceAvailable": True,
                    "sourceVersion": "v_modified",
                    "sourcePathOrProvenanceRef": "mock://diff.json",
                    "sourceSha256": "123456" * 10 + "1234",
                    "parsedRecordCount": len(mock_items),
                },
            ),
        }
        report_modified = self.auditor.audit(custom_external_sources=mock_external)
        self.assertNotEqual(
            report_normal["canonicalReportSha256"],
            report_modified["canonicalReportSha256"],
            "Changing external observations must alter canonicalReportSha256",
        )

    # 15. Fail-closed provenance on git failure (Review Item G)
    def test_15_fail_closed_provenance_on_git_failure(self):
        with patch("subprocess.check_output", side_effect=subprocess.SubprocessError("git not found")):
            report = self.auditor.audit()
            self.assertEqual(report["computedFromRevision"], "UNKNOWN")
            self.assertTrue(report["provenance"]["provenanceUnavailable"])

    # 16. Boundary 3 intersection using real PR #1 touched set (Review Item E)
    def test_16_actual_boundary3_touched_set_intersection(self):
        b3_head, b3_touched = get_actual_boundary3_touched_files(_PROJECT_ROOT)
        self.assertGreater(len(b3_touched), 0, "Actual Boundary 3 touched files set must not be empty")

        base_commit = "95b8d3c9db84e91ad4f914dceba9f22cddf94189"
        try:
            diff_files = subprocess.check_output(
                f"git diff --name-only {base_commit}..HEAD",
                cwd=str(_PROJECT_ROOT),
                text=True,
                shell=True,
            ).splitlines()
        except Exception:
            diff_files = []

        try:
            status_files = subprocess.check_output(
                "git status --porcelain",
                cwd=str(_PROJECT_ROOT),
                text=True,
                shell=True,
            ).splitlines()
            uncommitted = [line[3:].strip() for line in status_files if line.strip()]
        except Exception:
            uncommitted = []

        all_touched = set(f.strip() for f in diff_files if f.strip()) | set(f.strip() for f in uncommitted if f.strip())
        intersection = all_touched.intersection(set(b3_touched))
        self.assertEqual(
            len(intersection), 0,
            f"Boundary 3 real touched file intersection violation: {intersection}",
        )

    # 17. Missing visual reference detected (image2-1-1 磨刀石)
    def test_17_missing_visual_reference_detected(self):
        report = self.auditor.audit()
        missing = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_CANONICAL_VISUAL_MISSING
        ]
        self.assertGreater(len(missing), 0)
        m = [d for d in missing if d["canonicalId"] == "image2-1-1"]
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["canonicalName"], "磨刀石")
        self.assertEqual(m[0]["classification"], CLASSIFICATION_CANONICAL_VISUAL_MISSING)

    # 18. Insufficient reference separate from missing
    def test_18_insufficient_reference_separate_from_missing(self):
        report = self.auditor.audit()
        insufficient = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_VISUAL_REFERENCE_INSUFFICIENT
        ]
        self.assertGreater(len(insufficient), 0)
        for d in insufficient:
            self.assertEqual(d["classification"], CLASSIFICATION_VISUAL_REFERENCE_INSUFFICIENT)
            self.assertNotEqual(d["classification"], CLASSIFICATION_CANONICAL_VISUAL_MISSING)

    # 19. No competitor PNG/templates/database added to repo or output
    def test_19_no_competitor_binary_or_png_assets(self):
        assets_dir = _PROJECT_ROOT / "assets"
        for forbidden in ("AuctionPilot", "nte-auction-helper", "catalog.db", "catalog.sqlite"):
            self.assertFalse(
                (assets_dir / forbidden).exists(),
                f"Forbidden competitor path or database found in repo: {forbidden}"
            )
        evidence_dir = Path(r"D:\ObsidianLiveSyncTestVault\03-项目与工程\异环拍卖助手\Evidence\2026-09-17-pr-f-reference-catalog-auditor")
        if evidence_dir.is_dir():
            for f in evidence_dir.rglob("*"):
                if f.is_file():
                    ext = f.suffix.lower()
                    self.assertNotIn(
                        ext, [".dll", ".exe", ".so", ".bin", ".sqlite", ".db"],
                        f"Forbidden binary asset found in evidence output: {f}"
                    )

    # 20. Runtime catalog lookup unchanged and PR-E contracts preserved
    def test_20_runtime_catalog_lookup_and_contracts_unchanged(self):
        from item_identity_resolver import ItemIdentityResolver
        resolver = ItemIdentityResolver(catalog_path=_PROJECT_ROOT / "assets/catalog_065.json")
        res1 = resolver.resolve_candidates(1, 1, "white")
        self.auditor.audit()
        res2 = resolver.resolve_candidates(1, 1, "white")
        self.assertEqual(len(res1), len(res2))
        self.assertEqual([c["catalogId"] for c in res1], [c["catalogId"] for c in res2])

        from matcher_adapters import OpenCvScorerBaselineAdapter, NumpyNccMatcherAdapter
        base = OpenCvScorerBaselineAdapter()
        ncc = NumpyNccMatcherAdapter()
        self.assertEqual(base.adapter_reuse_mode, "scorer_replica")
        self.assertTrue(ncc.experimental)
        self.assertFalse(ncc.production_eligible)
        self.assertFalse(ncc.default_enabled)

    # 21. Discrepancy IDs unique and deterministic
    def test_21_discrepancy_ids_unique_and_deterministic(self):
        report = self.auditor.audit()
        disc_ids = [d["discrepancyId"] for d in report["discrepancies"]]
        self.assertEqual(len(disc_ids), len(set(disc_ids)), "Found duplicate discrepancy IDs!")
        for did in disc_ids:
            self.assertTrue(did.startswith("disc-"), f"Invalid discrepancyId format: {did}")

    # 22. Review Item A: 碧波天垂 cannot be promoted to 10th genuine missing
    def test_22_bibotianchui_not_promoted_to_genuine_missing(self):
        report = self.auditor.audit()
        # Genuine missing count must be strictly 9
        unmapped_count = report["inventorySummary"]["solverGaps"]["unmappedVisualGapsCount"]
        self.assertEqual(
            unmapped_count, 9,
            f"Genuine missing count must strictly equal 9 confirmed items, got {unmapped_count}"
        )
        unmapped_names = report["inventorySummary"]["solverGaps"]["unmappedNames"]
        self.assertNotIn(
            "碧波天垂", unmapped_names,
            "碧波天垂 must not be included in genuine unmapped visual gaps!"
        )
        self.assertEqual(sorted(unmapped_names), sorted(list(PRIOR_20260914_AUDIT_MISSING_9.keys())))

        # 碧波天垂 must be classified as INDEPENDENT_VERIFICATION_REQUIRED with USER_ITEM_CARD
        reconcil_map = {r["solverName"]: r for r in report["solverGapReconciliation"]}
        self.assertIn("碧波天垂", reconcil_map)
        bibo = reconcil_map["碧波天垂"]
        self.assertEqual(bibo["currentClassification"], CLASSIFICATION_INDEPENDENT_VERIFICATION_REQUIRED)
        self.assertEqual(bibo["recommendedNextEvidence"], RECOMMENDED_EVIDENCE_USER_ITEM_CARD)
        self.assertEqual(bibo["priorAuditClassification"], "证据不足，暂不处理")
        self.assertTrue(bibo["priorAuditSource"].endswith("2026-09-14-runtime-visual-catalog-diff.json"))
        self.assertIsNotNone(bibo["priorAuditSha256"])

        # Must be in verification queue
        queue_names = [q.get("canonicalName") for q in report["independentVerificationQueue"]]
        self.assertIn("碧波天垂", queue_names)

    # 23. Review Item B: Solver-known external observation not reference-only
    def test_23_solver_known_external_observation_not_reference_only(self):
        report = self.auditor.audit()
        ref_only_names = {
            d.get("referenceObservedName")
            for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED
        }
        for name in PRIOR_20260914_AUDIT_MISSING_9.keys():
            self.assertNotIn(
                name, ref_only_names,
                f"Solver gap item '{name}' was wrongly emitted as REFERENCE_ONLY_UNVERIFIED!"
            )
        self.assertNotIn(
            "碧波天垂", ref_only_names,
            "碧波天垂 must not be emitted as REFERENCE_ONLY_UNVERIFIED!"
        )
        self.assertNotIn(
            "碧波天玺", ref_only_names,
            "碧波天玺 must not be emitted as REFERENCE_ONLY_UNVERIFIED!"
        )

    # 24. Review Item B: Same-ID variant external observation reuses identity resolution
    def test_24_same_id_variant_external_observation_reuses_identity_resolution(self):
        report = self.auditor.audit()
        ref_only_names = {
            d.get("referenceObservedName")
            for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED
        }
        for variant in ("条纹椰", "浅绯祈手办", "酥酥酥天丼"):
            self.assertNotIn(
                variant, ref_only_names,
                f"Known variant '{variant}' was wrongly emitted as REFERENCE_ONLY_UNVERIFIED!"
            )

    # 25. Review Item B: Confirmed solver gaps have external corroboration attached
    def test_25_confirmed_solver_gap_can_have_external_corroboration(self):
        report = self.auditor.audit()
        reconcil_map = {r["solverName"]: r for r in report["solverGapReconciliation"]}
        # Verify that solver gaps present in AuctionPilot (like 超级存储盘) have corroboratingReferences
        for name in ("超级存储盘", "曜目权柄", "他山之石", "崭新限量排球", "鸣佩"):
            rec = reconcil_map.get(name)
            self.assertIsNotNone(rec, f"Missing solver reconciliation row for {name}")
            corrob = rec.get("corroboratingReferences", [])
            self.assertGreater(
                len(corrob), 0,
                f"Expected external corroboration for solver gap '{name}' from AuctionPilot"
            )
            c0 = corrob[0]
            self.assertIn("source", c0)
            self.assertIn("version", c0)
            self.assertIn("sourceSha256", c0)
            self.assertIn("sourcePathOrProvenanceRef", c0)
            self.assertEqual(c0["observedName"], name)

    # 26. Review Items B & E: Cross-report identity exclusivity invariant
    def test_26_cross_report_identity_exclusivity_invariant(self):
        report = self.auditor.audit()
        solver_gap_names = {
            d.get("canonicalName")
            for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_SOLVER_NAMED_VISUAL_UNNAMED
        }
        ref_only_names = {
            d.get("referenceObservedName")
            for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED
        }
        overlap = solver_gap_names.intersection(ref_only_names)
        self.assertEqual(
            len(overlap), 0,
            f"Mutually exclusive classification violation: items {overlap} have both SOLVER_NAMED_VISUAL_UNNAMED and REFERENCE_ONLY_UNVERIFIED!"
        )

    # 27. Review Item C: External provenance emits sourcePathOrProvenanceRef
    def test_27_external_provenance_ref_emitted(self):
        report = self.auditor.audit()
        ref_sources = report["canonicalAuthority"]["referenceOnlySources"]
        for src in ref_sources:
            self.assertIn("sourcePathOrProvenanceRef", src)
            if src.get("sourceAvailable"):
                self.assertTrue(
                    len(src["sourcePathOrProvenanceRef"]) > 0,
                    f"Available source {src['source']} missing sourcePathOrProvenanceRef"
                )

    # 28. Review Item D: Semantic Chinese character not destroyed by normalization
    def test_28_semantic_chinese_character_not_destroyed_by_normalization(self):
        # '一' is a meaningful Chinese character (e.g. 一簇幽火, 一心一意) and must not be replaced by hyphen
        res = normalize_item_name("一簇幽火")
        self.assertEqual(
            res, "一簇幽火",
            f"Normalization illegally altered Chinese character '一': got '{res}'"
        )
        self.assertNotIn("-", res)

    # 29. Blocker 1: NTE parser includes both gold and red sections
    def test_nte_parser_includes_gold_and_red_sections(self):
        sample_nte = """
# Gold section
PRICES = [
    100, 200
]
GOLD_SIZES = ["1x1", "1x2"]
GOLD_DIMENSIONS = [
    (1, 1), (1, 2)
]
GOLD_NAMES = [
    "金物品1", "金物品2"
]
ERROR_MARGIN = 0.05

# Red section
RED_PRICES_ALL = [
    300, 400, 500
]
RED_SIZES = ["2x2", "2x3", "3x3"]
RED_DIMENSIONS_ALL = [
    (2, 2), (2, 3), (3, 3)
]
RED_NAMES_ALL = [
    "红物品1", "红物品2", "红物品3"
]
RED_PRICES = [300, 400, 500]
"""
        items, meta = parse_nte_helper_source(sample_nte, "test://app.py", "mocksha")
        self.assertTrue(meta["goldSectionFound"])
        self.assertTrue(meta["redSectionFound"])
        self.assertEqual(meta["goldParsedCount"], 2)
        self.assertEqual(meta["redParsedCount"], 3)
        self.assertEqual(meta["parsedRecordCount"], 5)
        self.assertEqual(len(items), 5)
        self.assertTrue(meta["parseComplete"])
        self.assertEqual(len(meta["parseWarnings"]), 0)

        self.assertEqual(items[0]["name"], "金物品1")
        self.assertEqual(items[0]["quality"], "gold")
        self.assertEqual(items[2]["name"], "红物品1")
        self.assertEqual(items[2]["quality"], "red")

        # Also test on real NTE app.py if present
        nte_app_path = Path(r"C:\Users\Administrator\.grok\tmp\nte-auction-helper\app.py")
        if nte_app_path.is_file():
            real_items, real_meta = parse_nte_helper_source(
                nte_app_path.read_text(encoding="utf-8"),
                str(nte_app_path),
                compute_file_sha256(nte_app_path),
            )
            self.assertTrue(real_meta["goldSectionFound"])
            self.assertTrue(real_meta["redSectionFound"])
            self.assertEqual(real_meta["goldParsedCount"], 50)
            self.assertEqual(real_meta["redParsedCount"], 30)
            self.assertEqual(real_meta["parsedRecordCount"], 80)
            self.assertTrue(real_meta["parseComplete"])
            self.assertEqual(len(real_meta["parseWarnings"]), 0)

    # 30. Blocker 1: NTE parser count is dynamic, not hardcoded
    def test_nte_parser_count_is_dynamic(self):
        sample_nte = """
PRICES = [ 999 ]
GOLD_SIZES = ["1x1"]
GOLD_DIMENSIONS = [ (1, 1) ]
GOLD_NAMES = [ "单金" ]
ERROR_MARGIN = 0.05
RED_PRICES_ALL = [ 888, 777 ]
RED_SIZES = ["2x2", "3x3"]
RED_DIMENSIONS_ALL = [ (2, 2), (3, 3) ]
RED_NAMES_ALL = [ "单红1", "单红2" ]
RED_PRICES = [ 888, 777 ]
"""
        items, meta = parse_nte_helper_source(sample_nte, "test://dynamic.py")
        self.assertEqual(meta["goldParsedCount"], 1)
        self.assertEqual(meta["redParsedCount"], 2)
        self.assertEqual(meta["parsedRecordCount"], 3)
        self.assertEqual(len(items), 3)
        self.assertNotIn(meta["parsedRecordCount"], (50, 30, 80))

    # 31. Blocker 1: NTE incomplete or mismatched section reports warnings safely
    def test_nte_incomplete_section_reports_warning(self):
        # Missing red section
        gold_only = """
PRICES = [ 100 ]
GOLD_SIZES = ["1x1"]
GOLD_DIMENSIONS = [ (1, 1) ]
GOLD_NAMES = [ "金物品" ]
ERROR_MARGIN = 0.05
"""
        items, meta = parse_nte_helper_source(gold_only, "test://gold_only.py")
        self.assertTrue(meta["goldSectionFound"])
        self.assertFalse(meta["redSectionFound"])
        self.assertEqual(meta["goldParsedCount"], 1)
        self.assertEqual(meta["redParsedCount"], 0)
        self.assertFalse(meta["parseComplete"])
        self.assertGreater(len(meta["parseWarnings"]), 0)

        # Length mismatch in gold section (2 prices, 1 name)
        mismatched = """
PRICES = [ 100, 200 ]
GOLD_SIZES = ["1x1"]
GOLD_DIMENSIONS = [ (1, 1) ]
GOLD_NAMES = [ "金物品" ]
ERROR_MARGIN = 0.05
RED_PRICES_ALL = [ 300 ]
RED_SIZES = ["2x2"]
RED_DIMENSIONS_ALL = [ (2, 2) ]
RED_NAMES_ALL = [ "红物品" ]
RED_PRICES = [ 300 ]
"""
        items2, meta2 = parse_nte_helper_source(mismatched, "test://mismatch.py")
        self.assertFalse(meta2["parseComplete"])
        self.assertTrue(any("mismatch" in w.lower() for w in meta2["parseWarnings"]))

    # 32. Blocker 2: Same-ID conflict not promoted to confirmed alias
    def test_same_id_conflict_not_promoted_to_confirmed_alias(self):
        for name in ("条纹椰", "浅绯祈手办", "酥酥酥天丼", "梦中萤", "圣聆晶石", "鎏金盏"):
            res = self.auditor.resolve_local_identity(name)
            self.assertEqual(
                res["resolutionClass"],
                CLASSIFICATION_ATTRIBUTE_CONFLICT,
                f"Same-ID conflict item '{name}' must resolve to ATTRIBUTE_CONFLICT, got {res['resolutionClass']}",
            )
            self.assertIsNone(res.get("aliasMatch"), f"Same-ID conflict '{name}' must not have aliasMatch")
            self.assertIsNotNone(res.get("conflictCanonicalId"), f"Same-ID conflict '{name}' must have conflictCanonicalId")
            self.assertIsNotNone(res.get("conflictCanonicalName"), f"Same-ID conflict '{name}' must have conflictCanonicalName")

        # In report reconciliation, check that none are marked NAME_VARIANT or SOLVER_NAMED_VISUAL_UNNAMED
        report = self.auditor.audit()
        reconcil_map = {r["solverName"]: r for r in report["solverGapReconciliation"]}
        for name in ("条纹椰", "浅绯祈手办", "酥酥酥天丼"):
            rec = reconcil_map.get(name)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["currentClassification"], CLASSIFICATION_ATTRIBUTE_CONFLICT)
            self.assertFalse(rec["independentEvidenceAvailable"])
            self.assertEqual(rec["recommendedNextEvidence"], RECOMMENDED_EVIDENCE_USER_ITEM_CARD)
            self.assertNotEqual(rec["currentClassification"], CLASSIFICATION_NAME_VARIANT)
            self.assertNotEqual(rec["currentClassification"], CLASSIFICATION_SOLVER_NAMED_VISUAL_UNNAMED)

    # 33. Blocker 2: Same-ID conflict in external observation not emitted as REFERENCE_ONLY_UNVERIFIED
    def test_same_id_conflict_not_external_only(self):
        report = self.auditor.audit()
        ref_only_names = {
            d.get("referenceObservedName")
            for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED
        }
        for name in ("条纹椰", "浅绯祈手办", "酥酥酥天丼", "梦中萤", "圣聆晶石", "鎏金盏"):
            self.assertNotIn(
                name, ref_only_names,
                f"Same-ID conflict '{name}' was illegally emitted as REFERENCE_ONLY_UNVERIFIED!",
            )

        conflict_discs = [
            d for d in report["discrepancies"]
            if d["classification"] == CLASSIFICATION_ATTRIBUTE_CONFLICT
        ]
        conflict_names = {d.get("referenceObservedName") for d in conflict_discs}
        self.assertIn("条纹椰", conflict_names)
        self.assertIn("浅绯祈手办", conflict_names)
        self.assertIn("酥酥酥天丼", conflict_names)
        for cd in conflict_discs:
            self.assertFalse(cd["autoWriteAllowed"])
            self.assertFalse(cd["independentVerificationAvailable"])
            self.assertEqual(cd["recommendedNextEvidence"], RECOMMENDED_EVIDENCE_USER_ITEM_CARD)

    # 34. Blocker 2: Verified registry alias resolves when real authority exists
    def test_verified_registry_alias_can_resolve_when_real_authority_exists(self):
        # 1. Authority from solver/registry alias
        res_hammer = self.auditor.resolve_local_identity("咚咚锤")
        self.assertEqual(res_hammer["resolutionClass"], CLASSIFICATION_NAME_VARIANT)
        self.assertIsNotNone(res_hammer.get("aliasMatch"))
        self.assertIn("吨吨锤", res_hammer["aliasMatch"].get("aliasTarget", ""))

        # 2. Authority from verified card registry alternate names
        self.auditor._ensure_indexes_built()
        self.auditor._indexes["card_reg_by_alt_name"]["权威别名测试项"] = [{
            "name": "权威正名测试项",
            "catalogId": "test-authority-id",
        }]
        res_reg = self.auditor.resolve_local_identity("权威别名测试项")
        self.assertEqual(res_reg["resolutionClass"], CLASSIFICATION_NAME_VARIANT)
        self.assertIsNotNone(res_reg.get("aliasMatch"))
        self.assertEqual(res_reg["aliasMatch"].get("source"), "verified_source_card_registry.alternateNames")
        self.assertEqual(res_reg["aliasMatch"].get("canonicalId"), "test-authority-id")

        # 3. Same-ID conflict does NOT resolve as alias authority
        res_conflict = self.auditor.resolve_local_identity("条纹椰")
        self.assertEqual(res_conflict["resolutionClass"], CLASSIFICATION_ATTRIBUTE_CONFLICT)
        self.assertIsNone(res_conflict.get("aliasMatch"))

    # 35. Blocker 3: Prior missing set dynamically derived from prior audit rows
    def test_prior_missing_set_derived_from_prior_audit_rows(self):
        report = self.auditor.audit()
        gaps = report["inventorySummary"]["solverGaps"]
        self.assertTrue(gaps["priorAuditAvailable"])
        self.assertEqual(gaps["priorConfirmedMissingDerivedCount"], 9)
        self.assertEqual(len(gaps["priorConfirmedMissingDerivedNames"]), 9)
        self.assertEqual(gaps["regressionExpectedCount"], 9)
        self.assertTrue(gaps["regressionSetMatches"])

        expected_names = set(REGRESSION_EXPECTED_20260914_MISSING_9.keys())
        derived_names = set(gaps["priorConfirmedMissingDerivedNames"])
        self.assertEqual(derived_names, expected_names)

        reconcil_map = {r["solverName"]: r for r in report["solverGapReconciliation"]}
        for name in derived_names:
            self.assertIn(name, reconcil_map)
            self.assertEqual(reconcil_map[name]["currentClassification"], CLASSIFICATION_SOLVER_NAMED_VISUAL_UNNAMED)
            self.assertEqual(reconcil_map[name]["priorAuditClassification"], "确实缺运行时条目")

    # 36. Blocker 3: Prior audit unavailable fails closed without falling back to hardcoded 9
    def test_prior_audit_unavailable_does_not_fallback_to_hardcoded_truth(self):
        nonexistent = _PROJECT_ROOT / "docs/reports/nonexistent_audit.json"
        auditor_no_prior = ReferenceCatalogAuditor(_PROJECT_ROOT, prior_audit_path=nonexistent)
        report = auditor_no_prior.audit()
        gaps = report["inventorySummary"]["solverGaps"]

        self.assertFalse(gaps["priorAuditAvailable"])
        self.assertEqual(gaps["priorConfirmedMissingDerivedCount"], 0)
        self.assertEqual(len(gaps["priorConfirmedMissingDerivedNames"]), 0)
        self.assertFalse(gaps["regressionSetMatches"])

        # Fail-closed: unmapped visual gaps must NOT fall back to 9
        self.assertEqual(
            gaps["unmappedVisualGapsCount"], 0,
            "Without prior audit authority, unmapped visual gaps must not fall back to hardcoded 9!",
        )

        reconcil_map = {r["solverName"]: r for r in report["solverGapReconciliation"]}
        for name in REGRESSION_EXPECTED_20260914_MISSING_9.keys():
            self.assertIn(name, reconcil_map)
            self.assertEqual(
                reconcil_map[name]["currentClassification"],
                CLASSIFICATION_INDEPENDENT_VERIFICATION_REQUIRED,
                f"Item '{name}' should fail closed to INDEPENDENT_VERIFICATION_REQUIRED when prior audit unavailable",
            )

    # 37. Blocker 3: REGRESSION_EXPECTED_20260914_MISSING_9 is strictly check-only, not authority
    def test_regression_constant_is_check_only_not_authority(self):
        import tempfile
        mock_data = {
            "rows": [
                {"theirsName": "崭新限量排球", "theirsId": "theirs-1", "conclusion": "确实缺运行时条目", "recommendedResolution": "RECOVER_CANDIDATE"},
                {"theirsName": "曜目权柄", "theirsId": "theirs-2", "conclusion": "确实缺运行时条目", "recommendedResolution": "RECOVER_CANDIDATE"},
                {"theirsName": "碧波天垂", "theirsId": "theirs-3", "conclusion": "证据不足，暂不处理", "recommendedResolution": "VERIFY_USER_CARD"},
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(mock_data, f, ensure_ascii=False)
            tmp_path = Path(f.name)

        try:
            custom_auditor = ReferenceCatalogAuditor(_PROJECT_ROOT, prior_audit_path=tmp_path)
            report = custom_auditor.audit()
            gaps = report["inventorySummary"]["solverGaps"]

            self.assertTrue(gaps["priorAuditAvailable"])
            self.assertEqual(gaps["priorConfirmedMissingDerivedCount"], 2)
            self.assertEqual(sorted(gaps["priorConfirmedMissingDerivedNames"]), ["崭新限量排球", "曜目权柄"])
            self.assertFalse(gaps["regressionSetMatches"])
            self.assertEqual(gaps["regressionExpectedCount"], 9)

            unmapped = gaps["unmappedNames"]
            self.assertEqual(len(unmapped), 2)
            self.assertEqual(sorted(unmapped), ["崭新限量排球", "曜目权柄"])
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    # 38. Blocker: same-ID conflict + observed_id precedence (one truth, one classification)
    def test_same_id_conflict_with_observed_id_remains_attribute_conflict(self):
        # Explicit assertions required by the review: passing the observed_id must NOT
        # change the classification of a same-ID conflict into NAME_VARIANT.
        self.assertEqual(
            self.auditor.resolve_local_identity("条纹椰", "image26-1-1")["resolutionClass"],
            CLASSIFICATION_ATTRIBUTE_CONFLICT,
        )
        self.assertEqual(
            self.auditor.resolve_local_identity("浅绯祈手办", "image27-1-0")["resolutionClass"],
            CLASSIFICATION_ATTRIBUTE_CONFLICT,
        )

        same_id_cases = [
            ("条纹椰", "image26-1-1"),
            ("浅绯祈手办", "image27-1-0"),
            ("酥酥酥天丼", "image36-0-1"),
            ("梦中萤", "image7-1-2"),
            ("圣聆晶石", "image22-0-0"),
            ("鎏金盏", "image9-1-2"),
        ]
        for name, observed_id in same_id_cases:
            with_id = self.auditor.resolve_local_identity(name, observed_id)
            name_only = self.auditor.resolve_local_identity(name)

            self.assertEqual(
                with_id["resolutionClass"],
                CLASSIFICATION_ATTRIBUTE_CONFLICT,
                f"Same-ID conflict '{name}' with observed_id '{observed_id}' must stay ATTRIBUTE_CONFLICT, "
                f"got {with_id['resolutionClass']}",
            )
            self.assertEqual(
                with_id["resolutionClass"],
                name_only["resolutionClass"],
                f"Same truth '{name}' must not classify differently by entry point: "
                f"observed_id -> {with_id['resolutionClass']} vs name-only -> {name_only['resolutionClass']}",
            )
            self.assertNotEqual(with_id["resolutionClass"], CLASSIFICATION_NAME_VARIANT)
            self.assertNotEqual(with_id["resolutionClass"], CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED)

            # No alias authority is granted by the shared catalog ID alone
            self.assertIsNone(with_id.get("aliasMatch"))
            self.assertEqual(with_id.get("conflictCanonicalId"), observed_id)
            self.assertIsNotNone(with_id.get("conflictCanonicalName"))

            # Conflict rows fail closed: no independent evidence, user item card required
            self.assertFalse(with_id.get("independentEvidenceAvailable"))
            self.assertEqual(with_id.get("recommendedNextEvidence"), RECOMMENDED_EVIDENCE_USER_ITEM_CARD)

    # 39. Blocker: AuctionPilot same-ID conflict reuses ATTRIBUTE_CONFLICT at report level
    def test_auctionpilot_same_id_conflict_reuses_attribute_conflict(self):
        report = self.auditor.audit()

        ap_conflicts = [
            d for d in report["discrepancies"]
            if d["referenceSource"] == "AuctionPilot"
            and d["classification"] == CLASSIFICATION_ATTRIBUTE_CONFLICT
        ]
        ap_conflict_names = {d.get("referenceObservedName") for d in ap_conflicts}
        self.assertIn("条纹椰", ap_conflict_names)
        self.assertIn("浅绯祈手办", ap_conflict_names)
        for d in ap_conflicts:
            self.assertFalse(d["autoWriteAllowed"])
            self.assertFalse(d["independentVerificationAvailable"])
            self.assertEqual(d["recommendedNextEvidence"], RECOMMENDED_EVIDENCE_USER_ITEM_CARD)

        # The same-ID conflicts must never surface as NAME_VARIANT or REFERENCE_ONLY_UNVERIFIED
        for d in report["discrepancies"]:
            if d.get("referenceObservedName") in ("条纹椰", "浅绯祈手办"):
                self.assertNotEqual(
                    d["classification"], CLASSIFICATION_NAME_VARIANT,
                    f"AuctionPilot same-ID conflict '{d.get('referenceObservedName')}' must not be NAME_VARIANT",
                )
                self.assertNotEqual(
                    d["classification"], CLASSIFICATION_REFERENCE_ONLY_UNVERIFIED,
                    f"AuctionPilot same-ID conflict '{d.get('referenceObservedName')}' must not be REFERENCE_ONLY_UNVERIFIED",
                )

        # A lexical/OCR variant with no conflict evidence anywhere must still fall back to
        # NAME_VARIANT. The ID is derived dynamically so the assertion stays tied to real data.
        self.auditor._ensure_indexes_built()
        idx = self.auditor._indexes
        known_conflict_ids = {v[0] for v in KNOWN_SAME_ID_CONFLICTS.values()}
        probe_id = None
        for cid in sorted(idx["cat065_by_id"]):
            if cid in known_conflict_ids:
                continue
            name = idx["cat065_by_id"][cid]["Name"]
            prior_rows = [
                idx["prior_audit_entries"].get(cid),
                idx["prior_audit_entries"].get(name),
                idx["prior_audit_entries"].get(normalize_item_name(name)),
            ]
            if any(r and r.get("conclusion") == "属性冲突，待源卡裁定" for r in prior_rows):
                continue
            probe_id = cid
            break
        self.assertIsNotNone(probe_id, "Expected at least one canonical ID without same-ID conflict evidence")
        probe_name = idx["cat065_by_id"][probe_id]["Name"] + "·异体字"
        res_variant = self.auditor.resolve_local_identity(probe_name, probe_id)
        self.assertEqual(
            res_variant["resolutionClass"], CLASSIFICATION_NAME_VARIANT,
            f"Exact ID + different name without conflict evidence must stay NAME_VARIANT, got {res_variant['resolutionClass']}",
        )
        self.assertIsNotNone(res_variant.get("canonicalMatch"))
        self.assertIsNone(res_variant.get("conflictCanonicalId"))

    # 40. Blocker: genuine verified same-ID alias authority still allows NAME_VARIANT
    def test_verified_same_id_alias_authority_still_allows_name_variant(self):
        self.auditor._ensure_indexes_built()
        # Inject a genuine verified source-card registry alternate name bound to the SAME catalog ID
        self.auditor._indexes["card_reg_by_alt_name"]["权威同ID别名测试项"] = [{
            "name": "权威同ID正名",
            "catalogId": "image26-1-1",
        }]
        res = self.auditor.resolve_local_identity("权威同ID别名测试项", "image26-1-1")
        self.assertEqual(res["resolutionClass"], CLASSIFICATION_NAME_VARIANT)
        self.assertIsNotNone(res.get("aliasMatch"))
        self.assertEqual(res["aliasMatch"].get("source"), "verified_source_card_registry.alternateNames")
        self.assertEqual(res["aliasMatch"].get("canonicalId"), "image26-1-1")
        self.assertIsNone(res.get("conflictCanonicalId"))

        # The real same-ID conflict is unaffected: authority must be explicit, not inferred from the ID
        self.assertEqual(
            self.auditor.resolve_local_identity("条纹椰", "image26-1-1")["resolutionClass"],
            CLASSIFICATION_ATTRIBUTE_CONFLICT,
        )


if __name__ == "__main__":
    unittest.main()
