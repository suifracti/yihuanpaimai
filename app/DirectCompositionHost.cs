using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

namespace NTE.DirectComposition
{
    [ComImport]
    [Guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IDXGIDevice
    {
    }

    [ComImport]
    [Guid("4D93059D-097B-4651-9A60-F0F25116E2F3")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IDCompositionVisual
    {
        [PreserveSig]
        int SetOffsetX(float offsetX);
        [PreserveSig]
        int SetOffsetX_Anim(IntPtr animation);
        [PreserveSig]
        int SetOffsetY(float offsetY);
        [PreserveSig]
        int SetOffsetY_Anim(IntPtr animation);
        [PreserveSig]
        int SetTransform(IntPtr transform);
        [PreserveSig]
        int SetTransformParent(IDCompositionVisual visual);
        [PreserveSig]
        int SetEffect(IntPtr effect);
        [PreserveSig]
        int SetBitmapInterpolationMode(int mode);
        [PreserveSig]
        int SetBorderMode(int mode);
        [PreserveSig]
        int SetClip(IntPtr clip);
        [PreserveSig]
        int SetContent(IntPtr content);
        [PreserveSig]
        int AddVisual(IDCompositionVisual visual, bool insertAbove, IDCompositionVisual referenceVisual);
        [PreserveSig]
        int RemoveVisual(IDCompositionVisual visual);
        [PreserveSig]
        int RemoveAllVisuals();
        [PreserveSig]
        int SetCompositeMode(int mode);
    }

    [ComImport]
    [Guid("EACDD04C-117E-4E17-88F4-D1B12B0E3D89")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IDCompositionTarget
    {
        [PreserveSig]
        int SetRoot(IDCompositionVisual visual);
    }

    [ComImport]
    [Guid("C37EA93A-E7AA-450D-B16F-9746CB0407F3")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IDCompositionDevice
    {
        [PreserveSig]
        int Commit();
        [PreserveSig]
        int WaitForCommitCompletion();
        [PreserveSig]
        int GetFrameStatistics(IntPtr statistics);
        [PreserveSig]
        int CreateTargetForHwnd(IntPtr hwnd, bool topmost, out IDCompositionTarget target);
        [PreserveSig]
        int CreateVisual(out IDCompositionVisual visual);
        [PreserveSig]
        int CreateSurfaceControl(uint width, uint height, int pixelFormat, int alphaMode, out IntPtr surfaceControl);
    }

    public static class DCompNative
    {
        [DllImport("d3d11.dll", SetLastError = true)]
        public static extern int D3D11CreateDevice(
            IntPtr pAdapter,
            int DriverType,
            IntPtr Software,
            uint Flags,
            IntPtr pFeatureLevels,
            uint FeatureLevels,
            uint SDKVersion,
            out IntPtr ppDevice,
            out int pFeatureLevel,
            out IntPtr ppImmediateContext);

        [DllImport("dcomp.dll", SetLastError = true)]
        public static extern int DCompositionCreateDevice(
            IntPtr dxgiDevice,
            ref Guid iid,
            out IDCompositionDevice dcompositionDevice);

        [DllImport("user32.dll")]
        public static extern bool ReleaseCapture();

        [DllImport("user32.dll")]
        public static extern IntPtr SendMessage(IntPtr hWnd, int Msg, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW", SetLastError = true)]
        private static extern IntPtr SetWindowLongPtr64(IntPtr hWnd, int nIndex, IntPtr dwNewLong);

        [DllImport("user32.dll", EntryPoint = "SetWindowLongW", SetLastError = true)]
        private static extern int SetWindowLong32(IntPtr hWnd, int nIndex, int dwNewLong);

        public static IntPtr SetWindowLongPtr(IntPtr hWnd, int nIndex, IntPtr dwNewLong)
        {
            if (IntPtr.Size == 8)
                return SetWindowLongPtr64(hWnd, nIndex, dwNewLong);
            else
                return new IntPtr(SetWindowLong32(hWnd, nIndex, dwNewLong.ToInt32()));
        }

        public const int D3D_DRIVER_TYPE_HARDWARE = 1;
        public const uint D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0x20;
        public const uint D3D11_SDK_VERSION = 7;
        public static readonly Guid IID_IDCompositionDevice = new Guid("C37EA93A-E7AA-450D-B16F-9746CB0407F3");

        public static IDCompositionDevice CreateDevice()
        {
            IntPtr d3dDevice = IntPtr.Zero;
            IntPtr context = IntPtr.Zero;
            int featureLevel = 0;
            int hr = D3D11CreateDevice(
                IntPtr.Zero,
                D3D_DRIVER_TYPE_HARDWARE,
                IntPtr.Zero,
                D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                IntPtr.Zero,
                0,
                D3D11_SDK_VERSION,
                out d3dDevice,
                out featureLevel,
                out context);

            if (hr != 0 || d3dDevice == IntPtr.Zero)
            {
                // Fallback to WARP software driver
                hr = D3D11CreateDevice(
                    IntPtr.Zero,
                    2, // D3D_DRIVER_TYPE_WARP
                    IntPtr.Zero,
                    D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                    IntPtr.Zero,
                    0,
                    D3D11_SDK_VERSION,
                    out d3dDevice,
                    out featureLevel,
                    out context);
            }

            if (hr != 0 || d3dDevice == IntPtr.Zero)
            {
                throw new Exception("Failed to create D3D11 device: 0x" + hr.ToString("X8"));
            }

            IntPtr pDxgiDevice = IntPtr.Zero;
            Guid iidDxgi = new Guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c");
            hr = Marshal.QueryInterface(d3dDevice, ref iidDxgi, out pDxgiDevice);
            if (hr != 0 || pDxgiDevice == IntPtr.Zero)
            {
                Marshal.Release(d3dDevice);
                throw new Exception("Failed to query IDXGIDevice: 0x" + hr.ToString("X8"));
            }

            IDCompositionDevice dcompDevice = null;
            Guid iidDev = IID_IDCompositionDevice;
            hr = DCompositionCreateDevice(pDxgiDevice, ref iidDev, out dcompDevice);
            Marshal.Release(pDxgiDevice);
            Marshal.Release(d3dDevice);

            if (hr != 0 || dcompDevice == null)
            {
                throw new Exception("Failed to create DCompositionDevice: 0x" + hr.ToString("X8"));
            }

            return dcompDevice;
        }
    }

    public class DirectCompositionHudForm : Form
    {
        public IDCompositionDevice DCompDevice { get; private set; }
        public IDCompositionTarget DCompTarget { get; private set; }
        public IDCompositionVisual DCompRootVisual { get; private set; }
        public CoreWebView2CompositionController CompController { get; private set; }
        public CoreWebView2 WebView { get; private set; }

        public event Action<string> WebMessageReceivedCallback;

        private System.Windows.Forms.Timer _topmostTimer;
        private IntPtr _gameOwnerHwnd = IntPtr.Zero;
        private bool _compositionResourcesClosed;
        private const uint TopmostNoActivateFlags = 0x0013; // NOSIZE | NOMOVE | NOACTIVATE

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams cp = base.CreateParams;
                if (this.TopMost)
                {
                    cp.ExStyle |= 0x00000008; // WS_EX_TOPMOST (强置顶)
                }
                // 不写死 WS_EX_NOACTIVATE：启动不抢焦点靠 ShowWithoutActivation，
                // 用户点击后必须能正常激活、输入、拖动。
                return cp;
            }
        }

        protected override bool ShowWithoutActivation
        {
            get { return true; }
        }

        public DirectCompositionHudForm(int x, int y, int width, int height, bool topmost)
        {
            this.Text = "⚡ 异环拍卖战术助手 HUD";
            this.FormBorderStyle = FormBorderStyle.None;
            this.StartPosition = FormStartPosition.Manual;
            this.Location = new Point(x, y);
            this.Size = new Size(width, height);
            this.TopMost = topmost;
            this.BackColor = Color.FromArgb(0x12, 0x16, 0x1F);
            this.ShowInTaskbar = true;
            this.DoubleBuffered = true;

            this.SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint | ControlStyles.Opaque, true);

            // 启动高频置顶守护定时器 (200ms)
            if (topmost)
            {
                _topmostTimer = new System.Windows.Forms.Timer();
                _topmostTimer.Interval = 200;
                _topmostTimer.Tick += (s, e) =>
                {
                    try
                    {
                        // Refresh z-order without changing explicit Show()/Hide() visibility.
                        DCompNative.SetWindowPos(this.Handle, (IntPtr)(-1), 0, 0, 0, 0, TopmostNoActivateFlags);
                    }
                    catch { }
                };
                _topmostTimer.Start();
            }
        }

        public void SetGameOwner(IntPtr gameHwnd)
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action<IntPtr>(SetGameOwner), gameHwnd);
                return;
            }
            if (gameHwnd != IntPtr.Zero && gameHwnd != _gameOwnerHwnd)
            {
                _gameOwnerHwnd = gameHwnd;
                // GWLP_HWNDPARENT = -8: 将 HUD 设置为游戏窗口的从属窗口(Owned Window)
                // Windows 窗口管理器架构从底层保证从属窗口永远渲染在所有者窗口之上
                DCompNative.SetWindowLongPtr(this.Handle, -8, gameHwnd);
                DCompNative.SetWindowPos(this.Handle, (IntPtr)(-1), 0, 0, 0, 0, TopmostNoActivateFlags);
            }
        }

