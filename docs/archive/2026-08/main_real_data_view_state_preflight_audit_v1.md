# Main Real Data View-State Preflight Audit v1

**Checkpoint:** `6c0d164eff016cc5ad4ef75a7898967e9c129825`  
**Audit date:** 2026-08-21 (Asia/Shanghai)  
**Mode:** read-only preflight; no UI, Solver, CurrentMatch, Vision/OCR, History page, or bridge changes were made.

## Executive verdict

`PARTIAL_BINDING_ONLY`

The native Main host already owns a safe, scalar-only runtime snapshot and can reuse the existing `request_app_status` / `app_status` channel. The persisted canonical history also contains enough evidence to build a first read-only Overview aggregate, but it is a mixed schema-6/legacy dataset whose finalization, timestamp, finance, and prediction provenance are not uniform. It must pass a Main-specific admission/normalization layer before any values are shown.

The Prediction Performance page is **not ready for real binding**. No persisted, versioned production evaluation summary exists. The Lab can compute diagnostics, but it may replay Solver logic and is an experimental browser runtime; Benchmark v1 is explicitly `NOT_VALID_FOR_MODEL_ACCURACY`, while Benchmark v2 currently establishes geometry/provenance rather than prediction truth. All Analysis metrics therefore remain `NOT_AVAILABLE_YET`.

**Recommended next slice:** create a native-owned `MainViewStateProvider` and bind only the complete **“今日对局数” card** (today value, yesterday comparison, and its count series) from admitted persisted records. Keep the other five Overview cards and all Analysis metrics explicitly unavailable/mock until their semantics and evidence gates exist.

---

## 1. Audit boundaries and decision vocabulary

### FACT

Main remains a presentation consumer. The Overlay WebView remains the only production Solver runtime. The following are outside the Main data boundary:

- mutable `CurrentMatch`;
- raw `LATEST_PAYLOAD` or any live WebSocket payload object;
- OCR/Vision raw outputs;
- bids, auction facts, settlement item facts, or Solver recommendations;
- mutable history/runtime dictionaries or arrays;
- invoking or replaying `auction_engine_v06.js`, `solver_core_v06.js`, or Lab Solver functions.

### Status terms used below

- `AVAILABLE`: definition and reliable read-only source both exist.
- `BINDABLE_AFTER_MINIMAL_GATE`: source evidence exists, but a small admission/normalization contract is still required.
- `NOT_AVAILABLE_YET`: the metric definition, trustworthy evidence, or versioned aggregate artifact is missing.
- `FORBIDDEN_SOURCE`: data may exist upstream but may not cross the Main presentation boundary.

---

## 2. Current Main implementation and mock inventory

### FACT — Current bridge and runtime

- `core/main_window.js` defines both `mockDashboardState` and `mockPredictionPerformanceState` and renders them locally.
- Main polls `request_app_status` every 750 ms and consumes `app_status`.
- `app/main_window.py::MainWindowBridge.ALLOWED_ACTIONS` is exactly:
  - `toggle_overlay`
  - `get_overlay_visibility`
  - `request_app_status`
- `app/presentation_runtime.py` provides a frozen `PresentationRuntimeSnapshot` containing only:
  - `snapshotVersion`
  - `visionProcessState`
  - `refreshPending`
  - `sceneClass`
  - `shadowUpdating`
- `app_status` additionally contains native-owned `applicationState` and `overlayVisible` scalars.
- `presentationData` is still explicitly set to `mock`.

### FACT — Overview six-card mock fields

| UI field | Current mock value | Current mock comparison | Current chart fixture |
|---|---:|---|---|
| 今日对局数 | `18` | `较昨日 +5` | 12 fixed bars: `38,66,44,78,35,58,86,31,54,76,42,67` |
| 今日总价值 | `26.17 W` | `+6.32 W (+31.8%)` | 14 fixed SVG y-points: `37,31,33,23,28,18,26,31,24,28,19,18,10,4` |
| 平均每局 | `1.45 W` | `+0.18 W` | 14 fixed SVG y-points: `36,29,30,22,17,20,29,25,31,26,18,23,15,7` |
| 最高单局 | `5.42 W` | `+1.02 W` | 12 fixed bars: `73,36,61,55,68,89,47,66,39,31,82,44` |
| 净收益 | `+8.73 W` | `+3.21 W` | 14 fixed SVG y-points: `35,30,33,26,31,27,33,25,29,20,22,14,11,3` |
| 消耗 | `17.44 W` | `+3.11 W` | 12 fixed bars: `64,40,52,35,70,33,51,42,76,48,81,57` |

