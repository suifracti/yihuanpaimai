"""Separate-process writes must become visible without restarting the GUI."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import live_shadow


class HistoryExternalRefreshTests(unittest.TestCase):
    def setUp(self):
        live_shadow.reset_live_shadow_state()

    def tearDown(self):
        live_shadow.reset_live_shadow_state()

    def test_external_atomic_replacement_refreshes_same_size_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text('{"records":[{"id":"first"}]}', encoding="utf-8")
            live_shadow.load_history_snapshot(str(path))
            generation = live_shadow.history_generation()
            old_revision = live_shadow.get_live_dataset_revision()
            live_shadow._PROFILE_CACHE["old"] = {"value": 1}
            script = "from pathlib import Path; import os,sys; p=Path(sys.argv[1]); t=p.with_suffix('.tmp'); t.write_text('{\"records\":[{\"id\":\"other\"}]}',encoding='utf-8'); os.replace(t,p)"
            subprocess.run([sys.executable, "-c", script, str(path)], check=True,
                           capture_output=True, env=dict(os.environ))
            records = live_shadow.load_history_snapshot(str(path))
            self.assertEqual(records, [{"id": "other"}])
            self.assertGreater(live_shadow.history_generation(), generation)
            self.assertNotEqual(live_shadow.get_live_dataset_revision()["sha256"], old_revision["sha256"])
            self.assertEqual(live_shadow._PROFILE_CACHE, {})
            with patch("builtins.open", side_effect=AssertionError("unchanged file reopened")):
                self.assertEqual(live_shadow.load_history_snapshot(str(path)), records)

    def test_removed_file_clears_cached_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text('{"records":[{"id":"first"}]}', encoding="utf-8")
            live_shadow.load_history_snapshot(str(path))
            path.unlink()
            self.assertEqual(live_shadow.load_history_snapshot(str(path)), [])
            self.assertEqual(live_shadow.snapshot_size(), 0)
