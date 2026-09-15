# -*- coding: utf-8 -*-
"""Phase 16: HistoryRecordProjection purpleAvg targeted tests.

Verifies AC1-AC7:
- Canonical qualities.purple.avg -> observedFacts.purpleAvg
- None / missing fail-closed behavior
- Existing fields (q, goldAvg, purpleCount, winner, warehouse) projection regression
- JS contract in core/main_window.js
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from main_view_state import MainViewStateProvider


class HistoryRecordPurpleAvgProjectionTests(unittest.TestCase):
    def _dummy_decision(self):
        class DummyDecision:
            normalized_time = None
            lifecycle = "FINALIZED"
            admitted = True
            exclusion_reason = None
        return DummyDecision()

    def test_ac1_canonical_purple_avg_projected_to_observed_facts(self):
        """AC1: Canonical record['qualities']['purple']['avg'] = 4357 -> observedFacts.purpleAvg == 4357."""
        record = {
            "id": "match_purple_avg_001",
            "playedAt": "2026-08-17T14:11:56Z",
            "qualities": {
                "purple": {
                    "avg": 4357,
                    "count": 3,
                },
                "gold": {
                    "avg": 47286,
                },
            },
            "publicIntel": {
                "q": 11,
            },
        }
        proj = MainViewStateProvider._project_record(record, self._dummy_decision())
        self.assertEqual(proj.purple_avg, 4357)

        payload = proj.to_payload()
        self.assertIn("observedFacts", payload)
        self.assertEqual(payload["observedFacts"]["purpleAvg"], 4357)
        self.assertEqual(payload["observedFacts"]["q"], 11)
        self.assertEqual(payload["observedFacts"]["goldAvg"], 47286)
        self.assertEqual(payload["observedFacts"]["purpleCount"], 3)

    def test_ac2_js_render_history_detail_reads_purple_avg(self):
        """AC2: core/main_window.js renderHistoryDetail contains purpleAvg presentation contract."""
        js_path = PROJECT_ROOT / "core" / "main_window.js"
        self.assertTrue(js_path.exists())
        js = js_path.read_text(encoding="utf-8")
        self.assertIn('setText("detail-purple-avg", facts.purpleAvg != null ? formatCurrency(facts.purpleAvg) : "未记录");', js)

    def test_ac3_missing_purple_avg_fail_closed(self):
        """AC3: Missing or None qualities.purple.avg -> observedFacts.purpleAvg remains None (no default 0)."""
        record_empty = {
            "id": "match_purple_avg_empty",
            "playedAt": "2026-08-17T14:11:56Z",
        }
        proj_empty = MainViewStateProvider._project_record(record_empty, self._dummy_decision())
        self.assertIsNone(proj_empty.purple_avg)
        self.assertIsNone(proj_empty.to_payload()["observedFacts"]["purpleAvg"])

        record_none = {
            "id": "match_purple_avg_none",
            "playedAt": "2026-08-17T14:11:56Z",
            "qualities": {
                "purple": {
                    "avg": None,
                },
            },
        }
        proj_none = MainViewStateProvider._project_record(record_none, self._dummy_decision())
        self.assertIsNone(proj_none.purple_avg)
        self.assertIsNone(proj_none.to_payload()["observedFacts"]["purpleAvg"])

    def test_ac4_existing_fields_and_warehouse_projection_intact(self):
        """AC4: q, goldAvg, purpleCount, winner, warehouse summary projection intact alongside purpleAvg."""
        record = {
            "id": "match_all_fields_001",
            "playedAt": "2026-08-17T14:11:56Z",
            "publicIntel": {"q": 12},
            "qualities": {
                "gold": {"avg": 74379},
                "purple": {"avg": 5200, "count": 4},
            },
            "settlement": {
                "winner": "汐",
                "isSettled": True,
                "clearingPrice": 88000,
                "actualTotal": 120000,
            },
            "warehouse": {
                "slots": [
                    {"col": 0, "row": 0, "w": 1, "h": 1, "rarity": "gold", "evidenceLevel": "PIXEL_TEMPLATE_MATCH", "identifiedName": "万有星仪"},
                    {"col": 1, "row": 0, "w": 1, "h": 1, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
                ]
            },
        }
        proj = MainViewStateProvider._project_record(record, self._dummy_decision())
        payload = proj.to_payload()

        self.assertEqual(payload["observedFacts"]["purpleAvg"], 5200)
        self.assertEqual(payload["observedFacts"]["goldAvg"], 74379)
        self.assertEqual(payload["observedFacts"]["purpleCount"], 4)
        self.assertEqual(payload["observedFacts"]["q"], 12)
        self.assertEqual(payload["settlement"]["winner"], "汐")
        self.assertEqual(payload["warehouse"]["itemCount"], 2)
        self.assertEqual(payload["warehouse"]["unknownCount"], 1)


if __name__ == "__main__":
    unittest.main()
