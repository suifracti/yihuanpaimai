using NteHost.Protocol;
using NteHost.WindowMonitor.Win32;

namespace NteHost.WindowMonitor;

public sealed class WindowMonitorOptions
{
    /// <summary>Semantic definition of the target window.</summary>
    public TargetWindowSpec Spec { get; init; } = TargetWindowSpec.Default;

    /// <summary>
    /// Raw WinEvent queue capacity. The hook callback never blocks, so an
    /// over-running consumer drops the OLDEST record and counts the drop rather
    /// than stalling desktop-wide event delivery.
    /// </summary>
    public int EventQueueCapacity { get; init; } = 4096;

    /// <summary>
    /// When true a target that is still a live window but has become hidden is
    /// treated as lost: an invisible game window cannot be interacted with.
    /// </summary>
    public bool RequireVisible { get; init; } = true;

    /// <summary>
    /// Pass WINEVENT_SKIPOWNPROCESS to the hook. Off by default so the module also
    /// observes windows owned by its own process, which keeps controlled-window
    /// testing honest. The real target lives in another process either way.
    /// </summary>
    public bool SkipOwnProcessInHook { get; init; }

    /// <summary>
    /// Minimum spacing between two recovery enumerations. Recovery is a fallback,
    /// so it is rate-limited even if triggers arrive in a burst.
    /// </summary>
    public int RecoveryScanMinIntervalMs { get; init; } = 200;
}

/// <summary>
/// The V2-2A target window / focus monitor.
///
/// Threading model:
///   * the WinEvent pump thread only enqueues raw events (never blocks);
///   * one worker thread owns the state machine, so event ordering is total;
///   * callers read snapshots, which validate the held handle before answering.
///
/// Steady state is fully event driven. EnumWindows runs only as a bounded recovery
/// fallback, and every recovery run is counted and reported.
/// </summary>
public sealed class WindowMonitor : IRawWinEventSink, IDisposable
{
    private readonly WindowMonitorOptions _options;
    private readonly WindowIdentityReader _identityReader = new();
    private readonly WindowEnumerator _enumerator;
    private readonly WinEventHookSource _hook;
    private readonly object _gate = new();

    private readonly Queue<RawWinEvent> _queue = new();
    private readonly List<WindowMonitorEvent> _events = new();

    private Thread? _worker;
    private volatile bool _stopRequested;
    private bool _started;

    private WindowIdentity? _target;
    private long _generation;
    private bool _isTargetForeground;
    private bool _needsRecoveryScan;
    private long _lastRecoveryScanTick;
    private long _sequence;
    private long _droppedEvents;
    private long _processedEvents;

    public WindowMonitor(WindowMonitorOptions? options = null)
    {
        _options = options ?? new WindowMonitorOptions();
        _enumerator = new WindowEnumerator(_identityReader);
        _hook = new WinEventHookSource(this, _options.SkipOwnProcessInHook);
    }

    public TargetWindowSpec Spec => _options.Spec;

    public long RecoveryScanCount => _enumerator.EnumerationCount;

    public long DroppedEventCount => Interlocked.Read(ref _droppedEvents);

    public long ProcessedEventCount => Interlocked.Read(ref _processedEvents);

    public long RawCallbackCount => _hook.RawCallbackCount;

    public long ImageNameResolutions => _identityReader.ImageNameResolutions;

    public bool IsHookInstalled => _hook.IsHookInstalled;

    public bool IsRunning => _started && !_stopRequested;

    // ------------------------------------------------------------------ lifetime

    public void Start()
    {
        if (_started)
        {
            throw new InvalidOperationException("the window monitor is already started");
        }
        _started = true;
        _stopRequested = false;

        _worker = new Thread(WorkerLoop)
        {
            IsBackground = true,
            Name = "nte-window-monitor-worker",
        };
        _worker.Start();

        // Hook first, then scan: anything created during the scan still produces an
        // event, so no window can slip through the gap between scan and hook.
        _hook.Start();
        RequestRecoveryScan("initial-scan");
    }

