import unittest
from current_match import CurrentMatch

class EmptyDraftFactsTests(unittest.TestCase):
    def test_defaults_are_not_observations(self):
        match=CurrentMatch()
        self.assertFalse(match.has_any_fact())
        match.begin_next_match()
        self.assertFalse(match.has_any_fact())
    def test_explicit_zero_and_positive_costs_are_facts(self):
        for key in ('intelCost','otherCost','futureIncrementalCost','q'):
            for value in (0,1):
                with self.subTest(key=key,value=value):
                    match=CurrentMatch()
                    match.apply_facts({key:value},source='manual',intent='confirm')
                    self.assertTrue(match.has_any_fact())
    def test_raw_evidence_remains_durable(self):
        match=CurrentMatch();match.facts['settlementEvidence']={'path':'capture.png'}
        self.assertTrue(match.has_any_fact())

    def test_empty_write_is_skipped_but_cleared_saved_record_is_flushed(self):
        import main
        from unittest.mock import Mock, patch
        match=CurrentMatch();archiver=Mock();archiver.db_paths=['isolated-history'];archiver.save_draft.return_value={'id':match.id}
        with patch.object(main,'CURRENT_MATCH',match), patch.object(main,'DRAFT_ARCHIVER',archiver), patch.object(main,'_LAST_DRAFT_WRITE',None), patch.object(main,'_manual_draft_record',return_value={}), patch.object(main,'LATEST_PAYLOAD',{}), patch.object(main,'_DRAFT_TIMER',None):
            self.assertIsNone(main._persist_current_draft_now())
            archiver.save_draft.assert_not_called()
            main._LAST_DRAFT_WRITE=(match.id,1)
            self.assertEqual(main.flush_draft_save_sync(),{'id':match.id})
            archiver.save_draft.assert_called_once()
