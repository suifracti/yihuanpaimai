import win32api, win32process
import clr, sys, os
from System.Threading import Thread, ThreadStart, ApartmentState
clr.AddReference('System.Windows.Forms')
clr.AddReference(r'C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll')
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'
import System.Windows.Forms as WinForms
from Microsoft.Web.WebView2.Core import CoreWebView2Environment

def run():
    form = WinForms.Form()
    form.Show()
    data_folder = r'D:\yihuanpaimai\build\wv2_data'
    t = CoreWebView2Environment.CreateAsync(None, data_folder, None)
    while not t.IsCompleted:
        WinForms.Application.DoEvents()
    print("Env completed!")
    h = win32api.GetModuleHandle('WebView2Loader.dll')
    print('WebView2Loader module handle:', h)
    if h:
        name = win32process.GetModuleFileNameEx(win32process.GetCurrentProcess(), h)
        print('WebView2Loader path:', name)
    form.Close()

t = Thread(ThreadStart(run))
t.SetApartmentState(ApartmentState.STA)
t.Start()
t.Join()
