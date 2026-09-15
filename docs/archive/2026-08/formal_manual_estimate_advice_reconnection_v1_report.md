# Formal Manual Estimate / Advice Reconnection v1

## Outcome

**Final verdict: `BLOCKED_BY_UNPROVEN_SOLVER_CONTEXT`**

This cut stopped at the frozen catalog/Solver authority boundary. No product runtime, Solver algorithm, catalog, Canonical history, or UI file was changed. Wiring the old aliases directly would make unverified compatibility assumptions affect user-visible estimates and bidding advice.

## 1. Initial / final repository state

- Initial HEAD: `452659269c4d1729880000f2c11ca6fd1d605251`
- Final HEAD: the independent report/test commit reported in the handoff; its parent is the initial HEAD above.
- Tracked status before this cut: clean.
- Pre-existing untracked files were preserved and excluded from the commit.

## 2. Short v0.6 reuse map

| v0.6 capability | Existing source/function | Current 0.67 owner | Decision |
|---|---|---|---|
| Structural/value solve | `core/auction_engine_v06.js::solveAuctionPipeline` | Overlay WebView | REUSE; already called |
| Full-shadow decision lines | `calculateV06DecisionLines` | Overlay Solver runtime | REUSE only after support/context gate |
| P20/P50/P80 | `formalValue`, `rawShadow`, `decision.valueP*` | Overlay rendering | REUSE; quantiles, not accuracy |
| Recommended max | `decision.recommendedMax` | Overlay rendering | REUSE only for valid full-shadow result |
| Bid action | `decision.action` / live-bid comparison | Overlay rendering | ADAPT after a valid advice context exists |
| Current bid | v0.6 decision-console input; engine `leaderBid` | Current Manual has no matching input | ADAPT later, after context gate |
| Target profit | v0.6 decision-console input; snapshot normalized fact | Current adapters silently default to 30,000 | ADAPT later; no new Canonical truth field in this cut |
| Historical profile | `core/live_shadow.py` and existing runtime | Overlay currently receives it only on Vision HUD path | ADAPT later; do not use repo research history |
| Venue/box compatibility | legacy v0.6 aliases/priors | Frozen Alpha catalog compatibility rows | BLOCKED; current rows are explicitly unresolved |

## 3. Root cause of structural-only / no-advice

The current Manual path is:

`overlay_alpha.html::collectFacts` → `scheduleLocalSolver` → local `solverInput` → `paintResult` → `AuctionEngineV06.solveAuctionPipeline`.

It does not supply a frozen `probabilityProfile`; therefore the engine correctly produces `structural_only`, `rawShadow = null`, and `recommendedMax = null`. The existing Vision HUD path separately calls `app/main.py::build_in_auction_hud_payload` → `live_shadow.attach_live_shadow`, but that profile is not wired to Manual.

That missing wiring is not the only issue. The structural calculation itself calls `lowTierValue`, which consumes `venueTier || venue` and the v0.6 `LOW_TIER_PRIOR`. The approved Alpha catalog explicitly records all three current venue translations for consumer `v06_solver` as `UNRESOLVED`.

The focused test demonstrates the material mismatch:

| Current exact venue | Current exact-name prior | Old combined-label prior |
|---|---:|---:|
| 海贝场 | 12,000 fallback | 8,000 |
| 珊瑚场 | 12,000 | 12,000 |
| 真珠场 | 12,000 fallback | 30,000 |

Thus restoring the old aliases would change estimate inputs materially and would contradict the catalog's fail-closed authority rather than merely reconnect presentation.

## 4. Inputs and context status

- Current Manual inputs already reaching the engine: Q, gold average, purple count, known Gold/Red/Purple, exact venue, exact box, and field condition.
- Current catalog entry costs are authoritative: 海贝 0, 珊瑚 5,000, 真珠 20,000. They must not be replaced by the old fixed 5,000 default.
- Current bid is not present in the Manual form and therefore cannot drive a formal action.
- Target profit is not present in the Manual form. Both adapters/engine currently fall back to 30,000, so it cannot be presented as a user-confirmed business target.
- Exact current venue → v0.6 context remains `SOLVER_CONTEXT_MAPPING_UNRESOLVED` for all three venues.
- Exact catalog box → v0.6 effect semantics also lacks an approved compatibility authority. An exact display name must not silently become a normalized effect or default box.

## 5. Estimate, support, and advice semantics

