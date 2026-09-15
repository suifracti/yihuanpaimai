# -*- coding: utf-8 -*-
"""P1 longitudinal UI and transport acceptance with isolated runtime data."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "app"), str(ROOT / "core")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

WOOD_BOX = "实木宝箱 · 中级藏品概率提升"
GLASS_BOX = "琉璃宝箱 · 宝石类概率提升"


class P1UiTransportLongitudinalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p1-ui-transport-")
        self.old_root = os.environ.get("YIHUAN_DATA_ROOT")
        os.environ["YIHUAN_DATA_ROOT"] = self.temp.name
        import main as app_main
        from main_window import MainWindowBridge, OverlayVisibilityController
        from recognition_mode import set_recognition_mode

        self.app_main = app_main
        self.OverlayVisibilityController = OverlayVisibilityController
        self.MainWindowBridge = MainWindowBridge
        app_main.cancel_draft_save()
        self.old_overrides = dict(app_main._LIVE_MANUAL_OVERRIDES)
        self.old_vision_active = app_main._LIVE_VISION_ACTIVE
        self.old_vision_match = app_main._LIVE_VISION_MATCH_ID
        self.old_payload = dict(app_main.LATEST_PAYLOAD)
        app_main._LIVE_MANUAL_OVERRIDES.clear()
        app_main._LIVE_VISION_ACTIVE = False
        app_main._LIVE_VISION_MATCH_ID = None
        app_main.LATEST_PAYLOAD.clear()
        app_main.CURRENT_MATCH.begin_next_match()
        set_recognition_mode("auto")

    def tearDown(self):
        self.app_main.cancel_draft_save()
        self.app_main.CURRENT_MATCH.begin_next_match()
        self.app_main._LIVE_MANUAL_OVERRIDES.clear()
        self.app_main._LIVE_MANUAL_OVERRIDES.update(self.old_overrides)
        self.app_main._LIVE_VISION_ACTIVE = self.old_vision_active
        self.app_main._LIVE_VISION_MATCH_ID = self.old_vision_match
        self.app_main.LATEST_PAYLOAD.clear()
        self.app_main.LATEST_PAYLOAD.update(self.old_payload)
        if self.old_root is None:
            os.environ.pop("YIHUAN_DATA_ROOT", None)
        else:
            os.environ["YIHUAN_DATA_ROOT"] = self.old_root
        self.temp.cleanup()

    def _seed_vision(self, **facts):
        defaults = {"box": WOOD_BOX, "q": 9, "goldAvg": 33538, "venueId": "venue-shanhu"}
        defaults.update(facts)
        self.app_main.CURRENT_MATCH.apply_facts(defaults, source="vision")
        return self.app_main.CURRENT_MATCH

    def _bridge(self):
        overlay = MagicMock()
        overlay.Visible = False
        controller = self.OverlayVisibilityController(overlay)
        return self.MainWindowBridge(
            controller,
            current_match_provider=self.app_main.get_current_match_presentation_summary,
            manual_facts_provider=lambda facts: self.app_main.publish_manual_payload(
                self.app_main.apply_manual_facts(facts)
            ),
        )

    def test_main_q_only_keeps_box_and_overlay_payload_syncs(self):
        match = self._seed_vision()
        bridge = self._bridge()
        response = bridge.dispatch({"action": "manual_facts", "facts": {"q": 12}, "requestId": "main-1"})
        self.assertTrue(response["manualFactsResult"]["ok"])
        self.assertEqual(match.facts["box"], WOOD_BOX)
        self.assertEqual(match.facts["q"], 12)
        self.assertEqual(match.facts["goldAvg"], 33538)
        overlay = self.app_main.LATEST_PAYLOAD
        self.assertEqual(overlay.get("box"), WOOD_BOX)
        self.assertEqual(overlay.get("q"), 12)
        presentation = response["currentMatch"]
        self.assertEqual(presentation["facts"]["box"], WOOD_BOX)
        self.assertEqual(presentation["facts"]["q"], 12)
        self.assertEqual(presentation["environment"]["box"], WOOD_BOX)

    def test_main_clear_and_restore_auto_use_bridge_envelope(self):
        match = self._seed_vision()
        bridge = self._bridge()
        bridge.dispatch({
            "action": "manual_facts",
            "facts": {"box": None, "boxId": None},
            "clearedFields": ["box", "boxId"],
        })
        self.assertIsNone(match.facts["box"])
        self.assertTrue(match.field_states["box"].protected)
        receipt = self.app_main.LATEST_PAYLOAD
        self.assertIn("box", receipt.get("manualControl", {}).get("clearedFields") or receipt.get("fieldStates") or {})
        self.assertTrue((receipt.get("fieldStates") or {}).get("box", {}).get("protected"))
        bridge.dispatch({
            "action": "manual_facts",
            "facts": {},
            "restoreAutoFields": ["box", "boxId"],
        })
        self.assertFalse(match.field_states["box"].protected)
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        self.assertEqual(match.facts["box"], WOOD_BOX)

    def test_overlay_confirm_protects_and_main_q_edit_does_not_unprotect(self):
        match = self._seed_vision()
        payload = self.app_main.apply_manual_facts({
            "facts": {"box": WOOD_BOX},
            "intent": "confirm",
        })
        confirmed = match.facts["box"]
        self.assertTrue(confirmed)
        self.assertTrue(match.field_states["box"].protected)
        self.assertTrue((payload.get("fieldStates") or {}).get("box", {}).get("protected"))
        self._bridge().dispatch({"action": "manual_facts", "facts": {"q": 21}})
        self.assertEqual(match.facts["q"], 21)
        self.assertTrue(match.field_states["box"].protected)
        match.apply_facts({"box": GLASS_BOX}, source="vision")
        self.assertEqual(match.facts["box"], confirmed)

    def test_both_ends_clear_and_restore_receipts(self):
        match = self._seed_vision()
        overlay = self.app_main.apply_manual_facts({
            "facts": {"box": None},
            "clearedFields": ["box", "boxId"],
        })
        self.assertIsNone(overlay.get("box") if overlay.get("box") not in ("未选择",) else None)
        self.assertIsNone(match.facts["box"])
        main_receipt = self._bridge().dispatch({
            "action": "manual_facts",
            "facts": {},
            "restoreAutoFields": ["box", "boxId"],
        })
        self.assertFalse(match.field_states["box"].protected)
        self.assertFalse((main_receipt["currentMatch"].get("fieldStates") or {}).get("box", {}).get("protected", True))

    def test_round_change_keeps_fixed_box(self):
        match = self._seed_vision()
        self.app_main.sync_vision_to_current_match({
            "scene": "IN_AUCTION",
            "round": 2,
            "q": 9,
            "box": "未知箱型",
            "goldAvg": 33538,
            "venueId": "venue-shanhu",
            "lobbyVenueKey": "shanhu",
        })
        self.assertEqual(match.facts["box"], WOOD_BOX)
        self.assertEqual(match.facts["q"], 9)

    def test_stale_command_and_old_snapshot_do_not_clobber(self):
        from current_match import CurrentMatch
        from live_match_control import LiveMatchControl
        from live_match_transport import LiveMatchPublisher, LiveMatchReceiver

        match = self._seed_vision()
        publisher = LiveMatchPublisher()
        control = LiveMatchControl()
        pipe = type("P", (), {"reset_session_state": lambda self: None})()
        session = type("S", (), {"active": False, "observe": lambda *a, **k: None})()
        good = {
            "revision": 2,
            "expectedMatchId": match.id,
            "snapshot": match.snapshot(),
            "facts": {"q": 12},
        }
        stale = {
            "revision": 1,
            "expectedMatchId": match.id,
            "snapshot": match.snapshot(),
            "facts": {"box": None},
            "clearedFields": ["box"],
        }
        self.assertTrue(control.apply(good, match, publisher, pipe, session))
        self.assertFalse(control.apply(stale, match, publisher, pipe, session))
        self.assertEqual(match.facts["box"], WOOD_BOX)
        worker, mirror = CurrentMatch(), CurrentMatch()
        mirror.id = worker.id
        mirror.apply_facts({"box": WOOD_BOX, "q": 12}, source="vision")
        worker.apply_facts({"q": 12}, source="vision")
        replay = LiveMatchPublisher()
        receiver = LiveMatchReceiver()
        first = replay.attach({}, worker)["visionState"]
        self.assertTrue(receiver.apply(first, mirror))
        self.assertEqual(mirror.facts["box"], WOOD_BOX)
        self.assertFalse(receiver.apply(first, mirror))
        self.assertEqual(mirror.facts["box"], WOOD_BOX)

    def test_reconnect_resume_keeps_protected_box_on_new_match_id(self):
        match = self._seed_vision()
        match.apply_facts({"box": WOOD_BOX}, source="manual", intent="confirm")
        self.app_main._LIVE_CONTROL_REVISION = 4
        self.app_main._LIVE_MANUAL_OVERRIDES.update({"q": 9})

        async def run():
            async with self.app_main.websockets.serve(self.app_main.ws_handler, "127.0.0.1", 0) as server:
                url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                async with self.app_main.websockets.connect(url) as worker:
                    await worker.send(json.dumps({"type": "vision_worker_hello"}))
                    resumed = json.loads(await asyncio.wait_for(worker.recv(), 3))
                    self.assertEqual(resumed["action"], "worker_resume")
                    self.assertEqual(resumed["snapshot"]["id"], match.id)
                    self.assertEqual(resumed["snapshot"]["box"], WOOD_BOX)
                    self.assertTrue((resumed["snapshot"].get("fieldStates") or {}).get("box", {}).get("protected"))
                    self.assertEqual(resumed["facts"].get("q"), 9)

        asyncio.run(run())

    def test_busy_solver_does_not_block_mode_switch(self):
        from recognition_mode import get_recognition_mode, set_recognition_mode

        self._seed_vision()
        set_recognition_mode("manual")
        started = {"count": 0}

        def hang(*args, **kwargs):
            started["count"] += 1
            time.sleep(2)
            return {"shadowUpdating": True}

        with patch("live_shadow.attach_live_shadow", side_effect=hang):
            t0 = time.monotonic()
            payload = self.app_main.apply_manual_facts({"facts": {"recognitionMode": "auto"}})
            elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.5)
        self.assertEqual(get_recognition_mode(), "auto")
        self.assertEqual(payload["recognitionMode"], "auto")
        self.assertEqual(started["count"], 0)

    def test_live_vision_ws_applies_mode_switch_without_waiting_solver(self):
        from recognition_mode import get_recognition_mode, set_recognition_mode

        match = self._seed_vision()
        set_recognition_mode("manual")
        self.app_main._LIVE_VISION_ACTIVE = True
        self.app_main._LIVE_VISION_MATCH_ID = match.id
        self.app_main.LATEST_PAYLOAD.update({"type": "manual_alpha_state", "q": 9})

        async def run():
            async with self.app_main.websockets.serve(self.app_main.ws_handler, "127.0.0.1", 0) as server:
                url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                async with self.app_main.websockets.connect(url) as socket:
                    await socket.send(json.dumps({
                        "type": "manual_facts",
                        "action": "manual_facts",
                        "facts": {"recognitionMode": "auto"},
                    }))
                    reply = None
                    for _ in range(4):
                        message = json.loads(await asyncio.wait_for(socket.recv(), 3))
                        if message.get("recognitionMode") == "auto":
                            reply = message
                            break
                    self.assertIsNotNone(reply)
                    self.assertEqual(reply.get("recognitionMode"), "auto")

        with patch("live_shadow.attach_live_shadow", side_effect=AssertionError("solver must not run")):
            asyncio.run(run())
        self.assertEqual(get_recognition_mode(), "auto")

    def test_cross_match_does_not_leak_box(self):
        from live_match_transport import LiveMatchSession

        match = self._seed_vision()
        original = match.id
        session = LiveMatchSession()
        session.observe({"scene": "IN_AUCTION"}, match)
        session.observe({"scene": "AUCTION_LOBBY"}, match)
        self.assertNotEqual(match.id, original)
        self.assertIsNone(match.facts["box"])
        self.assertEqual(match.facts_revision, 0)


if __name__ == "__main__":
    unittest.main()
