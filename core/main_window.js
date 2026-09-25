
function validateWelfareReceipt(id, errorId) {
  const input = document.getElementById(id);
  const raw = input.value.trim();
  const valid = !raw || (/^[0-9]+$/.test(raw) && Number.isSafeInteger(Number(raw)));
  input.setAttribute('aria-invalid', String(!valid));
  document.getElementById(errorId).textContent = valid ? '' : '请输入非负整数；未知请留空。此金额尚未保存。';
  return valid;
}

function sessionAccountingText(a) {
  if (!a) return '本局净收益待核对';
  const n = v => v == null ? '未知' : Number(v).toLocaleString('zh-CN');
  return `福利实收 ${n(a.welfareReceived)} · 已付费用 ${n(a.paidCosts)} · 按结算价值计净收益 ${n(a.sessionNet)}` + (a.complete ? '（不代表藏品已出售到账）' : `；待确认：${(a.missingFacts || []).join('、')}`);
}

function readSparkleInputs(countId, namesId) {
  const count = document.getElementById(countId).value.trim();
  const names = document.getElementById(namesId).value.trim();
  if (!count && !names) return null;
  return {transformedOneByOneCount: count || null, verifiedGemItems: names};
}
function sparkleNames(value) {
  const items = value?.verifiedGemItems;
  return Array.isArray(items) ? items.map(x => typeof x === 'string' ? x : `${x.name}*${x.count ?? 1}`).join('+') : (items || '');
}
function sparkleBoundsText(b) {
  if (!b) return '等待宝石证据计算';
  if (b.status !== 'valid') return '证据待核对：' + b.reason;
  const n = value => Number(value).toLocaleString('zh-CN');
  return `仅转换宝石：${n(b.lower)} ～ ${b.upper == null ? '上限未知' : n(b.upper)}；已确认 ${b.knownCount} 件。概率未确认，不用于整仓估值或出价建议。`;
}
"use strict";

const dashboard = {
  overlayVisible: null,
  requestSequence: 0,
  bridgeReady: Boolean(window.chrome && window.chrome.webview),
  currentView: "overview",
  mascotPresentation: null,
  mascotState: null,
  lastAutomaticMascotState: null,
  statusPollTimer: null,
  lastMainViewState: null,
  guidebookCatalog: null,
  guidebookSources: null,
  guidebookSourcesRequestId: null,
  guidebookSourcesError: null,
  guidebookSearch: "",
  guidebookRarity: "all",
  guidebookCategory: "all",
  guidebookGridSize: "all",
  guidebookSelectedItem: null,
  guidebookTab: "catalog",
  guidebookRecordsSignature: null,
  pendingFieldCondition: null,
  pendingFieldConditionReceiptRevision: null,
  selectedRecordId: null,
  selectedLegacyKey: null,
  legacyRecords: null,
  legacyLoadRequested: false,
  selectedHistoryRecords: new Map(),
  pendingDeleteSelection: null,
  historyFilter: {
    primaryTab: "all",
    source: "all",
    outcome: "all",
    evidence: "all",
    admission: "all",
    timeRange: "all",
    startDate: "",
    endDate: "",
    search: "",
    debug: false,
  },
  review: null,
  reviewEdits: null,
  pendingReviewRequestId: null,
  matchState: {
    matchId: null,
    factsRevision: 0,
    observationFactsRevision: null,
    observationProfile: null,
    observationSessionId: null,
    venueId: null,
    venue: null,
    boxId: null,
    box: null,
    fieldCondition: "standard",
    q: null,
    goldAvg: null,
    purpleCount: null,
    leaderBid: null,
    knownGold: "",
  },
  lastSyncedFacts: {
    venueId: null,
    venue: null,
    boxId: null,
    box: null,
    fieldCondition: "standard",
  },
  matchOptions: {
    venues: [],
    fieldConditions: [],
  },
  nextMatchPreparation: null,
  nextMatchPreparationDraft: null,
  nextMatchPreparationDirty: false,
  nextMatchPreparationRequestId: null,
  nextMatchPreparationVersion: null,
  matchSyncTimer: null,
  lastSnapshotResult: null,
  warehouseReview: null,
  warehouseInstanceReview: null,
  pendingOverrideConfirm: false,
  pendingReasonKind: null,
  wirSaveConfirmOpen: false,
  warehouseArmingToken: null,
};

const mascotStateCopy = Object.freeze({
  idle: { title: "随时待命", description: "准备陪你查看拍卖数据。", chip: "就绪" },
  loading: { title: "正在处理", description: "正在分析数据状态，等待结果返回。", chip: "分析中" },
  thinking: { title: "认真思考中", description: "正在整理线索与下一步建议。", chip: "思考中" },
  success: { title: "分析完成", description: "任务已顺利完成。", chip: "完成" },
  warning: { title: "请留意", description: "这里有一项提醒需要关注。", chip: "提醒" },
  sleep: { title: "暂时休息", description: "当前没有进行中的任务。", chip: "休息" }
});

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatCurrency(val) {
  if (val === null || val === undefined || !Number.isFinite(val)) return "暂无";
  return Math.round(val).toLocaleString("zh-CN");
}

function formatProfit(val) {
  if (val === null || val === undefined || !Number.isFinite(val)) return "未结算";
  const num = Math.round(val);
  const prefix = num > 0 ? "+" : "";
  return prefix + num.toLocaleString("zh-CN");
}

function formatSettlementProfit(settlement) {
  if (typeof settlement?.acquired !== "boolean") return "归属未知";
  if (!settlement.acquired) return "他人拍下（非本人收益）";
  return formatProfit(settlement.realizedProfit);
}

function formatMode(mode) {
  if (!mode) return "未指定";
  if (mode === "full_shadow") return "完整先验支持";
  if (mode === "structural_only") return "基础结构推断";
  return mode;
}

function formatSupport(support) {
  if (!support) return "暂无支持记录";
  if (support === "FULL_SHADOW") return "完整先验支持";
  if (support === "STRUCTURAL_ONLY") return "基础结构推断";
  if (support === "INSUFFICIENT_HISTORY") return "样本不足";
  return support;
}

function formatResultReason(reason) {
  if (!reason) return "正常结束";
  if (reason === "won") return "成功拍下";
  if (reason === "outbid") return "出价超限退出";
  if (reason === "early_close") return "提前退出";
  if (reason === "folded") return "主动放弃";
  return reason;
}

function formatExclusionReason(reason) {
  if (!reason) return "未准入";
  const map = {
    DRAFT: "草稿待补全",
    CANCELLED: "已放弃对局",
    DIAGNOSTIC: "诊断样本",
    MISSING_RECORD_ID: "缺少记录ID",
    DUPLICATE_RECORD_ID: "重复记录ID",
    INVALID_TIMESTAMP: "时间戳无效",
    UNSUPPORTED_LIFECYCLE: "非正式生命周期",
    LEGACY_WITHOUT_SETTLEMENT_EVIDENCE: "缺少结算证据",
  };
  return map[reason] || reason;
}

function setMascotState(state) {
  const contract = dashboard.mascotPresentation;
  const assetId = contract && contract.states[state];
  const asset = assetId && contract.assets[assetId];
  const copy = mascotStateCopy[state];
  if (!asset || !copy) return false;

  dashboard.mascotState = state;
  const panel = document.getElementById("mascot-panel");
  const stateImg = document.getElementById("mascot-state-image");
  const portraitImg = document.getElementById("mascot-portrait");
  if (panel) panel.dataset.state = state;
  if (stateImg) {
    stateImg.src = asset.uri;
    stateImg.hidden = false;
  }
  if (portraitImg) {
    portraitImg.src = asset.uri;
  }
  const titleEl = document.getElementById("mascot-state-title");
  const descEl = document.getElementById("mascot-state-description");
  const chipEl = document.getElementById("mascot-state-chip");
  if (titleEl) titleEl.textContent = copy.title;
  if (descEl) descEl.textContent = copy.description;
  if (chipEl) chipEl.textContent = copy.chip;
  document.querySelectorAll("[data-mascot-state]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.mascotState === state);
    button.setAttribute("aria-pressed", String(button.dataset.mascotState === state));
  });
  return true;
}

function configureMascotPresentation(contract) {
  if (!contract || contract.mode !== "presentation_only" || !contract.assets || !contract.states) return;
  const portrait = contract.assets[contract.defaultPortraitAssetId];
  if (!portrait || portrait.role !== "portrait") return;

  dashboard.mascotPresentation = contract;
  const stateImg = document.getElementById("mascot-state-image");
  const portraitImg = document.getElementById("mascot-portrait");
  if (stateImg) {
    stateImg.src = portrait.uri;
    stateImg.hidden = false;
  }
  if (portraitImg) {
    portraitImg.src = portrait.uri;
  }
  const panel = document.getElementById("mascot-panel");
  if (panel) panel.dataset.ready = "true";
  document.querySelectorAll("[data-mascot-state]").forEach((button) => {
    button.disabled = !contract.states[button.dataset.mascotState];
  });
  const requested = new URLSearchParams(window.location.search).get("mascot");
  setMascotState(contract.states[requested] ? requested : contract.fallbackState);
}

function applyAutomaticMascotState(payload) {
  const binding = window.MascotRuntimeBinding;
  if (!binding || typeof binding.consumeHostMascotState !== "function") return;
  const hostState = binding.consumeHostMascotState(payload.mascotState);
  if (!hostState || !dashboard.mascotPresentation) return;
  const nextState = hostState.state;
  if (dashboard.mascotPresentation.states[nextState] !== hostState.assetId) return;
  const stateChanged = nextState !== dashboard.lastAutomaticMascotState;
  dashboard.lastAutomaticMascotState = nextState;
  if (stateChanged || payload.applicationState === "shutting_down") {
    setMascotState(nextState);
  }
}

function renderMatchCountMetric(mainViewState) {
  const history = mainViewState && mainViewState.history;
  const metric = mainViewState &&
    mainViewState.overview &&
    mainViewState.overview.metrics &&
    mainViewState.overview.metrics.matchCount;
  const cards = document.querySelectorAll('[data-metric="matches"]');
  if (!cards || !cards.length) return;

  cards.forEach((card) => {
    const valueTarget = card.querySelector("[data-value]");
    const changeTarget = card.querySelector("[data-change]");
    const bars = Array.from(card.querySelectorAll(".mini-chart.bars i"));
    if (!valueTarget) return;

    if (history && !["AVAILABLE", "EMPTY"].includes(history.availability)) {
      valueTarget.textContent = "--";
      const copyByAvailability = {
        CORRUPT: "历史数据暂时无法读取",
        MIGRATION_REQUIRED: "历史数据需要迁移确认",
        MIGRATION_CONFLICT: "检测到旧版历史冲突",
        UNAVAILABLE: "历史数据暂不可用",
      };
      if (changeTarget) {
        changeTarget.textContent = copyByAvailability[history.availability] || "历史数据暂不可用";
      }
      bars.forEach((bar) => bar.style.setProperty("--v", "4%"));
      return;
    }

    if (!metric || metric.availability !== "AVAILABLE" || !Number.isInteger(metric.value)) {
      valueTarget.textContent = "--";
      if (changeTarget) changeTarget.textContent = "真实数据暂不可用";
      bars.forEach((bar) => bar.style.setProperty("--v", "4%"));
      return;
    }

    valueTarget.textContent = String(metric.value);
    if (history && history.availability === "EMPTY") {
      if (changeTarget) changeTarget.textContent = "历史为空";
      bars.forEach((bar) => bar.style.setProperty("--v", "4%"));
      return;
    }
    const comparison = metric.comparison || {};
    const delta = Number.isInteger(comparison.absoluteDelta) ? comparison.absoluteDelta : 0;
    const relative = Number.isFinite(comparison.relativeDelta) ? comparison.relativeDelta : null;
    const signedDelta = delta > 0 ? `+${delta}` : String(delta);
    const relativeText = relative === null
      ? ""
      : ` (${relative > 0 ? "+" : ""}${(relative * 100).toFixed(1)}%)`;
    if (changeTarget) {
      changeTarget.textContent = "较昨日 ";
      const deltaTarget = document.createElement("span");
      if (delta > 0) deltaTarget.className = "delta-positive";
      else if (delta < 0) deltaTarget.className = "delta-orange";
      deltaTarget.textContent = `${signedDelta}${relativeText}`;
      changeTarget.appendChild(deltaTarget);
    }

    const series = Array.isArray(metric.series)
      ? metric.series.filter((point) => point && typeof point.date === "string" && Number.isInteger(point.value) && point.value >= 0)
      : [];
    const maxValue = Math.max(1, ...series.map((point) => point.value));
    bars.forEach((bar, index) => {
      const point = series[index];
      const height = point && point.value > 0
        ? Math.max(10, Math.round((point.value / maxValue) * 100))
        : 4;
      bar.style.setProperty("--v", `${height}%`);
      if (point) {
        bar.title = `${point.date}：${point.value} 局`;
        bar.dataset.date = point.date;
        bar.dataset.value = String(point.value);
      } else {
        bar.removeAttribute("title");
        delete bar.dataset.date;
        delete bar.dataset.value;
      }
    });
  });
}

function renderOverview(mainViewState) {
  renderMatchCountMetric(mainViewState);

  const history = mainViewState && mainViewState.history;
  const admission = mainViewState && mainViewState.admission;

  document.querySelectorAll('[data-metric="totalRecords"]').forEach((totalCard) => {
    const valTarget = totalCard.querySelector("[data-value]");
    const totalCount = history && Number.isInteger(history.totalCount) ? history.totalCount : "--";
    if (valTarget) valTarget.textContent = String(totalCount);
  });

  document.querySelectorAll('[data-metric="admittedRecords"]').forEach((admittedCard) => {
    const valTarget = admittedCard.querySelector("[data-value]");
    const admittedCount = admission && Number.isInteger(admission.admittedCount) ? admission.admittedCount : "--";
    if (valTarget) valTarget.textContent = String(admittedCount);
  });

  document.querySelectorAll('[data-metric="excludedRecords"]').forEach((excludedCard) => {
    const valTarget = excludedCard.querySelector("[data-value]");
    const excludedCount = admission && Number.isInteger(admission.excludedCount) ? admission.excludedCount : "--";
    if (valTarget) valTarget.textContent = String(excludedCount);
  });
}

function renderAnalysis(mainViewState) {
  const analysis = mainViewState && mainViewState.analysis;
  const statusBadge = document.getElementById("analysis-status-badge");
  const statusHint = document.getElementById("analysis-status-hint");
  const titleEl = document.getElementById("analysis-title");
  const descEl = document.getElementById("analysis-desc");

  const maeEl = document.getElementById("eval-mae-value");
  const calibEl = document.getElementById("eval-calib-value");
  const safeEl = document.getElementById("eval-safe-value");

  if (analysis && analysis.availability === "AVAILABLE") {
    if (statusBadge) {
      statusBadge.className = "tag is-ready";
      statusBadge.textContent = "正式评估已发布";
    }
    if (statusHint) statusHint.textContent = "已达评估样本门槛";
    if (titleEl) titleEl.textContent = analysis.title || "模型预测表现评估";
    if (descEl) descEl.textContent = analysis.description || "基于当前符合评估条件的真实对局样本统计。";

    if (maeEl && analysis.mae != null) {
      maeEl.textContent = formatCurrency(analysis.mae);
      maeEl.classList.add("is-active");
    }
    if (calibEl && analysis.calibrationCoverage != null) {
      calibEl.textContent = `${(analysis.calibrationCoverage * 100).toFixed(1)}%`;
      calibEl.classList.add("is-active");
    }
    if (safeEl && analysis.safetyRatio != null) {
      safeEl.textContent = `${(analysis.safetyRatio * 100).toFixed(1)}%`;
      safeEl.classList.add("is-active");
    }
  } else {
    if (statusBadge) {
      statusBadge.className = "tag is-warning";
      statusBadge.textContent = "评估样本积累中";
    }
    if (statusHint) statusHint.textContent = "正式评估门槛未就绪";
    if (titleEl) titleEl.textContent = (analysis && analysis.title) || "暂无足够正式评估数据";
    if (descEl) descEl.textContent = (analysis && analysis.description) || "当前尚未积累足够符合正式评估条件的实战对局样本。异环拍卖助手坚持真实性与严谨性，绝不展示任何预设或虚构的准确率指标。完成更多完整对局后，系统将自动发布正式估值误差分布与分位数区间校准分析。";

    if (maeEl) {
      maeEl.textContent = "样本积累中";
      maeEl.classList.remove("is-active");
    }
    if (calibEl) {
      calibEl.textContent = "样本积累中";
      calibEl.classList.remove("is-active");
    }
    if (safeEl) {
      safeEl.textContent = "样本积累中";
      safeEl.classList.remove("is-active");
    }
  }
}

function ensureLegacyLoaded() {
  if (dashboard.legacyRecords === null && dashboard.legacyLoadRequested !== true) {
    dashboard.legacyLoadRequested = true;
    postNative("request_legacy_archive");
  }
}

function projectLiveTrialDraft(record) {
  const qualities = record?.qualities || {};
  const known = color => (qualities[color]?.knownItems || [])
    .map(item => item?.name || item?.value || "").filter(Boolean).join("+");
  const facts = {
    ...record,
    q: record?.q ?? record?.publicIntel?.q,
    totalItems: record?.totalItems ?? record?.publicIntel?.totalItems,
    totalGrid: record?.totalGrid ?? record?.publicIntel?.totalGrid,
    goldAvg: record?.goldAvg ?? qualities.gold?.avg,
    purpleCount: record?.purpleCount ?? qualities.purple?.count,
    purpleAvg: record?.purpleAvg ?? qualities.purple?.avg,
    blueCount: record?.blueCount ?? qualities.blue?.count,
    goldCount: record?.goldCount ?? qualities.gold?.count,
    redCount: record?.redCount ?? qualities.red?.count,
    whiteCount: record?.whiteCount ?? qualities.white?.count,
    whiteAvg: record?.whiteAvg ?? qualities.white?.avg,
    greenCount: record?.greenCount ?? qualities.green?.count,
    greenAvg: record?.greenAvg ?? qualities.green?.avg,
    blueAvg: record?.blueAvg ?? qualities.blue?.avg,
    knownGold: record?.knownGold ?? known("gold"),
    knownPurple: record?.knownPurple ?? known("purple"),
    knownRed: record?.knownRed ?? known("red"),
    knownBlue: record?.knownBlue ?? known("blue"),
    knownGreen: record?.knownGreen ?? known("green"),
    knownWhite: record?.knownWhite ?? known("white")
  };
  return {
    kind: "current", recordSource: "live-trial", id: record?.id,
    playedAt: record?.playedAt, localPlayedAt: record?.playedAt,
    lifecycle: "DRAFT", admitted: false, exclusionReason: "隔离试用草稿",
    environment: record?.environment || {}, observedFacts: facts,
    prediction: { hasSnapshot: false }, settlement: record?.settlement || { isSettled: false },
    settlementEvidenceAvailable: Boolean(record?.settlement?.truthEvidence?.evidenceReferences?.length),
    settlementReviewed: Boolean(record?.settlement?.reviewedItems?.length),
    auctionEvidence: record?.auctionEvidence,
    matchSummary: "隔离试用草稿 · 未进入正式 History", dataOrigin: "live-trial"
  };
}

function buildHistoryItems() {
  const current = (dashboard.lastMainViewState && dashboard.lastMainViewState.history && Array.isArray(dashboard.lastMainViewState.history.recentRecords))
    ? dashboard.lastMainViewState.history.recentRecords.map((r) => ({ kind: "current", ...r }))
    : [];
  const liveTrial = (dashboard.lastMainViewState && dashboard.lastMainViewState.history && Array.isArray(dashboard.lastMainViewState.history.liveTrialDrafts))
    ? dashboard.lastMainViewState.history.liveTrialDrafts.map(projectLiveTrialDraft)
    : [];
  const legacy = (dashboard.legacyRecords || []).map((r) => ({ kind: "legacy", ...r }));
  return [...liveTrial, ...current, ...legacy];
}

function historySelectionKey(recordId, source) {
  return `${source || "current"}:${recordId || ""}`;
}

function updateHistorySelectionControls() {
  const selectAll = document.getElementById("history-select-all");
  const deleteSelected = document.getElementById("history-delete-selected-btn");
  const visibleCheckboxes = Array.from(document.querySelectorAll("#history-list .history-record-checkbox"))
    .filter(node => !node.hidden && !node.disabled);
  const checkedCount = dashboard.selectedHistoryRecords.size;
  if (deleteSelected) {
    deleteSelected.disabled = checkedCount === 0;
    deleteSelected.textContent = checkedCount ? `删除所选（${checkedCount}）` : "删除所选";
  }
  if (selectAll) {
    const visibleChecked = visibleCheckboxes.filter((node) => node.checked).length;
    selectAll.checked = visibleCheckboxes.length > 0 && visibleChecked === visibleCheckboxes.length;
    selectAll.indeterminate = visibleChecked > 0 && visibleChecked < visibleCheckboxes.length;
    selectAll.disabled = visibleCheckboxes.length === 0;
  }
}

function setHistorySelection(recordId, source, checked) {
  const id = String(recordId || "").trim();
  if (source !== "current" && source !== "legacy") return;
  const kind = source === "legacy" ? "legacy" : "current";
  if (!id) return;
  const key = historySelectionKey(id, kind);
  if (checked) {
    dashboard.selectedHistoryRecords.set(key, { recordId: id, source: kind });
  } else {
    dashboard.selectedHistoryRecords.delete(key);
  }
  updateHistorySelectionControls();
}

function getRecordShanghaiParts(isoStr) {
  if (!isoStr) return { dateStr: "未知日期", timeStr: "--:--", fullStr: "未知时间", timestamp: 0 };
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) {
    const clean = isoStr.replace("T", " ").slice(0, 16);
    const datePart = clean.slice(0, 10) || "未知日期";
    const timePart = clean.slice(11, 16) || "--:--";
    return { dateStr: datePart, timeStr: timePart, fullStr: clean, timestamp: 0 };
  }
  // Convert to Shanghai UTC+8
  const utc = d.getTime() + (d.getTimezoneOffset() * 60000);
  const shDate = new Date(utc + (3600000 * 8));
  const pad = (n) => String(n).padStart(2, "0");
  const yyyy = shDate.getFullYear();
  const mm = pad(shDate.getMonth() + 1);
  const dd = pad(shDate.getDate());
  const hh = pad(shDate.getHours());
  const min = pad(shDate.getMinutes());
  return {
    dateStr: `${yyyy}-${mm}-${dd}`,
    timeStr: `${hh}:${min}`,
    fullStr: `${yyyy}-${mm}-${dd} ${hh}:${min}`,
    timestamp: d.getTime(),
  };
}

function matchesFilter(it, f) {
  // 1. Primary Tab: all | pending | verified
  const isReviewed = Boolean(
    it.settlementReviewed === true ||
    it.reviewed === true ||
    (it.settlement && (it.settlement.verified === true || it.settlement.settlementReviewed === true))
  );
  if (f.primaryTab === "verified" && !isReviewed) return false;
  if (f.primaryTab === "pending" && isReviewed) return false;

  // 2. Source: all | current | legacy
  if (f.source === "current" && it.kind !== "current") return false;
  if (f.source === "legacy" && it.kind !== "legacy") return false;

  // 3. Outcome: all | settled | unsettled | abandoned
  const isSettled = Boolean(it.lifecycle === "FINALIZED" || it.isSettled === true || (it.settlement && it.settlement.isSettled === true));
  const isAbandoned = Boolean(it.lifecycle === "CANCELLED" || it.outcome === "folded" || it.exclusionReason === "CANCELLED");
  const isUnsettled = !isSettled && !isAbandoned;
  if (f.outcome === "settled" && !isSettled) return false;
  if (f.outcome === "unsettled" && !isUnsettled) return false;
  if (f.outcome === "abandoned" && !isAbandoned) return false;

  // 4. Evidence (Screenshot): all | has | none
  const hasShot = it.kind === "legacy"
    ? Boolean(it.screenshotAvailable)
    : (it.recordSource === "live-trial"
      ? Boolean(it.auctionEvidence?.nativeObservation?.sourceFrames?.length)
      : Boolean(it.settlementEvidenceAvailable === true || (it.settlement && it.settlement.settlementEvidenceAvailable === true)));
  if (f.evidence === "has" && !hasShot) return false;
  if (f.evidence === "none" && hasShot) return false;

  // 5. Admission: all | admitted | excluded
  if (f.admission === "admitted") {
    if (!(it.admitted === true || (it.kind === "legacy" && it.status === "verified"))) return false;
  } else if (f.admission === "excluded") {
    if (it.admitted !== false) return false;
  }

  // 6. Time Range (Shanghai natural day boundaries)
  const rawTime = it.localPlayedAt || it.playedAt || "";
  const parts = getRecordShanghaiParts(rawTime);
  if (f.timeRange === "today") {
    const nowParts = getRecordShanghaiParts(new Date().toISOString());
    if (parts.dateStr !== nowParts.dateStr) return false;
  } else if (f.timeRange === "7d") {
    if (parts.timestamp > 0 && Date.now() - parts.timestamp > 7 * 86400000) return false;
  } else if (f.timeRange === "30d") {
    if (parts.timestamp > 0 && Date.now() - parts.timestamp > 30 * 86400000) return false;
  } else if (f.timeRange === "custom") {
    if (f.startDate && parts.dateStr < f.startDate) return false;
    if (f.endDate && parts.dateStr > f.endDate) return false;
  }

  // 7. Search text
  if (f.search) {
    const env = it.environment || {};
    const hay = `${env.venueName || env.venue || it.venue || ""} ${env.box || it.box || ""} ${it.id || it.key || ""}`.toLowerCase();
    if (!hay.includes(f.search.toLowerCase())) return false;
  }
  return true;
}

function renderHistoryList(items) {
  const listContainer = document.getElementById("history-list");
  const countBadge = document.getElementById("history-count-badge");
  const emptyState = document.getElementById("history-empty-state");
  const errorState = document.getElementById("history-error-state");
  if (errorState) errorState.hidden = true;
  const trialCount = items.filter(item => item.recordSource === "live-trial").length;
  countBadge.textContent = trialCount ? `${items.length} 条（含 ${trialCount} 条隔离草稿）` : `${items.length} 条`;
  listContainer.innerHTML = "";
  if (items.length === 0) {
    if (emptyState) emptyState.hidden = false;
    updateHistorySelectionControls();
    return;
  }
  if (emptyState) emptyState.hidden = true;

  // Group items by Shanghai date
  const groups = {};
  items.forEach((it) => {
    const rawTime = it.localPlayedAt || it.playedAt || "";
    const parts = getRecordShanghaiParts(rawTime);
    it._shParts = parts;
    const key = parts.dateStr || "其他日期";
    if (!groups[key]) groups[key] = [];
    groups[key].push(it);
  });

  Object.keys(groups).forEach((dateKey) => {
    const dateHeader = document.createElement("div");
    dateHeader.className = "history-date-group-header";
    dateHeader.textContent = dateKey;
    listContainer.appendChild(dateHeader);

    groups[dateKey].forEach((it) => {
      const item = document.createElement("div");
      item.className = "history-item";
      item.setAttribute("data-record-id", it.id || it.key);
      const isSelected = it.kind === "current"
        ? it.id === dashboard.selectedRecordId
        : it.key === dashboard.selectedLegacyKey;
      if (isSelected) item.classList.add("is-selected");

      const timeStr = it._shParts ? it._shParts.fullStr : (it.localPlayedAt || it.playedAt || "").replace("T", " ").slice(0, 16);
      const env = it.environment || {};
      const venueName = env.venueName || env.venue || it.venue || "未指定会场";
      const boxName = env.box || it.box || "";
      
      const isSettled = it.lifecycle === "FINALIZED" || it.isSettled === true || (it.settlement && it.settlement.isSettled === true);
      const isCancelled = it.lifecycle === "CANCELLED" || it.outcome === "folded";
      const isCompleted = it.kind === "legacy" ? isSettled : it.lifecycle === "FINALIZED";
      const outcomeBadge = it.recordSource === "live-trial"
        ? `<span class="item-badge badge-draft">隔离草稿</span>`
        : isCompleted
        ? `<span class="item-badge badge-finalized">已结算</span>`
        : (isCancelled ? `<span class="item-badge badge-cancelled">已放弃</span>`
          : `<span class="item-badge badge-draft">${isSettled ? "待补全" : "未结算"}</span>`);

      const isReviewed = Boolean(
        it.settlementReviewed === true ||
        it.reviewed === true ||
        (it.settlement && (it.settlement.verified === true || it.settlement.settlementReviewed === true))
      );
      const reviewedBadge = isReviewed ? `<span class="item-badge badge-admitted">已核对</span>` : "";

      const hasShot = (it.kind === "legacy"
        ? !!it.screenshotAvailable
        : (it.recordSource === "live-trial"
          ? Boolean(it.auctionEvidence?.nativeObservation?.sourceFrames?.length)
          : (it.settlementEvidenceAvailable === true || (it.settlement && it.settlement.settlementEvidenceAvailable === true))));
      const shotBadge = hasShot ? `<span class="item-badge badge-shot" title="有结算截图">📷 截图</span>` : "";
      
      const st = it.settlement || {};
      let resultSummary = "未结算";
      if (isSettled) {
        const total = it.actualTotal != null ? it.actualTotal : st.actualTotal;
        if (total != null) resultSummary = `总值 ${formatCurrency(total)}`;
      }

      item.innerHTML = `
        <div class="history-item-top">
          <label class="history-item-select" title="选择此条记录">
            <input type="checkbox" class="history-record-checkbox" data-record-id="${escapeHtml(it.id || it.key)}" data-source="${escapeHtml(it.recordSource || it.kind)}" ${it.recordSource === "live-trial" ? "hidden disabled" : ""} ${dashboard.selectedHistoryRecords.has(historySelectionKey(it.id || it.key, it.kind)) ? "checked" : ""} />
            <span class="history-item-time">${timeStr}</span>
          </label>
          <div class="history-item-badges">${outcomeBadge}${reviewedBadge}${shotBadge}</div>
        </div>
        <div class="history-item-venue">${venueName} ${boxName ? `· ${boxName}` : ""}</div>
        <div class="history-item-summary">${resultSummary}</div>
      `;

      item.addEventListener("click", () => {
        if (it.kind === "legacy") {
          if (dashboard.selectedLegacyKey === it.key && dashboard.selectedRecord && dashboard.selectedRecord.kind === "legacy") return;
          dashboard.selectedLegacyKey = it.key;
          dashboard.selectedRecordId = null;
          listContainer.querySelectorAll(".history-item").forEach((el) => {
            el.classList.toggle("is-selected", el === item);
          });
          showLegacyReviewDetail(it.key);
        } else {
          if (dashboard.selectedRecordId === it.id && dashboard.selectedRecord && dashboard.selectedRecord.id === it.id && dashboard.selectedRecord.kind !== "legacy") return;
          dashboard.selectedRecordId = it.id;
          dashboard.selectedLegacyKey = null;
          listContainer.querySelectorAll(".history-item").forEach((el) => {
            el.classList.toggle("is-selected", el === item);
          });
          renderHistoryDetail(it);
        }
      });
      const checkbox = item.querySelector(".history-record-checkbox");
      if (checkbox) {
        checkbox.addEventListener("click", (event) => event.stopPropagation());
        checkbox.addEventListener("change", (event) => {
          setHistorySelection(event.target.dataset.recordId, event.target.dataset.source, event.target.checked);
        });
      }
      listContainer.appendChild(item);
    });
  });
  updateHistorySelectionControls();
}

function applyHistoryFilters() {
  const f = dashboard.historyFilter;
  const items = buildHistoryItems();
  const filtered = items.filter((it) => matchesFilter(it, f));
  renderHistoryList(filtered);
  if (f.source !== "current" && dashboard.legacyRecords === null) ensureLegacyLoaded();

  let currentSelection = null;
  if (dashboard.selectedRecordId) {
    currentSelection = filtered.find((it) => it.kind === "current" && it.id === dashboard.selectedRecordId);
  } else if (dashboard.selectedLegacyKey) {
    currentSelection = filtered.find((it) => it.kind === "legacy" && it.key === dashboard.selectedLegacyKey);
  }
  if (currentSelection) {
    const isAlreadySelected = (
      dashboard.selectedRecord &&
      (currentSelection.kind === "legacy"
        ? (dashboard.selectedRecord.kind === "legacy" && (dashboard.selectedRecord.key === currentSelection.key || dashboard.selectedRecord.id === currentSelection.key))
        : (dashboard.selectedRecord.kind !== "legacy" && dashboard.selectedRecord.id === currentSelection.id))
    );
    if (!isAlreadySelected) {
      if (currentSelection.kind === "legacy") {
        showLegacyReviewDetail(currentSelection.key);
      } else {
        renderHistoryDetail(currentSelection);
      }
    }
  } else if (filtered.length > 0) {
    const first = filtered[0];
    if (first.kind === "legacy") {
      dashboard.selectedLegacyKey = first.key;
      dashboard.selectedRecordId = null;
      showLegacyReviewDetail(first.key);
    } else {
      dashboard.selectedRecordId = first.id;
      dashboard.selectedLegacyKey = null;
      renderHistoryDetail(first);
    }
  } else {
    dashboard.selectedRecordId = null;
    dashboard.selectedLegacyKey = null;
    renderHistoryDetail(null);
  }
}

function renderHistory(mainViewState) {
  dashboard.lastMainViewState = mainViewState;
  renderGuidebook();
  const history = mainViewState && mainViewState.history;
  const availability = history ? history.availability : "UNAVAILABLE";
  const errorState = document.getElementById("history-error-state");
  const emptyState = document.getElementById("history-empty-state");
  const listContainer = document.getElementById("history-list");
  const countBadge = document.getElementById("history-count-badge");
  const placeholder = document.getElementById("history-detail-placeholder");
  const detailCard = document.getElementById("history-detail-card");

  if (!["AVAILABLE", "EMPTY"].includes(availability)) {
    if (emptyState) emptyState.hidden = true;
    if (errorState) errorState.hidden = false;
    if (listContainer) listContainer.innerHTML = "";
    if (countBadge) countBadge.textContent = "不可用";
    if (placeholder) placeholder.hidden = false;
    if (detailCard) detailCard.hidden = true;
    const errorDesc = document.getElementById("history-error-desc");
    const errorMap = {
      CORRUPT: "本地历史文件损坏或格式无法解析，已启用安全保护。",
      UNAVAILABLE: "本地历史存储服务暂不可用。",
      MIGRATION_REQUIRED: "检测到旧版数据，需要迁移确认。",
      MIGRATION_CONFLICT: "历史数据版本冲突，已进入只读保护模式。",
    };
    if (errorDesc) errorDesc.textContent = errorMap[availability] || "历史数据暂不可用";
    return;
  }
  if (errorState) errorState.hidden = true;
  applyHistoryFilters();
  if (availability === "EMPTY" && (dashboard.legacyRecords === null || dashboard.legacyRecords.length === 0)) {
    if (emptyState) emptyState.hidden = false;
  }
}

