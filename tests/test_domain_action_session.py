import json
from pathlib import Path
import unittest

from domain_action_session import DomainActionSession, NextMatchAdmission, claimed_bid_to_domain_intent
from session_fsm import AuctionSessionFSM, SessionState
from vision_contract import VisionObservation, VisionSettlement


class DomainActionSessionTests(unittest.TestCase):
    def setUp(self):
        self.fsm = AuctionSessionFSM()
        self.fsm.trigger_match_start()
        self.fsm.handle_observation(VisionObservation(round=1))
        self.session = DomainActionSession(self.fsm, "match-1", match_generation=1, observation_session_id="obs-1")

    def settle(self):
        self.assertTrue(self.session.observe(VisionObservation(round=5,
            settlement=VisionSettlement(isSettlement=True, clearingPrice=500)),
            match_id="match-1", qualified=True, source_sequence=11))

    def receipt(self, kind, status, sequence=12, **extra):
        return dict(intentId=kind, kind=kind, status=status, matchId="match-1",
                    matchGeneration=1, observationSessionId="obs-1", evidenceSequence=sequence,
                    newMatchGeneration=2, **extra)

    def lobby(self):
        self.settle()
        self.assertTrue(self.session.archive_completed(match_id="match-1", write_success=True))
        self.assertTrue(self.session.accept_receipt(self.receipt("ReturnLobby", "SENT_PENDING_CONFIRMATION"), now_ns=100))
        self.assertTrue(self.session.accept_receipt(self.receipt("ReturnLobby", "CONFIRMED"), now_ns=101))

    def admission(self, **extra):
        args = dict(admission_id="admission-1", previous_match_id="match-1", budget=1000,
                    deadline_ns=1000, lease_id="lease-1", takeover_generation=2,
                    previous_match_generation=1, observation_session_id="obs-1",
                    explicitly_authorized=True)
        args.update(extra)
        return NextMatchAdmission(**args)

    def test_archive_failure_and_unqualified_settlement_do_not_allow_return(self):
        obs = VisionObservation(settlement=VisionSettlement(isSettlement=True))
        self.assertFalse(self.session.observe(obs, match_id="foreign", qualified=True, source_sequence=10))
        self.assertFalse(self.session.observe(obs, match_id="match-1", qualified=False, source_sequence=10))
        self.settle()
        self.assertFalse(self.session.archive_completed(match_id="match-1", write_success=False))
        self.assertFalse(self.session.accept_receipt(self.receipt("ReturnLobby", "CONFIRMED"), now_ns=100))
        self.assertEqual(self.fsm.state, SessionState.SETTLEMENT)

    def test_preparation_and_os_acceptance_never_create_new_session(self):
        self.lobby()
        old_session = self.fsm.session_id
        self.assertTrue(self.session.prepare_next(self.admission(), now_ns=200))
        self.assertEqual(self.fsm.session_id, old_session)
        self.assertEqual(self.fsm.state, SessionState.PREPARING)
        self.assertTrue(self.session.accept_receipt(self.receipt("StartNextMatch", "SENT_PENDING_CONFIRMATION"), now_ns=201))
        self.assertEqual(self.fsm.state, SessionState.PREPARING)
        self.assertEqual(self.fsm.session_id, old_session)
        for evidence in [self.receipt("StartNextMatch", "CONFIRMED", newMatchId="match-1"),
                         self.receipt("StartNextMatch", "CONFIRMED", sequence=12, newMatchId="match-2")]:
            self.assertFalse(self.session.accept_receipt(evidence, now_ns=202))
        self.assertTrue(self.session.accept_receipt(self.receipt("StartNextMatch", "CONFIRMED", sequence=13,
            newMatchId="match-2"), now_ns=203))
        self.assertEqual(self.session.match_id, "match-2")
        self.assertEqual(self.fsm.state, SessionState.AUCTION_R1)
        self.assertNotEqual(self.fsm.session_id, old_session)

    def test_admission_unknown_budget_or_missing_permission_rejected(self):
        self.assertFalse(self.session.prepare_next(self.admission(), now_ns=100))
        self.lobby()
        for admission in [self.admission(budget=0), self.admission(budget=True),
                          self.admission(explicitly_authorized=False), self.admission(deadline_ns=199),
                          self.admission(previous_match_id="foreign"), self.admission(previous_match_generation=2),
                          self.admission(observation_session_id="foreign")]:
            self.assertFalse(self.session.prepare_next(admission, now_ns=200))
        self.assertEqual(self.session.phase, "LOBBY")

    def test_unknown_and_continuity_failure_stop_without_resetting_fsm(self):
        for mode in ("receipt", "target", "disconnect", "budget", "lease", "takeover", "timeout"):
            with self.subTest(mode=mode):
                self.setUp()
                self.lobby()
                self.session.prepare_next(self.admission(), now_ns=200)
                if mode == "receipt":
                    self.session.accept_receipt(self.receipt("StartNextMatch", "UNKNOWN"), now_ns=201)
                else:
                    self.assertFalse(self.session.continuity(connected=mode != "disconnect",
                        target_matches=mode != "target", budget_known=mode != "budget",
                        lease_id="foreign" if mode == "lease" else "lease-1",
                        takeover_generation=3 if mode == "takeover" else 2,
                        now_ns=1000 if mode == "timeout" else 201))
                self.assertEqual(self.session.phase, "STOPPED")
                self.assertEqual(self.fsm.state, SessionState.PREPARING)
                self.assertFalse(self.session.prepare_next(self.admission(), now_ns=300))

    def test_unrelated_not_sent_cannot_cancel_pending_receipt(self):
        self.lobby()
        self.session.prepare_next(self.admission(), now_ns=200)
        self.session.accept_receipt(self.receipt("StartNextMatch", "SENT_PENDING_CONFIRMATION"), now_ns=201)
        unrelated = self.receipt("StartNextMatch", "NOT_SENT")
        unrelated["intentId"] = "other-id"
        self.session.accept_receipt(unrelated, now_ns=202)
        self.assertEqual(self.session.pending_intent, "StartNextMatch")

    def test_conflicting_not_sent_for_pending_send_stops_instead_of_allowing_retry(self):
        self.lobby()
        self.session.prepare_next(self.admission(), now_ns=200)
        self.session.accept_receipt(self.receipt("StartNextMatch", "SENT_PENDING_CONFIRMATION"), now_ns=201)
        self.session.accept_receipt(self.receipt("StartNextMatch", "NOT_SENT"), now_ns=202)
        self.assertEqual(self.session.phase, "STOPPED")
        self.assertFalse(self.session.accept_receipt(self.receipt("StartNextMatch", "SENT_PENDING_CONFIRMATION"), now_ns=203))

    def test_sol_b_claim_conversion_preserves_scope_money_and_deadline(self):
        binding = dict(matchId="match-1", matchGeneration=1, observationSessionId="obs-1", round=1, factsRevision=7)
        claim = dict(ok=True, state="CLAIMED", executionEnabled=True, amount=500, approvalId="approved-1",
            budget=dict(approved=True, approvalId="approved-1", remaining=1000),
            intent=dict(schemaVersion="bid-intent.v1", status="READY", binding=binding,
                intentId="bid-1", requestedBid=500, maxSafeBid=800, deadlineMs=1500))
        native = dict(**binding, budget=1000, leaseExpiresNs=2_000_000_000,
            takeoverGeneration=2, leaseId="lease-1", window=dict(hwnd=10, pid=20, processInstanceToken=30, focusEpoch=40))
        intent = claimed_bid_to_domain_intent(claim, native, now_ms=1000, now_ns=1_000_000_000)
        self.assertEqual(intent["amount"], 500)
        self.assertEqual(intent["deadlineNs"], 1_500_000_000)
        self.assertEqual(intent["maxSafeBid"], 800)
        self.assertEqual(intent["approvalId"], "approved-1")
        self.assertEqual({key: intent[key] for key in binding}, binding)
        prepared = dict(claim, executionEnabled=False, commitBeforeSendRequired=True)
        self.assertEqual(claimed_bid_to_domain_intent(prepared, native, now_ms=1000, now_ns=1_000_000_000), intent)
        for bad_native in (dict(native, factsRevision=8), dict(native, observationSessionId="foreign"),
                           dict(native, matchGeneration=2), dict(native, budget=999),
                           dict(native, leaseExpiresNs=1_400_000_000)):
            with self.assertRaises(ValueError):
                claimed_bid_to_domain_intent(claim, bad_native, now_ms=1000, now_ns=1_000_000_000)
        for bad_claim in (dict(claim, executionEnabled=False), dict(claim, state="RESERVED"),
                          dict(claim, amount=801), dict(claim, approvalId="foreign")):
            with self.assertRaises(ValueError):
                claimed_bid_to_domain_intent(bad_claim, native, now_ms=1000, now_ns=1_000_000_000)

    def test_native_wire_receipts_one_match_to_next_match(self):
        # C# harness exports its actual production coordinator receipts. Required
        # precondition; absence is a failure, never a synthetic substitute/skip.
        path = Path(__file__).resolve().parents[1] / "build/native-domain-actions/workflow.json"
        workflow = json.loads(path.read_text(encoding="utf-8"))
        self.settle()
        self.assertTrue(self.session.archive_completed(match_id="match-1", write_success=True))
        for receipt in workflow[2:4]:
            self.assertTrue(self.session.accept_receipt(receipt, now_ns=1_100_000_000))
        old_id = self.fsm.session_id
        self.assertTrue(self.session.prepare_next(self.admission(deadline_ns=2_000_000_000), now_ns=1_100_000_001))
        self.assertTrue(self.session.accept_receipt(workflow[4], now_ns=1_100_000_002))
        self.assertEqual(self.fsm.session_id, old_id)
        self.assertTrue(self.session.accept_receipt(workflow[5], now_ns=1_100_000_003))
        self.assertEqual(self.session.match_id, "match-2")
        self.assertEqual(self.fsm.state, SessionState.AUCTION_R1)
