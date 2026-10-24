using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using NteHost.DomainActions;
using NteHost.Input;
using NteHost.Protocol;
using NteHost.WindowMonitor;

namespace WgcLiveHarness;

/// <summary>
/// Operator-gated bridge from a domain.action.dispatch onto the existing ticketed
/// backend. The scene-anchor decoder supplies NTE_VERIFIED_GAME_V1 anchors.
/// The dummy decoder is never used. With the gate unset this type is not constructed.
/// </summary>
sealed class TicketedSceneAnchorDispatch : IDisposable
{
    readonly IGameDomainFrameDecoder decoder;
    readonly InputSafetyGuard guard;
    readonly Win32LowLevelInputObserver observer;
    readonly GameFocus focus;
    readonly SwitchingObligations obligations;
    readonly NativeDomainActionRuntime runtime;
    readonly WindowsTicketedDomainBackend backend;
    readonly object gate = new();
    readonly WindowIdentityReader identities = new();
    readonly string sessionId;
    readonly Action<JsonObject> publish;
    Func<DomainIntent, NativeDomainFrame?>? engineCapture;
    DomainIntent? current;
    DomainIntent? pending;
    NativeDomainFrame? pinned;
    NativeDomainFrame? latestCapture;
    bool usePinned;
    long confirmationDeadlineNs;
    bool settlementReturned;
    bool armed;
    bool disposed;
    int dispatching;
    readonly UserInputCourtesy courtesy = new();
    Func<string, bool> runCancelled = _ => false;
    long inputSequence;
    string runApproval = "";
    GameFocus.BorrowedFocus? pendingFocus;
    GameFocus.BorrowedFocus? activeFocus;

    void YieldToHardware()
    {
        courtesy.HardwareInput(ProtocolClock.NowNs());
        var borrowed = Volatile.Read(ref activeFocus);
        // Never perform window calls inside the low-level input hook.
        if (borrowed is not null) ThreadPool.QueueUserWorkItem(_ => borrowed.Dispose());
    }

    void OnObservedInput(ObservedInputEvent observed)
    {
        guard.OnObservedInput(observed); // own cursor moves are exempted before hardware yield
    }

    TicketedSceneAnchorDispatch(string sessionId, IGameDomainFrameDecoder decoder, InputSafetyGuard guard,
        Win32LowLevelInputObserver observer, GameFocus focus, SwitchingObligations obligations,
        WindowsTicketedDomainBackend backend, NativeDomainActionRuntime runtime, Action<JsonObject> publish)
    {
        this.sessionId = sessionId;
        this.decoder = decoder;
        this.guard = guard;
        this.observer = observer;
        this.focus = focus;
        this.obligations = obligations;
        this.backend = backend;
        this.runtime = runtime;
        this.publish = publish;
    }

    public bool AwaitingVisibleResult { get { lock (gate) return pending is not null; } }
    public int ConfirmationWaitMs => (int)Math.Max(1, (confirmationDeadlineNs - ProtocolClock.NowNs()) / 1_000_000);

    public PortOutcome ClickSettlementSkip(Func<bool> current)
    {
        lock (gate)
        {
            if (disposed || pending is not null || !current()) return new(false, false, "SKIP_UNAVAILABLE");
            if (!courtesy.IsIdle(ProtocolClock.NowNs()) || runCancelled(runApproval))
                return new(false, false, "USER_INPUT_YIELD");
            inputSequence = courtesy.Sequence;
            using var borrowed = focus.Borrow(() => courtesy.Uninterrupted(inputSequence));
            if (!borrowed.Activated) return new(false, false, "SKIP_GAME_ACTIVATION_FAILED");
            if (!armed)
            {
                var arm = guard.Arm(new ArmRequest(focus.Target));
                if (!arm.Ok) return new(false, false, arm.Reason);
                armed = true;
            }
            Volatile.Write(ref dispatching, 1);
            Volatile.Write(ref activeFocus, borrowed);
            try { return backend.ClickSettlementSkip(() => current() && InputUninterrupted()); }
            finally
            {
                Volatile.Write(ref activeFocus, null);
                Volatile.Write(ref dispatching, 0);
            }
        }
    }

