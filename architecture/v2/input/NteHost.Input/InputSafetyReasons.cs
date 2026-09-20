namespace NteHost.Input;

/// <summary>
/// Every terminal reason this module can report. Reasons are stable strings so
/// they can be asserted on by machine from the verifier output and the raw
/// timeline without depending on enum ordinals.
/// </summary>
public static class InputSafetyReasons
{
    public const string Ok = "OK";

    // --- state machine ---
    public const string NotArmed = "NOT_ARMED";
    public const string AlreadyArmed = "ALREADY_ARMED";
    public const string GuardReleased = "GUARD_RELEASED";
    public const string Cancelled = "CANCELLED";
    public const string AlreadyCancelled = "ALREADY_CANCELLED";
    public const string AlreadyReleased = "ALREADY_RELEASED";

    // --- arm preconditions ---
    public const string ObserverNotRunning = "OBSERVER_NOT_RUNNING";
    public const string FocusSnapshotInvalid = "FOCUS_SNAPSHOT_INVALID";
    public const string TargetIdMismatch = "TARGET_ID_MISMATCH";
    public const string NotForeground = "NOT_FOREGROUND";
    public const string FocusEpochChanged = "FOCUS_EPOCH_CHANGED";

    // --- prepare ---
    public const string InvalidAction = "INVALID_ACTION";
    public const string CursorMoveNotApplied = "CURSOR_MOVE_NOT_APPLIED";

    // --- takeover classification ---
    public const string UserKeyDown = "USER_KEY_DOWN";
    public const string UserMouseButton = "USER_MOUSE_BUTTON";
    public const string UserMouseWheel = "USER_MOUSE_WHEEL";
    public const string UserMouseHorizontalWheel = "USER_MOUSE_HORIZONTAL_WHEEL";
    public const string UserMouseMove = "USER_MOUSE_MOVE";
    public const string UserInputUnknown = "USER_INPUT_UNKNOWN";

    // --- exemption ledger denial reasons ---
    public const string DenyNotInjected = "DENY_NOT_INJECTED";
    public const string DenyLowerIntegrityInjected = "DENY_LOWER_INTEGRITY_INJECTED";
    public const string DenyMarkerMismatch = "DENY_MARKER_MISMATCH";
    public const string DenyKindNeverExemptible = "DENY_KIND_NEVER_EXEMPTIBLE";
    public const string DenyNoPendingIntent = "DENY_NO_PENDING_INTENT";
    public const string DenyIntentExpired = "DENY_INTENT_EXPIRED";
    public const string DenyIntentAlreadyConsumed = "DENY_INTENT_ALREADY_CONSUMED";
    public const string DenyCoordinateMismatch = "DENY_COORDINATE_MISMATCH";
    public const string DenyBudgetExhausted = "DENY_EXEMPTION_BUDGET_EXHAUSTED";
    public const string DenyIntentAbandoned = "DENY_INTENT_ABANDONED";

    // --- executor ticket gate ---
    public const string TicketMissing = "EXECUTOR_TICKET_MISSING";
    public const string TicketExpired = "EXECUTOR_TICKET_EXPIRED";
    public const string TicketReused = "EXECUTOR_TICKET_REUSED";
    public const string TicketForeign = "EXECUTOR_TICKET_FOREIGN";
    public const string TicketActionMismatch = "EXECUTOR_TICKET_ACTION_MISMATCH";
    public const string TicketGuardNotArmed = "EXECUTOR_GUARD_NOT_ARMED";
    public const string BackendError = "BACKEND_ERROR";
    public const string SendInputPartial = "SENDINPUT_PARTIAL";

    // --- cursor restore ---
    public const string CursorRestoreUserTakeover = "CURSOR_RESTORE_SKIPPED_USER_TAKEOVER";
    public const string CursorRestoreNotMoved = "CURSOR_RESTORE_NOT_NEEDED";
    public const string CursorRestoreDisabled = "CURSOR_RESTORE_DISABLED";
    public const string CursorRestoreFailed = "CURSOR_RESTORE_FAILED";
    public const string CursorRestoreOk = "CURSOR_RESTORE_OK";
}

/// <summary>Stable timeline phase names, emitted into the raw NDJSON trace.</summary>
public static class TracePhase
{
    public const string ArmRequested = "ARM_REQUESTED";
    public const string ArmRejected = "ARM_REJECTED";
    public const string Armed = "ARMED";
    public const string Precheck1Begin = "PRECHECK_1_BEGIN";
    public const string Precheck1Pass = "PRECHECK_1_PASS";
    public const string Precheck1Fail = "PRECHECK_1_FAIL";
    public const string PrepareBegin = "PREPARE_BEGIN";
    public const string SelfIntentRegistered = "SELF_INTENT_REGISTERED";
    public const string PrepareAborted = "PREPARE_ABORTED";
    public const string PrepareDone = "PREPARE_DONE";
    public const string Precheck2Begin = "PRECHECK_2_BEGIN";
    public const string Precheck2Pass = "PRECHECK_2_PASS";
    public const string Precheck2Fail = "PRECHECK_2_FAIL";
    public const string TicketIssued = "TICKET_ISSUED";
    public const string TicketRejected = "TICKET_REJECTED";
    public const string SendInputInvoked = "SENDINPUT_INVOKED";
    public const string SendInputSkipped = "SENDINPUT_SKIPPED";
    public const string ObservedEvent = "OBSERVED_EVENT";
    public const string ObservedIgnoredUnarmed = "OBSERVED_IGNORED_UNARMED";
    public const string ExemptionGranted = "EXEMPTION_GRANTED";
    public const string ExemptionDenied = "EXEMPTION_DENIED";
    public const string Takeover = "TAKEOVER";
    public const string CancelRequested = "CANCEL_REQUESTED";
    public const string ReleaseBegin = "RELEASE_BEGIN";
    public const string CursorRestore = "CURSOR_RESTORE";
    public const string CursorRestoreSkipped = "CURSOR_RESTORE_SKIPPED";
    public const string CursorPrepareInvoked = "CURSOR_PREPARE_INVOKED";
    public const string ReleaseDone = "RELEASE_DONE";
}
