# -*- coding: utf-8 -*-
"""Reviewed mixed-proposal splitting and ownership regressions."""

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCHMARK_DIR.parents[1]
SPLIT = BENCHMARK_DIR / "fixtures" / "reviewed_split_44d473_v1.json"
SPLIT_GROUPING = BENCHMARK_DIR / "fixtures" / "grouping_review_split_children_v1.json"
UPPER_ADMISSION = BENCHMARK_DIR / "fixtures" / "reviewed_split_upper_parent_v1.json"
LOWER_ADMISSION = BENCHMARK_DIR / "fixtures" / "reviewed_split_lower_parent_v1.json"
SINGLE_ADMISSION = BENCHMARK_DIR / "fixtures" / "reviewed_single_parent_v1.json"
MULTI_ADMISSION = BENCHMARK_DIR / "fixtures" / "reviewed_multi_parent_v1.json"
SINGLE_GROUPING = BENCHMARK_DIR / "fixtures" / "grouping_review_single_v1.json"
MULTI_GROUPING = BENCHMARK_DIR / "fixtures" / "grouping_review_multi_v1.json"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _load_module("benchmark_v2_adapter_split_tests", BENCHMARK_DIR / "adapter.py")
SPLITTER = _load_module("benchmark_v2_proposal_split_tests", BENCHMARK_DIR / "proposal_split.py")
PROPOSAL = _load_module("benchmark_v2_proposal_boundary_split_tests", BENCHMARK_DIR / "proposal_boundary.py")
VALIDATOR = ADAPTER._load_v1_validator(REPO_ROOT)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestReviewedProposalSplitContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-split-", dir=BENCHMARK_DIR)
        self.temp_dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write_json(self, name, payload):
        path = self.temp_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _admission_for_grouping(self, grouping, *, selected_group_id=None, name="case"):
        grouping_path = self._write_json(f"{name}-grouping.json", grouping)
        fixture = _read(UPPER_ADMISSION)
        fixture["groupingReview"] = {
            "path": grouping_path.relative_to(REPO_ROOT).as_posix(),
            "expectedSha256": PROPOSAL.sha256_file(grouping_path),
            "selectedGroupId": selected_group_id or grouping["groups"][0]["groupId"],
        }
        return self._write_json(f"{name}-admission.json", fixture)

    def _grouping_for_split(self, split, *, name):
        split_path = self._write_json(f"{name}-split.json", split)
        grouping = _read(SPLIT_GROUPING)
        grouping["splitReviewPath"] = split_path.relative_to(REPO_ROOT).as_posix()
        grouping["splitReviewHash"] = PROPOSAL.sha256_file(split_path)
        return grouping

    def test_1_real_mixed_proposal_splits_into_two_children(self):
        schema = _read(BENCHMARK_DIR / "reviewed_proposal_split_contract_v1.schema.json")
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertTrue(SPLITTER.FORBIDDEN_SPLIT_FIELDS.isdisjoint(schema["properties"]))
        result = SPLITTER.load_and_validate_split(SPLIT, repo_root=REPO_ROOT, require_admission_review=True)
        self.assertEqual(result["split"]["proposalId"], "proposal-44d473f3458cff319236")
        self.assertEqual(len(result["children"]), 2)
        self.assertEqual(
            {child["childId"]: child["sourceCells"] for child in result["children"]},
            {
                "split-child-1c9b91687748": [[1, 0], [2, 0]],
                "split-child-7a64c32a095d": [[3, 0]],
            },
        )
        self.assertEqual(result["discardedRegions"][0]["sourcePixelBbox"], [0, 99, 31, 103])

    def test_2_artifact_hash_mismatch_fails(self):
        split = _read(SPLIT)
        split["proposalArtifactHash"] = "0" * 64
        path = self._write_json("bad-artifact-hash.json", split)
        with self.assertRaises(SPLITTER.SplitError) as caught:
            SPLITTER.load_and_validate_split(path, repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_SPLIT_ARTIFACT_HASH")

    def test_3_unknown_proposal_fails(self):
        split = _read(SPLIT)
        split["proposalId"] = "proposal-does-not-exist"
        path = self._write_json("unknown-proposal.json", split)
        with self.assertRaises(SPLITTER.SplitError) as caught:
            SPLITTER.load_and_validate_split(path, repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_SPLIT_PROPOSAL_UNKNOWN")

    def test_4_overlapping_authoritative_child_cells_fail(self):
        split = _read(SPLIT)
        split["children"][1]["sourceCells"] = [[2, 0], [3, 0]]
        path = self._write_json("overlapping-cells.json", split)
        with self.assertRaises(SPLITTER.SplitError) as caught:
            SPLITTER.load_and_validate_split(path, repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_SPLIT_CHILD_CELL_OVERLAP")

    def test_5_unreviewed_split_cannot_enter_queue(self):
        split = _read(SPLIT)
        split["reviewStatus"] = "pending_review"
        grouping = self._grouping_for_split(split, name="pending")
        fixture = self._admission_for_grouping(grouping, name="pending")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "pending-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_SPLIT_NOT_REVIEWED")

    def test_6_reviewed_split_proposal_cannot_be_directly_admitted(self):
        grouping = _read(SINGLE_GROUPING)
        group = grouping["groups"][0]
        group["memberProposalIds"] = ["proposal-44d473f3458cff319236"]
        group["resolvedParentBbox"] = [0, 33, 31, 132]
        fixture = self._admission_for_grouping(grouping, name="direct-split-proposal")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "direct-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_SPLIT_PROPOSAL_DIRECT_PARENT")

    def test_7_reviewed_split_proposal_cannot_be_complete_group_member(self):
        grouping = _read(MULTI_GROUPING)
        grouping["groups"][0]["memberProposalIds"].append("proposal-44d473f3458cff319236")
        fixture = self._admission_for_grouping(grouping, name="whole-group-member")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "whole-group-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_SPLIT_PROPOSAL_DIRECT_PARENT")

    def test_8_both_children_reenter_geometry_and_queue_admission(self):
        upper = ADAPTER.run_slice(UPPER_ADMISSION, self.temp_dir / "upper", repo_root=REPO_ROOT)
        lower = ADAPTER.run_slice(LOWER_ADMISSION, self.temp_dir / "lower", repo_root=REPO_ROOT)
        for result, expected_bbox in ((upper, [8, 13, 38, 99]), (lower, [8, 103, 98, 162])):
            validation = VALIDATOR.validate_contract_file(Path(result["paths"]["geometryContract"]), repo_root=REPO_ROOT)
            self.assertTrue(validation.valid, [issue.message for issue in validation.issues])
            self.assertEqual(result["geometryContract"]["instances"][0]["bbox"], expected_bbox)
            self.assertEqual(result["queue"]["admissionStatus"], "PASS")
            provenance = result["sourceRecord"]["proposalProvenance"]
            self.assertEqual(provenance["parentResolutionMethod"], "reviewed_split_child_parent")
            self.assertEqual(provenance["splitSourceProposalId"], "proposal-44d473f3458cff319236")
            self.assertEqual(provenance["selectedSplitChildCount"], 1)

    def test_9_existing_single_and_multi_grouping_chains_still_pass(self):
        single = ADAPTER.run_slice(SINGLE_ADMISSION, self.temp_dir / "legacy-single", repo_root=REPO_ROOT)
        multi = ADAPTER.run_slice(MULTI_ADMISSION, self.temp_dir / "legacy-multi", repo_root=REPO_ROOT)
        self.assertEqual(single["queue"]["admissionStatus"], "PASS")
        self.assertEqual(multi["queue"]["admissionStatus"], "PASS")

    def test_10_one_split_child_cannot_enter_two_parent_groups(self):
        grouping = _read(SPLIT_GROUPING)
        duplicate = copy.deepcopy(grouping["groups"][0])
        duplicate["groupId"] = "group-duplicate-split-child"
        grouping["groups"].append(duplicate)
        fixture = self._admission_for_grouping(grouping, name="duplicate-child")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "duplicate-child-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_SPLIT_CHILD_MULTIPLE_PARENT_GROUPS")

    def test_11_split_review_metadata_order_does_not_change_instance_id(self):
        baseline = ADAPTER.run_slice(UPPER_ADMISSION, self.temp_dir / "baseline", repo_root=REPO_ROOT)
        split = _read(SPLIT)
        split["children"].reverse()
        grouping = self._grouping_for_split(split, name="reordered")
        fixture = self._admission_for_grouping(grouping, name="reordered")
        replay = ADAPTER.run_slice(fixture, self.temp_dir / "reordered-output", repo_root=REPO_ROOT)
        self.assertEqual(
            baseline["queue"]["items"][0]["instanceId"],
            replay["queue"]["items"][0]["instanceId"],
        )

    def test_12_parent_resolution_cannot_reclaim_discarded_pixels(self):
        grouping = _read(SPLIT_GROUPING)
        grouping["groups"][0]["resolvedParentBbox"] = [8, 13, 38, 102]
        fixture = self._admission_for_grouping(grouping, name="reclaim-discard")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            ADAPTER.run_slice(fixture, self.temp_dir / "reclaim-discard-output", repo_root=REPO_ROOT)
        self.assertEqual(caught.exception.code, "E_GROUP_DISCARDED_REGION_OWNERSHIP")


if __name__ == "__main__":
    unittest.main()
