# Capture Runtime Readiness / First Valid Pair Preflight v1

Audit date: 2026-08-22 (Asia/Shanghai)

Initial checkpoint: `95cfd17d5963fa0b3e070b3b6d120d076ee98b65`

Scope: experiment-only upper-tail capture readiness; no Solver/Shadow algorithm change, no history rewrite, no accuracy computation.

## Executive verdict

`READY_FOR_NATURAL_COLLECTION`

The prediction-time sidecar can now run from both source and a fresh frozen package, fails closed without changing the product prediction, and has a deterministic future truth-pair admission gate. There are no real reviewed pairs yet (`realValidPairCount = 0`). Algorithm work remains blocked until naturally collected, independently reviewed pairs exist and a separate Upper-tail Truth-Gated Audit v2 is run.

## 1. Repository and commit facts

### FACT

- `INITIAL_HEAD = 95cfd17d5963fa0b3e070b3b6d120d076ee98b65`.
- The tracked tree was clean at audit start. Numerous unrelated pre-existing untracked user/experiment/design files were present; none were deleted or staged by this work.
- Capture contract and runtime hook are both traceable to checkpoint commit `95cfd17d5963fa0b3e070b3b6d120d076ee98b65`.
- This readiness pass found and minimally fixed three infrastructure defects:
  1. the package omitted the Node runtime's three required JS assets;
  2. frozen runtime path resolution looked in `_internal` rather than `_internal/core`;
  3. runtime rejection observability and fixture/smoke/natural evidence separation were not strong enough to prevent test artifacts from resembling real evidence.

### RECOMMENDATION

Keep unrelated untracked files outside this commit. Treat the final commit from this audit as the natural-collection readiness checkpoint, not as an algorithm-performance checkpoint.

## 2. Actual runtime hook call chain

### FACT

The production call path is:

```text
app/main.py::build_in_auction_hud_payload
  -> core/live_shadow.py::attach_live_shadow
  -> core/live_shadow.py::_shadow_worker_loop
  -> core/live_shadow.py::compute_live_probability_profile
  -> core/live_shadow.py::_runtime_compute / _oneshot_compute
  -> core/live_shadow_runtime.js::compute
  -> core/auction_engine_v06.js::solveAuctionPipeline
  -> core/live_shadow_runtime.js::buildSupportCaptureEnvelope
  -> core/live_shadow.py::capture_prediction_support_envelope
  -> experiments/.../runtime_capture_hook.py::capture_prediction_support_envelope
  -> contract validation + atomic sidecar write
  -> existing probabilityProfile / predictionSnapshot / frozenPrediction publication
```

`buildSupportCaptureEnvelope` is invoked only after `solveAuctionPipeline` has returned a valid pipeline result and frozen prediction snapshot. The private envelope is removed from the public result path: only the pre-existing product profile/snapshot/frozen prediction are packed and cached. Capture invokes no Solver and performs no second prediction.

### INFERENCE

Capture timing is ex-ante with respect to settlement: the envelope is created inside the prediction runtime immediately after solve, not from the settlement/archive flow. Recursive forbidden-key validation additionally prevents a later enriched object from being persisted as a prediction capture.

## 3. Runtime ownership boundary

### FACT

- Overlay WebView remains the sole production Solver owner/runtime.
- Native/Python is a coordinator and sidecar serializer; it does not instantiate Solver state.
- Main WebView receives no support envelope and loads no Solver through this change.
- The hook consumes only the explicitly constructed private `production-support-envelope.v1`.
- It does not read `LATEST_PAYLOAD`, `CurrentMatch`, settlement history, OCR, or Vision output to reconstruct a prediction.

## 4. Prediction-time purity classification

### FACT

| Class | Artifact fields | Meaning |
|---|---|---|
| A — prediction-time observable | `matchId`, `matchBinding`, `capturePhase`, `capturedAt`, embedded `predictionSnapshot`, `fullCandidateStates`, `valuationStates` | Values present when the production solve finishes |
| B — production-derived support | normalized mixture weights, per-state valuation breakdown, supported/unsupported tail blocks, aggregate P20/P50/P80 and quantile provenance | Already-emitted support used by the production prediction; serialized, not recomputed |
| C — metadata/hash | schema/contract versions, `collectionClass`, resolver/method versions, capture/prediction/artifact IDs and SHA-256 graph | Provenance, integrity, and evidence-class separation |
| D — forbidden post-settlement | `actualTotal`, settlement/settlementItems, reviewed truth/truth artifact, post-match correction, clearing price, purchase spend, realized profit, acquired items | Recursively rejected; no sidecar is written |

The runtime match id must be explicit and cannot be `unknown_match`. `capturedAt` must include a timezone. `collectionClass` is part of the prediction hash and can only be fixture, smoke, or natural runtime.

### VERDICT

`PREDICTION_TIME_PURITY_PASS`.

## 5. Published prediction versus capture equality

### FACT

