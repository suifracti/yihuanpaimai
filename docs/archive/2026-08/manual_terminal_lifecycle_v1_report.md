# Manual Terminal Lifecycle v1

Date: 2026-08-22 (Asia/Shanghai)

Initial HEAD: `2f66b532af22f9d088070045bd9ef1b3798c712c`

Final HEAD: `SELF` — the independent commit containing this report

Tracked status at start: clean

Pre-existing untracked files: preserved and excluded from this cut

## 1. 0.6 terminal flow reuse map

| 0.6 capability | 0.67 owner | Decision |
|---|---|---|
| `lab/index.html` “本局结束 · 结算并保存” | Manual Overlay terminal panel | Reuse the explicit end-of-match product intent and settlement terminology |
| settlement input: clearing price, actual total, acquisition/winner | Canonical v7 `settlement` and `bidding` namespaces | Reuse the business meaning; do not create parallel fields |
| persist first, reset only after success | `CanonicalHistoryStore.persist_record_transactional()` | Reuse the atomic transaction authority and re-read verification |
| failed save retains current game | `ManualTerminalCoordinator` + existing `CurrentMatch` | Reuse the failure behavior with stable UI reason codes |
| next-match reset after terminal success | existing CurrentMatch/holder reset path | Adapt to explicit finalized/keep-draft/discard intent |

No second lifecycle database, history store, Solver, WebView, or runtime was introduced.

## 2. Current Manual terminal flow

```text
Manual edits
  -> same CurrentMatch DRAFT
  -> debounced durable DRAFT save
  -> explicit terminal choice
       a) settlement input -> validate -> DRAFT to FINALIZED
       b) keep DRAFT -> persist/verify
       c) discard -> DRAFT to CANCELLED
       d) cancel -> no state change
  -> transaction success and re-read verification
  -> reset holders/form/presentation
  -> new UUID-backed matchId
```

The old silent `新一局 -> save DRAFT -> clear` behavior is removed. A next-match request without an explicit disposition returns `TERMINAL_INTENT_REQUIRED` and leaves the current match untouched.

## 3. Settlement fields reused

The minimal terminal form collects:

- `settlement.clearingPrice`
- `settlement.actualTotal`
- `settlement.acquired`
- `settlement.winner`

It derives the existing Canonical v7 `settlement.realizedProfit` from acquisition, clearing price, actual value, and existing `costs.total`. Existing `settlementItems` can be preserved when supplied. `bidding.leaderName`, `leaderBid`, `isMyLead`, and, when acquired, `myFinalBid` are projected from the same terminal facts.

Manual completion sets `settlement.status=verified` and `verified=true`, but does **not** invent `truthEvidence` or claim `INDEPENDENT_REVIEWED_SETTLEMENT`.

## 4. DRAFT transition behavior

- Edits continue to update one `CurrentMatch` and one persisted DRAFT by `matchId`.
- Debounce and shutdown flush still use the durable per-user history authority.
- Prediction snapshot, catalog provenance, exact venue/box selection, and catalog-derived entry cost are attached to the DRAFT projection.
- DRAFT updates cannot overwrite an already-FINALIZED record because `CanonicalHistoryStore` remains the transition authority.
- Match IDs now use `draft_<uuid4 hex>`; this removes the prior second-timestamp/process-sequence collision risk across fast restarts.

## 5. FINALIZED transition behavior

`ManualTerminalCoordinator.finalize()` deep-copies the current Canonical DRAFT, removes only forbidden legacy root projections, validates settlement input and prediction snapshot, validates the complete Canonical v7 FINALIZED record, persists transactionally, then re-reads and verifies the terminal record.

Only after that verification does `app/main.py` reset the active runtime state and create a new match. A persistence or verification failure leaves the active match and settlement inputs intact.

## 6. Exactly-once mechanism

- Manual mutations, draft timers, finalize, keep, and discard are serialized by a process-level re-entrant Manual state lock.
- Every terminal request carries `expectedMatchId`; a stale request cannot act on a newer match.
- `CanonicalHistoryStore` enforces one record per ID and permits an identical FINALIZED retry idempotently while rejecting a differing FINALIZED rewrite.
- A retry for an already finalized old ID returns stable `ALREADY_FINALIZED` instead of appending another record.
- Six concurrent finalize calls were verified to produce one `FINALIZED` and five `ALREADY_FINALIZED` results.

## 7. Incomplete-DRAFT next-match behavior

The terminal layer presents four explicit outcomes:

- finish and settle;
- retain as DRAFT and start another match;
- discard and start another match;
- cancel.

There is no implicit finalization and no default disposition.

## 8. Discard / keep-draft semantics

- Keep: the current Canonical DRAFT is persisted and re-read as `DRAFT`; only then is the runtime reset.
- Discard: the current record transitions to the existing legal `CANCELLED` lifecycle state, is persisted and verified; only then is the runtime reset.
- Cancel: no bridge mutation is sent and the current match is unchanged.
- Existing historical DRAFT records are not rewritten, deleted, or automatically finalized.

## 9. Reset and new-match behavior

Successful finalize/keep/discard clears the active snapshot holder, truth holder, settlement UI, local dirty state, stale engine presentation, and current Manual facts. It then creates a new `CurrentMatch` with a different UUID-backed ID.

Venue, box, field condition, bidding, known items, prediction presentation, and settlement facts do not leak from match A to match B. The existing Overlay HWND, WebView, and sole Solver runtime remain alive and unchanged.

## 10. Prediction and catalog provenance preservation

The terminal record is projected from the existing Canonical DRAFT rather than reconstructed from a reduced settlement object. It therefore preserves:

