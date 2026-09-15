"""Read-only frame probe shared by source and frozen runtime acceptance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


def run_from_environment(assets_dir: str) -> int:
    result = {"smoke": "vision-frame-v1", "frozen": bool(getattr(sys, "frozen", False)),
              "success": False}
    try:
        import cv2
        import numpy as np
        from runtime_revision import get_code_revision
        from keyboard_auction_pipeline import KeyboardAuctionPipeline
        from visual_catalog import verified_references

        frame_path = Path(os.environ["NTE_SMOKE_FRAME"]).resolve(strict=True)
        data = frame_path.read_bytes()
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Frame cannot be decoded")
        pipe = KeyboardAuctionPipeline(catalog_path=str(Path(assets_dir) / "catalog_065.json"))
        pipe.recognition_mode_provider=lambda:'auto'
        pipe._ensure_ocr()
        references = verified_references()
        result['visualReferenceCount'] = len(references)
        if not references:
            raise RuntimeError('Verified visual catalog references are missing')
        result.update(codeRevision=get_code_revision(), frameSha256=hashlib.sha256(data).hexdigest(),
                      frameSize=[int(frame.shape[1]), int(frame.shape[0])],
                      templateCounts={"characters": len(pipe.character_matcher.templates),
                                      "venues": len(pipe.venue_matcher.templates),
                                      "tools": len(pipe.tool_matcher.templates)})
        from visual_catalog import deterministic_reference_crops
        crops = deterministic_reference_crops()
        result["catalogLoad"] = {
            "verifiedReferences": len(references),
            "manifestRecovered": len(crops),
            "manifestSelected": "v2" if (Path(assets_dir) / "items" / "catalog_reference_manifest_v2.json").is_file() else "v1",
            "manifestV2Present": (Path(assets_dir) / "items" / "catalog_reference_manifest_v2.json").is_file(),
        }
        fields = ("scene", "round", "timer", "q", "goldAvg", "goldCount", "box",
                  "lobbyCharacter", "lobbyVenue", "lobbyToolGroup", "currentEstimate",
                  "isSettlement", "myName", "opponents", "finalBids", "warehouseSlots")
        fields += ('settlementReady', 'settlementItemCount', 'settlementExactItemCount',
                   'settlementExactValueSum', 'settlementLedgerVerified', 'settlementItems',
                   'clearingPrice', 'actualTotal', 'winner')
        def _compact_items(items):
            out = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                out.append({
                    "name": item.get("name") or item.get("identifiedName"),
                    "catalogId": item.get("catalogId") or item.get("exactItemId"),
                    "status": item.get("status"),
                    "price": item.get("price"),
                    "row": item.get("row"),
                    "col": item.get("col"),
                    "widthCells": item.get("widthCells") or item.get("w"),
                    "heightCells": item.get("heightCells") or item.get("h"),
                    "bbox": item.get("bbox"),
                    "rarity": item.get("rarity"),
                })
            return out

        result["frames"] = []
        for _ in range(len(pipe.scene_roi_router.groups)+2):
            if pipe._classify_scene_fast(frame.copy()).get('confirmed'):break
        for _ in range(2):
            context = pipe.process_frame(frame.copy())
            st = context.get("settlementData") or {}
            row = {k: context.get(k) for k in fields}
            row["clearingPrice"] = context.get("clearingPrice") if context.get("clearingPrice") is not None else st.get("clearingPrice")
            row["actualTotal"] = context.get("actualTotal") if context.get("actualTotal") is not None else st.get("actualTotal")
            row["winner"] = context.get("winner") or st.get("winner")
            row["settlementItems"] = _compact_items(context.get("settlementItems") or st.get("items") or [])
            result["frames"].append(json.loads(json.dumps(row, default=str)))
        result['sceneRouting']=pipe._route
        pipe._navigation_executor.shutdown(wait=True)
        result["success"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    output = os.environ.get("NTE_SMOKE_OUTPUT")
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1
