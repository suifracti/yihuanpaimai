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
    this.children = [];
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
    if (selector === "button") return this.children.filter(child => child.tagName === "BUTTON");
    if (selector === "[data-wh-catalog-id]") return this.buttons.filter(button => button.dataset.whCatalogId !== undefined);
    if (selector === "[data-guidebook-original]" || selector === "[data-guidebook-confirmed-item]" || selector === "[data-guidebook-item-index]") {
      return this.buttons.filter(button => selector.includes("original")
        ? button.dataset.guidebookOriginal !== undefined
        : selector.includes("confirmed") ? button.dataset.guidebookConfirmedItem !== undefined
          : button.dataset.guidebookItemIndex !== undefined);
    }
    const dataAttribute = selector.match(/^\[data-([\w-]+)\]$/);
    if (dataAttribute) {
      const key = dataAttribute[1].replace(/-([a-z])/g, (_m, ch) => ch.toUpperCase());
      return this.buttons.filter(button => Object.hasOwn(button.dataset, key));
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
  click() {
    if (this.disabled) return;
    this.listeners.click?.({ target: this });
    this.onclick?.({ target: this });
  }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
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
  createElement(tagName) { const element = new FakeElement(); element.tagName = String(tagName).toUpperCase(); return element; },
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
    intelCardEvidence: { observations: [{ field: "q", value: 17, status: "OBSERVED", round: 3, rawText: "本局内紫金红合计17件", frameSequence: 10, observationSessionId: "session-a" }] },
    warehouse: { slots: [{ rarity: "gold", status: "CANDIDATE", candidates: [{ name: "待确认藏品", catalogId: "candidate-1", confidence: 0.99 }] }] },
    auctionEvidence: { nativeObservation: { observationSessionId: "session-a", sourceFrames: [
      { evidenceId: "evidence-1", frameSequence: 9, observationSessionId: "session-a", capturedAt: "t9", round: 2 },
      { evidenceId: "evidence-2", frameSequence: 10, observationSessionId: "session-a", capturedAt: "t10", round: 3 },
      { evidenceId: "evidence-3", frameSequence: 11, observationSessionId: "session-a", capturedAt: "t11", round: 4 }
    ] } } },
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
assert.equal(sent[0].action, "request_guidebook_sources");
assert.match(get("guidebook-catalog-grid").innerHTML, /独立目录条目/);
assert.match(get("guidebook-item-detail").innerHTML, /基础参考价/);

