"""Real 2026-08-25 warehouse evidence smoke for the A-style review UI."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from runtime_data import DATA_ROOT_OVERRIDE_ENV, runtime_data_paths
from settlement_evidence_store_v2 import STORE_RELATIVE_ROOT, SettlementEvidenceStoreV2
from warehouse_capture_session import (
    PRODUCTION_SCROLL_DRIVER_ENABLED,
    WarehouseCaptureSession,
    get_production_scroll_driver,
)
from warehouse_identity_review import ACTION_CONFIRM, ACTION_FLAG, CatalogAuthority
from warehouse_identity_review_session import (
    VIEW_KEYS,
    WarehouseIdentityReviewSession,
    WarehouseIdentityReviewSessionError,
)
from warehouse_scrollbar_observation import CHANGE_CHANGED, CHANGE_UNKNOWN, STATE_MIDDLE, STATE_TOP
from warehouse_segment_overlap import align_warehouse_segments

OVERLAP = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_overlap_v1"
SHOT_DIR = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_identity_review_real_v1"
KEY = "recWirReal01"


def _prod_env() -> dict:
    return {key: value for key, value in os.environ.items() if key != DATA_ROOT_OVERRIDE_ENV}


def _load(name: str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(OVERLAP / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(OVERLAP / name)
    return image


def _obs(state, change=CHANGE_UNKNOWN, fingerprint=""):
    return {
        "scrollState": state,
        "segmentChange": change,
        "confidence": 0.9,
        "warehouseFingerprint": fingerprint or state.lower(),
        "thumbPosition": 0.1,
        "thumbLength": 0.2,
        "trackBox": [1, 1, 2, 10],
        "thumbBox": [1, 1, 2, 3],
        "sourceId": state,
    }


def _decode_data_url(data_url: str) -> np.ndarray:
    payload = base64.b64decode(str(data_url).split(",", 1)[1])
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise AssertionError("crop data URL is not a decodable image")
    return image


def _is_real_crop(data_url: str) -> bool:
    image = _decode_data_url(data_url)
    return image.size > 0 and float(image.std()) > 12.0


class ScriptedFrames:
    def __init__(self, frames):
        self.frames = list(frames)
        self.captures = 0

    def capture(self):
        self.captures += 1
        return self.frames[min(self.captures - 1, len(self.frames) - 1)]


class ScriptedObserver:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def observe(self, _frame, **_kwargs):
        self.calls += 1
        return dict(self.results[min(self.calls - 1, len(self.results) - 1)])


class RecordingScroll:
    def __init__(self):
        self.requests = []

    def request_next_scroll(self):
        self.requests.append("DOWN")


def _panel_html() -> str:
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


def _fill_real_view(page, view: dict) -> None:
    page.evaluate(
        """(view) => {
          const coverage = document.getElementById("wir-coverage");
          const caption = document.getElementById("wir-coverage-caption");
          const progress = document.getElementById("wir-progress");
          const trackPos = document.getElementById("wir-track-pos");
          const persist = document.getElementById("wir-persist");
          const geom = document.getElementById("wir-geom");
          const draft = document.getElementById("wir-draft");
          if (coverage) {
            coverage.textContent = view.coverageStatus === "COMPLETE"
              ? "仓库滚动覆盖完整"
              : (view.coverageStatus === "PARTIAL" ? "只审阅已看到的藏品，不代表整仓完整" : "覆盖未就绪");
          }
          if (caption) caption.textContent = view.coverageCaption || "";
          if (progress) progress.textContent = `已处理 ${view.processedCount || 0} / ${view.trackCount || 0} · 未处理 ${view.unresolvedCount || 0}`;
          if (trackPos) trackPos.textContent = `第 ${view.trackIndex || 0} / ${view.trackCount || 0} 件`;
          if (persist) persist.textContent = view.persistenceCaption || "尚未写入历史记录";
          if (geom) geom.textContent = `${view.geometryStatus || ""} · ${view.clipped ? "裁断" : "完整"}`;
          if (draft) draft.textContent = "已选候选尚未确认";
          const img = document.getElementById("wir-hero-img");
          const missing = document.getElementById("wir-hero-missing");
          const best = view.bestObservation || {};
          if (img && missing) {
            if (best.imageAvailable && best.imageDataUrl) {
              img.src = best.imageDataUrl;
              img.hidden = false;
              missing.hidden = true;
            } else {
              img.removeAttribute("src");
              img.hidden = true;
              missing.hidden = false;
            }
          }
          const thumbs = document.getElementById("wir-thumbs");
          if (thumbs) {
            const usable = (view.otherObservations || []).filter((item) => item.imageAvailable && item.imageDataUrl);
            thumbs.innerHTML = usable.map((item) => `<img alt="其他证据" src="${item.imageDataUrl}">`).join("");
          }
          const box = document.getElementById("wir-candidates");
          if (box) {
            box.innerHTML = (view.candidates || []).map((item) =>
              `<div class="wir-candidate ${item.selected ? "is-selected" : ""}"><strong>${item.candidateName || item.candidateId}</strong><div>${item.geometryText || ""} · CANDIDATE_ONLY</div></div>`
            ).join("") || "<div class=\\"wir-missing\\">无几何候选</div>";
          }
          const reasonBox = document.getElementById("wir-reason-box");
          if (reasonBox) reasonBox.hidden = true;
        }""",
        view,
    )


class WarehouseIdentityReviewRealEvidenceV1Tests(unittest.TestCase):
    def setUp(self):
        self.prev_env = os.environ.get(DATA_ROOT_OVERRIDE_ENV)
        self.prod = runtime_data_paths(_prod_env())
        self.hist = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        os.environ[DATA_ROOT_OVERRIDE_ENV] = str(self.root)
        isolated = runtime_data_paths()
        self.assertEqual(isolated.root, self.root)
        self.store = SettlementEvidenceStoreV2(isolated.root)

    def tearDown(self):
        after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.assertEqual(after, self.hist)
        self.assertFalse((PROJECT_ROOT / STORE_RELATIVE_ROOT).exists())
        if self.prev_env is None:
            os.environ.pop(DATA_ROOT_OVERRIDE_ENV, None)
        else:
            os.environ[DATA_ROOT_OVERRIDE_ENV] = self.prev_env
        self.tmp.cleanup()

    def _capture_packet(self):
        frames = [_load("pair_a_prev.png"), _load("pair_a_next.png"), _load("pair_b_next.png")]
        session = WarehouseCaptureSession(
            frame_provider=ScriptedFrames(frames),
            scene_validator=lambda _raw: {"isSettlement": True, "stable": True, "recordStableKey": KEY},
            scroll_requester=RecordingScroll(),
            clock=lambda: 0.0,
            idle=lambda _dt: None,
            timeout_s=20.0,
            store=self.store,
            observer=ScriptedObserver([
                _obs(STATE_TOP, CHANGE_UNKNOWN, "t"),
                _obs(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                _obs(STATE_MIDDLE, CHANGE_CHANGED, "m2"),
            ]),
            aligner=align_warehouse_segments,
            max_steps=2,
            already_cropped=True,
        )
        result = session.start()
        packet = session.review_packet()
        self.assertIsNotNone(packet)
        self.assertGreaterEqual(len(result["savedDescriptors"]), 3)
        return packet, result

    def _open_review(self, packet, *, store="DEFAULT"):
        actual = self.store if store == "DEFAULT" else store
        review = WarehouseIdentityReviewSession(store=actual, catalog=CatalogAuthority())
        view = review.open(packet)
        self.assertTrue(view["available"])
        return review, view

    def _pick_multi_obs(self, review, packet):
        ranked = []
        for track in packet.get("tracks") or []:
            if len(track.get("observations") or []) < 2:
                continue
            view = review.select_track(str(track.get("trackId")))
            others = [
                item for item in (view.get("otherObservations") or [])
                if item.get("imageAvailable") and item.get("imageDataUrl")
            ]
            best = view.get("bestObservation") or {}
            if best.get("imageAvailable") and best.get("imageDataUrl") and others:
                ranked.append((len(others), len(best.get("imageDataUrl") or ""), view, others))
        if not ranked:
            self.fail("expected a real track with two legal observation crops")
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        winner = ranked[0][2]
        fresh = review.select_track(str(winner["currentTrackId"]))
        others = [
            item for item in (fresh.get("otherObservations") or [])
            if item.get("imageAvailable") and item.get("imageDataUrl")
        ]
        return fresh, others

    def test_real_descriptor_crop_and_observation_switch(self):
        packet, _result = self._capture_packet()
        review, view = self._open_review(packet)
        self.assertTrue(set(view) <= VIEW_KEYS)
        blob = json.dumps({key: value for key, value in view.items() if key not in {"bestObservation", "otherObservations"}})
        self.assertNotIn("relativePath", blob)
        self.assertNotIn("bbox", blob)
        self.assertNotIn("sha256", blob)
        self.assertNotIn("Quality", blob)
        self.assertNotIn("recordStableKey", view)
        self.assertNotEqual(view.get("recordAlias"), KEY)
        chosen, others = self._pick_multi_obs(review, packet)
        self.assertTrue(_is_real_crop(chosen["bestObservation"]["imageDataUrl"]))
        self.assertTrue(_is_real_crop(others[0]["imageDataUrl"]))
        before_candidates = [item["candidateId"] for item in chosen["candidates"]]
        switched = review.select_observation(str(others[0]["observationId"]))
        self.assertEqual(switched["currentTrackId"], chosen["currentTrackId"])
        self.assertEqual(switched["draftAction"], chosen["draftAction"])
        self.assertIsNone(switched["draftAction"])
        self.assertEqual([item["candidateId"] for item in switched["candidates"]], before_candidates)
        self.assertEqual(switched["bestObservation"]["observationId"], others[0]["observationId"])
        self.assertTrue(_is_real_crop(switched["bestObservation"]["imageDataUrl"]))
        self.assertGreaterEqual(len(chosen["otherObservations"]) + 1, 2)
        self.track_count = chosen["trackCount"]
        self.obs_count = 1 + len(chosen["otherObservations"])

    def test_missing_evidence_and_reason_gate(self):
        packet, _result = self._capture_packet()
        review, view = self._open_review(packet, store=None)
        self.assertFalse(view["hasLegalEvidence"])
        self.assertFalse(view["bestObservation"]["imageAvailable"])
        self.assertIsNone(view["bestObservation"]["imageDataUrl"])
        with self.assertRaises(WarehouseIdentityReviewSessionError) as raised:
            review.apply({"action": ACTION_CONFIRM, "selectedCatalogId": "x", "confirmCandidate": True})
        self.assertEqual(raised.exception.code, "EVIDENCE_UNAVAILABLE")
        live, _ = self._open_review(packet)
        with self.assertRaises(WarehouseIdentityReviewSessionError) as flagged:
            live.apply({"action": ACTION_FLAG})
        self.assertEqual(flagged.exception.code, "REASON_REQUIRED")
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        self.assertIn('id="wir-reason-box" hidden', html)
        self.assertIn("wir-primary", html)
        self.assertIn("明确确认此候选", html)
        self.assertIn("尚未写入历史记录", html)
        self.assertIn("wirRevealReason", js)
        self.assertIn("pendingReasonKind", js)
        self.assertNotIn("wir-thumb-missing", js)
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        self.assertIsNotNone(get_production_scroll_driver())

    def test_real_layout_screenshots(self):
        from playwright.sync_api import sync_playwright

        packet, _result = self._capture_packet()
        review, _view = self._open_review(packet)
        chosen, others = self._pick_multi_obs(review, packet)
        if chosen["candidates"]:
            chosen = review.select_candidate(str(chosen["candidates"][0]["candidateId"]))
        self.assertTrue(_is_real_crop(chosen["bestObservation"]["imageDataUrl"]))
        self.assertTrue(_is_real_crop(others[0]["imageDataUrl"]))
        payload = {
            "coverageStatus": chosen["coverageStatus"],
            "coverageCaption": chosen["coverageCaption"],
            "processedCount": chosen["processedCount"],
            "unresolvedCount": chosen["unresolvedCount"],
            "trackCount": chosen["trackCount"],
            "trackIndex": chosen["trackIndex"],
            "persistenceCaption": chosen["persistenceCaption"],
            "geometryStatus": chosen["geometryStatus"],
            "clipped": chosen["clipped"],
            "bestObservation": {
                "imageAvailable": True,
                "imageDataUrl": chosen["bestObservation"]["imageDataUrl"],
            },
            "otherObservations": [
                {"imageAvailable": True, "imageDataUrl": item["imageDataUrl"]}
                for item in chosen["otherObservations"]
                if item.get("imageAvailable") and item.get("imageDataUrl")
            ],
            "candidates": chosen["candidates"][:4],
        }
        html = _panel_html()
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        wide = SHOT_DIR / "wide_1280x800.png"
        narrow = SHOT_DIR / "narrow_720x900.png"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content(html, wait_until="load")
            _fill_real_view(page, payload)
            self.assertFalse(page.evaluate("() => [...document.querySelectorAll('button,.wir-thumb-missing')].some((n) => (n.textContent || '').trim() === '不可用')"))
            self.assertTrue(page.evaluate("() => document.getElementById('wir-reason-box').hidden"))
            self.assertIn("尚未写入历史记录", page.inner_text("#wir-persist"))
            self.assertFalse(page.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"))
            page.screenshot(path=str(wide), full_page=True)
            page.set_viewport_size({"width": 720, "height": 900})
            self.assertFalse(page.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"))
            page.screenshot(path=str(narrow), full_page=True)
            browser.close()
        self.assertGreaterEqual(wide.stat().st_size, 20000)
        self.assertGreaterEqual(narrow.stat().st_size, 20000)


if __name__ == "__main__":
    unittest.main()