The chart fixtures have no timestamps, units, or source provenance. They are visual mock coordinates, not historical values.

### FACT — Overview performance-strip mock fields

| UI field | Current mock |
|---|---|
| P20 / P50 / P80 “准确度” | `68% / 56% / 44%` |
| 整体误差 MAE | `2,420`; `较昨日 -13.6%` |
| 方向准确率 | `71%`; `较昨日 +5%` |
| 极端命中率 ≥P80 | `31%`; `较昨日 -1%` |
| 综合评分 | `B+`; `较昨日 升级 ↑` |

### FACT — Prediction Performance page mock fields

| UI field | Current mock |
|---|---|
| P20 准确率 | `68%`; `较昨天 +6%` |
| P50 准确率 | `56%`; `较昨天 +3%` |
| P80 准确率 | `44%`; `较昨天 -2%` |
| 整体误差 MAE | `2,420`; `较昨天 -380 (↓13.6%)` |
| 方向准确率 / gauge | `71%`; `较昨天 +5%` |
| 极端命中率 ≥P80 | `31%`; `较昨天 -1%` |
| 综合评分 badge | `B+`; `较昨天 升级 ↑` |
| 解读 | `P20 表现优秀，P50 一般，P80 偏弱，今天整体比昨天略好。` |

The Overview performance strip and Analysis page are two visual consumers of the same conceptual metric family. They must eventually consume one evaluation summary; they must not compute separate values.

---

## 3. Existing read-only source inventory

| Candidate source | Current owner | Exists | What it contains | Reliability for Main | Main decision |
|---|---|---:|---|---|---|
| `异环拍卖数据.json` | persisted product history; written by AutoArchiver and legacy/manual tooling | Yes | schema-6/legacy match records, settlement values, costs, some frozen predictions | Mixed; usable only through explicit admission and normalization | Allowed through a new provider; never expose raw records |
| `core/auto_archiver.py` output | Vision worker archive path | Yes | newly archived settlement records and drafts | Persisted/atomic writes, but finalization and finance semantics are not fully canonical | Input evidence only; provider must not trust every field blindly |
| `core/live_shadow.py` in-memory snapshot | Vision/Shadow worker | Yes | full mutable history list and derived Shadow state | Solver-oriented, process-local, mutable, and not a Main presentation contract | `FORBIDDEN_SOURCE` for Main |
| Archived `record.prediction` | mixed record producers; sometimes frozen Overlay prediction | Partial | estimate and, on some records, probability profile | provenance/version coverage is incomplete | Not directly consumable by Main; future evaluation pipeline input only |
| `lab/index.html` evaluation functions | experimental Lab browser runtime | Yes | MAE, APE, P20–P80 coverage, walk-forward and finance diagnostics | useful definitions, but may replay Solver and is not a frozen product artifact | Definition/reference only; Main must not call it |
| Benchmark v1 | experiment artifacts | Yes | GPT/Gemini comparisons and crop QA | explicitly not valid for model accuracy | Forbidden as production performance source |
| Benchmark v2 | experiment geometry/provenance track | Yes | validated source/proposal/geometry admission | no production prediction accuracy truth | Not a performance source |
| `PresentationRuntimeSnapshot` | native/Python host | Yes | five sanitized runtime scalars | reliable for presentation status | `AVAILABLE` |
| `applicationState`, `overlayVisible` | native Main lifecycle/overlay controller | Yes | app lifecycle and Overlay visibility | reliable for presentation status | `AVAILABLE` |

### FACT — Current historical dataset evidence

Read-only inspection of `异环拍卖数据.json` at this checkpoint found:

