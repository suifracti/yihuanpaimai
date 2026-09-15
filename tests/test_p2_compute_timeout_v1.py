# -*- coding: utf-8 -*-
"""Hung compute must time out, recover, and never block mode/facts."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "core")]

os.environ.setdefault("YIHUAN_DATA_ROOT", str(ROOT / "build" / "diagnosis_20260909" / "p2-timeout-data"))

import live_shadow
from live_shadow import (
    attach_live_shadow,
    compute_live_probability_profile,
    reset_live_shadow_state,
    wait_for_shadow,
)
from recognition_mode import set_recognition_mode, get_recognition_mode


HANG_JS = str(ROOT / "tests" / "fixtures" / "hang_shadow_runtime.js")


class TestP2ComputeTimeout(unittest.TestCase):
    def setUp(self):
        reset_live_shadow_state()
        self.tmp = tempfile.TemporaryDirectory(prefix="p2_timeout_")
        self.db = os.path.join(self.tmp.name, "hist.json")
        Path(self.db).write_text('{"schemaVersion":6,"records":[]}', encoding="utf-8")
        live_shadow.load_history_snapshot(self.db)
        self._old_timeout = os.environ.get("YIHUAN_COMPUTE_TIMEOUT_S")
        self._old_runtime = os.environ.get("YIHUAN_SHADOW_RUNTIME_JS")
        os.environ["YIHUAN_COMPUTE_TIMEOUT_S"] = "1.0"

    def tearDown(self):
        reset_live_shadow_state()
        if self._old_timeout is None:
            os.environ.pop("YIHUAN_COMPUTE_TIMEOUT_S", None)
        else:
            os.environ["YIHUAN_COMPUTE_TIMEOUT_S"] = self._old_timeout
        if self._old_runtime is None:
            os.environ.pop("YIHUAN_SHADOW_RUNTIME_JS", None)
        else:
            os.environ["YIHUAN_SHADOW_RUNTIME_JS"] = self._old_runtime
        self.tmp.cleanup()

    def test_hanging_runtime_times_out_and_does_not_use_webview(self):
        host = Mock()
        host.is_ready.return_value = True
        host.compute.side_effect = AssertionError("webview fallback is forbidden")
        live_shadow.register_webview_host(host)
        os.environ["YIHUAN_SHADOW_RUNTIME_JS"] = HANG_JS
        t0 = time.perf_counter()
        profile, meta = compute_live_probability_profile(
            {"scene": "IN_AUCTION", "q": 12, "goldAvg": 74379, "matchId": "hang"},
            db_path=self.db,
            persist_runtime=True,
        )
        elapsed = time.perf_counter() - t0
        live_shadow.unregister_webview_host()
        self.assertIsNone(profile)
        self.assertEqual((meta.get("supportCapture") or {}).get("reason"), "COMPUTE_TIMEOUT")
        self.assertLess(elapsed, 4.0)
        host.compute.assert_not_called()

    def test_mode_switch_during_hung_compute(self):
        import threading
        os.environ["YIHUAN_SHADOW_RUNTIME_JS"] = HANG_JS

        def hung():
            compute_live_probability_profile(
                {"scene": "IN_AUCTION", "q": 12, "goldAvg": 74379, "matchId": "busy"},
                db_path=self.db,
                persist_runtime=True,
            )

        worker = threading.Thread(target=hung, name="hung-compute", daemon=True)
        worker.start()
        time.sleep(0.05)
        t0 = time.perf_counter()
        set_recognition_mode("auto")
        mode = get_recognition_mode()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(mode, "auto")
        self.assertLess(elapsed_ms, 500)
        worker.join(timeout=5)

    def test_sustained_real_compute_does_not_block_mode(self):
        os.environ.pop("YIHUAN_SHADOW_RUNTIME_JS", None)
        os.environ["YIHUAN_COMPUTE_TIMEOUT_S"] = "8"
        switches = []
        t0 = time.perf_counter()
        for i in range(8):
            attach_live_shadow(
                {"scene": "IN_AUCTION", "q": 12, "goldAvg": 74379, "box": "琉璃宝箱", "matchId": f"load-{i}"},
                db_path=self.db,
            )
            t1 = time.perf_counter()
            set_recognition_mode("auto" if i % 2 == 0 else "manual")
            switches.append((time.perf_counter() - t1) * 1000)
        self.assertLess(max(switches), 500)
        self.assertLess(time.perf_counter() - t0, 8)

    def test_stale_generation_is_discarded(self):
        slow = {"calls": 0}

        def fake_compute(ctx, db_path=None, persist_runtime=True):
            slow["calls"] += 1
            gen = ctx.get("q")
            time.sleep(0.4)
            return {"p50": gen}, {"cache": "miss", "predictionSnapshot": {"matchId": ctx.get("matchId"), "q": gen}}

        with patch.object(live_shadow, "compute_live_probability_profile", side_effect=fake_compute):
            attach_live_shadow({"scene": "IN_AUCTION", "q": 1, "goldAvg": 1000, "matchId": "a"}, db_path=self.db)
            attach_live_shadow({"scene": "IN_AUCTION", "q": 9, "goldAvg": 2000, "matchId": "a"}, db_path=self.db)
            got = wait_for_shadow(timeout=3.0)
        self.assertIsNotNone(got)
        self.assertEqual(got.get("p50"), 9)


if __name__ == "__main__":
    unittest.main()
