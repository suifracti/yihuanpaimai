using System.Runtime.InteropServices;
using System.Text;
using NteHost.DomainActions;
using NteHost.Input;

// Test application only. Known control rectangles and pixel code are NEVER
// registered as an HTGame profile. All OS input comes from production adapter.
sealed class Win32DummyWindow : IDisposable
{
    const string ClassName = "NteDomainDummyTarget";
    readonly Thread thread;
    readonly ManualResetEventSlim ready = new();
    readonly Proc procedure;
    Proc? editProcedure;
    IntPtr editOriginal;
    public IntPtr Hwnd, Edit, Submit;
    public int Clicks;
    public long Accepted;
    public string FieldText => Text(Edit);
    public Win32DummyWindow()
    {
        procedure = WindowProc;
        thread = new Thread(Run) { IsBackground = true };
        thread.Start();
        if (!ready.Wait(5000) || Hwnd == IntPtr.Zero) throw new Exception("DUMMY_WINDOW_UNAVAILABLE");
        SetForegroundWindow(Hwnd);
        if (!SpinWait.SpinUntil(() => GetForegroundWindow() == Hwnd, 1500)) throw new Exception("DUMMY_CANNOT_ACQUIRE_FOREGROUND");
    }
    void Run()
    {
        SetThreadDpiAwarenessContext(new(-4));
        var wc = new WndClass { Size = (uint)Marshal.SizeOf<WndClass>(), ClassName = ClassName,
            Procedure = Marshal.GetFunctionPointerForDelegate(procedure), Background = new(6) };
        // Same-process second dummy can reuse the registered class.
        RegisterClassEx(ref wc);
        Hwnd = CreateWindowEx(0x80, ClassName, "Sol-C restricted input DUMMY", 0x90000000,
            100, 100, 400, 280, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
        Edit = CreateWindowEx(0, "EDIT", "12", 0x50802000, 40, 40, 160, 36, Hwnd, new(101), IntPtr.Zero, IntPtr.Zero);
        Submit = CreateWindowEx(0, "BUTTON", "Submit dummy", 0x50000000, 40, 100, 160, 36, Hwnd, new(102), IntPtr.Zero, IntPtr.Zero);
        editProcedure = (h, message, w, l) => {
            if (message == 0x100 && w.ToInt64() == 0x41 && GetKeyState(0xA2) < 0)
            { SendMessage(h, 0xB1, IntPtr.Zero, new(-1)); return IntPtr.Zero; } // test app Ctrl+A handler
            return CallWindowProc(editOriginal, h, message, w, l);
        };
        editOriginal = SetWindowLongPtr(Edit, -4, Marshal.GetFunctionPointerForDelegate(editProcedure));
        ready.Set();
        while (GetMessage(out var msg, IntPtr.Zero, 0, 0) > 0) { TranslateMessage(ref msg); DispatchMessage(ref msg); }
    }
    IntPtr WindowProc(IntPtr hwnd, uint msg, IntPtr w, IntPtr l)
    {
        if (msg == 0x111 && (w.ToInt64() & 0xffff) == 102 && (w.ToInt64() >> 16) == 0)
        { Interlocked.Increment(ref Clicks); Accepted = long.TryParse(Text(Edit), out var amount) ? amount : -1; InvalidateRect(hwnd, IntPtr.Zero, true); }
        if (msg == 0xF)
        {
            var dc = BeginPaint(hwnd, out var paint);
            if (Edit != IntPtr.Zero) { DrawCode(dc, Text(Edit), 180); DrawCode(dc, Accepted.ToString(), 220); }
            EndPaint(hwnd, ref paint); return IntPtr.Zero;
        }
        if (msg == 0x10) { DestroyWindow(hwnd); return IntPtr.Zero; }
        if (msg == 2) { PostQuitMessage(0); return IntPtr.Zero; }
        return DefWindowProc(hwnd, msg, w, l);
    }
    static void DrawCode(IntPtr dc, string text, int y)
    {
        // Independently readable test capture cells: count, then actual field digits.
        DrawCell(dc, 20, y, text.Length);
        for (int i = 0; i < 7; i++) DrawCell(dc, 40 + i * 20, y, i < text.Length && char.IsDigit(text[i]) ? text[i] - '0' : 0);
    }
    static void DrawCell(IntPtr dc, int x, int y, int value)
    {
        var rect = new Rect { Left = x, Top = y, Right = x + 10, Bottom = y + 10 };
        var brush = CreateSolidBrush((uint)(40 + value * 20));
        FillRect(dc, ref rect, brush); DeleteObject(brush);
    }
    public NativeDomainFrame Capture(ActionScope scope)
    {
        InvalidateRect(Hwnd, IntPtr.Zero, true); UpdateWindow(Hwnd);
        GetClientRect(Hwnd, out var rect); var origin = new Point(); ClientToScreen(Hwnd, ref origin);
        int width = rect.Right, height = rect.Bottom;
        var dc = GetDC(Hwnd); var memory = CreateCompatibleDC(dc); var bitmap = CreateCompatibleBitmap(dc, width, height);
        var old = SelectObject(memory, bitmap);
        try
        {
            if (!BitBlt(memory, 0, 0, width, height, dc, 0, 0, 0x00CC0020)) throw new Exception("DUMMY_CAPTURE_FAILED");
            // Bitmap must be deselected before GetDIBits per Win32 contract.
            SelectObject(memory, old);
            var info = new BitmapInfo { Size = 40, Width = width, Height = -height, Planes = 1, BitCount = 32 };
            var bytes = new byte[width * height * 4];
            if (GetDIBits(dc, bitmap, 0, (uint)height, bytes, ref info, 0) != height) throw new Exception("DUMMY_READBACK_FAILED");
            long now = TraceClock.NowNs();
            return new(scope with { CapturedNs = now }, new(width, height, origin.X, origin.Y), bytes, width * 4);
        }
        finally { SelectObject(memory, old); DeleteObject(bitmap); DeleteDC(memory); ReleaseDC(Hwnd, dc); }
    }
    public void Dispose() { if (Hwnd != IntPtr.Zero) PostMessage(Hwnd, 0x10, IntPtr.Zero, IntPtr.Zero); thread.Join(2000); }
    static string Text(IntPtr hwnd) { var s = new StringBuilder(32); GetWindowText(hwnd, s, s.Capacity); return s.ToString(); }
    public void Activate() => SetForegroundWindow(Hwnd);
    public void ResetFieldForTest() { SetWindowText(Edit, "12"); InvalidateRect(Hwnd, IntPtr.Zero, true); }
    public static bool IsForeground(long hwnd) => GetForegroundWindow().ToInt64() == hwnd;
    static long DecodeNumber(NativeDomainFrame frame, int y)
    {
        int Read(int x) { int index = (y + 5) * frame.Stride + (x + 5) * 4 + 2; return (frame.Pixels.Span[index] - 40) / 20; }
        int count = Read(20); if (count is < 1 or > 7) throw new Exception("DUMMY_PIXEL_CODE_INVALID");
        long result = 0; for (int i = 0; i < count; i++) { int digit = Read(40 + i * 20); if (digit is < 0 or > 9) throw new Exception("DUMMY_DIGIT_INVALID"); result = result * 10 + digit; }
        return result;
    }
    public sealed class Decoder : IGameDomainFrameDecoder
    {
        public bool Drift;
        public bool BadAmount;
        public DecodedDomainFrame Decode(NativeDomainFrame f)
        {
            var s = f.Scope;
            var controls = new List<VisibleControlAnchor>();
            foreach (var kind in Enum.GetValues<DomainPrimitive>())
                controls.Add(new(kind, Drift ? 41 : 40, kind is DomainPrimitive.FocusAmountField or DomainPrimitive.ReplaceAmountDigits ? 40 : 100,
                    160, 36, f.Geometry, s.MatchId, s.MatchGeneration, s.ObservationSessionId, s.Round,
                    s.FactsRevision, s.Window, s.SourceSequence, s.CapturedNs, true, f.EvidenceRef, "NTE_DOMAIN_DUMMY_V1"));
            return new("AUCTION", s.Round, s.MatchId, s.MatchGeneration,
                new(1, "dummy-self", DecodeNumber(f, 220), true, f.EvidenceRef),
                BadAmount ? 999 : DecodeNumber(f, 180), controls);
        }
    }
    delegate IntPtr Proc(IntPtr h, uint m, IntPtr w, IntPtr l);
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct WndClass
    { public uint Size, Style; public IntPtr Procedure; public int ClassExtra, WindowExtra; public IntPtr Instance, Icon, Cursor, Background; public string? Menu; public string ClassName; public IntPtr IconSmall; }
    [StructLayout(LayoutKind.Sequential)] struct Message { public IntPtr Hwnd; public uint Id; public UIntPtr WParam; public IntPtr LParam; public uint Time; public Point Point; public uint Private; }
    [StructLayout(LayoutKind.Sequential)] struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] struct Paint { public IntPtr Dc; public int Erase; public Rect Rect; public int Restore, Update; [MarshalAs(UnmanagedType.ByValArray, SizeConst=32)] public byte[] Reserved; }
    [StructLayout(LayoutKind.Sequential)] struct BitmapInfo { public uint Size; public int Width, Height; public ushort Planes, BitCount; public uint Compression, SizeImage; public int XPels, YPels; public uint Used, Important; }
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern ushort RegisterClassEx(ref WndClass wc);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateWindowEx(uint ex, string cls, string text, uint style, int x,int y,int width,int height,IntPtr parent,IntPtr id,IntPtr instance,IntPtr data);
    [DllImport("user32.dll")] static extern int GetMessage(out Message msg,IntPtr hwnd,uint first,uint last);
    [DllImport("user32.dll")] static extern bool TranslateMessage(ref Message msg);
    [DllImport("user32.dll")] static extern IntPtr DispatchMessage(ref Message msg);
    [DllImport("user32.dll")] static extern IntPtr DefWindowProc(IntPtr hwnd,uint msg,IntPtr w,IntPtr l);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr hwnd,uint msg,IntPtr w,IntPtr l);
    [DllImport("user32.dll")] static extern bool DestroyWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern void PostQuitMessage(int code);
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr hwnd,uint msg,IntPtr w,IntPtr l);
    [DllImport("user32.dll", EntryPoint="SetWindowLongPtrW")] static extern IntPtr SetWindowLongPtr(IntPtr hwnd,int index,IntPtr value);
    [DllImport("user32.dll")] static extern IntPtr CallWindowProc(IntPtr original,IntPtr hwnd,uint msg,IntPtr w,IntPtr l);
    [DllImport("user32.dll")] static extern short GetKeyState(int key);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd,StringBuilder text,int length);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern bool SetWindowText(IntPtr hwnd,string text);
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr hwnd,out Rect rect);
    [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr hwnd,ref Point point);
    [DllImport("user32.dll")] static extern bool InvalidateRect(IntPtr hwnd,IntPtr rect,bool erase);
    [DllImport("user32.dll")] static extern bool UpdateWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr BeginPaint(IntPtr hwnd,out Paint paint);
    [DllImport("user32.dll")] static extern bool EndPaint(IntPtr hwnd,ref Paint paint);
    [DllImport("user32.dll")] static extern IntPtr GetDC(IntPtr hwnd);
    [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr hwnd,IntPtr dc);
    [DllImport("user32.dll")] static extern int FillRect(IntPtr dc,ref Rect rect,IntPtr brush);
    [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("gdi32.dll")] static extern IntPtr CreateSolidBrush(uint color);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr obj);
    [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleBitmap(IntPtr dc,int w,int h);
    [DllImport("gdi32.dll")] static extern IntPtr SelectObject(IntPtr dc,IntPtr obj);
    [DllImport("gdi32.dll")] static extern bool DeleteDC(IntPtr dc);
    [DllImport("gdi32.dll")] static extern bool BitBlt(IntPtr dc,int x,int y,int w,int h,IntPtr src,int sx,int sy,uint rop);
    [DllImport("gdi32.dll")] static extern int GetDIBits(IntPtr dc,IntPtr bitmap,uint start,uint lines,byte[] bytes,ref BitmapInfo info,uint usage);
}
