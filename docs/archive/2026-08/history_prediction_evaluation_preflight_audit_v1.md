# History / Records + Prediction Evaluation Preflight Audit v1

**Checkpoint:** `205c49706d563cbc6445818d74c927e2058c951d`  
**Audit date:** 2026-08-21 (`Asia/Shanghai`)  
**Mode:** read-only audit and contract decision. No product code, History UI, Evaluation pipeline, Solver, persisted history, or mock metric was changed.

## Executive verdict

`READY_AFTER_CONTRACT_FIX`

This verdict has two deliberately separate parts:

- **History / Records:** ready for a minimal read-only implementation after the existing record-admission rules are promoted into one explicit shared `History Admission Policy v1`. The persisted file contains useful admitted facts, but it is not a homogeneous Canonical v7 dataset.
- **Prediction Evaluation:** currently `BLOCKED_BY_DATA_PROVENANCE` for product metrics. The file contains a small promising cohort, but no record presently satisfies a complete, versioned Prediction Snapshot Gate plus independently auditable Truth Gate. Main must continue to show Analysis as mock/unavailable.

At audit time the live persisted file contains **287 records**, not the earlier 285-record baseline. The difference is two additional DRAFTs; the admitted population remains **155**. Current `MainViewStateProvider` result is **155 admitted / 132 excluded**.

The strongest existing evaluation precursor is:

- 23 admitted records with `solvedAt`, `inputHash`, Solver/model versions, saved calibrated P20/P50/P80, high/manual settlement confidence, and screenshot references;
- of those, 21 have `solverStatus=valid`;
- of those valid snapshots, 13 are full-coverage, 7 partial-coverage, and 1 has no resolvable coverage mode;
- none has a versioned prediction-snapshot contract, exact stored input payload, dataset revision, truth evidence hash/reviewer, or settlement observation timestamp.

Therefore **13 is a candidate audit cohort, not a publishable sample count**. The formal product evaluation sample count is still **0** until the contract/evidence gate is implemented and those candidates are independently admitted.

---

## 1. Scope, evidence, and decision vocabulary

### FACT — inspected authorities

The audit traced the current persisted/history and presentation call chains through:

- `异环拍卖数据.json` (actual persisted file at audit time);
- `app/main.py`, including `CANONICAL_DATABASE`, DRAFT persistence, worker archive, Main provider, and lifecycle;
- `app/main_view_state.py` and its admission/cache contract;
- `app/main_window.py`, `core/main_window.js`, and `core/main_window.html`;
- `core/current_match.py` and `docs/contracts/canonical-match-record-v7.md`;
- `core/auto_archiver.py`, `core/live_shadow.py`, and `core/auction_engine_v06.js`;
- `core/solver_core_v06.js` / Lab evaluation definitions as experimental reference only;
- focused history, frozen-prediction, Shadow, finance, and Main-boundary tests;
- `app/异环拍卖助手.spec` and the current source/frozen data-path resolution.

### Definitions used in this report

These states are not interchangeable:

| Term | Meaning |
|---|---|
| `record exists` | A JSON row is physically present. No quality claim. |
| `history admitted` | The row passed lifecycle, ID, timestamp, duplicate, diagnostic, and minimum settlement-evidence rules for a history view/count. |
| `evaluation eligible` | The admitted row also passed Truth Gate, Prediction Snapshot Gate, temporal/target compatibility, model/mode policy, and duplicate isolation. |
| `high-confidence ground truth` | The target truth is independently traceable to approved evidence with a declared verification method; a field named `verified` is insufficient by itself. |

### Boundary that remains authoritative

Main is a presentation consumer. It must not receive or invoke:

- mutable `CurrentMatch` or raw `LATEST_PAYLOAD`;
- raw records, bids, settlement item lists, OCR text, screenshots, or player facts;
- Solver input/result objects or a Solver replay API;
- `live_shadow.current_snapshot()` or another mutable runtime/history object.

Overlay remains the sole production Solver runtime. Offline evaluation owns artifacts; native Main reads only immutable whitelist summaries.

---

## 2. Current persisted data facts

### FACT — file-level contract

| Property | Observed value |
|---|---:|
| Canonical runtime path (source run) | `D:\yihuanpaimai\异环拍卖数据.json` |
| Size | `34,794,075` bytes |
| SHA-256 at audit | `b66b61116d196d344462228038aaef771cd7a74a78bb46a5efb6ccaa948b074e` |
| Top-level `version` | `v0.6` |
| Top-level `schemaVersion` | `6` |
| Records | `287` |
| Per-record `schemaVersion=7` | `107` (all current DRAFTs) |
| Per-record schema absent | `180` |

