# Sol-C / Issue #44 domain actions (offline integration contract)

Base: PR #22 `25fd1d0073ce24e3c2f92f95cdeb8a706d4f9630`. Consumer: Luna-B; Solver producer: Sol-B PR #47 `3cf468143c189144ee0950b736d116e283efec61`.

## Available code

`NteHost.DomainActions` is a standalone net8 library. `DomainActionCoordinator(readScope, clock, port=null)` owns preflight, one attempted action per match/round/kind, duplicate-ID receipts, one pending confirmation, and a latched UNKNOWN stop. It invokes no OS APIs. A missing port returns `NOT_SENT / EXECUTION_OFF_NO_TICKET_PORT`.

`RestrictedDomainInputPort(ticketedBackend, clock)` implements the closed transaction:

- Bid: focus amount field → replace bounded integer digits → freshly captured exact amount-field readback → submit bid.
- ReturnLobby: only after qualified settlement and successful archive.
- StartNextMatch: only in confirmed lobby after archive and explicit new-match admission.

No coordinates, arbitrary keys/text/macros or retry count are supplied by the caller. `ITicketedDomainBackend` is the only adapter boundary. Every primitive must reuse Native target identity/focus checks and a one-shot ticket, and check the supplied `current()` at the final ticket commit, including cursor preparation. Its outcome must disclose any attempted side effect, even a partial/throwing call. The checked amount-field readback is not game acceptance.

The existing `InputSafetyGuard`/`SafeSendInputExecutor` only support wheel/move. This change **does not add or enable a Win32 amount/click backend** or exempt key/button takeover events. The backend supplied by the tests is fake only. Main wiring, production ticket support and visible-control mapping are still NOT_RUN; integrating this library with `port=null` is safe. Do not substitute unguarded SendInput/SendMessage or infer input authorization from READY/HUD fields.

## Sol-B claim and wire fields

Main first verifies an adapter is available and explicit execution admission exists; otherwise display only and do not claim. Sol-B `BidIntentBook.reserve` / `claim` already issue a once-only obligation. `claimed_bid_to_domain_intent(claim,native_scope,now_ms=...,now_ns=...)` consumes that returned mapping without reserving, claiming or granting approval again. Native scope is independently built from qualified current state. It must include:

`matchId`, `matchGeneration`, `observationSessionId`, `round`, `factsRevision`, `budget` (approved remaining before this claim's deduction), `leaseExpiresNs`, `leaseId`, `takeoverGeneration`, `window={hwnd,pid,processInstanceToken,focusEpoch}`.

The converted intent retains the complete binding, exact requested amount and maxSafeBid. The caller pairs monotonic clock samples; the remaining millisecond deadline is converted to Native nanoseconds and cannot exceed the existing lease. Native independently checks the amount against maxSafeBid, approved amount limit and remaining budget, source qualification/current age, scene, target identity, current revision and takeover generation. `SourceQualified` is the existing source-gate verdict, never a caller's reinterpretation of FUTURE/PARTIAL evidence. Default max age is 500 ms; an existing tighter gate remains authoritative.

C# wire serialization uses camelCase properties and `JsonStringEnumConverter`; do not serialize enum ordinals. DomainIntent fields are the converted mapping above; `kind` is `Bid`, `ReturnLobby` or `StartNextMatch`. `ActionScope` additionally supplies independent approved amount limit, exact scene (`AUCTION`, `SETTLEMENT`, `LOBBY`), source sequence/capture time, sourceQualified, connected, foregroundMatches, executionAuthorized, settlementArchived and newMatchAdmission. A view has both Native window/process/focus binding and observation session/match generation. `factsRevision=0` is valid; negative values are rejected.

## Receipt contract

| Status | Meaning | Sol-B book outcome |
|---|---|---|
| NOT_SENT | No side effect attempted; a new plan may be considered under its own policy | NOT_SENT; Sol-B deliberately burns this round claim |
| SENT_PENDING_CONFIRMATION | Some input completed; acceptance unproven | Keep CLAIMED/reservation; no resend |
| CONFIRMED | New, qualified, attributed visible result | EFFECTIVE for Bid only |
| UNKNOWN | Partial send, exception, deadline, discontinuity or conflicting receipt | UNKNOWN; retain reservation and stop |

Never map pending or amount-field readback to EFFECTIVE. `VisibleResult` binds intent ID/kind and original match/generation/round/factsRevision, observationSessionId, target/focus identity and takeover generation. Its sequence/time must be later than the send boundary and original frame, fresh, non-future, and within the current qualified stream. Bid requires the **accepted own bid** amount, not another bidder's amount or a field displaying typed digits. Return requires visible LOBBY. Start requires AUCTION_R1 plus a different nonempty newMatchId and strictly advancing newMatchGeneration. LOADING/config preparation alone cannot confirm a new match.

Call `Poll()` on deadline/timer/disconnect/takeover changes. UNKNOWN is terminal for this coordinator and cannot be reset by an ID change. The in-memory receipt limit is 512; exhaustion refuses new work rather than evicting obligations. Real dispatch must additionally persist Sol-B reservation/claim and Native attempted/pending/UNKNOWN obligations **before input**, restore them across process restart and reconcile conservatively; constructing empty books/coordinators after a crash is not recovery. Durable execution obligation storage is absent from this increment; real execution stays OFF until supplied and tested. No personal history writer is used as this ledger.

## Session integration

`DomainActionSession(existing_fsm,match_id,match_generation=...,observation_session_id=...)` wraps the existing `AuctionSessionFSM`; it does not change its legacy behavior. Only qualified, strictly advancing observations for the active match enter `observe`. Successful actual archive acknowledgement enters `archive_completed`; failed writes remain SETTLEMENT. Return pending does not reset the FSM; confirmed ReturnLobby feeds a zero-round lobby observation to the archived FSM. Do not feed retained auction frames to its permissive ARCHIVED reset branch.

`prepare_next(NextMatchAdmission(...),now_ns=...)` requires that confirmed lobby, explicit admission bound to previous match/generation/observation session, positive approved budget, current lease/takeover generation and deadline. It stores configuration only. A pending Start receipt keeps PREPARING and the old session ID. Only the corresponding confirmed Native new-match receipt creates the next FSM session and admits R1. Call `continuity(...)` on current connection/target/budget/lease/takeover/time changes. UNKNOWN or a conflicting same-ID NOT_SENT after a pending send stops; there is no automatic resend/reset. Admission does not itself authorize real UI execution.

## Minimal offline verification

Run from the isolated branch/worktree:

```powershell
dotnet run --project tests/native_domain_actions/domain-actions.csproj -- build/native-domain-actions/workflow.json
$env:TEMP=(Resolve-Path build).Path; $env:TMP=$env:TEMP
& D:/yihuanpaimai/build/takeover_20260905/repro-venv/Scripts/python.exe tools/run_tests.py test_domain_action_session test_session_fsm --output build/domain-session-tests.json
```

The C# harness uses fake primitives only and exports actual coordinator receipts. Python consumes those exact wire receipts for a completed first match → archive → confirmed lobby → next preparation → pending start → confirmed second R1; missing native output fails instead of synthesizing evidence. Neighbor legacy FSM tests are included. Outputs/intermediates stay under `build/`. No game/window/input/real budget/main merge is part of this verification.

Before any real execution: explicit user input/budget authorization; production adapter/control mapping with unchanged existing gates and final ticket checks; accepted-own-bid/new-match evidence attribution; durable obligations and restart UNKNOWN reconciliation; Luna-B Main/WS wiring; isolated-window ticket/takeover verification. These are unresolved conditions, not claims of full automatic bidding readiness.
