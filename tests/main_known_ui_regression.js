const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
class Element {
  constructor() { this.value=''; this.dataset={}; this.hidden=true; this.handlers={}; this.children=[]; this.style={}; }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  fire(name, event={}) { for(const fn of this.handlers[name] || []) fn(event); }
  set innerHTML(value) { this.html=value; this._textContent=''; this.children=[...value.matchAll(/class="suggest-item known-suggest-item" data-index="(\d+)"/g)].map(m=>{ const e=new Element();e.dataset.index=m[1];return e; }); }
  get innerHTML() { return this.html || ''; }
  set textContent(value) { this._textContent=String(value ?? ''); this.html=''; this.children=[]; }
  get textContent() { return this._textContent || ''; }
  querySelectorAll(selector) {
    if (selector === '.suggest-item') return this.children;
    const result=[];
    for(const child of this.children) {
      if (selector === 'button' && child.tagName === 'button') result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children=[]; }
  setCustomValidity(message) { this.error=message; }
  reportValidity() {}
}
const elements = new Map();
for(const rarity of ['gold','purple','red']) for(const prefix of ['match-input-known-','match-suggest-','match-chips-']) elements.set(prefix+rarity,new Element());
const sandbox={console,setTimeout,clearTimeout,URLSearchParams,document:{addEventListener(){},getElementById:id=>elements.get(id)||null,querySelectorAll:()=>[]}, window:{addEventListener(){},setTimeout,clearTimeout,location:{search:''}},performance};
sandbox.window.AuctionEngineV06=require('../core/auction_engine_v06.js');
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(require.resolve('../core/main_window.js'),'utf8'),sandbox);
const liveSeatsGrid=new Element(), liveIntelTimeline=new Element();
elements.set('match-seats-grid',liveSeatsGrid);
elements.set('match-intel-timeline',liveIntelTimeline);
const observedAuction={
  observationProfile:'native-readonly-v1', observationStatus:'FRAME',
  visionHealth:{profile:'native-readonly-v1',status:'READY',stage:'native-frame'},
  bidding:{hiddenBids:false,seats:[
    {slot:1,name:'旅行的意义',currentBid:450000},
    {slot:2,name:'何海良',currentBid:708520},
    {slot:3,name:'枫',currentBid:400000},
    {slot:4,name:'PLAYER_LOCAL',currentBid:0,isMe:true}
  ]},
  publicIntel:{timeline:{observations:[
    {round:3,participation:'recorded',text:'金品均价仪器 本局内所有金色品质藏品的平均价值为40，615。'}
  ]}}
};
sandbox.observedAuction=observedAuction;
vm.runInContext('renderCurrentAuctionDetails(observedAuction)',sandbox);
for(const amount of ['450,000','708,520','400,000','>0<']) assert(liveSeatsGrid.innerHTML.includes(amount),amount);
assert(liveSeatsGrid.innerHTML.includes('何海良'));
assert(liveSeatsGrid.innerHTML.includes('>0<'));
assert(liveIntelTimeline.innerHTML.includes('40，615'));
vm.runInContext("renderCurrentAuctionDetails({...observedAuction,observationStatus:'PAUSED',visionHealth:{profile:'native-readonly-v1',status:'ERROR',stage:'native-paused'}})",sandbox);
assert(liveSeatsGrid.textContent.includes('观察已暂停'));
assert(!liveSeatsGrid.innerHTML.includes('708,520'));
assert(liveIntelTimeline.textContent.includes('保留在本局草稿中'));
console.log('live Main shows current four-seat bids and raw intel only for a fresh Native frame, then hides paused values: passed');
vm.runInContext('syncMatchFacts=()=>{}; setupKnownItemsAutocomplete();',sandbox);
const input=elements.get('match-input-known-gold'), suggestions=elements.get('match-suggest-gold');
input.value='电话';input.fire('input');
assert(suggestions.innerHTML.includes('赤色来电'));assert.equal(suggestions.hidden,false);
let prevented=false;suggestions.children[0].fire('pointerdown',{preventDefault(){prevented=true;}});assert(prevented);
suggestions.children[0].fire('click');input.fire('change');
assert.equal(vm.runInContext('serializeKnownChips("gold")',sandbox),'赤色来电');
input.value='澄空';input.fire('input');assert(suggestions.innerHTML.includes('澄空之眼'));
input.fire('keydown',{key:'Enter',isComposing:true});assert.equal(input.value,'澄空');
suggestions.children[0].fire('click');
assert.equal(vm.runInContext('serializeKnownChips("gold")',sandbox),'赤色来电+澄空之眼');
input.value='不存在';input.fire('change');assert(input.error.includes('找不到'));
assert.equal(vm.runInContext('dashboard.knownChips.gold.length',sandbox),2);
console.log('catalog suggestions, IME, single-click single commit and invalid-input feedback: passed');
input.value='赤色来电/澄空';input.fire('input');
assert(suggestions.innerHTML.includes('澄空之眼'));
suggestions.children[0].fire('click');
assert(vm.runInContext('serializeKnownChips("gold")',sandbox).includes('赤色来电/澄空之眼'));
console.log('slash alternative completion preserves the expression: passed');
const sent=[];
sandbox.window.chrome={webview:{postMessage:text=>sent.push(JSON.parse(text))}};
sandbox.document.createElement=tag=>{const el=new Element();el.tagName=tag;return el;};
elements.set('warehouse-originals',new Element());
vm.runInContext("requestOriginalScreenshots('shot-match', 'warehouse-originals')",sandbox);
let req=sent.at(-1);
sandbox.reply={type:'app_status',action:req.action,requestId:req.requestId,originalScreenshots:{ok:true,recordId:'shot-match',images:[{evidenceId:'shot1',capturedAt:'now',dataUrl:'data:image/png;base64,AA=='}]}};
vm.runInContext('handleNativeMessage({data:reply})',sandbox);
const gallery=elements.get('warehouse-originals');
const remove=gallery.querySelectorAll('button').find(x=>x.textContent==='删除截图');
assert(remove);
remove.fire('click',{preventDefault(){},stopPropagation(){}});
req=sent.at(-1);assert.equal(req.action,'delete_original_screenshot');assert.equal(req.evidenceId,'shot1');
sandbox.reply={type:'app_status',action:req.action,requestId:req.requestId,originalScreenshots:{ok:true,recordId:'shot-match',images:[],undoEvidenceId:'shot1'}};
vm.runInContext('handleNativeMessage({data:reply})',sandbox);
const undo=gallery.querySelectorAll('button').find(x=>x.textContent==='撤销删除');assert(undo);
undo.fire('click');assert.equal(sent.at(-1).action,'restore_original_screenshot');
assert.equal(sent.at(-1).evidenceId,'shot1');
console.log('per-image delete and undo button routing: passed');
const evidenceParent=new Element();sandbox.evidenceParent=evidenceParent;
sandbox.evidenceRecord={auctionEvidence:{intel:[{round:2,lines:[{text:'随机展示5件藏品。'}]}],
  bids:[{round:2,seats:[{slot:1,currentBid:1222222},{slot:2,currentBid:0},{slot:3,currentBid:555555},{slot:4,currentBid:666666}]}],
  warehouse:[{scene:'SETTLEMENT',slots:[{w:2,h:2,identityStatus:'UNKNOWN',identifiedName:'不能冒充已识别'}]}],
  flow:[{scene:'TOOL_REPLENISH_CONFIRM'}],priorMatchActivity:[{}],replenishment:'CONFIRMATION_SEEN'}};
vm.runInContext('renderAuctionEvidence(evidenceRecord,evidenceParent)',sandbox);
const evidenceSection=evidenceParent.children[0];assert.equal(evidenceSection.children.length,4);
const textOf=e=>(e.textContent||'')+e.children.map(textOf).join('\n');
const historyText=textOf(evidenceSection);
for(const text of ['随机展示5件藏品','座位 2：0','666666','补货确认','前局遗留','未确认名称']) assert(historyText.includes(text),text);
assert(!historyText.includes('不能冒充已识别'));
console.log('history shows raw intel, four seats including zero, uncertain inventory and prior-match restock: passed');
