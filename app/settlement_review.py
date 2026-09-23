# -*- coding: utf-8 -*-
"""Native-owned Settlement Review service (v1).

Machine proposal is NEVER automatically promoted to verified Ground Truth.
Only an explicit user save promotes reviewedItems to the History record, and
it always preserves the original machine evidence + screenshot provenance.

Review projections (DTOs) handed to Main are whitelisted and immutable:
- bounded settlement summary
- screenshot reference (+ base64 data URL for display)
- machine proposals (proposal-level whitelist)
- previously reviewed items
No raw canonical record, no Solver state, no mutable CurrentMatch is exposed.
"""

from __future__ import annotations

import base64
import copy
import datetime
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from settlement_grid import settlement_grid_bounds

from canonical_history_store import CanonicalHistoryStore
from evidence_storage import get_canonical_data_dir, save_evidence_png, verify_evidence_file
from legacy_archive import LegacyArchive
from review_overlay import ReviewOverlayStore
from runtime_data import resolve_runtime_history_path
from native_trial_drafts import NativeTrialDraftStore, resolve_native_trial_history_path
from settlement_catalog_candidates import get_global_catalog_candidate_resolver
from settlement_evidence_store_v2 import (
    COVERAGE_PARTIAL,
    COVERAGE_UNPROVEN,
    KIND_MAIN,
    KIND_MANUAL_GAME,
    SettlementEvidenceStoreV2,
)
from settlement_human_review import (
    ACTION_CONFIRM_CANDIDATE,
    ACTION_CONFIRM_OVERRIDE,
    SettlementHumanReviewError,
    apply_settlement_human_review_action,
    load_settlement_reviewed_truth,
)
from settlement_item_recognizer import SettlementItemRecognizer
from settlement_review_file_originals import (
    ReviewFileOriginalError,
    build_truth_evidence_v2,
    lookup_runtime_file_originals,
    sanitize_evidence_references,
    verify_runtime_original,
)


def _aware_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_file_as_data_url(path: Path) -> Optional[str]:
    try:
        raw = path.read_bytes()
        mime = "image/png" if path.suffix.lower() in (".png",) else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
    except Exception:
        return None


def _whitelist_proposal(it: Dict[str, Any]) -> Dict[str, Any]:
    """Proposal-level whitelist: no raw component internals beyond what the
    review UI needs (cells/bbox are grid coordinates, not raw pixels)."""
    return {
        "slotIndex": it.get("slotIndex"),
        "rarity": it.get("rarity"),
        "shape": it.get("shape"),
        "cells": [list(c) for c in (it.get("cells") or [])],
        "bbox": it.get("bbox"),
        "status": it.get("identificationStatus") or it.get("status"),
        "groupingAmbiguous": bool(it.get("groupingAmbiguous")),
        "partitionCandidates": list(it.get("partitionCandidates") or []),
        "candidateItemIds": list(it.get("candidateItemIds") or []),
        "candidatePrices": list(it.get("candidatePrices") or []),
        "score": it.get("confidence"),
        "name": it.get("name") if it.get("identificationStatus") == "exact" else None,
        "exactItemId": it.get("exactItemId") if it.get("identificationStatus") == "exact" else None,
        "price": it.get("price") if it.get("identificationStatus") == "exact" else None,
    }


