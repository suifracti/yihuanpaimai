"""
architecture/v2/contracts/models.py

Standardized Python models, dataclasses, binary framing, ring-buffer geometry,
connection-generation sequence trackers, QPC clock domain expiry, struct packing,
and fail-closed validators for NTE Architecture V2 Host-Engine IPC Protocol.
"""

from __future__ import annotations

import json
import struct
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

# Protocol & Framing Constants
PROTOCOL_VERSION: str = "1.0.0"
FRAME_HEADER_MAGIC: int = 0x4246544E  # ASCII 'NTFB' in little-endian
FRAME_HEADER_VERSION: int = 1
FRAME_HEADER_SIZE: int = 64
MAX_MESSAGE_BYTES: int = 1048576  # 1 MB maximum length prefix
DEFAULT_PIXEL_FORMAT_BGRA8: int = 1

# Ring Buffer Geometry Constants & Invariants
SLOT_COUNT: int = 4
MAX_FRAME_WIDTH: int = 1920
MAX_FRAME_HEIGHT: int = 1080
SLOT_PAYLOAD_CAPACITY_BYTES: int = 8294400  # 1920 * 1080 * 4
SLOT_SIZE_BYTES: int = 8294464             # 64 + 8294400
SLOT_ALIGNMENT_BYTES: int = 64
MAP_TOTAL_SIZE_BYTES: int = 33177856       # 4 * 8294464

# Struct layout: 64 bytes little-endian (<I i q i i i i i i q q I i)
FRAME_HEADER_STRUCT_FORMAT: str = "<IiqiiiiiiqqIi"
assert struct.calcsize(FRAME_HEADER_STRUCT_FORMAT) == FRAME_HEADER_SIZE


def get_slot_offset(slot_index: int) -> int:
    """Calculates byte offset for ring buffer slot index."""
    if not (0 <= slot_index < SLOT_COUNT):
        raise ContractValidationError(
            "ERR_SLOT_INDEX_OUT_OF_BOUNDS",
            f"Buffer index {slot_index} out of bounds (valid: 0 <= index < {SLOT_COUNT})"
        )
    return slot_index * SLOT_SIZE_BYTES


class MessageType(str, Enum):
    HELLO = "HELLO"
    HELLO_ACK = "HELLO_ACK"
    HEARTBEAT = "HEARTBEAT"
    FRAME_READY = "FRAME_READY"
    FRAME_ACK = "FRAME_ACK"
    PERCEPTION_RESULT = "PERCEPTION_RESULT"
    ABORT_SCAN = "ABORT_SCAN"
    COMMAND = "COMMAND"
    COMMAND_RESULT = "COMMAND_RESULT"
    STATE_SNAPSHOT_REQUEST = "STATE_SNAPSHOT_REQUEST"
    STATE_SNAPSHOT = "STATE_SNAPSHOT"
    ENGINE_SHUTDOWN = "ENGINE_SHUTDOWN"
    ENGINE_RESTARTING = "ENGINE_RESTARTING"
    ERROR = "ERROR"


class CapabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    EXPERIMENTAL = "EXPERIMENTAL"
    NOT_MEASURED = "NOT_MEASURED"


class LifecycleState(str, Enum):
    ENGINE_DOWN = "ENGINE_DOWN"
    STARTING = "STARTING"
    HANDSHAKING = "HANDSHAKING"
    SYNCING = "SYNCING"
    READY = "READY"
    DEGRADED = "DEGRADED"


class ErrorCategory(str, Enum):
    PROTOCOL = "PROTOCOL"
    TRANSPORT = "TRANSPORT"
    PAYLOAD = "PAYLOAD"
    TIMEOUT = "TIMEOUT"
    AUTHORITY = "AUTHORITY"
    CAPABILITY = "CAPABILITY"


class HelloAckStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_VERSION = "REJECTED_VERSION"
    REJECTED_CAPABILITY = "REJECTED_CAPABILITY"


class EngineReadiness(str, Enum):
    STARTING = "STARTING"
    LOADING = "LOADING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class FrameAckStatus(str, Enum):
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    SKIPPED = "SKIPPED"
    CORRUPTED = "CORRUPTED"