- validated `predictionSnapshot`, when present;
- `catalogVersion`, approval status, SHA-256, evidence cohort, and venue/box evidence classes;
- exact catalog venue/box identity and `boxId=null` unknown semantics;
- catalog-derived entry cost (`0`, `5000`, or `20000`).

The Upper-tail capture contract and truth-review gate were not modified.

## 11. Failure preservation behavior

Missing/inconsistent settlement fields, invalid Canonical records, invalid prediction snapshots, unavailable history, write failures, re-read failures, stale IDs, and illegal transitions all fail closed:

- current `matchId` remains unchanged;
- current facts and settlement inputs remain visible;
- the DRAFT is not silently promoted or deleted;
- no new match is created;
- only stable user-facing error codes/messages cross the bridge; no path, traceback, or raw exception leaks.

## 12. Restart behavior

- DRAFT close/restart: the old DRAFT remains in durable history, is not auto-presented as the active match, and a fresh active ID is created. No unsupported resume semantics were added.
- FINALIZED/reset close/restart: the prior record remains exactly once as FINALIZED; it is not restored as active and is not duplicated by retry.

## 13. Admission behavior

History Admission Policy v1 is unchanged. DRAFT and CANCELLED records remain excluded according to the existing policy. A valid FINALIZED Manual record is admitted only when it independently satisfies the existing policy; this cut did not weaken truth or evaluation eligibility gates.

## 14. Source smoke

Isolated `YIHUAN_DATA_ROOT` source smoke passed:

- entered Manual facts and observed one DRAFT;
- completed settlement and observed exactly one FINALIZED record;
- retry returned `ALREADY_FINALIZED`;
- next match received a distinct ID;
- Overlay HWND remained identical;
- clean exit succeeded;
- DRAFT restart scenario preserved the prior DRAFT without auto-resume.

## 15. Fresh package smoke

A fresh PyInstaller build passed the same real bridge/UI lifecycle under an isolated data root:

- A DRAFT -> FINALIZED -> B;
- A remained exactly once after restart;
- B had a new match ID;
- package history remained under the isolated durable data root;
- package directory remained byte/metadata unchanged by history writes;
- Overlay HWND stayed stable;
- clean exit and no lingering process passed.

## 16. Source/package parity

Source and package both produced one admitted FINALIZED record with identical lifecycle and terminal semantics. Package restart re-read one FINALIZED record. The smoke compared canonical status, record count, retry behavior, admission, new-ID behavior, and revision/hash integrity rather than expecting independently generated UUIDs or timestamps to be byte-identical.

## 17. Integrity hashes

All values are unchanged from the cut baseline:

| Authority | SHA-256 |
|---|---|
| repo research history `异环拍卖数据.json` | `6A9695F8EF44058F2C369AC1BD1407A6306A327B63D1C0A160631D5348ED699A` |
| `core/auction_engine_v06.js` | `8F31258F73B22CE978A61555AD6765E231305588F0B8239609CE8A8230F98862` |
| `core/solver_core_v06.js` | `1EC8DCA270A8219EB00133421723A114F3649B81CD07C769C765AC2C7AFED07F` |
| `core/shadow_profile_v06.js` | `9967F269F5C5B66DC8A010E3077CE014700C0B94333D93ACF25A4021F9C886A5` |
| approved Alpha catalog | `321A0BD7851D30AAFF40022621E4B4C0A1157A25873DE28E50DCDAAE7CBF01D3` |

No Solver formula, prior, candidate generation, Shadow algorithm, catalog truth, or repo history content changed.

## 18. Tests

- `41/41` focused Manual terminal, app-flow, debounce/input, Main lifecycle, and Canonical v7 tests passed.
- `2/2` direct v0.6 Solver reliability/integrity tests passed.
- Python compilation passed for the modified Python modules.
- Overlay inline JavaScript syntax check passed.
- Source smoke passed.
- Fresh package build and packaged smoke passed.

Covered gates include same-ID DRAFT update, DRAFT->FINALIZED, immutable FINALIZED, double/repeated/concurrent finalize, stale retry, keep/discard/cancel, incomplete settlement, validation/write failure preservation, prediction/catalog preservation, no truth-evidence fabrication, unique IDs across restarts, Overlay identity stability, source/package parity, restart persistence, and clean shutdown.

## 19. Pre-existing unrelated failures

The following were reproduced and left unchanged:

- `tests.test_golden_comparison.test_07_frozen_prediction_preservation`: legacy fixture expects root `prediction`, while current Canonical output uses `predictionSnapshot`.
- `tests.test_v06_final` legacy schema-6 persistence assertion expects old flat v0.65 fields.
- `tests.test_manual_alpha` legacy assertion expects `qualities.gold.knownItems` to be a string rather than the current Canonical list.

These are pre-existing legacy fixture debt and were not made green by changing current Canonical semantics.

## 20. Files in this cut

- new `app/manual_terminal.py`
- modified `app/main.py`
- modified `core/current_match.py`
- modified `core/overlay_alpha.html`
- modified `app/异环拍卖助手.spec`
- modified `tests/test_manual_input_perf.py`
- new `tests/test_manual_terminal_lifecycle_v1.py`
- new `tests/test_manual_terminal_app_flow_v1.py`
- new `tests/manual_terminal_smoke.py`
- this report

## 21. Final verdict

`MANUAL_TERMINAL_LOOP_READY`

The 0.67 Manual Alpha can now complete consecutive matches through an explicit, exactly-once, failure-preserving terminal lifecycle without moving Solver ownership or weakening history admission.
