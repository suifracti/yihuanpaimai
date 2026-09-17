"""
tests/test_v2_host_engine_contracts.py

Targeted unit tests for NTE Architecture V2 Host-Engine IPC Protocol Contracts:
- Schema specifications validation
- 64-byte FrameHeader binary struct packing, unpacking, offsets, and fail-closed guards
- Envelope structure, validation, and fail-closed policies
- 4-byte binary framing with maxMessageBytes guard
- Lifecycle state machine transition guards
- Golden test vectors parity verification
- Cross-language C# parity artifact verification
"""

import json
import os
import struct
import unittest
from pathlib import Path

from architecture.v2.contracts.models import (
    FRAME_HEADER_MAGIC,
    FRAME_HEADER_SIZE,
    FRAME_HEADER_VERSION,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    ContractValidationError,
    DropCounters,
    Envelope,
    FrameHeaderV1,
    LifecycleState,
    LifecycleStateMachine,
    MessageType,
    decode_framed_message,
    encode_framed_message,
    validate_envelope,
)


class TestV2HostEngineContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts_dir = Path(__file__).resolve().parent.parent / "architecture" / "v2" / "contracts"
        cls.assertTrue(cls.contracts_dir.exists(), f"Contracts dir {cls.contracts_dir} must exist")

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

    def test_03_capability_negotiation_unmeasured_and_experimental_guards(self):
        cap_path = self.contracts_dir / "capability_negotiation_v1.json"
        with open(cap_path, "r", encoding="utf-8") as f:
            cap_data = json.load(f)
        caps = {c["name"]: c for c in cap_data["capabilities"]}
        
        # WGC must be NOT_MEASURED
        self.assertIn("WGC", caps)
        self.assertEqual(caps["WGC"]["status"], "NOT_MEASURED")
        
        # WebView2 must be EXPERIMENTAL
        self.assertIn("WebView2", caps)
        self.assertEqual(caps["WebView2"]["status"], "EXPERIMENTAL")
        
        # BitBlt, SharedMemoryRing, NamedPipeIpc, LowLevelHooks must be AVAILABLE
        self.assertEqual(caps["BitBlt"]["status"], "AVAILABLE")
        self.assertEqual(caps["SharedMemoryRing"]["status"], "AVAILABLE")
        self.assertEqual(caps["NamedPipeIpc"]["status"], "AVAILABLE")
        self.assertEqual(caps["LowLevelHooks"]["status"], "AVAILABLE")
        
        # SendInput must be UNAVAILABLE
        self.assertEqual(caps["SendInput"]["status"], "UNAVAILABLE")

    def test_04_low_level_hooks_timeout_distinction(self):
        proto_path = self.contracts_dir / "protocol_v1.json"
        with open(proto_path, "r", encoding="utf-8") as f:
            proto = json.load(f)
        timeouts = proto["timeouts"]
        self.assertEqual(timeouts["registryConfiguredLowLevelHooksTimeoutMs"], 25000)
        self.assertEqual(timeouts["effectiveLowLevelHooksTimeoutMs"], 1000)
        self.assertEqual(timeouts["syntheticInternalDispatchMicrobenchUs"], 45)
        self.assertEqual(timeouts["realOsCallbackLatencyStatus"], "NOT_MEASURED")

    def test_05_frame_header_struct_size_and_field_offsets(self):
        layout_path = self.contracts_dir / "frame_buffer_layout_v1.json"
        with open(layout_path, "r", encoding="utf-8") as f:
            layout = json.load(f)
        
        expected_fields = layout["headerStructure"]["fields"]
        self.assertEqual(layout["headerStructure"]["totalSizeBytes"], 64)
        self.assertEqual(FRAME_HEADER_SIZE, 64)

        # Verify field by field byte offset against Python struct calculation
        field_fmt_map = {
            "magic": "I",
            "headerVersion": "i",
            "sequence": "q",
            "width": "i",
            "height": "i",
            "stride": "i",
            "pixelFormat": "i",
            "bufferLength": "i",
            "flags": "i",
            "captureTimestampNs": "q",
            "producerTimestampNs": "q",
            "cornerChecksum": "I",
            "reserved": "i",
        }
        cur_offset = 0
        for field_info in expected_fields:
            fname = field_info["name"]
            expected_offset = field_info["offset"]
            self.assertEqual(cur_offset, expected_offset, f"Field {fname} offset mismatch")
            fmt = field_fmt_map[fname]
            sz = struct.calcsize("<" + fmt)
            self.assertEqual(sz, field_info["size"], f"Field {fname} size mismatch")
            cur_offset += sz
        self.assertEqual(cur_offset, 64)

    def test_06_frame_header_pack_unpack_roundtrip(self):
        header = FrameHeaderV1(
            magic=FRAME_HEADER_MAGIC,
            headerVersion=1,
            sequence=42,
            width=1920,
            height=1080,
            stride=7680,
            pixelFormat=1,
            bufferLength=8294400,
            flags=1,
            captureTimestampNs=1234567890,
            producerTimestampNs=1234570000,
            cornerChecksum=0xDEADBEEF,
            reserved=0,
        )
        packed = header.pack()
        self.assertEqual(len(packed), 64)

        unpacked = FrameHeaderV1.unpack(packed)
        self.assertEqual(unpacked.magic, FRAME_HEADER_MAGIC)
        self.assertEqual(unpacked.headerVersion, 1)
        self.assertEqual(unpacked.sequence, 42)
        self.assertEqual(unpacked.width, 1920)
        self.assertEqual(unpacked.height, 1080)
        self.assertEqual(unpacked.stride, 7680)
        self.assertEqual(unpacked.pixelFormat, 1)
        self.assertEqual(unpacked.bufferLength, 8294400)
        self.assertEqual(unpacked.flags, 1)
        self.assertEqual(unpacked.captureTimestampNs, 1234567890)
        self.assertEqual(unpacked.producerTimestampNs, 1234570000)
        self.assertEqual(unpacked.cornerChecksum, 0xDEADBEEF)
        self.assertEqual(unpacked.reserved, 0)

    def test_07_frame_header_fail_closed_on_corrupt_magic_or_version(self):
        # Corrupt magic
        bad_magic_bytes = struct.pack(
            "<IiqiiiiiiqqIi",
            0x11223344, 1, 0, 1920, 1080, 7680, 1, 8294400, 0, 0, 0, 0, 0
        )
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(bad_magic_bytes)
        self.assertEqual(ctx.exception.error_code, "ERR_CORRUPT_FRAME_MAGIC")

        # Corrupt version
        bad_version_bytes = struct.pack(
            "<IiqiiiiiiqqIi",
            FRAME_HEADER_MAGIC, 99, 0, 1920, 1080, 7680, 1, 8294400, 0, 0, 0, 0, 0
        )
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(bad_version_bytes)
        self.assertEqual(ctx.exception.error_code, "ERR_PROTOCOL_VERSION_MISMATCH")

        # Corrupt pixel format
        bad_fmt_bytes = struct.pack(
            "<IiqiiiiiiqqIi",
            FRAME_HEADER_MAGIC, 1, 0, 1920, 1080, 7680, 99, 8294400, 0, 0, 0, 0, 0
        )
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(bad_fmt_bytes)
        self.assertEqual(ctx.exception.error_code, "ERR_UNSUPPORTED_PIXEL_FORMAT")

        # Truncated buffer
        with self.assertRaises(ContractValidationError) as ctx:
            FrameHeaderV1.unpack(b"\x00" * 32)
        self.assertEqual(ctx.exception.error_code, "ERR_FRAME_PAYLOAD_TOO_SHORT")

    def test_08_envelope_validation_success_and_fail_closed(self):
        valid_dict = {
            "protocolVersion": "1.0.0",
            "sessionId": "sess-test",
            "messageType": "HEARTBEAT",
            "requestId": "req-1",
            "correlationId": None,
            "sequence": 1,
            "monotonicTimestampNs": 1000,
            "payload": {
                "timestamp": 123456.0,
                "state": "HEALTHY",
            },
        }
        env = validate_envelope(valid_dict)
        self.assertEqual(env.messageType, "HEARTBEAT")
        self.assertEqual(env.sequence, 1)

        # Missing envelope field
        bad_dict = dict(valid_dict)
        del bad_dict["sessionId"]
        with self.assertRaises(ContractValidationError) as ctx:
            validate_envelope(bad_dict)
        self.assertEqual(ctx.exception.error_code, "ERR_MALFORMED_ENVELOPE")

        # Wrong protocol version
        bad_ver = dict(valid_dict, protocolVersion="2.0.0")
        with self.assertRaises(ContractValidationError) as ctx:
            validate_envelope(bad_ver)
        self.assertEqual(ctx.exception.error_code, "ERR_PROTOCOL_VERSION_MISMATCH")

        # Unknown message type
        bad_type = dict(valid_dict, messageType="UNKNOWN_FOO")
        with self.assertRaises(ContractValidationError) as ctx:
            validate_envelope(bad_type)
        self.assertEqual(ctx.exception.error_code, "ERR_UNKNOWN_MESSAGE_TYPE")

        # Missing required payload field (HEARTBEAT requires 'timestamp' and 'state')
        bad_payload = dict(valid_dict, payload={"timestamp": 12345.0})
        with self.assertRaises(ContractValidationError) as ctx:
            validate_envelope(bad_payload)
        self.assertEqual(ctx.exception.error_code, "ERR_MISSING_REQUIRED_FIELD")

    def test_09_binary_framing_encode_decode_and_guard(self):
        env = Envelope(
            protocolVersion="1.0.0",
            sessionId="s-001",
            messageType="ABORT_SCAN",
            requestId="r-001",
            correlationId=None,
            sequence=10,
            monotonicTimestampNs=5000,
            payload={"reason": "USER_TAKEOVER", "triggerTimestampNs": 5000},
        )
        framed = encode_framed_message(env)
        self.assertGreater(len(framed), 4)
        
        # Verify length prefix
        payload_len = struct.unpack_from("<I", framed, 0)[0]
        self.assertEqual(payload_len, len(framed) - 4)

        # Decode
        decoded, consumed = decode_framed_message(framed)
        self.assertEqual(consumed, len(framed))
        self.assertEqual(decoded.messageType, "ABORT_SCAN")
        self.assertEqual(decoded.payload["reason"], "USER_TAKEOVER")

        # Oversized message guard
        huge_fake_prefix = struct.pack("<I", MAX_MESSAGE_BYTES + 100) + b"\x00" * 10
        with self.assertRaises(ContractValidationError) as ctx:
            decode_framed_message(huge_fake_prefix)
        self.assertEqual(ctx.exception.error_code, "ERR_MESSAGE_TOO_LARGE")

    def test_10_lifecycle_state_machine_transitions(self):
        sm = LifecycleStateMachine(LifecycleState.ENGINE_DOWN)
        self.assertEqual(sm.current_state, LifecycleState.ENGINE_DOWN)

        # Valid forward cycle
        sm.transition_to(LifecycleState.STARTING)
        sm.transition_to(LifecycleState.HANDSHAKING)
        sm.transition_to(LifecycleState.SYNCING)
        sm.transition_to(LifecycleState.READY)
        sm.transition_to(LifecycleState.DEGRADED)
        sm.transition_to(LifecycleState.READY)
        sm.transition_to(LifecycleState.ENGINE_DOWN)

        # Invalid transition: ENGINE_DOWN directly to READY
        with self.assertRaises(ContractValidationError) as ctx:
            sm.transition_to(LifecycleState.READY)
        self.assertEqual(ctx.exception.error_code, "ERR_AUTHORITY_VIOLATION")

    def test_11_golden_vectors_verification(self):
        golden_path = self.contracts_dir / "golden_vectors_v1.json"
        self.assertTrue(golden_path.exists())
        with open(golden_path, "r", encoding="utf-8") as f:
            golden_data = json.load(f)

        # 1. Verify frame header vector
        h_vec = golden_data["frameHeaderVector"]
        expected_h_hex = h_vec["packedHex"]
        test_h = FrameHeaderV1(
            magic=0x4246544E,
            headerVersion=1,
            sequence=101,
            width=1920,
            height=1080,
            stride=7680,
            pixelFormat=1,
            bufferLength=8294400,
            flags=1,
            captureTimestampNs=1000000000,
            producerTimestampNs=1003200000,
            cornerChecksum=0x12345678,
            reserved=0,
        )
        self.assertEqual(test_h.pack().hex().lower(), expected_h_hex.lower())

        # 2. Verify all message vectors
        vectors = golden_data["messageVectors"]
        self.assertGreaterEqual(len(vectors), 11)
        for vec in vectors:
            name = vec["name"]
            raw_env = vec["envelope"]
            env = validate_envelope(raw_env)
            self.assertEqual(env.messageType, vec["messageType"])
            
            framed = encode_framed_message(env)
            self.assertEqual(len(framed) - 4, vec["lengthPrefixBytes"], f"Length prefix mismatch in {name}")
            self.assertEqual(framed.hex().lower(), vec["expectedFramedHex"].lower(), f"Framed hex mismatch in {name}")

    def test_12_cross_language_parity_artifacts_pass(self):
        layout_parity_path = self.contracts_dir / "frame_layout_parity.json"
        self.assertTrue(layout_parity_path.exists(), "frame_layout_parity.json must exist")
        with open(layout_parity_path, "r", encoding="utf-8") as f:
            layout_parity = json.load(f)
        self.assertTrue(layout_parity["allOffsetsEqual"], "All frame header offsets between C# and spec must match")
        self.assertTrue(layout_parity["headerSizeEqual"], "Frame header size in C# must be 64 bytes")
        self.assertEqual(layout_parity["headerSizeBytes"], 64)

        cross_parity_path = self.contracts_dir / "cross_language_parity.json"
        self.assertTrue(cross_parity_path.exists(), "cross_language_parity.json must exist")
        with open(cross_parity_path, "r", encoding="utf-8") as f:
            cross_parity = json.load(f)
        self.assertTrue(cross_parity["allVectorsPass"], "All golden vectors must pass cross-language C# verification")
        self.assertTrue(cross_parity["headerPackingParity"], "FrameHeader packing parity must pass in C#")
        self.assertEqual(cross_parity["totalVectorsTested"], 11)


if __name__ == "__main__":
    unittest.main()
