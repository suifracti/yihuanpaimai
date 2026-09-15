"""Real DOM click of the human-label export button, using isolated data."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import socket
import time
import zipfile
import websockets
from verify_p1_real_ui import WS, eval_main
from verify_p3_isolated_real_app_history import run_one_launch


def verify(args):
    output = args.out_dir.resolve()
    assert not output.exists() and args.source_data.resolve() not in output.parents
    with socket.socket() as port:
        port.bind(('127.0.0.1', 8766))
    output.mkdir(parents=True)
    data = output / 'data'
    shutil.copytree(args.source_data, data)
    history = data / 'history/异环拍卖数据.json'
    shutil.copyfile(args.history, history)
    before = history.read_bytes()
    bundle = output / 'human-labels.zip'
    async def interact(zip_out, trigger_export):
        async with websockets.connect(WS) as connection:
            await connection.send(json.dumps({'type': 'manual_bootstrap', 'action': 'manual_bootstrap'}))
            await eval_main(connection, "showView('history'); true")
            clicked = await eval_main(connection, f"""(() => {{
                const button = document.getElementById('history-labels-export-btn');
                if (!button || button.disabled) return false;
                button.dataset.outputPath = {json.dumps(str(bundle))};
                button.click(); return true;
            }})()""")
            assert clicked
            times = []
            for _ in range(150):
                start = time.monotonic()
                state = await eval_main(connection, "JSON.stringify({disabled:document.getElementById('history-labels-export-btn').disabled,text:document.getElementById('history-labels-export-status').textContent})")
                times.append(time.monotonic() - start)
                state = json.loads(state) if isinstance(state, str) else state
                if not state['disabled']:
                    break
                await asyncio.sleep(.2)
            assert bundle.exists() and f'已导出 {args.expected_samples} 份' in state['text'], state
            return {'state': state, 'uiProbeCount': len(times), 'maxUiProbeSeconds': max(times)}
    report = {'status': 'RUNNING'}
    try:
        dual, dom, clean = run_one_launch('human_labels', data, output / 'app.log', output,
            zip_out=bundle, trigger_export=True, interactor=interact)
        assert dual and clean
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            assert len(manifest['samples']) == args.expected_samples
            assert set(archive.namelist()) == {'manifest.json'} | {s['relativePath'] for s in manifest['samples']}
            for sample in manifest['samples']:
                assert sample['provenanceType'] == 'HUMAN_REVIEWED_CATALOG_ID'
                assert hashlib.sha256(archive.read(sample['relativePath'])).hexdigest() == sample['cropSha256']
        assert history.read_bytes() == before
        report.update(status='PASS', dualLaunched=dual, cleanExit=clean, dom=dom,
                      humanSamples=len(manifest['samples']), rejectedCount=len(manifest['rejected']),
                      historyUnchanged=True)
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-data', type=Path, required=True)
    parser.add_argument('--history', type=Path, required=True)
    parser.add_argument('--expected-samples', type=int, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    verify(parser.parse_args())
