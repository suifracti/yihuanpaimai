const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../core/main_window.js'), 'utf8');
const start = source.indexOf('function nativeStoppedObservationMessage(');
const end = source.indexOf('\nfunction renderMatch(', start);
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);
const render = sandbox.nativeStoppedObservationMessage;
const last = { matchId: 'match-180', frameSequence: 180,
  capturedAtUtc: '2026-10-04T12:56:21.7745133+00:00' };
for (const stage of ['native-paused', 'native-error', 'native-stopped']) {
  const input = { matchId: 'match-180', visionHealth: { stage, reason: 'source-clock-stale-at-readback',
    lastSuccessfulObservation: last, observationStopped: true } };
  const before = JSON.stringify(input);
  const text = render(input);
  assert.match(text, /观察已停止.*source-clock-stale-at-readback/);
  assert.match(text, /20:56:21/);
  assert.match(text, /match-180.*未自动重启/);
  assert.equal(JSON.stringify(input), before, 'presentation must preserve evidence');
}
assert.equal(render({visionHealth: {stage: 'native-frame', observationStopped: false}}), null);
assert.equal(render({visionHealth: {stage: 'native-starting'}}), null);
assert.match(render({matchId: 'no-frame', visionHealth: {stage: 'native-error'}}), /尚无成功观察.*no-frame/);
assert.match(render({visionHealth: {stage: 'native-error', reason: 'source-clock-future-at-selection',
  processExitConfirmed: false}}), /source-clock-future-at-selection.*Host退出未确认/);
console.log('Native terminal reason, last success, match and evidence retention: passed');
