"""Isolated tests for warehouse reviewed-label dataset export v1."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from runtime_data import DATA_ROOT_OVERRIDE_ENV, HISTORY_FILENAME, runtime_data_paths
from settlement_evidence_store_v2 import KIND_WAREHOUSE, KIND_WAREHOUSE_SEGMENT, STORE_RELATIVE_ROOT, SettlementEvidenceStoreV2
from warehouse_catalog_geometry import CatalogGeometryIndex
from warehouse_coverage_ledger import REASON_COMPLETE, REASON_USER_STOP, WarehouseCoverageLedger
from warehouse_identity_review import (
    ACTION_CONFIRM,
    ACTION_DEFER,
    ACTION_EXCLUDE,
    ACTION_FLAG,
    ACTION_OUT_OF_CATALOG,
    ACTION_OVERRIDE,
    CatalogAuthority,
    artifact_fingerprint_for,
    resolve_warehouse_identity_review,
)
from warehouse_reviewed_label_export import (
    MIN_SOURCES,
    MIN_TRACKS_PER_QUALITY,
    export_reviewed_label_dataset,
    group_id_for,
    iter_item_frames,
)
from warehouse_review_packet import build_warehouse_review_packet, source_fingerprint_for

CATALOG = [
    {"Id": "catRect", "Name": "RectBox", "Quality": "金", "Width": 2, "Height": 2, "Cells": 4, "Shape": "1100011000000000000000000"},
    {"Id": "catOther", "Name": "OtherBox", "Quality": "紫", "Width": 1, "Height": 1, "Cells": 1, "Shape": "1000000000000000000000000"},
]


def _png(color=(20, 90, 180), size=(80, 80)) -> bytes:
    image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    image[:] = color
    return cv2.imencode(".png", image)[1].tobytes()


class WarehouseReviewedLabelExportV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.prev = os.environ.get(DATA_ROOT_OVERRIDE_ENV)
        prod_env = {key: value for key, value in os.environ.items() if key != DATA_ROOT_OVERRIDE_ENV}
        try:
            self.prod = runtime_data_paths(prod_env)
            self.hist = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
            self.prod_store = (self.prod.root / STORE_RELATIVE_ROOT)
            self.prod_store_marker = self.prod_store.exists()
        except Exception:
            self.prod = None
            self.hist = None
            self.prod_store = None
            self.prod_store_marker = None
        os.environ[DATA_ROOT_OVERRIDE_ENV] = str(self.root)
        (self.root / "history").mkdir(parents=True, exist_ok=True)
        self.history = CanonicalHistoryStore(self.root / "history" / HISTORY_FILENAME)
        self.store = SettlementEvidenceStoreV2(self.root)
        self.catalog = CatalogAuthority(CATALOG)
        self.out = self.root / "export"

    def tearDown(self):
        if self.prev is None:
            os.environ.pop(DATA_ROOT_OVERRIDE_ENV, None)
        else:
            os.environ[DATA_ROOT_OVERRIDE_ENV] = self.prev
        if self.prod is not None:
            after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
            self.assertEqual(after, self.hist)
        self.tmp.cleanup()

    def _desc(self, key, color=(20, 90, 180), kind=KIND_WAREHOUSE_SEGMENT):
        return self.store.save_original(record_stable_key=key, kind=kind, image_bytes=_png(color, (80, 80)))

    def _packet(self, key, descriptors, *, complete=True):
        ledger = WarehouseCoverageLedger(key)
        ledger.add_segment(descriptors[0], sequence_index=0, top_proof={"trusted": True, "proofId": "t"})
        evidence_map = {"seg0": descriptors[0]["evidenceId"]}
        segments = [{"segmentId": "seg0", "sequenceIndex": 0, "originY": 0.0, "scrollState": "TOP", "chainId": 0}]
        if complete and len(descriptors) >= 3:
            ledger.add_segment(descriptors[1], sequence_index=1, overlap_proof={"trusted": True, "aligned": True, "proofId": "o1", "previousEvidenceId": descriptors[0]["evidenceId"]})
            ledger.add_segment(descriptors[2], sequence_index=2, bottom_proof={"trusted": True, "proofId": "b"}, overlap_proof={"trusted": True, "aligned": True, "proofId": "o2", "previousEvidenceId": descriptors[1]["evidenceId"]})
            evidence_map["seg1"] = descriptors[1]["evidenceId"]
            evidence_map["seg2"] = descriptors[2]["evidenceId"]
            segments.extend([
                {"segmentId": "seg1", "sequenceIndex": 1, "originY": 10.0, "scrollState": "MIDDLE", "chainId": 0},
                {"segmentId": "seg2", "sequenceIndex": 2, "originY": 20.0, "scrollState": "BOTTOM", "chainId": 0},
            ])
            coverage = ledger.finalize(REASON_COMPLETE)
        else:
            coverage = ledger.finalize(REASON_USER_STOP)
        candidates = [{"catalogId": "catRect", "name": "RectBox", "identityStatus": "CANDIDATE_ONLY",
                       "geometry": {"width": 2, "height": 2, "cells": 4, "shape": "1100011000000000000000000"},
                       "matchReasons": ["EXACT_CELL_MASK"]}]
        track = {
            "trackId": "track-a", "status": "OBSERVED", "clipped": False, "reasons": [],
            "widthCandidates": [2], "heightCandidates": [2], "spanCandidates": [4],
            "globalCellMaskCandidates": [{"cellMask": [[1, 1], [1, 1]]}], "candidates": candidates,
            "observations": [
                {"observationId": "obs-a0", "segmentId": "seg0", "sequenceIndex": 0, "localBox": [10.0, 10.0, 50.0, 50.0], "status": "OBSERVED"},
            ],
        }
        physical = {
            "schemaVersion": "warehouse-physical-ledger.v1", "recordStableKey": key, "chainStatus": "ACTIVE",
            "segments": segments, "tracks": [track], "conflicts": [],
        }
        packet = build_warehouse_review_packet(
            coverage_ledger=coverage, physical_ledger=physical, descriptors=descriptors,
            catalog_index=CatalogGeometryIndex(CATALOG), segment_evidence_map=evidence_map,
        )
        packet["tracks"][0]["candidates"] = candidates
        packet["tracks"][0]["bestObservationId"] = "obs-a0"
        packet["sourceFingerprint"] = source_fingerprint_for(packet)
        return packet

    def _artifact(self, packet, action=ACTION_CONFIRM, **decision_extra):
        item = {"decisionId": "d1", "trackId": "track-a", "action": action}
        item.update(decision_extra)
        if action in {ACTION_CONFIRM, ACTION_OVERRIDE} and "selectedCatalogId" not in item:
            item["selectedCatalogId"] = "catRect" if action == ACTION_CONFIRM else "catOther"
        if action == ACTION_OVERRIDE:
            item["overrideReason"] = "HUMAN_VISUAL_IDENTIFICATION"
            item["confirmedByHuman"] = True
        if action in {ACTION_OUT_OF_CATALOG, ACTION_EXCLUDE, ACTION_FLAG} and "reason" not in item:
            item["reason"] = "no"
        document = {
            "schemaVersion": "warehouse-identity-review-decision.v1",
            "recordStableKey": packet["recordStableKey"],
            "packetFingerprint": packet["sourceFingerprint"],
            "reviewedAt": "2026-08-25T16:00:00Z",
            "reviewerType": "HUMAN",
            "decisions": [item],
        }
        return resolve_warehouse_identity_review(packet, document, catalog=self.catalog)

    def _seed(self, key, artifact, *, source="vision-auto-archiver"):
        record = build_canonical_match_record_v7(
            match_id=key,
            played_at="2026-08-25T12:00:00+08:00",
            lifecycle_status="FINALIZED",
            source=source,
            environment={"venue": "珊瑚场", "box": "皮制宝箱", "fieldCondition": "standard"},
            settlement={
                "status": "verified", "verified": True, "clearingPrice": 100000,
                "actualTotal": 200000, "realizedProfit": 50000, "acquired": True,
                "winner": "玩家本人", "settlementItems": [],
                "warehouseIdentityReview": artifact,
            },
        )
        self.history.persist_record_transactional(record, is_finalized=True)
        return record

    def _confirmed(self, key="recExp01", action=ACTION_CONFIRM, complete=True, **kwargs):
        top = self._desc(key, (20, 90, 180))
        descriptors = [top]
        if complete:
            descriptors.extend([self._desc(key, (20, 140, 80)), self._desc(key, (40, 40, 40))])
        packet = self._packet(key, descriptors, complete=complete)
        artifact = self._artifact(packet, action=action, **kwargs)
        self._seed(key, artifact)
        return packet, artifact

    def test_confirm_override_partial_and_group_id(self):
        packet, artifact = self._confirmed("recExp01", ACTION_CONFIRM)
        self._confirmed("recExp02", ACTION_OVERRIDE, selectedCatalogId="catOther")
        self._confirmed("recExp03", ACTION_CONFIRM, complete=False)
        manifest = export_reviewed_label_dataset(runtime_root=self.root, output_dir=self.out)
        actions = {item["action"] for item in manifest["samples"]}
        self.assertIn(ACTION_CONFIRM, actions)
        self.assertIn(ACTION_OVERRIDE, actions)
        partial = [item for item in manifest["samples"] if item["recordStableKey"] == "recExp03"]
        self.assertEqual(len(partial), 1)
        self.assertEqual(partial[0]["warehouseCoverage"], "PARTIAL")
        self.assertFalse(partial[0]["solverEligible"])
        self.assertTrue(partial[0]["trainingEligible"])
        item = artifact["resolvedItems"][0]
        extra = {"evidenceId": item["evidenceId"], "bbox": item["bbox"], "sequenceIndex": 7, "sha256": item["sha256"]}
        frames = iter_item_frames(item, extra_frames=[extra])
        self.assertEqual(len(frames), 2)
        self.assertEqual(group_id_for("recExp01", "track-a"), frames and group_id_for(item["recordStableKey"], item["trackId"]))
        self.assertTrue(all(sample["groupId"] == group_id_for(sample["recordStableKey"], sample["trackId"]) for sample in manifest["samples"]))
        self.assertTrue(all(sample["solverEligible"] is False for sample in manifest["samples"]))
        blob = json.dumps(manifest)
        self.assertNotIn(str(self.root), blob.replace("\\\\", "/"))
        self.assertNotIn("C:/", blob)
        crop_path = self.out / manifest["samples"][0]["relativePath"]
        self.assertTrue(crop_path.is_file())
        self.assertEqual(hashlib.sha256(crop_path.read_bytes()).hexdigest(), manifest["samples"][0]["cropSha256"])

    def test_rejections_hash_bbox_and_legacy_89(self):
        packet, artifact = self._confirmed("recExpGood")
        self._confirmed("recExpDefer", ACTION_DEFER)
        self._confirmed("recExpOut", ACTION_OUT_OF_CATALOG, reason="out")
        self._confirmed("recExpFlag", ACTION_FLAG, reason="geom")
        self._confirmed("recExpExcl", ACTION_EXCLUDE, reason="false")
        seg = self._desc("recExpThumb", (20, 90, 180))
        thumb = self._desc("recExpThumb", (11, 11, 11), kind=KIND_WAREHOUSE)
        packet_thumb = self._packet("recExpThumb", [seg, self._desc("recExpThumb", (1, 2, 3)), self._desc("recExpThumb", (3, 2, 1))])
        art_thumb = self._artifact(packet_thumb)
        art_thumb["resolvedItems"][0]["evidenceId"] = thumb["evidenceId"]
        art_thumb["resolvedItems"][0]["sha256"] = thumb["sha256"]
        art_thumb["artifactFingerprint"] = artifact_fingerprint_for(art_thumb)
        self._seed("recExpThumb", art_thumb)
        key_missing = "recExpMiss"
        top = self._desc(key_missing)
        packet_missing = self._packet(key_missing, [top, self._desc(key_missing, (9, 9, 9)), self._desc(key_missing, (8, 8, 8))])
        art_missing = self._artifact(packet_missing)
        art_missing["resolvedItems"][0]["evidenceId"] = "missing-ev"
        art_missing["artifactFingerprint"] = artifact_fingerprint_for(art_missing)
        self._seed(key_missing, art_missing)
        key_bbox = "recExpBBox"
        packet_bbox, art_bbox = self._confirmed(key_bbox)
        stored = self.history.lookup(key_bbox)
        stored["settlement"]["warehouseIdentityReview"]["resolvedItems"][0]["bbox"] = [9, 9, 9, 9]
        stored["settlement"]["warehouseIdentityReview"]["artifactFingerprint"] = artifact_fingerprint_for(stored["settlement"]["warehouseIdentityReview"])
        self.history.update_record_transactional(key_bbox, {"settlement": {"warehouseIdentityReview": stored["settlement"]["warehouseIdentityReview"]}})
        key_hash = "recExpHash"
        packet_hash, art_hash = self._confirmed(key_hash)
        stored_h = self.history.lookup(key_hash)
        stored_h["settlement"]["warehouseIdentityReview"]["resolvedItems"][0]["sha256"] = "ab" * 32
        stored_h["settlement"]["warehouseIdentityReview"]["artifactFingerprint"] = artifact_fingerprint_for(stored_h["settlement"]["warehouseIdentityReview"])
        self.history.update_record_transactional(key_hash, {"settlement": {"warehouseIdentityReview": stored_h["settlement"]["warehouseIdentityReview"]}})
        self._seed("g89-old", artifact, source="vision-89")
        manifest = export_reviewed_label_dataset(runtime_root=self.root, output_dir=self.out)
        reasons = {item["reason"] for item in manifest["rejected"]}
        self.assertIn("DEFER", reasons)
        self.assertIn("MARK_OUT_OF_CATALOG", reasons)
        self.assertIn("FLAG_GEOMETRY_ERROR", reasons)
        self.assertIn("EXCLUDE_FALSE_COMPONENT", reasons)
        self.assertIn("MISSING_ORIGINAL", reasons)
        self.assertIn("INVALID_BBOX", reasons)
        self.assertIn("HASH_MISMATCH", reasons)
        self.assertIn("LEGACY_89_GROUP", reasons)
        self.assertTrue("THUMBNAIL_ONLY" in reasons or "INVALID_DESCRIPTOR" in reasons or "MISSING_ORIGINAL" in reasons)

    def test_deterministic_and_does_not_touch_history_or_store(self):
        self._confirmed("recExpDet")
        history_before = (self.root / "history" / HISTORY_FILENAME).read_bytes()
        store_files = sorted(p.read_bytes() for p in (self.root / STORE_RELATIVE_ROOT).rglob("*") if p.is_file())
        first = export_reviewed_label_dataset(runtime_root=self.root, output_dir=self.out)
        second_dir = self.root / "export2"
        second = export_reviewed_label_dataset(runtime_root=self.root, output_dir=second_dir)
        self.assertEqual(
            (self.out / "manifest.json").read_bytes(),
            (second_dir / "manifest.json").read_bytes(),
        )
        self.assertEqual(first["samples"][0]["cropSha256"], second["samples"][0]["cropSha256"])
        self.assertEqual((self.root / "history" / HISTORY_FILENAME).read_bytes(), history_before)
        after_store = sorted(p.read_bytes() for p in (self.root / STORE_RELATIVE_ROOT).rglob("*") if p.is_file())
        self.assertEqual(after_store, store_files)
        self.assertEqual(first["readiness"]["minTracksPerQuality"], MIN_TRACKS_PER_QUALITY)
        self.assertEqual(first["readiness"]["minSources"], MIN_SOURCES)
        self.assertEqual(first["readiness"]["status"], "INSUFFICIENT_EVIDENCE")

    def test_three_gold_tracks_from_two_sources_are_training_ready(self):
        self._confirmed("recReadyA")
        self._confirmed("recReadyB")
        top = self._desc("recReadyA", (9, 8, 7))
        # second gold track on recReadyA via extra resolved item sharing store original
        record = self.history.lookup("recReadyA")
        artifact = record["settlement"]["warehouseIdentityReview"]
        extra = dict(artifact["resolvedItems"][0])
        extra["trackId"] = "track-b"
        extra["evidenceId"] = top["evidenceId"]
        extra["sha256"] = top["sha256"]
        extra["sequenceIndex"] = 3
        artifact["resolvedItems"] = [artifact["resolvedItems"][0], extra]
        artifact["artifactFingerprint"] = artifact_fingerprint_for(artifact)
        self.history.update_record_transactional("recReadyA", {"settlement": {"warehouseIdentityReview": artifact}})
        manifest = export_reviewed_label_dataset(runtime_root=self.root, output_dir=self.root / "ready")
        gold = manifest["readiness"]["byQuality"]["金"]
        self.assertGreaterEqual(gold["trackCount"], 3)
        self.assertGreaterEqual(gold["sourceCount"], 2)
        self.assertEqual(manifest["readiness"]["status"], "TRAINING_READY")

    def test_cli_requires_explicit_paths(self):
        tools_dir = str(PROJECT_ROOT / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from export_warehouse_reviewed_labels import main as tool_main
        with self.assertRaises(SystemExit):
            tool_main([])


if __name__ == "__main__":
    unittest.main()
