"""
Neverness to Everness (异环) - 窗口级捕获与 HUD 视觉隔离安全引擎 (v0.65)

核心功能：
  1. Windows DWM 级别 HUD 自身视觉隔离 (WDA_EXCLUDEFROMCAPTURE)
  2. 优先 PrintWindow 抓游戏窗口自身像素，避免 mss 把叠在客户区上的 HUD 抓进视觉
  3. 游戏窗口句柄自动发现与精准坐标绑定
  4. 画面安全诊断 (黑屏检测、最小化检测、低对比度与遮挡告警)
"""

import sys
import os
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple, Dict, Any, List
import cv2
import numpy as np

# Windows API 常量
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011 # Windows 10 2004+ 专属免录屏/免截图属性
PW_RENDERFULLCONTENT = 0x00000002

class RECT(ctypes.Structure):
    _fields_ = [
        ('left', wintypes.LONG),
        ('top', wintypes.LONG),
        ('right', wintypes.LONG),
        ('bottom', wintypes.LONG)
    ]

class WindowCaptureManager:
    def __init__(self, game_title_keywords: Optional[List[str]] = None):
        self.keywords = game_title_keywords or ["异环", "Neverness", "NevernessToEverness", "NTE"]
        self.user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

    def set_hud_exclude_from_capture(self, hwnd: int) -> bool:
        """
        设置 HUD 窗口为 WDA_EXCLUDEFROMCAPTURE，彻底杜绝 HUD 悬浮窗被截图导致 OCR 自干扰
        [状态标记]: 机制已实现，待真实 HUD+mss 像素验证
        """
        if not self.user32 or not hwnd:
            return False
        try:
            res = self.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            return bool(res)
        except Exception:
            return False

    def set_hud_capturable(self, hwnd: int) -> bool:
        """设置 HUD 窗口为 WDA_NONE (0)，允许正常截图与录屏"""
        if not self.user32 or not hwnd:
            return False
        try:
            res = self.user32.SetWindowDisplayAffinity(hwnd, WDA_NONE)
            return bool(res)
        except Exception:
            return False

    def find_game_hwnd(self) -> Optional[int]:
        """Use the shared real-game gate; never probe our own UI synchronously."""
        if not self.user32:
            return None
        from window_tracker import GameWindowTracker
        return GameWindowTracker(target_titles=self.keywords).find_game_window()

    def capture_hwnd_pixels(self, hwnd: int) -> Optional[np.ndarray]:
        """抓指定窗口自己的客户区像素，不含叠在上面的其它顶层窗（HUD）。"""
        if not hwnd:
            return None
        try:
            from window_tracker import ensure_default_desktop
            ensure_default_desktop()
        except Exception:
            pass
        try:
            import win32gui
            import win32ui
        except Exception:
            return None
        try:
            wr = win32gui.GetWindowRect(int(hwnd))
            cr = win32gui.GetClientRect(int(hwnd))
            pt = win32gui.ClientToScreen(int(hwnd), (0, 0))
            win_w, win_h = int(wr[2] - wr[0]), int(wr[3] - wr[1])
            client_w, client_h = int(cr[2]), int(cr[3])
            if win_w < 64 or win_h < 64 or client_w < 64 or client_h < 64:
                return None
            hwnd_dc = win32gui.GetWindowDC(int(hwnd))
            src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            mem_dc = src_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(src_dc, win_w, win_h)
            mem_dc.SelectObject(bmp)
            ok = bool(ctypes.windll.user32.PrintWindow(int(hwnd), mem_dc.GetSafeHdc(), PW_RENDERFULLCONTENT))
            bits = bmp.GetBitmapBits(True)
            img = np.frombuffer(bits, dtype=np.uint8)
            try:
                win32gui.DeleteObject(bmp.GetHandle())
            except Exception:
                pass
            mem_dc.DeleteDC()
            src_dc.DeleteDC()
            win32gui.ReleaseDC(int(hwnd), hwnd_dc)
            if not ok or img.size != win_w * win_h * 4:
                return None
            full = img.reshape((win_h, win_w, 4))[:, :, :3]
            ox = max(0, min(win_w - 1, int(pt[0] - wr[0])))
            oy = max(0, min(win_h - 1, int(pt[1] - wr[1])))
            x2 = min(win_w, ox + client_w)
            y2 = min(win_h, oy + client_h)
            crop = full[oy:y2, ox:x2]
            if crop.size == 0:
                return None
            return crop.copy()
        except Exception:
            return None

    def _grab_client_mss(self, hwnd: int, sct) -> Optional[np.ndarray]:
        if sct is None or not hwnd:
            return None
        try:
            import win32gui
            pt = win32gui.ClientToScreen(int(hwnd), (0, 0))
            cr = win32gui.GetClientRect(int(hwnd))
            width, height = int(cr[2]), int(cr[3])
            if width < 64 or height < 64:
                return None
            shot = sct.grab({"left": int(pt[0]), "top": int(pt[1]), "width": width, "height": height})
            return np.array(shot)[:, :, :3]
        except Exception:
            return None

    def capture_game_client(self, hwnd: int, sct=None) -> Tuple[Optional[np.ndarray], str]:
        """优先 PrintWindow；黑屏/失败再退回 mss。mss 依赖 HUD 已设 WDA_EXCLUDEFROMCAPTURE。"""
        img = self.capture_hwnd_pixels(hwnd)
        if img is not None:
            diag = self.diagnose_frame_safety(img)
            if diag.get("reason") not in ("black_screen", "frame_empty", "resolution_too_small"):
                return img, "printwindow"
        fallback = self._grab_client_mss(hwnd, sct)
        if fallback is not None:
            diag = self.diagnose_frame_safety(fallback)
            if diag.get("reason") not in ("black_screen", "frame_empty", "resolution_too_small"):
                return fallback, "mss"
        return None, "none"

    def capture_foreground_client(self, hwnd: int) -> Optional[np.ndarray]:
        """Bounded desktop capture for the foreground-only scrolling session.

        PrintWindow can block on a game's render thread. The scrolling host
        already requires foreground ownership; never enter that synchronous call.
        """
        if not hwnd or self.user32 is None:
            return None
        if int(self.user32.GetForegroundWindow()) != int(hwnd):
            return None
        import mss
        with mss.mss() as sct:
            frame = self._grab_client_mss(hwnd, sct)
        if int(self.user32.GetForegroundWindow()) != int(hwnd):
            return None
        return frame

    def get_window_rect(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """获取目标窗口在屏幕上的绝对矩形区域 (left, top, width, height)"""
        if not self.user32 or not hwnd:
            return None
        rect = RECT()
        if self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            return (rect.left, rect.top, w, h)
        return None

    @staticmethod
    def diagnose_frame_safety(frame: Optional[np.ndarray]) -> Dict[str, Any]:
        """
        视觉安全体检：检测全黑屏、极端低对比度、窗口最小化等异常并输出诊断
        """
        if frame is None or frame.size == 0:
            return {
                "safe": False,
                "reason": "frame_empty",
                "message": "画面帧为空或读取失败"
            }

        h, w = frame.shape[:2]
        if w < 640 or h < 360:
            return {
                "safe": False,
                "reason": "resolution_too_small",
                "message": f"分辨率过小 ({w}x{h})，可能窗口已最小化"
            }

        # 灰度与亮度分布分析
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        mean_lum = float(np.mean(gray))
        std_lum = float(np.std(gray))

        if mean_lum < 5.0 and std_lum < 8.0:
            return {
                "safe": False,
                "reason": "black_screen",
                "message": "全黑屏：游戏可能处于切屏过渡或最小化状态"
            }

        if std_lum < 10.0:
            return {
                "safe": False,
                "reason": "low_contrast",
                "message": "画面对比度极低，无法稳定提取文字与藏品轮廓"
            }

        # 清晰度 (Laplacian 方差)
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        is_blurry = laplacian_var < 20.0

        return {
            "safe": True,
            "meanLuminance": round(mean_lum, 2),
            "contrastStd": round(std_lum, 2),
            "sharpnessVar": round(laplacian_var, 2),
            "isBlurry": is_blurry,
            "message": "画面质量健康" if not is_blurry else "画面模糊，建议核对渲染分辨率"
        }