function renderHistoryDetail(record) {
  if (dashboard.historicalWarehouseReview && dashboard.historicalWarehouseReview !== record?.id) resetHistoricalWarehouseReview();
  dashboard.historyDetailRenderCount = (dashboard.historyDetailRenderCount || 0) + 1;
  const placeholder = document.getElementById("history-detail-placeholder");
  const detailCard = document.getElementById("history-detail-card");

  if (!record) {
    placeholder.hidden = false;
    detailCard.hidden = true;
    dashboard.selectedRecord = null;
    return;
  }

  dashboard.selectedRecord = record;
  renderAuctionEvidence(record, detailCard);
  let originals = document.getElementById("history-originals");
  if (!originals) {
    originals = document.createElement("div");
    originals.id = "history-originals";
    originals.className = "detail-section";
    detailCard.appendChild(originals);
  }
  const recordSource = record.recordSource || "current";
  if (originals.dataset.recordId !== record.id || originals.dataset.source !== recordSource) requestOriginalScreenshots(record.id, "history-originals", recordSource);
  placeholder.hidden = false;
  placeholder.hidden = true;
  detailCard.hidden = false;
  // Restore all detail sections (a previous legacy selection may have hidden them).
  document.querySelectorAll("#history-detail-card .detail-section").forEach((section) => {
    section.hidden = false;
  });

  // Header
  const env = record.environment || {};
  const venueTitle = `${env.venueName || env.venue || "对局详情"}${env.box ? ` · ${env.box}` : ""}`;
  const titleEl = document.getElementById("detail-match-title");
  if (titleEl) titleEl.textContent = venueTitle;
  const matchIdEl = document.getElementById("detail-match-id");
  if (matchIdEl) matchIdEl.textContent = record.id || "--";
  document.getElementById("detail-played-at").textContent = `对局时间：${record.localPlayedAt || record.playedAt || "未知时间"}`;

  const lifecycleBadge = document.getElementById("detail-lifecycle-badge");
  lifecycleBadge.className = "badge";
  if (record.lifecycle === "FINALIZED") {
    lifecycleBadge.classList.add("badge-finalized");
    lifecycleBadge.textContent = "已完成";
  } else if (record.lifecycle === "CANCELLED") {
    lifecycleBadge.classList.add("badge-cancelled");
    lifecycleBadge.textContent = "已放弃";
  } else if (record.lifecycle === "DRAFT") {
    lifecycleBadge.classList.add("badge-draft");
    lifecycleBadge.textContent = "草稿";
  } else {
    lifecycleBadge.classList.add("badge-unknown");
    lifecycleBadge.textContent = record.lifecycle || "未指定";
  }

  const admissionBadge = document.getElementById("detail-admission-badge");
  if (admissionBadge) {
    admissionBadge.hidden = recordSource === "live-trial";
    admissionBadge.className = "badge";
    if (record.admitted) {
      admissionBadge.classList.add("badge-admitted");
      admissionBadge.textContent = "准入通过";
    } else {
      admissionBadge.classList.add("badge-excluded");
      admissionBadge.textContent = `排除：${formatExclusionReason(record.exclusionReason)}`;
    }
  }
  const draftSaveStatus = document.getElementById("detail-draft-save-status");
  if (draftSaveStatus) {
    draftSaveStatus.hidden = recordSource !== "live-trial";
    draftSaveStatus.textContent = recordSource === "live-trial" ? "隔离草稿已保存" : "";
  }

  const deleteBtn = document.getElementById("detail-delete-btn");
  if (deleteBtn) {
    deleteBtn.hidden = recordSource === "live-trial";
    deleteBtn.style.display = recordSource === "live-trial" ? "none" : "";
  }

  const facts = record.observedFacts || {};
  const prediction = record.prediction || {};
  const settlement = record.settlement || {};
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  // Section 0: Match Summary (Phase 18: runtime deterministic presentation text)
  const summarySection = document.getElementById("detail-summary-section");
  const summaryText = document.getElementById("detail-match-summary");
  if (summarySection && summaryText) {
    const summaryVal = typeof record.matchSummary === "string" ? record.matchSummary.trim() : "";
    if (summaryVal) {
      summaryText.textContent = summaryVal;
      summarySection.hidden = false;
    } else {
      summaryText.textContent = "";
      summarySection.hidden = true;
    }
  }

  // Section 1: Environment & Observed Facts (bounded projection only).
  setText("detail-venue", env.venueName || env.venue || "未记录");
  setText("detail-box", env.box || "未记录");
  setText("detail-condition", env.fieldConditionName || env.fieldCondition || "标准规则");
  setText("detail-q", facts.q != null ? String(facts.q) : "未记录");
  setText("detail-gold-avg", facts.goldAvg != null ? formatCurrency(facts.goldAvg) : "未记录");
  setText("detail-purple-count", facts.purpleCount != null ? String(facts.purpleCount) : "未记录");
  setText("detail-purple-avg", facts.purpleAvg != null ? formatCurrency(facts.purpleAvg) : "未记录");
  for (const color of ["gold", "purple", "red", "blue", "green", "white"]) {
    setText(`detail-known-${color}`, facts["known" + color[0].toUpperCase() + color.slice(1)] || "未记录");
  }
  setText("detail-blue-count", facts.blueCount != null ? String(facts.blueCount) : "未记录");
  setText("detail-gold-count", facts.goldCount != null ? String(facts.goldCount) : "未记录");
  setText("detail-red-count", facts.redCount != null ? String(facts.redCount) : "未记录");
  setText("detail-total-items", facts.totalItems != null ? String(facts.totalItems) : "未记录");
  setText("detail-total-grid", facts.totalGrid != null ? String(facts.totalGrid) : "未记录");
  setText("detail-gold-grid", facts.goldGrid != null ? String(facts.goldGrid) : "未记录");
  setText("detail-purple-grid", facts.purpleGrid != null ? String(facts.purpleGrid) : "未记录");
  setText("detail-white-count", facts.whiteCount != null ? String(facts.whiteCount) : "未记录");
  setText("detail-white-avg", facts.whiteAvg != null ? String(facts.whiteAvg) : "未记录");
  setText("detail-white-grid", facts.whiteGrid != null ? String(facts.whiteGrid) : "未记录");
  setText("detail-green-count", facts.greenCount != null ? String(facts.greenCount) : "未记录");
  setText("detail-green-avg", facts.greenAvg != null ? String(facts.greenAvg) : "未记录");
  setText("detail-green-grid", facts.greenGrid != null ? String(facts.greenGrid) : "未记录");
  setText("detail-blue-avg", facts.blueAvg != null ? String(facts.blueAvg) : "未记录");
  setText("detail-dark-controls", `${facts.privateBidCap ?? "未记录"} ／ ${facts.bidActionCount ?? "未记录"}`);
  setText("detail-session-accounting", sessionAccountingText(facts.sessionAccounting));
  setText("detail-intel-evidence", facts.intelEvidenceSummary || "未记录情报识别证据");
  setText("detail-blue-grid", facts.blueGrid != null ? String(facts.blueGrid) : "未记录");
  setText("detail-sparkle", facts.sparkle == null ? "未记录" : `转换宝石总数：${facts.sparkle.transformedOneByOneCount ?? '未知'}；已确认：${sparkleNames(facts.sparkle) || '未填写'}`);
  setText("detail-red-grid", facts.redGrid != null ? String(facts.redGrid) : "未记录");

  setText("detail-entry-cost", env.entryCost != null ? formatCurrency(env.entryCost) : "未记录");

  // Warehouse summary (Phase 10: bounded canonical summary)
  const warehouse = record.warehouse;
  const reviewUnits = (record.settlement && record.settlement.reviewUnits) || record.reviewUnits || [];
  let warehouseText = "未记录";
  if (warehouse && typeof warehouse === "object" && typeof warehouse.itemCount === "number" && warehouse.itemCount > 0) {
    const total = warehouse.itemCount;
    const unknown = warehouse.unknownCount || 0;
    if (unknown > 0) {
      warehouseText = `${total} 件（其中 ${unknown} 件未具名）`;
    } else {
      warehouseText = `${total} 件`;
    }
  } else if (reviewUnits.length > 0) {
    const confirmedCount = reviewUnits.filter(u => u.status === 'CONFIRMED' || u.confirmed || u.exactMatch).length;
    const unconfirmedCount = reviewUnits.length - confirmedCount;
    warehouseText = unconfirmedCount > 0 ? `${reviewUnits.length} 件（其中 ${unconfirmedCount} 件待确认）` : `${reviewUnits.length} 件`;
  }
  setText("detail-warehouse", warehouseText);

  // Section 2: Persisted prediction snapshot; never recompute in Main.
  const hasPrediction = prediction.hasSnapshot === true;
  setText("detail-p20", hasPrediction ? formatCurrency(prediction.p20) : "未记录");
  setText("detail-p50", hasPrediction ? formatCurrency(prediction.p50) : "未记录");
  setText("detail-p80", hasPrediction ? formatCurrency(prediction.p80) : "未记录");
  setText("detail-rec-max", hasPrediction ? formatCurrency(prediction.recommendedMax) : "未记录");

  setText("detail-cost-summary", record.costSummary || "费用未记录");

  // Section 3: Settlement truth remains separate from Snapshot facts.
  const settlementFields = document.getElementById("detail-settlement-fields");
  const settlementAbsent = document.getElementById("detail-settlement-absent");
  const isSettled = settlement.isSettled === true;
  if (settlementFields) settlementFields.hidden = !isSettled;
  if (settlementAbsent) settlementAbsent.hidden = isSettled;
  setText("detail-clearing-price", isSettled ? formatCurrency(settlement.clearingPrice) : "未记录");
  setText("detail-actual-total", isSettled ? formatCurrency(settlement.actualTotal) : "未记录");
  setText("detail-profit", isSettled ? formatSettlementProfit(settlement) : "未记录");
  let acquiredText = "归属未知";
  if (settlement.acquired === true) acquiredText = "本人拍下";
  else if (settlement.acquired === false) acquiredText = "他人拍下";
  if (settlement.winner) acquiredText += " · " + settlement.winner;
  setText("detail-acquired", acquiredText);

  const qSel = settlement.qualitySellSelection;
  const qSrc = settlement.qualitySellSelectionSource;
  const qSources = settlement.qualitySellSelectionSources;
  let qSelText = "未记录";
  if (qSel && typeof qSel === "object") {
    const colorNames = { white: "白", green: "绿", blue: "蓝", purple: "紫", gold: "金", red: "红" };
    const srcMarks = { default_self_acquired: "默认", visual_observed: "视觉", manual_override: "人工", unknown: "" };
    const hasPerColor = qSources && typeof qSources === "object";
    const parts = [];
    for (const [col, cname] of Object.entries(colorNames)) {
      const state = qSel[col];
      const stateChar = state === "selected" ? "✓" : (state === "unselected" ? "✗" : "?");
      // Per-color provenance: a single manual toggle must not relabel the rest.
      const perColor = hasPerColor ? (srcMarks[qSources[col]] || "") : "";
      const mark = hasPerColor ? (perColor ? `·${perColor}` : "") : "";
      parts.push(`${cname}:${stateChar}${mark}`);
    }
    const srcDesc = hasPerColor
      ? " (逐色来源)"
      : (qSrc === "default_self_acquired" ? " (本人拍下默认)" : (qSrc === "visual_observed" ? " (视觉识别)" : (qSrc === "manual_override" ? " (人工修改)" : "")));
    qSelText = parts.join(" ") + srcDesc;
  }
  setText("detail-sell-selection", qSelText);

  // Settlement Review section: load the whitelisted review DTO for this record.
  const isReviewLoaded = (
    dashboard.review &&
    dashboard.review.recordId === record.id &&
    dashboard.reviewSource === recordSource
  );
  const isReviewPending = (
    dashboard.pendingReviewRecordId === record.id &&
    dashboard.pendingReviewSource === recordSource
  );
  if (!isReviewLoaded && !isReviewPending) {
    loadSettlementReview(record.id, recordSource);
  }
}

function renderAuctionEvidence(record, parent) {
  let section = document.getElementById('history-auction-evidence');
  if (!section) {
    section = document.createElement('div');
    section.id = 'history-auction-evidence';
    section.className = 'detail-section';
    parent.appendChild(section);
  }
  section.replaceChildren();
  const evidence = record.auctionEvidence;
  if (!evidence) return;
  let container=section;
  const add = (tag, text) => {const el=document.createElement(tag);el.textContent=text;container.appendChild(el);};
  const group = (text) => {
    const details=document.createElement('details');
    details.className='auction-evidence-group';
    const summary=document.createElement('summary');summary.textContent=text;
    details.appendChild(summary);section.appendChild(details);container=details;
  };
  group(`情报原文（${(evidence.intel || []).length} 条变化记录）`);
  for (const observation of evidence.intel || []) {
    add('p',`第 ${observation.round ?? '?'} 回合 · ${observation.capturedAt || ''}`);
    add('p',(observation.lines || []).map(line=>line.text).join('；'));
  }
  const rawBids = evidence.bids || [];
  const roundMap = new Map();
  for (const obs of rawBids) {
    const r = obs.round ?? 1;
    if (!roundMap.has(r)) {
      roundMap.set(r, {
        round: r,
        capturedAt: obs.capturedAt,
        seats: (obs.seats || []).map(s => ({ ...s }))
      });
    } else {
      const existing = roundMap.get(r);
      existing.capturedAt = obs.capturedAt || existing.capturedAt;
      const seatBySlot = new Map();
      for (const s of existing.seats) seatBySlot.set(s.slot, s);
      for (const s of (obs.seats || [])) {
        if (!seatBySlot.has(s.slot)) {
          existing.seats.push({ ...s });
        } else {
          const target = seatBySlot.get(s.slot);
          if (s.name && (!target.name || target.name === `座位 ${s.slot}` || target.name.includes('未识别'))) {
            target.name = s.name;
          }
          if (s.currentBid != null) target.currentBid = s.currentBid;
          if (s.bid != null && s.bid >= 0) target.bid = s.bid;
          if (s.observationStatus) target.observationStatus = s.observationStatus;
        }
      }
    }
  }
  const consolidatedBids = Array.from(roundMap.values()).sort((a, b) => (Number(a.round) || 0) - (Number(b.round) || 0));
  group(`四人出价（共 ${consolidatedBids.length} 回合）`);
  for (const observation of consolidatedBids) {
    add('p',`第 ${observation.round ?? '?'} 回合 · ` + (observation.seats || []).map(seat=>
      `${seat.name || `座位 ${seat.slot}`}：${seat.currentBid != null ? seat.currentBid : (seat.bid != null && seat.bid >= 0 ? seat.bid : '未识别')}`).join(' / '));
  }
  const reviewUnits = (record.settlement && record.settlement.reviewUnits) || record.reviewUnits || [];
  if (reviewUnits && reviewUnits.length > 0) {
    const confirmedCount = reviewUnits.filter(u => u.status === 'CONFIRMED' || u.confirmed || u.exactMatch).length;
    const unconfirmedCount = reviewUnits.length - confirmedCount;
    group(`仓库藏品审阅（共 ${reviewUnits.length} 件 · ${confirmedCount} 件已确认 / ${unconfirmedCount} 件待确认）`);
    for (const unit of reviewUnits) {
      const name = unit.name || unit.selectedCandidateName || unit.identifiedName || (unit.candidates && unit.candidates[0] && (unit.candidates[0].name || unit.candidates[0].catalogId)) || `${unit.w || '?'}×${unit.h || '?'} 藏品`;
      const statusText = (unit.status === 'CONFIRMED' || unit.confirmed) ? '已确认' : '待确认';
      const confText = unit.confidence != null ? ` (置信度 ${(unit.confidence * 100).toFixed(0)}%)` : '';
      add('p', `${name} · ${statusText}${confText}`);
    }
  } else {
    group(`仓库观察（${(evidence.warehouse || []).length} 个画面）`);
    for (const observation of evidence.warehouse || []) {
      add('p',`${observation.scene === 'SETTLEMENT' ? '结算仓库' : `第 ${observation.round ?? '?'} 回合`} · ${observation.capturedAt || ''} · ${(observation.slots || []).length} 个可见槽位`);
      add('p',(observation.slots || []).map(slot=>(slot.identityStatus === 'EXACT' && slot.identifiedName) || `${slot.w || '?'}×${slot.h || '?'} 轮廓（未确认名称）`).join('；'));
    }
  }
  group('流程与补货');
  const names={AUCTION_LOBBY:'大厅',IN_AUCTION:'局内',SETTLEMENT:'结算',AUCTION_LOADING:'加载',TOOL_REPLENISH:'补货',TOOL_REPLENISH_CONFIRM:'补货确认',MATCHING_SUCCESS:'匹配成功',LOAD_ABORTED:'加载中断，返回大世界',OPEN_WORLD:'大世界'};
  for (const event of evidence.flow || []) add('p',`${event.capturedAt || ''} · ${names[event.scene] || event.scene}${event.lines ? '：'+event.lines.join('；') : ''}`);
  if ((evidence.priorMatchActivity || []).length) add('p','开局前补货属于前局遗留，不计入本局道具消耗。');
  const restock={UNOBSERVED:'尚未观察到补货',NEEDS_REPLENISHMENT:'道具已消耗，待补货',CONFIRMATION_SEEN:'已看到补货确认页，补充结果待核对',COMPLETED:'已确认补货完成'};
  add('p',restock[evidence.replenishment] || '补货结果待核对');
}

function showLegacyReviewDetail(legacyKey) {
  resetHistoricalWarehouseReview();
  const placeholder = document.getElementById("history-detail-placeholder");
  const detailCard = document.getElementById("history-detail-card");
  if (placeholder) placeholder.hidden = true;
  if (detailCard) detailCard.hidden = false;

  const rec = (dashboard.legacyRecords || []).find((r) => r.key === legacyKey) || {};
  dashboard.selectedRecord = { kind: "legacy", ...rec };

  // Header for legacy record
  const titleEl = document.getElementById("detail-match-title");
  if (titleEl) titleEl.textContent = `${rec.venue || "历史归档"}${rec.box ? ` · ${rec.box}` : ""}`;
  const matchIdEl = document.getElementById("detail-match-id");
  if (matchIdEl) matchIdEl.textContent = rec.id || rec.key || legacyKey;

  const playedAtEl = document.getElementById("detail-played-at");
  if (playedAtEl) playedAtEl.textContent = `对局时间：${rec.playedAt || "未知时间"}`;

  const lifecycleBadge = document.getElementById("detail-lifecycle-badge");
  if (lifecycleBadge) {
    lifecycleBadge.className = "badge badge-legacy";
    lifecycleBadge.textContent = "历史归档";
    lifecycleBadge.hidden = false;
  }

  const admissionBadge = document.getElementById("detail-admission-badge");
  if (admissionBadge) {
    admissionBadge.hidden = true;
  }

  // Show delete button for legacy record too
  const deleteBtn = document.getElementById("detail-delete-btn");
  if (deleteBtn) {
    deleteBtn.hidden = false;
    deleteBtn.style.display = "";
    deleteBtn.title = "删除此条历史归档记录";
  }

  // Hide record-specific sections; only the review section applies to legacy.
  const sections = document.querySelectorAll("#history-detail-card .detail-section");
  sections.forEach((section) => {
    if (section.id !== "detail-review-section") section.hidden = true;
  });
  loadSettlementReview(legacyKey, "legacy");
}

const GUIDEBOOK_RARITIES = ["gold", "purple", "red", "blue", "green", "white"];
const GUIDEBOOK_RARITY_LABELS = { gold: "金", purple: "紫", red: "红", blue: "蓝", green: "绿", white: "白" };
const GUIDEBOOK_FACT_LABELS = {
  q: "总高阶件数 Q", goldAvg: "金色均价", purpleCount: "紫色数量",
  purpleAvg: "紫色均价", goldCount: "金色数量", redCount: "红色数量",
  totalItems: "总件数", totalGrid: "总占格"
};

function requestGuidebookSources() {
  if (dashboard.guidebookSources || dashboard.guidebookSourcesRequestId) return;
  const requestId = postNative("request_guidebook_sources");
  if (requestId) dashboard.guidebookSourcesRequestId = requestId;
}

function guidebookCatalogRows() {
  if (Array.isArray(dashboard.guidebookCatalog)) return dashboard.guidebookCatalog;
  const engine = window.AuctionEngineV06;
  if (!engine || typeof engine.baseCatalogFor !== "function") return [];
  const context = { playedAt: new Date().toISOString() };
  const catalog = engine.baseCatalogFor(context) || {};
  const version = typeof engine.catalogVersionFor === "function" ? engine.catalogVersionFor(context) : "当前目录";
  const rows = [];
  for (const rarity of GUIDEBOOK_RARITIES) {
    for (const [index, item] of (Array.isArray(catalog[rarity]) ? catalog[rarity] : []).entries()) {
      const name = String(item?.[0] || "").trim();
      if (!name) continue;
      const price = item[1] == null || item[1] === "" ? null : Number(item[1]);
      rows.push({
        key: `${rarity}:${index}:${name}`,
        rarity,
        name,
        price: Number.isFinite(price) ? price : null,
        footprint: item[2] == null ? "" : String(item[2]),
        catalogVersion: version,
        sourceRecords: []
      });
    }
  }
  for (const source of dashboard.guidebookSources?.items || []) {
    if (!source || typeof source !== "object") continue;
    const solverKey = source.solverMatch?.key;
    const linked = solverKey ? rows.find(row => row.key === solverKey) : null;
    if (linked) {
      linked.sourceRecords.push(source);
      continue;
    }
    rows.push({
      key: source.sourceId || `guidebook14:${source.category}:${source.sourceGeometry}:${source.sourceName}`,
      rarity: source.sourceRarity || "unknown",
      name: String(source.name || source.sourceName || "名称待确认"),
      price: null,
      footprint: source.sourceGeometry || `${source.width || "?"}x${source.height || "?"}`,
      catalogVersion: "1.4 来源资料",
      sourceOnly: true,
      sourceRecords: [source],
      sourceData: source
    });
  }
  dashboard.guidebookCatalog = rows;
  return rows;
}

function guidebookFilterCategory(item) {
  return (item.sourceRecords || []).map(source => source.category).filter(Boolean);
}

function renderGuidebookFilters(rows) {
  const categorySelect = document.getElementById("guidebook-category-filter");
  const gridSelect = document.getElementById("guidebook-grid-filter");
  if (categorySelect) categorySelect.value = dashboard.guidebookCategory || "all";
  if (!gridSelect) return;
  const sizes = [...new Set(rows.map(item => /^\d+x\d+$/i.test(item.footprint || "")
    ? item.footprint.toLowerCase() : "unknown"))].sort((a, b) => {
    if (a === "unknown") return 1;
    if (b === "unknown") return -1;
    const [aw, ah] = a.split("x").map(Number);
    const [bw, bh] = b.split("x").map(Number);
    return aw - bw || ah - bh;
  });
  const options = [`<option value="all">全部尺寸</option>`, ...sizes.map(size =>
    `<option value="${escapeHtml(size)}">${size === "unknown" ? "尺寸未知" : escapeHtml(size.replace("x", " × "))}</option>`
  )];
  gridSelect.innerHTML = options.join("");
  if (dashboard.guidebookGridSize !== "all" && !sizes.includes(dashboard.guidebookGridSize)) dashboard.guidebookGridSize = "all";
  gridSelect.value = dashboard.guidebookGridSize || "all";
}

function guidebookSourceImagesMarkup(source) {
  const images = Array.isArray(source?.sourceImages) ? source.sourceImages : [];
  if (!images.length) return `<p class="guidebook-source-missing">没有保存可回看的来源图片。</p>`;
  return `<div class="guidebook-source-images">${images.map((image, index) => {
    const row = Array.isArray(image.cell) ? Number(image.cell[0]) + 1 : null;
    const column = Array.isArray(image.cell) ? Number(image.cell[1]) + 1 : null;
    const location = row != null && column != null ? `截图卡片位置：第 ${row} 行、第 ${column} 列` : "截图卡片位置未记录";
    const label = `${source.category || "来源图鉴"} · ${source.sourceGeometry || "格子尺寸未知"} · ${location}`;
    return `<details class="guidebook-source-image"><summary>查看来源原图 ${index + 1} · ${escapeHtml(label)}</summary>${image.uri
      ? `<img src="${escapeHtml(image.uri)}" alt="${escapeHtml(source.sourceName || source.name || "藏品")}来源原图" loading="lazy"><small>${escapeHtml(image.path || "")}</small>`
      : `<p class="guidebook-source-missing">来源原图暂不可读取；原文件路径：${escapeHtml(image.path || "未知")}</p>`}</details>`;
  }).join("")}</div>`;
}

function guidebookCatalogDetailMarkup(item) {
  if (!item) return `<span class="tag">本地目录</span><h2>没有匹配条目</h2><p>可清除搜索词或更换筛选条件。</p>`;
  const sources = item.sourceRecords || [];
  const source = sources[0] || null;
  const sourceLabel = source
    ? `<p>1.4 用户分类：${escapeHtml(source.category)} · 素材格子：${escapeHtml(source.sourceGeometry)}。分类来自素材目录，不作为品质或求解规则。</p>`
    : `<p>此条未在本批 1.4 素材中建立来源分类；现有条目身份与估值目录保持不变。</p>`;
  const solverValue = item.sourceOnly
    ? `<p class="guidebook-source-status">仅展示来源资料，未纳入当前求解目录；不会据此产生估值。</p>`
    : `<p>${item.price == null ? "当前求解目录未提供参考价。" : `当前求解目录基础参考价：${formatCurrency(item.price)}`}</p>`;
  const sourceValue = source?.sourcePriceStatus === "VISUALLY_CONFIRMED_1_4_SOURCE" && source.sourcePrice != null
    ? `<p>1.4 原图价签：${formatCurrency(source.sourcePrice)}（已回看原图${source.solverMatch?.price != null && source.sourcePrice !== source.solverMatch.price ? "；与现有目录不同，未替换目录值" : ""}）</p>`
    : source ? `<p>1.4 原图来源已关联；未独立确认的价格保持未知。</p>` : "";
  const conflictMarkup = sources.flatMap(entry => entry.dataConflicts || []).map(conflict =>
    `<p class="guidebook-conflict">待核差异 · ${escapeHtml(conflict.field)}：${escapeHtml(conflict.basis)}</p>`
  ).join("");
  const candidateMarkup = source?.solverCandidate
    ? `<p class="guidebook-conflict">相似求解条目：${escapeHtml(source.solverCandidate.name)}；身份尚未确认，不自动关联。</p>` : "";
  const imageMarkup = sources.map(guidebookSourceImagesMarkup).join("");
  const sourceStatus = item.sourceOnly ? "1.4 来源资料 · 仅展示" : "现有求解目录条目";
  const rarityLabel = GUIDEBOOK_RARITY_LABELS[item.rarity] || "品质未确认";
  return `<span class="${GUIDEBOOK_RARITY_LABELS[item.rarity] ? `rarity-tag is-${item.rarity}` : "tag"}">${rarityLabel}</span><h2>${escapeHtml(item.name)}</h2><p class="guidebook-source-status">${sourceStatus}</p>${solverValue}${sourceLabel}${sourceValue}<p>${item.footprint && item.footprint !== "unknown" ? `现有目录规格：${escapeHtml(item.footprint)}。` : "目录规格未知。"}目录条目不代表本局已经识别或确认了该藏品。</p>${candidateMarkup}${conflictMarkup}${imageMarkup}<small>目录版本：${escapeHtml(item.catalogVersion || "未知")}${source?.visualCatalogId ? ` · 稳定图鉴 ID：${escapeHtml(source.visualCatalogId)}` : ""}</small>`;
}

function renderGuidebookCatalog() {
  const grid = document.getElementById("guidebook-catalog-grid");
  const count = document.getElementById("guidebook-catalog-count");
  const detail = document.getElementById("guidebook-item-detail");
  const sourceNote = document.getElementById("guidebook-catalog-source");
  if (!grid || !count || !detail) return;
  const rows = guidebookCatalogRows();
  const pendingCandidate = dashboard.pendingGuidebookCandidate;
  if (pendingCandidate && dashboard.guidebookSources) {
    const idMatches = rows.filter(item => (item.sourceRecords || []).some(source =>
      String(source.visualCatalogId || source.catalogId || "") === pendingCandidate.catalogId
    ));
    const nameMatches = rows.filter(item => item.name === pendingCandidate.name
      && (!pendingCandidate.rarity || item.rarity === pendingCandidate.rarity));
    const selected = idMatches.length === 1 ? idMatches[0] : (idMatches.length === 0 && nameMatches.length === 1 ? nameMatches[0] : null);
    if (selected) {
      dashboard.guidebookSelectedItem = selected.key;
      dashboard.guidebookSearch = "";
    } else {
      dashboard.guidebookSelectedItem = null;
      dashboard.guidebookSearch = pendingCandidate.name || pendingCandidate.catalogId;
    }
    dashboard.pendingGuidebookCandidate = null;
  }
  renderGuidebookFilters(rows);
  const query = String(dashboard.guidebookSearch || "").trim().toLowerCase();
  const searchInput = document.getElementById("guidebook-catalog-search");
  if (searchInput && document.activeElement !== searchInput) searchInput.value = dashboard.guidebookSearch || "";
  const filtered = rows.filter(item => {
    const categoryMatch = dashboard.guidebookCategory === "all"
      || (dashboard.guidebookCategory === "other" ? !(item.sourceRecords || []).length
        : guidebookFilterCategory(item).includes(dashboard.guidebookCategory));
    const size = /^\d+x\d+$/i.test(item.footprint || "") ? item.footprint.toLowerCase() : "unknown";
    const queryText = [item.name, item.key, ...(item.sourceRecords || []).flatMap(source => [
      source.sourceName, source.visualCatalogId, source.catalogId, source.sourceId, source.solverMatch?.key,
      ...(source.sourceNames || [])
    ])]
      .filter(Boolean).join(" ").toLowerCase();
    return categoryMatch
      && (dashboard.guidebookRarity === "all" || item.rarity === dashboard.guidebookRarity)
      && ((dashboard.guidebookGridSize || "all") === "all" || size === dashboard.guidebookGridSize)
      && (!query || queryText.includes(query));
  });
  count.textContent = rows.length ? `${filtered.length} / ${rows.length} 条` : (dashboard.guidebookSourcesError || "本地估值目录不可用");
  if (sourceNote) {
    const countText = dashboard.guidebookSources?.counts?.uniqueSourceEntries;
    sourceNote.textContent = dashboard.guidebookSourcesError
      ? dashboard.guidebookSourcesError
      : `估值参考来自现有求解器基础目录。${countText ? `另关联 ${countText} 条 1.4 来源资料；新增条目只供浏览，不自动进入识别或求解。` : "1.4 来源资料正在加载。"}格子尺寸按来源目录原样显示，如 1×2 与 2×1 分别保留。`;
  }
  grid.innerHTML = filtered.length
    ? filtered.map((item, index) => {
      const rarityLabel = GUIDEBOOK_RARITY_LABELS[item.rarity] || "待确认";
      const source = (item.sourceRecords || [])[0];
      const subtitle = item.sourceOnly
        ? `来源资料 · ${source?.category || "分类待确认"} · ${item.footprint || "尺寸待确认"}`
        : source ? `${source.category} · ${source.sourceGeometry}` : `现有目录 · ${item.footprint || "尺寸未知"}`;
      const value = item.sourceOnly
        ? (source?.sourcePriceStatus === "VISUALLY_CONFIRMED_1_4_SOURCE" && source.sourcePrice != null ? `原图 ${formatCurrency(source.sourcePrice)} · 仅展示` : "来源字段待确认 · 仅展示")
        : (item.price == null ? "目录未提供参考价" : `目录参考 ${formatCurrency(item.price)}`);
      return `<button type="button" role="listitem" class="guidebook-item-card${item.key === dashboard.guidebookSelectedItem ? " is-selected" : ""}" data-guidebook-item-index="${index}" aria-pressed="${item.key === dashboard.guidebookSelectedItem}"><span class="rarity-tag${GUIDEBOOK_RARITY_LABELS[item.rarity] ? ` is-${item.rarity}` : ""}">${rarityLabel}</span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(subtitle)}</small><small>${escapeHtml(value)}</small></button>`;
    }).join("")
    : `<p class="guidebook-empty">${rows.length ? "没有符合筛选条件的藏品。" : escapeHtml(dashboard.guidebookSourcesError || "正在读取本地目录与 1.4 来源资料。")}</p>`;
  const selected = filtered.find(item => item.key === dashboard.guidebookSelectedItem) || filtered[0] || null;
  if (selected) dashboard.guidebookSelectedItem = selected.key;
  detail.innerHTML = guidebookCatalogDetailMarkup(selected);
  grid.querySelectorAll("[data-guidebook-item-index]").forEach(button => {
    button.addEventListener("click", () => {
      const item = filtered[Number(button.dataset.guidebookItemIndex)];
      if (!item) return;
      dashboard.guidebookSelectedItem = item.key;
      renderGuidebookCatalog();
    });
  });
}

function guidebookDrafts() {
  const rows = dashboard.lastMainViewState?.history?.liveTrialDrafts;
  if (!Array.isArray(rows)) return [];
  return rows.filter(record => record && String(record.lifecycleStatus || "").toUpperCase() === "DRAFT"
    && String(record.dataOrigin || "").toLowerCase() === "live-trial");
}

function guidebookRecognitionSlots(record) {
  return [
    ...(Array.isArray(record?.warehouse?.slots) ? record.warehouse.slots : []),
    ...(Array.isArray(record?.observedFacts?.warehouse?.slots) ? record.observedFacts.warehouse.slots : []),
    ...(Array.isArray(record?.warehouseSummary?.slots) ? record.warehouseSummary.slots : []),
    ...(Array.isArray(record?.auctionEvidence?.warehouse?.slots) ? record.auctionEvidence.warehouse.slots : []),
    ...(Array.isArray(record?.auctionEvidence?.warehouseEvidence?.slots) ? record.auctionEvidence.warehouseEvidence.slots : [])
  ];
}

function guidebookConfirmedItems(record) {
  const confirmed = [];
  for (const item of guidebookRecognitionSlots(record)) {
    const exactEvidence = ["EXACT_IDENTIFIED", "UNIQUE_IN_CATALOG"].includes(String(item?.evidenceLevel || ""));
    const identityConfirmed = item?.status === "CONFIRMED" || item?.confirmed === true || exactEvidence;
    const catalogId = item?.catalogId || item?.selectedCandidate?.catalogId;
    const identifiedName = item?.identifiedName || item?.name || item?.selectedCandidateName;
    if (identityConfirmed && catalogId && identifiedName) confirmed.push({
      catalogId: String(catalogId), identifiedName: String(identifiedName), rarity: item.rarity
    });
  }
  const reviewRows = [
    ...(Array.isArray(record?.identityEvidence) ? record.identityEvidence : []),
    ...(Array.isArray(record?.settlement?.identityEvidence) ? record.settlement.identityEvidence : [])
  ];
  for (const item of reviewRows) {
    const identityConfirmed = item?.status === "CONFIRMED" || item?.identityStatus === "EXACT_IDENTIFIED";
    const identifiedName = item?.identifiedName || item?.name || item?.selectedCandidateName;
    if (identityConfirmed && item?.catalogId && identifiedName) confirmed.push({
      catalogId: String(item.catalogId), identifiedName: String(identifiedName), rarity: item.rarity
    });
  }
  return confirmed.filter((item, index, rows) => rows.findIndex(other =>
    other.catalogId === item.catalogId && other.identifiedName === item.identifiedName
  ) === index);
}

function guidebookUnresolvedItemNotes(record) {
  return guidebookRecognitionSlots(record).map(item => {
    if (!item || item.confirmed === true || item.status === "CONFIRMED"
      || ["EXACT_IDENTIFIED", "UNIQUE_IN_CATALOG"].includes(String(item.evidenceLevel || ""))) return "";
    const candidates = Array.isArray(item.candidates) ? item.candidates : [];
    const candidateNames = candidates.map(candidate => candidate?.name || candidate?.catalogId).filter(Boolean).slice(0, 4);
    if (candidateNames.length) return `候选身份（待确认）：${candidateNames.join(" / ")}`;
    if (item.w != null || item.h != null) return `几何信息已记录：${item.w ?? "?"} × ${item.h ?? "?"}；身份未知`;
    if (item.rarity && item.rarity !== "unknown") return `已知品质：${item.rarity}；藏品身份待确认`;
    return "藏品身份未知，待确认";
  }).filter((note, index, rows) => note && rows.indexOf(note) === index);
}

function guidebookInstanceReviewMarkup(record) {
  const native = record?.auctionEvidence?.nativeObservation || {};
  const slots = [
    record?.warehouse?.slots,
    record?.observedFacts?.warehouse?.slots,
    record?.warehouseSummary?.slots,
    record?.auctionEvidence?.warehouse?.slots,
    record?.auctionEvidence?.warehouseEvidence?.slots
  ].find(rows => Array.isArray(rows) && rows.length) || [];
  const confirmedCount = slots.filter(item => item?.manualDecision?.action === "CONFIRM_CANDIDATE"
    || item?.status === "CONFIRMED" || ["CONFIRMED", "EXACT", "MANUAL_CONFIRMED"].includes(String(item?.identityStatus || ""))
    || ["EXACT_IDENTIFIED", "UNIQUE_IN_CATALOG"].includes(String(item?.evidenceLevel || ""))).length;
  const slotsMarkup = slots.length
    ? `<p class="guidebook-identity-note">物理实例：${slots.length} 件 · ${confirmedCount} 件已确认 · ${slots.length - confirmedCount} 件待确认</p>`
    : `<p class="guidebook-identity-note">物理实例数量：本草稿未记录槽位。</p>`;
  const decisions = Array.isArray(native.warehouseInstanceDecisions) ? native.warehouseInstanceDecisions : [];
  const crops = Array.isArray(native.warehouseSlotSources) ? native.warehouseSlotSources : [];
  const actionLabels = {
    CONFIRM_CANDIDATE: "确认候选",
    REJECT_CANDIDATE: "拒绝候选",
    RESTORE_AUTOMATIC: "恢复自动处理"
  };
  const decisionsMarkup = decisions.map(decision => {
    const action = actionLabels[decision?.action] || "未知实例决定";
    const anchor = decision?.instanceAnchor || {};
    const position = anchor.row != null && anchor.col != null
      && Number.isFinite(Number(anchor.row)) && Number.isFinite(Number(anchor.col))
      ? `第 ${Number(anchor.row) + 1} 行 · 第 ${Number(anchor.col) + 1} 列`
      : "物理位置未记录";
    const crop = crops.find(item => item?.evidenceId === decision?.activityEvidenceId);
    const frame = crop?.frameSequence == null ? "活动帧序号未记录" : `活动帧 ${crop.frameSequence}`;
    const cropNote = decision?.activityEvidenceId
      ? (crop ? `裁图已关联 · ${frame} · ${decision.activityEvidenceId}` : `裁图引用未找到 · ${decision.activityEvidenceId}`)
      : "未记录活动裁图引用";
    const source = decision?.source === "HUMAN_INSTANCE_REVIEW" ? "人工实例复核"
      : decision?.source ? String(decision.source) : "决定来源未记录";
    const candidate = decision?.catalogId ? ` · 目录 ID ${escapeHtml(decision.catalogId)}` : "";
    const session = decision?.sessionId ? ` · 会话 ${decision.sessionId}` : "";
    return `<div class="guidebook-observation"><strong>每个实例最近保存的决定：${action}${candidate}</strong><p>${escapeHtml(source)} · ${escapeHtml(position)}${escapeHtml(session)}</p><small class="guidebook-frame-provenance">${escapeHtml(cropNote)}</small></div>`;
  }).join("");
  const auditMarkup = decisionsMarkup
    ? `<div class="guidebook-instance-decisions"><strong>实例决定记录</strong>${decisionsMarkup}</div>`
    : `<p class="guidebook-identity-note">没有保存实例级人工决定记录。</p>`;
  return `${slotsMarkup}${auditMarkup}`;
}

