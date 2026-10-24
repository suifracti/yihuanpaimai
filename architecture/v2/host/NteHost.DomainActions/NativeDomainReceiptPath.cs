using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using System.Globalization;
using System.Text.RegularExpressions;

namespace NteHost.DomainActions;

/// <summary>Independent captured pixels with immutable scope, never a Solver result.</summary>
public sealed class NativeDomainFrame
{
    public ActionScope Scope { get; }
    public ClientGeometry Geometry { get; }
    public ReadOnlyMemory<byte> Pixels { get; }
    public int Stride { get; }
    public string EvidenceRef { get; }
    readonly Dictionary<IGameDomainFrameDecoder, DecodedDomainFrame?> decoded = new();
    public DecodedDomainFrame? DecodeOnce(IGameDomainFrameDecoder decoder)
    {
        lock (decoded)
        {
            if (decoded.TryGetValue(decoder, out var result)) return result;
            try { result = decoder.Decode(this); } catch { result = null; }
            decoded.Add(decoder, result);
            return result;
        }
    }
    public NativeDomainFrame(ActionScope scope, ClientGeometry geometry, byte[] bgra, int stride)
    {
        if (geometry.Width <= 0 || geometry.Height <= 0 || stride < geometry.Width * 4L
            || (long)stride * geometry.Height != bgra.Length) throw new ArgumentException("INVALID_FRAME_GEOMETRY");
        Scope = scope; Geometry = geometry; Stride = stride;
        Pixels = bgra.ToArray();
        EvidenceRef = $"capture:{scope.ObservationSessionId}:{scope.SourceSequence}:{Convert.ToHexString(SHA256.HashData(Pixels.Span))}";
    }
}
public sealed record OwnSeatBinding(int Slot, string PlayerIdentity);
public sealed record CapturedOwnBid(int Slot, string PlayerIdentity, long? Amount, bool AcceptanceVisible,
    string EvidenceRef)
{
    // The submitted button uses K/M with two decimal places. Retain its text;
    // it is a display confirmation of the already read-back exact input.
    public string? DisplayText { get; init; }
    public bool Readable => Amount is > 0 || Regex.IsMatch(Regex.Replace(DisplayText ?? "", @"\s*[,，]\s*", ",").Trim(), @"^(?:[1-9]\d*(?:\.\d{1,2})?[KM]|[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)$", RegexOptions.IgnoreCase);
    public bool MatchesAmount(long expected)
    {
        if (Amount is { } exact) return exact == expected;
        string text = Regex.Replace(DisplayText ?? "", @"\s", "").Replace('，', ',').Replace('．', '.').Replace('·', '.');
        if (Regex.IsMatch(text, @"^(?:\d+|\d{1,3}(?:,\d{3})+)$")
            && long.TryParse(text.Replace(",", ""), out var integer)) return expected > 0 && integer == expected;
        var match = Regex.Match(text,
            @"^(\d+(?:\.\d{1,2})?)([KM])$", RegexOptions.IgnoreCase);
        if (!match.Success || !decimal.TryParse(match.Groups[1].Value, NumberStyles.AllowDecimalPoint,
                CultureInfo.InvariantCulture, out var shown)) return false;
        decimal scale = match.Groups[2].Value.Equals("K", StringComparison.OrdinalIgnoreCase) ? 1000 : 1000000;
        // The UI hides the last digits. At a half step either neighboring
        // rendering is consistent; the exact input was checked before Submit.
        decimal displayUnit = scale / 100; // K: 10; M: 10,000, including hidden trailing zeroes.
        return expected > 0 && Math.Abs(expected - shown * scale) <= displayUnit / 2;
    }
}
public sealed record InstrumentStock(int? GoldAverage, int? PurpleCount, long? RefillCost, long? Funds);
public sealed record DecodedDomainFrame(string Scene, int Round, string MatchId, long MatchGeneration,
    CapturedOwnBid? OwnBid, long? AmountField, IReadOnlyList<VisibleControlAnchor> Controls)
{ public CapturedOwnBid? OwnSeatBid { get; init; }
  public long? BidWarningAmount { get; init; }
  public bool GoldAverageVisible { get; init; }
  public bool PurpleCountVisible { get; init; }
  public InstrumentStock? Instruments { get; init; }
  public SettlementSale? Sale { get; init; } }
public interface IGameDomainFrameDecoder
{
    // All fields must derive from THIS frame's pixels. Existing cached seats/myBid
    // or a typed amount ROI cannot attest accepted-own-bid. Unknown returns null.
    DecodedDomainFrame? Decode(NativeDomainFrame frame);
}
public sealed class UnconnectedGameDomainDecoder : IGameDomainFrameDecoder
{
    public DecodedDomainFrame? Decode(NativeDomainFrame frame) => null;
}

