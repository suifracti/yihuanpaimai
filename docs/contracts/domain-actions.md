# Sol-C / Issue #44 domain actions (offline integration contract)

## Current rule — 2026-10-20, PR #55

The user's “保持简单” instruction supersedes older freshness/proof requirements below. Input safety is target-window identity, a one-shot ticket, and no resend after UNKNOWN. Amount limits and reading the intended amount remain business behavior.

After a completed click, capture a new target-window image, decode that frame once and cache the result. Recognizing the expected result yields CONFIRMED; otherwise, after three seconds, UNKNOWN latches and prevents resend. Presentation-marker age/future status, anchor age, first-frame proofs and a 500ms image expiry are not action gates. Successful image capture does not create Solver facts or a warehouse SOURCE.

Current implementation work is limited to one real confirmed bid. Entry-fee automation, continuous looping and M5 remain deferred.

PR #56 adds pre-match instrument replenishment. A left click consumes one ticket, sends move/down, holds 60ms, then releases once. Raw API counts are two calls per click; the release is cleanup, including after partial/throwing press, never another press or retry. This is input pulse duration, not a wait for a scene or a freshness condition.

Base: PR #22 `25fd1d0073ce24e3c2f92f95cdeb8a706d4f9630`. Consumer: Luna-B; Solver producer: Sol-B PR #47 `3cf468143c189144ee0950b736d116e283efec61`.

## Available code

`NteHost.DomainActions` is a standalone net8 library. `DomainActionCoordinator(readScope, clock, port=null)` owns preflight, one attempted action per match/round/kind, duplicate-ID receipts, one pending confirmation, and a latched UNKNOWN stop. It invokes no OS APIs. A missing port returns `NOT_SENT / EXECUTION_OFF_NO_TICKET_PORT`.

`RestrictedDomainInputPort(ticketedBackend, clock)` implements the closed transaction:

- Bid: focus amount field → replace bounded integer digits → freshly captured exact amount-field readback → submit bid.
- ReturnLobby: only after qualified settlement and successful archive.
- StartNextMatch: only in confirmed lobby after archive and explicit new-match admission.

No coordinates, arbitrary keys/text/macros or retry count are supplied by the caller. `ITicketedDomainBackend` is the only adapter boundary. Every primitive must reuse Native target identity/focus checks and a one-shot ticket, and check the supplied `current()` at the final ticket commit, including cursor preparation. Its outcome must disclose any attempted side effect, even a partial/throwing call. The checked amount-field readback is not game acceptance.

The continuation adds `WindowsTicketedDomainBackend` below. Legacy public input actions still support only wheel/move; internal amount/left-click capabilities are OFF by default and accessible solely to this domain assembly. Main wiring and game-specific visible-control calibration remain NOT_CONNECTED; integrating with `port=null` is safe. No unguarded SendInput/SendMessage or approval inferred from READY/HUD fields is permitted.

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

Call `Poll()` on deadline/timer/disconnect/takeover changes. UNKNOWN is terminal for this coordinator and cannot be reset by an ID change. The in-memory receipt limit is 512; exhaustion refuses new work rather than evicting obligations. Real dispatch must additionally persist Sol-B reservation/claim and Native attempted/pending/UNKNOWN obligations **before input**, restore them across process restart and reconcile conservatively; constructing empty books/coordinators after a crash is not recovery. Native never creates another budget store; the continuation below consumes Sol-B's sole durable owner. Real execution stays OFF until the owner/IPC/admission path is installed and tested. No personal history writer is used as this ledger.

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

## Native production adapter continuation

`WindowsTicketedDomainBackend(guard,controlEvidence,obligationPort,clock,inputTargetId,allowGameInput=false)` implements the five primitives through the existing ticket executor and `Win32RawInputBackend`. **inputTargetId is the opaque existing `AWindowFocusAdapter`/guard identity token, not HWND**; pass the same token used to arm that guard. HWND/PID/process instance are independently revalidated against the OS. Domain guards require `EnableRestrictedDomainActions=true` from explicit execution admission; all legacy guards remain OFF. The existing 16-exemption/250ms intent/500ms ticket limits are unchanged. Every domain ticket re-reads focus and expiry after its potentially blocking source/control check, at final consume.

