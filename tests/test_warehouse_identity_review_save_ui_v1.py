"""Tests for explicit save-reviewed-result UI wired to 4C4C3A persist."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
from warehouse_identity_review_session import WarehouseIdentityReviewSession
from warehouse_review_packet import build_warehouse_review_packet, source_fingerprint_for

SHOT_DIR = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_identity_review_save_v1"
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


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _descriptor(evidence_id: str, seed: str, key: str) -> dict:
    digest = _digest(seed)
    return {
        "schemaVersion": ORIGINAL_V2,
        "evidenceId": evidence_id,
        "recordStableKey": key,
        "kind": "warehouse-segment",
        "capturedAt": "2026-08-25T12:00:00Z",
        "storageMode": "file",
        "relativePath": f"evidence/settlement_v2/blobs/{digest[:2]}/{digest}.png",
        "sha256": digest,
        "byteSize": 1024,
        "mimeType": "image/png",
        "width": 640,
        "height": 720,
        "coverageMode": "viewport-segment",
        "coverageStatus": "PARTIAL",
    }


def _packet(key="recWirSave01"):
    ledger = WarehouseCoverageLedger(key)
    top = _descriptor("ev-top", "aa", key)
    mid = _descriptor("ev-mid", "bb", key)
    bot = _descriptor("ev-bot", "cc", key)
    ledger.add_segment(top, sequence_index=0, top_proof={"trusted": True, "proofId": "t"})
    ledger.add_segment(mid, sequence_index=1, overlap_proof={"trusted": True, "aligned": True, "proofId": "o1", "previousEvidenceId": "ev-top"})
    ledger.add_segment(bot, sequence_index=2, bottom_proof={"trusted": True, "proofId": "b"}, overlap_proof={"trusted": True, "aligned": True, "proofId": "o2", "previousEvidenceId": "ev-mid"})
    coverage = ledger.finalize(REASON_COMPLETE)
    candidates = [{
        "catalogId": "catRect", "name": "RectBox", "identityStatus": "CANDIDATE_ONLY",
        "geometry": {"width": 2, "height": 2, "cells": 4, "shape": "1100011000000000000000000"},
        "matchReasons": ["EXACT_CELL_MASK"],
    }]
    track = {
        "trackId": "track-a", "status": "OBSERVED", "clipped": False, "reasons": [],
        "widthCandidates": [2], "heightCandidates": [2], "spanCandidates": [4],
        "globalCellMaskCandidates": [{"cellMask": [[1, 1], [1, 1]]}],
        "candidates": candidates,
        "observations": [
            {"observationId": "obs-a0", "segmentId": "seg0", "sequenceIndex": 0, "localBox": [4.0, 6.0, 40.0, 50.0], "status": "OBSERVED"},
            {"observationId": "obs-a1", "segmentId": "seg1", "sequenceIndex": 1, "localBox": [4.0, 6.0, 40.0, 50.0], "status": "OBSERVED"},
        ],
    }
    physical = {
        "schemaVersion": "warehouse-physical-ledger.v1",
        "recordStableKey": key,
        "chainStatus": "ACTIVE",
        "segments": [
            {"segmentId": "seg0", "sequenceIndex": 0, "originY": 0.0, "scrollState": "TOP", "chainId": 0},
            {"segmentId": "seg1", "sequenceIndex": 1, "originY": 90.0, "scrollState": "MIDDLE", "chainId": 0},
            {"segmentId": "seg2", "sequenceIndex": 2, "originY": 210.0, "scrollState": "BOTTOM", "chainId": 0},
        ],
        "tracks": [track],
        "conflicts": [],
    }
    packet = build_warehouse_review_packet(
        coverage_ledger=coverage,
        physical_ledger=physical,
        descriptors=[top, mid, bot],
        catalog_index=CatalogGeometryIndex(CATALOG),
    )
    packet["tracks"][0]["candidates"] = candidates
    packet["tracks"][0]["bestObservationId"] = "obs-a0"
    packet["sourceFingerprint"] = source_fingerprint_for(packet)
    return packet


def _seed(history: CanonicalHistoryStore, match_id: str, *, source="vision-auto-archiver"):
    record = build_canonical_match_record_v7(
        match_id=match_id,
        played_at="2026-08-25T12:00:00+08:00",
        lifecycle_status="FINALIZED",
        source=source,
        environment={"venue": "珊瑚场", "box": "皮制宝箱", "fieldCondition": "standard"},
        settlement={
            "status": "verified", "verified": True, "clearingPrice": 100000,
            "actualTotal": 200000, "realizedProfit": 50000, "acquired": True,
            "winner": "玩家本人", "settlementItems": [],
        },
    )
    history.persist_record_transactional(record, is_finalized=True)
    return record


def _artifact(packet, catalog, action=ACTION_CONFIRM):
    decisions = [{
        "decisionId": "d1", "trackId": "track-a", "action": action,
        **({"selectedCatalogId": "catRect"} if action == ACTION_CONFIRM else {}),
    }]
    document = {
        "schemaVersion": "warehouse-identity-review-decision.v1",
        "recordStableKey": packet["recordStableKey"],
        "packetFingerprint": packet["sourceFingerprint"],
        "reviewedAt": "2026-08-25T16:00:00Z",
        "reviewerType": "HUMAN",
        "decisions": decisions,
    }
    return resolve_warehouse_identity_review(packet, document, catalog=catalog)


def _panel_html() -> str:
    source = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
    start = source.index('<section class="wir-panel"')
    end = source.index("</section>", start) + len("</section>")
    panel = source[start:end].replace(" hidden", "", 1)
    css = (CORE_DIR / "main_window.css").read_text(encoding="utf-8")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
{css}
html,body{{margin:0;background:#111318;min-width:0!important}}
</style></head><body>{panel}</body></html>"""


