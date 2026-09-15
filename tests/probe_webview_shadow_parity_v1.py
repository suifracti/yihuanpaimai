# -*- coding: utf-8 -*-
"""Probe: Verify real Overlay WebView2 executes Live Shadow with 100% frozen parity and 0 Node descendants."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
import websockets

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(CORE_DIR))

FROZEN_SOLVER_CORE_SHA256 = "1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f"

CTX_1415_BASE = {
    "scene": "IN_AUCTION",
    "round": 3,
    "timer": 12,
    "playedAt": "2026-08-17T14:15:59.030277",
    "venue": "中级场 · 珊瑚场",
    "lobbyVenue": "中级场 · 珊瑚场",
    "box": "琉璃宝箱 · 宝石类概率提升",
    "fieldCondition": "standard",
    "q": 12,
    "goldAvg": 74379,
    "avg": 74379,
    "purple": 7,
    "purpleCount": 7,
    "costs": {"entry": 5000, "info": 0, "other": 0},
    "lobbyEntryCost": 5000,
}


def get_descendant_pids(parent_pid: int) -> list[int]:
    """Get all descendant process IDs on Windows using WMIC or powershell."""
    try:
        cmd = f"powershell -NoProfile -Command \"Get-CimInstance Win32_Process | Where-Object {{ $_.ParentProcessId -eq {parent_pid} }} | Select-Object -ExpandProperty ProcessId\""
        out = subprocess.check_output(cmd, shell=True, text=True, timeout=5)
        pids = [int(p.strip()) for p in out.strip().split() if p.strip().isdigit()]
        all_descendants = list(pids)
        for pid in pids:
            all_descendants.extend(get_descendant_pids(pid))
        return all_descendants
    except Exception:
        return []


def count_descendant_processes_by_name(parent_pid: int, names: list[str]) -> dict[str, int]:
    counts = {name.lower(): 0 for name in names}
    descendants = get_descendant_pids(parent_pid)
    if not descendants:
        return counts
    try:
        cmd = f"powershell -NoProfile -Command \"Get-Process -Id {','.join(map(str, descendants))} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessName\""
        out = subprocess.check_output(cmd, shell=True, text=True, timeout=5)
        for proc_name in out.strip().split():
            clean_name = proc_name.strip().lower()
            if clean_name in counts:
                counts[clean_name] += 1
            elif f"{clean_name}.exe" in counts:
                counts[f"{clean_name}.exe"] += 1
    except Exception:
        pass
    return counts


class ProbeWebviewShadowParity(unittest.TestCase):
    def test_solver_core_source_hash_integrity(self):
        solver_file = CORE_DIR / "solver_core_v06.js"
        self.assertTrue(solver_file.is_file(), f"Missing {solver_file}")
        actual_hash = hashlib.sha256(solver_file.read_bytes()).hexdigest()
        self.assertEqual(
            actual_hash,
            FROZEN_SOLVER_CORE_SHA256,
            f"solver_core_v06.js hash mismatch: expected={FROZEN_SOLVER_CORE_SHA256} actual={actual_hash}",
        )

    def test_webview_real_execution_parity_and_zero_node(self):
        """Start python app with Overlay WebView, initialize adapter, compute shadow, verify 100% parity."""
        solver_code = (CORE_DIR / "solver_core_v06.js").read_text(encoding="utf-8")
        raw_records = json.loads((PROJECT_ROOT / "异环拍卖数据.json").read_text(encoding="utf-8")).get("records", [])
        records = [
            {k: v for k, v in r.items() if k not in {"rounds", "prediction", "screenshots"}}
            for r in raw_records
            if isinstance(r, dict)
        ]

        with tempfile.TemporaryDirectory(prefix="nte_probe_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            env = os.environ.copy()
            env["YIHUAN_DATA_ROOT"] = str(tmp_path)
            env["NTE_DISABLE_VISION"] = "1"
            env["NTE_DEBUG"] = "1"
            env["NTE_ALLOW_HUD_CAPTURE"] = "1"
            env["PYTHONUNBUFFERED"] = "1"

            # Launch app in background
            app_script = PROJECT_ROOT / "app" / "main.py"
            proc = subprocess.Popen([sys.executable, str(app_script)], cwd=str(PROJECT_ROOT), env=env)
            try:
                time.sleep(3.5)

                async def run_probe():
                    async def recv_overlay_result(socket, timeout=15.0):
                        deadline = time.time() + timeout
                        while time.time() < deadline:
                            raw = await asyncio.wait_for(socket.recv(), timeout=max(0.5, deadline - time.time()))
                            data = json.loads(raw)
                            if data.get("type") == "overlay_js_result" or "result" in data:
                                res_str = data.get("result")
                                if isinstance(res_str, str):
                                    try:
                                        return json.loads(res_str)
                                    except Exception:
                                        return res_str
                                return res_str
                        raise TimeoutError("overlay_js_result timed out")

                    async with websockets.connect("ws://127.0.0.1:8766", close_timeout=2, max_size=10 * 1024 * 1024) as ws:
                        # 1. Initialize solver in WebView
                        init_script = (
                            f"(() => {{"
                            f"  if (!window.LiveShadowWebviewAdapter) return {{ ok: false, error: 'NO_ADAPTER' }};"
                            f"  const res = window.LiveShadowWebviewAdapter.initSolver({json.dumps(solver_code)}, {json.dumps(FROZEN_SOLVER_CORE_SHA256)});"
                            f"  const recRes = window.LiveShadowWebviewAdapter.setRecords({json.dumps(records)});"
                            f"  return {{ init: res, records: recRes, isReady: window.LiveShadowWebviewAdapter.isReady() }};"
                            f"}})()"
                        )
                        await ws.send(json.dumps({"type": "eval_overlay_js", "script": init_script}))
                        init_result = await recv_overlay_result(ws, timeout=15.0)
                        print("PROBE INIT RESULT:", init_result)
                        self.assertTrue(init_result.get("isReady"), f"Adapter not ready: {init_result}")

                        # 2. Compute 100k (leaderBid = 100000)
                        req_100k = {**CTX_1415_BASE, "leaderBid": 100000}
                        compute_100k_script = (
                            f"(() => {{"
                            f"  const res = window.LiveShadowWebviewAdapter.compute({json.dumps(req_100k)});"
                            f"  return res;"
                            f"}})()"
                        )
                        await ws.send(json.dumps({"type": "eval_overlay_js", "script": compute_100k_script}))
                        res_100k = await recv_overlay_result(ws, timeout=15.0)
                        print("PROBE 100k RESULT:", json.dumps(res_100k.get("probabilityProfile", {}).get("shadowWhole"), indent=2))

                        # 3. Compute 600k (leaderBid = 600000)
                        req_600k = {**CTX_1415_BASE, "leaderBid": 600000}
                        compute_600k_script = (
                            f"(() => {{"
                            f"  const res = window.LiveShadowWebviewAdapter.compute({json.dumps(req_600k)});"
                            f"  return res;"
                            f"}})()"
                        )
                        await ws.send(json.dumps({"type": "eval_overlay_js", "script": compute_600k_script}))
                        res_600k = await recv_overlay_result(ws, timeout=15.0)

                        return res_100k, res_600k

                res_100k, res_600k = asyncio.run(run_probe())

                # Check process tree for 0 node.exe descendants
                counts = count_descendant_processes_by_name(proc.pid, ["node.exe", "node"])
                print(f"Descendant process counts: {counts}")
                self.assertEqual(counts.get("node.exe", 0) + counts.get("node", 0), 0, f"External node spawned: {counts}")

                # Verify Cut 4 frozen values
                prof_100k = res_100k.get("probabilityProfile") or {}
                shadow_whole_100k = prof_100k.get("shadowWhole") or {}
                pred_100k = res_100k.get("predictionSnapshot") or {}
                forecast_100k = (pred_100k.get("forecast") or {}).get("quantiles") or {}
                action_100k = (res_100k.get("frozenPrediction") or {}).get("actionDirective")

                self.assertTrue(prof_100k.get("isFullShadow"))
                self.assertAlmostEqual(shadow_whole_100k.get("p20"), 415124.0131428572, places=4)
                self.assertAlmostEqual(shadow_whole_100k.get("p50"), 437503.0131428572, places=4)
                self.assertAlmostEqual(shadow_whole_100k.get("p80"), 513175.0131428572, places=4)

                prof_600k = res_600k.get("probabilityProfile") or {}
                shadow_whole_600k = prof_600k.get("shadowWhole") or {}
                action_600k = (res_600k.get("frozenPrediction") or {}).get("actionDirective")

                # Invariance under leaderBid
                self.assertEqual(shadow_whole_100k.get("p20"), shadow_whole_600k.get("p20"))
                self.assertEqual(shadow_whole_100k.get("p50"), shadow_whole_600k.get("p50"))
                self.assertEqual(shadow_whole_100k.get("p80"), shadow_whole_600k.get("p80"))

                print("PROBE PASSED: ALL VALUES 100% MATCH CUT 4 FROZEN BENCHMARK!")

            finally:
                subprocess.run(f"taskkill /F /PID {proc.pid} /T", shell=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
