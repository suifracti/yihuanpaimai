# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "app"))

from current_match import CurrentMatch
from live_match_transport import LiveMatchPublisher, LiveMatchReceiver
import main
from recognition_mode import set_recognition_mode, get_recognition_mode


class LiveMatchCanonicalSOTTests(unittest.TestCase):
    def setUp(self):
        self.receiver = LiveMatchReceiver()
        self.publisher = LiveMatchPublisher()

    def test_manual_override_protected_while_vision_updates_dynamic_facts(self):
        match = CurrentMatch()
        # User manually sets venue, box, q, costs
        match.apply_facts({
            "venue": "中级场 · 珊瑚场",
            "venueId": "venue-shanhu",
            "box": "珊瑚宝箱",
            "boxId": "box-shanhu",
            "q": 12,
            "entryCost": 50000,
        }, source="manual")

        # Worker observes different facts from OCR, plus dynamic seat & bid facts
        worker = CurrentMatch()
        worker.id = match.id
        worker.apply_facts({
            "venue": "初级场 · 海贝场",
            "box": "琉璃宝箱",
            "q": 9,
            "leaderBid": 70000,
            "roundNo": 2,
            "seats": [
                {"slot": 1, "name": "PlayerA", "bid": 70000, "observationStatus": "VISIBLE"},
                {"slot": 2, "name": "PlayerB", "bid": 60000, "observationStatus": "VISIBLE"},
            ]
        }, source="vision")

        # Worker publisher has controlRevision=0
        state = self.publisher.attach({}, worker)["visionState"]
        self.assertEqual(state["controlRevision"], 0)

        # Apply to match with minimum_control_revision=3 (simulating UI revision ahead)
        accepted = self.receiver.apply(state, match, minimum_control_revision=3)
        self.assertTrue(accepted, "Receiver must not reject whole frame on revision mismatch")

        # Manual facts remain protected
        self.assertEqual(match.facts["venue"], "中级场 · 珊瑚场")
        self.assertEqual(match.facts["box"], "珊瑚宝箱")
        self.assertEqual(match.facts["q"], 12)
        self.assertEqual(match.facts["entryCost"], 50000)

        # Dynamic/un-overridden facts from vision are updated
        self.assertEqual(match.facts["leaderBid"], 70000)
        self.assertEqual(match.facts["roundNo"], 2)
        self.assertEqual(len(match.facts["seats"]), 2)

        # Canonical overlayState contains the authoritative merged state
        overlay = main.build_canonical_overlay_state(match)
        self.assertEqual(overlay["venue"], "中级场 · 珊瑚场")
        self.assertEqual(overlay["box"], "珊瑚宝箱")
        self.assertEqual(overlay["q"], 12)
        self.assertEqual(overlay["leaderBid"], 70000)
        self.assertEqual(overlay["round"], 2)

    def test_manual_mode_does_not_halt_vision_sync(self):
        match = CurrentMatch()
        set_recognition_mode("manual")
        try:
            # When recognitionMode is manual, sync_vision_to_current_match must still sync
            # un-overridden facts to CURRENT_MATCH
            saved = main.CURRENT_MATCH
            main.CURRENT_MATCH = match
            try:
                # User manually sets q
                match.apply_facts({"q": 10}, source="manual")
                
                # Vision arrives with round and dynamic seats
                ctx = {
                    "scene": "IN_AUCTION",
                    "round": 3,
                    "leaderBid": 120000,
                    "recognitionMode": "manual",
                    "q": 8,  # vision sees 8
                }
                main.sync_vision_to_current_match(ctx)

                # q remains 10 (protected)
                self.assertEqual(match.facts["q"], 10)
                # Dynamic facts updated despite manual mode
                self.assertEqual(match.facts["roundNo"], 3)
                self.assertEqual(match.facts["leaderBid"], 120000)
            finally:
                main.CURRENT_MATCH = saved
        finally:
            set_recognition_mode("auto")


if __name__ == "__main__":
    unittest.main()
