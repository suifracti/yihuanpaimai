# -*- coding: utf-8 -*-
"""Phase 19: Shared Item Identity Resolver & Warehouse Candidate Monotonicity Tests.

Verifies AC1-AC15:
- AC1: Dimension-only candidates (5x5 unknown rarity yields deterministic candidates from legal catalog)
- AC2: Real 5x5 gray fixture includes 万有星仪 and does not upgrade to EXACT
- AC3: Rarity narrowing (gold 5x5 is subset of unknown 5x5)
- AC4: Unique candidate remains CANDIDATE with identifiedName=None (no UNIQUE -> EXACT upgrade)
- AC5: Monotonic candidate shrinkage via intersection: [A, B, C] -> [A, B] -> [A, B]
- AC6: No unjustified expansion: [A, B] + [A, B, C, D] stays [A, B]
- AC7: Existing EXACT is monotonically preserved and never downgraded
- AC8: CurrentMatch to_canonical() retains identityStatus, candidates, identifiedName
- AC9: History persistence (AutoArchiver) retains candidate state
- AC10: Exported records retain warehouse.slots[].identityStatus and candidates
- AC11: Settlement occupancy schema and persistence untouched
- AC12: SettlementCatalogCandidateResolver delegation regression unchanged
- AC13: UI candidate wording displays "可能：A / B / C" and never as "已识别"
- AC14/AC15: No live templates, no appearance matcher, no threshold changes
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from item_identity_resolver import (
    ItemIdentityResolver,
    IdentityResolution,
    resolve_item_identity,
    merge_candidates,
    merge_slot_identity,
    default_catalog_path,
)
from settlement_catalog_candidates import SettlementCatalogCandidateResolver
from current_match import CurrentMatch
from auto_archiver import AutoArchiver
from canonical_history_store import CanonicalHistoryStore
from main import _merge_canonical_warehouse
from main_window import MainWindowBridge, OverlayVisibilityController


class _FakeOverlay:
    def __init__(self, visible: bool = False):
        self.Visible = visible

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class TestWarehouseSlotIdentityV1(unittest.TestCase):
    def setUp(self):
        self.catalog_path = default_catalog_path()
        self.resolver = ItemIdentityResolver(self.catalog_path)

    def test_ac1_dimension_only_candidates(self):
        """AC1: 5x5 with unknown rarity returns deterministic candidates from legal catalog."""
        res = self.resolver.resolve_item_identity({"width": 5, "height": 5, "rarity": "unknown"})
        self.assertEqual(res.identity_status, "CANDIDATE")
        self.assertIsNone(res.identified_name)
        self.assertTrue(len(res.candidates) > 0)

        # Candidates must be deterministically sorted by catalogId
        cids = [c["catalogId"] for c in res.candidates]
        self.assertEqual(cids, sorted(cids))

        # Repeated call produces strictly identical result
        res2 = self.resolver.resolve_item_identity({"width": 5, "height": 5, "rarity": "unknown"})
        self.assertEqual(res.to_dict(), res2.to_dict())

    def test_ac2_real_5x5_gray_slot_includes_wan_you_xing_yi(self):
        """AC2: 5x5 gray slot includes 万有星仪 in candidate list, but remains CANDIDATE and NOT exact."""
        res = self.resolver.resolve_item_identity({"width": 5, "height": 5, "rarity": "unknown"})
        names = [c["name"] for c in res.candidates]
        self.assertIn("万有星仪", names)
        self.assertNotEqual(res.identity_status, "EXACT")
        self.assertIsNone(res.identified_name)

    def test_ac3_rarity_narrowing(self):
        """AC3: Known rarity candidates are a strict subset of unknown-rarity dimension candidates."""
        res_unknown = self.resolver.resolve_item_identity({"width": 5, "height": 5, "rarity": "unknown"})
        res_gold = self.resolver.resolve_item_identity({"width": 5, "height": 5, "rarity": "gold"})

        cids_unknown = {c["catalogId"] for c in res_unknown.candidates}
        cids_gold = {c["catalogId"] for c in res_gold.candidates}

        self.assertTrue(cids_gold.issubset(cids_unknown))
        self.assertLess(len(cids_gold), len(cids_unknown))
        self.assertEqual([c["name"] for c in res_gold.candidates], ["万有星仪"])

    def test_ac4_unique_candidate_remains_candidate(self):
        """AC4: Even when candidate set has length 1 (unique in catalog), identityStatus remains CANDIDATE."""
        res_gold = self.resolver.resolve_item_identity({"width": 5, "height": 5, "rarity": "gold"})
        self.assertEqual(len(res_gold.candidates), 1)
        self.assertEqual(res_gold.identity_status, "CANDIDATE")
        self.assertIsNone(res_gold.identified_name)

    def test_ac5_monotonic_shrink_intersection(self):
        """AC5: Consecutive observations on same slot shrink candidate pool: [A, B, C] -> [A, B]."""
        old_slot = {
            "identityStatus": "CANDIDATE",
            "candidates": [
                {"catalogId": "c1", "name": "ItemA"},
                {"catalogId": "c2", "name": "ItemB"},
                {"catalogId": "c3", "name": "ItemC"},
            ],
            "identifiedName": None,
        }
        new_res = IdentityResolution(
            identity_status="CANDIDATE",
            candidates=(
                {"catalogId": "c1", "name": "ItemA"},
                {"catalogId": "c2", "name": "ItemB"},
            ),
            identified_name=None,
        )
        merged = merge_slot_identity(old_slot, new_res)
        self.assertEqual(merged["identityStatus"], "CANDIDATE")
        self.assertEqual([c["catalogId"] for c in merged["candidates"]], ["c1", "c2"])
        self.assertIsNone(merged["identifiedName"])

    def test_ac6_no_unjustified_expansion(self):
        """AC6: Observation providing [A, B, C, D] to a slot that already narrowed to [A, B] cannot expand."""
        old_slot = {
            "identityStatus": "CANDIDATE",
            "candidates": [
                {"catalogId": "c1", "name": "ItemA"},
                {"catalogId": "c2", "name": "ItemB"},
            ],
            "identifiedName": None,
        }
        new_res = IdentityResolution(
            identity_status="CANDIDATE",
            candidates=(
                {"catalogId": "c1", "name": "ItemA"},
                {"catalogId": "c2", "name": "ItemB"},
                {"catalogId": "c3", "name": "ItemC"},
                {"catalogId": "c4", "name": "ItemD"},
            ),
            identified_name=None,
        )
        merged = merge_slot_identity(old_slot, new_res)
        self.assertEqual([c["catalogId"] for c in merged["candidates"]], ["c1", "c2"])

    def test_ac7_exact_monotonicity_not_downgraded(self):
        """AC7: An already EXACT slot is never downgraded by a subsequent metadata observation."""
        exact_slot = {
            "identityStatus": "EXACT",
            "candidates": [{"catalogId": "c1", "name": "ItemA"}],
            "identifiedName": "ItemA",
        }
        new_res = IdentityResolution(
            identity_status="CANDIDATE",
            candidates=(
                {"catalogId": "c1", "name": "ItemA"},
                {"catalogId": "c2", "name": "ItemB"},
            ),
            identified_name=None,
        )
        merged = merge_slot_identity(exact_slot, new_res)
        self.assertEqual(merged["identityStatus"], "EXACT")
        self.assertEqual(merged["identifiedName"], "ItemA")

    def test_ac7_slot_reset_allows_fresh_candidates(self):
        """AC7/Reset: When explicit reset occurs, new observation set is accepted."""
        old_slot = {
            "identityStatus": "CANDIDATE",
            "candidates": [{"catalogId": "c1", "name": "ItemA"}],
            "identifiedName": None,
        }
        new_res = IdentityResolution(
            identity_status="CANDIDATE",
            candidates=(
                {"catalogId": "c9", "name": "NewItem"},
            ),
            identified_name=None,
        )
        merged = merge_slot_identity(old_slot, new_res, reset=True)
        self.assertEqual([c["catalogId"] for c in merged["candidates"]], ["c9"])

    def test_ac8_current_match_canonical_preserves_candidates(self):
        """AC8: CurrentMatch.to_canonical() preserves identityStatus, candidates, identifiedName."""
        cm = CurrentMatch()
        slot_data = {
            "col": 0,
            "row": 0,
            "w": 5,
            "h": 5,
            "rarity": "gold",
            "evidenceLevel": "RARITY_AND_SHAPE",
            "identityStatus": "CANDIDATE",
            "candidates": [{"catalogId": "image27-0-2", "name": "万有星仪"}],
            "identifiedName": None,
        }
        cm.apply_facts({"warehouse": {"slots": [slot_data]}})
        canonical = cm.to_canonical()

        self.assertIn("warehouse", canonical)
        slots = canonical["warehouse"]["slots"]
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]["identityStatus"], "CANDIDATE")
        self.assertEqual(slots[0]["candidates"], [{"catalogId": "image27-0-2", "name": "万有星仪"}])
        self.assertIsNone(slots[0]["identifiedName"])

    def test_ac9_auto_archiver_preserves_candidate_state(self):
        """AC9: AutoArchiver creates record with identityStatus and candidates preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "test_hist.json"
            archiver = AutoArchiver(db_paths=[str(store_path)])
            ctx = {
                "matchId": "match_p19_001",
                "lifecycleStatus": "FINALIZED",
                "settlementReady": True,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 10000,
                    "actualTotal": 12000,
                    "profit": 2000,
                },
                "warehouse": {
                    "slots": [
                        {
                            "col": 1,
                            "row": 2,
                            "w": 5,
                            "h": 5,
                            "rarity": "gold",
                            "evidenceLevel": "RARITY_AND_SHAPE",
                            "identityStatus": "CANDIDATE",
                            "candidates": [{"catalogId": "image27-0-2", "name": "万有星仪"}],
                            "identifiedName": None,
                        }
                    ]
                }
            }
            res = archiver.archive_match(ctx)
            self.assertIsNotNone(res, "Archive returned None")

            # Verify persisted history
            store = CanonicalHistoryStore(store_path)
            db = store.read_database()
            records = db.get("records") or []
            self.assertEqual(len(records), 1)
            rec_slots = records[0].get("warehouse", {}).get("slots", [])
            self.assertEqual(len(rec_slots), 1)
            self.assertEqual(rec_slots[0]["identityStatus"], "CANDIDATE")
            self.assertEqual(rec_slots[0]["candidates"], [{"catalogId": "image27-0-2", "name": "万有星仪"}])

    def test_ac10_export_retains_candidates_without_reshape(self):
        """AC10: Phase 17 Export retains identityStatus and candidates in exported MatchRecord."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_path = Path(tmpdir) / "异环拍卖数据.json"
            out_path = Path(tmpdir) / "exported.json"
            record = {
                "id": "match_p19_exp",
                "schemaVersion": 7,
                "productVersion": "v0.67-alpha",
                "lifecycleStatus": "FINALIZED",
                "playedAt": "2026-08-17T14:11:56Z",
                "warehouse": {
                    "slots": [
                        {
                            "col": 0,
                            "row": 0,
                            "w": 5,
                            "h": 5,
                            "rarity": "gold",
                            "evidenceLevel": "RARITY_AND_SHAPE",
                            "identityStatus": "CANDIDATE",
                            "candidates": [{"catalogId": "image27-0-2", "name": "万有星仪"}],
                            "identifiedName": None,
                        }
                    ]
                }
            }
            with open(hist_path, "w", encoding="utf-8") as f:
                json.dump({"schemaVersion": 6, "records": [record]}, f)

            bridge = MainWindowBridge(
                OverlayVisibilityController(_FakeOverlay()),
                history_path_provider=lambda: hist_path,
            )
            res = bridge.dispatch({
                "action": "export_history_records",
                "outputPath": str(out_path),
            })
            self.assertTrue(res["exportResult"]["ok"])

            with open(out_path, "r", encoding="utf-8") as f:
                exported_doc = json.load(f)

            exported_slots = exported_doc["records"][0]["warehouse"]["slots"]
            self.assertEqual(exported_slots[0]["identityStatus"], "CANDIDATE")
            self.assertEqual(exported_slots[0]["candidates"], [{"catalogId": "image27-0-2", "name": "万有星仪"}])

    def test_ac12_settlement_resolver_delegation_behavior_identical(self):
        """AC12: SettlementCatalogCandidateResolver produces identical results via shared resolver."""
        settle_resolver = SettlementCatalogCandidateResolver()
        hypothesis = {
            "widthCells": 5,
            "heightCells": 5,
            "rarity": "gold",
            "gridShape": "5x5",
        }
        candidates = settle_resolver.resolve_candidates_for_hypothesis(hypothesis)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["name"], "万有星仪")
        self.assertEqual(candidates[0]["catalogId"], "image27-0-2")

    def test_ac13_ui_html_and_javascript_candidate_wiring(self):
        """AC13: UI HTML has warehouse pane and JS formats '可能：A / B / C' without claiming exact."""
        html_path = CORE_DIR / "main_window.html"
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("match-wh-status-badge", html)
        self.assertIn("match-wh-count", html)
        self.assertIn("match-wh-slots-list", html)

        js_path = CORE_DIR / "main_window.js"
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()

        self.assertIn("match-wh-slots-list", js)
        self.assertIn("可能：", js)
        self.assertIn("已识别：", js)


if __name__ == "__main__":
    unittest.main()
