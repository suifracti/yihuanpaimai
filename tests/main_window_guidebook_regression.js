const fs = require("fs");
const vm = require("vm");
const assert = require("assert/strict");

class FakeClassList {
  constructor() { this.values = new Set(); }
  toggle(value, force) {
    const enabled = force === undefined ? !this.values.has(value) : Boolean(force);
    if (enabled) this.values.add(value); else this.values.delete(value);
    return enabled;
  }
  add(value) { this.values.add(value); }
  remove(value) { this.values.delete(value); }
  contains(value) { return this.values.has(value); }
}

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.hidden = false;
    this.dataset = {};
    this.style = {};
    this.classList = new FakeClassList();
    this.attributes = {};
    this.listeners = {};
    this.buttons = [];
    this.value = "";
    this._innerHTML = "";
    this.textContent = "";
  }
  set innerHTML(value) {
    this._innerHTML = String(value);
    this.buttons = [];
    const pattern = /<button\b([^>]*)>/g;
    for (const match of this._innerHTML.matchAll(pattern)) {
      const button = new FakeElement();
      for (const attr of match[1].matchAll(/([\w-]+)="([^"]*)"/g)) {
        const rawKey = attr[1].startsWith("data-") ? attr[1].slice(5) : attr[1];
        const key = rawKey.replace(/-([a-z])/g, (_m, ch) => ch.toUpperCase());
        button.dataset[key] = attr[2];
      }
      this.buttons.push(button);
    }
  }
  get innerHTML() { return this._innerHTML; }
  querySelectorAll(selector) {
    if (selector === "[data-guidebook-original]" || selector === "[data-guidebook-confirmed-item]" || selector === "[data-guidebook-item-index]") {
      return this.buttons.filter(button => selector.includes("original")
        ? button.dataset.guidebookOriginal !== undefined
        : selector.includes("confirmed") ? button.dataset.guidebookConfirmedItem !== undefined
          : button.dataset.guidebookItemIndex !== undefined);
    }
    return [];
  }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  scrollIntoView() {}
  focus() {}
  matches() { return false; }
  closest() { return null; }
  click() { this.listeners.click?.({ target: this }); }
  replaceChildren() { this.children = []; }
}

const ids = new Map();
const get = id => {
  if (!ids.has(id)) ids.set(id, new FakeElement(id));
  return ids.get(id);
};
const pages = ["overview", "match", "history", "guidebook", "analysis"].map(name => {
  const el = get(`page-${name}`); el.dataset.viewPage = name; return el;
});
const navs = ["overview", "match", "history", "guidebook", "analysis"].map(name => {
  const el = get(`nav-${name}`); el.dataset.viewTarget = name; return el;
});
const tabs = ["catalog", "records"].map(name => {
  const el = get(`tab-${name}`); el.dataset.guidebookTab = name; return el;
});
const rarityButtons = [];
const document = {
  getElementById: get,
  querySelector(selector) {
    let match = selector.match(/^\[data-view-page="([^"]+)"\]$/);
    if (match) return pages.find(page => page.dataset.viewPage === match[1]) || null;
    match = selector.match(/^\[data-view-target="([^"]+)"\]$/);
    if (match) return navs.find(nav => nav.dataset.viewTarget === match[1]) || null;
    return null;
  },
  querySelectorAll(selector) {
    if (selector === "[data-view-page]") return pages;
    if (selector === "[data-view-target]") return navs;
    if (selector === "[data-guidebook-tab]") return tabs;
    if (selector === "[data-guidebook-rarity]") return rarityButtons;
    return [];
  },
  addEventListener() {}
};

const sent = [];
const sandbox = {
  document,
  window: {
    chrome: { webview: { postMessage: message => sent.push(JSON.parse(message)) } },
    AuctionEngineV06: {
      baseCatalogFor: () => ({ gold: [["独立目录条目", 12345, "2x2"]], purple: [], red: [], blue: [], green: [], white: [] }),
      catalogVersionFor: () => "2026-08-13"
    },
    addEventListener() {}
  },
  Date,
  Intl,
  console,
  setTimeout,
  clearTimeout
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("core/main_window.js", "utf8"), sandbox);

