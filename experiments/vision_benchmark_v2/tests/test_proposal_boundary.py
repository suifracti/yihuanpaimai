# -*- coding: utf-8 -*-
"""Production proposal export, replay, and authority-boundary regressions."""

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCHMARK_DIR.parents[1]
EXPORT_CONFIG = BENCHMARK_DIR / "fixtures" / "proposal_export_single_source_v1.json"
REVIEW_FIXTURE = BENCHMARK_DIR / "fixtures" / "reviewed_single_parent_v1.json"
GROUPING_FIXTURE = BENCHMARK_DIR / "fixtures" / "grouping_review_single_v1.json"
ARTIFACT_PATH = BENCHMARK_DIR / "proposal_artifact.json"
ATOMICITY_REVIEW = BENCHMARK_DIR / "atomicity_review_v1.json"
SELECTED_PROPOSAL_ID = "proposal-57f0e84c5467469bce38"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BOUNDARY = _load_module("benchmark_v2_proposal_boundary_tests", BENCHMARK_DIR / "proposal_boundary.py")
ADAPTER = _load_module("benchmark_v2_adapter_proposal_tests", BENCHMARK_DIR / "adapter.py")
VALIDATOR = ADAPTER._load_v1_validator(REPO_ROOT)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _selected(artifact):
    return next(item for item in artifact["itemProposals"] if item["proposalId"] == SELECTED_PROPOSAL_ID)


class TestProductionProposalBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-proposals-", dir=BENCHMARK_DIR)
        self.temp_dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write_json(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _fixture_for_artifact(self, artifact):
        artifact_path = self._write_json(self.temp_dir / "proposal-artifact.json", artifact)
        atomicity = _read(ATOMICITY_REVIEW)
        atomicity["proposalArtifactPath"] = artifact_path.relative_to(REPO_ROOT).as_posix()
        atomicity["proposalArtifactHash"] = BOUNDARY.sha256_file(artifact_path)
        atomicity_path = self._write_json(self.temp_dir / "atomicity-review.json", atomicity)
        grouping = _read(GROUPING_FIXTURE)
        grouping["proposalArtifactPath"] = artifact_path.relative_to(REPO_ROOT).as_posix()
        grouping["proposalArtifactHash"] = BOUNDARY.sha256_file(artifact_path)
        grouping["atomicityReviewPath"] = atomicity_path.relative_to(REPO_ROOT).as_posix()
        grouping["atomicityReviewHash"] = BOUNDARY.sha256_file(atomicity_path)
        grouping_path = self._write_json(self.temp_dir / "grouping-review.json", grouping)
        fixture = _read(REVIEW_FIXTURE)
        fixture["groupingReview"] = {
            "path": grouping_path.relative_to(REPO_ROOT).as_posix(),
            "expectedSha256": BOUNDARY.sha256_file(grouping_path),
            "selectedGroupId": grouping["groups"][0]["groupId"],
        }
        fixture_path = self._write_json(self.temp_dir / "reviewed-fixture.json", fixture)
        return fixture_path

    def _run_artifact(self, artifact, name):
        fixture_path = self._fixture_for_artifact(artifact)
        return ADAPTER.run_slice(fixture_path, self.temp_dir / name, repo_root=REPO_ROOT)

    def test_1_same_source_and_primitive_version_export_identically_and_replay(self):
        schema = _read(BENCHMARK_DIR / "proposal_contract_v1.schema.json")
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(
            set(schema["required"]),
            {"schemaVersion", "source", "sceneProposal", "roiProposal", "itemProposals"},
        )
        item_properties = set(schema["$defs"]["itemProposal"]["properties"])
        self.assertTrue(BOUNDARY.FORBIDDEN_AUTHORITY_FIELDS.isdisjoint(item_properties))

        first = BOUNDARY.export_artifact(EXPORT_CONFIG, repo_root=REPO_ROOT)
        second = BOUNDARY.export_artifact(EXPORT_CONFIG, repo_root=REPO_ROOT)
        self.assertEqual(first, second)
        self.assertEqual(BOUNDARY.sha256_json(first), BOUNDARY.sha256_json(second))
        self.assertEqual(first, _read(ARTIFACT_PATH))

        first_replay = self._run_artifact(copy.deepcopy(first), "first-replay")
        second_replay = self._run_artifact(copy.deepcopy(second), "second-replay")
        self.assertEqual(
            first_replay["queue"]["items"][0]["instanceId"],
            second_replay["queue"]["items"][0]["instanceId"],
        )
        self.assertEqual(
            first_replay["queue"]["items"][0]["cropSha256"],
            second_replay["queue"]["items"][0]["cropSha256"],
        )

    def test_2_source_hash_mismatch_fails_adapter_replay(self):
        artifact = _read(ARTIFACT_PATH)
        artifact["source"]["sha256"] = "0" * 64
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            self._run_artifact(artifact, "bad-source-hash")
        self.assertEqual(caught.exception.code, "E_PROPOSAL_SOURCE_HASH")

    def test_3_non_source_pixel_item_proposal_fails(self):
        artifact = _read(ARTIFACT_PATH)
        _selected(artifact)["coordinateSpace"] = "normalized_viewport"
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            self._run_artifact(artifact, "bad-coordinate-space")
        self.assertEqual(caught.exception.code, "E_PROPOSAL_COORDINATE_SPACE")

    def test_4_out_of_bounds_item_proposal_fails(self):
        artifact = _read(ARTIFACT_PATH)
        _selected(artifact)["bbox"] = [300, 300, 400, 400]
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            self._run_artifact(artifact, "bad-bbox")
        self.assertEqual(caught.exception.code, "E_PROPOSAL_BBOX_BOUNDS")

    def test_5_run_local_track_id_is_provenance_not_instance_identity(self):
        baseline = ADAPTER.run_slice(REVIEW_FIXTURE, self.temp_dir / "baseline-track", repo_root=REPO_ROOT)
        artifact = _read(ARTIFACT_PATH)
        _selected(artifact)["trackId"] = "run-local-track-98765"
        replay = self._run_artifact(artifact, "track-provenance")

        baseline_item = baseline["queue"]["items"][0]
        replay_item = replay["queue"]["items"][0]
        self.assertEqual(replay_item["instanceId"], baseline_item["instanceId"])
        self.assertNotIn("track", replay_item["instanceId"])
        self.assertEqual(
            replay["sourceRecord"]["proposalProvenance"]["selectedProposalTrackIds"][0]["trackId"],
            "run-local-track-98765",
        )

    def test_6_semantic_observation_is_provenance_not_instance_identity(self):
        baseline = ADAPTER.run_slice(REVIEW_FIXTURE, self.temp_dir / "baseline-semantic", repo_root=REPO_ROOT)
        artifact = _read(ARTIFACT_PATH)
        evidence = _selected(artifact)["rawProposalEvidence"]
        evidence["rarityObservation"] = "semantic-label-must-not-own-identity"
        replay = self._run_artifact(artifact, "semantic-provenance")

        self.assertEqual(
            replay["queue"]["items"][0]["instanceId"],
            baseline["queue"]["items"][0]["instanceId"],
        )
        self.assertIsNone(replay["geometryContract"]["instances"][0]["canonicalItemId"])
        self.assertIsNone(replay["geometryContract"]["instances"][0]["observationLabel"])

    def test_7_reviewed_proposal_resolution_enters_existing_v2_admission(self):
        result = ADAPTER.run_slice(REVIEW_FIXTURE, self.temp_dir / "admitted", repo_root=REPO_ROOT)
        provenance = result["sourceRecord"]["proposalProvenance"]
        instance = result["geometryContract"]["instances"][0]
        validation = VALIDATOR.validate_contract_file(
            Path(result["paths"]["geometryContract"]),
            repo_root=REPO_ROOT,
        )

        self.assertEqual(provenance["selectedProposalIds"], [SELECTED_PROPOSAL_ID])
        self.assertEqual(provenance["resolvedParentBbox"], [61, 164, 92, 197])
        self.assertEqual(instance["bbox"], provenance["resolvedParentBbox"])
        self.assertEqual(result["queue"]["admissionStatus"], "PASS")
        self.assertTrue(validation.valid, [issue.message for issue in validation.issues])


if __name__ == "__main__":
    unittest.main()
