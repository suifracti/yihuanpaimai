"""Live Historical Shadow coordinator.

Production compute is a persistent Node process. Overlay/Main only project
completed snapshots. Overlay WebView is a packaged fallback, not the owner.
The capture/OCR loop must never wait for Node / Historical Shadow.
"""
from __future__ import annotations

import hashlib
import copy
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import sys

_FROZEN_ROOT = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
if _FROZEN_ROOT:
    PROJECT_ROOT = os.path.abspath(_FROZEN_ROOT)
    CORE_DIR = os.path.join(PROJECT_ROOT, "core")
else:
    CORE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.abspath(os.path.join(CORE_DIR, ".."))
RUNTIME_JS = os.path.join(CORE_DIR, "live_shadow_runtime.js")


def _runtime_js() -> str:
    override = str(os.environ.get("YIHUAN_SHADOW_RUNTIME_JS") or "").strip()
    return override or RUNTIME_JS
APP_DIR = os.path.join(PROJECT_ROOT, "app")
for _p in (PROJECT_ROOT, CORE_DIR, APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from runtime_revision import get_code_revision
from runtime_data import resolve_runtime_history_path
from history_admission import (
    evaluate_history_admission,
    build_duplicate_index,
    HISTORY_ADMISSION_POLICY_VERSION,
)
from experiments.upper_tail_truth_support_capture_v1.runtime_capture_hook import (
    capture_prediction_support_envelope,
)

_CACHE_LOCK = threading.Lock()
_SNAPSHOT: Optional[List[Dict[str, Any]]] = None
_SNAPSHOT_PATH: Optional[str] = None
_SNAPSHOT_FILE_STAMP = None
_SNAPSHOT_DATASET_REVISION: Optional[Dict[str, Any]] = None
_SNAPSHOT_N = 0
_HISTORY_GEN = 0
_PROFILE_CACHE: Dict[str, Dict[str, Any]] = {}
_RUNTIME: Optional[subprocess.Popen] = None
_RUNTIME_LOCK = threading.Lock()
_SHADOW_LOCK = threading.Lock()
_WEBVIEW_HOST: Optional[Any] = None
_REQUEST_GEN = 0
_PENDING_KEY: Optional[str] = None
_PENDING_CTX: Optional[Dict[str, Any]] = None
_PENDING_PATH: Optional[str] = None
_IN_FLIGHT_GEN: Optional[int] = None
_IN_FLIGHT_KEY: Optional[str] = None
_WORKER_THREAD: Optional[threading.Thread] = None
_LATEST_PROFILE: Optional[Dict[str, Any]] = None
_LATEST_PREDICTION_SNAPSHOT: Optional[Dict[str, Any]] = None
_LATEST_FROZEN_PREDICTION: Optional[Dict[str, Any]] = None
_LATEST_STATES: Dict[str, Any] = {"exact": [], "expanded": []}
_LATEST_META: Dict[str, Any] = {}
_LATEST_KEY: Optional[str] = None
_LATEST_GEN = 0
_LATEST_MATCH_GEN = 0
_MATCH_GEN = 0
_PREDICTION_LISTENER: Optional[Callable[[Dict[str, Any]], None]] = None
SHADOW_SCENE_IN_AUCTION = "IN_AUCTION"
_LOG = logging.getLogger(__name__)


def _capture_collection_class() -> str:
    value = os.environ.get("YIHUAN_CAPTURE_COLLECTION_CLASS", "NATURAL_RUNTIME_CAPTURE").strip()
    return value or "NATURAL_RUNTIME_CAPTURE"


def default_history_path() -> str:
    return str(resolve_runtime_history_path())


def history_generation() -> int:
    return _HISTORY_GEN


def snapshot_size() -> int:
    return _SNAPSHOT_N


def current_snapshot() -> List[Dict[str, Any]]:
    with _CACHE_LOCK:
        return list(_SNAPSHOT or [])


def _compute_dataset_revision_locked(raw_bytes: bytes, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    file_sha256 = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else "0" * 64
    record_count = len(records)
    duplicate_index = build_duplicate_index(records)
    admitted_records = [
        r for r in records
        if isinstance(r, dict) and evaluate_history_admission(r, duplicate_index).admitted
    ]
    admitted_ids = sorted(str(r.get("id")) for r in admitted_records)
    support_eligible_ids = sorted(
        str(r.get("id"))
        for r in admitted_records
        if (
            r.get("boxEvidenceClass")
            or ((r.get("environment") or {}).get("boxEvidenceClass") if isinstance(r.get("environment"), dict) else None)
        ) != "OPERATOR_ASSERTED_CURRENT"
    )
    eligible_record_ids_sha256 = hashlib.sha256(
        json.dumps(admitted_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cutoff_iso = datetime.now(timezone.utc).isoformat()
    return {
        "sourceId": "canonical_match_history",
        "sha256": file_sha256,
        "recordCount": record_count,
        "eligibleRecordCount": len(admitted_ids),
        "supportEligibleRecordCount": len(support_eligible_ids),
        "admissionPolicyVersion": HISTORY_ADMISSION_POLICY_VERSION,
        "cutoffExclusive": cutoff_iso,
        "eligibleRecordIdsSha256": eligible_record_ids_sha256,
    }


def get_live_dataset_revision(db_path: Optional[str] = None) -> Dict[str, Any]:
    with _CACHE_LOCK:
        if _SNAPSHOT_DATASET_REVISION is not None:
            return dict(_SNAPSHOT_DATASET_REVISION)
    load_history_snapshot(db_path)
    with _CACHE_LOCK:
        return dict(_SNAPSHOT_DATASET_REVISION or {})


def _history_file_stamp(stat):
    return (stat.st_mtime_ns, stat.st_size, stat.st_ino)


def load_history_snapshot(db_path: Optional[str] = None, force: bool = False) -> List[Dict[str, Any]]:
    """Reuse unchanged history; notice atomic writes by other processes."""
    global _SNAPSHOT, _SNAPSHOT_PATH, _SNAPSHOT_DATASET_REVISION, _SNAPSHOT_N, _HISTORY_GEN, _PROFILE_CACHE
    global _SNAPSHOT_FILE_STAMP
    path = os.path.abspath(db_path or default_history_path())
    with _CACHE_LOCK:
        try:
            stamp = _history_file_stamp(os.stat(path))
        except FileNotFoundError:
            stamp = None
        if _SNAPSHOT is not None and not force and path == _SNAPSHOT_PATH and stamp == _SNAPSHOT_FILE_STAMP:
            return _SNAPSHOT
        raw_bytes = b""
        records: List[Dict[str, Any]] = []
        if os.path.exists(path):
            with open(path, "rb") as fh:
                raw_bytes = fh.read()
                stamp = _history_file_stamp(os.fstat(fh.fileno()))
            if raw_bytes:
                raw = json.loads(raw_bytes.decode("utf-8"))
                records = raw if isinstance(raw, list) else list(raw.get("records") or [])
        _SNAPSHOT = records
        _SNAPSHOT_PATH = path
        _SNAPSHOT_FILE_STAMP = stamp
        _SNAPSHOT_N = len(records)
        _SNAPSHOT_DATASET_REVISION = _compute_dataset_revision_locked(raw_bytes, records)
        _HISTORY_GEN += 1
        _PROFILE_CACHE.clear()
        _invalidate_latest_locked()
        snapshot = list(_SNAPSHOT)
    # The production WebView syncs by dataset revision in _runtime_compute.
    # Keep an already-running headless test runtime equally current.
    if _RUNTIME is not None:
        _push_runtime_records(snapshot)
    return snapshot


def ingest_archived_record(record: Optional[Dict[str, Any]], db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Apply a disk-confirmed archive record to the in-memory snapshot."""
    global _SNAPSHOT, _SNAPSHOT_PATH, _SNAPSHOT_DATASET_REVISION, _SNAPSHOT_N, _HISTORY_GEN, _PROFILE_CACHE
    if not isinstance(record, dict) or not record.get("id"):
        return None
    path = os.path.abspath(db_path or _SNAPSHOT_PATH or default_history_path())
    copy = json.loads(json.dumps(record, ensure_ascii=False))
    with _CACHE_LOCK:
        raw_bytes = b""
        if _SNAPSHOT is None or path != _SNAPSHOT_PATH:
            records: List[Dict[str, Any]] = []
            if os.path.exists(path):
                with open(path, "rb") as fh:
                    raw_bytes = fh.read()
                if raw_bytes:
                    raw = json.loads(raw_bytes.decode("utf-8"))
                    records = raw if isinstance(raw, list) else list(raw.get("records") or [])
            _SNAPSHOT = records
            _SNAPSHOT_PATH = path
            _HISTORY_GEN = 1
        rec_id = str(copy["id"])
        replaced = False
        for i, existing in enumerate(_SNAPSHOT):
            if str((existing or {}).get("id")) == rec_id:
                _SNAPSHOT[i] = copy
                replaced = True
                break
        if not replaced:
            _SNAPSHOT.append(copy)
        _SNAPSHOT_N = len(_SNAPSHOT)
        serialized_bytes = json.dumps(_SNAPSHOT, ensure_ascii=False).encode("utf-8")
        _SNAPSHOT_DATASET_REVISION = _compute_dataset_revision_locked(serialized_bytes, _SNAPSHOT)
        _HISTORY_GEN += 1
        _PROFILE_CACHE.clear()
        _invalidate_latest_locked()
        snapshot = list(_SNAPSHOT)
    _push_runtime_records(snapshot)
    return {
        "id": rec_id,
        "replaced": replaced,
        "historyGen": _HISTORY_GEN,
        "historyN": _SNAPSHOT_N,
    }


def _invalidate_latest_locked() -> None:
    global _LATEST_PROFILE, _LATEST_PREDICTION_SNAPSHOT, _LATEST_FROZEN_PREDICTION
    global _LATEST_KEY, _LATEST_GEN, _LATEST_STATES, _LATEST_META, _LATEST_MATCH_GEN
    _LATEST_PROFILE = None
    _LATEST_PREDICTION_SNAPSHOT = None
    _LATEST_FROZEN_PREDICTION = None
    _LATEST_KEY = None
    _LATEST_GEN = 0
    _LATEST_STATES = {"exact": [], "expanded": []}
    _LATEST_META = {}
    _LATEST_MATCH_GEN = 0


def invalidate_match_shadow(match_gen: Optional[int] = None) -> int:
    """Drop in-flight/latest Shadow so a previous match cannot write back."""
    global _MATCH_GEN, _REQUEST_GEN, _PENDING_CTX, _PENDING_PATH, _PENDING_KEY
    with _CACHE_LOCK:
        _PROFILE_CACHE.clear()
        _invalidate_latest_locked()
    with _SHADOW_LOCK:
        if match_gen is not None:
            _MATCH_GEN = int(match_gen)
        else:
            _MATCH_GEN += 1
        _REQUEST_GEN += 1
        _PENDING_CTX = None
        _PENDING_PATH = None
        _PENDING_KEY = None
        return _MATCH_GEN


def reset_live_shadow_state() -> None:
    global _SNAPSHOT, _SNAPSHOT_PATH, _SNAPSHOT_DATASET_REVISION, _SNAPSHOT_N, _HISTORY_GEN, _PROFILE_CACHE, _RUNTIME
    global _REQUEST_GEN, _PENDING_KEY, _PENDING_CTX, _PENDING_PATH, _IN_FLIGHT_GEN, _IN_FLIGHT_KEY
    with _CACHE_LOCK:
        _SNAPSHOT = None
        _SNAPSHOT_PATH = None
        _SNAPSHOT_DATASET_REVISION = None
        _SNAPSHOT_N = 0
        _HISTORY_GEN = 0
        _PROFILE_CACHE.clear()
        _invalidate_latest_locked()
    with _SHADOW_LOCK:
        _REQUEST_GEN += 1
        _PENDING_KEY = None
        _PENDING_CTX = None
        _PENDING_PATH = None
        _IN_FLIGHT_GEN = None
        _IN_FLIGHT_KEY = None
    with _RUNTIME_LOCK:
        proc = _RUNTIME
        _RUNTIME = None
    if proc is None:
        return
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            if stream:
                stream.close()
        except Exception:
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            pass


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(value[k]) for k in sorted(value, key=lambda x: str(x))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(x) for x in value]
    return str(value)


# These fields are read by historical similarity and component estimation.
# Keep transport and cache identity together so edits cannot reuse old support.
_PROFILE_DETAIL_FIELDS = (
    "privateBidCap", "bidActionCount",
    "sparkle",
    "knownBlue", "knownGreen", "knownWhite",
    "totalItems", "goldTotal", "goldGrid", "purpleGrid", "redGrid", "blueCount", "blueAvg", "blueGrid",
    "greenCount", "greenAvg", "greenGrid", "whiteCount", "whiteAvg", "whiteGrid",
)


def _profile_detail_context(ctx):
    public = ctx.get("publicInfo") if isinstance(ctx.get("publicInfo"), dict) else {}
    details = {key: public.get(key) if public.get(key) is not None else ctx.get(key)
               for key in _PROFILE_DETAIL_FIELDS}
    grid = public.get("totalGrid")
    if grid is None:
        grid = ctx.get("totalGrid") if ctx.get("totalGrid") is not None else ctx.get("totalGrids")
    return {**details, "totalGrid": grid, "totalGrids": grid,
            "publicInfo": {**public, **details, "totalGrid": grid}}


def _profile_cache_key(ctx: Dict[str, Any], history_gen: int) -> str:
    payload = {
        "historyGen": history_gen,
        "matchId": ctx.get("matchId") or ctx.get("id"),
        "observationSessionId": ctx.get("observationSessionId"),
        "targetHwnd": (ctx.get("target") or {}).get("targetHwnd") if isinstance(ctx.get("target"), dict) else None,
        "targetPid": (ctx.get("target") or {}).get("targetPid") if isinstance(ctx.get("target"), dict) else None,
        "round": ctx.get("round") if ctx.get("round") is not None else ctx.get("roundNo"),
        # Revision is a publication lease, not a solver input. CurrentMatch
        # can advance it for bids/OCR provenance while valuation inputs stay
        # identical; keep one in-flight computation for that exact input.
        "venue": ctx.get("lobbyVenue") or ctx.get("venue"),
        "box": ctx.get("box"),
        "fieldCondition": ctx.get("fieldCondition") or "unknown",
        "catalogVersion": ctx.get("catalogVersion"),
        "q": ctx.get("q"),
        "goldAvg": ctx.get("goldAvg") if ctx.get("goldAvg") is not None else ctx.get("avg"),
        "purpleAvg": ctx.get("purpleAvg"),
        "purple": ctx.get("purple") if ctx.get("purple") is not None else ctx.get("purpleCount"),
        "goldCount": ctx.get("goldCount"),
        "redCount": ctx.get("redCount"),
        "knownGold": ctx.get("knownGold") or [],
        "knownPurple": ctx.get("knownPurple") or [],
        "knownRed": ctx.get("knownRed") or [],
        "playedAt": ctx.get("playedAt"),
        **_profile_detail_context(ctx),
        "roundingMode": ctx.get("roundingMode") or "floor",
        "matchGeneration": ctx.get("matchGeneration") or 0,
        "nativeSolverGeneration": ctx.get("nativeSolverGeneration"),
    }
    raw = json.dumps(_jsonable(payload), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _shadow_history_allowed_ids(records: List[Dict[str, Any]]) -> List[str]:
    """Do not treat operator-asserted box membership as independently verified truth.

    Missing provenance is legacy-compatible; only the new explicit weak evidence
    class is excluded. This is an admission guard, not a Shadow algorithm change.
    """
    allowed = []
    for record in records:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        environment = record.get("environment") if isinstance(record.get("environment"), dict) else {}
        evidence_class = record.get("boxEvidenceClass") or environment.get("boxEvidenceClass")
        if evidence_class == "OPERATOR_ASSERTED_CURRENT":
            continue
        allowed.append(str(record["id"]))
    return allowed


def _solver_ctx(ctx: Dict[str, Any], records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "matchId": ctx.get("matchId") or ctx.get("id"),
        "playedAt": ctx.get("playedAt"),
        "venue": ctx.get("lobbyVenue") or ctx.get("venue") or "未知场地",
        "box": ctx.get("box") or "未知箱型",
        "fieldCondition": ctx.get("fieldCondition") or "unknown",
        "catalogVersion": ctx.get("catalogVersion"),
        "q": ctx.get("q"),
        "avg": ctx.get("avg") if ctx.get("avg") is not None else ctx.get("goldAvg"),
        "goldAvg": ctx.get("goldAvg") if ctx.get("goldAvg") is not None else ctx.get("avg"),
        "purpleAvg": ctx.get("purpleAvg"),
        "purple": ctx.get("purple") if ctx.get("purple") is not None else ctx.get("purpleCount"),
        "purpleCount": ctx.get("purpleCount") if ctx.get("purpleCount") is not None else ctx.get("purple"),
        "goldCount": ctx.get("goldCount"),
        "redCount": ctx.get("redCount"),
        "knownGold": ctx.get("knownGold") or [],
        "knownPurple": ctx.get("knownPurple") or [],
        "knownRed": ctx.get("knownRed") or [],
        **_profile_detail_context(ctx),
        "roundingMode": ctx.get("roundingMode") or "floor",
        "costs": ctx.get("costs"),
        "allowedHistoryIds": _shadow_history_allowed_ids(records or []),
    }


def _facts_ready(ctx: Dict[str, Any]) -> bool:
    # Evidence-only bounds do not require gold count/average or probability data.
    if ctx.get("fieldCondition") in ("sparkle", "闪耀之心", "shining_heart"):
        return True
    q = ctx.get("q")
    avg = ctx.get("goldAvg") if ctx.get("goldAvg") is not None else ctx.get("avg")
    try:
        return float(q) > 0 and float(avg) > 0
    except (TypeError, ValueError):
        return False


def compute_timeout_s() -> float:
    raw = os.environ.get("YIHUAN_COMPUTE_TIMEOUT_S", "8")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 8.0
    return max(0.2, value)


def _kill_runtime(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        try:
            if stream:
                stream.close()
        except Exception:
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            pass


def _read_json_line(proc: subprocess.Popen, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
    if not proc.stdout:
        return None
    deadline = time.time() + (timeout if timeout is not None else compute_timeout_s())
    while time.time() < deadline:
        remaining = max(0.05, deadline - time.time())
        box: "queue.Queue[Any]" = queue.Queue(maxsize=1)

        def _reader() -> None:
            try:
                box.put(proc.stdout.readline())
            except Exception as exc:
                box.put(exc)

        worker = threading.Thread(target=_reader, name="shadow-readline", daemon=True)
        worker.start()
        worker.join(remaining)
        if worker.is_alive():
            raise TimeoutError("COMPUTE_TIMEOUT")
        item = box.get_nowait() if not box.empty() else None
        if isinstance(item, Exception):
            raise item
        if not item:
            return None
        text = str(item).strip()
        if not text.startswith("{"):
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    raise TimeoutError("COMPUTE_TIMEOUT")


class WebViewShadowHost:
    """Hosts live shadow calculation inside the existing Overlay WebView2 / V8 context."""

    def __init__(self, form: Any, solver_code: Optional[str] = None):
        self._form = form
        self._solver_code = solver_code or ""
        if not self._solver_code:
            self._load_solver_code()
        self._lock = threading.Lock()
        self._records_synced_sha256: Optional[str] = None
        self._initialized = False
        self._init_error: Optional[str] = None
        if self._solver_code:
            self._init_solver(self._solver_code)

    def _load_solver_code(self) -> None:
        candidate_paths = [
            os.path.join(CORE_DIR, "solver_core_v06.js"),
            os.path.join(PROJECT_ROOT, "core", "solver_core_v06.js"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "core", "solver_core_v06.js") if getattr(sys, "frozen", False) else "",
        ]
        for cp in candidate_paths:
            if cp and os.path.isfile(cp):
                try:
                    with open(cp, "rb") as fh:
                        self._solver_code = fh.read().decode("utf-8")
                    if self._solver_code:
                        break
                except Exception:
                    pass

    def _init_solver(self, solver_code: str) -> bool:
        if not solver_code:
            self._load_solver_code()
            solver_code = self._solver_code
        if not solver_code:
            self._init_error = "EMPTY_SOLVER_CODE"
            return False
        if not self._form or not hasattr(self._form, "ExecuteScript"):
            self._init_error = "FORM_UNAVAILABLE"
            return False
        try:
            code_json = json.dumps(solver_code, ensure_ascii=False)
            script = f"window.LiveShadowWebviewAdapter ? JSON.stringify(window.LiveShadowWebviewAdapter.initSolver({code_json})) : JSON.stringify({{ ok: false, error: 'NO_ADAPTER' }})"
            with self._lock:
                raw = self._form.ExecuteScript(script)
            if not raw:
                self._init_error = "EMPTY_INIT_RESPONSE"
                return False
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if isinstance(parsed, dict) and parsed.get("ok"):
                self._initialized = True
                self._init_error = None
                return True
            self._init_error = (parsed.get("error") if isinstance(parsed, dict) else None) or "INIT_FAILED"
            return False
        except Exception as e:
            self._init_error = str(e)
            return False

    def is_ready(self) -> bool:
        if not self._form or not hasattr(self._form, "ExecuteScript"):
            return False
        if not self._initialized:
            if not self._init_solver(self._solver_code):
                return False
        try:
            script = "window.LiveShadowWebviewAdapter ? window.LiveShadowWebviewAdapter.isReady() : false"
            with self._lock:
                raw = self._form.ExecuteScript(script)
            if not raw:
                return False
            res = json.loads(raw)
            return bool(res)
        except Exception:
            return False

    def sync_records_if_needed(self, records: List[Dict[str, Any]], dataset_revision: Dict[str, Any]) -> bool:
        rev_sha = str(dataset_revision.get("sha256") or "")
        if self._records_synced_sha256 == rev_sha and rev_sha:
            return True
        if not self._form or not hasattr(self._form, "ExecuteScript"):
            return False
        try:
            compact_records = [
                {k: v for k, v in r.items() if k not in {"rounds", "prediction", "screenshots"}}
                for r in records
                if isinstance(r, dict)
            ]
            recs_json = json.dumps(compact_records, ensure_ascii=False)
            script = f"window.LiveShadowWebviewAdapter ? JSON.stringify(window.LiveShadowWebviewAdapter.setRecords({recs_json})) : JSON.stringify({{ ok: false, error: 'NO_ADAPTER' }})"
            with self._lock:
                raw = self._form.ExecuteScript(script)
                if not raw:
                    return False
                parsed = json.loads(raw)
                if isinstance(parsed, str):
                    parsed = json.loads(parsed)
                if isinstance(parsed, dict) and parsed.get("ok"):
                    self._records_synced_sha256 = rev_sha
                    return True
                return False
        except Exception as e:
            _LOG.warning("Failed to sync records to webview: %s", e)
            return False

    def compute(self, req: Dict[str, Any]) -> Dict[str, Any]:
        if not self._form or not hasattr(self._form, "ExecuteScript"):
            return {"ok": False, "error": "HOST_UNAVAILABLE"}
        try:
            req_json = json.dumps(req, ensure_ascii=False)
            script = f"window.LiveShadowWebviewAdapter ? JSON.stringify(window.LiveShadowWebviewAdapter.compute({req_json})) : JSON.stringify({{ ok: false, error: 'NO_ADAPTER' }})"
            with self._lock:
                raw = self._form.ExecuteScript(script)
                if not raw:
                    return {"ok": False, "error": "EMPTY_RESULT"}
                parsed = json.loads(raw)
                if isinstance(parsed, str):
                    parsed = json.loads(parsed)
                return parsed if isinstance(parsed, dict) else {"ok": False, "error": "INVALID_RESPONSE_FORMAT"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def register_webview_host(host: Any) -> None:
    global _WEBVIEW_HOST
    with _SHADOW_LOCK:
        _WEBVIEW_HOST = host


def unregister_webview_host() -> None:
    global _WEBVIEW_HOST
    with _SHADOW_LOCK:
        _WEBVIEW_HOST = None


def get_webview_host() -> Optional[Any]:
    return _WEBVIEW_HOST


def _bundled_node() -> Optional[str]:
    candidates = [
        os.path.join(PROJECT_ROOT, "runtime", "node.exe"),
        os.path.join(PROJECT_ROOT, "runtime", "node"),
        os.path.join(os.path.dirname(sys.executable), "node.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _node_executable() -> Optional[str]:
    """Bundled node first. Frozen never uses PATH. Source may use PATH node."""
    bundled = _bundled_node()
    if bundled:
        return bundled
    if getattr(sys, "frozen", False):
        return None
    return shutil.which("node") or shutil.which("node.exe")


def _start_runtime(db_path: str) -> Optional[subprocess.Popen]:
    """Persistent production compute process. Overlay WebView is not required."""
    node = _node_executable()
    if not node:
        return None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    try:
        return subprocess.Popen(
            [node, _runtime_js(), "--records", db_path],
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=flags,
            startupinfo=startupinfo,
        )
    except Exception:
        return None


def _push_runtime_records(records: List[Dict[str, Any]]) -> None:
    with _RUNTIME_LOCK:
        proc = _RUNTIME
        if proc is None or proc.poll() is not None or not proc.stdin or not proc.stdout:
            return
        proc.stdin.write(json.dumps({"action": "setRecords", "records": records}, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        _read_json_line(proc)


def _skip_compute(reason: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {
        "ok": True,
        "insufficient": True,
        "probabilityProfile": None,
        "predictionSnapshot": None,
        "frozenPrediction": None,
        "exactStates": [],
        "expandedStates": [],
        "computeHost": None,
        "supportCapture": {"status": "SKIPPED", "reason": reason},
    }
    if extra:
        payload.update(extra)
    return payload


def _compute_request(ctx: Dict[str, Any], records: List[Dict[str, Any]], db_path: str) -> Dict[str, Any]:
    return {
        "ctx": _solver_ctx(ctx, records),
        "captureContext": {
            "matchId": ctx.get("matchId") or ctx.get("id"),
            "collectionClass": _capture_collection_class(),
        },
        "datasetRevision": get_live_dataset_revision(db_path),
        "codeRevision": get_code_revision(),
    }


def _compute_via_node(ctx: Dict[str, Any], db_path: str, records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    global _RUNTIME
    timeout = compute_timeout_s()
    with _RUNTIME_LOCK:
        proc = _RUNTIME
        if proc is None or proc.poll() is not None:
            proc = _start_runtime(db_path)
            if proc is not None:
                try:
                    _read_json_line(proc, timeout=timeout)
                except TimeoutError:
                    _kill_runtime(proc)
                    _RUNTIME = None
                    return _skip_compute("COMPUTE_TIMEOUT")
            _RUNTIME = proc
        if proc is None or not proc.stdin or not proc.stdout:
            return None
        try:
            proc.stdin.write(json.dumps({"action": "setRecords", "records": records}, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            _read_json_line(proc, timeout=timeout)
            proc.stdin.write(json.dumps(_compute_request(ctx, records, db_path), ensure_ascii=False) + "\n")
            proc.stdin.flush()
            parsed = _read_json_line(proc, timeout=timeout)
        except TimeoutError:
            _LOG.warning("Node shadow compute timed out after %.1fs; restarting runtime", timeout)
            _kill_runtime(proc)
            _RUNTIME = None
            return _skip_compute("COMPUTE_TIMEOUT")
        except Exception as exc:
            _LOG.warning("Node shadow compute failed: %s", exc)
            _kill_runtime(proc)
            _RUNTIME = None
            return _skip_compute("NODE_RUNTIME_FAILED", {"error": str(exc)})
    if not isinstance(parsed, dict):
        return None
    parsed.setdefault("ok", True)
    parsed["computeHost"] = "node"
    return parsed


def resolve_solver_catalog_identity(
    ctx: Dict[str, Any], quality: str, name: str,
) -> Optional[Dict[str, Any]]:
    """Resolve one name against the catalog the production solver will consume.

    This read-only query uses the same persistent Node runtime and catalog
    version selection as solver computation; it does not run valuation.
    ``None`` means the runtime could not answer. A mapping with
    ``available=False`` means the current solver catalog has no unique match.
    """
    global _RUNTIME
    quality_key = str(quality or "").strip().lower()
    item_name = str(name or "").strip()
    if quality_key not in {"gold", "purple", "red"} or not item_name:
        return {"ok": True, "available": False, "item": None}

    request = {
        "action": "resolveKnownIdentity",
        "ctx": _solver_ctx(ctx if isinstance(ctx, dict) else {}, []),
        "quality": quality_key,
        "name": item_name,
    }
    timeout = compute_timeout_s()
    # Catalog lookup does not need, and should not open, official History.
    lookup_records = os.path.join(PROJECT_ROOT, "build", "native-observation", "solver-catalog-lookup-empty.json")
    with _RUNTIME_LOCK:
        proc = _RUNTIME
        if proc is None or proc.poll() is not None:
            proc = _start_runtime(lookup_records)
            if proc is None:
                _RUNTIME = None
                return None
            try:
                ready = _read_json_line(proc, timeout=timeout)
            except Exception:
                ready = None
            if not isinstance(ready, dict) or ready.get("ready") is not True:
                _kill_runtime(proc)
                _RUNTIME = None
                return None
            _RUNTIME = proc
        if not proc.stdin or not proc.stdout:
            return None
        try:
            proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            parsed = _read_json_line(proc, timeout=timeout)
        except Exception as exc:
            _LOG.warning("Solver catalog lookup failed: %s", exc)
            _kill_runtime(proc)
            _RUNTIME = None
            return None
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        return None
    return parsed


def _runtime_compute(ctx: Dict[str, Any], db_path: str) -> Dict[str, Any]:
    records = list(_SNAPSHOT or [])
    node_res = _compute_via_node(ctx, db_path, records)
    if node_res is not None:
        return node_res
    reason = "NODE_RUNTIME_DISABLED" if _node_executable() is None else "COMPUTE_HOST_UNAVAILABLE"
    return _skip_compute(reason)


def _oneshot_compute(ctx: Dict[str, Any], db_path: str) -> Dict[str, Any]:
    records = list(_SNAPSHOT or [])
    node = _node_executable()
    if node:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        try:
            proc = subprocess.run(
                [node, _runtime_js(), "--once", "--records", db_path],
                cwd=PROJECT_ROOT,
                input=json.dumps({
                    **_compute_request(ctx, records, db_path),
                    "records": records,
                }, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=compute_timeout_s(),
                creationflags=flags,
                startupinfo=startupinfo,
            )
        except subprocess.TimeoutExpired:
            return _skip_compute("COMPUTE_TIMEOUT")
        except Exception:
            return _skip_compute("NODE_RUNTIME_FAILED")
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or "live shadow oneshot failed")
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
        if not lines:
            raise RuntimeError("live shadow oneshot returned no JSON")
        parsed = json.loads(lines[-1])
        if isinstance(parsed, dict):
            parsed["computeHost"] = "node"
        return parsed
    return _skip_compute("COMPUTE_HOST_UNAVAILABLE")


def _in_auction_for_shadow(ctx: Dict[str, Any]) -> bool:
    if ctx.get("isSettlement") or ctx.get("scene") == "SETTLEMENT":
        return False
    if ctx.get("inLobby") or ctx.get("isLoading"):
        return False
    scene = ctx.get("scene")
    if scene in ("AUCTION_LOBBY", "AUCTION_LOADING", "OPEN_WORLD", "CITY_TYCOON_HUB", "CITY_LEISURE_MENU"):
        return False
    return scene == SHADOW_SCENE_IN_AUCTION or bool(ctx.get("inAuction"))


def completed_prediction_for_match(match_id: str) -> Dict[str, Any]:
    """Read only completed pre-settlement work; never schedule or await a solve."""
    with _SHADOW_LOCK:
        snapshot = _LATEST_PREDICTION_SNAPSHOT
        if not isinstance(snapshot, dict) or snapshot.get("matchId") != match_id:
            return {}
        return copy.deepcopy({"snapshot": snapshot, "frozenPrediction": _LATEST_FROZEN_PREDICTION})


def register_prediction_listener(listener: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    """Register the GUI presentation callback for completed Shadow results.

    The callback is deliberately presentation-only.  It runs after the
    background computation has accepted a non-stale result and never changes
    Solver inputs, History, or the capture loop's scheduling policy.
    """
    global _PREDICTION_LISTENER
    with _SHADOW_LOCK:
        _PREDICTION_LISTENER = listener


def _ensure_worker() -> None:
    global _WORKER_THREAD
    with _SHADOW_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return
        _WORKER_THREAD = threading.Thread(target=_shadow_worker_loop, name="live-shadow", daemon=True)
        _WORKER_THREAD.start()


def _shadow_worker_loop() -> None:
    global _IN_FLIGHT_GEN, _IN_FLIGHT_KEY, _PENDING_CTX, _PENDING_PATH, _PENDING_KEY
    global _LATEST_PROFILE, _LATEST_PREDICTION_SNAPSHOT, _LATEST_FROZEN_PREDICTION
    global _LATEST_META, _LATEST_STATES, _LATEST_KEY, _LATEST_GEN, _LATEST_MATCH_GEN
    while True:
        with _SHADOW_LOCK:
            pending_ctx = _PENDING_CTX
            pending_path = _PENDING_PATH
            pending_key = _PENDING_KEY
            pending_gen = _REQUEST_GEN if pending_ctx is not None else None
            if pending_ctx is None:
                wait = True
            else:
                wait = False
                _IN_FLIGHT_GEN = pending_gen
                _IN_FLIGHT_KEY = pending_key
                _PENDING_CTX = None
                _PENDING_PATH = None
                _PENDING_KEY = None
        if wait:
            time.sleep(0.01)
            continue
        try:
            profile, meta = compute_live_probability_profile(
                pending_ctx, db_path=pending_path, persist_runtime=True
            )
        except Exception as exc:
            profile, meta = None, {"cache": "error", "error": str(exc)}
        publish_event = None
        publish_listener = None
        with _SHADOW_LOCK:
            stale = pending_gen != _REQUEST_GEN
            if not stale:
                _LATEST_PROFILE = profile
                completed_snapshot = (meta or {}).get("predictionSnapshot")
                completed_frozen = (meta or {}).get("frozenPrediction")
                _LATEST_PREDICTION_SNAPSHOT = completed_snapshot
                _LATEST_FROZEN_PREDICTION = completed_frozen
                _LATEST_META = dict(meta or {})
                _LATEST_META["shadowGen"] = pending_gen
                _LATEST_STATES = {
                    "exact": (meta or {}).get("exactStates") or [],
                    "expanded": (meta or {}).get("expandedStates") or [],
                }
                _LATEST_KEY = pending_key
                _LATEST_GEN = pending_gen or 0
                _LATEST_MATCH_GEN = int((pending_ctx or {}).get("matchGeneration") or 0)
                if profile is not None or isinstance(completed_snapshot, dict):
                    publish_listener = _PREDICTION_LISTENER
                    publish_event = {
                        "matchId": (pending_ctx or {}).get("matchId") or (pending_ctx or {}).get("id"),
                        "matchGeneration": int((pending_ctx or {}).get("matchGeneration") or 0),
                        "scene": (pending_ctx or {}).get("scene"),
                        "observationSessionId": (pending_ctx or {}).get("observationSessionId"),
                        # Main-local validity generation.  This is intentionally
                        # presentation metadata and never enters the frozen
                        # MMF/FRAME_READY transport.
                        "nativeSolverGeneration": (pending_ctx or {}).get("nativeSolverGeneration"),
                        "target": copy.deepcopy((pending_ctx or {}).get("target")),
                        "round": (pending_ctx or {}).get("round") if (pending_ctx or {}).get("round") is not None else (pending_ctx or {}).get("roundNo"),
                        "factsRevision": (pending_ctx or {}).get("factsRevision"),
                        "engineFactsRevision": (pending_ctx or {}).get("engineFactsRevision"),
                        "presentationSource": (pending_ctx or {}).get("presentationSource"),
                        "shadowGen": pending_gen,
                        "probabilityProfile": copy.deepcopy(profile),
                        "predictionSnapshot": copy.deepcopy(completed_snapshot),
                        "frozenPrediction": copy.deepcopy(completed_frozen),
                        "shadowMeta": copy.deepcopy(_LATEST_META),
                        "shadowStates": copy.deepcopy(_LATEST_STATES),
                    }
            _IN_FLIGHT_GEN = None
            _IN_FLIGHT_KEY = None
        if publish_listener is not None and isinstance(publish_event, dict):
            try:
                publish_listener(publish_event)
            except Exception:
                _LOG.exception("live shadow presentation callback failed")


def compute_live_probability_profile(
    ctx: Dict[str, Any],
    db_path: Optional[str] = None,
    persist_runtime: bool = True,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Blocking compute for tests / worker thread. Capture loop must not call this."""
    records = load_history_snapshot(db_path)
    path = _SNAPSHOT_PATH or default_history_path()
    meta = {
        "cache": "skip",
        "historyGen": history_generation(),
        "historyPath": path,
        "historyN": len(records),
    }
    if not _facts_ready(ctx):
        meta["cache"] = "insufficient"
        return None, meta
    key = _profile_cache_key(ctx, history_generation())
    with _CACHE_LOCK:
        hit = _PROFILE_CACHE.get(key)
    if hit is not None:
        meta["cache"] = "hit"
        meta["exactStates"] = hit.get("exactStates")
        meta["expandedStates"] = hit.get("expandedStates")
        meta["predictionSnapshot"] = hit.get("predictionSnapshot")
        meta["frozenPrediction"] = hit.get("frozenPrediction")
        return hit.get("probabilityProfile"), meta
    try:
        result = _runtime_compute(ctx, path) if persist_runtime else _oneshot_compute(ctx, path)
    except Exception as exc:
        meta["cache"] = "error"
        meta["error"] = str(exc)
        return None, meta
    meta["computeHost"] = result.get("computeHost")
    if result.get("ok") is False:
        meta["cache"] = "error"
        meta["error"] = result.get("error") or "runtime not ok"
        return None, meta
    skipped = result.get("supportCapture") if isinstance(result.get("supportCapture"), dict) else None
    if skipped and skipped.get("status") == "SKIPPED":
        meta["supportCapture"] = dict(skipped)
        meta["cache"] = "skip"
        return None, meta
    profile = result.get("probabilityProfile")
    snap = result.get("predictionSnapshot")
    frozen = result.get("frozenPrediction")
    # Capture is a fail-closed sidecar: invalid/mismatched support is rejected
    # without changing the already-computed production result.
    capture_envelope = result.get("supportCaptureEnvelope")
    if isinstance(capture_envelope, dict):
        capture_result = capture_prediction_support_envelope(capture_envelope)
        meta["supportCapture"] = dict(capture_result.as_immutable_mapping())
    else:
        meta["supportCapture"] = {
            "status": "REJECTED",
            "reason": "SUPPORT_CAPTURE_ENVELOPE_MISSING",
        }
    capture_meta = meta["supportCapture"]
    if capture_meta.get("status") == "REJECTED":
        _LOG.warning(
            "upper-tail capture rejected reason=%s",
            capture_meta.get("reason") or "UNKNOWN_CAPTURE_REJECTION",
        )
    elif capture_meta.get("status") in ("WRITTEN", "DUPLICATE"):
        _LOG.info(
            "upper-tail capture %s captureId=%s predictionHash=%s",
            str(capture_meta.get("status")).lower(),
            capture_meta.get("captureId"),
            capture_meta.get("predictionHash"),
        )
    packed = {
        "probabilityProfile": profile,
        "predictionSnapshot": snap,
        "frozenPrediction": frozen,
        "exactStates": result.get("exactStates") or [],
        "expandedStates": result.get("expandedStates") or [],
    }
    with _CACHE_LOCK:
        _PROFILE_CACHE[key] = packed
    meta["cache"] = "miss"
    meta["exactStates"] = packed["exactStates"]
    meta["expandedStates"] = packed["expandedStates"]
    meta["predictionSnapshot"] = snap
    meta["frozenPrediction"] = frozen
    return profile, meta


def attach_live_shadow(ctx: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Non-blocking: publish latest facts, return last completed profile."""
    global _REQUEST_GEN, _PENDING_CTX, _PENDING_PATH, _PENDING_KEY
    out = dict(ctx)
    with _CACHE_LOCK:
        has_snap = _SNAPSHOT is not None
        hist_gen = _HISTORY_GEN
        records_n = _SNAPSHOT_N
        path = _SNAPSHOT_PATH or (os.path.abspath(db_path) if db_path else default_history_path())
    if not has_snap:
        out["probabilityProfile"] = None
        out["predictionSnapshot"] = None
        out["frozenPrediction"] = None
        out["shadowUpdating"] = False
        out["shadowMeta"] = {"cache": "no-snapshot", "historyGen": hist_gen, "historyN": records_n, "shadowUpdating": False}
        return out
    eligible = _in_auction_for_shadow(ctx) and _facts_ready(ctx)
    match_gen = int(ctx.get("matchGeneration") or 0)
    key = _profile_cache_key(ctx, hist_gen) if eligible else None
    with _SHADOW_LOCK:
        in_flight = _IN_FLIGHT_GEN is not None or _PENDING_CTX is not None
        latest_profile = _LATEST_PROFILE
        latest_snap = _LATEST_PREDICTION_SNAPSHOT
        latest_frozen = _LATEST_FROZEN_PREDICTION
        latest_meta = dict(_LATEST_META or {})
        latest_states = dict(_LATEST_STATES or {"exact": [], "expanded": []})
        latest_key = _LATEST_KEY
        latest_gen = _LATEST_GEN
        latest_match = _LATEST_MATCH_GEN
        pending_key = _PENDING_KEY
        inflight_key = _IN_FLIGHT_KEY
    if not eligible:
        out["probabilityProfile"] = None
        out["predictionSnapshot"] = None
        out["frozenPrediction"] = None
        out["shadowUpdating"] = False
        out["shadowMeta"] = {
            "cache": "skip-scene" if not _in_auction_for_shadow(ctx) else "insufficient",
            "historyGen": hist_gen,
            "historyN": records_n,
            "shadowUpdating": False,
            "shadowGen": latest_gen,
        }
        return out
    cached = None
    with _CACHE_LOCK:
        packed = _PROFILE_CACHE.get(key) if key else None
        if packed:
            cached = packed
    if cached and latest_match in (0, match_gen):
        out["probabilityProfile"] = cached.get("probabilityProfile")
        out["predictionSnapshot"] = cached.get("predictionSnapshot")
        out["frozenPrediction"] = cached.get("frozenPrediction")
        out["shadowStates"] = {
            "exact": cached.get("exactStates") or [],
            "expanded": cached.get("expandedStates") or [],
        }
        out["shadowUpdating"] = False
        out["shadowMeta"] = {
            "cache": "hit",
            "historyGen": hist_gen,
            "historyN": records_n,
            "shadowUpdating": False,
            "shadowGen": latest_gen,
            "exactStates": out["shadowStates"]["exact"],
            "expandedStates": out["shadowStates"]["expanded"],
        }
        return out
    stale = (latest_key is not None and latest_key != key) or (latest_match != match_gen)
    already_queued = pending_key == key or inflight_key == key
    if not already_queued:
        with _SHADOW_LOCK:
            _REQUEST_GEN += 1
            _PENDING_CTX = dict(ctx)
            _PENDING_PATH = path
            _PENDING_KEY = key
        _ensure_worker()
        in_flight = True
    out["shadowUpdating"] = True
    if latest_profile is not None and not stale:
        out["probabilityProfile"] = latest_profile
        out["predictionSnapshot"] = latest_snap
        out["frozenPrediction"] = latest_frozen
        out["shadowStates"] = latest_states
    else:
        out["probabilityProfile"] = None
        out["predictionSnapshot"] = None
        out["frozenPrediction"] = None
    out["shadowMeta"] = {
        "cache": "pending",
        "historyGen": hist_gen,
        "historyN": records_n,
        "shadowUpdating": True,
        "shadowStale": stale,
        "shadowGen": latest_gen,
        "inFlight": in_flight,
        **({k: latest_meta.get(k) for k in ("error",) if latest_meta.get(k)}),
    }
    return out


def wait_for_shadow(timeout: float = 8.0, key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Test helper: wait until the latest completed profile matches key or any result arrives."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _SHADOW_LOCK:
            pending = _PENDING_CTX is not None or _IN_FLIGHT_GEN is not None
            latest = _LATEST_PROFILE
            latest_key = _LATEST_KEY
        if not pending and latest is not None and (key is None or latest_key == key):
            return latest
        if not pending and key is not None and latest_key == key:
            return latest
        time.sleep(0.02)
    return None


def warmup_shadow_runtime(db_path: Optional[str] = None) -> None:
    """Start Node once at worker boot so the first IN_AUCTION is not a Popen."""
    global _RUNTIME
    load_history_snapshot(db_path)
    path = _SNAPSHOT_PATH or default_history_path()
    with _RUNTIME_LOCK:
        if _RUNTIME is None or _RUNTIME.poll() is not None:
            proc = _start_runtime(path)
            if proc is not None:
                _read_json_line(proc)
            _RUNTIME = proc
    _ensure_worker()
