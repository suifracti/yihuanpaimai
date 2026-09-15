"""Targeted regression tests for 4D2D1A: Authoritative Bindings Wiring Only.

Tests that production warehouse capture host reads the authoritative live state,
enables eligibility only during stable settlement at TOP, and remains fail-closed
in all other scenes.
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

from warehouse_capture_arming import (
    CONFIRM_CAPTION,
    REASON_NOT_SETTLEMENT,
    REASON_PREPARED,
    REASON_START_REQUIRES_TOP,
)
from warehouse_capture_host import (
    STATE_DRIVER_NOT_CONFIGURED,
    STATE_IDLE,
    WarehouseCaptureHost,
    build_production_warehouse_capture_host,
)


class TestAuthoritativeBindingsWiring4D2D1A(unittest.TestCase):
    def test_production_host_wires_authoritative_bindings_probe(self):
        import main

        host = main.WAREHOUSE_CAPTURE_HOST
        self.assertIsNotNone(host)
        self.assertTrue(host.factory_ready)

        # 1. Default / initial empty state -> Fail-closed (not settlement)
        main.LATEST_PAYLOAD.clear()
        self.assertFalse(host.available)
        self.assertEqual(host.presentation().state, STATE_DRIVER_NOT_CONFIGURED)
        self.assertEqual(host.prepare()["reason"], REASON_NOT_SETTLEMENT)

        # 2. AUCTION_LOBBY scene -> Fail-closed
        main.LATEST_PAYLOAD.update({
            "scene": "AUCTION_LOBBY",
            "inLobby": True,
            "inAuction": False,
            "isSettlement": False,
        })
        self.assertFalse(host.available)
        self.assertEqual(host.presentation().state, STATE_DRIVER_NOT_CONFIGURED)
        self.assertEqual(host.prepare()["reason"], REASON_NOT_SETTLEMENT)

        # 3. IN_AUCTION scene -> Fail-closed
        main.LATEST_PAYLOAD.update({
            "scene": "IN_AUCTION",
            "inAuction": True,
            "isSettlement": False,
        })
        self.assertFalse(host.available)
        self.assertEqual(host.prepare()["reason"], REASON_NOT_SETTLEMENT)

        # 4. SETTLEMENT scene with stable=True and scrollState=TOP -> Available & Eligible
        main.LATEST_PAYLOAD.update({
            "scene": "SETTLEMENT",
            "isSettlement": True,
            "hadSettlement": True,
            "settlementReady": True,
            "settlementData": {"stable": True, "recordStableKey": "rec_live_4d2d"},
            "recordStableKey": "rec_live_4d2d",
            "scrollState": "TOP",
            "warehouseRoi": (100, 100, 800, 600),
            "gameHwnd": 12345,
        })
        self.assertTrue(host.available)
        self.assertEqual(host.presentation().state, STATE_IDLE)
        self.assertEqual(host.presentation().message, "采集完整仓库")

        # 5. Prepare returns valid arming token
        prepared = host.prepare()
        self.assertTrue(prepared["ok"])
        self.assertEqual(prepared["reason"], REASON_PREPARED)
        self.assertEqual(prepared["confirmCaption"], CONFIRM_CAPTION)
        token = prepared["armingToken"]
        self.assertIsNotNone(token)

        # 6. SETTLEMENT scene with scrollState=MIDDLE -> Requires TOP
        main.LATEST_PAYLOAD["scrollState"] = "MIDDLE"
        prepared_mid = host.prepare()
        self.assertFalse(prepared_mid["ok"])
        self.assertEqual(prepared_mid["reason"], REASON_START_REQUIRES_TOP)

        # Cleanup
        main.LATEST_PAYLOAD.clear()


if __name__ == "__main__":
    unittest.main()
