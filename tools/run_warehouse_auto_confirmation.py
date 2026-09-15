# -*- coding: utf-8 -*-
"""Run evidence-backed automatic confirmation on production warehouse review packet and benchmark video.

Directly tests the production auto-confirmation chain, verifies CanonicalHistoryStore persistence,
idempotency, restart read-back, and raw crop export.
Generates an audit report strictly reporting confirmed correct count, error count, and unresolved reasons.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT / "core"), str(PROJECT_ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from warehouse_auto_confirmation import (
    CONFIRMATION_STATUS_CONFIRMED,
    evaluate_auto_confirmation,
    export_warehouse_evidence_crops,
)

DEFAULT_PACKET_PATH = (
    PROJECT_ROOT
    / "build"
    / "diagnosis_20260911"
    / "p3-warehouse"
    / "video_audit_retest_v5"
    / "audit_review_packet.json"
)
DEFAULT_GT_PATH = (
    PROJECT_ROOT / "assets" / "items" / "video_ground_truth_reference_144037.json"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "build"
    / "diagnosis_20260911"
    / "p3-warehouse"
    / "auto_confirmation_run_v5"
)


def run_confirmation_pipeline(
    packet_path: Path,
    gt_path: Path,
    output_dir: Path,
) -> Dict[str, Any]:
    packet_path = Path(packet_path).resolve()
    gt_path = Path(gt_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not packet_path.is_file():
        raise FileNotFoundError(f"Review packet not found: {packet_path}")

    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    raw_units = packet.get("reviewUnits", [])
    segments = packet.get("segments", [])
    record_id = str(packet.get("recordStableKey") or "2026-09-08_14-40-37").strip()

    # Step 1: Execute Evidence-Backed Auto-Confirmation
    confirmed_units = evaluate_auto_confirmation(
        review_units=raw_units,
        segments=segments,
        existing_record=None,
    )

    # Step 2: Set up test CanonicalHistoryStore and verify persistence, idempotency, restart
    test_db_dir = output_dir / "history"
    test_db_dir.mkdir(parents=True, exist_ok=True)
    test_db_path = test_db_dir / "test_canonical_history.json"
    if test_db_path.exists():
        test_db_path.unlink()

    store = CanonicalHistoryStore(test_db_path)
    initial_draft = build_canonical_match_record_v7(
        match_id=record_id,
        played_at="2026-09-08T14:40:37Z",
        lifecycle_status="DRAFT",
        source="live_capture",
    )
    store.persist_record_transactional(initial_draft, is_finalized=False)

    # First write
    written1 = store.persist_warehouse_evidence(
        record_id,
        review_units=confirmed_units,
    )
    if written1 is None:
        raise RuntimeError("Failed to persist warehouse evidence to history store")

    # Idempotent second write
    written2 = store.persist_warehouse_evidence(
        record_id,
        review_units=confirmed_units,
    )
    if written2 is None:
        raise RuntimeError("Failed idempotent second write to history store")

    # Restart verification: Re-instantiate store from disk
    restarted_store = CanonicalHistoryStore(test_db_path)
    loaded_record = restarted_store.lookup(record_id)
    if loaded_record is None:
        raise RuntimeError("Failed to read back record after simulated restart")

    persisted_units = loaded_record.get("settlement", {}).get("reviewUnits", [])
    if len(persisted_units) != len(confirmed_units):
        raise RuntimeError(
            f"Persisted unit count mismatch: expected {len(confirmed_units)}, got {len(persisted_units)}"
        )

    # Step 2b: MainWindowBridge Simulated Restart & Export Dispatch
    from main_window import MainWindowBridge

    class _DummyOverlayController:
        visible = True

    bridge = MainWindowBridge(
        overlay_controller=_DummyOverlayController(),
        history_path_provider=lambda: test_db_path,
    )
    bridge_export_path = output_dir / f"exported_history_bridge_{record_id}.json"
    bridge_resp = bridge.dispatch({
        "action": "export_history_records",
        "outputPath": str(bridge_export_path),
        "recordIds": [record_id],
    })
    bridge_export_ok = bool(bridge_resp.get("exportResult", {}).get("ok")) and bridge_export_path.is_file()

    # Step 3: Raw crop export & Disk verification
    runtime_root = PROJECT_ROOT / "build" / "diagnosis_20260911" / "p3-warehouse" / "store_dense"
    ev_store = SettlementEvidenceStoreV2(runtime_root) if runtime_root.is_dir() else None
    crops_export = export_warehouse_evidence_crops(
        record_id=record_id,
        review_units=persisted_units,
        store=ev_store,
        output_dir=output_dir,
        segments=segments,
    )

    import hashlib
    crops_disk_verified = 0
    for s in crops_export.get("samples", []):
        cp = s.get("cropPath")
        expected_sha = s.get("cropSha256")
        if cp:
            full_cp = output_dir / cp
            if full_cp.is_file() and full_cp.stat().st_size > 0:
                actual_sha = hashlib.sha256(full_cp.read_bytes()).hexdigest()
                if actual_sha == expected_sha:
                    crops_disk_verified += 1

    # Step 4: Independent evaluation against ground truth (Audit Only)
    gt_data = json.loads(gt_path.read_text(encoding="utf-8")) if gt_path.is_file() else {}
    gt_items = gt_data.get("items", [])
    gt_by_anchor = {}
    for it in gt_items:
        bb = it.get("gridBoundingBox", {})
        key = (bb.get("row"), bb.get("col"), bb.get("width"), bb.get("height"))
        gt_by_anchor[key] = it

    confirmed_items = []
    confirmed_correct = 0
    confirmed_error = 0
    unresolved_items = []

    for u in persisted_units:
        uid = u.get("reviewUnitId")
        wa = u.get("worldAnchor", {})
        fp = u.get("footprint", {})
        key = (wa.get("row"), wa.get("col"), fp.get("widthCells"), fp.get("heightCells"))
        gt_item = gt_by_anchor.get(key)
        gt_cid = gt_item.get("catalogId") if gt_item else None
        gt_name = gt_item.get("canonicalName") if gt_item else None

        conf_status = u.get("confirmationStatus")
        sel_cid = u.get("selectedCatalogId")
        sel_name = u.get("canonicalName")

        if conf_status == CONFIRMATION_STATUS_CONFIRMED:
            is_match = (sel_cid == gt_cid)
            if is_match:
                confirmed_correct += 1
            else:
                confirmed_error += 1
            confirmed_items.append({
                "reviewUnitId": uid,
                "worldAnchor": wa,
                "footprint": fp,
                "selectedCatalogId": sel_cid,
                "canonicalName": sel_name,
                "groundTruthCatalogId": gt_cid,
                "groundTruthName": gt_name,
                "isCorrect": is_match,
                "confirmationReasons": u.get("confirmationReasons"),
            })
        else:
            unresolved_items.append({
                "reviewUnitId": uid,
                "worldAnchor": wa,
                "footprint": fp,
                "candidates": u.get("candidates"),
                "groundTruthCatalogId": gt_cid,
                "groundTruthName": gt_name,
                "unconfirmedReasons": u.get("unconfirmedReasons"),
            })

    # Summary statistics
    total_units = len(persisted_units)
    auto_confirmed_count = len(confirmed_items)
    unresolved_count = len(unresolved_items)

    from collections import Counter
    reason_breakdown = Counter()
    for item in unresolved_items:
        reasons_key = tuple(item.get("unconfirmedReasons") or ["UNKNOWN"])
        reason_breakdown[reasons_key] += 1

    report = {
        "metadata": {
            "title": "仓库证据驱动自动确证与同局历史保存审计报告",
            "recordId": record_id,
            "inputPacket": str(packet_path),
            "groundTruthPath": str(gt_path),
            "outputDir": str(output_dir),
            "statistics": {
                "totalUnits": total_units,
                "autoConfirmedCount": auto_confirmed_count,
                "confirmedCorrectCount": confirmed_correct,
                "confirmedErrorCount": confirmed_error,
                "unresolvedCount": unresolved_count,
            },
            "unresolvedReasonBreakdown": {
                str(k): v for k, v in reason_breakdown.items()
            },
            "persistenceVerification": {
                "firstWriteOk": True,
                "idempotentSecondWriteOk": True,
                "restartReadBackOk": True,
                "mainWindowBridgeExportOk": bridge_export_ok,
                "cropsExportSampleCount": crops_export.get("sampleCount", 0),
                "cropsDiskVerifiedCount": crops_disk_verified,
            },
            "executionAudit": {
                "HEADLESS_BRIDGE_DISPATCH_AND_RESTART": "EXECUTED",
                "PER_ITEM_HISTORY_RECONSTRUCTION": "EXECUTED",
                "ALL_CROPS_DISK_HASH_VERIFIED": "EXECUTED" if crops_disk_verified == crops_export.get("sampleCount", 0) else "MISMATCH",
                "REAL_GUI_INTERACTIVE_WINDOW_DISPLAY": "NOT_EXECUTED",
            },
        },
        "confirmedItems": confirmed_items,
        "unresolvedItems": unresolved_items,
    }

    report_path = output_dir / f"video_auto_confirmation_report_{record_id}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


def main():
    parser = argparse.ArgumentParser(description="Run warehouse auto-confirmation and history persistence audit.")
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET_PATH, help="Path to audit review packet JSON.")
    parser.add_argument("--gt", type=Path, default=DEFAULT_GT_PATH, help="Path to independent ground truth JSON.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory for reports and crops.")
    args = parser.parse_args()

    report = run_confirmation_pipeline(args.packet, args.gt, args.out)
    stats = report["metadata"]["statistics"]
    print("=================================================================")
    print("  仓库证据驱动自动确证与同局历史保存流水线测试报告")
    print("=================================================================")
    print(f"  总物品单元数 (Total Units):              {stats['totalUnits']}")
    print(f"  自动确证总数 (Auto-Confirmed Count):      {stats['autoConfirmedCount']}")
    print(f"  自动确证正确数 (Confirmed Correct):        {stats['confirmedCorrectCount']}")
    print(f"  自动确证错误数 (Confirmed Error):          {stats['confirmedErrorCount']}")
    print(f"  未决保留候选数 (Unresolved Count):        {stats['unresolvedCount']}")
    print("-----------------------------------------------------------------")
    print("  未决原因统计分类 (Unresolved Reason Breakdown):")
    for reasons, count in report["metadata"]["unresolvedReasonBreakdown"].items():
        print(f"    - {count} 件: {reasons}")
    print("-----------------------------------------------------------------")
    p_ver = report["metadata"]["persistenceVerification"]
    print(f"  历史持久化测试: 初始写入={p_ver['firstWriteOk']}, 幂等写入={p_ver['idempotentSecondWriteOk']}, 重启读回={p_ver['restartReadBackOk']}")
    print(f"  原图裁片导出样本数: {p_ver['cropsExportSampleCount']}")
    print("=================================================================")


if __name__ == "__main__":
    main()
