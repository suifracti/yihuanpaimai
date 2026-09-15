import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from current_match import CurrentMatch
from v06_adapter import canonical_to_v06_solver_input
class CostPersistenceTests(unittest.TestCase):
 def test_costs_survive_current_canonical_and_solver_translation(self):
  cm=CurrentMatch();cm.apply_facts({'venue':'shanhu','entryCost':5000,'intelCost':1200,'otherCost':300,'futureIncrementalCost':700})
  record=cm.to_canonical();expected={'entry':5000,'intel':1200,'other':300,'sunkCost':6500,'futureIncrementalCost':700,'total':7200}
  self.assertEqual(record['costs'],expected)
  self.assertEqual(canonical_to_v06_solver_input(record)['costs'],expected)
  cm.apply_facts({'intelCost':0,'otherCost':0,'futureIncrementalCost':0})
  self.assertEqual(cm.to_canonical()['costs']['total'],5000)
 def test_unknown_entry_does_not_become_free(self):
  cm=CurrentMatch();cm.apply_facts({'intelCost':1200})
  self.assertIsNone(cm.to_canonical()['costs']['total'])
  self.assertEqual(cm.to_canonical()['costs']['intel'],1200)
 def test_live_overrides_replace_stale_nested_costs(self):
  from live_match_control import LiveMatchControl
  cm=CurrentMatch();control=LiveMatchControl();control.match_id=cm.id
  control.overrides={'intelCost':1200,'otherCost':300,'futureIncrementalCost':700}
  old={'entry':5000,'intel':0,'other':0,'sunkCost':5000,'futureIncrementalCost':0,'total':5000}
  ctx=control.apply_to_frame({'costs':old},cm)
  self.assertEqual(ctx['costs']['total'],7200)
  self.assertEqual(old['total'],5000)
  control.overrides={'intelCost':0,'otherCost':0,'futureIncrementalCost':0}
  self.assertEqual(control.apply_to_frame(ctx,cm)['costs']['total'],5000)
if __name__=='__main__':unittest.main()
