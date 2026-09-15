import hashlib
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

from warehouse_grid_geometry import observe_warehouse_grid


class WarehouseGridBoundsTests(unittest.TestCase):
    def test_real_scroll_track_bounds_exclude_quality_filters_at_multiple_sizes(self):
        root = Path(__file__).parent / 'fixtures' / 'warehouse_grid_bounds'
        raw = (root / 'top-with-quality-filters.png').read_bytes()
        provenance = json.loads((root / 'provenance.json').read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), provenance['cropSha256'])
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        for scale in (1, 2 / 3, 4 / 3):
            with self.subTest(scale=scale):
                frame = cv2.resize(image, None, fx=scale, fy=scale)
                grid = observe_warehouse_grid(frame, already_cropped=True)['grid']
                self.assertEqual(grid['status'], 'OK')
                self.assertEqual(grid['visibleRowCount'], 10)
                self.assertLess(grid['yLines'][-1], provenance['filterCenterApproxPx'] * scale)
                self.assertLess(abs(grid['yLines'][-1] - provenance['gridBottomApproxPx'] * scale), 10 * scale)
