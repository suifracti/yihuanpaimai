using System.Diagnostics;
using System.Runtime.InteropServices;

namespace NteHost.Input.Verifier;

internal enum ForegroundWindowReadStatus
{
    NotRead = 0,
    ValidWindow = 1,
    Null = 2,
    Exception = 3,
}

internal readonly record struct ForegroundWindowRead(
    ForegroundWindowReadStatus Status,
    IntPtr Window,
    string Error)
{
    public bool ReturnedNormally => Status != ForegroundWindowReadStatus.Exception;
}

internal readonly record struct ForegroundRestoreResult(
    bool Ok,
    bool Skipped,
    bool UserTakeover,
    string Reason,
    IntPtr OriginalWindow,
    bool OriginalWindowValid,
    IntPtr ActualBefore,
    bool ActualBeforeRead,
    bool SetForegroundCalled,
    bool SetForegroundReturned,
    IntPtr ActualAfter,
    bool ActualAfterRead,
    ForegroundWindowReadStatus ActualBeforeStatus,
    ForegroundWindowReadStatus ActualAfterStatus,
    int NullForegroundReadCount,
    int PollCount,
    int TakeoverReadCount,
    long ElapsedMs);

/// <summary>
/// Shared foreground-restore decision path for the Win32 harness and fake
/// verifier.  It records the request and confirmation separately, waits only
/// inside a bounded window, and treats takeover/read failures as terminal
/// decisions rather than as a successful restore.
/// </summary>
internal static class ForegroundRestoreVerifier
{
    public static ForegroundRestoreResult Restore(
        IntPtr originalWindow,
        bool originalWindowCaptured,
        Func<IntPtr, bool> isWindow,
        Func<IntPtr> getForeground,
        Func<IntPtr, bool> setForeground,
        Func<TakeoverReadResult> readTakeover,
        TimeSpan confirmationTimeout,
        TimeSpan pollInterval,
        Func<long>? nowMilliseconds = null,
        Action<TimeSpan>? wait = null)
    {
        ArgumentNullException.ThrowIfNull(isWindow);
        ArgumentNullException.ThrowIfNull(getForeground);
        ArgumentNullException.ThrowIfNull(setForeground);
        ArgumentNullException.ThrowIfNull(readTakeover);

        Stopwatch stopwatch = Stopwatch.StartNew();
        nowMilliseconds ??= () => stopwatch.ElapsedMilliseconds;
        wait ??= Thread.Sleep;

        long started = nowMilliseconds();
        int pollCount = 0;
        int takeoverReadCount = 0;
        int nullForegroundReadCount = 0;
        ForegroundWindowRead beforeRead = Read(getForeground);
        if (beforeRead.Status == ForegroundWindowReadStatus.Null)
        {
            nullForegroundReadCount++;
        }

        IntPtr actualBefore = beforeRead.Window;
        bool actualBeforeRead = beforeRead.ReturnedNormally;
        if (beforeRead.Status == ForegroundWindowReadStatus.Exception)
        {
            return Result(
                ok: false,
                skipped: false,
                userTakeover: false,
                reason: "FOREGROUND_ACTUAL_BEFORE_READ_EXCEPTION:" + beforeRead.Error,
                originalWindow,
                originalWindowValid: false,
                actualBefore,
                actualBeforeRead,
                setForegroundCalled: false,
                setForegroundReturned: false,
                actualAfter: IntPtr.Zero,
                actualAfterRead: false,
                actualBeforeStatus: beforeRead.Status,
                actualAfterStatus: ForegroundWindowReadStatus.NotRead,
                nullForegroundReadCount,
                pollCount,
                takeoverReadCount,
                Elapsed(nowMilliseconds, started));
        }

        if (!originalWindowCaptured || originalWindow == IntPtr.Zero)
        {
            return Result(
                ok: false,
                skipped: false,
                userTakeover: false,
                reason: "ORIGINAL_FOREGROUND_UNAVAILABLE",
                originalWindow,
                originalWindowValid: false,
                actualBefore,
                actualBeforeRead,
                setForegroundCalled: false,
                setForegroundReturned: false,
                actualAfter: IntPtr.Zero,
                actualAfterRead: false,
                actualBeforeStatus: beforeRead.Status,
                actualAfterStatus: ForegroundWindowReadStatus.NotRead,
                nullForegroundReadCount,
                pollCount,
                takeoverReadCount,
                Elapsed(nowMilliseconds, started));
        }

        bool originalWindowValid;
        try
        {
            originalWindowValid = isWindow(originalWindow);
        }
        catch
        {
            originalWindowValid = false;
        }

        if (!originalWindowValid)
        {
            return Result(
                ok: false,
                skipped: false,
                userTakeover: false,
                reason: "ORIGINAL_FOREGROUND_INVALID",
                originalWindow,
                originalWindowValid,
                actualBefore,
                actualBeforeRead,
                setForegroundCalled: false,
                setForegroundReturned: false,
                actualAfter: IntPtr.Zero,
                actualAfterRead: false,
                actualBeforeStatus: beforeRead.Status,
                actualAfterStatus: ForegroundWindowReadStatus.NotRead,
                nullForegroundReadCount,
                pollCount,
                takeoverReadCount,
                Elapsed(nowMilliseconds, started));
        }

        bool requested;
        try
        {
            requested = setForeground(originalWindow);
        }
        catch
        {
            ForegroundWindowRead afterExceptionRead = Read(getForeground);
            if (afterExceptionRead.Status == ForegroundWindowReadStatus.Null)
            {
                nullForegroundReadCount++;
            }
            return Result(
                ok: false,
                skipped: false,
                userTakeover: false,
                reason: "FOREGROUND_REQUEST_EXCEPTION",
                originalWindow,
                originalWindowValid,
                actualBefore,
                actualBeforeRead,
                setForegroundCalled: true,
                setForegroundReturned: false,
                afterExceptionRead.Window,
                afterExceptionRead.ReturnedNormally,
                actualBeforeStatus: beforeRead.Status,
                actualAfterStatus: afterExceptionRead.Status,
                nullForegroundReadCount,
                pollCount,
                takeoverReadCount,
                Elapsed(nowMilliseconds, started));
        }

        if (!requested)
        {
            ForegroundWindowRead afterRejectedRead = Read(getForeground);
            if (afterRejectedRead.Status == ForegroundWindowReadStatus.Null)
            {
                nullForegroundReadCount++;
            }
            return Result(
                ok: false,
                skipped: false,
                userTakeover: false,
                reason: "FOREGROUND_REQUEST_REJECTED",
                originalWindow,
                originalWindowValid,
                actualBefore,
                actualBeforeRead,
                setForegroundCalled: true,
                setForegroundReturned: false,
                afterRejectedRead.Window,
                afterRejectedRead.ReturnedNormally,
                actualBeforeStatus: beforeRead.Status,
                actualAfterStatus: afterRejectedRead.Status,
                nullForegroundReadCount,
                pollCount,
                takeoverReadCount,
                Elapsed(nowMilliseconds, started));
        }

        long timeoutMs = Math.Max(1, (long)Math.Ceiling(Math.Max(0, confirmationTimeout.TotalMilliseconds)));
        TimeSpan poll = pollInterval <= TimeSpan.Zero
            ? TimeSpan.FromMilliseconds(1)
            : pollInterval;
        while (true)
        {
            TakeoverReadResult takeover;
            try
            {
                takeover = readTakeover();
            }
            catch (Exception ex)
            {
                ForegroundWindowRead afterTakeoverExceptionRead = Read(getForeground);
                if (afterTakeoverExceptionRead.Status == ForegroundWindowReadStatus.Null)
                {
                    nullForegroundReadCount++;
                }
                return Result(
                    ok: false,
                    skipped: false,
                    userTakeover: false,
                    reason: "TAKEOVER_STATE_READ_EXCEPTION:" + ex.GetType().Name,
                    originalWindow,
                    originalWindowValid,
                    actualBefore,
                    actualBeforeRead,
                    setForegroundCalled: true,
                    setForegroundReturned: true,
                    afterTakeoverExceptionRead.Window,
                    afterTakeoverExceptionRead.ReturnedNormally,
                    actualBeforeStatus: beforeRead.Status,
                    actualAfterStatus: afterTakeoverExceptionRead.Status,
                    nullForegroundReadCount,
                    pollCount,
                    takeoverReadCount,
                    Elapsed(nowMilliseconds, started));
            }

            takeoverReadCount++;
            if (!takeover.Ok)
            {
                ForegroundWindowRead afterTakeoverReadFailure = Read(getForeground);
                if (afterTakeoverReadFailure.Status == ForegroundWindowReadStatus.Null)
                {
                    nullForegroundReadCount++;
                }
                return Result(
                    ok: false,
                    skipped: false,
                    userTakeover: false,
                    reason: "TAKEOVER_STATE_READ_FAILED_DURING_FOREGROUND_RESTORE:" + takeover.Reason,
                    originalWindow,
                    originalWindowValid,
                    actualBefore,
                    actualBeforeRead,
                    setForegroundCalled: true,
                    setForegroundReturned: true,
                    afterTakeoverReadFailure.Window,
                    afterTakeoverReadFailure.ReturnedNormally,
                    actualBeforeStatus: beforeRead.Status,
                    actualAfterStatus: afterTakeoverReadFailure.Status,
                    nullForegroundReadCount,
                    pollCount,
                    takeoverReadCount,
                    Elapsed(nowMilliseconds, started));
            }

            if (takeover.Seen)
            {
                ForegroundWindowRead afterTakeover = Read(getForeground);
                if (afterTakeover.Status == ForegroundWindowReadStatus.Null)
                {
                    nullForegroundReadCount++;
                }
                return Result(
                    ok: false,
                    skipped: true,
                    userTakeover: true,
                    reason: "FOREGROUND_RESTORE_USER_TAKEOVER_DURING_CONFIRMATION",
                    originalWindow,
                    originalWindowValid,
                    actualBefore,
                    actualBeforeRead,
                    setForegroundCalled: true,
                    setForegroundReturned: true,
                    afterTakeover.Window,
                    afterTakeover.ReturnedNormally,
                    actualBeforeStatus: beforeRead.Status,
                    actualAfterStatus: afterTakeover.Status,
                    nullForegroundReadCount,
                    pollCount,
                    takeoverReadCount,
                    Elapsed(nowMilliseconds, started));
            }

            bool stillValid;
            try
            {
                stillValid = isWindow(originalWindow);
            }
            catch
            {
                stillValid = false;
            }

            if (!stillValid)
            {
                ForegroundWindowRead afterInvalidRead = Read(getForeground);
                if (afterInvalidRead.Status == ForegroundWindowReadStatus.Null)
                {
                    nullForegroundReadCount++;
                }
                return Result(
                    ok: false,
                    skipped: false,
                    userTakeover: false,
                    reason: "ORIGINAL_FOREGROUND_INVALID_DURING_CONFIRMATION",
                    originalWindow,
                    originalWindowValid,
                    actualBefore,
                    actualBeforeRead,
                    setForegroundCalled: true,
                    setForegroundReturned: true,
                    afterInvalidRead.Window,
                    afterInvalidRead.ReturnedNormally,
                    actualBeforeStatus: beforeRead.Status,
                    actualAfterStatus: afterInvalidRead.Status,
                    nullForegroundReadCount,
                    pollCount,
                    takeoverReadCount,
                    Elapsed(nowMilliseconds, started));
            }

            ForegroundWindowRead confirmationRead = Read(getForeground);
            if (confirmationRead.Status == ForegroundWindowReadStatus.Null)
            {
                nullForegroundReadCount++;
            }

            if (confirmationRead.Status == ForegroundWindowReadStatus.Exception)
            {
                return Result(
                    ok: false,
                    skipped: false,
                    userTakeover: false,
                    reason: confirmationRead.Error.Length == 0
                        ? "FOREGROUND_ACTUAL_CONFIRMATION_READ_FAILED"
                        : "FOREGROUND_ACTUAL_CONFIRMATION_READ_EXCEPTION:" + confirmationRead.Error,
                    originalWindow,
                    originalWindowValid,
                    actualBefore,
                    actualBeforeRead,
                    setForegroundCalled: true,
                    setForegroundReturned: true,
                    confirmationRead.Window,
                    confirmationRead.ReturnedNormally,
                    actualBeforeStatus: beforeRead.Status,
                    actualAfterStatus: confirmationRead.Status,
                    nullForegroundReadCount,
                    pollCount,
                    takeoverReadCount,
                    Elapsed(nowMilliseconds, started));
            }

            if (confirmationRead.Window == originalWindow)
            {
                return Result(
                    ok: true,
                    skipped: false,
                    userTakeover: false,
                    reason: "FOREGROUND_RESTORE_OK",
                    originalWindow,
                    originalWindowValid,
                    actualBefore,
                    actualBeforeRead,
                    setForegroundCalled: true,
                    setForegroundReturned: true,
                    confirmationRead.Window,
                    confirmationRead.ReturnedNormally,
                    actualBeforeStatus: beforeRead.Status,
                    actualAfterStatus: confirmationRead.Status,
                    nullForegroundReadCount,
                    pollCount,
                    takeoverReadCount,
                    Elapsed(nowMilliseconds, started));
            }

            long elapsed = Elapsed(nowMilliseconds, started);
            if (elapsed >= timeoutMs)
            {
                return Result(
                    ok: false,
                    skipped: false,
                    userTakeover: false,
                    reason: "FOREGROUND_CONFIRMATION_TIMEOUT",
                    originalWindow,
                    originalWindowValid,
                    actualBefore,
                    actualBeforeRead,
                    setForegroundCalled: true,
                    setForegroundReturned: true,
                    confirmationRead.Window,
                    confirmationRead.ReturnedNormally,
                    actualBeforeStatus: beforeRead.Status,
                    actualAfterStatus: confirmationRead.Status,
                    nullForegroundReadCount,
                    pollCount,
                    takeoverReadCount,
                    elapsed);
            }

            pollCount++;
            long remainingMs = timeoutMs - elapsed;
            TimeSpan delay = poll <= TimeSpan.FromMilliseconds(remainingMs)
                ? poll
                : TimeSpan.FromMilliseconds(remainingMs);
            wait(delay);
        }
    }

