# -*- coding: utf-8 -*-
"""Read-time Effective Truth Resolver for Settlement Records.

Provides pure functional resolution from (Persisted Record + Review Sidecar)
to an effective evaluation record view.
Never mutates input dict or persistent database files.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from settlement_truth_reviewer import ReviewStoreManager, project_tier3_truth_evidence


def resolve_effective_record_truth(
    record: Mapping[str, Any],
    data_root: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Pure read-time resolver for effective settlement truth.

    If the record contains a Tier 1 Truth Evidence object, and a valid terminal
    confirmed/corrected Review Artifact exists in the review sidecar store,
    projects Tier 3 Truth into the returned effective record copy.
    
    If the review is rejected or does not exist, retains the existing Tier 1 evidence.
    """
    if not isinstance(record, Mapping):
        return dict(record) if isinstance(record, dict) else {}

    rec_copy = copy.deepcopy(dict(record))
    settlement = rec_copy.get("settlement")
    if not isinstance(settlement, dict):
        return rec_copy

    truth = settlement.get("truthEvidence")
    if not isinstance(truth, dict):
        return rec_copy

    match_id = str(truth.get("matchId") or rec_copy.get("id") or "").strip()
    source_hash = str(truth.get("truthPayloadSha256") or "").strip()
    if not match_id or not source_hash:
        return rec_copy

    review_store = ReviewStoreManager(data_root=data_root)
    review_artifact = review_store.get_terminal_review(match_id, source_hash)
    if review_artifact:
        tier3 = project_tier3_truth_evidence(truth, review_artifact, data_dir=data_root)
        if tier3 is not None:
            settlement["truthEvidence"] = tier3

    return rec_copy
