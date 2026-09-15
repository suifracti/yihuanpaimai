import unittest
import os
import sys
import numpy as np
import cv2

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from vision_pipeline import (
    NTEVisionPipeline,
    SCENE_OPEN_WORLD,
    SCENE_CITY_TYCOON_HUB,
    SCENE_CITY_LEISURE_MENU,
    SCENE_AUCTION_LOBBY,
    SCENE_IN_AUCTION,
    SCENE_UNKNOWN,
    parse_bid_text,
    parse_money_amount,
)


def _box(x, y, w=120, h=30):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


class TestLobbyRecognition(unittest.TestCase):
    def setUp(self):
        self.pipeline = NTEVisionPipeline()

    def test_parse_lobby_shanhu(self):
        mock_ocr = [
            (_box(50, 50), "即刻落槌", 0.99),
            (_box(1200, 400), "当前：珊瑚场", 0.98),
            (_box(1450, 400), "选择会场", 0.95),
            (_box(1200, 700), "高级品鉴仪器组", 0.97),
            (_box(1450, 700), "达芙蒂尔", 0.96),
            (_box(1200, 900), "开始匹配", 0.99),
        ]
        res = self.pipeline._parse_lobby(mock_ocr)
        self.assertTrue(res["inLobby"])
        self.assertEqual(res["venue"], "中级场 · 珊瑚场")
        self.assertEqual(res["venueKey"], "shanhu")
        self.assertEqual(res["toolGroup"], "高级品鉴仪器组")
        self.assertEqual(res["character"], "达芙蒂尔")
        self.assertEqual(res["entryCost"], 5000)

    def test_parse_lobby_haibei(self):
        mock_ocr = [
            (_box(50, 50), "即刻落槌", 0.99),
            (_box(1200, 400), "当前：海贝场", 0.98),
            (_box(1200, 700), "基础品鉴仪器组", 0.97),
            (_box(1450, 700), "哈尼娅", 0.96),
            (_box(1200, 900), "开始匹配", 0.99),
        ]
        res = self.pipeline._parse_lobby(mock_ocr)
        self.assertTrue(res["inLobby"])
        self.assertEqual(res["venue"], "初级场 · 海贝场")
        self.assertEqual(res["venueKey"], "haibei")
        self.assertEqual(res["toolGroup"], "基础品鉴仪器组")
        self.assertEqual(res["character"], "哈尼亚")
        self.assertEqual(res["entryCost"], 0)

    def test_parse_lobby_does_not_lock_first_venue_on_picker(self):
        """选场页三列同时出现时，没有「当前：」就不能锁成海贝场。"""
        mock_ocr = [
            (_box(200, 700), "海贝场", 0.98),
            (_box(500, 700), "珊瑚场", 0.98),
            (_box(800, 700), "真珠场", 0.98),
            (_box(450, 850), "请选择一个拍卖场", 0.99),
        ]
        res = self.pipeline._parse_lobby_loadout(mock_ocr)
        self.assertIsNone(res["venueKey"])

    def test_parse_lobby_current_coral_not_haibei(self):
        mock_ocr = [
            (_box(1200, 400), "当前：珊瑚场", 0.98),
            (_box(1200, 700), "高级品鉴仪器组", 0.97),
            (_box(1450, 820), "哈尼亚", 0.96),
        ]
        res = self.pipeline._parse_lobby_loadout(mock_ocr)
        self.assertEqual(res["venueKey"], "shanhu")
        self.assertEqual(res["character"], "哈尼亚")
        self.assertNotEqual(res["character"], "达芙蒂尔")

    def test_parse_lobby_loadout_without_hard_anchor(self):
        """右下备战区可能扫不到「开始匹配」，仍必须抽出助手和仪器组。"""
        mock_ocr = [
            (_box(1200, 400), "当前：海贝场", 0.98),
            (_box(1200, 700), "高级品鉴仪器组", 0.97),
            (_box(1450, 820), "达芙蒂尔", 0.96),
        ]
        res = self.pipeline._parse_lobby_loadout(mock_ocr)
        self.assertEqual(res["venueKey"], "haibei")
        self.assertEqual(res["toolGroup"], "高级品鉴仪器组")
        self.assertEqual(res["character"], "达芙蒂尔")
        self.assertEqual(res["entryCost"], 0)
        self.pipeline._apply_lobby_loadout(res)
        c = self.pipeline.current_context
        self.assertEqual(c["lobbyCharacter"], "达芙蒂尔")
        self.assertEqual(c["lobbyToolGroup"], "高级品鉴仪器组")
        self.assertEqual(c["character"], "达芙蒂尔")
        self.assertIsNone(c.get("toolGroup"))

    def test_ocr_typo_su_maps_to_advanced_tool_group(self):
        mock_ocr = [
            (_box(1200, 400), "当前：珊瑚场", 0.98),
            (_box(1200, 700), "吸品鉴仪器组", 0.90),
            (_box(1450, 820), "哈尼亚", 0.96),
        ]
        res = self.pipeline._parse_lobby_loadout(mock_ocr)
        self.assertEqual(res["toolGroup"], "高级品鉴仪器组")
        self.assertEqual(res["character"], "哈尼亚")
        self.assertEqual(res["venueKey"], "shanhu")

    def test_lobby_does_not_flip_back_to_tycoon(self):
        self.pipeline.current_context["scene"] = SCENE_AUCTION_LOBBY
        self.pipeline.current_context["inLobby"] = True
        painter = TestPreAuctionSceneClassification()
        img = painter._paint_tycoon_like()
        ctx = self.pipeline.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_AUCTION_LOBBY)
        self.assertTrue(ctx["inLobby"])

    def test_character_update_is_not_blocked_by_pair_special_case(self):
        self.pipeline.current_context["lobbyCharacter"] = "小吱"
        self.pipeline.current_context["character"] = "小吱"
        self.pipeline._apply_lobby_loadout({
            "venue": "中级场 · 珊瑚场",
            "venueKey": "shanhu",
            "venueLabel": "珊瑚场",
            "toolGroup": "高级品鉴仪器组",
            "character": "达芙蒂尔",
            "entryCost": 5000,
        })
        self.assertEqual(self.pipeline.current_context["lobbyCharacter"], "达芙蒂尔")

    def test_refresh_failure_clears_previous_character(self):
        self.pipeline.current_context["lobbyCharacter"] = "达芙蒂尔"
        self.pipeline._apply_lobby_loadout({
            "clearCharacter": True,
            "characterSource": "unrecognized",
            "characterScore": 0.12,
            "characterSecondScore": 0.10,
        })
        self.assertIsNone(self.pipeline.current_context["lobbyCharacter"])
        self.assertEqual(self.pipeline.current_context["lobbyCharacterSource"], "unrecognized")

    def test_ocr_typo_xiaoai_does_not_guess_xiaozhi(self):
        mock_ocr = [
            (_box(1200, 400), "当前：珊瑚场", 0.98),
            (_box(1450, 820), "小哎", 0.81),
        ]
        res = self.pipeline._parse_lobby_loadout(mock_ocr)
        self.assertIsNone(res["character"])
        self.assertEqual(res["venueKey"], "shanhu")

    def test_short_token_does_not_force_dafuteer(self):
        mock_ocr = [
            (_box(1200, 400), "当前：珊瑚场", 0.98),
            (_box(1450, 820), "哈尼亚", 0.96),
            (_box(800, 500), "蒂尔", 0.4),
        ]
        res = self.pipeline._parse_lobby_loadout(mock_ocr)
        self.assertEqual(res["character"], "哈尼亚")

    def test_reset_session_state_clears_stuck_lobby(self):
        self.pipeline.current_context["scene"] = SCENE_AUCTION_LOBBY
        self.pipeline.current_context["inLobby"] = True
        self.pipeline.current_context["lobbyCharacter"] = "达芙蒂尔"
        self.pipeline.current_context["lobbyVenue"] = "中级场 · 珊瑚场"
        self.pipeline.reset_session_state()
        c = self.pipeline.current_context
        self.assertEqual(c["scene"], SCENE_UNKNOWN)
        self.assertFalse(c["inLobby"])
        self.assertIsNone(c["lobbyCharacter"])
        self.assertIsNone(c["lobbyVenue"])

    def test_parse_non_lobby(self):
        mock_ocr = [
            (_box(800, 50), "第 1 回合", 0.99),
            (_box(850, 90), "00:15", 0.98),
        ]
        res = self.pipeline._parse_lobby(mock_ocr)
        self.assertFalse(res["inLobby"])

    def test_instant_hammer_card_alone_is_not_lobby(self):
        """都市闲趣列表底部的「即刻落槌」卡片不得误判为拍卖大厅。"""
        mock_ocr = [
            (_box(80, 40), "MENU", 0.99),
            (_box(160, 40), "都市闲趣", 0.99),
            (_box(400, 40), "大亨计划激励金", 0.98),
            (_box(200, 820), "即刻落槌", 0.99),
            (_box(500, 520), "排球之星", 0.97),
            (_box(200, 520), "格斗俱乐部", 0.97),
        ]
        res = self.pipeline._parse_lobby(mock_ocr)
        self.assertFalse(res["inLobby"])

    def test_parse_loading_screen(self):
        mock_loading_ocr = [
            (_box(1200, 100), "「粉爪银行」", 0.99),
            (_box(1200, 200, 400, 40), "德沃夏克集团旗下的...", 0.95),
            (_box(1700, 950), "100%", 1.0),
        ]
        res = self.pipeline._parse_loading(mock_loading_ocr)
        self.assertTrue(res["isLoading"])
        self.assertEqual(res["percent"], 100)
        self.assertEqual(res["venue"], "粉爪银行")

    def test_loading_ignores_leisure_activity_name(self):
        """闲趣活动名「粉爪大劫案」不得被当成载入场地。"""
        mock_ocr = [
            (_box(600, 400), "「粉爪大劫案」", 0.99),
            (_box(1700, 950), "80%", 0.99),
        ]
        res = self.pipeline._parse_loading(mock_ocr)
        self.assertTrue(res["isLoading"])  # 有进度条
        self.assertNotEqual(res.get("venue"), "粉爪大劫案")


