"""Read-only V2-3 Engine probe.

This process intentionally stops at transport validation: it reads the Host-owned
fixed-v1 MMF, verifies the FrameHeaderV1/FRAME_READY contract and pixel checksum,
returns FRAME_ACK, and emits a transport-only PERCEPTION_RESULT so the existing
SupervisorSession can complete its normal ACK wait. It does not run OCR, vision,
history, or any input path.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sys
from dataclasses import asdict
from typing import Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
ENGINE_REF_DIR = os.path.join(REPO_ROOT, "architecture", "v2", "host", "engine_ref")
CONTRACTS_DIR = os.path.join(REPO_ROOT, "architecture", "v2", "contracts")
if ENGINE_REF_DIR not in sys.path:
    sys.path.insert(0, ENGINE_REF_DIR)
if CONTRACTS_DIR not in sys.path:
    sys.path.insert(0, CONTRACTS_DIR)

from nte_engine_ref import (  # noqa: E402
    Engine as ReferenceEngine,
    PipeClient,
    ProtocolError,
    load_mandatory_capabilities,
    parse_args as parse_reference_args,
    probe_shared_memory,
    qpc_ns,
)
from models import (  # noqa: E402
    FRAME_HEADER_SIZE,
    FRAME_HEADER_MAGIC,
    FRAME_HEADER_VERSION,
    MAP_TOTAL_SIZE_BYTES,
    SLOT_COUNT,
    FrameHeaderV1,
    verify_frame_metadata_match,
)


FILE_MAP_READ = 0x0004
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
KERNEL32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
KERNEL32.OpenFileMappingW.restype = ctypes.c_void_p
KERNEL32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                   ctypes.c_uint32, ctypes.c_size_t]
KERNEL32.MapViewOfFile.restype = ctypes.c_void_p
KERNEL32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
KERNEL32.UnmapViewOfFile.restype = ctypes.c_int
KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]
KERNEL32.CloseHandle.restype = ctypes.c_int


def corner_checksum(bgra: bytes, width: int, height: int, stride: int) -> int:
    last_x = (width - 1) * 4
    last_y = (height - 1) * stride
    total = 0
    for offset in (0, last_x, last_y, last_y + last_x):
        total += sum(bgra[offset:offset + 4])
    return total & 0xFFFFFFFF


class ReadOnlyFrameMap:
    def __init__(self, map_name: str, declared_size: int):
        if declared_size != MAP_TOTAL_SIZE_BYTES:
            raise ProtocolError(
                "ERR_RING_GEOMETRY_MISMATCH",
                f"declared MMF size {declared_size} != fixed v1 {MAP_TOTAL_SIZE_BYTES}",
            )
        self.map_name = map_name
        self.handle = KERNEL32.OpenFileMappingW(FILE_MAP_READ, 0, map_name)
        if not self.handle or self.handle == INVALID_HANDLE_VALUE:
            raise ProtocolError(
                "ERR_BUFFER_UNAVAILABLE",
                f"OpenFileMappingW failed for {map_name}; win32={ctypes.get_last_error()}",
            )
        self.view = KERNEL32.MapViewOfFile(
            self.handle, FILE_MAP_READ, 0, 0, MAP_TOTAL_SIZE_BYTES
        )
        if not self.view:
            error = ctypes.get_last_error()
            KERNEL32.CloseHandle(self.handle)
            self.handle = None
            raise ProtocolError("ERR_BUFFER_UNAVAILABLE", f"MapViewOfFile failed; win32={error}")

    def read(self, buffer_index: int, buffer_length: int) -> tuple[bytes, bytes]:
        if not (0 <= buffer_index < SLOT_COUNT):
            raise ProtocolError("ERR_SLOT_INDEX_OUT_OF_BOUNDS", f"bufferIndex={buffer_index}")
        if buffer_length < 0 or buffer_length > MAP_TOTAL_SIZE_BYTES:
            raise ProtocolError("ERR_FRAME_CAPACITY_EXCEEDED", f"bufferLength={buffer_length}")
        slot_offset = buffer_index * 8294464
        base = self.view + slot_offset
        header = ctypes.string_at(base, FRAME_HEADER_SIZE)
        pixels = ctypes.string_at(base + FRAME_HEADER_SIZE, buffer_length)
        return header, pixels

    def close(self) -> None:
        if getattr(self, "view", None):
            KERNEL32.UnmapViewOfFile(self.view)
            self.view = None
        if getattr(self, "handle", None):
            KERNEL32.CloseHandle(self.handle)
            self.handle = None


class FrameProbeEngine(ReferenceEngine):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.frame_map: ReadOnlyFrameMap | None = None
        self.frame_records: list[dict[str, Any]] = []
        self.read_count = 0

    def write_frame_evidence(self) -> None:
        path = os.path.join(self.work_dir, "engine_frame_probe.json")
        result = {
            "schemaVersion": "v2.3.engine-frame-probe.v1",
            "mapName": self.map_name,
            "declaredSize": self.frame_buffer_size,
            "readOnly": True,
            "readCount": self.read_count,
            "frames": self.frame_records,
            "contentValid": bool(self.frame_records)
            and all(row.get("contentValid") is True for row in self.frame_records),
        }
        os.makedirs(self.work_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)

    def handle_frame_ready(self, envelope: dict[str, Any]) -> None:
        payload = envelope.get("payload") or {}
        record: dict[str, Any] = {
            "frameReadyPayload": payload,
            "contentValid": False,
            "metadataMatch": False,
            "checksumMatch": False,
            "nonZero": False,
        }
        buffer_index = int(payload.get("bufferIndex", -1))
        sequence = int(payload.get("sequence", -1))
        status = "CORRUPTED"
        try:
            if self.frame_map is None:
                self.frame_map = ReadOnlyFrameMap(self.map_name, self.frame_buffer_size)
            header_bytes, pixels = self.frame_map.read(
                buffer_index, int(payload.get("bufferLength", -1))
            )
            header = FrameHeaderV1.unpack(header_bytes)
            record["header"] = asdict(header)
            verify_frame_metadata_match(payload, header, expected_buffer_index=buffer_index)
            record["metadataMatch"] = True
            expected_checksum = corner_checksum(
                pixels, header.width, header.height, header.stride
            )
            record["computedCornerChecksum"] = expected_checksum
            record["checksumMatch"] = expected_checksum == header.cornerChecksum
            record["nonZero"] = any(pixels)
            record["pixelSha256"] = hashlib.sha256(pixels).hexdigest()
            record["pixelBytesRead"] = len(pixels)
            record["contentValid"] = (
                header.magic == FRAME_HEADER_MAGIC
                and header.headerVersion == FRAME_HEADER_VERSION
                and header.bufferLength == len(pixels)
                and record["metadataMatch"]
                and record["checksumMatch"]
                and record["nonZero"]
            )
            status = "CONSUMED" if record["contentValid"] else "CORRUPTED"
            self.read_count += 1
        except Exception as exc:  # retain exact first failure in the evidence
            record["errorType"] = type(exc).__name__
            record["error"] = str(exc)

        record["frameReadyPayload"] = payload
        self.frame_records.append(record)
        self.write_frame_evidence()

        self.send(
            "FRAME_ACK",
            {
                "sessionId": self.session_id,
                "bufferIndex": buffer_index,
                "sequence": sequence,
                "status": status,
            },
            "frame-ack",
            correlation_id=envelope.get("requestId"),
        )
        # This is a transport-only response required by the existing Host method;
        # it deliberately contains no OCR/recognition result.
        self.send(
            "PERCEPTION_RESULT",
            {
                "frameSequence": sequence,
                "scene": "TRANSPORT_ONLY",
                "inAuction": False,
                "bids": [],
                "processingMs": 0.0,
            },
            "transport-result",
            correlation_id=envelope.get("requestId"),
        )

    def run(self) -> int:
        self.log(
            "engine.start",
            pipeName=self.pipe_name,
            mapName=self.map_name,
            frameBufferSize=self.frame_buffer_size,
            pid=os.getpid(),
        )
        self.pipe = PipeClient(self.pipe_name)
        self.log("pipe.connected")
        self.mmf_probe = probe_shared_memory(self.map_name, self.frame_buffer_size)
        with open(os.path.join(self.work_dir, "engine_mmf_probe.json"), "w", encoding="utf-8") as fh:
            json.dump(self.mmf_probe, fh, indent=2)
        self.log("engine.read_loop_entering")
        while True:
            envelope = self.pipe.recv()
            if envelope is None:
                self.log("pipe.eof")
                return 0
            message_type = envelope.get("messageType")
            self.log(
                "recv",
                messageType=message_type,
                sequence=envelope.get("sequence"),
                requestId=envelope.get("requestId"),
            )
            if message_type == "HELLO":
                self.handle_hello(envelope)
            elif message_type == "FRAME_READY":
                self.handle_frame_ready(envelope)
            elif message_type == "ENGINE_SHUTDOWN":
                self.write_frame_evidence()
                self.log("shutdown.requested")
                return 0
            elif message_type == "HEARTBEAT":
                if self.heartbeat_enabled:
                    self.send(
                        "HEARTBEAT",
                        {"timestamp": qpc_ns(), "state": "HEALTHY", "activeMatchId": None},
                        "hb",
                        correlation_id=envelope.get("requestId"),
                    )
            else:
                self.send_error(
                    "ERR_UNKNOWN_MESSAGE_TYPE",
                    "PROTOCOL",
                    f"unsupported messageType {message_type}",
                    False,
                )


def main(argv: list[str]) -> int:
    args = parse_reference_args(argv)
    engine = FrameProbeEngine(args)
    try:
        return engine.run()
    except ProtocolError as exc:
        engine.log("engine.protocol_error", errorCode=exc.error_code, message=str(exc))
        try:
            engine.send_error(exc.error_code, "TRANSPORT", str(exc), True)
        except Exception:
            pass
        return 9
    except KeyboardInterrupt:
        return 0
    finally:
        engine.write_frame_evidence()
        if engine.frame_map is not None:
            engine.frame_map.close()
        if engine.pipe:
            engine.pipe.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
