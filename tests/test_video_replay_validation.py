import unittest

from tools.replay_videos import validate_recorded_bills


class VideoReplayValidationTests(unittest.TestCase):
    def test_wrong_animation_write_fails_even_if_final_file_is_correct(self):
        expected = [{'clearingPrice': 666666, 'actualTotal': 631993, 'profit': -34673,
                     'visibleItemCount': 1}]
        record = {'settlement': {'clearingPrice': 666666, 'actualTotal': 631993,
                                'realizedProfit': -34673, 'settlementItems': [{}]}}
        writes = {'archives': [{'seconds': 236, 'settlement': {'clearingPrice': 666666, 'actualTotal': 17217}}]}
        errors = validate_recorded_bills(writes, [record], expected)
        self.assertEqual(len(errors), 1)
        self.assertIn('236s', errors[0])

    def test_missing_record_and_empty_scroll_cannot_pass_completion(self):
        expected = [{'clearingPrice': 666668, 'actualTotal': 538255, 'profit': -128413,
                     'visibleItemCount': 21}]
        self.assertTrue(validate_recorded_bills({}, [], expected))
        record = {'settlement': {'clearingPrice': 666668, 'actualTotal': 538255,
                                'realizedProfit': -128413, 'settlementItems': []}}
        self.assertIn('Archived visible item count differs from recording',
                      validate_recorded_bills({}, [record], expected))
        self.assertTrue(validate_recorded_bills({}, [record, {'settlement': {}}], expected))
