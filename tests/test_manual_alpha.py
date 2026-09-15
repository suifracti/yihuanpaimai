# -*- coding: utf-8 -*-
"""0.67 Alpha first-cut: Manual → Canonical → Solver / DRAFT / next match."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from auto_archiver import AutoArchiver
from current_match import CurrentMatch
from live_shadow import history_generation, ingest_archived_record, reset_live_shadow_state
from v06_adapter import canonical_to_v06_solver_input


GLASS_BOX = "琉璃宝箱 · 宝石类概率提升"
KNOWN_GOLD = "4546/48648+185165"
KNOWN_RED = "454654*2"


def _manual_canonical(match: CurrentMatch) -> dict:
    return match.to_canonical()


class TestManualAlphaVerticalSlice(unittest.TestCase):
    def test_a_manual_canonical_solver_keeps_known_expr(self):
        match = CurrentMatch()
        match.apply_facts({
            "box": GLASS_BOX,
            "fieldCondition": "standard",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": KNOWN_GOLD,
            "knownRed": KNOWN_RED,
            "knownPurple": "拈花小像+金角月芒",
        })
        canonical = _manual_canonical(match)
        self.assertEqual(canonical["environment"]["box"], GLASS_BOX)
        self.assertEqual(canonical["environment"]["fieldCondition"], "standard")
        self.assertEqual(canonical["publicIntel"]["q"], 9)
        self.assertEqual(canonical["qualities"]["gold"]["avg"], 33538)
        self.assertEqual(canonical["qualities"]["purple"]["count"], 5)
        self.assertEqual(
            canonical["qualities"]["gold"]["knownItems"],
            [{"name": "4546/48648"}, {"name": "185165"}],
        )
        self.assertEqual(
            canonical["qualities"]["red"]["knownItems"],
            [{"name": "454654*2"}],
        )
        self.assertEqual(
            canonical["qualities"]["purple"]["knownItems"],
            [{"name": "拈花小像"}, {"name": "金角月芒"}],
        )
        self.assertIsNone(canonical["loadout"]["character"])
        self.assertIsNone(canonical["loadout"]["solverToolGroup"])
        self.assertIsNone(canonical["environment"]["venue"])

        solver_in = canonical_to_v06_solver_input(canonical)
        self.assertEqual(solver_in["q"], 9)
        self.assertEqual(solver_in["goldAvg"], 33538)
        self.assertEqual(solver_in["avg"], 33538)
        self.assertEqual(solver_in["purpleCount"], 5)
        self.assertEqual(solver_in["knownGold"], KNOWN_GOLD)
        self.assertEqual(solver_in["knownRed"], KNOWN_RED)
        self.assertEqual(solver_in["box"], GLASS_BOX)
        self.assertEqual(solver_in["fieldCondition"], "standard")
        self.assertIsNone(solver_in["venue"])
        self.assertIsNone(solver_in["character"])
        self.assertIsNone(solver_in["toolGroup"])

        classic = CurrentMatch()
        classic.apply_facts({
            "box": "实木宝箱 · 中级藏品概率提升",
            "fieldCondition": "standard",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "万有星仪",
            "knownPurple": "拈花小像+金角月芒",
        })
        classic_in = canonical_to_v06_solver_input(classic.to_canonical())
        script = (
            "const engine=require('./core/auction_engine_v06.js');"
            "const res=engine.solveAuctionPipeline(" + json.dumps(classic_in, ensure_ascii=False) + ");"
            "const states=(res.states||[]).map(s=>`${s.G}/${s.P}/${s.R}`);"
            "console.log(JSON.stringify({status:res.solverStatus,states,knownGold:res.knownGold||null,inputKnown:"
            + json.dumps(classic_in["knownGold"], ensure_ascii=False) + "}));"
        )
        out = subprocess.check_output(["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8")
        data = json.loads(out)
        self.assertEqual(data["status"], "valid")
        self.assertIn("3/5/1", data["states"])
        self.assertIn("4/5/0", data["states"])

        expr_script = (
            "const adapter=require('./core/v06_adapter.js');"
            "const engine=require('./core/auction_engine_v06.js');"
            "const canonical=" + json.dumps(canonical, ensure_ascii=False) + ";"
            "const solverIn=adapter.canonicalToV06SolverInput(canonical);"
            "let status='ok';"
            "try { engine.parseFlexibleKnown(solverIn.knownGold, engine.GOLD_ITEMS, '金色'); } catch(e) { status='parse'; }"
            "console.log(JSON.stringify({knownGold:solverIn.knownGold,knownRed:solverIn.knownRed,q:solverIn.q,goldAvg:solverIn.goldAvg,status}));"
        )
        expr = json.loads(subprocess.check_output(["node", "-e", expr_script], cwd=PROJECT_ROOT, encoding="utf-8"))
        self.assertEqual(expr["knownGold"], KNOWN_GOLD)
        self.assertEqual(expr["knownRed"], KNOWN_RED)
        self.assertEqual(expr["q"], 9)
        self.assertEqual(expr["goldAvg"], 33538)

    def test_b_draft_does_not_ingest_shadow(self):
        reset_live_shadow_state()
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "drafts.json")
            archiver = AutoArchiver(db_paths=[db])
            match = CurrentMatch()
            match.apply_facts({
                "box": GLASS_BOX,
                "fieldCondition": "standard",
                "q": 11,
                "goldAvg": 47286,
                "purpleCount": 3,
                "knownGold": KNOWN_GOLD,
                "knownRed": KNOWN_RED,
            })
            before = history_generation()
            with mock.patch("live_shadow.ingest_archived_record", wraps=ingest_archived_record) as ingest:
                saved = archiver.save_draft(match.to_canonical())
            self.assertIsNotNone(saved)
            self.assertEqual(saved["lifecycleStatus"], "DRAFT")
            self.assertEqual(saved["knownGold"], KNOWN_GOLD)
            self.assertEqual(saved["knownRed"], KNOWN_RED)
            ingest.assert_not_called()
            self.assertEqual(history_generation(), before)
            with open(db, "r", encoding="utf-8") as fh:
                disk = json.load(fh)
            rows = disk.get("records") or []
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["lifecycleStatus"], "DRAFT")
            self.assertEqual(rows[0]["q"], 11)
            self.assertEqual(rows[0]["qualities"]["gold"]["avg"], 47286)
            settlement_view = CurrentMatch()
            settlement_view.apply_facts({
                "box": rows[0]["environment"]["box"],
                "fieldCondition": rows[0]["environment"]["fieldCondition"],
                "q": rows[0]["publicIntel"]["q"],
                "goldAvg": rows[0]["qualities"]["gold"]["avg"],
                "purpleCount": rows[0]["qualities"]["purple"]["count"],
                "knownGold": rows[0]["knownGold"],
                "knownRed": rows[0]["knownRed"],
            })
            inherited = settlement_view.snapshot()
            self.assertEqual(inherited["box"], GLASS_BOX)
            self.assertEqual(inherited["fieldCondition"], "standard")
            self.assertEqual(inherited["purpleCount"], 3)
            self.assertEqual(inherited["knownGold"], KNOWN_GOLD)
            self.assertEqual(inherited["lifecycleStatus"], "DRAFT")

    def test_c_partial_facts_and_next_match_reset(self):
        match = CurrentMatch()
        match.apply_facts({"q": 9})
        canonical = match.to_canonical()
        solver_in = canonical_to_v06_solver_input(canonical)
        self.assertEqual(solver_in["q"], 9)
        self.assertIsNone(solver_in["goldAvg"])
        self.assertIsNone(solver_in["box"])
        self.assertIsNone(solver_in["fieldCondition"])
        self.assertIsNone(solver_in["venue"])
        self.assertIsNone(solver_in["character"])
        self.assertIsNone(solver_in["toolGroup"])
        script = (
            "const engine=require('./core/auction_engine_v06.js');"
            "const res=engine.solveAuctionPipeline(" + json.dumps(solver_in, ensure_ascii=False) + ");"
            "console.log(JSON.stringify({status:res.solverStatus,p50:(res.formalValue||{}).p50,p20:(res.formalValue||{}).p20,p80:(res.formalValue||{}).p80}));"
        )
        partial = json.loads(subprocess.check_output(["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8"))
        self.assertEqual(partial["status"], "fallback")
        self.assertIsNone(partial["p50"])
        self.assertIsNone(partial["p20"])
        self.assertIsNone(partial["p80"])

        match.apply_facts({"goldAvg": 33538, "box": GLASS_BOX, "fieldCondition": "standard"})
        ready = canonical_to_v06_solver_input(match.to_canonical())
        ready_script = (
            "const engine=require('./core/auction_engine_v06.js');"
            "const res=engine.solveAuctionPipeline(" + json.dumps(ready, ensure_ascii=False) + ");"
            "console.log(JSON.stringify({status:res.solverStatus,q:res.q||null}));"
        )
        ready_out = json.loads(subprocess.check_output(["node", "-e", ready_script], cwd=PROJECT_ROOT, encoding="utf-8"))
        self.assertIn(ready_out["status"], ("valid", "no-match", "fallback", "incomplete"))
        first_id = match.id
        nxt = match.begin_next_match()
        self.assertNotEqual(nxt["id"], first_id)
        self.assertIsNone(nxt["box"])
        self.assertIsNone(nxt["fieldCondition"])
        self.assertIsNone(nxt["q"])
        self.assertIsNone(nxt["goldAvg"])
        self.assertEqual(nxt["knownGold"], "")
        self.assertEqual(nxt["lifecycleStatus"], "DRAFT")


if __name__ == "__main__":
    unittest.main()
