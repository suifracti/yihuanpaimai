"""Exercise the reported manual match through the packaged WebView and archive."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

import websockets
from manual_advice_smoke import start, stop, recv_until, decode_script_result


async def flow():
    async with websockets.connect("ws://127.0.0.1:8766") as socket:
        await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
        boot = await recv_until(socket, lambda r: r.get("type") == "manual_alpha_state")
        mid = boot["matchId"]
        assert boot['recognitionMode'] == 'manual', boot
        await socket.send(json.dumps({'type':'manual_facts','action':'manual_facts','facts':{'recognitionMode':'auto'}}))
        await recv_until(socket, lambda r: r.get('type') == 'manual_alpha_state' and r.get('recognitionMode') == 'auto')
        await socket.send(json.dumps({'type':'eval_overlay_js','action':'eval_overlay_js','script':"document.getElementById('recognitionModeBtn').click(); 'clicked'"}))
        await recv_until(socket, lambda r: r.get('type') == 'manual_alpha_state' and r.get('recognitionMode') == 'manual')
        await socket.send(json.dumps({'type':'eval_overlay_js','action':'eval_overlay_js','script':'manualState.liveVisionActive = true; true'}))
        await recv_until(socket, lambda r: r.get('type') == 'overlay_js_result')
        facts = {"venueId": "venue-shanhu", "boxId": "box-shanhu-mother-of-pearl", "fieldCondition": "standard", "q": 27,
                 "goldAvg": 35280, "purpleCount": 15, "knownGold": "101554+60285",
                 "knownPurple": "5955+3675"}
        await socket.send(json.dumps({"type": "manual_facts", "action": "manual_facts", "facts": facts}))
        await recv_until(socket, lambda r: r.get("matchId") == mid and r.get("q") == 27)
        deadline = time.monotonic() + 45
        result = None
        while time.monotonic() < deadline:
            script = """JSON.stringify((()=>{const d=manualState.latestNativePayload||{};const r=manualState.latestEngineResult||{};const s=d.predictionSnapshot||d.solverInput?.predictionSnapshot||r.predictionSnapshot;return {snapshot:s,display:document.getElementById('p50Label').textContent};})())"""
            await socket.send(json.dumps({"type": "eval_overlay_js", "action": "eval_overlay_js", "script": script}))
            response = await recv_until(socket, lambda r: r.get("type") == "overlay_js_result", timeout=10)
            result = decode_script_result(response.get("result"))
            normalized = ((result or {}).get("snapshot") or {}).get("input", {}).get("normalizedFacts", {})
            known = normalized.get("knownItems") or {}
            if normalized.get("knownGold") == facts["knownGold"] or known.get("knownGold") == facts["knownGold"]:
                break
            await asyncio.sleep(.25)
        assert result and result.get("snapshot"), result
        normalized = result["snapshot"]["input"]["normalizedFacts"]
        assert facts["knownGold"] in json.dumps(normalized), normalized
        assert result["display"] == "整仓待补全", result
        # Submit the actual UI immediately after the result appears; do not wait
        # for its deferred facts sync to win a race with settlement.
        await socket.send(json.dumps({"type": "eval_overlay_js", "action": "eval_overlay_js",
            "script": "document.getElementById('terminalClearingPrice').value='666666';"
            "document.getElementById('terminalActualTotal').value='1072197';"
            "document.getElementById('terminalAcquired').value='false';"
            "document.getElementById('terminalWinner').value='SmokeWinner';submitSettlement();true"}))
        final = await recv_until(socket, lambda r: bool(r.get("terminalResult")), timeout=40)
        assert final["terminalResult"]["status"] == "FINALIZED", final
        return {"matchId": mid, "display": result["display"], "knownInputsPreserved": True, "recognitionModeRoundtrip": True}


def main():
    exe = Path(sys.argv[1]).resolve()
    root = Path(sys.argv[2]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    data = root / 'data'
    env = {**os.environ, "YIHUAN_DATA_ROOT": str(data), "LOCALAPPDATA": str(root/'local'),
        "NTE_DISABLE_VISION": "1", "NTE_DISABLE_ICON": "1", "NTE_MAIN_UI_SMOKE": "1",
        "NTE_ALLOW_HUD_CAPTURE": "1", "NTE_LOG_FILE": str(root/'app.log')}
    proc, probe, window, _ = start([str(exe)], env, root/'app.log')
    try:
        result = asyncio.run(flow())
        records = json.loads((data/'history/异环拍卖数据.json').read_text(encoding='utf-8'))['records']
        record = next(r for r in records if r['id'] == result['matchId'])
        assert record['settlement']['actualTotal'] == 1072197
        assert record['predictionSnapshot']['matchId'] == result['matchId']
        assert '101554+60285' in json.dumps(record['predictionSnapshot']['input']['normalizedFacts'])
        result['archivePreservedKnownInputs'] = True
        (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
    finally:
        stop(proc, probe, window)


if __name__ == '__main__':
    main()
