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
/// decision. No key codes, no scan codes, no typed text, no input history, and
/// no unbounded coordinate stream are retained anywhere in this module.
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
}

/// <summary>
/// The only actions this module is allowed to perform on the OS input stream.
/// Keyboard injection is intentionally absent: V2-2B never injects keys, and the
/// self-exemption ledger refuses to register key intents, so a key event can
/// never be exempted and therefore can never be hidden from the user.
/// </summary>
public enum InputActionKind
{
    MouseWheel,
    MouseHorizontalWheel,
    CursorMove,
}

/// <summary>
/// Optional cursor move performed *between* the two prechecks. This is the real
/// production shape of the operation (park the pointer on a known-safe point,
/// then scroll), and it is what opens the TOCTOU window that must fail closed.
/// </summary>
public readonly record struct CursorPrepare(int X, int Y);

public sealed record InputAction
{
    public required InputActionKind Kind { get; init; }
    public int WheelDelta { get; init; }
    public int X { get; init; }
    public int Y { get; init; }
    public CursorPrepare? Prepare { get; init; }

    public string Fingerprint => Kind switch
    {
        InputActionKind.MouseWheel => Prepare is { } p ? $"WHEEL:{WheelDelta}|PREPARE:{p.X},{p.Y}" : $"WHEEL:{WheelDelta}",
        InputActionKind.MouseHorizontalWheel => Prepare is { } q ? $"HWHEEL:{WheelDelta}|PREPARE:{q.X},{q.Y}" : $"HWHEEL:{WheelDelta}",
        InputActionKind.CursorMove => $"MOVE:{X},{Y}",
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
