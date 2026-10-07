using System.Collections.Concurrent;
using System.Text.Json.Nodes;

namespace WgcLiveHarness;

// Independent SOURCE service; business SendFrame/OCR never owns this worker.
internal sealed class DeliverySourcePump : IDisposable
{
    private readonly CancellationTokenSource _stop = new();
    private readonly Thread _worker;
    private readonly WarehouseEvidenceLease _lease;
    private readonly Action<string> _unconfirmed;
    public DeliverySourcePump(WarehouseEvidenceLease lease, BlockingCollection<JsonObject> queue,
        Action drain, Func<(long Gate, long Deadline, long Match, string Token), Func<bool>, WarehouseSourceFrame> capture,
        Func<bool> revalidate, Action<Exception> failure, Action<string> unconfirmed)
    {
        _lease = lease; _unconfirmed = unconfirmed;
        _worker = new Thread(() =>
        {
            while (!_stop.IsCancellationRequested)
            {
                (long Gate, long Deadline, long Match, string Token)? attempted = null;
                try
                {
                    drain(); lease.Tick();
                    if (lease.RequestSnapshot() is { } request)
                    {
                        attempted = request;
                        bool Cancelled() => _stop.IsCancellationRequested || !lease.RequestCurrent(request.Gate, request.Match, request.Token);
                        var frame = capture(request, Cancelled);
                        if (!Cancelled() && !lease.TryPublish(frame, revalidate)
                            && lease.RequestCurrent(request.Gate, request.Match, request.Token))
                            lease.Close("SOURCE_EXPLICIT_FRAME_NOT_ADMITTED");
                    }
                    else _stop.Token.WaitHandle.WaitOne(25);
                }
                catch (OperationCanceledException)
                {
                    if (!_stop.IsCancellationRequested && attempted is { } cancelledRequest
                        && lease.RequestCurrent(cancelledRequest.Gate, cancelledRequest.Match, cancelledRequest.Token))
                        lease.Close("SOURCE_REQUEST_CANCELLED");
                }
                catch (Exception ex)
                {
                    if (attempted is null || (attempted is { } failedRequest
                        && lease.RequestCurrent(failedRequest.Gate, failedRequest.Match, failedRequest.Token)))
                        lease.Close("SOURCE_ACQUISITION_FAILED:" + ex.Message);
                    failure(ex);
                }
            }
        }) { IsBackground = true, Name = "native-source-v2" };
        _worker.Start();
    }
    public void Dispose()
    {
        _lease.SignalStop(); _stop.Cancel();
        if (!_worker.Join(1500)) _unconfirmed("source-worker-exit-unconfirmed-after-1500ms");
    }
}