vm.runInContext(`dashboard.lastMainViewState = { history: { liveTrialDrafts: [
  { id: "trial-a", lifecycleStatus: "DRAFT", dataOrigin: "live-trial", playedAt: "2026-09-23T12:00:00+08:00", updatedAt: "t1", factsRevision: 4,
    environment: { venueName: "珊瑚场" },
    intelCardEvidence: { observations: [{ field: "q", value: 17, status: "OBSERVED", round: 3, rawText: "本局内紫金红合计17件" }] },
    warehouse: { slots: [{ rarity: "gold", status: "CANDIDATE", candidates: [{ name: "待确认藏品", catalogId: "candidate-1", confidence: 0.99 }] }] },
    auctionEvidence: { nativeObservation: { sourceFrames: [{ evidenceId: "evidence-1" }] } } },
  { id: "trial-c", lifecycleStatus: "DRAFT", dataOrigin: "live-trial", q: 5, updatedAt: "t0", intelCardEvidence: { observations: [] } },
  { id: "trial-confirmed", lifecycleStatus: "DRAFT", dataOrigin: "live-trial", updatedAt: "t2",
    warehouse: { slots: [{ status: "CONFIRMED", catalogId: "gold-confirmed", identifiedName: "独立目录条目", rarity: "gold" }] } },
  { id: "formal-b", lifecycleStatus: "FINALIZED", dataOrigin: "history" }
] } }; dashboard.matchState = { matchId: "live-now", factsRevision: 9, q: 6, venueId: "venue-other" };`, sandbox);

sandbox.showView("guidebook");
assert.equal(vm.runInContext("dashboard.currentView", sandbox), "guidebook");
assert.equal(get("page-guidebook").hidden, false);
assert.equal(get("page-overview").hidden, true);
assert.equal(get("nav-guidebook").classList.contains("is-active"), true);
assert.match(get("guidebook-catalog-grid").innerHTML, /独立目录条目/);
assert.match(get("guidebook-item-detail").innerHTML, /基础参考价/);

sandbox.setGuidebookTab("records");
assert.equal(get("guidebook-catalog-panel").hidden, true);
assert.equal(get("guidebook-records-panel").hidden, false);
const list = get("guidebook-recognition-list");
assert.match(list.innerHTML, /trial-a/);
assert.match(list.innerHTML, /本局内紫金红合计17件/);
assert.match(list.innerHTML, /草稿事实/);
assert.match(list.innerHTML, /<p>5<\/p>/);
assert.doesNotMatch(list.innerHTML, /formal-b/);
assert.match(list.innerHTML, /live-trial DRAFT/);
assert.match(list.innerHTML, /候选身份（待确认）：待确认藏品/);
assert.doesNotMatch(list.innerHTML, /已确认：待确认藏品/);
assert.match(list.innerHTML, /已确认：独立目录条目/);
list.querySelectorAll("[data-guidebook-confirmed-item]")[0].click();
assert.equal(get("guidebook-catalog-panel").hidden, false);
assert.match(get("guidebook-item-detail").innerHTML, /独立目录条目/);
sandbox.setGuidebookTab("records");

