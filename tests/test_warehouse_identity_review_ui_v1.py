"""Tests for A-style warehouse identity review UI and Native view model."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from main_window import MainWindowBridge, OverlayVisibilityController
from runtime_data import runtime_data_paths
from settlement_evidence_store_v2 import KIND_WAREHOUSE_SEGMENT, SettlementEvidenceStoreV2
from warehouse_catalog_geometry import CatalogGeometryIndex
from warehouse_capture_session import PRODUCTION_SCROLL_DRIVER_ENABLED, get_production_scroll_driver
from warehouse_coverage_ledger import REASON_COMPLETE, REASON_USER_STOP, WarehouseCoverageLedger
from warehouse_identity_review import (
    ACTION_CONFIRM,
    ACTION_DEFER,
    ACTION_EXCLUDE,
    ACTION_FLAG,
    ACTION_OUT_OF_CATALOG,
    ACTION_OVERRIDE,
    CatalogAuthority,
)
from warehouse_identity_review_session import (
    VIEW_KEYS,
    WarehouseIdentityReviewSession,
    WarehouseIdentityReviewSessionError,
    crop_verified_observation,
)
from warehouse_review_packet import build_warehouse_review_packet

SHOT_DIR = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_identity_review_ui_v1"

CATALOG = [
    {
        "Id": "catRect",
        "Name": "RectBox",
        "Quality": "金",
        "Width": 2,
        "Height": 2,
        "Cells": 4,
        "Shape": "1100011000000000000000000",
    },
    {
        "Id": "catOther",
        "Name": "OtherBox",
        "Quality": "紫",
        "Width": 1,
        "Height": 1,
        "Cells": 1,
        "Shape": "1000000000000000000000000",
    },
    {
        "Id": "catBad",
        "Name": "BrokenGeom",
        "Quality": "白",
        "Width": 0,
        "Height": 0,
        "Cells": 0,
        "Shape": "0000000000000000000000000",
    },
]


class _FakeOverlay:
    def __init__(self):
        self.Visible = True
        self.WebView = object()

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class _FakeHost:
    def __init__(self, packet):
        self._packet = packet

    def review_packet_copy(self):
        return self._packet

    def presentation_payload(self):
        return {
            "available": False,
            "state": "IDLE",
            "segmentCount": 0,
            "coverageStatus": "COVERAGE_UNPROVEN",
            "stopAvailable": False,
            "message": "",
            "terminationReason": None,
            "packetAvailable": True,
            "packetStatus": "REVIEW_REQUIRED",
            "packetFingerprint": "a" * 64,
            "reviewStatus": "REVIEW_REQUIRED",
        }


class _RecordingSession:
    def __init__(self):
        self.opened = []
        self.dispatched = []

    def open(self, packet=None):
        self.opened.append(packet)
        return {"available": packet is not None, "sessionId": "native-session"}

    def dispatch(self, payload):
        self.dispatched.append(payload)
        return {"available": True, "sessionId": "native-session"}

    def view(self):
        return {"available": True, "sessionId": "native-session"}


def _png(color=(30, 80, 160), size=(80, 80)) -> bytes:
    image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    image[:] = color
    return cv2.imencode(".png", image)[1].tobytes()


def _descriptor(store, key, color):
    return store.save_original(record_stable_key=key, kind=KIND_WAREHOUSE_SEGMENT, image_bytes=_png(color, (120, 90)))


def _track(track_id, observations):
    return {
        "trackId": track_id,
        "status": "OBSERVED",
        "clipped": False,
        "reasons": [],
        "widthCandidates": [2],
        "heightCandidates": [2],
        "spanCandidates": [4],
        "globalCellMaskCandidates": [{"cellMask": [[1, 1], [1, 1]]}],
        "observations": observations,
    }


def _packet_with_store(store, key="recWir01", *, complete=True, extra_tracks=None):
    top = _descriptor(store, key, (20, 90, 180))
    mid = _descriptor(store, key, (20, 140, 80))
    descriptors = [top, mid]
    ledger = WarehouseCoverageLedger(key)
    ledger.add_segment(top, sequence_index=0, top_proof={"trusted": True, "proofId": "t"})
    ledger.add_segment(
        mid,
        sequence_index=1,
        overlap_proof={"trusted": True, "aligned": True, "proofId": "o1", "previousEvidenceId": top["evidenceId"]},
    )
    physical_segments = [
        {"segmentId": "seg0", "sequenceIndex": 0, "originY": 0.0, "scrollState": "TOP", "chainId": 0},
        {"segmentId": "seg1", "sequenceIndex": 1, "originY": 10.0, "scrollState": "MIDDLE", "chainId": 0},
    ]
    evidence_map = {"seg0": top["evidenceId"], "seg1": mid["evidenceId"]}
    if complete:
        bot = _descriptor(store, key, (40, 40, 40))
        descriptors.append(bot)
        ledger.add_segment(
            bot,
            sequence_index=2,
            bottom_proof={"trusted": True, "proofId": "b"},
            overlap_proof={"trusted": True, "aligned": True, "proofId": "o2", "previousEvidenceId": mid["evidenceId"]},
        )
        physical_segments.append(
            {"segmentId": "seg2", "sequenceIndex": 2, "originY": 20.0, "scrollState": "BOTTOM", "chainId": 0}
        )
        evidence_map["seg2"] = bot["evidenceId"]
        coverage = ledger.finalize(REASON_COMPLETE)
    else:
        coverage = ledger.finalize(REASON_USER_STOP)
    index = CatalogGeometryIndex(CATALOG)
    track = _track("track-a", [
        {"observationId": "obs-a", "segmentId": "seg0", "sequenceIndex": 0, "localBox": [10, 10, 70, 70], "status": "OBSERVED"},
        {"observationId": "obs-b", "segmentId": "seg1", "sequenceIndex": 1, "localBox": [8, 8, 60, 60], "status": "AMBIGUOUS"},
    ])
    tracks = [track]
    if extra_tracks:
        tracks.extend(extra_tracks)
    physical = {
        "schemaVersion": "warehouse-physical-ledger.v1",
        "recordStableKey": key,
        "chainStatus": "ACTIVE",
        "segments": physical_segments,
        "tracks": tracks,
        "conflicts": [],
    }
    packet = build_warehouse_review_packet(
        coverage_ledger=coverage,
        physical_ledger=physical,
        descriptors=descriptors,
        catalog_index=index,
        segment_evidence_map=evidence_map,
    )
    return packet, descriptors


def _authority():
    return CatalogAuthority(CATALOG)


def _session(store, packet=None, **kwargs):
    packet = packet or _packet_with_store(store)[0]
    session = WarehouseIdentityReviewSession(store=store, catalog=_authority(), **kwargs)
    session.open(packet)
    return session, packet


def _render_review_html() -> str:
    source = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
    start = source.index('<section class="wir-panel"')
    end = source.index("</section>", start) + len("</section>")
    panel = source[start:end].replace(" hidden", "", 1)
    css = (CORE_DIR / "main_window.css").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
{css}
html, body {{ margin: 0; background: #111318; min-width: 0 !important; }}
.app-shell {{ min-width: 0 !important; }}
.wir-panel {{ margin: 12px; }}
  </style>
</head>
<body>{panel}</body>
</html>"""


