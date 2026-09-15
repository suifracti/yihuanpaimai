"""Preview the reviewed September 8 cleanup list; use --delete to delete it."""
from __future__ import annotations

import argparse
import csv
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/reports/2026-09-08-cleanup-candidates.csv'
PROTECTED = [ROOT / path for path in (
    'build/takeover_20260907/friend-app-package-v6',
    'build/takeover_20260908/friend-app-package-v7',
    'build/takeover_20260908/friend-app-package-v8',
    'build/takeover_20260905/repro-venv',
    'build/diagnosis_20260908', 'dist/异环拍卖助手',
)]


def inside(path, parent):
    return path == parent or parent in path.parents


def running_executables():
    """Read process image paths using Windows APIs; do not stop any process."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    pids = (wintypes.DWORD * 32768)()
    size = wintypes.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(size)):
        raise OSError('Cannot check running processes')
    if size.value >= ctypes.sizeof(pids):
        raise OSError('Process list truncated')
    result = []
    for pid in pids[:size.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                result.append(Path(buffer.value).resolve())
        finally:
            kernel.CloseHandle(handle)
    return result


def validate(path, tracked, active):
    resolved = path.resolve()
    if resolved != path or not inside(resolved, ROOT) or resolved == ROOT:
        raise ValueError(f'Unsafe path: {path}')
    if any(inside(resolved, p) or inside(p, resolved) for p in PROTECTED):
        raise ValueError(f'Protected path: {path}')
    if any(inside(p, resolved) for p in tracked + active):
        raise ValueError(f'Source file or running program: {path}')
    for parent in [path, *path.parents]:
        if parent == ROOT:
            break
        if parent.exists() and parent.lstat().st_file_attributes & 0x400:
            raise ValueError(f'Link/junction: {parent}')
    if not path.exists():
        return 0, 0
    items = [path]
    if path.is_dir():
        for directory, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                child = Path(directory) / name
                if child.lstat().st_file_attributes & 0x400:
                    raise ValueError(f'Link/junction: {child}')
                items.append(child)
    files = [p for p in items if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def main():
    parser = argparse.ArgumentParser(description='旧构建产物清理；默认只预览，不删除。')
    parser.add_argument('--delete', action='store_true', help='检查后输入 DELETE 执行删除')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This cleanup list is for Windows only')
    tracked_raw = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT)
    tracked = [ROOT / name.decode('utf-8') for name in tracked_raw.split(b'\0') if name]
    active = running_executables()
    with MANIFEST.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    plan = []
    for row in rows:
        path = ROOT / row['Relative']
        count, size = validate(path, tracked, active)
        # Never silently delete a directory that grew since it was reviewed.
        if count > int(row['Files']) or size > int(row['Bytes'] or 0):
            print(f'SKIP (changed since review): {path}')
            continue
        if path.exists():
            plan.append((path, size, count))
            print(f'{size / 1024**2:9.1f} MiB  {row["Relative"]}')
    print(f'\n{len(plan)} targets, {sum(size for _, size, _ in plan) / 1024**3:.2f} GiB')
    if not args.delete:
        print('Preview only. Run with --delete to delete these paths.')
        return
    if input('Type DELETE to confirm: ').strip() != 'DELETE':
        print('Cancelled.')
        return
    report = []
    try:
        for path, size, count in plan:
            new_count, new_size = validate(path, tracked, running_executables())
            if new_count > count or new_size > size:
                raise ValueError(f'Contents changed after preview: {path}')
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            report.append({'path': str(path.relative_to(ROOT)), 'bytes': size, 'deleted': True})
    finally:
        output = ROOT / 'build/cleanup-20260908-result.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Deleted {len(report)} targets. Result: {output}')


if __name__ == '__main__':
    main()
