"""In-memory A-style warehouse identity review session.

Native-owned view model and evidence crops. Does not persist History or
trust client paths, hashes, bboxes, names, or qualities.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np

from warehouse_identity_review import (
    ACTION_CONFIRM,
    ACTION_DEFER,
    ACTION_EXCLUDE,
    ACTION_EXCLUDE_V2,
    ACTION_FLAG,
    ACTION_OUT_OF_CATALOG,
    ACTION_OVERRIDE,
    OVERRIDE_REASONS,
    CatalogAuthority,
    resolve_warehouse_identity_review,
)

from warehouse_review_packet import source_fingerprint_for, validate_warehouse_review_packet

MAX_CROP_EDGE = 360
THUMB_CROP_EDGE = 96
OPS = frozenset({
    "open",
    "view",
    "select_track",
    "next_track",
    "prev_track",
    "select_observation",
    "select_candidate",
    "select_override",
    "apply",
    "undo",
    "search",
    "finalize",
    "filter_unresolved",
})
VIEW_KEYS = frozenset({
    "available",
    "sessionId",
    "packetFingerprint",
    "recordAlias",
    "recordStableKey",
    "coverageStatus",
    "coverageCaption",
    "reviewCompletion",
    "identityResolution",
    "trackIndex",
    "trackCount",
    "currentTrackId",
    "geometryStatus",
    "clipped",
    "pixelOnly",
    "hasLegalEvidence",
    "bestObservation",
    "otherObservations",
    "candidates",
    "draftAction",
    "processedCount",
    "unresolvedCount",
    "availableActions",
    "filterUnresolved",
    "artifactReady",
    "persistenceCaption",
    "overrideHits",
    "message",
})
REASON_ACTIONS = frozenset({ACTION_OVERRIDE, ACTION_OUT_OF_CATALOG, ACTION_EXCLUDE, ACTION_FLAG})
FORBIDDEN_CLIENT_FIELDS = frozenset({
    "sha256",
    "relativePath",
    "bbox",
    "Name",
    "Quality",
    "name",
    "quality",
    "evidenceId",
    "imageBytes",
    "hash",
    "packet",
    "File",
    "LiveFiles",
    "Value",
    "price",
    "imageDataUrl",
})
OPS_ACTIONS = [
    ACTION_CONFIRM,
    ACTION_OVERRIDE,
    ACTION_OUT_OF_CATALOG,
    ACTION_DEFER,
    ACTION_EXCLUDE,
    ACTION_FLAG,
]


class WarehouseIdentityReviewSessionError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class WarehouseIdentityReviewSession:
    def __init__(
        self,
        *,
        store: Any = None,
        catalog: Optional[CatalogAuthority] = None,
        packet_provider: Optional[Any] = None,
    ):
        self._store = store
        self._catalog = catalog or CatalogAuthority()
        self._packet_provider = packet_provider
        self._session_id: Optional[str] = None
        self._packet: Optional[Dict[str, Any]] = None
        self._fingerprint: Optional[str] = None
        self._track_ids: List[str] = []
        self._index = 0
        self._selected_observation: Optional[str] = None
        self._drafts: Dict[str, Dict[str, Any]] = {}
        self._filter_unresolved = False
        self._artifact: Optional[Dict[str, Any]] = None
        self._base_artifact_fingerprint: Optional[str] = None
        self._search_hits: List[Dict[str, Any]] = []
        self._crop_memo: Dict[Tuple[str, int], Dict[str, Any]] = {}

    def dispatch(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        extra = set(payload) & FORBIDDEN_CLIENT_FIELDS
        if extra:
            raise WarehouseIdentityReviewSessionError("FORBIDDEN_CLIENT_FIELD")
        op = str(payload.get("op") or payload.get("reviewOp") or "").strip()
        if op not in OPS:
            raise WarehouseIdentityReviewSessionError("UNKNOWN_OP")
        if op == "open":
            return self.open()
        self._bind_request(payload)
        if op == "view":
            return self.view()
        if op == "select_track":
            return self.select_track(str(payload.get("trackId") or ""))
        if op == "next_track":
            return self.step_track(1)
        if op == "prev_track":
            return self.step_track(-1)
        if op == "select_observation":
            return self.select_observation(str(payload.get("observationId") or ""))
        if op == "select_candidate":
            return self.select_candidate(str(payload.get("selectedCatalogId") or payload.get("candidateId") or ""))
        if op == "select_override":
            return self.select_override(str(payload.get("selectedCatalogId") or payload.get("candidateId") or ""))
        if op == "apply":
            return self.apply(payload)
        if op == "undo":
            return self.undo()
        if op == "search":
            return self.search(str(payload.get("query") or ""))
        if op == "finalize":
            return self.finalize(str(payload.get("reviewedAt") or ""))
        if op == "filter_unresolved":
            self._filter_unresolved = bool(payload.get("filterUnresolved"))
            return self.view()
        raise WarehouseIdentityReviewSessionError("UNKNOWN_OP")

    def open(self, packet: Optional[Mapping[str, Any]] = None, *, saved_artifact=None) -> Dict[str, Any]:
        source = packet
        if source is None and self._packet_provider is not None:
            source = self._packet_provider() if callable(self._packet_provider) else self._packet_provider
        if not isinstance(source, Mapping):
            self.close()
            return self.view()
        ok, _reasons = validate_warehouse_review_packet(source)
        if not ok:
            self.close()
            return self.view()
        fingerprint = source_fingerprint_for(source)
        if source.get("sourceFingerprint") != fingerprint:
            self.close()
            return self.view()
        key = str(source.get("recordStableKey") or "")
        previous_key = str((self._packet or {}).get("recordStableKey") or "")
        previous_fp = self._fingerprint
        if previous_key and previous_key != key:
            self.close()
        elif previous_fp and previous_fp != fingerprint:
            self._reset_drafts()
            self._artifact = None
        self._packet = copy.deepcopy(dict(source))
        self._fingerprint = fingerprint
        self._session_id = self._session_id or uuid.uuid4().hex
        if self._packet.get("schemaVersion") == "warehouse-review-packet.v2":
            self._track_ids = [str(item.get("reviewUnitId")) for item in self._packet.get("reviewUnits") or []]
        else:
            self._track_ids = [str(item.get("trackId")) for item in self._packet.get("tracks") or []]
        if self._index >= len(self._track_ids):
            self._index = 0
        self._selected_observation = None
        self._search_hits = []
        self._crop_memo = {}
        if saved_artifact is not None and not self._drafts:
            self.restore_saved_artifact(saved_artifact)
        return self.view()

    def restore_saved_artifact(self, artifact):
        """Restore Native-loaded decisions bound to this exact immutable packet."""
        from warehouse_identity_review_persist import validate_review_artifact
        validate_review_artifact(artifact)
        if (not self._packet or artifact.get("recordStableKey") != self._packet.get("recordStableKey")
                or artifact.get("packetFingerprint") != self._fingerprint):
            raise WarehouseIdentityReviewSessionError("PACKET_FINGERPRINT_MISMATCH")
        drafts = {}
        if artifact.get("reviewerType") == "HUMAN":
            for decision in artifact.get("decisions") or []:
                if decision.get("reviewerType") == "AUTO":
                    continue
                uid = decision.get("reviewUnitId") or decision.get("trackId")
                if uid not in self._track_ids:
                    raise WarehouseIdentityReviewSessionError("UNKNOWN_TRACK")
                draft = {k: copy.deepcopy(decision[k]) for k in
                         ("decisionId", "action", "selectedCatalogId", "overrideReason", "reason")
                         if decision.get(k) is not None}
                if draft.get("action") == ACTION_OVERRIDE:
                    draft["overrideCatalogId"] = draft.get("selectedCatalogId")
                drafts[uid] = draft
        self._drafts = drafts
        self._artifact = copy.deepcopy(dict(artifact))
        self._base_artifact_fingerprint = artifact["artifactFingerprint"]

    def mark_persisted(self, fingerprint):
        if self._artifact and self._artifact.get("artifactFingerprint") == fingerprint:
            self._base_artifact_fingerprint = fingerprint

    def close(self) -> None:
        self._session_id = None
        self._packet = None
        self._fingerprint = None
        self._track_ids = []
        self._index = 0
        self._selected_observation = None
        self._reset_drafts()
        self._artifact = None
        self._search_hits = []
        self._crop_memo = {}

    def _reset_drafts(self) -> None:
        self._drafts = {}
        self._base_artifact_fingerprint = None
        self._filter_unresolved = False

    def _bind_request(self, payload: Mapping[str, Any]) -> None:
        if self._packet is None or not self._session_id:
            raise WarehouseIdentityReviewSessionError("NO_SESSION")
        session_id = str(payload.get("sessionId") or "").strip()
        fingerprint = str(payload.get("packetFingerprint") or "").strip()
        if session_id and session_id != self._session_id:
            self.close()
            raise WarehouseIdentityReviewSessionError("SESSION_MISMATCH")
        if fingerprint and fingerprint != self._fingerprint:
            self._reset_drafts()
            self._artifact = None
            raise WarehouseIdentityReviewSessionError("PACKET_FINGERPRINT_MISMATCH")

    def view(self) -> Dict[str, Any]:
        if self._packet is None or not self._track_ids:
            return _empty_view()
        track = self._current_track()
        if track is None:
            return _empty_view()
        observations = list(track.get("observations") or [])
        best_id = str(track.get("bestObservationId") or "")
        native_best = _find_obs(observations, best_id) or (observations[0] if observations else None)
        selected_id = self._selected_observation or best_id
        featured = _find_obs(observations, selected_id) or native_best
        others = [
            item for item in observations
            if str(item.get("observationId")) != str((featured or {}).get("observationId"))
        ]
        unit_id = str(track.get("reviewUnitId") or track.get("trackId") or "")
        draft = self._drafts.get(unit_id) or {}
        best_crop = self._observation_view(native_best, featured=True)
        legal = bool(best_crop.get("imageAvailable"))
        actions = list(OPS_ACTIONS)
        if not legal:
            actions = [ACTION_DEFER, ACTION_FLAG]
        processed = sum(1 for track_id in self._track_ids if self._is_processed(track_id))
        live_completion = (
            "COMPLETE" if self._track_ids and all(self._is_processed(tid) for tid in self._track_ids)
            else ("PARTIAL" if any((self._drafts.get(tid) or {}).get("action") for tid in self._track_ids) else "NOT_STARTED")
        )
        artifact = self._artifact or {}
        featured_view = self._observation_view(featured, featured=True)
        payload = {
            "available": True,
            "sessionId": self._session_id,
            "packetFingerprint": self._fingerprint,
            "recordAlias": "本局仓库",
            "recordStableKey": self._packet.get("recordStableKey"),
            "coverageStatus": str((self._packet.get("warehouseCoverage") or {}).get("status") or ""),
            "coverageCaption": _coverage_caption(self._packet),
            "reviewCompletion": artifact.get("reviewCompletion") or live_completion,
            "identityResolution": artifact.get("identityResolution"),
            "trackIndex": self._index + 1,
            "trackCount": len(self._track_ids),
            "currentTrackId": track.get("reviewUnitId") or track.get("trackId"),
            "geometryStatus": track.get("geometryEvidenceStatus"),
            "clipped": bool(track.get("clipped") or track.get("visibility") == "CLIPPED"),
            "pixelOnly": bool(track.get("pixelOnly")),
            "hasLegalEvidence": legal,
            "bestObservation": featured_view,
            "otherObservations": [self._observation_view(item, featured=False) for item in others],
            "candidates": self._candidate_views(track, draft),
            "draftAction": draft.get("action"),
            "processedCount": processed,
            "unresolvedCount": len(self._track_ids) - processed,
            "availableActions": actions,
            "filterUnresolved": self._filter_unresolved,
            "artifactReady": self._artifact is not None,
            "persistenceCaption": "尚未写入历史记录",
            "overrideHits": self._override_hit_views(draft),
            "message": _status_message(legal, self._artifact, draft.get("action")),
        }
        extra = set(payload) - VIEW_KEYS
        for key in extra:
            payload.pop(key, None)
        return payload

    def select_track(self, track_id: str) -> Dict[str, Any]:
        if track_id not in self._track_ids:
            raise WarehouseIdentityReviewSessionError("UNKNOWN_TRACK")
        self._index = self._track_ids.index(track_id)
        self._selected_observation = None
        self._search_hits = []
        return self.view()

    def step_track(self, delta: int) -> Dict[str, Any]:
        visible = self._visible_ids() or list(self._track_ids)
        if not visible:
            return self.view()
        current = self._track_ids[self._index] if self._track_ids else ""
        if current not in visible:
            return self.select_track(visible[0])
        position = visible.index(current)
        return self.select_track(visible[(position + int(delta)) % len(visible)])

    def select_observation(self, observation_id: str) -> Dict[str, Any]:
        track = self._current_track()
        if track is None or not _find_obs(track.get("observations") or [], observation_id):
            raise WarehouseIdentityReviewSessionError("UNKNOWN_OBSERVATION")
        self._selected_observation = observation_id
        return self.view()

    def select_candidate(self, catalog_id: str) -> Dict[str, Any]:
        track = self._current_track()
        if track is None:
            raise WarehouseIdentityReviewSessionError("NO_SESSION")
        ids = {str(item.get("catalogId")) for item in (track.get("candidates") or [])}
        if catalog_id not in ids:
            raise WarehouseIdentityReviewSessionError("UNKNOWN_CANDIDATE")
        unit_id = str(track.get("reviewUnitId") or track.get("trackId") or "")
        draft = self._drafts.setdefault(unit_id, {})
        draft["selectedCatalogId"] = catalog_id
        draft.pop("overrideCatalogId", None)
        return self.view()

    def select_override(self, catalog_id: str) -> Dict[str, Any]:
        track = self._current_track()
        if track is None:
            raise WarehouseIdentityReviewSessionError("NO_SESSION")
        record = self._catalog.get(catalog_id)
        if record is None:
            raise WarehouseIdentityReviewSessionError("UNKNOWN_CATALOG_ID")
        candidate_ids = {str(item.get("catalogId")) for item in (track.get("candidates") or [])}
        unit_id = str(track.get("reviewUnitId") or track.get("trackId") or "")
        draft = self._drafts.setdefault(unit_id, {})
        draft["overrideCatalogId"] = catalog_id
        draft["overrideQuarantined"] = record.get("catalogGeometryStatus") == "QUARANTINED"
        if catalog_id in candidate_ids:
            draft["overrideInCandidates"] = True
        else:
            draft.pop("overrideInCandidates", None)
        if not any(item.get("catalogId") == catalog_id for item in self._search_hits):
            self._search_hits = [{
                "catalogId": catalog_id,
                "candidateName": record.get("name") or "",
                "quarantined": record.get("catalogGeometryStatus") == "QUARANTINED",
            }] + self._search_hits
        return self.view()

    def apply(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        track = self._current_track()
        if track is None:
            raise WarehouseIdentityReviewSessionError("NO_SESSION")
        unit_id = str(track.get("reviewUnitId") or track.get("trackId") or "")
        existing = self._drafts.get(unit_id) or {}
        if existing.get("action"):
            raise WarehouseIdentityReviewSessionError("ALREADY_PROCESSED")
        action = str(payload.get("reviewAction") or payload.get("action") or "")
        if action not in {
            ACTION_CONFIRM, ACTION_OVERRIDE, ACTION_OUT_OF_CATALOG, ACTION_DEFER, ACTION_EXCLUDE, ACTION_EXCLUDE_V2, ACTION_FLAG,
        }:
            raise WarehouseIdentityReviewSessionError("UNKNOWN_ACTION")
        legal = bool(self.view().get("hasLegalEvidence"))
        if not legal and action not in {ACTION_DEFER, ACTION_FLAG}:
            raise WarehouseIdentityReviewSessionError("EVIDENCE_UNAVAILABLE")
        candidate_ids = {str(item.get("catalogId")) for item in (track.get("candidates") or [])}
        draft: Dict[str, Any] = {
            "selectedCatalogId": existing.get("selectedCatalogId"),
            "overrideCatalogId": existing.get("overrideCatalogId"),
            "action": action,
            "decisionId": uuid.uuid4().hex,
        }
        if action == ACTION_CONFIRM:
            selected = str(existing.get("selectedCatalogId") or "")
            client = str(payload.get("selectedCatalogId") or "")
            if client and selected and client != selected:
                raise WarehouseIdentityReviewSessionError("CANDIDATE_MISMATCH")
            selected = selected or client
            if not selected:
                raise WarehouseIdentityReviewSessionError("CANDIDATE_NOT_SELECTED")
            if selected not in candidate_ids:
                raise WarehouseIdentityReviewSessionError("UNKNOWN_CANDIDATE")
            if payload.get("confirmCandidate") is not True:
                raise WarehouseIdentityReviewSessionError("CONFIRM_REQUIRED")
            draft["selectedCatalogId"] = selected
        elif action == ACTION_OVERRIDE:
            selected = str(existing.get("overrideCatalogId") or payload.get("selectedCatalogId") or "")
            if not selected:
                raise WarehouseIdentityReviewSessionError("OVERRIDE_NOT_SELECTED")
            if selected in candidate_ids and (self._catalog.get(selected) or {}).get("catalogGeometryStatus") != "QUARANTINED":
                raise WarehouseIdentityReviewSessionError("OVERRIDE_ID_IN_CANDIDATES")
            record = self._catalog.get(selected)
            if record is None:
                raise WarehouseIdentityReviewSessionError("UNKNOWN_CATALOG_ID")
            reason = str(payload.get("overrideReason") or "")
            if reason not in OVERRIDE_REASONS:
                raise WarehouseIdentityReviewSessionError("REASON_REQUIRED")
            if payload.get("confirmedByHuman") is not True:
                raise WarehouseIdentityReviewSessionError("CONFIRM_REQUIRED")
            draft["selectedCatalogId"] = selected
            draft["overrideCatalogId"] = selected
            draft["overrideReason"] = reason
            draft["confirmedByHuman"] = True
        elif action in {ACTION_OUT_OF_CATALOG, ACTION_EXCLUDE, ACTION_EXCLUDE_V2, ACTION_FLAG}:
            reason = str(payload.get("reason") or payload.get("geometryErrorType") or "").strip()
            if not reason:
                raise WarehouseIdentityReviewSessionError("REASON_REQUIRED")
            draft["reason"] = reason
        elif action == ACTION_DEFER:
            note = str(payload.get("reason") or "").strip()
            if note:
                draft["reason"] = note
        self._drafts[unit_id] = draft
        self._artifact = None
        return self.view()

    def undo(self) -> Dict[str, Any]:
        track = self._current_track()
        if track is not None:
            unit_id = str(track.get("reviewUnitId") or track.get("trackId") or "")
            current = self._drafts.get(unit_id) or {}
            self._drafts[unit_id] = {
                key: current[key]
                for key in ("selectedCatalogId", "overrideCatalogId")
                if current.get(key)
            }
            self._artifact = None
        return self.view()

    def search(self, query: str) -> Dict[str, Any]:
        needle = str(query or "").strip().casefold()
        hits: List[Dict[str, Any]] = []
        if needle:
            for catalog_id, record in sorted(self._catalog._by_id.items()):
                name = str(record.get("name") or "")
                if needle in catalog_id.casefold() or needle in name.casefold():
                    hits.append({
                        "catalogId": catalog_id,
                        "candidateName": name,
                        "quarantined": record.get("catalogGeometryStatus") == "QUARANTINED",
                    })
                if len(hits) >= 12:
                    break
        self._search_hits = hits
        return self.view()

    def finalize(self, reviewed_at: str = "") -> Dict[str, Any]:
        if self._packet is None:
            raise WarehouseIdentityReviewSessionError("NO_SESSION")
        stamp = str(reviewed_at or "").strip()
        if not stamp:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        decisions = []
        is_v2 = self._packet.get("schemaVersion") == "warehouse-review-packet.v2"
        id_key = "reviewUnitId" if is_v2 else "trackId"
        for track_id in self._track_ids:
            draft = self._drafts.get(track_id) or {}
            action = draft.get("action")
            if not action:
                continue
            item: Dict[str, Any] = {
                "decisionId": draft.get("decisionId") or uuid.uuid4().hex,
                id_key: track_id,
                "action": action,
            }
            if action in {ACTION_CONFIRM, ACTION_OVERRIDE}:
                item["selectedCatalogId"] = draft.get("selectedCatalogId")
            if action == ACTION_OVERRIDE:
                item["overrideReason"] = draft.get("overrideReason")
                item["confirmedByHuman"] = True
            if draft.get("reason"):
                item["reason"] = draft.get("reason")
            decisions.append(item)
        document = {
            "schemaVersion": "warehouse-identity-review-decision.v2" if is_v2 else "warehouse-identity-review-decision.v1",
            "recordStableKey": self._packet.get("recordStableKey"),
            "packetFingerprint": self._fingerprint,
            "reviewedAt": stamp,
            "reviewerType": "HUMAN",
            "decisions": decisions,
        }
        artifact = resolve_warehouse_identity_review(self._packet, document, catalog=self._catalog)
        self._artifact = artifact
        return self.view()

    def artifact_copy(self) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._artifact) if self._artifact else None

    def persist_binding(self) -> Optional[Dict[str, str]]:
        if self._artifact is None or not self._session_id or not self._fingerprint:
            return None
        return {
            "sessionId": str(self._session_id),
            "packetFingerprint": str(self._fingerprint),
            "recordStableKey": str(self._artifact.get("recordStableKey") or ""),
            "artifactFingerprint": str(self._artifact.get("artifactFingerprint") or ""),
            "baseArtifactFingerprint": self._base_artifact_fingerprint,
        }

    def _current_track(self) -> Optional[Dict[str, Any]]:
        if self._packet is None or not self._track_ids:
            return None
        visible = self._visible_ids()
        current = self._track_ids[self._index]
        if visible and current not in visible:
            self._index = self._track_ids.index(visible[0])
            current = visible[0]
        if self._packet.get("schemaVersion") == "warehouse-review-packet.v2":
            for item in self._packet.get("reviewUnits") or []:
                if str(item.get("reviewUnitId")) == current:
                    return item
        else:
            for item in self._packet.get("tracks") or []:
                if str(item.get("trackId")) == current:
                    return item
        return None

    def _visible_ids(self) -> List[str]:
        if not self._filter_unresolved:
            return list(self._track_ids)
        return [track_id for track_id in self._track_ids if not self._is_processed(track_id)]

    def _is_processed(self, track_id: str) -> bool:
        action = (self._drafts.get(track_id) or {}).get("action")
        return bool(action) and action != ACTION_DEFER

    def _candidate_views(self, track: Mapping[str, Any], draft: Mapping[str, Any]) -> List[Dict[str, Any]]:
        selected = draft.get("selectedCatalogId")
        views = []
        for item in track.get("candidates") or []:
            geometry = item.get("geometry") or {}
            views.append({
                "candidateId": item.get("catalogId"),
                "candidateName": item.get("name") or "",
                "requiresOverride": (self._catalog.get(str(item.get("catalogId") or "")) or {}).get("catalogGeometryStatus") == "QUARANTINED",
                "identityStatus": "CANDIDATE_ONLY",
                "geometryText": f"{geometry.get('width')}x{geometry.get('height')}/{geometry.get('cells')}",
                "selected": item.get("catalogId") == selected,
            })
        return views

    def _override_hit_views(self, draft: Mapping[str, Any]) -> List[Dict[str, Any]]:
        selected = draft.get("overrideCatalogId")
        hits = []
        for item in self._search_hits:
            hits.append({
                "catalogId": item.get("catalogId"),
                "candidateName": item.get("candidateName") or "",
                "quarantined": bool(item.get("quarantined")),
                "selected": item.get("catalogId") == selected,
            })
        return hits

    def _observation_view(self, observation: Optional[Mapping[str, Any]], *, featured: bool) -> Dict[str, Any]:
        if observation is None:
            return {
                "observationId": None,
                "status": None,
                "imageAvailable": False,
                "imageDataUrl": None,
                "featured": featured,
            }
        crop = self._crop(observation, max_edge=MAX_CROP_EDGE if featured else THUMB_CROP_EDGE)
        return {
            "observationId": observation.get("observationId"),
            "status": observation.get("status"),
            "imageAvailable": crop.get("imageAvailable"),
            "imageDataUrl": crop.get("imageDataUrl") if crop.get("imageAvailable") else None,
            "featured": featured,
        }

    def _crop(self, observation: Mapping[str, Any], *, max_edge: int) -> Dict[str, Any]:
        observation_id = str(observation.get("observationId") or "")
        memo_key = (observation_id, int(max_edge))
        cached = self._crop_memo.get(memo_key)
        if cached is not None:
            return cached
        if self._store is None or self._packet is None:
            result = {"imageAvailable": False, "imageDataUrl": None}
            self._crop_memo[memo_key] = result
            return result
        try:
            data_url = crop_verified_observation(
                store=self._store,
                packet=self._packet,
                observation_id=observation_id,
                max_edge=max_edge,
            )
        except Exception:
            result = {"imageAvailable": False, "imageDataUrl": None}
            self._crop_memo[memo_key] = result
            return result
        result = {"imageAvailable": bool(data_url), "imageDataUrl": data_url}
        self._crop_memo[memo_key] = result
        return result


def crop_verified_observation(
    *,
    store: Any,
    packet: Mapping[str, Any],
    observation_id: str,
    max_edge: int = MAX_CROP_EDGE,
) -> Optional[str]:
    track_obs = None
    units = (
        packet.get("reviewUnits")
        if packet.get("schemaVersion") == "warehouse-review-packet.v2"
        else packet.get("tracks")
    )
    for track in units or []:
        for item in track.get("observations") or []:
            if str(item.get("observationId")) == observation_id:
                track_obs = item
                break
        if track_obs is not None:
            break
    if track_obs is None:
        raise WarehouseIdentityReviewSessionError("UNKNOWN_OBSERVATION")
    evidence_id = str(track_obs.get("evidenceId") or "")
    bbox = track_obs.get("bbox")
    if not evidence_id or not isinstance(bbox, list) or len(bbox) != 4:
        raise WarehouseIdentityReviewSessionError("EVIDENCE_UNAVAILABLE")
    key = str(packet.get("recordStableKey") or "")
    descriptor = None
    for item in store.list_record_evidence(key):
        if item.get("evidenceId") == evidence_id:
            descriptor = item
            break
    if descriptor is None:
        raise WarehouseIdentityReviewSessionError("ORPHAN_EVIDENCE")
    if descriptor.get("recordStableKey") != key or descriptor.get("kind") != "warehouse-segment":
        raise WarehouseIdentityReviewSessionError("RECORD_KEY_MISMATCH")
    payload = store.load_original(descriptor)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != descriptor.get("sha256"):
        raise WarehouseIdentityReviewSessionError("HASH_MISMATCH")
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise WarehouseIdentityReviewSessionError("INVALID_IMAGE")
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(round(float(bbox[0])))))
    y1 = max(0, min(height - 1, int(round(float(bbox[1])))))
    x2 = max(x1 + 1, min(width, int(round(float(bbox[2])))))
    y2 = max(y1 + 1, min(height, int(round(float(bbox[3])))))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        raise WarehouseIdentityReviewSessionError("INVALID_BBOX")
    edge = max(crop.shape[0], crop.shape[1])
    limit = max(16, int(max_edge))
    if edge > limit:
        scale = limit / float(edge)
        crop = cv2.resize(
            crop,
            (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))),
        )
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        raise WarehouseIdentityReviewSessionError("ENCODE_FAILED")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def _find_obs(items: Sequence[Mapping[str, Any]], observation_id: str) -> Optional[Mapping[str, Any]]:
    for item in items:
        if str(item.get("observationId")) == observation_id:
            return item
    return None


def _coverage_caption(packet: Mapping[str, Any]) -> str:
    status = str((packet.get("warehouseCoverage") or {}).get("status") or "")
    if status == "COMPLETE":
        return "不等于身份已全部识别"
    if status == "PARTIAL":
        return "只审阅已看到的藏品，不代表整仓完整"
    return "覆盖尚未证明"


def _status_message(legal: bool, artifact: Optional[Mapping[str, Any]], draft_action: Optional[str]) -> Optional[str]:
    if artifact is not None:
        return "已生成审阅结果，尚未写入历史记录"
    if not legal:
        return "当前证据不可用，只能暂缓或标记几何错误"
    if draft_action:
        return f"本件草稿：{draft_action}（未确认写入）"
    return None


def _empty_view() -> Dict[str, Any]:
    payload = {key: None for key in VIEW_KEYS}
    payload.update({
        "available": False,
        "trackCount": 0,
        "processedCount": 0,
        "unresolvedCount": 0,
        "filterUnresolved": False,
        "artifactReady": False,
        "persistenceCaption": "尚未写入历史记录",
        "candidates": [],
        "otherObservations": [],
        "overrideHits": [],
        "availableActions": [],
    })
    return payload
