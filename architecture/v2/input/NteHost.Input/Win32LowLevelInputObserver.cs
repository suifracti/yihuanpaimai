using System.Runtime.InteropServices;

namespace NteHost.Input;

public sealed record ObserverStartOutcome(bool Ok, string Reason);

public sealed record ObserverDiagnostics(
    string Name,
    bool HooksInstalled,
    bool IsRunning,
    bool ThreadAlive,
    bool KeyboardHookReleased,
    bool MouseHookReleased,
    long KeyboardEventsObserved,
    long MouseEventsObserved,
    long ForwardedEvents,
    long SuppressedInputEvents,
    long SinkFaults,
    double CallbackMaxUs,
    double CallbackP95Us,
    string LastError)
{
    /// <summary>Exceptions while decoding/classifying hook payloads.</summary>
    public long ClassificationFaults { get; init; }
}

/// <summary>
/// Low-level input observation. The observer is a *witness*, never a filter:
/// its hook procedure always chains to <c>CallNextHookEx</c>, so user input is
/// never swallowed, delayed beyond a bounded in-memory decision, or hijacked.
/// </summary>
public interface IInputObserver
{
    string Name { get; }

    bool IsRunning { get; }

    ObserverStartOutcome Start(Action<ObservedInputEvent> sink);

    void Stop();

    ObserverDiagnostics Diagnostics();
}

/// <summary>
/// Deterministic observer used by the targeted matrix. It lets a test deliver an
/// exactly-specified <see cref="ObservedInputEvent"/> to the guard, including
/// events that cannot be produced through the real OS path (a genuinely
/// non-injected "hardware" event, a lower-integrity injection, a spoofed marker).
/// The real <see cref="Win32LowLevelInputObserver"/> is exercised separately by the
/// live controlled-window scenarios.
/// </summary>
public sealed class FakeInputObserver : IInputObserver
{
    private readonly object _gate = new();
    private Action<ObservedInputEvent>? _sink;
    private long _sequence;

    public string Name { get; init; } = "fake";

    public bool IsRunning { get; private set; }

    public long EmittedCount { get; private set; }

    public ObserverStartOutcome Start(Action<ObservedInputEvent> sink)
    {
        lock (_gate)
        {
            _sink = sink;
            IsRunning = true;
        }

        return new ObserverStartOutcome(true, InputSafetyReasons.Ok);
    }

    public void Stop()
    {
        lock (_gate)
        {
            IsRunning = false;
            _sink = null;
        }
    }

    public ObserverDiagnostics Diagnostics() => new(
        Name, IsRunning, IsRunning, false, true, true, 0, 0, EmittedCount, 0, 0, 0, 0, string.Empty)
    {
        ClassificationFaults = 0,
    };

    public void Emit(in ObservedInputEvent observed)
    {
        Action<ObservedInputEvent>? sink;
        lock (_gate)
        {
            sink = _sink;
            EmittedCount++;
        }

        sink?.Invoke(observed);
    }

    public ObservedInputEvent Next(
        InputEventKind kind,
        InputEventOrigin origin,
        ulong extraInfo,
        int x = 0,
        int y = 0,
        uint nativeFlags = 0)
    {
        InputDeviceClass device = kind == InputEventKind.KeyDown
            ? InputDeviceClass.Keyboard
            : InputDeviceClass.Mouse;

        return new ObservedInputEvent(
            kind,
            device,
            origin,
            extraInfo,
            x,
            y,
            TraceClock.NowNs(),
            Interlocked.Increment(ref _sequence))
        {
            NativeFlags = nativeFlags,
        };
    }
}

/// <summary>
/// Dedicated-thread Windows low-level keyboard + mouse observer.
///
/// Design constraints that matter for safety:
///   * the hook procedure performs only bounded, allocation-free classification
///     and one synchronous callback. The callback contract is "in-memory state
///     transition only, never an OS call", which is what keeps hook latency far
///     below the machine's LowLevelHooksTimeout and prevents a stalled hook queue.
///   * the hook procedure never throws and never returns a suppressing value.
///   * teardown posts WM_QUIT to the owning thread and unhooks on that same
///     thread inside a finally block, so handles are released even on failure.
///
/// It records no key codes, no scan codes, no typed text and no coordinate
/// history. Only the closed event set in <see cref="InputEventKind"/> is forwarded.
/// </summary>
public sealed class Win32LowLevelInputObserver : IInputObserver
{
    private const int LatencySampleCapacity = 4096;
    private const int P95 = 95;

