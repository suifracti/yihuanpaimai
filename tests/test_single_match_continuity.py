# -*- coding: utf-8 -*-
"""Targeted unit tests for Single Match Continuity (同一局连续性).

Verifies:
1. Replay session bootstrap creates matching identity and origin.
2. Manual facts and protection are saved to DRAFT on the exact matchId / recordStableKey.
3. Finalized settlement merges in-place into the existing DRAFT:
   - Database record count strictly equals 1 (no orphan draft).
   - Lifecycle transitions from DRAFT to FINALIZED.
   - Rule 7.1 manual protected facts (box, q, blue/red counts, goldAvg) are preserved.
   - All 29 review units and Item #10 visual-latiao-1x2 are attached.
4. LiveMatchReceiver properly synchronizes data_origin from snapshots.
5. Explicit Next Match transitions cleanly to record 2 without overwriting record 1.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"

for p in (
    r"C:\Program Files\Python310\Lib\site-packages",
    r"C:\Program Files\Python310\Lib\site-packages\win32",
    r"C:\Program Files\Python310\Lib\site-packages\win32\lib",
    str(PROJECT_ROOT),
    str(CORE_DIR),
    str(APP_DIR),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from auto_archiver import AutoArchiver, build_canonical_match_record_v7
from canonical_history_store import CanonicalHistoryStore, _can_merge_records
from current_match import CurrentMatch, FieldState
from live_match_transport import LiveMatchReceiver


class SingleMatchContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="nte_continuity_test_")
        self.db_path = os.path.join(self.tmp_dir, "异环拍卖数据.json")
        self.store = CanonicalHistoryStore(self.db_path)
        self.archiver = AutoArchiver(db_paths=[self.db_path])

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_live_match_receiver_syncs_data_origin(self):
        """Verify that LiveMatchReceiver.apply updates current_match.data_origin."""
        match = CurrentMatch()
        self.assertEqual(match.data_origin, "live")

        receiver = LiveMatchReceiver()
        worker_state = {
            "version": 1,
            "session": "test_session_1",
            "sequence": 1,
            "controlRevision": 0,
            "snapshot": {
                "id": "replayfile_85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6",
                "lifecycleStatus": "DRAFT",
                "schemaVersion": 7,
                "dataOrigin": "replay",
                "facts": {},
            },
        }
        applied = receiver.apply(worker_state, match)
        self.assertTrue(applied)
        self.assertEqual(match.id, "replayfile_85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6")
        self.assertEqual(match.data_origin, "replay")
        self.assertEqual(match.snapshot().get("dataOrigin"), "replay")
        self.assertEqual(match.to_canonical().get("dataOrigin"), "replay")

    def test_draft_to_finalized_in_place_evolution(self):
        """Verify that DRAFT evolutes to FINALIZED in-place with strictly 1 record."""
        replay_id = "replayfile_85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6"

        # 1. Establish match session
        match = CurrentMatch()
        match.id = replay_id
        match.data_origin = "replay"

        # 2. Enter manual facts and protect box
        match.apply_facts(
            {
                "q": 21,
                "blueCount": 3,
                "redCount": 1,
                "venue": "珊瑚场",
                "box": "琉璃宝箱",
                "goldAvg": 64836,
            },
            source="manual",
            intent="confirm",
        )
        match.field_states["box"] = FieldState(
            value="琉璃宝箱", source="manual", status="confirmed", protected=True
        )

        # 3. Save DRAFT
        draft_record = match.to_canonical()
        draft_record["lifecycleStatus"] = "DRAFT"
        draft_record["recordStableKey"] = replay_id
        draft_record["fieldStates"] = {
            "box": {"value": "琉璃宝箱", "source": "manual", "status": "confirmed", "protected": True}
        }
        written_draft = self.store.persist_record_transactional(draft_record, is_finalized=False)
        self.assertIsNotNone(written_draft)

        # Verify DB has exactly 1 DRAFT record
        db_after_draft = json.loads(Path(self.db_path).read_text(encoding="utf-8"))
        records_1 = db_after_draft.get("records") or []
        self.assertEqual(len(records_1), 1)
        self.assertEqual(records_1[0]["id"], replay_id)
        self.assertEqual(records_1[0]["dataOrigin"], "replay")
        self.assertEqual(records_1[0]["lifecycleStatus"], "DRAFT")

        # 4. Finalize settlement with 29 review units and Item #10 visual-latiao-1x2
        review_units = []
        for i in range(1, 30):
            uid = f"settlement_item_{i}"
            if i == 10:
                review_units.append(
                    {
                        "reviewUnitId": uid,
                        "slotIndex": i,
                        "canonicalName": "酷辣辣辣条",
                        "selectedCatalogId": "visual-latiao-1x2",
                        "price": 280000,
                        "confirmationStatus": "CONFIRMED",
                    }
                )
            else:
                review_units.append(
                    {
                        "reviewUnitId": uid,
                        "slotIndex": i,
                        "canonicalName": f"物品_{i}",
                        "selectedCatalogId": f"item_{i}",
                        "price": 1000,
                        "confirmationStatus": "CONFIRMED",
                    }
                )

        finalized_record = build_canonical_match_record_v7(
            match_id=replay_id,
            played_at="2026-09-15T20:00:00+08:00",
            lifecycle_status="FINALIZED",
            source="vision-auto-archiver",
            data_origin="replay",
            environment={"venue": "珊瑚场", "box": "未知箱型", "fieldCondition": "standard"},
            public_intel={"q": None},
            qualities={},
            settlement={
                "clearingPrice": 250000,
                "actualTotal": 580000,
                "realizedProfit": 330000,
                "winner": "玩家本人",
                "acquired": True,
                "status": "verified",
                "verified": True,
                "reviewUnits": review_units,
            },
        )
        finalized_record["recordStableKey"] = replay_id
        finalized_record["reviewUnits"] = review_units

        # Finalize via store
        written_final = self.store.persist_record_transactional(
            finalized_record, is_finalized=True, preserve_archive_sidecars=True
        )
        self.assertIsNotNone(written_final)

        # 5. Assert database state: STRICTLY 1 record, NO orphan draft!
        db_after_final = json.loads(Path(self.db_path).read_text(encoding="utf-8"))
        records_2 = db_after_final.get("records") or []
        self.assertEqual(len(records_2), 1, f"Expected strictly 1 record, got {len(records_2)}")

        final_rec = records_2[0]
        self.assertEqual(final_rec["id"], replay_id)
        self.assertEqual(final_rec["recordStableKey"], replay_id)
        self.assertEqual(final_rec["lifecycleStatus"], "FINALIZED")
        self.assertEqual(final_rec["dataOrigin"], "replay")

        # 6. Assert Rule 7.1 manual protected facts preserved in v7 namespaces
        env = final_rec.get("environment") or {}
        pub = final_rec.get("publicIntel") or {}
        quals = final_rec.get("qualities") or {}

        self.assertEqual(env.get("box"), "琉璃宝箱", "Protected box must be preserved")
        self.assertEqual(env.get("venue"), "珊瑚场", "Venue must be preserved")
        self.assertEqual(pub.get("q"), 21, "Manual q must be preserved")
        self.assertEqual(quals.get("blue", {}).get("count"), 3, "Manual blueCount must be preserved")
        self.assertEqual(quals.get("red", {}).get("count"), 1, "Manual redCount must be preserved")
        self.assertEqual(quals.get("gold", {}).get("avg"), 64836, "Manual goldAvg must be preserved")

        # 7. Assert reviewUnits and Item #10
        st = final_rec.get("settlement") or {}
        saved_units = st.get("reviewUnits") or final_rec.get("reviewUnits") or []
        self.assertEqual(len(saved_units), 29)
        u10 = next((u for u in saved_units if u.get("reviewUnitId") == "settlement_item_10"), None)
        self.assertIsNotNone(u10)
        self.assertEqual(u10.get("selectedCatalogId"), "visual-latiao-1x2")
        self.assertEqual(u10.get("price"), 280000)
        self.assertEqual(u10.get("confirmationStatus"), "CONFIRMED")

        # 8. Assert explicit Next Match creates 2nd record without overwriting 1st
        match.begin_next_match()
        self.assertNotEqual(match.id, replay_id)
        match.apply_facts({"q": 15, "venue": "黄金场"})
        draft_2 = match.to_canonical()
        draft_2["lifecycleStatus"] = "DRAFT"
        self.store.persist_record_transactional(draft_2, is_finalized=False)

        db_after_next = json.loads(Path(self.db_path).read_text(encoding="utf-8"))
        records_3 = db_after_next.get("records") or []
        self.assertEqual(len(records_3), 2, f"Expected 2 records after next match, got {len(records_3)}")

        # Verify record 1 is still the finalized record
        rec_final = next((r for r in records_3 if r.get("lifecycleStatus") == "FINALIZED"), None)
        rec_draft = next((r for r in records_3 if r.get("lifecycleStatus") == "DRAFT"), None)
        self.assertIsNotNone(rec_final)
        self.assertIsNotNone(rec_draft)
        self.assertEqual(rec_final["id"], replay_id)
        self.assertEqual(rec_final["settlement"]["clearingPrice"], 250000)
        self.assertEqual(rec_draft["id"], match.id)


if __name__ == "__main__":
    unittest.main()
