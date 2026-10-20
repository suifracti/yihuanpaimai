using NteHost.DomainActions;
using NteHost.Input;
using NteHost.WindowMonitor;
using System.Text.Json;
using System.Text.Json.Nodes;

static class WindowsBackendChecks
{
    static void Require(bool ok, string message) { if (!ok) throw new Exception(message); }
    sealed class Focus : IFocusSnapshotProvider
    {
        public long Target; public long Epoch; long sequence;
        public FocusSnapshot Capture() => new(true, Target, Win32DummyWindow.IsForeground(Target) ? Target : -1,
            Epoch, Interlocked.Increment(ref sequence), TraceClock.NowNs());
    }
    sealed class Trace : IInputTraceSink
    {
        public Action<string>? OnPhase;
        public void Write(string phase, string detail) => OnPhase?.Invoke(phase);
    }
    sealed class Fixture : IDisposable
    {
        public readonly Win32DummyWindow Window;
        public readonly IInputObserver Observer;
        public readonly InputSafetyGuard Guard;
        public readonly IRawInputBackend Raw;
        public readonly Focus Focus;
        public readonly Trace Trace = new();
        public readonly Win32DummyWindow.Decoder Decoder = new();
        public ActionScope Scope;
        public DomainIntent Intent;
        public DomainActionCoordinator Coordinator;
        public NativeDomainActionRuntime Runtime;
        public WindowsTicketedDomainBackend Backend;
        public readonly List<JsonObject> Events = new();
        public int AttemptCommits, ReceiptCommits;
        public bool CommitAllowed = true, ReceiptAllowed = true;
        public NativeDomainFrame? Latest;
        readonly IExecutionObligationPort obligations;
        public Fixture(Win32DummyWindow window, bool partial = false, bool enable = true,
            bool fakeObserver = false, bool noPort = false, bool unknownAnchor = false,
            IExecutionObligationPort? obligationsOverride = null, Action<JsonObject>? publishOverride = null)
        {
            Window = window; window.Activate();
            window.ResetFieldForTest();
            long confirmationsBefore = window.Clicks;
            Require(SpinWait.SpinUntil(() => Win32DummyWindow.IsForeground(window.Hwnd.ToInt64()), 1000), "DUMMY_FOREGROUND_REQUIRED");
            var identity = new WindowIdentityReader().Read(window.Hwnd.ToInt64());
            var binding = new WindowBinding(identity.Hwnd, identity.Pid, identity.ProcessInstanceToken, 0);
            Focus = new() { Target = binding.Hwnd };
            long now = TraceClock.NowNs();
            Scope = new("dummy-match", 1, 4, 50000, 20000, "AUCTION", "dummy-lease", now + 20_000_000_000,
                binding, 1, 1, now, true, true, true, true, false, false)
                { MatchGeneration = 1, ObservationSessionId = "dummy-observation", ApprovalId = "dummy-offline-approval" };
            Intent = new("dummy-bid", DomainActionKind.Bid, Scope.MatchId, 1, 4, 12345, 50000,
                now + 10_000_000_000, 1, Scope.LeaseId, binding)
                { MatchGeneration = 1, ObservationSessionId = Scope.ObservationSessionId, MaxSafeBid = 20000, ApprovalId = Scope.ApprovalId };
            Observer = fakeObserver ? new FakeInputObserver() : new Win32LowLevelInputObserver();
            Require(Observer.Start(_ => { }).Ok, "OBSERVER_FAILED");
            Raw = partial ? new CountingRawInputBackend { PartialSendResult = 1 } : new Win32RawInputBackend();
            Guard = new(Observer, Focus, new Win32CursorBackend(), Raw, Trace,
                new InputSafetyOptions { EnableRestrictedDomainActions = enable, RestoreCursorOnCleanRelease = false });
            // Observer was bootstrapped before guard construction; bind its actual hook witness now.
            Observer.Stop(); Require(Observer.Start(e => Guard.OnObservedInput(e)).Ok, "GUARD_OBSERVER_FAILED");
            Require(Guard.Arm(new(binding.Hwnd)).Ok, "ARM_FAILED");
            var testObligations = new DelegatedExecutionObligationPort(i => {
                AttemptCommits++;
                if (!CommitAllowed) return false;
                // Test-only ACK record, NOT another budget book. Prove disk acknowledgement
                // occurs after safe amount editing, before the confirm click.
                Require(Raw.SendCallCount == 2 && window.Clicks == confirmationsBefore, "ATTEMPT_MUST_PRECEDE_CONFIRMATION");
                using var file = new FileStream("build/native-domain-actions/dummy-attempt-ack.json", FileMode.Create, FileAccess.Write);
                System.Text.Json.JsonSerializer.Serialize(file, i); file.Flush(true); return true;
            }, r => { ReceiptCommits++; return ReceiptAllowed; });
            obligations = obligationsOverride ?? testObligations;
            var control = new CapturedDomainControlEvidence(Capture, unknownAnchor ? new UnconnectedGameDomainDecoder() : Decoder);
            var backend = new WindowsTicketedDomainBackend(Guard, control, noPort ? null : obligations, TraceClock.NowNs, binding.Hwnd);
            Backend = backend;
            Coordinator = new(Current, TraceClock.NowNs, new RestrictedDomainInputPort(backend, TraceClock.NowNs));
            Runtime = new(Coordinator, new(Decoder, TraceClock.NowNs), obligations, publishOverride ?? Events.Add);
        }
        public void AdoptIntent(DomainIntent intent)
        {
            Intent = intent;
            Scope = Scope with { MatchId = intent.MatchId, Round = intent.Round,
                FactsRevision = intent.FactsRevision, Budget = intent.Budget,
                ApprovedAmountLimit = intent.MaxSafeBid, Scene = "AUCTION",
                LeaseId = intent.LeaseId, LeaseExpiresNs = intent.DeadlineNs + 5_000_000_000,
                Window = intent.Window, TakeoverGeneration = intent.TakeoverGeneration,
                MatchGeneration = intent.MatchGeneration,
                ObservationSessionId = intent.ObservationSessionId,
                ApprovalId = intent.ApprovalId, Connected = true,
                ForegroundMatches = true, ExecutionAuthorized = true, SourceQualified = true };
        }
        public NativeDomainFrame Capture()
        {
            Scope = Scope with { SourceSequence = Scope.SourceSequence + 1, CapturedNs = TraceClock.NowNs(),
                ForegroundMatches = Win32DummyWindow.IsForeground(Scope.Window.Hwnd) };
            Latest = Window.Capture(Scope); Scope = Latest.Scope; return Latest;
        }
        ActionScope Current() => Capture().Scope;
        public void Dispose() { Guard.Cancel("TEST_END"); Guard.Release(); Observer.Stop(); }
    }
    public static void Run()
    {
        if (!OperatingSystem.IsWindows()) throw new Exception("DUMMY_REQUIRES_WINDOWS_NO_SKIP");
        Directory.CreateDirectory("build/native-domain-actions");
        using var window = new Win32DummyWindow();
        using (var f = new Fixture(window))
        {
            var receipt = f.Runtime.Dispatch(f.Intent);
            Console.WriteLine($"dummy raw={f.Raw.SendCallCount} acceptedRecords={f.Raw.InputsSentCount} field={window.FieldText} clicks={window.Clicks} guard={f.Guard.State}/{f.Guard.CancelReason} read={f.Backend.LastReadbackReason}");
            Require(receipt.Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "ACTUAL_OS_SEND_MUST_STAY_PENDING: " + receipt.Reason);
            Require(SpinWait.SpinUntil(() => window.FieldText == "12345" && window.Clicks == 1, 1000), "DUMMY_DID_NOT_RECEIVE_EXACT_DIGITS_AND_BUTTON");
            Require(f.Raw.SendCallCount == 3 && f.AttemptCommits == 1, "TICKETED_PRIMITIVES_OR_DURABLE_ACK");
            Require(!f.Guard.UserTakeoverSeen && f.Guard.State == GuardState.Armed, "SELF_INPUT_MUST_MATCH_LEDGER");
            var frame = f.Capture();
            Require(f.Runtime.OnIndependentCapture(f.Intent.IntentId, frame, new(2, "other"))?.Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "OPPONENT_CONFIRMATION");
            var ownReceipt = f.Runtime.OnIndependentCapture(f.Intent.IntentId, frame, new(1, "dummy-self"));
            Console.WriteLine($"own receipt={ownReceipt?.Status}/{ownReceipt?.Reason} appAccepted={window.Accepted} pixels={f.Decoder.Decode(frame).OwnBid?.Amount}");
            Require(ownReceipt?.Status == ReceiptStatus.CONFIRMED, "INDEPENDENT_OWN_PIXEL_RECEIPT");
            var envelope = f.Events.Last();
            Require((string?)envelope["receiptChannel"] == "bid", "BID_RECEIPT_CHANNEL");
            var payload = envelope["receipt"]!;
            Require((string?)payload["status"] == "CONFIRMED" && (string?)payload["evidenceRef"] == frame.EvidenceRef, "MAIN_SCHEMA_PROJECTION");
            File.WriteAllText("build/native-domain-actions/dummy-receipt-events.json", new JsonArray(f.Events.Select(e => e.DeepClone()).ToArray()).ToJsonString());
            Require(f.Runtime.Dispatch(f.Intent).Status == ReceiptStatus.CONFIRMED && f.Raw.SendCallCount == 3, "NO_DUPLICATE_OS_SEND");
            Console.WriteLine("PASS actual Windows tickets: exact digits/button + independent own pixel receipt + duplicate no-send");
        }
        foreach (string mode in new[] { "disabled", "missing-obligation", "commit-failure", "focus-epoch", "wrong-instance", "takeover", "shutdown", "other-window", "unknown-anchor" })
        {
            using var f = new Fixture(window, enable: mode != "disabled", noPort: mode == "missing-obligation", unknownAnchor: mode == "unknown-anchor");
            if (mode == "commit-failure") f.CommitAllowed = false;
            if (mode == "wrong-instance") f.Intent = f.Intent with { Window = f.Intent.Window with { ProcessInstanceToken = f.Intent.Window.ProcessInstanceToken + 1 } };
            if (mode == "takeover") f.Guard.Cancel("USER_TAKEOVER");
            if (mode == "shutdown") f.Guard.Release();
            if (mode is "drift" or "focus-epoch") f.Trace.OnPhase = phase => {
                if (phase == TracePhase.TicketIssued) { if (mode == "drift") f.Decoder.Drift = true; else f.Focus.Epoch++; }
            };
            using var other = mode == "other-window" ? new Win32DummyWindow() : null;
            var result = f.Runtime.Dispatch(f.Intent);
            Require(result.Status == ReceiptStatus.NOT_SENT && f.Raw.SendCallCount == (mode=="commit-failure"?2:0),
                "GATE_FAILED " + mode + " " + result.Status + " " + result.Reason);
            Console.WriteLine("PASS no confirmation input: " + mode);
        }
        using (var f = new Fixture(window, partial: true, fakeObserver: true))
        {
            Require(f.Runtime.Dispatch(f.Intent).Status == ReceiptStatus.NOT_SENT, "PARTIAL_EDIT_IS_NOT_SUBMITTED");
            Require(f.Runtime.Dispatch(f.Intent with { IntentId = "retry" }).Status == ReceiptStatus.NOT_SENT && f.Raw.SendCallCount == 1, "PARTIAL_RESEND");
            Console.WriteLine("PASS partial edit stops without submission or continued input (fake partial)");
        }
        using (var f = new Fixture(window))
        {
            f.Decoder.BadAmount = true;
            Require(f.Runtime.Dispatch(f.Intent).Status == ReceiptStatus.NOT_SENT && f.Raw.SendCallCount == 3, "BAD_AMOUNT_MUST_NOT_SUBMIT_AFTER_TWO_FILLS");
            Require(window.Clicks == 1, "UNVERIFIED_AMOUNT_CLICKED_SUBMIT");
            Console.WriteLine("PASS two actual field fills but mismatched captured amount NOT_SENT/no submit");
        }
        using (var f = new Fixture(window))
        {
            f.ReceiptAllowed = false;
            Require(f.Runtime.Dispatch(f.Intent).Status == ReceiptStatus.UNKNOWN, "LOST_PENDING_DURABILITY_MUST_STOP");
            Require(f.Runtime.Dispatch(f.Intent with { IntentId = "retry" }).Status == ReceiptStatus.NOT_SENT && f.Raw.SendCallCount == 3, "DURABILITY_RESEND");
            Console.WriteLine("PASS pending durability failure UNKNOWN/no resend");
        }
        Console.WriteLine("PASS Windows dummy adapter; HTGame never constructed/discovered/authorized");
    }

