import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(os.environ.get('NTE_TEST_RUNTIME_ROOT', Path(__file__).resolve().parents[1]))


class DarkBidGuardTests(unittest.TestCase):
    def test_hidden_bid_never_drives_profit_or_fold_and_does_not_mutate_facts(self):
        for condition in ('dark', '天黑了'):
            baseline = None
            for bid in (None, 0, 10000, 900000):
                ctx = {'q': 1, 'avg': 60040, 'knownGold': '算力面包', 'goldCount': 1,
                    'purple': 0, 'redCount': 0, 'blueCount': 0, 'greenCount': 0, 'whiteCount': 0,
                    'fieldCondition': condition, 'leaderBid': bid, 'targetProfit': 0,
                    'costs': {'entry': 5000, 'intel': 0, 'other': 0}}
                script = "const fs=require('fs'),e=require('./core/auction_engine_v06.js'),c=JSON.parse(fs.readFileSync(0,'utf8')); const before=JSON.stringify(c),r=e.solveAuctionPipeline(c); console.log(JSON.stringify({r,unchanged:before===JSON.stringify(c)}));"
                direct = json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'), '-e', script], cwd=ROOT, input=json.dumps(ctx), text=True, encoding='utf-8'))
                self.assertTrue(direct['unchanged'])
                result = json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'), 'core/live_shadow_runtime.js', '--once'], cwd=ROOT, input=json.dumps({'ctx':ctx,'records':[]}), text=True, encoding='utf-8'))
                for decision in (direct['r']['decision'], result['frozenPrediction']['decision']):
                    self.assertIsNone(decision['expectedProfit'])
                    self.assertIsNone(decision['roiOnTotalSpend'])
                    self.assertFalse(decision['isFold'])
                    self.assertTrue(decision['hiddenBids'])
                frozen = result['frozenPrediction']
                values = [frozen.get(k) for k in ('estimate', 'globalLine', 'marginalLine')]
                self.assertIsNotNone(values[0])
                if baseline is None:
                    baseline = values
                self.assertEqual(values, baseline)
                self.assertIn('出价金额不可见', frozen['decision']['actionReason'])

    def test_standard_bid_still_affects_profit(self):
        decisions = []
        for bid in (10000, 900000):
            ctx = {'q':1,'avg':60040,'knownGold':'算力面包','goldCount':1,'purple':0,
                   'redCount':0,'blueCount':0,'greenCount':0,'whiteCount':0,
                   'fieldCondition':'standard','leaderBid':bid,'costs':{'entry':5000,'intel':0,'other':0}}
            result = json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'), 'core/live_shadow_runtime.js', '--once'], cwd=ROOT, input=json.dumps({'ctx':ctx,'records':[]}), text=True, encoding='utf-8'))
            decisions.append(result['frozenPrediction']['decision'])
        self.assertGreater(decisions[0]['expectedProfit'], 0)
        self.assertLess(decisions[1]['expectedProfit'], 0)
        self.assertFalse(decisions[0]['hiddenBids'])
