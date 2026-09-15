# -*- coding: utf-8 -*-
"""Targeted post-match raw-capture and relocatable-export checks."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for entry in (str(PROJECT_ROOT / "app"), str(PROJECT_ROOT / "core")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from current_match import CurrentMatch
from canonical_match_record import build_canonical_match_record_v7
from match_export_bundle import MatchExportError, export_match_bundle
from match_import_bundle import import_match_bundle
from main_window import MainWindowBridge, OverlayVisibilityController
from settlement_capture_links import merge_capture_link
from settlement_evidence_store_v2 import KIND_MAIN, KIND_MANUAL_GAME, SettlementEvidenceStoreV2


def _png_bytes() -> bytes:
    image = np.zeros((18, 27, 3), dtype=np.uint8)
    image[:, :] = (12, 80, 160)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise AssertionError("test image encode failed")
    return encoded.tobytes()


class PostMatchCaptureExportTests(unittest.TestCase):
    def test_main_bridge_exposes_non_ocr_capture_action(self):
        class Overlay:
            Visible = False

            def Show(self):
                self.Visible = True

            def Hide(self):
                self.Visible = False

        bridge = MainWindowBridge(
            OverlayVisibilityController(Overlay()),
            save_settlement_screenshot_provider=lambda: {
                "ok": True,
                "status": "SAVED",
                "recognitionStarted": False,
                "relativePath": "evidence/settlement_v2/blobs/aa/test.png",
            },
        )
        response = bridge.dispatch({"action": "save_settlement_screenshot"})
        self.assertEqual(response["settlementScreenshot"]["status"], "SAVED")
        self.assertFalse(response["settlementScreenshot"]["recognitionStarted"])

    def test_main_bridge_exposes_unrestricted_game_capture_action(self):
        class Overlay:
            Visible = False

            def Show(self):
                self.Visible = True

            def Hide(self):
                self.Visible = False

        bridge = MainWindowBridge(
            OverlayVisibilityController(Overlay()),
            save_game_screenshot_provider=lambda: {
                "ok": True,
                "status": "SAVED",
                "recognitionStarted": False,
                "sceneGate": "NONE",
                "relativePath": "evidence/settlement_v2/blobs/aa/manual.png",
            },
        )
        response = bridge.dispatch({"action": "save_game_screenshot"})
        self.assertEqual(response["gameScreenshot"]["status"], "SAVED")
        self.assertEqual(response["gameScreenshot"]["sceneGate"], "NONE")
        self.assertFalse(response["gameScreenshot"]["recognitionStarted"])

    def test_capture_link_is_append_only_and_draft_safe(self):
        match = CurrentMatch()
        descriptor = SettlementEvidenceStoreV2(Path(tempfile.mkdtemp())).save_original(
            record_stable_key=match.id,
            kind=KIND_MAIN,
            image_bytes=_png_bytes(),
            captured_at="2026-09-07T12:00:00+08:00",
        )
        descriptor["captureSequence"] = 1
        descriptor["captureSource"] = "printwindow"
        descriptor["sourceFrameAt"] = "2026-09-07T12:00:00.123+08:00"
        links = merge_capture_link(
            None,
            descriptor,
            match_id=match.id,
            source_instance_id="desktop_test_instance",
            app_version="test",
            catalog_version="2026-08-13",
        )
        match.apply_facts({"settlementEvidence": links}, source="capture")
        canonical = match.to_canonical()
        self.assertEqual(canonical["lifecycleStatus"], "DRAFT")
        self.assertEqual(canonical["settlement"]["evidenceAttachments"]["matchId"], match.id)
        self.assertEqual(len(canonical["settlement"]["evidenceAttachments"]["captures"]), 1)
        cap = canonical["settlement"]["evidenceAttachments"]["captures"][0]
        self.assertEqual(cap.get("captureSequence"), 1)
        self.assertEqual(cap.get("captureSource"), "printwindow")
        self.assertEqual(cap.get("sourceFrameAt"), "2026-09-07T12:00:00.123+08:00")
        self.assertIsNone(canonical["settlement"]["actualTotal"])

    def test_manual_game_capture_is_an_exportable_draft_attachment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            data_root = root / "runtime"
            data_root.mkdir()
            history = data_root / "history.json"
            store = SettlementEvidenceStoreV2(data_root)
            descriptor = store.save_original(
                record_stable_key="manual_match",
                kind=KIND_MANUAL_GAME,
                image_bytes=_png_bytes(),
                captured_at="2026-09-07T12:00:00+08:00",
                coverage_mode="unspecified",
            )
            record = build_canonical_match_record_v7(
                match_id="manual_match",
                played_at="2026-09-07T12:00:00+08:00",
                lifecycle_status="DRAFT",
                source="test-manual-capture",
                environment={"venue": "test", "box": "test"},
            )
            record["settlement"]["evidenceAttachments"] = {
                "matchId": "manual_match",
                "captures": [descriptor],
            }
            history.write_text(json.dumps({"records": [record]}, ensure_ascii=False), encoding="utf-8")
            output = root / "manual.zip"
            result = export_match_bundle(
                history_path=history,
                data_root=data_root,
                output_path=output,
            )
            self.assertEqual(result["recordCount"], 1)
            self.assertEqual(result["imageCount"], 1)
            with zipfile.ZipFile(output) as archive:
                records = json.loads(archive.read("records.json"))
                capture = records["records"][0]["settlement"]["exportedCaptures"][0]
                self.assertEqual(capture["kind"], KIND_MANUAL_GAME)
                self.assertTrue(archive.read(capture["packageFile"]))

    def test_zip_contains_records_originals_and_relocates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            data_root = root / "runtime"
            data_root.mkdir()
            history = data_root / "history.json"
            store = SettlementEvidenceStoreV2(data_root)
            payload = _png_bytes()
            first = store.save_original(record_stable_key="match_a", kind=KIND_MAIN, image_bytes=payload)
            second = store.save_original(record_stable_key="match_b", kind=KIND_MAIN, image_bytes=payload)
            history.write_text(json.dumps({
                "version": "v0.67-runtime",
                "schemaVersion": 6,
                "records": [
                    {"id": "match_a", "lifecycleStatus": "DRAFT", "playedAt": "2026-09-07T12:00:00+08:00",
                     "settlement": {"evidenceAttachments": {"captures": [first]}}},
                    {"id": "match_b", "lifecycleStatus": "DRAFT", "playedAt": "2026-09-07T12:01:00+08:00",
                     "settlement": {"evidenceAttachments": {"captures": [second]}}},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            output = root / "delivery" / "matches.zip"
            result = export_match_bundle(
                history_path=history,
                data_root=data_root,
                output_path=output,
                record_ids=["match_a", "match_b"],
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["recordCount"], 2)
            self.assertEqual(result["imageCount"], 1)  # blob is safely deduplicated
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("records.json", names)
                manifest = json.loads(archive.read("manifest.json"))
                records = json.loads(archive.read("records.json"))
                self.assertEqual(manifest["recordCount"], 2)
                image_names = [name for name in names if name.endswith(".png")]
                self.assertEqual(len(image_names), 1)
                decoded = cv2.imdecode(np.frombuffer(archive.read(image_names[0]), dtype=np.uint8), cv2.IMREAD_COLOR)
                self.assertIsNotNone(decoded)
                serialized = json.dumps(records, ensure_ascii=False)
                self.assertNotIn("D:\\\\", serialized)
                self.assertNotIn("/runtime/", serialized)
                unpacked = root / "unpacked"
                archive.extractall(unpacked)
                rel = Path(image_names[0])
                self.assertTrue((unpacked / rel).is_file())

    def test_missing_original_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            data_root = root / "runtime"
            data_root.mkdir()
            history = data_root / "history.json"
            store = SettlementEvidenceStoreV2(data_root)
            descriptor = store.save_original(record_stable_key="match_missing", kind=KIND_MAIN, image_bytes=_png_bytes())
            (data_root / descriptor["relativePath"]).unlink()
            history.write_text(json.dumps({"records": [{"id": "match_missing", "playedAt": "2026-09-07T12:00:00+08:00"}]}), encoding="utf-8")
            with self.assertRaises(MatchExportError):
                export_match_bundle(history_path=history, data_root=data_root, output_path=root / "bad.zip")

    def test_bundle_import_keeps_record_attachment_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source_data = root / "source-runtime"
            source_data.mkdir()
            source_history = source_data / "history.json"
            source_store = SettlementEvidenceStoreV2(source_data)
            descriptor = source_store.save_original(
                record_stable_key="match_import_001",
                kind=KIND_MAIN,
                image_bytes=_png_bytes(),
                captured_at="2026-09-07T12:00:00+08:00",
            )
            record = build_canonical_match_record_v7(
                match_id="match_import_001",
                played_at="2026-09-07T12:00:00+08:00",
                lifecycle_status="DRAFT",
                source="test-import",
                environment={"venue": "test", "box": "test"},
            )
            record["settlement"]["evidenceAttachments"] = {
                "matchId": "match_import_001",
                "sourceInstanceId": "desktop_test",
                "captures": [descriptor],
            }
            source_history.write_text(json.dumps({"records": [record]}, ensure_ascii=False), encoding="utf-8")
            bundle = root / "bundle.zip"
            export_match_bundle(
                history_path=source_history,
                data_root=source_data,
                output_path=bundle,
            )

            target_data = root / "target-runtime"
            target_data.mkdir()
            target_history = target_data / "history.json"
            first = import_match_bundle(
                history_path=target_history,
                data_root=target_data,
                input_path=bundle,
            )
            self.assertEqual(first["importedRecordCount"], 1)
            self.assertEqual(first["skippedRecordCount"], 0)
            imported = json.loads(target_history.read_text(encoding="utf-8"))["records"][0]
            self.assertEqual(imported["id"], "match_import_001")
            self.assertTrue(imported["settlement"]["exportedCaptures"])
            imported_path = target_data / imported["settlement"]["exportedCaptures"][0]["packageFile"]
            self.assertTrue(imported_path.is_file())

            second = import_match_bundle(
                history_path=target_history,
                data_root=target_data,
                input_path=bundle,
            )
            self.assertEqual(second["importedRecordCount"], 0)
            self.assertEqual(second["skippedRecordCount"], 1)


if __name__ == "__main__":
    unittest.main()