The top-level object also retains legacy/migration audit metadata. Its stored `savedAt` predates subsequent file writes, so it is not a reliable source revision. The byte SHA-256/atomic file revision is the reliable revision.

### FACT — actual schema/product mixture

| Cohort | Count | Meaning |
|---|---:|---|
| Canonical-shaped v7 DRAFT | 107 | Created by `CurrentMatch.to_canonical()` / DRAFT persistence; not finalized history. |
| Legacy/schema-less persisted rows | 180 | Calculator/manual/user/screenshot/auto-archive generations with mixed versions. |
| `productVersion=v0.67-alpha` | 107 | DRAFT cohort. |
| `v0.1 / v0.2 / v0.3 / v0.5 / v0.6 / v0.65` | 180 total | Multiple historical producer generations. |

`Canonical MatchRecord v7` is a design contract and the DRAFT shape. It is **not** the current finalized persisted-history format. The active `AutoArchiver` still writes schema-6-style top-level records, omits per-record `schemaVersion`, and does not set `lifecycleStatus=FINALIZED`.

### FACT — lifecycle and timestamp completeness

| Evidence | Count |
|---|---:|
| `lifecycleStatus=DRAFT` | 107 |
| Lifecycle absent | 180 |
| Explicit FINALIZED | 0 |
| Parseable timezone-naive `playedAt/timestamp` | 266 |
| Missing timestamp | 21 |
| Timezone-aware timestamp | 0 |

Legacy naive timestamps must continue to be interpreted as `Asia/Shanghai`; silently using machine locale would change day admission and temporal ordering.

### FACT — source/producer distribution

| `source` | Count |
|---|---:|
| `calculator` | 128 |
| `manual` | 128 |
| `0.65-vision-auto-archiver` | 16 |
| `screenshot-batch` | 8 |
| `user` | 7 |

The current schema does not have one uniformly populated, versioned `producer` object. `source` and `productVersion` are the available but incomplete proxies.

### FACT — exact and probable duplicates

- Missing IDs: `0`.
- Duplicate ID groups: `0`.
- One exact content-fingerprint group contains `2` rows with the same timestamp/value/clearing/venue/box tuple but different IDs.

### INFERENCE

ID-upsert protects only repeated writes using the same ID. `AutoArchiver` creates time-derived IDs and its signature dedupe is process-local and limited to 60 seconds, so semantically duplicated records can survive under different IDs.

### RECOMMENDATION

- Exact duplicate IDs: fail closed for both History and Evaluation.
- Probable content duplicates: do not delete automatically; mark `POTENTIAL_CONTENT_DUPLICATE`. They may be shown only with a data-quality badge and must be excluded from Evaluation until resolved.
- A future stable match/event identity should be producer-owned; presentation code must not invent one.

---

## 3. Current History Admission Matrix

### FACT — current `MainViewStateProvider` policy result

| Result | Count |
|---|---:|
| Admitted | 155 |
| Excluded | 132 |
| Excluded: `DRAFT` | 107 |
| Excluded: `INVALID_TIMESTAMP` | 21 |
| Excluded: `LEGACY_WITHOUT_SETTLEMENT_EVIDENCE` | 4 |

At the 2026-08-21 local-day boundary, today and yesterday are both zero admitted matches. The additional local records are DRAFTs and correctly do not change the real match-count card.

### Proposed `History Admission Policy v1`

This proposal formalizes and extends the existing `ADMISSION_POLICY_VERSION=1`; it must not become a second competing policy.

| Record condition | History decision | Evaluation decision | Reason |
|---|---|---|---|
| Not a JSON object | Exclude | Exclude | `INVALID_RECORD` |
| Missing/blank ID | Exclude | Exclude | `MISSING_RECORD_ID` |
| Duplicate ID | Exclude every member | Exclude | `DUPLICATE_RECORD_ID` |
| Probable content duplicate | Admit only as flagged diagnostic/history fact | Exclude pending review | `POTENTIAL_CONTENT_DUPLICATE` |
| `DRAFT` | Exclude | Exclude | `DRAFT` |
| `CANCELLED/CANCELED` | Exclude | Exclude | `CANCELLED` |
| Diagnostic record/status | Exclude | Exclude | `DIAGNOSTIC` |
| Unsupported explicit lifecycle | Exclude | Exclude | `UNSUPPORTED_LIFECYCLE` |
| Invalid/missing timestamp | Exclude from dated History | Exclude | `INVALID_TIMESTAMP` |
| `FINALIZED` + valid structure | Admit | Continue to Truth Gate | Explicit lifecycle. |
| Legacy without lifecycle, nested verified settlement + positive actual | Admit | Continue to stricter Truth Gate | Compatibility only. |
| Trusted auto archive + positive actual and clearing | Admit | Continue to stricter Truth Gate | Existing match-count compatibility. |
| Other legacy row | Exclude | Exclude | `LEGACY_WITHOUT_SETTLEMENT_EVIDENCE` |