    private readonly object _gate = new();
    private readonly double[] _latencySamplesUs = new double[LatencySampleCapacity];
    private readonly ManualResetEventSlim _startedEvent = new(false);

    private NativeInputMethods.HookProc? _keyboardProc;
    private NativeInputMethods.HookProc? _mouseProc;
    private Action<ObservedInputEvent>? _sink;
    private Thread? _thread;
    private uint _threadId;
    private IntPtr _keyboardHook = IntPtr.Zero;
    private IntPtr _mouseHook = IntPtr.Zero;
    private bool _running;
    private bool _hooksInstalled;
    private string _lastError = string.Empty;

    private int _latencySampleCount;
    private double _callbackMaxUs;
    private long _keyboardEvents;
    private long _mouseEvents;
    private long _forwardedEvents;
    private long _sinkFaults;
    private long _classificationFaults;
    private long _sequence;

    public Win32LowLevelInputObserver(string name = "guard")
    {
        Name = name;
    }

    public string Name { get; }

    public bool IsRunning
    {
        get { lock (_gate) { return _running; } }
    }

    public ObserverStartOutcome Start(Action<ObservedInputEvent> sink)
    {
        ArgumentNullException.ThrowIfNull(sink);

        lock (_gate)
        {
            if (_running)
            {
                return new ObserverStartOutcome(true, InputSafetyReasons.Ok);
            }

            _sink = sink;
            _lastError = string.Empty;
            _startedEvent.Reset();
            _keyboardHook = IntPtr.Zero;
            _mouseHook = IntPtr.Zero;
            _hooksInstalled = false;

            _thread = new Thread(HookThreadMain)
            {
                IsBackground = true,
                Name = $"nte-input-observer-{Name}",
            };
            _thread.Start();
        }

        if (!_startedEvent.Wait(TimeSpan.FromSeconds(3)))
        {
            Stop();
            return new ObserverStartOutcome(false, "HOOK_START_TIMEOUT");
        }

        lock (_gate)
        {
            if (!_hooksInstalled)
            {
                string error = string.IsNullOrEmpty(_lastError) ? "HOOK_INSTALL_FAILED" : _lastError;
                _running = false;
                _thread = null;
                _sink = null;
                return new ObserverStartOutcome(false, error);
            }

            _running = true;
            return new ObserverStartOutcome(true, InputSafetyReasons.Ok);
        }
    }

    public void Stop()
    {
        Thread? thread;
        uint threadId;

        lock (_gate)
        {
            if (!_running && _thread is null)
            {
                return;
            }

            _running = false;
            thread = _thread;
            threadId = _threadId;
        }

        if (threadId != 0)
        {
            NativeInputMethods.PostThreadMessageW(threadId, NativeInputMethods.WM_QUIT, UIntPtr.Zero, IntPtr.Zero);
        }

        if (thread is not null && thread.IsAlive)
        {
            thread.Join(TimeSpan.FromSeconds(2));
        }

        lock (_gate)
        {
            _thread = null;
            _threadId = 0;
            _sink = null;
            _keyboardProc = null;
            _mouseProc = null;
            _hooksInstalled = false;
        }
    }

    public ObserverDiagnostics Diagnostics()
    {
        lock (_gate)
        {
        return new ObserverDiagnostics(
                Name,
                _hooksInstalled,
                _running,
                _thread is { IsAlive: true },
                _keyboardHook == IntPtr.Zero,
                _mouseHook == IntPtr.Zero,
                Interlocked.Read(ref _keyboardEvents),
                Interlocked.Read(ref _mouseEvents),
                Interlocked.Read(ref _forwardedEvents),
                // Hard invariant: this observer never returns a suppressing value
                // from its hook procedure, so the count is structurally 0.
                0,
                Interlocked.Read(ref _sinkFaults),
                _callbackMaxUs,
                Percentile(95),
                _lastError)
            {
                ClassificationFaults = Interlocked.Read(ref _classificationFaults),
            };
        }
    }

