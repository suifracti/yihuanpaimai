# -*- coding: utf-8 -*-
"""Shared Transaction Authority for Canonical Match History Database.

Provides:
1. Process-wide reentrant locking plus a per-database OS lock for independent writers.
2. Transaction lifecycle: Lock -> Re-read latest disk -> Validate Transition -> Modify -> Tmp -> Fsync -> Replace -> Re-read Verify.
3. Strict idempotency and conflict rules:
   - Existing FINALIZED + identical content -> Idempotent no-op (returns existing).
   - Existing FINALIZED + differing content -> FinalizedRecordConflictError (fail-closed).
   - Existing DRAFT + incoming FINALIZED -> Validated transition to FINALIZED.
   - Existing DRAFT + incoming DRAFT -> Draft update.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

_ORIG_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

_CORE_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _CORE_DIR.parent
_APP_DIR = _ROOT_DIR / "app"
for _p in (str(_CORE_DIR), str(_APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from canonical_match_record import (
    validate_canonical_match_record_v7,
    validate_finalized_match_record_v7,
)
from runtime_data import resolve_runtime_history_path
from history_file_lock import history_file_lock

_HISTORY_STORE_LOCK = threading.RLock()


class HistoryStoreError(Exception):
    """Base error for canonical history store operations."""


class FinalizedRecordConflictError(HistoryStoreError):
    """Raised when attempting to overwrite an already finalized record with differing content."""


def _canonical_json_str(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _verify_authoritative_item_name(
    cat_id: Any,
    provided_name: Optional[str],
    authority: Any,
    context: str = "item",
) -> str:
    cat_id_str = str(cat_id or "").strip()
    if not cat_id_str:
        raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: {context} missing catalogId")
    cat_rec = authority.get(cat_id_str)
    if cat_rec is None:
        raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: unknown catalogId '{cat_id_str}' in {context}")
    auth_name = str(cat_rec.get("name") or "").strip()
    if not auth_name:
        raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: catalog item '{cat_id_str}' lacks authoritative name")
    if not provided_name or not str(provided_name).strip():
        raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: {context} for '{cat_id_str}' lacks canonicalName")
    clean_provided = str(provided_name).strip()
    if clean_provided == cat_id_str:
        raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: canonicalName cannot be catalogId '{cat_id_str}' in {context}")
    if clean_provided != auth_name:
        raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: candidate name mismatch for '{cat_id_str}' in {context}: expected '{auth_name}', got '{clean_provided}'")
    return auth_name


_verify_human_confirmed_item_name = _verify_authoritative_item_name


def _extract_match_keys(rec: Any) -> set[str]:
    """Extract physical match identity keys from a record or record-like mapping."""
    if not isinstance(rec, Mapping):
        return set()
    keys = set()
    for k in ("id", "recordStableKey", "matchId"):
        val = str(rec.get(k) or "").strip()
        if val and val.lower() not in ("standard", "null", "none", "unknown", "undefined"):
            keys.add(val)
    st = rec.get("settlement")
    if isinstance(st, Mapping):
        for k in ("recordStableKey", "matchId"):
            val = str(st.get(k) or "").strip()
            if val and val.lower() not in ("standard", "null", "none", "unknown", "undefined"):
                keys.add(val)
    bd = rec.get("bidding")
    if isinstance(bd, Mapping):
        val = str(bd.get("matchId") or "").strip()
        if val and val.lower() not in ("standard", "null", "none", "unknown", "undefined"):
            keys.add(val)
    return keys


def _extract_evidence_shas(rec: Any) -> set[str]:
    """Extract evidence blob SHA-256 digests from truthEvidence fileOriginals."""
    if not isinstance(rec, Mapping):
        return set()
    shas = set()
    st = rec.get("settlement")
    if isinstance(st, Mapping):
        truth = st.get("truthEvidence")
        if isinstance(truth, Mapping):
            for orig in truth.get("fileOriginals") or []:
                if not isinstance(orig, Mapping):
                    continue
                sha = str(orig.get("sha256") or "").strip().lower()
                if _ORIG_SHA_RE.fullmatch(sha):
                    shas.add(sha)
    return shas


def _can_merge_records(rec1: Mapping[str, Any], rec2: Mapping[str, Any]) -> bool:
    """Determine whether two records represent the exact same physical match.

    Rules:
    1. Origin Guard: If both records declare an execution/data origin (e.g. 'live' vs 'replay' or 'test')
       and they differ, they must NEVER merge.
    2. Primary Key Match: If they share at least one physical match key (id, recordStableKey, matchId),
       they are the same match and may merge.
    3. Conflicting Explicit IDs: If both records have non-draft, non-empty primary IDs and their
       keys do not intersect, they are distinct matches and MUST NOT merge, even if they reference
       identical evidence blob SHAs.
    4. Replay Draft Continuation: A replay record (id or recordStableKey starting with 'replayfile_')
       can only merge with an un-finalized draft record if the draft provably originated from the same
       replay source (matching replaySourceFingerprint or sourceFingerprint) and is NOT a live match.
    5. Draft Separation: Live draft records with distinct draft IDs are distinct sessions and must
       NOT merge based on evidence blob hashes alone.
    """
    if not isinstance(rec1, Mapping) or not isinstance(rec2, Mapping):
        return False

    orig1 = str(rec1.get("dataOrigin") or rec1.get("executionOrigin") or "").strip().lower()
    orig2 = str(rec2.get("dataOrigin") or rec2.get("executionOrigin") or "").strip().lower()
    if orig1 and orig2 and orig1 != orig2:
        return False

    keys1 = _extract_match_keys(rec1)
    keys2 = _extract_match_keys(rec2)

    # 1. Direct primary key match
    if keys1 and keys2 and (keys1 & keys2):
        return True

    # Check for explicit non-draft IDs
    def _is_explicit(k: str) -> bool:
        lk = k.lower()
        return not (lk.startswith("draft_") or lk.startswith("auto_"))

    exp1 = {k for k in keys1 if _is_explicit(k)}
    exp2 = {k for k in keys2 if _is_explicit(k)}

    # 2. Conflicting explicit IDs: both have explicit IDs that do not match -> NEVER merge
    if exp1 and exp2:
        return False

    # 3. If either is explicitly live, distinct draft IDs cannot merge
    if orig1 == "live" or orig2 == "live":
        return False

    # 4. Replay draft continuation (only allowed when non-live and provably same replay source)
    rep_key1 = next((k for k in keys1 if k.startswith("replayfile_")), None)
    rep_key2 = next((k for k in keys2 if k.startswith("replayfile_")), None)
    rep_key = rep_key1 or rep_key2
    draft_rec = rec2 if rep_key1 else (rec1 if rep_key2 else None)
    if rep_key and draft_rec:
        fp = rep_key[len("replayfile_"):]
        draft_fp = str(
            draft_rec.get("replaySourceFingerprint")
            or draft_rec.get("sourceFingerprint")
            or ""
        ).strip().lower()
        if draft_fp and draft_fp == fp:
            return True
        # If draft has no explicit fingerprint, check truth evidence sha if explicitly replay origin
        draft_orig = str(draft_rec.get("dataOrigin") or draft_rec.get("executionOrigin") or "").strip().lower()
        if draft_orig == "replay":
            shas = _extract_evidence_shas(draft_rec)
            if fp in shas:
                return True

    return False


def _deduplicate_records(raw_records: List[Any]) -> List[Dict[str, Any]]:
    """Defensively deduplicate records by physical match identity.

    1 match = 1 canonical history record.
    FINALIZED records always take precedence over DRAFT/CANCELLED.
    If multiple records of same status exist, the one with richer evidence / later timestamp is kept.
    Preserves original order of appearance while removing duplicate occurrences.
    """
    if not raw_records:
        return []

    groups: List[Dict[str, Any]] = []

    for item in raw_records:
        if not isinstance(item, dict):
            continue

        target_idx = None
        for idx, curr in enumerate(groups):
            if _can_merge_records(curr, item):
                target_idx = idx
                break

        if target_idx is None:
            groups.append(item)
            continue

        curr = groups[target_idx]
        curr_status = str(curr.get("lifecycleStatus") or "").strip().upper()
        item_status = str(item.get("lifecycleStatus") or "").strip().upper()

        # Choose winner between curr and item
        winner = curr
        loser = item
        if item_status == "FINALIZED" and curr_status != "FINALIZED":
            winner = item
            loser = curr
        elif curr_status == "FINALIZED" and item_status != "FINALIZED":
            winner = curr
            loser = item
        else:
            curr_caps = len(((curr.get("settlement") or {}).get("evidenceAttachments") or {}).get("captures") or [])
            item_caps = len(((item.get("settlement") or {}).get("evidenceAttachments") or {}).get("captures") or [])
            if item_caps > curr_caps:
                winner = item
                loser = curr
            else:
                curr_time = str(curr.get("playedAt") or "")
                item_time = str(item.get("playedAt") or "")
                if item_time > curr_time:
                    winner = item
                    loser = curr

        # Preserve sidecars from loser into winner if missing
        merged = copy.deepcopy(winner)
        if "predictionSnapshot" in loser and "predictionSnapshot" not in merged:
            merged["predictionSnapshot"] = copy.deepcopy(loser["predictionSnapshot"])
        if "intelCardEvidence" in loser and "intelCardEvidence" not in merged:
            merged["intelCardEvidence"] = copy.deepcopy(loser["intelCardEvidence"])
        m_st = merged.setdefault("settlement", {})
        l_st = loser.get("settlement") or {}
        for f in ("warehouseOccupancy", "warehouseIdentityReview", "reviewUnits", "warehouseReviewUnits", "truthEvidence", "evidenceAttachments"):
            if f in l_st and f not in m_st:
                m_st[f] = copy.deepcopy(l_st[f])

        groups[target_idx] = merged

    return groups


class CanonicalHistoryStore:
    """Shared transactional storage manager for canonical match records."""

    def __init__(self, db_path: Optional[Path | str] = None):
        if db_path is None:
            self.db_path = resolve_runtime_history_path()
        else:
            self.db_path = Path(db_path).resolve()

    def read_database(self) -> Dict[str, Any]:
        """Read latest database state from disk."""
        with _HISTORY_STORE_LOCK:
            if not self.db_path.exists():
                return {"version": "v0.6", "schemaVersion": 6, "records": []}
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    if "records" not in loaded and isinstance(loaded.get("games"), list):
                        loaded["records"] = loaded["games"]
                    elif "records" not in loaded:
                        raise HistoryStoreError("Canonical history object has no records array")
                    if not isinstance(loaded.get("records"), list):
                        raise HistoryStoreError("Canonical history records must be an array")
                    loaded["records"] = _deduplicate_records(loaded["records"])
                    return loaded
                elif isinstance(loaded, list):
                    return {"version": "v0.6", "schemaVersion": 6, "records": _deduplicate_records(loaded)}
                raise HistoryStoreError("Canonical history root must be an object or array")
            except HistoryStoreError:
                raise
            except Exception as e:
                raise HistoryStoreError(f"Failed to read canonical database {self.db_path}: {e}") from e

    def lookup(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Return a persisted record by ID, recordStableKey, or matchId, or None if it does not exist."""
        lookup_id = str(record_id or "").strip()
        if not lookup_id:
            return None
        db_data = self.read_database()
        records = db_data.get("records") or []
        for r in records:
            if isinstance(r, dict):
                r_keys = _extract_match_keys(r)
                if lookup_id in r_keys or str(r.get("id") or "").strip() == lookup_id:
                    return r
        return None

    get_record = lookup

    def persist_draft_warehouse_occupancy(
        self, record_id: str, occupancy: Mapping[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Replace or append warehouse occupancy on existing DRAFT match under the store lock."""
        if not str(record_id or "").strip() or not occupancy:
            return None
        with _HISTORY_STORE_LOCK, history_file_lock(self.db_path):
            existing = self.get_record(record_id)
            if existing is None or str(existing.get("lifecycleStatus") or "").upper() != "DRAFT":
                return None
            updated = copy.deepcopy(existing)
            settlement = updated.get("settlement")
            if not isinstance(settlement, dict):
                settlement = {}
                updated["settlement"] = settlement
            settlement["warehouseOccupancy"] = copy.deepcopy(dict(occupancy))
            return self.persist_record_transactional(updated, is_finalized=False)

    persist_warehouse_occupancy = persist_draft_warehouse_occupancy

    def persist_warehouse_evidence(
        self,
        record_id: str,
        *,
        match_id: Optional[str] = None,
        record_stable_key: Optional[str] = None,
        occupancy: Optional[Mapping[str, Any]] = None,
        identity_review: Optional[Mapping[str, Any]] = None,
        review_units: Optional[Sequence[Mapping[str, Any]]] = None,
        review_packet: Optional[Mapping[str, Any]] = None,
        catalog: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """Atomically merges warehouse evidence into an existing record (DRAFT or FINALIZED).

        Preserves pre-match predictions, round quotes, bidding details, and all existing facts.
        Protects prior human decisions inside the store lock.
        Rejects misattribution / non-existent records fail-closed.
        """
        # 1. Multi-identifier resolution and consistency check
        id_inputs = {}
        if record_id and str(record_id).strip():
            id_inputs["record_id"] = str(record_id).strip()
        if match_id and str(match_id).strip():
            id_inputs["match_id"] = str(match_id).strip()
        if record_stable_key and str(record_stable_key).strip():
            id_inputs["record_stable_key"] = str(record_stable_key).strip()

        if not id_inputs:
            return None

        with _HISTORY_STORE_LOCK, history_file_lock(self.db_path):
            resolved_records = {}
            for param_name, param_val in id_inputs.items():
                rec = self.get_record(param_val)
                if rec is None:
                    # Non-existent target fails closed
                    return None
                resolved_records[param_name] = rec

            # Verify that ALL provided identifiers resolve to the EXACT SAME canonical record
            first_rec = next(iter(resolved_records.values()))
            actual_id = str(first_rec.get("id") or "")
            for param_name, rec in resolved_records.items():
                if str(rec.get("id") or "") != actual_id:
                    # Cross-match identifier conflict: reject fail-closed!
                    return None

            # Verify match_id matches the record's played_match_id or matchId
            if "match_id" in id_inputs:
                m_id = id_inputs["match_id"]
                rec_m = str(first_rec.get("played_match_id") or first_rec.get("matchId") or "")
                rec_st = str(first_rec.get("recordStableKey") or "")
                if rec_m and rec_m != m_id and rec_st != m_id and actual_id != m_id:
                    return None

            # Verify record_stable_key matches the record's recordStableKey
            if "record_stable_key" in id_inputs:
                st_key = id_inputs["record_stable_key"]
                rec_st = str(first_rec.get("recordStableKey") or "")
                if rec_st and rec_st != st_key and actual_id != st_key:
                    return None

            existing = first_rec
            settlement_patch = {}
            if review_packet is not None:
                from warehouse_review_packet import validate_warehouse_review_packet, source_fingerprint_for
                valid, reasons = validate_warehouse_review_packet(review_packet)
                if (not valid or review_packet.get("recordStableKey") != str(record_id)
                        or review_packet.get("sourceFingerprint") != source_fingerprint_for(review_packet)):
                    raise HistoryStoreError("INVALID_REVIEW_PACKET")
                settlement_patch["warehouseReviewPacket"] = copy.deepcopy(dict(review_packet))
                descs = review_packet.get("segments") or review_packet.get("descriptors") or []
                if descs:
                    settlement_patch["pageCount"] = len(descs)
                    settlement_patch["warehousePageCount"] = len(descs)

            # 2. Extract prior human decisions in lock
            try:
                from warehouse_auto_confirmation import extract_human_decisions
                human_decisions = extract_human_decisions(existing)
            except Exception:
                human_decisions = {}

            from warehouse_identity_review import CatalogAuthority
            authority = catalog if isinstance(catalog, CatalogAuthority) else CatalogAuthority()

            # 3. Merge review units preserving unprovided units and locking in human decisions
            merged_units = None
            if review_units is not None:
                incoming_by_id = {
                    str(u.get("reviewUnitId") or "").strip(): copy.deepcopy(dict(u))
                    for u in review_units
                    if u.get("reviewUnitId")
                }
                existing_units = existing.get("settlement", {}).get("reviewUnits") or []
                existing_by_id = {
                    str(u.get("reviewUnitId") or "").strip(): copy.deepcopy(dict(u))
                    for u in existing_units
                    if u.get("reviewUnitId")
                }

                all_uids = list(incoming_by_id.keys()) + [uid for uid in existing_by_id if uid not in incoming_by_id]
                merged_units = []
                for uid in all_uids:
                    u_item = incoming_by_id.get(uid) or existing_by_id.get(uid)
                    if not u_item:
                        continue
                    if uid in human_decisions:
                        h_dec = human_decisions[uid]
                        if h_dec.get("catalogId"):
                            true_name = _verify_authoritative_item_name(
                                h_dec["catalogId"], h_dec.get("canonicalName"), authority, context="human decision"
                            )
                            u_item["confirmationStatus"] = "CONFIRMED"
                            u_item["identityStatus"] = "EXACT_IDENTIFIED"
                            u_item["selectedCatalogId"] = str(h_dec["catalogId"]).strip()
                            u_item["canonicalName"] = true_name
                            u_item["confirmedByHuman"] = True
                            u_item["confirmationReasons"] = ["HUMAN_REVIEWED_PRIOR_DECISION_PROTECTED"]
                        else:
                            u_item["confirmationStatus"] = "CANDIDATE_ONLY"
                            u_item["identityStatus"] = "REVIEW_REQUIRED"
                            u_item["selectedCatalogId"] = None
                            u_item["canonicalName"] = None
                            u_item["confirmedByHuman"] = True
                            u_item["unconfirmedReasons"] = ["HUMAN_DEFERRED_PRIOR_DECISION_PROTECTED"]
                    else:
                        if not u_item.get("confirmedByHuman"):
                            if u_item.get("confirmationStatus") == "CONFIRMED" or u_item.get("selectedCatalogId"):
                                c_id = u_item.get("selectedCatalogId")
                                c_name = u_item.get("canonicalName")
                                if c_name:
                                    true_name = _verify_authoritative_item_name(
                                        c_id, c_name, authority, context="reviewUnit"
                                    )
                                    u_item["canonicalName"] = true_name
                                else:
                                    cat_rec = authority.get(c_id)
                                    if cat_rec is None:
                                        raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: unknown catalogId '{c_id}' in reviewUnit")
                                    u_item["canonicalName"] = cat_rec.get("name")
                    merged_units.append(u_item)
                settlement_patch["reviewUnits"] = merged_units

            # 4. Synchronize warehouseOccupancy projection
            if occupancy is not None:
                settlement_patch["warehouseOccupancy"] = copy.deepcopy(dict(occupancy))
            elif merged_units is not None:
                try:
                    from warehouse_occupancy_adapter import adapt_review_packet_to_warehouse_occupancy
                    adapted = adapt_review_packet_to_warehouse_occupancy({"reviewUnits": merged_units})
                    if adapted:
                        settlement_patch["warehouseOccupancy"] = adapted
                except Exception:
                    pass

            # 5. Synchronize warehouseIdentityReview projection
            target_ir = None
            if identity_review is not None:
                if not isinstance(identity_review, Mapping):
                    raise HistoryStoreError("INVALID_IDENTITY_REVIEW: identity_review must be a mapping")
                target_ir = copy.deepcopy(dict(identity_review))

                target_key = str(target_ir.get("recordStableKey") or "").strip()
                if not target_key or target_key != actual_id:
                    raise HistoryStoreError(
                        f"INVALID_IDENTITY_REVIEW: recordStableKey '{target_key}' does not match record '{actual_id}'"
                    )

                from warehouse_identity_review_persist import (
                    _validate_artifact,
                    WarehouseIdentityReviewPersistError,
                )
                try:
                    _validate_artifact(target_ir)
                except WarehouseIdentityReviewPersistError as exc:
                    raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: {exc.code} {exc}") from exc
                except Exception as exc:
                    raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: {exc}") from exc

                # Authoritative catalog check on all resolved items and decisions in incoming artifact
                for item in target_ir.get("resolvedItems") or []:
                    if isinstance(item, Mapping):
                        cid = item.get("catalogId")
                        cname = item.get("name")
                        _verify_authoritative_item_name(cid, cname, authority, context="resolvedItem")
                for decision in target_ir.get("decisions") or []:
                    if isinstance(decision, Mapping):
                        cid = decision.get("selectedCatalogId") or decision.get("catalogId")
                        action = decision.get("action")
                        if action in ("CONFIRM_CANDIDATE", "CONFIRM_CATALOG_OVERRIDE") or cid:
                            cname = decision.get("canonicalName") or decision.get("name")
                            if cname:
                                _verify_authoritative_item_name(cid, cname, authority, context="decision")
                            else:
                                if authority.get(cid) is None:
                                    raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: unknown catalogId '{cid}' in decision")
            elif human_decisions and "warehouseIdentityReview" in (existing.get("settlement") or {}):
                target_ir = copy.deepcopy(existing["settlement"]["warehouseIdentityReview"])

            if isinstance(target_ir, dict) and target_ir.get("schemaVersion"):
                from warehouse_identity_review import SHA256_RE, artifact_fingerprint_for
                from warehouse_identity_review_persist import (
                    _validate_artifact,
                    WarehouseIdentityReviewPersistError,
                )

                is_v2 = target_ir.get("schemaVersion") == "warehouse-identity-review.v2"
                id_key = "reviewUnitId" if is_v2 else "trackId"
                unres_key = "unresolvedUnits" if is_v2 else "unresolvedTracks"

                if human_decisions:
                    # 1. Update decisions list
                    decisions_list = target_ir.get("decisions")
                    if isinstance(decisions_list, list):
                        new_dec_list = []
                        seen_uids = set()
                        for d in decisions_list:
                            if isinstance(d, dict):
                                d_uid = str(d.get(id_key) or d.get("reviewUnitId") or d.get("trackId") or "").strip()
                                if d_uid and d_uid in human_decisions:
                                    h_data = human_decisions[d_uid]
                                    cat_id = h_data.get("catalogId")
                                    action = h_data.get("action") or ("CONFIRM_CANDIDATE" if cat_id else "DEFER")
                                    up_d = copy.deepcopy(d)
                                    up_d["action"] = action
                                    cat_k = "selectedCatalogId" if "selectedCatalogId" in up_d else "catalogId"
                                    if cat_id:
                                        true_name = _verify_human_confirmed_item_name(
                                            cat_id, h_data.get("canonicalName"), authority
                                        )
                                        up_d[cat_k] = str(cat_id).strip()
                                        up_d["canonicalName"] = true_name
                                    else:
                                        up_d[cat_k] = None
                                        up_d["canonicalName"] = None
                                    up_d["confirmedByHuman"] = True
                                    up_d["reviewerType"] = "HUMAN"
                                    new_dec_list.append(up_d)
                                    seen_uids.add(d_uid)
                                elif d_uid:
                                    new_dec_list.append(d)
                                    seen_uids.add(d_uid)
                                else:
                                    new_dec_list.append(d)

                        for h_uid, h_data in human_decisions.items():
                            if h_uid not in seen_uids:
                                cat_id = h_data.get("catalogId")
                                action = h_data.get("action") or ("CONFIRM_CANDIDATE" if cat_id else "DEFER")
                                new_dec = {
                                    "decisionId": f"dec-human-{h_uid}",
                                    id_key: h_uid,
                                    "action": action,
                                    "selectedCatalogId": str(cat_id).strip() if cat_id else None,
                                    "confirmedByHuman": True,
                                    "reviewerType": "HUMAN",
                                }
                                if cat_id:
                                    new_dec["canonicalName"] = _verify_human_confirmed_item_name(
                                        cat_id, h_data.get("canonicalName"), authority
                                    )
                                new_dec_list.append(new_dec)
                                seen_uids.add(h_uid)
                        target_ir["decisions"] = new_dec_list

                    # 2. Update resolvedItems & unresolvedTracks/unresolvedUnits if present
                    if "resolvedItems" in target_ir:
                        resolved = [r for r in target_ir.get("resolvedItems") or [] if isinstance(r, dict)]
                        unresolved = [u for u in target_ir.get(unres_key) or [] if isinstance(u, dict)]
                        res_by_id = {str(r.get(id_key) or r.get("trackId") or r.get("reviewUnitId")): r for r in resolved}
                        unres_by_id = {str(u.get(id_key) or u.get("trackId") or u.get("reviewUnitId")): u for u in unresolved}

                        for h_uid, h_data in human_decisions.items():
                            if h_data.get("catalogId"):
                                cat_id = str(h_data["catalogId"]).strip()
                                true_name = _verify_human_confirmed_item_name(
                                    cat_id, h_data.get("canonicalName"), authority
                                )
                                # Confirmed by human: must be in resolved with genuine evidence
                                if h_uid in res_by_id:
                                    r_item = res_by_id[h_uid]
                                    r_item["catalogId"] = cat_id
                                    r_item["name"] = true_name
                                    r_item["confirmedByHuman"] = True
                                    r_item["action"] = "CONFIRM_CANDIDATE"
                                    if h_uid in unres_by_id:
                                        unres_by_id.pop(h_uid, None)
                                else:
                                    # Look up genuine evidence in merged_units / existing_units / unres_by_id
                                    unit_item = None
                                    if merged_units:
                                        unit_item = next((u for u in merged_units if str(u.get(id_key) or u.get("reviewUnitId") or u.get("trackId") or "") == h_uid), None)
                                    if not unit_item and existing.get("settlement", {}).get("reviewUnits"):
                                        unit_item = next((u for u in existing["settlement"]["reviewUnits"] if str(u.get(id_key) or u.get("reviewUnitId") or u.get("trackId") or "") == h_uid), None)

                                    ev_obs = None
                                    if unit_item and isinstance(unit_item.get("observations"), list) and unit_item["observations"]:
                                        ev_obs = unit_item["observations"][0]
                                    elif unit_item and isinstance(unit_item.get("bestObservation"), dict):
                                        ev_obs = unit_item["bestObservation"]
                                    elif h_uid in unres_by_id and isinstance(unres_by_id[h_uid].get("observations"), list) and unres_by_id[h_uid]["observations"]:
                                        ev_obs = unres_by_id[h_uid]["observations"][0]

                                    ev_id = str((ev_obs.get("evidenceId") if ev_obs else None) or (unit_item.get("evidenceId") if unit_item else None) or "").strip()
                                    ev_sha = str((ev_obs.get("sha256") if ev_obs else None) or (unit_item.get("sha256") if unit_item else None) or (unit_item.get("cropSha256") if unit_item else None) or "").strip()
                                    ev_bbox = (ev_obs.get("bbox") if ev_obs else None) or (unit_item.get("bbox") if unit_item else None)

                                    # Strict evidence check: never fabricate fake evidence references!
                                    if not ev_id or not SHA256_RE.fullmatch(ev_sha) or not isinstance(ev_bbox, list) or len(ev_bbox) != 4:
                                        # Genuine evidence missing: retain as unresolved
                                        if h_uid not in unres_by_id:
                                            unres_by_id[h_uid] = {
                                                id_key: h_uid,
                                                "action": "DEFER",
                                                "identityStatus": "UNRESOLVED",
                                                "reason": "EVIDENCE_REFERENCE_MISSING",
                                            }
                                        continue

                                    if h_uid in unres_by_id:
                                        unres_by_id.pop(h_uid, None)

                                    new_res_entry = {
                                        id_key: h_uid,
                                        "catalogId": cat_id,
                                        "name": true_name,
                                        "confirmedByHuman": True,
                                        "recordStableKey": actual_id,
                                        "packetFingerprint": target_ir["packetFingerprint"],
                                        "evidenceId": ev_id,
                                        "sha256": ev_sha,
                                        "bbox": [float(b) for b in ev_bbox],
                                        "action": "CONFIRM_CANDIDATE",
                                    }
                                    if is_v2:
                                        new_res_entry["physicalGroupId"] = unit_item.get("physicalGroupId") if unit_item else None
                                        new_res_entry["supportingTrackIds"] = list(unit_item.get("supportingTrackIds") or []) if unit_item else []
                                        new_res_entry["worldAnchor"] = dict(unit_item.get("worldAnchor") or {"row": 0, "col": 0}) if unit_item else {"row": 0, "col": 0}
                                        new_res_entry["footprint"] = dict(unit_item.get("footprint") or {"widthCells": 1, "heightCells": 1}) if unit_item else {"widthCells": 1, "heightCells": 1}
                                        new_res_entry["sequenceIndex"] = int(ev_obs.get("sequenceIndex") or 0) if ev_obs else 0
                                        new_res_entry["provenanceType"] = "HUMAN_REVIEWED_CATALOG_ID"

                                    res_by_id[h_uid] = new_res_entry
                            else:
                                # Deferred by human: must be in unresolved, NOT in resolved
                                if h_uid in res_by_id:
                                    res_by_id.pop(h_uid, None)
                                if h_uid in unres_by_id:
                                    u_item = unres_by_id[h_uid]
                                    u_item["action"] = "DEFER"
                                    u_item["identityStatus"] = "UNRESOLVED"
                                else:
                                    unres_by_id[h_uid] = {
                                        id_key: h_uid,
                                        "action": "DEFER",
                                        "identityStatus": "UNRESOLVED",
                                    }

                        target_ir["resolvedItems"] = list(res_by_id.values())
                        target_ir[unres_key] = list(unres_by_id.values())

                        if isinstance(target_ir.get("summary"), dict):
                            target_ir["summary"]["resolvedItemCount"] = len(res_by_id)
                            u_count_key = "unresolvedUnitCount" if is_v2 else "unresolvedTrackCount"
                            target_ir["summary"][u_count_key] = len(unres_by_id)
                            target_ir["summary"]["decisionCount"] = len(target_ir.get("decisions") or [])

                    if "artifactFingerprint" in target_ir:
                        target_ir["artifactFingerprint"] = artifact_fingerprint_for(target_ir)

                    # Strict validation parity on merged artifact
                    try:
                        _validate_artifact(target_ir)
                    except WarehouseIdentityReviewPersistError as exc:
                        raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: merged artifact validation failed: {exc.code} {exc}") from exc
                    except Exception as exc:
                        raise HistoryStoreError(f"INVALID_IDENTITY_REVIEW: merged artifact validation failed: {exc}") from exc

                settlement_patch["warehouseIdentityReview"] = target_ir

            if not settlement_patch:
                return existing

            # Check idempotency: if settlement patch doesn't change anything, return existing
            current_st = existing.get("settlement") or {}
            is_same = True
            for k, v in settlement_patch.items():
                if _canonical_json_str(current_st.get(k)) != _canonical_json_str(v):
                    is_same = False
                    break
            if is_same:
                return existing

            lifecycle = str(existing.get("lifecycleStatus") or "").upper()
            if lifecycle == "FINALIZED":
                return self.update_record_transactional(
                    actual_id,
                    {"settlement": settlement_patch},
                )
            if lifecycle == "DRAFT":
                updated = copy.deepcopy(existing)
                settlement = updated.get("settlement")
                if not isinstance(settlement, dict):
                    settlement = {}
                    updated["settlement"] = settlement
                settlement.update(settlement_patch)
                return self.persist_record_transactional(updated, is_finalized=False)
            return None

    def persist_record_transactional(
        self,
        record: Mapping[str, Any],
        is_finalized: bool = True,
        *,
        preserve_archive_sidecars: bool = False,
    ) -> Dict[str, Any]:
        """Atomically persist a DRAFT or FINALIZED record with transition validation and idempotency."""
        rec_id = str(record.get("id") or "").strip()
        if not rec_id:
            raise HistoryStoreError("Cannot persist record without a valid non-empty 'id'.")

        rec_dict = copy.deepcopy(dict(record))
        lifecycle = str(rec_dict.get("lifecycleStatus") or "").strip().upper()

        if is_finalized or lifecycle == "FINALIZED":
            is_valid, reasons = validate_finalized_match_record_v7(rec_dict, match_id=rec_id)
            if not is_valid:
                # If schemaVersion != 7 (e.g. legacy test record), allow base validation if needed
                if rec_dict.get("schemaVersion") != 7:
                    pass
                else:
                    raise HistoryStoreError(f"Cannot persist invalid FINALIZED record {rec_id}: {reasons}")
        else:
            is_valid, reasons = validate_canonical_match_record_v7(rec_dict, match_id=rec_id)
            if not is_valid and rec_dict.get("schemaVersion") == 7:
                raise HistoryStoreError(f"Cannot persist invalid DRAFT record {rec_id}: {reasons}")

        with _HISTORY_STORE_LOCK, history_file_lock(self.db_path):
            db_data = self.read_database()
            rows: List[Dict[str, Any]] = db_data.setdefault("records", [])

            matching_indices = []
            for i, r in enumerate(rows):
                if not isinstance(r, dict):
                    continue
                if _can_merge_records(r, rec_dict):
                    matching_indices.append(i)

            existing_idx = None
            existing_record = None
            if matching_indices:
                existing_idx = matching_indices[0]
                existing_record = rows[existing_idx]
                for extra_idx in sorted(matching_indices[1:], reverse=True):
                    del rows[extra_idx]

            if existing_record is not None:
                existing_lifecycle = str(existing_record.get("lifecycleStatus") or "").strip().upper()
                if existing_lifecycle == "FINALIZED":
                    # Check identical content (idempotency)
                    if _canonical_json_str(existing_record) == _canonical_json_str(rec_dict):
                        return existing_record  # Idempotent no-op

                    # If incoming is a DRAFT, an already finalized record cannot be overwritten with a DRAFT.
                    if not is_finalized or lifecycle != "FINALIZED":
                        raise FinalizedRecordConflictError(
                            f"Cannot overwrite already FINALIZED record '{rec_id}' with differing content."
                        )

                    # Both are FINALIZED. Check whether core immutable settlement facts conflict:
                    ex_st = existing_record.get("settlement") or {}
                    in_st = rec_dict.get("settlement") or {}
                    core_conflict = False
                    for f in ("clearingPrice", "actualTotal", "realizedProfit", "winner", "acquired"):
                        if ex_st.get(f) is not None and in_st.get(f) is not None:
                            if _canonical_json_str(ex_st.get(f)) != _canonical_json_str(in_st.get(f)):
                                core_conflict = True
                                break
                    if core_conflict:
                        raise FinalizedRecordConflictError(
                            f"Cannot overwrite already FINALIZED record '{rec_id}' with differing content."
                        )

                    # Core facts match: merge allowed sidecars and evidence without tampering
                    if not rec_dict.get("predictionSnapshot") and existing_record.get("predictionSnapshot"):
                        rec_dict["predictionSnapshot"] = copy.deepcopy(existing_record["predictionSnapshot"])
                    if not rec_dict.get("intelCardEvidence") and existing_record.get("intelCardEvidence"):
                        rec_dict["intelCardEvidence"] = copy.deepcopy(existing_record["intelCardEvidence"])
                    if not rec_dict.get("auctionEvidence") and existing_record.get("auctionEvidence"):
                        rec_dict["auctionEvidence"] = copy.deepcopy(existing_record["auctionEvidence"])

                    rec_settlement = rec_dict.setdefault("settlement", {})
                    for field in (
                        "warehouseOccupancy",
                        "warehouseIdentityReview",
                        "reviewUnits",
                        "warehouseReviewUnits",
                        "evidenceAttachments",
                        "truthEvidence",
                        "settlementWinnerName",
                        "settlementAuctionAssistantName",
                        "auctionAssistant",
                        "isSelfWinner",
                    ):
                        if field in ex_st and field not in rec_settlement:
                            rec_settlement[field] = copy.deepcopy(ex_st[field])
                    from quality_sell_selection import merge_quality_sell_sidecar_bundle
                    merge_quality_sell_sidecar_bundle(ex_st, rec_settlement)

                    rows[existing_idx] = rec_dict
                else:
                    if preserve_archive_sidecars and not rec_dict.get("predictionSnapshot"):
                        prior_snapshot = existing_record.get("predictionSnapshot")
                        if isinstance(prior_snapshot, dict):
                            from evaluation_eligibility import validate_prediction_snapshot_for_storage
                            valid, _ = validate_prediction_snapshot_for_storage(prior_snapshot, match_id=rec_id)
                            if valid:
                                rec_dict["predictionSnapshot"] = copy.deepcopy(prior_snapshot)
                    if preserve_archive_sidecars:
                        if 'intelCardEvidence' not in rec_dict and isinstance(existing_record.get('intelCardEvidence'), dict):
                            rec_dict['intelCardEvidence'] = copy.deepcopy(existing_record['intelCardEvidence'])
                        prior_auction_evidence = existing_record.get('auctionEvidence')
                        if isinstance(prior_auction_evidence, dict):
                            if not isinstance(rec_dict.get('auctionEvidence'), dict):
                                rec_dict['auctionEvidence'] = copy.deepcopy(prior_auction_evidence)
                            else:
                                prior_native = prior_auction_evidence.get('nativeObservation')
                                next_native = rec_dict['auctionEvidence'].get('nativeObservation')
                                if isinstance(prior_native, dict) and isinstance(next_native, dict):
                                    if 'sourceFrames' not in next_native and 'sourceFrames' in prior_native:
                                        next_native['sourceFrames'] = copy.deepcopy(prior_native['sourceFrames'])
                        prior_settlement = existing_record.get("settlement") or {}
                        # These fields belong to capture/review writers, never OCR archive.
                        for field in (
                            "warehouseReviewPacket",
                            "pageCount",
                            "warehousePageCount",
                            "warehouseOccupancy",
                            "warehouseIdentityReview",
                            "reviewUnits",
                            "warehouseReviewUnits",
                            "reviewedItems",
                            "reviewedAt",
                            "reviewProvenance",
                            "inventoryArchive",
                            "settlementItems",
                            "visibleInventory",
                        ):
                            if field in prior_settlement and (field in ("warehouseReviewPacket", "pageCount", "warehousePageCount",
                                                                       "inventoryArchive", "settlementItems", "visibleInventory")
                                                              or field not in rec_dict.setdefault("settlement", {})):
                                rec_dict.setdefault("settlement", {})[field] = copy.deepcopy(prior_settlement[field])
                        from quality_sell_selection import merge_quality_sell_sidecar_bundle
                        merge_quality_sell_sidecar_bundle(prior_settlement, rec_dict.setdefault("settlement", {}))
                        for f in ("reviewUnits", "warehouseReviewUnits"):
                            if f in existing_record and f not in rec_dict:
                                rec_dict[f] = copy.deepcopy(existing_record[f])
                        if prior_settlement.get("identityReviews"):
                            for field in ("winner", "acquired", "identityReviews"):
                                rec_dict.setdefault("settlement", {})[field] = copy.deepcopy(prior_settlement.get(field))

                        # Preserve fieldStates and manual protected/missing facts from prior draft per Rule 7.1
                        if 'fieldStates' not in rec_dict and isinstance(existing_record.get('fieldStates'), dict):
                            rec_dict['fieldStates'] = copy.deepcopy(existing_record['fieldStates'])
                        prior_field_states = existing_record.get('fieldStates') or {}

                        env = rec_dict.setdefault('environment', {})
                        ex_env = existing_record.get('environment') or {}
                        for efld in ('venue', 'venueName', 'box', 'boxType', 'fieldCondition', 'fieldConditionName'):
                            fs = prior_field_states.get(efld) or {}
                            is_protected = isinstance(fs, dict) and fs.get('protected')
                            val = existing_record.get(efld) or ex_env.get(efld)
                            if is_protected or (env.get(efld) in (None, '', '未知箱型') and val):
                                if val:
                                    env[efld] = copy.deepcopy(val)

                        pub = rec_dict.setdefault('publicIntel', {})
                        ex_pub = existing_record.get('publicIntel') or {}
                        for pfld in ('q', 'totalItems', 'totalGrid'):
                            fs = prior_field_states.get(pfld) or {}
                            is_protected = isinstance(fs, dict) and fs.get('protected')
                            val = existing_record.get(pfld) if existing_record.get(pfld) is not None else ex_pub.get(pfld)
                            if is_protected or (pub.get(pfld) in (None, '') and val not in (None, '')):
                                pub[pfld] = copy.deepcopy(val)

                        quals = rec_dict.setdefault('qualities', {})
                        ex_quals = existing_record.get('qualities') or {}
                        for qcolor in ('white', 'green', 'blue', 'purple', 'gold', 'red'):
                            qblock = quals.setdefault(qcolor, {})
                            ex_qblock = ex_quals.get(qcolor) or {}
                            for subfld in ('count', 'avg', 'grid', 'minCount', 'maxCount', 'total'):
                                fld_key = f'{qcolor}{subfld.capitalize()}'
                                fs = prior_field_states.get(fld_key) or {}
                                is_protected = isinstance(fs, dict) and fs.get('protected')
                                val = existing_record.get(fld_key) if existing_record.get(fld_key) is not None else ex_qblock.get(subfld)
                                if is_protected or (qblock.get(subfld) in (None, '') and val not in (None, '')):
                                    qblock[subfld] = copy.deepcopy(val)

                        if not is_finalized:
                            for fld in (
                                "q", "goldAvg", "venue", "venueName", "box", "boxType",
                                "blueCount", "redCount", "goldCount", "purpleCount", "greenCount", "whiteCount",
                                "blueAvg", "redAvg", "purpleAvg", "greenAvg", "whiteAvg",
                                "blueGrid", "redGrid", "goldGrid", "purpleGrid", "greenGrid", "whiteGrid",
                                "totalGrid", "totalItems", "fieldCondition", "fieldConditionName"
                            ):
                                if (rec_dict.get(fld) in (None, "") and existing_record.get(fld) not in (None, "")):
                                    rec_dict[fld] = copy.deepcopy(existing_record[fld])

                        validator = validate_finalized_match_record_v7 if is_finalized else validate_canonical_match_record_v7
                        valid, reasons = validator(rec_dict, match_id=rec_id)
                        if not valid and rec_dict.get("schemaVersion") == 7:
                            raise HistoryStoreError(f"Cannot preserve invalid archive sidecars for {rec_id}: {reasons}")
                    rows[existing_idx] = rec_dict
            else:
                rows.append(rec_dict)

            # Atomic write to disk
            parent_dir = self.db_path.parent
            parent_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.db_path.with_suffix(f".tmp_{os.getpid()}_{threading.get_ident()}")

            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(db_data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                os.replace(str(tmp_path), str(self.db_path))
            except Exception as e:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                raise HistoryStoreError(f"Failed to write database atomically to {self.db_path}: {e}") from e

            # Re-read verification
            re_read = self.read_database()
            for r in re_read.get("records") or []:
                if isinstance(r, dict):
                    r_keys = _extract_match_keys(r)
                    if rec_id in r_keys or str(r.get("id") or "").strip() == rec_id:
                        return r

            raise HistoryStoreError(f"Persisted record '{rec_id}' not found after re-reading database.")

    def update_record_transactional(
        self,
        record_id: str,
        patch: Mapping[str, Any],
        *,
        identity_review: Optional[Mapping[str, Any]] = None,
        expected_warehouse_review_fingerprint: Optional[str] = None,
        expected_inventory_archive: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Apply a targeted field patch to an existing record atomically.

        Unlike persist_record_transactional (which treats an existing FINALIZED
        record as a conflict), this mutates the record in place: it preserves
        the record identity and all untouched fields, deep-merges nested dicts,
        writes atomically, and re-reads to verify.  Used for immutable
        append-only review metadata (e.g. settlement.reviewedItems +
        settlement.reviewProvenance) without discarding machine evidence.
        """
        target_id = str(record_id or "").strip()
        if not target_id:
            raise HistoryStoreError("RECORD_ID_EMPTY")
        if not isinstance(patch, Mapping):
            raise HistoryStoreError("RECORD_PATCH_INVALID")

        with _HISTORY_STORE_LOCK, history_file_lock(self.db_path):
            db_data = self.read_database()
            rows: List[Dict[str, Any]] = db_data.setdefault("records", [])
            match_idx = None
            for i, r in enumerate(rows):
                if isinstance(r, dict):
                    r_keys = _extract_match_keys(r)
                    if (str(r.get("id") or "").strip() == target_id
                            or (expected_inventory_archive is None and target_id in r_keys)):
                        match_idx = i
                        break
            if match_idx is None:
                raise HistoryStoreError("RECORD_NOT_FOUND")

            updated = dict(rows[match_idx])
            if expected_inventory_archive is not None:
                if (str(updated.get("lifecycleStatus") or "").upper() != "DRAFT"
                        or str(updated.get("dataOrigin") or "").lower() != "live-trial"):
                    raise HistoryStoreError("INVENTORY_ARCHIVE_NOT_TRIAL_DRAFT")
                archive = (updated.get("settlement") or {}).get("inventoryArchive") or {}
                if any(archive.get(key) != value for key, value in expected_inventory_archive.items()):
                    raise HistoryStoreError("INVENTORY_ARCHIVE_CHANGED")
            if expected_warehouse_review_fingerprint is not None:
                current_review = (updated.get("settlement") or {}).get("warehouseIdentityReview") or {}
                if str(current_review.get("artifactFingerprint") or "") != expected_warehouse_review_fingerprint:
                    raise HistoryStoreError("WAREHOUSE_REVIEW_CHANGED")
            if identity_review is not None:
                if updated.get("lifecycleStatus") != "DRAFT":
                    raise HistoryStoreError("仅可核对草稿身份，已完成记录不可改写")
                winner = identity_review.get("winner")
                acquired = identity_review.get("acquired")
                if not isinstance(winner, str) or not winner.strip() or len(winner.strip()) > 64:
                    raise HistoryStoreError("请填写有效竞得者名称")
                if acquired is not None and type(acquired) is not bool:
                    raise HistoryStoreError("竞得归属必须为本人、他人或未知")
                st = copy.deepcopy(updated.get("settlement") or {})
                audit = list(st.get("identityReviews") or [])
                audit.append({"before": {"winner": st.get("winner"), "acquired": st.get("acquired")},
                              "after": {"winner": winner.strip(), "acquired": acquired},
                              "reviewedBy": "user", "reviewedAt": identity_review.get("reviewedAt")})
                st.update(winner=winner.strip(), acquired=acquired, identityReviews=audit)
                updated["settlement"] = st
            for key, value in patch.items():
                if isinstance(value, Mapping) and isinstance(updated.get(key), dict):
                    merged = dict(updated[key])
                    merged.update(dict(value))
                    updated[key] = merged
                else:
                    updated[key] = value
            rows[match_idx] = updated

            parent_dir = self.db_path.parent
            parent_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.db_path.with_suffix(f".tmp_{os.getpid()}_{threading.get_ident()}")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(db_data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                os.replace(str(tmp_path), str(self.db_path))
            except Exception as e:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                raise HistoryStoreError(f"Failed to update database atomically to {self.db_path}: {e}") from e

            re_read = self.read_database()
            for r in re_read.get("records") or []:
                if isinstance(r, dict):
                    r_keys = _extract_match_keys(r)
                    if str(r.get("id") or "").strip() == target_id or target_id in r_keys:
                        return r
            raise HistoryStoreError(f"Updated record '{target_id}' not found after re-reading database.")

    def append_finalized_evidence(
        self,
        record_id: str,
        *,
        evidence_entry: Optional[Mapping[str, Any]] = None,
        links: Optional[Mapping[str, Any]] = None,
        review_update: Optional[Mapping[str, Any]] = None,
        audit_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Safely enrich a record (especially FINALIZED) with late evidence or review sidecars.

        Strictly enforces allowlist:
        - Allowed: settlement.evidenceAttachments, settlement.warehouseOccupancy,
                   settlement.warehouseIdentityReview, settlement.warehouseReviewUnits,
                   settlement.reviewedItems, settlement.reviewProvenance,
                   settlement.reviewedAt, evidenceAuditTrail.
        - Forbidden to mutate: clearingPrice, actualTotal, realizedProfit,
                               winner, acquired, isAcquired, venue, venueId,
                               box, boxId, costs, q, goldAvg, purpleCount,
                               fieldCondition, bids, bidRounds, leaderBid,
                               predictionSnapshot, formalValue, decision.
        Appends an audit trail entry with before/after revision.
        """
        target_id = str(record_id or "").strip()
        if not target_id:
            raise HistoryStoreError("RECORD_ID_EMPTY")

        FORBIDDEN_FIELDS = frozenset({
            "clearingPrice", "actualTotal", "realizedProfit",
            "winner", "acquired", "isAcquired",
            "settlementWinnerName", "isSelfWinner",
            "venue", "venueId", "box", "boxId",
            "costs", "q", "goldAvg", "purpleCount", "fieldCondition",
            "bids", "bidRounds", "leaderBid",
            "predictionSnapshot", "formalValue", "decision",
        })

        ALLOWED_REVIEW_FIELDS = frozenset({
            "warehouseOccupancy",
            "warehouseIdentityReview",
            "warehouseReviewUnits",
            "reviewUnits",
            "warehouseReviewPacket",
            "pageCount",
            "warehousePageCount",
            "reviewedItems",
            "reviewProvenance",
            "reviewedAt",
            "evidenceAttachments",
            "evidenceAuditTrail",
        })

        if review_update is not None:
            if not isinstance(review_update, Mapping):
                raise HistoryStoreError("INVALID_REVIEW_UPDATE: must be a mapping")
            for k in review_update:
                if k in FORBIDDEN_FIELDS:
                    raise HistoryStoreError(f"FORBIDDEN_MUTATION: cannot modify core field '{k}' on finalized record")
                if k not in ALLOWED_REVIEW_FIELDS:
                    raise HistoryStoreError(f"UNAUTHORIZED_FIELD: field '{k}' not in allowlist for finalized enrichment")

        with _HISTORY_STORE_LOCK, history_file_lock(self.db_path):
            db_data = self.read_database()
            rows: List[Dict[str, Any]] = db_data.setdefault("records", [])
            match_idx = None
            for i, r in enumerate(rows):
                if isinstance(r, dict):
                    r_keys = _extract_match_keys(r)
                    if str(r.get("id") or "").strip() == target_id or target_id in r_keys:
                        match_idx = i
                        break
            if match_idx is None:
                raise HistoryStoreError(f"RECORD_NOT_FOUND: '{target_id}'")

            existing = rows[match_idx]
            updated = copy.deepcopy(existing)
            settlement = updated.setdefault("settlement", {})
            current_attachments = settlement.setdefault("evidenceAttachments", {})
            captures = current_attachments.setdefault("captures", [])

            # Merge links
            if links:
                for meta_k in ("matchId", "sourceInstanceId", "appVersion", "catalogVersion"):
                    if meta_k in links and not current_attachments.get(meta_k):
                        current_attachments[meta_k] = links[meta_k]
                new_captures = list(links.get("captures") or [])
                for cap in new_captures:
                    if isinstance(cap, Mapping):
                        cap_sha = cap.get("sha256")
                        if cap_sha and not any(c.get("sha256") == cap_sha for c in captures):
                            captures.append(copy.deepcopy(dict(cap)))

            # Append evidence_entry
            if evidence_entry:
                entry_dict = copy.deepcopy(dict(evidence_entry))
                entry_sha = entry_dict.get("sha256")
                if entry_sha and not any(c.get("sha256") == entry_sha for c in captures):
                    captures.append(entry_dict)

            if captures:
                settlement["pageCount"] = len(captures)
                settlement["warehousePageCount"] = len(captures)

            # Merge review_update
            if review_update:
                for k, v in review_update.items():
                    if k in ALLOWED_REVIEW_FIELDS and k != "evidenceAuditTrail":
                        settlement[k] = copy.deepcopy(v)

            # Audit trail
            audit_trail = updated.setdefault("evidenceAuditTrail", [])
            prior_rev = len(audit_trail)
            new_rev = prior_rev + 1
            added_sha = (
                evidence_entry.get("sha256") if isinstance(evidence_entry, Mapping)
                else (links.get("captures")[-1].get("sha256") if links and links.get("captures") else None)
            )
            audit_entry = {
                "revision": new_rev,
                "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
                "auditReason": str(audit_reason or "POST_FINALIZATION_EVIDENCE_ENRICHMENT"),
                "captureCount": len(captures),
                "addedEvidenceSha": added_sha,
            }
            audit_trail.append(audit_entry)

            rows[match_idx] = updated

            # Atomic write to disk
            parent_dir = self.db_path.parent
            parent_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.db_path.with_suffix(f".tmp_{os.getpid()}_{threading.get_ident()}")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(db_data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                os.replace(str(tmp_path), str(self.db_path))
            except Exception as e:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                raise HistoryStoreError(f"Failed to enrich finalized record atomically in {self.db_path}: {e}") from e

            re_read = self.read_database()
            for r in re_read.get("records") or []:
                if isinstance(r, dict):
                    r_keys = _extract_match_keys(r)
                    if str(r.get("id") or "").strip() == target_id or target_id in r_keys:
                        return r
            raise HistoryStoreError(f"Enriched record '{target_id}' not found after re-reading database.")

    def delete_record_transactional(
        self,
        record_id: str,
        active_match_id: Optional[str] = None,
        *,
        write_rolling_backup: bool = True,
    ) -> Dict[str, Any]:
        """Atomically delete a record by ID with pre-delete backup, active match guard, and re-read verification."""
        target_id = str(record_id or "").strip()
        if not target_id:
            raise HistoryStoreError("RECORD_ID_EMPTY")

        if active_match_id and target_id == str(active_match_id).strip():
            raise HistoryStoreError("ACTIVE_MATCH_CANNOT_BE_DELETED")

        with _HISTORY_STORE_LOCK, history_file_lock(self.db_path):
            db_data = self.read_database()
            rows: List[Dict[str, Any]] = db_data.setdefault("records", [])

            match_idx = None
            matched_record = None
            for i, r in enumerate(rows):
                if isinstance(r, dict):
                    r_keys = _extract_match_keys(r)
                    if str(r.get("id") or "").strip() == target_id or target_id in r_keys:
                        match_idx = i
                        matched_record = r
                        break

            if match_idx is None or matched_record is None:
                raise HistoryStoreError("RECORD_NOT_FOUND")

            # Check if matched record is active match
            rec_keys = _extract_match_keys(matched_record)
            if active_match_id and (str(active_match_id).strip() in rec_keys or str(matched_record.get("id") or "").strip() == str(active_match_id).strip()):
                raise HistoryStoreError("ACTIVE_MATCH_CANNOT_BE_DELETED")

            parent_dir = self.db_path.parent
            parent_dir.mkdir(parents=True, exist_ok=True)

            if write_rolling_backup:
                # Existing callers retain the established delete safety copy.
                backup_path = parent_dir / "history_delete_backup_v1.json"
                tmp_backup = parent_dir / f"history_delete_backup_v1.tmp_{os.getpid()}_{threading.get_ident()}"
                try:
                    with open(tmp_backup, "w", encoding="utf-8") as f:
                        json.dump(db_data, f, ensure_ascii=False, indent=2)
                        f.flush()
                        try:
                            os.fsync(f.fileno())
                        except Exception:
                            pass
                    os.replace(str(tmp_backup), str(backup_path))
                except Exception:
                    if tmp_backup.exists():
                        try:
                            tmp_backup.unlink()
                        except Exception:
                            pass
                    # The transaction itself remains authoritative.

            # Delete the record
            del rows[match_idx]

            # Atomic write updated database to disk
            tmp_path = self.db_path.with_suffix(f".tmp_{os.getpid()}_{threading.get_ident()}")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(db_data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                os.replace(str(tmp_path), str(self.db_path))
            except Exception as e:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                raise HistoryStoreError(f"Failed to delete record atomically: {e}") from e

            # Re-read verification
            re_read = self.read_database()
            for r in re_read.get("records") or []:
                if isinstance(r, dict):
                    r_keys = _extract_match_keys(r)
                    if str(r.get("id") or "").strip() == target_id or target_id in r_keys:
                        raise HistoryStoreError(f"Record '{target_id}' still present after deletion.")

            return {
                "ok": True,
                "deletedRecordId": target_id,
                "deletedRecord": matched_record,
                "remainingCount": len(re_read.get("records") or []),
            }
