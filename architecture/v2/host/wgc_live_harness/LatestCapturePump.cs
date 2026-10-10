using System.Diagnostics;

namespace WgcLiveHarness;

/// <summary>
/// One owner creates, reads and disposes the capture source. The normal slot
/// contains at most one private frame; Take transfers it, never lends it.
/// An explicit job has a separate result and preempts a normal selection.
/// Neither a replacement nor a job can mutate a frame already taken by MMF
/// publication or SOURCE saving. MMF retains its own exact-ACK ownership.
/// </summary>
internal sealed class LatestCapturePump<TSource, TFrame> : IDisposable
    where TSource : IDisposable where TFrame : class
{
    private readonly object _gate = new();
    private readonly Thread _owner;
    private readonly Func<bool> _externalStop;
    private readonly Action<string> _unconfirmedExit;
    private TFrame? _latest;
    private Job? _job;
    private bool _ready, _stopped;
    private Exception? _failure;
    private long _acquired, _taken, _replaced, _explicitFrames, _lastCaptureTicks, _lastTakeTicks;
    private long _firstReplacedTicks, _lastReplacedTicks;
    private double _maximumTakeGapMs;
    private sealed class Job(Func<TSource, Func<bool>, object?> action)
    {
        public readonly Func<TSource, Func<bool>, object?> Action = action;
        public object? Result;
        public Exception? Error;
        public bool Done;
        public volatile bool Cancelled;
    }

    public LatestCapturePump(Func<TSource> create, Func<TSource, Func<bool>, TFrame> capture,
        Func<bool> externalStop, int intervalMs, Action<string> unconfirmedExit)
    {
        _externalStop = externalStop;
        _unconfirmedExit = unconfirmedExit;
        _owner = new Thread(() =>
        {
            try
            {
                using var source = create();
                lock (_gate) { _ready = true; Monitor.PulseAll(_gate); }
                while (!IsStopped)
                {
                    Job? job;
                    lock (_gate) job = _job;
                    if (job is not null)
                    {
                        try
                        {
                            if (!job.Cancelled && !IsStopped)
                            {
                                job.Result = job.Action(source, () => IsStopped || job.Cancelled);
                                if (job.Result is TFrame) { lock (_gate) _explicitFrames++; }
                            }
                        }
                        catch (Exception ex) { job.Error = ex; }
                        finally
                        {
                            lock (_gate) { job.Done = true; _job = null; Monitor.PulseAll(_gate); }
                        }
                        continue;
                    }
                    try
                    {
                        var frame = capture(source, () => IsStopped || HasJob);
                        lock (_gate)
                        {
                            if (IsStopped) break;
                            _acquired++;
                            if (_latest is not null) { _replaced++; _lastReplacedTicks = Stopwatch.GetTimestamp(); if (_firstReplacedTicks == 0) _firstReplacedTicks = _lastReplacedTicks; }
                            _latest = frame;
                            _lastCaptureTicks = Stopwatch.GetTimestamp();
                            Monitor.PulseAll(_gate);
                            if (_job is null && !IsStopped) Monitor.Wait(_gate, intervalMs);
                        }
                    }
                    catch (CaptureScopeInvalidatedException) { }
                    // Only the ordinary producer throws this typed, age-only
                    // discard. Explicit SOURCE jobs retain their original errors.
                    catch (OrdinaryFrameExpiredException) { }
                    catch (OperationCanceledException) when (IsStopped || HasJob) { }
                }
            }
            catch (Exception ex) { lock (_gate) _failure = ex; }
            finally
            {
                lock (_gate)
                {
                    _stopped = true; _latest = null;
                    if (_job is { } job) { job.Cancelled = true; job.Done = true; _job = null; }
                    Monitor.PulseAll(_gate);
                }
            }
        }) { IsBackground = true, Name = "native-wgc-owner" };
        _owner.Start();
        WaitUntil(() => _ready, 15000);
    }

    private bool HasJob { get { lock (_gate) return _job is not null; } }
    public bool IsStopped { get { lock (_gate) return _stopped || _externalStop(); } }
    public string? Failure { get { lock (_gate) return _failure?.ToString(); } }
    public Exception? FailureException { get { lock (_gate) return _failure; } }
    public void DiscardLatest() { lock (_gate) { _latest = null; Monitor.PulseAll(_gate); } }
    private void CheckAvailable()
    {
        if (_failure is not null) throw new InvalidOperationException("capture-owner-failed", _failure);
        if (IsStopped) throw new OperationCanceledException("capture-owner-stopped");
    }
    private void WaitUntil(Func<bool> done, int timeoutMs)
    {
        var deadline = Environment.TickCount64 + timeoutMs;
        lock (_gate)
        {
            while (!done())
            {
                CheckAvailable();
                var left = deadline - Environment.TickCount64;
                if (left <= 0) throw new TimeoutException("capture-owner-wait-timeout");
                Monitor.Wait(_gate, (int)Math.Min(50, left));
            }
            CheckAvailable();
        }
    }
    public TFrame Take(int timeoutMs)
    {
        WaitUntil(() => _latest is not null, timeoutMs);
        lock (_gate)
        {
            CheckAvailable();
            var frame = _latest!; _latest = null; _taken++;
            var now = Stopwatch.GetTimestamp();
            if (_lastTakeTicks != 0)
                _maximumTakeGapMs = Math.Max(_maximumTakeGapMs,
                    (now - _lastTakeTicks) * 1000.0 / Stopwatch.Frequency);
            _lastTakeTicks = now;
            return frame;
        }
    }
    public TResult Invoke<TResult>(Func<TSource, Func<bool>, TResult> action, int timeoutMs, bool discardLatest = false)
    {
        var job = new Job((source, stop) => action(source, stop));
        lock (_gate)
        {
            CheckAvailable();
            var queueDeadline = Environment.TickCount64 + timeoutMs;
            while (_job is not null)
            {
                CheckAvailable();
                var left = queueDeadline - Environment.TickCount64;
                if (left <= 0) throw new TimeoutException("capture-job-arbitration-timeout");
                Monitor.Wait(_gate, (int)Math.Min(50, left));
            }
            if (discardLatest && _latest is not null) { _latest = null; _replaced++; }
            _job = job; Monitor.PulseAll(_gate);
        }
        try
        {
            WaitUntil(() => job.Done, timeoutMs);
            if (job.Error is not null) System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(job.Error).Throw();
            return (TResult)job.Result!;
        }
        finally { lock (_gate) { job.Cancelled = true; Monitor.PulseAll(_gate); } }
    }
    public object Statistics()
    {
        lock (_gate) return new { acquiredFrames = _acquired, takenFrames = _taken,
            replacedFrames = _replaced, explicitFrames = _explicitFrames, firstReplacementMonotonicTicks = _firstReplacedTicks, lastReplacementMonotonicTicks = _lastReplacedTicks, pendingFrames = _latest is null ? 0 : 1,
            explicitJobs = _job is null ? 0 : 1, maximumObservationGapMs = _maximumTakeGapMs,
            lastAcquisitionMonotonicTicks = _lastCaptureTicks, stopwatchFrequency = Stopwatch.Frequency,
            stopped = IsStopped, ownerExited = !_owner.IsAlive, failure = _failure?.Message };
    }
    public void Dispose()
    {
        lock (_gate) { _stopped = true; _latest = null; if (_job is { } job) job.Cancelled = true; Monitor.PulseAll(_gate); }
        if (!_owner.Join(1500)) _unconfirmedExit("capture-owner-exit-unconfirmed-after-1500ms");
    }
}
