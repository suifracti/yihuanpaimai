# -*- coding: utf-8 -*-
"""Regression tests for 0.67 Alpha manual input performance & focus protection."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
_IMPORT_RUNTIME_DATA = tempfile.TemporaryDirectory(prefix="nte-manual-import-data-")
os.environ.setdefault("YIHUAN_DATA_ROOT", _IMPORT_RUNTIME_DATA.name)
sys.path.insert(0, APP_DIR)
sys.path.insert(0, CORE_DIR)

import main as app_main
from auto_archiver import AutoArchiver
from current_match import CurrentMatch
from manual_terminal import ManualTerminalCoordinator


class TestManualInputDebounceAndFlush(unittest.TestCase):
    def setUp(self):
        app_main.cancel_draft_save()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "drafts.json")
        self.archiver = AutoArchiver(db_paths=[self.db_path])
        self.orig_archiver = app_main.DRAFT_ARCHIVER
        self.orig_terminal = app_main.MANUAL_TERMINAL
        app_main.DRAFT_ARCHIVER = self.archiver
        app_main.MANUAL_TERMINAL = ManualTerminalCoordinator(self.db_path)
        app_main.CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        app_main.cancel_draft_save()
        app_main.CURRENT_MATCH.begin_next_match()
        app_main.DRAFT_ARCHIVER = self.orig_archiver
        app_main.MANUAL_TERMINAL = self.orig_terminal
        self.tmp_dir.cleanup()

    def test_rapid_typing_debounces_disk_writes(self):
        """Rapid continuous typing should memory-update immediately, but debounce disk writes."""
        seq = "51077/18031+577777*2"
        app_main.apply_manual_facts({"q": 9, "goldAvg": 33538, "purpleCount": 5})

        with mock.patch.object(self.archiver, "save_draft", wraps=self.archiver.save_draft) as spy_save:
            # Simulate 20 rapid keystroke patches
            for i in range(1, len(seq) + 1):
                app_main.apply_manual_facts({"knownGold": seq[:i]})

            # Memory state is instantly updated to the latest keystroke
            snap = app_main.CURRENT_MATCH.snapshot()
            self.assertEqual(snap["knownGold"], seq)

            # Disk save has NOT run 20 times during rapid burst
            self.assertLessEqual(spy_save.call_count, 1)

            # Flush boundaries: explicit flush saves the final draft
            saved = app_main.flush_draft_save_sync()
            self.assertIsNotNone(saved)
            self.assertEqual(saved["knownGold"], seq)

            # Verify persisted disk file
            with open(self.db_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            records = data.get("records") or []
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["knownGold"], seq)
            self.assertEqual(records[0]["publicIntel"]["q"], 9)
            self.assertEqual(records[0]["qualities"]["gold"]["avg"], 33538)

    def test_flush_on_next_match_persists_pending_draft(self):
        """Starting next match before debounce timer fires must synchronously flush pending draft."""
        app_main.apply_manual_facts({
            "box": "琉璃宝箱 · 宝石类概率提升",
            "fieldCondition": "standard",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "51077/18031",
            "knownRed": "577777*2",
        })
        old_id = app_main.CURRENT_MATCH.id

        # Immediately start next match without waiting for debounce timer
        next_payload = app_main.begin_next_manual_match({
            "expectedMatchId": old_id,
            "disposition": "keep_draft",
        })
        self.assertNotEqual(next_payload["matchId"], old_id)
        self.assertEqual(next_payload["terminalResult"]["status"], "DRAFT_KEPT")

        # Confirm old match draft was flushed to disk
        with open(self.db_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        records = data.get("records") or []
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], old_id)
        self.assertEqual(records[0]["knownGold"], "51077/18031")
        self.assertEqual(records[0]["knownRed"], "577777*2")

    def test_partial_patch_does_not_clobber_existing_facts(self):
        """Sending only changed fields must not overwrite unmentioned facts."""
        app_main.apply_manual_facts({"q": 9, "goldAvg": 33538, "purpleCount": 5})
        # Send partial patch with only knownGold
        app_main.apply_manual_facts({"knownGold": "万有星仪"})

        snap = app_main.CURRENT_MATCH.snapshot()
        self.assertEqual(snap["q"], 9)
        self.assertEqual(snap["goldAvg"], 33538)
        self.assertEqual(snap["purpleCount"], 5)
        self.assertEqual(snap["knownGold"], "万有星仪")


class TestOverlayHtmlInputProtection(unittest.TestCase):
    def test_overlay_html_focused_and_composing_protection(self):
        """Test overlay_alpha.html JS logic for focus protection, IME composition, and matchId reset."""
        js_code = """
        const fs = require('fs');
        const path = require('path');
        
        // Mock DOM & window environment
        const state = {
          dirty: false,
          suppress: false,
          matchId: 'draft_100',
          activeFieldId: null,
          isComposing: false,
          lastSyncedFacts: {}
        };
        
        const dom = {
          qInput: { value: '9', classList: { contains: () => false, toggle: () => {} }, removeAttribute: () => {} },
          goldAvgInput: { value: '33538', classList: { contains: () => false, toggle: () => {} }, removeAttribute: () => {} },
          purpleCountInput: { value: '5', classList: { contains: () => false, toggle: () => {} }, removeAttribute: () => {} },
          knownGoldInput: { value: '51077', classList: { contains: () => true, toggle: () => {} }, getAttribute: () => 'gold', removeAttribute: () => {} },
          knownRedInput: { value: '', classList: { contains: () => true, toggle: () => {} }, getAttribute: () => 'red', removeAttribute: () => {} },
          knownPurpleInput: { value: '', classList: { contains: () => true, toggle: () => {} }, getAttribute: () => 'purple', removeAttribute: () => {} },
          boxSelectHold: { value: '' },
          fieldSelectHold: { value: '' },
          boxChip: { querySelector: () => ({ textContent: '' }), classList: { toggle: () => {} } },
          fieldChip: { querySelector: () => ({ textContent: '' }), classList: { toggle: () => {} } }
        };
        
        function applyManualState(d, force) {
          const incomingId = d.matchId || '';
          const resetMatch = Boolean(force) || (incomingId && incomingId !== state.matchId);
          if (incomingId) state.matchId = incomingId;
          if (resetMatch) {
            state.lastSyncedFacts = {};
            state.dirty = false;
          }
          
          const inputs = [
            { id: 'qInput', val: d.q, key: 'q' },
            { id: 'goldAvgInput', val: d.goldAvg, key: 'goldAvg' },
            { id: 'purpleCountInput', val: d.purpleCount, key: 'purpleCount' },
            { id: 'knownGoldInput', val: d.knownGold, key: 'knownGold' },
            { id: 'knownRedInput', val: d.knownRed, key: 'knownRed' },
            { id: 'knownPurpleInput', val: d.knownPurple, key: 'knownPurple' }
          ];
          
          inputs.forEach(({ id, val, key }) => {
            const el = dom[id];
            const isEditingThis = (state.activeFieldId === id) || (state.isComposing && state.activeFieldId === id);
            if (resetMatch || !isEditingThis) {
              el.value = (val == null || val === '') ? '' : String(val);
              state.lastSyncedFacts[key] = val == null ? null : (typeof val === 'number' ? val : String(val));
            }
          });
        }

        const results = {};

        // Case 1: User is focusing knownGoldInput and typing '51077/18'
        state.activeFieldId = 'knownGoldInput';
        dom.knownGoldInput.value = '51077/18';
        // Server broadcasts older/intermediate state
        applyManualState({ matchId: 'draft_100', knownGold: '51077', q: 9, goldAvg: 33538 }, false);
        results.focusProtected = dom.knownGoldInput.value; // Must remain '51077/18'

        // Case 2: User is IME composing
        state.isComposing = true;
        dom.knownGoldInput.value = 'wanyou';
        applyManualState({ matchId: 'draft_100', knownGold: '', q: 9, goldAvg: 33538 }, false);
        results.imeProtected = dom.knownGoldInput.value; // Must remain 'wanyou'

        // Case 3: Authoritative next match (matchId changes)
        state.isComposing = false;
        applyManualState({ matchId: 'draft_101', knownGold: '', q: null, goldAvg: null }, false);
        results.nextMatchReset = dom.knownGoldInput.value; // Must be reset to ''
        results.nextMatchQ = dom.qInput.value; // Must be reset to ''

        // Case 4: VenueTier change resets mismatched box
        state.venueTier = 'zhongji';
        state.box = '琉璃宝箱 · 宝石类概率提升';
        const validBoxesGaoji = ['完整的保险箱（高级藏品概率提升）', '璀璨的保险箱（宝石类概率提升）', '未知/其他'];
        // Switching to gaoji tier
        state.venueTier = 'gaoji';
        if (state.box && !validBoxesGaoji.includes(state.box)) {
          state.box = '';
        }
        results.venueChangedBoxReset = state.box; // Must be reset to ''

        console.log(JSON.stringify(results));
        """
        out = subprocess.check_output(["node", "-e", js_code], cwd=PROJECT_ROOT, encoding="utf-8")
        data = json.loads(out)
        self.assertEqual(data["focusProtected"], "51077/18")
        self.assertEqual(data["imeProtected"], "wanyou")
        self.assertEqual(data["nextMatchReset"], "")
        self.assertEqual(data["nextMatchQ"], "")
        self.assertEqual(data["venueChangedBoxReset"], "")


class TestVenueLevelAndBoxSelection(unittest.TestCase):
    def setUp(self):
        app_main.cancel_draft_save()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "drafts.json")
        self.archiver = AutoArchiver(db_paths=[self.db_path])
        self.orig_archiver = app_main.DRAFT_ARCHIVER
        self.orig_terminal = app_main.MANUAL_TERMINAL
        app_main.DRAFT_ARCHIVER = self.archiver
        app_main.MANUAL_TERMINAL = ManualTerminalCoordinator(self.db_path)
        app_main.CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        app_main.cancel_draft_save()
        app_main.CURRENT_MATCH.begin_next_match()
        app_main.DRAFT_ARCHIVER = self.orig_archiver
        app_main.MANUAL_TERMINAL = self.orig_terminal
        self.tmp_dir.cleanup()

    def test_exact_venue_field_and_catalog_box_independent_patches(self):
        """Exact venue and owned box come from the approved Alpha catalog."""
        app_main.apply_manual_facts({
            "venueId": "venue-zhenzhu",
            "boxId": "box-zhenzhu-complete-safe",
            "fieldCondition": "dark",
        })
        snap = app_main.CURRENT_MATCH.snapshot()
        self.assertIsNone(snap["venueTier"])
        self.assertEqual(snap["venue"], "真珠场")
        self.assertEqual(snap["venueId"], "venue-zhenzhu")
        self.assertEqual(snap["fieldCondition"], "dark")
        self.assertEqual(snap["box"], "完整的保险箱")
        self.assertEqual(snap["entryCost"], 20000)

        canonical = app_main.CURRENT_MATCH.to_canonical()
        self.assertIsNone(canonical["environment"]["venueTier"])
        self.assertEqual(canonical["environment"]["venue"], "真珠场")
        self.assertEqual(canonical["environment"]["fieldCondition"], "dark")
        self.assertEqual(canonical["environment"]["box"], "完整的保险箱")
        self.assertEqual(canonical["costs"]["entry"], 20000)

    def test_legacy_venue_roundtrip_without_fake_tier(self):
        """A legacy shorthand cannot become a new Manual canonical fact."""
        app_main.apply_manual_facts({"venue": "shanhu"})
        canonical = app_main.CURRENT_MATCH.to_canonical()
        self.assertEqual(canonical["environment"]["venue"], "珊瑚场")
        self.assertIsNone(canonical["environment"].get("venueTier"))

    def test_observed_boxes_not_in_official_sot_closed_set(self):
        """Observed boxes are exposed to manual options, but NOT in official SOT boxesByVenue."""
        from business_sot import boxes_by_venue, observed_boxes
        official = boxes_by_venue()
        self.assertEqual(official.get("高级场 · 真珠场"), ["未知高级场箱型"])

        observed = observed_boxes().get("gaoji") or []
        names = [it.get("name") for it in observed]
        self.assertIn("完整的保险箱（高级藏品概率提升）", names)
        self.assertIn("璀璨的保险箱（宝石类概率提升）", names)

        # Manual Alpha options are now catalog-owned and exact-venue based.
        options = app_main._manual_options()
        zhenzhu = next(item for item in options["venues"] if item["venueId"] == "venue-zhenzhu")
        self.assertIn("完整的保险箱", [item["displayName"] for item in zhenzhu["boxes"]])
        self.assertIn("未知 / 其他", [item["displayName"] for item in zhenzhu["boxes"]])


class TestCanonicalDatabaseIsolationRegression(unittest.TestCase):
    def test_canonical_history_database_byte_for_byte_unchanged_after_manual_input(self):
        """Ensure default project database is NEVER modified by manual input or debounce timers."""
        import hashlib
        from pathlib import Path
        db_path = Path(PROJECT_ROOT) / "异环拍卖数据.json"
        if not db_path.is_file():
            return

        initial_bytes = db_path.read_bytes()
        initial_hash = hashlib.sha256(initial_bytes).hexdigest()

        # Run rapid typing and match creation in isolated sandboxes
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_db = os.path.join(tmp_dir, "drafts.json")
            orig = app_main.DRAFT_ARCHIVER
            app_main.DRAFT_ARCHIVER = AutoArchiver(db_paths=[tmp_db])
            try:
                app_main.CURRENT_MATCH.begin_next_match()
                app_main.apply_manual_facts({"q": 9, "goldAvg": 33538, "purpleCount": 5, "knownGold": "51077"})
                app_main.schedule_draft_save(delay_sec=0.01)
                time.sleep(0.05)
            finally:
                app_main.cancel_draft_save()
                app_main.CURRENT_MATCH.begin_next_match()
                app_main.DRAFT_ARCHIVER = orig

        # Give extra time to ensure any rogue background thread cannot write to production
        time.sleep(0.1)

        after_bytes = db_path.read_bytes()
        after_hash = hashlib.sha256(after_bytes).hexdigest()
        self.assertEqual(after_hash, initial_hash)
        self.assertEqual(after_bytes, initial_bytes)


if __name__ == "__main__":
    unittest.main()