        public void ClearGameOwner()
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action(ClearGameOwner));
                return;
            }
            if (_gameOwnerHwnd == IntPtr.Zero)
            {
                return;
            }
            _gameOwnerHwnd = IntPtr.Zero;
            DCompNative.SetWindowLongPtr(this.Handle, -8, IntPtr.Zero);
            DCompNative.SetWindowPos(this.Handle, (IntPtr)(-1), 0, 0, 0, 0, TopmostNoActivateFlags);
        }

        public void ActivateOverlay()
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action(ActivateOverlay));
                return;
            }
            // 用户主动点到 Overlay 后才要前台/焦点；启动路径仍不抢焦点。
            this.Activate();
            this.Focus();
        }

        public void BeginDrag()
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action(BeginDrag));
                return;
            }
            this.ActivateOverlay();
            DCompNative.ReleaseCapture();
            DCompNative.SendMessage(this.Handle, 0x00A1, (IntPtr)2, IntPtr.Zero);
        }

        public void InitializeComposition(CoreWebView2Environment env, string htmlPath)
        {
            InitializeComposition(env, htmlPath, 8766);
        }

        public void InitializeComposition(CoreWebView2Environment env, string htmlPath, int websocketPort)
        {
            if (websocketPort < 1 || websocketPort > 65535)
                throw new ArgumentOutOfRangeException("websocketPort");
            // 1. Create DirectComposition Device & Visual Tree
            this.DCompDevice = DCompNative.CreateDevice();
            IDCompositionTarget target;
            int hrTarget = this.DCompDevice.CreateTargetForHwnd(this.Handle, true, out target);
            if (hrTarget != 0 || target == null)
            {
                throw new Exception("CreateTargetForHwnd failed: 0x" + hrTarget.ToString("X8"));
            }
            this.DCompTarget = target;

            IDCompositionVisual rootVisual;
            int hrVisual = this.DCompDevice.CreateVisual(out rootVisual);
            if (hrVisual != 0 || rootVisual == null)
            {
                throw new Exception("CreateVisual failed: 0x" + hrVisual.ToString("X8"));
            }
            this.DCompRootVisual = rootVisual;

            int hrRoot = this.DCompTarget.SetRoot(this.DCompRootVisual);
            if (hrRoot != 0)
            {
                throw new Exception("SetRoot failed: 0x" + hrRoot.ToString("X8"));
            }

            // 2. Create CoreWebView2CompositionController
            var ctrlTask = env.CreateCoreWebView2CompositionControllerAsync(this.Handle);
            while (!ctrlTask.IsCompleted)
            {
                Application.DoEvents();
            }

            if (ctrlTask.IsFaulted)
            {
                throw new Exception("CreateCoreWebView2CompositionControllerAsync faulted", ctrlTask.Exception);
            }

            this.CompController = ctrlTask.Result;
            try
            {
                this.CompController.DefaultBackgroundColor = Color.Transparent;
            }
            catch { }
            this.WebView = this.CompController.CoreWebView2;

            // 3. Connect RootVisualTarget to Visual Tree
            this.CompController.RootVisualTarget = this.DCompRootVisual;
            this.CompController.Bounds = new Rectangle(0, 0, this.ClientSize.Width, this.ClientSize.Height);
            this.CompController.IsVisible = true;

            // 4. Commit Visual Tree
            this.DCompDevice.Commit();

            // 5. Configure Settings & Bridge
            this.WebView.Settings.IsScriptEnabled = true;
            this.WebView.Settings.IsWebMessageEnabled = true;
            this.WebView.Settings.AreDevToolsEnabled = true;

            string bridgeScript = @"
            (function() {
                window.pywebview = {
                    api: {
                        exit_app: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'exit_app'})); },
                        snap_to_game: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'snap_to_game'})); },
                        open_config: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'open_config'})); },
                        open_lab: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'open_lab'})); },
                        report_hud_status: function(status) { window.chrome.webview.postMessage(JSON.stringify({action: 'report_hud_status', status: status})); },
                        start_live_vision: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'start_live_vision'})); },
                        begin_drag: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'begin_drag'})); },
                        get_pos: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'get_pos'})); },
                        set_pos: function(x, y) { window.chrome.webview.postMessage(JSON.stringify({action: 'set_pos', x: x, y: y})); },
                        move_rel: function(dx, dy) { window.chrome.webview.postMessage(JSON.stringify({action: 'move_rel', dx: dx, dy: dy})); }
                    }
                };
                window.dispatchEvent(new CustomEvent('pywebviewready'));
            })();";
            this.WebView.AddScriptToExecuteOnDocumentCreatedAsync(bridgeScript);

            this.WebView.WebMessageReceived += (s, e) =>
            {
                try
                {
                    string msg = e.TryGetWebMessageAsString();
                    if (WebMessageReceivedCallback != null)
                    {
                        WebMessageReceivedCallback(msg);
                    }
                }
                catch { }
            };

            // 6. Navigate to HTML
            var navigation = new UriBuilder(new Uri(Path.GetFullPath(htmlPath)));
            navigation.Fragment = "wsPort=" + websocketPort.ToString(System.Globalization.CultureInfo.InvariantCulture);
            this.WebView.Navigate(navigation.Uri.AbsoluteUri);
        }

        public void CloseCompositionResources()
        {
            if (this.InvokeRequired)
            {
                this.Invoke(new Action(CloseCompositionResources));
                return;
            }
            if (_compositionResourcesClosed)
            {
                return;
            }
            _compositionResourcesClosed = true;

            if (_topmostTimer != null)
            {
                _topmostTimer.Stop();
                _topmostTimer.Dispose();
                _topmostTimer = null;
            }
            WebMessageReceivedCallback = null;
            if (CompController != null)
            {
                CompController.Close();
                CompController = null;
            }
            WebView = null;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                CloseCompositionResources();
            }
            base.Dispose(disposing);
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            if (this.CompController != null && this.DCompDevice != null)
            {
                this.CompController.Bounds = new Rectangle(0, 0, this.ClientSize.Width, this.ClientSize.Height);
                this.DCompDevice.Commit();
            }
        }

        protected override void WndProc(ref Message m)
        {
            const int WM_WINDOWPOSCHANGING = 0x0046;
            const int WM_MOUSEMOVE = 0x0200;
            const int WM_LBUTTONDOWN = 0x0201;
            const int WM_LBUTTONUP = 0x0202;
            const int WM_LBUTTONDBLCLK = 0x0203;
            const int WM_RBUTTONDOWN = 0x0204;
            const int WM_RBUTTONUP = 0x0205;
            const int WM_RBUTTONDBLCLK = 0x0206;
            const int WM_MBUTTONDOWN = 0x0207;
            const int WM_MBUTTONUP = 0x0208;
            const int WM_MOUSEWHEEL = 0x020A;
            const int WM_MOUSELEAVE = 0x02A3;

            const int WM_NCHITTEST = 0x0084;
            const int HTCLIENT = 1;
            const int HTCAPTION = 2;

            // 拦截并强制保持 TopMost 层级
            if (m.Msg == WM_WINDOWPOSCHANGING && this.TopMost)
            {
                try
                {
                    Marshal.WriteIntPtr(m.LParam, IntPtr.Size, (IntPtr)(-1));
                }
                catch { }
            }

            // 统一由 HTML/JS 触发 begin_drag，全窗口返回 HTCLIENT 确保 WebView2 接收完整的 hover/click/drag 事件
            if (m.Msg == WM_NCHITTEST)
            {
                m.Result = (IntPtr)HTCLIENT;
                return;
            }

            if (this.CompController != null)
            {
                CoreWebView2MouseEventKind kind = (CoreWebView2MouseEventKind)(-1);
                switch (m.Msg)
                {
                    case WM_MOUSEMOVE: kind = CoreWebView2MouseEventKind.Move; break;
                    case WM_LBUTTONDOWN: kind = CoreWebView2MouseEventKind.LeftButtonDown; break;
                    case WM_LBUTTONUP: kind = CoreWebView2MouseEventKind.LeftButtonUp; break;
                    case WM_LBUTTONDBLCLK: kind = CoreWebView2MouseEventKind.LeftButtonDoubleClick; break;
                    case WM_RBUTTONDOWN: kind = CoreWebView2MouseEventKind.RightButtonDown; break;
                    case WM_RBUTTONUP: kind = CoreWebView2MouseEventKind.RightButtonUp; break;
                    case WM_RBUTTONDBLCLK: kind = CoreWebView2MouseEventKind.RightButtonDoubleClick; break;
                    case WM_MBUTTONDOWN: kind = CoreWebView2MouseEventKind.MiddleButtonDown; break;
                    case WM_MBUTTONUP: kind = CoreWebView2MouseEventKind.MiddleButtonUp; break;
                    case WM_MOUSEWHEEL: kind = CoreWebView2MouseEventKind.Wheel; break;
                    case WM_MOUSELEAVE: kind = CoreWebView2MouseEventKind.Leave; break;
                }

                if ((int)kind != -1)
                {
                    int x = unchecked((short)(m.LParam.ToInt64() & 0xFFFF));
                    int y = unchecked((short)((m.LParam.ToInt64() >> 16) & 0xFFFF));
                    if (m.Msg == WM_MOUSEWHEEL)
                    {
                        Point ptScreen = new Point(x, y);
                        Point ptClient = this.PointToClient(ptScreen);
                        x = ptClient.X;
                        y = ptClient.Y;
                    }

                    uint mouseData = (m.Msg == WM_MOUSEWHEEL) ? unchecked((uint)((m.WParam.ToInt64() >> 16) & 0xFFFF)) : 0;
                    CoreWebView2MouseEventVirtualKeys keys = CoreWebView2MouseEventVirtualKeys.None;
                    long w = m.WParam.ToInt64() & 0xFFFF;
                    if ((w & 0x0001) != 0) keys |= CoreWebView2MouseEventVirtualKeys.LeftButton;
                    if ((w & 0x0002) != 0) keys |= CoreWebView2MouseEventVirtualKeys.RightButton;
                    if ((w & 0x0004) != 0) keys |= CoreWebView2MouseEventVirtualKeys.Shift;
                    if ((w & 0x0008) != 0) keys |= CoreWebView2MouseEventVirtualKeys.Control;
                    if ((w & 0x0010) != 0) keys |= CoreWebView2MouseEventVirtualKeys.MiddleButton;

                    try
                    {
                        this.CompController.SendMouseInput(kind, keys, mouseData, new Point(x, y));
                    }
                    catch { }
                }
            }

            base.WndProc(ref m);
        }
        public Bitmap CaptureScreen()
        {
            Rectangle bounds = this.Bounds;
            Bitmap bmp = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format32bppArgb);
            using (Graphics g = Graphics.FromImage(bmp))
            {
                g.CopyFromScreen(bounds.Location, Point.Empty, bounds.Size);
            }
            return bmp;
        }

        public string CapturePreviewToFile(string path)
        {
            if (this.InvokeRequired)
            {
                string result = null;
                this.Invoke(new Action(() => { result = CapturePreviewToFile(path); }));
                return result;
            }
            if (this.WebView == null)
            {
                throw new Exception("WebView is not ready");
            }
            string full = Path.GetFullPath(path);
            string dir = Path.GetDirectoryName(full);
            if (!string.IsNullOrEmpty(dir))
            {
                Directory.CreateDirectory(dir);
            }
            using (FileStream stream = new FileStream(full, FileMode.Create, FileAccess.Write))
            {
                var task = this.WebView.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, stream);
                while (!task.IsCompleted)
                {
                    Application.DoEvents();
                }
                if (task.IsFaulted)
                {
                    throw task.Exception;
                }
                stream.Flush();
            }
            return full;
        }

        public string ExecuteScript(string script)
        {
            if (this.InvokeRequired)
            {
                string result = null;
                Exception failure = null;
                var completion = new System.Threading.Tasks.TaskCompletionSource<bool>();
                this.BeginInvoke(new Action(() => {
                    // A timed-out queued call must not run later on a new match.
                    if (completion.Task.IsCompleted) return;
                    try { result = ExecuteScript(script); }
                    catch (Exception ex) { failure = ex; }
                    finally { completion.TrySetResult(true); }
                }));
                if (!completion.Task.Wait(12000))
                {
                    completion.TrySetCanceled();
                    throw new TimeoutException("WEBVIEW_SCRIPT_DISPATCH_TIMEOUT");
                }
                if (failure != null) throw failure;
                return result;
            }
            if (this.WebView == null)
            {
                throw new Exception("WebView is not ready");
            }
            var task = this.WebView.ExecuteScriptAsync(script);
            var deadline = System.Diagnostics.Stopwatch.StartNew();
            while (!task.IsCompleted)
            {
                if (deadline.ElapsedMilliseconds >= 10000)
                    throw new TimeoutException("WEBVIEW_SCRIPT_TIMEOUT");
                Application.DoEvents();
                System.Threading.Thread.Sleep(1);
            }
            if (task.IsFaulted)
            {
                throw task.Exception;
            }
            return task.Result;
        }
    }

    public class DirectCompositionMainForm : Form
    {
        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams cp = base.CreateParams;
                if (this.TopMost)
                {
                    cp.ExStyle |= 0x00000008; // WS_EX_TOPMOST
                }
                return cp;
            }
        }

        public DirectCompositionMainForm()
        {
            this.Text = "异环拍卖助手";
            this.FormBorderStyle = FormBorderStyle.Sizable;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.ClientSize = new Size(1280, 660);
            this.MinimumSize = new Size(1100, 680);
            this.BackColor = Color.FromArgb(15, 17, 19);
            this.ShowInTaskbar = true;
            this.DoubleBuffered = true;
        }

        public void SetTopMostNoActivate(bool topmost)
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action<bool>(SetTopMostNoActivate), topmost);
                return;
            }
            if (this.TopMost == topmost)
            {
                return;
            }
            this.TopMost = topmost;
            IntPtr insertAfter = topmost ? (IntPtr)(-1) : (IntPtr)(-2); // HWND_TOPMOST (-1), HWND_NOTOPMOST (-2)
            DCompNative.SetWindowPos(this.Handle, insertAfter, 0, 0, 0, 0, 0x0013); // SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
        }
    }
}
