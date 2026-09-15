# -*- coding: utf-8 -*-
"""Small, append-only links from a live match draft to raw captures.

The image bytes and their authoritative descriptors remain owned by
SettlementEvidenceStoreV2.  This module only builds the non-business metadata
needed to keep a capture associated with the same match across restarts and
exports.  It never promotes a DRAFT or invents settlement facts.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Optional


SCHEMA_VERSION = "settlement-capture-links.v1"


def _capture_projection(descriptor: Mapping[str, Any]) -> Dict[str, Any]:
    """Return only stable, relocatable fields from a trusted store descriptor."""
    fields = (
        "evidenceId",
        "recordStableKey",
        "kind",
        "capturedAt",
        "relativePath",
        "sha256",
        "byteSize",
        "mimeType",
        "width",
        "height",
        "coverageMode",
        "coverageStatus",
        "evidenceOrigin",
        "captureSequence",
        "captureSource",
        "sourceFrameAt",
    )
    return {key: descriptor[key] for key in fields if key in descriptor}


def merge_capture_link(
    existing: Optional[Mapping[str, Any]],
    descriptor: Mapping[str, Any],
    *,
    match_id: str,
    source_instance_id: str,
    app_version: Optional[str] = None,
    catalog_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one saved capture without replacing prior, clearer originals."""
    prior = copy.deepcopy(dict(existing)) if isinstance(existing, Mapping) else {}
    captures = prior.get("captures")
    if not isinstance(captures, list):
        captures = []

    incoming = _capture_projection(descriptor)
    incoming_id = str(incoming.get("evidenceId") or "")
    incoming_sha = str(incoming.get("sha256") or "")
    already_present = False
    merged = []
    for raw in captures:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        same_id = incoming_id and str(item.get("evidenceId") or "") == incoming_id
        same_bytes = (
            incoming_sha
            and str(item.get("sha256") or "") == incoming_sha
            and str(item.get("kind") or "") == str(incoming.get("kind") or "")
        )
        if same_id or same_bytes:
            already_present = True
            # Keep the original entry's identity, but accept missing descriptor
            # fields from the newly verified store result.
            for key, value in incoming.items():
                item.setdefault(key, value)
        merged.append(item)
    if not already_present:
        merged.append(incoming)

    merged.sort(key=lambda item: (str(item.get("capturedAt") or ""), str(item.get("evidenceId") or "")))
    result: Dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "matchId": str(match_id),
        "sourceInstanceId": str(prior.get("sourceInstanceId") or source_instance_id),
        "captures": merged,
    }
    for key, value in (
        ("appVersion", app_version),
        ("catalogVersion", catalog_version),
    ):
        if prior.get(key) not in (None, ""):
            result[key] = prior[key]
        elif value not in (None, ""):
            result[key] = str(value)
    return result

