namespace NteHost.DomainActions;

public enum DomainPrimitive { FocusAmountField, ReplaceAmountDigits, SubmitBid, ReturnLobby, StartNextMatch,
    OpenInstrument, SelectGoldAverage, UseGoldAverage, OpenBidPanel,
    OpenToolSetup, RequestToolRefill, ConfirmToolRefill, CloseToolSetup, BrowseToolGroups, SelectToolGroup,
    ConfirmEntryFee, ClearAmount, AmountDigit0, AmountDigit1, AmountDigit2, AmountDigit3, AmountDigit4,
    AmountDigit5, AmountDigit6, AmountDigit7, AmountDigit8, AmountDigit9, SelectPurpleCount, UsePurpleCount, ConfirmBidWarning }
public sealed record AmountFieldReadback(long Amount, string MatchId, int Round, long FactsRevision,
    WindowBinding Window, long TakeoverGeneration, long CapturedNs, bool SourceQualified)
{
    public long MatchGeneration { get; init; }
    public string ObservationSessionId { get; init; } = "";
}

public interface ITicketedDomainBackend
{
    // Native adapter owns target geometry and MUST acquire/consume an existing
    // one-shot ticket after both identity/focus checks. No caller coordinates,
    // arbitrary text, keys, macros, retry loops or default Win32 implementation.
    // current must also be checked at the ticket commit boundary. Side-effect
    // attempts include cursor preparation and partial/throwing native sends.
    PortOutcome Execute(DomainPrimitive primitive, DomainIntent intent, Func<bool> current);
    AmountFieldReadback? ReadAmountField();
    bool HasTimeToFillAndConfirm(DomainIntent intent) => true;
    bool HasTimeToConfirm(DomainIntent intent) => true;
}

/// <summary>Closed bid/return/start transaction, for a ticketed adapter or offline substitute.</summary>
public sealed class RestrictedDomainInputPort : IRestrictedDomainInputPort
{
    private readonly ITicketedDomainBackend backend;
    private readonly Func<long> clock;
    public RestrictedDomainInputPort(ITicketedDomainBackend backend, Func<long> clock)
    {
        this.backend = backend; this.clock = clock;
    }
    public PortOutcome TrySend(DomainIntent intent, Func<bool> current)
    {
        PortOutcome Step(DomainPrimitive primitive)
        {
            if (!current()) return new(false, false, "CURRENT_REJECTED_BEFORE_" + primitive);
            try
            {
                var result = backend.Execute(primitive, intent, current);
                return result;
            }
            catch { return new(true, false, "PRIMITIVE_EXCEPTION_UNKNOWN"); }
        }
        if (intent.Kind == DomainActionKind.ReturnLobby) return Step(DomainPrimitive.ReturnLobby);
        if (intent.Kind == DomainActionKind.StartNextMatch) return Step(DomainPrimitive.StartNextMatch);
        if (AuctionPreparation.IsPreparation(intent.Kind)
            && Enum.TryParse<DomainPrimitive>(intent.Kind.ToString(), out var preparation)) return Step(preparation);
        if (intent.Kind != DomainActionKind.Bid || intent.Amount is not (> 0 and <= 9_999_999))
            return new(false, false, "INVALID_BOUNDED_AMOUNT");
        PortOutcome NotSubmitted(string reason) => new(false,false,reason) { BidConfirmationAttempted=false };
        if (!backend.HasTimeToFillAndConfirm(intent)) return NotSubmitted("ROUND_TIME_TOO_SHORT");
        var focus = Step(DomainPrimitive.FocusAmountField);
        if (!focus.Completed) return NotSubmitted(focus.Reason);
        for (int attempt=0; attempt<2; attempt++)
        {
            if (!backend.HasTimeToFillAndConfirm(intent)) return NotSubmitted("ROUND_TIME_TOO_SHORT");
            var replace = Step(DomainPrimitive.ReplaceAmountDigits);
            if (!replace.Completed) return NotSubmitted(replace.Reason);
            long replacedNs = clock();
            AmountFieldReadback? field;
            try { field = backend.ReadAmountField(); }
            catch { field = null; }
            if (field is not null && field.Window != intent.Window) return NotSubmitted("TARGET_IDENTITY_REJECTED");
            if (field is not null && field.Amount == intent.Amount && field.CapturedNs > replacedNs)
            {
                if (!backend.HasTimeToConfirm(intent)) return NotSubmitted("ROUND_TIME_TOO_SHORT");
                var submit=Step(DomainPrimitive.SubmitBid);
                return submit with { BidConfirmationAttempted=submit.SideEffectAttempted };
            }
            // Before SubmitBid, clear-and-refill is safe. At most two fills,
            // exactly one read after each complete amount, never per digit.
        }
        return NotSubmitted("AMOUNT_FILL_FAILED_AFTER_2");
    }
}
