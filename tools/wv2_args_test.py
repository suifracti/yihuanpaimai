import clr, sys, os
from System.Threading import Thread, ThreadStart, ApartmentState
clr.AddReference('System.Windows.Forms')
clr.AddReference(r'C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll')
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'

import System.Windows.Forms as WinForms
from Microsoft.Web.WebView2.Core import CoreWebView2Environment, CoreWebView2EnvironmentOptions

def test_args(arg_str):
    form = WinForms.Form()
    form.Show()
    data_folder = r'D:\yihuanpaimai\build\wv2_data_args'
    os.makedirs(data_folder, exist_ok=True)
    
    opts = CoreWebView2EnvironmentOptions()
    opts.AdditionalBrowserArguments = arg_str
    
    env_t = CoreWebView2Environment.CreateAsync(None, data_folder, opts)
    while not env_t.IsCompleted:
        WinForms.Application.DoEvents()
    env = env_t.Result
    
    ctrl_t = env.CreateCoreWebView2ControllerAsync(form.Handle)
    while not ctrl_t.IsCompleted:
        WinForms.Application.DoEvents()
        
    print(f"Args: '{arg_str}' -> Status: {ctrl_t.Status}")
    if ctrl_t.IsFaulted:
        print(f"Exception: {ctrl_t.Exception.InnerExceptions[0].Message}")
    else:
        print("SUCCESS!!!")
    form.Close()

def run():
    for args in [
        "--disable-gpu",
        "--in-process-gpu",
        "--disable-features=RendererCodeIntegrity",
        "--no-sandbox --disable-gpu",
        "--disable-gpu-compositing",
    ]:
        test_args(args)

t = Thread(ThreadStart(run))
t.SetApartmentState(ApartmentState.STA)
t.Start()
t.Join()
