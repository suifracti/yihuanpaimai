# -*- coding: utf-8 -*-
"""Reviewed single/multi proposal parent grouping regressions."""

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCHMARK_DIR.parents[1]
SINGLE_ADMISSION = BENCHMARK_DIR / "fixtures" / "reviewed_single_parent_v1.json"
MULTI_ADMISSION = BENCHMARK_DIR / "fixtures" / "reviewed_multi_parent_v1.json"
MULTI_GROUPING = BENCHMARK_DIR / "fixtures" / "grouping_review_multi_v1.json"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _load_module("benchmark_v2_adapter_grouping_tests", BENCHMARK_DIR / "adapter.py")
GROUPING = _load_module("benchmark_v2_grouping_review_tests", BENCHMARK_DIR / "grouping_review.py")
PROPOSAL = _load_module("benchmark_v2_proposal_boundary_grouping_tests", BENCHMARK_DIR / "proposal_boundary.py")
VALIDATOR = ADAPTER._load_v1_validator(REPO_ROOT)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestParentGroupingContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-grouping-", dir=BENCHMARK_DIR)
        self.temp_dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write_json(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _fixture_for_grouping(self, grouping, name="case"):
        grouping_path = self._write_json(self.temp_dir / f"{name}-grouping.json", grouping)
        fixture = _read(MULTI_ADMISSION)
        fixture["groupingReview"] = {
            "path": grouping_path.relative_to(REPO_ROOT).as_posix(),
            "expectedSha256": PROPOSAL.sha256_file(grouping_path),
            "selectedGroupId": grouping["groups"][0]["groupId"],
        }
        return self._write_json(self.temp_dir / f"{name}-admission.json", fixture)

    def _run_grouping(self, grouping, name):
        fixture = self._fixture_for_grouping(grouping, name)
        return ADAPTER.run_slice(fixture, self.temp_dir / f"{name}-output", repo_root=REPO_ROOT)

    def test_1_single_proposal_review_remains_admissible(self):
        schema = _read(BENCHMARK_DIR / "parent_grouping_contract_v1.schema.json")
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(
            set(schema["required"]),
            {
                "groupingVersion", "sourceId", "proposalArtifactPath", "proposalArtifactHash",
                "atomicityReviewPath", "atomicityReviewHash", "groups",
            },
        )
        group_properties = set(schema["$defs"]["group"]["properties"])
        self.assertTrue(GROUPING.FORBIDDEN_GROUPING_FIELDS.isdisjoint(group_properties))

        result = ADAPTER.run_slice(SINGLE_ADMISSION, self.temp_dir / "single", repo_root=REPO_ROOT)
        provenance = result["sourceRecord"]["proposalProvenance"]
        self.assertEqual(provenance["parentResolutionMethod"], "single_proposal")
        self.assertEqual(provenance["selectedProposalCount"], 1)
        self.assertEqual(result["queue"]["admissionStatus"], "PASS")

    def test_2_real_multi_fragment_parent_is_admitted_and_order_stable(self):
        baseline = ADAPTER.run_slice(MULTI_ADMISSION, self.temp_dir / "multi", repo_root=REPO_ROOT)
        provenance = baseline["sourceRecord"]["proposalProvenance"]
        validation = VALIDATOR.validate_contract_file(
            Path(baseline["paths"]["geometryContract"]),
            repo_root=REPO_ROOT,
        )
        self.assertEqual(provenance["parentResolutionMethod"], "reviewed_multi_proposal_group")
        self.assertEqual(provenance["selectedProposalCount"], 23)
        self.assertEqual(provenance["bboxDerivation"], "reviewed_override")
        self.assertEqual(provenance["selectedProposalUnionBbox"], [92, 99, 246, 263])
        self.assertEqual(provenance["resolvedParentBbox"], [99, 101, 248, 251])
        self.assertEqual(baseline["queue"]["items"][0]["cropDimensions"], {"width": 149, "height": 150})
        self.assertTrue(validation.valid, [issue.message for issue in validation.issues])

        reordered = _read(MULTI_GROUPING)
        reordered["groups"][0]["memberProposalIds"].reverse()
        replay = self._run_grouping(reordered, "reordered")
        self.assertEqual(
            replay["queue"]["items"][0]["instanceId"],
            baseline["queue"]["items"][0]["instanceId"],
        )

        reduced = _read(MULTI_GROUPING)
        reduced["groups"][0]["memberProposalIds"].pop()
        reduced_replay = self._run_grouping(reduced, "reduced")
        self.assertEqual(
            reduced_replay["queue"]["items"][0]["instanceId"],
            baseline["queue"]["items"][0]["instanceId"],
        )

    def test_3_unknown_member_proposal_fails(self):
        grouping = _read(MULTI_GROUPING)
        grouping["groups"][0]["memberProposalIds"].append("proposal-does-not-exist")
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            self._run_grouping(grouping, "unknown-member")
        self.assertEqual(caught.exception.code, "E_GROUP_PROPOSAL_UNKNOWN")

    def test_4_one_proposal_cannot_belong_to_two_parent_groups(self):
        grouping = _read(MULTI_GROUPING)
        duplicate_group = copy.deepcopy(grouping["groups"][0])
        duplicate_group["groupId"] = "group-duplicate-owner"
        grouping["groups"].append(duplicate_group)
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            self._run_grouping(grouping, "duplicate-owner")
        self.assertEqual(caught.exception.code, "E_PROPOSAL_MULTIPLE_PARENT_GROUPS")

    def test_5_proposal_artifact_hash_mismatch_fails(self):
        grouping = _read(MULTI_GROUPING)
        grouping["proposalArtifactHash"] = "0" * 64
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            self._run_grouping(grouping, "artifact-hash")
        self.assertEqual(caught.exception.code, "E_GROUPING_ARTIFACT_HASH")

    def test_6_resolved_parent_bbox_out_of_bounds_fails(self):
        grouping = _read(MULTI_GROUPING)
        grouping["groups"][0]["resolvedParentBbox"] = [99, 101, 400, 401]
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            self._run_grouping(grouping, "bbox-bounds")
        self.assertEqual(caught.exception.code, "E_GROUP_BBOX_BOUNDS")

    def test_7_unreviewed_multi_group_cannot_enter_queue(self):
        grouping = _read(MULTI_GROUPING)
        grouping["groups"][0]["reviewStatus"] = "pending_review"
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            self._run_grouping(grouping, "pending-review")
        self.assertEqual(caught.exception.code, "E_GROUP_NOT_REVIEWED")


if __name__ == "__main__":
    unittest.main()
