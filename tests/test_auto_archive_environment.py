import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import main
from auto_archiver import AutoArchiver
from current_match import CurrentMatch

CATALOG_FIELDS=('venueId','boxId','catalogVersion','catalogApprovalStatus','catalogSha256',
                'gameEvidenceCohort','venueEvidenceClass','boxEvidenceClass')

class AutoArchiveEnvironmentTests(unittest.TestCase):
    def context(self):
        current=CurrentMatch()
        ctx={'id':current.id,'isSettlement':True,'settlementReady':True,
             'lobbyVenueKey':'shanhu','venue':'中级场 · 珊瑚场','box':'琉璃宝箱 · 宝石类概率提升',
             'settlementData':{'isSettlement':True,'clearingPrice':666666,'actualTotal':631993,
                               'winner':'汐','acquired':None}}
        with patch.object(main,'CURRENT_MATCH',current):
            main.sync_vision_to_current_match(ctx)
        return ctx

    def test_observed_catalog_survives_actual_transaction_and_reload(self):
        ctx=self.context()
        expected={k:ctx[k] for k in CATALOG_FIELDS}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'history.json'
            saved=AutoArchiver([str(path)]).archive_match(ctx)
            self.assertIsNotNone(saved)
            row=json.loads(path.read_text(encoding='utf-8'))['records'][0]
        env=row['environment']
        self.assertEqual({k:env.get(k) for k in CATALOG_FIELDS},expected)
        self.assertEqual(env['box'],'琉璃宝箱')
        self.assertIsNone(env['boxType'],'No evidence for a legacy wood type')
        self.assertEqual(row['lifecycleStatus'],'DRAFT')

    def test_late_catalog_resolution_is_not_discarded_as_duplicate(self):
        resolved=self.context()
        unresolved=copy.deepcopy(resolved)
        for key in CATALOG_FIELDS: unresolved.pop(key,None)
        with tempfile.TemporaryDirectory() as tmp:
            archiver=AutoArchiver([str(Path(tmp)/'history.json')])
            self.assertIsNotNone(archiver.archive_match(unresolved))
            saved=archiver.archive_match(resolved)
            self.assertIsNotNone(saved)
            self.assertEqual(saved['environment']['boxId'],resolved['boxId'])

    def test_missing_environment_does_not_invent_a_venue_or_box_type(self):
        ctx=self.context()
        for key in (*CATALOG_FIELDS,'venue','box','lobbyVenueKey'):ctx.pop(key,None)
        with tempfile.TemporaryDirectory() as tmp:
            saved=AutoArchiver([str(Path(tmp)/'history.json')]).archive_match(ctx)
        self.assertIsNone(saved['environment']['venue'])
        self.assertIsNone(saved['environment']['boxType'])

    def test_clearer_items_update_same_bill_before_duplicate_timeout(self):
        ctx = self.context()
        ctx['settlementItems'] = [{'row': 0, 'col': 0, 'widthCells': 1, 'heightCells': 1,
                                   'status': 'unknown', 'price': None}]
        with tempfile.TemporaryDirectory() as tmp, patch('auto_archiver.time.time', return_value=100):
            path = Path(tmp) / 'history.json'
            archiver = AutoArchiver([str(path)])
            self.assertIsNotNone(archiver.archive_match(ctx))
            ctx['settlementReady'] = True
            ctx['settlementItems'][0].update(status='exact', exactItemId='observed-id', price=8177, name='observed')
            saved = archiver.archive_match(ctx)
            self.assertIsNotNone(saved)
            self.assertEqual(saved['settlement']['settlementItems'][0]['name'], 'observed')
            ctx['settlementReady'] = True
            self.assertIsNone(archiver.archive_match(ctx))
            self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['records']), 1)
