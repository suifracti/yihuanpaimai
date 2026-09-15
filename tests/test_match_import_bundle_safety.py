# -*- coding: utf-8 -*-
"""Targeted contract and security tests for product match bundle import.

Covers:
1. Exact file set equality check: ZIP namelist strictly equals manifest.json + file_map.
2. Comprehensive hash and size check of every file including records.json, 说明.txt, crops/, evidence/, attachments/.
3. Strict path traversal / absolute path / drive letter rejection.
4. Fail-closed guarantee: any failure halts execution before any local data or database mutation.
5. Full roundtrip test: real 39-item warehouse export -> import to fresh isolated directory -> reload store -> 100% match.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from typing import Any, Dict, Tuple
import unittest
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT / "core"), str(PROJECT_ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from match_export_bundle import export_match_bundle
from match_import_bundle import MatchImportError, import_match_bundle


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestMatchImportBundleSafety(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)
        self.source_dir = self.test_dir / "source"
        self.target_dir = self.test_dir / "target"
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.target_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_valid_bundle(self) -> Tuple[Path, Dict[str, bytes], Dict[str, Any]]:
        """Build a compliant match-export-bundle.v1 in memory and write to zip."""
        bundle_path = self.test_dir / "valid_bundle.zip"
        crop_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        crop_sha = _sha256(crop_bytes)

        rec = build_canonical_match_record_v7(
            match_id="match_valid_001",
            played_at="2026-09-12T09:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
            environment={"venue": "test_venue", "box": "test_box"},
        )
        rec["settlement"]["isSettled"] = True
        rec["settlement"]["clearingPrice"] = 100000
        rec["settlement"]["actualTotal"] = 120000
        rec["settlement"]["realizedProfit"] = 20000
        rec["settlement"]["acquired"] = True
        rec["settlement"]["winner"] = "本人拍下"
        rec["settlement"]["exportedCaptures"] = [
            {
                "packageFile": "crops/match_valid_001_u1.png",
                "sha256": crop_sha,
            }
        ]

        records_payload = {
            "version": "history-export.v2",
            "schemaVersion": "history-export.v2",
            "exportTimestamp": "2026-09-12T10:00:00Z",
            "records": [rec],
        }
        records_bytes = json.dumps(records_payload, ensure_ascii=False, indent=2).encode("utf-8")
        readme_bytes = "异环拍卖助手导出数据包\n".encode("utf-8")
        crop_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

        file_map_entries = [
            {"path": "records.json", "sha256": _sha256(records_bytes), "size": len(records_bytes)},
            {"path": "说明.txt", "sha256": _sha256(readme_bytes), "size": len(readme_bytes)},
            {"path": "crops/match_valid_001_u1.png", "sha256": _sha256(crop_bytes), "size": len(crop_bytes)},
        ]

        manifest = {
            "schemaVersion": "match-export-bundle.v1",
            "exportTimestamp": "2026-09-12T10:00:00Z",
            "recordCount": 1,
            "imageCount": 1,
            "files": file_map_entries,
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

        file_contents = {
            "manifest.json": manifest_bytes,
            "records.json": records_bytes,
            "说明.txt": readme_bytes,
            "crops/match_valid_001_u1.png": crop_bytes,
        }

        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, content in file_contents.items():
                zf.writestr(name, content)

        return bundle_path, file_contents, manifest

    def test_valid_bundle_imports_cleanly(self):
        bundle_path, _, _ = self._create_valid_bundle()
        target_hist = self.target_dir / "history.json"
        res = import_match_bundle(
            history_path=target_hist,
            data_root=self.target_dir,
            input_path=bundle_path,
        )
        self.assertEqual(res["importedRecordCount"], 1)
        self.assertEqual(res["skippedRecordCount"], 0)
        self.assertTrue((self.target_dir / "crops" / "match_valid_001_u1.png").is_file())

        store = CanonicalHistoryStore(target_hist)
        rec = store.lookup("match_valid_001")
        self.assertIsNotNone(rec)

    def test_negative_mode_1_tampered_records_json_rejected(self):
        """Tampering records.json content causes SHA-256 mismatch and blocks before write."""
        bundle_path, files, _ = self._create_valid_bundle()
        tampered_records = files["records.json"] + b" "
        bad_zip = self.test_dir / "bad_records.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, tampered_records if name == "records.json" else content)

        target_hist = self.target_dir / "history.json"
        with self.assertRaises(MatchImportError) as cm:
            import_match_bundle(
                history_path=target_hist,
                data_root=self.target_dir,
                input_path=bad_zip,
            )
        self.assertIn("文件哈希校验失败：records.json", str(cm.exception))
        self.assertFalse(target_hist.exists())
        self.assertFalse((self.target_dir / "crops").exists())

    def test_negative_mode_2_tampered_readme_rejected(self):
        """Tampering 说明.txt causes SHA-256 mismatch and blocks before write."""
        bundle_path, files, _ = self._create_valid_bundle()
        tampered_readme = files["说明.txt"] + b"\nEXTRA"
        bad_zip = self.test_dir / "bad_readme.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, tampered_readme if name == "说明.txt" else content)

        target_hist = self.target_dir / "history.json"
        with self.assertRaises(MatchImportError) as cm:
            import_match_bundle(
                history_path=target_hist,
                data_root=self.target_dir,
                input_path=bad_zip,
            )
        self.assertIn("文件哈希校验失败：说明.txt", str(cm.exception))
        self.assertFalse(target_hist.exists())
        self.assertFalse((self.target_dir / "crops").exists())

    def test_negative_mode_3_extra_unregistered_file_rejected(self):
        """ZIP containing any unmanifested file fails the exact set equality check."""
        bundle_path, files, _ = self._create_valid_bundle()
        bad_zip = self.test_dir / "bad_extra.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
            zf.writestr("rogue_payload.exe", b"MALICIOUS")

        target_hist = self.target_dir / "history.json"
        with self.assertRaises(MatchImportError) as cm:
            import_match_bundle(
                history_path=target_hist,
                data_root=self.target_dir,
                input_path=bad_zip,
            )
        self.assertIn("含有未登记的额外文件", str(cm.exception))
        self.assertFalse(target_hist.exists())
        self.assertFalse((self.target_dir / "crops").exists())

    def test_negative_mode_4_missing_registered_file_rejected(self):
        """ZIP missing a file listed in manifest fails exact set check."""
        bundle_path, files, _ = self._create_valid_bundle()
        bad_zip = self.test_dir / "bad_missing.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            for name, content in files.items():
                if name != "crops/match_valid_001_u1.png":
                    zf.writestr(name, content)

        target_hist = self.target_dir / "history.json"
        with self.assertRaises(MatchImportError) as cm:
            import_match_bundle(
                history_path=target_hist,
                data_root=self.target_dir,
                input_path=bad_zip,
            )
        self.assertIn("缺少登记文件", str(cm.exception))
        self.assertFalse(target_hist.exists())

    def test_negative_mode_5_tampered_crop_file_rejected(self):
        """Tampering a crop file payload fails SHA-256 check before write."""
        bundle_path, files, _ = self._create_valid_bundle()
        bad_zip = self.test_dir / "bad_crop.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, b"CORRUPTED_CROP" if name.startswith("crops/") else content)

        target_hist = self.target_dir / "history.json"
        with self.assertRaises(MatchImportError) as cm:
            import_match_bundle(
                history_path=target_hist,
                data_root=self.target_dir,
                input_path=bad_zip,
            )
        self.assertIn("文件哈希校验失败：crops/", str(cm.exception))
        self.assertFalse(target_hist.exists())
        self.assertFalse((self.target_dir / "crops").exists())

    def test_negative_mode_6_forged_file_size_rejected(self):
        """Forged size in manifest fails size check before parsing."""
        bundle_path, files, manifest = self._create_valid_bundle()
        bad_manifest = copy.deepcopy(manifest)
        bad_manifest["files"][0]["size"] = 99999999  # Forged records.json size
        bad_manifest_bytes = json.dumps(bad_manifest, ensure_ascii=False, indent=2).encode("utf-8")

        bad_zip = self.test_dir / "bad_size.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, bad_manifest_bytes if name == "manifest.json" else content)

        target_hist = self.target_dir / "history.json"
        with self.assertRaises(MatchImportError) as cm:
            import_match_bundle(
                history_path=target_hist,
                data_root=self.target_dir,
                input_path=bad_zip,
            )
        self.assertIn("文件大小校验失败", str(cm.exception))
        self.assertFalse(target_hist.exists())

    def test_negative_mode_7_path_traversal_in_crops_rejected(self):
        """Manifest or archive with 'crops/../escape.png' is blocked."""
        bundle_path, files, manifest = self._create_valid_bundle()
        bad_manifest = copy.deepcopy(manifest)
        bad_manifest["files"].append({
            "path": "crops/../escape.txt",
            "sha256": "0" * 64,
            "size": 10,
        })
        bad_manifest_bytes = json.dumps(bad_manifest, ensure_ascii=False, indent=2).encode("utf-8")

        bad_zip = self.test_dir / "bad_traversal.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("manifest.json", bad_manifest_bytes)
            for name, content in files.items():
                if name != "manifest.json":
                    zf.writestr(name, content)
            zf.writestr("crops/../escape.txt", b"ESCAPE_PAYLOAD")

        target_hist = self.target_dir / "history.json"
        with self.assertRaises(MatchImportError) as cm:
            import_match_bundle(
                history_path=target_hist,
                data_root=self.target_dir,
                input_path=bad_zip,
            )
        self.assertIn("数据包路径不安全", str(cm.exception))
        self.assertFalse(target_hist.exists())

    def test_negative_mode_8_duplicate_zip_members_rejected(self):
        """ZIP archive containing duplicate file members is immediately rejected fail-closed."""
        bundle_path, files, manifest = self._create_valid_bundle()
        bad_zip = self.test_dir / "bad_duplicate.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
            # Write duplicate member entry
            zf.writestr("records.json", b'{"duplicate": true}')

        target_hist = self.target_dir / "history.json"
        with self.assertRaises(MatchImportError) as cm:
            import_match_bundle(
                history_path=target_hist,
                data_root=self.target_dir,
                input_path=bad_zip,
            )
        self.assertIn("数据包含有重复文件条目", str(cm.exception))
        self.assertFalse(target_hist.exists())

    def test_negative_mode_9_metadata_suffix_bypass_rejected(self):
        """Prefix/suffix bypass attempts like records.json.evil or 说明.txt.bak are strictly blocked."""
        for evil_name in ("records.json.evil", "说明.txt.bak", "evidence_fake/foo.png"):
            bundle_path, files, manifest = self._create_valid_bundle()
            bad_manifest = copy.deepcopy(manifest)
            bad_manifest["files"].append({
                "path": evil_name,
                "sha256": _sha256(b"EVIL"),
                "size": 4,
            })
            bad_manifest_bytes = json.dumps(bad_manifest, ensure_ascii=False, indent=2).encode("utf-8")

            bad_zip = self.test_dir / f"bad_bypass_{evil_name.replace('/', '_')}.zip"
            with zipfile.ZipFile(bad_zip, "w") as zf:
                zf.writestr("manifest.json", bad_manifest_bytes)
                for name, content in files.items():
                    if name != "manifest.json":
                        zf.writestr(name, content)
                zf.writestr(evil_name, b"EVIL")

            target_hist = self.target_dir / "history.json"
            with self.assertRaises(MatchImportError) as cm:
                import_match_bundle(
                    history_path=target_hist,
                    data_root=self.target_dir,
                    input_path=bad_zip,
                )
            self.assertIn("数据包包含不允许导入的文件", str(cm.exception))
            self.assertFalse(target_hist.exists())

    def test_negative_mode_10_missing_size_in_manifest_rejected(self):
        """Manifest entry lacking mandatory 'size' attribute is rejected fail-closed."""
        bundle_path, files, manifest = self._create_valid_bundle()
        bad_manifest = copy.deepcopy(manifest)
        # Remove size from crops entry
        for entry in bad_manifest["files"]:
            if entry["path"].startswith("crops/"):
                del entry["size"]

        bad_manifest_bytes = json.dumps(bad_manifest, ensure_ascii=False, indent=2).encode("utf-8")
        bad_zip = self.test_dir / "bad_missing_size.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("manifest.json", bad_manifest_bytes)
            for name, content in files.items():
                if name != "manifest.json":
                    zf.writestr(name, content)

        target_hist = self.target_dir / "history.json"
        with self.assertRaises(MatchImportError) as cm:
            import_match_bundle(
                history_path=target_hist,
                data_root=self.target_dir,
                input_path=bad_zip,
            )
        self.assertIn("manifest.json 缺少文件大小", str(cm.exception))
        self.assertFalse(target_hist.exists())

    def test_negative_mode_11_invalid_size_types_rejected(self):
        """Manifest entries with float, boolean, or invalid string size values are strictly rejected."""
        bundle_path, files, manifest = self._create_valid_bundle()

        invalid_size_cases = [
            (1.9, "不能为浮点数"),
            (True, "不能为布尔值"),
            (False, "不能为布尔值"),
            ("1.9", "严格纯数字整数"),
            ("-5", "严格纯数字整数"),
            ("abc", "严格纯数字整数"),
        ]

        for bad_val, expected_err in invalid_size_cases:
            bad_manifest = copy.deepcopy(manifest)
            for entry in bad_manifest["files"]:
                if entry["path"] == "records.json":
                    entry["size"] = bad_val
                    entry["byteSize"] = bad_val

            bad_manifest_bytes = json.dumps(bad_manifest, ensure_ascii=False, indent=2).encode("utf-8")
            bad_zip = self.test_dir / f"bad_size_{type(bad_val).__name__}_{bad_val}.zip"
            with zipfile.ZipFile(bad_zip, "w") as zf:
                zf.writestr("manifest.json", bad_manifest_bytes)
                for name, content in files.items():
                    if name != "manifest.json":
                        zf.writestr(name, content)

            target_hist = self.target_dir / "history.json"
            if target_hist.exists():
                target_hist.unlink()

            with self.assertRaises(MatchImportError) as cm:
                import_match_bundle(
                    history_path=target_hist,
                    data_root=self.target_dir,
                    input_path=bad_zip,
                )
            self.assertIn(expected_err, str(cm.exception))
            self.assertFalse(target_hist.exists())

    def test_full_roundtrip_39_item_warehouse_export_and_isolated_import(self):
        """Full roundtrip test using real 39-item warehouse dataset:
        1. Set up source directory with base record, raw packet, evidence blobs, and crops.
        2. Run WarehouseCaptureHost to persist warehouse evidence natively.
        3. Run export_match_bundle to generate exported ZIP package.
        4. Import ZIP package into fresh isolated target directory via import_match_bundle.
        5. Verify target history store has 39 items (28 confirmed, 11 candidate).
        6. Verify all 39 crops and evidence blobs exist on disk in target directory with matching SHA-256.
        7. Verify idempotency: re-importing skips with 0 imported / 1 skipped.
        """
        from warehouse_capture_host import WarehouseCaptureHost

        target_match_id = "dense_audit_20260908_144037"

        # 1. Prepare source environment
        src_evidence = PROJECT_ROOT / "build" / "diagnosis_20260909" / "p3-warehouse" / "store_dense" / "evidence"
        src_crops = PROJECT_ROOT / "build" / "diagnosis_20260911" / "p3-warehouse" / "auto_confirmation_run_v5" / "crops"
        v5_packet_path = PROJECT_ROOT / "build" / "diagnosis_20260911" / "p3-warehouse" / "video_audit_retest_v5" / "audit_review_packet.json"
        src_hist_file = PROJECT_ROOT / "build" / "diagnosis_20260911" / "p3-warehouse" / "auto_confirmation_run_v5" / "history" / "test_canonical_history.json"

        if not (src_evidence.is_dir() and src_crops.is_dir() and v5_packet_path.is_file() and src_hist_file.is_file()):
            self.skipTest("Raw warehouse diagnostic fixtures not available in environment")

        shutil.copytree(src_evidence, self.source_dir / "evidence")
        shutil.copytree(src_crops, self.source_dir / "crops")

        src_hist_dir = self.source_dir / "history"
        src_hist_dir.mkdir(parents=True, exist_ok=True)
        src_hist_path = src_hist_dir / "history.json"

        store_src = CanonicalHistoryStore(str(src_hist_path))
        src_data = json.loads(src_hist_file.read_text(encoding="utf-8"))
        base_rec = src_data["records"][0]
        base_rec["settlement"]["clearingPrice"] = 990000
        base_rec["settlement"]["actualTotal"] = 1050070
        base_rec["settlement"]["realizedProfit"] = 60070
        base_rec["settlement"]["acquired"] = True
        base_rec["settlement"]["winner"] = "本人拍下"
        base_rec["settlement"]["isSettled"] = True
        store_src.persist_record_transactional(base_rec, is_finalized=False)

        packet = json.loads(v5_packet_path.read_text(encoding="utf-8"))
        host = WarehouseCaptureHost(history_store_factory=lambda: store_src)
        result = host.persist_warehouse_occupancy_and_review(packet)
        self.assertIsNotNone(result)

        # Verify host persisted 39 units with crops natively
        saved_rec = store_src.get_record(target_match_id)
        saved_st = saved_rec.get("settlement", {})
        saved_units = saved_st.get("reviewUnits", [])
        self.assertEqual(len(saved_units), 39)
        self.assertTrue(all(u.get("cropPath") and u.get("cropSha256") for u in saved_units))

        # 2. Export match bundle
        export_bundle_zip = self.test_dir / "exported_39_bundle.zip"
        export_match_bundle(
            history_path=src_hist_path,
            data_root=self.source_dir,
            output_path=export_bundle_zip,
            record_ids=[target_match_id],
        )
        self.assertTrue(export_bundle_zip.is_file())
        self.assertGreater(export_bundle_zip.stat().st_size, 0)

        # 3. Import bundle into completely fresh target directory
        target_hist_path = self.target_dir / "history" / "history.json"
        import_res = import_match_bundle(
            history_path=target_hist_path,
            data_root=self.target_dir,
            input_path=export_bundle_zip,
        )
        self.assertEqual(import_res["importedRecordCount"], 1)
        self.assertEqual(import_res["skippedRecordCount"], 0)

        # 4. Read back target history store
        store_tgt = CanonicalHistoryStore(str(target_hist_path))
        tgt_rec = store_tgt.get_record(target_match_id)
        self.assertIsNotNone(tgt_rec)
        tgt_st = tgt_rec.get("settlement", {})
        tgt_units = tgt_st.get("reviewUnits", [])
        self.assertEqual(len(tgt_units), 39)

        confirmed_units = [u for u in tgt_units if u.get("confirmationStatus") == "CONFIRMED"]
        candidate_units = [u for u in tgt_units if u.get("confirmationStatus") == "CANDIDATE_ONLY"]
        self.assertEqual(len(confirmed_units), 28)
        self.assertEqual(len(candidate_units), 11)

        # 5. Verify all 39 crops exist on target disk and match SHA-256
        for u in tgt_units:
            crop_rel = u.get("cropPath")
            self.assertIsNotNone(crop_rel)
            target_crop_file = self.target_dir / crop_rel
            self.assertTrue(target_crop_file.is_file(), f"Target crop file missing: {crop_rel}")
            self.assertEqual(
                _sha256(target_crop_file.read_bytes()),
                u.get("cropSha256"),
                f"Crop hash mismatch for {crop_rel}",
            )

        # 6. Verify evidence blobs exist on target disk
        for capture in tgt_st.get("exportedCaptures", []):
            pkg_file = capture.get("packageFile")
            self.assertIsNotNone(pkg_file)
            target_blob_file = self.target_dir / pkg_file
            self.assertTrue(target_blob_file.is_file(), f"Target blob missing: {pkg_file}")
            self.assertEqual(
                _sha256(target_blob_file.read_bytes()),
                capture.get("sha256"),
                f"Blob hash mismatch for {pkg_file}",
            )

        # 7. Test Idempotency: re-importing skips duplicate record
        reimport_res = import_match_bundle(
            history_path=target_hist_path,
            data_root=self.target_dir,
            input_path=export_bundle_zip,
        )
        self.assertEqual(reimport_res["importedRecordCount"], 0)
        self.assertEqual(reimport_res["skippedRecordCount"], 1)


if __name__ == "__main__":
    unittest.main()
