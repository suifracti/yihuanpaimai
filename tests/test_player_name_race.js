// -*- coding: utf-8 -*-
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');

class MockElement {
  constructor(id) {
    this.id = id;
    this.value = '';
    this.textContent = '';
    this.hidden = false;
    this.disabled = false;
    this.dataset = {};
    this.style = {};
    this.handlers = {};
    this.children = [];
    this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
  }
  addEventListener(name, fn) {
    (this.handlers[name] ||= []).push(fn);
  }
  fire(name, event = {}) {
    for (const fn of this.handlers[name] || []) fn(event);
  }
  querySelectorAll() { return []; }
  appendChild(c) { this.children.push(c); }
  setAttribute(name, val) { this[name] = String(val); }
  getAttribute(name) { return this[name] ?? null; }
}

function createTestContext() {
  const elements = new Map();
  const getOrCreate = (id) => {
    if (!elements.has(id)) elements.set(id, new MockElement(id));
    return elements.get(id);
  };

  const sentNative = [];
  const docHandlers = {};
  const sandbox = {
    console,
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
    setInterval: () => 1,
    clearInterval: () => {},
    URLSearchParams: class { get() { return null; } },
    document: {
      addEventListener(name, fn) {
        (docHandlers[name] ||= []).push(fn);
      },
      getElementById: (id) => getOrCreate(id),
      querySelector: () => new MockElement('mock'),
      querySelectorAll: () => [],
      createElement: (tag) => new MockElement(tag),
      activeElement: null,
    },
    window: {
      addEventListener() {},
      location: { search: '' },
      chrome: {
        webview: {
          postMessage: (jsonStr) => {
            const parsed = JSON.parse(jsonStr);
            sentNative.push(parsed);
          },
        },
      },
    },
    performance: { now: () => Date.now() },
  };

  sandbox.window.AuctionEngineV06 = {
    computeInventoryCoverage() { return { isFullCoverage: false }; },
  };

  vm.createContext(sandbox);
  const code = fs.readFileSync(require.resolve('../core/main_window.js'), 'utf8');
  vm.runInContext(code, sandbox);

  vm.runInContext(`
    const pInput = document.getElementById("player-display-name");
    if (pInput) {
      pInput.addEventListener("input", () => { dashboard.isPlayerNameEditing = true; });
    }
    const pBtn = document.getElementById("save-player-display-name");
    if (pBtn) {
      pBtn.addEventListener("click", savePlayerDisplayName);
    }
  `, sandbox);

  return { sandbox, elements, sentNative, getOrCreate };
}

console.log('=== Running Nickname State Machine & Race Tests ===');

// --------------------------------------------------------------------------
// Test 1: IDLE -> SAVING -> Intermediate Old Payload -> Authoritative ACK
// --------------------------------------------------------------------------
{
  const { sandbox, elements, sentNative, getOrCreate } = createTestContext();
  const input = getOrCreate('player-display-name');
  const btn = getOrCreate('save-player-display-name');
  const status = getOrCreate('player-display-name-status');

  // Initial state: empty / not set
  vm.runInContext('renderMatch({ configuredPlayerName: "" })', sandbox);
  assert.equal(status.textContent, '未设置，使用画面姓名；清空后保存可恢复');
  assert.equal(status.style.color, '#94a3b8');
  assert.equal(input.value, '');
  assert.equal(btn.disabled, false);

  // 1. User types new nickname "秋星祭测试"
  input.value = '秋星祭测试';
  input.fire('input');
  assert.equal(vm.runInContext('dashboard.isPlayerNameEditing', sandbox), true);

  // 2. User clicks save button
  vm.runInContext('savePlayerDisplayName()', sandbox);
  assert.equal(vm.runInContext('dashboard.isSavingPlayerName', sandbox), true);
  assert.equal(vm.runInContext('dashboard.pendingPlayerName', sandbox), '秋星祭测试');
  assert.equal(btn.disabled, true);
  assert.equal(status.textContent, '正在保存…');
  assert.equal(status.style.color, '#94a3b8');
  assert.equal(sentNative.length, 1);
  assert.equal(sentNative[0].action, 'manual_facts');
  assert.equal(sentNative[0].facts.configuredPlayerName, '秋星祭测试');

  // 3. Race condition: An OLD payload arrives before native has finished writing
  vm.runInContext('renderMatch({ configuredPlayerName: "" })', sandbox);
  // Must NOT roll back typed input!
  assert.equal(input.value, '秋星祭测试', 'Input value must not be rolled back by stale payload');
  // Must stay in "正在保存…"
  assert.equal(status.textContent, '正在保存…', 'Status must stay "正在保存…" on stale payload');
  assert.equal(btn.disabled, true, 'Save button must remain disabled during save');
  assert.equal(vm.runInContext('dashboard.isSavingPlayerName', sandbox), true);

  // 4. Authoritative ACK payload arrives with configuredPlayerName="秋星祭测试"
  vm.runInContext('renderMatch({ configuredPlayerName: "秋星祭测试" })', sandbox);
  assert.equal(vm.runInContext('dashboard.isSavingPlayerName', sandbox), false, 'isSavingPlayerName must be cleared');
  assert.equal(vm.runInContext('dashboard.pendingPlayerName', sandbox), null, 'pendingPlayerName must be cleared');
  assert.equal(vm.runInContext('dashboard.isPlayerNameEditing', sandbox), false, 'isPlayerNameEditing must be reset');
  assert.equal(status.textContent, '已设置：秋星祭测试', 'Status must immediately show configured name');
  assert.equal(status.style.color, '#34d399', 'Status color must be green');
  assert.equal(input.value, '秋星祭测试', 'Input value must remain clean configured name');
  assert.equal(btn.disabled, false, 'Save button must be re-enabled');

  console.log('Test 1 (Save with in-flight race & authoritative ACK): PASS');
}

