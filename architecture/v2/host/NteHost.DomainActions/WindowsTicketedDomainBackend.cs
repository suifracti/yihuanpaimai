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
            if (attemptedPrimitives.Contains((intent.IntentId, primitive))) return new(false, false, "PRIMITIVE_ALREADY_ATTEMPTED");
            if (primitive == DomainPrimitive.ReplaceAmountDigits && !attemptedPrimitives.Contains((intent.IntentId, DomainPrimitive.FocusAmountField)))
                return new(false, false, "AMOUNT_FIELD_NOT_FOCUSED");
            if (primitive == DomainPrimitive.SubmitBid && (amountIntent != intent || !amountVerified))
                return new(false, false, "AMOUNT_FIELD_NOT_VERIFIED");
            if (intent.Amount is not (> 0 and <= 9_999_999) && intent.Kind == DomainActionKind.Bid)
                return new(false, false, "INVALID_AMOUNT");
            VisibleControlAnchor? anchor;
            try { anchor = evidence.Locate(primitive, intent); } catch { anchor = null; }
            if (anchor == null) return new(false, false, "NOT_CONNECTED_CONTROL_ANCHOR_UNKNOWN");
            if (!AnchorMatches(anchor, primitive, intent)) return new(false, false, "INITIAL_CONTROL_ANCHOR_UNQUALIFIED_OR_STALE");
            string validationFailure = "NONE";
            bool Valid()
            {
                if (!current()) { validationFailure = "CURRENT_CONTEXT_REJECTED"; return false; }
                if (inputTargetId == 0 || !guard.IsArmedFor(inputTargetId, intent.Window.FocusEpoch))
                { validationFailure = "GUARD_NOT_ARMED_FOR_TARGET"; return false; }
                if (!PlatformMatches(anchor, intent)) { validationFailure = "INITIAL_PLATFORM_CHANGED"; return false; }
                var latest = evidence.Locate(primitive, intent);
                // New frames are allowed, but the recognized control and geometry
                // must be identical. Drift after preflight never silently retargets.
                // The initial anchor fixes coordinates; its freshness was checked
                // at acquisition. Freshness at every use belongs to this independent
                // latest capture, not the initial image aging during current().
                bool controlsCurrent = latest != null && AnchorMatches(latest, primitive, intent)
                    && latest.Left == anchor.Left && latest.Top == anchor.Top && latest.Width == anchor.Width
                    && latest.Height == anchor.Height && latest.Geometry == anchor.Geometry
                    && latest.ControlProfile == anchor.ControlProfile && PlatformMatches(latest, intent);
                if (!controlsCurrent) { validationFailure = "LATEST_CONTROL_SCOPE_FRESHNESS_OR_GEOMETRY_REJECTED"; return false; }
                if (primitive != DomainPrimitive.SubmitBid) return true;
                // Re-read the exact field again at SubmitBid's final ticket check;
                // a prior successful read does not authorize a changed field.
                var field = evidence.CaptureAmountField(); long now = clock();
                return field != null && field.SourceQualified && field.Amount == intent.Amount
                    && field.CapturedNs > lastAmountMutationNs && field.CapturedNs <= now
                    && now - field.CapturedNs <= 500_000_000 && field.Window == intent.Window
                    && field.MatchId == intent.MatchId && field.MatchGeneration == intent.MatchGeneration
                    && field.ObservationSessionId == intent.ObservationSessionId && field.Round == intent.Round
                    && field.FactsRevision == intent.FactsRevision && field.TakeoverGeneration == intent.TakeoverGeneration
                    && PlatformMatches(latest!, intent);
            }
            bool SafeValid() { try { return Valid(); } catch (Exception e) { validationFailure = "VALIDATION_EXCEPTION_" + e.GetType().Name; return false; } }
            if (!SafeValid()) return new(false, false, "DOMAIN_TARGET_CONTROL_OR_CURRENT_REJECTED:" + validationFailure);
            if (obligations == null) return new(false, false, "DURABLE_ATTEMPT_PORT_NOT_CONNECTED");
            if (committed.TryGetValue(intent.IntentId, out var previous) && previous != intent)
                return new(false, false, "DURABLE_INTENT_CONFLICT");
            if (!committed.ContainsKey(intent.IntentId))
            {
                try
                {
                    if (!obligations.CommitBeforeInput(intent)) return new(false, false, "DURABLE_ATTEMPT_NOT_ACKNOWLEDGED");
                }
                catch { return new(false, false, "DURABLE_ATTEMPT_COMMIT_FAILED"); }
                committed.Add(intent.IntentId, intent);
            }
            InputAction action;
            if (primitive == DomainPrimitive.ReplaceAmountDigits)
                action = InputAction.DomainAmount(intent.Amount!.Value, SafeValid);
            else
            {
                int x = anchor.Geometry.ScreenX + anchor.Left + anchor.Width / 2;
                int y = anchor.Geometry.ScreenY + anchor.Top + anchor.Height / 2;
                int vx = GetSystemMetrics(76), vy = GetSystemMetrics(77), vw = GetSystemMetrics(78), vh = GetSystemMetrics(79);
                if (vw <= 1 || vh <= 1 || x < vx || y < vy || x >= vx + vw || y >= vy + vh)
                    return new(false, false, "CONTROL_OUTSIDE_VIRTUAL_DESKTOP");
                // Pixel-center mapping is used so Windows' absolute move lands in
                // the exact pixel, including negative monitor coordinates.
                int ax = (int)(((long)(x - vx) * 65536 + 32768) / vw);
                int ay = (int)(((long)(y - vy) * 65536 + 32768) / vh);
                action = InputAction.DomainClick(x, y, ax, ay, SafeValid);
            }
            var result = guard.Execute(action);
            if (result.SendCallCount > 0) attemptedPrimitives.Add((intent.IntentId, primitive));
            if (primitive == DomainPrimitive.ReplaceAmountDigits && result.SendCallCount > 0)
            { lastAmountMutationNs = clock(); amountIntent = intent; amountVerified = false; amountCurrent = SafeValid; }
            return new(result.SendCallCount > 0, result.Ok, result.Reason);
        }
    }

    public AmountFieldReadback? ReadAmountField()
    {
        // Independent capture after typing. A provider returning cached field
        // pixels before this mutation cannot unlock SubmitBid.
        lock (gate)
        {
            var i = amountIntent;
            amountVerified = false;
            if (i == null || amountCurrent == null) { LastReadbackReason = "NO_AMOUNT_MUTATION"; return null; }
            long readDeadline = Math.Min(i.DeadlineNs, clock() + 250_000_000);
            // SendInput's return precedes UI rendering. Read up to five independent
            // new frames; this retries OBSERVATION only, never any input primitive.
            for (int sample = 0; sample < 5 && clock() < readDeadline; sample++)
            {
                if (!amountCurrent()) { LastReadbackReason = "CURRENT_BEFORE_READ_REJECTED"; return null; }
                var field = evidence.CaptureAmountField(); long now = clock();
                if (!amountCurrent()) { LastReadbackReason = "CURRENT_AFTER_READ_REJECTED"; return null; }
                if (now >= readDeadline) { LastReadbackReason = "READ_DEADLINE_EXPIRED"; return null; }
                amountVerified = field != null && field.CapturedNs > lastAmountMutationNs
                    && field.SourceQualified && field.CapturedNs <= now && now - field.CapturedNs <= 500_000_000
                    && field.MatchId == i.MatchId && field.MatchGeneration == i.MatchGeneration
                    && field.ObservationSessionId == i.ObservationSessionId && field.Round == i.Round
                    && field.FactsRevision == i.FactsRevision && field.Window == i.Window
                    && field.TakeoverGeneration == i.TakeoverGeneration && field.Amount == i.Amount;
                LastReadbackReason = amountVerified ? "EXACT_FIELD_CONFIRMED" : $"FIELD_UNPROVEN:{field?.Amount}";
                if (amountVerified) return field;
                if (sample < 4) Thread.Sleep(40);
            }
            return null;
        }
    }

    private bool AnchorMatches(VisibleControlAnchor a, DomainPrimitive primitive, DomainIntent i)
    {
        long now = clock();
        return a.Primitive == primitive && a.MatchId == i.MatchId && a.MatchGeneration == i.MatchGeneration
            && a.ObservationSessionId == i.ObservationSessionId && a.Round == i.Round && a.FactsRevision == i.FactsRevision
            && a.Window == i.Window && a.SourceQualified && a.SourceSequence > 0 && a.CapturedNs > 0
            && a.CapturedNs <= now && now - a.CapturedNs <= 500_000_000 && now < i.DeadlineNs
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
