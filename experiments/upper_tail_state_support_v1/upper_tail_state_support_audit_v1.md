# Upper-tail / State Support Audit v1

## Final verdict

**`INCONCLUSIVE`**

Best-supported mechanism: **`C_VALUE_MODEL_ERROR`**, but `D_DATA_LIMITATION` prevents a population-level causal claim.

This is a frozen-snapshot, offline audit. It does not change or tune the production Solver. Current-HEAD replay is an unmodified, read-only geometry diagnostic and is not substituted for the causal prediction-time artifact.

## FACT — production state-support paths

- `maxPlausibleGoldCount` exists and can penalize high-G state weight by ×0.02.
- It can also filter incomplete states during valuation expansion.
- Independently, low-information histories can compress a large hard state set to representative valuation states.
- Candidate state weights are normalized into `relativeWeight`; `shadowWhole` is the weighted mixture of supported state distributions.

## GOLD_COUNT_SUPPORT_CAP audit

- Audited frozen Global OOS profiles: **48**.
- High-confidence complete realized-state rows: **20**.
- Truth G recalled by full candidates: **19/20**.
- Truth G recalled by saved probability-profile candidates: **19/20**.
- Profiles with full→profile G loss: **2**; observed losses attributable to the Gold cap: **0**.
- The only truth-G miss has a prediction/truth contract conflict (prediction P=9 versus settlement P=1), so it is not valid evidence that the cap removed the realized state.
- Result: the cap is a real latent code-path risk, but it is **not an observed cause of the audited extreme upper-tail misses**.

## Extreme upper-tail selection

Pre-registered selection: Global v1.2 OOS records with `actualTotal ≥ 900,000` and `actualTotal > saved P80`. Selected **7** records.

| Record | Actual | Saved P80 | Shortfall | Truth / locked state | Candidates | Uniform P80-capable mass | Weighted mass | Classification |
|---|---:|---:|---:|---|---:|---:|---:|---|
| `r-msvt5jxu-kewgma` | 1464886 | 1063175 | 401711 (27.4%) | unknown | 7 | 0.0% | 0.0% | `D_DATA_LIMITATION` |
| `r-mspvjp1i-kpyt6n` | 1279983 | 943904 | 336079 (26.3%) | unknown | 10 | 40.0% | 1.2% | `B_STATE_LIKELIHOOD_SUPPRESSION` |
| `r-msw0sh9u-94rikb` | 1015283 | 787518 | 227765 (22.4%) | 4/7/4 | 2 | 0.0% | 0.0% | `C_VALUE_MODEL_ERROR` |
| `r-mssi85je-2ulgt2` | 944569 | 745203 | 199366 (21.1%) | 7/16/4 | 6 | 0.0% | 0.0% | `C_VALUE_MODEL_ERROR` |
| `r-mspx4xtt-i9xoag` | 1582800 | 1404160 | 178640 (11.3%) | 10/13/2 | 1 | 0.0% | 0.0% | `D_DATA_LIMITATION` |
| `r-mssmdaxy-uodvsp` | 1167818 | 1078633 | 89185 (7.6%) | unknown | 4 | 0.0% | 0.0% | `D_DATA_LIMITATION` |
| `r-msw014jf-ug8f80` | 1020192 | 959106 | 61086 (6.0%) | 7/15/3 | 1 | 0.0% | 0.0% | `D_DATA_LIMITATION` |

## State-likelihood evidence

`before weighting` is the uniform candidate-state mass; `after weighting` is the frozen production `relativeWeight`. No counterfactual parameter or new heuristic is applied.

### `r-msvt5jxu-kewgma` — `D_DATA_LIMITATION`

- No verified realized G/P/R is available to distinguish missing state support from within-state tail error.
- P80-capable state mass: uniform 0.00% → weighted 0.00%.
- Top saved tail states: G/P/R=8/7/2, P80=1102738.426909091, mass=14.29%; G/P/R=7/7/3, P80=1063174.926909091, mass=14.29%; G/P/R=9/7/1, P80=1044253.426909091, mass=14.29%; G/P/R=6/7/4, P80=1023610.426909091, mass=14.29%; G/P/R=10/7/0, P80=985765.426909091, mass=14.29%.

### `r-mspvjp1i-kpyt6n` — `B_STATE_LIKELIHOOD_SUPPRESSION`

- Candidate states with P80 at/above actualTotal exist, but legacy weighting removes more than half their uniform mass and leaves under 20%.
- P80-capable state mass: uniform 40.00% → weighted 1.22%.
- Top saved tail states: G/P/R=0/6/9, P80=1758476.8666666667, mass=0.30%; G/P/R=1/6/8, P80=1628707.8666666667, mass=0.30%; G/P/R=2/6/7, P80=1488291.8666666667, mass=0.30%; G/P/R=3/6/6, P80=1318419.8666666667, mass=0.30%; G/P/R=4/6/5, P80=1168173.8666666667, mass=0.30%.

### `r-msw0sh9u-94rikb` — `C_VALUE_MODEL_ERROR`

