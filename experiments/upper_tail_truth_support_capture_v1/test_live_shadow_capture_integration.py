# -*- coding: utf-8 -*-
"""Real Node-shadow -> private envelope -> sidecar integration regression."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "core", PROJECT_ROOT / "app"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import live_shadow  # noqa: E402
from experiments.upper_tail_truth_support_capture_v1.capture_contract import (  # noqa: E402
    sha256_json,
)
from experiments.upper_tail_truth_support_capture_v1.runtime_capture_hook import (  # noqa: E402
    CAPTURE_PHASE,
    load_and_validate_capture,
)
from experiments.upper_tail_truth_support_capture_v1.test_runtime_capture_hook import (  # noqa: E402
    _runtime_envelope,
)


class LiveShadowCaptureIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        live_shadow.reset_live_shadow_state()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.history = self.root / "history.json"
        self.capture_dir = self.root / "captures"
        names = ["「泪滴」", "「摇星」", "九格小食", "永生花环", "鸣佩"]
        records = []
        for index, name in enumerate(names):
            records.append(
                {
                    "id": f"history-{index}",
                    "playedAt": f"2026-08-{10 + index:02d}T10:00:00+08:00",
                    "venue": "V",
                    "box": "B",
                    "q": 9,
                    "goldCount": 3,
                    "purpleCount": 5,
                    "redCount": 1,
                    "goldAvg": 33538,
                    "actualTotal": 200000 + index * 10000,
                    "fieldCondition": "standard",
                    "catalogVersion": "2026-08-13",
                    "redInventoryComplete": True,
                    "settlementVerifiedRedItems": name,
                    "settlement": {
                        "redCount": 1,
                        "redInventoryComplete": True,
                        "verifiedRedItems": name,
                        "truthSource": "fixture",
                        "truthConfidence": "verified",
                    },
                }
            )
        self.history.write_text(
            json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        live_shadow.reset_live_shadow_state()
        self.temp.cleanup()

    def test_capture_occurs_after_solve_without_mutating_public_outputs_or_history(self) -> None:
        history_before = hashlib.sha256(self.history.read_bytes()).hexdigest()
        ctx = {
            "matchId": "capture-integration-001",
            "playedAt": "2026-08-22T10:00:00+08:00",
            "scene": "IN_AUCTION",
            "round": 3,
            "q": 9,
            "purpleCount": 5,
            "goldAvg": 33538,
            "venue": "V",
            "box": "B",
            "fieldCondition": "standard",
            "catalogVersion": "2026-08-13",
        }
        with mock.patch.dict(
            os.environ,
            {
                "YIHUAN_UPPER_TAIL_CAPTURE_DIR": str(self.capture_dir),
                "YIHUAN_CAPTURE_COLLECTION_CLASS": "RUNTIME_SMOKE_CAPTURE",
            },
        ):
            profile, meta = live_shadow.compute_live_probability_profile(
                ctx, db_path=str(self.history), persist_runtime=False
            )

        profile_hash = sha256_json(profile)
        snapshot_hash = sha256_json(meta["predictionSnapshot"])
        frozen_hash = sha256_json(meta["frozenPrediction"])
        self.assertEqual(meta["supportCapture"]["status"], "WRITTEN")
        artifact = load_and_validate_capture(meta["supportCapture"]["path"])

        self.assertEqual(artifact["capturePhase"], CAPTURE_PHASE)
        self.assertEqual(artifact["collectionClass"], "RUNTIME_SMOKE_CAPTURE")
        self.assertEqual(artifact["predictionSnapshotSha256"], snapshot_hash)
        self.assertEqual(artifact["matchId"], ctx["matchId"])
        self.assertEqual(artifact["matchBinding"]["status"], "RUNTIME_CONTEXT_BINDING")
        self.assertEqual(artifact["predictionSnapshot"]["matchId"], "unknown_match")
        self.assertEqual(
            artifact["aggregateDistribution"]["quantiles"],
            meta["predictionSnapshot"]["forecast"]["quantiles"],
        )
        self.assertEqual(sha256_json(profile), profile_hash)
        self.assertEqual(sha256_json(meta["predictionSnapshot"]), snapshot_hash)
        self.assertEqual(sha256_json(meta["frozenPrediction"]), frozen_hash)
        self.assertEqual(hashlib.sha256(self.history.read_bytes()).hexdigest(), history_before)
        self.assertNotIn("supportCaptureEnvelope", profile)
        self.assertNotIn("supportCaptureEnvelope", meta)

    def test_capture_rejection_is_logged_and_does_not_block_prediction(self) -> None:
        envelope = _runtime_envelope()
        envelope["actualTotal"] = 999999
        public_profile = {"shadowWhole": {"p20": 1, "p50": 2, "p80": 3}}
        public_frozen = {"center": 2, "source": "unchanged-fixture"}
        fake_result = {
            "ok": True,
            "probabilityProfile": public_profile,
            "predictionSnapshot": envelope["predictionSnapshot"],
            "frozenPrediction": public_frozen,
            "exactStates": [],
            "expandedStates": [],
            "supportCaptureEnvelope": envelope,
        }
        with mock.patch.object(live_shadow, "_oneshot_compute", return_value=fake_result), mock.patch.object(
            live_shadow._LOG, "warning"
        ) as warning, mock.patch.dict(
            os.environ,
            {
                "YIHUAN_UPPER_TAIL_CAPTURE_DIR": str(self.capture_dir),
                "YIHUAN_CAPTURE_COLLECTION_CLASS": "RUNTIME_SMOKE_CAPTURE",
            },
        ):
            profile, meta = live_shadow.compute_live_probability_profile(
                {"q": 15, "goldAvg": 36488.5},
                db_path=str(self.history),
                persist_runtime=False,
            )
        self.assertEqual(profile, public_profile)
        self.assertEqual(meta["predictionSnapshot"], envelope["predictionSnapshot"])
        self.assertEqual(meta["frozenPrediction"], public_frozen)
        self.assertEqual(meta["supportCapture"]["status"], "REJECTED")
        self.assertIn("POST_SETTLEMENT_FIELD_FORBIDDEN", meta["supportCapture"]["reason"])
        warning.assert_called_once()
        self.assertEqual(list(self.capture_dir.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