class SettlementReviewService:
    """Loads review sessions, imports screenshots, persists reviewed truth."""

    def __init__(
        self,
        history_path_provider: Optional[Any] = None,
        data_root_provider: Optional[Any] = None,
        legacy_archive: Optional[LegacyArchive] = None,
        overlay_store: Optional[ReviewOverlayStore] = None,
        native_trial_store: Optional[NativeTrialDraftStore] = None,
    ):
        self._history_path_provider = history_path_provider or (lambda: str(resolve_runtime_history_path()))
        self._data_root_provider = data_root_provider or (lambda: str(get_canonical_data_dir()))
        self._legacy_archive = legacy_archive or LegacyArchive()
        self._overlay_store = overlay_store or ReviewOverlayStore()
        self._native_trial_store = native_trial_store or NativeTrialDraftStore(
            resolve_native_trial_history_path()
        )

    # ------------------------------------------------------------------ store
    def _store(self, source: str = "current") -> CanonicalHistoryStore:
        path = self._native_trial_store.history_path if source == "live-trial" else self._history_path_provider()
        return CanonicalHistoryStore(path)

    def _data_root(self, source: str = "current") -> Path:
        if source == "live-trial":
            return self._native_trial_store.root
        return Path(self._data_root_provider()).resolve()

    def _evidence_dir(self, source: str = "current") -> Path:
        d = self._data_root(source) / "evidence" / "settlement"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---------------------------------------------------------------- helpers
    def _load_record(self, record_id: str, source: str = "current") -> Optional[Dict[str, Any]]:
        if source == "live-trial":
            return self._native_trial_store.lookup(record_id)
        return self._store(source).lookup(record_id)

    def get_record(self, record_id: str, source: str = "current") -> Optional[Dict[str, Any]]:
        return self._load_record(record_id, source)

    def lookup_runtime_file_originals(self, record_id: str, source: str = "current") -> List[Dict[str, Any]]:
        return lookup_runtime_file_originals(record_id, self._data_root(source))

    def _evidence_image(self, uri: Optional[str], source: str = "current") -> Optional[Path]:
        if not uri:
            return None
        p = self._data_root(source) / uri.replace("/", os.sep)
        return p if p.is_file() else None

    def _run_recognizer(self, image_path: Path) -> List[Dict[str, Any]]:
        img = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        rec = SettlementItemRecognizer()
        res = rec.parse_settlement_ledger(img)
        return [_whitelist_proposal(it) for it in (res.get("settlementItems") or [])]

    def _build_dto(
        self,
        record_id: str,
        record: Dict[str, Any],
        screenshot_uri: Optional[str],
        screenshot_sha: Optional[str],
        image_path: Optional[Path],
        proposals: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        st = record.get("settlement") or {}
        reviewed = st.get("reviewedItems") or []
        review_units = copy.deepcopy(st.get("reviewUnits") or record.get("reviewUnits") or [])
        return {
            "recordId": record_id,
            "identityEditable": record.get("lifecycleStatus") == "DRAFT",
            "settlement": {
                "clearingPrice": st.get("clearingPrice"),
                "actualTotal": st.get("actualTotal"),
                "realizedProfit": st.get("realizedProfit"),
                "acquired": st.get("acquired"),
                "winner": st.get("winner"),
                "reviewed": bool(reviewed),
                "reviewedAt": st.get("reviewedAt"),
                "reviewUnits": review_units,
            },
            "screenshot": {
                "available": image_path is not None,
                "uri": screenshot_uri,
                "sha256": screenshot_sha,
                "dataUrl": _read_file_as_data_url(image_path) if image_path is not None else None,
            },
            "proposals": proposals,
            "reviewedItems": reviewed,
            "reviewUnits": review_units,
        }

    # ------------------------------------------------------------- main flows
    def legacy_archive_list(self) -> List[Dict[str, Any]]:
        """Legacy projections enriched with review-overlay status (bounded)."""
        projections = self._legacy_archive.list_projections()
        file_sha = self._legacy_archive.source_info().get("fileSha256")
        for p in projections:
            ov = self._overlay_store.get_overlay(file_sha, p["key"]) if file_sha else None
            p["reviewed"] = bool(ov and ov.get("reviewedItems"))
            p["reviewedAt"] = ((ov or {}).get("reviewProvenance") or {}).get("reviewedAt")
            if ov and ov.get("screenshot") and ov["screenshot"].get("uri"):
                p["screenshotAvailable"] = True
        return projections

    def delete_imported_screenshot(self, record_id: str, source: str = "current") -> Dict[str, Any]:
        """Delete user-imported screenshot reference and return a fresh clean review session."""
        record = self._load_legacy_record(record_id) if source == "legacy" else self._load_record(record_id, source)
        if record is None:
            return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "记录不存在"}
        sanitized_key = record_id.replace(":", "_")
        try:
            v2_store = self._v2_store(source)
            v2_store.unlink_user_imports(sanitized_key)
        except Exception as exc:
            return {"ok": False, "status": "DELETE_FAILED", "message": str(exc)}

        if source == "legacy":
            src_info = self._legacy_archive.source_info()
            file_sha = src_info.get("fileSha256")
            if file_sha:
                self._overlay_store.remove_screenshot(file_sha, record_id)
            return self.create_review_session(record_id, source="legacy")

        return self.create_review_session(record_id, source=source)

    def _load_legacy_record(self, key: str) -> Optional[Dict[str, Any]]:
        return self._legacy_archive.get_record(key)

    def _v2_store(self, source: str = "current") -> SettlementEvidenceStoreV2:
        return SettlementEvidenceStoreV2(self._data_root(source))

    def _load_v2_evidence_for_record(self, record_id: str, source: str = "current") -> Tuple[Optional[Path], Optional[str], Optional[np.ndarray]]:
        try:
            sanitized_key = record_id.replace(":", "_")
            v2_store = self._v2_store(source)
            descriptors = v2_store.list_record_evidence(sanitized_key)
            # The archived bill can reference a later, clearer stable viewport.
            # Do not silently replace it with the first animation frame in the
            # evidence index. A warehouse segment still cannot become main.
            record = self._load_record(record_id, source) or {}
            truth = (record.get('settlement') or {}).get('truthEvidence') or {}
            preferred = [d.get('sha256') for d in (truth.get('fileOriginals') or [])
                         if d.get('kind') == KIND_MAIN]
            mains = [d for d in descriptors if d.get('kind') == KIND_MAIN]
            main_desc = next((d for sha in preferred for d in mains if d.get('sha256') == sha),
                             next(iter(mains), None))
            if not main_desc:
                manuals = [d for d in descriptors if d.get('kind') == KIND_MANUAL_GAME]
                preferred_manual = [d.get('sha256') for d in (truth.get('fileOriginals') or [])
                                    if d.get('kind') == KIND_MANUAL_GAME]
                main_desc = next((d for sha in preferred_manual for d in manuals if d.get('sha256') == sha),
                                 next(iter(manuals), next(iter(descriptors), None)))
            if main_desc:
                blob_path = v2_store.root / main_desc.get("relativePath", "")
                if blob_path.is_file():
                    img = cv2.imdecode(np.fromfile(str(blob_path), dtype=np.uint8), cv2.IMREAD_COLOR)
                    return blob_path, main_desc.get("sha256"), img
        except Exception:
            pass
        return None, None, None

    def list_original_screenshots(self, record_id: str, source: str = "current") -> Dict[str, Any]:
        """Show verified originals without running expensive item recognition."""
        if source == "live-trial":
            record = self._native_trial_store.lookup(record_id)
            if record is None:
                return {"ok": False, "recordId": record_id, "source": source, "message": "隔离草稿不存在"}
            images = []
            for index, image in enumerate(self._native_trial_store.source_images(record_id), start=1):
                raw = image.get("data")
                mime = image.get("mimeType") or "application/octet-stream"
                images.append({
                    "evidenceId": image.get("evidenceId"),
                    "sequence": index,
                    "sha256": image.get("sha256"),
                    "width": image.get("width"),
                    "height": image.get("height"),
                    "capturedAt": image.get("capturedAt"),
                    "kind": image.get("kind"),
                    "readOnly": True,
                    "error": image.get("error"),
                    "dataUrl": "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii") if raw else None,
                })
        else:
            images = []
        store = self._v2_store(source)
        for index, desc in enumerate(store.list_record_evidence(record_id.replace(":", "_")), start=len(images) + 1):
            try:
                raw = store.load_original(desc)
                images.append({
                    "evidenceId": desc.get("evidenceId"),
                    "sequence": index,
                    "sha256": desc.get("sha256"),
                    "width": desc.get("width"),
                    "height": desc.get("height"),
                    "capturedAt": desc.get("capturedAt"),
                    "kind": desc.get("kind"),
                    "dataUrl": "data:" + desc.get("mimeType", "image/png") + ";base64," + base64.b64encode(raw).decode("ascii"),
                })
            except Exception:
                images.append({
                    "evidenceId": desc.get("evidenceId"),
                    "sequence": index,
                    "sha256": desc.get("sha256"),
                    "error": "原图缺失或校验失败",
                })
        return {"ok": True, "recordId": record_id, "source": source, "images": images}

    def remove_original_screenshot(self, record_id: str, evidence_id: str, *, restore: bool = False, source: str = "current") -> Dict[str, Any]:
        if source == "live-trial":
            return {"ok": False, "recordId": record_id, "source": source, "message": "观察原图属于隔离草稿的只读证据，不能删除"}
        try:
            self._v2_store(source).set_original_removed(record_id.replace(":", "_"), evidence_id, not restore)
            result = self.list_original_screenshots(record_id, source)
            result["message"] = "截图已恢复" if restore else "截图已从列表删除，原始证据保留"
            if not restore:
                result["undoEvidenceId"] = evidence_id
            return result
        except Exception as exc:
            return {"ok": False, "recordId": record_id, "message": str(exc)}

    def create_review_session(self, record_id: str, source: str = "current") -> Dict[str, Any]:
        """Load a record (+ screenshot evidence) and build a whitelisted review
        session from the current recognizer proposal.  source='current' reads
        CanonicalHistoryStore; source='legacy' reads the Legacy Archive lane and
        merges any existing review overlay (never touching the source file)."""
        v2_store = self._v2_store(source)
        v2_path, v2_sha, v2_img = self._load_v2_evidence_for_record(record_id, source)

        if source == "legacy":
            record = self._load_legacy_record(record_id)
            if record is None and not v2_path:
                return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "Legacy 记录不存在"}
            src_info = self._legacy_archive.source_info()
            file_sha = src_info.get("fileSha256")
            overlay = self._overlay_store.get_overlay(file_sha, record_id) if file_sha else None
            st = (record or {}).get("settlement") if isinstance((record or {}).get("settlement"), dict) else {}
            refs = (st.get("truthEvidence") or {}).get("evidenceReferences") or []
            uri = refs[0].get("uri") if refs else None
            sha = refs[0].get("sha256") if refs else (v2_sha or None)
            if overlay and overlay.get("screenshot"):
                uri = overlay["screenshot"].get("uri") or uri
                sha = overlay["screenshot"].get("sha256") or sha
            image_path = self._evidence_image(uri, source) or v2_path
            proposals = self._run_recognizer(image_path) if image_path is not None else []
            review = self._build_dto(
                record_id, {"settlement": st}, uri, sha, image_path, proposals
            )
            review["source"] = "legacy"
            review["legacy"] = {
                "key": record_id,
                "fileSha256": file_sha,
                "file": src_info.get("path"),
            }
            if image_path is None and record:
                embedded = self._legacy_archive.embedded_screenshot(record)
                if embedded:
                    review["screenshot"] = {
                        "available": True,
                        "uri": None,
                        "sha256": embedded["sha256"],
                        "dataUrl": embedded["dataUrl"],
                        "source": embedded["source"],
                    }
            review["reviewedItems"] = (overlay or {}).get("reviewedItems") or []
            review["settlement"]["reviewed"] = bool((overlay or {}).get("reviewedItems"))
            review["settlement"]["reviewedAt"] = ((overlay or {}).get("reviewProvenance") or {}).get("reviewedAt")
            return {"ok": True, "review": review}

        record = self._load_record(record_id, source)
        if record is None and not v2_path:
            return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "记录不存在"}
        st = (record or {}).get("settlement") or {}
        refs = (st.get("truthEvidence") or {}).get("evidenceReferences") or []
        uri = refs[0].get("uri") if refs else None
        sha = refs[0].get("sha256") if refs else (v2_sha or None)
        # v2 has an explicit main-settlement role. Older saved reference lists
        # can start with a warehouse crop and must not override that main image.
        if v2_path is not None:
            image_path = v2_path
            uri = v2_path.relative_to(self._data_root(source)).as_posix()
            sha = v2_sha
        else:
            image_path = self._evidence_image(uri, source)
        sanitized_key = record_id.replace(":", "_")
        descriptors = v2_store.list_record_evidence(sanitized_key)
        main_desc = next((d for d in descriptors if d.get("kind") == KIND_MAIN and d.get('sha256') == sha), None)
        if not main_desc:
            main_desc = next((d for d in descriptors if d.get('sha256') == sha), None)
        if not main_desc and descriptors:
            main_desc = next((d for d in descriptors if d.get("kind") == KIND_MANUAL_GAME), descriptors[0])
        parent_ev_id = main_desc.get("evidenceId") if main_desc else None
        parent_sha = main_desc.get("sha256") if main_desc else sha

        review_units = (record or {}).get("settlement", {}).get("reviewUnits") or (record or {}).get("reviewUnits") or []
        is_warehouse_record = bool(review_units or (record or {}).get("warehouseIdentityReview") or (record or {}).get("warehouseOccupancy"))

        grouping_hypotheses = []
        identity_evidences = []

        if is_warehouse_record and review_units:
            proposals = []
            for idx, u in enumerate(review_units):
                uid = u.get("reviewUnitId") or f"unit_{idx}"
                status = u.get("confirmationStatus")
                cid = u.get("selectedCatalogId")
                cname = u.get("canonicalName")
                rarity = u.get("rarity") or "purple"
                shape = u.get("gridShape") or "1x1"

                formatted_cands = []
                for c in (u.get("candidates") or []):
                    formatted_cands.append({
                        "catalogId": c.get("catalogId"),
                        "name": c.get("name") or "待辨认",
                        "rarity": c.get("rarity") or rarity,
                        "value": c.get("value") or c.get("price"),
                        "templateScore": c.get("templateScore") or c.get("score"),
                    })
                if status == "CONFIRMED" and cid and not any(c.get("catalogId") == cid for c in formatted_cands):
                    formatted_cands.insert(0, {
                        "catalogId": cid,
                        "name": cname or "待辨认",
                        "rarity": rarity,
                        "value": None,
                        "templateScore": 1.0,
                    })

                crop_data_url = None
                crop_rel = u.get("cropPath")
                if crop_rel:
                    crop_full = self._data_root(source) / crop_rel.replace("/", os.sep)
                    if crop_full.is_file():
                        crop_bytes = crop_full.read_bytes()
                        crop_data_url = "data:image/png;base64," + base64.b64encode(crop_bytes).decode("ascii")

                identity_evidences.append({
                    "groupingHypothesisId": uid,
                    "reviewUnitId": uid,
                    "rarity": rarity,
                    "gridShape": shape,
                    "identityStatus": "EXACT_IDENTIFIED" if status == "CONFIRMED" else "AMBIGUOUS_CANDIDATES",
                    "candidateCatalogId": cid,
                    "candidates": formatted_cands,
                    "top1Score": 1.0 if status == "CONFIRMED" else (formatted_cands[0].get("templateScore") if formatted_cands else None),
                    "cropDataUrl": crop_data_url,
                    "cropPath": u.get("cropPath"),
                    "cropSha256": u.get("cropSha256"),
                    "cells": u.get("cells") or [],
                    "bbox": u.get("bbox") or [],
                    "confirmationStatus": status,
                    "canonicalName": cname,
                    "selectedCatalogId": cid,
                    "recordStableKey": record_id,
                    "parentEvidenceId": parent_ev_id,
                    "parentSha256": parent_sha,
                })
                grouping_hypotheses.append({
                    "groupingHypothesisId": uid,
                    "reviewUnitId": uid,
                    "rarity": rarity,
                    "gridShape": shape,
                    "cells": u.get("cells") or [],
                    "bbox": u.get("bbox") or [],
                    "recordStableKey": record_id,
                    "parentEvidenceId": parent_ev_id,
                    "parentSha256": parent_sha,
                })
        else:
            proposals = self._run_recognizer(image_path) if image_path is not None else []
            img = v2_img
            if img is None and image_path is not None:
                img = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)

            if img is not None:
                rec = SettlementItemRecognizer()
                ledger = rec.parse_settlement_ledger(img)
                grouping_hypotheses = ledger.get("physicalGroupingHypotheses") or []

                h, w = img.shape[:2]
                gx1, gy1, gx2, gy2 = settlement_grid_bounds(img)
                crop = img[gy1:gy2, gx1:gx2] if gx2 > gx1 and gy2 > gy1 else img

                resolver = get_global_catalog_candidate_resolver()
                identity_evidences = resolver.resolve_identity_evidence_for_hypotheses(
                    grouping_hypotheses,
                    crop_image=crop,
                    templates=rec.templates,
                )

                for ev, hyp in zip(identity_evidences, grouping_hypotheses):
                    ev["recordStableKey"] = record_id
                    ev["parentEvidenceId"] = parent_ev_id
                    ev["parentSha256"] = parent_sha
                    hyp["recordStableKey"] = record_key if (record_key := record_id) else None
                    hyp["parentEvidenceId"] = parent_ev_id
                    hyp["parentSha256"] = parent_sha
                    bbox = hyp.get("bbox")
                    if crop is not None and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                        bx, by, bw, bh = bbox
                        if by + bh <= crop.shape[0] and bx + bw <= crop.shape[1] and bw > 0 and bh > 0:
                            item_roi = crop[by:by+bh, bx:bx+bw]
                            _, buf = cv2.imencode(".png", item_roi)
                            ev["cropDataUrl"] = "data:image/png;base64," + base64.b64encode(buf).decode("ascii")

        v2_reviewed = load_settlement_reviewed_truth(v2_store, sanitized_key)
        reviewed_items = v2_reviewed if v2_reviewed else (st.get("reviewedItems") or [])

        dto = self._build_dto(record_id, record or {"settlement": st}, uri, sha, image_path, proposals)
        dto["source"] = source
        dto["groupingHypotheses"] = grouping_hypotheses
        dto["identityEvidence"] = identity_evidences
        dto["reviewUnits"] = identity_evidences
        dto["reviewedItems"] = reviewed_items
        dto["settlement"]["reviewed"] = bool(reviewed_items)
        if v2_reviewed and v2_reviewed[0].get("reviewedAt"):
            dto["settlement"]["reviewedAt"] = v2_reviewed[0].get("reviewedAt")

        if main_desc:
            dto["screenshot"]["evidenceId"] = main_desc.get("evidenceId")
            dto["screenshot"]["warehouseCoverage"] = COVERAGE_PARTIAL
            dto["screenshot"]["coverageStatus"] = COVERAGE_UNPROVEN
            dto["screenshot"]["width"] = main_desc.get("width")
            dto["screenshot"]["height"] = main_desc.get("height")
            dto["evidence"] = main_desc

        return {
            "ok": True,
            "review": dto,
        }

    def apply_item_review_action(
        self,
        record_id: str,
        action_payload: Mapping[str, Any],
        source: str = "current",
    ) -> Dict[str, Any]:
        """Apply an item-level review action (CONFIRM_CANDIDATE or CONFIRM_CATALOG_OVERRIDE)
        using C3.4A settlement_human_review bridge.

        Zero writes to History canonical business data, zero writes to knownItems/Solver/CurrentMatch.
        """
        session_res = self.create_review_session(record_id, source=source)
        if not session_res.get("ok"):
            return session_res

        review_dto = session_res.get("review") or {}
        identity_evidences = review_dto.get("identityEvidence") or []
        grouping_hypotheses = review_dto.get("groupingHypotheses") or []

        v2_store = self._v2_store(source)
        try:
            reviewed_item = apply_settlement_human_review_action(
                store=v2_store,
                candidate_evidence_list=identity_evidences,
                action_payload=action_payload,
                proposals=grouping_hypotheses,
            )
        except SettlementHumanReviewError as exc:
            return {
                "ok": False,
                "status": exc.code,
                "message": str(exc),
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "ERROR",
                "message": str(exc),
            }

        updated_reviews = load_settlement_reviewed_truth(v2_store, record_id)
        return {
            "ok": True,
            "recordId": record_id,
            "reviewedItem": reviewed_item,
            "reviewedItems": updated_reviews,
            "reviewedCount": len(updated_reviews),
        }

    def rerun_recognition(
        self,
        record_id: str,
        source: str = "current",
    ) -> Dict[str, Any]:
        """Explicit re-recognition for an existing stored settlement screenshot (4D2D1M-C3.5C):

        1. Checks that a valid file-backed raw screenshot exists in Evidence Store v2 or evidence refs.
        2. If no screenshot exists -> returns NO_SCREENSHOT_EVIDENCE fail-closed.
        3. Runs existing recognizer -> physical grouping hypotheses -> identity evidence resolver.
        4. Binds provenance (recordStableKey, parentEvidenceId, parentSha256, bbox, cells).
        5. Zero auto-review, zero promotion of UNIQUE/EXACT to reviewed truth, zero modification to existing reviewed truth.
        6. Coverage strictly remains PARTIAL / COVERAGE_UNPROVEN.
        7. Zero writes to canonical business data, knownItems, Solver, CurrentMatch.
        """
        sanitized_key = record_id.replace(":", "_")
        v2_store = self._v2_store(source)
        v2_path, v2_sha, v2_img = self._load_v2_evidence_for_record(record_id, source)

        record = self._load_legacy_record(record_id) if source == "legacy" else self._load_record(record_id, source)
        if record is None and not v2_path:
            return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "记录不存在"}

        st = (record or {}).get("settlement") if isinstance((record or {}).get("settlement"), dict) else {}
        refs = (st.get("truthEvidence") or {}).get("evidenceReferences") or []
        uri = refs[0].get("uri") if refs else None
        sha = refs[0].get("sha256") if refs else (v2_sha or None)
        image_path = self._evidence_image(uri, source) or v2_path

        img = v2_img
        if img is None and image_path is not None and Path(image_path).is_file():
            img = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)

        if img is None:
            return {
                "ok": False,
                "status": "NO_SCREENSHOT_EVIDENCE",
                "message": "当前记录无已持久化的结算截图，请先导入截图",
            }

        # Look up parent raw evidence descriptor from v2 store
        descriptors = v2_store.list_record_evidence(sanitized_key)
        main_desc = next((d for d in descriptors if d.get("kind") == KIND_MAIN and d.get('sha256') == sha), None)
        parent_ev_id = main_desc.get("evidenceId") if main_desc else None
        parent_sha = main_desc.get("sha256") if main_desc else sha

        rec = SettlementItemRecognizer()
        ledger = rec.parse_settlement_ledger(img)
        grouping_hypotheses = ledger.get("physicalGroupingHypotheses") or []

        h, w = img.shape[:2]
        gx1, gy1, gx2, gy2 = settlement_grid_bounds(img)
        crop = img[gy1:gy2, gx1:gx2] if gx2 > gx1 and gy2 > gy1 else img

        resolver = get_global_catalog_candidate_resolver()
        identity_evidences = resolver.resolve_identity_evidence_for_hypotheses(
            grouping_hypotheses,
            crop_image=crop,
            templates=rec.templates,
        )

        for ev, hyp in zip(identity_evidences, grouping_hypotheses):
            ev["recordStableKey"] = record_id
            ev["parentEvidenceId"] = parent_ev_id
            ev["parentSha256"] = parent_sha
            bbox = hyp.get("bbox")
            if crop is not None and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                bx, by, bw, bh = bbox
                if by + bh <= crop.shape[0] and bx + bw <= crop.shape[1] and bw > 0 and bh > 0:
                    item_roi = crop[by:by+bh, bx:bx+bw]
                    _, buf = cv2.imencode(".png", item_roi)
                    ev["cropDataUrl"] = "data:image/png;base64," + base64.b64encode(buf).decode("ascii")

        # Load existing reviewed items (strict isolation: NEVER modify or overwrite)
        v2_reviewed = load_settlement_reviewed_truth(v2_store, sanitized_key)
        overlay = self._overlay_store.get_overlay(self._legacy_archive.source_info().get("fileSha256") or "", record_id) if source == "legacy" else None
        reviewed_items = (overlay or {}).get("reviewedItems") if source == "legacy" else (v2_reviewed or (st.get("reviewedItems") or []))

        proposals = self._run_recognizer(image_path) if image_path is not None else []
        dto = self._build_dto(record_id, record or {"settlement": st}, uri, sha, image_path, proposals)
        dto["source"] = source
        dto["groupingHypotheses"] = grouping_hypotheses
        dto["identityEvidence"] = identity_evidences
        dto["reviewedItems"] = reviewed_items
        dto["settlement"]["reviewed"] = bool(reviewed_items)
        if v2_reviewed and v2_reviewed[0].get("reviewedAt"):
            dto["settlement"]["reviewedAt"] = v2_reviewed[0].get("reviewedAt")

        if main_desc:
            dto["screenshot"]["evidenceId"] = main_desc.get("evidenceId")
            dto["screenshot"]["warehouseCoverage"] = COVERAGE_PARTIAL
            dto["screenshot"]["coverageStatus"] = COVERAGE_UNPROVEN
            dto["screenshot"]["width"] = main_desc.get("width")
            dto["screenshot"]["height"] = main_desc.get("height")
            dto["evidence"] = main_desc

        return {
            "ok": True,
            "status": "RERECOGNITION_COMPLETED",
            "recordId": record_id,
            "review": dto,
            "identityEvidenceCount": len(identity_evidences),
            "groupingHypothesesCount": len(grouping_hypotheses),
        }

    def import_screenshot(
        self,
        record_id: str,
        source_path: str,
        source: str = "current",
    ) -> Dict[str, Any]:
        """Import / backfill a user-selected settlement screenshot (png/jpg/jpeg) for an existing History record.

        1. File-backed immutable storage into Evidence Store v2 (never overwrite)
        2. Binds recordStableKey, evidenceId, SHA-256, width/height, byteSize, mimeType, kind, capturedAt
        3. Coverage is strictly PARTIAL / COVERAGE_UNPROVEN
        4. Zero recognition, zero grouping, zero identity resolution, zero automatic review
        5. Zero writes to History canonical business fields (clearing/profit), knownItems, Solver, CurrentMatch.
        """
        record = self._load_legacy_record(record_id) if source == "legacy" else self._load_record(record_id, source)
        if record is None:
            return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "请先选择要绑定的 History 记录"}
        src = Path(source_path)
        if not src.is_file():
            return {"ok": False, "status": "SOURCE_NOT_FOUND", "message": "源文件不存在"}
        suffix = src.suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg"):
            return {"ok": False, "status": "UNSUPPORTED_FORMAT", "message": "仅支持 png / jpg / jpeg"}
        try:
            raw = src.read_bytes()
        except OSError as exc:
            return {"ok": False, "status": "SOURCE_UNREADABLE", "message": str(exc)}
        if not raw:
            return {"ok": False, "status": "EMPTY_FILE", "message": "文件为空"}

        digest = _sha256_bytes(raw)
        ext = ".png" if suffix == ".png" else ".jpg"
        dst_name = f"import_{digest[:16]}{ext}"
        dst = self._evidence_dir(source) / dst_name
        if not dst.exists():
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            tmp.write_bytes(raw)
            os.replace(str(tmp), str(dst))
        uri = f"evidence/settlement/{dst_name}"

        sanitized_key = record_id.replace(":", "_")
        v2_store = self._v2_store(source)
        try:
            desc = v2_store.save_original(
                record_stable_key=sanitized_key,
                kind=KIND_MAIN,
                image_bytes=raw,
                captured_at=_aware_now(),
                coverage_mode="viewport-segment",
                coverage_status=COVERAGE_UNPROVEN,
                evidence_origin="user-import",
            )
        except Exception as exc:
            return {"ok": False, "status": "STORE_SAVE_FAILED", "message": str(exc)}

        file_sha = None
        src_file_path = None
        record = None
        st = {}
        overlay = None
        if source == "legacy":
            record = self._load_legacy_record(record_id)
            if record is None:
                return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "Legacy 记录不存在"}
            src_info = self._legacy_archive.source_info()
            file_sha = src_info.get("fileSha256")
            src_file_path = src_info.get("path")
            st = record.get("settlement") if isinstance(record.get("settlement"), dict) else {}
            if file_sha:
                overlay = self._overlay_store.get_overlay(file_sha, record_id)
        else:
            record = self._load_record(record_id, source)
            if record is None:
                return {
                    "ok": False,
                    "status": "RECORD_NOT_FOUND",
                    "message": "请先选择要绑定的 History 记录",
                }
            st = record.get("settlement") or {}

        v2_blob_path = v2_store.root / desc["relativePath"]
        data_url = _read_file_as_data_url(v2_blob_path) or _read_file_as_data_url(dst)

        v2_reviewed = load_settlement_reviewed_truth(v2_store, sanitized_key)
        reviewed_items = (overlay or {}).get("reviewedItems") if source == "legacy" else (v2_reviewed or (st.get("reviewedItems") or []))
        review_dto = {
            "recordId": record_id,
            "identityEditable": source in {"current", "live-trial"} and record.get("lifecycleStatus") == "DRAFT",
            "source": source,
            "settlement": {
                "clearingPrice": st.get("clearingPrice"),
                "actualTotal": st.get("actualTotal"),
                "realizedProfit": st.get("realizedProfit"),
                "acquired": st.get("acquired"),
                "winner": st.get("winner"),
                "reviewed": bool(reviewed_items),
                "reviewedAt": (reviewed_items or [{}])[0].get("reviewedAt") if reviewed_items else None,
            },
            "screenshot": {
                "available": True,
                "uri": uri,
                "v2Path": desc["relativePath"],
                "sha256": digest,
                "dataUrl": data_url,
                "evidenceId": desc["evidenceId"],
                "width": desc["width"],
                "height": desc["height"],
                "warehouseCoverage": COVERAGE_PARTIAL,
                "coverageStatus": COVERAGE_UNPROVEN,
                "source": "manual history backfill",
            },
            "evidence": desc,
            "proposals": [],
            "groupingHypotheses": [],
            "identityEvidence": [],
            "reviewedItems": reviewed_items,
            "provenance": {
                "source": "manual history backfill",
                "sourceFilePath": str(src.resolve()),
                "importedAt": desc["capturedAt"],
                "sha256": digest,
                "evidenceId": desc["evidenceId"],
                "warehouseCoverage": COVERAGE_PARTIAL,
                "coverageStatus": COVERAGE_UNPROVEN,
                "uri": uri,
            },
        }
        if source == "legacy":
            review_dto["legacy"] = {
                "key": record_id,
                "fileSha256": file_sha,
                "file": src_file_path,
            }

        return {
            "ok": True,
            "status": "EVIDENCE_BACKFILLED",
            "recordId": record_id,
            "evidence": desc,
            "provenance": review_dto["provenance"],
            "review": review_dto,
        }

    def save_reviewed_settlement(
        self,
        record_id: str,
        reviewed_items: List[Dict[str, Any]],
        review_meta: Optional[Dict[str, Any]] = None,
        source: str = "current",
        runtime_file_originals: Optional[List[Dict[str, Any]]] = None,
        identity_review: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Transactionally persist user-reviewed itemized truth.

        - current: into the canonical record's settlement.reviewedItems,
          preserving all machine evidence; on failure the record is untouched.
        - legacy: into the ReviewOverlay sidecar store bound to the legacy
          source file hash + stable record key; the original JSON is never
          modified.
        """
        if not isinstance(reviewed_items, list):
            return {"ok": False, "status": "REVIEWED_ITEMS_INVALID", "message": "reviewedItems 必须为数组"}
        if identity_review is not None:
            from auto_archiver import FORBIDDEN_WINNER_PLACEHOLDERS
            if source not in {"current", "live-trial"} or not isinstance(identity_review, dict):
                return {"ok": False, "message": "仅支持本地草稿的身份核对"}
            winner = identity_review.get("winner")
            if not isinstance(winner, str) or not winner.strip() or winner.strip() in FORBIDDEN_WINNER_PLACEHOLDERS:
                return {"ok": False, "message": "请填写结算画面中的竞得者名称"}
            identity_review = {"winner": winner.strip(), "acquired": identity_review.get("acquired"), "reviewedAt": _aware_now()}

        if source == "legacy":
            record = self._load_legacy_record(record_id)
            if record is None:
                return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "Legacy 记录不存在"}
            src_info = self._legacy_archive.source_info()
            file_sha = src_info.get("fileSha256")
            if not file_sha:
                return {"ok": False, "status": "SOURCE_UNREADABLE", "message": "Legacy 源文件不可读"}
            # latest imported screenshot sha (fall back to overlay/record evidence)
            screenshot_sha = None
            screenshot_uri = None
            overlay_prev = self._overlay_store.get_overlay(file_sha, record_id)
            if overlay_prev and overlay_prev.get("screenshot"):
                screenshot_sha = overlay_prev["screenshot"].get("sha256")
                screenshot_uri = overlay_prev["screenshot"].get("uri")
            try:
                saved = self._overlay_store.save_overlay(
                    file_sha256=file_sha,
                    record_key=record_id,
                    source_file_name=src_info.get("path") or "异环拍卖数据.json",
                    screenshot_uri=screenshot_uri,
                    screenshot_sha256=screenshot_sha,
                    reviewed_items=reviewed_items,
                    review_meta=review_meta,
                )
            except Exception as exc:
                return {"ok": False, "status": "SAVE_FAILED", "message": str(exc)}
            return {
                "ok": True,
                "recordId": record_id,
                "reviewedCount": len(saved.get("reviewedItems") or []),
                "reviewedAt": (saved.get("reviewProvenance") or {}).get("reviewedAt"),
                "lane": "legacy_overlay",
            }

        if source not in {"current", "live-trial"}:
            return {"ok": False, "status": "SOURCE_UNSUPPORTED", "message": "当前复核来源不支持写入"}
        record = self._load_record(record_id, source)
        if record is None:
            return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "记录不存在"}
        if identity_review is not None and str(record.get("lifecycleStatus") or "").upper() != "DRAFT":
            return {"ok": False, "status": "IDENTITY_REVIEW_DRAFT_ONLY", "message": "仅允许核对本地草稿"}

        now = _aware_now()
        base_sha = None
        st_prev = record.get("settlement") or {}
        if st_prev.get("truthEvidence") and st_prev["truthEvidence"].get("evidenceReferences"):
            base_sha = st_prev["truthEvidence"]["evidenceReferences"][0].get("sha256")

        client_meta = review_meta if isinstance(review_meta, dict) else {}
        # Client-supplied descriptors/paths/hashes are never trusted as v2 originals.
        backend_originals = runtime_file_originals
        if backend_originals is None:
            backend_originals = lookup_runtime_file_originals(record_id, self._data_root(source))

        patch = {
            "settlement": {
                "reviewedItems": reviewed_items,
                "reviewedAt": now,
                "reviewProvenance": {
                    "reviewedBy": "user",
                    "reviewedAt": now,
                    "baseSha256": base_sha,
                    "reviewMeta": {
                        key: value
                        for key, value in client_meta.items()
                        if key not in {"fileOriginals", "descriptor", "relativePath", "sha256"}
                    },
                },
            }
        }

        if backend_originals:
            try:
                verified = [
                    verify_runtime_original(item, record_id=record_id, data_root=self._data_root(source))
                    for item in backend_originals
                ]
                patch["settlement"]["truthEvidence"] = build_truth_evidence_v2(
                    record_id=record_id,
                    existing=st_prev.get("truthEvidence") if isinstance(st_prev.get("truthEvidence"), dict) else {},
                    settlement=st_prev,
                    originals=verified,
                    observed_at=now,
                )
            except ReviewFileOriginalError as exc:
                return {
                    "ok": False,
                    "status": exc.status,
                    "warning": exc.message,
                    "message": exc.message,
                }
        elif client_meta.get("screenshotUri") and client_meta.get("screenshotSha256"):
            existing_ev = st_prev.get("truthEvidence") or {}
            refs = sanitize_evidence_references(existing_ev.get("evidenceReferences"))
            pointer = {
                "uri": str(client_meta["screenshotUri"]).strip(),
                "sha256": str(client_meta["screenshotSha256"]).strip().lower(),
            }
            refs = [item for item in refs if item != pointer]
            refs.insert(0, pointer)
            if existing_ev:
                upgraded = dict(existing_ev)
                upgraded["evidenceReferences"] = refs
                if "type" in upgraded:
                    upgraded.pop("type", None)
                patch["settlement"]["truthEvidence"] = upgraded
            else:
                actual_tot = st_prev.get("actualTotal")
                patch["settlement"]["truthEvidence"] = {
                    "schemaVersion": "settlement-truth-evidence.v1",
                    "matchId": record_id,
                    "actualTotal": float(actual_tot) if actual_tot not in (None, "") else None,
                    "settlementObservedAt": now,
                    "truthSource": "user_import",
                    "truthConfidence": "high",
                    "evidenceReferences": refs,
                }

        try:
            if source == "live-trial":
                updated = self._native_trial_store.update_reviewed_draft(
                    record_id, patch, identity_review=identity_review
                )
            else:
                updated = self._store(source).update_record_transactional(
                    record_id, patch, identity_review=identity_review
                )
        except Exception as exc:
            return {"ok": False, "status": "SAVE_FAILED", "message": str(exc)}
        st = updated.get("settlement") or {}
        return {
            "ok": True,
            "recordId": record_id,
            "reviewedCount": len(st.get("reviewedItems") or []),
            "reviewedAt": st.get("reviewedAt"),
            "identityReviewed": identity_review is not None,
            "source": source,
        }
