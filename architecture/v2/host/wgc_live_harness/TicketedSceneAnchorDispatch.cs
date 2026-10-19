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
    readonly SceneAnchorGameDecoder decoder;
    readonly InputSafetyGuard guard;
    readonly Win32LowLevelInputObserver observer;
    readonly GameFocus focus;
    readonly SwitchingObligations obligations;
    readonly NativeDomainActionRuntime runtime;
    readonly WindowsTicketedDomainBackend backend;
    readonly object gate = new();
    readonly string sessionId;
    readonly Action<JsonObject> publish;
    Func<DomainIntent, NativeDomainFrame?>? engineCapture;
    DomainIntent? current;
    DomainIntent? pending;
    NativeDomainFrame? pinned;
    bool confirming;
    bool usePinned;
    bool settlementReturned;
    bool armed;
    bool disposed;

    TicketedSceneAnchorDispatch(string sessionId, SceneAnchorGameDecoder decoder, InputSafetyGuard guard,
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

    public static TicketedSceneAnchorDispatch? TryCreate(string anchorDirectory, string sessionId, long hwnd,
        Action<JsonObject> publish)
    {
        if (hwnd == 0 || publish is null) return null;
        var decoder = SceneAnchorGameDecoder.Load(anchorDirectory);
        if (!decoder.Ready) return null;
        decoder.ReadAmount = SceneAnchorOcr.Read;
        decoder.ReadCommittedAmount = SceneAnchorOcr.Read;
        var focus = new GameFocus { Target = hwnd };
        var observer = new Win32LowLevelInputObserver("scene-anchor");
        var guard = new InputSafetyGuard(observer, focus, new Win32CursorBackend(), new Win32RawInputBackend(), null,
            new InputSafetyOptions { EnableRestrictedDomainActions = true, RestoreCursorOnCleanRelease = false });
        if (!observer.Start(observed => guard.OnObservedInput(observed)).Ok)
        {
            observer.Stop();
            return null;
        }
        TicketedSceneAnchorDispatch? dispatch = null;
        var obligations = new SwitchingObligations();
        var evidence = new CapturedDomainControlEvidence(() => dispatch!.CaptureEngine(), decoder);
        var backend = new WindowsTicketedDomainBackend(guard, evidence, obligations, ProtocolClock.NowNs, hwnd, allowGameInput: true);
        var coordinator = new DomainActionCoordinator(() => dispatch!.CaptureEngine()?.Scope, ProtocolClock.NowNs,
            new RestrictedDomainInputPort(backend, ProtocolClock.NowNs));
        var runtime = new NativeDomainActionRuntime(coordinator, new(decoder, ProtocolClock.NowNs), obligations,
            message => dispatch!.publish(message));
        dispatch = new(sessionId, decoder, guard, observer, focus, obligations, backend, runtime, publish);
        return dispatch;
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
            confirming = false;
            DomainReceipt receipt;
            try { receipt = runtime.Dispatch(intent); }
            finally { current = pending; }
            if (receipt.Status == ReceiptStatus.SENT_PENDING_CONFIRMATION) pending = intent;
            else if (receipt.Status == ReceiptStatus.UNKNOWN) pending = null;
            return true;
        }
    }

    public void Observe(NativeDomainFrame? engine)
    {
        lock (gate)
        {
            var intent = pending;
            if (engine is null || intent is null) return;
            // A frame that cannot confirm must not be polled. Continuity loss
            // latches UNKNOWN, and that same coordinator can never return.
            if (!CanConfirm(intent, engine) && ProtocolClock.NowNs() < intent.DeadlineNs) return;
            current = intent;
            confirming = true;
            usePinned = true;
            pinned = engine;
            DomainReceipt? receipt;
            try
            {
                receipt = runtime.OnIndependentCapture(intent.IntentId, engine,
                    new OwnSeatBinding(SceneAnchorGameDecoder.OwnCommittedBidSlot, SceneAnchorGameDecoder.OwnCommittedBidIdentity));
            }
            finally
            {
                usePinned = false;
                pinned = null;
                confirming = false;
                current = null;
            }
            if (receipt?.Status == ReceiptStatus.CONFIRMED)
            {
                if (receipt.Kind == DomainActionKind.ReturnLobby) settlementReturned = true;
                pending = null;
            }
            else if (receipt?.Status == ReceiptStatus.UNKNOWN) pending = null;
        }
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        try { guard.Cancel("OBSERVATION_STOPPED"); } catch { }
        try { guard.Release(); } catch { }
        observer.Stop();
    }

    NativeDomainFrame? CaptureEngine()
    {
        var intent = current;
        if (intent is null) return null;
        NativeDomainFrame? engine;
        if (usePinned) engine = pinned;
        else
        {
            var capture = engineCapture;
            if (capture is null) return null;
            try { engine = capture(intent); }
            catch { return null; }
        }
        return engine is null ? null : Authorize(engine, intent, confirming);
    }

    bool CanConfirm(DomainIntent intent, NativeDomainFrame engine)
    {
        DecodedDomainFrame? view;
        try { view = decoder.Decode(engine); }
        catch { return false; }
        if (view is null) return false;
        return intent.Kind switch
        {
            DomainActionKind.Bid => (view.Scene is "AUCTION" or "AUCTION_R1")
                && view.OwnBid?.Amount == intent.Amount,
            DomainActionKind.ReturnLobby => view.Scene == "LOBBY"
                && view.MatchId == intent.MatchId && view.MatchGeneration == intent.MatchGeneration,
            DomainActionKind.StartNextMatch => view.Scene == "AUCTION_R1" && view.Round == 1
                && !string.IsNullOrWhiteSpace(view.MatchId) && view.MatchId != intent.MatchId
                && view.MatchGeneration > intent.MatchGeneration,
            _ => false,
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

    NativeDomainFrame Authorize(NativeDomainFrame engine, DomainIntent intent, bool confirmingFrame)
    {
        DecodedDomainFrame? view = null;
        try { view = decoder.Decode(engine); } catch { view = null; }
        string scene = view?.Scene ?? "UNKNOWN";
        string expected = Expected(intent.Kind);
        bool confirmScene = intent.Kind switch
        {
            DomainActionKind.Bid => scene is "AUCTION" or "AUCTION_R1",
            DomainActionKind.ReturnLobby => scene == "LOBBY",
            DomainActionKind.StartNextMatch => scene == "AUCTION_R1",
            _ => false,
        };
        bool pixelsMatch = confirmingFrame ? confirmScene : scene == expected;
        bool identity = intent.Window.Hwnd == engine.Scope.Window.Hwnd
            && intent.Window.Pid == engine.Scope.Window.Pid
            && intent.Window.ProcessInstanceToken == engine.Scope.Window.ProcessInstanceToken;
        var scope = engine.Scope with
        {
            Budget = intent.Budget,
            ApprovedAmountLimit = intent.Kind == DomainActionKind.Bid ? intent.MaxSafeBid : intent.Budget,
            Scene = confirmingFrame ? scene : expected,
            LeaseId = intent.LeaseId,
            LeaseExpiresNs = intent.DeadlineNs,
            TakeoverGeneration = intent.TakeoverGeneration,
            Connected = true,
            ExecutionAuthorized = pixelsMatch && engine.Scope.ForegroundMatches,
            SettlementArchived = scene == "SETTLEMENT" || settlementReturned,
            NewMatchAdmission = settlementReturned && scene == "LOBBY",
            ApprovalId = intent.ApprovalId,
            Window = identity ? intent.Window : engine.Scope.Window,
        };
        return new(scope, engine.Geometry, engine.Pixels.ToArray(), engine.Stride);
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
        _ => "INVALID",
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
            _ => false,
        };
        public bool CommitReceipt(DomainReceipt receipt) => receipt.Kind == DomainActionKind.Bid
            ? Bid?.CommitReceipt(receipt) == true : true;
    }

    sealed class GameFocus : IFocusSnapshotProvider
    {
        public long Target;
        long epoch, sequence, lastForeground = long.MinValue;
        bool seen;
        public FocusSnapshot Capture()
        {
            long foreground = GetForegroundWindow().ToInt64();
            if (!seen) { seen = true; lastForeground = foreground; }
            else if (foreground != lastForeground) { lastForeground = foreground; epoch++; }
            return new(true, Target, foreground, epoch, ++sequence, ProtocolClock.NowNs());
        }
        [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    }
}