// Concrete capture/decoder join shared by the amount field and controls. Capture
// callback must request a new WGC frame; retained Engine context is not a capture.
public sealed class CapturedDomainControlEvidence : IDomainControlEvidence
{
    public string LastFailure { get; private set; } = "NOT_READ";
    public IReadOnlyList<VisibleControlAnchor> AmountKeypad { get; private set; } = [];
    private readonly Func<NativeDomainFrame?> capture;
    private readonly IGameDomainFrameDecoder decoder;
    public CapturedDomainControlEvidence(Func<NativeDomainFrame?> capture, IGameDomainFrameDecoder decoder)
    { this.capture = capture; this.decoder = decoder; }
    public VisibleControlAnchor? Locate(DomainPrimitive primitive, DomainIntent intent)
    {
        LastFailure = "CAPTURE_STARTED";
        var frame = capture();
        if (frame == null) { LastFailure = "INDEPENDENT_CAPTURE_UNAVAILABLE"; return null; }
        LastFailure = "DECODE_STARTED";
        var view = frame.DecodeOnce(decoder);
        if (primitive == DomainPrimitive.ReplaceAmountDigits)
            AmountKeypad = view?.Controls.Where(c => c.Primitive == DomainPrimitive.ClearAmount
                || c.Primitive >= DomainPrimitive.AmountDigit0 && c.Primitive <= DomainPrimitive.AmountDigit9).ToArray() ?? [];
        if (primitive is DomainPrimitive.ConfirmToolRefill or DomainPrimitive.ConfirmEntryFee
            && view?.Instruments?.RefillCost != intent.Amount)
        { LastFailure = "REFILL_PRICE_CHANGED_OR_UNKNOWN"; return null; }
        if (primitive == DomainPrimitive.ConfirmBidWarning && view?.BidWarningAmount != intent.Amount)
        { LastFailure = "BID_WARNING_AMOUNT_MISMATCH"; return null; }
        if (primitive == DomainPrimitive.SellNonRed && view?.Sale?.Ready != true)
        { LastFailure="SALE_SELECTION_NOT_READY_RED_MUST_BE_OFF"; return null; }
        string expectedScene = primitive == DomainPrimitive.ConfirmBidWarning ? "BID_WARNING" : intent.Kind switch { DomainActionKind.Bid => "AUCTION",
            DomainActionKind.ReturnLobby or DomainActionKind.SellNonRed => "SETTLEMENT", DomainActionKind.StartNextMatch => "LOBBY",
            _ => AuctionPreparation.ExpectedScene(intent.Kind) ?? "INVALID" };
        bool selectedList = intent.Kind is DomainActionKind.SelectGoldAverage or DomainActionKind.SelectPurpleCount
            && view?.Scene is "INSTRUMENT_GOLD_SELECTED" or "INSTRUMENT_PURPLE_SELECTED";
        bool cancellingKnownPopup = intent.Kind == DomainActionKind.CancelKnownPopup && AuctionPreparation.IsKnownPopup(view?.Scene) && view?.Scene == intent.RecoveryScene;
        if (view == null || (view.Scene != expectedScene && !selectedList && !cancellingKnownPopup)
            || view.MatchId != frame.Scope.MatchId || view.MatchGeneration != frame.Scope.MatchGeneration
            || view.Round != frame.Scope.Round)
        { LastFailure = $"DECODE_OR_SCOPE:expected={expectedScene},decoded={view?.Scene},scope={frame.Scope.Scene}"; return null; }
        var matches = view?.Controls.Where(a => a.Primitive == primitive
            && a.EvidenceRef == frame.EvidenceRef && a.SourceSequence == frame.Scope.SourceSequence
            && a.CapturedNs == frame.Scope.CapturedNs && a.Geometry == frame.Geometry).ToArray();
        LastFailure = matches is { Length: 1 } ? "OK" : "CONTROL_BINDING_OR_MATCH_COUNT:" + matches?.Length;
        return matches is { Length: 1 } ? matches[0] : null;
    }
    public SettlementSale? CaptureSaleSelection() { var f=capture(); return f?.DecodeOnce(decoder)?.Sale; }
    public AmountFieldReadback? CaptureAmountField()
    {
        var frame = capture();
        if (frame == null) return null;
        var view = frame.DecodeOnce(decoder);
        if (view?.AmountField is not (>= 0 and <= 9_999_999) || view.Scene != "AUCTION"
            || view.MatchId != frame.Scope.MatchId || view.MatchGeneration != frame.Scope.MatchGeneration
            || view.Round != frame.Scope.Round) return null;
        var s = frame.Scope;
        return new(view.AmountField.Value, s.MatchId, s.Round, s.FactsRevision, s.Window,
            s.TakeoverGeneration, s.CapturedNs, s.SourceQualified)
            { MatchGeneration = s.MatchGeneration, ObservationSessionId = s.ObservationSessionId };
    }
}