function guidebookObservationValue(field, value) {
  if (field === "goldAvg" || field === "purpleAvg") return formatCurrency(value);
  return String(value);
}

function guidebookObservationSourceFrame(item, record) {
  const frames = record?.auctionEvidence?.nativeObservation?.sourceFrames;
  if (!Array.isArray(frames)) return null;
  const native = record?.auctionEvidence?.nativeObservation || {};
  const wantedSequence = item?.frameSequence ?? item?.sourceFrameSequence;
  const wantedSession = item?.observationSessionId || item?.sourceObservationSessionId || item?.sessionId
    || native.observationSessionId;
  if (wantedSequence != null) {
    return frames.find(frame => Number(frame?.frameSequence) === Number(wantedSequence)
      && (!wantedSession || !frame?.observationSessionId || frame.observationSessionId === wantedSession)) || null;
  }
  if (item?.frameId != null) {
    const wantedFrameId = String(item.frameId);
    return frames.find(frame => String(frame?.capturedAt || "") === wantedFrameId
      && (!wantedSession || !frame?.observationSessionId || frame.observationSessionId === wantedSession)) || null;
  }
  return null;
}

function guidebookObservationSourceLabel(item, record) {
  const exact = guidebookObservationSourceFrame(item, record);
  if (exact) {
    const sequence = exact.frameSequence == null ? "序号未记录" : `第 ${exact.frameSequence} 帧`;
    return `首次来源原图已保存：${sequence} · ${exact.capturedAt || "时间未记录"}`;
  }
  if (item?.frameSequence != null || item?.sourceFrameSequence != null || item?.frameId != null) {
    return "事实标记的原始来源帧未保存在本草稿；下方图片仅供回看，不代替首次来源。";
  }
  return "未记录可验证的首次来源帧；下方只列本局已保存关键帧。";
}

function renderGuidebookRecords() {
  const list = document.getElementById("guidebook-recognition-list");
  const count = document.getElementById("guidebook-record-count");
  const empty = document.getElementById("guidebook-records-empty");
  if (!list || !count || !empty) return;
  const records = guidebookDrafts();
  const signature = records.map(record => {
    const observations = record.intelCardEvidence?.observations || [];
    const frames = record.auctionEvidence?.nativeObservation?.sourceFrames || [];
    return `${record.id}:${record.updatedAt || ""}:${record.factsRevision ?? ""}:${observations.length}:${frames.length}`;
  }).join("|");
  if (signature === dashboard.guidebookRecordsSignature && list.dataset.rendered === "true") return;
  dashboard.guidebookRecordsSignature = signature;
  list.dataset.rendered = "true";
  count.textContent = `${records.length} 条隔离草稿`;
  empty.hidden = records.length > 0;
  list.innerHTML = records.map((record, index) => {
    const facts = record.intelCardEvidence || {};
    const observations = Array.isArray(facts.observations) ? facts.observations : [];
    const usable = observations.filter(item => item && item.value != null).slice(0, 10);
    const storedFields = ["q", "goldAvg", "purpleCount", "purpleAvg", "goldCount", "redCount", "totalItems", "totalGrid"];
    const observedFields = new Set(usable.map(item => item.field));
    for (const field of storedFields) {
      const value = record[field] ?? (field === "purpleCount" ? record.purple : null);
      if (value != null && !observedFields.has(field)) usable.push({ field, value, status: "STORED_FACT" });
    }
    const frames = record.auctionEvidence?.nativeObservation?.sourceFrames || [];
    const environment = record.environment || {};
    const title = [environment.venueName || environment.venue || record.venue, environment.box || record.box].filter(Boolean).join(" · ") || "会场/宝箱未记录";
    const knownNames = GUIDEBOOK_RARITIES.map(rarity => ({ rarity, value: record[`known${rarity[0].toUpperCase()}${rarity.slice(1)}`] }))
      .filter(item => item.value != null && String(item.value).trim());
    const confirmedItems = guidebookConfirmedItems(record);
    const unresolvedItemNotes = guidebookUnresolvedItemNotes(record);
    const observationMarkup = usable.length ? usable.map(item => {
      const label = GUIDEBOOK_FACT_LABELS[item.field] || item.field || "局内事实";
      const state = item.status === "OBSERVED" ? "原图观察" : item.status === "CONFIRMED" ? "已确认" : item.status === "STORED_FACT" ? "草稿事实" : "待核对";
      return `<div class="guidebook-observation"><strong>${escapeHtml(label)} · ${escapeHtml(state)}${item.round != null ? ` · 第 ${escapeHtml(item.round)} 回合` : ""}</strong><p>${escapeHtml(guidebookObservationValue(item.field, item.value))}${item.rawText ? `　｜　${escapeHtml(item.rawText)}` : ""}</p><small class="guidebook-frame-provenance">${escapeHtml(guidebookObservationSourceLabel(item, record))}</small></div>`;
    }).join("") : `<p class="guidebook-identity-note">本草稿没有单件身份事实；不会从品质、轮廓或置信度推定藏品名称。</p>`;
    const identityMarkup = confirmedItems.length
      ? confirmedItems.map(item => {
        const catalogMatches = guidebookCatalogRows().filter(row => !row.sourceOnly && row.name === item.identifiedName
          && (!item.rarity || row.rarity === item.rarity));
        const catalogMatch = catalogMatches.length === 1 ? catalogMatches[0] : null;
        return `<span class="guidebook-item-confirmed">已确认：${escapeHtml(item.identifiedName)}${catalogMatch ? ` <button type="button" class="btn-review-action" data-guidebook-confirmed-item="${escapeHtml(catalogMatch.key)}">查看图鉴条目</button>` : "（当前估值目录无同名条目）"}</span>`;
      }).join(" ")
      : `<span class="guidebook-identity-note">未保存可关联到正式目录的身份确认项。</span>`;
    const unresolvedMarkup = unresolvedItemNotes.map(note => `<p class="guidebook-identity-note">${escapeHtml(note)}</p>`).join("");
    const instanceReviewMarkup = guidebookInstanceReviewMarkup(record);
    const namesMarkup = knownNames.length
      ? `<p class="guidebook-identity-note">局内名称字段（未附图鉴身份确认）：${knownNames.map(item => `${GUIDEBOOK_RARITY_LABELS[item.rarity]}色 ${escapeHtml(item.value)}`).join("；")}</p>`
      : "";
    return `<article class="guidebook-record-card"><div class="guidebook-record-top"><div><h3>${escapeHtml(title)}</h3><p class="guidebook-record-meta">${escapeHtml(record.playedAt || record.updatedAt || "时间未记录")} · ${escapeHtml(record.id || "未知局")}</p></div><span class="tag">live-trial DRAFT</span></div><div class="guidebook-observation-list">${observationMarkup}</div><div class="guidebook-identity-note">藏品身份：${identityMarkup}</div>${unresolvedMarkup}${instanceReviewMarkup}${namesMarkup}<p class="guidebook-record-meta">保存原图：${frames.length} 张 · 隔离草稿，不进入正式 History</p><button type="button" class="btn-review-action" data-guidebook-original="${index}" data-record-id="${escapeHtml(record.id || "")}">查看本局保存原图</button><div class="guidebook-evidence" id="guidebook-source-${index}" data-record-id="" data-source="live-trial"></div></article>`;
  }).join("");
  list.querySelectorAll("[data-guidebook-original]").forEach(button => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.guidebookOriginal);
      const record = records[index];
      const containerId = `guidebook-source-${index}`;
      if (record?.id) requestOriginalScreenshots(record.id, containerId, "live-trial");
    });
  });
  list.querySelectorAll("[data-guidebook-confirmed-item]").forEach(button => {
    button.addEventListener("click", () => {
      dashboard.guidebookRarity = "all";
      dashboard.guidebookSearch = "";
      dashboard.guidebookSelectedItem = button.dataset.guidebookConfirmedItem;
      setGuidebookTab("catalog");
      renderGuidebook();
    });
  });
}

function renderGuidebookCharacters() {
  const list = document.getElementById("guidebook-character-list");
  const count = document.getElementById("guidebook-character-count");
  const empty = document.getElementById("guidebook-characters-empty");
  if (!list || !count || !empty) return;
  const roles = dashboard.guidebookSources?.roles || [];
  count.textContent = `${roles.length} 名`;
  empty.hidden = roles.length > 0;
  if (!roles.length) {
    empty.textContent = dashboard.guidebookSourcesError || (dashboard.guidebookSourcesRequestId ? "正在读取角色原图与技能资料…" : "角色资料尚未加载。");
    list.innerHTML = "";
    return;
  }
  list.innerHTML = roles.map(role => {
    const revelations = Array.isArray(role.revelations) && role.revelations.length
      ? `<ul class="guidebook-character-revelations">${role.revelations.map(text => `<li>${escapeHtml(text)}</li>`).join("")}</ul>` : "";
    const image = role.sourceImage?.uri
      ? `<details class="guidebook-role-source"><summary>查看角色来源原图</summary><img src="${escapeHtml(role.sourceImage.uri)}" alt="${escapeHtml(role.name)}技能来源原图" loading="lazy"><small>${escapeHtml(role.sourceImage.path || "")}</small></details>`
      : `<p class="guidebook-source-missing">角色来源原图暂不可读取。</p>`;
    return `<article class="guidebook-character-card"><div class="guidebook-character-heading"><h3>${escapeHtml(role.name)}</h3>${role.newInThisBatch ? `<span class="tag">本批素材新增</span>` : ""}</div>${role.flavor ? `<p class="guidebook-character-flavor">${escapeHtml(role.flavor)}</p>` : ""}<strong>${escapeHtml(role.skillName || "技能资料待确认")}</strong><p>${escapeHtml(role.skillDescription || "技能说明待确认")}</p>${revelations}${role.integrationNote ? `<p class="guidebook-identity-note">${escapeHtml(role.integrationNote)}</p>` : ""}${image}</article>`;
  }).join("");
}

