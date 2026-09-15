"""Targeted verification test for warehouse placement resolution into Review Packet V2 (4D2D1Q-UAT14).

Covers:
- General principled placement resolution without object/dimension/anchor special casing.
- 绝对是亲手钓的鱼 (image10-0-0) -> 1 review unit (5x5).
- 万有星仪 (image27-0-2) -> 1 review unit (5x5, FULL + CLIPPED under single placement).
- Zero world-cell overlap between selected placements.
- Target raw fragment tracks converge into supportingTrackIds instead of individual review tasks.
- Identity proposals remain candidates with selectedCatalogId = None.
- V2 review packet schema validation PASS.
- WarehouseIdentityReviewSession opens the V2 packet cleanly.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(CORE_DIR),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from warehouse_catalog_geometry import CatalogGeometryIndex
from warehouse_identity_review import CatalogAuthority
from warehouse_identity_review_session import WarehouseIdentityReviewSession
from warehouse_placement_resolver import WarehousePlacementResolver
from warehouse_reconstruction import WarehouseReconstructionProcessor
from warehouse_review_packet import (
    SCHEMA_VERSION_V2,
    validate_warehouse_review_packet,
)


class TestWarehousePlacementResolutionV1(unittest.TestCase):
    def setUp(self):
        self.prev_path = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_overlap_v1" / "pair_a_prev.png"
        self.next_path = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_overlap_v1" / "pair_a_next.png"
        self.assertTrue(self.prev_path.is_file(), f"Missing fixture: {self.prev_path}")
        self.assertTrue(self.next_path.is_file(), f"Missing fixture: {self.next_path}")

        self.img_prev = cv2.imread(str(self.prev_path))
        self.img_next = cv2.imread(str(self.next_path))
        self.assertIsNotNone(self.img_prev)
        self.assertIsNotNone(self.img_next)

        catalog_path = PROJECT_ROOT / "assets" / "catalog_065.json"
        self.catalog_data = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else []
        self.authority = CatalogAuthority(self.catalog_data)
        self.catalog_index = CatalogGeometryIndex(self.catalog_data)

        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp_dir.name)
        self.store = SettlementEvidenceStoreV2(self.runtime_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_placement_resolution_production_slice(self):
        """Production placement resolver creates V2 review packet from real warehouse pair."""
        key = "rec_pair_a_prod_01"
        resolver = WarehousePlacementResolver()
        proc = WarehouseReconstructionProcessor(
            key,
            catalog_index=self.catalog_index,
            placement_resolver=resolver,
        )

        desc_prev = {
            "evidenceId": "ev_prev_pair_a",
            "recordStableKey": key,
            "sha256": "1" * 64,
            "kind": "warehouse-segment",
            "sequenceIndex": 0,
            "width": int(self.img_prev.shape[1]),
            "height": int(self.img_prev.shape[0]),
            "coverageStatus": "PARTIAL",
        }
        desc_next = {
            "evidenceId": "ev_next_pair_a",
            "recordStableKey": key,
            "sha256": "2" * 64,
            "kind": "warehouse-segment",
            "sequenceIndex": 1,
            "width": int(self.img_next.shape[1]),
            "height": int(self.img_next.shape[0]),
            "coverageStatus": "PARTIAL",
        }

        acc0 = proc.accept_segment(self.img_prev, desc_prev, sequence_index=0, already_cropped=True)
        self.assertTrue(acc0["accepted"])
        acc1 = proc.accept_segment(
            self.img_next,
            desc_next,
            sequence_index=1,
            overlap_proof={"trusted": True, "aligned": True, "offsetY": 90.0, "verticalOffsetPx": -90, "previousEvidenceId": "ev_prev_pair_a"},
            already_cropped=True,
        )
        self.assertTrue(acc1["accepted"])

        coverage_res = {
            "recordStableKey": key,
            "coverageStatus": "COMPLETE",
            "finalized": True,
            "terminationReason": "COMPLETE",
            "segments": [
                {"evidenceId": "ev_prev_pair_a", "sequenceIndex": 0, "sha256": "1" * 64},
                {"evidenceId": "ev_next_pair_a", "sequenceIndex": 1, "sha256": "2" * 64},
            ],
        }

        snap = proc.finalize(coverage_res)
        self.assertTrue(snap["packetAvailable"])

        packet = proc.packet_copy()
        self.assertIsNotNone(packet)
        self.assertEqual(packet["schemaVersion"], SCHEMA_VERSION_V2)

        # 1. Packet Schema Validation
        ok, reasons = validate_warehouse_review_packet(packet)
        self.assertTrue(ok, f"V2 review packet failed schema validation: {reasons}")

        review_units = packet.get("reviewUnits", [])
        self.assertGreater(len(review_units), 0)

        # 2. Verify 绝对是亲手钓的鱼 (image10-0-0)
        fish_units = [
            u for u in review_units
            if any(c.get("catalogId") == "image10-0-0" for c in u.get("candidates", []))
        ]
        self.assertEqual(len(fish_units), 1, "Fish (image10-0-0) must converge into exactly 1 Review Unit")
        fish_unit = fish_units[0]
        self.assertEqual(fish_unit["worldAnchor"], {"row": 5, "col": 0})
        self.assertEqual(fish_unit["footprint"], {"widthCells": 5, "heightCells": 5})
        self.assertEqual(fish_unit["placementStatus"], "RESOLVED")
        self.assertIsNone(fish_unit["selectedCatalogId"], "Identity must remain unconfirmed candidate proposal")
        self.assertGreaterEqual(len(fish_unit["supportingTrackIds"]), 1)
        self.assertEqual(fish_unit["candidates"][0]["name"], "绝对是亲手钓的鱼")
        self.assertEqual(fish_unit["candidates"][0]["catalogId"], "image10-0-0")

        # 3. Verify 万有星仪 (image27-0-2)
        inst_units = [
            u for u in review_units
            if any(c.get("catalogId") == "image27-0-2" for c in u.get("candidates", []))
        ]
        self.assertEqual(len(inst_units), 1, "Instrument (image27-0-2) must converge into exactly 1 Review Unit")
        inst_unit = inst_units[0]
        self.assertEqual(inst_unit["worldAnchor"], {"row": 0, "col": 0})
        self.assertEqual(inst_unit["footprint"], {"widthCells": 5, "heightCells": 5})
        self.assertEqual(inst_unit["placementStatus"], "RESOLVED")
        self.assertIsNone(inst_unit["selectedCatalogId"], "Identity must remain unconfirmed candidate proposal")
        self.assertGreaterEqual(len(inst_unit["supportingTrackIds"]), 1)
        self.assertEqual(inst_unit["candidates"][0]["name"], "万有星仪")
        self.assertEqual(inst_unit["candidates"][0]["catalogId"], "image27-0-2")

        # Check multi-frame observations for Instrument (FULL in prev + CLIPPED in next)
        inst_obs_statuses = [obs.get("status") for obs in inst_unit.get("observations", [])]
        self.assertIn("FULL", inst_obs_statuses)
        self.assertIn("CLIPPED", inst_obs_statuses)
        self.assertEqual(len(inst_unit["observations"]), 2)

        # 4. Verify 0 Overlap between Selected Placements
        fish_cells = set(
            (fish_unit["worldAnchor"]["row"] + r, fish_unit["worldAnchor"]["col"] + c)
            for r in range(fish_unit["footprint"]["heightCells"])
            for c in range(fish_unit["footprint"]["widthCells"])
        )
        inst_cells = set(
            (inst_unit["worldAnchor"]["row"] + r, inst_unit["worldAnchor"]["col"] + c)
            for r in range(inst_unit["footprint"]["heightCells"])
            for c in range(inst_unit["footprint"]["widthCells"])
        )
        self.assertTrue(
            fish_cells.isdisjoint(inst_cells),
            f"Fish cells {fish_cells} and Instrument cells {inst_cells} must not overlap",
        )

        # 5. Verify WarehouseIdentityReviewSession opens the V2 packet cleanly
        session = WarehouseIdentityReviewSession(catalog=self.authority)
        view = session.open(packet)
        self.assertTrue(view["available"])
        self.assertEqual(view["trackCount"], len(review_units))

    def test_placement_fail_closed_unknown(self):
        """Case A: Insufficient geometry / visual evidence must resolve to UNKNOWN without physicalGroupId."""
        import numpy as np
        img_empty = np.full((631, 600, 3), 40, dtype=np.uint8)
        desc_empty = [{"evidenceId": "ev_empty", "sequenceIndex": 0, "sha256": "0" * 64}]
        phys_empty = {"segments": [{"segmentId": "ev_empty", "sequenceIndex": 0}], "tracks": []}

        resolver = WarehousePlacementResolver()
        units = resolver.resolve(
            physical_ledger=phys_empty,
            descriptors=desc_empty,
            frames={"ev_empty": img_empty},
        )
        self.assertGreater(len(units), 0)
        for u in units:
            self.assertEqual(u["placementStatus"], "UNKNOWN")
            self.assertIsNone(u["physicalGroupId"])
            self.assertEqual(u["candidateStatus"], "UNKNOWN")
            self.assertEqual(len(u["candidates"]), 0)

    def test_placement_fail_closed_ambiguous_region(self):
        """Case B: Near-tie competing placement hypotheses must resolve to AMBIGUOUS_REGION."""
        import numpy as np
        img_sym = np.full((631, 600, 3), 40, dtype=np.uint8)
        x_lines = [1, 57, 113, 169, 225, 281, 337, 393, 449, 505, 561]
        y_lines = [0, 56, 112, 168, 224, 280, 336, 392, 448, 504, 560, 616]

        # Draw identical textured blocks causing competing overlapping rectangle partitions
        for r in [1, 2, 3]:
            for c in [1, 2]:
                img_sym[y_lines[r] + 8 : y_lines[r + 1] - 8, x_lines[c] + 8 : x_lines[c + 1] - 8] = (180, 140, 60)

        desc = [{"evidenceId": "ev_sym", "sequenceIndex": 0, "sha256": "3" * 64}]
        phys = {"segments": [{"segmentId": "ev_sym", "sequenceIndex": 0}], "tracks": []}

        resolver = WarehousePlacementResolver()
        units = resolver.resolve(
            physical_ledger=phys,
            descriptors=desc,
            frames={"ev_sym": img_sym},
        )
        
        ambiguous_units = [u for u in units if u["placementStatus"] == "AMBIGUOUS_REGION"]
        self.assertGreater(len(ambiguous_units), 0, "Near-tie hypotheses must produce AMBIGUOUS_REGION")
        for u in ambiguous_units:
            self.assertIsNone(u["physicalGroupId"])
            self.assertEqual(u["candidateStatus"], "AMBIGUOUS")

    def test_gutter_evidence_external_vs_internal(self):
        """Verify external boundary between target items is detected as strong gutter, while internal lines are not."""
        from warehouse_placement_resolver import pure_valley_gutter

        x_lines = [1, 57, 113, 169, 225, 281, 337, 393, 449, 505, 561]
        y_lines = [0, 56, 112, 168, 224, 280, 336, 392, 448, 504, 560, 616]

        # 1. External horizontal boundary between 万有星仪 (row 4) and 绝对是亲手钓的鱼 (row 5) at y=280
        ext_h_vals = [
            pure_valley_gutter(self.img_prev, y_lines[5], (x_lines[c], x_lines[c + 1]), "h")
            for c in range(5)
        ]
        ext_h_mean = sum(ext_h_vals) / len(ext_h_vals)
        self.assertGreaterEqual(ext_h_mean, 0.8, "External boundary at y=280 must be detected as strong gutter")

        # 2. Representative internal horizontal lines inside 万有星仪 (row 1->2 at y=112) and inside 绝对是亲手钓的鱼 (row 6->7 at y=392)
        int_inst_h_vals = [
            pure_valley_gutter(self.img_prev, y_lines[2], (x_lines[c], x_lines[c + 1]), "h")
            for c in range(5)
        ]
        int_inst_h_mean = sum(int_inst_h_vals) / len(int_inst_h_vals)
        self.assertLess(int_inst_h_mean, 0.5, "Internal grid line in 万有星仪 must not be upgraded to strong gutter")

        int_fish_h_vals = [
            pure_valley_gutter(self.img_prev, y_lines[7], (x_lines[c], x_lines[c + 1]), "h")
            for c in range(5)
        ]
        int_fish_h_mean = sum(int_fish_h_vals) / len(int_fish_h_vals)
        self.assertLess(int_fish_h_mean, 0.5, "Internal grid line in 绝对是亲手钓的鱼 must not be upgraded to strong gutter")

        # 3. Representative internal vertical lines inside target objects
        int_inst_v_vals = [
            pure_valley_gutter(self.img_prev, x_lines[2], (y_lines[r], y_lines[r + 1]), "v")
            for r in range(5)
        ]
        self.assertLess(sum(int_inst_v_vals) / len(int_inst_v_vals), 0.5)

    def test_settlement_runtime_wiring_defaults_to_v2_review_units(self):
        """Production capture session factory defaults to V2 placement review units without manual injection."""
        from warehouse_capture_production import make_production_session_factory

        frames = [self.img_prev, self.img_next, self.img_next]
        frame_idx = [0]

        def frame_provider(raw_scene=None):
            idx = frame_idx[0]
            if idx < len(frames):
                frame_idx[0] += 1
                return frames[idx]
            return frames[-1]

        class FakeOsAdapter:
            def wheel(self, delta, hwnd): pass
            def set_cursor_pos(self, x, y): pass
            def get_client_rect(self, hwnd): return (0, 0, 600, 631)
            def is_window(self, hwnd): return True
            def get_foreground_window(self): return 1234
            def set_foreground_window(self, hwnd): return True

        session_factory = make_production_session_factory(
            bindings_probe=lambda: {
                "isSettlement": True,
                "stable": True,
                "hwnd": 1234,
                "recordStableKey": "rec_pair_a_runtime_wiring",
                "scrollState": "TOP",
                "scene": "SETTLEMENT",
                "warehouseRoi": (0, 0, 600, 631),
            },
            os_adapter_factory=lambda: FakeOsAdapter(),
            store_factory=lambda: self.store,
            frame_provider_factory=lambda: frame_provider,
            scene_validator_factory=lambda: (lambda raw: {"is_settlement": True, "stable": True, "record_stable_key": "rec_pair_a_runtime_wiring"}),
        )

        class FakeCancelToken:
            def is_cancelled(self): return False

        # No placement_resolver or reconstruction_factory injected by test
        session = session_factory(
            scene={"scene": "SETTLEMENT"},
            cancellation_token=FakeCancelToken(),
            status_sink=None,
        )
        session._already_cropped = True
        session._max_steps = 2

        result = session.start()
        self.assertTrue(result["accepted"])
        packet = session.review_packet()
        self.assertIsNotNone(packet)

        # 1. Packet schema version and structure
        self.assertEqual(packet.get("schemaVersion"), SCHEMA_VERSION_V2)
        self.assertIn("reviewUnits", packet)
        self.assertNotIn("tracks", packet)

        ok, errors = validate_warehouse_review_packet(packet)
        self.assertTrue(ok, f"V2 schema validation failed: {errors}")

        review_units = packet["reviewUnits"]
        self.assertGreater(len(review_units), 0)

        # 2. 绝对是亲手钓的鱼 (image10-0-0) -> 1 review unit (5x5, anchor 5,0)
        fish_units = [
            u for u in review_units
            if any(c.get("catalogId") == "image10-0-0" for c in u.get("candidates", []))
        ]
        self.assertEqual(len(fish_units), 1, "Expected exactly 1 review unit for 绝对是亲手钓的鱼")
        fish_unit = fish_units[0]
        self.assertEqual(fish_unit["worldAnchor"], {"row": 5, "col": 0})
        self.assertEqual(fish_unit["footprint"], {"widthCells": 5, "heightCells": 5})
        self.assertEqual(fish_unit["placementStatus"], "RESOLVED")
        self.assertIsNone(fish_unit.get("selectedCatalogId"))
        self.assertGreater(len(fish_unit.get("supportingTrackIds") or []), 0)

        # 3. 万有星仪 (image27-0-2) -> 1 review unit (5x5, anchor 0,0, FULL+CLIPPED deduped)
        inst_units = [
            u for u in review_units
            if any(c.get("catalogId") == "image27-0-2" for c in u.get("candidates", []))
        ]
        self.assertEqual(len(inst_units), 1, "Expected exactly 1 review unit for 万有星仪")
        inst_unit = inst_units[0]
        self.assertEqual(inst_unit["worldAnchor"], {"row": 0, "col": 0})
        self.assertEqual(inst_unit["footprint"], {"widthCells": 5, "heightCells": 5})
        self.assertEqual(inst_unit["placementStatus"], "RESOLVED")
        self.assertIsNone(inst_unit.get("selectedCatalogId"))
        self.assertGreater(len(inst_unit.get("supportingTrackIds") or []), 0)

        # 4. Human review session navigation by reviewUnitId
        review_session = WarehouseIdentityReviewSession(
            store=self.store,
            catalog=self.authority,
            packet_provider=session.review_packet,
        )
        view = review_session.open()
        self.assertTrue(view["available"])
        self.assertEqual(view["trackCount"], len(review_units))
        self.assertEqual(view["currentTrackId"], review_units[0]["reviewUnitId"])


if __name__ == "__main__":
    unittest.main()