### Timestamp normalization

1. Parse ISO `playedAt`, falling back only to the declared legacy `timestamp` field.
2. `Z`/offset timestamps are converted to `Asia/Shanghai` for display windows.
3. Legacy naive timestamps are explicitly assigned `Asia/Shanghai`, not machine-local time.
4. Persist both normalized instant and a `timestampAssumption=legacy_asia_shanghai` provenance marker in an internal normalized record; do not rewrite the source row.
5. Evaluation additionally requires unambiguous ordering between prediction cutoff and settlement observation.

### Important limitation

`history admitted` is suitable for match counts and a traceable records index. It is **not** a blanket assertion that every field in the admitted row is true. Each History column still has a field-specific availability/trust gate.

---

## 4. Settlement truth and confidence audit

### FACT — admitted population

| Field/evidence among 155 admitted records | Count |
|---|---:|
| Positive `actualTotal` | 155 |
| Positive `clearingPrice` | 95 |
| Nested settlement status/verified | 150 |
| `truthConfidence=high` | 39 |
| `truthConfidence=unknown` | 111 |
| No nested truth confidence | 5 |
| `truthSource=manual-settlement` | 39 |
| Settlement ledger marked verified | 0 |

The 150 `verified` values are not equivalent to 150 independently verified truths. Legacy normalization in `solver_core_v06.js` can promote a positive legacy `actualTotal` to settlement status `verified`; 111 of the admitted verified rows still have `truthConfidence=unknown`.

The 39 high/manual records are stronger. However, even the strongest 23 prediction-bearing records have:

- screenshot references: yes (32 references across 23 records);
- OCR evidence: 22/23;
- `settlementObservedAt`: 0/23;
- truth evidence hash: 0/23;
- reviewer/verification actor: 0/23;
- versioned truth-verification method: absent.

### Proposed Truth-confidence Gate v1

For **full-inventory actual value** evaluation, require all of:

1. History admitted and not a probable duplicate.
2. `settlement.status=verified` and a positive finite `actualTotal`.
3. Enumerated `truthSource` and `truthConfidence=high` (or a separately approved machine-verification tier).
4. `settlementObservedAt` after the selected prediction's `informationCutoffAt/solvedAt`.
5. Immutable evidence reference(s) plus content hash.
6. Verification method/version and reviewer or deterministic verifier identity.
7. No unresolved conflict between top-level and nested truth values.

For **item/quality/Red-tail** evaluation, additionally require:

- complete physical inventory scope;
- verified/deduplicated item ledger or explicit complete Red inventory;
- item identity/quality provenance appropriate to the requested metric.

### INFERENCE

The current data can support a human evidence audit of total-value truth. It cannot support product-grade item-level or Red-tail evaluation: no current record has a verified settlement ledger, and the high-confidence string alone does not prove inventory completeness.

---

## 5. Prediction provenance audit

### FACT — current production snapshot generator

`core/auction_engine_v06.js::buildPredictionSnapshot()` currently produces a frozen object with model/solver/catalog versions, status, `inputHash`, `solvedAt`, round, estimate, decision lines, structural/formal values, Shadow/calibration, market and entry decision, and costs.

`AutoArchiver.archive_match()` copies `ctx.frozenPrediction || ctx.prediction` without recomputing it. That is the correct preservation direction.

However, the current `inputHash` implementation is not SHA-1 despite its `sha1-` prefix: `solverInputHash()` uses a 32-bit FNV-style `fastHash`. The exact normalized input payload is not persisted beside the hash.

### FACT — actual persisted prediction coverage

