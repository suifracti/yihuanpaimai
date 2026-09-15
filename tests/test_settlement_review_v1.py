# -*- coding: utf-8 -*-
"""Settlement Review + Screenshot Import v1 gates.

1. HISTORY_REVIEW_BACKEND_GATE: whitelisted review DTO from a History record
   (machine proposals + bounded settlement + screenshot evidence).
2. SCREENSHOT_IMPORT_REVIEWED_SAVE_GATE: import screenshot -> review session;
   save reviewed truth transactionally (current lane = record update,
   legacy lane = review overlay sidecar; original legacy JSON untouched).
3. MAIN_PRESENTATION_BOUNDARY_GATE: raw settlementItems / evidence never cross
   into Main (currentMatch.settlement bounded; history projection bounded).
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import cv2

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
APP_DIR = os.path.join(PROJECT_ROOT, "app")
for p in (CORE_DIR, APP_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from evidence_storage import save_evidence_png
from legacy_archive import LegacyArchive, stable_legacy_key
from review_overlay import ReviewOverlayStore
from settlement_review import SettlementReviewService
from settlement_truth_holder import build_settlement_truth_evidence_v1


def _make_frame(text="SETTLEMENT PROOF"):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cv2.putText(frame, text, (200, 200), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 0), 3)
    return frame


def _persist_record_with_evidence(history_path, data_root, match_id="match_review_001"):
    store = CanonicalHistoryStore(history_path)
    record = build_canonical_match_record_v7(
        match_id=match_id,
        played_at="2026-08-17T14:12:00+08:00",
        lifecycle_status="FINALIZED",
        source="vision-auto-archiver",
        environment={"venue": "珊瑚场", "box": "琉璃宝箱", "fieldCondition": "standard"},
        public_intel={"q": 12},
        settlement={
            "status": "verified",
            "verified": True,
            "clearingPrice": 120000,
            "actualTotal": 200000,
            "realizedProfit": 75000,
            "acquired": True,
            "winner": "玩家本人",
            "settlementItems": [],
        },
    )
    store.persist_record_transactional(record, is_finalized=True)

    frame = _make_frame()
    rel_uri, digest = save_evidence_png(frame, match_id, subfolder="settlement", data_dir=data_root)
    truth_ev = build_settlement_truth_evidence_v1(
        match_id=match_id,
        actual_total=200000.0,
        settlement_observed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        truth_source="test_fixture",
        truth_confidence="medium",
        evidence_uri=rel_uri,
        evidence_sha256=digest,
    )
    store.update_record_transactional(match_id, {"settlement": {"truthEvidence": truth_ev}})
    return match_id, rel_uri, digest


class TestSettlementReviewV1(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.environ["YIHUAN_DATA_ROOT"] = self.root
        self.history_path = os.path.join(self.root, "history", "异环拍卖数据.json")
        # legacy source file
        self.legacy_path = os.path.join(self.root, "legacy_source", "异环拍卖数据.json")
        os.makedirs(os.path.dirname(self.legacy_path), exist_ok=True)
        legacy_doc = {
            "version": "v0.6",
            "records": [
                {"id": "legacy_match_001", "venue": "海贝场", "box": "破损的包裹",
                 "lifecycleStatus": "FINALIZED", "settlement": {"clearingPrice": 10000, "actualTotal": 20000}},
                {"playedAt": "2026-08-10T10:00:00", "venue": "珊瑚场", "settlement": {}},
            ],
        }
        with open(self.legacy_path, "w", encoding="utf-8") as f:
            json.dump(legacy_doc, f, ensure_ascii=False)
        with open(self.legacy_path, "rb") as _lf:
            self.legacy_raw_before = _lf.read()
        self.legacy_sha_before = hashlib.sha256(self.legacy_raw_before).hexdigest()

        self.overlay_path = os.path.join(self.root, "state", "settlement_review_overlays.json")
        self.store = CanonicalHistoryStore(self.history_path)
        self.legacy = LegacyArchive(path_provider=lambda: self.legacy_path)
        self.overlay = ReviewOverlayStore(self.overlay_path)
        self.service = SettlementReviewService(
            history_path_provider=lambda: self.history_path,
            data_root_provider=lambda: self.root,
            legacy_archive=self.legacy,
            overlay_store=self.overlay,
        )

    def tearDown(self):
        os.environ.pop("YIHUAN_DATA_ROOT", None)
        self.tmp.cleanup()

    # ----------------------------------------------------------------- gate 1
    def test_history_review_backend_gate(self):
        """Whitelisted review DTO: record + screenshot evidence + machine proposals."""
        match_id, rel_uri, digest = _persist_record_with_evidence(self.history_path, self.root)
        result = self.service.create_review_session(match_id)
        self.assertTrue(result["ok"])
        review = result["review"]
        self.assertEqual(review["recordId"], match_id)
        self.assertEqual(review["settlement"]["clearingPrice"], 120000)
        self.assertTrue(review["screenshot"]["available"])
        self.assertEqual(review["screenshot"]["uri"], rel_uri)
        self.assertEqual(review["screenshot"]["sha256"], digest)
        self.assertIsInstance(review["proposals"], list)
        for p in review["proposals"]:
            # whitelist only: no raw component internals beyond grid coordinates
            self.assertTrue(set(p.keys()) <= {
                "slotIndex", "rarity", "shape", "cells", "bbox", "status",
                "groupingAmbiguous", "partitionCandidates",
                "candidateItemIds", "candidatePrices", "score", "name", "exactItemId", "price",
            })
        self.assertIsInstance(review["reviewedItems"], list)

    # ----------------------------------------------------------------- gate 2
    def test_screenshot_import_reviewed_save_gate(self):
        """Import -> review session; save -> record.reviewedItems (current lane)."""
        match_id, _rel, _dig = _persist_record_with_evidence(self.history_path, self.root)
        png_path = os.path.join(self.root, "user_shot.png")
        cv2.imwrite(png_path, _make_frame("USER IMPORT"))

        imp = self.service.import_screenshot(match_id, png_path)
        self.assertTrue(imp["ok"], imp)
        review = imp["review"]
        self.assertIs(review["settlement"].get("acquired"), True)
        self.assertEqual(review["settlement"].get("winner"), "玩家本人")
        self.assertTrue(review["screenshot"]["available"])
        self.assertTrue(review["screenshot"]["uri"].startswith("evidence/settlement/import_"))
        with open(png_path, "rb") as _pf:
            self.assertEqual(review["screenshot"]["sha256"], hashlib.sha256(_pf.read()).hexdigest())
        self.assertIn("provenance", review)

        reviewed = [
            {"slotIndex": 1, "itemId": "万有星仪", "name": "万有星仪", "price": 150000,
             "rarity": "gold", "shape": "2x2", "cells": [[0, 0], [0, 1]], "bbox": [0, 0, 10, 10],
             "status": "confirmed", "groupingAmbiguous": False, "partitionCandidates": []},
        ]
        saved = self.service.save_reviewed_settlement(match_id, reviewed)
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["reviewedCount"], 1)

        store = CanonicalHistoryStore(self.history_path)
        rec = store.lookup(match_id)
        self.assertEqual(len(rec["settlement"]["reviewedItems"]), 1)
        self.assertEqual(rec["settlement"]["reviewedItems"][0]["itemId"], "万有星仪")
        # machine evidence preserved
        self.assertIn("truthEvidence", rec["settlement"])

    def test_legacy_lane_import_reviewed_save_gate(self):
        """Legacy lane: read-only archive + overlay save; original JSON untouched."""
        source_info = self.legacy.source_info()
        self.assertTrue(source_info["available"])
        self.assertEqual(source_info["recordCount"], 2)
        projections = self.legacy.list_projections()
        self.assertEqual(len(projections), 2)
        keys = [p["key"] for p in projections]
        self.assertIn("legacy:legacy_match_001", keys)
        # stable fingerprint key for record without id
        self.assertTrue(any(k.startswith("legacy:fp:") for k in keys))

        legacy_key = "legacy:legacy_match_001"
        session = self.service.create_review_session(legacy_key, source="legacy")
        self.assertTrue(session["ok"], session)
        self.assertEqual(session["review"]["source"], "legacy")
        self.assertEqual(session["review"]["settlement"]["clearingPrice"], 10000)

        # import + save reviewed truth -> overlay, NOT the original file
        png_path = os.path.join(self.root, "legacy_shot.png")
        cv2.imwrite(png_path, _make_frame("LEGACY IMPORT"))
        imp = self.service.import_screenshot(legacy_key, png_path, source="legacy")
        self.assertTrue(imp["ok"], imp)

        reviewed = [
            {"slotIndex": 1, "itemId": "未知", "name": None, "price": None,
             "rarity": "purple", "shape": "1x1", "cells": [[0, 0]], "bbox": [0, 0, 10, 10],
             "status": "unknown", "groupingAmbiguous": True, "partitionCandidates": ["1x1", "2x1"]},
        ]
        saved = self.service.save_reviewed_settlement(legacy_key, reviewed, source="legacy")
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["lane"], "legacy_overlay")

        overlay = self.overlay.get_overlay(self.legacy_sha_before, legacy_key)
        self.assertIsNotNone(overlay)
        self.assertEqual(len(overlay["reviewedItems"]), 1)
        self.assertEqual(overlay["source"]["fileSha256"], self.legacy_sha_before)

        # original legacy JSON byte-identical (never modified)
        with open(self.legacy_path, "rb") as _lf:
            self.assertEqual(_lf.read(), self.legacy_raw_before)

        # reopened session merges overlay reviewedItems
        session2 = self.service.create_review_session(legacy_key, source="legacy")
        self.assertEqual(len(session2["review"]["reviewedItems"]), 1)

    # ----------------------------------------------------------------- gate 3
    def test_main_presentation_boundary_gate(self):
        """Raw settlementItems / evidence never cross into Main."""
        from main import CURRENT_MATCH, get_current_match_presentation_summary

        CURRENT_MATCH.begin_next_match()
        CURRENT_MATCH.apply_facts({
            "venue": "珊瑚场", "box": "琉璃宝箱", "fieldCondition": "standard",
            "q": 12, "goldAvg": 74379, "purpleCount": 7,
            "clearingPrice": 120000, "actualTotal": 200000, "realizedProfit": 75000,
            "isAcquired": True,
            "settlementItems": [
                {"slotIndex": 1, "rarity": "gold", "status": "ambiguous",
                 "candidateItemIds": ["A", "B"], "candidatePrices": [1, 2], "cells": [[0, 0]]},
            ],
            "settlementTruthEvidence": {"schemaVersion": "settlement-truth-evidence.v1", "matchId": "x"},
        })
        summary = get_current_match_presentation_summary()
        st = summary["settlement"]
        self.assertNotIn("items", st)
        self.assertNotIn("evidence", st)
        for key in ("itemCount", "exactCount", "ambiguousCount", "unknownCount", "evidenceAvailable"):
            self.assertIn(key, st)
        self.assertTrue(st["evidenceAvailable"])

        # history projection: no raw settlementItems in Main payload
        from main_view_state import HistoryRecordProjection, MainViewStateProvider
        import tempfile as _tf
        with _tf.TemporaryDirectory() as td:
            db_path = os.path.join(td, "h.json")
            _persist_record_with_evidence(db_path, td)
            provider = MainViewStateProvider(db_path)
            snap = provider.snapshot()
            payload = snap.to_payload()
            rec = payload["history"]["recentRecords"][0]
            self.assertNotIn("settlementItems", rec["settlement"])
            self.assertIn("settlementItemCount", rec["settlement"])


    # ----------------------------------------------------------------- resolver
    def test_legacy_resolver_env_persisted_and_packaged(self):
        """Legacy source resolver: env override, persisted user source, packaged
        walk-up from sys.executable — never relies on cwd alone."""
        import legacy_archive as la
        from legacy_archive import _resolve_legacy_path
        from pathlib import Path as _P
        from unittest import mock

        # 1) env override
        env_file = os.path.join(self.root, "env_legacy.json")
        with open(env_file, "w", encoding="utf-8") as f:
            json.dump({"records": []}, f)
        with mock.patch.dict(os.environ, {"YIHUAN_LEGACY_HISTORY_PATH": env_file}, clear=False), \
             mock.patch.object(la, "_persisted_user_source", return_value=None):
            self.assertEqual(str(_resolve_legacy_path()), os.path.realpath(env_file))

        # 2) persisted user source has highest priority
        user_file = os.path.join(self.root, "user_selected.json")
        with open(user_file, "w", encoding="utf-8") as f:
            json.dump({"records": []}, f)
        with mock.patch.object(la, "_persisted_user_source", return_value=_P(user_file).resolve()):
            self.assertEqual(str(_resolve_legacy_path()), os.path.realpath(user_file))

        # 3) packaged dev build: walk up from sys.executable dir to repo root
        pkg_root = os.path.join(self.root, "pkg", "dist", "异环拍卖助手")
        os.makedirs(pkg_root, exist_ok=True)
        legacy_at_root = os.path.join(self.root, "pkg", "异环拍卖数据.json")
        with open(legacy_at_root, "w", encoding="utf-8") as f:
            json.dump({"records": []}, f)
        fake_exe = os.path.join(pkg_root, "异环拍卖助手.exe")
        with mock.patch.object(la, "_persisted_user_source", return_value=None), \
             mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(la.sys, "frozen", True, create=True), \
             mock.patch.object(la.sys, "executable", fake_exe):
            self.assertEqual(str(_resolve_legacy_path()), os.path.realpath(legacy_at_root))

    # --------------------------------------------------------------- routing
    def test_import_action_routing_gate(self):
        """Bridge routing: import_settlement_screenshot with a source path reaches
        the review service and returns a review session (not a silent no-op)."""
        from main_window import MainWindowBridge

        match_id, _rel, _dig = _persist_record_with_evidence(self.history_path, self.root)
        png_path = os.path.join(self.root, "route.png")
        cv2.imwrite(png_path, _make_frame("ROUTE"))

        class DummyOverlay:
            visible = False

        bridge = MainWindowBridge(DummyOverlay(), settlement_review_service=self.service)
        resp = bridge.dispatch(json.dumps({
            "action": "import_settlement_screenshot",
            "recordId": match_id,
            "sourcePath": png_path,
        }))
        self.assertTrue(resp["settlementReview"]["ok"], resp["settlementReview"])
        self.assertTrue(resp["settlementReview"]["review"]["screenshot"]["available"])
        # whitelisted proposal fields only
        for p in resp["settlementReview"]["review"]["proposals"]:
            self.assertTrue(set(p.keys()) <= {
                "slotIndex", "rarity", "shape", "cells", "bbox", "status",
                "groupingAmbiguous", "partitionCandidates",
                "candidateItemIds", "candidatePrices", "score", "name", "exactItemId", "price",
            })


    # --------------------------------------------------------------- provenance
    def test_legacy_screenshot_provenance_gate(self):
        """Legacy records with embedded settlement screenshot thumbnails are exposed:
        1. main-settlement thumbnail -> screenshotAvailable=True
        2. warehouse-supplement-only -> screenshotAvailable=False
        3. no thumbnail -> screenshotAvailable=False
        4. Settlement Review DTO does not fallback to warehouse-supplement."""
        import base64 as _b64
        tiny_png = _b64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        data_url = "data:image/jpeg;base64," + _b64.b64encode(tiny_png).decode("ascii")
        legacy_doc = {
            "records": [
                {"id": "legacy_shot_001", "venue": "珊瑚场", "settlement": {"clearingPrice": 50000, "actualTotal": 80000},
                 "screenshots": [{"id": "shot_1", "name": "SnowShot_1.png", "path": "SnowShot_1.png", "thumbnailDataUrl": data_url, "kind": "settlement", "segmentRole": "main-settlement"}]},
                {"id": "legacy_warehouse_only_002", "venue": "海贝场", "settlement": {"clearingPrice": 30000},
                 "screenshots": [{"id": "shot_2", "name": "SnowShot_2.png", "path": "SnowShot_2.png", "thumbnailDataUrl": data_url, "kind": "settlement", "segmentRole": "warehouse-supplement"}]},
                {"id": "legacy_no_shot_003", "venue": "黄金场", "settlement": {}},
            ],
        }
        with open(self.legacy_path, "w", encoding="utf-8") as f:
            json.dump(legacy_doc, f, ensure_ascii=False)
        with open(self.legacy_path, "rb") as _lf:
            self.legacy_raw_before = _lf.read()
        self.legacy_sha_before = hashlib.sha256(self.legacy_raw_before).hexdigest()

        projections = self.legacy.list_projections()
        by_key = {p["key"]: p for p in projections}
        self.assertTrue(by_key["legacy:legacy_shot_001"]["screenshotAvailable"])
        self.assertFalse(by_key["legacy:legacy_warehouse_only_002"]["screenshotAvailable"])
        self.assertFalse(by_key["legacy:legacy_no_shot_003"]["screenshotAvailable"])

        # 1. Main settlement screenshot embedded
        embedded1 = self.legacy.embedded_screenshot(legacy_doc["records"][0])
        self.assertIsNotNone(embedded1)
        self.assertEqual(embedded1["source"], "legacy_embedded_thumbnail")
        self.assertEqual(len(embedded1["sha256"]), 64)
        self.assertEqual(embedded1["dataUrl"], data_url)
        self.assertEqual(embedded1["segmentRole"], "main-settlement")

        # 2. Warehouse supplement only -> returns None
        embedded2 = self.legacy.embedded_screenshot(legacy_doc["records"][1])
        self.assertIsNone(embedded2)

        # 3. No screenshot -> returns None
        embedded3 = self.legacy.embedded_screenshot(legacy_doc["records"][2])
        self.assertIsNone(embedded3)

        # 4. Review session provenance
        session1 = self.service.create_review_session("legacy:legacy_shot_001", source="legacy")
        self.assertTrue(session1["ok"], session1)
        self.assertTrue(session1["review"]["screenshot"]["available"])
        self.assertEqual(session1["review"]["screenshot"]["source"], "legacy_embedded_thumbnail")
        self.assertEqual(session1["review"]["screenshot"]["sha256"], embedded1["sha256"])

        # Warehouse supplement only: not available for settlement review
        session2 = self.service.create_review_session("legacy:legacy_warehouse_only_002", source="legacy")
        self.assertTrue(session2["ok"])
        self.assertFalse(session2["review"]["screenshot"]["available"])

        # No screenshot: not available
        session3 = self.service.create_review_session("legacy:legacy_no_shot_003", source="legacy")
        self.assertTrue(session3["ok"])
        self.assertFalse(session3["review"]["screenshot"]["available"])

    def test_projection_evidence_filter_fields_gate(self):
        """Projection exposes bounded evidence/review fields for filters."""
        from main_view_state import MainViewStateProvider
        match_id, rel_uri, digest = _persist_record_with_evidence(self.history_path, self.root)
        provider = MainViewStateProvider(self.history_path)
        payload = provider.snapshot().to_payload()
        rec = payload["history"]["recentRecords"][0]
        self.assertEqual(rec["id"], match_id)
        self.assertTrue(rec["settlement"]["settlementEvidenceAvailable"])
        self.assertFalse(rec["settlement"]["settlementReviewed"])
        # bounded: no raw items/evidence in the payload
        self.assertNotIn("settlementItems", rec["settlement"])
        self.assertNotIn("truthEvidence", rec["settlement"])

    def test_screenshot_delete_and_replace_lifecycle_gate(self):
        """Screenshot import -> replace -> delete lifecycle preserves boundaries."""
        # 1. Current Lane: import screenshot
        match_id, _, _ = _persist_record_with_evidence(self.history_path, self.root, match_id="match_lifecycle_001")
        img1 = _make_frame("SHOT 1")
        shot1_path = os.path.join(self.root, "shot1.png")
        cv2.imwrite(shot1_path, img1)
        res1 = self.service.import_screenshot(match_id, shot1_path, source="current")
        self.assertTrue(res1["ok"])
        self.assertTrue(res1["review"]["screenshot"]["available"])
        sha1 = res1["review"]["screenshot"]["sha256"]

        # 2. Replace screenshot
        img2 = _make_frame("SHOT 2 REPLACED")
        shot2_path = os.path.join(self.root, "shot2.png")
        cv2.imwrite(shot2_path, img2)
        res2 = self.service.import_screenshot(match_id, shot2_path, source="current")
        self.assertTrue(res2["ok"])
        self.assertTrue(res2["review"]["screenshot"]["available"])
        sha2 = res2["review"]["screenshot"]["sha256"]
        self.assertNotEqual(sha1, sha2)

        # 3. Delete screenshot: clears evidence, keeps record intact
        del_res = self.service.delete_imported_screenshot(match_id, source="current")
        self.assertTrue(del_res["ok"])
        # Removing imports must reveal the original captured evidence again.
        self.assertTrue(del_res["review"]["screenshot"]["available"])
        self.assertNotEqual(del_res["review"]["screenshot"]["sha256"], sha1)
        # Record still exists
        rec_after = self.store.lookup(match_id)
        self.assertIsNotNone(rec_after)
        self.assertEqual(rec_after["id"], match_id)

        # 4. Legacy Lane: import screenshot -> overlay created -> delete -> falls back to embedded thumbnail
        import base64 as _b64
        tiny_png = _b64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        data_url = "data:image/jpeg;base64," + _b64.b64encode(tiny_png).decode("ascii")
        legacy_doc = {
            "records": [
                {"id": "legacy_life_001", "venue": "珊瑚场", "settlement": {"clearingPrice": 50000},
                 "screenshots": [{"id": "shot_x", "name": "SnowShot_x.png", "thumbnailDataUrl": data_url, "kind": "settlement", "segmentRole": "main-settlement"}]},
            ],
        }
        with open(self.legacy_path, "w", encoding="utf-8") as f:
            json.dump(legacy_doc, f, ensure_ascii=False)

        leg_key = "legacy:legacy_life_001"
        # User imports custom screenshot for legacy record
        res_leg_imp = self.service.import_screenshot(leg_key, shot1_path, source="legacy")
        self.assertTrue(res_leg_imp["ok"])
        self.assertIn(res_leg_imp["review"]["provenance"]["source"], ("manual history backfill", "user_import"))

        # User saves review overlay
        self.service.save_reviewed_settlement(leg_key, [{"slotIndex": 1, "status": "confirmed", "name": "测试藏品"}], source="legacy")

        # Delete imported screenshot from legacy overlay: falls back to embedded thumbnail
        res_leg_del = self.service.delete_imported_screenshot(leg_key, source="legacy")
        self.assertTrue(res_leg_del["ok"])
        self.assertTrue(res_leg_del["review"]["screenshot"]["available"])
        self.assertEqual(res_leg_del["review"]["screenshot"]["source"], "legacy_embedded_thumbnail")
        # Legacy JSON untouched
        self.assertTrue(os.path.exists(self.legacy_path))

    def test_legacy_record_delete_lifecycle_gate(self):
        """Deleting a legacy record removes it from legacy archive and creates a backup."""
        legacy_doc = {
            "records": [
                {"id": "leg_del_001", "venue": "珊瑚场", "settlement": {"clearingPrice": 50000}},
                {"id": "leg_del_002", "venue": "黄金场", "settlement": {"clearingPrice": 80000}},
            ],
        }
        with open(self.legacy_path, "w", encoding="utf-8") as f:
            json.dump(legacy_doc, f, ensure_ascii=False)

        res = self.legacy.delete_record("legacy:leg_del_001")
        self.assertTrue(res["ok"])
        self.assertEqual(res["remainingCount"], 1)

        projections = self.legacy.list_projections()
        self.assertEqual(len(projections), 1)
        self.assertEqual(projections[0]["id"], "leg_del_002")


    def test_attach_and_replace_screenshot_never_creates_duplicate_match(self):
        """Attaching or replacing screenshot for existing record preserves count and never creates duplicate records."""
        match_id, _, _ = _persist_record_with_evidence(self.history_path, self.root, match_id="match_no_dupe_001")
        initial_records = self.store.read_database().get("records", [])
        self.assertEqual(len(initial_records), 1)

        # 1. Attach screenshot
        shot1_path = os.path.join(self.root, "shot_att.png")
        cv2.imwrite(shot1_path, _make_frame("ATTACH"))
        res_attach = self.service.import_screenshot(match_id, shot1_path, source="current")
        self.assertTrue(res_attach["ok"])
        self.assertEqual(res_attach["review"]["recordId"], match_id)

        # Record count must still be 1 (no new record created during import)
        self.assertEqual(len(self.store.read_database().get("records", [])), 1)

        # 2. Save review with screenshot metadata
        reviewed = [
            {"slotIndex": 1, "itemId": "黄金罗盘", "name": "黄金罗盘", "price": 88000,
             "rarity": "gold", "shape": "2x2", "cells": [[0, 0], [0, 1]], "bbox": [0, 0, 10, 10],
             "status": "confirmed", "groupingAmbiguous": False, "partitionCandidates": []}
        ]
        meta = {
            "screenshotUri": res_attach["review"]["screenshot"]["uri"],
            "screenshotSha256": res_attach["review"]["screenshot"]["sha256"],
            "provenance": res_attach["review"].get("provenance"),
        }
        res_save = self.service.save_reviewed_settlement(match_id, reviewed, review_meta=meta, source="current")
        self.assertTrue(res_save["ok"])

        # Record count is still strictly 1
        records_after_save = self.store.read_database().get("records", [])
        self.assertEqual(len(records_after_save), 1)
        rec = records_after_save[0]
        self.assertEqual(rec["id"], match_id)
        self.assertEqual(len(rec["settlement"]["reviewedItems"]), 1)
        self.assertEqual(rec["settlement"]["truthEvidence"]["evidenceReferences"][0]["sha256"], res_attach["review"]["screenshot"]["sha256"])

        # 3. Replace screenshot on existing record
        shot2_path = os.path.join(self.root, "shot_rep.png")
        cv2.imwrite(shot2_path, _make_frame("REPLACE"))
        res_replace = self.service.import_screenshot(match_id, shot2_path, source="current")
        self.assertTrue(res_replace["ok"])
        self.assertEqual(res_replace["review"]["recordId"], match_id)
        self.assertEqual(len(self.store.read_database().get("records", [])), 1)

    def test_item_by_item_manual_correction_and_unknown_writeback(self):
        """Item-by-item manual corrections (custom name/price), candidate selections, and unknowns save cleanly."""
        match_id, _, _ = _persist_record_with_evidence(self.history_path, self.root, match_id="match_correction_001")
        reviewed = [
            # Item 1: confirmed machine candidate
            {"slotIndex": 1, "itemId": "万有星仪", "name": "万有星仪", "price": 150000,
             "rarity": "gold", "shape": "2x2", "cells": [[0, 0]], "bbox": [0, 0, 10, 10],
             "status": "confirmed", "groupingAmbiguous": False, "partitionCandidates": []},
            # Item 2: manual correction override (custom user item and price)
            {"slotIndex": 2, "itemId": "古代机械核心", "name": "古代机械核心", "price": 99000,
             "rarity": "purple", "shape": "2x1", "cells": [[1, 0], [1, 1]], "bbox": [10, 0, 20, 10],
             "status": "confirmed", "isManualCorrection": True, "groupingAmbiguous": False, "partitionCandidates": []},
            # Item 3: marked as unknown
            {"slotIndex": 3, "itemId": None, "name": None, "price": None,
             "rarity": "blue", "shape": "1x1", "cells": [[2, 0]], "bbox": [20, 0, 30, 10],
             "status": "unknown", "groupingAmbiguous": True, "partitionCandidates": ["1x1"]},
        ]
        saved = self.service.save_reviewed_settlement(match_id, reviewed, source="current")
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["reviewedCount"], 3)

        rec = self.store.lookup(match_id)
        items = rec["settlement"]["reviewedItems"]
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["status"], "confirmed")
        self.assertEqual(items[1]["isManualCorrection"], True)
        self.assertEqual(items[1]["name"], "古代机械核心")
        self.assertEqual(items[1]["price"], 99000)
    def test_history_settlement_item_review_surface_grouping_identity_evidence(self):
        """
        Verify Minimal History Settlement Item Review Surface (4D2D1M-C3.5A):
        1. History record with settlement evidence can load grouping hypotheses and identity evidences.
        2. Real evidence metadata is displayed (groupingHypothesisId, rarity, gridShape, bbox, identityStatus, candidates, cropDataUrl).
        3. Ambiguous item requires explicit candidate selection and succeeds on valid candidate.
        4. Catalog override succeeds on valid catalog item and rejects invalid catalogId.
        5. No user submission -> No reviewed truth generated.
        6. Persisted truth uses existing C3.4A bridge and store.
        7. Saved review updates presentation state.
        8. Zero writes to canonical business records, knownItems, Solver, CurrentMatch.
        """
        from settlement_evidence_store_v2 import KIND_MAIN, SettlementEvidenceStoreV2
        from settlement_human_review import (
            ACTION_CONFIRM_CANDIDATE,
            ACTION_CONFIRM_OVERRIDE,
            load_settlement_reviewed_truth,
        )

        match_id = "match_c35a_review_001"
        v2_store = SettlementEvidenceStoreV2(self.root)

        # Prepare a fixture frame and save to v2 evidence store as MAIN_ORIGINAL
        fixture_path = (
            os.path.join(PROJECT_ROOT, "tests", "fixtures", "real_snapshots_4d2d1j", "fixture_settlement_client_sanitized.png")
        )
        img = cv2.imread(fixture_path)
        self.assertIsNotNone(img)
        _, png_bytes = cv2.imencode(".png", img)
        main_desc = v2_store.save_original(
            record_stable_key=match_id,
            kind=KIND_MAIN,
            image_bytes=png_bytes.tobytes(),
        )

        # Also persist a basic canonical record (business data)
        store = CanonicalHistoryStore(self.history_path)
        record = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-30T10:00:00+08:00",
            lifecycle_status="FINALIZED",
            source="vision-auto-archiver",
            environment={"venue": "珊瑚场", "box": "琉璃宝箱", "fieldCondition": "standard"},
            public_intel={"q": 12},
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 600000,
                "actualTotal": 785974,
                "realizedProfit": 185974,
                "acquired": True,
                "winner": "玩家本人",
                "settlementItems": [],
            },
        )
        store.persist_record_transactional(record, is_finalized=True)

        # 1 & 5. Initial load: no user action -> 0 reviewed truth
        initial_reviews = load_settlement_reviewed_truth(v2_store, match_id)
        self.assertEqual(initial_reviews, [])

        session = self.service.create_review_session(match_id, source="current")
        self.assertTrue(session["ok"])
        review_dto = session["review"]

        # 2. Verify UI receives real grouping hypotheses and identity evidence
        grouping_hyps = review_dto.get("groupingHypotheses") or []
        identity_evs = review_dto.get("identityEvidence") or []
        self.assertGreater(len(grouping_hyps), 0)
        self.assertGreater(len(identity_evs), 0)
        self.assertEqual(review_dto["settlement"]["reviewed"], False)

        first_ev = identity_evs[0]
        self.assertIn("groupingHypothesisId", first_ev)
        self.assertIn("rarity", first_ev)
        self.assertIn("gridShape", first_ev)
        self.assertIn("bbox", first_ev)
        self.assertIn("identityStatus", first_ev)
        self.assertIn("cropDataUrl", first_ev)

        # Find ambiguous hypothesis in identity evidences
        amb_ev = next((ev for ev in identity_evs if ev["identityStatus"] == "AMBIGUOUS_CANDIDATES"), None)
        self.assertIsNotNone(amb_ev)
        amb_hyp_id = amb_ev["groupingHypothesisId"]
        self.assertGreater(len(amb_ev["candidateCatalogIds"]), 1)

        # 3. CONFIRM_CANDIDATE on ambiguous without candidate selection -> FAILS
        fail_res = self.service.apply_item_review_action(
            match_id,
            {
                "groupingHypothesisId": amb_hyp_id,
                "action": ACTION_CONFIRM_CANDIDATE,
            },
        )
        self.assertFalse(fail_res["ok"])
        self.assertEqual(fail_res["status"], "SELECTED_CATALOG_ID_REQUIRED")

        # CONFIRM_CANDIDATE on ambiguous with valid candidate -> SUCCEEDS
        chosen_cat_id = amb_ev["candidateCatalogIds"][0]
        confirm_res = self.service.apply_item_review_action(
            match_id,
            {
                "groupingHypothesisId": amb_hyp_id,
                "action": ACTION_CONFIRM_CANDIDATE,
                "selectedCatalogId": chosen_cat_id,
            },
        )
        self.assertTrue(confirm_res["ok"])
        self.assertEqual(confirm_res["reviewedItem"]["selectedCatalogId"], chosen_cat_id)
        self.assertEqual(confirm_res["reviewedCount"], 1)

        # 4. CONFIRM_CATALOG_OVERRIDE with invalid catalogId -> FAILS
        other_ev = identity_evs[1]
        other_hyp_id = other_ev["groupingHypothesisId"]
        override_fail = self.service.apply_item_review_action(
            match_id,
            {
                "groupingHypothesisId": other_hyp_id,
                "action": ACTION_CONFIRM_OVERRIDE,
                "selectedCatalogId": "non_existent_fake_override_9999",
            },
        )
        self.assertFalse(override_fail["ok"])
        self.assertEqual(override_fail["status"], "INVALID_OVERRIDE_CATALOG_ID")

        # CONFIRM_CATALOG_OVERRIDE with valid catalogId -> SUCCEEDS
        override_ok = self.service.apply_item_review_action(
            match_id,
            {
                "groupingHypothesisId": other_hyp_id,
                "action": ACTION_CONFIRM_OVERRIDE,
                "selectedCatalogId": "image1-0-1",
                "overrideReason": "HUMAN_OVERRIDE",
            },
        )
        self.assertTrue(override_ok["ok"])
        self.assertEqual(override_ok["reviewedItem"]["selectedCatalogId"], "image1-0-1")
        self.assertEqual(override_ok["reviewedCount"], 2)

        # 6 & 7. Verify updated reviewed presentation state reloaded
        session_updated = self.service.create_review_session(match_id, source="current")
        self.assertTrue(session_updated["ok"])
        updated_dto = session_updated["review"]
        self.assertEqual(updated_dto["settlement"]["reviewed"], True)
        self.assertEqual(len(updated_dto["reviewedItems"]), 2)

        # 8. Verify canonical business record untouched & no knownItems written
        rec_after = store.lookup(match_id)
        self.assertEqual(rec_after["settlement"]["clearingPrice"], 600000)
        self.assertEqual(rec_after["settlement"]["actualTotal"], 785974)
        self.assertFalse(os.path.exists(os.path.join(self.root, "known_items.json")))

    def test_history_settlement_screenshot_backfill_evidence_store_v2(self):
        """
        Verify History Settlement Screenshot Import / Backfill (4D2D1M-C3.5B):
        1. Explicitly select screenshot for an existing History record;
        2. File-backed evidence saved into Evidence Store v2;
        3. Correctly binds recordStableKey, evidenceId, SHA-256, width/height, mimeType, kind, capturedAt;
        4. Coverage remains PARTIAL / COVERAGE_UNPROVEN;
        5. Zero recognition / zero grouping / zero identity / zero automatic review triggered;
        6. History business data, knownItems, Solver, CurrentMatch remain untouched.
        """
        from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
        from settlement_human_review import load_settlement_reviewed_truth

        match_id = "match_c35b_backfill_001"
        store = CanonicalHistoryStore(self.history_path)
        record = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-30T11:00:00+08:00",
            lifecycle_status="FINALIZED",
            source="vision-auto-archiver",
            environment={"venue": "珊瑚场", "box": "琉璃宝箱", "fieldCondition": "standard"},
            public_intel={"q": 12},
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 550000,
                "actualTotal": 820000,
                "realizedProfit": 270000,
                "acquired": True,
                "winner": "玩家本人",
                "settlementItems": [],
            },
        )
        store.persist_record_transactional(record, is_finalized=True)

        shot_path = os.path.join(self.root, "manual_backfill_shot.png")
        frame = _make_frame("BACKFILL MANUAL SHOT")
        cv2.imwrite(shot_path, frame)
        raw_bytes = Path(shot_path).read_bytes()
        expected_sha = hashlib.sha256(raw_bytes).hexdigest()

        # 1. Backfill / Import screenshot
        res = self.service.import_screenshot(match_id, shot_path, source="current")
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "EVIDENCE_BACKFILLED")
        self.assertEqual(res["recordId"], match_id)

        # 2 & 3. Verify file-backed persistence in Evidence Store v2
        v2_store = SettlementEvidenceStoreV2(self.root)
        evidences = v2_store.list_record_evidence(match_id)
        self.assertEqual(len(evidences), 1)
        desc = evidences[0]
        self.assertEqual(desc["recordStableKey"], match_id)
        self.assertTrue(desc["evidenceId"].startswith(f"sev2_{match_id}_"))
        self.assertEqual(desc["sha256"], expected_sha)
        self.assertEqual(desc["width"], 1920)
        self.assertEqual(desc["height"], 1080)
        self.assertEqual(desc["kind"], "main-settlement")
        self.assertEqual(desc["storageMode"], "file")

        # Verify blob on disk is immutable and exact
        blob_path = v2_store.root / desc["relativePath"]
        self.assertTrue(blob_path.is_file())
        self.assertEqual(blob_path.read_bytes(), raw_bytes)

        # 4. Coverage remains PARTIAL / COVERAGE_UNPROVEN
        self.assertEqual(desc["coverageStatus"], "COVERAGE_UNPROVEN")
        self.assertEqual(desc["coverageMode"], "viewport-segment")
        self.assertEqual(res["review"]["screenshot"]["warehouseCoverage"], "PARTIAL")
        self.assertEqual(res["review"]["screenshot"]["coverageStatus"], "COVERAGE_UNPROVEN")
        self.assertEqual(res["provenance"]["warehouseCoverage"], "PARTIAL")
        self.assertEqual(res["provenance"]["coverageStatus"], "COVERAGE_UNPROVEN")

        # 5. Zero recognition / zero grouping / zero identity / zero automatic review
        self.assertEqual(res["review"]["proposals"], [])
        self.assertEqual(res["review"]["groupingHypotheses"], [])
        self.assertEqual(res["review"]["identityEvidence"], [])
        self.assertEqual(res["review"]["reviewedItems"], [])
        self.assertEqual(load_settlement_reviewed_truth(v2_store, match_id), [])

        # 6. Canonical business records, knownItems, Solver, CurrentMatch untouched
        rec_after = store.lookup(match_id)
        self.assertEqual(rec_after["settlement"]["clearingPrice"], 550000)
        self.assertEqual(rec_after["settlement"]["actualTotal"], 820000)
        self.assertEqual(rec_after["settlement"]["realizedProfit"], 270000)
        self.assertFalse(os.path.exists(os.path.join(self.root, "known_items.json")))

    def test_explicit_rerecognition_from_stored_screenshot(self):
        """
        Verify Explicit Re-recognition for Imported Settlement Screenshot (4D2D1M-C3.5C):
        1. Cannot rerun recognition when no raw screenshot exists -> NO_SCREENSHOT_EVIDENCE.
        2. Recognition runs ONLY on explicit user trigger (import itself does NOT run recognition).
        3. Reuses existing recognizer -> grouping hypotheses -> identity resolver pipeline.
        4. Derived grouping / identity evidence binds parent raw evidence ID, parent SHA, recordStableKey, bbox, cells, cropDataUrl.
        5. UNIQUE_IN_CATALOG / EXACT_IDENTIFIED do NOT automatically become reviewed truth.
        6. Existing reviewed truth is not modified, overwritten, or remapped.
        7. Coverage strictly remains PARTIAL / COVERAGE_UNPROVEN.
        8. History business data, knownItems, Solver, CurrentMatch remain unchanged.
        """
        from settlement_evidence_store_v2 import KIND_MAIN, SettlementEvidenceStoreV2
        from settlement_human_review import (
            ACTION_CONFIRM_CANDIDATE,
            load_settlement_reviewed_truth,
        )

        match_id = "match_c35c_rerecog_001"
        store = CanonicalHistoryStore(self.history_path)
        record = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-30T12:00:00+08:00",
            lifecycle_status="FINALIZED",
            source="vision-auto-archiver",
            environment={"venue": "珊瑚场", "box": "琉璃宝箱", "fieldCondition": "standard"},
            public_intel={"q": 12},
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 700000,
                "actualTotal": 950000,
                "realizedProfit": 250000,
                "acquired": True,
                "winner": "玩家本人",
                "settlementItems": [],
            },
        )
        store.persist_record_transactional(record, is_finalized=True)

        # 1. Without screenshot: rerun_recognition fails with NO_SCREENSHOT_EVIDENCE
        fail_res = self.service.rerun_recognition(match_id, source="current")
        self.assertFalse(fail_res["ok"])
        self.assertEqual(fail_res["status"], "NO_SCREENSHOT_EVIDENCE")

        # 2. Backfill a real fixture screenshot
        fixture_path = os.path.join(
            PROJECT_ROOT,
            "tests",
            "fixtures",
            "real_snapshots_4d2d1j",
            "fixture_settlement_client_sanitized.png",
        )
        import_res = self.service.import_screenshot(match_id, fixture_path, source="current")
        self.assertTrue(import_res["ok"])
        # Import itself does NOT trigger recognition
        self.assertEqual(import_res["review"]["groupingHypotheses"], [])
        self.assertEqual(import_res["review"]["identityEvidence"], [])

        # 3. Explicit user trigger: rerun_recognition
        recog_res = self.service.rerun_recognition(match_id, source="current")
        self.assertTrue(recog_res["ok"])
        self.assertEqual(recog_res["status"], "RERECOGNITION_COMPLETED")

        review_dto = recog_res["review"]
        grouping_hyps = review_dto["groupingHypotheses"]
        identity_evs = review_dto["identityEvidence"]
        self.assertGreater(len(grouping_hyps), 0)
        self.assertGreater(len(identity_evs), 0)

        # 4. Verify parent evidence provenance binding
        v2_store = SettlementEvidenceStoreV2(self.root)
        evidences = v2_store.list_record_evidence(match_id)
        main_desc = next((d for d in evidences if d.get("kind") == KIND_MAIN), None)
        self.assertIsNotNone(main_desc)

        for ev in identity_evs:
            self.assertEqual(ev["recordStableKey"], match_id)
            self.assertEqual(ev["parentEvidenceId"], main_desc["evidenceId"])
            self.assertEqual(ev["parentSha256"], main_desc["sha256"])
            self.assertIn("cropDataUrl", ev)
            self.assertIn("bbox", ev)
            self.assertIn("cells", ev)
            self.assertIn("groupingHypothesisId", ev)

        # 5. UNIQUE_IN_CATALOG / EXACT_IDENTIFIED do not automatically become reviewed truth
        initial_reviewed_truth = load_settlement_reviewed_truth(v2_store, match_id)
        self.assertEqual(initial_reviewed_truth, [])
        self.assertEqual(review_dto["settlement"]["reviewed"], False)

        # Perform 1 manual review action
        first_ev = identity_evs[0]
        hyp_id = first_ev["groupingHypothesisId"]
        cat_id = first_ev["candidateCatalogIds"][0]
        confirm_res = self.service.apply_item_review_action(
            match_id,
            {
                "groupingHypothesisId": hyp_id,
                "action": ACTION_CONFIRM_CANDIDATE,
                "selectedCatalogId": cat_id,
            },
        )
        self.assertTrue(confirm_res["ok"])
        self.assertEqual(confirm_res["reviewedCount"], 1)

        # 6. Rerun recognition again: existing reviewed truth is preserved and NOT overwritten
        rerun_res2 = self.service.rerun_recognition(match_id, source="current")
        self.assertTrue(rerun_res2["ok"])
        reviewed_after_rerun = rerun_res2["review"]["reviewedItems"]
        self.assertEqual(len(reviewed_after_rerun), 1)
        self.assertEqual(reviewed_after_rerun[0]["selectedCatalogId"], cat_id)

        # 7. Coverage remains PARTIAL / COVERAGE_UNPROVEN
        self.assertEqual(rerun_res2["review"]["screenshot"]["warehouseCoverage"], "PARTIAL")
        self.assertEqual(rerun_res2["review"]["screenshot"]["coverageStatus"], "COVERAGE_UNPROVEN")

        # 8. Canonical business data, knownItems, Solver, CurrentMatch untouched
        rec_after = store.lookup(match_id)
        self.assertEqual(rec_after["settlement"]["clearingPrice"], 700000)
        self.assertEqual(rec_after["settlement"]["actualTotal"], 950000)
        self.assertEqual(rec_after["settlement"]["realizedProfit"], 250000)
        self.assertFalse(os.path.exists(os.path.join(self.root, "known_items.json")))


if __name__ == "__main__":
    unittest.main()
