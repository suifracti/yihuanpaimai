# -*- coding: utf-8 -*-
"""Issue #15: warehouse identity candidates and limited grids into solveAuctionPipeline.

Contract:
  - CANDIDATE slots with two catalog names become one OR token (A/B), not two confirmed items.
  - UNIQUE / one-name candidates never become knownGold.
  - Human-confirmed / EXACT+DIRECT names stay confirmed.
  - The same goldGrid excludes physically impossible OR members instead of relaxing the search.
  - Settlement items and later records do not rewrite the contemporaneous known expression.
  - Incomplete candidate warehouses do not mint decision.valueP50 or recommendedMax.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))

from v06_adapter import (  # noqa: E402
    canonical_to_v06_solver_input,
    warehouse_slots_known_tokens,
)

NODE = str(ROOT / "runtime" / "node.exe") if (ROOT / "runtime" / "node.exe").is_file() else "node"

CONFIRMED_GOLD = "万有星仪"
CANDIDATE_A = "罐装随心泥"
CANDIDATE_B = "金龙鱼"
OR_TOKEN = "/".join(sorted([CANDIDATE_A, CANDIDATE_B]))
BREAD = "算力面包"


def _canonical(**kwargs):
    record = {
        "schemaVersion": 7,
        "fillDefaults": False,
        "source": "manual",
        "id": "issue-15-warehouse-candidate",
        "playedAt": "2026-08-19T12:00:00Z",
        "environment": {
            "venue": "shanhu",
            "venueName": "中级场 · 珊瑚场",
            "box": "实木宝箱 · 中级藏品概率提升",
            "fieldCondition": "standard",
        },
        "loadout": {"character": "达芙蒂尔", "solverToolGroup": "group1"},
        "costs": {"entry": 5000, "intel": 0, "other": 0, "sunkCost": 5000, "total": 5000},
        "publicIntel": {"q": 18, "totalItems": None, "totalGrid": None, "avgValueBasis": "unknown"},
        "qualities": {
            "white": {"count": None, "avg": None, "grid": None, "knownItems": []},
            "green": {"count": None, "avg": None, "grid": None, "knownItems": []},
            "blue": {"count": None, "avg": None, "grid": None, "knownItems": []},
            "purple": {"count": 9, "avg": None, "grid": None, "knownItems": []},
            "gold": {"count": None, "avg": 71190, "grid": None, "knownItems": []},
            "red": {
                "count": None, "avg": None, "grid": None, "knownItems": [],
                "redInventoryComplete": False, "settlementVerifiedRedItems": "",
            },
        },
        "bidding": {"round": 2, "leaderBid": 100000},
        "settlement": {"status": "pending", "actualTotal": None, "settlementItems": []},
        "warehouse": {"slots": []},
    }
    record.update(kwargs)
    return record


def _slot(col, row, w, h, rarity, **extra):
    slot = {"col": col, "row": row, "w": w, "h": h, "rarity": rarity}
    slot.update(extra)
    return slot


def _run_pipeline(solver_input, records=None):
    payload = {"input": solver_input, "records": records or []}
    script = r"""
const fs=require('fs');
const engine=require('./core/auction_engine_v06.js');
const payload=JSON.parse(fs.readFileSync(0,'utf8'));
const res=engine.solveAuctionPipeline(payload.input, payload.records);
process.stdout.write(JSON.stringify({
  solverStatus: res.solverStatus,
  stateCount: res.stateCount,
  states: (res.states||[]).map(s=>({G:s.G,P:s.P,R:s.R,combo:s.sampleCombo})),
  p50: res.formalValue && res.formalValue.p50,
  valueScope: res.formalValue && res.formalValue.valueScope,
  valueP50: res.decision && res.decision.valueP50,
  recommendedMax: res.decision && res.decision.recommendedMax,
  degradationLevel: res.decision && res.decision.degradationLevel
}));
"""
    out = subprocess.check_output(
        [NODE, "-e", script],
        cwd=ROOT,
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
    )
    return json.loads(out)


def _js_adapter(data):
    script = r"""