- Contract validation requires aggregate `p20`, `p50`, and `p80` to equal the embedded frozen `prediction-snapshot.v1` values exactly.
- The deterministic fixture checks `predictionSnapshotSha256`, `predictionHash`, and all intermediate hashes.
- Source and packaged runtime smokes compare the capture quantile object directly with the prediction snapshot published by the same solve; both returned `quantilesEqual = true`.
- The capture builder does not have an independent quantile estimator.

### VERDICT

`EXACT_QUANTILE_EQUALITY_PASS`.

## 6. Candidate/valuation mapping integrity

### FACT

The contract and runtime converter require:

- declared full-state and valuation-state counts to match actual arrays;
- every `fullCandidateState` to be referenced exactly once;
- no duplicate `sourceFullStateId` ownership;
- every source state id to exist;
- single-source valuation geometry to match its full state;
- explicit resolver/compression method when aggregation occurs;
- no missing mapping or implicit state loss.

Missing or inconsistent data returns a deterministic rejection reason and writes no artifact. No fallback geometry is invented.

### VERDICT

`STATE_MAPPING_INTEGRITY_PASS`.

## 7. Weight integrity

### FACT

- `normalizedWeight` must be finite and non-negative.
- The full valuation-state sum must be 1 within the contract's frozen tolerance.
- Runtime conversion copies the production profile's actual `stateCandidates[].relativeWeight` used by the mixture.
- It does not persist debug/pre-normalized weights and has no uniform fallback or weight re-estimator.
- Supported weight is reconciled to the frozen prediction coverage.

### VERDICT

`PRODUCTION_MIXTURE_WEIGHT_INTEGRITY_PASS`.

## 8. Tail and quantile provenance integrity

### FACT

Each supported valuation state records P20/P50/P80/P95/max plus tail mode, method, version, direct-game count, bootstrap count, and evidence references/hashes. An unsupported state must record an explicit reason and cannot silently become a zero-valued tail.

The integrity graph hashes full states, valuation states, normalized weights, breakdowns, and tail contributions into `mixtureInputSha256`. Aggregate P20/P50/P80 provenance repeats that exact hash and lists participating valuation state IDs. The validator rejects numerical/provenance cross-link mismatches.

### VERDICT

`TAIL_AND_QUANTILE_PROVENANCE_PASS`.

## 9. Sidecar lifecycle and package path

### FACT

Default natural store:

```text
%LOCALAPPDATA%\异环拍卖助手\experiment_captures\
  upper_tail_truth_support_capture_v1\predictions\utsc_<prediction-hash-prefix>.json
```

- `YIHUAN_UPPER_TAIL_CAPTURE_DIR` is an explicit source/package smoke override.
- Filename is content-addressed by validated `captureId`.
- Write uses `mkstemp` in the destination directory, UTF-8 serialization, flush + `fsync`, then `os.replace`; the `finally` block removes any surviving temp file.
- Same valid content is `DUPLICATE` and is not rewritten.
- A corrupt file at the target path is rejected and never overwritten.
- Process restart preserves the same behavior because validation is file/content based, not in-memory based.
- Frozen layout now resolves runtime JS from `_MEIPASS/core`; the spec includes `live_shadow_runtime.js`, `shadow_profile_v06.js`, and `solver_core_v06.js`.

### VERDICT

`SIDECAR_LIFECYCLE_PASS`.

## 10. Storage growth / retention preflight

### FACT

- The current default directory contains 10 pre-readiness test-generated prediction files, 7,555–10,762 bytes each (100,456 bytes total), and no truth sidecars. All use `unknown_match` and predate `collectionClass`; the revised validator rejects them, so none count as fixture, smoke, natural, or real pairs. They were preserved rather than deleted.
- The refreshed deterministic fixture is 9,520 bytes; the real source/frozen smoke artifact is 10,647 bytes.
- The audited production candidate support has historically been small (up to about 10 states in this audit context).

### INFERENCE

- Expected ordinary artifact size is roughly 8–12 KB.
- A conservative multi-state upper-tail planning range is about 35–50 KB for a much larger candidate envelope.
- 100 naturally distinct predictions are approximately 0.8–5 MB; 1,000 are approximately 8–50 MB.
- Content-addressed idempotence prevents unbounded repeat writes of one identical prediction, but genuinely distinct predictions accumulate.

### RECOMMENDATION

No retention subsystem is justified yet. Reassess after natural collection supplies observed growth and access patterns.

## 11. Capture failure semantics

### FACT

Frozen semantics are:

```text
production prediction continues unchanged
capture returns REJECTED
reason code is retained and logged
no invalid artifact is persisted
public payload/history/CurrentMatch are untouched
```

A focused integration regression injects a forbidden post-settlement field, confirms warning logging and rejection, and confirms the product profile/snapshot/frozen outputs still publish unchanged.

### VERDICT

`FAILURE_ISOLATION_PASS`.

## 12. Reviewed settlement truth flow

### FACT

The future flow is:

```text
immutable natural prediction capture
  -> later settlement
  -> independent review under existing evidence boundary
  -> upper-tail-settlement-truth.v1 sidecar
  -> exact pair validator
```