class CommandResultStatus(str, Enum):
    ACK = "ACK"
    REJECT = "REJECT"
    EXPIRED = "EXPIRED"
    STALE_SESSION = "STALE_SESSION"
    DUPLICATE = "DUPLICATE"
    NOT_FOREGROUND = "NOT_FOREGROUND"
    FROZEN = "FROZEN"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    FAILED = "FAILED"


class AbortReason(str, Enum):
    USER_TAKEOVER = "USER_TAKEOVER"
    FOCUS_LOST = "FOCUS_LOST"
    ESCAPE_KEY = "ESCAPE_KEY"
    TARGET_CLOSED = "TARGET_CLOSED"


class SlotState(str, Enum):
    FREE = "FREE"
    WRITING = "WRITING"
    COMMITTED = "COMMITTED"
    CONSUMER_LOCKED = "CONSUMER_LOCKED"


class ContractValidationError(ValueError):
    """Raised when envelope, payload, or binary frame header violates contract rules."""
    def __init__(self, error_code: str, message: str):
        super().__init__(f"[{error_code}] {message}")
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class Envelope:
    protocolVersion: str
    sessionId: str
    messageType: str
    requestId: str
    correlationId: Optional[str]
    sequence: int
    monotonicTimestampNs: int
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocolVersion": self.protocolVersion,
            "sessionId": self.sessionId,
            "messageType": self.messageType,
            "requestId": self.requestId,
            "correlationId": self.correlationId,
            "sequence": self.sequence,
            "monotonicTimestampNs": self.monotonicTimestampNs,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False)


@dataclass
class FrameHeaderV1:
    magic: int = FRAME_HEADER_MAGIC
    headerVersion: int = FRAME_HEADER_VERSION
    sequence: int = 0
    width: int = 1920
    height: int = 1080
    stride: int = 7680
    pixelFormat: int = DEFAULT_PIXEL_FORMAT_BGRA8
    bufferLength: int = 8294400
    flags: int = 0
    captureTimestampNs: int = 0
    producerTimestampNs: int = 0
    cornerChecksum: int = 0
    reserved: int = 0

    def pack(self) -> bytes:
        return struct.pack(
            FRAME_HEADER_STRUCT_FORMAT,
            self.magic,
            self.headerVersion,
            self.sequence,
            self.width,
            self.height,
            self.stride,
            self.pixelFormat,
            self.bufferLength,
            self.flags,
            self.captureTimestampNs,
            self.producerTimestampNs,
            self.cornerChecksum,
            self.reserved,
        )

    @classmethod
    def unpack(cls, buffer: bytes, offset: int = 0) -> "FrameHeaderV1":
        if len(buffer) - offset < FRAME_HEADER_SIZE:
            raise ContractValidationError(
                "ERR_FRAME_PAYLOAD_TOO_SHORT",
                f"Buffer size {len(buffer) - offset} is less than required header size {FRAME_HEADER_SIZE}"
            )
        vals = struct.unpack_from(FRAME_HEADER_STRUCT_FORMAT, buffer, offset)
        header = cls(
            magic=vals[0],
            headerVersion=vals[1],
            sequence=vals[2],
            width=vals[3],
            height=vals[4],
            stride=vals[5],
            pixelFormat=vals[6],
            bufferLength=vals[7],
            flags=vals[8],
            captureTimestampNs=vals[9],
            producerTimestampNs=vals[10],
            cornerChecksum=vals[11],
            reserved=vals[12],
        )
        header.validate()
        return header

    def validate(self) -> None:
        if self.magic != FRAME_HEADER_MAGIC:
            raise ContractValidationError(
                "ERR_CORRUPT_FRAME_MAGIC",
                f"Invalid frame magic 0x{self.magic:08X}, expected 0x{FRAME_HEADER_MAGIC:08X}"
            )
        if self.headerVersion != FRAME_HEADER_VERSION:
            raise ContractValidationError(
                "ERR_PROTOCOL_VERSION_MISMATCH",
                f"Unsupported frame header version {self.headerVersion}, expected {FRAME_HEADER_VERSION}"
            )
        if self.pixelFormat != DEFAULT_PIXEL_FORMAT_BGRA8:
            raise ContractValidationError(
                "ERR_UNSUPPORTED_PIXEL_FORMAT",
                f"Unsupported pixel format {self.pixelFormat}, expected {DEFAULT_PIXEL_FORMAT_BGRA8} (BGRA8)"
            )
        # Capacity and dimension invariants
        if self.width > MAX_FRAME_WIDTH or self.height > MAX_FRAME_HEIGHT:
            raise ContractValidationError(
                "ERR_FRAME_CAPACITY_EXCEEDED",
                f"Frame geometry {self.width}x{self.height} exceeds max capacity {MAX_FRAME_WIDTH}x{MAX_FRAME_HEIGHT}"
            )
        expected_stride = self.width * 4
        if self.stride != expected_stride:
            raise ContractValidationError(
                "ERR_FRAME_METADATA_MISMATCH",
                f"Stride {self.stride} does not match expected width * 4 = {expected_stride}"
            )
        expected_length = self.stride * self.height
        if self.bufferLength != expected_length:
            raise ContractValidationError(
                "ERR_FRAME_METADATA_MISMATCH",
                f"BufferLength {self.bufferLength} does not match expected stride * height = {expected_length}"
            )
        if self.bufferLength > SLOT_PAYLOAD_CAPACITY_BYTES:
            raise ContractValidationError(
                "ERR_FRAME_CAPACITY_EXCEEDED",
                f"BufferLength {self.bufferLength} exceeds slot capacity {SLOT_PAYLOAD_CAPACITY_BYTES}"
            )


