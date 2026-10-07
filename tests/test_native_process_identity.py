"""Real child identity, rejected before window monitoring/WGC/Engine initialization."""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from native_observation import NativeObservationBridge


class NativeProcessIdentityTests(unittest.TestCase):
    def test_spawn_receipt_matches_real_host_self_report_before_capture(self):
        host = Path(os.environ['NTE_NATIVE_IDENTITY_TEST_HOST']).resolve(strict=True)
        self.assertTrue(host.is_relative_to(ROOT / 'build'))
        events, logs = [], []
        bridge = NativeObservationBridge(str(ROOT), events.append,
            lambda stage, text: logs.append({'stage': stage, 'text': text}))
        # First mode argument is rejected by the actual Host before any window API is reached.
        bridge._resolve_command = lambda: [str(host), '--observation-window-mode', 'invalid-offline-mode']
        child = bridge.start()
        self.assertIsNotNone(child)
        try:
            self.assertEqual(child.wait(timeout=5), 2)
            bridge._reader.join(timeout=1)
            bridge._stderr_reader.join(timeout=1)
            self.assertFalse(bridge._reader.is_alive())
            spawn = json.loads(next(e['text'] for e in logs if e['stage'] == 'STARTUP:NATIVE_IDENTITY'))
            self.assertEqual(spawn['mainPid'], os.getpid())
            self.assertEqual(spawn['mainParentPid'], os.getppid())
            self.assertEqual(spawn['parentPidAtSpawn'], os.getpid())
            self.assertEqual(spawn['hostSpawnPid'], child.pid)
            actual = next(e for e in events if e.get('reason') == 'invalid-observation-window-mode')
            self.assertEqual(actual['hostPid'], child.pid)
            self.assertTrue(actual['observationSessionId'].startswith('native-live-'))
            self.assertFalse(bridge.running)
            self.assertFalse((bridge.session_dir / 'engine-trace.jsonl').exists())
        finally:
            bridge.stop(timeout=1)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    try: stream.close()
                    except OSError as exc:
                        # Windows can reject the buffered STOP flush after the child closed stdin.
                        if stream is not child.stdin or child.poll() is None or exc.errno not in (22, 32):
                            raise
        (ROOT / 'build/native-retained-boundary-20261006/process-identity-verified.json').write_text(
            json.dumps({'passed': True, 'spawn': spawn, 'hostSelfReport': actual,
                        'exitCode': child.returncode, 'gameCapture': False, 'gameInput': False},
                       ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
