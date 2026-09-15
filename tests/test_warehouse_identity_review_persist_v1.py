"""Isolated tests for warehouse identity review artifact persistence."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
TESTS_DIR = PROJECT_ROOT / "tests"
for entry in (str(CORE_DIR), str(APP_DIR), str(TESTS_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import (
    build_canonical_match_record_v7,
    validate_canonical_match_record_v7,
)
from history_admission import DuplicateIndex, evaluate_history_admission
from runtime_data import DATA_ROOT_OVERRIDE_ENV, runtime_data_paths
from warehouse_catalog_geometry import CatalogGeometryIndex
from warehouse_identity_review import (
    ACTION_CONFIRM,
    ACTION_DEFER,
    CatalogAuthority,
    REVIEW_SCHEMA,
    artifact_fingerprint_for,
    resolve_warehouse_identity_review,
)
from warehouse_identity_review_persist import (
    IDEMPOTENCY_FIELDS,
    WarehouseIdentityReviewPersistError,
    persist_warehouse_identity_review,
)
from warehouse_identity_review_session import WarehouseIdentityReviewSession
from warehouse_coverage_ledger import REASON_COMPLETE, REASON_USER_STOP, WarehouseCoverageLedger
from warehouse_review_packet import build_warehouse_review_packet, source_fingerprint_for
from settlement_truth_evidence_contract import ORIGINAL_V2, load_contract_schema

EMPTY_DUPES = DuplicateIndex(frozenset(), frozenset(), 0)
CATALOG = [
    {
        "Id": "catRect",
        "Name": "RectBox",
        "Quality": "金",
        "Width": 2,
        "Height": 2,
        "Cells": 4,
        "Shape": "1100011000000000000000000",
    }
]


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _descriptor(evidence_id: str, seed: str, key: str) -> dict:
    digest = _digest(seed)
    return {
        "schemaVersion": ORIGINAL_V2,
        "evidenceId": evidence_id,
        "recordStableKey": key,
        "kind": "warehouse-segment",
        "capturedAt": "2026-08-25T12:00:00Z",
        "storageMode": "file",
        "relativePath": f"evidence/settlement_v2/blobs/{digest[:2]}/{digest}.png",
        "sha256": digest,
        "byteSize": 1024,
        "mimeType": "image/png",
        "width": 640,
        "height": 720,
        "coverageMode": "viewport-segment",
        "coverageStatus": "PARTIAL",
    }


def _coverage(complete: bool, key: str):
    ledger = WarehouseCoverageLedger(key)
    top = _descriptor("ev-top", "aa", key)
    descriptors = [top]
    ledger.add_segment(top, sequence_index=0, top_proof={"trusted": True, "proofId": "t"})
    if complete:
        mid = _descriptor("ev-mid", "bb", key)
        bot = _descriptor("ev-bot", "cc", key)
        descriptors.extend([mid, bot])
        ledger.add_segment(
            mid,
            sequence_index=1,
            overlap_proof={"trusted": True, "aligned": True, "proofId": "o1", "previousEvidenceId": "ev-top"},
        )
        ledger.add_segment(
            bot,
            sequence_index=2,
            bottom_proof={"trusted": True, "proofId": "b"},
            overlap_proof={"trusted": True, "aligned": True, "proofId": "o2", "previousEvidenceId": "ev-mid"},
        )
        return ledger.finalize(REASON_COMPLETE), descriptors
    return ledger.finalize(REASON_USER_STOP), descriptors


def _track(track_id, candidates, observations):
    return {
        "trackId": track_id,
        "status": "OBSERVED",
        "clipped": False,
        "reasons": [],
        "widthCandidates": [2],
        "heightCandidates": [2],
        "spanCandidates": [4],
        "globalCellMaskCandidates": [{"cellMask": [[1, 1], [1, 1]]}],
        "observations": observations,
        "candidates": candidates,
    }


def _obs(oid, segment_id, sequence):
    return {
        "observationId": oid,
        "segmentId": segment_id,
        "sequenceIndex": sequence,
        "localBox": [4.0, 6.0, 40.0, 50.0],
        "status": "OBSERVED",
    }


def _physical(key, tracks, complete):
    segments = [{"segmentId": "seg0", "sequenceIndex": 0, "originY": 0.0, "scrollState": "TOP", "chainId": 0}]
    if complete:
        segments.extend([
            {"segmentId": "seg1", "sequenceIndex": 1, "originY": 90.0, "scrollState": "MIDDLE", "chainId": 0},
            {"segmentId": "seg2", "sequenceIndex": 2, "originY": 210.0, "scrollState": "BOTTOM", "chainId": 0},
        ])
    return {
        "schemaVersion": "warehouse-physical-ledger.v1",
        "recordStableKey": key,
        "chainStatus": "ACTIVE",
        "segments": segments,
        "tracks": tracks,
        "conflicts": [],
    }


def _packet(key="recIdRev01", *, complete=True):
    coverage, descriptors = _coverage(complete, key)
    candidates = [
        {
            "catalogId": "catRect",
            "name": "RectBox",
            "identityStatus": "CANDIDATE_ONLY",
            "geometry": {"width": 2, "height": 2, "cells": 4, "shape": "1100011000000000000000000"},
            "matchReasons": ["EXACT_CELL_MASK"],
        }
    ]
    tracks = [_track("track-a", candidates, [_obs("obs-a0", "seg0", 0), _obs("obs-a1", "seg1" if complete else "seg0", 1 if complete else 0)])]
    physical = _physical(key, tracks, complete)
    packet = build_warehouse_review_packet(
        coverage_ledger=coverage,
        physical_ledger=physical,
        descriptors=descriptors,
        catalog_index=CatalogGeometryIndex(CATALOG),
    )
    packet["tracks"][0]["candidates"] = candidates
    packet["tracks"][0]["bestObservationId"] = "obs-a0"
    packet["sourceFingerprint"] = source_fingerprint_for(packet)
    return packet


def _seed_record(history: CanonicalHistoryStore, match_id: str, *, source="vision-auto-archiver", lifecycle="FINALIZED"):
    record = build_canonical_match_record_v7(
        match_id=match_id,
        played_at="2026-08-25T12:00:00+08:00",
        lifecycle_status=lifecycle,
        source=source,
        environment={"venue": "珊瑚场", "box": "皮制宝箱", "fieldCondition": "standard"},
        settlement={
            "status": "verified",
            "verified": True,
            "clearingPrice": 100000,
            "actualTotal": 200000,
            "realizedProfit": 50000,
            "acquired": True,
            "winner": "玩家本人",
            "settlementItems": [],
        },
    )
    history.persist_record_transactional(record, is_finalized=(lifecycle == "FINALIZED"))
    return record


class WarehouseIdentityReviewPersistV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.prev_env = os.environ.get(DATA_ROOT_OVERRIDE_ENV)
        prod_env = {key: value for key, value in os.environ.items() if key != DATA_ROOT_OVERRIDE_ENV}
        try:
            self.prod = runtime_data_paths(prod_env)
            self.hist = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        except Exception:
            self.prod = None
            self.hist = None
        os.environ[DATA_ROOT_OVERRIDE_ENV] = str(self.root)
        self.history_path = runtime_data_paths().history_path
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history = CanonicalHistoryStore(self.history_path)
        self.catalog = CatalogAuthority(CATALOG)

    def tearDown(self):
        if self.prev_env is None:
            os.environ.pop(DATA_ROOT_OVERRIDE_ENV, None)
        else:
            os.environ[DATA_ROOT_OVERRIDE_ENV] = self.prev_env
        if self.prod is not None:
            after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
            self.assertEqual(after, self.hist)
        self.tmp.cleanup()

    def _artifact_for(self, packet, decisions):
        document = {
            "schemaVersion": "warehouse-identity-review-decision.v1",
            "recordStableKey": packet["recordStableKey"],
            "packetFingerprint": packet["sourceFingerprint"],
            "reviewedAt": "2026-08-25T16:00:00Z",
            "reviewerType": "HUMAN",
            "decisions": decisions,
        }
        return resolve_warehouse_identity_review(packet, document, catalog=self.catalog)

    def _ready_session(self, packet, action=ACTION_CONFIRM):
        session = WarehouseIdentityReviewSession(catalog=self.catalog)
        session.open(packet)
        if action == ACTION_CONFIRM:
            decisions = [{
                "decisionId": "d1",
                "trackId": "track-a",
                "action": ACTION_CONFIRM,
                "selectedCatalogId": "catRect",
            }]
        elif action == ACTION_DEFER:
            decisions = [{"decisionId": "d1", "trackId": "track-a", "action": ACTION_DEFER}]
        else:
            decisions = [{"decisionId": "d1", "trackId": "track-a", "action": action, "reason": "later"}]
        session._artifact = self._artifact_for(packet, decisions)
        return session

    def test_schema_slot_is_optional_and_closed(self):
        match = load_contract_schema("match-record-v7.schema.json")
        settlement = match["properties"]["settlement"]
        self.assertIs(settlement["additionalProperties"], False)
        self.assertIs(match["additionalProperties"], False)
        self.assertNotIn("warehouseIdentityReview", settlement["required"])
        self.assertEqual(
            settlement["properties"]["warehouseIdentityReview"]["$ref"],
            "https://yihuanpaimai.local/schemas/warehouse-identity-review-v1.schema.json",
        )
        self.assertNotIn("warehouseIdentityReview", settlement["properties"]["truthEvidence"]["oneOf"][0])
        old = build_canonical_match_record_v7(
            match_id="oldV7Compat01",
            played_at="2026-08-25T12:00:00+08:00",
            lifecycle_status="FINALIZED",
            source="vision-auto-archiver",
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 1,
                "actualTotal": 2,
                "realizedProfit": 0,
                "acquired": True,
                "winner": "x",
                "settlementItems": [],
            },
        )
        ok, reasons = validate_canonical_match_record_v7(old)
        self.assertTrue(ok, reasons)
        self.assertNotIn("warehouseIdentityReview", old["settlement"])
        self.assertEqual(IDEMPOTENCY_FIELDS, ("packetFingerprint", "artifactFingerprint"))

    def test_auto_archive_preserves_reviewed_draft_artifact(self):
        try:
            from auto_archiver import AutoArchiver
            import test_live_settlement_authority as fixture
        except (ImportError, ModuleNotFoundError):
            self.skipTest("win32gui / main environment not available")
        packet = _packet()
        match_id = packet["recordStableKey"]
        archiver = AutoArchiver([str(self.history_path)])
        archiver.archive_match(fixture.LiveSettlementAuthorityTests().context(match_id, None))
        session = self._ready_session(packet)
        binding = session.persist_binding()
        persist_warehouse_identity_review(
            session=session, history_store=self.history,
            session_id=binding["sessionId"], packet_fingerprint=binding["packetFingerprint"])
        reviewed = self.history.lookup(match_id)["settlement"]["warehouseIdentityReview"]
        saved = archiver.archive_match(fixture.LiveSettlementAuthorityTests().context(match_id, False))
        self.assertEqual(saved["settlement"]["warehouseIdentityReview"], reviewed)
        self.assertEqual(saved["lifecycleStatus"], "FINALIZED")

    def test_legal_artifact_round_trip_and_idempotent(self):
        packet = _packet()
        _seed_record(self.history, packet["recordStableKey"])
        before = self.history.lookup(packet["recordStableKey"])
        before_admission = evaluate_history_admission(before, EMPTY_DUPES)
        session = self._ready_session(packet)
        binding = session.persist_binding()
        first = persist_warehouse_identity_review(
            session=session,
            history_store=self.history,
            session_id=binding["sessionId"],
            packet_fingerprint=binding["packetFingerprint"],
        )
        self.assertTrue(first["ok"])
        self.assertTrue(first["written"])
        self.assertFalse(first["idempotent"])
        stored = self.history.lookup(packet["recordStableKey"])
        artifact = stored["settlement"]["warehouseIdentityReview"]
        self.assertEqual(artifact["schemaVersion"], REVIEW_SCHEMA)
        self.assertEqual(artifact["artifactFingerprint"], session.artifact_copy()["artifactFingerprint"])
        self.assertEqual(artifact_fingerprint_for(artifact), artifact["artifactFingerprint"])
        self.assertEqual(stored["lifecycleStatus"], "FINALIZED")
        self.assertTrue(stored["settlement"]["verified"])
        self.assertEqual(stored["settlement"]["status"], "verified")
        after_admission = evaluate_history_admission(stored, EMPTY_DUPES)
        self.assertEqual(after_admission.admitted, before_admission.admitted)
        self.assertEqual(after_admission.exclusion_reason, before_admission.exclusion_reason)
        self.assertEqual(after_admission.lifecycle, before_admission.lifecycle)
        again = persist_warehouse_identity_review(
            session=session,
            history_store=self.history,
            session_id=binding["sessionId"],
            packet_fingerprint=binding["packetFingerprint"],
        )
        self.assertTrue(again["idempotent"])
        self.assertFalse(again["written"])
        self.assertEqual(
            self.history.lookup(packet["recordStableKey"])["settlement"]["warehouseIdentityReview"]["artifactFingerprint"],
            artifact["artifactFingerprint"],
        )

    def test_partial_review_does_not_change_lifecycle_or_admission(self):
        packet = _packet(complete=False)
        _seed_record(self.history, packet["recordStableKey"])
        session = self._ready_session(packet, action=ACTION_DEFER)
        artifact = session.artifact_copy()
        self.assertEqual(artifact["reviewCompletion"], "PARTIAL")
        binding = session.persist_binding()
        persist_warehouse_identity_review(
            session=session,
            history_store=self.history,
            session_id=binding["sessionId"],
            packet_fingerprint=binding["packetFingerprint"],
        )
        stored = self.history.lookup(packet["recordStableKey"])
        self.assertEqual(stored["lifecycleStatus"], "FINALIZED")
        self.assertTrue(stored["settlement"]["verified"])
        self.assertEqual(stored["settlement"]["warehouseIdentityReview"]["reviewCompletion"], "PARTIAL")

    def test_conflict_and_binding_failures_do_not_write(self):
        packet = _packet()
        _seed_record(self.history, packet["recordStableKey"])
        session = self._ready_session(packet)
        binding = session.persist_binding()
        persist_warehouse_identity_review(
            session=session,
            history_store=self.history,
            session_id=binding["sessionId"],
            packet_fingerprint=binding["packetFingerprint"],
        )
        before = self.history_path.read_bytes()
        session._artifact = self._artifact_for(packet, [{"decisionId": "d2", "trackId": "track-a", "action": ACTION_DEFER}])
        with self.assertRaises(WarehouseIdentityReviewPersistError) as raised:
            persist_warehouse_identity_review(
                session=session,
                history_store=self.history,
                session_id=session.persist_binding()["sessionId"],
                packet_fingerprint=session.persist_binding()["packetFingerprint"],
            )
        self.assertEqual(raised.exception.code, "ARTIFACT_CONFLICT")
        self.assertEqual(self.history_path.read_bytes(), before)
        with self.assertRaises(WarehouseIdentityReviewPersistError) as session_err:
            persist_warehouse_identity_review(
                session=session,
                history_store=self.history,
                session_id="nope",
                packet_fingerprint=binding["packetFingerprint"],
            )
        self.assertEqual(session_err.exception.code, "SESSION_MISMATCH")
        with self.assertRaises(WarehouseIdentityReviewPersistError) as fp_err:
            persist_warehouse_identity_review(
                session=session,
                history_store=self.history,
                session_id=binding["sessionId"],
                packet_fingerprint="a" * 64,
            )
        self.assertEqual(fp_err.exception.code, "PACKET_FINGERPRINT_MISMATCH")
        self.assertEqual(self.history_path.read_bytes(), before)

    def test_illegal_inputs_and_legacy_are_rejected(self):
        packet = _packet()
        session = self._ready_session(packet)
        binding = session.persist_binding()
        with self.assertRaises(WarehouseIdentityReviewPersistError) as raised:
            persist_warehouse_identity_review(
                session=session,
                history_store=self.history,
                session_id=binding["sessionId"],
                packet_fingerprint=binding["packetFingerprint"],
                artifact=session.artifact_copy(),
            )
        self.assertEqual(raised.exception.code, "FORBIDDEN_CLIENT_FIELD")
        with self.assertRaises(WarehouseIdentityReviewPersistError) as missing:
            persist_warehouse_identity_review(
                session=session,
                history_store=self.history,
                session_id=binding["sessionId"],
                packet_fingerprint=binding["packetFingerprint"],
            )
        self.assertEqual(missing.exception.code, "RECORD_NOT_FOUND")
        _seed_record(self.history, packet["recordStableKey"], source="legacy")
        with self.assertRaises(WarehouseIdentityReviewPersistError) as legacy:
            persist_warehouse_identity_review(
                session=session,
                history_store=self.history,
                session_id=binding["sessionId"],
                packet_fingerprint=binding["packetFingerprint"],
            )
        self.assertEqual(legacy.exception.code, "LEGACY_SOURCE_FORBIDDEN")
        other = _packet(key="recIdRev99")
        _seed_record(self.history, other["recordStableKey"])
        with self.assertRaises(WarehouseIdentityReviewPersistError) as mismatch:
            persist_warehouse_identity_review(
                session=session,
                history_store=self.history,
                session_id=binding["sessionId"],
                packet_fingerprint=binding["packetFingerprint"],
                record_stable_key="recIdRev99",
            )
        self.assertEqual(mismatch.exception.code, "RECORD_KEY_MISMATCH")
        session._artifact["resolvedItems"][0]["sha256"] = "zz"
        with self.assertRaises(WarehouseIdentityReviewPersistError) as evidence:
            persist_warehouse_identity_review(
                session=session,
                history_store=self.history,
                session_id=binding["sessionId"],
                packet_fingerprint=binding["packetFingerprint"],
            )
        self.assertIn(evidence.exception.code, {"INVALID_ARTIFACT", "EVIDENCE_REF_MISMATCH"})

    def test_transaction_failure_keeps_history_bytes(self):
        packet = _packet()
        _seed_record(self.history, packet["recordStableKey"])
        session = self._ready_session(packet)
        binding = session.persist_binding()
        before = self.history_path.read_bytes()
        with mock.patch("canonical_history_store.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(WarehouseIdentityReviewPersistError) as raised:
                persist_warehouse_identity_review(
                    session=session,
                    history_store=self.history,
                    session_id=binding["sessionId"],
                    packet_fingerprint=binding["packetFingerprint"],
                )
        self.assertEqual(raised.exception.code, "HISTORY_WRITE_FAILED")
        self.assertEqual(self.history_path.read_bytes(), before)
        blob = json.loads(before.decode("utf-8"))
        self.assertNotIn("warehouseIdentityReview", blob["records"][0]["settlement"])


if __name__ == "__main__":
    unittest.main()
