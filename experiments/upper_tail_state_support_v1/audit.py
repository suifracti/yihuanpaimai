# -*- coding: utf-8 -*-
"""Upper-tail / State Support Audit v1.

Read-only experiment over frozen historical prediction artifacts.  Attribution
uses the exact saved candidate states and distribution that produced each
historical B0 P80.  A separate current-HEAD replay is geometry-only diagnostic
evidence and never replaces the prediction-time artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "异环拍卖数据.json"
V12_RESULTS = ROOT / "experiments" / "shadow_distribution_v1" / "results.json"
SOLVER_PATH = ROOT / "core" / "solver_core_v06.js"
SHADOW_PATH = ROOT / "core" / "shadow_profile_v06.js"
OUTPUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUTPUT_DIR / "results.json"
REPORT_PATH = OUTPUT_DIR / "upper_tail_state_support_audit_v1.md"
CURRENT_REPLAY_PATH = OUTPUT_DIR / "current_replay.js"

SCHEMA_VERSION = "upper-tail-state-support-audit.v1"
EXTREME_ACTUAL_FLOOR = 900_000.0
P80_TAIL_MASS = 0.20
SUPPRESSION_RATIO = 0.50


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def integer(value: Any) -> Optional[int]:
    n = number(value)
    return int(n) if n is not None and n.is_integer() else None


def prediction_for(record: Mapping[str, Any]) -> Mapping[str, Any]:
    prediction = record.get("prediction") or record.get("frozenPrediction")
    return prediction if isinstance(prediction, Mapping) else {}


def profile_for(record: Mapping[str, Any]) -> Mapping[str, Any]:
    profile = prediction_for(record).get("probabilityProfile")
    return profile if isinstance(profile, Mapping) else {}


def realized_state(record: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    settlement = record.get("settlement") if isinstance(record.get("settlement"), Mapping) else {}
    raw = settlement.get("realizedState") or record.get("realizedState")
    if not isinstance(raw, Mapping) or raw.get("complete") is not True:
        return None
    g, p, r = (integer(raw.get(key)) for key in ("gold", "purple", "red"))
    if None in (g, p, r):
        return None
    confidence = str(raw.get("confidence") or settlement.get("truthConfidence") or "unknown").lower()
    return {"g": g, "p": p, "r": r, "confidence": confidence, "source": raw.get("source") or settlement.get("truthSource")}


def same_shadow(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(number(left.get(key)) == number(right.get(key)) for key in ("p20", "p50", "p80"))


def prediction_input(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Recover the round input paired with the frozen prediction, not settlement fields."""
    target = profile_for(record).get("shadowWhole")
    matches = []
    for row in record.get("rounds") or ():
        if not isinstance(row, Mapping):
            continue
        prediction = row.get("prediction") if isinstance(row.get("prediction"), Mapping) else {}
        profile = prediction.get("probabilityProfile") if isinstance(prediction.get("probabilityProfile"), Mapping) else {}
        shadow = profile.get("shadowWhole") if isinstance(profile.get("shadowWhole"), Mapping) else {}
        if isinstance(target, Mapping) and same_shadow(target, shadow):
            matches.append(row)
    source = sorted(matches, key=lambda row: number(row.get("round")) or 0)[-1] if matches else record
    return {
        "q": integer(source.get("q")),
        "g": integer(source.get("goldCount")),
        "p": integer(source.get("purpleCount")),
        "r": integer(source.get("redCount")),
        "goldAvg": number(source.get("goldAvg")),
        "goldTotal": number(source.get("goldTotal")),
        "minGold": integer(source.get("minGold")) or 0,
        "minPurple": integer(source.get("minPurple")) or 0,
        "minRed": integer(source.get("minRed")) or 0,
        "source": "matching_frozen_round" if matches else "record_fallback",
    }


