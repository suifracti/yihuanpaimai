import clr, sys, os, time, json
import numpy as np
from PIL import Image

PROJECT_ROOT = r"D:\yihuanpaimai"
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
HTML_PATH = os.path.join(CORE_DIR, "tactical_hud.html")
DLL_PATH = os.path.join(PROJECT_ROOT, "app", "DirectCompositionHost.dll")
WV2_DLL = r"C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll"
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
clr.AddReference('System.IO')
clr.AddReference(WV2_DLL)
clr.AddReference(DLL_PATH)

from System.Threading import Thread, ThreadStart, ApartmentState
from System.IO import FileStream, FileMode
import System.Windows.Forms as WinForms
from Microsoft.Web.WebView2.Core import CoreWebView2Environment, CoreWebView2CapturePreviewImageFormat
from NTE.DirectComposition import DirectCompositionHudForm

def test_visual_rendering():
    capture_path = os.path.join(PROJECT_ROOT, "build", "hud_visual_test.png")
    os.makedirs(os.path.dirname(capture_path), exist_ok=True)
    if os.path.exists(capture_path):
        os.remove(capture_path)

    def _gui():
        form = DirectCompositionHudForm(200, 200, 390, 450, True)
        form.Show()

        data_folder = os.path.join(PROJECT_ROOT, "build", "wv2_visual_test")
        os.makedirs(data_folder, exist_ok=True)

        env_task = CoreWebView2Environment.CreateAsync(None, data_folder, None)
        while not env_task.IsCompleted:
            WinForms.Application.DoEvents()
        env = env_task.Result

        form.InitializeComposition(env, HTML_PATH)

        # Wait 3.5s for full rendering
        t_end = time.time() + 3.5
        while time.time() < t_end:
            WinForms.Application.DoEvents()
            time.sleep(0.05)

        # Capture preview from WebView2 directly
        fs = FileStream(capture_path, FileMode.Create)
        cap_task = form.WebView.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, fs)
        while not cap_task.IsCompleted:
            WinForms.Application.DoEvents()
        fs.Close()
        print(f"Captured WebView2 frame to {capture_path}")

        form.Close()

    t = Thread(ThreadStart(_gui))
    t.SetApartmentState(ApartmentState.STA)
    t.Start()
    t.Join()

    # Analyze captured image
    assert os.path.exists(capture_path), "Capture file not found"
    img = Image.open(capture_path)
    arr = np.array(img)
    print(f"Image dimensions: {img.size}")
    print(f"Image shape: {arr.shape}")

    # Check unique colors
    unique_colors = len(np.unique(arr.reshape(-1, arr.shape[-1]), axis=0))
    print(f"Unique colors in rendered HUD frame: {unique_colors}")
    print(f"Mean pixel brightness: {arr.mean():.2f}, Max brightness: {arr.max()}, Min brightness: {arr.min()}")

    # A completely black or unrendered frame would have unique_colors = 1 and mean = 0
    # A fully rendered HUD frame has hundreds of colors (golden card badges, green pills, buttons, grid preview cells)
    print(f"Sample color pixels present in HUD:")
    # Check green color in HUD (RGBA roughly around [52, 211, 153])
    green_pixels = np.sum((arr[:, :, 0] < 80) & (arr[:, :, 1] > 150) & (arr[:, :, 2] > 100))
    print(f"  Green status badge pixels count: {green_pixels}")
    # Check gold color in HUD (RGBA roughly around [250, 204, 21])
    gold_pixels = np.sum((arr[:, :, 0] > 200) & (arr[:, :, 1] > 180) & (arr[:, :, 2] < 50))
    print(f"  Golden action badge pixels count: {gold_pixels}")

    assert unique_colors > 100, f"Frame has too few colors: {unique_colors}"
    assert green_pixels > 0, "No green badge pixels found in rendered frame!"
    print("\n>>> VISUAL PRESENTATION VERIFICATION 100% SUCCESSFUL!")

if __name__ == "__main__":
    test_visual_rendering()