    // Planning metadata comes from the same held WGC pixels as FRAME. These
    // anchors are deliberately unqualified for input: every dispatch still
    // reacquires an independent frame through CaptureEngine and its tickets.
    public JsonObject? DescribePlanningFrame(CapturedBgraFrame frame, JsonObject? state,
        WindowMonitorSnapshot target, ClientGeometry geometry, long frameSequence)
    {
        if (target.TargetIdentity is not { IsPresent: true } identity) return null;
        var match = state?["currentMatch"] as JsonObject;
        var window = new WindowBinding(target.TargetHwnd, target.TargetPid, identity.ProcessInstanceToken, 0);
        var scope = new ActionScope((string?)match?["id"] ?? "", (int?)match?["roundNo"] ?? 0,
            (long?)match?["factsRevision"] ?? 0, 0, 0, "UNKNOWN", "", 0, window, 0,
            frame.AcquisitionSequence, frame.CaptureTimestampNs, false, false, target.IsTargetForeground,
            false, false, false)
        { MatchGeneration = (long?)state?["lastFrame"]?["matchGeneration"] ?? 0,
            ObservationSessionId = sessionId };
        var held = new NativeDomainFrame(scope, geometry, frame.Pixels, frame.Stride);
        var view = held.DecodeOnce(decoder);
        var funds = SceneAnchorOcr.ReadAssets(held.Pixels, frame.Width, frame.Height, frame.Stride, view?.Scene);
        return new JsonObject { ["schemaVersion"] = "domain-planning-view.v1", ["planningOnly"] = true,
            ["inputActions"] = false, ["frameSequence"] = frameSequence,
            ["readbackNs"] = frame.CaptureTimestampNs, ["matchId"] = scope.MatchId,
            ["matchGeneration"] = scope.MatchGeneration, ["factsRevision"] = scope.FactsRevision,
            ["round"] = scope.Round, ["scene"] = view?.Scene, ["goldAverageVisible"] = view?.GoldAverageVisible,
            ["purpleCountVisible"] = view?.PurpleCountVisible,
            ["funds"] = funds, ["instruments"] = JsonSerializer.SerializeToNode(view?.Instruments, Json),
            ["advancedToolGroupVisible"] = view?.Controls.Any(c => c.Primitive == DomainPrimitive.SelectToolGroup) == true };
    }

    public static TicketedSceneAnchorDispatch? TryCreate(string anchorDirectory, string sessionId, long hwnd,
        Action<JsonObject> publish, Func<string, bool>? runCancelled = null)
    {
        if (hwnd == 0 || publish is null) return null;
        var decoder = SceneAnchorGameDecoder.Load(anchorDirectory);
        if (!decoder.Ready) return null;
        decoder.ReadAmount = SceneAnchorOcr.ReadAmountField;
        decoder.ReadCommittedAmount = SceneAnchorOcr.Read;
        decoder.ReadCommittedText = SceneAnchorOcr.ReadCommittedText;
        decoder.ReadIntelText = SceneAnchorOcr.ReadText;
        decoder.ReadInstruments = SceneAnchorOcr.ReadInstruments;
        var focus = new GameFocus { Target = hwnd };
        var observer = new Win32LowLevelInputObserver("scene-anchor");
        TicketedSceneAnchorDispatch? dispatch = null;
        var guard = new InputSafetyGuard(observer, focus, new Win32CursorBackend(), new Win32RawInputBackend(), null,
            new InputSafetyOptions { EnableRestrictedDomainActions = true, RestoreCursorOnCleanRelease = false,
                HardwareYield = _ => dispatch?.YieldToHardware(),
                DomainYieldRequested = () => dispatch is not null && !dispatch.courtesy.Uninterrupted(dispatch.inputSequence) });
        if (!observer.Start(observed => dispatch?.OnObservedInput(observed)).Ok)
        {
            observer.Stop();
            return null;
        }
        var obligations = new SwitchingObligations();
        var evidence = new CapturedDomainControlEvidence(() => dispatch!.CaptureEngine(), decoder);
        var backend = new WindowsTicketedDomainBackend(guard, evidence, obligations, ProtocolClock.NowNs, hwnd, allowGameInput: true);
        var coordinator = new DomainActionCoordinator(() => dispatch!.ReadScope(), ProtocolClock.NowNs,
            new CourtesyPort(new RestrictedDomainInputPort(backend, ProtocolClock.NowNs), () => dispatch!.InputUninterrupted()),
            () => !dispatch!.InputUninterrupted());
        var runtime = new NativeDomainActionRuntime(coordinator, new(decoder, ProtocolClock.NowNs), obligations,
            message => dispatch!.publish(message));
        dispatch = new(sessionId, decoder, guard, observer, focus, obligations, backend, runtime, publish);
        dispatch.runCancelled = runCancelled ?? (_ => false);
        return dispatch;
    }