class WarehouseIdentityReviewSaveUIV1Tests(unittest.TestCase):
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

    def _bridge(self, session):
        return MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            warehouse_identity_review_session=session,
            warehouse_identity_review_history_store=self.history,
        )

    def _ready(self, key="recWirSave01", action=ACTION_CONFIRM):
        packet = _packet(key)
        _seed(self.history, key)
        session = WarehouseIdentityReviewSession(catalog=self.catalog)
        session.open(packet)
        session._artifact = _artifact(packet, self.catalog, action=action)
        return session, packet

    def _dispatch(self, bridge, op, session, **extra):
        binding = session.persist_binding() or {}
        payload = {
            "action": "warehouse_identity_review",
            "op": op,
            "sessionId": binding.get("sessionId"),
            "packetFingerprint": binding.get("packetFingerprint"),
        }
        payload.update(extra)
        return bridge.dispatch(payload)["warehouseIdentityReview"]

    def test_generate_without_save_does_not_write(self):
        session, packet = self._ready()
        bridge = self._bridge(session)
        view = self._dispatch(bridge, "view", session)
        self.assertTrue(view["artifactReady"])
        self.assertTrue(view["persistenceAvailable"])
        self.assertFalse(view["persisted"])
        self.assertEqual(view["persistenceCaption"], "尚未写入历史记录")
        stored = self.history.lookup(packet["recordStableKey"])
        self.assertNotIn("warehouseIdentityReview", stored["settlement"])

    def test_confirm_saves_once_and_retry_is_idempotent(self):
        session, packet = self._ready()
        bridge = self._bridge(session)
        first = self._dispatch(bridge, "persist", session, artifact={"evil": True}, Name="x", bbox=[1, 2, 3, 4])
        self.assertTrue(first["persisted"])
        self.assertEqual(first["persistStatus"], "SAVED")
        self.assertEqual(first["persistMessage"], "已写入本局记录")
        stored = self.history.lookup(packet["recordStableKey"])
        fingerprint = stored["settlement"]["warehouseIdentityReview"]["artifactFingerprint"]
        again = self._dispatch(bridge, "persist", session)
        self.assertTrue(again["persisted"])
        self.assertEqual(again["persistMessage"], "已写入本局记录")
        self.assertEqual(
            self.history.lookup(packet["recordStableKey"])["settlement"]["warehouseIdentityReview"]["artifactFingerprint"],
            fingerprint,
        )

    def test_conflict_session_and_transaction_failures_do_not_write(self):
        session, packet = self._ready()
        bridge = self._bridge(session)
        self._dispatch(bridge, "persist", session)
        before = self.history_path.read_bytes()
        session._artifact = _artifact(packet, self.catalog, action=ACTION_DEFER)
        conflict = self._dispatch(bridge, "persist", session)
        self.assertEqual(conflict["persistStatus"], "ARTIFACT_CONFLICT")
        self.assertEqual(conflict["persistMessage"], "本局已有不同审阅结果，未覆盖")
        self.assertFalse(conflict["persisted"])
        self.assertEqual(self.history_path.read_bytes(), before)
        expired = self._dispatch(bridge, "persist", session, sessionId="nope")
        self.assertEqual(expired["persistStatus"], "SESSION_MISMATCH")
        self.assertIn("未写入", expired["persistMessage"])
        self.assertEqual(self.history_path.read_bytes(), before)
        session2, _packet = self._ready("recWirSave02")
        bridge2 = self._bridge(session2)
        before2 = self.history_path.read_bytes()
        with mock.patch("canonical_history_store.os.replace", side_effect=OSError("disk")):
            failed = self._dispatch(bridge2, "persist", session2)
        self.assertEqual(failed["persistStatus"], "HISTORY_WRITE_FAILED")
        self.assertEqual(self.history_path.read_bytes(), before2)

    def test_frontend_confirm_contract_and_no_auto_save(self):
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        self.assertIn("写入本局记录", html)
        self.assertIn("将本次人工审阅结果写入本局记录；不会自动用于 Solver、算法优化或识图训练。", html)
        self.assertIn("确认写入", html)
        self.assertIn('id="wir-save" class="btn-review-action" hidden', html)
        self.assertIn("postWarehousePersist", js)
        self.assertIn('op: "persist"', js)
        self.assertNotIn("已训练", html + js)
        self.assertNotIn("已优化算法", html + js)
        self.assertNotIn("保存成功", html)
        show = re.search(r"function showView\([^)]*\) \{[\s\S]{0,900}", js)
        self.assertIsNotNone(show)
        self.assertNotIn("persist", show.group(0))
        self.assertIn("wirSaveConfirmOpen = false", show.group(0))
        unload = re.search(r"beforeunload[\s\S]{0,240}", js)
        self.assertIsNotNone(unload)
        self.assertNotIn("persist", unload.group(0))
        cancel = re.search(r"wir-save-cancel[\s\S]{0,280}", js)
        self.assertIsNotNone(cancel)
        self.assertNotIn("postWarehousePersist", cancel.group(0))
        persist_fn = re.search(r"function postWarehousePersist\(\) \{[\s\S]*?\n\}", js)
        self.assertIsNotNone(persist_fn)
        self.assertIn("sessionId", persist_fn.group(0))
        self.assertIn("packetFingerprint", persist_fn.group(0))
        self.assertNotIn("artifact", persist_fn.group(0))
        self.assertNotIn("bbox", persist_fn.group(0))
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        self.assertIsNotNone(get_production_scroll_driver())

    def test_layout_screenshots(self):
        from playwright.sync_api import sync_playwright

        html = _panel_html()
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        confirm = SHOT_DIR / "confirm_1280x800.png"
        saved = SHOT_DIR / "saved_1280x800.png"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content(html, wait_until="load")
            page.evaluate(
                """() => {
                  const coverage = document.getElementById("wir-coverage");
                  if (coverage) coverage.textContent = "仓库滚动覆盖完整";
                  const persist = document.getElementById("wir-persist");
                  if (persist) persist.textContent = "尚未写入历史记录";
                  const save = document.getElementById("wir-save");
                  if (save) { save.hidden = false; save.textContent = "写入本局记录"; }
                  const box = document.getElementById("wir-save-confirm");
                  if (box) box.hidden = false;
                  const draft = document.getElementById("wir-draft");
                  if (draft) draft.textContent = "已选候选尚未确认";
                  const cand = document.getElementById("wir-candidates");
                  if (cand) cand.innerHTML = '<div class="wir-candidate is-selected"><strong>RectBox</strong><div>2x2/4 · CANDIDATE_ONLY</div></div>';
                }"""
            )
            page.screenshot(path=str(confirm), full_page=True)
            page.evaluate(
                """() => {
                  const box = document.getElementById("wir-save-confirm");
                  if (box) box.hidden = true;
                  const save = document.getElementById("wir-save");
                  if (save) { save.hidden = false; save.disabled = true; save.textContent = "已写入本局记录"; }
                  const persist = document.getElementById("wir-persist");
                  if (persist) persist.textContent = "已写入本局记录";
                  const message = document.getElementById("wir-message");
                  if (message) message.textContent = "已写入本局记录";
                }"""
            )
            page.screenshot(path=str(saved), full_page=True)
            browser.close()
        self.assertGreaterEqual(confirm.stat().st_size, 8000)
        self.assertGreaterEqual(saved.stat().st_size, 8000)


if __name__ == "__main__":
    unittest.main()
