# -*- coding: utf-8 -*-
"""Focused invariants for Shadow Distribution control audit v1.2."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

import experiment


class ShadowDistributionControlAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = experiment.PROJECT_ROOT / "异环拍卖数据.json"
        cls.db_hash_before = experiment.sha256_file(cls.db_path)
        cls.dataset = experiment.load_quantile_ablation_dataset(cls.db_path)
        cls.catalogs, cls.catalog_provenance = experiment.load_catalog_snapshots(
            experiment.CORE_DIR / "solver_core_v06.js"
        )
        original = experiment.BOOTSTRAP_REPLICATES
        experiment.BOOTSTRAP_REPLICATES = 250
        try:
            cls.first = experiment.run_control_suite(cls.dataset, cls.catalogs)
            cls.second = experiment.run_control_suite(cls.dataset, cls.catalogs)
        finally:
            experiment.BOOTSTRAP_REPLICATES = original

    def test_same_oos_ids_and_population(self):
        self.assertEqual(self.first["testRecordIds"], self.second["testRecordIds"])
        self.assertEqual(len(self.first["testRecordIds"]), 48)
        self.assertTrue(self.first["invariants"]["sameOosIds"])
        self.assertTrue(self.first["invariants"]["sameOosOrder"])

    def test_p50_is_exact_for_every_dispersion_candidate(self):
        self.assertTrue(self.first["invariants"]["dispersionP50Exact"])
        self.assertTrue(self.first["invariants"]["p50MetricsExact"])
        for row in self.first["perRecord"]:
            baseline = row["models"][experiment.MODEL_NAMES[0]]["p50"]
            for name in experiment.DISPERSION_MODELS:
                self.assertEqual(row["models"][name]["p50"], baseline)

    def test_seeded_outputs_are_reproducible(self):
        self.assertEqual(experiment.public_suite(self.first), experiment.public_suite(self.second))

    def test_a0_rn_proxy_catalog_share_reconstruction_path(self):
        self.assertTrue(self.first["invariants"]["sameReconstructionPathA0RnA1"])
        self.assertEqual(self.first["invariants"]["supportPointsPerState"], 7)

    def test_actual_total_does_not_enter_prediction_generation(self):
        record = self.dataset[20]
        changed = replace(record, actual_total=record.actual_total * 99.0)
        for kwargs in (
            {"variance_model": "off"},
            {"variance_model": "proxy", "proxy_coefficient": 0.25},
            {"variance_model": "null", "null_scale_ratio": 0.10},
            {"variance_model": "catalog", "catalogs": self.catalogs},
        ):
            left = experiment.generate_reconstructed_prediction(record, **kwargs)
            right = experiment.generate_reconstructed_prediction(changed, **kwargs)
            self.assertEqual(left, right)

    def test_all_folds_are_time_safe(self):
        self.assertTrue(self.first["invariants"]["allFoldsTimeSafe"])
        self.assertTrue(all(fold["trainMaxEpoch"] <= fold["testMinEpoch"] for fold in self.first["folds"]))

    def test_catalog_is_read_from_versioned_production_rule_source(self):
        self.assertEqual(self.catalog_provenance["sourcePath"], "core/solver_core_v06.js")
        self.assertEqual(set(self.catalogs), {"pre-2026-08-13", "2026-08-13"})
        self.assertGreater(len(self.catalogs["2026-08-13"].gold), len(self.catalogs["pre-2026-08-13"].gold))

    def test_v11_control_reproduction_resolves_b1_claims(self):
        controls = experiment.legacy_v11_controls(self.dataset)
        self.assertFalse(controls["quantileEquality"]["B1_R_equals_B0"])
        self.assertFalse(controls["quantileEquality"]["B1_G_equals_B0"])
        self.assertFalse(controls["quantileEquality"]["AB_equals_A1"])

    def test_artifact_schema_and_integrity(self):
        output_dir = Path(experiment.__file__).resolve().parent
        results = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
        manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(results["schemaVersion"], experiment.ARTIFACT_SCHEMA_VERSION)
        self.assertEqual(manifest["schemaVersion"], "shadow-distribution-dataset-manifest.v1.2")
        self.assertEqual(results["globalPrimary"]["testRecordIds"], manifest["globalOosRecordIds"])
        self.assertEqual(results["metadata"]["databaseSha256Before"], results["metadata"]["databaseSha256After"])

    def test_main_database_is_byte_for_byte_unchanged(self):
        self.assertEqual(experiment.sha256_file(self.db_path), self.db_hash_before)


if __name__ == "__main__":
    unittest.main()