    bool InputUninterrupted() => !disposed && !runCancelled(runApproval)
        && courtesy.Uninterrupted(inputSequence);

    bool WaitForIdle(DomainIntent intent)
    {
        bool announced = false;
        while (!disposed && !runCancelled(intent.ApprovalId))
        {
            long now = ProtocolClock.NowNs();
            if (intent.Kind != DomainActionKind.ReturnLobby && !AuctionPreparation.IsLobby(intent.Kind)
                && intent.Round > 0 && intent.RoundDeadlineNs - now <
                (intent.Kind == DomainActionKind.Bid ? 6_000_000_000 : 3_000_000_000)) return false;
            if (courtesy.IsIdle(now))
            {
                Console.Error.WriteLine(new JsonObject { ["type"]="domain.action.idle-ready",
                    ["intentId"]=intent.IntentId,["hardwareEvents"]=courtesy.Sequence,
                    ["waitedForIdle"]=announced,["observer"]=JsonSerializer.SerializeToNode(observer.Diagnostics()),
                    ["atNs"]=now }.ToJsonString());
                return true;
            }
            if (!announced)
            {
                Console.Error.WriteLine(new JsonObject { ["type"]="domain.action.yield",
                    ["intentId"]=intent.IntentId,["reason"]="WAITING_USER_IDLE",["atNs"]=now }.ToJsonString());
                announced = true;
            }
            Thread.Sleep(25);
        }
        return false;
    }

    sealed class CourtesyPort(IRestrictedDomainInputPort inner, Func<bool> uninterrupted) : IRestrictedDomainInputPort
    {
        public PortOutcome TrySend(DomainIntent intent, Func<bool> current)
        {
            var result = inner.TrySend(intent, () => uninterrupted() && current());
            return UserInputCourtesy.CanRetry(result, !uninterrupted())
                ? new(false, false, "USER_INPUT_YIELD") { BidConfirmationAttempted = false } : result;
        }
    }