function setGuidebookTab(tab) {
  dashboard.guidebookTab = ["records", "characters"].includes(tab) ? tab : "catalog";
  document.querySelectorAll("[data-guidebook-tab]").forEach(button => {
    const active = button.dataset.guidebookTab === dashboard.guidebookTab;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  const catalogPanel = document.getElementById("guidebook-catalog-panel");
  const recordsPanel = document.getElementById("guidebook-records-panel");
  const charactersPanel = document.getElementById("guidebook-characters-panel");
  if (catalogPanel) catalogPanel.hidden = dashboard.guidebookTab !== "catalog";
  if (recordsPanel) recordsPanel.hidden = dashboard.guidebookTab !== "records";
  if (charactersPanel) charactersPanel.hidden = dashboard.guidebookTab !== "characters";
}

function renderGuidebook() {
  if (dashboard.currentView !== "guidebook") return;
  requestGuidebookSources();
  setGuidebookTab(dashboard.guidebookTab);
  renderGuidebookCatalog();
  renderGuidebookCharacters();
  renderGuidebookRecords();
}

function renderSolverAdmissionStatus(currentMatch) {
  const card = document.getElementById("match-admission-card");
  if (!card) return;
  const gate = currentMatch.solverAdmission || {};
  const requirements = Array.isArray(gate.requirements) ? gate.requirements : [];
  const blockers = Array.isArray(gate.blockingReasons) ? gate.blockingReasons : [];
  const status = String(currentMatch.solverStatus || currentMatch.prediction?.solverStatus || "").toLowerCase();
  const native = currentMatch.observationProfile === "native-readonly-v1";
  const paused = currentMatch.lifecycleStatus === "FINALIZED" || currentMatch.nativeInvalidated === true || status === "paused";
  let title = "等待当前局信息";
  let state = "等待中";
  let summary = "只使用已进入本局的事实；缺项不会以历史值或默认值补齐。";
  if (paused) {
    title = currentMatch.lifecycleStatus === "FINALIZED" ? "本局已结算" : "实时竞拍建议已暂停";
    state = "未发布建议";
    summary = currentMatch.solverMissingReason || "恢复观察后，收到新的有效局内帧才会重新评估；旧结果不会自动恢复。";
  } else if (blockers.length || gate.eligible === false) {
    title = "当前局尚不满足建议条件";
    state = "缺少必要条件";
    summary = currentMatch.solverMissingReason || "补齐下方所列事实后，系统才会重新判断；已识别情报不会替代缺项。";
  } else if (status === "pending" || status === "refreshing" || currentMatch.shadowUpdating === true) {
    title = "本局信息已提交，正在计算";
    state = "计算中";
    summary = "当前计算完成前不沿用旧建议。";
  } else if (status === "stale" || status === "expired") {
    title = "当前建议结果已过期";
    state = "结果已过期";
    summary = currentMatch.solverMissingReason || "事实或版本已经变化；旧结果不会作为本局建议，请等待新鲜局内帧和重新计算。";
  } else if (status === "fallback") {
    title = "当前只有降级计算结果";
    state = "降级结果不可用作建议";
    summary = currentMatch.solverMissingReason || "降级或近似结果不作为实时竞拍建议发布；等待完整计算。";
  } else if (status === "valid" && currentMatch.prediction?.recommendedMax != null
      && (!native || gate.eligible === true)) {
    title = "当前局建议可用";
    state = "本局有效结果";
    summary = "金额对应当前局事实与版本；回合变化后会重新评估。";
  } else if (status === "no-match") {
    title = "当前事实约束冲突";
    state = "暂不建议";
    summary = currentMatch.solverMissingReason || currentMatch.prediction?.actionReason || "请核对已显示的当前局事实。";
  } else if (["error", "failed", "timeout"].includes(status)) {
    title = "本局计算未完成";
    state = status === "timeout" ? "计算超时" : "计算失败";
    summary = currentMatch.solverMissingReason || (status === "timeout"
      ? "本次计算超时，没有可发布的当前局结果；请等待后续有效帧重算。"
      : "没有可发布的当前局结果；请等下一帧重算。");
  } else if (gate.eligible === true && status !== "valid") {
    title = "必要事实已齐，暂无可发布结果";
    state = status === "incomplete" ? "等待当前结果" : "未发布建议";
    summary = currentMatch.solverMissingReason || "需要本局有效观察与合格计算结果后才显示建议。";
  }

  document.getElementById("match-admission-title").textContent = title;
  document.getElementById("match-admission-state").textContent = state;
  document.getElementById("match-admission-summary").textContent = summary;
  const calcStatus = document.getElementById("match-live-calc-status");
  if (calcStatus) calcStatus.textContent = state;
  const known = requirements.filter(item => item.status === "available");
  document.getElementById("match-admission-known").innerHTML = known.length
    ? known.map(item => {
      const value = item.value == null ? "" : (item.key === "goldAvg" || item.key === "entryCost" ? formatCurrency(item.value) : String(item.value));
      return `<span class="match-admission-chip">${escapeHtml(item.label)}${value ? `：${escapeHtml(value)}` : ""}</span>`;
    }).join("")
    : `<span class="match-admission-chip">暂无已接收的必要事实</span>`;
  const invalid = requirements.filter(item => item.status === "invalid").map(item => `${item.label}无效`);
  const missing = [...blockers, ...invalid].filter((item, index, rows) => rows.indexOf(item) === index);
  document.getElementById("match-admission-blockers").innerHTML = missing.length
    ? missing.map(item => `<span class="match-admission-chip is-blocking">${escapeHtml(item)}</span>`).join("")
    : `<span class="match-admission-chip">无事实门禁缺项</span>`;
  const actionContainer = document.getElementById("match-admission-actions");
  const actionLabels = {
    venueId: ["手动选择/核对会场与费用", "match-venue-trigger"],
    entryCost: ["手动核对会场与费用", "match-venue-trigger"],
    fieldCondition: ["手动选择/核对规则", "match-cond-trigger"],
    boxId: ["手动选择/核对宝箱", "match-box-trigger"],
    q: ["等待观察或核对 Q 情报", "match-input-q"],
    goldAvg: ["等待观察或核对金色均价", "match-input-gold-avg"]
  };
  const actionKeys = Array.isArray(gate.actionKeys) ? gate.actionKeys : [];
  const canSendManual = !paused && (!native || currentMatch.nativeInvalidated !== true);
  const actions = canSendManual ? actionKeys.filter(key => actionLabels[key]) : [];
  if (actionContainer) {
    actionContainer.hidden = actions.length === 0;
    actionContainer.innerHTML = actions.map(key => `<button type="button" data-admission-jump="${escapeHtml(actionLabels[key][1])}">${escapeHtml(actionLabels[key][0])}</button>`).join("");
  }
  const purpleCount = currentMatch.facts?.purpleCount ?? currentMatch.qualities?.purple?.count;
  document.getElementById("match-admission-auxiliary").textContent = purpleCount == null
    ? ""
    : `已接收紫色数量 ${purpleCount}，作为当前情报约束；它本身不替代会场、入场费或规则条件。`;
}

function focusAdmissionControl(id) {
  const target = document.getElementById(id);
  if (!target) return;
  const details = target.closest("details");
  if (details) details.open = true;
  target.scrollIntoView?.({ behavior: "smooth", block: "center" });
  if (target.matches("button")) target.click();
  else target.focus?.();
}

function showView(viewName) {
  if (viewName !== "history" && dashboard.historicalWarehouseReview) resetHistoricalWarehouseReview();
  const page = document.querySelector(`[data-view-page="${viewName}"]`);
  const nav = document.querySelector(`[data-view-target="${viewName}"]`);
  if (!page || !nav) return;
  document.querySelectorAll("[data-view-page]").forEach((candidate) => {
    const active = candidate === page;
    candidate.hidden = !active;
    candidate.classList.toggle("is-active", active);
  });
  document.querySelectorAll("[data-view-target]").forEach((candidate) => {
    const active = candidate === nav;
    candidate.classList.toggle("is-active", active);
    if (active) candidate.setAttribute("aria-current", "page");
    else candidate.removeAttribute("aria-current");
  });
  dashboard.currentView = viewName;
  dashboard.wirSaveConfirmOpen = false;
  const saveConfirm = document.getElementById("wir-save-confirm");
  if (saveConfirm) saveConfirm.hidden = true;
  const captureConfirm = document.getElementById("warehouse-capture-confirm");
  if (captureConfirm) captureConfirm.hidden = true;
  if (viewName === "match" && dashboard.lastCurrentMatch) {
    renderMatch(dashboard.lastCurrentMatch, dashboard.overlayVisible);
  } else if (viewName === "guidebook") {
    renderGuidebook();
  } else if (viewName === "history" && dashboard.lastMainViewState) {
    renderHistory(dashboard.lastMainViewState);
  } else if (viewName === "analysis" && dashboard.lastMainViewState) {
    renderAnalysis(dashboard.lastMainViewState);
  }
}

function isBridgeReady() {
  return Boolean(window.chrome && window.chrome.webview);
}

function postNative(action, payload = {}) {
  if (!isBridgeReady()) return;
  dashboard.requestSequence += 1;
  if (action === "warehouse_identity_review") dashboard.latestWarehouseRequestId = `main-${dashboard.requestSequence}`;
  const commandPayload = { ...payload };
  if (action === "manual_facts" && dashboard.matchState.observationProfile === "native-readonly-v1") {
    commandPayload.expectedMatchId ??= dashboard.matchState.matchId;
    commandPayload.expectedFactsRevision ??= dashboard.matchState.observationFactsRevision;
    commandPayload.expectedObservationSessionId ??= dashboard.matchState.observationSessionId;
    commandPayload.expectedRound ??= dashboard.lastCurrentMatch?.observationRound ?? null;
    commandPayload.expectedTargetInstance ??= dashboard.lastCurrentMatch?.observationTarget ?? null;
  }
  window.chrome.webview.postMessage(JSON.stringify({
    action,
    ...commandPayload,
    requestId: `main-${dashboard.requestSequence}`
  }));
  return "main-" + dashboard.requestSequence;
}

function openDeleteRecordModal() {
  const record = dashboard.selectedRecord;
  if (!record) return;

  dashboard.pendingDeleteSelection = null;

  const modal = document.getElementById("delete-record-modal");
  const timeEl = document.getElementById("delete-modal-time");
  const infoEl = document.getElementById("delete-modal-info");
  const lifeEl = document.getElementById("delete-modal-lifecycle");
  const errorEl = document.getElementById("delete-modal-error");

  const isLegacy = record.kind === "legacy";
  const timeStr = record.localPlayedAt || record.playedAt || "未知时间";
  const env = record.environment || {};
  const venue = env.venueName || env.venue || record.venue || "未指定会场";
  const box = env.box || record.box || "";
  const lifecycle = isLegacy ? "LEGACY" : (record.lifecycle || record.lifecycleStatus || "DRAFT");
  const lifecycleText = isLegacy ? "历史归档" : (lifecycle === "FINALIZED" ? "已完成" : (lifecycle === "CANCELLED" ? "已放弃" : "草稿"));

  if (timeEl) timeEl.textContent = timeStr;
  if (infoEl) infoEl.textContent = `${venue}${box ? ` · ${box}` : ""}`;
  if (lifeEl) {
    lifeEl.textContent = lifecycleText;
    lifeEl.className = `badge ${isLegacy ? "badge-legacy" : (lifecycle === "FINALIZED" ? "badge-finalized" : (lifecycle === "CANCELLED" ? "badge-cancelled" : "badge-draft"))}`;
  }
  if (errorEl) {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  if (modal) modal.hidden = false;
}

function openBatchDeleteRecordModal() {
  const selections = Array.from(dashboard.selectedHistoryRecords.values());
  if (!selections.length) return;
  dashboard.pendingDeleteSelection = selections;
  const modal = document.getElementById("delete-record-modal");
  const titleEl = document.getElementById("delete-modal-title");
  const warningEl = modal ? modal.querySelector(".modal-warning-text") : null;
  const errorEl = document.getElementById("delete-modal-error");
  if (titleEl) titleEl.textContent = `确定删除选中的 ${selections.length} 条记录吗？`;
  if (warningEl) warningEl.textContent = "此操作将从本机历史记录中移除所选对局及其关联记录。";
  if (errorEl) {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }
  if (modal) modal.hidden = false;
}

function closeDeleteRecordModal() {
  const modal = document.getElementById("delete-record-modal");
  if (modal) modal.hidden = true;
  const errorEl = document.getElementById("delete-modal-error");
  if (errorEl) {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }
  dashboard.pendingDeleteSelection = null;
  const titleEl = document.getElementById("delete-modal-title");
  const warningEl = modal ? modal.querySelector(".modal-warning-text") : null;
  if (titleEl) titleEl.textContent = "确定删除这条记录吗？";
  if (warningEl) warningEl.textContent = "此操作将从本机历史记录中移除该条记录。";
}

function confirmDeleteRecord() {
  if (Array.isArray(dashboard.pendingDeleteSelection) && dashboard.pendingDeleteSelection.length) {
    const selections = dashboard.pendingDeleteSelection.slice();
    postNative("delete_history_records", { selections });
    return;
  }
  const record = dashboard.selectedRecord;
  if (!record) return;
  const errorEl = document.getElementById("delete-modal-error");
  if (errorEl) {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }
  const recordId = record.key || record.id;
  postNative("delete_history_record", { recordId, source: record.recordSource || record.kind || "current" });
}

function populateMatchOptions(options) {
  if (!options) return;
  if (options.venues && options.venues.length) {
    dashboard.matchOptions.venues = options.venues;
    for (const menuId of ["match-venue-menu", "next-match-venue-menu"]) {
      const venueMenu = document.getElementById(menuId);
      if (venueMenu && (!venueMenu.children.length || venueMenu.dataset.version !== String(options.venues.length))) {
        venueMenu.dataset.version = String(options.venues.length);
        venueMenu.innerHTML = options.venues.map(v =>
          `<div class="dropdown-item" data-venue-id="${escapeHtml(v.venueId)}" data-venue-name="${escapeHtml(v.displayName)}">${escapeHtml(v.displayName)}</div>`
        ).join("");
      }
    }
  }
  if (options.fieldConditions && options.fieldConditions.length) {
    dashboard.matchOptions.fieldConditions = options.fieldConditions;
    for (const menuId of ["match-cond-menu", "next-match-cond-menu"]) {
      const condMenu = document.getElementById(menuId);
      if (condMenu && (!condMenu.children.length || condMenu.dataset.version !== String(options.fieldConditions.length))) {
        condMenu.dataset.version = String(options.fieldConditions.length);
        condMenu.innerHTML = options.fieldConditions.map(c =>
          `<div class="dropdown-item" data-cond-id="${escapeHtml(c.id)}" data-cond-name="${escapeHtml(c.name)}">${escapeHtml(c.name)}</div>`
        ).join("");
      }
    }
  }
}

function updateNextMatchPreparationBoxDropdown(venueId) {
  const menu = document.getElementById("next-match-box-menu");
  const display = document.getElementById("next-match-box-display");
  if (!menu) return;
  const venue = (dashboard.matchOptions.venues || []).find(item => item.venueId === venueId);
  const boxes = venue?.boxes || [];
  menu.innerHTML = boxes.map(box =>
    `<div class="dropdown-item" data-box-id="${escapeHtml(box.boxId)}" data-box-name="${escapeHtml(box.displayName)}">${escapeHtml(box.displayName)}</div>`
  ).join("");
  if (!boxes.length) {
    menu.innerHTML = `<div class="dropdown-item" style="color:#64748b;cursor:default">请先选择会场</div>`;
    if (display) display.textContent = "请选择宝箱";
  }
}

function setNextMatchPreparationVenue(venueId, venueName) {
  dashboard.nextMatchPreparationDraft = dashboard.nextMatchPreparationDraft || {};
  Object.assign(dashboard.nextMatchPreparationDraft, {
    venueId, venue: venueName, boxId: null, box: null,
  });
  dashboard.nextMatchPreparationDirty = true;
  document.getElementById("next-match-venue-display").textContent = venueName || "请选择会场";
  document.getElementById("next-match-box-display").textContent = "请选择宝箱";
  updateNextMatchPreparationBoxDropdown(venueId);
  renderNextMatchPreparation(dashboard.lastCurrentMatch);
}

function setNextMatchPreparationBox(boxId, boxName) {
  dashboard.nextMatchPreparationDraft = dashboard.nextMatchPreparationDraft || {};
  Object.assign(dashboard.nextMatchPreparationDraft, { boxId, box: boxName });
  dashboard.nextMatchPreparationDirty = true;
  document.getElementById("next-match-box-display").textContent = boxName || "请选择宝箱";
  renderNextMatchPreparation(dashboard.lastCurrentMatch);
}

function setNextMatchPreparationCondition(conditionId, conditionName) {
  dashboard.nextMatchPreparationDraft = dashboard.nextMatchPreparationDraft || {};
  Object.assign(dashboard.nextMatchPreparationDraft, {
    fieldCondition: conditionId, fieldConditionName: conditionName,
  });
  dashboard.nextMatchPreparationDirty = true;
  document.getElementById("next-match-cond-display").textContent = conditionName || "请选择规则";
  renderNextMatchPreparation(dashboard.lastCurrentMatch);
}

function submitNextMatchPreparation(operation) {
  const settings = dashboard.nextMatchPreparationDraft || {};
  if (operation === "SAVE" && (!settings.venueId || !settings.boxId || !settings.fieldCondition)) {
    const status = document.getElementById("next-match-preparation-status");
    if (status) status.textContent = "请明确选择会场、宝箱和规则后再保存；未知项不能自动补默认值。";
    return;
  }
  const requestId = postNative("next_match_preparation", {
    operation,
    settings,
    preparationRevision: dashboard.nextMatchPreparation?.revision || null,
  });
  if (requestId) {
    dashboard.nextMatchPreparationRequestId = requestId;
    const status = document.getElementById("next-match-preparation-status");
    if (status) status.textContent = operation === "SAVE" ? "正在保存下一局准备设置…" : "正在处理下一局设置…";
  } else {
    const status = document.getElementById("next-match-preparation-status");
    if (status) status.textContent = "界面连接尚未就绪；设置未保存。";
  }
}

function renderNextMatchPreparation(currentMatch = dashboard.lastCurrentMatch) {
  const panel = document.getElementById("next-match-preparation");
  if (!panel) return;
  const native = currentMatch?.observationProfile === "native-readonly-v1";
  panel.hidden = !native;
  if (!native) return;

  const state = currentMatch.nextMatchPreparation || dashboard.nextMatchPreparation || { status: "NONE" };
  dashboard.nextMatchPreparation = state;
  const version = `${state.revision || ""}:${state.status || "NONE"}`;
  if (dashboard.nextMatchPreparationDraft === null ||
      (dashboard.nextMatchPreparationVersion !== version && !dashboard.nextMatchPreparationDirty)) {
    dashboard.nextMatchPreparationDraft = state.settings ? { ...state.settings } : {};
    dashboard.nextMatchPreparationDirty = false;
  }
  dashboard.nextMatchPreparationVersion = version;
  const draft = dashboard.nextMatchPreparationDraft || {};
  const venue = (dashboard.matchOptions.venues || []).find(item => item.venueId === draft.venueId);
  const box = venue?.boxes?.find(item => item.boxId === draft.boxId);
  const condition = (dashboard.matchOptions.fieldConditions || []).find(item => item.id === draft.fieldCondition);
  document.getElementById("next-match-venue-display").textContent = draft.venue || venue?.displayName || "请选择会场";
  updateNextMatchPreparationBoxDropdown(draft.venueId);
  if (draft.box) document.getElementById("next-match-box-display").textContent = draft.box;
  else if (box) document.getElementById("next-match-box-display").textContent = box.displayName;
  document.getElementById("next-match-cond-display").textContent = draft.fieldConditionName || condition?.name || "请选择规则";

  const cost = state.settings?.entryCost ?? (venue?.entryCost ?? null);
  const source = document.getElementById("next-match-preparation-cost-source");
  if (source) {
    source.textContent = cost === null || cost === undefined
      ? "入场费未知；选择有依据的会场后由目录提供，不会自动补零。"
      : `入场费 ${formatCurrency(Number(cost))} · 来源：批准目录 ${state.settings?.catalogVersion || currentMatch.options?.catalogVersion || "当前目录"}（${state.settings?.venueEvidenceClass || venue?.venueEvidenceClass || "来源待核"}）`;
  }

  const status = document.getElementById("next-match-preparation-status");
  const save = document.getElementById("next-match-preparation-save");
  const cancel = document.getElementById("next-match-preparation-cancel");
  const apply = document.getElementById("next-match-preparation-apply");
  const observed = document.getElementById("next-match-preparation-observed");
  const retry = document.getElementById("next-match-preparation-retry");
  const prepStatus = String(state.status || "NONE").toUpperCase();
  const changed = dashboard.nextMatchPreparationDirty;
  const factsReady = Boolean(draft.venueId && draft.boxId && draft.fieldCondition);
  const health = currentMatch.visionHealth || {};
  const observerStarted = Boolean(currentMatch.observationSessionId)
    || ["native-starting", "native-ready", "native-refreshing"].includes(health.stage);
  const baseState = observerStarted ? "等待下一局新鲜竞拍帧" : "观察尚未启动";
  if (status) {
    if (prepStatus === "APPLYING") status.textContent = `设置正在由 worker 应用于本局 ${state.matchId || state.boundMatchId || "…"}，等待回执；建议资格暂未恢复。`;
    else if (prepStatus === "CONFLICT") status.textContent = `本局 worker 观察与准备值冲突：${(state.conflicts || []).map(item => `${item.label}（观察：${item.observedLabel}；准备：${item.preparedLabel}）`).join("；")}。请选择如何处理。`;
    else if (prepStatus === "FAILED") status.textContent = state.retryable === true
      ? `应用失败：${state.reasonLabel || state.reason || "worker 未接受"}。设置仍绑定原局，重试只会针对本局。`
      : `结果未确认：${state.reasonLabel || state.reason || "观察范围已变化"}。不会自动重发；等待本局新鲜事实核实，或取消准备。`;
    else if (prepStatus === "APPLIED") status.textContent = `worker 已确认应用于本局 ${state.matchId || ""}。这次设置不会自动沿用到下一局。`;
    else if (prepStatus === "CANCELLED") status.textContent = state.reasonLabel || "下一局准备已取消；当前局事实未改。";
    else if (changed && factsReady) status.textContent = "所选设置尚未保存；已保存的准备方案保持不变，当前局事实未改。";
    else if (prepStatus === "PREPARED") status.textContent = `下一局设置已保存 · ${draft.venue || venue?.displayName || "会场待选"} · ${draft.box || box?.displayName || "宝箱待选"} · ${draft.fieldConditionName || condition?.name || "规则待选"}。${baseState}；当前局事实未改。`;
    else status.textContent = "尚未保存下一局设置；留空表示未知，不会自动填入默认规则或费用。";
  }
  const busy = prepStatus === "APPLYING" || prepStatus === "CONFLICT";
  const unresolved = ["APPLYING", "CONFLICT", "FAILED"].includes(prepStatus);
  for (const id of ["next-match-venue-trigger", "next-match-box-trigger", "next-match-cond-trigger"]) {
    const trigger = document.getElementById(id);
    if (trigger) trigger.disabled = unresolved;
  }
  if (save) { save.disabled = unresolved || !factsReady; save.textContent = prepStatus === "APPLIED" ? "明确准备再下一局" : "保存下一局设置"; }
  if (cancel) cancel.hidden = !["PREPARED", "CONFLICT", "FAILED"].includes(prepStatus);
  if (apply) apply.hidden = prepStatus !== "CONFLICT";
  if (observed) observed.hidden = prepStatus !== "CONFLICT";
  if (retry) retry.hidden = prepStatus !== "FAILED" || state.retryable !== true;
  if (save) save.onclick = () => submitNextMatchPreparation("SAVE");
  if (cancel) cancel.onclick = () => submitNextMatchPreparation("CANCEL");
  if (apply) apply.onclick = () => submitNextMatchPreparation("CONFIRM_PREPARED");
  if (observed) observed.onclick = () => submitNextMatchPreparation("USE_OBSERVED");
  if (retry) retry.onclick = () => submitNextMatchPreparation("RETRY");
}

function updateMatchBoxDropdown(venueId) {
  const boxMenu = document.getElementById("match-box-menu");
  const boxDisplay = document.getElementById("match-box-display");
  if (!boxMenu) return;
  const venues = dashboard.matchOptions.venues || [];
  const venue = venues.find(v => v.venueId === venueId);
  const boxes = venue ? (venue.boxes || []) : [];
  
  boxMenu.innerHTML = boxes.map(b => 
    `<div class="dropdown-item" data-box-id="${b.boxId}" data-box-name="${b.displayName}">${b.displayName}</div>`
  ).join("");
  const boxProtected = Boolean((dashboard.lastCurrentMatch || {}).fieldStates?.box?.protected);
  if (boxProtected) {
    boxMenu.innerHTML += `<div class="dropdown-item" data-restore-auto="box,boxId">恢复自动</div>`;
  }
  
  if (!boxes.length) {
    boxMenu.innerHTML = `<div class="dropdown-item" style="color: #64748b; cursor: default;">请先选择会场</div>`;
    if (boxProtected) {
      boxMenu.innerHTML += `<div class="dropdown-item" data-restore-auto="box,boxId">恢复自动</div>`;
    }
    if (boxDisplay && !dashboard.matchState.box) boxDisplay.textContent = "请选择宝箱";
  }
}

function restoreMatchAuto(fields) {
  postNative("manual_facts", { facts: {}, restoreAutoFields: fields });
}

function setMatchVenue(venueId, venueName) {
  dashboard.matchState.venueId = venueId;
  dashboard.matchState.venue = venueName;
  dashboard.matchState.boxId = null;
  dashboard.matchState.box = null;
  
  const venueDisplay = document.getElementById("match-venue-display");
  if (venueDisplay) venueDisplay.textContent = venueName || "请选择会场";
  const boxDisplay = document.getElementById("match-box-display");
  if (boxDisplay) boxDisplay.textContent = "请选择宝箱";
  
  updateMatchBoxDropdown(venueId);
  syncMatchFacts();
}

function setMatchBox(boxId, boxName) {
  dashboard.matchState.boxId = boxId;
  dashboard.matchState.box = boxName;
  const boxDisplay = document.getElementById("match-box-display");
  if (boxDisplay) boxDisplay.textContent = boxName || "请选择宝箱";
  syncMatchFacts();
}

function setMatchCondition(condId, condName) {
  if (dashboard.matchState.observationProfile === "native-readonly-v1") {
    const prior = dashboard.lastCurrentMatch?.manualCommandResult || dashboard.lastCurrentMatch?.nativeControlResult || {};
    const revision = Number(prior.revision);
    dashboard.pendingFieldConditionReceiptRevision = Number.isFinite(revision) ? revision : -1;
    dashboard.pendingFieldCondition = condId;
  }
  dashboard.matchState.fieldCondition = condId;
  const condDisplay = document.getElementById("match-cond-display");
  if (condDisplay) condDisplay.textContent = condName || "标准对局";
  syncMatchFacts();
}

function getCatalogItems(rarity) {
  const list = window.AuctionEngineV06.baseCatalogFor({ playedAt: new Date().toISOString() })[rarity] || [];
  return list.map(x => ({
    name: String(x[0] || ""),
    price: Number(x[1]) || 0
  })).filter(x => Number.isFinite(x.price) && x.price > 0);
}

function addKnownChip(rarity, rawVal, name, price) {
  if (!dashboard.knownChips) {
    dashboard.knownChips = { gold: [], red: [], purple: [], blue: [], green: [], white: [] };
  }
  const str = String(rawVal || "").trim();
  if (!str) return;
  const chipObj = { raw: str, name: name || str, price: price || null };
  dashboard.knownChips[rarity].push(chipObj);
  renderKnownChips(rarity);
  syncMatchFacts();
}

function removeKnownChip(rarity, index) {
  if (!dashboard.knownChips || !dashboard.knownChips[rarity]) return;
  dashboard.knownChips[rarity].splice(index, 1);
  renderKnownChips(rarity);
  syncMatchFacts();
}

function serializeKnownChips(rarity) {
  if (!dashboard.knownChips || !dashboard.knownChips[rarity]) return "";
  return dashboard.knownChips[rarity].map(c => c.raw).filter(Boolean).join("+");
}

function renderKnownChips(rarity) {
  const container = document.getElementById(`match-chips-${rarity}`);
  if (!container) return;
  const chips = (dashboard.knownChips && dashboard.knownChips[rarity]) || [];
  container.innerHTML = chips.map((c, idx) => {
    const label = c.price ? `${escapeHtml(c.name)} (${formatCurrency(c.price)})` : escapeHtml(c.name);
    return `<span class="known-chip is-${rarity}"><span>${label}</span><button type="button" class="chip-remove" data-rarity="${rarity}" data-index="${idx}" title="删除">×</button></span>`;
  }).join("");
}

function syncKnownChipsFromFacts(facts) {
  if (!dashboard.knownChips) {
    dashboard.knownChips = { gold: [], red: [], purple: [], blue: [], green: [], white: [] };
  }
  ["gold", "red", "purple", "blue", "green", "white"].forEach(rarity => {
    const key = `known${rarity[0].toUpperCase()}${rarity.slice(1)}`;
    const raw = String(facts[key] || "").trim();
    const currSerialized = serializeKnownChips(rarity);
    if (raw !== currSerialized) {
      if (!raw) {
        dashboard.knownChips[rarity] = [];
      } else {
        const tokens = raw.split("+").map(t => t.trim()).filter(Boolean);
        const catalog = getCatalogItems(rarity);
        dashboard.knownChips[rarity] = tokens.map(tok => {
          const match = catalog.find(item => item.name === tok || String(item.price) === tok);
          return {
            raw: tok,
            name: match ? match.name : tok,
            price: match ? match.price : (/^\d+$/.test(tok) ? Number(tok) : null)
          };
        });
      }
      renderKnownChips(rarity);
    }
  });
}

function setupKnownItemsAutocomplete() {
  ["gold", "red", "purple", "blue", "green", "white"].forEach(rarity => {
    const input = document.getElementById(`match-input-known-${rarity}`);
    const suggestBox = document.getElementById(`match-suggest-${rarity}`);
    const chipsBox = document.getElementById(`match-chips-${rarity}`);

    if (chipsBox) {
      chipsBox.addEventListener("click", (e) => {
        const btn = e.target.closest(".chip-remove");
        if (btn) {
          const r = btn.dataset.rarity;
          const idx = Number(btn.dataset.index);
          removeKnownChip(r, idx);
        }
      });
    }

    if (!input || !suggestBox) return;

    const hideSuggest = () => {
      suggestBox.hidden = true;
      suggestBox.innerHTML = "";
    };

    const commitInput = () => {
      const val = input.value.trim();
      if (!val) return;
      try {
        const key = `known${rarity[0].toUpperCase()}${rarity.slice(1)}`;
        window.AuctionEngineV06.validateKnownInput({
          [key]: [serializeKnownChips(rarity), val].filter(Boolean).join("+")
        });
        input.setCustomValidity("");
      } catch (error) {
        input.setCustomValidity(error.message || "请填写图鉴中的名称或价格");
        input.reportValidity();
        return;
      }
      const catalog = getCatalogItems(rarity);
      const match = catalog.find(item => item.name === val || String(item.price) === val);
      addKnownChip(rarity, val, match ? match.name : val, match ? match.price : null);
      input.value = "";
      hideSuggest();
    };

    const updateSuggest = () => {
      input.setCustomValidity("");
      const val = input.value.trim();
      if (!val) {
        hideSuggest();
        return;
      }
      const fragment = val.split(/[+/]/).at(-1).trim();
      const prefix = val.slice(0, val.length - val.split(/[+/]/).at(-1).length);
      const all = getCatalogItems(rarity);
      const isNum = /^\d+$/.test(fragment);
      let matched = [];
      if (isNum) {
        const seen = new Set();
        for (const it of all) {
          const pStr = String(it.price);
          if (pStr.startsWith(fragment) && !seen.has(pStr)) {
            seen.add(pStr);
            matched.push({ name: it.name, price: it.price, raw: prefix + it.name, label: `${pStr} (${it.name})` });
          }
        }
      } else {
        const seen = new Set();
        for (const it of all) {
          if ((it.name.includes(fragment) || ({"赤色来电":"电话", "澄空之眼":"戒指"}[it.name] || "").includes(fragment)) && !seen.has(it.name)) {
            seen.add(it.name);
            matched.push({ name: it.name, price: it.price, raw: prefix + it.name, label: `${it.name} (${formatCurrency(it.price)})` });
          }
        }
      }
      if (!matched.length) {
        hideSuggest();
        return;
      }
      const hits = matched.slice(0, 6);
      suggestBox.innerHTML = hits.map((item, idx) => `
        <div class="suggest-item known-suggest-item" data-index="${idx}">
          <span>${escapeHtml(item.label)}</span>
        </div>
      `).join("");
      suggestBox.hidden = false;

      suggestBox.querySelectorAll(".suggest-item").forEach(itemEl => {
        itemEl.addEventListener("pointerdown", (e) => e.preventDefault());
        itemEl.addEventListener("click", () => {
          const idx = Number(itemEl.dataset.index);
          const chosen = hits[idx];
          if (chosen) {
            input.value = chosen.raw;
            commitInput();
          }
        });
      });
    };

    input.addEventListener("input", updateSuggest);
    input.addEventListener("focus", updateSuggest);
    input.addEventListener("change", commitInput);
    input.addEventListener("blur", () => {
      window.setTimeout(hideSuggest, 200);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) {
        e.preventDefault();
        commitInput();
      } else if (e.key === "Escape") {
        hideSuggest();
      }
    });
  });
}

function getMatchFactsFromForm() {
  const parseNumOrNull = (id) => {
    const el = document.getElementById(id);
    if (!el) return null;
    const v = el.value.trim().replace(/,/g, "");
    if (v === "") return null;
    const num = Number(v);
    return Number.isFinite(num) ? num : null;
  };

  const q = parseNumOrNull("match-input-q");
  const goldAvg = parseNumOrNull("match-input-gold-avg");
  const purpleCount = parseNumOrNull("match-input-purple-count");
  const purpleAvg = parseNumOrNull("match-input-purple-avg");
  const blueCount = parseNumOrNull("match-input-blue-count");
  const goldCount = parseNumOrNull("match-input-gold-count");
  const redCount = parseNumOrNull("match-input-red-count");
  const totalItems = parseNumOrNull("match-input-total-items");
  const totalGrid = parseNumOrNull("match-input-total-grid");
  const goldGrid = parseNumOrNull("match-input-gold-grid");
  const purpleGrid = parseNumOrNull("match-input-purple-grid");

  const knownGold = serializeKnownChips("gold");
  const knownRed = serializeKnownChips("red");
  const knownPurple = serializeKnownChips("purple");

  return {
    venueId: dashboard.matchState.venueId,
    venue: dashboard.matchState.venue,
    boxId: dashboard.matchState.boxId,
    box: dashboard.matchState.box,
    fieldCondition: dashboard.matchState.fieldCondition,
    q: q,
    goldAvg: goldAvg,
    purpleCount: purpleCount,
    purple: purpleCount,
    purpleAvg: purpleAvg,
    blueCount: blueCount,
    goldCount: goldCount,
    redCount: redCount,
    totalItems: totalItems,
    totalGrid: totalGrid,
    goldGrid: goldGrid,
    purpleGrid: purpleGrid,
    whiteCount: parseNumOrNull("match-input-white-count"),
    whiteAvg: parseNumOrNull("match-input-white-avg"),
    whiteGrid: parseNumOrNull("match-input-white-grid"),
    greenCount: parseNumOrNull("match-input-green-count"),
    greenAvg: parseNumOrNull("match-input-green-avg"),
    greenGrid: parseNumOrNull("match-input-green-grid"),
    blueAvg: parseNumOrNull("match-input-blue-avg"),
    blueGrid: parseNumOrNull("match-input-blue-grid"),
    redGrid: parseNumOrNull("match-input-red-grid"),
    knownGold: knownGold,
    knownRed: knownRed,
    knownPurple: knownPurple,
    sparkle: readSparkleInputs("match-sparkle-count", "match-sparkle-names"),
    privateBidCap: parseNumOrNull("match-input-private-bid-cap"),
    bidActionCount: parseNumOrNull("match-input-bid-action-count"),
    welfareReceived: parseNumOrNull("match-input-welfare-received"),
    knownBlue: serializeKnownChips("blue"),
    knownGreen: serializeKnownChips("green"),
    knownWhite: serializeKnownChips("white"),

  };
}

function isMissingMatchFact(value) {
  return value === undefined || value === null || value === "";
}

function getChangedMatchFacts() {
  const current = getMatchFactsFromForm();
  const prev = dashboard.lastSyncedFacts || (dashboard.lastSyncedFacts = {});
  const patch = {};
  const clearedFields = [];
  for (const [key, value] of Object.entries(current)) {
    const oldVal = Object.prototype.hasOwnProperty.call(prev, key) ? prev[key] : undefined;
    const oldMissing = isMissingMatchFact(oldVal);
    const newMissing = isMissingMatchFact(value);
    if ((key === "sparkle" && JSON.stringify(oldVal ?? null) === JSON.stringify(value)) || oldVal === value || (oldMissing && newMissing)) {
      if (oldVal === undefined && newMissing) prev[key] = value;
      continue;
    }
    patch[key] = value;
    if (newMissing && !oldMissing) clearedFields.push(key);
  }
  return { patch, clearedFields };
}

function syncMatchFacts() {
  if (!validateWelfareReceipt("match-input-private-bid-cap", "match-error-private-bid-cap")) return;
  if (!validateWelfareReceipt("match-input-bid-action-count", "match-error-bid-action-count")) return;
  if (!validateWelfareReceipt("match-input-welfare-received", "match-welfare-error")) return;
  const { patch, clearedFields } = getChangedMatchFacts();
  if (!Object.keys(patch).length && !clearedFields.length) return;
  const payload = { facts: patch };
  if (clearedFields.length) payload.clearedFields = clearedFields;
  postNative("manual_facts", payload);
  Object.assign(dashboard.lastSyncedFacts, patch);
}

function syncMatchFactsDebounced(delay = 250) {
  if (dashboard.matchSyncTimer) {
    clearTimeout(dashboard.matchSyncTimer);
  }
  dashboard.matchSyncTimer = setTimeout(() => {
    syncMatchFacts();
  }, delay);
}

function openNextMatchModal() {
  const modal = document.getElementById("next-match-modal");
  if (modal) modal.hidden = false;
}

function closeNextMatchModal() {
  const modal = document.getElementById("next-match-modal");
  if (modal) modal.hidden = true;
}

function toggleManualSettleEdit() {
  const manualContainer = document.getElementById("settle-manual-edit-container");
  if (manualContainer) {
    manualContainer.hidden = !manualContainer.hidden;
    const btn = document.getElementById("settle-modal-toggle-edit-btn");
    if (btn) {
      btn.textContent = manualContainer.hidden ? "修正识别结果" : "折叠手动修正";
    }
  }
}

function openSettleMatchModal() {
  const modal = document.getElementById("settle-match-modal");
  const err = document.getElementById("settle-modal-error");
  if (err) { err.hidden = true; err.textContent = ""; }

  const facts = currentMatch.facts || {};
  const settleData = currentMatch.settlement || {};

  const winner = facts.settlementWinnerName || facts.winner || settleData.winner || "";
  const assistant = facts.settlementAuctionAssistantName || facts.auctionAssistant || settleData.auctionAssistant || "";
  const clearing = facts.clearingPrice ?? settleData.clearingPrice ?? null;
  const actual = facts.actualTotal ?? settleData.actualTotal ?? null;
  const profit = facts.realizedProfit ?? settleData.realizedProfit ?? (actual != null && clearing != null ? (actual - clearing) : null);
  let isSelf = facts.isSelfWinner ?? settleData.isSelfWinner ?? null;
  if (isSelf === null && (facts.isAcquired !== undefined || facts.acquired !== undefined)) {
    isSelf = Boolean(facts.isAcquired ?? facts.acquired);
  }

  // Populate summary fields
  const winnerEl = document.getElementById("settle-summary-winner");
  if (winnerEl) winnerEl.textContent = winner || "未知";
  const clearingEl = document.getElementById("settle-summary-clearing");
  if (clearingEl) clearingEl.textContent = clearing != null ? formatCurrency(clearing) : "--";
  const actualEl = document.getElementById("settle-summary-actual");
  if (actualEl) actualEl.textContent = actual != null ? formatCurrency(actual) : "--";
  const profitEl = document.getElementById("settle-summary-profit");
  if (profitEl) {
    profitEl.textContent = profit != null ? ((profit >= 0 ? "+" : "") + formatCurrency(profit)) : "--";
    profitEl.style.color = profit != null ? (profit >= 0 ? "#34d399" : "#f87171") : "#f59e0b";
  }
  const acquiredEl = document.getElementById("settle-summary-acquired");
  if (acquiredEl) acquiredEl.textContent = isSelf != null ? (isSelf ? "是" : "否") : "未知";
  const assistantEl = document.getElementById("settle-summary-assistant");
  if (assistantEl) assistantEl.textContent = assistant || "无 / 未知";

  // Pre-fill manual edit inputs
  const clearingInput = document.getElementById("settle-clearing-price");
  if (clearingInput) clearingInput.value = clearing != null ? clearing : "";
  const actualInput = document.getElementById("settle-actual-total");
  if (actualInput) actualInput.value = actual != null ? actual : "";
  const acquiredInput = document.getElementById("settle-acquired-select");
  if (acquiredInput) acquiredInput.value = isSelf != null ? String(isSelf) : "";
  const winnerInput = document.getElementById("settle-winner-name");
  if (winnerInput) winnerInput.value = winner || "";

  // Check confidence / completeness
  const isComplete = Boolean(winner && clearing != null && clearing > 0 && actual != null && actual > 0 && isSelf != null);
  const manualContainer = document.getElementById("settle-manual-edit-container");
  const hintEl = document.getElementById("settle-summary-hint");
  const toggleBtn = document.getElementById("settle-modal-toggle-edit-btn");
  if (manualContainer) {
    manualContainer.hidden = isComplete;
  }
  if (hintEl) {
    hintEl.hidden = !isComplete;
  }
  if (toggleBtn) {
    toggleBtn.textContent = (manualContainer && !manualContainer.hidden) ? "折叠手动修正" : "修正识别结果";
  }

  const isAlreadyFinalized = Boolean(facts.settlementFinalized || currentMatch.lifecycleStatus === "FINALIZED");
  const titleEl = document.getElementById("settle-modal-title");
  if (titleEl) {
    titleEl.textContent = isAlreadyFinalized ? "本局结算（已自动完成）" : "本局结算";
  }
  const confirmButton = document.getElementById("settle-modal-confirm-btn");
  if (confirmButton) {
    confirmButton.disabled = false;
    confirmButton.textContent = isAlreadyFinalized ? "确认并开始下一局" : "确认保存并开始下一局";
  }

  if (modal) modal.hidden = false;
}

function closeSettleMatchModal() {
  const modal = document.getElementById("settle-match-modal");
  if (modal) modal.hidden = true;
  const err = document.getElementById("settle-modal-error");
  if (err) { err.hidden = true; err.textContent = ""; }
}

function confirmSettleMatch() {
  const isAlreadyFinalized = Boolean(currentMatch.facts.settlementFinalized || currentMatch.lifecycleStatus === "FINALIZED");
  const expectedMatchId = dashboard.matchState.matchId;

  if (isAlreadyFinalized) {
    keepDraftAndStartNextMatch();
    return;
  }

  const manualContainer = document.getElementById("settle-manual-edit-container");
  const isManualExpanded = manualContainer && !manualContainer.hidden;

  let clearingPrice, actualTotal, isSelf, winner;
  if (isManualExpanded) {
    const clearingRaw = document.getElementById("settle-clearing-price").value.trim();
    const actualRaw = document.getElementById("settle-actual-total").value.trim();
    clearingPrice = Number(clearingRaw.replace(/,/g, ""));
    actualTotal = Number(actualRaw.replace(/,/g, ""));
    const acquiredRaw = document.getElementById("settle-acquired-select").value;
    isSelf = acquiredRaw === "true";
    winner = document.getElementById("settle-winner-name").value.trim();
  } else {
    const facts = currentMatch.facts || {};
    const settleData = currentMatch.settlement || {};
    clearingPrice = Number(facts.clearingPrice ?? settleData.clearingPrice ?? 0);
    actualTotal = Number(facts.actualTotal ?? settleData.actualTotal ?? 0);
    winner = String(facts.settlementWinnerName || facts.winner || settleData.winner || "").trim();
    isSelf = Boolean(facts.isSelfWinner ?? settleData.isSelfWinner ?? (facts.isAcquired ?? facts.acquired ?? false));
  }

  const errorEl = document.getElementById("settle-modal-error");
  if (!(clearingPrice > 0) || !(actualTotal > 0) || !winner) {
    if (errorEl) {
      errorEl.textContent = "未能完整识别结算数据，请点击「修正识别结果」手动填写或留作草稿。";
      errorEl.hidden = false;
    }
    if (manualContainer) {
      manualContainer.hidden = false;
      const toggleBtn = document.getElementById("settle-modal-toggle-edit-btn");
      if (toggleBtn) toggleBtn.textContent = "折叠手动修正";
    }
    return;
  }

  const assistant = currentMatch.facts.settlementAuctionAssistantName || currentMatch.facts.auctionAssistant || "";
  const settlementPayload = {
    expectedMatchId: expectedMatchId,
    settlement: {
      clearingPrice: clearingPrice,
      actualTotal: actualTotal,
      acquired: isSelf,
      winner: winner,
      settlementWinnerName: winner,
      settlementAuctionAssistantName: assistant,
      auctionAssistant: assistant,
      isSelfWinner: isSelf
    }
  };

  postNative("manual_finalize", settlementPayload);
  const confirmButton = document.getElementById("settle-modal-confirm-btn");
  if (confirmButton) { confirmButton.disabled = true; confirmButton.textContent = "正在保存…"; }
}

function keepDraftAndStartNextMatch() {
  const expectedMatchId = dashboard.matchState.matchId;
  if (!expectedMatchId) return;
  const confirmButton = document.getElementById("settle-modal-confirm-btn");
  if (confirmButton) confirmButton.disabled = true;
  postNative("manual_next_match", { expectedMatchId, disposition: "keep_draft" });
  closeSettleMatchModal();
}

function updatePlayerDisplayNameStatus(name, options = {}) {
  const playerNameStatus = document.getElementById("player-display-name-status");
  const saveBtn = document.getElementById("save-player-display-name");
  if (options.saving) {
    if (saveBtn) saveBtn.disabled = true;
    if (playerNameStatus) {
      playerNameStatus.textContent = "正在保存…";
      playerNameStatus.style.color = "#94a3b8";
    }
    return;
  }
  if (saveBtn) saveBtn.disabled = false;
  dashboard.isSavingPlayerName = false;
  dashboard.pendingPlayerName = null;
  if (!playerNameStatus) return;
  if (options.error) {
    playerNameStatus.textContent = `保存失败：${options.error}`;
    playerNameStatus.style.color = "#f87171";
    return;
  }
  const cleanName = (name || "").trim();
  if (cleanName) {
    playerNameStatus.textContent = `已设置：${cleanName}`;
    playerNameStatus.style.color = "#34d399";
  } else {
    playerNameStatus.textContent = "未设置，使用画面姓名；清空后保存可恢复";
    playerNameStatus.style.color = "#94a3b8";
  }
}

function savePlayerDisplayName() {
  const input = document.getElementById("player-display-name");
  const btn = document.getElementById("save-player-display-name");
  if (!input) return;
  const rawValue = (input.value || "").trim();
  dashboard.isSavingPlayerName = true;
  dashboard.pendingPlayerName = rawValue;
  updatePlayerDisplayNameStatus(null, { saving: true });
  postNative("manual_facts", { facts: { configuredPlayerName: rawValue } });
}

function renderManualCommandReceipt(result) {
  const statusEl = document.getElementById("manual-command-status");
  if (!statusEl) return;
  const status = String(result?.status || "").toUpperCase();
  const reason = String(result?.reason || result?.message || result?.result?.errorDetails || "");
  const reasonText = {
    STALE_MATCH_COMMAND: "观察局或版本已变化，请按当前画面重试",
    COMMAND_PENDING: "上一条修改仍在等待确认",
    STALE_FACTS_REVISION: "局内事实已变化，请按当前画面重试",
    STALE_ROUND: "回合已变化，请按当前画面重试",
    MATCH_CHANGED: "当前局已变化，修改未生效",
    NATIVE_OBSERVATION_NOT_RUNNING: "观察未运行，修改未生效",
    OBSERVATION_INVALIDATED: "观察已暂停或失联，修改未生效",
    OBSERVATION_SCOPE_CHANGED: "观察目标或局内版本已变化，修改未生效",
    "observation-frame-timeout": "局内画面长时间未更新，修改未生效",
    NATIVE_CONTROL_CHANNEL_FAILED: "未能发送到观察 worker，修改未生效",
    TIMEOUT: "观察 worker 未及时确认，修改未生效"
  }[reason] || reason;
  if (status === "PENDING" || status === "SENT") {
    statusEl.textContent = "修改已发送，等待观察 worker 确认";
    statusEl.style.color = "#f59e0b";
  } else if (status === "ACK" || status === "ACCEPTED") {
    statusEl.textContent = "观察 worker 已确认修改";
    statusEl.style.color = "#34d399";
  } else if (["REJECT", "REJECTED", "ERROR", "TIMEOUT"].includes(status)) {
    statusEl.textContent = `修改未生效：${reasonText || "当前状态不允许修改"}`;
    statusEl.style.color = "#f87171";
  } else {
    statusEl.textContent = "";
  }
  statusEl.hidden = !statusEl.textContent;
}

function renderCurrentAuctionDetails(currentMatch) {
  const health = currentMatch.visionHealth || {};
  const isNative = currentMatch.observationProfile === "native-readonly-v1" || health.profile === "native-readonly-v1";
  const nativeFrameIsLive = !isNative || (
    currentMatch.observationStatus === "FRAME"
    && health.status === "READY"
    && health.stage === "native-frame"
  );
  const bidding = currentMatch.bidding || {};
  const seatsGrid = document.getElementById("match-seats-grid");
  if (seatsGrid) {
    if (!nativeFrameIsLive) {
      const waitingForFrame = isNative && ["native-ready", "native-starting", "native-refreshing"].includes(health.stage);
      seatsGrid.textContent = waitingForFrame
        ? "等待当前局的新鲜观察帧；当前出价暂不可用"
        : "观察已暂停；上一有效帧的出价不作为当前出价";
    } else if (!Array.isArray(bidding.seats) || bidding.seats.length === 0) {
      seatsGrid.textContent = "暂无当前出价观察";
    } else {
      seatsGrid.innerHTML = bidding.seats.map(seat => {
        const slot = seat.slot || seat.seat;
        const bid = seat.currentBid != null ? seat.currentBid : seat.bid;
        const label = escapeHtml(seat.name || `座位 ${slot}`);
        const bidText = bidding.hiddenBids ? "金额隐藏" : bid != null ? formatCurrency(bid) : "未识别";
        return `
        <div class="seat-pill ${seat.isMe ? "is-me" : ""}">
          <span class="seat-name">${label}</span>
          <span class="seat-bid">${escapeHtml(bidText)}</span>
        </div>`;
      }).join("");
    }
  }

  const intelEl = document.getElementById("match-intel-timeline");
  if (intelEl) {
    if (!nativeFrameIsLive) {
      intelEl.textContent = isNative
        ? "观察已暂停；已采集情报保留在本局草稿中"
        : "暂无情报原文";
    } else {
      const timeline = currentMatch.publicIntel?.timeline || {};
      const rows = Array.isArray(timeline.observations) ? timeline.observations : [];
      if (!rows.length) {
        intelEl.textContent = "暂无情报原文";
      } else {
        intelEl.innerHTML = rows.map(row => {
          const mark = row.participation === "valuation" ? "已参与估价" : row.participation === "pending" ? "待解析" : "仅记录";
          const round = row.round != null ? `第 ${row.round} 回合` : "";
          return `<p class="intel-line">${escapeHtml(round)} · ${mark} · ${escapeHtml(row.text || row.rawText || "")}</p>`;
        }).join("");
      }
    }
  }
}

function openGuidebookWarehouseCandidate(catalogId, name, rarity) {
  const candidate = {
    catalogId: String(catalogId || "").trim(),
    name: String(name || "").trim(),
    rarity: String(rarity || "").trim()
  };
  if (!candidate.catalogId && !candidate.name) return;
  dashboard.pendingGuidebookCandidate = candidate;
  dashboard.guidebookSearch = candidate.catalogId || candidate.name;
  dashboard.guidebookCategory = "all";
  dashboard.guidebookGridSize = "all";
  dashboard.guidebookRarity = "all";
  dashboard.guidebookSelectedItem = null;
  showView("guidebook");
  setGuidebookTab("catalog");
  renderGuidebook();
}

function renderWarehouseSlots(warehouse, currentMatch = dashboard.lastCurrentMatch) {
  const slotsListEl = document.getElementById("match-wh-slots-list");
  if (!slotsListEl) return;
  const slots = warehouse?.slots || [];
  if (!slots.length) {
    slotsListEl.innerHTML = `<div style="color: var(--text-dim, #888); font-size: 12px; padding: 4px 0;">暂无仓库槽位数据</div>`;
    return;
  }

  slotsListEl.innerHTML = slots.map((slot, index) => {
    const candidates = Array.isArray(slot.candidates) ? slot.candidates.slice() : [];
    const bestId = String(slot.bestCandidateId || "");
    if (bestId) candidates.sort((a, b) => {
      const aBest = String(a?.catalogId || a?.Id || "") === bestId;
      const bBest = String(b?.catalogId || b?.Id || "") === bestId;
      return Number(bBest) - Number(aBest);
    });
    const best = candidates.find(item => String(item?.catalogId || item?.Id || "") === bestId)
      || candidates[0] || null;
    const exact = slot.identityStatus === "EXACT" && slot.identifiedName;
    const manualDecision = slot.manualDecision && typeof slot.manualDecision === "object" ? slot.manualDecision : null;
    const candidateName = slot.bestCandidateName || best?.name || best?.Name || "";
    const rarityLabel = ({ gold: "金", purple: "紫", red: "红", blue: "蓝", green: "绿", white: "白" })[slot.rarity] || "品质待确认";
    const size = slot.w && slot.h ? `${slot.w}×${slot.h}` : "尺寸待确认";
    const position = slot.row != null && slot.col != null
      && Number.isInteger(Number(slot.row)) && Number.isInteger(Number(slot.col))
      ? `第 ${Number(slot.row) + 1} 行 · 第 ${Number(slot.col) + 1} 列`
      : `实例 ${index + 1}`;
    const status = manualDecision?.action === "CONFIRM_CANDIDATE"
      ? `<span class="wh-identity-state is-candidate">人工确认 · 本实例</span>`
      : manualDecision?.action === "REJECT_CANDIDATE"
        ? `<span class="wh-identity-state is-candidate">已排除此候选</span>`
        : exact
      ? `<span class="wh-identity-state is-confirmed">已确证</span>`
      : slot.identityStatus === "CANDIDATE" || candidates.length
        ? `<span class="wh-identity-state is-candidate">候选 · 未确证</span>`
        : `<span class="wh-identity-state is-unknown">身份未知</span>`;
    const identity = manualDecision?.action === "CONFIRM_CANDIDATE"
      ? `人工确认：${escapeHtml(manualDecision.name || manualDecision.manualIdentity?.name || candidateName)}（仅此实例）`
      : manualDecision?.action === "REJECT_CANDIDATE"
        ? `已排除：${escapeHtml(manualDecision.name || candidateName)}；其他身份仍待确认`
        : exact
      ? `已识别：${escapeHtml(slot.identifiedName)}`
      : candidateName
        ? `${slot.identityReferenceKind === "DERIVED_UNVERIFIED" ? "派生参考候选" : "视觉候选"}：${escapeHtml(candidateName)}（未达到身份确证条件）`
        : candidates.length ? "候选集合待核对" : "当前只确认槽位与品质/尺寸";
    const candidateButtons = candidates.slice(0, 3).map(item => {
      const id = String(item?.catalogId || item?.Id || "");
      const label = String(item?.name || item?.Name || "待辨认");
      if (!id) return `<span class="wh-candidate-name">${escapeHtml(label)}</span>`;
      return `<button type="button" class="wh-candidate-link" data-wh-catalog-id="${escapeHtml(id)}" data-wh-catalog-name="${escapeHtml(label)}" data-wh-rarity="${escapeHtml(slot.rarity || "")}" title="打开图鉴条目与可用来源">图鉴：${escapeHtml(label)}</button>`;
    }).join("");
    const omitted = candidates.length > 3 ? `<small class="wh-candidate-more">另有 ${candidates.length - 3} 个候选</small>` : "";
    const activity = slot.activityEvidence && slot.activityEvidence.evidenceId;
    const reviewButton = activity
      ? `<button type="button" class="btn-wb-action" data-wh-open-review="${index}">看活动裁图与候选来源</button>`
      : `<span class="wh-evidence-missing">本次活动裁图未保存</span>`;
    return `<article class="wh-slot-item"><div class="wh-slot-heading"><strong>${position} · ${size} · ${rarityLabel}</strong>${status}</div><div class="wh-slot-identity">${identity}</div>${candidateButtons ? `<div class="wh-slot-candidates">${candidateButtons}${omitted}</div>` : ""}<div style="margin-top:5px;">${reviewButton}</div></article>`;
  }).join("");

  slotsListEl.querySelectorAll("[data-wh-catalog-id]").forEach(button => {
    button.addEventListener("click", () => openGuidebookWarehouseCandidate(
      button.dataset.whCatalogId, button.dataset.whCatalogName, button.dataset.whRarity
    ));
  });
  slotsListEl.querySelectorAll("[data-wh-open-review]").forEach(button => {
    button.addEventListener("click", () => openWarehouseInstanceReview(
      slots[Number(button.dataset.whOpenReview)], currentMatch
    ));
  });
  renderWarehouseInstanceReviewPanel();
}

function warehouseAnchorForSlot(slot) {
  return {
    row: Number(slot.row), col: Number(slot.col), w: Number(slot.w),
    h: Number(slot.h), rarity: String(slot.rarity || "unknown")
  };
}

function openWarehouseInstanceReview(slot, currentMatch = dashboard.lastCurrentMatch) {
  const activity = slot?.activityEvidence;
  if (!slot || !activity?.evidenceId) return;
  if (dashboard.warehouseInstanceReview?.busy) return;
  const match = currentMatch || {};
  const candidateIds = (Array.isArray(slot.candidates) ? slot.candidates : [])
    .map(item => String(item?.catalogId || item?.Id || "")).filter(Boolean);
  const review = {
    slot: JSON.parse(JSON.stringify(slot)),
    requestId: null,
    evidence: null,
    selectedCandidateId: null,
    receipt: null,
    busy: false,
    matchId: match.matchId,
    sessionId: activity.sessionId || match.observationSessionId,
    round: match.observationRound,
    targetInstance: match.observationTarget || match.target || null,
    mainDecisionGeneration: match.nativeInstanceDecisionGeneration,
  };
  dashboard.warehouseInstanceReview = review;
  review.requestId = postNative("request_warehouse_slot_evidence", {
    matchId: review.matchId,
    sessionId: review.sessionId,
    round: review.round,
    targetInstance: review.targetInstance,
    mainDecisionGeneration: review.mainDecisionGeneration,
    instanceAnchor: warehouseAnchorForSlot(slot),
    activityEvidenceId: activity.evidenceId,
    instanceDecisionToken: slot.instanceDecisionToken,
    candidateIds,
  });
  renderWarehouseInstanceReviewPanel();
}

function renderWarehouseInstanceReviewPanel() {
  const panel = document.getElementById("match-wh-instance-review");
  if (!panel) return;
  const review = dashboard.warehouseInstanceReview;
  if (!review?.slot) { panel.hidden = true; return; }
  panel.hidden = false;
  const slot = review.slot;
  const source = review.evidence?.source || slot.activityEvidence || {};
  const title = document.getElementById("match-wh-instance-review-title");
  const meta = document.getElementById("match-wh-instance-review-meta");
  const status = document.getElementById("match-wh-instance-review-status");
  const image = document.getElementById("match-wh-instance-review-image");
  const candidateList = document.getElementById("match-wh-instance-review-candidates");
  const confirmButton = document.getElementById("match-wh-instance-confirm");
  const rejectButton = document.getElementById("match-wh-instance-reject");
  const restoreButton = document.getElementById("match-wh-instance-restore");
  if (title) title.textContent = `活动实例 · 第 ${Number(slot.row) + 1} 行第 ${Number(slot.col) + 1} 列`;
  if (meta) {
    const sourceKind = source.sourceKind === "offline-replay" ? "离线回放活动帧裁图"
      : ["native_wgc", "native"].includes(String(source.sourceKind || "").toLowerCase())
        ? "Native 活动帧裁图" : "来源类型未知的活动裁图";
    const box = Array.isArray(source.box) ? source.box.join(", ") : "未知";
    meta.textContent = `${sourceKind} · 局 ${source.matchId || review.matchId || "未知"} · 会话 ${source.sessionId || review.sessionId || "未知"} · ${source.observedAt || "时间未记录"} · 帧 ${source.frameSequence ?? "未知"} · 原帧坐标 ${box}`;
  }
  if (image) {
    image.hidden = !review.evidence?.dataUrl;
    image.src = review.evidence?.dataUrl || "";
  }
  if (status) {
    if (review.receipt?.status === "ACK") {
      const action = review.receipt.decision?.action;
      const valuationStatus = review.receipt.solverRefreshStatus === "WAITING_FOR_FRESH_OBSERVATION"
        ? "估值输入已变更，旧建议已撤销；等待新鲜有效帧后按现有准入重新求解。"
        : "估值输入未变化；建议状态以求解状态卡为准。";
      status.textContent = action === "CONFIRM_CANDIDATE" ? `观察 worker 已确认这一个实例（人工来源）。${valuationStatus}`
        : action === "REJECT_CANDIDATE" ? "观察 worker 已排除此实例的所选候选；其他身份仍未确认。"
          : `观察 worker 已撤销此实例的人工决定。${valuationStatus}`;
      if (action === "REJECT_CANDIDATE") status.textContent += ` ${valuationStatus}`;
    } else if (review.receipt?.status === "REJECTED") {
      status.textContent = `未生效：${review.receipt.reason || "观察 worker 拒绝或观察范围已变化"}`;
    } else if (review.busy) {
      status.textContent = "等待观察 worker 回执；修改尚未显示为生效。";
    } else if (review.evidence?.ok) {
      status.textContent = review.evidence.decisionAllowed && review.scopeCurrent !== false
        ? "已打开本次活动裁图和候选来源。选择一个候选后可作实例级决定。"
        : "活动裁图可回看；当前局、会话或观察资格已变化，实例决定暂不可提交。";
    } else if (review.evidence) {
      status.textContent = review.evidence.message || "本次活动裁图缺失；没有使用其他图片替代。";
    } else {
      status.textContent = "正在读取与此槽位对应的活动裁图；等待结果期间不会提交决定。";
    }
  }
  const candidates = review.evidence?.candidates || [];
  if (candidateList) {
    candidateList.innerHTML = candidates.length ? candidates.map(candidate => {
      const id = String(candidate.catalogId || candidate.Id || "");
      const selected = id === review.selectedCandidateId;
      const manual = slot.manualDecision || {};
      const rejected = manual.action === "REJECT_CANDIDATE" && manual.catalogId === id;
      const images = (candidate.sourceImages || []).filter(row => row?.available && row.uri).slice(0, 2)
        .map(row => `<img src="${escapeHtml(row.uri)}" alt="图鉴来源：${escapeHtml(candidate.name || "候选条目")}" style="width:64px;height:64px;object-fit:contain;background:#0b1220;border-radius:5px;">`).join("");
      const sourceStatus = images ? "图鉴来源图片" : "图鉴来源图片暂不可用";
      return `<article style="padding:7px;border:1px solid ${selected ? "#60a5fa" : "var(--border-subtle, #334155)"};border-radius:6px;"><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;"><strong>${escapeHtml(candidate.name || candidate.Name || "待辨认")}</strong><span>${selected ? "当前选择" : ""}${rejected ? " · 已在本实例排除" : ""}</span><button type="button" class="btn-wb-action" data-wh-review-select="${escapeHtml(id)}">选择此候选</button></div><div style="font-size:11px;opacity:.8;margin:4px 0;">目录 ID：${escapeHtml(id)} · ${sourceStatus}</div><div style="display:flex;gap:5px;">${images}</div></article>`;
    }).join("") : `<div style="font-size:12px;opacity:.75;">此槽位没有可供人工确认的候选；未知信息保持未知。</div>`;
    candidateList.querySelectorAll("[data-wh-review-select]").forEach(button => button.addEventListener("click", () => {
      review.selectedCandidateId = button.dataset.whReviewSelect;
      renderWarehouseInstanceReviewPanel();
    }));
  }
  const decisionAllowed = Boolean(review.evidence?.decisionAllowed && review.scopeCurrent !== false
    && !review.busy && review.evidence?.ok);
  const candidateDecisionAllowed = decisionAllowed && review.evidence?.identityStatus === "CANDIDATE";
  if (confirmButton) {
    confirmButton.disabled = !candidateDecisionAllowed || !review.selectedCandidateId;
    confirmButton.onclick = () => submitWarehouseInstanceDecision("CONFIRM_CANDIDATE");
  }
  if (rejectButton) {
    rejectButton.disabled = !candidateDecisionAllowed || !review.selectedCandidateId;
    rejectButton.onclick = () => submitWarehouseInstanceDecision("REJECT_CANDIDATE");
  }
  if (restoreButton) {
    restoreButton.hidden = !slot.manualDecision;
    restoreButton.disabled = !decisionAllowed || review.busy;
    restoreButton.onclick = () => submitWarehouseInstanceDecision("RESTORE_AUTOMATIC");
  }
  const close = document.getElementById("match-wh-instance-review-close");
  if (close) {
    close.disabled = review.busy;
    close.onclick = () => { dashboard.warehouseInstanceReview = null; panel.hidden = true; };
  }
}

function submitWarehouseInstanceDecision(decision) {
  const review = dashboard.warehouseInstanceReview;
  if (!review?.slot || !review.evidence?.decisionAllowed || review.scopeCurrent === false || review.busy) return;
  review.busy = true;
  review.receipt = null;
  review.pendingCommandId = null;
  const requestId = postNative("warehouse_instance_decision", {
    matchId: review.matchId,
    sessionId: review.sessionId,
    round: review.round,
    targetInstance: review.targetInstance,
    mainDecisionGeneration: review.mainDecisionGeneration,
    instanceAnchor: warehouseAnchorForSlot(review.slot),
    activityEvidenceId: review.slot.activityEvidence?.evidenceId,
    instanceDecisionToken: review.slot.instanceDecisionToken,
    expectedGenerationId: review.slot.activityEvidence?.generationId,
    expectedInvalidationGeneration: review.slot.instanceDecisionGeneration,
    decision,
    catalogId: decision === "RESTORE_AUTOMATIC" ? null : review.selectedCandidateId,
  });
  review.decisionRequestId = requestId;
  renderWarehouseInstanceReviewPanel();
}

function syncWarehouseInstanceReviewFromMatch(currentMatch) {
  if (!currentMatch) return;
  const activeReview = dashboard.warehouseInstanceReview;
  if (!activeReview?.slot) return;
  activeReview.scopeCurrent = currentMatch.matchId === activeReview.matchId
    && currentMatch.observationSessionId === activeReview.sessionId
    && currentMatch.warehouseDecisionEligible === true;
  const receipt = currentMatch.warehouseInstanceDecisionResult;
  if (receipt && activeReview.pendingCommandId
      && receipt.commandId === activeReview.pendingCommandId
      && receipt.matchId === activeReview.matchId
      && receipt.activityEvidenceId === activeReview.slot.activityEvidence?.evidenceId
      && receipt.instanceDecisionToken === activeReview.slot.instanceDecisionToken
      && ["ACK", "REJECTED"].includes(receipt.status)) {
    activeReview.receipt = receipt;
    activeReview.busy = false;
    const updatedSlot = (currentMatch.warehouse?.slots || []).find(slot => {
      const a = warehouseAnchorForSlot(slot);
      const b = warehouseAnchorForSlot(activeReview.slot);
      return a.row === b.row && a.col === b.col && a.w === b.w && a.h === b.h && a.rarity === b.rarity;
    });
    if (updatedSlot) activeReview.slot = JSON.parse(JSON.stringify(updatedSlot));
  }
  renderWarehouseInstanceReviewPanel();
}

function renderMatch(currentMatch, overlayVisible) {
  if (!currentMatch) return;
  // Keep live auction facts visible even if an unrelated details widget fails
  // later in this large renderer. Native values are hidden until a fresh FRAME.
  renderCurrentAuctionDetails(currentMatch);
  const playerNameInput = document.getElementById('player-display-name');
  const trialLabel = document.getElementById('isolated-trial-label');
  if (trialLabel) trialLabel.hidden = currentMatch.isolatedTrial !== true;

  const incomingConfigured = (currentMatch.configuredPlayerName || "").trim();
  if (dashboard.isSavingPlayerName && dashboard.pendingPlayerName !== null) {
    if (incomingConfigured === dashboard.pendingPlayerName) {
      dashboard.isSavingPlayerName = false;
      dashboard.pendingPlayerName = null;
      dashboard.isPlayerNameEditing = false;
      if (playerNameInput) {
        playerNameInput.value = incomingConfigured;
      }
      updatePlayerDisplayNameStatus(incomingConfigured);
    }
  } else if (!dashboard.isSavingPlayerName) {
    if (playerNameInput && document.activeElement !== playerNameInput && !dashboard.isPlayerNameEditing) {
      playerNameInput.value = incomingConfigured;
    }
    updatePlayerDisplayNameStatus(incomingConfigured);
  }
  const modeButton = document.getElementById('recognition-mode-toggle');
  if (modeButton) {
    modeButton.dataset.mode = currentMatch.recognitionMode || 'manual';
    modeButton.textContent = modeButton.dataset.mode === 'auto' ? '自动识别：开' : '手动识别';
    modeButton.title = '点击切换手动／自动；结算采集单独控制';
  }
  renderManualCommandReceipt(currentMatch.manualCommandResult || currentMatch.nativeControlResult);
  dashboard.lastCurrentMatch = currentMatch;
  syncWarehouseInstanceReviewFromMatch(currentMatch);
  dashboard.matchState.factsRevision = Number(currentMatch.factsRevision || 0);
  dashboard.matchState.observationFactsRevision = currentMatch.observationFactsRevision ?? null;
  dashboard.matchState.observationProfile = currentMatch.observationProfile || null;
  dashboard.matchState.observationSessionId = currentMatch.observationSessionId || null;
  const visionHealthStatus = document.getElementById('vision-health-status');
  if (visionHealthStatus) {
    const health = currentMatch.visionHealth || {};
    const nativeProfile = currentMatch.observationProfile === 'native-readonly-v1' || health.profile === 'native-readonly-v1';
    const nativeWaiting = nativeProfile && ['native-starting', 'native-ready', 'native-refreshing'].includes(health.stage);
    const needsNativeAction = nativeProfile && health.status !== 'READY' && !nativeWaiting;
    const nativeTelemetry = nativeProfile && health.status === 'READY' && health.freshnessMs != null;
    visionHealthStatus.hidden = nativeProfile ? !(needsNativeAction || nativeWaiting || nativeTelemetry) : health.status !== 'ERROR';
    visionHealthStatus.textContent = visionHealthStatus.hidden ? '' : '识别暂时异常，正在重试；当前显示为上次结果';
    if (!visionHealthStatus.hidden && nativeProfile) {
      if (nativeTelemetry) visionHealthStatus.textContent = `Native WGC · 新鲜度 ${Number(health.freshnessMs).toFixed(0)}ms · 帧 ${health.frameSequence ?? '--'}`;
      else if (health.stage === 'native-ready') visionHealthStatus.textContent = 'Native Host 已就绪，等待首个业务帧';
      else if (health.stage === 'native-refreshing') visionHealthStatus.textContent = `等待当前局的新观察帧：${health.reason || '实时建议暂不可用'}`;
      else if (health.stage === 'native-explicit-start' || health.stage === 'native-stopped') visionHealthStatus.textContent = 'Native 观察未启动，点击开始观察';
      else if (health.stage === 'native-starting') visionHealthStatus.textContent = '正在启动 Native 观察，请保持游戏窗口可见并置前';
      else if (health.stage === 'native-paused') visionHealthStatus.textContent = `Native 观察已暂停：${health.reason || '目标窗口或场景边界变化'}；点击重新开始`;
      else if (health.stage === 'native-error') visionHealthStatus.textContent = `Native 观察异常：${health.reason || '请重新开始观察'}`;
    } else if (!visionHealthStatus.hidden && health.stage === 'process') {
      visionHealthStatus.textContent = '识别进程已退出，点击恢复识别；当前显示为上次结果';
    } else if (!visionHealthStatus.hidden && health.stage === 'starting') {
      visionHealthStatus.textContent = '正在启动识别；当前显示为上次结果';
    }
    const restoreButton = document.getElementById('restore-vision-btn');
    if (restoreButton) {
      restoreButton.hidden = nativeProfile ? !needsNativeAction : visionHealthStatus.hidden || health.stage !== 'process';
      const sameMatchRecovery = nativeProfile
        && health.stage === 'native-paused'
        && ['focus-lost', 'capture-failed', 'observation-frame-timeout'].includes(String(health.reason || ''));
      restoreButton.dataset.resumeSameMatch = sameMatchRecovery ? 'true' : 'false';
      restoreButton.textContent = nativeProfile
        ? (sameMatchRecovery ? '恢复同局观察' : '开始新局观察')
        : '恢复识别';
    }
  }
  const previousMatchId = dashboard.matchState.matchId;

  const matchIdEl = document.getElementById("match-live-id");
  const lifecycleEl = document.getElementById("match-live-lifecycle");
  const completeEl = document.getElementById("match-live-completeness");
  const btnTextEl = document.getElementById("match-live-overlay-btn-text");

  if (matchIdEl) matchIdEl.textContent = currentMatch.matchId || "--";
  if (lifecycleEl) {
    const isFinalized = currentMatch.lifecycleStatus === "FINALIZED";
    lifecycleEl.textContent = isFinalized ? "已完成" : "进行中";
    lifecycleEl.className = `badge ${isFinalized ? "badge-lifecycle is-finalized" : "badge-lifecycle"}`;
  }
  if (completeEl) {
    completeEl.textContent = currentMatch.isComplete ? "事实已就绪" : (currentMatch.hasAnyFact ? "输入待完善" : "未开始输入");
    completeEl.className = `badge ${currentMatch.isComplete ? "badge-admission is-admitted" : "badge-admission is-excluded"}`;
  }
  if (btnTextEl) {
    btnTextEl.textContent = overlayVisible ? "隐藏局内悬浮窗" : "打开局内悬浮窗";
  }

  // Populate options
  if (currentMatch.options) {
    populateMatchOptions(currentMatch.options);
  }
  renderNextMatchPreparation(currentMatch);

  // Environment facts & Form Inputs
  const env = currentMatch.environment || {};
  const facts = {
    ...(currentMatch.publicIntel || {}),
    ...(currentMatch.facts || {}),
  };
  
  const isMissingVal = (v) => !v || v === "未选择" || v === "等待选择会场" || v === "请选择会场" || v === "未知场地" || v === "未知会场" || v === "等待选择宝箱" || v === "请选择宝箱" || v === "未知箱型";

  const incomingVenueId = env.venueId || facts.venueId || null;
  const rawVenue = env.venueName || facts.venue || null;
  const incomingVenue = isMissingVal(rawVenue) ? null : rawVenue;

  const incomingBoxId = env.boxId || facts.boxId || null;
  const rawBox = env.box || facts.box || null;
  const incomingBox = isMissingVal(rawBox) ? null : rawBox;
  const conditionRequirement = currentMatch.solverAdmission?.requirements?.find(item => item.key === "fieldCondition");
  const conditionIsMissing = conditionRequirement?.status === "missing";

  if (currentMatch.matchId !== previousMatchId) {
    dashboard.matchState.matchId = currentMatch.matchId;
    dashboard.matchState.venueId = incomingVenueId;
    dashboard.matchState.venue = incomingVenue;
    dashboard.matchState.boxId = incomingBoxId;
    dashboard.matchState.box = incomingBox;
    dashboard.matchState.fieldCondition = conditionIsMissing ? null : (env.fieldCondition || facts.fieldCondition || "standard");
    dashboard.pendingFieldCondition = null;
    dashboard.pendingFieldConditionReceiptRevision = null;
  } else {
    // Same match: preserve manual inputs across refreshes / null states
    if (incomingVenue) {
      dashboard.matchState.venueId = incomingVenueId;
      dashboard.matchState.venue = incomingVenue;
    } else if (currentMatch.fieldStates?.venue?.status === "cleared") {
      dashboard.matchState.venueId = null;
      dashboard.matchState.venue = null;
    } else if (incomingVenueId && !dashboard.matchState.venueId) {
      dashboard.matchState.venueId = incomingVenueId;
    }

    if (incomingBox) {
      dashboard.matchState.boxId = incomingBoxId;
      dashboard.matchState.box = incomingBox;
    } else if (currentMatch.fieldStates?.box?.status === "cleared") {
      dashboard.matchState.boxId = null;
      dashboard.matchState.box = null;
    } else if (incomingBoxId && !dashboard.matchState.boxId) {
      dashboard.matchState.boxId = incomingBoxId;
    }

    const isFieldCondManual = Boolean(
      currentMatch.fieldStates?.fieldCondition?.source === "manual" ||
      currentMatch.fieldStates?.fieldCondition?.protected
    );
    const incFieldCond = env.fieldCondition || facts.fieldCondition;
    const receipt = currentMatch.manualCommandResult || currentMatch.nativeControlResult || {};
    const receiptRevision = Number(receipt.revision);
    const receiptStatus = String(receipt.status || "").toUpperCase();
    const hasNewConditionReceipt = dashboard.pendingFieldCondition != null
      && Number.isFinite(receiptRevision)
      && receiptRevision > Number(dashboard.pendingFieldConditionReceiptRevision ?? -1)
      && ["ACK", "ACCEPTED", "REJECT", "REJECTED", "ERROR"].includes(receiptStatus);
    if (hasNewConditionReceipt) {
      dashboard.pendingFieldCondition = null;
      dashboard.pendingFieldConditionReceiptRevision = null;
      if (["REJECT", "REJECTED", "ERROR"].includes(receiptStatus)) {
        dashboard.matchState.fieldCondition = facts.fieldCondition || null;
        dashboard.lastSyncedFacts.fieldCondition = dashboard.matchState.fieldCondition;
      }
    }
    if (conditionIsMissing && !isFieldCondManual && dashboard.pendingFieldCondition == null) {
      dashboard.matchState.fieldCondition = null;
    } else if (!isFieldCondManual && incFieldCond && incFieldCond !== "unknown") {
      dashboard.matchState.fieldCondition = incFieldCond;
    } else if (isFieldCondManual && currentMatch.fieldStates?.fieldCondition?.value) {
      dashboard.matchState.fieldCondition = currentMatch.fieldStates.fieldCondition.value;
    }
  }

  dashboard.lastSyncedFacts = dashboard.lastSyncedFacts || {};
  dashboard.lastSyncedFacts.venueId = dashboard.matchState.venueId;
  dashboard.lastSyncedFacts.venue = dashboard.matchState.venue;
  dashboard.lastSyncedFacts.boxId = dashboard.matchState.boxId;
  dashboard.lastSyncedFacts.box = dashboard.matchState.box;
  dashboard.lastSyncedFacts.fieldCondition = dashboard.matchState.fieldCondition;

  if (currentMatch.matchId !== previousMatchId) {
    requestOriginalScreenshots(currentMatch.matchId, "warehouse-originals");
    dashboard.lastSnapshotResult = null;
    ["gold", "red", "purple", "blue", "green", "white"].forEach((rarity) => {
      const input = document.getElementById(`match-input-known-${rarity}`);
      if (input) input.value = "";
    });
  }

  const venueDisplay = document.getElementById("match-venue-display");
  const boxDisplay = document.getElementById("match-box-display");
  const condDisplay = document.getElementById("match-cond-display");

  const venueDisplayName = dashboard.matchState.venue || "请选择会场";
  const boxDisplayName = dashboard.matchState.box || "请选择宝箱";

  if (venueDisplay) venueDisplay.textContent = venueDisplayName;
  if (boxDisplay) boxDisplay.textContent = boxDisplayName;
  if (condDisplay) condDisplay.textContent = env.fieldConditionName || (dashboard.matchState.fieldCondition ? "标准对局" : "待确认规则");

  // Task-flow Header update
  const headingEl = document.getElementById("match-live-heading");
  const ruleTagEl = document.getElementById("match-live-rule-tag");
  const statusBadgeEl = document.getElementById("match-live-status-badge");
  const compTextEl = document.getElementById("match-live-completeness-text");
  const headingVenue = dashboard.matchState.venue || "未选择会场";
  const headingBox = dashboard.matchState.box || "未选择宝箱";
  if (headingEl) headingEl.textContent = `${headingVenue} · ${headingBox}`;
  if (ruleTagEl) ruleTagEl.textContent = env.fieldConditionName || (dashboard.matchState.fieldCondition ? "标准规则" : "待确认规则");
  if (statusBadgeEl) {
    const isFinalized = currentMatch.lifecycleStatus === "FINALIZED";
    statusBadgeEl.textContent = isFinalized ? "已结算" : (currentMatch.isComplete ? "估值已生成" : "正在收集情报");
    statusBadgeEl.className = `badge ${isFinalized ? "badge-lifecycle is-finalized" : "badge-lifecycle"}`;
  }
  if (compTextEl) {
    compTextEl.textContent = currentMatch.isComplete ? "事实已就绪" : (currentMatch.hasAnyFact ? "输入待完善" : "未开始输入");
  }

  if (dashboard.matchState.venueId) {
    updateMatchBoxDropdown(dashboard.matchState.venueId);
  }

  // Numeric & text inputs: do not overwrite while user is typing or if confirmed manually
  const syncField = (id, val, factKey) => {
    const el = document.getElementById(id);
    if (!el || document.activeElement === el) return;
    const fState = factKey ? (currentMatch.fieldStates?.[factKey] || currentMatch.facts?.fieldStates?.[factKey]) : null;
    const isManual = fState && (fState.source === "manual" || fState.protected);
    if (isManual) {
      if (fState.value !== null && fState.value !== undefined) {
        el.value = fState.value;
        if (factKey) dashboard.lastSyncedFacts[factKey] = fState.value;
      }
      return;
    }
    el.value = (val !== null && val !== undefined) ? val : "";
    if (factKey) dashboard.lastSyncedFacts[factKey] = (val !== null && val !== undefined) ? val : null;
  };

  const sparkleEditing = ['match-sparkle-count', 'match-sparkle-names'].some(id => document.activeElement === document.getElementById(id));
  if (currentMatch.matchId !== previousMatchId || !sparkleEditing) {
    document.getElementById('match-sparkle-count').value = facts.sparkle?.transformedOneByOneCount ?? '';
    document.getElementById('match-sparkle-names').value = sparkleNames(facts.sparkle);
    dashboard.lastSyncedFacts.sparkle = facts.sparkle ?? null;
  }
  const sparkleVisible = dashboard.matchState.fieldCondition === 'sparkle';
  document.getElementById('match-sparkle-fields').hidden = !sparkleVisible;
  document.getElementById('match-sparkle-bounds').textContent = sparkleVisible ? sparkleBoundsText(currentMatch.prediction?.evidenceBounds) : '';
  if (currentMatch.matchId !== previousMatchId) {
    document.getElementById("match-input-welfare-received").value = facts.welfareReceived ?? "";
    validateWelfareReceipt("match-input-welfare-received", "match-welfare-error");
  }
  if (currentMatch.matchId !== previousMatchId || document.getElementById("match-input-welfare-received").getAttribute("aria-invalid") !== "true") {
    syncField("match-input-welfare-received", facts.welfareReceived, "welfareReceived");
  }
  document.getElementById("match-session-accounting").textContent = sessionAccountingText(currentMatch.sessionAccounting);
  if (currentMatch.matchId !== previousMatchId) {
    document.getElementById("match-input-private-bid-cap").value = facts.privateBidCap ?? "";
    validateWelfareReceipt("match-input-private-bid-cap", "match-error-private-bid-cap");
  }
  if (document.getElementById("match-input-private-bid-cap").getAttribute("aria-invalid") !== "true") syncField("match-input-private-bid-cap", facts.privateBidCap, "privateBidCap");
  if (currentMatch.matchId !== previousMatchId) {
    document.getElementById("match-input-bid-action-count").value = facts.bidActionCount ?? "";
    validateWelfareReceipt("match-input-bid-action-count", "match-error-bid-action-count");
  }
  if (document.getElementById("match-input-bid-action-count").getAttribute("aria-invalid") !== "true") syncField("match-input-bid-action-count", facts.bidActionCount, "bidActionCount");
  syncField("match-input-q", facts.q, "q");
  syncField("match-input-gold-avg", facts.goldAvg, "goldAvg");
  syncField("match-input-purple-count", facts.purpleCount, "purpleCount");
  syncField("match-input-purple-avg", facts.purpleAvg, "purpleAvg");
  syncField("match-input-blue-count", facts.blueCount, "blueCount");
  syncField("match-input-gold-count", facts.goldCount, "goldCount");
  syncField("match-input-red-count", facts.redCount, "redCount");
  syncField("match-input-total-items", facts.totalItems, "totalItems");
  syncField("match-input-total-grid", facts.totalGrid, "totalGrid");
  const displayCostField = (id, val) => {
    const el = document.getElementById(id);
    if (el) {
      if (val !== null && val !== undefined && Number(val) > 0) {
        el.textContent = `系统计算 ${formatCurrency(val)}`;
        el.style.color = "#38bdf8";
      } else {
        el.textContent = "未知 / 暂无自动数据";
        el.style.color = "#94a3b8";
      }
    }
  };
  displayCostField("match-display-intel-cost", facts.intelCost);
  displayCostField("match-display-other-cost", facts.otherCost);
  displayCostField("match-display-future-cost", facts.futureIncrementalCost);

  syncField("match-input-gold-grid", facts.goldGrid, "goldGrid");
  syncField("match-input-purple-grid", facts.purpleGrid, "purpleGrid");
  syncField("match-input-white-count", facts.whiteCount, "whiteCount");
  syncField("match-input-white-avg", facts.whiteAvg, "whiteAvg");
  syncField("match-input-white-grid", facts.whiteGrid, "whiteGrid");
  syncField("match-input-green-count", facts.greenCount, "greenCount");
  syncField("match-input-green-avg", facts.greenAvg, "greenAvg");
  syncField("match-input-green-grid", facts.greenGrid, "greenGrid");
  syncField("match-input-blue-avg", facts.blueAvg, "blueAvg");
  syncField("match-input-blue-grid", facts.blueGrid, "blueGrid");
  syncField("match-input-red-grid", facts.redGrid, "redGrid");


  // Synchronize Known Items Chips with facts
  syncKnownChipsFromFacts(facts);

  // Intelligence & 6-Rarity Matrix
  const lobby = currentMatch.lobby || {};
  const lobbyCharEl = document.getElementById("match-lobby-character");
  const lobbyToolEl = document.getElementById("match-lobby-tool");
  const lobbyEntryEl = document.getElementById("match-lobby-entry");
  if (lobbyCharEl) lobbyCharEl.textContent = lobby.character || "未识别/默认";
  if (lobbyToolEl) lobbyToolEl.textContent = lobby.lobbyToolGroup || "标准仪器";
  if (lobbyEntryEl) lobbyEntryEl.textContent = formatCurrency(lobby.entryCost);

  // Missing Facts Guidance
  const missingValList = currentMatch.missingValueFacts || [];
  const missingDecList = currentMatch.missingDecisionFacts || [];
  const missingValRow = document.getElementById("match-missing-val-row");
  const missingValBox = document.getElementById("match-missing-val-container");
  const missingDecRow = document.getElementById("match-missing-dec-row");
  const missingDecBox = document.getElementById("match-missing-dec-container");

  if (missingValRow && missingValBox) {
    missingValRow.hidden = missingValList.length === 0;
    missingValBox.innerHTML = missingValList.map(t => `<span class="missing-tag">${t}</span>`).join(" ");
  }
  if (missingDecRow && missingDecBox) {
    missingDecRow.hidden = missingDecList.length === 0;
    missingDecBox.innerHTML = missingDecList.map(t => `<span class="missing-tag">${t}</span>`).join(" ");
  }
  renderSolverAdmissionStatus(currentMatch);

  // Adaptive Snapshot Button State (Without Jumpy Layout)
  const snapBtn = document.getElementById("match-btn-snapshot");
  const snapLabel = document.getElementById("match-snapshot-btn-label");
  const snapHintText = document.getElementById("match-snapshot-status-text");
  if (snapBtn && snapLabel) {
    if (snapHintText) snapHintText.style.color = "";
    let factCount = 0;
    if (facts.venueId || env.venueId) factCount++;
    if (facts.boxId || env.boxId) factCount++;
    if (facts.q != null) factCount++;
    if (facts.purpleCount != null) factCount++;
    if (facts.goldAvg != null) factCount++;
    if (facts.purpleAvg != null) factCount++;
    if (facts.knownGold || facts.knownRed || facts.knownPurple) factCount++;

    const lastRes = dashboard.lastSnapshotResult;
    const isRecognizing = lastRes && (lastRes.status === "recognizing" || lastRes.status === "busy");

    if (isRecognizing) {
      snapBtn.disabled = true;
      snapBtn.className = "btn-snapshot-action is-recognizing";
      snapLabel.textContent = "识别中...";
      if (snapHintText) {
        snapHintText.textContent = lastRes.summary || "正在快照识别游戏画面...";
        snapHintText.style.color = "var(--text-muted)";
      }
    } else {
      snapBtn.disabled = false;
      if (currentMatch.lifecycleStatus === "FINALIZED") {
        snapBtn.className = "btn-snapshot-action";
        snapLabel.textContent = "快照识别 (Capture)";
        if (snapHintText) snapHintText.textContent = "本局对局已完成结算";
      } else if (factCount >= 3 || (currentMatch.prediction && currentMatch.prediction.hasSnapshot)) {
        snapBtn.className = "btn-snapshot-action";
        snapLabel.textContent = "再次识别";
        if (snapHintText) snapHintText.textContent = `已获取 ${factCount}/7 项情报 · 可再次快照补充`;
      } else {
        snapBtn.className = "btn-snapshot-action is-prominent";
        snapLabel.textContent = "快照识别 (Capture)";
        if (snapHintText) snapHintText.textContent = "看到游戏情报卡片时点击，自动提取对局事实";
      }
      if (snapHintText && lastRes) {
        snapHintText.textContent = lastRes.summary || (lastRes.ok ? "✓ 快照识别成功" : "⚠️ 未识别到对局事实");
        snapHintText.style.color = lastRes.ok ? "#34d399" : "#f87171";
      }
    }
  }

  // 6-Rarity Matrix
  const qObj = currentMatch.qualities || {};
  const setRarityCard = (rarity, data) => {
    const countEl = document.getElementById(`match-q-${rarity}-count`);
    const avgEl = document.getElementById(`match-q-${rarity}-avg`);
    if (countEl) countEl.textContent = (data && data.count !== null && data.count !== undefined) ? `${data.count} 件` : "--";
    if (avgEl) {
      if (rarity === "red") {
        avgEl.textContent = (data && data.knownItems) ? `约束: ${data.knownItems}` : "件数: --";
      } else {
        avgEl.textContent = (data && data.avg !== null && data.avg !== undefined) ? `均价: ${formatCurrency(data.avg)}` : "均价: --";
      }
    }
  };
  setRarityCard("white", qObj.white);
  setRarityCard("green", qObj.green);
  setRarityCard("blue", qObj.blue);
  setRarityCard("purple", qObj.purple);
  setRarityCard("gold", qObj.gold);
  setRarityCard("red", qObj.red);

  const costSummary = document.getElementById("match-cost-summary");
  if (costSummary) costSummary.textContent = currentMatch.costSummary || "费用待确认";

  // Prediction & Decision Lines
  const pred = currentMatch.prediction;
  const lines = currentMatch.decisionLines || {};
  const emptyCard = document.getElementById("match-live-prediction-empty");
  const contentCard = document.getElementById("match-live-prediction-content");

  if (pred && pred.hasSnapshot) {
    if (emptyCard) emptyCard.hidden = true;
    if (contentCard) contentCard.hidden = false;

    const p20El = document.getElementById("match-live-p20");
    const p50El = document.getElementById("match-live-p50");
    const estimateLabel = document.getElementById("match-live-estimate-label");
    const p50SubEl = document.getElementById("match-live-p50-sub");
    const p80El = document.getElementById("match-live-p80");
    const recEl = document.getElementById("match-live-recommended-max");
    const recLabelEl = document.getElementById("match-live-rec-label");
    const p20LabelEl = document.getElementById("match-live-p20-label");
    const p50SubLabelEl = document.getElementById("match-live-p50-sub-label");
    const p80LabelEl = document.getElementById("match-live-p80-label");

    const isP80Null = pred.p80 === null || pred.p80 === undefined;
    const hasStructuralCenter = (pred.structuralCenter !== null && pred.structuralCenter !== undefined) || (pred.ev !== null && pred.ev !== undefined);
    const structCenter = pred.structuralCenter != null ? pred.structuralCenter : pred.ev;
    const structMin = pred.structuralFeasibleMin != null ? pred.structuralFeasibleMin : lines.structuralFeasibleMin;
    const structMax = pred.structuralFeasibleMax != null ? pred.structuralFeasibleMax : lines.structuralFeasibleMax;
    const structRefBid = pred.structuralReferenceBid != null ? pred.structuralReferenceBid : lines.structuralReferenceBid;

    const profitEl = document.getElementById("match-live-expected-profit");
    const expectedProfit = lines.expectedProfit;
    if (profitEl) profitEl.textContent = "预期盈亏（当前叫价，P50扣整局成本）：" + (typeof expectedProfit !== "number" || !Number.isFinite(expectedProfit) || pred.mode !== "full_shadow" ? "—" : expectedProfit === 0 ? "0（保本）" : (expectedProfit > 0 ? "+" : "") + expectedProfit.toLocaleString("zh-CN"));
    const targetLineEl = document.getElementById("match-live-target-line");
    const globalLineEl = document.getElementById("match-live-global-line");
    const marginalLineEl = document.getElementById("match-live-marginal-line");
    const actBadge = document.getElementById("match-live-action-badge");
    const actTitle = document.getElementById("match-live-action-title");
    const actReason = document.getElementById("match-live-action-reason");
    const supportBadge = document.getElementById("match-live-support-badge");

    if (isP80Null && hasStructuralCenter) {
      if (estimateLabel) estimateLabel.textContent = "非概率结构估值中枢";
      if (p20LabelEl) p20LabelEl.textContent = "可行下界";
      if (p50SubLabelEl) p50SubLabelEl.textContent = "估值中枢";
      if (p80LabelEl) p80LabelEl.textContent = "市场P80";
      if (recLabelEl) recLabelEl.textContent = "结构建议上限 (非正式)";

      if (p20El) p20El.textContent = structMin != null ? formatCurrency(structMin) : "--";
      if (p50El) p50El.textContent = formatCurrency(structCenter);
      if (p50SubEl) p50SubEl.textContent = formatCurrency(structCenter);
      if (p80El) p80El.textContent = "暂无(0个可比历史样本)";
      if (recEl) recEl.textContent = structRefBid != null ? formatCurrency(structRefBid) : (pred.recommendedMax != null ? formatCurrency(pred.recommendedMax) : "--");
    } else {
      if (estimateLabel) estimateLabel.textContent = pred.estimateLabel || "整仓预测中位 (P50)";
      if (p20LabelEl) p20LabelEl.textContent = "保守 (P20)";
      if (p50SubLabelEl) p50SubLabelEl.textContent = "中位基准 (P50)";
      if (p80LabelEl) p80LabelEl.textContent = "乐观 (P80)";
      if (recLabelEl) recLabelEl.textContent = "建议最高出价";

      if (p20El) p20El.textContent = formatCurrency(pred.p20);
      if (p50El) {
        if (pred.solverStatus === "no-match") {
          p50El.textContent = "无可行解";
        } else if (pred.p50 !== null && pred.p50 !== undefined) {
          p50El.textContent = formatCurrency(pred.p50);
        } else if (pred.referenceValue !== null && pred.referenceValue !== undefined) {
          p50El.textContent = formatCurrency(pred.referenceValue);
        } else if (pred.actionReason === "CONSTRAINTS_INFEASIBLE" || (typeof pred.actionReason === "string" && pred.actionReason.includes("冲突"))) {
          p50El.textContent = "无可行解";
        } else {
          p50El.textContent = "--";
        }
      }
      if (p50SubEl) {
        p50SubEl.textContent = (pred.p50 !== null && pred.p50 !== undefined) ? formatCurrency(pred.p50) : "--";
      }
      if (p80El) p80El.textContent = isP80Null ? "暂无(0个可比历史样本)" : formatCurrency(pred.p80);
      if (recEl) recEl.textContent = formatCurrency(pred.recommendedMax);
    }

    if (targetLineEl) targetLineEl.textContent = formatCurrency(lines.targetLine);
    if (globalLineEl) globalLineEl.textContent = formatCurrency(lines.globalLine);
    if (marginalLineEl) marginalLineEl.textContent = formatCurrency(lines.marginalLine);

    const directive = pred.actionDirective;
    const actionLabel = pred.solverStatus === "no-match" ? "约束冲突" : directive === "PASS" ? "建议放弃" : directive === "BID" ? "可考虑出价" : (!directive || directive === "WAIT") ? "等待情报" : directive;
    if (actBadge) {
      actBadge.textContent = actionLabel;
      actBadge.className = `advice-directive-badge ${directive === "PASS" ? "is-pass" : directive === "BID" ? "is-bid" : "is-wait"}`;
    }
    if (actTitle) {
      actTitle.textContent = `行动建议：${actionLabel}`;
    }
    if (actReason) {
      actReason.textContent = pred.actionReason || "等待有效出价建议";
    }
    if (supportBadge) {
      const modeText = pred.mode === "full_shadow" ? "历史先验支持" : pred.mode === "partial_shadow" ? "部分历史覆盖" : "基础结构推断";
      const ratio = pred.coverageRatio != null ? ` (${Math.round(pred.coverageRatio * 100)}%)` : "";
      supportBadge.textContent = `${modeText}${ratio}`;
      supportBadge.className = `badge badge-admission ${pred.mode === "full_shadow" ? "is-admitted" : "is-excluded"}`;
    }
  } else {
    if (emptyCard) emptyCard.hidden = false;
    if (contentCard) contentCard.hidden = true;
  }

  // Update Overview Page Card
  const overviewActiveCard = document.getElementById("overview-active-card");
  const overviewEmptyCard = document.getElementById("overview-empty-card");
  const overviewMatchTitle = document.getElementById("overview-match-title");
  const overviewMatchRule = document.getElementById("overview-match-rule");
  const overviewMatchIntel = document.getElementById("overview-match-intel-count");
  const overviewMatchP50 = document.getElementById("overview-match-p50");
  const overviewMatchRecMax = document.getElementById("overview-match-rec-max");
  const overviewMatchLifecycle = document.getElementById("overview-match-lifecycle");

  const hasActiveDraft = Boolean(currentMatch && (currentMatch.hasAnyFact || env.venueId || facts.venueId || facts.q !== null || currentMatch.isComplete));
  if (overviewActiveCard && overviewEmptyCard) {
    overviewActiveCard.hidden = !hasActiveDraft;
    overviewEmptyCard.hidden = hasActiveDraft;
  }
  if (hasActiveDraft) {
    if (overviewMatchTitle) overviewMatchTitle.textContent = `${venueDisplayName} · ${boxDisplayName}`;
    if (overviewMatchRule) overviewMatchRule.textContent = env.fieldConditionName || "标准规则";
    if (overviewMatchLifecycle) {
      overviewMatchLifecycle.textContent = currentMatch.lifecycleStatus === "FINALIZED" ? "已完成" : "进行中";
    }
    let factCount = 0;
    if (facts.venueId || env.venueId) factCount++;
    if (facts.boxId || env.boxId) factCount++;
    if (facts.q != null) factCount++;
    if (facts.purpleCount != null) factCount++;
    if (facts.goldAvg != null) factCount++;
    if (facts.purpleAvg != null) factCount++;
    if (facts.knownGold || facts.knownRed || facts.knownPurple) factCount++;
    if (overviewMatchIntel) overviewMatchIntel.textContent = `已获取 ${factCount}/7 项情报`;
    if (overviewMatchP50) overviewMatchP50.textContent = (pred && pred.p50 != null) ? formatCurrency(pred.p50) : "--";
    if (overviewMatchRecMax) overviewMatchRecMax.textContent = (pred && pred.recommendedMax != null) ? formatCurrency(pred.recommendedMax) : "--";
  }

  // Section D: Explainability & Candidate Space
  const exp = currentMatch.explainability || {};
  const expCandGsEl = document.getElementById("match-exp-candidate-gs");
  const expStateCountEl = document.getElementById("match-exp-state-count");
  const expHardFloorEl = document.getElementById("match-exp-hard-floor");
  const expTheoBoundsEl = document.getElementById("match-exp-theo-bounds");
  const expGoldInferEl = document.getElementById("match-exp-gold-inference");
  const expGoldValEl = document.getElementById("match-exp-val-gold");
  const expPurpleValEl = document.getElementById("match-exp-val-purple");
  const expRedValEl = document.getElementById("match-exp-val-red");
  const expLowValEl = document.getElementById("match-exp-val-low");

  if (expCandGsEl) expCandGsEl.textContent = (exp.candidateGs && exp.candidateGs.length) ? JSON.stringify(exp.candidateGs) : "--";
  if (expStateCountEl) expStateCountEl.textContent = exp.candidateStateCount ? `${exp.candidateStateCount} 个可行状态` : "--";
  if (expHardFloorEl) expHardFloorEl.textContent = formatCurrency(exp.hardFloor);
  if (expTheoBoundsEl) expTheoBoundsEl.textContent = (exp.theoreticalMin != null && exp.theoreticalMax != null) ? `${formatCurrency(exp.theoreticalMin)} ~ ${formatCurrency(exp.theoreticalMax)}` : "--";
  if (expGoldInferEl) {
    if (typeof exp.goldInference === "string") {
      expGoldInferEl.textContent = exp.goldInference;
    } else if (exp.goldInference && typeof exp.goldInference === "object") {
      expGoldInferEl.textContent = JSON.stringify(exp.goldInference);
    } else {
      expGoldInferEl.textContent = facts.goldAvg ? `均价 ${formatCurrency(facts.goldAvg)} 驱动` : "暂无";
    }
  }
  const breakdown = exp.componentBreakdown || {};
  if (expGoldValEl) expGoldValEl.textContent = formatCurrency(breakdown.gold);
  if (expPurpleValEl) expPurpleValEl.textContent = formatCurrency(breakdown.purple);
  if (expRedValEl) expRedValEl.textContent = formatCurrency(breakdown.red);
  if (expLowValEl) expLowValEl.textContent = formatCurrency(breakdown.lowTier);

  // Section E: Bidding & Seats
  const freeIntel = document.getElementById("match-free-intel-status");
  freeIntel.hidden = !currentMatch.freeIntelStatus;
  freeIntel.textContent = currentMatch.freeIntelStatus?.message || "";
  const bidding = currentMatch.bidding || {};
  document.getElementById("match-dark-controls").hidden = !bidding.hiddenBids && !["match-input-private-bid-cap", "match-input-bid-action-count"].some(id => document.getElementById(id).getAttribute("aria-invalid") === "true");

  // Section F: Settlement & Warehouse
  const settle = currentMatch.settlement;
  const settleStatusText = document.getElementById("match-settle-status-text");
  const settleClearing = document.getElementById("match-settle-clearing");
  const settleActual = document.getElementById("match-settle-actual");
  const settleProfit = document.getElementById("match-settle-profit");
  const settleWinner = document.getElementById("match-settle-winner");

  if (settle) {
    if (settleStatusText) settleStatusText.textContent = settle.settlementFinalized ? "已完成记账" : (settle.settlementReady ? "就绪待审查" : "已登记");
    if (settleClearing) settleClearing.textContent = formatCurrency(settle.clearingPrice);
    if (settleActual) settleActual.textContent = formatCurrency(settle.actualTotal);
    if (settleProfit) settleProfit.textContent = formatSettlementProfit(settle);
    if (settleWinner) settleWinner.textContent = settle.winner || "--";
  } else {
    if (settleStatusText) settleStatusText.textContent = "未结算";
    if (settleClearing) settleClearing.textContent = "--";
    if (settleActual) settleActual.textContent = "--";
    if (settleProfit) settleProfit.textContent = "--";
    if (settleWinner) settleWinner.textContent = "--";
  }

  const wh = currentMatch.warehouse || {};
  const whStatusBadge = document.getElementById("match-wh-status-badge");
  const whCount = document.getElementById("match-wh-count");
  if (whStatusBadge) {
    whStatusBadge.textContent = wh.status === "synced" ? "已同步" : "未录入";
    whStatusBadge.className = `badge ${wh.status === "synced" ? "badge-admission is-admitted" : "badge-admission is-excluded"}`;
  }
  if (whCount) whCount.textContent = `${wh.itemCount || 0} 件 (${wh.exactCount || 0} 确诊)`;

  renderWarehouseSlots(wh, currentMatch);

  // Section G: History Trace Navigation
  const navIdEl = document.getElementById("match-nav-match-id");
  if (navIdEl) navIdEl.textContent = currentMatch.matchId || "--";
}

function renderWarehouseCapture(capture) {
  const slot = document.getElementById("warehouse-capture-slot");
  const button = document.getElementById("warehouse-capture-toggle");
  const message = document.getElementById("warehouse-capture-message");
  if (!slot || !button) return;
  const available = Boolean(capture && capture.available);
  slot.hidden = false;
  slot.dataset.available = available ? "true" : "false";

  const state = String((capture && capture.state) || (available ? "IDLE" : "DRIVER_NOT_CONFIGURED"));
  const running = Boolean(capture && capture.stopAvailable);
  slot.dataset.state = state;

  button.disabled = !available && !running;
  button.textContent = running ? "停止采集" : "采集完整仓库";

  if (message) {
    message.textContent = (capture && capture.message) || "";
  }

  if (!available || running) {
    const confirm = document.getElementById("warehouse-capture-confirm");
    if (confirm) confirm.hidden = true;
    if (!available) {
      dashboard.warehouseArmingToken = null;
    }
  }

  const manualControls = document.getElementById("warehouse-manual-controls");
  const manualStartBtn = document.getElementById("warehouse-manual-start-btn");
  const manualPageCounter = document.getElementById("warehouse-manual-page-counter");
  const manualMessage = document.getElementById("warehouse-manual-message");
  const manualConfirm = document.getElementById("warehouse-manual-confirm");

  if (capture && capture.state === "MANUAL_CAPTURING") {
    if (manualControls) manualControls.hidden = false;
    if (manualStartBtn) manualStartBtn.hidden = true;
    if (manualConfirm) manualConfirm.hidden = true;
    if (manualPageCounter) manualPageCounter.textContent = `已采集 ${capture.segmentCount || 0} 页`;
    if (manualMessage) manualMessage.textContent = capture.message || "";
  } else {
    if (manualControls) manualControls.hidden = true;
    if (manualStartBtn) manualStartBtn.hidden = false;
    if (manualMessage && capture && capture.message && (capture.state === "ALIGNING" || capture.state === "COMPLETE" || capture.state === "ERROR")) {
      manualMessage.textContent = capture.message;
    }
  }

  const review = document.getElementById("warehouse-identity-review");
  const fingerprint = capture && capture.packetFingerprint ? String(capture.packetFingerprint) : "";
  if (review && capture && capture.packetAvailable && !dashboard.historicalWarehouseReview && dashboard.currentView === "match") {
    if (review.dataset.fingerprint !== fingerprint) {
      postNative("warehouse_identity_review", { op: "open" });
      review.dataset.fingerprint = fingerprint;
    }
  } else if (review && (!capture || !capture.packetAvailable)) {
    review.dataset.fingerprint = "";
  }
}

function wirEscape(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderWarehouseIdentityReview(view) {
  if (dashboard.historicalWarehouseReview && view?.recordStableKey &&
      view.recordStableKey !== dashboard.historicalWarehouseReview) return;
  const panel = document.getElementById("warehouse-identity-review");
  if (!panel) return;
  const available = Boolean(view && view.available);
  panel.hidden = !available;
  if (!available) {
    dashboard.warehouseReview = view || { available: false };
    return;
  }
  const coverage = document.getElementById("wir-coverage");
  const caption = document.getElementById("wir-coverage-caption");
  const progress = document.getElementById("wir-progress");
  const trackPos = document.getElementById("wir-track-pos");
  const persist = document.getElementById("wir-persist");
  const message = document.getElementById("wir-message");
  const geom = document.getElementById("wir-geom");
  const draft = document.getElementById("wir-draft");
  const resolution = document.getElementById("wir-resolution");
  if (coverage) {
    if (view.coverageStatus === "COMPLETE") coverage.textContent = "仓库滚动覆盖完整";
    else if (view.coverageStatus === "PARTIAL") coverage.textContent = "只审阅已看到的藏品，不代表整仓完整";
    else coverage.textContent = "覆盖未就绪";
  }
  if (caption) caption.textContent = view.coverageCaption || "";
  if (progress) progress.textContent = `已处理 ${view.processedCount || 0} / ${view.trackCount || 0} · 未处理 ${view.unresolvedCount || 0}`;
  if (trackPos) trackPos.textContent = `第 ${view.trackIndex || 0} / ${view.trackCount || 0} 件`;
  const persistText = view.persistenceCaption || (view.persisted ? "已写入本局记录" : "尚未写入历史记录");
  if (persist) persist.textContent = persistText;
  if (message) {
    const extra = view.persistMessage || view.message || "";
    message.textContent = extra && extra !== persistText ? extra : "";
  }
  if (geom) {
    const shape = view.clipped ? "裁断" : "完整";
    geom.textContent = `${view.geometryStatus || ""} · ${shape}${view.pixelOnly ? " · PIXEL_ONLY" : ""}`;
  }
  if (draft) draft.textContent = view.draftAction ? `本件草稿：${view.draftAction}（点击不等于确认）` : "已选候选尚未确认";
  if (resolution) {
    if (view.artifactReady) {
      resolution.textContent = `审阅 ${view.reviewCompletion || ""} · 身份 ${view.identityResolution || ""}`;
    } else {
      resolution.textContent = "";
    }
  }
  const saveBtn = document.getElementById("wir-save");
  const saveConfirm = document.getElementById("wir-save-confirm");
  const canSave = Boolean(view.artifactReady && view.persistenceAvailable && !view.persisted && view.persistStatus !== "CONFLICT");
  if (saveBtn) {
    saveBtn.textContent = "写入本局记录";
    if (view.persisted || view.persistStatus === "CONFLICT") {
      saveBtn.hidden = true;
      saveBtn.disabled = true;
    } else {
      saveBtn.hidden = !canSave;
      saveBtn.disabled = !canSave;
    }
  }
  if (saveConfirm) {
    if (view.persisted || !canSave) dashboard.wirSaveConfirmOpen = false;
    saveConfirm.hidden = !dashboard.wirSaveConfirmOpen;
  }
  const img = document.getElementById("wir-hero-img");
  const missing = document.getElementById("wir-hero-missing");
  const best = view.bestObservation || {};
  if (img && missing) {
    if (best.imageAvailable && best.imageDataUrl) {
      img.src = best.imageDataUrl;
      img.hidden = false;
      missing.hidden = true;
    } else {
      img.removeAttribute("src");
      img.hidden = true;
      missing.hidden = false;
    }
  }
  const thumbs = document.getElementById("wir-thumbs");
  if (thumbs) {
    const usable = (view.otherObservations || []).filter((item) => item.imageAvailable && item.imageDataUrl && item.observationId);
    thumbs.innerHTML = usable.map((item) =>
      `<img data-obs="${wirEscape(item.observationId)}" alt="其他证据" src="${item.imageDataUrl}">`
    ).join("");
  }
  const reasonBox = document.getElementById("wir-reason-box");
  const overrideSelect = document.getElementById("wir-override-reason");
  if (reasonBox && !dashboard.pendingReasonKind) reasonBox.hidden = true;
  if (overrideSelect) overrideSelect.hidden = dashboard.pendingReasonKind !== "override";
  const box = document.getElementById("wir-candidates");
  if (box) {
    box.innerHTML = (view.candidates || []).map((item) => `
      <div class="wir-candidate ${item.selected ? "is-selected" : ""}" data-candidate="${wirEscape(item.candidateId)}">
        <strong>${wirEscape(item.candidateName || "待辨认")}</strong>
        ${item.requiresOverride ? '<div>图鉴尺寸待核对，确认时需填写人工核准理由</div>' : ''}
        <div>${wirEscape(item.geometryText || "")} · ${wirEscape(item.identityStatus || "CANDIDATE_ONLY")}</div>
      </div>`).join("") || "<div class=\"wir-missing\">无几何候选</div>";
  }
  const hits = document.getElementById("wir-search-hits");
  if (hits) {
    hits.innerHTML = (view.overrideHits || []).map((item) => `
      <div class="wir-hit ${item.selected ? "is-selected" : ""}" data-override="${wirEscape(item.catalogId)}">
        ${wirEscape(item.candidateName || "待辨认")}
        ${item.quarantined ? "<span class=\"wir-quarantine\">QUARANTINED GEOMETRY</span>" : ""}
      </div>`).join("");
  }
  const legal = Boolean(view.hasLegalEvidence);
  const processed = Boolean(view.draftAction);
  const confirmBtn = document.getElementById("wir-confirm-candidate");
  const overrideBtn = document.getElementById("wir-override");
  const outBtn = document.getElementById("wir-out");
  const excludeBtn = document.getElementById("wir-exclude");
  if (confirmBtn) confirmBtn.disabled = !legal || processed;
  if (overrideBtn) {
    overrideBtn.disabled = !legal || processed;
    overrideBtn.textContent = dashboard.pendingOverrideConfirm ? "明确覆盖确认" : "覆盖确认";
  }
  if (outBtn) outBtn.disabled = !legal || processed;
  if (excludeBtn) excludeBtn.disabled = !legal || processed;
  const filter = document.getElementById("wir-filter-unresolved");
  if (filter) filter.checked = Boolean(view.filterUnresolved);
  dashboard.warehouseReview = view;
}

function postWarehouseReview(op, extra = {}) {
  const view = dashboard.warehouseReview || {};
  postNative("warehouse_identity_review", {
    op,
    sessionId: view.sessionId,
    packetFingerprint: view.packetFingerprint,
    ...extra
  });
}

function postWarehousePersist() {
  const view = dashboard.warehouseReview || {};
  dashboard.pendingWarehouseHistoryRefresh = dashboard.historicalWarehouseReview
    ? { recordId: dashboard.historicalWarehouseReview, sessionId: view.sessionId } : null;
  postNative("warehouse_identity_review", {
    op: "persist",
    sessionId: view.sessionId,
    packetFingerprint: view.packetFingerprint
  });
}

function wirRevealReason(kind) {
  const box = document.getElementById("wir-reason-box");
  const select = document.getElementById("wir-override-reason");
  const exception = document.getElementById("wir-exception");
  dashboard.pendingReasonKind = kind;
  if (exception) exception.open = true;
  if (box) box.hidden = false;
  if (select) select.hidden = kind !== "override";
}

function renderPinState(pinned) {
  dashboard.mainPinned = Boolean(pinned);
  const control = document.getElementById("pin-control");
  const status = document.getElementById("pin-status");
  const button = document.getElementById("pin-toggle");
  if (control) control.dataset.pinned = String(dashboard.mainPinned);
  if (status) status.textContent = dashboard.mainPinned ? "窗口置顶开启" : "窗口置顶关闭";
  if (button) {
    button.textContent = dashboard.mainPinned ? "取消置顶" : "开启置顶";
    button.disabled = false;
  }
}

function renderOverlayState(visible) {
  dashboard.overlayVisible = Boolean(visible);
  const control = document.getElementById("overlay-control");
  const status = document.getElementById("overlay-status");
  const button = document.getElementById("overlay-toggle");
  if (control) control.dataset.visible = String(dashboard.overlayVisible);
  if (status) status.textContent = dashboard.overlayVisible ? "Overlay 已显示" : "Overlay 已隐藏";
  if (button) {
    button.textContent = dashboard.overlayVisible ? "隐藏" : "显示";
    button.disabled = false;
  }
}

function setBridgeState(kind, label) {
  const status = document.querySelector(".topbar-status");
  if (status) {
    status.classList.toggle("is-ready", kind === "ready");
    status.classList.toggle("is-error", kind === "error");
  }
  if (dashboard.overlayVisible === null || kind === "error") {
    document.getElementById("overlay-status").textContent = label;
  }
}

function setHistorySource(source) {
  dashboard.historyFilter.source = source;
  document.querySelectorAll(".filter-source").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.source === source);
  });
  applyHistoryFilters();
}