def verify_frame_metadata_match(frame_ready_payload: Dict[str, Any], header: FrameHeaderV1) -> None:
    """Verifies that FRAME_READY message payload matches shared memory header exact."""
    checks = [
        ("sequence", frame_ready_payload.get("sequence"), header.sequence),
        ("width", frame_ready_payload.get("width"), header.width),
        ("height", frame_ready_payload.get("height"), header.height),
        ("stride", frame_ready_payload.get("stride"), header.stride),
        ("pixelFormat", frame_ready_payload.get("pixelFormat"), header.pixelFormat),
        ("bufferLength", frame_ready_payload.get("bufferLength"), header.bufferLength),
        ("captureTimestampNs", frame_ready_payload.get("captureTimestampNs"), header.captureTimestampNs),
        ("checksum", frame_ready_payload.get("checksum"), header.cornerChecksum),
    ]
    for field_name, payload_val, header_val in checks:
        if payload_val != header_val:
            raise ContractValidationError(
                "ERR_FRAME_METADATA_MISMATCH",
                f"FRAME_READY metadata mismatch for '{field_name}': payload={payload_val}, header={header_val}"
            )


def verify_message_allowed_in_state(current_state: LifecycleState, message_type: str) -> None:
    """Ensures operational messages cannot be processed before completing handshake."""
    if current_state in (LifecycleState.ENGINE_DOWN, LifecycleState.STARTING, LifecycleState.HANDSHAKING):
        allowed = {"HELLO", "HELLO_ACK", "HEARTBEAT", "ENGINE_SHUTDOWN", "ERROR"}
        if message_type not in allowed:
            raise ContractValidationError(
                "ERR_MESSAGE_BEFORE_HANDSHAKE",
                f"Message '{message_type}' is forbidden in lifecycle state '{current_state.value}' prior to handshake completion"
            )


@dataclass
class DropCounters:
    producerOverwrite: int = 0
    consumerTimeout: int = 0
    captureFailure: int = 0
    contentInvalid: int = 0
    frameSuperseded: int = 0
    bufferUnavailable: int = 0

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