Truth links by all three immutable values: `captureId`, `predictionHash`, and prediction `artifactSha256`. It never selects “the nearest” or most recent prediction. The truth builder creates a separate artifact and never overwrites prediction capture.

`reviewClass = INDEPENDENT_REVIEWED_SETTLEMENT` and an explicit reviewer are required for a real pair. OCR stability, repeated frames, and same-source evidence do not automatically grant independent-review status.

`COMPLETE` requires reconciled components and zero unattributed value. `PARTIAL` can be preserved for audit but is deterministically rejected from `VALID_UPPER_TAIL_PAIR_V1`.

## 13. `VALID_UPPER_TAIL_PAIR_V1` gate

### FACT

`pair_admission.py` defines `gateVersion = valid-upper-tail-pair.v1`. Admission requires:

1. prediction contract/hashes/mapping/weights/quantiles all valid;
2. `collectionClass = NATURAL_RUNTIME_CAPTURE`;
3. truth contract/evidence/hash all valid;
4. exact prediction capture/hash/artifact linkage;
5. `reviewClass = INDEPENDENT_REVIEWED_SETTLEMENT`;
6. timezone-aware review at or after prediction capture;
7. `COMPLETE` actual-value decomposition.

It separately reports `MATCHED_VALUATION_STATE`, `STATE_SPACE_MISSING`, or `INVALID_REALIZED_STATE`. `valueModelErrorEligible` additionally requires a matched valuation state. The gate computes no accuracy, error, score, or causal verdict.

Deterministic reason codes include prefixed prediction/truth contract failures plus non-natural capture, non-independent review, invalid time order, and incomplete truth decomposition.

## 14. Fixture, smoke, and real pair accounting

### FACT

| Evidence class | Prediction captures | Linked truth artifacts | Admitted real pairs |
|---|---:|---:|---:|
| `CONTRACT_VALID_FIXTURE` | 1 | 1 | 0 |
| source `RUNTIME_SMOKE_CAPTURE` | 1 | 0 | 0 |
| packaged `RUNTIME_SMOKE_CAPTURE` | 1 | 0 | 0 |
| `REAL_REVIEWED_PAIR` | 0 | 0 | 0 |

`realValidPairCount = 0`.

Synthetic unit tests exercise natural/independent branches but are test-local and are never counted as stored natural observations or real pairs.

## 15. Source/package parity

### FACT

- Source smoke: PASS; real Node support path, `WRITTEN`, exact quantiles, temporary history unchanged, 10,647-byte artifact.
- Fresh packaged smoke: PASS; same parity signature `064aa98e41348b9c91b6917671a6f14f1d1dd73c68fa529e7ac9b3365153df2e`, `WRITTEN`, exact quantiles, temporary history unchanged, 10,647-byte artifact, exit code 0, no lingering process.
- Smoke capture IDs differ because `capturedAt` and build provenance are hashed; this is expected and does not weaken schema/output parity.

## 16. Integrity hashes

### FACT

| Target | Before SHA-256 | After SHA-256 |
|---|---|---|
| `异环拍卖数据.json` | `E9C75F920646839F3DAFA02E7A6DFF1802827E0D4C4DCBBE121F21C7B82847FE` | `E9C75F920646839F3DAFA02E7A6DFF1802827E0D4C4DCBBE121F21C7B82847FE` |
| `core/solver_core_v06.js` | `1EC8DCA270A8219EB00133421723A114F3649B81CD07C769C765AC2C7AFED07F` | `1EC8DCA270A8219EB00133421723A114F3649B81CD07C769C765AC2C7AFED07F` |
| `core/shadow_profile_v06.js` | `9967F269F5C5B66DC8A010E3077CE014700C0B94333D93ACF25A4021F9C886A5` | `9967F269F5C5B66DC8A010E3077CE014700C0B94333D93ACF25A4021F9C886A5` |

All three are byte-for-byte unchanged. The default sidecar directory also
retained the same 10-file manifest hash before and after regression tests, so
test calls without a runtime match id produced no new natural-store artifacts.

## 17. Risks and recommendations

### FACT

- No real independently reviewed pair exists yet.
- Capture currently depends on the external Node runtime already required by the live-shadow production path; this audit did not add or vendor a second runtime.
- Old test artifacts remain on disk but are invalid under the new evidence-class contract and cannot pass the real-pair gate.

### RECOMMENDATION

- Allow normal product usage to accumulate `NATURAL_RUNTIME_CAPTURE` sidecars; do not ask the user to grind benchmark games.
- When settlement evidence is independently reviewed, create a separate exact-linked truth sidecar.
- Do not change state support, likelihood, value model, variance, or Gold cap until real contract-valid pairs exist and Upper-tail Truth-Gated Audit v2 is performed.

## Final verdict

`READY_FOR_NATURAL_COLLECTION`

This verdict means capture infrastructure is ready for passive natural evidence collection. It does **not** validate `C_VALUE_MODEL_ERROR`, prove model accuracy, or authorize algorithm changes.
