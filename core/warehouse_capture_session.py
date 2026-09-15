"""Warehouse capture session orchestrator (injected scroll driver).

Wires the passive scrollbar observer, overlap aligner, Coverage Ledger, and
Evidence Store v2 into a cancellable, fail-closed settlement-warehouse session.

Scroll happens only through an injected requester. There is no production OS
input driver. Completeness is never inferred here; only Ledger finalize decides.
"""

from __future__ import annotations

import hashlib
import copy
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import cv2
import numpy as np

from settlement_evidence_store_v2 import (
    COVERAGE_UNPROVEN,
    KIND_WAREHOUSE_SEGMENT,
    SettlementEvidenceStoreError,
    detect_image_type,
)
from settlement_stable_frame_persist import encode_settlement_original
from warehouse_coverage_ledger import (
    REASON_COMPLETE as LEDGER_COMPLETE,
    REASON_INCOMPLETE as LEDGER_INCOMPLETE,
    REASON_MISSING_OVERLAP as LEDGER_MISSING_OVERLAP,
    REASON_TIMEOUT as LEDGER_TIMEOUT,
    REASON_USER_STOP as LEDGER_USER_STOP,
    REASON_WINDOW_LOST as LEDGER_WINDOW_LOST,
    STATUS_UNPROVEN,
    WarehouseCoverageLedger,
    WarehouseCoverageLedgerError,
)
from warehouse_scrollbar_observation import (
    CHANGE_CHANGED,
    CHANGE_UNCHANGED,
    STATE_BOTTOM,
    STATE_MIDDLE,
    STATE_NO_SCROLL,
    STATE_TOP,
    STATE_UNKNOWN,
    WarehouseScrollbarObserver,
    warehouse_search_roi,
)
from warehouse_segment_overlap import (
    DIR_DOWN,
    STATUS_CONFLICT,
    STATUS_VERIFIED,
    align_warehouse_segments,
)
from warehouse_support_frame import stationary_support_proof

SCHEMA_VERSION = "warehouse-capture-session.v1"
STATUS_SCHEMA_VERSION = "warehouse-capture-session-status.v1"

REASON_COMPLETE = "COMPLETE"
REASON_USER_STOP = "USER_STOP"
REASON_USER_INPUT = "USER_INPUT"
REASON_ESCAPE = "ESCAPE"
REASON_INPUT_GUARD_FAILED = "INPUT_GUARD_FAILED"
REASON_TIMEOUT = "TIMEOUT"
REASON_WINDOW_LOST = "WINDOW_LOST"
REASON_SCENE_LEFT = "SCENE_LEFT"
REASON_STORE_FAILED = "STORE_FAILED"
REASON_OBSERVER_UNKNOWN = "OBSERVER_UNKNOWN"
REASON_OVERLAP_UNVERIFIED = "OVERLAP_UNVERIFIED"
REASON_OVERLAP_CONFLICT = "OVERLAP_CONFLICT"
REASON_CONSECUTIVE_UNCHANGED = "CONSECUTIVE_UNCHANGED"
REASON_SAFETY_STEP_LIMIT = "SAFETY_STEP_LIMIT"
REASON_START_REQUIRES_TOP = "START_REQUIRES_TOP"
REASON_SCROLL_DRIVER_NOT_CONFIGURED = "SCROLL_DRIVER_NOT_CONFIGURED"
REASON_START_REQUIRES_STABLE_SETTLEMENT = "START_REQUIRES_STABLE_SETTLEMENT"
REASON_WAREHOUSE_NOT_PRESENT = "WAREHOUSE_NOT_PRESENT"
REASON_MISSING_STABLE_KEY = "MISSING_STABLE_KEY"
REASON_STABLE_KEY_CHANGED = "STABLE_KEY_CHANGED"

PHASE_IDLE = "IDLE"
PHASE_STARTING = "STARTING"
PHASE_CAPTURING = "CAPTURING"
PHASE_SCROLLING = "SCROLLING"
PHASE_WAITING = "WAITING"
PHASE_ALIGNING = "ALIGNING"
PHASE_FINALIZING = "FINALIZING"
PHASE_STOPPED = "STOPPED"

DEFAULT_MAX_STEPS = 16
DEFAULT_MAX_UNCHANGED = 3
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_POLL_INTERVAL_S = 0.05

PRODUCTION_SCROLL_DRIVER_ENABLED = True

STATUS_KEYS = (
    "schemaVersion",
    "event",
    "phase",
    "recordStableKey",
    "scrollState",
    "segmentChange",
    "coverageStatus",
    "finalized",
    "terminationReason",
    "segmentCount",
    "scrollRequestCount",
    "accepted",
)

RESULT_KEYS = (
    "schemaVersion",
    "accepted",
    "coverageStatus",
    "terminationReason",
    "finalized",
    "ledger",
    "savedDescriptors",
    "scrollRequestCount",
    "statusEvents",
    "packetAvailable",
    "packetStatus",
    "packetFingerprint",
    "reviewStatus",
    "reconstructionWarnings",
    "missingPages",
)


def get_production_scroll_driver():
    """Closed production builder. Instantiating it does not send OS input."""
    if not PRODUCTION_SCROLL_DRIVER_ENABLED:
        return None
    from warehouse_capture_production import ProductionScrollDriverFactory

    return ProductionScrollDriverFactory()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_bool(value: Any) -> bool:
    return bool(value)


