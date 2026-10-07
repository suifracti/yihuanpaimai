"""Offline startup orchestration; no assistant, Host, window or input launched."""
import asyncio
import importlib.util
import json
from pathlib import Path
import time
import unittest

spec = importlib.util.spec_from_file_location("native_startup", Path(__file__).resolve().parents[1] / "tools/start_native_observation.py")
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)


class NativeStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_request_immediately_then_first_failure_without_retry(self):
        class Bus:
            sent = []
            messages = iter([{"visionHealth": {"stage": "native-stopped", "reason": "explicit-start-required"}},
                             {"visionHealth": {"stage": "native-starting"}},
                             {"visionHealth": {"stage": "native-ready"}},
                             {"visionHealth": {"stage": "native-error", "reason": "source-clock-future-at-selection"}}])
            async def send(self, message):
                self.sent.append((time.perf_counter_ns(), json.loads(message)))
            async def recv(self):
                return json.dumps(next(self.messages))
        bus, events = Bus(), []
        began = time.perf_counter_ns()
        result = await startup.request_once(bus, lambda stage, **data: events.append({"stage": stage, **data}))
        self.assertFalse(result)
        self.assertEqual(events[-2]["stage"], "engine-ready-awaiting-first-frame")
        self.assertEqual(len(bus.sent), 1)
        self.assertEqual(bus.sent[0][1], {"type": "start_live_vision", "resumeSameMatch": False})
        self.assertLess((bus.sent[0][0] - began) / 1e6, 250)
        self.assertEqual(events[-1]["health"]["reason"], "source-clock-future-at-selection")


if __name__ == "__main__":
    unittest.main()
