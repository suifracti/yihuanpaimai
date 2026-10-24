namespace NteHost.DomainActions;

public enum DomainActionKind { Bid, ReturnLobby, StartNextMatch, OpenInstrument, SelectGoldAverage, UseGoldAverage, OpenBidPanel,
    OpenToolSetup, RequestToolRefill, ConfirmToolRefill, CloseToolSetup, BrowseToolGroups, SelectToolGroup, ConfirmEntryFee,
    SelectPurpleCount, UsePurpleCount, CancelKnownPopup, SellNonRed }
public static class AuctionPreparation
{
    public static string? ExpectedScene(DomainActionKind kind) => kind switch
    {
        DomainActionKind.OpenInstrument or DomainActionKind.OpenBidPanel => "AUCTION_READY",
        DomainActionKind.SelectGoldAverage => "INSTRUMENT_LIST",
        DomainActionKind.UseGoldAverage => "INSTRUMENT_GOLD_SELECTED",
        DomainActionKind.SelectPurpleCount => "INSTRUMENT_LIST",
        DomainActionKind.UsePurpleCount => "INSTRUMENT_PURPLE_SELECTED",
        DomainActionKind.OpenToolSetup => "LOBBY",
        DomainActionKind.RequestToolRefill or DomainActionKind.CloseToolSetup => "TOOL_SETUP",
        DomainActionKind.ConfirmToolRefill => "TOOL_REFILL_CONFIRM",
        DomainActionKind.ConfirmEntryFee => "ENTRY_FEE",
        DomainActionKind.CancelKnownPopup => "KNOWN_POPUP",
        DomainActionKind.BrowseToolGroups or DomainActionKind.SelectToolGroup => "TOOL_GROUPS",
        _ => null,
    };
    public static bool IsKnownPopup(string? scene) => scene is "TOOL_REFILL_CONFIRM" or "ENTRY_FEE" or "TOOL_SETUP" or "TOOL_GROUPS";
    public static bool IsPreparation(DomainActionKind kind) => ExpectedScene(kind) is not null;
    public static bool IsLobby(DomainActionKind kind) => kind is DomainActionKind.OpenToolSetup
        or DomainActionKind.RequestToolRefill or DomainActionKind.ConfirmToolRefill or DomainActionKind.CloseToolSetup
        or DomainActionKind.BrowseToolGroups or DomainActionKind.SelectToolGroup
        or DomainActionKind.StartNextMatch or DomainActionKind.ConfirmEntryFee or DomainActionKind.CancelKnownPopup;
    public static bool Confirms(DomainActionKind kind, string scene, bool effectVisible = false) => kind switch
    {
        DomainActionKind.OpenInstrument => scene is "INSTRUMENT_LIST" or "INSTRUMENT_GOLD_SELECTED" or "INSTRUMENT_PURPLE_SELECTED",
        DomainActionKind.SelectGoldAverage => scene == "INSTRUMENT_GOLD_SELECTED",
        DomainActionKind.UseGoldAverage => scene == "AUCTION_READY" && effectVisible,
        DomainActionKind.SelectPurpleCount => scene == "INSTRUMENT_PURPLE_SELECTED",
        DomainActionKind.UsePurpleCount => scene == "AUCTION_READY" && effectVisible,
        DomainActionKind.OpenBidPanel => scene == "AUCTION",
        DomainActionKind.OpenToolSetup => scene is "TOOL_SETUP" or "TOOL_GROUPS",
        DomainActionKind.BrowseToolGroups => scene == "TOOL_GROUPS",
        DomainActionKind.SelectToolGroup => scene == "TOOL_SETUP",
        DomainActionKind.RequestToolRefill => scene == "TOOL_REFILL_CONFIRM",
        DomainActionKind.ConfirmToolRefill => scene is "TOOL_SETUP" or "LOBBY",
        DomainActionKind.CloseToolSetup => scene == "LOBBY",
        DomainActionKind.CancelKnownPopup => scene is "LOBBY" or "TOOL_SETUP" or "TOOL_GROUPS",
        DomainActionKind.ConfirmEntryFee => scene is "LOBBY" or "AUCTION_R1" or "AUCTION_READY" or "AUCTION",
        _ => false,
    };
}
public enum ReceiptStatus { NOT_SENT, SENT_PENDING_CONFIRMATION, CONFIRMED, UNKNOWN }
public sealed record WindowBinding(long Hwnd, int Pid, long ProcessInstanceToken, long FocusEpoch);
public sealed record DomainIntent(string IntentId, DomainActionKind Kind, string MatchId, int Round,
    long FactsRevision, long? Amount, long Budget, long DeadlineNs, long TakeoverGeneration,
    string LeaseId, WindowBinding Window)
{
    public long MatchGeneration { get; init; }
    public string ObservationSessionId { get; init; } = "";
    public long MaxSafeBid { get; init; }
    public string ApprovalId { get; init; } = "";
    public string RecoveryScene { get; init; } = "";
    public int GoldStockBefore { get; init; }
    public int PurpleStockBefore { get; init; }
    public long MinimumFunds { get; init; }
    public long FundsBefore { get; init; }
    public long RoundDeadlineNs { get; init; }
    public bool SettlementAcquired { get; init; }
}

