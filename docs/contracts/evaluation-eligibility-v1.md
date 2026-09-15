# Evaluation Eligibility Contract v1

The executable authority is `app/evaluation_eligibility.py`. It validates provenance and emits eligibility/reason counts only. It must not replay Solver or compute MAE, Bias, accuracy, calibration, or any other performance metric.

## Gate order

`Persisted Record` → `History Admission` → `Duplicate Isolation` → `Truth Gate` → `Prediction Snapshot Gate` → `Temporal Compatibility` → `Target/Mode Compatibility` → `Model Cohort` → `Eligibility Result`

## Legacy candidates

A legacy row may be labeled `legacy_candidate` only when it is History-admitted and has high/manual verified total truth plus saved `solvedAt`, legacy input hash, solver/model/catalog versions, and saved calibrated P20/P50/P80. This label is diagnostic. It never grants formal eligibility.

Legacy `sha1-*` input hashes are actually 32-bit fast hashes in the current implementation. They are flagged `LEGACY_WEAK_INPUT_HASH` and must not be reinterpreted as SHA-1.

## Output rules

- Per-record result: formal eligible boolean, structured reasons, and normalized metadata needed by a later evaluator.
- Aggregate scanner: record/admission/candidate/formal counts, single-primary rejection counts, all-reason counts, flags, and eligible cohort counts.
- `formallyEligibleCount + sum(primaryRejectionReasonCounts) == recordCount`.
- Multiple valid model versions are always separate cohort keys; no combined metric cohort is created.
- No raw records or metric values are emitted by the CLI scanner.

## Formal requirements

- Prediction must conform to `prediction-snapshot.v1` under `record.predictionSnapshot`.
- Truth must conform to `settlement-truth-evidence.v1` under `record.settlement.truthEvidence`.
- Formal candidates must be Canonical record schema 7; schema-less legacy rows remain diagnostic candidates only.
- Prediction cutoff/solve must predate settlement observation.
- Full actual-value evaluation requires valid full Shadow and full-inventory forecast target.
- Partial/structural outputs cannot masquerade as a full-inventory forecast.
- Red-tail/item-level eligibility additionally requires complete scope and a verified, deduplicated item ledger.

## Reason-code authority

All reason strings are frozen in `EligibilityReason`. History reasons are imported from `HistoryExclusionReason`; no second History vocabulary is created.