    private static ForegroundWindowRead Read(Func<IntPtr> getForeground)
    {
        try
        {
            IntPtr actual = getForeground();
            return actual == IntPtr.Zero
                ? new ForegroundWindowRead(ForegroundWindowReadStatus.Null, IntPtr.Zero, string.Empty)
                : new ForegroundWindowRead(ForegroundWindowReadStatus.ValidWindow, actual, string.Empty);
        }
        catch (Exception ex)
        {
            return new ForegroundWindowRead(
                ForegroundWindowReadStatus.Exception,
                IntPtr.Zero,
                ex.GetType().Name);
        }
    }

    private static long Elapsed(Func<long> nowMilliseconds, long started) =>
        Math.Max(0, nowMilliseconds() - started);

    private static ForegroundRestoreResult Result(
        bool ok,
        bool skipped,
        bool userTakeover,
        string reason,
        IntPtr originalWindow,
        bool originalWindowValid,
        IntPtr actualBefore,
        bool actualBeforeRead,
        bool setForegroundCalled,
        bool setForegroundReturned,
        IntPtr actualAfter,
        bool actualAfterRead,
        ForegroundWindowReadStatus actualBeforeStatus,
        ForegroundWindowReadStatus actualAfterStatus,
        int nullForegroundReadCount,
        int pollCount,
        int takeoverReadCount,
        long elapsedMs) => new(
            ok,
            skipped,
            userTakeover,
            reason,
            originalWindow,
            originalWindowValid,
            actualBefore,
            actualBeforeRead,
            setForegroundCalled,
            setForegroundReturned,
            actualAfter,
            actualAfterRead,
            actualBeforeStatus,
            actualAfterStatus,
            nullForegroundReadCount,
            pollCount,
            takeoverReadCount,
            elapsedMs);
}

