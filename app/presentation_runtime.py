"""Read-only presentation runtime state for the native Main Window."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional


SNAPSHOT_VERSION = 1
VISION_PROCESS_STATES = frozenset(("running", "stopped", "exited", "disabled"))


@dataclass(frozen=True)
class PresentationRuntimeSnapshot:
    """Immutable, scalar-only snapshot safe to serialize into the Main WebView."""

    snapshot_version: int = SNAPSHOT_VERSION
    vision_process_state: str = "stopped"
    refresh_pending: bool = False
    scene_class: str = "unknown"
    shadow_updating: bool = False

    def to_payload(self) -> dict:
        """Return a fresh JSON-safe object; never expose the frozen object itself."""
        return {
            "snapshotVersion": self.snapshot_version,
            "visionProcessState": self.vision_process_state,
            "refreshPending": self.refresh_pending,
            "sceneClass": self.scene_class,
            "shadowUpdating": self.shadow_updating,
        }


class PresentationRuntimeState:
    """Thread-safe reducer that retains only approved presentation scalars."""

    def __init__(self, vision_process_state: str = "stopped"):
        self._lock = threading.Lock()
        self._snapshot = PresentationRuntimeSnapshot(
            vision_process_state=self._validate_vision_state(vision_process_state)
        )
        self._active_refresh_request_id: Optional[str] = None

    def snapshot(self) -> PresentationRuntimeSnapshot:
        with self._lock:
            return self._snapshot

    def set_vision_process_state(self, state: str) -> None:
        state = self._validate_vision_state(state)
        with self._lock:
            next_snapshot = self._snapshot
            if next_snapshot.vision_process_state != state:
                next_snapshot = replace(next_snapshot, vision_process_state=state)
            if state != "running" and next_snapshot.refresh_pending:
                self._active_refresh_request_id = None
                next_snapshot = replace(next_snapshot, refresh_pending=False)
            self._snapshot = next_snapshot

    def begin_refresh(self, request_id: str) -> None:
        request_id = self._validate_request_id(request_id)
        with self._lock:
            self._active_refresh_request_id = request_id
            if not self._snapshot.refresh_pending:
                self._snapshot = replace(self._snapshot, refresh_pending=True)

    def observe_transport(self, payload: Mapping[str, Any]) -> None:
        """Copy approved scalar observations without retaining the source mapping."""
        if not isinstance(payload, Mapping):
            return

        scene_class = self._classify_scene(payload)
        shadow_value = payload.get("shadowUpdating")
        shadow_explicit = isinstance(shadow_value, bool)
        refresh_value = payload.get("refreshPending")
        refresh_id = payload.get("refreshRequestId")

        with self._lock:
            if (
                isinstance(refresh_value, bool)
                and isinstance(refresh_id, str)
                and self._active_refresh_request_id is not None
                and refresh_id != self._active_refresh_request_id
            ):
                return
            next_snapshot = self._snapshot

            if scene_class is not None:
                next_snapshot = replace(next_snapshot, scene_class=scene_class)
                if scene_class != "auction":
                    next_snapshot = replace(next_snapshot, shadow_updating=False)

            if shadow_explicit and (scene_class is None or scene_class == "auction"):
                next_snapshot = replace(
                    next_snapshot, shadow_updating=bool(shadow_value)
                )

            # Refresh authority starts in begin_refresh(). A completion may clear
            # only the current request; stale or unsolicited payloads are ignored.
            if isinstance(refresh_value, bool) and isinstance(refresh_id, str):
                if (
                    refresh_value is False
                    and refresh_id == self._active_refresh_request_id
                ):
                    self._active_refresh_request_id = None
                    next_snapshot = replace(next_snapshot, refresh_pending=False)

            self._snapshot = next_snapshot

    @staticmethod
    def _classify_scene(payload: Mapping[str, Any]) -> Optional[str]:
        keys = (
            "scene",
            "solverStatus",
            "isLoading",
            "inAuction",
            "inLobby",
            "gameDetected",
        )
        if not any(key in payload for key in keys):
            return None

        scene = str(payload.get("scene") or "").upper()
        solver_status = str(payload.get("solverStatus") or "").lower()
        if (
            payload.get("isLoading") is True
            or scene == "AUCTION_LOADING"
            or solver_status == "loading"
        ):
            return "loading"
        if payload.get("inAuction") is True or scene in ("IN_AUCTION", "AUCTION"):
            return "auction"
        if payload.get("inLobby") is True or scene == "AUCTION_LOBBY" or solver_status == "lobby":
            return "lobby"
        if solver_status.startswith("nav_") or scene in (
            "OPEN_WORLD",
            "CITY_TYCOON_HUB",
            "CITY_LEISURE_MENU",
        ):
            return "navigation"
        return "unknown"

    @staticmethod
    def _validate_vision_state(state: str) -> str:
        if state not in VISION_PROCESS_STATES:
            raise ValueError(f"Unsupported vision process state: {state!r}")
        return state

    @staticmethod
    def _validate_request_id(request_id: str) -> str:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("Refresh request id must be a non-empty string")
        return request_id
