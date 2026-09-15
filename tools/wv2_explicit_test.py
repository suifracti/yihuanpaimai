import clr, sys, os
from System.Threading import Thread, ThreadStart, ApartmentState
clr.AddReference('System.Windows.Forms')
clr.AddReference(r'C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll')
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'

import System.Windows.Forms as WinForms
from Microsoft.Web.WebView2.Core import CoreWebView2Environment

def run_gui():
    form = WinForms.Form()
    form.Show()
    data_folder = r'D:\yihuanpaimai\build\wv2_data_explicit'
    browser_folder = r'C:\Program Files (x86)\Microsoft\EdgeWebView\Application\149.0.4022.52'
    os.makedirs(data_folder, exist_ok=True)
    
    env_task = CoreWebView2Environment.CreateAsync(browser_folder, data_folder, None)
    while not env_task.IsCompleted:
        WinForms.Application.DoEvents()
    env = env_task.Result
    print("Env status:", env_task.Status)
    
    ctrl_task = env.CreateCoreWebView2ControllerAsync(form.Handle)
    while not ctrl_task.IsCompleted:
        WinForms.Application.DoEvents()
        
    print("Controller status:", ctrl_task.Status)
    if ctrl_task.IsFaulted:
        print("Controller Exception:", ctrl_task.Exception)
    else:
        print("SUCCESS!!!")
    form.Close()

t = Thread(ThreadStart(run_gui))
t.SetApartmentState(ApartmentState.STA)
t.Start()
t.Join()
