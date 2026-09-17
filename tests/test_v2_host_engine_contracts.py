"""
tests/test_v2_host_engine_contracts.py

Comprehensive targeted unit tests for NTE Architecture V2 Host-Engine IPC Protocol Contracts:
- Ring buffer geometry & slot offset formulas
- 64-byte FrameHeader binary struct layout, offsets, and fail-closed integrity
- Strict fail-closed envelope validation (no type coercion, UUID non-empty string, int64 >= 0)
- Metadata synchronization between FRAME_READY and shared memory FrameHeaderV1
- Monotonic sequence tracking per sender per session (stale sequence detection)
- Command deduplication and idempotency keying ((sessionId, commandId), reuse mismatch, replay)
- Slot lock and release token ownership semantics (no forced overwrite on timeout)
- Lifecycle recovery state machine & READY gate requirements (reconnect mandatory SYNCING)
- Reproducible cross-language parity execution with .NET ContractVerifier
- 19+ machine-executed fail-closed negative test cases
"""

import json
import os
import struct
import subprocess
import unittest
from pathlib import Path

from architecture.v2.contracts.models import (
    FRAME_HEADER_MAGIC,
    FRAME_HEADER_SIZE,
    FRAME_HEADER_VERSION,
    MAP_TOTAL_SIZE_BYTES,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    SLOT_COUNT,
    SLOT_PAYLOAD_CAPACITY_BYTES,
    SLOT_SIZE_BYTES,
    CommandIdempotencyManager,
    ContractValidationError,
    DropCounters,
    Envelope,
    FrameHeaderV1,
    LifecycleState,
    LifecycleStateMachine,
    MessageType,
    RingBufferSlotManager,
    SequenceTracker,
    SlotState,
    decode_framed_message,
    encode_framed_message,
    get_slot_offset,
    validate_envelope,
    verify_frame_metadata_match,
)


