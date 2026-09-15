"""Switch non-multiplier conditions in real Main/HUD; compare production snapshots."""
import argparse
import json
from pathlib import Path
import websockets
from verify_p1_real_ui import WS, eval_main, eval_overlay, wait_main_match, wait_overlay_payload
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
        fields = {'q': '1', 'gold-avg': '60040', 'gold-count': '1', 'purple-count': '0',
                  'red-count': '0', 'blue-count': '0', 'green-count': '0', 'white-count': '0',
                  'intel-cost': '1200', 'other-cost': '300', 'future-cost': '700', 'known-gold': '算力面包'}
        await eval_main(ws, '(()=>{for(const [key,value] of Object.entries('+json.dumps(fields, ensure_ascii=False)+')){const e=document.getElementById("match-input-"+key);e.focus();e.value=value;e.dispatchEvent(new Event("change",{bubbles:true}));}document.activeElement?.blur();return true})()')
        rows = []
        baseline = None
        for condition in ('standard', 'extraIntel', 'standard'):
            await eval_overlay(ws, 'document.getElementById("fieldChip").click();document.querySelector('+json.dumps('#popoverList .popover-item[data-val="'+condition+'"]')+').click();true')
            await wait_overlay_payload(ws, lambda d: (d.get('fieldCondition') or 'standard') == condition and d.get('intelCost') == 1200 and not d.get('shadowUpdating') and ((d.get('predictionSnapshot') or d.get('solverInput', {}).get('predictionSnapshot') or {}).get('status') or {}).get('solverStatus') == 'valid', timeout=30)
            await wait_main_match(ws, lambda d: d.get('facts', {}).get('fieldCondition') == condition and (d.get('prediction') or {}).get('solverStatus') == 'valid', timeout=20)
            payload = await eval_overlay(ws, 'JSON.stringify(manualState.latestNativePayload)')
            frozen = payload.get('frozenPrediction') or payload['solverInput']['frozenPrediction']
            snap = payload.get('predictionSnapshot') or payload['solverInput']['predictionSnapshot']
            value = {'forecast': snap['forecast'], 'costInfo': frozen['costInfo'],
                     'estimate': frozen['estimate'], 'globalLine': frozen['globalLine'], 'marginalLine': frozen['marginalLine']}
            if baseline is None:
                baseline = value
            assert value == baseline, (condition, value, baseline)
            assert value['costInfo']['allCosts'] == 7200, value
            main = await eval_main(ws, 'JSON.stringify({p50:document.getElementById("match-live-p50").textContent,cost:document.getElementById("match-cost-summary").textContent})')
            if rows:
                assert main == rows[0]['main'], (condition, main)
            hint_main = await eval_main(ws, 'JSON.stringify({hidden:document.getElementById("match-free-intel-status").hidden,text:document.getElementById("match-free-intel-status").textContent})')
            hint_hud = await eval_overlay(ws, 'JSON.stringify({hidden:document.getElementById("freeIntelStatus").hidden,text:document.getElementById("freeIntelStatus").textContent})')
            assert hint_main == hint_hud, (hint_main,hint_hud)
            assert hint_main['hidden'] == (condition != 'extraIntel')
            if condition == 'extraIntel':
                assert '回合待识别' in hint_main['text'], hint_main
                assert payload['freeIntelStatus']['observed'] is False
            rows.append({'condition': condition, 'value': value, 'main': main, 'hint':hint_main})
            (out/'observations.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        return rows

try:
    dual, rows, clean = run_one_launch('conditions', data, out/'app.log', out, interactor=interact, frozen_executable=a.executable)
    assert dual and clean
    report.update(status='PASS', rows=rows)
except Exception as exc:
    report.update(status='FAIL', error=repr(exc))
    raise
finally:
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