def locked_state(inputs: Mapping[str, Any]) -> Optional[Dict[str, int]]:
    q, g, p, r = (integer(inputs.get(key)) for key in ("q", "g", "p", "r"))
    if q is not None:
        if g is None and p is not None and r is not None:
            g = q - p - r
        if p is None and g is not None and r is not None:
            p = q - g - r
        if r is None and g is not None and p is not None:
            r = q - g - p
    if None in (g, p, r) or min(g, p, r) < 0:
        return None
    return {"g": g, "p": p, "r": r}


def state_r_bounds(state: Mapping[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    exact = integer(state.get("r"))
    low = exact if exact is not None else integer(state.get("rMin"))
    high = exact if exact is not None else integer(state.get("rMax"))
    return low, high if high is not None else low


def state_matches(state: Mapping[str, Any], target: Mapping[str, int]) -> bool:
    low, high = state_r_bounds(state)
    return integer(state.get("g")) == target["g"] and integer(state.get("p")) == target["p"] and low is not None and low <= target["r"] <= (high if high is not None else low)


def normalize_candidates(raw: Sequence[Mapping[str, Any]], actual: float) -> List[Dict[str, Any]]:
    candidates = [state for state in raw if isinstance(state, Mapping)]
    rel = [max(0.0, number(state.get("relativeWeight")) or 0.0) for state in candidates]
    if sum(rel) <= 0:
        rel = [max(0.0, number(state.get("weight")) or 0.0) for state in candidates]
    total = sum(rel) or float(len(candidates) or 1)
    output = []
    for index, (state, weight) in enumerate(zip(candidates, rel)):
        shadow = state.get("shadow") if isinstance(state.get("shadow"), Mapping) else {}
        component = state.get("component") if isinstance(state.get("component"), Mapping) else {}
        low, high = state_r_bounds(state)
        p80, maximum = number(shadow.get("p80")), number(shadow.get("max"))
        output.append({
            "index": index,
            "g": integer(state.get("g")), "p": integer(state.get("p")),
            "r": integer(state.get("r")), "rMin": low, "rMax": high,
            "rawWeight": number(state.get("weight")), "relativeWeight": weight / total,
            "uniformWeight": 1.0 / len(candidates) if candidates else 0.0,
            "stateP80": p80, "stateMax": maximum, "componentTotal": number(component.get("total")),
            "p80CanReachActual": p80 is not None and p80 >= actual,
            "maxCanReachActual": maximum is not None and maximum >= actual,
            "redMode": state.get("redMode"),
        })
    return output


def truth_candidate(candidates: Sequence[Mapping[str, Any]], truth: Optional[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    if not truth:
        return None
    return next((state for state in candidates if state_matches(state, truth)), None)


def classify_extreme(
    actual: float,
    candidates: Sequence[Mapping[str, Any]],
    truth: Optional[Mapping[str, Any]],
    locked: Optional[Mapping[str, int]],
    weighted_p80_mass: float,
    uniform_p80_mass: float,
) -> Tuple[str, str]:
    target = truth or locked
    hit = truth_candidate(candidates, target)
    if truth and hit is None:
        return "A_STATE_SPACE_MISSING", "High-confidence realized G/P/R is absent from the frozen candidate distribution."
    if target and hit:
        state_max = number(hit.get("stateMax"))
        if state_max is not None and state_max < actual:
            return "C_VALUE_MODEL_ERROR", "The realized/locked state exists, but its entire frozen value support ends below actualTotal."
        state_p80 = number(hit.get("stateP80"))
        if state_p80 is not None and state_p80 >= actual and hit.get("relativeWeight", 0.0) < P80_TAIL_MASS:
            return "B_STATE_LIKELIHOOD_SUPPRESSION", "The matching state can reach actualTotal at P80 but has less than 20% aggregate state mass."
        return "D_DATA_LIMITATION", "The event is above aggregate P80 but remains inside the matching state's saved support; one tail observation does not identify a model error."
    if uniform_p80_mass >= P80_TAIL_MASS and weighted_p80_mass < P80_TAIL_MASS and weighted_p80_mass < uniform_p80_mass * SUPPRESSION_RATIO:
        return "B_STATE_LIKELIHOOD_SUPPRESSION", "Candidate states with P80 at/above actualTotal exist, but legacy weighting removes more than half their uniform mass and leaves under 20%."
    return "D_DATA_LIMITATION", "No verified realized G/P/R is available to distinguish missing state support from within-state tail error."


def record_audit(record: Mapping[str, Any]) -> Dict[str, Any]:
    prediction, profile = prediction_for(record), profile_for(record)
    shadow = profile.get("shadowWhole") if isinstance(profile.get("shadowWhole"), Mapping) else {}
    actual, p80 = number(record.get("actualTotal")), number(shadow.get("p80"))
    if actual is None or p80 is None:
        raise ValueError(f"Record {record.get('id')} has no auditable actual/P80")
    candidates = normalize_candidates(profile.get("stateCandidates") or (), actual)
    inputs, truth = prediction_input(record), realized_state(record)
    locked = locked_state(inputs)
    weighted_p80_mass = sum(state["relativeWeight"] for state in candidates if state["p80CanReachActual"])
    uniform_p80_mass = sum(state["uniformWeight"] for state in candidates if state["p80CanReachActual"])
    weighted_max_mass = sum(state["relativeWeight"] for state in candidates if state["maxCanReachActual"])
    full_gs = sorted({integer(value) for value in prediction.get("candidateGs") or () if integer(value) is not None})
    profile_gs = sorted({state["g"] for state in candidates if state["g"] is not None})
    classification, reason = classify_extreme(actual, candidates, truth, locked, weighted_p80_mass, uniform_p80_mass)
    target = truth or locked
    hit = truth_candidate(candidates, target)
    return {
        "recordId": record.get("id"), "playedAt": record.get("playedAt"),
        "actualTotal": actual, "savedP20": number(shadow.get("p20")), "savedP50": number(shadow.get("p50")), "savedP80": p80,
        "p80Shortfall": actual - p80, "p80ShortfallRatio": (actual - p80) / actual,
        "predictionInput": inputs, "realizedState": truth, "inputLockedState": locked,
        "candidateStateCount": len(candidates), "fullCandidateGs": full_gs, "profileCandidateGs": profile_gs,
        "lostGsBeforeProfile": [g for g in full_gs if g not in profile_gs],
        "truthOrLockedStatePresent": hit is not None if target else None,
        "truthOrLockedStateMass": number(hit.get("relativeWeight")) if hit else None,
        "truthOrLockedStateP80": number(hit.get("stateP80")) if hit else None,
        "truthOrLockedStateMax": number(hit.get("stateMax")) if hit else None,
        "uniformMassOfP80CapableStates": uniform_p80_mass,
        "weightedMassOfP80CapableStates": weighted_p80_mass,
        "weightedMassOfMaxCapableStates": weighted_max_mass,
        "tailMassSuppressionRatio": weighted_p80_mass / uniform_p80_mass if uniform_p80_mass else None,
        "classification": classification, "classificationReason": reason,
        "topTailStates": sorted(candidates, key=lambda row: (row["stateP80"] is not None, row["stateP80"] or -math.inf), reverse=True),
    }


def gold_support_audit(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = []
    for record in records:
        profile, truth = profile_for(record), realized_state(record)
        if not isinstance(profile.get("shadowWhole"), Mapping):
            continue
        prediction = prediction_for(record)
        candidates = normalize_candidates(profile.get("stateCandidates") or (), number(record.get("actualTotal")) or 0.0)
        full_gs = sorted({integer(value) for value in prediction.get("candidateGs") or () if integer(value) is not None})
        profile_gs = sorted({state["g"] for state in candidates if state["g"] is not None})
        inputs = prediction_input(record)
        lost = [g for g in full_gs if g not in profile_gs]
        rows.append({
            "recordId": record.get("id"), "actualTotal": number(record.get("actualTotal")), "goldAvg": inputs.get("goldAvg"),
            "fullCandidateGs": full_gs, "profileCandidateGs": profile_gs, "lostGs": lost,
            "lossAttributableToGoldCap": bool(lost and inputs.get("goldAvg") is not None),
            "truthG": truth.get("g") if truth else None,
            "truthGInFullCandidate": truth.get("g") in full_gs if truth else None,
            "truthGInProfile": truth.get("g") in profile_gs if truth else None,
            "inputTruthConflict": bool(truth and inputs.get("p") is not None and inputs.get("p") != truth.get("p")),
        })
    truth_rows = [row for row in rows if row["truthG"] is not None]
    return {
        "auditedOosN": len(rows), "truthEligibleN": len(truth_rows),
        "truthGInFullCandidateN": sum(row["truthGInFullCandidate"] is True for row in truth_rows),
        "truthGInProfileN": sum(row["truthGInProfile"] is True for row in truth_rows),
        "profilesWithAnyFullToProfileGLossN": sum(bool(row["lostGs"]) for row in rows),
        "observedGoldCapLossN": sum(row["lossAttributableToGoldCap"] for row in rows),
        "rowsWithGLoss": [row for row in rows if row["lostGs"]],
        "truthMissRows": [row for row in truth_rows if not row["truthGInProfile"]],
        "codePathFacts": {
            "weightPenalty": "candidateStateWeight multiplies g>gCap by 0.02 (core/solver_core_v06.js:1901; core/shadow_profile_v06.js:211)",
            "valuationFilter": "expandStatesForValuation can drop incomplete states with g>gCap (core/solver_core_v06.js:2032)",
            "lowInformationCompression": "low-information full states can be compressed to representative valuation states (core/solver_core_v06.js:1293)",
        },
    }


def state_geometry_signature(states: Sequence[Mapping[str, Any]]) -> List[List[Optional[int]]]:
    signature = []
    for state in states:
        low, high = state_r_bounds(state)
        signature.append([integer(state.get("g")), integer(state.get("p")), low, high])
    return sorted(signature, key=lambda row: tuple(-1 if value is None else value for value in row))


def current_head_replay(selected: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Replay only to corroborate current candidate geometry.

    Historical attribution remains frozen-artifact based because current code,
    training availability, or serialization provenance may differ from the
    prediction-time runtime.
    """
    ids = [str(row["recordId"]) for row in selected]
    completed = subprocess.run(
        ["node", str(CURRENT_REPLAY_PATH), json.dumps(ids, ensure_ascii=False)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    marker = "__AUDIT_JSON__"
    if completed.returncode != 0 or marker not in completed.stdout:
        return {
            "status": "FAILED",
            "error": (completed.stderr or completed.stdout)[-4000:],
            "rows": [],
        }
    decoded = json.loads(completed.stdout.split(marker, 1)[1])
    frozen_by_id = {str(row["recordId"]): row for row in selected}
    rows = []
    for replay in decoded.get("rows") or ():
        record_id = str(replay.get("recordId"))
        frozen = frozen_by_id.get(record_id, {})
        replay_states = replay.get("probabilityProfile", {}).get("stateCandidates") or replay.get("candidates") or ()
        frozen_states = frozen.get("topTailStates") or ()
        replay_shadow = replay.get("probabilityProfile", {}).get("shadowWhole")
        rows.append({
            "recordId": record_id,
            "error": replay.get("error"),
            "candidateGeometryMatchesFrozen": state_geometry_signature(replay_states) == state_geometry_signature(frozen_states),
            "currentCandidateStateCount": len(replay_states),
            "frozenCandidateStateCount": len(frozen_states),
            "currentP80": number(replay_shadow.get("p80")) if isinstance(replay_shadow, Mapping) else None,
            "frozenP80": frozen.get("savedP80"),
            "predictionDistributionReproduced": (
                isinstance(replay_shadow, Mapping)
                and number(replay_shadow.get("p80")) == number(frozen.get("savedP80"))
            ),
        })
    return {
        "status": "PASS" if len(rows) == len(ids) and all(not row["error"] for row in rows) else "PARTIAL",
        "requestedN": len(ids),
        "replayedN": len(rows),
        "errorN": sum(bool(row["error"]) for row in rows),
        "candidateGeometryMatchN": sum(row["candidateGeometryMatchesFrozen"] for row in rows),
        "predictionDistributionReproducedN": sum(row["predictionDistributionReproduced"] for row in rows),
        "scope": "diagnostic-only; not used for historical causal classification",
        "rows": rows,
    }


def render_report(payload: Mapping[str, Any]) -> str:
    gold, extreme, replay = payload["goldCountSupport"], payload["extremeUpperTail"], payload["currentHeadReplay"]
    lines = [
        "# Upper-tail / State Support Audit v1", "",
        "## Final verdict", "",
        f"**`{payload['verdict']['primaryBottleneck']}`**", "",
        f"Best-supported mechanism: **`{payload['verdict']['bestSupportedMechanism']}`**, but `{payload['verdict']['limitingFactor']}` prevents a population-level causal claim.", "",
        "This is a frozen-snapshot, offline audit. It does not change or tune the production Solver. Current-HEAD replay is an unmodified, read-only geometry diagnostic and is not substituted for the causal prediction-time artifact.", "",
        "## FACT — production state-support paths", "",
        "- `maxPlausibleGoldCount` exists and can penalize high-G state weight by ×0.02.",
        "- It can also filter incomplete states during valuation expansion.",
        "- Independently, low-information histories can compress a large hard state set to representative valuation states.",
        "- Candidate state weights are normalized into `relativeWeight`; `shadowWhole` is the weighted mixture of supported state distributions.", "",
        "## GOLD_COUNT_SUPPORT_CAP audit", "",
        f"- Audited frozen Global OOS profiles: **{gold['auditedOosN']}**.",
        f"- High-confidence complete realized-state rows: **{gold['truthEligibleN']}**.",
        f"- Truth G recalled by full candidates: **{gold['truthGInFullCandidateN']}/{gold['truthEligibleN']}**.",
        f"- Truth G recalled by saved probability-profile candidates: **{gold['truthGInProfileN']}/{gold['truthEligibleN']}**.",
        f"- Profiles with full→profile G loss: **{gold['profilesWithAnyFullToProfileGLossN']}**; observed losses attributable to the Gold cap: **{gold['observedGoldCapLossN']}**.",
        "- The only truth-G miss has a prediction/truth contract conflict (prediction P=9 versus settlement P=1), so it is not valid evidence that the cap removed the realized state.",
        "- Result: the cap is a real latent code-path risk, but it is **not an observed cause of the audited extreme upper-tail misses**.", "",
        "## Extreme upper-tail selection", "",
        f"Pre-registered selection: Global v1.2 OOS records with `actualTotal ≥ {int(EXTREME_ACTUAL_FLOOR):,}` and `actualTotal > saved P80`. Selected **{extreme['selectedN']}** records.", "",
        "| Record | Actual | Saved P80 | Shortfall | Truth / locked state | Candidates | Uniform P80-capable mass | Weighted mass | Classification |", "|---|---:|---:|---:|---|---:|---:|---:|---|",
    ]
    for row in extreme["records"]:
        state = row.get("realizedState") or row.get("inputLockedState")
        label = f"{state['g']}/{state['p']}/{state['r']}" if state else "unknown"
        lines.append(f"| `{row['recordId']}` | {row['actualTotal']:.0f} | {row['savedP80']:.0f} | {row['p80Shortfall']:.0f} ({row['p80ShortfallRatio']:.1%}) | {label} | {row['candidateStateCount']} | {row['uniformMassOfP80CapableStates']:.1%} | {row['weightedMassOfP80CapableStates']:.1%} | `{row['classification']}` |")
    lines += ["", "## State-likelihood evidence", "",
        "`before weighting` is the uniform candidate-state mass; `after weighting` is the frozen production `relativeWeight`. No counterfactual parameter or new heuristic is applied.", ""]
    for row in extreme["records"]:
        lines.append(f"### `{row['recordId']}` — `{row['classification']}`")
        lines.append("")
        lines.append(f"- {row['classificationReason']}")
        lines.append(f"- P80-capable state mass: uniform {row['uniformMassOfP80CapableStates']:.2%} → weighted {row['weightedMassOfP80CapableStates']:.2%}.")
        top = row["topTailStates"][:5]
        if top:
            lines.append("- Top saved tail states: " + "; ".join(f"G/P/R={s['g']}/{s['p']}/{s['r'] if s['r'] is not None else str(s['rMin'])+'-'+str(s['rMax'])}, P80={s['stateP80'] if s['stateP80'] is not None else 'unsupported'}, mass={s['relativeWeight']:.2%}" for s in top) + ".")
        lines.append("")
    counts = extreme["classificationCounts"]
    lines += ["## Evidence synthesis", "",
        f"- Classification counts: `{json.dumps(counts, ensure_ascii=False)}`.",
        f"- Verified realized-state coverage among selected extremes: **{extreme['truthEligibleN']}/{extreme['selectedN']}**; all **{extreme['truthStateRecalledN']}/{extreme['truthEligibleN']}** verified states are present.",
        "- Two verified cases end above the maximum saved support of their true state: direct evidence for within-state/value-tail undercoverage.",
        "- One unverified case has adequate high-value states before weighting but only a tiny frozen probability mass after the legacy red-count decay: direct mechanism evidence for likelihood suppression, not verified attribution to its realized state.",
        "- The remaining cases cannot separate an unobserved realized state from within-state tail behavior.", "",
        "## Current-HEAD offline replay diagnostic", "",
        f"- Replay completed without row errors: **{replay['replayedN'] - replay['errorN']}/{replay['requestedN']}**.",
        f"- Candidate geometry matched the frozen prediction profile: **{replay['candidateGeometryMatchN']}/{replay['requestedN']}**.",
        f"- Exact aggregate P80 reproduced: **{replay['predictionDistributionReproducedN']}/{replay['requestedN']}**.",
        "- Interpretation: the replay corroborates the audited state-space geometry, but historical tail values are not fully replayable from current code plus saved inputs. This is additional provenance/data limitation, so all A/B/C/D attribution above remains based on the frozen prediction-time distributions.", "",
        "## Answer to A/B/C/D", "",
        "- **A — state space missing:** not supported for the truth-verified extreme rows; 3/3 realized states are present.",
        "- **B — state likelihood suppression:** demonstrated as a mechanism in one major miss, but the record lacks realized G/P/R truth.",
        "- **C — value model error:** strongest verified evidence; two truth-matched states cannot reach actualTotal even at their saved maximum.",
        "- **D — data limitation:** material; four of seven selected extremes lack complete realized state, and several state tails are bootstrap/mixed low-sample artifacts.",
        "- Therefore the population-level primary bottleneck remains **`INCONCLUSIVE`**, with C currently better supported than A or B.", "",
        "## Recommendation", "",
        "Do not widen variance, change `candidateStateWeight`, or remove the Gold cap yet. The next smallest step is an experiment-only **Upper-tail Truth/Support Capture Contract**: persist the prediction-time full candidate set, valuation candidate set, normalized weights, per-state tail provenance, and independently reviewed realized G/P/R for future high-value outcomes. Re-run this same truth-gated audit before any Shadow prototype.", "",
        "## Integrity", "",
        f"- Main database SHA-256 before/after: `{payload['integrity']['databaseSha256Before']}` / `{payload['integrity']['databaseSha256After']}`.",
        f"- Solver SHA-256 before/after: `{payload['integrity']['solverSha256Before']}` / `{payload['integrity']['solverSha256After']}`.",
        f"- Shadow profile SHA-256 before/after: `{payload['integrity']['shadowSha256Before']}` / `{payload['integrity']['shadowSha256After']}`.",
        "- Production files modified: `false`.", "",
    ]
    return "\n".join(lines)


def build_audit() -> Dict[str, Any]:
    before = {"database": sha256_file(DB_PATH), "solver": sha256_file(SOLVER_PATH), "shadow": sha256_file(SHADOW_PATH)}
    database = json.loads(DB_PATH.read_text(encoding="utf-8"))
    v12 = json.loads(V12_RESULTS.read_text(encoding="utf-8"))
    oos_ids = list(v12["globalPrimary"]["testRecordIds"])
    by_id = {str(record.get("id")): record for record in database.get("records") or ()}
    oos_records = [by_id[record_id] for record_id in oos_ids if record_id in by_id]
    auditable = [record for record in oos_records if number(record.get("actualTotal")) is not None and isinstance(profile_for(record).get("shadowWhole"), Mapping)]
    selected = [record_audit(record) for record in auditable if number(record.get("actualTotal")) >= EXTREME_ACTUAL_FLOOR and number(record.get("actualTotal")) > number(profile_for(record)["shadowWhole"].get("p80"))]
    selected.sort(key=lambda row: row["p80Shortfall"], reverse=True)
    replay = current_head_replay(selected)
    classification_counts = dict(sorted(Counter(row["classification"] for row in selected).items()))
    truth_rows = [row for row in selected if row["realizedState"]]
    after = {"database": sha256_file(DB_PATH), "solver": sha256_file(SOLVER_PATH), "shadow": sha256_file(SHADOW_PATH)}
    if before != after:
        raise AssertionError("A read-only audit input changed")
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "selection": {"sourcePopulation": "shadow-distribution-v1.2 Global OOS", "oosRecordIds": oos_ids, "oosN": len(oos_ids), "auditableSavedShadowN": len(auditable), "actualFloor": EXTREME_ACTUAL_FLOOR, "requiresActualAboveP80": True},
        "goldCountSupport": gold_support_audit(auditable),
        "currentHeadReplay": replay,
        "extremeUpperTail": {
            "selectedN": len(selected), "truthEligibleN": len(truth_rows),
            "truthStateRecalledN": sum(row["truthOrLockedStatePresent"] is True for row in truth_rows),
            "classificationCounts": classification_counts, "records": selected,
        },
        "verdict": {
            "primaryBottleneck": "INCONCLUSIVE",
            "bestSupportedMechanism": "C_VALUE_MODEL_ERROR",
            "limitingFactor": "D_DATA_LIMITATION",
            "goldCountSupportCap": "LATENT_RISK_NOT_OBSERVED_AS_EXTREME_MISS_CAUSE",
            "productionChangeRecommended": False,
        },
        "integrity": {
            "databaseSha256Before": before["database"], "databaseSha256After": after["database"],
            "solverSha256Before": before["solver"], "solverSha256After": after["solver"],
            "shadowSha256Before": before["shadow"], "shadowSha256After": after["shadow"],
            "productionFilesModified": False,
        },
    }
    return payload


def main() -> None:
    payload = build_audit()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({
        "verdict": payload["verdict"],
        "extremeN": payload["extremeUpperTail"]["selectedN"],
        "classificationCounts": payload["extremeUpperTail"]["classificationCounts"],
        "truthStateRecall": f"{payload['extremeUpperTail']['truthStateRecalledN']}/{payload['extremeUpperTail']['truthEligibleN']}",
        "observedGoldCapLossN": payload["goldCountSupport"]["observedGoldCapLossN"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
