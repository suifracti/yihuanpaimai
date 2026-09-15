import os, sys, time, ctypes, json
import numpy as np
import win32gui, win32con

PROJECT_ROOT = r"D:\yihuanpaimai"
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
HTML_PATH = os.path.join(CORE_DIR, "tactical_hud.html")
DLL_PATH = os.path.join(PROJECT_ROOT, "app", "DirectCompositionHost.dll")
WV2_DLL = r"C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll"
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'

import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
clr.AddReference('System.IO')
clr.AddReference(WV2_DLL)
clr.AddReference(DLL_PATH)

from System.Threading import Thread, ThreadStart, ApartmentState
import System.Windows.Forms as WinForms
from Microsoft.Web.WebView2.Core import CoreWebView2Environment
from NTE.DirectComposition import DirectCompositionHudForm

user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000

def test_p0_fixes():
    print("==================================================")
    print("TESTING P0-1 (OBSERVATION GATE) & P0-2 (MOUSE DRAG)")
    print("==================================================")

    init_x, init_y = 300, 300
    form_ref = None
    env_ref = None
    hud_hwnd = None

    def _gui():
        nonlocal form_ref, env_ref, hud_hwnd
        form = DirectCompositionHudForm(init_x, init_y, 390, 450, True)
        form_ref = form
        form.Show()
        hud_hwnd = form.Handle.ToInt64()

        data_folder = os.path.join(PROJECT_ROOT, "build", "wv2_p0_test")
        os.makedirs(data_folder, exist_ok=True)

        env_task = CoreWebView2Environment.CreateAsync(None, data_folder, None)
        while not env_task.IsCompleted:
            WinForms.Application.DoEvents()
        env = env_task.Result
        env_ref = env

        form.InitializeComposition(env, HTML_PATH)

        # Handle begin_drag callback
        def on_msg(msg_str):
            try:
                data = json.loads(msg_str)
                if data.get("action") == "begin_drag":
                    form.BeginDrag()
            except Exception:
                pass
        form.WebMessageReceivedCallback += on_msg

        t_end = time.time() + 10.0
        while time.time() < t_end:
            WinForms.Application.DoEvents()
            time.sleep(0.02)

        form.Close()

    t = Thread(ThreadStart(_gui))
    t.SetApartmentState(ApartmentState.STA)
    t.Start()

    time.sleep(2.5) # Wait for form to initialize

    # Test 1: P0-2 Human-Like Mouse Dragging on Title Bar
    print("\n[TEST P0-2] Simulating Human Mouse Drag on Title Bar Blank Area...")
    rect1 = win32gui.GetWindowRect(hud_hwnd)
    print(f"  Window position before drag: ({rect1[0]}, {rect1[1]})")

    # Start drag at title bar blank area: x = rect1[0] + 60, y = rect1[1] + 15
    start_x = rect1[0] + 60
    start_y = rect1[1] + 15
    user32.SetCursorPos(start_x, start_y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)

    # Move mouse smoothly in 10 steps (+100px x, +80px y)
    target_dx = 100
    target_dy = 80
    for step in range(1, 11):
        cx = start_x + int(target_dx * (step / 10.0))
        cy = start_y + int(target_dy * (step / 10.0))
        user32.SetCursorPos(cx, cy)
        time.sleep(0.02)

    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.2)

    rect2 = win32gui.GetWindowRect(hud_hwnd)
    print(f"  Window position after drag: ({rect2[0]}, {rect2[1]})")
    actual_dx = rect2[0] - rect1[0]
    actual_dy = rect2[1] - rect1[1]
    print(f"  Actual displacement: dx={actual_dx}, dy={actual_dy}")

    assert actual_dx == target_dx and actual_dy == target_dy, f"Drag failed! Expected ({target_dx}, {target_dy}), got ({actual_dx}, {actual_dy})"
    print("  >>> P0-2 Human Mouse Drag PASSED!")

    # Test 2: P0-1 Game Presence & Standby Validity Gate
    print("\n[TEST P0-1] Verifying Standby Observation Validity Gate...")
    from window_tracker import GameWindowTracker
    tracker = GameWindowTracker()
    game_hwnd = tracker.find_game_window()
    print(f"  Current Game Window Detected: {game_hwnd} (Expected None when game not running)")
    assert game_hwnd is None, "Game window unexpectedly detected during test"

    from vision_pipeline import NTEVisionPipeline
    pipeline = NTEVisionPipeline()
    ctx_init = pipeline.current_context
    print(f"  Initial pipeline inAuction: {ctx_init.get('inAuction')}, round: {ctx_init.get('round')}")
    assert ctx_init.get('inAuction') is False, "Pipeline should start with inAuction=False"
    assert ctx_init.get('round') == 0, "Pipeline should start with round=0"

    # Test with blank/desktop screen frame
    blank_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    ctx_blank = pipeline.process_frame(blank_frame)
    print(f"  Blank frame pipeline inAuction: {ctx_blank.get('inAuction')}, round: {ctx_blank.get('round')}")
    assert ctx_blank.get('inAuction') is False, "Blank frame should yield inAuction=False"
    assert ctx_blank.get('round') == 0, "Blank frame should yield round=0"

    print("  >>> P0-1 Observation Validity Gate PASSED!")

    t.Join()
    print("\n==================================================")
    print("ALL P0 FIXES VERIFIED SUCCESSFULLY (100%)!")
    print("==================================================")

if __name__ == "__main__":
    test_p0_fixes()
