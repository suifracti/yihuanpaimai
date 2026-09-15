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

if __name__=='__main__':unittest.main()
