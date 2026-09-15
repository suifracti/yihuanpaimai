"""
Neverness to Everness (异环) - 游戏窗口自动吸附与跟踪 (v0.65)
"""

import os
import sys
import ctypes
import logging
import win32gui
import win32process
from typing import Optional, Tuple, Dict, Any, List

logger = logging.getLogger("WINDOW_SCAN")

LAUNCHER_TITLE_MARKERS = ("启动器", "launcher")
HUD_TITLE_MARKERS = (
    "战术助手",
    "战术 hud",
    "战术hud",
    "拍卖助手",
    "overlay alpha",
    "yihuan",
    "异环拍卖",
    "异环战术",
    "异环对局助手",
)
GAME_PROCESS_MARKERS = ("htgame", "neverness", "nte-win64", "hotta", "projectnte", "client-win64", "nte")
GAME_CLASS_MARKERS = ("unrealwindow",)
GAME_TITLE_MARKERS = ("异环", "neverness", "projectnte", "nte")
EXCLUDE_CLASS_PREFIXES = ("qt", "chrome", "windowsforms", "applicationframewindow")


def ensure_default_desktop() -> bool:
    """Attach the calling thread to the interactive 'Default' desktop if possible.
    Essential on Windows when background threads or packaged EXEs enumerate top-level windows.
    """
    try:
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32"):
            user32 = ctypes.windll.user32
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
                user32.CloseDesktop(hdesk)
                return True
    except Exception:
        pass
    return False


def _process_basename(pid: int) -> str:
    if not pid:
        return ""
    try:
        # 1. PROCESS_QUERY_LIMITED_INFORMATION (0x1000) works across UAC/elevation boundaries
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "kernel32"):
            kernel32 = ctypes.windll.kernel32
            h = kernel32.OpenProcess(0x1000, False, int(pid))
            if h:
                try:
                    import ctypes.wintypes
                    buf = ctypes.create_unicode_buffer(1024)
                    size = ctypes.wintypes.DWORD(1024)
                    if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        return os.path.basename(buf.value or "").lower()
                finally:
                    kernel32.CloseHandle(h)
    except Exception:
        pass
    # 2. Fallback to win32process
    try:
        import win32api
        import win32con
        access = win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ
        handle = win32api.OpenProcess(access, False, int(pid))
        if handle:
            try:
                path = win32process.GetModuleFileNameEx(handle, 0)
                return os.path.basename(path or "").lower()
            finally:
                win32api.CloseHandle(handle)
    except Exception:
        pass
    return ""


def score_window_candidate(
    hwnd: int, target_titles: Optional[Tuple[str, ...]] = None
) -> Tuple[int, Optional[str], Dict[str, Any]]:
    """Score a window candidate for being the real game client.
    Returns: (score, reject_reason, meta_dict)
    """
    meta: Dict[str, Any] = {
        "hwnd": int(hwnd) if hwnd else 0,
        "pid": 0,
        "process": "",
        "title": "",
        "class": "",
        "visible": False,
        "rect": (0, 0, 0, 0),
        "score": 0,
        "rejectReason": None,
    }
    if not hwnd:
        meta["rejectReason"] = "NULL_HWND"
        return 0, "NULL_HWND", meta

    ensure_default_desktop()

    try:
        if not win32gui.IsWindow(hwnd):
            meta["rejectReason"] = "NOT_A_WINDOW"
            return 0, "NOT_A_WINDOW", meta

        visible = bool(win32gui.IsWindowVisible(hwnd))
        meta["visible"] = visible
        if not visible:
            meta["rejectReason"] = "NOT_VISIBLE"
            return 0, "NOT_VISIBLE", meta

        if win32gui.IsIconic(hwnd):
            meta["rejectReason"] = "MINIMIZED"
            return 0, "MINIMIZED", meta

        # Checking PID before GetWindowText avoids deadlock on UI thread
        _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
        meta["pid"] = pid
        if pid == os.getpid():
            meta["rejectReason"] = "OWN_PROCESS"
            return 0, "OWN_PROCESS", meta

        title = (win32gui.GetWindowText(hwnd) or "").strip()
        meta["title"] = title
        cls = (win32gui.GetClassName(hwnd) or "").strip()
        meta["class"] = cls
        cls_lower = cls.lower()
        title_lower = title.lower()
        compact_title = title.replace(" ", "").lower()

        rect = win32gui.GetWindowRect(hwnd)
        meta["rect"] = rect
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]

        # Check negative markers
        if any(mark in title_lower for mark in HUD_TITLE_MARKERS):
            meta["rejectReason"] = "HUD_OR_ASSISTANT_TITLE"
            return 0, "HUD_OR_ASSISTANT_TITLE", meta

        if any(mark in title_lower for mark in LAUNCHER_TITLE_MARKERS) or "启动器" in compact_title:
            meta["rejectReason"] = "LAUNCHER_TITLE"
            return 0, "LAUNCHER_TITLE", meta

        if any(cls_lower.startswith(p) for p in EXCLUDE_CLASS_PREFIXES):
            meta["rejectReason"] = "ASSISTANT_OR_BROWSER_CLASS"
            return 0, "ASSISTANT_OR_BROWSER_CLASS", meta

        if w < 300 or h < 200:
            meta["rejectReason"] = "TOO_SMALL"
            return 0, "TOO_SMALL", meta

        exe = _process_basename(pid)
        meta["process"] = exe

        if any(mark in exe for mark in ("yihuan", "异环拍卖助手", "msedgewebview2")):
            meta["rejectReason"] = "ASSISTANT_PROCESS"
            return 0, "ASSISTANT_PROCESS", meta

        # Positive scoring
        score = 0
        if any(mark in cls_lower for mark in GAME_CLASS_MARKERS):
            score += 35

        if any(mark in exe for mark in GAME_PROCESS_MARKERS):
            score += 40

        title_markers = set(GAME_TITLE_MARKERS)
        if target_titles:
            for t in target_titles:
                clean_t = str(t).strip().lower()
                if clean_t:
                    title_markers.add(clean_t)

        if any(mark in title_lower for mark in title_markers):
            score += 45

        if w >= 1280 and h >= 720:
            score += 15
        elif w >= 800 and h >= 600:
            score += 5

        meta["score"] = score
        if score < 40:
            meta["rejectReason"] = f"SCORE_TOO_LOW_{score}"
            return score, f"SCORE_TOO_LOW_{score}", meta

        return score, None, meta

    except Exception as exc:
        meta["rejectReason"] = f"EXCEPTION_{type(exc).__name__}"
        return 0, meta["rejectReason"], meta


