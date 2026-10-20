using NteHost.DomainActions;
using System.Text.Json;
using System.Text.Json.Serialization;

// Fake-only: no Win32 backend, hook, window, mouse or keyboard is constructed.
sealed class FakePort : IRestrictedDomainInputPort
{
    public int Sends;
    public bool Partial;
    public bool Throw;
    public Action? BetweenPrechecks;
    public PortOutcome TrySend(DomainIntent intent, Func<bool> current)
    {
        if (!current()) return new(false, false, "PRECHECK_REJECTED");
        BetweenPrechecks?.Invoke();
        if (!current()) return new(false, false, "FINAL_PRECHECK_REJECTED");
        Sends++;
        if (Throw) throw new InvalidOperationException();
        return new(true, !Partial, Partial ? "PARTIAL_SEND" : "OS_ACCEPTED_WAIT_FOR_VISIBLE_RESULT");
    }
}
sealed class Fixture
{
    public long Now = 1_000_000_000;
    public WindowBinding Window = new(10, 20, 30, 40);
    public ActionScope Scope;
    public FakePort Port = new();
    public DomainActionCoordinator Coordinator;
    public Fixture(bool executionPort = true)
    {
        Scope = new("match-1", 1, 7, 1000, 800, "AUCTION", "lease-1", Now + 900_000_000,
            Window, 2, 10, Now - 10_000_000, true, true, true, true, false, false)
            { MatchGeneration = 1, ObservationSessionId = "obs-1", ApprovalId = "test-approval" };
        Coordinator = new(() => Scope, () => Now, executionPort ? Port : null);
    }
    public DomainIntent Intent(string id = "bid-1", DomainActionKind kind = DomainActionKind.Bid) =>
        new(id, kind, Scope.MatchId, Scope.Round, Scope.FactsRevision,
            kind == DomainActionKind.Bid ? 500 : null, Scope.Budget, Now + 500_000_000,
            Scope.TakeoverGeneration, Scope.LeaseId, Window)
            { MatchGeneration = Scope.MatchGeneration, ObservationSessionId = Scope.ObservationSessionId, MaxSafeBid = 800, ApprovalId = Scope.ApprovalId };
    public VisibleResult Evidence(DomainIntent i, string scene = "AUCTION", string? newMatch = null)
    {
        Now += 10_000_000;
        Scope = Scope with { SourceSequence = Scope.SourceSequence + 1, CapturedNs = Now };
        return new(i.IntentId, i.Kind, i.MatchId, i.Round, i.FactsRevision, i.Amount, newMatch,
            scene, Scope.SourceSequence, Now, true, Window, i.TakeoverGeneration)
            { OriginMatchGeneration = i.MatchGeneration, ObservationSessionId = i.ObservationSessionId,
                NewMatchGeneration = newMatch == null ? 0 : i.MatchGeneration + 1 };
    }
}
sealed class FakeTicketBackend : ITicketedDomainBackend
{
    public readonly List<DomainPrimitive> Operations = new();
    public Func<AmountFieldReadback?> Read = () => null;
    public Action<DomainPrimitive>? BeforeCommit;
    public PortOutcome Execute(DomainPrimitive primitive, DomainIntent intent, Func<bool> current)
    {
        BeforeCommit?.Invoke(primitive);
        if (!current()) return new(false, false, "TICKET_FINAL_GATE_REJECTED");
        Operations.Add(primitive);
        return new(true, true, "OS_ACCEPTED");
    }
    public AmountFieldReadback? ReadAmountField() => Read();
}
static class Program
{
    static int cases;
    static void Require(bool value, string reason) { if (!value) throw new Exception(reason); }
    static void Case(string name, Action action) { action(); cases++; Console.WriteLine("PASS " + name); }
    static void Main(string[] args)
    {
        if (args.Contains("--preparation-only")) { PreparationChecks.Run(args.LastOrDefault()); return; }
        if (args.Contains("--input-source-only")) { InputCaptureChecks.Run(); return; }
        if (args.Contains("--input-future-only")) { InputCaptureChecks.RunFuture(); return; }
        if (args.Contains("--cross-process-dummy-host")) { WindowsBackendChecks.RunCrossProcessHost(); return; }
        if (args.Contains("--ack-timeout-dummy")) { WindowsBackendChecks.RunAckTimeoutDummy(); return; }
        if (args.Contains("--dummy-window")) { WindowsBackendChecks.Run(); return; }
        Case("default execution OFF", () => {
            var f = new Fixture(false); Require(f.Coordinator.Dispatch(f.Intent()).Status == ReceiptStatus.NOT_SENT, "OFF");
            Require(f.Port.Sends == 0, "NO_INPUT");
        });
        Case("window identity and bounded amount", () => {
            foreach (var change in new Func<ActionScope, ActionScope>[] {
                s => s with { ForegroundMatches = false },
                s => s with { Window = s.Window with { ProcessInstanceToken = 31 } } }) {
                var f = new Fixture(); var i = f.Intent(); f.Scope = change(f.Scope);
                Require(f.Coordinator.Dispatch(i).Status == ReceiptStatus.NOT_SENT && f.Port.Sends == 0, "WRONG_WINDOW");
            }
            foreach (long amount in new long[] { -1, 0, 801, 1001, 10_000_000 }) {
                var f = new Fixture(); Require(f.Coordinator.Dispatch(f.Intent() with { Amount = amount }).Status == ReceiptStatus.NOT_SENT, "AMOUNT_BOUND");
            }
        });
        Case("target changes between prechecks prevent send", () => {
            var f = new Fixture(); f.Port.BetweenPrechecks = () => f.Scope = f.Scope with { Window = f.Scope.Window with { Pid = 999 } };
            Require(f.Coordinator.Dispatch(f.Intent()).Status == ReceiptStatus.NOT_SENT && f.Port.Sends == 0, "FINAL_GATE");
        });
        Case("bounded bid primitives require new exact field readback before submit", () => {
            foreach (bool valid in new[] { false, true }) {
                var f = new Fixture(); var i = f.Intent(); var backend = new FakeTicketBackend();
                backend.Read = () => { f.Now += 1; return new(valid ? 500 : 499, i.MatchId, 1, 7,
                    i.Window, 2, f.Now, true) { MatchGeneration = 1, ObservationSessionId = "obs-1" }; };
                var coordinator = new DomainActionCoordinator(() => f.Scope, () => f.Now,
                    new RestrictedDomainInputPort(backend, () => f.Now));
                var result = coordinator.Dispatch(i);
                Require(result.Status == (valid ? ReceiptStatus.SENT_PENDING_CONFIRMATION : ReceiptStatus.UNKNOWN), "FIELD_CONFIRMATION");
                Require(backend.Operations.SequenceEqual(valid ? new[] { DomainPrimitive.FocusAmountField,
                    DomainPrimitive.ReplaceAmountDigits, DomainPrimitive.SubmitBid } : new[] {
                    DomainPrimitive.FocusAmountField, DomainPrimitive.ReplaceAmountDigits }), "CLOSED_SEQUENCE");
            }
        });
        Case("window changes after field focus stop before amount and cannot retry", () => {
            var f = new Fixture(); var i = f.Intent(); var backend = new FakeTicketBackend();
            backend.BeforeCommit = primitive => { if (primitive == DomainPrimitive.ReplaceAmountDigits)
                f.Scope = f.Scope with { Window = f.Scope.Window with { Pid = 999 } }; };
            var coordinator = new DomainActionCoordinator(() => f.Scope, () => f.Now,
                new RestrictedDomainInputPort(backend, () => f.Now));
            Require(coordinator.Dispatch(i).Status == ReceiptStatus.UNKNOWN, "FOCUS_SIDE_EFFECT_UNKNOWN");
            Require(backend.Operations.SequenceEqual(new[] { DomainPrimitive.FocusAmountField }), "NO_AMOUNT_AFTER_TAKEOVER");
            Require(coordinator.Dispatch(i with { IntentId = "retry" }).Status == ReceiptStatus.NOT_SENT, "NO_RETRY");
        });
        Case("OS acceptance pending; only own later visible amount confirms", () => {
            var f = new Fixture(); var i = f.Intent(); var sent = f.Coordinator.Dispatch(i);
            Require(sent.Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "SEND_IS_NOT_ACCEPTANCE");
            var evidence = f.Evidence(i);
            foreach (var bad in new[] { evidence with { AcceptedOwnAmount = 499 }, evidence with { OriginMatchId = "other" },
                evidence with { OriginFactsRevision = 8 },
                evidence with { CapturedNs = sent.SentNs },
                evidence with { Window = f.Window with { Pid = 21 } } })
                Require(f.Coordinator.Confirm(bad).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "UNRELATED_RESULT_CONFIRMED");
            Require(f.Coordinator.Confirm(evidence).Status == ReceiptStatus.CONFIRMED, "VISIBLE_CONFIRMATION");
            Require(f.Coordinator.Dispatch(i).Status == ReceiptStatus.CONFIRMED && f.Port.Sends == 1, "IDEMPOTENT");
            Require(f.Coordinator.Dispatch(i with { IntentId = "new-id" }).Status == ReceiptStatus.NOT_SENT && f.Port.Sends == 1, "ROUND_RESEND");
        });
        Case("current read may finish a new capture before confirmation comparison", () => {
            var f = new Fixture();
            f.Coordinator = new(() => { f.Now += 1; f.Scope = f.Scope with { CapturedNs = f.Now }; return f.Scope; },
                () => f.Now, f.Port);
            var i = f.Intent(); Require(f.Coordinator.Dispatch(i).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "DISPATCH");
            var evidence = f.Evidence(i);
            Require(f.Coordinator.Confirm(evidence).Status == ReceiptStatus.CONFIRMED, "POST_READ_CLOCK_REQUIRED");
        });
        Case("partial or throwing backend UNKNOWN and globally no resend", () => {
            foreach (bool throws in new[] { false, true }) {
                var f = new Fixture(); f.Port.Partial = !throws; f.Port.Throw = throws; var i = f.Intent();
                Require(f.Coordinator.Dispatch(i).Status == ReceiptStatus.UNKNOWN, "PARTIAL_UNKNOWN");
                f.Port.Partial = false; f.Port.Throw = false;
                Require(f.Coordinator.Dispatch(i with { IntentId = "retry" }).Status == ReceiptStatus.NOT_SENT && f.Port.Sends == 1, "UNKNOWN_RESEND");
            }
        });
        Case("3 second confirmation timeout or changed target becomes UNKNOWN", () => {
            foreach (bool changed in new[] { false, true }) {
                var f = new Fixture(); var i = f.Intent(); var sent = f.Coordinator.Dispatch(i);
                if (changed) f.Scope = f.Scope with { Window = f.Window with { Pid = 999 } };
                else f.Now = sent.SentNs + 3_000_000_000;
                Require(f.Coordinator.Poll()!.Status == ReceiptStatus.UNKNOWN, "PENDING_STOP");
                Require(f.Coordinator.Dispatch(i with { IntentId = "retry" }).Status == ReceiptStatus.NOT_SENT && f.Port.Sends == 1, "NO_RESEND");
            }
        });
        Case("one match through archive/lobby/next admission; receipts exported", () => {
            var f = new Fixture(); var workflow = new List<DomainReceipt>();
            var backend = new FakeTicketBackend();
            backend.Read = () => { f.Now += 1; return new(500, "match-1", 1, 7, f.Window, 2, f.Now, true)
                { MatchGeneration = 1, ObservationSessionId = "obs-1" }; };
            f.Coordinator = new DomainActionCoordinator(() => f.Scope, () => f.Now,
                new RestrictedDomainInputPort(backend, () => f.Now));
            var bid = f.Intent(); workflow.Add(f.Coordinator.Dispatch(bid)); workflow.Add(f.Coordinator.Confirm(f.Evidence(bid)));
            f.Scope = f.Scope with { Scene = "SETTLEMENT", Round = 5 };
            var exit = f.Intent("return-1", DomainActionKind.ReturnLobby);
            Require(f.Coordinator.Dispatch(exit).Status == ReceiptStatus.NOT_SENT, "ARCHIVE_REQUIRED");
            f.Scope = f.Scope with { SettlementArchived = true };
            workflow.Add(f.Coordinator.Dispatch(exit)); workflow.Add(f.Coordinator.Confirm(f.Evidence(exit, "LOBBY")));
            f.Scope = f.Scope with { Scene = "LOBBY", Round = 0 };
            var start = f.Intent("start-1", DomainActionKind.StartNextMatch);
            Require(f.Coordinator.Dispatch(start).Status == ReceiptStatus.NOT_SENT, "EXPLICIT_ADMISSION_REQUIRED");
            f.Scope = f.Scope with { NewMatchAdmission = true };
            workflow.Add(f.Coordinator.Dispatch(start));
            Require(f.Coordinator.Confirm(f.Evidence(start, "LOADING", "match-2")).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "LOADING_NOT_NEW_MATCH");
            workflow.Add(f.Coordinator.Confirm(f.Evidence(start, "AUCTION_R1", "match-2")));
            Require(workflow.Last().Status == ReceiptStatus.CONFIRMED && backend.Operations.SequenceEqual(new[] {
                DomainPrimitive.FocusAmountField, DomainPrimitive.ReplaceAmountDigits, DomainPrimitive.SubmitBid,
                DomainPrimitive.ReturnLobby, DomainPrimitive.StartNextMatch }), "NEW_MATCH_CONFIRMATION");
            if (args.Length == 1) {
                var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
                options.Converters.Add(new JsonStringEnumConverter());
                File.WriteAllText(args[0], JsonSerializer.Serialize(workflow, options));
            }
        });
        Case("scene anchors locate the published controls and stay disconnected without the operator gate", () => {
            Require(!SceneAnchorGameDecoder.OperatorAllowsGameInput(null)
                && !SceneAnchorGameDecoder.OperatorAllowsGameInput("true")
                && !SceneAnchorGameDecoder.OperatorAllowsGameInput("0")
                && SceneAnchorGameDecoder.OperatorAllowsGameInput("1"), "OPERATOR_GATE");
            var directory = AnchorDirectory();
            var decoder = SceneAnchorGameDecoder.Load(directory);
            Require(decoder.Ready, "ANCHOR_CATALOG");
            Require(!SceneAnchorGameDecoder.Load(Path.Combine(directory, "missing")).Ready, "MISSING_CATALOG_STAYS_DISCONNECTED");
            const int width = 1920, height = 1080;
            NativeDomainFrame Blank(string scene, int round)
            {
                var window = new WindowBinding(1, 2, 3, 0);
                var scope = new ActionScope("anchor-match", round, 1, 100, 100, scene, "lease", 2_000_000_000,
                    window, 1, 7, 1_000_000_000, true, true, true, true, false, false)
                    { MatchGeneration = 4, ObservationSessionId = "anchor-obs", ApprovalId = "anchor-approval" };
                return new(scope, new(width, height, 0, 0), new byte[width * height * 4], width * 4);
            }
            SceneAnchorGameDecoder.GrayImage RequireTemplate(string name)
            {
                Require(decoder.TryGetTemplate(name, out var image), "TEMPLATE " + name);
                return image;
            }
            var exit = RequireTemplate("settlement_exit_label.png");
            var sale = RequireTemplate("settlement_sale_label.png");
            var confirm = RequireTemplate("bid_confirm_label.png");
            var start = RequireTemplate("lobby_start_label.png");
            var exitOnly = Blank("SETTLEMENT", 5);
            var exitPixels = exitOnly.Pixels.ToArray();
            SceneAnchorGameDecoder.PaintGray(exitPixels, exitOnly.Stride, 1675, 977, exit);
            Require(decoder.Decode(new NativeDomainFrame(exitOnly.Scope, exitOnly.Geometry, exitPixels, exitOnly.Stride)) is null,
                "EXIT_WITHOUT_SALE_WITNESS");
            var settlementPixels = exitPixels.ToArray();
            SceneAnchorGameDecoder.PaintGray(settlementPixels, exitOnly.Stride, 1328, 851, sale);
            var settlement = decoder.Decode(new NativeDomainFrame(exitOnly.Scope, exitOnly.Geometry, settlementPixels, exitOnly.Stride));
            var back = settlement?.Controls.SingleOrDefault(control => control.Primitive == DomainPrimitive.ReturnLobby);
            Require(settlement?.Scene == "SETTLEMENT" && back is { Left: 1675, Top: 977, Width: 52, Height: 30 }
                && back.ControlProfile == SceneAnchorGameDecoder.VerifiedGameProfile, "RETURN_ANCHOR " + back);
            var bidPixels = new byte[width * height * 4];
            SceneAnchorGameDecoder.PaintGray(bidPixels, width * 4, 1189, 926, confirm);
            var digit = new SceneAnchorGameDecoder.GrayImage(Enumerable.Repeat((byte)255, 20 * 30).ToArray(), 20, 30);
            SceneAnchorGameDecoder.PaintGray(bidPixels, width * 4, 1300, 710, digit);
            var bidFrame = Blank("AUCTION", 1);
            var bid = decoder.Decode(new NativeDomainFrame(bidFrame.Scope, bidFrame.Geometry, bidPixels, bidFrame.Stride));
            var submit = bid?.Controls.Single(control => control.Primitive == DomainPrimitive.SubmitBid);
            var focus = bid?.Controls.Single(control => control.Primitive == DomainPrimitive.FocusAmountField);
            Require(bid?.Scene == "AUCTION" && submit is { Left: 1189, Top: 926 }
                && submit.Left + submit.Width / 2 > (883 + 1459) / 2 + 40, "CONFIRM_NOT_CLEAR_BUTTON");
            Require(focus is { Left: 1139, Top: 701, Width: 370, Height: 50 }, "AMOUNT_LINE_EXCLUDES_ALLOWED_RANGE " + focus);
            var lobbyPixels = new byte[width * height * 4];
            SceneAnchorGameDecoder.PaintGray(lobbyPixels, width * 4, 1208, 961, start);
            var lobbyFrame = Blank("LOBBY", 0);
            var lobby = decoder.Decode(new NativeDomainFrame(lobbyFrame.Scope, lobbyFrame.Geometry, lobbyPixels, lobbyFrame.Stride));
            var next = lobby?.Controls.SingleOrDefault(control => control.Primitive == DomainPrimitive.StartNextMatch);
            Require(lobby?.Scene == "LOBBY" && next is { Left: 1208, Top: 961 }
                && !lobby.Controls.Any(control => control.Primitive == DomainPrimitive.ReturnLobby), "START_ANCHOR");
            var closed = new byte[width * height * 4];
            for (int y = 200; y < 700; y += 2)
                for (int x = 40; x < 500; x += 2)
                {
                    int pixel = (y * width + x) * 4;
                    closed[pixel] = closed[pixel + 1] = closed[pixel + 2] = 220;
                }
            int readX = -1, readY = -1, readW = -1, readH = -1;
            decoder.ReadCommittedAmount = (_, _, _, _, x, y, w, h) =>
            {
                readX = x; readY = y; readW = w; readH = h; return 300000;
            };
            var closedFrame = Blank("AUCTION", 1);
            var closedView = decoder.Decode(new NativeDomainFrame(closedFrame.Scope, closedFrame.Geometry, closed, closedFrame.Stride));
            Require(closedView?.Scene == "AUCTION_R1" && closedView.OwnBid?.Amount == 300000
                && readX == 1382 && readY == 864 && readW == 1901 - 1382 && readH == 1069 - 864
                && readX + readW <= width && readY + readH <= height, "COMMITTED_SEARCH_BOX " + readX + "," + readY + " " + readW + "x" + readH);
            decoder.ReadCommittedAmount = null;
            Require(decoder.Decode(Blank("AUCTION", 1)) is null, "BLANK_FRAME_STAYS_UNCONNECTED");
        });
        ReceiptPathChecks.Run();
        Console.WriteLine($"PASS {cases} scenarios (fake input only)");
    }

    static string AnchorDirectory()
    {
        foreach (var start in new[] { AppContext.BaseDirectory, Directory.GetCurrentDirectory() })
        {
            var dir = new DirectoryInfo(start);
            while (dir is not null)
            {
                var candidate = Path.Combine(dir.FullName, "assets", "scene_anchors");
                if (File.Exists(Path.Combine(candidate, "domain_controls.json"))) return candidate;
                dir = dir.Parent;
            }
        }
        throw new Exception("SCENE_ANCHOR_DIR_NOT_FOUND");
    }
}
