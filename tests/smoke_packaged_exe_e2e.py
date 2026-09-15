"""End-to-End Packaged Executable Real WebView Smoke Test (Cut 5)."""

from __future__ import annotations

import asyncio
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
DIST_EXE = PROJECT_ROOT / "dist" / "cut5_truthful_main" / "异环拍卖助手" / "异环拍卖助手.exe"
DIST_DIR = DIST_EXE.parent
WS_URL = "ws://127.0.0.1:8766"


def wait_ws_connectable(timeout: float = 20.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            import socket
            s = socket.socket()
            s.settimeout(0.3)
            s.connect(("127.0.0.1", 8766))
            s.close()
            return True
        except Exception:
            time.sleep(0.3)
    return False


class PackagedExeE2ESmoke(unittest.TestCase):
    def test_packaged_executable_real_flow(self):
        self.assertTrue(DIST_EXE.is_file(), f"Packaged executable not found: {DIST_EXE}")

        with tempfile.TemporaryDirectory() as temp_root:
            isolated_root = Path(temp_root)
            log_path = isolated_root / "packaged_smoke.log"

            # Pre-flight: Record files in dist directory to prove package dir is NOT written to
            dist_files_before = set(DIST_DIR.rglob("*"))

            env = os.environ.copy()
            env["YIHUAN_DATA_ROOT"] = str(isolated_root)
            env["NTE_DISABLE_VISION"] = "1"
            env["NTE_DEBUG"] = "1"
            env["NTE_LOG_FILE"] = str(log_path)
            env["PYTHONUNBUFFERED"] = "1"

            # -------------------------------------------------------------
            # RUN 1: Fresh Startup -> Empty State -> Manual Input -> Finalize -> Next Match -> Exit
            # -------------------------------------------------------------
            proc1 = subprocess.Popen(
                [str(DIST_EXE), "--debug"],
                cwd=str(DIST_DIR),
                env=env,
            )

            async def _run_session_1():
                async with websockets.connect(WS_URL, close_timeout=2) as ws:
                    # 1. Inspect initial bootstrap payload
                    await ws.send(json.dumps({"type": "manual_bootstrap"}))
                    raw_0 = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    msg_0 = json.loads(raw_0)
                    self.assertEqual(msg_0.get("lifecycleStatus"), "DRAFT")
                    self.assertIn("matchId", msg_0)

                    # 2. Input Manual Facts for Match A
                    facts_msg = {
                        "type": "manual_facts",
                        "facts": {
                            "venueId": "venue-shanhu",
                            "boxId": "box-shanhu-wood",
                            "fieldCondition": "standard",
                            "fieldConditionName": "标准规则",
                            "q": 15,
                            "goldAvg": 33538,
                            "purpleCount": 5,
                            "knownGold": "万有星仪",
                            "leaderBid": 200000,
                        }
                    }
                    await ws.send(json.dumps(facts_msg, ensure_ascii=False))
                    while True:
                        raw_facts = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        msg_facts = json.loads(raw_facts)
                        if msg_facts.get("type") == "manual_alpha_state" and msg_facts.get("venue"):
                            break
                    self.assertEqual(msg_facts.get("venue"), "珊瑚场")
                    current_match_id = msg_facts["matchId"]

                    # 3. Finalize match A
                    finalize_msg = {
                        "type": "manual_finalize",
                        "expectedMatchId": current_match_id,
                        "settlement": {
                            "actualTotal": 450000,
                            "clearingPrice": 380000,
                            "realizedProfit": 65000,
                            "acquired": True,
                            "won": True,
                            "winner": "本人拍下",
                            "resultReason": "won",
                            "settlementItems": [{"name": "万有星仪", "price": 51077, "rarity": "gold"}],
                        }
                    }
                    await ws.send(json.dumps(finalize_msg, ensure_ascii=False))
                    while True:
                        raw_fin = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        msg_fin = json.loads(raw_fin)
                        term = msg_fin.get("terminalResult")
                        if term and term.get("status") == "FINALIZED":
                            break
                    saved_match_id = term.get("matchId")
                    self.assertEqual(saved_match_id, current_match_id)
                    # Next match was automatically initialized with reset=True
                    self.assertEqual(msg_fin.get("lifecycleStatus"), "DRAFT")
                    self.assertNotEqual(msg_fin.get("matchId"), saved_match_id)

                    return saved_match_id

            try:
                self.assertTrue(wait_ws_connectable(), "Packaged HUD WebSocket did not become ready")
                saved_id = asyncio.run(_run_session_1())
            finally:
                proc1.terminate()
                try:
                    proc1.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc1.kill()
                    proc1.wait()
                if log_path.is_file():
                    print("--- PACKAGED LOG START ---")
                    print(log_path.read_text(encoding="utf-8", errors="ignore"))
                    print("--- PACKAGED LOG END ---")

            time.sleep(1.0)

            # -------------------------------------------------------------
            # Verify Main View State projection on the persisted history
            # -------------------------------------------------------------
            sys.path.insert(0, str(PROJECT_ROOT / "core"))
            sys.path.insert(0, str(PROJECT_ROOT / "app"))
            from main_view_state import MainViewStateProvider
            from runtime_data import resolve_runtime_history_path
            per_user_history = resolve_runtime_history_path({"YIHUAN_DATA_ROOT": str(isolated_root)})
            self.assertTrue(per_user_history.is_file(), f"History file missing at {per_user_history}")

            provider = MainViewStateProvider(per_user_history)
            snap = provider.snapshot()
            self.assertEqual(snap.history_availability, "AVAILABLE")
            self.assertEqual(snap.total_record_count, 1)
            self.assertEqual(len(snap.history_records), 1)

            rec_payload = snap.history_records[0].to_payload()
            self.assertEqual(rec_payload["id"], saved_id)
            self.assertEqual(rec_payload["lifecycle"], "FINALIZED")
            self.assertEqual(rec_payload["environment"]["venueName"], "珊瑚场")
            self.assertIsNone(rec_payload["environment"]["venueTier"])
            self.assertTrue(rec_payload["settlement"]["isSettled"])
            self.assertEqual(rec_payload["settlement"]["actualTotal"], 450000)
            self.assertEqual(rec_payload["settlement"]["clearingPrice"], 380000)
            self.assertEqual(rec_payload["settlement"]["realizedProfit"], 65000)
            self.assertTrue(rec_payload["settlement"]["acquired"])
            self.assertEqual(rec_payload["settlement"]["winner"], "本人拍下")

            # -------------------------------------------------------------
            # RUN 2: Restart Session -> Verify Persistence & No Duplication
            # -------------------------------------------------------------
            proc2 = subprocess.Popen(
                [str(DIST_EXE), "--debug"],
                cwd=str(DIST_DIR),
                env=env,
            )

            async def _run_session_2():
                async with websockets.connect(WS_URL, close_timeout=2) as ws:
                    await ws.send(json.dumps({"type": "manual_bootstrap"}))
                    raw_r = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    msg_r = json.loads(raw_r)
                    self.assertEqual(msg_r.get("lifecycleStatus"), "DRAFT")
                    self.assertNotEqual(msg_r.get("matchId"), saved_id)

            try:
                self.assertTrue(wait_ws_connectable(), "Packaged HUD WebSocket did not become ready on restart")
                asyncio.run(_run_session_2())
            finally:
                proc2.terminate()
                try:
                    proc2.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc2.kill()
                    proc2.wait()

            # Verify history record still exists exactly once after restart
            history_data = json.loads(per_user_history.read_text(encoding="utf-8"))
            self.assertEqual(len(history_data.get("records", [])), 1)
            self.assertEqual(history_data["records"][0]["id"], saved_id)

            # -------------------------------------------------------------
            # Verify: Package directory has NOT been polluted by user history
            # -------------------------------------------------------------
            dist_files_after = set(DIST_DIR.rglob("*"))
            new_dist_files = dist_files_after - dist_files_before
            self.assertEqual(
                new_dist_files,
                set(),
                f"Packaged directory was polluted with new files: {new_dist_files}",
            )


if __name__ == "__main__":
    unittest.main()
