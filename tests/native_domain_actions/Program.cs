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
            { MatchGeneration = 1, ObservationSessionId = "obs-1" };
        Coordinator = new(() => Scope, () => Now, executionPort ? Port : null);
    }
    public DomainIntent Intent(string id = "bid-1", DomainActionKind kind = DomainActionKind.Bid) =>
        new(id, kind, Scope.MatchId, Scope.Round, Scope.FactsRevision,
            kind == DomainActionKind.Bid ? 500 : null, Scope.Budget, Now + 500_000_000,
            Scope.TakeoverGeneration, Scope.LeaseId, Window)
            { MatchGeneration = Scope.MatchGeneration, ObservationSessionId = Scope.ObservationSessionId, MaxSafeBid = 800 };
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
        Case("default execution OFF", () => {
            var f = new Fixture(false); Require(f.Coordinator.Dispatch(f.Intent()).Status == ReceiptStatus.NOT_SENT, "OFF");
            Require(f.Port.Sends == 0, "NO_INPUT");
        });
        Case("money, scope, source, authorization gates", () => {
            foreach (var change in new Func<ActionScope, ActionScope>[] {
                s => s with { Budget = 0 }, s => s with { ApprovedAmountLimit = 499 },
                s => s with { MatchId = "foreign" }, s => s with { Round = 2 },
                s => s with { MatchGeneration = 2 }, s => s with { ObservationSessionId = "obs-other" },
                s => s with { FactsRevision = 8 }, s => s with { SourceQualified = false },
                s => s with { CapturedNs = 1 }, s => s with { CapturedNs = 1_000_000_001 },
                s => s with { ExecutionAuthorized = false }, s => s with { Connected = false },
                s => s with { ForegroundMatches = false }, s => s with { LeaseId = "foreign" },
                s => s with { Window = s.Window with { ProcessInstanceToken = 31 } },
                s => s with { TakeoverGeneration = 3 }, s => s with { LeaseExpiresNs = 1 } }) {
                var f = new Fixture(); var i = f.Intent(); f.Scope = change(f.Scope);
                Require(f.Coordinator.Dispatch(i).Status == ReceiptStatus.NOT_SENT && f.Port.Sends == 0, "GATE_FAILED");
            }
            foreach (long amount in new long[] { -1, 0, 801, 1001, 10_000_000 }) {
                var f = new Fixture(); Require(f.Coordinator.Dispatch(f.Intent() with { Amount = amount }).Status == ReceiptStatus.NOT_SENT, "AMOUNT_BOUND");
            }
        });
        Case("target changes between prechecks prevent send", () => {
            var f = new Fixture(); f.Port.BetweenPrechecks = () => f.Scope = f.Scope with { TakeoverGeneration = 3 };
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
        Case("takeover after field focus stops before amount and cannot retry", () => {
            var f = new Fixture(); var i = f.Intent(); var backend = new FakeTicketBackend();
            backend.BeforeCommit = primitive => { if (primitive == DomainPrimitive.ReplaceAmountDigits)
                f.Scope = f.Scope with { TakeoverGeneration = 3 }; };
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
                evidence with { OriginFactsRevision = 8 }, evidence with { SourceQualified = false },
                evidence with { SourceSequence = 10 }, evidence with { CapturedNs = sent.SentNs },
                evidence with { CapturedNs = f.Now + 1 }, evidence with { SourceSequence = 99 },
                evidence with { Window = f.Window with { Pid = 21 } } })
                Require(f.Coordinator.Confirm(bad).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "UNRELATED_RESULT_CONFIRMED");
            Require(f.Coordinator.Confirm(evidence).Status == ReceiptStatus.CONFIRMED, "VISIBLE_CONFIRMATION");
            Require(f.Coordinator.Dispatch(i).Status == ReceiptStatus.CONFIRMED && f.Port.Sends == 1, "IDEMPOTENT");
            Require(f.Coordinator.Dispatch(i with { IntentId = "new-id" }).Status == ReceiptStatus.NOT_SENT && f.Port.Sends == 1, "ROUND_RESEND");
        });
        Case("partial or throwing backend UNKNOWN and globally no resend", () => {
            foreach (bool throws in new[] { false, true }) {
                var f = new Fixture(); f.Port.Partial = !throws; f.Port.Throw = throws; var i = f.Intent();
                Require(f.Coordinator.Dispatch(i).Status == ReceiptStatus.UNKNOWN, "PARTIAL_UNKNOWN");
                f.Port.Partial = false; f.Port.Throw = false;
                Require(f.Coordinator.Dispatch(i with { IntentId = "retry" }).Status == ReceiptStatus.NOT_SENT && f.Port.Sends == 1, "UNKNOWN_RESEND");
            }
        });
        Case("pending timeout/disconnect/budget loss/takeover become UNKNOWN", () => {
            foreach (int mode in new[] { 0, 1, 2, 3 }) {
                var f = new Fixture(); var i = f.Intent(); f.Coordinator.Dispatch(i);
                if (mode == 0) f.Now = i.DeadlineNs;
                if (mode == 1) f.Scope = f.Scope with { Connected = false };
                if (mode == 2) f.Scope = f.Scope with { Budget = 0 };
                if (mode == 3) f.Scope = f.Scope with { TakeoverGeneration = 3 };
                Require(f.Coordinator.Poll()!.Status == ReceiptStatus.UNKNOWN, "PENDING_STOP");
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
        Console.WriteLine($"PASS {cases} scenarios (fake input only)");
    }
}