| Evidence among 155 admitted records | Count |
|---|---:|
| Prediction object | 128 |
| No prediction object | 27 |
| Legacy prediction without `solvedAt` | 105 |
| Prediction with `solvedAt + inputHash + solverVersion + modelVersion` | 23 |
| Saved calibrated P20/P50/P80 in that cohort | 23 |
| `solverStatus=valid` in that cohort | 21 |
| `solverStatus=incomplete` | 2 |
| Valid + full coverage | 13 |
| Valid + partial coverage | 7 |
| Valid + unresolved coverage mode | 1 |

The 23-snapshot cohort is homogeneous in declared versions (`modelVersion=v0.5-field-conditions`, `solverVersion=v0.6-reliability`, catalog `2026-08-13`). It is **not** the same version label as the current Overlay generator (`v0.65`). Model versions must never be pooled silently.

The cohort's saved historical reference IDs are encouraging: no target self-reference, no missing history reference, and no same/future-time reference was found. This is necessary but not sufficient provenance.

### Why legacy prediction objects are not formally evaluable

- 105 admitted prediction objects lack `solvedAt`.
- Their model/version/status semantics span several generations.
- The exact fact snapshot and selection moment are absent.
- A later-edited top-level history row cannot prove it still equals the facts used at solve time.
- A saved estimate alone does not identify whether it is structural EV, full Shadow P50, partial conditional P50, or another model layer.

### Why the 23 stronger snapshots are still only candidates

They lack:

- `predictionSnapshotVersion`;
- exact immutable normalized input payload or content-addressed input artifact;
- truthful hash algorithm declaration and collision-resistant hash;
- history/dataset revision and explicit cutoff artifact;
- explicit `informationMode/degradationLevel` field (mode must currently be inferred from `probabilityProfile.coverageRatio`);
- a declared snapshot selection rule (for example, latest valid pre-settlement full-shadow snapshot);
- a settlement observation timestamp and sealed truth evidence.

Partial-coverage Shadow is a conditional distribution over covered states. Its P50 must not be compared to the full-inventory `actualTotal` as though it were a full forecast.

---

## 6. Minimum Prediction Snapshot Contract proposal

### RECOMMENDATION — `prediction-snapshot.v1`

```jsonc
{
  "schemaVersion": "prediction-snapshot.v1",
  "predictionId": "opaque-or-content-addressed-id",
  "matchId": "...",
  "round": 4,
  "snapshotRole": "latest_valid_pre_settlement",
  "solvedAt": "2026-08-21T10:00:00.000Z",
  "informationCutoffAt": "2026-08-21T10:00:00.000Z",
  "producer": {
    "runtime": "overlay_runtime",
    "solverName": "auction_engine_v06",
    "solverVersion": "v0.65",
    "modelVersion": "...",
    "catalogVersion": "...",
    "codeRevision": "..."
  },
  "input": {
    "contractVersion": 1,
    "hashAlgorithm": "sha256",
    "sha256": "...",
    "facts": {},
    "historyRevision": {
      "sourceSha256": "...",
      "cutoffExclusive": "...",
      "eligibleRecordCount": 0,
      "eligibleRecordIdsSha256": "..."
    }
  },
  "mode": {
    "informationMode": "full_shadow",
    "coverageRatio": 1.0,
    "supportedStateCount": 4,
    "totalStateCount": 4
  },
  "status": {
    "solverStatus": "valid",
    "provisional": false,
    "diagnosticOnly": false
  },
  "valueDistribution": {
    "scope": "full_inventory_actual_total",
    "p20": 0,
    "p50": 0,
    "p80": 0
  },
  "structuralValue": {},
  "marketPrediction": {},
  "frozen": true
}
```

Contract rules:

- The stored `input.facts` is a normalized facts-only whitelist, never raw OCR text or mutable `CurrentMatch`.
- Structural quantiles, full Shadow quantiles, partial conditional quantiles, and market-clearing predictions remain separate namespaces and targets.
- Timestamp is not identity; `predictionId` excludes mutable save time.
- The selected snapshot must predate settlement evidence and follow one declared selection policy.
- Full-history replay may be an offline diagnostic, but it cannot retroactively become a frozen production snapshot.

---

## 7. Evaluation eligibility matrix

### Proposed gate sequence

`Historical Dataset`  
→ `History Admission Policy`  
→ `Duplicate Isolation`  
→ `Truth Gate`  
→ `Prediction Snapshot Gate`  
→ `Temporal + Target Compatibility`  
→ `Model/Mode Cohort`  
→ `Evaluation`  
→ `Frozen Summary Artifact`  
→ `MainViewStateProvider`  
→ `Overview / Analysis`

### Matrix

