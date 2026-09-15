"""Targeted regression test for 4D2D1Q-UAT3:
Persist settlement main stable-frame and establish History binding upon warehouse capture.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import cv2
import numpy as np

from canonical_history_store import CanonicalHistoryStore
from settlement_evidence_store_v2 import KIND_MAIN, SettlementEvidenceStoreV2
from warehouse_capture_host import WarehouseCaptureHost
from settlement_review import SettlementReviewService
from runtime_data import runtime_data_paths


class TestSettlementMainFrameWarehouseBindingV1(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmp_dir.name).resolve()
        os.environ["YIHUAN_DATA_ROOT"] = str(self.data_root)

        # Snapshot production history baseline directly from LOCALAPPDATA to guarantee zero mutation
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        self.prod_history_file = (
            Path(local_app_data) / "异环拍卖助手" / "data" / "history" / "异环拍卖数据.json"
            if local_app_data
            else None
        )
        self.prod_history_sha = (
            hashlib.sha256(self.prod_history_file.read_bytes()).hexdigest()
            if self.prod_history_file and self.prod_history_file.is_file()
            else None
        )

        self.store = SettlementEvidenceStoreV2(self.data_root)
        self.record_key = "rec_uat3_match_001"

        # Create dummy settlement BGR frame (1920x1080)
        self.frame = np.full((1080, 1920, 3), 42, dtype=np.uint8)
        cv2.putText(self.frame, "SETTLEMENT TEST FRAME", (200, 200), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)

    def tearDown(self):
        # Verify production history remains strictly untouched
        if self.prod_history_file and self.prod_history_file.is_file():
            after_sha = hashlib.sha256(self.prod_history_file.read_bytes()).hexdigest()
            self.assertEqual(after_sha, self.prod_history_sha, "Production history must not be modified!")
        self.tmp_dir.cleanup()

    def test_warehouse_capture_persists_main_frame_and_binds_to_history(self):
        """Verify that triggering warehouse capture saves main settlement frame before session runs,
        and preserves it even if warehouse capture later stops or returns PARTIAL."""
        session_started = []

        class MockSession:
            def __init__(self, **kwargs):
                self.status_sink = kwargs.get("status_sink")

            def start(self):
                session_started.append(True)
                # Simulate warehouse capture being stopped / returning PARTIAL coverage
                return {
                    "accepted": True,
                    "coverageStatus": "PARTIAL",
                    "terminationReason": "USER_STOP",
                    "savedDescriptors": [],
                }

            def review_packet(self):
                return None

        bindings = {
            "isSettlement": True,
            "stable": True,
            "recordStableKey": self.record_key,
            "hwnd": 1234,
            "scrollState": "TOP",
            "storeAvailable": True,
            "foreground": True,
            "visible": True,
            "minimized": False,
        }

        class MockWindowAdapter:
            def is_window(self, hwnd):
                return True
            def is_window_visible(self, hwnd):
                return True
            def is_iconic(self, hwnd):
                return False
            def get_foreground_window(self):
                return 1234

        host = WarehouseCaptureHost(
            session_factory=lambda **kw: MockSession(**kw),
            driver_available=True,
            bindings_probe=lambda: bindings,
            scene_probe=lambda: bindings,
            window_adapter=MockWindowAdapter(),
            store_factory=lambda: self.store,
            frame_provider_factory=lambda: (lambda: self.frame),
            arming_required=False,
        )

        # 1. Start warehouse capture host
        res = host.start()
        self.assertTrue(res.get("ok"))

        # Wait for worker thread to complete execution
        if host._thread is not None:
            host._thread.join(timeout=5.0)

        # 2. Verify warehouse session did start
        self.assertTrue(session_started, "Session should have been started by host")

        # 3. Verify main settlement frame evidence is persisted in Store v2
        evidences = self.store.list_record_evidence(self.record_key)
        main_ev = [e for e in evidences if e.get("kind") == KIND_MAIN]
        self.assertEqual(len(main_ev), 1, "Expected exactly 1 main settlement evidence persisted")

        descriptor = main_ev[0]
        self.assertEqual(descriptor.get("recordStableKey"), self.record_key)
        self.assertEqual(descriptor.get("kind"), KIND_MAIN)

        # 4. Verify evidence file on disk and hash
        evidence_path = self.data_root / descriptor["relativePath"]
        self.assertTrue(evidence_path.is_file(), f"Evidence file missing at {evidence_path}")
        file_bytes = evidence_path.read_bytes()
        calculated_sha = hashlib.sha256(file_bytes).hexdigest()
        self.assertEqual(descriptor["sha256"], calculated_sha)

        # 5. Verify SettlementReviewService can load this evidence for the record
        history_store = CanonicalHistoryStore(self.data_root / "history" / "异环拍卖数据.json")
        history_store.persist_record_transactional(
            {
                "schemaVersion": "match-record.v7",
                "productVersion": "0.67.0-alpha",
                "id": self.record_key,
                "lifecycleStatus": "FINALIZED",
                "playedAt": "2026-08-31T09:20:00Z",
                "roundCount": 5,
                "source": "manual",
                "costs": {"entryFee": 0, "total": 0},
                "lot": {"venue": "hotel", "box": "gold", "fieldCondition": "none"},
                "qualities": {},
                "bidding": {"seats": []},
                "settlement": {
                    "status": "verified",
                    "verified": True,
                    "clearingPrice": 100000,
                    "actualTotal": 150000,
                    "realizedProfit": 50000,
                    "acquired": True,
                    "winner": "本人拍下",
                    "settlementItems": [],
                },
            },
            is_finalized=True,
        )

        review_service = SettlementReviewService(
            history_path_provider=lambda: str(self.data_root / "history" / "异环拍卖数据.json"),
            data_root_provider=lambda: str(self.data_root),
        )

        session_dto = review_service.create_review_session(self.record_key)
        self.assertTrue(session_dto.get("ok"))
        review_obj = session_dto.get("review") or {}
        screenshot = review_obj.get("screenshot") or {}
        self.assertTrue(screenshot.get("available"), "Screenshot should be available in review session")
        self.assertEqual(screenshot.get("sha256"), calculated_sha)
        self.assertTrue(str(screenshot.get("dataUrl") or "").startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
