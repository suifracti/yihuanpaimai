# -*- coding: utf-8 -*-
"""Warehouse active-scan freeze guard and collision protection.

Immediately freezes the active scanning chain, halts automated wheel drivers,
and pauses progress advancement when any of 4 freeze conditions occur:
1. USER_KEYBOARD_INPUT: User pressed any key (escape, typing, hotkeys).
2. FOCUS_LOST: Game window lost foreground focus, was minimized, or obscured.
3. GAME_INTERACTION_CONFLICT: Bidding round transition, auction prompt, or dialog.
4. USER_TAKEOVER: User mouse interaction outside scan region or manual wheel input.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

SCHEMA_VERSION = "warehouse-active-scan-freeze.v1"

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
    """Manages active scan freeze conditions and enforces scroll/progress halt."""

    def __init__(self, on_freeze_callback: Optional[Callable[[str], None]] = None):
        self._is_frozen: bool = False
        self._freeze_reason: Optional[str] = None
        self._frozen_at: Optional[float] = None
        self._freeze_events: List[Dict[str, Any]] = []
        self._on_freeze_callback = on_freeze_callback

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

    def trigger_freeze(self, reason: str, details: Optional[Mapping[str, Any]] = None) -> bool:
        """Trigger scan freeze under specified condition.

        Returns True if state transitioned to frozen.
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
            except Exception:
                pass

        return True

    def assert_scroll_permitted(self) -> None:
        """Raise WarehouseScanFrozenError if scrolling is forbidden due to freeze."""
        if self._is_frozen:
            raise WarehouseScanFrozenError(self._freeze_reason or "SCAN_FROZEN")

    def unfreeze_rearmed(self, arming_token: str) -> bool:
        """Explicitly unfreeze upon clean re-arming."""
        if not arming_token or not str(arming_token).strip():
            return False
        self._is_frozen = False
        self._freeze_reason = None
        self._frozen_at = None
        return True

    def to_payload(self) -> Dict[str, Any]:
        """Serialize freeze status for HUD / diagnostics."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "isFrozen": self._is_frozen,
            "freezeReason": self._freeze_reason,
            "frozenAt": self._frozen_at,
            "scrollPermitted": self.scroll_permitted,
            "progressFrozen": self.progress_frozen,
            "eventCount": len(self._freeze_events),
            "latestEvent": self._freeze_events[-1] if self._freeze_events else None,
        }
