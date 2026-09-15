#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Settlement Truth Review v1 Offline Management CLI.

Provides an auditable, offline command-line workflow for human reviewers to:
- List pending Tier 1 settlement records requiring verification.
- Inspect details and view original evidence PNG images.
- Submit immutable terminal review events (confirm, correct, reject).
- Store review artifacts in the content-addressed sidecar Review Store.

Usage:
  python tools/review_settlement_truth.py list [--database <path>] [--all]
  python tools/review_settlement_truth.py view <match_id> [--database <path>]
  python tools/review_settlement_truth.py confirm <match_id> [--reviewer-id <id>] [--database <path>]
  python tools/review_settlement_truth.py correct <match_id> <actual_total> [--reviewer-id <id>] [--database <path>]
  python tools/review_settlement_truth.py reject <match_id> [--reviewer-id <id>] [--database <path>]
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

_TOOLS_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _TOOLS_DIR.parent
_CORE_DIR = _ROOT_DIR / "core"
_APP_DIR = _ROOT_DIR / "app"
for _p in (str(_CORE_DIR), str(_APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from evidence_storage import verify_evidence_file
from runtime_revision import get_code_revision
from settlement_truth_holder import validate_settlement_truth_evidence
from settlement_truth_reviewer import (
    ReviewConflictError,
    ReviewError,
    ReviewStoreManager,
    build_settlement_truth_review_v1,
    project_tier3_truth_evidence,
    validate_settlement_truth_review,
)


def resolve_paths(db_arg: Optional[str], root_arg: Optional[str]) -> Tuple[Path, Path]:
    if db_arg:
        db_path = Path(db_arg).resolve()
    else:
        db_path = (_ROOT_DIR / "异环拍卖数据.json").resolve()

    if root_arg:
        data_root = Path(root_arg).resolve()
    else:
        data_root = db_path.parent.resolve()

    return db_path, data_root


def resolve_reviewer_id(cli_reviewer_id: Optional[str], interactive: bool = True) -> str:
    # 1. Explicit CLI argument
    if cli_reviewer_id and str(cli_reviewer_id).strip():
        return str(cli_reviewer_id).strip()

    # 2. Environment variable
    env_val = os.environ.get("NTE_REVIEWER_ID")
    if env_val and str(env_val).strip():
        return str(env_val).strip()

    # 3. Local configuration
    config_path = _APP_DIR / "config.json"
    if config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            cfg_id = cfg.get("reviewerId")
            if cfg_id and str(cfg_id).strip():
                return str(cfg_id).strip()
        except Exception:
            pass

    # 4. Interactive prompt
    if interactive and sys.stdin.isatty():
        hint = getpass.getuser() or "operator"
        try:
            val = input(f"Enter stable reviewer identity [{hint}]: ").strip()
            return val or hint
        except (EOFError, KeyboardInterrupt):
            pass

    raise ReviewError(
        "Formal reviewer identity is required. Provide --reviewer-id <id> or set NTE_REVIEWER_ID environment variable."
    )


def load_database_records(db_path: Path) -> List[Dict[str, Any]]:
    if not db_path.is_file():
        raise ReviewError(f"Database file not found: {db_path}")
    try:
        content = db_path.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "records" in data and isinstance(data["records"], list):
            return data["records"]
        else:
            raise ReviewError("Database file does not contain a valid JSON record array.")
    except Exception as e:
        raise ReviewError(f"Failed to read database {db_path}: {e}")


def get_record_tier1_evidence(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    settlement = record.get("settlement")
    if not isinstance(settlement, dict):
        return None
    truth = settlement.get("truthEvidence")
    if not isinstance(truth, dict):
        return None
    if truth.get("schemaVersion") != "settlement-truth-evidence.v1":
        return None
    return truth


def cmd_list(args: argparse.Namespace) -> int:
    db_path, data_root = resolve_paths(getattr(args, "database", None), getattr(args, "data_root", None))
    records = load_database_records(db_path)
    store = ReviewStoreManager(data_root)

    print(f"📂 Database:  {db_path}")
    print(f"📦 Data Root: {data_root}")
    print(f"📋 Total Records: {len(records)}\n")

    header = f"{'Match ID':<35} {'Actual Total':<15} {'Observed At':<30} {'PNG Valid':<10} {'Review Status':<15}"
    print(header)
    print("-" * len(header))

    count = 0
    for rec in records:
        mid = str(rec.get("id") or "").strip()
        truth = get_record_tier1_evidence(rec)
        if not truth:
            continue

        source_sha = truth.get("truthPayloadSha256", "")
        existing_rev = store.get_terminal_review(mid, source_sha) if source_sha else None

        if existing_rev and not getattr(args, "all", False):
            continue

        # Check PNG disk validity
        rel_uri = (truth.get("evidenceReferences") or [{}])[0].get("uri")
        ev_sha = (truth.get("evidenceReferences") or [{}])[0].get("sha256")
        png_ok = verify_evidence_file(rel_uri, ev_sha, data_dir=data_root) if (rel_uri and ev_sha) else False

        rev_status = existing_rev.get("action", "unreviewed") if existing_rev else "pending"
        actual_val = str(truth.get("actualTotal", "--"))
        obs_at = str(truth.get("settlementObservedAt", "--"))

        print(f"{mid:<35} {actual_val:<15} {obs_at:<30} {str(png_ok):<10} {rev_status:<15}")
        count += 1

    print(f"\nFound {count} record(s).")
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    db_path, data_root = resolve_paths(getattr(args, "database", None), getattr(args, "data_root", None))
    records = load_database_records(db_path)
    store = ReviewStoreManager(data_root)

    target_id = str(args.match_id).strip()
    target_rec = next((r for r in records if str(r.get("id") or "").strip() == target_id), None)
    if not target_rec:
        print(f"❌ Match ID '{target_id}' not found in database {db_path}")
        return 1

    truth = get_record_tier1_evidence(target_rec)
    if not truth:
        print(f"❌ Match '{target_id}' does not have a valid settlement.truthEvidence object.")
        return 1

    is_valid, reasons = validate_settlement_truth_evidence(truth, match_id=target_id, data_dir=data_root, check_disk_bytes=True)
    if not is_valid:
        print(f"⚠️ Tier 1 Truth Evidence failed validation: {reasons}")

    rel_uri = truth["evidenceReferences"][0]["uri"]
    ev_sha = truth["evidenceReferences"][0]["sha256"]
    png_path = data_root / rel_uri.replace("/", os.sep)

    source_sha = truth.get("truthPayloadSha256", "")
    existing_rev = store.get_terminal_review(target_id, source_sha)

    print("\n" + "=" * 60)
    print(f"🔍 Match Details: {target_id}")
    print("=" * 60)
    print(f"Played At:           {target_rec.get('playedAt') or target_rec.get('timestamp')}")
    print(f"Venue / Box:         {target_rec.get('venue')} / {target_rec.get('box')}")
    print(f"Machine ActualTotal: {truth.get('actualTotal')}")
    print(f"Clearing Price:      {target_rec.get('clearingPrice')}")
    print(f"Profit:              {target_rec.get('realizedProfit') or target_rec.get('profit')}")
    print(f"Captured At:         {truth.get('settlementObservedAt')}")
    print(f"Evidence URI:        {rel_uri}")
    print(f"Evidence SHA-256:    {ev_sha}")
    print(f"PNG File Path:       {png_path}")
    print(f"PNG Exists & Valid:  {png_path.is_file()}")
    print(f"Terminal Review:     {existing_rev.get('action') if existing_rev else 'None (Pending)'}")
    if existing_rev:
        print(f"Review ID:           {existing_rev.get('reviewId')}")
        print(f"Reviewer:            {existing_rev.get('reviewer', {}).get('id')}")
        print(f"Reviewed At:         {existing_rev.get('reviewedAt')}")
        print(f"Reviewed Total:      {existing_rev.get('reviewedActualTotal')}")
    print("=" * 60 + "\n")

    if not getattr(args, "no_open", False) and png_path.is_file():
        try:
            print(f"🖼️ Opening evidence image: {png_path}")
            if sys.platform == "win32":
                os.startfile(str(png_path))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(png_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(png_path)], check=False)
        except Exception as e:
            print(f"⚠️ Could not open image viewer automatically: {e}")

    return 0


def _execute_review(args: argparse.Namespace, action: str, corrected_total: Optional[float] = None) -> int:
    db_path, data_root = resolve_paths(getattr(args, "database", None), getattr(args, "data_root", None))
    records = load_database_records(db_path)
    store = ReviewStoreManager(data_root)

    target_id = str(args.match_id).strip()
    target_rec = next((r for r in records if str(r.get("id") or "").strip() == target_id), None)
    if not target_rec:
        print(f"❌ Match ID '{target_id}' not found in database {db_path}")
        return 1

    truth = get_record_tier1_evidence(target_rec)
    if not truth:
        print(f"❌ Match '{target_id}' does not have a valid settlement.truthEvidence object.")
        return 1

    # Strictly re-validate source Tier 1 and disk PNG
    is_valid, reasons = validate_settlement_truth_evidence(truth, match_id=target_id, data_dir=data_root, check_disk_bytes=True)
    if not is_valid:
        print(f"❌ Source Tier 1 Evidence failed contract/disk validation: {reasons}")
        return 1

    source_sha = truth["truthPayloadSha256"]
    existing_rev = store.get_terminal_review(target_id, source_sha)
    if existing_rev:
        print(f"❌ Terminal review already exists for match '{target_id}' (reviewId={existing_rev.get('reviewId')}, action={existing_rev.get('action')}).")
        print("   Overwriting existing review is strictly forbidden.")
        return 1

    reviewer_id = resolve_reviewer_id(getattr(args, "reviewer_id", None))
    reviewed_at = datetime.now(timezone(timedelta(hours=8))).isoformat()
    original_total = float(truth["actualTotal"])
    rel_uri = truth["evidenceReferences"][0]["uri"]
    ev_sha = truth["evidenceReferences"][0]["sha256"]

    if action == "confirmed":
        reviewed_total = original_total
    elif action == "corrected":
        if corrected_total is None or corrected_total <= 0:
            print("❌ corrected action requires a positive numeric actual_total.")
            return 1
        reviewed_total = float(corrected_total)
    else:  # rejected
        reviewed_total = None

    artifact = build_settlement_truth_review_v1(
        match_id=target_id,
        action=action,
        original_actual_total=original_total,
        reviewed_actual_total=reviewed_total,
        source_truth_payload_sha256=source_sha,
        evidence_uri=rel_uri,
        evidence_sha256=ev_sha,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
    )

    try:
        saved_path = store.save_review_artifact(artifact)
        print(f"✅ Review artifact saved: {saved_path}")
        print(f"   Review ID:       {artifact['reviewId']}")
        print(f"   Action:          {artifact['action']}")
        print(f"   Reviewer:        {reviewer_id}")
        print(f"   Original Total:  {original_total}")
        print(f"   Reviewed Total:  {reviewed_total}")
        print(f"   Reviewed At:     {reviewed_at}")
    except ReviewConflictError as e:
        print(f"❌ Conflict: {e}")
        return 1
    except Exception as e:
        print(f"❌ Failed to save review artifact: {e}")
        return 1

    # Project Tier 3 candidate
    tier3_proj = project_tier3_truth_evidence(truth, artifact, data_dir=data_root)
    if tier3_proj:
        print(f"🌟 Tier 3 Truth Evidence Projection Generated (truthConfidence: 'high', payloadSha256: {tier3_proj['truthPayloadSha256'][:16]}...)")
    else:
        print("ℹ️ Tier 3 Truth Evidence Projection is UNAVAILABLE (action is rejected or invalid).")

    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    return _execute_review(args, action="confirmed")


def cmd_correct(args: argparse.Namespace) -> int:
    try:
        corrected_val = float(args.actual_total)
    except ValueError:
        print(f"❌ Invalid numeric value for actual_total: {args.actual_total}")
        return 1
    return _execute_review(args, action="corrected", corrected_total=corrected_val)


def cmd_reject(args: argparse.Namespace) -> int:
    return _execute_review(args, action="rejected")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--database", "-d", default=argparse.SUPPRESS, help="Path to database JSON file")
    common.add_argument("--data-root", "-r", default=argparse.SUPPRESS, help="Path to canonical data root directory")
    common.add_argument("--reviewer-id", "-u", default=argparse.SUPPRESS, help="Stable reviewer identity string")

    parser = argparse.ArgumentParser(
        description="Settlement Truth Review v1 Offline Management CLI",
        parents=[common],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List pending or unreviewed Tier 1 records", parents=[common])
    p_list.add_argument("--all", "-a", action="store_true", help="Show all records including already reviewed ones")

    # view / inspect
    p_view = subparsers.add_parser("view", help="Inspect record details and open evidence screenshot", parents=[common])
    p_view.add_argument("match_id", help="Target match ID to inspect")
    p_view.add_argument("--no-open", action="store_true", help="Do not launch image viewer")

    p_inspect = subparsers.add_parser("inspect", help="Alias for view", parents=[common])
    p_inspect.add_argument("match_id", help="Target match ID to inspect")
    p_inspect.add_argument("--no-open", action="store_true", help="Do not launch image viewer")

    # confirm
    p_conf = subparsers.add_parser("confirm", help="Confirm that machine actualTotal matches the screenshot", parents=[common])
    p_conf.add_argument("match_id", help="Target match ID to confirm")

    # correct
    p_corr = subparsers.add_parser("correct", help="Correct machine actualTotal to match the screenshot", parents=[common])
    p_corr.add_argument("match_id", help="Target match ID to correct")
    p_corr.add_argument("actual_total", type=float, help="Corrected actualTotal value")

    # reject
    p_rej = subparsers.add_parser("reject", help="Reject screenshot evidence (blurry, corrupt, invalid)", parents=[common])
    p_rej.add_argument("match_id", help="Target match ID to reject")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in {"view", "inspect"}:
        return cmd_view(args)
    elif args.command == "list":
        return cmd_list(args)
    elif args.command == "confirm":
        return cmd_confirm(args)
    elif args.command == "correct":
        return cmd_correct(args)
    elif args.command == "reject":
        return cmd_reject(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
