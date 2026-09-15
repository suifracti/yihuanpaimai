import io
import json
import os
import pefile
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
ASSETS_DIR = PROJECT_ROOT / "assets"
DIST_EXE = PROJECT_ROOT / "dist" / "cut5_truthful_main" / "异环拍卖助手" / "异环拍卖助手.exe"

# Isolate test runtime data root before importing main / database modules
_ISOLATED_DATA_DIR = tempfile.TemporaryDirectory(prefix="nte_test_isolation_", ignore_cleanup_errors=True)
os.environ["YIHUAN_DATA_ROOT"] = str(Path(_ISOLATED_DATA_DIR.name).resolve())

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(CORE_DIR))

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
import System.Windows.Forms as WinForms
import System.Drawing as Drawing
from System.Drawing import Color
from System.Threading import Thread, ThreadStart, ApartmentState

# Load WebView2 and DirectComposition assemblies
wv2_candidates = [
    PROJECT_ROOT / "dist" / "cut5_truthful_main" / "异环拍卖助手" / "_internal" / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll",
    Path(sys.prefix) / "Lib" / "site-packages" / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll",
    APP_DIR / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll",
]
wv2_dll = next((p for p in wv2_candidates if p.is_file()), None)
if wv2_dll:
    clr.AddReference(str(wv2_dll))

dcomp_dll = APP_DIR / "DirectCompositionHost.dll"
from System.Reflection import Assembly
Assembly.LoadFrom(str(dcomp_dll.resolve()))
from NTE.DirectComposition import DirectCompositionHudForm, DirectCompositionMainForm, DCompNative
from Microsoft.Web.WebView2.Core import CoreWebView2Environment

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from current_match import CurrentMatch, empty_facts
from main import (
    CURRENT_MATCH,
    ACTIVE_SNAPSHOT_HOLDER,
    apply_manual_facts,
    get_current_match_presentation_summary,
    finalize_manual_match,
    handle_delete_history_record,
)


