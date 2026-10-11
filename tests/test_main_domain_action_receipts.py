"""Main routes bid and session receipts to their distinct consumers."""
import copy
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

import main as app_main
from domain_action_session import DomainActionSession
from session_fsm import AuctionSessionFSM, SessionState
from vision_contract import VisionObservation, VisionSettlement


class MainDomainActionReceiptTests(unittest.TestCase):
    def _session(self, *, archived=False):
        fsm = AuctionSessionFSM()
        fsm.trigger_match_start()
        fsm.handle_observation(VisionObservation(round=1))
        session = DomainActionSession(
            fsm, "match-1", match_generation=1, observation_session_id="obs-1",
        )
        if archived:
            self.assertTrue(session.observe(
                VisionObservation(round=5, settlement=VisionSettlement(isSettlement=True)),
                match_id="match-1", qualified=True, source_sequence=10,
            ))
            self.assertTrue(session.archive_completed(match_id="match-1", write_success=True))
        return session

    def _route(self, receipt, *, session):
        latest = {}
        current_match = SimpleNamespace(id="match-1", _seq=1)

        def summary():
            return {
                "bidActionReceipt": copy.deepcopy(latest.get("bidActionReceipt")),
                "domainActionReceipt": copy.deepcopy(latest.get("domainActionReceipt")),
                "domainActionReceiptAccepted": latest.get("domainActionReceiptAccepted"),
                "domainActionSessionPhase": session.phase,
            }

        event = {
            "type": "domain.action.receipt",
            "observationSessionId": "obs-1",
            "receiptChannel": "bid" if receipt["kind"] == "Bid" else "session",
            "receipt": receipt,
        }
        with mock.patch.multiple(
            app_main,
            CURRENT_MATCH=current_match,
            LATEST_PAYLOAD=latest,
            _NATIVE_EXPECTED_SESSION="obs-1",
            _NATIVE_OBSERVATION_SESSION="obs-1",
            _NATIVE_DOMAIN_ACTION_SESSION=session,
            _NATIVE_DURABLE_BID_OBLIGATION_OWNER=SimpleNamespace(
                receipt_is_committed=lambda _receipt: True),
            WS_EVENT_LOOP=None,
        ), mock.patch.object(app_main, "get_current_match_presentation_summary", side_effect=summary), \
             mock.patch.object(app_main, "_native_post_main_status"):
            result = app_main._native_observation_event(event)
            return result, copy.deepcopy(latest)

    def test_return_lobby_receipt_advances_session_and_never_becomes_bid_receipt(self):
        session = self._session(archived=True)
        pending = {
            "intentId": "return-1", "kind": "ReturnLobby",
            "status": "SENT_PENDING_CONFIRMATION", "matchId": "match-1",
            "matchGeneration": 1, "observationSessionId": "obs-1",
        }
        first, state = self._route(pending, session=session)
        self.assertTrue(state["domainActionReceiptAccepted"])
        self.assertEqual(session.pending_intent, "return-1")
        self.assertIsNone(state.get("bidActionReceipt"))
        self.assertEqual(first["currentMatch"]["domainActionReceipt"]["kind"], "ReturnLobby")

        confirmed = {**pending, "status": "CONFIRMED", "evidenceSequence": 11}
        _, state = self._route(confirmed, session=session)
        self.assertTrue(state["domainActionReceiptAccepted"])
        self.assertEqual(session.phase, "LOBBY")
        self.assertEqual(session.fsm.state, SessionState.PREPARING)
        self.assertIsNone(state.get("bidActionReceipt"))

    def test_bid_receipt_stays_on_bid_channel_without_touching_session_fsm(self):
        session = self._session()
        receipt = {
            "intentId": "bid-1", "kind": "Bid", "status": "CONFIRMED",
            "matchId": "match-1", "matchGeneration": 1,
            "observationSessionId": "obs-1", "approvalId": "approval-1",
        }
        result, state = self._route(receipt, session=session)
        self.assertEqual(state["bidActionReceipt"]["intentId"], "bid-1")
        self.assertIsNone(state.get("domainActionReceipt"))
        self.assertEqual(result["receiptChannel"], "bid")
        self.assertEqual(session.phase, "AUCTION")
        self.assertIsNone(session.pending_intent)

    def test_unacknowledged_bid_receipt_is_not_main_visible(self):
        session = self._session()
        receipt = {
            "intentId": "bid-1", "kind": "Bid", "status": "CONFIRMED",
            "matchId": "match-1", "matchGeneration": 1,
            "observationSessionId": "obs-1", "approvalId": "approval-1",
        }
        latest = {}
        with mock.patch.multiple(
            app_main,
            CURRENT_MATCH=SimpleNamespace(id="match-1", _seq=1),
            LATEST_PAYLOAD=latest,
            _NATIVE_EXPECTED_SESSION="obs-1",
            _NATIVE_OBSERVATION_SESSION="obs-1",
            _NATIVE_DOMAIN_ACTION_SESSION=session,
            _NATIVE_DURABLE_BID_OBLIGATION_OWNER=SimpleNamespace(
                receipt_is_committed=lambda _receipt: False),
            WS_EVENT_LOOP=None,
        ), mock.patch.object(app_main, "_native_post_main_status"):
            self.assertIsNone(app_main._native_observation_event({
                "type": "domain.action.receipt", "observationSessionId": "obs-1",
                "receiptChannel": "bid", "receipt": receipt,
            }))
        self.assertNotIn("bidActionReceipt", latest)

    def test_starting_host_binds_boot_id_and_discards_previous_obligation_owner(self):
        prior_owner = object()
        starting = {
            "type": "native_observation",
            "schemaVersion": "native-observation-v1",
            "status": "STARTING",
            "observationSessionId": "obs-1",
            "sourceKind": "native_wgc",
            "details": {"domainActionBootId": "boot-current"},
            "inputActions": False,
            "formalHistoryWriter": False,
        }
        with mock.patch.multiple(
            app_main,
            _NATIVE_EXPECTED_SESSION=None,
            _NATIVE_OBSERVATION_SESSION="obs-1",
            _NATIVE_DOMAIN_ACTION_BOOT_ID="boot-previous",
            _NATIVE_DURABLE_BID_OBLIGATION_OWNER=prior_owner,
        ), mock.patch.object(app_main, "_native_confirm_window_mode", return_value=True), \
             mock.patch.object(app_main, "_native_publish_health"):
            app_main._native_observation_event(starting)
            self.assertEqual(app_main._NATIVE_DOMAIN_ACTION_BOOT_ID, "boot-current")
            self.assertIsNone(app_main._NATIVE_DURABLE_BID_OBLIGATION_OWNER)


if __name__ == "__main__":
    unittest.main()