/// <summary>
/// A short-lived, self-owned dummy window used only by the explicitly gated live
/// verifier.  Original desktop state is captured before this type creates or
/// shows a window.  Cursor and foreground restoration are explicit operations;
/// Dispose never silently changes user state.
///
/// The guard owns cursor restoration after an operation has been armed.  This
/// harness records and verifies that result, while it owns the previous
/// foreground restoration and the window/thread lifecycle.  That split avoids a
/// second SetCursorPos call and prevents a harness finally block from overriding
/// the guard's user-takeover decision.
/// </summary>
internal sealed class ControlledWindowHarness : IDisposable
{
    private const string ClassName = "NteInputGuardControlledWindow";

    private readonly ManualResetEventSlim _ready = new(false);
    private readonly ManualResetEventSlim _closed = new(false);
    private readonly ControlledWindowNativeMethods.WndProc _wndProc;
    private Thread? _thread;
    private IntPtr _hwnd = IntPtr.Zero;
    private string _lastError = string.Empty;
    private int _syncDisposed;
    private int _shutdownRequested;
    private readonly object _promptGate = new();
    private string _promptText = string.Empty;
    private bool _promptDisplayed;

    private ControlledWindowHarness()
    {
        _wndProc = WindowProc;
    }

    public IntPtr Hwnd => _hwnd;

