"""Menu wording observed in the August 17 and 18 full recording replays."""
import unittest
from pathlib import Path
import cv2
import numpy as np

from vision_pipeline import NTEVisionPipeline


def words(texts):
    return [([[220, y], [700, y], [700, y+30], [220, y+30]], text, .99)
            for y, text in zip((110, 440, 500, 580, 875), texts)]


class VideoNavigationRegressions(unittest.TestCase):
    def test_real_cold_settlement_routes_to_ocr_at_multiple_resolutions(self):
        root = Path(__file__).resolve().parent / 'fixtures/video_replay'
        frame = cv2.imdecode(np.fromfile(root / 'cold_settlement.jpg', np.uint8), 1)
        pipeline = NTEVisionPipeline()
        for width, height in ((960, 540), (1920, 1080), (2560, 1440)):
            with self.subTest(width=width):
                result = pipeline._classify_scene_fast(cv2.resize(frame, (width, height)))
                self.assertEqual(result['scene'], 'SETTLEMENT')
        menu = cv2.imdecode(np.fromfile(root / 'helper_selection.jpg', np.uint8), 1)
        self.assertNotEqual(pipeline._classify_scene_fast(menu)['scene'], 'SETTLEMENT')

    def test_helper_selection_is_lobby_even_with_live_skill_words(self):
        pipeline = NTEVisionPipeline()
        result = pipeline._classify_pre_auction_scene(words([
            '竞拍帮手列表', '技能描述', '千眼其一',
            '竞拍开始时，显示紫色、金色和红色品质藏品的总件数。', '确认']))
        self.assertEqual(result['scene'], 'AUCTION_LOBBY')
        pipeline._apply_pre_auction_scene(result)
        self.assertFalse(pipeline.current_context['inAuction'])
        self.assertEqual(pipeline.current_context['round'], 0)

    def test_skill_card_alone_is_not_a_menu_exit(self):
        pipeline = NTEVisionPipeline()
        result = pipeline._classify_pre_auction_scene(words(['千眼其一', '总件数为 8']))
        self.assertEqual(result['scene'], 'UNKNOWN')

    def test_stable_animation_subtotal_is_not_final_truth(self):
        pipeline = NTEVisionPipeline()
        subtotal = {'isSettlement': True, 'clearingPrice': 666666,
                    'actualTotal': 17217, 'profit': -649449, 'animationComplete': False}
        for _ in range(5):
            pipeline._stabilize_settlement(subtotal)
            self.assertFalse(pipeline.current_context['settlementReady'])
        final = {**subtotal, 'actualTotal': 631993, 'profit': -34673, 'animationComplete': True}
        pipeline._stabilize_settlement(final)
        self.assertFalse(pipeline.current_context['settlementReady'])
        pipeline._stabilize_settlement(final)
        self.assertTrue(pipeline.current_context['settlementReady'])
