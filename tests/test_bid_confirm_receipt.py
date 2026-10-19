"""Confirm, send, and a new-frame receipt. Drives the shipped chain and real videos."""
import json
from pathlib import Path
import tempfile
import unittest

import cv2

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / 'core'))

from bid_intent import per_match_fund_cap
from domain_action_session import confirm_send_and_receive
from durable_bid_obligations import DurableBidIntentBook
from scene_anchors import classify_auction_flow_frame


VIDEOS = ROOT / 'data' / 'videos'
PANEL_VIDEO = VIDEOS / '2026-09-08 13-40-43.mkv'


def frame_at(path, index):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise AssertionError(f'missing frame {index} in {path.name}')
    return frame


def current():
    return dict(matchId='m-video', matchGeneration=1, observationSessionId='s-video',
                round=3, factsRevision=4, scene='IN_AUCTION',
                decisionEligible=True, sourceQualified=True)


def event():
    # Feasible floor 666 minus zero costs is the Solver suggestion. The later
    # video frame shows that same committed bid on the control.
    scope = current()
    return dict(scope, predictionSnapshot={
        'schemaVersion': 'prediction-snapshot.v1', 'snapshotRole': 'latest_valid_pre_settlement',
        'matchId': scope['matchId'], 'round': scope['round'], 'predictionId': 'p-video',
        'input': {'inputHash': 'h-video', 'normalizedFacts': {
            'q': 9, 'goldAvg': 33538, 'round': scope['round'],
            'costs': {'sunkCost': 0, 'total': 0}, 'targetProfit': 0}},
        'status': {'solverStatus': 'valid', 'diagnosticOnly': False, 'provisional': False},
        'mode': {'informationMode': 'structural_only'},
        'forecast': {'scope': 'structural_inventory', 'quantiles': None,
                     'structural': {'feasibleRange': [666, 2000], 'center': 1000}}})


def native_scope():
    return dict(budget=0, leaseExpiresNs=10_000_000_000, takeoverGeneration=1,
                leaseId='video-lease',
                window=dict(hwnd=1, pid=2, processInstanceToken=3, focusEpoch=4))


class BidConfirmReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PANEL_VIDEO.is_file():
            raise AssertionError('local auction video is not on this machine')
        cls.panel = frame_at(PANEL_VIDEO, 4092)
        cls.filled = frame_at(PANEL_VIDEO, 6430)
        cls.settlement = frame_at(PANEL_VIDEO, 8769)
        cls.lobby = frame_at(PANEL_VIDEO, 233)

    def test_video_frames_label_panel_settlement_return_and_lobby(self):
        panel = classify_auction_flow_frame(self.panel)
        settlement = classify_auction_flow_frame(self.settlement)
        lobby = classify_auction_flow_frame(self.lobby)
        filled = classify_auction_flow_frame(self.filled)
        self.assertEqual(panel['scene'], 'BID_PANEL')
        self.assertEqual(settlement['scene'], 'SETTLEMENT')
        self.assertIn('RETURN', settlement['labels'])
        self.assertTrue(settlement['returnAvailable'])
        self.assertEqual(lobby['scene'], 'AUCTION_LOBBY')
        self.assertNotEqual(filled['scene'], 'BID_PANEL')
        self.assertIn(filled['scene'], ('IN_AUCTION', 'SETTLEMENT', 'AUCTION_LOBBY'))

    def test_config_default_cap_is_the_suggestion(self):
        example = json.loads((ROOT / 'app' / 'config.example.json').read_text(encoding='utf-8'))
        live = json.loads((ROOT / 'app' / 'config.json').read_text(encoding='utf-8'))
        self.assertIsNone(per_match_fund_cap(example))
        self.assertIsNone(per_match_fund_cap(live))
        self.assertIsNone(example['bid']['perMatchFundCap'])

    def test_confirm_send_and_new_frame_fills_the_solver_amount(self):
        result, second, stored = self._run(configured_cap=None, current_funds=2_802_874, next_frame=self.filled)
        self.assertTrue(result['sent'], result)
        self.assertEqual(result['suggestion'], 666)
        self.assertEqual(result['amount'], 666)
        self.assertEqual(result['envelope']['intent']['amount'], 666)
        self.assertLessEqual(result['amount'], 2_802_874)
        self.assertEqual(result['outcome'], 'FILLED', result)
        self.assertFalse(result['resendAllowed'])
        self.assertTrue(str(result['evidenceRef']).startswith('frame/'))
        self.assertEqual(second['reason'], 'RESEND_BLOCKED')
        self.assertFalse(second['sent'])
        self.assertEqual(stored, 'EFFECTIVE')

    def test_configured_cap_and_funds_cannot_exceed_the_suggestion(self):
        capped, _, stored = self._run(configured_cap=100, current_funds=2_802_874, next_frame=self.filled)
        self.assertEqual(capped['suggestion'], 666)
        self.assertEqual(capped['amount'], 100)
        self.assertEqual(capped['envelope']['intent']['amount'], 100)
        self.assertNotEqual(capped['outcome'], 'FILLED')
        self.assertFalse(capped['resendAllowed'])
        self.assertNotEqual(stored, 'EFFECTIVE')
        funds, second, _ = self._run(configured_cap=None, current_funds=50, next_frame=self.filled)
        self.assertEqual(funds['amount'], 50)
        self.assertLessEqual(funds['amount'], 50)
        self.assertNotEqual(funds['outcome'], 'FILLED')
        self.assertEqual(second['reason'], 'RESEND_BLOCKED')

    def test_unknown_or_unchanged_frame_does_not_resend(self):
        result, second, stored = self._run(configured_cap=None, current_funds=2_802_874, next_frame=self.panel)
        self.assertTrue(result['sent'], result)
        self.assertEqual(result['amount'], 666)
        self.assertEqual(result['outcome'], 'UNKNOWN')
        self.assertFalse(result['resendAllowed'])
        self.assertEqual(second['reason'], 'RESEND_BLOCKED')
        self.assertFalse(second['sent'])
        self.assertEqual(stored, 'UNKNOWN')

    def test_settlement_without_the_amount_is_not_a_fill_and_does_not_resend(self):
        result, second, stored = self._run(configured_cap=None, current_funds=2_802_874, next_frame=self.settlement)
        self.assertEqual(result['outcome'], 'NOT_FILLED', result)
        self.assertEqual(result['amount'], 666)
        self.assertFalse(result['resendAllowed'])
        self.assertEqual(second['reason'], 'RESEND_BLOCKED')
        self.assertNotEqual(stored, 'EFFECTIVE')

    def test_missing_confirmation_or_panel_does_not_send(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temp:
            path = Path(temp) / 'obligations.json'
            refused = confirm_send_and_receive(
                path, event(), current(), configured_cap=None, current_funds=2_802_874,
                user_confirmed=False, approval_id='main-window', pre_frame=self.panel,
                next_frame=self.filled, native_scope=native_scope(), now_ms=100, now_ns=100_000_000,
                deadline_ms=800, clock_id='bid-boot')
            self.assertEqual(refused['reason'], 'USER_CONFIRMATION_REQUIRED')
            self.assertFalse(refused['sent'])
            self.assertFalse(path.exists())
            wrong = confirm_send_and_receive(
                path, event(), current(), configured_cap=None, current_funds=2_802_874,
                user_confirmed=True, approval_id='main-window', pre_frame=self.lobby,
                next_frame=self.filled, native_scope=native_scope(), now_ms=100, now_ns=100_000_000,
                deadline_ms=800, clock_id='bid-boot')
            self.assertEqual(wrong['reason'], 'PRECONDITION_NOT_BID_PANEL')
            self.assertFalse(path.exists())

    def _run(self, *, configured_cap, current_funds, next_frame):
        parent = ROOT / 'build' / 'goal-20261019-c'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            path = Path(temp) / 'obligations.json'
            args = dict(configured_cap=configured_cap, current_funds=current_funds,
                        user_confirmed=True, approval_id='main-window-confirm',
                        pre_frame=self.panel, next_frame=next_frame, native_scope=native_scope(),
                        now_ms=100, now_ns=100_000_000, deadline_ms=800, clock_id='bid-boot')
            result = confirm_send_and_receive(path, event(), current(), **args)
            second = confirm_send_and_receive(path, event(), current(), **args)
            book = DurableBidIntentBook(path, ledger_id='bid-boot', budget={
                'approved': True, 'approvalId': 'main-window-confirm',
                'binding': {'matchId': 'm-video', 'matchGeneration': 1, 'observationSessionId': 's-video'},
                'expiresAtMs': 800, 'remaining': current_funds, 'maxBid': result.get('amount') or 1},
                clock_id='bid-boot')
            stored = book.recover()['state']['entries']
            state = next(iter(stored.values()))['storedState'] if stored else None
            return result, second, state


if __name__ == '__main__':
    unittest.main()
