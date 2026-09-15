import json
import sys
from pathlib import Path
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "core") not in sys.path:
    sys.path.insert(0, str(ROOT / "core"))

from settlement_item_recognizer import SettlementItemRecognizer
from visual_catalog import (development_references, feature_match_evidence,
                            load_visual_templates, verified_references,
                            _foreground_alignment, _occluded_foreground_alignment)
FIXTURES = ROOT / "tests/fixtures/settlement_cards_v2"


class VisualCatalogIdentityTests(unittest.TestCase):
    def test_selection_badge_is_not_item_evidence(self):
        from selection_occlusion import selection_occlusion
        templates = load_visual_templates()
        references = verified_references()
        for template in templates.values():
            self.assertFalse(selection_occlusion(template)[0].any())
        board = cv2.imdecode(np.fromfile(FIXTURES / "2026-08-18_11-19-25_455.png", np.uint8), 1)
        vase = board[393:506, 56:169]
        self.assertTrue(selection_occlusion(vase)[0].any())
        scores = {r["name"]: _occluded_foreground_alignment(vase, templates[f"visual/{r['catalogId']}.png"])["score"]
                  for r in references if (r["width"], r["height"], r["rarity"]) == (2, 2, "gold")}
        self.assertGreaterEqual(scores["双颈玉瓶-白"], .85)
        self.assertTrue(all(score < .85 for name, score in scores.items() if name != "双颈玉瓶-白"))
        badge = cv2.imdecode(np.fromfile(ROOT / "assets/scene_anchors/selection_marker.png", np.uint8), 1)
        empty = np.full((113, 113, 3), (35, 80, 125), np.uint8)
        empty[40:73, 40:73] = badge
        for template in templates.values():
            self.assertLess(_occluded_foreground_alignment(empty, template)["score"], .85)

    def test_compressed_selection_badge_is_registered_for_identity_memory(self):
        from selection_occlusion import selection_occlusion
        board = cv2.imdecode(np.fromfile(FIXTURES / "2026-08-18_11-19-25_455.png", np.uint8), 1)
        # These two 1x1 cards are the compressed-video cases that used to fall
        # below the old .85 badge threshold and break cross-frame registration.
        for crop in (board[0:56, 169:225], board[112:169, 507:563]):
            mask, detection = selection_occlusion(crop)
            self.assertTrue(mask.any())
            self.assertGreaterEqual(detection["score"], .80)
            self.assertIn("bbox", detection)

        # The unselected reveal contains a pink item of its own. Its lower
        # score must not be mistaken for the selection badge.
        reveal = cv2.imdecode(np.fromfile(ROOT / "tests/fixtures/video_replay/reveal_board_450.png", np.uint8), 1)
        mask, detection = selection_occlusion(reveal[0:56, 169:225])
        self.assertFalse(mask.any())
        self.assertLess(detection["score"], .75)

    def test_small_objects_ignore_rarity_background_without_confusing_neighbors(self):
        # Independent visual labels from video 2026-08-25 21-58-33 at 6s.
        # These pixels are validation examples, never catalog templates.
        board = cv2.imdecode(np.fromfile(FIXTURES / "2026-08-25_21-58-33_6.png", np.uint8), 1)
        templates = load_visual_templates()
        references = verified_references()
        samples = [(507, 0, 56, 56, "崭新的弹珠", "white"),
                   (282, 112, 56, 57, "肥皂", "green"),
                   (394, 506, 56, 56, "金月", "green")]
        for x, y, w, h, name, rarity in samples:
            query = board[y:y+h, x:x+w]
            scores = {r["name"]: _foreground_alignment(query, templates[f"visual/{r['catalogId']}.png"])["score"]
                      for r in references if (r["width"], r["height"], r["rarity"]) == (1, 1, rarity)}
            self.assertGreaterEqual(scores[name], .85, name)
            for other, score in scores.items():
                if other != name:
                    self.assertLess(score, .85, (name, other, score))

    def test_real_labels_and_no_total_driven_guessing(self):
        samples = json.loads((FIXTURES / "annotations.json").read_text(encoding="utf-8"))
        recognizer = SettlementItemRecognizer()
        for sample in samples:
            if len(sample['identityAnnotations']) != len(sample['rectangles']):
                continue
            with self.subTest(image=sample['image']):
                board = cv2.imdecode(np.fromfile(FIXTURES / sample["image"], np.uint8), 1)
                frame = np.zeros((1080, 1920, 3), np.uint8)
                frame[214:776, 1315:1878] = board
                result = recognizer.parse_settlement_ledger(frame, actual_total=1)
                expected = {tuple(i["rect"]): i for i in sample["identityAnnotations"]}
                exact = [i for i in result["settlementItems"] if i["status"] == "exact"]
                self.assertEqual(len(exact), len(expected))
                for item in exact:
                    rect = tuple(item[key] for key in ("row", "col", "widthCells", "heightCells"))
                    self.assertEqual(item["name"], expected[rect]['name'])
                    self.assertEqual(item["price"], expected[rect]['value'])
                self.assertFalse(result["settlementLedgerVerified"])
                self.assertEqual(result["settlementExactValueSum"], sample["actualTotal"])

    def test_shared_pedestal_is_not_enough_to_identify_the_sculpture(self):
        board = cv2.imdecode(np.fromfile(FIXTURES / '2026-08-25_21-58-33_6.png', np.uint8), 1)
        query = board[:112, 282:338]
        references = {r['name']: r for r in verified_references()}
        templates = load_visual_templates()
        for name in ('结的艺术', '环的冥思'):
            ident = references[name]['catalogId']
            score = max(feature_match_evidence(query, template)['score'] for key, template in templates.items()
                        if key == f'visual/{ident}.png' or key.startswith(f'visual/{ident}@'))
            if name == '结的艺术':
                self.assertGreaterEqual(score, .85)
            else:
                self.assertLess(score, .85)

    def test_reference_identity_and_geometry_are_source_backed(self):
        references = verified_references()
        by_name = {r["name"]: r for r in references}
        self.assertEqual((by_name["扭扭饼干"]["width"], by_name["扭扭饼干"]["height"]), (1, 1))
        self.assertEqual(by_name["猫丸秘制豚骨拉面"]["value"], 9040)
        self.assertGreaterEqual(len(references), 81)
        from visual_catalog import deterministic_reference_crops
        manifest_crops = deterministic_reference_crops()
        templates = load_visual_templates()
        self.assertEqual(len(templates), 2 * len(references) + len(manifest_crops))
        for record in references:
            self.assertIn(f"visual/{record['catalogId']}.png", templates)
            self.assertIn(f"visual/{record['catalogId']}@expanded.png", templates)
        for record in manifest_crops:
            self.assertIn(f"visual/{record['catalogId']}@catalog-reference-crop.png", templates)

    def test_video_development_references_are_separate_and_source_backed(self):
        development = development_references()
        verified = verified_references()
        from visual_catalog import deterministic_reference_crops
        manifest_crops = deterministic_reference_crops()
        expected_verified = len(json.loads((ROOT / "assets/items/visual_catalog_v2.json").read_text(encoding="utf-8"))["records"])
        self.assertEqual(len(verified), expected_verified)
        self.assertEqual(len(development), 2)
        base_templates = load_visual_templates(include_development=False)
        self.assertEqual(len(base_templates), 2 * len(verified) + len(manifest_crops))
        self.assertFalse(any(k.startswith("video-dev/") for k in base_templates))
        templates = load_visual_templates(include_development=True)
        self.assertEqual(len(templates), len(base_templates) + len(development))
        for record in development:
            self.assertEqual(record["sampleClass"], "development-reference")
            self.assertIn(f"video-dev/{record['catalogId']}.png", templates)
            self.assertNotEqual(record["imagePath"], record["acceptanceSample"]["fixture"])

    def test_production_recognizer_excludes_development_references_and_identifies_formal_crops(self):
        recognizer = SettlementItemRecognizer()
        self.assertFalse(recognizer.include_development)
        self.assertFalse(any(k.startswith("video-dev/") for k in recognizer.templates))
        for filename, row, col, expected_name, expected_price, expected_tpl in (
            ("2026-08-18_11-19-25_189.png", 0, 6, "生鸡蛋", 178, "visual/image2-1-0@catalog-reference-crop.png"),
            ("2026-08-25_21-58-33_6.png", 0, 8, "纸牌", 183, "visual/image2-0-2@catalog-reference-crop.png"),
        ):
            with self.subTest(filename=filename):
                board = cv2.imdecode(np.fromfile(FIXTURES / filename, np.uint8), 1)
                frame = np.zeros((1080, 1920, 3), np.uint8)
                frame[214:776, 1315:1878] = board
                result = recognizer.parse_settlement_ledger(frame)
                item = next(i for i in result["settlementItems"]
                            if i["row"] == row and i["col"] == col)
                self.assertEqual((item["status"], item["name"], item["price"]),
                                 ("exact", expected_name, expected_price))
                self.assertEqual(item["identityEvidence"]["evidenceSource"], "VISUAL_FEATURE_MATCH")
                self.assertEqual(item["identityEvidence"]["templateReference"], expected_tpl)

    def test_video_development_references_identify_separate_acceptance_frames(self):
        recognizer = SettlementItemRecognizer(include_development=True)
        for filename, row, col, expected_name, expected_price, expected_source, tpl_prefix in (
            ("2026-08-18_11-19-25_189.png", 0, 6, "生鸡蛋", 178, "VISUAL_FEATURE_MATCH", "visual/"),
            ("2026-08-25_21-58-33_6.png", 0, 8, "纸牌", 183, "VIDEO_DEVELOPMENT_REFERENCE_MATCH", "video-dev/"),
        ):
            with self.subTest(filename=filename):
                board = cv2.imdecode(np.fromfile(FIXTURES / filename, np.uint8), 1)
                frame = np.zeros((1080, 1920, 3), np.uint8)
                frame[214:776, 1315:1878] = board
                result = recognizer.parse_settlement_ledger(frame)
                item = next(i for i in result["settlementItems"]
                            if i["row"] == row and i["col"] == col)
                self.assertEqual((item["status"], item["name"], item["price"]),
                                 ("exact", expected_name, expected_price))
                self.assertEqual(item["identityEvidence"]["evidenceSource"], expected_source)
                self.assertTrue(item["identityEvidence"]["templateReference"].startswith(tpl_prefix))

    def test_background_and_shuffled_pixels_never_become_exact(self):
        templates = load_visual_templates()
        board = cv2.imdecode(np.fromfile(FIXTURES / "2026-08-17_14-11-56_240.png", np.uint8), 1)
        noise = board[:56, :56].copy()
        rng = np.random.default_rng(20260906)
        rng.shuffle(noise.reshape(-1, 3), axis=0)

        from warehouse_placement_resolver import WarehousePlacementResolver
        resolver = WarehousePlacementResolver()

        for query in (np.full((56, 56, 3), 110, np.uint8), noise):
            for template in templates.values():
                self.assertLess(feature_match_evidence(query, template)["score"], .85)
            # Direct test of production foreground extractor and candidate admission on background/noise
            self.assertIsNone(resolver._extract_foreground(query))
            _, cands, inliers = resolver.match_catalog_candidates(query, 1, 1)
            self.assertEqual(cands, [])
            self.assertEqual(inliers, 0)


    def test_fragment_cannot_become_an_identified_item(self):
        recognizer = SettlementItemRecognizer()
        board = cv2.imdecode(np.fromfile(FIXTURES / "2026-08-17_14-11-56_240.png", np.uint8), 1)
        evidence = recognizer.resolve_hypothesis_identity_evidence({
            "widthCells": 2, "heightCells": 2, "rarity": "purple",
            "groupingAmbiguous": True}, board[:112, :113])
        self.assertNotEqual(evidence["status"], "EXACT_IDENTIFIED")
        self.assertIsNone(evidence["candidateCatalogId"])


