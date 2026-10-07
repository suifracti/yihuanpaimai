"""One offline slow-consumer check against the existing real Engine queue.

Only transport adapters and the slow business callback are fixtures; no pipe,
window, OCR, capture, history initializer or real process is started.
"""
import importlib.util
from pathlib import Path
import queue
import sys
import threading
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class NativeExistingBackpressureTests(unittest.TestCase):
    def test_slow_business_worker_does_not_block_ack_and_queue_stays_bounded(self):
        path = ROOT / 'architecture/v2/host/engine_v22/nte_engine_v22.py'
        spec = importlib.util.spec_from_file_location('offline_native_slow_engine', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        engine = object.__new__(module.RealEngine)
        engine.session_id, engine.fault = 'isolated-slow', ''
        engine.stop_event = threading.Event()
        engine.frame_queue = queue.Queue(maxsize=2)
        engine._identity_generation_lock = threading.Lock()
        engine._identity_invalidation_generation = 0
        engine.log = lambda *args, **kwargs: None
        engine._drain_deferred_identity = lambda: None
        acknowledgments = []
        engine.send = lambda kind, payload, *args, **kwargs: acknowledgments.append((kind, dict(payload)))
        engine.reader = SimpleNamespace(read_frame=lambda payload, session: {
            'header': {'sequence': payload['sequence']}, 'bufferIndex': 0,
            'readCompletedNs': module.qpc_ns(), 'bgr': np.zeros((3, 4, 3), dtype=np.uint8)})
        entered, release = threading.Event(), threading.Event()
        processed = []
        engine._process_frame = lambda item: (processed.append(item["header"]["sequence"]), entered.set(), release.wait(2))
        worker = threading.Thread(target=engine._worker_loop, daemon=True)
        worker.start()
        try:
            engine.handle_frame_ready({'payload': {'sequence': 1}})
            self.assertTrue(entered.wait(1), 'first business callback must be blocked')
            for sequence in (2, 3, 4):
                engine.handle_frame_ready({'payload': {'sequence': sequence}})
            self.assertEqual(engine.frame_queue.qsize(), 2)
            self.assertFalse(release.is_set())
            self.assertEqual([(p['sequence'], p['status']) for kind, p in acknowledgments],
                             [(1, 'CONSUMED'), (2, 'CONSUMED'), (3, 'CONSUMED'), (4, 'SKIPPED')])
        finally:
            engine.stop_event.set()
            release.set()
            worker.join(1)
        self.assertFalse(worker.is_alive(), 'offline fixture must exit')
        self.assertEqual(processed, [1], 'stop must discard pending frames, not drain them into business')
        self.assertTrue(engine.frame_queue.empty())


if __name__ == '__main__':
    unittest.main()
