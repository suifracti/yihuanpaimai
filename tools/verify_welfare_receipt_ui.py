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
        await eval_overlay(ws, 'document.getElementById("fieldChip").click();document.querySelector("#popoverList .popover-item[data-val=welfare]").click();true')
        await wait_main_match(ws, lambda d: d.get('facts', {}).get('fieldCondition') == 'welfare')
        rows = []
        for surface, value in [('main', '3000'), ('hud', '0'), ('main', ''), ('main', '2500')]:
            evaluate = eval_main if surface == 'main' else eval_overlay
            ident = 'match-input-welfare-received' if surface == 'main' else 'welfareReceivedInput'
            await evaluate(ws, '(()=>{const e=document.getElementById('+json.dumps(ident)+');e.focus();e.value='+json.dumps(value)+';e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));e.dispatchEvent(new FocusEvent("blur"));e.blur();return true})()')
            expected = int(value) if value else None
            await wait_main_match(ws, lambda d:d.get('facts',{}).get('welfareReceived') == expected and (d.get('sessionAccounting') or {}).get('welfareReceived') == expected, timeout=20)
            await wait_overlay_payload(ws, lambda d:d.get('welfareReceived') == expected and (d.get('sessionAccounting') or {}).get('welfareReceived') == expected, timeout=20)
            main = await eval_main(ws, 'JSON.stringify({input:document.getElementById("match-input-welfare-received").value,text:document.getElementById("match-session-accounting").textContent})')
            hud = await eval_overlay(ws, 'JSON.stringify({input:document.getElementById("welfareReceivedInput").value,text:document.getElementById("sessionAccounting").textContent})')
            for view in (main,hud):
                assert view['input'] == value, view
                assert '净收益 未知' in view['text'], view
            rows.append({'surface':surface,'value':value,'main':main,'hud':hud})
            (out/'observations.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        for surface in ('main', 'hud'):
            evaluate = eval_main if surface == 'main' else eval_overlay
            ident = 'match-input-welfare-received' if surface == 'main' else 'welfareReceivedInput'
            error_id = 'match-welfare-error' if surface == 'main' else 'welfareError'
            for invalid in ('1.9', '-1', '1e3', '9007199254740992'):
                await evaluate(ws, '(()=>{const e=document.getElementById('+json.dumps(ident)+');e.focus();e.value='+json.dumps(invalid)+';e.dispatchEvent(new Event("change",{bubbles:true}));e.dispatchEvent(new FocusEvent("blur"));e.blur();return true})()')
                await asyncio.sleep(.6)
                error = await evaluate(ws, 'document.getElementById('+json.dumps(error_id)+').textContent')
                assert '尚未保存' in error, error
                await wait_main_match(ws, lambda d:d.get('facts',{}).get('welfareReceived') == 2500)
                actual = (await evaluate(ws, 'JSON.stringify({value:document.getElementById('+json.dumps(ident)+').value})'))['value']
                assert actual == invalid, (surface, invalid, actual, error)
            await evaluate(ws, '(()=>{const e=document.getElementById('+json.dumps(ident)+');e.focus();e.value="2500";e.dispatchEvent(new Event("change",{bubbles:true}));e.dispatchEvent(new FocusEvent("blur"));e.blur();return true})()')
            await asyncio.sleep(.6)
            assert await evaluate(ws, 'document.getElementById('+json.dumps(error_id)+').textContent') == ''
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
        text = await eval_main(ws, 'document.getElementById("detail-session-accounting").textContent')
        assert '福利实收 2,500' in text and '净收益 未知' in text, text
        return text

try:
    dual, rows, clean = run_one_launch('sparkle-evidence', data, out/'app.log', out, interactor=interact, frozen_executable=a.executable)
    assert dual and clean
    saved = json.loads(history.read_text(encoding='utf-8'))['records']
    assert any(r.get('settlement', {}).get('welfare', {}).get('received') == 2500 for r in saved), saved
    dual2, text, clean2 = run_one_launch('reopen', data, out/'reopen.log', out, interactor=reopen, frozen_executable=a.executable)
    assert dual2 and clean2
    report.update(status='PASS', rows=rows, saved=True, historyText=text)
except Exception as exc:
    report.update(status='FAIL', error=repr(exc))
    raise
finally:
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
