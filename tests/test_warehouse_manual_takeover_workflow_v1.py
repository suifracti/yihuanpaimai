"""Targeted unit tests for manual warehouse takeover workflow (Fix 6).

Covers:
- UI contract: #warehouse-manual-slot, confirmation dialog, 3 explicit actions.
- Host contract: prepare_manual, start_manual, capture_manual_page, finish_manual_capture, cancel_manual_capture.
- Duplicate page suppression during manual paging.
- Persistence contract: pageCount, reviewUnits, and finalized record immutability.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_placement_resolver import WarehousePlacementResolver
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from settlement_truth_evidence_contract import validate_settlement_evidence_original_v2
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from main_window import MainWindowBridge
from warehouse_capture_host import (
    WarehouseCaptureHost,
    STATE_MANUAL_CAPTURING,
    STATE_ALIGNING,
    STATE_IDLE,
)


class TestWarehouseManualTakeoverWorkflowV1(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_manual_wh_", dir=PROJECT_ROOT / "build"))
        self.history_path = self.temp_dir / "history" / "异环拍卖数据.json"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = CanonicalHistoryStore(str(self.history_path))
        self.evidence_store = SettlementEvidenceStoreV2(self.temp_dir)
        # Exercise real geometry, evidence and persistence, without rerunning
        # the unrelated full identity-reference matrix. Missing references must
        # keep identity unknown; they cannot relax any confirmation threshold.
        resolver = WarehousePlacementResolver(manifest_path=self.temp_dir / "no-identity-references.json")
        resolver_patch = patch("warehouse_capture_production.get_production_placement_resolver", return_value=resolver)
        resolver_patch.start()
        self.addCleanup(resolver_patch.stop)
        self.record_id = "test_manual_match_20260913"

        base_record = build_canonical_match_record_v7(
            match_id=self.record_id,
            played_at="2026-09-13T21:20:00Z",
            lifecycle_status="FINALIZED",
            source="manual",
            environment={"venue": "珊瑚场", "box": "实木宝箱", "fieldCondition": "standard"},
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 850000,
                "actualTotal": 1000000,
                "realizedProfit": 150000,
                "winner": "测试玩家",
                "acquired": True,
            },
        )
        self.store.persist_record_transactional(base_record, is_finalized=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ui_contract_elements_exist(self):
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        css = (CORE_DIR / "main_window.css").read_text(encoding="utf-8")

        self.assertIn('id="warehouse-manual-slot"', html)
        self.assertIn("即将由人工分页截取仓库当前页并推算，是否继续？", html)
        self.assertIn('id="warehouse-manual-snap-btn"', html)
        self.assertIn('id="warehouse-manual-finish-btn"', html)
        self.assertIn('id="warehouse-manual-cancel-btn"', html)

        self.assertIn(".warehouse-manual-slot", css)
        self.assertIn(".warehouse-manual-controls", css)

        self.assertIn("prepare_warehouse_manual_takeover", js)
        self.assertIn("start_warehouse_manual_takeover", js)
        self.assertIn("capture_warehouse_manual_page", js)
        self.assertIn("finish_warehouse_manual_capture", js)
        self.assertIn("cancel_warehouse_manual_capture", js)

    def test_host_manual_capture_lifecycle(self):
        frame1 = np.full((1080, 1920, 3), 10, dtype=np.uint8)
        frame2 = np.full((1080, 1920, 3), 20, dtype=np.uint8)

        frames = [frame1, frame1, frame2]
        frame_idx = 0

        def fake_frame_provider():
            nonlocal frame_idx
            idx = min(frame_idx, len(frames) - 1)
            frame_idx += 1
            return frames[idx]

        snap_data = {
            "hwnd": 12345,
            "recordStableKey": self.record_id,
            "storeAvailable": True,
        }

        host = WarehouseCaptureHost(
            bindings_probe=lambda: snap_data,
            frame_provider_factory=lambda: fake_frame_provider,
            store_factory=lambda: self.evidence_store,
            driver_available=False,
        )

        prep = host.prepare_manual()
        self.assertTrue(prep["ok"])
        self.assertEqual(prep["reason"], "MANUAL_READY")

        started = host.start_manual(self.record_id)
        self.assertTrue(started["ok"])
        self.assertEqual(host.presentation_payload()["state"], STATE_MANUAL_CAPTURING)

        # Page 1
        res1 = host.capture_manual_page()
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["pageCount"], 1)
        descriptor = host._manual_pages[0]
        self.assertTrue(validate_settlement_evidence_original_v2(descriptor)[0])
        self.assertTrue(self.evidence_store.verify(descriptor)["ok"])
        self.assertNotIn("sequenceIndex", descriptor)
        self.assertTrue(descriptor["evidenceId"].startswith("sev2_"))

        # Page 2 duplicate
        res2 = host.capture_manual_page()
        self.assertTrue(res2["ok"])
        self.assertTrue(res2.get("duplicate"))
        self.assertEqual(res2["pageCount"], 1)

        # Page 3 distinct
        res3 = host.capture_manual_page()
        self.assertTrue(res3["ok"])
        self.assertEqual(res3["pageCount"], 2)

        # Cancel resets state
        cancelled = host.cancel_manual_capture()
        self.assertTrue(cancelled["ok"])
        self.assertNotEqual(host.presentation_payload()["state"], STATE_MANUAL_CAPTURING)

    def test_manual_original_failure_does_not_accept_a_page(self):
        frame = np.full((1080, 1920, 3), 10, dtype=np.uint8)
        host = WarehouseCaptureHost(
            bindings_probe=lambda: {"hwnd": 12345, "recordStableKey": self.record_id, "storeAvailable": True},
            frame_provider_factory=lambda: lambda: frame,
            store_factory=lambda: self.evidence_store,
            driver_available=False,
        )
        self.assertTrue(host.start_manual(self.record_id)["ok"])
        with patch.object(self.evidence_store, "save_original", side_effect=OSError("storage unavailable")):
            result = host.capture_manual_page()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "STORE_FAILED")
        self.assertEqual(result["pageCount"], 0)
        self.assertEqual(host._manual_pages, [])
        self.assertEqual(host._manual_frames, {})
        self.assertIn("原图保存失败", host.presentation_payload()["message"])
        # The same real store accepts a retry after the transient failure.
        self.assertTrue(host.capture_manual_page()["ok"])
        self.assertTrue(self.evidence_store.verify(host._manual_pages[0])["ok"])

    def test_three_real_top_pages_and_duplicate_remain_partial(self):
        root = PROJECT_ROOT / "build/codex_other_video_20260912/134043-bounded-replay"
        report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        sources = [root / "store" / segment["fileOriginal"]["relativePath"]
                   for segment in report["coverage"]["segments"]]
        host = WarehouseCaptureHost(store_factory=lambda: self.evidence_store, driver_available=False)
        before = self.store.get_record(self.record_id)
        # These existing source pages have a TOP proof and no BOTTOM proof.
        # Coverage/physical-ledger regression does not need the exhaustive
        # placement enumerator; its existing optional-resolver path stays real.
        with patch("warehouse_capture_production.get_production_placement_resolver", return_value=None):
            result = host.process_capture_images(self.record_id, sources + [sources[0]], history_store=self.store)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["persisted"])
        self.assertEqual(result["pageCount"], 3)
        self.assertEqual(result["coverageStatus"], "PARTIAL")
        self.assertEqual(result["coverage"]["terminationReason"], "MISSING_BOTTOM")
        self.assertIsNone(result["coverage"]["bottomEndpoint"])
        self.assertEqual([segment["sequenceIndex"] for segment in result["coverage"]["segments"]], [0, 1, 2])
        for segment in result["coverage"]["segments"]:
            self.assertTrue(validate_settlement_evidence_original_v2(segment["fileOriginal"])[0])
            self.assertTrue(self.evidence_store.verify(segment["fileOriginal"])["ok"])
        after = self.store.get_record(self.record_id)
        for key in ("clearingPrice", "actualTotal", "realizedProfit", "winner", "acquired"):
            self.assertEqual(after["settlement"][key], before["settlement"][key])
        self.assertEqual(after.get("predictionSnapshot"), before.get("predictionSnapshot"))
        self.assertEqual(after["settlement"]["warehousePageCount"], 3)

    def test_real_adjacent_crops_do_not_bridge_the_unproven_bottom_gap(self):
        root = PROJECT_ROOT / "tests/fixtures/warehouse_overlap_v1"
        names = ["pair_a_prev.png", "pair_a_next.png", "pair_b_next.png", "bottom.png"]
        pages = [self.evidence_store.save_original(
            record_stable_key=self.record_id, kind="warehouse-segment",
            image_bytes=(root / name).read_bytes(), evidence_origin="user-import",
        ) for name in names]
        host = WarehouseCaptureHost(store_factory=lambda: self.evidence_store, driver_available=False)
        with patch("warehouse_capture_production.get_production_placement_resolver", return_value=None):
            result = host._process_saved_pages(self.record_id, pages, history_store=self.store, already_cropped=True)
        self.assertTrue(result["ok"], result.get("error"))
        coverage = result["coverage"]
        self.assertEqual(coverage["coverageStatus"], "PARTIAL")
        self.assertIsNotNone(coverage["topEndpoint"])
        self.assertIsNotNone(coverage["bottomEndpoint"])
        # A genuine bottom view cannot fill a missing adjacent pixel-overlap link.
        self.assertTrue(coverage["gaps"])
        self.assertEqual(coverage["terminationReason"], "MISSING_OVERLAP")
        self.assertEqual(len(coverage["overlapProofs"]), 2)
        self.assertEqual(result["confirmedCount"], 0)
        self.assertTrue(any(len({obs["evidenceId"] for obs in unit.get("observations", [])}) >= 2
                            for unit in result["packet"].get("tracks", [])))
        self.assertNotEqual(host.presentation_payload()["state"], "COMPLETE")

    def test_real_history_write_failure_is_visible_and_keeps_review_packet(self):
        frame = np.full((1080, 1920, 3), 10, dtype=np.uint8)
        payload = cv2.imencode(".png", frame)[1].tobytes()
        page = self.evidence_store.save_original(
            record_stable_key=self.record_id, kind="warehouse-segment", image_bytes=payload,
        )
        host = WarehouseCaptureHost(store_factory=lambda: self.evidence_store, driver_available=False)
        before = self.history_path.read_bytes()
        # Inject an actual atomic file replacement failure after original intake.
        with patch("canonical_history_store.os.replace", side_effect=OSError("disk unavailable")):
            result = host._process_saved_pages(self.record_id, [page], history_store=self.store)
        self.assertFalse(result["ok"])
        self.assertFalse(result["persisted"])
        self.assertEqual(result["reason"], "HISTORY_NOT_SAVED")
        view = host.presentation_payload()
        self.assertEqual(view["state"], "ERROR")
        self.assertTrue(view["packetAvailable"])
        self.assertIn("尚未保存本局记录", view["message"])
        self.assertEqual(self.history_path.read_bytes(), before)
        self.assertTrue(self.evidence_store.verify(page)["ok"])
        # The stored original can be retried without a new game capture.
        retry = host._process_saved_pages(self.record_id, [page], history_store=self.store)
        self.assertTrue(retry["ok"], retry.get("error"))
        self.assertTrue(retry["persisted"])

    def test_manual_worker_uses_saved_original_and_shared_processing(self):
        frame = np.full((1080, 1920, 3), 10, dtype=np.uint8)
        page = self.evidence_store.save_original(
            record_stable_key=self.record_id, kind="warehouse-segment",
            image_bytes=cv2.imencode(".png", frame)[1].tobytes(),
        )
        host = WarehouseCaptureHost(store_factory=lambda: self.evidence_store,
                                    history_store_factory=lambda: self.store, driver_available=False)
        # No live or mutable frame buffer is required for the manual continuation.
        host._run_manual_processing(self.record_id, [page], {})
        self.assertNotEqual(host.presentation_payload()["state"], "ERROR")
        self.assertEqual(self.store.get_record(self.record_id)["settlement"]["warehousePageCount"], 1)

    def test_manual_processing_cannot_overwrite_a_new_capture(self):
        frame = np.full((1080, 1920, 3), 10, dtype=np.uint8)
        host = WarehouseCaptureHost(
            bindings_probe=lambda: {"hwnd": 12345, "recordStableKey": self.record_id, "storeAvailable": True},
            frame_provider_factory=lambda: lambda: frame,
            store_factory=lambda: self.evidence_store, driver_available=False,
        )
        self.assertTrue(host.start_manual(self.record_id)["ok"])
        self.assertTrue(host.capture_manual_page()["ok"])
        entered, release = threading.Event(), threading.Event()
        workers = []
        def delayed_processing(*args, **kwargs):
            workers.append(threading.current_thread())
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test worker release timed out")
            return {}
        with patch.object(host, "_process_saved_pages", side_effect=delayed_processing):
            try:
                self.assertTrue(host.finish_manual_capture()["ok"])
                self.assertTrue(entered.wait(1))
                self.assertFalse(host.start_manual(self.record_id)["ok"])
                self.assertFalse(host.cancel_manual_capture()["ok"])
                competing = host.process_capture_images(self.record_id, [frame], history_store=self.store)
                self.assertFalse(competing["ok"])
                self.assertEqual(competing["reason"], "ALREADY_RUNNING")
                self.assertEqual(host.presentation_payload()["state"], "ALIGNING")
            finally:
                release.set()
                if workers:
                    workers[0].join(2)
        self.assertFalse(host._manual_processing)
        self.assertTrue(host.start_manual(self.record_id)["ok"])

    def test_bridge_dispatch_manual_takeover(self):
        class _FakeOverlay:
            def __init__(self):
                self.Visible = True
            def Show(self):
                self.Visible = True
            def Hide(self):
                self.Visible = False

        from main_window import OverlayVisibilityController

        host = WarehouseCaptureHost(
            bindings_probe=lambda: {"hwnd": 1234, "recordStableKey": self.record_id, "storeAvailable": True},
            driver_available=False,
        )
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            warehouse_capture_host=host,
        )

        res_prep = bridge.dispatch({"action": "prepare_warehouse_manual_takeover"})
        self.assertTrue(res_prep["warehouseCaptureCommand"]["ok"])

        res_start = bridge.dispatch({"action": "start_warehouse_manual_takeover"})
        self.assertTrue(res_start["warehouseCaptureCommand"]["ok"])
        self.assertEqual(res_start["warehouseCapture"]["state"], STATE_MANUAL_CAPTURING)

        res_cancel = bridge.dispatch({"action": "cancel_warehouse_manual_capture"})
        self.assertTrue(res_cancel["warehouseCaptureCommand"]["ok"])
        self.assertNotEqual(res_cancel["warehouseCapture"]["state"], STATE_MANUAL_CAPTURING)


if __name__ == "__main__":
    unittest.main()