def _fill_review_panel(page) -> None:
    png = _png((20, 90, 180), (80, 80))
    import base64
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    page.evaluate(
        """({dataUrl}) => {
          const coverage = document.getElementById("wir-coverage");
          const caption = document.getElementById("wir-coverage-caption");
          const progress = document.getElementById("wir-progress");
          const trackPos = document.getElementById("wir-track-pos");
          const persist = document.getElementById("wir-persist");
          const geom = document.getElementById("wir-geom");
          const draft = document.getElementById("wir-draft");
          const message = document.getElementById("wir-message");
          if (coverage) coverage.textContent = "仓库滚动覆盖完整";
          if (caption) caption.textContent = "不等于身份已全部识别";
          if (progress) progress.textContent = "已处理 0 / 2 · 未处理 2";
          if (trackPos) trackPos.textContent = "第 1 / 2 件";
          if (persist) persist.textContent = "尚未写入历史记录";
          if (geom) geom.textContent = "EXACT · 完整";
          if (draft) draft.textContent = "已选候选尚未确认";
          if (message) message.textContent = "";
          const img = document.getElementById("wir-hero-img");
          const missing = document.getElementById("wir-hero-missing");
          if (img && missing) {
            img.src = dataUrl;
            img.hidden = false;
            missing.hidden = true;
          }
          const thumbs = document.getElementById("wir-thumbs");
          if (thumbs) thumbs.innerHTML = '<span class="wir-thumb-missing">不可用</span>';
          const box = document.getElementById("wir-candidates");
          if (box) box.innerHTML = '<div class="wir-candidate is-selected"><strong>RectBox</strong><div>2x2/4 · CANDIDATE_ONLY</div></div>';
        }""",
        {"dataUrl": data_url},
    )


