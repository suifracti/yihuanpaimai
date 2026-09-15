# -*- coding: utf-8 -*-
"""Real Replay End-to-End Smoke Test.

Proves that pre-recorded real-match video frames can drive the production
Vision Worker loop, Triggered Snapshot, and Settlement / Archiver pipeline
with complete isolation and 0 production-code modifications.
"""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
TESTS_DIR = PROJECT_ROOT / "tests"

for p in (str(PROJECT_ROOT), str(APP_DIR), str(CORE_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from async_snapshot_controller import AsyncTriggeredSnapshotController
from auto_archiver import AutoArchiver
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import validate_canonical_match_record_v7
from current_match import CurrentMatch
from harness.replay_frame_source import (
    ReplayFrameSource,
    bind_triggered_snapshot_to_replay,
)
from runtime_data import resolve_runtime_history_path
from settlement_truth_holder import ACTIVE_SETTLEMENT_TRUTH_HOLDER
from vision_pipeline import NTEVisionPipeline
from vision_worker_loop import run_vision_capture_loop


def _file_hash_and_count(path: Path) -> tuple[Optional[str], int]:
    if not path.exists():
        return None, 0
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
        count = len(data.get("records", []))
    except Exception:
        count = 0
    return digest, count


class TestRealReplayEndToEndSmoke(unittest.TestCase):
    def setUp(self):
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()

    def tearDown(self):
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()

    def test_real_replay_end_to_end_worker_snapshot_settlement_smoke(self):
        """AC1, AC2, AC3: Full match replay drives production worker loop, triggered snapshot, and isolated settlement."""
        # 0. Check production history before run (using actual LOCALAPPDATA path)
        prod_env = {"LOCALAPPDATA": os.environ.get("LOCALAPPDATA", "")}
        prod_history_path = resolve_runtime_history_path(env=prod_env)
        before_hash, before_count = _file_hash_and_count(prod_history_path)

        # 1. Setup isolated temporary data root
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_root = os.environ.get("YIHUAN_DATA_ROOT")
            os.environ["YIHUAN_DATA_ROOT"] = tmp_dir
            try:

                # 2. Prepare sequenced real replay frames
                replay_assets_dir = PROJECT_ROOT / "assets" / "replay_frames"
                settle_assets_dir = PROJECT_ROOT / "assets" / "settlement_frames"

                selected_frames = [
                    # Lobby
                    replay_assets_dir / "frame_0000s_00m00s.jpg",
                    # Loading transition
                    replay_assets_dir / "frame_0250s_04m10s.jpg",
                    # In-Auction R1
                    replay_assets_dir / "frame_0075s_01m15s.jpg",
                    # In-Auction R2
                    replay_assets_dir / "frame_0150s_02m30s.jpg",
                    # Settlement stabilization sequence (3 frames to trigger settlementReady)
                    settle_assets_dir / "sec_478.jpg",
                    settle_assets_dir / "sec_483.jpg",
                    settle_assets_dir / "sec_488.jpg",
                ]

                # Verify all frame assets exist
                for f in selected_frames:
                    self.assertTrue(f.exists(), f"Frame fixture missing: {f}")

                replay_source = ReplayFrameSource(selected_frames)

                # 3. Instantiate production pipeline and state
                pipeline = NTEVisionPipeline()
                pipeline._ensure_ocr()

                current_match = CurrentMatch()
                isolated_history_path = resolve_runtime_history_path()
                archiver = AutoArchiver(db_paths=[str(isolated_history_path)])

                # 4. Bind AsyncTriggeredSnapshotController to ReplayFrameSource (AC2)
                snapshot_results = []
                snapshot_controller = AsyncTriggeredSnapshotController(
                    current_match_provider=lambda: current_match,
                    target_titles=["异环"],
                )
                bind_triggered_snapshot_to_replay(snapshot_controller, replay_source)

                # Scripted action: trigger snapshot on R1 opening frame
                snapshot_executed = {"done": False}

                def _on_r1_frame(source: ReplayFrameSource):
                    if not snapshot_executed["done"]:
                        snapshot_executed["done"] = True
                        res = snapshot_controller.request_snapshot()
                        snapshot_results.append(res)
                        # Wait for snapshot background thread to finish
                        if snapshot_controller._worker_thread:
                            snapshot_controller._worker_thread.join(timeout=15.0)

                replay_source.on_frame_name("frame_0075s_01m15s", _on_r1_frame)

                # 5. Track observed scenes during worker loop (AC1)
                observed_scenes = []
                published_payloads = []

                async def _mock_publish(payload: dict):
                    published_payloads.append(payload)
                    scene = payload.get("scene") or (
                        "AUCTION_LOBBY" if payload.get("inLobby") else (
                            "AUCTION_LOADING" if payload.get("isLoading") else (
                                "SETTLEMENT" if payload.get("isSettlement") else "IN_AUCTION"
                            )
                        )
                    )
                    observed_scenes.append(scene)

                stop_flag = {"stop": False}

                # Frame provider that stops after all frames are consumed
                def _frame_provider():
                    hwnd, img, ts = replay_source.provide_frame()
                    if img is None:
                        stop_flag["stop"] = True
                    return hwnd, img, ts

                # Run production worker loop
                async def _run_loop():
                    await run_vision_capture_loop(
                        pipeline=pipeline,
                        stop_flag=stop_flag,
                        frame_provider=_frame_provider,
                        publish_fn=_mock_publish,
                        archiver=archiver,
                        fps=50.0,
                        current_match=current_match,
                    )

                asyncio.run(_run_loop())

                # === Assertions ===

                # AC1: Worker Replay - Observed full sequence of scenes
                self.assertIn("AUCTION_LOBBY", observed_scenes, "Must observe AUCTION_LOBBY")
                self.assertIn("AUCTION_LOADING", observed_scenes, "Must observe AUCTION_LOADING")
                self.assertIn("IN_AUCTION", observed_scenes, "Must observe IN_AUCTION")
                self.assertIn("SETTLEMENT", observed_scenes, "Must observe SETTLEMENT")

                # AC2: Triggered Snapshot on R1 frame with authentic business completion
                self.assertTrue(snapshot_executed["done"], "Triggered snapshot hook must have fired")
                self.assertGreaterEqual(len(snapshot_results), 1, "Snapshot request result must be captured")
                self.assertEqual(snapshot_results[0].get("status"), "recognizing", "Request must be accepted")
                last_res = snapshot_controller._last_result
                self.assertIsNotNone(last_res, "Snapshot controller must record last_result")
                self.assertTrue(last_res.get("ok"), f"Snapshot task must succeed: {last_res}")
                self.assertEqual(last_res.get("status"), "completed")
                self.assertGreaterEqual(last_res.get("appliedFactCount", 0), 1, "Must extract and apply at least 1 fact")
                self.assertIn("快照识别完成", last_res.get("summary", ""))
                self.assertEqual(current_match.facts.get("goldAvg"), 67571, "CurrentMatch must receive goldAvg from snapshot")

                # AC3: Settlement / Isolation
                # Check that isolated DB has the saved settlement draft record
                store = CanonicalHistoryStore(isolated_history_path)
                records = store.read_database().get("records", [])
                self.assertGreaterEqual(len(records), 1, "Must auto-archive settlement record to isolated DB")
                settle_rec = records[-1]
                self.assertEqual(settle_rec["schemaVersion"], 7)
                self.assertEqual(settle_rec["lifecycleStatus"], "DRAFT")
                self.assertEqual(settle_rec["settlement"]["clearingPrice"], 454444.0)
                self.assertIsNotNone(settle_rec["settlement"]["actualTotal"])
                self.assertGreater(settle_rec["settlement"]["actualTotal"], 0)
                self.assertIsNone(settle_rec["settlement"]["winner"])

                # Validate canonical v7 contract
                is_valid, reasons = validate_canonical_match_record_v7(settle_rec)
                self.assertTrue(is_valid, f"Archived record failed v7 validation: {reasons}")

                # Verify production history has 0 changes
                after_hash, after_count = _file_hash_and_count(prod_history_path)
                self.assertEqual(before_hash, after_hash, "Production history SHA256 must NOT change")
                self.assertEqual(before_count, after_count, "Production history record count must NOT change")

            finally:
                if old_root is not None:
                    os.environ["YIHUAN_DATA_ROOT"] = old_root
                else:
                    os.environ.pop("YIHUAN_DATA_ROOT", None)


if __name__ == "__main__":
    unittest.main()