class SequenceTracker:
    """
    Tracks monotonic sequence high-water marks per sender per connection generation.
    Generation key: (sessionId, sessionNonce, senderRole).
    """
    def __init__(self, session_id: str, session_nonce: str):
        self.session_id: str = session_id
        self.current_nonce: str = session_nonce
        self._sender_high_water: Dict[Tuple[str, str, str], int] = {}

    def reset_generation(self, session_id: str, new_nonce: str) -> None:
        """Called upon new HELLO/HELLO_ACK handshake negotiation."""
        self.session_id = session_id
        self.current_nonce = new_nonce

    def check_and_update(self, sender_role: str, session_id: str, session_nonce: str, sequence: int) -> None:
        if session_id != self.session_id:
            raise ContractValidationError(
                "ERR_STALE_SESSION",
                f"Session ID '{session_id}' does not match active session '{self.session_id}'"
            )
        if session_nonce != self.current_nonce:
            raise ContractValidationError(
                "ERR_STALE_GENERATION",
                f"Session nonce '{session_nonce}' belongs to an earlier or unknown connection generation"
            )
        if sequence < 0:
            raise ContractValidationError(
                "ERR_MALFORMED_ENVELOPE",
                f"Negative sequence {sequence} not allowed"
            )
        gen_key = (session_id, session_nonce, sender_role)
        last_seq = self._sender_high_water.get(gen_key, -1)
        if sequence <= last_seq:
            raise ContractValidationError(
                "ERR_STALE_SEQUENCE",
                f"Stale sequence {sequence} for generation {gen_key} (last high-water: {last_seq})"
            )
        self._sender_high_water[gen_key] = sequence


class CommandIdempotencyManager:
    """Deduplicates incoming COMMAND messages by (sessionId, commandId) in QPC clock domain."""
    def __init__(self, retention_seconds: int = 300):
        self.retention_seconds: int = retention_seconds
        self._cache: Dict[Tuple[str, str], Tuple[Dict[str, Any], Optional[Dict[str, Any]], int, float]] = {}

    def process_command(self, session_id: str, command_id: str, action: str, parameters: Dict[str, Any], expires_at_ns: int, receiver_now_ns: int) -> Optional[Dict[str, Any]]:
        """
        Evaluates receiverNowNs >= expiresAtNs upon arrival.
        Returns cached result if identical replay.
        Raises ContractValidationError if mismatched payload reuse.
        """
        key = (session_id, command_id)
        current_payload = {"action": action, "parameters": parameters}

        if receiver_now_ns >= expires_at_ns:
            return {"commandId": command_id, "status": "EXPIRED", "errorDetails": "Command expired before receipt evaluation"}

        if key in self._cache:
            cached_payload, cached_result, exp_ns, _ = self._cache[key]
            if cached_payload != current_payload:
                raise ContractValidationError(
                    "ERR_COMMAND_ID_REUSE_MISMATCH",
                    f"CommandId '{command_id}' reused in session '{session_id}' with conflicting action or parameters"
                )
            if cached_result is not None:
                return cached_result
            raise ContractValidationError(
                "ERR_DUPLICATE_COMMAND",
                f"CommandId '{command_id}' is currently pending execution"
            )

        self._cache[key] = (current_payload, None, expires_at_ns, time.time())
        return None

    def store_result(self, session_id: str, command_id: str, result: Dict[str, Any]) -> None:
        key = (session_id, command_id)
        if key in self._cache:
            payload, _, exp, ts = self._cache[key]
            self._cache[key] = (payload, result, exp, ts)