    public bool Created => _hwnd != IntPtr.Zero;

    public bool OriginalStateCaptured { get; private set; }

    public bool OriginalForegroundCaptured { get; private set; }

    public bool OriginalCursorCaptured { get; private set; }

    public bool ForegroundAcquired { get; private set; }

    public bool ForegroundRestoreAttempted { get; private set; }

    public bool ForegroundRestoreSkipped { get; private set; }

    public bool ForegroundRestored { get; private set; }

    public bool ForegroundRestoreOriginalWindowValid { get; private set; }

    public IntPtr ForegroundBeforeRestore { get; private set; }

    public bool ForegroundBeforeRestoreReadSucceeded { get; private set; }

    public bool ForegroundSetCalled { get; private set; }

    public bool ForegroundSetReturned { get; private set; }

    public IntPtr ForegroundAfterRestore { get; private set; }

    public bool ForegroundAfterRestoreReadSucceeded { get; private set; }

    public ForegroundWindowReadStatus ForegroundBeforeRestoreStatus { get; private set; }

    public ForegroundWindowReadStatus ForegroundAfterRestoreStatus { get; private set; }

    public int ForegroundNullReadCount { get; private set; }

    public int ForegroundRestorePollCount { get; private set; }

    public int ForegroundRestoreTakeoverReadCount { get; private set; }

    public long ForegroundRestoreElapsedMs { get; private set; }

    public bool ForegroundRestoreTakeoverDetected { get; private set; }

    public bool CursorRestoreAttempted { get; private set; }

    public bool CursorRestoreSkipped { get; private set; }

    public bool CursorRestored { get; private set; }

    public bool CursorAfterReadSucceeded { get; private set; }

    public bool WindowThreadExited { get; private set; }

    public bool SynchronizationDisposed => Volatile.Read(ref _syncDisposed) != 0;

    public bool ThreadAlive => _thread is { IsAlive: true };

    public IntPtr PreviousForeground { get; private set; }

    public long WheelMessages => Interlocked.Read(ref _wheelCounter);

    public long HorizontalWheelMessages => Interlocked.Read(ref _horizontalWheelCounter);

    public long MoveMessages => Interlocked.Read(ref _moveCounter);

    public long ButtonMessages => Interlocked.Read(ref _buttonCounter);

    public long HarnessCursorSetCalls => Interlocked.Read(ref _cursorSetCounter);

    public (int X, int Y) CursorBefore { get; private set; }

    public (int X, int Y) CursorAfter { get; private set; }

    public int OriginX { get; private set; } = 160;

    public int OriginY { get; private set; } = 160;

    public int Width { get; } = 320;

    public int Height { get; } = 200;

    public (int X, int Y) Center => (OriginX + (Width / 2), OriginY + (Height / 2));

    public string CursorRestoreReason { get; private set; } = string.Empty;

    public string ForegroundRestoreReason { get; private set; } = string.Empty;

    public string LastError => _lastError;

    public Action<string>? WindowMessageObserver { get; set; }

    public bool PromptDisplayed
    {
        get { lock (_promptGate) { return _promptDisplayed; } }
    }

