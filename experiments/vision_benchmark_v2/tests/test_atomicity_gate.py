# -*- coding: utf-8 -*-
"""Atomicity review admission matrix and non-bypass regressions."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCHMARK_DIR.parents[1]
ATOMICITY_REVIEW = BENCHMARK_DIR / "atomicity_review_v1.json"
SINGLE_GROUPING = BENCHMARK_DIR / "fixtures" / "grouping_review_single_v1.json"
MULTI_GROUPING = BENCHMARK_DIR / "fixtures" / "grouping_review_multi_v1.json"
SPLIT_GROUPING = BENCHMARK_DIR / "fixtures" / "grouping_review_split_children_v1.json"
SINGLE_ADMISSION = BENCHMARK_DIR / "fixtures" / "reviewed_single_parent_v1.json"
MULTI_ADMISSION = BENCHMARK_DIR / "fixtures" / "reviewed_multi_parent_v1.json"
SPLIT_ADMISSION = BENCHMARK_DIR / "fixtures" / "reviewed_split_upper_parent_v1.json"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _load_module("benchmark_v2_adapter_atomicity_tests", BENCHMARK_DIR / "adapter.py")
BOUNDARY = _load_module("benchmark_v2_proposal_boundary_atomicity_tests", BENCHMARK_DIR / "proposal_boundary.py")
ATOMICITY = _load_module("benchmark_v2_atomicity_review_tests", BENCHMARK_DIR / "atomicity_review.py")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestAtomicityAdmissionGate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-atomicity-", dir=BENCHMARK_DIR)
        self.temp_dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write_json(self, name, payload):
        path = self.temp_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _fixture_for_grouping(self, grouping, *, base=SINGLE_ADMISSION, selected_group_id=None, name="case"):
        grouping_path = self._write_json(f"{name}-grouping.json", grouping)
        fixture = _read(base)
        fixture["groupingReview"] = {
            "path": grouping_path.relative_to(REPO_ROOT).as_posix(),
            "expectedSha256": BOUNDARY.sha256_file(grouping_path),
            "selectedGroupId": selected_group_id or grouping["groups"][0]["groupId"],
        }
        return self._write_json(f"{name}-admission.json", fixture)

    def _grouping_with_atomicity(self, grouping, atomicity, *, name):
        atomicity_path = self._write_json(f"{name}-atomicity.json", atomicity)
        grouping["atomicityReviewPath"] = atomicity_path.relative_to(REPO_ROOT).as_posix()
        grouping["atomicityReviewHash"] = BOUNDARY.sha256_file(atomicity_path)
        return grouping

    @staticmethod
    def _set_classification(atomicity, proposal_id, classification, review_status="reviewed_consistent"):
        record = next(review for review in atomicity["reviews"] if review["proposalId"] == proposal_id)
        record["atomicityClassification"] = classification
        record["reviewStatus"] = review_status

    @staticmethod
    def _single_group_for(proposal_id, bbox):
        grouping = _read(SINGLE_GROUPING)
        group = grouping["groups"][0]
        group["memberProposalIds"] = [proposal_id]
        group["resolvedParentBbox"] = bbox
        group["bboxDerivation"] = "proposal_bbox"
        group["resolutionMethod"] = "single_proposal"
        return grouping

    def test_1_missing_atomicity_review_fails(self):
        grouping = _read(SINGLE_GROUPING)
        del grouping["atomicityReviewPath"]
        del grouping["atomicityReviewHash"]
        fixture = self._fixture_for_grouping(grouping, name="missing-review")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "missing-review-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_ATOMICITY_REVIEW_REQUIRED")

    def test_2_atomic_clear_single_path_passes(self):
        result = ADAPTER.run_slice(SINGLE_ADMISSION, self.temp_dir / "atomic-clear", repo_root=REPO_ROOT)
        provenance = result["sourceRecord"]["proposalProvenance"]
        self.assertEqual(
            provenance["atomicityClassifications"],
            {"proposal-57f0e84c5467469bce38": "ATOMIC_CLEAR"},
        )
        self.assertEqual(result["queue"]["admissionStatus"], "PASS")

    def test_3_fragment_cannot_use_direct_single_admission(self):
        grouping = self._single_group_for("proposal-3f6968ebc9be50c2e62d", [0, 0, 31, 33])
        fixture = self._fixture_for_grouping(grouping, name="fragment-single")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "fragment-single-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_ATOMICITY_SINGLE_REQUIRES_CLEAR")

    def test_4_reviewed_fragments_grouping_path_passes(self):
        result = ADAPTER.run_slice(MULTI_ADMISSION, self.temp_dir / "fragments-group", repo_root=REPO_ROOT)
        classifications = set(result["sourceRecord"]["proposalProvenance"]["atomicityClassifications"].values())
        self.assertEqual(classifications, {"FRAGMENT_OF_ONE_PARENT"})
        self.assertEqual(result["queue"]["admissionStatus"], "PASS")

    def test_5_each_unsplit_mixed_proposal_is_blocked(self):
        mixed = {
            "proposal-5fcee11df94349a175a4": [184, 33, 215, 132],
            "proposal-ab6e10659fa202f3aba3": [215, 33, 246, 132],
            "proposal-1b68b91599db03d3c32a": [276, 66, 307, 164],
        }
        for index, (proposal_id, bbox) in enumerate(mixed.items()):
            with self.subTest(proposal_id=proposal_id):
                grouping = self._single_group_for(proposal_id, bbox)
                fixture = self._fixture_for_grouping(grouping, name=f"mixed-{index}")
                with self.assertRaises(ADAPTER.AdapterError) as caught:
                    ADAPTER.run_slice(fixture, self.temp_dir / f"mixed-{index}-output", repo_root=REPO_ROOT)
                self.assertEqual(caught.exception.code, "E_ATOMICITY_SPLIT_REQUIRED")

    def test_6_mixed_with_approved_valid_split_passes(self):
        result = ADAPTER.run_slice(SPLIT_ADMISSION, self.temp_dir / "approved-split", repo_root=REPO_ROOT)
        classifications = result["sourceRecord"]["proposalProvenance"]["atomicityClassifications"]
        self.assertEqual(classifications, {"proposal-44d473f3458cff319236": "MIXED_MULTI_PARENT"})
        self.assertEqual(result["queue"]["admissionStatus"], "PASS")

    def test_7_ambiguous_fails_closed(self):
        atomicity = _read(ATOMICITY_REVIEW)
        self._set_classification(atomicity, "proposal-57f0e84c5467469bce38", "AMBIGUOUS")
        grouping = self._grouping_with_atomicity(_read(SINGLE_GROUPING), atomicity, name="ambiguous")
        fixture = self._fixture_for_grouping(grouping, name="ambiguous")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "ambiguous-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_ATOMICITY_BLOCKED_CLASS")

    def test_8_background_or_noise_fails_closed(self):
        atomicity = _read(ATOMICITY_REVIEW)
        self._set_classification(atomicity, "proposal-57f0e84c5467469bce38", "BACKGROUND_OR_NOISE")
        grouping = self._grouping_with_atomicity(_read(SINGLE_GROUPING), atomicity, name="background")
        fixture = self._fixture_for_grouping(grouping, name="background")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "background-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_ATOMICITY_BLOCKED_CLASS")

    def test_9_atomicity_review_artifact_hash_mismatch_fails(self):
        grouping = _read(SINGLE_GROUPING)
        grouping["atomicityReviewHash"] = "0" * 64
        fixture = self._fixture_for_grouping(grouping, name="review-hash")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "review-hash-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_ATOMICITY_REVIEW_HASH")

    def test_10_no_existing_adapter_path_can_omit_the_gate(self):
        cases = (
            (SINGLE_GROUPING, SINGLE_ADMISSION),
            (MULTI_GROUPING, MULTI_ADMISSION),
            (SPLIT_GROUPING, SPLIT_ADMISSION),
        )
        for index, (grouping_path, admission_path) in enumerate(cases):
            with self.subTest(grouping=grouping_path.name):
                grouping = _read(grouping_path)
                grouping.pop("atomicityReviewPath")
                grouping.pop("atomicityReviewHash")
                fixture = self._fixture_for_grouping(
                    grouping,
                    base=admission_path,
                    selected_group_id=grouping["groups"][0]["groupId"],
                    name=f"bypass-{index}",
                )
                with self.assertRaises(ADAPTER.AdapterError) as caught:
                    ADAPTER.run_slice(fixture, self.temp_dir / f"bypass-{index}-output", repo_root=REPO_ROOT)
                self.assertEqual(caught.exception.code, "E_ATOMICITY_REVIEW_REQUIRED")

    def test_11_pending_review_fails_closed(self):
        atomicity = _read(ATOMICITY_REVIEW)
        self._set_classification(
            atomicity,
            "proposal-57f0e84c5467469bce38",
            "ATOMIC_CLEAR",
            review_status="pending_review",
        )
        grouping = self._grouping_with_atomicity(_read(SINGLE_GROUPING), atomicity, name="pending")
        fixture = self._fixture_for_grouping(grouping, name="pending")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "pending-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_ATOMICITY_NOT_REVIEWED")

    def test_12_review_artifact_covers_exactly_all_66_proposals(self):
        result = ATOMICITY.load_and_validate_atomicity_review(ATOMICITY_REVIEW, repo_root=REPO_ROOT)
        self.assertEqual(len(result["reviewMap"]), 66)
        counts = {}
        for record in result["reviewMap"].values():
            classification = record["atomicityClassification"]
            counts[classification] = counts.get(classification, 0) + 1
        self.assertEqual(
            counts,
            {"ATOMIC_CLEAR": 9, "FRAGMENT_OF_ONE_PARENT": 53, "MIXED_MULTI_PARENT": 4},
        )


if __name__ == "__main__":
    unittest.main()
