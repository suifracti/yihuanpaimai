# Shadow Distribution Reproducibility / Control-Group Audit v1.2

## Verdict

**Global primary: `INSUFFICIENT_EVIDENCE`**

Production implementation remains prohibited. Cohorts are pre-registered as `EXPLORATORY_SUBGROUP`.

## FACT — v1.1 B1 conflict

Fresh rerun is deterministic. `report.md` was stale relative to `results.json` and the committed harness. Under the actual authority, B1-R and B1-G change quantiles and AB is not equal to A1.

| v1.1 model | P20 pinball | P50 pinball | P80 pinball | Avg pinball | Winkler | Central60 |
|---|---:|---:|---:|---:|---:|---:|
| B0 | 35934.74 | 57029.42 | 51833.09 | 48265.75 | 438839.12 | 27.08% |
| A1 | 34428.47 | 57029.42 | 47700.89 | 46386.26 | 410646.79 | 41.67% |
| B1_R | 38419.01 | 57029.42 | 44196.78 | 46548.40 | 413078.95 | 22.92% |
| B1_G | 36044.81 | 57029.42 | 49486.45 | 47520.23 | 427656.31 | 16.67% |
| AB | 34657.48 | 57029.42 | 46192.44 | 45959.78 | 404249.56 | 45.83% |

Quantile equality audit: `{"B1_R_equals_B0": false, "B1_G_equals_B0": false, "AB_equals_A1": false}`.

## Control matrix

- `B0_PRODUCTION_SAVED`: saved production `shadowWhole` quantiles; no reconstruction.
- `A0_RECONSTRUCTION_NO_NON_RED_VARIANCE`: the candidate reconstruction path with fixed non-red values repeated to the same seven-point support shape.
- `RN_NULL_MATCHED_VARIANCE`: the A0 path plus deterministic training-fold null dispersion, with no catalog/business structure.
- `A1_PROXY_GAUSSIAN_CV`: the A0 path plus the existing training-fold Gaussian/CV proxy.
- `A1_CATALOG_DISCRETE`: the A0 path plus version-selected production rule-price supports and deterministic discrete convolution.
- All reconstructed candidates share folds, weighting, normalization, seven support points per state, quantile interpolation, and an exact saved-B0 P50 anchor.

## Pre-registered Gate 1

`A0 ≈ B0` requires the paired-bootstrap 95% CI for both mean Winkler and mean average-pinball deltas to lie wholly inside ±2% of the corresponding B0 score. A CI wholly outside that margin is a material reconstruction difference. Anything between is inconclusive.

Result: reconstruction status `INCONCLUSIVE`; equivalence established `False`; audit `{"winkler": {"absoluteMargin": 8776.7824, "bootstrap95CiWithinMargin": false, "materiallyDifferent": false}, "averagePinball": {"absoluteMargin": 965.315, "bootstrap95CiWithinMargin": false, "materiallyDifferent": false}}`.

## Global OOS metrics (N=48)

| Model | P20 pinball | P50 pinball | P80 pinball | Avg pinball | Winkler | F(P20) | F(P50) | F(P80) | Central60 | Median norm span | P50 MAE | P50 MARE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0_PRODUCTION_SAVED | 35934.74 | 57029.42 | 51833.09 | 48265.75 | 438839.12 | 31.25% | 45.83% | 58.33% | 27.08% [0.1657, 0.41] | 15.76% | 114058.84 | 26.50% |
| A0_RECONSTRUCTION_NO_NON_RED_VARIANCE | 37456.57 | 57029.42 | 47858.39 | 47448.12 | 426574.79 | 37.50% | 45.83% | 58.33% | 20.83% [0.1173, 0.3426] | 17.96% | 114058.84 | 26.50% |
| RN_NULL_MATCHED_VARIANCE | 34588.16 | 57029.42 | 48189.76 | 46602.45 | 413889.65 | 25.00% | 45.83% | 68.75% | 43.75% [0.307, 0.5773] | 22.32% | 114058.84 | 26.50% |
| A1_PROXY_GAUSSIAN_CV | 34428.47 | 57029.42 | 47700.89 | 46386.26 | 410646.79 | 25.00% | 45.83% | 66.67% | 41.67% [0.2885, 0.5572] | 24.19% | 114058.84 | 26.50% |
| A1_CATALOG_DISCRETE | 41054.72 | 57029.42 | 47632.67 | 48572.27 | 443436.93 | 8.33% | 45.83% | 87.50% | 79.17% [0.6574, 0.8827] | 67.22% | 114058.84 | 26.50% |

## Paired inference

Deltas are candidate minus reference; negative is better.

### A0_vs_B0

