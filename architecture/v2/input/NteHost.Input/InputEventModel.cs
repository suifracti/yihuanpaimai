using System.Diagnostics;

namespace NteHost.Input;

/// <summary>
/// Closed set of input event kinds the observer is allowed to forward.
/// Anything the low-level hook sees that does not map into this set is never
/// forwarded at all, so it can neither cause a false takeover nor a false
/// exemption. The set is deliberately closed rather than "unknown kind" so that
/// an unmapped message can never be interpreted as a policy input.
/// </summary>
public enum InputEventKind
{
    KeyDown,
    MouseButtonDown,
    MouseWheel,
    MouseHorizontalWheel,
    MouseMove,
}

public enum InputDeviceClass
{
    Keyboard,
    Mouse,
}

/// <summary>
/// How the OS says the event entered the input stream.
///
/// TRUST BOUNDARY (see also <c>TrustBoundary</c> documentation in the PR):
///   * <see cref="Injected"/> means the OS low-level hook set LLKHF_INJECTED /
///     LLMHF_INJECTED. That proves "not physical hardware", it does NOT prove
///     "produced by this process". Any other process using SendInput produces
///     the same flag.
///   * <see cref="LowerIntegrityInjected"/> means the injection came from a
///     lower integrity level (LLKHF/LLMHF_LOWER_IL_INJECTED). That is never
///     treated as trustworthy.
///   * <see cref="Hardware"/> means the OS did not mark the event as injected.
///     Only this origin is, by construction, impossible to forge from user mode.
/// </summary>
public enum InputEventOrigin
{
    Hardware,
    Injected,
    LowerIntegrityInjected,
}

/// <summary>
/// A single observed input event, reduced to the minimum needed for the safety
/// decision. Only the closed transient domain key/button discriminator is
/// forwarded; no scan codes, typed text, input history or unbounded coordinate
/// stream are retained anywhere in this module.
/// </summary>
public readonly record struct ObservedInputEvent(
    InputEventKind Kind,
    InputDeviceClass Device,
    InputEventOrigin Origin,
    ulong ExtraInfo,
    int X,
    int Y,
    long MonotonicNs,
    long Sequence)
{
    /// <summary>
    /// Raw low-level hook flags.  This is diagnostic provenance only; the
    /// policy classification remains the <see cref="Origin"/> value.
    /// Synthetic/fake events leave this at zero unless a test explicitly
    /// supplies flags.
    /// </summary>
    public uint NativeFlags { get; init; }
    // Only the closed domain key set and left-button identity, not typed text/history.
    public uint DomainCode { get; init; }
}

/// <summary>
/// The only actions this module is allowed to perform on the OS input stream.
/// Legacy public actions never inject keys. Internal, OFF-by-default domain
/// capabilities permit only an exact left click or bounded amount replacement.
/// </summary>
public enum InputActionKind
{
    MouseWheel,
    MouseHorizontalWheel,
    CursorMove,
    RestrictedLeftClick,
    RestrictedAmountDigits,
    RestrictedAmountKeypad,
}

/// <summary>
/// Optional cursor move performed *between* the two prechecks. This is the real
/// production shape of the operation (park the pointer on a known-safe point,
/// then scroll), and it is what opens the TOCTOU window that must fail closed.
/// </summary>
public readonly record struct CursorPrepare(int X, int Y);
internal readonly record struct KeypadClick(int X, int Y, int AbsoluteX, int AbsoluteY);

