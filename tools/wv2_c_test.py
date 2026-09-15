import ctypes, sys, os
from ctypes import wintypes, c_void_p, c_int, c_wchar_p, POINTER, Structure, byref, HRESULT, WINFUNCTYPE

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
ole32 = ctypes.windll.ole32

ole32.CoInitialize(None)

loader_path = r'C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native\WebView2Loader.dll'
loader = ctypes.CDLL(loader_path)
print("Loader loaded:", loader)

# Test CreateCoreWebView2EnvironmentWithOptions
# HRESULT CreateCoreWebView2EnvironmentWithOptions(
#   PCWSTR browserExecutableFolder,
#   PCWSTR userDataFolder,
#   ICoreWebView2EnvironmentOptions* environmentOptions,
#   ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler* environment_created_handler
# );
print("Functions in loader:", [f for f in dir(loader) if "Create" in f or "WebView" in f])
