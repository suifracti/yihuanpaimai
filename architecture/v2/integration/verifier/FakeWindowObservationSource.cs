using NteHost.Integration;
using NteHost.WindowMonitor;

namespace NteIntegrationVerifier;

/// <summary>
/// Deterministic stand-in for the A observation boundary. It emits accepted A
/// snapshot/event records plus an explicit raw revision; it never calls Win32.
/// </summary>
internal sealed class FakeWindowObservationSource : IWindowObservationSource
{
    private readonly object _gate = new();
    private readonly List<IntegrationWindowEvent> _events = new();
    private readonly List<long> _rawRevisions = new();
    private WindowMonitorSnapshot _snapshot;
    private long _revision;
    private long _eventSequence;
    private long _dropped;
    private bool _pending;
    private int _readCount;
    private long _lastReadRevision;
    private readonly List<IntegrationWindowObservation> _readLog = new();

    public FakeWindowObservationSource(WindowIdentity identity, long aGeneration = 1)
    {
        _snapshot = Snapshot(identity, identity.Hwnd, aGeneration, true, "fake-initial");
    }

    public Action<int, FakeWindowObservationSource>? AfterRead { get; set; }

    public int ReadCount
    {
        get { lock (_gate) return _readCount; }
    }

    public WindowMonitorSnapshot CurrentSnapshot
    {
        get { lock (_gate) return _snapshot; }
    }

    public IReadOnlyList<IntegrationWindowObservation> ReadLog
    {
        get { lock (_gate) return _readLog.ToArray(); }
    }

    public IntegrationWindowObservation Read()
    {
        IntegrationWindowObservation result;
        int count;
        lock (_gate)
        {
            count = ++_readCount;
            long before = _lastReadRevision;
            result = new IntegrationWindowObservation(
                _revision,
                before,
                _pending,
                _dropped,
                _snapshot,
                _events.ToArray(),
                _rawRevisions.ToArray());
            _readLog.Add(result);
            _lastReadRevision = _revision;
            _events.Clear();
            _rawRevisions.Clear();
            _pending = false;
            _dropped = 0;
        }

        AfterRead?.Invoke(count, this);
        return result;
    }

    public void SetForeground(bool isForeground, string reason = "fake-focus")
    {
        lock (_gate)
        {
            uint eventType = isForeground ? 0x0003u : 0x0004u;
            _revision++;
            _rawRevisions.Add(_revision);
            _eventSequence++;
            _events.Add(new IntegrationWindowEvent(
                _revision,
                Event(WindowMonitorEventKind.ForegroundGained, eventType, reason)));
            if (!isForeground)
            {
                _events[^1] = new IntegrationWindowEvent(
                    _revision,
                    Event(WindowMonitorEventKind.ForegroundLost, eventType, reason));
            }

            _snapshot = _snapshot with
            {
                ForegroundHwnd = isForeground ? _snapshot.TargetHwnd : 0,
                IsTargetForeground = isForeground,
                ObservedAtNs = NteHost.Input.TraceClock.NowNs(),
                Reason = reason,
            };
        }
    }

    public void RebuildSameHwnd(int newPid, long newProcessInstanceToken, long aGeneration)
    {
        lock (_gate)
        {
            WindowIdentity old = _snapshot.TargetIdentity ?? WindowIdentity.None;
            _revision++;
            _rawRevisions.Add(_revision);
            _eventSequence++;
            _events.Add(new IntegrationWindowEvent(
                _revision,
                Event(WindowMonitorEventKind.TargetLost, 0x0002u, "identity-rebuild-old")));

            var replacement = old with
            {
                Pid = newPid,
                ProcessInstanceToken = newProcessInstanceToken,
                Title = old.Title + "-recreated",
            };

            _revision++;
            _rawRevisions.Add(_revision);
            _eventSequence++;
            _events.Add(new IntegrationWindowEvent(
                _revision,
                Event(WindowMonitorEventKind.TargetReacquired, 0x0001u, "identity-rebuild-new")));
            _snapshot = Snapshot(replacement, replacement.Hwnd, aGeneration, true, "identity-rebuild");
        }
    }

    public void MarkPending()
    {
        lock (_gate) _pending = true;
    }

    public void MarkOverflow(long dropped)
    {
        lock (_gate)
        {
            long count = Math.Max(1, dropped);
            _revision += count;
            _dropped += count;
        }
    }

    public void MarkRevisionGap()
    {
        lock (_gate) _revision++;
    }

    public void MarkInternalRevisionGap()
    {
        lock (_gate)
        {
            _revision += 2;
            _rawRevisions.Add(_revision);
        }
    }

    private WindowMonitorEvent Event(WindowMonitorEventKind kind, uint source, string reason)
    {
        return new WindowMonitorEvent
        {
            Sequence = _eventSequence,
            Kind = kind,
            SourceEvent = $"fake:{source:x}",
            TargetHwnd = _snapshot.TargetHwnd,
            TargetPid = _snapshot.TargetPid,
            TargetImageName = _snapshot.TargetIdentity?.ProcessImageName ?? string.Empty,
            TargetClassName = _snapshot.TargetIdentity?.ClassName ?? string.Empty,
            ForegroundHwnd = _snapshot.ForegroundHwnd,
            IsTargetAlive = _snapshot.IsTargetAlive,
            IsTargetForeground = _snapshot.IsTargetForeground,
            Generation = _snapshot.Generation,
            ObservedAtNs = NteHost.Input.TraceClock.NowNs(),
            Reason = reason,
        };
    }

    private static WindowMonitorSnapshot Snapshot(
        WindowIdentity identity,
        long foregroundHwnd,
        long aGeneration,
        bool foreground,
        string reason) =>
        new()
        {
            TargetHwnd = identity.Hwnd,
            TargetPid = identity.Pid,
            ForegroundHwnd = foregroundHwnd,
            IsTargetAlive = true,
            IsTargetForeground = foreground,
            Generation = aGeneration,
            ObservedAtNs = NteHost.Input.TraceClock.NowNs(),
            Reason = reason,
            TargetIdentity = identity,
        };

    public static WindowIdentity Identity(
        long hwnd = 0x1001,
        int pid = 100,
        long processInstanceToken = 0xabc1,
        string image = "auction.exe") =>
        new(hwnd, pid, image, "AuctionWindow", "Auction", true, processInstanceToken);
}
