import copy
from pathlib import Path
import unittest

import cv2
import numpy as np

from settlement_identity_memory import SettlementIdentityMemory
from settlement_item_recognizer import SettlementItemRecognizer


ROOT = Path(__file__).resolve().parents[1]


class SettlementIdentityMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def frame(path):
            board = cv2.imdecode(np.fromfile(ROOT/path, np.uint8), 1)
            result = np.zeros((1080, 1920, 3), np.uint8)
            result[214:776, 1315:1878] = board
            return result
        cls.early = frame('tests/fixtures/video_replay/reveal_board_450.png')
        cls.final = frame('tests/fixtures/settlement_cards_v2/2026-08-18_11-19-25_455.png')
        r = SettlementItemRecognizer()
        cls.early_ledger = r.parse_settlement_ledger(cls.early)
        cls.final_ledger = r.parse_settlement_ledger(cls.final, actual_total=426860)
        # Exercise transfer independently of improvements to single-frame recall.
        for item in cls.final_ledger['settlementItems']:
            if (item['row'], item['col']) in {(0, 0), (0, 1), (0, 4), (0, 6)}:
                item.update(status='unknown', name=None, price=None, exactItemId=None)

    def memory(self):
        memory = SettlementIdentityMemory()
        memory.observe(key=('match-A', 1), ledger=self.early_ledger, frame=self.early,
                       captured_at='2026-08-18T11:26:55+08:00')
        return memory

    def fuse(self, memory, **overrides):
        arguments = dict(key=('match-A', 1), ledger=self.final_ledger, frame=self.final,
                         captured_at='2026-08-18T11:27:00+08:00',
                         persist=lambda frame, at: dict(evidenceId='source-original', sha256='a'*64))
        arguments.update(overrides)
        return memory.fuse(**arguments)

    def test_reveal_identity_requires_registered_pixels_and_persisted_original(self):
        result = self.fuse(self.memory())
        expected = {(0, 0): '柠檬气泡水', (0, 1): '崭新的弹珠',
                    (0, 3): '噗卡好梦棉花糖', (0, 4): '惠比寿宫廷小塔',
                    (0, 6): '气象指南'}
        promoted = [i for i in result['settlementItems'] if i.get('identityObservation')]
        self.assertEqual({(i['row'], i['col']): i['name'] for i in promoted}, expected)
        self.assertEqual(len(result['settlementIdentityFileOriginals']), 1)
        for item in promoted:
            self.assertEqual(item['identityObservation']['parentEvidenceId'], 'source-original')
        self.assertFalse(result['settlementLedgerVerified'])
        self.assertEqual(self.final_ledger, self.fuse(self.memory(), persist=lambda *args: None))

    def test_no_cross_match_expired_or_scrolled_identity_transfer(self):
        for change in (dict(key=('match-B', 2)),
                       dict(captured_at='2026-08-18T11:29:00+08:00'),
                       dict(frame=np.roll(self.final, 56, axis=0))):
            with self.subTest(change=list(change)):
                self.assertEqual(self.final_ledger, self.fuse(self.memory(), **change))

    def test_conflicting_exact_identity_blocks_entire_source_view(self):
        ledger = copy.deepcopy(self.final_ledger)
        item = next(i for i in ledger['settlementItems'] if (i['row'], i['col']) == (0, 0))
        item.update(status='exact', exactItemId='different-item')
        self.assertEqual(ledger, self.fuse(self.memory(), ledger=ledger))
