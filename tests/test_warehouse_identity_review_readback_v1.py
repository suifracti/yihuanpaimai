"""Readback of persisted warehouse identity review into a closed summary."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from main_window import MainWindowBridge, OverlayVisibilityController
from runtime_data import DATA_ROOT_OVERRIDE_ENV, runtime_data_paths
from settlement_truth_evidence_contract import ORIGINAL_V2
from warehouse_capture_session import PRODUCTION_SCROLL_DRIVER_ENABLED, get_production_scroll_driver
from warehouse_catalog_geometry import CatalogGeometryIndex
from warehouse_coverage_ledger import REASON_COMPLETE, WarehouseCoverageLedger
from warehouse_identity_review import ACTION_CONFIRM, ACTION_DEFER, CatalogAuthority, resolve_warehouse_identity_review
from warehouse_identity_review_persist import SUMMARY_KEYS, persist_warehouse_identity_review, summarize_persisted_identity_review
from warehouse_identity_review_session import WarehouseIdentityReviewSession
from warehouse_review_packet import build_warehouse_review_packet, source_fingerprint_for

SHOT_DIR = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_identity_review_readback_v1"
CATALOG = [{
    "Id": "catRect", "Name": "RectBox", "Quality": "金",
    "Width": 2, "Height": 2, "Cells": 4, "Shape": "1100011000000000000000000",
}]


class _FakeOverlay:
    def __init__(self):
        self.Visible = True
        self.WebView = object()

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class _FakeReviewService:
    def create_review_session(self, record_id, source="current"):
        return {
            "ok": True,
            "review": {
                "recordId": record_id,
                "source": source,
                "settlement": {"clearingPrice": 1, "actualTotal": 2, "realizedProfit": 0},
                "screenshot": {"available": False, "uri": None, "sha256": None, "dataUrl": None},
                "proposals": [],
                "reviewedItems": [],
            },
        }


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _packet(key="recWirRead01"):
    ledger = WarehouseCoverageLedger(key)
    top = {
        "schemaVersion": ORIGINAL_V2, "evidenceId": "ev-top", "recordStableKey": key,
        "kind": "warehouse-segment", "capturedAt": "2026-08-25T12:00:00Z", "storageMode": "file",
        "relativePath": f"evidence/settlement_v2/blobs/aa/{_digest('aa')}.png",
        "sha256": _digest("aa"), "byteSize": 1024, "mimeType": "image/png", "width": 640, "height": 720,
        "coverageMode": "viewport-segment", "coverageStatus": "PARTIAL",
    }
    mid = dict(top, evidenceId="ev-mid", sha256=_digest("bb"), relativePath=f"evidence/settlement_v2/blobs/bb/{_digest('bb')}.png")
    bot = dict(top, evidenceId="ev-bot", sha256=_digest("cc"), relativePath=f"evidence/settlement_v2/blobs/cc/{_digest('cc')}.png")
    ledger.add_segment(top, sequence_index=0, top_proof={"trusted": True, "proofId": "t"})
    ledger.add_segment(mid, sequence_index=1, overlap_proof={"trusted": True, "aligned": True, "proofId": "o1", "previousEvidenceId": "ev-top"})
    ledger.add_segment(bot, sequence_index=2, bottom_proof={"trusted": True, "proofId": "b"}, overlap_proof={"trusted": True, "aligned": True, "proofId": "o2", "previousEvidenceId": "ev-mid"})
    candidates = [{"catalogId": "catRect", "name": "RectBox", "identityStatus": "CANDIDATE_ONLY",
                   "geometry": {"width": 2, "height": 2, "cells": 4, "shape": "1100011000000000000000000"},
                   "matchReasons": ["EXACT_CELL_MASK"]}]
    physical = {
        "schemaVersion": "warehouse-physical-ledger.v1", "recordStableKey": key, "chainStatus": "ACTIVE",
        "segments": [
            {"segmentId": "seg0", "sequenceIndex": 0, "originY": 0.0, "scrollState": "TOP", "chainId": 0},
            {"segmentId": "seg1", "sequenceIndex": 1, "originY": 90.0, "scrollState": "MIDDLE", "chainId": 0},
            {"segmentId": "seg2", "sequenceIndex": 2, "originY": 210.0, "scrollState": "BOTTOM", "chainId": 0},
        ],
        "tracks": [{
            "trackId": "track-a", "status": "OBSERVED", "clipped": False, "reasons": [],
            "widthCandidates": [2], "heightCandidates": [2], "spanCandidates": [4],
            "globalCellMaskCandidates": [{"cellMask": [[1, 1], [1, 1]]}], "candidates": candidates,
            "observations": [
                {"observationId": "obs-a0", "segmentId": "seg0", "sequenceIndex": 0, "localBox": [4.0, 6.0, 40.0, 50.0], "status": "OBSERVED"},
            ],
        }],
        "conflicts": [],
    }
    packet = build_warehouse_review_packet(
        coverage_ledger=ledger.finalize(REASON_COMPLETE),
        physical_ledger=physical,
        descriptors=[top, mid, bot],
        catalog_index=CatalogGeometryIndex(CATALOG),
    )
    packet["tracks"][0]["candidates"] = candidates
    packet["tracks"][0]["bestObservationId"] = "obs-a0"
    packet["sourceFingerprint"] = source_fingerprint_for(packet)
    return packet


def _seed(history, match_id, **settlement_extra):
    settlement = {
        "status": "verified", "verified": True, "clearingPrice": 100000,
        "actualTotal": 200000, "realizedProfit": 50000, "acquired": True,
        "winner": "玩家本人", "settlementItems": [],
    }
    settlement.update(settlement_extra)
    record = build_canonical_match_record_v7(
        match_id=match_id,
        played_at="2026-08-25T12:00:00+08:00",
        lifecycle_status="FINALIZED",
        source="vision-auto-archiver",
        environment={"venue": "珊瑚场", "box": "皮制宝箱", "fieldCondition": "standard"},
        settlement=settlement,
    )
    history.persist_record_transactional(record, is_finalized=True)
    return record


class WarehouseIdentityReviewReadbackV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.prev_env = os.environ.get(DATA_ROOT_OVERRIDE_ENV)
        prod_env = {key: value for key, value in os.environ.items() if key != DATA_ROOT_OVERRIDE_ENV}
        try:
            self.prod = runtime_data_paths(prod_env)
            self.hist = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        except Exception:
            self.prod = None
            self.hist = None
        os.environ[DATA_ROOT_OVERRIDE_ENV] = str(self.root)
        self.history_path = runtime_data_paths().history_path
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history = CanonicalHistoryStore(self.history_path)
        self.catalog = CatalogAuthority(CATALOG)

    def tearDown(self):
        if self.prev_env is None:
            os.environ.pop(DATA_ROOT_OVERRIDE_ENV, None)
        else:
            os.environ[DATA_ROOT_OVERRIDE_ENV] = self.prev_env
        if self.prod is not None:
            after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
            self.assertEqual(after, self.hist)
        self.tmp.cleanup()

    def _persist_once(self, key="recWirRead01"):
        packet = _packet(key)
        _seed(self.history, key)
        session = WarehouseIdentityReviewSession(catalog=self.catalog)
        session.open(packet)
        session._artifact = resolve_warehouse_identity_review(
            packet,
            {
                "schemaVersion": "warehouse-identity-review-decision.v1",
                "recordStableKey": packet["recordStableKey"],
                "packetFingerprint": packet["sourceFingerprint"],
                "reviewedAt": "2026-08-25T16:00:00Z",
                "reviewerType": "HUMAN",
                "decisions": [{"decisionId": "d1", "trackId": "track-a", "action": ACTION_CONFIRM, "selectedCatalogId": "catRect"}],
            },
            catalog=self.catalog,
        )
        persist_warehouse_identity_review(
            session=session,
            history_store=self.history,
            session_id=session.persist_binding()["sessionId"],
            packet_fingerprint=session.persist_binding()["packetFingerprint"],
        )
        return packet, session.artifact_copy()

    def test_old_v7_legacy_and_illegal_fail_closed(self):
        missing = summarize_persisted_identity_review(_seed(self.history, "recWirRead00"))
        self.assertFalse(missing["saved"])
        self.assertFalse(missing["readable"])
        self.assertEqual(set(missing), SUMMARY_KEYS)
        self.assertIn("尚未写入", missing["caption"])
        legacy = summarize_persisted_identity_review({"id": "legacy:abc", "source": "legacy", "schemaVersion": 7, "settlement": {}})
        self.assertFalse(legacy["saved"])
        self.assertIn("旧版", legacy["caption"])
        old = dict(_seed(self.history, "recWirReadOld"))
        old["schemaVersion"] = 6
        self.assertFalse(summarize_persisted_identity_review(old)["saved"])
        _seed(self.history, "recWirReadBad")
        self.history.update_record_transactional(
            "recWirReadBad",
            {"settlement": {"warehouseIdentityReview": {"schemaVersion": "nope", "relativePath": "C:/x.png"}}},
        )
        bad = summarize_persisted_identity_review(self.history.lookup("recWirReadBad"))
        self.assertFalse(bad["saved"])
        self.assertFalse(bad["readable"])
        self.assertEqual(bad["caption"], "仓库审阅结果不可读取")
        self.assertIsNone(bad["reviewCompletion"])

    def test_destroy_session_and_cold_start_readback(self):
        packet, artifact = self._persist_once()
        del artifact
        fresh_session = WarehouseIdentityReviewSession(catalog=self.catalog)
        self.assertIsNone(fresh_session.persist_binding())
        record = self.history.lookup(packet["recordStableKey"])
        summary = summarize_persisted_identity_review(record)
        self.assertTrue(summary["saved"])
        self.assertTrue(summary["readable"])
        self.assertEqual(summary["caption"], "已写入本局记录")
        self.assertEqual(summary["warehouseCoverage"], "COMPLETE")
        self.assertEqual(summary["reviewCompletion"], "COMPLETE")
        self.assertEqual(summary["identityResolution"], "FULLY_RESOLVED")
        self.assertEqual(summary["resolvedCount"], 1)
        self.assertEqual(summary["excludedCount"], 0)
        self.assertEqual(summary["unresolvedCount"], 0)
        blob = str(summary)
        self.assertNotIn("sha256", blob)
        self.assertNotIn("bbox", blob)
        self.assertNotIn("decisions", blob)
        self.assertNotIn("resolvedItems", blob)
        self.assertNotIn("relativePath", blob)
        self.assertEqual(set(summary), SUMMARY_KEYS)

        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            settlement_review_service=_FakeReviewService(),
            warehouse_identity_review_session=WarehouseIdentityReviewSession(catalog=self.catalog),
            warehouse_identity_review_history_store=self.history,
        )
        response = bridge.dispatch({
            "action": "request_settlement_review",
            "recordId": packet["recordStableKey"],
            "source": "current",
        })
        attached = response["settlementReview"]["warehouseIdentitySummary"]
        self.assertEqual(attached, summary)
        self.assertEqual(response["settlementReview"]["review"]["warehouseIdentitySummary"]["caption"], "已写入本局记录")
        self.assertNotIn("warehouseIdentityReview", response["settlementReview"]["review"]["settlement"])

    def test_same_fingerprint_blocks_resave_and_conflict_has_no_overwrite(self):
        packet, _artifact = self._persist_once("recWirRead02")
        session = WarehouseIdentityReviewSession(catalog=self.catalog)
        session.open(packet)
        session._artifact = resolve_warehouse_identity_review(
            packet,
            {
                "schemaVersion": "warehouse-identity-review-decision.v1",
                "recordStableKey": packet["recordStableKey"],
                "packetFingerprint": packet["sourceFingerprint"],
                "reviewedAt": "2026-08-25T16:00:00Z",
                "reviewerType": "HUMAN",
                "decisions": [{"decisionId": "d1", "trackId": "track-a", "action": ACTION_CONFIRM, "selectedCatalogId": "catRect"}],
            },
            catalog=self.catalog,
        )
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            warehouse_identity_review_session=session,
            warehouse_identity_review_history_store=self.history,
        )
        view = bridge.dispatch({
            "action": "warehouse_identity_review",
            "op": "view",
            "sessionId": session.persist_binding()["sessionId"],
            "packetFingerprint": session.persist_binding()["packetFingerprint"],
        })["warehouseIdentityReview"]
        self.assertTrue(view["persisted"])
        self.assertFalse(view["persistenceAvailable"])
        self.assertEqual(view["persistStatus"], "SAVED")
        session._artifact = resolve_warehouse_identity_review(
            packet,
            {
                "schemaVersion": "warehouse-identity-review-decision.v1",
                "recordStableKey": packet["recordStableKey"],
                "packetFingerprint": packet["sourceFingerprint"],
                "reviewedAt": "2026-08-25T17:00:00Z",
                "reviewerType": "HUMAN",
                "decisions": [{"decisionId": "d2", "trackId": "track-a", "action": ACTION_DEFER}],
            },
            catalog=self.catalog,
        )
        conflict = bridge.dispatch({
            "action": "warehouse_identity_review",
            "op": "view",
            "sessionId": session.persist_binding()["sessionId"],
            "packetFingerprint": session.persist_binding()["packetFingerprint"],
        })["warehouseIdentityReview"]
        self.assertEqual(conflict["persistStatus"], "CONFLICT")
        self.assertFalse(conflict["persistenceAvailable"])
        self.assertIn("未覆盖", conflict["persistenceCaption"])

    def test_single_saved_caption_and_screenshot(self):
        from playwright.sync_api import sync_playwright

        css = (CORE_DIR / "main_window.css").read_text(encoding="utf-8")
        page_html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
{css}
html,body{{margin:0;background:#111318}}
.detail-section{{padding:16px;margin:16px}}
</style></head><body>
<div class="detail-section detail-section-review" id="detail-review-section">
  <div class="detail-section-title">结算截图与核对</div>
  <div class="wir-saved-summary" id="wir-saved-summary">
    <div class="wir-saved-caption" id="wir-saved-caption">已写入本局记录</div>
    <div class="wir-saved-facts" id="wir-saved-facts">覆盖 COMPLETE · 审阅 COMPLETE · 身份 FULLY_RESOLVED · 已确认 1 · 已排除 0 · 未决 0</div>
  </div>
</div>
</body></html>"""
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        shot = SHOT_DIR / "reopen_1280x800.png"
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        self.assertIn("renderWarehouseIdentitySummary", js)
        self.assertIn("extra !== persistText", js)
        self.assertNotIn('saveBtn.textContent = "已写入本局记录"', js)
        self.assertNotIn("已训练", js)
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        self.assertIsNotNone(get_production_scroll_driver())
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content(page_html, wait_until="load")
            count = page.evaluate("() => (document.body.innerText.match(/已写入本局记录/g) || []).length")
            self.assertEqual(count, 1)
            page.screenshot(path=str(shot), full_page=True)
            browser.close()
        self.assertGreaterEqual(shot.stat().st_size, 8000)


if __name__ == "__main__":
    unittest.main()
