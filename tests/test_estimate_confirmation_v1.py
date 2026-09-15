"""Unit tests for Estimate N=2 candidate confirmation contract (4D2D1M-C2.26)."""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from vision_pipeline import NTEVisionPipeline


class TestEstimateConfirmationV1(unittest.TestCase):
    def setUp(self):
        self.pipe = NTEVisionPipeline()
        self.pipe.reset_session_state()

    def test_estimate_single_frame_jitter_filtered_and_real_change_confirmed(self):
        """
        Verify Estimate N=2 Candidate Confirmation Contract (4D2D1M-C2.26):
        1. 176535 -> 776535 -> 176535 -> 176535 (776535 never published)
        2. 176535 -> 200000 -> 200000 (200000 confirmed after 2nd observation)
        3. OCR miss / None resets candidate and holds confirmed.
        """
        p = self.pipe

        # --- Phase 1: Establish initial 176535 ---
        # Frame 1: first observation 176535 -> candidate, not published
        est1 = p._apply_estimate_observation(176535)
        self.assertIsNone(est1)
        self.assertEqual(p._estimate_candidate["val"], 176535)
        self.assertEqual(p._estimate_candidate["count"], 1)

        # Frame 2: second matching observation 176535 -> confirmed!
        est2 = p._apply_estimate_observation(176535)
        self.assertEqual(est2, 176535)
        self.assertEqual(p._confirmed_estimate, 176535)

        # --- Phase 2: Single-frame legal-wrong jitter (776535) ---
        # Frame 3: legal-wrong outlier 776535 -> candidate, NOT published
        est3 = p._apply_estimate_observation(776535)
        self.assertEqual(est3, 176535, "Single-frame outlier 776535 must NEVER be published")
        self.assertEqual(p._estimate_candidate["val"], 776535)
        self.assertEqual(p._estimate_candidate["count"], 1)

        # Frame 4: clean 176535 returns -> clears challenger, published remains 176535
        est4 = p._apply_estimate_observation(176535)
        self.assertEqual(est4, 176535)
        self.assertIsNone(p._estimate_candidate["val"])

        # --- Phase 3: Real legitimate estimate transition (200000) ---
        # Frame 5: first 200000 -> candidate, published remains 176535
        est5 = p._apply_estimate_observation(200000)
        self.assertEqual(est5, 176535)
        self.assertEqual(p._estimate_candidate["val"], 200000)
        self.assertEqual(p._estimate_candidate["count"], 1)

        # Frame 6: second 200000 -> confirmed!
        est6 = p._apply_estimate_observation(200000)
        self.assertEqual(est6, 200000)
        self.assertEqual(p._confirmed_estimate, 200000)

        # --- Phase 4: Miss / invalid handling ---
        # Frame 7: observation is None or < 1000 -> clears candidate, holds confirmed
        p._estimate_candidate = {"val": 300000, "count": 1}
        est7 = p._apply_estimate_observation(None)
        self.assertEqual(est7, 200000)
        self.assertIsNone(p._estimate_candidate["val"])


if __name__ == "__main__":
    unittest.main()
