import asyncio
import unittest
import numpy as np
from vision_worker_loop import run_vision_capture_loop


class VisionHealthRecoveryTests(unittest.TestCase):
    def test_fault_stages_publish_no_facts_then_success_clears_error(self):
        for stage in ('capture', 'recognition', 'presentation'):
            with self.subTest(stage=stage):
                published = []
                calls = {'capture': 0, 'recognition': 0, 'presentation': 0}
                frame = np.zeros((2, 2, 3), dtype=np.uint8)
                def provider():
                    calls['capture'] += 1
                    if calls['capture'] > 3:
                        return None, None, 'EOF'
                    if stage == 'capture' and calls['capture'] == 1:
                        raise OSError('capture unavailable')
                    return 1, frame, 'test-frame'
                def infer(*args, **kwargs):
                    calls['recognition'] += 1
                    if stage == 'recognition' and calls['recognition'] == 1:
                        raise RuntimeError('OCR unavailable')
                    return {'scene': 'IN_AUCTION', 'q': 5}
                def present(*args, **kwargs):
                    calls['presentation'] += 1
                    if stage == 'presentation' and calls['presentation'] == 1:
                        raise RuntimeError('projection unavailable')
                    return dict(kwargs['ctx'])
                async def publish(payload):
                    published.append(payload)
                asyncio.run(run_vision_capture_loop(pipeline=None, frame_provider=provider,
                    process_frame_fn=infer, process_live_game_frame_fn=present, publish_fn=publish, fps=1000))
                self.assertEqual(published[0], {'type': 'vision_health', 'visionHealth': {'status': 'ERROR', 'stage': stage}})
                self.assertEqual(published[-1]['visionHealth']['status'], 'READY')
                self.assertEqual(published[-1]['q'], 5)


if __name__ == '__main__':
    unittest.main()
