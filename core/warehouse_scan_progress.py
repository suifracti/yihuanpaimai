# -*- coding: utf-8 -*-
"""Warehouse scan progress monotonicity and anti-teleportation tracker and guard.

Enforces:
1. Strict monotonicity: progress is strictly non-decreasing during an active scan sequence.
2. Anti-teleportation: forbids jumping directly 0% -> 100% or large unproven leaps (> 0.35)
   without CURRENT TRANSITION physical evidence (strict overlapVerified is True + positive offset).
   Historical overlaps cannot authorize current leaps.
3. Idempotent deduplication: repeating the same segment/transition produces identical progress,
   zero step/overlap/displacement inflation. Observation call count is never segment evidence.
4. Decoupling: progress != complete. Even 100% progress does not imply warehouse COMPLETE.
5. Canonical #4 status: explicitly outputs canonicalTask4Status = 'UNFINISHED'.
6. Safety coordination: consumes frozen state from scan safety coordinator SSOT.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

SCHEMA_VERSION = "warehouse-scan-progress.v1"
CANONICAL_TASK4_STATUS = "UNFINISHED"
PROGRESS_KIND = "heuristic_observability"

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
        record_stable_key: Optional[str] = None,
        expected_total_steps: int = 16,
        expected_total_height_px: Optional[float] = None,
        enforce_strict_guards: bool = True,
    ):
        if expected_total_steps <= 0:
            raise WarehouseScanProgressError("INVALID_EXPECTED_STEPS", "expected_total_steps must be > 0")
        self.record_stable_key = str(record_stable_key or "").strip()
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
        self._safety_coordinator: Optional[Any] = None

        self._teleportation_attempts_blocked: int = 0
        self._monotonicity_violations_blocked: int = 0

        # Idempotent deduplication sets
        self._seen_segment_ids: Set[str] = set()
        self._seen_transition_ids: Set[str] = set()
        self._seen_observation_ids: Set[str] = set()
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
        if self._safety_coordinator is not None:
            return bool(self._safety_coordinator.is_frozen)
        return self._is_frozen

    @property
    def freeze_reason(self) -> Optional[str]:
        if self._safety_coordinator is not None and self._safety_coordinator.is_frozen:
            return self._safety_coordinator.freeze_reason
        return self._freeze_reason

    def attach_safety_coordinator(self, coordinator: Any) -> None:
        """Attach the single SSOT safety coordinator."""
        self._safety_coordinator = coordinator

    def freeze(self, reason: str = "EXTERNAL_FREEZE") -> None:
        """Freeze active progress advancement."""
        self._is_frozen = True
        self._freeze_reason = reason

    def unfreeze(self, force: bool = False) -> None:
        """Unfreeze progress advancement upon verified re-arm."""
        if self._safety_coordinator is not None and not force:
            if self._safety_coordinator.is_frozen:
                raise WarehouseScanProgressError(
                    "UNFREEZE_REQUIRES_COORDINATOR",
                    "Progress tracker cannot independently unfreeze while safety coordinator is frozen"
                )
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
        overlap_verified: Optional[bool] = None,
        raw_progress_hint: Optional[float] = None,
        segment_id: Optional[str] = None,
        observation_id: Optional[str] = None,
        transition_id: Optional[str] = None,
        from_segment_id: Optional[str] = None,
        to_segment_id: Optional[str] = None,
    ) -> float:
        """Update scan progress using physical observable evidence."""
        if self.is_frozen:
            return self._progress_ratio

        # Strict boolean resolution for overlap: non-bool or False is not accepted
        strict_overlap: bool = False
        if overlap_verified is not None:
            if isinstance(overlap_verified, bool) and overlap_verified is True:
                strict_overlap = True
        elif isinstance(has_verified_overlap, bool) and has_verified_overlap is True:
            strict_overlap = True

        # Build stable transition identifier
        if transition_id is None and (from_segment_id or to_segment_id):
            transition_id = f"{from_segment_id or 'start'}->{to_segment_id or 'end'}"

        # 1. Idempotency Check
        is_dup_segment = False
        if segment_id is not None:
            s_id = str(segment_id).strip()
            if s_id in self._seen_segment_ids:
                is_dup_segment = True
            else:
                self._seen_segment_ids.add(s_id)

        is_dup_transition = False
        if transition_id is not None:
            t_id = str(transition_id).strip()
            if t_id in self._seen_transition_ids:
                is_dup_transition = True
            else:
                self._seen_transition_ids.add(t_id)

        is_dup_obs = False
        if observation_id is not None:
            o_id = str(observation_id).strip()
            if o_id in self._seen_observation_ids:
                is_dup_obs = True
            else:
                self._seen_observation_ids.add(o_id)

        # If observation is fully duplicate and carries no new scrollbar/step progression, return unchanged
        if is_dup_segment and is_dup_transition:
            return self._progress_ratio

        if scrollbar_state:
            self._scrollbar_state = str(scrollbar_state).upper()

        # Update physical displacement if transition is new and verified
        has_valid_offset = (
            isinstance(verified_offset_px, (int, float))
            and not isinstance(verified_offset_px, bool)
            and verified_offset_px > 0
        )
        if strict_overlap and not is_dup_transition:
            self._verified_overlap_count += 1
            if has_valid_offset:
                self._cumulative_displacement_px += float(verified_offset_px)

        # Update step count: only from explicit segment_index or new segment_id
        is_backward_attempt = False
        if isinstance(segment_index, int) and not isinstance(segment_index, bool):
            if segment_index < self._step_count:
                is_backward_attempt = True
            self._step_count = max(self._step_count, segment_index)
        elif not is_dup_segment and segment_id is not None:
            self._step_count += 1
        # If segment_index is None and segment_id is None, DO NOT increment step count!

        # Scrollbar travel tracking
        if isinstance(scrollbar_ratio, (int, float)) and not isinstance(scrollbar_ratio, bool):
            r_clamped = max(0.0, min(1.0, float(scrollbar_ratio)))
            if r_clamped < self._scrollbar_travel_ratio:
                is_backward_attempt = True
            self._scrollbar_travel_ratio = max(self._scrollbar_travel_ratio, r_clamped)

        # 2. Evidence-backed candidate progress calculation
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

        # Segment continuity evidence (only if step_count > 0)
        if self._step_count > 0:
            step_ratio = min(1.0, self._step_count / max(1, self.expected_total_steps))
            evidence_components.append((0.25, step_ratio))

        if evidence_components:
            total_weight = sum(w for w, _ in evidence_components)
            candidate_progress = sum(w * val for w, val in evidence_components) / total_weight
        else:
            candidate_progress = self._progress_ratio

        # Current transition evidence authority:
        # A large jump (> 0.35) CANNOT rely on historical overlap count!
        # It strictly requires that THIS CURRENT TRANSITION has verified overlap + displacement.
        current_transition_verified = (
            strict_overlap
            and has_valid_offset
            and not is_dup_transition
        )

        # External progress hint integration
        if isinstance(raw_progress_hint, (int, float)) and not isinstance(raw_progress_hint, bool):
            hint_clamped = max(0.0, min(1.0, float(raw_progress_hint)))
            if hint_clamped < self._progress_ratio:
                is_backward_attempt = True
            hint_delta = hint_clamped - self._progress_ratio
            if hint_delta > MAX_ALLOWABLE_SINGLE_STEP_JUMP:
                if not current_transition_verified:
                    self._teleportation_attempts_blocked += 1
                    if self.enforce_strict_guards:
                        raise WarehouseScanProgressError(
                            "PROGRESS_JUMP_REJECTED_NO_EVIDENCE",
                            f"Progress jump from {self._progress_ratio:.2f} to {hint_clamped:.2f} rejected: current transition lacks verified overlap/displacement"
                        )
                    hint_clamped = self._progress_ratio + MAX_ALLOWABLE_SINGLE_STEP_JUMP
            candidate_progress = max(candidate_progress, hint_clamped)

        # 3. Anti-teleportation Gate (No large jump > 0.35 without CURRENT transition verification)
        jump_delta = candidate_progress - self._progress_ratio
        if jump_delta > MAX_ALLOWABLE_SINGLE_STEP_JUMP:
            if not current_transition_verified:
                self._teleportation_attempts_blocked += 1
                if self.enforce_strict_guards:
                    raise WarehouseScanProgressError(
                        "PROGRESS_JUMP_REJECTED_NO_EVIDENCE",
                        f"Progress leap from {self._progress_ratio:.2f} to {candidate_progress:.2f} rejected: current transition lacks verified overlap/displacement"
                    )
                candidate_progress = min(candidate_progress, self._progress_ratio + MAX_ALLOWABLE_SINGLE_STEP_JUMP)

        # 4. Monotonicity Gate (Progress must NEVER decrease)
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
            "transitionId": transition_id,
            "segmentId": segment_id,
        })

        return self._progress_ratio

    def to_payload(self) -> Dict[str, Any]:
        """Serialize current progress state into contract schema."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "progressKind": PROGRESS_KIND,
            "productionCompletenessEligible": False,
            "recordStableKey": self.record_stable_key,
            "progressRatio": round(self._progress_ratio, 4),
            "isComplete": self.is_complete,
            "canonicalTask4Status": CANONICAL_TASK4_STATUS,
            "monotonicityPreserved": True,
            "isFrozen": self.is_frozen,
            "freezeReason": self.freeze_reason,
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
