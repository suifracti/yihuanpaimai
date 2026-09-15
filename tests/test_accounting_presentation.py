"""Exercise native Main/HUD projection using real CurrentMatch facts."""
import unittest
from unittest.mock import patch
from current_match import CurrentMatch
import main


class AccountingPresentationTests(unittest.TestCase):
    def test_main_and_hud_agree_on_ownership_cost_and_receipt_boundaries(self):
        for acquired, entry, receipt, actual, expected in (
            (True, 5000, 3000, 60040, 16540),
            (False, 5000, 3000, 60040, -3500),
            (None, 5000, 3000, 60040, None),
            (True, None, 3000, 60040, None),
            (True, 0, 3000, 60040, 21540),
            (True, 5000, 0, 60040, 13540),
            (True, 5000, None, 60040, None),
            (True, 5000, 3000, 43501, 1),
        ):
            with self.subTest(acquired=acquired, entry=entry, receipt=receipt, expected=expected):
                current = CurrentMatch()
                current.apply_facts({'fieldCondition': 'welfare', 'entryCost': entry,
                    'intelCost': 1200, 'otherCost': 300, 'futureIncrementalCost': 99999,
                    'isAcquired': acquired, 'actualTotal': actual, 'clearingPrice': 40000,
                    'welfareReceived': receipt, 'realizedProfit': 999999}, intent='confirm')
                with patch.object(main, 'CURRENT_MATCH', current):
                    summary = main.get_current_match_presentation_summary()
                    hud = main.build_manual_alpha_payload(include_solver_input=False)
                self.assertIn('sessionAccounting', summary)
                self.assertEqual(summary['sessionAccounting'], hud['sessionAccounting'])
                self.assertEqual(summary['sessionAccounting']['sessionNet'], expected)
                self.assertEqual(summary['sessionAccounting']['welfareReceived'], receipt)
                self.assertEqual(current.snapshot()['actualTotal'], actual)
                self.assertEqual(current.snapshot()['realizedProfit'], 999999)