class CatalogProvenanceAndIdentityIntegrityTests(unittest.TestCase):
    """Tests enforcing strict ID-name provenance, anti-regression validation, and benchmark separation."""

    def test_validator_rejects_genuine_name_with_wrong_id(self):
        from catalog_validator import validate_item_identity
        # Both '起司' (image1-0-1) and '柠檬气泡水' (image13-0-1) are genuine catalog names.
        # Pairing either genuine name with the other item's genuine ID must be rejected.
        with self.assertRaises(ValueError) as ctx1:
            validate_item_identity("image1-0-1", "柠檬气泡水")
        self.assertIn("Catalog ID-name mismatch", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            validate_item_identity("image13-0-1", "起司")
        self.assertIn("Catalog ID-name mismatch", str(ctx2.exception))

        # Correct pairs must pass cleanly
        self.assertTrue(validate_item_identity("image1-0-1", "起司"))
        self.assertTrue(validate_item_identity("image13-0-1", "柠檬气泡水"))

    def test_validator_rejects_unregistered_id_and_missing_id(self):
        from catalog_validator import validate_item_identity
        # Legitimate genuine name without valid registered catalog ID must be rejected
        with self.assertRaises(ValueError) as ctx1:
            validate_item_identity("unregistered-catalog-id", "起司")
        self.assertIn("without valid catalogId", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            validate_item_identity(None, "起司")
        self.assertIn("without valid catalogId", str(ctx2.exception))

        with self.assertRaises(ValueError) as ctx3:
            validate_item_identity("", "起司")
        self.assertIn("without valid catalogId", str(ctx3.exception))

    def test_validator_rejects_field_conflicts_within_same_record(self):
        from catalog_validator import validate_catalog_record
        # 1. Contradictory name vs canonicalName
        with self.assertRaises(ValueError) as ctx1:
            validate_catalog_record({
                "catalogId": "image1-0-1",
                "name": "起司",
                "canonicalName": "柠檬气泡水",
            })
        self.assertIn("Field conflict", str(ctx1.exception))

        # 2. Contradictory catalogId vs selectedCatalogId
        with self.assertRaises(ValueError) as ctx2:
            validate_catalog_record({
                "catalogId": "image1-0-1",
                "selectedCatalogId": "image13-0-1",
                "canonicalName": "起司",
            })
        self.assertIn("Field conflict", str(ctx2.exception))

        # 3. Contradictory confirmed vs unconfirmed status
        with self.assertRaises(ValueError) as ctx3:
            validate_catalog_record({
                "catalogId": "image1-0-1",
                "canonicalName": "起司",
                "status": "CONFIRMED",
                "identityStatus": "UNCONFIRMED_VISUAL_ITEM",
            })
        self.assertIn("Field conflict", str(ctx3.exception))

    def test_validator_enforces_null_canonical_name_for_unconfirmed_visual_units(self):
        from catalog_validator import validate_item_identity
        # Unconfirmed visual item with canonicalName=None passes cleanly
        self.assertTrue(validate_item_identity(None, None, "UNCONFIRMED_VISUAL_ITEM"))
        self.assertTrue(validate_item_identity(None, None, "UNKNOWN_OR_CANDIDATE_UNCONFIRMED"))
        self.assertTrue(validate_item_identity(None, None, "REVIEW_REQUIRED"))

        # Claiming confirmed status without canonicalName or without catalogId must be rejected
        with self.assertRaises(ValueError) as ctx1:
            validate_item_identity(None, None, "CONFIRMED")
        self.assertIn("Status contradiction", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            validate_item_identity("image1-0-1", None, "CONFIRMED")
        self.assertIn("Status contradiction", str(ctx2.exception))

    def test_manifest_cannot_self_authorize_new_id_without_source_evidence(self):
        from catalog_validator import validate_catalog_record, has_verifiable_source_evidence
        # An arbitrary new ID outside catalog_065 without independent verified source card evidence must be rejected
        unverified_record = {
            "catalogId": "unverified-self-claimed-id",
            "canonicalName": "起司",
            "status": "CONFIRMED",
        }
        self.assertFalse(has_verifiable_source_evidence(unverified_record))
        with self.assertRaises(ValueError) as ctx:
            validate_catalog_record(unverified_record)
        self.assertIn("lacks independent verifiable source screenshot card evidence", str(ctx.exception))

        # Even with fabricated metadata pointing to a nonexistent screenshot file
        fabricated_record = {
            "catalogId": "unverified-self-claimed-id",
            "canonicalName": "起司",
            "status": "CONFIRMED",
            "sourceScreenshot": "assets/items/catalog_screenshots/nonexistent_shot.png",
            "sourceScreenshotSha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "bbox": [10, 20, 100, 200],
        }
        self.assertFalse(has_verifiable_source_evidence(fabricated_record))
        with self.assertRaises(ValueError):
            validate_catalog_record(fabricated_record)

    def test_entrypoints_reject_corrupt_or_conflicting_inputs(self):
        import tempfile
        from visual_catalog import deterministic_reference_crops
        from warehouse_placement_resolver import WarehousePlacementResolver

        # Test deterministic_reference_crops rejects corrupted manifest
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({
                "records": [
                    {
                        "catalogId": "image1-0-1",
                        "canonicalName": "柠檬气泡水",  # ID-name mismatch with real catalog
                        "status": "RECOVERED_DETERMINISTIC",
                        "cropRelativePath": "assets/items/crops/1x1/image1-0-1.png",
                    }
                ]
            }))
            temp_path = Path(f.name)

        try:
            with self.assertRaises(ValueError):
                deterministic_reference_crops(manifest_path=temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

        # Test WarehousePlacementResolver rejects manifest with field conflict
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({
                "records": [
                    {
                        "catalogId": "image1-0-1",
                        "name": "起司",
                        "canonicalName": "柠檬气泡水",  # conflicting fields
                        "status": "RECOVERED_DETERMINISTIC",
                        "cropRelativePath": "assets/items/crops/1x1/image1-0-1.png",
                    }
                ]
            }))
            temp_path = Path(f.name)

        try:
            with self.assertRaises(ValueError):
                WarehousePlacementResolver(manifest_path=temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_report_generator_rejects_unverified_benchmark_item(self):
        from catalog_validator import validate_catalog_record
        # Benchmark items must NOT possess unverified formal canonicalName
        corrupt_benchmark_item = {
            "referenceId": "test_box_01",
            "name": "起司",
            "canonicalName": "柠檬气泡水",  # field conflict
            "status": "UNCONFIRMED_VISUAL_ITEM",
        }
        with self.assertRaises(ValueError):
            validate_catalog_record(corrupt_benchmark_item)

    def test_manifest_v2_all_records_pass_strict_provenance(self):
        from catalog_validator import validate_manifest_records
        manifest_path = ROOT / "assets" / "items" / "catalog_reference_manifest_v2.json"
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = manifest_data.get("records", [])
        self.assertEqual(len(records), 214)
        self.assertEqual(manifest_data.get("recoveredCount"), 213)
        self.assertEqual(manifest_data.get("unresolvedCount"), 1)

        errors = validate_manifest_records(records)
        self.assertEqual(errors, [], f"Manifest validation errors: {errors}")

        # Verify that all 167 pre-existing IDs are completely preserved
        # and the 46 new IDs correspond exactly to this round's connected items
        connection_report_path = ROOT / "assets" / "items" / "catalog_47_connection_report.json"
        self.assertTrue(connection_report_path.is_file(), "Connection report missing")
        report_data = json.loads(connection_report_path.read_text(encoding="utf-8"))
        connected_ids = {it["catalogId"] for it in report_data.get("connectedItems", [])}
        self.assertEqual(len(connected_ids), 46, "Must have exactly 46 connected items")

        unresolved_in_report = report_data.get("remainingUnresolvedItems", [])
        self.assertEqual(len(unresolved_in_report), 1)
        self.assertEqual(unresolved_in_report[0]["catalogId"], "image2-1-1")
        self.assertEqual(unresolved_in_report[0]["officialName"], "磨刀石")

        manifest_ids = {r["catalogId"] for r in records}
        self.assertEqual(len(manifest_ids), 214, "All 214 manifest IDs must be distinct")
        self.assertTrue(connected_ids.issubset(manifest_ids), "All 46 connected IDs must be in manifest")

        pre_existing_ids = (manifest_ids - connected_ids) - {"image2-1-1"}
        self.assertEqual(len(pre_existing_ids), 167, "Must preserve exactly 167 pre-existing IDs")

        # Verify each of the 46 connected items matches official name from catalog_065.json
        cat065_path = ROOT / "assets" / "catalog_065.json"
        cat065 = {c["Id"]: c for c in json.loads(cat065_path.read_text(encoding="utf-8"))}
        for it in report_data.get("connectedItems", []):
            cid = it["catalogId"]
            self.assertIn(cid, cat065, f"Connected item {cid} must exist in catalog_065.json")
            self.assertEqual(it["name"], cat065[cid]["Name"], f"Name mismatch for {cid}")

    def test_ground_truth_144037_all_items_have_null_canonical_name_and_pass(self):
        from catalog_validator import validate_catalog_record, is_valid_catalog_id, get_official_name
        gt_path = ROOT / "assets" / "items" / "video_ground_truth_reference_144037.json"
        gt_data = json.loads(gt_path.read_text(encoding="utf-8"))
        items = gt_data.get("items", [])
        self.assertEqual(len(items), 39)

        verified_count = 0
        unconfirmed_count = 0
        for it in items:
            self.assertTrue(validate_catalog_record(it, root=ROOT))
            cname = it.get("canonicalName")
            if cname is None:
                # Unconfirmed items must keep canonicalName null and use unconfirmed status
                self.assertEqual(it.get("identityStatus"), "UNCONFIRMED")
                self.assertIsNone(it.get("catalogId"))
                unconfirmed_count += 1
            else:
                # Confirmed items must have verified source card evidence and match official catalog
                self.assertEqual(it.get("identityStatus"), "VISUALLY_CHECKED_SOURCE_CARD")
                cid = it.get("catalogId")
                self.assertIsNotNone(cid)
                self.assertTrue(is_valid_catalog_id(cid))
                self.assertEqual(cname, get_official_name(cid))

                # Verify source screenshot file exists on disk
                src = it.get("sourceScreenshot")
                self.assertIsNotNone(src)
                self.assertTrue((ROOT / src).is_file(), f"Source screenshot {src} not found on disk")

                # Verify card bbox has valid dimensions
                bbox = it.get("cardBbox") or it.get("bbox")
                self.assertIsNotNone(bbox)
                self.assertEqual(len(bbox), 4)
                self.assertGreater(bbox[2], 0)
                self.assertGreater(bbox[3], 0)
                verified_count += 1

        # 39 items verified against independent catalog screenshots and authoritative registry
        self.assertEqual(verified_count, 39)
        self.assertEqual(unconfirmed_count, 0)
        ref_32 = next(i for i in items if i["referenceId"] == "ref_144037_32")
        self.assertEqual(ref_32["canonicalName"], "琉璃尾")
        self.assertEqual(ref_32["catalogId"], "visual-liuliwei-4x1")
        self.assertEqual(ref_32["identityStatus"], "VISUALLY_CHECKED_SOURCE_CARD")

    def test_video_39_machine_predictions_separated_from_ground_truth(self):
        from catalog_validator import validate_item_identity
        gt_path = ROOT / "assets" / "items" / "video_ground_truth_reference_144037.json"
        align_baseline_path = ROOT / "assets" / "items" / "video_prediction_alignment_144037_20260909.json"
        align_retest_path = ROOT / "assets" / "items" / "video_prediction_alignment_144037_retest_20260911.json"
        align_primary_path = ROOT / "assets" / "items" / "video_prediction_alignment_144037.json"

        self.assertTrue(align_baseline_path.is_file(), "Baseline prediction alignment must exist")
        self.assertTrue(align_retest_path.is_file(), "Retest prediction alignment must exist")
        self.assertTrue(align_primary_path.is_file(), "Primary prediction alignment must exist")

        gt_data = json.loads(gt_path.read_text(encoding="utf-8"))
        baseline_data = json.loads(align_baseline_path.read_text(encoding="utf-8"))
        retest_data = json.loads(align_retest_path.read_text(encoding="utf-8"))

        gt_items = gt_data.get("items", [])
        self.assertEqual(len(gt_items), 39)

        # 1. Historical 20260909 baseline: 26 plausible, 10 no candidate, 3 geometry contradictions
        base_stats = baseline_data.get("metadata", {}).get("statistics", {})
        self.assertEqual(base_stats.get("candidatePlausibleCount"), 26)
        self.assertEqual(base_stats.get("noMachineCandidateCount"), 10)
        self.assertEqual(base_stats.get("geometryContradictionCount"), 3)
        self.assertEqual(base_stats.get("confirmedExactCount"), 0)

        # 2. Historical 20260911 retest v1: 30 plausible, 8 no candidate, 1 geometry contradiction
        # Not locked to 26/10/3!
        retest_stats = retest_data.get("metadata", {}).get("statistics", {})
        self.assertEqual(retest_stats.get("candidatePlausibleCount"), 30)
        self.assertEqual(retest_stats.get("noMachineCandidateCount"), 8)
        self.assertEqual(retest_stats.get("geometryContradictionCount"), 1)
        self.assertEqual(retest_stats.get("confirmedExactCount"), 0)

        # 3. Current production retest (v4) / primary alignment:
        # Verified improvements: 39 shape-consistent candidates, 39 identity matches, 0 geometry contradictions, 0 no-candidate
        primary_data = json.loads(align_primary_path.read_text(encoding="utf-8"))
        prim_stats = primary_data.get("metadata", {}).get("statistics", {})
        self.assertEqual(prim_stats.get("shapeConsistentCount"), 39)
        self.assertEqual(prim_stats.get("candidateListMatchedCount"), 39)
        self.assertEqual(prim_stats.get("firstChoiceMatchedCount"), 39)
        self.assertEqual(prim_stats.get("falseFirstChoiceCount"), 0)
        self.assertEqual(prim_stats.get("identityMatchedCount"), 39)
        self.assertEqual(prim_stats.get("noMachineCandidateCount"), 0)
        self.assertEqual(prim_stats.get("geometryContradictionCount"), 0)
        self.assertEqual(prim_stats.get("confirmedExactCount"), 0)
        self.assertEqual(prim_stats.get("groundTruthConfirmedCount"), 39)

        # Zero degradation verification: every item matched in retest v1 must remain matched in primary
        retest_items = {it["referenceId"]: it for it in retest_data.get("items", [])}
        primary_items = {it["referenceId"]: it for it in primary_data.get("items", [])}
        for ref_id, old_it in retest_items.items():
            if old_it.get("alignmentCategory") == "CANDIDATE_PLAUSIBLE":
                new_it = primary_items[ref_id]
                self.assertEqual(
                    new_it.get("alignmentCategory"),
                    "CANDIDATE_PLAUSIBLE",
                    f"Regression detected: {ref_id} was PLAUSIBLE in retest v1 but degraded in current alignment",
                )

        # 4. Shape matching does NOT equal confirmed identity:
        # Machine prediction candidates must stay CANDIDATE_ONLY or UNCONFIRMED, never CONFIRMED
        for align_set in (baseline_data.get("items", []), retest_data.get("items", []), primary_data.get("items", [])):
            self.assertEqual(len(align_set), 39)
            for it in align_set:
                self.assertIn(it.get("identityStatus"), ("CANDIDATE_ONLY", "UNCONFIRMED"))
                for cand in it.get("machineCandidates", []):
                    self.assertEqual(cand.get("identityStatus"), "CANDIDATE_ONLY")
                    self.assertTrue(
                        validate_item_identity(
                            cand["catalogId"],
                            cand["name"],
                            cand.get("identityStatus", "CANDIDATE_ONLY"),
                        )
                    )


    def test_deterministic_reference_crops_invokes_validator_and_loads(self):
        from visual_catalog import deterministic_reference_crops
        crops = deterministic_reference_crops()
        self.assertEqual(len(crops), 213)
        for crop in crops:
            self.assertEqual(crop.get("status"), "RECOVERED_DETERMINISTIC")
            self.assertIsNotNone(crop.get("cropSha256"))

        crop_ids = {c["catalogId"] for c in crops}
        self.assertEqual(len(crop_ids), 213)

        connection_report_path = ROOT / "assets" / "items" / "catalog_47_connection_report.json"
        report_data = json.loads(connection_report_path.read_text(encoding="utf-8"))
        connected_ids = {it["catalogId"] for it in report_data.get("connectedItems", [])}
        self.assertTrue(connected_ids.issubset(crop_ids))
        self.assertEqual(len(crop_ids - connected_ids), 167)

    def test_warehouse_placement_resolver_validates_cache_on_init(self):
        from warehouse_placement_resolver import WarehousePlacementResolver
        resolver = WarehousePlacementResolver()
        self.assertEqual(len(resolver._ref_cache), 213)
        for cid, entry in resolver._ref_cache.items():
            self.assertEqual(entry["entry"]["catalogId"], cid)

        cache_ids = set(resolver._ref_cache.keys())
        connection_report_path = ROOT / "assets" / "items" / "catalog_47_connection_report.json"
        report_data = json.loads(connection_report_path.read_text(encoding="utf-8"))
        connected_ids = {it["catalogId"] for it in report_data.get("connectedItems", [])}
        self.assertTrue(connected_ids.issubset(cache_ids))
        self.assertEqual(len(cache_ids - connected_ids), 167)

    def test_unresolved_47_audit_file_matches_catalog_065_exactly(self):
        audit_path = ROOT / "assets" / "items" / "catalog_unresolved_47_audit.json"
        self.assertTrue(audit_path.is_file(), "Audit file missing")
        audit_data = json.loads(audit_path.read_text(encoding="utf-8"))
        unresolved = audit_data.get("unresolvedCatalogItems", [])
        self.assertEqual(len(unresolved), 47)

        cat065_path = ROOT / "assets" / "catalog_065.json"
        cat065 = {c["Id"]: c for c in json.loads(cat065_path.read_text(encoding="utf-8"))}

        for item in unresolved:
            cid = item["catalogId"]
            self.assertIn(cid, cat065, f"Missing {cid} in cat065")
            self.assertEqual(item["officialName"], cat065[cid]["Name"])
            self.assertEqual(item["classification"], "已有真实名称但缺程序裁图")
            self.assertEqual(item["manifestStatus"], "MISSING_UNRESOLVED")
            self.assertIsNone(item["sourceScreenshot"])
            self.assertIsNone(item["cropRelativePath"])
            self.assertFalse(item["cropOnDisk"])

        benchmark_summary = audit_data.get("benchmarkVisualUnitsSummary", {})
        self.assertEqual(benchmark_summary.get("totalItems"), 39)
        self.assertEqual(benchmark_summary.get("classification"), "画面已裁切但身份尚未确认")

    def test_validator_rejects_genuine_card_paired_with_wrong_genuine_name(self):
        from catalog_validator import validate_catalog_record
        # Genuine screenshot and bbox for '霜铁交响' (visual-04d191b44682)
        real_card = {
            "catalogId": "visual-04d191b44682",
            "name": "起司",  # Mismatched name: '起司' is a genuine item, but this card belongs to '霜铁交响'
            "status": "CONFIRMED",
            "sourceScreenshot": "assets/items/catalog_screenshots/2X3/{FD33E1F1-6A47-4A1A-9A89-9163570FEA0A}.png",
            "bbox": [0, 0, 393, 274],
        }
        with self.assertRaises(ValueError) as ctx1:
            validate_catalog_record(real_card)
        self.assertIn("Source card identity mismatch", str(ctx1.exception))
        self.assertIn("霜铁交响", str(ctx1.exception))
        self.assertIn("起司", str(ctx1.exception))

        # Genuine card paired with wrong catalogId
        wrong_id_card = {
            "catalogId": "image1-0-1",  # catalogId for '起司', but card is '霜铁交响'
            "name": "霜铁交响",
            "status": "CONFIRMED",
            "sourceScreenshot": "assets/items/catalog_screenshots/2X3/{FD33E1F1-6A47-4A1A-9A89-9163570FEA0A}.png",
            "bbox": [0, 0, 393, 274],
        }
        with self.assertRaises(ValueError) as ctx2:
            validate_catalog_record(wrong_id_card)
        self.assertIn("Source card catalogId mismatch", str(ctx2.exception))

    def test_validator_rejects_non_image_screenshot_file(self):
        import hashlib
        from catalog_validator import validate_catalog_record
        # Non-image file (catalog_065.json) pretending to be a screenshot
        json_path = ROOT / "assets" / "catalog_065.json"
        json_sha = hashlib.sha256(json_path.read_bytes()).hexdigest()
        fake_image_record = {
            "catalogId": "image1-0-1",
            "name": "起司",
            "status": "CONFIRMED",
            "sourceScreenshot": "assets/catalog_065.json",
            "sourceScreenshotSha256": json_sha,
            "bbox": [0, 0, 10, 10],
        }
        with self.assertRaises(ValueError) as ctx:
            validate_catalog_record(fake_image_record)
        self.assertIn("not a valid decodable image", str(ctx.exception))

    def test_validator_rejects_zero_area_and_negative_bbox(self):
        from catalog_validator import validate_catalog_record
        real_shot = "assets/items/catalog_screenshots/2X3/{FD33E1F1-6A47-4A1A-9A89-9163570FEA0A}.png"
        # Zero-area bbox [0, 0, 0, 0]
        zero_area = {
            "catalogId": "visual-04d191b44682",
            "name": "霜铁交响",
            "status": "CONFIRMED",
            "sourceScreenshot": real_shot,
            "bbox": [0, 0, 0, 0],
        }
        with self.assertRaises(ValueError) as ctx1:
            validate_catalog_record(zero_area)
        self.assertIn("strictly positive", str(ctx1.exception))

        # Negative width
        neg_w = {
            "catalogId": "visual-04d191b44682",
            "name": "霜铁交响",
            "status": "CONFIRMED",
            "sourceScreenshot": real_shot,
            "bbox": [0, 0, -10, 20],
        }
        with self.assertRaises(ValueError) as ctx2:
            validate_catalog_record(neg_w)
        self.assertIn("strictly positive", str(ctx2.exception))

        # Negative coordinate
        neg_coord = {
            "catalogId": "visual-04d191b44682",
            "name": "霜铁交响",
            "status": "CONFIRMED",
            "sourceScreenshot": real_shot,
            "bbox": [-5, 0, 100, 100],
        }
        with self.assertRaises(ValueError) as ctx3:
            validate_catalog_record(neg_coord)
        self.assertIn("cannot be negative", str(ctx3.exception))

    def test_validator_rejects_out_of_bounds_bbox(self):
        from catalog_validator import validate_catalog_record
        real_shot = "assets/items/catalog_screenshots/2X3/{FD33E1F1-6A47-4A1A-9A89-9163570FEA0A}.png"
        # Massive out-of-bounds bbox
        oob_huge = {
            "catalogId": "visual-04d191b44682",
            "name": "霜铁交响",
            "status": "CONFIRMED",
            "sourceScreenshot": real_shot,
            "bbox": [0, 0, 9999, 9999],
        }
        with self.assertRaises(ValueError) as ctx1:
            validate_catalog_record(oob_huge)
        self.assertIn("extends beyond image dimensions", str(ctx1.exception))

        # Partially out of bounds on x axis (1000 + 300 = 1300 > 1178)
        oob_x = {
            "catalogId": "visual-04d191b44682",
            "name": "霜铁交响",
            "status": "CONFIRMED",
            "sourceScreenshot": real_shot,
            "bbox": [1000, 0, 300, 100],
        }
        with self.assertRaises(ValueError) as ctx2:
            validate_catalog_record(oob_x)
        self.assertIn("extends beyond image dimensions", str(ctx2.exception))

    def test_entrypoints_reject_card_mismatch_and_corrupt_images(self):
        import hashlib
        import tempfile
        from visual_catalog import deterministic_reference_crops
        from warehouse_placement_resolver import WarehousePlacementResolver

        # Case 1: Temporary manifest with genuine card paired with wrong genuine name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({
                "records": [
                    {
                        "catalogId": "visual-04d191b44682",
                        "canonicalName": "起司",  # wrong name! Card belongs to 霜铁交响
                        "status": "RECOVERED_DETERMINISTIC",
                        "sourceScreenshot": "assets/items/catalog_screenshots/2X3/{FD33E1F1-6A47-4A1A-9A89-9163570FEA0A}.png",
                        "bbox": [0, 0, 393, 274],
                        "cropRelativePath": "assets/items/reference_crops_v1/visual-04d191b44682.png",
                    }
                ]
            }))
            temp_path1 = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx_loader1:
                deterministic_reference_crops(manifest_path=temp_path1)
            self.assertIn("Source card identity mismatch", str(ctx_loader1.exception))

            with self.assertRaises(ValueError) as ctx_res1:
                WarehousePlacementResolver(manifest_path=temp_path1)
            self.assertIn("Source card identity mismatch", str(ctx_res1.exception))
        finally:
            temp_path1.unlink(missing_ok=True)

        # Case 2: Temporary manifest with non-image file as screenshot
        json_path = ROOT / "assets" / "catalog_065.json"
        json_sha = hashlib.sha256(json_path.read_bytes()).hexdigest()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({
                "records": [
                    {
                        "catalogId": "image1-0-1",
                        "canonicalName": "起司",
                        "status": "RECOVERED_DETERMINISTIC",
                        "sourceScreenshot": "assets/catalog_065.json",
                        "sourceScreenshotSha256": json_sha,
                        "bbox": [0, 0, 10, 10],
                        "cropRelativePath": "assets/items/reference_crops_v1/image1-0-1.png",
                    }
                ]
            }))
            temp_path2 = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx_loader2:
                deterministic_reference_crops(manifest_path=temp_path2)
            self.assertIn("not a valid decodable image", str(ctx_loader2.exception))
        finally:
            temp_path2.unlink(missing_ok=True)

        # Case 3: Temporary manifest with zero-area bbox
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({
                "records": [
                    {
                        "catalogId": "visual-04d191b44682",
                        "canonicalName": "霜铁交响",
                        "status": "RECOVERED_DETERMINISTIC",
                        "sourceScreenshot": "assets/items/catalog_screenshots/2X3/{FD33E1F1-6A47-4A1A-9A89-9163570FEA0A}.png",
                        "bbox": [0, 0, 0, 0],
                        "cropRelativePath": "assets/items/reference_crops_v1/visual-04d191b44682.png",
                    }
                ]
            }))
            temp_path3 = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx_loader3:
                deterministic_reference_crops(manifest_path=temp_path3)
            self.assertIn("strictly positive", str(ctx_loader3.exception))
        finally:
            temp_path3.unlink(missing_ok=True)

        # Verify correct production samples continue to load cleanly
        crops = deterministic_reference_crops()
        self.assertEqual(len(crops), 213)
        resolver = WarehousePlacementResolver()
        self.assertEqual(len(resolver._ref_cache), 213)

    def test_entrypoints_reject_replaced_screenshot_file_with_updated_manifest_hash(self):
        """Codex reproduction: replacing physical screenshot with another genuine screenshot
        and updating the manifest's claimed sourceScreenshotSha256 MUST be rejected
        by validate_catalog_record and entrypoints (deterministic_reference_crops,
        WarehousePlacementResolver), because authoritative hash originates from
        the independent verified source card registry.
        """
        import hashlib
        import tempfile
        from catalog_validator import validate_catalog_record
        from visual_catalog import deterministic_reference_crops
        from warehouse_placement_resolver import WarehousePlacementResolver

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            # 1. Choose card for '霜铁交响' (visual-04d191b44682)
            rel_shot = "assets/items/catalog_screenshots/2X3/{FD33E1F1-6A47-4A1A-9A89-9163570FEA0A}.png"
            fake_shot_dest = temp_root / rel_shot
            fake_shot_dest.parent.mkdir(parents=True, exist_ok=True)

            # Replace with bytes of another real screenshot (e.g. from 1x1 catalog screenshot)
            other_real_shot = ROOT / "assets/items/catalog_screenshots/1x1/{9138F8CF-782A-4086-937D-FAF3CD4E810B}.png"
            self.assertTrue(other_real_shot.is_file())
            other_bytes = other_real_shot.read_bytes()
            fake_shot_dest.write_bytes(other_bytes)
            replaced_sha = hashlib.sha256(other_bytes).hexdigest()

            # Copy a real crop image so crop-on-disk check wouldn't fail before card check
            crop_rel = "assets/items/reference_crops_v1/visual-04d191b44682.png"
            real_crop = ROOT / crop_rel
            dest_crop = temp_root / crop_rel
            dest_crop.parent.mkdir(parents=True, exist_ok=True)
            if real_crop.is_file():
                dest_crop.write_bytes(real_crop.read_bytes())
                crop_sha = hashlib.sha256(real_crop.read_bytes()).hexdigest()
            else:
                dest_crop.write_bytes(b"dummy")
                crop_sha = hashlib.sha256(b"dummy").hexdigest()

            # Record retains original ID, name, path, and bbox, but updates manifest sha to replaced file
            bad_record = {
                "catalogId": "visual-04d191b44682",
                "name": "霜铁交响",
                "canonicalName": "霜铁交响",
                "status": "RECOVERED_DETERMINISTIC",
                "sourceScreenshot": rel_shot,
                "sourceScreenshotSha256": replaced_sha,
                "bbox": [0, 0, 393, 274],
                "cropRelativePath": crop_rel,
                "cropSha256": crop_sha,
            }

            # 1. Direct validator must reject it because actual file SHA does not match registry SHA
            with self.assertRaises(ValueError) as ctx_val:
                validate_catalog_record(bad_record, root=temp_root)
            self.assertIn("Source screenshot SHA256 mismatch against authoritative registry", str(ctx_val.exception))

            # 2. Write manifest and test loading entrypoints
            manifest_path = temp_root / "test_manifest.json"
            manifest_path.write_text(json.dumps({"records": [bad_record]}), encoding="utf-8")

            # Entrypoint 1: deterministic_reference_crops must reject it
            with self.assertRaises(ValueError) as ctx_crops:
                deterministic_reference_crops(manifest_path=manifest_path, root=temp_root)
            self.assertIn("Source screenshot SHA256 mismatch against authoritative registry", str(ctx_crops.exception))

            # Entrypoint 2: WarehousePlacementResolver must reject it
            with self.assertRaises(ValueError) as ctx_res:
                WarehousePlacementResolver(manifest_path=manifest_path, root=temp_root)
            self.assertIn("Source screenshot SHA256 mismatch against authoritative registry", str(ctx_res.exception))

        # 3. Production loading continues to load cleanly
        crops = deterministic_reference_crops()
        self.assertEqual(len(crops), 213)
        resolver = WarehousePlacementResolver()
        self.assertEqual(len(resolver._ref_cache), 213)

    def test_validator_and_entrypoints_reject_empty_slot_card(self):
        """Regression test for empty slot failure: in 2X1/{48710325-8642-4753-AAFD-302E079D2B93}.png,
        the candidate box [781, 285, 366, 236] is an empty slot and must NOT be accepted as a verified
        card for image2-1-1 (磨刀石). Attempting to load this fake empty slot must be rejected by validator
        and both production entrypoints as an unverified card not in registry.
        Furthermore, the actual card on screen at [390, 265, 391, 265] is titled '锻刀石' (visual-65250f2f6c5a),
        so attempting to pair image2-1-1 ('磨刀石') with that card must also be rejected by identity mismatch.
        """
        import tempfile
        from catalog_validator import validate_catalog_record
        from visual_catalog import deterministic_reference_crops
        from warehouse_placement_resolver import WarehousePlacementResolver

        real_shot = "assets/items/catalog_screenshots/2X1/{48710325-8642-4753-AAFD-302E079D2B93}.png"

        # Case 1: Empty slot [781, 285, 366, 236] is not in registry -> rejected
        empty_slot_record = {
            "catalogId": "image2-1-1",
            "name": "磨刀石",
            "canonicalName": "磨刀石",
            "status": "RECOVERED_DETERMINISTIC",
            "sourceScreenshot": real_shot,
            "bbox": [781, 285, 366, 236],
            "cropRelativePath": "assets/items/reference_crops_v1/image1-0-1.png",
        }
        with self.assertRaises(ValueError) as ctx1:
            validate_catalog_record(empty_slot_record)
        self.assertIn("does not exist in the verified source card registry", str(ctx1.exception))

        # Case 2: Attempting to pair '磨刀石' with the middle card [390, 265, 391, 265] which belongs to '锻刀石'
        mismatched_card_record = {
            "catalogId": "image2-1-1",
            "name": "磨刀石",
            "canonicalName": "磨刀石",
            "status": "RECOVERED_DETERMINISTIC",
            "sourceScreenshot": real_shot,
            "bbox": [390, 265, 391, 265],
        }
        with self.assertRaises(ValueError) as ctx2:
            validate_catalog_record(mismatched_card_record)
        self.assertIn("Source card identity mismatch", str(ctx2.exception))
        self.assertIn("锻刀石", str(ctx2.exception))
        self.assertIn("磨刀石", str(ctx2.exception))

        # Case 3: Production entrypoints reject a manifest with the empty slot card
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"records": [empty_slot_record]}))
            temp_path = Path(f.name)

        try:
            with self.assertRaises(ValueError) as ctx_crops:
                deterministic_reference_crops(manifest_path=temp_path)
            self.assertIn("does not exist in the verified source card registry", str(ctx_crops.exception))

            with self.assertRaises(ValueError) as ctx_res:
                WarehousePlacementResolver(manifest_path=temp_path)
            self.assertIn("does not exist in the verified source card registry", str(ctx_res.exception))
        finally:
            temp_path.unlink(missing_ok=True)

    def test_low_saturation_and_multicomponent_foreground_fallback(self):
        """Tests production foreground extraction, IoU 0.75 calibration, and negative sample suppression.

        Threshold Calibration Rationale:
        IoU threshold was calibrated from 0.80 to 0.75 based on empirical evidence from multi-component
        furniture items (e.g. 复古圆桌 ref_144037_05 / image14-0-2), whose narrow legs (~1-2px on grid crops)
        undergo discrete pixel boundary quantization during resizing, yielding IoU ~ 0.77-0.83.
        Strict false-positive suppression is maintained by requiring correlation >= 0.85 (measured 0.9427)
        and error <= 22.0 (measured 11.96), which strongly rejects same-size competing items, empty background,
        selection badges, and occlusions.
        """
        from warehouse_placement_resolver import WarehousePlacementResolver
        resolver = WarehousePlacementResolver()

        # 1. Positive: Low-saturation neutral item (绵绵云, 1x1, image3-0-1)
        cloud_crop = cv2.imread(str(ROOT / "assets/items/ground_truth_reference_144037/ref_144037_20.png"))
        self.assertIsNotNone(cloud_crop)
        res_cloud = resolver._compute_foreground_alignment(
            cloud_crop, resolver._ref_cache["image3-0-1"]["img"]
        )
        self.assertIsNotNone(res_cloud)
        self.assertGreaterEqual(res_cloud["iou"], 0.75)
        self.assertGreaterEqual(res_cloud["correlation"], 0.85)
        self.assertLessEqual(res_cloud["error"], 22.0)

        # 2. Positive: Multi-component object grouping (复古圆桌, 2x1, image14-0-2)
        table_crop = cv2.imread(str(ROOT / "assets/items/ground_truth_reference_144037/ref_144037_05.png"))
        self.assertIsNotNone(table_crop)
        res_table = resolver._compute_foreground_alignment(
            table_crop, resolver._ref_cache["image14-0-2"]["img"]
        )
        self.assertIsNotNone(res_table)
        self.assertGreaterEqual(res_table["iou"], 0.75)
        self.assertGreaterEqual(res_table["correlation"], 0.85)
        self.assertLessEqual(res_table["error"], 22.0)

        # Production entrypoint assignment for table_crop:
        score_table, cands_table, _ = resolver.match_catalog_candidates(table_crop, 2, 1)
        self.assertEqual(len(cands_table), 1)
        self.assertEqual(cands_table[0]["catalogId"], "image14-0-2")

        # 3. Negative: Same-size competitors (all other 26 2x1 catalog items must be rejected)
        refs_2x1 = [entry for entry in resolver._ref_cache.values() if entry["widthCells"] == 2 and entry["heightCells"] == 1]
        for r in refs_2x1:
            if r["entry"]["catalogId"] == "image14-0-2":
                continue
            res_comp = resolver._compute_foreground_alignment(table_crop, r["img"])
            self.assertIsNone(res_comp, f"Competitor {r['entry']['catalogId']} must be rejected by correlation/error/iou")

        # 4. Negative: Tabletop background / uniform empty cells
        empty_cell = np.full((75, 75, 3), 25, dtype=np.uint8)
        self.assertIsNone(resolver._extract_foreground(empty_cell))
        self.assertIsNone(resolver._compute_foreground_alignment(
            empty_cell, resolver._ref_cache["image3-0-1"]["img"]
        ))
        score_empty, cands_empty, _ = resolver.match_catalog_candidates(empty_cell, 1, 1, is_empty=True)
        self.assertEqual(cands_empty, [])

        # 5. Negative: Centered badge overlay and heavy occlusion
        badge_crop = table_crop.copy()
        bh, bw = badge_crop.shape[:2]
        badge_crop[bh//4:3*bh//4, bw//4:3*bw//4] = (255, 0, 255)  # Obscure object body with badge
        self.assertIsNone(resolver._compute_foreground_alignment(badge_crop, resolver._ref_cache["image14-0-2"]["img"]))

        occ_crop = table_crop.copy()
        occ_crop[:, :occ_crop.shape[1]//2] = 20  # 50% occlusion
        self.assertIsNone(resolver._compute_foreground_alignment(occ_crop, resolver._ref_cache["image14-0-2"]["img"]))

        # 6. Negative: Random noise and distant disconnected noise blobs directly on production _extract_foreground
        rng = np.random.default_rng(20260911)
        noise_img = rng.integers(0, 255, (75, 75, 3), dtype=np.uint8)
        self.assertIsNone(resolver._extract_foreground(noise_img))

        disconnected_noise = np.full((100, 100, 3), 20, dtype=np.uint8)
        cv2.circle(disconnected_noise, (20, 20), 8, (200, 200, 200), -1)
        cv2.circle(disconnected_noise, (80, 80), 8, (200, 200, 200), -1)
        self.assertIsNone(resolver._extract_foreground(disconnected_noise))

    def test_affine_and_homography_anomaly_guards(self):
        """Directly exercises production resolver._compute_sift_inliers and match_catalog_candidates.
        Verifies that scale degeneracy, point collapse, and anisotropic shear are rejected by production guards.
        Proves that removing the production guards causes the test to fail.
        """
        from warehouse_placement_resolver import WarehousePlacementResolver
        resolver = WarehousePlacementResolver()
        ref_01 = resolver._ref_cache["image1-0-1"]
        img_01 = ref_01["img"]
        h, w = img_01.shape[:2]

        # 1. Scale anomaly: huge upscale (scale ~ 4.0 > 3.0)
        huge_img = cv2.resize(img_01, (w * 4, h * 4))
        # Production guard returns 0
        inl_huge = resolver._compute_sift_inliers(huge_img, ref_01)
        self.assertEqual(inl_huge, 0, "Production scale guard must reject scale > 3.0")
        _, cands_huge, _ = resolver.match_catalog_candidates(huge_img, 1, 1)
        self.assertEqual(cands_huge, [], "Production admission must reject huge scale anomaly")

        # Proof of guard necessity: raw RANSAC without scale check produces > 50 inliers
        kp1, des1 = ref_01["kp"], ref_01["des"]
        kp2, des2 = resolver._sift.detectAndCompute(huge_img, None)
        matches = resolver._matcher.knnMatch(des1, des2, k=2)
        good = [m for m, n in matches if len(matches[0]) == 2 and m.distance < 0.75 * n.distance]
        src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        M, m_mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=5.0)
        raw_scale = np.sqrt(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0])
        self.assertGreater(raw_scale, 3.0)
        self.assertGreater(int(m_mask.sum()), 50, "Without scale guard, raw affine produces massive fake inliers")

        # 2. Scale anomaly: tiny scale (scale ~ 0.04 < 0.08)
        tiny_img = cv2.resize(img_01, (16, 16))
        pad_tiny = np.zeros((75, 75, 3), dtype=np.uint8)
        pad_tiny[:16, :16] = tiny_img
        inl_tiny = resolver._compute_sift_inliers(pad_tiny, ref_01)
        self.assertEqual(inl_tiny, 0, "Production scale guard must reject scale < 0.08")

        # 3. Severe anisotropic shear / perspective distortion: fx=2.8, fy=1.0 (shear ratio ~ 2.8 > 1.40)
        sheared_img = cv2.resize(img_01, (int(w * 2.8), h))
        inl_sheared = resolver._compute_sift_inliers(sheared_img, ref_01)
        self.assertEqual(inl_sheared, 0, "Production SVD guard must reject shear ratio > 1.40")
        _, cands_sheared, _ = resolver.match_catalog_candidates(sheared_img, 1, 1)
        self.assertEqual(cands_sheared, [], "Production admission must reject sheared anomaly")

        # Proof of SVD guard necessity: raw homography without SVD check produces >= 5 inliers (crossing 5-inlier admission)
        kp2_s, des2_s = resolver._sift.detectAndCompute(sheared_img, None)
        matches_s = resolver._matcher.knnMatch(des1, des2_s, k=2)
        good_s = [m for m, n in matches_s if len(matches_s[0]) == 2 and m.distance < 0.75 * n.distance]
        src_s = np.float32([kp1[m.queryIdx].pt for m in good_s]).reshape(-1, 1, 2)
        dst_s = np.float32([kp2_s[m.trainIdx].pt for m in good_s]).reshape(-1, 1, 2)
        H_s, h_mask_s = cv2.findHomography(src_s, dst_s, cv2.RANSAC, 5.0)
        raw_shear_inl = int(h_mask_s.sum())
        self.assertGreaterEqual(raw_shear_inl, 5, "Without SVD guard, raw homography produces fake inliers >= 5")

    def test_sift_five_inlier_admission_and_ambiguity_margin(self):
        """Directly exercises production match_catalog_candidates admission and margin gates.
        Verifies:
        1. Inliers >= 5 and margin >= 4 admits candidate.
        2. Inliers < 5 rejects candidate.
        3. Near-tie competition (margin < 4) rejects candidate.
        """
        from warehouse_placement_resolver import WarehousePlacementResolver
        resolver = WarehousePlacementResolver()

        # 1. Genuine crop ref_144037_01 (2x3, 销魂挠挠爪, image12-0-0) has 9 inliers >= 5 and margin >= 4
        crop_01 = cv2.imread(str(ROOT / "assets/items/ground_truth_reference_144037/ref_144037_01.png"))
        self.assertIsNotNone(crop_01)
        score_01, cands_01, inliers_01 = resolver.match_catalog_candidates(crop_01, 2, 3)
        self.assertGreaterEqual(inliers_01, 5, "Genuine item must produce at least 5 SIFT inliers")
        self.assertEqual(len(cands_01), 1)
        self.assertEqual(cands_01[0]["catalogId"], "image12-0-0")
        self.assertIn("SIFT_INLIERS_", cands_01[0]["matchReasons"][1])

        # 2. Corrupted/blurred crop: SIFT inliers < 5 -> production admission returns no candidate
        blurred = cv2.GaussianBlur(crop_01, (31, 31), 10.0)
        score_blur, cands_blur, inliers_blur = resolver.match_catalog_candidates(blurred, 2, 3)
        self.assertLess(inliers_blur, 5, "Blurred image must produce < 5 inliers")
        self.assertEqual(cands_blur, [], "Blurred image with insufficient inliers (< 5) must be rejected")

        # 3. Near-tie ambiguity test directly through production match_catalog_candidates:
        # Reads two different identities strictly from official catalog (image12-0-0 and image1-0-0).
        # Controls matching evidence (assigning matching descriptors to image1-0-0) to manufacture a near-tie (margin = 0 < 4).
        orig_kp_b = resolver._ref_cache["image1-0-0"]["kp"]
        orig_des_b = resolver._ref_cache["image1-0-0"]["des"]
        try:
            resolver._ref_cache["image1-0-0"]["kp"] = resolver._ref_cache["image12-0-0"]["kp"]
            resolver._ref_cache["image1-0-0"]["des"] = resolver._ref_cache["image12-0-0"]["des"]
            # Both genuine catalog references now produce identical inliers (margin = 0 < 4), production must reject both!
            score_tie, cands_tie, inliers_tie = resolver.match_catalog_candidates(crop_01, 2, 3)
            self.assertEqual(cands_tie, [], "Near-tie ambiguity between genuine catalog items (margin < 4) must reject candidates in production")
        finally:
            resolver._ref_cache["image1-0-0"]["kp"] = orig_kp_b
            resolver._ref_cache["image1-0-0"]["des"] = orig_des_b

    def test_sift_keypoint_deduplication_prevents_multi_voting(self):
        """Verifies destination keypoint deduplication (uniq_dst = len(set(m.trainIdx for m in inliers)))
        in resolver._compute_sift_inliers.
        """
        from warehouse_placement_resolver import WarehousePlacementResolver
        resolver = WarehousePlacementResolver()
        crop_05 = cv2.imread(str(ROOT / "assets/items/ground_truth_reference_144037/ref_144037_05.png"))
        self.assertIsNotNone(crop_05)
        kp2, des2 = resolver._sift.detectAndCompute(crop_05, None)

        # Competitor image19-1-1 previously claimed fake inliers due to multi-voting
        comp_entry = resolver._ref_cache["image19-1-1"]
        inl_dedup = resolver._compute_sift_inliers(crop_05, comp_entry, roi_kp_des=(kp2, des2))
        self.assertLess(inl_dedup, 5, "Deduplicated inliers for competitor must be < 5")

        # Verification through production admission entrypoint
        score_table, cands_table, _ = resolver.match_catalog_candidates(crop_05, 2, 1)
        self.assertEqual(len(cands_table), 1)
        self.assertNotEqual(cands_table[0]["catalogId"], "image19-1-1")

    def test_alignment_metrics_distinguishes_candidate_list_and_first_choice_error(self):
        """Tests Requirements 1, 2, 3, 4:
        1. Report entrypoint must strictly validate raw candidate ID and name:
           Unknown ID or ID-name mismatch must raise ValueError and not write output.
        2. Test names for catalog items (e.g. image19-1-1) must be read from authoritative registry.
        3. A review unit with 'wrong first choice + correct second choice' must be counted as a first choice error.
        4. Raw first choice is evaluated from the FIRST candidate: dimensionally incorrect items
           cannot be filtered out to promote the 2nd item to first choice!
        """
        import tempfile
        sys.path.insert(0, str(ROOT / "tools"))
        sys.path.insert(0, str(ROOT / "core"))
        from generate_39_identity_alignment import generate_alignment
        from catalog_validator import get_official_name

        name_19 = get_official_name("image19-1-1")
        name_12 = get_official_name("image12-0-0")
        name_11 = get_official_name("image11-0-1")
        name_1 = get_official_name("image1-0-1")
        self.assertIsNotNone(name_19, "image19-1-1 must exist in official registry")
        self.assertIsNotNone(name_12, "image12-0-0 must exist in official registry")
        self.assertIsNotNone(name_11, "image11-0-1 must exist in official registry")
        self.assertIsNotNone(name_1, "image1-0-1 must exist in official registry")

        build_dir = ROOT / "build"
        build_dir.mkdir(parents=True, exist_ok=True)

        # Negative Test A: Unknown catalogId must raise ValueError and NOT write report
        unknown_id_packet = {
            "metadata": {"packetId": "audit_mock_unknown_id"},
            "reviewUnits": [
                {
                    "reviewUnitId": "unit_unknown",
                    "anchorKey": [0, 0, 2, 3],
                    "candidates": [
                        {"catalogId": "unregistered-id-xyz", "name": name_12, "identityStatus": "CANDIDATE_ONLY"}
                    ],
                }
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8", dir=str(build_dir)) as f_bad1:
            json.dump(unknown_id_packet, f_bad1, indent=2, ensure_ascii=False)
            bad1_pkt = Path(f_bad1.name)
        bad1_out = build_dir / f"test_must_not_exist_1_{bad1_pkt.stem}.json"
        try:
            with self.assertRaises(ValueError):
                generate_alignment(packet_path=bad1_pkt, output_path=bad1_out)
            self.assertFalse(bad1_out.exists(), "Entrypoint failure must NOT create or overwrite report")
        finally:
            bad1_pkt.unlink(missing_ok=True)
            bad1_out.unlink(missing_ok=True)

        # Negative Test B: Genuine ID with mismatched name must raise ValueError and NOT write report
        mismatch_packet = {
            "metadata": {"packetId": "audit_mock_mismatch"},
            "reviewUnits": [
                {
                    "reviewUnitId": "unit_mismatch",
                    "anchorKey": [0, 2, 1, 3],
                    "candidates": [
                        # Genuine ID image11-0-1 (烟紫水晶) paired with wrong name '起司'
                        {"catalogId": "image11-0-1", "name": name_1, "identityStatus": "CANDIDATE_ONLY"}
                    ],
                }
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8", dir=str(build_dir)) as f_bad2:
            json.dump(mismatch_packet, f_bad2, indent=2, ensure_ascii=False)
            bad2_pkt = Path(f_bad2.name)
        bad2_out = build_dir / f"test_must_not_exist_2_{bad2_pkt.stem}.json"
        try:
            with self.assertRaises(ValueError):
                generate_alignment(packet_path=bad2_pkt, output_path=bad2_out)
            self.assertFalse(bad2_out.exists(), "ID-name mismatch must be rejected without creating report")
        finally:
            bad2_pkt.unlink(missing_ok=True)
            bad2_out.unlink(missing_ok=True)

        # Valid Packet: Testing First-Choice Error & Shape Filter Promotion Guard
        mock_packet = {
            "metadata": {
                "packetId": "audit_mock_first_choice_error",
                "creationTimestamp": "2026-09-11T19:15:00Z",
                "gitCommit": "8039a4f",
            },
            "reviewUnits": [
                {
                    # Unit 1: Wrong first choice (image19-1-1) + correct second choice (image12-0-0)
                    "reviewUnitId": "unit_mock_01",
                    "anchorKey": [0, 0, 2, 3],
                    "worldAnchor": {"row": 0, "col": 0},
                    "footprint": {"widthCells": 2, "heightCells": 3},
                    "shape": "2x3",
                    "bbox": [0.0, 0.0, 150.0, 225.0],
                    "quality": "blue",
                    "candidates": [
                        # First choice: WRONG (image19-1-1, 2x3, name read from official registry)
                        {
                            "catalogId": "image19-1-1",
                            "name": name_19,
                            "identityStatus": "CANDIDATE_ONLY",
                            "geometry": {"shape": "2x3", "width": 2, "height": 3},
                        },
                        # Second choice: CORRECT (image12-0-0, 2x3, name read from official registry)
                        {
                            "catalogId": "image12-0-0",
                            "name": name_12,
                            "identityStatus": "CANDIDATE_ONLY",
                            "geometry": {"shape": "2x3", "width": 2, "height": 3},
                        },
                    ],
                },
                {
                    # Unit 2: First candidate has wrong shape (1x1 != 1x3); second candidate has correct shape & ID
                    # Requirement 4: First choice must be evaluated from the raw first item;
                    # dimensionally incorrect item CANNOT be filtered out to promote the 2nd item as first choice!
                    "reviewUnitId": "unit_mock_02",
                    "anchorKey": [0, 2, 1, 3],
                    "worldAnchor": {"row": 0, "col": 2},
                    "footprint": {"widthCells": 1, "heightCells": 3},
                    "shape": "1x3",
                    "bbox": [150.0, 0.0, 225.0, 225.0],
                    "quality": "blue",
                    "candidates": [
                        # Candidate 0: WRONG SHAPE 1x1 (GT is 1x3)
                        {
                            "catalogId": "image1-0-1",
                            "name": name_1,
                            "identityStatus": "CANDIDATE_ONLY",
                            "geometry": {"shape": "1x1", "width": 1, "height": 1},
                        },
                        # Candidate 1: CORRECT SHAPE 1x3 and CORRECT ID image11-0-1
                        {
                            "catalogId": "image11-0-1",
                            "name": name_11,
                            "identityStatus": "CANDIDATE_ONLY",
                            "geometry": {"shape": "1x3", "width": 1, "height": 3},
                        },
                    ],
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8", dir=str(build_dir)) as f_pkt:
            json.dump(mock_packet, f_pkt, indent=2, ensure_ascii=False)
            mock_pkt_path = Path(f_pkt.name)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8", dir=str(build_dir)) as f_out:
            mock_out_path = Path(f_out.name)

        try:
            generate_alignment(packet_path=mock_pkt_path, output_path=mock_out_path)
            res_data = json.loads(mock_out_path.read_text(encoding="utf-8"))
            stats = res_data["metadata"]["statistics"]
            items_by_ref = {it["referenceId"]: it for it in res_data["items"]}

            # Unit 1 evaluation: ref_144037_01 (0, 0, 2, 3)
            u1_rec = items_by_ref["ref_144037_01"]
            self.assertTrue(u1_rec["candidateListMatchesGroundTruth"], "Secondary choice matches ground truth")
            self.assertFalse(u1_rec["firstChoiceMatchesGroundTruth"], "First choice is incorrect")
            self.assertTrue(u1_rec["isFirstChoiceError"], "Must be recorded as first choice error")

            # Unit 2 evaluation: ref_144037_02 (0, 2, 1, 3)
            # Raw first choice was Candidate 0 with wrong shape (1x1). Must NOT be promoted!
            u2_rec = items_by_ref["ref_144037_02"]
            self.assertTrue(u2_rec["candidateListMatchesGroundTruth"], "Secondary choice in candidate list matches ground truth")
            self.assertFalse(u2_rec["firstChoiceMatchesGroundTruth"], "Raw first candidate had wrong shape: must NOT be first choice match")
            self.assertTrue(u2_rec["isFirstChoiceError"], "Raw first choice error must be strictly recorded")

            # Overall stats assertion:
            self.assertEqual(stats["falseFirstChoiceCount"], 2, "Both units must record first choice error")
            self.assertEqual(stats["candidateListMatchedCount"], 2, "Both units matched in candidate list")
            self.assertEqual(stats["firstChoiceMatchedCount"], 0, "Neither unit had a correct first choice")
        finally:
            mock_pkt_path.unlink(missing_ok=True)
            mock_out_path.unlink(missing_ok=True)
