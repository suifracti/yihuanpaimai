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
    private readonly List<long> _rawRevisionsSinceIntegrationRead = new();
    private long _integrationEventSequence;
    private long _integrationRawRevision;
    private long _integrationDroppedSinceRead;
    private long _lastProcessedRawRevision;

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
    private int _workerBusy;

    /// <summary>Number of overflow-drop observations that actually emitted evidence.</summary>
    private long _overflowObservations;

    /// <summary>
    /// Diagnostic seam: while non-zero, raw ingestion is suppressed at the queue so a
    /// test can drive a genuinely quiet window after an overflow. Without a way to
    /// stop the input, "recovery must not keep firing" cannot be distinguished from
    /// "recovery fired because input kept arriving".
    /// </summary>
    private volatile bool _rawIngestionSuppressedForDiagnostics;
    private int _rawIngestionInFlight;

    /// <summary>
    /// Diagnostic seam for the lock-isolation test. When the test wants to prove the
    /// callback does not wait on the STATE lock, it needs the state lock to be held by
    /// something it controls, deterministically, rather than inferring it from "a slow
    /// identity evaluation is probably running right now". This handle is null until
    /// the test asks for the lock, and the test releases it explicitly.
    /// </summary>
    private volatile bool _stateGateHeldForDiagnostics;
    private readonly ManualResetEventSlim _stateGateAcquired = new(false);
    private readonly ManualResetEventSlim _stateGateReleaseRequested = new(false);

    /// <summary>
    /// Diagnostic seams for a deterministic raw-lock direction-B check. The holder
    /// thread confirms that the queue lock is acquired before the independent
    /// producer starts; the release signal is handled separately so the producer may
    /// wait on the real queue lock instead of being falsely sequenced after a
    /// synchronous hold command.
    /// </summary>
    private readonly ManualResetEventSlim _rawQueueLockAcquired = new(false);
    private readonly ManualResetEventSlim _rawQueueLockReleaseRequested = new(false);
    private Thread? _rawQueueLockHolder;
    private readonly ManualResetEventSlim _rawProducerStarted = new(false);
    private readonly ManualResetEventSlim _rawProducerCompleted = new(false);
    private Thread? _rawProducer;

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

    /// <summary>
    /// How many times the worker observed a NEW overflow drop and therefore emitted
    /// `EventQueueOverflow`. Distinct from <see cref="DroppedEventCount"/> (cumulative
    /// records dropped): this counts the recovery decisions, which is what must not
    /// latch.
    /// </summary>
    public long OverflowObservationCount => Interlocked.Read(ref _overflowObservations);

    public long ProcessedEventCount => Interlocked.Read(ref _processedEvents);

    /// <summary>
    /// Diagnostic-only cumulative count of records accepted by the raw queue.
    /// This is intentionally distinct from <see cref="ProcessedEventCount"/>:
    /// the latter is incremented by the worker after a drain and is not an
    /// enqueue counter.
    /// </summary>
    public long RawEnqueuedEventCountForDiagnostics => _rawQueue.EnqueuedCount;

    public int RawQueueCount => _rawQueue.Count;

    /// <summary>
    /// Diagnostic-only non-blocking queue count. Returns <c>null</c> while the raw
    /// queue lock is intentionally held by a test seam.
    /// </summary>
    public int? TryRawQueueCountForDiagnostics =>
        _rawQueue.TryGetCount(out var count) ? count : null;

    /// <summary>
    /// Diagnostic-only worker activity indicator. A drained batch is counted before
    /// its state-machine work runs, so queue emptiness alone is not an idle proof.
    /// </summary>
    public bool IsWorkerBusyForDiagnostics => Volatile.Read(ref _workerBusy) != 0;

    /// <summary>Diagnostic-only count of callbacks currently inside raw ingestion.</summary>
    public int RawIngestionInFlightForDiagnostics => Volatile.Read(ref _rawIngestionInFlight);

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

        ReleaseRawQueueLockForDiagnostics();
        _rawProducer?.Join(3000);

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
        Interlocked.Increment(ref _rawIngestionInFlight);
        try
        {
            // Diagnostic seam: a deliberately quiet period, used by the
            // overflow-regression test to prove that recovery stops once the input
            // stops. Suppression happens HERE rather than at the queue so the callback
            // path itself is unchanged.
            if (_rawIngestionSuppressedForDiagnostics)
            {
                return;
            }

            var observedAtNs = ProtocolClock.NowNs();
            _rawQueue.Enqueue(new RawWinEvent(eventType, hwnd, observedAtNs));
            Signal();
        }
        finally
        {
            Interlocked.Decrement(ref _rawIngestionInFlight);
        }
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

    /// <summary>
    /// Starts a raw-lock hold on a separate thread and returns only after that thread
    /// has confirmed acquisition. A companion release command must end the hold.
    /// </summary>
    public void BeginRawQueueLockHoldForDiagnostics(int milliseconds)
    {
        if (_rawQueueLockHolder?.IsAlive == true)
        {
            throw new InvalidOperationException("a diagnostic raw queue lock hold is already active");
        }

        _rawQueueLockAcquired.Reset();
        _rawQueueLockReleaseRequested.Reset();
        _rawQueueLockHolder = new Thread(() =>
            _rawQueue.HoldQueueLockForDiagnostics(
                milliseconds, _rawQueueLockAcquired, _rawQueueLockReleaseRequested))
        {
            IsBackground = true,
            Name = "raw-queue-lock-hold",
        };
        _rawQueueLockHolder.Start();
    }

    public bool WaitForRawQueueLockAcquiredForDiagnostics(int timeoutMs) =>
        _rawQueueLockAcquired.Wait(timeoutMs);

    public void ReleaseRawQueueLockForDiagnostics()
    {
        _rawQueueLockReleaseRequested.Set();
        _rawQueueLockHolder?.Join(5000);
        _rawQueueLockHolder = null;
    }

    /// <summary>
    /// Starts an independent producer. If the raw lock is held, this thread blocks
    /// inside the real queue enqueue until the explicit release signal is handled.
    /// </summary>
    public void StartRawProducerForDiagnostics(int count)
    {
        if (_rawProducer?.IsAlive == true)
        {
            throw new InvalidOperationException("a diagnostic raw producer is already active");
        }

        _rawProducerStarted.Reset();
        _rawProducerCompleted.Reset();
        _rawProducer = new Thread(() =>
        {
            _rawProducerStarted.Set();
            for (var i = 0; i < count; i++)
            {
                EnqueueRawEventBypassingSuppressionForDiagnostics(DiagnosticCreateEventType, 0);
            }
            _rawProducerCompleted.Set();
        })
        {
            IsBackground = true,
            Name = "raw-event-producer",
        };
        _rawProducer.Start();
    }

    public bool WaitForRawProducerStartedForDiagnostics(int timeoutMs) =>
        _rawProducerStarted.Wait(timeoutMs);

    public bool WaitForRawProducerCompletedForDiagnostics(int timeoutMs) =>
        _rawProducerCompleted.Wait(timeoutMs);

    public bool IsRawProducerCompletedForDiagnostics => _rawProducerCompleted.IsSet;

    /// <summary>
    /// Diagnostic seam: start/stop suppressing raw ingestion, to create a genuinely
    /// quiet observation window.
    /// </summary>
    public void SetRawIngestionSuppressedForDiagnostics(bool suppressed) =>
        _rawIngestionSuppressedForDiagnostics = suppressed;

    /// <summary>
    /// Diagnostic seam: enqueue through the RAW QUEUE directly, bypassing the
    /// ingestion-suppression flag. Used to (a) fill the queue to capacity while a
    /// hold is in progress and (b) confirm ingestion resumes after a release, without
    /// depending on the suppress toggle.
    /// </summary>
    public void EnqueueRawEventBypassingSuppressionForDiagnostics(uint eventType, long hwnd)
    {
        var observedAtNs = ProtocolClock.NowNs();
        _rawQueue.Enqueue(new RawWinEvent(eventType, hwnd, observedAtNs));
        Signal();
    }

    /// <summary>
    /// Diagnostic seam: hold the STATE lock for a requested duration and report when
    /// it was actually taken.
    ///
    /// This exists so the isolation test can prove direction A deterministically: the
    /// state lock is verifiably held by the test's own call, so an ingestion performed
    /// meanwhile cannot be excused as "the worker happened not to be busy". Inferring
    /// the hold from a slow identity evaluation leaves the test unable to distinguish
    /// "the callback is not serialised" from "the state path was idle at that instant".
    /// </summary>
    public void HoldStateGateForDiagnostics(int milliseconds)
    {
        _stateGateAcquired.Reset();
        _stateGateReleaseRequested.Reset();
        _stateGateHeldForDiagnostics = true;
        var releaser = new Thread(() =>
        {
            lock (_gate)
            {
                _stateGateAcquired.Set();
                _stateGateReleaseRequested.Wait(milliseconds + 30_000);
            }
            _stateGateHeldForDiagnostics = false;
        })
        {
            IsBackground = true,
            Name = "state-gate-hold",
        };
        releaser.Start();
    }

    /// <summary>Blocks until <see cref="HoldStateGateForDiagnostics"/> has taken the lock.</summary>
    public bool WaitForStateGateAcquiredForDiagnostics(int timeoutMs) =>
        _stateGateAcquired.Wait(timeoutMs);

    /// <summary>Releases a hold taken by <see cref="HoldStateGateForDiagnostics"/>.</summary>
    public void ReleaseStateGateForDiagnostics() => _stateGateReleaseRequested.Set();

    public bool IsStateGateHeldForDiagnostics => _stateGateHeldForDiagnostics;

    /// <summary>
    /// Diagnostic seam: push N events straight into the bounded queue, bypassing
    /// suppression, to overflow a small-capacity queue deterministically.
    /// </summary>
    public void OverflowQueueForDiagnostics(int count)
    {
        for (var i = 0; i < count; i++)
        {
            EnqueueRawEventBypassingSuppressionForDiagnostics(DiagnosticCreateEventType, 0);
        }
    }

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

            Interlocked.Exchange(ref _workerBusy, 1);
            try
            {
                var drained = _rawQueue.DrainWithDelta();
                var batch = drained.Events;

                if (drained.DroppedSinceLastDrain > 0)
                {
                    lock (_gate)
                    {
                        _integrationDroppedSinceRead += drained.DroppedSinceLastDrain;
                    }
                }

                // React to a drop that just happened, NOT to the cumulative total. The
                // total never decreases, so `DroppedCount > 0` would latch the monitor
                // into requesting recovery on every loop iteration forever after the very
                // first overflow.
                if (drained.OverflowedSinceLastDrain)
                {
                    Interlocked.Increment(ref _overflowObservations);
                    Emit(WindowMonitorEventKind.EventQueueOverflow, "event-queue-overflow", 0,
                        ProtocolClock.NowNs(),
                        $"droppedSinceLastDrain={drained.DroppedSinceLastDrain} " +
                        $"totalDropped={_rawQueue.DroppedCount} capacity={_rawQueue.Capacity}",
                        rawRevision: drained.RawRevisionAfterDrain);
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
            finally
            {
                Interlocked.Exchange(ref _workerBusy, 0);
            }
        }
    }

    private void ProcessBatch(RawWinEvent[] batch)
    {
        foreach (var raw in batch)
        {
            lock (_gate)
            {
                if (raw.Revision > 0)
                {
                    _rawRevisionsSinceIntegrationRead.Add(raw.Revision);
                    _lastProcessedRawRevision = Math.Max(_lastProcessedRawRevision, raw.Revision);
                }

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
                            "target window destroy/hide event", raw.Revision);
                    }
                }
            }

            // Foreground is authoritative from the OS, not from the event payload.
            EvaluateForeground(raw.EventType, raw.ObservedAtNs, raw.Revision);
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

        Adopt(identity, $"promoted-from-{WinEvent.Name(raw.EventType)}", raw.ObservedAtNs, raw.Revision);
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
    private void Adopt(WindowIdentity identity, string reason, long observedAtNs, long rawRevision = 0)
    {
        var reacquire = _generation > 0;
        _target = identity;
        _generation++;

        Emit(reacquire ? WindowMonitorEventKind.TargetReacquired : WindowMonitorEventKind.TargetAcquired,
            reason, identity.Hwnd, observedAtNs,
            $"identity: {identity.Describe()}", rawRevision);

        // A brand new target has an unknown foreground relationship; evaluate it
        // immediately so the snapshot is never stale after acquisition.
        _isTargetForeground = false;
    }

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private void LoseTarget(string reason, long observedAtNs, string detail, long rawRevision = 0)
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
            $"rejected handle: {detail}; identityCacheGeneration={_identityReader.CacheGeneration}",
            rawRevision);

        _target = null;
        _isTargetForeground = false;
        _needsRecoveryScan = true;
        _pendingRecoveryReason = "target-lost";

        Emit(WindowMonitorEventKind.TargetLost, reason, lost.Hwnd, observedAtNs,
            $"lost identity: {lost.Describe()}", rawRevision);
    }

    private void EvaluateForeground(uint sourceEvent, long observedAtNs, long rawRevision = 0)
    {
        lock (_gate)
        {
            EvaluateForegroundInline(sourceEvent, observedAtNs, rawRevision);
        }
    }

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private void EvaluateForegroundInline(long observedAtNs) =>
        EvaluateForegroundInline(0, observedAtNs, _lastProcessedRawRevision);

    /// <summary>Caller must hold <see cref="_gate"/>.</summary>
    private void EvaluateForegroundInline(uint sourceEvent, long observedAtNs, long rawRevision = 0)
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
            $"foreground=0x{foreground:x} target=0x{_target.Hwnd:x} identity={verdict.Describe()}",
            rawRevision);
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
    private void Emit(
        WindowMonitorEventKind kind,
        string sourceEvent,
        long hwnd,
        long observedAtNs,
        string reason,
        long rawRevision = 0)
    {
        // Ordering discipline: the event list is a total order (sequence), so the
        // timestamps carried in it must be non-decreasing in that order. `observedAtNs`
        // is normally the raw event's own stamp, which is taken on the pump thread at
        // callback entry - and Windows delivers OUTOFCONTEXT callbacks whose arrival
        // order need not agree with their stamp order. Two independent sources feed one
        // emit stream (the raw event's stamp and the live `NowNs()` used by the
        // snapshot/recovery paths), so without this clamp a derived event could be
        // appended carrying an earlier stamp than the event before it and the stream
        // would read as if time went backwards.
        //
        // Clamping is the honest resolution rather than re-stamping: it preserves the
        // observation time where it is already ordered, and only raises a stamp that
        // would otherwise violate the invariant the module documents.
        var lastObservedAtNs = _events.Count > 0 ? _events[^1].ObservedAtNs : 0;
        var orderedObservedAtNs = observedAtNs < lastObservedAtNs ? lastObservedAtNs : observedAtNs;

        _sequence++;
        _events.Add(new WindowMonitorEvent
        {
            Sequence = _sequence,
            RawRevision = rawRevision,
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
            ObservedAtNs = orderedObservedAtNs,
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

    /// <summary>
    /// Captures the production observation boundary consumed by Integration.
    ///
    /// The read is intentionally a fence, not a best-effort combination of
    /// <see cref="Snapshot"/> and <see cref="Events"/>. A concurrent raw callback,
    /// worker drain, or still-pending queue makes this read pending; the caller must
    /// fail closed and retry after the source settles. A pending read does not retire
    /// the integration cursor, so the next stable read still contains every raw
    /// revision and derived transition since the last stable fence.
    /// </summary>
    public WindowMonitorIntegrationObservation ReadIntegrationObservation()
    {
        lock (_gate)
        {
            // Keep the last stable cursor as the LEFT endpoint of this read. The
            // endpoint must be captured before committing the current fence; using
            // the updated cursor here makes a complete batch [1,2,3] look like a
            // gap from 3 -> 3 to the Integration adapter.
            var rawRevisionBeforeBatch = _integrationRawRevision;
            var rawAtStart = _rawQueue.Revision;
            var snapshot = Snapshot();
            var rawAfterSnapshot = _rawQueue.Revision;

            var events = _events
                .Where(item => item.Sequence > _integrationEventSequence)
                .ToArray();
            var rawRevisions = _rawRevisionsSinceIntegrationRead.ToArray();
            var dropped = _integrationDroppedSinceRead;

            var pending = rawAfterSnapshot != rawAtStart
                || _rawQueue.Count > 0
                || IsWorkerBusyForDiagnostics
                || rawAfterSnapshot > _lastProcessedRawRevision;

            var rawAtEnd = _rawQueue.Revision;
            if (rawAtEnd != rawAfterSnapshot)
            {
                pending = true;
            }

            if (!pending)
            {
                _integrationRawRevision = rawAtEnd;
                if (_events.Count > 0)
                {
                    _integrationEventSequence = _events[^1].Sequence;
                }
                _rawRevisionsSinceIntegrationRead.Clear();
                _integrationDroppedSinceRead = 0;
            }

            return new WindowMonitorIntegrationObservation(
                rawRevisionBeforeBatch,
                rawAtEnd,
                pending,
                dropped,
                snapshot,
                events,
                rawRevisions);
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
            if (empty && !IsWorkerBusyForDiagnostics)
            {
                // Give the worker one more scheduling slice to finish the batch.
                Thread.Sleep(15);
                lock (_gate)
                {
                    if (_rawQueue.Count == 0 && !IsWorkerBusyForDiagnostics)
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
