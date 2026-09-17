# -*- coding: utf-8 -*-
"""Targeted Unit Tests for PR-D: Warehouse Observability & Guard Enhancements.

Verifies the 4 core components and contract boundaries:
1. Warehouse Scan Progress Monotonicity & Anti-Teleportation (warehouse_scan_progress.py)
   - Progress is monotonically non-decreasing.
   - Downward progress attempts are clamped/blocked.
   - Anti-teleportation: 0% -> 100% leaps without verified evidence are blocked.
   - Progress != complete: progress == 1.0 does NOT mean complete.
   - Canonical Task #4 status explicitly reported as UNFINISHED.
2. 1x1 Double-Evidence Dedup Gate (warehouse_double_evidence_dedup.py)
   - High-risk 1x1 items require both Spatial Grid Continuity and Feature Invariance.
   - Approximate visual match alone is strictly rejected.
   - Ambiguous items are retained as AMBIGUOUS without forced exact collapse.
   - Non-1x1 items follow standard pipeline.
3. Active-Scan Freeze Guard (warehouse_active_scan_freeze.py)
   - Freezes scan, halts automated wheel driver, and pauses progress on:
     a. User keyboard input
     b. Focus lost
     c. Game interaction conflict
     d. User takeover
   - Explicit re-arm required to resume.
4. NTECloudGame Window Recognition (window_tracker.py)
   - Recognizes cloud game windows (ntecloudgame.exe, 云·异环) with clientType='cloud'.
   - Preserves distinction: cloud window is NEVER guessed as htgame.exe.
   - Local htgame.exe recognized as clientType='local'.
   - Negative filters (launcher, own process, too small) strictly preserved.
5. Boundary 3 file intersection is strictly empty.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_CORE_DIR = os.path.join(_PROJECT_ROOT, "core")
_APP_DIR = os.path.join(_PROJECT_ROOT, "app")
for _p in (_PROJECT_ROOT, _CORE_DIR, _APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import window_tracker
from warehouse_active_scan_freeze import (
    FREEZE_REASON_FOCUS_LOST,
    FREEZE_REASON_GAME_CONFLICT,
    FREEZE_REASON_KEYBOARD,
    FREEZE_REASON_TAKEOVER,
    WarehouseActiveScanFreezeGuard,
    WarehouseScanFrozenError,
)
from warehouse_double_evidence_dedup import (
    REASON_1X1_AMBIGUOUS_COMPETITOR,
    REASON_1X1_APPROXIMATE_ONLY_REJECTED,
    REASON_1X1_DOUBLE_EVIDENCE_MET,
    REASON_1X1_FEATURE_INVARIANCE_INSUFFICIENT,
    REASON_1X1_SPATIAL_CONTINUITY_MISSING,
    STATUS_ADMITTED,
    STATUS_AMBIGUOUS,
    WarehouseDoubleEvidenceDedupGate,
    is_1x1_item,
)
from warehouse_scan_progress import (
    CANONICAL_TASK4_STATUS,
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
    # 1. Warehouse Scan Progress Monotonicity & Anti-Teleportation
    # =========================================================================

    def test_01_progress_monotonicity_under_normal_steps(self):
        """1. Progress is monotonically non-decreasing across normal verified steps."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=10, expected_total_height_px=1000.0)
        self.assertEqual(tracker.progress_ratio, 0.0)

        prev_progress = 0.0
        # Step through with incremental verified segments
        for i in range(1, 8):
            p = tracker.update_from_observation(
                segment_index=i,
                verified_offset_px=120.0,
                has_verified_overlap=True,
                scrollbar_ratio=i * 0.12,
            )
            self.assertGreaterEqual(p, prev_progress, f"Monotonicity violated at step {i}: {p} < {prev_progress}")
            prev_progress = p

        payload = tracker.to_payload()
        self.assertTrue(payload["monotonicityPreserved"])
        self.assertEqual(payload["guardMetrics"]["monotonicityViolationsBlocked"], 0)

    def test_02_backward_progress_attempt_is_clamped_and_blocked(self):
        """2. Attempting to reduce progress is blocked; progress never decreases."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=10)
        # Advance to some progress
        p1 = tracker.update_from_observation(
            segment_index=5,
            verified_offset_px=200.0,
            has_verified_overlap=True,
            scrollbar_ratio=0.5,
        )
        self.assertGreater(p1, 0.3)

        # Attempt to report an earlier scrollbar position (e.g. 0.1) or lower step
        p2 = tracker.update_from_observation(
            segment_index=1,
            verified_offset_px=0.0,
            has_verified_overlap=False,
            scrollbar_ratio=0.1,
        )
        # Progress must NOT decrease!
        self.assertGreaterEqual(p2, p1)
        self.assertEqual(p2, p1)
        payload = tracker.to_payload()
        self.assertGreaterEqual(payload["guardMetrics"]["monotonicityViolationsBlocked"], 1)

    def test_03_teleportation_jump_without_evidence_rejected(self):
        """3. Leaping 0% -> 100% or large unproven jump without verified overlap fails closed."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=10, enforce_strict_guards=True)
        self.assertEqual(tracker.progress_ratio, 0.0)

        # Attempt to inject a 100% progress hint directly on step 1 with 0 verified overlaps
        with self.assertRaises(WarehouseScanProgressError) as ctx:
            tracker.update_from_observation(
                segment_index=1,
                has_verified_overlap=False,
                raw_progress_hint=1.0,
            )
        self.assertIn("PROGRESS_JUMP_REJECTED_NO_EVIDENCE", ctx.exception.code)

        # Tracker progress remains safely 0.0 or minimal
        self.assertLess(tracker.progress_ratio, 0.3)

    def test_04_progress_100_percent_does_not_equal_complete(self):
        """4. Progress == 1.0 does NOT equal complete; canonicalTask4Status is UNFINISHED."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=5, expected_total_height_px=500.0)
        # Advance gradually to 1.0 with verified evidence
        for i in range(1, 6):
            tracker.update_from_observation(
                segment_index=i,
                verified_offset_px=100.0,
                has_verified_overlap=True,
                scrollbar_ratio=i * 0.2,
                scrollbar_state="BOTTOM" if i == 5 else "MIDDLE",
            )

        self.assertAlmostEqual(tracker.progress_ratio, 1.0, places=1)
        # Crucial invariants:
        self.assertFalse(tracker.is_complete)
        payload = tracker.to_payload()
        self.assertFalse(payload["isComplete"])
        self.assertEqual(payload["canonicalTask4Status"], CANONICAL_TASK4_STATUS)
        self.assertEqual(payload["canonicalTask4Status"], "UNFINISHED")

    # =========================================================================
    # 2. 1x1 Double-Evidence Dedup Gate
    # =========================================================================

    def test_05_1x1_dedup_requires_double_evidence(self):
        """5. High-risk 1x1 items require both spatial grid continuity and feature invariance."""
        gate = WarehouseDoubleEvidenceDedupGate()

        cand_1x1 = {
            "widthCells": 1,
            "heightCells": 1,
            "globalBoundingBox": [100.0, 200.0, 140.0, 240.0],
            "contentDigest": "hash_apple_1",
        }
        obs_1x1 = {
            "widthCells": 1,
            "heightCells": 1,
            "globalBox": [102.0, 201.0, 142.0, 241.0],  # 2.2px spatial distance (well within 12px)
            "contentDigest": "hash_apple_1",
        }

        # Case A: Approximate visual match alone (chainOk is False -> unproven spatial continuity)
        seg_bad_spatial = {"chainOk": False, "overlapVerified": False}
        dec_a = gate.evaluate_1x1_dedup(
            cand_1x1, obs_1x1, seg_bad_spatial, raw_visual_similarity=0.92
        )
        self.assertFalse(dec_a["admitted"])
        self.assertEqual(dec_a["status"], STATUS_AMBIGUOUS)
        self.assertTrue(dec_a["ambiguityPreserved"])
        self.assertIn("SPATIAL", dec_a["reason"])

        # Case B: Spatial continuity alone (visual similarity too low, e.g. 0.65)
        seg_good_spatial = {"chainOk": True, "overlapVerified": True}
        dec_b = gate.evaluate_1x1_dedup(
            cand_1x1, obs_1x1, seg_good_spatial, raw_visual_similarity=0.65
        )
        self.assertFalse(dec_b["admitted"])
        self.assertEqual(dec_b["status"], STATUS_AMBIGUOUS)
        self.assertTrue(dec_b["ambiguityPreserved"])
        self.assertIn("FEATURE", dec_b["reason"])

        # Case C: Double evidence met! (chainOk=True, overlap verified, visual similarity=0.95)
        dec_c = gate.evaluate_1x1_dedup(
            cand_1x1, obs_1x1, seg_good_spatial, raw_visual_similarity=0.95
        )
        self.assertTrue(dec_c["admitted"])
        self.assertEqual(dec_c["status"], STATUS_ADMITTED)
        self.assertEqual(dec_c["reason"], REASON_1X1_DOUBLE_EVIDENCE_MET)
        self.assertFalse(dec_c["ambiguityPreserved"])

    def test_06_1x1_ambiguous_competitor_preserves_ambiguity(self):
        """6. Ambiguous competition within margin preserves STATUS_AMBIGUOUS without forced collapse."""
        gate = WarehouseDoubleEvidenceDedupGate(min_distinctiveness_gap=0.15)
        cand_1x1 = {"widthCells": 1, "heightCells": 1, "globalBoundingBox": [100.0, 200.0, 140.0, 240.0]}
        obs_1x1 = {"widthCells": 1, "heightCells": 1, "globalBox": [101.0, 200.0, 141.0, 240.0]}
        seg_context = {"chainOk": True, "overlapVerified": True}

        # Two competitors with close scores: best=0.91, second=0.88 (gap=0.03 < 0.15)
        decision = gate.evaluate_1x1_dedup(
            cand_1x1,
            obs_1x1,
            seg_context,
            competing_candidate_scores=[0.91, 0.88],
            raw_visual_similarity=0.91,
        )
        self.assertFalse(decision["admitted"])
        self.assertEqual(decision["status"], STATUS_AMBIGUOUS)
        self.assertEqual(decision["reason"], REASON_1X1_AMBIGUOUS_COMPETITOR)
        self.assertTrue(decision["ambiguityPreserved"])

    def test_07_non_1x1_item_bypasses_1x1_gate(self):
        """7. Multi-cell items (2x2, 1x3, etc.) follow standard pipeline without 1x1 rejection."""
        gate = WarehouseDoubleEvidenceDedupGate()
        cand_2x2 = {"widthCells": 2, "heightCells": 2}
        obs_2x2 = {"widthCells": 2, "heightCells": 2}
        dec = gate.evaluate_1x1_dedup(cand_2x2, obs_2x2, {"chainOk": True})
        self.assertTrue(dec["admitted"])
        self.assertEqual(dec["status"], "NON_1X1_STANDARD_EVAL")

    # =========================================================================
    # 3. Active-Scan Freeze Guard
    # =========================================================================

    def test_08_active_scan_freeze_on_keyboard_input(self):
        """8. User keyboard input triggers immediate scan freeze and scroll halt."""
        guard = WarehouseActiveScanFreezeGuard()
        self.assertTrue(guard.scroll_permitted)
        self.assertFalse(guard.is_frozen)

        # Trigger keyboard input
        guard.trigger_freeze(FREEZE_REASON_KEYBOARD, {"vk": "VK_ESCAPE"})
        self.assertTrue(guard.is_frozen)
        self.assertEqual(guard.freeze_reason, "USER_KEYBOARD_INPUT")
        self.assertFalse(guard.scroll_permitted)
        self.assertTrue(guard.progress_frozen)

        # Assert scroll permitted raises error
        with self.assertRaises(WarehouseScanFrozenError) as ctx:
            guard.assert_scroll_permitted()
        self.assertIn("USER_KEYBOARD_INPUT", ctx.exception.reason)

    def test_09_active_scan_freeze_on_focus_lost(self):
        """9. Focus lost triggers freeze and scroll halt."""
        guard = WarehouseActiveScanFreezeGuard()
        guard.trigger_freeze(FREEZE_REASON_FOCUS_LOST, {"prevHwnd": 1234, "newHwnd": 5678})
        self.assertTrue(guard.is_frozen)
        self.assertEqual(guard.freeze_reason, "FOCUS_LOST")
        self.assertFalse(guard.scroll_permitted)

    def test_10_active_scan_freeze_on_game_interaction_conflict(self):
        """10. Game interaction / bidding conflict triggers freeze."""
        guard = WarehouseActiveScanFreezeGuard()
        guard.trigger_freeze(FREEZE_REASON_GAME_CONFLICT, {"event": "BIDDING_ROUND_STARTED"})
        self.assertTrue(guard.is_frozen)
        self.assertEqual(guard.freeze_reason, "GAME_INTERACTION_CONFLICT")

    def test_11_active_scan_freeze_on_user_takeover_and_rearm(self):
        """11. User takeover triggers freeze; explicit re-arm unfreezes."""
        guard = WarehouseActiveScanFreezeGuard()
        guard.trigger_freeze(FREEZE_REASON_TAKEOVER, {"action": "MANUAL_WHEEL_SCROLL"})
        self.assertTrue(guard.is_frozen)
        self.assertFalse(guard.scroll_permitted)

        # Unfreeze requires explicit re-arm token
        self.assertFalse(guard.unfreeze_rearmed(""))
        self.assertTrue(guard.is_frozen)

        self.assertTrue(guard.unfreeze_rearmed("token_rearm_123"))
        self.assertFalse(guard.is_frozen)
        self.assertTrue(guard.scroll_permitted)

    def test_12_progress_tracker_freezes_advancement_when_frozen(self):
        """12. Progress tracker pauses advancement while frozen."""
        tracker = WarehouseScanProgressTracker(expected_total_steps=10)
        p1 = tracker.update_from_observation(segment_index=3, verified_offset_px=100.0, has_verified_overlap=True)
        self.assertGreater(p1, 0.1)

        tracker.freeze("USER_KEYBOARD_INPUT")
        self.assertTrue(tracker.is_frozen)

        # Subsequent observations do NOT advance progress
        p2 = tracker.update_from_observation(segment_index=6, verified_offset_px=200.0, has_verified_overlap=True)
        self.assertEqual(p2, p1)

        tracker.unfreeze()
        self.assertFalse(tracker.is_frozen)
        p3 = tracker.update_from_observation(segment_index=6, verified_offset_px=200.0, has_verified_overlap=True)
        self.assertGreater(p3, p2)

    # =========================================================================
    # 4. NTECloudGame Window Recognition
    # =========================================================================

    def test_13_nte_cloud_game_window_recognition(self):
        """13. Recognizes NTECloudGame window with clientType='cloud'; never guessed as htgame.exe."""
        with patch.object(window_tracker.win32gui, "IsWindow", return_value=True), \
             patch.object(window_tracker.win32gui, "IsWindowVisible", return_value=True), \
             patch.object(window_tracker.win32gui, "IsIconic", return_value=False), \
             patch.object(window_tracker.win32process, "GetWindowThreadProcessId", return_value=(999, 44100)), \
             patch.object(window_tracker.win32gui, "GetWindowText", return_value="云·异环"), \
             patch.object(window_tracker.win32gui, "GetClassName", return_value="NTECloudWindow"), \
             patch.object(window_tracker.win32gui, "GetWindowRect", return_value=(0, 0, 1920, 1080)), \
             patch.object(window_tracker, "_process_basename", return_value="ntecloudgame.exe"):

            score, reject_reason, meta = score_window_candidate(55667)
            self.assertIsNone(reject_reason)
            self.assertGreaterEqual(score, 40)
            self.assertEqual(meta["clientType"], "cloud")
            self.assertEqual(meta["process"], "ntecloudgame.exe")
            # Invariant: Cloud window is NEVER guessed as local htgame.exe!
            self.assertNotEqual(meta["process"], "htgame.exe")
            self.assertTrue(is_real_game_window(55667))

    def test_14_local_game_window_recognition(self):
        """14. Recognizes local htgame.exe with clientType='local'."""
        with patch.object(window_tracker.win32gui, "IsWindow", return_value=True), \
             patch.object(window_tracker.win32gui, "IsWindowVisible", return_value=True), \
             patch.object(window_tracker.win32gui, "IsIconic", return_value=False), \
             patch.object(window_tracker.win32process, "GetWindowThreadProcessId", return_value=(999, 37324)), \
             patch.object(window_tracker.win32gui, "GetWindowText", return_value="异环"), \
             patch.object(window_tracker.win32gui, "GetClassName", return_value="UnrealWindow"), \
             patch.object(window_tracker.win32gui, "GetWindowRect", return_value=(0, 0, 1920, 1080)), \
             patch.object(window_tracker, "_process_basename", return_value="htgame.exe"):

            score, reject_reason, meta = score_window_candidate(12345)
            self.assertIsNone(reject_reason)
            self.assertGreaterEqual(score, 40)
            self.assertEqual(meta["clientType"], "local")
            self.assertEqual(meta["process"], "htgame.exe")
            self.assertTrue(is_real_game_window(12345))

    def test_15_cloud_window_negative_exclusions_and_safety(self):
        """15. Cloud window negative exclusions (launcher, too small, own process) strictly enforced."""
        # Cloud launcher rejected
        with patch.object(window_tracker.win32gui, "IsWindow", return_value=True), \
             patch.object(window_tracker.win32gui, "IsWindowVisible", return_value=True), \
             patch.object(window_tracker.win32gui, "IsIconic", return_value=False), \
             patch.object(window_tracker.win32process, "GetWindowThreadProcessId", return_value=(999, 1111)), \
             patch.object(window_tracker.win32gui, "GetWindowText", return_value="云·异环 启动器"), \
             patch.object(window_tracker.win32gui, "GetClassName", return_value="Qt5QWindowIcon"), \
             patch.object(window_tracker.win32gui, "GetWindowRect", return_value=(0, 0, 1280, 720)), \
             patch.object(window_tracker, "_process_basename", return_value="ntecloud_launcher.exe"):

            score, reject_reason, meta = score_window_candidate(8899)
            self.assertEqual(reject_reason, "LAUNCHER_TITLE")
            self.assertFalse(is_real_game_window(8899))

        # Cloud window too small rejected
        with patch.object(window_tracker.win32gui, "IsWindow", return_value=True), \
             patch.object(window_tracker.win32gui, "IsWindowVisible", return_value=True), \
             patch.object(window_tracker.win32gui, "IsIconic", return_value=False), \
             patch.object(window_tracker.win32process, "GetWindowThreadProcessId", return_value=(999, 2222)), \
             patch.object(window_tracker.win32gui, "GetWindowText", return_value="云·异环"), \
             patch.object(window_tracker.win32gui, "GetClassName", return_value="NTECloudWindow"), \
             patch.object(window_tracker.win32gui, "GetWindowRect", return_value=(0, 0, 200, 150)), \
             patch.object(window_tracker, "_process_basename", return_value="ntecloudgame.exe"):

            score, reject_reason, meta = score_window_candidate(8900)
            self.assertEqual(reject_reason, "TOO_SMALL")
            self.assertFalse(is_real_game_window(8900))

    # =========================================================================
    # 5. Boundary 3 Isolation Check
    # =========================================================================

    def test_16_boundary3_intersection_zero(self):
        """16. Boundary 3 files must remain 100% untouched (empty intersection)."""
        try:
            out_b3 = subprocess.check_output(
                ["git", "diff", "--name-only", "main...origin/feature/b3-input-safety"],
                cwd=_PROJECT_ROOT,
                encoding="utf-8",
            )
            b3_files = set(filter(None, [line.strip() for line in out_b3.splitlines()]))
            out_branch = subprocess.check_output(
                ["git", "diff", "--name-only", "main"],
                cwd=_PROJECT_ROOT,
                encoding="utf-8",
            )
            branch_files = set(filter(None, [line.strip() for line in out_branch.splitlines()]))
            intersection = b3_files & branch_files
            self.assertEqual(len(intersection), 0, f"Boundary 3 file intersection not empty: {intersection}")
        except Exception as e:
            self.fail(f"Boundary 3 intersection check failed: {e}")


if __name__ == "__main__":
    unittest.main()
