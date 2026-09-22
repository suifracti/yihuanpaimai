using NteHost.WindowMonitor;
using WindowMonitorService = NteHost.WindowMonitor.WindowMonitor;

namespace NteHost.Integration;

/// <summary>
/// Production Integration source backed by the real V2-2A WindowMonitor.
/// WindowMonitor owns the WinEvent hook, raw revision fence, identity validation,
/// and atomic observation cursor; this adapter only translates its public records
/// into the Integration contract.
/// </summary>
public sealed class WindowMonitorObservationSource : IWindowObservationSource, IDisposable
{
    private readonly WindowMonitorService _monitor;
    private bool _disposed;

    public WindowMonitorObservationSource(WindowMonitorService monitor)
    {
        _monitor = monitor ?? throw new ArgumentNullException(nameof(monitor));
    }

    public WindowMonitorService Monitor => _monitor;

    public IntegrationWindowObservation Read()
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(WindowMonitorObservationSource));
        }

        WindowMonitorIntegrationObservation observation = _monitor.ReadIntegrationObservation();
        var events = observation.Events
            .Select(item => new IntegrationWindowEvent(item.RawRevision, item))
            .ToArray();

        return new IntegrationWindowObservation(
            observation.RawRevision,
            observation.RawRevisionBeforeBatch,
            observation.HasPendingEvents,
            observation.DroppedSinceLastRead,
            observation.Snapshot,
            events,
            observation.RawEventRevisions);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _monitor.Dispose();
    }
}
