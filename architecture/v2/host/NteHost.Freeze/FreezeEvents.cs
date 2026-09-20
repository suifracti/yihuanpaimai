using System;
using System.Collections.Generic;
using System.Linq;

namespace NteHost.Freeze;

/// <summary>
/// Abstract event vocabulary consumed by <see cref="FreezeCoordinator"/>.
///
/// V2-2C is deliberately transport-agnostic: the coordinator NEVER touches Win32, hooks,
/// SendInput, window discovery or the wheel driver. Producers (V2-2A input/focus monitor,
/// V2-2B foreground supervisor, the Python engine, or a test) translate their own signals
/// into these events and feed them in. See CURRENT_SCOPE OUT_OF_SCOPE list.
/// </summary>
public enum FreezeEventKind
{
    /// <summary>Bidding round transition / auction prompt / modal dialog.</summary>
    BidActive,

    /// <summary>Soft keyboard (IME / on-screen keyboard) became active.</summary>
    SoftKeyboardActive,

    /// <summary>Target window lost foreground focus / minimised / obscured.</summary>
    ForegroundLost,

    /// <summary>User mouse interaction outside the scan region, or manual wheel input.</summary>
    UserTakeover,

    /// <summary>Explicit freeze request from the operator or a supervising component.</summary>
    ExplicitFreeze,

    /// <summary>Release exactly one freeze reason. The others stay in force.</summary>
    ReasonCleared,

    /// <summary>Session / generation changed; all previous reasons are discarded.</summary>
    SessionChanged,

    /// <summary>Current C session identity was explicitly validated.</summary>
    SessionValidated,

    /// <summary>State snapshot arrived after a crash / restart / reconnect.</summary>
    SnapshotResync,

    /// <summary>Explicit rearm / resume request. Must clear every Python rearm criterion.</summary>
    RearmRequest,

    /// <summary>An active scan / scroll request that must be gated by the invariant.</summary>
    ScanRequest,
}

/// <summary>
/// One abstract input event. A single flat shape is used so that the differential harness
/// can drive the Python reference and the native machine from the exact same JSON scenario.
/// </summary>
public sealed class FreezeEvent
{
    public FreezeEventKind Kind { get; init; }

    /// <summary>Reason carried by <see cref="FreezeEventKind.ReasonCleared"/> (raw token).</summary>
    public string? Reason { get; init; }

    /// <summary>Generation the producer believes is current. Null is rejected by safety gates.</summary>
    public long? GenerationId { get; init; }

    /// <summary>Free-text provenance for the trace (never used for control flow).</summary>
    public string? Detail { get; init; }

    // ---- RearmRequest criteria (strict booleans, mirroring the Python keyword-only args) ----
    public bool ManualRearmConfirmed { get; init; }
    public bool TargetFocusValid { get; init; }
    public bool NoGameConflict { get; init; }
    public bool NoUserTakeoverActive { get; init; }

    /// <summary>
    /// Opaque rearm credential bound to the current coordinator instance, generation and
    /// freeze round. It is single-use; the verifier never treats its text as provenance.
    /// </summary>
    public string? RearmToken { get; init; }

    // ---- SnapshotResync payload ----
    /// <summary>Whether the snapshot claims the coordinator was frozen.</summary>
    public bool? SnapshotIsFrozen { get; init; }

    /// <summary>Reasons the snapshot claims were active (raw tokens).</summary>
    public IReadOnlyList<string>? SnapshotReasons { get; init; }

    /// <summary>Whether the snapshot itself passed integrity validation.</summary>
    public bool SnapshotValidated { get; init; }

    public static FreezeEvent Of(FreezeEventKind kind, string? reason = null, long? generationId = null) =>
        new() { Kind = kind, Reason = reason, GenerationId = generationId };
}

/// <summary>Why a scan / scroll request was refused, or that it was allowed.</summary>
public sealed class ScanDecision
{
    public bool Permitted { get; init; }

    /// <summary>One reason that denies the request. Null when permitted.</summary>
    public FreezeReason? DeniedBy { get; init; }

    /// <summary>Every reason in force at decision time (ordered, deterministic).</summary>
    public IReadOnlyList<FreezeReason> ActiveReasons { get; init; } = Array.Empty<FreezeReason>();

    /// <summary>Machine-readable denial code, null when permitted.</summary>
    public string? DenialCode { get; init; }

    /// <summary>True when the request was refused because its generation was stale.</summary>
    public bool StaleGeneration { get; init; }

    public bool WheelEmitted { get; init; }
}

public enum RearmOutcome
{
    APPLIED,
    ALREADY_ALLOW,
    REJECTED_CRITERIA,
    REJECTED_ACTIVE_REASONS,
    REJECTED_SESSION_UNVERIFIED,
    REJECTED_MISSING_SESSION,
    REJECTED_STALE_GENERATION,
    REJECTED_STALE_TOKEN,
    REJECTED_EXPIRED_TOKEN,
    REJECTED_FOREIGN_TOKEN,
    REJECTED_REUSED_TOKEN,
    REJECTED_MISSING_TOKEN,
}
