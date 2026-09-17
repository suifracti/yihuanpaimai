"""
Neverness to Everness (异环) - 拍卖战术助手主程序 (v0.65)
【单一入口主程序】
所有参数均在同目录下的 config.json 中配置，所有核心模块均在 core/ 文件夹中。
双击运行即可自动完成：
  1. 高分屏 DPI 适配与自适应坐标安全保护 (支持 1080P / 2K / 4K)
  2. 读取 config.json 环境参数
  3. 启动本地后台 WebSocket 通信总线
  4. 弹出游戏右上角透明战术悬浮窗 (支持拖拽、右键菜单与游戏吸附)
  5. 启动实时屏幕感知与智能决策推演
  6. 终局自动记账归档
"""

import sys
import os
import io
import math

# 运行时路径分两种情况：源码运行时 app/ 是入口目录，打包后
# BASE_DIR 是发行目录，BUNDLE_DIR 是资源包目录 (_internal)。
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, '_MEIPASS', os.path.join(BASE_DIR, "_internal"))
    PROJECT_ROOT = BUNDLE_DIR if os.path.exists(os.path.join(BUNDLE_DIR, "core")) else BASE_DIR
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

CORE_DIR = os.path.join(PROJECT_ROOT, "core")
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
LAB_PATH = os.path.join(PROJECT_ROOT, "lab", "index.html")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, CORE_DIR)

if __name__ == "__main__":
    # Callbacks import main; keep the executable entrypoint as the same owner.
    sys.modules["main"] = sys.modules[__name__]

# 无控制台（GUI模式）标准流安全防护
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import time
from datetime import datetime, timezone, timedelta
import json
import threading
import asyncio
import webbrowser
import ctypes
import subprocess
import tempfile
import uuid
from typing import Optional, Dict, Any, List, Callable, Set
import cv2
import websockets
import numpy as np
import mss
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    for _pydir in [
        r"C:\Program Files\Python310\Lib\site-packages\pywin32_system32",
        os.path.join(sys.prefix, "Lib", "site-packages", "pywin32_system32"),
    ]:
        if os.path.isdir(_pydir):
            try:
                os.add_dll_directory(_pydir)
            except OSError:
                pass

import win32gui
import win32con

from main_view_state import MainViewStateProvider
from presentation_runtime import PresentationRuntimeState
from recognition_mode import get_recognition_mode, set_recognition_mode
from player_identity import get_player_name, set_player_name
from session_accounting import accounting_from_facts
from live_match_projection import bids_hidden_now
from field_intel_status import free_intel_status
from warehouse_capture_host import (
    attach_warehouse_capture_presentation,
    build_production_warehouse_capture_host,
    set_warehouse_capture_host,
)


def get_production_warehouse_bindings() -> Dict[str, Any]:
    """Read authoritative live bindings without duplicating state authority."""
    try:
        from window_tracker import ensure_default_desktop
        ensure_default_desktop()
    except Exception:
        pass
    payload = globals().get("LATEST_VISION_PAYLOAD") or globals().get("LATEST_PAYLOAD") or {}
    scene = str(payload.get("scene") or ("SETTLEMENT" if payload.get("isSettlement") else "UNKNOWN"))
    is_settlement = bool(payload.get("isSettlement") or scene == "SETTLEMENT")

    settlement_data = payload.get("settlementData") if isinstance(payload.get("settlementData"), dict) else {}
    stable = bool(
        settlement_data.get("stable")
        or payload.get("settlementReady")
        or payload.get("settlementStable")
        or payload.get("settlementFinalized")
    )

    cur_match = globals().get("CURRENT_MATCH")
    match_id = getattr(cur_match, "id", "") if cur_match is not None else ""
    record_key = str(
        payload.get("recordStableKey")
        or settlement_data.get("recordStableKey")
        or match_id
        or ""
    ).strip()

    game_hwnd = int(payload.get("gameHwnd") or payload.get("hwnd") or 0)
    if not game_hwnd:
        try:
            from window_capture import WindowCaptureManager

            mgr = WindowCaptureManager()
            found = mgr.find_game_hwnd()
            game_hwnd = int(found or 0)
        except Exception:
            game_hwnd = 0

    foreground = bool(payload.get("foreground", True))
    visible = bool(payload.get("visible", True))
    minimized = bool(payload.get("minimized", False))
    if game_hwnd:
        try:
            if win32gui.IsWindow(game_hwnd):
                foreground = win32gui.GetForegroundWindow() == game_hwnd
                visible = bool(win32gui.IsWindowVisible(game_hwnd))
                minimized = bool(win32gui.IsIconic(game_hwnd))
        except Exception:
            pass

    scroll_state = str(payload.get("scrollState") or "").strip().upper()
    warehouse_roi = payload.get("warehouseRoi")
    if not warehouse_roi or not isinstance(warehouse_roi, (list, tuple)) or len(warehouse_roi) != 4 or warehouse_roi == (0, 0, 0, 0):
        try:
            from warehouse_scrollbar_observation import warehouse_search_roi

            if game_hwnd and win32gui.IsWindow(game_hwnd):
                rect = win32gui.GetClientRect(game_hwnd)
                w, h = int(rect[2]), int(rect[3])
                if w > 0 and h > 0:
                    warehouse_roi = warehouse_search_roi(w, h)
                else:
                    warehouse_roi = warehouse_search_roi(1920, 1080)
            else:
                warehouse_roi = warehouse_search_roi(1920, 1080)
        except Exception:
            warehouse_roi = (0, 0, 0, 0)

    if not scroll_state or scroll_state == "UNKNOWN":
        raw_scroll = payload.get("scrollState")
        if raw_scroll:
            scroll_state = str(raw_scroll).strip().upper()
        else:
            frame = payload.get("frame")
            if frame is not None:
                try:
                    from warehouse_scrollbar_observation import observe_warehouse_scrollbar

                    obs = observe_warehouse_scrollbar(frame)
                    scroll_state = str(obs.get("scrollState") or "UNKNOWN").strip().upper()
                except Exception:
                    scroll_state = "UNKNOWN"
            else:
                scroll_state = "UNKNOWN"

    warehouse_present = payload.get("warehousePresent")
    if warehouse_present is None:
        warehouse_present = payload.get("warehouse_present")
    if warehouse_present is None:
        frame = payload.get("frame")
        if frame is not None:
            try:
                from warehouse_grid_geometry import observe_warehouse_grid

                grid_obs = observe_warehouse_grid(frame)
                warehouse_present = grid_obs.get("grid", {}).get("status") == "OK"
            except Exception:
                warehouse_present = False
        else:
            warehouse_present = False
    else:
        warehouse_present = bool(warehouse_present)

    return {
        "scene": scene,
        "isSettlement": is_settlement,
        "stable": stable,
        "recordStableKey": record_key,
        "hwnd": game_hwnd,
        "warehouseRoi": tuple(warehouse_roi) if isinstance(warehouse_roi, (list, tuple)) and len(warehouse_roi) == 4 else (0, 0, 0, 0),
        "scrollState": scroll_state,
        "warehousePresent": warehouse_present,
        "storeAvailable": True,
        "foreground": foreground,
        "visible": visible,
        "minimized": minimized,
    }


WAREHOUSE_CAPTURE_HOST = build_production_warehouse_capture_host(
    bindings_probe=get_production_warehouse_bindings
)
set_warehouse_capture_host(WAREHOUSE_CAPTURE_HOST)

_CAPTURE_SAFETY_OVERRIDE_CALLBACK: Optional[Callable[[bool], Any]] = None
_CAPTURE_SAFETY_OVERRIDE_FLAG: bool = False
_AUTO_CAPTURE_ATTEMPTED_KEYS: Set[str] = set()


def set_capture_safety_override(override: bool) -> bool:
    global _CAPTURE_SAFETY_OVERRIDE_FLAG
    _CAPTURE_SAFETY_OVERRIDE_FLAG = bool(override)
    if _CAPTURE_SAFETY_OVERRIDE_CALLBACK is not None:
        try:
            res = _CAPTURE_SAFETY_OVERRIDE_CALLBACK(override)
            if res is not None:
                return bool(res)
        except Exception:
            pass
    return _CAPTURE_SAFETY_OVERRIDE_FLAG


def get_capture_safety_override() -> bool:
    return bool(_CAPTURE_SAFETY_OVERRIDE_FLAG)


def register_capture_safety_override_callback(cb: Optional[Callable[[bool], Any]]) -> None:
    global _CAPTURE_SAFETY_OVERRIDE_CALLBACK
    _CAPTURE_SAFETY_OVERRIDE_CALLBACK = cb


def reset_auto_capture_guard() -> None:
    """Helper for testing: clears attempted keys and resets safety override."""
    global _CAPTURE_SAFETY_OVERRIDE_FLAG
    _AUTO_CAPTURE_ATTEMPTED_KEYS.clear()
    _CAPTURE_SAFETY_OVERRIDE_FLAG = False


