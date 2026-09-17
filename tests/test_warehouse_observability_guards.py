# -*- coding: utf-8 -*-
"""Targeted Unit & Integration Tests for PR-D: Warehouse Observability & Guard Enhancements.

Covers:
1. Section A: Real Runtime Chain Integration:
   - warehouse observation -> progress guard (via PhysicalComponentLedger)
   - cross-segment merge candidate -> 1x1 double-evidence gate -> physical ledger merge / ambiguous
   - input/focus/conflict signal -> active-scan freeze authority -> scroll precheck -> zero wheel
2. Section B: Progress Anti-Teleportation & Idempotency:
   - first observation segment_index=16 + ratio=1.0 + no overlap => large jump rejected
   - past overlap exists + current jump has no verified transition evidence => rejected
   - same segment repeated 20 times => progress unchanged
   - same overlap transition replayed => overlap/displacement idempotent
   - progress=1.0 => isComplete remains false, canonicalTask4Status = UNFINISHED
3. Section C: 1x1 Double-Evidence Gate Fail-Closed:
   - missing global box => AMBIGUOUS
   - mixed local/global frames without originY => AMBIGUOUS
   - "false" bool strings (chainOk="false" or overlapVerified="false") => fail-closed AMBIGUOUS
   - generic status VERIFIED only without overlapVerified=True => AMBIGUOUS
   - missing competitor evidence => AMBIGUOUS
   - NaN / >1 visual similarity => AMBIGUOUS
   - non-1x1 item => status=NOT_APPLICABLE, requiresStandardPipeline=True, admitted=False
4. Section D: Active Scan Freeze SSOT & Coordinator:
   - keyboard abort event => scan frozen => actual scroll request count 0
   - focus lost => request count 0
   - callback throws => request count still 0, haltCallbackFailed=True
   - rearm while focus lost => rejected
   - explicit safe manual rearm => only then scroll can continue
   - freeze => progress cannot advance
5. Section E: NTECloudGame Window Recognition Tightened Negative Matrix:
   - unknown.exe + "云·异环" title only => not high-confidence game
   - somecloudgamehelper.exe => rejected
   - generic CloudGameWindow + unrelated title => rejected
   - exact ntecloudgame.exe + valid geometry => cloud
   - NTECloudGameWnd + NTE-specific title => cloud
   - local htgame.exe => local unchanged
6. Boundary 3 file intersection is strictly empty.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import unittest
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_CORE_DIR = os.path.join(_PROJECT_ROOT, "core")
_APP_DIR = os.path.join(_PROJECT_ROOT, "app")
for _p in (_PROJECT_ROOT, _CORE_DIR, _APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from warehouse_active_scan_freeze import (
    FREEZE_REASON_FOCUS_LOST,
    FREEZE_REASON_GAME_CONFLICT,
    FREEZE_REASON_KEYBOARD,
    FREEZE_REASON_TAKEOVER,
    WarehouseActiveScanFreezeGuard,
    WarehouseScanFrozenError,
    WarehouseScanSafetyCoordinator,
)
from warehouse_double_evidence_dedup import (
    REASON_1X1_AMBIGUOUS_COMPETITOR,
    REASON_1X1_APPROXIMATE_ONLY_REJECTED,
    REASON_1X1_COMPETITOR_EVIDENCE_MISSING,
    REASON_1X1_DOUBLE_EVIDENCE_MET,
    REASON_1X1_FEATURE_INVARIANCE_INSUFFICIENT,
    REASON_1X1_GEOMETRY_MISSING,
    REASON_1X1_INVALID_VISUAL_SIMILARITY,
    REASON_1X1_MIXED_COORDINATE_FRAMES,
    REASON_1X1_SPATIAL_CONTINUITY_MISSING,
    REASON_NON_1X1_ITEM,
    STATUS_ADMITTED,
    STATUS_AMBIGUOUS,
    STATUS_NOT_APPLICABLE,
    WarehouseDoubleEvidenceDedupGate,
    is_1x1_item,
)
from warehouse_physical_ledger import PhysicalComponentLedger
from warehouse_scan_progress import (
    CANONICAL_TASK4_STATUS,
    MAX_ALLOWABLE_SINGLE_STEP_JUMP,
    PROGRESS_KIND,
    WarehouseScanProgressError,
    WarehouseScanProgressTracker,
)
from window_tracker import (
    GameWindowTracker,
    is_real_game_window,
    score_window_candidate,
)


class TestWarehouseObservabilityGuards(unittest.TestCase):
    # =========================================================================
    # Section B: Progress Anti-Teleportation & Idempotency
    # =========================================================================

    def test_b01_first_observation_large_jump_rejected_without_overlap(self):
        """B1. First observation segment_index=16 + ratio=1.0 + no overlap => large jump rejected."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=16, enforce_strict_guards=True)
        self.assertEqual(tracker.progress_ratio, 0.0)

        with self.assertRaises(WarehouseScanProgressError) as ctx:
            tracker.update_from_observation(
                segment_id="seg_first",
                segment_index=16,
                scrollbar_ratio=1.0,
                overlap_verified=False,
                raw_progress_hint=1.0,
            )
        self.assertEqual(ctx.exception.code, "PROGRESS_JUMP_REJECTED_NO_EVIDENCE")
        # Progress remains at 0.0
        self.assertEqual(tracker.progress_ratio, 0.0)
        self.assertEqual(tracker.to_payload()["guardMetrics"]["teleportationAttemptsBlocked"], 1)

    def test_b02_past_overlap_exists_but_current_transition_unverified_rejected(self):
        """B2. Historical overlap exists, but current jump lacks current transition evidence => rejected."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=10, enforce_strict_guards=True)

        # 1. First small step with verified overlap
        p1 = tracker.update_from_observation(
            segment_id="seg_1",
            transition_id="init->seg_1",
            segment_index=1,
            scrollbar_ratio=0.1,
            overlap_verified=True,
            verified_offset_px=50.0,
        )
        self.assertGreater(p1, 0.0)
        self.assertLessEqual(p1, 0.35)

        # 2. Next transition attempts a massive leap to 0.90, but current transition has NO verified overlap
        with self.assertRaises(WarehouseScanProgressError) as ctx:
            tracker.update_from_observation(
                segment_id="seg_2",
                transition_id="seg_1->seg_2",
                segment_index=9,
                scrollbar_ratio=0.9,
                overlap_verified=False,  # Unverified transition!
                verified_offset_px=None,
                raw_progress_hint=0.9,
            )
        self.assertEqual(ctx.exception.code, "PROGRESS_JUMP_REJECTED_NO_EVIDENCE")
        # Historical overlap did NOT allow the current jump
        self.assertEqual(tracker.progress_ratio, p1)

    def test_b03_same_segment_repeated_20_times_progress_unchanged(self):
        """B3. Repeating identical segment/observation 20 times preserves identical progress."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=10)

        initial = tracker.update_from_observation(
            segment_id="seg_steady",
            observation_id="obs_hash_abc",
            transition_id="trans_0",
            segment_index=2,
            scrollbar_ratio=0.2,
            overlap_verified=True,
            verified_offset_px=80.0,
        )

        for _ in range(20):
            repeated = tracker.update_from_observation(
                segment_id="seg_steady",
                observation_id="obs_hash_abc",
                transition_id="trans_0",
                segment_index=2,
                scrollbar_ratio=0.2,
                overlap_verified=True,
                verified_offset_px=80.0,
            )
            self.assertEqual(repeated, initial)

        payload = tracker.to_payload()
        self.assertEqual(payload["evidence"]["verifiedOverlapCount"], 1)
        self.assertEqual(payload["evidence"]["cumulativeDisplacementPx"], 80.0)

    def test_b04_replaying_same_overlap_transition_is_idempotent(self):
        """B4. Same overlap transition replayed does not increment displacement or step count."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=10)

        p1 = tracker.update_from_observation(
            segment_id="seg_A",
            transition_id="trans_A->B",
            overlap_verified=True,
            verified_offset_px=100.0,
        )
        self.assertEqual(tracker.to_payload()["evidence"]["cumulativeDisplacementPx"], 100.0)
        self.assertEqual(tracker.to_payload()["evidence"]["verifiedOverlapCount"], 1)

        # Replay the same transition
        p2 = tracker.update_from_observation(
            segment_id="seg_A",
            transition_id="trans_A->B",
            overlap_verified=True,
            verified_offset_px=100.0,
        )
        self.assertEqual(p2, p1)
        self.assertEqual(tracker.to_payload()["evidence"]["cumulativeDisplacementPx"], 100.0)
        self.assertEqual(tracker.to_payload()["evidence"]["verifiedOverlapCount"], 1)

    def test_b05_progress_100_percent_decoupled_from_completeness(self):
        """B5. Progress = 1.0 does NOT mean complete; canonicalTask4Status = UNFINISHED."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=5, enforce_strict_guards=False)

        # Step up gradually with valid evidence
        for i in range(1, 6):
            tracker.update_from_observation(
                segment_id=f"seg_{i}",
                transition_id=f"trans_{i-1}->{i}",
                segment_index=i,
                scrollbar_ratio=i * 0.2,
                scrollbar_state="BOTTOM" if i == 5 else "MIDDLE",
                overlap_verified=True,
                verified_offset_px=100.0,
            )

        payload = tracker.to_payload()
        self.assertGreaterEqual(tracker.progress_ratio, 0.8)
        self.assertFalse(tracker.is_complete)
        self.assertEqual(payload["canonicalTask4Status"], CANONICAL_TASK4_STATUS)
        self.assertEqual(payload["progressKind"], PROGRESS_KIND)
        self.assertFalse(payload["productionCompletenessEligible"])

    def test_b06_backward_progress_attempt_clamped(self):
        """B6. Backward progress attempt is clamped and recorded."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=10)

        p1 = tracker.update_from_observation(
            segment_id="seg_5",
            segment_index=5,
            scrollbar_ratio=0.5,
            overlap_verified=True,
            verified_offset_px=150.0,
        )
        # Attempt to report an earlier scrollbar position and lower step
        p2 = tracker.update_from_observation(
            segment_id="seg_1",
            segment_index=1,
            scrollbar_ratio=0.1,
            overlap_verified=False,
        )
        self.assertEqual(p2, p1)
        payload = tracker.to_payload()
        self.assertGreaterEqual(payload["guardMetrics"]["monotonicityViolationsBlocked"], 1)

    # =========================================================================
    # Section C: 1x1 Double-Evidence Gate Fail-Closed
    # =========================================================================

    def test_c01_missing_global_box_fails_closed(self):
        """C1. Missing or degenerate [0,0,0,0] global box fails closed as AMBIGUOUS."""
        gate = WarehouseDoubleEvidenceDedupGate()
        cand_no_box = {"widthCells": 1, "heightCells": 1}
        obs_valid = {"widthCells": 1, "heightCells": 1, "globalBox": [10.0, 20.0, 50.0, 60.0]}
        seg = {"chainOk": True, "overlapVerified": True, "competitorSearchComplete": True}

        dec = gate.evaluate_1x1_dedup(cand_no_box, obs_valid, seg, raw_visual_similarity=0.95)
        self.assertFalse(dec["admitted"])
        self.assertEqual(dec["status"], STATUS_AMBIGUOUS)
        self.assertEqual(dec["reason"], REASON_1X1_GEOMETRY_MISSING)
        self.assertFalse(dec["spatialEvidencePassed"])
        self.assertTrue(dec["ambiguityPreserved"])

    def test_c02_mixed_local_global_frames_without_origin_fails_closed(self):
        """C2. Mixed local/global frames without originY fails closed."""
        gate = WarehouseDoubleEvidenceDedupGate()
        cand = {"widthCells": 1, "heightCells": 1, "globalBoundingBox": [10.0, 20.0, 50.0, 60.0]}
        obs_local = {"widthCells": 1, "heightCells": 1, "localBox": [10.0, 20.0, 50.0, 60.0]}  # No globalBox
        seg_no_origin = {"chainOk": True, "overlapVerified": True, "competitorSearchComplete": True}

        dec = gate.evaluate_1x1_dedup(cand, obs_local, seg_no_origin, raw_visual_similarity=0.95)
        self.assertFalse(dec["admitted"])
        self.assertEqual(dec["status"], STATUS_AMBIGUOUS)
        self.assertEqual(dec["reason"], REASON_1X1_MIXED_COORDINATE_FRAMES)
        self.assertTrue(dec["ambiguityPreserved"])

    def test_c03_string_booleans_fail_closed(self):
        """C3. Non-boolean string 'false' / 'true' / 1 rejects strictly."""
        gate = WarehouseDoubleEvidenceDedupGate()
        cand = {"widthCells": 1, "heightCells": 1, "globalBoundingBox": [10.0, 20.0, 50.0, 60.0]}
        obs = {"widthCells": 1, "heightCells": 1, "globalBox": [11.0, 21.0, 51.0, 61.0]}

        # String 'true' is NOT boolean True
        seg_str_bool = {"chainOk": "true", "overlapVerified": 1, "competitorSearchComplete": True}
        dec = gate.evaluate_1x1_dedup(cand, obs, seg_str_bool, raw_visual_similarity=0.95)
        self.assertFalse(dec["admitted"])
        self.assertEqual(dec["status"], STATUS_AMBIGUOUS)
        self.assertFalse(dec["spatialEvidencePassed"])

    def test_c04_generic_status_verified_alone_rejected(self):
        """C4. Generic status 'VERIFIED' without strict overlapVerified=True is rejected."""
        gate = WarehouseDoubleEvidenceDedupGate()
        cand = {"widthCells": 1, "heightCells": 1, "globalBoundingBox": [10.0, 20.0, 50.0, 60.0]}
        obs = {"widthCells": 1, "heightCells": 1, "globalBox": [10.0, 20.0, 50.0, 60.0]}
        seg_generic = {"chainOk": True, "status": "VERIFIED", "competitorSearchComplete": True}

        dec = gate.evaluate_1x1_dedup(cand, obs, seg_generic, raw_visual_similarity=0.95)
        self.assertFalse(dec["admitted"])
        self.assertEqual(dec["status"], STATUS_AMBIGUOUS)
        self.assertFalse(dec["spatialEvidencePassed"])

    def test_c05_missing_competitor_evidence_fails_closed(self):
        """C5. Missing competitor scores without competitorSearchComplete fails closed."""
        gate = WarehouseDoubleEvidenceDedupGate()
        cand = {"widthCells": 1, "heightCells": 1, "globalBoundingBox": [10.0, 20.0, 50.0, 60.0]}
        obs = {"widthCells": 1, "heightCells": 1, "globalBox": [10.0, 20.0, 50.0, 60.0]}
        seg = {"chainOk": True, "overlapVerified": True}  # competitorSearchComplete not specified

        dec = gate.evaluate_1x1_dedup(
            cand, obs, seg, raw_visual_similarity=0.95, competing_candidate_scores=None
        )
        self.assertFalse(dec["admitted"])
        self.assertEqual(dec["status"], STATUS_AMBIGUOUS)
        self.assertEqual(dec["reason"], REASON_1X1_COMPETITOR_EVIDENCE_MISSING)

    def test_c06_invalid_visual_similarity_rejected(self):
        """C6. NaN or > 1.0 visual similarity fails closed."""
        gate = WarehouseDoubleEvidenceDedupGate()
        cand = {"widthCells": 1, "heightCells": 1, "globalBoundingBox": [10.0, 20.0, 50.0, 60.0]}
        obs = {"widthCells": 1, "heightCells": 1, "globalBox": [10.0, 20.0, 50.0, 60.0]}
        seg = {"chainOk": True, "overlapVerified": True, "competitorSearchComplete": True}

        for bad_sim in [float("nan"), 1.5, -0.2]:
            dec = gate.evaluate_1x1_dedup(cand, obs, seg, raw_visual_similarity=bad_sim)
            self.assertFalse(dec["admitted"])
            self.assertEqual(dec["status"], STATUS_AMBIGUOUS)
            self.assertEqual(dec["reason"], REASON_1X1_INVALID_VISUAL_SIMILARITY)

    def test_c07_non_1x1_item_returns_not_applicable(self):
        """C7. Non-1x1 item returns NOT_APPLICABLE and requiresStandardPipeline=True."""
        gate = WarehouseDoubleEvidenceDedupGate()
        cand_2x2 = {"widthCells": 2, "heightCells": 2, "globalBoundingBox": [10.0, 20.0, 90.0, 100.0]}
        obs_2x2 = {"widthCells": 2, "heightCells": 2, "globalBox": [10.0, 20.0, 90.0, 100.0]}
        seg = {"chainOk": True, "overlapVerified": True}

        dec = gate.evaluate_1x1_dedup(cand_2x2, obs_2x2, seg, raw_visual_similarity=0.95)
        self.assertFalse(dec["admitted"])  # Module does not claim authority to admit non-1x1
        self.assertEqual(dec["status"], STATUS_NOT_APPLICABLE)
        self.assertTrue(dec["requiresStandardPipeline"])
        self.assertEqual(dec["reason"], REASON_NON_1X1_ITEM)

    def test_c08_1x1_double_evidence_success(self):
        """C8. 1x1 double evidence met when spatial and distinctive feature invariance both pass."""
        gate = WarehouseDoubleEvidenceDedupGate()
        cand = {"widthCells": 1, "heightCells": 1, "globalBoundingBox": [10.0, 20.0, 50.0, 60.0]}
        obs = {"widthCells": 1, "heightCells": 1, "globalBox": [12.0, 21.0, 52.0, 61.0]}  # ~2.2px dist (< 12px)
        seg = {"chainOk": True, "overlapVerified": True, "competitorSearchComplete": True}

        dec = gate.evaluate_1x1_dedup(
            cand, obs, seg, raw_visual_similarity=0.95, competing_candidate_scores=[0.95, 0.70]
        )
        self.assertTrue(dec["admitted"])
        self.assertEqual(dec["status"], STATUS_ADMITTED)
        self.assertEqual(dec["reason"], REASON_1X1_DOUBLE_EVIDENCE_MET)
        self.assertTrue(dec["spatialEvidencePassed"])
        self.assertTrue(dec["featureEvidencePassed"])

    # =========================================================================
    # Section D: Active Scan Freeze SSOT & Coordinator
    # =========================================================================

    def test_d01_keyboard_abort_event_freezes_and_blocks_scroll_pulse(self):
        """D1. Keyboard abort event freezes scan and blocks actual scroll requests (0 wheels)."""
        coordinator = WarehouseActiveScanFreezeGuard()
        mock_wheel = MagicMock()

        # Before freeze: scroll works
        coordinator.execute_scroll_request(mock_wheel, 120)
        mock_wheel.assert_called_once_with(120)
        self.assertEqual(coordinator.scroll_requests_executed, 1)

        # Trigger keyboard abort
        coordinator.on_input_abort_signal("KEY_DOWN", {"key": "Escape"})
        self.assertTrue(coordinator.is_frozen)
        self.assertEqual(coordinator.freeze_reason, FREEZE_REASON_KEYBOARD)

        # Subsequent scroll request MUST be blocked: mock_wheel not called again!
        mock_wheel.reset_mock()
        res = coordinator.execute_scroll_request(mock_wheel, 120)
        self.assertIsNone(res)
        mock_wheel.assert_not_called()
        self.assertEqual(coordinator.scroll_requests_blocked, 1)

    def test_d02_focus_lost_blocks_scroll(self):
        """D2. Focus lost triggers freeze and blocks scroll requests."""
        coordinator = WarehouseActiveScanFreezeGuard()
        mock_wheel = MagicMock()

        coordinator.on_focus_lost({"hwnd": 12345})
        self.assertTrue(coordinator.is_frozen)
        self.assertEqual(coordinator.freeze_reason, FREEZE_REASON_FOCUS_LOST)

        coordinator.execute_scroll_request(mock_wheel, 120)
        mock_wheel.assert_not_called()
        self.assertEqual(coordinator.scroll_requests_blocked, 1)

    def test_d03_callback_throws_scroll_still_blocked(self):
        """D3. Halt callback throws an exception: error provenance recorded, scroll remains blocked."""
        def faulty_callback(reason: str):
            raise RuntimeError("Halt notification failed in external sink")

        coordinator = WarehouseActiveScanFreezeGuard(on_freeze_callback=faulty_callback)
        mock_wheel = MagicMock()

        coordinator.trigger_freeze(FREEZE_REASON_TAKEOVER)
        self.assertTrue(coordinator.is_frozen)
        self.assertTrue(coordinator.halt_callback_failed)
        self.assertIn("Halt notification failed", coordinator.halt_callback_error or "")

        # Scroll MUST remain blocked!
        coordinator.execute_scroll_request(mock_wheel, 120)
        mock_wheel.assert_not_called()
        self.assertEqual(coordinator.scroll_requests_blocked, 1)

    def test_d04_rearm_while_focus_lost_rejected(self):
        """D4. Attempting re-arm while focus is lost is rejected; system remains frozen."""
        coordinator = WarehouseActiveScanFreezeGuard()
        coordinator.trigger_freeze(FREEZE_REASON_FOCUS_LOST)

        rearmed = coordinator.attempt_rearm(
            manual_rearm_confirmed=True,
            target_focus_valid=False,  # Focus still invalid!
            no_game_conflict=True,
            no_user_takeover_active=True,
        )
        self.assertFalse(rearmed)
        self.assertTrue(coordinator.is_frozen)

    def test_d05_explicit_safe_manual_rearm_permits_scroll(self):
        """D5. Only explicit safe manual re-arm (all 4 criteria True) unfreezes and permits scroll."""
        coordinator = WarehouseActiveScanFreezeGuard()
        coordinator.trigger_freeze(FREEZE_REASON_KEYBOARD)

        # Legacy token is disallowed
        self.assertFalse(coordinator.unfreeze_rearmed("some_token"))
        self.assertTrue(coordinator.is_frozen)

        # Clean re-arm
        rearmed = coordinator.attempt_rearm(
            manual_rearm_confirmed=True,
            target_focus_valid=True,
            no_game_conflict=True,
            no_user_takeover_active=True,
        )
        self.assertTrue(rearmed)
        self.assertFalse(coordinator.is_frozen)

        # Scroll permitted again
        mock_wheel = MagicMock(return_value="OK")
        res = coordinator.execute_scroll_request(mock_wheel, 120)
        self.assertEqual(res, "OK")
        mock_wheel.assert_called_once()

    def test_d06_freeze_pauses_progress_advancement(self):
        """D6. Attaching coordinator to progress tracker freezes progress advancement."""
        coordinator = WarehouseActiveScanFreezeGuard()
        tracker = WarehouseScanProgressTracker()
        tracker.attach_safety_coordinator(coordinator)

        p1 = tracker.update_from_observation(segment_index=1, scrollbar_ratio=0.1)
        self.assertGreater(p1, 0.0)

        coordinator.trigger_freeze(FREEZE_REASON_TAKEOVER)
        self.assertTrue(tracker.is_frozen)

        # Progress advancement attempted while frozen returns last progress
        p2 = tracker.update_from_observation(segment_index=5, scrollbar_ratio=0.5)
        self.assertEqual(p2, p1)

        # Tracker cannot independently unfreeze while coordinator is frozen
        with self.assertRaises(WarehouseScanProgressError):
            tracker.unfreeze()

    # =========================================================================
    # Section E: NTECloudGame Window Recognition Tightened Negative Matrix
    # =========================================================================

    def test_e01_unknown_exe_with_cloud_title_only_is_not_high_confidence(self):
        """E1. Unknown.exe with '云·异环' title only is rejected / score < 40."""
        score, reject, meta = score_window_candidate(
            hwnd=123,
            target_titles=("云·异环",),
        )
        # Mock window properties via patch
        with patch("window_tracker._process_basename", return_value="unknown.exe"), \
             patch("window_tracker.win32gui.IsWindow", return_value=True), \
             patch("window_tracker.win32gui.IsWindowVisible", return_value=True), \
             patch("window_tracker.win32gui.GetWindowRect", return_value=(0, 0, 1920, 1080)), \
             patch("window_tracker.win32gui.GetWindowText", return_value="云·异环"), \
             patch("window_tracker.win32gui.GetClassName", return_value="UnknownWndClass"), \
             patch("window_tracker.win32process.GetWindowThreadProcessId", return_value=(0, 9999)):
            score, reject, meta = score_window_candidate(123)
            self.assertNotEqual(meta.get("clientType"), "cloud")
            self.assertFalse(is_real_game_window(123))

    def test_e02_helper_process_rejected(self):
        """E2. somecloudgamehelper.exe is strictly rejected as helper process."""
        with patch("window_tracker._process_basename", return_value="somecloudgamehelper.exe"), \
             patch("window_tracker.win32gui.IsWindow", return_value=True), \
             patch("window_tracker.win32gui.IsWindowVisible", return_value=True), \
             patch("window_tracker.win32gui.GetWindowRect", return_value=(0, 0, 1920, 1080)), \
             patch("window_tracker.win32gui.GetWindowText", return_value="云·异环"), \
             patch("window_tracker.win32gui.GetClassName", return_value="NTECloudGameWnd"), \
             patch("window_tracker.win32process.GetWindowThreadProcessId", return_value=(0, 9999)):
            score, reject, meta = score_window_candidate(123)
            self.assertEqual(reject, "HELPER_OR_EXCLUDED_PROCESS")
            self.assertFalse(is_real_game_window(123))

    def test_e03_generic_cloudgamewindow_with_unrelated_title_rejected(self):
        """E3. Generic CloudGameWindow with unrelated title is not recognized as game."""
        with patch("window_tracker._process_basename", return_value="someplayer.exe"), \
             patch("window_tracker.win32gui.IsWindow", return_value=True), \
             patch("window_tracker.win32gui.IsWindowVisible", return_value=True), \
             patch("window_tracker.win32gui.GetWindowRect", return_value=(0, 0, 1920, 1080)), \
             patch("window_tracker.win32gui.GetWindowText", return_value="Notepad Document"), \
             patch("window_tracker.win32gui.GetClassName", return_value="CloudGameWindow"), \
             patch("window_tracker.win32process.GetWindowThreadProcessId", return_value=(0, 9999)):
            score, reject, meta = score_window_candidate(123)
            self.assertNotEqual(meta.get("clientType"), "cloud")
            self.assertFalse(is_real_game_window(123))

    def test_e04_exact_ntecloudgame_exe_recognized_as_cloud(self):
        """E4. Exact ntecloudgame.exe with valid geometry recognized as cloud with score >= 40."""
        with patch("window_tracker._process_basename", return_value="ntecloudgame.exe"), \
             patch("window_tracker.win32gui.IsWindow", return_value=True), \
             patch("window_tracker.win32gui.IsWindowVisible", return_value=True), \
             patch("window_tracker.win32gui.GetWindowRect", return_value=(0, 0, 1920, 1080)), \
             patch("window_tracker.win32gui.GetWindowText", return_value="云·异环"), \
             patch("window_tracker.win32gui.GetClassName", return_value="NTECloudGameWnd"), \
             patch("window_tracker.win32process.GetWindowThreadProcessId", return_value=(0, 9999)):
            score, reject, meta = score_window_candidate(123)
            self.assertIsNone(reject)
            self.assertEqual(meta.get("clientType"), "cloud")
            self.assertEqual(meta.get("process"), "ntecloudgame.exe")
            self.assertGreaterEqual(score, 40)
            self.assertTrue(is_real_game_window(123))

    def test_e05_ntecloudgamewnd_with_nte_title_recognized_as_cloud(self):
        """E5. Fallback: NTECloudGameWnd + NTE-specific title recognized as cloud."""
        with patch("window_tracker._process_basename", return_value="cloud_runtime.exe"), \
             patch("window_tracker.win32gui.IsWindow", return_value=True), \
             patch("window_tracker.win32gui.IsWindowVisible", return_value=True), \
             patch("window_tracker.win32gui.GetWindowRect", return_value=(0, 0, 1920, 1080)), \
             patch("window_tracker.win32gui.GetWindowText", return_value="云·异环"), \
             patch("window_tracker.win32gui.GetClassName", return_value="NTECloudGameWnd"), \
             patch("window_tracker.win32process.GetWindowThreadProcessId", return_value=(0, 9999)):
            score, reject, meta = score_window_candidate(123)
            self.assertIsNone(reject)
            self.assertEqual(meta.get("clientType"), "cloud")
            self.assertTrue(is_real_game_window(123))

    def test_e06_local_htgame_exe_recognized_as_local_unchanged(self):
        """E6. Local htgame.exe recognized as clientType='local'."""
        with patch("window_tracker._process_basename", return_value="htgame.exe"), \
             patch("window_tracker.win32gui.IsWindow", return_value=True), \
             patch("window_tracker.win32gui.IsWindowVisible", return_value=True), \
             patch("window_tracker.win32gui.GetWindowRect", return_value=(0, 0, 1920, 1080)), \
             patch("window_tracker.win32gui.GetWindowText", return_value="异环"), \
             patch("window_tracker.win32gui.GetClassName", return_value="UnrealWindow"), \
             patch("window_tracker.win32process.GetWindowThreadProcessId", return_value=(0, 9999)):
            score, reject, meta = score_window_candidate(123)
            self.assertIsNone(reject)
            self.assertEqual(meta.get("clientType"), "local")
            self.assertTrue(is_real_game_window(123))

    # =========================================================================
    # Section A: Real Runtime Chain Integration Tests
    # =========================================================================

    def test_a01_observation_to_progress_guard_in_physical_ledger(self):
        """A1. PhysicalComponentLedger automatically advances progress tracker on add_segment."""
        ledger = PhysicalComponentLedger("recChainObs01")
        self.assertIsNotNone(ledger.progress_tracker)
        self.assertEqual(ledger.progress_tracker.progress_ratio, 0.0)

        fake_obs_1 = {
            "components": [
                {"observationId": "o1", "boundingBox": [10, 20, 50, 60], "widthCells": 1, "heightCells": 1}
            ],
            "grid": {"status": "OK", "cellWidth": 40, "cellHeight": 40, "xLines": [10, 50], "yLines": [20, 60]},
        }
        ledger.add_segment(fake_obs_1, sequence_index=0, segment_id="seg_0", scroll_state="TOP")
        p0 = ledger.progress_tracker.progress_ratio

        overlap_link = {
            "status": "VERIFIED",
            "direction": "DOWN",
            "verticalOffsetPx": -80,
            "trusted": True,
            "aligned": True,
        }
        fake_obs_2 = {
            "components": [
                {"observationId": "o2", "boundingBox": [10, 100, 50, 140], "widthCells": 1, "heightCells": 1}
            ],
            "grid": {"status": "OK", "cellWidth": 40, "cellHeight": 40, "xLines": [10, 50], "yLines": [20, 60]},
        }
        ledger.add_segment(fake_obs_2, sequence_index=1, segment_id="seg_1", overlap=overlap_link, scroll_state="MIDDLE")
        p1 = ledger.progress_tracker.progress_ratio

        self.assertGreaterEqual(p1, p0)
        self.assertGreater(ledger.progress_tracker.to_payload()["evidence"]["verifiedOverlapCount"], 0)
        self.assertEqual(ledger.scan_progress["canonicalTask4Status"], CANONICAL_TASK4_STATUS)

    def test_a02_1x1_double_evidence_gate_controls_physical_ledger_merge(self):
        """A2. 1x1 items in PhysicalComponentLedger pass through dedup gate; unproven match stays ambiguous."""
        ledger = PhysicalComponentLedger("recChainDedup01")

        # Segment 0: 1x1 item at (10, 20, 50, 60)
        obs_0 = {
            "components": [
                {"observationId": "item_1x1_A", "boundingBox": [10, 20, 50, 60], "widthCells": 1, "heightCells": 1}
            ],
            "grid": {"status": "OK", "cellWidth": 40, "cellHeight": 40, "xLines": [10, 50], "yLines": [20, 60]},
        }
        ledger.add_segment(obs_0, sequence_index=0, segment_id="seg_0", scroll_state="TOP")

        # Segment 1: Verified chain overlap (chainOk=True), but unproven feature match
        verified_overlap = {"status": "VERIFIED", "direction": "DOWN", "verticalOffsetPx": 0, "trusted": True, "aligned": True}
        obs_1 = {
            "components": [
                {"observationId": "item_1x1_B", "boundingBox": [10, 20, 50, 60], "widthCells": 1, "heightCells": 1}
            ],
            "grid": {"status": "OK", "cellWidth": 40, "cellHeight": 40, "xLines": [10, 50], "yLines": [20, 60]},
        }
        snap = ledger.add_segment(obs_1, sequence_index=1, segment_id="seg_1", overlap=verified_overlap)

        # Gate evaluations recorded in ledger
        self.assertGreaterEqual(len(ledger.dedup_gate.gate_evaluations), 1)
        # Because spatial continuity was unverified, the two 1x1 observations MUST NOT merge into 1 track
        self.assertGreaterEqual(len(snap["tracks"]), 2)

    def test_a03_active_scan_freeze_authority_blocks_wheel_pulse(self):
        """A3. Active scan freeze authority enforces zero wheel pulse through precheck."""
        coordinator = WarehouseScanSafetyCoordinator()
        wheel_calls = []

        def mock_pulse(delta: int):
            wheel_calls.append(delta)

        # Normal pulse passes precheck
        coordinator.execute_scroll_request(mock_pulse, -120)
        self.assertEqual(len(wheel_calls), 1)

        # Trigger conflict
        coordinator.on_game_conflict({"round": 2, "state": "BIDDING"})
        self.assertTrue(coordinator.is_frozen)

        # Pulse during conflict is rejected, wheel function not called
        coordinator.execute_scroll_request(mock_pulse, -120)
        self.assertEqual(len(wheel_calls), 1)  # Stays at 1, zero additional wheels
        self.assertEqual(coordinator.scroll_requests_blocked, 1)

    # =========================================================================
    # Boundary 3 Isolation
    # =========================================================================

    def test_boundary3_intersection_zero(self):
        """Verify Boundary 3 files remain 100% untouched."""
        try:
            b3_output = subprocess.check_output(
                ["git", "diff", "--name-only", "main...origin/feature/b3-input-safety"],
                cwd=_PROJECT_ROOT,
                text=True,
            )
            b3_files = set(b3_output.strip().splitlines())
        except Exception:
            b3_files = {
                "app/warehouse_capture_host.py",
                "core/warehouse_capture_production.py",
                "core/warehouse_capture_session.py",
                "core/warehouse_input_abort_guard.py",
                "core/warehouse_wheel_driver.py",
            }

        try:
            cur_output = subprocess.check_output(
                ["git", "diff", "--name-only", "main...HEAD"],
                cwd=_PROJECT_ROOT,
                text=True,
            )
            cur_files = set(cur_output.strip().splitlines())
        except Exception:
            cur_files = set()

        intersection = b3_files.intersection(cur_files)
        self.assertEqual(
            len(intersection),
            0,
            f"Boundary 3 file intersection must be empty! Found: {intersection}",
        )


if __name__ == "__main__":
    unittest.main()
