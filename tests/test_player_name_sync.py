# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "app"))

from player_identity import get_player_name, set_player_name, normalize_player_name
import runtime_data


class PlayerNameSyncTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._orig_root = os.environ.get("YIHUAN_DATA_ROOT")
        os.environ["YIHUAN_DATA_ROOT"] = self._temp_dir.name

    def tearDown(self):
        if self._orig_root is None:
            os.environ.pop("YIHUAN_DATA_ROOT", None)
        else:
            os.environ["YIHUAN_DATA_ROOT"] = self._orig_root
        self._temp_dir.cleanup()

    def test_save_player_name_persists_and_recovers_on_restart(self):
        self.assertEqual(get_player_name(), "")
        saved = set_player_name("秋星祭02")
        self.assertEqual(saved, "秋星祭02")
        self.assertEqual(get_player_name(), "秋星祭02")

        # Verify physical file
        path = Path(self._temp_dir.name) / "state" / "player-identity.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data.get("displayName"), "秋星祭02")

        # Simulate clearing
        set_player_name("")
        self.assertEqual(get_player_name(), "")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data.get("displayName"), "")

    def test_invalid_player_name_raises_and_preserves_state(self):
        set_player_name("原有效昵称")
        with self.assertRaises(ValueError):
            normalize_player_name("换行\n昵称")
        with self.assertRaises(ValueError):
            normalize_player_name("a" * 65)
        # Original state preserved
        self.assertEqual(get_player_name(), "原有效昵称")

    def test_main_window_bridge_manual_facts_player_name_authoritative_response(self):
        from main_window import MainWindowBridge

        overlay_controller = type("MockOverlay", (), {"visible": False, "toggle": lambda s: False})()
        bridge = MainWindowBridge(
            overlay_controller=overlay_controller,
            manual_facts_provider=lambda facts: set_player_name(facts.get("configuredPlayerName") if isinstance(facts, dict) else ""),
            current_match_provider=lambda: {"matchId": "m1", "configuredPlayerName": get_player_name()},
        )

        # 1. Save player name
        res = bridge.dispatch({"action": "manual_facts", "facts": {"configuredPlayerName": "新玩家Alpha"}})
        self.assertTrue(res.get("manualFactsResult", {}).get("ok"))
        self.assertEqual(res.get("currentMatch", {}).get("configuredPlayerName"), "新玩家Alpha")
        self.assertEqual(get_player_name(), "新玩家Alpha")

        # 2. Clear player name
        res_clear = bridge.dispatch({"action": "manual_facts", "facts": {"configuredPlayerName": ""}})
        self.assertTrue(res_clear.get("manualFactsResult", {}).get("ok"))
        self.assertEqual(res_clear.get("currentMatch", {}).get("configuredPlayerName"), "")
        self.assertEqual(get_player_name(), "")

        # 3. Invalid name cannot fake success
        def failing_provider(facts):
            normalize_player_name(facts.get("configuredPlayerName"))
        bridge._manual_facts_provider = failing_provider
        res_err = bridge.dispatch({"action": "manual_facts", "facts": {"configuredPlayerName": "bad\nname"}})
        self.assertFalse(res_err.get("manualFactsResult", {}).get("ok"))
        self.assertIn("error", res_err.get("manualFactsResult", {}))


if __name__ == "__main__":
    unittest.main()
