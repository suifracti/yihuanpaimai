using NteHost.DomainActions;
using NteHost.Input;
using NteHost.WindowMonitor;
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
        public Fixture(Win32DummyWindow window, bool partial = false, bool enable = true, bool fakeObserver = false, bool noPort = false, bool unknownAnchor = false)
        {
            Window = window; window.Activate();
            window.ResetFieldForTest();
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
            obligations = new DelegatedExecutionObligationPort(i => {
                AttemptCommits++;
                if (!CommitAllowed) return false;
                // Test-only ACK record, NOT another budget book. Prove disk acknowledgement
                // occurs with zero raw calls and before this transaction's input.
                Require(Raw.SendCallCount == 0, "ATTEMPT_MUST_PRECEDE_INPUT");
                using var file = new FileStream("build/native-domain-actions/dummy-attempt-ack.json", FileMode.Create, FileAccess.Write);
                System.Text.Json.JsonSerializer.Serialize(file, i); file.Flush(true); return true;
            }, r => { ReceiptCommits++; return ReceiptAllowed; });
            var control = new CapturedDomainControlEvidence(Capture, unknownAnchor ? new UnconnectedGameDomainDecoder() : Decoder);
            var backend = new WindowsTicketedDomainBackend(Guard, control, noPort ? null : obligations, TraceClock.NowNs, binding.Hwnd);
            Backend = backend;
            Coordinator = new(Current, TraceClock.NowNs, new RestrictedDomainInputPort(backend, TraceClock.NowNs));
            Runtime = new(Coordinator, new(Decoder, TraceClock.NowNs), obligations, Events.Add);
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
            var payload = f.Events.Last()["currentMatch"]!["bidActionReceipt"]!;
            Require((string?)payload["status"] == "CONFIRMED" && (string?)payload["evidenceRef"] == frame.EvidenceRef, "MAIN_SCHEMA_PROJECTION");
            File.WriteAllText("build/native-domain-actions/dummy-receipt-events.json", new JsonArray(f.Events.Select(e => e.DeepClone()).ToArray()).ToJsonString());
            Require(f.Runtime.Dispatch(f.Intent).Status == ReceiptStatus.CONFIRMED && f.Raw.SendCallCount == 3, "NO_DUPLICATE_OS_SEND");
            Console.WriteLine("PASS actual Windows tickets: exact digits/button + independent own pixel receipt + duplicate no-send");
        }
        foreach (string mode in new[] { "disabled", "missing-obligation", "commit-failure", "drift", "focus-epoch", "wrong-instance", "takeover", "shutdown", "other-window", "unknown-anchor" })
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
            Require(result.Status == ReceiptStatus.NOT_SENT && f.Raw.SendCallCount == 0,
                "GATE_FAILED " + mode + " " + result.Status + " " + result.Reason);
            Console.WriteLine("PASS zero OS input: " + mode);
        }
        using (var f = new Fixture(window, partial: true, fakeObserver: true))
        {
            Require(f.Runtime.Dispatch(f.Intent).Status == ReceiptStatus.UNKNOWN, "PARTIAL_MUST_BE_UNKNOWN");
            Require(f.Runtime.Dispatch(f.Intent with { IntentId = "retry" }).Status == ReceiptStatus.NOT_SENT && f.Raw.SendCallCount == 1, "PARTIAL_RESEND");
            Console.WriteLine("PASS partial backend UNKNOWN/no retry (fake partial, no partial OS modifier injection)");
        }
        using (var f = new Fixture(window))
        {
            int tickets = 0; int clicks = window.Clicks;
            f.Trace.OnPhase = phase => { if (phase == TracePhase.TicketIssued && ++tickets == 3) f.Decoder.BadAmount = true; };
            Require(f.Runtime.Dispatch(f.Intent).Status == ReceiptStatus.UNKNOWN && f.Raw.SendCallCount == 2, "FIELD_CHANGED_AFTER_READBACK_MUST_NOT_SUBMIT");
            Require(window.Clicks == clicks, "FIELD_DRIFT_SUBMITTED");
            Console.WriteLine("PASS final ticket rejects field drift AFTER the earlier exact amount read");
        }
        using (var f = new Fixture(window))
        {
            f.Decoder.BadAmount = true;
            Require(f.Runtime.Dispatch(f.Intent).Status == ReceiptStatus.UNKNOWN && f.Raw.SendCallCount == 2, "BAD_AMOUNT_MUST_NOT_SUBMIT");
            Require(window.Clicks == 1, "UNVERIFIED_AMOUNT_CLICKED_SUBMIT");
            Console.WriteLine("PASS actual field mutation but mismatched captured amount UNKNOWN/no submit");
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
}