// Produced from the current qualified Native/Engine state, never from the intent itself.
public sealed record ActionScope(string MatchId, int Round, long FactsRevision, long Budget,
    long ApprovedAmountLimit, string Scene, string LeaseId, long LeaseExpiresNs,
    WindowBinding Window, long TakeoverGeneration, long SourceSequence, long CapturedNs,
    bool SourceQualified, bool Connected, bool ForegroundMatches, bool ExecutionAuthorized,
    bool SettlementArchived, bool NewMatchAdmission)
{
    public long MatchGeneration { get; init; }
    public string ObservationSessionId { get; init; } = "";
    public string ApprovalId { get; init; } = "";
}

public sealed record VisibleResult(string IntentId, DomainActionKind Kind, string OriginMatchId,
    int OriginRound, long OriginFactsRevision, long? AcceptedOwnAmount, string? NewMatchId,
    string Scene, long SourceSequence, long CapturedNs, bool SourceQualified,
    WindowBinding Window, long TakeoverGeneration)
{
    public bool PreparationEffectVisible { get; init; }
    public bool SaleConfirmed { get; init; }
    public InstrumentStock? Instruments { get; init; }
    public long OriginMatchGeneration { get; init; }
    public string ObservationSessionId { get; init; } = "";
    public long NewMatchGeneration { get; init; }
    public string? EvidenceRef { get; init; }
}
public sealed record DomainReceipt(string IntentId, DomainActionKind Kind, string MatchId, int Round,
    long FactsRevision, ReceiptStatus Status, string Reason, long? Amount,
    long SentNs = 0, long EvidenceSequence = 0, string? NewMatchId = null)
{
    public long MatchGeneration { get; init; }
    public string ObservationSessionId { get; init; } = "";
    public long NewMatchGeneration { get; init; }
    public string? EvidenceRef { get; init; }
    public bool StopAvailable { get; init; } = true;
    public bool TakeoverAvailable { get; init; } = true;
    public string ApprovalId { get; init; } = "";
}

public sealed record PortOutcome(bool SideEffectAttempted, bool Completed, string Reason)
{
    // Editing an unsubmitted amount is not an attempted bid confirmation.
    public bool? BidConfirmationAttempted { get; init; }
}
public interface IRestrictedDomainInputPort
{
    // A closed domain operation, not coordinates/text/key scripts. Implementations must
    // use existing Native identity + one-shot input ticket checks for EVERY primitive,
    // call current immediately before each side effect (including cursor preparation),
    // and report any attempted side effect even when the backend fails. No retries.
    PortOutcome TrySend(DomainIntent intent, Func<bool> current);
}

/// <summary>Offline-ready policy/receipt owner. No port means execution OFF.</summary>
public sealed class DomainActionCoordinator
{
    private readonly object gate = new();
    private readonly Func<ActionScope?> readScope;
    private readonly Func<long> clock;
    private readonly IRestrictedDomainInputPort? port;
    private readonly Func<bool> yieldRequested;
    private readonly Dictionary<string, (DomainIntent Intent, DomainReceipt Receipt, long Sequence)> receipts = new();
    private readonly HashSet<(string, int, DomainActionKind)> attempted = new();
    private readonly HashSet<string> warningAttempted = new();
    private string? pending;
    private bool stopped;
    private readonly Dictionary<(string,long), int> unknownCounts = new();
    private readonly HashSet<string> unknownIntents = new();
    public DomainReceipt? Receipt(string id) { lock(gate) return receipts.TryGetValue(id,out var e) ? e.Receipt : null; }

