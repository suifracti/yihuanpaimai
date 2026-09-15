# -*- coding: utf-8 -*-
"""Isolated Real App Launch, 39-Item History Review, Restart & DOM Export Verification.

Validates in a clean, isolated environment:
1. Launches real application (app/main.py) with isolated YIHUAN_DATA_ROOT.
2. In History view DOM, clicks the target 39-item record (dense_audit_20260908_144037).
3. Verifies in DOM:
   - 39 units loaded with the explicitly expected confirmation counts.
   - For all confirmed units: official name, catalogId, and raw crop.
   - For all candidate-only units: candidate options and raw crop.
   - Warehouse identity summary card: caption and facts text.
4. Triggers the REAL export button (#history-export-btn) via DOM click.
5. Verifies exported .zip bundle:
   - Contains the exact file set (original images, 39 crops, index, records, manifest).
   - All files have 100% SHA-256 integrity match.
   - records.json is relocatable and paths are desensitized.
6. Graceful WM_CLOSE clean exit.
7. Re-launches the real application process (simulating true process restart).
8. Re-queries DOM in second instance to verify complete, identical read-back across restart.
9. Second clean WM_CLOSE exit.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(r"D:\yihuanpaimai").resolve()
sys.path[:0] = [
    str(ROOT / "core"),
    str(ROOT / "app"),
    str(ROOT / "tools"),
    str(ROOT / "tests"),
    "C:/Program Files/Python310/Lib/site-packages",
    "C:/Program Files/Python310/Lib/site-packages/win32",
    "C:/Program Files/Python310/Lib/site-packages/win32/lib",
    "C:/Program Files/Python310/Lib/site-packages/Pythonwin",
]

import websockets
from canonical_history_store import CanonicalHistoryStore
from match_export_bundle import export_match_bundle
from warehouse_auto_confirmation import evaluate_auto_confirmation
from warehouse_identity_review import artifact_fingerprint_for
from warehouse_occupancy_adapter import adapt_review_packet_to_warehouse_occupancy
from verify_p1_real_ui import WS, eval_main, start_source, stop_source

OUT_DIR = ROOT / "build" / "diagnosis_20260911" / "p3-warehouse" / "isolated_app_real_test"
TARGET_MATCH_ID = "dense_audit_20260908_144037"
SOURCE_PACKET = ROOT / "build/diagnosis_20260911/p3-warehouse/video_audit_retest_v5/audit_review_packet.json"
SOURCE_EVIDENCE = ROOT / "build/diagnosis_20260909/p3-warehouse/store_dense/evidence"
EXPECTED_CONFIRMED = 28
EXPECTED_CANDIDATE = 11
EXPECTED_BLOBS = 12


def configure_evidence(packet_path: Path, evidence_root: Path, expected_confirmed: int):
    global SOURCE_PACKET, SOURCE_EVIDENCE, EXPECTED_CONFIRMED, EXPECTED_CANDIDATE, EXPECTED_BLOBS
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if packet.get("recordStableKey") != TARGET_MATCH_ID or len(packet.get("reviewUnits") or []) != 39:
        raise ValueError("This acceptance suite requires the 39-item development match")
    if not 0 <= expected_confirmed <= 39:
        raise ValueError("Expected confirmed count must be between 0 and 39")
    SOURCE_PACKET, SOURCE_EVIDENCE = packet_path, evidence_root
    EXPECTED_CONFIRMED = expected_confirmed
    EXPECTED_CANDIDATE = 39 - expected_confirmed
    EXPECTED_BLOBS = len({s["sha256"] for s in packet["segments"]})


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_isolated_environment(data_root: Path) -> None:
    """Prepares isolated directory with canonical history, crops, and evidence."""
    data_root.mkdir(parents=True, exist_ok=True)

    # 1. Copy original evidence blobs and index
    src_evidence = SOURCE_EVIDENCE
    dst_evidence = data_root / "evidence"
    if dst_evidence.exists():
        shutil.rmtree(dst_evidence)
    shutil.copytree(src_evidence, dst_evidence)

    # 2. Generate every crop from the selected packet's original evidence.
    dst_crops = data_root / "crops"
    if dst_crops.exists():
        shutil.rmtree(dst_crops)
    dst_crops.mkdir(parents=True)

    # 3. Build canonical history database with base record
    hist_dir = data_root / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    hist_path = hist_dir / "异环拍卖数据.json"

    store = CanonicalHistoryStore(str(hist_path))
    src_hist_file = ROOT / "build" / "diagnosis_20260911" / "p3-warehouse" / "auto_confirmation_run_v5" / "history" / "test_canonical_history.json"
    src_data = json.loads(src_hist_file.read_text(encoding="utf-8"))
    base_rec = src_data["records"][0]
    for key in ("reviewUnits", "warehouseIdentityReview", "warehouseOccupancy"):
        base_rec["settlement"].pop(key, None)
    base_rec["settlement"]["clearingPrice"] = 990000
    base_rec["settlement"]["actualTotal"] = 1050070
    base_rec["settlement"]["realizedProfit"] = 60070
    base_rec["settlement"]["acquired"] = True
    base_rec["settlement"]["winner"] = "本人拍下"
    base_rec["settlement"]["isSettled"] = True
    store.persist_record_transactional(base_rec, is_finalized=False)

    # 4. Load the caller-selected raw packet without a prefabricated review.
    packet = json.loads(SOURCE_PACKET.read_text(encoding="utf-8"))
    # 5. Production WarehouseCaptureHost executes the real transaction:
    # evaluate_auto_confirmation -> build_auto_identity_review_artifact -> persist_warehouse_evidence
    from warehouse_capture_host import WarehouseCaptureHost
    host = WarehouseCaptureHost(
        history_store_factory=lambda: store,
    )
    result = host.persist_warehouse_occupancy_and_review(packet)
    if result is None:
        raise RuntimeError("Production WarehouseCaptureHost failed to persist warehouse evidence from selected packet!")

    rec = store.get_record(TARGET_MATCH_ID)
    st = rec.get("settlement", {})
    ir_artifact = st.get("warehouseIdentityReview")
    if not ir_artifact:
        raise RuntimeError("Production WarehouseCaptureHost did not generate/persist warehouseIdentityReview!")

    # Verify that the production host automatically bound cropPath and cropSha256 into reviewUnits natively
    units = st.get("reviewUnits", [])
    if not units or len(units) != 39:
        raise RuntimeError(f"Expected 39 reviewUnits persisted by host, got {len(units)}!")
    missing_crops = [u.get("reviewUnitId") for u in units if not (u.get("cropPath") and u.get("cropSha256"))]
    if missing_crops:
        raise RuntimeError(f"Production WarehouseCaptureHost failed to bind crops and hashes natively into units: {missing_crops}")

    (data_root / "ir_artifact.json").write_text(json.dumps(ir_artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    (data_root / "evaluated_units.json").write_text(json.dumps(units, ensure_ascii=False, indent=2), encoding="utf-8")


async def interact_with_real_app(zip_out: Optional[Path], trigger_export: bool) -> Dict[str, Any]:
    """Interacts with the real application WebView DOM via WebSocket."""
    async with websockets.connect(WS) as socket:
        await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
        await asyncio.sleep(0.5)

        # 1. Navigate to History view
        view = await eval_main(socket, "showView('history'); dashboard.currentView")

        # 2. Wait up to 10s for history items to render
        for _ in range(50):
            count = await eval_main(socket, "document.querySelectorAll('#history-list .history-item').length")
            if count and int(count) > 0:
                break
            await asyncio.sleep(0.2)

        # 3. Check if target match item is already selected; if not, click it
        click_res = await eval_main(socket, f"""(() => {{
            const items = Array.from(document.querySelectorAll('#history-list .history-item'));
            const target = items.find(el => el.getAttribute('data-record-id') === {json.dumps(TARGET_MATCH_ID)});
            if (!target) return {{ found: false, count: items.length }};
            const isSelected = target.classList.contains('is-selected') || (dashboard.selectedRecordId === {json.dumps(TARGET_MATCH_ID)});
            if (!isSelected) {{
                target.click();
            }}
            return {{ found: true, count: items.length, wasSelected: isSelected }};
        }})()""")

        await asyncio.sleep(0.5)

        # 4. Wait for detail card, 39 review cards to render in DOM, and review data to be populated
        ready = False
        for _ in range(60):
            ready = await eval_main(socket, """(() => {
                const detailCard = document.getElementById('history-detail-card');
                if (!detailCard || detailCard.hidden) return false;
                const cards = document.querySelectorAll('#review-proposals .grouping-card');
                if (cards.length < 39) return false;
                const rev = dashboard.review || {};
                if (!rev.reviewUnits || !Array.isArray(rev.reviewUnits) || rev.reviewUnits.length < 39) return false;
                return true;
            })()""")
            if ready:
                break
            await asyncio.sleep(0.2)

        if not ready:
            raise RuntimeError(f"Timeout waiting for review DTO with reviewUnits and 39 cards to render in DOM for match {TARGET_MATCH_ID}!")

        # 5. Extract detail card & 39 units verification data from DOM and client state
        dom_detail = await eval_main(socket, f"""JSON.stringify((() => {{
            try {{
                const detailCard = document.getElementById('history-detail-card');
                const matchId = (document.getElementById('detail-match-id')?.textContent || '').trim();
                const lifecycle = (document.getElementById('detail-lifecycle-badge')?.textContent || '').trim();
                const clearingPrice = (document.getElementById('detail-clearing-price')?.textContent || '').trim();
                const actualTotal = (document.getElementById('detail-actual-total')?.textContent || '').trim();
                const profit = (document.getElementById('detail-profit')?.textContent || '').trim();
                const warehouseText = (document.getElementById('detail-warehouse')?.textContent || '').trim();
                const wirCaption = (document.getElementById('wir-saved-caption')?.textContent || '').trim();
                const wirFacts = (document.getElementById('wir-saved-facts')?.textContent || '').trim();
                const wirSummaryVisible = Boolean(document.getElementById('wir-saved-summary') && !document.getElementById('wir-saved-summary').hidden);

                const review = dashboard.review || {{}};
                if (!review.reviewUnits || !Array.isArray(review.reviewUnits) || review.reviewUnits.length !== 39) {{
                    throw new Error("Missing or invalid dashboard.review.reviewUnits in WebSocket DTO!");
                }}
                const reviewUnits = review.reviewUnits;

                const historyDetailRenderCount = dashboard.historyDetailRenderCount || 0;
                const loadSettlementReviewCount = dashboard.loadSettlementReviewCount || 0;
                const reviewSectionRenderCount = dashboard.reviewSectionRenderCount || 0;
                const singleRenderOk = (historyDetailRenderCount === 1 && loadSettlementReviewCount === 1 && reviewSectionRenderCount === 1);
                const doubleRenderDetected = !singleRenderOk;

                const unitSummaries = reviewUnits.map(u => ({{
                    reviewUnitId: u.reviewUnitId,
                    confirmationStatus: u.confirmationStatus,
                    canonicalName: u.canonicalName,
                    selectedCatalogId: u.selectedCatalogId,
                    candidateCount: (u.candidates || []).length,
                    cropPath: u.cropPath,
                    cropSha256: u.cropSha256,
                }}));

                const confirmedList = unitSummaries.filter(u => u.confirmationStatus === 'CONFIRMED');
                const candidateList = unitSummaries.filter(u => u.confirmationStatus === 'CANDIDATE_ONLY');

                const domCards = Array.from(document.querySelectorAll('#review-proposals .grouping-card'));
                const domCardSummaries = domCards.map((el, i) => {{
                    const title = (el.querySelector('.card-region-title')?.textContent || '').trim();
                    const badge = (el.querySelector('.proposal-status-badge')?.textContent || '').trim();
                    const candNames = Array.from(el.querySelectorAll('.review-cand-btn .cand-name')).map(b => (b.textContent || '').trim());
                    const candBtnCount = el.querySelectorAll('.review-cand-btn').length;
                    const thumb = el.querySelector('.grouping-thumb img');
                    const hasThumb = Boolean(thumb && thumb.src && thumb.src.startsWith('data:image/png;base64,'));
                    return {{
                        idx: i + 1,
                        title,
                        badge,
                        candNames,
                        candBtnCount,
                        hasThumb,
                    }};
                }});

                return {{
                    cardVisible: Boolean(detailCard && !detailCard.hidden),
                    matchId,
                    lifecycle,
                    clearingPrice,
                    actualTotal,
                    profit,
                    warehouseText,
                    wirSummaryVisible,
                    wirCaption,
                    wirFacts,
                    singleRenderOk,
                    doubleRenderDetected,
                    renderCounts: {{
                        historyDetail: historyDetailRenderCount,
                        loadSettlementReview: loadSettlementReviewCount,
                        reviewSection: reviewSectionRenderCount,
                    }},
                    totalUnits: unitSummaries.length,
                    confirmedCount: confirmedList.length,
                    candidateCount: candidateList.length,
                    domCardCount: domCards.length,
                    domCardsWithThumbs: domCardSummaries.filter(c => c.hasThumb).length,
                    domCardSummaries,
                    units: unitSummaries,
                }};
            }} catch (err) {{
                return {{
                    jsError: String(err && err.message ? err.message : err),
                    stack: String(err && err.stack ? err.stack : ''),
                }};
            }}
        }})())""")

        if dom_detail is None:
            raise RuntimeError(f"eval_main returned None for dom_detail for match {TARGET_MATCH_ID}!")
        parsed_dom = json.loads(dom_detail) if isinstance(dom_detail, str) else dom_detail
        if isinstance(parsed_dom, dict) and "jsError" in parsed_dom:
            raise RuntimeError(f"DOM extraction failed with JS error: {parsed_dom['jsError']}\nStack: {parsed_dom.get('stack')}")

        # 6. Trigger real export button in DOM if requested
        export_res = None
        if trigger_export and zip_out:
            await eval_main(socket, f"""(() => {{
                const btn = document.getElementById('history-export-btn');
                if (btn) {{
                    btn.dataset.outputPath = {json.dumps(str(zip_out))};
                    btn.click();
                }}
            }})()""")

            # Poll for ZIP output
            for _ in range(60):
                if zip_out.is_file() and zip_out.stat().st_size > 0:
                    status_text = await eval_main(socket, "document.getElementById('history-export-status')?.textContent || ''")
                    export_res = {
                        "ok": True,
                        "sizeBytes": zip_out.stat().st_size,
                        "statusText": status_text,
                    }
                    break
                await asyncio.sleep(0.2)
            if not export_res:
                status_text = await eval_main(socket, "document.getElementById('history-export-status')?.textContent || ''")
                export_res = {"ok": False, "statusText": status_text, "sizeBytes": 0}

        return {
            "currentView": view,
            "clickTarget": click_res,
            "domDetail": dom_detail,
            "exportResult": export_res,
        }


def run_one_launch(
    tag: str,
    data_root: Path,
    log_path: Path,
    work_dir: Path,
    zip_out: Optional[Path] = None,
    trigger_export: bool = False,
    interactor=None,
    frozen_executable: Optional[Path] = None,
    default_data_local_root: Optional[Path] = None,
    vision_enabled: bool = False,
) -> Tuple[bool, Dict[str, Any], bool]:
    """Runs a single live application process, conducts DOM queries/export, and safely exits."""
    env = os.environ.copy()
    python_path_parts = [
        str(ROOT / "core"),
        str(ROOT / "app"),
        str(ROOT / "tools"),
        str(ROOT / "tests"),
        "C:/Program Files/Python310/Lib/site-packages",
        "C:/Program Files/Python310/Lib/site-packages/win32",
        "C:/Program Files/Python310/Lib/site-packages/win32/lib",
        "C:/Program Files/Python310/Lib/site-packages/Pythonwin",
    ]
    env["PYTHONPATH"] = ";".join(python_path_parts)
    env.update({
        "YIHUAN_DATA_ROOT": str(data_root),
        "LOCALAPPDATA": str(work_dir / f"local_app_data_{tag}"),
        "NTE_DISABLE_VISION": "0" if vision_enabled else "1",
        "NTE_DISABLE_ICON": "1",
        "NTE_ALLOW_HUD_CAPTURE": "1",
        "NTE_DEBUG": "1",
        "NTE_LOG_FILE": str(log_path),
    })
    if default_data_local_root is not None:
        env.pop("YIHUAN_DATA_ROOT", None)
        env["LOCALAPPDATA"] = str(default_data_local_root)

    py = Path(sys.executable)
    command = [str(py), str(ROOT / "app" / "main.py")]
    cwd = ROOT
    if frozen_executable is not None:
        command = [str(frozen_executable.resolve(strict=True))]
        cwd = work_dir
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PATH"] = str(Path(env.get("SystemRoot", "C:/Windows")) / "System32")
    process, probe, main_win, hud = start_source(command, env, log_path, cwd=cwd)
    dual_launched = (main_win["hwnd"] > 0 and hud["hwnd"] > 0 and process.poll() is None)

    killed_forced = False
    try:
        interaction_data = asyncio.run((interactor or interact_with_real_app)(zip_out, trigger_export))
        probe.close(main_win["hwnd"])
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            killed_forced = True
            process.kill()
            process.wait(timeout=5)
        clean_exit = (not killed_forced) and (process.poll() is not None and process.poll() >= 0)
        return dual_launched, interaction_data, clean_exit
    finally:
        if process.poll() is None:
            killed_forced = True
            process.kill()
            process.wait(timeout=5)


def verify_exported_zip(zip_path: Path, unpacked_dir: Path) -> Dict[str, Any]:
    """Extracts the exported ZIP bundle and performs complete file and hash verification."""
    if not zip_path.is_file() or zip_path.stat().st_size == 0:
        return {"ok": False, "error": "Zip file does not exist or is empty"}

    if unpacked_dir.exists():
        shutil.rmtree(unpacked_dir)
    unpacked_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf_names = zf.namelist()
        zf.extractall(unpacked_dir)

    manifest_path = unpacked_dir / "manifest.json"
    records_path = unpacked_dir / "records.json"
    readme_path = unpacked_dir / "说明.txt"

    errors = []
    if not manifest_path.is_file():
        errors.append("MISSING_MANIFEST_JSON")
        return {"ok": False, "error": "Missing manifest.json in export bundle", "errors": errors}
    if not records_path.is_file():
        errors.append("MISSING_RECORDS_JSON")
        return {"ok": False, "error": "Missing records.json in export bundle", "errors": errors}
    if not readme_path.is_file():
        errors.append("MISSING_README_TXT")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records_data = json.loads(records_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"JSON parse error: {exc}", "errors": ["JSON_PARSE_ERROR"]}

    files_list = manifest.get("files", [])
    mismatches = []
    crops_verified = 0
    blobs_verified = 0

    for item in files_list:
        p = item.get("path") or item.get("packagePath")
        expected_sha = item.get("sha256")
        fpath = unpacked_dir / p
        if not fpath.is_file():
            mismatches.append({"path": p, "error": "FILE_MISSING"})
            continue
        actual_sha = _sha256_file(fpath)
        if actual_sha != expected_sha:
            mismatches.append({"path": p, "error": "SHA256_MISMATCH", "expected": expected_sha, "actual": actual_sha})
            continue

        if "crops/" in p:
            crops_verified += 1
        elif "blobs/" in p:
            blobs_verified += 1

    # Desensitization check: records.json should NOT contain developer machine absolute paths
    raw_records_text = records_path.read_text(encoding="utf-8")
    has_host_leak = ("D:/yihuanpaimai" in raw_records_text or "D:\\yihuanpaimai" in raw_records_text)

    # Check that records.json contains the 39 units
    export_rec = records_data.get("records", [{}])[0]
    exp_units = export_rec.get("settlement", {}).get("reviewUnits", [])
    exp_conf = sum(1 for u in exp_units if u.get("confirmationStatus") == "CONFIRMED")
    exp_cand = sum(1 for u in exp_units if u.get("confirmationStatus") == "CANDIDATE_ONLY")

    # Strict entry set equality gate:
    # ZIP actual entries must strictly equal manifest's files + manifest.json
    manifest_paths = {item.get("path") or item.get("packagePath") for item in files_list}
    expected_zf_names = manifest_paths | {"manifest.json"}
    actual_zf_names = set(zf_names)

    extra_files = list(actual_zf_names - expected_zf_names)
    missing_files = list(expected_zf_names - actual_zf_names)
    is_exact_set = (actual_zf_names == expected_zf_names)
    if extra_files:
        errors.append(f"UNMANIFESTED_EXTRA_FILES: {extra_files}")
    if missing_files:
        errors.append(f"MISSING_EXPECTED_FILES: {missing_files}")
    if mismatches:
        errors.append(f"HASH_OR_FILE_MISMATCHES: {len(mismatches)}")

    if "records.json" not in manifest_paths:
        errors.append("MANIFEST_MISSING_RECORDS_JSON")
    if "说明.txt" not in manifest_paths:
        errors.append("MANIFEST_MISSING_README_TXT")

    ok = (
        is_exact_set
        and len(mismatches) == 0
        and not has_host_leak
        and crops_verified == 39
        and blobs_verified == EXPECTED_BLOBS
        and len(exp_units) == 39
        and exp_conf == EXPECTED_CONFIRMED
        and exp_cand == EXPECTED_CANDIDATE
        and len(manifest_paths) == 42 + EXPECTED_BLOBS
        and len(zf_names) == 43 + EXPECTED_BLOBS
        and len(errors) == 0
    )

    return {
        "ok": ok,
        "isExactSet": is_exact_set,
        "actualTotalFiles": len(zf_names),
        "manifestFiles": len(files_list),
        "totalFiles": len(files_list),
        "extraFiles": extra_files,
        "missingFiles": missing_files,
        "mismatches": mismatches,
        "cropsVerified": crops_verified,
        "blobsVerified": blobs_verified,
        "hasHostLeak": has_host_leak,
        "recordsUnitCount": len(exp_units),
        "recordsConfirmedCount": exp_conf,
        "recordsCandidateCount": exp_cand,
        "errors": errors,
    }


def verify_zip_negative_modes(valid_zip_path: Path, work_dir: Path) -> Dict[str, Any]:
    """Tests the three strict ZIP negative modes:
    1. Extra unmanifested file -> must fail
    2. Missing blob image -> must fail
    3. Missing manifest.json -> must fail
    """
    neg_dir = work_dir / "zip_negative_tests"
    if neg_dir.exists():
        shutil.rmtree(neg_dir)
    neg_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # --- Mode 1: Extra unmanifested file ---
    neg1_zip = neg_dir / "neg1_extra_file.zip"
    shutil.copy2(valid_zip_path, neg1_zip)
    with zipfile.ZipFile(neg1_zip, "a") as zf:
        zf.writestr("unmanifested_extra_file.png", b"fake_extra_data")
    neg1_res = verify_exported_zip(neg1_zip, neg_dir / "unpacked_neg1")
    mode1_blocked = (not neg1_res["ok"]) and (len(neg1_res.get("extraFiles", [])) > 0)
    results["mode1_extra_file"] = {
        "blocked": mode1_blocked,
        "detail": f"ok={neg1_res['ok']}, extraFiles={neg1_res.get('extraFiles')}",
    }

    # --- Mode 2: Missing blob image ---
    neg2_zip = neg_dir / "neg2_missing_blob.zip"
    target_omit = None
    with zipfile.ZipFile(valid_zip_path, "r") as zf_in:
        all_names = zf_in.namelist()
        blob_names = [n for n in all_names if "blobs/" in n]
        target_omit = blob_names[0] if blob_names else None
        with zipfile.ZipFile(neg2_zip, "w") as zf_out:
            for item in zf_in.infolist():
                if item.filename != target_omit:
                    zf_out.writestr(item, zf_in.read(item.filename))
    neg2_res = verify_exported_zip(neg2_zip, neg_dir / "unpacked_neg2")
    mode2_blocked = (not neg2_res["ok"]) and (
        len(neg2_res.get("mismatches", [])) > 0 or len(neg2_res.get("missingFiles", [])) > 0
    )
    results["mode2_missing_blob"] = {
        "blocked": mode2_blocked,
        "detail": f"ok={neg2_res['ok']}, omitted='{target_omit}', mismatches={len(neg2_res.get('mismatches', []))}",
    }

    # --- Mode 3: Missing manifest.json ---
    neg3_zip = neg_dir / "neg3_missing_manifest.zip"
    with zipfile.ZipFile(valid_zip_path, "r") as zf_in:
        with zipfile.ZipFile(neg3_zip, "w") as zf_out:
            for item in zf_in.infolist():
                if item.filename != "manifest.json":
                    zf_out.writestr(item, zf_in.read(item.filename))
    neg3_res = verify_exported_zip(neg3_zip, neg_dir / "unpacked_neg3")
    mode3_blocked = (not neg3_res["ok"]) and ("Missing manifest.json" in neg3_res.get("error", ""))
    results["mode3_missing_manifest"] = {
        "blocked": mode3_blocked,
        "detail": f"ok={neg3_res['ok']}, error='{neg3_res.get('error')}'",
    }

    # --- Mode 4: Tampered confirmed item name in records.json (keeping counts) ---
    neg4_zip = neg_dir / "neg4_tampered_records_name.zip"
    with zipfile.ZipFile(valid_zip_path, "r") as zf_in:
        records_raw = json.loads(zf_in.read("records.json").decode("utf-8"))
        rec0 = records_raw["records"][0]
        units = rec0["settlement"]["reviewUnits"]
        for u in units:
            if u.get("confirmationStatus") == "CONFIRMED":
                u["canonicalName"] = "虚构藏品名_伪造"
                break
        tampered_records_bytes = json.dumps(records_raw, ensure_ascii=False, indent=2).encode("utf-8")
        with zipfile.ZipFile(neg4_zip, "w") as zf_out:
            for item in zf_in.infolist():
                if item.filename == "records.json":
                    zf_out.writestr("records.json", tampered_records_bytes)
                else:
                    zf_out.writestr(item, zf_in.read(item.filename))
    neg4_res = verify_exported_zip(neg4_zip, neg_dir / "unpacked_neg4")
    mode4_blocked = (not neg4_res["ok"]) and any(
        m.get("path") == "records.json" and m.get("error") == "SHA256_MISMATCH"
        for m in neg4_res.get("mismatches", [])
    )
    results["mode4_tampered_records_name"] = {
        "blocked": mode4_blocked,
        "detail": f"ok={neg4_res['ok']}, mismatches={neg4_res.get('mismatches')}",
    }

    all_blocked = bool(mode1_blocked and mode2_blocked and mode3_blocked and mode4_blocked)
    results["all_negative_modes_blocked"] = all_blocked
    return results


def verify_auto_source_projection_three_way_consistency(
    ir_artifact: Mapping[str, Any],
    review_units: Sequence[Mapping[str, Any]],
    dom_data: Mapping[str, Any],
    catalog_authority: Any,
) -> Dict[str, Any]:
    """Verifies strict 3-way consistency between reviewUnits, warehouseIdentityReview, and DOM:
    1. reviewerType must be AUTO, confirmedByHuman must be False everywhere.
    2. provenanceType must be AUTO_CONFIRMED_EVIDENCE on all resolved items.
    3. Authoritative catalog names must match official catalog and never equal catalogId.
    4. DOM must reflect the expected confirmed and candidate-only counts.
    """
    errors = []

    # 1. ir_artifact check
    if ir_artifact.get("reviewerType") != "AUTO":
        errors.append(f"ir_artifact reviewerType is not AUTO: {ir_artifact.get('reviewerType')}")
    resolved = ir_artifact.get("resolvedItems") or []
    unresolved = ir_artifact.get("unresolvedUnits") or []
    decisions = ir_artifact.get("decisions") or []

    if len(resolved) != EXPECTED_CONFIRMED:
        errors.append(f"resolvedItems count is {len(resolved)}, expected {EXPECTED_CONFIRMED}")
    if len(unresolved) != EXPECTED_CANDIDATE:
        errors.append(f"unresolvedUnits count is {len(unresolved)}, expected {EXPECTED_CANDIDATE}")

    for r in resolved:
        uid = r.get("reviewUnitId") or r.get("trackId")
        if r.get("confirmedByHuman") is not False:
            errors.append(f"resolved item {uid} has confirmedByHuman={r.get('confirmedByHuman')}, expected False")
        if r.get("provenanceType") != "AUTO_CONFIRMED_EVIDENCE":
            errors.append(f"resolved item {uid} has provenanceType={r.get('provenanceType')}, expected AUTO_CONFIRMED_EVIDENCE")
        cat_id = str(r.get("catalogId") or "")
        name = str(r.get("name") or "")
        if not name or name == cat_id:
            errors.append(f"resolved item {uid} name '{name}' is empty or equals catalogId '{cat_id}'")
        auth_rec = catalog_authority.get(cat_id)
        if not auth_rec or auth_rec.get("name") != name:
            errors.append(f"resolved item {uid} name '{name}' does not match authoritative name '{auth_rec.get('name') if auth_rec else None}'")

    for u in unresolved:
        uid = u.get("reviewUnitId") or u.get("trackId")
        if u.get("confirmedByHuman") is not False:
            errors.append(f"unresolved item {uid} has confirmedByHuman={u.get('confirmedByHuman')}, expected False")

    for d in decisions:
        if d.get("reviewerType") != "AUTO":
            errors.append(f"decision {d.get('decisionId')} reviewerType is {d.get('reviewerType')}, expected AUTO")
        if d.get("confirmedByHuman") is not False:
            errors.append(f"decision {d.get('decisionId')} confirmedByHuman is {d.get('confirmedByHuman')}, expected False")

    # 2. review_units check
    conf_units = [u for u in review_units if u.get("confirmationStatus") == "CONFIRMED"]
    cand_units = [u for u in review_units if u.get("confirmationStatus") == "CANDIDATE_ONLY"]
    if len(conf_units) != EXPECTED_CONFIRMED:
        errors.append(f"review_units CONFIRMED count is {len(conf_units)}, expected {EXPECTED_CONFIRMED}")
    if len(cand_units) != EXPECTED_CANDIDATE:
        errors.append(f"review_units CANDIDATE count is {len(cand_units)}, expected {EXPECTED_CANDIDATE}")

    for u in conf_units:
        if u.get("confirmedByHuman") is not False:
            errors.append(f"unit {u.get('reviewUnitId')} confirmedByHuman is not False")
        if not u.get("selectedCatalogId"):
            errors.append(f"confirmed unit {u.get('reviewUnitId')} missing selectedCatalogId")
        cname = str(u.get("canonicalName") or "")
        cid = str(u.get("selectedCatalogId") or "")
        if not cname or cname == cid:
            errors.append(f"confirmed unit {u.get('reviewUnitId')} canonicalName is invalid: '{cname}'")

    for u in cand_units:
        if u.get("confirmedByHuman") is not False:
            errors.append(f"candidate unit {u.get('reviewUnitId')} confirmedByHuman is not False")
        if u.get("selectedCatalogId") is not None:
            errors.append(f"candidate unit {u.get('reviewUnitId')} should have selectedCatalogId=None")

    # 3. DOM check
    if dom_data.get("confirmedCount") != EXPECTED_CONFIRMED:
        errors.append(f"DOM confirmedCount is {dom_data.get('confirmedCount')}, expected {EXPECTED_CONFIRMED}")
    if dom_data.get("candidateCount") != EXPECTED_CANDIDATE:
        errors.append(f"DOM candidateCount is {dom_data.get('candidateCount')}, expected {EXPECTED_CANDIDATE}")
    if dom_data.get("totalUnits") != 39:
        errors.append(f"DOM totalUnits is {dom_data.get('totalUnits')}, expected 39")

    # Check DOM card badges
    card_summaries = dom_data.get("domCardSummaries") or []
    auto_badges = [c for c in card_summaries if str(c.get("badge", "")).startswith("自动识别：")]
    if len(auto_badges) != EXPECTED_CONFIRMED:
        errors.append(f"DOM cards with '自动识别：' badge is {len(auto_badges)}, expected {EXPECTED_CONFIRMED}")

    # Check for zero catalogId leak in DOM item name positions
    for c in card_summaries:
        badge = str(c.get("badge") or "")
        if "image" in badge or "visual-" in badge:
            errors.append(f"DOM card badge leaked catalogId: '{badge}'")
        for cn in c.get("candNames") or []:
            if cn.startswith("image") or cn.startswith("visual-"):
                errors.append(f"DOM card candidate name leaked catalogId: '{cn}'")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "resolvedCount": len(resolved),
        "unresolvedCount": len(unresolved),
        "autoBadgesCount": len(auto_badges),
        "reviewerType": ir_artifact.get("reviewerType"),
    }


def run_single_suite(run_idx: int, run_dir: Path) -> Dict[str, Any]:
    print(f"\n==================================================================", flush=True)
    print(f"RUN {run_idx}: Preparing isolated environment in {run_dir}...", flush=True)
    print(f"==================================================================", flush=True)
    data_root = run_dir / "data"
    prepare_isolated_environment(data_root)
    print("Isolated environment prepared successfully.", flush=True)

    # Launch 1: Live app launch, history review, 39 items check, real DOM export, clean exit
    print(f"\n[Run {run_idx} - Step 2] Launching real application process (Launch 1)...", flush=True)
    log_launch_1 = run_dir / "app_launch_1.log"
    zip_out = run_dir / "export_bundle_launch1.zip"
    dual_1, inter_1, exit_1 = run_one_launch(
        f"r{run_idx}_launch_1",
        data_root,
        log_launch_1,
        work_dir=run_dir,
        zip_out=zip_out,
        trigger_export=True,
    )
    print(f"Launch 1 finished: dualLaunched={dual_1}, cleanExit={exit_1}", flush=True)

    raw_dom_1 = inter_1.get("domDetail")
    dom_1 = json.loads(raw_dom_1) if isinstance(raw_dom_1, str) else (raw_dom_1 or {})
    print(f"Launch 1 DOM detail: cardVisible={dom_1.get('cardVisible')}, units={dom_1.get('totalUnits')}, conf={dom_1.get('confirmedCount')}, cand={dom_1.get('candidateCount')}, domCards={dom_1.get('domCardCount')}, thumbs={dom_1.get('domCardsWithThumbs')}, singleRenderOk={dom_1.get('singleRenderOk')}", flush=True)

    # Verify exported ZIP
    print(f"\n[Run {run_idx} - Step 3] Verifying exported ZIP bundle from real DOM button click...", flush=True)
    unpacked_dir_1 = run_dir / "unpacked_bundle_1"
    zip_verify = verify_exported_zip(zip_out, unpacked_dir_1)
    print(f"ZIP Verification: ok={zip_verify['ok']}, totalFiles={zip_verify.get('actualTotalFiles')}, crops={zip_verify.get('cropsVerified')}, blobs={zip_verify.get('blobsVerified')}, mismatches={len(zip_verify.get('mismatches', []))}", flush=True)

    print(f"\n[Run {run_idx} - Step 3b] Verifying strict ZIP entry set gate and 4 negative failure modes...", flush=True)
    zip_neg = verify_zip_negative_modes(zip_out, run_dir)
    print(f"ZIP Negative Modes: allBlocked={zip_neg['all_negative_modes_blocked']}, mode1={zip_neg['mode1_extra_file']['blocked']}, mode2={zip_neg['mode2_missing_blob']['blocked']}, mode3={zip_neg['mode3_missing_manifest']['blocked']}, mode4={zip_neg['mode4_tampered_records_name']['blocked']}", flush=True)

    print(f"\n[Run {run_idx} - Step 3c] Verifying 3-way consistency between reviewUnits, warehouseIdentityReview, and DOM...", flush=True)
    ir_saved = json.loads((data_root / "ir_artifact.json").read_text(encoding="utf-8"))
    units_saved = json.loads((data_root / "evaluated_units.json").read_text(encoding="utf-8"))
    from warehouse_identity_review import CatalogAuthority
    ca = CatalogAuthority()
    three_way = verify_auto_source_projection_three_way_consistency(ir_saved, units_saved, dom_1, ca)
    print(f"3-Way Consistency: ok={three_way['ok']}, reviewerType={three_way.get('reviewerType')}, resolved={three_way.get('resolvedCount')}, unresolved={three_way.get('unresolvedCount')}, autoBadges={three_way.get('autoBadgesCount')}/{EXPECTED_CONFIRMED}", flush=True)

    # Launch 2 (Process Restart): Launch real app second time, re-query DOM, assert identical
    print(f"\n[Run {run_idx} - Step 4] Restarting real application process (Launch 2)...", flush=True)
    time.sleep(1.5)
    log_launch_2 = run_dir / "app_launch_2.log"
    dual_2, inter_2, exit_2 = run_one_launch(
        f"r{run_idx}_launch_2",
        data_root,
        log_launch_2,
        work_dir=run_dir,
        zip_out=None,
        trigger_export=False,
    )
    print(f"Launch 2 finished: dualLaunched={dual_2}, cleanExit={exit_2}", flush=True)

    raw_dom_2 = inter_2.get("domDetail")
    dom_2 = json.loads(raw_dom_2) if isinstance(raw_dom_2, str) else (raw_dom_2 or {})
    print(f"Launch 2 DOM detail: cardVisible={dom_2.get('cardVisible')}, units={dom_2.get('totalUnits')}, conf={dom_2.get('confirmedCount')}, cand={dom_2.get('candidateCount')}, domCards={dom_2.get('domCardCount')}, thumbs={dom_2.get('domCardsWithThumbs')}, singleRenderOk={dom_2.get('singleRenderOk')}", flush=True)

    # Compare Launch 1 vs Launch 2
    details_identical = (
        dom_1.get("matchId") == dom_2.get("matchId")
        and dom_1.get("lifecycle") == dom_2.get("lifecycle")
        and dom_1.get("clearingPrice") == dom_2.get("clearingPrice")
        and dom_1.get("actualTotal") == dom_2.get("actualTotal")
        and dom_1.get("warehouseText") == dom_2.get("warehouseText")
        and dom_1.get("wirSummaryVisible") is True
        and dom_2.get("wirSummaryVisible") is True
        and dom_1.get("wirCaption") == "已写入本局记录"
        and dom_2.get("wirCaption") == "已写入本局记录"
        and dom_1.get("wirFacts") == dom_2.get("wirFacts")
        and dom_1.get("totalUnits") == 39
        and dom_2.get("totalUnits") == 39
        and dom_1.get("confirmedCount") == EXPECTED_CONFIRMED
        and dom_2.get("confirmedCount") == EXPECTED_CONFIRMED
        and dom_1.get("candidateCount") == EXPECTED_CANDIDATE
        and dom_2.get("candidateCount") == EXPECTED_CANDIDATE
        and dom_1.get("domCardCount") == 39
        and dom_2.get("domCardCount") == 39
        and dom_1.get("units") == dom_2.get("units")
        and dom_1.get("singleRenderOk") is True
        and dom_2.get("singleRenderOk") is True
        and not dom_1.get("doubleRenderDetected")
        and not dom_2.get("doubleRenderDetected")
    )
    print(f"Launch 1 vs Launch 2 consistency check: {details_identical}", flush=True)

    # Assertions
    checks = [
        {
            "id": "REAL_APP_DUAL_WINDOW_LAUNCH_1",
            "name": "真实应用主窗口与HUD双窗口启动 (Launch 1)",
            "pass": bool(dual_1),
            "detail": f"dualLaunched={dual_1}",
        },
        {
            "id": "DOM_39_UNITS_LOADED_LAUNCH_1",
            "name": f"真实 DOM 历史加载 39 件藏品 ({EXPECTED_CONFIRMED} 确证 / {EXPECTED_CANDIDATE} 候选与单次确定性渲染)",
            "pass": bool(
                dom_1.get("cardVisible")
                and dom_1.get("totalUnits") == 39
                and dom_1.get("confirmedCount") == EXPECTED_CONFIRMED
                and dom_1.get("candidateCount") == EXPECTED_CANDIDATE
                and dom_1.get("domCardCount") == 39
                and dom_1.get("singleRenderOk")
                and not dom_1.get("doubleRenderDetected")
            ),
            "detail": f"total={dom_1.get('totalUnits')}, confirmed={dom_1.get('confirmedCount')}, candidate={dom_1.get('candidateCount')}, domCards={dom_1.get('domCardCount')}, singleRenderOk={dom_1.get('singleRenderOk')}, renderCounts={dom_1.get('renderCounts')}",
        },
        {
            "id": "DOM_WIR_SUMMARY_READABLE_LAUNCH_1",
            "name": "真实 DOM 仓库身份审阅可读摘要断言 (wir-saved-summary)",
            "pass": bool(
                dom_1.get("wirSummaryVisible")
                and dom_1.get("wirCaption") == "已写入本局记录"
                and f"已确认 {EXPECTED_CONFIRMED}" in str(dom_1.get("wirFacts"))
                and f"未决 {EXPECTED_CANDIDATE}" in str(dom_1.get("wirFacts"))
            ),
            "detail": f"visible={dom_1.get('wirSummaryVisible')}, caption='{dom_1.get('wirCaption')}', facts='{dom_1.get('wirFacts')}'",
        },
        {
            "id": "AUTO_SOURCE_PROJECTION_THREE_WAY_CONSISTENCY",
            "name": "自动/人工来源投影三方严格一致性校验 (reviewUnits / warehouseIdentityReview / DOM)",
            "pass": bool(three_way.get("ok")),
            "detail": f"reviewerType={three_way.get('reviewerType')}, resolved={three_way.get('resolvedCount')}/{EXPECTED_CONFIRMED}, unresolved={three_way.get('unresolvedCount')}/{EXPECTED_CANDIDATE}, autoBadges={three_way.get('autoBadgesCount')}/{EXPECTED_CONFIRMED}, errors={len(three_way.get('errors', []))}",
        },
        {
            "id": "DOM_WAREHOUSE_PROJECTION_AND_RAW_CROPS",
            "name": "仓库概要统计显示与 39 张原始裁图渲染有效",
            "pass": bool("39" in str(dom_1.get("warehouseText")) and dom_1.get("domCardsWithThumbs") == 39 and all(u.get("cropPath") and u.get("cropSha256") for u in dom_1.get("units", []))),
            "detail": f"warehouseText='{dom_1.get('warehouseText')}', domThumbs={dom_1.get('domCardsWithThumbs')}/39",
        },
        {
            "id": "REAL_DOM_EXPORT_BUTTON_TRIGGER",
            "name": "通过真实 DOM 导出按钮触发 export_history_records",
            "pass": bool(zip_out.is_file() and zip_out.stat().st_size > 0),
            "detail": f"zipSize={zip_out.stat().st_size if zip_out.is_file() else 0}",
        },
        {
            "id": "EXPORT_BUNDLE_ZIP_AND_HASH_INTEGRITY",
            "name": "导出 ZIP 包自包含性、实际枚举全部文件与 39 张裁图、原图 SHA-256 100% 核验与脱敏",
            "pass": bool(zip_verify.get("ok")),
            "detail": f"actualTotalFiles={zip_verify.get('actualTotalFiles')}, manifestFiles={zip_verify.get('totalFiles')}, crops={zip_verify.get('cropsVerified')}/39, blobs={zip_verify.get('blobsVerified')}, mismatches={len(zip_verify.get('mismatches', []))}, noLeak={not zip_verify.get('hasHostLeak')}",
        },
        {
            "id": "EXPORT_ZIP_STRICT_GATE_AND_FOUR_NEGATIVE_MODES",
            "name": "导出 ZIP 严格等于门禁 (原图、裁图与 manifest 完整集合 包含 records.json 与 说明.txt) 与 4 类负例测试全阻断",
            "pass": bool(zip_verify.get("ok") and zip_neg.get("all_negative_modes_blocked")),
            "detail": f"exactSet={zip_verify.get('isExactSet')}, totalFiles={zip_verify.get('actualTotalFiles')}/{43 + EXPECTED_BLOBS}, manifestFiles={zip_verify.get('manifestFiles')}/{42 + EXPECTED_BLOBS}, negBlocked={zip_neg.get('all_negative_modes_blocked')}, mode1Extra={zip_neg.get('mode1_extra_file', {}).get('blocked')}, mode2MissingBlob={zip_neg.get('mode2_missing_blob', {}).get('blocked')}, mode3MissingManifest={zip_neg.get('mode3_missing_manifest', {}).get('blocked')}, mode4TamperedRecordsName={zip_neg.get('mode4_tampered_records_name', {}).get('blocked')}",
        },
        {
            "id": "REAL_APP_CLEAN_SHUTDOWN_1",
            "name": "第一实例真实 WM_CLOSE 安全退出与干净关闭",
            "pass": bool(exit_1),
            "detail": f"cleanExit={exit_1}",
        },
        {
            "id": "REAL_APP_PROCESS_RESTART_LAUNCH_2",
            "name": "真实应用进程完全重启 (Launch 2)",
            "pass": bool(dual_2),
            "detail": f"dualLaunched={dual_2}",
        },
        {
            "id": "RESTART_DOM_39_UNITS_IDENTICAL_RECHECK",
            "name": "重启后 DOM 历史与审阅摘要逐项比对与首实例 100% 吻合",
            "pass": bool(details_identical),
            "detail": f"detailsIdentical={details_identical}, units={dom_2.get('totalUnits')}, conf={dom_2.get('confirmedCount')}, cand={dom_2.get('candidateCount')}, domCards={dom_2.get('domCardCount')}, wirSummaryVisible={dom_2.get('wirSummaryVisible')}",
        },
        {
            "id": "REAL_APP_CLEAN_SHUTDOWN_2",
            "name": "第二实例真实 WM_CLOSE 安全退出与干净关闭",
            "pass": bool(exit_2),
            "detail": f"cleanExit={exit_2}",
        },
    ]

    all_passed = all(c["pass"] for c in checks)
    status_str = "PASS" if all_passed else "FAIL"

    summary = {
        "status": status_str,
        "runIndex": run_idx,
        "targetMatchId": TARGET_MATCH_ID,
        "totalChecks": len(checks),
        "passedChecks": sum(1 for c in checks if c["pass"]),
        "failedChecks": sum(1 for c in checks if not c["pass"]),
        "checks": checks,
        "launch1": {
            "dualLaunched": dual_1,
            "cleanExit": exit_1,
            "domDetail": dom_1,
            "zipVerify": zip_verify,
            "zipNegativeModes": zip_neg,
            "threeWayConsistency": three_way,
        },
        "launch2": {
            "dualLaunched": dual_2,
            "cleanExit": exit_2,
            "domDetail": dom_2,
        },
    }

    report_file = OUT_DIR / f"isolated_app_real_test_report_run{run_idx}.json"
    report_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nRUN {run_idx} RESULT: {status_str} ({summary['passedChecks']}/{summary['totalChecks']} passed)", flush=True)
    for c in checks:
        st = "PASS" if c["pass"] else "FAIL"
        print(f"  [{st}] {c['id']}: {c['name']} -> {c['detail']}", flush=True)
    print(f"Run report written to: {report_file}", flush=True)

    return summary


def main() -> int:
    print("==================================================================", flush=True)
    print("P3 ISOLATED REAL APPLICATION HISTORY REVIEW, RESTART & EXPORT SUITE", flush=True)
    print("==================================================================", flush=True)

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_run_summaries = []
    for run_idx in range(1, 4):
        print(f"\n******************************************************************", flush=True)
        print(f"STARTING VERIFICATION RUN {run_idx} / 3", flush=True)
        print(f"******************************************************************", flush=True)
        run_dir = OUT_DIR / f"run_{run_idx}"
        run_dir.mkdir(parents=True, exist_ok=True)
        summary = run_single_suite(run_idx, run_dir)
        all_run_summaries.append(summary)
        if summary.get("status") != "PASS" or summary.get("passedChecks") != 12:
            print(f"RUN {run_idx} FAILED! Aborting consecutive runs.", flush=True)
            break
        print(f"RUN {run_idx} COMPLETED WITH 12/12 CHECKS PASSING.", flush=True)

    all_passed = (len(all_run_summaries) == 3 and all(s.get("status") == "PASS" and s.get("passedChecks") == 12 for s in all_run_summaries))
    status_str = "PASS" if all_passed else "FAIL"

    latest_summary = all_run_summaries[-1] if all_run_summaries else {}
    overall_summary = {
        "status": status_str,
        "targetMatchId": TARGET_MATCH_ID,
        "totalRuns": 3,
        "completedRuns": len(all_run_summaries),
        "passedRuns": sum(1 for s in all_run_summaries if s.get("status") == "PASS" and s.get("passedChecks") == 12),
        "allRunsPassed": all_passed,
        "runs": all_run_summaries,
        "latestRun": latest_summary,
        # Preserve top-level fields for compatibility
        "totalChecks": latest_summary.get("totalChecks", 12),
        "passedChecks": latest_summary.get("passedChecks", 0),
        "failedChecks": latest_summary.get("failedChecks", 12),
        "checks": latest_summary.get("checks", []),
        "launch1": latest_summary.get("launch1", {}),
        "launch2": latest_summary.get("launch2", {}),
    }

    report_file = OUT_DIR / "isolated_app_real_test_report.json"
    report_file.write_text(json.dumps(overall_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n==================================================================", flush=True)
    print(f"3-RUN CONSECUTIVE SUITE RESULT: {status_str} ({overall_summary['passedRuns']}/3 PASSED)", flush=True)
    for idx in range(1, len(all_run_summaries) + 1):
        print(f"  Run {idx}: {OUT_DIR / f'isolated_app_real_test_report_run{idx}.json'}", flush=True)
    print(f"  Summary / Latest: {report_file}", flush=True)
    print("==================================================================", flush=True)

    return 0 if all_passed else 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--expected-confirmed", type=int, required=True)
    args = parser.parse_args()
    SOURCE_PACKET = args.packet.resolve()
    SOURCE_EVIDENCE = args.evidence_root.resolve()
    OUT_DIR = args.out_dir.resolve()
    if not SOURCE_PACKET.is_file() or not SOURCE_EVIDENCE.is_dir():
        parser.error("Packet and original evidence must exist")
    if OUT_DIR.exists():
        parser.error("Output directory already exists; preserve prior acceptance evidence")
    configure_evidence(SOURCE_PACKET, SOURCE_EVIDENCE, args.expected_confirmed)
    raise SystemExit(main())
