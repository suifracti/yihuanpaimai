using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;

namespace NteHost.Freeze;

public enum FreezeState
{
    ALLOW,
    FROZEN,
}

/// <summary>
/// V2-2C's transport-agnostic freeze coordinator.
///
/// The coordinator is the native safety state machine only. It has no Win32, hook,
/// SendInput, window or wheel-driver surface. The caller supplies the current C session
/// generation on every scan, reason-clear and rearm request. A rearm credential is opaque,
/// single-use, bound to this coordinator instance, the current generation and the current
/// freeze round. Clearing reasons never resumes scanning; explicit rearm is still required.
///
/// Scan submission has a deliberately small critical section: the permission check and the
/// scan commit happen together under _gate. A freeze that wins before that commit produces no
/// actuator call. A freeze that arrives after the commit is allowed to block subsequent work,
/// but cannot revoke the already committed operation. The fake verifier records the actuator
/// call separately, including callbacks that return null/throw.
/// </summary>
public sealed class FreezeCoordinator
{
    public const string NativeSchemaVersion = "v2.2c.native.freeze.coordinator.v2";
    public const string PythonContractSchemaVersion = "warehouse-active-scan-freeze.v2";

    private sealed class RearmCredential
    {
        public required long InstanceId { get; init; }
        public required long GenerationId { get; init; }
        public required long FreezeRound { get; init; }
        public bool Consumed { get; set; }
    }

    private static long _nextInstanceId;
    private readonly object _gate = new();
    private readonly long _instanceId = Interlocked.Increment(ref _nextInstanceId);
    private readonly List<FreezeReason> _reasons = new();
    private readonly FreezeTrace _trace = new();
    private readonly Dictionary<string, RearmCredential> _issuedTokens = new(StringComparer.Ordinal);
    private readonly HashSet<string> _retiredTokens = new(StringComparer.Ordinal);
    private readonly Action<FreezeReason>? _onFreezeHalt;

    private int _seq;
    private bool _awaitingRearm = true;
    private long _generation;
    private long _freezeRound;
    private long _credentialSequence;
    private string? _haltCallbackError;
    private bool _haltCallbackFailed;

    private int _scanRequestsAttempted;
    private int _scanRequestsDenied;
    private int _scanRequestsExecuted;
    private int _scanCommits;
    private int _actuatorInvocations;
    private int _actuatorFailures;
    private int _wheelEmissions;
    private string? _lastActuatorError;
    private int _rearmAppliedCount;
    private int _freezeTransitionsApplied;

    /// <param name="generationId">The C session identity for this coordinator.</param>
    /// <param name="onFreezeHalt">A fake or abstract halt sink; exceptions never unfreeze.</param>
    public FreezeCoordinator(long generationId = 1, Action<FreezeReason>? onFreezeHalt = null)
    {
        _generation = generationId;
        _onFreezeHalt = onFreezeHalt;
        _reasons.Add(FreezeReason.SESSION_UNVERIFIED);
    }

    // ------------------------------------------------------------------ state

    public long GenerationId
    {
        get { lock (_gate) return _generation; }
    }

    /// <summary>Stable textual spelling of the C session identity; not an A Generation.</summary>
    public string SessionId
    {
        get { lock (_gate) return SessionIdLocked; }
    }

    public long FreezeRound
    {
        get { lock (_gate) return _freezeRound; }
    }

    public bool AwaitingRearm
    {
        get { lock (_gate) return _awaitingRearm; }
    }

    public IReadOnlyList<FreezeReason> ActiveReasons
    {
        get { lock (_gate) return _reasons.ToArray(); }
    }

    public bool IsFrozen
    {
        get { lock (_gate) return IsFrozenLocked; }
    }

    public FreezeState State
    {
        get { lock (_gate) return StateLocked; }
    }

    public FreezeReason? PrimaryReason
    {
        get { lock (_gate) return PrimaryReasonLocked; }
    }

    public bool ScanPermitted
    {
        get { lock (_gate) return !IsFrozenLocked; }
    }

    public bool ProgressFrozen => IsFrozen;

    public bool HaltCallbackFailed
    {
        get { lock (_gate) return _haltCallbackFailed; }
    }

    public string? HaltCallbackError
    {
        get { lock (_gate) return _haltCallbackError; }
    }