sandbox.renderSolverAdmissionStatus({
  observationProfile: "native-readonly-v1",
  nativeInvalidated: false,
  solverStatus: "incomplete",
  solverMissingReason: "缺失入场费",
  facts: { purpleCount: 9 },
  solverAdmission: {
    eligible: false,
    requirements: [
      { key: "q", label: "总高阶件数 Q", status: "available", value: 17 },
      { key: "goldAvg", label: "金色均价", status: "available", value: 55444 },
      { key: "entryCost", label: "入场费", status: "missing", value: null },
      { key: "fieldCondition", label: "场地规则", status: "missing", value: null }
    ],
    blockingReasons: ["缺失入场费", "缺失场地规则"],
    actionKeys: ["venueId", "fieldCondition"]
  }
});
assert.match(get("match-admission-title").textContent, /尚不满足建议条件/);
assert.match(get("match-admission-blockers").innerHTML, /缺失入场费/);
assert.match(get("match-admission-blockers").innerHTML, /缺失场地规则/);
assert.match(get("match-admission-auxiliary").textContent, /紫色数量 9/);
assert.equal(get("match-admission-actions").hidden, false);
sandbox.renderSolverAdmissionStatus({
  observationProfile: "native-readonly-v1", nativeInvalidated: true,
  solverStatus: "paused", solverMissingReason: "实时观察未就绪；恢复后等待新的有效局内帧",
  solverAdmission: { eligible: true, requirements: [], blockingReasons: [], actionKeys: ["fieldCondition"] }
});
assert.match(get("match-admission-title").textContent, /实时竞拍建议已暂停/);
assert.equal(get("match-admission-actions").hidden, true);
sandbox.renderSolverAdmissionStatus({
  observationProfile: "native-readonly-v1", nativeInvalidated: false,
  solverStatus: "valid", prediction: { recommendedMax: 123456 },
  solverAdmission: { eligible: false, requirements: [], blockingReasons: ["缺失入场费"], actionKeys: ["venueId"] }
});
assert.match(get("match-admission-title").textContent, /尚不满足建议条件/);
assert.match(get("match-admission-state").textContent, /缺少必要条件/);
sandbox.renderSolverAdmissionStatus({
  observationProfile: "native-readonly-v1", nativeInvalidated: false,
  solverStatus: "stale", solverMissingReason: "事实版本已变化",
  solverAdmission: { eligible: true, requirements: [], blockingReasons: [], actionKeys: [] }
});
assert.match(get("match-admission-title").textContent, /结果已过期/);
assert.match(get("match-admission-summary").textContent, /事实版本已变化/);
const commandStatus = get("manual-command-status");
sandbox.renderManualCommandReceipt({ status: "ACK" });
assert.equal(commandStatus.hidden, false);
assert.match(commandStatus.textContent, /观察 worker 已确认/);
sandbox.renderManualCommandReceipt({ status: "REJECTED", reason: "observation-frame-timeout" });
assert.match(commandStatus.textContent, /画面长时间未更新，修改未生效/);

const matchBeforeRead = vm.runInContext("JSON.stringify(dashboard.matchState)", sandbox);
list.querySelectorAll("[data-guidebook-original]")[0].click();
assert.equal(sent.length, 1);
assert.equal(sent[0].action, "request_original_screenshots");
assert.equal(sent[0].source, "live-trial");
assert.equal(sent[0].recordId, "trial-a");
assert.equal(vm.runInContext("JSON.stringify(dashboard.matchState)", sandbox), matchBeforeRead);

vm.runInContext(`dashboard.matchState = {
  matchId: "live-now", factsRevision: 9, observationFactsRevision: 4,
  observationSessionId: "session-a", observationProfile: "native-readonly-v1",
  venueId: "venue-a", venue: "珊瑚场", boxId: "box-a", box: "已选宝箱", fieldCondition: null
};
dashboard.lastCurrentMatch = {
  observationRound: 5, observationTarget: { pid: 42, processStartTime: "start-a" },
  manualCommandResult: { revision: 2 }
};
dashboard.lastSyncedFacts = {
  venueId: "venue-a", venue: "珊瑚场", boxId: "box-a", box: "已选宝箱",
  fieldCondition: null, q: 16
};`, sandbox);
get("match-input-q").value = "17";
const unrelatedEdit = JSON.parse(vm.runInContext("JSON.stringify(getChangedMatchFacts())", sandbox));
assert.equal(unrelatedEdit.patch.q, 17);
assert.equal(Object.hasOwn(unrelatedEdit.patch, "fieldCondition"), false);
const beforeRuleCommand = sent.length;
sandbox.setMatchCondition("standard", "标准对局");
assert.equal(sent.length, beforeRuleCommand + 1);
assert.equal(sent.at(-1).action, "manual_facts");
assert.equal(sent.at(-1).facts.fieldCondition, "standard");
assert.equal(sent.at(-1).expectedMatchId, "live-now");

console.log("guidebook navigation, bundled catalog, isolated recognition records and read-only original lookup: passed");