    public DomainActionCoordinator(Func<ActionScope?> readScope, Func<long> clock,
        IRestrictedDomainInputPort? port = null, Func<bool>? yieldRequested = null)
    {
        this.readScope = readScope; this.clock = clock; this.port = port;
        this.yieldRequested = yieldRequested ?? (() => false);
    }

    public DomainReceipt Dispatch(DomainIntent intent)
    {
        lock (gate)
        {
            if (receipts.TryGetValue(intent.IntentId, out var prior))
            {
                // IDs are immutable; return the original receipt, never send twice.
                return prior.Intent == intent ? prior.Receipt : prior.Receipt with { Reason = "INTENT_ID_CONFLICT" };
            }
            DomainReceipt NotSent(string reason) => new(intent.IntentId, intent.Kind, intent.MatchId,
                intent.Round, intent.FactsRevision, ReceiptStatus.NOT_SENT, reason, intent.Amount)
                { MatchGeneration = intent.MatchGeneration, ObservationSessionId = intent.ObservationSessionId, ApprovalId = intent.ApprovalId };
            if (stopped) return NotSent("SESSION_STOPPED_UNKNOWN");
            if (pending != null) return NotSent("CONFIRMATION_PENDING");
            if (receipts.Count >= 512) return NotSent("RECEIPT_CAPACITY_STOP");
            if (intent.Kind == DomainActionKind.Bid
                && attempted.Contains((intent.MatchId, intent.Round, intent.Kind))) return NotSent("ACTION_ALREADY_ATTEMPTED");
            var scope = SafeRead();
            string reason = Validate(intent, scope);
            if (reason != "OK") return NotSent(yieldRequested() ? "USER_INPUT_YIELD" : reason);
            if (port == null) return NotSent("EXECUTION_OFF_NO_TICKET_PORT");
            PortOutcome outcome;
            try { outcome = port.TrySend(intent, () => Validate(intent, SafeRead()) == "OK"); }
            catch { outcome = new(true, false, "PORT_EXCEPTION_DELIVERY_UNKNOWN"); }
            bool attemptedCommit = outcome.BidConfirmationAttempted ?? outcome.SideEffectAttempted;
            // Same intent may wait/retry only before its irreversible confirmation.
            // No receipt or attempted claim is created for a yielded draft edit.
            if (!attemptedCommit && outcome.Reason == "USER_INPUT_YIELD")
                return NotSent(outcome.Reason);
            long sentNs = attemptedCommit ? clock() : 0; // Draft edits are not a submitted bid.
            var status = !attemptedCommit ? ReceiptStatus.NOT_SENT
                : outcome.Completed ? ReceiptStatus.SENT_PENDING_CONFIRMATION : ReceiptStatus.UNKNOWN;
            var receipt = new DomainReceipt(intent.IntentId, intent.Kind, intent.MatchId, intent.Round,
                intent.FactsRevision, status, outcome.Reason, intent.Amount, sentNs)
                { MatchGeneration = intent.MatchGeneration, ObservationSessionId = intent.ObservationSessionId, ApprovalId = intent.ApprovalId };
            receipts.Add(intent.IntentId, (intent, receipt, scope!.SourceSequence));
            if (attemptedCommit) attempted.Add((intent.MatchId, intent.Round, intent.Kind));
            if (status == ReceiptStatus.SENT_PENDING_CONFIRMATION) pending = intent.IntentId;
            if (status == ReceiptStatus.UNKNOWN && intent.Kind == DomainActionKind.Bid) return Stop(receipts[intent.IntentId], receipt.Reason);
            return receipt;
        }
    }

