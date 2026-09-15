"""Training crops must reject invalid bounds instead of silently changing evidence."""
import sys
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from warehouse_reviewed_label_export import _crop_png, WarehouseReviewedLabelExportError, export_reviewed_label_bundle


class LabelCropBoundsTests(unittest.TestCase):
    def test_bridge_reports_invalid_destination_in_plain_language(self):
        from unittest.mock import Mock
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
        from main_window import MainWindowBridge
        bridge = MainWindowBridge(Mock())
        result = bridge.dispatch({'action': 'export_reviewed_labels', 'outputPath': 'invalid.txt'})['labelsExportResult']
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'ERROR')
        self.assertEqual(result['message'], '请选择以 .zip 结尾的样本包文件。')

    def test_failed_bundle_export_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'labels.zip'
            target.write_bytes(b'previous export')
            with patch('warehouse_reviewed_label_export.export_reviewed_label_dataset', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    export_reviewed_label_bundle(runtime_root=temp, output_path=target)
            self.assertEqual(target.read_bytes(), b'previous export')
            self.assertEqual(list(Path(temp).iterdir()), [target])

    def test_invalid_bounds_rejected(self):
        image = cv2.imencode('.png', np.zeros((10, 10, 3), np.uint8))[1].tobytes()
        for bbox in ([0, 0, 0, 1], [-1, 0, 2, 2], [0, 0, 11, 2],
                     [True, 0, 2, 2], [0, 0, float('nan'), 2], [0, 0, float('inf'), 2],
                     [0, 0, 0.1, 0.1], [0, 0, '2', 2]):
            with self.subTest(bbox=bbox), self.assertRaises(WarehouseReviewedLabelExportError):
                _crop_png(image, bbox)

    def test_valid_edge_crop_keeps_exact_pixels(self):
        pixels = np.arange(300, dtype=np.uint8).reshape(10, 10, 3)
        image = cv2.imencode('.png', pixels)[1].tobytes()
        crop = cv2.imdecode(np.frombuffer(_crop_png(image, [8, 7, 10, 10]), np.uint8), 1)
        np.testing.assert_array_equal(crop, pixels[7:10, 8:10])
