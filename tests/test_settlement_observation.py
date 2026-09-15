import unittest
import numpy as np

from settlement_observation import SettlementObservation


class SettlementObservationTests(unittest.TestCase):
    def observation(self, selector, key, items, color, timestamp):
        return selector.select(key=key, ledger={'settlementItems': items},
                               frame=np.full((3, 3, 3), color, np.uint8), captured_at=timestamp)

    def test_scroll_keeps_original_items_pixels_and_time_together(self):
        selector = SettlementObservation()
        items = [{'name': 'observed', 'status': 'exact', 'widthCells': 5, 'heightCells': 5}]
        self.observation(selector, ('match-a', 100), items, 50, 'first')
        # Many single-cell fragments must not outrank one real closed card.
        fragments = [{'groupingAmbiguous': True} for _ in range(40)]
        self.observation(selector, ('match-a', 100), fragments, 100, 'scrolled')
        selected = self.observation(selector, ('match-a', 100), [], 200, 'empty')
        self.assertEqual(selected['capturedAt'], 'first')
        self.assertEqual(selected['ledger']['settlementItems'][0]['name'], 'observed')
        self.assertTrue(np.all(selected['frame'] == 50))
        items[0]['name'] = 'mutated caller'
        self.assertEqual(selected['ledger']['settlementItems'][0]['name'], 'observed')

    def test_better_identity_replaces_equal_geometry_but_never_crosses_bill(self):
        selector = SettlementObservation()
        self.observation(selector, ('a', 100), [{'status': 'unknown'}], 1, 'unknown')
        result = self.observation(selector, ('a', 100), [{'status': 'exact'}], 2, 'identified')
        self.assertEqual(result['capturedAt'], 'identified')
        result = self.observation(selector, ('b', 100), [], 3, 'new-match')
        self.assertEqual(result['ledger']['settlementItems'], [])
        result = self.observation(selector, ('b', 200), [], 4, 'new-bill')
        self.assertEqual(result['capturedAt'], 'new-bill')
