import os
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import subprocess
import main


class VisionProcessStartRecoveryTests(unittest.TestCase):
    def test_concurrent_starts_and_exited_process_replacement(self):
        spawned = []
        real_popen = subprocess.Popen
        def controlled_spawn(*args, **kwargs):
            time.sleep(.05)
            proc = real_popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                              stdin=subprocess.DEVNULL, stdout=kwargs['stdout'], stderr=kwargs['stderr'],
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            spawned.append(proc)
            return proc
        try:
            with patch.dict(os.environ, {'NTE_DISABLE_VISION': '0'}), patch.object(main, 'VISION_PROCESS', None), patch.object(main.subprocess, 'Popen', side_effect=controlled_spawn):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    returned = list(pool.map(lambda _: main.start_vision_worker(), range(4)))
                self.assertEqual(len(spawned), 1)
                self.assertTrue(all(p is spawned[0] for p in returned))
                spawned[0].terminate(); spawned[0].wait(timeout=5)
                self.assertEqual(main.get_presentation_runtime_snapshot().vision_process_state, 'exited')
                replacement = main.start_vision_worker()
                self.assertEqual(len(spawned), 2)
                self.assertNotEqual(replacement.pid, spawned[0].pid)
                self.assertIsNone(replacement.poll())
                self.assertEqual(main.get_presentation_runtime_snapshot().vision_process_state, 'running')
        finally:
            for process in spawned:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)

    def test_spawn_failure_closes_parent_log_and_allows_retry(self):
        handles = []
        class Process:
            pid = 123
            def poll(self): return None
        process = Process()
        def spawn(*args, **kwargs):
            handles.append(kwargs['stdout'])
            if len(handles) == 1:
                raise OSError('temporary spawn failure')
            return process
        with patch.dict(os.environ, {'NTE_DISABLE_VISION': '0'}), patch.object(main, 'VISION_PROCESS', None), patch.object(main.subprocess, 'Popen', side_effect=spawn):
            self.assertIsNone(main.start_vision_worker())
            self.assertIs(main.start_vision_worker(), process)
            self.assertTrue(all(handle.closed for handle in handles))


if __name__ == '__main__':
    unittest.main()