    public bool TryHandle(JsonObject message, string bootId, WindowMonitorSnapshot target,
        DomainActionAcknowledgementRouter acknowledgements, Func<DomainIntent, NativeDomainFrame?> capture,
        Action<JsonObject> emit)
    {
        lock (gate)
        {
            engineCapture = capture;
            DomainIntent? intent = null;
            try { intent = (message["intent"] as JsonObject)?.Deserialize<DomainIntent>(Json); }
            catch (JsonException) { }
            if (!Bound(message, intent, bootId, target))
            {
                emit(new JsonObject { ["type"] = "domain.action.dispatch.rejected",
                    ["observationSessionId"] = sessionId, ["reason"] = "DISPATCH_SCOPE_INVALID",
                    ["inputActions"] = false, ["decoder"] = "SCENE_ANCHOR" });
                return true;
            }
            if(armed && !guard.IsArmedFor(target.TargetHwnd, intent!.Window.FocusEpoch))
            {
                string reason="INPUT_GUARD_"+guard.State+":"+guard.CancelReason;
                if(intent.Kind==DomainActionKind.Bid)
                    CommitNotSent(intent,message,acknowledgements,emit,bootId,reason);
                else emit(Rejected(intent,reason));
                return true;
            }
            runApproval = intent!.ApprovalId;
            while (true)
            {
            if (!WaitForIdle(intent))
            {
                string reason = runCancelled(runApproval) || disposed ? "USER_STOP" : "ROUND_TIME_TOO_SHORT";
                if (intent.Kind == DomainActionKind.Bid)
                    CommitNotSent(intent, message, acknowledgements, emit, bootId, reason);
                else publish(new JsonObject { ["type"]="domain.action.receipt",["observationSessionId"]=sessionId,
                    ["receiptChannel"]=AuctionPreparation.IsPreparation(intent.Kind) ? "preparation" : "session",
                    ["receipt"]=JsonSerializer.SerializeToNode(new DomainReceipt(intent.IntentId,intent.Kind,intent.MatchId,
                        intent.Round,intent.FactsRevision,ReceiptStatus.NOT_SENT,reason,intent.Amount) {
                        MatchGeneration=intent.MatchGeneration,ObservationSessionId=sessionId,ApprovalId=intent.ApprovalId },Json) });
                return true;
            }
            inputSequence = courtesy.Sequence;
            var liveIdentity = identities.Read(target.TargetHwnd);
            focus.Target = target.TargetHwnd;
            bool identityMatches = liveIdentity is { IsPresent: true }
                && liveIdentity.Pid == intent!.Window.Pid
                && liveIdentity.ProcessInstanceToken == intent.Window.ProcessInstanceToken;
            var borrowed = identityMatches ? focus.Borrow(() => courtesy.Uninterrupted(inputSequence)) : null;
            Volatile.Write(ref activeFocus, borrowed);
            try
            {
            if (!identityMatches || borrowed?.Activated != true)
            {
                string reason = identityMatches ? "GAME_ACTIVATION_FAILED" : "GAME_IDENTITY_CHANGED";
                Console.Error.WriteLine(new JsonObject { ["type"]="domain.action.activation",["intentId"]=intent!.IntentId,
                    ["reason"]=reason,["identityMatches"]=identityMatches,["targetHwnd"]=target.TargetHwnd,
                    ["actualPid"]=liveIdentity?.Pid,["expectedPid"]=intent.Window.Pid,
                    ["actualInstance"]=liveIdentity?.ProcessInstanceToken,["expectedInstance"]=intent.Window.ProcessInstanceToken,
                    ["activation"]=focus.LastActivation?.DeepClone() }.ToJsonString());
                if (intent!.Kind == DomainActionKind.Bid)
                    CommitNotSent(intent, message, acknowledgements, emit, bootId, reason);
                else emit(Rejected(intent!, reason));
                return true;
            }
            if (!armed)
            {
                focus.Target = target.TargetHwnd;
                var arm = guard.Arm(new ArmRequest(target.TargetHwnd));
                if (!arm.Ok)
                {
                    if (intent!.Kind == DomainActionKind.Bid)
                        CommitNotSent(intent, message, acknowledgements, emit, bootId, "ARM_" + arm.Reason);
                    else
                        emit(Rejected(intent!, "ARM_" + arm.Reason));
                    return true;
                }
                armed = true;
            }
            if (intent!.Kind == DomainActionKind.Bid)
            {
                obligations.Bid = new MainProcessExecutionObligationPort(acknowledgements, emit, bootId,
                    (string)message["ledgerId"]!, (long)message["ledgerRevision"]!, sessionId, intent);
            }
            current = intent;
            latestCapture = null;
            DomainReceipt receipt;
            Volatile.Write(ref dispatching, 1);
            try { receipt = runtime.Dispatch(intent); }
            finally { Volatile.Write(ref dispatching, 0); current = pending; }
            if (receipt.Status == ReceiptStatus.NOT_SENT && receipt.Reason == "USER_INPUT_YIELD")
            {
                backend.ResetUnsubmittedEdit(intent);
                borrowed?.Dispose(); // return focus before waiting for another idle interval
                continue;
            }
            if (receipt.Status == ReceiptStatus.SENT_PENDING_CONFIRMATION)
            {
                pending = intent;
                confirmationDeadlineNs = receipt.SentNs + 3_000_000_000;
                pendingFocus = borrowed; // return after the existing visible-result check
            }
            else if (receipt.Status == ReceiptStatus.UNKNOWN) pending = null;
            return true;
            }
            finally
            {
                if (!ReferenceEquals(pendingFocus, borrowed))
                { borrowed?.Dispose(); Interlocked.CompareExchange(ref activeFocus, null, borrowed); }
            }
            }
        }
    }