public sealed class NativeVisibleResultProducer
{
    private readonly IGameDomainFrameDecoder decoder;
    private readonly Func<long> clock;
    public NativeVisibleResultProducer(IGameDomainFrameDecoder decoder, Func<long> clock)
    { this.decoder = decoder; this.clock = clock; }
    public IGameDomainFrameDecoder Decoder => decoder;
    public VisibleResult? FromCapture(DomainIntent intent, DomainReceipt pending, NativeDomainFrame frame, OwnSeatBinding? ownSeat)
    {
        var s = frame.Scope; long now = clock();
        if (pending.Status is not (ReceiptStatus.SENT_PENDING_CONFIRMATION or ReceiptStatus.UNKNOWN) || pending.IntentId != intent.IntentId
            || s.CapturedNs <= pending.SentNs || s.Window != intent.Window
            || s.ObservationSessionId != intent.ObservationSessionId || s.TakeoverGeneration != intent.TakeoverGeneration)
            return null;
        var view = frame.DecodeOnce(decoder);
        if (pending.Status == ReceiptStatus.UNKNOWN && view is not null)
            view = view with { OwnBid = view.OwnSeatBid };
        if (view == null || view.MatchId != s.MatchId || view.MatchGeneration != s.MatchGeneration || view.Round != s.Round)
            return null;
        long? accepted = null; string? newMatch = null; long newGeneration = 0;
        if (intent.Kind == DomainActionKind.Bid)
        {
            if (s.MatchId != intent.MatchId || s.MatchGeneration != intent.MatchGeneration || s.Round != intent.Round
                || view.Scene is not ("AUCTION" or "AUCTION_R1" or "AUCTION_READY" or "AUCTION_WAITING") || ownSeat == null || view.OwnBid == null
                || !view.OwnBid.AcceptanceVisible || view.OwnBid.Slot != ownSeat.Slot
                || string.IsNullOrWhiteSpace(ownSeat.PlayerIdentity) || view.OwnBid.PlayerIdentity != ownSeat.PlayerIdentity
                || view.OwnBid.EvidenceRef != frame.EvidenceRef || intent.Amount is not { } amount
                || !view.OwnBid.MatchesAmount(amount)) return null;
            accepted = amount;
        }
        else if (intent.Kind == DomainActionKind.SellNonRed)
        {
            if (view.Scene != "SETTLEMENT" || s.MatchId != intent.MatchId || s.MatchGeneration != intent.MatchGeneration
                || !(view.Sale?.Sold == true || intent.FundsBefore > 0 && view.Sale?.Funds > intent.FundsBefore)) return null;
        }
        else if (intent.Kind == DomainActionKind.ReturnLobby)
        {
            if (view.Scene != "LOBBY") return null;
        }
        else if (intent.Kind == DomainActionKind.StartNextMatch)
        {
            if (view.Scene != "ENTRY_FEE") return null;
        }
        else if (AuctionPreparation.IsPreparation(intent.Kind))
        {
            if (!AuctionPreparation.Confirms(intent.Kind, view.Scene,
                    intent.Kind == DomainActionKind.UsePurpleCount ? view.PurpleCountVisible : view.GoldAverageVisible)
                || s.MatchId != intent.MatchId || s.MatchGeneration != intent.MatchGeneration
                || s.Round != intent.Round) return null;
        }
        else return null;
        return new(intent.IntentId, intent.Kind, intent.MatchId, intent.Round, intent.FactsRevision,
            accepted, newMatch, view.Scene, s.SourceSequence, s.CapturedNs, s.SourceQualified, s.Window, s.TakeoverGeneration)
            { OriginMatchGeneration = intent.MatchGeneration, ObservationSessionId = s.ObservationSessionId,
              NewMatchGeneration = newGeneration, EvidenceRef = frame.EvidenceRef,
              PreparationEffectVisible = intent.Kind == DomainActionKind.UsePurpleCount ? view.PurpleCountVisible : view.GoldAverageVisible,
              Instruments = view.Instruments, SaleConfirmed = intent.Kind == DomainActionKind.SellNonRed };
    }
}

