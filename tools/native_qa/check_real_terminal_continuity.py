"""Explicitly replay retained local SOURCE images for terminal continuity QA.

This opt-in command reads ignored build/native-auto-pages-20261010/real-once-08
capture output. It does not launch a game or capture new frames.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ['YIHUAN_REAL_SOURCE_QA'] = '1'

from tests.test_native_half_viewport_flow import RealSourceTerminalContinuityQATests


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RealSourceTerminalContinuityQATests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
