import hashlib
import json
import os
import unittest
from pathlib import Path
import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "assets" / "catalog_065.json"
MANIFEST_PATH = PROJECT_ROOT / "assets" / "items" / "catalog_reference_manifest_v1.json"
CROPS_DIR = PROJECT_ROOT / "assets" / "items" / "reference_crops_v1"


class TestCatalogReferenceManifestV1(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CATALOG_PATH.is_file(), f"catalog_065.json must exist at {CATALOG_PATH}")
        self.assertTrue(MANIFEST_PATH.is_file(), f"Manifest must exist at {MANIFEST_PATH}")
        
        self.catalog_data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.manifest_data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.catalog_by_id = {item["Id"]: item for item in self.catalog_data}

    def test_manifest_structure_and_counts(self):
        records = self.manifest_data.get("records", [])
        self.assertEqual(len(records), 200, "Manifest must have exactly 200 records")
        self.assertEqual(self.manifest_data.get("totalRecords"), 200)
        
        recovered_count = self.manifest_data.get("recoveredCount", 0)
        unresolved_count = self.manifest_data.get("unresolvedCount", 0)
        self.assertEqual(recovered_count + unresolved_count, 200, "Recovered + unresolved must equal 200")
        self.assertGreater(recovered_count, 100, "Must recover substantial deterministic catalog items")

    def test_recovered_entries_provenance_and_integrity(self):
        records = self.manifest_data.get("records", [])
        seen_slots = {}
        
        for entry in records:
            cid = entry["catalogId"]
            self.assertIn(cid, self.catalog_by_id, f"Manifest entry {cid} must exist in catalog_065.json")
            cat_item = self.catalog_by_id[cid]
            
            self.assertEqual(entry["name"], cat_item["Name"])
            self.assertEqual(entry["quality"], cat_item["Quality"])
            self.assertEqual(entry["widthCells"], cat_item["Width"])
            self.assertEqual(entry["heightCells"], cat_item["Height"])
            
            status = entry["status"]
            self.assertIn(status, ["RECOVERED_DETERMINISTIC", "MISSING_UNRESOLVED"])
            
            if status == "RECOVERED_DETERMINISTIC":
                # Check source screenshot
                src_rel = entry["sourceScreenshot"]
                self.assertIsNotNone(src_rel)
                src_path = PROJECT_ROOT / src_rel
                self.assertTrue(src_path.is_file(), f"Source screenshot {src_path} must exist")
                
                src_bytes = src_path.read_bytes()
                expected_src_sha = hashlib.sha256(src_bytes).hexdigest()
                self.assertEqual(entry["sourceScreenshotSha256"], expected_src_sha)
                
                # Check bbox bounds
                src_img = cv2.imdecode(np.frombuffer(src_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                h_img, w_img = src_img.shape[:2]
                bx, by, bw, bh = entry["bbox"]
                self.assertGreaterEqual(bx, 0)
                self.assertGreaterEqual(by, 0)
                self.assertLessEqual(bx + bw, w_img)
                self.assertLessEqual(by + bh, h_img)
                self.assertGreater(bw, 100)
                self.assertGreater(bh, 100)
                
                # Check crop file
                crop_rel = entry["cropRelativePath"]
                self.assertIsNotNone(crop_rel)
                crop_path = PROJECT_ROOT / crop_rel
                self.assertTrue(crop_path.is_file(), f"Crop file {crop_path} must exist")
                
                crop_bytes = crop_path.read_bytes()
                expected_crop_sha = hashlib.sha256(crop_bytes).hexdigest()
                self.assertEqual(entry["cropSha256"], expected_crop_sha)
                
                # Check slot collision uniqueness
                slot_key = (src_rel, entry["slotRow"], entry["slotCol"])
                if slot_key in seen_slots:
                    self.fail(f"Duplicate slot assignment: {slot_key} assigned to both {seen_slots[slot_key]} and {cid}")
                seen_slots[slot_key] = cid
            else:
                self.assertIsNotNone(entry.get("reason"), f"Unresolved entry {cid} must have a reason")

    def test_target_objects_fish_and_instrument_ready(self):
        records_by_id = {r["catalogId"]: r for r in self.manifest_data.get("records", [])}
        
        # 1. 绝对是亲手钓的鱼 (image10-0-0)
        self.assertIn("image10-0-0", records_by_id)
        fish = records_by_id["image10-0-0"]
        self.assertEqual(fish["name"], "绝对是亲手钓的鱼")
        self.assertEqual(fish["status"], "RECOVERED_DETERMINISTIC")
        fish_crop_path = PROJECT_ROOT / fish["cropRelativePath"]
        self.assertTrue(fish_crop_path.is_file())
        
        # 2. 万有星仪 (image27-0-2)
        self.assertIn("image27-0-2", records_by_id)
        inst = records_by_id["image27-0-2"]
        self.assertEqual(inst["name"], "万有星仪")
        self.assertEqual(inst["status"], "RECOVERED_DETERMINISTIC")
        inst_crop_path = PROJECT_ROOT / inst["cropRelativePath"]
        self.assertTrue(inst_crop_path.is_file())


if __name__ == "__main__":
    unittest.main()
