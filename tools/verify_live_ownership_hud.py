"""Verify host ownership projection and real HUD DOM, separately from OCR accuracy."""
import argparse
import asyncio
import json
import os
from pathlib import Path

import websockets
from verify_p1_real_ui import WS, eval_overlay, eval_main, wait_main_match, wait_overlay_payload
from verify_p3_isolated_real_app_history import run_one_launch


def verify(args):
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    data = output / 'data'
    history = data / 'history/异环拍卖数据.json'
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps({'schemaVersion': 2, 'records': []}), encoding='utf-8')
    local_root = output / 'default-local' if args.trial_default else None
    if local_root:
        data = local_root / '异环拍卖助手试用/data'
        daily_history = local_root / '异环拍卖助手/data/history/异环拍卖数据.json'
        daily_history.parent.mkdir(parents=True)
        daily_bytes = json.dumps({'records': [{'id': 'daily-sentinel'}]}).encode()
        daily_history.write_bytes(daily_bytes)
        daily_pet = local_root / '异环拍卖助手/desktop_pet_state_v1.json'
        daily_pet.write_bytes(b'{"trialSentinel":true}')
    os.environ['YIHUAN_DATA_ROOT'] = str(output / 'projection-data')
    import main

    context = json.loads(args.context.read_text(encoding='utf-8'))
    assert context['isAcquired'] is False
    cases = []
    for value in (False, True, None, 'true', 1):
        ctx = dict(context, isAcquired=value)
        payload = main.build_in_auction_hud_payload(ctx, compute_shadow=False)
        expected = value if type(value) is bool else None
        assert payload['isAcquired'] is expected
        cases.append((payload, '本人拍下' if expected is True else '他人拍下' if expected is False else '归属未知'))
    nav = main.build_nav_hud_payload({'scene': 'OPEN_WORLD'})
    launch_number = 0

    async def interact(_zip, _export):
        rows = []
        async with websockets.connect(WS) as ws:
            await ws.send(json.dumps({'type': 'manual_bootstrap', 'action': 'manual_bootstrap'}))
            await asyncio.sleep(.5)
            await eval_main(ws, "showView('match'); true")
            if launch_number == 1:
                await eval_main(ws, "{const el=document.getElementById('player-display-name');el.focus();el.value='PLAYER_LOCAL';document.getElementById('save-player-display-name').click();true}")
                receipt = await wait_overlay_payload(ws, lambda d: d.get('configuredPlayerName') == 'PLAYER_LOCAL')
            current = await wait_main_match(ws, lambda d: d.get('configuredPlayerName') == 'PLAYER_LOCAL')
            if local_root:
                assert current.get('isolatedTrial') is True
                assert await eval_main(ws, "!document.getElementById('isolated-trial-label').hidden")
            status = await eval_main(ws, "document.getElementById('player-display-name-status').textContent")
            assert '已保存：PLAYER_LOCAL' in status, status
            await eval_overlay(ws, 'setOverlayExpanded(true); true')
            for payload, label in cases + [(nav, '')]:
                result = await eval_overlay(ws, """JSON.stringify((() => {
                    paintResult(PAYLOAD);
                    const el = document.getElementById('currentOwnership');
                    return {text:el.textContent, hidden:el.hidden};
                })())""".replace('PAYLOAD', json.dumps(payload, ensure_ascii=False)))
                assert result['hidden'] == (not label), result
                assert result['text'].startswith(label), result
                if not label:
                    assert result['text'] == ''
                rows.append(result)
            if launch_number == 2:
                await eval_main(ws, "{const el=document.getElementById('player-display-name');el.focus();el.value='';document.getElementById('save-player-display-name').click();true}")
                await wait_overlay_payload(ws, lambda d: d.get('configuredPlayerName') == '')
                await wait_main_match(ws, lambda d: d.get('configuredPlayerName') == '')
        return rows

    report = {'status': 'RUNNING', 'scope': 'Actual replay context host projection and real HUD DOM; other branches synthetic, no OCR run'}
    try:
        report['launches'] = []
        for launch_number in (1, 2):
            dual, rows, clean = run_one_launch(f'live_ownership_{launch_number}', data,
                                              output / f'app-{launch_number}.log', output,
                                              interactor=interact, frozen_executable=args.executable,
                                              default_data_local_root=local_root)
            assert dual and clean
            report['launches'].append({'dualLaunched': dual, 'cleanExit': clean, 'cases': rows})
            saved = json.loads((data / 'state/player-identity.json').read_text(encoding='utf-8'))
            assert saved['displayName'] == ('PLAYER_LOCAL' if launch_number == 1 else '')
            if local_root:
                assert daily_history.read_bytes() == daily_bytes
                assert daily_pet.read_bytes() == b'{"trialSentinel":true}'
                assert (data / 'state/desktop_pet_state_v1.json').is_file()
                trial_history = json.loads((data / 'history/异环拍卖数据.json').read_text(encoding='utf-8'))
                assert all(r['id'] != 'daily-sentinel' for r in trial_history['records'])
        report.update(status='PASS', namePreference='native save, process restart readback, native clear and disk readback')
    except Exception as exc:
        report.update(status='FAIL', error=repr(exc))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--trial-default', action='store_true', help='Do not override data root; verify packaged trial defaults')
    verify(parser.parse_args())
