import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'core'))
from acquisition_authority import AcquisitionNameTracker, acquisition_from_context


class AcquisitionNameTrackerTests(unittest.TestCase):
    def test_configured_name_supports_late_settlement_and_survives_match_change(self):
        tracker = AcquisitionNameTracker()
        tracker.set_player_name('秋星祭02')
        for key, winner, expected in [('first', '秋星祭02', True), ('second', '汐', False)]:
            tracker.bind(key)
            self.assertIsNone(tracker.observe_winner(winner, .99, False, 1))
            self.assertIsNone(tracker.observe_winner(winner, .99, False, 1))
            self.assertIs(tracker.observe_winner(winner, .99, False, 2), expected)
            self.assertEqual(tracker.evidence()['configuredPlayerName'], '秋星祭02')

    def test_configured_identity_conflicts_and_changes_revoke(self):
        for conflict in ('own', 'opponent'):
            tracker = AcquisitionNameTracker()
            tracker.bind('match')
            tracker.set_player_name('秋星祭02')
            tracker.observe_winner('秋星祭02', .99, False, 1)
            self.assertTrue(tracker.observe_winner('秋星祭02', .99, False, 2))
            for frame in (3, 4):
                tracker.observe_name(4 if conflict == 'own' else 2,
                                     '新名字' if conflict == 'own' else '秋星祭02', frame)
            self.assertIsNone(tracker.value)
            self.assertIsNone(tracker.observe_winner('秋星祭02', .99, False, 5))
        tracker = self.seeded()
        tracker.set_player_name('秋星祭02')
        tracker.observe_winner('秋星祭02', .99, False, 3)
        self.assertTrue(tracker.observe_winner('秋星祭02', .99, False, 4))
        tracker.set_player_name('')
        self.assertIsNone(tracker.value)
        self.assertIsNone(tracker.observe_winner('秋星祭02', .99, False, 5))
        self.assertTrue(tracker.observe_winner('秋星祭02', .99, False, 6))

    def test_configured_name_does_not_bypass_weak_or_ambiguous_winner(self):
        for confidence, ambiguous in ((.4, False), (.99, True)):
            tracker = AcquisitionNameTracker()
            tracker.bind('match')
            tracker.set_player_name('秋星祭02')
            for frame in (1, 2, 3):
                self.assertIsNone(tracker.observe_winner('秋星祭02', confidence, ambiguous, frame))

    def test_pipeline_preference_change_clears_previous_published_identity(self):
        from unittest.mock import patch
        from vision_pipeline import NTEVisionPipeline
        pipe = NTEVisionPipeline()
        try:
            with patch('player_identity.get_player_name', return_value='秋星祭02'):
                pipe._bind_acquisition_record('match')
            pipe.current_context.update(isAcquired=True, settlementData={'acquired': True, 'winner': '秋星祭02'})
            with patch('player_identity.get_player_name', return_value='新名字'):
                pipe._bind_acquisition_record('match')
            self.assertEqual(pipe._acquisition_names.configured_name, '新名字')
            self.assertEqual(acquisition_from_context(pipe.current_context), (True, None))
            self.assertIsNone(pipe.current_context['settlementData']['winner'])
        finally:
            executor = getattr(pipe, '_navigation_executor', None)
            if executor is not None:
                executor.shutdown(wait=True)

    def test_name_preference_persists_and_rejects_invalid_updates(self):
        import tempfile
        from unittest.mock import patch
        import player_identity
        with tempfile.TemporaryDirectory() as folder, patch.object(player_identity, 'resolve_runtime_data_root', return_value=Path(folder)):
            self.assertEqual(player_identity.get_player_name(), '')
            player_identity.set_player_name(' 秋星祭02 ')
            self.assertEqual(player_identity.get_player_name(), '秋星祭02')
            for value in (True, None, 'a\nb', 'a' * 65):
                with self.assertRaises(ValueError):
                    player_identity.set_player_name(value)
                self.assertEqual(player_identity.get_player_name(), '秋星祭02')
            player_identity.set_player_name('')
            self.assertEqual(player_identity.get_player_name(), '')

    def seeded(self):
        tracker = AcquisitionNameTracker()
        tracker.bind('match-one')
        for frame in (1, 2):
            tracker.observe_name(4, '秋星祭02', frame)
            tracker.observe_name(1, '汐', frame)
        return tracker

    def test_self_and_other_require_two_fresh_winner_readings(self):
        for name, expected in [('秋星祭02', True), ('汐', False)]:
            tracker = self.seeded()
            self.assertIsNone(tracker.observe_winner(name, .99, False, 3))
            self.assertIsNone(tracker.observe_winner(name, .99, False, 3))
            self.assertIs(tracker.observe_winner(name, .99, False, 4), expected)
            self.assertEqual(acquisition_from_context({'settlementData': {'acquired': tracker.value}}), (True, expected))

    def test_unknown_name_low_confidence_and_duplicates_are_not_other(self):
        for kind in ('unknown', 'weak', 'duplicate'):
            tracker = self.seeded()
            if kind == 'duplicate':
                tracker.observe_name(2, '秋星祭02', 2)
            name = '秋星祭O2' if kind == 'unknown' else '秋星祭02'
            for frame in (3, 4, 5):
                self.assertIsNone(tracker.observe_winner(name, .4 if kind == 'weak' else .99, False, frame))

    def test_conflicts_revoke_but_empty_frame_retains_confirmed_value(self):
        tracker = self.seeded()
        tracker.observe_winner('秋星祭02', .99, False, 3)
        self.assertTrue(tracker.observe_winner('秋星祭02', .99, False, 4))
        self.assertTrue(tracker.observe_winner(None, 0, False, 5))
        self.assertIsNone(tracker.observe_winner('汐', .99, False, 6))
        self.assertFalse(tracker.observe_winner('汐', .99, False, 7))
        self.assertIsNone(tracker.observe_winner('汐', .99, True, 8))

    def test_cross_match_reset_requires_new_roster(self):
        tracker = self.seeded()
        tracker.bind('match-two')
        for frame in (3, 4, 5):
            self.assertIsNone(tracker.observe_winner('秋星祭02', .99, False, frame))

    def test_repeated_cached_roster_does_not_confirm_identity(self):
        tracker = AcquisitionNameTracker()
        tracker.bind('match-one')
        for _ in range(3):
            tracker.observe_name(4, '秋星祭02', 1)
        for frame in (2, 3):
            self.assertIsNone(tracker.observe_winner('秋星祭02', .99, False, frame))

    def test_single_character_roster_names_reach_tracker_and_evidence_is_detached(self):
        from vision_pipeline import NTEVisionPipeline
        pipe = NTEVisionPipeline()
        items = [(slot, .12, .2 + slot * .14, .03, .05, name)
                 for slot, name in enumerate(['音', '汐', '莫要', '秋星祭02'], 1)]
        pipe._update_seat_names_and_finals_from_ocr(items, 1, .1)
        self.assertEqual(pipe._slot_names[1], '音')
        self.assertEqual(pipe._slot_names[2], '汐')
        tracker = AcquisitionNameTracker()
        tracker.bind('match-one')
        for frame in (1, 2):
            for slot, name in pipe._slot_names.items():
                tracker.observe_name(slot, name, frame)
        tracker.observe_winner('音', .99, False, 3)
        self.assertFalse(tracker.observe_winner('音', .99, False, 4))
        proof = tracker.evidence()
        self.assertEqual(proof['winnerSamples'], 2)
        self.assertEqual(proof['recordStableKey'], 'match-one')
        proof['roster'][0]['name'] = 'mutated'
        self.assertEqual(tracker.evidence()['roster'][0]['name'], '音')

    def test_late_conflicting_roster_revokes_confirmed_ownership(self):
        for slot, name in ((2, '秋星祭02'), (4, '新名字')):
            tracker = self.seeded()
            tracker.observe_winner('秋星祭02', .99, False, 3)
            self.assertTrue(tracker.observe_winner('秋星祭02', .99, False, 4))
            tracker.observe_name(slot, name, 5)
            self.assertIsNone(tracker.value)
            self.assertIsNone(tracker.observe_winner('秋星祭02', .99, False, 6))

    def test_late_settlement_can_confirm_only_after_fresh_roster(self):
        tracker = AcquisitionNameTracker()
        tracker.bind('late-entry')
        for frame in (1, 2, 3):
            self.assertIsNone(tracker.observe_winner('汐', .99, False, frame))
        for frame in (4, 5):
            tracker.observe_name(4, '秋星祭02', frame)
            tracker.observe_name(1, '汐', frame)
        self.assertIsNone(tracker.value)
        self.assertFalse(tracker.observe_winner('汐', .99, False, 6))

    def test_keyboard_new_key_clears_ownership_before_early_returns(self):
        import numpy as np
        from unittest.mock import patch
        from keyboard_auction_pipeline import KeyboardAuctionPipeline
        for scene, busy in (('UNKNOWN', False), ('SETTLEMENT', True)):
            with self.subTest(scene=scene):
                pipe = KeyboardAuctionPipeline()
                try:
                    pipe._acquisition_names = self.seeded()
                    pipe._acquisition_names.observe_winner('秋星祭02', .99, False, 3)
                    pipe._acquisition_names.observe_winner('秋星祭02', .99, False, 4)
                    old = {'acquired': True, 'winner': '秋星祭02'}
                    pipe.current_context.update(recordStableKey='match-one', isAcquired=True,
                        acquired=True, didCurrentUserAcquire=True, winner='秋星祭02',
                        settlement=old, settlementData=old)
                    pipe._navigation_future = object() if busy else None
                    route = {'scene': scene, 'phase': scene, 'generation': 1}
                    with patch.object(pipe, '_classify_scene_fast', return_value=route), \
                         patch.object(pipe, '_finish_navigation_read'):
                        result = pipe.process_frame(np.zeros((20, 20, 3), dtype=np.uint8),
                                                    record_stable_key='match-two')
                    self.assertEqual(result['recordStableKey'], 'match-two')
                    self.assertEqual(acquisition_from_context(result), (True, None))
                    self.assertIsNone(result.get('winner'))
                    self.assertEqual(pipe._acquisition_names.names, {})
                    self.assertIsNone(pipe._acquisition_names.value)
                    self.assertTrue(old['acquired'])  # Do not mutate previously published evidence.
                finally:
                    pipe._navigation_future = None
                    pipe._navigation_executor.shutdown(wait=True)


if __name__ == '__main__':
    unittest.main()
