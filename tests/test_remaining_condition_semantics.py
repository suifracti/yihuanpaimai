"""Non-multiplier conditions must preserve valuation facts and paid costs."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(os.environ.get('NTE_TEST_RUNTIME_ROOT', Path(__file__).resolve().parents[1]))


def compute(condition, intel=1200):
    ctx = {'q': 1, 'goldCount': 1, 'avg': 60040, 'knownGold': '算力面包',
           'purple': 0, 'redCount': 0, 'blueCount': 0, 'greenCount': 0, 'whiteCount': 0,
           'fieldCondition': condition, 'round': 1, 'targetProfit': 0,
           'costs': {'entry': 5000, 'intel': intel, 'other': 300,
                     'sunkCost': 5300 + intel, 'futureIncrementalCost': 700, 'total': 6000 + intel}}
    return json.loads(subprocess.check_output(
        [str(ROOT/'runtime/node.exe'), 'core/live_shadow_runtime.js', '--once'],
        cwd=ROOT, input=json.dumps({'ctx': ctx, 'records': []}), text=True, encoding='utf-8'))


class RemainingConditionSemanticsTests(unittest.TestCase):
    def test_no_invented_value_multiplier_or_erasure_of_paid_intel(self):
        for intel in (0, 1200):
            base = compute('standard', intel)
            for condition in ('dark', '天黑了', 'extraIntel', '一手情报', 'welfare', '福利多多', 'gemMaze', '宝石迷阵'):
                with self.subTest(condition=condition, intel=intel):
                    result = compute(condition, intel)
                    self.assertTrue(result['exactStates'])
                    self.assertEqual(result['exactStates'], base['exactStates'])
                    self.assertEqual(result['predictionSnapshot']['forecast'], base['predictionSnapshot']['forecast'])
                    frozen = result['frozenPrediction']
                    self.assertEqual(frozen['estimate'], base['frozenPrediction']['estimate'])
                    self.assertEqual(frozen['globalLine'], base['frozenPrediction']['globalLine'])
                    self.assertEqual(frozen['marginalLine'], base['frozenPrediction']['marginalLine'])
                    self.assertEqual(frozen['costInfo'], base['frozenPrediction']['costInfo'])
                    self.assertEqual(frozen['costInfo']['allCosts'], 6000 + intel)
