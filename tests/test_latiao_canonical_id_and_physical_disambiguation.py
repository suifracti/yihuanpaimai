# -*- coding: utf-8 -*-
"""Unit and negative test suite for Item #10 (酷辣辣辣条) canonical ID binding and physical disambiguation."""
from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from catalog_validator import (
    AmbiguousCatalogIdentifierError,
    get_authoritative_item_metadata,
    get_official_item,
    get_valid_physical_profiles,
    is_valid_catalog_id,
    resolve_legacy_catalog_identity,
    validate_catalog_record,
    validate_item_physical_consistency,
)
from settlement_catalog_candidates import SettlementCatalogCandidateResolver


class LatiaoCanonicalIdAndPhysicalDisambiguationTests(unittest.TestCase):
    """TC-01 to TC-06 and regression assertions for Item #10 (酷辣辣辣条)."""

    def test_tc01_white_positive(self):
        """TC-01: White 1x1 Latiao is valid with canonical ID image3-0-2 and value 100."""
        item = get_official_item("image3-0-2")
        self.assertIsNotNone(item)
        self.assertEqual(item["name"], "酷辣辣辣条")
        self.assertEqual(item["quality"], "灰")
        self.assertEqual(item["widthCells"], 1)
        self.assertEqual(item["heightCells"], 1)
        self.assertEqual(item["value"], 100)

        # Physical consistency validation
        self.assertTrue(
            validate_item_physical_consistency(
                "image3-0-2",
                name="酷辣辣辣条",
                quality="white",
                width=1,
                height=1,
            )
        )

        # Record validation
        record = {
            "catalogId": "image3-0-2",
            "name": "酷辣辣辣条",
            "quality": "白",
            "widthCells": 1,
            "heightCells": 1,
            "status": "CONFIRMED",
        }
        self.assertTrue(validate_catalog_record(record, root=ROOT))

    def test_tc02_red_positive(self):
        """TC-02: Red 1x2 Latiao is valid with canonical ID visual-latiao-1x2 and value 280,000."""
        meta = get_authoritative_item_metadata("visual-latiao-1x2")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["name"], "酷辣辣辣条")
        self.assertEqual(meta["quality"], "红")
        self.assertEqual(meta["widthCells"], 1)
        self.assertEqual(meta["heightCells"], 2)
        self.assertEqual(meta["value"], 280000)

        # Physical consistency validation
        self.assertTrue(
            validate_item_physical_consistency(
                "visual-latiao-1x2",
                name="酷辣辣辣条",
                quality="red",
                width=1,
                height=2,
            )
        )

        # Record validation with source card evidence
        record = {
            "catalogId": "visual-latiao-1x2",
            "name": "酷辣辣辣条",
            "quality": "红",
            "widthCells": 1,
            "heightCells": 2,
            "sourceScreenshot": "assets/items/catalog_screenshots/1X2/{343D8F72-4689-4286-AFFD-80CEC2496DC7}.png",
            "bbox": [0, 0, 383, 278],
            "status": "CONFIRMED",
        }
        self.assertTrue(validate_catalog_record(record, root=ROOT))

    def test_tc03_legacy_compatible_red_resolution(self):
        """TC-03: Legacy record with raw ID image3-0-2 resolves to visual-latiao-1x2 when physical context matches."""
        # When quality is red and grid is 1x2
        resolved = resolve_legacy_catalog_identity(
            "image3-0-2",
            observed_quality="red",
            observed_grid_w=1,
            observed_grid_h=2,
        )
        self.assertEqual(resolved, "visual-latiao-1x2")

        # Inverted grid dimensions (2x1) also resolve correctly
        resolved_inv = resolve_legacy_catalog_identity(
            "image3-0-2",
            observed_quality="红",
            observed_grid_w=2,
            observed_grid_h=1,
        )
        self.assertEqual(resolved_inv, "visual-latiao-1x2")

    def test_tc04_negative_size_and_quality_mismatch_on_red_id(self):
        """TC-04: Reject pairing visual-latiao-1x2 with white 1x1 physical observations (cross-mismatch guard)."""
        # Dimension mismatch
        with self.assertRaises(ValueError) as ctx:
            validate_item_physical_consistency(
                "visual-latiao-1x2",
                name="酷辣辣辣条",
                quality="red",
                width=1,
                height=1,
            )
        self.assertIn("Physical dimension mismatch", str(ctx.exception))

        # Quality mismatch
        with self.assertRaises(ValueError) as ctx:
            validate_item_physical_consistency(
                "visual-latiao-1x2",
                name="酷辣辣辣条",
                quality="white",
                width=1,
                height=2,
            )
        self.assertIn("Physical quality mismatch", str(ctx.exception))

        # Full record validation rejection
        with self.assertRaises(ValueError):
            validate_catalog_record({
                "catalogId": "visual-latiao-1x2",
                "name": "酷辣辣辣条",
                "quality": "white",
                "widthCells": 1,
                "heightCells": 1,
                "status": "CONFIRMED",
            }, root=ROOT)

    def test_tc05_negative_tampered_legacy_binding(self):
        """TC-05: Reject pairing image3-0-2 directly with red 1x2 physical observations without disambiguation."""
        # Direct consistency validation on image3-0-2 must reject red or 1x2
        with self.assertRaises(ValueError) as ctx:
            validate_item_physical_consistency(
                "image3-0-2",
                name="酷辣辣辣条",
                quality="red",
                width=1,
                height=2,
            )
        self.assertTrue(
            "Physical dimension mismatch" in str(ctx.exception)
            or "Physical quality mismatch" in str(ctx.exception)
        )

        # Record validation directly claiming image3-0-2 is 1x2 red must be rejected
        with self.assertRaises(ValueError):
            validate_catalog_record({
                "catalogId": "image3-0-2",
                "name": "酷辣辣辣条",
                "quality": "red",
                "widthCells": 1,
                "heightCells": 2,
                "status": "CONFIRMED",
            }, root=ROOT)

    def test_tc06_negative_naked_alias_without_context_fail_closed(self):
        """TC-06: Naked alias image3-0-2 without physical context is strictly rejected (Fail-Closed)."""
        # Completely naked
        with self.assertRaises(AmbiguousCatalogIdentifierError) as ctx:
            resolve_legacy_catalog_identity("image3-0-2")
        self.assertIn("requires unambiguous visual physical context", str(ctx.exception))

        # Missing dimensions
        with self.assertRaises(AmbiguousCatalogIdentifierError):
            resolve_legacy_catalog_identity("image3-0-2", observed_quality="red")

        # Missing quality
        with self.assertRaises(AmbiguousCatalogIdentifierError):
            resolve_legacy_catalog_identity("image3-0-2", observed_grid_w=1, observed_grid_h=2)

        # Contradictory context (red with 1x1)
        with self.assertRaises(AmbiguousCatalogIdentifierError):
            resolve_legacy_catalog_identity("image3-0-2", observed_quality="red", observed_grid_w=1, observed_grid_h=1)

        # Contradictory context (white with 1x2)
        with self.assertRaises(AmbiguousCatalogIdentifierError):
            resolve_legacy_catalog_identity("image3-0-2", observed_quality="white", observed_grid_w=1, observed_grid_h=2)

    def test_registry_unconditional_alias_unbind(self):
        """Verify image3-0-2 is NOT an unconditional alias of visual-latiao-1x2 in the registry."""
        reg_path = ROOT / "assets/items/verified_source_card_registry.json"
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        latiao_cards = [c for c in data.get("cards", []) if c.get("catalogId") == "visual-latiao-1x2"]
        self.assertEqual(len(latiao_cards), 1)
        card = latiao_cards[0]
        # alternateCatalogIds must not contain image3-0-2
        alts = card.get("alternateCatalogIds") or []
        self.assertNotIn("image3-0-2", alts)

    def test_candidate_resolver_distinct_hypotheses(self):
        """Verify candidate resolver returns visual-latiao-1x2 for 1x2 red and image3-0-2 for 1x1 white."""
        resolver = SettlementCatalogCandidateResolver()

        # 1x2 red hypothesis
        cands_1x2_red = resolver.resolve_candidates_for_hypothesis({"widthCells": 1, "heightCells": 2, "rarity": "red"})
        cids_1x2 = [c["catalogId"] for c in cands_1x2_red]
        self.assertIn("visual-latiao-1x2", cids_1x2)
        self.assertNotIn("image3-0-2", cids_1x2)

        # 1x1 white hypothesis
        cands_1x1_white = resolver.resolve_candidates_for_hypothesis({"widthCells": 1, "heightCells": 1, "rarity": "white"})
        cids_1x1 = [c["catalogId"] for c in cands_1x1_white]
        self.assertIn("image3-0-2", cids_1x1)
        self.assertNotIn("visual-latiao-1x2", cids_1x1)

    def test_non_circular_disambiguation_signature(self):
        """Verify resolve_legacy_catalog_identity takes ONLY physical observations (no price parameter)."""
        sig = inspect.signature(resolve_legacy_catalog_identity)
        params = list(sig.parameters.keys())
        self.assertIn("raw_catalog_id", params)
        self.assertIn("observed_quality", params)
        self.assertIn("observed_grid_w", params)
        self.assertIn("observed_grid_h", params)
        self.assertNotIn("price", params)
        self.assertNotIn("value", params)
        self.assertNotIn("clearing_price", params)


if __name__ == "__main__":
    unittest.main()