    /// <summary>Marks that a recovery enumeration is due. Cheap and idempotent.</summary>
    public void RequestRecoveryScan(string reason)
    {
        lock (_gate)
        {
            _needsRecoveryScan = true;
            _pendingRecoveryReason = reason;
        }
        Signal();
    }

    private string _pendingRecoveryReason = "recovery";

    public void Dispose()
    {
        _stopRequested = true;
        Signal();

        _hook.Dispose();
        _worker?.Join(3000);
        _worker = null;

        lock (_gate)
        {
            _queue.Clear();
            _target = null;
            _isTargetForeground = false;
        }
        _identityReader.ClearCache();
    }

    // ------------------------------------------------------------------ raw sink

    /// <summary>
    /// Called on the WinEvent pump thread. Must not block: it stamps the time,
    /// enqueues, and returns.
    /// </summary>
    public void OnRawWinEvent(uint eventType, long hwnd, int idObject)
    {
        var observedAtNs = ProtocolClock.NowNs();

        lock (_gate)
        {
            if (_queue.Count >= _options.EventQueueCapacity)
            {
                _queue.Dequeue();
                _droppedEvents++;
            }
            _queue.Enqueue(new RawWinEvent(eventType, hwnd, observedAtNs));
        }
        Signal();
    }

    private readonly SemaphoreSlim _wake = new(0, int.MaxValue);

    private void Signal()
    {
        try
        {
            _wake.Release();
        }
        catch (SemaphoreFullException)
        {
            // already awake; nothing to do
        }
    }

    // ------------------------------------------------------------------ worker

    private void WorkerLoop()
    {
        while (!_stopRequested)
        {
            _wake.Wait(20);
            while (_wake.CurrentCount > 0)
            {
                _wake.Wait(0);
            }

            RawWinEvent[] batch;
            bool overflowed;
            lock (_gate)
            {
                batch = _queue.ToArray();
                _queue.Clear();
                overflowed = _droppedEvents > 0;
            }

            if (overflowed)
            {
                RequestRecoveryScan("event-queue-overflow");
            }

            if (batch.Length == 0)
            {
                // Nothing to do; if a recovery scan is due, run it now.
                RunPendingRecoveryScanIfDue();
                continue;
            }

            Interlocked.Add(ref _processedEvents, batch.Length);
            ProcessBatch(batch);
        }
    }

    private void ProcessBatch(RawWinEvent[] batch)
    {
        foreach (var raw in batch)
        {
            lock (_gate)
            {
                if (_target is null)
                {
                    // Cheap path first: promote the event HWND if it matches, before
                    // considering a full enumeration.
                    TryPromote(raw);
                }
                else
                {
                    // The target may itself be the subject of this event.
                    if (raw.Hwnd != 0 && raw.Hwnd == _target.Hwnd &&
                        raw.EventType is WinEvent.EVENT_OBJECT_DESTROY or WinEvent.EVENT_OBJECT_HIDE)
                    {
                        LoseTarget(WinEvent.Name(raw.EventType), raw.ObservedAtNs, "target window destroy/hide event");
                    }
                }
            }

            // Foreground is authoritative from the OS, not from the event payload.
            EvaluateForeground(raw.EventType, raw.ObservedAtNs);
        }

        RunPendingRecoveryScanIfDue();
    }

    private void RunPendingRecoveryScanIfDue()
    {
        bool due;
        string reason;
        lock (_gate)
        {
            due = _needsRecoveryScan;
            reason = _pendingRecoveryReason;
        }
        if (!due)
        {
            return;
        }

        // Recovery exists to find a target we do not have. Once a target is held,
        // enumerating would be pure cost and would muddy the event stream, so the
        // pending request is simply cleared.
        lock (_gate)
        {
            if (_target is not null)
            {
                _needsRecoveryScan = false;
                return;
            }
        }

        var now = Environment.TickCount64;
        if (now - Interlocked.Read(ref _lastRecoveryScanTick) < _options.RecoveryScanMinIntervalMs)
        {
            return;
        }
        Interlocked.Exchange(ref _lastRecoveryScanTick, now);

        lock (_gate)
        {
            _needsRecoveryScan = false;
        }

        var matches = _enumerator.FindMatches(_options.Spec, _options.RequireVisible);
        var scanNs = ProtocolClock.NowNs();

        lock (_gate)
        {
            Emit(WindowMonitorEventKind.RecoveryScanPerformed, "scan", 0, scanNs,
                $"reason={reason}; matches={matches.Count}");

            if (_target is null && matches.Count > 0)
            {
                Adopt(PreferForeground(matches), "recovery-scan", scanNs);
            }
        }

        EvaluateForeground(0, scanNs);
    }

