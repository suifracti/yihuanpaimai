# -*- coding: utf-8 -*-
"""Comprehensive tests for Dual-Track Prediction Evaluation Artifact v1."""

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
TOOLS_DIR = PROJECT_ROOT / "tools"

for p in (str(PROJECT_ROOT), str(APP_DIR), str(CORE_DIR), str(TOOLS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from canonical_match_record import build_canonical_match_record_v7
from evaluation_metrics import calculate_point_and_quantile_metrics
from prediction_evaluation_generator import (
    generate_evaluation_artifact_from_file,
    generate_prediction_evaluation_summary,
)


class TestPredictionEvaluationArtifactV1(unittest.TestCase):
    def test_real_database_probe_zero_formal_and_active_legacy(self):
        """Test generating artifact from deterministic fixture database: formal=0, legacy active, db unchanged."""
        fixture_records = [
            # 1. Canonical v7 DRAFT (excluded from admission with DRAFT, unusable in legacy exploratory)
            {
                "schemaVersion": 7,
                "productVersion": "v0.67-alpha",
                "id": "fixture_v7_draft_01",
                "playedAt": "2026-08-22T10:00:00+08:00",
                "lifecycleStatus": "DRAFT",
                "source": "manual",
                "environment": {"venue": "shanhu", "box": "standard", "fieldCondition": "standard"},
                "loadout": {"character": "达芙蒂尔", "solverToolGroup": "group1"},
                "costs": {"entry": 5000, "total": 5000},
                "publicIntel": {"q": 9},
                "qualities": {"gold": {"avg": 33538, "knownItems": []}},
                "bidding": {"rounds": []},
                "settlement": {"status": "pending", "verified": False, "clearingPrice": None, "actualTotal": None, "realizedProfit": None},
            },
            # 2. Legacy admitted record with full point + quantile estimates (point & quantile candidate)
            {
                "id": "fixture_legacy_admitted_point_and_quantile_02",
                "playedAt": "2026-08-10T12:00:00",
                "source": "0.65-vision-auto-archiver",
                "venue": "珊瑚场",
                "box": "实木宝箱",
                "fieldCondition": "standard",
                "q": 9,
                "goldAvg": 33538,
                "avg": 33538,
                "clearingPrice": 100000,
                "actualTotal": 125000,
                "realizedProfit": 25000,
                "prediction": {
                    "estimate": 120000,
                    "solverVersion": "v0.65",
                    "probabilityProfile": {
                        "shadowWhole": {
                            "p20": 100000,
                            "p50": 120000,
                            "p80": 150000,
                        }
                    },
                },
                "acquired": True,
                "winner": "玩家本人",
            },
            # 3. Legacy admitted record with point estimate only (point candidate)
            {
                "id": "fixture_legacy_admitted_point_only_03",
                "playedAt": "2026-08-11T14:00:00",
                "source": "0.65-vision-auto-archiver",
                "venue": "海贝场",
                "box": "纸箱",
                "fieldCondition": "standard",
                "q": 6,
                "avg": 20000,
                "clearingPrice": 50000,
                "actualTotal": 60000,
                "realizedProfit": 10000,
                "prediction": {
                    "estimate": 58000,
                    "solverVersion": "v0.65",
                },
                "acquired": True,
                "winner": "玩家本人",
            },
            # 4. Legacy excluded record (no prices, incomplete)
            {
                "id": "fixture_legacy_excluded_04",
                "playedAt": "2026-08-12T16:00:00",
                "venue": "未知场地",
                "box": "未知箱型",
                "clearingPrice": None,
                "actualTotal": None,
                "realizedProfit": None,
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "fixture_db.json"
            fixture_db = {
                "version": 1,
                "schemaVersion": 6,
                "records": fixture_records,
            }
            db_path.write_text(json.dumps(fixture_db, ensure_ascii=False, indent=2), encoding="utf-8")
            bytes_before = db_path.read_bytes()
            sha_before = hashlib.sha256(bytes_before).hexdigest()

            artifact = generate_evaluation_artifact_from_file(db_path)

            # 1. Source & Metadata
            self.assertEqual(artifact["schemaVersion"], "prediction-evaluation-summary.v1")
            self.assertEqual(artifact["source"]["recordCount"], 4)
            self.assertEqual(artifact["source"]["datasetSchemaVersion"], 6)
            self.assertEqual(artifact["source"]["sha256"], sha_before)
            self.assertEqual(artifact["source"]["recordSchemaComposition"]["legacyOrSchemaLess"], 3)
            self.assertEqual(artifact["source"]["recordSchemaComposition"]["canonicalV7Draft"], 1)

            # 2. Admission
            self.assertEqual(artifact["admission"]["admittedCount"], 2)
            self.assertEqual(artifact["admission"]["excludedCount"], 2)
            self.assertEqual(artifact["admission"]["exclusionReasonCounts"]["DRAFT"], 1)
            self.assertEqual(artifact["admission"]["exclusionReasonCounts"]["LEGACY_WITHOUT_SETTLEMENT_EVIDENCE"], 1)

            # 3. Formal Track: 0 eligible, status NOT_AVAILABLE_YET, metrics strictly null
            formal = artifact["formalEvaluation"]
            self.assertEqual(formal["eligibility"]["formallyEligibleCount"], 0)
            self.assertEqual(formal["availability"]["status"], "NOT_AVAILABLE_YET")
            self.assertIsNone(formal["overallMetrics"]["metrics"])
            self.assertEqual(formal["overallMetrics"]["sampleCount"], 0)
            self.assertEqual(formal["cohorts"], [])

            # 4. Legacy Exploratory Track: Active research inventory
            legacy = artifact["legacyExploratoryEvaluation"]
            self.assertEqual(legacy["publicationStatus"], "EXPLORATORY_ONLY")
            self.assertFalse(legacy["formalComparable"])
            self.assertEqual(legacy["provenanceLevel"], "LEGACY_INCOMPLETE")

            inv = legacy["sampleInventory"]
            self.assertEqual(inv["admittedCount"], 2)
            self.assertEqual(inv["pointMetricCandidateCount"], 2)
            self.assertEqual(inv["quantileMetricCandidateCount"], 1)
            self.assertEqual(inv["distributionOnlyCount"], 0)
            self.assertEqual(inv["unusableCount"], 2)

            self.assertEqual(legacy["overallMetrics"]["status"], "AVAILABLE")
            self.assertEqual(legacy["overallMetrics"]["sampleCount"], 2)
            self.assertIsNotNone(legacy["overallMetrics"]["metrics"])
            self.assertEqual(legacy["overallMetrics"]["metrics"]["mae"], 3500.0)
            self.assertEqual(legacy["overallMetrics"]["metrics"]["signedBias"], -3500.0)
            self.assertIn("mare", legacy["overallMetrics"]["metrics"])

            # 5. Deterministic Payload SHA-256
            self.assertTrue(bool(artifact["artifactPayloadSha256"]))

            # 6. Verify Database Invariance
            bytes_after = db_path.read_bytes()
            sha_after = hashlib.sha256(bytes_after).hexdigest()
            self.assertEqual(bytes_before, bytes_after)
            self.assertEqual(sha_before, sha_after)

    def test_metrics_math_accuracy_and_null_guards(self):
        """Test metric math formulas, underestimation thresholds, and central 60% interval."""
        # Zero samples strictly returns None
        self.assertIsNone(calculate_point_and_quantile_metrics([]))

        # Sample: actual=100, estimate=80, p20=75, p50=80, p80=110
        s1 = {"actual": 100.0, "estimate": 80.0, "p20": 75.0, "p50": 80.0, "p80": 110.0}
        # Sample: actual=200, estimate=220, p20=180, p50=220, p80=240
        s2 = {"actual": 200.0, "estimate": 220.0, "p20": 180.0, "p50": 220.0, "p80": 240.0}

        m = calculate_point_and_quantile_metrics([s1, s2])
        self.assertIsNotNone(m)
        self.assertEqual(m["sampleCount"], 2)

        # MAE: (|100-80| + |200-220|) / 2 = (20 + 20) / 2 = 20.0
        self.assertEqual(m["mae"], 20.0)
        # Median AE: 20.0
        self.assertEqual(m["medianAe"], 20.0)
        # Signed Bias: ((80-100) + (220-200)) / 2 = (-20 + 20) / 2 = 0.0
        self.assertEqual(m["signedBias"], 0.0)
        # MARE: (20/100 + 20/200) / 2 = (0.2 + 0.1) / 2 = 0.15
        self.assertEqual(m["mare"], 0.15)

        # Underestimation: s1 u=0.20 (>0.10, not >0.20); s2 u=0.0
        self.assertEqual(m["underestimateRate10"], 0.5)
        self.assertEqual(m["underestimateRate20"], 0.0)

        # Quantiles:
        # s1: actual=100. P20=75 (100<=75 False), P80=110 (100<=110 True), Central60 (75<=100<=110 True)
        # s2: actual=200. P20=180 (200<=180 False), P80=240 (200<=240 True), Central60 (180<=200<=240 True)
        self.assertEqual(m["p20LowerTailCoverage"], 0.0)
        self.assertEqual(m["p80UpperTailCoverage"], 1.0)
        self.assertEqual(m["central60PredictionIntervalCoverage"], 1.0)

    def test_provisional_sample_size_publication_gates(self):
        """Test candidate publication thresholds: N=1 -> INSUFFICIENT_SAMPLE, N=5 -> PRELIMINARY, N=20 -> AVAILABLE."""
        from evaluation_eligibility import build_input_sha256, build_truth_payload_sha256

        # Create helper synthetic eligible sample
        def _make_sample(idx):
            mid = f"syn_{idx:04d}"
            actual = 100000.0 + idx * 5000.0
            t_solve = f"2026-08-21T10:{idx:02d}:05+08:00"
            t_settle = f"2026-08-21T10:{idx:02d}:55+08:00"
            truth_src = "manual_confirmed_against_screenshot"
            facts = {"q": 10 + idx}
            input_h = build_input_sha256(facts)
            truth_h = build_truth_payload_sha256(match_id=mid, actual_total=actual, settlement_observed_at=t_settle, truth_source=truth_src)
            return {
                "schemaVersion": 7,
                "productVersion": "v0.67-alpha",
                "id": mid,
                "lifecycleStatus": "FINALIZED",
                "playedAt": t_solve,
                "source": "vision-auto-archiver",
                "environment": {
                    "venueTier": "zhongji",
                    "venue": "shanhu",
                    "box": "实木宝箱",
                    "boxType": "wood",
                    "fieldCondition": "standard",
                },
                "loadout": {"character": "达芙蒂尔", "lobbyToolGroup": None, "solverToolGroup": "group1"},
                "costs": {"entry": 5000, "intel": 0, "other": 0, "sunkCost": 5000, "futureIncrementalCost": 0, "total": 5000},
                "publicIntel": {"q": 10 + idx, "totalItems": 66, "totalGrid": 84},
                "qualities": {
                    "white": {"count": None, "avg": None, "grid": None, "knownItems": []},
                    "green": {"count": None, "avg": None, "grid": None, "knownItems": []},
                    "blue": {"count": None, "avg": None, "grid": None, "knownItems": []},
                    "purple": {"count": 5, "avg": 2007, "knownItems": []},
                    "gold": {"count": 4, "avg": 33538, "knownItems": []},
                    "red": {"count": None, "knownItems": []},
                },
                "bidding": {"seats": [], "myName": "玩家本人", "myFinalBid": 100000, "leaderName": "玩家本人", "leaderBid": 100000, "leaderTies": [], "isMyLead": True, "historicalBids": {}, "finalBids": {}, "rounds": []},
                "settlement": {
                    "status": "verified",
                    "verified": True,
                    "clearingPrice": 100000.0,
                    "actualTotal": actual,
                    "realizedProfit": 20000.0,
                    "acquired": True,
                    "winner": "玩家本人",
                    "settlementItems": [],
                    "truthEvidence": {
                        "schemaVersion": "settlement-truth-evidence.v1",
                        "matchId": mid,
                        "actualTotal": actual,
                        "settlementObservedAt": t_settle,
                        "truthSource": truth_src,
                        "truthConfidence": "high",
                        "evidenceReferences": [{"uri": "ev.png", "sha256": "a" * 64}],
                        "verification": {"method": "human_screenshot_audit_v1", "version": "1.0", "verifier": {"type": "reviewer", "id": "rev"}},
                        "unresolvedTruthConflict": False,
                        "truthPayloadSha256": truth_h,
                    },
                },
                "predictionSnapshot": {
                    "schemaVersion": "prediction-snapshot.v1",
                    "predictionId": f"pred_{idx}",
                    "matchId": mid,
                    "solvedAt": t_solve,
                    "informationCutoffAt": t_solve,
                    "snapshotRole": "latest_valid_pre_settlement",
                    "producer": {"runtime": "test", "solverName": "v06", "solverVersion": "v0.6", "modelVersion": "v0.6", "catalogVersion": "0813", "codeRevision": "rev1"},
                    "input": {"contractVersion": 1, "normalizedFacts": facts, "hashAlgorithm": "sha256", "inputHash": input_h, "datasetRevision": {"sourceId": "test", "sha256": "d" * 64, "recordCount": 10, "admissionPolicyVersion": 1, "cutoffExclusive": t_solve, "eligibleRecordIdsSha256": "e" * 64}},
                    "mode": {"informationMode": "full_shadow", "coverageRatio": 1.0, "supportedStateCount": 2, "totalStateCount": 2},
                    "status": {"solverStatus": "valid", "provisional": False, "diagnosticOnly": False},
                    "forecast": {"target": "full_inventory_actual_total", "scope": "full_inventory", "quantiles": {"p20": 110000, "p50": 120000, "p80": 130000}},
                    "frozen": True,
                },
            }

        # 1 sample: INSUFFICIENT_SAMPLE, metrics null
        art1 = generate_prediction_evaluation_summary([_make_sample(1)])
        self.assertEqual(art1["formalEvaluation"]["availability"]["status"], "INSUFFICIENT_SAMPLE")
        self.assertIsNone(art1["formalEvaluation"]["overallMetrics"]["metrics"])

        # 5 samples: PRELIMINARY, metrics computed
        art5 = generate_prediction_evaluation_summary([_make_sample(i) for i in range(1, 6)])
        self.assertEqual(art5["formalEvaluation"]["availability"]["status"], "PRELIMINARY")
        self.assertIsNotNone(art5["formalEvaluation"]["overallMetrics"]["metrics"])

        # 20 samples: AVAILABLE, metrics computed
        art20 = generate_prediction_evaluation_summary([_make_sample(i) for i in range(1, 21)])
        self.assertEqual(art20["formalEvaluation"]["availability"]["status"], "AVAILABLE")
        self.assertIsNotNone(art20["formalEvaluation"]["overallMetrics"]["metrics"])

    def test_json_schema_validation(self):
        """Validate artifact against docs/contracts/prediction-evaluation-summary-v1.schema.json."""
        schema_path = PROJECT_ROOT / "docs" / "contracts" / "prediction-evaluation-summary-v1.schema.json"
        schema_dict = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema_dict["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema_dict["title"], "Prediction Evaluation Summary Artifact v1")

        db_path = PROJECT_ROOT / "异环拍卖数据.json"
        artifact = generate_evaluation_artifact_from_file(db_path)

        # Check required root properties from schema
        for req in schema_dict["required"]:
            self.assertIn(req, artifact)
        self.assertEqual(artifact["schemaVersion"], "prediction-evaluation-summary.v1")

    def test_cli_generator_and_output_file(self):
        """Test CLI tool tools/generate_evaluation_artifact.py writing output files."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmp_dir:
            cmd = [
                sys.executable,
                str(TOOLS_DIR / "generate_evaluation_artifact.py"),
                str(PROJECT_ROOT / "异环拍卖数据.json"),
                "--output-dir",
                tmp_dir,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            data = json.loads(proc.stdout)
            self.assertEqual(data["schemaVersion"], "prediction-evaluation-summary.v1")

            latest_p = Path(tmp_dir) / "latest.json"
            self.assertTrue(latest_p.is_file())
            saved_data = json.loads(latest_p.read_text(encoding="utf-8"))
            self.assertEqual(saved_data["artifactPayloadSha256"], data["artifactPayloadSha256"])


if __name__ == "__main__":
    unittest.main()
