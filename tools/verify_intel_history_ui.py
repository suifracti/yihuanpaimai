"""Exercise synthetic saved intel evidence through actual Main/HUD app processes."""
import argparse
import asyncio
import json
import hashlib
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
data = out / 'data'
history = data / 'history/异环拍卖数据.json'
history.parent.mkdir(parents=True)
source = {'field': 'goldCount', 'frameId': 'synthetic-frame-1',
          'rawText': '金色藏品总数量2 <img src=x onerror=alert(1)>'}
cases = [
    ('missing', None, '未记录情报识别证据'),
    ('tentative', {'version': 1, 'facts': {'goldCount': {'status': 'UNKNOWN', 'tentative': 2}}, 'observations': [source]}, '待确认 2'),
    ('confirmed', {'version': 1, 'facts': {'goldCount': {'status': 'OBSERVED', 'value': 2, 'sources': [source, {**source, 'frameId': 'synthetic-frame-2'}]}}}, '识别已确认 2'),
    ('conflict', {'version': 1, 'facts': {'goldCount': {'status': 'CONFLICT', 'candidates': [2, 3], 'sources': [source]}}}, '存在冲突；候选 2 / 3'),
    ('future', {'version': 2}, '情报证据版本暂不支持回看'),
    ('non-numeric', {'version': 1, 'cardReadings': [{'frameId': 'synthetic-random-card', 'rawText': '拍卖师公开情报 随机展示2件藏品', 'is_physical_ocr': True}]}, '卡片原文（公开情报标题，本次识别，不作为新增事实）：拍卖师公开情报 随机展示2件藏品'),
]
event_text = '拍卖师公开情报 随机展示2件藏品'
event = {'id': 'public-card:' + hashlib.sha256(event_text.replace(' ', '').encode('utf-8')).hexdigest(),
         'status': 'CONFIRMED_CONTENT', 'roundObserved': 1, 'rawText': event_text,
         'sources': [{'frameId': 'synthetic-event-' + str(i), 'round': 1,
                      'rawText': event_text, 'is_physical_ocr': True} for i in (1, 2)]}
cases.append(('public-event', {'version': 1, 'publicCardEvents': [event, event]}, '第1回合两次识别一致的公开内容'))
records = [{'id': 'synthetic-intel-' + ident, 'schemaVersion': 7,
            'source': 'synthetic-intel-ui-test', 'collectionClass': 'SYNTHETIC_TEST',
            'lifecycleStatus': 'DRAFT', 'playedAt': '2026-09-13T00:00:00+08:00',
            'environment': {'venue': '珊瑚场', 'fieldCondition': 'extraIntel'},
            'costs': {'entry': 0, 'intel': 1200, 'other': 0},
            'intelCardEvidence': evidence}
           for ident, evidence, _ in cases]
history.write_text(json.dumps({'schemaVersion': 7, 'records': records}, ensure_ascii=False), encoding='utf-8')
report = {'status': 'RUNNING', 'evidenceClass': 'SYNTHETIC_UI_TEST'}

async def interact(*_):
    async with websockets.connect(WS) as ws:
        await eval_main(ws, "showView('history');true")
        rows = []
        for ident, evidence, expected in cases + cases[:1]:
            selector = '[data-record-id="synthetic-intel-' + ident + '"].history-item'
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                clicked = await eval_main(ws, '(()=>{const e=document.querySelector(' + json.dumps(selector) + ');if(!e)return false;e.click();return true})()')
                if clicked:
                    break
                await asyncio.sleep(.2)
            assert clicked, ident
            result = await eval_main(ws, '(()=>{const e=document.getElementById("detail-intel-evidence");e.scrollIntoView();return JSON.stringify({text:e.textContent,images:e.querySelectorAll("img").length,visible:e.getBoundingClientRect().height>0})})()')
            assert expected in result['text'], (ident, result)
            assert result['visible'] and result['images'] == 0, result
            if ident in ('tentative', 'confirmed', 'conflict'):
                assert source['rawText'] in result['text'] and '免费／付费来源未确认' in result['text'], result
            if ident == 'confirmed':
                assert '记录来源 2 帧' in result['text'], result
            if ident == 'public-event':
                assert result['text'].count('两次识别一致的公开内容') == 1, result
            rows.append({'case': ident, **result})
        return rows

try:
    dual, rows, clean = run_one_launch('intel-history', data, out/'app.log', out, interactor=interact, frozen_executable=a.executable)
    assert dual and clean
    report.update(status='PASS', rows=rows)
except Exception as exc:
    report.update(status='FAIL', error=repr(exc))
    raise
finally:
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