    private double Percentile(double percentile)
    {
        int count = Volatile.Read(ref _latencySampleCount);
        if (count <= 0)
        {
            return 0;
        }

        var copy = new double[count];
        Array.Copy(_latencySamplesUs, copy, count);
        Array.Sort(copy);
        int index = (int)Math.Ceiling(percentile / 100.0 * count) - 1;
        return copy[Math.Clamp(index, 0, count - 1)];
    }

    private void RecordLatency(double micros)
    {
        int slot = Interlocked.Increment(ref _latencySampleCount) - 1;
        if (slot < LatencySampleCapacity)
        {
            _latencySamplesUs[slot] = micros;
        }

        double current = Volatile.Read(ref _callbackMaxUs);
        while (micros > current)
        {
            double observed = Interlocked.CompareExchange(ref _callbackMaxUs, micros, current);
            if (observed == current)
            {
                break;
            }

            current = observed;
        }
    }

    private void HookThreadMain()
    {
        // Force the thread message queue into existence before publishing the
        // thread id, otherwise an early Stop() could post WM_QUIT into the void.
        NativeInputMethods.PeekMessageW(out _, IntPtr.Zero, 0, 0, 0);

        lock (_gate)
        {
            _threadId = NativeInputMethods.GetCurrentThreadId();
        }

        _keyboardProc = KeyboardHookProc;
        _mouseProc = MouseHookProc;

        try
        {
            _keyboardHook = NativeInputMethods.SetWindowsHookExW(
                NativeInputMethods.WH_KEYBOARD_LL, _keyboardProc, IntPtr.Zero, 0);
            if (_keyboardHook == IntPtr.Zero)
            {
                lock (_gate) { _lastError = "HOOK_KB_FAILED"; }
                _startedEvent.Set();
                return;
            }

            _mouseHook = NativeInputMethods.SetWindowsHookExW(
                NativeInputMethods.WH_MOUSE_LL, _mouseProc, IntPtr.Zero, 0);
            if (_mouseHook == IntPtr.Zero)
            {
                lock (_gate) { _lastError = "HOOK_MS_FAILED"; }
                NativeInputMethods.UnhookWindowsHookEx(_keyboardHook);
                _keyboardHook = IntPtr.Zero;
                _startedEvent.Set();
                return;
            }

            lock (_gate) { _hooksInstalled = true; }
            _startedEvent.Set();
        }
        catch (Exception ex)
        {
            lock (_gate) { _lastError = "HOOK_INSTALL_EXCEPTION: " + ex.GetType().Name; }
            TryUnhook(ref _keyboardHook);
            TryUnhook(ref _mouseHook);
            _startedEvent.Set();
            return;
        }

        try
        {
            while (true)
            {
                int result = NativeInputMethods.GetMessageW(out var msg, IntPtr.Zero, 0, 0);
                if (result <= 0)
                {
                    break;
                }

                NativeInputMethods.TranslateMessage(ref msg);
                NativeInputMethods.DispatchMessageW(ref msg);
            }
        }
        catch
        {
            // Message pump faults must not leave hooks installed.
        }
        finally
        {
            TryUnhook(ref _keyboardHook);
            TryUnhook(ref _mouseHook);
            lock (_gate) { _hooksInstalled = false; }
        }
    }

    private static void TryUnhook(ref IntPtr hook)
    {
        IntPtr handle = hook;
        hook = IntPtr.Zero;
        if (handle != IntPtr.Zero)
        {
            try
            {
                NativeInputMethods.UnhookWindowsHookEx(handle);
            }
            catch
            {
                // Best effort: the handle is already dropped from our state.
            }
        }
    }

