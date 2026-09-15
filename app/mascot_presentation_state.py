"""Native-owned, presentation-only mascot state selection.

This module deliberately depends only on the immutable presentation runtime
snapshot and the verified mascot presentation contract.  It is the sole owner
of automatic mascot state selection for both Main and Desktop Pet consumers.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from presentation_runtime import PresentationRuntimeSnapshot


SNAPSHOT_VERSION = 1
AUTOMATIC_STATES = frozenset(("idle", "loading", "thinking", "sleep"))
REQUIRED_STATES = frozenset(
    ("idle", "loading", "thinking", "success", "warning", "sleep")
)


@dataclass(frozen=True)
class MascotPresentationSnapshot:
    """Immutable, JSON-safe identity of one approved presentation asset."""

    snapshot_version: int
    state: str
    asset_id: str

    def to_payload(self) -> dict:
        return {
            "snapshotVersion": self.snapshot_version,
            "state": self.state,
            "assetId": self.asset_id,
        }


class MascotPresentationStateCoordinator:
    """Select one automatic mascot state for every presentation consumer."""

    def __init__(self, mascot_presentation_contract: Mapping):
        if not isinstance(mascot_presentation_contract, Mapping):
            raise TypeError("Mascot presentation contract must be a mapping")
        if mascot_presentation_contract.get("mode") != "presentation_only":
            raise ValueError("Mascot contract exceeds presentation authority")

        declared_states = mascot_presentation_contract.get("states")
        declared_assets = mascot_presentation_contract.get("assets")
        if not isinstance(declared_states, Mapping) or not isinstance(
            declared_assets, Mapping
        ):
            raise ValueError("Mascot contract is missing states or assets")
        if set(declared_states) != REQUIRED_STATES:
            raise ValueError("Mascot contract has an unexpected state surface")

        state_assets = {}
        for state, asset_id in declared_states.items():
            record = declared_assets.get(asset_id)
            if not isinstance(record, Mapping) or record.get("role") != "chibi_state":
                raise ValueError(f"Mascot state {state!r} has no approved chibi asset")
            state_assets[str(state)] = str(asset_id)

        fallback = mascot_presentation_contract.get("fallbackState")
        if fallback != "idle":
            raise ValueError("Mascot automatic fallback must remain idle")

        self._state_assets = MappingProxyType(state_assets)
        self._lock = threading.Lock()
        self._snapshot = self._build_snapshot("idle")

    @property
    def state_assets(self) -> Mapping[str, str]:
        return self._state_assets

    def update(
        self,
        application_state: str,
        presentation_runtime: PresentationRuntimeSnapshot,
    ) -> MascotPresentationSnapshot:
        if not isinstance(presentation_runtime, PresentationRuntimeSnapshot):
            raise TypeError("Mascot state requires an immutable presentation snapshot")

        state = self._select_state(application_state, presentation_runtime)
        with self._lock:
            if self._snapshot.state != state:
                self._snapshot = self._build_snapshot(state)
            return self._snapshot

    def snapshot(self) -> MascotPresentationSnapshot:
        with self._lock:
            return self._snapshot

    def _build_snapshot(self, state: str) -> MascotPresentationSnapshot:
        if state not in AUTOMATIC_STATES:
            raise ValueError(f"State is not automatic: {state!r}")
        return MascotPresentationSnapshot(
            snapshot_version=SNAPSHOT_VERSION,
            state=state,
            asset_id=self._state_assets[state],
        )

    @staticmethod
    def _select_state(
        application_state: str,
        runtime: PresentationRuntimeSnapshot,
    ) -> str:
        if application_state == "shutting_down":
            return "sleep"
        if runtime.refresh_pending:
            return "loading"
        if runtime.scene_class == "loading":
            return "loading"
        if runtime.shadow_updating:
            return "thinking"
        return "idle"