def is_real_game_window(hwnd) -> bool:
    """Only a real game client may own the overlay. Never the launcher."""
    score, reject_reason, _meta = score_window_candidate(hwnd)
    return bool(not reject_reason and score >= 40)


class GameWindowTracker:
    def __init__(self, target_titles=("异环", "NevernessToEverness", "NTE", "ProjectNTE", "UnrealWindow", "Hotta")):
        self.target_titles = tuple(str(t).lower() for t in (target_titles or ()))
        self.own_pid = os.getpid()

    def find_game_window(self) -> Optional[int]:
        """Find the real game client HWND with highest score. Never return the launcher or our overlay."""
        ensure_default_desktop()
        candidates: List[Tuple[int, int, Dict[str, Any]]] = []

        def enum_cb(hwnd, extra):
            try:
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    return True
                score, reject_reason, meta = score_window_candidate(hwnd, self.target_titles)
                title = meta.get("title") or ""
                proc = meta.get("process") or ""
                cls = meta.get("class") or ""
                is_interesting = (
                    score > 0
                    or any(k in title.lower() for k in ("异环", "neverness", "hud", "助手", "game"))
                    or any(k in proc.lower() for k in ("htgame", "neverness", "python", "yihuan"))
                    or "unreal" in cls.lower()
                )
                if is_interesting:
                    logger.info(
                        "WINDOW_SCAN candidate: hwnd=%s pid=%s process=%s title=%r class=%r visible=%s rect=%s score=%s rejectReason=%s",
                        meta["hwnd"],
                        meta["pid"],
                        meta["process"],
                        meta["title"],
                        meta["class"],
                        meta["visible"],
                        meta["rect"],
                        meta["score"],
                        meta["rejectReason"],
                    )
                if not reject_reason and score >= 40:
                    candidates.append((score, hwnd, meta))
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass

        if candidates:
            # Pick highest score, break ties with larger client area
            candidates.sort(
                key=lambda item: (
                    item[0],
                    (item[2]["rect"][2] - item[2]["rect"][0]) * (item[2]["rect"][3] - item[2]["rect"][1]),
                ),
                reverse=True,
            )
            return candidates[0][1]

        return None

    def get_snap_position(self, hud_width=390, hud_height=450, padding_right=20, padding_top=40) -> Optional[Tuple[int, int]]:
        """获取 HUD 应当吸附的屏幕坐标 (X, Y)"""
        hwnd = self.find_game_window()
        if not hwnd:
            return None

        try:
            rect = win32gui.GetWindowRect(hwnd)  # (left, top, right, bottom)
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top

            if width <= 300 or height <= 300:
                return None  # 最小化或不可见时忽略

            # 目标位置：贴在游戏窗口内部的右上角
            snap_x = right - hud_width - padding_right
            snap_y = top + padding_top

            return (snap_x, snap_y)
        except Exception:
            return None
