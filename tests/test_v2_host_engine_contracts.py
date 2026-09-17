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
    ENVELOPE_FIELD_TYPES,
    FRAME_HEADER_MAGIC,
    FRAME_HEADER_SIZE,
    FRAME_HEADER_VERSION,
    FRAME_READY_BUFFER_INDEX_FIELD,
    FRAME_READY_HEADER_METADATA_FIELDS,
    MAP_TOTAL_SIZE_BYTES,
    MAX_MESSAGE_BYTES,
    PAYLOAD_FIELD_TYPES,
    PROTOCOL_VERSION,
    REQUIRED_ENVELOPE_FIELDS,
    REQUIRED_PAYLOAD_FIELDS,
    RING_GEOMETRY_POLICY,
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
    get_fixed_v1_geometry,
    get_slot_offset,
    validate_envelope,
    validate_hello_ack_readiness,
    validate_hello_fixed_geometry,
    validate_state_snapshot,
    verify_frame_metadata_match,
    verify_message_allowed_in_state,
)
from architecture.v2.contracts.schema_parity import write_parity_report


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
            "sessionId": "test-session-001",
            "bufferIndex": 0,
            "sequence": 999,  # Mismatch: header has 101
            "width": 1920, "height": 1080, "stride": 7680, "pixelFormat": 1,
            "bufferLength": 8294400, "captureTimestampNs": 1000000000, "cornerChecksum": 0x12345678
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
        tracker = SequenceTracker("session-01", "nonce-01")
        tracker.check_and_update("sender-A", "session-01", "nonce-01", 10)
        tracker.check_and_update("sender-A", "session-01", "nonce-01", 15)

        # Sequence <= 15 is stale
        with self.assertRaises(ContractValidationError) as ctx:
            tracker.check_and_update("sender-A", "session-01", "nonce-01", 14)
        self.assertEqual(ctx.exception.error_code, "ERR_STALE_SEQUENCE")

    def test_22_neg_stale_session_id(self):
        tracker = SequenceTracker("session-01", "nonce-01")
        with self.assertRaises(ContractValidationError) as ctx:
            tracker.check_and_update("sender-A", "session-WRONG", "nonce-01", 1)
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

        # All 14 message vectors
        self.assertEqual(len(golden_data["messageVectors"]), 14)
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
        self.assertGreaterEqual(data["totalTests"], 40)
        # The verifier must read the message catalog itself, not only golden framed hex.
        catalog_tests = [c["name"] for c in data["testCases"] if c["name"].startswith("MessageCatalog_")]
        for required in (
            "MessageCatalog_Count_14",
            "MessageCatalog_GoldenRequiredFields_Parity",
            "MessageCatalog_FrameReady_HeaderMetadata_Parity",
            "MessageCatalog_StateSnapshot_Parity",
        ):
            self.assertIn(required, catalog_tests)

    def test_36_neg_frame_ready_before_handshake(self):
        # FRAME_READY before completing handshake is strictly forbidden
        with self.assertRaises(ContractValidationError) as ctx1:
            verify_message_allowed_in_state(LifecycleState.HANDSHAKING, "FRAME_READY")
        self.assertEqual(ctx1.exception.error_code, "ERR_MESSAGE_BEFORE_HANDSHAKE")

        with self.assertRaises(ContractValidationError) as ctx2:
            verify_message_allowed_in_state(LifecycleState.STARTING, "COMMAND")
        self.assertEqual(ctx2.exception.error_code, "ERR_MESSAGE_BEFORE_HANDSHAKE")

    def test_37_neg_state_snapshot_wrong_session(self):
        snap_env = Envelope(
            protocolVersion="1.0.0", sessionId="active-session-001",
            messageType="STATE_SNAPSHOT", requestId="snap-1", correlationId=None,
            sequence=1, monotonicTimestampNs=1000,
            payload={
                "snapshotSchemaVersion": "1.0.0",
                "snapshotSessionId": "stale-session-999",  # Mismatch with active session
                "snapshotSequence": 1,
                "businessReady": True,
                "currentMatchProjection": {"matchState": "IN_PROGRESS", "draftCount": 0, "finalizedCount": 1}
            }
        )
        with self.assertRaises(ContractValidationError) as ctx:
            validate_state_snapshot(snap_env, "active-session-001")
        self.assertEqual(ctx.exception.error_code, "ERR_STALE_SESSION")

    def test_38_neg_frame_capacity_exceeded(self):
        # 3840x2160 frame into 1080p slot
        huge_header = FrameHeaderV1(
            magic=FRAME_HEADER_MAGIC, headerVersion=1, sequence=1,
            width=3840, height=2160, stride=15360, pixelFormat=1,
            bufferLength=33177600, flags=0, captureTimestampNs=1000,
            producerTimestampNs=2000, cornerChecksum=0, reserved=0
        )
        with self.assertRaises(ContractValidationError) as ctx:
            huge_header.validate()
        self.assertEqual(ctx.exception.error_code, "ERR_FRAME_CAPACITY_EXCEEDED")

    def test_39_pos_sequence_generation_reset_on_new_nonce(self):
        # Generation 1: (sess-1, nonce-1, engine)
        tracker = SequenceTracker("sess-1", "nonce-1")
        tracker.check_and_update("engine", "sess-1", "nonce-1", 10)
        tracker.check_and_update("engine", "sess-1", "nonce-1", 100)

        # Host spawns new Engine child with nonce-2; generation resets
        tracker.reset_generation("sess-1", "nonce-2")
        # New Engine starting at sequence 0 or 1 is ACCEPTED
        tracker.check_and_update("engine", "sess-1", "nonce-2", 0)
        tracker.check_and_update("engine", "sess-1", "nonce-2", 1)

        # Stale packet bearing old nonce-1 arrives
        with self.assertRaises(ContractValidationError) as ctx:
            tracker.check_and_update("engine", "sess-1", "nonce-1", 50)
        self.assertEqual(ctx.exception.error_code, "ERR_STALE_GENERATION")

    def test_40_pos_command_delayed_evaluates_expired(self):
        mgr = CommandIdempotencyManager()
        # Command originally valid with expiresAtNs = 5000, but arrives at receiverNowNs = 6000
        res = mgr.process_command("sess-1", "cmd-late", "DO_VALUATION", {"id": 1}, 5000, 6000)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "EXPIRED")

    # ------------------------------------------------------------------
    # MESSAGE CATALOG SSOT CONSISTENCY (single schema truth enforcement)
    # ------------------------------------------------------------------
    def _load_json(self, filename):
        with open(self.contracts_dir / filename, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _catalog_messages(self):
        catalog = self._load_json("message_catalog_v1.json")
        return catalog, {msg["messageType"]: msg for msg in catalog["messages"]}

    def test_message_catalog_matches_python_models(self):
        """The catalog must be a byte-faithful mirror of models.PAYLOAD_FIELD_TYPES."""
        catalog, catalog_messages = self._catalog_messages()

        self.assertEqual(catalog["totalMessageTypes"], 14)
        self.assertEqual(len(catalog["messages"]), 14)
        self.assertEqual(sorted(catalog_messages), sorted(t.value for t in MessageType))

        for message_type, field_specs in PAYLOAD_FIELD_TYPES.items():
            message = catalog_messages[message_type]
            declared = message["payloadSchema"]["properties"]

            self.assertEqual(message["requiredPayloadFields"], REQUIRED_PAYLOAD_FIELDS[message_type])
            self.assertEqual(declared, field_specs, f"{message_type} payloadSchema drifted from models")
            self.assertFalse(message["payloadSchema"]["additionalProperties"])
            self.assertEqual(
                [name for name, spec in declared.items() if spec["required"]],
                message["requiredPayloadFields"],
                f"{message_type} required flags disagree with requiredPayloadFields",
            )

        # Envelope schema is part of the same single truth.
        self.assertEqual(catalog["envelopeSchema"]["requiredFields"], REQUIRED_ENVELOPE_FIELDS)
        self.assertEqual(catalog["envelopeSchema"]["properties"], ENVELOPE_FIELD_TYPES)

        # Ring geometry is FIXED v1 constants - HELLO declares only name + size.
        geometry = catalog["ringBufferGeometry"]
        self.assertEqual(geometry["policy"], RING_GEOMETRY_POLICY)
        self.assertFalse(geometry["geometryIsNegotiated"])
        self.assertEqual(
            get_fixed_v1_geometry(),
            {
                "slotCount": SLOT_COUNT,
                "slotSizeBytes": SLOT_SIZE_BYTES,
                "mapTotalSizeBytes": MAP_TOTAL_SIZE_BYTES,
            },
        )
        for constant in ("slotCount", "slotSizeBytes", "mapTotalSizeBytes"):
            self.assertNotIn(constant, PAYLOAD_FIELD_TYPES["HELLO"])
            self.assertNotIn(constant, PAYLOAD_FIELD_TYPES["HELLO_ACK"])
        self.assertIn("frameBufferSize", PAYLOAD_FIELD_TYPES["HELLO"])
        self.assertEqual(geometry["mapTotalSizeBytes"], MAP_TOTAL_SIZE_BYTES)

        golden = self._load_json("golden_vectors_v1.json")
        golden_hello = next(v for v in golden["messageVectors"] if v["messageType"] == "HELLO")
        validate_hello_fixed_geometry(golden_hello["envelope"]["payload"])
        with self.assertRaises(ContractValidationError) as ctx:
            validate_hello_fixed_geometry({"frameBufferSize": MAP_TOTAL_SIZE_BYTES + 64})
        self.assertEqual(ctx.exception.error_code, "ERR_RING_GEOMETRY_MISMATCH")

        # Fail-closed error codes declared by the catalog must exist in the error catalog.
        error_catalog = self._load_json("error_catalog_v1.json")
        known = {entry["errorCode"] for entry in error_catalog["errors"]}
        self.assertTrue(set(catalog["failClosedErrorCodes"]).issubset(known))

    def test_all_golden_vectors_satisfy_catalog_schema(self):
        """Every golden vector payload must satisfy the catalog schema for its type."""
        catalog, catalog_messages = self._catalog_messages()
        golden = self._load_json("golden_vectors_v1.json")

        self.assertEqual(len(golden["messageVectors"]), 14)
        self.assertEqual(
            sorted(v["messageType"] for v in golden["messageVectors"]),
            sorted(catalog_messages),
        )

        for vector in golden["messageVectors"]:
            message_type = vector["messageType"]
            envelope = vector["envelope"]
            payload = envelope["payload"]

            # Envelope + payload schema must validate fail-closed.
            validated = validate_envelope(envelope)
            self.assertEqual(validated.messageType, message_type)

            required = catalog_messages[message_type]["requiredPayloadFields"]
            missing = [name for name in required if name not in payload]
            self.assertEqual(missing, [], f"{message_type} golden payload misses catalog required fields")

            declared = set(catalog_messages[message_type]["payloadSchema"]["properties"])
            undeclared = sorted(set(payload) - declared)
            self.assertEqual(undeclared, [], f"{message_type} golden payload has undeclared fields")

            # Required-ness must never be satisfiable by a null value.
            for name in required:
                spec = catalog_messages[message_type]["payloadSchema"]["properties"][name]
                self.assertFalse(spec["nullable"], f"{message_type}.{name} is required but nullable")

    def test_state_snapshot_catalog_matches_resync_validator(self):
        """STATE_SNAPSHOT catalog schema must equal the projection the resync validator enforces."""
        catalog, catalog_messages = self._catalog_messages()
        snapshot = catalog_messages["STATE_SNAPSHOT"]
        properties = snapshot["payloadSchema"]["properties"]
        projection = properties["currentMatchProjection"]

        self.assertEqual(
            snapshot["requiredPayloadFields"],
            ["snapshotSchemaVersion", "snapshotSessionId", "snapshotSequence", "businessReady", "currentMatchProjection"],
        )
        self.assertEqual(projection, PAYLOAD_FIELD_TYPES["STATE_SNAPSHOT"]["currentMatchProjection"])
        self.assertEqual(
            [name for name, spec in projection["properties"].items() if spec["required"]],
            ["matchId", "matchState", "auctionPhase", "draftCount", "finalizedCount", "activeAuctionItems", "bids"],
        )
        self.assertFalse(projection["nullable"])
        self.assertFalse(projection["additionalProperties"])
        # The legacy, conflicting top-level snapshot schema must be gone.
        self.assertNotIn("snapshotSchema", catalog)
        self.assertNotIn("stateSnapshotSchema", catalog)

        golden = self._load_json("golden_vectors_v1.json")
        golden_snapshot = next(v for v in golden["messageVectors"] if v["messageType"] == "STATE_SNAPSHOT")
        session_id = golden_snapshot["envelope"]["sessionId"]
        envelope = Envelope(**golden_snapshot["envelope"])

        # Golden snapshot is accepted by the resync validator.
        validate_state_snapshot(envelope, session_id)

        # Stale session wins over projection schema (fail-closed ordering).
        with self.assertRaises(ContractValidationError) as ctx1:
            validate_state_snapshot(envelope, "stale-session-999")
        self.assertEqual(ctx1.exception.error_code, "ERR_STALE_SESSION")

        # Missing required projection field is rejected.
        broken_projection = dict(golden_snapshot["envelope"]["payload"])
        broken_projection["currentMatchProjection"] = {"matchState": "IN_PROGRESS", "draftCount": 0}
        with self.assertRaises(ContractValidationError) as ctx2:
            validate_state_snapshot(Envelope(**{**golden_snapshot["envelope"], "payload": broken_projection}), session_id)
        self.assertEqual(ctx2.exception.error_code, "ERR_MISSING_REQUIRED_FIELD")

        # Wrong projection value type is rejected without coercion.
        coerced_projection = dict(golden_snapshot["envelope"]["payload"])
        coerced_projection["currentMatchProjection"] = dict(
            golden_snapshot["envelope"]["payload"]["currentMatchProjection"]
        )
        coerced_projection["currentMatchProjection"]["draftCount"] = "0"
        with self.assertRaises(ContractValidationError) as ctx3:
            validate_state_snapshot(Envelope(**{**golden_snapshot["envelope"], "payload": coerced_projection}), session_id)
        self.assertEqual(ctx3.exception.error_code, "ERR_SCHEMA_VALIDATION_FAILED")

    def test_hello_ack_catalog_matches_ready_gate(self):
        """HELLO_ACK readiness must be the single authority behind the lifecycle READY gate."""
        catalog, catalog_messages = self._catalog_messages()
        ack = catalog_messages["HELLO_ACK"]["payloadSchema"]["properties"]

        self.assertIn("readiness", catalog_messages["HELLO_ACK"]["requiredPayloadFields"])
        self.assertIn("engineBusinessReady", catalog_messages["HELLO_ACK"]["requiredPayloadFields"])
        self.assertEqual(ack["readiness"]["type"], "string")
        self.assertEqual(ack["readiness"]["enum"], PAYLOAD_FIELD_TYPES["HELLO_ACK"]["readiness"]["enum"])
        self.assertEqual(ack["engineBusinessReady"]["type"], "boolean")
        self.assertFalse(ack["readiness"]["nullable"])
        self.assertFalse(ack["engineBusinessReady"]["nullable"])

        readiness_contract = catalog["readinessContract"]
        self.assertEqual(readiness_contract["authoritativeField"], "readiness")
        self.assertEqual(readiness_contract["owner"], "HELLO_ACK")
        self.assertEqual(readiness_contract["businessReadyProjection"], "engineBusinessReady")
        self.assertEqual(sorted(readiness_contract["enum"]), sorted(ack["readiness"]["enum"]))

        lifecycle = self._load_json("lifecycle_recovery_v1.json")
        gate_field = lifecycle["readyGateRequirements"]["readinessField"]
        self.assertEqual(sorted(gate_field["enum"]), sorted(ack["readiness"]["enum"]))
        self.assertEqual(gate_field["readyGateValue"], "READY")
        self.assertEqual(gate_field["projectionField"], "engineBusinessReady")
        gates = {gate["gate"]: gate["condition"] for gate in lifecycle["readyGateRequirements"]["gates"]}
        self.assertEqual(len(gates), 4)
        self.assertIn("engineBusinessReady", gates["engineBusinessReady"])

        golden = self._load_json("golden_vectors_v1.json")
        golden_ack = next(v for v in golden["messageVectors"] if v["messageType"] == "HELLO_ACK")["envelope"]["payload"]
        validate_hello_ack_readiness(golden_ack)

        # readiness == READY must imply engineBusinessReady == true
        with self.assertRaises(ContractValidationError) as ctx1:
            validate_hello_ack_readiness({**golden_ack, "engineBusinessReady": False})
        self.assertEqual(ctx1.exception.error_code, "ERR_SCHEMA_VALIDATION_FAILED")

        # readiness in [STARTING, LOADING] must not advertise business readiness
        for early in ("STARTING", "LOADING"):
            with self.assertRaises(ContractValidationError) as ctx2:
                validate_hello_ack_readiness({**golden_ack, "readiness": early, "engineBusinessReady": True})
            self.assertEqual(ctx2.exception.error_code, "ERR_SCHEMA_VALIDATION_FAILED")

        # A rejected handshake must never advertise business readiness
        with self.assertRaises(ContractValidationError) as ctx3:
            validate_hello_ack_readiness({**golden_ack, "status": "REJECTED_VERSION"})
        self.assertEqual(ctx3.exception.error_code, "ERR_SCHEMA_VALIDATION_FAILED")

        # Readiness outside the enum is rejected
        with self.assertRaises(ContractValidationError) as ctx4:
            validate_hello_ack_readiness({**golden_ack, "readiness": "BUSINESS_READY"})
        self.assertEqual(ctx4.exception.error_code, "ERR_SCHEMA_VALIDATION_FAILED")

        # No second field may express engine readiness: modelStatus is not a protocol field.
        declared_field_names = set(ENVELOPE_FIELD_TYPES)
        for message_type, fields in PAYLOAD_FIELD_TYPES.items():
            self.assertNotIn("modelStatus", fields, f"{message_type} must not declare modelStatus")
            declared_field_names |= set(fields)
        for message in catalog["messages"]:
            self.assertNotIn("modelStatus", message["payloadSchema"]["properties"])
        self.assertNotIn("modelStatus", declared_field_names)
        # ... and the catalog must say so explicitly rather than leave it ambiguous.
        self.assertIn("modelStatus", readiness_contract["modelStatusNote"])

    def test_frame_ready_catalog_matches_header_metadata(self):
        """FRAME_READY must declare exactly what verify_frame_metadata_match() checks."""
        catalog, catalog_messages = self._catalog_messages()
        frame_ready = catalog_messages["FRAME_READY"]
        properties = frame_ready["payloadSchema"]["properties"]

        expected_checked = [FRAME_READY_BUFFER_INDEX_FIELD] + [
            payload_field for payload_field, _ in FRAME_READY_HEADER_METADATA_FIELDS
        ]
        self.assertEqual(catalog["frameHeaderMetadataContract"]["checkedFields"], expected_checked)
        self.assertEqual(
            frame_ready["requiredPayloadFields"],
            REQUIRED_PAYLOAD_FIELDS["FRAME_READY"],
        )
        for name in expected_checked:
            self.assertIn(name, frame_ready["requiredPayloadFields"])
            self.assertIn(name, properties)

        # Naming / typing rules that the reviewer flagged as blockers.
        self.assertIn("cornerChecksum", properties)
        self.assertNotIn("checksum", properties)
        self.assertEqual(properties["pixelFormat"]["type"], "integer")
        self.assertEqual(properties["pixelFormat"]["enum"], [1])
        self.assertEqual(properties["cornerChecksum"]["type"], "integer")
        # Header field names must match payload field names one-to-one.
        for payload_field, header_attr in FRAME_READY_HEADER_METADATA_FIELDS:
            self.assertEqual(payload_field, header_attr)
            self.assertIn(payload_field, properties)
        header_fields = set(FrameHeaderV1.__dataclass_fields__)
        for payload_field, _ in FRAME_READY_HEADER_METADATA_FIELDS:
            self.assertIn(payload_field, header_fields)

        # Behavioural parity: a golden-consistent payload passes, every mutation fails.
        golden = self._load_json("golden_vectors_v1.json")
        payload = next(v for v in golden["messageVectors"] if v["messageType"] == "FRAME_READY")["envelope"]["payload"]
        header = FrameHeaderV1(
            magic=FRAME_HEADER_MAGIC, headerVersion=FRAME_HEADER_VERSION, sequence=payload["sequence"],
            width=payload["width"], height=payload["height"], stride=payload["stride"],
            pixelFormat=payload["pixelFormat"], bufferLength=payload["bufferLength"], flags=0,
            captureTimestampNs=payload["captureTimestampNs"], producerTimestampNs=0,
            cornerChecksum=payload["cornerChecksum"], reserved=0,
        )
        verify_frame_metadata_match(payload, header, expected_buffer_index=payload["bufferIndex"])

        for field_name in expected_checked:
            mutated = dict(payload)
            if field_name == FRAME_READY_BUFFER_INDEX_FIELD:
                mutated[field_name] = payload[field_name] + 1
            else:
                mutated[field_name] = payload[field_name] + 1
            with self.assertRaises(ContractValidationError) as ctx:
                verify_frame_metadata_match(mutated, header, expected_buffer_index=payload["bufferIndex"])
            self.assertEqual(
                ctx.exception.error_code,
                "ERR_FRAME_METADATA_MISMATCH",
                f"mutation of '{field_name}' was not detected as a metadata mismatch",
            )

        # bufferIndex bounds are enforced even without an expected slot.
        with self.assertRaises(ContractValidationError) as ctx_bounds:
            verify_frame_metadata_match({**payload, "bufferIndex": SLOT_COUNT}, header)
        self.assertEqual(ctx_bounds.exception.error_code, "ERR_SLOT_INDEX_OUT_OF_BOUNDS")

        # A correct payload read from the wrong slot is rejected.
        with self.assertRaises(ContractValidationError) as ctx_slot:
            verify_frame_metadata_match(payload, header, expected_buffer_index=1)
        self.assertEqual(ctx_slot.exception.error_code, "ERR_FRAME_METADATA_MISMATCH")

    def test_message_schema_parity_report_is_generated_and_green(self):
        """message_schema_parity.json is machine-generated and must be fully green."""
        report = write_parity_report(self.contracts_dir)

        report_path = self.contracts_dir / "message_schema_parity.json"
        self.assertTrue(report_path.exists(), "message_schema_parity.json must be generated")
        with open(report_path, "r", encoding="utf-8") as handle:
            on_disk = json.load(handle)

        self.assertEqual(on_disk, report)
        self.assertEqual(on_disk["totalMessages"], 14)
        for key in (
            "catalogModelParity",
            "catalogEnvelopeParity",
            "catalogGoldenParity",
            "catalogLifecycleParity",
            "catalogFrameMetadataParity",
            "catalogStateSnapshotParity",
            "catalogGeometryParity",
            "catalogErrorCodeParity",
            "allPassed",
        ):
            self.assertTrue(on_disk[key], f"{key} must be true, failures={on_disk['failures']}")
        self.assertEqual(on_disk["passedChecks"], on_disk["totalChecks"])
        self.assertEqual(on_disk["failures"], [])


if __name__ == "__main__":
    unittest.main()
