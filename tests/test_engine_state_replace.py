"""engine_state.json replace must survive one Windows sharing refusal."""
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "architecture/v2/host/engine_v22"))
engine = importlib.import_module("nte_engine_v22")


class EngineStateReplaceTests(unittest.TestCase):
    def test_live_identity_reaches_existing_worker_without_blocking_frame_consumer(self):
        started, release = threading.Event(), threading.Event()

        class Vision:
            def process_frame(self, frame):
                started.set()
                release.wait(2)
                return {"slots": [], "inputPixel": int(frame[0, 0, 0])}

        module = types.ModuleType('warehouse_vision')
        module.WarehouseVisionV1 = Vision
        from deferred_identity_analyzer import DeferredIdentityAnalyzer
        analyzer = DeferredIdentityAnalyzer()
        frame = np.full((8, 8, 3), 42, dtype=np.uint8)
        host = types.SimpleNamespace(
            pipeline=types.SimpleNamespace(take_deferred_identity=lambda: {'kind': 'warehouse', 'round': 1}),
            _identity_scope_kind=lambda context: 'warehouse', _identity_generation=lambda: 3,
            _identity_analyzer=analyzer, _warehouse_viewport_scope=types.SimpleNamespace(current_key='viewport'),
            current_match=types.SimpleNamespace(id='match', _seq=1, facts_revision=1),
            session_id='session', generation_id=1, data_origin='offline-test', log=lambda *a, **k: None)
        item = {'identityInvalidationGeneration': 3, 'bgr': frame,
                'header': {'sequence': 7, 'captureTimestampNs': 100}, 'rawSha256': 'source-hash'}
        try:
            with patch.dict(sys.modules, {'warehouse_vision': module}):
                engine.RealEngine._submit_deferred_identity(host, item, {'scene': 'IN_AUCTION', 'round': 1})
                self.assertTrue(started.wait(1), 'live path must submit warehouse work')
                self.assertFalse(release.is_set(), 'dispatch must return while recognition is still busy')
                self.assertEqual(analyzer.poll(), [])
                frame[:] = 0  # consumer can release/reuse its frame after copying
                release.set()
                deadline = time.monotonic() + 2
                results = []
                while not results and time.monotonic() < deadline:
                    results = analyzer.poll()
                    time.sleep(.001)
                self.assertEqual(results[0]['warehouseVision']['inputPixel'], 42)
                self.assertEqual(results[0]['frameSequence'], 7)
                self.assertEqual(results[0]['matchId'], 'match')
        finally:
            release.set()
            analyzer.close()

    def test_one_permission_error_then_the_same_file_lands(self):
        calls = {"n": 0}
        original = engine.os.replace

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("denied")
            return original(src, dst)

        engine.os.replace = flaky
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "engine_state.json"
                engine._atomic_json(path, {"ready": True})
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ready": True})
                self.assertEqual(calls["n"], 2)
                self.assertFalse(path.with_name(path.name + ".tmp").exists())
        finally:
            engine.os.replace = original

    def test_repeated_permission_error_stays_an_error(self):
        original = engine.os.replace

        def denied(src, dst):
            raise PermissionError("denied")

        engine.os.replace = denied
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "engine_state.json"
                with self.assertRaises(PermissionError):
                    engine._atomic_json(path, {"ready": False})
                self.assertFalse(path.exists())
        finally:
            engine.os.replace = original

    def test_live_bid_loop_dispatches_warehouse_identity_and_keeps_settlement(self):
        seen = []

        class Host:
            _identity_analyzer = None

            def __init__(self, kind):
                self.kind = kind

            def _identity_scope_kind(self, context):
                return self.kind

            def _identity_generation(self):
                seen.append(self.kind)
                return 3

            def log(self, *args, **kwargs):
                seen.append("log")

            @property
            def pipeline(self):
                kind = self.kind
                return type("Pipe", (), {
                    "take_deferred_identity": staticmethod(lambda: {"kind": kind, "round": 1}),
                })()

        Host._submit_deferred_identity = engine.RealEngine._submit_deferred_identity
        # No switch gates deferred identity: the product switch drives dispatch,
        # recognition itself only follows the observed frame.
        Host("warehouse")._submit_deferred_identity({}, {"scene": "IN_AUCTION"})
        self.assertEqual(seen[:2], ["warehouse", "log"])
        seen.clear()
        Host("settlement")._submit_deferred_identity({}, {"scene": "SETTLEMENT"})
        self.assertEqual(seen[:2], ["settlement", "log"])
        seen.clear()
        Host("warehouse")._submit_deferred_identity({}, {"scene": "IN_AUCTION"})
        self.assertEqual(seen[:2], ["warehouse", "log"])


if __name__ == "__main__":
    unittest.main()