function closeAllDropdowns() {
  document.querySelectorAll(".custom-dropdown").forEach((d) => {
    d.classList.remove("is-open");
    const menu = d.querySelector(".dropdown-menu");
    const trigger = d.querySelector(".dropdown-trigger");
    if (menu) menu.hidden = true;
    if (trigger) trigger.setAttribute("aria-expanded", "false");
  });
}

function initCustomDropdowns() {
  document.querySelectorAll(".custom-dropdown").forEach((dropdown) => {
    const trigger = dropdown.querySelector(".dropdown-trigger");
    const menu = dropdown.querySelector(".dropdown-menu");
    const label = trigger ? (trigger.querySelector(".dropdown-label") || trigger.querySelector("span:first-child")) : null;
    if (!trigger || !menu) return;

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = dropdown.classList.contains("is-open");
      closeAllDropdowns();
      if (!isOpen) {
        dropdown.classList.add("is-open");
        menu.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
      }
    });

    menu.addEventListener("click", (e) => {
      const item = e.target.closest(".dropdown-item");
      if (!item) return;
      e.stopPropagation();
      const value = item.dataset.value;
      const text = item.textContent;

      menu.querySelectorAll(".dropdown-item").forEach((i) => i.classList.remove("is-selected"));
      item.classList.add("is-selected");
      if (label) label.textContent = text;

      closeAllDropdowns();

      if (dropdown.id === "dropdown-filter-source") {
        dashboard.historyFilter.source = value;
        applyHistoryFilters();
      } else if (dropdown.id === "dropdown-filter-outcome") {
        dashboard.historyFilter.outcome = value;
        applyHistoryFilters();
      } else if (dropdown.id === "dropdown-filter-evidence") {
        dashboard.historyFilter.evidence = value;
        applyHistoryFilters();
      } else if (dropdown.id === "dropdown-filter-admission") {
        dashboard.historyFilter.admission = value;
        applyHistoryFilters();
      } else if (dropdown.id === "dropdown-filter-time") {
        dashboard.historyFilter.timeRange = value;
        const customBox = document.getElementById("history-custom-dates");
        if (customBox) customBox.hidden = (value !== "custom");
        applyHistoryFilters();
      } else if (dropdown.id === "match-venue-dropdown") {
        setMatchVenue(item.dataset.venueId, item.dataset.venueName);
      } else if (dropdown.id === "match-box-dropdown") {
        if (item.dataset.restoreAuto) {
          restoreMatchAuto(item.dataset.restoreAuto.split(","));
        } else {
          setMatchBox(item.dataset.boxId, item.dataset.boxName);
        }
      } else if (dropdown.id === "match-cond-dropdown") {
        setMatchCondition(item.dataset.condId, item.dataset.condName);
      } else if (dropdown.id === "next-match-venue-dropdown") {
        setNextMatchPreparationVenue(item.dataset.venueId, item.dataset.venueName);
      } else if (dropdown.id === "next-match-box-dropdown") {
        setNextMatchPreparationBox(item.dataset.boxId, item.dataset.boxName);
      } else if (dropdown.id === "next-match-cond-dropdown") {
        setNextMatchPreparationCondition(item.dataset.condId, item.dataset.condName);
      }
    });
  });

  document.addEventListener("click", () => {
    closeAllDropdowns();
  });
}

