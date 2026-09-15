# Upper-tail Truth/Support Capture Contract v1

Experiment-only sidecar contract for future upper-tail audits. It links the existing authoritative `prediction-snapshot.v1` and `settlement-truth-evidence.v1` contracts without changing either production artifact.

## Two-phase chain

```text
existing Solver result + frozen prediction-snapshot.v1
  -> experiment capture input
  -> upper-tail-prediction-support-capture.v1
  -> later reviewed settlement evidence
  -> upper-tail-settlement-truth.v1
  -> future truth-gated audit (not implemented here)
```

Prediction-time capture freezes:

- the complete hard candidate state set;
- the valuation state set and explicit full-state mapping;
- normalized weights;
- per-state gold/purple/red/low-tier valuation breakdown and provenance;
- supported/unsupported per-state tail distributions and evidence hashes;
- P20/P50/P80 source state IDs and mixture-input hash;
- prediction snapshot hash, prediction hash, capture ID, and artifact hash.

Every prediction artifact also carries a non-semantic collection class:

- `CONTRACT_VALID_FIXTURE` for deterministic contract fixtures;
- `RUNTIME_SMOKE_CAPTURE` for source/frozen runtime probes;
- `NATURAL_RUNTIME_CAPTURE` for naturally collected product observations.

Only the last class can enter the real-pair admission gate.

Settlement capture freezes:

- independently verified G/P/R and reviewer provenance;
- links to existing truth evidence by URI, file hash, and truth-payload hash;
- actual-value components, their evidence references, unattributed value, and reconciliation delta;
- an exact link to the prediction-time capture.

Truth review is likewise classified as `CONTRACT_VALID_FIXTURE` or
`INDEPENDENT_REVIEWED_SETTLEMENT`; only an independently reviewed artifact can
form a real pair.  A fixture or smoke artifact can prove infrastructure only.

## Authority boundary

- The contract/hook imports no Solver, Shadow algorithm, history, OCR, or Vision module.
- The authorized integration changes only the live-shadow coordinator/runtime protocol and packaging entrypoint; `auction_engine_v06.js`, `solver_core_v06.js`, and `shadow_profile_v06.js` remain unchanged.
- The adapter does not reconstruct candidate support. It maps the already-emitted expanded states, relative weights, components, tails, and quantiles into the frozen contract and performs only validation, arithmetic reconciliation, and hashing.
- The builder computes integrity hashes and arithmetic reconciliation only. It computes no accuracy, MAE, bias, coverage score, or A/B/C/D verdict.
- `PARTIAL` value decomposition is preservable but is not sufficient by itself for a future C-value-model-error conclusion.
- These files are sidecars. They are never written into `异环拍卖数据.json`.

## CLI

```powershell
python experiments/upper_tail_truth_support_capture_v1/capture_contract.py capture-prediction `
  --input experiments/upper_tail_truth_support_capture_v1/fixtures/prediction_capture_input.json `
  --output prediction_capture.json

python experiments/upper_tail_truth_support_capture_v1/capture_contract.py capture-truth `
  --input experiments/upper_tail_truth_support_capture_v1/fixtures/truth_capture_input.json `
  --prediction prediction_capture.json `
  --output truth_capture.json

python experiments/upper_tail_truth_support_capture_v1/capture_contract.py validate `
  --artifact prediction_capture.json
```

Truth validation additionally requires `--prediction prediction_capture.json`.

## Future re-evaluation gate for C

A later audit may evaluate `C_VALUE_MODEL_ERROR` only when all of the following hold:

1. both artifacts pass their validators and hashes;
2. the verified G/P/R reconciles with prediction-time Q;
3. the realized state is linked to a captured valuation state;
4. that state has supported tail provenance;
5. actual-value decomposition is `COMPLETE` and evidence-backed;
6. comparison semantics are defined by a separate versioned audit.

This v1 contract deliberately does not perform step 6.

## Runtime capture hook

`runtime_capture_hook.py` is the only runtime-facing experiment adapter.  The
Node shadow runtime creates a private `production-support-envelope.v1` only
after `solveAuctionPipeline` returns.  The Python coordinator consumes that
envelope on a cache miss, validates it, writes a sidecar, and never exposes the
private envelope to the HUD or canonical history.

Default sidecar location:

```text
%LOCALAPPDATA%/异环拍卖助手/experiment_captures/
  upper_tail_truth_support_capture_v1/predictions/utsc_<hash>.json
```

`YIHUAN_UPPER_TAIL_CAPTURE_DIR` is the source/package smoke override.  Existing
valid captures are immutable and replay-safe; corrupt files are rejected and
never overwritten.  Predictions without frozen full-inventory P20/P50/P80 are
not eligible for this upper-tail v1 artifact and produce no file.

Runtime capture requires an explicit native match id; missing or
`unknown_match` bindings fail closed and produce no artifact. Exact snapshot
bindings are marked `EXACT_SNAPSHOT_MATCH`; an explicitly authorized runtime
binding is hashed as `RUNTIME_CONTEXT_BINDING`. Arbitrary mismatches fail
closed.

## First-valid-pair gate

`pair_admission.py` defines deterministic gate
`valid-upper-tail-pair.v1`. `VALID_UPPER_TAIL_PAIR_V1` requires a valid
`NATURAL_RUNTIME_CAPTURE`, a valid `INDEPENDENT_REVIEWED_SETTLEMENT`, exact
capture/hash/artifact linkage, timezone-ordered review, and `COMPLETE` actual
value decomposition. It reports whether verified G/P/R matches a captured
valuation state, but computes no accuracy or model-performance metric.
