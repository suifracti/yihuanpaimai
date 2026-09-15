"""One-time, short-lived warehouse capture arming tokens.

Prepare is read-only. Confirm re-checks bindings before any OS input.
Tokens never include paths, hashes, or raw input history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

CONFIRM_CAPTION = (
    "程序仅在结算页滚动仓库；按 Esc、点击、滚轮或任意按键会立即停止；"
    "不会点击、出价或返回顶部；未完整覆盖会保存为部分。"
)

TOKEN_TTL_S = 12.0
REASON_PREPARED = "PREPARED"
REASON_NOT_SETTLEMENT = "NOT_SETTLEMENT"
REASON_TOKEN_INVALID = "TOKEN_INVALID"
REASON_TOKEN_EXPIRED = "TOKEN_EXPIRED"
REASON_TOKEN_REUSED = "TOKEN_REUSED"
REASON_BINDING_CHANGED = "BINDING_CHANGED"
REASON_STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
REASON_START_REQUIRES_TOP = "START_REQUIRES_TOP"


@dataclass
class WarehouseCaptureArmingToken:
    token_id: str
    record_stable_key: str
    hwnd: int
    scene: str
    warehouse_roi: Tuple[int, int, int, int]
    scroll_state: str
    created_at: float
    ttl_s: float = TOKEN_TTL_S
    consumed: bool = False

    def expired(self, now: float) -> bool:
        return float(now) - float(self.created_at) > float(self.ttl_s)

    def consume(self) -> bool:
        if self.consumed:
            return False
        self.consumed = True
        return True


def snapshot_bindings(raw: Any) -> Optional[dict]:
    if not isinstance(raw, Mapping):
        return None
    key = str(raw.get("recordStableKey") or raw.get("record_stable_key") or "").strip()
    try:
        hwnd = int(raw.get("hwnd") or 0)
    except (TypeError, ValueError):
        hwnd = 0
    roi = raw.get("warehouseRoi") or raw.get("warehouse_roi")
    if isinstance(roi, (list, tuple)) and len(roi) == 4:
        try:
            roi_t = (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
        except (TypeError, ValueError):
            roi_t = (0, 0, 0, 0)
    else:
        roi_t = (0, 0, 0, 0)
    scene = "SETTLEMENT" if (
        raw.get("isSettlement") or raw.get("is_settlement") or str(raw.get("scene") or "") == "SETTLEMENT"
    ) else str(raw.get("scene") or "UNKNOWN")
    warehouse_present = raw.get("warehousePresent")
    if warehouse_present is None:
        warehouse_present = raw.get("warehouse_present")
    if warehouse_present is None:
        frame = raw.get("frame")
        if frame is not None:
            try:
                from warehouse_grid_geometry import observe_warehouse_grid

                grid_obs = observe_warehouse_grid(frame, already_cropped=bool(raw.get("already_cropped", False)))
                warehouse_present = grid_obs.get("grid", {}).get("status") == "OK"
            except Exception:
                warehouse_present = False
        else:
            warehouse_present = True
    else:
        warehouse_present = bool(warehouse_present)

    return {
        "isSettlement": scene == "SETTLEMENT",
        "stable": bool(raw.get("stable", raw.get("isStable", False))),
        "recordStableKey": key,
        "hwnd": hwnd,
        "warehouseRoi": roi_t,
        "scrollState": str(raw.get("scrollState") or raw.get("scroll_state") or "UNKNOWN"),
        "warehousePresent": warehouse_present,
        "storeAvailable": bool(raw.get("storeAvailable", True)),
        "foreground": bool(raw.get("foreground", True)),
        "visible": bool(raw.get("visible", True)),
        "minimized": bool(raw.get("minimized", False)),
        "scene": scene,
    }


def bindings_match(token: WarehouseCaptureArmingToken, snap: Mapping[str, Any]) -> bool:
    if not token or not isinstance(snap, Mapping):
        return False
    roi = snap.get("warehouseRoi") or (0, 0, 0, 0)
    return (
        token.record_stable_key == str(snap.get("recordStableKey") or "")
        and int(token.hwnd) == int(snap.get("hwnd") or 0)
        and token.scene == str(snap.get("scene") or "")
        and tuple(token.warehouse_roi) == tuple(roi)
    )


def issue_arming_token(snap: Mapping[str, Any], *, now: float, ttl_s: float = TOKEN_TTL_S) -> WarehouseCaptureArmingToken:
    roi = snap.get("warehouseRoi") or (0, 0, 0, 0)
    return WarehouseCaptureArmingToken(
        token_id=uuid.uuid4().hex,
        record_stable_key=str(snap.get("recordStableKey") or ""),
        hwnd=int(snap.get("hwnd") or 0),
        scene=str(snap.get("scene") or "UNKNOWN"),
        warehouse_roi=(int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])),
        scroll_state=str(snap.get("scrollState") or "UNKNOWN"),
        created_at=float(now),
        ttl_s=float(ttl_s),
    )