function onFilterControlChanged() {
  const search = document.getElementById("filter-search");
  const debug = document.getElementById("filter-debug");
  if (search) dashboard.historyFilter.search = search.value.trim();
  if (debug) dashboard.historyFilter.debug = debug.checked;
  applyHistoryFilters();
}

// ---------------------------------------------------------------- legacy archive
function toggleLegacyArchive() {
  const pane = document.getElementById("legacy-archive-pane");
  const collapsed = pane.hidden;
  pane.hidden = !collapsed;
  if (collapsed && dashboard.legacyRecords === null) loadLegacyArchive();
}

function loadLegacyArchive() {
  const loading = document.getElementById("legacy-loading");
  const empty = document.getElementById("legacy-empty");
  if (loading) loading.hidden = false;
  if (empty) empty.hidden = true;
  postNative("request_legacy_archive");
}

function renderLegacyArchive(response) {
  const loading = document.getElementById("legacy-loading");
  if (loading) loading.hidden = true;
  const empty = document.getElementById("legacy-empty");
  if (!response || response.ok !== true) {
    if (empty) {
      empty.hidden = false;
      empty.textContent = (response && response.message) || "旧版归档不可用";
      empty.innerHTML = `<div class="empty-title">${(response && response.message) || "旧版归档不可用"}</div>
        <button type="button" class="btn-legacy-select" id="legacy-select-file-btn">选择旧历史文件 (.json)</button>`;
      const btn = document.getElementById("legacy-select-file-btn");
      if (btn) btn.addEventListener("click", selectLegacySource);
    }
    return;
  }
  const list = document.getElementById("legacy-list");
  const info = document.getElementById("legacy-source-info");
  const records = response.records || [];
  dashboard.legacyRecords = records;
  applyHistoryFilters();
  if (info) {
    const src = response.source || {};
    info.textContent = src.available ? `${src.recordCount} 条 · ${src.fileSha256 ? src.fileSha256.slice(0, 8) : ""}` : "文件缺失";
  }
  if (records.length === 0) {
    if (empty) empty.hidden = false;
    list.innerHTML = "";
    return;
  }
  if (empty) empty.hidden = true;
  list.innerHTML = "";
  records.forEach((rec) => {
    const item = document.createElement("div");
    item.className = "history-item legacy-item";
    item.setAttribute("data-legacy-key", rec.key);
    const timeStr = rec.playedAt ? rec.playedAt.slice(0, 16) : "未知时间";
    const settled = rec.isSettled ? `总值 ${formatCurrency(rec.actualTotal)}` : "未结算";
    item.innerHTML = `
      <div class="history-item-top">
        <span class="history-item-time">${timeStr}</span>
        <span class="item-badge badge-legacy">LEGACY</span>
      </div>
      <div class="history-item-venue">${rec.venue || "未指定会场"} ${rec.box ? `· ${rec.box}` : ""}</div>
      <div class="history-item-summary">${settled}</div>
    `;
    item.addEventListener("click", () => {
      dashboard.selectedLegacyKey = rec.key;
      list.querySelectorAll(".legacy-item.is-selected").forEach((el) => el.classList.remove("is-selected"));
      item.classList.add("is-selected");
      showLegacyReviewDetail(rec.key);
    });
    list.appendChild(item);
  });
}

// ---------------------------------------------------------------- settlement review
const RARITY_MAP = {
  red: "红色",
  gold: "金色",
  purple: "紫色",
  blue: "蓝色",
  green: "绿色",
  white: "白色"
};

function loadSettlementReview(recordId, source, force = false) {
  const currentSource = source || "current";
  if (!force) {
    if (dashboard.review && dashboard.review.recordId === recordId && dashboard.reviewSource === currentSource) {
      return;
    }
    if (dashboard.pendingReviewRecordId === recordId && dashboard.pendingReviewSource === currentSource) {
      return;
    }
  }
  dashboard.loadSettlementReviewCount = (dashboard.loadSettlementReviewCount || 0) + 1;
  dashboard.review = null;
  dashboard.reviewEdits = null;
  dashboard.pendingReviewRecordId = recordId;
  dashboard.pendingReviewSource = currentSource;
  const section = document.getElementById("detail-review-section");
  const empty = document.getElementById("review-empty");
  const proposalsContainer = document.getElementById("review-proposals");
  if (proposalsContainer) proposalsContainer.innerHTML = "";
  const wirSummaryBox = document.getElementById("wir-saved-summary");
  if (wirSummaryBox) wirSummaryBox.hidden = true;
  if (section) section.hidden = true;
  if (empty) empty.hidden = true;
  dashboard.pendingReviewRequestId = postNative("request_settlement_review", { recordId, source: currentSource });
}

function updateReviewSummaryStats() {
  const review = dashboard.review;
  if (!review) return;
  const proposals = review.proposals || [];
  const edits = dashboard.reviewEdits || [];
  let confirmed = 0;
  let unknown = 0;
  let pending = 0;
  proposals.forEach((p) => {
    const ed = edits.find((e) => e.slotIndex === p.slotIndex);
    if (ed && ed.status === "confirmed") confirmed++;
    else if (ed && ed.status === "unknown") unknown++;
    else pending++;
  });
  const pendingEl = document.getElementById("stat-pending-num");
  const confirmedEl = document.getElementById("stat-confirmed-num");
  const unknownEl = document.getElementById("stat-unknown-num");
  if (pendingEl) pendingEl.textContent = String(pending);
  if (confirmedEl) confirmedEl.textContent = String(confirmed);
  if (unknownEl) unknownEl.textContent = String(unknown);
}

function renderWarehouseIdentitySummary(summary) {
  const box = document.getElementById("wir-saved-summary");
  const caption = document.getElementById("wir-saved-caption");
  const facts = document.getElementById("wir-saved-facts");
  if (!box) return;
  if (!summary) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  if (caption) caption.textContent = summary.caption || "尚未写入仓库身份审阅";
  if (facts) {
    if (summary.saved && summary.readable) {
      facts.hidden = false;
      facts.textContent = `覆盖 ${summary.warehouseCoverage || "--"} · 审阅 ${summary.reviewCompletion || "--"} · 身份 ${summary.identityResolution || "--"} · 已确认 ${summary.resolvedCount || 0} · 已排除 ${summary.excludedCount || 0} · 未决 ${summary.unresolvedCount || 0}`;
    } else {
      facts.hidden = true;
      facts.textContent = "";
    }
  }
}

function resetHistoricalWarehouseReview() {
  const panel = document.getElementById("warehouse-identity-review");
  const home = dashboard.warehousePanelHome;
  if (panel && home && home.parentNode) home.parentNode.insertBefore(panel, home.nextSibling);
  if (panel) { panel.hidden = true; panel.dataset.fingerprint = ""; }
  dashboard.historicalWarehouseReview = null;
  dashboard.latestWarehouseRequestId = null;
  dashboard.pendingWarehouseHistoryRefresh = null;
  dashboard.warehouseReview = { available: false };
}

function openHistoricalWarehouseReview() {
  const review = dashboard.review;
  if (!review || !review.recordId || !review.warehouseReviewAvailable) return;
  const panel = document.getElementById("warehouse-identity-review");
  const section = document.getElementById("detail-review-section");
  if (!panel || !section) return;
  if (!dashboard.warehousePanelHome) {
    dashboard.warehousePanelHome = document.createComment("warehouse review home");
    panel.parentNode.insertBefore(dashboard.warehousePanelHome, panel);
  }
  dashboard.historicalWarehouseReview = review.recordId;
  section.appendChild(panel);
  panel.hidden = true;
  postNative("warehouse_identity_review", { op: "open", recordId: review.recordId });
}

function renderReviewSection(review) {
  if (dashboard.historicalWarehouseReview && (!review || review.recordId !== dashboard.historicalWarehouseReview)) {
    resetHistoricalWarehouseReview();
  }
  dashboard.reviewSectionRenderCount = (dashboard.reviewSectionRenderCount || 0) + 1;
  const section = document.getElementById("detail-review-section");
  if (!section) return;
  if (!review) {
    section.hidden = true;
    renderWarehouseIdentitySummary(null);
    return;
  }
  section.hidden = false;
  dashboard.review = review;
  dashboard.reviewSource = review.source || dashboard.pendingReviewSource || "current";
  if (!dashboard.review.recordId && dashboard.pendingReviewRecordId) {
    dashboard.review.recordId = dashboard.pendingReviewRecordId;
  }
  dashboard.pendingReviewRecordId = null;
  dashboard.pendingReviewSource = null;
  renderWarehouseIdentitySummary(review.warehouseIdentitySummary);
  const resumeWarehouse = document.getElementById("history-warehouse-review-btn");
  if (resumeWarehouse) resumeWarehouse.hidden = !review.warehouseReviewAvailable;
  let revisions = document.getElementById("history-warehouse-revisions");
  if (!revisions) {
    revisions = document.createElement("div");
    revisions.id = "history-warehouse-revisions";
    section.appendChild(revisions);
  }
  revisions.textContent = (review.warehouseReviewRevisions || []).map((item, index) =>
    `修改前记录 ${index + 1}：${item.reviewedAt || "时间未记录"}，${item.reviewerType === "HUMAN" ? "含人工审阅" : "自动记录"}，已确认 ${item.resolvedCount} 件`).join("；");

  if (dashboard.reviewEdits === null) {
    dashboard.reviewEdits = (review.reviewedItems && Array.isArray(review.reviewedItems))
      ? JSON.parse(JSON.stringify(review.reviewedItems))
      : [];
  }

  const srcLabel = document.getElementById("detail-review-tag");
  if (srcLabel) {
    srcLabel.textContent = review.source === "legacy"
      ? "历史归档 · 机器识别候选 · 人工保存后生效"
      : "当前历史 · 机器识别候选 · 人工保存后生效";
  }

  // screenshot
  const img = document.getElementById("review-screenshot-img");
  const noShot = document.getElementById("review-no-screenshot");
  const hasScreenshot = Boolean(review.screenshot && review.screenshot.available && review.screenshot.dataUrl);
  if (hasScreenshot) {
    img.src = review.screenshot.dataUrl;
    img.hidden = false;
    noShot.hidden = true;
  } else {
    img.hidden = true;
    noShot.hidden = false;
    noShot.textContent = review.source === "legacy" ? "无可用结算截图，可手动导入补录" : "暂无截图证据（可导入）";
  }

  // buttons state
  const replaceBtn = document.getElementById("review-replace-btn");
  const deleteBtn = document.getElementById("review-delete-btn");
  const rerecognizeBtn = document.getElementById("review-rerecognize-btn");
  if (replaceBtn) replaceBtn.disabled = !hasScreenshot;
  if (deleteBtn) deleteBtn.disabled = !hasScreenshot;
  if (rerecognizeBtn) rerecognizeBtn.disabled = !hasScreenshot;

  // summary
  const st = review.settlement || {};
  const identityFields = document.getElementById("review-identity-fields");
  if (identityFields) {
    identityFields.hidden = !review.identityEditable || review.source === "legacy";
    document.getElementById("review-winner-name").value = st.winner || "";
    document.getElementById("review-acquired").value = typeof st.acquired === "boolean" ? String(st.acquired) : "unknown";
    document.getElementById("review-identity-confirm").checked = false;
  }
  const summaryBox = document.getElementById("review-summary-box");
  summaryBox.hidden = false;
  document.getElementById("review-clearing").textContent = st.clearingPrice != null ? formatCurrency(st.clearingPrice) : "--";
  document.getElementById("review-actual").textContent = st.actualTotal != null ? formatCurrency(st.actualTotal) : "--";
  document.getElementById("review-profit").textContent = formatSettlementProfit(st);
  const evId = (review.screenshot && review.screenshot.evidenceId) || (review.evidence && review.evidence.evidenceId) || "--";
  const evIdEl = document.getElementById("review-evidence-id");
  if (evIdEl) evIdEl.textContent = evId;
  document.getElementById("review-sha").textContent = (review.screenshot && review.screenshot.sha256) ? review.screenshot.sha256.slice(0, 16) : "--";
  const covEl = document.getElementById("review-coverage");
  if (covEl) {
    const rawCov = (review.screenshot && review.screenshot.coverageStatus) || (review.evidence && review.evidence.coverageStatus) || "COVERAGE_UNPROVEN";
    const covMap = {
      "COMPLETE": "完整覆盖",
      "PARTIAL": "部分覆盖",
      "COVERAGE_UNPROVEN": "部分覆盖（待核对）",
      "PARTIAL / COVERAGE_UNPROVEN": "部分覆盖（待核对）"
    };
    covEl.textContent = covMap[rawCov] || rawCov;
  }
  document.getElementById("review-status").textContent = st.reviewed ? `已审阅 (${st.reviewedAt || ""})` : "未审阅";

  // proposals or grouping hypotheses
  const container = document.getElementById("review-proposals");
  container.innerHTML = "";

  const identityEvidences = review.identityEvidence || [];
  const proposals = review.proposals || [];

  if (identityEvidences.length > 0) {
    // 4D2D1M-C3.5A: Render real grouping hypotheses & identity evidence
    const statsBar = document.createElement("div");
    statsBar.className = "review-stats-banner";
    const reviewedCount = (review.reviewedItems || []).length;
    statsBar.innerHTML = `
      <div class="stat-pill"><span class="stat-num">${identityEvidences.length}</span><span class="stat-label">可见藏品</span></div>
      <div class="stat-pill stat-confirmed"><span class="stat-num">${reviewedCount}</span><span class="stat-label">已确认事实</span></div>
      <div class="stat-pill stat-pending"><span class="stat-num">${identityEvidences.length - reviewedCount}</span><span class="stat-label">待审核</span></div>
    `;
    container.appendChild(statsBar);

    const cardsContainer = document.createElement("div");
    cardsContainer.className = "review-cards-list";

    function createGroupingCard(ev, idx) {
      const card = document.createElement("div");
      card.className = "review-proposal-card grouping-card";
      const hypId = ev.groupingHypothesisId || `ghyp_${idx}`;
      card.setAttribute("data-grouping-id", hypId);

      const rarityText = RARITY_MAP[ev.rarity] || ev.rarity || "未知品质";
      const shapeLabel = ev.gridShape || "1x1";
      const rawStatus = ev.identityStatus || ev.status || "UNKNOWN";
      const statusMap = {
        "EXACT_IDENTIFIED": "自动已识别",
        "AMBIGUOUS_CANDIDATES": "待辨认",
        "UNIQUE_IN_CATALOG": "图鉴唯一",
        "AMBIGUOUS_IN_CATALOG": "多候选待核对",
        "NO_CATALOG_MATCH": "无图鉴匹配",
        "UNRESOLVED_NOISE": "底板噪点",
        "UNKNOWN": "未定"
      };
      const statusLabel = statusMap[rawStatus] || rawStatus;

      const reviewedItem = (review.reviewedItems || []).find(
        (r) => r.groupingHypothesisId === hypId || r.proposalId === hypId
      );

      let statusBadgeText = "🤖 待核对 · 机器推断";
      let statusBadgeClass = "is-machine-pending";
      if (reviewedItem) {
        statusBadgeText = `✓ 人工已核准：${reviewedItem.catalogName || "已确认"}`;
        statusBadgeClass = "is-human-confirmed";
      } else if (statusLabel === "UNRESOLVED_NOISE") {
        statusBadgeText = "未决底板噪点";
        statusBadgeClass = "is-unknown";
      }

      const cands = ev.rankedCandidates || ev.candidates || [];
      const machineMatch = rawStatus === "EXACT_IDENTIFIED"
        ? cands.find((c) => c.catalogId === ev.candidateCatalogId) : null;
      if (!reviewedItem && machineMatch) {
        statusBadgeText = `自动识别：${escapeHtml(machineMatch.name)}`;
      }
      let candHtml = "";
      if (cands.length > 0) {
        candHtml = cands.map((c, ci) => {
          const isSelected = (reviewedItem && reviewedItem.selectedCatalogId === c.catalogId) || (!reviewedItem && machineMatch && c.catalogId === machineMatch.catalogId) || (cands.length === 1 && !reviewedItem);
          const scoreStr = c.templateScore != null && c.templateScore > 0 ? ` (匹配度: ${Math.round(c.templateScore * 100)}%)` : "";
          return `<button type="button" class="review-cand-btn rarity-${c.rarity || ev.rarity || 'white'} ${isSelected ? 'is-selected' : ''}" data-grouping-id="${hypId}" data-catalog-id="${c.catalogId}"><span class="cand-name">${c.name}</span><span class="cand-price">${c.value != null ? formatCurrency(c.value) : "价值未知"}${scoreStr}</span></button>`;
        }).join(" ");
      } else {
        candHtml = `<span class="review-cand-none">图鉴无直接对应候选 (可手动选择其他图鉴物品)</span>`;
      }

      const scoreDisplay = ev.top1Score != null && ev.top1Score > 0
        ? `<span class="card-meta-pill">匹配得分：${Math.round(ev.top1Score * 100)}（非准确率）</span>`
        : "";

      const thumbHtml = ev.cropDataUrl
        ? `<div class="grouping-thumb" style="display:inline-block; margin-right:8px;"><img src="${ev.cropDataUrl}" alt="${hypId}" style="max-height:42px; border-radius:4px; vertical-align:middle;" /></div>`
        : "";

      card.innerHTML = `
        <div class="card-top-row">
          <div class="card-title-group" style="display:flex; align-items:center; flex-wrap:wrap; gap:6px;">
            ${thumbHtml}
            <strong class="card-region-title">物品 #${idx + 1}</strong>
            <span class="card-meta-pill pill-rarity-${ev.rarity || 'white'}">${rarityText}</span>
            <span class="card-meta-pill pill-shape">${shapeLabel}</span>
            <span class="card-meta-pill pill-status">${statusLabel}</span>
            ${scoreDisplay}
          </div>
          <span class="proposal-status-badge ${statusBadgeClass}">${statusBadgeText}</span>
        </div>
        <div class="card-cands-row" style="margin-top: 8px;">${candHtml}</div>
        <div class="card-correction-row" style="display:flex; gap:8px; margin-top:8px; align-items:center; flex-wrap:wrap;">
          <button type="button" class="btn-review-action btn-review-primary btn-confirm-candidate" data-grouping-id="${hypId}">确认候选</button>
          <input type="text" class="form-control review-input-override-id" data-grouping-id="${hypId}" placeholder="输入其他图鉴ID (如: image1-0-1)" autocomplete="off" style="width: 220px;">
          <button type="button" class="btn-review-action btn-confirm-override" data-grouping-id="${hypId}">选择其他图鉴物品</button>
        </div>
        <div class="card-bottom-row" style="margin-top: 8px; font-size: 11px; color: var(--text-muted);">
          <details class="review-advanced-details">
            <summary>几何与证据溯源</summary>
            <div class="advanced-info-body">
              <div><strong>假设标识 (ID)：</strong>${hypId}</div>
              <div><strong>物理坐标 (Cells)：</strong>${JSON.stringify(ev.cells || [])}</div>
              <div><strong>包围盒 (BBox)：</strong>${JSON.stringify(ev.bbox || [])}</div>
              <div><strong>候选数量：</strong>${ev.candidateCount != null ? ev.candidateCount : cands.length}</div>
              <div><strong>证据来源：</strong>${ev.evidenceSource || "--"}</div>
            </div>
          </details>
        </div>
      `;
      return card;
    }

    identityEvidences.forEach((ev, idx) => {
      cardsContainer.appendChild(createGroupingCard(ev, idx));
    });
    container.appendChild(cardsContainer);

    // Bind grouping events
    cardsContainer.querySelectorAll(".review-cand-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const card = btn.closest(".grouping-card");
        if (!card) return;
        card.querySelectorAll(".review-cand-btn").forEach((b) => b.classList.remove("is-selected"));
        btn.classList.add("is-selected");
      });
    });

    cardsContainer.querySelectorAll(".btn-confirm-candidate").forEach((btn) => {
      btn.addEventListener("click", () => {
        const hypId = btn.dataset.groupingId;
        const card = btn.closest(".grouping-card");
        if (!card) return;
        const selectedBtn = card.querySelector(".review-cand-btn.is-selected");
        const selectedCatId = selectedBtn ? selectedBtn.dataset.catalogId : null;
        postNative("settlement_item_review_action", {
          recordId: review.recordId,
          groupingHypothesisId: hypId,
          action: "CONFIRM_CANDIDATE",
          selectedCatalogId: selectedCatId,
          source: review.source || "current",
        });
      });
    });

    cardsContainer.querySelectorAll(".btn-confirm-override").forEach((btn) => {
      btn.addEventListener("click", () => {
        const hypId = btn.dataset.groupingId;
        const card = btn.closest(".grouping-card");
        if (!card) return;
        const input = card.querySelector(".review-input-override-id");
        const overrideCatId = input ? input.value.trim() : "";
        if (!overrideCatId) {
          const status = document.getElementById("review-save-status");
          if (status) status.textContent = "请先输入图鉴ID";
          return;
        }
        postNative("settlement_item_review_action", {
          recordId: review.recordId,
          groupingHypothesisId: hypId,
          action: "CONFIRM_CATALOG_OVERRIDE",
          selectedCatalogId: overrideCatId,
          overrideReason: "HUMAN_OVERRIDE",
          source: review.source || "current",
        });
      });
    });

    return;
  }

  if (proposals.length === 0) {
    container.innerHTML = `<div class="review-empty">无机器识别候选（可先导入截图）。</div>`;
    return;
  }

  // 1. Top Summary Banner
  const statsBar = document.createElement("div");
  statsBar.className = "review-stats-banner";
  statsBar.innerHTML = `
    <div class="stat-pill"><span class="stat-num">${proposals.length}</span><span class="stat-label">识别区域</span></div>
    <div class="stat-pill stat-pending"><span class="stat-num" id="stat-pending-num">0</span><span class="stat-label">待确认</span></div>
    <div class="stat-pill stat-confirmed"><span class="stat-num" id="stat-confirmed-num">0</span><span class="stat-label">已确认</span></div>
    <div class="stat-pill stat-unknown"><span class="stat-num" id="stat-unknown-num">0</span><span class="stat-label">标未知</span></div>
  `;
  container.appendChild(statsBar);

  // 2. Separate actionable vs unassigned
  const actionable = [];
  const unassigned = [];
  proposals.forEach((p, idx) => {
    const hasCands = p.candidateItemIds && p.candidateItemIds.length > 0;
    const hasPart = p.partitionCandidates && p.partitionCandidates.length > 0;
    if (hasCands || hasPart || !p.groupingAmbiguous) {
      actionable.push({ proposal: p, originalIndex: idx });
    } else {
      unassigned.push({ proposal: p, originalIndex: idx });
    }
  });

  const cardsContainer = document.createElement("div");
  cardsContainer.className = "review-cards-list";

  function createProposalCard(p, idx) {
    const card = document.createElement("div");
    card.className = "review-proposal-card";
    card.setAttribute("data-slot", p.slotIndex);
    card.setAttribute("data-idx", idx);

    const rarityText = RARITY_MAP[p.rarity] || p.rarity || "未知品质";
    const shapeLabel = p.shape || "1x1";
    const ambigTag = p.groupingAmbiguous ? `<span class="tag-ambig" title="局部连通块重叠或候选组合歧义">⚠️ 分组歧义</span>` : "";

    const ed = (dashboard.reviewEdits || []).find((e) => e.slotIndex === p.slotIndex);
    let statusText = "🤖 待核对 · 机器推断";
    let statusClass = "is-machine-pending";
    if (ed && ed.status === "confirmed") {
      statusText = `✓ 人工已核准：${ed.name || "已确认"}`;
      statusClass = "is-human-confirmed";
    } else if (ed && ed.status === "unknown") {
      statusText = "已标未知";
      statusClass = "is-unknown";
    }

    let candHtml = "";
    if (p.candidateItemIds && p.candidateItemIds.length > 0) {
      candHtml = (p.candidateItemIds || []).map((name, ci) => {
        const price = (p.candidatePrices || [])[ci];
        const isSelected = ed && ed.status === "confirmed" && (ed.itemId === name || ed.name === name);
        const priceStr = price != null ? ` (${formatCurrency(price)})` : "";
        return `<button type="button" class="review-cand-btn rarity-${p.rarity || 'white'} ${isSelected ? 'is-selected' : ''}" data-slot="${p.slotIndex}" data-cand-idx="${ci}"><span class="cand-name">${name}</span><span class="cand-price">${priceStr}</span></button>`;
      }).join(" ");
    } else {
      candHtml = `<span class="review-cand-none">暂无可确认候选</span>`;
    }

    const customName = ed && ed.isManualCorrection ? (ed.name || "") : "";
    const customPrice = ed && ed.isManualCorrection && ed.price != null ? ed.price : "";

    card.innerHTML = `
      <div class="card-top-row">
        <div class="card-title-group">
          <strong class="card-region-title">区域 #${p.slotIndex}</strong>
          <span class="card-meta-pill pill-rarity-${p.rarity || 'white'}">${rarityText}</span>
          <span class="card-meta-pill pill-shape">${shapeLabel}</span>
          ${ambigTag}
        </div>
        <span class="proposal-status-badge ${statusClass}" id="status-badge-${p.slotIndex}">${statusText}</span>
      </div>
      <div class="card-cands-row">${candHtml}</div>
      <div class="card-correction-row">
        <input type="text" class="form-control review-input-custom-name" data-slot="${p.slotIndex}" placeholder="人工修正名称 (如: ${(p.candidateItemIds && p.candidateItemIds[0]) || '藏品名称'})" value="${customName}" autocomplete="off">
        <input type="number" class="form-control review-input-custom-price" data-slot="${p.slotIndex}" placeholder="价格" value="${customPrice}" min="0">
        <button type="button" class="btn-apply-correction" data-slot="${p.slotIndex}">应用修正</button>
      </div>
      <div class="card-bottom-row">
        <div class="card-actions-group">
          <button type="button" class="btn-review-mini btn-mark-unknown" data-slot="${p.slotIndex}">标为未知</button>
          <button type="button" class="btn-review-mini btn-clear-choice" data-slot="${p.slotIndex}">清除</button>
        </div>
        <details class="review-advanced-details">
          <summary>高级识别证据</summary>
          <div class="advanced-info-body">
            <div><strong>网格坐标：</strong>${JSON.stringify(p.cells || [])}</div>
            <div><strong>分块候选：</strong>${JSON.stringify(p.partitionCandidates || [])}</div>
            <div><strong>包围盒：</strong>${JSON.stringify(p.bbox || [])}</div>
            <div><strong>置信度：</strong>${p.score != null ? p.score : "--"}</div>
          </div>
        </details>
      </div>
    `;
    return card;
  }

  actionable.forEach((item) => {
    cardsContainer.appendChild(createProposalCard(item.proposal, item.originalIndex));
  });
  container.appendChild(cardsContainer);

  // 3. Unassigned / Ambiguous group (default collapsed)
  if (unassigned.length > 0) {
    const unassignedGroup = document.createElement("details");
    unassignedGroup.className = "review-unassigned-group";
    if (actionable.length === 0) unassignedGroup.open = true;
    const summary = document.createElement("summary");
    summary.className = "unassigned-group-summary";
    summary.textContent = `未分组识别证据 (${unassigned.length}) — 点击展开`;
    unassignedGroup.appendChild(summary);

    const unassignedList = document.createElement("div");
    unassignedList.className = "unassigned-items-list";
    unassigned.forEach((item) => {
      unassignedList.appendChild(createProposalCard(item.proposal, item.originalIndex));
    });
    unassignedGroup.appendChild(unassignedList);
    container.appendChild(unassignedGroup);
  }

  // Bind handlers
  container.querySelectorAll(".review-cand-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const slot = Number(btn.dataset.slot);
      const candIdx = Number(btn.dataset.candIdx);
      confirmProposal(slot, candIdx);
    });
  });
  container.querySelectorAll(".btn-mark-unknown").forEach((btn) => {
    btn.addEventListener("click", () => {
      const slot = Number(btn.dataset.slot);
      markProposalUnknown(slot);
    });
  });
  container.querySelectorAll(".btn-clear-choice").forEach((btn) => {
    btn.addEventListener("click", () => {
      const slot = Number(btn.dataset.slot);
      clearProposalChoice(slot);
    });
  });
  container.querySelectorAll(".btn-apply-correction").forEach((btn) => {
    btn.addEventListener("click", () => {
      const slot = Number(btn.dataset.slot);
      const card = btn.closest(".review-proposal-card");
      if (!card) return;
      const nameInput = card.querySelector(".review-input-custom-name");
      const priceInput = card.querySelector(".review-input-custom-price");
      const nameVal = nameInput ? nameInput.value.trim() : "";
      const priceVal = priceInput && priceInput.value.trim() !== "" ? Number(priceInput.value.trim().replace(/,/g, "")) : null;
      applyManualCorrection(slot, nameVal, priceVal);
    });
  });

  updateReviewSummaryStats();
}

