"""Manual warehouse-capture command host.

Owns at most one background 4B2A session. Start/stop are native-only and
never accept client descriptors, paths, hashes, HWND, or Store/Ledger
authority. Production wheel driver stays disabled unless a test injects a
fake factory and an explicit driver_available flag.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
from pathlib import Path
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

PRESENTATION_KEYS = (
    "available",
    "state",
    "segmentCount",
    "coverageStatus",
    "stopAvailable",
    "message",
    "terminationReason",
    "disabledReason",
    "packetAvailable",
    "packetStatus",
    "packetFingerprint",
    "reviewStatus",
)

STATE_IDLE = "IDLE"
STATE_STARTING = "STARTING"
STATE_WAITING_FOR_GAME_FOCUS = "WAITING_FOR_GAME_FOCUS"
STATE_CAPTURING = "CAPTURING"
STATE_SCROLLING = "SCROLLING"
STATE_WAITING = "WAITING"
STATE_ALIGNING = "ALIGNING"
STATE_COMPLETE = "COMPLETE"
STATE_PARTIAL = "PARTIAL"
STATE_START_REQUIRES_TOP = "START_REQUIRES_TOP"
STATE_DRIVER_NOT_CONFIGURED = "DRIVER_NOT_CONFIGURED"
STATE_ERROR = "ERROR"
STATE_MANUAL_CAPTURING = "MANUAL_CAPTURING"
TOTAL_SETTLEMENT_BUDGET_S = 70.0

RUNNING_STATES = frozenset(
    {STATE_STARTING, STATE_WAITING_FOR_GAME_FOCUS, STATE_CAPTURING, STATE_SCROLLING, STATE_WAITING, STATE_ALIGNING, "FINALIZING", STATE_MANUAL_CAPTURING}
)

REASON_STARTED = "STARTED"
REASON_ALREADY_RUNNING = "ALREADY_RUNNING"
REASON_SCROLL_DRIVER_NOT_CONFIGURED = "SCROLL_DRIVER_NOT_CONFIGURED"
REASON_STOP_REQUESTED = "STOP_REQUESTED"
REASON_NO_SESSION = "NO_SESSION"
REASON_PREPARED = "PREPARED"
REASON_NOT_SETTLEMENT = "NOT_SETTLEMENT"
REASON_TOKEN_INVALID = "TOKEN_INVALID"
REASON_TOKEN_EXPIRED = "TOKEN_EXPIRED"
REASON_TOKEN_REUSED = "TOKEN_REUSED"
REASON_BINDING_CHANGED = "BINDING_CHANGED"
REASON_STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
REASON_START_REQUIRES_TOP = "START_REQUIRES_TOP"
REASON_INPUT_GUARD_FAILED = "INPUT_GUARD_FAILED"
REASON_OBSERVATION_PROFILE_READONLY = "OBSERVATION_PROFILE_READONLY"

DISABLED_REASON_GAME_NOT_DETECTED = "GAME_NOT_DETECTED"
DISABLED_REASON_SETTLEMENT_NOT_DETECTED = "SETTLEMENT_NOT_DETECTED"
DISABLED_REASON_SETTLEMENT_NOT_STABLE = "SETTLEMENT_NOT_STABLE"
DISABLED_REASON_WAREHOUSE_NOT_PRESENT = "WAREHOUSE_NOT_PRESENT"
DISABLED_REASON_RECORD_KEY_NOT_STABLE = "RECORD_KEY_NOT_STABLE"
DISABLED_REASON_SCROLL_NOT_AT_TOP = "SCROLL_NOT_AT_TOP"
DISABLED_REASON_DRIVER_NOT_AVAILABLE = "DRIVER_NOT_AVAILABLE"
DISABLED_REASON_STORE_NOT_AVAILABLE = "STORE_NOT_AVAILABLE"

DISABLED_REASON_MESSAGES = {
    DISABLED_REASON_GAME_NOT_DETECTED: "未检测到《异环》游戏窗口",
    DISABLED_REASON_SETTLEMENT_NOT_DETECTED: "未检测到结算界面",
    DISABLED_REASON_SETTLEMENT_NOT_STABLE: "结算画面尚未稳定",
    DISABLED_REASON_WAREHOUSE_NOT_PRESENT: "未确认仓库区域",
    DISABLED_REASON_RECORD_KEY_NOT_STABLE: "本局记录标识尚未稳定",
    DISABLED_REASON_SCROLL_NOT_AT_TOP: "仓库滚动条未置顶",
    DISABLED_REASON_DRIVER_NOT_AVAILABLE: "自动滚动组件不可用",
    DISABLED_REASON_STORE_NOT_AVAILABLE: "证据存储不可用",
}

CONFIRM_CAPTION = (
    "程序仅在结算页滚动仓库；按 Esc、点击、滚轮或任意按键会立即停止；"
    "不会点击、出价或返回顶部；未完整覆盖会保存为部分。"
)

MESSAGE_IDLE = "采集完整仓库"
MESSAGE_STARTING = "正在准备仓库采集"
MESSAGE_WAITING_FOR_GAME_FOCUS = "请按 Alt+Tab 返回游戏，回到游戏后自动开始"
MESSAGE_RUNNING = "仓库采集中 · 已保存 {n} 段 · 可停止"
MESSAGE_COMPLETE = "仓库覆盖完成"
MESSAGE_PARTIAL = "采集已停止 · 证据不完整"
MESSAGE_START_REQUIRES_TOP = "请先将结算仓库滚到顶部"
MESSAGE_DRIVER_NOT_CONFIGURED = "当前版本尚未启用自动滚动"
MESSAGE_ERROR = "采集未完成，已保留现有证据"


def production_scroll_driver_is_ready() -> bool:
    """Production 4B2A driver remains disabled unless both gates flip."""
    try:
        from warehouse_capture_session import (
            PRODUCTION_SCROLL_DRIVER_ENABLED,
            get_production_scroll_driver,
        )
    except Exception:
        return False
    return bool(PRODUCTION_SCROLL_DRIVER_ENABLED) and get_production_scroll_driver() is not None


def _closed_state(value: Any) -> str:
    text = str(value or STATE_IDLE).strip().upper()
    if text == "FINALIZING":
        return STATE_CAPTURING
    if text in {
        STATE_IDLE,
        STATE_STARTING,
        STATE_WAITING_FOR_GAME_FOCUS,
        STATE_CAPTURING,
        STATE_SCROLLING,
        STATE_WAITING,
        STATE_ALIGNING,
        STATE_COMPLETE,
        STATE_PARTIAL,
        STATE_START_REQUIRES_TOP,
        STATE_DRIVER_NOT_CONFIGURED,
        STATE_ERROR,
        STATE_MANUAL_CAPTURING,
    }:
        return text
    return STATE_ERROR


def _message_for(state: str, segment_count: int) -> str:
    if state == STATE_MANUAL_CAPTURING:
        return f"手动采集中 · 已保存 {max(0, int(segment_count))} 页"
    if state == STATE_IDLE:
        return MESSAGE_IDLE
    if state == STATE_STARTING:
        return MESSAGE_STARTING
    if state == STATE_WAITING_FOR_GAME_FOCUS:
        return MESSAGE_WAITING_FOR_GAME_FOCUS
    if state in RUNNING_STATES:
        return MESSAGE_RUNNING.format(n=max(0, int(segment_count)))
    if state == STATE_COMPLETE:
        return MESSAGE_COMPLETE
    if state == STATE_PARTIAL:
        return MESSAGE_PARTIAL
    if state == STATE_START_REQUIRES_TOP:
        return MESSAGE_START_REQUIRES_TOP
    if state == STATE_DRIVER_NOT_CONFIGURED:
        return MESSAGE_DRIVER_NOT_CONFIGURED
    return MESSAGE_ERROR


def _state_from_result(result: Mapping[str, Any]) -> str:
    reason = str(result.get("terminationReason") or "")
    coverage = str(result.get("coverageStatus") or "")
    if reason == "COMPLETE" or coverage == "COMPLETE":
        return STATE_COMPLETE
    if reason == "START_REQUIRES_TOP":
        return STATE_START_REQUIRES_TOP
    if reason == REASON_SCROLL_DRIVER_NOT_CONFIGURED:
        return STATE_DRIVER_NOT_CONFIGURED
    if coverage == "PARTIAL" or reason in {
        "USER_STOP",
        "USER_INPUT",
        "ESCAPE",
        "TIMEOUT",
        "WINDOW_LOST",
        "SCENE_LEFT",
        "STORE_FAILED",
        "OBSERVER_UNKNOWN",
        "OVERLAP_UNVERIFIED",
        "OVERLAP_CONFLICT",
        "CONSECUTIVE_UNCHANGED",
        "SAFETY_STEP_LIMIT",
        "STABLE_KEY_CHANGED",
        "PARTIAL",
    }:
        return STATE_PARTIAL
    if result.get("accepted") and coverage in {"PARTIAL", "COMPLETE"}:
        return STATE_PARTIAL if coverage != "COMPLETE" else STATE_COMPLETE
    return STATE_ERROR


class CaptureCancelToken:
    def __init__(self):
        self._cancelled = False
        self._reason = None
        self._lock = threading.Lock()

    def cancel(self, reason: str = "USER_STOP") -> None:
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            text = str(reason or "USER_STOP").strip().upper()
            if text not in {
                "USER_STOP",
                "USER_INPUT",
                "USER_MOUSE_MOVE",
                "ESCAPE",
                "MOUSE_BUTTON",
                "WHEEL",
                "HORIZONTAL_WHEEL",
                "KEY_DOWN",
                "USER_TAKEOVER",
            }:
                text = "USER_STOP"
            self._reason = text

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def reason(self) -> Optional[str]:
        with self._lock:
            return self._reason


@dataclass(frozen=True)
class WarehouseCapturePresentation:
    available: bool = False
    state: str = STATE_IDLE
    segment_count: int = 0
    coverage_status: str = "COVERAGE_UNPROVEN"
    stop_available: bool = False
    message: str = MESSAGE_DRIVER_NOT_CONFIGURED
    termination_reason: Optional[str] = None
    disabled_reason: Optional[str] = None
    packet_available: bool = False
    packet_status: str = "UNAVAILABLE"
    packet_fingerprint: Optional[str] = None
    review_status: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "available": bool(self.available),
            "state": self.state,
            "segmentCount": int(self.segment_count),
            "coverageStatus": self.coverage_status,
            "stopAvailable": bool(self.stop_available),
            "message": self.message,
            "terminationReason": self.termination_reason,
            "disabledReason": self.disabled_reason,
            "packetAvailable": bool(self.packet_available),
            "packetStatus": self.packet_status,
            "packetFingerprint": self.packet_fingerprint,
            "reviewStatus": self.review_status,
        }
        extra = set(payload) - set(PRESENTATION_KEYS)
        for key in extra:
            payload.pop(key, None)
        return payload


CROP_CACHE_VERSION = "v1"


class WarehouseCropRecoveryError(RuntimeError):
    """Rollback could not complete; on-disk old crops remain for recovery."""

    def __init__(self, recovery_dir: Path, failures: Sequence[str]):
        self.recovery_dir = recovery_dir
        super().__init__(f"Warehouse crop recovery required; backups: {recovery_dir}; {'; '.join(failures)}")


def _validate_and_normalize_crop_bbox(
    bbox: Any,
    img_w: int,
    img_h: int,
) -> Tuple[int, int, int, int]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise RuntimeError(f"WarehouseCaptureHost: crop bbox must be 4 elements, got: {bbox}")
    for i, v in enumerate(bbox):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)):
            raise RuntimeError(f"WarehouseCaptureHost: crop bbox element {i} is not a finite number: {v}")
    x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    if x1 < 0 or y1 < 0:
        raise RuntimeError(f"WarehouseCaptureHost: crop bbox cannot have negative coordinates: [{x1}, {y1}, {x2}, {y2}]")
    if x2 > img_w or y2 > img_h:
        raise RuntimeError(f"WarehouseCaptureHost: crop bbox [{x1}, {y1}, {x2}, {y2}] extends beyond image bounds ({img_w}x{img_h})")
    ix1 = int(round(x1))
    iy1 = int(round(y1))
    ix2 = int(round(x2))
    iy2 = int(round(y2))
    if ix2 <= ix1 or iy2 <= iy1:
        raise RuntimeError(f"WarehouseCaptureHost: crop bbox [{x1}, {y1}, {x2}, {y2}] coordinate order invalid or zero/negative area (w={ix2-ix1}, h={iy2-iy1})")
    if (ix2 - ix1) * (iy2 - iy1) <= 0:
        raise RuntimeError(f"WarehouseCaptureHost: crop bbox area must be strictly positive: w={ix2-ix1}, h={iy2-iy1}")
    return ix1, iy1, ix2, iy2


class WarehouseCaptureHost:
    def __init__(
        self,
        *,
        session_factory: Optional[Callable[..., Any]] = None,
        driver_available: bool = False,
        scene_probe: Optional[Callable[[], Mapping[str, Any]]] = None,
        input_guard_factory: Optional[Callable[..., Any]] = None,
        bindings_probe: Optional[Callable[[], Mapping[str, Any]]] = None,
        window_adapter: Optional[Any] = None,
        clock: Optional[Callable[[], float]] = None,
        token_ttl_s: float = 12.0,
        arming_required: bool = False,
        foreground_wait_timeout_s: float = 15.0,
        idle: Optional[Callable[[float], None]] = None,
        store_factory: Optional[Callable[[], Any]] = None,
        frame_provider_factory: Optional[Callable[[], Any]] = None,
        occupancy_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        history_store_factory: Optional[Callable[[], Any]] = None,
        input_execution_allowed: Optional[Callable[[], bool]] = None,
    ):
        self._session_factory = session_factory
        self._driver_available = bool(driver_available)
        self._scene_probe = scene_probe
        self._input_guard_factory = input_guard_factory
        self._bindings_probe = bindings_probe
        self._window_adapter = window_adapter
        self._clock = clock
        self._token_ttl_s = float(token_ttl_s)
        self._foreground_wait_timeout_s = float(foreground_wait_timeout_s)
        self._idle = idle if idle is not None else time.sleep
        self._store_factory = store_factory
        self._frame_provider_factory = frame_provider_factory
        self._occupancy_sink = occupancy_sink
        self._history_store_factory = history_store_factory
        self._input_execution_allowed = input_execution_allowed
        self._pending_token = None
        self._arming_required = bool(arming_required)
        self._confirmed_once = False
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cancel = CaptureCancelToken()
        self._starts = 0
        self._review_packet = None
        self._active_record_key = None
        self._resume_session = None
        self._resume_bindings = None
        self._settlement_entry_monotonics: Dict[str, float] = {}
        self._settlement_game_remainings: Dict[str, float] = {}
        self._settlement_effective_deadlines: Dict[str, float] = {}
        self._manual_mode = False
        self._manual_processing = False
        self._manual_record_key: Optional[str] = None
        self._manual_pages: List[Dict[str, Any]] = []
        self._manual_frames: Dict[str, Any] = {}
        self._presentation = self._build_presentation(
            STATE_IDLE if self.available else STATE_DRIVER_NOT_CONFIGURED,
            0,
            "COVERAGE_UNPROVEN",
            None,
        )

    @property
    def factory_ready(self) -> bool:
        return self._session_factory is not None and self._driver_available

    def _game_input_allowed(self) -> bool:
        """Fail closed when the active observation profile is read-only."""
        callback = self._input_execution_allowed
        if callback is None:
            return True
        try:
            return bool(callback())
        except Exception:
            return False

    @property
    def available(self) -> bool:
        if not self.factory_ready:
            return False
        return bool(self._running) or (self._game_input_allowed() and self._settlement_eligible())

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def start_count(self) -> int:
        with self._lock:
            return self._starts

    def presentation(self) -> WarehouseCapturePresentation:
        with self._lock:
            if not self._running and self._starts == 0:
                if self._presentation.state in {STATE_IDLE, STATE_DRIVER_NOT_CONFIGURED, STATE_START_REQUIRES_TOP}:
                    if not self.available:
                        target_state = STATE_DRIVER_NOT_CONFIGURED
                    elif self._presentation.state == STATE_START_REQUIRES_TOP:
                        snap = self._snapshot_bindings()
                        scroll = str((snap or {}).get("scrollState") or "").strip().upper()
                        if scroll in {"TOP", "NO_SCROLL"}:
                            target_state = STATE_IDLE
                        else:
                            target_state = STATE_START_REQUIRES_TOP
                    else:
                        target_state = STATE_IDLE

                    if self._presentation.state != target_state:
                        self._presentation = self._build_presentation(
                            target_state,
                            self._presentation.segment_count,
                            self._presentation.coverage_status,
                            self._presentation.termination_reason if target_state != STATE_IDLE else None,
                            packet_available=self._presentation.packet_available,
                            packet_status=self._presentation.packet_status,
                            packet_fingerprint=self._presentation.packet_fingerprint,
                            review_status=self._presentation.review_status,
                        )
            if not self._running and self._resume_session is not None:
                old = self._presentation
                self._presentation = self._build_presentation(
                    old.state, old.segment_count, old.coverage_status, old.termination_reason,
                    old.packet_available, old.packet_status, old.packet_fingerprint, old.review_status)
            return self._presentation

    def presentation_payload(self) -> Dict[str, Any]:
        return self.presentation().to_payload()

    def start(self, arming_token: Optional[Any] = None) -> Dict[str, Any]:
        with self._lock:
            if not self._game_input_allowed():
                return {"ok": False, "reason": REASON_OBSERVATION_PROFILE_READONLY}
            if self._arming_required and not self._confirmed_once:
                return {"ok": False, "reason": REASON_TOKEN_INVALID}
            self._confirmed_once = False
            if self._running or self._manual_mode or self._manual_processing:
                return {"ok": False, "reason": REASON_ALREADY_RUNNING}
            if not self.factory_ready:
                self._presentation = self._build_presentation(
                    STATE_DRIVER_NOT_CONFIGURED,
                    self._presentation.segment_count,
                    self._presentation.coverage_status,
                    REASON_SCROLL_DRIVER_NOT_CONFIGURED,
                )
                return {"ok": False, "reason": REASON_SCROLL_DRIVER_NOT_CONFIGURED}

            snap = self._snapshot_bindings()
            self._active_record_key = str((snap or {}).get("recordStableKey") or "") or None
            if self._resume_bindings and self._resume_bindings.get("recordStableKey") != self._active_record_key:
                self._resume_session = None
                self._resume_bindings = None
            if snap is not None:
                key = str(snap.get("recordStableKey") or "").strip()
                deadline = self._settlement_effective_deadlines.get(key)
                if deadline is None:
                    entry_time = self._settlement_entry_monotonics.get(key)
                    if entry_time is not None:
                        deadline = entry_time + TOTAL_SETTLEMENT_BUDGET_S
                        self._settlement_effective_deadlines[key] = deadline
                if deadline is not None and self._now() >= deadline:
                    return {"ok": False, "reason": "TIMEOUT"}

            self._cancel = CaptureCancelToken()
            self._running = True
            self._starts += 1
            self._presentation = self._build_presentation(
                STATE_STARTING, 0, "COVERAGE_UNPROVEN", None
            )
            token = self._cancel
            thread = threading.Thread(
                target=self._run_worker,
                args=(token, arming_token),
                name="warehouse-capture-session",
                daemon=True,
            )
            self._thread = thread
        thread.start()
        return {"ok": True, "reason": REASON_STARTED}

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            if not self._running:
                return {"ok": True, "reason": REASON_NO_SESSION}
            self._cancel.cancel()
            return {"ok": True, "reason": REASON_STOP_REQUESTED}

    def prepare(self) -> Dict[str, Any]:
        from warehouse_capture_arming import CONFIRM_CAPTION, issue_arming_token

        if not self._game_input_allowed():
            return {"ok": False, "reason": REASON_OBSERVATION_PROFILE_READONLY, "armingToken": None}
        if self._running:
            return {"ok": False, "reason": REASON_ALREADY_RUNNING, "armingToken": None}
        if not self.factory_ready:
            return {"ok": False, "reason": REASON_SCROLL_DRIVER_NOT_CONFIGURED, "armingToken": None}
        snap = self._snapshot_bindings()
        if snap is None or not snap.get("isSettlement") or not snap.get("stable") or not snap.get("warehousePresent", True):
            return {"ok": False, "reason": REASON_NOT_SETTLEMENT, "armingToken": None}
        if not snap.get("storeAvailable", True):
            return {"ok": False, "reason": REASON_STORE_UNAVAILABLE, "armingToken": None}
        hwnd_reason = self._hwnd_gate(snap, require_foreground=False)
        if hwnd_reason:
            return {"ok": False, "reason": hwnd_reason, "armingToken": None}

        # Monotonic settlement deadline check (70s budget from first settlement detection)
        key = str(snap.get("recordStableKey") or "").strip()
        deadline = self._settlement_effective_deadlines.get(key)
        if deadline is None:
            entry_time = self._settlement_entry_monotonics.get(key)
            if entry_time is not None:
                deadline = entry_time + TOTAL_SETTLEMENT_BUDGET_S
                self._settlement_effective_deadlines[key] = deadline
        if deadline is not None and self._now() >= deadline:
            return {
                "ok": False,
                "reason": "TIMEOUT",
                "armingToken": None,
                "message": "结算采集已过截止时间 (预算耗尽)",
            }

        scroll = str(snap.get("scrollState") or "UNKNOWN")
        if scroll not in {"TOP", "NO_SCROLL"} and not self._resume_available(snap):
            with self._lock:
                self._pending_token = None
                self._presentation = self._build_presentation(
                    STATE_START_REQUIRES_TOP,
                    self._presentation.segment_count,
                    "COVERAGE_UNPROVEN",
                    REASON_START_REQUIRES_TOP,
                )
            return {
                "ok": False,
                "reason": REASON_START_REQUIRES_TOP,
                "armingToken": None,
                "message": MESSAGE_START_REQUIRES_TOP,
            }
        now = self._now()
        token = issue_arming_token(snap, now=now, ttl_s=self._token_ttl_s)
        if token is None:
            return {"ok": False, "reason": REASON_NOT_SETTLEMENT, "armingToken": None}
        with self._lock:
            self._pending_token = token
        return {
            "ok": True,
            "reason": REASON_PREPARED,
            "armingToken": token.token_id,
            "confirmCaption": CONFIRM_CAPTION,
        }


    def prepare_manual(self) -> Dict[str, Any]:
        """Manual takeover prepare gate: requires game HWND, stable record key, store available.
        Does NOT require automatic settlementReady or stable detection.
        """
        if self._running or self._manual_mode or self._manual_processing:
            return {"ok": False, "reason": REASON_ALREADY_RUNNING}

        snap = self._snapshot_bindings() or {}
        hwnd = int(snap.get("hwnd") or snap.get("gameHwnd") or 0)
        if hwnd <= 0:
            try:
                from window_capture import WindowCaptureManager
                hwnd = int(WindowCaptureManager().find_game_hwnd() or 0)
            except Exception:
                hwnd = 0
        if hwnd <= 0:
            return {
                "ok": False,
                "reason": DISABLED_REASON_GAME_NOT_DETECTED,
                "message": DISABLED_REASON_MESSAGES[DISABLED_REASON_GAME_NOT_DETECTED],
            }

        key = str(snap.get("recordStableKey") or "").strip()
        if not key:
            try:
                from current_match import CURRENT_MATCH
                if CURRENT_MATCH and getattr(CURRENT_MATCH, "id", None):
                    key = str(CURRENT_MATCH.id).strip()
            except Exception:
                pass
        if not key:
            try:
                from main import CURRENT_MATCH
                if CURRENT_MATCH and getattr(CURRENT_MATCH, "id", None):
                    key = str(CURRENT_MATCH.id).strip()
            except Exception:
                pass
        if not key:
            return {
                "ok": False,
                "reason": DISABLED_REASON_RECORD_KEY_NOT_STABLE,
                "message": DISABLED_REASON_MESSAGES[DISABLED_REASON_RECORD_KEY_NOT_STABLE],
            }

        if snap.get("storeAvailable") is False:
            return {
                "ok": False,
                "reason": DISABLED_REASON_STORE_NOT_AVAILABLE,
                "message": DISABLED_REASON_MESSAGES[DISABLED_REASON_STORE_NOT_AVAILABLE],
            }

        return {
            "ok": True,
            "reason": "MANUAL_READY",
            "recordStableKey": key,
            "confirmCaption": "请确认当前为结算仓库界面。确认后可在游戏中自行滚动，连续截取多页，最后点击“完成采集”生成仓库审阅包。",
        }

    def start_manual(self, record_key: Optional[str] = None) -> Dict[str, Any]:
        """Enter manual takeover capture mode."""
        with self._lock:
            if self._running or self._manual_processing:
                return {"ok": False, "reason": REASON_ALREADY_RUNNING}
            prep = self.prepare_manual()
            if not prep.get("ok"):
                return prep
            self._manual_mode = True
            self._manual_record_key = str(record_key or prep.get("recordStableKey") or "").strip()
            self._manual_pages = []
            self._manual_frames = {}
            self._presentation = self._build_presentation(
                STATE_MANUAL_CAPTURING,
                0,
                "COVERAGE_UNPROVEN",
                None,
                message="手动采集中 · 已保存 0 页",
            )
            return {"ok": True, "pageCount": 0, "message": "手动采集中 · 已保存 0 页"}

    def capture_manual_page(self) -> Dict[str, Any]:
        """Capture one page from game window in manual takeover mode."""
        with self._lock:
            if not self._manual_mode:
                return {"ok": False, "reason": "NOT_IN_MANUAL_MODE", "message": "当前未处于手动采集模式"}

            frame_provider = self._frame_provider_factory() if self._frame_provider_factory else None
            frame = frame_provider() if callable(frame_provider) else None
            if frame is None or getattr(frame, "size", 0) == 0:
                try:
                    from window_capture import WindowCaptureManager
                    mgr = WindowCaptureManager()
                    hwnd = mgr.find_game_hwnd()
                    if hwnd:
                        frame, _ = mgr.capture_game_client(hwnd)
                except Exception:
                    frame = None

            if frame is None or getattr(frame, "size", 0) == 0:
                return {"ok": False, "reason": "CAPTURE_FAILED", "message": "画面截取失败"}

            from settlement_stable_frame_persist import encode_settlement_original
            from datetime import datetime
            image_bytes = encode_settlement_original(frame)
            digest = hashlib.sha256(image_bytes).hexdigest()

            # Duplicate rejection against every already accepted source image
            if any(page.get("sha256") == digest for page in self._manual_pages):
                return {
                    "ok": True,
                    "duplicate": True,
                    "pageCount": len(self._manual_pages),
                    "message": f"该截图已采集，未重复追加；已保存 {len(self._manual_pages)} 页",
                }

            # A page is accepted only after its immutable original is saved
            # and verified. Keep the Store descriptor intact; sequence is a
            # separate ledger argument, never an original-evidence field.
            try:
                from settlement_truth_evidence_contract import validate_settlement_evidence_original_v2
                store = self._store_factory() if self._store_factory else None
                if store is None or not callable(getattr(store, "save_original", None)) or not callable(getattr(store, "verify", None)):
                    raise RuntimeError("STORE_UNAVAILABLE")
                page_desc = store.save_original(
                    record_stable_key=self._manual_record_key,
                    kind="warehouse-segment",
                    image_bytes=image_bytes,
                    captured_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                    coverage_mode="viewport-segment",
                    coverage_status="COVERAGE_UNPROVEN",
                )
                valid, reasons = validate_settlement_evidence_original_v2(page_desc)
                if (not valid or page_desc.get("sha256") != digest
                        or page_desc.get("recordStableKey") != self._manual_record_key
                        or page_desc.get("kind") != "warehouse-segment"
                        or not store.verify(page_desc).get("ok")):
                    raise ValueError("ORIGINAL_NOT_VERIFIED: " + ",".join(reasons))
            except Exception as exc:
                logger.warning("manual original was not accepted: %s", exc)
                message = "原图保存失败，未追加页面；已保存页面保持可用"
                self._presentation = self._build_presentation(
                    STATE_MANUAL_CAPTURING, len(self._manual_pages),
                    "COVERAGE_UNPROVEN", "STORE_FAILED", message=message,
                )
                return {"ok": False, "reason": "STORE_FAILED", "pageCount": len(self._manual_pages),
                        "message": message}

            self._manual_pages.append(page_desc)
            self._manual_frames[page_desc["evidenceId"]] = frame

            self._presentation = self._build_presentation(
                STATE_MANUAL_CAPTURING,
                len(self._manual_pages),
                "COVERAGE_UNPROVEN",
                None,
                message=f"手动采集中 · 已保存 {len(self._manual_pages)} 页",
            )
            return {"ok": True, "pageCount": len(self._manual_pages), "message": f"已采集 {len(self._manual_pages)} 页"}

    def finish_manual_capture(self) -> Dict[str, Any]:
        """Finish manual multi-page capture and trigger asynchronous pipeline processing."""
        with self._lock:
            if not self._manual_mode:
                return {"ok": False, "reason": "NOT_IN_MANUAL_MODE", "message": "当前未处于手动采集模式"}
            if not self._manual_pages:
                return {"ok": False, "reason": "NO_PAGES", "message": "尚未采集任何页面"}

            pages = list(self._manual_pages)
            frames = dict(self._manual_frames)
            record_key = self._manual_record_key

            self._manual_mode = False
            self._manual_processing = True
            self._presentation = self._build_presentation(
                STATE_ALIGNING,
                len(pages),
                "COVERAGE_UNPROVEN",
                None,
                message=f"{len(pages)}页处理中…",
            )

            th = threading.Thread(
                target=self._run_manual_processing,
                args=(record_key, pages, frames),
                name="warehouse-manual-processing",
                daemon=True,
            )
            try:
                th.start()
            except Exception:
                self._manual_processing = False
                raise
            return {"ok": True, "pageCount": len(pages), "message": f"{len(pages)}页处理中…"}

    def cancel_manual_capture(self) -> Dict[str, Any]:
        """Cancel manual takeover."""
        with self._lock:
            if self._manual_processing:
                return {"ok": False, "reason": REASON_ALREADY_RUNNING,
                        "message": "页面处理中，未取消；已保存原图保持可用"}
            self._manual_mode = False
            self._manual_pages = []
            self._manual_frames = {}
            self._presentation = self._build_presentation(
                STATE_IDLE if self.available else STATE_DRIVER_NOT_CONFIGURED,
                0,
                "COVERAGE_UNPROVEN",
                None,
            )
            return {"ok": True, "reason": "USER_CANCEL"}

    def _run_manual_processing(
        self,
        record_key: str,
        pages: List[Dict[str, Any]],
        frames: Dict[str, Any],
    ) -> None:
        # Reload the verified immutable originals, rather than mutable capture
        # buffers. Manual and saved-image entry points share the same pipeline.
        try:
            self._process_saved_pages(record_key, pages)
        except Exception as exc:
            logger.exception("WarehouseCaptureHost: manual processing error: %s", exc)
            self._saved_pages_failure(len(pages), "PROCESSING_FAILED", str(exc))
        finally:
            with self._lock:
                self._manual_processing = False

    def _saved_pages_failure(self, page_count: int, reason: str, error: str) -> Dict[str, Any]:
        message = "采集处理未完成，尚未保存本局记录；已保存原图保持可用"
        with self._lock:
            self._presentation = self._build_presentation(
                STATE_ERROR, page_count, "COVERAGE_UNPROVEN", reason, message=message,
            )
        return {"ok": False, "reason": reason, "pageCount": page_count,
                "persisted": False, "error": error[:240], "message": message}

    def _process_saved_pages(
        self,
        record_key: str,
        pages: Sequence[Mapping[str, Any]],
        *,
        history_store: Optional[Any] = None,
        already_cropped: bool = False,
        finalization_reason: str = 'COMPLETE',
    ) -> Dict[str, Any]:
        """Consume Store originals; coverage and physical identity have separate proofs."""
        import cv2
        import numpy as np
        from warehouse_catalog_geometry import CatalogGeometryIndex
        from warehouse_capture_production import get_production_placement_resolver
        from warehouse_coverage_ledger import WarehouseCoverageLedger
        from warehouse_reconstruction import WarehouseReconstructionProcessor
        from warehouse_scrollbar_observation import WarehouseScrollbarObserver, warehouse_search_roi
        from warehouse_segment_overlap import align_warehouse_segments, DIR_DOWN
        from warehouse_support_frame import stationary_support_proof
        from warehouse_auto_confirmation import evaluate_auto_confirmation
        from warehouse_identity_review import CatalogAuthority, build_auto_identity_review_artifact
        from settlement_truth_evidence_contract import validate_settlement_evidence_original_v2

        evidence_store = self._store_factory() if self._store_factory else None
        if evidence_store is None or not callable(getattr(evidence_store, "load_original", None)):
            raise RuntimeError("STORE_UNAVAILABLE")
        catalog_path = Path(__file__).resolve().parents[1] / "assets/catalog_065.json"
        catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))
        proc = WarehouseReconstructionProcessor(
            record_key, catalog_index=CatalogGeometryIndex(catalog_data),
            placement_resolver=get_production_placement_resolver(),
        )
        ledger = WarehouseCoverageLedger(record_key)
        observer = WarehouseScrollbarObserver()
        accepted_pages = []
        seen_hashes, seen_pixels = set(), set()
        ids = {}
        previous = None
        for supplied in pages:
            desc = dict(supplied)
            valid, reasons = validate_settlement_evidence_original_v2(desc)
            if not valid or desc.get("recordStableKey") != record_key or desc.get("kind") != "warehouse-segment":
                raise ValueError("INVALID_ORIGINAL: " + ",".join(reasons))
            seg_id, digest = desc["evidenceId"], desc["sha256"]
            if seg_id in ids and ids[seg_id] != digest:
                raise ValueError("SOURCE_HASH_CONFLICT")
            ids[seg_id] = digest
            payload = evidence_store.load_original(desc)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError("SOURCE_HASH_MISMATCH")
            frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None or frame.shape[:2] != (desc["height"], desc["width"]):
                raise ValueError("SOURCE_FRAME_SIZE_MISMATCH")
            pixel_digest = hashlib.sha256(frame.tobytes()).hexdigest()
            if digest in seen_hashes or pixel_digest in seen_pixels:
                continue
            seen_hashes.add(digest)
            seen_pixels.add(pixel_digest)
            sequence = len(accepted_pages)
            observation = observer.observe(frame, source_id=seg_id, already_cropped=already_cropped)
            if already_cropped:
                crop = frame
            else:
                x1, y1, x2, y2 = warehouse_search_roi(desc["width"], desc["height"])
                crop = frame[y1:y2, x1:x2]
            coverage_link, physical_link = None, None
            if previous is not None:
                prev_crop, prev_desc = previous
                alignment = align_warehouse_segments(
                    prev_crop, crop, prev_id=prev_desc["evidenceId"],
                    next_id=seg_id, required_direction=DIR_DOWN,
                )
                offset = alignment.get("verticalOffsetPx")
                verified_motion = (alignment.get("status") == "VERIFIED"
                                   and alignment.get("direction") == DIR_DOWN
                                   and isinstance(offset, (int, float)) and not isinstance(offset, bool)
                                   and math.isfinite(offset) and offset < 0)
                proof = alignment if verified_motion else stationary_support_proof(prev_crop, crop)
                if proof is not None:
                    coverage_link = {
                        "trusted": True, "aligned": True,
                        "proofId": proof.get("progressionProofId") or proof.get("proofId")
                                   or f"overlap:{prev_desc['sha256']}:{digest}",
                        "previousEvidenceId": prev_desc["evidenceId"],
                    }
                    # A stationary support frame may preserve the same origin;
                    # only VERIFIED pixel motion can move a global instance.
                    physical_link = {**proof, **coverage_link}
            state = observation.get("scrollState")
            top = {"trusted": True, "proofId": f"top:{digest}"} if state in {"TOP", "NO_SCROLL"} else None
            bottom = {"trusted": True, "proofId": f"bottom:{digest}"} if state in {"BOTTOM", "NO_SCROLL"} else None
            ledger.add_segment(desc, sequence_index=sequence, top_proof=top,
                               bottom_proof=bottom, overlap_proof=coverage_link)
            intake = proc.accept_segment(frame, desc, sequence, observation, physical_link,
                                         already_cropped=already_cropped)
            if not intake.get("accepted"):
                raise ValueError("RECONSTRUCTION_REJECTED: " + str(intake.get("reason")))
            accepted_pages.append(desc)
            previous = (crop, desc)
        if not accepted_pages:
            raise ValueError("NO_PAGES")
        coverage = ledger.finalize(finalization_reason)
        proc.finalize(coverage)
        packet = proc.packet_copy()
        if packet is None:
            raise RuntimeError("BUILD_PACKET_FAILED")
        units = evaluate_auto_confirmation(packet.get("reviewUnits", []), segments=accepted_pages)
        identity_review = build_auto_identity_review_artifact(packet, units, catalog=CatalogAuthority(catalog_data))
        persisted, persist_error = None, None
        try:
            store = history_store if history_store is not None else (
                self._history_store_factory() if self._history_store_factory else None)
            if store is None:
                from canonical_history_store import CanonicalHistoryStore
                store = CanonicalHistoryStore()
            # This API validates attribution and protects current human decisions
            # under the store lock. Never bypass a rejection with a raw patch.
            persisted = store.persist_warehouse_evidence(
                record_key, review_units=units, identity_review=identity_review, review_packet=packet,
            )
            if persisted is None:
                raise RuntimeError("HISTORY_RECORD_REJECTED")
        except Exception as exc:
            persist_error = f"{type(exc).__name__}: {exc}"[:240]
            logger.warning("Warehouse review not saved for %s: %s", record_key, exc)
        if isinstance(persisted, Mapping):
            saved_settlement = persisted.get("settlement") or {}
            units = saved_settlement.get("reviewUnits", units)
            identity_review = saved_settlement.get("warehouseIdentityReview", identity_review)
        total_slots = len(units)
        confirmed_count = sum(unit.get("confirmationStatus") == "CONFIRMED" for unit in units)
        counts = f"{total_slots} 个槽位 / {confirmed_count} 已确认 / {total_slots - confirmed_count} 待确认"
        message = (f"已生成审阅包，尚未保存本局记录；{counts}" if persist_error
                   else f"已写入本局记录；{counts}")
        with self._lock:
            self._review_packet = packet
            self._presentation = self._build_presentation(
                STATE_ERROR if persist_error else (STATE_COMPLETE if coverage["coverageStatus"] == "COMPLETE" else STATE_PARTIAL),
                len(accepted_pages), coverage["coverageStatus"],
                "HISTORY_NOT_SAVED" if persist_error else coverage["terminationReason"],
                packet_available=True, packet_status="READY",
                packet_fingerprint=packet.get("sourceFingerprint"), review_status="READY", message=message,
            )
        return {
            "ok": persist_error is None, "reason": "HISTORY_NOT_SAVED" if persist_error else coverage["terminationReason"],
            "recordStableKey": record_key, "pageCount": len(accepted_pages),
            "coverageStatus": coverage["coverageStatus"], "coverage": coverage,
            "totalSlots": total_slots, "confirmedCount": confirmed_count,
            "unconfirmedCount": total_slots - confirmed_count,
            "packet": packet, "identityReview": identity_review,
            "persisted": persist_error is None, "error": persist_error, "message": message,
        }

    def process_capture_images(
        self,
        record_key: str,
        images: Sequence[Any],
        *,
        history_store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Save supplied images as immutable originals, then use the manual pipeline."""
        import cv2
        import numpy as np
        from settlement_evidence_store_v2 import detect_image_type
        from settlement_stable_frame_persist import encode_settlement_original
        pages = []
        with self._lock:
            if self._running or self._manual_mode or self._manual_processing:
                return {"ok": False, "reason": REASON_ALREADY_RUNNING, "persisted": False}
            self._manual_processing = True
            self._presentation = self._build_presentation(
                STATE_ALIGNING, 0, "COVERAGE_UNPROVEN", None,
                message="正在校验图片并生成仓库审阅包",
            )
        try:
            evidence_store = self._store_factory() if self._store_factory else None
            if evidence_store is None or not callable(getattr(evidence_store, "save_original", None)):
                raise RuntimeError("STORE_UNAVAILABLE")
            for image in images:
                if isinstance(image, (str, Path)):
                    payload = Path(image).read_bytes()
                    if detect_image_type(payload) is None:
                        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if frame is None:
                            raise ValueError("INVALID_IMAGE")
                        payload = encode_settlement_original(frame)
                elif isinstance(image, np.ndarray):
                    payload = encode_settlement_original(image)
                else:
                    raise ValueError("INVALID_IMAGE")
                pages.append(evidence_store.save_original(
                    record_stable_key=record_key, kind="warehouse-segment", image_bytes=payload,
                    coverage_mode="viewport-segment", coverage_status="COVERAGE_UNPROVEN",
                    evidence_origin="user-import",
                ))
            return self._process_saved_pages(record_key, pages, history_store=history_store)
        except Exception as exc:
            logger.warning("Warehouse saved-image intake failed: %s", exc)
            return self._saved_pages_failure(len(pages), "PROCESSING_FAILED", str(exc))
        finally:
            with self._lock:
                self._manual_processing = False

    def _resume_available(self, snap) -> bool:
        previous = self._resume_session
        bindings = self._resume_bindings
        if not previous or not bindings or not snap or snap.get("scrollState") != "MIDDLE":
            return False
        if any(snap.get(field) != bindings.get(field) for field in
               ("recordStableKey", "hwnd", "warehouseRoi", "scene")):
            return False
        return bool(previous.can_resume(str(snap.get("recordStableKey") or "")))

    def confirm(self, token_id: str) -> Dict[str, Any]:
        from warehouse_capture_arming import bindings_match

        if not self._game_input_allowed():
            return {"ok": False, "reason": REASON_OBSERVATION_PROFILE_READONLY}
        with self._lock:
            pending = self._pending_token
        if pending is None:
            return {"ok": False, "reason": REASON_TOKEN_INVALID}
        if str(token_id or "") != pending.token_id:
            return {"ok": False, "reason": REASON_TOKEN_INVALID}
        if pending.consumed:
            return {"ok": False, "reason": REASON_TOKEN_REUSED}
        if pending.expired(self._now()):
            with self._lock:
                if self._pending_token is pending:
                    self._pending_token = None
            return {"ok": False, "reason": REASON_TOKEN_EXPIRED}
        snap = self._snapshot_bindings()
        if snap is None or not bindings_match(pending, snap):
            with self._lock:
                if self._pending_token is pending:
                    self._pending_token = None
            return {"ok": False, "reason": REASON_BINDING_CHANGED}
        hwnd_reason = self._hwnd_gate(snap, require_foreground=False)
        if hwnd_reason:
            return {"ok": False, "reason": hwnd_reason}
        if not pending.consume():
            return {"ok": False, "reason": REASON_TOKEN_REUSED}
        with self._lock:
            if self._pending_token is pending:
                self._pending_token = None
            self._confirmed_once = True
        return self.start(arming_token=pending)

    def _now(self) -> float:
        clock = self._clock
        if clock is None:
            return time.monotonic()
        if callable(clock):
            return float(clock())
        return time.monotonic()

    def _evaluate_disabled_reason(self) -> tuple[Optional[str], Optional[str]]:
        if not self.factory_ready:
            return DISABLED_REASON_DRIVER_NOT_AVAILABLE, DISABLED_REASON_MESSAGES[DISABLED_REASON_DRIVER_NOT_AVAILABLE]
        snap = self._snapshot_bindings()
        hwnd = 0
        if snap is not None:
            hwnd = int(snap.get("hwnd") or snap.get("gameHwnd") or 0)
        if hwnd <= 0:
            try:
                from window_capture import WindowCaptureManager
                hwnd = int(WindowCaptureManager().find_game_hwnd() or 0)
            except Exception:
                hwnd = 0
        if hwnd <= 0:
            return DISABLED_REASON_GAME_NOT_DETECTED, DISABLED_REASON_MESSAGES[DISABLED_REASON_GAME_NOT_DETECTED]
        if snap is None:
            return DISABLED_REASON_SETTLEMENT_NOT_DETECTED, DISABLED_REASON_MESSAGES[DISABLED_REASON_SETTLEMENT_NOT_DETECTED]
        if snap.get("storeAvailable") is False:
            return DISABLED_REASON_STORE_NOT_AVAILABLE, DISABLED_REASON_MESSAGES[DISABLED_REASON_STORE_NOT_AVAILABLE]
        scene = str(snap.get("scene") or "").strip().upper()
        if not snap.get("isSettlement") or (scene and scene != "SETTLEMENT" and not snap.get("isSettlement")):
            return DISABLED_REASON_SETTLEMENT_NOT_DETECTED, DISABLED_REASON_MESSAGES[DISABLED_REASON_SETTLEMENT_NOT_DETECTED]
        if not snap.get("warehousePresent", True):
            return DISABLED_REASON_WAREHOUSE_NOT_PRESENT, DISABLED_REASON_MESSAGES[DISABLED_REASON_WAREHOUSE_NOT_PRESENT]
        if not snap.get("stable"):
            return DISABLED_REASON_SETTLEMENT_NOT_STABLE, DISABLED_REASON_MESSAGES[DISABLED_REASON_SETTLEMENT_NOT_STABLE]
        if not snap.get("recordStableKey"):
            return DISABLED_REASON_RECORD_KEY_NOT_STABLE, DISABLED_REASON_MESSAGES[DISABLED_REASON_RECORD_KEY_NOT_STABLE]
        scroll_state = str(snap.get("scrollState") or "").strip().upper()
        if scroll_state not in ("TOP", "NO_SCROLL") and not self._resume_available(snap):
            return DISABLED_REASON_SCROLL_NOT_AT_TOP, DISABLED_REASON_MESSAGES[DISABLED_REASON_SCROLL_NOT_AT_TOP]
        return None, None

    def _settlement_eligible(self) -> bool:
        if self._bindings_probe is None and self._scene_probe is None:
            return True
        snap = self._snapshot_bindings()
        if not snap:
            return False
        if not snap.get("isSettlement") or not snap.get("stable") or not snap.get("warehousePresent", True):
            return False
        hwnd = int(snap.get("hwnd") or snap.get("gameHwnd") or 0)
        if hwnd <= 0:
            try:
                from window_capture import WindowCaptureManager
                hwnd = int(WindowCaptureManager().find_game_hwnd() or 0)
            except Exception:
                hwnd = 0
        if hwnd <= 0:
            return False
        if snap.get("storeAvailable") is False:
            return False
        if not snap.get("recordStableKey"):
            return False
        scroll_state = str(snap.get("scrollState") or "").strip().upper()
        if scroll_state not in ("TOP", "NO_SCROLL") and not self._resume_available(snap):
            return False
        return True

    def _snapshot_bindings(self) -> Optional[dict]:
        from warehouse_capture_arming import snapshot_bindings

        raw = None
        probe = self._bindings_probe or self._scene_probe
        if probe is None:
            return None
        try:
            raw = probe()
        except Exception:
            return None
        snap = snapshot_bindings(raw)
        self._record_settlement_scene(snap, raw)
        return snap

    def _record_settlement_scene(self, snap: Optional[Mapping[str, Any]], raw: Any = None) -> None:
        if not snap or not snap.get("isSettlement"):
            return
        key = str(snap.get("recordStableKey") or "").strip()
        if not key:
            return
        now = self._now()
        if key not in self._settlement_entry_monotonics:
            self._settlement_entry_monotonics[key] = now
            self._settlement_effective_deadlines[key] = now + TOTAL_SETTLEMENT_BUDGET_S

        # Extract countdown observation
        rem = None
        if snap.get("gameRemainingS") is not None:
            try:
                rem = float(snap.get("gameRemainingS"))
            except (TypeError, ValueError):
                pass
        elif snap.get("remainingTime") is not None:
            try:
                rem = float(snap.get("remainingTime"))
            except (TypeError, ValueError):
                pass
        elif isinstance(raw, Mapping):
            for k in ("gameRemainingS", "remainingTime", "countdown"):
                if raw.get(k) is not None:
                    try:
                        rem = float(raw[k])
                        break
                    except (TypeError, ValueError):
                        pass

        if rem is not None:
            self._settlement_game_remainings[key] = rem
            obs_deadline = now + max(0.0, rem)
            current_dl = self._settlement_effective_deadlines.get(
                key, self._settlement_entry_monotonics[key] + TOTAL_SETTLEMENT_BUDGET_S
            )
            self._settlement_effective_deadlines[key] = min(current_dl, obs_deadline)

    def notify_scene_detected(self, scene_data: Mapping[str, Any], raw: Any = None) -> None:
        """Explicit entrypoint for scene probe / vision loop notifications."""
        from warehouse_capture_arming import snapshot_bindings
        snap = snapshot_bindings(scene_data)
        self._record_settlement_scene(snap, raw=raw or scene_data)

    def _hwnd_gate(self, snap: Mapping[str, Any], *, require_foreground: bool = True) -> Optional[str]:
        hwnd = int(snap.get("hwnd") or snap.get("gameHwnd") or 0)
        if hwnd <= 0:
            try:
                from window_capture import WindowCaptureManager
                hwnd = int(WindowCaptureManager().find_game_hwnd() or 0)
            except Exception:
                hwnd = 0
        if hwnd <= 0:
            return "HWND_INVALID"
        adapter = self._window_adapter
        if adapter is None:
            if snap.get("minimized"):
                return "HWND_MINIMIZED"
            if snap.get("visible") is False:
                return "HWND_HIDDEN"
            if require_foreground and snap.get("foreground") is False:
                return "NOT_FOREGROUND"
            return None
        try:
            if hasattr(adapter, "is_window") and not adapter.is_window(hwnd):
                return "HWND_INVALID"
            if hasattr(adapter, "is_window_visible") and not adapter.is_window_visible(hwnd):
                return "HWND_HIDDEN"
            if hasattr(adapter, "is_iconic") and adapter.is_iconic(hwnd):
                return "HWND_MINIMIZED"
            if require_foreground and hasattr(adapter, "get_foreground_window") and int(adapter.get_foreground_window() or 0) != hwnd:
                return "NOT_FOREGROUND"
        except Exception:
            return "HWND_INVALID"
        return None

    def review_packet_copy(self):
        with self._lock:
            return copy.deepcopy(self._review_packet) if self._review_packet else None

    def _run_worker(self, token: CaptureCancelToken, arming_token: Optional[Any] = None) -> None:
        result: Optional[Mapping[str, Any]] = None
        session = None
        guard = None
        entry_time: Optional[float] = None
        game_rem: Optional[float] = None
        deadline_monotonic: Optional[float] = None
        snap = None
        try:
            if token.is_cancelled():
                result = {
                    "accepted": True,
                    "coverageStatus": "PARTIAL",
                    "terminationReason": token.reason() or "USER_STOP",
                    "savedDescriptors": [],
                }
                return

            has_bindings = (
                self._bindings_probe is not None
                or self._scene_probe is not None
                or self._window_adapter is not None
                or arming_token is not None
            )

            if has_bindings:
                snap = self._snapshot_bindings()
                key = str((snap or {}).get("recordStableKey") or "").strip()
                entry_time = self._settlement_entry_monotonics.get(key)
                game_rem = self._settlement_game_remainings.get(key)
                deadline_monotonic = self._settlement_effective_deadlines.get(key)
                if deadline_monotonic is None:
                    if entry_time is not None:
                        deadline_monotonic = entry_time + TOTAL_SETTLEMENT_BUDGET_S
                    else:
                        deadline_monotonic = self._now() + TOTAL_SETTLEMENT_BUDGET_S

                if self._now() >= deadline_monotonic:
                    result = {
                        "accepted": False,
                        "coverageStatus": "COVERAGE_UNPROVEN",
                        "terminationReason": "TIMEOUT",
                        "savedDescriptors": [],
                        "scrollRequestCount": 0,
                    }
                    self._finish(result)
                    return

                # Step 1: Wait for game window to be restored to foreground (if not currently foreground)
                hwnd_gate = self._hwnd_gate(snap or {}, require_foreground=True)
                if hwnd_gate == "NOT_FOREGROUND":
                    with self._lock:
                        self._presentation = self._build_presentation(
                            STATE_WAITING_FOR_GAME_FOCUS,
                            self._presentation.segment_count,
                            self._presentation.coverage_status,
                            None,
                        )
                    deadline = min(self._now() + self._foreground_wait_timeout_s, deadline_monotonic)
                    while not token.is_cancelled() and self._now() < deadline:
                        self._idle(0.05)
                        snap = self._snapshot_bindings()
                        if snap is None or not snap.get("isSettlement"):
                            result = {
                                "accepted": False,
                                "coverageStatus": "COVERAGE_UNPROVEN",
                                "terminationReason": "SCENE_LEFT",
                                "savedDescriptors": [],
                                "scrollRequestCount": 0,
                            }
                            return
                        hwnd_reason = self._hwnd_gate(snap, require_foreground=False)
                        if hwnd_reason:
                            result = {
                                "accepted": False,
                                "coverageStatus": "COVERAGE_UNPROVEN",
                                "terminationReason": hwnd_reason,
                                "savedDescriptors": [],
                                "scrollRequestCount": 0,
                            }
                            return
                        if self._hwnd_gate(snap, require_foreground=True) is None:
                            break
                    else:
                        if token.is_cancelled():
                            result = {
                                "accepted": True,
                                "coverageStatus": "PARTIAL",
                                "terminationReason": token.reason() or "USER_STOP",
                                "savedDescriptors": [],
                                "scrollRequestCount": 0,
                            }
                            return
                        result = {
                            "accepted": False,
                            "coverageStatus": "COVERAGE_UNPROVEN",
                            "terminationReason": "TIMEOUT",
                            "savedDescriptors": [],
                            "scrollRequestCount": 0,
                        }
                        return

                # Step 2: Full re-verification of authoritative state under foreground
                snap = self._snapshot_bindings()
                if snap is None or not snap.get("isSettlement") or not snap.get("stable") or not snap.get("warehousePresent", True):
                    result = {
                        "accepted": False,
                        "coverageStatus": "COVERAGE_UNPROVEN",
                        "terminationReason": "NOT_SETTLEMENT",
                        "savedDescriptors": [],
                        "scrollRequestCount": 0,
                    }
                    return

                if arming_token is not None:
                    if arming_token.expired(self._now()):
                        result = {
                            "accepted": False,
                            "coverageStatus": "COVERAGE_UNPROVEN",
                            "terminationReason": REASON_TOKEN_EXPIRED,
                            "savedDescriptors": [],
                            "scrollRequestCount": 0,
                        }
                        return
                    from warehouse_capture_arming import bindings_match

                    if not bindings_match(arming_token, snap):
                        result = {
                            "accepted": False,
                            "coverageStatus": "COVERAGE_UNPROVEN",
                            "terminationReason": REASON_BINDING_CHANGED,
                            "savedDescriptors": [],
                            "scrollRequestCount": 0,
                        }
                        return

                scroll = str(snap.get("scrollState") or "UNKNOWN")
                if scroll not in {"TOP", "NO_SCROLL"} and not self._resume_available(snap):
                    result = {
                        "accepted": False,
                        "coverageStatus": "COVERAGE_UNPROVEN",
                        "terminationReason": REASON_START_REQUIRES_TOP,
                        "savedDescriptors": [],
                        "scrollRequestCount": 0,
                    }
                    return

                gate = self._hwnd_gate(snap, require_foreground=True)
                if gate is not None:
                    result = {
                        "accepted": False,
                        "coverageStatus": "COVERAGE_UNPROVEN",
                        "terminationReason": gate,
                        "savedDescriptors": [],
                        "scrollRequestCount": 0,
                    }
                    return

            # Step 3: All verified: Install & arm input guard
            if self._input_guard_factory is not None:
                try:
                    guard = self._input_guard_factory(cancel_token=token)
                except TypeError:
                    try:
                        guard = self._input_guard_factory()
                    except Exception:
                        guard = None
                except Exception:
                    guard = None
                installed = False
                try:
                    installed = bool(guard is not None and guard.install())
                except Exception:
                    installed = False
                if not installed:
                    result = {
                        "accepted": False,
                        "coverageStatus": "COVERAGE_UNPROVEN",
                        "terminationReason": REASON_INPUT_GUARD_FAILED,
                        "savedDescriptors": [],
                        "scrollRequestCount": 0,
                    }
                    return
                if hasattr(guard, "arm"):
                    guard.arm()

            # Step 3.5: Capture and persist main settlement stable-frame evidence before rolling session
            if self._store_factory is not None and self._frame_provider_factory is not None:
                try:
                    store = self._store_factory()
                    frame_provider = self._frame_provider_factory()
                    if store is not None and frame_provider is not None:
                        frame = frame_provider() if callable(frame_provider) else None
                        key = str((snap or {}).get("recordStableKey") or "").strip()
                        if frame is not None and key:
                            from settlement_stable_frame_persist import persist_stable_settlement_original
                            persist_stable_settlement_original(
                                store=store,
                                is_settlement=True,
                                record_stable_key=key,
                                frame=frame,
                                extract_proposals=False,
                            )
                except Exception:
                    pass

            # Step 4: Start session
            scene = {}
            if self._scene_probe is not None:
                try:
                    probed = self._scene_probe()
                    if isinstance(probed, Mapping):
                        scene = dict(probed)
                except Exception:
                    scene = {}
            session = self._session_factory(
                scene=scene,
                cancellation_token=token,
                status_sink=self._on_session_event,
                settlement_entered_monotonic=entry_time,
                game_remaining_s=float(game_rem) if game_rem is not None else None,
                deadline_monotonic=deadline_monotonic,
            )
            if session is None:
                result = {
                    "accepted": False,
                    "coverageStatus": "COVERAGE_UNPROVEN",
                    "terminationReason": REASON_SCROLL_DRIVER_NOT_CONFIGURED,
                    "savedDescriptors": [],
                }
            else:
                if self._resume_available(snap) and hasattr(session, "resume_from"):
                    session.resume_from(self._resume_session)
                if guard is not None and hasattr(session, "attach_input_abort_guard"):
                    session.attach_input_abort_guard(guard)
                started = session.start()
                result = started if isinstance(started, Mapping) else {}
        except Exception:
            result = {
                "accepted": False,
                "coverageStatus": "PARTIAL" if self.presentation().segment_count else "COVERAGE_UNPROVEN",
                "terminationReason": "ERROR",
                "savedDescriptors": [],
            }
        finally:
            if guard is not None:
                try:
                    guard.uninstall()
                except Exception:
                    pass
            packet = None
            if session is not None and hasattr(session, "review_packet"):
                try:
                    packet = session.review_packet()
                except Exception:
                    packet = None
            if session is not None and hasattr(session, "can_resume") and snap:
                if session.can_resume(str(snap.get("recordStableKey") or "")):
                    self._resume_session = session
                    self._resume_bindings = copy.deepcopy(snap)
                elif (result or {}).get("accepted"):
                    self._resume_session = None
                    self._resume_bindings = None
            self._finish(result or {}, packet)

    def _on_session_event(self, event: Any) -> None:
        payload = event if isinstance(event, Mapping) else {}
        phase = _closed_state(payload.get("phase") or payload.get("state"))
        if phase not in RUNNING_STATES and phase != STATE_STARTING:
            return
        try:
            count = int(payload.get("segmentCount") or 0)
        except (TypeError, ValueError):
            count = 0
        coverage = str(payload.get("coverageStatus") or "COVERAGE_UNPROVEN")
        if coverage not in {"COVERAGE_UNPROVEN", "PARTIAL", "COMPLETE"}:
            coverage = "COVERAGE_UNPROVEN"
        with self._lock:
            if not self._running:
                return
            self._presentation = self._build_presentation(phase, count, coverage, None)

    def _finish(self, result: Mapping[str, Any], packet=None) -> None:
        state = _state_from_result(result)
        try:
            count = int(result.get("segmentCount") or len(result.get("savedDescriptors") or []) or 0)
        except (TypeError, ValueError):
            count = 0
        coverage = str(result.get("coverageStatus") or "COVERAGE_UNPROVEN")
        if coverage not in {"COVERAGE_UNPROVEN", "PARTIAL", "COMPLETE"}:
            coverage = "COVERAGE_UNPROVEN"
        reason = str(result.get("terminationReason") or "") or None
        with self._lock:
            self._running = False
            retained = bool(not packet and self._active_record_key and self._review_packet
                            and self._review_packet.get("recordStableKey") == self._active_record_key)
            if packet:
                self._review_packet = copy.deepcopy(packet)
            elif not retained:
                self._review_packet = None
            self._presentation = self._build_presentation(
                state,
                count,
                coverage,
                reason,
                packet_available=retained or bool(result.get("packetAvailable")),
                packet_status="RETAINED_PREVIOUS_ATTEMPT" if retained else str(result.get("packetStatus") or "UNAVAILABLE"),
                packet_fingerprint=self._review_packet.get("sourceFingerprint") if retained else result.get("packetFingerprint"),
                review_status=result.get("reviewStatus"),
            )
            sink = self._occupancy_sink

        if packet:
            try:
                from warehouse_occupancy_adapter import adapt_review_packet_to_warehouse_occupancy

                occupancy = adapt_review_packet_to_warehouse_occupancy(packet)
                if occupancy is not None:
                    if sink is not None:
                        try:
                            sink(occupancy)
                        except Exception:
                            pass
                    else:
                        try:
                            from main import CURRENT_MATCH
                        except Exception:
                            try:
                                from current_match import CURRENT_MATCH
                            except Exception:
                                CURRENT_MATCH = None
                        if CURRENT_MATCH is not None and getattr(CURRENT_MATCH, "id", None) and getattr(CURRENT_MATCH, "id", None) == packet.get("recordStableKey"):
                            try:
                                CURRENT_MATCH.apply_facts({"warehouseOccupancy": occupancy}, source="capture")
                            except Exception:
                                pass

                    try:
                        self._persist_draft_occupancy(packet, occupancy)
                    except WarehouseCropRecoveryError:
                        logger.exception("Warehouse crop recovery required after capture")
                        with self._lock:
                            self._presentation = replace(
                                self._presentation,
                                state=STATE_ERROR,
                                termination_reason="CROP_RECOVERY_REQUIRED",
                                message="仓库证据恢复未完成，已保留原图备份，请先处理保存错误。",
                            )
                    except Exception:
                        pass
            except Exception:
                pass

    def set_occupancy_sink(self, sink: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        with self._lock:
            self._occupancy_sink = sink

    def set_history_store_factory(self, factory: Optional[Callable[[], Any]]) -> None:
        with self._lock:
            self._history_store_factory = factory

    def persist_warehouse_occupancy_and_review(
        self, packet: Mapping[str, Any], occupancy: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Public production API to persist warehouse occupancy and review packet."""
        if not packet:
            return None
        if occupancy is None:
            occupancy = packet.get("warehouseOccupancy")
            if occupancy is None:
                try:
                    from warehouse_occupancy_adapter import adapt_review_packet_to_warehouse_occupancy
                    occupancy = adapt_review_packet_to_warehouse_occupancy(packet)
                except Exception:
                    occupancy = None
        return self._persist_draft_occupancy(packet, occupancy)

    @staticmethod
    def _ensure_review_units_crops_and_hashes(
        review_units: List[Dict[str, Any]],
        record_id: str,
        data_root: Path,
        segments: Optional[Sequence[Mapping[str, Any]]] = None,
        existing_record: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[Optional[Path], List[Tuple[Path, Path, Dict[str, Any]]]]:
        """Cut and cache item crops into a temporary staging area under crops/.

        Returns (staging_dir, staged_crops) where staged_crops is a list of
        (staged_path, final_target_path, cache_meta).
        If any required crop cannot be generated, raises RuntimeError (fail-closed).
        """
        if not review_units or not data_root or not record_id:
            return None, []

        crops_dir = data_root / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix=f".staging_{record_id}_", dir=str(crops_dir)))
        staged_crops: List[Tuple[Path, Path, Dict[str, Any]]] = []

        seg_sha_map: Dict[str, str] = {}
        if segments:
            for seg in segments:
                if isinstance(seg, dict):
                    eid = str(seg.get("evidenceId") or "").strip()
                    sha = str(seg.get("sha256") or "").strip().lower()
                    if eid and sha:
                        seg_sha_map[eid] = sha

        # Load existing crop cache from disk
        cache_file = crops_dir / ".crop_cache.json"
        crop_cache: Dict[str, Any] = {}
        if cache_file.is_file():
            try:
                crop_cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                crop_cache = {}

        loaded_images: Dict[str, Optional[Any]] = {}

        def get_blob_image(blob_sha: str) -> Optional[Any]:
            if not blob_sha or len(blob_sha) != 64 or any(c not in "0123456789abcdef" for c in blob_sha):
                return None
            if blob_sha in loaded_images:
                return loaded_images[blob_sha]
            prefix = blob_sha[:2]
            blob_path = data_root / "evidence" / "settlement_v2" / "blobs" / prefix / f"{blob_sha}.png"
            if not blob_path.is_file():
                parent_dir = data_root / "evidence" / "settlement_v2" / "blobs" / prefix
                found = False
                if parent_dir.is_dir():
                    for f in parent_dir.glob(f"{blob_sha}*"):
                        if f.is_file():
                            blob_path = f
                            found = True
                            break
                if not found:
                    loaded_images[blob_sha] = None
                    return None
            try:
                import cv2
                import numpy as np
                raw = blob_path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != blob_sha:
                    logger.error("Warehouse source image hash mismatch: %s", blob_path)
                    loaded_images[blob_sha] = None
                    return None
                img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                loaded_images[blob_sha] = img
                return img
            except Exception:
                loaded_images[blob_sha] = None
                return None

        try:
            for u in review_units:
                if not isinstance(u, dict):
                    continue
                uid = str(u.get("reviewUnitId") or "").strip()
                if not uid:
                    continue

                crop_filename = f"{record_id}_{uid}.png"
                crop_path = crops_dir / crop_filename
                cache_key = f"{record_id}_{uid}"

                obs_list = u.get("observations") or []
                best_obs = None
                if obs_list:
                    best_obs = next((o for o in obs_list if isinstance(o, dict) and o.get("status") == "FULL"), None)
                    if best_obs is None and isinstance(obs_list[0], dict):
                        best_obs = obs_list[0]

                raw_bbox = None
                blob_sha = None
                if best_obs:
                    raw_bbox = best_obs.get("bbox")
                    blob_sha = str(best_obs.get("sha256") or "").strip().lower()
                    if not blob_sha:
                        ev_id = str(best_obs.get("evidenceId") or "").strip()
                        blob_sha = seg_sha_map.get(ev_id)
                if raw_bbox is None:
                    raw_bbox = u.get("bbox")

                if not raw_bbox or len(raw_bbox) != 4 or not blob_sha:
                    raise RuntimeError(f"WarehouseCaptureHost: unit {uid} missing required evidence image or bbox (fail-closed)")

                img = get_blob_image(blob_sha)
                if img is None or getattr(img, "size", 0) <= 0:
                    raise RuntimeError(f"WarehouseCaptureHost: unit {uid} evidence blob {blob_sha} cannot be verified or decoded (fail-closed)")

                h_img, w_img = img.shape[:2]
                bx1, by1, bx2, by2 = _validate_and_normalize_crop_bbox(raw_bbox, w_img, h_img)

                # Strict cache verification: must match version, blobSha256, bbox, and file sha256
                is_cache_hit = False
                cached_sha256 = None
                if crop_path.is_file():
                    cached_entry = crop_cache.get(cache_key)
                    if cached_entry and (
                        cached_entry.get("version") == CROP_CACHE_VERSION
                        and cached_entry.get("blobSha256") == blob_sha
                        and tuple(cached_entry.get("bbox") or ()) == (bx1, by1, bx2, by2)
                        and cached_entry.get("cropSha256")
                    ):
                        try:
                            cbytes = crop_path.read_bytes()
                            file_sha = hashlib.sha256(cbytes).hexdigest()
                            if file_sha == cached_entry["cropSha256"]:
                                is_cache_hit = True
                                cached_sha256 = file_sha
                        except Exception:
                            is_cache_hit = False

                if is_cache_hit and cached_sha256:
                    u["cropPath"] = f"crops/{crop_filename}"
                    u["cropSha256"] = cached_sha256
                    continue

                # Cache miss: generate new crop
                crop = img[by1:by2, bx1:bx2]
                if crop.size <= 0:
                    raise RuntimeError(f"WarehouseCaptureHost: unit {uid} crop area is empty (fail-closed)")
                import cv2
                ok, buf = cv2.imencode(".png", crop)
                if not ok:
                    raise RuntimeError(f"WarehouseCaptureHost: unit {uid} cv2.imencode failed (fail-closed)")
                cbytes = buf.tobytes()
                c_sha = hashlib.sha256(cbytes).hexdigest()

                staged_path = staging_dir / crop_filename
                staged_path.write_bytes(cbytes)
                cache_meta = {
                    "key": cache_key,
                    "version": CROP_CACHE_VERSION,
                    "blobSha256": blob_sha,
                    "bbox": [bx1, by1, bx2, by2],
                    "cropSha256": c_sha,
                    "cropFilename": crop_filename,
                }
                staged_crops.append((staged_path, crop_path, cache_meta))
                u["cropPath"] = f"crops/{crop_filename}"
                u["cropSha256"] = c_sha

            return staging_dir, staged_crops
        except Exception:
            if staging_dir and staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            raise

    def _persist_draft_occupancy(
        self, packet: Mapping[str, Any], occupancy: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Persist settlement warehouse occupancy and review units to History on disk.

        Maintains distinction between live current match UI and target match evidence:
        Writes back to packet.recordStableKey even if CURRENT_MATCH has advanced to a new match,
        protecting the new match while ensuring previous match evidence is safely saved.
        """
        if not packet:
            return None

        # 1. Resolve match identity authority directly from packet
        packet_key = str(packet.get("recordStableKey") or "").strip()
        if not packet_key:
            return None
        match_id = packet_key

        # 2. Resolve history store
        store = None
        if self._history_store_factory is not None:
            try:
                store = self._history_store_factory()
            except Exception:
                store = None
        if store is None:
            try:
                from canonical_history_store import CanonicalHistoryStore

                store = CanonicalHistoryStore()
            except Exception:
                return None

        # 3. Fail-closed check: does the existing record exist in the store?
        existing = store.get_record(match_id)
        if existing is None:
            return None

        # Safely persist warehouse evidence (occupancy, identity_review, review_units)
        # 1. Obtain reviewUnits from packet - deepcopy so immutable packet is NEVER mutated!
        identity_review = packet.get("warehouseIdentityReview")
        raw_review_units = packet.get("reviewUnits")
        review_units = copy.deepcopy(raw_review_units) if raw_review_units is not None else None

        # Resolve data_root from store if available
        data_root = None
        if hasattr(store, "db_path") and getattr(store, "db_path"):
            dbp = Path(store.db_path).resolve()
            if dbp.parent.name == "history":
                data_root = dbp.parent.parent
            else:
                data_root = dbp.parent
        if data_root is None:
            try:
                from runtime_data import resolve_runtime_data_root
                data_root = resolve_runtime_data_root()
            except Exception:
                data_root = None

        staging_dir: Optional[Path] = None
        staged_crops: List[Tuple[Path, Path, Dict[str, Any]]] = []
        touched_crops: List[Path] = []
        backups: Dict[Path, Path] = {}
        keep_recovery = False
        new_cache_entries: Dict[str, Any] = {}

        try:
            # Cut/reuse crops into staging area
            if review_units:
                if not data_root:
                    raise RuntimeError("WarehouseCaptureHost: data_root unresolved, cannot generate required crops")
                staging_dir, staged_crops = self._ensure_review_units_crops_and_hashes(
                    review_units,
                    match_id,
                    data_root,
                    segments=packet.get("segments"),
                    existing_record=existing,
                )

            # If no explicit pre-fabricated identity_review, run full atomic transaction:
            if identity_review is None and review_units:
                from warehouse_auto_confirmation import evaluate_auto_confirmation
                from warehouse_identity_review import CatalogAuthority, build_auto_identity_review_artifact

                # 3. Evaluate auto confirmation
                evaluated_units = evaluate_auto_confirmation(
                    review_units,
                    segments=packet.get("segments"),
                    existing_record=existing,
                )
                for u in evaluated_units:
                    matching = next((r for r in review_units if r.get("reviewUnitId") == u.get("reviewUnitId")), None)
                    if matching:
                        if matching.get("cropPath") and not u.get("cropPath"):
                            u["cropPath"] = matching.get("cropPath")
                        if matching.get("cropSha256") and not u.get("cropSha256"):
                            u["cropSha256"] = matching.get("cropSha256")
                review_units = evaluated_units

                # 4. Build auto identity review artifact with unified CatalogAuthority
                cat_authority = CatalogAuthority()
                identity_review = build_auto_identity_review_artifact(
                    packet,
                    review_units,
                    catalog=cat_authority,
                    reviewed_at=packet.get("capturedAt") or packet.get("reviewedAt"),
                )
            elif identity_review is not None and review_units:
                from warehouse_auto_confirmation import evaluate_auto_confirmation
                evaluated_units = evaluate_auto_confirmation(
                    review_units,
                    segments=packet.get("segments"),
                    existing_record=existing,
                )
                for u in evaluated_units:
                    matching = next((r for r in review_units if r.get("reviewUnitId") == u.get("reviewUnitId")), None)
                    if matching:
                        if matching.get("cropPath") and not u.get("cropPath"):
                            u["cropPath"] = matching.get("cropPath")
                        if matching.get("cropSha256") and not u.get("cropSha256"):
                            u["cropSha256"] = matching.get("cropSha256")
                review_units = evaluated_units

            # Acquire every on-disk backup before replacing any final image.
            if hasattr(store, "persist_warehouse_evidence"):
                crops_dir = data_root / "crops"
                rollback_files = []
                for index, (staged_path, final_path, cache_meta) in enumerate(staged_crops):
                    if not staged_path.is_file():
                        raise RuntimeError(f"Missing staged crop: {staged_path}")
                    entry = {"target": final_path.name, "backup": None, "sha256": None}
                    if final_path.is_file():
                        original_bytes = final_path.read_bytes()
                        backup_path = staging_dir / f".backup_{index}.png"
                        backup_path.write_bytes(original_bytes)
                        backups[final_path] = backup_path
                        entry.update(backup=backup_path.name, sha256=hashlib.sha256(original_bytes).hexdigest())
                    rollback_files.append(entry)
                    if cache_meta:
                        new_cache_entries[cache_meta["key"]] = cache_meta

                if staged_crops:
                    (staging_dir / "rollback.json").write_text(json.dumps({
                        "recordId": match_id, "files": rollback_files,
                    }, ensure_ascii=False, indent=2), encoding="utf-8")

                for staged_path, final_path, _ in staged_crops:
                    touched_crops.append(final_path)
                    os.replace(staged_path, final_path)

                res = store.persist_warehouse_evidence(
                    match_id,
                    occupancy=occupancy,
                    identity_review=identity_review,
                    review_units=review_units,
                    # Legacy occupancy-only callers do not carry a resumable packet.
                    review_packet=packet if packet.get("schemaVersion") in
                    ("warehouse-review-packet.v1", "warehouse-review-packet.v2") else None,
                )
                if res is not None:
                    # Update .crop_cache.json on success
                    if new_cache_entries:
                        try:
                            cache_file = crops_dir / ".crop_cache.json"
                            cdata = {}
                            if cache_file.is_file():
                                cdata = json.loads(cache_file.read_text(encoding="utf-8"))
                            cdata.update(new_cache_entries)
                            cache_file.write_text(json.dumps(cdata, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception as exc:
                            logger.warning("Failed to update .crop_cache.json: %s", exc)
                    return res
                raise RuntimeError(f"persist_warehouse_evidence returned None for record {match_id}")

            # Refuse fallback if identity review or review units present
            if identity_review is not None or review_units is not None:
                raise RuntimeError("store does not support persist_warehouse_evidence")

            if hasattr(store, "persist_draft_warehouse_occupancy"):
                return store.persist_draft_warehouse_occupancy(match_id, occupancy)
            return None

        except Exception as exc:
            logger.error(
                "WarehouseCaptureHost: persistence transaction failed for record %s: %s (fail-closed, rolling back)",
                match_id,
                exc,
            )
            # Only touched targets need restoring. Keep backups until every restore succeeds.
            recovery_failures = []
            for index, p in enumerate(touched_crops):
                try:
                    if p in backups:
                        restore_path = staging_dir / f".restore_{index}.png"
                        restore_path.write_bytes(backups[p].read_bytes())
                        os.replace(restore_path, p)
                    else:
                        p.unlink(missing_ok=True)
                except Exception as restore_exc:
                    recovery_failures.append(f"{p.name}: {restore_exc}")
            if recovery_failures:
                keep_recovery = True
                logger.error("Warehouse crop recovery incomplete, retained %s: %s", staging_dir, recovery_failures)
                raise WarehouseCropRecoveryError(staging_dir, recovery_failures) from exc
            return None
        finally:
            if not keep_recovery and staging_dir and staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    def _build_presentation(
        self,
        state: str,
        segment_count: int,
        coverage_status: str,
        termination_reason: Optional[str],
        packet_available: bool = False,
        packet_status: str = "UNAVAILABLE",
        packet_fingerprint: Optional[str] = None,
        review_status: Optional[str] = None,
        message: Optional[str] = None,
    ) -> WarehouseCapturePresentation:
        closed = _closed_state(state)
        available = self.available
        disabled_reason = None

        if message is not None:
            resolved_message = message
        elif closed in RUNNING_STATES:
            resolved_message = _message_for(closed, segment_count)
        elif available and self._resume_available(self._snapshot_bindings()):
            resolved_message = "已保留采集证据；可尝试从当前页继续，画面核对失败会停止，原截止时间不变"
        elif closed == STATE_START_REQUIRES_TOP:
            disabled_reason = DISABLED_REASON_SCROLL_NOT_AT_TOP
            resolved_message = _message_for(closed, segment_count)
        elif not available:
            reason_code, reason_text = self._evaluate_disabled_reason()
            disabled_reason = reason_code
            resolved_message = reason_text or _message_for(closed, segment_count)
        else:
            resolved_message = _message_for(closed, segment_count)

        return WarehouseCapturePresentation(
            available=available,
            state=closed,
            segment_count=max(0, int(segment_count)),
            coverage_status=coverage_status,
            stop_available=closed in RUNNING_STATES,
            message=resolved_message if message is None else message,
            termination_reason=termination_reason,
            disabled_reason=disabled_reason,
            packet_available=packet_available,
            packet_status=packet_status,
            packet_fingerprint=packet_fingerprint if isinstance(packet_fingerprint, str) else None,
            review_status=str(review_status) if review_status else None,
        )


def build_production_warehouse_capture_host(**overrides) -> WarehouseCaptureHost:
    """Closed production host. Lazy factories do not send input at construction."""
    from warehouse_capture_session import PRODUCTION_SCROLL_DRIVER_ENABLED

    if not PRODUCTION_SCROLL_DRIVER_ENABLED:
        return WarehouseCaptureHost(session_factory=None, driver_available=False)
    from warehouse_capture_production import (
        make_production_guard_factory,
        make_production_session_factory,
    )

    def _inert_bindings():
        return {"isSettlement": False, "stable": False, "hwnd": 0, "recordStableKey": "", "scrollState": "UNKNOWN", "scene": "UNKNOWN"}

    def _lazy_os_adapter():
        from warehouse_wheel_driver import Win32WarehouseOsAdapter

        return Win32WarehouseOsAdapter()

    def _lazy_store():
        try:
            from runtime_data import runtime_data_paths
            from settlement_evidence_store_v2 import SettlementEvidenceStoreV2

            return SettlementEvidenceStoreV2(runtime_data_paths().root)
        except Exception:
            return None

    def _lazy_input_adapter():
        from warehouse_input_abort_guard import Win32InputActivityAdapter

        return Win32InputActivityAdapter()

    def _lazy_frame_provider():
        try:
            from window_capture import WindowCaptureManager

            mgr = WindowCaptureManager()

            def _get_frame(raw_scene=None):
                snap = (overrides.get("bindings_probe") or _inert_bindings)() or {}
                hwnd = int(snap.get("hwnd") or 0)
                if not hwnd:
                    hwnd = int(mgr.find_game_hwnd() or 0)
                if not hwnd:
                    return None
                frame, _ = mgr.capture_game_client(hwnd)
                return frame

            return _get_frame
        except Exception:
            return None

    bindings_probe = overrides.get("bindings_probe") or _inert_bindings
    os_adapter_factory = overrides.get("os_adapter_factory") or _lazy_os_adapter
    store_factory = overrides.get("store_factory") or _lazy_store
    input_adapter_factory = overrides.get("input_adapter_factory") or _lazy_input_adapter
    frame_provider_factory = overrides.get("frame_provider_factory") or _lazy_frame_provider
    session_factory = overrides.get("session_factory") or make_production_session_factory(
        bindings_probe=bindings_probe,
        os_adapter_factory=os_adapter_factory,
        store_factory=store_factory,
        frame_provider_factory=frame_provider_factory,
        scene_validator_factory=overrides.get("scene_validator_factory"),
        reconstruction_factory=overrides.get("reconstruction_factory"),
    )
    guard_factory = overrides.get("input_guard_factory") or make_production_guard_factory(
        adapter_factory=input_adapter_factory
    )
    return WarehouseCaptureHost(
        session_factory=session_factory,
        driver_available=True,
        scene_probe=overrides.get("scene_probe") or bindings_probe,
        input_guard_factory=guard_factory,
        bindings_probe=bindings_probe,
        window_adapter=overrides.get("window_adapter"),
        clock=overrides.get("clock"),
        token_ttl_s=float(overrides.get("token_ttl_s") or 12.0),
        foreground_wait_timeout_s=float(overrides.get("foreground_wait_timeout_s") or 10.0),
        idle=overrides.get("idle"),
        arming_required=True,
        store_factory=store_factory,
        frame_provider_factory=frame_provider_factory,
        history_store_factory=overrides.get("history_store_factory"),
        input_execution_allowed=overrides.get("input_execution_allowed"),
    )


_PRODUCTION_HOST = build_production_warehouse_capture_host()


def get_warehouse_capture_host() -> WarehouseCaptureHost:
    return _PRODUCTION_HOST


def set_warehouse_capture_host(host: Optional[WarehouseCaptureHost]) -> None:
    global _PRODUCTION_HOST
    _PRODUCTION_HOST = host or build_production_warehouse_capture_host()


def attach_warehouse_capture_presentation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Attach the closed presentation object; never copies raw session authority."""
    payload["warehouseCapture"] = get_warehouse_capture_host().presentation_payload()
    return payload
