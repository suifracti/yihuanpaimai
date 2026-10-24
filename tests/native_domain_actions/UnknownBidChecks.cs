using NteHost.DomainActions;
static class UnknownBidChecks {
 static void Check(bool ok,string msg) {if(!ok)throw new Exception(msg);}
 public static void Run() {
  var f=new Fixture();var i=f.Intent();f.Coordinator.Dispatch(i);f.Now+=4_000_000_000;
  Check(f.Coordinator.Poll()?.Status==ReceiptStatus.UNKNOWN,"FIRST_UNKNOWN");
  Check(f.Coordinator.Dispatch(i).Status==ReceiptStatus.UNKNOWN && f.Port.Sends==1,"NO_RESEND");
  var ev=f.Evidence(i) with {EvidenceRef="real-seat"};
  Check(f.Coordinator.Confirm(ev).Status==ReceiptStatus.CONFIRMED,"LATE_SAME_ROUND_CONFIRM");
  f.Scope=f.Scope with {Round=2,CapturedNs=f.Now,LeaseExpiresNs=f.Now+9_000_000_000};
  var next=f.Intent("bid-2");Check(f.Coordinator.Dispatch(next).Status==ReceiptStatus.SENT_PENDING_CONFIRMATION,"NEXT_ROUND_CONTINUES");
  f.Now+=4_000_000_000;Check(f.Coordinator.Poll()?.Reason=="SECOND_BID_UNKNOWN","SECOND_UNKNOWN_STOPS");
  f.Scope=f.Scope with {Round=3,CapturedNs=f.Now,LeaseExpiresNs=f.Now+9_000_000_000};
  Check(f.Coordinator.Dispatch(f.Intent("bid-3")).Status==ReceiptStatus.NOT_SENT,"STOP_AFTER_SECOND");
  var other=new Fixture();var oi=other.Intent();other.Coordinator.Dispatch(oi);other.Now+=4_000_000_000;other.Coordinator.Poll();
  Check(other.Coordinator.Confirm(other.Evidence(oi) with {OriginRound=2}).Status==ReceiptStatus.UNKNOWN,"OTHER_ROUND_NOT_CONFIRM");
  other.Coordinator.MarkUnknown(oi.IntentId,"OWN_BID_AMOUNT_MISMATCH");
  other.Scope=other.Scope with {Round=2,CapturedNs=other.Now,LeaseExpiresNs=other.Now+9_000_000_000};
  Check(other.Coordinator.Dispatch(other.Intent("next")).Status==ReceiptStatus.NOT_SENT,"MISMATCH_STOPS");
  Console.WriteLine("PASS first unknown no resend, same-round late confirm, next round continues, second unknown and mismatch stop");
 }
}
