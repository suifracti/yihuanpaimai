# -*- coding: utf-8 -*-
"""Regression for offline file-frame replay into official archive + crop persist."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class OfflineFrameArchiveChainTests(unittest.TestCase):
    def test_keyframe_source_accepts_png_without_frame_prefix(self):
        from frame_source import KeyframeDirectorySource
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settlement.png"
            cv2.imencode(".png", np.zeros((16, 16, 3), np.uint8))[1].tofile(str(path))
            source = KeyframeDirectorySource(tmp)
            self.assertEqual(len(source.paths), 1)
            hwnd, img, stamp = source.provide()
            self.assertEqual(hwnd, 1)
            self.assertIsNotNone(img)
            self.assertEqual(img.shape[0], 16)
            hwnd2, img2, stamp2 = source.provide()
            self.assertTrue(source.eof)
            self.assertIsNone(img2)

    def test_hold_last_repeats_same_physical_file_until_stop(self):
        from frame_source import KeyframeDirectorySource
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settlement.png"
            cv2.imencode(".png", np.zeros((16, 16, 3), np.uint8))[1].tofile(str(path))
            stop = {"stop": False}
            source = KeyframeDirectorySource(tmp, stop_flag=stop, hold_last=True)
            first = source.provide()
            held = source.provide()
            self.assertIsNotNone(first[1])
            self.assertIsNotNone(held[1])
            self.assertFalse(source.eof)
            self.assertEqual(source.index, 1)
            stop["stop"] = True
            eof = source.provide()
            self.assertTrue(source.eof)
            self.assertIsNone(eof[1])
            self.assertEqual(eof[2], "EOF")

    def test_hold_last_reuses_observation_time_for_same_file(self):
        from frame_source import KeyframeDirectorySource
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settlement.png"
            cv2.imencode(".png", np.zeros((16, 16, 3), np.uint8))[1].tofile(str(path))
            source = KeyframeDirectorySource(tmp, hold_last=True)
            first = source.provide()
            held = source.provide()
            self.assertEqual(first[2], held[2])
            digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            self.assertEqual(source.content_fingerprint(), digest)

    def test_distinct_matches_sharing_origsha_do_not_merge(self):
        from canonical_history_store import (
            _extract_match_keys,
            _can_merge_records,
            _deduplicate_records,
            CanonicalHistoryStore,
        )
        from canonical_match_record import build_canonical_match_record_v7
        sha = "85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6"
        a = build_canonical_match_record_v7(
            match_id="live_match_aaa",
            played_at="2026-09-15T12:00:00+08:00",
            lifecycle_status="DRAFT",
            data_origin="live",
            settlement={"truthEvidence": {"fileOriginals": [{"sha256": sha}]}},
        )
        b = build_canonical_match_record_v7(
            match_id="live_match_bbb",
            played_at="2026-09-15T12:05:00+08:00",
            lifecycle_status="DRAFT",
            data_origin="live",
            settlement={"truthEvidence": {"fileOriginals": [{"sha256": sha}]}},
        )
        # Physical match keys are decoupled from evidence blob hashes
        self.assertEqual(_extract_match_keys(a), {"live_match_aaa"})
        self.assertEqual(_extract_match_keys(b), {"live_match_bbb"})
        self.assertFalse(_can_merge_records(a, b))

        # In-memory deduplication preserves both distinct matches
        deduped = _deduplicate_records([a, b])
        self.assertEqual(len(deduped), 2)
        self.assertEqual({d["id"] for d in deduped}, {"live_match_aaa", "live_match_bbb"})

        # Storage-level insertion preserves both records without collapsing
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "异环拍卖数据.json"
            store = CanonicalHistoryStore(db_path)
            db_path.write_text(json.dumps({"schemaVersion": 7, "records": [a]}), encoding="utf-8")
            store.persist_record_transactional(b, is_finalized=False)
            reloaded = store.read_database().get("records") or []
            self.assertEqual(len(reloaded), 2)
            self.assertEqual({r["id"] for r in reloaded}, {"live_match_aaa", "live_match_bbb"})

    def test_live_and_replay_sharing_origsha_do_not_merge(self):
        from canonical_history_store import _can_merge_records, _deduplicate_records
        sha = "85ce3299f6c8304dfd6a41168bbf04995e69c2cc32b2da3e838fa656c71e78b6"
        live_rec = {
            "id": "live_001",
            "dataOrigin": "live",
            "settlement": {"truthEvidence": {"fileOriginals": [{"sha256": sha}]}},
        }
        replay_rec = {
            "id": f"replayfile_{sha}",
            "dataOrigin": "replay",
            "settlement": {"truthEvidence": {"fileOriginals": [{"sha256": sha}]}},
        }
        self.assertFalse(_can_merge_records(live_rec, replay_rec))
        self.assertEqual(len(_deduplicate_records([live_rec, replay_rec])), 2)

    def test_archive_match_cuts_review_crops_from_observation_frame(self):
        from auto_archiver import AutoArchiver
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["YIHUAN_DATA_ROOT"] = tmp
            history = Path(tmp) / "history" / "异环拍卖数据.json"
            history.parent.mkdir(parents=True)
            frame = np.zeros((80, 80, 3), np.uint8)
            frame[10:40, 10:50] = (0, 180, 255)
            ctx = {
                "id": "offline_frame_archive_001",
                "matchId": "offline_frame_archive_001",
                "settlementReady": True,
                "frame": frame,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 100000,
                    "actualTotal": 150000,
                    "profit": 50000,
                    "items": [{
                        "name": "扭扭饼干",
                        "catalogId": "image15-0-2",
                        "status": "exact",
                        "price": 1234,
                        "row": 0,
                        "col": 0,
                        "widthCells": 1,
                        "heightCells": 1,
                        "bbox": [10, 10, 40, 30],
                        "rarity": "green",
                    }],
                },
                "settlementItems": [{
                    "name": "扭扭饼干",
                    "catalogId": "image15-0-2",
                    "status": "exact",
                    "price": 1234,
                    "row": 0,
                    "col": 0,
                    "widthCells": 1,
                    "heightCells": 1,
                    "bbox": [10, 10, 40, 30],
                    "rarity": "green",
                }],
                "warehouse": {
                    "slots": [{
                        "col": 0,
                        "row": 0,
                        "w": 1,
                        "h": 1,
                        "rarity": "green",
                        "evidenceLevel": "IDENTIFIED",
                        "identityStatus": "EXACT",
                        "identifiedName": "扭扭饼干",
                        "candidates": [{"catalogId": "image15-0-2", "name": "扭扭饼干"}],
                    }]
                },
            }
            saved = AutoArchiver(db_paths=[str(history)]).archive_match(ctx)
            self.assertIsNotNone(saved)
            units = (saved.get("settlement") or {}).get("reviewUnits") or saved.get("reviewUnits") or []
            self.assertEqual(len(units), 1)
            unit = units[0]
            self.assertEqual(unit.get("canonicalName") or unit.get("name"), "扭扭饼干")
            self.assertTrue(unit.get("cropPath"))
            self.assertTrue(unit.get("cropSha256"))
            crop = Path(tmp) / unit["cropPath"].replace("/", os.sep)
            self.assertTrue(crop.is_file(), crop)
            disk = crop.read_bytes()
            self.assertEqual(__import__("hashlib").sha256(disk).hexdigest(), unit["cropSha256"])
            rec = json.loads(history.read_text(encoding="utf-8"))
            self.assertEqual(len(rec.get("records") or []), 1)

    def test_archive_without_warehouse_ctx_still_persists_crops(self):
        from auto_archiver import AutoArchiver
        from canonical_match_record import validate_canonical_match_record_v7
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["YIHUAN_DATA_ROOT"] = tmp
            history = Path(tmp) / "history" / "异环拍卖数据.json"
            history.parent.mkdir(parents=True)
            frame = np.zeros((80, 80, 3), np.uint8)
            frame[10:40, 10:50] = (0, 180, 255)
            ctx = {
                "id": "offline_frame_archive_002",
                "matchId": "offline_frame_archive_002",
                "settlementReady": True,
                "frame": frame,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 100000,
                    "actualTotal": 150000,
                    "profit": 50000,
                    "items": [{
                        "name": "扭扭饼干",
                        "catalogId": "image15-0-2",
                        "status": "exact",
                        "price": 1234,
                        "row": 0,
                        "col": 0,
                        "widthCells": 1,
                        "heightCells": 1,
                        "bbox": [10, 10, 40, 30],
                        "rarity": "green",
                    }],
                },
                "settlementItems": [{
                    "name": "扭扭饼干",
                    "catalogId": "image15-0-2",
                    "status": "exact",
                    "price": 1234,
                    "row": 0,
                    "col": 0,
                    "widthCells": 1,
                    "heightCells": 1,
                    "bbox": [10, 10, 40, 30],
                    "rarity": "green",
                }],
            }
            saved = AutoArchiver(db_paths=[str(history)]).archive_match(ctx)
            self.assertIsNotNone(saved)
            self.assertEqual(str(saved.get("lifecycleStatus") or "").upper(), "DRAFT")
            warehouse = saved.get("warehouse") or {}
            self.assertIsInstance(warehouse.get("slots"), list)
            ok, reasons = validate_canonical_match_record_v7(saved, match_id="offline_frame_archive_002")
            self.assertTrue(ok, reasons)
            units = (saved.get("settlement") or {}).get("reviewUnits") or []
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0].get("confirmationStatus"), "CONFIRMED")
            self.assertTrue(units[0].get("cropPath"))
            crop = Path(tmp) / units[0]["cropPath"].replace("/", os.sep)
            self.assertTrue(crop.is_file(), crop)
            rec = json.loads(history.read_text(encoding="utf-8"))
            self.assertEqual(len(rec.get("records") or []), 1)

    def test_same_signature_does_not_duplicate_record_or_items(self):
        from auto_archiver import AutoArchiver
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["YIHUAN_DATA_ROOT"] = tmp
            history = Path(tmp) / "history" / "异环拍卖数据.json"
            history.parent.mkdir(parents=True)
            frame = np.zeros((80, 80, 3), np.uint8)
            ctx = {
                "id": "offline_frame_archive_003",
                "matchId": "offline_frame_archive_003",
                "settlementReady": True,
                "frame": frame,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 100000,
                    "actualTotal": 150000,
                    "profit": 50000,
                    "items": [{
                        "name": "扭扭饼干",
                        "catalogId": "image15-0-2",
                        "status": "exact",
                        "row": 0,
                        "col": 0,
                        "widthCells": 1,
                        "heightCells": 1,
                        "bbox": [10, 10, 40, 30],
                        "rarity": "green",
                    }],
                },
                "settlementItems": [{
                    "name": "扭扭饼干",
                    "catalogId": "image15-0-2",
                    "status": "exact",
                    "row": 0,
                    "col": 0,
                    "widthCells": 1,
                    "heightCells": 1,
                    "bbox": [10, 10, 40, 30],
                    "rarity": "green",
                }],
            }
            archiver = AutoArchiver(db_paths=[str(history)])
            first = archiver.archive_match(ctx)
            second = archiver.archive_match(ctx)
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            rec = json.loads(history.read_text(encoding="utf-8"))
            self.assertEqual(len(rec.get("records") or []), 1)
            units = (rec["records"][0].get("settlement") or {}).get("reviewUnits") or []
            self.assertEqual(len(units), 1)

    def test_new_archiver_same_replay_key_does_not_add_match(self):
        from auto_archiver import AutoArchiver
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["YIHUAN_DATA_ROOT"] = tmp
            history = Path(tmp) / "history" / "异环拍卖数据.json"
            history.parent.mkdir(parents=True)
            key = "replayfile_" + ("ab" * 32)
            frame = np.zeros((80, 80, 3), np.uint8)
            items = [{
                "name": "扭扭饼干",
                "catalogId": "image15-0-2",
                "status": "exact",
                "row": 0,
                "col": 0,
                "widthCells": 1,
                "heightCells": 1,
                "bbox": [10, 10, 40, 30],
                "rarity": "green",
            }]
            def ctx():
                return {
                    "id": key,
                    "matchId": key,
                    "recordStableKey": key,
                    "settlementReady": True,
                    "frame": frame,
                    "settlementData": {
                        "isSettlement": True,
                        "clearingPrice": 100000,
                        "actualTotal": 150000,
                        "profit": 50000,
                        "items": items,
                    },
                    "settlementItems": items,
                }
            first = AutoArchiver(db_paths=[str(history)]).archive_match(ctx())
            second = AutoArchiver(db_paths=[str(history)]).archive_match(ctx())
            self.assertIsNotNone(first)
            rec = json.loads(history.read_text(encoding="utf-8"))
            self.assertEqual(len(rec.get("records") or []), 1)
            self.assertEqual(rec["records"][0]["id"], key)
            units = (rec["records"][0].get("settlement") or {}).get("reviewUnits") or []
            self.assertEqual(len(units), 1)


if __name__ == "__main__":
    unittest.main()