function getProposalEdits() {
  return (dashboard.reviewEdits && Array.isArray(dashboard.reviewEdits)) ? JSON.parse(JSON.stringify(dashboard.reviewEdits)) : [];
}

function setProposalEdit(slotIndex, edit) {
  const edits = getProposalEdits();
  const found = edits.find((e) => e.slotIndex === slotIndex);
  if (found) Object.assign(found, edit);
  else edits.push(Object.assign({ slotIndex }, edit));
  dashboard.reviewEdits = edits;
}

function confirmProposal(slotIndex, candIdx) {
  const review = dashboard.review;
  if (!review) return;
  const p = (review.proposals || []).find((it) => it.slotIndex === slotIndex);
  if (!p) return;
  const name = (p.candidateItemIds || [])[candIdx];
  const price = (p.candidatePrices || [])[candIdx];

  setProposalEdit(slotIndex, {
    slotIndex,
    itemId: name,
    name: name || "",
    price: price != null ? price : null,
    rarity: p.rarity,
    shape: p.shape,
    cells: p.cells || [],
    bbox: p.bbox || [],
    status: "confirmed",
    groupingAmbiguous: !!p.groupingAmbiguous,
    partitionCandidates: p.partitionCandidates || [],
  });

  const cards = document.querySelectorAll(`[data-slot="${slotIndex}"]`);
  cards.forEach((card) => {
    const badge = card.querySelector(".proposal-status-badge");
    if (badge) {
      badge.textContent = `已确认：${name || ""}`;
      badge.className = "proposal-status-badge is-confirmed";
    }
    card.querySelectorAll(".review-cand-btn").forEach((btn) => {
      const ci = Number(btn.dataset.candIdx);
      btn.classList.toggle("is-selected", ci === candIdx);
    });
  });

  updateReviewSummaryStats();
}

function markProposalUnknown(slotIndex) {
  const review = dashboard.review;
  if (!review) return;
  const p = (review.proposals || []).find((it) => it.slotIndex === slotIndex);
  if (!p) return;

  setProposalEdit(slotIndex, {
    slotIndex,
    itemId: null,
    name: null,
    price: null,
    rarity: p.rarity,
    shape: p.shape,
    cells: p.cells || [],
    bbox: p.bbox || [],
    status: "unknown",
    groupingAmbiguous: !!p.groupingAmbiguous,
    partitionCandidates: p.partitionCandidates || [],
  });

  const cards = document.querySelectorAll(`[data-slot="${slotIndex}"]`);
  cards.forEach((card) => {
    const badge = card.querySelector(".proposal-status-badge");
    if (badge) {
      badge.textContent = "已标未知";
      badge.className = "proposal-status-badge is-unknown";
    }
    card.querySelectorAll(".review-cand-btn").forEach((btn) => {
      btn.classList.remove("is-selected");
    });
  });

  updateReviewSummaryStats();
}

function clearProposalChoice(slotIndex) {
  const edits = getProposalEdits();
  dashboard.reviewEdits = edits.filter((e) => e.slotIndex !== slotIndex);

  const cards = document.querySelectorAll(`[data-slot="${slotIndex}"]`);
  cards.forEach((card) => {
    const badge = card.querySelector(".proposal-status-badge");
    if (badge) {
      badge.textContent = "待确认";
      badge.className = "proposal-status-badge is-pending";
    }
    card.querySelectorAll(".review-cand-btn").forEach((btn) => {
      btn.classList.remove("is-selected");
    });
  });

  updateReviewSummaryStats();
}

function resetReviewEdits() {
  dashboard.reviewEdits = null;
  const status = document.getElementById("review-save-status");
  if (status) status.textContent = "已撤销未保存修改";
  if (dashboard.review) renderReviewSection(dashboard.review);
}

function applyManualCorrection(slotIndex, customName, customPrice) {
  const review = dashboard.review;
  if (!review) return;
  const p = (review.proposals || []).find((it) => it.slotIndex === slotIndex);
  if (!p) return;
  if (!customName) {
    clearProposalChoice(slotIndex);
    return;
  }

  setProposalEdit(slotIndex, {
    slotIndex,
    itemId: customName,
    name: customName,
    price: Number.isFinite(customPrice) ? customPrice : null,
    rarity: p.rarity,
    shape: p.shape,
    cells: p.cells || [],
    bbox: p.bbox || [],
    status: "confirmed",
    isManualCorrection: true,
    groupingAmbiguous: !!p.groupingAmbiguous,
    partitionCandidates: p.partitionCandidates || [],
  });

  const cards = document.querySelectorAll(`[data-slot="${slotIndex}"]`);
  cards.forEach((card) => {
    const badge = card.querySelector(".proposal-status-badge");
    if (badge) {
      badge.textContent = `已确认：${customName}`;
      badge.className = "proposal-status-badge is-confirmed";
    }
    card.querySelectorAll(".review-cand-btn").forEach((btn) => {
      btn.classList.remove("is-selected");
    });
  });

  updateReviewSummaryStats();
}

function saveReviewedSettlement() {
  const review = dashboard.review;
  if (!review) return;
  const reviewedItems = getProposalEdits();
  const status = document.getElementById("review-save-status");
  if (status) status.textContent = "保存中…";
  postNative("save_settlement_review", {
    recordId: review.recordId,
    source: review.source || "current",
    reviewedItems,
    identityReview: review.identityEditable && document.getElementById("review-identity-confirm").checked
      ? { winner: document.getElementById("review-winner-name").value.trim(),
          acquired: document.getElementById("review-acquired").value === "unknown" ? null : document.getElementById("review-acquired").value === "true" }
      : null,
    reviewMeta: {
      screenshotUri: review.screenshot ? review.screenshot.uri : null,
      screenshotSha256: review.screenshot ? review.screenshot.sha256 : null,
      provenance: review.provenance || null,
    },
  });
}

function currentReviewTarget() {
  if (dashboard.selectedLegacyKey) return { recordId: dashboard.selectedLegacyKey, source: "legacy" };
  if (dashboard.selectedRecordId) return { recordId: dashboard.selectedRecordId, source: dashboard.selectedRecord?.recordSource || "current" };
  return null;
}

function importScreenshot() {
  const target = currentReviewTarget();
  if (!target) {
    const status = document.getElementById("review-save-status");
    if (status) status.textContent = "请先选择一局对局";
    return;
  }
  const status = document.getElementById("review-save-status");
  if (status) status.textContent = "打开文件选择框…";
  postNative("import_settlement_screenshot", target);
}

function replaceScreenshot() {
  const target = currentReviewTarget();
  if (!target) {
    const status = document.getElementById("review-save-status");
    if (status) status.textContent = "请先选择一局对局";
    return;
  }
  const status = document.getElementById("review-save-status");
  if (status) status.textContent = "打开文件选择框…";
  postNative("replace_settlement_screenshot", target);
}

function deleteScreenshot() {
  const target = currentReviewTarget();
  if (!target) return;
  const review = dashboard.review;
  if (review && review.settlement && review.settlement.reviewed) {
    if (!window.confirm("此对局已有已保存的审阅结果。将移除人工导入关联，保留原图、原始凭证和已保存的核对结果。是否继续？")) {
      return;
    }
  }
  const status = document.getElementById("review-save-status");
  if (status) status.textContent = "正在移除导入关联…";
  postNative("delete_settlement_screenshot", target);
}

function rerunSettlementRecognition() {
  const target = currentReviewTarget();
  if (!target) {
    const status = document.getElementById("review-save-status");
    if (status) status.textContent = "请先选择对局记录";
    return;
  }
  const status = document.getElementById("review-save-status");
  if (status) status.textContent = "正在重新识别结算截图…";
  postNative("rerun_settlement_recognition", target);
}

function selectLegacySource() {
  const loading = document.getElementById("legacy-loading");
  if (loading) loading.hidden = false;
  postNative("select_legacy_archive_source");
}

function renderSnapshotAssistResult(result) {
  if (!result) return;
  dashboard.lastSnapshotResult = result;
  const statusEl = document.getElementById("match-snapshot-status");
  const textEl = document.getElementById("match-snapshot-status-text");
  const snapBtn = document.getElementById("match-btn-snapshot");
  const snapLabel = document.getElementById("match-snapshot-btn-label");

  const status = result.status || (result.ok ? "completed" : "failed");
  const isRecognizing = status === "recognizing" || status === "busy";

  if (snapBtn) {
    snapBtn.disabled = isRecognizing;
    if (isRecognizing) {
      snapBtn.classList.add("is-recognizing");
      if (snapLabel) snapLabel.textContent = "识别中...";
    } else {
      snapBtn.classList.remove("is-recognizing");
      if (snapLabel) snapLabel.textContent = "再次识别";
    }
  }

  if (statusEl && textEl) {
    statusEl.hidden = false;
    if (isRecognizing) {
      textEl.textContent = result.summary || "正在快照识别游戏画面...";
      statusEl.style.borderColor = "var(--border)";
      statusEl.style.color = "var(--text-muted)";
    } else {
      textEl.textContent = result.summary || (result.ok ? "✓ 快照识别成功" : "⚠️ 未识别到对局事实");
      statusEl.style.borderColor = result.ok ? "rgba(52, 211, 153, 0.4)" : "rgba(248, 113, 113, 0.4)";
      statusEl.style.color = result.ok ? "#34d399" : "#f87171";
    }
  }
}

const originalScreenshotRequests = new Map();
function requestOriginalScreenshots(recordId, containerId, source = "current") {
  const container = document.getElementById(containerId);
  if (!container || !recordId) return;
  container.dataset.recordId = recordId;
  container.dataset.source = source;
  container.textContent = "正在读取已保存原图…";
  const requestId = postNative("request_original_screenshots", { recordId, source });
  originalScreenshotRequests.set(containerId, { requestId, recordId, source });
}

function renderOriginalScreenshots(payload) {
  for (const [containerId, pending] of originalScreenshotRequests) {
    if (pending.requestId !== payload.requestId) continue;
    const container = document.getElementById(containerId);
    const result = payload.originalScreenshots;
    if (!container || container.dataset.recordId !== pending.recordId || (container.dataset.source || "current") !== (pending.source || "current")) continue;
    originalScreenshotRequests.delete(containerId);
    container.querySelectorAll("button").forEach(button => { button.disabled = false; });
    if (!result.ok) {
      window.alert(result.message || "截图操作失败");
      return;
    }
    container.replaceChildren();
    const images = result.images || [];
    const record = result.source === "live-trial"
      ? guidebookDrafts().find(item => item.id === pending.recordId) || null
      : null;
    const heading = document.createElement("p");
    if (!images.length) {
      heading.textContent = "暂无截图证据";
      heading.style.color = "var(--text-muted, #94a3b8)";
    } else {
      heading.textContent = result.source === "live-trial"
        ? `本局隔离草稿的观察原图（${images.length} 张） · 原图只读，缺失事实仍显示为未记录`
        : `已保存 ${images.length} 张结算截图（同一对局证据组） · 逐件识别及完整覆盖尚待核对`;
      heading.style.fontWeight = "600";
    }
    container.appendChild(heading);
    if (result.undoEvidenceId) {
      const undo = document.createElement("button");
      undo.type = "button";
      undo.className = "btn-wb-action";
      undo.textContent = "撤销删除";
      undo.addEventListener("click", () => changeOriginalScreenshot("restore_original_screenshot", pending.recordId, result.undoEvidenceId, containerId, undo, pending.source));
      container.appendChild(undo);
    }
    if (result.message) {
      const status = document.createElement("p");
      status.textContent = result.message;
      container.appendChild(status);
    }
    if (!images.length) continue;

    const sources = record?.intelCardEvidence?.observations || [];
    const sourceSequences = sources.map(item => item?.frameSequence ?? item?.sourceFrameSequence)
      .filter(value => value != null).map(Number).filter(Number.isFinite);
    const nativeSession = record?.auctionEvidence?.nativeObservation?.observationSessionId || null;
    const matchingSourceIndex = images.reduce((found, shot, index) => {
      if (shot.frameSequence == null || !sourceSequences.includes(Number(shot.frameSequence))) return found;
      if (nativeSession && shot.observationSessionId && shot.observationSessionId !== nativeSession) return found;
      return index;
    }, -1);
    const selected = { index: matchingSourceIndex >= 0 ? matchingSourceIndex : images.length - 1 };
    const pickerLabel = document.createElement("label");
    pickerLabel.className = "guidebook-keyframe-label";
    pickerLabel.textContent = "选择已保存关键帧";
    const picker = document.createElement("select");
    picker.className = "form-control guidebook-keyframe-select";
    picker.setAttribute("aria-label", "选择已保存关键帧");
    images.forEach((shot, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      const kindLabel = shot.kind === "native-observation" ? "局内观察" : shot.kind === "manual-game" ? "手动截图" : "结算截图";
      const frameLabel = shot.frameSequence == null ? `保存图 ${shot.sequence || index + 1}` : `第 ${shot.frameSequence} 帧`;
      const roundLabel = shot.round == null ? "" : ` · 第 ${shot.round} 回合`;
      const sessionLabel = shot.observationSessionId ? ` · 会话 ${String(shot.observationSessionId).slice(0, 8)}` : "";
      option.textContent = `${frameLabel}${roundLabel} · ${shot.capturedAt || "时间未记录"} · ${kindLabel}${sessionLabel}`;
      picker.appendChild(option);
    });
    picker.value = String(selected.index);
    pickerLabel.appendChild(picker);
    container.appendChild(pickerLabel);
    const panel = document.createElement("div");
    panel.className = "guidebook-keyframe-viewer";
    container.appendChild(panel);

    const renderSelected = () => {
      panel.replaceChildren();
      const index = selected.index;
      const shot = images[index];
      if (!shot) return;
      const kindLabel = shot.kind === "native-observation" ? "局内观察原图" : shot.kind === "manual-game" ? "手动截图" : "结算截图";
      const meta = document.createElement("p");
      const frameLabel = shot.frameSequence == null ? `保存图 ${shot.sequence || index + 1}` : `第 ${shot.frameSequence} 帧`;
      const targetLabel = shot.targetInstance?.pid != null ? ` · 目标进程 ${shot.targetInstance.pid}` : "";
      const roundLabel = shot.round == null ? "" : ` · 第 ${shot.round} 回合`;
      const sessionLabel = shot.observationSessionId ? ` · 观察会话 ${shot.observationSessionId}` : "";
      const shaPrefix = shot.sha256 ? ` · SHA-256 ${shot.sha256.slice(0, 8)}…` : "";
      meta.className = "guidebook-keyframe-meta";
      meta.textContent = `${frameLabel} · ${kindLabel}${roundLabel} · ${shot.capturedAt || "时间未记录"}${sessionLabel}${targetLabel}${shaPrefix}${shot.error ? " · " + shot.error : ""}`;
      panel.appendChild(meta);

      const linkedFacts = record ? sources.filter(item => {
        const linked = guidebookObservationSourceFrame(item, record);
        if (!linked) return false;
        if (shot.frameSequence != null && linked.frameSequence != null) {
          return Number(linked.frameSequence) === Number(shot.frameSequence)
            && (!linked.observationSessionId || !shot.observationSessionId || linked.observationSessionId === shot.observationSessionId);
        }
        return Boolean(shot.capturedAt && linked.capturedAt === shot.capturedAt);
      }) : [];
      const provenance = document.createElement("p");
      provenance.className = "guidebook-frame-provenance";
      if (linkedFacts.length) {
        const factLabels = [...new Set(linkedFacts.map(item => GUIDEBOOK_FACT_LABELS[item.field] || item.field || "局内事实"))];
        provenance.textContent = `事实来源帧：${factLabels.join("、")} · 首次来源原图已保存`;
      } else {
        const priorFactSequence = sources.map(item => item?.frameSequence ?? item?.sourceFrameSequence)
          .filter(value => value != null).map(Number).filter(Number.isFinite);
        const sameSession = !nativeSession || !shot.observationSessionId || nativeSession === shot.observationSessionId;
        const laterThanKnownSource = shot.frameSequence != null && sameSession
          && priorFactSequence.some(sequence => Number(shot.frameSequence) > sequence);
        provenance.textContent = laterThanKnownSource
          ? "后续关键帧：仅供回看；没有保存“事实仍显示在此帧”的关联，不能作为首次来源或佐证。"
          : "未记录事实与此帧的首次来源关系；原图仅供回看，不代替首次来源。";
      }
      panel.appendChild(provenance);
      if (shot.dataUrl) {
        const img = document.createElement("img");
        img.src = shot.dataUrl;
        img.alt = `本局关键帧 ${frameLabel}`;
        img.className = "guidebook-keyframe-image";
        panel.appendChild(img);
      } else {
        const missing = document.createElement("p");
        missing.className = "guidebook-source-missing";
        missing.textContent = "这张关键帧原图未保存或当前无法读取。";
        panel.appendChild(missing);
      }
      if (!shot.readOnly) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn-wb-action";
        remove.textContent = "删除截图";
        remove.title = "从本局及历史截图列表移除，原始证据文件保留；可撤销";
        remove.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation();
          changeOriginalScreenshot("delete_original_screenshot", pending.recordId, shot.evidenceId, containerId, remove, pending.source);
        });
        panel.appendChild(remove);
      }
    };
    picker.addEventListener("change", () => {
      const index = Number(picker.value);
      if (!Number.isInteger(index) || index < 0 || index >= images.length) return;
      selected.index = index;
      renderSelected();
    });
    renderSelected();
  }
}

function changeOriginalScreenshot(action, recordId, evidenceId, containerId, button, source = "current") {
  button.disabled = true;
  const requestId = postNative(action, { recordId, evidenceId, source });
  originalScreenshotRequests.set(containerId, { requestId, recordId, source });
}