- Intrinsic P20/P50/P80 are value-distribution quantiles from one solve. They are not accuracy, confidence percentages, win probability, or recommended bid.
- Without a real support envelope, the engine's structural values can remain diagnostic/structural presentation only; they cannot be promoted to historically supported formal advice.
- Runtime history must remain the durable per-user history. The repo research dataset must not be reintroduced to manufacture support.
- A supported-history fixture could exercise the mechanical shadow path, but it cannot resolve the venue/box semantic authority problem.
- Unknown box must remain unknown; no default effect is permitted.
- `recommendedMax` is produced by existing engine code only for `full_shadow` with valid costs. It must remain null while required context is unresolved.
- Action/advice must remain unavailable rather than substituting P50 or a structural reference bid.

Recommended fail-closed reason codes for the future wiring are the existing/required narrow set: `SOLVER_CONTEXT_MAPPING_UNRESOLVED`, `STRUCTURAL_ONLY`, `INSUFFICIENT_HISTORY`, `MISSING_INPUT`, and `UNKNOWN_BOX`. This cut did not introduce a second status taxonomy.

## 6. Prediction and terminal boundaries

- No Prediction Snapshot contract was changed.
- No recommendation was written into prediction or settlement truth.
- Manual DRAFT autosave, FINALIZED exactly-once transition, keep-DRAFT/CANCELLED flow, and next-match reset were not changed.
- No upper-tail capture schema or gate was changed.
- Because no formal result was admitted, there was no valid prediction/advice snapshot to persist in this cut.

## 7. Validation and smoke disposition

Focused validation added:

1. Production Alpha catalog status is `APPROVED_FOR_ALPHA`.
2. All three current venues return `SOLVER_CONTEXT_MAPPING_UNRESOLVED` through the catalog authority.
3. The engine exact-name versus legacy-label low-tier priors are measured, including the material 海贝/真珠 mismatches.

Results:

- new context gate: `2/2 PASS`;
- Venue/Box catalog + progressive Alpha catalog: `28/28 PASS`;
- frozen Manual terminal lifecycle/app flow: `13/13 PASS`;
- focused total: `43/43 PASS`.

Source UI smoke and fresh packaged UI smoke were **not entered**. The correctness gate failed before any product mutation, so packaging a knowingly unproven Advice path would not provide valid acceptance evidence. Existing Manual terminal/package evidence from the parent checkpoint remains untouched; it is not claimed as Advice smoke.

The following requested scenarios are consequently blocked rather than falsely marked PASS:

- empty-history formal estimate/advice;
- supported-history formal recommendation;
- current-bid action transition;
- estimate/advice → FINALIZED snapshot preservation;
- source/package Advice parity;
- next-match stale-Advice reset.

## 8. Integrity hashes

Before this cut:

- repo research history: `6A9695F8EF44058F2C369AC1BD1407A6306A327B63D1C0A160631D5348ED699A`
- `core/auction_engine_v06.js`: `8F31258F73B22CE978A61555AD6765E231305588F0B8239609CE8A8230F98862`
- `core/solver_core_v06.js`: `1EC8DCA270A8219EB00133421723A114F3649B81CD07C769C765AC2C7AFED07F`
- `core/shadow_profile_v06.js`: `9967F269F5C5B66DC8A010E3077CE014700C0B94333D93ACF25A4021F9C886A5`
- approved Alpha catalog: `321A0BD7851D30AAFF40022621E4B4C0A1157A25873DE28E50DCDAAE7CBF01D3`

These authorities are expected to remain byte-identical after this report/test-only cut.

## 9. Required unblock, not implemented here

The minimum unblock is evidence-backed, versioned compatibility data owned by the approved catalog (or a catalog-versioned generated adapter) for:

1. exact `venue-haibei` / `venue-shanhu` / `venue-zhenzhu` → v0.6 Solver context;
2. exact box IDs → the existing v0.6 effect semantics;
3. explicit unknown behavior.

It must change the current `UNRESOLVED` rows through the catalog governance path, not through an Overlay/UI hardcode. Once frozen, the next product cut can reconnect the existing live-shadow profile, add the minimal current-bid/target-profit inputs actually required by v0.6, render existing decision lines, and run the full source/package parity matrix without modifying Solver formulas.

## 10. Pre-existing failures

No unrelated legacy failures were modified or reclassified. A broader mixed run reproduced one pre-existing `tests.test_manual_alpha` fixture failure: it expects `qualities.gold.knownItems` to be a string, while current Canonical v7 emits the structured list `[{'name': ...}]`. The cut did not touch that producer or fixture. The mixed run was `45/46`, with only this unrelated failure. Pre-existing untracked workspace files were not included.