const sourceRequestId = sent[0].requestId;
sandbox.handleNativeMessage({ data: {
  type: "app_status", action: "request_guidebook_sources", requestId: sourceRequestId,
  guidebookSources: { ok: true, counts: { uniqueSourceEntries: 3 }, items: [
    { sourceId: "vertical-source", name: "纵向来源样本", sourceName: "纵向来源样本", category: "古董", sourceGeometry: "1x2", sourceRarity: "blue", sourceOnly: true, sourcePrice: null, sourcePriceStatus: "UNKNOWN_NOT_PROMOTED", sourceImages: [{ uri: "file:///source-v.png", path: "1.4更新/古董/1x2/source.png" }] },
    { sourceId: "horizontal-source", name: "横向来源样本", sourceName: "横向来源样本", category: "科技", sourceGeometry: "2x1", sourceRarity: "blue", sourceOnly: true, sourcePrice: null, sourcePriceStatus: "UNKNOWN_NOT_PROMOTED", sourceImages: [{ uri: "file:///source-h.png", path: "1.4更新/科技/2x1/source.png" }] },
    { sourceId: "linked-source", visualCatalogId: "candidate-1", name: "独立目录条目", category: "日用", sourceGeometry: "2x2", sourceRarity: "gold", sourceOnly: false, solverMatch: { key: "gold:0:独立目录条目" }, sourcePrice: null, sourcePriceStatus: "UNKNOWN_NOT_PROMOTED", sourceImages: [{ uri: "file:///candidate-source.png", path: "1.4更新/日用/2x2/candidate-source.png" }] }
  ], roles: [{ name: "黑羽", skillName: "未卜先知", skillDescription: "每三回合随机揭示一项命运线索。", revelations: ["线索A"], newInThisBatch: true, sourceImage: { uri: "file:///black-feather.png", path: "1.4更新/角色/black.png" } }] }
} });
assert.match(get("guidebook-item-detail").innerHTML, /基础参考价/);
assert.match(get("guidebook-item-detail").innerHTML, /查看来源原图/);
sandbox.renderGuidebookCharacters();
assert.match(get("guidebook-character-list").innerHTML, /黑羽/);
assert.match(get("guidebook-character-list").innerHTML, /file:\/\/\/black-feather.png/);
vm.runInContext(`dashboard.guidebookCategory = "古董"; dashboard.guidebookGridSize = "1x2";`, sandbox);
sandbox.renderGuidebookCatalog();
assert.match(get("guidebook-catalog-grid").innerHTML, /纵向来源样本/);
assert.doesNotMatch(get("guidebook-catalog-grid").innerHTML, /横向来源样本/);
vm.runInContext(`dashboard.guidebookCategory = "科技"; dashboard.guidebookGridSize = "2x1";`, sandbox);
sandbox.renderGuidebookCatalog();
assert.match(get("guidebook-catalog-grid").innerHTML, /横向来源样本/);
assert.doesNotMatch(get("guidebook-catalog-grid").innerHTML, /纵向来源样本/);
vm.runInContext(`dashboard.guidebookCategory = "all"; dashboard.guidebookGridSize = "all";`, sandbox);
sandbox.renderGuidebookCatalog();
assert.match(get("guidebook-catalog-grid").innerHTML, /来源字段待确认 · 仅展示/);
assert.doesNotMatch(get("guidebook-catalog-grid").innerHTML, /原图 0/);

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

sandbox.showView("match");
const liveMatchBeforeCandidateBrowse = vm.runInContext("JSON.stringify(dashboard.matchState)", sandbox);
sandbox.renderWarehouseSlots({ slots: [
  { row: 3, col: 0, w: 2, h: 2, rarity: "gold", identityStatus: "CANDIDATE", bestCandidateId: "candidate-1", bestCandidateName: "独立目录条目", identityReferenceKind: "DIRECT", candidates: [
    { catalogId: "other-candidate", name: "其他相似条目" },
    { catalogId: "candidate-1", name: "独立目录条目" }
  ] },
  { row: 3, col: 2, w: 1, h: 1, rarity: "gold", identityStatus: "EXACT", identifiedName: "已确证条目", candidates: [{ catalogId: "confirmed-id", name: "已确证条目" }] }
] });
const liveWarehouse = get("match-wh-slots-list");
assert.match(liveWarehouse.innerHTML, /第 4 行 · 第 1 列/);
assert.match(liveWarehouse.innerHTML, /候选 · 未确证/);
assert.match(liveWarehouse.innerHTML, /已确证/);
assert.match(liveWarehouse.innerHTML, /独立目录条目/);
const liveCandidateLinks = liveWarehouse.querySelectorAll("[data-wh-catalog-id]");
assert.equal(liveCandidateLinks[0].dataset.whCatalogId, "candidate-1");
liveCandidateLinks[0].click();
assert.equal(get("page-guidebook").hidden, false);
assert.match(get("guidebook-item-detail").innerHTML, /独立目录条目/);
assert.match(get("guidebook-item-detail").innerHTML, /candidate-source\.png/);
assert.equal(vm.runInContext("JSON.stringify(dashboard.matchState)", sandbox), liveMatchBeforeCandidateBrowse);

