"""Read an actual ownership replay record in isolated Main/HUD, then restart."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import socket

import websockets
from verify_p1_real_ui import WS, eval_main
from verify_p3_isolated_real_app_history import run_one_launch


def verify(args):
    source = args.source_data.resolve(strict=True)
    history = args.history.resolve(strict=True)
    original = history.read_bytes()
    record = next(r for r in json.loads(original)['records'] if r['id'] == args.record_id)
    assert record['settlement']['acquired'] is False
    output = args.out_dir.resolve()
    if output.exists() or source == output or source in output.parents:
        raise ValueError('Use a fresh output outside source data')
    with socket.socket() as port:
        port.bind(('127.0.0.1', 8766))
    output.mkdir(parents=True)
    data = output / 'data'
    shutil.copytree(source, data)
    target = data / 'history/异环拍卖数据.json'
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(original)

    async def interact(_zip, _export):
        async with websockets.connect(WS) as connection:
            await connection.send(json.dumps({'type': 'manual_bootstrap', 'action': 'manual_bootstrap'}))
            await asyncio.sleep(.5)
            await eval_main(connection, "showView('history'); dashboard.currentView")
            for _ in range(60):
                found = await eval_main(connection, f"""(() => {{
                    const row = [...document.querySelectorAll('#history-list .history-item')]
                        .find(el => el.getAttribute('data-record-id') === {json.dumps(args.record_id)});
                    if (!row) return false;
                    if (dashboard.selectedRecordId !== {json.dumps(args.record_id)}) row.click();
                    return true;
                }})()""")
                if found:
                    break
                await asyncio.sleep(.2)
            assert found, 'Missing history row'
            for _ in range(60):
                dom = await eval_main(connection, """JSON.stringify({
                    profit: document.getElementById('detail-profit').textContent,
                    owner: document.getElementById('detail-acquired').textContent,
                    label: document.getElementById('detail-profit').parentElement.querySelector('.field-label').textContent,
                    reviewProfit: document.getElementById('review-profit').textContent,
                    reviewHidden: document.getElementById('detail-review-section').hidden,
                    reviewId: dashboard.review?.recordId,
                    reviewAcquired: dashboard.review?.settlement?.acquired
                })""")
                if dom.get('profit') == '他人拍下（非本人收益）':
                    break
                await asyncio.sleep(.2)
            assert dom['profit'] == '他人拍下（非本人收益）', dom
            assert dom['owner'] == '他人拍下 · ' + record['settlement']['winner'], dom
            assert dom['label'] == '结算账面收益', dom
            if not dom['reviewHidden']:
                assert dom.get('reviewId') == args.record_id, dom
                assert dom['reviewProfit'] == '他人拍下（非本人收益）', dom
                assert dom['reviewAcquired'] is False, dom
            # Synthetic formatting boundaries, explicitly separate from the real replay.
            boundaries = await eval_main(connection, """JSON.stringify([
                {acquired:true,realizedProfit:1}, {acquired:true,realizedProfit:0},
                {acquired:true,realizedProfit:-1}, {acquired:null,realizedProfit:333902},
                {acquired:'true',realizedProfit:333902}
            ].map(formatSettlementProfit))""")
            assert boundaries == ['+1', '0', '-1', '归属未知', '归属未知'], boundaries
            return {'dom': dom, 'syntheticFormattingBoundaries': boundaries}

    report = {'recordId': args.record_id, 'status': 'RUNNING', 'launches': []}
    try:
        for number in (1, 2):
            dual, result, clean = run_one_launch(f'ownership_{number}', data,
                output / f'app-{number}.log', output, interactor=interact)
            report['launches'].append({'dualLaunched': dual, 'cleanExit': clean, **result})
            assert dual and clean
            print(f'Launch {number}: ownership and profit DOM PASS', flush=True)
        assert report['launches'][0] == report['launches'][1]
        saved = next(r for r in json.loads(target.read_bytes())['records'] if r['id'] == args.record_id)
        assert saved['settlement'] == record['settlement']
        assert history.read_bytes() == original
        report.update(status='PASS', sourceSha256=hashlib.sha256(original).hexdigest())
    except Exception as exc:
        report.update(status='FAIL', error=repr(exc))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-data', type=Path, required=True)
    parser.add_argument('--history', type=Path, required=True)
    parser.add_argument('--record-id', required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    verify(parser.parse_args())