    public int ScanRequestsAttempted
    {
        get { lock (_gate) return _scanRequestsAttempted; }
    }

    public int ScanRequestsDenied
    {
        get { lock (_gate) return _scanRequestsDenied; }
    }

    /// <summary>Count of requests that crossed the permission/commit boundary.</summary>
    public int ScanRequestsExecuted
    {
        get { lock (_gate) return _scanRequestsExecuted; }
    }

    public int ScanCommitCount
    {
        get { lock (_gate) return _scanCommits; }
    }

    /// <summary>Count of actual delegate invocation attempts, including a throwing delegate.</summary>
    public int ActuatorInvocationCount
    {
        get { lock (_gate) return _actuatorInvocations; }
    }

    public int ActuatorFailureCount
    {
        get { lock (_gate) return _actuatorFailures; }
    }

    /// <summary>Legacy name retained; it counts actual actuator invocation attempts.</summary>
    public int WheelEmissions
    {
        get { lock (_gate) return _wheelEmissions; }
    }

    public string? LastActuatorError
    {
        get { lock (_gate) return _lastActuatorError; }
    }

    public int RearmAppliedCount
    {
        get { lock (_gate) return _rearmAppliedCount; }
    }

    public int FreezeTransitionsApplied
    {
        get { lock (_gate) return _freezeTransitionsApplied; }
    }

    public FreezeTrace Trace => _trace;

    // ------------------------------------------------------------- reason set

    /// <summary>
    /// Add one independent reason. Repeating a reason is a recorded no-op. A new reason starts
    /// a new freeze round, invalidating credentials from the previous round.
    /// </summary>
    public bool Freeze(FreezeReason reason, string? detail = null)
    {
        lock (_gate)
        {
            var before = SnapshotLocked();
            var grew = !_reasons.Contains(reason);
            if (grew)
            {
                _reasons.Add(reason);
                _freezeRound++;
                _freezeTransitionsApplied++;
                InvokeHaltLocked(reason);
            }

            _awaitingRearm = true;
            RecordLocked(
                FreezeEventKind.ExplicitFreeze,
                applied: grew,
                before: before,
                reason: reason,
                outcome: grew ? "REASON_ADDED" : "ALREADY_ACTIVE",
                detail: detail);
            return grew;
        }
    }

    /// <summary>
    /// Release exactly one reason. The current generation is mandatory and release never
    /// resumes scanning by itself.
    /// </summary>
    public bool ClearReason(FreezeReason reason, long? generationId = null, string? detail = null)
    {
        lock (_gate)
        {
            var before = SnapshotLocked();
            if (generationId is null)
            {
                RecordLocked(FreezeEventKind.ReasonCleared, applied: false, before: before, reason: reason,
                    outcome: "REJECTED_MISSING_SESSION", detail: detail,
                    errorCode: FreezeErrorCodes.MissingSession);
                return false;
            }

            if (generationId.Value != _generation)
            {
                RecordLocked(FreezeEventKind.ReasonCleared, applied: false, before: before, reason: reason,
                    outcome: "REJECTED_STALE_GENERATION", detail: detail,
                    errorCode: FreezeErrorCodes.StaleGeneration);
                return false;
            }

            if (reason == FreezeReason.SESSION_UNVERIFIED)
            {
                RecordLocked(FreezeEventKind.ReasonCleared, applied: false, before: before, reason: reason,
                    outcome: "REJECTED_SESSION_VALIDATION_REQUIRED", detail: detail,
                    errorCode: FreezeErrorCodes.SessionValidationRequired);
                return false;
            }

            var removed = _reasons.Remove(reason);
            RecordLocked(FreezeEventKind.ReasonCleared, applied: removed, before: before, reason: reason,
                outcome: removed ? "REASON_RELEASED" : "REASON_NOT_ACTIVE", detail: detail);
            return removed;
        }
    }