| Condition | Full-value point metrics | Quantile/calibration metrics | Red-tail metrics |
|---|---|---|---|
| History not admitted | Exclude | Exclude | Exclude |
| Truth unknown/unverified | Exclude | Exclude | Exclude |
| High total truth but item ledger incomplete | Eligible after provenance fix | Eligible after provenance fix | Exclude |
| Prediction lacks solved time/input/version | Exclude | Exclude | Exclude |
| Solver incomplete/fallback | Separate diagnostic only | Exclude from formal | Exclude |
| Structural-only | Separate structural diagnostic | No full Shadow quantile metric | Only if a distinct target is defined |
| Partial Shadow | Do not compare conditional P50 to full actual | Separate conditional evaluation only with matching truth scope | Exclude by default |
| Full Shadow + valid + high truth | Candidate after provenance/temporal checks | Candidate after same gates | Needs verified Red truth additionally |
| Mixed solver/model versions | Separate cohorts only | Separate cohorts only | Separate cohorts only |

### Current diagnostic funnel

| Stage | Count |
|---|---:|
| Persisted records | 287 |
| History admitted | 155 |
| High/manual settlement confidence | 39 |
| Stronger saved prediction + high truth | 23 |
| Solver valid | 21 |
| Valid full-coverage candidate | 13 |
| Formally publishable after current contracts | **0** |

This funnel is diagnostic only and is not a Benchmark score or Solver accuracy claim.

---

## 8. Offline Evaluation Pipeline and artifact proposal

### Ownership

- **History producer:** persists facts, lifecycle, truth evidence, and the frozen prediction snapshot reference.
- **Offline evaluator:** sole owner of admission/truth/prediction gates and metric computation. It must not mutate History.
- **Artifact writer:** atomically writes a frozen summary.
- **MainViewStateProvider:** validates artifact version/revision, caches it, and emits presentation-ready primitives only.
- **Main JS:** formats supplied values; it does not join records, filter samples, or calculate metrics.

### Artifact location

Derive the location from the native-resolved canonical data directory, not from a WebView or package asset path:

`<canonical-data-dir>\evaluation\prediction_evaluation_summary_v1.json`

The artifact is generated data and should not be baked into the PyInstaller bundle as an authority. The existing canonical history location itself is currently tied to source/portable distribution resolution; a future writable-data-location migration is a separate risk and must not be silently folded into this work.

### Proposed `prediction-evaluation-summary.v1`

```jsonc
{
  "schemaVersion": "prediction-evaluation-summary.v1",
  "evaluationVersion": 1,
  "metricDefinitionVersion": 1,
  "generatedAt": "...",
  "evaluationId": "...",
  "sourceRevisions": {
    "history": {
      "sourceId": "canonical_match_history",
      "schemaVersion": 6,
      "sha256": "...",
      "recordCount": 287
    }
  },
  "contracts": {
    "historyAdmissionPolicyVersion": 1,
    "truthGateVersion": 1,
    "predictionSnapshotVersion": 1,
    "snapshotSelectionPolicyVersion": 1
  },
  "cohort": {
    "solverVersion": "...",
    "modelVersion": "...",
    "catalogVersion": "...",
    "target": "full_inventory_actual_total",
    "window": {"start": "...", "endExclusive": "...", "timeZone": "Asia/Shanghai"},
    "informationMode": "full_shadow"
  },
  "admission": {
    "candidateN": 0,
    "sampleN": 0,
    "excludedN": 0,
    "exclusionReasonCounts": {}
  },
  "overall": {
    "mae": null,
    "medianAe": null,
    "mape": null,
    "medianApe": null,
    "bias": null,
    "relativeBias": null,
    "p20EmpiricalCoverage": null,
    "p50EmpiricalCoverage": null,
    "p80EmpiricalCoverage": null,
    "p20P80IntervalCoverage": null,
    "underestimateOver10Rate": null,
    "underestimateOver20Rate": null
  },
  "strata": [],
  "interpretation": {
    "ruleVersion": null,
    "status": "NOT_AVAILABLE",
    "reasonCodes": []
  }
}
```

### Stratification rules

- Always split by model/solver version and forecast target.
- Split by `full_shadow / partial_shadow / structural_only`; do not pool them.
- Optional strata (field condition, venue/box, Q bucket, high-value, verified Red-tail) must publish their own `sampleN` and minimum-sample status.
- No daily comparison unless both windows use the same metric definition, model version, target, selection policy, and minimum sample threshold.