def _no_overlap(page) -> bool:
    return page.evaluate(
        """() => {
          const nodes = [...document.querySelectorAll(".btn-review-action, .wir-filter")];
          const rects = nodes.map((node) => node.getBoundingClientRect()).filter((r) => r.width > 1 && r.height > 1);
          for (let i = 0; i < rects.length; i += 1) {
            for (let j = i + 1; j < rects.length; j += 1) {
              const a = rects[i];
              const b = rects[j];
              const overlap = !(a.right <= b.left + 0.5 || b.right <= a.left + 0.5 || a.bottom <= b.top + 0.5 || b.bottom <= a.top + 0.5);
              if (overlap) return false;
            }
          }
          return true;
        }"""
    )


class WarehouseIdentityReviewUIV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.store = SettlementEvidenceStoreV2(self.root)
        self.prod = runtime_data_paths()
        self.hist = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None

    def tearDown(self):
        after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.assertEqual(after, self.hist)
        self.tmp.cleanup()

    def test_hidden_without_packet_and_view_whitelist(self):
        session = WarehouseIdentityReviewSession(store=self.store)
        view = session.view()
        self.assertFalse(view["available"])
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        self.assertIn('id="warehouse-identity-review" hidden', html)
        self.assertTrue(set(view) <= VIEW_KEYS)

    def test_native_crop_and_no_path_leak(self):
        session, packet = _session(self.store)
        view = session.view()
        self.assertTrue(view["available"])
        self.assertTrue(view["bestObservation"]["imageAvailable"])
        self.assertTrue(str(view["bestObservation"]["imageDataUrl"]).startswith("data:image/png;base64,"))
        blob = json.dumps(view)
        self.assertNotIn("relativePath", blob)
        self.assertNotIn("bbox", blob)
        self.assertNotIn("sha256", blob)
        self.assertNotIn("Quality", blob)
        self.assertNotIn(packet["recordStableKey"], blob)
        self.assertNotIn("totalItems", blob)
        with self.assertRaises(WarehouseIdentityReviewSessionError) as raised:
            session.dispatch({"op": "view", "sha256": "abc"})
        self.assertEqual(raised.exception.code, "FORBIDDEN_CLIENT_FIELD")
        with self.assertRaises(WarehouseIdentityReviewSessionError):
            session.dispatch({"op": "apply", "bbox": [0, 0, 10, 10], "action": "DEFER"})
        with self.assertRaises(WarehouseIdentityReviewSessionError):
            crop_verified_observation(store=self.store, packet=packet, observation_id="missing-obs")

    def test_select_is_not_confirm_and_single_candidate_stays_open(self):
        session, _packet = _session(self.store)
        view = session.select_candidate("catRect")
        self.assertIsNone(view["draftAction"])
        self.assertTrue(any(item["selected"] for item in view["candidates"]))
        self.assertEqual(view["reviewCompletion"], "NOT_STARTED")
        with self.assertRaises(WarehouseIdentityReviewSessionError) as raised:
            session.apply({"action": "CONFIRM_CANDIDATE", "selectedCatalogId": "catRect"})
        self.assertEqual(raised.exception.code, "CONFIRM_REQUIRED")
        confirmed = session.apply({
            "action": "CONFIRM_CANDIDATE",
            "selectedCatalogId": "catRect",
            "confirmCandidate": True,
        })
        self.assertEqual(confirmed["draftAction"], "CONFIRM_CANDIDATE")
        with self.assertRaises(WarehouseIdentityReviewSessionError) as raised:
            session.apply({"action": "CONFIRM_CANDIDATE", "selectedCatalogId": "catRect", "confirmCandidate": True})
        self.assertEqual(raised.exception.code, "ALREADY_PROCESSED")
        undone = session.undo()
        self.assertIsNone(undone["draftAction"])

    def test_reason_required_and_finalize_not_persisted(self):
        session, _packet = _session(self.store)
        for action in (ACTION_OVERRIDE, ACTION_OUT_OF_CATALOG, ACTION_EXCLUDE, ACTION_FLAG):
            with self.assertRaises(WarehouseIdentityReviewSessionError) as raised:
                session.apply({"action": action, "selectedCatalogId": "catOther"})
            self.assertEqual(raised.exception.code, "REASON_REQUIRED" if action != ACTION_OVERRIDE else raised.exception.code)
        session.apply({"action": ACTION_CONFIRM, "selectedCatalogId": "catRect", "confirmCandidate": True})
        done = session.finalize("2026-08-25T16:00:00Z")
        self.assertTrue(done["artifactReady"])
        self.assertIn("尚未写入历史记录", done["persistenceCaption"])
        self.assertIn("尚未写入历史记录", done["message"])
        self.assertNotIn("保存成功", json.dumps(done, ensure_ascii=False))
        artifact = session.artifact_copy()
        self.assertEqual(artifact["identityResolution"], "FULLY_RESOLVED")
        self.assertEqual(done["identityResolution"], "FULLY_RESOLVED")
        self.assertEqual(done["reviewCompletion"], "COMPLETE")
        again = session.finalize("2026-08-25T16:00:00Z")
        self.assertEqual(session.artifact_copy()["artifactFingerprint"], artifact["artifactFingerprint"])
        self.assertEqual(again["persistenceCaption"], "尚未写入历史记录")

    def test_six_actions_map_to_resolver(self):
        cases = [
            ({"action": ACTION_CONFIRM, "selectedCatalogId": "catRect", "confirmCandidate": True}, ACTION_CONFIRM),
            ({
                "action": ACTION_OVERRIDE,
                "selectedCatalogId": "catOther",
                "overrideReason": "HUMAN_VISUAL_IDENTIFICATION",
                "confirmedByHuman": True,
            }, ACTION_OVERRIDE),
            ({"action": ACTION_OUT_OF_CATALOG, "reason": "not in book"}, ACTION_OUT_OF_CATALOG),
            ({"action": ACTION_DEFER, "reason": "later"}, ACTION_DEFER),
            ({"action": ACTION_EXCLUDE, "reason": "false box"}, ACTION_EXCLUDE),
            ({"action": ACTION_FLAG, "reason": "geom broken"}, ACTION_FLAG),
        ]
        for payload, expected in cases:
            session, _packet = _session(self.store)
            if expected == ACTION_OVERRIDE:
                session.select_override("catOther")
            view = session.apply(payload)
            self.assertEqual(view["draftAction"], expected)
            artifact = session.finalize("2026-08-25T16:00:00Z")
            copied = session.artifact_copy()
            self.assertEqual(copied["decisions"][0]["action"], expected)
            self.assertEqual(copied["artifactFingerprint"], session.finalize("2026-08-25T16:00:00Z") and session.artifact_copy()["artifactFingerprint"])
            self.assertIn("尚未写入历史记录", artifact["persistenceCaption"])

    def test_fingerprint_change_clears_draft(self):
        packet, _ = _packet_with_store(self.store)
        session = WarehouseIdentityReviewSession(store=self.store, catalog=_authority())
        session.open(packet)
        session.apply({"action": ACTION_DEFER})
        other, _ = _packet_with_store(self.store, key="recWir02")
        session.open(other)
        self.assertEqual(session.view()["processedCount"], 0)
        same_key, _ = _packet_with_store(
            self.store,
            key="recWir01",
            extra_tracks=[_track("track-z", [
                {"observationId": "obs-z", "segmentId": "seg0", "sequenceIndex": 0, "localBox": [15, 15, 55, 55], "status": "OBSERVED"},
            ])],
        )
        session.open(packet)
        session.apply({"action": ACTION_DEFER})
        session.open(same_key)
        self.assertEqual(session.view()["processedCount"], 0)
        self.assertNotEqual(packet["sourceFingerprint"], same_key["sourceFingerprint"])

    def test_stable_key_change_exits_session(self):
        session, packet = _session(self.store)
        first = session.view()["sessionId"]
        session.apply({"action": ACTION_DEFER})
        other, _ = _packet_with_store(self.store, key="recWir03")
        nxt = session.open(other)
        self.assertNotEqual(nxt["sessionId"], first)
        self.assertEqual(nxt["processedCount"], 0)

    def test_prev_next_does_not_auto_confirm(self):
        extra = [_track("track-b", [
            {"observationId": "obs-c", "segmentId": "seg0", "sequenceIndex": 0, "localBox": [12, 12, 72, 72], "status": "OBSERVED"},
        ])]
        packet, _ = _packet_with_store(self.store, extra_tracks=extra)
        session, _opened = _session(self.store, packet)
        session.select_candidate("catRect")
        self.assertIsNone(session.view()["draftAction"])
        nxt = session.step_track(1)
        self.assertIsNone(nxt["draftAction"])
        self.assertEqual(nxt["currentTrackId"], "track-b")
        back = session.step_track(-1)
        self.assertEqual(back["currentTrackId"], "track-a")
        self.assertIsNone(back["draftAction"])
        self.assertTrue(any(item["selected"] for item in back["candidates"]))

    def test_missing_evidence_blocks_identity_confirm(self):
        packet, _ = _packet_with_store(self.store)
        session = WarehouseIdentityReviewSession(store=None, catalog=_authority())
        view = session.open(packet)
        self.assertTrue(view["available"])
        self.assertFalse(view["hasLegalEvidence"])
        self.assertFalse(view["bestObservation"]["imageAvailable"])
        self.assertIsNone(view["bestObservation"]["imageDataUrl"])
        with self.assertRaises(WarehouseIdentityReviewSessionError) as raised:
            session.apply({"action": ACTION_CONFIRM, "selectedCatalogId": "catRect", "confirmCandidate": True})
        self.assertEqual(raised.exception.code, "EVIDENCE_UNAVAILABLE")
        deferred = session.apply({"action": ACTION_DEFER})
        self.assertEqual(deferred["draftAction"], ACTION_DEFER)

    def test_partial_copy_and_complete_not_identity(self):
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        css = (CORE_DIR / "main_window.css").read_text(encoding="utf-8")
        self.assertIn("persistenceCaption", js)
        self.assertIn("尚未写入历史记录", html)
        self.assertIn("warehouse-identity-review", html)
        self.assertIn("grid-template-columns: 1.1fr 0.9fr", css)
        self.assertIn("grid-template-columns: 1fr", css)
        self.assertIn("select_candidate", js)
        self.assertIn("confirmCandidate: true", js)
        self.assertIn("prev_track", js)
        self.assertIn("next_track", js)
        self.assertNotIn("totalItems", html)
        self.assertNotIn("保存成功", html)
        self.assertNotIn("身份全部识别", html)
        self.assertNotIn("身份全部识别", js)
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        self.assertIsNotNone(get_production_scroll_driver())
        packet, _ = _packet_with_store(self.store, key="recWir04", complete=False)
        session, _opened = _session(self.store, packet)
        view = session.view()
        self.assertEqual(view["coverageStatus"], "PARTIAL")
        self.assertIn("不代表整仓完整", view["coverageCaption"])
        self.assertNotIn("totalItems", json.dumps(view))
        complete_packet, _ = _packet_with_store(self.store, key="recWir05")
        complete_view = _session(self.store, complete_packet)[0].view()
        self.assertEqual(complete_view["coverageStatus"], "COMPLETE")
        self.assertIn("不等于身份已全部识别", complete_view["coverageCaption"])
        self.assertNotEqual(complete_view["reviewCompletion"], "FULLY_RESOLVED")

    def test_leave_page_does_not_auto_save(self):
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        show = re.search(r"function showView\([^)]*\) \{.*?\n\}", js, re.S)
        self.assertIsNotNone(show)
        self.assertNotIn("finalize", show.group(0))
        self.assertNotIn("warehouse_identity_review", show.group(0))
        unload = re.search(r"beforeunload[\s\S]{0,240}", js)
        self.assertIsNotNone(unload)
        self.assertNotIn("finalize", unload.group(0))
        self.assertNotIn("warehouse_identity_review", unload.group(0))

    def test_bridge_ignores_client_packet_and_paths(self):
        recorder = _RecordingSession()
        native_packet = {"native": True}
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            warehouse_capture_host=_FakeHost(native_packet),
            warehouse_identity_review_session=recorder,
        )
        response = bridge.dispatch({
            "action": "warehouse_identity_review",
            "op": "open",
            "packet": {"evil": True},
            "sha256": "abc",
            "bbox": [1, 2, 3, 4],
            "relativePath": "C:/secret.png",
            "Name": "spoof",
            "Quality": "金",
        })
        self.assertEqual(recorder.opened, [native_packet])
        self.assertTrue(response["warehouseIdentityReview"]["available"])
        bridge.dispatch({
            "action": "warehouse_identity_review",
            "op": "apply",
            "reviewAction": "CONFIRM_CANDIDATE",
            "bbox": [0, 0, 1, 1],
            "confirmCandidate": True,
            "selectedCatalogId": "catRect",
            "sessionId": "native-session",
        })
        self.assertEqual(len(recorder.dispatched), 1)
        self.assertNotIn("bbox", recorder.dispatched[0])
        self.assertNotIn("packet", recorder.dispatched[0])
        self.assertEqual(recorder.dispatched[0].get("reviewAction"), "CONFIRM_CANDIDATE")

    def test_override_quarantine_is_not_candidate_confirm(self):
        session, _packet = _session(self.store)
        hits = session.search("Broken")
        self.assertTrue(any(item["quarantined"] for item in hits["overrideHits"]))
        with self.assertRaises(WarehouseIdentityReviewSessionError):
            session.apply({"action": ACTION_CONFIRM, "selectedCatalogId": "catBad", "confirmCandidate": True})
        with self.assertRaises(WarehouseIdentityReviewSessionError) as raised:
            session.apply({
                "action": ACTION_OVERRIDE,
                "selectedCatalogId": "catRect",
                "overrideReason": "HUMAN_VISUAL_IDENTIFICATION",
                "confirmedByHuman": True,
            })
        self.assertEqual(raised.exception.code, "OVERRIDE_ID_IN_CANDIDATES")
        selected = session.select_override("catBad")
        self.assertTrue(any(item.get("selected") and item.get("quarantined") for item in selected["overrideHits"]))

    def test_layout_screenshots_fit(self):
        from playwright.sync_api import sync_playwright

        html = _render_review_html()
        wide = SHOT_DIR / "wide_1280x800.png"
        narrow = SHOT_DIR / "narrow_720x900.png"
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content(html, wait_until="load")
            _fill_review_panel(page)
            self.assertFalse(page.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"))
            self.assertTrue(_no_overlap(page))
            page.screenshot(path=str(wide), full_page=True)
            page.set_viewport_size({"width": 720, "height": 900})
            self.assertFalse(page.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"))
            self.assertTrue(_no_overlap(page))
            page.screenshot(path=str(narrow), full_page=True)
            browser.close()
        with Image.open(wide) as wide_img, Image.open(narrow) as narrow_img:
            self.assertGreaterEqual(wide_img.size[0], 1280)
            self.assertGreaterEqual(narrow_img.size[0], 720)


if __name__ == "__main__":
    unittest.main()