class TestPreAuctionSceneClassification(unittest.TestCase):
    def setUp(self):
        self.pipeline = NTEVisionPipeline()
        self.w, self.h = 1920, 1080

    def test_city_tycoon_hub(self):
        mock_ocr = [
            (_box(40, 20), "都市大亨", 0.99),
            (_box(700, 120), "大亨等级", 0.99),
            (_box(900, 400), "都市闲趣", 0.98),
            (_box(500, 350), "房产", 0.95),
            (_box(1400, 200), "富爪榜", 0.95),
            (_box(1600, 800), "升级", 0.95),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertEqual(res["scene"], SCENE_CITY_TYCOON_HUB)
        self.assertFalse(res["auctionEntryVisible"])

    def test_city_leisure_menu_top(self):
        mock_ocr = [
            (_box(80, 40), "MENU", 0.99),
            (_box(160, 40), "都市闲趣", 0.99),
            (_box(500, 40), "大亨计划激励金", 0.98),
            (_box(200, 250), "同城派送", 0.97),
            (_box(600, 250), "车辆赛事", 0.97),
            (_box(1000, 250), "店长特供", 0.97),
            (_box(600, 520), "粉爪大劫案", 0.97),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertEqual(res["scene"], SCENE_CITY_LEISURE_MENU)
        self.assertFalse(res["auctionEntryVisible"])

    def test_city_leisure_menu_auction_entry_visible(self):
        mock_ocr = [
            (_box(80, 40), "MENU", 0.99),
            (_box(160, 40), "都市闲趣", 0.99),
            (_box(500, 40), "大亨计划激励金", 0.98),
            (_box(200, 300), "小小麻将", 0.97),
            (_box(200, 520), "格斗俱乐部", 0.97),
            (_box(600, 520), "排球之星", 0.97),
            (_box(200, 820), "即刻落槌", 0.99),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertEqual(res["scene"], SCENE_CITY_LEISURE_MENU)
        self.assertTrue(res["auctionEntryVisible"])

    def test_auction_lobby_not_classified_as_pre_nav(self):
        """真正大厅应交点应交给 _parse_lobby，预导航分类返回 UNKNOWN。"""
        mock_ocr = [
            (_box(50, 40), "即刻落槌", 0.99),
            (_box(1200, 400), "当前：海贝场", 0.98),
            (_box(1450, 400), "选择会场", 0.95),
            (_box(1200, 900), "开始匹配", 0.99),
            (_box(80, 700), "展览柜收益", 0.96),
            (_box(200, 950), "藏品图鉴", 0.96),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertEqual(res["scene"], SCENE_UNKNOWN)
        lobby = self.pipeline._parse_lobby(mock_ocr, self.w, self.h)
        self.assertTrue(lobby["inLobby"])
        self.assertEqual(lobby["venueKey"], "haibei")

    def test_apply_pre_auction_scene_clears_lobby_flags(self):
        self.pipeline.current_context["inLobby"] = True
        self.pipeline.current_context["isLoading"] = True
        self.pipeline.current_context["loadingVenue"] = "粉爪银行"
        self.pipeline._apply_pre_auction_scene({
            "scene": SCENE_CITY_LEISURE_MENU,
            "auctionEntryVisible": True,
        })
        c = self.pipeline.current_context
        self.assertEqual(c["scene"], SCENE_CITY_LEISURE_MENU)
        self.assertTrue(c["auctionEntryVisible"])
        self.assertFalse(c["inLobby"])
        self.assertFalse(c["isLoading"])
        self.assertIsNone(c["loadingVenue"])
        self.assertEqual(c["sceneLabel"], "都市闲趣")


    def test_open_world_balcony_hud(self):
        """阳台大世界：左上 F5 + UID + Enter + 底栏血量 + 顶栏热键。"""
        mock_ocr = [
            (_box(120, 40), "F5", 0.99),
            (_box(1500, 30), "F1", 0.98),
            (_box(1560, 30), "F2", 0.98),
            (_box(1620, 30), "F3", 0.98),
            (_box(1680, 30), "F4", 0.98),
            (_box(1800, 30), "ESC", 0.97),
            (_box(40, 1040), "Enter", 0.99),
            (_box(40, 1060), "UID:900000000003", 0.99),
            (_box(900, 1000), "22101/22101", 0.98),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertEqual(res["scene"], SCENE_OPEN_WORLD)
        self.assertFalse(res["auctionEntryVisible"])

    def test_open_world_hp_bar_is_role_agnostic(self):
        """换角色后血量数字变化，只要仍是底栏 当前/上限 即可。"""
        mock_ocr = [
            (_box(120, 40), "F5", 0.99),
            (_box(40, 1060), "UID:900000000003", 0.99),
            (_box(900, 1000), "25139/25139", 0.98),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertEqual(res["scene"], SCENE_OPEN_WORLD)

    def test_open_world_driving_hud(self):
        """载具大世界：F5 + 时速表 + UID，无步行血条也可识别。"""
        mock_ocr = [
            (_box(120, 40), "F5", 0.99),
            (_box(1500, 30), "F1", 0.98),
            (_box(1560, 30), "F2", 0.98),
            (_box(40, 1040), "Enter", 0.99),
            (_box(40, 1060), "UID:900000000003", 0.99),
            (_box(960, 980), "KM/H", 0.97),
            (_box(900, 960), "R 000", 0.96),
            (_box(800, 80), "Dream Land", 0.95),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertEqual(res["scene"], SCENE_OPEN_WORLD)

    def test_open_world_not_confused_with_lobby(self):
        mock_ocr = [
            (_box(50, 40), "即刻落槌", 0.99),
            (_box(1200, 900), "开始匹配", 0.99),
            (_box(120, 40), "F5", 0.5),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertEqual(res["scene"], SCENE_UNKNOWN)

    def test_tycoon_title_chip_beats_uid_only(self):
        """都市大亨总览也有 UID；无 F5 时必须判都市大亨，不能判大世界。"""
        mock_ocr = [
            (_box(40, 20), "都市大亨", 0.99),
            (_box(700, 120), "大亨等级", 0.99),
            (_box(40, 1060), "UID:900000000003", 0.99),
            (_box(900, 400), "都市闲趣", 0.98),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertEqual(res["scene"], SCENE_CITY_TYCOON_HUB)

    def _paint_tycoon_like(self, w=1920, h=1080):
        img = np.full((h, w, 3), 230, dtype=np.uint8)  # 浅灰白城
        img[0:int(h * 0.11), 0:int(w * 0.22)] = (28, 28, 28)  # 左上深色标题胶囊
        img[int(h * 0.68):int(h * 0.92), int(w * 0.76):int(w * 0.97)] = (20, 140, 255)  # 右下橙钮
        return img

    def _paint_open_world_like(self, w=1920, h=1080, night=False):
        bg = 28 if night else 70
        img = np.full((h, w, 3), bg, dtype=np.uint8)
        # 左上圆形小地图
        cv2.circle(img, (int(w * 0.07), int(h * 0.10)), int(h * 0.07), (18, 18, 18), -1)
        cv2.circle(img, (int(w * 0.07), int(h * 0.10)), int(h * 0.07), (160, 160, 160), 3)
        # 底栏血条
        img[int(h * 0.91):int(h * 0.96), int(w * 0.32):int(w * 0.68)] = (230, 230, 230)
        # 顶栏热键浅色圆
        for x in (0.62, 0.70, 0.78, 0.86):
            cv2.circle(img, (int(w * x), int(h * 0.05)), 18, (200, 200, 200), -1)
        if night:
            # 右下技能钮偏橙，不能触发都市大亨
            cv2.circle(img, (int(w * 0.90), int(h * 0.88)), 46, (20, 90, 210), -1)
        return img

    def test_fast_scene_tycoon_without_ocr(self):
        img = self._paint_tycoon_like()
        res = self.pipeline._classify_scene_fast(img)
        self.assertEqual(res["scene"], SCENE_CITY_TYCOON_HUB)
        self.assertIsNone(self.pipeline._ocr_engine)

    def test_fast_scene_open_world_without_ocr(self):
        img = self._paint_open_world_like()
        res = self.pipeline._classify_scene_fast(img)
        self.assertEqual(res["scene"], SCENE_OPEN_WORLD)
        self.assertIsNone(self.pipeline._ocr_engine)

    def test_process_frame_nav_does_not_load_ocr(self):
        img = self._paint_tycoon_like()
        ctx = self.pipeline.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_CITY_TYCOON_HUB)
        self.assertIsNone(self.pipeline._ocr_engine)

    def test_night_open_world_is_not_tycoon(self):
        img = self._paint_open_world_like(night=True)
        res = self.pipeline._classify_scene_fast(img)
        self.assertEqual(res["scene"], SCENE_OPEN_WORLD)

    def _paint_leisure_like(self, w=1920, h=1080):
        img = np.full((h, w, 3), 18, dtype=np.uint8)  # 暗边
        img[int(h * 0.08):int(h * 0.92), int(w * 0.08):int(w * 0.92)] = (220, 220, 220)  # 浅色面板
        img[int(h * 0.07):int(h * 0.16), int(w * 0.09):int(w * 0.20)] = (20, 190, 245)  # 黄 MENU
        return img

    def test_fast_scene_leisure_without_ocr(self):
        img = self._paint_leisure_like()
        res = self.pipeline._classify_scene_fast(img)
        self.assertEqual(res["scene"], SCENE_CITY_LEISURE_MENU)
        self.assertIsNone(self.pipeline._ocr_engine)

    def _paint_lobby_like(self, w=1920, h=1080):
        img = np.full((h, w, 3), 40, dtype=np.uint8)
        img[int(h * 0.18):int(h * 0.78), int(w * 0.00):int(w * 0.58)] = (90, 90, 90)  # 左侧到中间都是展厅，不是 IDE 深色侧栏
        img[int(h * 0.20):int(h * 0.58), int(w * 0.62):int(w * 0.94)] = (30, 110, 220)  # 右上橙卡
        img[int(h * 0.84):int(h * 0.95), int(w * 0.64):int(w * 0.94)] = (235, 235, 235)  # 开始匹配
        return img

    def test_fast_scene_lobby_without_ocr(self):
        img = self._paint_lobby_like()
        res = self.pipeline._classify_scene_fast(img)
        self.assertEqual(res["scene"], SCENE_AUCTION_LOBBY)
        self.assertIsNone(self.pipeline._ocr_engine)

    def test_bright_center_does_not_override_lobby_card(self):
        """中间叠了亮窗口也不能把橙色会场卡+开始匹配打成都市大亨。"""
        img = self._paint_lobby_like()
        img[int(1080 * 0.16):int(1080 * 0.78), int(1920 * 0.08):int(1920 * 0.62)] = (230, 230, 230)
        res = self.pipeline._classify_scene_fast(img)
        self.assertEqual(res["scene"], SCENE_AUCTION_LOBBY)

    def test_leisure_does_not_stick_as_tycoon(self):
        self.pipeline._apply_pre_auction_scene({"scene": SCENE_CITY_TYCOON_HUB})
        ctx = self.pipeline.process_frame(self._paint_leisure_like())
        self.assertEqual(ctx["scene"], SCENE_CITY_LEISURE_MENU)

    def test_white_city_is_never_open_world(self):
        """都市大亨白城+橙钮即使带圆形标题标，也不能判大世界。"""
        img = self._paint_tycoon_like()
        cv2.circle(img, (80, 55), 28, (20, 20, 20), -1)
        res = self.pipeline._classify_scene_fast(img)
        self.assertEqual(res["scene"], SCENE_CITY_TYCOON_HUB)

    def test_uid_without_f5_is_not_open_world(self):
        mock_ocr = [
            (_box(40, 1060), "UID:900000000003", 0.99),
            (_box(40, 1040), "Enter", 0.99),
            (_box(900, 1000), "25139/25139", 0.98),
            (_box(1500, 30), "F1", 0.98),
            (_box(1560, 30), "F2", 0.98),
        ]
        res = self.pipeline._classify_pre_auction_scene(mock_ocr, self.w, self.h)
        self.assertNotEqual(res["scene"], SCENE_OPEN_WORLD)

    def _paint_desktop_capture_like(self, w=1920, h=1080):
        """整桌面录屏：左侧深色 IDE + 右侧游戏，不能被颜色快检打成大厅。"""
        img = np.full((h, w, 3), 28, dtype=np.uint8)
        img[int(h * 0.10):int(h * 0.90), 0:int(w * 0.28)] = (18, 18, 18)
        img[int(h * 0.18):int(h * 0.78), int(w * 0.30):int(w * 0.58)] = (90, 90, 90)
        img[int(h * 0.20):int(h * 0.58), int(w * 0.62):int(w * 0.94)] = (30, 110, 220)
        img[int(h * 0.84):int(h * 0.95), int(w * 0.64):int(w * 0.94)] = (235, 235, 235)
        return img

    def test_desktop_capture_is_not_fast_lobby(self):
        img = self._paint_desktop_capture_like()
        res = self.pipeline._classify_scene_fast(img)
        self.assertNotEqual(res["scene"], SCENE_AUCTION_LOBBY)

    def test_parse_venue_picker_is_lobby(self):
        mock_ocr = [
            (_box(300, 200), "AUCTION HOUSE", 0.99),
            (_box(200, 700), "海贝场", 0.98),
            (_box(500, 700), "珊瑚场", 0.98),
            (_box(800, 700), "真珠场", 0.98),
            (_box(450, 850), "请选择一个拍卖场", 0.99),
        ]
        res = self.pipeline._parse_lobby(mock_ocr, self.w, self.h)
        self.assertTrue(res["inLobby"])

    def test_live_in_auction_is_not_open_world(self):
        p = os.path.join(PROJECT_ROOT, "build", "live_fail", "t034.jpg")
        if not os.path.exists(p):
            self.skipTest("live auction frame missing")
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(img)
        fast = self.pipeline._classify_scene_fast(img)
        self.assertNotEqual(fast["scene"], SCENE_OPEN_WORLD)
        self.pipeline._ensure_ocr()
        ctx = self.pipeline.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_IN_AUCTION)
        self.assertTrue(ctx["inAuction"])
        self.assertFalse(ctx["inLobby"])

    def test_live_dark_lobby_is_not_open_world(self):
        p = os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby", "t0018.jpg")
        if not os.path.exists(p):
            self.skipTest("live lobby frame missing")
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(img)
        fast = self.pipeline._classify_scene_fast(img)
        self.assertEqual(fast["scene"], SCENE_AUCTION_LOBBY)
        self.pipeline._ensure_ocr()
        ctx = self.pipeline.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_AUCTION_LOBBY)
        self.assertTrue(ctx["inLobby"])
        self.assertEqual(ctx.get("lobbyVenueKey"), "haibei")
        self.assertEqual(ctx.get("lobbyCharacter"), "达芙蒂尔")
        self.assertEqual(ctx.get("lobbyToolGroup"), "高级品鉴仪器组")


class TestMoneyAndSettlementParsing(unittest.TestCase):
    def setUp(self):
        self.pipeline = NTEVisionPipeline()

    def test_parse_money_amount_ocr_separators(self):
        self.assertEqual(parse_money_amount("67,571"), 67571)
        self.assertEqual(parse_money_amount("67.571"), 67571)
        self.assertEqual(parse_money_amount("67，571"), 67571)
        self.assertEqual(parse_money_amount("平均价值为67.571。"), 67571)
        self.assertEqual(parse_bid_text("450K"), 450000)
        self.assertEqual(parse_bid_text("300,000"), 300000)

    def test_parse_settlement_normalized_1080p(self):
        mock_ocr = [
            (_box(480, 220), "竞拍结束", 0.99),
            (_box(420, 430), "最终成交价", 0.98),
            (_box(420, 500), "454,444", 0.99),
            (_box(720, 430), "实际价值", 0.98),
            (_box(720, 500), "972,970", 0.99),
            (_box(1020, 430), "收益", 0.98),
            (_box(1020, 500), "518,526", 0.99),
        ]
        res = self.pipeline._parse_settlement(mock_ocr, 1920, 1080)
        self.assertTrue(res["isSettlement"])
        self.assertEqual(res["clearingPrice"], 454444)
        self.assertEqual(res["actualTotal"], 972970)
        self.assertEqual(res["profit"], 518526)

    def test_parse_settlement_still_works_on_540p_band(self):
        # 旧关键帧约 540p，三列数字大约在 y=250
        mock_ocr = [
            (_box(200, 80), "竞拍结束", 0.99),
            (_box(180, 230), "最终成交价", 0.98),
            (_box(180, 250), "454,444", 0.99),
            (_box(360, 230), "实际价值", 0.98),
            (_box(360, 250), "972,970", 0.99),
            (_box(540, 230), "收益", 0.98),
            (_box(540, 250), "518,526", 0.99),
        ]
        res = self.pipeline._parse_settlement(mock_ocr, 960, 540)
        self.assertTrue(res["isSettlement"])
        self.assertEqual(res["clearingPrice"], 454444)
        self.assertEqual(res["actualTotal"], 972970)
        self.assertEqual(res["profit"], 518526)


if __name__ == "__main__":
    unittest.main()
