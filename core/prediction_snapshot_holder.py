# -*- coding: utf-8 -*-
"""Authoritative runtime prediction snapshot sidecar holder.

Maintains strictly one active prediction snapshot bound to matchId.
CurrentMatch is NEVER polluted with Solver inference output.
"""

from __future__ import annotations

from dataclasses import dataclass
import copy
from typing import Any, Dict, Optional


@dataclass
class ActivePredictionSnapshotHolder:
    match_id: Optional[str] = None
    snapshot: Optional[Dict[str, Any]] = None
    frozen_prediction: Optional[Dict[str, Any]] = None

    def clear(self) -> None:
        self.match_id = None
        self.snapshot = None
        self.frozen_prediction = None

    def update(
        self,
        match_id: str,
        snapshot: Optional[Dict[str, Any]] = None,
        frozen_prediction: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not match_id:
            return False
        mid = str(match_id).strip()
        if not mid:
            return False
        if snapshot and isinstance(snapshot, dict):
            snap_mid = str(snapshot.get("matchId") or "").strip()
            if snap_mid and snap_mid != mid:
                return False
        if self.match_id != mid:
            self.clear()
        if snapshot and isinstance(snapshot, dict):
            self.snapshot = copy.deepcopy(snapshot)
        if frozen_prediction and isinstance(frozen_prediction, dict):
            self.frozen_prediction = copy.deepcopy(frozen_prediction)
        self.match_id = mid
        return True

    def get_snapshot_for_match(self, match_id: str) -> Optional[Dict[str, Any]]:
        if not match_id or not self.match_id:
            return None
        if str(match_id).strip() == self.match_id:
            return self.snapshot
        return None

    def get_frozen_for_match(self, match_id: str) -> Optional[Dict[str, Any]]:
        if not match_id or not self.match_id:
            return None
        if str(match_id).strip() == self.match_id:
            return self.frozen_prediction
        return None


ACTIVE_SNAPSHOT_HOLDER = ActivePredictionSnapshotHolder()
