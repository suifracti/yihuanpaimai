const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../core/main_window.js'), 'utf8');
const start = source.indexOf('function renderObservationWindowMode(');
const end = source.indexOf('\nfunction requestNativeAutoWarehouse(', start);
const elements = {};
const sandbox = { dashboard: {}, document: { getElementById(id) {
  return elements[id] ||= {};
} } };
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);
const render = sandbox.renderObservationWindowMode;
render({ observationProfile: 'native-readonly-v1', nativeObservationRunning: true,
  observationWindowMode: 'background-readonly', effectiveObservationWindowMode: 'background-readonly',
  captureFreshnessPolicy: 'wgc-origin-strict-v1', effectiveCaptureFreshnessPolicy: 'wgc-delivery-v1',
  originStatus: 'FUTURE_AT_READ', nativeAutoWarehouseConfigured: true,
  nativeAutoWarehouseTrigger: { reasonText: '未建立同局对局锚点；当前建议未合格' },
  nativeAutoWarehouseCapability: true, visionHealth: { status: 'READY' } });
assert.equal(elements['capture-delivery-enabled'].checked, true);
assert.equal(elements['capture-delivery-enabled'].disabled, true);
assert.match(elements['capture-delivery-status'].textContent, /FUTURE_AT_READ.*来源绝对年龄／请求后渲染未证明/);
assert.match(elements['native-auto-warehouse-status'].textContent, /仅指定窗口滚动消息/);
assert.match(elements['native-auto-warehouse-status'].textContent, /未建立同局对局锚点；当前建议未合格/);
assert.match(elements['native-auto-warehouse-enabled'].title, /关闭后续自动触发/);
render({ observationProfile: 'native-readonly-v1', nativeObservationRunning: false,
  captureFreshnessPolicy: 'wgc-origin-strict-v1', visionHealth: { observationStopped: true } });
assert.equal(elements['capture-delivery-enabled'].checked, false);
assert.equal(elements['capture-delivery-enabled'].disabled, false);
assert.match(elements['capture-delivery-status'].textContent, /严格来源时序.*不自动降级/);
console.log(JSON.stringify({ passed: true, gameCapture: false, gameInput: false,
  checks: ['immutable-running-policy', 'delivery-evidence-meaning', 'window-scroll-option', 'stopped-mode-selection'] }));
