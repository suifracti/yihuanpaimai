# -*- coding: utf-8 -*-
"""Prediction Evaluation Artifact v1 Generator (Dual-Track Architecture).

Produces an immutable, versioned evaluation artifact cleanly separating:
1. formalEvaluation: Strictly for formally eligible records (provenance verified).
2. legacyExploratoryEvaluation: For exploratory research, empirical priors, and legacy diagnostics.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

_CORE_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _CORE_DIR.parent
_APP_DIR = _ROOT_DIR / "app"
for _p in (str(_CORE_DIR), str(_APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from evaluation_eligibility import (
    ELIGIBILITY_CONTRACT_VERSION,
    ModelCohort,
    build_duplicate_index,
    evaluate_record_eligibility,
)
from evaluation_metrics import calculate_point_and_quantile_metrics
from history_admission import (
    HISTORY_ADMISSION_POLICY_VERSION,
    evaluate_history_admission,
)
from legacy_exploratory_policy import (
    LEGACY_EXPLORATORY_POLICY_VERSION,
    classify_legacy_record,
)
from runtime_revision import get_code_revision
from version import APP_PRODUCT_VERSION


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_prediction_evaluation_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    source_sha256: str = "fixture_sha256",
    dataset_schema_version: Optional[int | str] = 6,
    data_root: Optional[Path | str] = None,
    publication_policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a dual-track Prediction Evaluation Summary Artifact v1."""
    pub_policy = dict(publication_policy or {})
    policy_status = str(pub_policy.get("policyStatus", "PROVISIONAL"))
    min_preliminary = int(pub_policy.get("minimumForPreliminary", 5))
    min_official = int(pub_policy.get("minimumForOfficial", 20))

    code_rev = get_code_revision()
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    artifact_id = f"eval_summary_{int(datetime.now().timestamp())}_{hashlib.sha256(source_sha256.encode('utf-8')).hexdigest()[:8]}"

    duplicate_index = build_duplicate_index(records)

    # 1. Record Schema Composition & History Admission Scan
    schema_composition = Counter()
    admitted_count = 0
    excluded_count = 0
    exclusion_reasons = Counter()

    for r in records:
        if not isinstance(r, Mapping):
            continue
        sv = r.get("schemaVersion")
        ls = str(r.get("lifecycleStatus") or "").strip().upper()
        if sv == 7:
            if ls == "FINALIZED":
                schema_composition["canonicalV7Finalized"] += 1
            elif ls == "DRAFT":
                schema_composition["canonicalV7Draft"] += 1
            else:
                schema_composition["canonicalV7Other"] += 1
        else:
            schema_composition["legacyOrSchemaLess"] += 1

        adm = evaluate_history_admission(r, duplicate_index)
        if adm.admitted:
            admitted_count += 1
        else:
            excluded_count += 1
            if adm.exclusion_reason:
                exclusion_reasons[adm.exclusion_reason] += 1

    # 2. Formal Evaluation Track
    formal_eligible_samples: List[Dict[str, Any]] = []
    formal_cohort_samples: Dict[str, List[Dict[str, Any]]] = {}
    formal_rejections = Counter()

    for r in records:
        res = evaluate_record_eligibility(r, duplicate_index, data_root=data_root)
        if res.formally_eligible:
            truth_dict = (r.get("settlement") or {}).get("truthEvidence") or {}
            actual_val = truth_dict.get("actualTotal") or (r.get("settlement") or {}).get("actualTotal") or r.get("actualTotal")
            snap = r.get("predictionSnapshot") or {}
            fc = snap.get("forecast") or {}
            quantiles = fc.get("quantiles") or {}

            sample_entry = {
                "id": r.get("id"),
                "actual": float(actual_val) if actual_val else None,
                "estimate": float(quantiles.get("p50")) if "p50" in quantiles else None,
                "p20": float(quantiles.get("p20")) if "p20" in quantiles else None,
                "p50": float(quantiles.get("p50")) if "p50" in quantiles else None,
                "p80": float(quantiles.get("p80")) if "p80" in quantiles else None,
            }
            formal_eligible_samples.append(sample_entry)
            cohort_key = res.cohort.key() if res.cohort else "unknown"
            formal_cohort_samples.setdefault(cohort_key, []).append(sample_entry)
        else:
            if res.primary_reason:
                formal_rejections[res.primary_reason] += 1

    formal_count = len(formal_eligible_samples)
    if formal_count == 0:
        formal_status = "NOT_AVAILABLE_YET"
        formal_reason = "Zero formally eligible match records found in history database."
        formal_metrics = None
    elif formal_count < min_preliminary:
        formal_status = "INSUFFICIENT_SAMPLE"
        formal_reason = f"Sample count ({formal_count}) is below minimum preliminary threshold ({min_preliminary})."
        formal_metrics = None
    elif formal_count < min_official:
        formal_status = "PRELIMINARY"
        formal_reason = f"Sample count ({formal_count}) satisfies preliminary threshold ({min_preliminary}) but below official threshold ({min_official})."
        formal_metrics = calculate_point_and_quantile_metrics(formal_eligible_samples)
    else:
        formal_status = "AVAILABLE"
        formal_reason = f"Sample count ({formal_count}) satisfies official threshold ({min_official})."
        formal_metrics = calculate_point_and_quantile_metrics(formal_eligible_samples)

    formal_cohort_payloads = []
    for c_key, c_samples in sorted(formal_cohort_samples.items()):
        c_count = len(c_samples)
        c_metrics = calculate_point_and_quantile_metrics(c_samples) if formal_status in {"PRELIMINARY", "AVAILABLE"} else None
        formal_cohort_payloads.append({
            "cohortKey": c_key,
            "sampleCount": c_count,
            "metrics": c_metrics,
        })

    # 3. Legacy Exploratory Evaluation Track
    legacy_classifications = [classify_legacy_record(r, duplicate_index) for r in records]

    point_candidates = [c for c in legacy_classifications if c.is_point_candidate]
    quantile_candidates = [c for c in legacy_classifications if c.is_quantile_candidate]
    dist_only_candidates = [c for c in legacy_classifications if c.is_distribution_only]
    unusable_candidates = [c for c in legacy_classifications if c.is_unusable]

    legacy_quality_flags = Counter()
    for c in legacy_classifications:
        for f in c.quality_flags:
            legacy_quality_flags[f] += 1

    legacy_point_samples = [
        {
            "id": c.record_id,
            "actual": c.actual_total,
            "estimate": c.point_estimate,
            "p20": c.p20,
            "p50": c.p50,
            "p80": c.p80,
        }
        for c in point_candidates
    ]

    legacy_overall_metrics = calculate_point_and_quantile_metrics(legacy_point_samples)
    legacy_status = "AVAILABLE" if legacy_overall_metrics is not None else "NOT_AVAILABLE_YET"

    # Cohort grouping for legacy
    legacy_cohort_groups: Dict[str, List[Dict[str, Any]]] = {}
    for c, s in zip(point_candidates, legacy_point_samples):
        group_key = f"{c.solver_version or 'unknown'}|{c.model_version or 'unknown'}|{c.catalog_version or 'unknown'}"
        legacy_cohort_groups.setdefault(group_key, []).append(s)

    legacy_cohort_payloads = []
    for g_key, g_samples in sorted(legacy_cohort_groups.items()):
        g_metrics = calculate_point_and_quantile_metrics(g_samples)
        legacy_cohort_payloads.append({
            "groupKey": g_key,
            "sampleCount": len(g_samples),
            "metrics": g_metrics,
        })

    # 4. Construct Artifact Payload
    artifact_payload: Dict[str, Any] = {
        "schemaVersion": "prediction-evaluation-summary.v1",
        "artifactMetadata": {
            "artifactId": artifact_id,
            "generatedAt": now_iso,
            "generator": {
                "name": "prediction_evaluation_engine",
                "version": APP_PRODUCT_VERSION,
                "codeRevision": code_rev,
                "runtime": f"cpython-{sys.version_info.major}.{sys.version_info.minor}",
            },
            "eligibilityContractVersion": ELIGIBILITY_CONTRACT_VERSION,
            "historyAdmissionPolicyVersion": HISTORY_ADMISSION_POLICY_VERSION,
            "publicationPolicy": {
                "policyStatus": policy_status,
                "minimumForPreliminary": min_preliminary,
                "minimumForOfficial": min_official,
            },
        },
        "source": {
            "sourceId": "canonical_match_history",
            "datasetSchemaVersion": dataset_schema_version,
            "sha256": source_sha256,
            "recordCount": len(records),
            "recordSchemaComposition": dict(sorted(schema_composition.items())),
        },
        "admission": {
            "admittedCount": admitted_count,
            "excludedCount": excluded_count,
            "exclusionReasonCounts": dict(sorted(exclusion_reasons.items())),
        },
        "formalEvaluation": {
            "eligibility": {
                "formallyEligibleCount": formal_count,
                "primaryRejectionReasonCounts": dict(sorted(formal_rejections.items())),
            },
            "availability": {
                "status": formal_status,
                "reason": formal_reason,
            },
            "cohorts": formal_cohort_payloads,
            "overallMetrics": {
                "status": formal_status,
                "sampleCount": formal_count,
                "metrics": formal_metrics,
            },
        },
        "legacyExploratoryEvaluation": {
            "policyVersion": LEGACY_EXPLORATORY_POLICY_VERSION,
            "publicationStatus": "EXPLORATORY_ONLY",
            "formalComparable": False,
            "provenanceLevel": "LEGACY_INCOMPLETE",
            "sampleInventory": {
                "admittedCount": admitted_count,
                "pointMetricCandidateCount": len(point_candidates),
                "quantileMetricCandidateCount": len(quantile_candidates),
                "distributionOnlyCount": len(dist_only_candidates),
                "unusableCount": len(unusable_candidates),
            },
            "qualityFlagCounts": dict(sorted(legacy_quality_flags.items())),
            "cohorts": legacy_cohort_payloads,
            "overallMetrics": {
                "status": legacy_status,
                "sampleCount": len(point_candidates),
                "metrics": legacy_overall_metrics,
            },
        },
    }

    # 5. Compute deterministic artifactPayloadSha256
    raw_payload_bytes = _canonical_json_bytes(artifact_payload)
    artifact_payload["artifactPayloadSha256"] = hashlib.sha256(raw_payload_bytes).hexdigest()

    return artifact_payload


def generate_evaluation_artifact_from_file(
    db_path: Path | str,
    output_dir: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Read database file, generate summary artifact, and optionally save to disk."""
    p = Path(db_path).resolve()
    raw_bytes = p.read_bytes()
    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    data = json.loads(raw_bytes.decode("utf-8"))
    records = data.get("records") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    dataset_schema_ver = data.get("schemaVersion", 6) if isinstance(data, dict) else None

    artifact = generate_prediction_evaluation_summary(
        records,
        source_sha256=source_sha256,
        dataset_schema_version=dataset_schema_ver,
        data_root=p.parent,
    )

    if output_dir:
        out_dir = Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        art_id = artifact["artifactMetadata"]["artifactId"]
        target_file = out_dir / f"{art_id}.json"
        latest_file = out_dir / "latest.json"

        content_str = json.dumps(artifact, ensure_ascii=False, indent=2)
        target_file.write_text(content_str, encoding="utf-8")
        latest_file.write_text(content_str, encoding="utf-8")

    return artifact
