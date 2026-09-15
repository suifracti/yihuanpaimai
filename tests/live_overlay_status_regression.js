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
}},fmtWan:x=>String(x),paintLeadFact(){},saveCopy:()=>({text:'',ok:false}),manualState:{}};
vm.createContext(sandbox);
const helperStart = html.indexOf("    function formatExpectedProfit(value)");
vm.runInContext(html.slice(helperStart, html.indexOf("\n    function ", helperStart + 10)), sandbox);
vm.runInContext(html.slice(start,end),sandbox);
for(const [payload,label] of [
  [{scene:'OPEN_WORLD',shadowUpdating:false},'等待进入拍卖'],
  [{scene:'IN_AUCTION',shadowUpdating:false},'情报不足'],
  [{scene:'IN_AUCTION',shadowUpdating:true},'正在计算'],
  [{scene:'SETTLEMENT',shadowUpdating:false},'本局已结算'],
]) {
  sandbox.payload=payload;
  vm.runInContext('paintTrustedLiveResult(payload)',sandbox);
  assert(elements.get('topActionBadge').textContent.includes(label));
}
console.log('overlay distinguishes navigation, missing facts, active calculation and settlement: passed');