- The realized/locked state exists, but its entire frozen value support ends below actualTotal.
- P80-capable state mass: uniform 0.00% → weighted 0.00%.
- Top saved tail states: G/P/R=4/7/4, P80=817170.8, mass=26.96%; G/P/R=5/7/3, P80=774041.8, mass=73.04%.

### `r-mssi85je-2ulgt2` — `C_VALUE_MODEL_ERROR`

- The realized/locked state exists, but its entire frozen value support ends below actualTotal.
- P80-capable state mass: uniform 0.00% → weighted 0.00%.
- Top saved tail states: G/P/R=6/16/5, P80=745202.8, mass=16.67%; G/P/R=7/16/4, P80=716357.3, mass=16.67%; G/P/R=8/16/3, P80=687511.8, mass=16.67%; G/P/R=9/16/2, P80=560616.3, mass=16.67%; G/P/R=10/16/1, P80=433719.8, mass=16.67%.

### `r-mspx4xtt-i9xoag` — `D_DATA_LIMITATION`

- The event is above aggregate P80 but remains inside the matching state's saved support; one tail observation does not identify a model error.
- P80-capable state mass: uniform 0.00% → weighted 0.00%.
- Top saved tail states: G/P/R=10/13/2, P80=1404160.290909091, mass=100.00%.

### `r-mssmdaxy-uodvsp` — `D_DATA_LIMITATION`

- No verified realized G/P/R is available to distinguish missing state support from within-state tail error.
- P80-capable state mass: uniform 0.00% → weighted 0.00%.
- Top saved tail states: G/P/R=5/8/3, P80=1102234.9333333333, mass=25.00%; G/P/R=6/8/2, P80=1078632.9333333333, mass=25.00%; G/P/R=7/8/1, P80=1055034.9333333333, mass=25.00%; G/P/R=4/8/4, P80=1027783.9333333333, mass=25.00%.

### `r-msw014jf-ug8f80` — `D_DATA_LIMITATION`

- The event is above aggregate P80 but remains inside the matching state's saved support; one tail observation does not identify a model error.
- P80-capable state mass: uniform 0.00% → weighted 0.00%.
- Top saved tail states: G/P/R=7/15/3, P80=959105.8993333334, mass=100.00%.

## Evidence synthesis

- Classification counts: `{"B_STATE_LIKELIHOOD_SUPPRESSION": 1, "C_VALUE_MODEL_ERROR": 2, "D_DATA_LIMITATION": 4}`.
- Verified realized-state coverage among selected extremes: **3/7**; all **3/3** verified states are present.
- Two verified cases end above the maximum saved support of their true state: direct evidence for within-state/value-tail undercoverage.
- One unverified case has adequate high-value states before weighting but only a tiny frozen probability mass after the legacy red-count decay: direct mechanism evidence for likelihood suppression, not verified attribution to its realized state.
- The remaining cases cannot separate an unobserved realized state from within-state tail behavior.

## Current-HEAD offline replay diagnostic

- Replay completed without row errors: **7/7**.
- Candidate geometry matched the frozen prediction profile: **7/7**.
- Exact aggregate P80 reproduced: **3/7**.
- Interpretation: the replay corroborates the audited state-space geometry, but historical tail values are not fully replayable from current code plus saved inputs. This is additional provenance/data limitation, so all A/B/C/D attribution above remains based on the frozen prediction-time distributions.

## Answer to A/B/C/D

- **A — state space missing:** not supported for the truth-verified extreme rows; 3/3 realized states are present.
- **B — state likelihood suppression:** demonstrated as a mechanism in one major miss, but the record lacks realized G/P/R truth.
- **C — value model error:** strongest verified evidence; two truth-matched states cannot reach actualTotal even at their saved maximum.
- **D — data limitation:** material; four of seven selected extremes lack complete realized state, and several state tails are bootstrap/mixed low-sample artifacts.
- Therefore the population-level primary bottleneck remains **`INCONCLUSIVE`**, with C currently better supported than A or B.

## Recommendation

Do not widen variance, change `candidateStateWeight`, or remove the Gold cap yet. The next smallest step is an experiment-only **Upper-tail Truth/Support Capture Contract**: persist the prediction-time full candidate set, valuation candidate set, normalized weights, per-state tail provenance, and independently reviewed realized G/P/R for future high-value outcomes. Re-run this same truth-gated audit before any Shadow prototype.

## Integrity

- Main database SHA-256 before/after: `e9c75f920646839f3dafa02e7a6dff1802827e0d4c4dcbbe121f21c7b82847fe` / `e9c75f920646839f3dafa02e7a6dff1802827e0d4c4dcbbe121f21c7b82847fe`.
- Solver SHA-256 before/after: `1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f` / `1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f`.
- Shadow profile SHA-256 before/after: `9967f269f5c5b66dc8a010e3077ce014700c0b94333d93acf25a4021f9c886a5` / `9967f269f5c5b66dc8a010e3077ce014700c0b94333d93acf25a4021f9c886a5`.
- Production files modified: `false`.
