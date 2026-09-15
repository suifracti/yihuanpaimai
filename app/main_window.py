"""Native lifetime owner and presentation-only Main dashboard host."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

from main_view_state import (
    MainViewStateSnapshot,
    unavailable_main_view_state_snapshot,
)
from mascot_presentation_state import MascotPresentationSnapshot
from presentation_runtime import PresentationRuntimeSnapshot


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _verified_project_asset(project_root: Path, relative_path: str, sha256: str) -> Path:
    root = project_root.resolve()
    resolved = (root / Path(relative_path)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Mascot asset escapes project root: {relative_path}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if digest != sha256:
        raise ValueError(f"Mascot asset hash mismatch: {relative_path}")
    return resolved


def load_mascot_presentation_contract(project_root: Path) -> dict:
    """Load the frozen presentation-only mascot mapping and verify every byte."""
    project_root = Path(project_root).resolve()
    manifest_path = project_root / "design/mascot/mascot_final_asset_manifest_v1.json"
    state_map_path = project_root / "design/mascot/mascot_state_asset_map_v1.json"
    manifest = _read_json(manifest_path)
    state_map = _read_json(state_map_path)

    if manifest.get("schemaVersion") != "mascot.final-assets.v1":
        raise ValueError("Unsupported mascot asset manifest")
    if state_map.get("schemaVersion") != "mascot.state-assets.v1":
        raise ValueError("Unsupported mascot state mapping")
    declared_manifest = (project_root / state_map.get("manifestPath", "")).resolve()
    if declared_manifest != manifest_path.resolve():
        raise ValueError("Mascot state mapping points to an unexpected manifest")
    boundary = state_map.get("authorityBoundary") or {}
    if boundary != {
        "controlsPresentationAssetOnly": True,
        "controlsSolverState": False,
        "controlsCanonicalFacts": False,
    }:
        raise ValueError("Mascot state mapping exceeds presentation authority")

    assets = {}
    for record in manifest.get("assets", []):
        asset_id = record.get("assetId")
        if not asset_id or asset_id in assets:
            raise ValueError(f"Invalid or duplicate mascot assetId: {asset_id!r}")
        if record.get("status") != "approved_final":
            continue
        asset_path = _verified_project_asset(
            project_root, record["path"], record["sha256"]
        )
        assets[asset_id] = {
            "assetId": asset_id,
            "role": record["role"],
            "uri": asset_path.as_uri(),
            "width": record["width"],
            "height": record["height"],
        }

    states = state_map.get("states") or {}
    if set(states) != {"idle", "loading", "thinking", "success", "warning", "sleep"}:
        raise ValueError("Mascot presentation states are incomplete")
    for state, asset_id in states.items():
        record = assets.get(asset_id)
        if record is None or record["role"] != state_map.get("presentationRole"):
            raise ValueError(f"Mascot state {state!r} has no approved chibi asset")
    if state_map.get("fallbackState") not in states:
        raise ValueError("Mascot fallback state is not mapped")

    portrait_id = state_map.get("defaultPortraitAssetId")
    if portrait_id not in assets or assets[portrait_id]["role"] != "portrait":
        raise ValueError("Mascot default portrait is not approved")
    if states["loading"] != "mascot.chibi.loading.v2":
        raise ValueError("Mascot loading state must use approved loading v2")

    return {
        "mode": "presentation_only",
        "manifestId": manifest["manifestId"],
        "mappingId": state_map["mappingId"],
        "defaultPortraitAssetId": portrait_id,
        "fallbackState": state_map["fallbackState"],
        "states": states,
        "assets": assets,
    }


class OverlayVisibilityController:
    """Show or hide one already-created overlay without replacing it."""

    def __init__(self, overlay, on_visibility_changed: Optional[Callable[[bool], None]] = None):
        self._overlay = overlay
        self._overlay_identity = id(overlay)
        self._on_visibility_changed = on_visibility_changed
        self._accepting_commands = True

    @property
    def overlay(self):
        return self._overlay

    @property
    def overlay_identity(self) -> int:
        return self._overlay_identity

    @property
    def visible(self) -> bool:
        return bool(self._overlay.Visible)

    def stop_accepting_commands(self) -> None:
        self._accepting_commands = False

    def show(self) -> bool:
        if not self._accepting_commands:
            return self.visible
        self._overlay.Show()
        self._publish()
        return self.visible

    def hide(self) -> bool:
        if not self._accepting_commands:
            return self.visible
        self._overlay.Hide()
        self._publish()
        return self.visible

    def toggle(self) -> bool:
        return self.hide() if self.visible else self.show()

    def _publish(self) -> None:
        if self._on_visibility_changed:
            self._on_visibility_changed(self.visible)


class ShutdownCoordinator:
    """Run shutdown steps once, in order, and continue after individual failures."""

    def __init__(
        self,
        begin_shutdown: Callable[[], None],
        cleanup_steps: Iterable[Tuple[str, Callable[[], None]]],
        close_main: Callable[[], None],
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self._begin_shutdown = begin_shutdown
        self._cleanup_steps = tuple(cleanup_steps)
        self._close_main = close_main
        self._logger = logger
        self._lock = threading.Lock()
        self._started = False
        self._reason = None

    @property
    def started(self) -> bool:
        with self._lock:
            return self._started

    @property
    def reason(self):
        with self._lock:
            return self._reason

    def request(self, reason: str, close_main: bool) -> bool:
        with self._lock:
            if self._started:
                return False
            self._started = True
            self._reason = str(reason or "unknown")

        self._log("SHUTDOWN:MAIN", f"shutdown started reason={self._reason}")
        self._run_step("disable-ui", self._begin_shutdown)
        for name, step in self._cleanup_steps:
            self._run_step(name, step)
        if close_main:
            self._run_step("close-main", self._close_main)
        self._log("SHUTDOWN:MAIN", "shutdown coordination completed")
        return True

    def _run_step(self, name: str, step: Callable[[], None]) -> None:
        try:
            step()
            self._log("SHUTDOWN:MAIN", f"shutdown step={name} ok")
        except Exception as exc:
            self._log("SHUTDOWN:MAIN", f"shutdown step={name} failed: {exc}")

    def _log(self, category: str, message: str) -> None:
        if self._logger:
            self._logger(category, message)


class MainWindowBridge:
    """Narrow Main presentation bridge with no Solver or canonical-state access."""

    ALLOWED_ACTIONS = frozenset(
        (
            "toggle_overlay",
            "get_overlay_visibility",
            "toggle_main_pin",
            "set_main_pin",
            "request_app_status",
            "delete_history_record",
            "delete_history_records",
            "request_legacy_archive",
            "select_legacy_archive_source",
            "request_settlement_review",
            "request_original_screenshots",
            "delete_original_screenshot",
            "restore_original_screenshot",
            "import_settlement_screenshot",
            "replace_settlement_screenshot",
            "delete_settlement_screenshot",
            "rerun_settlement_recognition",
            "save_settlement_review",
            "settlement_item_review_action",
            "manual_facts",
            "manual_next_match",
            "manual_finalize",
            "manual_bootstrap",
            "start_live_vision",
            "triggered_snapshot",
            "save_settlement_screenshot",
            "save_game_screenshot",
            "start_warehouse_capture",
            "prepare_warehouse_capture",
            "confirm_warehouse_capture",
            "stop_warehouse_capture",
            "prepare_warehouse_manual_takeover",
            "start_warehouse_manual_takeover",
            "capture_warehouse_manual_page",
            "finish_warehouse_manual_capture",
            "cancel_warehouse_manual_capture",
            "warehouse_identity_review",
            "export_history_records",
            "export_reviewed_labels",
            "import_history_bundle",
        )
    )
    REVIEW_CLIENT_KEYS = frozenset(
        (
            "action",
            "op",
            "reviewOp",
            "requestId",
            "recordId",
            "sessionId",
            "packetFingerprint",
            "trackId",
            "observationId",
            "selectedCatalogId",
            "candidateId",
            "query",
            "reviewAction",
            "confirmCandidate",
            "confirmOverride",
            "confirmedByHuman",
            "overrideReason",
            "reason",
            "geometryErrorType",
            "filterUnresolved",
            "reviewedAt",
            "groupingHypothesisId",
            "proposalId",
        )
    )

    def __init__(
        self,
        overlay_controller,
        presentation_runtime_provider=None,
        main_view_state_provider=None,
        mascot_state_provider=None,
        current_match_provider=None,
        delete_history_provider=None,
        delete_history_records_provider=None,
        settlement_review_service=None,
        legacy_archive_provider=None,
        manual_facts_provider=None,
        manual_next_match_provider=None,
        manual_finalize_provider=None,
        manual_bootstrap_provider=None,
        start_vision_provider=None,
        triggered_snapshot_provider=None,
        save_settlement_screenshot_provider=None,
        save_game_screenshot_provider=None,
        warehouse_capture_host=None,
        warehouse_identity_review_session=None,
        warehouse_identity_review_history_store=None,
        history_path_provider=None,
        topmost_controller=None,
        user_pinned: bool = True,
    ):
        self._overlay_controller = overlay_controller
        self._presentation_runtime_provider = presentation_runtime_provider
        self._main_view_state_provider = main_view_state_provider
        self._mascot_state_provider = mascot_state_provider
        self._current_match_provider = current_match_provider
        self._delete_history_provider = delete_history_provider
        self._delete_history_records_provider = delete_history_records_provider
        self._settlement_review_service = settlement_review_service
        self._legacy_archive_provider = legacy_archive_provider
        self._manual_facts_provider = manual_facts_provider
        self._manual_next_match_provider = manual_next_match_provider
        self._manual_finalize_provider = manual_finalize_provider
        self._manual_bootstrap_provider = manual_bootstrap_provider
        self._start_vision_provider = start_vision_provider
        self._triggered_snapshot_provider = triggered_snapshot_provider
        self._save_settlement_screenshot_provider = save_settlement_screenshot_provider
        self._save_game_screenshot_provider = save_game_screenshot_provider
        self._warehouse_capture_host = warehouse_capture_host
        self._warehouse_identity_review_session = warehouse_identity_review_session
        self._warehouse_identity_review_history_store = warehouse_identity_review_history_store
        self._history_path_provider = history_path_provider
        self._topmost_controller = topmost_controller
        self._user_pinned = bool(user_pinned)
        self._capture_safety_override = False
        self._applied_effective_topmost: Optional[bool] = None
        try:
            from main import register_capture_safety_override_callback
            register_capture_safety_override_callback(self.set_capture_safety_override)
        except Exception:
            pass

    @property
    def user_pinned(self) -> bool:
        return self._user_pinned

    @property
    def capture_safety_override(self) -> bool:
        return self._capture_safety_override

    @property
    def effective_topmost(self) -> bool:
        return bool(self._user_pinned and not self._capture_safety_override)

    def set_user_pinned(self, enable: bool) -> bool:
        enable = bool(enable)
        if self._user_pinned == enable and self._applied_effective_topmost is not None:
            return self._user_pinned
        self._user_pinned = enable
        self._apply_effective_topmost()
        return self._user_pinned

    def set_capture_safety_override(self, override: bool) -> bool:
        override = bool(override)
        try:
            import main as app_main
            app_main._CAPTURE_SAFETY_OVERRIDE_FLAG = override
        except Exception:
            pass
        if self._capture_safety_override == override and self._applied_effective_topmost is not None:
            return self._capture_safety_override
        self._capture_safety_override = override
        self._apply_effective_topmost()
        return self._capture_safety_override

    def _apply_effective_topmost(self) -> None:
        effective = self.effective_topmost
        if self._applied_effective_topmost == effective:
            return
        self._applied_effective_topmost = effective
        if self._topmost_controller is not None:
            try:
                self._topmost_controller(effective)
            except Exception:
                pass

    def set_main_window_topmost(self, enable: bool) -> None:
        self.set_user_pinned(enable)

    def presentation_runtime_payload(self) -> dict:
        snapshot = (
            self._presentation_runtime_provider()
            if self._presentation_runtime_provider is not None
            else PresentationRuntimeSnapshot()
        )
        if not isinstance(snapshot, PresentationRuntimeSnapshot):
            raise TypeError("Presentation runtime provider must return a frozen snapshot")
        return snapshot.to_payload()

    def main_view_state_payload(self) -> Optional[dict]:
        if self._main_view_state_provider is None:
            return None
        try:
            snapshot = self._main_view_state_provider()
        except Exception:
            snapshot = unavailable_main_view_state_snapshot(
                "UNAVAILABLE", "HISTORY_PROVIDER_FAILED"
            )
        if not isinstance(snapshot, MainViewStateSnapshot):
            snapshot = unavailable_main_view_state_snapshot(
                "UNAVAILABLE", "HISTORY_PROVIDER_INVALID"
            )
        return snapshot.to_payload()

    def mascot_state_payload(self, application_state: str = "ready") -> Optional[dict]:
        if self._mascot_state_provider is None:
            return None
        snapshot = self._mascot_state_provider(application_state)
        if not isinstance(snapshot, MascotPresentationSnapshot):
            raise TypeError("Mascot state provider must return a frozen snapshot")
        return snapshot.to_payload()

    def warehouse_capture_payload(self) -> dict:
        host = self._warehouse_capture_host
        if host is None:
            from warehouse_capture_host import WarehouseCaptureHost

            return WarehouseCaptureHost().presentation_payload()
        return host.presentation_payload()

    def _decorate_identity_review(self, session, view) -> dict:
        payload = dict(view) if isinstance(view, dict) else {}
        try:
            from warehouse_identity_review_persist import review_persistence_status

            payload.update(
                review_persistence_status(session, self._warehouse_identity_review_history_store)
            )
        except Exception:
            payload.setdefault("persistenceAvailable", False)
            payload.setdefault("persisted", False)
            payload.setdefault("persistStatus", "UNAVAILABLE")
            payload.setdefault("persistenceCaption", "尚未写入历史记录")
        if payload.get("persisted"):
            payload["persistenceCaption"] = "已写入本局记录"
        elif not payload.get("persistenceCaption"):
            payload["persistenceCaption"] = "尚未写入历史记录"
        return payload

    def _persist_warehouse_identity_review(self, session, session_id: str, packet_fingerprint: str) -> dict:
        from warehouse_identity_review_persist import (
            WarehouseIdentityReviewPersistError,
            persist_error_copy,
            persist_warehouse_identity_review,
        )

        store = self._warehouse_identity_review_history_store
        if store is None:
            view = self._decorate_identity_review(session, session.view())
            view["persistStatus"] = "UNAVAILABLE"
            view["persistMessage"] = "历史记录不可用，未写入"
            view["persistenceAvailable"] = False
            return view
        try:
            result = persist_warehouse_identity_review(
                session=session,
                history_store=store,
                session_id=session_id,
                packet_fingerprint=packet_fingerprint,
            )
        except WarehouseIdentityReviewPersistError as exc:
            view = self._decorate_identity_review(session, session.view())
            view["persistStatus"] = exc.code
            view["persistMessage"] = persist_error_copy(exc.code)
            view["persisted"] = False
            if exc.code != "ARTIFACT_CONFLICT":
                view["persistenceAvailable"] = False
            return view
        view = self._decorate_identity_review(session, session.view())
        if result.get("ok"):
            view["persisted"] = True
            view["persistStatus"] = "SAVED"
            view["persistenceCaption"] = "已写入本局记录"
            view["persistMessage"] = "已写入本局记录"
            view["persistenceAvailable"] = False
        return view

    def _with_identity_summary(self, result, record_id: str, source: str) -> dict:
        payload = dict(result) if isinstance(result, dict) else {"ok": False}
        try:
            from warehouse_identity_review_persist import summarize_persisted_identity_review

            record = None
            if str(source or "current") == "legacy":
                record = {
                    "id": record_id if str(record_id).startswith("legacy:") else f"legacy:{record_id}",
                    "source": "legacy",
                }
            elif self._warehouse_identity_review_history_store is not None and record_id:
                record = self._warehouse_identity_review_history_store.lookup(record_id)
            summary = summarize_persisted_identity_review(record)
        except Exception:
            summary = {
                "saved": False,
                "readable": False,
                "warehouseCoverage": None,
                "reviewCompletion": None,
                "identityResolution": None,
                "resolvedCount": None,
                "excludedCount": None,
                "unresolvedCount": None,
                "caption": "仓库审阅结果不可读取",
            }
        payload["warehouseIdentitySummary"] = summary
        review = payload.get("review")
        if isinstance(review, dict):
            review = dict(review)
            review["warehouseIdentitySummary"] = summary
            settlement = (record or {}).get("settlement") or {}
            review["warehouseReviewAvailable"] = bool(settlement.get("warehouseReviewPacket"))
            review["warehouseReviewRevisions"] = [
                {"reviewedAt": item.get("reviewedAt"), "reviewerType": item.get("reviewerType"),
                 "resolvedCount": len(item.get("resolvedItems") or [])}
                for item in settlement.get("warehouseIdentityReviewHistory") or []]
            payload["review"] = review
        return payload

    def current_match_payload(self) -> Optional[dict]:
        if self._current_match_provider is None:
            return None
        try:
            summary = self._current_match_provider()
            return summary if isinstance(summary, dict) else None
        except Exception:
            return None

    def dispatch(self, message) -> dict:
        payload = json.loads(message) if isinstance(message, str) else message
        if not isinstance(payload, dict):
            raise ValueError("Main bridge message must be an object")

        action = payload.get("action")
        if action not in self.ALLOWED_ACTIONS:
            raise ValueError(f"Main bridge action is not allowed: {action!r}")

        if action == "toggle_overlay":
            visible = self._overlay_controller.toggle()
        else:
            visible = self._overlay_controller.visible

        response = {
            "type": "app_status",
            "action": action,
            "requestId": payload.get("requestId"),
            "overlayVisible": bool(visible),
            "mainPinned": bool(self._user_pinned),
            "effectiveTopMost": bool(self.effective_topmost),
            "captureSafetyOverride": bool(self._capture_safety_override),
            "applicationState": "ready",
            "presentationData": (
                "mixed" if self._main_view_state_provider is not None else "mock"
            ),
            "solverOwner": "overlay_runtime",
            "presentationRuntime": self.presentation_runtime_payload(),
            "warehouseCapture": self.warehouse_capture_payload(),
        }

        if action == "toggle_main_pin":
            self.set_user_pinned(not self._user_pinned)
            response["mainPinned"] = bool(self._user_pinned)
            response["effectiveTopMost"] = bool(self.effective_topmost)
            response["captureSafetyOverride"] = bool(self._capture_safety_override)

        if action == "set_main_pin":
            self.set_user_pinned(bool(payload.get("pinned", True)))
            response["mainPinned"] = bool(self._user_pinned)
            response["effectiveTopMost"] = bool(self.effective_topmost)
            response["captureSafetyOverride"] = bool(self._capture_safety_override)

        if action == "delete_history_record":
            record_id = payload.get("recordId")
            source = payload.get("source") or ("legacy" if str(record_id).startswith("legacy:") else "current")
            if self._delete_history_provider is not None:
                try:
                    try:
                        delete_result = self._delete_history_provider(record_id, source=source)
                    except TypeError:
                        delete_result = self._delete_history_provider(record_id)
                except Exception as exc:
                    delete_result = {"ok": False, "status": "ERROR", "message": str(exc)}
            else:
                delete_result = {"ok": False, "status": "NO_PROVIDER", "message": "删除服务未就绪"}
            response["deleteResult"] = delete_result
            if delete_result.get("ok") and (delete_result.get("isLegacy") or source == "legacy"):
                archive = self._legacy_archive_provider() if self._legacy_archive_provider is not None else None
                if archive is not None:
                    try:
                        service = self._settlement_review_service
                        if service is not None and hasattr(service, "legacy_archive_list"):
                            records = service.legacy_archive_list()
                        else:
                            records = archive.list_projections()
                        response["legacyArchive"] = {
                            "ok": True,
                            "source": archive.source_info(),
                            "records": records,
                        }
                    except Exception:
                        pass

        if action == "delete_history_records":
            selections = payload.get("selections")
            if not isinstance(selections, list):
                raw_ids = payload.get("recordIds")
                raw_ids = raw_ids if isinstance(raw_ids, list) else []
                selections = [
                    {
                        "recordId": record_id,
                        "source": "legacy" if str(record_id).startswith("legacy:") else "current",
                    }
                    for record_id in raw_ids
                ]
            if self._delete_history_records_provider is not None:
                try:
                    delete_batch_result = self._delete_history_records_provider(selections)
                except Exception as exc:
                    delete_batch_result = {"ok": False, "status": "ERROR", "message": str(exc)}
            elif self._delete_history_provider is not None:
                # Focused hosts may only provide the existing single-record authority.
                deleted = []
                failed = []
                for selection in selections:
                    record_id = selection.get("recordId") if isinstance(selection, dict) else selection
                    source = selection.get("source") if isinstance(selection, dict) else None
                    try:
                        result = self._delete_history_provider(record_id, source=source)
                    except TypeError:
                        result = self._delete_history_provider(record_id)
                    if isinstance(result, dict) and result.get("ok"):
                        deleted.append(str(record_id))
                    else:
                        failed.append(result if isinstance(result, dict) else {"message": "删除失败"})
                delete_batch_result = {
                    "ok": bool(deleted) and not failed,
                    "status": "DELETED" if deleted and not failed else ("PARTIAL" if deleted else "ERROR"),
                    "deletedCount": len(deleted),
                    "deletedRecordIds": deleted,
                    "failedRecords": failed,
                    "message": f"已删除 {len(deleted)} 条对局记录。" if not failed else "部分记录未删除。",
                }
            else:
                delete_batch_result = {"ok": False, "status": "NO_PROVIDER", "message": "删除服务未就绪"}
            response["deleteBatchResult"] = delete_batch_result
            if delete_batch_result.get("ok") and delete_batch_result.get("legacyDeleted"):
                archive = self._legacy_archive_provider() if self._legacy_archive_provider is not None else None
                if archive is not None:
                    try:
                        service = self._settlement_review_service
                        records = (
                            service.legacy_archive_list()
                            if service is not None and hasattr(service, "legacy_archive_list")
                            else archive.list_projections()
                        )
                        response["legacyArchive"] = {
                            "ok": True,
                            "source": archive.source_info(),
                            "records": records,
                        }
                    except Exception:
                        pass

        if action == "request_legacy_archive":
            archive = self._legacy_archive_provider() if self._legacy_archive_provider is not None else None
            if archive is None:
                response["legacyArchive"] = {"ok": False, "status": "NO_LEGACY_ARCHIVE", "message": "Legacy 归档未就绪"}
            else:
                try:
                    service = self._settlement_review_service
                    if service is not None and hasattr(service, "legacy_archive_list"):
                        records = service.legacy_archive_list()
                    else:
                        records = archive.list_projections()
                    response["legacyArchive"] = {
                        "ok": True,
                        "source": archive.source_info(),
                        "records": records,
                    }
                except Exception as exc:
                    response["legacyArchive"] = {"ok": False, "status": "ERROR", "message": str(exc)}

        if action == "request_original_screenshots":
            service = self._settlement_review_service
            response["originalScreenshots"] = service.list_original_screenshots(
                str(payload.get("recordId") or "").strip()
            ) if service else {"ok": False, "message": "截图服务未就绪"}

        if action in ("delete_original_screenshot", "restore_original_screenshot"):
            service = self._settlement_review_service
            response["originalScreenshots"] = service.remove_original_screenshot(
                str(payload.get("recordId") or "").strip(),
                str(payload.get("evidenceId") or "").strip(),
                restore=action == "restore_original_screenshot",
            ) if service else {"ok": False, "message": "截图服务未就绪"}

        if action in (
            "request_settlement_review",
            "import_settlement_screenshot",
            "replace_settlement_screenshot",
            "delete_settlement_screenshot",
            "rerun_settlement_recognition",
            "save_settlement_review",
        ):
            service = self._settlement_review_service
            source = str(payload.get("source") or "current").strip()
            if service is None:
                response["settlementReview"] = {
                    "ok": False,
                    "status": "NO_REVIEW_SERVICE",
                    "message": "结算审阅服务未就绪",
                }
            else:
                try:
                    if action == "request_settlement_review":
                        result = service.create_review_session(
                            str(payload.get("recordId") or "").strip(), source=source
                        )
                    elif action in ("import_settlement_screenshot", "replace_settlement_screenshot"):
                        result = service.import_screenshot(
                            str(payload.get("recordId") or "").strip(),
                            str(payload.get("sourcePath") or "").strip(),
                            source=source,
                        )
                    elif action == "delete_settlement_screenshot":
                        result = service.delete_imported_screenshot(
                            str(payload.get("recordId") or "").strip(),
                            source=source,
                        )
                    elif action == "rerun_settlement_recognition":
                        result = service.rerun_recognition(
                            str(payload.get("recordId") or "").strip(),
                            source=source,
                        )
                    else:  # save_settlement_review
                        record_id = str(payload.get("recordId") or "").strip()
                        runtime_originals = None
                        if source != "legacy":
                            try:
                                from settlement_review_file_originals import lookup_runtime_file_originals
                                from runtime_data import runtime_data_paths

                                runtime_originals = lookup_runtime_file_originals(
                                    record_id, runtime_data_paths().root
                                )
                            except Exception:
                                runtime_originals = []
                        result = service.save_reviewed_settlement(
                            record_id,
                            payload.get("reviewedItems") or [],
                            payload.get("reviewMeta"),
                            source=source,
                            runtime_file_originals=runtime_originals,
                            identity_review=payload.get("identityReview"),
                        )
                except Exception as exc:
                    result = {"ok": False, "status": "ERROR", "message": str(exc)}
                response["settlementReview"] = self._with_identity_summary(
                    result,
                    str(payload.get("recordId") or "").strip(),
                    source,
                )

        if action == "settlement_item_review_action":
            service = self._settlement_review_service
            if service is None:
                response["settlementItemReview"] = {
                    "ok": False,
                    "status": "NO_REVIEW_SERVICE",
                    "message": "结算审阅服务未就绪",
                }
            else:
                try:
                    record_id = str(payload.get("recordId") or "").strip()
                    source = str(payload.get("source") or "current").strip()
                    result = service.apply_item_review_action(record_id, payload, source=source)
                except Exception as exc:
                    result = {"ok": False, "status": "ERROR", "message": str(exc)}
                response["settlementItemReview"] = result

        if action == "manual_facts":
            if self._manual_facts_provider is not None:
                try:
                    envelope_keys = (
                        "clearedFields",
                        "restoreAutoFields",
                        "intent",
                        "predictionSnapshot",
                        "frozenPrediction",
                    )
                    if any(key in payload for key in envelope_keys):
                        facts_payload = {
                            key: payload[key]
                            for key in ("facts",) + envelope_keys
                            if key in payload
                        }
                    else:
                        facts_payload = payload.get("facts") if "facts" in payload else payload
                    self._manual_facts_provider(facts_payload)
                    response["manualFactsResult"] = {"ok": True}
                except Exception as exc:
                    response["manualFactsResult"] = {"ok": False, "error": str(exc)}
            else:
                response["manualFactsResult"] = {"ok": False, "error": "NO_MANUAL_FACTS_PROVIDER"}

        if action == "manual_next_match":
            if self._manual_next_match_provider is not None:
                try:
                    res = self._manual_next_match_provider(payload)
                    response["manualNextMatchResult"] = res
                except Exception as exc:
                    response["manualNextMatchResult"] = {"ok": False, "error": str(exc)}
            else:
                response["manualNextMatchResult"] = {"ok": False, "error": "NO_MANUAL_NEXT_MATCH_PROVIDER"}

        if action == "manual_finalize":
            if self._manual_finalize_provider is not None:
                try:
                    res = self._manual_finalize_provider(payload)
                    response["manualFinalizeResult"] = res
                except Exception as exc:
                    response["manualFinalizeResult"] = {"ok": False, "error": str(exc)}
            else:
                response["manualFinalizeResult"] = {"ok": False, "error": "NO_MANUAL_FINALIZE_PROVIDER"}

        if action == "manual_bootstrap":
            if self._manual_bootstrap_provider is not None:
                try:
                    res = self._manual_bootstrap_provider()
                    response["manualBootstrapResult"] = res
                except Exception as exc:
                    response["manualBootstrapResult"] = {"ok": False, "error": str(exc)}
            else:
                response["manualBootstrapResult"] = {"ok": False, "error": "NO_MANUAL_BOOTSTRAP_PROVIDER"}

        if action == 'start_live_vision':
            try:
                response['visionStartResult'] = {'ok': bool(self._start_vision_provider and self._start_vision_provider())}
            except Exception as exc:
                response['visionStartResult'] = {'ok': False, 'error': str(exc)}

        if action in ("start_warehouse_capture", "prepare_warehouse_capture"):
            host = self._warehouse_capture_host
            if host is None:
                response["warehouseCaptureCommand"] = {
                    "ok": False,
                    "reason": "SCROLL_DRIVER_NOT_CONFIGURED",
                    "armingToken": None,
                }
            else:
                prep_result = host.prepare() if hasattr(host, "prepare") else host.start()
                response["warehouseCaptureCommand"] = prep_result
            response["warehouseCapture"] = self.warehouse_capture_payload()
            response["effectiveTopMost"] = bool(self.effective_topmost)
            response["captureSafetyOverride"] = bool(self._capture_safety_override)

        if action == "confirm_warehouse_capture":
            # 二次确认成功、进入 WAITING_FOR_GAME_FOCUS 之前，必须先设置 override 并取消置顶
            self.set_capture_safety_override(True)
            host = self._warehouse_capture_host
            token_id = str(payload.get("armingToken") or "")
            if host is None:
                response["warehouseCaptureCommand"] = {
                    "ok": False,
                    "reason": "SCROLL_DRIVER_NOT_CONFIGURED",
                }
            else:
                response["warehouseCaptureCommand"] = host.confirm(token_id)
            response["warehouseCapture"] = self.warehouse_capture_payload()
            response["effectiveTopMost"] = bool(self.effective_topmost)
            response["captureSafetyOverride"] = bool(self._capture_safety_override)

        if action == "stop_warehouse_capture":
            self.set_capture_safety_override(False)
            host = self._warehouse_capture_host
            if host is None:
                response["warehouseCaptureCommand"] = {"ok": True, "reason": "NO_SESSION"}
            else:
                response["warehouseCaptureCommand"] = host.stop()
            response["warehouseCapture"] = self.warehouse_capture_payload()
            response["effectiveTopMost"] = bool(self.effective_topmost)
            response["captureSafetyOverride"] = bool(self._capture_safety_override)

        if action in ("prepare_warehouse_manual_takeover", "start_warehouse_manual_takeover"):
            host = self._warehouse_capture_host
            if host is None:
                response["warehouseCaptureCommand"] = {"ok": False, "reason": "NO_HOST"}
            elif action == "prepare_warehouse_manual_takeover":
                response["warehouseCaptureCommand"] = host.prepare_manual() if hasattr(host, "prepare_manual") else {"ok": False}
            else:
                response["warehouseCaptureCommand"] = host.start_manual() if hasattr(host, "start_manual") else {"ok": False}
            response["warehouseCapture"] = self.warehouse_capture_payload()

        if action == "capture_warehouse_manual_page":
            host = self._warehouse_capture_host
            if host is None:
                response["warehouseCaptureCommand"] = {"ok": False, "reason": "NO_HOST"}
            else:
                response["warehouseCaptureCommand"] = host.capture_manual_page() if hasattr(host, "capture_manual_page") else {"ok": False}
            response["warehouseCapture"] = self.warehouse_capture_payload()

        if action == "finish_warehouse_manual_capture":
            host = self._warehouse_capture_host
            if host is None:
                response["warehouseCaptureCommand"] = {"ok": False, "reason": "NO_HOST"}
            else:
                response["warehouseCaptureCommand"] = host.finish_manual_capture() if hasattr(host, "finish_manual_capture") else {"ok": False}
            response["warehouseCapture"] = self.warehouse_capture_payload()

        if action == "cancel_warehouse_manual_capture":
            host = self._warehouse_capture_host
            if host is None:
                response["warehouseCaptureCommand"] = {"ok": True}
            else:
                response["warehouseCaptureCommand"] = host.cancel_manual_capture() if hasattr(host, "cancel_manual_capture") else {"ok": True}
            response["warehouseCapture"] = self.warehouse_capture_payload()

        if action == "warehouse_identity_review":
            session = self._warehouse_identity_review_session
            if session is None:
                response["warehouseIdentityReview"] = {"available": False}
            else:
                try:
                    safe = {
                        key: payload[key]
                        for key in self.REVIEW_CLIENT_KEYS
                        if key in payload
                    }
                    op = str(safe.get("op") or "view")
                    if op == "persist":
                        response["warehouseIdentityReview"] = self._persist_warehouse_identity_review(
                            session,
                            str(safe.get("sessionId") or ""),
                            str(safe.get("packetFingerprint") or ""),
                        )
                    elif op == "open":
                        host = self._warehouse_capture_host
                        requested_record = str(safe.get("recordId") or "").strip()
                        history = self._warehouse_identity_review_history_store
                        historical = history.lookup(requested_record) if requested_record and history is not None else None
                        packet = (
                            host.review_packet_copy()
                            if host is not None and hasattr(host, "review_packet_copy")
                            else None
                        )
                        if requested_record:
                            packet = ((historical or {}).get("settlement") or {}).get("warehouseReviewPacket")
                            if not packet:
                                raise ValueError("这条记录没有保存可继续审阅的证据包")
                        saved_artifact = None
                        history = self._warehouse_identity_review_history_store
                        if packet and history is not None:
                            saved = history.lookup(packet.get("recordStableKey"))
                            candidate = ((saved or {}).get("settlement") or {}).get("warehouseIdentityReview")
                            if candidate and candidate.get("packetFingerprint") == packet.get("sourceFingerprint"):
                                saved_artifact = candidate
                        response["warehouseIdentityReview"] = self._decorate_identity_review(
                            session, session.open(packet, saved_artifact=saved_artifact))
                    else:
                        response["warehouseIdentityReview"] = self._decorate_identity_review(session, session.dispatch(safe))
                except Exception as exc:
                    code = getattr(exc, "code", None) or "ERROR"
                    view = {"available": False, "message": str(code)}
                    try:
                        current = session.view()
                        if isinstance(current, dict):
                            view = self._decorate_identity_review(session, current)
                            view["message"] = str(code)
                    except Exception:
                        pass
                    response["warehouseIdentityReview"] = view

        if action == "triggered_snapshot":
            if self._triggered_snapshot_provider is not None:
                try:
                    response["snapshotResult"] = self._triggered_snapshot_provider()
                except Exception as exc:
                    response["snapshotResult"] = {
                        "ok": False,
                        "summary": str(exc),
                    }
            else:
                response["snapshotResult"] = {
                    "ok": False,
                    "summary": "NO_TRIGGERED_SNAPSHOT_PROVIDER",
                }

        if action == "save_settlement_screenshot":
            if self._save_settlement_screenshot_provider is not None:
                try:
                    response["settlementScreenshot"] = self._save_settlement_screenshot_provider()
                except Exception as exc:
                    response["settlementScreenshot"] = {
                        "ok": False,
                        "status": "ERROR",
                        "message": f"保存结算原图失败：{exc}",
                    }
            else:
                response["settlementScreenshot"] = {
                    "ok": False,
                    "status": "NO_SETTLEMENT_SCREENSHOT_PROVIDER",
                    "message": "结算截图入口未就绪。",
                }

        if action == "save_game_screenshot":
            if self._save_game_screenshot_provider is not None:
                try:
                    response["gameScreenshot"] = self._save_game_screenshot_provider()
                except Exception as exc:
                    response["gameScreenshot"] = {
                        "ok": False,
                        "status": "ERROR",
                        "message": f"保存异环截图失败：{exc}",
                    }
            else:
                response["gameScreenshot"] = {
                    "ok": False,
                    "status": "NO_GAME_SCREENSHOT_PROVIDER",
                    "message": "手动截图入口未就绪。",
                }

        if action == "export_reviewed_labels":
            try:
                from runtime_data import runtime_data_paths
                from warehouse_reviewed_label_export import export_reviewed_label_bundle
                response["labelsExportResult"] = export_reviewed_label_bundle(
                    runtime_root=runtime_data_paths().root, output_path=payload.get("outputPath") or "")
            except Exception as exc:
                code = getattr(exc, "code", None)
                message = {"ZIP_REQUIRED": "请选择以 .zip 结尾的样本包文件。",
                           "HISTORY_MISSING": "没有可导出的历史记录，请先保存一局记录。"}.get(code)
                if message is None:
                    message = "无法保存样本包，请检查保存位置是否可写、文件是否被占用后重试。" if isinstance(exc, OSError) else "样本导出失败，请检查记录和原图是否完整后重试。"
                response["labelsExportResult"] = {"ok": False, "status": "ERROR", "message": message}

        if action == "export_history_records":
            try:
                from datetime import datetime, timezone
                from pathlib import Path
                from canonical_history_store import CanonicalHistoryStore
                from runtime_data import resolve_runtime_history_path, runtime_data_paths

                if callable(self._history_path_provider):
                    h_path = self._history_path_provider()
                elif self._history_path_provider is not None:
                    h_path = self._history_path_provider
                else:
                    h_path = resolve_runtime_history_path()

                store = CanonicalHistoryStore(h_path)
                db_data = store.read_database()
                records = db_data.get("records") or []

                output_path = payload.get("outputPath")
                selected_ids = payload.get("recordIds")
                if isinstance(selected_ids, str):
                    selected_ids = [selected_ids]
                if not isinstance(selected_ids, list):
                    selected_ids = []

                if output_path and str(output_path).lower().endswith(".zip"):
                    from match_export_bundle import MatchExportError, export_match_bundle

                    paths = runtime_data_paths()
                    response["exportResult"] = export_match_bundle(
                        history_path=h_path,
                        data_root=paths.root,
                        output_path=output_path,
                        record_ids=selected_ids,
                    )
                    response["exportResult"]["selected"] = bool(selected_ids)
                else:
                    # Keep the old JSON lane for scripts and existing users;
                    # the UI now chooses the self-contained ZIP lane.
                    export_payload = {
                        "schemaVersion": "history-export.v1",
                        "exportedAt": datetime.now(timezone.utc).isoformat(),
                        "recordCount": len(records),
                        "records": records,
                    }

                    if output_path:
                        out_p = Path(output_path).resolve()
                        out_p.parent.mkdir(parents=True, exist_ok=True)
                        with open(out_p, "w", encoding="utf-8") as f:
                            json.dump(export_payload, f, ensure_ascii=False, indent=2)
                        response["exportResult"] = {
                            "ok": True,
                            "status": "SAVED",
                            "outputPath": str(out_p),
                            "recordCount": len(records),
                            "exportedAt": export_payload["exportedAt"],
                            "bundleType": "json-compatibility",
                        }
                    else:
                        response["exportResult"] = {
                            "ok": True,
                            "status": "READY",
                            "data": export_payload,
                            "recordCount": len(records),
                            "exportedAt": export_payload["exportedAt"],
                        }
            except Exception as exc:
                response["exportResult"] = {
                    "ok": False,
                    "status": "ERROR",
                    "message": f"导出失败：{exc}",
                }

        if action == "import_history_bundle":
            try:
                from canonical_history_store import CanonicalHistoryStore
                from match_import_bundle import MatchImportError, import_match_bundle
                from runtime_data import resolve_runtime_history_path, runtime_data_paths

                if callable(self._history_path_provider):
                    h_path = self._history_path_provider()
                elif self._history_path_provider is not None:
                    h_path = self._history_path_provider
                else:
                    h_path = resolve_runtime_history_path()
                input_path = str(payload.get("inputPath") or "").strip()
                if not input_path:
                    raise MatchImportError("未选择对局数据包")
                result = import_match_bundle(
                    history_path=h_path,
                    data_root=runtime_data_paths().root,
                    input_path=input_path,
                )
                response["importResult"] = result
            except Exception as exc:
                response["importResult"] = {
                    "ok": False,
                    "status": "ERROR",
                    "message": f"导入失败：{exc}",
                }

        main_view_state = self.main_view_state_payload()
        if main_view_state is not None:
            response["mainViewState"] = main_view_state
        mascot_state = self.mascot_state_payload("ready")
        if mascot_state is not None:
            response["mascotState"] = mascot_state
        current_match = self.current_match_payload()
        if current_match is not None:
            response["currentMatch"] = current_match
        return response

    def snapshot_completion_payload(self, snapshot_result: dict) -> dict:
        """Construct narrow presentation payload for async snapshot completion."""
        payload = {
            "type": "app_status",
            "action": "triggered_snapshot",
            "overlayVisible": bool(self._overlay_controller.visible if self._overlay_controller else False),
            "applicationState": "ready",
            "solverOwner": "overlay_runtime",
            "snapshotResult": dict(snapshot_result or {}),
        }
        main_view_state = self.main_view_state_payload()
        if main_view_state is not None:
            payload["mainViewState"] = main_view_state
        mascot_state = self.mascot_state_payload("ready")
        if mascot_state is not None:
            payload["mascotState"] = mascot_state
        current_match = self.current_match_payload()
        if current_match is not None:
            payload["currentMatch"] = current_match
        return payload


def _enable_dark_title_bar(hwnd: int) -> None:
    """Ask DWM for a dark native frame; unsupported Windows builds simply ignore it."""
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
            )
            if result == 0:
                break
    except Exception:
        pass


def create_main_window_type(WinForms, Drawing):
    """Create the native lifetime-owner Form after CLR assemblies are loaded."""
    try:
        from NTE.DirectComposition import DirectCompositionMainForm
        BaseForm = DirectCompositionMainForm
    except Exception:
        BaseForm = WinForms.Form

    class MainWindow(BaseForm):
        def __init__(self):
            self._overlay_controller = None
            self._bridge = None
            self._shutdown_request = None
            self._accepting_commands = False
            self._overlay_visible = False
            self._presentation_controller = None
            self._presentation_webview = None
            self._web_message_handler = None
            self._navigation_handler = None
            self._presentation_closed = False
            self._mascot_presentation = None
            self._desktop_pet_controller = None
            self._desktop_pet_menu_installed = False
            self._logger = None
            self._loading_label = None
            self._current_topmost = True
            self._settlement_review_queue_lock = threading.Lock()
            self._settlement_review_pending = None
            self._settlement_review_worker_active = False
            self._settlement_review_generation = 0
            self._dcomp_device = None
            self._dcomp_target = None
            self._dcomp_root_visual = None
            self._is_composition_host = False

            BaseForm.__init__(self)

            self.Text = "异环拍卖助手"
            self.StartPosition = WinForms.FormStartPosition.CenterScreen
            self.ClientSize = Drawing.Size(1280, 660)
            self.MinimumSize = Drawing.Size(1100, 680)
            self.BackColor = Drawing.Color.FromArgb(15, 17, 19)
            self._current_topmost = True
            self.TopMost = True

            ico_candidates = [
                os.path.join(os.path.dirname(__file__), "app_icon.ico"),
                os.path.join(os.path.dirname(__file__), "..", "assets", "app_icon.ico"),
                os.path.join(os.path.dirname(__file__), "assets", "app_icon.ico"),
                os.path.join(os.path.dirname(__file__), "..", "app_icon.ico"),
            ]
            for p in ico_candidates:
                if os.path.isfile(p):
                    try:
                        self.Icon = Drawing.Icon(os.path.abspath(p))
                        break
                    except Exception:
                        pass

            self._loading_label = WinForms.Label()
            self._loading_label.Text = "正在载入异环拍卖助手…"
            self._loading_label.ForeColor = Drawing.Color.FromArgb(151, 160, 155)
            self._loading_label.AutoSize = True
            self._loading_label.Location = Drawing.Point(28, 28)
            self.Controls.Add(self._loading_label)

            self.Resize += self._on_resize
            self.FormClosing += self._on_form_closing

        def set_topmost(self, enable: bool) -> None:
            """Explicit, idempotent TopMost control using SWP_NOACTIVATE."""
            enable = bool(enable)
            if self._current_topmost == enable:
                return
            self._current_topmost = enable
            if hasattr(self, "SetTopMostNoActivate"):
                try:
                    self.SetTopMostNoActivate(enable)
                except Exception:
                    pass
            else:
                self.TopMost = enable
                try:
                    handle = int(self.Handle.ToInt64())
                    user32 = ctypes.windll.user32
                    user32.SetWindowPos.argtypes = [
                        ctypes.c_void_p,
                        ctypes.c_void_p,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_uint,
                    ]
                    insert_after = (
                        ctypes.c_void_p(-1).value if enable else ctypes.c_void_p(-2).value
                    )
                    # SWP_NOSIZE (0x0001) | SWP_NOMOVE (0x0002) | SWP_NOACTIVATE (0x0010) = 0x0013
                    user32.SetWindowPos(
                        handle, insert_after, 0, 0, 0, 0, 0x0013
                    )
                except Exception:
                    pass

        def bind_lifecycle(
            self,
            overlay_controller,
            shutdown_request,
            presentation_runtime_provider=None,
            main_view_state_provider=None,
            mascot_state_provider=None,
            current_match_provider=None,
            delete_history_provider=None,
            delete_history_records_provider=None,
            settlement_review_service=None,
            legacy_archive_provider=None,
            manual_facts_provider=None,
            manual_next_match_provider=None,
            manual_finalize_provider=None,
            manual_bootstrap_provider=None,
            start_vision_provider=None,
            triggered_snapshot_provider=None,
            save_settlement_screenshot_provider=None,
            save_game_screenshot_provider=None,
            warehouse_capture_host=None,
            warehouse_identity_review_session=None,
            warehouse_identity_review_history_store=None,
            history_path_provider=None,
        ) -> None:
            self._overlay_controller = overlay_controller
            self._bridge = MainWindowBridge(
                overlay_controller,
                presentation_runtime_provider,
                main_view_state_provider,
                mascot_state_provider,
                current_match_provider,
                delete_history_provider,
                delete_history_records_provider,
                settlement_review_service,
                legacy_archive_provider,
                manual_facts_provider=manual_facts_provider,
                manual_next_match_provider=manual_next_match_provider,
                manual_finalize_provider=manual_finalize_provider,
                manual_bootstrap_provider=manual_bootstrap_provider,
                start_vision_provider=start_vision_provider,
                triggered_snapshot_provider=triggered_snapshot_provider,
                save_settlement_screenshot_provider=save_settlement_screenshot_provider,
                save_game_screenshot_provider=save_game_screenshot_provider,
                warehouse_capture_host=warehouse_capture_host,
                warehouse_identity_review_session=warehouse_identity_review_session,
                warehouse_identity_review_history_store=warehouse_identity_review_history_store,
                history_path_provider=history_path_provider,
                topmost_controller=self.set_topmost,
            )
            self._shutdown_request = shutdown_request
            self._accepting_commands = True
            self.set_topmost(self._bridge.effective_topmost)
            self.set_overlay_visible(overlay_controller.visible)

        def bind_desktop_pet(self, desktop_pet_controller) -> None:
            """Bind one native Pet without expanding the WebView bridge surface."""
            if (
                self._desktop_pet_controller is not None
                and self._desktop_pet_controller is not desktop_pet_controller
            ):
                raise RuntimeError("Main Window already owns a Desktop Pet controller")
            self._desktop_pet_controller = desktop_pet_controller
            desktop_pet_controller.install_main_window_menu()
            self._desktop_pet_menu_installed = True

        @property
        def presentation_ready(self) -> bool:
            return self._presentation_webview is not None

        @property
        def presentation_identity(self):
            return id(self._presentation_webview) if self._presentation_webview else None

        @property
        def WebView(self):
            return self._presentation_webview

        @property
        def CompController(self):
            return self._presentation_controller

        def initialize_presentation(
            self,
            environment,
            html_path: str,
            logger=None,
            smoke_mode: bool = False,
            mascot_presentation=None,
        ) -> None:
            """Attach one windowed presentation controller to this native Form."""
            if self._presentation_webview is not None:
                raise RuntimeError("Main presentation is already initialized")
            resolved_html = Path(html_path).resolve()
            if not resolved_html.is_file():
                raise FileNotFoundError(resolved_html)
            self._mascot_presentation = (
                mascot_presentation
                if mascot_presentation is not None
                else load_mascot_presentation_contract(resolved_html.parent.parent)
            )

            self._logger = logger
            _enable_dark_title_bar(int(self.Handle.ToInt64()))

            try:
                from Microsoft.Web.WebView2.WinForms import WebView2
            except Exception:
                import clr
                import webview
                from webview.util import interop_dll_path
                clr.AddReference(interop_dll_path('Microsoft.Web.WebView2.WinForms.dll'))
                from Microsoft.Web.WebView2.WinForms import WebView2

            if not self.IsHandleCreated:
                self.CreateControl()
            WinForms.Application.DoEvents()

            controller_task = environment.CreateCoreWebView2ControllerAsync(self.Handle)
            while not controller_task.IsCompleted:
                WinForms.Application.DoEvents()
            if controller_task.IsFaulted:
                # 待验证假设 (Unverified Hypothesis): 0x80070578: ERROR_INVALID_WINDOW_HANDLE
                # 假设系统在特定桌面会话/隔离/测试环境下阻止标准窗口句柄向 WebView2 传递。
                # 在该场景下激活 DirectComposition 兜底宿主。
                err_str = str(controller_task.Exception)
                if hasattr(environment, "CreateCoreWebView2CompositionControllerAsync") and (
                    "0x80070578" in err_str
                    or "0x80070057" in err_str
                    or "无效的窗口句柄" in err_str
                    or "预期的范围" in err_str
                ):
                    self._log(
                        "STARTUP:MAIN",
                        "Standard windowed HWND attachment failed (0x80070578; 待验证假设: 隔离环境窗口句柄限制); engaging fully-composed DirectComposition host fallback",
                    )
                    try:
                        from NTE.DirectComposition import DCompNative
                        self._dcomp_device = DCompNative.CreateDevice()
                        hr_t, target = self._dcomp_device.CreateTargetForHwnd(self.Handle, True)
                        if hr_t == 0 and target is not None:
                            self._dcomp_target = target
                            hr_v, root_visual = self._dcomp_device.CreateVisual()
                            if hr_v == 0 and root_visual is not None:
                                self._dcomp_root_visual = root_visual
                                self._dcomp_target.SetRoot(self._dcomp_root_visual)
                    except Exception as dcomp_err:
                        self._log("STARTUP:MAIN", f"DirectComposition visual tree initialization error: {dcomp_err}")

                    if self._dcomp_root_visual is None:
                        raise RuntimeError(
                            "DirectComposition visual tree creation failed: root visual target could not be established"
                        )

                    controller_task = environment.CreateCoreWebView2CompositionControllerAsync(self.Handle)
                    while not controller_task.IsCompleted:
                        WinForms.Application.DoEvents()
                    self._is_composition_host = True

                if controller_task.IsFaulted:
                    raise RuntimeError(
                        "Main CoreWebView2Controller initialization failed: "
                        f"{controller_task.Exception}"
                    )

            self._presentation_controller = controller_task.Result
            if self._presentation_controller is None:
                raise RuntimeError("Main CoreWebView2Controller initialization returned null controller")
            self._presentation_webview = self._presentation_controller.CoreWebView2
            if self._presentation_webview is None:
                raise RuntimeError("Main CoreWebView2 initialization returned null webview")

            if self._is_composition_host and self._dcomp_root_visual is not None:
                try:
                    self._presentation_controller.RootVisualTarget = self._dcomp_root_visual
                    using_graphics = Drawing.Graphics.FromHwnd(self.Handle)
                    self._presentation_controller.RasterizationScale = float(using_graphics.DpiX / 96.0)
                    using_graphics.Dispose()
                except Exception:
                    pass

            self._presentation_controller.Bounds = Drawing.Rectangle(
                0, 0, self.ClientSize.Width, self.ClientSize.Height
            )
            self._presentation_controller.IsVisible = True
            if self._dcomp_device is not None:
                try:
                    self._dcomp_device.Commit()
                except Exception:
                    pass

            settings = self._presentation_webview.Settings
            settings.IsScriptEnabled = True
            settings.IsWebMessageEnabled = True
            settings.AreDevToolsEnabled = False
            for setting_name, value in (
                ("AreDefaultContextMenusEnabled", False),
                ("IsStatusBarEnabled", False),
                ("IsZoomControlEnabled", False),
            ):
                try:
                    setattr(settings, setting_name, value)
                except Exception:
                    pass

            def on_web_message(sender, event):
                self._handle_web_message(event.TryGetWebMessageAsString())

            def on_navigation_completed(sender, event):
                if event.IsSuccess:
                    self._log("STARTUP:MAIN", "Main presentation page ready")
                    self._post_status("navigation_completed")
                else:
                    self._log(
                        "STARTUP:MAIN",
                        f"Main presentation navigation failed: {event.WebErrorStatus}",
                    )

            self._web_message_handler = on_web_message
            self._navigation_handler = on_navigation_completed
            self._presentation_webview.WebMessageReceived += self._web_message_handler
            self._presentation_webview.NavigationCompleted += self._navigation_handler
            navigation_uri = resolved_html.as_uri()
            if smoke_mode:
                navigation_uri += "?smoke=overlay-toggle"
            self._presentation_webview.Navigate(navigation_uri)
            self._loading_label.Visible = False
            self._log("STARTUP:MAIN", f"Main presentation WebView initialized: {resolved_html}")

        def execute_script(self, script: str):
            """QA-only: run script in the main presentation WebView on the UI thread."""
            if getattr(self, "InvokeRequired", False):
                holder = {"value": None, "error": None}
                event = threading.Event()

                def _dispatch():
                    try:
                        holder["value"] = self.execute_script(script)
                    except Exception as exc:
                        holder["error"] = exc
                    finally:
                        event.set()

                try:
                    from System import Action
                    self.BeginInvoke(Action(_dispatch))
                except Exception:
                    _dispatch()
                if not event.wait(12):
                    raise TimeoutError("MAIN_WEBVIEW_SCRIPT_DISPATCH_TIMEOUT")
                if holder["error"] is not None:
                    raise holder["error"]
                return holder["value"]
            webview = self._presentation_webview
            if webview is None:
                return None
            task = webview.ExecuteScriptAsync(str(script or ""))
            deadline = time.monotonic() + 10
            while not task.IsCompleted:
                if time.monotonic() >= deadline:
                    raise TimeoutError("MAIN_WEBVIEW_SCRIPT_TIMEOUT")
                WinForms.Application.DoEvents()
                time.sleep(0.001)
            if task.IsFaulted:
                raise task.Exception
            return task.Result

        def set_overlay_visible(self, visible: bool) -> None:
            self._overlay_visible = bool(visible)
            self._post_status("overlay_visibility_changed")

        def begin_shutdown(self) -> None:
            self._accepting_commands = False
            self.set_topmost(False)
            self._post_status("shutdown_started", application_state="shutting_down")

        def close_presentation_resources(self) -> None:
            if self._presentation_closed:
                return
            self._presentation_closed = True
            self._accepting_commands = False
            self.set_topmost(False)
            webview = self._presentation_webview
            if webview is not None:
                try:
                    if self._web_message_handler is not None:
                        webview.WebMessageReceived -= self._web_message_handler
                    if self._navigation_handler is not None:
                        webview.NavigationCompleted -= self._navigation_handler
                except Exception:
                    pass
            controller = self._presentation_controller
            if controller is not None:
                try:
                    if hasattr(controller, "Close"):
                        controller.Close()
                    elif hasattr(controller, "Dispose"):
                        controller.Dispose()
                except Exception:
                    pass
            self._presentation_webview = None
            self._presentation_controller = None
            self._web_message_handler = None
            self._navigation_handler = None

        def _handle_web_message(self, message: str) -> None:
            if not self._accepting_commands or self._bridge is None:
                return
            try:
                import json as _json

                payload = _json.loads(message)
                action = payload.get("action")
                if action == "request_settlement_review":
                    self._queue_settlement_review_request(message, payload)
                    return
                needs_dialog = (
                    action == "export_reviewed_labels"
                    or
                    (
                        action in ("import_settlement_screenshot", "replace_settlement_screenshot")
                        and not str(payload.get("sourcePath") or "").strip()
                    )
                    or (
                        action == "import_history_bundle"
                        and not str(payload.get("inputPath") or "").strip()
                    )
                    or action == "select_legacy_archive_source"
                    or (
                        action == "export_history_records"
                        and not str(payload.get("outputPath") or "").strip()
                    )
                )
                if needs_dialog:
                    self._open_file_dialog(action, payload)
                    return

                response = self._bridge.dispatch(message)
                self._overlay_visible = bool(response["overlayVisible"])
                response["mascotPresentation"] = self._mascot_presentation
                cmd = response.get("warehouseCaptureCommand")
                extra = ""
                if isinstance(cmd, dict):
                    extra = f" capture={cmd.get('ok')} reason={cmd.get('reason')}"
                self._log(
                    "ACTION:MAIN",
                    f"Main bridge action={response['action']} "
                    f"overlayVisible={response['overlayVisible']}{extra}",
                )
                self._post_json(response)
            except Exception as exc:
                self._log("ACTION:MAIN", f"Main bridge rejected message: {exc}")
                try:
                    self._post_json({
                        "type": "app_status",
                        "action": (payload or {}).get("action") or "unknown",
                        "overlayVisible": bool(getattr(self, "_overlay_visible", False)),
                        "applicationState": "ready",
                        "solverOwner": "overlay_runtime",
                        "settlementReview": {
                            "ok": False,
                            "status": "BRIDGE_ERROR",
                            "message": f"操作失败：{exc}",
                        },
                    })
                except Exception:
                    pass

        def _queue_settlement_review_request(self, message: str, payload: dict) -> None:
            """Run expensive review recognition away from the WebView UI thread.

            History clicks are intentionally latest-request-wins: a rapid series
            of clicks keeps only the newest pending record and stale results are
            never published over the currently selected record.
            """
            import json as _json

            with self._settlement_review_queue_lock:
                self._settlement_review_generation += 1
                generation = self._settlement_review_generation
                self._settlement_review_pending = (message, payload, generation)
                should_start = not self._settlement_review_worker_active
                if should_start:
                    self._settlement_review_worker_active = True

            self._post_json({
                "type": "app_status",
                "action": "request_settlement_review",
                "requestId": payload.get("requestId"),
                "overlayVisible": bool(self._overlay_visible),
                "applicationState": "busy",
                "solverOwner": "overlay_runtime",
                "settlementReview": {
                    "ok": True,
                    "status": "STARTED",
                    "recordId": str(payload.get("recordId") or ""),
                    "source": str(payload.get("source") or "current"),
                },
            })

            if not should_start:
                return

            def _worker() -> None:
                finished_normally = False
                try:
                    while True:
                        with self._settlement_review_queue_lock:
                            job = self._settlement_review_pending
                            self._settlement_review_pending = None
                        if job is None:
                            with self._settlement_review_queue_lock:
                                if self._settlement_review_pending is None:
                                    self._settlement_review_worker_active = False
                                    finished_normally = True
                                    return
                                continue

                        request_message, request_payload, request_generation = job
                        try:
                            response = self._bridge.dispatch(request_message)
                            finished = response.get("settlementReview") or {
                                "ok": False,
                                "status": "NO_RESULT",
                                "message": "未返回审阅结果",
                            }
                        except Exception as exc:
                            finished = {
                                "ok": False,
                                "status": "ERROR",
                                "message": f"加载对局详情失败：{exc}",
                            }

                        with self._settlement_review_queue_lock:
                            is_latest = request_generation == self._settlement_review_generation
                            has_pending = self._settlement_review_pending is not None
                        if is_latest:
                            response_payload = {
                                "type": "app_status",
                                "action": "request_settlement_review",
                                "requestId": request_payload.get("requestId"),
                                "overlayVisible": bool(self._overlay_visible),
                                "applicationState": "ready",
                                "solverOwner": "overlay_runtime",
                                "settlementReview": finished,
                            }
                            self._post_json(response_payload)
                        if not has_pending:
                            with self._settlement_review_queue_lock:
                                if self._settlement_review_pending is None:
                                    self._settlement_review_worker_active = False
                                    finished_normally = True
                                    return
                finally:
                    if not finished_normally:
                        with self._settlement_review_queue_lock:
                            self._settlement_review_worker_active = False

            import threading
            threading.Thread(target=_worker, daemon=True, name="settlement_review_worker").start()

        def _open_file_dialog(self, action: str, payload: dict) -> None:
            """Run a native file dialog on the UI thread and respond explicitly
            (cancel/error are never silently swallowed)."""
            import json as _json

            def _run() -> None:
                result: dict
                try:
                    if action in ("import_settlement_screenshot", "replace_settlement_screenshot"):
                        dlg = WinForms.OpenFileDialog()
                        dlg.Title = "选择结算截图"
                        dlg.Filter = "图片文件 (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg"
                        if dlg.ShowDialog(self) == WinForms.DialogResult.OK:
                            payload["sourcePath"] = dlg.FileName
                            response = self._bridge.dispatch(_json.dumps(payload, ensure_ascii=False))
                            result = response.get("settlementReview") or {
                                "ok": False, "status": "NO_RESULT", "message": "未返回审阅结果",
                            }
                        else:
                            result = {"ok": False, "status": "CANCELLED", "message": "已取消选择"}
                    elif action in ("export_history_records", "export_reviewed_labels", "import_history_bundle"):
                        from datetime import datetime
                        today_str = datetime.now().strftime("%Y-%m-%d")
                        if action in ("export_history_records", "export_reviewed_labels"):
                            if payload.get("outputPath"):
                                dialog_ok = True
                            else:
                                dlg = WinForms.SaveFileDialog()
                                dlg.Title = "导出全部对局数据包（含原始图片）"
                                dlg.Filter = "对局数据包 (*.zip)|*.zip|JSON 兼容导出 (*.json)|*.json"
                                dlg.FileName = f"异环拍卖对局包_{today_str}.zip"
                                if action == "export_reviewed_labels":
                                    dlg.Title = "导出全部人工确认样本"
                                    dlg.Filter = "人工样本包 (*.zip)|*.zip"
                                    dlg.FileName = f"异环人工确认样本_{today_str}.zip"
                                dialog_ok = dlg.ShowDialog(self) == WinForms.DialogResult.OK
                                if dialog_ok:
                                    payload["outputPath"] = dlg.FileName
                        else:
                            if payload.get("inputPath"):
                                dialog_ok = True
                            else:
                                dlg = WinForms.OpenFileDialog()
                                dlg.Title = "导入对局数据包"
                                dlg.Filter = "对局数据包 (*.zip)|*.zip"
                                dialog_ok = dlg.ShowDialog(self) == WinForms.DialogResult.OK
                                if dialog_ok:
                                    payload["inputPath"] = dlg.FileName

                        if dialog_ok:
                            request_payload = dict(payload)
                            result_key = {"export_history_records": "exportResult", "export_reviewed_labels": "labelsExportResult", "import_history_bundle": "importResult"}[action]
                            path_key = "inputPath" if action == "import_history_bundle" else "outputPath"
                            started_result = {
                                "ok": True,
                                "status": "STARTED",
                                path_key: str(request_payload.get(path_key) or ""),
                            }
                            self._post_json({
                                "type": "app_status",
                                "action": action,
                                "overlayVisible": bool(self._overlay_visible),
                                "applicationState": "busy",
                                "solverOwner": "overlay_runtime",
                                result_key: started_result,
                            })

                            def _run_bundle_operation() -> None:
                                try:
                                    response = self._bridge.dispatch(
                                        _json.dumps(request_payload, ensure_ascii=False)
                                    )
                                    finished = response.get(result_key) or {
                                        "ok": False,
                                        "status": "NO_RESULT",
                                        "message": "操作未返回结果。",
                                    }
                                except Exception as exc:
                                    finished = {
                                        "ok": False,
                                        "status": "ERROR",
                                        "message": f"操作失败：{exc}",
                                    }
                                self._post_json({
                                    "type": "app_status",
                                    "action": action,
                                    "overlayVisible": bool(self._overlay_visible),
                                    "applicationState": "ready",
                                    "solverOwner": "overlay_runtime",
                                    result_key: finished,
                                })

                            threading.Thread(
                                target=_run_bundle_operation,
                                name=f"{action}-worker",
                                daemon=True,
                            ).start()
                            return
                        else:
                            result = {
                                "ok": False,
                                "status": "CANCELLED",
                                "message": "已取消保存" if action == "export_history_records" else "已取消导入",
                            }
                    else:  # select_legacy_archive_source
                        dlg = WinForms.OpenFileDialog()
                        dlg.Title = "选择旧版历史文件"
                        dlg.Filter = "JSON 文件 (*.json)|*.json"
                        if dlg.ShowDialog(self) == WinForms.DialogResult.OK:
                            archive = self._bridge._legacy_archive_provider() if self._bridge._legacy_archive_provider else None
                            if archive is None:
                                result = {"ok": False, "status": "NO_LEGACY_ARCHIVE", "message": "Legacy 归档未就绪"}
                            else:
                                archive.set_user_source(dlg.FileName)
                                service = self._bridge._settlement_review_service
                                if service is not None and hasattr(service, "legacy_archive_list"):
                                    records = service.legacy_archive_list()
                                else:
                                    records = archive.list_projections()
                                result = {
                                    "ok": True,
                                    "source": archive.source_info(),
                                    "records": records,
                                }
                        else:
                            result = {"ok": False, "status": "CANCELLED", "message": "已取消选择"}
                except Exception as exc:
                    self._log("ACTION:MAIN", f"File dialog failed action={action}: {exc}")
                    result = {"ok": False, "status": "DIALOG_ERROR", "message": f"打开文件选择框失败：{exc}"}

                try:
                    if action == "select_legacy_archive_source":
                        self._post_json({
                            "type": "app_status",
                            "action": "select_legacy_archive_source",
                            "overlayVisible": bool(self._overlay_visible),
                            "applicationState": "ready",
                            "solverOwner": "overlay_runtime",
                            "legacyArchive": result,
                        })
                    elif action in ("export_history_records", "export_reviewed_labels"):
                        self._post_json({
                            "type": "app_status",
                            "action": action,
                            "overlayVisible": bool(self._overlay_visible),
                            "applicationState": "ready",
                            "solverOwner": "overlay_runtime",
                            ("labelsExportResult" if action == "export_reviewed_labels" else "exportResult"): result,
                        })
                    elif action == "import_history_bundle":
                        self._post_json({
                            "type": "app_status",
                            "action": "import_history_bundle",
                            "overlayVisible": bool(self._overlay_visible),
                            "applicationState": "ready",
                            "solverOwner": "overlay_runtime",
                            "importResult": result,
                        })
                    else:
                        self._post_json({
                            "type": "app_status",
                            "action": action,
                            "overlayVisible": bool(self._overlay_visible),
                            "applicationState": "ready",
                            "solverOwner": "overlay_runtime",
                            "settlementReview": result,
                        })
                except Exception:
                    pass

            if getattr(self, "InvokeRequired", False):
                try:
                    from System import Action
                    self.BeginInvoke(Action(_run))
                    return
                except Exception:
                    pass
            _run()

        def post_status(self, reason: str, application_state: str = "ready") -> None:
            if not self._accepting_commands:
                return
            if getattr(self, "InvokeRequired", False):
                try:
                    from System import Action
                    self.BeginInvoke(Action(lambda: self._post_status(reason, application_state)))
                    return
                except Exception:
                    pass
            self._post_status(reason, application_state)

        def _post_status(self, reason: str, application_state: str = "ready") -> None:
            payload = {
                "type": "app_status",
                "reason": reason,
                "overlayVisible": self._overlay_visible,
                "applicationState": application_state,
                "presentationData": "mixed",
                "solverOwner": "overlay_runtime",
                "mascotPresentation": self._mascot_presentation,
                "presentationRuntime": (
                    self._bridge.presentation_runtime_payload()
                    if self._bridge is not None
                    else PresentationRuntimeSnapshot().to_payload()
                ),
            }
            if self._bridge is not None:
                main_view_state = self._bridge.main_view_state_payload()
                if main_view_state is not None:
                    payload["mainViewState"] = main_view_state
                mascot_state = self._bridge.mascot_state_payload(application_state)
                if mascot_state is not None:
                    payload["mascotState"] = mascot_state
                current_match = self._bridge.current_match_payload()
                if current_match is not None:
                    payload["currentMatch"] = current_match
                wh_payload = self._bridge.warehouse_capture_payload()
                payload["warehouseCapture"] = wh_payload
                wh_state = str(wh_payload.get("state") or "")
                if wh_state in {"IDLE", "COMPLETE", "PARTIAL", "ERROR", "TIMEOUT", "SCENE_LEFT", "NO_SESSION"}:
                    self._bridge.set_capture_safety_override(False)
                elif wh_state in {"WAITING_FOR_GAME_FOCUS", "STARTING", "CAPTURING", "SCROLLING", "WAITING", "ALIGNING"}:
                    self._bridge.set_capture_safety_override(True)
                payload["mainPinned"] = bool(self._bridge.user_pinned)
                payload["effectiveTopMost"] = bool(self._bridge.effective_topmost)
                payload["captureSafetyOverride"] = bool(self._bridge.capture_safety_override)
            self._post_json(payload)

        def post_snapshot_result(self, snapshot_result: dict) -> None:
            if self._bridge is None:
                return
            payload = self._bridge.snapshot_completion_payload(snapshot_result)
            payload["overlayVisible"] = bool(self._overlay_visible)
            self._post_json(payload)

        def _post_json(self, payload: dict) -> None:
            if self._presentation_webview is None:
                return
            if getattr(self, "InvokeRequired", False):
                try:
                    from System import Action
                    self.BeginInvoke(Action(lambda: self._post_json(payload)))
                    return
                except Exception:
                    pass
            try:
                self._presentation_webview.PostWebMessageAsJson(
                    json.dumps(payload, ensure_ascii=False)
                )
            except Exception as exc:
                self._log("ACTION:MAIN", f"Main status publish failed: {exc}")

        def WndProc(self, m):
            if getattr(self, "_is_composition_host", False) and getattr(self, "_presentation_controller", None) is not None:
                msg = int(m.Msg)
                if msg in (0x0007, 0x0201):  # WM_SETFOCUS or WM_LBUTTONDOWN
                    try:
                        from Microsoft.Web.WebView2.Core import CoreWebView2MoveFocusReason
                        self._presentation_controller.MoveFocus(CoreWebView2MoveFocusReason.Programmatic)
                    except Exception:
                        pass
                from Microsoft.Web.WebView2.Core import CoreWebView2MouseEventKind, CoreWebView2MouseEventVirtualKeys
                kind = None
                if msg == 0x0200:   # WM_MOUSEMOVE
                    kind = CoreWebView2MouseEventKind.Move
                elif msg == 0x0201: # WM_LBUTTONDOWN
                    kind = CoreWebView2MouseEventKind.LeftButtonDown
                elif msg == 0x0202: # WM_LBUTTONUP
                    kind = CoreWebView2MouseEventKind.LeftButtonUp
                elif msg == 0x0203: # WM_LBUTTONDBLCLK
                    kind = CoreWebView2MouseEventKind.LeftButtonDoubleClick
                elif msg == 0x0204: # WM_RBUTTONDOWN
                    kind = CoreWebView2MouseEventKind.RightButtonDown
                elif msg == 0x0205: # WM_RBUTTONUP
                    kind = CoreWebView2MouseEventKind.RightButtonUp
                elif msg == 0x0206: # WM_RBUTTONDBLCLK
                    kind = CoreWebView2MouseEventKind.RightButtonDoubleClick
                elif msg == 0x0207: # WM_MBUTTONDOWN
                    kind = CoreWebView2MouseEventKind.MiddleButtonDown
                elif msg == 0x0208: # WM_MBUTTONUP
                    kind = CoreWebView2MouseEventKind.MiddleButtonUp
                elif msg == 0x020A: # WM_MOUSEWHEEL
                    kind = CoreWebView2MouseEventKind.Wheel
                elif msg == 0x02A3: # WM_MOUSELEAVE
                    kind = CoreWebView2MouseEventKind.Leave

                if kind is not None:
                    lparam = int(m.LParam.ToInt64())
                    wparam = int(m.WParam.ToInt64())
                    x = (lparam & 0xFFFF)
                    if x >= 0x8000:
                        x -= 0x10000
                    y = ((lparam >> 16) & 0xFFFF)
                    if y >= 0x8000:
                        y -= 0x10000

                    mouse_data = 0
                    if msg == 0x020A: # WM_MOUSEWHEEL
                        mouse_data = ((wparam >> 16) & 0xFFFF)
                        screen_pt = Drawing.Point(x, y)
                        client_pt = self.PointToClient(screen_pt)
                        x, y = client_pt.X, client_pt.Y

                    keys = getattr(CoreWebView2MouseEventVirtualKeys, "None")
                    if (wparam & 0x0001) != 0:
                        keys |= CoreWebView2MouseEventVirtualKeys.LeftButton
                    if (wparam & 0x0002) != 0:
                        keys |= CoreWebView2MouseEventVirtualKeys.RightButton
                    if (wparam & 0x0004) != 0:
                        keys |= CoreWebView2MouseEventVirtualKeys.Shift
                    if (wparam & 0x0008) != 0:
                        keys |= CoreWebView2MouseEventVirtualKeys.Control
                    if (wparam & 0x0010) != 0:
                        keys |= CoreWebView2MouseEventVirtualKeys.MiddleButton

                    try:
                        self._presentation_controller.SendMouseInput(kind, keys, mouse_data, Drawing.Point(x, y))
                    except Exception:
                        pass

            BaseForm.WndProc(self, m)

        def OnResize(self, event):
            try:
                BaseForm.OnResize(self, event)
            except Exception:
                pass
            self._update_presentation_bounds()

        def _on_resize(self, sender, event) -> None:
            self._update_presentation_bounds()

        def _update_presentation_bounds(self) -> None:
            controller = getattr(self, "_presentation_controller", None)
            if controller is not None and hasattr(controller, "Bounds"):
                client_size = getattr(self, "ClientSize", None)
                if client_size is not None:
                    try:
                        controller.Bounds = Drawing.Rectangle(
                            0, 0, client_size.Width, client_size.Height
                        )
                        dcomp = getattr(self, "_dcomp_device", None)
                        if dcomp is not None:
                            dcomp.Commit()
                    except Exception:
                        pass

        def _on_form_closing(self, sender, event) -> None:
            self.set_topmost(False)
            if self._shutdown_request:
                self._shutdown_request("main_window_close", False)

        def _log(self, category: str, message: str) -> None:
            if self._logger:
                self._logger(category, message)

    MainWindow.__name__ = "MainWindow"
    return MainWindow
