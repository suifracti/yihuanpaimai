"""Isolated tests for geometry-only catalog candidate sets."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(CORE_DIR),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_catalog_geometry import (
    COVERAGE_UNVERIFIED,
    COVERAGE_VERIFIED,
    GEOM_COMPATIBLE,
    GEOM_EXACT,
    GEOM_PIXEL,
    IDENTITY_CANDIDATE,
    STATUS_AMBIGUOUS,
    STATUS_OUT_OF_CATALOG,
    STATUS_SINGLE_UNVERIFIED,
    STATUS_UNIQUE,
    STATUS_UNKNOWN,
    CatalogGeometryIndex,
    _load_catalog,
    default_catalog_path,
    resolve_catalog_candidates,
)
from warehouse_physical_ledger import PhysicalComponentLedger

FORBIDDEN_MATCH_TOKENS = (
    'item.get("Quality")',
    'item.get("Value")',
    'item.get("File")',
    "LiveFiles",
    "candidates[0]",
    "knownItems",
    "canonical_history",
)


def _shape(mask_rows: list[str]) -> str:
    grid = ["00000" for _ in range(5)]
    for row, line in enumerate(mask_rows):
        grid[row] = (line.replace("#", "1").replace(".", "0") + "00000")[:5]
    return "".join(grid)


def _item(catalog_id: str, name: str, width: int, height: int, mask_rows: list[str]) -> dict:
    shape = _shape(mask_rows)
    return {
        "Id": catalog_id,
        "Name": name,
        "Width": width,
        "Height": height,
        "Cells": sum(line.count("#") for line in mask_rows),
        "Shape": shape,
        "Quality": "MUST_NOT_BE_READ",
        "Value": 999999,
        "File": "must-not-read.png",
        "LiveFiles": ["must-not-read-live.png"],
    }


def _track(
    *,
    width: int,
    height: int,
    mask: list[list[int]],
    clipped: bool = False,
    clipped_top: bool = False,
    clipped_bottom: bool = False,
    status: str = "OBSERVED",
    reasons: list[str] | None = None,
    span: int | None = None,
) -> dict:
    ones = sum(sum(row) for row in mask)
    return {
        "trackId": "pct1_test_obs",
        "status": status,
        "clipped": clipped,
        "reasons": list(reasons or []),
        "widthCandidates": [width],
        "heightCandidates": [height],
        "spanCandidates": [span if span is not None else ones],
        "globalCellMaskCandidates": [{"cellMask": mask}],
        "observations": [
            {
                "clippedTop": clipped_top,
                "clippedBottom": clipped_bottom,
                "status": status,
            }
        ],
    }


SYNTHETIC = [
    _item("catA", "Rect2x2", 2, 2, ["##", "##"]),
    _item("catB", "Ell2x2", 2, 2, ["#.", "##"]),
    _item("catC", "Bar3x1", 3, 1, ["###"]),
    _item("catD", "Bar2x3", 2, 3, ["##", "##", "##"]),
]


class WarehouseCatalogGeometryV1Tests(unittest.TestCase):
    def setUp(self):
        self.unverified = CatalogGeometryIndex(SYNTHETIC, catalog_coverage_status=COVERAGE_UNVERIFIED)
        self.verified = CatalogGeometryIndex(SYNTHETIC, catalog_coverage_status=COVERAGE_VERIFIED)
        self.real = CatalogGeometryIndex()

    def test_exact_geometry_returns_stable_candidate_set(self):
        track = _track(width=2, height=2, mask=[[1, 1], [1, 1]])
        result = self.unverified.resolve(track)
        self.assertEqual(result["geometryEvidenceStatus"], GEOM_EXACT)
        self.assertEqual(result["status"], STATUS_SINGLE_UNVERIFIED)
        self.assertEqual(result["candidateCount"], 1)
        self.assertEqual(result["candidates"][0]["catalogId"], "catA")
        self.assertEqual(result["candidates"][0]["identityStatus"], IDENTITY_CANDIDATE)
        again = self.unverified.resolve(track)
        self.assertEqual(result, again)

    def test_same_size_different_shape_not_merged(self):
        ell = self.unverified.resolve(_track(width=2, height=2, mask=[[1, 0], [1, 1]]))
        rect = self.unverified.resolve(_track(width=2, height=2, mask=[[1, 1], [1, 1]]))
        self.assertEqual([item["catalogId"] for item in ell["candidates"]], ["catB"])
        self.assertEqual([item["catalogId"] for item in rect["candidates"]], ["catA"])
        self.assertNotEqual(ell["candidates"], rect["candidates"])

    def test_clipped_track_returns_compatible_superset(self):
        visible = _track(
            width=2,
            height=2,
            mask=[[1, 1], [1, 1]],
            clipped=True,
            clipped_bottom=True,
            status="AMBIGUOUS",
            reasons=["CLIPPED_ONLY"],
        )
        result = self.unverified.resolve(visible)
        self.assertEqual(result["geometryEvidenceStatus"], GEOM_COMPATIBLE)
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        ids = [item["catalogId"] for item in result["candidates"]]
        self.assertEqual(ids, ["catA", "catD"])
        self.assertNotIn("UNIQUE_IN_CATALOG", result["status"])

    def test_pixel_only_is_not_forged_exact(self):
        track = _track(width=2, height=2, mask=[[1, 1], [1, 1]], reasons=["PIXEL_ONLY"], status="AMBIGUOUS")
        result = self.unverified.resolve(track)
        self.assertEqual(result["geometryEvidenceStatus"], GEOM_PIXEL)
        self.assertEqual(result["status"], STATUS_UNKNOWN)
        self.assertEqual(result["candidateCount"], 0)

    def test_zero_candidates_do_not_claim_out_of_catalog_when_unverified(self):
        missing = _track(width=4, height=4, mask=[[1] * 4 for _ in range(4)])
        unverified = self.unverified.resolve(missing)
        self.assertEqual(unverified["catalogCoverageStatus"], COVERAGE_UNVERIFIED)
        self.assertEqual(unverified["status"], STATUS_UNKNOWN)
        self.assertNotEqual(unverified["status"], STATUS_OUT_OF_CATALOG)
        verified = self.verified.resolve(missing)
        self.assertEqual(verified["status"], STATUS_OUT_OF_CATALOG)

    def test_single_candidate_stays_unverified_without_complete_catalog(self):
        track = _track(width=3, height=1, mask=[[1, 1, 1]])
        unverified = self.unverified.resolve(track)
        verified = self.verified.resolve(track)
        self.assertEqual(unverified["status"], STATUS_SINGLE_UNVERIFIED)
        self.assertEqual(verified["status"], STATUS_UNIQUE)
        self.assertEqual(unverified["candidates"][0]["identityStatus"], IDENTITY_CANDIDATE)

    def test_real_catalog_isolates_illegal_geometry_and_sorts(self):
        report = self.real.isolation_report()
        self.assertGreaterEqual(report["isolatedCount"], 7)
        self.assertEqual(report["duplicateIds"], [])
        isolated_ids = {item["catalogId"] for item in report["isolated"]}
        self.assertIn("image34-0-0", isolated_ids)
        self.assertIn("image36-0-1", isolated_ids)
        self.assertNotIn("image15-1-2", isolated_ids)
        ones = _track(width=1, height=1, mask=[[1]])
        result = self.real.resolve(ones)
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertGreater(result["candidateCount"], 1)
        ids = [item["catalogId"] for item in result["candidates"]]
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(all(item["identityStatus"] == IDENTITY_CANDIDATE for item in result["candidates"]))
        self.assertEqual(result["catalogCoverageStatus"], COVERAGE_UNVERIFIED)

    def test_source_does_not_read_quality_price_or_pick_first(self):
        source = (CORE_DIR / "warehouse_catalog_geometry.py").read_text(encoding="utf-8")
        matching = source.split("def _geometry_faults")[0]
        for token in FORBIDDEN_MATCH_TOKENS:
            self.assertNotIn(token, matching)
        self.assertNotIn("item.get(\"Quality\")", source)
        self.assertNotIn("item.get(\"Value\")", source)
        self.assertNotIn("item.get(\"File\")", source)
        self.assertNotIn("knownItems", source)
        self.assertNotIn("canonical_history", source)
        self.assertNotIn("warehouse_vision", source)

    def test_resolver_does_not_mutate_physical_track(self):
        ledger = PhysicalComponentLedger("recCatGeo01")
        before = ledger.snapshot()
        track = _track(width=2, height=2, mask=[[1, 1], [1, 1]])
        resolve_catalog_candidates(track, index=self.unverified)
        self.assertEqual(ledger.snapshot(), before)
        self.assertNotIn("candidates", track)
        self.assertNotIn("name", track)

    def test_source_default_catalog_is_repo_assets(self):
        expected = (PROJECT_ROOT / "assets" / "catalog_065.json").resolve()
        self.assertFalse(getattr(sys, "frozen", False))
        self.assertEqual(default_catalog_path(), expected)
        self.assertTrue(expected.is_file())
        loaded = _load_catalog(None)
        self.assertIsInstance(loaded, list)
        self.assertGreater(len(loaded), 0)

    def test_frozen_default_catalog_uses_meipass_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            meipass = Path(tmp).resolve()
            bundled = meipass / "assets" / "catalog_065.json"
            bundled.parent.mkdir(parents=True)
            bundled.write_text("[]", encoding="utf-8")
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "_MEIPASS", str(meipass), create=True
            ):
                path = default_catalog_path()
                self.assertEqual(path, bundled)
                self.assertNotEqual(
                    path, (PROJECT_ROOT / "assets" / "catalog_065.json").resolve()
                )
                self.assertEqual(_load_catalog(None), [])

    def test_spec_bundles_catalog_under_assets(self):
        spec = (APP_DIR / "异环拍卖助手.spec").read_text(encoding="utf-8")
        self.assertIn(
            "(os.path.join(PROJECT_ROOT, 'assets', 'catalog_065.json'), 'assets')",
            spec,
        )


if __name__ == "__main__":
    unittest.main()
