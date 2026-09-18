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

    /// <summary>
    /// Test-only seam. When non-zero, the worker deliberately spends this long on
    /// every identity/state evaluation. It exists so a test can prove that a slow
    /// state-machine path (the real one performs Win32 and process-identity work)
    /// cannot serialise raw callback ingestion. Never set in production wiring.
    /// </summary>
    public int IdentityWorkDelayMsForDiagnostics { get; init; }
}

/// <summary>
/// The V2-2A target window / focus monitor.
///
/// Threading model, and the lock discipline that makes it true:
///   * the WinEvent pump thread only stamps the time and appends to a bounded queue
///     it owns jointly with nobody. It does NOT touch the state lock. See
///     <see cref="RawEventQueue"/> for why that separation is load-bearing.
///   * one worker thread owns the state machine under <see cref="_gate"/>, and is
///     the only place where Win32 / process-identity work happens.
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
    private readonly RawEventQueue _rawQueue;

    /// <summary>State-machine lock. NEVER taken on the WinEvent callback thread.</summary>
    private readonly object _gate = new();

    private readonly SemaphoreSlim _wake = new(0, int.MaxValue);
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
    private long _processedEvents;

    public WindowMonitor(WindowMonitorOptions? options = null)
    {
        _options = options ?? new WindowMonitorOptions();
        _rawQueue = new RawEventQueue(_options.EventQueueCapacity);
        _enumerator = new WindowEnumerator(_identityReader);
        _hook = new WinEventHookSource(this, _options.SkipOwnProcessInHook);
    }

    public TargetWindowSpec Spec => _options.Spec;

    public long RecoveryScanCount => _enumerator.EnumerationCount;

    public long DroppedEventCount => _rawQueue.DroppedCount;

    public long ProcessedEventCount => Interlocked.Read(ref _processedEvents);

    public long RawCallbackCount => _hook.RawCallbackCount;

    public long ImageNameResolutions => _identityReader.ImageNameResolutions;

    /// <summary>Current identity-cache generation; moves on every identity boundary.</summary>
    public long IdentityCacheGeneration => _identityReader.CacheGeneration;

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
            _target = null;
            _isTargetForeground = false;
        }
        _rawQueue.Clear();
        _identityReader.InvalidateAll();
    }

    // ------------------------------------------------------------------ raw sink

    /// <summary>
    /// Called on the WinEvent pump thread. Stamps the monotonic time, appends to the
    /// bounded raw queue, signals the worker, and returns.
    ///
    /// This method deliberately does not take <see cref="_gate"/>. The state machine
    /// spends time inside Win32 and process-identity calls, so sharing its lock would
    /// let a busy worker stall desktop-wide WinEvent delivery. The only lock taken
    /// here is the raw queue's own, which nothing else holds for longer than a queue
    /// operation.
    /// </summary>
    public void OnRawWinEvent(uint eventType, long hwnd, int idObject)
    {
        var observedAtNs = ProtocolClock.NowNs();
        _rawQueue.Enqueue(new RawWinEvent(eventType, hwnd, observedAtNs));
        Signal();
    }

    /// <summary>
    /// Diagnostic seam used by the isolation/stress test: enqueue a synthetic raw
    /// event through exactly the same path the hook callback uses.
    /// </summary>
    public void InjectRawEventForDiagnostics(uint eventType, long hwnd) =>
        OnRawWinEvent(eventType, hwnd, WinEvent.OBJID_WINDOW);

    /// <summary>
    /// The WinEvent the diagnostic injection seam uses. Exposed so a harness can drive
    /// the ingestion path without reaching into the module's internal WinEvent table.
    /// </summary>
    public static uint DiagnosticCreateEventType => WinEvent.EVENT_OBJECT_CREATE;

    /// <summary>
    /// Diagnostic seam used by the isolation/stress test: hold the raw queue lock for
    /// a requested duration, to prove the worker does not need it and cannot deadlock
    /// against it.
    /// </summary>
    public void HoldRawQueueLockForDiagnostics(int milliseconds) =>
        _rawQueue.HoldQueueLockForDiagnostics(milliseconds);

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

            var batch = _rawQueue.Drain();
            var overflowed = _rawQueue.DroppedCount > 0;

            if (overflowed)
            {
                RequestRecoveryScan("event-queue-overflow");
            }

            if (batch.Length == 0)
            {
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
                        LoseTarget(WinEvent.Name(raw.EventType), raw.ObservedAtNs,
                            "target window destroy/hide event");
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
                EvaluateForegroundInline(scanNs);
            }
        }
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

        var identity = ReadIdentityWithDiagnosticDelay(raw.Hwnd);
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

    /// <summary>
    /// Identity work is the slow part of the state machine: it opens the process and
    /// queries its image path. The diagnostic delay hook is applied here so the
    /// isolation test can widen that window to a duration that is unambiguously
    /// measurable, instead of relying on a microsecond-scale race.
    /// </summary>
    private WindowIdentity ReadIdentityWithDiagnosticDelay(long hwnd)
    {
        if (_options.IdentityWorkDelayMsForDiagnostics > 0)
        {
            Thread.Sleep(_options.IdentityWorkDelayMsForDiagnostics);
        }
        return _identityReader.Read(hwnd);
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

        // Identity boundary #1: the pid-&gt;image mapping we cached for this target may
        // no longer describe the process. Drop it before anything can read it again,
        // so a recycled pid cannot answer with the old executable's name.
        _identityReader.InvalidatePid(lost.Pid);

        Emit(WindowMonitorEventKind.StaleHandleRejected, reason, lost.Hwnd, observedAtNs,
            $"rejected handle: {detail}; identityCacheGeneration={_identityReader.CacheGeneration}");

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
            EvaluateForegroundInline(sourceEvent, observedAtNs);
        }
    }

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private void EvaluateForegroundInline(long observedAtNs) => EvaluateForegroundInline(0, observedAtNs);

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private void EvaluateForegroundInline(uint sourceEvent, long observedAtNs)
    {
        var foreground = NativeWindowApiForeground();

        if (_target is null)
        {
            _isTargetForeground = false;
            return;
        }

        // Validate before trusting the handle: an HWND is a recyclable integer, and
        // so is a pid, so the FULL recorded identity is re-checked here.
        var verdict = RevalidateTargetWithDiagnosticDelay(_target);
        if (!verdict.IsSame)
        {
            LoseTarget(sourceEvent == 0 ? "validation" : WinEvent.Name(sourceEvent), observedAtNs,
                verdict.Describe());
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
            $"foreground=0x{foreground:x} target=0x{_target.Hwnd:x} identity={verdict.Describe()}");
    }

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private IdentityVerdict RevalidateTargetWithDiagnosticDelay(WindowIdentity target)
    {
        if (_options.IdentityWorkDelayMsForDiagnostics > 0)
        {
            Thread.Sleep(_options.IdentityWorkDelayMsForDiagnostics);
        }
        return _identityReader.Revalidate(target, _options.RequireVisible);
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
            TargetImageName = _target?.ProcessImageName ?? string.Empty,
            TargetClassName = _target?.ClassName ?? string.Empty,
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

            if (_target is not null)
            {
                var verdict = RevalidateTargetWithDiagnosticDelay(_target);
                if (!verdict.IsSame)
                {
                    LoseTarget("snapshot-validation", ProtocolClock.NowNs(), verdict.Describe());
                }
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
                empty = _rawQueue.Count == 0;
            }
            if (empty)
            {
                // Give the worker one more scheduling slice to finish the batch.
                Thread.Sleep(15);
                lock (_gate)
                {
                    if (_rawQueue.Count == 0)
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
}
