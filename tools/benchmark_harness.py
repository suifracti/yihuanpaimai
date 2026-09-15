import clr, sys, os, ctypes, json
import ctypes.wintypes
from System.Threading import Thread, ThreadStart, ApartmentState
from System import IntPtr

clr.AddReference('System.Windows.Forms')
clr.AddReference(r'C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll')
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'

import System.Windows.Forms as WinForms
from Microsoft.Web.WebView2.Core import CoreWebView2Environment

def is_elevated_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except:
        return False

def run_benchmark(dpi_mode=None, test_name=""):
    is_admin = is_elevated_admin()
    results = {
        "test_name": test_name,
        "is_admin": is_admin,
        "integrity_name": "High (Admin)" if is_admin else "Medium (Standard Non-Admin)",
        "dpi_mode": str(dpi_mode),
        "initial_form_hwnd": None,
        "shown_form_hwnd": None,
        "hwnd_recreated": False,
        "standard_controller_status": None,
        "standard_controller_hresult": None,
        "standard_controller_error": None,
        "composition_controller_status": None,
        "composition_controller_hresult": None,
        "composition_controller_error": None
    }

    if dpi_mode == "PerMonitorV2":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception as e:
            results["dpi_set_error"] = str(e)

    def _gui():
        form = WinForms.Form()
        form.Text = f"Benchmark: {test_name}"
        form.Width = 390
        form.Height = 450
        
        # Read Handle before show
        h_before = form.Handle.ToInt64()
        results["initial_form_hwnd"] = h_before
        
        form.Show()
        
        h_after = form.Handle.ToInt64()
        results["shown_form_hwnd"] = h_after
        results["hwnd_recreated"] = (h_before != h_after)
        
        data_folder = os.path.join(r"D:\yihuanpaimai\build", f"wv2_bench_{os.getpid()}_{test_name}")
        os.makedirs(data_folder, exist_ok=True)
        
        env_task = CoreWebView2Environment.CreateAsync(None, data_folder, None)
        while not env_task.IsCompleted:
            WinForms.Application.DoEvents()
        env = env_task.Result
        
        # 1. Test Standard Controller
        try:
            ctrl_task = env.CreateCoreWebView2ControllerAsync(form.Handle)
            while not ctrl_task.IsCompleted:
                WinForms.Application.DoEvents()
            results["standard_controller_status"] = str(ctrl_task.Status)
            if ctrl_task.IsFaulted:
                inner = ctrl_task.Exception.InnerExceptions[0]
                results["standard_controller_error"] = inner.Message
                results["standard_controller_hresult"] = hex(inner.ErrorCode & 0xFFFFFFFF) if hasattr(inner, 'ErrorCode') else hex(inner.HResult & 0xFFFFFFFF) if hasattr(inner, 'HResult') else None
            else:
                results["standard_controller_hresult"] = "0x0 (S_OK)"
        except Exception as ex:
            results["standard_controller_status"] = "Exception"
            results["standard_controller_error"] = str(ex)
            
        # 2. Test Composition Controller (Control)
        try:
            data_folder_comp = os.path.join(r"D:\yihuanpaimai\build", f"wv2_bench_comp_{os.getpid()}_{test_name}")
            os.makedirs(data_folder_comp, exist_ok=True)
            env_comp_task = CoreWebView2Environment.CreateAsync(None, data_folder_comp, None)
            while not env_comp_task.IsCompleted:
                WinForms.Application.DoEvents()
            env_comp = env_comp_task.Result
            
            comp_task = env_comp.CreateCoreWebView2CompositionControllerAsync(form.Handle)
            while not comp_task.IsCompleted:
                WinForms.Application.DoEvents()
            results["composition_controller_status"] = str(comp_task.Status)
            if comp_task.IsFaulted:
                inner_comp = comp_task.Exception.InnerExceptions[0]
                results["composition_controller_error"] = inner_comp.Message
                results["composition_controller_hresult"] = hex(inner_comp.ErrorCode & 0xFFFFFFFF) if hasattr(inner_comp, 'ErrorCode') else hex(inner_comp.HResult & 0xFFFFFFFF) if hasattr(inner_comp, 'HResult') else None
            else:
                results["composition_controller_hresult"] = "0x0 (S_OK)"
        except Exception as ex:
            results["composition_controller_status"] = "Exception"
            results["composition_controller_error"] = str(ex)

        form.Close()

    t = Thread(ThreadStart(_gui))
    t.SetApartmentState(ApartmentState.STA)
    t.Start()
    t.Join()
    
    out_json = json.dumps(results, ensure_ascii=False, indent=2)
    print("BENCHMARK_RESULT:\n" + out_json)
    out_path = os.path.join(r"D:\yihuanpaimai\build", f"bench_{test_name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_json)

if __name__ == "__main__":
    dpi = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "None" else None
    name = sys.argv[2] if len(sys.argv) > 2 else "default"
    run_benchmark(dpi_mode=dpi, test_name=name)
