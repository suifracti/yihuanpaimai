"""Actual native health transport and Main/HUD DOM; injected events, no OCR claim."""
import argparse
import asyncio
import json
from pathlib import Path
import websockets
from verify_p1_real_ui import WS, eval_main, eval_overlay, wait_main_match
from verify_p3_isolated_real_app_history import run_one_launch


async def interact(_zip, _export):
    rows = []
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({'type': 'vision_worker_hello'}))
        await eval_main(ws, "showView('match'); true")
        await eval_overlay(ws, 'setOverlayExpanded(true); true')
        for status in ('ERROR', 'WAITING', 'ERROR', 'READY'):
            await ws.send(json.dumps({'type': 'vision_health', 'visionHealth': {'status': status, 'stage': 'recognition'}}))
            await wait_main_match(ws, lambda d: d.get('visionHealth', {}).get('status') == status)
            await asyncio.sleep(.2)
            result = {}
            for target, fn, element in [('main', eval_main, 'vision-health-status'), ('hud', eval_overlay, 'visionHealthStatus')]:
                result[target] = await fn(ws, "JSON.stringify((()=>{const el=document.getElementById("+json.dumps(element)+");return {hidden:el.hidden,text:el.textContent};})())")
                assert result[target]['hidden'] == (status != 'ERROR'), result
                if status == 'ERROR':
                    assert '上次结果' in result[target]['text']
                else:
                    assert result[target]['text'] == ''
            rows.append(result)
            await eval_overlay(ws, 'setOverlayExpanded(false); true')
            compact = await eval_overlay(ws, "JSON.stringify((()=>{const el=document.getElementById('topVisionHealth');const rect=el.getBoundingClientRect();return {hidden:el.hidden,visible:rect.width>0&&rect.height>0&&rect.top>=0&&rect.bottom<=window.innerHeight,caption:document.getElementById('valuationCaption').textContent};})())")
            assert compact['hidden'] == (status != 'ERROR'), compact
            assert compact['visible'] == (status == 'ERROR'), compact
            assert compact['caption'] == ('上次估值' if status == 'ERROR' else '估值 (P50)'), compact
            result['compactHud'] = compact
            await eval_overlay(ws, 'setOverlayExpanded(true); true')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--executable', type=Path)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    data = out/'data'; history = data/'history/异环拍卖数据.json'; history.parent.mkdir(parents=True)
    history.write_text(json.dumps({'schemaVersion':7,'records':[]}),encoding='utf-8')
    report = {'status':'RUNNING'}
    try:
        dual, rows, clean = run_one_launch('health', data, out/'app.log', out, interactor=interact,
                                          frozen_executable=args.executable)
        assert dual and clean
        report.update(status='PASS', dualLaunched=dual, cleanExit=clean, injectedHealthEvents=rows)
    except Exception as exc:
        report.update(status='FAIL', error=repr(exc)); raise
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
