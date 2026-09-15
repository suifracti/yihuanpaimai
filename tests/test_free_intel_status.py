import copy
import unittest
from unittest.mock import patch
from field_intel_status import free_intel_status
from current_match import CurrentMatch
import main


class FreeIntelStatusTests(unittest.TestCase):
    def test_rule_rounds_do_not_create_observations_or_change_costs(self):
        for condition in ('extraIntel','extra_intel','first_intel','一手情报'):
            for round_no in (1,2,3,4,None,0,True,1.5,'1'):
                facts = {'fieldCondition':condition,'round':round_no,'intelCost':1200,
                         'intelObservations':[], 'intelFacts':{'q':{'status':'UNKNOWN','value':None}}}
                original = copy.deepcopy(facts)
                result = free_intel_status(facts)
                valid = type(round_no) is int and 1 <= round_no <= 4
                self.assertEqual(result['round'], round_no if valid else None)
                self.assertEqual(result['availableByRule'], round_no in (1,3) if valid else None)
                self.assertFalse(result['observed'])
                self.assertEqual(facts, original)
        self.assertIsNone(free_intel_status({'fieldCondition':'standard','round':1}))
        self.assertEqual(free_intel_status({'fieldCondition':'extraIntel','round':3,'scene':'SETTLEMENT'})['status'],'SETTLED')

    def test_native_main_hud_use_actual_round_and_reset(self):
        current = CurrentMatch()
        with patch.object(main,'CURRENT_MATCH',current):
            for round_no in (None,1,2,3,4):
                current.apply_facts({'fieldCondition':'extraIntel','roundNo':round_no,'intelCost':1200},intent='confirm')
                summary = main.get_current_match_presentation_summary()
                hud = main.build_manual_alpha_payload(include_solver_input=False)
                self.assertEqual(summary['freeIntelStatus'],hud['freeIntelStatus'])
                self.assertEqual(hud['freeIntelStatus']['round'],round_no)
                self.assertEqual(current.snapshot()['intelCost'],1200)
                self.assertFalse(current.snapshot().get('intelObservations'))
            current.begin_next_match()
            self.assertIsNone(main.get_current_match_presentation_summary()['freeIntelStatus'])