| Evidence | Count |
|---|---:|
| Records | `285` |
| `lifecycleStatus == DRAFT` | `105` |
| Missing `lifecycleStatus` | `180` |
| Non-null `actualTotal` | `176` |
| Non-null `clearingPrice` | `96` |
| Non-null `purchaseSpend` | `30` |
| Non-null `acquired`/`isAcquired` | `48` |
| Non-null `realizedProfit` | `16` |
| `costs.total` present | `180` |
| Non-null prediction object | `132` |
| Prediction with complete `probabilityProfile.shadowWhole` P20/P50/P80 | `63` |
| Prediction with `rawShadow` P20/P50/P80 | `0` |
| Prediction with `solvedAt` | `23` |
| Prediction with `inputHash` | `23` |
| Nested settlement `verified` | `171` |
| Nested settlement `pending` | `4` |
| Nested settlement truth confidence `high` | `39` |
| Nested settlement truth confidence `unknown` | `136` |

For the current local day, the file contains two records, both `DRAFT`, with no `actualTotal`. A safe finalized/verified view must therefore show zero/no data rather than the current mock numbers.

### FACT — Data-quality constraints that affect aggregation

1. `AutoArchiver.archive_match()` persists settlement records without writing `lifecycleStatus: FINALIZED`; drafts do explicitly write `DRAFT`.
2. The database mixes legacy, calculator, manual, screenshot-batch, user, and auto-archive producers.
3. Most `playedAt` values are timezone-naive. A Main day boundary must explicitly adopt `Asia/Shanghai` for legacy naive timestamps rather than silently inheriting machine locale.
4. AutoArchiver copies incoming `settlement.profit` into `realizedProfit`; it does not recompute the v7 formula `actualTotal - clearingPrice - costs.total`.
5. AutoArchiver infers acquisition using `(winner == myName) OR (profit > 0)`. This is not strong enough to make `acquired` a universal finance truth across the mixed dataset.
6. The observed persisted data includes highly implausible clearing values that are not marked diagnostic. A raw sum is not a product-grade aggregate.
7. `core/auction_engine_v06.js` has its own Solver-history eligibility rules. Those rules are for modeling, not a declared Main dashboard record-admission contract, and must not be reused silently.

### INFERENCE

The history file is a valid evidence source, but not yet a presentation-ready source. The provider must establish a versioned admission policy, normalize legacy timestamps, exclude drafts/cancelled/diagnostic records, require settlement evidence appropriate to each metric, and report exclusion/sample counts. It must not treat mere field presence as reliability.

---

## 4. Overview field-by-field source decisions

| UI field | Recommended real source / source owner | Exists | Reliable now | Aggregate needed | Allowed into Main | Refresh | Minimal gap |
|---|---|---:|---|---:|---|---|---|
| 今日对局数 | admitted persisted records from `异环拍卖数据.json`; owner: future native `MainViewStateProvider` | Yes | Conditional | local-day count | `BINDABLE_AFTER_MINIMAL_GATE` | pull, cached by history revision | formal record admission, local-day rule, duplicate/id policy |
| 今日总价值 | sum of admitted, verified `actualTotal`; history owner + provider | Yes (`176` non-null) | Conditional | sum | `BINDABLE_AFTER_MINIMAL_GATE`, only if label is defined as **结算总价值**, not prediction “估值” | pull/cached | value semantics, truth-confidence gate, outlier policy |
| 平均每局 | admitted verified `actualTotal` / eligible match count | Yes | Conditional | mean | `BINDABLE_AFTER_MINIMAL_GATE` under the same settlement-value definition | pull/cached | same gates; zero-sample behavior |
| 最高单局 | max admitted verified `actualTotal` | Yes | Conditional | max | `BINDABLE_AFTER_MINIMAL_GATE` under the same settlement-value definition | pull/cached | same gates; outlier policy |
| 净收益 | normalized acquired/payment/value/cost facts, not raw `realizedProfit` | Insufficient | No | finance ledger sum | `NOT_AVAILABLE_YET` | future pull/static aggregate | authoritative acquisition/payment/cost semantics and coverage; versioned finance policy |
| 消耗 | explicit product definition, then normalized `costs.total` and possibly `purchaseSpend` | Ambiguous | No | finance ledger sum | `NOT_AVAILABLE_YET` | future pull/static aggregate | decide whether “消耗” means operating costs, purchase spend, or both; complete evidence |