    /// <summary>
    /// Explicitly validates the current C session and clears only SESSION_UNVERIFIED. The
    /// generation is mandatory and must equal the coordinator's current session identity;
    /// this is the only API that may release the session-verification reason.
    /// </summary>
    public bool ValidateCurrentSession(long? generationId = null, string? detail = null)
    {
        lock (_gate)
        {
            var before = SnapshotLocked();
            if (generationId is null)
            {
                RecordLocked(FreezeEventKind.SessionValidated, applied: false, before: before,
                    reason: FreezeReason.SESSION_UNVERIFIED, outcome: "REJECTED_MISSING_SESSION",
                    detail: detail, errorCode: FreezeErrorCodes.MissingSession);
                return false;
            }

            if (generationId.Value != _generation)
            {
                RecordLocked(FreezeEventKind.SessionValidated, applied: false, before: before,
                    reason: FreezeReason.SESSION_UNVERIFIED, outcome: "REJECTED_STALE_GENERATION",
                    detail: detail, errorCode: FreezeErrorCodes.StaleGeneration);
                return false;
            }

            var removed = _reasons.Remove(FreezeReason.SESSION_UNVERIFIED);
            RecordLocked(FreezeEventKind.SessionValidated, applied: removed, before: before,
                reason: FreezeReason.SESSION_UNVERIFIED,
                outcome: removed ? "CURRENT_SESSION_VALIDATED" : "SESSION_ALREADY_VALIDATED",
                detail: detail);
            return true;
        }
    }

    // ------------------------------------------------------------------ rearm

    /// <summary>
    /// Explicit recovery. Session identity and a current, opaque, single-use credential are
    /// mandatory even when the machine is already ALLOW. Credentials are consumed on APPLIED
    /// or ALREADY_ALLOW, and are never accepted after a session/round change.
    /// </summary>
    public RearmOutcome Rearm(
        bool manualRearmConfirmed,
        bool targetFocusValid,
        bool noGameConflict,
        bool noUserTakeoverActive,
        long? generationId = null,
        string? rearmToken = null,
        string? detail = null)
    {
        lock (_gate)
        {
            var before = SnapshotLocked();

            if (generationId is null)
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_MISSING_SESSION,
                    FreezeErrorCodes.MissingSession, detail);
            }