    public string PromptText
    {
        get { lock (_promptGate) { return _promptText; } }
    }

    public static ControlledWindowHarness Create(int foregroundTimeoutMs = 1500)
    {
        var harness = new ControlledWindowHarness();
        if (!harness.CaptureOriginalState())
        {
            return harness;
        }

        harness.Start();
        if (harness.Created)
        {
            harness.AcquireForeground(foregroundTimeoutMs);
        }

        return harness;
    }

    private bool CaptureOriginalState()
    {
        try
        {
            PreviousForeground = ControlledWindowNativeMethods.GetForegroundWindow();
            if (PreviousForeground == IntPtr.Zero)
            {
                _lastError = "ORIGINAL_FOREGROUND_NULL";
                return false;
            }

            OriginalForegroundCaptured = true;

            if (!ControlledWindowNativeMethods.GetCursorPos(out ControlledWindowNativeMethods.POINT point))
            {
                _lastError = "ORIGINAL_CURSOR_READ_FAILED";
                return false;
            }

            CursorBefore = (point.X, point.Y);
            OriginalCursorCaptured = true;
            OriginalStateCaptured = true;
            return true;
        }
        catch (Exception ex)
        {
            _lastError = "ORIGINAL_STATE_READ_EXCEPTION:" + ex.GetType().Name;
            return false;
        }
    }

    private void Start()
    {
        try
        {
            _thread = new Thread(ThreadMain)
            {
                IsBackground = true,
                Name = "nte-controlled-window",
            };
            _thread.SetApartmentState(ApartmentState.STA);
            _thread.Start();
        }
        catch (Exception ex)
        {
            _lastError = "WINDOW_THREAD_START_EXCEPTION:" + ex.GetType().Name;
            _ready.Set();
            return;
        }

        if (!_ready.Wait(TimeSpan.FromSeconds(5)))
        {
            _lastError = "WINDOW_CREATE_TIMEOUT";
        }
    }

    private void ThreadMain()
    {
        IntPtr instance = IntPtr.Zero;
        ushort atom = 0;
        try
        {
            instance = ControlledWindowNativeMethods.GetModuleHandleW(null);

            var wc = new ControlledWindowNativeMethods.WNDCLASSEXW
            {
                cbSize = (uint)Marshal.SizeOf<ControlledWindowNativeMethods.WNDCLASSEXW>(),
                style = 0,
                lpfnWndProc = Marshal.GetFunctionPointerForDelegate(_wndProc),
                hInstance = instance,
                hbrBackground = ControlledWindowNativeMethods.GetSysColorBrush(
                    ControlledWindowNativeMethods.COLOR_WINDOW),
                lpszClassName = ClassName,
            };

            atom = ControlledWindowNativeMethods.RegisterClassExW(ref wc);
            if (atom == 0)
            {
                _lastError = "REGISTER_CLASS_FAILED";
                return;
            }

            _hwnd = ControlledWindowNativeMethods.CreateWindowExW(
                ControlledWindowNativeMethods.WS_EX_TOOLWINDOW,
                ClassName,
                "NTE Input Guard Controlled Window",
                ControlledWindowNativeMethods.WS_POPUP | ControlledWindowNativeMethods.WS_VISIBLE,
                OriginX,
                OriginY,
                Width,
                Height,
                IntPtr.Zero,
                IntPtr.Zero,
                instance,
                IntPtr.Zero);

            if (_hwnd == IntPtr.Zero)
            {
                _lastError = "CREATE_WINDOW_FAILED";
                return;
            }

            ControlledWindowNativeMethods.ShowWindow(_hwnd, ControlledWindowNativeMethods.SW_SHOW);
            ControlledWindowNativeMethods.BringWindowToTop(_hwnd);
            _ready.Set();

            while (true)
            {
                int result = ControlledWindowNativeMethods.GetMessageW(out var msg, IntPtr.Zero, 0, 0);
                if (result <= 0)
                {
                    break;
                }

                ControlledWindowNativeMethods.TranslateMessage(ref msg);
                ControlledWindowNativeMethods.DispatchMessageW(ref msg);
            }
        }
        catch (Exception ex)
        {
            _lastError = "WINDOW_THREAD_EXCEPTION:" + ex.GetType().Name;
        }
        finally
        {
            if (atom != 0 && instance != IntPtr.Zero)
            {
                try
                {
                    ControlledWindowNativeMethods.UnregisterClassW(ClassName, instance);
                }
                catch
                {
                    _lastError = string.IsNullOrEmpty(_lastError)
                        ? "UNREGISTER_CLASS_FAILED"
                        : _lastError;
                }
            }

            WindowThreadExited = true;
            _ready.Set();
            _closed.Set();
        }
    }

    private void AcquireForeground(int timeoutMs)
    {
        if (!Created || !OriginalStateCaptured)
        {
            return;
        }

        ControlledWindowNativeMethods.AllowSetForegroundWindow(ControlledWindowNativeMethods.ASFW_ANY);

        if (TryDirectForeground() || TryAttachedForeground())
        {
            ForegroundAcquired = true;
            return;
        }

        int deadline = Environment.TickCount + Math.Max(0, timeoutMs);
        while (Environment.TickCount < deadline)
        {
            if (ControlledWindowNativeMethods.GetForegroundWindow() == _hwnd)
            {
                ForegroundAcquired = true;
                return;
            }

            Thread.Sleep(20);
        }

        _lastError = "FOREGROUND_NOT_ACQUIRED";
    }

