const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const html = fs.readFileSync('core/overlay_alpha.html','utf8');
const start = html.indexOf('    function paintTrustedLiveResult(d)');
const end = html.indexOf('\n    function ', start + 10);
const elements = new Map();
const sandbox = {document:{getElementById(id){
  if(!elements.has(id)) elements.set(id,{textContent:'',classList:{toggle(){},remove(){},add(){}}});
  return elements.get(id);
}},fmtWan:x=>String(x),paintLeadFact(){},paintDraftSaveState(){},paintManualCommandResult(){},saveCopy:()=>({text:'',ok:false}),manualState:{}};
vm.createContext(sandbox);
const helperStart = html.indexOf("    function formatExpectedProfit(value)");
vm.runInContext(html.slice(helperStart, html.indexOf("\n    function ", helperStart + 10)), sandbox);
vm.runInContext(html.slice(start,end),sandbox);
for(const [payload,label] of [
  [{scene:'OPEN_WORLD',shadowUpdating:false},'等待进入拍卖'],
  [{scene:'IN_AUCTION',shadowUpdating:false},'情报不足'],
  [{scene:'IN_AUCTION',shadowUpdating:false,solverMissingReason:'缺失会场'},'缺失会场'],
  [{scene:'IN_AUCTION',shadowUpdating:true},'正在计算'],
  [{scene:'SETTLEMENT',shadowUpdating:false},'本局已结算'],
]) {
  sandbox.payload=payload;
  vm.runInContext('paintTrustedLiveResult(payload)',sandbox);
  assert(elements.get('topActionBadge').textContent.includes(label));
  if (payload.solverMissingReason) {
    assert.equal(elements.get('actionReason').textContent, `暂不生成出价建议：${payload.solverMissingReason}`);
  }
}
const escapeStart = html.indexOf('    function escapeHtml(str)');
const seatsStart = html.indexOf('    function paintLiveSeatsAndIntel(d)');
vm.runInContext(html.slice(escapeStart, html.indexOf('\n    function ', escapeStart + 10)), sandbox);
vm.runInContext(html.slice(seatsStart, html.indexOf('\n    function ', seatsStart + 10)), sandbox);
sandbox.auctionPayload = {
  seats: [
    {slot:1, currentBid:999999}, {slot:2, currentBid:1088888},
    {slot:3, currentBid:999999}, {slot:4, currentBid:1000000, isMe:true},
  ],
  auctionEvidence: {intel:[{round:5, rawText:'本局内所有金色品质藏品的平均价值为85，410。'}]},
};
vm.runInContext('paintLiveSeatsAndIntel(auctionPayload)', sandbox);
for(const amount of ['999999','1088888','1000000']) {
  assert(elements.get('liveSeats').innerHTML.includes(amount));
}
assert(elements.get('liveIntel').innerHTML.includes('85，410'));
sandbox.auctionPayload.observationSessionId = 'session-a';
sandbox.auctionPayload.matchId = 'match-a';
sandbox.auctionPayload.round = 5;
sandbox.auctionPayload.frame = {capturedAtUtc:'2026-09-26T11:50:20Z'};
vm.runInContext('paintLiveSeatsAndIntel(auctionPayload)', sandbox);
sandbox.auctionPayload.frame = {capturedAtUtc:'2026-09-26T11:50:21Z'};
sandbox.auctionPayload.seats = [{slot:2, currentBid:null, bid:123, name:'可可'}];
vm.runInContext('paintLiveSeatsAndIntel(auctionPayload)', sandbox);
assert(elements.get('liveSeats').innerHTML.includes('上次 1088888'));
assert(!elements.get('liveSeats').innerHTML.includes('>123<'));
sandbox.auctionPayload.round = 4;
vm.runInContext('paintLiveSeatsAndIntel(auctionPayload)', sandbox);
assert(!elements.get('liveSeats').innerHTML.includes('1088888'));
sandbox.auctionPayload.nativeInvalidated = true;
vm.runInContext('paintLiveSeatsAndIntel(auctionPayload)', sandbox);
assert.equal(elements.get('liveSeats').textContent, '当前无有效出价');
console.log('overlay distinguishes navigation, missing facts, active calculation and settlement: passed');
