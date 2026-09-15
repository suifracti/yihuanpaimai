# -*- coding: utf-8 -*-
"""Focused contract tests for Formal Manual Estimate / Advice Reconnection v2."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
CORE = ROOT / "core"
for entry in (str(APP), str(CORE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import main as app_main  # noqa: E402
from auto_archiver import AutoArchiver  # noqa: E402
from live_shadow import reset_live_shadow_state, wait_for_shadow  # noqa: E402
from manual_terminal import ManualTerminalCoordinator  # noqa: E402
from prediction_snapshot_holder import ACTIVE_SNAPSHOT_HOLDER  # noqa: E402


def solve_js(solver_input: dict) -> dict:
    script = (
        "const e=require('./core/auction_engine_v06.js');"
        "process.stdout.write(JSON.stringify(e.solveAuctionPipeline("
        + json.dumps(solver_input, ensure_ascii=False)
        + ")));"
    )
    output = subprocess.check_output(
        ["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8"
    )
    return json.loads(output[output.find("{"):])


class TestManualEstimateAdviceReconnectionV2(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="manual-advice-v2-")
        self.history = Path(self.temp.name) / "history.json"
        self.history.write_text('{"schemaVersion":6,"records":[]}', encoding="utf-8")
        self.old_database = app_main.CANONICAL_DATABASE
        self.old_archiver = app_main.DRAFT_ARCHIVER
        self.old_terminal = app_main.MANUAL_TERMINAL
        app_main.CANONICAL_DATABASE = str(self.history)
        app_main.DRAFT_ARCHIVER = AutoArchiver(db_paths=[str(self.history)])
        app_main.MANUAL_TERMINAL = ManualTerminalCoordinator(str(self.history))
        app_main.cancel_draft_save()
        app_main.CURRENT_MATCH.begin_next_match()
        ACTIVE_SNAPSHOT_HOLDER.clear()
        reset_live_shadow_state()

    def tearDown(self) -> None:
        app_main.cancel_draft_save()
        reset_live_shadow_state()
        ACTIVE_SNAPSHOT_HOLDER.clear()
        app_main.CURRENT_MATCH.begin_next_match()
        app_main.CANONICAL_DATABASE = self.old_database
        app_main.DRAFT_ARCHIVER = self.old_archiver
        app_main.MANUAL_TERMINAL = self.old_terminal
        self.temp.cleanup()

    def _facts(self, **extra) -> dict:
        facts = {
            "venueId": "venue-shanhu",
            "boxId": "box-shanhu-glass",
            "fieldCondition": "standard",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "万有星仪",
            "leaderBid": 100000,
            "targetProfit": 30000,
        }
        facts.update(extra)
        return facts

    def test_native_payload_owns_compatibility_and_empty_history_is_structural(self) -> None:
        payload = app_main.apply_manual_facts({"facts": self._facts()})
        solver_input = payload["solverInput"]
        self.assertEqual(payload["solverCompatibility"]["status"], "COMPATIBILITY_TRANSLATION")
        self.assertEqual(solver_input["venue"], "中级场 · 珊瑚场")
        self.assertEqual(solver_input["box"], "琉璃宝箱 · 宝石类概率提升")
        self.assertEqual(solver_input["matchId"], payload["matchId"])
        self.assertIsNone(solver_input["probabilityProfile"])
        self.assertFalse(payload["shadowUpdating"])
        self.assertEqual(payload["shadowSupport"]["status"], "STRUCTURAL_ONLY")
        self.assertIn("INSUFFICIENT_HISTORY", payload["shadowSupport"]["reasonCodes"])
        result = solve_js(solver_input)
        self.assertEqual(result["degradationLevel"], "structural_only")
        self.assertIsNone(result["rawShadow"])
        self.assertIsNone(result["decision"]["recommendedMax"])

    def test_visible_target_default_and_bid_are_decision_inputs_not_intrinsic_inputs(self) -> None:
        boot = app_main.build_manual_alpha_payload()
        self.assertEqual(boot["targetProfit"], 0)
        self.assertEqual(boot["targetProfitSource"], "NO_MINIMUM_PROFIT")
        self.assertIsNone(boot["leaderBid"])

        base = app_main.apply_manual_facts({"facts": self._facts()})["solverInput"]
        self.assertEqual(base["targetProfit"], 0)  # Old saved goal does not impose a live minimum.
        profile = {
            "coverageRatio": 1,
            "supportedStateCount": 2,
            "totalStateCount": 2,
            "supportedWeight": 1,
            "totalWeight": 1,
            "shadowWhole": {"p20": 400000, "p50": 500000, "p80": 600000},
        }
        low = solve_js({**base, "probabilityProfile": profile, "leaderBid": 100000, "targetProfit": 30000})
        high = solve_js({**base, "probabilityProfile": profile, "leaderBid": 600000, "targetProfit": 80000})
        for key in ("p20", "p50", "p80"):
            self.assertEqual(low["rawShadow"][key], high["rawShadow"][key])
        self.assertEqual(low["decision"]["recommendedMax"], high["decision"]["recommendedMax"])
        self.assertNotEqual(low["decision"]["actionDirective"], high["decision"]["actionDirective"])

    def test_unknown_box_never_defaults_and_cross_venue_pair_fails_closed(self) -> None:
        unknown = app_main.apply_manual_facts({
            "facts": self._facts(boxId=None, boxUnknown=True)
        })
        self.assertIsNone(unknown["boxId"])
        self.assertIsNone(unknown["solverInput"]["box"])
        self.assertEqual(
            unknown["solverCompatibility"]["boxStatus"], "UNKNOWN_NO_BOX_EFFECT"
        )
        with self.assertRaisesRegex(ValueError, "MANUAL_CATALOG_SELECTION_REJECTED"):
            app_main.apply_manual_facts({
                "facts": self._facts(boxId="box-haibei-damaged-package")
            })

    def test_snapshot_wrapper_reaches_holder_and_finalize_preserves_it(self) -> None:
        payload = app_main.apply_manual_facts({"facts": self._facts()})
        result = solve_js(payload["solverInput"])
        snapshot = result["predictionSnapshot"]
        self.assertEqual(snapshot["matchId"], payload["matchId"])
        app_main.apply_manual_facts({"facts": {}, "predictionSnapshot": snapshot})
        self.assertEqual(
            ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match(payload["matchId"])["predictionId"],
            snapshot["predictionId"],
        )
        finalized = app_main.finalize_manual_match({
            "expectedMatchId": payload["matchId"],
            "settlement": {
                "clearingPrice": 100000,
                "actualTotal": 160000,
                "acquired": True,
                "winner": "FixturePlayer",
            },
        })
        self.assertEqual(finalized["terminalResult"]["status"], "FINALIZED")
        records = json.loads(self.history.read_text(encoding="utf-8"))["records"]
        saved = next(row for row in records if row["id"] == payload["matchId"])
        self.assertEqual(saved["predictionSnapshot"]["predictionId"], snapshot["predictionId"])
        self.assertNotEqual(finalized["matchId"], payload["matchId"])
        self.assertIsNone(finalized["leaderBid"])
        self.assertEqual(finalized["solverAvailability"], "UNAVAILABLE")

    def test_supported_profile_uses_explicit_fixture_authority(self) -> None:
        research = ROOT / "异环拍卖数据.json"
        if not research.is_file():
            self.skipTest("explicit research fixture unavailable")
        reset_live_shadow_state()
        app_main.CANONICAL_DATABASE = str(research)
        payload = app_main.apply_manual_facts({"facts": self._facts(
            q=12,
            goldAvg=74379,
            purpleCount=7,
            knownGold="",
        )})
        if payload["shadowUpdating"]:
            wait_for_shadow(timeout=20)
            payload = app_main.build_manual_alpha_payload()
        profile = payload["solverInput"].get("probabilityProfile")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["coverageRatio"], 1)
        self.assertEqual(payload["shadowSupport"]["status"], "HISTORICAL_SUPPORTED")
        result = solve_js(payload["solverInput"])
        self.assertEqual(result["degradationLevel"], "full_shadow")
        self.assertIsNotNone(result["decision"]["recommendedMax"])

    def test_overlay_has_no_second_compatibility_or_shadow_selector(self) -> None:
        html = (CORE / "overlay_alpha.html").read_text(encoding="utf-8")
        self.assertIn('const solverIn = d && d.solverAvailability !== "UNAVAILABLE" ? d.solverInput : null;', html)
        self.assertIn('if (engine && engine.solveAuctionPipeline && solverIn)', html)
        self.assertIn('api.apply_manual_facts(payload)', html)
        self.assertNotIn('adapter.canonicalToV06SolverInput(d.canonical)', html)
        self.assertNotIn('if 海贝', html)
        self.assertNotIn('if 珊瑚', html)
        self.assertNotIn('if 真珠', html)

    def test_browser_sha256_fallback_matches_standard_snapshot_hash(self) -> None:
        script = r"""
        const fs=require('fs'),vm=require('vm'),util=require('util'),crypto=require('crypto');
        const sandbox={TextEncoder:util.TextEncoder};
        sandbox.globalThis=sandbox; sandbox.self=sandbox;
        vm.createContext(sandbox);
        vm.runInContext(fs.readFileSync('./core/auction_engine_v06.js','utf8'),sandbox);
        const value='{"venue":"中级场 · 珊瑚场","box":"琉璃宝箱 · 宝石类概率提升"}';
        const browser=sandbox.AuctionEngineV06.sha256Hex(value);
        const standard=crypto.createHash('sha256').update(value,'utf8').digest('hex');
        process.stdout.write(JSON.stringify({browser,standard}));
        """
        result = json.loads(subprocess.check_output(
            ["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8"
        ))
        self.assertEqual(result["browser"], result["standard"])


if __name__ == "__main__":
    unittest.main()
