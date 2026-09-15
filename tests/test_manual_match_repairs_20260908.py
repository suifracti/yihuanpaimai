"""Regression coverage for manual clues, animated bills and original browsing."""
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import cv2
from current_match import CurrentMatch
from settlement_review import SettlementReviewService
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2, KIND_MAIN


class ManualMatchRepairs(unittest.TestCase):
    def test_screenshot_delete_bridge_preserves_request_and_ownership(self):
        from main_window import MainWindowBridge
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            raw = cv2.imencode('.png', np.zeros((24, 32, 3), dtype=np.uint8))[1].tobytes()
            desc = SettlementEvidenceStoreV2(tmp).save_original(record_stable_key='bridge01', kind=KIND_MAIN, image_bytes=raw)
            service = SettlementReviewService(data_root_provider=lambda: tmp)
            bridge = MainWindowBridge(SimpleNamespace(visible=False), settlement_review_service=service)
            for action, count in [('delete_original_screenshot', 0), ('restore_original_screenshot', 1)]:
                reply = bridge.dispatch(json.dumps({'action': action, 'recordId': 'bridge01',
                    'evidenceId': desc['evidenceId'], 'requestId': 'delete-test'}))
                self.assertEqual(reply['requestId'], 'delete-test')
                self.assertTrue(reply['originalScreenshots']['ok'])
                self.assertEqual(len(reply['originalScreenshots']['images']), count)

    def test_remove_restore_is_record_scoped_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SettlementEvidenceStoreV2(tmp)
            raw = cv2.imencode('.png', np.full((24, 32, 3), 20, dtype=np.uint8))[1].tobytes()
            a = store.save_original(record_stable_key="match01", kind=KIND_MAIN, image_bytes=raw)
            b = store.save_original(record_stable_key="match02", kind=KIND_MAIN, image_bytes=raw)
            service = SettlementReviewService(data_root_provider=lambda: tmp)
            self.assertFalse(service.remove_original_screenshot("match02", a['evidenceId'])['ok'])
            removed = service.remove_original_screenshot("match01", a['evidenceId'])
            self.assertTrue(removed['ok'])
            self.assertEqual(removed['images'], [])
            self.assertEqual(removed['undoEvidenceId'], a['evidenceId'])
            reopened = SettlementReviewService(data_root_provider=lambda: tmp)
            self.assertEqual(reopened.list_original_screenshots('match01')['images'], [])
            self.assertEqual(len(reopened.list_original_screenshots('match02')['images']), 1)
            self.assertEqual(store.load_original(b), raw)
            self.assertEqual(store.load_original(a), raw)
            self.assertEqual(len(reopened.remove_original_screenshot('match01', a['evidenceId'], restore=True)['images']), 1)
            reopened.remove_original_screenshot('match01', a['evidenceId'])
            store.save_original(record_stable_key="match01", kind=KIND_MAIN, image_bytes=raw)
            self.assertEqual(len(reopened.list_original_screenshots('match01')['images']), 1)

    def test_animation_cannot_become_verified_bill(self):
        match = CurrentMatch()
        match.apply_facts({"clearingPrice": 666666, "actualTotal": 4975,
            "realizedProfit": -661691, "settlementReady": False}, source="vision")
        self.assertIsNone(match.to_canonical()["settlement"]["actualTotal"])
        match.apply_facts({"clearingPrice": 666666, "actualTotal": 1072197,
            "realizedProfit": 405531, "settlementReady": True}, source="vision")
        self.assertEqual(match.to_canonical()["settlement"]["actualTotal"], 1072197)
        match.apply_facts({"actualTotal": 4975, "settlementReady": False}, source="vision")
        self.assertEqual(match.to_canonical()["settlement"]["actualTotal"], 1072197)
        self.assertIsNone(match.to_canonical()["settlement"]["acquired"])

    def test_manual_bill_does_not_need_ocr_readiness(self):
        match = CurrentMatch()
        match.apply_facts({"clearingPrice": 666666, "actualTotal": 1072197}, source="manual")
        self.assertEqual(match.to_canonical()["settlement"]["actualTotal"], 1072197)

    def test_original_gallery_loads_both_views_without_recognition(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SettlementEvidenceStoreV2(tmp)
            for value in (20, 100):
                store.save_original(record_stable_key="match01", kind=KIND_MAIN,
                    image_bytes=cv2.imencode('.png', np.full((24, 32, 3), value, dtype=np.uint8))[1].tobytes())
            service = SettlementReviewService(data_root_provider=lambda: tmp)
            with patch.object(service, "_run_recognizer", side_effect=AssertionError("must not recognize")):
                result = service.list_original_screenshots("match01")
            self.assertEqual(len(result["images"]), 2)
            self.assertTrue(all(i["dataUrl"].startswith("data:image/png;base64,") for i in result["images"]))
            desc = store.list_record_evidence("match01")[0]
            (Path(tmp) / desc["relativePath"]).write_bytes(b"corrupted")
            result = service.list_original_screenshots("match01")
            self.assertEqual(sum("error" in i for i in result["images"]), 1)
