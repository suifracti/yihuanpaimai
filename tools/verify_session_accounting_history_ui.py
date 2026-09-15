"""Synthetic accounting fixtures viewed via real frozen history UI, not game evidence."""
import argparse
import asyncio
import json
import time
from pathlib import Path
import websockets
from verify_p1_real_ui import WS, eval_main
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
cases = [
    ('own', True, 5000, 3000, 60040, 700, '16,540'),
    ('other', False, 5000, 3000, 60040, 700, '-3,500'),
    ('unknown-owner', None, 5000, 3000, 60040, 700, '未知'),
    ('unknown-entry', True, None, 3000, 60040, 700, '未知'),
    ('zero-entry', True, 0, 3000, 60040, 700, '21,540'),
    ('zero-receipt', True, 5000, 0, 60040, 700, '13,540'),
    ('unknown-receipt', True, 5000, None, 60040, 700, '未知'),
    ('future-not-paid', True, 5000, 3000, 60040, 99999, '16,540'),
    ('one-profit', True, 5000, 3000, 43501, 700, '1'),
]
records = []
for ident, acquired, entry, receipt, actual, future, expected in cases:
    records.append({'id': 'synthetic-accounting-'+ident, 'schemaVersion': 7,
        'source': 'synthetic-accounting-ui-test', 'collectionClass': 'SYNTHETIC_TEST',
        'lifecycleStatus': 'DRAFT', 'playedAt': '2026-09-13T00:00:00+08:00',
        'environment': {'venue': '珊瑚场', 'fieldCondition': 'welfare'},
        'costs': {'entry': entry, 'intel': 1200, 'other': 300, 'futureIncrementalCost': future},
        'settlement': {'status': 'pending', 'acquired': acquired, 'actualTotal': actual,
            'clearingPrice': 40000, 'realizedProfit': 999999,
            'welfare': {'received': receipt, 'expected': 90000}}})
history.write_text(json.dumps({'schemaVersion': 7, 'records': records}, ensure_ascii=False), encoding='utf-8')
report = {'status': 'RUNNING', 'evidenceClass': 'SYNTHETIC_UI_TEST'}

async def interact(*_):
    async with websockets.connect(WS) as ws:
        await eval_main(ws, "showView('history');true")
        rows = []
        for ident, _, _, _, _, _, expected in cases:
            deadline = time.monotonic()+15
            clicked = False
            selector = '[data-record-id="synthetic-accounting-'+ident+'"].history-item'
            while time.monotonic() < deadline:
                clicked = await eval_main(ws, '(()=>{const e=document.querySelector('+json.dumps(selector)+');if(!e)return false;e.click();return true})()')
                if clicked:
                    break
                await asyncio.sleep(.2)
            assert clicked, ident
            value = await eval_main(ws, 'JSON.stringify({text:document.getElementById("detail-session-accounting").textContent})')
            text = value['text']
            displayed = text.split('按结算价值计净收益 ', 1)[1].split('（', 1)[0].split('；', 1)[0]
            assert displayed == expected, (ident, text, expected)
            rows.append({'case': ident, 'expected': expected, 'display': text})
        return rows

try:
    dual, rows, clean = run_one_launch('accounting-history', data, out/'app.log', out, interactor=interact, frozen_executable=a.executable)
    assert dual and clean
    report.update(status='PASS', rows=rows)
except Exception as exc:
    report.update(status='FAIL', error=repr(exc))
    raise
finally:
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