### One artifact, two presentation consumers

Overview and Analysis must receive slices derived from the same artifact revision/hash through `MainViewStateProvider`. Overview may show a small approved subset; Analysis may show the full summary and strata. Neither may independently calculate or replay.

---

## 9. Metric readiness and formal semantics

### Status vocabulary

- `READY`: mathematical/business definition can be frozen now.
- `NEEDS_DEFINITION`: a product choice or target/denominator remains ambiguous.
- `NOT_JUSTIFIED`: current evidence cannot support publication, even if a formula is obvious.

**Publication status today:** no prediction-performance metric below may replace the current mock UI because no frozen evaluation artifact exists and the current formally eligible sample is zero.

Let an eligible record have verified full-inventory truth `y_i > 0`, full-shadow forecast quantiles `q_i(0.2), q_i(0.5), q_i(0.8)`, and point forecast `e_i = q_i(0.5)`.

| Metric | Readiness | Proposed definition / denominator | Placement decision |
|---|---|---|---|
| MAE | `READY` definition; `NOT_JUSTIFIED` to publish now | `mean(|e_i-y_i|)` over full-gate eligible records for one model/mode/window. Unit: currency. | Analysis; Overview only after stable N/rubric. |
| Median AE | `READY` definition; `NOT_JUSTIFIED` now | `median(|e_i-y_i|)`, same denominator. | Analysis. |
| Relative error | `NEEDS_DEFINITION` | Decide and name MAPE `mean(|e-y|/y)` versus Median APE. Report both is preferable; never call either generic “accuracy.” | Analysis. |
| Bias | `NEEDS_DEFINITION` | Freeze currency bias `mean(e-y)` and/or relative bias `mean((e-y)/y)`; positive means overestimate. | Analysis. |
| Quantile calibration | `READY` definition; `NOT_JUSTIFIED` now | For alpha in `.2/.5/.8`, empirical coverage `mean(y_i <= q_i(alpha))` versus nominal alpha; also consider pinball loss. | Analysis only. |
| Generic “coverage” | `NEEDS_DEFINITION` | Must split **forecast availability coverage** from **P20-P80 interval coverage**. | Analysis; label explicitly. |
| P20/P50/P80 coverage | `READY` definition; `NOT_JUSTIFIED` now | `Pr(y<=q_alpha)` with all eligible records as denominator. Expected values are near 20/50/80%, not “accuracy.” | Analysis; current “P20/P50/P80 准确率” labels must not receive these values unchanged. |
| P20-P80 interval coverage | `READY` definition; `NOT_JUSTIFIED` now | `mean(q20<=y<=q80)`, nominal 60%. | Analysis. |
| Underestimation error | `NEEDS_DEFINITION` | Choose mean shortfall over all records or severity conditional on `e<y`; publish denominator explicitly. | Analysis. |
| `>10%` underestimation rate | `READY` formula after point-target freeze; `NOT_JUSTIFIED` now | `mean((y-e)/y > .10)` over all eligible point forecasts. | Analysis; possible future Overview risk signal. |
| `>20%` catastrophic underestimation | `READY` formula after point-target freeze; `NOT_JUSTIFIED` now | `mean((y-e)/y > .20)` over all eligible point forecasts. | Analysis. |
| High-value performance | `NEEDS_DEFINITION` | Predeclare value threshold or external segment; never choose threshold after seeing errors. | Analysis only until stable. |
| Red-tail performance | `NOT_JUSTIFIED` | Requires complete verified Red truth/ledger and declared tail target; current ledger verification is zero. | Do not show now. |
| Direction accuracy | `NEEDS_DEFINITION` | No persisted baseline/direction label identifies what “direction” means. | Do not show now. |
| Extreme hit rate `>=P80` | `NEEDS_DEFINITION` | Must choose whether this means tail-event recall, exceedance calibration, or interval hit; denominator/threshold absent. | Do not show now. |
| Grade / `B+` | `NOT_JUSTIFIED` | Requires versioned rubric, metric weights, minimum N, and unavailable-data behavior. | Do not show now. |

### Critical semantic correction

Solver P20/P50/P80 are value-distribution quantiles. They are not three tiers of “prediction accuracy.” Quantile empirical coverage is a calibration diagnostic, and P20-P80 interval coverage has a nominal target of roughly 60%; neither can populate the existing accuracy labels without a UI/metric contract change.

---

## 10. Finance / profit audit

### FACT — admitted field coverage

