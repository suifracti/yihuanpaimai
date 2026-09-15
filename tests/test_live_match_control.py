"""GUI command acknowledgement, correction persistence and next-match isolation."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from current_match import CurrentMatch
from live_match_control import LiveMatchControl
from live_match_transport import LiveMatchPublisher, LiveMatchReceiver, LiveMatchSession


class LiveMatchControlTests(unittest.TestCase):
    def setUp(self):
        self.current = CurrentMatch()
        self.publisher = LiveMatchPublisher()
        self.receiver = LiveMatchReceiver()
        self.session = LiveMatchSession()
        self.control = LiveMatchControl()
        self.pipe = Mock()

    def command(self, **kwargs):
        return dict(revision=1, expectedMatchId=self.current.id,
                    snapshot=self.current.snapshot(), **kwargs)

    def test_old_frames_blocked_until_manual_correction_is_acknowledged(self):
        mirror = CurrentMatch()
        self.current.apply_facts({"q": 12})
        old = self.publisher.attach({}, self.current)["visionState"]
        self.assertTrue(self.receiver.apply(old, mirror))
        mirror.apply_facts({"q": 9}, source="manual")
        # In field-level authority, revision differences do not drop the whole frame;
        # unoverridden fields update, while protected manual fields (q) are preserved.
        self.assertTrue(self.receiver.apply(self.publisher.attach({}, self.current)["visionState"], mirror, 1))
        self.assertEqual(mirror.facts["q"], 9)
        self.assertTrue(self.control.apply(self.command(facts={"q": 9}), self.current,
                                           self.publisher, self.pipe, self.session))
        ctx = self.control.apply_to_frame({"scene": "IN_AUCTION", "q": 12}, self.current, self.session)
        self.current.apply_facts(ctx, source="vision")
        self.assertTrue(self.receiver.apply(self.publisher.attach({}, self.current)["visionState"], mirror, 1))
        self.assertEqual(mirror.facts["q"], 9)

    def test_next_match_suppresses_old_bill_until_exit(self):
        next_match = CurrentMatch()
        command = self.command(reset=True)
        command["snapshot"] = next_match.snapshot()
        self.assertTrue(self.control.apply(command, self.current, self.publisher, self.pipe, self.session))
        old_bill = {"scene": "SETTLEMENT", "isSettlement": True, "settlementReady": True,
                    "settlementData": {"actualTotal": 10000}}
        filtered = self.control.apply_to_frame(old_bill, self.current, self.session)
        self.assertFalse(filtered["isSettlement"])
        self.assertNotIn("settlementData", filtered)
        self.control.apply_to_frame({"scene": "AUCTION_LOBBY"}, self.current, self.session)
        self.assertEqual(self.current.id, next_match.id)
        self.assertFalse(self.control.awaiting_exit)
        self.pipe.reset_session_state.assert_called_once()

    def test_natural_exit_releases_previous_manual_overrides(self):
        self.control.apply(self.command(facts={"q": 9}), self.current, self.publisher, self.pipe, self.session)
        self.control.apply_to_frame({"scene": "IN_AUCTION", "q": 12}, self.current, self.session)
        self.control.apply_to_frame({"scene": "AUCTION_LOBBY"}, self.current, self.session)
        ctx = self.control.apply_to_frame({"scene": "IN_AUCTION", "q": 7}, self.current, self.session)
        self.assertEqual(ctx["q"], 7)

    def test_stale_and_duplicate_commands_do_not_change_live_match(self):
        command = self.command(facts={"q": 9})
        self.publisher.attach({}, self.current)
        command["expectedMatchId"] = "old"
        command["snapshot"]["id"] = "other"
        self.assertFalse(self.control.apply(command, self.current, self.publisher, self.pipe, self.session))
        self.assertIsNone(self.current.facts["q"])
        command = self.command(facts={"q": 9})
        self.assertTrue(self.control.apply(command, self.current, self.publisher, self.pipe, self.session))
        self.assertFalse(self.control.apply(command, self.current, self.publisher, self.pipe, self.session))

    def test_bootstrap_restores_current_id_and_corrections_after_reconnect(self):
        old = CurrentMatch()
        old.apply_facts({"q": 9})
        command = {"revision": 0, "snapshot": old.snapshot(), "facts": {"q": 9}}
        self.assertTrue(self.control.apply(command, self.current, self.publisher,
                                           self.pipe, self.session, bootstrap=True))
        self.assertEqual(self.current.id, old.id)
        frame = self.control.apply_to_frame({"scene": "IN_AUCTION", "q": 12}, self.current, self.session)
        self.assertEqual(frame["q"], 9)