class RingBufferSlotManager:
    """Tracks slot lifecycle states and guarantees no overwrite of consumer-locked slots."""
    def __init__(self, slot_count: int = SLOT_COUNT):
        self.slot_count: int = slot_count
        self._states: List[SlotState] = [SlotState.FREE] * slot_count
        self._active_lock: List[Optional[Tuple[str, int]]] = [None] * slot_count  # (sessionId, sequence)

    def allocate_write_slot(self) -> int:
        for idx in range(self.slot_count):
            if self._states[idx] == SlotState.FREE:
                self._states[idx] = SlotState.WRITING
                return idx
        raise ContractValidationError(
            "ERR_BUFFER_UNAVAILABLE",
            f"All {self.slot_count} ring buffer slots are locked"
        )

    def commit_frame(self, slot_index: int, session_id: str, sequence: int) -> None:
        if not (0 <= slot_index < self.slot_count):
            raise ContractValidationError("ERR_SLOT_INDEX_OUT_OF_BOUNDS", f"Invalid index {slot_index}")
        self._states[slot_index] = SlotState.CONSUMER_LOCKED
        self._active_lock[slot_index] = (session_id, sequence)

    def release_slot(self, slot_index: int, session_id: str, sequence: int) -> None:
        if not (0 <= slot_index < self.slot_count):
            raise ContractValidationError("ERR_SLOT_INDEX_OUT_OF_BOUNDS", f"Invalid slot index {slot_index}")
        if self._states[slot_index] != SlotState.CONSUMER_LOCKED:
            raise ContractValidationError("ERR_SLOT_NOT_LOCKED", f"Slot {slot_index} is not in CONSUMER_LOCKED state")
        active = self._active_lock[slot_index]
        if active != (session_id, sequence):
            raise ContractValidationError(
                "ERR_UNKNOWN_FRAME_ACK",
                f"Release token ({session_id}, {sequence}) does not match active lock {active} on slot {slot_index}"
            )
        self._states[slot_index] = SlotState.FREE
        self._active_lock[slot_index] = None

    def get_slot_state(self, slot_index: int) -> SlotState:
        if not (0 <= slot_index < self.slot_count):
            raise ContractValidationError("ERR_SLOT_INDEX_OUT_OF_BOUNDS", f"Invalid index {slot_index}")
        return self._states[slot_index]


class LifecycleStateMachine:
    VALID_TRANSITIONS: Dict[LifecycleState, List[LifecycleState]] = {
        LifecycleState.ENGINE_DOWN: [LifecycleState.STARTING],
        LifecycleState.STARTING: [LifecycleState.HANDSHAKING, LifecycleState.ENGINE_DOWN],
        LifecycleState.HANDSHAKING: [LifecycleState.SYNCING, LifecycleState.READY, LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN],
        LifecycleState.SYNCING: [LifecycleState.READY, LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN],
        LifecycleState.READY: [LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN],
        LifecycleState.DEGRADED: [LifecycleState.READY, LifecycleState.SYNCING, LifecycleState.ENGINE_DOWN],
    }

    def __init__(self, initial_state: LifecycleState = LifecycleState.ENGINE_DOWN, is_cold_boot: bool = True):
        self._current_state: LifecycleState = initial_state
        self.is_cold_boot: bool = is_cold_boot
        self.protocol_negotiated: bool = False
        self.capabilities_accepted: bool = False
        self.engine_business_ready: bool = False
        self.snapshot_resynced: bool = False

    @property
    def current_state(self) -> LifecycleState:
        return self._current_state

    def transition_to(self, new_state: LifecycleState) -> LifecycleState:
        allowed = self.VALID_TRANSITIONS.get(self._current_state, [])
        if new_state not in allowed:
            raise ContractValidationError(
                "ERR_INVALID_STATE_TRANSITION",
                f"Invalid lifecycle transition from {self._current_state.value} to {new_state.value}. Allowed: {[s.value for s in allowed]}"
            )

        # Enforce READY Gate Invariants
        if new_state == LifecycleState.READY:
            if self._current_state == LifecycleState.HANDSHAKING:
                if not self.is_cold_boot:
                    raise ContractValidationError(
                        "ERR_INVALID_STATE_TRANSITION",
                        "Direct transition from HANDSHAKING to READY is forbidden on reconnect; MUST transition to SYNCING first"
                    )
                if not self.engine_business_ready:
                    raise ContractValidationError(
                        "ERR_INVALID_STATE_TRANSITION",
                        "Cannot transition to READY on cold boot while engine_business_ready is false"
                    )
            elif self._current_state == LifecycleState.SYNCING:
                if not (self.engine_business_ready and self.snapshot_resynced):
                    raise ContractValidationError(
                        "ERR_INVALID_STATE_TRANSITION",
                        "Cannot transition from SYNCING to READY without validated snapshot and businessReady == true"
                    )

        if self._current_state == LifecycleState.READY and new_state in [LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN]:
            self.is_cold_boot = False
            self.snapshot_resynced = False

        self._current_state = new_state
        return self._current_state


