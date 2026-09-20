namespace NteHost.Input;

/// <summary>
/// Single-use capability issued by <see cref="InputSafetyGuard"/> after BOTH
/// prechecks pass. The executor refuses to touch the OS without a valid one, so
/// "fail closed" is a structural property of the code path rather than a promise:
/// there is no route to <see cref="IRawInputBackend.Send"/> that skips this gate.
/// </summary>
public sealed class SendInputTicket
{
    private int _consumed;

    internal SendInputTicket(long id, long authorityId, string actionFingerprint, long issuedNs, long expiresNs, ulong marker)
    {
        Id = id;
        AuthorityId = authorityId;
        ActionFingerprint = actionFingerprint;
        IssuedNs = issuedNs;
        ExpiresNs = expiresNs;
        Marker = marker;
    }

    public long Id { get; }

    public long AuthorityId { get; }

    public string ActionFingerprint { get; }

    public long IssuedNs { get; }

    public long ExpiresNs { get; }

    /// <summary>
    /// Per-arming marker stamped into <c>dwExtraInfo</c> on every record this
    /// ticket authorises. The marker is part of the ticket, so the executor cannot
    /// invent one and the ledger cannot accept one it never issued.
    /// </summary>
    public ulong Marker { get; }

    public bool IsConsumed => Volatile.Read(ref _consumed) != 0;

    internal bool TryConsume() => Interlocked.Exchange(ref _consumed, 1) == 0;
}

public interface ISendInputTicketAuthority
{
    long AuthorityId { get; }

    /// <summary>
    /// Validates and atomically consumes the ticket. Returns <see cref="InputSafetyReasons.Ok"/>
    /// on success, otherwise the blocking reason.
    /// </summary>
    string TryConsumeTicket(SendInputTicket ticket, InputAction action);
}

public sealed record ExecutorOutcome(
    bool Ok,
    string Reason,
    long SendCallCount,
    long InputsSentCount);

/// <summary>
/// Safe SendInput executor. Owns the only call site of the raw backend.
/// </summary>
public sealed class SafeSendInputExecutor
{
    private readonly IRawInputBackend _backend;
    private readonly ISendInputTicketAuthority _authority;

    public SafeSendInputExecutor(IRawInputBackend backend, ISendInputTicketAuthority authority)
    {
        _backend = backend;
        _authority = authority;
    }

    public long SendCallCount => _backend.SendCallCount;

    public long InputsSentCount => _backend.InputsSentCount;

    public ExecutorOutcome Execute(InputAction action, SendInputTicket? ticket)
    {
        ArgumentNullException.ThrowIfNull(action);

        if (ticket is null)
        {
            return Fail(InputSafetyReasons.TicketMissing);
        }

        if (ticket.AuthorityId != _authority.AuthorityId)
        {
            return Fail(InputSafetyReasons.TicketForeign);
        }

        if (ticket.IsConsumed)
        {
            return Fail(InputSafetyReasons.TicketReused);
        }

        if (TraceClock.NowNs() > ticket.ExpiresNs)
        {
            return Fail(InputSafetyReasons.TicketExpired);
        }

        if (!string.Equals(ticket.ActionFingerprint, action.Fingerprint, StringComparison.Ordinal))
        {
            return Fail(InputSafetyReasons.TicketActionMismatch);
        }

        InputRecord[] inputs = BuildInputs(action, ticket.Marker, out string buildReason);
        if (inputs.Length == 0)
        {
            return Fail(buildReason);
        }

        // Atomic with the authority's state check, so an external Cancel() that
        // successfully linearises before this point yields zero SendInput calls.
        // A request blocked behind the guard's state gate cannot revoke a call that
        // has already crossed the backend boundary.
        string authorityReason = _authority.TryConsumeTicket(ticket, action);
        if (authorityReason != InputSafetyReasons.Ok)
        {
            return Fail(authorityReason);
        }

        try
        {
            uint accepted = _backend.Send(inputs);
            if (accepted != inputs.Length)
            {
                return Fail(InputSafetyReasons.SendInputPartial);
            }
        }
        catch
        {
            return Fail(InputSafetyReasons.BackendError);
        }

        return new ExecutorOutcome(true, InputSafetyReasons.Ok, _backend.SendCallCount, _backend.InputsSentCount);
    }

    private ExecutorOutcome Fail(string reason) =>
        new(false, reason, _backend.SendCallCount, _backend.InputsSentCount);

    private static InputRecord[] BuildInputs(InputAction action, ulong marker, out string reason)
    {
        reason = InputSafetyReasons.Ok;

        switch (action.Kind)
        {
            case InputActionKind.MouseWheel:
                return
                [
                    new InputRecord(
                        NativeInputMethods.INPUT_MOUSE,
                        0,
                        0,
                        unchecked((uint)action.WheelDelta),
                        NativeInputMethods.MOUSEEVENTF_WHEEL,
                        marker),
                ];

            case InputActionKind.MouseHorizontalWheel:
                return
                [
                    new InputRecord(
                        NativeInputMethods.INPUT_MOUSE,
                        0,
                        0,
                        unchecked((uint)action.WheelDelta),
                        NativeInputMethods.MOUSEEVENTF_HWHEEL,
                        marker),
                ];

            case InputActionKind.CursorMove:
                // Cursor moves go through ICursorBackend, never through SendInput.
                reason = InputSafetyReasons.InvalidAction;
                return [];

            default:
                reason = InputSafetyReasons.InvalidAction;
                return [];
        }
    }
}
