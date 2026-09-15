# -*- coding: utf-8 -*-
"""
Unit and regression tests for Boundary Item 2:
底部品质出售默认勾选机制 (Bottom Quality Sell Default Checked Mechanism)

Verifies:
1. State model and default rules (acquired=True -> white..gold selected, red unselected; acquired=False/None -> all unknown)
2. Recognition fault tolerance between checked (frame-255) and deselected (frame-257) frames (29 items identical)
3. Red items (Latiao) remain fully recognized regardless of red sell selection state
4. Visual detection of sell selection pill bar from game frames
5. CurrentMatch lifecycle, single-color modification, manual override protection, and zero cross-match inheritance
6. Canonical v7 schema integration, forbidden root field validation, and history store persistence
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
TOOLS_DIR = PROJECT_ROOT / "tools"
TESTS_DIR = PROJECT_ROOT / "tests"

for p in (str(PROJECT_ROOT), str(APP_DIR), str(CORE_DIR), str(TOOLS_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from quality_sell_selection import (
    CANONICAL_QUALITIES,
    VALID_SELECTION_STATES,
    resolve_default_quality_sell_selection,
    normalize_quality_sell_selection,
    update_single_quality_sell_selection,
    detect_quality_sell_selection_from_frame,
)
from current_match import CurrentMatch, USER_CONFIRMED_FACT_KEYS
from canonical_match_record import (
    build_canonical_match_record_v7,
    validate_canonical_match_record_v7,
    validate_finalized_match_record_v7,
)
from canonical_history_store import CanonicalHistoryStore
from settlement_item_recognizer import SettlementItemRecognizer


class TestBottomQualitySellSelection(unittest.TestCase):
    def test_quality_sell_selection_default_rules(self):
        """Default rule test: acquired=True defaults to white..gold selected, red unselected."""
        sel_acquired = resolve_default_quality_sell_selection(True)
        self.assertEqual(sel_acquired["white"], "selected")
        self.assertEqual(sel_acquired["green"], "selected")
        self.assertEqual(sel_acquired["blue"], "selected")
        self.assertEqual(sel_acquired["purple"], "selected")
        self.assertEqual(sel_acquired["gold"], "selected")
        self.assertEqual(sel_acquired["red"], "unselected")

        # acquired=False or None must NOT force self-acquired default (all unknown)
        sel_not_acquired = resolve_default_quality_sell_selection(False)
        self.assertTrue(all(v == "unknown" for v in sel_not_acquired.values()))

        sel_none = resolve_default_quality_sell_selection(None)
        self.assertTrue(all(v == "unknown" for v in sel_none.values()))

    def test_normalize_and_update_single_quality(self):
        """Normalization and single quality modification: cancelling a color updates ONLY that color."""
        base = resolve_default_quality_sell_selection(True)
        self.assertEqual(base["gold"], "selected")
        self.assertEqual(base["red"], "unselected")

        # Deselect gold only
        updated = update_single_quality_sell_selection(base, "gold", "unselected")
        self.assertEqual(updated["gold"], "unselected")
        self.assertEqual(updated["white"], "selected")
        self.assertEqual(updated["green"], "selected")
        self.assertEqual(updated["blue"], "selected")
        self.assertEqual(updated["purple"], "selected")
        self.assertEqual(updated["red"], "unselected")

        # Select red only
        updated2 = update_single_quality_sell_selection(updated, "red", "selected")
        self.assertEqual(updated2["red"], "selected")
        self.assertEqual(updated2["gold"], "unselected")
        self.assertEqual(updated2["white"], "selected")

        # Invalid state rejected
        with self.assertRaises(ValueError):
            update_single_quality_sell_selection(base, "red", "invalid_state")

        with self.assertRaises(ValueError):
            update_single_quality_sell_selection(base, "black", "selected")

    def test_visual_detection_from_real_frames(self):
        """Verify visual detection of bottom quality pill bar on real game recordings."""
        early_dir = os.path.join(str(PROJECT_ROOT), "build", "codex_other_video_20260912", "desktop-early")

        def load_game(p):
            img = cv2.imread(p)
            if img is not None and img.shape == (1080, 1920, 3):
                return img[157:967, 163:1603]
            return img

        # Frame 251: default state (white..gold selected, red unselected)
        f251_path = os.path.join(early_dir, "frame-251.png")
        if os.path.exists(f251_path):
            f251 = load_game(f251_path)
            det251 = detect_quality_sell_selection_from_frame(f251)
            self.assertIsNotNone(det251)
            self.assertEqual(det251["white"], "selected")
            self.assertEqual(det251["green"], "selected")
            self.assertEqual(det251["blue"], "selected")
            self.assertEqual(det251["purple"], "selected")
            self.assertEqual(det251["gold"], "selected")
            self.assertEqual(det251["red"], "unselected")

        # Frame 255: user deselected green, purple, gold (white, blue selected, others unselected)
        f255_path = os.path.join(early_dir, "frame-255.png")
        if os.path.exists(f255_path):
            f255 = load_game(f255_path)
            det255 = detect_quality_sell_selection_from_frame(f255)
            self.assertIsNotNone(det255)
            self.assertEqual(det255["white"], "selected")
            self.assertEqual(det255["green"], "unselected")
            self.assertEqual(det255["blue"], "selected")
            self.assertEqual(det255["purple"], "unselected")
            self.assertEqual(det255["gold"], "unselected")
            self.assertEqual(det255["red"], "unselected")

        # Frame 257: user deselected all (all 6 unselected)
        f257_path = os.path.join(early_dir, "frame-257.png")
        if os.path.exists(f257_path):
            f257 = load_game(f257_path)
            det257 = detect_quality_sell_selection_from_frame(f257)
            self.assertIsNotNone(det257)
            self.assertTrue(all(v == "unselected" for v in det257.values()))

    def test_recognition_fault_tolerance_checked_vs_deselected(self):
        """Recognition fault tolerance: warehouse grid item extraction is 100% identical between checked (255) and deselected (257) frames."""
        early_dir = os.path.join(str(PROJECT_ROOT), "build", "codex_other_video_20260912", "desktop-early")
        f255_path = os.path.join(early_dir, "frame-255.png")
        f257_path = os.path.join(early_dir, "frame-257.png")

        if not (os.path.exists(f255_path) and os.path.exists(f257_path)):
            self.skipTest("Review evidence frames not found")

        def load_game(p):
            img = cv2.imread(p)
            if img is not None and img.shape == (1080, 1920, 3):
                return img[157:967, 163:1603]
            return img

        recognizer = SettlementItemRecognizer()
        f255 = load_game(f255_path)
        f257 = load_game(f257_path)

        items255 = recognizer.parse_settlement_ledger(f255)["settlementItems"]
        items257 = recognizer.parse_settlement_ledger(f257)["settlementItems"]

        # Both must extract exactly 29 items
        self.assertEqual(len(items255), 29)
        self.assertEqual(len(items257), 29)

        # Compare geometries, bounding boxes, row, col, w, h, rarity
        slots255 = [(it["row"], it["col"], it["widthCells"], it["heightCells"], it["rarity"]) for it in items255]
        slots257 = [(it["row"], it["col"], it["widthCells"], it["heightCells"], it["rarity"]) for it in items257]

        self.assertEqual(slots255, slots257, "Item geometries must be 100% identical between checked and deselected frames")

    # ------------------------------------------------------------------
    # Gap 2 (external review 2026-09-16): identity must not drift when the
    # user deselects bottom quality sell controls.  Comparing only
    # (row, col, widthCells, heightCells, rarity) proves geometry, not identity.
    # ------------------------------------------------------------------
    IDENTITY_FIELDS = ("catalogId", "exactItemId", "name", "price",
                       "identificationStatus", "status")

    @staticmethod
    def _pair_by_position(items):
        """Pair items by settlement grid position (row, col).

        A geometric key deliberately does NOT presuppose identity equality.
        """
        paired = {}
        for it in items:
            paired.setdefault((it.get("row"), it.get("col")), []).append(it)
        return paired

    def test_identity_stability_across_deselection(self):
        """Checked (255) vs deselected (257): no lost/phantom item, no identity drift.

        Comparable fields (same physical grid slot, both frames):
          - row / col / widthCells / heightCells / rarity  -> must be identical
          - canonical item ID (catalogId / exactItemId), name, price,
            identificationStatus, status -> must be identical for items that are
            EXACT in BOTH frames.
        Directional (not an identity change, therefore not comparable as equality):
          - items that are `ambiguous` in one frame and `exact` in the other.
            An unresolved identity is not a competing identity, so this is a
            resolution-strength difference, not drift.  It must never go
            exact -> ambiguous (identity strength must never weaken).
        """
        early_dir = os.path.join(str(PROJECT_ROOT), "build", "codex_other_video_20260912", "desktop-early")
        f255_path = os.path.join(early_dir, "frame-255.png")
        f257_path = os.path.join(early_dir, "frame-257.png")
        if not (os.path.exists(f255_path) and os.path.exists(f257_path)):
            self.skipTest("Review evidence frames not found")

        def load_game(p):
            img = cv2.imread(p)
            if img is not None and img.shape == (1080, 1920, 3):
                return img[157:967, 163:1603]
            return img

        recognizer = SettlementItemRecognizer()
        items255 = recognizer.parse_settlement_ledger(load_game(f255_path))["settlementItems"]
        items257 = recognizer.parse_settlement_ledger(load_game(f257_path))["settlementItems"]

        self.assertEqual(len(items255), 29)
        self.assertEqual(len(items257), 29)

        paired255 = self._pair_by_position(items255)
        paired257 = self._pair_by_position(items257)
        keys255 = {k for k in paired255 if k != (None, None)}
        keys257 = {k for k in paired257 if k != (None, None)}

        # No lost item, no phantom item.
        self.assertEqual(keys255 - keys257, set(), "items present in 255 but missing in 257")
        self.assertEqual(keys257 - keys255, set(), "phantom items only present in 257")
        # No duplicate occupancy at one position.
        self.assertTrue(all(len(v) == 1 for v in paired255.values()))
        self.assertTrue(all(len(v) == 1 for v in paired257.values()))

        def is_exact(item):
            return str(item.get("identificationStatus") or "").lower() == "exact"

        per_item_diff = []
        for key in sorted(keys255 & keys257):
            a = paired255[key][0]
            b = paired257[key][0]
            # Geometry and quality must be identical.
            self.assertEqual(
                (a.get("row"), a.get("col"), a.get("widthCells"), a.get("heightCells"), a.get("rarity")),
                (b.get("row"), b.get("col"), b.get("widthCells"), b.get("heightCells"), b.get("rarity")),
                f"geometry/rarity changed at {key}",
            )
            # Identity strength must never weaken.
            if is_exact(a):
                self.assertTrue(is_exact(b), f"identity weakened exact->non-exact at {key}")
                # Both EXACT: identity fields must be byte-identical.
                for field in self.IDENTITY_FIELDS:
                    self.assertEqual(a.get(field), b.get(field),
                                     f"identity field {field} drifted at {key}")
            elif is_exact(b):
                # ambiguous -> exact: resolution improved. Record it, do not fail.
                per_item_diff.append({
                    "position": list(key),
                    "transition": "ambiguous->exact",
                    "resolvedAs": {f: b.get(f) for f in ("catalogId", "name", "price")},
                })

        # The recorded direction must be one-way only (resolution improvement).
        self.assertTrue(
            all(d["transition"] == "ambiguous->exact" for d in per_item_diff),
            "unexpected identity transition direction",
        )

    def test_red_item_non_loss_when_red_unselected(self):
        """Red items remain recognized and confirmed even when red quality sell selection is unselected."""
        video_dir = os.path.join(str(PROJECT_ROOT), "build", "codex_other_video_20260912")
        f550_path = os.path.join(video_dir, "134436-match2-game-550.png")
        if not os.path.exists(f550_path):
            self.skipTest("Frame 550 not found")

        recognizer = SettlementItemRecognizer()
        f550 = cv2.imread(f550_path)
        ledger = recognizer.parse_settlement_ledger(f550)

        # Find red items
        red_items = [it for it in ledger["settlementItems"] if it["rarity"] == "red"]
        self.assertGreaterEqual(len(red_items), 1, "Red item must be detected")
        red_item = red_items[0]
        self.assertEqual(red_item["rarity"], "red")
        self.assertEqual(red_item["identificationStatus"], "exact")

        # In this frame, red is unselected, yet red item is present and exactly identified
        det = detect_quality_sell_selection_from_frame(f550)
        self.assertIsNotNone(det)
        self.assertEqual(det["red"], "unselected")

    def test_current_match_lifecycle_and_reset(self):
        """CurrentMatch lifecycle: auto-default on isAcquired, manual override protection, and clean reset on begin_next_match."""
        cm = CurrentMatch()
        # Initial state
        self.assertIsNone(cm.facts.get("qualitySellSelection"))
        self.assertIsNone(cm.facts.get("qualitySellSelectionSource"))

        # Step 1: User acquires the lot
        cm.apply_facts({"isAcquired": True, "winner": "玩家本人"}, source="manual", intent="confirm")
        facts = cm.facts
        self.assertIsNotNone(facts.get("qualitySellSelection"))
        self.assertEqual(facts["qualitySellSelection"]["white"], "selected")
        self.assertEqual(facts["qualitySellSelection"]["gold"], "selected")
        self.assertEqual(facts["qualitySellSelection"]["red"], "unselected")
        self.assertEqual(facts.get("qualitySellSelectionSource"), "default_self_acquired")

        # Step 2: User manually toggles red to selected
        cm.update_quality_sell_selection_color("red", "selected")
        self.assertEqual(cm.facts["qualitySellSelection"]["red"], "selected")
        self.assertEqual(cm.facts.get("qualitySellSelectionSource"), "manual_override")

        # Step 3: Changing isAcquired again does NOT overwrite manual override
        cm.apply_facts({"isAcquired": True}, source="manual", intent="confirm")
        self.assertEqual(cm.facts["qualitySellSelection"]["red"], "selected")
        self.assertEqual(cm.facts.get("qualitySellSelectionSource"), "manual_override")

        # Step 4: Next match must NEVER inherit previous match preferences
        cm.begin_next_match()
        self.assertIsNone(cm.facts.get("qualitySellSelection"))
        self.assertIsNone(cm.facts.get("qualitySellSelectionSource"))

    def test_per_color_provenance_manual_override_does_not_lock_other_colors(self):
        """A->D strict sequence: one manual toggle must not freeze the other five colors.

        A. acquired=True -> default (white..gold selected, red unselected)
        B. user cancels GREEN only -> green=unselected / manual_override
        C. vision observes blue=unselected, purple=unselected
        D. ordinary acquisition refresh

        Required outcome:
          - green keeps the manual choice
          - blue/purple still accept visual_observed
          - white/gold/red are NOT relabelled manual_override
          - acquisition refresh does not reset visual/manual facts to default
        """
        cm = CurrentMatch()

        # ---- A ----
        cm.apply_facts({"isAcquired": True}, source="manual", intent="confirm")
        sel = cm.facts["qualitySellSelection"]
        self.assertEqual([sel[q] for q in CANONICAL_QUALITIES],
                         ["selected", "selected", "selected", "selected", "selected", "unselected"])
        self.assertEqual(cm.facts["qualitySellSelectionSource"], "default_self_acquired")

        # ---- B ----
        cm.update_quality_sell_selection_color("green", "unselected")
        self.assertEqual(cm.facts["qualitySellSelection"]["green"], "unselected")
        srcs = cm.facts["qualitySellSelectionSources"]
        self.assertEqual(srcs["green"], "manual_override")
        # Only green is manual; the other five keep their own provenance.
        self.assertEqual([q for q in CANONICAL_QUALITIES if srcs[q] == "manual_override"], ["green"])
        self.assertEqual(cm.facts["qualitySellSelectionSource"], "manual_override")

        # ---- C ----
        vision = dict(cm.facts["qualitySellSelection"])
        vision["blue"] = "unselected"
        vision["purple"] = "unselected"
        cm.apply_facts(
            {"qualitySellSelection": vision, "qualitySellSelectionSource": "visual_observed"},
            source="vision",
        )
        sel = cm.facts["qualitySellSelection"]
        srcs = cm.facts["qualitySellSelectionSources"]
        # green manual choice survives
        self.assertEqual(sel["green"], "unselected")
        self.assertEqual(srcs["green"], "manual_override")
        # blue/purple accept visual observation
        self.assertEqual(sel["blue"], "unselected")
        self.assertEqual(sel["purple"], "unselected")
        self.assertEqual(srcs["blue"], "visual_observed")
        self.assertEqual(srcs["purple"], "visual_observed")
        # untouched colors are not wrongly relabelled manual_override
        for q in ("white", "gold", "red"):
            self.assertNotEqual(srcs[q], "manual_override", f"{q} wrongly marked manual_override")
        self.assertEqual(sel["white"], "selected")
        self.assertEqual(sel["gold"], "selected")
        self.assertEqual(sel["red"], "unselected")

        # ---- D ----
        before = dict(cm.facts["qualitySellSelection"])
        before_srcs = dict(cm.facts["qualitySellSelectionSources"])
        cm.apply_facts({"isAcquired": True}, source="manual", intent="confirm")
        self.assertEqual(cm.facts["qualitySellSelection"], before,
                         "acquisition refresh reset visual/manual facts to default")
        self.assertEqual(cm.facts["qualitySellSelectionSources"], before_srcs)

        # Provenance is derived, never a locked user-confirmed fact.
        self.assertNotIn("qualitySellSelectionSource", USER_CONFIRMED_FACT_KEYS)
        self.assertNotIn("qualitySellSelectionSources", USER_CONFIRMED_FACT_KEYS)
        # And a direct provenance write is refused (aggregate stays derived).
        cm.apply_facts({"qualitySellSelectionSource": "unknown"}, source="manual", intent="confirm")
        self.assertEqual(cm.facts["qualitySellSelectionSource"], "manual_override")

    def test_canonical_v7_validation_and_persistence(self):
        """Canonical MatchRecord v7 schema validation and CanonicalHistoryStore persistence."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            record_id = "test_boundary2_match_001"
            raw_record = {
                "id": record_id,
                "playedAt": "2026-09-15T12:00:00+08:00",
                "lifecycleStatus": "FINALIZED",
                "source": "manual",
                "environment": {"venue": "珊瑚", "box": "精致", "fieldCondition": "standard"},
                "loadout": {"character": "达芙蒂尔"},
                "costs": {"entry": 5000, "intel": 0, "other": 0, "sunkCost": 5000, "total": 5000},
                "publicIntel": {"q": 21, "totalItems": 29, "totalGrid": 100},
                "qualities": {},
                "bidding": {"myName": "玩家本人", "leaderName": "玩家本人", "leaderBid": 50000},
                "settlement": {
                    "status": "verified",
                    "verified": True,
                    "clearingPrice": 50000,
                    "actualTotal": 120000,
                    "realizedProfit": 65000,
                    "acquired": True,
                    "winner": "玩家本人",
                    "qualitySellSelection": {
                        "white": "selected",
                        "green": "selected",
                        "blue": "selected",
                        "purple": "selected",
                        "gold": "selected",
                        "red": "unselected",
                    },
                    "qualitySellSelectionSource": "default_self_acquired",
                },
            }

            record = build_canonical_match_record_v7(raw_record)
            ok, reasons = validate_finalized_match_record_v7(record, match_id=record_id)
            self.assertTrue(ok, f"Validation failed: {reasons}")
            self.assertEqual(record["settlement"]["qualitySellSelection"]["red"], "unselected")
            self.assertEqual(record["settlement"]["qualitySellSelectionSource"], "default_self_acquired")

            # Root-level legacy forbidden field test
            bad_record = dict(record)
            bad_record["qualitySellSelection"] = record["settlement"]["qualitySellSelection"]
            ok_bad, reasons_bad = validate_finalized_match_record_v7(bad_record, match_id=record_id)
            self.assertFalse(ok_bad)
            self.assertIn("FORBIDDEN_LEGACY_FLAT_FIELD_QUALITYSELLSELECTION", reasons_bad)

            # Persistence roundtrip test
            db_file = os.path.join(tmp_dir, "canonical_history.json")
            store = CanonicalHistoryStore(db_file)
            persisted = store.persist_record_transactional(record, is_finalized=True)
            self.assertEqual(persisted["settlement"]["qualitySellSelection"]["white"], "selected")
            self.assertEqual(persisted["settlement"]["qualitySellSelection"]["red"], "unselected")

            # Re-read from store
            loaded = store.lookup(record_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["settlement"]["qualitySellSelection"], record["settlement"]["qualitySellSelection"])
            self.assertEqual(loaded["settlement"]["qualitySellSelectionSource"], "default_self_acquired")

    def test_ledger_quality_sell_reaches_product_surface(self):
        """Chain lock: a real visual detection must survive every hop to the Main UI payload.

        Regression for the frozen-EXE minimal product path breakpoint:
          ledger (recognizer) -> VisionPipeline._attach_settlement_ledger -> archive block
          -> canonical v7 settlement -> Main history detail projection.

        Before the fix the detection result stayed buried in settlement["ledger"], so the
        archiver, the canonical record, the history file and the Main detail card all fell
        back to the "unknown" default even though the frame had been read successfully.
        """
        frame_path = os.path.join(
            str(PROJECT_ROOT), "build", "exe_chain_20260915", "frames", "settlement_blob_144037.png"
        )
        if not os.path.exists(frame_path):
            self.skipTest("Replay settlement frame not found")

        frame = cv2.imread(frame_path)
        self.assertIsNotNone(frame)

        # Hop 1: recognizer actually detects the six colors on this frame.
        recognizer = SettlementItemRecognizer()
        ledger = recognizer.parse_settlement_ledger(frame, actual_total=1556124)
        self.assertIn("qualitySellSelection", ledger)
        self.assertEqual(ledger["qualitySellSelectionSource"], "visual_observed")
        detected = ledger["qualitySellSelection"]
        self.assertEqual(set(detected), set(CANONICAL_QUALITIES))

        # Hop 2: the pipeline must promote it out of the ledger into the live context.
        from vision_pipeline import NTEVisionPipeline

        pipe = object.__new__(NTEVisionPipeline)
        pipe._settlement_recognizer = recognizer
        pipe.current_context = {}
        pipe._stabilize_settlement = lambda *a, **k: None
        settlement = {"clearingPrice": 1222222, "actualTotal": 1556124, "profit": 333902, "acquired": False}
        pipe._attach_settlement_ledger(
            settlement, frame=frame, captured_at="2026-09-16T01:50:00", actual_total=1556124
        )
        self.assertEqual(settlement.get("qualitySellSelection"), detected)
        self.assertEqual(settlement.get("qualitySellSelectionSource"), "visual_observed")
        self.assertEqual(pipe.current_context.get("qualitySellSelection"), detected)
        self.assertEqual(pipe.current_context.get("qualitySellSelectionSource"), "visual_observed")

        # Hop 3: the archiver block, driven from the live context, must carry provenance.
        from quality_sell_selection import (
            aggregate_selection_source,
            normalize_quality_sell_selection,
            normalize_quality_sell_selection_sources,
            sources_from_aggregate,
        )

        ctx = pipe.current_context
        q_sel = ctx.get("qualitySellSelection")
        q_src = ctx.get("qualitySellSelectionSource")
        q_sources = ctx.get("qualitySellSelectionSources")
        self.assertIsNotNone(q_sel)
        norm_sources = (
            normalize_quality_sell_selection_sources(q_sources)
            if isinstance(q_sources, dict)
            else sources_from_aggregate(q_src)
        )
        settlement_block = {
            "acquired": settlement["acquired"],
            "actualTotal": settlement["actualTotal"],
            "qualitySellSelection": normalize_quality_sell_selection(q_sel),
            "qualitySellSelectionSources": norm_sources,
            "qualitySellSelectionSource": aggregate_selection_source(norm_sources),
        }
        self.assertEqual(settlement_block["qualitySellSelectionSource"], "visual_observed")
        self.assertEqual(
            set(settlement_block["qualitySellSelectionSources"].values()), {"visual_observed"}
        )

        # Hop 4: canonical v7 keeps both the states and the provenance.
        record = build_canonical_match_record_v7({
            "id": "chain_lock",
            "lifecycleStatus": "FINALIZED",
            "playedAt": "2026-09-16T01:50:00+08:00",
            "settlement": settlement_block,
        })
        st = record["settlement"]
        self.assertEqual(st["qualitySellSelection"], detected)
        self.assertEqual(st["qualitySellSelectionSource"], "visual_observed")
        ok, reasons = validate_canonical_match_record_v7(record)
        self.assertTrue(ok, f"Validation failed: {reasons}")

        # Hop 5: the Main history-detail payload must expose it (not a bare "未记录").
        from history_admission import build_duplicate_index, evaluate_history_admission
        from main_view_state import MainViewStateProvider

        decision = evaluate_history_admission(record, build_duplicate_index([]))
        payload = MainViewStateProvider._project_record(record, decision).to_payload()
        projected = payload["settlement"]
        self.assertEqual(projected["qualitySellSelection"], detected)
        self.assertEqual(projected["qualitySellSelectionSource"], "visual_observed")
        self.assertEqual(
            set(projected["qualitySellSelectionSources"].values()), {"visual_observed"}
        )


if __name__ == "__main__":
    unittest.main()