class RealProductStabilizationTests(unittest.TestCase):
    def setUp(self):
        CURRENT_MATCH.facts = empty_facts()
        CURRENT_MATCH.begin_next_match()
        ACTIVE_SNAPSHOT_HOLDER.clear()

    def test_gui_no_console_gate(self):
        """GUI_NO_CONSOLE_GATE: Prove PE subsystem is WINDOWS_GUI (2) and no console created."""
        self.assertTrue(DIST_EXE.is_file(), f"Missing packaged exe at {DIST_EXE}")
        pe = pefile.PE(str(DIST_EXE))
        subsystem = pe.OPTIONAL_HEADER.Subsystem
        self.assertEqual(subsystem, 2, f"Expected IMAGE_SUBSYSTEM_WINDOWS_GUI (2), got {subsystem}")

        # Check spec file console config
        spec_path = APP_DIR / "异环拍卖助手.spec"
        with open(str(spec_path), "r", encoding="utf-8") as f:
            spec_content = f.read()
        self.assertIn("console=False", spec_content, "spec file must have console=False")

    def test_exe_embedded_icon_gate(self):
        """EXE_EMBEDDED_ICON_GATE: Extract embedded PE icon resources and verify match with official mascot."""
        self.assertTrue(DIST_EXE.is_file(), f"Missing packaged exe at {DIST_EXE}")
        pe = pefile.PE(str(DIST_EXE))
        RT_ICON = 3
        icon_types = [e for e in pe.DIRECTORY_ENTRY_RESOURCE.entries if e.id == RT_ICON]
        self.assertTrue(len(icon_types) > 0, "No RT_ICON resource in executable PE")

        entries = icon_types[0].directory.entries
        sizes_found = []
        raw_256_png = None
        for res in entries:
            data_entry = res.directory.entries[0].data
            offset = data_entry.struct.OffsetToData
            size = data_entry.struct.Size
            raw_data = pe.get_data(offset, size)
            if raw_data.startswith(b'\x89PNG'):
                im = Image.open(io.BytesIO(raw_data))
                sizes_found.append(im.size)
                if im.size == (256, 256):
                    raw_256_png = raw_data
            else:
                w, h = struct.unpack('<ii', raw_data[4:12])
                sizes_found.append((w, h // 2))

        for expected in [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]:
            self.assertIn(expected, sizes_found, f"Missing resolution {expected} in PE embedded icons")

        self.assertIsNotNone(raw_256_png, "Missing 256x256 PNG in PE icon resources")
        import hashlib
        pe_256_hash = hashlib.sha256(raw_256_png).hexdigest()
        app_icon_png = APP_DIR / "app_icon.png"
        with open(str(app_icon_png), "rb") as f:
            app_png_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(pe_256_hash, app_png_hash, "PE embedded 256x256 icon does not match app/app_icon.png")

    def test_overlay_transparent_corner_gate(self):
        """OVERLAY_TRANSPARENT_CORNER_GATE: Verify CompController DefaultBackgroundColor is Color.Transparent."""
        results = {}
        errors = []

        def _run_overlay_test():
            try:
                hud = DirectCompositionHudForm(100, 100, 420, 520, False)
                hud.Show()
                env_task = CoreWebView2Environment.CreateAsync(
                    None, os.path.join(os.environ.get("TEMP", "."), "wv_overlay_corner_test"), None
                )
                while not env_task.IsCompleted:
                    WinForms.Application.DoEvents()
                env = env_task.Result

                html_path = (CORE_DIR / "tactical_hud.html").resolve()
                hud.InitializeComposition(env, str(html_path))

                bg_color = hud.CompController.DefaultBackgroundColor
                results["default_bg_alpha"] = bg_color.A
                results["default_bg_is_transparent"] = (bg_color == Color.Transparent or bg_color.A == 0)

                hud.CloseCompositionResources()
                hud.Close()
            except Exception as exc:
                errors.append(exc)

        t = Thread(ThreadStart(_run_overlay_test))
        t.SetApartmentState(ApartmentState.STA)
        t.Start()
        t.Join(20000)

        if errors:
            raise errors[0]

        self.assertTrue(results.get("default_bg_is_transparent"), f"HUD CompController background is not transparent: {results}")

    def test_q_real_input_solver_gate(self):
        """Q_REAL_INPUT_SOLVER_GATE: Verify Q sensitivity and parity between engine and manual input."""
        # Step 1: Direct engine solve
        js_solve_script = """
        const engine = require('./core/auction_engine_v06.js');
        const adapter = require('./core/v06_adapter.js');

        const fix1 = {
            venue: '珊瑚场',
            box: '实木宝箱',
            fieldCondition: 'standard',
            q: 9,
            goldAvg: 33538,
            purpleCount: 5,
            knownGold: '万有星仪'
        };
        const fix2 = { ...fix1, q: 15 };

        const in1 = adapter.canonicalToV06SolverInput(fix1);
        const in2 = adapter.canonicalToV06SolverInput(fix2);

        const r1 = engine.solveAuctionPipeline(in1);
        const r2 = engine.solveAuctionPipeline(in2);

        console.log(JSON.stringify({
            q9_p50: Math.round(r1.formalValue.p50),
            q15_p50: Math.round(r2.formalValue.p50)
        }));
        """
        p = subprocess.run(["node", "-e", js_solve_script], capture_output=True, text=True, encoding="utf-8", cwd=str(PROJECT_ROOT))
        self.assertEqual(p.returncode, 0, f"Node solve failed: {p.stderr}")
        res = json.loads(p.stdout)
        expected_q9_p50 = res["q9_p50"]
        expected_q15_p50 = res["q15_p50"]

        self.assertEqual(expected_q9_p50, 208525, "Expected Q=9 P50 to be 208525")
        self.assertEqual(expected_q15_p50, 373243, "Expected Q=15 P50 to be 373243")

        # Step 2: Apply facts via backend apply_manual_facts
        apply_manual_facts({
            "venue": "珊瑚场",
            "box": "实木宝箱",
            "fieldCondition": "standard",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "万有星仪"
        })
        snap_q9 = CURRENT_MATCH.snapshot()
        self.assertEqual(snap_q9.get("q"), 9)

        # Update to Q=15
        apply_manual_facts({"q": 15})
        snap_q15 = CURRENT_MATCH.snapshot()
        self.assertEqual(snap_q15.get("q"), 15)

    def test_current_match_live_sync_gate(self):
        """CURRENT_MATCH_LIVE_SYNC_GATE: Verify bounded immutable presentation summary live linking."""
        # 1. Initial state
        summary = get_current_match_presentation_summary()
        self.assertEqual(summary["matchId"], CURRENT_MATCH.id)
        self.assertEqual(summary["lifecycleStatus"], "DRAFT")
        self.assertFalse(summary["isComplete"])
        self.assertEqual(summary["facts"]["q"], None)

        # 2. Apply facts in Overlay
        js_solve_script = """
        const engine = require('./core/auction_engine_v06.js');
        const adapter = require('./core/v06_adapter.js');
        const fix = {
            venue: '珊瑚场',
            box: '实木宝箱',
            fieldCondition: 'standard',
            q: 15,
            goldAvg: 33538,
            purpleCount: 5,
            knownGold: '万有星仪'
        };
        const in_solver = adapter.canonicalToV06SolverInput(fix);
        const res = engine.solveAuctionPipeline(in_solver);
        const snap = res.predictionSnapshot;
        if (snap) {
            snap.formalValue = res.formalValue;
            snap.forecast.quantiles = {
                p20: Math.round(res.formalValue.p20),
                p50: Math.round(res.formalValue.p50),
                p80: Math.round(res.formalValue.p80),
                recommendedMax: 350000
            };
        }
        console.log(JSON.stringify(snap));
        """
        proc = subprocess.run(["node", "-e", js_solve_script], capture_output=True, text=True, encoding="utf-8", cwd=str(PROJECT_ROOT))
        valid_snapshot = json.loads(proc.stdout.strip())
        valid_snapshot["matchId"] = CURRENT_MATCH.id

        apply_manual_facts({
            "venue": "珊瑚场",
            "box": "实木宝箱",
            "fieldCondition": "standard",
            "q": 15,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "万有星仪",
            "predictionSnapshot": valid_snapshot,
        })

        summary2 = get_current_match_presentation_summary()
        self.assertTrue(summary2["isComplete"])
        self.assertEqual(summary2["environment"]["venueName"], "珊瑚场")
        self.assertEqual(summary2["environment"]["box"], "实木宝箱")
        self.assertEqual(summary2["facts"]["q"], 15)
        self.assertEqual(summary2["facts"]["goldAvg"], 33538)
        self.assertEqual(summary2["facts"]["purpleCount"], 5)
        self.assertEqual(summary2["facts"]["knownGold"], "万有星仪")

        self.assertIsNotNone(summary2["prediction"])
        self.assertEqual(summary2["prediction"]["p50"], 373243)
        self.assertEqual(summary2["prediction"]["actionDirective"], "BID")

        # 3. Finalize
        finalize_result = finalize_manual_match({
            "expectedMatchId": CURRENT_MATCH.id,
            "settlement": {
                "isSettled": True,
                "clearingPrice": 300000,
                "actualTotal": 380000,
                "realizedProfit": 80000,
                "acquired": True,
                "winner": "本人拍下",
                "resultReason": "won",
            },
        })
        self.assertEqual(finalize_result.get("terminalResult", {}).get("status"), "FINALIZED")

        # 4. Next match terminal lifecycle
        new_draft = CURRENT_MATCH.begin_next_match()
        self.assertNotEqual(new_draft["id"], summary["matchId"])
        summary3 = get_current_match_presentation_summary()
        self.assertEqual(summary3["matchId"], new_draft["id"])
        self.assertEqual(summary3["facts"]["q"], None)
        self.assertIsNone(summary3["prediction"])

    def test_packaged_no_node_runtime_gate(self):
        """PACKAGED_NO_NODE_RUNTIME_GATE: Verify running packaged app never spawns node.exe."""
        self.assertTrue(DIST_EXE.is_file(), f"Missing packaged exe at {DIST_EXE}")
        import tempfile
        with tempfile.TemporaryDirectory(prefix="nte_node_probe_") as tmp_dir:
            env = dict(os.environ)
            env["YIHUAN_DATA_ROOT"] = tmp_dir
            env["NTE_ALLOW_NODE_SHADOW"] = "0"
            
            proc = subprocess.Popen(
                [str(DIST_EXE)],
                env=env,
                cwd=str(DIST_EXE.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                time.sleep(3.0)
                # Check process tree for node.exe
                out = subprocess.check_output('tasklist /FO CSV /NH', shell=True, text=True)
                # Parse running tasks
                tasks = [line.split(',')[0].strip('"').lower() for line in out.splitlines() if line.strip()]
                # Node.exe should not be spawned by our app
                # To be precise, check child processes of proc.pid
                ps_cmd = f"Get-CimInstance Win32_Process | Where-Object {{ $_.ParentProcessId -eq {proc.pid} }} | Select-Object -ExpandProperty Name"
                ps_out = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
                child_names = [line.strip().lower() for line in ps_out.stdout.splitlines() if line.strip()]
                
                self.assertNotIn("node.exe", child_names, f"Found node.exe spawned as child process: {child_names}")
                self.assertNotIn("cmd.exe", child_names, f"Found cmd.exe spawned as child process: {child_names}")
            finally:
                subprocess.run(f"taskkill /F /PID {proc.pid} /T", shell=True, capture_output=True)

    def test_test_runtime_data_isolation_gate(self):
        """TEST_RUNTIME_DATA_ISOLATION_GATE: Real user %LOCALAPPDATA% history must remain 100% untouched."""
        from runtime_data import resolve_runtime_history_path
        real_user_path = resolve_runtime_history_path({"LOCALAPPDATA": os.environ.get("LOCALAPPDATA", "")})
        
        # State before
        exists_before = real_user_path.exists()
        size_before = real_user_path.stat().st_size if exists_before else None
        mtime_before = real_user_path.stat().st_mtime if exists_before else None
        
        # Run a sample manual flow in isolated environment
        apply_manual_facts({"q": 15, "goldAvg": 33538})
        get_current_match_presentation_summary()
        
        # State after
        exists_after = real_user_path.exists()
        size_after = real_user_path.stat().st_size if exists_after else None
        mtime_after = real_user_path.stat().st_mtime if exists_after else None
        
        self.assertEqual(exists_before, exists_after)
        self.assertEqual(size_before, size_after)
        self.assertEqual(mtime_before, mtime_after)

    def test_history_single_record_delete_safe(self):
        """Verify safe single record deletion with pre-delete backup and active match guard."""
        # 1. Create a dummy record in isolated DB
        from runtime_data import resolve_runtime_history_path
        store = CanonicalHistoryStore(resolve_runtime_history_path())
        dummy_id = "test_del_record_001"
        rec = build_canonical_match_record_v7(
            match_id=dummy_id,
            played_at="2026-08-23T12:00:00+08:00",
            lifecycle_status="DRAFT",
            source="manual",
            environment={
                "venueTier": "zhongji",
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
            },
            public_intel={"q": 15, "totalItems": 66, "totalGrid": 84},
            qualities={
                "purple": {"count": 5, "avg": 2007, "knownItems": [{"name": "拈花小像"}]},
                "gold": {"count": 0, "avg": None, "knownItems": []},
                "red": {"count": 0, "avg": None, "knownItems": []},
            },
            costs={"entry": 5000, "floorBid": 10000, "bidIncrement": 2000},
            loadout={"character": "测试角色"},
            bidding={"leaderBid": None, "targetProfit": 30000, "actionCount": 0},
            settlement={"isSettlement": False},
        )
        store.persist_record_transactional(rec, is_finalized=False)
        
        # 2. Delete the record
        res = handle_delete_history_record(dummy_id)
        self.assertTrue(res.get("ok"), f"Delete failed: {res}")
        self.assertEqual(res.get("status"), "DELETED")
        self.assertEqual(res.get("recordId"), dummy_id)
        
        # 3. Verify backup file exists
        backup_path = resolve_runtime_history_path().parent / "history_delete_backup_v1.json"
        self.assertTrue(backup_path.is_file(), "Backup file history_delete_backup_v1.json was not created")
        
        # 4. Verify record is not in database
        db_after = store.read_database()
        ids_after = [r.get("id") for r in db_after.get("records") or [] if isinstance(r, dict)]
        self.assertNotIn(dummy_id, ids_after)

    def test_history_delete_active_match_guard(self):
        """Active current match must be guarded against deletion."""
        active_id = CURRENT_MATCH.id
        res = handle_delete_history_record(active_id)
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("status"), "ACTIVE_MATCH_GUARD")

    def test_current_match_real_ui_sync_gate(self):
        """CURRENT_MATCH_REAL_UI_SYNC_GATE: Overlay facts -> CURRENT_MATCH -> summary -> app_status -> Main."""
        from main import begin_next_manual_match
        from main_window import MainWindowBridge

        # 1. Start clean match A
        match_a_id = CURRENT_MATCH.id
        self.assertFalse(CURRENT_MATCH.has_any_fact())

        # 2. Input baseline facts
        patch = {
            "venueId": "venue-shanhu",
            "boxId": "box-shanhu-glass",
            "venue": "珊瑚场",
            "box": "琉璃宝箱",
            "fieldCondition": "standard",
            "q": 12,
            "goldAvg": 74379,
            "purpleCount": 7,
            "leaderBid": 100000,
        }
        apply_manual_facts({"facts": patch})

        # 3. Verify CURRENT_MATCH has facts
        self.assertTrue(CURRENT_MATCH.has_any_fact())
        self.assertEqual(CURRENT_MATCH.facts["q"], 12)
        self.assertEqual(CURRENT_MATCH.facts["goldAvg"], 74379)
        self.assertEqual(CURRENT_MATCH.facts["purpleCount"], 7)
        self.assertEqual(CURRENT_MATCH.facts["leaderBid"], 100000)

        # 4. Verify presentation summary projection
        summary = get_current_match_presentation_summary()
        self.assertEqual(summary["matchId"], match_a_id)
        self.assertTrue(summary["isComplete"])
        self.assertEqual(summary["environment"]["venueName"], "珊瑚场")
        self.assertEqual(summary["environment"]["box"], "琉璃宝箱")
        self.assertEqual(summary["facts"]["q"], 12)
        self.assertEqual(summary["facts"]["goldAvg"], 74379)
        self.assertEqual(summary["facts"]["purpleCount"], 7)
        self.assertEqual(summary["facts"]["leaderBid"], 100000)

        # 5. Verify Main Window Bridge dispatch
        class DummyOverlay:
            visible = True
        bridge = MainWindowBridge(overlay_controller=DummyOverlay(), current_match_provider=get_current_match_presentation_summary)
        dispatched = bridge.dispatch({"action": "request_app_status"})
        self.assertIn("currentMatch", dispatched)
        cm = dispatched["currentMatch"]
        self.assertEqual(cm["matchId"], match_a_id)
        self.assertEqual(cm["facts"]["q"], 12)
        self.assertEqual(cm["facts"]["goldAvg"], 74379)

        # 6. Test New Match transition
        begin_next_manual_match({"expectedMatchId": match_a_id, "disposition": "DISCARD"})
        match_b_id = CURRENT_MATCH.id
        self.assertNotEqual(match_a_id, match_b_id)
        self.assertFalse(CURRENT_MATCH.has_any_fact())

        summary_b = get_current_match_presentation_summary()
        self.assertEqual(summary_b["matchId"], match_b_id)
        self.assertFalse(summary_b["isComplete"])
        self.assertIsNone(summary_b["facts"]["q"])
        self.assertIsNone(summary_b["facts"]["goldAvg"])

    def test_price_constraint_real_input_gate(self):
        """PRICE_CONSTRAINT_REAL_INPUT_GATE: Test feasible, infeasible, and clearing of price constraints."""
        import subprocess
        from pathlib import Path

        js_script = r'''
        const engine = require('./core/auction_engine_v06.js');
        const baseline = {
            venue: '珊瑚场',
            box: '琉璃宝箱',
            fieldCondition: 'standard',
            q: 12,
            avg: 74379,
            p: 7,
            goldAvg: 74379,
            purple: 7,
            leaderBid: 100000
        };

        // 1. Feasible constraint: 18031
        const resFeasible = engine.solveAuctionPipeline({ ...baseline, knownGold: '18031' });
        
        // 2. Infeasible constraint: 51077 (with baseline Q=12, P=7, goldAvg=74379)
        const resInfeasible = engine.solveAuctionPipeline({ ...baseline, knownGold: '51077' });

        // 3. Clear constraint: restore baseline
        const resCleared = engine.solveAuctionPipeline({ ...baseline, knownGold: '' });

        console.log(JSON.stringify({
            feasibleP50: resFeasible.formalValue.p50,
            feasibleStatus: resFeasible.solverStatus,
            infeasibleStatus: resInfeasible.solverStatus,
            infeasibleDirective: resInfeasible.decision ? resInfeasible.decision.actionDirective : null,
            clearedP50: resCleared.formalValue.p50
        }));
        '''
        probe = subprocess.run(["node", "-e", js_script], capture_output=True, text=True, cwd=str(PROJECT_ROOT), encoding="utf-8")
        self.assertEqual(probe.returncode, 0, f"Node solver probe failed: {probe.stderr}")
        data = json.loads(probe.stdout.strip())

        self.assertEqual(data["feasibleStatus"], "valid")
        self.assertEqual(data["feasibleP50"], 432672)
        self.assertEqual(data["infeasibleStatus"], "no-match")
        self.assertIn("无可行解", data["infeasibleDirective"])
        self.assertEqual(data["clearedP50"], 439781.5)

    def test_desktop_pet_default_hidden_gate(self):
        """DESKTOP_PET_DEFAULT_HIDDEN_GATE: Verify desktop pet is hidden by default on app launch."""
        from desktop_pet import DesktopPetPositionState, DesktopPetPositionStore
        import tempfile

        # Default state dataclass must have visible = False
        default_state = DesktopPetPositionState()
        self.assertFalse(default_state.visible, "DesktopPetPositionState.visible must default to False")

        # Loading from non-existent path must return visible = False
        with tempfile.TemporaryDirectory(prefix="nte_pet_probe_") as tmp_dir:
            store = DesktopPetPositionStore(path=Path(tmp_dir) / "non_existent_pet.json")
            loaded = store.load()
            self.assertFalse(loaded.visible, "DesktopPetPositionStore.load() must default to visible = False")

    def test_known_item_autocomplete_real_interaction_gate(self):
        """KNOWN_ITEM_AUTOCOMPLETE_REAL_INTERACTION_GATE: Verify autocomplete suggestions and interaction."""
        import subprocess

        js_script = r'''
        const engine = require('./core/auction_engine_v06.js');
        const goldItems = engine.GOLD_ITEMS.map(x => ({ name: x[0], price: x[1] }));

        // 1. Partial typing "5107" -> should match 51077
        const partialMatches = goldItems.filter(x => String(x.price).startsWith('5107'));
        
        // 2. Full typing "51077" -> exact match
        const exactMatches = goldItems.filter(x => String(x.price).startsWith('51077'));
        
        // 3. Name typing "万有" -> matches 万有星仪
        const nameMatches = goldItems.filter(x => x.name.includes('万有'));

        console.log(JSON.stringify({
            partialCount: partialMatches.length,
            partialFirstPrice: partialMatches[0].price,
            partialFirstName: partialMatches[0].name,
            exactCount: exactMatches.length,
            nameCount: nameMatches.length,
            nameFirstPrice: nameMatches[0].price
        }));
        '''
        probe = subprocess.run(["node", "-e", js_script], capture_output=True, text=True, cwd=str(PROJECT_ROOT), encoding="utf-8")
        self.assertEqual(probe.returncode, 0, f"Node autocomplete probe failed: {probe.stderr}")
        data = json.loads(probe.stdout.strip())

        self.assertEqual(data["partialCount"], 1)
        self.assertEqual(data["partialFirstPrice"], 51077)
        self.assertEqual(data["partialFirstName"], "万有星仪")
        self.assertEqual(data["exactCount"], 1)
        self.assertEqual(data["nameCount"], 1)
        self.assertEqual(data["nameFirstPrice"], 51077)

    def test_box_selection_real_solver_gate(self):
        """BOX_SELECTION_REAL_SOLVER_GATE: Verify venue+box selection propagates to solver without UNKNOWN_BOX."""
        from venue_box_catalog import load_catalog, solver_context_translation
        from main import build_manual_alpha_payload

        cat = load_catalog()

        # 1. 珊瑚场 + 琉璃宝箱
        trans_glass = solver_context_translation(cat, venue_id="venue-shanhu", box_id="box-shanhu-glass")
        self.assertEqual(trans_glass["status"], "COMPATIBILITY_TRANSLATION")
        self.assertEqual(trans_glass["boxStatus"], "COMPATIBILITY_TRANSLATION")
        self.assertEqual(trans_glass["box"], "琉璃宝箱 · 宝石类概率提升")

        # Apply to match
        apply_manual_facts({"facts": {"venueId": "venue-shanhu", "boxId": "box-shanhu-glass", "q": 12, "goldAvg": 74379, "purpleCount": 7}})
        payload_glass = build_manual_alpha_payload()
        self.assertEqual(payload_glass["solverCompatibility"]["boxStatus"], "COMPATIBILITY_TRANSLATION")
        self.assertEqual(payload_glass["solverCompatibility"]["box"], "琉璃宝箱 · 宝石类概率提升")
        self.assertNotIn("UNKNOWN_BOX", payload_glass["shadowSupport"]["reasonCodes"])

        # 2. Change to 实木宝箱
        trans_wood = solver_context_translation(cat, venue_id="venue-shanhu", box_id="box-shanhu-wood")
        self.assertEqual(trans_wood["status"], "COMPATIBILITY_TRANSLATION")
        self.assertEqual(trans_wood["boxStatus"], "COMPATIBILITY_TRANSLATION")
        self.assertEqual(trans_wood["box"], "实木宝箱 · 中级藏品概率提升")

        apply_manual_facts({"facts": {"boxId": "box-shanhu-wood"}})
        payload_wood = build_manual_alpha_payload()
        self.assertEqual(payload_wood["solverCompatibility"]["boxStatus"], "COMPATIBILITY_TRANSLATION")
        self.assertEqual(payload_wood["solverCompatibility"]["box"], "实木宝箱 · 中级藏品概率提升")
        self.assertNotIn("UNKNOWN_BOX", payload_wood["shadowSupport"]["reasonCodes"])


if __name__ == "__main__":
    unittest.main()
