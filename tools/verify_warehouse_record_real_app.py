"""Verify an isolated persisted warehouse record in real Main/HUD processes.

Copies caller-selected data into a fresh directory, clicks the history row,
checks every rendered item and saved coverage, exports via the real DOM button,
then closes/restarts the app and checks the same record again. Does not assert
that recording or recognition was complete; expected counts/coverage are explicit.
"""
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


FIELDS = ('reviewUnitId', 'selectedCatalogId', 'canonicalName', 'confirmationStatus', 'cropSha256')


def unit_fields(units):
    return [{field: unit.get(field) for field in FIELDS} for unit in units]


def verify(args):
    source = args.source_data.resolve(strict=True)
    source_history = args.history.resolve(strict=True)
    source_history.relative_to(source)
    output = args.out_dir.resolve()
    if output.exists() or output == source or source in output.parents:
        raise ValueError('Use a fresh output outside source data')
    # Do not interrupt an existing application/debug server.
    with socket.socket() as port:
        port.bind(('127.0.0.1', 8766))
    records = json.loads(source_history.read_text(encoding='utf-8'))['records']
    record = next(r for r in records if r['id'] == args.record_id)
    expected_units = record['settlement']['reviewUnits']
    assert len(expected_units) == args.expected_count
    assert sum(u.get('confirmationStatus') == 'CONFIRMED' for u in expected_units) == args.expected_confirmed
    assert record['settlement']['warehouseIdentityReview']['warehouseCoverageStatus'] == args.expected_coverage
    output.mkdir(parents=True)
    data = output / 'data'
    shutil.copytree(source, data)
    history = data / 'history/异环拍卖数据.json'
    history.parent.mkdir(exist_ok=True)
    shutil.copyfile(source_history, history)
    expected = unit_fields(expected_units)

    async def interact(zip_out, trigger_export):
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
            if not found:
                raise AssertionError('Target history row not found')
            ready = False
            for _ in range(60):
                ready = await eval_main(connection, f"""Boolean(
                    dashboard.review?.recordId === {json.dumps(args.record_id)} &&
                    dashboard.review?.reviewUnits?.length === {args.expected_count} &&
                    document.querySelectorAll('#review-proposals .grouping-card').length === {args.expected_count} &&
                    [...document.querySelectorAll('#review-proposals .grouping-card')].every(el =>
                        el.querySelector('.grouping-thumb img')?.complete &&
                        el.querySelector('.grouping-thumb img')?.naturalWidth > 0))""")
                if ready:
                    break
                await asyncio.sleep(.2)
            if not ready:
                raise AssertionError('Real history detail did not render expected review units')
            dom = await eval_main(connection, """JSON.stringify((() => {
                const cards = [...document.querySelectorAll('#review-proposals .grouping-card')];
                return {
                    recordId: dashboard.review.recordId,
                    summary: dashboard.review.warehouseIdentitySummary,
                    units: dashboard.review.reviewUnits.map(u => ({reviewUnitId:u.reviewUnitId,
                        selectedCatalogId:u.selectedCatalogId, canonicalName:u.canonicalName,
                        confirmationStatus:u.confirmationStatus, cropSha256:u.cropSha256})),
                    cards: cards.map(el => ({title:el.querySelector('.card-region-title')?.textContent?.trim(),
                        badge:el.querySelector('.proposal-status-badge')?.textContent?.trim(),
                        imageReady:Boolean(el.querySelector('.grouping-thumb img')?.complete &&
                            el.querySelector('.grouping-thumb img')?.naturalWidth > 0)})),
                    summaryVisible: !document.getElementById('wir-saved-summary').hidden,
                    summaryText: document.getElementById('wir-saved-facts').textContent,
                    lifecycle: document.getElementById('detail-lifecycle-badge').textContent.trim()
                };
            })())""")
            if isinstance(dom, str):
                dom = json.loads(dom)
            assert dom['units'] == expected
            assert len(dom['cards']) == args.expected_count and all(c['imageReady'] for c in dom['cards'])
            for unit, card in zip(expected_units, dom['cards']):
                if unit.get('confirmationStatus') == 'CONFIRMED':
                    assert unit.get('canonicalName') and unit['canonicalName'] in card['badge']
            if record['lifecycleStatus'] == 'DRAFT':
                assert dom['lifecycle'] == '草稿'
            assert dom['summaryVisible'] and dom['summary']['warehouseCoverage'] == args.expected_coverage
            assert f'覆盖 {args.expected_coverage}' in dom['summaryText']
            if args.expected_coverage != 'COMPLETE':
                assert dom['summary']['identityResolution'] == 'PARTIAL'
            if getattr(args, 'verify_resume', False):
                assert await eval_main(connection, """(() => {
                    const button = document.getElementById('history-warehouse-review-btn');
                    if (!button || button.hidden || button.disabled) return false;
                    button.click(); return true;
                })()""")
                resumed = False
                for _ in range(60):
                    resumed = await eval_main(connection, f"""Boolean(
                        dashboard.warehouseReview?.available &&
                        dashboard.warehouseReview?.trackCount === {args.expected_count} &&
                        dashboard.warehouseReview?.hasLegalEvidence &&
                        document.getElementById('detail-review-section').contains(
                            document.getElementById('warehouse-identity-review')) &&
                        !document.getElementById('warehouse-identity-review').hidden)""")
                    if resumed:
                        break
                    await asyncio.sleep(.2)
                assert resumed, 'History resume did not open verified evidence'
                dom['historyResumeVerified'] = True
            if trigger_export:
                clicked = await eval_main(connection, f"""(() => {{
                    const button = document.getElementById('history-export-btn');
                    if (!button || button.disabled) return false;
                    button.dataset.outputPath = {json.dumps(str(zip_out))}; button.click(); return true;
                }})()""")
                assert clicked
                for _ in range(100):
                    if zip_out.is_file() and zip_out.stat().st_size:
                        break
                    await asyncio.sleep(.2)
                assert zip_out.is_file()
            return dom

    results = []
    report = {'recordId': args.record_id, 'expectedCount': args.expected_count,
              'expectedConfirmed': args.expected_confirmed, 'expectedCoverage': args.expected_coverage,
              'launches': results, 'status': 'RUNNING'}
    try:
        bundle = output / 'dom-export.zip'
        for number in (1, 2):
            dual, dom, clean = run_one_launch(f'warehouse_{number}', data,
                output / f'app-{number}.log', output,
                zip_out=bundle if number == 1 else None, trigger_export=number == 1, interactor=interact,
                frozen_executable=args.executable)
            results.append({'dualLaunched': dual, 'cleanExit': clean, 'dom': dom})
            assert dual and clean
            print(f'Launch {number}: {len(dom["units"])} units, coverage {args.expected_coverage}', flush=True)
        assert results[0]['dom'] == results[1]['dom']
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            files = manifest['files']
            assert set(archive.namelist()) == {f['path'] for f in files} | {'manifest.json'}
            for file in files:
                assert hashlib.sha256(archive.read(file['path'])).hexdigest() == file['sha256']
            exported = json.loads(archive.read('records.json'))['records']
            target = next(r for r in exported if r['id'] == args.record_id)
            assert unit_fields(target['settlement']['reviewUnits']) == expected
            assert target['settlement']['warehouseIdentityReview']['warehouseCoverageStatus'] == args.expected_coverage
            report['zipFileCount'] = len(archive.namelist())
            report['manifestFileCount'] = len(files)
        report['status'] = 'PASS'
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-data', type=Path, required=True)
    parser.add_argument('--history', type=Path, required=True)
    parser.add_argument('--record-id', required=True)
    parser.add_argument('--expected-count', type=int, required=True)
    parser.add_argument('--expected-confirmed', type=int, required=True)
    parser.add_argument('--expected-coverage', choices=['COMPLETE', 'PARTIAL', 'COVERAGE_UNPROVEN'], required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--verify-resume', action='store_true')
    parser.add_argument('--executable', type=Path, help='Verify an isolated frozen executable')
    verify(parser.parse_args())
