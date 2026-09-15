# -*- coding: utf-8 -*-
"""P2: production compute is a persistent Node process, not Overlay WebView."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "core")]

os.environ.setdefault("YIHUAN_DATA_ROOT", str(ROOT / "build" / "diagnosis_20260909" / "p2-isolation-data"))

import live_shadow
from live_shadow import _runtime_compute, _node_executable, reset_live_shadow_state
from keyboard_auction_pipeline import KeyboardAuctionPipeline


class TestP2RuntimeIsolation(unittest.TestCase):
    def setUp(self):
        reset_live_shadow_state()
        self.tmp = tempfile.TemporaryDirectory(prefix="p2_shadow_")
        self.db = os.path.join(self.tmp.name, "hist.json")
        Path(self.db).write_text('{"schemaVersion":6,"records":[]}', encoding="utf-8")
        live_shadow.load_history_snapshot(self.db)

    def tearDown(self):
        reset_live_shadow_state()
        self.tmp.cleanup()

    def test_source_node_is_available(self):
        self.assertIsNotNone(_node_executable())

    def test_runtime_prefers_node_even_if_webview_is_registered(self):
        host = Mock()
        host.is_ready.return_value = True
        host.compute.side_effect = AssertionError("overlay must not own production compute")
        live_shadow.register_webview_host(host)
        node_result = {"ok": True, "probabilityProfile": {"coverageRatio": 1}, "computeHost": "node"}
        try:
            with patch.object(live_shadow, "_compute_via_node", return_value=node_result) as node_fn:
                result = _runtime_compute({"scene": "IN_AUCTION", "q": 9, "goldAvg": 33538, "matchId": "p2"}, self.db)
            node_fn.assert_called_once()
            self.assertEqual(result.get("computeHost"), "node")
            host.compute.assert_not_called()
        finally:
            live_shadow.unregister_webview_host()

    def test_keyboard_pipeline_does_not_bypass_card_confirmation(self):
        pipe = KeyboardAuctionPipeline()
        self.assertFalse(pipe.fast_live_intel)

    def test_overlay_projects_and_does_not_local_solve_first(self):
        html = (ROOT / "core" / "overlay_alpha.html").read_text(encoding="utf-8")
        self.assertIn("paintLiveSeatsAndIntel", html)
        self.assertIn("live_shadow_compute.js", html)
        paint_idx = html.find("function paintResult(d)")
        solve_idx = html.find("engine.solveAuctionPipeline && solverIn", paint_idx)
        trusted_idx = html.find("paintTrustedLiveResult(d)", paint_idx)
        self.assertGreater(trusted_idx, paint_idx)
        self.assertGreater(solve_idx, trusted_idx)

    def test_shared_compute_module_exists(self):
        js = (ROOT / "core" / "live_shadow_compute.js").read_text(encoding="utf-8")
        self.assertIn("function compute(", js)
        runtime = (ROOT / "core" / "live_shadow_runtime.js").read_text(encoding="utf-8")
        self.assertIn("live_shadow_compute.js", runtime)
        adapter = (ROOT / "core" / "live_shadow_webview_adapter.js").read_text(encoding="utf-8")
        self.assertIn("LiveShadowCompute", adapter)


if __name__ == "__main__":
    unittest.main()
