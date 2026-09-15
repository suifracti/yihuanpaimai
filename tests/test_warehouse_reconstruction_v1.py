"""Integration tests for capture-session reconstruction wiring."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from runtime_data import runtime_data_paths
from settlement_evidence_store_v2 import (
    STORE_RELATIVE_ROOT,
    SettlementEvidenceStoreError,
    SettlementEvidenceStoreV2,
)
from warehouse_capture_host import PRESENTATION_KEYS, WarehouseCaptureHost
from warehouse_capture_session import (
    PRODUCTION_SCROLL_DRIVER_ENABLED,
    WarehouseCaptureSession,
    get_production_scroll_driver,
)
from warehouse_coverage_ledger import STATUS_COMPLETE, STATUS_PARTIAL
from warehouse_reconstruction import (
    PACKET_FAILED,
    PACKET_READY,
    PACKET_UNAVAILABLE,
    WarehouseReconstructionProcessor,
)
from warehouse_scrollbar_observation import (
    CHANGE_CHANGED,
    CHANGE_UNKNOWN,
    STATE_BOTTOM,
    STATE_MIDDLE,
    STATE_TOP,
)
from warehouse_segment_overlap import DIR_DOWN, STATUS_VERIFIED, align_warehouse_segments

OVERLAP = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_overlap_v1"
KEY = "recWHRecon01"


def _load(name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(OVERLAP / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(OVERLAP / name)
    return image


def _bgr(color, size=(48, 32)) -> np.ndarray:
    image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    image[:] = color
    return image


def _obs(state, change=CHANGE_UNKNOWN, fingerprint=""):
    return {
        "scrollState": state,
        "segmentChange": change,
        "confidence": 0.9,
        "warehouseFingerprint": fingerprint or state.lower(),
        "thumbPosition": 0.1,
        "thumbLength": 0.2,
        "trackBox": [1, 1, 2, 10],
        "thumbBox": [1, 1, 2, 3],
        "sourceId": state,
    }


def _verified_down(*_a, prev_id="", next_id="", **_k):
    return {
        "status": STATUS_VERIFIED,
        "direction": DIR_DOWN,
        "verticalOffsetPx": -40,
        "reason": "CONTENT_ALIGNED",
        "prevId": prev_id,
        "nextId": next_id,
        "supportCount": 5,
    }


class ScriptedFrames:
    def __init__(self, frames):
        self.frames = list(frames)
        self.captures = 0

    def capture(self):
        self.captures += 1
        return self.frames[min(self.captures - 1, len(self.frames) - 1)]


class ScriptedObserver:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def observe(self, _frame, **_kwargs):
        self.calls += 1
        return dict(self.results[min(self.calls - 1, len(self.results) - 1)])


class RecordingScroll:
    def __init__(self):
        self.requests = []

    def request_next_scroll(self):
        self.requests.append("DOWN")


class FailingStore:
    def save_original(self, **_kwargs):
        raise SettlementEvidenceStoreError("DISK_FULL", "no")


class WarehouseReconstructionV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.store = SettlementEvidenceStoreV2(self.root)
        self.prod = runtime_data_paths()
        self.prod_history = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.driver = RecordingScroll()

    def tearDown(self):
        after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.assertEqual(after, self.prod_history)
        self.assertFalse((PROJECT_ROOT / STORE_RELATIVE_ROOT).exists())
        self.tmp.cleanup()

    def _session(self, frames, observations, **kwargs):
        return WarehouseCaptureSession(
            frame_provider=kwargs.pop("frame_provider", ScriptedFrames(frames)),
            scene_validator=kwargs.pop(
                "scene_validator",
                lambda _raw: {"isSettlement": True, "stable": True, "recordStableKey": KEY},
            ),
            scroll_requester=kwargs.pop("scroll_requester", self.driver),
            status_sink=kwargs.pop("status_sink", None),
            clock=kwargs.pop("clock", lambda: 0.0),
            idle=kwargs.pop("idle", lambda _dt: None),
            timeout_s=kwargs.pop("timeout_s", 20.0),
            store=kwargs.pop("store", self.store),
            observer=kwargs.pop("observer", ScriptedObserver(observations)),
            aligner=kwargs.pop("aligner", _verified_down),
            max_steps=kwargs.pop("max_steps", 16),
            already_cropped=kwargs.pop("already_cropped", True),
            reconstruction_factory=kwargs.pop("reconstruction_factory", None),
            **kwargs,
        )

    def test_store_failure_does_not_create_observations(self):
        processor_holder = {}

        def factory(key):
            processor_holder["p"] = WarehouseReconstructionProcessor(key)
            return processor_holder["p"]

        result = self._session(
            [_bgr((1, 2, 3))],
            [_obs(STATE_TOP)],
            store=FailingStore(),
            reconstruction_factory=factory,
        ).start()
        self.assertEqual(result["terminationReason"], "STORE_FAILED")
        self.assertEqual(result["savedDescriptors"], [])
        snap = processor_holder.get("p")
        if snap is not None:
            self.assertEqual(snap.readonly_snapshot()["processedCount"], 0)
            self.assertIsNone(snap.packet_copy())

    def test_real_8_12_16_chain_is_partial_and_deduped(self):
        frames = [_load("pair_a_prev.png"), _load("pair_a_next.png"), _load("pair_b_next.png")]
        session = self._session(
            frames,
            [
                _obs(STATE_TOP, CHANGE_UNKNOWN, "t"),
                _obs(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                _obs(STATE_MIDDLE, CHANGE_CHANGED, "m2"),
            ],
            aligner=align_warehouse_segments,
            max_steps=2,
        )
        result = session.start()
        self.assertEqual(result["coverageStatus"], STATUS_PARTIAL)
        self.assertNotEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(len(result["savedDescriptors"]), 3)
        packet = session.review_packet()
        self.assertIsNotNone(packet)
        self.assertEqual(packet["warehouseCoverage"]["status"], STATUS_PARTIAL)
        self.assertNotIn("totalItems", packet["summary"])
        shared = [
            track
            for track in packet["tracks"]
            if 5 in (track.get("widthCandidates") or [])
            and len(track["observations"]) >= 3
        ]
        self.assertTrue(shared, [ (t["trackId"], t.get("widthCandidates"), len(t["observations"])) for t in packet["tracks"][:8]])
        self.assertTrue(all(c["identityStatus"] == "CANDIDATE_ONLY" for t in packet["tracks"] for c in t["candidates"]))
        self.assertTrue(all(t["selectedCatalogId"] is None for t in packet["tracks"]))

    def test_injected_complete_chain_keeps_review_required(self):
        frames = [_load("pair_a_prev.png"), _load("pair_a_next.png"), _load("pair_b_next.png")]
        session = self._session(
            frames,
            [
                _obs(STATE_TOP, CHANGE_UNKNOWN, "t"),
                _obs(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                _obs(STATE_BOTTOM, CHANGE_CHANGED, "b"),
            ],
            aligner=_verified_down,
        )
        result = session.start()
        self.assertEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(result["packetStatus"], PACKET_READY)
        packet = session.review_packet()
        self.assertEqual(packet["warehouseCoverage"]["status"], STATUS_COMPLETE)
        self.assertEqual(packet["reviewStatus"], "REVIEW_REQUIRED")
        self.assertEqual(packet["summary"]["reviewedIdentityCount"], 0)
        self.assertTrue(all(t["identityStatus"] == "REVIEW_REQUIRED" for t in packet["tracks"]))
        self.assertTrue(all(t["selectedCatalogId"] is None for t in packet["tracks"]))

    def test_user_stop_and_scene_left_keep_evidence_and_partial_packet(self):
        token = {"c": False}

        class Token:
            def is_cancelled(self):
                return token["c"]

        def sink(event):
            if event.get("event") == "segment_saved":
                token["c"] = True

        stopped = self._session(
            [_load("pair_a_prev.png"), _load("pair_a_next.png")],
            [_obs(STATE_TOP), _obs(STATE_MIDDLE, CHANGE_CHANGED)],
            cancellation_token=Token(),
            status_sink=sink,
            aligner=align_warehouse_segments,
        ).start()
        self.assertEqual(stopped["terminationReason"], "USER_STOP")
        self.assertEqual(stopped["coverageStatus"], STATUS_PARTIAL)
        self.assertEqual(len(stopped["savedDescriptors"]), 1)

        class CountingValidator:
            def __init__(self):
                self.n = 0

            def validate(self, _raw):
                self.n += 1
                if self.n == 1:
                    return {"isSettlement": True, "stable": True, "recordStableKey": KEY}
                return {"isSettlement": False, "stable": True, "recordStableKey": KEY}

        left = self._session(
            [_load("pair_a_prev.png"), _load("pair_a_next.png")],
            [_obs(STATE_TOP), _obs(STATE_MIDDLE, CHANGE_CHANGED)],
            scene_validator=CountingValidator(),
            aligner=align_warehouse_segments,
        ).start()
        self.assertEqual(left["terminationReason"], "SCENE_LEFT")
        self.assertGreaterEqual(len(left["savedDescriptors"]), 1)
        self.assertIn(left["packetStatus"], {PACKET_READY, PACKET_UNAVAILABLE})

    def test_exactly_once_and_duplicate_hash(self):
        processor = WarehouseReconstructionProcessor(KEY)
        frame = _load("pair_a_prev.png")
        desc = self.store.save_original(
            record_stable_key=KEY,
            kind="warehouse-segment",
            image_bytes=cv2.imencode(".png", frame)[1].tobytes(),
        )
        first = processor.accept_segment(frame, desc, 0, _obs(STATE_TOP), None)
        second = processor.accept_segment(frame, desc, 1, _obs(STATE_MIDDLE), _verified_down())
        self.assertEqual(first["reason"], "OK")
        self.assertEqual(second["reason"], "DUPLICATE")
        self.assertEqual(processor.readonly_snapshot()["processedCount"], 1)

    def test_grid_unknown_does_not_create_components_or_stop_capture(self):
        def unknown_grid(*_a, **_k):
            return {"grid": {"status": "UNKNOWN", "reason": "EMPTY_FRAME"}, "components": []}

        def factory(key):
            return WarehouseReconstructionProcessor(key, observe_grid=unknown_grid)

        result = self._session(
            [_bgr((9, 9, 9)), _bgr((8, 8, 8)), _bgr((7, 7, 7))],
            [_obs(STATE_TOP), _obs(STATE_MIDDLE, CHANGE_CHANGED), _obs(STATE_BOTTOM, CHANGE_CHANGED)],
            reconstruction_factory=factory,
        ).start()
        self.assertEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertIn("GRID_UNKNOWN", result["reconstructionWarnings"])
        self.assertEqual(result["terminationReason"], "COMPLETE")

    def test_packet_failure_does_not_change_coverage(self):
        def boom(**_kwargs):
            raise RuntimeError("packet explode")

        def factory(key):
            return WarehouseReconstructionProcessor(key, packet_builder=boom)

        result = self._session(
            [_load("pair_a_prev.png"), _load("pair_a_next.png"), _load("pair_b_next.png")],
            [_obs(STATE_TOP), _obs(STATE_MIDDLE, CHANGE_CHANGED), _obs(STATE_BOTTOM, CHANGE_CHANGED)],
            reconstruction_factory=factory,
        ).start()
        self.assertEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(result["terminationReason"], "COMPLETE")
        self.assertEqual(result["packetStatus"], PACKET_FAILED)
        self.assertFalse(result["packetAvailable"])
        self.assertIsNone(result["packetFingerprint"])

    def test_presentation_whitelist_and_production_driver(self):
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        self.assertIsNotNone(get_production_scroll_driver())
        host = WarehouseCaptureHost()
        payload = host.presentation_payload()
        self.assertEqual(set(payload), set(PRESENTATION_KEYS))
        self.assertIn("packetAvailable", payload)
        self.assertIn("packetStatus", payload)
        self.assertIn("packetFingerprint", payload)
        self.assertIn("reviewStatus", payload)
        self.assertNotIn("candidates", payload)
        self.assertNotIn("ledger", payload)
        self.assertNotIn("relativePath", payload)
        src = (CORE_DIR / "warehouse_reconstruction.py").read_text(encoding="utf-8")
        self.assertNotIn("canonical_history", src)
        self.assertNotIn("knownItems", src)
        self.assertNotIn("candidates[0]", src)
        self.assertNotIn("warehouse_vision", src)

    def test_fingerprint_is_deterministic(self):
        frames = [_load("pair_a_prev.png"), _load("pair_a_next.png"), _load("pair_b_next.png")]
        first = self._session(
            frames,
            [_obs(STATE_TOP), _obs(STATE_MIDDLE, CHANGE_CHANGED), _obs(STATE_BOTTOM, CHANGE_CHANGED)],
        ).start()
        store2 = SettlementEvidenceStoreV2(self.root / "b")
        second = self._session(
            frames,
            [_obs(STATE_TOP), _obs(STATE_MIDDLE, CHANGE_CHANGED), _obs(STATE_BOTTOM, CHANGE_CHANGED)],
            store=store2,
        ).start()
        self.assertEqual(first["packetStatus"], second["packetStatus"])
        if first["packetFingerprint"]:
            self.assertEqual(first["packetFingerprint"], second["packetFingerprint"])


if __name__ == "__main__":
    unittest.main()