| Field | Count among 155 admitted |
|---|---:|
| Positive `actualTotal` | 155 |
| Positive `clearingPrice` | 95 |
| Finite `costs.total` | 155 (only 66 positive; zero often means unknown legacy default) |
| Explicit boolean `acquired` | 48 |
| Finite `purchaseSpend` | 30 |
| Finite `realizedProfit` | 16 |

For the 16 rows where actual, clearing, costs, and realizedProfit coexist:

- zero match the Canonical v7 documented formula `actualTotal - clearingPrice - costs.total`;
- 8 match `actualTotal - clearingPrice` (cost ignored);
- 4 match `actualTotal - purchaseSpend` (cost ignored);
- the remaining rows follow other/unclear semantics.

`AutoArchiver` copies upstream settlement `profit`; it also infers acquisition as winner-match **or positive profit**. This cannot serve as an authoritative cross-version finance contract.

### Verdict by finance field

| Field | Product use now |
|---|---|
| `actualTotal` | May be shown as settlement value only after field-specific Truth Gate. |
| `clearingPrice` | May be shown as final clearing fact only when explicitly present and trusted; unknown is not zero. |
| `costs.total` | Historical display with provenance only; zero cannot universally mean verified zero. |
| `purchaseSpend` | `NOT_AVAILABLE_YET` as a complete aggregate. |
| `acquired` | `NOT_AVAILABLE_YET` as a complete aggregate. |
| `realizedProfit` | `NOT_AVAILABLE_YET`. |
| Overview net profit / spend cards | `NOT_AVAILABLE_YET`. |

No Main card should infer profit from incomplete payment/acquisition evidence.

---

## 11. History / Records product boundary

### Minimum History list: trusted facts only

Default list should contain admitted records and presentation-safe summaries:

- normalized local played time plus a legacy-time-assumption badge when applicable;
- lifecycle/admission status;
- venue/box/field condition only when present and normalized;
- verified settlement actual value and clearing price with truth-confidence badge;
- prediction availability, selected snapshot mode, and model version (not a recommendation);
- compact exclusion/data-quality indicators.

Do not show unknown finance values as zero, infer acquisition, or include raw OCR/player/bid data in Main payload.

### Single-match detail boundary

A read-only detail can present three columns/sections:

1. **Observed match facts:** normalized environment/public facts and provenance.
2. **Frozen prediction snapshot:** solve time, round, model/solver/catalog versions, information mode/coverage, P20/P50/P80 target/scope, status, and input/dataset revisions.
3. **Settlement truth:** actual total, clearing, observation/verification method, confidence, evidence availability, and conflict status.

Error values are shown only when the row is evaluation eligible. Otherwise display its exclusion reason, not a misleading error.

### User-visible quality status

- History defaults to admitted records.
- A data-quality filter may expose excluded/DRAFT records without counting them.
- Detail view should show admission status, evaluation eligibility, truth confidence, and reason codes.
- Analysis must show `sampleN`, candidate/excluded counts, reason breakdown, model/mode/window, and artifact revision.

### Page responsibilities

| Page | Responsibility |
|---|---|
| Overview | A few decision-value summaries from admitted history and the same frozen evaluation artifact. |
| Analysis | Formal model performance, calibration, risk metrics, strata, denominators, and provenance. |
| History | Traceable per-match facts, frozen prediction versus truth, and quality/admission reasons. |

History is not the evaluator, Analysis is not a record editor, and Overview is not a second aggregation implementation.

---

## 12. Minimum implementation boundary (not implemented)

### Recommended next cut — `Evaluation Eligibility Contracts v1`

The next single action should **not** be History UI or metric calculation. It should:

1. formalize the existing admission rules as one shared `History Admission Policy v1`;
2. add schema/validators for `Prediction Snapshot v1` and `Settlement Truth Evidence v1`;
3. implement a read-only eligibility scanner that emits counts/reason codes only, with no metrics and no Solver replay;
4. run the 23 strong legacy candidates through that scanner as `legacy_candidate`, preserving formal eligibility at zero until evidence review;
5. ensure new future finalized records can persist the required contracts atomically.

Likely future file scope (names may follow repository style):

- new contract/schema documents for history admission, prediction snapshot, truth evidence, and evaluation summary;
- a pure native/Python admission/eligibility module with no Solver/Vision/OCR/Main imports;
- focused fixtures/tests for mixed schema, timestamp, duplicate, truth, prediction, temporal, mode, and target gates;
- minimal producer integration only in a later, separately approved slice;
- no Main/UI change until a frozen summary artifact exists.

