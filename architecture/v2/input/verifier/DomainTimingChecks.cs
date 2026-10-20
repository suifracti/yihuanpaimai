using NteHost.Input;

namespace NteHost.Input.Verifier;

// Fake-only execution of the real guard and executor. Never creates a window,
// installs hooks or invokes an OS input API. Delays model independent capture.
internal static class DomainTimingChecks
{
    sealed class Raw(FakeInputObserver observer, bool click, int eventDelayMs) : IRawInputBackend
    {
        public long SendCallCount { get; private set; }
        public long InputsSentCount { get; private set; }
        public IReadOnlyList<ulong> SentExtraInfo => [];
        long downAt;
        public bool VisiblePress { get; private set; }
        public uint Send(InputRecord[] inputs)
        {
            SendCallCount++;
            InputsSentCount += inputs.Length;
            if (eventDelayMs > 0) Thread.Sleep(eventDelayMs);
            long seq = 0;
            if (click)
            {
                foreach (var input in inputs)
                {
                    if ((input.Flags & 1) != 0) Emit(InputEventKind.MouseMove, InputDeviceClass.Mouse, 0);
                    if ((input.Flags & 2) != 0) { downAt=TraceClock.NowNs(); Emit(InputEventKind.MouseButtonDown, InputDeviceClass.Mouse, 1); }
                    if ((input.Flags & 4) != 0) VisiblePress=TraceClock.NowNs()-downAt>=40_000_000;
                }
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
            {
                if(click) Require(raw.VisiblePress,"PRESS_MUST_SPAN_A_GAME_POLL_INSTEAD_OF_DOWN_UP_IN_ONE_BATCH");
                Require(outcome.Ok && raw.SendCallCount == (click ? 2 : 1) && !guard.UserTakeoverSeen && guard.State == GuardState.Armed,
                    "OWN_INPUT_MUST_NOT_EXPIRE_DURING_CAPTURE");
            }
            else
                Require(!outcome.Ok && raw.SendCallCount == 0, "FINAL_GATE_MUST_PREVENT_SEND");
            // A completed/failed action never authorizes a second raw send by itself.
            Require(guard.ExecuteWithTicket(action, null).Ok == false && raw.SendCallCount <= (click ? 2 : 1), "MISSING_TICKET");
        }
        finally { guard.Cancel("TEST_END"); guard.Release(); observer.Stop(); }
    }

    static void Require(bool ok, string reason)
    {
        if (!ok) throw new InvalidOperationException(reason);
    }
}
