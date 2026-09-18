#!/usr/bin/env python3
"""V2-1 reference (mock) Intelligence Engine.

This is NOT the production engine. It implements exactly enough of protocol 1.0.0
to let the Native Host supervisor be exercised for real:

  * Windows Named Pipe CLIENT on the pipe name the Host hands over in argv
  * the frozen 4-byte little-endian uint32 length prefix + UTF-8 JSON framing
  * exact HELLO validation (fixed-v1 geometry + mandatory capabilities)
  * HELLO_ACK with the readiness / engineBusinessReady contract
  * HEARTBEAT, STATE_SNAPSHOT_REQUEST -> STATE_SNAPSHOT, COMMAND -> COMMAND_RESULT
  * fail-closed ERROR emission before exiting on a protocol violation
  * a crash marker written in the shared WINDOWS_QPC_NANOSECONDS domain

It opens the Host's fixed-v1 shared memory read-only and records whether the OS
denies a writable view, but it NEVER writes a frame header, a pixel or a
FRAME_READY message. There is no stdio protocol path here either: stdout/stderr
are logs only.

Standard library only. No third-party imports.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import time
from ctypes import wintypes

# --------------------------------------------------------------------------- #
# Win32
# --------------------------------------------------------------------------- #

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

FILE_MAP_READ = 0x0004
FILE_MAP_WRITE = 0x0002
ERROR_ACCESS_DENIED = 5
ERROR_PIPE_BUSY = 231
ERROR_FILE_NOT_FOUND = 2

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
k32.ReadFile.restype = wintypes.BOOL
k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
k32.WriteFile.restype = wintypes.BOOL
k32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
k32.CloseHandle.restype = wintypes.BOOL
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.OpenFileMappingW.restype = wintypes.HANDLE
k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
k32.UnmapViewOfFile.restype = wintypes.BOOL
k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]


class ProtocolError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(f"[{error_code}] {message}")
        self.error_code = error_code


def qpc_ns() -> int:
    """Same WINDOWS_QPC_NANOSECONDS domain the .NET Host uses."""
    return time.perf_counter_ns()


# --------------------------------------------------------------------------- #
# Named Pipe client
# --------------------------------------------------------------------------- #

class PipeClient:
    def __init__(self, pipe_name: str, connect_timeout_ms: int = 10000):
        self.pipe_name = pipe_name
        self.handle = None
        deadline = time.monotonic() + connect_timeout_ms / 1000.0
        last_err = 0
        while time.monotonic() < deadline:
            handle = k32.CreateFileW(
                pipe_name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None
            )
            if handle not in (None, 0, INVALID_HANDLE_VALUE):
                self.handle = handle
                return
            last_err = ctypes.get_last_error()
            time.sleep(0.02)
        raise ProtocolError("ERR_PIPE_DISCONNECTED", f"could not connect to {pipe_name} (win32 error {last_err})")

    def send_raw(self, payload: bytes) -> None:
        framed = struct.pack("<I", len(payload)) + payload
        written = wintypes.DWORD(0)
        buf = ctypes.create_string_buffer(framed, len(framed))
        ok = k32.WriteFile(self.handle, ctypes.cast(buf, ctypes.c_void_p), len(framed),
                           ctypes.byref(written), None)
        if not ok:
            raise ProtocolError("ERR_PIPE_BROKEN", f"WriteFile failed with win32 error {ctypes.get_last_error()}")

    def send(self, envelope: dict) -> None:
        self.send_raw(json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    def _read_exact(self, count: int) -> bytes | None:
        chunks = []
        remaining = count
        while remaining > 0:
            buf = ctypes.create_string_buffer(remaining)
            read = wintypes.DWORD(0)
            ok = k32.ReadFile(self.handle, ctypes.cast(buf, ctypes.c_void_p), remaining,
                              ctypes.byref(read), None)
            if not ok:
                err = ctypes.get_last_error()
                if err in (109, 232):  # ERROR_BROKEN_PIPE / ERROR_NO_DATA
                    return None
                raise ProtocolError("ERR_PIPE_BROKEN", f"ReadFile failed with win32 error {err}")
            if read.value == 0:
                return None
            chunks.append(buf.raw[: read.value])
            remaining -= read.value
        return b"".join(chunks)

    def recv(self) -> dict | None:
        prefix = self._read_exact(4)
        if prefix is None:
            return None
        (length,) = struct.unpack("<I", prefix)
        if length > 1048576:
            raise ProtocolError("ERR_MESSAGE_TOO_LARGE", f"declared length {length} exceeds 1048576")
        body = self._read_exact(length)
        if body is None:
            raise ProtocolError("ERR_INCOMPLETE_FRAME", f"stream ended inside a {length}-byte payload")
        return json.loads(body.decode("utf-8"))

    def close(self) -> None:
        if self.handle not in (None, 0, INVALID_HANDLE_VALUE):
            k32.CloseHandle(self.handle)
            self.handle = None


# --------------------------------------------------------------------------- #
# Shared memory probe (read-only, no writes)
# --------------------------------------------------------------------------- #

def probe_shared_memory(map_name: str, declared_size: int) -> dict:
    """Opens the Host's mapping read-only and records whether a writable view is
    denied by the OS. Never writes any byte of the mapping."""
    result = {
        "mapName": map_name,
        "declaredSize": declared_size,
        "openMode": "FILE_MAP_READ (0x0004)",
        "openSucceeded": False,
        "openErrorCode": 0,
        "readViewMapped": False,
        "readViewErrorCode": 0,
        "writeViewDenied": False,
        "writeViewErrorCode": 0,
        "writeDenialStatus": "NOT_MEASURED",
        "firstBytesAllZero": None,
        "frameHeadersWritten": 0,
        "frameReadyMessagesSent": 0,
    }

    handle = k32.OpenFileMappingW(FILE_MAP_READ, False, map_name)
    if handle in (None, 0, INVALID_HANDLE_VALUE):
        result["openErrorCode"] = ctypes.get_last_error()
        return result
    result["openSucceeded"] = True

    try:
        view = k32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 64)
        if view:
            result["readViewMapped"] = True
            head = ctypes.string_at(view, 64)
            result["firstBytesAllZero"] = all(b == 0 for b in head)
            k32.UnmapViewOfFile(view)
        else:
            result["readViewErrorCode"] = ctypes.get_last_error()

        # A handle opened with FILE_MAP_READ must not be able to obtain a writable
        # view. This is the OS-level write-denial assertion.
        write_view = k32.MapViewOfFile(handle, FILE_MAP_WRITE, 0, 0, 0)
        if write_view:
            result["writeViewDenied"] = False
            k32.UnmapViewOfFile(write_view)
            result["writeDenialStatus"] = "NOT_DENIED"
        else:
            err = ctypes.get_last_error()
            result["writeViewDenied"] = True
            result["writeViewErrorCode"] = err
            result["writeDenialStatus"] = "PASS_OS_DENIED" if err == ERROR_ACCESS_DENIED else f"NOT_MEASURED(err={err})"
    finally:
        k32.CloseHandle(handle)

    return result


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #

def find_contracts_dir() -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.abspath(os.path.join(here, "..", "..", "contracts"))
    if os.path.isfile(os.path.join(candidate, "capability_negotiation_v1.json")):
        return candidate
    return None


def load_mandatory_capabilities() -> list[str]:
    contracts = find_contracts_dir()
    if not contracts:
        return ["BitBlt", "SharedMemoryRing", "NamedPipeIpc", "LowLevelHooks"]
    with open(os.path.join(contracts, "capability_negotiation_v1.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    return [c["name"] for c in data["capabilities"] if c.get("isMandatory")]


class Engine:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.session_id = args.session_id
        self.nonce = args.nonce
        self.pipe_name = args.pipe_name
        self.map_name = args.frame_buffer_name
        self.frame_buffer_size = args.frame_buffer_size
        self.work_dir = args.work_dir
        self.generation_id = args.generation_id
        self.log_path = args.log
        self.fault = args.fault or ""
        self.fault_missing_capability = args.fault_missing_mandatory_capability
        self.fault_hello_size = args.fault_hello_size

        self.sequence = 0
        self.pipe: PipeClient | None = None
        self.heartbeat_enabled = True
        self.wrong_session_snapshot = False
        self.linger_ms = 1200
        self.request_counter = 0
        self.hello_seen = False
        self.session_nonce_used = self.nonce
        self.mmf_probe: dict | None = None

    # -- logging ---------------------------------------------------------- #
    def log(self, event: str, **details) -> None:
        record = {
            "tsNs": qpc_ns(),
            "event": event,
            "sessionId": self.session_id,
            "sessionNonceShort": self.nonce[:8],
            "generationId": self.generation_id,
            "details": details,
        }
        line = json.dumps(record, ensure_ascii=False)
        print(line, file=sys.stderr, flush=True)
        if self.log_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.log_path)), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def next_sequence(self) -> int:
        """Sequence counters are scoped PER_SENDER_PER_CONNECTION_GENERATION and are
        reset on every new handshake. This engine deliberately starts at 0 so that
        the wire itself proves a replacement generation's sequence 0 is accepted
        rather than rejected by the previous generation's high-water mark."""
        value = self.sequence
        self.sequence += 1
        return value

    def next_request_id(self, prefix: str) -> str:
        self.request_counter += 1
        return f"{prefix}-{self.request_counter:04d}"

    # -- envelopes -------------------------------------------------------- #
    def envelope(self, message_type: str, payload: dict, request_id: str, correlation_id: str | None) -> dict:
        return {
            "protocolVersion": "1.0.0",
            "sessionId": self.session_id,
            "messageType": message_type,
            "requestId": request_id,
            "correlationId": correlation_id,
            "sequence": self.next_sequence(),
            "monotonicTimestampNs": qpc_ns(),
            "payload": payload,
        }

    def send(self, message_type: str, payload: dict, prefix: str, correlation_id: str | None = None) -> dict:
        request_id = self.next_request_id(prefix)
        envelope = self.envelope(message_type, payload, request_id, correlation_id)
        assert self.pipe is not None
        self.pipe.send(envelope)
        self.log("send", messageType=message_type, sequence=envelope["sequence"], requestId=request_id)
        return envelope

    def send_error(self, error_code: str, category: str, message: str, is_fatal: bool) -> None:
        try:
            self.send("ERROR", {
                "errorCode": error_code,
                "category": category,
                "message": message,
                "isFatal": is_fatal,
            }, "err")
        except Exception:  # the peer may already be gone
            pass

    # -- HELLO ------------------------------------------------------------ #
    def handle_hello(self, envelope: dict) -> None:
        payload = envelope.get("payload") or {}
        self.hello_seen = True

        if envelope.get("sessionId") != self.session_id:
            self.send_error("ERR_STALE_SESSION", "PROTOCOL", "HELLO sessionId mismatch", True)
            raise SystemExit(4)

        expected_size = self.frame_buffer_size

        declared = payload.get("frameBufferSize")
        if not isinstance(declared, int) or isinstance(declared, bool):
            self.send_error("ERR_RING_GEOMETRY_MISMATCH", "PROTOCOL",
                            "HELLO frameBufferSize must be an integer", True)
            raise SystemExit(5)
        if declared != expected_size:
            self.send_error(
                "ERR_RING_GEOMETRY_MISMATCH", "PROTOCOL",
                f"HELLO frameBufferSize={declared} does not equal the fixed v1 mapTotalSizeBytes {expected_size}; "
                "v1 ring geometry is NOT negotiated",
                True,
            )
            raise SystemExit(5)

        if payload.get("sessionNonce") != self.nonce:
            self.send_error("ERR_STALE_GENERATION", "PROTOCOL", "HELLO sessionNonce mismatch", True)
            raise SystemExit(6)

        capabilities = payload.get("capabilities") or {}
        mandatory = load_mandatory_capabilities()
        unavailable = [name for name in mandatory if capabilities.get(name) != "AVAILABLE"]

        if self.fault_missing_capability:
            unavailable.append(self.fault_missing_capability)

        if unavailable:
            self.send("HELLO_ACK", {
                "engineVersion": "1.0.0-v2-1-ref",
                "negotiatedProtocol": "1.0.0",
                "status": "REJECTED_CAPABILITY",
                "readiness": "STARTING",
                "enginePid": os.getpid(),
                "engineBusinessReady": False,
            }, "ack")
            self.log("hello.rejected_capability", unavailable=unavailable)
            return

        # Mandatory capabilities are AVAILABLE. NOT_MEASURED / EXPERIMENTAL
        # capabilities are advertised by the Host but never activated here.
        self.send("HELLO_ACK", {
            "engineVersion": "1.0.0-v2-1-ref",
            "negotiatedProtocol": "1.0.0",
            "status": "ACCEPTED",
            "readiness": "READY",
            "enginePid": os.getpid(),
            "engineBusinessReady": True,
        }, "ack", correlation_id=envelope.get("requestId"))
        self.log("hello.accepted", enginePid=os.getpid())

    # -- runtime handlers -------------------------------------------------- #
    def handle_state_snapshot_request(self, envelope: dict) -> None:
        session_for_snapshot = "wrong-session-000" if self.wrong_session_snapshot else self.session_id
        self.wrong_session_snapshot = False
        payload = {
            "snapshotSchemaVersion": "1.0.0",
            "snapshotSessionId": session_for_snapshot,
            "snapshotSequence": 10,
            "businessReady": True,
            "currentMatchProjection": {
                "matchId": "match-mock-0001",
                "matchState": "IN_PROGRESS",
                "auctionPhase": "BIDDING",
                "draftCount": 0,
                "finalizedCount": 14,
                "activeAuctionItems": [42],
                "bids": [{"seat": 2, "price": 200000}],
            },
        }
        self.send("STATE_SNAPSHOT", payload, "ss", correlation_id=envelope.get("requestId"))

    def handle_command(self, envelope: dict) -> None:
        payload = envelope.get("payload") or {}
        command_id = payload.get("commandId", "")
        action = payload.get("action", "")

        if action == "test.simulate_crash":
            self.write_crash_marker()
            self.log("crash.simulated", commandId=command_id)
            sys.stderr.flush()
            os._exit(3)

        if action == "test.close_pipe":
            self.log("pipe.closing_abruptly", commandId=command_id)
            if self.pipe:
                self.pipe.close()
            sys.stderr.flush()
            os._exit(4)

        if action == "test.close_pipe_and_linger":
            # Test-only: close the pipe and stay alive for a while before exiting, so
            # the pipe EOF signal is deterministically observed BEFORE Process.Exited.
            self.send("COMMAND_RESULT", {"commandId": command_id, "status": "ACK"}, "cmdres")
            self.log("pipe.closed_then_lingering", commandId=command_id, lingerMs=self.linger_ms)
            if self.pipe:
                self.pipe.close()
            sys.stderr.flush()
            time.sleep(self.linger_ms / 1000.0)
            os._exit(5)

        if action == "test.stop_heartbeat":
            self.heartbeat_enabled = False

        if action == "test.resume_heartbeat":
            self.heartbeat_enabled = True

        if action == "test.wrong_session_snapshot":
            self.wrong_session_snapshot = True

        if action == "test.graceful_exit":
            self.send("COMMAND_RESULT", {"commandId": command_id, "status": "ACK"}, "cmdres")
            sys.stderr.flush()
            os._exit(0)

        self.send("COMMAND_RESULT", {
            "commandId": command_id,
            "status": "ACK",
            "resultData": {"echo": action},
        }, "cmdres", correlation_id=envelope.get("requestId"))

    def write_crash_marker(self) -> None:
        marker = {
            "crashMarkerNs": qpc_ns(),
            "generationId": self.generation_id,
            "nonceShort": self.nonce[:8],
            "pid": os.getpid(),
        }
        path = os.path.join(self.work_dir, "crash_marker.json")
        os.makedirs(self.work_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(marker, fh)
            fh.flush()
            os.fsync(fh.fileno())
        self.log("crash.marker_written", crashMarkerNs=marker["crashMarkerNs"])

    # -- main loop --------------------------------------------------------- #
    def run(self) -> int:
        pipe_name = self.pipe_name
        if self.fault == "wrong_pipe":
            # Test-only fault: connect to a pipe the Host never created, so the
            # supervisor's fail-closed path can be exercised.
            pipe_name = pipe_name + "_wrong"

        self.log("engine.start", pipeName=pipe_name, mapName=self.map_name,
                 frameBufferSize=self.frame_buffer_size, pid=os.getpid())

        self.pipe = PipeClient(pipe_name)
        self.log("pipe.connected")

        self.mmf_probe = probe_shared_memory(self.map_name, self.frame_buffer_size)
        probe_path = os.path.join(self.work_dir, "engine_mmf_probe.json")
        with open(probe_path, "w", encoding="utf-8") as fh:
            json.dump(self.mmf_probe, fh, indent=2)
        self.log("mmf.probed", **{k: self.mmf_probe[k] for k in (
            "openSucceeded", "readViewMapped", "writeViewDenied", "writeViewErrorCode",
            "writeDenialStatus", "firstBytesAllZero")})

        self.log("engine.read_loop_entering")
        while True:
            envelope = self.pipe.recv()
            if envelope is None:
                self.log("pipe.eof")
                return 0

            message_type = envelope.get("messageType")
            self.log("recv", messageType=message_type, sequence=envelope.get("sequence"),
                     requestId=envelope.get("requestId"))

            if message_type == "HELLO":
                self.handle_hello(envelope)
            elif message_type == "HEARTBEAT":
                if self.heartbeat_enabled:
                    self.send("HEARTBEAT", {
                        "timestamp": time.time(),
                        "state": "HEALTHY",
                        "activeMatchId": "match-mock-0001",
                    }, "hb", correlation_id=envelope.get("requestId"))
            elif message_type == "STATE_SNAPSHOT_REQUEST":
                self.handle_state_snapshot_request(envelope)
            elif message_type == "COMMAND":
                self.handle_command(envelope)
            elif message_type == "ENGINE_SHUTDOWN":
                # Protocol 1.0.0 defines NO shutdown ACK. Exit gracefully.
                self.log("shutdown.requested", reason=(envelope.get("payload") or {}).get("reason"))
                return 0
            elif message_type == "ABORT_SCAN":
                pass
            else:
                self.send_error("ERR_UNKNOWN_MESSAGE_TYPE", "PROTOCOL",
                                f"unsupported messageType {message_type}", False)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="V2-1 reference engine (mock)")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--pipe-name", required=True)
    parser.add_argument("--frame-buffer-name", required=True)
    parser.add_argument("--frame-buffer-size", type=int, required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--generation-id", type=int, default=1)
    parser.add_argument("--log", default=None)
    parser.add_argument("--fault", default=None,
                        help="test-only fault injection: wrong_pipe")
    parser.add_argument("--fault-missing-mandatory-capability", default=None,
                        help="test-only: advertise this mandatory capability as unavailable")
    parser.add_argument("--linger-ms", type=int, default=1200,
                        help="test-only: how long the engine stays alive after closing the pipe")
    parser.add_argument("--fault-hello-size", default=None,
                        help="test-only: recorded for the host-side fault; the engine always "
                             "expects the fixed v1 frameBufferSize handed over in argv")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    engine = Engine(args)
    engine.linger_ms = getattr(args, "linger_ms", 1200)
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
        if engine.pipe:
            engine.pipe.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
