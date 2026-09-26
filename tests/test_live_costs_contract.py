# -*- coding: utf-8 -*-
"""Live costs: 0 is a real free ticket; unknown must not become 5000."""
import json
import os
import subprocess
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from business_sot import venue_entry_cost
from main import (build_in_auction_hud_payload, build_nav_hud_payload,
                  _native_unverified_cost_summary, _native_unverified_accounting)


def run_js(script: str):
    prelude = "const engine = require('./core/auction_engine_v06.js');\n" + script
    proc = subprocess.run(
        ["node", "-e", prelude],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr + "\n" + proc.stdout)
    return json.loads(proc.stdout)


class TestLiveCostsContract(unittest.TestCase):
    def test_native_catalog_fee_and_default_zero_are_not_payment_receipts(self):
        facts = {"entryCost": 5000, "intelCost": 0, "otherCost": 0}
        self.assertIn("已配置入场费 5,000", _native_unverified_cost_summary(facts))
        self.assertIn("已付合计未知", _native_unverified_cost_summary(facts))
        accounting = _native_unverified_accounting(facts)
        self.assertIsNone(accounting["paidCosts"])
        self.assertIsNone(accounting["sessionNet"])
        self.assertFalse(accounting["complete"])
        self.assertIn("入场费 未观察", _native_unverified_cost_summary({"entryCost": None}))

    def test_sot_entry_costs(self):
        self.assertEqual(venue_entry_cost("初级场 · 海贝场"), 0)
        self.assertEqual(venue_entry_cost("海贝场"), 0)
        self.assertEqual(venue_entry_cost("中级场 · 珊瑚场"), 5000)
        self.assertEqual(venue_entry_cost("珊瑚场"), 5000)
        self.assertEqual(venue_entry_cost("高级场 · 真珠场"), 20000)
        self.assertIsNone(venue_entry_cost("未知场地"))
        self.assertIsNone(venue_entry_cost(None))

    def test_junior_venue_keeps_zero_through_payload_and_engine(self):
        ctx = {
            "scene": "IN_AUCTION",
            "round": 1,
            "venue": "初级场 · 海贝场",
            "lobbyVenue": "初级场 · 海贝场",
            "lobbyEntryCost": 0,
            "q": 7,
            "goldAvg": 12000,
        }
        payload = build_in_auction_hud_payload(ctx)
        self.assertEqual(payload["costs"]["entry"], 0)
        self.assertEqual(payload["costs"]["complete"], True)
        costs = run_js(
            "console.log(JSON.stringify(engine.resolveSessionCosts("
            + json.dumps({"costs": payload["costs"]}, ensure_ascii=False)
            + ")));"
        )
        self.assertEqual(costs["entry"], 0)
        self.assertEqual(costs["allCosts"], 0)
        venue_only = build_in_auction_hud_payload({
            "scene": "IN_AUCTION",
            "round": 1,
            "venue": "初级场 · 海贝场",
        })
        self.assertEqual(venue_only["costs"]["entry"], 0)

    def test_coral_entry_comes_from_fact_not_fallback(self):
        ctx = {
            "scene": "IN_AUCTION",
            "round": 3,
            "venue": "中级场 · 珊瑚场",
            "lobbyVenue": "中级场 · 珊瑚场",
            "lobbyEntryCost": 5000,
            "q": 12,
            "goldAvg": 74379,
        }
        payload = build_in_auction_hud_payload(ctx)
        self.assertEqual(payload["costs"]["entry"], 5000)
        costs = run_js(
            "console.log(JSON.stringify(engine.resolveSessionCosts("
            + json.dumps({"costs": payload["costs"]}, ensure_ascii=False)
            + ")));"
        )
        self.assertEqual(costs["entry"], 5000)
        self.assertEqual(costs["allCosts"], 5000)

    def test_nav_payload_keeps_free_and_unknown(self):
        junior = build_nav_hud_payload({
            "scene": "AUCTION_LOBBY",
            "inLobby": True,
            "lobbyVenue": "初级场 · 海贝场",
            "lobbyEntryCost": 0,
        })
        self.assertEqual(junior["costs"]["entry"], 0)
        self.assertEqual(junior["lobbyEntryCost"], 0)
        unknown = build_nav_hud_payload({"scene": "AUCTION_LOBBY", "inLobby": True})
        self.assertIsNone(unknown["costs"]["entry"])

    def test_unknown_entry_is_not_forged(self):
        ctx = {"scene": "IN_AUCTION", "round": 1, "venue": "未知场地"}
        payload = build_in_auction_hud_payload(ctx)
        self.assertIsNone(payload["costs"]["entry"])
        self.assertFalse(payload["costs"]["complete"])
        costs = run_js(
            "console.log(JSON.stringify(engine.resolveSessionCosts("
            + json.dumps({"costs": payload["costs"]}, ensure_ascii=False)
            + ")));"
        )
        self.assertIsNone(costs["entry"])
        self.assertIsNone(costs["allCosts"])
        self.assertFalse(costs["complete"])

    def test_shadow_modes_unaffected(self):
        res = run_js(
            """
            const live = {q:12, goldAvg:74379, purple:7, costs:{entry:0,intel:0,other:0,sunkCost:0,futureIncrementalCost:0,total:0}};
            const structural = engine.solveAuctionPipeline(live);
            const full = engine.solveAuctionPipeline({
              ...live,
              coverageRatio: 1,
              probabilityProfile: {
                coverageRatio: 1, supportedStateCount: 2, totalStateCount: 2,
                supportedWeight: 1, totalWeight: 1,
                shadowWhole: {p20:300000,p50:400000,p80:500000}
              }
            });
            console.log(JSON.stringify({
              structural: structural.degradationLevel,
              structuralP50: structural.decision.valueP50,
              full: full.degradationLevel,
              fullP50: full.decision.valueP50,
              fullSafe: full.decision.safeBuy,
              fullAllCost: full.decision.costInfo.allCosts
            }));
            """
        )
        self.assertEqual(res["structural"], "structural_only")
        self.assertIsNone(res["structuralP50"])
        self.assertEqual(res["full"], "full_shadow")
        self.assertEqual(res["fullP50"], 400000)
        self.assertEqual(res["fullAllCost"], 0)
        self.assertEqual(res["fullSafe"], 370000)  # Default profit 30000; no implicit ROI target.


if __name__ == "__main__":
    unittest.main()
