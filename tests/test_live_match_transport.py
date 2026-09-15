"""Worker process -> real WebSocket handler -> Main current match."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "app", ROOT / "core"):
    sys.path.insert(0, str(path))

import main
from current_match import CurrentMatch
from live_match_transport import LiveMatchPublisher, LiveMatchReceiver, LiveMatchSession


class LiveMatchTransportTests(unittest.TestCase):
    def test_reconnect_handshake_restores_gui_corrections_and_retires_old_socket(self):
        async def run():
            current = CurrentMatch()
            current.apply_facts({"q": 9})
            with patch.object(main, "CURRENT_MATCH", current), \
                 patch.object(main, "_LIVE_CONTROL_REVISION", 3), \
                 patch.object(main, "_LIVE_CONTROL_WAITING_EXIT", True), \
                 patch.object(main, "_LIVE_MANUAL_OVERRIDES", {"q": 9}), \
                 patch.object(main, "LATEST_PAYLOAD", {}):
                async with main.websockets.serve(main.ws_handler, "127.0.0.1", 0) as server:
                    url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                    async with main.websockets.connect(url) as old:
                        await old.send(json.dumps({"type": "vision_worker_hello"}))
                        first = json.loads(await asyncio.wait_for(old.recv(), 3))
                        self.assertEqual(first["revision"], 3)
                        async with main.websockets.connect(url) as replacement:
                            await replacement.send(json.dumps({"type": "vision_worker_hello"}))
                            resumed = json.loads(await asyncio.wait_for(replacement.recv(), 3))
                            self.assertEqual(resumed["snapshot"]["id"], current.id)
                            self.assertEqual(resumed["facts"], {"q": 9})
                            self.assertTrue(resumed["reset"])
                            with self.assertRaises(main.websockets.exceptions.ConnectionClosed):
                                await asyncio.wait_for(old.recv(), 3)
        asyncio.run(run())

    def test_worker_frame_does_not_start_native_capture(self):
        import numpy as np
        with patch.object(main, "maybe_trigger_auto_warehouse_capture") as capture:
            main.process_live_game_frame(
                np.zeros((2, 2, 3), dtype=np.uint8), game_hwnd=1,
                ctx={"scene": "UNKNOWN"}, run_capture_orchestration=False)
            capture.assert_not_called()

    def test_settlement_scene_alone_does_not_prove_capture_stability(self):
        before = copy.deepcopy(main.LATEST_PAYLOAD)
        vision_before = copy.deepcopy(main.LATEST_VISION_PAYLOAD)
        try:
            main.LATEST_VISION_PAYLOAD.clear()
            main.LATEST_PAYLOAD.clear()
            main.LATEST_PAYLOAD.update({"scene": "SETTLEMENT", "isSettlement": True,
                                        "hadSettlement": True, "gameHwnd": 1})
            self.assertFalse(main.get_production_warehouse_bindings()["stable"])
            main.LATEST_PAYLOAD["settlementStable"] = True
            self.assertTrue(main.get_production_warehouse_bindings()["stable"])
        finally:
            main.LATEST_VISION_PAYLOAD.clear()
            main.LATEST_VISION_PAYLOAD.update(vision_before)
            main.LATEST_PAYLOAD.clear()
            main.LATEST_PAYLOAD.update(before)

    def test_session_exit_changes_id_but_temporary_window_loss_does_not(self):
        current, session = CurrentMatch(), LiveMatchSession()
        original = current.id
        current.apply_facts({"q": 12})
        for scene in ("IN_AUCTION", "UNKNOWN", "IN_AUCTION", "SETTLEMENT"):
            session.observe({"scene": scene}, current)
            self.assertEqual(current.id, original)
        ctx = {"scene": "AUCTION_LOBBY"}
        session.observe(ctx, current)
        self.assertNotEqual(current.id, original)
        self.assertIsNone(current.facts["q"])
        self.assertEqual(ctx["matchId"], current.id)
        second = current.id
        for scene in ("AUCTION_LOBBY", "AUCTION_LOADING", "IN_AUCTION"):
            session.observe({"scene": scene}, current)
            self.assertEqual(current.id, second)
    def test_ordering_retired_ids_and_local_capture_preservation(self):
        publisher, receiver = LiveMatchPublisher(), LiveMatchReceiver()
        worker, mirror = CurrentMatch(), CurrentMatch()
        worker.apply_facts({"q": 12, "isAcquired": False})
        first = publisher.attach({}, worker)["visionState"]
        self.assertTrue(receiver.apply(first, mirror))
        self.assertEqual(mirror.id, worker.id)
        self.assertEqual(mirror.facts["q"], 12)
        self.assertIs(mirror.facts["isAcquired"], False)
        mirror.facts["warehouseOccupancy"] = {"local": "capture"}
        self.assertTrue(receiver.apply(publisher.attach({}, worker)["visionState"], mirror))
        self.assertEqual(mirror.facts["warehouseOccupancy"], {"local": "capture"})
        self.assertFalse(receiver.apply(first, mirror))
        worker.begin_next_match()
        self.assertTrue(receiver.apply(publisher.attach({}, worker)["visionState"], mirror))
        self.assertIsNone(mirror.facts["q"])
        self.assertIsNone(mirror.facts["warehouseOccupancy"])
        first["sequence"] = 100
        self.assertFalse(receiver.apply(first, mirror))

    def test_separate_process_delivers_two_matches_through_real_ws_handler(self):
        async def run():
            current = CurrentMatch()
            saved_payload = copy.deepcopy(main.LATEST_PAYLOAD)
            main.LATEST_PAYLOAD.clear()
            child = None
            try:
                with patch.object(main, "CURRENT_MATCH", current), patch.object(main, "_LIVE_CONTROL_REVISION", 0):
                    async with main.websockets.serve(main.ws_handler, "127.0.0.1", 0) as server:
                        port = server.sockets[0].getsockname()[1]
                        url = f"ws://127.0.0.1:{port}"
                        async with main.websockets.connect(url) as observer:
                            script = '''
import asyncio, json, sys
import websockets
from current_match import CurrentMatch
from live_match_transport import LiveMatchPublisher
async def run():
    publisher = LiveMatchPublisher()
    current = CurrentMatch()
    async with websockets.connect(sys.argv[1]) as ws:
        await ws.send(json.dumps({"type": "vision_worker_hello"}))
        while json.loads(await ws.recv()).get("action") != "worker_resume":
            pass
        current.id = "worker_first"
        current.apply_facts({"q": 12, "goldCount": 4, "isAcquired": False})
        old = publisher.attach({"scene": "IN_AUCTION"}, current)
        await ws.send(json.dumps(old))
        current.begin_next_match()
        current.id = "worker_second"
        current.apply_facts({"q": 9})
        await ws.send(json.dumps(publisher.attach({"scene": "IN_AUCTION"}, current)))
        old["visionState"]["sequence"] = 100
        await ws.send(json.dumps(old))
        await asyncio.sleep(0.1)
asyncio.run(run())
'''
                            env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
                            child = await asyncio.create_subprocess_exec(
                                sys.executable, "-c", script, url, env=env,
                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                            first = json.loads(await asyncio.wait_for(observer.recv(), 15))
                            second = json.loads(await asyncio.wait_for(observer.recv(), 15))
                            self.assertEqual(first["visionState"]["snapshot"]["id"], "worker_first")
                            self.assertEqual(second["visionState"]["snapshot"]["id"], "worker_second")
                            stdout, stderr = await asyncio.wait_for(child.communicate(), 15)
                            self.assertEqual(child.returncode, 0, stderr.decode(errors="replace"))
                            self.assertEqual(current.id, "worker_second")
                            self.assertEqual(current.facts["q"], 9)
                            self.assertIsNone(current.facts["goldCount"])
                            self.assertIsNone(current.facts["isAcquired"])
                            with self.assertRaises(asyncio.TimeoutError):
                                await asyncio.wait_for(observer.recv(), 0.05)
            finally:
                if child is not None and child.returncode is None:
                    child.kill()
                    await child.communicate()
                main.LATEST_PAYLOAD.clear()
                main.LATEST_PAYLOAD.update(saved_payload)
        asyncio.run(run())
