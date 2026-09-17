using System;
using System.Collections.Generic;
using System.Linq;

namespace NteHost.Protocol;

public enum LifecycleState
{
    ENGINE_DOWN,
    STARTING,
    HANDSHAKING,
    SYNCING,
    READY,
    DEGRADED,
}

/// <summary>
/// Host-side mirror of models.py::LifecycleStateMachine. The transition table and
/// the READY gate are copied verbatim from the frozen contract; D05 asserts that
/// this table still matches the catalog's lifecycle document.
/// </summary>
public sealed class LifecycleStateMachine
{
    public static readonly IReadOnlyDictionary<LifecycleState, LifecycleState[]> ValidTransitions =
        new Dictionary<LifecycleState, LifecycleState[]>
        {
            [LifecycleState.ENGINE_DOWN] = new[] { LifecycleState.STARTING },
            [LifecycleState.STARTING] = new[] { LifecycleState.HANDSHAKING, LifecycleState.ENGINE_DOWN },
            [LifecycleState.HANDSHAKING] = new[] { LifecycleState.SYNCING, LifecycleState.READY, LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN },
            [LifecycleState.SYNCING] = new[] { LifecycleState.READY, LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN },
            [LifecycleState.READY] = new[] { LifecycleState.DEGRADED, LifecycleState.ENGINE_DOWN },
            [LifecycleState.DEGRADED] = new[] { LifecycleState.READY, LifecycleState.SYNCING, LifecycleState.ENGINE_DOWN },
        };

    public LifecycleState Current { get; private set; }
    public bool IsColdBoot { get; private set; }

    // READY gate inputs (lifecycle_recovery_v1.json -> readyGateRequirements.gates).
    public bool ProtocolNegotiated { get; set; }
    public bool CapabilitiesAccepted { get; set; }
    public bool EngineBusinessReady { get; set; }
    public bool SnapshotResynced { get; set; }
    public bool NoRecoverableBusinessState { get; set; }

    private readonly List<(string from, string to, string outcome)> _trace = new();
    public IReadOnlyList<(string from, string to, string outcome)> Trace => _trace;

    public LifecycleStateMachine(LifecycleState initial = LifecycleState.ENGINE_DOWN, bool isColdBoot = true)
    {
        Current = initial;
        IsColdBoot = isColdBoot;
    }

    public bool SnapshotRequirementSatisfied =>
        (IsColdBoot && NoRecoverableBusinessState) || SnapshotResynced;

    public bool AllReadyGatesSatisfied =>
        ProtocolNegotiated && CapabilitiesAccepted && EngineBusinessReady && SnapshotRequirementSatisfied;

    public LifecycleState TransitionTo(LifecycleState next)
    {
        var allowed = ValidTransitions[Current];
        if (!allowed.Contains(next))
        {
            _trace.Add((Current.ToString(), next.ToString(), "REJECTED"));
            throw new ProtocolViolationException(ErrorCodes.InvalidStateTransition,
                $"invalid lifecycle transition {Current} -> {next}; allowed: [{string.Join(", ", allowed.Select(s => s.ToString()))}]");
        }

        if (next == LifecycleState.READY)
        {
            if (Current == LifecycleState.HANDSHAKING)
            {
                if (!IsColdBoot)
                {
                    _trace.Add((Current.ToString(), next.ToString(), "REJECTED"));
                    throw new ProtocolViolationException(ErrorCodes.InvalidStateTransition,
                        "direct transition HANDSHAKING -> READY is forbidden on reconnect; SYNCING is mandatory");
                }
                if (!(NoRecoverableBusinessState && EngineBusinessReady))
                {
                    _trace.Add((Current.ToString(), next.ToString(), "REJECTED"));
                    throw new ProtocolViolationException(ErrorCodes.InvalidStateTransition,
                        "cold-boot HANDSHAKING -> READY requires noRecoverableBusinessState == true and engineBusinessReady == true");
                }
                if (!(ProtocolNegotiated && CapabilitiesAccepted))
                {
                    _trace.Add((Current.ToString(), next.ToString(), "REJECTED"));
                    throw new ProtocolViolationException(ErrorCodes.InvalidStateTransition,
                        "cold-boot HANDSHAKING -> READY requires protocolNegotiated and capabilitiesAccepted");
                }
            }
            else if (Current == LifecycleState.SYNCING)
            {
                if (!(EngineBusinessReady && SnapshotResynced))
                {
                    _trace.Add((Current.ToString(), next.ToString(), "REJECTED"));
                    throw new ProtocolViolationException(ErrorCodes.InvalidStateTransition,
                        "SYNCING -> READY requires a validated snapshot and businessReady == true");
                }
            }
            else if (Current == LifecycleState.DEGRADED)
            {
                if (!AllReadyGatesSatisfied)
                {
                    _trace.Add((Current.ToString(), next.ToString(), "REJECTED"));
                    throw new ProtocolViolationException(ErrorCodes.InvalidStateTransition,
                        "DEGRADED -> READY requires every READY gate to hold again");
                }
            }
        }

        if (Current == LifecycleState.READY &&
            (next == LifecycleState.DEGRADED || next == LifecycleState.ENGINE_DOWN))
        {
            IsColdBoot = false;
            SnapshotResynced = false;
        }

        _trace.Add((Current.ToString(), next.ToString(), "ACCEPTED"));
        Current = next;
        return Current;
    }

    /// <summary>Non-throwing probe used to prove a transition is rejected (T05).</summary>
    public bool TryTransitionTo(LifecycleState next, out string errorCode)
    {
        try
        {
            TransitionTo(next);
            errorCode = string.Empty;
            return true;
        }
        catch (ProtocolViolationException ex)
        {
            errorCode = ex.ErrorCode;
            return false;
        }
    }
}
