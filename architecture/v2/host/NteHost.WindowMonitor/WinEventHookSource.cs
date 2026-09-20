using System.Runtime.InteropServices;
using NteHost.WindowMonitor.Win32;

namespace NteHost.WindowMonitor;

/// <summary>
/// Receives raw WinEvents.
///
/// Implementations must return promptly: this runs on the thread that delivers
/// OUTOFCONTEXT events, and a slow implementation delays event delivery for the
/// whole desktop. "Promptly" means no Win32 call, no process handling, and no lock
/// that a slower path in the same component can hold.
/// </summary>
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
///      fields to the sink. Any real work on this thread would stall event
///      delivery for the whole desktop.
///   2. The delegate instance is held in a field for the whole subscription
///      lifetime. If it were only reachable from the SetWinEventHook call, the GC
///      could collect the thunk and Windows would call into freed memory.
///
/// Note on the sink contract: "must not block" is enforced by the sink's design
/// rather than by this class. <see cref="WindowMonitor.OnRawWinEvent"/> takes no
/// lock that the state machine ever holds, so the callback cannot be serialised
/// behind Win32 or process-identity work performed by the worker. See
/// <see cref="RawEventQueue"/> for the mechanism.
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

    // Set once Dispose has begun. The callback checks this AFTER incrementing the
    // raw counter: an OUTOFCONTEXT callback that was already in flight when the
    // hook was removed must not be counted as "a callback that still ran after
    // Dispose", because the unsubscribe had no chance to stop it. Counting it
    // would turn an unavoidable OS-level race into a false instability signal.
    private volatile bool _disposed;

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

        // Unsubscribe race guard. UnhookWinEvent only stops *future* callbacks; a
        // callback already delivered cannot be revoked. Once Dispose has started we
        // no longer act on the event, so teardown cannot be extended (or a captured
        // resource touched) by a callback that raced the unhook.
        if (_disposed)
        {
            return;
        }

        // Window-level events only; child-object noise is dropped before it can
        // reach the queue.
        if (idObject != WinEvent.OBJID_WINDOW)
        {
            return;
        }

        // Bounded, lock-free with respect to the state machine: the sink appends to
        // its own raw queue and returns.
        _sink.OnRawWinEvent(eventType, hwnd.ToInt64(), idObject);
    }

    public void Dispose()
    {
        _disposed = true;
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
