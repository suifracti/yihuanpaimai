const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');

class Element {
  constructor() { this.hidden = true; this.textContent = ''; this.children = []; this.dataset = {}; this.listeners = {}; this.attributes = {}; }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; this.textContent = ''; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  click() { if (this.listeners.click) this.listeners.click({ target: this }); }
  removeAttribute(name) { delete this.attributes[name]; if (name === 'src') this.src = ''; }
  setAttribute(name, value) { this.attributes[name] = value; }
}

const ids = [
  'match-bid-intent-status', 'match-bid-intent-title', 'match-bid-intent-detail',
  'match-bid-intent-execution', 'match-bid-intent-budget', 'match-bid-intent-receipt',
  'history-native-raw-partial', 'history-native-raw-partial-pages',
  'history-native-raw-partial-status', 'history-native-raw-partial-image',
  'history-native-raw-partial-meta',
];
const elements = new Map(ids.map(id => [id, new Element()]));
const posted = [];
const sandbox = {
  console, setTimeout, clearTimeout, URLSearchParams, performance,
  document: {
    addEventListener() {},
    getElementById: id => elements.get(id) || null,
    createElement: () => new Element(),
    querySelectorAll: () => [],
  },
  window: { addEventListener() {}, setTimeout, clearTimeout, location: { search: '' },
    chrome: { webview: { postMessage: value => posted.push(JSON.parse(value)) } } },
};
sandbox.window.AuctionEngineV06 = require('../core/auction_engine_v06.js');
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../core/main_window.js'), 'utf8'), sandbox);

const current = {
  observationProfile: 'native-readonly-v1',
  matchId: 'match-1', round: 2, automaticExecutionEnabled: false,
  bidActionBackendStatus: 'NOT_CONNECTED', bidActionReceipt: null,
  bidIntent: {
    status: 'READY', executionEnabled: false, maxSafeBid: 153000,
    valuationBasis: 'FEASIBLE_LOWER_BOUND_NOT_P50',
    binding: { matchId: 'match-1', matchGeneration: 7, observationSessionId: 'session-1', round: 2, factsRevision: 8 },
    source: { predictionId: 'prediction-1' },
    budget: { approved: false, available: null },
    prohibitions: ['BUDGET_APPROVAL_REQUIRED'],
  },
};
sandbox.renderBidIntentStatus(current);
assert.equal(elements.get('match-bid-intent-status').hidden, false);
assert.match(elements.get('match-bid-intent-title').textContent, /仅供审阅/);
assert.match(elements.get('match-bid-intent-detail').textContent, /153,000.*不是 P50/);
assert.equal(elements.get('match-bid-intent-execution').textContent, '自动执行：关闭');
assert.match(elements.get('match-bid-intent-budget').textContent, /未批准.*余额未知/);
assert.match(elements.get('match-bid-intent-receipt').textContent, /暂无记录.*发送端未接入/);

const boundReceipt = {
  kind: 'Bid', intentId: 'intent-1', status: 'CONFIRMED', matchId: 'match-1', matchGeneration: 7,
  observationSessionId: 'session-1', round: 2, factsRevision: 8,
};
sandbox.renderBidIntentStatus({ ...current, bidActionReceipt: boundReceipt });
assert.match(elements.get('match-bid-intent-receipt').textContent, /已收到绑定的游戏确认/);

sandbox.renderBidIntentStatus({ ...current, bidActionReceipt: { ...boundReceipt, matchId: 'other-match' } });
assert.match(elements.get('match-bid-intent-receipt').textContent, /范围或状态未核实/);
assert.doesNotMatch(elements.get('match-bid-intent-receipt').textContent, /已收到绑定的游戏确认/);
sandbox.renderBidIntentStatus({ ...current, bidActionReceipt: { ...boundReceipt, kind: 'ReturnLobby' } });
assert.match(elements.get('match-bid-intent-receipt').textContent, /范围或状态未核实/);

sandbox.renderBidIntentStatus({ ...current, observationProfile: 'manual' });
assert.equal(elements.get('match-bid-intent-status').hidden, true);

const rawPartialSession = 'abcdef0123456789abcdef0123456789';
const rawPartialArchive = {
  sessionId: rawPartialSession, pageCount: 2, terminationReason: 'NO_QUALIFIED_PAGES',
};
const projectedDraft = sandbox.projectLiveTrialDraft({
  id: 'trial-match-1', nativeRawPartialArchives: [rawPartialArchive],
});
assert.deepEqual(projectedDraft.nativeRawPartialArchives, [rawPartialArchive]);
sandbox.renderNativeRawPartialArchives(projectedDraft);
assert.equal(elements.get('history-native-raw-partial').hidden, false);
assert.equal(elements.get('history-native-raw-partial-pages').children.length, 3);
elements.get('history-native-raw-partial-pages').children[1].click();
assert.deepEqual(posted[0], {
  action: 'request_native_warehouse_archive_page', sessionId: rawPartialSession,
  pageIndex: 0, requestId: 'main-1',
});
sandbox.renderNativeRawPartialPage({
  ok: true, status: 'RAW_PARTIAL_ARCHIVED', coverageStatus: 'COVERAGE_UNPROVEN',
  sessionId: rawPartialSession, pageIndex: 0, pageCount: 2, sourceSequence: 17,
  capturedAt: '2026-10-11T10:00:00Z', sourceSha256: 'b'.repeat(64),
  previewDataUrl: 'data:image/jpeg;base64,AA==',
}, 'main-1');
assert.equal(elements.get('history-native-raw-partial-image').hidden, false);
assert.equal(elements.get('history-native-raw-partial-image').src, 'data:image/jpeg;base64,AA==');
assert.match(elements.get('history-native-raw-partial-meta').textContent, /SHA-256 b/);
assert.match(elements.get('history-native-raw-partial-status').textContent, /覆盖仍未证明/);
sandbox.renderNativeRawPartialPage({
  ok: true, sessionId: 'another-session', pageIndex: 0, pageCount: 2,
  previewDataUrl: 'data:image/jpeg;base64,BB==',
}, 'main-1');
assert.equal(elements.get('history-native-raw-partial-image').src, 'data:image/jpeg;base64,AA==');
sandbox.renderNativeRawPartialArchives({ recordSource: 'live-trial', nativeRawPartialArchives: [] });
assert.equal(elements.get('history-native-raw-partial').hidden, true);
console.log('Bid intent UI remains read-only; raw PARTIAL pages reopen only from a verified session: passed');