    sealed class DeferredObligations : IExecutionObligationPort
    {
        IExecutionObligationPort? inner;
        public void Configure(IExecutionObligationPort value) => inner = value;
        public bool CommitBeforeInput(DomainIntent intent) => inner?.CommitBeforeInput(intent) == true;
        public bool CommitReceipt(DomainReceipt receipt) => inner?.CommitReceipt(receipt) == true;
    }

    static readonly System.Text.Json.JsonSerializerOptions ProtocolJson = new()
    { PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.CamelCase,
      Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter() } };
    static void EmitProtocolLine(JsonObject line)
    {
        lock (ProtocolJson) { Console.WriteLine(line.ToJsonString(ProtocolJson)); Console.Out.Flush(); }
    }

    public static void RunCrossProcessHost()
    {
        if (!OperatingSystem.IsWindows()) throw new Exception("CROSS_PROCESS_DUMMY_REQUIRES_WINDOWS");
        Console.InputEncoding = new System.Text.UTF8Encoding(false);
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        var bootId = Guid.NewGuid().ToString("N");
        const string sessionId = "obs-1";
        using var window = new Win32DummyWindow();
        var deferred = new DeferredObligations();
        using var f = new Fixture(window, obligationsOverride: deferred,
            publishOverride: EmitProtocolLine);
        var identity = new WindowIdentityReader().Read(f.Scope.Window.Hwnd);
        EmitProtocolLine(new JsonObject {
            ["type"] = "domain.action.host_ready", ["protocolVersion"] = 1,
            ["bootId"] = bootId, ["observationSessionId"] = sessionId,
            ["window"] = new JsonObject {
                ["hwnd"] = identity.Hwnd, ["pid"] = identity.Pid,
                ["processInstanceToken"] = identity.ProcessInstanceToken, ["focusEpoch"] = 0,
            },
        });
        var raw = Console.In.ReadLine();
        var dispatch = JsonNode.Parse(raw ?? "") as JsonObject
            ?? throw new Exception("MAIN_DISPATCH_REQUIRED");
        if ((string?)dispatch["type"] != "domain.action.dispatch"
            || (int?)dispatch["protocolVersion"] != 1
            || (string?)dispatch["bootId"] != bootId
            || (string?)dispatch["observationSessionId"] != sessionId
            || dispatch["intent"] is not JsonObject intentNode)
            throw new Exception("MAIN_DISPATCH_BINDING_REJECTED");
        var ledgerId = (string?)dispatch["ledgerId"] ?? "";
        var intent = intentNode.Deserialize<DomainIntent>(ProtocolJson)
            ?? throw new Exception("MAIN_INTENT_INVALID");
        if (intent.Kind != DomainActionKind.Bid || intent.ObservationSessionId != sessionId
            || intent.Window.Hwnd != identity.Hwnd || intent.Window.Pid != identity.Pid
            || intent.Window.ProcessInstanceToken != identity.ProcessInstanceToken)
            throw new Exception("DUMMY_INTENT_SCOPE_MISMATCH");
        f.AdoptIntent(intent);
        var acknowledgements = new DomainActionAcknowledgementRouter(TimeSpan.FromSeconds(3));
        var ackReader = new Thread(() => {
            while (Console.In.ReadLine() is { } line)
            {
                try { if (JsonNode.Parse(line) is JsonObject ack) acknowledgements.Accept(ack); }
                catch (System.Text.Json.JsonException) { }
            }
        }) { IsBackground = true, Name = "dummy-main-ack-reader" };
        ackReader.Start();
        var port = new MainProcessExecutionObligationPort(acknowledgements, EmitProtocolLine,
            bootId, ledgerId, (long?)dispatch["ledgerRevision"] ?? -1, sessionId, intent);
        deferred.Configure(port);

        var sent = f.Runtime.Dispatch(intent);
        if (sent.Status != ReceiptStatus.SENT_PENDING_CONFIRMATION)
            throw new Exception("DUMMY_SEND_NOT_PENDING:" + sent.Status + ":" + sent.Reason);
        var captured = f.Capture();
        var confirmed = f.Runtime.OnIndependentCapture(intent.IntentId, captured,
            new OwnSeatBinding(1, "dummy-self"));
        if (confirmed?.Status != ReceiptStatus.CONFIRMED || window.Accepted != intent.Amount)
            throw new Exception("DUMMY_INDEPENDENT_RECEIPT_FAILED:" + confirmed?.Status);
        EmitProtocolLine(new JsonObject { ["type"] = "domain.action.host_complete",
            ["inputActions"] = false, ["dummyInputCount"] = f.Raw.SendCallCount,
            ["acceptedAmount"] = window.Accepted, ["receiptStatus"] = confirmed.Status.ToString() });
    }

    public static void RunAckTimeoutDummy()
    {
        if (!OperatingSystem.IsWindows()) throw new Exception("ACK_TIMEOUT_DUMMY_REQUIRES_WINDOWS");
        Directory.CreateDirectory("build/native-domain-actions");
        using var window = new Win32DummyWindow();
        var deferred = new DeferredObligations();
        using var f = new Fixture(window, obligationsOverride: deferred);
        deferred.Configure(new MainProcessExecutionObligationPort(
            new DomainActionAcknowledgementRouter(TimeSpan.FromMilliseconds(50)),
            _ => { }, "dummy-boot", "dummy-ledger", 1,
            f.Intent.ObservationSessionId, f.Intent));
        var timedOut = f.Runtime.Dispatch(f.Intent);
        Require(timedOut.Status == ReceiptStatus.NOT_SENT && f.Raw.SendCallCount == 2
            && f.Events.All(e=>(string?)e["type"]!="domain.action.receipt"), "MISSING_MAIN_ACK_BLOCKS_CONFIRMATION_AND_BID_PROJECTION");
        Console.WriteLine("PASS Main ACK timeout blocks confirmation and exposes only a stop notice");
    }
}