            if (generationId.Value != _generation)
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_STALE_GENERATION,
                    FreezeErrorCodes.StaleGeneration, detail);
            }

            if (string.IsNullOrWhiteSpace(rearmToken))
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_MISSING_TOKEN,
                    FreezeErrorCodes.MissingToken, detail);
            }

            if (_retiredTokens.Contains(rearmToken))
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_STALE_TOKEN,
                    FreezeErrorCodes.StaleToken, detail);
            }

            if (!_issuedTokens.TryGetValue(rearmToken, out var credential)
                || credential.InstanceId != _instanceId)
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_FOREIGN_TOKEN,
                    FreezeErrorCodes.ForeignToken, detail);
            }

            if (credential.Consumed)
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_REUSED_TOKEN,
                    FreezeErrorCodes.ReusedToken, detail);
            }

            if (credential.GenerationId != _generation)
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_STALE_GENERATION,
                    FreezeErrorCodes.StaleGeneration, detail);
            }

            if (credential.FreezeRound != _freezeRound)
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_EXPIRED_TOKEN,
                    FreezeErrorCodes.ExpiredToken, detail);
            }

            if (!(manualRearmConfirmed && targetFocusValid && noGameConflict && noUserTakeoverActive))
            {
                RecordLocked(FreezeEventKind.RearmRequest, applied: false, before: before,
                    outcome: RearmOutcome.REJECTED_CRITERIA.ToString(), detail: detail,
                    errorCode: FreezeErrorCodes.RearmCriteriaUnsatisfied);
                return RearmOutcome.REJECTED_CRITERIA;
            }

            if (_reasons.Contains(FreezeReason.SESSION_UNVERIFIED))
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_SESSION_UNVERIFIED,
                    FreezeErrorCodes.SessionUnverified, detail);
            }

            if (_reasons.Count > 0)
            {
                return RecordRearmRejectionLocked(
                    before, RearmOutcome.REJECTED_ACTIVE_REASONS,
                    FreezeErrorCodes.ActiveFreezeReasons, detail);
            }

            credential.Consumed = true;
            if (!IsFrozenLocked)
            {
                RecordLocked(FreezeEventKind.RearmRequest, applied: false, before: before,
                    outcome: RearmOutcome.ALREADY_ALLOW.ToString(), detail: detail);
                return RearmOutcome.ALREADY_ALLOW;
            }

            _awaitingRearm = false;
            _rearmAppliedCount++;
            _haltCallbackFailed = false;
            _haltCallbackError = null;

            RecordLocked(FreezeEventKind.RearmRequest, applied: true, before: before,
                outcome: RearmOutcome.APPLIED.ToString(), detail: detail);
            return RearmOutcome.APPLIED;
        }
    }

    /// <summary>Deprecated token-only interface. It never proves safety.</summary>
    public bool UnfreezeRearmed(string? armingToken) => false;

    /// <summary>Issue an opaque credential bound to the current C session and freeze round.</summary>
    public string IssueRearmToken(string nonce)
    {
        if (string.IsNullOrWhiteSpace(nonce))
        {
            throw new ArgumentException("credential nonce must be non-empty", nameof(nonce));
        }

        lock (_gate)
        {
            var sequence = ++_credentialSequence;
            var token = $"rearm-i{_instanceId}-g{_generation}-r{_freezeRound}-n{sequence}-{nonce}";
            _issuedTokens[token] = new RearmCredential
            {
                InstanceId = _instanceId,
                GenerationId = _generation,
                FreezeRound = _freezeRound,
            };
            return token;
        }
    }

    // ----------------------------------------------------- generation / resync

    /// <summary>Start a new C session. All old credentials are retired and the machine freezes.</summary>
    public void SessionChanged(long newGenerationId, string? detail = null)
    {
        lock (_gate)
        {
            var before = SnapshotLocked();
            RetireCredentialsLocked();
            _reasons.Clear();
            _generation = newGenerationId;
            _freezeRound++;
            _reasons.Add(FreezeReason.SESSION_UNVERIFIED);
            _awaitingRearm = true;
            _freezeTransitionsApplied++;
            InvokeHaltLocked(FreezeReason.SESSION_UNVERIFIED);

            RecordLocked(FreezeEventKind.SessionChanged, applied: true, before: before,
                outcome: "REASONS_RESET_AWAITING_REARM", detail: detail);
        }
    }

    /// <summary>
    /// A resync is always fail-closed. It retires credentials and starts a new freeze round,
    /// even when the supplied snapshot claims that it was not frozen.
    /// </summary>
    public void SnapshotResync(
        bool validated,
        bool? snapshotIsFrozen,
        IEnumerable<string>? snapshotReasons,
        string? detail = null)
    {
        lock (_gate)
        {
            var before = SnapshotLocked();
            RetireCredentialsLocked();
            _reasons.Clear();
            var unknownTokens = new List<string>();

            if (validated && snapshotReasons is not null)
            {
                foreach (var token in snapshotReasons)
                {
                    var parsed = FreezeReasonCatalog.TryParse(token);
                    if (parsed is null)
                    {
                        unknownTokens.Add(token);
                        continue;
                    }

                    if (!_reasons.Contains(parsed.Value))
                    {
                        _reasons.Add(parsed.Value);
                    }
                }
            }

            _reasons.Remove(FreezeReason.SESSION_UNVERIFIED);
            _reasons.Add(FreezeReason.SESSION_UNVERIFIED);
            _awaitingRearm = true;
            _freezeRound++;
            _freezeTransitionsApplied++;
            InvokeHaltLocked(FreezeReason.SESSION_UNVERIFIED);

            var outcome = validated
                ? (snapshotIsFrozen == true ? "RESYNC_FROZEN_FAIL_CLOSED" : "RESYNC_NOT_FROZEN_FORCED_FROZEN")
                : "RESYNC_UNVALIDATED_FORCED_FROZEN";

            RecordLocked(FreezeEventKind.SnapshotResync, applied: true, before: before, outcome: outcome,
                detail: unknownTokens.Count == 0
                    ? detail
                    : $"unknown snapshot reason tokens ignored: [{string.Join(", ", unknownTokens)}]; {detail}",
                errorCode: validated ? null : FreezeErrorCodes.SnapshotUnvalidated);
        }
    }

    // -------------------------------------------------------------- scan gate

    /// <summary>Precheck. Missing session identity is a refusal, not an implicit current session.</summary>
    public ScanDecision PrecheckScanRequest(long? generationId = null)
    {
        lock (_gate)
        {
            _scanRequestsAttempted++;
            var decision = EvaluateLocked(generationId);
            if (!decision.Permitted)
            {
                _scanRequestsDenied++;
            }

            return decision;
        }
    }

    /// <summary>
    /// The permission check and commit are atomic under _gate. The delegate is invoked only
    /// after commit and outside the gate, so a callback can re-enter the coordinator. A
    /// callback exception is reported as a post-commit actuator failure; it cannot roll back
    /// the commit or pretend that no invocation occurred.
    /// </summary>
    public bool ExecuteScrollRequest(Action<int> scrollFn, int delta, long? generationId = null)
    {
        ArgumentNullException.ThrowIfNull(scrollFn);

        lock (_gate)
        {
            _scanRequestsAttempted++;
            var decision = EvaluateLocked(generationId);
            if (!decision.Permitted)
            {
                _scanRequestsDenied++;
                return false;
            }

            _scanRequestsExecuted++;
            _scanCommits++;
        }

        lock (_gate)
        {
            _actuatorInvocations++;
            _wheelEmissions++;
        }

        try
        {
            scrollFn(delta);
            return true;
        }
        catch (Exception ex)
        {
            lock (_gate)
            {
                _actuatorFailures++;
                _lastActuatorError = $"{ex.GetType().Name}: {ex.Message}";
            }

            return false;
        }
    }

    public void AssertScanPermitted(long? generationId = null)
    {
        lock (_gate)
        {
            var decision = EvaluateLocked(generationId);
            if (!decision.Permitted)
            {
                throw new FreezeViolationException(
                    decision.DenialCode ?? FreezeErrorCodes.Frozen,
                    decision.DeniedBy?.ToString() ?? FreezeReason.SESSION_UNVERIFIED.ToString());
            }
        }
    }

    // -------------------------------------------------------------- diagnostics

    public Dictionary<string, object?> ToPayload()
    {
        lock (_gate)
        {
            return new Dictionary<string, object?>
            {
                ["schemaVersion"] = NativeSchemaVersion,
                ["pythonContractSchemaVersion"] = PythonContractSchemaVersion,
                ["instanceId"] = _instanceId,
                ["sessionId"] = SessionIdLocked,
                ["generationId"] = _generation,
                ["freezeRound"] = _freezeRound,
                ["state"] = StateLocked.ToString(),
                ["isFrozen"] = IsFrozenLocked,
                ["awaitingRearm"] = _awaitingRearm,
                ["activeReasons"] = _reasons.Select(FreezeNames.Of).ToArray(),
                ["primaryReason"] = PrimaryReasonLocked is null ? null : FreezeNames.Of(PrimaryReasonLocked.Value),
                ["scanPermitted"] = !IsFrozenLocked,
                ["progressFrozen"] = IsFrozenLocked,
                ["haltCallbackFailed"] = _haltCallbackFailed,
                ["haltCallbackError"] = _haltCallbackError,
                ["lastActuatorError"] = _lastActuatorError,
                ["scanMetrics"] = new Dictionary<string, int>
                {
                    ["attempted"] = _scanRequestsAttempted,
                    ["denied"] = _scanRequestsDenied,
                    ["executed"] = _scanRequestsExecuted,
                    ["commits"] = _scanCommits,
                    ["actuatorInvocations"] = _actuatorInvocations,
                    ["actuatorFailures"] = _actuatorFailures,
                    ["wheelEmissions"] = _wheelEmissions,
                },
                ["rearmAppliedCount"] = _rearmAppliedCount,
                ["freezeTransitionsApplied"] = _freezeTransitionsApplied,
                ["traceCount"] = _trace.Count,
            };
        }
    }

    // ------------------------------------------------------------------ helpers

    private string SessionIdLocked => $"c-session-g{_generation}";

    private bool IsFrozenLocked => _awaitingRearm || _reasons.Count > 0;

    private FreezeState StateLocked => IsFrozenLocked ? FreezeState.FROZEN : FreezeState.ALLOW;

    private FreezeReason? PrimaryReasonLocked => _reasons.Count == 0 ? null : _reasons[0];

    private void InvokeHaltLocked(FreezeReason reason)
    {
        if (_onFreezeHalt is null)
        {
            return;
        }

        try
        {
            _onFreezeHalt(reason);
            _haltCallbackFailed = false;
            _haltCallbackError = null;
        }
        catch (Exception ex)
        {
            _haltCallbackFailed = true;
            _haltCallbackError = $"{ex.GetType().Name}: {ex.Message}";
        }
    }

    private void RetireCredentialsLocked()
    {
        foreach (var token in _issuedTokens.Keys)
        {
            _retiredTokens.Add(token);
        }

        _issuedTokens.Clear();
    }

    private RearmOutcome RecordRearmRejectionLocked(
        (FreezeState State, List<FreezeReason> Reasons, long Generation) before,
        RearmOutcome outcome,
        string errorCode,
        string? detail)
    {
        RecordLocked(FreezeEventKind.RearmRequest, applied: false, before: before,
            outcome: outcome.ToString(), detail: detail, errorCode: errorCode);
        return outcome;
    }

    private ScanDecision EvaluateLocked(long? generationId)
    {
        if (generationId is null)
        {
            return new ScanDecision
            {
                Permitted = false,
                DeniedBy = null,
                ActiveReasons = _reasons.ToArray(),
                DenialCode = FreezeErrorCodes.MissingSession,
                StaleGeneration = false,
                WheelEmitted = false,
            };
        }

        if (generationId.Value != _generation)
        {
            return new ScanDecision
            {
                Permitted = false,
                DeniedBy = null,
                ActiveReasons = _reasons.ToArray(),
                DenialCode = FreezeErrorCodes.StaleGeneration,
                StaleGeneration = true,
                WheelEmitted = false,
            };
        }

        if (IsFrozenLocked)
        {
            return new ScanDecision
            {
                Permitted = false,
                DeniedBy = PrimaryReasonLocked,
                ActiveReasons = _reasons.ToArray(),
                DenialCode = FreezeErrorCodes.Frozen,
                StaleGeneration = false,
                WheelEmitted = false,
            };
        }

        return new ScanDecision
        {
            Permitted = true,
            ActiveReasons = Array.Empty<FreezeReason>(),
            WheelEmitted = false,
        };
    }

    private (FreezeState State, List<FreezeReason> Reasons, long Generation) SnapshotLocked() =>
        (StateLocked, _reasons.ToList(), _generation);

    private void RecordLocked(
        FreezeEventKind kind,
        bool applied,
        (FreezeState State, List<FreezeReason> Reasons, long Generation) before,
        FreezeReason? reason = null,
        string? outcome = null,
        string? detail = null,
        string? errorCode = null)
    {
        _trace.Append(
            seq: ++_seq,
            eventKind: kind,
            applied: applied,
            stateBefore: before.State,
            stateAfter: StateLocked,
            reasonsBefore: before.Reasons,
            reasonsAfter: _reasons,
            generationBefore: before.Generation,
            generationAfter: _generation,
            reason: reason,
            outcome: outcome,
            detail: detail,
            errorCode: errorCode);
    }
}