    private bool TryDirectForeground()
    {
        ControlledWindowNativeMethods.SetForegroundWindow(_hwnd);
        return ControlledWindowNativeMethods.GetForegroundWindow() == _hwnd;
    }

    private bool TryAttachedForeground()
    {
        IntPtr foreground = ControlledWindowNativeMethods.GetForegroundWindow();
        uint foregroundThread = foreground == IntPtr.Zero
            ? 0
            : ControlledWindowNativeMethods.GetWindowThreadProcessId(foreground, out _);
        uint currentThread = ControlledWindowNativeMethods.GetCurrentThreadId();

        bool attached = false;
        if (foregroundThread != 0 && foregroundThread != currentThread)
        {
            attached = ControlledWindowNativeMethods.AttachThreadInput(foregroundThread, currentThread, true);
        }

        try
        {
            ControlledWindowNativeMethods.SetWindowPos(
                _hwnd,
                IntPtr.Zero,
                0,
                0,
                0,
                0,
                ControlledWindowNativeMethods.SWP_NOMOVE | ControlledWindowNativeMethods.SWP_NOSIZE |
                ControlledWindowNativeMethods.SWP_SHOWWINDOW);
            ControlledWindowNativeMethods.SetForegroundWindow(_hwnd);
            return ControlledWindowNativeMethods.GetForegroundWindow() == _hwnd;
        }
        finally
        {
            if (attached)
            {
                ControlledWindowNativeMethods.AttachThreadInput(foregroundThread, currentThread, false);
            }
        }
    }

    public bool TryReadCurrentCursor(out (int X, int Y) position)
    {
        try
        {
            if (ControlledWindowNativeMethods.GetCursorPos(out ControlledWindowNativeMethods.POINT point))
            {
                position = (point.X, point.Y);
                CursorAfter = position;
                CursorAfterReadSucceeded = true;
                return true;
            }
        }
        catch (Exception ex)
        {
            _lastError = "CURRENT_CURSOR_READ_EXCEPTION:" + ex.GetType().Name;
        }

        position = default;
        CursorAfterReadSucceeded = false;
        if (string.IsNullOrEmpty(_lastError))
        {
            _lastError = "CURRENT_CURSOR_READ_FAILED";
        }

        return false;
    }

    /// <summary>Harness-only cursor placement, used before arming a test.</summary>
    public bool PlaceCursor(int x, int y)
    {
        Interlocked.Increment(ref _cursorSetCounter);
        try
        {
            return ControlledWindowNativeMethods.SetCursorPos(x, y);
        }
        catch (Exception ex)
        {
            _lastError = "CURSOR_PLACE_EXCEPTION:" + ex.GetType().Name;
            return false;
        }
    }

    /// <summary>
    /// Restores the cursor captured before window creation.  This is called only
    /// by the cleanup coordinator on the no-takeover branch; it verifies both the
    /// Win32 return value and the final coordinates.
    /// </summary>
    public bool RestoreOriginalCursor()
    {
        CursorRestoreAttempted = true;
        CursorRestoreSkipped = false;

        if (!OriginalCursorCaptured)
        {
            CursorRestored = false;
            CursorRestoreReason = "ORIGINAL_CURSOR_UNAVAILABLE";
            return false;
        }

        bool requested;
        try
        {
            Interlocked.Increment(ref _cursorSetCounter);
            requested = ControlledWindowNativeMethods.SetCursorPos(CursorBefore.X, CursorBefore.Y);
        }
        catch (Exception ex)
        {
            CursorRestored = false;
            CursorRestoreReason = "CURSOR_RESTORE_EXCEPTION:" + ex.GetType().Name;
            return false;
        }

        bool read = TryReadCurrentCursor(out var actual);
        CursorRestored = requested && read && actual == CursorBefore;
        CursorRestoreReason = CursorRestored
            ? "CURSOR_RESTORE_OK"
            : requested ? "CURSOR_RESTORE_COORDINATE_MISMATCH" : "CURSOR_RESTORE_FAILED";
        return CursorRestored;
    }

    /// <summary>
    /// Validates a cursor restore performed by the guard.  This method never calls
    /// SetCursorPos, so it cannot duplicate the guard's restore or override a
    /// takeover decision.
    /// </summary>
    public bool VerifyGuardCursorRestore(bool guardReturnValue, (int X, int Y) expected)
    {
        CursorRestoreAttempted = true;
        CursorRestoreSkipped = false;
        CursorRestored = guardReturnValue && TryReadCurrentCursor(out var actual) && actual == expected;
        CursorRestoreReason = CursorRestored
            ? "CURSOR_RESTORE_OK"
            : guardReturnValue ? "CURSOR_RESTORE_COORDINATE_MISMATCH" : "CURSOR_RESTORE_FAILED";
        return CursorRestored;
    }

