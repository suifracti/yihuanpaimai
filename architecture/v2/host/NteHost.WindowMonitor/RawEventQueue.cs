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

    public RawEventQueue(int capacity)
    {
        _capacity = Math.Max(1, capacity);
        _queue = new Queue<RawWinEvent>(_capacity);
    }

    public int Capacity => _capacity;

    public long DroppedCount => Interlocked.Read(ref _dropped);

    public long EnqueuedCount => Interlocked.Read(ref _enqueued);

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

    /// <summary>Atomically takes everything currently queued.</summary>
    public RawWinEvent[] Drain()
    {
        lock (_sync)
        {
            if (_queue.Count == 0)
            {
                return Array.Empty<RawWinEvent>();
            }
            var batch = _queue.ToArray();
            _queue.Clear();
            return batch;
        }
    }

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
}

/// <summary>One raw observation from the WinEvent pump thread.</summary>
public readonly record struct RawWinEvent(uint EventType, long Hwnd, long ObservedAtNs)
{
    public static RawWinEvent Synthetic(uint eventType, long hwnd) =>
        new(eventType, hwnd, ProtocolClock.NowNs());
}
