// Offline check for the 竞拍席 auto-run switch.
//
// The page must read app_status.autoAuction as it is, start/stop through the
// one allowed action pair, and never show a switched-on run that has no first
// frame yet as "closed". It also must not reuse stop_warehouse_capture as the
// switch's stop.
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict'), path = require('path');

class Element {
  constructor(id) { this.id = id; this.dataset = {}; this.handlers = {}; this._text = ''; this.disabled = false; this.title = ''; this.hidden = false; }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  fire(name, event = {}) { for (const fn of this.handlers[name] || []) fn(event); }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value ?? ''); }
  get classList() { const self = this; return { toggle(cls, on) { const set = new Set((self._classes ||= [])); on ? set.add(cls) : set.delete(cls); self._classes = [...set]; } }; }
}

const ids = [
  'auto-run-band', 'auto-run-state', 'auto-run-note', 'auto-run-reason', 'auto-run-mode',
  'auto-run-phase', 'auto-run-matches', 'auto-run-coverage', 'auto-run-funds',
  'auto-run-limit', 'auto-run-targets', 'auto-run-toggle', 'auto-run-hint',
];
const elements = new Map(ids.map(id => [id, new Element(id)]));
const posted = [];

const sandbox = {
  console, setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {},
  performance, URLSearchParams,
  document: {
    addEventListener() {},
    getElementById: id => elements.get(id) || null,
    querySelectorAll: () => [],
    querySelector: () => null,
  },
  window: {
    addEventListener() {}, setTimeout, clearTimeout, setInterval: () => 0, clearInterval: () => {},
    location: { search: '' },
    matchMedia: undefined,
    chrome: { webview: { postMessage: raw => posted.push(JSON.parse(raw)) } },
  },
};
sandbox.window.window = sandbox.window;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'core', 'main_window.js'), 'utf8'), sandbox);

const el = id => elements.get(id);
const run = (state, command) => vm.runInContext('renderAutoAuction', sandbox)(state, command);

// 1. A switched-on run with no frame yet is starting, not closed.
run({ enabled: true, running: true, phase: null, reason: null, mode: 'bid', matchesDone: 0, maxMatches: null, minimumFunds: 100000, instrumentTargets: { goldAverage: 1, purpleCount: 1 }, coverage: null, savedSources: 0 });
assert.equal(el('auto-run-band').dataset.state, 'starting');
assert.equal(el('auto-run-state').textContent, '正在启动');
assert.equal(el('auto-run-toggle').textContent, '停止自动拍卖');
assert.equal(el('auto-run-toggle').dataset.mode, 'stop');
assert.ok(el('auto-run-note').textContent.includes('等第一帧'), 'starting note must say what it is waiting for');
assert.equal(el('auto-run-phase').textContent, '等待第一帧');
assert.equal(el('auto-run-toggle').disabled, false);

// 2. Running with real backend fields, no local counters.
run({ enabled: true, running: true, phase: 'collecting', reason: 'WAITING_WAREHOUSE_SAVE', mode: 'observe', matchesDone: 3, maxMatches: 10, minimumFunds: 120000, instrumentTargets: { goldAverage: 2, purpleCount: 1 }, coverage: 'PARTIAL', savedSources: 21 });
assert.equal(el('auto-run-band').dataset.state, 'running');
assert.equal(el('auto-run-state').textContent, '自动拍卖运行中');
assert.equal(el('auto-run-mode').textContent, '观察 · 不出价');
assert.equal(el('auto-run-phase').textContent, '结算收仓');
assert.equal(el('auto-run-matches').textContent, '3 / 10');
assert.equal(el('auto-run-coverage').textContent, '只收了一部分 · 21 张原图');
assert.equal(el('auto-run-funds').textContent, '120,000');
assert.equal(el('auto-run-limit').textContent, '10 局');
assert.equal(el('auto-run-targets').textContent, '金均 2 · 紫数 1');
assert.ok(el('auto-run-reason').textContent.includes('收页'), 'waiting reason must be readable');

// 3. Any stop shows the first plain-language reason and offers start again.
run({ enabled: false, running: false, phase: 'stopped', reason: 'USER_STOP', mode: 'bid', matchesDone: 3, maxMatches: 10 });
assert.equal(el('auto-run-band').dataset.state, 'stopped');
assert.equal(el('auto-run-state').textContent, '已停止');
assert.ok(el('auto-run-reason').textContent.includes('你按下了停止'));
assert.equal(el('auto-run-toggle').textContent, '重新开始自动拍卖');
assert.equal(el('auto-run-toggle').dataset.mode, 'start');

run({ enabled: true, running: false, phase: 'stopped', reason: 'AUTO_AUCTION_MATCH_LIMIT' });
assert.ok(el('auto-run-reason').textContent.includes('局数上限'), 'match limit must explain itself');

// 4. A never-started switch is off; an unwired bridge is not "off".
run({ enabled: false, running: false, phase: null, reason: null, mode: 'bid', matchesDone: 0, maxMatches: null, minimumFunds: 100000 });
assert.equal(el('auto-run-band').dataset.state, 'off');
assert.equal(el('auto-run-state').textContent, '未开启');
assert.equal(el('auto-run-matches').textContent, '0（不限）');
assert.equal(el('auto-run-coverage').textContent, '本局还没收仓');

run(null);
assert.equal(el('auto-run-band').dataset.state, 'unavailable');
assert.equal(el('auto-run-state').textContent, '未接入');
assert.equal(el('auto-run-toggle').disabled, true);
assert.notEqual(el('auto-run-state').textContent, '未开启', 'a missing payload is not the off state');

// 5. Both buttons use the switch's own actions, never the capture stop.
vm.runInContext('bindAutoRunSwitch()', sandbox);
run({ enabled: false, running: false, phase: null, reason: null, mode: 'bid', matchesDone: 0, maxMatches: null, minimumFunds: 100000 });
el('auto-run-toggle').fire('click');
assert.equal(posted.at(-1).action, 'auto_auction_start');
// A second click while the first command is unanswered must not queue another.
el('auto-run-toggle').fire('click');
assert.equal(posted.length, 1, 'an unanswered command must not be sent twice');
// The reply to start clears the pending flag and turns the button into stop.
run({ enabled: true, running: true, phase: 'idle', mode: 'bid', matchesDone: 0, maxMatches: null }, { ok: true, reason: null });
el('auto-run-toggle').fire('click');
assert.equal(posted.at(-1).action, 'auto_auction_stop');
assert.ok(!posted.some(message => message.action === 'stop_warehouse_capture'));

// 6. A failed start reports the reason instead of pretending it is on.
run({ enabled: false, running: false, phase: null, reason: null }, { ok: false, reason: 'OBSERVATION_UNAVAILABLE' });
assert.ok(el('auto-run-hint').textContent.includes('观察没有启动'));

console.log('auto-run switch reads backend state, starts/stops once, and never shows a starting run as closed: passed');