public sealed record InputAction
{
    public required InputActionKind Kind { get; init; }
    public int WheelDelta { get; init; }
    public int X { get; init; }
    public int Y { get; init; }
    public CursorPrepare? Prepare { get; init; }
    internal string? AmountDigits { get; init; }
    internal IReadOnlyList<KeypadClick>? KeypadClicks { get; init; }
    internal CursorPrepare? DomainPoint { get; init; }
    internal int DomainAbsoluteX { get; init; }
    internal int DomainAbsoluteY { get; init; }
    internal Func<bool>? DomainCurrent { get; init; }
    internal bool IsDomain => Kind is InputActionKind.RestrictedLeftClick or InputActionKind.RestrictedAmountDigits or InputActionKind.RestrictedAmountKeypad;
    internal bool DomainValid => !IsDomain || (DomainCurrent != null &&
        (Kind == InputActionKind.RestrictedLeftClick ? DomainPoint.HasValue && DomainAbsoluteX is >= 0 and <= 65535
            && DomainAbsoluteY is >= 0 and <= 65535 :
            AmountDigits is { Length: >= 1 and <= 7 } d && d.All(c => c is >= '0' and <= '9') && d[0] != '0'
            && (Kind != InputActionKind.RestrictedAmountKeypad || KeypadClicks is { } keys
                && keys.Count == d.Length + 1 && keys.All(k => k.AbsoluteX is >= 0 and <= 65535 && k.AbsoluteY is >= 0 and <= 65535))));
    internal bool CheckDomainCurrent()
    {
        if (!IsDomain) return true;
        try { return DomainValid && DomainCurrent!(); } catch { return false; }
    }
    // Accessible solely to the domain assembly; there is no public coordinate/key API.
    internal static InputAction DomainClick(int x, int y, int absoluteX, int absoluteY, Func<bool> current) => new()
        { Kind = InputActionKind.RestrictedLeftClick, DomainPoint = new(x, y),
          DomainAbsoluteX = absoluteX, DomainAbsoluteY = absoluteY, DomainCurrent = current };
    internal static InputAction DomainAmount(long amount, Func<bool> current) => new()
        { Kind = InputActionKind.RestrictedAmountDigits,
          AmountDigits = amount.ToString(System.Globalization.CultureInfo.InvariantCulture), DomainCurrent = current };
    internal static InputAction DomainKeypad(long amount, IReadOnlyList<KeypadClick> clicks, Func<bool> current) => new()
        { Kind = InputActionKind.RestrictedAmountKeypad, KeypadClicks = clicks.ToArray(),
          AmountDigits = amount.ToString(System.Globalization.CultureInfo.InvariantCulture), DomainCurrent = current };

    public string Fingerprint => Kind switch
    {
        InputActionKind.MouseWheel => Prepare is { } p ? $"WHEEL:{WheelDelta}|PREPARE:{p.X},{p.Y}" : $"WHEEL:{WheelDelta}",
        InputActionKind.MouseHorizontalWheel => Prepare is { } q ? $"HWHEEL:{WheelDelta}|PREPARE:{q.X},{q.Y}" : $"HWHEEL:{WheelDelta}",
        InputActionKind.CursorMove => $"MOVE:{X},{Y}",
        InputActionKind.RestrictedLeftClick => $"DOMAIN_LEFT:{DomainPoint}:{DomainAbsoluteX},{DomainAbsoluteY}",
        InputActionKind.RestrictedAmountDigits => $"DOMAIN_AMOUNT:{AmountDigits}",
        InputActionKind.RestrictedAmountKeypad => $"DOMAIN_KEYPAD:{AmountDigits}:{string.Join(';', KeypadClicks ?? [])}",
        _ => "UNKNOWN",
    };

    public static InputAction Wheel(int delta) =>
        new() { Kind = InputActionKind.MouseWheel, WheelDelta = delta };

    public static InputAction WheelWithPrepare(int delta, int prepareX, int prepareY) =>
        new()
        {
            Kind = InputActionKind.MouseWheel,
            WheelDelta = delta,
            Prepare = new CursorPrepare(prepareX, prepareY),
        };

    public static InputAction HorizontalWheel(int delta) =>
        new() { Kind = InputActionKind.MouseHorizontalWheel, WheelDelta = delta };

    public static InputAction MoveTo(int x, int y) =>
        new() { Kind = InputActionKind.CursorMove, X = x, Y = y };
}

/// <summary>
/// Backend-neutral representation of one INPUT record. The raw backend converts
/// this into the Win32 <c>INPUT</c> struct; fakes count it without touching the OS.
/// </summary>
public readonly record struct InputRecord(
    uint Type,
    int Dx,
    int Dy,
    uint MouseData,
    uint Flags,
    ulong ExtraInfo);

/// <summary>Monotonic clock shared by every trace producer in this module.</summary>
public static class TraceClock
{
    private static readonly double TicksToNs = 1_000_000_000.0 / Stopwatch.Frequency;

    public static long NowNs() => (long)(Stopwatch.GetTimestamp() * TicksToNs);
}
