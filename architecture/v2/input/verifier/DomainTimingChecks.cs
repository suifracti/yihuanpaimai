using NteHost.Input;

namespace NteHost.Input.Verifier;

// Fake-only execution of the real guard and executor. Never creates a window,
// installs hooks or invokes an OS input API. Delays model independent capture.
internal static class DomainTimingChecks
{
    public static int RunKeypad()
    {
        foreach(string mode in new[]{"ok","wrong-window","partial","throw"})
        {
            var observer=new FakeInputObserver(); var focus=new FakeFocusSnapshotProvider();
            var raw=new CountingRawInputBackend {PartialSendResult=mode=="partial"?1u:null,ThrowOnSend=mode=="throw"};
            var trace=new InMemoryInputTraceSink();
            var guard=new InputSafetyGuard(observer,focus,new FakeCursorBackend(),raw,trace,
                new InputSafetyOptions {EnableRestrictedDomainActions=true,RestoreCursorOnCleanRelease=false});
            observer.Start(e=>guard.OnObservedInput(e));
            Require(guard.Arm(new(1)).Ok,"KEYPAD_ARM");
            if(mode=="wrong-window") focus.SetForeground(2);
            var points=Enumerable.Range(0,7).Select(i=>new KeypadClick(10+i,20,100+i,200)).ToArray();
            var action=InputAction.DomainKeypad(222809,points,()=>true);
            var result=guard.Execute(action);
            int tickets=trace.Records.Count(r=>r.Phase==TracePhase.TicketIssued);
            Require(mode=="ok" ? result.Ok && raw.SendCallCount==7 && raw.InputsSentCount==21 && tickets==1
                : !result.Ok && raw.SendCallCount==(mode=="wrong-window"?0:1),"ONE_TICKET_ENTIRE_FILL:"+mode);
            if(mode=="ok") {
                long sequence=0;
                foreach(var point in points) foreach(var kind in new[]{InputEventKind.MouseMove,InputEventKind.MouseButtonDown})
                    observer.Emit(new(kind,InputDeviceClass.Mouse,InputEventOrigin.Injected,raw.SentExtraInfo[0],
                        point.X,point.Y,TraceClock.NowNs(),++sequence) {DomainCode=kind==InputEventKind.MouseButtonDown?1u:0u});
                Require(guard.State==GuardState.Armed,"WHOLE_FILL_OWN_CLICKS_NOT_TAKEOVER");
            }
            long sent=raw.SendCallCount;
            var ticket=new SendInputTicket(999,guard.AuthorityId,action.Fingerprint,0,long.MaxValue,1);
            ticket.TryConsume();
            Require(!guard.ExecuteWithTicket(action,ticket).Ok && raw.SendCallCount==sent,"CONSUMED_TICKET_CANNOT_RESEND_FILL");
            guard.Cancel("END"); guard.Release(); observer.Stop();
        }
        Console.WriteLine("PASS one ticket per whole keypad fill, wrong target rejected, partial/throw stops, consumed ticket cannot resend; zero OS input");
        return 0;
    }
    sealed class Raw(FakeInputObserver observer, bool click, int eventDelayMs) : IRawInputBackend
    {
        public long SendCallCount { get; private set; }
        public long InputsSentCount { get; private set; }
        public IReadOnlyList<ulong> SentExtraInfo => [];
        public uint Send(InputRecord[] inputs)
        {
            SendCallCount++;
            InputsSentCount += inputs.Length;
            if (eventDelayMs > 0) Thread.Sleep(eventDelayMs);
            long seq = 0;
            if (click)
            {
                Emit(InputEventKind.MouseMove, InputDeviceClass.Mouse, 0);
                Emit(InputEventKind.MouseButtonDown, InputDeviceClass.Mouse, 1);
            }
            else
                foreach (var input in inputs.Where(i => i.Type == 1 && i.Flags == 0))
                    Emit(InputEventKind.KeyDown, InputDeviceClass.Keyboard, input.MouseData);
            return (uint)inputs.Length;

            void Emit(InputEventKind kind, InputDeviceClass device, uint code) => observer.Emit(
                new(kind, device, InputEventOrigin.Injected, inputs[0].ExtraInfo,
                    10, 20, TraceClock.NowNs(), ++seq) { DomainCode = code });
        }
    }

    public static int Run()
    {
        foreach (bool click in new[] { true, false })
            foreach (string mode in new[] { "slow-valid", "current-rejected", "focus-changed", "cancelled", "ticket-expired", "late-event" })
                Check(click, mode);
        Console.WriteLine("PASS domain timing: 12 fake-only cases; zero OS input");
        return 0;
    }

    static void Check(bool click, string mode)
    {
        var observer = new FakeInputObserver();
        var focus = new FakeFocusSnapshotProvider();
        var raw = new Raw(observer, click, mode == "late-event" ? 300 : 0);
        var trace = new InMemoryInputTraceSink();
        var guard = new InputSafetyGuard(observer, focus, new FakeCursorBackend(), raw, trace,
            new InputSafetyOptions { EnableRestrictedDomainActions = true, RestoreCursorOnCleanRelease = false });
        observer.Start(e => guard.OnObservedInput(e));
        Require(guard.Arm(new(1)).Ok, "ARM");
        int reads = 0;
        bool Current()
        {
            if (++reads != 3) return true;
            // A slow callback must not expire a domain ticket or its own events.
            Thread.Sleep(mode == "ticket-expired" ? 550 : 300);
            if (mode == "focus-changed") focus.SetForeground(2);
            if (mode == "cancelled") guard.Cancel("TEST_USER_STOP");
            return mode != "current-rejected";
        }
        var action = click ? InputAction.DomainClick(10, 20, 100, 200, Current)
            : InputAction.DomainAmount(12345, Current);
        var outcome = guard.Execute(action);
        Console.WriteLine($"{(click ? "click" : "digits")}/{mode}: ok={outcome.Ok} sends={raw.SendCallCount} takeover={guard.UserTakeoverSeen} reason={outcome.Reason}");
        try
        {
            if (mode is "slow-valid" or "ticket-expired" or "late-event")
                Require(outcome.Ok && raw.SendCallCount == 1 && !guard.UserTakeoverSeen && guard.State == GuardState.Armed,
                    "OWN_INPUT_MUST_NOT_EXPIRE_DURING_CAPTURE");
            else
                Require(!outcome.Ok && raw.SendCallCount == 0, "FINAL_GATE_MUST_PREVENT_SEND");
            // A completed/failed action never authorizes a second raw send by itself.
            Require(guard.ExecuteWithTicket(action, null).Ok == false && raw.SendCallCount <= 1, "MISSING_TICKET");
        }
        finally { guard.Cancel("TEST_END"); guard.Release(); observer.Stop(); }
    }

    static void Require(bool ok, string reason)
    {
        if (!ok) throw new InvalidOperationException(reason);
    }
}
