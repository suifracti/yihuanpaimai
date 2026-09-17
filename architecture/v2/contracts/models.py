"""
architecture/v2/contracts/models.py

Standardized Python models, dataclasses, binary framing, struct packing,
and contract validators for NTE Architecture V2 Host-Engine IPC Protocol.
"""

from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

# Protocol & Framing Constants
PROTOCOL_VERSION: str = "1.0.0"
FRAME_HEADER_MAGIC: int = 0x4246544E  # ASCII 'NTFB' in little-endian
FRAME_HEADER_VERSION: int = 1
FRAME_HEADER_SIZE: int = 64
MAX_MESSAGE_BYTES: int = 1048576  # 1 MB maximum length prefix
DEFAULT_PIXEL_FORMAT_BGRA8: int = 1

# Struct layout: 64 bytes little-endian (<I i q i i i i i i q q I i)
FRAME_HEADER_STRUCT_FORMAT: str = "<IiqiiiiiiqqIi"
assert struct.calcsize(FRAME_HEADER_STRUCT_FORMAT) == FRAME_HEADER_SIZE


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


class FrameAckStatus(str, Enum):
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


class LifecycleStateMachine:
    VALID_TRANSITIONS: Dict[LifecycleState, List[LifecycleState]] = {
        LifecycleState.ENGINE_DOWN: [LifecycleState.STARTING],
        LifecycleState.STARTING: [LifecycleState.HANDSHAKING, LifecycleState.ENGINE_DOWN],
        LifecycleState.HANDSHAKING: [LifecycleState.SYNCING, LifecycleState.READY, LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN],
        LifecycleState.SYNCING: [LifecycleState.READY, LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN],
        LifecycleState.READY: [LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN],
        LifecycleState.DEGRADED: [LifecycleState.READY, LifecycleState.SYNCING, LifecycleState.ENGINE_DOWN],
    }

    def __init__(self, initial_state: LifecycleState = LifecycleState.ENGINE_DOWN):
        self._current_state = initial_state

    @property
    def current_state(self) -> LifecycleState:
        return self._current_state

    def transition_to(self, new_state: LifecycleState) -> LifecycleState:
        allowed = self.VALID_TRANSITIONS.get(self._current_state, [])
        if new_state not in allowed:
            raise ContractValidationError(
                "ERR_AUTHORITY_VIOLATION",
                f"Invalid lifecycle transition from {self._current_state.value} to {new_state.value}. Allowed: {[s.value for s in allowed]}"
            )
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

# Required payload fields mapped from message_catalog_v1.json
REQUIRED_PAYLOAD_FIELDS: Dict[str, List[str]] = {
    "HELLO": ["hostVersion", "supportedProtocols", "sessionNonce", "capabilities", "frameBufferName", "frameBufferSize"],
    "HELLO_ACK": ["engineVersion", "negotiatedProtocol", "status", "enginePid"],
    "HEARTBEAT": ["timestamp", "state"],
    "FRAME_READY": ["bufferIndex", "sequence", "width", "height", "stride", "pixelFormat", "captureTimestampNs"],
    "FRAME_ACK": ["bufferIndex", "sequence", "status"],
    "PERCEPTION_RESULT": ["frameSequence", "scene", "inAuction", "bids"],
    "ABORT_SCAN": ["reason", "triggerTimestampNs"],
    "COMMAND": ["commandId", "action", "expiresAtNs"],
    "COMMAND_RESULT": ["commandId", "status"],
    "STATE_SNAPSHOT_REQUEST": ["includeDrafts"],
    "STATE_SNAPSHOT": ["matchState", "draftCount", "finalizedCount", "snapshotSequence"],
    "ENGINE_SHUTDOWN": ["reason", "timeoutMs"],
    "ENGINE_RESTARTING": ["reason", "exitCode"],
    "ERROR": ["errorCode", "category", "message", "isFatal"],
}


def validate_envelope(msg_dict: Dict[str, Any]) -> Envelope:
    """Validates envelope schema against protocol_v1.json fail-closed rules."""
    for req_field in REQUIRED_ENVELOPE_FIELDS:
        if req_field not in msg_dict:
            raise ContractValidationError(
                "ERR_MALFORMED_ENVELOPE",
                f"Missing required envelope field: {req_field}"
            )

    proto_ver = msg_dict["protocolVersion"]
    if not isinstance(proto_ver, str) or proto_ver != PROTOCOL_VERSION:
        raise ContractValidationError(
            "ERR_PROTOCOL_VERSION_MISMATCH",
            f"Unsupported protocolVersion '{proto_ver}', expected '{PROTOCOL_VERSION}'"
        )

    msg_type = msg_dict["messageType"]
    valid_types = {t.value for t in MessageType}
    if msg_type not in valid_types:
        raise ContractValidationError(
            "ERR_UNKNOWN_MESSAGE_TYPE",
            f"Unrecognized messageType '{msg_type}'. Valid types: {sorted(valid_types)}"
        )

    if not isinstance(msg_dict["sequence"], int):
        raise ContractValidationError(
            "ERR_MALFORMED_ENVELOPE",
            "Field 'sequence' must be an integer"
        )

    if not isinstance(msg_dict["monotonicTimestampNs"], int):
        raise ContractValidationError(
            "ERR_MALFORMED_ENVELOPE",
            "Field 'monotonicTimestampNs' must be an integer"
        )

    if not isinstance(msg_dict["payload"], dict):
        raise ContractValidationError(
            "ERR_MALFORMED_ENVELOPE",
            "Field 'payload' must be a dictionary object"
        )

    # Validate required payload fields per message type
    req_payload_fields = REQUIRED_PAYLOAD_FIELDS.get(msg_type, [])
    payload = msg_dict["payload"]
    for req_p in req_payload_fields:
        if req_p not in payload:
            raise ContractValidationError(
                "ERR_MISSING_REQUIRED_FIELD",
                f"Payload for {msg_type} missing required field: '{req_p}'"
            )

    return Envelope(
        protocolVersion=proto_ver,
        sessionId=str(msg_dict["sessionId"]),
        messageType=msg_type,
        requestId=str(msg_dict["requestId"]),
        correlationId=str(msg_dict["correlationId"]) if msg_dict["correlationId"] is not None else None,
        sequence=msg_dict["sequence"],
        monotonicTimestampNs=msg_dict["monotonicTimestampNs"],
        payload=payload,
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
    Raises ContractValidationError or ValueError if buffer is incomplete or corrupt.
    """
    if len(buffer) < 4:
        raise ValueError("Buffer too short to read length prefix")
    payload_len = struct.unpack_from("<I", buffer, 0)[0]
    if payload_len > MAX_MESSAGE_BYTES:
        raise ContractValidationError(
            "ERR_MESSAGE_TOO_LARGE",
            f"Framed payload length {payload_len} exceeds max {MAX_MESSAGE_BYTES}"
        )
    total_len = 4 + payload_len
    if len(buffer) < total_len:
        raise ValueError(f"Incomplete message: need {total_len} bytes, got {len(buffer)}")

    raw_json = buffer[4:total_len].decode("utf-8")
    try:
        msg_dict = json.loads(raw_json)
    except Exception as e:
        raise ContractValidationError(
            "ERR_SCHEMA_VALIDATION_FAILED",
            f"Invalid JSON in message body: {str(e)}"
        )
    envelope = validate_envelope(msg_dict)
    return envelope, total_len