/// <summary>Actual receipt events for Luna-B's transport, with durable commit before publication.</summary>
public sealed class NativeDomainActionRuntime
{
    private readonly DomainActionCoordinator coordinator;
    private readonly NativeVisibleResultProducer producer;
    private readonly IExecutionObligationPort? obligations;
    private readonly Action<JsonObject> publish;
    private readonly Dictionary<string, DomainIntent> intents = new();
    private readonly object gate = new();
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Converters = { new JsonStringEnumConverter() } };
    public NativeDomainActionRuntime(DomainActionCoordinator coordinator, NativeVisibleResultProducer producer,
        IExecutionObligationPort? obligations, Action<JsonObject> publish)
    { this.coordinator = coordinator; this.producer = producer; this.obligations = obligations; this.publish = publish; }
    public DomainReceipt Dispatch(DomainIntent intent)
    {
        lock (gate)
        {
            if (intents.TryGetValue(intent.IntentId, out var prior) && prior != intent)
                throw new ArgumentException("IMMUTABLE_INTENT_CONFLICT");
            intents[intent.IntentId] = intent;
            var receipt = coordinator.Dispatch(intent);
            return receipt.Status == ReceiptStatus.NOT_SENT && receipt.Reason == "USER_INPUT_YIELD"
                ? receipt : Emit(receipt);
        }
    }
    public DomainReceipt? OnIndependentCapture(string intentId, NativeDomainFrame frame, OwnSeatBinding? ownSeat)
    {
        lock (gate)
        {
            if (!intents.TryGetValue(intentId, out var intent)) return null;
            var pending = coordinator.Receipt(intentId);
            if (pending == null) return null;
            if (pending.Status == ReceiptStatus.UNKNOWN) {
                var own=frame.DecodeOnce(producer.Decoder)?.OwnSeatBid;
                if (frame.Scope.MatchId != intent.MatchId || frame.Scope.MatchGeneration != intent.MatchGeneration
                    || frame.Scope.Round != intent.Round || frame.Scope.Window != intent.Window
                    || frame.Scope.ObservationSessionId != intent.ObservationSessionId || frame.Scope.CapturedNs <= pending.SentNs) return null;
                if (own?.Readable == true && intent.Amount is { } expected && !own.MatchesAmount(expected))
                    return Emit(coordinator.MarkUnknown(intentId,"OWN_BID_AMOUNT_MISMATCH"));
            }
            if (pending.IntentId != intentId) return null;
            VisibleResult? result;
            try { result = producer.FromCapture(intent, pending, frame, ownSeat); }
            catch { result = null; }
            return result == null ? (pending.Status == ReceiptStatus.UNKNOWN ? pending : Poll()) : Emit(coordinator.Confirm(result));
        }
    }
    public DomainReceipt? ContinueBidWarning(string intentId, long amount, ActionScope frame,
        Func<Func<bool>, PortOutcome> send)
    {
        lock (gate) {
            var result=coordinator.ContinueBidWarning(intentId, amount, frame, send);
            return result?.Status == ReceiptStatus.UNKNOWN ? Emit(result) : result;
        }
    }
    public DomainReceipt? Poll()
    {
        lock (gate) { var result = coordinator.Poll(); return result == null ? null : Emit(result); }
    }
    private DomainReceipt Emit(DomainReceipt receipt)
    {
        bool committed = receipt.Kind != DomainActionKind.Bid;
        if (receipt.Kind == DomainActionKind.Bid)
        {
            try { committed = obligations?.CommitReceipt(receipt) == true; } catch { committed = false; }
            if (!committed)
            {
                publish(new JsonObject { ["type"]="domain.action.dispatch.rejected",
                    ["observationSessionId"]=receipt.ObservationSessionId, ["intentId"]=receipt.IntentId,
                    ["reason"]="DURABLE_RECEIPT_COMMIT_FAILED:" + receipt.Reason,
                    ["inputActions"]=false }); // a stop notice, never a committed bid receipt
                if (receipt.Status != ReceiptStatus.NOT_SENT)
                    receipt = coordinator.MarkUnknown(receipt.IntentId, "DURABLE_RECEIPT_COMMIT_FAILED");
            }
        }
        var node = JsonSerializer.SerializeToNode(receipt, Json)!.AsObject();
        var message = new JsonObject
        {
            ["type"] = "domain.action.receipt",
            ["observationSessionId"] = receipt.ObservationSessionId,
            ["receipt"] = node,
            ["receiptChannel"] = receipt.Kind == DomainActionKind.Bid ? "bid"
                : AuctionPreparation.IsPreparation(receipt.Kind) ? "preparation" : "session",
        };
        // Main only exposes a bid receipt after its sole durable ledger ACK.
        if (committed) publish(message);
        return receipt;
    }
}