const reviewMatch = {
  matchId: "live-review", observationSessionId: "session-review", observationRound: 5,
  observationTarget: { pid: 42, processStartTime: "start-review" },
  nativeInstanceDecisionGeneration: 12, warehouseDecisionEligible: true,
  warehouse: { slots: [] }
};
const reviewSlots = [0, 1].map(col => ({
  row: 2, col, w: 1, h: 2, rarity: "purple", identityStatus: "CANDIDATE",
  candidates: [
    { catalogId: "candidate-one", name: "同名物品" },
    { catalogId: "candidate-two", name: "相似候选" }
  ],
  activityEvidence: {
    evidenceId: `activity-${col}`, sourceKind: "offline-replay", sessionId: "session-review",
    generationId: 31, matchId: "live-review", frameSequence: 81 + col,
    instanceAnchor: { row: 2, col, w: 1, h: 2, rarity: "purple" }
  },
  instanceDecisionToken: `decision-token-${col}`, instanceDecisionGeneration: 4
}));
sandbox.renderWarehouseSlots({ slots: reviewSlots }, reviewMatch);
const reviewButtons = get("match-wh-slots-list").querySelectorAll("[data-wh-open-review]");
assert.equal(reviewButtons.length, 2);
reviewButtons[1].click();
const evidenceRequest = sent.at(-1);
assert.equal(evidenceRequest.action, "request_warehouse_slot_evidence");
assert.equal(evidenceRequest.matchId, "live-review");
assert.equal(evidenceRequest.instanceAnchor.col, 1, "same-name items must open the selected physical slot");
assert.equal(evidenceRequest.activityEvidenceId, "activity-1");
sandbox.handleNativeMessage({ data: {
  type: "app_status", action: "request_warehouse_slot_evidence", requestId: evidenceRequest.requestId,
  warehouseSlotEvidence: {
    ok: true, decisionAllowed: true, identityStatus: "CANDIDATE",
    source: { sourceKind: "offline-replay", matchId: "live-review", sessionId: "session-review", frameSequence: 82, box: [40, 50, 20, 35] },
    dataUrl: "data:image/png;base64,ACTIVITYCROP",
    candidates: [
      { catalogId: "candidate-one", name: "同名物品", sourceImages: [{ available: true, uri: "file:///catalog-one.png" }] },
      { catalogId: "candidate-two", name: "相似候选", sourceImages: [{ available: true, uri: "file:///catalog-two.png" }] }
    ]
  }
} });
assert.equal(get("match-wh-instance-review-image").src, "data:image/png;base64,ACTIVITYCROP");
assert.match(get("match-wh-instance-review-meta").textContent, /离线回放活动帧裁图/);
assert.match(get("match-wh-instance-review-candidates").innerHTML, /catalog-one\.png/);
const candidateChoices = get("match-wh-instance-review-candidates").querySelectorAll("[data-wh-review-select]");
candidateChoices[1].click();
assert.equal(get("match-wh-instance-confirm").disabled, false);
get("match-wh-instance-confirm").click();
const decisionRequest = sent.at(-1);
assert.equal(decisionRequest.action, "warehouse_instance_decision");
assert.equal(decisionRequest.instanceAnchor.col, 1);
assert.equal(decisionRequest.activityEvidenceId, "activity-1");
assert.equal(decisionRequest.catalogId, "candidate-two");
assert.equal(get("match-wh-instance-review-status").textContent, "等待观察 worker 回执；修改尚未显示为生效。");
assert.equal(get("match-wh-instance-review-close").disabled, true);
reviewButtons[0].click();
assert.equal(vm.runInContext("dashboard.warehouseInstanceReview.slot.col", sandbox), 1,
  "a pending decision stays attached to its physical instance until its receipt arrives");