### Companion fields: yesterday comparison and mini charts

| Companion UI field | Decision |
|---|---|
| “较昨日” for match count | `BINDABLE_AFTER_MINIMAL_GATE`; compute today/previous local-day count from the same admitted set |
| Match-count mini chart | `BINDABLE_AFTER_MINIMAL_GATE`; provider returns dated count points, JS only normalizes their visual height |
| “较昨日” for total/average/max | Inherits the corresponding value metric's gate; must include previous-day sample count and distinguish no data from zero |
| Total/average/max mini charts | Inherit the corresponding value metric's gate; no anonymous fixed SVG coordinates |
| “较昨日” and charts for profit/cost | `NOT_AVAILABLE_YET` because the base finance metrics are unavailable |

### RECOMMENDATION — Overview semantics

- Define “今日总价值 / 平均每局 / 最高单局” as **verified settlement actual value** if they are bound from history.
- Do not keep the auxiliary label “估值” when displaying actual settlement truth; that would be a semantic misrepresentation.
- Do not infer player profit from `actualTotal - cost` without authoritative acquisition and payment evidence.
- Do not coerce unknown finance values to zero.

---

## 5. Prediction Performance field-by-field source decisions

| UI field | Candidate source | Exists | Reliable | Aggregate / definition needed | Main decision | Refresh | Minimal gap |
|---|---|---:|---:|---|---|---|---|
| P20 accuracy | future frozen production evaluation summary | No | No | a formally defined quantile metric, window, denominator, model version | `NOT_AVAILABLE_YET` | future static/cached artifact | metric definition + evaluation pipeline |
| P50 accuracy | future frozen production evaluation summary | No | No | definition (not merely “percentage close”), sample gate, model version | `NOT_AVAILABLE_YET` | future static/cached artifact | metric definition + evaluation pipeline |
| P80 accuracy | future frozen production evaluation summary | No | No | formal quantile/tail metric and denominator | `NOT_AVAILABLE_YET` | future static/cached artifact | metric definition + evaluation pipeline |
| MAE | future evaluation summary derived from frozen prediction P50/estimate and verified actual | Inputs partial; summary absent | No | strict frozen-prediction join, absolute error, sample/provenance gate | `NOT_AVAILABLE_YET` | future static/cached artifact | offline evaluator; no Main Solver replay |
| Direction accuracy | future evaluation summary | No | No | define “direction” and its baseline/label | `NOT_AVAILABLE_YET` | future static/cached artifact | product metric definition + labels |
| Extreme hit rate ≥P80 | future evaluation summary | No | No | define whether this is exceedance, recall, or calibration; declare denominator | `NOT_AVAILABLE_YET` | future static/cached artifact | product metric definition + labels |
| Grade / badge | future rubric applied to a validated summary | No | No | versioned grade thresholds and minimum sample rule | `NOT_AVAILABLE_YET` | future static/cached artifact | approved scoring rubric |
| Interpretation | future deterministic interpretation of available metrics | No | No | versioned rules; must cite metric/sample state | `NOT_AVAILABLE_YET` | same as evaluation summary | validated metrics + interpretation rules |
| All “较昨天” deltas | two comparable versioned evaluation windows | No | No | same model/metric version, day window, minimum sample | `NOT_AVAILABLE_YET` | future static/cached artifact | daily evaluation snapshots |

### FACT — Why saved predictions are not enough

- P20/P50/P80 are value quantiles/range estimates. They are not inherently three “accuracy percentages.”
- Only 63/285 records contain a complete saved `probabilityProfile.shadowWhole` range, and only 23 include `solvedAt` plus `inputHash`.
- A raw MAE over whichever records happen to have an estimate would mix solver versions, provenance levels, and settlement confidence.
- Lab diagnostics explicitly distinguish saved snapshots from strict temporal replay. Replaying missing predictions inside Main would make Main a Solver caller and violate the architecture.
- Experimental P20–P80 coverage is not equivalent to three P20/P50/P80 accuracy percentages, direction accuracy, or “extreme hit rate.”

### FACT — Benchmark exclusion