    /// <summary>Records the takeover branch and reads, but never moves, the cursor.</summary>
    public bool PreserveUserCursor()
    {
        CursorRestoreAttempted = false;
        CursorRestoreSkipped = true;
        bool read = TryReadCurrentCursor(out _);
        CursorRestored = false;
        CursorRestoreReason = read ? "CURSOR_RESTORE_USER_TAKEOVER" : "CURRENT_CURSOR_READ_FAILED";
        return read;
    }

    public bool RestorePreviousForeground(
        Func<TakeoverReadResult> readTakeover,
        TimeSpan confirmationTimeout,
        TimeSpan pollInterval)
    {
        ArgumentNullException.ThrowIfNull(readTakeover);
        ForegroundRestoreAttempted = true;
        ForegroundRestoreSkipped = false;

        ForegroundRestoreResult result = ForegroundRestoreVerifier.Restore(
            PreviousForeground,
            OriginalForegroundCaptured,
            ControlledWindowNativeMethods.IsWindow,
            ControlledWindowNativeMethods.GetForegroundWindow,
            ControlledWindowNativeMethods.SetForegroundWindow,
            readTakeover,
            confirmationTimeout,
            pollInterval);

        ForegroundRestoreOriginalWindowValid = result.OriginalWindowValid;
        ForegroundBeforeRestore = result.ActualBefore;
        ForegroundBeforeRestoreReadSucceeded = result.ActualBeforeRead;
        ForegroundSetCalled = result.SetForegroundCalled;
        ForegroundSetReturned = result.SetForegroundReturned;
        ForegroundAfterRestore = result.ActualAfter;
        ForegroundAfterRestoreReadSucceeded = result.ActualAfterRead;
        ForegroundBeforeRestoreStatus = result.ActualBeforeStatus;
        ForegroundAfterRestoreStatus = result.ActualAfterStatus;
        ForegroundNullReadCount = result.NullForegroundReadCount;
        ForegroundRestorePollCount = result.PollCount;
        ForegroundRestoreTakeoverReadCount = result.TakeoverReadCount;
        ForegroundRestoreElapsedMs = result.ElapsedMs;
        ForegroundRestoreTakeoverDetected = result.UserTakeover;
        ForegroundRestoreSkipped = result.Skipped;
        ForegroundRestored = result.Ok;
        ForegroundRestoreReason = result.Reason;
        return result.Ok;
    }

    public bool PreserveUserForeground()
    {
        ForegroundRestoreAttempted = false;
        ForegroundRestoreSkipped = true;
        ForegroundRestored = false;
        ForegroundRestoreTakeoverDetected = true;
        ForegroundRestoreReason = "FOREGROUND_RESTORE_USER_TAKEOVER";
        return true;
    }

    private IntPtr WindowProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
        switch (msg)
        {
            case ControlledWindowNativeMethods.WM_APP_L5_PROMPT:
                lock (_promptGate)
                {
                    _promptDisplayed = true;
                }

                ControlledWindowNativeMethods.InvalidateRect(hWnd, IntPtr.Zero, true);
                ControlledWindowNativeMethods.UpdateWindow(hWnd);
                return new IntPtr(1);

            case ControlledWindowNativeMethods.WM_PAINT:
                DrawPrompt(hWnd);
                return IntPtr.Zero;

            case ControlledWindowNativeMethods.WM_MOUSEWHEEL:
                Interlocked.Increment(ref _wheelCounter);
                NotifyWindowMessage("WM_MOUSEWHEEL");
                return IntPtr.Zero;

            case ControlledWindowNativeMethods.WM_MOUSEHWHEEL:
                Interlocked.Increment(ref _horizontalWheelCounter);
                NotifyWindowMessage("WM_MOUSEHWHEEL");
                return IntPtr.Zero;

            case ControlledWindowNativeMethods.WM_MOUSEMOVE:
                Interlocked.Increment(ref _moveCounter);
                NotifyWindowMessage("WM_MOUSEMOVE");
                return IntPtr.Zero;

            case ControlledWindowNativeMethods.WM_LBUTTONDOWN:
            case ControlledWindowNativeMethods.WM_RBUTTONDOWN:
                Interlocked.Increment(ref _buttonCounter);
                NotifyWindowMessage(msg == ControlledWindowNativeMethods.WM_LBUTTONDOWN
                    ? "WM_LBUTTONDOWN"
                    : "WM_RBUTTONDOWN");
                return IntPtr.Zero;

            case ControlledWindowNativeMethods.WM_APP_SHUTDOWN:
                ControlledWindowNativeMethods.DestroyWindow(hWnd);
                return IntPtr.Zero;

            case ControlledWindowNativeMethods.WM_DESTROY:
                ControlledWindowNativeMethods.PostQuitMessage(0);
                return IntPtr.Zero;
        }