REQUIRED_ENVELOPE_FIELDS = [
    "protocolVersion",
    "sessionId",
    "messageType",
    "requestId",
    "correlationId",
    "sequence",
    "monotonicTimestampNs",
    "payload",
]

REQUIRED_PAYLOAD_FIELDS: Dict[str, List[str]] = {
    "HELLO": ["hostVersion", "supportedProtocols", "sessionNonce", "capabilities", "frameBufferName", "slotCount", "slotSizeBytes", "mapTotalSizeBytes"],
    "HELLO_ACK": ["engineVersion", "negotiatedProtocol", "status", "readiness", "enginePid", "slotCount", "slotSizeBytes", "mapTotalSizeBytes", "engineBusinessReady"],
    "HEARTBEAT": ["timestamp", "state"],
    "FRAME_READY": ["sessionId", "bufferIndex", "sequence", "width", "height", "stride", "pixelFormat", "bufferLength", "captureTimestampNs", "checksum"],
    "FRAME_ACK": ["sessionId", "bufferIndex", "sequence", "status"],
    "PERCEPTION_RESULT": ["frameSequence", "scene", "inAuction", "bids"],
    "ABORT_SCAN": ["reason", "triggerTimestampNs"],
    "COMMAND": ["commandId", "action", "parameters", "expiresAtNs"],
    "COMMAND_RESULT": ["commandId", "status"],
    "STATE_SNAPSHOT_REQUEST": ["includeDrafts"],
    "STATE_SNAPSHOT": ["snapshotSchemaVersion", "snapshotSessionId", "snapshotSequence", "businessReady", "currentMatchProjection"],
    "ENGINE_SHUTDOWN": ["reason", "timeoutMs"],
    "ENGINE_RESTARTING": ["reason", "exitCode"],
    "ERROR": ["errorCode", "category", "message", "isFatal"],
}


def validate_envelope(msg_dict: Dict[str, Any]) -> Envelope:
    """Validates envelope schema against protocol_v1.json fail-closed rules without type coercion."""
    if not isinstance(msg_dict, dict):
        raise ContractValidationError("ERR_MALFORMED_ENVELOPE", "Envelope must be a JSON dictionary")

    for req_field in REQUIRED_ENVELOPE_FIELDS:
        if req_field not in msg_dict:
            raise ContractValidationError(
                "ERR_MALFORMED_ENVELOPE",
                f"Missing required envelope field: '{req_field}'"
            )

    proto_ver = msg_dict["protocolVersion"]
    if not isinstance(proto_ver, str) or proto_ver != PROTOCOL_VERSION:
        raise ContractValidationError(
            "ERR_PROTOCOL_VERSION_MISMATCH",
            f"Unsupported protocolVersion '{proto_ver}', exact '{PROTOCOL_VERSION}' required"
        )

    session_id = msg_dict["sessionId"]
    if not isinstance(session_id, str) or len(session_id.strip()) == 0:
        raise ContractValidationError(
            "ERR_MALFORMED_ENVELOPE",
            "Field 'sessionId' must be a non-empty string"
        )

    msg_type = msg_dict["messageType"]
    valid_types = {t.value for t in MessageType}
    if not isinstance(msg_type, str) or msg_type not in valid_types:
        raise ContractValidationError(
            "ERR_UNKNOWN_MESSAGE_TYPE",
            f"Unrecognized messageType '{msg_type}'. Valid types: {sorted(valid_types)}"
        )

    req_id = msg_dict["requestId"]
    if not isinstance(req_id, str) or len(req_id.strip()) == 0:
        raise ContractValidationError(
            "ERR_MALFORMED_ENVELOPE",
            "Field 'requestId' must be a non-empty string"
        )

    corr_id = msg_dict["correlationId"]
    if corr_id is not None and not isinstance(corr_id, str):
        raise ContractValidationError(
            "ERR_MALFORMED_ENVELOPE",
            "Field 'correlationId' must be a string or null"
        )

    seq = msg_dict["sequence"]
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise ContractValidationError(
            "ERR_MALFORMED_ENVELOPE",
            "Field 'sequence' must be a non-negative integer (int64 >= 0)"
        )

    ts_ns = msg_dict["monotonicTimestampNs"]
    if isinstance(ts_ns, bool) or not isinstance(ts_ns, int) or ts_ns < 0:
        raise ContractValidationError(
            "ERR_MALFORMED_ENVELOPE",
            "Field 'monotonicTimestampNs' must be a non-negative integer (int64 >= 0)"
        )

    payload = msg_dict["payload"]
    if not isinstance(payload, dict):
        raise ContractValidationError(
            "ERR_MALFORMED_ENVELOPE",
            "Field 'payload' must be a dictionary object"
        )

    # Validate required payload fields per message type
    req_payload_fields = REQUIRED_PAYLOAD_FIELDS.get(msg_type, [])
    for req_p in req_payload_fields:
        if req_p not in payload:
            raise ContractValidationError(
                "ERR_MISSING_REQUIRED_FIELD",
                f"Payload for {msg_type} missing required field: '{req_p}'"
            )

    return Envelope(
        protocolVersion=proto_ver,
        sessionId=session_id,
        messageType=msg_type,
        requestId=req_id,
        correlationId=corr_id,
        sequence=seq,
        monotonicTimestampNs=ts_ns,
        payload=payload,
    )


