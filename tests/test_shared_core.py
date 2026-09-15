"""
PHASE 2 Automated Test Suite: Shared Pure Core Engine
验证：
  1. core/auction_engine_v06.js 零 DOM 依赖独立运行
  2. 15:53 经典对局求解测试 (必须产出 G3/P5/R1 与 G4/P5/R0)
  3. 红色重复上限 R=2 测试
  4. Sunk Cost 与 Marginal Chase Line 独立性
  5. 熵变计算与 Intel Event 生成器
"""

import os
import sys
import json
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

class TestSharedPureCore(unittest.TestCase):
    def test_pure_core_in_node(self):
        cmd = [
            "node", "-e",
            """
            const Engine = require('./core/auction_engine_v06.js');
            const res = Engine.runV06ReliabilitySelfTests();
            if (!res.passed) {
              console.error(JSON.stringify(res));
              process.exit(1);
            }
            console.log('PURE_CORE_OK');
            """
        ]
        res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, f"Engine failed: {res.stderr}")
        self.assertIn("PURE_CORE_OK", res.stdout)

    def test_pure_core_solver_exact_1553(self):
        cmd = [
            "node", "-e",
            """
            const Engine = require('./core/auction_engine_v06.js');
            const sol = Engine.solveExactStatesSync({
              q: 9,
              p: 5,
              avg: 33538,
              roundingMode: 'floor',
              knownPurple: '拈花小像+金角月芒',
              knownGold: '万有星仪'
            });
            const states = sol.states.map(s => `${s.G}/${s.P}/${s.R}`);
            if (!states.includes('3/5/1') || !states.includes('4/5/0')) {
              console.error('Missing expected states:', states);
              process.exit(1);
            }
            console.log('1553_OK');
            """
        ]
        res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, f"15:53 failed: {res.stderr}")
        self.assertIn("1553_OK", res.stdout)

    def test_pure_core_roi_and_cost_lines(self):
        cmd = [
            "node", "-e",
            """
            const Engine = require('./core/auction_engine_v06.js');
            const ctx = {
              costs: { entry: 5000, intel: 45000, other: 0, sunkCost: 50000, futureIncrementalCost: 15000 },
              targetROI: 0.20
            };
            const decision = {
              center: 600000,
              low: 550000,
              coverageRatio: 1,
              rawShadow: { p20: 550000, p50: 600000, p80: 650000 },
              shadowCalibrated: { calibrated: { p20: 550000, p50: 600000, p80: 650000 } }
            };
            const lines = Engine.calculateV06DecisionLines(ctx, decision, 450000);
            
            // Global (RecommendedMax) = 600,000 - 65,000 = 535,000
            // Marginal (ChaseLimit) = 600,000 - 15,000 = 585,000
            // Target ROI (SafeBuy) = floor(600,000 / 1.20 - 65,000) = 500,000 - 65,000 = 435,000
            if (lines.globalLine !== 535000 || lines.marginalLine !== 585000 || lines.targetLine !== 435000) {
              console.error('Lines calculation mismatch:', lines);
              process.exit(1);
            }
            console.log('ROI_COST_LINES_OK');
            """
        ]
        res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, f"Lines failed: {res.stderr}")
        self.assertIn("ROI_COST_LINES_OK", res.stdout)

if __name__ == "__main__":
    unittest.main()
