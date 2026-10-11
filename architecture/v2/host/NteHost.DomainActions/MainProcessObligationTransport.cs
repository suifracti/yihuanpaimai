using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace NteHost.DomainActions;

/// <summary>Correlates Main's durable ACKs with the one Host request waiting on them.</summary>
public sealed class DomainActionAcknowledgementRouter
{
    private readonly ConcurrentDictionary<string, TaskCompletionSource<JsonObject>> pending = new();
    private readonly TimeSpan timeout;
    public DomainActionAcknowledgementRouter(TimeSpan? timeout = null) =>
        this.timeout = timeout ?? TimeSpan.FromSeconds(2);

    public bool Accept(JsonObject message)
    {
        var id = (string?)message["requestId"];
        return !string.IsNullOrWhiteSpace(id) && pending.TryGetValue(id, out var waiter)
            && waiter.TrySetResult((JsonObject)message.DeepClone());
    }

    public JsonObject? Exchange(JsonObject request, Action<JsonObject> emit)
    {
        var id = (string?)request["requestId"];
        if (string.IsNullOrWhiteSpace(id)) return null;
        var waiter = new TaskCompletionSource<JsonObject>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!pending.TryAdd(id, waiter)) return null;
        try
        {
            emit((JsonObject)request.DeepClone());
            return waiter.Task.Wait(timeout) ? waiter.Task.Result : null;
        }
        catch { return null; }
        finally { pending.TryRemove(id, out _); }
    }
}

/// <summary>
/// A bid-only Host port. The Main process owns the sole durable ledger and
/// must ACK the exact intent/revision before this port permits the first input.
/// </summary>
public sealed class MainProcessExecutionObligationPort : IExecutionObligationPort
{
    private readonly DomainActionAcknowledgementRouter router;
    private readonly Action<JsonObject> emit;
    private readonly string bootId, ledgerId, observationSessionId;
    private readonly string intentId;
    private readonly DomainIntent boundIntent;
    private readonly object gate = new();
    private long ledgerRevision;
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Converters = { new JsonStringEnumConverter() },
    };

    public MainProcessExecutionObligationPort(DomainActionAcknowledgementRouter router,
        Action<JsonObject> emit, string bootId, string ledgerId, long ledgerRevision,
        string observationSessionId, DomainIntent boundIntent)
    {
        this.router = router; this.emit = emit; this.bootId = bootId;
        this.ledgerId = ledgerId; this.ledgerRevision = ledgerRevision;
        this.observationSessionId = observationSessionId; this.boundIntent = boundIntent;
        this.intentId = boundIntent.IntentId;
        if (string.IsNullOrWhiteSpace(bootId) || string.IsNullOrWhiteSpace(ledgerId)
            || string.IsNullOrWhiteSpace(observationSessionId) || string.IsNullOrWhiteSpace(intentId)
            || ledgerRevision < 0) throw new ArgumentException("OBLIGATION_IDENTITY_REQUIRED");
    }

    public bool CommitBeforeInput(DomainIntent intent)
    {
        if (intent.Kind != DomainActionKind.Bid || !Matches(intent)) return false;
        lock (gate)
        {
            var request = Envelope("domain.action.obligation.request", intent.IntentId);
            request["requestKind"] = "attempted";
            request["intent"] = JsonSerializer.SerializeToNode(boundIntent, Json);
            return Exchange(request);
        }
    }

    public bool CommitReceipt(DomainReceipt receipt)
    {
        // ReturnLobby and StartNextMatch belong to the session FSM, never Sol-B's bid book.
        if (receipt.Kind != DomainActionKind.Bid) return true;
        if (receipt.IntentId != intentId || receipt.ObservationSessionId != observationSessionId
            || string.IsNullOrWhiteSpace(receipt.ApprovalId)) return false;
        lock (gate)
        {
            var request = Envelope("domain.action.receipt.commit.request", receipt.IntentId);
            request["intent"] = JsonSerializer.SerializeToNode(boundIntent, Json);
            request["receipt"] = JsonSerializer.SerializeToNode(receipt, Json);
            request["independentlyQualified"] = receipt.Status switch
            {
                ReceiptStatus.CONFIRMED => !string.IsNullOrWhiteSpace(receipt.EvidenceRef),
                ReceiptStatus.NOT_SENT => receipt.SentNs == 0,
                _ => false,
            };
            return Exchange(request);
        }
    }

    private JsonObject Envelope(string type, string id) => new()
    {
        ["type"] = type,
        ["protocolVersion"] = 1,
        ["requestId"] = Guid.NewGuid().ToString("N"),
        ["bootId"] = bootId,
        ["ledgerId"] = ledgerId,
        ["ledgerRevision"] = ledgerRevision,
        ["observationSessionId"] = observationSessionId,
        ["intentId"] = id,
    };

    private bool Exchange(JsonObject request)
    {
        var expectedRevision = ledgerRevision;
        var ack = router.Exchange(request, emit);
        var accepted = ack is not null
            && (string?)ack["requestId"] == (string?)request["requestId"]
            && (string?)ack["bootId"] == bootId
            && (string?)ack["ledgerId"] == ledgerId
            && (string?)ack["intentId"] == intentId
            && (bool?)ack["accepted"] == true
            && (long?)ack["ledgerRevision"] == expectedRevision + 1;
        if (accepted) ledgerRevision = expectedRevision + 1;
        return accepted;
    }

    private bool Matches(DomainIntent intent) => intent.IntentId == intentId
        && intent.ObservationSessionId == observationSessionId
        && intent.Kind == DomainActionKind.Bid
        && intent.MatchId.Length > 0 && intent.ApprovalId.Length > 0 && intent == boundIntent;
}