function handleNativeMessage(event) {
  const payload = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
  if (!payload || payload.type !== "app_status") return;
  if (["request_original_screenshots", "delete_original_screenshot", "restore_original_screenshot"].includes(payload.action) && payload.originalScreenshots) {
    const updatedContainers = [...originalScreenshotRequests].filter(([, request]) => request.requestId === payload.requestId).map(([id]) => id);
    renderOriginalScreenshots(payload);
    if (payload.action !== "request_original_screenshots") {
      for (const id of ["warehouse-originals", "history-originals"]) {
        const node = document.getElementById(id);
        if (!updatedContainers.includes(id) && node?.dataset.recordId === payload.originalScreenshots.recordId && (node?.dataset.source || "current") === (payload.originalScreenshots.source || "current")) {
          requestOriginalScreenshots(payload.originalScreenshots.recordId, id, payload.originalScreenshots.source || "current");
        }
      }
    }
    return;
  }
  if (payload.action === "request_guidebook_sources" && payload.guidebookSources) {
    if (dashboard.guidebookSourcesRequestId && payload.requestId !== dashboard.guidebookSourcesRequestId) return;
    dashboard.guidebookSourcesRequestId = null;
    if (payload.guidebookSources.ok) {
      dashboard.guidebookSources = payload.guidebookSources;
      dashboard.guidebookSourcesError = null;
    } else {
      dashboard.guidebookSources = { items: [], roles: [], counts: {} };
      dashboard.guidebookSourcesError = payload.guidebookSources.message || "1.4 图鉴资料读取失败";
    }
    dashboard.guidebookCatalog = null;
    if (dashboard.currentView === "guidebook") renderGuidebook();
  }
  if (payload.action === "request_warehouse_slot_evidence" && payload.warehouseSlotEvidence) {
    const review = dashboard.warehouseInstanceReview;
    if (!review || review.requestId !== payload.requestId) return;
    review.evidence = payload.warehouseSlotEvidence;
    review.busy = false;
    if (review.evidence.ok) {
      const firstCandidate = (review.evidence.candidates || []).find(item => item.catalogId || item.Id);
      review.selectedCandidateId = String(firstCandidate?.catalogId || firstCandidate?.Id || "") || null;
    }
    renderWarehouseInstanceReviewPanel();
  }
  if (payload.action === "warehouse_instance_decision" && payload.warehouseInstanceDecision) {
    const review = dashboard.warehouseInstanceReview;
    if (!review || review.decisionRequestId !== payload.requestId) return;
    const result = payload.warehouseInstanceDecision;
    if (result.status === "PENDING") {
      review.busy = true;
      review.pendingCommandId = result.commandId;
      review.receipt = null;
    } else {
      review.busy = false;
      review.receipt = result;
    }
    renderWarehouseInstanceReviewPanel();
  }
  if (payload.action === "manual_facts" && payload.manualFactsResult) {
    renderManualCommandReceipt(payload.manualCommandResult || {
      status: payload.manualFactsResult.status,
      reason: payload.manualFactsResult.error || payload.manualFactsResult.message
    });
    if (payload.manualFactsResult.status === "PENDING") {
      dashboard.pendingManualCommand = payload.requestId || true;
    } else if (!payload.manualFactsResult.ok) {
      dashboard.isSavingPlayerName = false;
      dashboard.pendingPlayerName = null;
      updatePlayerDisplayNameStatus(null, { error: payload.manualFactsResult.error || "写入失败" });
    } else {
      dashboard.isPlayerNameEditing = false;
    }
  }
  if (payload.action === "next_match_preparation" && payload.nextMatchPreparationResult) {
    const result = payload.nextMatchPreparationResult;
    if (!dashboard.nextMatchPreparationRequestId || payload.requestId === dashboard.nextMatchPreparationRequestId) {
      dashboard.nextMatchPreparationRequestId = null;
      if (result.preparation) {
        dashboard.nextMatchPreparation = result.preparation;
        dashboard.nextMatchPreparationVersion = null;
        dashboard.nextMatchPreparationDirty = false;
        if (dashboard.lastCurrentMatch) {
          dashboard.lastCurrentMatch.nextMatchPreparation = result.preparation;
        }
      }
      if (result.ok === false) {
        const status = document.getElementById("next-match-preparation-status");
        if (status) status.textContent = result.message || "下一局准备未生效。";
      }
      renderNextMatchPreparation(dashboard.lastCurrentMatch);
    }
  }
  if (payload.action === "manual_finalize") {
    const reply = payload.manualFinalizeResult || {};
    const result = reply.terminalResult || reply;
    const button = document.getElementById("settle-modal-confirm-btn");
    if (button) { button.disabled = false; button.textContent = "保存并结算"; }
    if (result.ok === true) {
      closeSettleMatchModal();
    } else {
      const error = document.getElementById("settle-modal-error");
      if (error) { error.hidden = false; error.textContent = result.message || "保存未成功，请检查输入后重试；当前局仍保留。"; }
    }
  }
  if (payload.action === "triggered_snapshot" && payload.snapshotResult) {
    renderSnapshotAssistResult(payload.snapshotResult);
  }
  if (payload.action === "save_settlement_screenshot" && payload.settlementScreenshot) {
    const result = payload.settlementScreenshot;
    if (result.ok) requestOriginalScreenshots(dashboard.matchState.matchId, "warehouse-originals");
    const button = document.getElementById("match-btn-save-settlement-screenshot");
    const status = document.getElementById("match-settlement-screenshot-status");
    if (button) button.disabled = false;
    if (status) {
      if (result.ok) {
        status.textContent = `已保存原图 · ${result.width || "?"}×${result.height || "?"} · ${result.relativePath || "已关联当前对局"}`;
        status.style.color = "#34d399";
      } else if (result.status === "NOT_SETTLEMENT") {
        status.innerHTML = `未检测到结算画面；可点击「<a href="javascript:void(0)" id="switch-to-manual-capture-link" style="color:#60a5fa;text-decoration:underline">手动截图（异环）</a>」直接采集`;
        status.style.color = "#f87171";
        const link = document.getElementById("switch-to-manual-capture-link");
        if (link) {
          link.addEventListener("click", () => {
            const manualBtn = document.getElementById("match-btn-save-game-screenshot");
            if (manualBtn) manualBtn.click();
          });
        }
      } else {
        status.textContent = result.message || "保存结算原图失败";
        status.style.color = "#f87171";
      }
    }
  }
  if (payload.action === "save_game_screenshot" && payload.gameScreenshot) {
    const result = payload.gameScreenshot;
    if (result.ok && !result.duplicate && result.status !== "DUPLICATE_IGNORED") {
      requestOriginalScreenshots(dashboard.matchState.matchId, "warehouse-originals");
    }
    const button = document.getElementById("match-btn-save-game-screenshot");
    const status = document.getElementById("match-game-screenshot-status");
    if (button) button.disabled = false;
    if (status) {
      if (result.status === "DUPLICATE_IGNORED" || result.duplicate) {
        status.textContent = result.message || "该截图与上一张完全相同，未重复追加；请滚动仓库后再截取。";
        status.style.color = "#f59e0b";
      } else if (result.ok) {
        status.textContent = result.message || `已保存异环原图 · ${result.width || "?"}×${result.height || "?"} · ${result.sha256 ? result.sha256.slice(0, 8) : ""}`;
        status.style.color = "#34d399";
      } else {
        status.textContent = result.message || "保存异环截图失败";
        status.style.color = "#f87171";
      }
    }
  }
  if (payload.action === "request_legacy_archive" && payload.legacyArchive) {
    renderLegacyArchive(payload.legacyArchive);
  }
  if (payload.action === "select_legacy_archive_source" && payload.legacyArchive) {
    renderLegacyArchive(payload.legacyArchive);
    const info = document.getElementById("legacy-source-info");
    if (info && payload.legacyArchive.ok) info.textContent = `已选择 · ${(payload.legacyArchive.source || {}).recordCount || 0} 条`;
  }
  if (payload.action === "request_settlement_review" && payload.settlementReview) {
    const reviewResult = payload.settlementReview;
    const reviewRequestId = payload.requestId || "";
    if (
      reviewRequestId &&
      dashboard.pendingReviewRequestId &&
      reviewRequestId !== dashboard.pendingReviewRequestId
    ) {
      return;
    }
    if (reviewResult.status === "STARTED") {
      const status = document.getElementById("review-save-status");
      if (status) status.textContent = "正在加载该局详情，识别在后台进行…";
    } else {
      dashboard.pendingReviewRequestId = null;
    }
    if (reviewResult.status === "STARTED") {
      // Keep the detail pane responsive while screenshot recognition runs.
    } else if (reviewResult.ok) {
      const review = reviewResult.review || {};
      if (reviewResult.warehouseIdentitySummary) {
        review.warehouseIdentitySummary = reviewResult.warehouseIdentitySummary;
      }
      renderReviewSection(review);
    } else {
      const section = document.getElementById("detail-review-section");
      if (section) section.hidden = true;
      renderWarehouseIdentitySummary(reviewResult.warehouseIdentitySummary || null);
    }
  }
  if ((payload.action === "import_settlement_screenshot" || payload.action === "replace_settlement_screenshot") && payload.settlementReview) {
    if (payload.settlementReview.ok) {
      renderReviewSection(payload.settlementReview.review);
      const status = document.getElementById("review-save-status");
      if (status) {
        status.textContent = payload.action === "replace_settlement_screenshot"
          ? "已替换结算截图并保存原始证据"
          : "已导入结算截图并保存原始证据";
      }
    } else {
      const status = document.getElementById("review-save-status");
      if (status) status.textContent = (payload.settlementReview.message) || "操作失败";
    }
  }
  if (payload.action === "rerun_settlement_recognition" && payload.settlementReview) {
    if (payload.settlementReview.ok) {
      renderReviewSection(payload.settlementReview.review);
      const status = document.getElementById("review-save-status");
      const count = (payload.settlementReview.review && payload.settlementReview.review.identityEvidence) ? payload.settlementReview.review.identityEvidence.length : 0;
      if (status) {
        status.textContent = `重新识别完成，生成 ${count} 个物理分组候选（待审核）`;
      }
    } else {
      const status = document.getElementById("review-save-status");
      if (status) status.textContent = (payload.settlementReview.message) || "重新识别失败";
    }
  }
  if (payload.action === "delete_settlement_screenshot" && payload.settlementReview) {
    if (payload.settlementReview.ok) {
      renderReviewSection(payload.settlementReview.review);
      const status = document.getElementById("review-save-status");
      if (status) status.textContent = "已移除导入关联，原图及已保存凭证保留";
    } else {
      const status = document.getElementById("review-save-status");
      if (status) status.textContent = (payload.settlementReview.message) || "删除失败";
    }
  }
  if (payload.action === "save_settlement_review" && payload.settlementReview) {
    const status = document.getElementById("review-save-status");
    if (status) {
      status.textContent = payload.settlementReview.ok
        ? (payload.settlementReview.identityReviewed ? "已保存身份修正，保留草稿及原始识别记录" : `已保存 ${payload.settlementReview.reviewedCount} 件审阅事实`)
        : (payload.settlementReview.message || "保存失败");
    }
    if (payload.settlementReview.ok && dashboard.review) {
      dashboard.review.settlement.reviewed = true;
      dashboard.review.settlement.reviewedAt = payload.settlementReview.reviewedAt;
      document.getElementById("review-status").textContent = "已审阅";
      if (payload.settlementReview.identityReviewed) {
        loadSettlementReview(dashboard.review.recordId, dashboard.review.source || "current");
      }
    }
  }
  if (payload.action === "settlement_item_review_action" && payload.settlementItemReview) {
    const res = payload.settlementItemReview;
    const status = document.getElementById("review-save-status");
    if (res.ok) {
      const it = res.reviewedItem || {};
      if (status) {
        status.textContent = `已保存藏品审阅事实：${it.catalogName || it.selectedCatalogId || "已确认"}`;
      }
      if (res.recordId) {
        loadSettlementReview(res.recordId, (dashboard.review && dashboard.review.source) || "current");
      }
    } else {
      if (status) {
        status.textContent = res.message || "审阅操作失败";
      }
    }
  }
  if (payload.mascotPresentation && dashboard.mascotPresentation === null) {
    configureMascotPresentation(payload.mascotPresentation);
  }
  if (typeof payload.overlayVisible === "boolean") {
    renderOverlayState(payload.overlayVisible);
  }
  if (typeof payload.mainPinned === "boolean") {
    renderPinState(payload.mainPinned);
  }
  if (payload.action === "delete_history_record" && payload.deleteResult) {
    if (payload.deleteResult.ok) {
      closeDeleteRecordModal();
      if (dashboard.selectedRecord) {
        dashboard.selectedHistoryRecords.delete(
          historySelectionKey(
            dashboard.selectedRecord.key || dashboard.selectedRecord.id,
            dashboard.selectedRecord.kind || "current",
          ),
        );
      }
      dashboard.selectedRecordId = null;
      dashboard.selectedLegacyKey = null;
      dashboard.selectedRecord = null;
      const placeholder = document.getElementById("history-detail-placeholder");
      const detailCard = document.getElementById("history-detail-card");
      if (placeholder) placeholder.hidden = false;
      if (detailCard) detailCard.hidden = true;
      if (payload.legacyArchive) {
        renderLegacyArchive(payload.legacyArchive);
      } else if (payload.deleteResult.isLegacy) {
        postNative("request_legacy_archive");
      }
      postNative("request_app_status");
    } else {
      const errorEl = document.getElementById("delete-modal-error");
      if (errorEl) {
        errorEl.textContent = payload.deleteResult.message || "删除失败，请稍后重试";
        errorEl.hidden = false;
      }
    }
  }
  if (payload.labelsExportResult) {
    const result = payload.labelsExportResult;
    const button = document.getElementById("history-labels-export-btn");
    const status = document.getElementById("history-labels-export-status");
    if (button) button.disabled = result.status === "STARTED";
    if (status) status.textContent = result.status === "STARTED" ? "正在导出人工确认样本…"
      : result.status === "CANCELLED" ? "已取消导出。"
      : result.ok ? `已导出 ${result.sampleCount} 份人工确认样本；未确认和自动结果未作为人工标签。${result.readiness === "INSUFFICIENT_EVIDENCE" ? "当前样本量不足。" : ""}`
      : (result.message || "导出失败，请重试。");
  }
  if (payload.action === "export_history_records" && payload.exportResult) {
    const res = payload.exportResult;
    const status = document.getElementById("history-export-status");
    const button = document.getElementById("history-export-btn");
    if (button) button.disabled = res.status === "STARTED";
    if (status) {
      if (res.status === "STARTED") {
        status.textContent = "正在导出全部历史对局及原始图片，请稍候…";
      } else if (res.ok && res.status === "SAVED") {
        if (res.bundleSchemaVersion) {
          status.textContent = `已导出 ${res.recordCount} 条对局及 ${res.imageCount || 0} 张图片：${res.outputPath || "已保存"}`;
        } else {
          status.textContent = `已导出 ${res.recordCount} 条本地对局。`;
        }
      } else if (res.status === "CANCELLED") {
        status.textContent = "已取消导出。";
      } else {
        status.textContent = res.message || "导出失败，请检查保存位置后重试。";
      }
    }
  }
  if (payload.action === "delete_history_records" && payload.deleteBatchResult) {
    const res = payload.deleteBatchResult;
    const status = document.getElementById("history-export-status");
    if (res.ok) {
      closeDeleteRecordModal();
      dashboard.selectedHistoryRecords.clear();
      dashboard.selectedRecordId = null;
      dashboard.selectedLegacyKey = null;
      dashboard.selectedRecord = null;
      const placeholder = document.getElementById("history-detail-placeholder");
      const detailCard = document.getElementById("history-detail-card");
      if (placeholder) placeholder.hidden = false;
      if (detailCard) detailCard.hidden = true;
      if (status) status.textContent = res.message || `已删除 ${res.deletedCount || 0} 条对局记录。`;
      if (payload.legacyArchive) renderLegacyArchive(payload.legacyArchive);
      else if (res.legacyDeleted) postNative("request_legacy_archive");
      postNative("request_app_status");
    } else {
      const errorEl = document.getElementById("delete-modal-error");
      if (errorEl) {
        errorEl.textContent = res.message || "批量删除失败，请稍后重试";
        errorEl.hidden = false;
      }
    }
    updateHistorySelectionControls();
  }
  if (payload.action === "import_history_bundle" && payload.importResult) {
    const res = payload.importResult;
    const status = document.getElementById("history-export-status");
    const button = document.getElementById("history-import-btn");
    if (button) button.disabled = res.status === "STARTED";
    if (status) {
      if (res.status === "STARTED") {
        status.textContent = "正在导入对局及原始图片，请稍候…";
      } else if (res.ok && res.status === "SAVED") {
        status.textContent = `已导入 ${res.importedRecordCount || 0} 条新对局，跳过 ${res.skippedRecordCount || 0} 条重复记录，关联 ${res.imageCount || 0} 张图片。`;
        // Refresh only the history snapshot. Import must not trigger a live
        // vision force-refresh while the user is playing.
        postNative("request_app_status");
      } else if (res.status === "CANCELLED") {
        status.textContent = "已取消导入。";
      } else {
        status.textContent = res.message || "导入失败，未覆盖现有对局。";
      }
    }
  }
  if (payload.mainViewState) {
    dashboard.lastMainViewState = payload.mainViewState;
    renderOverview(payload.mainViewState);
    renderHistory(payload.mainViewState);
    renderAnalysis(payload.mainViewState);
  }
  if (payload.currentMatch) {
    renderMatch(payload.currentMatch, dashboard.overlayVisible);
  }
  if (payload.warehouseCapture) {
    renderWarehouseCapture(payload.warehouseCapture);
  }
  if (payload.warehouseCaptureCommand) {
    const cmd = payload.warehouseCaptureCommand;
    const confirm = document.getElementById("warehouse-capture-confirm");
    const message = document.getElementById("warehouse-capture-message");
    const manualConfirm = document.getElementById("warehouse-manual-confirm");
    const manualMsg = document.getElementById("warehouse-manual-message");
    if (cmd.reason === "MANUAL_READY") {
      if (manualConfirm) manualConfirm.hidden = false;
    } else if (cmd.reason && cmd.reason.startsWith("DISABLED_") && !cmd.armingToken) {
      if (manualMsg && cmd.message) manualMsg.textContent = cmd.message;
    }
    if (cmd.ok && cmd.armingToken) {
      dashboard.warehouseArmingToken = cmd.armingToken;
      if (confirm) confirm.hidden = false;
    } else {
      dashboard.warehouseArmingToken = null;
      if (confirm) confirm.hidden = true;
      if (message && cmd.message && cmd.reason !== "MANUAL_READY") message.textContent = cmd.message;
    }
  }
  if (payload.warehouseIdentityReview && payload.requestId === dashboard.latestWarehouseRequestId) {
    renderWarehouseIdentityReview(payload.warehouseIdentityReview);
    const pending = dashboard.pendingWarehouseHistoryRefresh;
    const result = payload.warehouseIdentityReview;
    if (pending && result.sessionId === pending.sessionId && result.persisted) {
      dashboard.pendingWarehouseHistoryRefresh = null;
      if (dashboard.review?.recordId === pending.recordId) {
        postNative("request_settlement_review", { recordId: pending.recordId, source: "current" });
      }
    }
  }
  applyAutomaticMascotState(payload);
  if (payload.applicationState === "shutting_down") {
    if (dashboard.statusPollTimer !== null) {
      window.clearInterval(dashboard.statusPollTimer);
      dashboard.statusPollTimer = null;
    }
    document.getElementById("overlay-toggle").disabled = true;
    setBridgeState("error", "正在安全退出");
  } else {
    setBridgeState("ready", "桌面服务已连接");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.viewTarget));
  });
  document.querySelectorAll("[data-guidebook-tab]").forEach(button => {
    button.addEventListener("click", () => setGuidebookTab(button.dataset.guidebookTab));
  });
  document.querySelectorAll("[data-guidebook-rarity]").forEach(button => {
    button.addEventListener("click", () => {
      dashboard.guidebookRarity = button.dataset.guidebookRarity || "all";
      document.querySelectorAll("[data-guidebook-rarity]").forEach(candidate => {
        candidate.classList.toggle("is-active", candidate === button);
      });
      renderGuidebookCatalog();
    });
  });
  const guidebookSearch = document.getElementById("guidebook-catalog-search");
  if (guidebookSearch) guidebookSearch.addEventListener("input", () => {
    dashboard.guidebookSearch = guidebookSearch.value || "";
    renderGuidebookCatalog();
  });
  const guidebookCategory = document.getElementById("guidebook-category-filter");
  if (guidebookCategory) guidebookCategory.addEventListener("change", () => {
    dashboard.guidebookCategory = guidebookCategory.value || "all";
    renderGuidebookCatalog();
  });
  const guidebookGrid = document.getElementById("guidebook-grid-filter");
  if (guidebookGrid) guidebookGrid.addEventListener("change", () => {
    dashboard.guidebookGridSize = guidebookGrid.value || "all";
    renderGuidebookCatalog();
  });
  const guidebookAssistant = document.getElementById("guidebook-open-assistant");
  if (guidebookAssistant) guidebookAssistant.addEventListener("click", () => showView("match"));
  const admissionActions = document.getElementById("match-admission-actions");
  if (admissionActions) admissionActions.addEventListener("click", event => {
    const button = event.target.closest("[data-admission-jump]");
    if (button) focusAdmissionControl(button.dataset.admissionJump);
  });
  document.querySelectorAll("[data-nav-action]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.navAction));
  });
  document.querySelectorAll("[data-mascot-state]").forEach((button) => {
    button.addEventListener("click", () => setMascotState(button.dataset.mascotState));
  });
  const pinButton = document.getElementById("pin-toggle");
  if (pinButton) {
    pinButton.addEventListener("click", () => {
      postNative("toggle_main_pin");
    });
  }
  const overlayButton = document.getElementById("overlay-toggle");
  overlayButton.addEventListener("click", () => {
    postNative("toggle_overlay");
  });
  const wirPrev = document.getElementById("wir-prev");
  const wirNext = document.getElementById("wir-next");
  if (wirPrev) wirPrev.addEventListener("click", () => {
    dashboard.pendingOverrideConfirm = false;
    postWarehouseReview("prev_track");
  });
  if (wirNext) wirNext.addEventListener("click", () => {
    dashboard.pendingOverrideConfirm = false;
    postWarehouseReview("next_track");
  });
  if (document.getElementById("wir-candidates")) {
    document.getElementById("wir-candidates").addEventListener("click", (event) => {
      const node = event.target.closest("[data-candidate]");
      if (!node) return;
      dashboard.pendingOverrideConfirm = false;
      postWarehouseReview("select_candidate", { selectedCatalogId: node.getAttribute("data-candidate") });
    });
  }
  if (document.getElementById("wir-thumbs")) {
    document.getElementById("wir-thumbs").addEventListener("click", (event) => {
      const node = event.target.closest("[data-obs]");
      if (node && node.getAttribute("data-obs")) postWarehouseReview("select_observation", { observationId: node.getAttribute("data-obs") });
    });
  }
  const wirConfirm = document.getElementById("wir-confirm-candidate");
  if (wirConfirm) wirConfirm.addEventListener("click", () => {
    const selected = (dashboard.warehouseReview && dashboard.warehouseReview.candidates || []).find((item) => item.selected);
    if (!selected) return;
    if (selected.requiresOverride) {
      wirRevealReason("override");
      document.getElementById("wir-exception").open = true;
      postWarehouseReview("select_override", { selectedCatalogId: selected.candidateId });
      document.getElementById("wir-message").textContent = "该藏品的图鉴尺寸待核对，请选择人工核准理由后确认。";
      return;
    }
    postWarehouseReview("apply", { reviewAction: "CONFIRM_CANDIDATE", selectedCatalogId: selected.candidateId, confirmCandidate: true });
  });
  const wirOverride = document.getElementById("wir-override");
  if (wirOverride) wirOverride.addEventListener("click", () => {
    const box = document.getElementById("wir-reason-box");
    const hit = document.querySelector(".wir-hit.is-selected");
    const reason = document.getElementById("wir-override-reason");
    if (!box || box.hidden || dashboard.pendingReasonKind !== "override") {
      wirRevealReason("override");
      return;
    }
    if (!hit || !reason || !reason.value) return;
    if (!dashboard.pendingOverrideConfirm) {
      dashboard.pendingOverrideConfirm = true;
      wirOverride.textContent = "明确覆盖确认";
      return;
    }
    postWarehouseReview("apply", {
      reviewAction: "CONFIRM_CATALOG_OVERRIDE",
      selectedCatalogId: hit.getAttribute("data-override"),
      overrideReason: reason.value,
      confirmedByHuman: true,
      confirmOverride: true
    });
    dashboard.pendingOverrideConfirm = false;
    dashboard.pendingReasonKind = null;
  });
  ["wir-out", "wir-exclude", "wir-flag"].forEach((id, index) => {
    const node = document.getElementById(id);
    if (!node) return;
    const actions = ["MARK_OUT_OF_CATALOG", "EXCLUDE_FALSE_COMPONENT", "FLAG_GEOMETRY_ERROR"];
    const kinds = ["out", "exclude", "flag"];
    node.addEventListener("click", () => {
      const box = document.getElementById("wir-reason-box");
      const text = document.getElementById("wir-reason");
      if (!box || box.hidden || dashboard.pendingReasonKind !== kinds[index] || !(text && text.value.trim())) {
        wirRevealReason(kinds[index]);
        return;
      }
      postWarehouseReview("apply", { reviewAction: actions[index], reason: text.value });
      dashboard.pendingReasonKind = null;
    });
  });
  const wirDefer = document.getElementById("wir-defer");
  if (wirDefer) wirDefer.addEventListener("click", () => {
    dashboard.pendingReasonKind = null;
    postWarehouseReview("apply", { reviewAction: "DEFER" });
  });
  const wirUndo = document.getElementById("wir-undo");
  if (wirUndo) wirUndo.addEventListener("click", () => {
    dashboard.pendingOverrideConfirm = false;
    dashboard.pendingReasonKind = null;
    postWarehouseReview("undo");
  });
  const wirSearch = document.getElementById("wir-search-btn");
  if (wirSearch) wirSearch.addEventListener("click", () => {
    const input = document.getElementById("wir-search-input");
    dashboard.pendingOverrideConfirm = false;
    postWarehouseReview("search", { query: input ? input.value : "" });
  });
  const wirHits = document.getElementById("wir-search-hits");
  if (wirHits) wirHits.addEventListener("click", (event) => {
    const node = event.target.closest(".wir-hit");
    if (!node) return;
    dashboard.pendingOverrideConfirm = false;
    postWarehouseReview("select_override", { selectedCatalogId: node.getAttribute("data-override") });
  });
  const wirFilter = document.getElementById("wir-filter-unresolved");
  if (wirFilter) wirFilter.addEventListener("change", () => postWarehouseReview("filter_unresolved", { filterUnresolved: wirFilter.checked }));
  const wirFinalize = document.getElementById("wir-finalize");
  if (wirFinalize) wirFinalize.addEventListener("click", () => {
    dashboard.wirSaveConfirmOpen = false;
    postWarehouseReview("finalize");
  });
  const wirSave = document.getElementById("wir-save");
  if (wirSave) wirSave.addEventListener("click", () => {
    const view = dashboard.warehouseReview || {};
    if (!view.artifactReady || !view.persistenceAvailable || view.persisted) return;
    dashboard.wirSaveConfirmOpen = true;
    const box = document.getElementById("wir-save-confirm");
    if (box) box.hidden = false;
  });
  const wirSaveCancel = document.getElementById("wir-save-cancel");
  if (wirSaveCancel) wirSaveCancel.addEventListener("click", () => {
    dashboard.wirSaveConfirmOpen = false;
    const box = document.getElementById("wir-save-confirm");
    if (box) box.hidden = true;
  });
  const wirSaveConfirmBtn = document.getElementById("wir-save-confirm-btn");
  if (wirSaveConfirmBtn) wirSaveConfirmBtn.addEventListener("click", () => {
    dashboard.wirSaveConfirmOpen = false;
    const box = document.getElementById("wir-save-confirm");
    if (box) box.hidden = true;
    postWarehousePersist();
  });
  const warehouseToggle = document.getElementById("warehouse-capture-toggle");
  if (warehouseToggle) {
    warehouseToggle.addEventListener("click", () => {
      const slot = document.getElementById("warehouse-capture-slot");
      if (!slot || warehouseToggle.disabled || slot.dataset.available !== "true") return;
      const running = slot.dataset.state && ["STARTING", "CAPTURING", "SCROLLING", "WAITING", "ALIGNING"].includes(slot.dataset.state);
      if (running) {
        postNative("stop_warehouse_capture");
        return;
      }
      postNative("prepare_warehouse_capture");
    });
  }
  const warehouseCancel = document.getElementById("warehouse-capture-cancel");
  if (warehouseCancel) {
    warehouseCancel.addEventListener("click", () => {
      dashboard.warehouseArmingToken = null;
      const box = document.getElementById("warehouse-capture-confirm");
      if (box) box.hidden = true;
    });
  }
  const warehouseConfirm = document.getElementById("warehouse-capture-confirm-btn");
  if (warehouseConfirm) {
    warehouseConfirm.addEventListener("click", () => {
      const token = dashboard.warehouseArmingToken;
      const box = document.getElementById("warehouse-capture-confirm");
      if (box) box.hidden = true;
      if (!token) return;
      postNative("confirm_warehouse_capture", { armingToken: token });
      dashboard.warehouseArmingToken = null;
    });
  }
  const manualStartBtn = document.getElementById("warehouse-manual-start-btn");
  if (manualStartBtn) {
    manualStartBtn.addEventListener("click", () => {
      postNative("prepare_warehouse_manual_takeover");
    });
  }
  const manualConfirmCancel = document.getElementById("warehouse-manual-confirm-cancel");
  if (manualConfirmCancel) {
    manualConfirmCancel.addEventListener("click", () => {
      const confirm = document.getElementById("warehouse-manual-confirm");
      if (confirm) confirm.hidden = true;
    });
  }
  const manualConfirmBtn = document.getElementById("warehouse-manual-confirm-btn");
  if (manualConfirmBtn) {
    manualConfirmBtn.addEventListener("click", () => {
      const confirm = document.getElementById("warehouse-manual-confirm");
      if (confirm) confirm.hidden = true;
      postNative("start_warehouse_manual_takeover");
    });
  }
  const manualSnapBtn = document.getElementById("warehouse-manual-snap-btn");
  if (manualSnapBtn) {
    manualSnapBtn.addEventListener("click", () => {
      postNative("capture_warehouse_manual_page");
    });
  }
  const manualFinishBtn = document.getElementById("warehouse-manual-finish-btn");
  if (manualFinishBtn) {
    manualFinishBtn.addEventListener("click", () => {
      postNative("finish_warehouse_manual_capture");
    });
  }
  const manualCancelBtn = document.getElementById("warehouse-manual-cancel-btn");
  if (manualCancelBtn) {
    manualCancelBtn.addEventListener("click", () => {
      postNative("cancel_warehouse_manual_capture");
    });
  }
  const matchOverlayBtn = document.getElementById("match-live-overlay-toggle");
  if (matchOverlayBtn) {
    matchOverlayBtn.addEventListener("click", () => {
      postNative("toggle_overlay");
    });
  }

  const deleteBtn = document.getElementById("detail-delete-btn");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", openDeleteRecordModal);
  }
  const modalCancelBtn = document.getElementById("delete-modal-cancel-btn");
  if (modalCancelBtn) {
    modalCancelBtn.addEventListener("click", closeDeleteRecordModal);
  }
  const modalConfirmBtn = document.getElementById("delete-modal-confirm-btn");
  if (modalConfirmBtn) {
    modalConfirmBtn.addEventListener("click", confirmDeleteRecord);
  }
  const historySelectAll = document.getElementById("history-select-all");
  if (historySelectAll) {
    historySelectAll.addEventListener("change", () => {
      const checked = historySelectAll.checked;
      document.querySelectorAll("#history-list .history-record-checkbox").forEach((checkbox) => {
        if (checkbox.disabled || checkbox.hidden) return;
        checkbox.checked = checked;
        setHistorySelection(checkbox.dataset.recordId, checkbox.dataset.source, checked);
      });
      updateHistorySelectionControls();
    });
  }
  const historyDeleteSelectedBtn = document.getElementById("history-delete-selected-btn");
  if (historyDeleteSelectedBtn) {
    historyDeleteSelectedBtn.addEventListener("click", openBatchDeleteRecordModal);
  }

  const historyFilterBtn = document.getElementById("history-filter-toggle");
  if (historyFilterBtn) {
    historyFilterBtn.addEventListener("click", toggleHistoryFilter);
  }
  const legacyToggleBtn = document.getElementById("legacy-archive-toggle");
  if (legacyToggleBtn) {
    legacyToggleBtn.addEventListener("click", toggleLegacyArchive);
  }
  document.querySelectorAll(".filter-source").forEach((btn) => {
    btn.addEventListener("click", () => setHistorySource(btn.dataset.source));
  });
  initCustomDropdowns();
  const filterSearch = document.getElementById("filter-search");
  if (filterSearch) {
    filterSearch.addEventListener("input", () => {
      dashboard.historyFilter.search = filterSearch.value.trim();
      applyHistoryFilters();
    });
  }
  const filterDebug = document.getElementById("filter-debug");
  if (filterDebug) {
    filterDebug.addEventListener("change", () => {
      dashboard.historyFilter.debug = filterDebug.checked;
      applyHistoryFilters();
    });
  }
  const historyExportBtn = document.getElementById("history-export-btn");
  const labelsExportBtn = document.getElementById("history-labels-export-btn");
  if (labelsExportBtn) labelsExportBtn.addEventListener("click", () => {
    if (labelsExportBtn.disabled) return;
    labelsExportBtn.disabled = true;
    document.getElementById("history-labels-export-status").textContent = "请选择人工样本包保存位置。";
    postNative("export_reviewed_labels", { outputPath: labelsExportBtn.dataset.outputPath || undefined });
  });
  if (historyExportBtn) {
    historyExportBtn.addEventListener("click", () => {
      const status = document.getElementById("history-export-status");
      if (historyExportBtn.disabled) return;
      historyExportBtn.disabled = true;
      if (status) status.textContent = "请选择保存位置；将导出全部历史对局及其原始图片。";
      const customPath = historyExportBtn.dataset.outputPath || historyExportBtn.getAttribute("data-output-path");
      postNative("export_history_records", {
        recordIds: [],
        outputPath: customPath || undefined,
      });
    });
  }
  const historyImportBtn = document.getElementById("history-import-btn");
  if (historyImportBtn) {
    historyImportBtn.addEventListener("click", () => {
      const status = document.getElementById("history-export-status");
      if (historyImportBtn.disabled) return;
      historyImportBtn.disabled = true;
      if (status) status.textContent = "请选择对局数据包；导入会保留现有记录，不覆盖冲突。";
      postNative("import_history_bundle");
    });
  }
  const settlementScreenshotBtn = document.getElementById("match-btn-save-settlement-screenshot");
  if (settlementScreenshotBtn) {
    settlementScreenshotBtn.addEventListener("click", () => {
      if (settlementScreenshotBtn.disabled) return;
      settlementScreenshotBtn.disabled = true;
      const status = document.getElementById("match-settlement-screenshot-status");
      if (status) {
        status.textContent = "正在保存当前结算原图…不会等待识别";
        status.style.color = "";
      }
      postNative("save_settlement_screenshot");
    });
  }
  const gameScreenshotBtn = document.getElementById("match-btn-save-game-screenshot");
  if (gameScreenshotBtn) {
    gameScreenshotBtn.addEventListener("click", () => {
      if (gameScreenshotBtn.disabled) return;
      gameScreenshotBtn.disabled = true;
      const status = document.getElementById("match-game-screenshot-status");
      if (status) {
        status.textContent = "正在保存异环原图…不会等待识别";
        status.style.color = "";
      }
      postNative("save_game_screenshot");
    });
  }
  const reviewImportBtn = document.getElementById("review-import-btn");
  if (reviewImportBtn) {
    reviewImportBtn.addEventListener("click", importScreenshot);
  }
  const reviewReplaceBtn = document.getElementById("review-replace-btn");
  if (reviewReplaceBtn) {
    reviewReplaceBtn.addEventListener("click", replaceScreenshot);
  }
  const reviewRerecognizeBtn = document.getElementById("review-rerecognize-btn");
  if (reviewRerecognizeBtn) {
    reviewRerecognizeBtn.addEventListener("click", rerunSettlementRecognition);
  }
  const reviewDeleteBtn = document.getElementById("review-delete-btn");
  if (reviewDeleteBtn) {
    reviewDeleteBtn.addEventListener("click", deleteScreenshot);
  }
  const reviewSaveBtn = document.getElementById("review-save-btn");
  if (reviewSaveBtn) {
    reviewSaveBtn.addEventListener("click", saveReviewedSettlement);
  }
  const reviewResetBtn = document.getElementById("review-reset-btn");
  if (reviewResetBtn) {
    reviewResetBtn.addEventListener("click", resetReviewEdits);
  }

  // History Main Tabs
  document.querySelectorAll(".history-main-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".history-main-tab").forEach((t) => t.classList.remove("is-active"));
      tab.classList.add("is-active");
      dashboard.historyFilter.primaryTab = tab.dataset.historyTab;
      applyHistoryFilters();
    });
  });

  // History Custom Date Inputs
  const dateStart = document.getElementById("filter-date-start");
  const dateEnd = document.getElementById("filter-date-end");
  if (dateStart) {
    dateStart.addEventListener("change", () => {
      dashboard.historyFilter.startDate = dateStart.value;
      applyHistoryFilters();
    });
  }
  if (dateEnd) {
    dateEnd.addEventListener("change", () => {
      dashboard.historyFilter.endDate = dateEnd.value;
      applyHistoryFilters();
    });
  }

  // Match Form Inputs & Stepper Binding
  [
    "match-input-q",
    "match-input-purple-count",
    "match-input-purple-avg",
    "match-input-gold-avg",
    "match-sparkle-count", "match-sparkle-names",
    "match-input-private-bid-cap",
    "match-input-bid-action-count",
    "match-input-welfare-received",
    "match-input-blue-count",
    "match-input-gold-count",
    "match-input-red-count",
    "match-input-total-items",
    "match-input-total-grid",

    "match-input-gold-grid",
    "match-input-purple-grid",
    "match-input-white-count",
    "match-input-white-avg",
    "match-input-white-grid",
    "match-input-green-count",
    "match-input-green-avg",
    "match-input-green-grid",
    "match-input-blue-avg",
    "match-input-blue-grid",
    "match-input-red-grid"
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => syncMatchFactsDebounced(250));
      el.addEventListener("change", () => ["match-input-welfare-received", "match-input-private-bid-cap", "match-input-bid-action-count"].includes(id) ? syncMatchFacts() : syncMatchFactsDebounced(50));
      if (["match-input-welfare-received", "match-input-private-bid-cap", "match-input-bid-action-count"].includes(id)) el.addEventListener("blur", syncMatchFacts);
    }
  });

  const playerNameInput = document.getElementById("player-display-name");
  if (playerNameInput) {
    playerNameInput.addEventListener("input", () => {
      dashboard.isPlayerNameEditing = true;
    });
    playerNameInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        savePlayerDisplayName();
      }
    });
    playerNameInput.addEventListener("blur", () => {
      if (dashboard.lastCurrentMatch && (playerNameInput.value || "").trim() === (dashboard.lastCurrentMatch.configuredPlayerName || "")) {
        dashboard.isPlayerNameEditing = false;
      }
    });
  }
  const savePlayerBtn = document.getElementById("save-player-display-name");
  if (savePlayerBtn) {
    savePlayerBtn.addEventListener("click", savePlayerDisplayName);
  }

  // Overview CTA button bindings
  const overviewResumeBtn = document.getElementById("overview-btn-resume");
  if (overviewResumeBtn) overviewResumeBtn.addEventListener("click", () => showView("match"));
  const overviewStartBtn = document.getElementById("overview-btn-start");
  if (overviewStartBtn) overviewStartBtn.addEventListener("click", () => showView("match"));
  const overviewHistoryBtn = document.getElementById("overview-btn-history");
  if (overviewHistoryBtn) overviewHistoryBtn.addEventListener("click", () => showView("history"));
  const overviewQuickNewBtn = document.getElementById("overview-btn-quick-new");
  if (overviewQuickNewBtn) overviewQuickNewBtn.addEventListener("click", openNextMatchModal);

  // Match Snapshot Assist Hero Button Binding
  const matchSnapshotBtn = document.getElementById("match-btn-snapshot");
  if (matchSnapshotBtn) {
    matchSnapshotBtn.addEventListener("click", () => {
      if (matchSnapshotBtn.disabled || matchSnapshotBtn.classList.contains("is-recognizing")) return;
      renderSnapshotAssistResult({
        ok: true,
        status: "recognizing",
        summary: "正在快照识别游戏画面...",
      });
      postNative("triggered_snapshot");
    });
  }

  // Setup Known Items Autocomplete & Chip Interaction
  setupKnownItemsAutocomplete();

  // Valuation Drawer Binding (Sliding Drawer on Right)
  const openDrawerBtn = document.getElementById("match-btn-open-drawer");
  const drawerEl = document.getElementById("valuation-drawer");
  const drawerBackdrop = document.getElementById("valuation-drawer-backdrop");
  const drawerCloseBtn = document.getElementById("valuation-drawer-close");

  function openValuationDrawer() {
    if (drawerEl) drawerEl.classList.add("is-open");
    if (drawerEl) drawerEl.setAttribute("aria-hidden", "false");
    if (drawerBackdrop) drawerBackdrop.classList.add("is-open");
    if (openDrawerBtn) openDrawerBtn.setAttribute("aria-expanded", "true");
  }
  function closeValuationDrawer() {
    if (drawerEl) drawerEl.classList.remove("is-open");
    if (drawerEl) drawerEl.setAttribute("aria-hidden", "true");
    if (drawerBackdrop) drawerBackdrop.classList.remove("is-open");
    if (openDrawerBtn) openDrawerBtn.setAttribute("aria-expanded", "false");
  }

  if (openDrawerBtn) openDrawerBtn.addEventListener("click", openValuationDrawer);
  if (drawerCloseBtn) drawerCloseBtn.addEventListener("click", closeValuationDrawer);
  if (drawerBackdrop) drawerBackdrop.addEventListener("click", closeValuationDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeValuationDrawer();
    }
  });

  // Collapsible Section Headers Binding
  document.querySelectorAll(".section-header-clickable").forEach((header) => {
    header.addEventListener("click", () => {
      const section = header.closest(".detail-section");
      if (section) {
        section.classList.toggle("collapsed");
      }
    });
  });

  // Section F: Open Settle Modal Shortcut
  const openSettleBtn = document.getElementById("match-btn-open-settle-modal");
  if (openSettleBtn) {
    openSettleBtn.addEventListener("click", openSettleMatchModal);
  }

  // Section G: Go to History View Shortcut
  const gotoHistoryBtn = document.getElementById("match-btn-goto-history");
  if (gotoHistoryBtn) {
    gotoHistoryBtn.addEventListener("click", () => {
      showView("history");
    });
  }

  document.querySelectorAll(".stepper-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.stepTarget;
      const step = Number(btn.dataset.step || 1);
      const inputEl = document.getElementById(targetId);
      if (inputEl) {
        const curr = Number(inputEl.value) || 0;
        const min = inputEl.min !== "" ? Number(inputEl.min) : 0;
        const max = inputEl.max !== "" ? Number(inputEl.max) : Infinity;
        const next = Math.max(min, Math.min(max, curr + step));
        inputEl.value = next;
        syncMatchFacts();
      }
    });
  });

  // Next Match & Settle Modals Binding
  const matchNextBtn = document.getElementById("match-btn-next");
  if (matchNextBtn) {
    matchNextBtn.addEventListener("click", openNextMatchModal);
  }
  const nextModalKeepBtn = document.getElementById("next-modal-keep-btn");
  if (nextModalKeepBtn) {
    nextModalKeepBtn.addEventListener("click", () => {
      const payload = { expectedMatchId: dashboard.matchState.matchId, disposition: "keep_draft" };
      postNative("manual_next_match", payload);
      closeNextMatchModal();
    });
  }
  const nextModalDiscardBtn = document.getElementById("next-modal-discard-btn");
  if (nextModalDiscardBtn) {
    nextModalDiscardBtn.addEventListener("click", () => {
      const payload = { expectedMatchId: dashboard.matchState.matchId, disposition: "discard" };
      postNative("manual_next_match", payload);
      closeNextMatchModal();
    });
  }
  const nextModalCloseBtn = document.getElementById("next-modal-close-btn");
  if (nextModalCloseBtn) {
    nextModalCloseBtn.addEventListener("click", closeNextMatchModal);
  }

  const matchSettleBtn = document.getElementById("match-btn-settle");
  if (matchSettleBtn) {
    matchSettleBtn.addEventListener("click", openSettleMatchModal);
  }
  const settleToggleEditBtn = document.getElementById("settle-modal-toggle-edit-btn");
  if (settleToggleEditBtn) {
    settleToggleEditBtn.addEventListener("click", toggleManualSettleEdit);
  }
  const settleConfirmBtn = document.getElementById("settle-modal-confirm-btn");
  if (settleConfirmBtn) {
    settleConfirmBtn.addEventListener("click", confirmSettleMatch);
  }
  const settleKeepDraftBtn = document.getElementById("settle-modal-keep-draft-btn");
  if (settleKeepDraftBtn) {
    settleKeepDraftBtn.addEventListener("click", keepDraftAndStartNextMatch);
  }
  const settleCancelBtn = document.getElementById("settle-modal-cancel-btn");
  if (settleCancelBtn) {
    settleCancelBtn.addEventListener("click", closeSettleMatchModal);
  }

  function initBridge(attempts = 0) {
    if (dashboard.bridgeInitialized) return;
    if (isBridgeReady()) {
      dashboard.bridgeInitialized = true;
      dashboard.bridgeReady = true;
      window.chrome.webview.addEventListener("message", handleNativeMessage);
      postNative("get_overlay_visibility");
      postNative("request_app_status");
      if (dashboard.statusPollTimer === null) {
        dashboard.statusPollTimer = window.setInterval(
          () => postNative("request_app_status"),
          750
        );
      }
      setBridgeState("ready", "桌面服务已连接");
      if (new URLSearchParams(window.location.search).get("smoke") === "overlay-toggle") {
        const smokeClick = (remaining) => {
          if (overlayButton.disabled) {
            window.setTimeout(() => smokeClick(remaining), 100);
            return;
          }
          overlayButton.click();
          if (remaining > 1) window.setTimeout(() => smokeClick(remaining - 1), 700);
        };
        window.setTimeout(() => smokeClick(2), 350);
      }
    } else if (attempts < 20) {
      window.setTimeout(() => initBridge(attempts + 1), 100);
    } else {
      setBridgeState("error", "仅可在桌面应用内使用");
    }
  }

  initBridge();

  const urlParams = new URLSearchParams(window.location.search);
  const initialView = urlParams.get("view");
  if (initialView) {
    showView(initialView);
  }
  if (urlParams.get("drawer") === "open") {
    openValuationDrawer();
  }
});

window.addEventListener("beforeunload", () => {
  if (dashboard.statusPollTimer !== null) {
    window.clearInterval(dashboard.statusPollTimer);
    dashboard.statusPollTimer = null;
  }
});
