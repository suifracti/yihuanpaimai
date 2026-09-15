# Upper-tail Truth/Support Capture Contract v1 — implementation report

## Outcome

`CAPTURE_HOOK_INTEGRATED`

The experiment-only two-phase capture chain is implemented. Production Solver output and canonical history remain unchanged. No performance metric or new causal verdict is calculated.

## Files and contracts

- `capture_contract.py`: deterministic builders, validators, content hashing, atomic sidecar writer, and CLI.
- `upper_tail_prediction_support_capture_v1.schema.json`: machine-readable prediction support shape.
- `upper_tail_settlement_truth_v1.schema.json`: machine-readable reviewed truth shape.
- `fixtures/prediction_capture_input.json`: future capture-envelope fixture.
- `fixtures/truth_capture_input.json`: reviewed settlement fixture.
- `fixtures/expected_prediction_capture.json`: deterministic frozen prediction example.
- `fixtures/expected_truth_capture.json`: deterministic frozen truth example.
- `test_capture_contract.py`: focused fail-closed regression suite.

## Prediction artifact

Schema: `upper-tail-prediction-support-capture.v1`.

The artifact embeds an unchanged `prediction-snapshot.v1` and records its SHA-256. Candidate geometry is represented at two explicit layers:

1. `fullCandidateStates`: complete production candidate geometry;
2. `valuationStates`: the states actually used for probability/value mixture, each with canonical `sourceFullStateIds`.

Every full state must be owned exactly once. Single-source valuation geometry must match its full state. Compression requires an explicit aggregation method. This makes reconstruction/compression differences auditable instead of implicit.

Each valuation state contains:

- `normalizedWeight`, with sum exactly 1 within numeric tolerance;
- `valuationBreakdown.components[]` and reconciled total range;
- `tailContribution.supportStatus`;
- supported state P20/P50/P80/P95/max;
- tail mode, method, version, direct-game count, bootstrap count, and evidence references.

Aggregate P20/P50/P80 must equal the existing frozen prediction snapshot. Their provenance points to the supported state IDs and `mixtureInputSha256`.

Integrity graph:

```text
predictionSnapshotSha256
fullCandidateStatesSha256
valuationStatesSha256
normalizedWeightsSha256
valuationBreakdownsSha256
tailContributionsSha256
       -> mixtureInputSha256
       -> quantile provenance
       -> predictionHash
       -> captureId
       -> artifactSha256
```

`collectionClass` separates deterministic fixtures, runtime smoke probes, and
natural runtime observations. The class is part of the hashed prediction body,
so test artifacts cannot be relabeled as real observations.

## Settlement truth artifact

Schema: `upper-tail-settlement-truth.v1`.

It records independently reviewed G/P/R, verification method/version/reviewer, existing truth-evidence references, actual-value components, per-component evidence references, unattributed value, and reconciliation delta. Verified G/P/R must sum to prediction-time Q.

The truth artifact links exactly one prediction capture by `captureId`, `predictionHash`, and `artifactSha256`. It cannot be silently relinked after capture.

`reviewClass` is also hashed. Only `INDEPENDENT_REVIEWED_SETTLEMENT` with an
explicit reviewer may enter the future real-pair gate; contract fixtures remain
non-real by construction.

`COMPLETE` requires zero unattributed value. `PARTIAL` remains auditable but must not be treated as complete value ground truth.

## Fail-closed gates

- missing/duplicate/incompletely mapped states;
- non-canonical source-state mapping;
- state geometry mismatch;
- normalized weights not summing to one;
- support weight inconsistent with frozen coverage;
- missing or non-reconciling valuation breakdown;
- unsupported tail without explicit reason;
- supported tail without versioned evidence provenance;
- aggregate quantile mismatch with `prediction-snapshot.v1`;
- any intermediate or final hash mismatch;
- non-verified G/P/R or Q mismatch;
- missing truth evidence;
- actual decomposition mismatch;
- truth-to-prediction link mismatch;
- timezone-naive capture/review timestamps.
- missing/`unknown_match` runtime match identity or forbidden post-settlement fields;
- fixture/smoke collection classes presented as natural runtime evidence.

## Scope proof

- Solver algorithm modifications: `none`.
- Shadow algorithm modifications: `none`.
- Runtime integration: private post-solve envelope in `live_shadow_runtime.js`, consumed by the Python coordinator before product publication.
- Canonical history writes: `none`.
- Existing record migration: `none`.
- New heuristic/parameter: `none`.
- Accuracy/performance metrics: `none`.
- Re-evaluation of `C_VALUE_MODEL_ERROR`: intentionally deferred until future valid paired artifacts exist.

## Runtime integration status

`CAPTURE_HOOK_INTEGRATED`.

The experiment hook is attached at the live-shadow cache-miss boundary:

```text
solveAuctionPipeline returns
  -> private support envelope (timestamped, snapshot-hashed)
  -> experiment normalization and fail-closed validation
  -> atomic immutable sidecar
  -> existing profile/snapshot/frozen prediction published unchanged
```

The envelope is not part of the public HUD/Shadow payload.  It records no
settlement fields and cannot be generated from the settlement/archive path.
Invalid mapping, non-normalized weights, quantile/hash mismatch, timezone-naive
timestamps, duplicate corruption, and non-auditable match binding all produce
no new artifact.  No legacy history is backfilled.

The deterministic `valid-upper-tail-pair.v1` gate additionally requires exact
prediction/truth linkage, natural runtime collection, independent review,
review-after-capture ordering, and `COMPLETE` value decomposition. It exposes
reason codes and realized-state support relation only; it computes no accuracy
or causal verdict.