public static class FreezeErrorCodes
{
    public const string Frozen = "ERR_SCAN_FROZEN";
    public const string ActiveFreezeReasons = "ERR_ACTIVE_FREEZE_REASONS";
    public const string SessionUnverified = "ERR_SESSION_UNVERIFIED";
    public const string SessionValidationRequired = "ERR_SESSION_VALIDATION_REQUIRED";
    public const string MissingSession = "ERR_MISSING_SESSION";
    public const string StaleGeneration = "ERR_STALE_GENERATION";
    public const string MissingToken = "ERR_MISSING_REARM_TOKEN";
    public const string StaleToken = "ERR_STALE_REARM_TOKEN";
    public const string ExpiredToken = "ERR_EXPIRED_REARM_TOKEN";
    public const string ForeignToken = "ERR_FOREIGN_REARM_TOKEN";
    public const string ReusedToken = "ERR_REUSED_REARM_TOKEN";
    public const string RearmCriteriaUnsatisfied = "ERR_REARM_CRITERIA_UNSATISFIED";
    public const string SnapshotUnvalidated = "ERR_SNAPSHOT_UNVALIDATED";
    public const string ActuatorException = "ERR_ACTUATOR_EXCEPTION_AFTER_COMMIT";
}

public sealed class FreezeViolationException : Exception
{
    public FreezeViolationException(string errorCode, string reason)
        : base($"[{errorCode}] active scan is frozen: {reason}")
    {
        ErrorCode = errorCode;
        Reason = reason;
    }

    public string ErrorCode { get; }

    public string Reason { get; }
}
