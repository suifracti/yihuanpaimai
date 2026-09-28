"""Finish one saved settlement viewport into its existing isolated DRAFT.

This never changes pre-settlement facts, prediction, formal History, or a live
CurrentMatch. The session's saved frame/state pair must identify the draft.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from native_trial_drafts import NativeTrialDraftStore  # noqa: E402
from settlement_inventory_archive import _archive_key, recognize_saved_inventory  # noqa: E402


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

    source = drafts.capture_frame(frame_path, {
        "capturedAtUtc": frame_record["capturedAt"],
        "frameSequence": frame_record["frameSequence"],
        "observationSessionId": state["state"]["sessionId"],
        "targetInstance": state["state"]["observationTargetIdentity"],
    }, expected_pixel_sha256=frame_record["pixelSha256"])
    source.update(settlementBoundary=True, pixelSha256=frame_record["pixelSha256"])
    result = recognize_saved_inventory(drafts, match_id, source)
    old_archive = (draft.get("settlement") or {}).get("inventoryArchive") or {}
    archive = {"sourceKey": _archive_key(match_id, source), "status": "SAVED",
               "source": source, "capturedAt": source["capturedAt"], "attempts": 1}
    drafts.patch_inventory_archive(match_id, {**result, "inventoryArchive": archive},
                                   {"sourceKey": old_archive.get("sourceKey")})
    visible = result["visibleInventory"]
    return {"matchId": match_id, "status": "SAVED", "visibleProposals": len(result["settlementItems"]),
            "trustedReferenceMatches": visible["trustedReferenceMatchCount"],
            "parentEvidenceId": visible["parentEvidenceId"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(continue_saved_session(args.session_dir), ensure_ascii=True))