    public DomainReceipt Confirm(VisibleResult evidence)
    {
        lock (gate)
        {
            if (!receipts.TryGetValue(evidence.IntentId, out var entry))
                throw new ArgumentException("UNKNOWN_INTENT", nameof(evidence));
            if (entry.Receipt.Status != ReceiptStatus.SENT_PENDING_CONFIRMATION
                && !(entry.Intent.Kind == DomainActionKind.Bid && entry.Receipt.Status == ReceiptStatus.UNKNOWN && !stopped)) return entry.Receipt;
            var i = entry.Intent;
            var current = SafeRead();
            long now = clock();
            if (current is not null && current.Window != i.Window)
                return Stop(entry, "TARGET_IDENTITY_CHANGED");
            if (entry.Receipt.Status != ReceiptStatus.UNKNOWN && now >= entry.Receipt.SentNs + 3_000_000_000)
                return Stop(entry, "VISIBLE_RESULT_TIMEOUT_3S");
            bool matches = evidence.Kind == i.Kind && evidence.OriginMatchId == i.MatchId
                && evidence.OriginRound == i.Round && evidence.OriginFactsRevision == i.FactsRevision
                && evidence.OriginMatchGeneration == i.MatchGeneration && evidence.ObservationSessionId == i.ObservationSessionId
                && evidence.Window == i.Window && evidence.TakeoverGeneration == i.TakeoverGeneration
                && evidence.CapturedNs > entry.Receipt.SentNs;
            matches &= i.Kind switch
            {
                DomainActionKind.Bid => (evidence.Scene is "AUCTION" or "AUCTION_R1" or "AUCTION_READY" or "AUCTION_WAITING") && evidence.AcceptedOwnAmount == i.Amount,
                DomainActionKind.ReturnLobby => evidence.Scene == "LOBBY",
                DomainActionKind.SellNonRed => evidence.Scene == "SETTLEMENT" && evidence.SaleConfirmed,
                DomainActionKind.StartNextMatch => evidence.Scene == "ENTRY_FEE",
                _ when AuctionPreparation.IsPreparation(i.Kind) => AuctionPreparation.Confirms(i.Kind, evidence.Scene, evidence.PreparationEffectVisible),
                _ => false,
            };
            if (i.Kind == DomainActionKind.CancelKnownPopup) matches &= evidence.Scene != i.RecoveryScene;
            if (i.Kind == DomainActionKind.ConfirmToolRefill)
                matches &= (evidence.Scene == "LOBBY"
                    ? i.Amount is > 0 && i.FundsBefore >= i.Amount
                        && evidence.Instruments?.Funds == i.FundsBefore - i.Amount
                    : evidence.Instruments?.GoldAverage > i.GoldStockBefore
                        || evidence.Instruments?.PurpleCount > i.PurpleStockBefore)
                    && evidence.Instruments?.Funds >= i.MinimumFunds;
            if (!matches) return entry.Receipt; // Neither OS success nor unrelated/stale frames confirm.
            var confirmed = entry.Receipt with { Status = ReceiptStatus.CONFIRMED, Reason = "VISIBLE_RESULT_CONFIRMED",
                EvidenceSequence = evidence.SourceSequence, NewMatchId = evidence.NewMatchId,
                NewMatchGeneration = evidence.NewMatchGeneration };
            confirmed = confirmed with { EvidenceRef = evidence.EvidenceRef };
            receipts[i.IntentId] = (i, confirmed, entry.Sequence); pending = null;
            return confirmed;
        }
    }

    // A visible high-price dialog is a distinct, one-shot continuation of the
    // existing bid, never a retry of SubmitBid or an UNKNOWN receipt.
    public DomainReceipt? ContinueBidWarning(string intentId, long amount, ActionScope frame,
        Func<Func<bool>, PortOutcome> send)
    {
        lock (gate)
        {
            if (pending != intentId || !receipts.TryGetValue(intentId, out var entry)) return null;
            var i=entry.Intent;
            if (entry.Receipt.Status != ReceiptStatus.SENT_PENDING_CONFIRMATION || i.Kind != DomainActionKind.Bid) return entry.Receipt;
            if (clock() >= entry.Receipt.SentNs+3_000_000_000) return Stop(entry,"VISIBLE_RESULT_TIMEOUT_3S");
            if (warningAttempted.Contains(intentId)) return entry.Receipt;
            if (amount != i.Amount || frame.Scene != "BID_WARNING" || frame.Window != i.Window
                || frame.MatchId != i.MatchId || frame.MatchGeneration != i.MatchGeneration
                || frame.ObservationSessionId != i.ObservationSessionId || frame.Round != i.Round
                || frame.CapturedNs <= entry.Receipt.SentNs) return entry.Receipt;
            warningAttempted.Add(intentId); // Includes a throwing/unknown API result.
            PortOutcome result;
            try { result=send(()=>Validate(i,SafeRead())=="OK"); }
            catch { result=new(true,false,"BID_WARNING_EXCEPTION_UNKNOWN"); }
            if (!result.Completed) return Stop(entry,"BID_WARNING_"+result.Reason);
            var receipt=entry.Receipt with {SentNs=clock(),Reason="BID_WARNING_SENT_PENDING_CONFIRMATION"};
            receipts[intentId]=(i,receipt,entry.Sequence);
            return receipt;
        }
    }

