# -*- coding: utf-8 -*-
"""App-level Manual terminal/reset/failure integration tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="nte-manual-terminal-import-")
os.environ.setdefault("YIHUAN_DATA_ROOT", _IMPORT_DATA.name)
for path in (APP_DIR, CORE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import main as app_main
from auto_archiver import AutoArchiver
from manual_terminal import ManualTerminalCoordinator


class TestManualTerminalAppFlow(unittest.TestCase):
    def setUp(self):
        app_main.cancel_draft_save()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "history.json"
        self.old_archiver = app_main.DRAFT_ARCHIVER
        self.old_terminal = app_main.MANUAL_TERMINAL
        app_main.DRAFT_ARCHIVER = AutoArchiver(db_paths=[str(self.path)])
        app_main.MANUAL_TERMINAL = ManualTerminalCoordinator(self.path)
        app_main.ACTIVE_SNAPSHOT_HOLDER.clear()
        app_main.ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()
        app_main.CURRENT_MATCH.begin_next_match()
        app_main.apply_manual_facts({
            "venueId": "venue-shanhu",
            "boxId": "box-shanhu-glass",
            "fieldCondition": "standard",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "万有星仪",
        })
        self.match_id = app_main.CURRENT_MATCH.id

    def tearDown(self):
        app_main.cancel_draft_save()
        app_main.ACTIVE_SNAPSHOT_HOLDER.clear()
        app_main.ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()
        app_main.CURRENT_MATCH.begin_next_match()
        app_main.DRAFT_ARCHIVER = self.old_archiver
        app_main.MANUAL_TERMINAL = self.old_terminal
        self.temp.cleanup()

    @property
    def settlement(self):
        return {
            "clearingPrice": 100000,
            "actualTotal": 160000,
            "acquired": True,
            "winner": "FixturePlayer",
        }

    def _rows(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["records"]

    def test_finalize_then_new_match_resets_only_after_verified_write(self):
        payload = app_main.finalize_manual_match({
            "expectedMatchId": self.match_id,
            "settlement": self.settlement,
        })
        self.assertTrue(payload["terminalResult"]["ok"])
        self.assertEqual(payload["terminalResult"]["status"], "FINALIZED")
        self.assertNotEqual(payload["matchId"], self.match_id)
        self.assertEqual(payload["lifecycleStatus"], "DRAFT")
        self.assertIsNone(payload["venueId"])
        self.assertIsNone(payload["boxId"])
        self.assertIsNone(payload["q"])
        self.assertEqual(payload["knownGold"], "")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.match_id)
        self.assertEqual(rows[0]["lifecycleStatus"], "FINALIZED")

        new_id = payload["matchId"]
        retry = app_main.finalize_manual_match({
            "expectedMatchId": self.match_id,
            "settlement": self.settlement,
        })
        self.assertEqual(retry["terminalResult"]["status"], "ALREADY_FINALIZED")
        self.assertEqual(retry["matchId"], new_id)
        self.assertEqual(len(self._rows()), 1)

    def test_failure_keeps_match_and_settlement_can_retry(self):
        failed = app_main.finalize_manual_match({
            "expectedMatchId": self.match_id,
            "settlement": {"clearingPrice": 100000},
        })
        self.assertFalse(failed["terminalResult"]["ok"])
        self.assertEqual(failed["matchId"], self.match_id)
        self.assertEqual(app_main.CURRENT_MATCH.id, self.match_id)
        self.assertEqual(app_main.CURRENT_MATCH.facts["q"], 9)
        self.assertEqual(self._rows()[0]["lifecycleStatus"], "DRAFT")

        retry = app_main.finalize_manual_match({
            "expectedMatchId": self.match_id,
            "settlement": self.settlement,
        })
        self.assertEqual(retry["terminalResult"]["status"], "FINALIZED")

    def test_terminal_request_rejects_invalid_displayed_snapshot(self):
        payload = app_main.finalize_manual_match({
            "expectedMatchId": self.match_id,
            "settlement": self.settlement,
            "predictionSnapshot": {"matchId": "another-match"},
        })
        self.assertFalse(payload["terminalResult"]["ok"])
        self.assertEqual(app_main.CURRENT_MATCH.id, self.match_id)
        self.assertEqual(self._rows()[0]["lifecycleStatus"], "DRAFT")

    def test_unspecified_next_match_intent_cannot_clear(self):
        payload = app_main.begin_next_manual_match({"expectedMatchId": self.match_id})
        self.assertEqual(payload["terminalResult"]["status"], "TERMINAL_INTENT_REQUIRED")
        self.assertEqual(app_main.CURRENT_MATCH.id, self.match_id)
        self.assertEqual(app_main.CURRENT_MATCH.facts["q"], 9)

    def test_keep_draft_and_discard_use_distinct_lifecycle(self):
        kept = app_main.begin_next_manual_match({
            "expectedMatchId": self.match_id,
            "disposition": "keep_draft",
        })
        self.assertEqual(kept["terminalResult"]["status"], "DRAFT_KEPT")
        self.assertNotEqual(kept["matchId"], self.match_id)
        self.assertEqual(self._rows()[0]["lifecycleStatus"], "DRAFT")

        next_id = kept["matchId"]
        app_main.apply_manual_facts({
            "venueId": "venue-haibei", "boxId": None, "boxUnknown": True,
            "fieldCondition": "standard", "q": 3,
        })
        discarded = app_main.begin_next_manual_match({
            "expectedMatchId": next_id,
            "disposition": "discard",
        })
        by_id = {row["id"]: row for row in self._rows()}
        self.assertEqual(discarded["terminalResult"]["status"], "DRAFT_DISCARDED")
        self.assertEqual(by_id[next_id]["lifecycleStatus"], "CANCELLED")

    def test_concurrent_finalize_is_exactly_once(self):
        results = []

        def worker():
            results.append(app_main.finalize_manual_match({
                "expectedMatchId": self.match_id,
                "settlement": self.settlement,
            })["terminalResult"]["status"])

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count("FINALIZED"), 1)
        self.assertEqual(results.count("ALREADY_FINALIZED"), 5)
        self.assertEqual(len(self._rows()), 1)

    def test_overlay_requires_explicit_terminal_intent(self):
        html = (CORE_DIR / "overlay_alpha.html").read_text(encoding="utf-8")
        self.assertIn('id="terminalFinish"', html)
        self.assertIn('id="terminalKeep"', html)
        self.assertIn('id="terminalDiscard"', html)
        self.assertIn('id="terminalClose"', html)
        self.assertIn('action: "manual_finalize"', html)
        self.assertIn('requestNextDisposition("keep_draft")', html)
        self.assertIn('requestNextDisposition("discard")', html)
        self.assertIn('document.getElementById("nextBtn").onclick = openTerminal', html)
        self.assertNotIn(
            'sendHost({ action: "manual_next_match", type: "manual_next_match" });',
            html,
        )


if __name__ == "__main__":
    unittest.main()
