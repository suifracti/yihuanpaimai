"""Exercise real history DOM edit/save/restart/export against isolated copied data."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import socket
import zipfile
import websockets
from verify_p1_real_ui import WS, eval_main
from verify_p3_isolated_real_app_history import run_one_launch


def verify(args):
    output = args.out_dir.resolve()
    source = args.source_data.resolve(strict=True)
    assert not output.exists() and source not in output.parents
    with socket.socket() as port:
        port.bind(('127.0.0.1', 8766))
    output.mkdir(parents=True)
    data = output / 'data'
    shutil.copytree(source, data)
    history = data / 'history/异环拍卖数据.json'
    shutil.copyfile(args.history, history)
    def record():
        return next(r for r in json.loads(history.read_text(encoding='utf-8'))['records'] if r['id'] == args.record_id)
    before = record()
    packet = before['settlement']['warehouseReviewPacket']
    uid = packet['reviewUnits'][0]['reviewUnitId']
    initial = before['settlement']['warehouseIdentityReview']
    was_confirmed = any(i['reviewUnitId'] == uid for i in initial['resolvedItems'])
    confirming = bool(args.confirm_catalog_id)
    assert not was_confirmed if confirming else was_confirmed
    expected = len(initial['resolvedItems']) + (1 if confirming else -1)
    action = 'CONFIRM_CATALOG_OVERRIDE' if args.override else ('CONFIRM_CANDIDATE' if confirming else 'DEFER')
    snapshots = []

    async def interact(zip_out, trigger_export):
        async with websockets.connect(WS) as connection:
            async def wait(expression):
                for _ in range(100):
                    if await eval_main(connection, expression):
                        return
                    await asyncio.sleep(.2)
                raise AssertionError('DOM condition did not become true: ' + expression)
            async def click(element):
                await wait(f"Boolean(document.getElementById('{element}') && !document.getElementById('{element}').hidden && !document.getElementById('{element}').disabled)")
                await eval_main(connection, f"document.getElementById('{element}').click(); true")
            await connection.send(json.dumps({'type': 'manual_bootstrap', 'action': 'manual_bootstrap'}))
            await eval_main(connection, "showView('history'); true")
            row = f"[...document.querySelectorAll('#history-list .history-item')].find(e => e.dataset.recordId === {json.dumps(args.record_id)})"
            await wait(f"Boolean({row})")
            await eval_main(connection, f"({row}).click(); true")
            await wait(f"dashboard.review?.recordId === {json.dumps(args.record_id)}")
            await click('history-warehouse-review-btn')
            await wait(f"dashboard.warehouseReview?.currentTrackId === {json.dumps(uid)} && dashboard.warehouseReview?.hasLegalEvidence")
            if trigger_export:
                if confirming:
                    await click('wir-undo')
                    await wait("!dashboard.warehouseReview?.draftAction")
                    selector = f"[data-candidate={json.dumps(args.confirm_catalog_id)}]"
                    await wait(f"Boolean(document.querySelector({json.dumps(selector)}))")
                    await eval_main(connection, f"document.querySelector({json.dumps(selector)}).click(); true")
                    await wait(f"dashboard.warehouseReview?.candidates?.some(c => c.selected && c.candidateId === {json.dumps(args.confirm_catalog_id)})")
                    await click('wir-confirm-candidate')
                    if args.override:
                        await wait("Boolean(document.querySelector('.wir-hit.is-selected'))")
                        await eval_main(connection, "document.getElementById('wir-override-reason').value='HUMAN_VISUAL_IDENTIFICATION'; true")
                        await click('wir-override')
                        await click('wir-override')
                else:
                    await click('wir-defer')
                await wait(f"dashboard.warehouseReview?.draftAction === {json.dumps(action)}")
                await click('wir-finalize')
                await wait("dashboard.warehouseReview?.artifactReady && dashboard.warehouseReview?.persistenceAvailable")
                await click('wir-save')
                await click('wir-save-confirm-btn')
                await wait("dashboard.warehouseReview?.persisted === true")
            else:
                await wait(f"dashboard.warehouseReview?.draftAction === {json.dumps(action)}")
            await wait(f"dashboard.review?.warehouseIdentitySummary?.resolvedCount === {expected}")
            await wait("Boolean(document.getElementById('history-warehouse-revisions')?.textContent.includes('修改前记录'))")
            result = await eval_main(connection, "JSON.stringify({action:dashboard.warehouseReview.draftAction,summary:dashboard.review.warehouseIdentitySummary,revisions:document.getElementById('history-warehouse-revisions').textContent})")
            if trigger_export:
                await eval_main(connection, f"document.getElementById('history-export-btn').dataset.outputPath = {json.dumps(str(zip_out))}; true")
                await click('history-export-btn')
                for _ in range(100):
                    if zip_out.exists():
                        break
                    await asyncio.sleep(.2)
                assert zip_out.exists()
            return json.loads(result) if isinstance(result, str) else result

    report = {'status': 'RUNNING', 'recordId': args.record_id, 'simulatedHumanAction': action, 'launches': snapshots}
    bundle = output / 'edited-match.zip'
    try:
        for n in (1, 2):
            dual, dom, clean = run_one_launch(f'history_edit_{n}', data, output / f'app-{n}.log', output,
                zip_out=bundle if n == 1 else None, trigger_export=n == 1, interactor=interact)
            snapshots.append({'dualLaunched': dual, 'cleanExit': clean, 'dom': dom})
            assert dual and clean
        assert snapshots[0]['dom'] == snapshots[1]['dom']
        after = record()
        assert after['lifecycleStatus'] == before['lifecycleStatus']
        assert after['settlement']['warehouseIdentityReviewHistory'][-1] == initial
        unit = next(u for u in after['settlement']['reviewUnits'] if u['reviewUnitId'] == uid)
        assert unit['selectedCatalogId'] == (args.confirm_catalog_id if confirming else None) and unit['confirmedByHuman'] is True
        with zipfile.ZipFile(bundle) as archive:
            for entry in json.loads(archive.read('manifest.json'))['files']:
                assert hashlib.sha256(archive.read(entry['path'])).hexdigest() == entry['sha256']
            exported = next(r for r in json.loads(archive.read('records.json'))['records'] if r['id'] == args.record_id)
            assert exported['settlement']['warehouseIdentityReview'] == after['settlement']['warehouseIdentityReview']
            assert exported['settlement']['warehouseIdentityReviewHistory'] == after['settlement']['warehouseIdentityReviewHistory']
        report.update(status='PASS', resolvedAfter=expected)
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-data', type=Path, required=True)
    parser.add_argument('--history', type=Path, required=True)
    parser.add_argument('--record-id', required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--confirm-catalog-id')
    parser.add_argument('--override', action='store_true')
    verify(parser.parse_args())
