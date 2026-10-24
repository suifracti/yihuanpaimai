using NteHost.DomainActions;

static class CourtesyChecks
{
    static void Check(bool value, string reason) { if (!value) throw new Exception(reason); Console.WriteLine("PASS "+reason); }
    sealed class YieldPort : IRestrictedDomainInputPort
    {
        public int Calls;
        public bool ConfirmAttempted;
        public PortOutcome TrySend(DomainIntent intent, Func<bool> current)
        {
            Calls++;
            return Calls==1 ? new(ConfirmAttempted,false,"USER_INPUT_YIELD") {BidConfirmationAttempted=ConfirmAttempted}
                : new(true,true,"SENT") {BidConfirmationAttempted=true};
        }
    }
    public static void Run()
    {
        int restores=0, pauses=0;
        Check(UserInputCourtesy.ReturnFocus(()=>true,()=>++restores==2,()=>pauses++)
            && restores==2 && pauses==1,"temporary focus refusal retries only restoration");
        restores=0; pauses=0;
        Check(!UserInputCourtesy.ReturnFocus(()=>true,()=>{restores++;return false;},()=>pauses++)
            && restores==3 && pauses==2,"persistent focus refusal is bounded");
        restores=0; bool borrowed=true;
        Check(!UserInputCourtesy.ReturnFocus(()=>borrowed,()=>{restores++;return false;},()=>borrowed=false)
            && restores==1,"user choosing another window prevents another focus request");
        var idle=new UserInputCourtesy(); idle.HardwareInput(2_000_000_000);
        Check(!idle.IsIdle(3_499_999_999) && idle.IsIdle(3_500_000_000),"wait 1.5 seconds after hardware input");
        var before=idle.Sequence; idle.HardwareInput(4_000_000_000);
        Check(!idle.Uninterrupted(before),"hardware interrupts current edit without permanent stop");
        Check(UserInputCourtesy.CanRetry(new(true,false,"partial edit") {BidConfirmationAttempted=false},true),"unfinished amount may clear and refill");
        Check(!UserInputCourtesy.CanRetry(new(true,false,"unknown confirmation") {BidConfirmationAttempted=true},true),"unknown confirmation cannot retry");
        Check(!UserInputCourtesy.CanRetry(new(true,true,"sent"),true),"completed send is not undone by later activity");
        var f=new Fixture(); var port=new YieldPort();
        var coordinator=new DomainActionCoordinator(()=>f.Scope,()=>f.Now,port);
        var intent=f.Intent();
        Check(coordinator.Dispatch(intent).Reason=="USER_INPUT_YIELD","yield has no attempted bid");
        Check(coordinator.Dispatch(intent).Status==ReceiptStatus.SENT_PENDING_CONFIRMATION && port.Calls==2,"same unsent intent resumes once idle");
        coordinator.Dispatch(intent);
        Check(port.Calls==2,"sent intent never replays");
        port=new YieldPort {ConfirmAttempted=true};
        coordinator=new DomainActionCoordinator(()=>f.Scope,()=>f.Now,port);
        Check(coordinator.Dispatch(intent).Status==ReceiptStatus.UNKNOWN,"interrupted confirmation remains unknown");
        coordinator.Dispatch(intent);
        Check(port.Calls==1,"unknown bid never replays");
    }
}