sandbox.handleNativeMessage({ data: {
  type: "app_status", action: "warehouse_instance_decision", requestId: decisionRequest.requestId,
  warehouseInstanceDecision: { status: "PENDING", commandId: "native-control-77" }
} });
const staleReceiptMatch = {
  ...reviewMatch, warehouseDecisionEligible: true,
  warehouseInstanceDecisionResult: {
    commandId: "native-control-old", status: "ACK", matchId: "live-review",
    activityEvidenceId: "activity-1", instanceDecisionToken: "decision-token-1",
    decision: { action: "CONFIRM_CANDIDATE", catalogId: "candidate-one" }
  }
};
sandbox.syncWarehouseInstanceReviewFromMatch(staleReceiptMatch);
assert.equal(vm.runInContext("dashboard.warehouseInstanceReview.busy", sandbox), true);
assert.match(get("match-wh-instance-review-status").textContent, /尚未显示为生效/);
const acceptedReviewSlots = [{ ...reviewSlots[1], manualDecision: { action: "CONFIRM_CANDIDATE", catalogId: "candidate-two", name: "相似候选" } }];
sandbox.syncWarehouseInstanceReviewFromMatch({
  ...reviewMatch,
  warehouse: { slots: acceptedReviewSlots },
  warehouseInstanceDecisionResult: {
    commandId: "native-control-77", status: "ACK", matchId: "live-review",
    activityEvidenceId: "activity-1", instanceDecisionToken: "decision-token-1",
    decision: { action: "CONFIRM_CANDIDATE", catalogId: "candidate-two" }
  }
});
assert.equal(vm.runInContext("dashboard.warehouseInstanceReview.busy", sandbox), false);
assert.match(get("match-wh-instance-review-status").textContent, /worker 已确认这一个实例/);
sandbox.renderWarehouseSlots({ slots: acceptedReviewSlots }, reviewMatch);
assert.match(get("match-wh-slots-list").innerHTML, /人工确认 · 本实例/);
get("match-wh-instance-reject").click();
const rejectRequest = sent.at(-1);
assert.equal(rejectRequest.decision, "REJECT_CANDIDATE");
sandbox.handleNativeMessage({ data: {
  type: "app_status", action: "warehouse_instance_decision", requestId: rejectRequest.requestId,
  warehouseInstanceDecision: { status: "REJECTED", reason: "STALE_MATCH_OR_SESSION" }
} });
assert.match(get("match-wh-instance-review-status").textContent, /未生效/);
sandbox.syncWarehouseInstanceReviewFromMatch({
  ...reviewMatch, matchId: "next-match", warehouseDecisionEligible: false,
  warehouseInstanceDecisionResult: null
});
assert.equal(get("match-wh-instance-confirm").disabled, true);

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
assert.match(get("match-admission-actions").innerHTML, /手动选择\/核对规则/);
assert.match(get("match-admission-actions").innerHTML, /手动选择\/核对会场与费用/);
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
const originalRequestStart = sent.length;
list.querySelectorAll("[data-guidebook-original]")[0].click();
assert.equal(sent.length, originalRequestStart + 1);
const originalRequest = sent.at(-1);
assert.equal(originalRequest.action, "request_original_screenshots");
assert.equal(originalRequest.source, "live-trial");
assert.equal(originalRequest.recordId, "trial-a");
sandbox.handleNativeMessage({ data: {
  type: "app_status", action: "request_original_screenshots", requestId: originalRequest.requestId,
  originalScreenshots: { ok: true, recordId: "trial-a", source: "live-trial", images: [
    { sequence: 1, evidenceId: "evidence-1", frameSequence: 9, observationSessionId: "session-a", capturedAt: "t9", round: 2, kind: "native-observation", readOnly: true, dataUrl: "data:image/png;base64,AA==" },
    { sequence: 2, evidenceId: "evidence-2", frameSequence: 10, observationSessionId: "session-a", capturedAt: "t10", round: 3, kind: "native-observation", readOnly: true, dataUrl: "data:image/png;base64,AA==" },
    { sequence: 3, evidenceId: "evidence-3", frameSequence: 11, observationSessionId: "session-a", capturedAt: "t11", round: 4, kind: "native-observation", readOnly: true, dataUrl: "data:image/png;base64,AA==" }
  ] }
} });
const viewer = get("guidebook-source-0");
const picker = viewer.children.find(child => child.className === "guidebook-keyframe-label").children[0];
const imagePanel = viewer.children.find(child => child.className === "guidebook-keyframe-viewer");
assert.equal(picker.value, "1");
assert.match(imagePanel.children[0].textContent, /第 10 帧/);
assert.match(imagePanel.children[1].textContent, /事实来源帧：总高阶件数 Q/);
picker.value = "2";
picker.listeners.change();
assert.match(imagePanel.children[0].textContent, /第 11 帧/);
assert.match(imagePanel.children[1].textContent, /后续关键帧/);
assert.doesNotMatch(imagePanel.children[1].textContent, /首次来源原图已保存/);
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

console.log("guidebook categories and dimensions, source-only pricing, role provenance, isolated records and selectable frame provenance: passed");
