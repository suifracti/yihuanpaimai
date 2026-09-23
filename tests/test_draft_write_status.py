# -*- coding: utf-8 -*-
"""Targeted unit tests for get_current_match_presentation_summary fail-closed acquired presentation."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"

for p in (
    r"C:\Program Files\Python310\Lib\site-packages",
    r"C:\Program Files\Python310\Lib\site-packages\win32",
    r"C:\Program Files\Python310\Lib\site-packages\win32\lib",
    str(PROJECT_ROOT),
    str(CORE_DIR),
    str(APP_DIR),
):
    if p not in sys.path:
        sys.path.insert(0, p)

import os
if hasattr(os, "add_dll_directory"):
    dll_dir = r"C:\Program Files\Python310\Lib\site-packages\pywin32_system32"
    if os.path.exists(dll_dir):
        os.add_dll_directory(dll_dir)


import main
from unittest.mock import Mock, patch

class DraftWriteStatusTests(unittest.TestCase):
    def setUp(self):
        main.CURRENT_MATCH.begin_next_match()
        main.CURRENT_MATCH.apply_facts({'q':12})

    def test_unavailable_never_reports_saved(self):
        with patch.object(main, 'DRAFT_ARCHIVER', Mock(db_paths=[])):
            self.assertEqual(main.draft_write_status(), 'UNAVAILABLE')
            self.assertIsNone(main._persist_current_draft_now())
            self.assertFalse(main.build_manual_alpha_payload(include_solver_input=False)['draftSaved'])

    def test_success_is_bound_to_written_revision(self):
        archiver=Mock(db_paths=['isolated']);archiver.save_draft.return_value={'id':main.CURRENT_MATCH.id}
        with patch.object(main,'DRAFT_ARCHIVER',archiver), patch.object(main,'_LAST_DRAFT_WRITE',None), patch.object(main,'_DRAFT_WRITE_FAILED',False), patch.object(main,'publish_manual_payload'):
            self.assertEqual(main.draft_write_status(),'PENDING')
            main._persist_current_draft_now()
            self.assertEqual(main.draft_write_status(),'SAVED')
            main.CURRENT_MATCH.apply_facts({'intelCost':1})
            self.assertEqual(main.draft_write_status(),'PENDING')
            archiver.save_draft.return_value=None
            main._persist_current_draft_now()
            self.assertEqual(main.draft_write_status(),'FAILED')
            self.assertFalse(main.build_manual_alpha_payload(include_solver_input=False)['draftSaved'])

    def test_native_save_failure_is_visible_and_retry_saves_the_same_match(self):
        match_id = main.CURRENT_MATCH.id
        store = Mock()
        store.lookup.return_value = None
        store.save_draft.side_effect = [RuntimeError("disk full"), {"id": match_id}]
        published = []
        source_frame = {"sha256": "known-frame", "relativePath": "source-frames/known-frame.bmp"}
        with patch.object(main, "native_observation_enabled", return_value=True), \
             patch.object(main, "NATIVE_TRIAL_DRAFT_STORE", store), \
             patch.object(main, "_NATIVE_TRIAL_SOURCE_FRAMES", [source_frame]), \
             patch.object(main, "_manual_draft_record", return_value={"id": match_id, "dataOrigin": "live-trial"}), \
             patch.object(main, "_LAST_DRAFT_WRITE", None), \
             patch.object(main, "_DRAFT_WRITE_FAILED", False), \
             patch.object(main, "_NATIVE_DRAFT_SAVE_ERROR", None), \
             patch.object(main, "_NATIVE_DRAFT_SAVE_ERROR_MATCH_ID", None), \
             patch.object(main, "LATEST_PAYLOAD", {"type": "manual_alpha_state", "matchId": match_id}), \
             patch.object(main, "publish_manual_payload", side_effect=lambda payload: published.append(dict(payload))):
            self.assertIsNone(main._persist_current_draft_now())
            self.assertEqual(main.draft_write_status(), "FAILED")
            self.assertIn("disk full", published[-1]["draftSaveError"])
            self.assertEqual(published[-1]["draftSaveStatus"], "FAILED")

            result = main.retry_draft_save()
            self.assertTrue(result["ok"], result)
            self.assertEqual(main.draft_write_status(), "SAVED")
            self.assertEqual(store.save_draft.call_count, 2)
            self.assertEqual(published[-1]["draftSaveStatus"], "SAVED")

if __name__=='__main__':unittest.main()