    /// <summary>
    /// When several windows satisfy the spec, prefer the one the user is actually
    /// looking at; otherwise take the lowest HWND so the choice is deterministic.
    /// </summary>
    private static WindowIdentity PreferForeground(IReadOnlyList<WindowIdentity> matches)
    {
        var foreground = NativeWindowApiForeground();
        if (foreground != 0)
        {
            foreach (var candidate in matches)
            {
                if (candidate.Hwnd == foreground)
                {
                    return candidate;
                }
            }
        }
        return matches[0];
    }

    // ------------------------------------------------------------------ state

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private void TryPromote(RawWinEvent raw)
    {
        if (raw.Hwnd == 0)
        {
            return;
        }

        var identity = _identityReader.Read(raw.Hwnd);
        if (!identity.IsPresent)
        {
            return;
        }
        if (!_options.Spec.Matches(identity.ProcessImageName, identity.ClassName))
        {
            return;
        }
        if (_options.RequireVisible && !identity.IsVisible)
        {
            return;
        }

        Adopt(identity, $"promoted-from-{WinEvent.Name(raw.EventType)}", raw.ObservedAtNs);
    }

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private void Adopt(WindowIdentity identity, string reason, long observedAtNs)
    {
        var reacquire = _generation > 0;
        _target = identity;
        _generation++;

        Emit(reacquire ? WindowMonitorEventKind.TargetReacquired : WindowMonitorEventKind.TargetAcquired,
            reason, identity.Hwnd, observedAtNs,
            $"identity: {identity.Describe()}");

        // A brand new target has an unknown foreground relationship; evaluate it
        // immediately so the snapshot is never stale after acquisition.
        _isTargetForeground = false;
    }

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private void LoseTarget(string reason, long observedAtNs, string detail)
    {
        if (_target is null)
        {
            return;
        }

        var lost = _target;
        Emit(WindowMonitorEventKind.StaleHandleRejected, reason, lost.Hwnd, observedAtNs,
            $"rejected handle: {detail}");

        _target = null;
        _isTargetForeground = false;
        _needsRecoveryScan = true;
        _pendingRecoveryReason = "target-lost";

        Emit(WindowMonitorEventKind.TargetLost, reason, lost.Hwnd, observedAtNs,
            $"lost identity: {lost.Describe()}");
    }

    private void EvaluateForeground(uint sourceEvent, long observedAtNs)
    {
        lock (_gate)
        {
            var foreground = NativeWindowApiForeground();

            if (_target is null)
            {
                _isTargetForeground = false;
                return;
            }

            // Validate before trusting the handle: an HWND is a recyclable integer.
            var stillValid = _identityReader.IsStillSameWindow(_target, _options.RequireVisible);
            if (!stillValid)
            {
                LoseTarget(sourceEvent == 0 ? "validation" : WinEvent.Name(sourceEvent), observedAtNs,
                    "handle failed liveness/identity validation");
                return;
            }

            var isForeground = foreground != 0 && foreground == _target.Hwnd;
            if (isForeground == _isTargetForeground)
            {
                return;
            }

            _isTargetForeground = isForeground;
            Emit(isForeground ? WindowMonitorEventKind.ForegroundGained : WindowMonitorEventKind.ForegroundLost,
                sourceEvent == 0 ? "validation" : WinEvent.Name(sourceEvent), _target.Hwnd, observedAtNs,
                $"foreground=0x{foreground:x} target=0x{_target.Hwnd:x}");
        }
    }

