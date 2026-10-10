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
if (process.argv.includes('--saved-advice')) {
  const formatStart = html.indexOf('    function fmtWan(');
  vm.runInContext(html.slice(formatStart, html.indexOf('\n    function ', formatStart + 10)), sandbox);
  const file = process.argv[process.argv.indexOf('--saved-advice') + 1];
  const replay = JSON.parse(fs.readFileSync(file, 'utf8'));
  const payload = replay.mainPayload;
  sandbox.payload = payload;
  vm.runInContext('paintTrustedLiveResult(payload)', sandbox);
  assert.equal(payload.solverStatus, 'valid');
  assert.equal(payload.frozenPrediction.decision.recommendedMax, null);
  assert.equal(elements.get('topRecommendedMax').textContent, '580,238');
  assert.match(elements.get('topCapLabel').textContent, /结构参考/);
  assert.match(elements.get('recommendedMax').textContent, /非正式上限/);
  assert.match(elements.get('actionReason').textContent, /历史记录 0 条/);
  assert.match(elements.get('pRange').textContent, /仅部分候选，非整仓范围/);
  assert.equal(payload.predictionSnapshot.forecast.quantiles, null);
  const hud = Object.fromEntries(['topActionBadge','topCapLabel','topRecommendedMax','p50Label','pRange','actionReason']
    .map(id => [id, elements.get(id).textContent]));
  const mainSource = fs.readFileSync('core/main_window.js', 'utf8');
  const mainSandbox = { document:sandbox.document, dashboard:{} };
  vm.createContext(mainSandbox);
  for (const name of ['escapeHtml', 'formatCurrency', 'renderMatchFocus']) {
    const begin = mainSource.indexOf(`function ${name}(`);
    const next = mainSource.indexOf('\nfunction ', begin + 10);
    vm.runInContext(mainSource.slice(begin, next), mainSandbox);
  }
  mainSandbox.currentMatch = payload.currentMatch;
  vm.runInContext('renderMatchFocus(currentMatch)', mainSandbox);
  assert.equal(elements.get('match-focus-amount').textContent, '580,238');
  assert.match(elements.get('match-focus-result-type').textContent, /非正式上限/);
  const main = Object.fromEntries(['match-focus-amount','match-focus-result-type','match-focus-secondary','match-focus-reason']
    .map(id => [id, elements.get(id).textContent]));
  // Even a valid cached snapshot cannot revive the display after revocation.
  sandbox.payload = {...payload, nativeInvalidated:true};
  vm.runInContext('paintTrustedLiveResult(payload)', sandbox);
  assert.equal(elements.get('topRecommendedMax').textContent, '—');
  assert.match(elements.get('topActionBadge').textContent, /暂停/);
  const receipt = {passed:true, verificationMode:'saved-offline-render', desktopAcceptance:false,
    gameCapture:false, gameInput:false, main, hud, revokedSnapshotHidden:true};
  fs.writeFileSync(pathForReceipt(file), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
  process.exit(0);
}
function pathForReceipt(file) { return require('path').join(require('path').dirname(file), 'display-result.json'); }
for(const [payload,label] of [
  [{scene:'OPEN_WORLD',shadowUpdating:false},'等待进入拍卖'],
  [{scene:'IN_AUCTION',shadowUpdating:false},'情报不足'],
  [{scene:'IN_AUCTION',shadowUpdating:false,solverMissingReason:'缺失会场'},'缺失会场'],
  [{scene:'IN_AUCTION',shadowUpdating:true},'正在计算'],
  [{scene:'UNKNOWN',nativeInvalidated:true,shadowUpdating:false},'观察已暂停'],
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
