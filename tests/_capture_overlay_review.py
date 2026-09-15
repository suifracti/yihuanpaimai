# -*- coding: utf-8 -*-
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _alpha_live_smoke import launch_hud, wait_ready, send_facts

OUT = Path(__file__).resolve().parents[1] / "tests" / "alpha_live_shots"
OUT.mkdir(parents=True, exist_ok=True)
WS = "ws://127.0.0.1:8766"


async def call(ws, payload, expect, timeout=8):
    await ws.send(json.dumps(payload, ensure_ascii=False))
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1)
            data = json.loads(raw)
        except Exception:
            continue
        last = data
        if data.get("type") == expect:
            return data
    return last


async def main():
    launch_hud()
    hwnd, title, box = wait_ready(40)
    default_path = str(OUT / "review_default.png")
    expanded_path = str(OUT / "review_expanded.png")
    pop_venue_path = str(OUT / "review_popover_venue.png")
    pop_boxes_gaoji_path = str(OUT / "review_popover_gaoji_boxes.png")
    pop_field_path = str(OUT / "review_popover_field.png")

    async with websockets.connect(WS) as ws:
        await send_facts(ws, {
            "venue": "shanhu",
            "box": "琉璃宝箱 · 宝石类概率提升",
            "fieldCondition": "standard",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "51077/18031",
            "knownRed": "577777*2",
        })
        await asyncio.sleep(0.6)
        # 1. Collapsed
        await call(ws, {"type": "eval_overlay_js", "script": "typeof setExpanded === 'function' ? setExpanded(false) : (window.setOverlayExpanded && window.setOverlayExpanded(false))"}, "overlay_js_result")
        await asyncio.sleep(0.4)
        d1 = await call(ws, {"type": "capture_overlay_preview", "path": default_path}, "overlay_preview_saved")
        
        # 2. Expanded default
        await call(ws, {"type": "eval_overlay_js", "script": "typeof setExpanded === 'function' ? setExpanded(true) : (window.setOverlayExpanded && window.setOverlayExpanded(true))"}, "overlay_js_result")
        await asyncio.sleep(0.5)
        d2 = await call(ws, {"type": "capture_overlay_preview", "path": expanded_path}, "overlay_preview_saved")

        # 3. Popover open: Venue levels
        await call(ws, {"type": "eval_overlay_js", "script": "openPopover('venueTier', document.getElementById('venueChip'))"}, "overlay_js_result")
        await asyncio.sleep(0.4)
        d3 = await call(ws, {"type": "capture_overlay_preview", "path": pop_venue_path}, "overlay_preview_saved")

        # 4. Switch to 高级场 and open box popover
        await call(ws, {"type": "eval_overlay_js", "script": "selectPopoverOption('venueTier', 'gaoji'); openPopover('box', document.getElementById('boxChip'))"}, "overlay_js_result")
        await asyncio.sleep(0.4)
        d4 = await call(ws, {"type": "capture_overlay_preview", "path": pop_boxes_gaoji_path}, "overlay_preview_saved")

        # 5. Open field condition popover
        await call(ws, {"type": "eval_overlay_js", "script": "openPopover('field', document.getElementById('fieldChip'))"}, "overlay_js_result")
        await asyncio.sleep(0.4)
        d5 = await call(ws, {"type": "capture_overlay_preview", "path": pop_field_path}, "overlay_preview_saved")

    report = {
        "hwnd": hwnd,
        "title": title,
        "box": box,
        "default": d1,
        "expanded": d2,
        "popVenue": d3,
        "popGaojiBoxes": d4,
        "popField": d5,
        "defaultExists": Path(default_path).exists(),
        "expandedExists": Path(expanded_path).exists(),
        "popVenueExists": Path(pop_venue_path).exists(),
        "popGaojiBoxesExists": Path(pop_boxes_gaoji_path).exists(),
        "popFieldExists": Path(pop_field_path).exists(),
    }
    (OUT / "review_capture.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
