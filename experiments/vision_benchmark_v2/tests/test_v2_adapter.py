# -*- coding: utf-8 -*-
"""Regression tests for the Benchmark v2 single-source admission slice."""

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCHMARK_DIR.parents[1]
FIXTURE_PATH = BENCHMARK_DIR / "fixtures" / "reviewed_single_parent_v1.json"

SPEC = importlib.util.spec_from_file_location(
    "benchmark_v2_single_source_adapter",
    BENCHMARK_DIR / "adapter.py",
)
ADAPTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ADAPTER
SPEC.loader.exec_module(ADAPTER)
VALIDATOR = ADAPTER._load_v1_validator(REPO_ROOT)


def _fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _codes(result):
    return {issue.code for issue in result.issues}


class TestV2SingleSourceAdapter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".test-admission-", dir=BENCHMARK_DIR)
        self.temp_dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write_fixture(self, payload, name="fixture.json"):
        path = self.temp_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _run(self, fixture_path=None, output_name="output"):
        return ADAPTER.run_slice(
            fixture_path or FIXTURE_PATH,
            self.temp_dir / output_name,
            repo_root=REPO_ROOT,
        )

    def test_1_eligible_fixed_source_is_admitted_deterministically(self):
        first = self._run(output_name="first")
        second = self._run(output_name="second")

        first_item = first["queue"]["items"][0]
        second_item = second["queue"]["items"][0]
        instance = first["geometryContract"]["instances"][0]
        source = first["sourceRecord"]

        self.assertEqual(first["queue"]["admissionStatus"], "PASS")
        self.assertEqual(first["queue"]["validation"]["preflight"], "PASS")
        self.assertEqual(first["queue"]["validation"]["finalAdmission"], "PASS")
        self.assertTrue(first_item["instanceId"].startswith("inst-"))
        self.assertNotIn("REP-", first_item["instanceId"])
        self.assertNotIn("s01", first_item["instanceId"])
        self.assertIsNone(instance["canonicalItemId"])
        self.assertIsNone(instance["observationLabel"])
        self.assertEqual(first_item["cropDimensions"], {"width": 31, "height": 33})
        self.assertEqual(source["coordinateSpace"], "source_pixel")
        self.assertEqual(source["sha256"], _fixture()["expectedSourceSha256"])
        self.assertEqual(first_item["instanceId"], second_item["instanceId"])
        self.assertEqual(first_item["queueId"], second_item["queueId"])
        self.assertEqual(first_item["cropSha256"], second_item["cropSha256"])

    def test_2_source_hash_or_declared_dimensions_are_rejected(self):
        bad_hash = _fixture()
        bad_hash["expectedSourceSha256"] = "0" * 64
        with self.assertRaisesRegex(ADAPTER.AdapterError, "E_SOURCE_HASH_MISMATCH"):
            self._run(self._write_fixture(bad_hash, "bad-hash.json"), "bad-hash")

        bad_dimensions = _fixture()
        bad_dimensions["expectedWidth"] -= 1
        with self.assertRaises(ADAPTER.AdapterError) as caught:
            self._run(self._write_fixture(bad_dimensions, "bad-dimensions.json"), "bad-dimensions")
        self.assertEqual(caught.exception.code, "E_PREFLIGHT_VALIDATION")
        self.assertIn("E_SOURCE_DIMENSIONS_MISMATCH", caught.exception.message)

    def test_3_invalid_roi_is_rejected_before_materialization(self):
        bad_roi = _fixture()
        bad_roi["inventoryRoi"]["width"] += 1
        with self.assertRaises(ADAPTER.AdapterError) as roi_caught:
            self._run(self._write_fixture(bad_roi, "bad-roi.json"), "bad-roi")
        self.assertEqual(roi_caught.exception.code, "E_PROPOSAL_ROI_MISMATCH")

    def test_4_crop_dimensions_must_equal_bbox_extent(self):
        result = self._run()
        crop_path = Path(result["paths"]["crop"])
        with Image.open(crop_path) as crop:
            crop.crop((0, 0, crop.width - 1, crop.height)).save(crop_path, format="PNG")

        validation = VALIDATOR.validate_contract_file(
            Path(result["paths"]["geometryContract"]),
            repo_root=REPO_ROOT,
        )
        self.assertFalse(validation.valid)
        self.assertIn("E_CROP_DIMENSIONS_MISMATCH", _codes(validation))

    def test_5_queue_cannot_reference_an_unknown_instance(self):
        result = self._run()
        contract = copy.deepcopy(result["geometryContract"])
        contract["queueSlots"][0]["instanceId"] = "inst-does-not-exist"

        validation = VALIDATOR.validate_contract_data(
            contract,
            contract_path=Path(result["paths"]["geometryContract"]),
            repo_root=REPO_ROOT,
        )
        self.assertFalse(validation.valid)
        self.assertIn("E_QUEUE_INSTANCE_UNKNOWN", _codes(validation))

    def test_6_one_instance_cannot_enter_the_queue_twice(self):
        result = self._run()
        contract = copy.deepcopy(result["geometryContract"])
        duplicate = copy.deepcopy(contract["queueSlots"][0])
        duplicate["queueId"] += "-duplicate"
        contract["queueSlots"].append(duplicate)

        validation = VALIDATOR.validate_contract_data(
            contract,
            contract_path=Path(result["paths"]["geometryContract"]),
            repo_root=REPO_ROOT,
        )
        self.assertFalse(validation.valid)
        self.assertIn("E_INSTANCE_MULTIPLE_QUEUE_SLOTS", _codes(validation))


if __name__ == "__main__":
    unittest.main()
