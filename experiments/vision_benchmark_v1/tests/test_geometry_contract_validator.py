# -*- coding: utf-8 -*-
"""Regression tests for the standalone Benchmark v1 geometry contract."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BENCHMARK_DIR.parents[1]
FIXTURES = BENCHMARK_DIR / "fixtures"

SPEC = importlib.util.spec_from_file_location(
    "benchmark_geometry_validator",
    BENCHMARK_DIR / "validate_geometry_contract.py",
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def _validate(name):
    return VALIDATOR.validate_contract_file(FIXTURES / name, repo_root=REPO_ROOT)


def _codes(result):
    return {issue.code for issue in result.issues}


class TestGeometryContractValidator(unittest.TestCase):
    def test_schema_is_valid_json_and_names_required_contract_fields(self):
        with (BENCHMARK_DIR / "geometry_contract_v1.schema.json").open(encoding="utf-8") as handle:
            schema = json.load(handle)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(
            set(schema["required"]),
            {"contractVersion", "pathBase", "sources", "instances", "queueSlots"},
        )
        self.assertIn("source", schema["$defs"])
        self.assertIn("physicalItemInstance", schema["$defs"])
        self.assertIn("queueSlot", schema["$defs"])

    def test_valid_source_relative_fixture_passes(self):
        result = _validate("geometry_contract_valid.json")
        self.assertTrue(result.valid, [issue.message for issue in result.issues])
        self.assertTrue(result.pack_eligible)
        self.assertEqual((result.source_count, result.instance_count, result.queue_slot_count), (1, 1, 1))

    def test_rep04_coordinate_space_mismatch_is_rejected_before_crop(self):
        result = _validate("geometry_contract_rep04_coordinate_mismatch.json")
        self.assertFalse(result.valid)
        self.assertIn("E_ROI_COORDINATE_SPACE", _codes(result))
        self.assertNotIn("E_CROP_DIMENSIONS_MISMATCH", _codes(result))

    def test_rep05_ineligible_scene_is_rejected_before_bbox_or_crop(self):
        result = _validate("geometry_contract_rep05_ineligible_source.json")
        self.assertFalse(result.valid)
        self.assertEqual(_codes(result), {"E_SOURCE_NOT_INVENTORY_ELIGIBLE"})

    def test_large_parent_instances_cannot_fan_out_to_multiple_slots(self):
        result = _validate("geometry_contract_large_parent_duplicates.json")
        self.assertFalse(result.valid)
        duplicates = [issue for issue in result.issues if issue.code == "E_INSTANCE_MULTIPLE_QUEUE_SLOTS"]
        self.assertEqual(len(duplicates), 2)
        messages = "\n".join(issue.message for issue in duplicates)
        self.assertIn("inst-regression-new-flavor-parent", messages)
        self.assertIn("inst-regression-giovanni-statue-parent", messages)


if __name__ == "__main__":
    unittest.main()