    public void Observe(NativeDomainFrame? engine)
    {
        lock (gate)
        {
            var intent = pending;
            if (intent is null) return;
            if (!InputUninterrupted())
            {
                pendingFocus?.Dispose();
                pendingFocus = null;
            }
            engine = LobbyFrame(engine, intent);
            current = intent;
            pinned = engine;
            usePinned = true;
            DomainReceipt? receipt;
            try
            {
                DomainReceipt? continuation=null;
                if (engine is not null && intent.Kind == DomainActionKind.Bid && courtesy.IsIdle(ProtocolClock.NowNs())
                    && engine.DecodeOnce(decoder) is {Scene: "BID_WARNING", BidWarningAmount: { } amount})
                {
                    inputSequence = courtesy.Sequence;
                    using var borrowed = focus.Borrow(() => courtesy.Uninterrupted(inputSequence));
                    Volatile.Write(ref dispatching,1);
                    try {
                        continuation=runtime.ContinueBidWarning(intent.IntentId,amount,
                            engine.Scope with {Scene="BID_WARNING"},
                            valid=>borrowed.Activated
                                ? backend.Execute(DomainPrimitive.ConfirmBidWarning,intent,()=>InputUninterrupted() && valid())
                                : new(false,false,"GAME_ACTIVATION_FAILED"));
                        if (continuation?.Status == ReceiptStatus.SENT_PENDING_CONFIRMATION)
                            confirmationDeadlineNs=continuation.SentNs+3_000_000_000;
                    }
                    finally { Volatile.Write(ref dispatching,0); }
                }
                receipt = continuation ?? (engine is null ? runtime.Poll() : runtime.OnIndependentCapture(intent.IntentId, engine,
                    new OwnSeatBinding(SceneAnchorGameDecoder.OwnCommittedBidSlot, SceneAnchorGameDecoder.OwnCommittedBidIdentity)));
            }
            finally
            {
                usePinned = false;
                pinned = null;
                    current = null;
            }
            if (receipt?.Status == ReceiptStatus.CONFIRMED)
            {
                if (receipt.Kind == DomainActionKind.ReturnLobby) settlementReturned = true;
                pending = null;
            }
            else if (receipt?.Status == ReceiptStatus.UNKNOWN) pending = null;
            if (pending is null)
            { pendingFocus?.Dispose(); pendingFocus = null; Volatile.Write(ref activeFocus, null); }
        }
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        pendingFocus?.Dispose(); pendingFocus = null;
        try { guard.Cancel("OBSERVATION_STOPPED"); } catch { }
        try { guard.Release(); } catch { }
        observer.Stop();
    }

    NativeDomainFrame? CaptureEngine()
    {
        var intent = current;
        if (intent is null) return null;
        if (usePinned) return pinned;
        NativeDomainFrame? engine;
        var capture = engineCapture;
        if (capture is null) return null;
        try { engine = capture(intent); }
        catch { return null; }
        engine = LobbyFrame(engine, intent);
        if (engine is not null && intent.Kind is DomainActionKind.ReturnLobby or DomainActionKind.StartNextMatch or DomainActionKind.CancelKnownPopup)
        {
            var scene = engine.DecodeOnce(decoder)?.Scene ?? "UNKNOWN";
            engine = new(engine.Scope with { Scene = scene, SettlementArchived = scene == "SETTLEMENT" || settlementReturned,
                NewMatchAdmission = settlementReturned && scene == "LOBBY" }, engine.Geometry, engine.Pixels.ToArray(), engine.Stride);
        }
        latestCapture = engine;
        return engine;
    }

    static NativeDomainFrame? LobbyFrame(NativeDomainFrame? frame, DomainIntent intent) =>
        frame is not null && AuctionPreparation.IsLobby(intent.Kind)
            ? new(frame.Scope with { MatchId = "lobby-" + intent.ObservationSessionId,
                MatchGeneration = 1, Round = 0 }, frame.Geometry, frame.Pixels.ToArray(), frame.Stride) : frame;

    ActionScope? ReadScope()
    {
        if (usePinned) return pinned?.Scope;
        var frame = latestCapture ?? CaptureEngine();
        if (frame is null) return null;
        var identity = identities.Read(frame.Scope.Window.Hwnd);
        return frame.Scope with {
            Window = new(identity.Hwnd, identity.Pid, identity.ProcessInstanceToken, frame.Scope.Window.FocusEpoch),
            ForegroundMatches = focus.Capture().ForegroundId == identity.Hwnd,
        };
    }

    void CommitNotSent(DomainIntent intent, JsonObject message, DomainActionAcknowledgementRouter acknowledgements,
        Action<JsonObject> emit, string bootId, string reason)
    {
        var receipt = new DomainReceipt(intent.IntentId, DomainActionKind.Bid, intent.MatchId, intent.Round,
            intent.FactsRevision, ReceiptStatus.NOT_SENT, reason, intent.Amount, SentNs: 0)
        {
            MatchGeneration = intent.MatchGeneration,
            ObservationSessionId = intent.ObservationSessionId,
            ApprovalId = intent.ApprovalId,
        };
        try
        {
            var port = new MainProcessExecutionObligationPort(acknowledgements, emit, bootId,
                (string)message["ledgerId"]!, (long)message["ledgerRevision"]!, sessionId, intent);
            if (!port.CommitReceipt(receipt))
            {
                emit(Rejected(intent, "DURABLE_NOT_SENT_RECEIPT_NOT_ACKNOWLEDGED"));
                return;
            }
            publish(new JsonObject
            {
                ["type"] = "domain.action.receipt",
                ["observationSessionId"] = sessionId,
                ["receiptChannel"] = "bid",
                ["receipt"] = JsonSerializer.SerializeToNode(receipt, Json),
            });
        }
        catch (Exception ex)
        {
            emit(Rejected(intent, "DURABLE_NOT_SENT_RECEIPT_FAILED:" + ex.GetType().Name));
        }
    }

