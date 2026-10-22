import json
from pathlib import Path
import tempfile
import unittest

from domain_action_session import (
    DomainActionSession, NextMatchAdmission, advance_live_domain_loop,
    claimed_bid_to_domain_intent, fresh_live_domain_state,
)
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
        self.assertEqual(self.session.match_id, "match-1")
        self.assertEqual(self.session.phase, 'ENTRY_FEE')
        self.assertEqual(self.fsm.session_id, old_id)


class AuthorizedLiveDomainLoopTests(unittest.TestCase):
    def view(self, *, funds, scene, round_no, directory, **extra):
        from test_bid_intent_contract import current, event
        scope = current()
        scope["round"] = round_no
        proposal = event()
        proposal.update(scope)
        proposal["predictionSnapshot"]["matchId"] = scope["matchId"]
        proposal["predictionSnapshot"]["round"] = round_no
        proposal["predictionSnapshot"]["input"]["normalizedFacts"]["round"] = round_no
        base = dict(
            publishedScene=scene, foreground=True, userConfirmed=True, currentFunds=funds,
            configuredCap=None, engine=dict(scope), proposalEvent=proposal, current=dict(scope),
            window=dict(hwnd=10, pid=20, processInstanceToken=30, focusEpoch=40),
            approvalId="goal-20261019-authorized", bootId="boot-live",
            leaseId="live-" + scope["matchId"], ledgerPath=str(Path(directory) / "bid-ledger.json"),
            nowMs=100, nowNs=1_000_000, deadlineMs=800, deadlineNs=701_000_000,
            roundRemainingMs=30000, roundDeadlineNs=30_001_000_000,
            bidReceipt=None, sessionReceipt=None,
        )
        base.update(extra)
        return base

    def test_short_round_is_skipped_without_a_ledger_and_next_round_can_bid(self):
        with tempfile.TemporaryDirectory() as directory:
            sent = []
            state = fresh_live_domain_state()
            view = self.view(funds=100000, scene='AUCTION', round_no=2, directory=directory,
                             roundRemainingMs=5900)
            advance_live_domain_loop(state, view, lambda *args: sent.append(args) or True)
            self.assertEqual(state['reason'], 'ROUND_TIME_TOO_SHORT')
            self.assertEqual(list(Path(directory).iterdir()), [])
            view['roundRemainingMs'] = 30000
            advance_live_domain_loop(state, view, lambda *args: sent.append(args) or True)
            self.assertEqual(sent, [])
            next_round = self.view(funds=100000, scene='AUCTION', round_no=3, directory=directory)
            advance_live_domain_loop(state, next_round, lambda *args: sent.append(args) or True)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][1]['intent']['roundDeadlineNs'], 30_001_000_000)

    def test_authorized_live_loop_sends_each_step_once(self):
        with tempfile.TemporaryDirectory() as directory:
            sent = []
            state = fresh_live_domain_state()
            refused = self.view(funds=None, scene="AUCTION", round_no=2, directory=directory, foreground=False)
            state = advance_live_domain_loop(state, refused, lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(sent, [])
            self.assertEqual(state["phase"], "idle")
            capped_dir = directory + "-cap"
            Path(capped_dir).mkdir()
            capped_sent = []
            advance_live_domain_loop(
                fresh_live_domain_state(),
                self.view(funds=100, scene="AUCTION", round_no=2, directory=capped_dir),
                lambda owner, envelope: capped_sent.append(envelope) or True)
            self.assertEqual(capped_sent[0]["intent"]["amount"], 100)
            self.assertEqual(capped_sent[0]["intent"]["window"]["focusEpoch"], 0)
            self.assertEqual(capped_sent[0]["intent"]["takeoverGeneration"], 0)

            state = advance_live_domain_loop(
                state, self.view(funds=100000, scene="AUCTION", round_no=2, directory=directory),
                lambda owner, envelope: sent.append((owner, envelope)) or True)
            self.assertEqual(state["phase"], "bid_dispatched")
            self.assertEqual(len(sent), 1)
            bid = sent[0][1]
            self.assertEqual(bid["type"], "domain.action.dispatch")
            self.assertEqual(bid["intent"]["kind"], "Bid")
            self.assertEqual(bid["intent"]["amount"], 58000)
            self.assertEqual(bid["intent"]["window"]["focusEpoch"], 0)
            self.assertEqual(bid["intent"]["takeoverGeneration"], 0)
            self.assertLessEqual(bid["intent"]["amount"], bid["intent"]["maxSafeBid"])
            self.assertFalse(state["resendAllowed"])
            pending = self.view(funds=100000, scene="AUCTION", round_no=2, directory=directory,
                                bidReceipt=dict(intentId=bid["intent"]["intentId"], kind="Bid",
                                                status="SENT_PENDING_CONFIRMATION"))
            state = advance_live_domain_loop(state, pending, lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(len(sent), 1)
            confirmed = self.view(funds=100000, scene="SETTLEMENT", round_no=2, directory=directory, collectionFinished=True,
                                  bidReceipt=dict(intentId=bid["intent"]["intentId"], kind="Bid", status="CONFIRMED"))
            state = advance_live_domain_loop(state, confirmed, lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(state["phase"], "return_dispatched")
            returned = sent[1]
            self.assertIsNone(returned["intent"]["amount"])
            self.assertEqual(returned["intent"]["kind"], "ReturnLobby")
            self.assertEqual(returned["intent"]["round"], 2)
            self.assertEqual(returned["intent"]["window"]["focusEpoch"], 0)
            lobby = self.view(funds=100000, scene="LOBBY", round_no=0, directory=directory,
                              sessionReceipt=dict(intentId=returned["intent"]["intentId"], kind="ReturnLobby",
                                                  status="CONFIRMED"))
            state = advance_live_domain_loop(state, lobby, lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(state["phase"], "start_dispatched")
            started = sent[2]
            self.assertEqual(started["intent"]["kind"], "StartNextMatch")
            self.assertEqual(started["intent"]["round"], 0)
            self.assertIsNone(started["intent"]["amount"])
            done = self.view(funds=100000, scene="AUCTION", round_no=1, directory=directory,
                             sessionReceipt=dict(intentId=started["intent"]["intentId"], kind="StartNextMatch",
                                                 status="CONFIRMED", newMatchId="match-2", newMatchGeneration=2))
            state = advance_live_domain_loop(state, done, lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(state["phase"], "bid_dispatched")
            self.assertEqual(len(sent), 4)
            self.assertFalse(state["resendAllowed"])

    def test_authorized_live_loop_unknown_or_not_sent_does_not_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            sent = []

            def send(owner, envelope):
                sent.append(envelope)
                return True

            state = advance_live_domain_loop(
                fresh_live_domain_state(),
                self.view(funds=100000, scene="AUCTION", round_no=2, directory=directory), send)
            bid_id = sent[0]["intent"]["intentId"]
            unknown = self.view(funds=100000, scene="SETTLEMENT", round_no=2, directory=directory,
                                bidReceipt=dict(intentId=bid_id, kind="Bid", status="UNKNOWN"))
            state = advance_live_domain_loop(state, unknown, send)
            self.assertEqual(state["phase"], "stopped")
            self.assertEqual(state["reason"], "UNKNOWN")
            self.assertFalse(state["resendAllowed"])
            again = advance_live_domain_loop(state, unknown, send)
            self.assertEqual(len(sent), 1)
            self.assertEqual(again["phase"], "stopped")

        with tempfile.TemporaryDirectory() as directory:
            sent = []
            state = advance_live_domain_loop(
                fresh_live_domain_state(),
                self.view(funds=100000, scene="AUCTION", round_no=2, directory=directory),
                lambda owner, envelope: sent.append(envelope) or True)
            blocked = self.view(funds=100000, scene="SETTLEMENT", round_no=2, directory=directory,
                                bidReceipt=dict(intentId=sent[0]["intent"]["intentId"], kind="Bid", status="NOT_SENT"))
            state = advance_live_domain_loop(state, blocked, lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(state["phase"], "collecting")
            self.assertEqual(state["reason"], "WAITING_WAREHOUSE_SAVE")
            self.assertEqual(len(sent), 1)
            self.assertFalse(state["resendAllowed"])

    def test_lobby_waits_for_the_settled_capture_then_starts_the_next_match(self):
        with tempfile.TemporaryDirectory() as directory:
            sent = []
            scope = self.view(funds=100000, scene='LOBBY', round_no=0, directory=directory)
            settled = scope['engine']['matchId']
            state = fresh_live_domain_state()
            state.update(phase='collecting', settledMatch=settled, mode='bid')
            state = advance_live_domain_loop(
                state, dict(scope, collectionFinished=False, captureRecordKey=None),
                lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(state['phase'], 'collecting')
            self.assertEqual(state['reason'], 'WAITING_WAREHOUSE_SAVE')
            self.assertEqual(sent, [])
            state = advance_live_domain_loop(
                state, dict(scope, collectionFinished=True, captureRecordKey=settled,
                            captureProgress=['COMPLETE', 20, 0], savedSources=20,
                            coverageStatus='COMPLETE'),
                lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(state['matchesDone'], 1)
            self.assertEqual(state['phase'], 'start_dispatched')
            self.assertEqual(len(sent), 1)

    def test_a_capture_stopped_on_this_record_closes_it_even_without_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            sent = []
            scope = self.view(funds=100000, scene='LOBBY', round_no=0, directory=directory)
            settled = scope['engine']['matchId']
            state = fresh_live_domain_state()
            state.update(phase='collecting', settledMatch=settled, mode='bid')
            # Stopped while another record was bound: this settlement still waits.
            waiting = dict(scope, collectionFinished=True, captureRecordKey=None,
                           captureStoppedRecord='draft_other', savedSources=0,
                           coverageStatus='PARTIAL')
            state = advance_live_domain_loop(state, waiting,
                                             lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(state['reason'], 'WAITING_WAREHOUSE_SAVE')
            self.assertEqual(sent, [])
            # Stopped on this record with nothing saved: close it and move on.
            stopped = dict(scope, collectionFinished=True, captureRecordKey=None,
                           captureStoppedRecord=settled, savedSources=0,
                           coverageStatus='PARTIAL')
            state = advance_live_domain_loop(state, stopped,
                                             lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(state['matchesDone'], 1)
            self.assertEqual(len(sent), 1)

    def test_published_bid_control_and_asset_integer_gate(self):
        import cv2
        import numpy as np
        from scene_anchors import one_asset_integer, published_domain_scene, read_asset_funds
        from visual_catalog import asset_root
        blank = np.zeros((1080, 1920, 3), np.uint8)
        self.assertIsNone(published_domain_scene(blank))
        self.assertIsNone(one_asset_integer(["我的资产", "推荐 300,000", "2,802,874"]))
        self.assertEqual(one_asset_integer(["我的资产 2,802,874"]), 2802874)
        self.assertIsNone(read_asset_funds(blank))
        template = cv2.imdecode(np.fromfile(
            asset_root() / "assets/scene_anchors/bid_confirm_label.png", np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(template)
        frame = blank.copy()
        y, x = 926, 1189
        frame[y:y + template.shape[0], x:x + template.shape[1]] = template
        self.assertEqual(published_domain_scene(frame), "AUCTION")

    def test_fee_confirm_pixel_accepts_the_live_pill_and_rejects_gray(self):
        from scene_anchors import fee_confirm_pixel
        self.assertTrue(fee_confirm_pixel(242, 81, 145))
        self.assertTrue(fee_confirm_pixel(234, 87, 142))
        self.assertFalse(fee_confirm_pixel(213, 213, 213))
        self.assertFalse(fee_confirm_pixel(180, 180, 180))
        self.assertFalse(fee_confirm_pixel(True, 81, 145))
