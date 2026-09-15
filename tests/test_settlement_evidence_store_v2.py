"""Isolated tests for file-backed Settlement Evidence Store v2."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from runtime_data import runtime_data_paths
from settlement_evidence_store_v2 import (
    COVERAGE_PARTIAL,
    COVERAGE_UNPROVEN,
    KIND_MAIN,
    KIND_WAREHOUSE,
    STORE_RELATIVE_ROOT,
    SettlementEvidenceStoreError,
    SettlementEvidenceStoreV2,
)


def _encode(image: np.ndarray, ext: str) -> bytes:
    ok, buf = cv2.imencode(ext, image)
    if not ok or buf is None:
        raise RuntimeError(f"failed to encode {ext}")
    return buf.tobytes()


def _png(color=(12, 34, 56), size=(16, 10)) -> bytes:
    image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    image[:] = color
    return _encode(image, ".png")


def _jpeg(color=(70, 80, 90), size=(20, 12)) -> bytes:
    image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    image[:] = color
    return _encode(image, ".jpg")


class SettlementEvidenceStoreV2Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "runtime-root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.prod_paths = runtime_data_paths()
        self.prod_history = (
            self.prod_paths.history_path.read_bytes()
            if self.prod_paths.history_path.exists()
            else None
        )
        self.store = SettlementEvidenceStoreV2(self.root)

    def tearDown(self):
        after = (
            self.prod_paths.history_path.read_bytes()
            if self.prod_paths.history_path.exists()
            else None
        )
        self.assertEqual(after, self.prod_history)
        self.assertFalse((PROJECT_ROOT / STORE_RELATIVE_ROOT).exists())
        self._tmp.cleanup()

    def _tmp_files(self) -> list[Path]:
        return [path for path in self.root.rglob("*") if path.is_file() and ".tmp-" in path.name]

    def test_png_and_jpeg_round_trip_hash_size_and_mime(self):
        png = _png()
        jpg = _jpeg()
        png_desc = self.store.save_original(
            record_stable_key="recA",
            kind=KIND_MAIN,
            image_bytes=png,
            captured_at="2026-08-25T12:00:00Z",
            coverage_status=COVERAGE_UNPROVEN,
        )
        jpg_desc = self.store.save_original(
            record_stable_key="recA",
            kind=KIND_WAREHOUSE,
            image_bytes=jpg,
            captured_at="2026-08-25T12:01:00Z",
            coverage_status=COVERAGE_PARTIAL,
        )
        self.assertEqual(self.store.load_original(png_desc), png)
        self.assertEqual(self.store.load_original(jpg_desc), jpg)
        self.assertEqual(png_desc["sha256"], hashlib.sha256(png).hexdigest())
        self.assertEqual(jpg_desc["sha256"], hashlib.sha256(jpg).hexdigest())
        self.assertEqual(png_desc["byteSize"], len(png))
        self.assertEqual(jpg_desc["byteSize"], len(jpg))
        self.assertEqual(png_desc["mimeType"], "image/png")
        self.assertEqual(jpg_desc["mimeType"], "image/jpeg")
        self.assertEqual((png_desc["width"], png_desc["height"]), (16, 10))
        self.assertEqual((jpg_desc["width"], jpg_desc["height"]), (20, 12))
        self.assertEqual(png_desc["storageMode"], "file")
        self.assertFalse(Path(png_desc["relativePath"]).is_absolute())
        self.assertEqual(png_desc["coverageStatus"], COVERAGE_UNPROVEN)
        self.assertEqual(jpg_desc["coverageStatus"], COVERAGE_PARTIAL)
        self.assertNotEqual(png_desc["coverageStatus"], "COMPLETE")

    def test_same_bytes_dedupe_across_records(self):
        payload = _png((1, 2, 3))
        first = self.store.save_original(record_stable_key="rec1", kind=KIND_MAIN, image_bytes=payload)
        second = self.store.save_original(record_stable_key="rec2", kind=KIND_MAIN, image_bytes=payload)
        third = self.store.save_original(record_stable_key="rec1", kind=KIND_MAIN, image_bytes=payload)
        blob_files = list((self.root / "evidence" / "settlement_v2" / "blobs").rglob("*.png"))
        self.assertEqual(len(blob_files), 1)
        self.assertEqual(first["relativePath"], second["relativePath"])
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["evidenceId"], third["evidenceId"])
        self.assertEqual(len(self.store.list_record_evidence("rec1")), 1)
        self.assertEqual(len(self.store.list_record_evidence("rec2")), 1)

    def test_invalid_bytes_leave_no_files(self):
        before = {path for path in self.root.rglob("*") if path.is_file()}
        with self.assertRaises(SettlementEvidenceStoreError) as raised:
            self.store.save_original(record_stable_key="recX", kind=KIND_MAIN, image_bytes=b"not-an-image")
        self.assertEqual(raised.exception.code, "INVALID_IMAGE")
        with self.assertRaises(SettlementEvidenceStoreError):
            self.store.save_original(record_stable_key="recX", kind=KIND_MAIN, image_bytes=b"\x89PNG\r\n\x1a\ntrunc")
        after = {path for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(self._tmp_files(), [])

    def test_path_traversal_and_complete_are_rejected(self):
        payload = _png()
        for bad in ("../escape", "a/b", "a\\b", "..", "", "C:abs", "rec/../x"):
            with self.assertRaises(SettlementEvidenceStoreError):
                self.store.save_original(record_stable_key=bad, kind=KIND_MAIN, image_bytes=payload)
        with self.assertRaises(SettlementEvidenceStoreError) as raised:
            self.store.save_original(
                record_stable_key="recOk",
                kind="settlement",
                image_bytes=payload,
            )
        self.assertEqual(raised.exception.code, "INVALID_KIND")
        with self.assertRaises(SettlementEvidenceStoreError) as raised:
            self.store.save_original(
                record_stable_key="recOk",
                kind=KIND_MAIN,
                image_bytes=payload,
                coverage_status="COMPLETE",
            )
        self.assertEqual(raised.exception.code, "INVALID_COVERAGE_STATUS")
        self.assertFalse((self.root / "evidence").exists())

    def test_write_failure_leaves_no_final_or_temp_files(self):
        payload = _png((9, 8, 7))

        def boom(*_args, **_kwargs):
            raise OSError("simulated replace failure")

        with mock.patch.object(self.store, "_atomic_write_bytes", side_effect=boom):
            with self.assertRaises(OSError):
                self.store.save_original(record_stable_key="recFail", kind=KIND_MAIN, image_bytes=payload)
        leftovers = [path for path in self.root.rglob("*") if path.is_file()]
        self.assertEqual(leftovers, [])
        self.assertEqual(self._tmp_files(), [])

    def test_verify_detects_missing_and_hash_mismatch(self):
        payload = _png((4, 5, 6))
        descriptor = self.store.save_original(record_stable_key="recV", kind=KIND_MAIN, image_bytes=payload)
        ok = self.store.verify(descriptor)
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["status"], "OK")
        blob = self.root / descriptor["relativePath"]
        blob.unlink()
        missing = self.store.verify(descriptor)
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["status"], "MISSING")
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(b"corrupted-not-original")
        mismatch = self.store.verify(descriptor)
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["status"], "HASH_MISMATCH")

    def test_existing_blob_mismatch_is_fail_closed(self):
        payload = _png((11, 22, 33))
        digest = hashlib.sha256(payload).hexdigest()
        dest = self.root / "evidence" / "settlement_v2" / "blobs" / digest[:2] / f"{digest}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"wrong-bytes-same-name")
        with self.assertRaises(SettlementEvidenceStoreError) as raised:
            self.store.save_original(record_stable_key="recConflict", kind=KIND_MAIN, image_bytes=payload)
        self.assertEqual(raised.exception.code, "BLOB_HASH_CONFLICT")
        self.assertEqual(dest.read_bytes(), b"wrong-bytes-same-name")

    def test_constructor_requires_explicit_absolute_root(self):
        with self.assertRaises(SettlementEvidenceStoreError):
            SettlementEvidenceStoreV2("")
        with self.assertRaises(SettlementEvidenceStoreError):
            SettlementEvidenceStoreV2("relative/root")

    def test_does_not_touch_production_or_history(self):
        payload = _png((3, 3, 3))
        self.store.save_original(record_stable_key="recIso", kind=KIND_MAIN, image_bytes=payload)
        listed = self.store.list_record_evidence("recIso")
        self.assertEqual(len(listed), 1)
        self.assertTrue(str(self.root) in str((self.root / listed[0]["relativePath"]).resolve()))
        self.assertNotIn(str(self.prod_paths.root), str((self.root / listed[0]["relativePath"]).resolve()))


if __name__ == "__main__":
    unittest.main()
