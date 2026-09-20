using System.Runtime.InteropServices;

namespace NteHost.Input;

/// <summary>
/// Minimal Win32 P/Invoke surface for the V2-2B input safety layer.
///
/// Deliberately narrow. This module owns exactly three OS capabilities:
///   1. low-level keyboard/mouse hook installation + teardown,
///   2. cursor position read/write (needed for the save/restore guard),
///   3. a single SendInput entry point (reached only through the ticket-gated executor).
///
/// It intentionally contains NO window discovery, NO window lifecycle monitoring,
/// NO foreground event subscription, NO OCR, and NO game integration. The only
/// foreground read is <see cref="GetForegroundWindow"/>, used to take a
/// point-in-time focus snapshot at the instant of a guard decision, which is the
/// authority explicitly granted to V2-2B. Window discovery/lifecycle belongs to
/// V2-2A and is not implemented here.
/// </summary>
internal static class NativeInputMethods
{
    internal const int WH_KEYBOARD_LL = 13;
    internal const int WH_MOUSE_LL = 14;

    internal const int WM_KEYDOWN = 0x0100;
    internal const int WM_SYSKEYDOWN = 0x0104;
    internal const int WM_MOUSEMOVE = 0x0200;
    internal const int WM_LBUTTONDOWN = 0x0201;
    internal const int WM_RBUTTONDOWN = 0x0204;
    internal const int WM_MBUTTONDOWN = 0x0207;
    internal const int WM_XBUTTONDOWN = 0x020B;
    internal const int WM_MOUSEWHEEL = 0x020A;
    internal const int WM_MOUSEHWHEEL = 0x020E;
    internal const uint WM_QUIT = 0x0012;

    // Low-level hook structure flags.
    internal const uint LLKHF_INJECTED = 0x00000010;
    internal const uint LLKHF_LOWER_IL_INJECTED = 0x00000002;
    internal const uint LLMHF_INJECTED = 0x00000001;
    internal const uint LLMHF_LOWER_IL_INJECTED = 0x00000002;

    // SendInput constants.
    internal const uint INPUT_MOUSE = 0;
    internal const uint MOUSEEVENTF_MOVE = 0x0001;
    internal const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
    internal const uint MOUSEEVENTF_WHEEL = 0x0800;
    internal const uint MOUSEEVENTF_HWHEEL = 0x1000;
    internal const uint WHEEL_DELTA = 120;

    internal delegate IntPtr HookProc(int nCode, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    internal struct POINT
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct KBDLLHOOKSTRUCT
    {
        public uint vkCode;
        public uint scanCode;
        public uint flags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct MSLLHOOKSTRUCT
    {
        public POINT pt;
        public uint mouseData;
        public uint flags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct MOUSEINPUT
    {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint dwFlags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct KEYBDINPUT
    {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct HARDWAREINPUT
    {
        public uint uMsg;
        public ushort wParamL;
        public ushort wParamH;
    }

    [StructLayout(LayoutKind.Explicit)]
    internal struct INPUTUNION
    {
        [FieldOffset(0)] public MOUSEINPUT mi;
        [FieldOffset(0)] public KEYBDINPUT ki;
        [FieldOffset(0)] public HARDWAREINPUT hi;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct INPUT
    {
        public uint type;
        public INPUTUNION u;
    }

    internal readonly record struct NativeMarkerBoundaryDiagnostics(
        int ProcessPointerBits,
        int UIntPtrBits,
        int InputSizeBytes,
        int MouseInputSizeBytes,
        int MouseInputExtraInfoOffsetBytes,
        int MsllHookStructSizeBytes,
        int MsllHookStructExtraInfoOffsetBytes,
        ulong ManagedMarker,
        ulong NativeExtraInfo,
        ulong MarshaledExtraInfo);

    /// <summary>
    /// Describes the managed-to-native marker boundary without calling any OS
    /// input API.  The marshaled value is read back from an unmanaged INPUT
    /// buffer, so this catches construction/layout truncation deterministically.
    /// </summary>
    internal static NativeMarkerBoundaryDiagnostics InspectMarker(ulong marker)
    {
        UIntPtr nativeMarker = InputMarker.ToNative(marker);
        var input = new INPUT
        {
            type = INPUT_MOUSE,
            u = new INPUTUNION
            {
                mi = new MOUSEINPUT
                {
                    dwExtraInfo = nativeMarker,
                },
            },
        };

        int inputSize = Marshal.SizeOf<INPUT>();
        ulong marshaledMarker;
        IntPtr storage = Marshal.AllocHGlobal(inputSize);
        try
        {
            Marshal.StructureToPtr(input, storage, fDeleteOld: false);
            INPUT roundTrip = Marshal.PtrToStructure<INPUT>(storage);
            marshaledMarker = InputMarker.FromNative(roundTrip.u.mi.dwExtraInfo);
        }
        finally
        {
            Marshal.DestroyStructure<INPUT>(storage);
            Marshal.FreeHGlobal(storage);
        }

        return new NativeMarkerBoundaryDiagnostics(
            IntPtr.Size * 8,
            UIntPtr.Size * 8,
            inputSize,
            Marshal.SizeOf<MOUSEINPUT>(),
            (int)Marshal.OffsetOf<MOUSEINPUT>(nameof(MOUSEINPUT.dwExtraInfo)),
            Marshal.SizeOf<MSLLHOOKSTRUCT>(),
            (int)Marshal.OffsetOf<MSLLHOOKSTRUCT>(nameof(MSLLHOOKSTRUCT.dwExtraInfo)),
            marker,
            InputMarker.FromNative(nativeMarker),
            marshaledMarker);
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct MSG
    {
        public IntPtr hwnd;
        public uint message;
        public UIntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public POINT pt;
    }

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    internal static extern IntPtr SetWindowsHookExW(int idHook, HookProc lpfn, IntPtr hMod, uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool UnhookWindowsHookEx(IntPtr hhk);

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern int GetMessageW(out MSG lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool PeekMessageW(out MSG lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax, uint wRemoveMsg);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool TranslateMessage(ref MSG lpMsg);

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern IntPtr DispatchMessageW(ref MSG lpMsg);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool PostThreadMessageW(uint idThread, uint msg, UIntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll")]
    internal static extern uint GetCurrentThreadId();

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool GetCursorPos(out POINT lpPoint);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern int GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
}
