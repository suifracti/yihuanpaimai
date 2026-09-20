using NteHost.Protocol;

namespace NteHost.WindowMonitor;

/// <summary>
/// The bounded raw WinEvent queue that sits between the hook callback and the
/// worker.
///
/// It is deliberately its OWN object with its OWN lock, and it is not touched by
/// the state machine. That separation is the whole point: the WinEvent callback
/// runs on a thread that must never stall (a slow callback delays event delivery
/// for the entire desktop), while the state machine legitimately performs Win32
/// and process-identity work that can be slow. If the two shared a lock, the
/// callback would inherit the state machine's latency and could not honour its
/// contract.
///
/// Failure mode on overflow: drop the OLDEST record and count the drop. Dropping
/// the oldest keeps the freshest observations, and the drop counter lets the
/// worker trigger a recovery enumeration, so nothing is silently lost.
/// </summary>
public sealed class RawEventQueue
{
    private readonly object _sync = new();
    private readonly Queue<RawWinEvent> _queue;

    private readonly int _capacity;
    private long _dropped;
    private long _enqueued;
    private long _droppedSinceLastDrain;
    private long _droppedAcknowledged;

    public RawEventQueue(int capacity)
    {
        _capacity = Math.Max(1, capacity);
        _queue = new Queue<RawWinEvent>(_capacity);
    }

    public int Capacity => _capacity;

    public long DroppedCount => Interlocked.Read(ref _dropped);

    public long EnqueuedCount => Interlocked.Read(ref _enqueued);

    /// <summary>
    /// Diagnostic seam: the number of records dropped during the most recent
    /// <see cref="DrainWithDelta"/>.
    ///
    /// The worker must react to a drop that has JUST happened, not to the fact that
    /// a drop ever happened. <see cref="DroppedCount"/> is cumulative and never
    /// decreases, so testing <c>DroppedCount &gt; 0</c> would latch "overflowing"
    /// permanently after the very first drop and keep requesting recovery forever.
    /// </summary>
    public long DroppedSinceLastDrain => Interlocked.Read(ref _droppedSinceLastDrain);

    /// <summary>
    /// Appends one raw event. Bounded work only: no Win32 call, no allocation beyond
    /// the ring slot, no dependency on any other lock in the module.
    /// </summary>
    public void Enqueue(in RawWinEvent raw)
    {
        lock (_sync)
        {
            while (_queue.Count >= _capacity)
            {
                _queue.Dequeue();
                _dropped++;
            }
            _queue.Enqueue(raw);
            _enqueued++;
        }
    }

    /// <summary>
    /// Atomically takes everything currently queued, and reports how many records
    /// were dropped since the previous call.
    ///
    /// The delta is the important half. <see cref="DroppedCount"/> is cumulative, so
    /// a worker that asks "has anything ever been dropped?" answers yes forever after
    /// the first overflow and would keep triggering recovery on every subsequent
    /// loop iteration. Recovery must respond to a NEW drop only.
    /// </summary>
    public RawEventBatch DrainWithDelta()
    {
        lock (_sync)
        {
            var events = _queue.ToArray();
            _queue.Clear();

            var droppedSinceLastDrain = _dropped - _droppedAcknowledged;
            _droppedAcknowledged = _dropped;
            Interlocked.Exchange(ref _droppedSinceLastDrain, droppedSinceLastDrain);
            return new RawEventBatch(events, droppedSinceLastDrain);
        }
    }

    /// <summary>Atomically takes everything currently queued (delta discarded).</summary>
    public RawWinEvent[] Drain() => DrainWithDelta().Events;

    public int Count
    {
        get
        {
            lock (_sync)
            {
                return _queue.Count;
            }
        }
    }

    public void Clear()
    {
        lock (_sync)
        {
            _queue.Clear();
        }
    }

    /// <summary>
    /// Test/diagnostic seam: holds <see cref="_sync"/> for a requested duration so a
    /// harness can prove that the callback never waits on this lock for the state
    /// machine, and vice versa.
    /// </summary>
    public void HoldQueueLockForDiagnostics(int milliseconds)
    {
        lock (_sync)
        {
            Thread.Sleep(milliseconds);
        }
    }

    /// <summary>
    /// Diagnostic-only non-blocking count probe. A lock-holder test must be able to
    /// keep its command loop responsive while another thread owns <see cref="_sync"/>.
    /// </summary>
    public bool TryGetCount(out int count)
    {
        if (!Monitor.TryEnter(_sync))
        {
            count = 0;
            return false;
        }

        try
        {
            count = _queue.Count;
            return true;
        }
        finally
        {
            Monitor.Exit(_sync);
        }
    }

    /// <summary>
    /// Diagnostic seam variant that confirms acquisition while the queue lock is
    /// still held, then waits for an explicit release signal. The holder and the
    /// producer are intentionally separate threads so a producer may block on the
    /// real queue lock until the test releases it.
    /// </summary>
    public void HoldQueueLockForDiagnostics(
        int milliseconds,
        ManualResetEventSlim acquired,
        ManualResetEventSlim releaseRequested)
    {
        lock (_sync)
        {
            acquired.Set();
            releaseRequested.Wait(milliseconds + 30_000);
        }
    }
}

/// <summary>One raw observation from the WinEvent pump thread.</summary>
public readonly record struct RawWinEvent(uint EventType, long Hwnd, long ObservedAtNs)
{
    public static RawWinEvent Synthetic(uint eventType, long hwnd) =>
        new(eventType, hwnd, ProtocolClock.NowNs());
}

/// <summary>
/// One drain result: the events taken, plus how many records overflow-dropped since
/// the previous drain. The drop count is a DELTA, not a running total, so a consumer
/// can distinguish "a drop just happened" from "a drop happened at some point in the
/// past".
/// </summary>
public readonly record struct RawEventBatch(RawWinEvent[] Events, long DroppedSinceLastDrain)
{
    public bool OverflowedSinceLastDrain => DroppedSinceLastDrain > 0;

    public int Length => Events.Length;

    public bool IsEmpty => Events.Length == 0;
}
