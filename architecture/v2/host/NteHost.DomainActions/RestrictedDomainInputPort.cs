namespace NteHost.DomainActions;

public enum DomainPrimitive { FocusAmountField, ReplaceAmountDigits, SubmitBid, ReturnLobby, StartNextMatch,
    OpenInstrument, SelectGoldAverage, UseGoldAverage, OpenBidPanel,
    OpenToolSetup, RequestToolRefill, ConfirmToolRefill, CloseToolSetup }
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
        bool attempted = false;
        PortOutcome Step(DomainPrimitive primitive)
        {
            if (!current()) return new(attempted, false, "CURRENT_REJECTED_BEFORE_" + primitive);
            try
            {
                var result = backend.Execute(primitive, intent, current);
                attempted |= result.SideEffectAttempted;
                return result with { SideEffectAttempted = attempted };
            }
            catch { return new(true, false, "PRIMITIVE_EXCEPTION_UNKNOWN"); }
        }
        if (intent.Kind == DomainActionKind.ReturnLobby) return Step(DomainPrimitive.ReturnLobby);
        if (intent.Kind == DomainActionKind.StartNextMatch) return Step(DomainPrimitive.StartNextMatch);
        if (AuctionPreparation.IsPreparation(intent.Kind)
            && Enum.TryParse<DomainPrimitive>(intent.Kind.ToString(), out var preparation)) return Step(preparation);
        if (intent.Kind != DomainActionKind.Bid || intent.Amount is not (> 0 and <= 9_999_999))
            return new(false, false, "INVALID_BOUNDED_AMOUNT");
        var focus = Step(DomainPrimitive.FocusAmountField);
        if (!focus.Completed) return focus;
        var replace = Step(DomainPrimitive.ReplaceAmountDigits);
        if (!replace.Completed) return replace;
        long replacedNs = clock();
        AmountFieldReadback? field;
        try { field = backend.ReadAmountField(); }
        catch { return new(attempted, false, "AMOUNT_READBACK_EXCEPTION"); }
        long now = clock();
        // Field readback is a pre-submit check, never the accepted-bid receipt.
        // Require a newly captured field frame, not retained pixels before typing.
        if (field == null || field.Amount != intent.Amount || field.Window != intent.Window
            || field.CapturedNs <= replacedNs)
            return new(attempted, false, "AMOUNT_FIELD_READBACK_UNPROVEN");
        return Step(DomainPrimitive.SubmitBid);
    }
}
