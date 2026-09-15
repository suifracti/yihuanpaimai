"""Ordered real-video observations through the frozen recognition and archive chain."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from datetime import datetime, timedelta


def run_from_environment():
    import cv2
    from keyboard_auction_pipeline import KeyboardAuctionPipeline
    from player_identity import get_player_name
    from runtime_data import resolve_runtime_data_root
    from runtime_revision import get_code_revision
    from auto_archiver import AutoArchiver
    from canonical_history_store import CanonicalHistoryStore
    import main

    output = Path(os.environ['NTE_ACQUISITION_OUTPUT']).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'success': False, 'frozen': bool(getattr(sys, 'frozen', False)),
              'codeRevision': get_code_revision(), 'configuredPlayerName': get_player_name(),
              'scope': 'Ordered sampled video frames, no OS capture/input, per-item matching disabled', 'frames': []}
    pipe = None
    cap = None

    def save():
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    try:
        config = json.loads(Path(os.environ['NTE_ACQUISITION_CONFIG']).read_text(encoding='utf-8'))
        video = Path(config['video']).resolve(strict=True)
        report['video'] = str(video)
        pipe = KeyboardAuctionPipeline()
        pipe.recognition_mode_provider = lambda: 'auto'
        pipe._ensure_ocr()
        cap = cv2.VideoCapture(str(video))
        assert cap.isOpened(), 'Cannot open video'
        for second in config['seconds']:
            cap.set(cv2.CAP_PROP_POS_MSEC, (second - 1) * 1000)
            for _ in range(30):
                ok, frame = cap.read()
                assert ok, 'Missing video frame'
                pipe._classify_scene_fast(frame)
            captured = (datetime.fromisoformat(config['startTime']) + timedelta(seconds=second)).isoformat()
            started = time.monotonic()
            ctx = pipe.process_frame(frame, captured, False, config['recordKey'], False)
            payload = main.build_in_auction_hud_payload(ctx, compute_shadow=False)
            row = {'second': second, 'frameSha256': hashlib.sha256(frame.tobytes()).hexdigest(),
                   'elapsedSeconds': time.monotonic() - started, 'scene': ctx.get('scene'),
                   'myName': ctx.get('myName'), 'acquired': ctx.get('isAcquired'),
                   'currentEstimate': ctx.get('currentEstimate'), 'seats': ctx.get('seats'),
                   'fastSeatBids': getattr(pipe, '_df_shadow_seat_bids', None),
                   'projectedAcquired': payload.get('isAcquired'),
                   'settlement': ctx.get('settlementData'), 'evidence': pipe._acquisition_names.evidence()}
            report['frames'].append(json.loads(json.dumps(row)))
            save()
        assert ctx.get('isAcquired') is config['expectedAcquired'], 'Unexpected final ownership'
        assert payload.get('isAcquired') is config['expectedAcquired'], 'HUD projection mismatch'
        history = resolve_runtime_data_root() / 'history/acquisition-replay.json'
        archiver = AutoArchiver(db_paths=[str(history)])
        if config.get('lockArchiveOnce') is True:
            import ctypes
            from ctypes import wintypes
            history.parent.mkdir(parents=True, exist_ok=True)
            with history.open('xb') as stream:
                stream.write(b'{"schemaVersion":7,"records":[]}')
            original = history.read_bytes()
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.CreateFileW(str(history), 0x80000000, 0, None, 3, 0, None)
            assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
            before = json.dumps(ctx, sort_keys=True)
            try:
                assert archiver.archive_match(ctx) is None
                assert archiver.last_saved_signature is None
                assert json.dumps(ctx, sort_keys=True) == before
            finally:
                kernel.CloseHandle(handle)
            assert history.read_bytes() == original
            time.sleep(1.1)
            report['storageFailure'] = {'realSharingViolation': True, 'contextUnchanged': True,
                                        'historyUnchanged': True, 'retryDelaySeconds': 1.1}
        saved = archiver.archive_match(ctx)
        assert saved is not None, 'No archived record'
        reopened = CanonicalHistoryStore(history).lookup(saved['id'])
        assert reopened['settlement']['acquired'] is config['expectedAcquired']
        assert reopened['auctionEvidence']['acquisition'][-1]['acquired'] is config['expectedAcquired']
        report.update(success=True, recordId=saved['id'], archivedSettlement=reopened['settlement'],
                      archivedEvidence=reopened['auctionEvidence']['acquisition'])
    except Exception as exc:
        report['error'] = repr(exc)
        report['traceback'] = traceback.format_exc()
    finally:
        if cap is not None:
            cap.release()
        executor = getattr(pipe, '_navigation_executor', None)
        if executor is not None:
            executor.shutdown(wait=True)
        save()
    return 0 if report['success'] else 1