    bool Bound(JsonObject message, DomainIntent? intent, string bootId, WindowMonitorSnapshot target)
    {
        var identity = target.TargetIdentity;
        if (intent is null || (int?)message["protocolVersion"] != 1
            || string.IsNullOrWhiteSpace((string?)message["requestId"])
            || (string?)message["bootId"] != bootId
            || (string?)message["observationSessionId"] != sessionId
            || intent.ObservationSessionId != sessionId
            || intent.MatchGeneration <= 0 || intent.Budget <= 0
            || string.IsNullOrWhiteSpace(intent.LeaseId)
            || intent.Window.FocusEpoch != 0 || intent.TakeoverGeneration != 0
            || identity is not { IsPresent: true }
            || intent.Window.Hwnd != target.TargetHwnd
            || intent.Window.Pid != target.TargetPid
            || intent.Window.ProcessInstanceToken != identity.ProcessInstanceToken)
            return false;
        if (intent.Kind == DomainActionKind.Bid)
            return (long?)message["ledgerRevision"] is >= 0
                && !string.IsNullOrWhiteSpace((string?)message["ledgerId"])
                && intent.Round is >= 1 and <= 5
                && intent.Amount is > 0 and <= 9_999_999
                && intent.Amount <= intent.MaxSafeBid && intent.Amount <= intent.Budget
                && !string.IsNullOrWhiteSpace(intent.ApprovalId);
        if (intent.Kind == DomainActionKind.ReturnLobby) return intent.Amount is null;
        if (intent.Kind == DomainActionKind.StartNextMatch) return intent.Amount is null && intent.Round == 0;
        if (AuctionPreparation.IsPreparation(intent.Kind)) return !string.IsNullOrWhiteSpace(intent.ApprovalId)
            && (AuctionPreparation.IsLobby(intent.Kind) ? intent.Round == 0
                && (intent.Kind is DomainActionKind.ConfirmToolRefill or DomainActionKind.ConfirmEntryFee ? intent.Amount is > 0 && intent.Amount <= intent.Budget : intent.Amount is null)
                : intent.Amount is null && intent.Round is >= 1 and <= 5);
        return false;
    }

    JsonObject Rejected(DomainIntent intent, string reason) => new()
    {
        ["type"] = "domain.action.dispatch.rejected",
        ["observationSessionId"] = sessionId,
        ["intentId"] = intent.IntentId,
        ["reason"] = reason,
        ["inputActions"] = false,
        ["decoder"] = "SCENE_ANCHOR",
    };

    static string Expected(DomainActionKind kind) => kind switch
    {
        DomainActionKind.Bid => "AUCTION",
        DomainActionKind.ReturnLobby => "SETTLEMENT",
        DomainActionKind.StartNextMatch => "LOBBY",
        _ => AuctionPreparation.ExpectedScene(kind) ?? "INVALID",
    };