    // Called on timer, disconnect and takeover; UNKNOWN cannot be cleared by a resend.
    public DomainReceipt? Poll()
    {
        lock (gate)
        {
            if (pending == null) return null;
            var entry = receipts[pending];
            var current = SafeRead();
            long now = clock();
            if (current is not null && current.Window != entry.Intent.Window)
                return Stop(entry, "TARGET_IDENTITY_CHANGED");
            return now >= entry.Receipt.SentNs + 3_000_000_000
                ? Stop(entry, "VISIBLE_RESULT_TIMEOUT_3S") : entry.Receipt;
        }
    }

    public DomainReceipt MarkUnknown(string intentId, string reason)
    {
        lock (gate)
        {
            if (!receipts.TryGetValue(intentId, out var entry)) throw new ArgumentException("UNKNOWN_INTENT");
            return Stop(entry, reason);
        }
    }

    private DomainReceipt Stop((DomainIntent Intent, DomainReceipt Receipt, long Sequence) entry, string reason)
    {
        if(entry.Intent.Kind == DomainActionKind.Bid) {
            var key=(entry.Intent.MatchId,entry.Intent.MatchGeneration);
            if(unknownIntents.Add(entry.Intent.IntentId))
                unknownCounts[key]=unknownCounts.GetValueOrDefault(key)+1;
            if(unknownCounts[key]>=2) { stopped=true; reason="SECOND_BID_UNKNOWN"; }
            if(reason is "OWN_BID_AMOUNT_MISMATCH" or "TARGET_IDENTITY_CHANGED") stopped=true;
        }
        var result = entry.Receipt with { Status = ReceiptStatus.UNKNOWN, Reason = reason };
        receipts[entry.Intent.IntentId] = (entry.Intent, result, entry.Sequence);
        pending = null; return result;
    }
    private ActionScope? SafeRead() { try { return readScope(); } catch { return null; } }
    private string Validate(DomainIntent i, ActionScope? s)
    {
        long now = clock();
        if (string.IsNullOrWhiteSpace(i.IntentId) || string.IsNullOrWhiteSpace(i.MatchId)
            || string.IsNullOrWhiteSpace(i.LeaseId) || i.FactsRevision < 0 || i.Budget <= 0
            || i.MatchGeneration <= 0 || string.IsNullOrWhiteSpace(i.ObservationSessionId)
            || i.Window.Hwnd <= 0 || i.Window.Pid <= 0 || i.Window.ProcessInstanceToken <= 0)
            return "INVALID_INTENT";
        if (s is null || s.Window != i.Window || !s.ForegroundMatches)
            return "TARGET_IDENTITY_REJECTED";
        if (i.Kind == DomainActionKind.CancelKnownPopup && (!AuctionPreparation.IsKnownPopup(i.RecoveryScene) || s.Scene != i.RecoveryScene))
            return "RECOVERY_SCENE_MISMATCH";
        return i.Kind switch
        {
            DomainActionKind.Bid when i.Round is >= 1 and <= 5
                && i.Amount is > 0 and <= 9_999_999 && i.Amount <= i.Budget
                && i.Amount <= i.MaxSafeBid
                && !string.IsNullOrWhiteSpace(i.ApprovalId) => "OK",
            DomainActionKind.SellNonRed when s.Scene == "SETTLEMENT" && s.SettlementArchived && i.SettlementAcquired
                && i.Amount is null && !string.IsNullOrWhiteSpace(i.ApprovalId) => "OK",
            DomainActionKind.ReturnLobby when s.Scene == "SETTLEMENT" && s.SettlementArchived && i.Amount == null => "OK",
            DomainActionKind.StartNextMatch when s.Scene == "LOBBY"
                && i.Round == 0 && i.Amount == null => "OK",
            _ when AuctionPreparation.IsLobby(i.Kind) && i.Round == 0
                && !string.IsNullOrWhiteSpace(i.ApprovalId)
                && (i.Kind is DomainActionKind.ConfirmToolRefill or DomainActionKind.ConfirmEntryFee
                    ? (i.Kind == DomainActionKind.ConfirmEntryFee ? i.Amount is >= 0 : i.Amount is > 0)
                        && i.Amount <= i.Budget && i.MinimumFunds >= 0 : i.Amount is null) => "OK",
            _ when AuctionPreparation.IsPreparation(i.Kind)
                && i.Amount is null && i.Round is >= 1 and <= 5
                && !string.IsNullOrWhiteSpace(i.ApprovalId) => "OK",
            _ => "DOMAIN_SCENE_AMOUNT_OR_ADMISSION_REJECTED",
        };
    }
}
