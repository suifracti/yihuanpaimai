using System.Runtime.InteropServices;
using NteHost.Input;
using NteHost.WindowMonitor;

namespace NteHost.DomainActions;

public sealed record ClientGeometry(int Width, int Height, int ScreenX, int ScreenY);
public sealed record VisibleControlAnchor(DomainPrimitive Primitive, int Left, int Top, int Width, int Height,
    ClientGeometry Geometry, string MatchId, long MatchGeneration, string ObservationSessionId,
    int Round, long FactsRevision, WindowBinding Window, long SourceSequence, long CapturedNs,
    bool SourceQualified, string EvidenceRef, string ControlProfile);

public interface IDomainControlEvidence
{
    string LastFailure => "UNREPORTED";
    IReadOnlyList<VisibleControlAnchor> AmountKeypad => [];
    // Detector reads ONLY this target's independent new capture, including ROI/geometry.
    // Null means not connected. No fixed game coordinates or dummy-profile fallback.
    VisibleControlAnchor? Locate(DomainPrimitive primitive, DomainIntent intent);
    AmountFieldReadback? CaptureAmountField();
}
public interface IExecutionObligationPort
{
    // Sol-B owns the sole durable book. A successful acknowledgement must mean
    // this exact immutable claim's attempted obligation was flushed before input.
    bool CommitBeforeInput(DomainIntent intent);
    bool CommitReceipt(DomainReceipt receipt);
}
public sealed class DelegatedExecutionObligationPort : IExecutionObligationPort
{
    private readonly Func<DomainIntent, bool> commitAttempted;
    private readonly Func<DomainReceipt, bool> commitReceipt;
    public DelegatedExecutionObligationPort(Func<DomainIntent, bool> commitAttempted,
        Func<DomainReceipt, bool> commitReceipt)
    { this.commitAttempted = commitAttempted; this.commitReceipt = commitReceipt; }
    public bool CommitBeforeInput(DomainIntent intent) => commitAttempted(intent);
    public bool CommitReceipt(DomainReceipt receipt) => commitReceipt(receipt);
}

/// <summary>Foreground-only closed OS adapter through the existing InputSafetyGuard.</summary>
public sealed class WindowsTicketedDomainBackend : ITicketedDomainBackend
{
    private readonly InputSafetyGuard guard;
    private readonly IDomainControlEvidence evidence;
    private readonly IExecutionObligationPort? obligations;
    private readonly Func<long> clock;
    private readonly WindowIdentityReader identities = new();
    private readonly Dictionary<string, DomainIntent> committed = new();
    private readonly object gate = new();
    private readonly bool allowGameInput;
    private readonly long inputTargetId;
    private long lastAmountMutationNs;
    private DomainIntent? amountIntent;
    private bool amountVerified;
    private Func<bool>? amountCurrent;
    public string LastReadbackReason { get; private set; } = "NOT_READ";
    private readonly HashSet<(string, DomainPrimitive)> attemptedPrimitives = new();
    private int fillAttempts;
    private VisibleControlAnchor? amountAnchor;
    private IReadOnlyList<VisibleControlAnchor> amountKeys = [];

    // allowGameInput must remain FALSE for offline integration. It is a second,
    // explicit operator gate; neither a READY intent nor a recognized ROI sets it.
    public WindowsTicketedDomainBackend(InputSafetyGuard guard, IDomainControlEvidence evidence,
        IExecutionObligationPort? obligations, Func<long> clock, long inputTargetId, bool allowGameInput = false)
    { this.guard = guard; this.evidence = evidence; this.obligations = obligations; this.clock = clock;
      this.inputTargetId = inputTargetId; this.allowGameInput = allowGameInput; }

