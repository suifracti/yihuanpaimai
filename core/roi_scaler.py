"""
Neverness to Everness (异环) - 跨分辨率 ROI 归一化与缩放适配器 (v0.65)

核心功能：
  1. 定义基准 16:9 归一化 ROI 坐标系 (Normalized Coordinate Space [0.0, 1.0])
  2. 支持 1080p (1920x1080)、1440p (2560x1440)、4K (3840x2160) 及任意 DPI 动态切片
  3. 智能黑边/带状视口 (Letterbox / Pillarbox) 补偿
"""

from typing import Tuple, Dict, Any, List, Optional
import numpy as np

# 16:9 基准归一化 ROI 字典 (left, top, right, bottom) in [0.0, 1.0]
NORMALIZED_ROIS = {
    # 1. 顶栏：回合与倒计时
    "header_round_timer": (0.42, 0.02, 0.58, 0.10),
    # 1b. 右上角：当前估价胶囊与实时估值
    "current_estimate_chip": (0.775, 0.130, 0.940, 0.180),
    "current_estimate_digits": (0.853, 0.137, 0.925, 0.173),
    
    # 2. 中间：旧看板切片（过小，仅兼容；情报卡读取走 intel_card_stack）
    "intel_board": (0.35, 0.12, 0.65, 0.35),
    # 2b. 中央情报栈大区：面板标题 + 实际卡片列。卡片张数/顺序在区内动态检测，禁止按行号钉死。
    "intel_card_stack": (0.34, 0.13, 0.68, 0.80),
    
    # 3. 底部 4 人独立出价栏 (4个席位切片，历史遗留)
    "bid_slot_1_player": (0.15, 0.82, 0.32, 0.98),
    "bid_slot_2_opp1": (0.33, 0.82, 0.50, 0.98),
    "bid_slot_3_opp2": (0.51, 0.82, 0.68, 0.98),
    "bid_slot_4_opp3": (0.69, 0.82, 0.86, 0.98),
    # 3b. 左侧 4 席位纵向完整面板条带 (名字 + 实时大出价 + R1~R4 历史小槽位)
    "seats_bids_panel": (0.02, 0.12, 0.32, 0.78),
    "seat_current_bid_1": (0.120, 0.225, 0.215, 0.272),
    "seat_current_bid_2": (0.120, 0.372, 0.215, 0.419),
    "seat_current_bid_3": (0.120, 0.520, 0.215, 0.567),
    "seat_current_bid_4": (0.120, 0.668, 0.215, 0.715),
    
    # 4. 终局结算大账单 (成交价、实际价值、净收益)
    "settlement_summary_row": (0.20, 0.22, 0.80, 0.42),
    
    # 5. 拍卖场核心有效计算区域 (裁剪无关背景，极速 OCR)
    "auction_main_canvas": (0.02, 0.00, 0.98, 0.98),
    # 5a2. 局内集中开局快检 ROI（覆盖顶栏回合/倒计时 + 中央情报卡栈 + 底部箱型）
    "focused_opening_canvas": (0.32, 0.02, 0.76, 0.88),
    # 5b. 局内右侧「我的资产」完整可见网格。HUD 应从捕获层排除，不再靠缩 ROI。
    "warehouse_board": (0.685, 0.196, 0.978, 0.755),
    
    # 6. 大厅右下备战区（兜底大图，不要每帧扫）
    "lobby_right_panel": (0.55, 0.45, 0.98, 0.98),
    # 6b. 选择会场三列大卡（仅选场页）
    "lobby_venue_picker": (0.08, 0.18, 0.92, 0.90),
    # 6c. 当前会场胶囊「当前：珊瑚场」
    "lobby_venue_chip": (0.62, 0.52, 0.84, 0.64),
    # 6c2. 当前会场搜索区（闭集模板）
    "lobby_venue_search": (0.62, 0.53, 0.82, 0.63),
    # 6d. 助手名字（右下角色卡，OCR 兜底）
    "lobby_character_chip": (0.82, 0.74, 0.97, 0.88),
    # 6d2. 助手立绘搜索区（闭集模板，含整张角色卡）
    "lobby_character_search": (0.83, 0.66, 0.97, 0.88),
    # 6e. 仪器组标题
    "lobby_tool_chip": (0.62, 0.68, 0.84, 0.78),
    # 6e2. 仪器组标题搜索区（闭集模板）
    "lobby_tool_search": (0.61, 0.68, 0.83, 0.76),

    # 7. 对局前导航快扫：顶栏 HUD（F5 / 都市大亨 / MENU 都市闲趣）
    "nav_top_chrome": (0.00, 0.00, 0.55, 0.22),
    # 8. 左上角标题胶囊（都市大亨 / 即刻落槌）
    "nav_title_chip": (0.00, 0.00, 0.32, 0.14),
    # 9. 对局前导航快扫：底栏（UID / Enter / 血量 / 时速）
    "nav_bottom_chrome": (0.00, 0.86, 0.55, 1.00),
}

class ROIScaler:
    @staticmethod
    def get_viewport_rect(width: int, height: int, target_aspect: float = 16.0 / 9.0) -> Tuple[int, int, int, int]:
        """
        计算消除黑边后的真实 16:9 内容视口 (vx, vy, vw, vh)
        """
        if width <= 0 or height <= 0:
            return (0, 0, width, height)

        current_aspect = width / float(height)
        
        # 宽屏带黑边 (Letterbox / 带鱼屏 Pillarbox)
        if abs(current_aspect - target_aspect) < 0.02:
            return (0, 0, width, height)
        elif current_aspect > target_aspect:
            # 屏幕过宽，左右有黑边 (Pillarbox)
            vw = int(height * target_aspect)
            vh = height
            vx = (width - vw) // 2
            vy = 0
            return (vx, vy, vw, vh)
        else:
            # 屏幕过高 (16:10)，上下有黑边 (Letterbox)
            vw = width
            vh = int(width / target_aspect)
            vx = 0
            vy = (height - vh) // 2
            return (vx, vy, vw, vh)

    @classmethod
    def scale_roi(cls, roi_key: str, width: int, height: int) -> Tuple[int, int, int, int]:
        """
        根据归一化比例计算目标分辨率下的绝对像素裁剪区域 (x1, y1, x2, y2)
        """
        norm_box = NORMALIZED_ROIS.get(roi_key, (0.0, 0.0, 1.0, 1.0))
        vx, vy, vw, vh = cls.get_viewport_rect(width, height)
        
        nx1, ny1, nx2, ny2 = norm_box
        x1 = vx + int(nx1 * vw)
        y1 = vy + int(ny1 * vh)
        x2 = vx + int(nx2 * vw)
        y2 = vy + int(ny2 * vh)

        # 边界保护
        x1 = max(0, min(width - 1, x1))
        y1 = max(0, min(height - 1, y1))
        x2 = max(x1 + 1, min(width, x2))
        y2 = max(y1 + 1, min(height, y2))

        return (x1, y1, x2, y2)

    @classmethod
    def crop_roi(cls, frame: np.ndarray, roi_key: str) -> np.ndarray:
        """从图像帧中直接按比例裁剪对应 ROI"""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = cls.scale_roi(roi_key, w, h)
        return frame[y1:y2, x1:x2]
