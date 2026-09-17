# -*- coding: utf-8 -*-
"""Warehouse scan progress monotonicity and anti-teleportation tracker and guard.

Enforces:
1. Strict monotonicity: progress is strictly non-decreasing during an active scan sequence.
2. Anti-teleportation: forbids jumping directly 0% -> 100% or large unproven leaps without
   observable physical evidence (scrollbar travel, verified overlap, segment continuity).
3. Decoupling: progress != complete. Even 100% progress does not imply warehouse COMPLETE.
4. Canonical #4 status: explicitly outputs canonicalTask4Status = 'UNFINISHED'.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "warehouse-scan-progress.v1"
CANONICAL_TASK4_STATUS = "UNFINISHED"

MAX_ALLOWABLE_SINGLE_STEP_JUMP = 0.35


class WarehouseScanProgressError(ValueError):
    """Raised on invalid progress arguments or illegal state transitions."""
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class WarehouseScanProgressTracker:
    """Tracks warehouse scan progress backed by multi-modal observable evidence."""

    def __init__(
        self,
        expected_total_steps: int = 16,
        expected_total_height_px: Optional[float] = None,
        enforce_strict_guards: bool = True,
    ):
        if expected_total_steps <= 0:
            raise WarehouseScanProgressError("INVALID_EXPECTED_STEPS", "expected_total_steps must be > 0")
        self.expected_total_steps = expected_total_steps
        self.expected_total_height_px = float(expected_total_height_px) if expected_total_height_px else None
        self.enforce_strict_guards = enforce_strict_guards

        self._progress_ratio: float = 0.0
        self._step_count: int = 0
        self._verified_overlap_count: int = 0
        self._cumulative_displacement_px: float = 0.0
        self._scrollbar_travel_ratio: float = 0.0
        self._scrollbar_state: str = "TOP"
        self._is_frozen: bool = False
        self._freeze_reason: Optional[str] = None
        self._teleportation_attempts_blocked: int = 0
        self._monotonicity_violations_blocked: int = 0
        self._history: List[Dict[str, Any]] = []

    @property
    def progress_ratio(self) -> float:
        return self._progress_ratio

    @property
    def is_complete(self) -> bool:
        # Progress != Complete! Completeness requires formal endpoint ledger proof.
        return False

    @property
    def is_frozen(self) -> bool:
        return self._is_frozen

    @property
    def freeze_reason(self) -> Optional[str]:
        return self._freeze_reason

    def freeze(self, reason: str = "EXTERNAL_FREEZE") -> None:
        """Freeze active progress advancement."""
        self._is_frozen = True
        self._freeze_reason = reason

    def unfreeze(self) -> None:
        """Unfreeze progress advancement upon verified re-arm."""
        self._is_frozen = False
        self._freeze_reason = None

    def update_from_observation(
        self,
        *,
        scrollbar_state: Optional[str] = None,
        scrollbar_ratio: Optional[float] = None,
        verified_offset_px: Optional[float] = None,
        segment_index: Optional[int] = None,
        has_verified_overlap: bool = False,
        raw_progress_hint: Optional[float] = None,
    ) -> float:
        """Update scan progress using physical observable evidence."""
        if self._is_frozen:
            return self._progress_ratio

        if scrollbar_state:
            self._scrollbar_state = str(scrollbar_state).upper()

        if isinstance(verified_offset_px, (int, float)) and not isinstance(verified_offset_px, bool):
            if verified_offset_px > 0 and has_verified_overlap:
                self._cumulative_displacement_px += float(verified_offset_px)
                self._verified_overlap_count += 1

        if has_verified_overlap and not (isinstance(verified_offset_px, (int, float)) and verified_offset_px > 0):
            self._verified_overlap_count += 1

        is_backward_attempt = False
        if isinstance(segment_index, int) and not isinstance(segment_index, bool):
            if segment_index < self._step_count:
                is_backward_attempt = True
            self._step_count = max(self._step_count, segment_index)
        else:
            self._step_count += 1

        if isinstance(scrollbar_ratio, (int, float)) and not isinstance(scrollbar_ratio, bool):
            r_clamped = max(0.0, min(1.0, float(scrollbar_ratio)))
            if r_clamped < self._scrollbar_travel_ratio:
                is_backward_attempt = True
            self._scrollbar_travel_ratio = max(self._scrollbar_travel_ratio, r_clamped)

        # 1. Evidence-backed candidate progress calculation
        evidence_components: List[Tuple[float, float]] = []

        # Scrollbar evidence
        if self._scrollbar_travel_ratio > 0.0:
            evidence_components.append((0.40, self._scrollbar_travel_ratio))
        elif self._scrollbar_state == "TOP":
            evidence_components.append((0.20, 0.05))
        elif self._scrollbar_state == "BOTTOM":
            evidence_components.append((0.40, 0.95))

        # Overlap displacement evidence
        if self.expected_total_height_px and self.expected_total_height_px > 0:
            disp_ratio = min(1.0, self._cumulative_displacement_px / self.expected_total_height_px)
            evidence_components.append((0.35, disp_ratio))
        elif self._verified_overlap_count > 0:
            step_overlap_ratio = min(1.0, self._verified_overlap_count / max(1, self.expected_total_steps - 1))
            evidence_components.append((0.35, step_overlap_ratio))

        # Segment continuity evidence
        step_ratio = min(1.0, self._step_count / max(1, self.expected_total_steps))
        evidence_components.append((0.25, step_ratio))

        if evidence_components:
            total_weight = sum(w for w, _ in evidence_components)
            candidate_progress = sum(w * val for w, val in evidence_components) / total_weight
        else:
            candidate_progress = self._progress_ratio

        # Incorporate external hint if provided, with anti-teleportation gate
        if isinstance(raw_progress_hint, (int, float)) and not isinstance(raw_progress_hint, bool):
            hint_clamped = max(0.0, min(1.0, float(raw_progress_hint)))
            if hint_clamped > self._progress_ratio + MAX_ALLOWABLE_SINGLE_STEP_JUMP:
                if self._verified_overlap_count == 0 and self._step_count <= 2:
                    self._teleportation_attempts_blocked += 1
                    if self.enforce_strict_guards:
                        raise WarehouseScanProgressError(
                            "PROGRESS_JUMP_REJECTED_NO_EVIDENCE",
                            f"Attempted jump from {self._progress_ratio:.2f} to {hint_clamped:.2f} without overlap evidence"
                        )
                    hint_clamped = self._progress_ratio + MAX_ALLOWABLE_SINGLE_STEP_JUMP
            candidate_progress = max(candidate_progress, hint_clamped)

        # 2. Anti-teleportation Gate (No 0% -> 100% jump without verified multi-segment evidence)
        jump_delta = candidate_progress - self._progress_ratio
        if jump_delta > MAX_ALLOWABLE_SINGLE_STEP_JUMP:
            if self._verified_overlap_count == 0 and self._step_count <= 2:
                self._teleportation_attempts_blocked += 1
                if self.enforce_strict_guards:
                    raise WarehouseScanProgressError(
                        "PROGRESS_JUMP_REJECTED_NO_EVIDENCE",
                        f"Unproven progress jump from {self._progress_ratio:.2f} to {candidate_progress:.2f} rejected"
                    )
                candidate_progress = min(candidate_progress, self._progress_ratio + MAX_ALLOWABLE_SINGLE_STEP_JUMP)

        # 3. Monotonicity Gate (Progress must NEVER decrease)
        if candidate_progress < self._progress_ratio or is_backward_attempt:
            self._monotonicity_violations_blocked += 1
            candidate_progress = self._progress_ratio

        self._progress_ratio = max(0.0, min(1.0, candidate_progress))

        self._history.append({
            "step": self._step_count,
            "progress": round(self._progress_ratio, 4),
            "scrollbarState": self._scrollbar_state,
            "overlapCount": self._verified_overlap_count,
            "cumDisplacement": round(self._cumulative_displacement_px, 1),
        })

        return self._progress_ratio

    def to_payload(self) -> Dict[str, Any]:
        """Serialize current progress state into contract schema."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "progressRatio": round(self._progress_ratio, 4),
            "isComplete": self.is_complete,
            "canonicalTask4Status": CANONICAL_TASK4_STATUS,
            "monotonicityPreserved": True,
            "isFrozen": self._is_frozen,
            "freezeReason": self._freeze_reason,
            "evidence": {
                "stepCount": self._step_count,
                "verifiedOverlapCount": self._verified_overlap_count,
                "cumulativeDisplacementPx": round(self._cumulative_displacement_px, 1),
                "scrollbarTravelRatio": round(self._scrollbar_travel_ratio, 4),
                "scrollbarState": self._scrollbar_state,
            },
            "guardMetrics": {
                "teleportationAttemptsBlocked": self._teleportation_attempts_blocked,
                "monotonicityViolationsBlocked": self._monotonicity_violations_blocked,
            },
        }
