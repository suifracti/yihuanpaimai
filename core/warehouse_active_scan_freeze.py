# -*- coding: utf-8 -*-
"""Warehouse active-scan freeze guard and scan safety coordinator (SSOT).

Immediately freezes the active scanning chain, halts automated wheel drivers,
and pauses progress advancement when any of 4 freeze conditions occur:
1. USER_KEYBOARD_INPUT: User pressed any key (escape, typing, hotkeys).
2. FOCUS_LOST: Game window lost foreground focus, was minimized, or obscured.
3. GAME_INTERACTION_CONFLICT: Bidding round transition, auction prompt, or dialog.
4. USER_TAKEOVER: User mouse interaction outside scan region or manual wheel input.

Enforces:
- Single SSOT Authority: Coordinates both scroll path and progress tracker.
- Strict Scroll Precheck: Scroll requests must pass precheck; if frozen, request is rejected, wheel count += 0.
- Halt Callback Provenance: Callback exceptions are recorded (haltCallbackFailed=True); scroll remains blocked.
- Explicit Re-arm Contract: Unfreezing requires strict manual confirmation + clean validation of focus,
  conflict, and user takeover conditions. Simple tokens are rejected.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "warehouse-active-scan-freeze.v2"

FREEZE_REASON_KEYBOARD = "USER_KEYBOARD_INPUT"
FREEZE_REASON_FOCUS_LOST = "FOCUS_LOST"
FREEZE_REASON_GAME_CONFLICT = "GAME_INTERACTION_CONFLICT"
FREEZE_REASON_TAKEOVER = "USER_TAKEOVER"

VALID_FREEZE_REASONS = frozenset({
    FREEZE_REASON_KEYBOARD,
    FREEZE_REASON_FOCUS_LOST,
    FREEZE_REASON_GAME_CONFLICT,
    FREEZE_REASON_TAKEOVER,
})


class WarehouseScanFrozenError(RuntimeError):
    """Raised when an operation is attempted while active scan is frozen."""
    def __init__(self, reason: str):
        super().__init__(f"Active warehouse scan is frozen: {reason}")
        self.reason = reason


class WarehouseActiveScanFreezeGuard:
    """SSOT Authority managing active scan freeze conditions and enforcing scroll/progress halt."""

    def __init__(self, on_freeze_callback: Optional[Callable[[str], None]] = None):
        self._is_frozen: bool = False
        self._freeze_reason: Optional[str] = None
        self._frozen_at: Optional[float] = None
        self._freeze_events: List[Dict[str, Any]] = []
        self._rearm_events: List[Dict[str, Any]] = []
        self._on_freeze_callback = on_freeze_callback

        # Halt callback execution metrics
        self._halt_callback_failed: bool = False
        self._halt_callback_error: Optional[str] = None

        # Scroll execution metrics (SSOT precheck)
        self._scroll_requests_attempted: int = 0
        self._scroll_requests_blocked: int = 0
        self._scroll_requests_executed: int = 0

    @property
    def is_frozen(self) -> bool:
        return self._is_frozen

    @property
    def freeze_reason(self) -> Optional[str]:
        return self._freeze_reason

    @property
    def scroll_permitted(self) -> bool:
        """Returns True only when scan is active and not frozen."""
        return not self._is_frozen

    @property
    def progress_frozen(self) -> bool:
        """Returns True when progress advancement is halted."""
        return self._is_frozen

    @property
    def halt_callback_failed(self) -> bool:
        return self._halt_callback_failed

    @property
    def halt_callback_error(self) -> Optional[str]:
        return self._halt_callback_error

    @property
    def scroll_requests_blocked(self) -> int:
        return self._scroll_requests_blocked

    @property
    def scroll_requests_executed(self) -> int:
        return self._scroll_requests_executed

    def trigger_freeze(self, reason: str, details: Optional[Mapping[str, Any]] = None) -> bool:
        """Trigger scan freeze under specified condition.

        Immediately sets is_frozen=True and executes halt callback.
        If halt callback fails, records provenance without unblocking safety.
        """
        r_str = str(reason or "").strip()
        if r_str not in VALID_FREEZE_REASONS:
            r_str = FREEZE_REASON_TAKEOVER  # Default safe takeover

        now = time.time()
        self._is_frozen = True
        self._freeze_reason = r_str
        self._frozen_at = now

        evt = {
            "reason": r_str,
            "timestamp": now,
            "details": dict(details or {}),
        }
        self._freeze_events.append(evt)

        if self._on_freeze_callback:
            try:
                self._on_freeze_callback(r_str)
                self._halt_callback_failed = False
                self._halt_callback_error = None
            except Exception as e:
                # Do NOT silently swallow: record failure provenance, but keep scan strictly blocked!
                self._halt_callback_failed = True
                self._halt_callback_error = f"{type(e).__name__}: {e}"

        return True

    # Real trigger adapter methods
    def on_input_abort_signal(self, event_kind: str, details: Optional[Mapping[str, Any]] = None) -> bool:
        """Adapter: receive input abort event from input monitor / hook."""
        k = str(event_kind or "").upper()
        if "KEY" in k:
            reason = FREEZE_REASON_KEYBOARD
        else:
            reason = FREEZE_REASON_TAKEOVER
        return self.trigger_freeze(reason, details)

    def on_focus_lost(self, details: Optional[Mapping[str, Any]] = None) -> bool:
        """Adapter: receive foreground focus loss event from window tracker."""
        return self.trigger_freeze(FREEZE_REASON_FOCUS_LOST, details)

    def on_game_conflict(self, details: Optional[Mapping[str, Any]] = None) -> bool:
        """Adapter: receive bidding round / modal conflict signal."""
        return self.trigger_freeze(FREEZE_REASON_GAME_CONFLICT, details)

    # Scroll precheck & dispatch (Single SSOT)
    def precheck_scroll_permitted(self) -> bool:
        """Precheck before sending any scroll pulse.

        Returns True if scroll is permitted.
        If frozen, records blocked count, guarantees wheel count += 0, returns False.
        """
        self._scroll_requests_attempted += 1
        if self._is_frozen:
            self._scroll_requests_blocked += 1
            return False
        return True

    def execute_scroll_request(
        self,
        scroll_fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a scroll pulse through the SSOT guard precheck.

        If frozen: rejects immediately, never calls scroll_fn, returns None.
        If permitted: calls scroll_fn and increments executed count.
        """
        if not self.precheck_scroll_permitted():
            return None
        self._scroll_requests_executed += 1
        return scroll_fn(*args, **kwargs)

    def assert_scroll_permitted(self) -> None:
        """Raise WarehouseScanFrozenError if scrolling is forbidden due to freeze."""
        if self._is_frozen:
            raise WarehouseScanFrozenError(self._freeze_reason or "SCAN_FROZEN")

    # Strict Re-arm Contract
    def attempt_rearm(
        self,
        *,
        manual_rearm_confirmed: bool = False,
        target_focus_valid: bool = False,
        no_game_conflict: bool = False,
        no_user_takeover_active: bool = False,
        details: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        """Attempt safe manual re-arm.

        Requires strict boolean True on all 4 safety criteria:
        1. manual_rearm_confirmed: explicit human confirmation (not arbitrary string token).
        2. target_focus_valid: target window confirmed in foreground.
        3. no_game_conflict: no active modal / bidding conflict.
        4. no_user_takeover_active: no ongoing user keyboard or mouse takeover.

        If any criterion is False, rearm is rejected and system remains frozen.
        """
        if not (isinstance(manual_rearm_confirmed, bool) and manual_rearm_confirmed is True):
            return False
        if not (isinstance(target_focus_valid, bool) and target_focus_valid is True):
            return False
        if not (isinstance(no_game_conflict, bool) and no_game_conflict is True):
            return False
        if not (isinstance(no_user_takeover_active, bool) and no_user_takeover_active is True):
            return False

        self._is_frozen = False
        self._freeze_reason = None
        self._frozen_at = None
        self._halt_callback_failed = False
        self._halt_callback_error = None

        self._rearm_events.append({
            "timestamp": time.time(),
            "details": dict(details or {}),
        })
        return True

    def unfreeze_rearmed(self, arming_token: str) -> bool:
        """Deprecated legacy interface: rejected unless explicitly verified via attempt_rearm."""
        # Arbitrary token alone is explicitly disallowed as proof of safety
        return False

    def to_payload(self) -> Dict[str, Any]:
        """Serialize freeze status for HUD / diagnostics."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "isFrozen": self._is_frozen,
            "freezeReason": self._freeze_reason,
            "frozenAt": self._frozen_at,
            "scrollPermitted": self.scroll_permitted,
            "progressFrozen": self.progress_frozen,
            "haltCallbackFailed": self._halt_callback_failed,
            "haltCallbackError": self._halt_callback_error,
            "scrollMetrics": {
                "attempted": self._scroll_requests_attempted,
                "blocked": self._scroll_requests_blocked,
                "executed": self._scroll_requests_executed,
            },
            "eventCount": len(self._freeze_events),
            "rearmCount": len(self._rearm_events),
            "latestEvent": self._freeze_events[-1] if self._freeze_events else None,
        }


# Alias for safety coordinator architecture
WarehouseScanSafetyCoordinator = WarehouseActiveScanFreezeGuard
