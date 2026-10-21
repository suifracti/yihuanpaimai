"""Narrow geometry regression and opt-in replay of the Oct-21 saved game."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from settlement_item_recognizer import SettlementItemRecognizer
from warehouse_reconstruction import WarehouseReconstructionProcessor
from warehouse_placement_resolver import WarehousePlacementResolver
from warehouse_scrollbar_observation import warehouse_content_roi

FIXTURE = json.loads((Path(__file__).parent/'fixtures/m4b_20261021_review_regression.json').read_text('utf-8'))


class ReviewGeometryRegression(unittest.TestCase):
    def test_item_reconstruction_uses_existing_content_domain(self):
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[780:836] = (50, 160, 220)  # Sell-quality controls, below the grid.
        proc = WarehouseReconstructionProcessor('record', placement_resolver=Mock(),
            observe_grid=lambda *a, **k: {'grid':{'status':'UNKNOWN'}})
        proc.accept_segment(frame, {'recordStableKey':'record','evidenceId':'page',
            'sha256':'a'*64,'width':1920,'height':1080}, 0, already_cropped=False)
        x1,y1,x2,y2 = warehouse_content_roi(1920,1080)
        self.assertEqual(proc._source_origins['page'], (x1,y1))
        np.testing.assert_array_equal(proc._frames['page'], frame[y1:y2,x1:x2])
        self.assertFalse(proc._frames['page'].any())

    def test_empty_candidate_is_not_sent_for_identity_matching(self):
        frame = np.full((112,112,3), (28,28,20), np.uint8)
        frame[56:,56:] = (180,140,60)  # Visible blue item; not an all-empty frame.
        resolver = WarehousePlacementResolver(manifest_path=Path('unused-catalog.json'))
        queries = []
        def match(roi,w,h,**kwargs):
            if (w,h)==(1,1):
                queries.append(roi.copy())
            return 0.,[],0
        resolver.match_catalog_candidates = match
        grid = {'grid':{'status':'OK','xLines':[0,56,112],'yLines':[0,56,112]}}
        with patch('warehouse_placement_resolver.observe_warehouse_grid', return_value=grid):
            resolver.resolve(physical_ledger={'segments':[{'segmentId':'page','sequenceIndex':0}],'tracks':[]},
                descriptors=[{'evidenceId':'page','sequenceIndex':0,'sha256':'a'*64}],frames={'page':frame})
        self.assertTrue(queries)
        self.assertTrue(all(not np.array_equal(roi, frame[:56,:56]) for roi in queries))


@unittest.skipUnless(os.environ.get('NTE_M4B_WAREHOUSE_REPLAY_ROOT'), 'private saved originals are opt-in')
class SavedGameRegression(unittest.TestCase):
    def test_actual_controls_and_empty_slots_are_absent_after_production_refinement(self):
        root = Path(os.environ['NTE_M4B_WAREHOUSE_REPLAY_ROOT']).resolve()
        manifest = json.loads((root/'warehouse-intake'/f"{FIXTURE['sessionId']}.json").read_text('utf-8'))
        for case in FIXTURE['falseUnits']:
            descriptor = case['descriptor']
            raw = (root/descriptor['relativePath']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), descriptor['sha256'])
            image = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            x,y,r,b = map(int,case['bbox'])
            if case['type']=='footer':
                self.assertGreaterEqual(y,warehouse_content_roi(image.shape[1],image.shape[0])[3])
            else:
                hsv = cv2.cvtColor(image[y:b,x:r],cv2.COLOR_BGR2HSV)
                self.assertIsNone(SettlementItemRecognizer._cell_rarity(hsv,0,0,r-x,b-y)[0])
                self.assertTrue(SettlementItemRecognizer._cell_is_empty(hsv,0,0,r-x,b-y))
        work = root/'warehouse-refinement'/FIXTURE['sessionId']
        before = json.loads((work/f"{FIXTURE['beforeJobId']}.json").read_text('utf-8'))['evidence']['review_units']
        after = json.loads((root/manifest['refinement']['resultPath']).read_text('utf-8'))['evidence']['review_units']
        bad = {case['id'] for case in FIXTURE['falseUnits']}
        self.assertTrue(bad <= {u['reviewUnitId'] for u in before})
        self.assertFalse(bad & {u['reviewUnitId'] for u in after})
        confirmed = lambda units: {u['reviewUnitId']:u['selectedCatalogId'] for u in units
                                  if u.get('confirmationStatus')=='CONFIRMED'}
        self.assertEqual(confirmed(before),confirmed(after))
        self.assertEqual(manifest['refinement']['state'],'COMPLETE')

    def test_actual_bill_readback_uses_game_original_and_keeps_catalog_separate(self):
        from native_trial_drafts import NativeTrialDraftStore
        from settlement_review import SettlementReviewService
        root = Path(os.environ['NTE_M4B_WAREHOUSE_REPLAY_ROOT']).resolve()
        service = SettlementReviewService(native_trial_store=NativeTrialDraftStore(root/'canonical-history.json'))
        before = (root/'canonical-history.json').read_bytes()
        dto = service.create_review_session(FIXTURE['recordId'],'live-trial')['review']
        self.assertEqual(dto['screenshot']['sha256'],FIXTURE['billSha256'])
        self.assertEqual(dto['settlement']['actualTotal'],FIXTURE['actualTotal'])
        self.assertEqual(dto['settlement']['realizedProfit'],FIXTURE['realizedProfit'])
        self.assertNotEqual(dto['catalogValuation']['knownCatalogValue'],FIXTURE['actualTotal'])
        self.assertEqual((root/'canonical-history.json').read_bytes(),before)
