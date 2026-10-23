// The ticket stays click-through except for one small stop button. This runs
// the shipped overlay script against a fake DOM: the button only appears while
// the backend says the run is on, it reports its own rectangle for the native
// hit test, and clicking it sends the same stop the main window sends.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');

const html = fs.readFileSync('core/overlay_alpha.html', 'utf8');

function slice(startMarker, endMarker) {
  const start = html.indexOf(startMarker);
  assert.ok(start > 0, `missing marker: ${startMarker}`);
  const end = html.indexOf(endMarker, start + startMarker.length);
  assert.ok(end > start, `missing end marker: ${endMarker}`);
  return html.slice(start, end);
}

const button = {
  hidden: true,
  disabled: false,
  offsetParent: {},
  box: { left: 356, top: 10, width: 54, height: 32 },
  getBoundingClientRect() {
    const { left, top, width, height } = this.box;
    return { left, top, width, height, right: left + width, bottom: top + height };
  },
};

const elements = { autoRunStopBtn: button };
const sent = [];
const timers = [];
const frames = [];

const sandbox = {
  document: { getElementById: (id) => elements[id] || null },
  sendHost: (message) => sent.push(message),
  window: {
    devicePixelRatio: 1.25,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
  },
  requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; },
  Math,
  Number,
  Boolean,
};
vm.createContext(sandbox);

vm.runInContext(
  slice('    const autoRunView = { running: false', '    function bind() {'),
  sandbox,
);
vm.runInContext(
  slice('      document.getElementById("autoRunStopBtn").onclick = () => {',
        '      document.getElementById("terminalClose").onclick'),
  sandbox,
);

const flushFrames = () => {
  while (frames.length) frames.shift()();
};

// The markup ships hidden: a stopped run never flashes a stop button.
assert.match(html, /id="autoRunStopBtn"[^>]*hidden/,
  'stop button must start hidden so a stopped run shows nothing to click');

// Running: the button appears and hands its rectangle to the host hit test.
flushFrames();
vm.runInContext('applyAutoAuctionState({ enabled: true, running: true, phase: null })', sandbox);
assert.equal(button.hidden, false, 'a starting run must already offer stop');
flushFrames();
const rectMessage = sent[sent.length - 1];
assert.equal(rectMessage.action, 'auto_run_stop_rect');
assert.deepEqual(JSON.parse(JSON.stringify(rectMessage.rect)),
  { x: 356, y: 10, width: 54, height: 32 });
assert.equal(rectMessage.scale, 1.25);

// Same rectangle again: no chatter to the host.
const before = sent.length;
vm.runInContext('applyAutoAuctionState({ enabled: true, running: true, phase: "collecting" })', sandbox);
flushFrames();
assert.equal(sent.length, before, 'unchanged rectangle must not be resent');

// Stopped for any reason: the button goes away and the host is told to clear
// the live rectangle, so the whole ticket is click-through again.
vm.runInContext('applyAutoAuctionState({ enabled: false, running: false, phase: "stopped", reason: "AUTO_AUCTION_MATCH_LIMIT" })', sandbox);
assert.equal(button.hidden, true, 'a finished run must not leave a stop target');
flushFrames();
assert.equal(sent[sent.length - 1].rect, null);

// No product loop wired: still nothing to stop.
vm.runInContext('applyAutoAuctionState(null)', sandbox);
assert.equal(button.hidden, true);

// Clicking sends the one stop, not the capture stop, and guards double clicks.
vm.runInContext('applyAutoAuctionState({ enabled: true, running: true, phase: "bid_dispatched" })', sandbox);
flushFrames();
sent.length = 0;
button.onclick();
assert.deepEqual(JSON.parse(JSON.stringify(sent)),
  [{ action: 'auto_auction_stop', type: 'auto_auction_stop' }]);
assert.equal(button.disabled, true);
assert.equal(timers[timers.length - 1].ms, 1500);
timers[timers.length - 1].fn();
assert.equal(button.disabled, false);

assert.ok(!sent.some((message) => String(message.action).includes('warehouse')),
  'the ticket must never stop just the warehouse capture');

console.log('overlay stop button appears only while running, reports its rect, and sends the shared stop: passed');