        return ControlledWindowNativeMethods.DefWindowProcW(hWnd, msg, wParam, lParam);
    }

    public bool DisplayPrompt(string text, out string reason)
    {
        reason = string.Empty;
        if (!Created || !ThreadAlive)
        {
            reason = "L5_PROMPT_WINDOW_NOT_ALIVE";
            return false;
        }

        lock (_promptGate)
        {
            _promptText = text;
            _promptDisplayed = false;
        }

        try
        {
            IntPtr response = ControlledWindowNativeMethods.SendMessageW(
                _hwnd,
                ControlledWindowNativeMethods.WM_APP_L5_PROMPT,
                IntPtr.Zero,
                IntPtr.Zero);
            if (response == IntPtr.Zero || !PromptDisplayed)
            {
                reason = "L5_PROMPT_DISPLAY_FAILED";
                return false;
            }

            reason = "L5_PROMPT_DISPLAYED";
            return true;
        }
        catch (Exception ex)
        {
            reason = "L5_PROMPT_DISPLAY_EXCEPTION:" + ex.GetType().Name;
            return false;
        }
    }

    private void DrawPrompt(IntPtr hWnd)
    {
        string text;
        lock (_promptGate)
        {
            text = _promptText;
        }

        IntPtr hdc = ControlledWindowNativeMethods.GetDC(hWnd);
        if (hdc == IntPtr.Zero)
        {
            ControlledWindowNativeMethods.ValidateRect(hWnd, IntPtr.Zero);
            return;
        }

        try
        {
            if (ControlledWindowNativeMethods.GetClientRect(
                    hWnd,
                    out ControlledWindowNativeMethods.RECT rect))
            {
                ControlledWindowNativeMethods.SetBkMode(hdc, ControlledWindowNativeMethods.TRANSPARENT);
                ControlledWindowNativeMethods.SetTextColor(hdc, 0x00000000);
                ControlledWindowNativeMethods.DrawTextW(
                    hdc,
                    text,
                    -1,
                    ref rect,
                    ControlledWindowNativeMethods.DT_CENTER |
                    ControlledWindowNativeMethods.DT_VCENTER |
                    ControlledWindowNativeMethods.DT_SINGLELINE);
            }
        }
        finally
        {
            ControlledWindowNativeMethods.ValidateRect(hWnd, IntPtr.Zero);
            ControlledWindowNativeMethods.ReleaseDC(hWnd, hdc);
        }
    }

    private void NotifyWindowMessage(string message)
    {
        try
        {
            WindowMessageObserver?.Invoke(message);
        }
        catch
        {
            // Evidence observers must never break the controlled window pump.
        }
    }

    private long _wheelCounter;
    private long _horizontalWheelCounter;
    private long _moveCounter;
    private long _buttonCounter;
    private long _cursorSetCounter;

    public bool RequestShutdown()
    {
        if (Volatile.Read(ref _syncDisposed) != 0)
        {
            _lastError = "WINDOW_SYNC_ALREADY_DISPOSED";
            return false;
        }

        if (!Created)
        {
            return true;
        }

        if (Interlocked.Exchange(ref _shutdownRequested, 1) != 0)
        {
            return true;
        }

        try
        {
            bool posted = ControlledWindowNativeMethods.PostMessageW(
                _hwnd, ControlledWindowNativeMethods.WM_APP_SHUTDOWN, IntPtr.Zero, IntPtr.Zero);
            if (!posted)
            {
                _lastError = "WINDOW_SHUTDOWN_POST_FAILED";
            }

            return posted;
        }
        catch (Exception ex)
        {
            _lastError = "WINDOW_SHUTDOWN_POST_EXCEPTION:" + ex.GetType().Name;
            return false;
        }
    }

    public bool ShutdownAndWait(TimeSpan timeout)
    {
        if (_thread is null)
        {
            WindowThreadExited = true;
            return true;
        }

        RequestShutdown();
        Stopwatch stopwatch = Stopwatch.StartNew();
        TimeSpan remaining = timeout - stopwatch.Elapsed;
        if (remaining > TimeSpan.Zero && !_closed.Wait(remaining))
        {
            _lastError = "WINDOW_THREAD_EXIT_TIMEOUT";
            WindowThreadExited = false;
            return false;
        }

        remaining = timeout - stopwatch.Elapsed;
        if (remaining > TimeSpan.Zero && _thread.IsAlive)
        {
            _thread.Join(remaining);
        }

        if (_thread.IsAlive)
        {
            _lastError = "WINDOW_THREAD_EXIT_TIMEOUT";
            WindowThreadExited = false;
            return false;
        }

        WindowThreadExited = true;
        return true;
    }

    /// <summary>
    /// Synchronization objects are released only after the window thread has
    /// exited.  A timeout is a failure and intentionally leaves the objects
    /// available for a later retry.
    /// </summary>
    public bool DisposeSynchronizationIfSafe()
    {
        if (Volatile.Read(ref _syncDisposed) != 0)
        {
            return true;
        }

        if (ThreadAlive || !WindowThreadExited)
        {
            _lastError = "WINDOW_SYNC_DISPOSE_BLOCKED_THREAD_ALIVE";
            return false;
        }

        if (Interlocked.Exchange(ref _syncDisposed, 1) != 0)
        {
            return true;
        }

        _ready.Dispose();
        _closed.Dispose();
        return true;
    }

    public void Dispose()
    {
        // Dispose is deliberately lifecycle-only.  Cursor and foreground policy
        // must have been decided by the cleanup coordinator before this call.
        ShutdownAndWait(TimeSpan.FromSeconds(2));
        DisposeSynchronizationIfSafe();
    }
}
