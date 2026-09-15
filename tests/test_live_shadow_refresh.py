# -*- coding: utf-8 -*-
"""Stage 2: archive success refreshes Live history snapshot without restart."""
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from auto_archiver import AutoArchiver
from live_shadow import (
    compute_live_probability_profile,
    current_snapshot,
    history_generation,
    ingest_archived_record,
    load_history_snapshot,
    reset_live_shadow_state,
    snapshot_size,
)

REAL_DB = os.path.join(PROJECT_ROOT, "异环拍卖数据.json")

CTX = {
    "playedAt": "2099-12-31T23:59:00",
    "venue": "中级场 · 珊瑚场",
    "lobbyVenue": "中级场 · 珊瑚场",
    "box": "琉璃宝箱 · 宝石类概率提升",
    "fieldCondition": "standard",
    "q": 12,
    "goldAvg": 74379,
    "purple": 7,
}


def _seed_db(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": "v0.6", "schemaVersion": 6, "records": records}, fh, ensure_ascii=False)


def _eligible_red_record(rid, played_at="2099-01-01T00:00:00", price=150051, name="他山之石"):
    text = f"{name} {price}"
    return {
        "id": rid,
        "playedAt": played_at,
        "venue": "中级场 · 珊瑚场",
        "box": "螺钿宝箱 · 古董类概率提升",
        "fieldCondition": "standard",
        "q": 11,
        "goldAvg": 30000,
        "purpleCount": 7,
        "redCount": 1,
        "actualTotal": 400000,
        "redInventoryComplete": True,
        "settlementVerifiedRedItems": text,
        "settlement": {
            "status": "verified",
            "redInventoryComplete": True,
            "redCount": 1,
            "verifiedRedItems": text,
            "realizedState": {"gold": 3, "purple": 7, "red": 1},
        },
        "source": "test-eligible",
    }


def _ineligible_auto_record(rid, played_at="2099-01-02T00:00:00"):
    return {
        "id": rid,
        "playedAt": played_at,
        "venue": "中级场 · 珊瑚场",
        "box": "琉璃宝箱 · 宝石类概率提升",
        "fieldCondition": "standard",
        "q": 12,
        "goldAvg": 74379,
        "purple": 7,
        "actualTotal": 631993,
        "clearingPrice": 666666,
        "redInventoryComplete": None,
        "settlementVerifiedRedItems": None,
        "settlementItems": [{"name": "候选(14件)", "price": 2035}],
        "source": "0.65-vision-auto-archiver",
    }


def _archive_ctx(**overrides):
    ctx = {
        "venue": "中级场 · 珊瑚场",
        "box": "琉璃宝箱 · 宝石类概率提升",
        "fieldCondition": "standard",
        "q": 12,
        "goldAvg": 74379,
        "purple": 7,
        "settlementReady": True,
        "settlementData": {
            "isSettlement": True,
            "clearingPrice": 666666,
            "actualTotal": 631993,
            "profit": -34673,
        },
    }
    ctx.update(overrides)
    return ctx


class TestLiveShadowRefresh(unittest.TestCase):
    def setUp(self):
        reset_live_shadow_state()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "hist.json")

    def tearDown(self):
        reset_live_shadow_state()
        self.tmp.cleanup()

    def test_unverified_archive_stays_draft_without_ingesting_shadow(self):
        _seed_db(self.db, [_ineligible_auto_record("seed-1", "2026-08-01T00:00:00")])
        load_history_snapshot(self.db)
        g0 = history_generation()
        n0 = snapshot_size()
        rec = AutoArchiver(db_paths=[self.db]).archive_match(_archive_ctx())
        self.assertIsNotNone(rec)
        self.assertEqual(rec["lifecycleStatus"], "DRAFT")
        self.assertEqual(snapshot_size(), n0)
        self.assertEqual(history_generation(), g0)
        ids = [r["id"] for r in current_snapshot()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(rec["id"], ids)
        with open(self.db, encoding="utf-8") as fh:
            disk = json.load(fh)
        disk_hit = next(r for r in disk["records"] if r["id"] == rec["id"])
        self.assertEqual(disk_hit["lifecycleStatus"], "DRAFT")
        self.assertEqual(disk_hit["settlement"]["actualTotal"], rec["settlement"]["actualTotal"])

    def test_duplicate_id_replaces_without_append(self):
        rec = _ineligible_auto_record("dup-1")
        _seed_db(self.db, [rec])
        load_history_snapshot(self.db)
        g0 = history_generation()
        updated = deepcopy(rec)
        updated["actualTotal"] = 777777
        info = ingest_archived_record(updated, self.db)
        self.assertTrue(info["replaced"])
        self.assertEqual(snapshot_size(), 1)
        self.assertEqual(history_generation(), g0 + 1)
        self.assertEqual(current_snapshot()[0]["actualTotal"], 777777)

    def test_archive_write_failure_does_not_bump(self):
        _seed_db(self.db, [])
        load_history_snapshot(self.db)
        g0 = history_generation()
        n0 = snapshot_size()
        blocking_file = os.path.join(self.tmp.name, "blocking_file_not_dir")
        with open(blocking_file, "w", encoding="utf-8") as f:
            f.write("not a directory")
        failing_path = os.path.join(blocking_file, "subpath", "db.json")
        rec = AutoArchiver(db_paths=[failing_path]).archive_match(_archive_ctx())
        self.assertIsNone(rec)
        self.assertEqual(history_generation(), g0)
        self.assertEqual(snapshot_size(), n0)

    def test_cache_misses_after_generation_change(self):
        _seed_db(self.db, [_ineligible_auto_record("seed-cache", "2026-08-01T00:00:00")])
        load_history_snapshot(self.db)
        _, first = compute_live_probability_profile(CTX, db_path=self.db)
        self.assertIn(first["cache"], ("hit", "miss"))
        ingest_archived_record(_ineligible_auto_record("seed-cache-2", "2026-08-02T00:00:00"), self.db)
        _, second = compute_live_probability_profile(CTX, db_path=self.db)
        self.assertEqual(second["cache"], "miss")
        self.assertEqual(second["historyGen"], first["historyGen"] + 1)

    def test_ineligible_new_record_does_not_change_shadow(self):
        _seed_db(self.db, [_eligible_red_record("old-eli", "2026-08-16T00:00:00")])
        load_history_snapshot(self.db)
        before, meta0 = compute_live_probability_profile(CTX, db_path=self.db)
        rec = AutoArchiver(db_paths=[self.db]).archive_match(_archive_ctx())
        self.assertIsNotNone(rec)
        after, meta1 = compute_live_probability_profile(CTX, db_path=self.db)
        self.assertEqual(meta1["historyN"], meta0["historyN"] + 1)
        self.assertGreater(meta1["historyGen"], meta0["historyGen"])
        self.assertEqual(before["coverageRatio"], after["coverageRatio"])
        self.assertEqual(before.get("shadowWhole"), after.get("shadowWhole"))
        self.assertEqual(before["supportedStateCount"], after["supportedStateCount"])

    def test_eligible_new_record_can_change_profile(self):
        _seed_db(self.db, [])
        load_history_snapshot(self.db)
        before, _ = compute_live_probability_profile(CTX, db_path=self.db)
        ingest_archived_record(_eligible_red_record("new-eli", "2099-06-01T00:00:00"), self.db)
        after, meta = compute_live_probability_profile(CTX, db_path=self.db)
        self.assertEqual(meta["cache"], "miss")
        self.assertNotEqual(
            (before.get("source"), before.get("sameR") if False else before.get("status"), before.get("partialShadowP50"), before.get("shadowWhole")),
            (after.get("source"), after.get("status"), after.get("partialShadowP50"), after.get("shadowWhole")),
        )
        # Empty history has no complete red labels; adding one R=1 complete record must become visible.
        self.assertGreaterEqual(after["supportedStateCount"], before["supportedStateCount"])

    def test_memory_only_archive_does_not_touch_live_snapshot(self):
        _seed_db(self.db, [])
        load_history_snapshot(self.db)
        g0 = history_generation()
        rec = AutoArchiver(db_paths=[]).archive_match(_archive_ctx())
        self.assertIsNotNone(rec)
        self.assertEqual(history_generation(), g0)
        self.assertEqual(snapshot_size(), 0)


class TestStage1StillHoldsOnRealDb(unittest.TestCase):
    def test_1415_numbers_unchanged(self):
        if not os.path.exists(REAL_DB):
            self.skipTest("real db missing")
        reset_live_shadow_state()
        with open(os.path.join(PROJECT_ROOT, "tests", "fixtures", "shadow_1415_legacy.json"), encoding="utf-8") as fh:
            fixture = json.load(fh)
        profile, meta = compute_live_probability_profile({
            "playedAt": "2026-08-17T14:15:59.030277",
            "venue": "中级场 · 珊瑚场",
            "box": "琉璃宝箱 · 宝石类概率提升",
            "fieldCondition": "standard",
            "q": 12,
            "goldAvg": 74379,
            "purple": 7,
        }, db_path=REAL_DB)
        self.assertGreaterEqual(meta["historyN"], 178)
        self.assertTrue(profile["isFullShadow"])
        self.assertAlmostEqual(profile["shadowWhole"]["p50"], fixture["shadowWhole"]["p50"], places=4)
        reset_live_shadow_state()


if __name__ == "__main__":
    unittest.main()
