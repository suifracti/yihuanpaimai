"""Saved content, not capture IDs or wheel receipts, must qualify automatic scrolling."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core'), str(ROOT)]
from native_capture_delivery import DELIVERY
from native_warehouse_auto_capture import NativeWarehouseAutoCapture
from warehouse_support_frame import stationary_support_proof
from tests.test_native_warehouse_auto_capture import Source
from tests.test_native_delivery_contract import proof


class DeliverySource(Source):
    def __init__(self):
        super().__init__()
        self.scope['capturePolicy'] = DELIVERY
        self._ordinal = 0

    def capture_manual_page(self):
        self._ordinal += 1
        return super().capture_manual_page()

    def request_scroll_down(self, **kwargs):
        return super().request_scroll_down()

    def source_session_snapshot(self):
        result = super().source_session_snapshot()
        result['requestAttempts'] = self._ordinal
        result['savedSource'].update(capturePolicy=DELIVERY,
            deliveryProof=self.pages[-1]['deliveryProof'] if self.pages else None)
        return result


def visible_content():
    # A coloured textured item on a dark background; no unknown white silhouette.
    image = np.full((240, 600, 3), 20, np.uint8)
    yy, xx = np.indices((100, 100))
    image[40:140, 40:140, 0] = 30 + (xx % 20)
    image[40:140, 40:140, 1] = 80 + (yy % 60)
    image[40:140, 40:140, 2] = 170 + ((xx + yy) % 60)
    cv2.rectangle(image, (180, 40), (236, 96), (55, 55, 55), 1)  # ordinary empty cell
    return image


class ContentStabilityTests(unittest.TestCase):
    def start(self, images):
        self.now, self.source, self.logs = [100.0], DeliverySource(), []
        self.auto = NativeWarehouseAutoCapture(self.source, clock=lambda: self.now[0], timers=False,
            diagnostic_log=lambda record: self.logs.append(record))
        self.assertTrue(self.auto.confirm(self.auto.prepare()['armingToken'])['ok'])
        self.auto.on_event({'state': 'OPEN', 'reason': 'SOURCE_READY'})
        def read(page):
            return images[page['number']], {'scrollState': 'TOP', 'trackBox': [590, 0, 596, 240],
                'thumbBox': [590, 10, 596, 80], 'thumbPosition': .05,
                'capturePolicy': DELIVERY, 'deliveryProof': page['deliveryProof'],
                'revealMarker': {'status': 'NOT_DETECTED'}}
        reader = patch.object(self.auto, '_read_page', side_effect=read)
        reader.start(); self.addCleanup(reader.stop)
        self.auto.on_event({'state': 'OPEN', 'reason': 'PAGE_ACCEPTED', 'page': self.page(0)})
        self.now[0] += .7
        self.auto.poll()

    def page(self, number):
        return {'number': number, 'capturePolicy': DELIVERY,
            'deliveryProof': proof(number + 1, request=10_000_000_000 + number * 500_000_000)}

    def support(self, duplicate=False):
        if duplicate:
            self.auto.on_event({'state': 'OPEN', 'reason': 'DUPLICATE_PAGE',
                'proof': {'pixelSha256': 'hash', 'deliveryProof': self.page(1)['deliveryProof']}})
        else:
            self.auto.on_event({'state': 'OPEN', 'reason': 'PAGE_ACCEPTED', 'page': self.page(1)})

    def wheels(self):
        return sum(a[0] == 'SCROLL_DOWN' for a in self.source.actions)

    def test_local_reveal_change_rejected_even_when_global_stationary_gate_passes(self):
        before = visible_content(); after = before.copy()
        after[45:49, 45:49] = (240, 120, 40)  # localized revealing animation
        self.assertIsNotNone(stationary_support_proof(before, after), 'known weak-gate counterexample')
        self.start([before, after]); self.support()
        self.assertEqual(self.wheels(), 0)
        self.assertTrue(self.auto._active)
        self.assertEqual(self.auto._phase, 'WAIT_STABLE')
        self.assertTrue(any('CONTENT_CHANGING' in record for record in self.logs))
        self.assertEqual(len(self.source.pages), 2, 'keep partial originals, not two-page coverage')

    def test_identical_independent_unrevealed_outlines_are_not_stable_items(self):
        image = visible_content()
        cv2.rectangle(image, (300, 40), (355, 150), (210, 210, 210), 2)
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                self.start([image, image.copy()]); self.support(duplicate)
                self.assertEqual(self.wheels(), 0)
                self.assertEqual(self.auto._reason, 'CONTENT_UNREVEALED_OR_UNKNOWN')

    def test_visible_stable_page_can_request_wheel_but_duplicate_after_wheel_is_no_progress(self):
        image = visible_content()
        self.start([image, image.copy()]); self.support()
        self.assertEqual(self.wheels(), 1)
        self.auto.on_event({'state': 'OPEN', 'reason': 'WINDOW_WHEEL_MESSAGE_SENT'})
        self.now[0] += .4; self.auto.poll()
        self.auto.on_event({'state': 'OPEN', 'reason': 'DUPLICATE_PAGE',
            'proof': {'pixelSha256': 'hash', 'deliveryProof': proof(3, request=11_000_000_000)}})
        self.assertEqual(self.auto._reason, 'WINDOW_SCROLL_NO_PROGRESS')
        self.assertEqual(self.wheels(), 1, 'no retry of an uncertain wheel')
        self.assertTrue(self.auto._post_scroll_frame_received)
        self.assertEqual(self.source.actions[-1], ('PROCESS', 'INCOMPLETE'))


if __name__ == '__main__':
    unittest.main()