    static readonly JsonSerializerOptions Json = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Converters = { new JsonStringEnumConverter() },
    };

    sealed class SwitchingObligations : IExecutionObligationPort
    {
        public MainProcessExecutionObligationPort? Bid;
        public bool CommitBeforeInput(DomainIntent intent) => intent.Kind switch
        {
            DomainActionKind.Bid => Bid?.CommitBeforeInput(intent) == true,
            DomainActionKind.ReturnLobby or DomainActionKind.StartNextMatch => true,
            _ when AuctionPreparation.IsPreparation(intent.Kind) => true,
            _ => false,
        };
        public bool CommitReceipt(DomainReceipt receipt) => receipt.Kind == DomainActionKind.Bid
            ? Bid?.CommitReceipt(receipt) == true : true;
    }

    sealed class GameFocus : IFocusSnapshotProvider
    {
        public long Target;
        public JsonObject? LastActivation;
        long sequence;
        public BorrowedFocus Borrow(Func<bool> noHardwareInput) => new(this, noHardwareInput);
        public sealed class BorrowedFocus : IDisposable
        {
            readonly GameFocus owner;
            readonly Func<bool> noHardwareInput;
            readonly long original;
            readonly WindowIdentity? originalIdentity;
            readonly Point cursor;
            int disposed;
            public bool Activated { get; }
            public BorrowedFocus(GameFocus owner, Func<bool> noHardwareInput)
            {
                this.owner=owner; this.noHardwareInput=noHardwareInput;
                original=GetForegroundWindow().ToInt64();
                originalIdentity=new WindowIdentityReader().Read(original);
                GetCursorPos(out cursor);
                Activated=owner.Activate();
            }
            public void Dispose()
            {
                if (Interlocked.Exchange(ref disposed, 1) != 0) return;
                // If the user chose a different window, never pull focus away.
                if (original==0 || original==owner.Target || GetForegroundWindow().ToInt64()!=owner.Target) return;
                bool StillBorrowed()
                {
                    if (GetForegroundWindow().ToInt64()!=owner.Target) return false;
                    var now=new WindowIdentityReader().Read(original);
                    return now is {IsPresent:true} && originalIdentity is not null
                        && now.Pid==originalIdentity.Pid && now.ProcessInstanceToken==originalIdentity.ProcessInstanceToken;
                }
                int attempts=0;
                bool restored=UserInputCourtesy.ReturnFocus(StillBorrowed,
                    () => { attempts++; return owner.ActivateWindow(original); }, () => Thread.Sleep(50));
                if (restored && noHardwareInput()) SetCursorPos(cursor.X,cursor.Y);
                Console.Error.WriteLine(new JsonObject { ["type"]="domain.action.focus-return",
                    ["target"]=original,["restored"]=restored,["attempts"]=attempts,
                    ["activation"]=owner.LastActivation?.DeepClone(),
                    ["hardwareInterrupted"]=!noHardwareInput(),["atNs"]=ProtocolClock.NowNs() }.ToJsonString());
            }
        }
        public bool Activate()
            => ActivateWindow(Target);
        bool ActivateWindow(long target)
        {
            var foreground = GetForegroundWindow();
            LastActivation=new JsonObject { ["foregroundBefore"]=foreground.ToInt64(),["target"]=target };
            if (foreground.ToInt64() == target) return true;
            // The caller, foreground owner and target are separate threads. Join
            // both input queues for one activation, then detach; send no keys.
            uint caller = GetCurrentThreadId();
            uint owner = GetWindowThreadProcessId(foreground, out _);
            uint targetOwner = GetWindowThreadProcessId(new IntPtr(target), out _);
            bool attached = owner != 0 && owner != caller && AttachThreadInput(caller, owner, true);
            bool targetAttached = targetOwner != 0 && targetOwner != caller && targetOwner != owner
                && AttachThreadInput(caller, targetOwner, true);
            LastActivation["callerThread"]=caller; LastActivation["foregroundThread"]=owner;
            LastActivation["attached"]=attached;
            LastActivation["targetThread"]=targetOwner; LastActivation["targetAttached"]=targetAttached;
            try
            {
                bool accepted=SetForegroundWindow(new IntPtr(target));
                long after=GetForegroundWindow().ToInt64();
                LastActivation["accepted"]=accepted;LastActivation["foregroundAfter"]=after;
                return after == target;
            }
            finally
            {
                if (targetAttached) AttachThreadInput(caller, targetOwner, false);
                if (attached) AttachThreadInput(caller, owner, false);
            }
        }
        public FocusSnapshot Capture()
            => ObserveForeground(GetForegroundWindow().ToInt64());

        internal FocusSnapshot ObserveForeground(long foreground)
        {
            // Each send still checks the actual foreground target. Returning
            // to that same game between actions must not invalidate all later
            // tickets because of an unrelated historical focus counter.
            return new(true, Target, foreground, 0, ++sequence, ProtocolClock.NowNs());
        }
        [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
        [StructLayout(LayoutKind.Sequential)] struct Point { public int X,Y; }
        [DllImport("user32.dll")] static extern bool GetCursorPos(out Point point);
        [DllImport("user32.dll")] static extern bool SetCursorPos(int x,int y);
        [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
        [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
        [DllImport("user32.dll")] static extern bool AttachThreadInput(uint caller, uint owner, bool attach);
    }
}