    public PortOutcome Execute(DomainPrimitive primitive, DomainIntent intent, Func<bool> current)
    {
        lock (gate)
        {
            if (!Enum.IsDefined(primitive) || !KindAllows(intent.Kind, primitive)) return new(false, false, "PRIMITIVE_NOT_ALLOWED");
            if (attemptedPrimitives.Contains((intent.IntentId, primitive))
                && (primitive != DomainPrimitive.ReplaceAmountDigits || fillAttempts >= 2)) return new(false, false, "PRIMITIVE_ALREADY_ATTEMPTED");
            if (primitive == DomainPrimitive.ReplaceAmountDigits && !attemptedPrimitives.Contains((intent.IntentId, DomainPrimitive.FocusAmountField)))
                return new(false, false, "AMOUNT_FIELD_NOT_FOCUSED");
            if (primitive == DomainPrimitive.SubmitBid && (amountIntent != intent || !amountVerified))
                return new(false, false, "AMOUNT_FIELD_NOT_VERIFIED");
            if (intent.Amount is not (> 0 and <= 9_999_999) && intent.Kind == DomainActionKind.Bid)
                return new(false, false, "INVALID_AMOUNT");
            VisibleControlAnchor? anchor;
            try { anchor = primitive == DomainPrimitive.ReplaceAmountDigits && amountIntent == intent && amountAnchor is not null
                    ? amountAnchor : evidence.Locate(primitive, intent); } catch { anchor = null; }
            if (anchor == null) return new(false, false, "NOT_CONNECTED_CONTROL_ANCHOR_UNKNOWN:" + evidence.LastFailure);
            if (!AnchorMatches(anchor, primitive, intent)) return new(false, false, "CONTROL_NOT_FOUND_IN_TARGET");
            string validationFailure = "NONE";
            bool Valid()
            {
                if (!current()) { validationFailure = "CURRENT_CONTEXT_REJECTED"; return false; }
                if (inputTargetId == 0 || !guard.IsArmedFor(inputTargetId, intent.Window.FocusEpoch))
                { validationFailure = "GUARD_NOT_ARMED_FOR_TARGET"; return false; }
                if (!PlatformMatches(anchor, intent)) { validationFailure = "INITIAL_PLATFORM_CHANGED"; return false; }
                return true;

            }
            bool SafeValid() { try { return Valid(); } catch (Exception e) { validationFailure = "VALIDATION_EXCEPTION_" + e.GetType().Name; return false; } }
            if (!SafeValid()) return new(false, false, "DOMAIN_TARGET_CONTROL_OR_CURRENT_REJECTED:" + validationFailure);
            if (obligations == null) return new(false, false, "DURABLE_ATTEMPT_PORT_NOT_CONNECTED");
            if (committed.TryGetValue(intent.IntentId, out var previous) && previous != intent)
                return new(false, false, "DURABLE_INTENT_CONFLICT");
            if (!committed.ContainsKey(intent.IntentId) && (intent.Kind != DomainActionKind.Bid || primitive == DomainPrimitive.SubmitBid))
            {
                try
                {
                    if (!obligations.CommitBeforeInput(intent)) return new(false, false, "DURABLE_ATTEMPT_NOT_ACKNOWLEDGED");
                }
                catch { return new(false, false, "DURABLE_ATTEMPT_COMMIT_FAILED"); }
                committed.Add(intent.IntentId, intent);
            }
            PortOutcome Click(VisibleControlAnchor control, Func<bool> valid)
            {
                int x = control.Geometry.ScreenX + control.Left + control.Width / 2;
                int y = control.Geometry.ScreenY + control.Top + control.Height / 2;
                int vx = GetSystemMetrics(76), vy = GetSystemMetrics(77), vw = GetSystemMetrics(78), vh = GetSystemMetrics(79);
                if (vw <= 1 || vh <= 1 || x < vx || y < vy || x >= vx + vw || y >= vy + vh)
                    return new(false, false, "CONTROL_OUTSIDE_VIRTUAL_DESKTOP");
                // Pixel-center mapping is used so Windows' absolute move lands in
                // the exact pixel, including negative monitor coordinates.
                int ax = (int)(((long)(x - vx) * 65536 + 32768) / vw);
                int ay = (int)(((long)(y - vy) * 65536 + 32768) / vh);
                var sent = guard.Execute(InputAction.DomainClick(x, y, ax, ay, valid));
                return new(sent.SendCallCount > 0, sent.Ok, sent.Reason);
            }
            bool gameKeypad = anchor.ControlProfile == SceneAnchorGameDecoder.VerifiedGameProfile;
            // This game's amount panel is already a keypad, not a Windows edit.
            // Do not click a guessed "focus" point or type Ctrl+A into it.
            if (gameKeypad && primitive == DomainPrimitive.FocusAmountField)
            {
                attemptedPrimitives.Add((intent.IntentId, primitive));
                return new(false, true, "KEYPAD_ALREADY_OPEN");
            }
            PortOutcome result;
            if (gameKeypad && primitive == DomainPrimitive.ReplaceAmountDigits)
            {
                if (amountIntent != intent) { fillAttempts = 0; amountKeys = evidence.AmountKeypad.ToArray(); amountAnchor = anchor; }
                if (++fillAttempts > 2) return new(false, false, "AMOUNT_FILL_LIMIT");
                var keys = KeypadSequence(intent.Amount!.Value);
                var points = new List<KeypadClick>();
                int vx = GetSystemMetrics(76), vy = GetSystemMetrics(77), vw = GetSystemMetrics(78), vh = GetSystemMetrics(79);
                foreach (var key in keys)
                {
                    var control = amountKeys.SingleOrDefault(c => c.Primitive == key);
                    if (control is null || !AnchorMatches(control, key, intent))
                        return new(false, false, "KEYPAD_CONTROL_UNAVAILABLE:" + key);
                    int x = control.Geometry.ScreenX + control.Left + control.Width / 2;
                    int y = control.Geometry.ScreenY + control.Top + control.Height / 2;
                    if (vw <= 1 || vh <= 1 || x < vx || y < vy || x >= vx+vw || y >= vy+vh)
                        return new(false,false,"CONTROL_OUTSIDE_VIRTUAL_DESKTOP");
                    points.Add(new(x,y,(int)(((long)(x-vx)*65536+32768)/vw),(int)(((long)(y-vy)*65536+32768)/vh)));
                }
                var sent = guard.Execute(InputAction.DomainKeypad(intent.Amount.Value, points, SafeValid));
                result = new(sent.SendCallCount > 0, sent.Ok, sent.Reason);
            }
            else if (primitive == DomainPrimitive.ReplaceAmountDigits)
            {
                var sent = guard.Execute(InputAction.DomainAmount(intent.Amount!.Value, SafeValid));
                result = new(sent.SendCallCount > 0, sent.Ok, sent.Reason);
            }
            else result = Click(anchor, SafeValid);
            if (result.SideEffectAttempted) attemptedPrimitives.Add((intent.IntentId, primitive));
            if (primitive == DomainPrimitive.ReplaceAmountDigits && result.SideEffectAttempted)
            { lastAmountMutationNs = clock(); amountIntent = intent; amountVerified = false; amountCurrent = SafeValid; }
            return result;
        }
    }