const fs=require('fs');
const a=require('./core/v06_adapter.js');
process.stdout.write(JSON.stringify(a.canonicalToV06SolverInput(JSON.parse(fs.readFileSync(0,'utf8')))));
"""
    out = subprocess.check_output(
        [NODE, "-e", script],
        cwd=ROOT,
        input=json.dumps(data, ensure_ascii=False),
        text=True,
        encoding="utf-8",
    )
    return json.loads(out)


class SolverWarehouseCandidateContractV1Tests(unittest.TestCase):
    def test_unique_candidate_is_not_a_confirmed_known_item(self):
        record = _canonical(warehouse={"slots": [
            _slot(
                0, 0, 4, 1, "gold",
                evidenceLevel="UNIQUE_IN_CATALOG",
                identityStatus="CANDIDATE",
                identifiedName=None,
                identityReferenceKind="DERIVED_UNVERIFIED",
                candidates=[{"catalogId": "gold-fish", "name": CANDIDATE_B}],
                bestCandidateName=CANDIDATE_B,
            )
        ]})
        py = canonical_to_v06_solver_input(record)
        js = _js_adapter(record)
        self.assertEqual(py["knownGold"], "")
        self.assertEqual(js["knownGold"], "")
        self.assertEqual(warehouse_slots_known_tokens(record["warehouse"]["slots"])["knownGold"], [])
        solved = _run_pipeline(py)
        self.assertEqual(solved["solverStatus"], "valid")
        self.assertEqual(solved["stateCount"], 6)
        self.assertEqual(solved["p50"], 649862)
        self.assertIsNone(solved["valueP50"])
        self.assertIsNone(solved["recommendedMax"])
        self.assertEqual(solved["degradationLevel"], "structural_only")

    def test_confirmed_plus_or_candidates_constrain_without_unique_promotion(self):
        record = _canonical()
        record["qualities"]["gold"]["knownItems"] = [{"name": CONFIRMED_GOLD, "price": 51077}]
        record["warehouse"]["slots"] = [
            _slot(
                0, 0, 5, 5, "gold",
                evidenceLevel="EXACT_IDENTIFIED",
                identityStatus="EXACT",
                identifiedName=CONFIRMED_GOLD,
                identityReferenceKind="DIRECT",
                candidates=[{"catalogId": "star", "name": CONFIRMED_GOLD}],
            ),
            _slot(
                6, 0, 4, 1, "gold",
                evidenceLevel="CANDIDATE_SET",
                identityStatus="CANDIDATE",
                identifiedName=None,
                candidates=[
                    {"catalogId": "mud", "name": CANDIDATE_A},
                    {"catalogId": "fish", "name": CANDIDATE_B},
                ],
            ),
        ]
        py = canonical_to_v06_solver_input(record)
        js = _js_adapter(record)
        expected = CONFIRMED_GOLD + "+" + OR_TOKEN
        self.assertEqual(py["knownGold"], expected)
        self.assertEqual(js["knownGold"], expected)
        self.assertNotIn(CANDIDATE_A, py["knownGold"].split("+"))
        self.assertNotIn(CANDIDATE_B, py["knownGold"].split("+"))
        self.assertIn("/", py["knownGold"])
        solved = _run_pipeline(py)
        self.assertEqual(solved["solverStatus"], "valid")
        self.assertEqual(solved["stateCount"], 4)
        self.assertEqual(solved["p50"], 699165)
        self.assertEqual([f"{s['G']}/{s['P']}/{s['R']}" for s in solved["states"]], ["6/9/3", "7/9/2", "8/9/1", "9/9/0"])
        self.assertIsNone(solved["valueP50"])
        self.assertIsNone(solved["recommendedMax"])
        unique_promoted = _run_pipeline({**py, "knownGold": CONFIRMED_GOLD + "+" + CANDIDATE_B})
        self.assertNotEqual(unique_promoted["p50"], solved["p50"])

    def test_limited_grid_excludes_impossible_or_member_instead_of_relaxing(self):
        avg = (60040 + 124816) // 2
        record = _canonical()
        record["publicIntel"]["q"] = 2
        record["qualities"]["purple"]["count"] = 0
        record["qualities"]["gold"] = {
            "count": 2, "avg": avg, "grid": 6, "knownItems": [{"name": BREAD, "price": 60040}],
        }
        record["warehouse"]["slots"] = [
            _slot(
                0, 0, 1, 2, "gold",
                evidenceLevel="EXACT_IDENTIFIED",
                identityStatus="EXACT",
                identifiedName=BREAD,
                identityReferenceKind="DIRECT",
                candidates=[{"catalogId": "bread", "name": BREAD}],
            ),
            _slot(
                2, 0, 4, 1, "gold",
                evidenceLevel="CANDIDATE_SET",
                identityStatus="CANDIDATE",
                identifiedName=None,
                candidates=[
                    {"catalogId": "mud", "name": CANDIDATE_A},
                    {"catalogId": "fish", "name": CANDIDATE_B},
                ],
            ),
        ]
        py = canonical_to_v06_solver_input(record)
        self.assertEqual(py["knownGold"], BREAD + "+" + OR_TOKEN)
        self.assertEqual(py["goldGrid"], 6)
        unconstrained = _run_pipeline({**py, "goldGrid": None, "publicInfo": {**py["publicInfo"], "goldGrid": None}})
        self.assertEqual(unconstrained["solverStatus"], "valid")
        self.assertEqual(unconstrained["states"][0]["combo"], [60040, 124816])
        limited = _run_pipeline(py)
        self.assertEqual(limited["solverStatus"], "no-match")
        self.assertEqual(limited["stateCount"], 0)
        self.assertIsNone(limited["p50"])
        self.assertIsNone(limited.get("recommendedMax"))
        self.assertIsNone(limited.get("valueP50"))
        fitting = _run_pipeline({**py, "goldGrid": 14, "publicInfo": {**py["publicInfo"], "goldGrid": 14}})
        self.assertEqual(fitting["solverStatus"], "valid")
        self.assertEqual(fitting["states"][0]["combo"], [60040, 124816])

    def test_settlement_and_future_records_do_not_rewrite_then_known_expression(self):
        record = _canonical()
        record["qualities"]["gold"]["knownItems"] = [{"name": CONFIRMED_GOLD, "price": 51077}]
        record["warehouse"]["slots"] = [
            _slot(
                0, 0, 4, 3, "gold",
                evidenceLevel="CANDIDATE_SET",
                identityStatus="CANDIDATE",
                identifiedName=None,
                candidates=[
                    {"catalogId": "mud", "name": CANDIDATE_A},
                    {"catalogId": "fish", "name": CANDIDATE_B},
                ],
            )
        ]
        record["settlement"] = {
            "status": "verified",
            "actualTotal": 9999999,
            "settlementItems": [{"name": CANDIDATE_B, "status": "exact", "price": 111111}],
        }
        py = canonical_to_v06_solver_input(record)
        self.assertEqual(py["knownGold"], CONFIRMED_GOLD + "+" + OR_TOKEN)
        self.assertNotEqual(py["knownGold"], CONFIRMED_GOLD + "+" + CANDIDATE_B)
        future = [{
            "id": "future-settlement",
            "playedAt": "2099-01-01T00:00:00Z",
            "lifecycleStatus": "FINALIZED",
            "publicIntel": {"q": 18},
            "settlement": {"actualTotal": 9999999},
        }]
        now = _run_pipeline(py, records=[])
        leaked = _run_pipeline(py, records=future)
        self.assertEqual(now["stateCount"], leaked["stateCount"])
        self.assertEqual(now["p50"], leaked["p50"])
        self.assertEqual(now["states"], leaked["states"])
        self.assertIsNone(now["valueP50"])
        self.assertIsNone(now["recommendedMax"])

    def test_python_and_js_adapters_agree_on_warehouse_tokens(self):
        record = _canonical()
        record["qualities"]["gold"]["knownItems"] = [{"name": CONFIRMED_GOLD}]
        record["warehouse"]["slots"] = [
            _slot(
                1, 2, 4, 1, "gold",
                identityStatus="CANDIDATE",
                evidenceLevel="CANDIDATE_SET",
                candidates=[{"name": CANDIDATE_B}, {"name": CANDIDATE_A}],
            ),
            _slot(
                0, 0, 1, 1, "gold",
                identityStatus="CANDIDATE",
                evidenceLevel="UNIQUE_IN_CATALOG",
                candidates=[{"name": "浅绯祈手办"}],
            ),
        ]
        py = canonical_to_v06_solver_input(record)
        js = _js_adapter(record)
        self.assertEqual(py["knownGold"], js["knownGold"])
        self.assertEqual(py["knownGold"], CONFIRMED_GOLD + "+" + OR_TOKEN)


if __name__ == "__main__":
    unittest.main()
