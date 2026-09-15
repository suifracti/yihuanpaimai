"""Actual Main/HUD DOM edits, production bounds and saved evidence in isolation."""
import argparse
import asyncio
import json
import time
from pathlib import Path
import websockets
from verify_p1_real_ui import WS, eval_main, eval_overlay, wait_main_match, wait_overlay_payload, recv_until
from verify_p3_isolated_real_app_history import run_one_launch

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
p.add_argument('--executable', type=Path)
a = p.parse_args()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
data = out/'data'
history = data/'history/异环拍卖数据.json'
history.parent.mkdir(parents=True)
history.write_text('{"schemaVersion":7,"records":[]}', encoding='utf-8')
report = {'status': 'RUNNING'}

async def interact(*_):
    async with websockets.connect(WS) as ws:
        await eval_main(ws, "showView('match');true")
        await wait_main_match(ws, lambda d: bool(d.get('matchId')))
        await eval_overlay(ws, 'document.getElementById("toggleBtn").click();document.getElementById("venueChip").click();[...document.querySelectorAll("#popoverList .popover-item")].find(e=>e.textContent.includes("珊瑚")).click();true')
        await wait_overlay_payload(ws, lambda d: d.get('venueId') == 'venue-shanhu')
        await eval_overlay(ws, 'document.getElementById("boxChip").click();[...document.querySelectorAll("#popoverList .popover-item")].find(e=>e.textContent.includes("琉璃")).click();true')
        await wait_overlay_payload(ws, lambda d: d.get('boxId') == 'box-shanhu-glass')
        await eval_overlay(ws, 'document.getElementById("fieldChip").click();document.querySelector("#popoverList .popover-item[data-val=sparkle]").click();true')
        await wait_main_match(ws, lambda d: d.get('facts', {}).get('fieldCondition') == 'sparkle')
        rows = []
        for surface, count, names, status, lower, upper in (
            ('main', '2', '泪滴', 'valid', 50099, 1364520),
            ('hud', '1', '泪滴*2', 'invalid', None, None),
            ('hud', '0', '', 'valid', 0, 0),
            ('main', '', '', 'valid', 0, None),
            ('main', '', '泪滴', 'valid', 50000, None),
        ):
            evaluate = eval_main if surface == 'main' else eval_overlay
            ids = ['match-sparkle-count', 'match-sparkle-names'] if surface == 'main' else ['sparkleCountInput', 'sparkleNamesInput']
            await evaluate(ws, '(()=>{for(const [id,value] of '+json.dumps(list(zip(ids, [count, names])), ensure_ascii=False)+'){const e=document.getElementById(id);e.closest("details").open=true;e.focus();e.value=value;e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));e.dispatchEvent(new FocusEvent("blur"));}document.activeElement?.blur();return true})()')
            expected = None if not count and not names else {'transformedOneByOneCount': count or None, 'verifiedGemItems': names}
            await wait_main_match(ws, lambda d: d.get('facts', {}).get('sparkle') == expected and (d.get('prediction') or {}).get('evidenceBounds', {}).get('status') == status and (d.get('prediction') or {}).get('evidenceBounds', {}).get('lower') == lower and (d.get('prediction') or {}).get('evidenceBounds', {}).get('upper') == upper, timeout=30)
            await wait_overlay_payload(ws, lambda d: d.get('sparkle') == expected and not d.get('shadowUpdating') and ((d.get('predictionSnapshot') or d.get('solverInput', {}).get('predictionSnapshot') or {}).get('evidenceBounds') or {}).get('status') == status, timeout=30)
            main = await eval_main(ws, 'JSON.stringify({count:document.getElementById("match-sparkle-count").value,names:document.getElementById("match-sparkle-names").value,text:document.getElementById("match-sparkle-bounds").textContent})')
            hud = await eval_overlay(ws, 'JSON.stringify({count:document.getElementById("sparkleCountInput").value,names:document.getElementById("sparkleNamesInput").value,text:document.getElementById("sparkleBounds").textContent})')
            for view in (main, hud):
                assert (view['count'], view['names']) == (count, names), view
                assert ('证据待核对' if status == 'invalid' else '仅转换宝石') in view['text'], view
            rows.append({'surface': surface, 'evidence': expected, 'main': main, 'hud': hud})
            (out/'observations.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        await eval_overlay(ws, 'document.getElementById("sparkleFields").open=true;document.getElementById("sparkleBounds").scrollIntoView({block:"nearest"});true')
        await ws.send(json.dumps({'type': 'capture_overlay_preview', 'path': str(out/'sparkle.png')}))
        shot = await recv_until(ws, lambda r: r.get('type') == 'overlay_preview_saved')
        assert shot.get('path')
        for condition in ('standard', 'sparkle'):
            await eval_overlay(ws, 'document.getElementById("fieldChip").click();document.querySelector('+json.dumps('#popoverList .popover-item[data-val="'+condition+'"]')+').click();true')
            await wait_main_match(ws, lambda d: d.get('facts', {}).get('fieldCondition') == condition)
            await wait_overlay_payload(ws, lambda d: d.get('fieldCondition') == condition)
            assert await eval_main(ws, 'document.getElementById("match-sparkle-fields").hidden') == (condition != 'sparkle')
            assert await eval_overlay(ws, 'document.getElementById("sparkleFields").hidden') == (condition != 'sparkle')
        return rows

async def reopen(*_):
    async with websockets.connect(WS) as ws:
        await eval_main(ws, "showView('history');true")
        deadline = time.monotonic() + 15
        clicked = False
        while time.monotonic() < deadline:
            clicked = await eval_main(ws, '(()=>{const e=document.querySelector(".history-item[data-record-id]");if(!e)return false;e.click();return true})()')
            if clicked:
                break
            await asyncio.sleep(.25)
        assert clicked, 'saved history absent'
        text = await eval_main(ws, 'document.getElementById("detail-sparkle").textContent')
        assert text == '转换宝石总数：未知；已确认：泪滴', text
        return text

try:
    dual, rows, clean = run_one_launch('sparkle-evidence', data, out/'app.log', out, interactor=interact, frozen_executable=a.executable)
    assert dual and clean
    saved = json.loads(history.read_text(encoding='utf-8'))['records']
    assert any(r.get('sparkle') == {'transformedOneByOneCount': None, 'verifiedGemItems': '泪滴'} for r in saved), saved
    dual2, text, clean2 = run_one_launch('reopen', data, out/'reopen.log', out, interactor=reopen, frozen_executable=a.executable)
    assert dual2 and clean2
    report.update(status='PASS', rows=rows, saved=True, historyText=text)
except Exception as exc:
    report.update(status='FAIL', error=repr(exc))
    raise
finally:
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
