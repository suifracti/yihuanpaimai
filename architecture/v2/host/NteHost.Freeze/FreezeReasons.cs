using System;
using System.Collections.Generic;
using System.Linq;

namespace NteHost.Freeze;

/// <summary>
/// Canonical freeze reason vocabulary for the native scan-safety state machine.
///
/// PROVENANCE (see Evidence/2026-09-18-v2-2c-freeze-coordinator/python_contract_mapping.json):
///   - The four PYTHON_PARITY reasons are byte-identical to the string constants in
///     core/warehouse_active_scan_freeze.py (FREEZE_REASON_*). They are the only reasons
///     the Python component can express, and they are the only reasons exercised by the
///     differential/parity surface.
///   - The two NATIVE_EXTENSION reasons do not exist in Python at all. They are required
///     by the V2-2C CURRENT_SCOPE ("explicit freeze" and "generation/session changed"
///     plus "crash/restart/snapshot resync must not default to ALLOW"). They are therefore
///     recorded as CONTRACT_GAP-1/-5/-6 and must never be presented as Python-derived.
/// </summary>
public enum FreezeReason
{
    // ---- PYTHON_PARITY (must stay byte-identical to models in core/warehouse_active_scan_freeze.py) ----
    USER_KEYBOARD_INPUT,
    FOCUS_LOST,
    GAME_INTERACTION_CONFLICT,
    USER_TAKEOVER,

    // ---- NATIVE_EXTENSION (no Python counterpart; see CONTRACT_GAP-1 / -5 / -6) ----
    EXPLICIT_FREEZE,
    SESSION_UNVERIFIED,
}

public static class FreezeReasonCatalog
{
    /// <summary>Reasons the Python PRD-F component can express. Parity surface only.</summary>
    public static readonly IReadOnlyList<FreezeReason> PythonParity = new[]
    {
        FreezeReason.USER_KEYBOARD_INPUT,
        FreezeReason.FOCUS_LOST,
        FreezeReason.GAME_INTERACTION_CONFLICT,
        FreezeReason.USER_TAKEOVER,
    };

    /// <summary>Reasons with no Python counterpart.</summary>
    public static readonly IReadOnlyList<FreezeReason> NativeExtension = new[]
    {
        FreezeReason.EXPLICIT_FREEZE,
        FreezeReason.SESSION_UNVERIFIED,
    };

    public static readonly IReadOnlyList<FreezeReason> All =
        PythonParity.Concat(NativeExtension).ToArray();

    /// <summary>
    /// Python's own string literal for the reason, or null when the reason has no Python
    /// counterpart. Used by the parity harness so a rename in either language fails loudly.
    /// </summary>
    public static string? PythonLiteral(FreezeReason reason) => reason switch
    {
        FreezeReason.USER_KEYBOARD_INPUT => "USER_KEYBOARD_INPUT",
        FreezeReason.FOCUS_LOST => "FOCUS_LOST",
        FreezeReason.GAME_INTERACTION_CONFLICT => "GAME_INTERACTION_CONFLICT",
        FreezeReason.USER_TAKEOVER => "USER_TAKEOVER",
        _ => null,
    };

    public static bool IsPythonParity(FreezeReason reason) => PythonParity.Contains(reason);

    /// <summary>
    /// Fail-closed reason resolution. An unrecognised token is NOT silently reclassified
    /// into an existing reason (that is what Python does; see CONTRACT_GAP-4) — the caller
    /// must handle the null and deny the request.
    /// </summary>
    public static FreezeReason? TryParse(string? token)
    {
        if (string.IsNullOrWhiteSpace(token))
        {
            return null;
        }

        foreach (var reason in All)
        {
            if (string.Equals(reason.ToString(), token.Trim(), StringComparison.Ordinal))
            {
                return reason;
            }
        }

        return null;
    }
}
