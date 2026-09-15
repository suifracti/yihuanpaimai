"""Targeted End-to-End Integration Test for Settlement V2 Review (4D2D1Q-UAT18).

Proves the complete runtime chain:
Production Settlement Capture (make_production_session_factory)
  -> V2 Review Packet (reviewUnits[])
  -> WarehouseIdentityReviewSession (reviewUnitId navigation + human decision)
  -> Real Product Persist (persist_warehouse_identity_review)
  -> Isolated Canonical History (MatchRecord v7 round-trip)
  -> Label Exporter Fail-Closed Check (UNSUPPORTED_V2_SCHEMA)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import (
    build_canonical_match_record_v7,
    validate_canonical_match_record_v7,
)
from runtime_data import HISTORY_FILENAME
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from warehouse_capture_production import make_production_session_factory
from warehouse_identity_review import (
    ACTION_CONFIRM,
    CatalogAuthority,
    REVIEW_SCHEMA_V2,
    validate_warehouse_identity_review,
)
from warehouse_identity_review_persist import (
    persist_warehouse_identity_review,
    summarize_persisted_identity_review,
)
from warehouse_identity_review_session import WarehouseIdentityReviewSession
from warehouse_review_packet import (
    SCHEMA_VERSION_V2 as PACKET_SCHEMA_V2,
    validate_warehouse_review_packet,
)
from warehouse_reviewed_label_export import export_reviewed_label_dataset

PROD_HISTORY_PATH = r"C:\Users\Administrator\AppData\Local\异环拍卖助手\data\history\异环拍卖数据.json"


class TestSettlementV2ReviewEndToEnd(unittest.TestCase):
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

        # Isolated data root for this test run
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp_dir.name).resolve()
        self.store = SettlementEvidenceStoreV2(self.runtime_root)

        # Snapshot production history file state to verify 0 mutation
        self.prod_history_before_bytes = None
        if os.path.exists(PROD_HISTORY_PATH):
            with open(PROD_HISTORY_PATH, "rb") as f:
                self.prod_history_before_bytes = f.read()

    def tearDown(self):
        # Assert production history file was never touched during this test
        if self.prod_history_before_bytes is not None and os.path.exists(PROD_HISTORY_PATH):
            with open(PROD_HISTORY_PATH, "rb") as f:
                prod_after_bytes = f.read()
            self.assertEqual(
                hashlib.sha256(self.prod_history_before_bytes).hexdigest(),
                hashlib.sha256(prod_after_bytes).hexdigest(),
                "Production History must remain 100% untouched during test",
            )
        self.temp_dir.cleanup()

    def test_settlement_v2_review_end_to_end_capture_review_persist(self):
        """Full end-to-end flow: capture -> V2 packet -> human review -> product persist -> isolated history round-trip."""
        key = "rec_e2e_settlement_v2_001"

        # 1. Setup isolated Canonical History Store and seed an initial DRAFT match record
        history_dir = self.runtime_root / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_path = history_dir / HISTORY_FILENAME
        history_store = CanonicalHistoryStore(str(history_path))

        raw_draft = build_canonical_match_record_v7(
            match_id=key,
            lifecycle_status="DRAFT",
            played_at="2026-08-31T15:00:00Z",
            source="live_capture",
        )
        history_store.persist_record_transactional(raw_draft, is_finalized=False)

        # 2. Production Settlement Capture Ownership (make_production_session_factory)
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
                "recordStableKey": key,
                "scrollState": "TOP",
                "scene": "SETTLEMENT",
                "warehouseRoi": (0, 0, 600, 631),
            },
            os_adapter_factory=lambda: FakeOsAdapter(),
            store_factory=lambda: self.store,
            frame_provider_factory=lambda: frame_provider,
            scene_validator_factory=lambda: (lambda raw: {"is_settlement": True, "stable": True, "record_stable_key": key}),
        )

        class FakeCancelToken:
            def is_cancelled(self): return False

        # No placement_resolver, reconstruction_factory, mock packet, or mock artifact is injected
        session = session_factory(
            scene={"scene": "SETTLEMENT"},
            cancellation_token=FakeCancelToken(),
            status_sink=None,
        )
        session._already_cropped = True
        session._max_steps = 2

        capture_result = session.start()
        self.assertTrue(capture_result["accepted"])
        packet = session.review_packet()
        self.assertIsNotNone(packet)

        # Verify Capture produced V2 review packet
        self.assertEqual(packet.get("schemaVersion"), PACKET_SCHEMA_V2)
        self.assertIn("reviewUnits", packet)
        self.assertNotIn("tracks", packet)

        ok, errors = validate_warehouse_review_packet(packet)
        self.assertTrue(ok, f"V2 review packet schema validation failed: {errors}")

        review_units = packet["reviewUnits"]
        self.assertGreater(len(review_units), 0)

        # Verify target items in reviewUnits
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

        # 3. Real WarehouseIdentityReviewSession Navigation and Human Decision
        review_session = WarehouseIdentityReviewSession(
            store=self.store,
            catalog=self.authority,
            packet_provider=session.review_packet,
        )
        view = review_session.open()
        self.assertTrue(view["available"])
        self.assertEqual(view["trackCount"], len(review_units))
        self.assertEqual(view["currentTrackId"], review_units[0]["reviewUnitId"])

        # Proposal != Truth: Before explicit confirmation, no resolved truth exists
        self.assertIsNone(review_session.artifact_copy())

        # Perform human review: Navigate to 绝对是亲手钓的鱼 and confirm candidate
        fish_unit_id = fish_unit["reviewUnitId"]
        review_session.select_track(fish_unit_id)
        review_session.select_candidate("image10-0-0")
        apply_res = review_session.apply({"action": ACTION_CONFIRM, "confirmCandidate": True})
        self.assertTrue(apply_res.get("available"))

        # Finalize human review session
        fin_view = review_session.finalize(reviewed_at="2026-08-31T15:30:00Z")
        self.assertTrue(fin_view.get("available"))

        reviewed_art = review_session.artifact_copy()
        self.assertIsNotNone(reviewed_art)
        self.assertEqual(reviewed_art["schemaVersion"], REVIEW_SCHEMA_V2)

        ok, val_errs = validate_warehouse_identity_review(reviewed_art)
        self.assertTrue(ok, f"V2 review artifact validation failed: {val_errs}")

        # Assert only the human-confirmed item is in resolvedItems
        self.assertEqual(len(reviewed_art["resolvedItems"]), 1)
        confirmed_fish = reviewed_art["resolvedItems"][0]
        self.assertEqual(confirmed_fish["reviewUnitId"], fish_unit_id)
        self.assertEqual(confirmed_fish["catalogId"], "image10-0-0")
        self.assertEqual(confirmed_fish["name"], "绝对是亲手钓的鱼")
        self.assertEqual(confirmed_fish["provenanceType"], "HUMAN_REVIEWED_CATALOG_ID")

        # Unconfirmed items (including 万有星仪) must NOT be in resolvedItems
        self.assertFalse(any(it.get("catalogId") == "image27-0-2" for it in reviewed_art["resolvedItems"]))

        # 4. Real Product Persist Ownership
        binding = review_session.persist_binding()
        self.assertIsNotNone(binding)

        persist_res = persist_warehouse_identity_review(
            session=review_session,
            history_store=history_store,
            session_id=binding["sessionId"],
            packet_fingerprint=binding["packetFingerprint"],
            record_stable_key=key,
        )
        self.assertTrue(persist_res["ok"])
        self.assertTrue(persist_res["written"])

        # 5. History Round-Trip and Full Provenance Fidelity
        loaded_record = history_store.lookup(key)
        self.assertIsNotNone(loaded_record)

        ok, canonical_reasons = validate_canonical_match_record_v7(loaded_record, match_id=key)
        self.assertTrue(ok, f"Canonical MatchRecord v7 validation failed: {canonical_reasons}")

        stored_art = loaded_record["settlement"]["warehouseIdentityReview"]
        self.assertEqual(stored_art["schemaVersion"], REVIEW_SCHEMA_V2)
        self.assertEqual(stored_art["recordStableKey"], key)
        self.assertEqual(stored_art["packetFingerprint"], reviewed_art["packetFingerprint"])
        self.assertEqual(stored_art["artifactFingerprint"], reviewed_art["artifactFingerprint"])

        self.assertEqual(len(stored_art["resolvedItems"]), 1)
        stored_fish = stored_art["resolvedItems"][0]
        self.assertEqual(stored_fish["reviewUnitId"], fish_unit_id)
        self.assertEqual(stored_fish["physicalGroupId"], fish_unit.get("physicalGroupId"))
        self.assertEqual(stored_fish["supportingTrackIds"], fish_unit["supportingTrackIds"])
        self.assertEqual(stored_fish["catalogId"], "image10-0-0")
        self.assertEqual(stored_fish["name"], "绝对是亲手钓的鱼")
        self.assertEqual(stored_fish["worldAnchor"], {"row": 5, "col": 0})
        self.assertEqual(stored_fish["footprint"], {"widthCells": 5, "heightCells": 5})
        self.assertEqual(stored_fish["provenanceType"], "HUMAN_REVIEWED_CATALOG_ID")
        self.assertTrue(bool(stored_fish["evidenceId"]))
        self.assertEqual(len(stored_fish["sha256"]), 64)
        self.assertEqual(len(stored_fish["bbox"]), 4)

        # 6. Check summary helper
        summary = summarize_persisted_identity_review(loaded_record)
        self.assertTrue(summary["saved"])
        self.assertTrue(summary["readable"])
        self.assertEqual(summary["resolvedCount"], 1)

        # 7. Training Exporter Fail-Closed Verification
        out_dir = self.runtime_root / "export_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = export_reviewed_label_dataset(runtime_root=self.runtime_root, output_dir=out_dir)
        self.assertEqual(len(manifest["samples"]), 0)
        self.assertTrue(any(r.get("reason") == "UNSUPPORTED_V2_SCHEMA" for r in manifest["rejected"]))


if __name__ == "__main__":
    unittest.main()
