import copy
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))
sys.path.insert(0, str(REPO_ROOT / "app"))

from current_match import CurrentMatch, empty_facts
from live_match_transport import LiveMatchReceiver
from venue_box_catalog import load_catalog, normalize_vision_venue


class VenuePreservationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog(
            REPO_ROOT / "assets" / "venue_box_catalog_v1" / "venue_box_catalog_v1.json"
        )
        self.match = CurrentMatch()

    def test_normalize_vision_venue_with_tier_prefix(self):
        norm = normalize_vision_venue(self.catalog, "中级场 · 珊瑚场")
        self.assertEqual(norm.get("status"), "NORMALIZED")
        self.assertEqual(norm.get("venueId"), "venue-shanhu")

        norm2 = normalize_vision_venue(self.catalog, "初级场 · 海贝场")
        self.assertEqual(norm2.get("status"), "NORMALIZED")
        self.assertEqual(norm2.get("venueId"), "venue-haibei")

        norm3 = normalize_vision_venue(self.catalog, "珊瑚场")
        self.assertEqual(norm3.get("status"), "NORMALIZED")
        self.assertEqual(norm3.get("venueId"), "venue-shanhu")

    def test_manual_venue_persists_across_vision_null_refreshes(self):
        # 1. User sets venue manually
        self.match.apply_facts({"venueId": "venue-shanhu", "venue": "珊瑚场"}, source="manual", intent="confirm")
        self.assertEqual(self.match.facts["venue"], "珊瑚场")
        self.assertEqual(self.match.facts["venueId"], "venue-shanhu")
        self.assertTrue(self.match.field_states["venue"].protected)

        # 2. Subsequent vision refresh with venue=None
        self.match.apply_facts({"venueId": None, "venue": None, "q": 10}, source="vision", intent="observe")
        # Venue must not be cleared
        self.assertEqual(self.match.facts["venue"], "珊瑚场")
        self.assertEqual(self.match.facts["venueId"], "venue-shanhu")
        self.assertEqual(self.match.facts["q"], 10)

        # 3. Vision snapshot intent with venue=None
        self.match.apply_facts({"venueId": None, "venue": None}, source="vision", intent="snapshot")
        self.assertEqual(self.match.facts["venue"], "珊瑚场")
        self.assertEqual(self.match.facts["venueId"], "venue-shanhu")

    def test_stale_worker_control_revision_rejected(self):
        receiver = LiveMatchReceiver()
        self.match.apply_facts({"venueId": "venue-shanhu", "venue": "珊瑚场"}, source="manual", intent="confirm")

        stale_state = {
            "version": 1,
            "controlRevision": 0,
            "session": "sess_1",
            "sequence": 1,
            "snapshot": {
                "schemaVersion": 7,
                "id": self.match.id,
                "lifecycleStatus": "DRAFT",
                "createdAt": "2026-09-14T12:00:00",
                "updatedAt": "2026-09-14T12:00:00",
                "venue": None,
                "venueId": None,
            },
        }
        # Even if worker frame arrives with venue=None and stale controlRevision,
        # manual venue is protected and not wiped.
        applied = receiver.apply(stale_state, self.match, minimum_control_revision=1)
        self.assertTrue(applied)
        self.assertEqual(self.match.facts["venue"], "珊瑚场")
        self.assertEqual(self.match.facts["venueId"], "venue-shanhu")

        # When worker catches up to revision 1 -> accepted, manual venue remains preserved
        fresh_state = copy.deepcopy(stale_state)
        fresh_state["controlRevision"] = 1
        fresh_state["sequence"] = 2
        applied = receiver.apply(fresh_state, self.match, minimum_control_revision=1)
        self.assertTrue(applied)
        self.assertEqual(self.match.facts["venue"], "珊瑚场")
        self.assertEqual(self.match.facts["venueId"], "venue-shanhu")

    def test_initial_worker_handshake_preserves_existing_facts(self):
        receiver = LiveMatchReceiver()
        # User already selected venue before worker sends frame
        self.match.apply_facts({"venueId": "venue-shanhu", "venue": "珊瑚场"}, source="manual", intent="confirm")

        # Worker connects with its own generated match_id
        initial_worker_state = {
            "version": 1,
            "controlRevision": 0,
            "session": "sess_initial",
            "sequence": 1,
            "snapshot": {
                "schemaVersion": 7,
                "id": "draft_worker_bootstrap",
                "lifecycleStatus": "DRAFT",
                "createdAt": "2026-09-14T12:00:00",
                "updatedAt": "2026-09-14T12:00:00",
                "venue": None,
                "venueId": None,
            },
        }
        applied = receiver.apply(initial_worker_state, self.match, minimum_control_revision=0)
        self.assertTrue(applied)
        # Must adopt worker id, but MUST NOT wipe existing manual facts!
        self.assertEqual(self.match.id, "draft_worker_bootstrap")
        self.assertEqual(self.match.facts["venue"], "珊瑚场")


if __name__ == "__main__":
    unittest.main()
