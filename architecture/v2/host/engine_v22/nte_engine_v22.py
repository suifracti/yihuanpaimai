#!/usr/bin/env python3
"""V2-2 real Engine adapter for the fixed-v1 Host frame transport.

This process is the first production-shaped Engine path in the V2 experiment:

* the Host owns capture, the MMF ring and FRAME_READY;
* this process opens the mapping read-only, validates the exact 64-byte header,
  copies the BGRA8 pixels before releasing the slot, and never writes MMF;
* the existing NTEVisionPipeline and CurrentMatch remain the business authority;
* the control pipe stays responsive while a bounded worker queue runs vision;
* state and canonical-history evidence are isolated under the Host work folder.

The existing architecture/v2/host/engine_ref/nte_engine_ref.py remains the
V2-1 mock/reference Engine and is intentionally not modified by this adapter.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import datetime as dt
import hashlib
import json
import os
import queue
import struct
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import cv2
import numpy as np


HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[4]
ENGINE_REF_DIR = REPO_ROOT / "architecture" / "v2" / "host" / "engine_ref"
CORE_DIR = REPO_ROOT / "core"
APP_DIR = REPO_ROOT / "app"
CONTRACTS_DIR = REPO_ROOT / "architecture" / "v2" / "contracts"
for _path in (str(ENGINE_REF_DIR), str(CORE_DIR), str(APP_DIR), str(CONTRACTS_DIR), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from nte_engine_ref import (  # noqa: E402
    FILE_MAP_READ,
    INVALID_HANDLE_VALUE,
    PipeClient,
    ProtocolError,
    k32,
    load_mandatory_capabilities,
    qpc_ns,
)
from canonical_history_store import CanonicalHistoryStore, HistoryStoreError  # noqa: E402
from current_match import FACT_KEYS, CurrentMatch, is_missing_observation  # noqa: E402
from deferred_identity_analyzer import (  # noqa: E402
    DeferredIdentityAnalyzer,
    deferred_identity_result_is_current,
)
from venue_box_catalog import (  # noqa: E402
    canonical_catalog_provenance,
    catalog_selection,
    load_catalog as load_venue_box_catalog,
    normalize_vision_venue,
)
from vision_pipeline import NTEVisionPipeline  # noqa: E402

# PipeClient's reference reader is intentionally blocking for V2-1 tests.  The
# real Engine keeps the control loop schedulable while the vision worker runs by
# polling named-pipe availability before each short ReadFile call.
k32.PeekNamedPipe.restype = wintypes.BOOL
k32.PeekNamedPipe.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
]

try:  # Contract helpers are shared with the Python verifier.
    from models import (  # type: ignore  # noqa: E402
        ContractValidationError,
        FrameHeaderV1,
        validate_envelope,
        validate_payload_fields,
    )
except ImportError:  # pragma: no cover - only used if launched outside the repo.
    ContractValidationError = ValueError  # type: ignore
    FrameHeaderV1 = None  # type: ignore
    validate_envelope = None  # type: ignore
    validate_payload_fields = None  # type: ignore


PROTOCOL_VERSION = "1.0.0"
FRAME_HEADER_MAGIC = 0x4246544E
FRAME_HEADER_VERSION = 1
FRAME_HEADER_SIZE = 64
PIXEL_FORMAT_BGRA8 = 1
SLOT_COUNT = 4
SLOT_PAYLOAD_CAPACITY = 8_294_400
SLOT_SIZE = 8_294_464
MAP_SIZE = 33_177_856
MAX_WIDTH = 1920
MAX_HEIGHT = 1080
FRAME_HEADER_STRUCT = "<IiqiiiiiiqqIi"
FRAME_HEADER_FIELDS = (
    "magic",
    "headerVersion",
    "sequence",
    "width",
    "height",
    "stride",
    "pixelFormat",
    "bufferLength",
    "flags",
    "captureTimestampNs",
    "producerTimestampNs",
    "cornerChecksum",
    "reserved",
)
FRAME_READY_CHECKED_FIELDS = (
    "bufferIndex",
    "sequence",
    "width",
    "height",
    "stride",
    "pixelFormat",
    "bufferLength",
    "captureTimestampNs",
    "cornerChecksum",
)


def _safe(value: Any) -> Any:
    """Convert NumPy/path values while preserving unknown as unknown."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _corner_checksum(raw: bytes, width: int, height: int, stride: int) -> int:
    last_x = (width - 1) * 4
    last_y = (height - 1) * stride
    total = 0
    for offset in (0, last_x, last_y, last_y + last_x):
        total += sum(raw[offset : offset + 4])
    return total & 0xFFFFFFFF


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(_safe(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class FrameMapReader:
    """Read-only view of the fixed v1 ring; no write mapping or byte writes."""

    def __init__(self, map_name: str, declared_size: int):
        if declared_size != MAP_SIZE:
            raise ProtocolError(
                "ERR_RING_GEOMETRY_MISMATCH",
                f"map size {declared_size} does not equal fixed v1 size {MAP_SIZE}",
            )
        self.map_name = map_name
        self.declared_size = declared_size
        self.handle = k32.OpenFileMappingW(FILE_MAP_READ, False, map_name)
        if self.handle in (None, 0, INVALID_HANDLE_VALUE):
            error = ctypes.get_last_error()
            raise ProtocolError("ERR_BUFFER_UNAVAILABLE", f"OpenFileMappingW failed with Win32 error {error}")
        self.view = k32.MapViewOfFile(self.handle, FILE_MAP_READ, 0, 0, MAP_SIZE)
        if not self.view:
            error = ctypes.get_last_error()
            k32.CloseHandle(self.handle)
            self.handle = None
            raise ProtocolError("ERR_BUFFER_UNAVAILABLE", f"MapViewOfFile read-only failed with Win32 error {error}")

    def probe(self) -> dict:
        head = ctypes.string_at(self.view, FRAME_HEADER_SIZE)
        return {
            "mapName": self.map_name,
            "declaredSize": self.declared_size,
            "openMode": "FILE_MAP_READ (0x0004)",
            "openSucceeded": True,
            "readViewMapped": True,
            "writeViewRequested": False,
            "writeViewDenied": "NOT_REQUESTED_BY_ENGINE",
            "firstBytesAllZero": all(b == 0 for b in head),
            "readOnlyContract": True,
        }

    def read_frame(self, payload: dict, expected_session_id: str) -> dict:
        if payload.get("sessionId") != expected_session_id:
            raise ProtocolError("ERR_STALE_SESSION", "FRAME_READY sessionId does not match active session")
        index = payload.get("bufferIndex")
        if type(index) is not int or not 0 <= index < SLOT_COUNT:
            raise ProtocolError("ERR_SLOT_INDEX_OUT_OF_BOUNDS", f"invalid frame bufferIndex {index!r}")

        slot_offset = index * SLOT_SIZE
        header_bytes = ctypes.string_at(self.view + slot_offset, FRAME_HEADER_SIZE)
        values = struct.unpack(FRAME_HEADER_STRUCT, header_bytes)
        header = dict(zip(FRAME_HEADER_FIELDS, values))

        if header["magic"] != FRAME_HEADER_MAGIC:
            raise ProtocolError("ERR_CORRUPT_FRAME_MAGIC", f"unexpected frame magic 0x{header['magic']:08X}")
        if header["headerVersion"] != FRAME_HEADER_VERSION:
            raise ProtocolError("ERR_SCHEMA_VALIDATION_FAILED", "unsupported FrameHeaderV1 version")
        width = header["width"]
        height = header["height"]
        stride = header["stride"]
        buffer_length = header["bufferLength"]
        if not (0 < width <= MAX_WIDTH and 0 < height <= MAX_HEIGHT):
            raise ProtocolError("ERR_FRAME_CAPACITY_EXCEEDED", f"invalid frame geometry {width}x{height}")
        if stride != width * 4 or buffer_length != stride * height:
            raise ProtocolError("ERR_FRAME_METADATA_MISMATCH", "FrameHeaderV1 geometry is inconsistent")
        if buffer_length > SLOT_PAYLOAD_CAPACITY:
            raise ProtocolError("ERR_FRAME_CAPACITY_EXCEEDED", "frame payload exceeds fixed slot capacity")
        if header["pixelFormat"] != PIXEL_FORMAT_BGRA8:
            raise ProtocolError("ERR_UNSUPPORTED_PIXEL_FORMAT", "only BGRA8 is supported")
        if header["reserved"] != 0:
            raise ProtocolError("ERR_SCHEMA_VALIDATION_FAILED", "FrameHeaderV1 reserved field is non-zero")

        for field in FRAME_READY_CHECKED_FIELDS:
            actual = index if field == "bufferIndex" else header[field]
            if payload.get(field) != actual:
                raise ProtocolError(
                    "ERR_FRAME_METADATA_MISMATCH",
                    f"FRAME_READY {field}={payload.get(field)!r} != header {actual!r}",
                )

        raw = ctypes.string_at(self.view + slot_offset + FRAME_HEADER_SIZE, buffer_length)
        checksum = _corner_checksum(raw, width, height, stride)
        if checksum != header["cornerChecksum"]:
            raise ProtocolError(
                "ERR_FRAME_CHECKSUM_FAILED",
                f"cornerChecksum={header['cornerChecksum']} computed={checksum}",
            )

        # Copy before the release token is emitted.  No worker ever reads the MMF
        # after this method returns, so a released slot cannot race the pipeline.
        bgra = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 4)).copy()
        bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        return {
            "bufferIndex": index,
            "header": header,
            "raw": raw,
            "rawSha256": _sha256_bytes(raw),
            "bgra": bgra,
            "bgr": bgr,
            "readCompletedNs": qpc_ns(),
        }

    def close(self) -> None:
        if self.view:
            k32.UnmapViewOfFile(self.view)
            self.view = None
        if self.handle not in (None, 0, INVALID_HANDLE_VALUE):
            k32.CloseHandle(self.handle)
            self.handle = None


