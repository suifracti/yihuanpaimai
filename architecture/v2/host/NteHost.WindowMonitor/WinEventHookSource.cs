using System.Runtime.InteropServices;
using NteHost.WindowMonitor.Win32;

namespace NteHost.WindowMonitor;

/// <summary>Receives raw WinEvents. Implementations MUST NOT block.</summary>
public interface IRawWinEventSink
{
    void OnRawWinEvent(uint eventType, long hwnd, int idObject);
}

/// <summary>
/// Owns the SetWinEventHook subscription and the message pump that delivers
/// OUTOFCONTEXT callbacks.
///
/// Two invariants matter here:
///   1. The callback runs on the pump thread and does nothing but hand the raw
///      fields to a non-blocking sink. Any real work on this thread would stall
///      event delivery for the whole desktop, so it is forbidden by construction.
///   2. The delegate instance is held in a field for the whole subscription
///      lifetime. If it were only reachable from the SetWinEventHook call, the GC
///      could collect the thunk and Windows would call into freed memory.
/// </summary>
public sealed class WinEventHookSource : IDisposable
{
    private readonly IRawWinEventSink _sink;
    private readonly bool _skipOwnProcess;

    private NativeWindowApi.WinEventDelegate? _callback;
    private IntPtr _hook;
    private Thread? _pumpThread;
    private volatile bool _stopRequested;
    private volatile bool _started;

    public WinEventHookSource(IRawWinEventSink sink, bool skipOwnProcess = false)
    {
        _sink = sink;
        _skipOwnProcess = skipOwnProcess;
    }

    public bool IsHookInstalled => _hook != IntPtr.Zero;

    public bool IsPumpRunning => _pumpThread is { IsAlive: true };

    /// <summary>Number of raw callbacks received from Windows.</summary>
    public long RawCallbackCount => Interlocked.Read(ref _rawCallbackCount);

    private long _rawCallbackCount;

    public void Start()
    {
        if (_started)
        {
            throw new InvalidOperationException("the WinEvent hook source is already started");
        }
        _started = true;
        _stopRequested = false;

        var ready = new ManualResetEventSlim(false);
        Exception? startError = null;

        _pumpThread = new Thread(() =>
        {
            try
            {
                // The delegate must stay rooted for the whole subscription.
                _callback = OnWinEvent;
                var flags = WinEvent.WINEVENT_OUTOFCONTEXT;
                if (_skipOwnProcess)
                {
                    flags |= WinEvent.WINEVENT_SKIPOWNPROCESS;
                }

                _hook = NativeWindowApi.SetWinEventHook(
                    WinEvent.Min, WinEvent.Max, IntPtr.Zero, _callback, 0, 0, flags);

                if (_hook == IntPtr.Zero)
                {
                    startError = new InvalidOperationException(
                        $"SetWinEventHook failed with Win32 error {Marshal.GetLastWin32Error()}");
                    return;
                }

                PumpMessages();
            }
            catch (Exception ex)
            {
                startError = ex;
            }
            finally
            {
                if (_hook != IntPtr.Zero)
                {
                    NativeWindowApi.UnhookWinEvent(_hook);
                    _hook = IntPtr.Zero;
                }
                ready.Set();
            }
        })
        {
            IsBackground = true,
            Name = "nte-winevent-pump",
        };
        _pumpThread.Start();

        // Wait until the hook is installed (or failed) so Start() is synchronous.
        var deadline = Environment.TickCount64 + 5000;
        while (Environment.TickCount64 < deadline)
        {
            if (startError is not null)
            {
                throw startError;
            }
            if (_hook != IntPtr.Zero)
            {
                return;
            }
            Thread.Sleep(1);
        }

        if (startError is not null)
        {
            throw startError;
        }
        throw new TimeoutException("SetWinEventHook did not complete within 5000ms");
    }

    private void PumpMessages()
    {
        var message = default(NativeMessage);
        while (!_stopRequested)
        {
            var hadMessage = false;
            while (PeekMessageW(ref message, IntPtr.Zero, 0, 0, 1))
            {
                TranslateMessage(ref message);
                DispatchMessageW(ref message);
                hadMessage = true;
            }

            if (!hadMessage)
            {
                // Short sleep instead of a blocking GetMessage so shutdown is prompt.
                Thread.Sleep(1);
            }
        }
    }

    private void OnWinEvent(IntPtr hook, uint eventType, IntPtr hwnd, int idObject, int idChild,
        uint eventThread, uint eventTime)
    {
        Interlocked.Increment(ref _rawCallbackCount);

        // Window-level events only; child-object noise is dropped before it can
        // reach the queue.
        if (idObject != WinEvent.OBJID_WINDOW)
        {
            return;
        }

        // MUST NOT block. The sink is contractually non-blocking.
        _sink.OnRawWinEvent(eventType, hwnd.ToInt64(), idObject);
    }

    public void Dispose()
    {
        _stopRequested = true;
        _pumpThread?.Join(3000);

        if (_hook != IntPtr.Zero)
        {
            NativeWindowApi.UnhookWinEvent(_hook);
            _hook = IntPtr.Zero;
        }

        // Dropping the last reference to the delegate after the unhook guarantees
        // Windows can no longer call into it.
        _callback = null;
        _pumpThread = null;
    }

    // ---- message pump P/Invoke ------------------------------------------------
    [StructLayout(LayoutKind.Sequential)]
    private struct NativeMessage
    {
        public IntPtr hwnd;
        public uint message;
        public IntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public int ptX;
        public int ptY;
        public uint lPrivate;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool PeekMessageW(ref NativeMessage lpMsg, IntPtr hWnd, uint wMsgFilterMin,
        uint wMsgFilterMax, uint wRemoveMsg);

    [DllImport("user32.dll")]
    private static extern bool TranslateMessage(ref NativeMessage lpMsg);

    [DllImport("user32.dll")]
    private static extern IntPtr DispatchMessageW(ref NativeMessage lpMsg);
}