def _ledger_reason(session_reason: str) -> str:
    if session_reason in {REASON_USER_STOP, REASON_USER_INPUT, REASON_ESCAPE}:
        return LEDGER_USER_STOP
    if session_reason == REASON_TIMEOUT:
        return LEDGER_TIMEOUT
    if session_reason == REASON_WINDOW_LOST:
        return LEDGER_WINDOW_LOST
    if session_reason in (REASON_OVERLAP_UNVERIFIED, REASON_OVERLAP_CONFLICT):
        return LEDGER_MISSING_OVERLAP
    return LEDGER_INCOMPLETE


def _normalize_frame(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {"image": None, "image_bytes": None, "window_lost": True, "already_cropped": None}
    if isinstance(raw, (bytes, bytearray)):
        return {"image": None, "image_bytes": bytes(raw), "window_lost": False, "already_cropped": None}
    if isinstance(raw, np.ndarray):
        return {"image": raw, "image_bytes": None, "window_lost": False, "already_cropped": None}
    payload = _mapping(raw)
    image = payload.get("image", payload.get("frame"))
    image_bytes = payload.get("imageBytes", payload.get("image_bytes"))
    if isinstance(image_bytes, (bytes, bytearray)):
        image_bytes = bytes(image_bytes)
    else:
        image_bytes = None
    if image is not None and not isinstance(image, np.ndarray):
        image = None
    return {
        "image": image,
        "image_bytes": image_bytes,
        "window_lost": _as_bool(payload.get("windowLost", payload.get("window_lost"))),
        "already_cropped": payload.get("alreadyCropped", payload.get("already_cropped")),
    }


def _ensure_image(frame: Mapping[str, Any]) -> Optional[np.ndarray]:
    image = frame.get("image")
    if isinstance(image, np.ndarray) and image.size:
        return image
    payload = frame.get("image_bytes")
    if not payload:
        return None
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None or getattr(decoded, "size", 0) == 0:
        return None
    return decoded


def _encode_original(frame: Mapping[str, Any], image: np.ndarray) -> bytes:
    payload = frame.get("image_bytes")
    if payload:
        if detect_image_type(payload) is None:
            raise SettlementEvidenceStoreError("INVALID_IMAGE", "encoded bytes are not PNG or JPEG")
        return payload
    return encode_settlement_original(image)


def _parse_scene(raw: Any) -> Dict[str, Any]:
    payload = _mapping(raw)
    key = (
        payload.get("recordStableKey")
        or payload.get("record_stable_key")
        or payload.get("id")
        or payload.get("matchId")
        or ""
    )
    scene = str(payload.get("scene") or "")
    is_settlement = payload.get("isSettlement", payload.get("is_settlement"))
    if is_settlement is None:
        is_settlement = scene == "SETTLEMENT"
    stable = payload.get("stable", payload.get("isStable", payload.get("is_stable")))
    warehouse_present = payload.get("warehousePresent", payload.get("warehouse_present"))
    # Production bindings always provide this independent authority. Keep the
    # legacy default for injected unit-test validators that predate the field.
    if warehouse_present is None:
        warehouse_present = True
    return {
        "is_settlement": _as_bool(is_settlement),
        "stable": _as_bool(stable),
        "warehouse_present": _as_bool(warehouse_present),
        "record_stable_key": str(key or "").strip(),
        "window_lost": _as_bool(payload.get("windowLost", payload.get("window_lost"))),
    }


def _call_provider(provider: Any) -> Any:
    if provider is None:
        return None
    if hasattr(provider, "capture") and callable(provider.capture):
        return provider.capture()
    if callable(provider):
        return provider()
    return None


def _call_validator(validator: Any, raw: Any) -> Any:
    if validator is None:
        return {}
    if hasattr(validator, "validate") and callable(validator.validate):
        return validator.validate(raw)
    if callable(validator):
        return validator(raw)
    return {}


def _is_cancelled(token: Any, flag: bool) -> bool:
    if flag:
        return True
    if token is None:
        return False
    if hasattr(token, "is_cancelled"):
        return bool(token.is_cancelled())
    if hasattr(token, "cancelled"):
        cancelled = token.cancelled
        return bool(cancelled() if callable(cancelled) else cancelled)
    if callable(token):
        return bool(token())
    return False


def _endpoint_proof(role: str, observation: Mapping[str, Any]) -> Dict[str, Any]:
    state = str(observation.get("scrollState") or STATE_UNKNOWN)
    fingerprint = str(observation.get("warehouseFingerprint") or "none")
    return {
        "trusted": True,
        "proofId": f"scrollbar-{role}:{state}:{fingerprint}",
        "role": role,
    }


def _overlap_proof(prev_id: str, next_id: str, alignment: Mapping[str, Any]) -> Dict[str, Any]:
    offset = alignment.get("verticalOffsetPx")
    proof_id = alignment.get("progressionProofId") or f"overlap-down:{prev_id}:{next_id}:{offset}"
    return {
        "trusted": True,
        "aligned": True,
        "proofId": str(proof_id),
        "previousEvidenceId": prev_id,
    }


class WarehouseCaptureSession:
    def __init__(
        self,
        *,
        frame_provider: Any = None,
        scene_validator: Any = None,
        scroll_requester: Any = None,
        cancellation_token: Any = None,
        status_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
        clock: Any = None,
        idle: Optional[Callable[[float], None]] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        settlement_entered_monotonic: Optional[float] = None,
        game_remaining_s: Optional[float] = None,
        deadline_monotonic: Optional[float] = None,
        store: Any = None,
        ledger_factory: Optional[Callable[[str], WarehouseCoverageLedger]] = None,
        observer: Any = None,
        aligner: Optional[Callable[..., Mapping[str, Any]]] = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_unchanged: int = DEFAULT_MAX_UNCHANGED,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        already_cropped: bool = False,
        reconstruction_factory: Optional[Callable[..., Any]] = None,
        input_abort_guard: Any = None,
        top_support_attempts: int = 0,
    ):
        self._frame_provider = frame_provider
        self._scene_validator = scene_validator
        self._scroll_requester = scroll_requester
        self._cancellation_token = cancellation_token
        self._status_sink = status_sink
        self._clock = clock
        self._idle = idle if idle is not None else time.sleep
        self._timeout_s = float(timeout_s)
        self._settlement_entered_monotonic = (
            float(settlement_entered_monotonic) if settlement_entered_monotonic is not None else None
        )
        self._game_remaining_s = (
            float(game_remaining_s) if game_remaining_s is not None else None
        )
        self._deadline = (
            float(deadline_monotonic) if deadline_monotonic is not None else None
        )
        self._store = store
        self._ledger_factory = ledger_factory or WarehouseCoverageLedger
        self._observer = observer if observer is not None else WarehouseScrollbarObserver()
        self._aligner = aligner or align_warehouse_segments
        self._max_steps = max(0, int(max_steps))
        self._max_unchanged = max(1, int(max_unchanged))
        self._poll_interval_s = max(0.0, float(poll_interval_s))
        self._already_cropped = bool(already_cropped)
        self._reconstruction_factory = reconstruction_factory
        self._input_abort_guard = input_abort_guard
        self._top_support_attempts = min(2, max(0, int(top_support_attempts)))
        self._pending_intake = None

        self._phase = PHASE_IDLE
        self._started = False
        self._accepted = False
        self._stopped = False
        self._user_stop = False
        self._started_at: Optional[float] = None
        self._key: Optional[str] = None
        self._ledger: Optional[WarehouseCoverageLedger] = None
        self._saved: List[Dict[str, Any]] = []
        self._saved_hashes: set[str] = set()
        self._scroll_request_count = 0
        self._events: List[Dict[str, Any]] = []
        self._result: Optional[Dict[str, Any]] = None
        self._last_scroll_state: Optional[str] = None
        self._last_segment_change: Optional[str] = None
        self._prev_roi: Optional[np.ndarray] = None
        self._prev_id: Optional[str] = None
        self._sequence_index = 0
        self._reconstruction: Any = None
        self._segment_inputs = []
        self._resume_source = None

    def can_resume(self, record_stable_key: str) -> bool:
        """Only a clean interrupted, in-memory chain can seed another attempt."""
        snap = self._snapshot_ledger() or {}
        return bool(
            self._stopped and self._accepted and self._key == record_stable_key
            and (self._result or {}).get("terminationReason") in {
                REASON_USER_STOP, REASON_USER_INPUT, REASON_ESCAPE, REASON_WINDOW_LOST,
            }
            and self._deadline is not None and not self._timed_out()
            and self._prev_roi is not None and self._saved
            and self._prev_id == self._saved[-1].get("evidenceId")
            and len(self._segment_inputs) == len(self._saved)
            and all("image" in item for item in self._segment_inputs)
            and not snap.get("gaps") and not snap.get("conflicts")
        )

    def resume_from(self, previous: "WarehouseCaptureSession") -> bool:
        if self._started or not previous.can_resume(previous._key):
            return False
        self._resume_source = previous
        self._deadline = min(self._deadline, previous._deadline) if self._deadline is not None else previous._deadline
        return True

    def _restore_resume(self, bundle, state) -> Optional[str]:
        previous = self._resume_source
        self._resume_source = None
        if previous is None or not previous.can_resume(self._key):
            return REASON_START_REQUIRES_TOP
        if not bundle["scene"]["stable"]:
            return REASON_START_REQUIRES_STABLE_SETTLEMENT
        # A scrollbar position alone does not identify a page. Require the same
        # viewport content; a changed page must be recaptured from TOP.
        if (state != previous._last_scroll_state or state != STATE_MIDDLE
                or not (np.array_equal(previous._prev_roi, bundle["roi"])
                        or stationary_support_proof(previous._prev_roi, bundle["roi"]))):
            return REASON_START_REQUIRES_TOP
        # Check every original before restoring coverage or issuing any input.
        try:
            for descriptor in previous._saved:
                payload = self._store.load_original(descriptor)
                if hashlib.sha256(payload).hexdigest() != descriptor["sha256"]:
                    return REASON_STORE_FAILED
        except Exception:
            return REASON_STORE_FAILED
        self._accepted = True
        self._ledger = self._ledger_factory(self._key)
        self._saved = copy.deepcopy(previous._saved)
        self._saved_hashes = set(previous._saved_hashes)
        self._scroll_request_count = previous._scroll_request_count
        for item in previous._segment_inputs:
            error = self._add_segment(item["descriptor"], **item["proofs"])
            if error:
                return error
            self._reconstruct_segment(item["image"], item["descriptor"], item["observation"], item["alignment"])
        self._prev_roi = previous._prev_roi.copy()
        self._prev_id = previous._prev_id
        self._emit("session_resumed")
        return None

    def stop(self) -> None:
        self._user_stop = True

    def attach_input_abort_guard(self, guard: Any) -> None:
        self._input_abort_guard = guard

    def update_game_countdown(
        self, remaining_s: float, observation_monotonic: Optional[float] = None
    ) -> None:
        """Update deadline based on new countdown observation.

        Game deadline = observation_monotonic + remaining_s, monotonically tightened.
        0 seconds remaining is valid and forces immediate deadline.
        """
        if remaining_s is None:
            return
        t_obs = float(observation_monotonic) if observation_monotonic is not None else self._now()
        obs_deadline = t_obs + max(0.0, float(remaining_s))
        if self._deadline is None:
            hard = (self._settlement_entered_monotonic or t_obs) + self._timeout_s
            self._deadline = min(hard, obs_deadline)
        else:
            self._deadline = min(self._deadline, obs_deadline)

    def start(self) -> Dict[str, Any]:
        if self._result is not None:
            return dict(self._result)
        if self._started:
            return dict(self._result or self._build_result(False, STATUS_UNPROVEN, REASON_START_REQUIRES_TOP))
        self._started = True
        self._phase = PHASE_STARTING
        now = self._now()
        self._started_at = now
        if self._deadline is None:
            anchor = self._settlement_entered_monotonic if self._settlement_entered_monotonic is not None else now
            hard_deadline = anchor + self._timeout_s
            if self._game_remaining_s is not None:
                self._deadline = min(hard_deadline, anchor + max(0.0, float(self._game_remaining_s)))
            else:
                self._deadline = hard_deadline
        try:
            return self._run()
        except SettlementEvidenceStoreError:
            return self._stop(REASON_STORE_FAILED)
        except Exception:
            if self._saved:
                return self._stop(REASON_STORE_FAILED)
            return self._reject(REASON_STORE_FAILED)
        finally:
            self._release_input_guard()

    def _now(self) -> float:
        clock = self._clock
        if clock is None:
            return time.monotonic()
        if hasattr(clock, "now") and callable(clock.now):
            return float(clock.now())
        if callable(clock):
            return float(clock())
        return time.monotonic()

    def _timed_out(self) -> bool:
        if self._deadline is None:
            return False
        return self._now() >= self._deadline

    def _cancelled(self) -> bool:
        return _is_cancelled(self._cancellation_token, self._user_stop)

    def _abort_reason(self) -> str:
        guard = self._input_abort_guard
        if guard is not None and hasattr(guard, "abort_reason"):
            try:
                reason = guard.abort_reason()
            except Exception:
                reason = None
            if reason in {REASON_ESCAPE, REASON_USER_INPUT}:
                return str(reason)
        token = self._cancellation_token
        if token is not None and hasattr(token, "reason"):
            try:
                reason = token.reason() if callable(token.reason) else token.reason
            except Exception:
                reason = None
            if reason in {REASON_ESCAPE, REASON_USER_INPUT, REASON_USER_STOP}:
                return str(reason)
        return REASON_USER_STOP

    def _install_input_guard(self) -> Optional[str]:
        guard = self._input_abort_guard
        if guard is None:
            return None
        if bool(getattr(guard, "installed", False)):
            return None
        try:
            ok = bool(guard.install())
        except Exception:
            ok = False
        if not ok:
            return REASON_INPUT_GUARD_FAILED
        return None

    def _arm_input_guard(self) -> None:
        guard = self._input_abort_guard
        if guard is None:
            return
        try:
            guard.arm()
        except Exception:
            return

    def _release_input_guard(self) -> None:
        guard = self._input_abort_guard
        if guard is None:
            return
        try:
            if hasattr(guard, "uninstall") and callable(guard.uninstall):
                guard.uninstall()
        except Exception:
            return

    def _snapshot_ledger(self) -> Optional[Dict[str, Any]]:
        if self._ledger is None:
            return None
        return self._ledger.snapshot()

    def _coverage_status(self) -> str:
        snap = self._snapshot_ledger()
        if snap is None:
            return STATUS_UNPROVEN
        return str(snap.get("coverageStatus") or STATUS_UNPROVEN)

    def _emit(self, event: str, termination_reason: Optional[str] = None) -> None:
        snap = self._snapshot_ledger()
        payload = {
            "schemaVersion": STATUS_SCHEMA_VERSION,
            "event": event,
            "phase": self._phase,
            "recordStableKey": self._key,
            "scrollState": self._last_scroll_state,
            "segmentChange": self._last_segment_change,
            "coverageStatus": (snap or {}).get("coverageStatus") or STATUS_UNPROVEN,
            "finalized": bool((snap or {}).get("finalized")),
            "terminationReason": termination_reason if termination_reason is not None else (snap or {}).get("terminationReason"),
            "segmentCount": len(self._saved),
            "scrollRequestCount": self._scroll_request_count,
            "accepted": self._accepted,
        }
        extra = set(payload) - set(STATUS_KEYS)
        for key in extra:
            payload.pop(key, None)
        event_copy = dict(payload)
        self._events.append(event_copy)
        if self._status_sink is not None:
            self._status_sink(dict(event_copy))

    def _build_result(self, accepted: bool, coverage: str, reason: str) -> Dict[str, Any]:
        snap = self._snapshot_ledger()
        missing_pages = None
        if coverage != "COMPLETE" or self._last_scroll_state != STATE_BOTTOM:
            missing_pages = {
                "reachedBottom": bool(self._last_scroll_state == STATE_BOTTOM),
                "lastScrollState": self._last_scroll_state or STATE_UNKNOWN,
                "capturedSegments": len(self._saved),
                "reason": reason,
                "remainingBudgetS": max(0.0, (self._deadline - self._now())) if self._deadline is not None else 0.0,
            }

        result = {
            "schemaVersion": SCHEMA_VERSION,
            "accepted": accepted,
            "coverageStatus": coverage,
            "terminationReason": reason,
            "finalized": bool((snap or {}).get("finalized")),
            "ledger": snap,
            "savedDescriptors": [dict(item) for item in self._saved],
            "scrollRequestCount": self._scroll_request_count,
            "statusEvents": [dict(item) for item in self._events],
            "missingPages": missing_pages,
            **self._reconstruction_fields(),
        }
        extra = set(result) - set(RESULT_KEYS)
        for key in extra:
            result.pop(key, None)
        return result

    def _reject(self, reason: str) -> Dict[str, Any]:
        self._stopped = True
        self._accepted = False
        self._phase = PHASE_STOPPED
        self._emit("start_rejected", reason)
        result = self._build_result(False, STATUS_UNPROVEN, reason)
        self._result = result
        return dict(result)

    def _stop(self, reason: str, *, complete: bool = False) -> Dict[str, Any]:
        self._stopped = True
        self._phase = PHASE_FINALIZING
        snap = None
        if self._ledger is not None:
            if complete:
                snap = self._ledger.finalize(LEDGER_COMPLETE)
                reason = str(snap.get("terminationReason") or reason)
            else:
                snap = self._ledger.finalize(_ledger_reason(reason))
        self._phase = PHASE_STOPPED
        coverage = str((snap or {}).get("coverageStatus") or STATUS_UNPROVEN)
        self._finalize_reconstruction(snap)
        self._emit("session_stopped", reason)
        result = self._build_result(self._accepted, coverage, reason)
        self._result = result
        return dict(result)

    def _observe(self, image: np.ndarray, already_cropped: bool) -> Dict[str, Any]:
        observer = self._observer
        if hasattr(observer, "observe") and callable(observer.observe):
            result = observer.observe(
                image,
                already_cropped=already_cropped,
                source_id=f"seg{self._sequence_index}",
            )
        elif callable(observer):
            result = observer(image, already_cropped=already_cropped)
        else:
            result = {"scrollState": STATE_UNKNOWN, "segmentChange": STATE_UNKNOWN}
        payload = dict(_mapping(result))
        self._last_scroll_state = str(payload.get("scrollState") or STATE_UNKNOWN)
        self._last_segment_change = str(payload.get("segmentChange") or STATE_UNKNOWN)
        return payload

    def _crop_roi(self, image: np.ndarray, already_cropped: bool) -> np.ndarray:
        if already_cropped:
            return image
        height, width = image.shape[:2]
        x1, y1, x2, y2 = warehouse_search_roi(width, height)
        return image[y1:y2, x1:x2]

    def _intake(self, *, at_start: bool) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if self._cancelled():
            return None, self._abort_reason()
        if self._timed_out():
            return None, REASON_TIMEOUT
        raw = _call_provider(self._frame_provider)
        frame = _normalize_frame(raw)
        if frame["window_lost"]:
            return None, REASON_WINDOW_LOST
        try:
            scene = _parse_scene(_call_validator(self._scene_validator, raw))
        except Exception:
            return None, REASON_SCENE_LEFT if not at_start else REASON_START_REQUIRES_STABLE_SETTLEMENT
        if scene["window_lost"]:
            return None, REASON_WINDOW_LOST
        if at_start:
            if not scene["is_settlement"]:
                return None, REASON_START_REQUIRES_STABLE_SETTLEMENT
            if not scene["warehouse_present"]:
                return None, REASON_WAREHOUSE_NOT_PRESENT
            if not scene["record_stable_key"]:
                return None, REASON_MISSING_STABLE_KEY
        else:
            if not scene["is_settlement"]:
                return None, REASON_SCENE_LEFT
            if not scene["warehouse_present"]:
                return None, REASON_WAREHOUSE_NOT_PRESENT
            if self._key and scene["record_stable_key"] and scene["record_stable_key"] != self._key:
                return None, REASON_STABLE_KEY_CHANGED
            if self._key and not scene["record_stable_key"]:
                return None, REASON_STABLE_KEY_CHANGED
        image = _ensure_image(frame)
        if image is None:
            return None, REASON_WINDOW_LOST
        cropped = frame["already_cropped"]
        already_cropped = self._already_cropped if cropped is None else bool(cropped)
        return {
            "frame": frame,
            "scene": scene,
            "image": image,
            "already_cropped": already_cropped,
            "roi": self._crop_roi(image, already_cropped),
        }, None

    def _persist(self, payload: bytes) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        if self._store is None:
            return None, REASON_STORE_FAILED
        digest = hashlib.sha256(payload).hexdigest()
        if digest in self._saved_hashes:
            return None, "duplicate"
        try:
            descriptor = self._store.save_original(
                record_stable_key=self._key,
                kind=KIND_WAREHOUSE_SEGMENT,
                image_bytes=payload,
                coverage_mode="viewport-segment",
                coverage_status=COVERAGE_UNPROVEN,
            )
        except Exception:
            return None, REASON_STORE_FAILED
        if not isinstance(descriptor, Mapping):
            return None, REASON_STORE_FAILED
        evidence_id = str(descriptor.get("evidenceId") or "").strip()
        sha256 = str(descriptor.get("sha256") or "").strip()
        if not evidence_id or not sha256 or descriptor.get("kind") != KIND_WAREHOUSE_SEGMENT:
            return None, REASON_STORE_FAILED
        copied = dict(descriptor)
        self._saved.append(copied)
        self._saved_hashes.add(sha256)
        return copied, None

    def _add_segment(
        self,
        descriptor: Mapping[str, Any],
        *,
        top_proof: Optional[Mapping[str, Any]] = None,
        bottom_proof: Optional[Mapping[str, Any]] = None,
        overlap_proof: Optional[Mapping[str, Any]] = None,
    ) -> Optional[str]:
        if self._ledger is None:
            return REASON_STORE_FAILED
        try:
            self._ledger.add_segment(
                descriptor,
                sequence_index=self._sequence_index,
                top_proof=top_proof,
                bottom_proof=bottom_proof,
                overlap_proof=overlap_proof,
            )
        except WarehouseCoverageLedgerError:
            return REASON_STORE_FAILED
        self._segment_inputs.append({
            "descriptor": copy.deepcopy(descriptor),
            "proofs": copy.deepcopy({"top_proof": top_proof, "bottom_proof": bottom_proof,
                                     "overlap_proof": overlap_proof}),
        })
        self._sequence_index += 1
        return None

    def review_packet(self) -> Optional[Dict[str, Any]]:
        processor = self._reconstruction
        if processor is None or not hasattr(processor, "packet_copy"):
            return None
        return processor.packet_copy()

    def _reconstruction_fields(self) -> Dict[str, Any]:
        processor = self._reconstruction
        empty = {
            "packetAvailable": False,
            "packetStatus": "UNAVAILABLE",
            "packetFingerprint": None,
            "reviewStatus": None,
            "reconstructionWarnings": [],
        }
        if processor is None or not hasattr(processor, "readonly_snapshot"):
            return empty
        try:
            snap = processor.readonly_snapshot()
        except Exception:
            return empty
        return {
            "packetAvailable": bool(snap.get("packetAvailable")),
            "packetStatus": snap.get("packetStatus") or "UNAVAILABLE",
            "packetFingerprint": snap.get("packetFingerprint"),
            "reviewStatus": snap.get("reviewStatus"),
            "reconstructionWarnings": list(snap.get("warnings") or []),
        }

    def _ensure_reconstruction(self) -> None:
        if self._reconstruction is not None or not self._key:
            return
        factory = self._reconstruction_factory
        if factory is None:
            from warehouse_reconstruction import WarehouseReconstructionProcessor

            factory = WarehouseReconstructionProcessor
        try:
            self._reconstruction = factory(self._key)
        except Exception:
            self._reconstruction = None

    def _reconstruct_segment(
        self,
        image: Any,
        descriptor: Mapping[str, Any],
        observation: Mapping[str, Any],
        overlap_proof: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if self._segment_inputs:
            self._segment_inputs[-1].update(image=image.copy(), observation=copy.deepcopy(observation),
                                            alignment=copy.deepcopy(overlap_proof))
        self._ensure_reconstruction()
        processor = self._reconstruction
        if processor is None or not hasattr(processor, "accept_segment"):
            return
        try:
            processor.accept_segment(
                image,
                descriptor,
                self._sequence_index - 1,
                observation,
                overlap_proof,
                already_cropped=self._already_cropped,
            )
        except Exception:
            return

    def _finalize_reconstruction(self, coverage: Optional[Mapping[str, Any]]) -> None:
        processor = self._reconstruction
        if processor is None or not hasattr(processor, "finalize"):
            return
        try:
            processor.finalize(coverage)
        except Exception:
            return

    def _request_scroll(self) -> Optional[str]:
        if self._stopped or self._cancelled():
            return self._abort_reason() if self._cancelled() else REASON_USER_STOP
        if self._timed_out():
            return REASON_TIMEOUT
        requester = self._scroll_requester
        if requester is None:
            return REASON_SCROLL_DRIVER_NOT_CONFIGURED
        if hasattr(requester, "clear_pending") and callable(requester.clear_pending):
            try:
                requester.clear_pending()
            except Exception:
                pass
        self._phase = PHASE_SCROLLING
        try:
            if hasattr(requester, "request_next_scroll") and callable(requester.request_next_scroll):
                requester.request_next_scroll()
            elif hasattr(requester, "request_scroll_down") and callable(requester.request_scroll_down):
                requester.request_scroll_down()
            elif callable(requester):
                requester()
            else:
                return REASON_SCROLL_DRIVER_NOT_CONFIGURED
        except Exception as exc:
            msg = str(exc)
            if "NOT_FOREGROUND" in msg or "HWND" in msg:
                return REASON_WINDOW_LOST
            if "NOT_STABLE_SETTLEMENT" in msg:
                return REASON_SCENE_LEFT
            if "WAREHOUSE_NOT_PRESENT" in msg:
                return REASON_WAREHOUSE_NOT_PRESENT
            if "STABLE_KEY_MISMATCH" in msg:
                return REASON_STABLE_KEY_CHANGED
            if "CANCELLED" in msg or "USER_ABORT" in msg:
                return self._abort_reason()
            if "TIMEOUT" in msg:
                return REASON_TIMEOUT
            return REASON_SCROLL_DRIVER_NOT_CONFIGURED
        self._scroll_request_count += 1
        self._emit("scroll_requested")
        return None

    def _align(self, next_id: str, roi: np.ndarray) -> Dict[str, Any]:
        self._phase = PHASE_ALIGNING
        if self._prev_roi is None or not self._prev_id:
            return {"status": "UNVERIFIED", "direction": "UNKNOWN"}
        try:
            result = self._aligner(
                self._prev_roi,
                roi,
                prev_id=self._prev_id,
                next_id=next_id,
                required_direction=DIR_DOWN,
            )
        except TypeError:
            result = self._aligner(self._prev_roi, roi)
        except Exception:
            return {"status": "UNVERIFIED", "direction": "UNKNOWN"}
        return dict(_mapping(result))

    def _wait_changed(self) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        unchanged = 0
        while not self._stopped:
            self._phase = PHASE_WAITING
            if self._pending_intake is not None:
                bundle, error = self._pending_intake, None
                self._pending_intake = None
            else:
                bundle, error = self._intake(at_start=False)
            if error:
                return None, error
            assert bundle is not None
            if not bundle["scene"]["stable"]:
                self._idle(self._poll_interval_s)
                if self._timed_out():
                    return None, REASON_TIMEOUT
                if self._cancelled():
                    return None, self._abort_reason()
                continue
            observation = bundle.get("observation") or self._observe(bundle["image"], bundle["already_cropped"])
            state = str(observation.get("scrollState") or STATE_UNKNOWN)
            change = str(observation.get("segmentChange") or STATE_UNKNOWN)
            if state == STATE_UNKNOWN:
                return None, REASON_OBSERVER_UNKNOWN
            if change != CHANGE_CHANGED:
                if change == CHANGE_UNCHANGED:
                    unchanged += 1
                else:
                    unchanged += 1
                if unchanged >= self._max_unchanged:
                    return None, REASON_CONSECUTIVE_UNCHANGED
                self._idle(self._poll_interval_s)
                continue
            try:
                payload = _encode_original(bundle["frame"], bundle["image"])
            except Exception:
                return None, REASON_STORE_FAILED
            digest = hashlib.sha256(payload).hexdigest()
            if digest in self._saved_hashes:
                unchanged += 1
                if unchanged >= self._max_unchanged:
                    return None, REASON_CONSECUTIVE_UNCHANGED
                self._idle(self._poll_interval_s)
                continue
            bundle["payload"] = payload
            bundle["observation"] = observation
            return bundle, None
        return None, self._abort_reason() if self._cancelled() else REASON_USER_STOP

    def _capture_top_support(self, first_bundle, first_descriptor, state):
        """At most two passive samples before scrolling; never extend the deadline."""
        for _ in range(self._top_support_attempts):
            self._idle(min(0.5, max(0.2, self._poll_interval_s)))
            bundle, error = self._intake(at_start=False)
            if error:
                return error
            observation = self._observe(bundle["image"], bundle["already_cropped"])
            bundle["observation"] = observation
            if not bundle["scene"]["stable"] or observation.get("scrollState") != state:
                # Keep a movement frame for the normal coverage path, without
                # requesting another wheel pulse before consuming it.
                self._pending_intake = bundle
                return REASON_OBSERVER_UNKNOWN if state == STATE_NO_SCROLL else None
            proof = stationary_support_proof(first_bundle["roi"], bundle["roi"])
            if proof is None:
                continue
            try:
                payload = _encode_original(bundle["frame"], bundle["image"])
            except Exception:
                return REASON_STORE_FAILED
            descriptor, error = self._persist(payload)
            if error == "duplicate":
                continue
            if error:
                return error
            overlap = {"trusted": True, "aligned": True, "proofId": proof["proofId"],
                       "previousEvidenceId": first_descriptor["evidenceId"]}
            error = self._add_segment(descriptor, overlap_proof=overlap,
                top_proof=_endpoint_proof("top", observation),
                bottom_proof=_endpoint_proof("bottom", observation) if state == STATE_NO_SCROLL else None)
            if error:
                return error
            self._reconstruct_segment(bundle["image"], descriptor, observation, {**proof, **overlap})
            self._prev_roi = bundle["roi"].copy()
            self._prev_id = str(descriptor["evidenceId"])
            self._emit("support_frame_saved")
            break
        return None

    def _run(self) -> Dict[str, Any]:
        self._emit("session_constructed")
        install_error = self._install_input_guard()
        if install_error:
            return self._reject(install_error)
        if self._cancelled():
            return self._reject(self._abort_reason())
        if self._timed_out():
            return self._reject(REASON_TIMEOUT)

        self._phase = PHASE_CAPTURING
        bundle, error = self._intake(at_start=True)
        if error:
            return self._reject(error)
        assert bundle is not None
        self._key = bundle["scene"]["record_stable_key"]
        observation = self._observe(bundle["image"], bundle["already_cropped"])
        state = str(observation.get("scrollState") or STATE_UNKNOWN)
        if state == STATE_MIDDLE and self._resume_source is not None:
            if self._scroll_requester is None:
                return self._reject(REASON_SCROLL_DRIVER_NOT_CONFIGURED)
            resume_error = self._restore_resume(bundle, state)
            if resume_error:
                return self._stop(resume_error) if self._accepted else self._reject(resume_error)
            self._arm_input_guard()
            return self._capture_remaining()
        self._resume_source = None
        if state not in (STATE_TOP, STATE_NO_SCROLL):
            return self._reject(REASON_START_REQUIRES_TOP)
        if state == STATE_TOP and self._scroll_requester is None:
            return self._reject(REASON_SCROLL_DRIVER_NOT_CONFIGURED)

        self._accepted = True
        self._ledger = self._ledger_factory(self._key)
        try:
            payload = _encode_original(bundle["frame"], bundle["image"])
        except Exception:
            return self._stop(REASON_STORE_FAILED)
        descriptor, persist_error = self._persist(payload)
        if persist_error:
            return self._stop(REASON_STORE_FAILED)
        assert descriptor is not None
        if state == STATE_NO_SCROLL:
            add_error = self._add_segment(
                descriptor,
                top_proof=_endpoint_proof("top", observation),
                bottom_proof=_endpoint_proof("bottom", observation),
            )
            if add_error:
                return self._stop(add_error)
            self._reconstruct_segment(bundle["image"], descriptor, observation, None)
            self._emit("segment_saved")
            error = self._capture_top_support(bundle, descriptor, state)
            if error:
                return self._stop(error)
            return self._stop(REASON_COMPLETE, complete=True)

        add_error = self._add_segment(descriptor, top_proof=_endpoint_proof("top", observation))
        if add_error:
            return self._stop(add_error)
        self._reconstruct_segment(bundle["image"], descriptor, observation, None)
        self._prev_roi = bundle["roi"].copy()
        self._prev_id = str(descriptor["evidenceId"])
        self._emit("segment_saved")
        self._arm_input_guard()
        support_error = self._capture_top_support(bundle, descriptor, state)
        if support_error:
            return self._stop(support_error)

        return self._capture_remaining()

    def _capture_remaining(self) -> Dict[str, Any]:
        while not self._stopped:
            if self._cancelled():
                return self._stop(self._abort_reason())
            if self._timed_out():
                return self._stop(REASON_TIMEOUT)
            if self._pending_intake is None and self._scroll_request_count >= self._max_steps:
                return self._stop(REASON_SAFETY_STEP_LIMIT)
            if self._pending_intake is None:
                request_error = self._request_scroll()
                if request_error:
                    return self._stop(request_error)
            nxt, wait_error = self._wait_changed()
            if wait_error:
                return self._stop(wait_error)
            assert nxt is not None
            observation = nxt["observation"]
            state = str(observation.get("scrollState") or STATE_UNKNOWN)
            if state == STATE_UNKNOWN:
                return self._stop(REASON_OBSERVER_UNKNOWN)
            if state == STATE_NO_SCROLL:
                return self._stop(REASON_OBSERVER_UNKNOWN)
            descriptor, persist_error = self._persist(nxt["payload"])
            if persist_error:
                return self._stop(REASON_STORE_FAILED)
            assert descriptor is not None
            alignment = self._align(str(descriptor["evidenceId"]), nxt["roi"])
            status = str(alignment.get("status") or "")
            direction = str(alignment.get("direction") or "")
            progression_verified = bool(
                alignment.get("progressionVerified") or (status == STATUS_VERIFIED and direction == DIR_DOWN)
            )
            overlap = None
            if progression_verified and direction == DIR_DOWN:
                overlap = _overlap_proof(str(self._prev_id), str(descriptor["evidenceId"]), alignment)
            bottom = _endpoint_proof("bottom", observation) if state == STATE_BOTTOM else None
            add_error = self._add_segment(descriptor, bottom_proof=bottom, overlap_proof=overlap)
            if add_error:
                return self._stop(add_error)
            self._reconstruct_segment(nxt["image"], descriptor, observation, alignment)
            self._prev_roi = nxt["roi"].copy()
            self._prev_id = str(descriptor["evidenceId"])
            self._emit("segment_saved")
            if status == STATUS_CONFLICT:
                return self._stop(REASON_OVERLAP_CONFLICT)
            if overlap is None:
                return self._stop(REASON_OVERLAP_UNVERIFIED)
            if state == STATE_BOTTOM:
                return self._stop(REASON_COMPLETE, complete=True)
            if state not in (STATE_TOP, STATE_MIDDLE):
                return self._stop(REASON_OBSERVER_UNKNOWN)
        return self._stop(self._abort_reason() if self._cancelled() else REASON_USER_STOP)
