# -*- coding: utf-8 -*-
"""Generate alignment file separating machine predictions from independent ground truth for 39 warehouse items.

Strictly preserves:
- assets/items/video_ground_truth_reference_144037.json (independent ground truth)
Outputs:
- assets/items/video_prediction_alignment_144037.json (machine prediction alignment)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "core"))
from catalog_validator import is_valid_catalog_id, get_official_name, validate_item_identity

GT_PATH = PROJECT_ROOT / "assets" / "items" / "video_ground_truth_reference_144037.json"
DEFAULT_RETEST_V2_PACKET = PROJECT_ROOT / "build" / "diagnosis_20260911" / "p3-warehouse" / "video_audit_retest_v2" / "audit_review_packet.json"
CATALOG_PATH = PROJECT_ROOT / "assets" / "catalog_065.json"
MANIFEST_V2_PATH = PROJECT_ROOT / "assets" / "items" / "catalog_reference_manifest_v2.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "assets" / "items" / "video_prediction_alignment_144037.json"


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _get_git_status(cwd: Path = PROJECT_ROOT) -> tuple[str, bool, Optional[str]]:
    try:
        c = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd), capture_output=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
        status_out = subprocess.run(["git", "status", "--porcelain"], cwd=str(cwd), capture_output=True, encoding="utf-8", errors="replace", check=True).stdout
        diff_out = subprocess.run(["git", "diff", "HEAD"], cwd=str(cwd), capture_output=True, encoding="utf-8", errors="replace", check=True).stdout
        is_dirty = bool(status_out.strip())
        diff_sha = hashlib.sha256(diff_out.encode("utf-8")).hexdigest() if is_dirty else None
        return c, is_dirty, diff_sha
    except Exception:
        return "UNKNOWN_COMMIT", False, None


def _get_packet_creation_commit(packet_path: Path) -> str:
    prov_path = packet_path.parent / "audit_provenance_20260911.json"
    if prov_path.is_file():
        try:
            prov_data = json.loads(prov_path.read_text(encoding="utf-8"))
            if prov_data.get("gitCommit") and prov_data["gitCommit"] != "UNKNOWN":
                return prov_data["gitCommit"]
        except Exception:
            pass
    try:
        res = subprocess.run(
            ["git", "log", "-n", "1", "--format=%H", "--", str(packet_path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        c = res.stdout.strip()
        if c:
            return c
    except Exception:
        pass
    return "WORKING_TREE_UNCOMMITTED"


def generate_alignment(packet_path: Optional[Path] = None, output_path: Optional[Path] = None) -> Path:
    if packet_path is None:
        raise ValueError(
            "Explicit --packet path is required to avoid accidental stale report generation. "
            "Pass --packet <path_to_audit_review_packet.json>."
        )

    packet_path = Path(packet_path).resolve()
    if not packet_path.is_file():
        raise FileNotFoundError(
            f"Audit review packet missing at '{packet_path}'. "
            f"Silent fallback to historical review packets is strictly forbidden; "
            f"pass an existing, validated audit packet path."
        )

    output_path = Path(output_path).resolve() if output_path else DEFAULT_OUTPUT_PATH

    gt_data = json.loads(GT_PATH.read_text(encoding="utf-8"))
    gt_items = gt_data.get("items", [])
    packet_data = json.loads(packet_path.read_text(encoding="utf-8"))
    packet_units = packet_data.get("reviewUnits", [])
    cat065 = {str(c["Id"]): c for c in json.loads(CATALOG_PATH.read_text(encoding="utf-8"))}
    manifest_v2 = {str(r["catalogId"]): r for r in json.loads(MANIFEST_V2_PATH.read_text(encoding="utf-8")).get("records", [])}

    # 0. Strict entrypoint validation of raw review unit candidates:
    # All candidates must have a valid registered catalogId and official name.
    # Unknown ID, missing name, or ID-name mismatch must raise ValueError immediately before any output is touched.
    for u in packet_units:
        u_id = u.get("reviewUnitId", "unknown_unit")
        for c in u.get("candidates", []):
            raw_cid = c.get("catalogId")
            raw_name = c.get("name") or c.get("canonicalName")
            if not raw_cid or not is_valid_catalog_id(str(raw_cid)):
                raise ValueError(
                    f"Unknown or invalid catalogId '{raw_cid}' in review unit '{u_id}': "
                    f"all candidates must originate strictly from the verified catalog."
                )
            if not raw_name or not str(raw_name).strip():
                raise ValueError(
                    f"Missing candidate name for catalogId '{raw_cid}' in review unit '{u_id}'."
                )
            validate_item_identity(
                str(raw_cid),
                str(raw_name).strip(),
                c.get("identityStatus", "CANDIDATE_ONLY"),
            )

    unit_by_anchor = {}
    for u in packet_units:
        wa = u.get("worldAnchor", {})
        fp = u.get("footprint", {})
        if wa.get("row") is not None and fp.get("widthCells") is not None:
            key = (wa.get("row"), wa.get("col"), fp.get("widthCells"), fp.get("heightCells"))
        elif u.get("anchorKey") and len(u["anchorKey"]) == 4:
            key = tuple(u["anchorKey"])
        else:
            key = None
        if key:
            unit_by_anchor[key] = u

    alignment_records = []
    plausible_count = 0
    no_cand_count = 0
    contradiction_count = 0
    candidate_list_matched_count = 0
    first_choice_matched_count = 0
    false_first_choice_count = 0
    ambiguous_count = 0
    gt_confirmed_count = 0

    for it in sorted(gt_items, key=lambda x: x["referenceId"]):
        ref_id = it["referenceId"]
        bb = it["gridBoundingBox"]
        gt_cname = it.get("canonicalName")
        gt_cid = it.get("catalogId")
        if gt_cname and gt_cid:
            gt_confirmed_count += 1

        key = (bb["row"], bb["col"], bb["width"], bb["height"])
        u = unit_by_anchor.get(key)

        crop_path = PROJECT_ROOT / it["localCropPath"]
        crop_exists = crop_path.is_file()

        u_cands = u.get("candidates", []) if u else []
        analyzed_cands = []
        for c in u_cands:
            cid = str(c.get("catalogId") or "").strip()
            # Use raw candidate name directly without table lookup rewriting
            cand_name = str(c.get("name") or c.get("canonicalName") or "").strip()
            c_geom = c.get("geometry", {})
            c_shape = c_geom.get("shape")
            c_reasons = c.get("matchReasons", [])

            shape_match = (c_shape == bb["shape"])

            # Strict ID and name binding verification:
            # Both catalogId and cand_name must match the ground truth binding!
            if gt_cid:
                expected_name = gt_cname or get_official_name(gt_cid) or (manifest_v2.get(gt_cid, {}).get("name")) or (cat065.get(gt_cid, {}).get("Name"))
                is_gt_match = (cid == gt_cid) and (cand_name == expected_name)
            else:
                is_gt_match = False

            analyzed_cands.append({
                "catalogId": cid,
                "name": cand_name,
                "candidateShape": c_shape,
                "shapeConsistent": shape_match,
                "identityMatchesGroundTruth": is_gt_match,
                "matchReasons": c_reasons,
                "inManifestV2": cid in manifest_v2,
                "inCatalog065": cid in cat065,
                "identityStatus": "CANDIDATE_ONLY",
            })

        consistent = [c for c in analyzed_cands if c["shapeConsistent"]]
        candidate_list_matched = any(c["identityMatchesGroundTruth"] and c["shapeConsistent"] for c in analyzed_cands)
        if candidate_list_matched:
            candidate_list_matched_count += 1

        first_choice_matched = False
        is_first_choice_error = False

        if not analyzed_cands:
            align_category = "NO_MACHINE_CANDIDATE"
            notes = "No candidate proposal generated by machine resolver."
            no_cand_count += 1
        else:
            # First choice is strictly the FIRST item in the raw candidate list (analyzed_cands[0])
            # It cannot skip dimensionally incorrect items to treat the 2nd item as first choice!
            raw_first_choice = analyzed_cands[0]
            first_choice_matched = bool(
                raw_first_choice["shapeConsistent"] and raw_first_choice["identityMatchesGroundTruth"]
            )
            if first_choice_matched:
                first_choice_matched_count += 1
            else:
                # Raw first choice failed shape or identity: strictly recorded as first choice error!
                is_first_choice_error = True
                false_first_choice_count += 1

            if consistent:
                align_category = "CANDIDATE_PLAUSIBLE"
                if len(consistent) > 1:
                    ambiguous_count += 1
                notes = (
                    f"Machine proposed {len(consistent)} shape-consistent candidate(s). "
                    f"Raw first choice: {raw_first_choice['name']} ({raw_first_choice['catalogId']}), matched={first_choice_matched}. "
                    f"Shape matching does NOT equal confirmed identity."
                )
                plausible_count += 1
            else:
                align_category = "GEOMETRY_CONTRADICTION"
                contradiction_cands = [f"{c['name']} ({c['candidateShape']})" for c in analyzed_cands]
                notes = (
                    f"Machine candidates {contradiction_cands} contradict ground truth shape {bb['shape']}; "
                    f"rejected candidate assignment."
                )
                contradiction_count += 1

        alignment_records.append({
            "referenceId": ref_id,
            "gridBoundingBox": bb,
            "quality": it["quality"],
            "visualDescription": it["visualDescription"],
            "observationBasis": it["observationBasis"],
            "localCropPath": it["localCropPath"],
            "cropExists": crop_exists,
            "machineReviewUnitId": u.get("reviewUnitId") if u else None,
            "machineCandidates": analyzed_cands,
            "alignmentCategory": align_category,
            "candidateListMatchesGroundTruth": candidate_list_matched,
            "firstChoiceMatchesGroundTruth": first_choice_matched,
            "isFirstChoiceError": is_first_choice_error,
            "identityStatus": "CANDIDATE_ONLY" if align_category == "CANDIDATE_PLAUSIBLE" else "UNCONFIRMED",
            "notes": notes,
        })

    head_commit, is_dirty, diff_sha = _get_git_status(PROJECT_ROOT)

    alignment_data = {
        "metadata": {
            "title": "39件基准录像物品机器预测与独立看图真值对齐报告",
            "videoPath": "D:\\yihuanpaimai\\data\\videos\\2026-09-08 14-40-37.mkv",
            "provenanceNote": (
                "Machine predictions extracted from dense warehouse reconstruction (audit_review_packet.json) "
                "aligned against independent visual inspection ground truth (video_ground_truth_reference_144037.json). "
                "Machine candidates are strictly separated from ground truth to prevent identity bias. "
                "No identities were guessed using total price."
            ),
            "nameCorrectionNote": (
                "Correction: The two items previously missing machine candidates were 复古圆桌 (ref_144037_05, image14-0-2, 2x1) "
                "and 绵绵云 (ref_144037_20, image3-0-1, 1x1). The ground truth reference data in "
                "assets/items/video_ground_truth_reference_144037.json was already correct; previous human-authored response text "
                "had misstated their names. All item names are strictly mapped from verified catalog IDs and manifest records."
            ),
            "inputPacketPath": (
                str(packet_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if (hasattr(packet_path, "is_relative_to") and packet_path.is_relative_to(PROJECT_ROOT))
                else str(packet_path).replace("\\", "/")
            ),
            "inputPacketSha256": _sha256_file(packet_path),
            "inputPacketCreationCommit": _get_packet_creation_commit(packet_path),
            "reportGenerationCommit": head_commit,
            "workingTreeDirty": is_dirty,
            "workingTreeDiffSha256": diff_sha,
            "catalogManifestSha256": _sha256_file(MANIFEST_V2_PATH),
            "groundTruthSha256": _sha256_file(GT_PATH),
            "totalItems": len(alignment_records),
            "statistics": {
                "candidatePlausibleCount": plausible_count,
                "shapeConsistentCount": plausible_count,
                "candidateListMatchedCount": candidate_list_matched_count,
                "firstChoiceMatchedCount": first_choice_matched_count,
                "falseFirstChoiceCount": false_first_choice_count,
                "identityMatchedCount": first_choice_matched_count,
                "falseIdentityCount": false_first_choice_count,
                "ambiguousCandidateCount": ambiguous_count,
                "noMachineCandidateCount": no_cand_count,
                "geometryContradictionCount": contradiction_count,
                "confirmedExactCount": 0,
                "groundTruthConfirmedCount": gt_confirmed_count,
            },
        },
        "items": alignment_records,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(alignment_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote alignment data to {output_path}")
    print(
        f"Statistics: plausible={plausible_count}, candidate_list_matched={candidate_list_matched_count}, "
        f"first_choice_matched={first_choice_matched_count}, false_first_choice={false_first_choice_count}, "
        f"ambiguous={ambiguous_count}, no_cand={no_cand_count}, contradiction={contradiction_count}, "
        f"confirmed_exact=0, gt_confirmed={gt_confirmed_count}"
    )
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate 39 item prediction alignment against ground truth.")
    parser.add_argument("--packet", type=str, required=True, help="Path to audit_review_packet.json")
    parser.add_argument("--output", type=str, default=None, help="Path to output alignment json")
    args = parser.parse_args()
    generate_alignment(
        packet_path=Path(args.packet),
        output_path=Path(args.output) if args.output else None,
    )
