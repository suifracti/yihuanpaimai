"""Foreground keyboard/mouse hints; never inject input or certify a scene."""
import sys

class KeyboardSceneHints:
    def __init__(self):
        self.last_frame=None

    def poll(self,frame,hwnd,scene):
        if frame is self.last_frame:return []
        self.last_frame=frame
        if sys.platform!='win32' or not hwnd:return []
        import ctypes
        from ctypes import wintypes
        user=ctypes.windll.user32
        user.GetForegroundWindow.restype=wintypes.HWND
        if user.GetForegroundWindow()!=hwnd:return []
        if user.GetAsyncKeyState(0x74)&1:return ['CITY_TYCOON_HUB']
        if user.GetAsyncKeyState(0x1B)&1:return ['OPEN_WORLD','AUCTION_LOBBY','CITY_LEISURE_MENU']
        if user.GetAsyncKeyState(1)&1:
            point=wintypes.POINT(); rect=wintypes.RECT()
            if not user.GetCursorPos(ctypes.byref(point)):return []
            user.ScreenToClient(wintypes.HWND(hwnd),ctypes.byref(point))
            if not user.GetClientRect(wintypes.HWND(hwnd),ctypes.byref(rect)):return []
            x=point.x/max(1,rect.right);y=point.y/max(1,rect.bottom)
            if scene=='OPEN_WORLD' and .13<x<.20 and y<.13:return ['CITY_TYCOON_HUB']
            if scene=='CITY_TYCOON_HUB':return ['CITY_LEISURE_MENU','OPEN_WORLD']
            if scene in ('CITY_LEISURE_MENU','WORLD_MAP'):return ['AUCTION_LOBBY','WORLD_MAP','CITY_LEISURE_MENU','OPEN_WORLD']
            if scene=='AUCTION_LOBBY' and x>.62 and y>.88:return ['AUCTION_LOBBY','AUCTION_LOADING']
            if scene=='TOOL_REPLENISH':return ['TOOL_REPLENISH_CONFIRM','TOOL_REPLENISH','AUCTION_LOBBY']
        return []