class RealEngine:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.session_id = args.session_id
        self.nonce = args.nonce
        self.pipe_name = args.pipe_name
        self.map_name = args.frame_buffer_name
        self.frame_buffer_size = args.frame_buffer_size
        self.work_dir = Path(args.work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.generation_id = int(args.generation_id)
        self.log_path = Path(args.log).resolve() if args.log else self.work_dir / "engine_trace.jsonl"
        self.fault = args.fault or ""
        self.data_origin = args.data_origin or "replay"

        self.pipe: Optional[PipeClient] = None
        self.reader: Optional[FrameMapReader] = None
        self.send_lock = threading.Lock()
        self.sequence = 0
        self.request_counter = 0
        self.hello_seen = False
        self.stop_event = threading.Event()
        self.heartbeat_enabled = True
        self.frame_queue: queue.Queue[dict] = queue.Queue(maxsize=2)
        self.worker: Optional[threading.Thread] = None
        self._identity_analyzer: Optional[DeferredIdentityAnalyzer] = None
        self._identity_generation_lock = threading.Lock()
        self._identity_invalidation_generation = 0
        self._identity_scope_key = None
        self._identity_last_committed_sequence: dict[tuple[str, str, Any], int] = {}
        self.frame_records_path = self.work_dir / "frame_records.ndjson"
        self.state_path = self.work_dir / "engine_state.json"
        self.state_manifest_path = self.work_dir / "engine_state_manifest.json"
        self.history_path = self.work_dir / "canonical_history.json"
        self.snapshot_sequence = 0
        self.last_context: dict = {}
        self.last_frame: dict = {}
        self.processing_errors: list[str] = []
        self.command_records: dict[str, dict] = {}
        self.reader_error: Optional[str] = None
        self.control_revision = 0
        self.manual_overrides: dict[str, Any] = {}
        self.awaiting_exit = False
        # The frozen frame header carries QPC nanoseconds, while the existing
        # vision pipeline accepts an aware ISO timestamp.  Associate the two
        # clock domains once at process start; never substitute OCR completion
        # time for the capture boundary.
        self._wall_minus_qpc_ns = time.time_ns() - qpc_ns()

        # These are loaded before the Named Pipe handshake.  READY therefore
        # means the real business objects are present, not merely that IPC works.
        self.catalog_path = Path(args.catalog).resolve() if args.catalog else REPO_ROOT / "assets" / "catalog_065.json"
        self.venue_catalog = None
        self.venue_catalog_provenance = None
        self.pipeline: NTEVisionPipeline
        self.current_match: CurrentMatch
        self.history_store: CanonicalHistoryStore
        self.business_ready = False
        self.preload()

    # -- logging and durable state -----------------------------------------
    def log(self, event: str, **details: Any) -> None:
        record = {
            "tsNs": qpc_ns(),
            "event": event,
            "sessionId": self.session_id,
            "sessionNonceShort": self.nonce[:8],
            "generationId": self.generation_id,
            "details": _safe(details),
        }
        line = json.dumps(record, ensure_ascii=False)
        print(line, file=sys.stderr, flush=True)
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass

    def preload(self) -> None:
        if self.fault == "model_load_fail":
            # G4 fault injection: fail before HELLO_ACK so the Host cannot
            # mistake an IPC process for a business-ready Engine.
            raise RuntimeError("test fault: model initialization failed before READY")
        if not self.catalog_path.is_file():
            raise RuntimeError(f"catalog missing: {self.catalog_path}")
        self.venue_catalog = load_venue_box_catalog()
        self.venue_catalog_provenance = canonical_catalog_provenance(self.venue_catalog)
        self.pipeline = NTEVisionPipeline(catalog_path=str(self.catalog_path))
        # The property constructs the real RapidOCR runtime and its ONNX model.
        ocr_engine = self.pipeline.ocr
        if ocr_engine is None or not self.pipeline.catalog:
            raise RuntimeError("business preload did not produce catalog and OCR objects")

        self.current_match = CurrentMatch()
        self.current_match.data_origin = self.data_origin
        self.current_match.source = "vision_v22"
        self._restore_state_if_present()
        self.history_store = CanonicalHistoryStore(str(self.history_path))
        self.business_ready = True
        if self.fault == "state_unwritable":
            # The Host work directory is isolated per run.  Replacing this
            # exact path with a directory makes the first durable state write
            # fail without touching any user or repository data.
            self.state_path.mkdir(parents=False, exist_ok=False)
        self._persist_state(reason="business_preload")
        self.log(
            "business_ready",
            catalogPath=str(self.catalog_path),
            catalogCount=len(self.pipeline.catalog),
            ocrReady=True,
            pipelineType=type(self.pipeline).__name__,
            currentMatchId=self.current_match.id,
            dataOrigin=self.current_match.data_origin,
            historyPath=str(self.history_path),
        )

    def _restore_state_if_present(self) -> None:
        if not self.state_path.is_file():
            self.current_match.id = f"replayfile_{hashlib.sha256(self.session_id.encode()).hexdigest()[:20]}"
            self.current_match.created_at = _utc_now()
            self.current_match.updated_at = self.current_match.created_at
            return
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            snap = state.get("currentMatch") if isinstance(state, dict) else None
            if not isinstance(snap, dict):
                raise ValueError("engine_state.json has no currentMatch object")
            self.current_match.id = str(snap.get("id") or self.current_match.id)
            self.current_match.lifecycle_status = str(snap.get("lifecycleStatus") or "DRAFT")
            self.current_match.source = str(snap.get("source") or "vision_v22")
            self.current_match.data_origin = str(snap.get("dataOrigin") or self.data_origin)
            self.current_match.created_at = str(snap.get("createdAt") or _utc_now())
            self.current_match.updated_at = str(snap.get("updatedAt") or self.current_match.created_at)
            self.current_match.facts = {
                key: copy.deepcopy(snap[key]) for key in FACT_KEYS if key in snap
            }
            # Keep the full v7 fact shape when a prior state predates a field.
            for key, value in CurrentMatch().facts.items():
                self.current_match.facts.setdefault(key, copy.deepcopy(value))
            self.current_match.facts_revision = int(snap.get("factsRevision") or 0)
            self.current_match.restore_field_states(snap.get("fieldStates"))
            self.control_revision = int(state.get("controlRevision") or 0)
            self.manual_overrides = copy.deepcopy(state.get("manualOverrides") or {})
            for key, field in self.current_match.field_states.items():
                if field.protected and key in FACT_KEYS:
                    self.manual_overrides[key] = copy.deepcopy(self.current_match.facts.get(key))
            prior_context = state.get("pipelineContext")
            if isinstance(prior_context, dict):
                self.pipeline.current_context.update(copy.deepcopy(prior_context))
                self.last_context = copy.deepcopy(prior_context)
            self.log("state.restored", statePath=str(self.state_path), matchId=self.current_match.id)
        except Exception as exc:
            # A corrupt local sidecar cannot silently become business truth.
            # Start an isolated DRAFT and leave the failure visible in the log.
            self.log("state.restore_failed", statePath=str(self.state_path), error=str(exc))
            self.current_match.id = f"replayfile_{hashlib.sha256(self.session_id.encode()).hexdigest()[:20]}"
            self.current_match.created_at = _utc_now()
            self.current_match.updated_at = self.current_match.created_at

    def _persist_state(self, *, reason: str, frame_record: Optional[dict] = None) -> None:
        snapshot = self.current_match.snapshot()
        state = {
            "schemaVersion": 1,
            "protocolVersion": PROTOCOL_VERSION,
            "generationId": self.generation_id,
            "sessionId": self.session_id,
            "businessReady": self.business_ready,
            "dataOrigin": self.data_origin,
            "reason": reason,
            "updatedAtUtc": _utc_now(),
            "currentMatch": snapshot,
            "controlRevision": self.control_revision,
            "manualOverrides": copy.deepcopy(self.manual_overrides),
            "pipelineContext": copy.deepcopy(self.last_context or self.pipeline.current_context),
            "lastFrame": frame_record or self.last_frame,
        }
        _atomic_json(self.state_path, state)
        state_bytes = self.state_path.read_bytes()
        _atomic_json(
            self.state_manifest_path,
            {
                "schemaVersion": 1,
                "statePath": str(self.state_path),
                "stateSha256": _sha256_bytes(state_bytes),
                "matchId": self.current_match.id,
                "factsRevision": self.current_match.facts_revision,
                "lifecycleStatus": self.current_match.lifecycle_status,
                "dataOrigin": self.current_match.data_origin,
                "reason": reason,
            },
        )

    def _append_frame_record(self, record: dict) -> None:
        self.frame_records_path.parent.mkdir(parents=True, exist_ok=True)
        with self.frame_records_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_safe(record), ensure_ascii=False, sort_keys=True) + "\n")

    def _persist_history(self) -> str:
        try:
            canonical = self.current_match.to_canonical()
            self.history_store.persist_record_transactional(canonical, is_finalized=False)
            return "PERSISTED_DRAFT"
        except HistoryStoreError as exc:
            self.log("history.persist_failed", error=str(exc))
            return f"FAILED:{type(exc).__name__}"
        except Exception as exc:
            self.log("history.persist_failed", error=str(exc))
            return f"FAILED:{type(exc).__name__}"

    def _capture_iso(self, capture_timestamp_ns: int) -> str:
        wall_ns = int(capture_timestamp_ns) + self._wall_minus_qpc_ns
        return dt.datetime.fromtimestamp(wall_ns / 1_000_000_000.0, dt.timezone.utc).isoformat()

    def _identity_generation(self) -> int:
        with self._identity_generation_lock:
            return self._identity_invalidation_generation

    def _invalidate_deferred_identity(self, reason: str) -> int:
        with self._identity_generation_lock:
            self._identity_invalidation_generation += 1
            generation = self._identity_invalidation_generation
        if self._identity_analyzer is not None:
            self._identity_analyzer.invalidate_pending()
        self.log("identity.deferred_invalidated", invalidationGeneration=generation, reason=reason)
        return generation

    # -- envelopes ----------------------------------------------------------
    def next_sequence(self) -> int:
        value = self.sequence
        self.sequence += 1
        return value

    def next_request_id(self, prefix: str) -> str:
        self.request_counter += 1
        return f"{prefix}-{self.request_counter:04d}"

    def envelope(self, message_type: str, payload: dict, prefix: str, correlation_id: Optional[str] = None) -> dict:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "sessionId": self.session_id,
            "messageType": message_type,
            "requestId": self.next_request_id(prefix),
            "correlationId": correlation_id,
            "sequence": self.next_sequence(),
            "monotonicTimestampNs": qpc_ns(),
            "payload": _safe(payload),
        }

    def send(self, message_type: str, payload: dict, prefix: str, correlation_id: Optional[str] = None) -> dict:
        if self.pipe is None:
            raise ProtocolError("ERR_PIPE_DISCONNECTED", "engine pipe is not connected")
        with self.send_lock:
            envelope = self.envelope(message_type, payload, prefix, correlation_id)
            self.pipe.send(envelope)
        self.log("send", messageType=message_type, sequence=envelope["sequence"], requestId=envelope["requestId"])
        return envelope

    def send_error(self, error_code: str, category: str, message: str, is_fatal: bool = False) -> None:
        try:
            self.send(
                "ERROR",
                {
                    "errorCode": error_code,
                    "category": category,
                    "message": message,
                    "isFatal": bool(is_fatal),
                },
                "err",
            )
        except Exception:
            pass

    def _pipe_available(self) -> Optional[int]:
        if self.pipe is None:
            raise ProtocolError("ERR_PIPE_DISCONNECTED", "engine pipe is not connected")
        available = wintypes.DWORD(0)
        ok = k32.PeekNamedPipe(self.pipe.handle, None, 0, None, ctypes.byref(available), None)
        if ok:
            return int(available.value)
        error = ctypes.get_last_error()
        if error in (109, 232):  # ERROR_BROKEN_PIPE / ERROR_NO_DATA
            return None
        raise ProtocolError("ERR_PIPE_BROKEN", f"PeekNamedPipe failed with Win32 error {error}")

    def _read_pipe_exact_polling(self, count: int) -> Optional[bytes]:
        if self.pipe is None:
            raise ProtocolError("ERR_PIPE_DISCONNECTED", "engine pipe is not connected")
        data = bytearray()
        while len(data) < count:
            available = self._pipe_available()
            if available is None:
                return None
            if available <= 0:
                time.sleep(0.002)
                continue
            amount = min(count - len(data), available)
            buffer = ctypes.create_string_buffer(amount)
            read = wintypes.DWORD(0)
            ok = k32.ReadFile(
                self.pipe.handle,
                ctypes.cast(buffer, ctypes.c_void_p),
                amount,
                ctypes.byref(read),
                None,
            )
            if not ok:
                error = ctypes.get_last_error()
                if error in (109, 232):
                    return None
                raise ProtocolError("ERR_PIPE_BROKEN", f"ReadFile failed with Win32 error {error}")
            if read.value == 0:
                return None
            data.extend(buffer.raw[: read.value])
        return bytes(data)

    def recv_polling(self) -> Optional[dict]:
        prefix = self._read_pipe_exact_polling(4)
        if prefix is None:
            return None
        (length,) = struct.unpack("<I", prefix)
        if length > 1_048_576:
            raise ProtocolError("ERR_MESSAGE_TOO_LARGE", f"declared length {length} exceeds 1048576")
        body = self._read_pipe_exact_polling(length)
        if body is None:
            raise ProtocolError("ERR_INCOMPLETE_FRAME", f"stream ended inside a {length}-byte payload")
        try:
            return json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise ProtocolError("ERR_SCHEMA_VALIDATION_FAILED", f"invalid JSON payload: {exc}") from exc

    # -- protocol handlers --------------------------------------------------
    def validate_inbound(self, envelope: dict) -> None:
        if validate_envelope is not None:
            try:
                validate_envelope(envelope)
            except ContractValidationError as exc:
                raise ProtocolError(getattr(exc, "error_code", "ERR_SCHEMA_VALIDATION_FAILED"), str(exc))
        else:
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                raise ProtocolError("ERR_MALFORMED_ENVELOPE", "payload must be an object")

    def handle_hello(self, envelope: dict) -> None:
        payload = envelope.get("payload") or {}
        if envelope.get("sessionId") != self.session_id:
            self.send_error("ERR_STALE_SESSION", "PROTOCOL", "HELLO sessionId mismatch", True)
            raise ProtocolError("ERR_STALE_SESSION", "HELLO sessionId mismatch")
        if payload.get("sessionNonce") != self.nonce:
            self.send_error("ERR_STALE_GENERATION", "PROTOCOL", "HELLO sessionNonce mismatch", True)
            raise ProtocolError("ERR_STALE_GENERATION", "HELLO sessionNonce mismatch")
        if payload.get("frameBufferSize") != MAP_SIZE:
            self.send_error("ERR_RING_GEOMETRY_MISMATCH", "PROTOCOL", "HELLO frameBufferSize is not fixed-v1", True)
            raise ProtocolError("ERR_RING_GEOMETRY_MISMATCH", "HELLO frameBufferSize is not fixed-v1")

        capabilities = payload.get("capabilities") or {}
        unavailable = [name for name in load_mandatory_capabilities() if capabilities.get(name) != "AVAILABLE"]
        if unavailable:
            self.send(
                "HELLO_ACK",
                {
                    "engineVersion": "2.2.0-real",
                    "negotiatedProtocol": PROTOCOL_VERSION,
                    "status": "REJECTED_CAPABILITY",
                    "readiness": "STARTING",
                    "enginePid": os.getpid(),
                    "engineBusinessReady": False,
                },
                "ack",
                correlation_id=envelope.get("requestId"),
            )
            self.log("hello.rejected_capability", unavailable=unavailable)
            return

        self.hello_seen = True
        self.send(
            "HELLO_ACK",
            {
                "engineVersion": "2.2.0-real",
                "negotiatedProtocol": PROTOCOL_VERSION,
                "status": "ACCEPTED",
                "readiness": "READY",
                "enginePid": os.getpid(),
                "engineBusinessReady": True,
            },
            "ack",
            correlation_id=envelope.get("requestId"),
        )
        self.log("hello.accepted", enginePid=os.getpid(), businessReady=self.business_ready)
        if self.fault == "exit_after_ready":
            os._exit(7)

    def _projection_bids(self, context: Optional[dict] = None) -> list[dict]:
        context = context or self.last_context or self.pipeline.current_context
        bids = []
        for seat in context.get("seats") or []:
            if not isinstance(seat, dict):
                continue
            raw_price = seat.get("currentBid", seat.get("bid"))
            if isinstance(raw_price, bool) or not isinstance(raw_price, (int, np.integer)) or int(raw_price) <= 0:
                continue
            raw_seat = seat.get("slot", seat.get("seat"))
            if isinstance(raw_seat, bool) or not isinstance(raw_seat, (int, np.integer)):
                continue
            item = {"seat": int(raw_seat), "price": int(raw_price)}
            if isinstance(seat.get("isWinning"), bool):
                item["isWinning"] = bool(seat["isWinning"])
            bids.append(item)
        return bids

    def _state_projection(self) -> dict:
        status = str(self.current_match.lifecycle_status or "DRAFT")
        context = self.last_context or self.pipeline.current_context
        return {
            "matchId": str(self.current_match.id),
            "matchState": status,
            "auctionPhase": str(context.get("scene") or "UNKNOWN"),
            "draftCount": 1 if status == "DRAFT" and self.current_match.has_any_fact() else 0,
            "finalizedCount": 1 if status == "FINALIZED" else 0,
            "activeAuctionItems": [],
            "bids": self._projection_bids(context),
        }

    def handle_state_snapshot_request(self, envelope: dict) -> None:
        self.snapshot_sequence += 1
        self.send(
            "STATE_SNAPSHOT",
            {
                "snapshotSchemaVersion": PROTOCOL_VERSION,
                "snapshotSessionId": self.session_id,
                "snapshotSequence": self.snapshot_sequence,
                "businessReady": self.business_ready,
                "currentMatchProjection": self._state_projection(),
            },
            "snapshot",
            correlation_id=envelope.get("requestId"),
        )

    def _command_result(self, command_id: str, status: str, *, error: Optional[str] = None, result: Optional[dict] = None) -> dict:
        payload: dict = {"commandId": command_id, "status": status}
        if error is not None:
            payload["errorDetails"] = error
        if result is not None:
            payload["resultData"] = result
        return payload

    def _apply_manual_control(self, command_id: str, parameters: dict) -> tuple[str, Optional[str], dict]:
        """Apply one GUI control command inside the sole business worker.

        The GUI keeps its existing presentation state, but the worker remains
        the only authority that can accept a revision.  A full snapshot is
        restored with its original field provenance; only the explicit facts
        patch becomes a manual override for subsequent vision frames.
        """
        revision = parameters.get("revision")
        snapshot = parameters.get("snapshot")
        if type(revision) is not int or revision < 0:
            return "REJECT", "invalid control revision", {}
        if revision <= self.control_revision:
            return "REJECT", "STALE_CONTROL_REVISION", {"controlRevision": self.control_revision}
        if not isinstance(snapshot, dict) or not str(snapshot.get("id") or "").strip():
            return "REJECT", "snapshot must contain a match id", {}

        expected_id = str(parameters.get("expectedMatchId") or "").strip()
        snapshot_id = str(snapshot.get("id") or "").strip()
        reset = parameters.get("reset") is True
        if "expectedFactsRevision" in parameters:
            expected_revision = parameters.get("expectedFactsRevision")
            expected_round = parameters.get("expectedRound")
            current_round = self.current_match.facts.get("roundNo")
            if type(expected_revision) is not int or expected_revision != self.current_match.facts_revision:
                return "REJECT", "STALE_FACTS_REVISION", {
                    "expectedFactsRevision": expected_revision,
                    "currentFactsRevision": self.current_match.facts_revision,
                }
            if type(expected_round) is not int or expected_round != current_round:
                return "REJECT", "STALE_ROUND", {
                    "expectedRound": expected_round,
                    "currentRound": current_round,
                }
            if not expected_id or expected_id != self.current_match.id:
                return "REJECT", "MATCH_CHANGED", {
                    "expectedMatchId": expected_id,
                    "currentMatchId": self.current_match.id,
                }
            if not reset and snapshot_id != self.current_match.id:
                return "REJECT", "MATCH_CHANGED", {
                    "snapshotMatchId": snapshot_id,
                    "currentMatchId": self.current_match.id,
                }
        if reset and expected_id and expected_id != self.current_match.id:
            return "REJECT", "MATCH_CHANGED", {
                "expectedMatchId": expected_id,
                "currentMatchId": self.current_match.id,
            }
        if (
            not reset
            and expected_id
            and expected_id != self.current_match.id
            and snapshot_id != self.current_match.id
        ):
            return "REJECT", "MATCH_CHANGED", {
                "expectedMatchId": expected_id,
                "currentMatchId": self.current_match.id,
            }

        patch = parameters.get("facts") or {}
        if not isinstance(patch, dict):
            return "REJECT", "facts must be an object", {}
        cleared_fields = [
            key for key in (parameters.get("clearedFields") or [])
            if key in FACT_KEYS
        ]
        restore_auto_fields = [
            key for key in (parameters.get("restoreAutoFields") or [])
            if key in FACT_KEYS
        ]

        self._invalidate_deferred_identity("manual_match_control")
        if reset or self.current_match.id != snapshot_id:
            self.current_match.begin_next_match()
            self.current_match.id = snapshot_id
            self.current_match.apply_facts(
                snapshot,
                source="manual",
                intent="snapshot",
                command_id=command_id,
            )
            self.current_match.lifecycle_status = str(snapshot.get("lifecycleStatus") or "DRAFT")
            self.current_match.data_origin = self.data_origin
            self.manual_overrides = {}

        for key in restore_auto_fields:
            self.manual_overrides.pop(key, None)
        for key, value in patch.items():
            if key in FACT_KEYS and key not in cleared_fields and not is_missing_observation(key, value):
                self.manual_overrides[key] = copy.deepcopy(value)
        for key in cleared_fields:
            self.manual_overrides[key] = None

        self.current_match.apply_facts(
            {key: copy.deepcopy(value) for key, value in self.manual_overrides.items()
             if key not in restore_auto_fields},
            source="manual",
            intent="confirm",
            cleared_fields=cleared_fields,
            restore_auto_fields=restore_auto_fields,
            command_id=command_id,
        )
        self.control_revision = revision
        if reset:
            self.pipeline.reset_session_state()
            self.awaiting_exit = True
        self._persist_state(reason="manual_control")
        return "ACK", None, {
            "echo": "match.apply_control",
            "businessReady": self.business_ready,
            "controlRevision": self.control_revision,
            "matchId": self.current_match.id,
            "factsRevision": self.current_match.facts_revision,
            "reset": reset,
            "expectedMatchId": expected_id,
            "expectedFactsRevision": parameters.get("expectedFactsRevision"),
            "expectedRound": parameters.get("expectedRound"),
            "expectedObservationSessionId": parameters.get("expectedObservationSessionId"),
        }

    def handle_command(self, envelope: dict) -> None:
        payload = envelope.get("payload") or {}
        command_id = str(payload.get("commandId") or "")
        action = str(payload.get("action") or "")
        parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        expires_at = payload.get("expiresAtNs")
        if not command_id or type(expires_at) is not int:
            self.send_error("ERR_SCHEMA_VALIDATION_FAILED", "PAYLOAD", "invalid COMMAND payload", False)
            return

        fingerprint = {"action": action, "parameters": copy.deepcopy(parameters)}
        prior = self.command_records.get(command_id)
        if prior is not None:
            if prior["fingerprint"] != fingerprint:
                self.send_error(
                    "ERR_COMMAND_ID_REUSE_MISMATCH",
                    "AUTHORITY",
                    f"commandId {command_id} was reused with a different action or parameters",
                    True,
                )
                return
            result = dict(prior["result"])
            result["status"] = "DUPLICATE"
            self.send("COMMAND_RESULT", result, "cmdres", correlation_id=envelope.get("requestId"))
            return

        if qpc_ns() >= expires_at:
            result = self._command_result(command_id, "EXPIRED", error="command expired before receipt evaluation")
            self.command_records[command_id] = {"fingerprint": fingerprint, "result": result}
            self.send("COMMAND_RESULT", result, "cmdres", correlation_id=envelope.get("requestId"))
            return

        if action == "test.simulate_crash":
            marker = {
                "crashMarkerNs": qpc_ns(),
                "generationId": self.generation_id,
                "nonceShort": self.nonce[:8],
                "pid": os.getpid(),
            }
            _atomic_json(self.work_dir / "crash_marker.json", marker)
            self.log("crash.simulated", commandId=command_id)
            os._exit(3)
        if action == "test.close_pipe":
            self.log("pipe.closing_abruptly", commandId=command_id)
            if self.pipe:
                self.pipe.close()
            os._exit(4)
        if action == "test.stop_heartbeat":
            self.heartbeat_enabled = False
        elif action == "test.resume_heartbeat":
            self.heartbeat_enabled = True
        elif action == "test.wrong_session_snapshot":
            # Kept as an explicit command so recovery tests can ask the real
            # Engine for a snapshot without mutating authoritative state.
            pass
        elif action == "match.apply_control":
            status, error, result_data = self._apply_manual_control(command_id, parameters)
            result = self._command_result(command_id, status, error=error, result=result_data)
            self.command_records[command_id] = {"fingerprint": fingerprint, "result": result}
            self.send("COMMAND_RESULT", result, "cmdres", correlation_id=envelope.get("requestId"))
            return
        elif action not in {"state.snapshot", "test.stop_heartbeat", "test.resume_heartbeat", "test.wrong_session_snapshot"}:
            result = self._command_result(command_id, "REJECT", error=f"unsupported action: {action}")
            self.command_records[command_id] = {"fingerprint": fingerprint, "result": result}
            self.send("COMMAND_RESULT", result, "cmdres", correlation_id=envelope.get("requestId"))
            return

        result = self._command_result(command_id, "ACK", result={"echo": action, "businessReady": self.business_ready})
        self.command_records[command_id] = {"fingerprint": fingerprint, "result": result}
        self.send("COMMAND_RESULT", result, "cmdres", correlation_id=envelope.get("requestId"))

    def _frame_ack(self, item: dict, status: str, processing_ms: float) -> None:
        header = item["header"]
        session_id = self.session_id
        sequence = int(header["sequence"])
        if self.fault in {"bad_ack", "old_session_ack"}:
            sequence += 1000
        if self.fault == "old_session_ack":
            session_id = "stale-session-0001"
        self.send(
            "FRAME_ACK",
            {
                "sessionId": session_id,
                "bufferIndex": int(item["bufferIndex"]),
                "sequence": sequence,
                "status": status,
                "mappingLatencyMs": max(0.0, (item["readCompletedNs"] - item["receivedNs"]) / 1_000_000.0),
                "processingLatencyMs": processing_ms,
            },
            "frame-ack",
        )

    def _perception_payload(self, item: dict, context: dict, processing_ms: float) -> dict:
        intel = []
        for raw in context.get("intelCardReadings") or []:
            if not isinstance(raw, dict):
                continue
            ident = raw.get("id") or raw.get("catalogId")
            value = raw.get("value") or raw.get("name")
            if isinstance(ident, str) and isinstance(value, str) and ident and value:
                intel.append({"id": ident, "value": value})

        payload = {
            "frameSequence": int(item["header"]["sequence"]),
            "scene": str(context.get("scene") or "UNKNOWN"),
            "inAuction": bool(context.get("inAuction")),
            "bids": self._projection_bids(context),
            "processingMs": float(processing_ms),
        }
        if intel:
            payload["intel"] = intel
        warehouse = context.get("warehouseVision")
        if isinstance(warehouse, dict):
            summary: dict[str, Any] = {}
            if warehouse.get("totalExpectedVal") is not None:
                summary["totalExpectedVal"] = _safe(warehouse.get("totalExpectedVal"))
            if warehouse.get("slots") is not None:
                summary["slotCount"] = len(warehouse.get("slots") or [])
            if summary:
                payload["warehouseSummary"] = summary
        return payload

    def _catalog_venue_facts(self, context: dict) -> dict:
        """Promote an observed lobby venue through the approved current catalog."""
        if context.get("scene") != "IN_AUCTION":
            return {}
        catalog = self.venue_catalog
        provenance = self.venue_catalog_provenance
        if not isinstance(catalog, Mapping) or not isinstance(provenance, Mapping):
            return {}
        venue_id = context.get("venueId")
        if not venue_id:
            observation = (
                context.get("lobbyVenueKey")
                or context.get("lobbyVenue")
                or context.get("venue")
            )
            normalized = normalize_vision_venue(catalog, observation)
            if normalized.get("status") != "NORMALIZED":
                return {}
            venue_id = normalized.get("venueId")
        try:
            selection = catalog_selection(catalog, venue_id, None)
        except (KeyError, TypeError, ValueError):
            return {}
        if selection.get("status") not in {"VALIDATED", "BOX_UNKNOWN"}:
            return {}
        return {
            "venueId": selection["venueId"],
            "venue": selection["venue"],
            "entryCost": selection["entryCost"],
            "venueEvidenceClass": selection["venueEvidenceClass"],
            **{
                key: provenance.get(key)
                for key in (
                    "catalogVersion",
                    "catalogApprovalStatus",
                    "catalogSha256",
                    "gameEvidenceCohort",
                )
            },
        }

    def _apply_pipeline_context(self, context: dict, observed_at: str) -> None:
        patch = {}
        for key in FACT_KEYS:
            if key not in context:
                continue
            value = context.get(key)
            if is_missing_observation(key, value):
                continue
            patch[key] = copy.deepcopy(_safe(value))
        patch.update(self._catalog_venue_facts(context))
        round_no = context.get("round")
        if round_no is not None and context.get("scene") == "IN_AUCTION":
            patch["roundNo"] = int(round_no)
        seats = context.get("seats")
        live_seats = []
        if isinstance(seats, list):
            normalized_seats = []
            for seat in seats:
                if not isinstance(seat, dict):
                    continue
                row = copy.deepcopy(_safe(seat))
                current_bid = row.get("currentBid")
                if current_bid is None or row.get("observationStatus") == "UNOBSERVED":
                    row.update(bid=None, currentBid=None, observationStatus="UNOBSERVED")
                else:
                    row.update(bid=current_bid, observationStatus="VISIBLE")
                    live_seats.append(row)
                normalized_seats.append(row)
            if live_seats:
                patch["seats"] = normalized_seats
            elif patch.get("roundNo") != self.current_match.facts.get("roundNo") and patch.get("roundNo"):
                # CurrentMatch's existing seat rollover clears last round's quotes.
                patch["seats"] = normalized_seats
            else:
                patch.pop("seats", None)
        if live_seats:
            patch["leaderBid"] = max(int(seat["currentBid"]) for seat in live_seats)
            my_seat = next((seat for seat in live_seats if seat.get("slot") == 4), None)
            if my_seat is not None:
                patch["myBid"] = int(my_seat["currentBid"])
            else:
                patch.pop("myBid", None)
        else:
            for key in ("leaderBid", "myBid", "leaderName", "leaderTies", "isMyLead"):
                patch.pop(key, None)
            if patch.get("roundNo") != self.current_match.facts.get("roundNo") and patch.get("roundNo"):
                patch.update(leaderBid=None, myBid=None, leaderName=None, leaderTies=[], isMyLead=None)
        if "auctionEvidence" not in patch:
            readings = context.get("intelCardReadings")
            if isinstance(readings, list) and readings:
                patch["auctionEvidence"] = {
                    "ownerMatchId": self.current_match.id,
                    "intel": copy.deepcopy(_safe(readings)),
                }
        if patch:
            self.current_match.apply_facts(patch, source="vision", intent="observe", observed_at=observed_at)
        self.current_match.updated_at = _utc_now()

    def _identity_scope_kind(self, context: dict) -> Optional[str]:
        scene = str(context.get("scene") or "UNKNOWN")
        if scene == "IN_AUCTION":
            kind = "warehouse"
        elif scene == "SETTLEMENT" or bool(context.get("isSettlement")):
            kind = "settlement"
        else:
            kind = None
        round_value = context.get("round")
        if round_value is None:
            round_value = self.current_match.facts.get("roundNo")
        try:
            round_value = int(round_value) if round_value is not None else None
        except (TypeError, ValueError):
            round_value = None
        key = None if kind is None else (
            self.current_match.id,
            self.current_match._seq,
            int(getattr(self.pipeline, "_match_gen", 0)),
            int(getattr(self.pipeline, "_session_generation", 0)),
            kind,
            round_value,
            str(context.get("recognitionMode") or "auto"),
        )
        if key != self._identity_scope_key:
            previous = self._identity_scope_key
            self._identity_scope_key = key
            self._identity_last_committed_sequence.clear()
            if previous is not None:
                self._invalidate_deferred_identity("observation_scope_changed")
        return kind

    def _submit_deferred_identity(self, item: dict, context: dict) -> None:
        pending = self.pipeline.take_deferred_identity()
        if not isinstance(pending, dict):
            return
        kind = str(pending.get("kind") or "")
        expected_kind = self._identity_scope_kind(context)
        if kind != expected_kind or kind not in {"warehouse", "settlement"}:
            return
        invalidation_generation = int(item.get("identityInvalidationGeneration", -1))
        if invalidation_generation != self._identity_generation():
            self.log("identity.deferred_frame_rejected", reason="INVALIDATED_BEFORE_DISPATCH",
                     frameSequence=item.get("header", {}).get("sequence"), kind=kind)
            return
        round_value = pending.get("round")
        if round_value is None:
            round_value = context.get("round", self.current_match.facts.get("roundNo"))
        try:
            round_value = int(round_value) if round_value is not None else None
        except (TypeError, ValueError):
            round_value = None
        if kind == "warehouse" and (round_value is None or round_value <= 0):
            return
        if self._identity_analyzer is None:
            self._identity_analyzer = DeferredIdentityAnalyzer()
        header = item["header"]
        descriptor = {
            "kind": kind,
            "sessionId": self.session_id,
            "generationId": self.generation_id,
            "matchId": self.current_match.id,
            "matchSequence": int(self.current_match._seq),
            "pipelineMatchGeneration": int(pending.get("matchGeneration", getattr(self.pipeline, "_match_gen", 0))),
            "pipelineSessionGeneration": int(pending.get("sessionGeneration", getattr(self.pipeline, "_session_generation", 0))),
            "factsRevisionAtDispatch": int(self.current_match.facts_revision),
            "invalidationGeneration": invalidation_generation,
            "round": round_value,
            "scene": str(context.get("scene") or "UNKNOWN"),
            "recognitionMode": str(context.get("recognitionMode") or "auto"),
            "frameSequence": int(header["sequence"]),
            "captureTimestampNs": int(header["captureTimestampNs"]),
            "capturedAt": str(item.get("capturedAt") or pending.get("captured_at") or ""),
            "pixelSha256": str(item.get("rawSha256") or ""),
            "actualTotal": pending.get("actual_total"),
        }
        frame = pending.get("frame")
        if not isinstance(frame, np.ndarray) or frame.size == 0:
            frame = item.get("bgr")
        if self._identity_analyzer.submit(descriptor, frame):
            self.log("identity.deferred_dispatched", kind=kind, matchId=descriptor["matchId"],
                     round=round_value, frameSequence=descriptor["frameSequence"],
                     factsRevision=descriptor["factsRevisionAtDispatch"],
                     pixelSha256=descriptor["pixelSha256"])

    @staticmethod
    def _warehouse_fact_projection(vision: dict) -> dict:
        projected = []
        for raw in vision.get("slots") or []:
            if not isinstance(raw, dict):
                continue
            try:
                if any(raw.get(key) is None for key in ("col", "row", "w", "h")):
                    continue
                slot = {
                    "col": int(raw["col"]),
                    "row": int(raw["row"]),
                    "w": int(raw["w"]),
                    "h": int(raw["h"]),
                    "rarity": str(raw.get("rarity") or "unknown"),
                    "evidenceLevel": str(raw.get("evidenceLevel") or "OUTLINE_ONLY"),
                    "identityStatus": str(raw.get("identityStatus") or "UNKNOWN"),
                    "candidates": [
                        {"catalogId": str(c.get("catalogId") or c.get("Id") or ""),
                         "name": str(c.get("name") or c.get("Name") or "")}
                        for c in (raw.get("candidates") or []) if isinstance(c, dict)
                        and (c.get("catalogId") or c.get("Id"))
                    ],
                }
                if raw.get("trackId") is not None:
                    slot["trackId"] = int(raw["trackId"])
                if (slot["identityStatus"] == "EXACT"
                        and raw.get("identityReferenceKind") == "DIRECT"
                        and raw.get("identifiedName")):
                    slot["identifiedName"] = str(raw["identifiedName"])
                projected.append(slot)
            except (TypeError, ValueError):
                continue
        return {"slots": projected}

    def _commit_deferred_identity(self, result: dict) -> bool:
        kind = str(result.get("kind") or "")
        scope_key = (kind, str(result.get("matchId") or ""), result.get("round") if kind == "warehouse" else None)
        scene = str((self.last_context or {}).get("scene") or "UNKNOWN")
        round_value = (self.last_context or {}).get("round")
        if round_value is None:
            round_value = self.current_match.facts.get("roundNo")
        try:
            round_value = int(round_value) if round_value is not None else None
        except (TypeError, ValueError):
            round_value = None
        current = {
            "sessionId": self.session_id,
            "generationId": self.generation_id,
            "matchId": self.current_match.id,
            "matchSequence": int(self.current_match._seq),
            "pipelineMatchGeneration": int(getattr(self.pipeline, "_match_gen", 0)),
            "pipelineSessionGeneration": int(getattr(self.pipeline, "_session_generation", 0)),
            "invalidationGeneration": self._identity_generation(),
            "recognitionMode": str((self.last_context or {}).get("recognitionMode") or "auto"),
            "factsRevision": int(self.current_match.facts_revision),
            "lastCommittedFrameSequence": self._identity_last_committed_sequence.get(scope_key, -1),
            "scene": scene,
            "round": round_value,
        }
        if not deferred_identity_result_is_current(result, current):
            self.log("identity.deferred_result_rejected", kind=kind,
                     matchId=result.get("matchId"), round=result.get("round"),
                     frameSequence=result.get("frameSequence"), currentScene=scene,
                     currentMatchId=self.current_match.id,
                     invalidationGeneration=current["invalidationGeneration"],
                     error=result.get("error"))
            return False

        evidence_refs = {
            "kind": "native-deferred-identity-frame",
            "sessionId": result["sessionId"],
            "generationId": result["generationId"],
            "matchId": result["matchId"],
            "round": result.get("round"),
            "frameSequence": result["frameSequence"],
            "captureTimestampNs": result["captureTimestampNs"],
            "capturedAt": result.get("capturedAt"),
            "pixelSha256": result.get("pixelSha256"),
            "identityReferencePolicy": "direct-exact-only; derived-unverified-is-candidate-only",
        }
        patch: dict[str, Any] = {}
        context = copy.deepcopy(self.last_context or {})
        if kind == "warehouse":
            vision = result.get("warehouseVision")
            if not isinstance(vision, dict):
                return False
            context["warehouseVision"] = copy.deepcopy(vision)
            context["warehouseSlots"] = copy.deepcopy(vision.get("slots") or [])
            context["warehouseExpectedVal"] = vision.get("totalExpectedVal", 0)
            context["warehouseValRange"] = copy.deepcopy(vision.get("valRange") or [0, 0])
            projected = self._warehouse_fact_projection(vision)
            if projected["slots"] and projected != self.current_match.facts.get("warehouse"):
                patch["warehouse"] = projected

            official_by_id = {
                str(row.get("Id") or ""): row for row in (self.pipeline.catalog or [])
                if isinstance(row, dict) and row.get("Id")
            }
            quality_targets = {"gold": ("knownGold", "金"), "purple": ("knownPurple", "紫"), "red": ("knownRed", "红")}
            exact_names: dict[str, dict[str, str]] = {field: {} for field, _quality in quality_targets.values()}
            for raw in vision.get("slots") or []:
                if not isinstance(raw, dict) or raw.get("identityStatus") != "EXACT":
                    continue
                if raw.get("identityReferenceKind") != "DIRECT":
                    continue
                catalog_id = str(raw.get("identifiedCatalogId") or "")
                official = official_by_id.get(catalog_id)
                if official is None:
                    continue
                fact_key_quality = quality_targets.get(str(raw.get("rarity") or ""))
                if (fact_key_quality is None or str(official.get("Quality") or "") != fact_key_quality[1]
                        or str(official.get("Name") or "") != str(raw.get("identifiedName") or "")):
                    continue
                field = fact_key_quality[0]
                name = str(official.get("Name") or "")
                if name and "+" not in name:
                    exact_names[field][catalog_id] = name
            for field, items in exact_names.items():
                if not items:
                    continue
                old = self.current_match.facts.get(field) or ""
                if isinstance(old, list):
                    names = [str(item.get("name") or item) if isinstance(item, dict) else str(item) for item in old]
                else:
                    names = [part.strip() for part in str(old).split("+") if part.strip()]
                merged = list(dict.fromkeys(names + list(items.values())))
                joined = "+".join(merged)
                if joined and joined != ("+".join(names)):
                    patch[field] = joined
        elif kind == "settlement":
            settlement_items = result.get("settlementItems")
            if not isinstance(settlement_items, list):
                return False
            context["settlementItems"] = copy.deepcopy(settlement_items)
            settlement_data = context.get("settlementData")
            if isinstance(settlement_data, dict):
                settlement_data["items"] = copy.deepcopy(settlement_items)
                settlement_data["ledger"] = copy.deepcopy({k: v for k, v in result.items()
                                                             if k not in {"frame", "warehouseVision"}})
                context["settlementData"] = settlement_data
            for key in ("settlementItems", "settlementLedgerVerified", "settlementLedgerStatus",
                        "settlementLedgerDelta"):
                if key in result and result.get(key) != self.current_match.facts.get(key):
                    patch[key] = copy.deepcopy(result[key])
            # Settlement discoveries remain settlement evidence and never enter
            # the pre-auction knownGold/knownPurple/knownRed facts.
        else:
            return False

        self.last_context = context
        if isinstance(getattr(self.pipeline, "current_context", None), dict):
            if kind == "warehouse":
                self.pipeline._apply_warehouse_state(copy.deepcopy(context["warehouseVision"]))
            else:
                self.pipeline.current_context.update(copy.deepcopy(context))
        revision_before = self.current_match.facts_revision
        if patch:
            self.current_match.apply_facts(
                patch,
                source="vision",
                intent="observe",
                observed_at=str(result.get("capturedAt") or ""),
                evidence_refs=evidence_refs,
            )
        self._identity_last_committed_sequence[scope_key] = int(result["frameSequence"])
        if self.current_match.facts_revision != revision_before:
            history_status = self._persist_history()
            self._persist_state(reason="deferred_identity_committed")
        else:
            history_status = "UNCHANGED"
        exact_count = sum(1 for slot in (result.get("warehouseVision", {}).get("slots") or [])
                          if isinstance(slot, dict) and slot.get("identityStatus") == "EXACT"
                          and slot.get("identityReferenceKind") == "DIRECT") if kind == "warehouse" else 0
        self.log("identity.deferred_committed", kind=kind, matchId=result.get("matchId"),
                 round=result.get("round"), frameSequence=result.get("frameSequence"),
                 exactDirectCount=exact_count, factsRevision=self.current_match.facts_revision,
                 historyStatus=history_status)
        return True

    def _drain_deferred_identity(self) -> None:
        if self._identity_analyzer is None:
            return
        for result in self._identity_analyzer.poll():
            self._commit_deferred_identity(result)

    def _apply_manual_overrides(self, context: dict) -> dict:
        """Project accepted GUI overrides into the next business frame."""
        if self.awaiting_exit:
            scene = str(context.get("scene") or "")
            if scene in {"AUCTION_LOBBY", "CITY_TYCOON_HUB", "CITY_LEISURE_MENU", "OPEN_WORLD"}:
                self.awaiting_exit = False
            else:
                context.update({
                    "scene": "UNKNOWN",
                    "inAuction": False,
                    "isSettlement": False,
                    "controlPendingExit": True,
                })
                return context
        for key, value in self.manual_overrides.items():
            if value is None:
                context.pop(key, None)
            else:
                context[key] = copy.deepcopy(value)
        return context

    def _process_frame(self, item: dict) -> None:
        started = qpc_ns()
        header = item["header"]
        try:
            captured_at = self._capture_iso(int(header["captureTimestampNs"]))
            context = self.pipeline.process_frame(
                item["bgr"],
                captured_at=captured_at,
                record_stable_key=self.current_match.id,
                # G3's minimum projection uses the existing scene/OCR/state
                # path. Heavy catalog identity remains an explicit follow-up
                # operation and must not block the transport ACK or the first
                # authoritative CurrentMatch projection.
                include_heavy_identity=False,
                prioritize_live_facts=True,
            )
            context = _safe(context)
            context["capturedAt"] = captured_at
            context["captureTimestampNs"] = int(header["captureTimestampNs"])
            context = self._apply_manual_overrides(context)
            self._identity_scope_kind(context)
            self.last_context = copy.deepcopy(context)
            self._apply_pipeline_context(context, captured_at)
            history_status = self._persist_history()
            processing_ms = (qpc_ns() - started) / 1_000_000.0
            self.last_frame = {
                "frameSequence": int(header["sequence"]),
                "bufferIndex": int(item["bufferIndex"]),
                "capturedAt": captured_at,
                "captureTimestampNs": int(header["captureTimestampNs"]),
                "pixelSha256": item["rawSha256"],
                "processingMs": processing_ms,
                "historyStatus": history_status,
            }
            record = {
                "frameSequence": int(header["sequence"]),
                "bufferIndex": int(item["bufferIndex"]),
                "header": header,
                "capturedAt": captured_at,
                "captureTimestampNs": int(header["captureTimestampNs"]),
                "pixelSha256": item["rawSha256"],
                "cornerChecksum": int(header["cornerChecksum"]),
                "scene": context.get("scene"),
                "inAuction": bool(context.get("inAuction")),
                "stateMatchId": self.current_match.id,
                "stateFactsRevision": self.current_match.facts_revision,
                "historyStatus": history_status,
                "processingMs": processing_ms,
            }
            self._append_frame_record(record)
            self._persist_state(reason="frame_processed", frame_record=record)

            if self.fault == "no_ack":
                self.log("frame.no_ack_fault", frameSequence=header["sequence"])
                return
            if self.fault == "consumer_exit":
                os._exit(8)

            if self.fault not in {"bad_ack", "old_session_ack"}:
                self.send(
                    "PERCEPTION_RESULT",
                    self._perception_payload(item, context, processing_ms),
                    "perception",
                )
            # Publish current bids/intel first. Only after the fast result has
            # crossed the existing pipe do we copy pixels for optional identity.
            try:
                self._submit_deferred_identity(item, context)
            except Exception as exc:
                self.log("identity.deferred_dispatch_failed", frameSequence=header.get("sequence"),
                         error=f"{type(exc).__name__}: {exc}")
            self.log(
                "frame.processed",
                frameSequence=header["sequence"],
                pixelSha256=item["rawSha256"],
                scene=context.get("scene"),
                inAuction=bool(context.get("inAuction")),
                processingMs=processing_ms,
            )
        except Exception as exc:
            self.processing_errors.append(f"{type(exc).__name__}: {exc}")
            self.log("frame.processing_failed", frameSequence=header.get("sequence"), error=str(exc))
            if self.fault != "no_ack" and not item.get("ackSent"):
                try:
                    self._frame_ack(item, "CORRUPTED", (qpc_ns() - started) / 1_000_000.0)
                except Exception:
                    pass
            try:
                self.send_error("ERR_SCHEMA_VALIDATION_FAILED", "PAYLOAD", str(exc), False)
            except Exception:
                pass

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set() or not self.frame_queue.empty():
            try:
                item = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                self._drain_deferred_identity()
                continue
            try:
                self._process_frame(item)
            finally:
                self.frame_queue.task_done()
                self._drain_deferred_identity()

    def handle_frame_ready(self, envelope: dict) -> None:
        if self.reader is None:
            raise ProtocolError("ERR_BUFFER_UNAVAILABLE", "frame reader is not initialized")
        if self.fault == "consumer_exit":
            os._exit(8)
        received_ns = qpc_ns()
        item = self.reader.read_frame(envelope.get("payload") or {}, self.session_id)
        item["receivedNs"] = received_ns
        item["identityInvalidationGeneration"] = self._identity_generation()
        if self.fault == "bad_header":
            self.send_error("ERR_CORRUPT_FRAME_MAGIC", "PAYLOAD", "test fault: header rejected", False)
            return
        try:
            self.frame_queue.put_nowait(item)
        except queue.Full:
            # The slot is released explicitly as SKIPPED; no frame is overwritten.
            self.send(
                "FRAME_ACK",
                {
                    "sessionId": self.session_id,
                    "bufferIndex": int(item["bufferIndex"]),
                    "sequence": int(item["header"]["sequence"]),
                    "status": "SKIPPED",
                },
                "frame-skip",
            )
            self.log("frame.skipped_queue_full", frameSequence=item["header"]["sequence"])
            item["ackSent"] = True
            return

        # The reader has copied the complete pixel payload out of MMF.  From
        # this point onward the worker owns a private NumPy copy, so the exact
        # release token can be sent without racing a future Host reuse of the
        # slot.  This keeps the protocol ACK inside the 500 ms frame-ACK SLA
        # even when the first real OCR pass takes tens of seconds.
        if self.fault != "no_ack":
            self._frame_ack(item, "CONSUMED", 0.0)
            item["ackSent"] = True
            if self.fault == "duplicate_ack":
                # A duplicate token is intentionally sent only after the valid
                # token; it can never grant ownership a second time.
                self._frame_ack(item, "CONSUMED", 0.0)
        else:
            self.log("frame.no_ack_fault", frameSequence=item["header"]["sequence"])

    def handle_heartbeat(self, envelope: dict) -> None:
        if not self.heartbeat_enabled:
            return
        self.send(
            "HEARTBEAT",
            {
                "timestamp": time.time(),
                "state": "BUSY" if not self.frame_queue.empty() else "HEALTHY",
                "activeMatchId": self.current_match.id,
            },
            "heartbeat",
            correlation_id=envelope.get("requestId"),
        )

    # -- main loop ----------------------------------------------------------
    def run(self) -> int:
        self.log(
            "engine.start",
            pipeName=self.pipe_name,
            mapName=self.map_name,
            frameBufferSize=self.frame_buffer_size,
            pid=os.getpid(),
            catalogPath=str(self.catalog_path),
            dataOrigin=self.data_origin,
        )
        try:
            self.pipe = PipeClient(self.pipe_name)
            self.log("pipe.connected")
            self.reader = FrameMapReader(self.map_name, self.frame_buffer_size)
            _atomic_json(self.work_dir / "engine_mmf_probe.json", self.reader.probe())
            self.log("mmf.read_only_mapped", mapName=self.map_name, mapSize=MAP_SIZE)
            self.worker = threading.Thread(target=self._worker_loop, name="nte-v22-vision", daemon=True)
            self.worker.start()

            while True:
                envelope = self.recv_polling()
                if envelope is None:
                    self.log("pipe.eof")
                    return 0
                self.log(
                    "recv",
                    messageType=envelope.get("messageType"),
                    sequence=envelope.get("sequence"),
                    requestId=envelope.get("requestId"),
                )
                try:
                    self.validate_inbound(envelope)
                    if envelope.get("sessionId") != self.session_id:
                        raise ProtocolError("ERR_STALE_SESSION", "envelope sessionId mismatch")
                    message_type = envelope.get("messageType")
                    if message_type == "HELLO":
                        self.handle_hello(envelope)
                    elif message_type == "HEARTBEAT":
                        self.handle_heartbeat(envelope)
                    elif message_type == "STATE_SNAPSHOT_REQUEST":
                        self.handle_state_snapshot_request(envelope)
                    elif message_type == "FRAME_READY":
                        if not self.hello_seen:
                            raise ProtocolError("ERR_MESSAGE_BEFORE_HANDSHAKE", "FRAME_READY before HELLO")
                        self.handle_frame_ready(envelope)
                    elif message_type == "COMMAND":
                        self.handle_command(envelope)
                    elif message_type == "ABORT_SCAN":
                        self._invalidate_deferred_identity("abort_scan")
                        self.log("scan.aborted", reason=(envelope.get("payload") or {}).get("reason"))
                    elif message_type == "ENGINE_SHUTDOWN":
                        self._invalidate_deferred_identity("engine_shutdown")
                        self.log("shutdown.requested", reason=(envelope.get("payload") or {}).get("reason"))
                        return 0
                    else:
                        self.send_error("ERR_UNKNOWN_MESSAGE_TYPE", "PROTOCOL", f"unsupported message {message_type}")
                except ProtocolError as exc:
                    self.reader_error = exc.error_code
                    self.log("protocol_error", errorCode=exc.error_code, message=str(exc))
                    self.send_error(exc.error_code, "PROTOCOL", str(exc), True)
                    return 9
        finally:
            self.stop_event.set()
            self._invalidate_deferred_identity("engine_exit")
            if self.worker is not None:
                self.worker.join(timeout=1.5)
            if self._identity_analyzer is not None:
                self._identity_analyzer.close(timeout=0.25)
            try:
                self._persist_state(reason="engine_exit")
            except Exception as exc:
                self.log("state.persist_on_exit_failed", error=str(exc))
            if self.reader is not None:
                self.reader.close()
            if self.pipe is not None:
                self.pipe.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="V2-2 real NTE Engine adapter")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--pipe-name", required=True)
    parser.add_argument("--frame-buffer-name", required=True)
    parser.add_argument("--frame-buffer-size", type=int, required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--generation-id", type=int, default=1)
    parser.add_argument("--log", default=None)
    parser.add_argument("--fault", default=None)
    parser.add_argument("--fault-missing-mandatory-capability", default=None)
    parser.add_argument("--fault-hello-size", default=None)
    parser.add_argument("--data-origin", default="replay")
    parser.add_argument("--catalog", default=None)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        engine = RealEngine(args)
    except Exception as exc:
        print(json.dumps({"event": "business_preload_failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 12
    try:
        return engine.run()
    except ProtocolError as exc:
        engine.log("engine.protocol_error", errorCode=exc.error_code, message=str(exc))
        engine.send_error(exc.error_code, "TRANSPORT", str(exc), True)
        return 9
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
