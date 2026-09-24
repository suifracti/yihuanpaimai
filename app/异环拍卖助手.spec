# -*- mode: python ; coding: utf-8 -*-
import datetime
import json
import os
import subprocess
from PyInstaller.utils.hooks import collect_all

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
PROJECT_ROOT = os.path.dirname(SPEC_DIR)

# Generate immutable build_info.json at build time
def _generate_build_info():
    code_revision = os.environ.get("NTE_BUILD_REVISION") or os.environ.get("NTE_CODE_REVISION")
    commit = ""
    is_dirty = False
    if not code_revision:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0:
                commit = proc.stdout.strip()
                status_proc = subprocess.run(
                    ["git", "status", "--porcelain", "--untracked-files=no"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                is_dirty = bool(status_proc.stdout.strip())
                code_revision = f"{commit}-dirty" if is_dirty else commit
        except Exception:
            pass
    if not code_revision:
        code_revision = "dev-unversioned"

    build_meta = {
        "codeRevision": code_revision,
        "buildCommit": commit or code_revision,
        "isDirty": is_dirty,
        "builtAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "builder": "pyinstaller-spec"
    }

    info_dir = os.environ.get("NTE_BUILD_INFO_DIR", SPEC_DIR)
    os.makedirs(info_dir, exist_ok=True)
    build_info_path = os.path.join(info_dir, "build_info.json")
    with open(build_info_path, "w", encoding="utf-8") as f:
        json.dump(build_meta, f, ensure_ascii=False, indent=2)
    return build_info_path

BUILD_INFO_FILE = _generate_build_info()
TRIAL_PROFILE_FILE = None
if os.environ.get('NTE_BUILD_ISOLATED_TRIAL') == '1':
    TRIAL_PROFILE_FILE = os.path.join(os.path.dirname(BUILD_INFO_FILE), 'isolated_trial.json')
    trial_payload = {
        'profile': 'isolated-trial-v1',
        'codeRevision': os.environ.get('NTE_BUILD_REVISION', ''),
        'builtAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    with open(TRIAL_PROFILE_FILE, 'w', encoding='utf-8') as f:
        json.dump(trial_payload, f, ensure_ascii=False, indent=2)
else:
    stale_marker = os.path.join(os.path.dirname(BUILD_INFO_FILE), 'isolated_trial.json')
    if os.path.exists(stale_marker):
        try:
            os.remove(stale_marker)
        except OSError:
            pass

datas = [
    (os.path.join(PROJECT_ROOT, 'assets', 'scene_anchors'), 'assets/scene_anchors'),
    (os.path.join(SPEC_DIR, 'config.json'), '.'),
    (os.path.join(SPEC_DIR, 'app_icon.ico'), '.'),
    (os.path.join(SPEC_DIR, 'DirectCompositionHost.dll'), '.'),
    (BUILD_INFO_FILE, '.'),
    (os.path.join(PROJECT_ROOT, 'core', 'tactical_hud.html'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'overlay_alpha.html'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'main_window.html'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'main_window.css'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'main_window.js'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'mascot_runtime_binding.js'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'auction_engine_v06.js'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'solver_core_v06.js'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'shadow_profile_v06.js'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'live_shadow_runtime.js'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'live_shadow_compute.js'), 'core'),
    (os.path.join(PROJECT_ROOT, 'runtime', 'node.exe'), 'runtime'),
    (os.path.join(PROJECT_ROOT, 'docs', 'contracts'), 'docs/contracts'),
    (os.path.join(PROJECT_ROOT, 'assets', 'items', 'verified_source_card_registry.json'), 'assets/items'),
    (os.path.join(PROJECT_ROOT, 'core', 'live_shadow_webview_adapter.js'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'v06_adapter.js'), 'core'),
    (os.path.join(PROJECT_ROOT, 'core', 'mascot.png'), 'core'),
    (os.path.join(PROJECT_ROOT, 'assets', 'catalog_065.json'), 'assets'),
    (os.path.join(PROJECT_ROOT, 'assets', 'business_sot_v06.json'), 'assets'),
    (os.path.join(PROJECT_ROOT, 'assets', 'lobby_characters'), 'assets/lobby_characters'),
    (os.path.join(PROJECT_ROOT, 'assets', 'lobby_venues'), 'assets/lobby_venues'),
    (os.path.join(PROJECT_ROOT, 'assets', 'lobby_tools'), 'assets/lobby_tools'),
    (os.path.join(PROJECT_ROOT, 'assets', 'venue_box_catalog_v1', 'venue_box_catalog_v1.json'), 'assets/venue_box_catalog_v1'),
    (os.path.join(PROJECT_ROOT, 'assets', 'venue_box_catalog_v1', 'v06_solver_compatibility_v1.json'), 'assets/venue_box_catalog_v1'),
    (os.path.join(PROJECT_ROOT, 'assets', 'items', 'catalog_reference_manifest_v1.json'), 'assets/items'),
    (os.path.join(PROJECT_ROOT, 'assets', 'items', 'catalog_reference_manifest_v2.json'), 'assets/items'),
    (os.path.join(PROJECT_ROOT, 'assets', 'items', 'visual_catalog_v2.json'), 'assets/items'),
    (os.path.join(PROJECT_ROOT, 'assets', 'items', 'video_development_references_v1.json'), 'assets/items'),
    (os.path.join(PROJECT_ROOT, 'assets', 'items', 'video_development_references_v1'), 'assets/items/video_development_references_v1'),
    (os.path.join(PROJECT_ROOT, 'assets', 'items', 'derived_warehouse_icon_references_v1'), 'assets/items/derived_warehouse_icon_references_v1'),
    (os.path.join(PROJECT_ROOT, 'assets', 'items', 'catalog_screenshots'), 'assets/items/catalog_screenshots'),
    (os.path.join(PROJECT_ROOT, 'assets', 'items', 'reference_crops_v1'), 'assets/items/reference_crops_v1'),
    (os.path.join(PROJECT_ROOT, 'lab', 'index.html'), 'lab'),
]
if TRIAL_PROFILE_FILE:
    datas.append((TRIAL_PROFILE_FILE, '.'))

# Approved mascot assets only. The manifest and state map are the runtime SOT;
# retired drafts and review sheets are intentionally not packaged.
mascot_datas = [
    ('mascot_final_asset_manifest_v1.json', 'design/mascot'),
    ('mascot_state_asset_map_v1.json', 'design/mascot'),
    ('exports/mascot_portrait_default.png', 'design/mascot/exports'),
    ('exports/mascot_default_bust.png', 'design/mascot/exports'),
    ('exports/mascot_portrait_thinking_v2.png', 'design/mascot/exports'),
    ('exports/mascot_portrait_success_v2.png', 'design/mascot/exports'),
    ('exports/mascot_avatar_round_v2.png', 'design/mascot/exports'),
    ('exports/mascot_avatar_square_v2.png', 'design/mascot/exports'),
    ('exports/chibi/mascot_chibi_idle.png', 'design/mascot/exports/chibi'),
    ('exports/chibi/mascot_chibi_thinking.png', 'design/mascot/exports/chibi'),
    ('exports/chibi/mascot_chibi_success.png', 'design/mascot/exports/chibi'),
    ('exports/chibi/mascot_chibi_warning.png', 'design/mascot/exports/chibi'),
    ('exports/chibi/mascot_chibi_sleep.png', 'design/mascot/exports/chibi'),
    ('exports/chibi/mascot_chibi_loading_v2.png', 'design/mascot/exports/chibi'),
]
datas += [
    (os.path.join(PROJECT_ROOT, 'design', 'mascot', source), destination)
    for source, destination in mascot_datas
]
binaries = []
hiddenimports = [
    'vision_pipeline',
    'shape_matcher',
    'grid_calibrator',
    'auto_archiver',
    'window_tracker',
    'settlement_item_recognizer',
    'warehouse_vision',
    'visual_catalog',
    'deferred_identity_analyzer',
    'delta_intel',
    'auction_brain',
    'session_fsm',
    'vision_contract',
    'window_capture',
    'win32gui',
    'win32con',
    'websockets',
    'webview',
    'prediction_snapshot_holder',
    'runtime_revision',
    'evaluation_eligibility',
    'history_admission',
    'canonical_match_record',
    'canonical_history_store',
    'manual_terminal',
    'effective_truth_resolver',
    'version',
    'evaluation_metrics',
    'legacy_exploratory_policy',
    'prediction_evaluation_generator',
    'venue_box_catalog',
    'settlement_review',
    'legacy_archive',
    'review_overlay',
    'snapshot_recognizer',
    'warehouse_placement_resolver',
    'warehouse_capture_production',
    'warehouse_capture_session',
    'warehouse_reconstruction',
    'warehouse_review_packet',
    'warehouse_identity_review',
    'warehouse_identity_review_session',
    'warehouse_identity_review_persist',
    'warehouse_catalog_geometry',
    'settlement_evidence_store_v2',
    'settlement_stable_frame_persist',
    'settlement_capture_links',
    'match_export_bundle',
    'match_import_bundle',
    'experiments.upper_tail_truth_support_capture_v1.capture_contract',
    'experiments.upper_tail_truth_support_capture_v1.runtime_capture_hook',
]
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    [os.path.join(SPEC_DIR, 'main.py')],
    pathex=[PROJECT_ROOT, os.path.join(PROJECT_ROOT, 'core'), SPEC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='异环拍卖助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(SPEC_DIR, 'app_icon.ico')],
    manifest=os.path.join(SPEC_DIR, 'app_manifest.xml'),
    uac_admin=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='异环拍卖助手',
)