def maybe_trigger_auto_warehouse_capture(
    ctx: Optional[Dict[str, Any]] = None,
    host: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Phase 11: Auto-trigger full warehouse capture orchestration once per recordStableKey.

    Reuses existing production prerequisites and start path:
    1. Check host already running guard
    2. Check per-recordStableKey once guard
    3. Check settlement prerequisites (fail-closed if context provided)
    4. Call existing host.prepare()
    5. Set existing captureSafetyOverride
    6. Call existing host.confirm(token_id)
    """
    if host is None:
        try:
            from warehouse_capture_host import get_warehouse_capture_host

            host = get_warehouse_capture_host()
        except Exception:
            return None

    if host is None:
        return None

    # Already running guard
    if getattr(host, "_running", False) or (hasattr(host, "is_running") and host.is_running):
        return None

    # Resolve recordStableKey
    record_key = ""
    if isinstance(ctx, dict):
        record_key = str(ctx.get("recordStableKey") or "").strip()
    if not record_key:
        cur_match = globals().get("CURRENT_MATCH")
        match_id = getattr(cur_match, "id", "") if cur_match is not None else ""
        record_key = str(match_id or "").strip()
    if not record_key:
        return None

    # Once guard: exactly 1 attempt per recordStableKey
    if record_key in _AUTO_CAPTURE_ATTEMPTED_KEYS:
        return None

    # Context prerequisites pre-check (fail-closed)
    if isinstance(ctx, dict):
        is_settle = bool(ctx.get("isSettlement") or ctx.get("scene") == "SETTLEMENT")
        if not is_settle:
            return None

        # Warehouse capture is authorized by the independent visual warehouse
        # authority. Settlement amount/stability remains an AutoArchive gate.
        if ctx.get("warehousePresent") is not True:
            return None

        scroll = str(ctx.get("scrollState") or "UNKNOWN").strip().upper()
        if scroll not in {"TOP", "NO_SCROLL"}:
            return None

    # Step 1: Reuse existing prepare() path
    if not hasattr(host, "prepare"):
        return None
    prep_res = host.prepare()
    if not isinstance(prep_res, dict) or not prep_res.get("ok"):
        return prep_res

    arming_token = prep_res.get("armingToken")
    if not arming_token:
        return prep_res

    # Mark once guard attempted for this key before starting
    _AUTO_CAPTURE_ATTEMPTED_KEYS.add(record_key)

    # Step 2: Safety override (drops topmost so game can be focused)
    set_capture_safety_override(True)

    # Step 3: Reuse existing confirm() -> starts worker
    if hasattr(host, "confirm"):
        confirm_res = host.confirm(arming_token)
        return confirm_res
    return prep_res
try:
    from canonical_history_store import CanonicalHistoryStore
    from runtime_data import runtime_data_paths
    from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
    from warehouse_identity_review_session import WarehouseIdentityReviewSession

    WAREHOUSE_IDENTITY_REVIEW = WarehouseIdentityReviewSession(
        store=SettlementEvidenceStoreV2(runtime_data_paths().root),
        packet_provider=WAREHOUSE_CAPTURE_HOST.review_packet_copy,
    )
    WAREHOUSE_IDENTITY_HISTORY = CanonicalHistoryStore()
except Exception:
    from warehouse_identity_review_session import WarehouseIdentityReviewSession

    WAREHOUSE_IDENTITY_REVIEW = WarehouseIdentityReviewSession(
        packet_provider=WAREHOUSE_CAPTURE_HOST.review_packet_copy,
    )
    WAREHOUSE_IDENTITY_HISTORY = None

# 显式注册 Windows 独立 AppUserModelID (确保 Windows 任务栏 / Dock / Alt+Tab 识别为独立看板娘应用而非 Python)
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('NTE.AuctionTacticalHud.Mascot.v065')
except Exception:
    pass

# 高分屏 Per-Monitor DPI 感知初始化 (防止 2K/4K 缩放坐标错位)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from runtime_data import (
    discover_legacy_history_candidates,
    initialize_runtime_data,
    resolve_runtime_history_path,
    resolve_runtime_data_root,
    is_isolated_trial,
)

RUNTIME_DATA_INITIALIZATION = initialize_runtime_data(
    legacy_candidates=discover_legacy_history_candidates(
        executable_dir=BASE_DIR,
        bundle_dir=PROJECT_ROOT,
        frozen=bool(getattr(sys, "frozen", False)),
    )
)
CANONICAL_DATABASE = (
    str(RUNTIME_DATA_INITIALIZATION.paths.history_path)
    if RUNTIME_DATA_INITIALIZATION.available
    and RUNTIME_DATA_INITIALIZATION.paths is not None
    else None
)
from runtime_revision import get_code_revision
from prediction_snapshot_holder import ACTIVE_SNAPSHOT_HOLDER
from settlement_truth_holder import ACTIVE_SETTLEMENT_TRUTH_HOLDER

if "--print-code-revision" in sys.argv or "--version" in sys.argv:
    print(get_code_revision())
    sys.exit(0)

if "--smoke-upper-tail-capture-hook" in sys.argv:
    from experiments.upper_tail_truth_support_capture_v1.runtime_capture_hook import (
        load_and_validate_capture,
        resolve_capture_store,
        source_package_parity_signature,
    )
    import hashlib
    import tempfile

    smoke_result = None
    previous_collection_class = os.environ.get("YIHUAN_CAPTURE_COLLECTION_CLASS")
    try:
        os.environ["YIHUAN_CAPTURE_COLLECTION_CLASS"] = "RUNTIME_SMOKE_CAPTURE"
        from live_shadow import compute_live_probability_profile, reset_live_shadow_state

        red_names = ["「泪滴」", "「摇星」", "九格小食", "永生花环", "鸣佩"]
        records = []
        for index, red_name in enumerate(red_names):
            records.append(
                {
                    "id": f"capture-smoke-history-{index}",
                    "playedAt": f"2026-08-{10 + index:02d}T10:00:00+08:00",
                    "venue": "capture-smoke-venue",
                    "box": "capture-smoke-box",
                    "q": 9,
                    "goldCount": 3,
                    "purpleCount": 5,
                    "redCount": 1,
                    "goldAvg": 33538,
                    "actualTotal": 200000 + index * 10000,
                    "fieldCondition": "standard",
                    "catalogVersion": "2026-08-13",
                    "redInventoryComplete": True,
                    "settlementVerifiedRedItems": red_name,
                    "settlement": {
                        "redCount": 1,
                        "redInventoryComplete": True,
                        "verifiedRedItems": red_name,
                        "truthSource": "smoke-fixture",
                        "truthConfidence": "verified",
                    },
                }
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke_history = os.path.join(temp_dir, "capture_smoke_history.json")
            with open(smoke_history, "w", encoding="utf-8", newline="\n") as stream:
                json.dump({"records": records}, stream, ensure_ascii=False)
            with open(smoke_history, "rb") as stream:
                history_before = hashlib.sha256(stream.read()).hexdigest()
            profile, meta = compute_live_probability_profile(
                {
                    "matchId": "runtime-capture-smoke-001",
                    "playedAt": "2026-08-22T10:00:00+08:00",
                    "scene": "IN_AUCTION",
                    "round": 3,
                    "q": 9,
                    "purpleCount": 5,
                    "goldAvg": 33538,
                    "venue": "capture-smoke-venue",
                    "box": "capture-smoke-box",
                    "fieldCondition": "standard",
                    "catalogVersion": "2026-08-13",
                },
                db_path=smoke_history,
                persist_runtime=False,
            )
            with open(smoke_history, "rb") as stream:
                history_after = hashlib.sha256(stream.read()).hexdigest()
            capture_meta = meta.get("supportCapture") or {}
            capture_path = capture_meta.get("path")
            if capture_meta.get("status") not in ("WRITTEN", "DUPLICATE") or not capture_path:
                raise RuntimeError(
                    "capture unavailable: "
                    f"status={capture_meta.get('status')!r} "
                    f"reason={capture_meta.get('reason')!r} "
                    f"shadowError={meta.get('error')!r}"
                )
            artifact = load_and_validate_capture(capture_path)
            published_quantiles = (meta.get("predictionSnapshot") or {}).get("forecast", {}).get("quantiles")
            capture_quantiles = artifact.get("aggregateDistribution", {}).get("quantiles")
            smoke_success = bool(
                capture_meta.get("status") in ("WRITTEN", "DUPLICATE")
                and artifact.get("collectionClass") == "RUNTIME_SMOKE_CAPTURE"
                and capture_quantiles == published_quantiles
                and history_before == history_after
                and profile is not None
            )
            smoke_result = {
                "smoke": "upper_tail_capture_hook_v1",
                "frozen": bool(getattr(sys, "frozen", False)),
                "signature": source_package_parity_signature(),
                "captureStore": str(resolve_capture_store()),
                "captureStatus": capture_meta.get("status"),
                "captureId": artifact.get("captureId"),
                "collectionClass": artifact.get("collectionClass"),
                "quantilesEqual": capture_quantiles == published_quantiles,
                "historyUnchanged": history_before == history_after,
                "artifactSize": os.path.getsize(capture_path),
                "success": smoke_success,
            }
        reset_live_shadow_state()
    except Exception as smoke_error:
        smoke_result = {
            "smoke": "upper_tail_capture_hook_v1",
            "frozen": bool(getattr(sys, "frozen", False)),
            "signature": source_package_parity_signature(),
            "captureStore": str(resolve_capture_store()),
            "error": f"{type(smoke_error).__name__}:{smoke_error}",
            "success": False,
        }
    finally:
        if previous_collection_class is None:
            os.environ.pop("YIHUAN_CAPTURE_COLLECTION_CLASS", None)
        else:
            os.environ["YIHUAN_CAPTURE_COLLECTION_CLASS"] = previous_collection_class
    smoke_output = os.environ.get("NTE_CAPTURE_HOOK_SMOKE_OUTPUT")
    if smoke_output:
        os.makedirs(os.path.dirname(os.path.abspath(smoke_output)), exist_ok=True)
        with open(smoke_output, "w", encoding="utf-8", newline="\n") as smoke_file:
            json.dump(smoke_result, smoke_file, ensure_ascii=False, indent=2)
            smoke_file.write("\n")
    print(json.dumps(smoke_result, ensure_ascii=False, indent=2))
    sys.exit(0 if smoke_result.get("success") else 1)

if "--smoke-evidence-storage" in sys.argv:
    from evidence_storage import get_canonical_data_dir, save_evidence_png, verify_evidence_file
    import hashlib

    smoke_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    smoke_frame[10:30, 10:30] = [200, 100, 50]
    smoke_frame[35:55, 35:55] = [50, 200, 100]

    match_id = "packaged_smoke_probe"
    rel_uri, digest = save_evidence_png(smoke_frame, match_id)

    data_dir = get_canonical_data_dir()
    file_path = data_dir / rel_uri.replace("/", os.sep)

    file_exists = file_path.is_file()
    verify_ok = verify_evidence_file(rel_uri, digest)

    disk_bytes = file_path.read_bytes() if file_exists else b""
    disk_sha256 = hashlib.sha256(disk_bytes).hexdigest()
    hash_match = (disk_sha256 == digest)

    try:
        if file_exists:
            file_path.unlink()
    except Exception:
        pass

    result = {
        "smoke": "evidence_storage_real_path",
        "frozen": getattr(sys, "frozen", False),
        "codeRevision": get_code_revision(),
        "canonicalDataDir": str(data_dir),
        "absoluteFilePath": str(file_path),
        "relativeUri": rel_uri,
        "sha256": digest,
        "diskSha256": disk_sha256,
        "fileExists": file_exists,
        "verifyEvidenceFile": verify_ok,
        "hashMatch": hash_match,
        "reReadVerified": bool(file_exists and verify_ok and hash_match),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["reReadVerified"] else 1)

if "--smoke-canonical-persistence" in sys.argv:
    import tempfile
    from auto_archiver import AutoArchiver
    from canonical_match_record import validate_finalized_match_record_v7

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_db = os.path.join(tmp_dir, "smoke_history.json")
        archiver = AutoArchiver(db_paths=[tmp_db])
        ctx = {
            "id": "smoke_packaged_001",
            "matchId": "smoke_packaged_001",
            "venue": "shanhu",
            "box": "实木宝箱",
            "boxType": "wood",
            "fieldCondition": "standard",
            "settlementReady": True,
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 100000,
                "actualTotal": 150000,
                "profit": 50000,
                "items": [],
            },
        }
        draft = archiver.archive_match(ctx)
        unknown_kept_draft = bool(draft and draft.get("lifecycleStatus") == "DRAFT"
                                 and draft.get("settlement", {}).get("acquired") is None)
        ctx["settlementReady"] = True
        ctx["settlementData"].update(acquired=False, winner="SmokeOpponent")
        rec = archiver.archive_match(ctx)
        is_val, reas = validate_finalized_match_record_v7(rec)
        success = bool(unknown_kept_draft and is_val and rec and rec.get("schemaVersion") == 7
                       and rec.get("lifecycleStatus") == "FINALIZED"
                       and rec.get("settlement", {}).get("acquired") is False)
        smoke_res = {
            "smoke": "canonical_match_record_v7_persistence",
            "frozen": getattr(sys, "frozen", False),
            "codeRevision": get_code_revision(),
            "validFinalizedV7": is_val,
            "unknownKeptDraft": unknown_kept_draft,
            "validationReasons": reas,
            "schemaVersion": rec.get("schemaVersion") if rec else None,
            "lifecycleStatus": rec.get("lifecycleStatus") if rec else None,
            "success": success,
        }
        print(json.dumps(smoke_res, ensure_ascii=False, indent=2))
        sys.exit(0 if success else 1)

PROCESS_START_TIME = time.perf_counter()
LOG_DIR = (
    str(RUNTIME_DATA_INITIALIZATION.paths.logs_dir)
    if RUNTIME_DATA_INITIALIZATION.paths is not None
    else None
)
DEBUG_MODE = ("--debug" in sys.argv) or (os.environ.get("NTE_DEBUG", "").strip() in ("1", "true", "TRUE", "yes"))

def _resolve_session_log_path() -> str:
    preset = (os.environ.get("NTE_LOG_FILE") or "").strip()
    if preset:
        parent = os.path.dirname(preset)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return preset
    if LOG_DIR is None:
        return os.devnull
    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(LOG_DIR, f"run_{stamp}.log")
    os.environ["NTE_LOG_FILE"] = path
    return path

LOG_FILE_PATH = _resolve_session_log_path()
_LOG_LOCK = threading.Lock()

LATEST_PAYLOAD: Dict[str, Any] = {}
LATEST_VISION_PAYLOAD: Dict[str, Any] = {}
VISION_PROCESS: Optional[subprocess.Popen] = None
_VISION_PROCESS_LOCK = threading.RLock()
HUD_JS_API = None
PRESENTATION_RUNTIME = PresentationRuntimeState(
    "disabled" if os.environ.get("NTE_DISABLE_VISION") == "1" else "stopped"
)
MAIN_VIEW_STATE_PROVIDER = MainViewStateProvider(
    CANONICAL_DATABASE,
    authority_availability=(
        RUNTIME_DATA_INITIALIZATION.availability
        if RUNTIME_DATA_INITIALIZATION.availability
        in {"MIGRATION_REQUIRED", "MIGRATION_CONFLICT", "CORRUPT", "UNAVAILABLE"}
        else None
    ),
    authority_reason=RUNTIME_DATA_INITIALIZATION.reason,
)

from session_costs import costs_from_facts, describe_costs
from acquisition_authority import acquisition_from_context
from current_match import CurrentMatch, CURRENT_MATCH, FORBIDDEN_WINNER_PLACEHOLDERS, is_missing_observation
from auto_archiver import AutoArchiver
from canonical_history_store import CanonicalHistoryStore
from manual_terminal import ManualTerminalCoordinator, ManualTerminalError
import business_sot as _business_sot
if getattr(sys, 'frozen', False):
    _business_sot._SOT_PATH = os.path.join(ASSETS_DIR, "business_sot_v06.json")
    _business_sot.load_sot.cache_clear()
from business_sot import all_boxes, field_conditions, canonicalize_field_condition, UNKNOWN_FIELD
if "--smoke-vision-frame" in sys.argv:
    from runtime_vision_smoke import run_from_environment
    sys.exit(run_from_environment(ASSETS_DIR))

from venue_box_catalog import (
    CatalogContractError,
    canonical_catalog_provenance,
    catalog_selection,
    load_catalog,
    manual_options as catalog_manual_options,
    normalize_vision_venue,
    normalize_vision_box,
    solver_context_translation,
)
from v06_adapter import canonical_to_v06_solver_input

# CURRENT_MATCH imported above from current_match singleton
DRAFT_ARCHIVER = AutoArchiver(
    db_paths=[CANONICAL_DATABASE] if CANONICAL_DATABASE else []
)
MANUAL_TERMINAL = ManualTerminalCoordinator(CANONICAL_DATABASE)
VENUE_BOX_CATALOG = load_catalog(
    os.path.join(ASSETS_DIR, "venue_box_catalog_v1", "venue_box_catalog_v1.json")
    if getattr(sys, "frozen", False)
    else None
)
MANUAL_VISIBLE_TARGET_PROFIT_DEFAULT = 0

def log_stage(category: str, msg: str):
    elapsed_ms = (time.perf_counter() - PROCESS_START_TIME) * 1000
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{elapsed_ms:8.2f}ms] [{category}] {msg}"
    print(line, flush=True)
    try:
        with _LOG_LOCK:
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
    except Exception:
        pass


def is_running_as_admin_or_high_integrity() -> bool:
    """
    检测当前进程是否以 Administrator / High Integrity Level 运行。
    WebView2 在未配置特殊沙箱参数时，在管理员权限下附加标准 HWND 控制器会导致
    0x80070578 (ERROR_INVALID_WINDOW_HANDLE) 报错造成页面无法加载。
    """
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return True
    except Exception:
        pass
    try:
        token = ctypes.wintypes.HANDLE()
        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32
        if advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            length = ctypes.wintypes.DWORD()
            advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(length))
            buf = ctypes.create_string_buffer(length.value)
            if advapi32.GetTokenInformation(token, 25, buf, length.value, ctypes.byref(length)):
                p_sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
                sub_auth_count = advapi32.GetSidSubAuthorityCount(p_sid).contents.value
                level = advapi32.GetSidSubAuthority(p_sid, sub_auth_count - 1).contents.value
                kernel32.CloseHandle(token)
                if level >= 0x3000:
                    return True
            kernel32.CloseHandle(token)
    except Exception:
        pass
    return False

def check_residual_processes():
    """核查残留子进程"""
    global VISION_PROCESS
    if VISION_PROCESS is not None and VISION_PROCESS.poll() is None:
        return 1, [VISION_PROCESS.pid]
    return 0, []


def get_presentation_runtime_snapshot():
    """Return a frozen presentation-only snapshot with current process liveness."""
    if os.environ.get("NTE_DISABLE_VISION") == "1":
        process_state = "disabled"
    elif VISION_PROCESS is None:
        process_state = "stopped"
    elif VISION_PROCESS.poll() is None:
        process_state = "running"
    else:
        process_state = "exited"
    PRESENTATION_RUNTIME.set_vision_process_state(process_state)
    return PRESENTATION_RUNTIME.snapshot()


def get_current_match_presentation_summary() -> dict:
    """Return an immutable, presentation-only projection of the live match draft."""
    try:
        snap = CURRENT_MATCH.snapshot()
        facts = snap if ("venue" in snap or "q" in snap) else (snap.get("facts", {}) if isinstance(snap, dict) else {})
        prediction = ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match(CURRENT_MATCH.id)
        frozen = ACTIVE_SNAPSHOT_HOLDER.get_frozen_for_match(CURRENT_MATCH.id) or {}

        has_venue = bool(facts.get("venue") or facts.get("venueId"))
        has_box = bool(facts.get("box") or facts.get("boxId"))
        q_val = facts.get("q")
        gold_val = facts.get("goldAvg")
        purple_val = facts.get("purpleCount") if facts.get("purpleCount") is not None else facts.get("purple")
        purple_avg = facts.get("purpleAvg")

        is_complete = bool(has_venue and has_box and q_val is not None and gold_val is not None and purple_val is not None)

        venue_display = facts.get("venue") or facts.get("venueName") or (facts.get("venueId") if facts.get("venueId") else "未选择")
        box_display = facts.get("box") or (facts.get("boxId") if facts.get("boxId") else "未选择")
        field_condition = facts.get("fieldConditionName") or facts.get("fieldCondition") or "标准规则"

        # Missing Facts Categorization
        missing_value_facts = []
        if not has_venue:
            missing_value_facts.append("缺失会场")
        if not has_box:
            missing_value_facts.append("缺失宝箱")
        if q_val is None:
            missing_value_facts.append("缺失总高阶件数 Q")
        if gold_val is None:
            missing_value_facts.append("缺失金色均价")
        if purple_val is None:
            missing_value_facts.append("缺失紫色数量")

        missing_decision_facts = []

        # Prediction Summary
        prediction_summary = None
        decision_lines = None
        explainability = None

        if prediction is not None and isinstance(prediction, dict):
            forecast = prediction.get("forecast") or {}
            quantiles = forecast.get("quantiles") or {}
            formal = frozen.get("formalValue") or prediction.get("formalValue") or {}
            dec = frozen.get("decision") or prediction.get("decision") or {}
            mode_obj = prediction.get("mode") or {}
            if not isinstance(mode_obj, dict):
                mode_obj = {"informationMode": mode_obj}

            # Formal quantiles come only from the snapshot's declared forecast.
            p20 = quantiles.get("p20")
            p50 = quantiles.get("p50")
            p80 = quantiles.get("p80")
            ev = formal.get("ev") or (dec.get("valueP50") if dec else None)
            rec_max = next((value for value in (
                quantiles.get("recommendedMax"), formal.get("recommendedMax"), dec.get("recommendedMax")
            ) if value is not None), None)
            directive = prediction.get("actionDirective") or dec.get("actionDirective") or "WAIT"
            reason = prediction.get("actionReason") or dec.get("actionReason")
            solver_status = (prediction.get("status") or {}).get("solverStatus")
            if solver_status == "no-match":
                p20 = p50 = p80 = rec_max = ev = None
                directive = "WAIT"
                reason = "约束冲突：当前数量、均价、占格或已知藏品互相矛盾，请核对或清空相关条件"
            has_limit = isinstance(rec_max, (int, float)) and not isinstance(rec_max, bool) and math.isfinite(rec_max) and rec_max >= 0
            if directive == "BID" and not has_limit:
                directive = "WAIT"
                reason = None
            if not reason:
                reason = "等待情报：" + "、".join(missing_value_facts) if missing_value_facts else "等待有效出价建议"

            structural_obj = forecast.get("structural") or {}
            structural_center = structural_obj.get("center") or dec.get("structuralCenter") or formal.get("structuralCenter") or formal.get("ev")
            structural_bounds = formal.get("candidateBounds") or {}
            structural_min = structural_obj.get("candidateBoundsMin") or structural_bounds.get("min") or dec.get("candidateBoundsMin")
            structural_max = structural_obj.get("candidateBoundsMax") or structural_bounds.get("max") or dec.get("candidateBoundsMax")
            structural_ref_bid = structural_obj.get("recommendedMax") or dec.get("structuralReferenceBid") or formal.get("structuralReferenceBid")

            prediction_summary = {
                "hasSnapshot": True,
                "evidenceBounds": prediction.get("evidenceBounds"),
                "solverStatus": solver_status,
                "p20": p20,
                "p50": p50,
                "p80": p80,
                "ev": ev,
                "referenceValue": dec.get("partialShadowP50") if mode_obj.get("informationMode") == "partial_shadow" else (formal.get("ev") or structural_center),
                "estimateLabel": "整仓预测中位 (P50)" if mode_obj.get("informationMode") == "full_shadow" else (
                    "部分覆盖参考值" if mode_obj.get("informationMode") == "partial_shadow" else ("非概率结构估值中枢（非 P50）" if structural_center is not None else "结构参考值（非 P50）")),
                "recommendedMax": rec_max,
                "structuralCenter": structural_center,
                "structuralFeasibleMin": structural_min,
                "structuralFeasibleMax": structural_max,
                "structuralReferenceBid": structural_ref_bid,
                "actionDirective": directive,
                "actionReason": reason,
                "entryGrade": dec.get("entryGrade"),
                "mode": mode_obj.get("informationMode") or prediction.get("mode") or "structural_only",
                "supportStatus": prediction.get("supportStatus") or "STRUCTURAL_ONLY",
                "coverageRatio": mode_obj.get("coverageRatio") or dec.get("coverageRatio") or 0.0,
                "supportedStateCount": mode_obj.get("supportedStateCount") or dec.get("supportedStateCount") or 0,
                "totalStateCount": mode_obj.get("totalStateCount") or dec.get("totalStateCount") or 0,
                "missingReason": dec.get("missingReason") or (missing_value_facts[0] if missing_value_facts else None),
            }

            decision_lines = {
                "targetLine": frozen.get("targetLine") or dec.get("targetLine"),
                "globalLine": frozen.get("globalLine") or dec.get("globalLine"),
                "marginalLine": frozen.get("marginalLine") or dec.get("marginalLine"),
                "expectedProfit": dec.get("expectedProfit"),
                "roiOnTotalSpend": dec.get("roiOnTotalSpend"),
                "roiOnPurchase": dec.get("roiOnPurchase"),
                "structuralCenter": structural_center,
                "structuralFeasibleMin": structural_min,
                "structuralFeasibleMax": structural_max,
                "structuralReferenceBid": structural_ref_bid,
            }

            candidate_gs = (formal.get("candidateGs") or frozen.get("candidateGs") or [])[:10]
            explainability = {
                "candidateGs": candidate_gs,
                "candidateStateCount": dec.get("totalStateCount") or len(candidate_gs),
                "hardFloor": dec.get("hardFloor") or formal.get("hardFloor"),
                "theoreticalMin": dec.get("theoreticalMin"),
                "theoreticalMax": dec.get("theoreticalMax"),
                "goldInference": formal.get("goldInference"),
                "componentBreakdown": formal.get("breakdown") or {
                    "gold": (gold_val or 0) * (facts.get("goldCount") or 1) if gold_val else 0,
                    "purple": (purple_avg or 3904) * (purple_val or 0) if purple_val else 0,
                    "red": 0,
                    "lowTier": 0,
                },
                "costs": costs_from_facts(facts),
            }

        # Settlement Summary
        settlement_summary = None
        clearing = facts.get("clearingPrice")
        actual = facts.get("actualTotal")
        profit = facts.get("realizedProfit")
        items = facts.get("settlementItems") or []
        evidence_available = bool(facts.get("settlementTruthEvidence") or facts.get("settlementEvidence"))
        raw_winner = facts.get("winner")
        winner_candidate = str(raw_winner).strip() if raw_winner is not None and str(raw_winner).strip() else None
        settlement_winner = winner_candidate if (winner_candidate and winner_candidate not in FORBIDDEN_WINNER_PLACEHOLDERS) else None
        if clearing is not None or actual is not None or profit is not None or items:
            raw_acquired = facts.get("isAcquired") if facts.get("isAcquired") is not None else facts.get("didCurrentUserAcquire")
            if raw_acquired is None and facts.get("acquired") is not None:
                raw_acquired = facts.get("acquired")
            acquired = raw_acquired if isinstance(raw_acquired, bool) else None

            settlement_summary = {
                "clearingPrice": clearing,
                "actualTotal": actual,
                "realizedProfit": profit,
                "acquired": acquired,
                "winner": settlement_winner,
                "itemCount": len(items),
                "exactCount": len([it for it in items if it.get("status") == "exact" or it.get("identificationStatus") == "exact"]),
                "ambiguousCount": len([it for it in items if it.get("status") in ("ambiguous", "unknown") or it.get("identificationStatus") in ("ambiguous", "unknown")]),
                "unknownCount": len([it for it in items if it.get("status") == "unknown" or it.get("identificationStatus") == "unknown"]),
                "evidenceAvailable": evidence_available,
                "settlementReady": bool(facts.get("settlementReady")),
                "settlementFinalized": bool(facts.get("settlementFinalized")),
            }

        # Warehouse Summary
        wh_fact = facts.get("warehouse")
        warehouse_slots = (wh_fact.get("slots") if isinstance(wh_fact, dict) else []) or []
        exact_count = len([
            s for s in warehouse_slots
            if s.get("evidenceLevel") in ("EXACT_IDENTIFIED", "UNIQUE_IN_CATALOG")
            or (s.get("identifiedName") and s.get("rarity") != "unknown" and s.get("evidenceLevel") != "OUTLINE_ONLY")
        ])
        unknown_count = len([
            s for s in warehouse_slots
            if s.get("rarity") == "unknown" or s.get("evidenceLevel") == "OUTLINE_ONLY"
        ])
        ambiguous_count = len(warehouse_slots) - exact_count - unknown_count
        warehouse_summary = {
            "status": "synced" if warehouse_slots else "unrecorded",
            "itemCount": len(warehouse_slots),
            "exactCount": exact_count,
            "ambiguousCount": ambiguous_count,
            "unknownCount": unknown_count,
            "evidenceAvailable": bool(warehouse_slots or facts.get("warehouseEvidence")),
            "slots": warehouse_slots,
        }

        from live_match_projection import project_bidding_summary, project_intel
        bidding_summary = project_bidding_summary(facts)
        raw_leader = facts.get("leaderName") or bidding_summary.get("leader")
        leader_candidate = str(raw_leader).strip() if raw_leader is not None and str(raw_leader).strip() else None
        bidding_leader = settlement_winner or (leader_candidate if (leader_candidate and leader_candidate not in FORBIDDEN_WINNER_PLACEHOLDERS) else None)
        bidding_summary["leader"] = bidding_leader
        bidding_summary["leaderBid"] = facts.get("leaderBid") if facts.get("leaderBid") is not None else bidding_summary.get("leaderBid")
        intel_projection = project_intel(facts.get("auctionEvidence"), facts.get("intelFacts"))

        # Lobby / Session Loadout (Distinct from match trunk)
        lobby_summary = {
            "character": facts.get("character") or "未识别/默认",
            "lobbyToolGroup": "标准仪器",
            "entryCost": facts.get("entryCost") or 0,
        }

        # 6-Rarity Observed Facts Matrix (Honest nulls for unparsed qualities)
        qualities_summary = {
            "white": {"count": facts.get("whiteCount"), "avg": facts.get("whiteAvg"), "grid": facts.get("whiteGrid"), "knownItems": facts.get("knownWhite") or ""},
            "green": {"count": facts.get("greenCount"), "avg": facts.get("greenAvg"), "grid": facts.get("greenGrid"), "knownItems": facts.get("knownGreen") or ""},
            "blue": {"count": facts.get("blueCount"), "avg": facts.get("blueAvg"), "grid": facts.get("blueGrid"), "knownItems": facts.get("knownBlue") or ""},
            "purple": {"count": purple_val, "avg": purple_avg, "grid": facts.get("purpleGrid"), "knownItems": facts.get("knownPurple") or ""},
            "gold": {"count": facts.get("goldCount"), "avg": gold_val, "grid": facts.get("goldGrid"), "knownItems": facts.get("knownGold") or ""},
            "red": {"count": facts.get("redCount"), "grid": facts.get("redGrid"), "knownItems": facts.get("knownRed") or ""},
        }

        options = _manual_options()
        return {
            "matchId": CURRENT_MATCH.id,
            "recognitionMode": get_recognition_mode(),
            "configuredPlayerName": get_player_name(),
            "visionHealth": dict(LATEST_PAYLOAD.get("visionHealth") or {}),
            "isolatedTrial": is_isolated_trial(),
            "lifecycleStatus": snap.get("lifecycleStatus", "DRAFT"),
            "hasAnyFact": CURRENT_MATCH.has_any_fact(),
            "isComplete": is_complete,
            "environment": {
                "venueId": facts.get("venueId"),
                "venueName": venue_display if venue_display != "未选择" else None,
                "boxId": facts.get("boxId"),
                "box": box_display if box_display != "未选择" else None,
                "fieldCondition": facts.get("fieldCondition") or "standard",
                "fieldConditionName": field_condition,
            },
            "lobby": lobby_summary,
            "publicIntel": {
                "q": q_val,
                "totalItems": facts.get("totalItems"),
                "totalGrid": facts.get("totalGrid"),
                "avgValueBasis": facts.get("avgValueBasis"),
                "timeline": intel_projection,
            },
            "auctionEvidence": facts.get("auctionEvidence"),
            "qualities": qualities_summary,
            "missingValueFacts": missing_value_facts,
            "missingDecisionFacts": missing_decision_facts,
            "facts": {
                "venueId": facts.get("venueId"),
                "venue": venue_display if venue_display != "未选择" else None,
                "boxId": facts.get("boxId"),
                "box": box_display if box_display != "未选择" else None,
                "fieldCondition": facts.get("fieldCondition") or "standard",
                "q": q_val,
                "goldAvg": gold_val,
                "purpleCount": purple_val,
                "purpleAvg": purple_avg,
                "purpleGrid": facts.get("purpleGrid"),
                "goldGrid": facts.get("goldGrid"),
                "redCount": facts.get("redCount"),
                **{key: facts.get(key) for key in ("blueCount", "goldCount", "totalItems", "totalGrid", "whiteCount", "whiteAvg", "whiteGrid", "greenCount", "greenAvg", "greenGrid", "blueAvg", "blueGrid", "redGrid")},
                "knownGold": facts.get("knownGold") or "",
                "knownPurple": facts.get("knownPurple") or "",
                **{key: facts.get(key) for key in ("privateBidCap", "bidActionCount")},
        "welfareReceived": facts.get("welfareReceived"),
                "sparkle": facts.get("sparkle"),
                "knownBlue": facts.get("knownBlue") or "",
                "knownGreen": facts.get("knownGreen") or "",
                "knownWhite": facts.get("knownWhite") or "",

                "knownRed": facts.get("knownRed") or "",
                **{key: facts.get(key) for key in ("intelCost", "otherCost", "futureIncrementalCost")},
                "leaderBid": facts.get("leaderBid"),
                "targetProfit": MANUAL_VISIBLE_TARGET_PROFIT_DEFAULT,
            },
            "options": options,
            "prediction": prediction_summary,
            "decisionLines": decision_lines,
            "explainability": explainability,
            "costSummary": describe_costs(costs_from_facts(facts)),
            "bidding": bidding_summary,
            "freeIntelStatus": free_intel_status(facts),
            "sessionAccounting": accounting_from_facts(facts),
            "settlement": settlement_summary,
            "warehouse": warehouse_summary,
            "factsRevision": snap.get("factsRevision"),
            "fieldStates": snap.get("fieldStates") or {},
        }
    except Exception:
        return {
            "matchId": getattr(CURRENT_MATCH, "id", "draft_fallback"),
            "lifecycleStatus": "DRAFT",
            "hasAnyFact": False,
            "isComplete": False,
            "environment": {"venueId": None, "venueName": None, "boxId": None, "box": None, "fieldCondition": "standard", "fieldConditionName": "标准规则"},
            "lobby": {"character": "未识别/默认", "lobbyToolGroup": "标准仪器", "entryCost": 0},
            "publicIntel": {"q": None, "totalItems": None, "totalGrid": None, "avgValueBasis": None, "timeline": {"observations": [], "structured": [], "observationCount": 0}},
            "auctionEvidence": None,
            "qualities": {
                "white": {"count": None, "avg": None, "grid": None, "knownItems": ""},
                "green": {"count": None, "avg": None, "grid": None, "knownItems": ""},
                "blue": {"count": None, "avg": None, "grid": None, "knownItems": ""},
                "purple": {"count": None, "avg": None, "grid": None, "knownItems": ""},
                "gold": {"count": None, "avg": None, "grid": None, "knownItems": ""},
                "red": {"count": None, "avg": None, "grid": None, "knownItems": ""},
            },
            "missingValueFacts": ["缺失会场", "缺失宝箱", "缺失总高阶件数 Q", "缺失金色均价", "缺失紫色数量"],
            "missingDecisionFacts": [],
            "facts": {"venueId": None, "venue": None, "boxId": None, "box": None, "fieldCondition": "standard", "q": None, "goldAvg": None, "purpleCount": None, "purpleAvg": None, "purpleGrid": None, "goldGrid": None, "redCount": None, "knownGold": "", "knownPurple": "", "knownRed": "", "leaderBid": None, "targetProfit": None},
            "options": {"venues": [], "fieldConditions": []},
            "prediction": None,
            "decisionLines": None,
            "explainability": None,
            "bidding": {"seats": [], "roundNo": 1, "leader": None, "leaderBid": None, "finalBids": []},
            "settlement": None,
            "warehouse": {"status": "unrecorded", "itemCount": 0, "exactCount": 0, "ambiguousCount": 0, "unknownCount": 0, "evidenceAvailable": False},
        }

def handle_delete_history_record(record_id: str, source: Optional[str] = None) -> Dict[str, Any]:
    record_id = str(record_id or "").strip()
    if not record_id:
        return {"ok": False, "status": "RECORD_ID_EMPTY", "message": "记录 ID 不能为空"}

    # Check if this is a legacy archive record
    is_legacy = (source == "legacy") or record_id.startswith("legacy:")
    if is_legacy:
        try:
            from legacy_archive import LegacyArchive
            archive = LegacyArchive()
            res = archive.delete_record(record_id)
            log_stage("ACTION:HISTORY", f"Legacy record deleted successfully id={record_id} remaining={res.get('remainingCount')}")
            return {
                "ok": True,
                "status": "DELETED",
                "recordId": record_id,
                "isLegacy": True,
                "remainingCount": res.get("remainingCount"),
                "message": "历史归档记录已成功删除",
            }
        except Exception as exc:
            err_str = str(exc)
            log_stage("ACTION:HISTORY", f"Legacy record delete failed id={record_id} err={err_str}")
            if "not found" in err_str.lower():
                return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "该归档记录不存在或已被删除"}
            return {"ok": False, "status": "DELETE_FAILED", "message": f"删除归档记录失败: {exc}"}

    active_match_id = str(getattr(CURRENT_MATCH, "id", "") or "").strip()
    if record_id == active_match_id:
        return {
            "ok": False,
            "status": "ACTIVE_MATCH_GUARD",
            "message": "这是当前正在进行的对局，请通过结束本局 / 放弃本局处理。",
        }

    db_path = resolve_runtime_history_path()
    store = CanonicalHistoryStore(db_path)
    try:
        res = store.delete_record_transactional(record_id, active_match_id=active_match_id)
        try:
            from live_shadow import load_history_snapshot
            load_history_snapshot(str(db_path), force=True)
        except Exception:
            pass
        log_stage("ACTION:HISTORY", f"Record deleted successfully id={record_id} remaining={res.get('remainingCount')}")
        return {
            "ok": True,
            "status": "DELETED",
            "recordId": record_id,
            "isLegacy": False,
            "remainingCount": res.get("remainingCount"),
            "message": "记录已成功删除",
        }
    except Exception as exc:
        err_msg = str(exc)
        if "RECORD_NOT_FOUND" in err_msg:
            # Fallback: maybe it is a legacy record without prefix?
            try:
                from legacy_archive import LegacyArchive
                archive = LegacyArchive()
                res = archive.delete_record(record_id)
                return {
                    "ok": True,
                    "status": "DELETED",
                    "recordId": record_id,
                    "isLegacy": True,
                    "remainingCount": res.get("remainingCount"),
                    "message": "历史归档记录已成功删除",
                }
            except Exception:
                pass
            return {"ok": False, "status": "RECORD_NOT_FOUND", "message": "该记录不存在或已被删除"}
        if "ACTIVE_MATCH" in err_msg:
            return {
                "ok": False,
                "status": "ACTIVE_MATCH_GUARD",
                "message": "这是当前正在进行的对局，请通过结束本局 / 放弃本局处理。",
            }
        log_stage("ACTION:HISTORY", f"Failed to delete record id={record_id}: {exc}")
        return {"ok": False, "status": "DELETE_FAILED", "message": "删除记录失败，请稍后重试"}


def handle_delete_history_records(selections: Any) -> Dict[str, Any]:
    """Delete selected history records with one active-match preflight.

    The existing single-record handler remains the authority for each delete.
    This wrapper only normalizes the UI selection and prevents a batch from
    partially deleting records when it includes the active match.
    """
    if not isinstance(selections, list):
        return {"ok": False, "status": "SELECTIONS_INVALID", "message": "未提供有效的记录选择"}

    normalized: List[Dict[str, str]] = []
    seen = set()
    for item in selections:
        if isinstance(item, dict):
            record_id = str(item.get("recordId") or item.get("id") or "").strip()
            source = str(item.get("source") or "").strip().lower()
        else:
            record_id = str(item or "").strip()
            source = ""
        if not record_id:
            continue
        if not source:
            source = "legacy" if record_id.startswith("legacy:") else "current"
        key = (source, record_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"recordId": record_id, "source": source})

    if not normalized:
        return {"ok": False, "status": "NO_SELECTION", "message": "请先选择要删除的对局记录"}

    active_match_id = str(getattr(CURRENT_MATCH, "id", "") or "").strip()
    if any(
        item["source"] != "legacy" and item["recordId"] == active_match_id
        for item in normalized
    ):
        return {
            "ok": False,
            "status": "ACTIVE_MATCH_GUARD",
            "requestedCount": len(normalized),
            "deletedRecordIds": [],
            "failedRecords": [],
            "message": "所选记录包含当前正在进行的对局，未删除任何记录。",
        }

    deleted: List[str] = []
    failed: List[Dict[str, Any]] = []
    legacy_deleted = False
    for item in normalized:
        result = handle_delete_history_record(item["recordId"], source=item["source"])
        if isinstance(result, dict) and result.get("ok"):
            deleted.append(item["recordId"])
            legacy_deleted = legacy_deleted or bool(result.get("isLegacy"))
        else:
            failed.append({
                "recordId": item["recordId"],
                "source": item["source"],
                "status": result.get("status") if isinstance(result, dict) else "ERROR",
                "message": result.get("message") if isinstance(result, dict) else "删除失败",
            })

    if failed:
        status = "PARTIAL" if deleted else "ERROR"
        message = f"已删除 {len(deleted)} 条，{len(failed)} 条未删除。"
    else:
        status = "DELETED"
        message = f"已删除 {len(deleted)} 条对局记录。"
    return {
        "ok": not failed,
        "status": status,
        "requestedCount": len(normalized),
        "deletedCount": len(deleted),
        "deletedRecordIds": deleted,
        "failedRecords": failed,
        "legacyDeleted": legacy_deleted,
        "message": message,
    }

def apply_runtime_icon():
    """实时注入运行中窗口与 Dock/任务栏的专属看板娘高清图标"""
    ico_candidates = [
        os.path.join(BASE_DIR, "app_icon.ico"),
        os.path.join(BASE_DIR, "_internal", "app_icon.ico"),
        os.path.join(os.path.dirname(__file__), "app_icon.ico"),
        os.path.join(os.path.dirname(__file__), "..", "app", "app_icon.ico"),
    ]
    ico_path = next((p for p in ico_candidates if os.path.isfile(p)), None)
    if not ico_path:
        return
    for _ in range(25):
        time.sleep(0.2)
        try:
            hicon_big = win32gui.LoadImage(0, ico_path, win32con.IMAGE_ICON, 256, 256, win32con.LR_LOADFROMFILE)
            hicon_small = win32gui.LoadImage(0, ico_path, win32con.IMAGE_ICON, 32, 32, win32con.LR_LOADFROMFILE)
            
            def _enum_cb(hwnd, _):
                title = win32gui.GetWindowText(hwnd)
                if "异环" in title or "HUD" in title:
                    win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, hicon_big)
                    win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, hicon_small)
            
            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            pass

from window_tracker import GameWindowTracker
from window_capture import WindowCaptureManager

def load_config() -> Dict[str, Any]:
    cfg_path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

CONFIG = load_config()
WS_PORT = CONFIG.get("network", {}).get("wsPort", 8766)

_boot_replay_video = str(os.environ.get("NTE_REPLAY_VIDEO") or CONFIG.get("app", {}).get("replayVideo") or "").strip()
_boot_replay_frames_dir = str(os.environ.get("NTE_REPLAY_FRAMES_DIR") or "").strip()
if _boot_replay_frames_dir or _boot_replay_video:
    try:
        from frame_source import KeyframeDirectorySource, VideoCaptureSource
        _boot_source = (
            VideoCaptureSource(_boot_replay_video) if (_boot_replay_video and os.path.isfile(_boot_replay_video))
            else KeyframeDirectorySource(_boot_replay_frames_dir) if (_boot_replay_frames_dir and os.path.isdir(_boot_replay_frames_dir))
            else None
        )
        if _boot_source and hasattr(_boot_source, "content_fingerprint"):
            _boot_fp = _boot_source.content_fingerprint()
            if _boot_fp:
                CURRENT_MATCH.id = f"replayfile_{_boot_fp}"
                CURRENT_MATCH.data_origin = "replay"
                log_stage("STARTUP", f"Initialized replay session id={CURRENT_MATCH.id} dataOrigin=replay")
    except Exception as _boot_err:
        log_stage("STARTUP", f"Could not pre-initialize replay session: {_boot_err}")


CONNECTED_CLIENTS = set()
HUD_HWND = None
WS_EVENT_LOOP = None
WS_STOP_EVENT = None
_SHADOW_PRESENTATION_LOCK = threading.Lock()
_SHADOW_PRESENTATION_KEYS: Dict[str, str] = {}
# Bind a vision stream to one stable match-time boundary.  This is deliberately
# keyed by match id: replay frames carry their recorded capture time, while a
# live match uses the first capture boundary and never re-reads the wall clock
# for every subsequent frame.
_VISION_MATCH_PLAYED_AT: Dict[str, str] = {}

async def broadcast_ws(payload: str):
    dead = []
    for client in list(CONNECTED_CLIENTS):
        try:
            await client.send(payload)
        except Exception:
            dead.append(client)
    for client in dead:
        CONNECTED_CLIENTS.discard(client)


def _publish_live_shadow_event(event: Dict[str, Any]) -> None:
    """Publish a completed Shadow result without waiting for another frame.

    The vision worker already published the authoritative OCR/geometry facts.
    This callback only merges the completed, non-stale valuation sidecar into
    the latest presentation payload, so an unrelated heavy OCR/identity pass
    cannot delay the first legal price display.
    """
    if not isinstance(event, dict):
        return
    match_id = str(event.get("matchId") or "").strip()
    snapshot = event.get("predictionSnapshot")
    profile = event.get("probabilityProfile")
    if not match_id or (not isinstance(snapshot, dict) and profile is None):
        return
    if isinstance(snapshot, dict) and str(snapshot.get("matchId") or "").strip() != match_id:
        return
    current = globals().get("CURRENT_MATCH")
    if current is None or str(getattr(current, "id", "")) != match_id:
        return
    payload = globals().get("LATEST_PAYLOAD")
    if not isinstance(payload, dict) or payload.get("scene") != "IN_AUCTION":
        return
    if _live_vision_presentation_active() and event.get("presentationSource") not in {"live_vision", "live_hud"}:
        # A manual/replay Shadow request queued before live takeover may finish
        # later with the same match id. It cannot replace live facts.
        return
    prediction_id = str(
        (snapshot or {}).get("predictionId")
        or (snapshot or {}).get("inputHash")
        or event.get("shadowGen")
        or ""
    )
    dedupe_key = f"{match_id}:{prediction_id}"
    with _SHADOW_PRESENTATION_LOCK:
        if _SHADOW_PRESENTATION_KEYS.get(match_id) == dedupe_key:
            return
        _SHADOW_PRESENTATION_KEYS[match_id] = dedupe_key
    with _MANUAL_STATE_LOCK:
        merged = dict(payload)
        shadow_meta = event.get("shadowMeta") or {
            "cache": "completed",
            "shadowUpdating": False,
        }
        shadow_states = event.get("shadowStates")
        merged.update({
            "probabilityProfile": profile,
            "predictionSnapshot": snapshot,
            "frozenPrediction": event.get("frozenPrediction"),
            "shadowMeta": shadow_meta,
            "shadowStates": shadow_states,
            "shadowUpdating": False,
        })
        # Manual/Overlay payloads keep the canonical Solver input under
        # solverInput.  Publishing only the top-level Shadow sidecar leaves
        # the WebView solving the old pending/structural input even though a
        # completed full-shadow result is already available.  Merge the
        # accepted same-match result into that nested input as one presentation
        # transaction; this does not change Solver inputs or History ownership.
        nested_solver_input = merged.get("solverInput")
        if isinstance(nested_solver_input, dict):
            nested_match_id = str(nested_solver_input.get("matchId") or match_id).strip()
            if nested_match_id == match_id:
                nested_solver_input = dict(nested_solver_input)
                nested_solver_input.update({
                    "probabilityProfile": profile,
                    "predictionSnapshot": snapshot,
                    "frozenPrediction": event.get("frozenPrediction"),
                    "shadowMeta": shadow_meta,
                    "shadowStates": shadow_states,
                    "shadowUpdating": False,
                })
                merged["solverInput"] = nested_solver_input
                profile_coverage = float((profile or {}).get("coverageRatio") or 0.0)
                if profile_coverage >= 0.999999 and (profile or {}).get("shadowWhole"):
                    support_status = "HISTORICAL_SUPPORTED"
                    support_reasons = []
                elif profile_coverage > 0:
                    support_status = "PARTIAL_HISTORICAL_SUPPORT"
                    support_reasons = ["PARTIAL_HISTORY_COVERAGE"]
                else:
                    support_status = "STRUCTURAL_ONLY"
                    support_reasons = ["NO_MATCHING_HISTORY_SUPPORT"]
                previous_support = merged.get("shadowSupport")
                if isinstance(previous_support, dict):
                    support_reasons.extend(
                        reason for reason in (previous_support.get("reasonCodes") or [])
                        if reason not in {
                            "HISTORICAL_PROFILE_PENDING",
                            "PARTIAL_HISTORY_COVERAGE",
                            "NO_MATCHING_HISTORY_SUPPORT",
                        }
                    )
                merged["shadowSupport"] = {
                    "status": support_status,
                    "reasonCodes": list(dict.fromkeys(support_reasons)),
                    "historyN": int(shadow_meta.get("historyN") or 0),
                    "coverageRatio": profile_coverage,
                }
        if isinstance(snapshot, dict):
            ACTIVE_SNAPSHOT_HOLDER.update(match_id, snapshot=snapshot, frozen_prediction=event.get("frozenPrediction"))
        LATEST_PAYLOAD.update(merged)
    loop = WS_EVENT_LOOP
    if loop is not None and loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(
                broadcast_ws(json.dumps(merged, ensure_ascii=False)),
                loop,
            )
        except Exception as exc:
            log_stage("PRESENTATION:SHADOW", f"completed result broadcast failed: {exc}")

_LAST_FORCE_REFRESH_TS = 0.0
_REFRESH_SEQ = 0
_REFRESH_LOCK = threading.Lock()

def _next_refresh_id() -> str:
    global _REFRESH_SEQ
    with _REFRESH_LOCK:
        _REFRESH_SEQ += 1
        seq = _REFRESH_SEQ
    return f"r{seq:04d}-{uuid.uuid4().hex[:6]}"

def request_force_refresh(request_id: Optional[str] = None) -> Optional[str]:
    """开一个新的刷新事务。每次点击都分配 request id，不再等当前 OCR 跑完。"""
    global _LAST_FORCE_REFRESH_TS
    now = time.time()
    rid = request_id or _next_refresh_id()
    _LAST_FORCE_REFRESH_TS = now
    PRESENTATION_RUNTIME.begin_refresh(rid)
    log_stage("ACTION:USER", f"User requested manual force_refresh request_id={rid}")
    pending_payload = {
        "action": "force_refresh",
        "refreshRequestId": rid,
        "refreshPending": True,
        "solverStatus": "refreshing",
        "scene": "AUCTION_LOBBY",
        "inLobby": True,
        "inAuction": False,
        "isLoading": False,
        "lobbyCharacter": None,
        "lobbyCharacterLabel": "识别中",
        "actionDirective": "🔄 正在识别当前画面",
        "actionReason": f"刷新事务 {rid}",
        "timestamp": now,
    }
    LATEST_PAYLOAD.update(pending_payload)
    if WS_EVENT_LOOP and WS_EVENT_LOOP.is_running():
        try:
            asyncio.run_coroutine_threadsafe(
                broadcast_ws(json.dumps(pending_payload)),
                WS_EVENT_LOOP,
            )
        except Exception as e:
            log_stage("ACTION:USER", f"force_refresh broadcast failed request_id={rid}: {e}")
    return rid

def _log_overlay_host_state(hwnd, tag: str = "") -> None:
    try:
        GWL_EXSTYLE = -20
        GW_OWNER = 4
        ex = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
        owner = win32gui.GetWindow(hwnd, GW_OWNER)
        owner_title = win32gui.GetWindowText(owner) if owner else ""
        fg = win32gui.GetForegroundWindow()
        fg_title = win32gui.GetWindowText(fg) if fg else ""
        noact = bool(ex & 0x08000000)
        log_stage(
            "STARTUP:HUD",
            f"host {tag} hwnd={int(hwnd)} exStyle=0x{ex:X} WS_EX_NOACTIVATE={noact} "
            f"owner={int(owner) if owner else 0} ownerTitle={owner_title or '-'} "
            f"fg={int(fg) if fg else 0} fgTitle={fg_title or '-'}",
        )
    except Exception as e:
        log_stage("STARTUP:HUD", f"host state log failed: {e}")


def get_hud_hwnd():
    global HUD_HWND
    if HUD_HWND and win32gui.IsWindow(HUD_HWND):
        return HUD_HWND
    def _enum_cb(h, _):
        global HUD_HWND
        title = win32gui.GetWindowText(h)
        if "异环" in title and "HUD" in title:
            HUD_HWND = h
    win32gui.EnumWindows(_enum_cb, None)
    return HUD_HWND

def move_hud_async(dx: int, dy: int):
    """通过 Windows DWM 异步硬件坐标置位 (0 死锁、0 阻塞、极致丝滑)"""
    h = get_hud_hwnd()
    if h:
        try:
            rect = win32gui.GetWindowRect(h)
            # 0x4015 = SWP_NOSIZE (0x0001) | SWP_NOZORDER (0x0004) | SWP_NOACTIVATE (0x0010) | SWP_ASYNCWINDOWPOS (0x4000)
            win32gui.SetWindowPos(h, 0, rect[0] + dx, rect[1] + dy, 0, 0, 0x4015)
        except Exception:
            pass

async def ws_handler(websocket):
    global _LIVE_WORKER_SOCKET, _LIVE_CONTROL_WAITING_EXIT
    global _LIVE_VISION_ACTIVE, _LIVE_VISION_MATCH_ID
    from live_match_transport import LiveMatchReceiver
    live_receiver = LiveMatchReceiver()
    CONNECTED_CLIENTS.add(websocket)
    log_stage("STARTUP:WS", "WebSocket client connected")
    try:
        if LATEST_PAYLOAD:
            try:
                await websocket.send(json.dumps(LATEST_PAYLOAD))
            except Exception:
                pass
        async for msg in websocket:
            try:
                data = json.loads(msg)
                msg_type = data.get("type")
                if msg_type == "vision_worker_hello":
                    previous_worker = _LIVE_WORKER_SOCKET
                    _LIVE_WORKER_SOCKET = websocket
                    if previous_worker is not None and previous_worker is not websocket:
                        await previous_worker.close()
                    with _MANUAL_STATE_LOCK:
                        resume = {"action": "worker_resume", "revision": _LIVE_CONTROL_REVISION,
                                  "snapshot": CURRENT_MATCH.snapshot(),
                                  "facts": dict(_LIVE_MANUAL_OVERRIDES),
                                  "reset": _LIVE_CONTROL_WAITING_EXIT}
                    await websocket.send(json.dumps(resume, ensure_ascii=False))
                elif msg_type == "prediction_archive_request":
                    if websocket is not _LIVE_WORKER_SOCKET:
                        continue
                    response = collect_gui_archive_prediction(data)
                    await websocket.send(json.dumps(response, ensure_ascii=False))
                elif msg_type == "report_hud_status":
                    status = data.get("status", {})
                    log_stage("STARTUP:HUD", "HUD window appeared: True")
                    log_stage("STARTUP:HUD", f"pywebview/WebView2 ready: {status.get('pywebviewReady', True)}")
                    log_stage("STARTUP:HUD", f"auction_engine_v06.js loaded: {status.get('auctionEngineLoaded')}")
                    st = status.get("sharedCoreSelfTests", {})
                    log_stage("STARTUP:HUD", f"Shared Core self-test result: {st.get('tested', 0)} tests, passed={st.get('passed', False)}")
                    log_stage("STARTUP:HUD", f"15:53 regression result: {'PASS' if status.get('regression1553Passed') else 'FAIL'}")
                    log_stage("STARTUP:HUD", "WebSocket ready: True")
                    log_stage("STARTUP:HUD", "HUD responsive: True")
                    log_stage("STARTUP:HUD", f"startup duration: {(time.perf_counter() - PROCESS_START_TIME) * 1000:.2f}ms")
                    start_vision_worker()
                elif msg_type == "force_refresh":
                    request_force_refresh(data.get("refreshRequestId") or data.get("requestId"))
                elif msg_type == "start_live_vision":
                    start_vision_worker()
                elif msg_type == "drag_delta":
                    dx = int(data.get("dx", 0))
                    dy = int(data.get("dy", 0))
                    if dx != 0 or dy != 0:
                        move_hud_async(dx, dy)
                elif msg_type in ("manual_facts", "manual_finalize", "manual_next_match", "manual_bootstrap", "triggered_snapshot", "capture_hud", "resize_hud", "capture_overlay_preview", "eval_overlay_js", "eval_main_js"):
                    if msg_type == "resize_hud":
                        continue
                    if msg_type in ("triggered_snapshot", "capture_hud"):
                        payload = handle_triggered_snapshot()
                        await websocket.send(json.dumps(payload, ensure_ascii=False))
                        continue
                    if msg_type == "capture_overlay_preview":
                        api = HUD_JS_API
                        saved = api.capture_overlay_preview(data.get("path")) if api else None
                        await websocket.send(json.dumps({"type": "overlay_preview_saved", "path": saved}, ensure_ascii=False))
                        continue
                    if msg_type == "eval_overlay_js":
                        api = HUD_JS_API
                        result = api.eval_overlay_js(data.get("script")) if api else None
                        await websocket.send(json.dumps({"type": "overlay_js_result", "result": result}, ensure_ascii=False))
                        continue
                    if msg_type == "eval_main_js":
                        api = HUD_JS_API
                        result = api.eval_main_js(data.get("script")) if api else None
                        await websocket.send(json.dumps({"type": "main_js_result", "result": result}, ensure_ascii=False))
                        continue
                    if msg_type == "manual_bootstrap" and _live_vision_presentation_active():
                        # Overlay sends manual_bootstrap on every reconnect. Once
                        # live vision has taken ownership, it must not replace the
                        # authoritative vision payload with the legacy manual one.
                        if LATEST_PAYLOAD:
                            await websocket.send(json.dumps(dict(LATEST_PAYLOAD), ensure_ascii=False))
                        continue
                    if msg_type in ("manual_finalize", "manual_next_match") and _live_vision_presentation_active():
                        if LATEST_PAYLOAD:
                            await websocket.send(json.dumps(dict(LATEST_PAYLOAD), ensure_ascii=False))
                        continue
                    if msg_type == "manual_finalize":
                        payload = finalize_manual_match(data)
                    elif msg_type == "manual_next_match":
                        payload = begin_next_manual_match(data)
                    elif msg_type == "manual_bootstrap":
                        payload = build_manual_alpha_payload()
                    else:
                        payload = apply_manual_facts(data)
                    await broadcast_ws(json.dumps(payload, ensure_ascii=False))
                else:
                    if isinstance(data, dict):
                        if data.get('type') == 'vision_health':
                            if websocket is not _LIVE_WORKER_SOCKET:
                                continue
                            health = data.get('visionHealth')
                            if not isinstance(health, dict) or health.get('status') not in ('ERROR', 'READY', 'WAITING'):
                                continue
                            LATEST_PAYLOAD['visionHealth'] = dict(health)
                            await broadcast_ws(json.dumps({'type': 'vision_health', 'visionHealth': health}))
                            continue
                        if "visionState" in data:
                            if websocket is not _LIVE_WORKER_SOCKET:
                                continue
                            with _MANUAL_STATE_LOCK:
                                previous_match_id = CURRENT_MATCH.id
                                if not live_receiver.apply(data["visionState"], CURRENT_MATCH, _LIVE_CONTROL_REVISION):
                                    continue
                                if CURRENT_MATCH.id != previous_match_id:
                                    _LIVE_MANUAL_OVERRIDES.clear()
                                _LIVE_CONTROL_WAITING_EXIT = data["visionState"].get("controlPendingExit") is True
                                LATEST_PAYLOAD.pop("manualControl", None)
                                _LIVE_VISION_MATCH_ID = CURRENT_MATCH.id
                                _LIVE_VISION_ACTIVE = data.get("scene") not in _LIVE_VISION_EXIT_SCENES
                        if "visionState" in data:
                            LATEST_VISION_PAYLOAD.clear()
                            LATEST_VISION_PAYLOAD.update(data)
                        data["recognitionMode"] = get_recognition_mode()
                        PRESENTATION_RUNTIME.observe_transport(data)
                        LATEST_PAYLOAD.update(data)
                        if "visionState" in data:
                            sync_vision_to_current_match(data)
                            overlay_state = build_canonical_overlay_state(CURRENT_MATCH, data)
                            data["overlayState"] = overlay_state
                            _sync_payload_with_canonical_facts(data, CURRENT_MATCH)
                            data, prediction_message = attach_gui_prediction(data)
                            if prediction_message is not None:
                                await websocket.send(json.dumps(prediction_message, ensure_ascii=False))
                            # Native capture/safety callbacks belong to the GUI process.
                            maybe_trigger_auto_warehouse_capture(data)
                            data = attach_warehouse_capture_presentation(data)
                            LATEST_PAYLOAD.update(data)
                            msg = json.dumps(data, ensure_ascii=False)
                        if data.get("scene") in _LIVE_VISION_EXIT_SCENES:
                            _LIVE_VISION_ACTIVE = False
                            _LIVE_VISION_MATCH_ID = None
                            # Do not hand a retired vision envelope to a later
                            # manual/replay session on the same process.
                            LATEST_PAYLOAD.pop("visionState", None)
                            LATEST_PAYLOAD.pop("predictionSnapshot", None)
                            LATEST_PAYLOAD.pop("frozenPrediction", None)
                        for client in list(CONNECTED_CLIENTS):
                            if client != websocket:
                                try:
                                    await client.send(msg)
                                except Exception:
                                    pass
            except Exception as e:
                log_stage("STARTUP:WS", f"WS message error: {e}")
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if _LIVE_WORKER_SOCKET is websocket:
            _LIVE_WORKER_SOCKET = None
        CONNECTED_CLIENTS.discard(websocket)

def start_ws_loop():
    global WS_EVENT_LOOP, WS_STOP_EVENT
    async def _runner():
        global WS_EVENT_LOOP, WS_STOP_EVENT
        from live_shadow import register_prediction_listener

        register_prediction_listener(_publish_live_shadow_event)
        WS_EVENT_LOOP = asyncio.get_running_loop()
        WS_STOP_EVENT = asyncio.Event()
        log_stage("STARTUP:WS", f"WebSocket bus starting on ws://127.0.0.1:{WS_PORT}...")
        async with websockets.serve(ws_handler, "127.0.0.1", WS_PORT, max_size=16 * 1024 * 1024):
            log_stage("STARTUP:WS", f"WebSocket bus ready on ws://127.0.0.1:{WS_PORT}")
            await WS_STOP_EVENT.wait()
    try:
        asyncio.run(_runner())
    except Exception as e:
        log_stage("STARTUP:WS", f"WebSocket bus error: {e}")
    finally:
        WS_EVENT_LOOP = None
        WS_STOP_EVENT = None


def stop_ws_loop():
    loop = WS_EVENT_LOOP
    stop_event = WS_STOP_EVENT
    if loop and loop.is_running() and stop_event is not None:
        loop.call_soon_threadsafe(stop_event.set)

def format_val_w(val: Optional[int]) -> str:
    if val is None:
        return "计算中..."
    return f"{val / 10000.0:.1f} W"


def _manual_options() -> Dict[str, Any]:
    venues = []
    for venue in catalog_manual_options(VENUE_BOX_CATALOG):
        venues.append({
            "venueId": venue["venueId"],
            "displayName": venue["displayName"],
            "entryCost": venue["entryCost"],
            "venueEvidenceClass": venue["venueEvidenceClass"],
            "boxes": [dict(box) for box in venue["boxes"]],
        })
    return {
        "catalogVersion": VENUE_BOX_CATALOG["catalogVersion"],
        "catalogApprovalStatus": VENUE_BOX_CATALOG["catalogStatus"],
        "venues": venues,
        "fieldConditions": [
            {"id": "standard", "name": "标准对局"},
            {"id": "dark", "name": "天黑了"},
            {"id": "extraIntel", "name": "一手情报"},
            {"id": "purpleDouble", "name": "加倍！！"},
            {"id": "goldDouble", "name": "加倍！！！"},
            {"id": "sparkle", "name": "闪耀之心"},
            {"id": "welfare", "name": "福利多多"},
            {"id": "gemMaze", "name": "宝石迷阵"},
        ],
    }


def _canonical_from_current_match() -> Dict[str, Any]:
    return CURRENT_MATCH.to_canonical()


_DRAFT_TIMER: Optional[threading.Timer] = None
_DRAFT_LOCK = threading.Lock()
_MANUAL_STATE_LOCK = threading.RLock()
_LIVE_CONTROL_REVISION = 0
_LIVE_WORKER_SOCKET = None
_LIVE_MANUAL_OVERRIDES = {}
_LIVE_CONTROL_WAITING_EXIT = False
_MANUAL_MATCH_PLAYED_AT: Dict[str, str] = {}
_CAPTURE_SOURCE_INSTANCE_ID = f"desktop_{uuid.uuid4().hex}"
_LIVE_VISION_ACTIVE = False
_LIVE_VISION_MATCH_ID: Optional[str] = None
_LIVE_VISION_EXIT_SCENES = frozenset({
    "CITY_TYCOON_HUB",
    "CITY_LEISURE_MENU",
    "OPEN_WORLD",
})


def _live_vision_presentation_active() -> bool:
    """Whether the current match is owned by the live vision authority."""
    return bool(_LIVE_VISION_ACTIVE and _LIVE_VISION_MATCH_ID == CURRENT_MATCH.id)


def make_live_control_command(expected_id, *, facts=None, reset=False, cleared_fields=None, restore_auto_fields=None):
    global _LIVE_CONTROL_REVISION, _LIVE_CONTROL_WAITING_EXIT
    _LIVE_CONTROL_REVISION += 1
    if reset:
        _LIVE_MANUAL_OVERRIDES.clear()
        _LIVE_CONTROL_WAITING_EXIT = True
    else:
        for key in (restore_auto_fields or []):
            _LIVE_MANUAL_OVERRIDES.pop(key, None)
        for key, value in (facts or {}).items():
            if key in (cleared_fields or []):
                _LIVE_MANUAL_OVERRIDES[key] = value
            elif value is None or value == "":
                continue
            else:
                _LIVE_MANUAL_OVERRIDES[key] = value
        for key in (cleared_fields or []):
            _LIVE_MANUAL_OVERRIDES[key] = None
    command = {"revision": _LIVE_CONTROL_REVISION, "expectedMatchId": expected_id,
               "snapshot": CURRENT_MATCH.snapshot(), "facts": facts or {}, "reset": reset}
    if cleared_fields:
        command["clearedFields"] = list(cleared_fields)
    if restore_auto_fields:
        command["restoreAutoFields"] = list(restore_auto_fields)
    return command


def _manual_draft_record() -> Dict[str, Any]:
    canonical = _canonical_from_current_match()
    snap = CURRENT_MATCH.snapshot()
    manual_played_at = _MANUAL_MATCH_PLAYED_AT.get(str(snap.get("id") or ""))
    record = {
        **canonical,
        "id": snap["id"],
        "lifecycleStatus": "DRAFT",
        "source": "manual",
        "fillDefaults": False,
        "playedAt": manual_played_at or snap.get("updatedAt") or snap.get("createdAt"),
        "updatedAt": snap.get("updatedAt"),
        "q": snap.get("q"),
        "goldAvg": snap.get("goldAvg"),
        "purpleCount": snap.get("purpleCount"),
        **{key: snap.get(key) for key in ('blueCount', 'goldCount', 'redCount', 'totalItems', 'purpleAvg', 'totalGrid', 'goldGrid', 'purpleGrid', 'whiteCount', 'whiteAvg', 'whiteGrid', 'greenCount', 'greenAvg', 'greenGrid', 'blueAvg', 'blueGrid', 'redGrid')},
        "purple": snap.get("purpleCount"),
        "box": snap.get("box"),
        "fieldCondition": snap.get("fieldCondition"),
        "knownGold": snap.get("knownGold") or "",
        "knownPurple": snap.get("knownPurple") or "",
        **{key: snap.get(key) for key in ("privateBidCap", "bidActionCount")},
        "welfareReceived": snap.get("welfareReceived"),
        "freeIntelStatus": free_intel_status(snap),
        "hiddenBids": bids_hidden_now(snap),
        "sessionAccounting": accounting_from_facts(snap),
        "sparkle": snap.get("sparkle"),
        "knownBlue": snap.get("knownBlue") or "",
        "knownGreen": snap.get("knownGreen") or "",
        "knownWhite": snap.get("knownWhite") or "",

        "knownRed": snap.get("knownRed") or "",
    }
    prediction_snapshot = ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match(snap["id"])
    if isinstance(prediction_snapshot, dict):
        record["predictionSnapshot"] = prediction_snapshot
    return record


_LAST_DRAFT_WRITE = None
_DRAFT_WRITE_FAILED = False


def draft_write_status():
    if not DRAFT_ARCHIVER.db_paths:
        return "UNAVAILABLE"
    if _LAST_DRAFT_WRITE == (CURRENT_MATCH.id, CURRENT_MATCH.facts_revision):
        return "SAVED"
    return "FAILED" if _DRAFT_WRITE_FAILED else "PENDING"


def _persist_current_draft_now() -> Optional[Dict[str, Any]]:
    global _DRAFT_TIMER, _LAST_DRAFT_WRITE, _DRAFT_WRITE_FAILED
    with _DRAFT_LOCK:
        _DRAFT_TIMER = None
    with _MANUAL_STATE_LOCK:
        if not DRAFT_ARCHIVER.db_paths:
            return None
        if not CURRENT_MATCH.has_any_fact() and not (
                _LAST_DRAFT_WRITE and _LAST_DRAFT_WRITE[0] == CURRENT_MATCH.id):
            return None
        written = DRAFT_ARCHIVER.save_draft(_manual_draft_record())
        _DRAFT_WRITE_FAILED = written is None
        if written is not None:
            _LAST_DRAFT_WRITE = (CURRENT_MATCH.id, CURRENT_MATCH.facts_revision)
        if (LATEST_PAYLOAD.get("type") == "manual_alpha_state"
                and LATEST_PAYLOAD.get("matchId") == CURRENT_MATCH.id):
            payload = {**LATEST_PAYLOAD, "draftSaved": draft_write_status() == "SAVED",
                       "draftSaveStatus": draft_write_status()}
            LATEST_PAYLOAD.update(payload)
            publish_manual_payload(payload)
        return written


def schedule_draft_save(delay_sec: float = 0.5):
    global _DRAFT_TIMER
    with _DRAFT_LOCK:
        if _DRAFT_TIMER:
            _DRAFT_TIMER.cancel()
        _DRAFT_TIMER = threading.Timer(delay_sec, _persist_current_draft_now)
        _DRAFT_TIMER.daemon = True
        _DRAFT_TIMER.start()


def cancel_draft_save():
    """Cancel and clear any pending asynchronous draft save timer."""
    global _DRAFT_TIMER
    with _DRAFT_LOCK:
        if _DRAFT_TIMER:
            _DRAFT_TIMER.cancel()
            _DRAFT_TIMER = None


def flush_draft_save_sync() -> Optional[Dict[str, Any]]:
    global _DRAFT_TIMER
    with _DRAFT_LOCK:
        if _DRAFT_TIMER:
            _DRAFT_TIMER.cancel()
            _DRAFT_TIMER = None
    if CURRENT_MATCH.has_any_fact() or (_LAST_DRAFT_WRITE and _LAST_DRAFT_WRITE[0] == CURRENT_MATCH.id):
        return _persist_current_draft_now()
    return None


def build_manual_alpha_payload(include_solver_input: bool = True) -> Dict[str, Any]:
    snap = CURRENT_MATCH.snapshot()
    canonical = _canonical_from_current_match()
    solver_input: Dict[str, Any] = {}
    compatibility = {
        "status": "MISSING_VENUE",
        "boxStatus": "UNKNOWN_NO_BOX_EFFECT",
        "boxSemantic": "NO_BOX_EFFECT",
    }
    shadow_support = {
        "status": "STRUCTURAL_ONLY",
        "reasonCodes": ["MISSING_VENUE"],
        "historyN": None,
        "coverageRatio": 0.0,
    }
    shadow_updating = False
    if include_solver_input and snap.get("venueId"):
        compatibility = dict(solver_context_translation(
            VENUE_BOX_CATALOG,
            venue_id=snap.get("venueId"),
            box_id=snap.get("boxId"),
        ))
        if compatibility.get("status") == "COMPATIBILITY_TRANSLATION":
            solver_input = canonical_to_v06_solver_input(canonical)
            solver_input.update({
                "matchId": snap["id"],
                "playedAt": _MANUAL_MATCH_PLAYED_AT.get(str(snap.get("id") or "")) or snap.get("createdAt"),
                "scene": "IN_AUCTION",
                "inAuction": True,
                "venue": compatibility.get("venue"),
                "box": compatibility.get("box"),
                "leaderBid": snap.get("leaderBid"),
                "targetProfit": MANUAL_VISIBLE_TARGET_PROFIT_DEFAULT,
                "codeRevision": get_code_revision(),
            })
            try:
                from live_shadow import (
                    attach_live_shadow,
                    get_live_dataset_revision,
                    load_history_snapshot,
                )
                records = load_history_snapshot(CANONICAL_DATABASE)
                revision = get_live_dataset_revision(CANONICAL_DATABASE)
                solver_input["datasetRevision"] = revision
                support_record_n = int(revision.get("supportEligibleRecordCount") or 0)
                # Catalog feasibility is useful even before the first eligible history record.
                solver_input = attach_live_shadow(solver_input, db_path=CANONICAL_DATABASE)
                if isinstance(solver_input.get("predictionSnapshot"), dict) and not solver_input.get("shadowUpdating"):
                    ACTIVE_SNAPSHOT_HOLDER.update(snap["id"], snapshot=solver_input["predictionSnapshot"], frozen_prediction=solver_input.get("frozenPrediction"))
                shadow_updating = bool(solver_input.get("shadowUpdating"))
                profile = solver_input.get("probabilityProfile") or {}
                meta = solver_input.get("shadowMeta") or {}
                coverage = float(profile.get("coverageRatio") or 0.0)
                history_n = int(meta.get("historyN") or 0)
                if support_record_n == 0:
                    support_status = "STRUCTURAL_ONLY"
                    reason_codes = ["INSUFFICIENT_HISTORY"]
                elif coverage >= 0.999999 and profile.get("shadowWhole"):
                    support_status = "HISTORICAL_SUPPORTED"
                    reason_codes = []
                elif coverage > 0:
                    support_status = "PARTIAL_HISTORICAL_SUPPORT"
                    reason_codes = ["PARTIAL_HISTORY_COVERAGE"]
                elif shadow_updating:
                    support_status = "SUPPORT_UPDATING"
                    reason_codes = ["HISTORICAL_PROFILE_PENDING"]
                else:
                    support_status = "STRUCTURAL_ONLY"
                    reason_codes = ["NO_MATCHING_HISTORY_SUPPORT"]
                if compatibility.get("boxStatus") == "UNKNOWN_NO_BOX_EFFECT":
                    reason_codes.append("UNKNOWN_BOX")
                shadow_support = {
                    "status": support_status,
                    "reasonCodes": reason_codes,
                    "historyN": history_n,
                    "coverageRatio": coverage,
                }
            except Exception as exc:
                log_stage("MANUAL:SHADOW", f"history support unavailable: {type(exc).__name__}")
                solver_input["probabilityProfile"] = None
                solver_input["shadowUpdating"] = False
                shadow_support = {
                    "status": "STRUCTURAL_ONLY",
                    "reasonCodes": ["HISTORY_UNAVAILABLE"],
                    "historyN": None,
                    "coverageRatio": 0.0,
                }
        else:
            shadow_support = {
                "status": "UNAVAILABLE",
                "reasonCodes": [str(compatibility.get("status") or "COMPATIBILITY_INVALID")],
                "historyN": None,
                "coverageRatio": 0.0,
            }
    return {
        "type": "manual_alpha_state",
        "recognitionMode": get_recognition_mode(),
        "configuredPlayerName": get_player_name(),
        "source": "manual",
        "fillDefaults": False,
        "manualMode": True,
        "inAuction": True,
        "scene": "IN_AUCTION",
        "sceneLabel": "手动局",
        "matchId": snap["id"],
        "lifecycleStatus": "DRAFT",
        "q": snap.get("q"),
        "goldAvg": snap.get("goldAvg"),
        "avg": snap.get("goldAvg"),
        "purple": snap.get("purpleCount"),
        "purpleCount": snap.get("purpleCount"),
        **{key: snap.get(key) for key in ('blueCount', 'goldCount', 'redCount', 'totalItems', 'purpleAvg', 'totalGrid', 'goldGrid', 'purpleGrid', 'whiteCount', 'whiteAvg', 'whiteGrid', 'greenCount', 'greenAvg', 'greenGrid', 'blueAvg', 'blueGrid', 'redGrid')},
        "venueId": snap.get("venueId"),
        "venueTier": None,
        "venue": snap.get("venue"),
        "boxId": snap.get("boxId"),
        "box": snap.get("box"),
        "fieldCondition": snap.get("fieldCondition") or "standard",
        "knownGold": snap.get("knownGold") or "",
        "knownPurple": snap.get("knownPurple") or "",
        **{key: snap.get(key) for key in ("privateBidCap", "bidActionCount")},
        "welfareReceived": snap.get("welfareReceived"),
        "freeIntelStatus": free_intel_status(snap),
        "hiddenBids": bids_hidden_now(snap),
        "sessionAccounting": accounting_from_facts(snap),
        "sparkle": snap.get("sparkle"),
        "knownBlue": snap.get("knownBlue") or "",
        "knownGreen": snap.get("knownGreen") or "",
        "knownWhite": snap.get("knownWhite") or "",

        "knownRed": snap.get("knownRed") or "",
        "leaderBid": snap.get("leaderBid"),
        "targetProfit": MANUAL_VISIBLE_TARGET_PROFIT_DEFAULT,
        "targetProfitSource": "NO_MINIMUM_PROFIT",
        **{key: snap.get(key) for key in ("intelCost", "otherCost", "futureIncrementalCost")},
        "manualOptions": _manual_options(),
        "canonical": canonical,
        "costSummary": describe_costs(canonical.get("costs")),
        "solverInput": solver_input,
        "solverCompatibility": compatibility,
        "solverAvailability": (
            "AVAILABLE" if solver_input else "UNAVAILABLE"
        ),
        "shadowSupport": shadow_support,
        "shadowUpdating": shadow_updating,
        "draftSaved": draft_write_status() == "SAVED",
        "draftSaveStatus": draft_write_status(),
        "factsRevision": snap.get("factsRevision"),
        "fieldStates": snap.get("fieldStates") or {},
    }


def _manual_patch_has_content(patch: Dict[str, Any]) -> bool:
    if not patch:
        return False
    for key, value in patch.items():
        if value in (None, ""):
            continue
        return True
    return False


def apply_manual_facts(facts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    with _MANUAL_STATE_LOCK:
        previous_facts = dict(CURRENT_MATCH.facts)
        raw_data = dict(facts or {})
        patch = dict(raw_data.get("facts") or raw_data)
        cleared_fields = [key for key in (raw_data.get("clearedFields") or patch.pop("clearedFields", []) or []) if isinstance(key, str)]
        restore_auto_fields = [key for key in (raw_data.get("restoreAutoFields") or patch.pop("restoreAutoFields", []) or []) if isinstance(key, str)]
        intent = raw_data.get("intent") or patch.pop("intent", None)
        if "recognitionMode" in patch:
            set_recognition_mode(patch.pop("recognitionMode"))
        if "configuredPlayerName" in patch:
            set_player_name(patch.pop("configuredPlayerName"))
        explicit_played_at = patch.get("playedAt")
        if isinstance(explicit_played_at, str) and explicit_played_at.strip():
            _MANUAL_MATCH_PLAYED_AT.setdefault(CURRENT_MATCH.id, explicit_played_at.strip())
        snap = raw_data.get("predictionSnapshot")
        frozen = raw_data.get("frozenPrediction")
        if snap or frozen:
            ACTIVE_SNAPSHOT_HOLDER.update(CURRENT_MATCH.id, snapshot=snap, frozen_prediction=frozen)

        input_issues = []
        for key in ("leaderBid", "targetProfit", "intelCost", "otherCost", "futureIncrementalCost"):
            if key not in patch or patch.get(key) in (None, ""):
                continue
            raw_value = patch.get(key)
            try:
                number = float(str(raw_value).replace(",", ""))
            except (TypeError, ValueError):
                number = -1
            if isinstance(raw_value, bool) or not number.is_integer() or number < 0:
                input_issues.append(
                    "INVALID_CURRENT_BID" if key == "leaderBid" else "INVALID_TARGET_PROFIT" if key == "targetProfit" else "INVALID_COST"
                )
        if input_issues:
            payload = build_manual_alpha_payload()
            payload["manualInputIssues"] = input_issues
            payload["draftSaved"] = draft_write_status() == "SAVED"
            LATEST_PAYLOAD.update(payload)
            return payload

        explicit_unknown_box = patch.get("boxUnknown") is True or patch.get("box") in ("未知/其他", "未知 / 其他")
        if explicit_unknown_box:
            for key in ("box", "boxId"):
                if key not in cleared_fields:
                    cleared_fields.append(key)
        env_edited = any(
            key in patch and not is_missing_observation(key, patch.get(key))
            for key in ("venueId", "boxId", "venue", "box")
        ) or explicit_unknown_box or any(key in cleared_fields for key in ("venueId", "boxId", "venue", "box"))
        if env_edited:
            venue_id = patch.get("venueId")
            if not venue_id and patch.get("venue"):
                norm_v = normalize_vision_venue(VENUE_BOX_CATALOG, patch.get("venue"))
                if norm_v.get("status") == "NORMALIZED":
                    venue_id = norm_v.get("venueId")
            if not venue_id:
                venue_id = CURRENT_MATCH.facts.get("venueId")

            box_id = patch.get("boxId")
            if not box_id and patch.get("box") and venue_id:
                norm_b = normalize_vision_box(VENUE_BOX_CATALOG, venue_id=venue_id, observation=patch.get("box"))
                if norm_b.get("status") == "NORMALIZED":
                    box_id = norm_b.get("boxId")
            if not box_id and not patch.get("box") and not explicit_unknown_box:
                box_id = CURRENT_MATCH.facts.get("boxId")

            if explicit_unknown_box:
                box_id = None
            try:
                selection = catalog_selection(VENUE_BOX_CATALOG, venue_id, box_id)
            except CatalogContractError as exc:
                raise ValueError(f"MANUAL_CATALOG_SELECTION_REJECTED:{exc}") from exc
            provenance = canonical_catalog_provenance(VENUE_BOX_CATALOG)
            catalog_update = {
                "venueId": selection["venueId"],
                "venueTier": None,
                "venue": selection["venue"],
                "boxId": selection["boxId"],
                "box": selection["box"],
                "entryCost": selection["entryCost"],
                "catalogVersion": provenance["catalogVersion"],
                "catalogApprovalStatus": provenance["catalogApprovalStatus"],
                "catalogSha256": provenance["catalogSha256"],
                "gameEvidenceCohort": provenance["gameEvidenceCohort"],
                "venueEvidenceClass": selection["venueEvidenceClass"],
                "boxEvidenceClass": selection["boxEvidenceClass"],
            }
            if is_missing_observation("box", catalog_update.get("box")) and not explicit_unknown_box:
                for stale in ("boxId", "box", "boxEvidenceClass"):
                    catalog_update.pop(stale, None)
                    patch.pop(stale, None)
            patch.update(catalog_update)
            for stale_key in ("boxUnknown",):
                patch.pop(stale_key, None)
        else:
            for key in ("venueId", "boxId", "venue", "box", "boxUnknown"):
                if key in patch and (is_missing_observation(key, patch.get(key)) or key == "boxUnknown"):
                    patch.pop(key, None)
        raw_field = patch.get("fieldCondition")
        if raw_field not in (None, ""):
            field = canonicalize_field_condition(raw_field)
            patch["fieldCondition"] = None if field == UNKNOWN_FIELD else field
            if patch["fieldCondition"]:
                for item in field_conditions():
                    if item.get("id") == patch["fieldCondition"]:
                        patch["fieldConditionName"] = item.get("name") or item.get("label")
                        break
            whole_form_empty_env = any(
                key in patch and is_missing_observation(key, patch.get(key))
                for key in ("venueId", "boxId", "box")
            )
            if (
                patch.get("fieldCondition") == "standard"
                and not CURRENT_MATCH.facts.get("fieldCondition")
                and "fieldCondition" not in cleared_fields
                and whole_form_empty_env
            ):
                patch.pop("fieldCondition", None)
                patch.pop("fieldConditionName", None)
        elif "fieldCondition" in patch and "fieldCondition" not in cleared_fields:
            patch.pop("fieldCondition", None)
        content_patch = {
            key: value for key, value in patch.items()
            if key == "boxUnknown" or not is_missing_observation(key, value)
        }
        if _manual_patch_has_content(content_patch) or cleared_fields or restore_auto_fields:
            CURRENT_MATCH.apply_facts(
                content_patch,
                source="manual",
                intent=intent or "confirm",
                cleared_fields=cleared_fields,
                restore_auto_fields=restore_auto_fields,
            )
            schedule_draft_save(0.5)
            saved = {"id": CURRENT_MATCH.id}
        else:
            saved = {"id": CURRENT_MATCH.id} if CURRENT_MATCH.has_any_fact() else None
        include_solver = bool(
            _manual_patch_has_content(content_patch) or cleared_fields or restore_auto_fields
        )
        payload = build_manual_alpha_payload(include_solver_input=include_solver)
        changed = {key: value for key, value in CURRENT_MATCH.facts.items()
                   if previous_facts.get(key) != value}
        if changed or cleared_fields or restore_auto_fields:
            payload["manualControl"] = make_live_control_command(
                CURRENT_MATCH.id,
                facts=changed,
                cleared_fields=cleared_fields,
                restore_auto_fields=restore_auto_fields,
            )
        payload["draftId"] = saved.get("id") if saved else CURRENT_MATCH.id
        payload["draftSaved"] = draft_write_status() == "SAVED"
        LATEST_PAYLOAD.update(payload)
        return payload


def _manual_terminal_payload(result: Dict[str, Any], *, reset: bool) -> Dict[str, Any]:
    previous_id = CURRENT_MATCH.id
    if reset:
        cancel_draft_save()
        ACTIVE_SNAPSHOT_HOLDER.clear()
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()
        _MANUAL_MATCH_PLAYED_AT.pop(previous_id, None)
        CURRENT_MATCH.begin_next_match()
    payload = build_manual_alpha_payload()
    if reset:
        payload["manualControl"] = make_live_control_command(previous_id, reset=True)
    payload["draftSaved"] = False if reset else draft_write_status() == "SAVED"
    payload["terminalResult"] = result
    LATEST_PAYLOAD.update(payload)
    return payload


def _manual_terminal_failure(error: ManualTerminalError) -> Dict[str, Any]:
    result = {
        "terminalVersion": 1,
        "ok": False,
        "status": error.code,
        "matchId": CURRENT_MATCH.id,
        "message": error.message,
    }
    return _manual_terminal_payload(result, reset=False)


def finalize_manual_match(request: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = dict(request or {})
    expected_id = str(raw.get("expectedMatchId") or "").strip()
    with _MANUAL_STATE_LOCK:
        if expected_id != CURRENT_MATCH.id:
            return _manual_terminal_payload(
                MANUAL_TERMINAL.stale_result(expected_id, CURRENT_MATCH.id), reset=False
            )
        try:
            log_stage("ACTION:MANUAL", f"Finalize requested matchId={expected_id}")
            flush_draft_save_sync()
            log_stage("ACTION:MANUAL", f"Finalize draft flushed matchId={expected_id}")
            draft = _manual_draft_record()
            # The displayed result can arrive with the terminal request before
            # its normal facts-sync message. Terminal validation enforces ownership.
            prediction = raw.get("predictionSnapshot") or ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match(expected_id)
            log_stage("ACTION:MANUAL", f"Finalize transaction starting matchId={expected_id} snapshot={bool(prediction)}")
            result = MANUAL_TERMINAL.finalize(
                draft,
                raw.get("settlement") or {},
                prediction_snapshot=prediction,
                played_at=CURRENT_MATCH.created_at,
            )
            log_stage("ACTION:MANUAL", f"Finalize transaction complete matchId={expected_id} status={result.get('status')}")
            return _manual_terminal_payload(result, reset=True)
        except ManualTerminalError as exc:
            return _manual_terminal_failure(exc)


def begin_next_manual_match(request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = dict(request or {})
    expected_id = str(raw.get("expectedMatchId") or "").strip()
    disposition = str(raw.get("disposition") or "").strip().lower()
    with _MANUAL_STATE_LOCK:
        if expected_id != CURRENT_MATCH.id:
            return _manual_terminal_payload(
                MANUAL_TERMINAL.stale_result(expected_id, CURRENT_MATCH.id), reset=False
            )
        if disposition not in {"keep_draft", "discard"}:
            return _manual_terminal_payload(
                {
                    "terminalVersion": 1,
                    "ok": False,
                    "status": "TERMINAL_INTENT_REQUIRED",
                    "matchId": CURRENT_MATCH.id,
                    "message": "请选择结束本局、保留草稿或丢弃当前局",
                },
                reset=False,
            )
        try:
            cancel_draft_save()
            draft = _manual_draft_record()
            result = (
                MANUAL_TERMINAL.keep_draft(draft)
                if disposition == "keep_draft"
                else MANUAL_TERMINAL.discard(draft)
            )
            return _manual_terminal_payload(result, reset=True)
        except ManualTerminalError as exc:
            return _manual_terminal_failure(exc)


def publish_manual_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if WS_EVENT_LOOP and WS_EVENT_LOOP.is_running():
        try:
            asyncio.run_coroutine_threadsafe(
                broadcast_ws(json.dumps(payload, ensure_ascii=False)),
                WS_EVENT_LOOP,
            )
        except Exception as e:
            log_stage("ACTION:USER", f"manual payload broadcast failed: {e}")
    return payload


from async_snapshot_controller import AsyncTriggeredSnapshotController

_MAIN_WINDOW_HOLDER: List[Any] = []

def _publish_async_snapshot_payload(payload: Dict[str, Any]) -> None:
    LATEST_PAYLOAD.update(payload)
    publish_manual_payload(payload)
    snap_res = payload.get("snapshotResult")
    if snap_res and _MAIN_WINDOW_HOLDER and _MAIN_WINDOW_HOLDER[0] is not None:
        try:
            _MAIN_WINDOW_HOLDER[0].post_snapshot_result(snap_res)
        except Exception as exc:
            log_stage("ACTION:MAIN", f"post_snapshot_result failed: {exc}")

ASYNC_SNAPSHOT_CONTROLLER = AsyncTriggeredSnapshotController(
    state_lock=_MANUAL_STATE_LOCK,
    current_match_provider=lambda: CURRENT_MATCH,
    persist_draft_callback=_persist_current_draft_now,
    publish_callback=_publish_async_snapshot_payload,
    payload_builder=build_manual_alpha_payload,
    target_titles=CONFIG.get("window", {}).get("targetTitles", ["异环"]),
)


def handle_triggered_snapshot() -> Dict[str, Any]:
    """Execute a single-shot triggered screenshot recognition asynchronously in background."""
    return ASYNC_SNAPSHOT_CONTROLLER.request_snapshot()


def handle_main_triggered_snapshot() -> Dict[str, Any]:
    """Run Snapshot through the production owner and return immediate presentation-safe status."""
    return ASYNC_SNAPSHOT_CONTROLLER.request_snapshot()


def handle_save_settlement_screenshot() -> Dict[str, Any]:
    """Save one raw client-area settlement frame without running OCR.

    This is deliberately separate from triggered_snapshot: a user pressing the
    settlement button must get an immutable original even when OCR, identity
    matching, goldAvg, or settlement ledger work is slow or incomplete.
    """
    started = time.perf_counter()
    try:
        bindings = get_production_warehouse_bindings()
        if str(bindings.get("scene") or "").strip().upper() != "SETTLEMENT" or not bindings.get("isSettlement"):
            return {
                "ok": False,
                "status": "NOT_SETTLEMENT",
                "message": "当前不是已确认的结算画面，未保存截图。",
            }

        record_key = str(getattr(CURRENT_MATCH, "id", "") or "").strip()
        if not record_key:
            return {
                "ok": False,
                "status": "NO_ACTIVE_MATCH",
                "message": "当前没有可关联的对局草稿，未保存截图。",
            }

        hwnd = int(bindings.get("hwnd") or 0)
        capture_mgr = WindowCaptureManager()
        if hwnd:
            try:
                title = str(win32gui.GetWindowText(hwnd) or "")
                if not any(keyword in title for keyword in capture_mgr.keywords):
                    hwnd = 0
            except Exception:
                hwnd = 0
        if not hwnd:
            hwnd = int(capture_mgr.find_game_hwnd() or 0)
        if not hwnd:
            return {
                "ok": False,
                "status": "GAME_WINDOW_NOT_FOUND",
                "message": "没有找到异环游戏窗口，未保存截图。",
            }

        now_dt = datetime.now(timezone(timedelta(hours=8)))
        captured_at = now_dt.isoformat(timespec="seconds")
        source_frame_at = now_dt.isoformat(timespec="milliseconds")
        frame, capture_source = capture_mgr.capture_game_client(hwnd)
        if frame is None or getattr(frame, "size", 0) == 0:
            return {
                "ok": False,
                "status": "CAPTURE_FAILED",
                "message": "游戏结算画面截取失败，未显示保存成功。",
            }

        from runtime_data import runtime_data_paths
        from settlement_capture_links import merge_capture_link
        from settlement_stable_frame_persist import persist_stable_settlement_original
        from settlement_evidence_store_v2 import SettlementEvidenceStoreV2

        paths = runtime_data_paths()
        store = SettlementEvidenceStoreV2(paths.root)
        saved = persist_stable_settlement_original(
            store=store,
            is_settlement=True,
            record_stable_key=record_key,
            frame=frame,
            captured_at=captured_at,
            extract_proposals=False,
        )
        descriptor = saved.get("descriptor") if isinstance(saved, dict) else None
        if not isinstance(descriptor, dict):
            return {
                "ok": False,
                "status": str(saved.get("status") or "SAVE_FAILED"),
                "message": str(saved.get("warning") or "原始结算截图保存失败。"),
            }

        try:
            from version import APP_PRODUCT_VERSION
            app_version = APP_PRODUCT_VERSION
        except Exception:
            app_version = "unknown"
        with _MANUAL_STATE_LOCK:
            existing_links = CURRENT_MATCH.facts.get("settlementEvidence")
            existing_captures = (
                [c for c in existing_links.get("captures", []) if isinstance(c, dict)]
                if isinstance(existing_links, dict)
                else []
            )
            capture_sequence = len(existing_captures) + 1
            descriptor["captureSequence"] = capture_sequence
            descriptor["captureSource"] = capture_source
            descriptor["sourceFrameAt"] = source_frame_at

            links = merge_capture_link(
                existing_links if isinstance(existing_links, dict) else None,
                descriptor,
                match_id=record_key,
                source_instance_id=_CAPTURE_SOURCE_INSTANCE_ID,
                app_version=app_version,
                catalog_version=CURRENT_MATCH.facts.get("catalogVersion"),
            )
            CURRENT_MATCH.apply_facts({"settlementEvidence": links}, source="capture")
            persisted = _persist_current_draft_now()
            if persisted is None:
                try:
                    persisted = DRAFT_ARCHIVER.append_finalized_evidence(
                        record_key,
                        evidence_entry=descriptor,
                        links=links,
                        audit_reason="POST_FINALIZATION_SETTLEMENT_SCREENSHOT",
                    )
                except Exception as enrich_err:
                    log_stage("EVIDENCE:SETTLEMENT", f"append_finalized_evidence failed: {enrich_err}")

        relative_path = str(descriptor.get("relativePath") or "").replace("\\", "/")
        absolute_path = str((paths.root / relative_path).resolve())
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        response = {
            "ok": persisted is not None,
            "status": "SAVED" if persisted is not None else "SAVED_BUT_DRAFT_LINK_FAILED",
            "message": (
                "已保存结算原图；对局关联已写入对局记录。"
                if persisted is not None
                else "原图已落盘，但当前对局关联未写入，请保留该文件并稍后重试导出。"
            ),
            "matchId": record_key,
            "sequence": capture_sequence,
            "captureSequence": capture_sequence,
            "captureId": descriptor.get("evidenceId"),
            "evidenceId": descriptor.get("evidenceId"),
            "relativePath": relative_path,
            "absolutePath": absolute_path,
            "sha256": descriptor.get("sha256"),
            "width": descriptor.get("width"),
            "height": descriptor.get("height"),
            "captureSource": capture_source,
            "capturedAt": descriptor.get("capturedAt"),
            "sourceFrameAt": source_frame_at,
            "elapsedMs": elapsed_ms,
            "recognitionStarted": False,
        }
        log_stage(
            "EVIDENCE:SETTLEMENT",
            f"raw settlement original saved matchId={record_key} evidenceId={descriptor.get('evidenceId')} "
            f"size={descriptor.get('width')}x{descriptor.get('height')} elapsed_ms={elapsed_ms}",
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        log_stage("EVIDENCE:SETTLEMENT", f"raw settlement original failed elapsed_ms={elapsed_ms}: {exc}")
        return {
            "ok": False,
            "status": "SAVE_FAILED",
            "message": f"保存结算原图失败：{exc}",
            "elapsedMs": elapsed_ms,
            "recognitionStarted": False,
        }


def handle_save_game_screenshot() -> Dict[str, Any]:
    """Save one unrestricted raw screenshot of the actual game client.

    This is a provenance-only fallback for live play.  It deliberately does
    not inspect scene, settlement readiness, OCR, identity, or any settlement
    form fields.  The only association gate is an active match id, because an
    unattached image cannot safely become part of a history record.
    """
    started = time.perf_counter()
    try:
        record_key = str(getattr(CURRENT_MATCH, "id", "") or "").strip()
        if not record_key:
            return {
                "ok": False,
                "status": "NO_ACTIVE_MATCH",
                "message": "当前没有可关联的对局，未保存截图。",
            }

        from runtime_data import runtime_data_paths
        from settlement_capture_links import merge_capture_link
        from settlement_evidence_store_v2 import (
            COVERAGE_UNPROVEN,
            KIND_MANUAL_GAME,
            SettlementEvidenceStoreV2,
        )
        from settlement_stable_frame_persist import encode_settlement_original

        bindings = get_production_warehouse_bindings()
        hwnd = int(bindings.get("hwnd") or 0)
        capture_mgr = WindowCaptureManager()

        # A stale payload handle must never make the Main window or HUD the
        # capture target.  Keep the fast authoritative handle when its title
        # still identifies the game; otherwise rediscover the game window.
        if hwnd:
            try:
                title = str(win32gui.GetWindowText(hwnd) or "")
                if not any(keyword in title for keyword in capture_mgr.keywords):
                    hwnd = 0
            except Exception:
                hwnd = 0
        if not hwnd:
            hwnd = int(capture_mgr.find_game_hwnd() or 0)
        if not hwnd:
            return {
                "ok": False,
                "status": "GAME_WINDOW_NOT_FOUND",
                "message": "没有找到异环游戏窗口，未保存截图。",
            }

        now_dt = datetime.now(timezone(timedelta(hours=8)))
        captured_at = now_dt.isoformat(timespec="seconds")
        source_frame_at = now_dt.isoformat(timespec="milliseconds")
        frame, capture_source = capture_mgr.capture_game_client(hwnd)
        if frame is None or getattr(frame, "size", 0) == 0:
            return {
                "ok": False,
                "status": "CAPTURE_FAILED",
                "message": "异环游戏画面截取失败，未显示保存成功。",
            }

        paths = runtime_data_paths()
        store = SettlementEvidenceStoreV2(paths.root)
        image_bytes = encode_settlement_original(frame)

        import hashlib
        current_sha256 = hashlib.sha256(image_bytes).hexdigest()
        with _MANUAL_STATE_LOCK:
            existing_links = CURRENT_MATCH.facts.get("settlementEvidence")
            last_sha = None
            existing_captures = []
            if isinstance(existing_links, dict) and isinstance(existing_links.get("captures"), list):
                existing_captures = [c for c in existing_links["captures"] if isinstance(c, dict)]
                if existing_captures:
                    last_sha = existing_captures[-1].get("sha256")
            is_dup = False
            if last_sha and last_sha == current_sha256:
                is_dup = True
            elif existing_captures and any(c.get("sha256") == current_sha256 for c in existing_captures):
                is_dup = True
            if is_dup:
                elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
                return {
                    "ok": True,
                    "status": "DUPLICATE_IGNORED",
                    "duplicate": True,
                    "message": "该截图与上一张完全相同，未重复追加；请滚动仓库后再截取。",
                    "matchId": record_key,
                    "sequence": len(existing_captures),
                    "captureSequence": len(existing_captures),
                    "sha256": current_sha256,
                    "captureSource": capture_source,
                    "sourceFrameAt": source_frame_at,
                    "elapsedMs": elapsed_ms,
                    "recognitionStarted": False,
                    "sceneGate": "NONE",
                }

        descriptor = store.save_original(
            record_stable_key=record_key,
            kind=KIND_MANUAL_GAME,
            image_bytes=image_bytes,
            captured_at=captured_at,
            coverage_mode="unspecified",
            coverage_status=COVERAGE_UNPROVEN,
        )
        capture_sequence = len(existing_captures) + 1
        descriptor["captureSequence"] = capture_sequence
        descriptor["captureSource"] = capture_source
        descriptor["sourceFrameAt"] = source_frame_at

        try:
            from version import APP_PRODUCT_VERSION
            app_version = APP_PRODUCT_VERSION
        except Exception:
            app_version = "unknown"
        with _MANUAL_STATE_LOCK:
            existing_links = CURRENT_MATCH.facts.get("settlementEvidence")
            links = merge_capture_link(
                existing_links if isinstance(existing_links, dict) else None,
                descriptor,
                match_id=record_key,
                source_instance_id=_CAPTURE_SOURCE_INSTANCE_ID,
                app_version=app_version,
                catalog_version=CURRENT_MATCH.facts.get("catalogVersion"),
            )
            CURRENT_MATCH.apply_facts({"settlementEvidence": links}, source="manual_capture")
            persisted = _persist_current_draft_now()
            if persisted is None:
                try:
                    persisted = DRAFT_ARCHIVER.append_finalized_evidence(
                        record_key,
                        evidence_entry=descriptor,
                        links=links,
                        audit_reason="POST_FINALIZATION_GAME_SCREENSHOT",
                    )
                except Exception as enrich_err:
                    log_stage("EVIDENCE:MANUAL_CAPTURE", f"append_finalized_evidence failed: {enrich_err}")

        relative_path = str(descriptor.get("relativePath") or "").replace("\\", "/")
        absolute_path = str((paths.root / relative_path).resolve())
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        sequence_num = len(links.get("captures") or [])
        response = {
            "ok": persisted is not None,
            "status": "SAVED" if persisted is not None else "SAVED_BUT_DRAFT_LINK_FAILED",
            "message": (
                f"已保存第 {sequence_num} 张截图（同一对局证据组）；已关联当前对局。"
                if persisted is not None
                else "原图已落盘，但当前对局关联未写入，请保留该文件并稍后导出。"
            ),
            "matchId": record_key,
            "sequence": sequence_num,
            "captureSequence": sequence_num,
            "captureId": descriptor.get("evidenceId"),
            "evidenceId": descriptor.get("evidenceId"),
            "relativePath": relative_path,
            "absolutePath": absolute_path,
            "sha256": descriptor.get("sha256"),
            "width": descriptor.get("width"),
            "height": descriptor.get("height"),
            "captureSource": capture_source,
            "capturedAt": descriptor.get("capturedAt"),
            "sourceFrameAt": source_frame_at,
            "elapsedMs": elapsed_ms,
            "recognitionStarted": False,
            "sceneGate": "NONE",
        }
        log_stage(
            "EVIDENCE:MANUAL_CAPTURE",
            f"raw game screenshot saved matchId={record_key} evidenceId={descriptor.get('evidenceId')} "
            f"size={descriptor.get('width')}x{descriptor.get('height')} elapsed_ms={elapsed_ms}",
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
        log_stage("EVIDENCE:MANUAL_CAPTURE", f"raw game screenshot failed elapsed_ms={elapsed_ms}: {exc}")
        return {
            "ok": False,
            "status": "SAVE_FAILED",
            "message": f"保存异环截图失败：{exc}",
            "elapsedMs": elapsed_ms,
            "recognitionStarted": False,
        }



def is_in_auction_hud(ctx: Dict[str, Any]) -> bool:
    """局内以 scene / inAuction 为准。round=0 只表示回合号未知，不能降级成导航。"""
    if ctx.get("isSettlement"):
        return True
    if ctx.get("scene") == "IN_AUCTION":
        return True
    return bool(ctx.get("inAuction"))


def _compact_warehouse_vision(ctx: Dict[str, Any]) -> Dict[str, Any]:
    wh = ctx.get("warehouseVision") or {}
    slots = []
    for s in (wh.get("slots") or []):
        slots.append({
            "col": s.get("col"),
            "row": s.get("row"),
            "w": s.get("w") if s.get("w") is not None else s.get("width_cells"),
            "h": s.get("h") if s.get("h") is not None else s.get("height_cells"),
            "rarity": s.get("rarity"),
            "evidence": s.get("evidenceLevel") or s.get("evidence"),
            "size": s.get("size"),
        })
    grid = wh.get("grid") or {}
    return {
        "cols": int(grid.get("cols") or 10),
        "rows": int(grid.get("rows") or 10),
        "slots": slots,
    }


def session_costs_from_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Live cost contract: 0 is a real free ticket; None means unknown."""
    from business_sot import venue_entry_cost

    raw = ctx.get("costs") if isinstance(ctx.get("costs"), dict) else {}
    entry = raw.get("entry", ctx.get("lobbyEntryCost"))
    if entry is None:
        entry = venue_entry_cost(ctx.get("lobbyVenue") or ctx.get("venue"))
    intel = raw.get("intel", raw.get("info", ctx.get("intelCost")))
    other = raw.get("other", ctx.get("otherCost"))
    future = raw.get("futureIncrementalCost", ctx.get("futureIncrementalCost"))
    if intel is None:
        intel = 0
    if other is None:
        other = 0
    if future is None:
        future = 0
    sunk = None if entry is None else int(entry) + int(intel) + int(other)
    total = None if sunk is None else sunk + int(future)
    return {
        "entry": None if entry is None else int(entry),
        "intel": int(intel),
        "other": int(other),
        "sunkCost": sunk,
        "futureIncrementalCost": int(future),
        "total": total,
        "complete": entry is not None,
    }


_EVIDENCE_LEVEL_RANK: Dict[str, int] = {
    "UNKNOWN": 0,
    "OUTLINE_ONLY": 1,
    "RARITY_ONLY": 2,
    "RARITY_AND_SHAPE": 3,
    "CANDIDATE_SET": 4,
    "UNIQUE_IN_CATALOG": 5,
    "EXACT_IDENTIFIED": 6,
}


def _merge_canonical_warehouse(
    existing_wh: Optional[Dict[str, Any]],
    raw_slots: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_slots, list):
        return existing_wh
    if not raw_slots and not existing_wh:
        return None

    existing_slots = list(existing_wh.get("slots") or []) if isinstance(existing_wh, dict) else []
    merged_slots: List[Dict[str, Any]] = [dict(s) for s in existing_slots]

    for raw in raw_slots:
        if not isinstance(raw, dict):
            continue
        col = raw.get("col")
        row = raw.get("row")
        w = raw.get("w") if raw.get("w") is not None else raw.get("width_cells")
        h = raw.get("h") if raw.get("h") is not None else raw.get("height_cells")
        if col is None or row is None or w is None or h is None:
            continue
        col, row, w, h = int(col), int(row), int(w), int(h)
        rarity = str(raw.get("rarity") or "unknown")
        evidence = str(raw.get("evidenceLevel") or raw.get("evidence") or "OUTLINE_ONLY")
        # Phase 19: Identity Status & Candidates
        raw_candidates = raw.get("candidates") or []
        normalized_cands = [
            {
                "catalogId": str(c.get("catalogId") or c.get("Id") or ""),
                "name": str(c.get("name") or c.get("Name") or ""),
            }
            for c in raw_candidates
            if isinstance(c, dict)
        ]
        raw_status = str(raw.get("identityStatus") or ("CANDIDATE" if normalized_cands else "UNKNOWN"))
        is_exact = raw_status == "EXACT" or evidence == "EXACT_IDENTIFIED"
        raw_name = raw.get("identifiedName") or raw.get("name")
        identified_name = str(raw_name) if raw_name and is_exact and rarity != "unknown" and evidence != "OUTLINE_ONLY" else None
        identity_status = "EXACT" if identified_name else ("CANDIDATE" if normalized_cands else "UNKNOWN")

        track_id = int(raw["trackId"]) if raw.get("trackId") is not None else None

        new_entry: Dict[str, Any] = {
            "col": col,
            "row": row,
            "w": w,
            "h": h,
            "rarity": rarity,
            "evidenceLevel": evidence,
            "identityStatus": identity_status,
            "candidates": normalized_cands,
            "identifiedName": identified_name,
        }
        if track_id is not None:
            new_entry["trackId"] = track_id

        # Match against existing slot by trackId or exact (col, row, w, h)
        matched_idx = None
        for idx, exist in enumerate(merged_slots):
            if track_id is not None and exist.get("trackId") is not None and exist["trackId"] == track_id:
                matched_idx = idx
                break
            if (exist.get("col"), exist.get("row"), exist.get("w"), exist.get("h")) == (col, row, w, h):
                matched_idx = idx
                break

        if matched_idx is None:
            merged_slots.append(new_entry)
        else:
            exist = merged_slots[matched_idx]
            exist_rank = _EVIDENCE_LEVEL_RANK.get(exist.get("evidenceLevel", "OUTLINE_ONLY"), 0)
            new_rank = _EVIDENCE_LEVEL_RANK.get(evidence, 0)

            # Monotonic upgrade of evidence level
            if new_rank > exist_rank:
                exist["evidenceLevel"] = evidence
                if rarity != "unknown":
                    exist["rarity"] = rarity
            elif new_rank == exist_rank:
                if exist.get("rarity") == "unknown" and rarity != "unknown":
                    exist["rarity"] = rarity

            # Phase 19: Monotonic Identity & Candidates merge
            if exist.get("identityStatus") == "EXACT" and exist.get("identifiedName"):
                # EXACT monotonicity (AC7): Never downgrade an already exact identity
                pass
            elif identity_status == "EXACT" and identified_name:
                exist["identityStatus"] = "EXACT"
                exist["identifiedName"] = identified_name
            else:
                # Monotonic candidate shrink: old ∩ new (AC5, AC6)
                from item_identity_resolver import merge_candidates
                exist_cands = exist.get("candidates") or []
                merged_cands = merge_candidates(exist_cands, normalized_cands)
                exist["candidates"] = merged_cands
                exist["identityStatus"] = "CANDIDATE" if merged_cands else "UNKNOWN"
                exist["identifiedName"] = None

            # Fail-closed guarantee for outline/unknown
            if exist.get("rarity") == "unknown" or exist.get("evidenceLevel") == "OUTLINE_ONLY":
                exist["identifiedName"] = None
                if exist.get("identityStatus") == "EXACT":
                    exist["identityStatus"] = "CANDIDATE" if exist.get("candidates") else "UNKNOWN"

    return {"slots": merged_slots}


def sync_vision_to_current_match(ctx: Dict[str, Any]) -> None:
    """Sync live vision observations (venue, box, Q, goldAvg, purpleCount, settlement, warehouse) into CURRENT_MATCH."""
    if not isinstance(ctx, dict):
        return
    if ctx.get('recognitionPaused'):
        return
    evidence = ctx.get('auctionEvidence')
    if isinstance(evidence, dict) and evidence.get('ownerMatchId') == CURRENT_MATCH.id:
        CURRENT_MATCH.apply_facts({'auctionEvidence': evidence}, source='vision')
    # In manual mode, continue syncing vision observations so un-overridden
    # fields (seats, round, intel) update while manual fields remain protected.
    patch: Dict[str, Any] = {}
    # Preserve observed public quantities in the live authority as well as in
    # AutoArchiver's record; the HUD projection carries only a subset.
    for key in (
        "venueId", "venueTier", "boxId", "boxType", "fieldConditionName",
        "character", "entryCost", "intelCost", "otherCost", "futureIncrementalCost", "totalItems", "totalGrid", "totalGrids",
        "goldCount", "goldTotal", "goldMinCount", "goldGrid",
        "purpleMinCount", "purpleGrid", "redCount", "redMinCount",
        "redMaxCount", "redGrid", "whiteCount", "whiteAvg", "whiteGrid",
        "greenCount", "greenAvg", "greenGrid", "blueCount", "blueAvg", "blueGrid",
    ):
        if ctx.get(key) is not None:
            patch[key] = ctx[key]
    raw_costs = ctx.get("costs")
    if isinstance(raw_costs, dict):
        for source, target in (("intel", "intelCost"), ("other", "otherCost"),
                               ("futureIncrementalCost", "futureIncrementalCost")):
            if raw_costs.get(source) is not None:
                patch[target] = raw_costs[source]
    if ctx.get("venue") and not is_missing_observation("venue", ctx.get("venue")):
        patch["venue"] = ctx.get("venue")
    if ctx.get("box") and not is_missing_observation("box", ctx.get("box")):
        patch["box"] = ctx.get("box")
    # Matcher display labels are legacy Solver labels. Resolve the confirmed
    # matcher key through approved observation aliases, as manual input does.
    venue_id = ctx.get("venueId")
    if not venue_id:
        normalized_venue = normalize_vision_venue(
            VENUE_BOX_CATALOG,
            ctx.get("lobbyVenueKey")
            or ctx.get("venue"),
        )
        venue_id = normalized_venue.get("venueId")
    if venue_id:
        box_id = ctx.get("boxId")
        if not box_id:
            box_id = normalize_vision_box(
                VENUE_BOX_CATALOG, venue_id=venue_id, observation=ctx.get("box")).get("boxId")
        try:
            selection = catalog_selection(VENUE_BOX_CATALOG, venue_id, box_id)
        except CatalogContractError:
            selection = None
        if selection is not None:
            provenance = canonical_catalog_provenance(VENUE_BOX_CATALOG)
            catalog_patch = {key: selection.get(key) for key in (
                "venueId", "venue", "boxId", "box", "entryCost", "venueEvidenceClass", "boxEvidenceClass")}
            catalog_patch.update({key: provenance.get(key) for key in (
                "catalogVersion", "catalogApprovalStatus", "catalogSha256", "gameEvidenceCohort")})
            catalog_patch["venueTier"] = None
            for key, value in list(catalog_patch.items()):
                if is_missing_observation(key, value) and not is_missing_observation(key, CURRENT_MATCH.facts.get(key)):
                    catalog_patch.pop(key, None)
            patch.update(catalog_patch)
            ctx.update(catalog_patch)
    if ctx.get("fieldCondition"):
        patch["fieldCondition"] = ctx.get("fieldCondition")
    if ctx.get("q") is not None:
        patch["q"] = ctx.get("q")
    if ctx.get("avg") is not None or ctx.get("goldAvg") is not None:
        patch["goldAvg"] = ctx.get("goldAvg") if ctx.get("goldAvg") is not None else ctx.get("avg")
    if ctx.get("purpleCount") is not None or ctx.get("purple") is not None:
        patch["purpleCount"] = ctx.get("purpleCount") if ctx.get("purpleCount") is not None else ctx.get("purple")
    if ctx.get("purpleAvg") is not None:
        patch["purpleAvg"] = ctx.get("purpleAvg")
    if ctx.get("currentLeaderBid") is not None or ctx.get("leaderBid") is not None:
        patch["leaderBid"] = ctx.get("currentLeaderBid") if ctx.get("currentLeaderBid") is not None else ctx.get("leaderBid")
    if isinstance(ctx.get("seats"), list) and ctx.get("seats"):
        patch["seats"] = ctx.get("seats")
    if ctx.get("round") is not None:
        patch["roundNo"] = ctx.get("round")
    for key in ("historicalBids", "finalBids", "leaderName", "leaderTies", "myName", "isMyLead", "myBid"):
        if ctx.get(key) is not None:
            patch[key] = ctx.get(key)
    if isinstance(ctx.get("intelFacts"), dict) and ctx.get("intelFacts"):
        patch["intelFacts"] = ctx.get("intelFacts")
    if isinstance(ctx.get("intelObservations"), list) and ctx.get("intelObservations"):
        patch["intelObservations"] = ctx.get("intelObservations")
    if isinstance(ctx.get("intelCardReadings"), list) and ctx.get("intelCardReadings"):
        patch["intelCardReadings"] = ctx.get("intelCardReadings")
    if isinstance(ctx.get("publicCardEvents"), list) and ctx.get("publicCardEvents"):
        patch["publicCardEvents"] = ctx.get("publicCardEvents")

    raw_slots = ctx.get("warehouseSlots")
    if raw_slots is None and isinstance(ctx.get("warehouseVision"), dict):
        raw_slots = ctx["warehouseVision"].get("slots")
    if raw_slots:
        current_wh = CURRENT_MATCH.facts.get("warehouse")
        merged_wh = _merge_canonical_warehouse(current_wh, raw_slots)
        if merged_wh is not None:
            patch["warehouse"] = merged_wh
            ctx["warehouse"] = merged_wh

    if ctx.get("isSettlement"):
        st = ctx.get("settlementData") or {}
        from acquisition_authority import acquisition_from_context

        acquired_present, acquired = acquisition_from_context(ctx)
        if acquired_present:
            patch["isAcquired"] = acquired
        if st.get("clearingPrice") is not None:
            patch["clearingPrice"] = st.get("clearingPrice")
        if st.get("actualTotal") is not None:
            patch["actualTotal"] = st.get("actualTotal")
        if st.get("profit") is not None:
            patch["realizedProfit"] = st.get("profit")
        settlement_winner = ctx.get("winner") or st.get("winner")
        if settlement_winner:
            patch["winner"] = settlement_winner
        welfare_val = ctx.get("welfareReceived") if ctx.get("welfareReceived") is not None else st.get("welfareReceived")
        if welfare_val is None and isinstance(st.get("welfare"), dict):
            welfare_val = st["welfare"].get("received")
        if welfare_val is not None:
            patch["welfareReceived"] = welfare_val
        if ctx.get("settlementVerifiedRedItems") is not None:
            patch["settlementVerifiedRedItems"] = ctx.get("settlementVerifiedRedItems")
        elif st.get("settlementVerifiedRedItems") is not None:
            patch["settlementVerifiedRedItems"] = st.get("settlementVerifiedRedItems")
        if ctx.get("settlementItems"):
            patch["settlementItems"] = ctx.get("settlementItems")
        if ctx.get("settlementTruthEvidence"):
            patch["settlementTruthEvidence"] = ctx.get("settlementTruthEvidence")
        elif ctx.get("settlementEvidence"):
            patch["settlementEvidence"] = ctx.get("settlementEvidence")
        if ctx.get("settlementReady") is not None:
            patch["settlementReady"] = ctx.get("settlementReady")
        if ctx.get("settlementFinalized") is not None:
            patch["settlementFinalized"] = ctx.get("settlementFinalized")
    if patch:
        with _MANUAL_STATE_LOCK:
            CURRENT_MATCH.apply_facts(patch, source="vision")


def collect_gui_archive_prediction(request):
    """Return completed pre-settlement work without feeding settlement facts to Solver."""
    from live_shadow import completed_prediction_for_match
    match_id = request.get("matchId")
    response = {"action": "prediction_archive_response", "requestId": request.get("requestId"),
                "matchId": match_id, "snapshot": None}
    with _MANUAL_STATE_LOCK:
        if match_id != CURRENT_MATCH.id:
            return response
        completed = completed_prediction_for_match(match_id)
        if completed:
            ACTIVE_SNAPSHOT_HOLDER.update(match_id, snapshot=completed["snapshot"],
                                          frozen_prediction=completed.get("frozenPrediction"))
        response["snapshot"] = ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match(match_id)
        response["frozenPrediction"] = ACTIVE_SNAPSHOT_HOLDER.get_frozen_for_match(match_id)
    return response

def build_canonical_overlay_state(current_match: Any, extra_ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    snap = current_match.snapshot() if hasattr(current_match, "snapshot") else (current_match or {})
    facts = getattr(current_match, "facts", None) or (snap if ("venue" in snap or "q" in snap) else snap.get("facts", {}))
    field_states = snap.get("fieldStates", {}) if isinstance(snap, dict) else {}
    extra = extra_ctx or {}

    purple_val = facts.get("purpleCount") if facts.get("purpleCount") is not None else facts.get("purple")
    entry_cost = facts.get("entryCost")
    intel_cost = facts.get("intelCost") or 0
    other_cost = facts.get("otherCost") or 0
    future_cost = facts.get("futureIncrementalCost") or 0

    return {
        "matchId": getattr(current_match, "id", "") or extra.get("matchId", ""),
        "matchGeneration": getattr(current_match, "_seq", 0),
        "lifecycleStatus": getattr(current_match, "lifecycle_status", "DRAFT"),
        "factsRevision": getattr(current_match, "facts_revision", 0),
        "venue": facts.get("venue") or extra.get("venue"),
        "venueId": facts.get("venueId") or extra.get("venueId"),
        "venueTier": facts.get("venueTier") or extra.get("venueTier"),
        "box": facts.get("box") or extra.get("box"),
        "boxId": facts.get("boxId") or extra.get("boxId"),
        "boxType": facts.get("boxType") or extra.get("boxType"),
        "fieldCondition": facts.get("fieldCondition") or extra.get("fieldCondition") or "unknown",
        "fieldConditionName": facts.get("fieldConditionName") or extra.get("fieldConditionName"),
        "q": facts.get("q") if facts.get("q") is not None else extra.get("q"),
        "goldAvg": facts.get("goldAvg") if facts.get("goldAvg") is not None else extra.get("goldAvg"),
        "purple": purple_val if purple_val is not None else extra.get("purple"),
        "purpleCount": purple_val if purple_val is not None else extra.get("purpleCount"),
        "purpleAvg": facts.get("purpleAvg") if facts.get("purpleAvg") is not None else extra.get("purpleAvg"),
        "goldCount": facts.get("goldCount") if facts.get("goldCount") is not None else extra.get("goldCount"),
        "goldTotal": facts.get("goldTotal") if facts.get("goldTotal") is not None else extra.get("goldTotal"),
        "redCount": facts.get("redCount") if facts.get("redCount") is not None else extra.get("redCount"),
        "whiteCount": facts.get("whiteCount") if facts.get("whiteCount") is not None else extra.get("whiteCount"),
        "whiteAvg": facts.get("whiteAvg") if facts.get("whiteAvg") is not None else extra.get("whiteAvg"),
        "greenCount": facts.get("greenCount") if facts.get("greenCount") is not None else extra.get("greenCount"),
        "greenAvg": facts.get("greenAvg") if facts.get("greenAvg") is not None else extra.get("greenAvg"),
        "blueCount": facts.get("blueCount") if facts.get("blueCount") is not None else extra.get("blueCount"),
        "blueAvg": facts.get("blueAvg") if facts.get("blueAvg") is not None else extra.get("blueAvg"),
        "totalItems": facts.get("totalItems") if facts.get("totalItems") is not None else extra.get("totalItems"),
        "totalGrid": facts.get("totalGrid") if facts.get("totalGrid") is not None else extra.get("totalGrid"),
        "totalGrids": facts.get("totalGrids") if facts.get("totalGrids") is not None else extra.get("totalGrids"),
        "knownGold": facts.get("knownGold") or extra.get("knownGold") or "",
        "knownPurple": facts.get("knownPurple") or extra.get("knownPurple") or "",
        "knownRed": facts.get("knownRed") or extra.get("knownRed") or "",
        "knownBlue": facts.get("knownBlue") or extra.get("knownBlue") or "",
        "knownGreen": facts.get("knownGreen") or extra.get("knownGreen") or "",
        "knownWhite": facts.get("knownWhite") or extra.get("knownWhite") or "",
        "sparkle": facts.get("sparkle") if facts.get("sparkle") is not None else extra.get("sparkle"),
        "leaderBid": facts.get("leaderBid") if facts.get("leaderBid") is not None else extra.get("leaderBid"),
        "leaderName": facts.get("leaderName") or extra.get("leaderName"),
        "isMyLead": facts.get("isMyLead") if facts.get("isMyLead") is not None else extra.get("isMyLead"),
        "myBid": facts.get("myBid") if facts.get("myBid") is not None else extra.get("myBid"),
        "seats": facts.get("seats") or extra.get("seats") or [],
        "round": facts.get("roundNo") or extra.get("round"),
        "costs": {
            "entry": entry_cost,
            "intel": intel_cost,
            "other": other_cost,
            "futureIncrementalCost": future_cost,
        },
        "entryCost": entry_cost,
        "intelCost": intel_cost,
        "otherCost": other_cost,
        "futureIncrementalCost": future_cost,
        "fieldStates": field_states,
        "protectedFields": [k for k, v in field_states.items() if isinstance(v, dict) and v.get("protected")],
    }


def _sync_payload_with_canonical_facts(data: Dict[str, Any], current_match: Any) -> None:
    snap = current_match.snapshot() if hasattr(current_match, "snapshot") else (current_match or {})
    facts = getattr(current_match, "facts", None) or (snap if ("venue" in snap or "q" in snap) else snap.get("facts", {}))
    for key in (
        "venue", "venueId", "venueTier", "box", "boxId", "boxType",
        "fieldCondition", "fieldConditionName", "q", "goldAvg", "purpleAvg",
        "goldTotal", "goldCount", "redCount", "whiteCount", "whiteAvg",
        "greenCount", "greenAvg", "blueCount", "blueAvg", "totalItems",
        "totalGrid", "totalGrids", "knownGold", "knownPurple", "knownRed",
        "knownBlue", "knownGreen", "knownWhite", "sparkle"
    ):
        if key in facts and facts[key] is not None:
            data[key] = facts[key]
    if facts.get("purpleCount") is not None or facts.get("purple") is not None:
        p_val = facts.get("purpleCount") if facts.get("purpleCount") is not None else facts.get("purple")
        data["purpleCount"] = p_val
        data["purple"] = p_val
    if facts.get("entryCost") is not None:
        data["entryCost"] = facts["entryCost"]
    if not isinstance(data.get("costs"), dict):
        data["costs"] = {}
    if facts.get("entryCost") is not None:
        data["costs"]["entry"] = facts.get("entryCost")
    data["costs"]["intel"] = facts.get("intelCost") or 0
    data["costs"]["other"] = facts.get("otherCost") or 0
    data["costs"]["futureIncrementalCost"] = facts.get("futureIncrementalCost") or 0
    if facts.get("leaderBid") is not None:
        data["leaderBid"] = facts["leaderBid"]
    if facts.get("leaderName") is not None:
        data["leaderName"] = facts["leaderName"]
    if facts.get("isMyLead") is not None:
        data["isMyLead"] = facts["isMyLead"]
    if facts.get("myBid") is not None:
        data["myBid"] = facts["myBid"]
    if facts.get("seats"):
        data["seats"] = facts["seats"]
    if facts.get("roundNo") is not None:
        data["round"] = facts["roundNo"]


def attach_gui_prediction(payload):
    """Schedule computation on the persistent Node process. Overlay/Main only project."""
    from live_shadow import attach_live_shadow, load_history_snapshot
    data = dict(payload)
    if data.get("scene") != "IN_AUCTION" or data.get("isSettlement"):
        return data, None
    load_history_snapshot(CANONICAL_DATABASE)
    ctx = dict(data)
    ctx.update(CURRENT_MATCH.snapshot())
    ctx["matchId"] = CURRENT_MATCH.id
    ctx["matchGeneration"] = CURRENT_MATCH._seq
    ctx["presentationSource"] = "live_vision"
    shadowed = attach_live_shadow(ctx, db_path=CANONICAL_DATABASE)
    for key in ("probabilityProfile", "shadowMeta", "shadowStates", "shadowUpdating"):
        data[key] = shadowed.get(key)
    snapshot = shadowed.get("predictionSnapshot")
    frozen = shadowed.get("frozenPrediction")
    if not isinstance(snapshot, dict) or snapshot.get("matchId") != CURRENT_MATCH.id:
        return data, None
    ACTIVE_SNAPSHOT_HOLDER.update(CURRENT_MATCH.id, snapshot=snapshot, frozen_prediction=frozen)
    data["predictionSnapshot"] = snapshot
    data["frozenPrediction"] = frozen
    return data, {"action": "prediction_snapshot", "matchId": CURRENT_MATCH.id,
                  "snapshot": snapshot, "frozenPrediction": frozen}


def build_in_auction_hud_payload(ctx: Dict[str, Any], *, compute_shadow: bool = True) -> Dict[str, Any]:
    cur_bid = int(ctx.get("currentLeaderBid") or 0)
    my_bid = int(ctx.get("myBid") or 0)
    leader_name = ctx.get("leaderName")
    is_my_lead = bool(ctx.get("isMyLead", False))
    leader_sub = "等待出价..."
    if cur_bid > 0:
        if is_my_lead:
            leader_sub = "🟢 我处于领跑"
        elif leader_name:
            leader_sub = f"🔴 对手「{leader_name}」领跑"
        else:
            leader_sub = "🔴 对手领跑"
    round_no = ctx.get("round") or 0
    seats = ctx.get("seats") or []
    opponents = ctx.get("opponents")
    if opponents is None:
        opponents = [{"slot": s.get("slot"), "name": s.get("name"), "bid": s.get("bid") or 0} for s in seats if s.get("name")]
    # Shadow consumes the context object, not the later presentation payload.
    # Carry the already-authoritative live cost contract into that context when
    # the vision path omitted it.  A missing entry cost remains None; the
    # existing intel/other zero defaults are the established contract.
    raw_costs = ctx.get("costs") if isinstance(ctx.get("costs"), dict) else None
    if raw_costs is None or raw_costs.get("entry") is None:
        ctx["costs"] = session_costs_from_ctx(ctx)
    from live_shadow import attach_live_shadow
    shadowed = attach_live_shadow(ctx) if compute_shadow else {}
    profile = shadowed.get("probabilityProfile")
    snap = shadowed.get("predictionSnapshot")
    frozen = shadowed.get("frozenPrediction")
    target_match_id = ctx.get("matchId") or ctx.get("id") or CURRENT_MATCH.id
    if snap or frozen:
        ACTIVE_SNAPSHOT_HOLDER.update(target_match_id, snapshot=snap, frozen_prediction=frozen)
        ctx["predictionSnapshot"] = snap
        ctx["frozenPrediction"] = frozen
    shadow_updating = bool(shadowed.get("shadowUpdating"))
    purple_count = ctx.get("purpleCount") if ctx.get("purpleCount") is not None else ctx.get("purple")
    payload = {
        "solverStatus": "valid" if int(round_no or 0) > 0 else "incomplete",
        "scene": ctx.get("scene") or "IN_AUCTION",
        "sceneLabel": ctx.get("sceneLabel") or "局内",
        "inAuction": True,
        "inLobby": False,
        "lobbyVenue": ctx.get("lobbyVenue"),
        "lobbyToolGroup": ctx.get("lobbyToolGroup"),
        "lobbyCharacter": ctx.get("lobbyCharacter"),
        "lobbyCharacterLabel": character_display_label(ctx),
        "lobbyCharacterScore": ctx.get("lobbyCharacterScore"),
        "lobbyCharacterSecondScore": ctx.get("lobbyCharacterSecondScore"),
        "lobbyCharacterSource": ctx.get("lobbyCharacterSource"),
        "gameDetected": True,
        "round": round_no,
        "timer": ctx.get("timer"),
        "q": ctx.get("q"),
        "avg": ctx.get("avg"),
        "goldAvg": ctx.get("goldAvg"),
        "purpleAvg": ctx.get("purpleAvg"),
        **{key: ctx.get(key) for key in ('blueCount', 'goldCount', 'redCount', 'totalItems', 'purpleAvg', 'totalGrid', 'goldGrid', 'purpleGrid', 'whiteCount', 'whiteAvg', 'whiteGrid', 'greenCount', 'greenAvg', 'greenGrid', 'blueAvg', 'blueGrid', 'redGrid')},
        "goldTotal": ctx.get("goldTotal"),
        "goldCount": ctx.get("goldCount"),
        "purple": purple_count,
        "purpleCount": purple_count,
        "totalGrids": ctx.get("totalGrids"),
        "knownGold": ctx.get("knownGold", []),
        "knownPurple": ctx.get("knownPurple", []),
        **{key: ctx.get(key) for key in ("privateBidCap", "bidActionCount")},
        "welfareReceived": ctx.get("welfareReceived"),
        "freeIntelStatus": free_intel_status(ctx),
        "hiddenBids": bids_hidden_now(ctx),
        "sessionAccounting": accounting_from_facts(ctx),
        "sparkle": ctx.get("sparkle"),
        "knownBlue": ctx.get("knownBlue", ""),
        "knownGreen": ctx.get("knownGreen", ""),
        "knownWhite": ctx.get("knownWhite", ""),

        "knownRed": ctx.get("knownRed", []),
        "venue": ctx.get("venue") or "未知场地",
        "box": ctx.get("box") or "未知箱型",
        "fieldCondition": ctx.get("fieldCondition") or "unknown",
        "toolGroup": ctx.get("toolGroup"),
        "leaderBid": cur_bid,
        "leaderBidFormatted": format_val_w(cur_bid) if cur_bid > 0 else "0 W",
        "leaderBidSub": leader_sub,
        "leaderName": leader_name,
        "leaderTies": ctx.get("leaderTies") or [],
        "historicalBids": ctx.get("historicalBids") or {},
        "finalBids": ctx.get("finalBids") or {},
        "myBid": my_bid,
        "myBidFormatted": format_val_w(my_bid) if my_bid > 0 else "0 W",
        "myName": ctx.get("myName"),
        "seats": seats,
        "opponents": opponents,
        "biddingHistory": ctx.get("biddingHistory", {}),
        "roundTimeline": ctx.get("roundTimeline", {}),
        "isSettlement": ctx.get("isSettlement", False),
        "isAcquired": acquisition_from_context(ctx)[1],
        "settlementData": ctx.get("settlementData"),
        "warehouseVision": _compact_warehouse_vision(ctx),
        "warehouseRoi": ctx.get("warehouseRoi"),
        "scrollState": ctx.get("scrollState"),
        "warehousePresent": ctx.get("warehousePresent") is True,
        "gameHwnd": ctx.get("gameHwnd"),
        "recordStableKey": ctx.get("recordStableKey"),
        "loadingDirection": None,
        "hadSettlement": bool(ctx.get("hadSettlement", False)),
        "costs": session_costs_from_ctx(ctx),
        "costSummary": describe_costs(session_costs_from_ctx(ctx)),
        "lobbyEntryCost": ctx.get("lobbyEntryCost"),
        "probabilityProfile": profile,
        "shadowMeta": shadowed.get("shadowMeta"),
        "shadowStates": shadowed.get("shadowStates"),
        "shadowUpdating": shadow_updating,
    }
    from strategy_ux_metrics import (
        EstimateMode,
        compute_strategy_metrics_summary,
        StrategyPanelShellState,
        get_authoritative_strategy_store,
    )
    store = get_authoritative_strategy_store()
    snap_quantiles = (snap or {}).get("forecast", {}).get("quantiles") or {} if isinstance(snap, dict) else {}
    strategy_metrics = compute_strategy_metrics_summary(
        mode=store.state.estimate_mode,
        prediction_snapshot=snap,
        val_p50=snap_quantiles.get("p50"),
        val_p20=snap_quantiles.get("p20"),
        val_p80=snap_quantiles.get("p80"),
    )
    strategy_panel = StrategyPanelShellState(
        is_panel_expanded=store.state.is_panel_expanded,
        estimate_mode=store.state.estimate_mode.value,
        fast_mode_available=False,
        strategy_round=store.state.strategy_round,
        strategy_venue=store.state.strategy_venue,
        strategy_profile=store.state.strategy_profile.value,
        strategy_source="user_strategy",
        metrics_summary=strategy_metrics,
        production_estimate=strategy_metrics.medianEstimate,
        is_experimental_expanded=store.state.is_experimental_expanded,
        can_undo=store.can_undo,
        can_redo=store.can_redo,
    )
    payload["estimateMode"] = store.state.estimate_mode.value
    payload["strategyMetrics"] = strategy_metrics.to_payload()
    payload["strategyPanel"] = strategy_panel.to_payload()
    from experimental_red_inference import safe_evaluate_experimental_red
    from experimental_probability_strategy import safe_evaluate_experimental_probability_strategy
    payload["experimentalRed"] = safe_evaluate_experimental_red(
        ctx,
        production_metrics=strategy_metrics.to_payload(),
        shadow_profile=profile,
    )
    payload["experimentalProbabilityStrategy"] = safe_evaluate_experimental_probability_strategy(
        ctx,
        production_metrics=strategy_metrics.to_payload(),
        shadow_profile=profile,
        experimental_red=payload.get("experimentalRed"),
    )
    return attach_warehouse_capture_presentation(payload)


def character_display_label(ctx: Dict[str, Any], refreshing: bool = False) -> Optional[str]:
    if refreshing:
        return "识别中"
    if ctx.get("lobbyCharacter"):
        return ctx.get("lobbyCharacter")
    if ctx.get("inLobby") or ctx.get("scene") == "AUCTION_LOBBY":
        return "未识别"
    return None


def build_nav_hud_payload(ctx: Dict[str, Any]) -> Dict[str, Any]:
    is_loading = bool(ctx.get("isLoading", False))
    in_lobby = bool(ctx.get("inLobby", False)) and not is_loading
    scene = ctx.get("scene") or ("AUCTION_LOADING" if is_loading else ("AUCTION_LOBBY" if in_lobby else "UNKNOWN"))
    scene_label = ctx.get("sceneLabel") or scene
    auction_entry = bool(ctx.get("auctionEntryVisible", False))
    venue_label = ctx.get("lobbyVenue")
    char_label = ctx.get("lobbyCharacter")
    char_shown = character_display_label(ctx)
    tool_label = ctx.get("lobbyToolGroup")
    entry_cost = ctx.get("lobbyEntryCost")
    loading_pct = ctx.get("loadingPercent")
    loading_venue = ctx.get("loadingVenue")
    loading_direction = ctx.get("loadingDirection") or ("to_lobby" if ctx.get("hadSettlement") else "to_auction")

    if is_loading or scene == "AUCTION_LOADING":
        solver_status = "loading"
        pct_txt = f"{loading_pct}%" if loading_pct is not None else "--%"
        lore_txt = f"「{loading_venue}」" if loading_venue else "载入信息未知"
        if loading_direction in ("to_lobby", "egress"):
            action_dir = "🏠 正在返回大厅"
            action_rsn = "对局已结束 · 正在退出拍卖并返回大厅"
            leader_sub = f"返回大厅中 ({pct_txt})"
        elif loading_direction in ("to_auction", "ingress"):
            action_dir = "🚀 正在载入拍卖 · 即将开槌"
            action_rsn = f"载入信息: {lore_txt} · 载入进度 {pct_txt}"
            leader_sub = f"对局加载中 ({pct_txt})"
        else:
            action_dir = "⏳ 正在载入..."
            action_rsn = f"载入进度 {pct_txt}"
            leader_sub = f"载入中 ({pct_txt})"
    elif in_lobby or scene == "AUCTION_LOBBY":
        ACTIVE_SNAPSHOT_HOLDER.clear()
        ctx["predictionSnapshot"] = None
        ctx["frozenPrediction"] = None
        solver_status = "lobby"
        action_dir = "🎮 准备就绪: 点击开始匹配"
        bits = [x for x in (venue_label, char_shown, tool_label) if x]
        action_rsn = ("已就绪: " + " · ".join(bits)) if bits else "拍卖大厅已识别"
        leader_sub = f"门票: {entry_cost} 珍珠" if entry_cost is not None else "门票: 待识别"
    elif scene == "OPEN_WORLD":
        solver_status = "nav_world"
        action_dir = "🌍 大世界"
        action_rsn = "当前不在拍卖"
        leader_sub = "大世界"
    elif scene == "CITY_TYCOON_HUB":
        solver_status = "nav_hub"
        action_dir = "🏙 都市大亨"
        action_rsn = "当前不在拍卖"
        leader_sub = "都市大亨"
    elif scene == "CITY_LEISURE_MENU":
        solver_status = "nav_leisure"
        action_dir = "🎮 都市闲趣"
        action_rsn = "当前不在拍卖"
        leader_sub = "即刻落槌可见" if auction_entry else "都市闲趣"
    else:
        solver_status = "standby"
        action_dir = "⏳ 监控待命中"
        action_rsn = "等待进入拍卖"
        leader_sub = "等待进入拍卖..."

    payload = {
        "solverStatus": solver_status,
        "scene": scene,
        "sceneLabel": scene_label,
        "auctionEntryVisible": auction_entry,
        "inAuction": False,
        "inLobby": in_lobby,
        "isLoading": is_loading,
        "loadingPercent": loading_pct,
        "loadingVenue": loading_venue,
        "loadingDirection": loading_direction,
        "hadSettlement": bool(ctx.get("hadSettlement", False)),
        "gameDetected": True,
        "round": 0,
        "timer": None,
        "lobbyVenue": venue_label,
        "lobbyVenueLabel": ctx.get("lobbyVenueLabel"),
        "lobbyCharacter": char_label,
        "lobbyCharacterLabel": char_shown,
        "lobbyCharacterScore": ctx.get("lobbyCharacterScore"),
        "lobbyCharacterSecondScore": ctx.get("lobbyCharacterSecondScore"),
        "lobbyCharacterSource": ctx.get("lobbyCharacterSource"),
        "lobbyToolGroup": tool_label,
        "lobbyEntryCost": entry_cost,
        "costs": session_costs_from_ctx(ctx),
        "costSummary": describe_costs(session_costs_from_ctx(ctx)),
        "leaderBidFormatted": "-- W",
        "leaderBidSub": leader_sub,
        "myBidFormatted": "-- W",
        "myName": ctx.get("myName", "玩家本人"),
        "actionDirective": action_dir,
        "actionReason": action_rsn,
        "opponents": [],
        "biddingHistory": {},
        "roundTimeline": {},
        "isSettlement": False,
        "gridCells": [0] * 250,
    }
    from strategy_ux_metrics import (
        EstimateMode,
        compute_strategy_metrics_summary,
        StrategyPanelShellState,
        get_authoritative_strategy_store,
    )
    store = get_authoritative_strategy_store()
    nav_metrics = compute_strategy_metrics_summary(
        mode=store.state.estimate_mode,
        val_p50=None,
        val_p20=None,
        val_p80=None,
    )
    nav_panel = StrategyPanelShellState(
        is_panel_expanded=store.state.is_panel_expanded,
        estimate_mode=store.state.estimate_mode.value,
        fast_mode_available=False,
        strategy_round=store.state.strategy_round,
        strategy_venue=store.state.strategy_venue,
        strategy_profile=store.state.strategy_profile.value,
        strategy_source="user_strategy",
        metrics_summary=nav_metrics,
        production_estimate=None,
        is_experimental_expanded=store.state.is_experimental_expanded,
        can_undo=store.can_undo,
        can_redo=store.can_redo,
    )
    payload["estimateMode"] = store.state.estimate_mode.value
    payload["strategyMetrics"] = nav_metrics.to_payload()
    payload["strategyPanel"] = nav_panel.to_payload()
    from experimental_red_inference import safe_evaluate_experimental_red
    from experimental_probability_strategy import safe_evaluate_experimental_probability_strategy
    payload["experimentalRed"] = safe_evaluate_experimental_red(
        ctx,
        production_metrics=nav_metrics.to_payload(),
    )
    payload["experimentalProbabilityStrategy"] = safe_evaluate_experimental_probability_strategy(
        ctx,
        production_metrics=nav_metrics.to_payload(),
        experimental_red=payload.get("experimentalRed"),
    )
    return attach_warehouse_capture_presentation(payload)


def process_live_game_frame(
    img: np.ndarray,
    *,
    game_hwnd: Optional[int] = None,
    captured_at: Optional[str] = None,
    pipeline_inst: Optional[Any] = None,
    ctx: Optional[Dict[str, Any]] = None,
    record_stable_key: Optional[str] = None,
    run_capture_orchestration: bool = True,
    sync_facts: bool = True,
    compute_shadow: bool = True,
) -> Dict[str, Any]:
    """Production live-frame handler:

    Runs vision recognition on live frame (or reuses existing parsed ctx), observes
    the warehouse scrollbar in settlement scene, merges authoritative match authority,
    and updates LATEST_PAYLOAD.
    """
    if ctx is None:
        pipe = pipeline_inst
        if pipe is None:
            from vision_pipeline import NTEVisionPipeline

            pipe = NTEVisionPipeline()

        shot_at = captured_at or datetime.now(timezone(timedelta(hours=8))).isoformat()
        stable_key = record_stable_key or str(getattr(CURRENT_MATCH, "id", "") or "")
        ctx = pipe.process_frame(img, captured_at=shot_at, record_stable_key=stable_key)

    # Vision contexts are per-frame and do not carry the canonical match
    # timestamp. Preserve any legal explicit value; otherwise bind the match
    # once to the first real capture boundary.  Replay therefore keeps its
    # source time instead of inheriting the replay process's created_at.
    played_at = ctx.get("playedAt")
    match_id_for_time = str(getattr(CURRENT_MATCH, "id", "") or "").strip()
    if played_at:
        if match_id_for_time:
            _VISION_MATCH_PLAYED_AT.setdefault(match_id_for_time, str(played_at))
    elif match_id_for_time:
        stable_played_at = _VISION_MATCH_PLAYED_AT.get(match_id_for_time)
        if not stable_played_at:
            candidate = captured_at
            try:
                if candidate:
                    datetime.fromisoformat(str(candidate).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                candidate = None
            stable_played_at = str(candidate or getattr(CURRENT_MATCH, "created_at", "") or "").strip()
            if stable_played_at:
                _VISION_MATCH_PLAYED_AT[match_id_for_time] = stable_played_at
        if stable_played_at:
            ctx["playedAt"] = stable_played_at

    effective_hwnd = int(game_hwnd or 0)
    if not effective_hwnd:
        try:
            from window_capture import WindowCaptureManager

            effective_hwnd = int(WindowCaptureManager().find_game_hwnd() or 0)
        except Exception:
            effective_hwnd = 0
    ctx["gameHwnd"] = effective_hwnd

    if ctx.get("isSettlement") or ctx.get("scene") in ("SETTLEMENT", "IN_AUCTION"):
        from warehouse_grid_geometry import observe_warehouse_grid
        from warehouse_scrollbar_observation import observe_warehouse_scrollbar, warehouse_search_roi

        obs = observe_warehouse_scrollbar(img, already_cropped=False)
        ctx["scrollState"] = str(obs.get("scrollState") or "UNKNOWN")
        h, w = img.shape[:2]
        ctx["warehouseRoi"] = warehouse_search_roi(w, h)
        try:
            grid_obs = observe_warehouse_grid(img, already_cropped=False)
            ctx["warehousePresent"] = grid_obs.get("grid", {}).get("status") == "OK"
        except Exception:
            ctx["warehousePresent"] = False
    else:
        ctx["warehousePresent"] = False

    if sync_facts:
        sync_vision_to_current_match(ctx)
    match_id = getattr(CURRENT_MATCH, "id", "")
    ctx["recordStableKey"] = str(match_id or "")

    if is_in_auction_hud(ctx):
        hud_payload = build_in_auction_hud_payload(ctx, compute_shadow=compute_shadow)
    else:
        hud_payload = build_nav_hud_payload(ctx)

    for key in ('auctionEvidence', 'sceneRouting', 'recognitionPaused', 'auctionPhase'):
        if key in ctx:
            hud_payload[key] = ctx[key]
    routing = ctx.get('sceneRouting') or {}
    if routing.get('message'):
        hud_payload['actionReason'] = routing['message']
    if ctx.get('auctionPhase') == 'MATCHING_SUCCESS':
        hud_payload['actionDirective'] = '匹配成功，等待加载'
    if pipeline_inst is not None and ctx.get('auctionEvidence', {}).get('hasReturned'):
        from auction_flow_evidence import AuctionEvidencePersistence
        persistence = getattr(pipeline_inst, '_auction_evidence_persistence', None)
        if persistence is None:
            persistence = AuctionEvidencePersistence(CanonicalHistoryStore())
            pipeline_inst._auction_evidence_persistence = persistence
        persistence.save(ctx['auctionEvidence'])

    PRESENTATION_RUNTIME.observe_transport(hud_payload)
    LATEST_VISION_PAYLOAD.clear()
    LATEST_VISION_PAYLOAD.update(hud_payload)
    LATEST_PAYLOAD.update(hud_payload)
    if run_capture_orchestration:
        maybe_trigger_auto_warehouse_capture(ctx)
    return hud_payload


def process_early_warehouse_frame(
    img: np.ndarray,
    *,
    game_hwnd: Optional[int] = None,
    captured_at: Optional[str] = None,
    pipeline_inst: Optional[Any] = None,
    **_kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """Publish the independent Warehouse observation before full-frame OCR.

    This is deliberately a narrow presentation path. It reuses the existing
    scene/grid/scroll/warehouse recognizers, carries no settlement ledger facts,
    and leaves the normal frame path to publish the authoritative later merge.
    """
    pipe = pipeline_inst
    if pipe is None or img is None or getattr(img, "size", 0) == 0:
        return None
    base = getattr(pipe, "current_context", None)
    if not isinstance(base, dict):
        return None

    previous_scene = str(base.get("scene") or "")
    try:
        fast_scene = (pipe._classify_scene_fast(img) or {}).get("scene")
    except Exception:
        fast_scene = None

    if getattr(pipe, 'scene_roi_router', None) is not None and fast_scene not in ('IN_AUCTION', 'SETTLEMENT'):
        return None
    is_settlement = fast_scene == "SETTLEMENT" or previous_scene == "SETTLEMENT"
    is_in_auction = previous_scene == "IN_AUCTION" or bool(base.get("inAuction"))
    if not (is_settlement or is_in_auction):
        return None
    if is_in_auction and not is_settlement and int(base.get("round") or 0) <= 0:
        return None

    from warehouse_grid_geometry import observe_warehouse_grid
    from warehouse_scrollbar_observation import observe_warehouse_scrollbar, warehouse_search_roi

    grid_obs = observe_warehouse_grid(img, already_cropped=False)
    if (grid_obs.get("grid") or {}).get("status") != "OK":
        return None
    scroll_obs = observe_warehouse_scrollbar(img, already_cropped=False)
    height, width = img.shape[:2]

    # Geometry only. Catalog identity belongs after OCR facts are published.
    ctx = dict(base)
    ctx["scene"] = "SETTLEMENT" if is_settlement else "IN_AUCTION"
    ctx["isSettlement"] = is_settlement
    ctx["inAuction"] = True
    ctx["inLobby"] = False
    ctx["isLoading"] = False
    ctx["warehousePresent"] = True
    ctx["warehouseRoi"] = warehouse_search_roi(width, height)
    ctx["scrollState"] = str(scroll_obs.get("scrollState") or "UNKNOWN")
    ctx["gameHwnd"] = int(game_hwnd or 0)
    ctx["recordStableKey"] = str(getattr(CURRENT_MATCH, "id", "") or base.get("recordStableKey") or "")
    if is_settlement:
        # This early packet is not a settlement ledger observation. Preserve
        # the DRAFT boundary until the normal settlement path is complete.
        ctx["settlementData"] = None
        ctx["settlementReady"] = False
        ctx["settlementFinalized"] = False

    return process_live_game_frame(
        img,
        game_hwnd=game_hwnd,
        captured_at=captured_at,
        pipeline_inst=pipe,
        ctx=ctx,
        # The GUI process owns the native capture host. The worker only emits
        # the early vision packet; the existing WS receiver performs the same
        # auto-capture orchestration as the normal packet path.
        run_capture_orchestration=False,
        sync_facts=False,
        compute_shadow=False,
    )


def vision_capture_worker():
    """
    后台屏幕捕获与视觉决策推演工作线程
    """
    log_stage("WORKER:VISION", f"Vision worker process started (PID={os.getpid()})")
    stop_flag = {"stop": False}

    def _mark_worker_stop(signum=None, frame=None):
        stop_flag["stop"] = True

    try:
        import signal
        signal.signal(signal.SIGTERM, _mark_worker_stop)
        signal.signal(signal.SIGINT, _mark_worker_stop)
    except Exception:
        pass
    time.sleep(0.5)
    
    # 仅在子进程中延迟导入重量级 ONNX / 图像处理管道
    from keyboard_auction_pipeline import KeyboardAuctionPipeline
    from shape_matcher import ShapeMatcher
    from auto_archiver import AutoArchiver
    from live_shadow import load_history_snapshot, warmup_shadow_runtime

    cat_path = os.path.join(ASSETS_DIR, "catalog_065.json")
    keyframe_candidates = [
        os.path.join(ASSETS_DIR, "replay_frames"),
        os.path.join(BASE_DIR, "录像关键帧"),
    ]
    keyframe_dir = next((p for p in keyframe_candidates if os.path.isdir(p)), keyframe_candidates[0])

    log_stage("WORKER:VISION", "Creating vision pipeline (OCR warms in background)...")
    t_init_0 = time.perf_counter()
    pipeline = KeyboardAuctionPipeline(catalog_path=cat_path)
    pipeline.recognition_mode_provider = get_recognition_mode
    pipeline.fast_live_intel = False
    pipeline._warm_ocr_async()
    if CANONICAL_DATABASE:
        hist = load_history_snapshot(CANONICAL_DATABASE)
        log_stage("WORKER:VISION", f"history snapshot n={len(hist)}")
    else:
        hist = []
        log_stage(
            "WORKER:VISION",
            "history unavailable; Historical Shadow remains on its no-history path",
        )
    archiver = AutoArchiver(
        db_paths=[CANONICAL_DATABASE] if CANONICAL_DATABASE else []
    )
    tracker = GameWindowTracker(target_titles=CONFIG.get("window", {}).get("targetTitles", ["异环"]))
    t_init_ms = (time.perf_counter() - t_init_0) * 1000
    log_stage("WORKER:VISION", f"Pipeline created in {t_init_ms:.1f}ms; RapidOCR warming asynchronously")

    mode = CONFIG.get("app", {}).get("mode", "live")
    ws_uri = f"ws://127.0.0.1:{WS_PORT}"
    replay_frames = []
    if mode == "replay":
        if not os.path.isdir(keyframe_dir):
            log_stage("WORKER:VISION", f"Replay directory missing: {keyframe_dir}")
            return
        replay_frames = sorted(f for f in os.listdir(keyframe_dir)
                               if f.startswith("frame_") and f.endswith(".jpg"))
        if not replay_frames:
            log_stage("WORKER:VISION", "Replay contains no frames; exiting")
            return
    # A transport reconnect must not rewind observations or lose a pending HUD.
    replay_progress = {"index": 0, "pending": None}
    from live_match_transport import LiveMatchSession
    replay_session = LiveMatchSession()

    async def _loop():
        from live_match_transport import LiveMatchPublisher
        from live_match_control import LiveMatchControl
        state_publisher = LiveMatchPublisher()
        live_control = LiveMatchControl()
        log_stage("WORKER:VISION", f"Connecting to WebSocket bus at {ws_uri}...")
        async with websockets.connect(ws_uri) as ws:
            async def publish_worker_payload(payload):
                state_publisher.awaiting_exit = live_control.awaiting_exit
                await ws.send(json.dumps(state_publisher.attach(payload, CURRENT_MATCH)))

            await ws.send(json.dumps({"type": "vision_worker_hello"}))
            while True:
                resume = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if resume.get("action") == "worker_resume":
                    live_control.apply(resume, CURRENT_MATCH, state_publisher, pipeline,
                                       replay_session, bootstrap=True)
                    break

            log_stage("WORKER:VISION", f"WebSocket connected, entering vision inference loop (mode={mode})")
            refresh_state = {
                "latest_id": None,
                "committed_id": None,
            }
            shutdown_state = {"flushing": False}
            from prediction_archive_transport import PredictionArchiveTransport

            async def send_prediction_request(request):
                await ws.send(json.dumps(request, ensure_ascii=False))

            prediction_transport = PredictionArchiveTransport(
                send_prediction_request, CURRENT_MATCH, ACTIVE_SNAPSHOT_HOLDER)

            async def _flush_settlement_if_needed(reason: str):
                if shutdown_state["flushing"] or not CONFIG.get("archiver", {}).get("autoSave", True):
                    return
                if pipeline is not None and hasattr(pipeline, "complete_heavy_identity"):
                    if getattr(pipeline, "_pending_heavy_identity", None):
                        try:
                            heavy_ctx = pipeline.complete_heavy_identity()
                            if isinstance(heavy_ctx, dict) and heavy_ctx.get("frame") is None:
                                heavy_ctx["frame"] = pipeline.current_context.get("frame")
                        except Exception as h_err:
                            log_stage("WORKER:VISION", f"flush identity error: {h_err}")
                if not pipeline.flush_settlement_for_shutdown():
                    return
                shutdown_state["flushing"] = True
                if not await prediction_transport.collect(pipeline.current_context):
                    shutdown_state["flushing"] = False
                    return
                saved = archiver.archive_match(pipeline.current_context)
                if saved:
                    from vision_worker_loop import apply_archive_lifecycle
                    apply_archive_lifecycle(saved, pipeline, CURRENT_MATCH)
                    log_stage(
                        "WORKER:VISION",
                        f"settlement finalize reason={reason} price={saved.get('clearingPrice')} "
                        f"actual={saved.get('actualTotal')} profit={saved.get('realizedProfit')} box={saved.get('box')}",
                    )

            async def _watch_force_refresh():
                try:
                    async for raw in ws:
                        try:
                            data = json.loads(raw) if isinstance(raw, str) else {}
                        except Exception:
                            continue
                        if isinstance(data, dict) and data.get("manualControl"):
                            if live_control.apply(data["manualControl"], CURRENT_MATCH, state_publisher,
                                                  pipeline, replay_session):
                                await publish_worker_payload({"controlApplied": True})
                            else:
                                revision = data["manualControl"].get("revision")
                                if type(revision) is int and revision > state_publisher.control_revision:
                                    state_publisher.control_revision = revision
                                    await publish_worker_payload({"controlRejected": "MATCH_CHANGED"})
                        elif isinstance(data, dict) and data.get("action") == "prediction_archive_response":
                            prediction_transport.receive(data)
                        elif isinstance(data, dict) and data.get("action") == "prediction_snapshot":
                            if data.get("matchId") == CURRENT_MATCH.id:
                                ACTIVE_SNAPSHOT_HOLDER.update(
                                    CURRENT_MATCH.id, snapshot=data.get("snapshot"),
                                    frozen_prediction=data.get("frozenPrediction"))
                        elif isinstance(data, dict) and data.get("action") == "force_refresh":
                            rid = data.get("refreshRequestId") or data.get("requestId") or _next_refresh_id()
                            refresh_state["latest_id"] = rid
                            log_stage("WORKER:VISION", f"force_refresh received request_id={rid}")
                        elif isinstance(data, dict) and data.get("action") == "flush_settlement":
                            log_stage("WORKER:VISION", "flush_settlement received")
                            asyncio.create_task(_flush_settlement_if_needed("ws-flush"))
                except Exception:
                    return

            watcher = asyncio.create_task(_watch_force_refresh())
            replay_video = str(os.environ.get("NTE_REPLAY_VIDEO") or CONFIG.get("app", {}).get("replayVideo") or "").strip()
            replay_frames_dir = str(os.environ.get("NTE_REPLAY_FRAMES_DIR") or "").strip()
            if mode == "replay" or replay_video or replay_frames_dir:
                from frame_source import KeyframeDirectorySource, VideoCaptureSource
                if replay_progress["pending"] is not None:
                    await publish_worker_payload(replay_progress["pending"])
                    replay_progress["pending"] = None
                if replay_video:
                    source = VideoCaptureSource(replay_video, stop_flag=stop_flag)
                    log_stage("WORKER:VISION", f"unified loop frame source=video path={replay_video}")
                elif replay_frames_dir:
                    source = KeyframeDirectorySource(replay_frames_dir, stop_flag=stop_flag, hold_last=True)
                    log_stage("WORKER:VISION", f"unified loop frame source=files dir={replay_frames_dir} n={len(source.paths)} hold_last=1")
                else:
                    source = KeyframeDirectorySource(keyframe_dir, stop_flag=stop_flag, hold_last=True)
                    log_stage("WORKER:VISION", f"unified loop frame source=keyframes dir={keyframe_dir} n={len(source.paths)} hold_last=1")
                fingerprint = source.content_fingerprint() if hasattr(source, "content_fingerprint") else None
                CURRENT_MATCH.data_origin = "replay"
                pipeline.current_context["dataOrigin"] = "replay"
                pipeline.current_context["executionOrigin"] = "replay"
                if fingerprint:
                    replay_key = f"replayfile_{fingerprint}"
                    CURRENT_MATCH.id = replay_key
                    pipeline.current_context["recordStableKey"] = replay_key
                    pipeline.current_context["id"] = replay_key
                    log_stage(
                        "WORKER:VISION",
                        f"replay source fingerprint={fingerprint} recordStableKey={replay_key}",
                    )

                def _replay_frame():
                    hwnd, img, stamp = source.provide()
                    replay_progress["index"] = getattr(source, "index", replay_progress["index"] + 1)
                    replay_progress["pending"] = None
                    return hwnd, img, stamp

                from vision_worker_loop import run_vision_capture_loop
                await run_vision_capture_loop(
                    pipeline=pipeline,
                    ws=ws,
                    stop_flag=stop_flag,
                    frame_provider=_replay_frame,
                    archiver=archiver,
                    fps=CONFIG.get("vision", {}).get("captureFps", 10),
                    log_fn=log_stage,
                    debug_mode=DEBUG_MODE,
                    process_live_game_frame_fn=lambda *args, **kwargs: process_live_game_frame(
                        *args, **kwargs, run_capture_orchestration=False, sync_facts=False, compute_shadow=False
                    ),
                    early_process_live_game_frame_fn=process_early_warehouse_frame,
                    auto_save_settlement=CONFIG.get("archiver", {}).get("autoSave", True),
                    current_match=CURRENT_MATCH,
                    state_publisher=state_publisher,
                    match_session=replay_session,
                    live_control=live_control,
                    sync_context_fn=sync_vision_to_current_match,
                    before_archive_fn=prediction_transport.collect,
                )
                await _flush_settlement_if_needed("shutdown" if stop_flag.get("stop") else "replay-eof")
                log_stage("WORKER:VISION", f"Replay finished source_eof={getattr(source, 'eof', True)}")
                return True
            else:
                # 真实游戏屏幕监控模式 (严格执行 Game Presence & 纯视觉特征管道)
                CURRENT_MATCH.data_origin = "live"
                pipeline.current_context["dataOrigin"] = "live"
                pipeline.current_context["executionOrigin"] = "live"
                sct = mss.mss()
                capture_mgr = WindowCaptureManager()
                last_capture_source = {"name": None}

                def _capture_game_frame():
                    from game_frame_capture import capture_tracked_game_frame
                    game_hwnd, img, captured_at, source = capture_tracked_game_frame(
                        tracker, capture_mgr, sct, win32gui.IsWindow)
                    if source != last_capture_source["name"]:
                        log_stage("WORKER:VISION", f"capture source={source}")
                        last_capture_source["name"] = source
                    return game_hwnd, img, captured_at

                def _commit_refresh_allowed(request_id):
                    latest = refresh_state.get("latest_id")
                    if request_id and latest and request_id != latest:
                        log_stage("WORKER:VISION", f"stale refresh dropped request_id={request_id} latest={latest}")
                        return False
                    refresh_state["committed_id"] = request_id
                    return True

                async def _run_refresh_transaction(request_id: str):
                    t_req = time.perf_counter()
                    pipeline.reset_session_state()
                    hwnd, img, shot_at = _capture_game_frame()
                    t_shot = time.perf_counter()
                    log_stage(
                        "WORKER:VISION",
                        f"refresh capture request_id={request_id} shot_ms={(t_shot - t_req) * 1000:.1f} present={hwnd is not None}",
                    )
                    if img is None:
                        if not _commit_refresh_allowed(request_id):
                            return False
                        payload = {
                            "solverStatus": "refreshing",
                            "refreshRequestId": request_id,
                            "refreshPending": False,
                            "inAuction": False,
                            "inLobby": False,
                            "gameDetected": False,
                            "lobbyCharacter": None,
                            "lobbyCharacterLabel": "未识别",
                            "actionDirective": "未识别到游戏画面",
                            "actionReason": f"刷新事务 {request_id} 无可用截图",
                        }
                        await ws.send(json.dumps(payload))
                        log_stage("WORKER:VISION", f"refresh committed request_id={request_id} status=no_frame")
                        return True
                    log_stage("WORKER:VISION", f"refresh infer start request_id={request_id}")
                    ctx = pipeline.process_frame(img, captured_at=shot_at, force_refresh=True)
                    t_done = time.perf_counter()
                    char_label = ctx.get("lobbyCharacter")
                    accepted = bool(char_label)
                    log_stage(
                        "WORKER:VISION",
                        f"refresh infer done request_id={request_id} infer_ms={(t_done - t_shot) * 1000:.1f} "
                        f"char={char_label} score={ctx.get('lobbyCharacterScore')} "
                        f"second={ctx.get('lobbyCharacterSecondScore')} source={ctx.get('lobbyCharacterSource')}",
                    )
                    if not _commit_refresh_allowed(request_id):
                        return False
                    if is_in_auction_hud(ctx):
                        hud_payload = build_in_auction_hud_payload(ctx, compute_shadow=False)
                    else:
                        hud_payload = build_nav_hud_payload(ctx)
                    hud_payload["refreshRequestId"] = request_id
                    hud_payload["refreshPending"] = False
                    if hud_payload.get("inLobby") or hud_payload.get("scene") == "AUCTION_LOBBY":
                        hud_payload["lobbyCharacter"] = char_label
                        hud_payload["lobbyCharacterLabel"] = char_label or "未识别"
                        hud_payload["lobbyCharacterScore"] = ctx.get("lobbyCharacterScore")
                        hud_payload["lobbyCharacterSecondScore"] = ctx.get("lobbyCharacterSecondScore")
                        hud_payload["lobbyCharacterSource"] = ctx.get("lobbyCharacterSource") or ("unrecognized" if not accepted else "template")
                    await publish_worker_payload(hud_payload)
                    log_stage(
                        "WORKER:VISION",
                        f"refresh committed request_id={request_id} status={'ok' if accepted else 'unrecognized'} "
                        f"total_ms={(t_done - t_req) * 1000:.1f}",
                    )
                from vision_worker_loop import run_vision_capture_loop

                await run_vision_capture_loop(
                    pipeline=pipeline,
                    ws=ws,
                    stop_flag=stop_flag,
                    frame_provider=_capture_game_frame,
                    archiver=archiver,
                    refresh_state=refresh_state,
                    run_refresh_transaction_fn=_run_refresh_transaction,
                    fps=CONFIG.get("vision", {}).get("captureFps", 10),
                    log_fn=log_stage,
                    debug_mode=DEBUG_MODE,
                    process_live_game_frame_fn=lambda *args, **kwargs: process_live_game_frame(
                        *args, **kwargs, run_capture_orchestration=False, sync_facts=False, compute_shadow=False
                    ),
                    early_process_live_game_frame_fn=process_early_warehouse_frame,
                    auto_save_settlement=CONFIG.get("archiver", {}).get("autoSave", True),
                    current_match=CURRENT_MATCH,
                    state_publisher=state_publisher,
                    match_session=replay_session,
                    live_control=live_control,
                    sync_context_fn=sync_vision_to_current_match,
                    before_archive_fn=prediction_transport.collect,
                )
                await _flush_settlement_if_needed("shutdown")

    while not stop_flag.get("stop"):
        try:
            if asyncio.run(_loop()) is True:
                break
        except Exception as exc:
            log_stage("WORKER:VISION", f"Vision transport reconnecting: {type(exc).__name__}: {exc}")
        if not stop_flag.get("stop"):
            time.sleep(0.5)

class HudJsApi:
    """供悬浮窗前端 JS 调用的原生桌面 API"""
    def __init__(self, tracker=None, config=None, base_dir=None):
        self.tracker = tracker
        self.config = config or {}
        self.base_dir = base_dir or ""
        self.form = None
        self.shutdown_request = None

    def set_form(self, form):
        self.form = form

    def set_shutdown_request(self, shutdown_request):
        self.shutdown_request = shutdown_request

    def _find_hwnd(self):
        if self.form:
            try:
                return self.form.Handle.ToInt64()
            except Exception:
                pass
        try:
            hwnd = win32gui.FindWindow(None, "⚡ 异环拍卖战术助手 HUD")
            if hwnd:
                return hwnd
        except Exception:
            pass
        return None

    def start_live_vision(self):
        return start_vision_worker() is not None

    def begin_drag(self):
        if self.form and hasattr(self.form, "ActivateOverlay"):
            try:
                self.form.ActivateOverlay()
            except Exception:
                pass
        hwnd = self._find_hwnd()
        if not hwnd:
            return False
        try:
            ctypes.windll.user32.ReleaseCapture()
            ctypes.windll.user32.SendMessageW(hwnd, win32con.WM_NCLBUTTONDOWN, win32con.HTCAPTION, 0)
            return True
        except Exception:
            return False

    def get_pos(self):
        if self.form:
            try:
                return [int(self.form.Location.X), int(self.form.Location.Y)]
            except Exception:
                pass
        return [100, 100]

    def set_pos(self, x, y):
        if self.form:
            try:
                from System.Drawing import Point
                self.form.Location = Point(int(x), int(y))
            except Exception:
                pass

    def resize_hud(self, w=None, h=None):
        if not self.form:
            return False
        try:
            from System.Drawing import Size
            width = int(w or self.form.Width)
            height = int(h or self.form.Height)
            self.form.Size = Size(max(320, width), max(64, height))
            return True
        except Exception as e:
            log_stage("STARTUP:HUD", f"resize_hud failed: {e}")
            return False

    def capture_overlay_preview(self, path=None):
        """Review-only: dump WebView pixels. Strictly gated by QA/debug environment."""
        if not (os.environ.get("NTE_DEBUG") or os.environ.get("NTE_ALLOW_HUD_CAPTURE")):
            log_stage("STARTUP:HUD", "capture_overlay_preview rejected: dev/QA mode only")
            return None
        if not self.form or not hasattr(self.form, "CapturePreviewToFile"):
            return None
        out = path or os.path.join(PROJECT_ROOT, "tests", "alpha_live_shots", "overlay_preview.png")
        try:
            saved = self.form.CapturePreviewToFile(out)
            log_stage("STARTUP:HUD", f"overlay preview saved {saved}")
            return saved
        except Exception as e:
            log_stage("STARTUP:HUD", f"overlay preview failed: {e}")
            return None

    def eval_overlay_js(self, script=None):
        """Review-only: execute script in WebView. Strictly gated by QA/debug environment."""
        if not (os.environ.get("NTE_DEBUG") or os.environ.get("NTE_ALLOW_HUD_CAPTURE")):
            log_stage("STARTUP:HUD", "eval_overlay_js rejected: dev/QA mode only")
            return None
        if not self.form or not hasattr(self.form, "ExecuteScript"):
            return None
        try:
            return self.form.ExecuteScript(str(script or ""))
        except Exception as e:
            log_stage("STARTUP:HUD", f"eval_overlay_js failed: {e}")
            return None

    def eval_main_js(self, script=None):
        """Review-only: execute script in the native Main WebView."""
        if not (os.environ.get("NTE_DEBUG") or os.environ.get("NTE_ALLOW_HUD_CAPTURE")):
            log_stage("STARTUP:MAIN", "eval_main_js rejected: dev/QA mode only")
            return None
        win = getattr(self, "_main_window", None)
        if win is None or not hasattr(win, "execute_script"):
            return None
        try:
            return win.execute_script(str(script or ""))
        except Exception as e:
            log_stage("STARTUP:MAIN", f"eval_main_js failed: {e}")
            return None

    def move_rel(self, dx, dy):
        if self.form:
            try:
                from System.Drawing import Point
                self.form.Location = Point(int(self.form.Location.X + dx), int(self.form.Location.Y + dy))
            except Exception:
                pass

    def report_hud_status(self, status=None, **kwargs):
        """HUD 页面完成加载并上报自检结果"""
        if status is None and kwargs:
            status = kwargs
        elif isinstance(status, str):
            try:
                status = json.loads(status)
            except Exception:
                status = {}
        elif not isinstance(status, dict):
            status = {}
        log_stage("STARTUP:HUD", "HUD window appeared: True")
        log_stage("STARTUP:HUD", f"pywebview/WebView2 ready: {status.get('pywebviewReady', True)}")
        log_stage("STARTUP:HUD", f"auction_engine_v06.js loaded: {status.get('auctionEngineLoaded')}")
        st = status.get("sharedCoreSelfTests", {})
        log_stage("STARTUP:HUD", f"Shared Core self-test result: {st.get('tested', 0)} tests, passed={st.get('passed', False)}")
        log_stage("STARTUP:HUD", f"15:53 regression result: {'PASS' if status.get('regression1553Passed') else 'FAIL'}")
        log_stage("STARTUP:HUD", "WebSocket ready: True")
        log_stage("STARTUP:HUD", "HUD responsive: True")
        log_stage("STARTUP:HUD", f"startup duration: {(time.perf_counter() - PROCESS_START_TIME) * 1000:.2f}ms")
        start_vision_worker()
        return {"status": "ok"}

    def exit_app(self):
        """退出战术助手"""
        log_stage("SHUTDOWN:MAIN", "Overlay requested application shutdown")
        if self.shutdown_request:
            return self.shutdown_request("overlay_exit_app", True)
        log_stage("SHUTDOWN:MAIN", "shutdown request ignored: coordinator unavailable")
        return False

    def snap_to_game(self):
        """重新吸附至游戏右上角"""
        w_cfg = self.config.get("window", {})
        pos = self.tracker.get_snap_position(
            hud_width=w_cfg.get("hudWidth", 390),
            hud_height=w_cfg.get("hudHeight", 450),
            padding_right=w_cfg.get("snapPaddingRight", 20),
            padding_top=w_cfg.get("snapPaddingTop", 40)
        )
        if pos and self.form:
            try:
                from System.Drawing import Point
                self.form.Location = Point(int(pos[0]), int(pos[1]))
                return True
            except Exception:
                pass
        return False

    def triggered_snapshot(self):
        """主动触发单帧游戏截图识别"""
        return handle_triggered_snapshot()

    def experimental_profile_set(self, payload=None, **kwargs):
        """Toggle experimental probability/strategy profile.

        Strictly whitelist-gated. Invalid profiles fail closed without state mutation.
        """
        if payload is None and kwargs:
            payload = kwargs
        elif isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        elif not isinstance(payload, dict):
            payload = {}

        profile_id = str(payload.get("profileId", ""))
        enabled = bool(payload.get("enabled", False))

        from experimental_probability_strategy import (
            ALLOWED_EXPERIMENTAL_PROFILES,
            get_global_strategy_registry,
        )

        reg = get_global_strategy_registry()
        if profile_id not in ALLOWED_EXPERIMENTAL_PROFILES or profile_id == "baseline":
            log_stage("STRATEGY_EXP", f"Rejected profile mutation: '{profile_id}'")
            return {
                "success": False,
                "error": f"Invalid or restricted profile ID: '{profile_id}'",
                "activeProfiles": reg.get_active_profile_ids(),
            }

        if enabled:
            ok = reg.enable_profile(profile_id)
        else:
            ok = reg.disable_profile(profile_id)

        log_stage("STRATEGY_EXP", f"Profile '{profile_id}' set to enabled={enabled} (ok={ok})")
        return {
            "success": ok,
            "profileId": profile_id,
            "enabled": enabled,
            "activeProfiles": reg.get_active_profile_ids(),
            "profileGeneration": reg.profile_generation,
        }

    def invoke_action(self, action_name, payload=None, **kwargs):
        """Generic action dispatcher for WebView frontend."""
        if action_name == "experimental_profile_set":
            return self.experimental_profile_set(payload, **kwargs)
        return {"success": False, "error": f"Unknown action: {action_name}"}

    def capture_game(self):
        return handle_triggered_snapshot()

    def open_config(self):
        """用记事本打开配置文件"""
        cfg_path = os.path.join(self.base_dir, "config.json")
        try:
            os.startfile(cfg_path)
        except Exception:
            pass

    def set_main_window(self, main_window):
        self._main_window = main_window

    def force_refresh(self, request_id=None):
        """主动触发重新感知：立即开一个带 request id 的识别事务。"""
        return request_force_refresh(request_id)

    def apply_manual_facts(self, facts=None):
        payload = apply_manual_facts(facts if isinstance(facts, dict) else {})
        if getattr(self, "_main_window", None) is not None:
            try:
                self._main_window.post_status("match_facts_updated")
            except Exception:
                pass
        return publish_manual_payload(payload)

    def finalize_manual_match(self, request=None):
        payload = finalize_manual_match(request if isinstance(request, dict) else {})
        if getattr(self, "_main_window", None) is not None:
            try:
                self._main_window.post_status("match_finalized")
            except Exception:
                pass
        return publish_manual_payload(payload)

    def begin_next_manual_match(self, request=None):
        payload = begin_next_manual_match(request if isinstance(request, dict) else {})
        if getattr(self, "_main_window", None) is not None:
            try:
                self._main_window.post_status("next_match_started")
            except Exception:
                pass
        return publish_manual_payload(payload)

    def manual_bootstrap(self):
        payload = build_manual_alpha_payload()
        return publish_manual_payload(payload)

    def open_lab(self):
        """在默认浏览器打开完整拍卖实验室"""
        candidates = [
            LAB_PATH,
            os.path.abspath(os.path.join(self.base_dir, "..", "lab", "index.html")),
        ]
        target_path = None
        for p in candidates:
            if os.path.exists(p):
                target_path = p
                break
        if target_path:
            try:
                webbrowser.open(f"file:///{target_path.replace(os.sep, '/')}")
            except Exception:
                pass

    def strategy_edit(self, request=None):
        req = request if isinstance(request, dict) else {}
        field_name = req.get("field")
        val = req.get("value")
        if not field_name:
            return {"status": "error", "error": "Missing field parameter"}
        from strategy_ux_metrics import get_authoritative_strategy_store
        store = get_authoritative_strategy_store()
        success, err = store.edit_typed(str(field_name), val)
        if not success:
            return {"status": "error", "error": err or "Validation failed"}
        return self._broadcast_strategy_state()

    def strategy_undo(self, request=None):
        from strategy_ux_metrics import get_authoritative_strategy_store
        cmd = get_authoritative_strategy_store().undo()
        res = self._broadcast_strategy_state()
        res["undoneCommand"] = {"field": cmd.field, "oldValue": cmd.old_value, "newValue": cmd.new_value} if cmd else None
        return res

    def strategy_redo(self, request=None):
        from strategy_ux_metrics import get_authoritative_strategy_store
        cmd = get_authoritative_strategy_store().redo()
        res = self._broadcast_strategy_state()
        res["redoneCommand"] = {"field": cmd.field, "oldValue": cmd.old_value, "newValue": cmd.new_value} if cmd else None
        return res

    def _broadcast_strategy_state(self):
        from strategy_ux_metrics import get_authoritative_strategy_store, StrategyPanelShellState, compute_strategy_metrics_summary
        hist = get_authoritative_strategy_store()
        val_p50 = LATEST_PAYLOAD.get("valP50") if isinstance(LATEST_PAYLOAD, dict) else None
        metrics = compute_strategy_metrics_summary(
            mode=hist.state.estimate_mode,
            val_p50=val_p50,
        )
        panel = StrategyPanelShellState(
            is_panel_expanded=hist.state.is_panel_expanded,
            estimate_mode=hist.state.estimate_mode.value,
            fast_mode_available=False,
            strategy_round=hist.state.strategy_round,
            strategy_venue=hist.state.strategy_venue,
            strategy_profile=hist.state.strategy_profile.value,
            strategy_source="user_strategy",
            metrics_summary=metrics,
            production_estimate=float(val_p50) if val_p50 is not None else None,
            is_experimental_expanded=hist.state.is_experimental_expanded,
            can_undo=hist.can_undo,
            can_redo=hist.can_redo,
        )
        if isinstance(LATEST_PAYLOAD, dict):
            LATEST_PAYLOAD["estimateMode"] = hist.state.estimate_mode.value
            LATEST_PAYLOAD["strategyMetrics"] = metrics.to_payload()
            LATEST_PAYLOAD["strategyPanel"] = panel.to_payload()
        if WS_EVENT_LOOP and WS_EVENT_LOOP.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_ws(json.dumps(LATEST_PAYLOAD)), WS_EVENT_LOOP)
        return {"status": "ok", "strategyPanel": panel.to_payload()}


def start_vision_worker():
    with _VISION_PROCESS_LOCK:
        return _start_vision_worker_locked()


def _set_vision_process_health(stage):
    health = {'status': 'ERROR', 'stage': stage}
    LATEST_PAYLOAD['visionHealth'] = health
    if WS_EVENT_LOOP and WS_EVENT_LOOP.is_running():
        asyncio.run_coroutine_threadsafe(broadcast_ws(json.dumps({'type': 'vision_health', 'visionHealth': health})), WS_EVENT_LOOP)


def _observe_vision_process_exit(worker):
    worker.wait()
    with _VISION_PROCESS_LOCK:
        if VISION_PROCESS is worker:
            PRESENTATION_RUNTIME.set_vision_process_state('exited')
            _set_vision_process_health('process')


def _start_vision_worker_locked():
    """把 RapidOCR 放到完全独立的进程，避免和 WebView2 共享 Python/COM 消息循环。"""
    global VISION_PROCESS
    if os.environ.get("NTE_DISABLE_VISION") == "1":
        PRESENTATION_RUNTIME.set_vision_process_state("disabled")
        log_stage("STARTUP:VISION", "Vision disabled via NTE_DISABLE_VISION=1")
        return None
    if VISION_PROCESS is not None and VISION_PROCESS.poll() is None:
        PRESENTATION_RUNTIME.set_vision_process_state("running")
        return VISION_PROCESS
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--vision-worker"]
    else:
        command = [sys.executable, os.path.abspath(__file__), "--vision-worker"]
    if DEBUG_MODE:
        command.append("--debug")
    env = os.environ.copy()
    if DEBUG_MODE:
        env["NTE_DEBUG"] = "1"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    try:
        log_stage("STARTUP:VISION", f"Spawning vision worker: {' '.join(command)} debug={DEBUG_MODE}")
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_handle:
            VISION_PROCESS = subprocess.Popen(
                command,
                cwd=BASE_DIR,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                creationflags=flags,
                startupinfo=startupinfo,
                close_fds=False,
                env=env,
            )
        PRESENTATION_RUNTIME.set_vision_process_state("running")
        log_stage("STARTUP:VISION", f"Vision worker started (PID={VISION_PROCESS.pid})")
        _set_vision_process_health('starting')
        if hasattr(VISION_PROCESS, 'wait'):
            threading.Thread(target=_observe_vision_process_exit, args=(VISION_PROCESS,), daemon=True,
                             name='vision-process-exit').start()
    except Exception as e:
        log_stage("STARTUP:VISION", f"Vision worker start failed: {e}")
        VISION_PROCESS = None
        PRESENTATION_RUNTIME.set_vision_process_state("stopped")
        _set_vision_process_health('process')
    return VISION_PROCESS


def request_flush_settlement() -> None:
    if WS_EVENT_LOOP and WS_EVENT_LOOP.is_running():
        try:
            asyncio.run_coroutine_threadsafe(
                broadcast_ws(json.dumps({"action": "flush_settlement"})),
                WS_EVENT_LOOP,
            )
        except Exception as e:
            log_stage("SHUTDOWN:VISION", f"flush_settlement broadcast failed: {e}")


def stop_vision_worker():
    with _VISION_PROCESS_LOCK:
        return _stop_vision_worker_locked()


def _stop_vision_worker_locked():
    global VISION_PROCESS
    worker, VISION_PROCESS = VISION_PROCESS, None
    PRESENTATION_RUNTIME.set_vision_process_state(
        "disabled" if os.environ.get("NTE_DISABLE_VISION") == "1" else "stopped"
    )
    if worker is None:
        return
    log_stage("SHUTDOWN:VISION", f"Stopping vision worker (PID={worker.pid})...")
    request_flush_settlement()
    time.sleep(0.4)
    try:
        if worker.poll() is None:
            worker.terminate()
            worker.wait(timeout=2.0)
            log_stage("SHUTDOWN:VISION", "Vision worker terminated cleanly")
    except Exception as e:
        log_stage("SHUTDOWN:VISION", f"Vision worker terminate exception ({e}), killing...")
        try:
            worker.kill()
            worker.wait(timeout=1.0)
            log_stage("SHUTDOWN:VISION", "Vision worker killed")
        except Exception as e2:
            log_stage("SHUTDOWN:VISION", f"Vision worker kill error: {e2}")


def stop_manual_shadow_runtime():
    """Dispose the parent-process historical support runtime, if Manual started it."""
    try:
        from live_shadow import reset_live_shadow_state
        reset_live_shadow_state()
    except Exception as exc:
        log_stage("SHUTDOWN:SHADOW", f"manual shadow cleanup failed: {type(exc).__name__}")


def setup_dotnet_webview2():
    """初始化 CLR / .NET 运行时及 WebView2 DirectComposition 控制器依赖"""
    import clr
    clr.AddReference('System.Windows.Forms')
    clr.AddReference('System.Drawing')
    clr.AddReference('System.IO')
    
    # 1. Locate Microsoft.Web.WebView2.Core.dll
    wv2_candidates = [
        os.path.join(getattr(sys, '_MEIPASS', ''), 'webview', 'lib', 'Microsoft.Web.WebView2.Core.dll'),
        os.path.join(BASE_DIR, '_internal', 'webview', 'lib', 'Microsoft.Web.WebView2.Core.dll'),
        os.path.join(BASE_DIR, 'webview', 'lib', 'Microsoft.Web.WebView2.Core.dll'),
        r'C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll',
    ]
    core_dll = next((p for p in wv2_candidates if os.path.isfile(p)), None)
    if not core_dll:
        raise RuntimeError("Microsoft.Web.WebView2.Core.dll not found")
    clr.AddReference(core_dll)

    winforms_dll = os.path.join(os.path.dirname(core_dll), 'Microsoft.Web.WebView2.WinForms.dll')
    if os.path.isfile(winforms_dll):
        clr.AddReference(winforms_dll)

    lib_dir = os.path.dirname(core_dll)
    native_dir = os.path.join(lib_dir, 'runtimes', 'win-x64', 'native')
    if os.path.isdir(native_dir):
        os.environ['Path'] = native_dir + ';' + os.environ.get('Path', '')

    # 2. Locate DirectCompositionHost.dll
    dcomp_candidates = [
        os.path.join(getattr(sys, '_MEIPASS', ''), 'DirectCompositionHost.dll'),
        os.path.join(BASE_DIR, '_internal', 'DirectCompositionHost.dll'),
        os.path.join(BASE_DIR, 'DirectCompositionHost.dll'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'DirectCompositionHost.dll'),
        os.path.join(PROJECT_ROOT, 'app', 'DirectCompositionHost.dll'),
    ]
    dcomp_dll = next((p for p in dcomp_candidates if os.path.isfile(p)), None)
    if not dcomp_dll:
        raise RuntimeError(f"DirectCompositionHost.dll not found (checked: {dcomp_candidates})")
    dcomp_dir = os.path.dirname(os.path.abspath(dcomp_dll))
    os.environ["Path"] = dcomp_dir + ";" + os.environ.get("Path", "")
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(dcomp_dir)
        except Exception:
            pass
    # pythonnet AddReference 走 Assembly.Load(名字)，不会按完整路径加载。
    # 必须 LoadFrom，否则工作目录/探测路径不对时会报找不到 DirectCompositionHost.dll。
    from System.Reflection import Assembly
    Assembly.LoadFrom(os.path.abspath(dcomp_dll))
    log_stage("STARTUP:MAIN", f"DirectCompositionHost loaded from {dcomp_dll}")


def run_hud_app():
    """Run one native Main Window and one existing DirectComposition Overlay."""
    setup_dotnet_webview2()

    from System.Threading import Thread, ThreadStart, ApartmentState
    from System import IntPtr
    import System.Drawing as Drawing
    import System.Windows.Forms as WinForms
    from Microsoft.Web.WebView2.Core import CoreWebView2Environment
    from NTE.DirectComposition import DirectCompositionHudForm
    from desktop_pet import DesktopPetController
    from main_window import (
        OverlayVisibilityController,
        ShutdownCoordinator,
        create_main_window_type,
        load_mascot_presentation_contract,
    )
    from mascot_presentation_state import MascotPresentationStateCoordinator

    user32 = ctypes.windll.user32
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)

    w_cfg = CONFIG.get("window", {})
    hud_w = w_cfg.get("hudWidth", 390)
    hud_h = w_cfg.get("hudHeight", 450)

    global HUD_JS_API
    snap_tracker = GameWindowTracker(target_titles=w_cfg.get("targetTitles", ["异环"]))
    js_api = HudJsApi(tracker=snap_tracker, config=CONFIG, base_dir=BASE_DIR)
    HUD_JS_API = js_api

    snap_pos = None
    if w_cfg.get("autoSnap", True):
        snap_pos = snap_tracker.get_snap_position(
            hud_width=hud_w,
            hud_height=hud_h,
            padding_right=w_cfg.get("snapPaddingRight", 20),
            padding_top=w_cfg.get("snapPaddingTop", 40)
        )
    
    if snap_pos:
        init_x, init_y = snap_pos
    else:
        init_x = screen_w - hud_w - 40
        init_y = 60

    init_x = max(20, min(screen_w - hud_w - 20, init_x))
    init_y = max(20, min(screen_h - hud_h - 20, init_y))

    html_path = os.path.abspath(os.path.join(CORE_DIR, "overlay_alpha.html"))
    main_html_path = os.path.abspath(os.path.join(CORE_DIR, "main_window.html"))
    data_folder = os.path.join(tempfile.gettempdir(), "nte_webview2_data")
    os.makedirs(data_folder, exist_ok=True)

    log_stage("STARTUP:MAIN", f"Creating DirectComposition Visual HUD window (html={html_path}, pos=({init_x}, {init_y}), size=({hud_w}x{hud_h}))")

    def _gui_thread():
        MainWindow = create_main_window_type(WinForms, Drawing)
        main_window = MainWindow()
        _MAIN_WINDOW_HOLDER.clear()
        _MAIN_WINDOW_HOLDER.append(main_window)
        mascot_presentation = load_mascot_presentation_contract(PROJECT_ROOT)
        mascot_state_coordinator = MascotPresentationStateCoordinator(
            mascot_presentation
        )

        def get_mascot_presentation_snapshot(application_state="ready"):
            return mascot_state_coordinator.update(
                application_state, get_presentation_runtime_snapshot()
            )

        overlay_form = DirectCompositionHudForm(init_x, init_y, hud_w, hud_h, w_cfg.get("onTop", True))
        js_api.set_form(overlay_form)

        try:
            from live_shadow import warmup_shadow_runtime
            warmup_shadow_runtime(CANONICAL_DATABASE)
            log_stage("STARTUP:MAIN", "Node compute runtime warmed; Overlay is presentation-only")
        except Exception as ex:
            log_stage("STARTUP:MAIN", f"Node compute warmup warning: {ex}")

        visibility_controller = OverlayVisibilityController(
            overlay_form,
            on_visibility_changed=main_window.set_overlay_visible,
        )
        shutdown_ref = {"coordinator": None}

        def on_overlay_closing(s, e):
            coordinator = shutdown_ref["coordinator"]
            if coordinator is not None and coordinator.started:
                return
            e.Cancel = True
            visibility_controller.hide()
            log_stage("ACTION:USER", "Overlay close redirected to Hide; application remains open")
        overlay_form.FormClosing += on_overlay_closing

        overlay_form.Show()

        # 0.67 Alpha 默认允许正常截图与录屏 (WDA_NONE = 0)
        try:
            hud_hwnd = int(overlay_form.Handle.ToInt64())
            capture_mgr = WindowCaptureManager()
            ok = capture_mgr.set_hud_capturable(hud_hwnd)
            log_stage("STARTUP:MAIN", f"HUD displayAffinity=WDA_NONE({ok}) HWND={hud_hwnd}")
        except Exception as ex:
            log_stage("STARTUP:MAIN", f"SetWindowDisplayAffinity warning: {ex}")

        try:
            _log_overlay_host_state(int(overlay_form.Handle.ToInt64()), "after-show")
        except Exception:
            pass

        log_stage("STARTUP:MAIN", "Creating CoreWebView2Environment...")
        env_task = CoreWebView2Environment.CreateAsync(None, data_folder, None)
        while not env_task.IsCompleted:
            WinForms.Application.DoEvents()
        env = env_task.Result
        log_stage("STARTUP:MAIN", "CoreWebView2Environment created (S_OK)")

        log_stage("STARTUP:MAIN", "Initializing DirectComposition Device, Visual Target & Presentation...")
        overlay_form.InitializeComposition(env, html_path, WS_PORT)
        log_stage("STARTUP:MAIN", "DirectComposition Visual Tree & Composition Controller created (S_OK)")

        def on_web_message(msg_str):
            try:
                data = json.loads(msg_str)
                action = data.get("action")
                coordinator = shutdown_ref["coordinator"]
                if coordinator is not None and coordinator.started and action != "exit_app":
                    return
                if action == "exit_app":
                    js_api.exit_app()
                elif action == "snap_to_game":
                    js_api.snap_to_game()
                elif action == "open_config":
                    js_api.open_config()
                elif action == "open_lab":
                    js_api.open_lab()
                elif action == "report_hud_status":
                    js_api.report_hud_status(data.get("status"))
                elif action == "force_refresh":
                    js_api.force_refresh(data.get("refreshRequestId") or data.get("requestId"))
                elif action == "manual_facts":
                    js_api.apply_manual_facts(data)
                elif action == "manual_finalize":
                    js_api.finalize_manual_match(data)
                elif action == "manual_next_match":
                    js_api.begin_next_manual_match(data)
                elif action == "manual_bootstrap":
                    js_api.manual_bootstrap()
                elif action in ("triggered_snapshot", "capture_hud"):
                    js_api.triggered_snapshot()
                elif action == "start_live_vision":
                    start_vision_worker()
                elif action == "begin_drag":
                    if hasattr(overlay_form, "ActivateOverlay"):
                        overlay_form.ActivateOverlay()
                    if hasattr(overlay_form, "BeginDrag"):
                        overlay_form.BeginDrag()
                    else:
                        js_api.begin_drag()
                elif action == "move_rel":
                    js_api.move_rel(int(data.get("dx", 0)), int(data.get("dy", 0)))
                elif action == "set_pos":
                    js_api.set_pos(int(data.get("x", 0)), int(data.get("y", 0)))
                elif action == "resize_hud":
                    js_api.resize_hud(data.get("w"), data.get("h"))
                elif action == "capture_overlay_preview":
                    js_api.capture_overlay_preview(data.get("path"))
                elif action == "eval_overlay_js":
                    js_api.eval_overlay_js(data.get("script"))
            except Exception as ex:
                log_stage("STARTUP:MAIN", f"WebMessage dispatch error: {ex}")
        overlay_form.WebMessageReceivedCallback += on_web_message

        desktop_pet = DesktopPetController(
            WinForms,
            Drawing,
            main_window,
            mascot_presentation,
            get_mascot_presentation_snapshot,
            logger=log_stage,
        )
        desktop_pet.create()
        main_window.bind_desktop_pet(desktop_pet)

        def begin_shutdown():
            desktop_pet.begin_shutdown()
            visibility_controller.stop_accepting_commands()
            main_window.begin_shutdown()

        def close_overlay():
            try:
                overlay_form.WebMessageReceivedCallback -= on_web_message
            except Exception:
                pass
            js_api.set_form(None)
            if hasattr(overlay_form, "CloseCompositionResources"):
                overlay_form.CloseCompositionResources()
            if not overlay_form.IsDisposed:
                overlay_form.Close()
                overlay_form.Dispose()

        def close_main_presentation():
            main_window.close_presentation_resources()

        def close_main():
            _MAIN_WINDOW_HOLDER.clear()
            if not main_window.IsDisposed and not main_window.Disposing:
                main_window.Close()

        shutdown_coordinator = ShutdownCoordinator(
            begin_shutdown=begin_shutdown,
            cleanup_steps=(
                ("flush-manual-draft", flush_draft_save_sync),
                ("cancel-warehouse-capture", WAREHOUSE_CAPTURE_HOST.stop),
                ("stop-vision-worker", stop_vision_worker),
                ("stop-manual-shadow-runtime", stop_manual_shadow_runtime),
                ("stop-websocket-bus", stop_ws_loop),
                ("close-desktop-pet", desktop_pet.close),
                ("close-main-presentation", close_main_presentation),
                ("close-overlay", close_overlay),
            ),
            close_main=close_main,
            logger=log_stage,
        )
        shutdown_ref["coordinator"] = shutdown_coordinator
        js_api.set_shutdown_request(shutdown_coordinator.request)
        from legacy_archive import LegacyArchive
        from settlement_review import SettlementReviewService

        legacy_archive = LegacyArchive()
        settlement_review_service = SettlementReviewService(
            legacy_archive=legacy_archive,
        )
        main_window.bind_lifecycle(
            visibility_controller,
            shutdown_coordinator.request,
            get_presentation_runtime_snapshot,
            MAIN_VIEW_STATE_PROVIDER.snapshot,
            get_mascot_presentation_snapshot,
            current_match_provider=get_current_match_presentation_summary,
            delete_history_provider=handle_delete_history_record,
            delete_history_records_provider=handle_delete_history_records,
            settlement_review_service=settlement_review_service,
            legacy_archive_provider=lambda: legacy_archive,
            manual_facts_provider=lambda facts: publish_manual_payload(apply_manual_facts(facts)),
            start_vision_provider=lambda: start_vision_worker() is not None,
            manual_next_match_provider=lambda req: publish_manual_payload(begin_next_manual_match(req)),
            manual_finalize_provider=lambda req: publish_manual_payload(finalize_manual_match(req)),
            manual_bootstrap_provider=lambda: publish_manual_payload(build_manual_alpha_payload()),
            triggered_snapshot_provider=handle_main_triggered_snapshot,
            save_settlement_screenshot_provider=handle_save_settlement_screenshot,
            save_game_screenshot_provider=handle_save_game_screenshot,
            warehouse_capture_host=WAREHOUSE_CAPTURE_HOST,
            warehouse_identity_review_session=WAREHOUSE_IDENTITY_REVIEW,
            warehouse_identity_review_history_store=WAREHOUSE_IDENTITY_HISTORY,
        )
        js_api.set_main_window(main_window)
        main_window.Show()
        main_window.initialize_presentation(
            env,
            main_html_path,
            log_stage,
            smoke_mode=os.environ.get("NTE_MAIN_UI_SMOKE") == "1",
            mascot_presentation=mascot_presentation,
        )
        if getattr(main_window, "_bridge", None) is not None:
            main_window.set_topmost(main_window._bridge.effective_topmost)

        log_stage("STARTUP:MAIN", "Running WinForms application message loop with native Main Window owner...")
        WinForms.Application.Run(main_window)
        try:
            from live_shadow import unregister_webview_host
            unregister_webview_host()
        except Exception:
            pass
        shutdown_coordinator.request("message_loop_returned", False)
        log_stage("SHUTDOWN:MAIN", "WinForms application message loop returned, clean exit")

    t_gui = Thread(ThreadStart(_gui_thread))
    t_gui.SetApartmentState(ApartmentState.STA)
    t_gui.Start()
    t_gui.Join()


def main():
    profile = "isolated-trial-v1" if is_isolated_trial() else "standard"
    data_root = str(resolve_runtime_data_root())
    log_stage("STARTUP:PROFILE", f"Runtime profile={profile} DATA_ROOT={data_root}")
    log_stage("STARTUP:MAIN", f"process started (PID={os.getpid()}, Frozen={getattr(sys, 'frozen', False)}, debug={DEBUG_MODE}, log={LOG_FILE_PATH})")

    # 0. 启动运行时看板娘图标注入线程
    if os.environ.get("NTE_DISABLE_ICON") != "1":
        log_stage("STARTUP:MAIN", "Starting icon injector thread...")
        t_icon = threading.Thread(target=apply_runtime_icon, daemon=True)
        t_icon.start()

    # 1. 启动后台 WebSocket 通信总线
    if os.environ.get("NTE_DISABLE_WS") != "1":
        log_stage("STARTUP:MAIN", "Starting WebSocket bus thread...")
        t_ws = threading.Thread(target=start_ws_loop, daemon=True)
        t_ws.start()

    time.sleep(0.2)

    # 2. 启动 DirectComposition 架构统一桌面悬浮窗 (无缝兼容 Medium / High 完整性)
    run_hud_app()


if __name__ == "__main__":
    if "--vision-worker" in sys.argv:
        vision_capture_worker()
    elif "--smoke-acquisition-video" in sys.argv:
        from runtime_acquisition_smoke import run_from_environment
        sys.exit(run_from_environment())
    else:
        main()