- Benchmark v1's contract audit states item identity accuracy, quality accuracy, and Red detection are `NOT_VALID_FOR_MODEL_ACCURACY`.
- Benchmark v2's frozen geometry track validates source/proposal/parent/crop provenance, not prediction-performance truth.

### RECOMMENDATION

The future owner of these fields should be a separate, offline/versioned **Prediction Evaluation Pipeline** that writes a frozen summary artifact. `MainViewStateProvider` may read only that artifact's scalar summary; it must not read raw predictions and calculate/replay Solver outcomes on demand.

---

## 6. Proposed Main Read-only View-State Contract v1

### Ownership model

**RECOMMENDATION** — Add a native/Python-side `MainViewStateProvider` as the only owner of Main business presentation snapshots.

It should:

1. receive the already resolved canonical history path from the native host;
2. read an atomically persisted file snapshot, never `live_shadow.current_snapshot()`;
3. normalize/admit/aggregate records in private local objects;
4. discard raw records after aggregation;
5. return a frozen snapshot object;
6. serialize to a fresh JSON-safe object containing whitelist primitives only;
7. cache by source revision (`mtime_ns`/size, then SHA-256 on change) so the 750 ms status poll never reparses 34 MB continuously;
8. never import or invoke Solver, Lab, Vision, OCR, or CurrentMatch code.

### Proposed schema

```json
{
  "mainViewStateVersion": 1,
  "generatedAt": "2026-08-21T18:00:00+08:00",
  "timeZone": "Asia/Shanghai",
  "sourceRevisions": {
    "history": {
      "sourceId": "canonical_match_history",
      "schemaVersion": 6,
      "sha256": "<hex>",
      "recordCount": 285,
      "admissionPolicyVersion": 1
    },
    "predictionEvaluation": null
  },
  "overview": {
    "window": {
      "kind": "local_day",
      "start": "2026-08-21T00:00:00+08:00",
      "endExclusive": "2026-08-22T00:00:00+08:00",
      "comparisonStart": "2026-08-20T00:00:00+08:00"
    },
    "metrics": {
      "matchCount": {
        "availability": "AVAILABLE",
        "value": 0,
        "unit": "match",
        "sampleN": 0,
        "excludedN": 2,
        "comparison": {
          "availability": "AVAILABLE",
          "previousValue": 0,
          "absoluteDelta": 0,
          "relativeDelta": null
        },
        "series": [
          {"date": "2026-08-21", "value": 0}
        ],
        "reasonCodes": []
      },
      "totalSettlementValue": {
        "availability": "NOT_AVAILABLE_YET",
        "value": null,
        "unit": "currency",
        "sampleN": 0,
        "comparison": null,
        "series": [],
        "reasonCodes": ["VALUE_SEMANTICS_NOT_APPROVED"]
      },
      "averageSettlementValue": {
        "availability": "NOT_AVAILABLE_YET",
        "value": null,
        "unit": "currency",
        "sampleN": 0,
        "comparison": null,
        "series": [],
        "reasonCodes": ["VALUE_SEMANTICS_NOT_APPROVED"]
      },
      "maximumSettlementValue": {
        "availability": "NOT_AVAILABLE_YET",
        "value": null,
        "unit": "currency",
        "sampleN": 0,
        "comparison": null,
        "series": [],
        "reasonCodes": ["VALUE_SEMANTICS_NOT_APPROVED"]
      },
      "netProfit": {
        "availability": "NOT_AVAILABLE_YET",
        "value": null,
        "unit": "currency",
        "sampleN": 0,
        "comparison": null,
        "series": [],
        "reasonCodes": ["FINANCE_TRUTH_INCOMPLETE"]
      },
      "spend": {
        "availability": "NOT_AVAILABLE_YET",
        "value": null,
        "unit": "currency",
        "sampleN": 0,
        "comparison": null,
        "series": [],
        "reasonCodes": ["SPEND_SEMANTICS_UNDEFINED"]
      }
    }
  },
  "predictionPerformance": {
    "availability": "NOT_AVAILABLE_YET",
    "evaluationVersion": null,
    "modelVersion": null,
    "window": null,
    "sampleN": 0,
    "metrics": {
      "p20Accuracy": null,
      "p50Accuracy": null,
      "p80Accuracy": null,
      "mae": null,
      "directionAccuracy": null,
      "extremeHitRate": null,
      "grade": null
    },
    "interpretation": null,
    "reasonCodes": ["PRODUCTION_EVALUATION_ARTIFACT_MISSING"]
  },
  "runtime": {
    "applicationState": "ready",
    "overlayVisible": true,
    "presentationRuntime": {
      "snapshotVersion": 1,
      "visionProcessState": "running",
      "refreshPending": false,
      "sceneClass": "unknown",
      "shadowUpdating": false
    }
  }
}
```