Amount replacement is a closed left-Control+A then 1..7 decimal digits, with key-up records; no arbitrary keys/text or Enter. Click is a marked absolute move and left down/up in the same existing ticketed raw batch. Exact marker, injected origin, non-lower-integrity origin, exact key/left-button/pixel intent, one-shot consumption/expiry/budget are conjunctive; physical input, unknown keys, other buttons and wrong codes still cancel. Keyboard native struct conversion uses KEYBDINPUT, rather than misinterpreting it as mouse input. Typed amount appears only in the authorized domain action/receipt, not a general key history.

The adapter requires a unique qualified visible anchor for the exact primitive and current immutable match/generation/session/round/revision/window/geometry, fresh non-future source and evidence hash. It checks anchor and geometry again at final commit and refuses drift. Submit also independently re-captures the exact amount field at its final ticket check. Sending digits does not imply rendered text: at most five new field observations within 250ms/original deadline may await the UI, with 40ms observation intervals; there is no retry of input. The test demonstrates the initial intermediate field `1/123` is rejected until exact `12345`; mismatch remains UNKNOWN/no Submit. `LastReadbackReason` distinguishes source/current/deadline/amount failure. Foreground only; no background universal-input claim, focus acquisition, arbitrary target positioning or game discovery. The production adapter does not restore cursor/focus behind takeover; instantiate the domain guard with clean cursor restoration disabled because its move is in the ticketed raw batch, not legacy cursor prepare. A partial batch may leave a modifier down; it is UNKNOWN, needs operator reconciliation, and is never automatically repaired by further unguarded input.

`NTE_DOMAIN_DUMMY_V1` anchors can target only `NteDomainDummyTarget` owned by this process. Game anchors require a separate `allowGameInput=true` operator gate plus verified `HTGame.exe/UnrealWindow` identity and `NTE_VERIFIED_GAME_V1`. `SceneAnchorGameDecoder` is that game detector: it NCC-matches the published templates in `assets/scene_anchors/domain_controls.json` and returns null when the directory or a unique match is missing. The live host uses it only when both `NTE_DOMAIN_ALLOW_GAME_INPUT=1` and `NTE_SCENE_ANCHOR_DIR` are set; otherwise `UnconnectedGameDomainDecoder` still produces NOT_CONNECTED/NOT_SENT. The search boxes are not click coordinates. The ticketed backend clicks the center of the matched template. Dummy rectangles cannot be a game fallback. Physical DPI/client mapping must agree with the independent capture and live client rect/origin; unknown mapping is refused. A bid whose readback or send result is unknown is not resent.

## WGC and receipt production boundary for Luna-B

`WgcLiveHarness.csproj` now references the compiled domain library. The new `WgcDomainCaptureAdapter.FromIndependentCapture` consumes the actual `CapturedBgraFrame` returned by `capture.CaptureAfterRequest` at `NativeObservationService`'s existing capture boundary. Pass the independent request/comparison clocks, immutable capture-owner binding and current capture scope epoch/mapping; do not derive capture-owner from the requested intent. Owner/window/epoch/client geometry/source qualification must match. Require strict source progress after request, source <= comparison, valid local age and consistent origin on delivery proofs; `FUTURE_AT_READ` is rejected rather than promoted. No capture/observation loop is rewritten or enabled here; Luna-B owns invoking this adapter and transport.

`CapturedDomainControlEvidence` joins independent capture to a configured `IGameDomainFrameDecoder` for exactly that pixel/hash/sequence. `NativeVisibleResultProducer` derives acceptance only from the independently decoded own seat/player identity, accepted amount (not typed field), correct match/round and evidence hash. Cached seats/myBid from `vision_pipeline` / Engine context are insufficient: current Engine can retain `isMe`/seat values; it does not attest accepted-own-bid on this independent frame. With the operator gate unset, the live host still uses no game decoder and a bid receipt stays NOT_SENT / GAME_DECODER_NOT_CONNECTED. When both environment variables above are set, `NativeObservationService` constructs `TicketedSceneAnchorDispatch` and calls `FromIndependentCapture` on a fresh `CaptureAfterRequest` for send and for visible confirmation. That path is the only one that can emit domain input. A frame that cannot confirm the pending action is not polled, so an unrelated picture does not latch UNKNOWN. An already-sent bid can be confirmed from AUCTION or AUCTION_R1 when the committed amount matches. Next-match proof requires the independently decoded new R1 and advancing match generation, never FSM config alone. The default envelope keeps `inputActions` false.

