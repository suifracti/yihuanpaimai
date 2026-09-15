import ctypes, sys, os
from ctypes import wintypes
import clr
from System.Threading import Thread, ThreadStart, ApartmentState
clr.AddReference(r'C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll')
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'
from Microsoft.Web.WebView2.Core import CoreWebView2Environment
from System import IntPtr

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == 0x0010: # WM_CLOSE
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

wnd_proc_ptr = WNDPROC(wnd_proc)

class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ('style', wintypes.UINT),
        ('lpfnWndProc', WNDPROC),
        ('cbClsExtra', ctypes.c_int),
        ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE),
        ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HICON),
        ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR),
        ('lpszClassName', wintypes.LPCWSTR),
    ]

def run():
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpszClassName = "WV2DirectNativeTestClass"
    wc.hInstance = hinst
    wc.lpfnWndProc = wnd_proc_ptr
    user32.RegisterClassW(ctypes.byref(wc))
    
    hwnd = user32.CreateWindowExW(
        0, "WV2DirectNativeTestClass", "Native Window",
        0x10CF0000, # WS_OVERLAPPEDWINDOW | WS_VISIBLE
        100, 100, 400, 400, 0, 0, hinst, 0
    )
    print("Native HWND created:", hwnd)
    
    data_folder = r'D:\yihuanpaimai\build\wv2_data_native'
    os.makedirs(data_folder, exist_ok=True)
    
    t = CoreWebView2Environment.CreateAsync(None, data_folder, None)
    t.Wait()
    env = t.Result
    print("Env created:", env)
    
    int_ptr = IntPtr(hwnd)
    print("Calling CreateCoreWebView2ControllerAsync with IntPtr:", int_ptr)
    
    ctrl_t = env.CreateCoreWebView2ControllerAsync(int_ptr)
    
    # Message pump
    msg = wintypes.MSG()
    while not ctrl_t.IsCompleted:
        if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
            
    print("Controller task completed! Status:", ctrl_t.Status)
    if ctrl_t.IsFaulted:
        print("Controller Exception:", ctrl_t.Exception)
    else:
        print("CONTROLLER SUCCESS WITH NATIVE HWND!!!", ctrl_t.Result)
        ctrl_t.Result.CoreWebView2.Navigate("https://www.bing.com")

t = Thread(ThreadStart(run))
t.SetApartmentState(ApartmentState.STA)
t.Start()
t.Join()
