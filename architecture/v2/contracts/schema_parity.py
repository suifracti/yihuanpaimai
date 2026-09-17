"""
architecture/v2/contracts/schema_parity.py

Machine-generated cross-artifact schema parity report for the V2-0 Host-Engine
IPC contract surface.  This module exists so that the message catalog can never
silently drift away from the Python models, the golden vectors, the lifecycle
READY gate, the fixed v1 ring geometry or the error catalog again.

Single source of truth:
  architecture/v2/contracts/models.py

Mirrors that are verified against it on every contract test run:
  message_catalog_v1.json   (schema surface)
  golden_vectors_v1.json    (wire surface)
  protocol_v1.json          (envelope + geometry surface)
  lifecycle_recovery_v1.json(READY gate surface)
  error_catalog_v1.json     (fail-closed error-code surface)
  frame_buffer_layout_v1.json (geometry surface)

Output: message_schema_parity.json (regenerated, never hand-edited).

Run standalone:  python architecture/v2/contracts/schema_parity.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from architecture.v2.contracts.models import (
    ENVELOPE_FIELD_TYPES,
    Envelope,
    FRAME_READY_BUFFER_INDEX_FIELD,
    FRAME_READY_HEADER_METADATA_FIELDS,
    MAP_TOTAL_SIZE_BYTES,
    MAX_FRAME_HEIGHT,
    MAX_FRAME_WIDTH,
    MessageType,
    PAYLOAD_FIELD_TYPES,
    PROTOCOL_VERSION,
    REQUIRED_ENVELOPE_FIELDS,
    REQUIRED_PAYLOAD_FIELDS,
    SLOT_ALIGNMENT_BYTES,
    SLOT_COUNT,
    SLOT_PAYLOAD_CAPACITY_BYTES,
    SLOT_SIZE_BYTES,
    validate_envelope,
    validate_hello_ack_readiness,
    validate_state_snapshot,
)

PARITY_SCHEMA_VERSION = "message.schema.parity.v1"
_SPEC_KEYS = ("type", "required", "nullable", "enum", "items", "properties", "additionalProperties")


def _canon(spec: Any) -> Any:
    """Canonicalizes a field descriptor so two representations compare structurally."""
    if isinstance(spec, dict):
        out: Dict[str, Any] = {}
        for key in _SPEC_KEYS:
            if key in spec:
                out[key] = _canon(spec[key])
        for key in spec:
            if key not in out:
                out[key] = _canon(spec[key])
        return out
    if isinstance(spec, list):
        return [_canon(item) for item in spec]
    return spec


class ParityChecks:
    """Collects pass/fail results without raising, so a report is always produced."""

    def __init__(self) -> None:
        self.checks: List[Dict[str, Any]] = []

    def record(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append({"check": name, "passed": bool(passed), "detail": detail})
        return bool(passed)

    def equal(self, name: str, actual: Any, expected: Any) -> bool:
        passed = actual == expected
        detail = "identical" if passed else f"actual={actual!r} expected={expected!r}"
        return self.record(name, passed, detail)

    @property
    def all_passed(self) -> bool:
        return all(check["passed"] for check in self.checks)

    def failures(self) -> List[Dict[str, Any]]:
        return [check for check in self.checks if not check["passed"]]


def _load(contracts_dir: Path, filename: str) -> Dict[str, Any]:
    with open(contracts_dir / filename, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_parity_report(contracts_dir: Path) -> Dict[str, Any]:
    """Builds the parity report dict. Never raises on parity failure."""
    contracts_dir = Path(contracts_dir)
    checks = ParityChecks()

    catalog = _load(contracts_dir, "message_catalog_v1.json")
    golden = _load(contracts_dir, "golden_vectors_v1.json")
    protocol = _load(contracts_dir, "protocol_v1.json")
    lifecycle = _load(contracts_dir, "lifecycle_recovery_v1.json")
    error_catalog = _load(contracts_dir, "error_catalog_v1.json")
    frame_layout = _load(contracts_dir, "frame_buffer_layout_v1.json")
    models_source = (contracts_dir / "models.py").read_text(encoding="utf-8")

    catalog_messages = {msg["messageType"]: msg for msg in catalog.get("messages", [])}
    python_types = {t.value for t in MessageType}

    # ---------------------------------------------------------------- count ----
    checks.equal("catalogTotalMessageTypes", catalog.get("totalMessageTypes"), 14)
    checks.equal("catalogMessageCount", len(catalog.get("messages", [])), 14)
    checks.equal("catalogMessageTypeSet", sorted(catalog_messages), sorted(python_types))
    checks.equal("goldenVectorCount", len(golden.get("messageVectors", [])), 14)
    checks.equal("catalogProtocolVersion", catalog.get("protocolVersion"), PROTOCOL_VERSION)

    # -------------------------------------------------- catalog <-> models ----
    for message_type in sorted(python_types):
        message = catalog_messages.get(message_type)
        if message is None:
            checks.record(f"catalogModelParity::{message_type}", False, "message missing from catalog")
            continue
        checks.equal(
            f"catalogModelParity::{message_type}::requiredPayloadFields",
            message.get("requiredPayloadFields"),
            REQUIRED_PAYLOAD_FIELDS[message_type],
        )
        checks.equal(
            f"catalogModelParity::{message_type}::payloadSchema.properties",
            _canon(message.get("payloadSchema", {}).get("properties", {})),
            _canon(PAYLOAD_FIELD_TYPES[message_type]),
        )
        declared_required = [
            name
            for name, spec in message.get("payloadSchema", {}).get("properties", {}).items()
            if spec.get("required")
        ]
        checks.equal(
            f"catalogModelParity::{message_type}::requiredFlagMatchesRequiredList",
            declared_required,
            message.get("requiredPayloadFields"),
        )
        checks.equal(
            f"catalogModelParity::{message_type}::additionalPropertiesFalse",
            message.get("payloadSchema", {}).get("additionalProperties"),
            False,
        )

    # ------------------------------------------------ envelope parity --------
    checks.equal(
        "catalogEnvelopeParity::requiredFields",
        catalog.get("envelopeSchema", {}).get("requiredFields"),
        REQUIRED_ENVELOPE_FIELDS,
    )
    checks.equal(
        "catalogEnvelopeParity::properties",
        _canon(catalog.get("envelopeSchema", {}).get("properties", {})),
        _canon(ENVELOPE_FIELD_TYPES),
    )
    checks.equal(
        "protocolEnvelopeParity::requiredFields",
        protocol.get("envelope", {}).get("requiredFields"),
        REQUIRED_ENVELOPE_FIELDS,
    )

    # -------------------------------------------- catalog <-> golden ---------
    golden_by_type = {vec["messageType"]: vec for vec in golden.get("messageVectors", [])}
    checks.equal("catalogGoldenParity::messageTypeSet", sorted(golden_by_type), sorted(python_types))
    for message_type in sorted(python_types):
        vector = golden_by_type.get(message_type)
        if vector is None:
            checks.record(f"catalogGoldenParity::{message_type}", False, "golden vector missing")
            continue
        payload = vector["envelope"].get("payload", {})
        required = REQUIRED_PAYLOAD_FIELDS[message_type]
        missing = [name for name in required if name not in payload]
        checks.record(
            f"catalogGoldenParity::{message_type}::requiredFieldsPresent",
            not missing,
            "all required fields present" if not missing else f"missing={missing}",
        )
        undeclared = sorted(set(payload) - set(PAYLOAD_FIELD_TYPES[message_type]))
        checks.record(
            f"catalogGoldenParity::{message_type}::noUndeclaredFields",
            not undeclared,
            "no undeclared fields" if not undeclared else f"undeclared={undeclared}",
        )
        try:
            validate_envelope(vector["envelope"])
            checks.record(f"catalogGoldenParity::{message_type}::envelopeValid", True, "validated")
        except Exception as exc:  # pragma: no cover - surfaced as a parity failure
            checks.record(f"catalogGoldenParity::{message_type}::envelopeValid", False, repr(exc))

    # ------------------------------- FRAME_READY <-> FrameHeader parity ------
    metadata_contract = catalog.get("frameHeaderMetadataContract", {})
    expected_checked = [FRAME_READY_BUFFER_INDEX_FIELD] + [
        payload_field for payload_field, _ in FRAME_READY_HEADER_METADATA_FIELDS
    ]
    checks.equal(
        "catalogFrameMetadataParity::checkedFields",
        metadata_contract.get("checkedFields"),
        expected_checked,
    )
    checks.equal(
        "catalogFrameMetadataParity::protocolCheckedFields",
        protocol.get("frameMetadataContract", {}).get("checkedFields"),
        expected_checked,
    )
    frame_ready_props = PAYLOAD_FIELD_TYPES["FRAME_READY"]
    checks.record(
        "catalogFrameMetadataParity::checkedFieldsAreRequired",
        all(name in REQUIRED_PAYLOAD_FIELDS["FRAME_READY"] for name in expected_checked),
        f"required={REQUIRED_PAYLOAD_FIELDS['FRAME_READY']}",
    )
    checks.record(
        "catalogFrameMetadataParity::cornerChecksumNaming",
        "cornerChecksum" in frame_ready_props
        and "checksum" not in frame_ready_props
        and "cornerChecksum" in expected_checked,
        "FRAME_READY payload exposes cornerChecksum and never the bare name checksum",
    )
    checks.equal(
        "catalogFrameMetadataParity::pixelFormatIsIntegerEnum",
        frame_ready_props["pixelFormat"].get("type"),
        "integer",
    )
    header_attr_names = {attr for _, attr in FRAME_READY_HEADER_METADATA_FIELDS}
    checks.record(
        "catalogFrameMetadataParity::payloadNamesMatchHeaderNames",
        header_attr_names == {name for name, _ in FRAME_READY_HEADER_METADATA_FIELDS},
        f"payload/header names identical: {sorted(header_attr_names)}",
    )

    # ------------------------------------- STATE_SNAPSHOT resync parity ------
    snapshot = catalog_messages.get("STATE_SNAPSHOT", {})
    snapshot_props = snapshot.get("payloadSchema", {}).get("properties", {})
    projection = snapshot_props.get("currentMatchProjection", {})
    checks.equal(
        "catalogStateSnapshotParity::requiredFields",
        snapshot.get("requiredPayloadFields"),
        [
            "snapshotSchemaVersion",
            "snapshotSessionId",
            "snapshotSequence",
            "businessReady",
            "currentMatchProjection",
        ],
    )
    checks.equal(
        "catalogStateSnapshotParity::projectionSchema",
        _canon(projection),
        _canon(PAYLOAD_FIELD_TYPES["STATE_SNAPSHOT"]["currentMatchProjection"]),
    )
    checks.equal(
        "catalogStateSnapshotParity::projectionRequiredFields",
        [name for name, spec in projection.get("properties", {}).items() if spec.get("required")],
        [
            "matchId",
            "matchState",
            "auctionPhase",
            "draftCount",
            "finalizedCount",
            "activeAuctionItems",
            "bids",
        ],
    )
    checks.record(
        "catalogStateSnapshotParity::noLegacyTopLevelSnapshotSchema",
        not any(key in catalog for key in ("snapshotSchema", "stateSnapshotSchema", "currentMatchSchema")),
        "legacy top-level snapshot schema absent from the catalog",
    )
    try:
        golden_snapshot = golden_by_type["STATE_SNAPSHOT"]["envelope"]
        validate_state_snapshot(Envelope(**golden_snapshot), golden_snapshot["sessionId"])
        checks.record("catalogStateSnapshotParity::goldenSnapshotAccepted", True, "resync validator accepted")
    except Exception as exc:  # pragma: no cover
        checks.record("catalogStateSnapshotParity::goldenSnapshotAccepted", False, repr(exc))

    # ------------------------------------ HELLO_ACK readiness / READY gate ---
    readiness = catalog.get("readinessContract", {})
    python_readiness_enum = PAYLOAD_FIELD_TYPES["HELLO_ACK"]["readiness"]["enum"]
    checks.equal(
        "catalogLifecycleParity::readinessEnum",
        sorted(readiness.get("enum") or []),
        sorted(python_readiness_enum),
    )
    checks.equal(
        "catalogLifecycleParity::readinessEnumMatchesCatalogPayload",
        catalog_messages.get("HELLO_ACK", {})
        .get("payloadSchema", {})
        .get("properties", {})
        .get("readiness", {})
        .get("enum"),
        python_readiness_enum,
    )
    lifecycle_readiness = lifecycle.get("readyGateRequirements", {}).get("readinessField", {})
    checks.equal(
        "catalogLifecycleParity::lifecycleReadinessEnum",
        sorted(lifecycle_readiness.get("enum") or []),
        sorted(python_readiness_enum),
    )
    checks.equal(
        "catalogLifecycleParity::businessReadyProjection",
        lifecycle_readiness.get("projectionField"),
        "engineBusinessReady",
    )
    checks.equal(
        "catalogLifecycleParity::readyGateValue",
        lifecycle_readiness.get("readyGateValue"),
        "READY",
    )
    engine_ready_gate = next(
        (
            gate
            for gate in lifecycle.get("readyGateRequirements", {}).get("gates", [])
            if gate.get("gate") == "engineBusinessReady"
        ),
        {},
    )
    checks.record(
        "catalogLifecycleParity::readyGateReferencesEngineBusinessReady",
        "engineBusinessReady" in engine_ready_gate.get("condition", ""),
        engine_ready_gate.get("condition", "<missing gate>"),
    )
    checks.record(
        "catalogLifecycleParity::readyGateRequiresReadinessReady",
        "readiness == READY" in engine_ready_gate.get("condition", "")
        or "readiness == READY" in lifecycle_readiness.get("consistencyRule", ""),
        "READY gate ties engineBusinessReady to readiness == READY",
    )
    try:
        golden_ack = golden_by_type["HELLO_ACK"]["envelope"]["payload"]
        validate_hello_ack_readiness(golden_ack)
        checks.record("catalogLifecycleParity::goldenHelloAckAccepted", True, "readiness contract satisfied")
    except Exception as exc:  # pragma: no cover
        checks.record("catalogLifecycleParity::goldenHelloAckAccepted", False, repr(exc))

    # ------------------------------------------- fixed v1 geometry parity ----
    geometry = catalog.get("ringBufferGeometry", {})
    expected_geometry = {
        "slotCount": SLOT_COUNT,
        "slotSizeBytes": SLOT_SIZE_BYTES,
        "mapTotalSizeBytes": MAP_TOTAL_SIZE_BYTES,
    }
    for key, value in expected_geometry.items():
        checks.equal(f"catalogGeometryParity::catalog::{key}", geometry.get(key), value)
    protocol_data_plane = protocol.get("transport", {}).get("dataPlane", {})
    for key, value in expected_geometry.items():
        checks.equal(f"catalogGeometryParity::protocol::{key}", protocol_data_plane.get(key), value)
    layout_geometry = frame_layout.get("ringBufferGeometry", {})
    for key, value in expected_geometry.items():
        checks.equal(f"catalogGeometryParity::frameLayout::{key}", layout_geometry.get(key), value)
    checks.equal(
        "catalogGeometryParity::layoutExtras",
        [
            layout_geometry.get("slotPayloadCapacityBytes"),
            layout_geometry.get("maxWidth"),
            layout_geometry.get("maxHeight"),
            layout_geometry.get("slotAlignmentBytes"),
        ],
        [SLOT_PAYLOAD_CAPACITY_BYTES, MAX_FRAME_WIDTH, MAX_FRAME_HEIGHT, SLOT_ALIGNMENT_BYTES],
    )
    checks.equal("catalogGeometryParity::policy", geometry.get("policy"), "FIXED_V1_CONSTANTS")
    checks.equal("catalogGeometryParity::geometryIsNegotiated", geometry.get("geometryIsNegotiated"), False)
    checks.equal(
        "catalogGeometryParity::protocolGeometryIsNegotiated",
        protocol_data_plane.get("geometryIsNegotiated"),
        False,
    )
    declared_field_names = set(ENVELOPE_FIELD_TYPES)
    for message in catalog.get("messages", []):
        declared_field_names |= set(message.get("payloadSchema", {}).get("properties", {}))
    forbidden_tokens = sorted(
        token
        for token in ("acceptedSlotCount", "acceptedSlotSizeBytes", "acceptedMapTotalSizeBytes")
        if token in declared_field_names
    )
    checks.record(
        "catalogGeometryParity::noNegotiatedGeometryFields",
        not forbidden_tokens,
        "no acceptedSlot* geometry negotiation fields are declared anywhere in the catalog"
        if not forbidden_tokens
        else f"declared negotiation fields={forbidden_tokens}",
    )
    checks.record(
        "catalogGeometryParity::helloCarriesNoGeometryConstants",
        not ({"slotCount", "slotSizeBytes", "mapTotalSizeBytes"} & set(PAYLOAD_FIELD_TYPES["HELLO"])),
        f"HELLO carries {sorted(PAYLOAD_FIELD_TYPES['HELLO'])}",
    )
    checks.record(
        "catalogGeometryParity::helloAckCarriesNoGeometryConstants",
        not ({"slotCount", "slotSizeBytes", "mapTotalSizeBytes"} & set(PAYLOAD_FIELD_TYPES["HELLO_ACK"])),
        f"HELLO_ACK carries {sorted(PAYLOAD_FIELD_TYPES['HELLO_ACK'])}",
    )

    # ------------------------------------------------ fail-closed error codes
    models_codes = sorted(set(re.findall(r"ERR_[A-Z0-9_]+", models_source)))
    catalog_codes = catalog.get("failClosedErrorCodes", [])
    checks.equal("catalogErrorCodeParity::catalogMatchesModelsSource", sorted(catalog_codes), models_codes)
    known_codes = {entry["errorCode"] for entry in error_catalog.get("errors", [])}
    unknown = sorted(set(catalog_codes) - known_codes)
    checks.record(
        "catalogErrorCodeParity::allDeclaredInErrorCatalog",
        not unknown,
        "all catalog error codes exist in error_catalog_v1.json" if not unknown else f"unknown={unknown}",
    )

    return {
        "schemaVersion": PARITY_SCHEMA_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "sourceOfTruth": "architecture/v2/contracts/models.py",
        "generator": "architecture/v2/contracts/schema_parity.py",
        "totalMessages": len(PAYLOAD_FIELD_TYPES),
        "catalogModelParity": all(
            check["passed"] for check in checks.checks if check["check"].startswith("catalogModelParity")
        ),
        "catalogEnvelopeParity": all(
            check["passed"]
            for check in checks.checks
            if check["check"].startswith(("catalogEnvelopeParity", "protocolEnvelopeParity"))
        ),
        "catalogGoldenParity": all(
            check["passed"] for check in checks.checks if check["check"].startswith("catalogGoldenParity")
        ),
        "catalogLifecycleParity": all(
            check["passed"] for check in checks.checks if check["check"].startswith("catalogLifecycleParity")
        ),
        "catalogFrameMetadataParity": all(
            check["passed"] for check in checks.checks if check["check"].startswith("catalogFrameMetadataParity")
        ),
        "catalogStateSnapshotParity": all(
            check["passed"] for check in checks.checks if check["check"].startswith("catalogStateSnapshotParity")
        ),
        "catalogGeometryParity": all(
            check["passed"] for check in checks.checks if check["check"].startswith("catalogGeometryParity")
        ),
        "catalogErrorCodeParity": all(
            check["passed"] for check in checks.checks if check["check"].startswith("catalogErrorCodeParity")
        ),
        "allPassed": checks.all_passed,
        "totalChecks": len(checks.checks),
        "passedChecks": sum(1 for check in checks.checks if check["passed"]),
        "failures": checks.failures(),
        "checks": checks.checks,
    }


def write_parity_report(contracts_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Regenerates message_schema_parity.json inside the contracts directory."""
    if contracts_dir is None:
        contracts_dir = Path(__file__).resolve().parent
    contracts_dir = Path(contracts_dir)
    report = build_parity_report(contracts_dir)
    out_path = contracts_dir / "message_schema_parity.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":  # pragma: no cover
    result = write_parity_report()
    print(f"totalMessages={result['totalMessages']} allPassed={result['allPassed']}")
    print(f"checks={result['passedChecks']}/{result['totalChecks']}")
    for failure in result["failures"]:
        print(f"  FAIL {failure['check']}: {failure['detail']}")
    raise SystemExit(0 if result["allPassed"] else 1)