The values above illustrate shape and honest availability behavior; they are not a new persisted dataset.

### Immutability and whitelist rules

The provider may emit only:

- numbers, booleans, short enums, dates, units, sample/exclusion counts, reason codes;
- dated aggregate points, never individual record IDs or records;
- source schema/version/hash metadata;
- the existing sanitized runtime scalars.

It must never emit:

- records, settlement items, bids, OCR strings, player names, or screenshots;
- `prediction`, `solverInput`, Solver result/recommendation, or replay outputs;
- `CurrentMatch`, `LATEST_PAYLOAD`, worker snapshots, or references to mutable dictionaries/lists;
- HTML fragments. Main JS should format escaped scalar values rather than accepting host-supplied HTML.

### Refresh model

| Section | Recommended refresh |
|---|---|
| Runtime | existing `request_app_status` pull / existing native status push |
| Overview history aggregate | cached pull; cheap file revision check on status request, recompute only after atomic history replacement |
| Prediction performance | static/cached by future evaluation artifact revision |

The existing bridge action surface can remain unchanged. `app_status` can add one `mainViewState` object. The current 750 ms poll must retrieve a cached snapshot, not perform disk parsing or evaluation on every poll.

---

## 7. Direct answers

### 1. Which Overview fields can use real data today?

- **Safest first candidate:** 今日对局数, after a versioned record-admission and Asia/Shanghai day-boundary gate.
- **Evidence exists but semantics must be approved first:** 今日总价值、平均每局、最高单局, if explicitly defined as verified **settlement actual value** rather than “估值.”
- **Not available:** 净收益、消耗.
- All yesterday deltas and charts inherit the availability of their base metric.

### 2. Which Analysis fields can use real data today?

None. All P20/P50/P80 accuracy, MAE, direction accuracy, extreme hit rate, grade, interpretation, and daily deltas are `NOT_AVAILABLE_YET`.

### 3. Which fields must wait for History/Records?

- A History/Records admission contract is required for every Overview business aggregate.
- Profit/spend additionally require authoritative acquisition, payment, and cost truth, not just a History page UI.
- The History page itself is not required for the provider; the persisted record contract is.

### 4. Which fields must wait for a formal prediction evaluation pipeline?

All Analysis fields and the Overview performance strip.

### 5. Can `request_app_status` / `app_status` be reused?

Yes. Add `mainViewState` to the existing response/push payload; do not add a bridge action. Keep the provider cached and preserve the existing runtime correlation/lifecycle behavior.

### 6. Should there be a separate `MainViewStateProvider`?

Yes. `PresentationRuntimeState` should stay a small runtime reducer. Business-history aggregation has different source ownership, caching, quality gates, and refresh cadence and should not be folded into it.

### 7. What is the minimal implementation slice?

1. Add a pure, native-owned record-admission/normalization policy v1.
2. Add a cached immutable `MainViewStateProvider` reading the resolved canonical history file.
3. Expose only the “今日对局数” card's value, yesterday comparison, sample/exclusion counts, and dated count series through existing `app_status`.
4. Keep the other five cards and all Analysis metrics explicitly mock/unavailable; do not mix mock finance/performance values into a card labeled as real.
5. Test that no Solver/CurrentMatch/worker/raw-record field is importable or serialized through the provider.

---

## 8. Final recommendation

**Verdict:** `PARTIAL_BINDING_ONLY`

The next cut should be **one read-only match-count card backed by a new `MainViewStateProvider` and an explicit admission policy**. Do not bind finance or prediction-performance values in the same cut. This establishes the native immutable View-State boundary with the smallest honest real-data surface and without moving Solver authority or exposing mutable runtime state.
