"""Exercise a real Windows history-file sharing violation and subsequent recovery."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
import argparse


def verify(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ['YIHUAN_DATA_ROOT'] = str(output / 'data')
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root/'core'), str(root/'app')]
    from auto_archiver import AutoArchiver
    from canonical_history_store import CanonicalHistoryStore
    history = output/'history.json'
    original = json.dumps({'schemaVersion': 7, 'records': []}).encode()
    history.write_bytes(original)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(history), 0x80000000, 0, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    archiver = AutoArchiver([str(history)])
    ctx = {'id': 'real-sharing-retry', 'settlementReady': True, 'isAcquired': False,
           'settlementData': {'isSettlement': True, 'clearingPrice': 100, 'actualTotal': 200}}
    try:
        failed = archiver.archive_match(ctx)
        assert failed is None
        assert ctx['settlementReady'] is True
        assert archiver.last_saved_signature is None
    finally:
        kernel.CloseHandle(handle)
    assert history.read_bytes() == original
    time.sleep(1.1)
    saved = archiver.archive_match(ctx)
    assert saved is not None
    reopened = CanonicalHistoryStore(history).lookup(ctx['id'])
    assert reopened['settlement']['acquired'] is False
    assert reopened['costs']['entry'] is None
    report = {'status': 'PASS', 'scope': 'Source AutoArchiver, real Windows sharing violation, release and actual store readback',
              'failedWritePreservedHistory': True, 'recordId': reopened['id'], 'lifecycleStatus': reopened['lifecycleStatus']}
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    verify(parser.parse_args().output)