// --------------------------------------------------------------------------
// Test 2: Clearing save: SAVING -> ACK -> IDLE + 未设置
// --------------------------------------------------------------------------
{
  const { sandbox, elements, sentNative, getOrCreate } = createTestContext();
  const input = getOrCreate('player-display-name');
  const btn = getOrCreate('save-player-display-name');
  const status = getOrCreate('player-display-name-status');

  // Pre-condition: already set to "秋星祭测试"
  vm.runInContext('renderMatch({ configuredPlayerName: "秋星祭测试" })', sandbox);
  assert.equal(status.textContent, '已设置：秋星祭测试');

  // User clears input and clicks save
  input.value = '   ';  // spaces should be trimmed
  vm.runInContext('savePlayerDisplayName()', sandbox);
  assert.equal(vm.runInContext('dashboard.isSavingPlayerName', sandbox), true);
  assert.equal(vm.runInContext('dashboard.pendingPlayerName', sandbox), '');
  assert.equal(status.textContent, '正在保存…');
  assert.equal(btn.disabled, true);

  // Authoritative ACK arrives with empty configuredPlayerName
  vm.runInContext('renderMatch({ configuredPlayerName: "" })', sandbox);
  assert.equal(vm.runInContext('dashboard.isSavingPlayerName', sandbox), false);
  assert.equal(status.textContent, '未设置，使用画面姓名；清空后保存可恢复');
  assert.equal(status.style.color, '#94a3b8');
  assert.equal(input.value, '');
  assert.equal(btn.disabled, false);

  console.log('Test 2 (Clear save & ACK): PASS');
}

// --------------------------------------------------------------------------
// Test 3: Native failure: SAVING -> ERROR -> No false "已设置"
// --------------------------------------------------------------------------
{
  const { sandbox, elements, getOrCreate } = createTestContext();
  const input = getOrCreate('player-display-name');
  const btn = getOrCreate('save-player-display-name');
  const status = getOrCreate('player-display-name-status');

  input.value = '新昵称';
  vm.runInContext('savePlayerDisplayName()', sandbox);
  assert.equal(status.textContent, '正在保存…');

  // Simulate native error reply
  vm.runInContext(`
    handleNativeMessage({
      data: {
        type: 'app_status',
        action: 'manual_facts',
        manualFactsResult: { ok: false, error: '写入失败：文件只读' }
      }
    })
  `, sandbox);

  assert.equal(vm.runInContext('dashboard.isSavingPlayerName', sandbox), false);
  assert.equal(vm.runInContext('dashboard.pendingPlayerName', sandbox), null);
  assert.equal(status.textContent, '保存失败：写入失败：文件只读');
  assert.equal(status.style.color, '#f87171');
  assert(!status.textContent.includes('已设置'), 'Failure must never display "已设置"');
  assert.equal(btn.disabled, false);

  console.log('Test 3 (Native failure rejection): PASS');
}

// --------------------------------------------------------------------------
// Test 4: Restart recovery
// --------------------------------------------------------------------------
{
  const { sandbox, elements, getOrCreate } = createTestContext();
  const input = getOrCreate('player-display-name');
  const status = getOrCreate('player-display-name-status');

  // On cold start, the first payload loaded from persisted storage
  vm.runInContext('renderMatch({ configuredPlayerName: "秋星祭测试" })', sandbox);
  assert.equal(status.textContent, '已设置：秋星祭测试');
  assert.equal(status.style.color, '#34d399');
  assert.equal(input.value, '秋星祭测试');

  console.log('Test 4 (Restart recovery): PASS');
}

console.log('\nAll Nickname State Machine & Race Tests PASSED!');