    private static long NativeWindowApiForeground() => Win32.NativeWindowApi.GetForegroundWindow().ToInt64();

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private void Emit(WindowMonitorEventKind kind, string sourceEvent, long hwnd, long observedAtNs, string reason)
    {
        _sequence++;
        _events.Add(new WindowMonitorEvent
        {
            Sequence = _sequence,
            Kind = kind,
            SourceEvent = sourceEvent,
            TargetHwnd = _target?.Hwnd ?? 0,
            TargetPid = _target?.Pid ?? 0,
            ForegroundHwnd = NativeWindowApiForeground(),
            IsTargetAlive = _target is not null,
            IsTargetForeground = _isTargetForeground,
            Generation = _generation,
            ObservedAtNs = observedAtNs,
            Reason = reason,
        });
    }

    // ------------------------------------------------------------------ readers

    /// <summary>
    /// A snapshot that revalidates the held handle before answering, so a consumer
    /// can never read a stale "alive" from a window that died a moment ago.
    /// </summary>
    public WindowMonitorSnapshot Snapshot()
    {
        lock (_gate)
        {
            var foreground = NativeWindowApiForeground();

            if (_target is not null && !_identityReader.IsStillSameWindow(_target, _options.RequireVisible))
            {
                LoseTarget("snapshot-validation", ProtocolClock.NowNs(),
                    "handle failed liveness/identity validation during snapshot");
            }

            var alive = _target is not null;
            var isForeground = alive && foreground != 0 && foreground == _target!.Hwnd;

            return new WindowMonitorSnapshot
            {
                TargetHwnd = _target?.Hwnd ?? 0,
                TargetPid = _target?.Pid ?? 0,
                ForegroundHwnd = foreground,
                IsTargetAlive = alive,
                IsTargetForeground = isForeground,
                Generation = _generation,
                ObservedAtNs = ProtocolClock.NowNs(),
                Reason = alive ? "snapshot" : "no-target",
                TargetIdentity = _target,
            };
        }
    }

    public IReadOnlyList<WindowMonitorEvent> Events
    {
        get
        {
            lock (_gate)
            {
                return _events.ToArray();
            }
        }
    }

    public WindowMonitorEvent? LastEvent
    {
        get
        {
            lock (_gate)
            {
                return _events.Count == 0 ? null : _events[^1];
            }
        }
    }

    /// <summary>Blocks until no raw events are pending and the worker is idle.</summary>
    public bool WaitForIdle(int timeoutMs)
    {
        var deadline = Environment.TickCount64 + timeoutMs;
        while (Environment.TickCount64 < deadline)
        {
            bool empty;
            lock (_gate)
            {
                empty = _queue.Count == 0;
            }
            if (empty)
            {
                // Give the worker one more scheduling slice to finish the batch.
                Thread.Sleep(15);
                lock (_gate)
                {
                    if (_queue.Count == 0)
                    {
                        return true;
                    }
                }
            }
            Thread.Sleep(5);
        }
        return false;
    }

    /// <summary>Blocks until an event of the given kind appears, or the timeout expires.</summary>
    public WindowMonitorEvent? WaitForEvent(WindowMonitorEventKind kind, int timeoutMs)
    {
        var deadline = Environment.TickCount64 + timeoutMs;
        while (Environment.TickCount64 < deadline)
        {
            lock (_gate)
            {
                for (var i = _events.Count - 1; i >= 0; i--)
                {
                    if (_events[i].Kind == kind)
                    {
                        return _events[i];
                    }
                }
            }
            Thread.Sleep(5);
        }
        return null;
    }

    /// <summary>Counts events of a kind, used by tests and by audit output.</summary>
    public int CountEvents(WindowMonitorEventKind kind)
    {
        lock (_gate)
        {
            return _events.Count(e => e.Kind == kind);
        }
    }

    private readonly record struct RawWinEvent(uint EventType, long Hwnd, long ObservedAtNs);
}