def validate_state_snapshot(snapshot_envelope: Envelope, active_session_id: str) -> None:
    """Validates STATE_SNAPSHOT session and projection integrity."""
    if snapshot_envelope.messageType != MessageType.STATE_SNAPSHOT.value:
        raise ContractValidationError("ERR_UNKNOWN_MESSAGE_TYPE", "Expected STATE_SNAPSHOT message")
    payload = snapshot_envelope.payload
    snap_sess = payload.get("snapshotSessionId")
    if snap_sess != active_session_id:
        raise ContractValidationError(
            "ERR_STALE_SESSION",
            f"STATE_SNAPSHOT snapshotSessionId '{snap_sess}' does not match active session '{active_session_id}'"
        )


def encode_framed_message(envelope: Envelope) -> bytes:
    """Encodes envelope to 4-byte uint32 length prefix + UTF-8 JSON."""
    json_bytes = envelope.to_json().encode("utf-8")
    payload_len = len(json_bytes)
    if payload_len > MAX_MESSAGE_BYTES:
        raise ContractValidationError(
            "ERR_MESSAGE_TOO_LARGE",
            f"Message length {payload_len} exceeds maximum allowed {MAX_MESSAGE_BYTES}"
        )
    return struct.pack("<I", payload_len) + json_bytes


def decode_framed_message(buffer: bytes) -> Tuple[Envelope, int]:
    """
    Decodes length-prefixed message from buffer.
    Returns (Envelope, bytes_consumed).
    Raises ContractValidationError if buffer is incomplete, oversized, or corrupt.
    """
    if len(buffer) < 4:
        raise ContractValidationError(
            "ERR_INCOMPLETE_FRAME",
            f"Buffer size {len(buffer)} is too short to read 4-byte length prefix"
        )
    payload_len = struct.unpack_from("<I", buffer, 0)[0]
    if payload_len > MAX_MESSAGE_BYTES:
        raise ContractValidationError(
            "ERR_MESSAGE_TOO_LARGE",
            f"Framed payload length {payload_len} exceeds max {MAX_MESSAGE_BYTES}"
        )
    total_len = 4 + payload_len
    if len(buffer) < total_len:
        raise ContractValidationError(
            "ERR_INCOMPLETE_FRAME",
            f"Incomplete message body: need {total_len} bytes, got {len(buffer)}"
        )

    try:
        raw_json = buffer[4:total_len].decode("utf-8")
        msg_dict = json.loads(raw_json)
    except Exception as e:
        raise ContractValidationError(
            "ERR_SCHEMA_VALIDATION_FAILED",
            f"Invalid JSON in message body: {str(e)}"
        )
    envelope = validate_envelope(msg_dict)
    return envelope, total_len
