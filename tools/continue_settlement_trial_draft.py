"""Finish one saved settlement viewport into its existing isolated DRAFT.

This never changes pre-settlement facts, prediction, formal History, or a live
CurrentMatch. The session's saved frame/state pair must identify the draft.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from native_trial_drafts import NativeTrialDraftStore  # noqa: E402
from settlement_evidence_store_v2 import (  # noqa: E402
    COVERAGE_UNPROVEN, KIND_MAIN, SettlementEvidenceStoreV2,
)
from settlement_item_proposals import extract_settlement_warehouse_proposals  # noqa: E402
from settlement_item_recognizer import SettlementItemRecognizer  # noqa: E402
from settlement_stable_frame_persist import encode_settlement_original  # noqa: E402


def continue_saved_session(session_dir: Path) -> dict:
    session_dir = session_dir.resolve(strict=True)
    allowed = (ROOT / "build" / "native-observation").resolve()
    if allowed not in session_dir.parents:
        raise ValueError("session must be under the isolated native-observation build root")
    state = json.loads((session_dir / "settlement-final-state.json").read_text(encoding="utf-8"))
    frame_record = state["state"]["lastFrame"]
    match_id = str(frame_record["stateMatchId"])
    if frame_record["scene"] != "SETTLEMENT" or state["frameSequence"] != frame_record["frameSequence"]:
        raise ValueError("saved frame/state is not a matching settlement pair")
    frame_path = session_dir / "settlement-final-frame.bmp"
    raw = frame_path.read_bytes()
    if (raw[:2] != b"BM" or raw[28:30] != b"\x20\x00" or
            hashlib.sha256(raw[54:]).hexdigest() != frame_record["pixelSha256"]):
        raise ValueError("settlement frame differs from worker pixel evidence")

    history_path = allowed / "trial-drafts" / "canonical-history.json"
    drafts = NativeTrialDraftStore(history_path)
    draft = drafts.lookup(match_id)
    if draft is None:
        raise ValueError("same-match isolated DRAFT is unavailable")
    existing = (draft.get("settlement") or {}).get("visibleInventory") or {}
    if existing.get("sourcePixelSha256") == frame_record["pixelSha256"]:
        return {"matchId": match_id, "status": "UNCHANGED", "visibleProposals": existing.get("visibleProposalCount")}

    frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise ValueError("saved settlement frame cannot be decoded")
    recognizer = SettlementItemRecognizer()
    ledger = recognizer.parse_settlement_ledger(frame, (draft.get("settlement") or {}).get("actualTotal"))
    store = SettlementEvidenceStoreV2(history_path.parent)
    parent = store.save_original(
        record_stable_key=match_id, kind=KIND_MAIN,
        image_bytes=encode_settlement_original(frame),
        captured_at=frame_record["capturedAt"],
        coverage_mode="viewport-segment", coverage_status=COVERAGE_UNPROVEN,
    )
    proposals = extract_settlement_warehouse_proposals(
        store=store, parent_descriptor=parent, recognizer=recognizer, save_crops=True)
    by_geometry = {}
    for proposal in proposals:
        cells = proposal.get("gridCells") or []
        if cells:
            key = (min(cell[0] for cell in cells), min(cell[1] for cell in cells),
                   proposal["widthCells"], proposal["heightCells"])
            by_geometry[key] = proposal
    items = []
    for item in ledger["settlementItems"]:
        key = (item["row"], item["col"], item["widthCells"], item["heightCells"])
        proposal = by_geometry.get(key)
        if proposal is None:
            raise ValueError(f"settlement source crop missing for geometry {key}")
        linked = copy.deepcopy(item)
        linked["sourcePhase"] = "SETTLEMENT"
        linked["sourceCapturedAt"] = frame_record["capturedAt"]
        linked["parentEvidenceId"] = parent["evidenceId"]
        linked["parentSha256"] = parent["sha256"]
        linked["cropEvidenceId"] = proposal["cropEvidenceId"]
        linked["cropRelativePath"] = proposal["cropRelativePath"]
        linked["cropSha256"] = proposal["cropSha256"]
        linked["identityEvidence"].update({
            "recordStableKey": match_id, "parentEvidenceId": parent["evidenceId"],
            "parentSha256": parent["sha256"], "cropEvidenceId": proposal["cropEvidenceId"],
            "cropRelativePath": proposal["cropRelativePath"], "cropSha256": proposal["cropSha256"],
        })
        items.append(linked)

    updated = copy.deepcopy(draft)
    settlement = updated.setdefault("settlement", {})
    settlement["settlementItems"] = items
    settlement["visibleInventory"] = {
        "sourcePhase": "SETTLEMENT", "sourceFrameSequence": frame_record["frameSequence"],
        "sourceCapturedAt": frame_record["capturedAt"],
        "sourcePixelSha256": frame_record["pixelSha256"],
        "parentEvidenceId": parent["evidenceId"], "parentSha256": parent["sha256"],
        "visibleProposalCount": len(items),
        "trustedReferenceMatchCount": sum(item["status"] == "exact" for item in items),
        "coverageStatus": "PARTIAL_VIEWPORT_ONLY", "outsideViewport": "UNKNOWN",
        "itemLedgerVerified": False,
    }
    # save_draft preserves the same record's prediction and activity inventory.
    drafts.save_draft(updated)
    return {"matchId": match_id, "status": "SAVED", "visibleProposals": len(items),
            "trustedReferenceMatches": settlement["visibleInventory"]["trustedReferenceMatchCount"],
            "parentEvidenceId": parent["evidenceId"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(continue_saved_session(args.session_dir), ensure_ascii=True))