class TestV2HostEngineContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts_dir = Path(__file__).resolve().parent.parent / "architecture" / "v2" / "contracts"
        cls.verifier_dir = Path(__file__).resolve().parent.parent / "architecture" / "v2" / "verifier"
        cls.assertTrue(cls.contracts_dir.exists(), f"Contracts dir {cls.contracts_dir} must exist")
        cls.assertTrue(cls.verifier_dir.exists(), f"Verifier dir {cls.verifier_dir} must exist")

    def test_01_specification_schemas_exist_and_valid_json(self):
        spec_files = [
            "protocol_v1.json",
            "message_catalog_v1.json",
            "frame_buffer_layout_v1.json",
            "authority_ownership_v1.json",
            "lifecycle_recovery_v1.json",
            "error_catalog_v1.json",
            "capability_negotiation_v1.json",
            "security_boundary_v1.json",
            "compatibility_policy_v1.md",
        ]
        for fname in spec_files:
            fpath = self.contracts_dir / fname
            self.assertTrue(fpath.exists(), f"Specification file {fname} must exist")
            if fname.endswith(".json"):
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.assertIn("protocolVersion", data)
                    self.assertEqual(data["protocolVersion"], "1.0.0")

    def test_02_message_catalog_declares_14_messages(self):
        catalog_path = self.contracts_dir / "message_catalog_v1.json"
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        self.assertEqual(catalog["totalMessageTypes"], 14)
        msg_names = {m["messageType"] for m in catalog["messages"]}
        self.assertEqual(len(msg_names), 14)
        enum_names = {t.value for t in MessageType}
        self.assertEqual(msg_names, enum_names)

    def test_03_capability_negotiation_guards(self):
        cap_path = self.contracts_dir / "capability_negotiation_v1.json"
        with open(cap_path, "r", encoding="utf-8") as f:
            cap_data = json.load(f)
        caps = {c["name"]: c for c in cap_data["capabilities"]}
        self.assertEqual(caps["WGC"]["status"], "NOT_MEASURED")
        self.assertEqual(caps["WebView2"]["status"], "EXPERIMENTAL")
        self.assertEqual(caps["SendInput"]["status"], "UNAVAILABLE")
        self.assertEqual(caps["BitBlt"]["status"], "AVAILABLE")
        self.assertEqual(caps["SharedMemoryRing"]["status"], "AVAILABLE")
        self.assertEqual(caps["NamedPipeIpc"]["status"], "AVAILABLE")

    def test_04_low_level_hooks_timeout_and_abort_latency(self):
        proto_path = self.contracts_dir / "protocol_v1.json"
        with open(proto_path, "r", encoding="utf-8") as f:
            proto = json.load(f)
        timeouts = proto["timeouts"]
        self.assertEqual(timeouts["registryConfiguredLowLevelHooksTimeoutMs"], 25000)
        self.assertEqual(timeouts["effectiveLowLevelHooksTimeoutMs"], 1000)
        self.assertEqual(timeouts["syntheticInternalDispatchMicrobenchUs"], 45)
        self.assertEqual(timeouts["realOsCallbackLatencyStatus"], "NOT_MEASURED")
        self.assertEqual(timeouts["targetAbortLatencyMs"], 1)
        self.assertEqual(timeouts["abortValidationStatus"], "NOT_MEASURED")

    def test_05_ring_buffer_geometry_constants_and_offsets(self):
        self.assertEqual(SLOT_COUNT, 4)
        self.assertEqual(SLOT_PAYLOAD_CAPACITY_BYTES, 8294400)
        self.assertEqual(SLOT_SIZE_BYTES, 8294464)
        self.assertEqual(MAP_TOTAL_SIZE_BYTES, 33177856)

        # Formula: slotOffset(index) = index * slotSizeBytes
        for i in range(4):
            self.assertEqual(get_slot_offset(i), i * SLOT_SIZE_BYTES)

        # Out of bounds raises ERR_SLOT_INDEX_OUT_OF_BOUNDS
        with self.assertRaises(ContractValidationError) as ctx1:
            get_slot_offset(-1)
        self.assertEqual(ctx1.exception.error_code, "ERR_SLOT_INDEX_OUT_OF_BOUNDS")

        with self.assertRaises(ContractValidationError) as ctx2:
            get_slot_offset(4)
        self.assertEqual(ctx2.exception.error_code, "ERR_SLOT_INDEX_OUT_OF_BOUNDS")

    def test_06_frame_header_struct_offsets_and_sizes(self):
        layout_path = self.contracts_dir / "frame_buffer_layout_v1.json"
        with open(layout_path, "r", encoding="utf-8") as f:
            layout = json.load(f)
        fields = layout["headerStructure"]["fields"]
        self.assertEqual(layout["headerStructure"]["totalSizeBytes"], 64)
        self.assertEqual(FRAME_HEADER_SIZE, 64)

        field_fmt = {
            "magic": "I", "headerVersion": "i", "sequence": "q",
            "width": "i", "height": "i", "stride": "i", "pixelFormat": "i",
            "bufferLength": "i", "flags": "i", "captureTimestampNs": "q",
            "producerTimestampNs": "q", "cornerChecksum": "I", "reserved": "i"
        }
        offset = 0
        for f in fields:
            self.assertEqual(offset, f["offset"])
            sz = struct.calcsize("<" + field_fmt[f["name"]])
            self.assertEqual(sz, f["size"])
            offset += sz
        self.assertEqual(offset, 64)

    def test_07_frame_header_pack_unpack_roundtrip(self):
        header = FrameHeaderV1(
            magic=FRAME_HEADER_MAGIC,
            headerVersion=1,
            sequence=100,
            width=1920,
            height=1080,
            stride=7680,
            pixelFormat=1,
            bufferLength=8294400,
            flags=1,
            captureTimestampNs=1000000000,
            producerTimestampNs=1003200000,
            cornerChecksum=0x12345678,
            reserved=0
        )
        packed = header.pack()
        self.assertEqual(len(packed), 64)
        unpacked = FrameHeaderV1.unpack(packed)
        self.assertEqual(unpacked.sequence, 100)
        self.assertEqual(unpacked.cornerChecksum, 0x12345678)

    # Negative Tests
    def test_08_neg_invalid_magic(self):
        bad = struct.pack("<IiqiiiiiiqqIi", 0xDEADBEEF, 1, 0, 1920, 1080, 7680, 1, 8294400, 0, 0, 0, 0, 0)
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(bad)
        self.assertEqual(ctx.exception.error_code, "ERR_CORRUPT_FRAME_MAGIC")

    def test_09_neg_invalid_header_version(self):
        bad = struct.pack("<IiqiiiiiiqqIi", FRAME_HEADER_MAGIC, 2, 0, 1920, 1080, 7680, 1, 8294400, 0, 0, 0, 0, 0)
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(bad)
        self.assertEqual(ctx.exception.error_code, "ERR_PROTOCOL_VERSION_MISMATCH")

    def test_10_neg_invalid_pixel_format(self):
        bad = struct.pack("<IiqiiiiiiqqIi", FRAME_HEADER_MAGIC, 1, 0, 1920, 1080, 7680, 99, 8294400, 0, 0, 0, 0, 0)
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(bad)
        self.assertEqual(ctx.exception.error_code, "ERR_UNSUPPORTED_PIXEL_FORMAT")

    def test_11_neg_stride_mismatch(self):
        # stride != width * 4 (e.g. width=1920, stride=5000)
        bad = struct.pack("<IiqiiiiiiqqIi", FRAME_HEADER_MAGIC, 1, 0, 1920, 1080, 5000, 1, 8294400, 0, 0, 0, 0, 0)
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(bad)
        self.assertEqual(ctx.exception.error_code, "ERR_FRAME_METADATA_MISMATCH")

    def test_12_neg_buffer_length_mismatch(self):
        # bufferLength != stride * height
        bad = struct.pack("<IiqiiiiiiqqIi", FRAME_HEADER_MAGIC, 1, 0, 1920, 1080, 7680, 1, 10000, 0, 0, 0, 0, 0)
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(bad)
        self.assertEqual(ctx.exception.error_code, "ERR_FRAME_METADATA_MISMATCH")

    def test_13_neg_frame_payload_too_short(self):
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(b"\x00" * 63)
        self.assertEqual(ctx.exception.error_code, "ERR_FRAME_PAYLOAD_TOO_SHORT")

    def test_14_neg_frame_metadata_header_mismatch(self):
        header = FrameHeaderV1(
            magic=FRAME_HEADER_MAGIC, headerVersion=1, sequence=101,
            width=1920, height=1080, stride=7680, pixelFormat=1,
            bufferLength=8294400, flags=0, captureTimestampNs=1000000000,
            producerTimestampNs=1003200000, cornerChecksum=0x12345678, reserved=0
        )
        # Mismatched sequence in payload
        mismatched_payload = {
            "sequence": 999,  # Mismatch: header has 101
            "width": 1920, "height": 1080, "stride": 7680, "pixelFormat": 1,
            "bufferLength": 8294400, "captureTimestampNs": 1000000000, "checksum": 0x12345678
        }
        with self.assertRaises(ContractValidationError) as ctx:
            verify_frame_metadata_match(mismatched_payload, header)
        self.assertEqual(ctx.exception.error_code, "ERR_FRAME_METADATA_MISMATCH")

    def test_15_neg_wrong_protocol_version(self):
        bad_env = {
            "protocolVersion": "1.1.0",  # Exact match 1.0.0 required
            "sessionId": "test-session", "messageType": "HEARTBEAT", "requestId": "req-1",
            "correlationId": None, "sequence": 1, "monotonicTimestampNs": 100,
            "payload": {"timestamp": 1.0, "state": "HEALTHY"}
        }
        with self.assertRaises(ContractValidationError) as ctx:
            validate_envelope(bad_env)
        self.assertEqual(ctx.exception.error_code, "ERR_PROTOCOL_VERSION_MISMATCH")

    def test_16_neg_unknown_message_type(self):
        bad_env = {
            "protocolVersion": "1.0.0", "sessionId": "test-session",
            "messageType": "SUPER_INVENTED_MESSAGE", "requestId": "req-1",
            "correlationId": None, "sequence": 1, "monotonicTimestampNs": 100,
            "payload": {}
        }
        with self.assertRaises(ContractValidationError) as ctx:
            validate_envelope(bad_env)
        self.assertEqual(ctx.exception.error_code, "ERR_UNKNOWN_MESSAGE_TYPE")

    def test_17_neg_malformed_envelope_and_no_coercion(self):
        base_env = {
            "protocolVersion": "1.0.0", "sessionId": "s-1", "messageType": "HEARTBEAT",
            "requestId": "req-1", "correlationId": None, "sequence": 1,
            "monotonicTimestampNs": 100, "payload": {"timestamp": 1.0, "state": "HEALTHY"}
        }
        # Missing sessionId
        bad1 = dict(base_env)
        del bad1["sessionId"]
        with self.assertRaises(ContractValidationError) as ctx1:
            validate_envelope(bad1)
        self.assertEqual(ctx1.exception.error_code, "ERR_MALFORMED_ENVELOPE")

        # Empty string sessionId
        bad2 = dict(base_env, sessionId="   ")
        with self.assertRaises(ContractValidationError) as ctx2:
            validate_envelope(bad2)
        self.assertEqual(ctx2.exception.error_code, "ERR_MALFORMED_ENVELOPE")

        # Boolean passed as sequence (Python bool is subclass of int; coercion prohibited)
        bad3 = dict(base_env, sequence=True)
        with self.assertRaises(ContractValidationError) as ctx3:
            validate_envelope(bad3)
        self.assertEqual(ctx3.exception.error_code, "ERR_MALFORMED_ENVELOPE")

        # Negative sequence
        bad4 = dict(base_env, sequence=-5)
        with self.assertRaises(ContractValidationError) as ctx4:
            validate_envelope(bad4)
        self.assertEqual(ctx4.exception.error_code, "ERR_MALFORMED_ENVELOPE")

    def test_18_neg_missing_required_payload_field(self):
        env_dict = {
            "protocolVersion": "1.0.0", "sessionId": "s-1", "messageType": "HEARTBEAT",
            "requestId": "req-1", "correlationId": None, "sequence": 1,
            "monotonicTimestampNs": 100, "payload": {"timestamp": 123.0}  # Missing 'state'
        }
        with self.assertRaises(ContractValidationError) as ctx:
            validate_envelope(env_dict)
        self.assertEqual(ctx.exception.error_code, "ERR_MISSING_REQUIRED_FIELD")

    def test_19_neg_oversized_payload(self):
        bad_buffer = struct.pack("<I", MAX_MESSAGE_BYTES + 50) + b"\x00" * 10
        with self.assertRaises(ContractValidationError) as ctx:
            decode_framed_message(bad_buffer)
        self.assertEqual(ctx.exception.error_code, "ERR_MESSAGE_TOO_LARGE")

    def test_20_neg_incomplete_frame(self):
        # Less than 4 bytes
        with self.assertRaises(ContractValidationError) as ctx1:
            decode_framed_message(b"\x01\x00")
        self.assertEqual(ctx1.exception.error_code, "ERR_INCOMPLETE_FRAME")

        # Prefix says 100 bytes, only 10 provided
        short_buf = struct.pack("<I", 100) + b"\x00" * 10
        with self.assertRaises(ContractValidationError) as ctx2:
            decode_framed_message(short_buf)
        self.assertEqual(ctx2.exception.error_code, "ERR_INCOMPLETE_FRAME")

    def test_21_neg_stale_sequence(self):
        tracker = SequenceTracker("session-01")
        tracker.check_and_update("sender-A", "session-01", 10)
        tracker.check_and_update("sender-A", "session-01", 15)

        # Sequence <= 15 is stale
        with self.assertRaises(ContractValidationError) as ctx:
            tracker.check_and_update("sender-A", "session-01", 14)
        self.assertEqual(ctx.exception.error_code, "ERR_STALE_SEQUENCE")

    def test_22_neg_stale_session_id(self):
        tracker = SequenceTracker("session-01")
        with self.assertRaises(ContractValidationError) as ctx:
            tracker.check_and_update("sender-A", "session-WRONG", 1)
        self.assertEqual(ctx.exception.error_code, "ERR_STALE_SESSION")

    def test_23_neg_duplicate_command(self):
        mgr = CommandIdempotencyManager()
        mgr.process_command("sess-1", "cmd-100", "REFRESH", {"itemId": 1}, 2000, 1000)
        # Re-sending before stored result raises ERR_DUPLICATE_COMMAND
        with self.assertRaises(ContractValidationError) as ctx:
            mgr.process_command("sess-1", "cmd-100", "REFRESH", {"itemId": 1}, 2000, 1000)
        self.assertEqual(ctx.exception.error_code, "ERR_DUPLICATE_COMMAND")

    def test_24_neg_same_command_different_payload(self):
        mgr = CommandIdempotencyManager()
        mgr.process_command("sess-1", "cmd-100", "REFRESH", {"itemId": 1}, 2000, 1000)
        # Same commandId with differing parameters
        with self.assertRaises(ContractValidationError) as ctx:
            mgr.process_command("sess-1", "cmd-100", "REFRESH", {"itemId": 999}, 2000, 1000)
        self.assertEqual(ctx.exception.error_code, "ERR_COMMAND_ID_REUSE_MISMATCH")

    def test_25_pos_command_idempotency_replay(self):
        mgr = CommandIdempotencyManager()
        res = mgr.process_command("sess-1", "cmd-100", "REFRESH", {"itemId": 1}, 2000, 1000)
        self.assertIsNone(res)
        cached_result = {"status": "ACK", "value": 42}
        mgr.store_result("sess-1", "cmd-100", cached_result)

        # Replay returns cached result
        replay = mgr.process_command("sess-1", "cmd-100", "REFRESH", {"itemId": 1}, 2000, 1000)
        self.assertEqual(replay, cached_result)

        # Expired command returns status EXPIRED
        expired = mgr.process_command("sess-1", "cmd-200", "REFRESH", {"itemId": 2}, 500, 1000)
        self.assertEqual(expired["status"], "EXPIRED")

    def test_26_neg_ack_wrong_buffer_index(self):
        mgr = RingBufferSlotManager()
        with self.assertRaises(ContractValidationError) as ctx:
            mgr.release_slot(99, "sess-1", 100)
        self.assertEqual(ctx.exception.error_code, "ERR_SLOT_INDEX_OUT_OF_BOUNDS")

    def test_27_neg_ack_slot_not_locked(self):
        mgr = RingBufferSlotManager()
        # Slot 0 is in state FREE
        with self.assertRaises(ContractValidationError) as ctx:
            mgr.release_slot(0, "sess-1", 100)
        self.assertEqual(ctx.exception.error_code, "ERR_SLOT_NOT_LOCKED")

    def test_28_neg_ack_unknown_frame(self):
        mgr = RingBufferSlotManager()
        slot = mgr.allocate_write_slot()
        mgr.commit_frame(slot, "sess-1", 100)

        # ACK with sequence 999 instead of 100
        with self.assertRaises(ContractValidationError) as ctx:
            mgr.release_slot(slot, "sess-1", 999)
        self.assertEqual(ctx.exception.error_code, "ERR_UNKNOWN_FRAME_ACK")

    def test_29_pos_ring_buffer_slot_lifecycle(self):
        mgr = RingBufferSlotManager(slot_count=4)
        slot0 = mgr.allocate_write_slot()
        self.assertEqual(slot0, 0)
        self.assertEqual(mgr.get_slot_state(0), SlotState.WRITING)

        mgr.commit_frame(slot0, "sess-1", 101)
        self.assertEqual(mgr.get_slot_state(0), SlotState.CONSUMER_LOCKED)

        mgr.release_slot(slot0, "sess-1", 101)
        self.assertEqual(mgr.get_slot_state(0), SlotState.FREE)

    def test_30_neg_lifecycle_invalid_state_transition(self):
        sm = LifecycleStateMachine(LifecycleState.ENGINE_DOWN)
        # ENGINE_DOWN -> READY is completely invalid
        with self.assertRaises(ContractValidationError) as ctx:
            sm.transition_to(LifecycleState.READY)
        self.assertEqual(ctx.exception.error_code, "ERR_INVALID_STATE_TRANSITION")

    def test_31_neg_lifecycle_reconnect_skipping_sync(self):
        # Non-cold-boot (reconnect / recovery)
        sm = LifecycleStateMachine(LifecycleState.ENGINE_DOWN, is_cold_boot=False)
        sm.transition_to(LifecycleState.STARTING)
        sm.transition_to(LifecycleState.HANDSHAKING)
        sm.engine_business_ready = True

        # Reconnect skipping SYNCING is strictly forbidden
        with self.assertRaises(ContractValidationError) as ctx:
            sm.transition_to(LifecycleState.READY)
        self.assertEqual(ctx.exception.error_code, "ERR_INVALID_STATE_TRANSITION")

    def test_32_neg_lifecycle_ready_before_resync(self):
        sm = LifecycleStateMachine(LifecycleState.ENGINE_DOWN, is_cold_boot=False)
        sm.transition_to(LifecycleState.STARTING)
        sm.transition_to(LifecycleState.HANDSHAKING)
        sm.transition_to(LifecycleState.SYNCING)
        # snapshot_resynced is False
        with self.assertRaises(ContractValidationError) as ctx:
            sm.transition_to(LifecycleState.READY)
        self.assertEqual(ctx.exception.error_code, "ERR_INVALID_STATE_TRANSITION")

    def test_33_pos_lifecycle_cold_boot_and_sync_recovery(self):
        # 1. Cold boot direct to READY (cold boot + engine_business_ready)
        sm_cold = LifecycleStateMachine(LifecycleState.ENGINE_DOWN, is_cold_boot=True)
        sm_cold.engine_business_ready = True
        sm_cold.transition_to(LifecycleState.STARTING)
        sm_cold.transition_to(LifecycleState.HANDSHAKING)
        sm_cold.transition_to(LifecycleState.READY)
        self.assertEqual(sm_cold.current_state, LifecycleState.READY)

        # 2. Crash and reconnect through SYNCING
        sm_cold.transition_to(LifecycleState.ENGINE_DOWN)
        self.assertFalse(sm_cold.is_cold_boot)
        sm_cold.transition_to(LifecycleState.STARTING)
        sm_cold.transition_to(LifecycleState.HANDSHAKING)
        sm_cold.transition_to(LifecycleState.SYNCING)
        sm_cold.snapshot_resynced = True
        sm_cold.engine_business_ready = True
        sm_cold.transition_to(LifecycleState.READY)
        self.assertEqual(sm_cold.current_state, LifecycleState.READY)

    def test_34_golden_vectors_exact_match(self):
        golden_path = self.contracts_dir / "golden_vectors_v1.json"
        self.assertTrue(golden_path.exists())
        with open(golden_path, "r", encoding="utf-8") as f:
            golden_data = json.load(f)

        # Frame header packed hex
        h_vec = golden_data["frameHeaderVector"]
        h = FrameHeaderV1(
            magic=0x4246544E, headerVersion=1, sequence=101, width=1920, height=1080,
            stride=7680, pixelFormat=1, bufferLength=8294400, flags=1,
            captureTimestampNs=1000000000, producerTimestampNs=1003200000,
            cornerChecksum=0x12345678, reserved=0
        )
        self.assertEqual(h.pack().hex().lower(), h_vec["packedHex"].lower())

        # All 11 message vectors
        for vec in golden_data["messageVectors"]:
            env = validate_envelope(vec["envelope"])
            self.assertEqual(env.messageType, vec["messageType"])
            framed = encode_framed_message(env)
            self.assertEqual(len(framed) - 4, vec["lengthPrefixBytes"])
            self.assertEqual(framed.hex().lower(), vec["expectedFramedHex"].lower())

    def test_35_reproducible_dotnet_contract_verifier(self):
        csproj = self.verifier_dir / "ContractVerifier.csproj"
        self.assertTrue(csproj.exists(), f"{csproj} must exist")

        # Run the standalone verifier executable via dotnet run
        cmd = ["dotnet", "run", "--project", str(csproj), "--", str(self.contracts_dir), str(self.contracts_dir)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"ContractVerifier execution failed:\n{proc.stdout}\n{proc.stderr}")

        # Verify output artifacts
        results_file = self.contracts_dir / "dotnet_contract_results.json"
        self.assertTrue(results_file.exists())
        with open(results_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertTrue(data["allPassed"])
        self.assertEqual(data["totalTests"], data["passedTests"])
        self.assertGreaterEqual(data["totalTests"], 30)


if __name__ == "__main__":
    unittest.main()