- winkler: mean -12264.33; median 0.00; 95% CI [-65837.2367, 37878.8194]; P(delta<0)=0.674; sign-flip p=0.658; max-record share=11.85%.
- averagePinball: mean -817.62; median 0.00; 95% CI [-4394.6995, 2488.9137]; P(delta<0)=0.672; sign-flip p=0.646; max-record share=11.85%.
- pinball80: mean -3974.70; median 0.00; 95% CI [-12613.4198, 3407.5125]; P(delta<0)=0.833; sign-flip p=0.367; max-record share=19.35%.

### A1_PROXY_vs_A0

- winkler: mean -15928.00; median 6014.13; 95% CI [-43921.1016, 10663.5352]; P(delta<0)=0.874; sign-flip p=0.261; max-record share=9.12%.
- averagePinball: mean -1061.87; median 400.94; 95% CI [-2899.6344, 677.6762]; P(delta<0)=0.880; sign-flip p=0.247; max-record share=9.12%.
- pinball80: mean -157.50; median 50.62; 95% CI [-2769.2008, 2484.0502]; P(delta<0)=0.541; sign-flip p=0.909; max-record share=8.00%.

### A1_PROXY_vs_RN

- winkler: mean -3242.86; median 314.58; 95% CI [-22378.3388, 13572.3087]; P(delta<0)=0.617; sign-flip p=0.761; max-record share=17.69%.
- averagePinball: mean -216.19; median 20.97; 95% CI [-1523.2792, 898.3921]; P(delta<0)=0.621; sign-flip p=0.759; max-record share=17.69%.
- pinball80: mean -488.87; median 224.86; 95% CI [-3449.541, 1995.0151]; P(delta<0)=0.620; sign-flip p=0.775; max-record share=20.71%.

### A1_CATALOG_vs_A0

- winkler: mean 16862.15; median 96469.14; 95% CI [-52192.8054, 82307.5577]; P(delta<0)=0.307; sign-flip p=0.628; max-record share=8.77%.
- averagePinball: mean 1124.14; median 6431.28; 95% CI [-3524.9859, 5363.8726]; P(delta<0)=0.311; sign-flip p=0.632; max-record share=8.77%.
- pinball80: mean -225.71; median 15467.47; 95% CI [-13805.6039, 11727.7576]; P(delta<0)=0.496; sign-flip p=0.974; max-record share=12.01%.

### A1_CATALOG_vs_RN

- winkler: mean 29547.29; median 115057.35; 95% CI [-35354.4213, 91171.1268]; P(delta<0)=0.175; sign-flip p=0.377; max-record share=6.92%.
- averagePinball: mean 1969.82; median 7670.49; 95% CI [-2452.0812, 5950.2975]; P(delta<0)=0.178; sign-flip p=0.373; max-record share=6.92%.
- pinball80: mean -557.09; median 17366.12; 95% CI [-14040.0924, 11555.2439]; P(delta<0)=0.517; sign-flip p=0.931; max-record share=9.26%.

## Exploratory historical cohorts

These subgroup diagnostics are pre-registered as exploratory and cannot override the Global verdict.

- `v0.3-dynamic-walkforward`: N=35; diagnostic `INSUFFICIENT_EVIDENCE`; interpretation `EXPLORATORY_SUBGROUP`.
- `v0.5-field-conditions`: N=28; diagnostic `INSUFFICIENT_EVIDENCE`; interpretation `EXPLORATORY_SUBGROUP`.
- `v0.6-reliability`: N=15; diagnostic `INSUFFICIENT_EVIDENCE`; interpretation `EXPLORATORY_SUBGROUP`.

## Zero-span diagnosis

- Total: 17
- Non-exclusive root causes: `{"NON_RED_UNCERTAINTY_GENUINELY_EXISTS": 17, "RECONSTRUCTION_ARTIFACT": 4, "RED_SAMPLE_SCARCITY": 7}`
- `RED_SAMPLE_SCARCITY`: 7 (41.18%)

## A1-CATALOG provenance and limitations

- Source: `core/solver_core_v06.js` @ `1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f`.
- Uses version-selected static discrete prices and deterministic bounded convolution; no Gaussian assumption.
- Venue/box item probabilities do not have an authoritative table and are not invented; equal item weights make this control provisional.

## Leakage audit

`{"status": "PASS", "chronologicalWalkForward": true, "testActualTotalUsedOnlyForScoring": true, "testSettlementItemsUsedForPrediction": false, "futureRecordsUsedForPrediction": false, "catalogIsStaticExAnteRuleData": true, "proxyHyperparameterLearnedFromTrainingFoldOnly": true, "nullScalePoolLearnedFromTrainingFoldOnly": true, "catalogVersionSelectedByPlayedAt": true}`

## Interpretation

- Reconstruction confound status: `INCONCLUSIVE` (equivalence not established is not treated as no confound).
- Proxy beats random widening: `False`.
- Catalog beats random widening: `False`.
- Production-path prototype recommended: `False`.
- `GOLD_COUNT_SUPPORT_CAP` remains `THIRD_FACTOR_UNTESTED`.
