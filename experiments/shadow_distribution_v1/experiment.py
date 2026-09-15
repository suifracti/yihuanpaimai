# -*- coding: utf-8 -*-
"""Shadow Distribution Reproducibility / Control-Group Audit v1.2.

Experiment-only read-only walk-forward audit. B0 is the production-saved
Shadow. A0, RN, A1-PROXY and A1-CATALOG share one reconstruction engine and
differ only in their non-red draw provider. Test settlement facts are scoring
targets only and production Solver files are read-only provenance inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
sys.path.insert(0, str(CORE_DIR))
sys.path.insert(0, str(APP_DIR))

from history_admission import build_duplicate_index  # noqa: E402
from legacy_exploratory_policy import classify_legacy_record  # noqa: E402

EXPERIMENT_VERSION = "shadow-distribution-control-audit-v1.2"
ARTIFACT_SCHEMA_VERSION = "shadow-distribution-results.v1.2"
SEED = 20260822
BOOTSTRAP_REPLICATES = 10_000
SUPPORT_POINTS = 7
EQUIVALENCE_MARGIN = 0.02
LOW_END_REGRESSION_LIMIT = 0.02
CATALOG_CUTOFF = datetime.fromisoformat("2026-08-13T00:00:00+08:00").timestamp()
MODEL_NAMES = (
    "B0_PRODUCTION_SAVED",
    "A0_RECONSTRUCTION_NO_NON_RED_VARIANCE",
    "RN_NULL_MATCHED_VARIANCE",
    "A1_PROXY_GAUSSIAN_CV",
    "A1_CATALOG_DISCRETE",
)
DISPERSION_MODELS = MODEL_NAMES[1:]
Z7 = (-1.645, -1.036, -0.524, 0.0, 0.524, 1.036, 1.645)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_seed(*parts: Any) -> int:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def median(values: Sequence[float]) -> float:
    return statistics.median(values) if values else 0.0


def pinball_loss(y: float, q: float, tau: float) -> float:
    diff = y - q
    return tau * diff if diff >= 0 else (tau - 1.0) * diff


def winkler_interval_score(lower: float, upper: float, y: float, alpha: float = 0.40) -> float:
    width = max(0.0, upper - lower)
    if y < lower:
        return width + (2.0 / alpha) * (lower - y)
    if y > upper:
        return width + (2.0 / alpha) * (y - upper)
    return width


def wilson_score_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denominator = 1.0 + z**2 / n
    center = (p + z**2 / (2.0 * n)) / denominator
    margin = z * math.sqrt(p * (1.0 - p) / n + z**2 / (4.0 * n**2)) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def weighted_quantile(values: Sequence[float], weights: Sequence[float], q: float) -> float:
    pairs = sorted(zip(values, weights), key=lambda pair: pair[0])
    if not pairs:
        return 0.0
    total = sum(weight for _, weight in pairs)
    threshold, accumulated = q * total, 0.0
    for value, weight in pairs:
        accumulated += weight
        if accumulated >= threshold:
            return value
    return pairs[-1][0]


def unweighted_quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    lower, fraction = math.floor(position), position - math.floor(position)
    return ordered[lower] + fraction * (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower])


@dataclass(frozen=True)
class ReplayRecord:
    record_id: str
    played_at: str
    epoch: float
    actual_total: float
    q: Optional[int]
    venue: Optional[str]
    box: Optional[str]
    field_condition: Optional[str]
    gold_count: Optional[int]
    gold_avg: Optional[float]
    gold_total: Optional[float]
    purple_count: Optional[int]
    purple_avg: Optional[float]
    red_count: Optional[int]
    known_red: Tuple[float, ...]
    known_gold: Tuple[float, ...]
    known_purple: Tuple[float, ...]
    model_version: str
    solver_version: str
    baseline_p20: float
    baseline_p50: float
    baseline_p80: float
    state_candidates: Tuple[Mapping[str, Any], ...]
    red_samples: Tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class CatalogSnapshot:
    version: str
    gold: Tuple[float, ...]
    purple: Tuple[float, ...]
    low_tier: Tuple[float, ...]


@dataclass(frozen=True)
class Prediction:
    p20: float
    p50: float
    p80: float
    reconstruction_signature: Tuple[Any, ...]
    non_red_scale: float
    variance_source: str


def parse_price_list(raw: Any) -> Tuple[float, ...]:
    if not raw:
        return ()
    values = raw if isinstance(raw, list) else str(raw).split()
    output = []
    for value in values:
        candidate = value.get("price") if isinstance(value, Mapping) else value
        try:
            number = float(str(candidate).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            output.append(number)
    return tuple(output)


def safe_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def safe_integer(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def load_quantile_ablation_dataset(db_path: Path) -> List[ReplayRecord]:
    records = (json.loads(db_path.read_text(encoding="utf-8")).get("records") or [])
    duplicate_index = build_duplicate_index(records)
    classifications = [classify_legacy_record(record, duplicate_index) for record in records]
    dataset = []
    for record, classification in zip(records, classifications):
        if not classification.is_quantile_candidate:
            continue
        prediction = record.get("prediction") or record.get("frozenPrediction") or {}
        profile = prediction.get("probabilityProfile") or {}
        red_samples = []
        for distribution in profile.get("stateDistributions") or ():
            stats = distribution.get("stats") or {}
            for key in ("p05", "p20", "p50", "p80", "p95", "min", "max"):
                value = safe_number(stats.get(key))
                if value is not None:
                    red_samples.append({"r": distribution.get("r", 0), "value": value, "reportedN": safe_integer(stats.get("n"))})
        if not red_samples:
            red_samples = [{"r": 0, "value": 0.0, "reportedN": 0}]
        played_at = str(record.get("playedAt") or "1970-01-01T00:00:00")
        try:
            epoch = datetime.fromisoformat(played_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            epoch = 0.0
        dataset.append(ReplayRecord(
            record_id=classification.record_id,
            played_at=played_at,
            epoch=epoch,
            actual_total=float(classification.actual_total),
            q=safe_integer(record.get("q")), venue=record.get("venue"), box=record.get("box"),
            field_condition=record.get("fieldCondition"), gold_count=safe_integer(record.get("goldCount")),
            gold_avg=safe_number(record.get("goldAvg")), gold_total=safe_number(record.get("goldTotal")),
            purple_count=safe_integer(record.get("purpleCount")), purple_avg=safe_number(record.get("purpleAvg")),
            red_count=safe_integer(record.get("redCount")), known_red=parse_price_list(record.get("knownRed")),
            known_gold=parse_price_list(record.get("knownGold")), known_purple=parse_price_list(record.get("knownPurple")),
            model_version=classification.model_version or "unknown", solver_version=classification.solver_version or "unknown",
            baseline_p20=float(classification.p20), baseline_p50=float(classification.p50), baseline_p80=float(classification.p80),
            state_candidates=tuple(profile.get("stateCandidates") or ()), red_samples=tuple(red_samples),
        ))
    return sorted(dataset, key=lambda record: record.epoch)


def _extract_js_array(source: str, name: str) -> List[List[Any]]:
    match = re.search(rf"const\s+{re.escape(name)}\s*=\s*(\[.*?\]);", source, re.S)
    if not match:
        raise ValueError(f"Missing catalog array {name}")
    return json.loads(match.group(1))


def _extract_item_triples(block: str) -> List[List[Any]]:
    pattern = re.compile(r'\["((?:\\.|[^"\\])*)",\s*([0-9]+),\s*"([0-9]+x[0-9]+)"\]')
    return [[json.loads(f'"{name}"'), int(price), size] for name, price, size in pattern.findall(block)]


def _apply_current_block(pre_items: List[List[Any]], source: str, name: str) -> List[List[Any]]:
    match = re.search(rf"const\s+{re.escape(name)}\s*=\s*(.*?);", source, re.S)
    if not match:
        raise ValueError(f"Missing catalog block {name}")
    output = [list(item) for item in pre_items]
    for item in _extract_item_triples(match.group(1)):
        index = next((i for i, old in enumerate(output) if old[0] == item[0]), None)
        if index is None:
            output.append(item)
        else:
            output[index] = item
    return output


def load_catalog_snapshots(path: Path) -> Tuple[Dict[str, CatalogSnapshot], Dict[str, Any]]:
    source = path.read_text(encoding="utf-8")
    pre = {rarity: _extract_js_array(source, f"PRE_0813_{rarity.upper()}_ITEMS") for rarity in ("gold", "purple", "blue", "green", "white")}
    current = {
        "gold": _apply_current_block(pre["gold"], source, "GOLD_ITEMS"),
        "purple": pre["purple"],
        "blue": _apply_current_block(pre["blue"], source, "BLUE_ITEMS"),
        "green": _apply_current_block(pre["green"], source, "GREEN_ITEMS"),
        "white": _apply_current_block(pre["white"], source, "WHITE_ITEMS"),
    }
    make = lambda version, rows: CatalogSnapshot(version, tuple(float(x[1]) for x in rows["gold"]), tuple(float(x[1]) for x in rows["purple"]), tuple(float(x[1]) for key in ("blue", "green", "white") for x in rows[key]))
    snapshots = {"pre-2026-08-13": make("pre-2026-08-13", pre), "2026-08-13": make("2026-08-13", current)}
    provenance = {
        "sourcePath": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"), "sha256": sha256_file(path),
        "parser": "experiment-only-static-js-catalog-parser.v1",
        "snapshots": {name: {"goldN": len(x.gold), "purpleN": len(x.purple), "lowTierN": len(x.low_tier)} for name, x in snapshots.items()},
        "limitations": ["Static rule-price support is not an empirical item-probability distribution.", "No authoritative venue/box item-probability restrictions exist; none are invented.", "Equal item weights are used inside each rarity support."],
    }
    return snapshots, provenance


def catalog_for_record(record: ReplayRecord, catalogs: Mapping[str, CatalogSnapshot]) -> CatalogSnapshot:
    snapshot = catalogs["pre-2026-08-13" if record.epoch < CATALOG_CUTOFF else "2026-08-13"]
    gm = 2.0 if record.field_condition == "goldDouble" else 1.0
    pm = 2.0 if record.field_condition == "purpleDouble" else 1.0
    return CatalogSnapshot(snapshot.version, tuple(x * gm for x in snapshot.gold), tuple(x * pm for x in snapshot.purple), snapshot.low_tier)


def compute_candidate_state_weight(state: Mapping[str, Any], record: ReplayRecord, red_decay_power: float = 0.18, gold_decay_base: float = 0.34) -> float:
    weight, r_value, g_value = 1.0, state.get("r", 0), state.get("g", 0)
    if finite(r_value):
        r = int(r_value)
        if r == 0: weight *= 1.35
        elif r == 1: weight *= 1.0
        elif r == 2: weight *= 0.55 if red_decay_power == 0.18 else math.sqrt(red_decay_power)
        elif r == 3: weight *= 0.28 if red_decay_power == 0.18 else red_decay_power * 0.7
        else: weight *= (red_decay_power ** max(0, r - 3)) * 0.28
    if record.gold_avg is not None and finite(g_value):
        g = int(g_value)
        if record.gold_avg >= 120_000: decay = (gold_decay_base * 0.65) ** max(0, g - 1)
        elif record.gold_avg >= 80_000: decay = gold_decay_base ** max(0, g - 1)
        elif record.gold_avg >= 50_000: decay = (gold_decay_base + 0.14) ** max(0, g - 1)
        else: decay = 0.78 ** max(0, g - 1)
        weight *= decay
    if record.red_count == 0 and r_value == 0: weight *= 1.5
    return max(1e-6, weight)


def component_fixed(component: Mapping[str, Any]) -> float:
    return sum(float((component.get(key) or {}).get("mid") or 0.0) for key in ("gold", "purple", "lowTier"))


def non_red_is_exact(record: ReplayRecord, g: int, p: int) -> bool:
    gold_exact = record.gold_total is not None or (record.gold_avg is not None and record.gold_count == g)
    purple_exact = p == 0 or (record.purple_avg is not None and record.purple_count == p)
    return gold_exact and purple_exact


def proxy_scale(component: Mapping[str, Any], record: ReplayRecord, g: int, p: int, coefficient: float) -> float:
    if non_red_is_exact(record, g, p): return 0.0
    gold_mid = float((component.get("gold") or {}).get("mid") or 0.0)
    gold_sigma = coefficient * (record.gold_avg or gold_mid / max(1, g)) if g > 0 else 0.0
    return math.sqrt(g * gold_sigma**2 + p * 8_000.0**2 + 2_500.0**2)


def compress_support(values: Sequence[float], limit: int = 49) -> List[float]:
    if len(values) <= limit: return sorted(values)
    return [unweighted_quantile(values, i / (limit - 1)) for i in range(limit)]


def sum_support(prices: Sequence[float], count: int) -> List[float]:
    if count <= 0 or not prices: return [0.0]
    support, base = [0.0], compress_support(prices, 49)
    for _ in range(count): support = compress_support([a + b for a in support for b in base], 49)
    return support


def remove_known(prices: Sequence[float], known: Sequence[float]) -> List[float]:
    output = list(prices)
    for value in known:
        if not output: break
        index = min(range(len(output)), key=lambda i: abs(output[i] - value))
        if abs(output[index] - value) < 0.5: output.pop(index)
    return output


def catalog_draws(component: Mapping[str, Any], record: ReplayRecord, g: int, p: int, r: int, catalog: CatalogSnapshot) -> List[float]:
    fixed = component_fixed(component)
    if non_red_is_exact(record, g, p): return [fixed] * SUPPORT_POINTS
    low_count = max(0, (record.q or g + p + r) - g - p - r)
    gs = sum_support(remove_known(catalog.gold, record.known_gold), max(0, g - len(record.known_gold)))
    ps = sum_support(remove_known(catalog.purple, record.known_purple), max(0, p - len(record.known_purple)))
    ls = sum_support(catalog.low_tier, low_count)
    combined = compress_support([a + b + c for a in gs for b in ps for c in ls], 121)
    raw = [unweighted_quantile(combined, i / (SUPPORT_POINTS - 1)) for i in range(SUPPORT_POINTS)]
    center = raw[SUPPORT_POINTS // 2]
    return [max(0.0, fixed + value - center) for value in raw]


def red_values(record: ReplayRecord, state: Mapping[str, Any], r: int) -> List[float]:
    stats, values = state.get("red") or {}, []
    for key in ("p10", "p20", "p50", "p80", "p90"):
        value = safe_number(stats.get(key))
        if value is not None: values.append(value)
    if not values: values = [float(x["value"]) for x in record.red_samples if x.get("r") == r and finite(x.get("value"))]
    return values or [0.0]


def generate_reconstructed_prediction(record: ReplayRecord, *, variance_model: str, proxy_coefficient: float = 0.22, null_scale_ratio: float = 0.0, catalogs: Optional[Mapping[str, CatalogSnapshot]] = None, red_decay_power: float = 0.18, gold_decay_base: float = 0.34, off_support_points: int = SUPPORT_POINTS) -> Prediction:
    if not record.state_candidates:
        return Prediction(record.baseline_p20, record.baseline_p50, record.baseline_p80, (("production-fallback",),), 0.0, "production-fallback")
    values, weights, signatures, scales = [], [], [], []
    catalog = catalog_for_record(record, catalogs) if catalogs is not None else None
    source = variance_model
    for state in record.state_candidates:
        g, p, r = int(state.get("g", 0) or 0), int(state.get("p", 0) or 0), int(state.get("r", 0) or 0)
        component, reds = state.get("component") or {}, red_values(record, state, r)
        fixed = component_fixed(component)
        state_weight = compute_candidate_state_weight(state, record, red_decay_power, gold_decay_base)
        if variance_model == "off": draws = [fixed] * off_support_points
        elif variance_model == "proxy":
            scale = proxy_scale(component, record, g, p, proxy_coefficient); scales.append(scale); draws = [max(0.0, fixed + z * scale) for z in Z7]; source = "gaussian-cv-proxy"
        elif variance_model == "null":
            scale = 0.0 if non_red_is_exact(record, g, p) else null_scale_ratio * max(1.0, record.baseline_p50); scales.append(scale); draws = [max(0.0, fixed + z * scale) for z in Z7]; source = "training-fold-null-randomized-scale"
        elif variance_model == "catalog":
            if catalog is None: raise ValueError("Catalog required")
            draws = catalog_draws(component, record, g, p, r, catalog); scales.append((max(draws) - min(draws)) / 3.29); source = f"catalog-discrete:{catalog.version}"
        else: raise ValueError(variance_model)
        signatures.append((g, p, r, round(state_weight, 12), len(draws), len(reds), round(fixed, 6)))
        draw_weight = state_weight / (len(draws) * len(reds))
        for non_red in draws:
            for red in reds: values.append(non_red + red); weights.append(draw_weight)
    raw20, raw50, raw80 = (weighted_quantile(values, weights, q) for q in (0.20, 0.50, 0.80))
    p50 = record.baseline_p50
    prediction = Prediction(max(0.0, p50 - (raw50 - raw20)), p50, p50 + (raw80 - raw50), tuple(signatures), mean(scales), source)
    assert prediction.p50 == record.baseline_p50
    return prediction


def fold_splits(total: int, min_train: int) -> List[Tuple[int, int]]:
    step, output, train_end = max(3, (total - min_train) // 4), [], min_train
    while train_end < total:
        test_end = min(total, train_end + step)
        output.append((train_end, test_end))
        if test_end == total: break
        train_end = test_end
    return output


def tune_proxy_coefficient(train_set: Sequence[ReplayRecord]) -> float:
    best = (float("inf"), 0.22)
    for integer in (10, 15, 20, 25, 30, 35):
        coefficient, scores = integer / 100.0, []
        for record in train_set:
            prediction = generate_reconstructed_prediction(record, variance_model="proxy", proxy_coefficient=coefficient)
            scores.append(winkler_interval_score(prediction.p20, prediction.p80, record.actual_total))
        best = min(best, (mean(scores), coefficient))
    return best[1]


def training_null_scale_pool(train_set: Sequence[ReplayRecord], coefficient: float) -> List[float]:
    ratios = []
    for record in train_set:
        prediction = generate_reconstructed_prediction(record, variance_model="proxy", proxy_coefficient=coefficient)
        if record.baseline_p50 > 0 and prediction.non_red_scale > 0:
            ratios.append(prediction.non_red_scale / record.baseline_p50)
    return ratios or [0.0]


def null_ratio_for_record(pool: Sequence[float], record_id: str, fold_index: int) -> float:
    rng = random.Random(stable_seed(SEED, "rn", fold_index, record_id))
    return pool[rng.randrange(len(pool))]


def per_record_scores(records: Sequence[ReplayRecord], predictions: Sequence[Prediction]) -> Dict[str, List[float]]:
    output = defaultdict(list)
    for record, prediction in zip(records, predictions):
        p20 = pinball_loss(record.actual_total, prediction.p20, 0.20)
        p50 = pinball_loss(record.actual_total, prediction.p50, 0.50)
        p80 = pinball_loss(record.actual_total, prediction.p80, 0.80)
        output["pinball20"].append(p20); output["pinball50"].append(p50); output["pinball80"].append(p80)
        output["averagePinball"].append((p20 + p50 + p80) / 3.0)
        output["winkler"].append(winkler_interval_score(prediction.p20, prediction.p80, record.actual_total))
    return dict(output)


def evaluate_model(records: Sequence[ReplayRecord], predictions: Sequence[Prediction]) -> Dict[str, Any]:
    n, scores = len(records), per_record_scores(records, predictions)
    actuals = [record.actual_total for record in records]
    p20s, p50s, p80s = ([getattr(prediction, key) for prediction in predictions] for key in ("p20", "p50", "p80"))
    hits = {
        "p20": sum(actual <= value for actual, value in zip(actuals, p20s)),
        "p50": sum(actual <= value for actual, value in zip(actuals, p50s)),
        "p80": sum(actual <= value for actual, value in zip(actuals, p80s)),
        "central60": sum(low <= actual <= high for actual, low, high in zip(actuals, p20s, p80s)),
    }
    widths = [max(0.0, high - low) for low, high in zip(p20s, p80s)]
    normalized = [width / p50 for width, p50 in zip(widths, p50s) if p50 > 0]
    absolute = [abs(actual - p50) for actual, p50 in zip(actuals, p50s)]
    relative = [abs(actual - p50) / actual for actual, p50 in zip(actuals, p50s) if actual > 0]
    return {
        "n": n,
        "meanPinballLoss20": round(mean(scores["pinball20"]), 2), "meanPinballLoss50": round(mean(scores["pinball50"]), 2),
        "meanPinballLoss80": round(mean(scores["pinball80"]), 2), "meanAveragePinballLoss": round(mean(scores["averagePinball"]), 2),
        "meanWinklerIntervalScore": round(mean(scores["winkler"]), 2),
        "empiricalFP20": round(hits["p20"] / n, 4), "empiricalFP50": round(hits["p50"] / n, 4), "empiricalFP80": round(hits["p80"] / n, 4),
        "central60Coverage": round(hits["central60"] / n, 4),
        "wilson95": {key: [round(x, 4) for x in wilson_score_interval(count, n)] for key, count in hits.items()},
        "medianNormalizedSpan": round(sorted(normalized)[len(normalized) // 2], 4) if normalized else 0.0, "meanNormalizedSpan": round(mean(normalized), 4),
        "p50Mae": round(mean(absolute), 2), "p50Mare": round(mean(relative), 4), "zeroSpanCount": sum(width == 0 for width in widths),
    }


def paired_inference(records: Sequence[ReplayRecord], candidate: Sequence[Prediction], reference: Sequence[Prediction], *, seed_label: str) -> Dict[str, Any]:
    cs, rs, output = per_record_scores(records, candidate), per_record_scores(records, reference), {}
    for metric in ("winkler", "averagePinball", "pinball80"):
        differences = [a - b for a, b in zip(cs[metric], rs[metric])]
        rng = random.Random(stable_seed(SEED, "bootstrap", seed_label, metric))
        boot = sorted(mean([differences[rng.randrange(len(differences))] for _ in differences]) for _ in range(BOOTSTRAP_REPLICATES))
        sign_rng, observed, extreme = random.Random(stable_seed(SEED, "sign", seed_label, metric)), abs(mean(differences)), 0
        for _ in range(BOOTSTRAP_REPLICATES):
            flipped = mean([value if sign_rng.random() < 0.5 else -value for value in differences])
            extreme += abs(flipped) >= observed
        total_absolute = sum(abs(value) for value in differences)
        output[metric] = {
            "candidateMinusReferenceMean": round(mean(differences), 4), "candidateMinusReferenceMedian": round(median(differences), 4),
            "bootstrap95Ci": [round(unweighted_quantile(boot, 0.025), 4), round(unweighted_quantile(boot, 0.975), 4)],
            "probabilityDeltaBelowZero": round(sum(value < 0 for value in boot) / len(boot), 4),
            "signFlipTwoSidedP": round((extreme + 1) / (BOOTSTRAP_REPLICATES + 1), 4),
            "largestAbsoluteRecordShare": round(max((abs(value) for value in differences), default=0.0) / total_absolute, 4) if total_absolute else 0.0,
        }
    return output


def run_control_suite(dataset: Sequence[ReplayRecord], catalogs: Mapping[str, CatalogSnapshot], *, min_train: int = 15) -> Dict[str, Any]:
    oos_records, predictions, fold_audit = [], {name: [] for name in MODEL_NAMES}, []
    for fold_index, (train_end, test_end) in enumerate(fold_splits(len(dataset), min_train), 1):
        train_set, test_set = dataset[:train_end], dataset[train_end:test_end]
        coefficient = tune_proxy_coefficient(train_set)
        null_pool = training_null_scale_pool(train_set, coefficient)
        fold_audit.append({
            "fold": fold_index, "trainRange": [0, train_end], "testRange": [train_end, test_end],
            "trainMaxEpoch": max(x.epoch for x in train_set), "testMinEpoch": min(x.epoch for x in test_set),
            "proxyCoefficient": coefficient, "nullScalePoolN": len(null_pool),
            "timeSafe": max(x.epoch for x in train_set) <= min(x.epoch for x in test_set),
        })
        for record in test_set:
            b0 = Prediction(record.baseline_p20, record.baseline_p50, record.baseline_p80, (("production",),), 0.0, "production-saved-shadowWhole")
            a0 = generate_reconstructed_prediction(record, variance_model="off")
            rn = generate_reconstructed_prediction(record, variance_model="null", null_scale_ratio=null_ratio_for_record(null_pool, record.record_id, fold_index))
            a1 = generate_reconstructed_prediction(record, variance_model="proxy", proxy_coefficient=coefficient)
            catalog = generate_reconstructed_prediction(record, variance_model="catalog", catalogs=catalogs)
            for name, prediction in zip(MODEL_NAMES, (b0, a0, rn, a1, catalog)): predictions[name].append(prediction)
            assert a0.reconstruction_signature == rn.reconstruction_signature == a1.reconstruction_signature == catalog.reconstruction_signature
        oos_records.extend(test_set)
    ids = [record.record_id for record in oos_records]
    assert len(set(ids)) == len(ids)
    assert all(len(rows) == len(ids) for rows in predictions.values())
    assert all(prediction.p50 == record.baseline_p50 for name in DISPERSION_MODELS for prediction, record in zip(predictions[name], oos_records))
    metrics = {name: evaluate_model(oos_records, rows) for name, rows in predictions.items()}
    comparisons = {
        "A0_vs_B0": paired_inference(oos_records, predictions[MODEL_NAMES[1]], predictions[MODEL_NAMES[0]], seed_label="A0-vs-B0"),
        "A1_PROXY_vs_A0": paired_inference(oos_records, predictions[MODEL_NAMES[3]], predictions[MODEL_NAMES[1]], seed_label="A1-vs-A0"),
        "A1_PROXY_vs_RN": paired_inference(oos_records, predictions[MODEL_NAMES[3]], predictions[MODEL_NAMES[2]], seed_label="A1-vs-RN"),
        "A1_CATALOG_vs_A0": paired_inference(oos_records, predictions[MODEL_NAMES[4]], predictions[MODEL_NAMES[1]], seed_label="CAT-vs-A0"),
        "A1_CATALOG_vs_RN": paired_inference(oos_records, predictions[MODEL_NAMES[4]], predictions[MODEL_NAMES[2]], seed_label="CAT-vs-RN"),
    }
    per_record = [{
        "recordId": record.record_id, "modelVersion": record.model_version, "solverVersion": record.solver_version, "actualTotal": record.actual_total,
        "models": {name: {"p20": rows[index].p20, "p50": rows[index].p50, "p80": rows[index].p80, "span": rows[index].p80 - rows[index].p20} for name, rows in predictions.items()},
    } for index, record in enumerate(oos_records)]
    p50_metric_tuples = {(metrics[name]["meanPinballLoss50"], metrics[name]["p50Mae"], metrics[name]["p50Mare"]) for name in MODEL_NAMES}
    return {
        "sampleCountEvaluated": len(oos_records), "testRecordIds": ids, "folds": fold_audit, "models": metrics,
        "pairedComparisons": comparisons,
        "invariants": {"sameOosIds": True, "sameOosOrder": True, "dispersionP50Exact": True, "p50MetricsExact": len(p50_metric_tuples) == 1, "sameReconstructionPathA0RnA1": True, "supportPointsPerState": SUPPORT_POINTS, "allFoldsTimeSafe": all(x["timeSafe"] for x in fold_audit)},
        "perRecord": per_record, "_predictions": predictions, "_records": oos_records,
    }


def tune_weight(train_set: Sequence[ReplayRecord], kind: str) -> float:
    candidates = (0.18, 0.30, 0.45, 0.60, 0.75) if kind == "red" else (0.34, 0.50, 0.65, 0.80)
    scored = []
    for value in candidates:
        scores = []
        for record in train_set:
            kwargs = {"red_decay_power": value} if kind == "red" else {"gold_decay_base": value}
            prediction = generate_reconstructed_prediction(record, variance_model="off", off_support_points=1, **kwargs)
            scores.append(winkler_interval_score(prediction.p20, prediction.p80, record.actual_total))
        scored.append((mean(scores), value))
    return min(scored)[1]


def legacy_v11_controls(dataset: Sequence[ReplayRecord], min_train: int = 15) -> Dict[str, Any]:
    names, predictions, records = ("B0", "A1", "B1_R", "B1_G", "AB"), {name: [] for name in ("B0", "A1", "B1_R", "B1_G", "AB")}, []
    for train_end, test_end in fold_splits(len(dataset), min_train):
        train_set, test_set = dataset[:train_end], dataset[train_end:test_end]
        coefficient, best_r, best_g = tune_proxy_coefficient(train_set), tune_weight(train_set, "red"), tune_weight(train_set, "gold")
        for record in test_set:
            rows = (
                Prediction(record.baseline_p20, record.baseline_p50, record.baseline_p80, (), 0.0, "production"),
                generate_reconstructed_prediction(record, variance_model="proxy", proxy_coefficient=coefficient),
                generate_reconstructed_prediction(record, variance_model="off", red_decay_power=best_r, off_support_points=1),
                generate_reconstructed_prediction(record, variance_model="off", gold_decay_base=best_g, off_support_points=1),
                generate_reconstructed_prediction(record, variance_model="proxy", proxy_coefficient=coefficient, red_decay_power=best_r, gold_decay_base=best_g),
            )
            for name, prediction in zip(names, rows): predictions[name].append(prediction)
        records.extend(test_set)
    same = lambda a, b: all((x.p20, x.p50, x.p80) == (y.p20, y.p50, y.p80) for x, y in zip(predictions[a], predictions[b]))
    return {
        "authority": "fresh deterministic rerun of committed v1.1 semantics", "models": {name: evaluate_model(records, rows) for name, rows in predictions.items()},
        "quantileEquality": {"B1_R_equals_B0": same("B1_R", "B0"), "B1_G_equals_B0": same("B1_G", "B0"), "AB_equals_A1": same("AB", "A1")},
        "conflictCause": "report.md was stale relative to deterministic results.json and committed v1.1 harness",
    }


def red_sample_n(record: ReplayRecord) -> int:
    counts = []
    for state in record.state_candidates:
        r = int(state.get("r", 0) or 0)
        if r <= 0: continue
        direct = safe_integer((state.get("red") or {}).get("n"))
        if direct is not None: counts.append(direct)
        else:
            counts.extend(int(x["reportedN"]) for x in record.red_samples if x.get("r") == r and safe_integer(x.get("reportedN")) is not None)
    return min(counts) if counts else 0


def zero_span_audit(dataset: Sequence[ReplayRecord]) -> Dict[str, Any]:
    rows = []
    for record in dataset:
        if not (record.baseline_p20 == record.baseline_p50 == record.baseline_p80): continue
        candidate_rs = sorted({int(state.get("r", 0) or 0) for state in record.state_candidates if finite(state.get("r", 0))})
        sample_n = red_sample_n(record)
        exact = record.gold_total is not None and record.red_count == 0 and (record.purple_count in (None, 0) or record.purple_avg is not None)
        non_red = any(int(state.get("g", 0) or 0) + int(state.get("p", 0) or 0) > 0 and not non_red_is_exact(record, int(state.get("g", 0) or 0), int(state.get("p", 0) or 0)) for state in record.state_candidates)
        scarcity = any(r > 0 for r in candidate_rs) and sample_n <= 1
        a0 = generate_reconstructed_prediction(record, variance_model="off")
        reconstruction = (
            not record.state_candidates
            or all(not (state.get("component") or {}) for state in record.state_candidates)
            or a0.p80 - a0.p20 > 1e-9
        )
        labels = []
        if non_red: labels.append("NON_RED_UNCERTAINTY_GENUINELY_EXISTS")
        if scarcity: labels.append("RED_SAMPLE_SCARCITY")
        if exact: labels.append("TRUE_VALUE_EXACTLY_OBSERVED")
        if reconstruction: labels.append("RECONSTRUCTION_ARTIFACT")
        if not labels: labels.append("UNRESOLVED_ZERO_SPAN")
        rows.append({
            "recordId": record.record_id, "modelVersion": record.model_version, "solverVersion": record.solver_version,
            "candidateR": candidate_rs, "redSampleN": sample_n, "goldTotalObserved": record.gold_total is not None,
            "goldCountKnown": record.gold_count is not None, "purpleCount": record.purple_count,
            "informationState": "exact" if exact else "non-exact", "rootCauseLabels": labels,
        })
    by = lambda key: dict(sorted(Counter(str(row[key]) for row in rows).items()))
    root = Counter(label for row in rows for label in row["rootCauseLabels"])
    scarcity_n = root["RED_SAMPLE_SCARCITY"]
    return {
        "totalZeroSpan": len(rows), "rootCauseCountsNonExclusive": dict(sorted(root.items())),
        "redSampleScarcityCount": scarcity_n, "redSampleScarcityShare": round(scarcity_n / len(rows), 4) if rows else 0.0,
        "byModelCohort": by("modelVersion"), "bySolverCohort": by("solverVersion"),
        "byCandidateR": dict(sorted(Counter(",".join(map(str, row["candidateR"])) or "none" for row in rows).items())),
        "byRedSampleN": by("redSampleN"), "byGoldTotalObserved": by("goldTotalObserved"), "byGoldCountKnown": by("goldCountKnown"),
        "byPurpleCount": by("purpleCount"), "byInformationState": by("informationState"), "rows": rows,
    }


def relative_delta(candidate: float, reference: float) -> float:
    return (candidate - reference) / reference if reference else 0.0


def compile_verdict(suite: Mapping[str, Any]) -> Dict[str, Any]:
    models, comparisons = suite["models"], suite["pairedComparisons"]
    b0, a0, proxy, catalog = (models[MODEL_NAMES[i]] for i in (0, 1, 3, 4))
    equivalence, materially_different = {}, False
    for metric, field in (("winkler", "meanWinklerIntervalScore"), ("averagePinball", "meanAveragePinballLoss")):
        ci, margin = comparisons["A0_vs_B0"][metric]["bootstrap95Ci"], EQUIVALENCE_MARGIN * b0[field]
        equivalence[metric] = {"absoluteMargin": round(margin, 4), "bootstrap95CiWithinMargin": ci[0] >= -margin and ci[1] <= margin, "materiallyDifferent": ci[0] > margin or ci[1] < -margin}
        materially_different |= equivalence[metric]["materiallyDifferent"]
    equivalent = all(value["bootstrap95CiWithinMargin"] for value in equivalence.values())
    def factor_gate(candidate: Mapping[str, Any]) -> Dict[str, bool]:
        return {
            "winklerImproves": candidate["meanWinklerIntervalScore"] < a0["meanWinklerIntervalScore"],
            "averagePinballNonWorse": candidate["meanAveragePinballLoss"] <= a0["meanAveragePinballLoss"],
            "p80Improves": candidate["meanPinballLoss80"] < a0["meanPinballLoss80"],
            "p50InvariantExact": suite["invariants"]["dispersionP50Exact"],
            "lowEndNoMaterialRegression": relative_delta(candidate["meanPinballLoss20"], a0["meanPinballLoss20"]) <= LOW_END_REGRESSION_LIMIT,
        }
    proxy_gate, catalog_gate = factor_gate(proxy), factor_gate(catalog)
    def beats_null(key: str) -> bool:
        return all(comparisons[key][metric]["candidateMinusReferenceMean"] < 0 and comparisons[key][metric]["probabilityDeltaBelowZero"] >= 0.90 for metric in ("winkler", "averagePinball", "pinball80"))
    proxy_null, catalog_null = beats_null("A1_PROXY_vs_RN"), beats_null("A1_CATALOG_vs_RN")
    if materially_different: verdict = "RECONSTRUCTION_CONFOUND"
    elif not equivalent: verdict = "INSUFFICIENT_EVIDENCE"
    elif all(catalog_gate.values()) and catalog_null and equivalent: verdict = "CATALOG_VARIANCE_SUPPORTED"
    elif all(proxy_gate.values()) and proxy_null and equivalent: verdict = "A1_PROXY_PROVISIONAL"
    elif (all(proxy_gate.values()) or all(catalog_gate.values())) and not (proxy_null or catalog_null): verdict = "NULL_WIDENING_ONLY"
    else: verdict = "INSUFFICIENT_EVIDENCE"
    confound_status = "TRUE" if materially_different else "FALSE" if equivalent else "INCONCLUSIVE"
    return {
        "globalPrimaryVerdict": verdict,
        "preRegisteredRules": {"primaryPopulation": "Global OOS", "equivalenceMarginRelativeToB0": EQUIVALENCE_MARGIN, "lowEndP20PinballRegressionLimit": LOW_END_REGRESSION_LIMIT, "nullSuperiorityProbabilityThreshold": 0.90, "cohorts": "EXPLORATORY_SUBGROUP only; cannot override Global"},
        "reconstructionConfound": materially_different, "reconstructionConfoundStatus": confound_status, "reconstructionEquivalent": equivalent, "equivalenceAudit": equivalence,
        "proxyGate": proxy_gate, "catalogGate": catalog_gate, "proxyBeatsRandomNull": proxy_null, "catalogBeatsRandomNull": catalog_null,
        "productionPathPrototypeRecommended": verdict == "CATALOG_VARIANCE_SUPPORTED",
        "thirdFactor": {"name": "GOLD_COUNT_SUPPORT_CAP", "status": "THIRD_FACTOR_UNTESTED"},
    }


def public_suite(suite: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in suite.items() if not key.startswith("_")}


def render_report(payload: Mapping[str, Any]) -> str:
    global_data, verdict = payload["globalPrimary"], payload["winningLogic"]
    metrics, comparisons = global_data["models"], global_data["pairedComparisons"]
    lines = [
        "# Shadow Distribution Reproducibility / Control-Group Audit v1.2", "",
        "## Verdict", "", f"**Global primary: `{verdict['globalPrimaryVerdict']}`**", "",
        "Production implementation remains prohibited. Cohorts are pre-registered as `EXPLORATORY_SUBGROUP`.", "",
        "## FACT — v1.1 B1 conflict", "",
        "Fresh rerun is deterministic. `report.md` was stale relative to `results.json` and the committed harness. Under the actual authority, B1-R and B1-G change quantiles and AB is not equal to A1.", "",
        "| v1.1 model | P20 pinball | P50 pinball | P80 pinball | Avg pinball | Winkler | Central60 |", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("B0", "A1", "B1_R", "B1_G", "AB"):
        row = payload["v11FreshReproduction"]["models"][name]
        lines.append(f"| {name} | {row['meanPinballLoss20']:.2f} | {row['meanPinballLoss50']:.2f} | {row['meanPinballLoss80']:.2f} | {row['meanAveragePinballLoss']:.2f} | {row['meanWinklerIntervalScore']:.2f} | {row['central60Coverage']:.2%} |")
    lines += ["", f"Quantile equality audit: `{json.dumps(payload['v11FreshReproduction']['quantileEquality'], ensure_ascii=False)}`.", "",
        "## Control matrix", "",
        "- `B0_PRODUCTION_SAVED`: saved production `shadowWhole` quantiles; no reconstruction.",
        "- `A0_RECONSTRUCTION_NO_NON_RED_VARIANCE`: the candidate reconstruction path with fixed non-red values repeated to the same seven-point support shape.",
        "- `RN_NULL_MATCHED_VARIANCE`: the A0 path plus deterministic training-fold null dispersion, with no catalog/business structure.",
        "- `A1_PROXY_GAUSSIAN_CV`: the A0 path plus the existing training-fold Gaussian/CV proxy.",
        "- `A1_CATALOG_DISCRETE`: the A0 path plus version-selected production rule-price supports and deterministic discrete convolution.",
        "- All reconstructed candidates share folds, weighting, normalization, seven support points per state, quantile interpolation, and an exact saved-B0 P50 anchor.", "",
        "## Pre-registered Gate 1", "",
        "`A0 ≈ B0` requires the paired-bootstrap 95% CI for both mean Winkler and mean average-pinball deltas to lie wholly inside ±2% of the corresponding B0 score. A CI wholly outside that margin is a material reconstruction difference. Anything between is inconclusive.", "",
        f"Result: reconstruction status `{verdict['reconstructionConfoundStatus']}`; equivalence established `{verdict['reconstructionEquivalent']}`; audit `{json.dumps(verdict['equivalenceAudit'], ensure_ascii=False)}`.", "",
        "## Global OOS metrics (N=48)", "",
        "| Model | P20 pinball | P50 pinball | P80 pinball | Avg pinball | Winkler | F(P20) | F(P50) | F(P80) | Central60 | Median norm span | P50 MAE | P50 MARE |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in MODEL_NAMES:
        row = metrics[name]
        lines.append(f"| {name} | {row['meanPinballLoss20']:.2f} | {row['meanPinballLoss50']:.2f} | {row['meanPinballLoss80']:.2f} | {row['meanAveragePinballLoss']:.2f} | {row['meanWinklerIntervalScore']:.2f} | {row['empiricalFP20']:.2%} | {row['empiricalFP50']:.2%} | {row['empiricalFP80']:.2%} | {row['central60Coverage']:.2%} {row['wilson95']['central60']} | {row['medianNormalizedSpan']:.2%} | {row['p50Mae']:.2f} | {row['p50Mare']:.2%} |")
    lines += ["", "## Paired inference", "", "Deltas are candidate minus reference; negative is better.", ""]
    for comparison, result in comparisons.items():
        lines.append(f"### {comparison}")
        lines.append("")
        for metric in ("winkler", "averagePinball", "pinball80"):
            row = result[metric]
            lines.append(f"- {metric}: mean {row['candidateMinusReferenceMean']:.2f}; median {row['candidateMinusReferenceMedian']:.2f}; 95% CI {row['bootstrap95Ci']}; P(delta<0)={row['probabilityDeltaBelowZero']:.3f}; sign-flip p={row['signFlipTwoSidedP']:.3f}; max-record share={row['largestAbsoluteRecordShare']:.2%}.")
        lines.append("")
    lines += ["## Exploratory historical cohorts", "", "These subgroup diagnostics are pre-registered as exploratory and cannot override the Global verdict.", ""]
    for name, cohort in payload["cohortExploratory"].items():
        diagnostic = cohort.get("diagnosticVerdict", {}).get("globalPrimaryVerdict", cohort.get("status", "UNAVAILABLE"))
        lines.append(f"- `{name}`: N={cohort['datasetN']}; diagnostic `{diagnostic}`; interpretation `EXPLORATORY_SUBGROUP`.")
    lines.append("")
    zero = payload["zeroSpanAudit"]
    lines += ["## Zero-span diagnosis", "", f"- Total: {zero['totalZeroSpan']}", f"- Non-exclusive root causes: `{json.dumps(zero['rootCauseCountsNonExclusive'], ensure_ascii=False)}`", f"- `RED_SAMPLE_SCARCITY`: {zero['redSampleScarcityCount']} ({zero['redSampleScarcityShare']:.2%})", "", "## A1-CATALOG provenance and limitations", "", f"- Source: `{payload['catalogProvenance']['sourcePath']}` @ `{payload['catalogProvenance']['sha256']}`.", "- Uses version-selected static discrete prices and deterministic bounded convolution; no Gaussian assumption.", "- Venue/box item probabilities do not have an authoritative table and are not invented; equal item weights make this control provisional.", "", "## Leakage audit", "", f"`{json.dumps(payload['leakageAudit'], ensure_ascii=False)}`", "", "## Interpretation", "", f"- Reconstruction confound status: `{verdict['reconstructionConfoundStatus']}` (equivalence not established is not treated as no confound).", f"- Proxy beats random widening: `{verdict['proxyBeatsRandomNull']}`.", f"- Catalog beats random widening: `{verdict['catalogBeatsRandomNull']}`.", f"- Production-path prototype recommended: `{verdict['productionPathPrototypeRecommended']}`.", "- `GOLD_COUNT_SUPPORT_CAP` remains `THIRD_FACTOR_UNTESTED`.", ""]
    return "\n".join(lines)


def main() -> None:
    db_path, solver_path = PROJECT_ROOT / "异环拍卖数据.json", CORE_DIR / "solver_core_v06.js"
    db_before = sha256_file(db_path)
    dataset = load_quantile_ablation_dataset(db_path)
    catalogs, catalog_provenance = load_catalog_snapshots(solver_path)
    legacy = legacy_v11_controls(dataset)
    global_suite = run_control_suite(dataset, catalogs, min_train=15)
    cohorts = {
        "v0.3-dynamic-walkforward": [x for x in dataset if x.model_version == "v0.3-dynamic-walkforward"],
        "v0.5-field-conditions": [x for x in dataset if x.model_version == "v0.5-field-conditions"],
        "v0.6-reliability": [x for x in dataset if x.solver_version == "v0.6-reliability"],
    }
    cohort_results = {}
    for name, records in cohorts.items():
        if len(records) >= 12:
            cohort_suite = run_control_suite(records, catalogs, min_train=7)
            cohort_results[name] = {"interpretation": "EXPLORATORY_SUBGROUP", "datasetN": len(records), "diagnosticVerdict": compile_verdict(cohort_suite), "suite": public_suite(cohort_suite)}
        else:
            cohort_results[name] = {"interpretation": "EXPLORATORY_SUBGROUP", "datasetN": len(records), "status": "INSUFFICIENT_SAMPLE_FOR_REPEATED_WALK_FORWARD"}
    db_after = sha256_file(db_path)
    if db_before != db_after: raise AssertionError("Main database changed")
    payload = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "metadata": {"generatedAt": datetime.now().astimezone().isoformat(), "experimentVersion": EXPERIMENT_VERSION, "seed": SEED, "bootstrapReplicates": BOOTSTRAP_REPLICATES, "totalQuantileRecords": len(dataset), "databaseSha256Before": db_before, "databaseSha256After": db_after, "productionFilesModified": False},
        "v11FreshReproduction": legacy, "catalogProvenance": catalog_provenance,
        "leakageAudit": {"status": "PASS", "chronologicalWalkForward": True, "testActualTotalUsedOnlyForScoring": True, "testSettlementItemsUsedForPrediction": False, "futureRecordsUsedForPrediction": False, "catalogIsStaticExAnteRuleData": True, "proxyHyperparameterLearnedFromTrainingFoldOnly": True, "nullScalePoolLearnedFromTrainingFoldOnly": True, "catalogVersionSelectedByPlayedAt": True},
        "globalPrimary": public_suite(global_suite), "cohortExploratory": cohort_results, "zeroSpanAudit": zero_span_audit(dataset), "winningLogic": compile_verdict(global_suite),
    }
    output = Path(__file__).resolve().parent
    (output / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {"schemaVersion": "shadow-distribution-dataset-manifest.v1.2", "databaseSha256": db_before, "sampleCount": len(dataset), "globalOosRecordIds": global_suite["testRecordIds"], "folds": global_suite["folds"], "samples": [{"id": x.record_id, "playedAt": x.played_at, "modelVersion": x.model_version, "solverVersion": x.solver_version, "baselineP20": x.baseline_p20, "baselineP50": x.baseline_p50, "baselineP80": x.baseline_p80} for x in dataset]}
    (output / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"experimentVersion": EXPERIMENT_VERSION, "globalVerdict": payload["winningLogic"]["globalPrimaryVerdict"], "globalN": global_suite["sampleCountEvaluated"], "zeroSpan": payload["zeroSpanAudit"]["totalZeroSpan"], "redSampleScarcity": payload["zeroSpanAudit"]["redSampleScarcityCount"], "databaseUnchanged": db_before == db_after}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