    public static IReadOnlyList<DomainPrimitive> KeypadSequence(long amount)
    {
        if (amount is not (> 0 and <= 9_999_999)) return [];
        return new[] { DomainPrimitive.ClearAmount }.Concat(amount.ToString(System.Globalization.CultureInfo.InvariantCulture)
            .Select(c => (DomainPrimitive)((int)DomainPrimitive.AmountDigit0 + c - '0'))).ToArray();
    }

    public bool HasTimeToFillAndConfirm(DomainIntent intent) => !allowGameInput
        || intent.RoundDeadlineNs - clock() >= 6_000_000_000;
    public bool HasTimeToConfirm(DomainIntent intent) => !allowGameInput
        || intent.RoundDeadlineNs - clock() >= 3_000_000_000;

    public AmountFieldReadback? ReadAmountField()
    {
        lock (gate)
        {
            var i = amountIntent;
            amountVerified = false;
            if (i == null || amountCurrent == null) { LastReadbackReason = "NO_AMOUNT_MUTATION"; return null; }
            if (!amountCurrent()) { LastReadbackReason = "TARGET_IDENTITY_REJECTED"; return null; }
            var field = evidence.CaptureAmountField(); // exactly one post-fill read
            amountVerified = field is not null && field.Window == i.Window && field.Amount == i.Amount
                && field.CapturedNs > lastAmountMutationNs;
            LastReadbackReason = amountVerified ? "EXACT_AMOUNT_VISIBLE" : "AMOUNT_READBACK_MISMATCH";
            return field;
        }
    }

    private bool AnchorMatches(VisibleControlAnchor a, DomainPrimitive primitive, DomainIntent i)
    {
        return a.Primitive == primitive && a.Window == i.Window
            && !string.IsNullOrWhiteSpace(a.EvidenceRef) && a.Geometry.Width > 0 && a.Geometry.Height > 0
            && a.Width >= 3 && a.Height >= 3 && a.Left >= 0 && a.Top >= 0
            && a.Left + (long)a.Width <= a.Geometry.Width && a.Top + (long)a.Height <= a.Geometry.Height;
    }
    private bool PlatformMatches(VisibleControlAnchor a, DomainIntent i)
    {
        var identity = identities.Read(i.Window.Hwnd);
        if (identity.Pid != i.Window.Pid || identity.ProcessInstanceToken != i.Window.ProcessInstanceToken
            || !identity.IsVisible || GetForegroundWindow().ToInt64() != i.Window.Hwnd || IsIconic(new(i.Window.Hwnd))) return false;
        bool dummy = a.ControlProfile == "NTE_DOMAIN_DUMMY_V1" && identity.ClassName == "NteDomainDummyTarget"
            && identity.Pid == Environment.ProcessId;
        bool game = allowGameInput && a.ControlProfile == "NTE_VERIFIED_GAME_V1"
            && identity.ClassName == "UnrealWindow" && string.Equals(identity.ProcessImageName, "HTGame.exe", StringComparison.OrdinalIgnoreCase);
        if (!dummy && !game) return false;
        if (!GetClientRect(new(i.Window.Hwnd), out var r) || !ClientToScreen(new(i.Window.Hwnd), ref r.Origin)) return false;
        return r.Right == a.Geometry.Width && r.Bottom == a.Geometry.Height
            && r.Origin.X == a.Geometry.ScreenX && r.Origin.Y == a.Geometry.ScreenY;
    }
    private static bool KindAllows(DomainActionKind kind, DomainPrimitive primitive) => kind switch
    {
        DomainActionKind.Bid => primitive is DomainPrimitive.FocusAmountField or DomainPrimitive.ReplaceAmountDigits or DomainPrimitive.SubmitBid,
        DomainActionKind.ReturnLobby => primitive == DomainPrimitive.ReturnLobby,
        DomainActionKind.StartNextMatch => primitive == DomainPrimitive.StartNextMatch,
        _ when AuctionPreparation.IsPreparation(kind) => primitive.ToString() == kind.ToString(),
        _ => false,
    };
    [StructLayout(LayoutKind.Sequential)] private struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] private struct Rect { public Point Origin; public int Right, Bottom; }
    [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll")] private static extern bool ClientToScreen(IntPtr hwnd, ref Point point);
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern int GetSystemMetrics(int index);
}