`NativeDomainActionRuntime.Dispatch/OnIndependentCapture/Poll` emits actual JSON `type=domain.action.receipt` with `currentMatch.bidActionReceipt`, including `approvalId`, `evidenceRef`, `stopAvailable`, `takeoverAvailable` and the original intent binding. Coordinator comparisons now take the clock AFTER reading the current view; otherwise a newly completed legitimate capture was falsely rejected as future. The adversarial future-frame assertions remain. Publish receipt only after durable receipt ACK; failed pending/effective commit latches UNKNOWN, never resends. Luna-B must correlate the original dispatched revision/approval while preserving its existing UI scope validation; no receipt transport/Main edits are included in this PR.

## Sole durable owner handshake

Sol-B PR #47 continuation `84e1f98d32b8261cacc5c4c732ce0543e3e26189` is the sole budget book. Native has `IExecutionObligationPort`/`DelegatedExecutionObligationPort`, not a second financial file. Prepare a Native intent from the book's durable CLAIMED envelope (`executionEnabled=false, commitBeforeSendRequired=true`). The prepared intent itself never authorizes sending. Immediately before the first primitive the Native callback must call `commit_domain_attempt(book,intent,current,native_scope,now_ms,now_ns)`: it invokes the owner's `attempted()` exactly once, verifies returned immutable amount/approval/binding/deadline, and only ACKs a durably committed ATTEMPTED permit. No earlier attempted call followed by another attempted call at the backend. Duplicate/restarted claims reject. Clock samples/epochs must be stably paired; uncertainty rejects/freeze rather than extending the earlier deadline.

For each Native receipt, `commit_domain_receipt(book,wire,independently_qualified,now_ms)` forwards the exact owner's schema including approvalId/evidenceRef. CONFIRMED only maps to EFFECTIVE with independent source provenance; pending never does. Exceptions/no ACK mean zero input before the first primitive or UNKNOWN after any attempted input. Failed post-attempt NOT_SENT reconciliation may conservatively leave the owner's UNKNOWN reservation frozen; the budget provider must surface that stop, never replace the book. Non-bid return/start require their own explicit current admission/obligation acknowledgement; a bid ledger receipt cannot be repurposed to authorize them.

Verification additions (Windows only for the dummy target; no HTGame):

```powershell
$artifacts=(Join-Path (Get-Location) 'build/dotnet')
dotnet run --project tests/native_domain_actions/domain-actions.csproj -p:UseArtifactsOutput=true -p:ArtifactsPath=$artifacts -- --dummy-window
dotnet run --project architecture/v2/input/verifier/NteInputGuardVerifier.csproj -p:UseArtifactsOutput=true -p:ArtifactsPath=$artifacts -- --output build/domain-input-neighbor
dotnet build architecture/v2/host/wgc_live_harness/WgcLiveHarness.csproj -p:UseArtifactsOutput=true -p:ArtifactsPath=$artifacts
# Use the integrated owner source, or point --owner-root to the approved Sol-B continuation worktree.
python tests/native_domain_actions/check_durable_owner.py --owner-root <owner-checkout>
```

The dummy test uses actual Win32 hooks/SendInput, editable field/button and independent GDI pixel capture with a test-only decoder. It refuses unknown controls, OFF/missing durable ACK, drift, bad identity/focus epoch, other foreground window, takeover and shutdown; exercises real field mismatch/final drift without Submit, simulated partial sends (avoiding partial modifier injection), receipt durability failure, and duplicate no-send. This proves OS adapter behavior for that controlled target, **not HTGame compatibility**. Real capture/control mapping, owned-seat acceptance, Main/IPC wiring, explicit real budget/input admission and operator reconciliation of partial/unknown obligations remain prerequisites. No real game input, quote, next match or main merge occurred.