---

## 13. Focused validation and smoke recommendations

### Contract/admission tests

- DRAFT/cancelled/diagnostic/invalid timestamp/duplicate ID exclusions.
- Naive timestamp fixed to `Asia/Shanghai`; aware timestamp conversion.
- probable content duplicate flagged and evaluation-blocked.
- legacy verified compatibility does not auto-promote truth confidence.
- source hash/change and atomic-read behavior.

### Prediction/Truth Gate tests

- missing snapshot version/input payload/hash algorithm/dataset revision fails closed.
- `solvedAt >= settlementObservedAt` fails.
- incomplete/fallback/diagnostic snapshot is excluded or placed in declared diagnostic cohort.
- partial Shadow cannot target full `actualTotal` metrics.
- full Shadow quantiles remain distinct from structural/market predictions.
- unknown truth confidence/evidence mismatch fails.
- Red-tail requires verified complete Red/item evidence.

### Evaluator/artifact tests

- deterministic metrics from fixed fixtures; one denominator per declared cohort.
- no future/self history references.
- model versions never pool.
- exact reason breakdown sums to candidate population.
- artifact is schema-valid, atomically written, and hash/revision reproducible.
- evaluator does not mutate History or import/call production Solver for missing snapshots.
- Overview and Analysis provider slices cite the identical artifact revision.

### Source smoke

- Load a small fixture, produce eligibility summary, then a frozen summary from pre-frozen snapshots.
- Confirm Main receives only whitelist scalar/aggregate payloads and no raw record/ID/prediction/evidence object.
- Confirm the existing match-count result remains unchanged.

### Packaged smoke

- Fresh build starts without a summary artifact and honestly reports `NOT_AVAILABLE_YET`.
- With a valid external artifact beside the canonical data directory, it is read/cached without Solver replay.
- Corrupt/schema-mismatched/source-hash-mismatched artifacts fail closed.
- No large raw history payload crosses WebView2; no lingering process on shutdown.
- The evaluation artifact is not treated as a bundled immutable product asset or second history SOT.

---

## 14. Risk register

| Risk | Severity | Control |
|---|---|---|
| Mixed schema and no finalized v7 producer | High | Contract-first producer/admission work. |
| `verified` inflated by legacy normalization | High | Separate Truth Gate with evidence/version. |
| Prediction input not reproducible | High | Exact normalized input artifact + real SHA-256. |
| Hash labeled `sha1` but implemented as 32-bit fast hash | High | Versioned algorithm field; do not reinterpret legacy hash. |
| Missing snapshot-selection moment | High | Freeze `snapshotRole` and temporal rule. |
| Partial/full/structural target mixing | High | Mode/target-specific cohorts. |
| Evaluation leakage from shared historical dataset | High | Freeze source revision/cutoff and allowed-ID digest; strict temporal tests. |
| Small full-valid candidate cohort (`n=13`) | High | No product score; minimum-N policy and uncertainty. |
| Probable content duplicate | Medium | Flag and exclude from evaluation pending review. |
| Finance semantics conflict | High | Keep profit/spend unavailable until finance contract. |
| Package data path doubles as writable history location | Medium | Future explicit writable data-root decision; do not mix into this slice. |
| Main mock labels imply quantile “accuracy” | High | Keep mock disclaimer; future metric/UI contract must relabel. |

---

## 15. Final decision

### Core facts

- Persisted history is top-level schema 6 with 287 mixed records; Canonical v7 finalized history is not yet the active producer format.
- Current History admission is stable at 155; 132 are excluded, principally 107 DRAFTs and 21 undated rows.
- There are 23 strong prediction/truth candidates, but only 13 are valid full-coverage candidates and none meets the complete future provenance contract today.
- Current finance fields are semantically inconsistent and cannot support profit/spend cards.

### Metrics legal today

- Real admitted match count and its dated count series.
- Field-specific History facts only when their trust gate passes.
- No production Prediction Performance metric is legal today.

### Final verdict

`READY_AFTER_CONTRACT_FIX`

History can proceed after one shared admission contract. Formal Prediction Evaluation remains `BLOCKED_BY_DATA_PROVENANCE` until the versioned Prediction Snapshot and Truth Evidence contracts are persisted and a frozen offline summary artifact exists.

**Recommended next cut:** `Evaluation Eligibility Contracts v1` — contracts, validators, and a reason-count-only scanner; no metrics, no UI, no replay.