    private IntPtr KeyboardHookProc(int nCode, IntPtr wParam, IntPtr lParam)
    {
        long startTicks = System.Diagnostics.Stopwatch.GetTimestamp();
        try
        {
            if (nCode >= 0)
            {
                int message = (int)wParam;
                if (message == NativeInputMethods.WM_KEYDOWN || message == NativeInputMethods.WM_SYSKEYDOWN)
                {
                    var data = Marshal.PtrToStructure<NativeInputMethods.KBDLLHOOKSTRUCT>(lParam);
                    Interlocked.Increment(ref _keyboardEvents);
                    Forward(new ObservedInputEvent(
                        InputEventKind.KeyDown,
                        InputDeviceClass.Keyboard,
                        ResolveOrigin(data.flags, NativeInputMethods.LLKHF_LOWER_IL_INJECTED, NativeInputMethods.LLKHF_INJECTED),
                        InputMarker.FromNative(data.dwExtraInfo),
                        0,
                        0,
                        TraceClock.NowNs(),
                        Interlocked.Increment(ref _sequence))
                    {
                        NativeFlags = data.flags,
                    });
                }
            }
        }
        catch
        {
            Interlocked.Increment(ref _classificationFaults);
            // Never let a classification fault escape into the OS hook chain.
        }
        finally
        {
            RecordLatency((System.Diagnostics.Stopwatch.GetTimestamp() - startTicks) * 1_000_000.0 /
                          System.Diagnostics.Stopwatch.Frequency);
        }

        // Always chain. This module never suppresses input.
        return NativeInputMethods.CallNextHookEx(_keyboardHook, nCode, wParam, lParam);
    }

    private IntPtr MouseHookProc(int nCode, IntPtr wParam, IntPtr lParam)
    {
        long startTicks = System.Diagnostics.Stopwatch.GetTimestamp();
        try
        {
            if (nCode >= 0)
            {
                int message = (int)wParam;
                InputEventKind? kind = message switch
                {
                    NativeInputMethods.WM_MOUSEMOVE => InputEventKind.MouseMove,
                    NativeInputMethods.WM_LBUTTONDOWN => InputEventKind.MouseButtonDown,
                    NativeInputMethods.WM_RBUTTONDOWN => InputEventKind.MouseButtonDown,
                    NativeInputMethods.WM_MBUTTONDOWN => InputEventKind.MouseButtonDown,
                    NativeInputMethods.WM_XBUTTONDOWN => InputEventKind.MouseButtonDown,
                    NativeInputMethods.WM_MOUSEWHEEL => InputEventKind.MouseWheel,
                    NativeInputMethods.WM_MOUSEHWHEEL => InputEventKind.MouseHorizontalWheel,
                    _ => null,
                };

                if (kind is not null)
                {
                    var data = Marshal.PtrToStructure<NativeInputMethods.MSLLHOOKSTRUCT>(lParam);
                    Interlocked.Increment(ref _mouseEvents);
                    Forward(new ObservedInputEvent(
                        kind.Value,
                        InputDeviceClass.Mouse,
                        ResolveOrigin(data.flags, NativeInputMethods.LLMHF_LOWER_IL_INJECTED, NativeInputMethods.LLMHF_INJECTED),
                        InputMarker.FromNative(data.dwExtraInfo),
                        data.pt.X,
                        data.pt.Y,
                        TraceClock.NowNs(),
                        Interlocked.Increment(ref _sequence))
                    {
                        NativeFlags = data.flags,
                    });
                }
            }
        }
        catch
        {
            Interlocked.Increment(ref _classificationFaults);
            // Never let a classification fault escape into the OS hook chain.
        }
        finally
        {
            RecordLatency((System.Diagnostics.Stopwatch.GetTimestamp() - startTicks) * 1_000_000.0 /
                          System.Diagnostics.Stopwatch.Frequency);
        }

        return NativeInputMethods.CallNextHookEx(_mouseHook, nCode, wParam, lParam);
    }

    private static InputEventOrigin ResolveOrigin(uint flags, uint lowerIntegrityFlag, uint injectedFlag)
    {
        if ((flags & lowerIntegrityFlag) != 0)
        {
            return InputEventOrigin.LowerIntegrityInjected;
        }

        if ((flags & injectedFlag) != 0)
        {
            return InputEventOrigin.Injected;
        }

        return InputEventOrigin.Hardware;
    }

    private void Forward(in ObservedInputEvent observed)
    {
        Action<ObservedInputEvent>? sink;
        lock (_gate) { sink = _sink; }

        if (sink is null)
        {
            return;
        }

        try
        {
            sink(observed);
            Interlocked.Increment(ref _forwardedEvents);
        }
        catch
        {
            Interlocked.Increment(ref _sinkFaults);
        }
    }
}
