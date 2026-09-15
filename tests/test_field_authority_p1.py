# -*- coding: utf-8 -*-
"""P1 field authority: box must not be cleared by empty auto/manual patches."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "app"), str(ROOT / "core")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from current_match import CurrentMatch
from live_match_control import LiveMatchControl
from live_match_transport import LiveMatchPublisher, LiveMatchReceiver


WOOD_BOX = "实木宝箱 · 中级藏品概率提升"
Q_ONLY_FORM = {
    "venueId": None,
    "venue": None,
    "boxId": None,
    "box": None,
    "fieldCondition": "standard",
    "q": 12,
    "goldAvg": None,
    "purpleCount": None,
    "purple": None,
    "purpleAvg": None,
    "blueCount": None,
    "goldCount": None,
    "redCount": None,
    "totalItems": None,
    "totalGrid": None,
    "goldGrid": None,
    "purpleGrid": None,
    "knownGold": "",
    "knownRed": "",
    "knownPurple": "",
}


def _audit_for(match: CurrentMatch, field: str):
    return [row for row in match.field_audit() if row.get("field") == field]


class FieldAuthorityCurrentMatchTests(unittest.TestCase):
    def test_empty_auto_observation_does_not_clear_existing_box(self):
        match = CurrentMatch()
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        match.apply_facts({"box": None, "q": 12}, source="vision")
        self.assertEqual(match.facts["box"], WOOD_BOX)
        self.assertEqual(match.facts["q"], 12)
        reasons = {row["reason"] for row in _audit_for(match, "box")}
        self.assertIn("MISSING_DOES_NOT_CLEAR", reasons)

    def test_unknown_placeholder_does_not_clear_existing_box(self):
        match = CurrentMatch()
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        match.apply_facts({"box": "未知箱型"}, source="vision")
        self.assertEqual(match.facts["box"], WOOD_BOX)

    def test_manual_null_without_clear_does_not_overwrite_or_block_later_ocr(self):
        match = CurrentMatch()
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        match.apply_facts({"q": 12, "box": None, "boxId": None, "venue": None}, source="manual")
        self.assertEqual(match.facts["box"], WOOD_BOX)
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        self.assertEqual(match.facts["box"], WOOD_BOX)
        self.assertFalse(match.field_states["box"].protected)

    def test_same_value_confirm_protects_against_conflicting_vision(self):
        match = CurrentMatch()
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        match.apply_facts({"box": WOOD_BOX}, source="manual", intent="confirm")
        self.assertTrue(match.field_states["box"].protected)
        match.apply_facts({"box": "琉璃宝箱 · 宝石类概率提升"}, source="vision")
        self.assertEqual(match.facts["box"], WOOD_BOX)
        conflict = [row for row in _audit_for(match, "box") if row["decision"] == "conflict"]
        self.assertTrue(conflict)
        self.assertEqual(match.field_states["box"].candidate, "琉璃宝箱 · 宝石类概率提升")

    def test_explicit_clear_then_restore_auto_allows_ocr(self):
        match = CurrentMatch()
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        match.apply_facts({}, source="manual", cleared_fields=["box", "boxId"])
        self.assertIsNone(match.facts["box"])
        self.assertEqual(match.field_states["box"].status, "cleared")
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        self.assertIsNone(match.facts["box"])
        match.apply_facts({}, source="manual", restore_auto_fields=["box", "boxId"])
        self.assertFalse(match.field_states["box"].protected)
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        self.assertEqual(match.facts["box"], WOOD_BOX)

    def test_snapshot_nulls_do_not_clear_existing_box(self):
        match = CurrentMatch()
        match.apply_facts({"box": WOOD_BOX, "q": 12}, source="vision")
        snapshot = match.snapshot()
        snapshot["box"] = None
        snapshot["boxId"] = None
        match.apply_facts(snapshot, source="vision", intent="snapshot")
        self.assertEqual(match.facts["box"], WOOD_BOX)
        self.assertEqual(match.facts["q"], 12)


class FieldAuthorityVisionSyncTests(unittest.TestCase):
    def test_catalog_selection_null_does_not_clear_observed_box(self):
        import main as app_main

        current = CurrentMatch()
        current.apply_facts({"box": WOOD_BOX}, source="vision")
        ctx = {
            "scene": "IN_AUCTION",
            "venue": "中级场 · 珊瑚场",
            "lobbyVenueKey": "shanhu",
            "box": None,
            "q": 12,
        }
        with patch.object(app_main, "CURRENT_MATCH", current):
            app_main.sync_vision_to_current_match(ctx)
        self.assertEqual(current.facts["box"], WOOD_BOX)
        self.assertEqual(current.facts["q"], 12)
        self.assertEqual(current.facts["venueId"], "venue-shanhu")


class FieldAuthorityManualFormTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="field-authority-p1-")
        self.old_root = os.environ.get("YIHUAN_DATA_ROOT")
        os.environ["YIHUAN_DATA_ROOT"] = self.temp.name
        import main as app_main

        self.app_main = app_main
        app_main.cancel_draft_save()
        self.old_match_id = app_main.CURRENT_MATCH.id
        self.old_overrides = dict(app_main._LIVE_MANUAL_OVERRIDES)
        app_main._LIVE_MANUAL_OVERRIDES.clear()
        app_main.CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        self.app_main.cancel_draft_save()
        self.app_main.CURRENT_MATCH.begin_next_match()
        self.app_main._LIVE_MANUAL_OVERRIDES.clear()
        self.app_main._LIVE_MANUAL_OVERRIDES.update(self.old_overrides)
        if self.old_root is None:
            os.environ.pop("YIHUAN_DATA_ROOT", None)
        else:
            os.environ["YIHUAN_DATA_ROOT"] = self.old_root
        self.temp.cleanup()

    def test_whole_form_q_edit_does_not_clear_existing_box(self):
        match = self.app_main.CURRENT_MATCH
        match.apply_facts({"box": WOOD_BOX}, source="vision")
        payload = self.app_main.apply_manual_facts({"facts": dict(Q_ONLY_FORM)})
        self.assertEqual(match.facts["box"], WOOD_BOX)
        self.assertEqual(match.facts["q"], 12)
        control = payload.get("manualControl") or {}
        self.assertNotIn("box", control.get("facts") or {})
        self.assertNotIn("box", self.app_main._LIVE_MANUAL_OVERRIDES)

    def test_explicit_unknown_box_still_clears(self):
        match = self.app_main.CURRENT_MATCH
        match.apply_facts({"box": WOOD_BOX, "venueId": "venue-shanhu"}, source="vision")
        payload = self.app_main.apply_manual_facts({
            "facts": {"venueId": "venue-shanhu", "boxId": None, "boxUnknown": True},
            "clearedFields": ["box", "boxId"],
        })
        self.assertIsNone(match.facts["box"])
        self.assertIsNone(payload.get("boxId"))


class FieldAuthorityTransportTests(unittest.TestCase):
    def test_control_command_null_facts_do_not_block_ocr(self):
        current = CurrentMatch()
        current.apply_facts({"box": WOOD_BOX, "q": 12}, source="vision")
        publisher = LiveMatchPublisher()
        control = LiveMatchControl()
        pipe = type("P", (), {"reset_session_state": lambda self: None})()
        session = type("S", (), {"active": False, "observe": lambda *a, **k: None})()
        command = {
            "revision": 1,
            "expectedMatchId": current.id,
            "snapshot": current.snapshot(),
            "facts": {"q": 12, "box": None, "boxId": None, "venue": None},
        }
        self.assertTrue(control.apply(command, current, publisher, pipe, session))
        ctx = control.apply_to_frame(
            {"scene": "IN_AUCTION", "q": 12, "box": WOOD_BOX},
            current,
            session,
        )
        self.assertEqual(ctx["box"], WOOD_BOX)
        self.assertNotIn("box", control.overrides)

    def test_explicit_clear_in_control_command_does_block_until_restore(self):
        current = CurrentMatch()
        current.apply_facts({"box": WOOD_BOX}, source="vision")
        publisher = LiveMatchPublisher()
        control = LiveMatchControl()
        pipe = type("P", (), {"reset_session_state": lambda self: None})()
        session = type("S", (), {"active": False, "observe": lambda *a, **k: None})()
        command = {
            "revision": 1,
            "expectedMatchId": current.id,
            "snapshot": current.snapshot(),
            "facts": {"box": None},
            "clearedFields": ["box"],
        }
        self.assertTrue(control.apply(command, current, publisher, pipe, session))
        ctx = control.apply_to_frame(
            {"scene": "IN_AUCTION", "box": WOOD_BOX},
            current,
            session,
        )
        self.assertIsNone(ctx.get("box"))
        restore = {
            "revision": 2,
            "expectedMatchId": current.id,
            "snapshot": current.snapshot(),
            "facts": {},
            "restoreAutoFields": ["box"],
        }
        self.assertTrue(control.apply(restore, current, publisher, pipe, session))
        ctx = control.apply_to_frame(
            {"scene": "IN_AUCTION", "box": WOOD_BOX},
            current,
            session,
        )
        self.assertEqual(ctx["box"], WOOD_BOX)

    def test_receiver_snapshot_nulls_do_not_wipe_gui_box(self):
        worker, mirror = CurrentMatch(), CurrentMatch()
        mirror.id = worker.id
        mirror.apply_facts({"box": WOOD_BOX}, source="vision")
        worker.apply_facts({"q": 12}, source="vision")
        publisher, receiver = LiveMatchPublisher(), LiveMatchReceiver()
        state = publisher.attach({}, worker)["visionState"]
        self.assertEqual(state["snapshot"]["id"], mirror.id)
        self.assertTrue(receiver.apply(state, mirror))
        self.assertEqual(mirror.facts["box"], WOOD_BOX)
        self.assertEqual(mirror.facts["q"], 12)


if __name__ == "__main__":
    unittest.main()
