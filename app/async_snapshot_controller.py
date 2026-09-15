"""Async Triggered Snapshot Controller v1.

Offloads frame capture, RapidOCR recognition, and draft state merging to a single-flight
background worker thread, keeping the WinForms UI thread unblocked and responsive.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class AsyncTriggeredSnapshotController:
    """Manages single-flight asynchronous triggered snapshot recognition tasks."""

    def __init__(
        self,
        *,
        recognizer_factory: Optional[Callable[[], Any]] = None,
        capture_manager_factory: Optional[Callable[[], Any]] = None,
        tracker_factory: Optional[Callable[[], Any]] = None,
        state_lock: Optional[threading.Lock] = None,
        current_match_provider: Optional[Callable[[], Any]] = None,
        persist_draft_callback: Optional[Callable[[], None]] = None,
        publish_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
        payload_builder: Optional[Callable[[], Dict[str, Any]]] = None,
        target_titles: Optional[list] = None,
        window_validator: Optional[Callable[[int], bool]] = None,
    ):
        self._recognizer_factory = recognizer_factory
        self._capture_manager_factory = capture_manager_factory
        self._tracker_factory = tracker_factory
        self._state_lock = state_lock or threading.Lock()
        self._current_match_provider = current_match_provider
        self._persist_draft_callback = persist_draft_callback
        self._publish_callback = publish_callback
        self._payload_builder = payload_builder
        self._target_titles = target_titles or ["异环"]
        self._window_validator = window_validator

        self._lock = threading.Lock()
        self._in_flight = False
        self._last_result: Optional[Dict[str, Any]] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._recognizer = None

    @property
    def in_flight(self) -> bool:
        with self._lock:
            return self._in_flight

    def _is_window_valid(self, hwnd: int) -> bool:
        if not hwnd or int(hwnd) <= 0:
            return False
        if self._window_validator is not None:
            return bool(self._window_validator(hwnd))
        try:
            import win32gui
            return bool(win32gui.IsWindow(hwnd))
        except Exception:
            return True

    def request_snapshot(self) -> Dict[str, Any]:
        """Trigger an asynchronous snapshot recognition task.

        Returns immediately with 'recognizing' if accepted, or 'busy' if already running.
        """
        captured_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with self._lock:
            if self._in_flight:
                return {
                    "type": "snapshot_assist_result",
                    "ok": False,
                    "status": "busy",
                    "capturedAt": captured_at,
                    "appliedFactCount": 0,
                    "conflictCount": 0,
                    "summary": "正在识别中，请稍候…",
                }

            match = self._current_match_provider() if self._current_match_provider else None
            match_id = getattr(match, "id", None)
            match_inst = match

            self._in_flight = True
            thread = threading.Thread(
                target=self._worker_entry,
                args=(match_inst, match_id),
                name="async-triggered-snapshot",
                daemon=True,
            )
            self._worker_thread = thread
            thread.start()

            response = {
                "type": "snapshot_assist_result",
                "ok": True,
                "status": "recognizing",
                "capturedAt": captured_at,
                "appliedFactCount": 0,
                "conflictCount": 0,
                "summary": "正在快照识别游戏画面...",
            }
            self._last_result = response
            return response

    def _get_recognizer(self):
        if self._recognizer_factory:
            return self._recognizer_factory()
        from snapshot_recognizer import SingleFrameSnapshotRecognizer

        if self._recognizer is None:
            self._recognizer = SingleFrameSnapshotRecognizer(include_card_evidence=False, focused=True)
        return self._recognizer

    def _get_capture_manager(self):
        if self._capture_manager_factory:
            return self._capture_manager_factory()
        from window_capture import WindowCaptureManager

        return WindowCaptureManager()

    def _get_tracker(self):
        if self._tracker_factory:
            return self._tracker_factory()
        from window_tracker import GameWindowTracker

        return GameWindowTracker(target_titles=self._target_titles)

    def _is_image_valid(self, img: Any) -> bool:
        if img is None:
            return False
        if hasattr(img, "size"):
            sz = getattr(img, "size")
            if isinstance(sz, (int, float)):
                return sz > 0
            if isinstance(sz, (tuple, list)):
                return all(x > 0 for x in sz)
        if hasattr(img, "shape"):
            return all(x > 0 for x in img.shape)
        if hasattr(img, "__len__"):
            return len(img) > 0
        return True

    def _worker_entry(self, target_match: Any, target_match_id: Optional[str]) -> None:
        try:
            captured_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            
            # 1. Locate game window
            try:
                tracker = self._get_tracker()
                hwnd = tracker.find_game_window() if tracker else 0
                if not self._is_window_valid(hwnd):
                    self._finish(
                        target_match,
                        target_match_id,
                        {
                            "type": "snapshot_assist_result",
                            "ok": False,
                            "status": "failed",
                            "capturedAt": captured_at,
                            "appliedFacts": {},
                            "conflicts": [],
                            "summary": "未检测到《异环》游戏运行窗口",
                        },
                    )
                    return
            except Exception as exc:
                logger.warning(f"Window tracker failed in snapshot worker: {exc}")
                self._finish(
                    target_match,
                    target_match_id,
                    {
                        "type": "snapshot_assist_result",
                        "ok": False,
                        "status": "failed",
                        "capturedAt": captured_at,
                        "appliedFacts": {},
                        "conflicts": [],
                        "summary": f"窗口定位失败: {exc}",
                    },
                )
                return

            # 2. Capture game client frame
            try:
                capture_mgr = self._get_capture_manager()
                img, source = capture_mgr.capture_game_client(hwnd)
                if not self._is_image_valid(img):
                    self._finish(
                        target_match,
                        target_match_id,
                        {
                            "type": "snapshot_assist_result",
                            "ok": False,
                            "status": "failed",
                            "capturedAt": captured_at,
                            "appliedFacts": {},
                            "conflicts": [],
                            "summary": "游戏画面截取失败或为空白",
                        },
                    )
                    return
            except Exception as exc:
                logger.warning(f"Capture failed in snapshot worker: {exc}")
                self._finish(
                    target_match,
                    target_match_id,
                    {
                        "type": "snapshot_assist_result",
                        "ok": False,
                        "status": "failed",
                        "capturedAt": captured_at,
                        "appliedFacts": {},
                        "conflicts": [],
                        "summary": f"截图截取异常: {exc}",
                    },
                )
                return

            # 3. Perform OCR recognition
            try:
                recognizer = self._get_recognizer()
                existing_facts = dict(getattr(target_match, "facts", {})) if target_match else {}
                res = recognizer.process_frame(img, existing_facts=existing_facts)
                res["status"] = "completed" if res.get("ok") else "failed"
                res["capturedAt"] = captured_at
                self._finish(target_match, target_match_id, res)
            except Exception as exc:
                logger.error(f"Snapshot recognizer crashed: {exc}", exc_info=True)
                self._finish(
                    target_match,
                    target_match_id,
                    {
                        "type": "snapshot_assist_result",
                        "ok": False,
                        "status": "failed",
                        "capturedAt": captured_at,
                        "appliedFacts": {},
                        "conflicts": [],
                        "summary": f"识别计算异常: {exc}",
                    },
                )
        finally:
            with self._lock:
                self._in_flight = False

    def _finish(self, target_match: Any, target_match_id: Optional[str], result: Dict[str, Any]) -> None:
        with self._state_lock:
            curr_match = self._current_match_provider() if self._current_match_provider else None
            curr_id = getattr(curr_match, "id", None)

            # Cross-match safety check: discard if match identity changed
            if curr_match is not target_match or curr_id != target_match_id:
                logger.info(
                    f"Snapshot result discarded due to match identity change: "
                    f"target={target_match_id} current={curr_id}"
                )
                return

            applied_facts = result.get("appliedFacts") or {}
            if result.get("ok") and applied_facts and curr_match:
                curr_match.apply_facts(applied_facts, source="triggered_snapshot")
                if self._persist_draft_callback:
                    try:
                        self._persist_draft_callback()
                    except Exception as exc:
                        logger.warning(f"Persist draft failed: {exc}")

            applied_count = len(applied_facts)
            conflict_count = len(result.get("conflicts") or [])
            ok = bool(result.get("ok"))
            if ok:
                summary = f"快照识别完成：应用 {applied_count} 项事实"
                if conflict_count:
                    summary += f"，保留 {conflict_count} 项手动输入冲突"
            else:
                raw_summary = str(result.get("summary") or "")
                if "未检测到" in raw_summary and "游戏" in raw_summary:
                    summary = "未检测到游戏运行窗口"
                elif "截取失败" in raw_summary or "为空白" in raw_summary:
                    summary = "游戏画面截取失败"
                elif raw_summary:
                    summary = raw_summary
                else:
                    summary = "本次快照未提取到可用事实"

            presentation_result = {
                "type": "snapshot_assist_result",
                "ok": ok,
                "status": result.get("status") or ("completed" if ok else "failed"),
                "capturedAt": result.get("capturedAt"),
                "appliedFactCount": applied_count,
                "conflictCount": conflict_count,
                "summary": summary,
            }
            self._last_result = presentation_result

            if self._payload_builder:
                payload = self._payload_builder()
            else:
                payload = {}
            payload["snapshotResult"] = presentation_result
            if self._publish_callback:
                try:
                    self._publish_callback(payload)
                except Exception as exc:
                    logger.warning(f"Publish snapshot payload failed: {exc}")
