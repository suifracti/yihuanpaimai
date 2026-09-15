"use strict";

// Experiment-only in-memory instrumentation. Production files are read only.
const fs = require("fs");

function mockDom() {
  const element = () => ({
    value: "", options: [], children: [], dataset: {}, style: {}, hidden: false,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, appendChild() {}, closest() { return null; }, reset() {},
    querySelector() { return element(); }, querySelectorAll() { return []; },
  });
  global.window = global;
  global.addEventListener = () => {};
  global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  global.document = {
    documentElement: { dataset: {} }, body: element(), addEventListener() {},
    getElementById() { return element(); }, querySelector() { return element(); },
    querySelectorAll() { return []; }, createElement() { return element(); },
  };
  global.requestAnimationFrame = callback => callback();
}

function exposeCurrentSolver() {
  mockDom();
  let source = fs.readFileSync("./core/solver_core_v06.js", "utf8");
  source = source
    .replace("let currentAnalysis = null;", "let currentAnalysis = null; global.__setAuditCurrentAnalysis = value => { currentAnalysis = value; };")
    .replace("let state = loadState();", "let state = loadState(); global.__auditState = state;")
    .replace("function replayContextFromRecord(r,snapshot=null,allowedHistoryIds=null){", "global.__replayContextFromRecord = function replayContextFromRecord(r,snapshot=null,allowedHistoryIds=null){")
    .replace("function analyzeContextWithSharedCore(ctx){", "global.__analyzeContextWithSharedCore = function analyzeContextWithSharedCore(ctx){");
  eval(source);
  if (!global.__auditState || !global.__replayContextFromRecord || !global.__analyzeContextWithSharedCore || !global.__setAuditCurrentAnalysis) {
    throw new Error("Failed to expose current replay boundary");
  }
}

function sameShadow(left, right) {
  return ["p20", "p50", "p80"].every(key => Number(left?.[key]) === Number(right?.[key]));
}

function matchingSnapshot(record) {
  const target = record?.prediction?.probabilityProfile?.shadowWhole;
  const matches = (record.rounds || []).filter(row => sameShadow(target, row?.prediction?.probabilityProfile?.shadowWhole));
  return matches.sort((a, b) => Number(a.round) - Number(b.round)).at(-1) || (record.rounds || []).at(-1) || null;
}

function slimState(state) {
  return { g: state.g ?? null, p: state.p ?? null, r: state.r ?? null, rMin: state.rMin ?? state.r ?? null, rMax: state.rMax ?? state.r ?? null };
}

function slimProfile(profile) {
  return {
    shadowWhole: profile?.shadowWhole ? { p20: profile.shadowWhole.p20, p50: profile.shadowWhole.p50, p80: profile.shadowWhole.p80, p95: profile.shadowWhole.p95, max: profile.shadowWhole.max } : null,
    coverageRatio: profile?.coverageRatio ?? null,
    stateCandidates: (profile?.stateCandidates || []).map(state => ({
      ...slimState(state), weight: state.weight ?? null, relativeWeight: state.relativeWeight ?? null,
      redMode: state.redMode ?? null,
      shadow: state.shadow ? { p80: state.shadow.p80, p95: state.shadow.p95, max: state.shadow.max } : null,
    })),
  };
}

function main() {
  exposeCurrentSolver();
  const database = JSON.parse(fs.readFileSync("./异环拍卖数据.json", "utf8"));
  const selected = new Set(JSON.parse(process.argv[2] || "[]"));
  global.__auditState.records = database.records || [];
  const records = global.__auditState.records;
  const rows = [];
  for (const record of records.filter(row => selected.has(row.id))) {
    const snapshot = matchingSnapshot(record);
    const playedAt = Date.parse(record.playedAt || record.date || "");
    const priorIds = new Set(records.filter(row => {
      const timestamp = Date.parse(row.playedAt || row.date || "");
      return Number.isFinite(timestamp) && Number.isFinite(playedAt) && timestamp < playedAt;
    }).map(row => row.id));
    try {
      const context = global.__replayContextFromRecord(record, snapshot, priorIds);
      // The production UI sets the live analysis object before decision-side
      // helpers are used. Offline replay has no render cycle, so provide only
      // the reconstructed context; candidate generation remains unchanged.
      global.__setAuditCurrentAnalysis(context);
      const solved = global.__analyzeContextWithSharedCore(context);
      const analysis = solved.analysis || {};
      rows.push({
        recordId: record.id, snapshotRound: snapshot?.round ?? null, error: solved.error || null,
        candidateGs: analysis.candidateGs || [], fullStateCount: analysis.fullStateCount ?? null,
        valuationStateCount: analysis.valuationStateCount ?? (analysis.candidates || []).length,
        valuationStateCompressed: analysis.valuationStateCompressed === true,
        candidates: (analysis.candidates || []).map(slimState),
        probabilityProfile: slimProfile(analysis.workingDecision?.probabilityProfile),
      });
    } catch (error) {
      rows.push({ recordId: record.id, snapshotRound: snapshot?.round ?? null, error: String(error?.stack || error) });
    }
  }
  process.stdout.write("\n__AUDIT_JSON__" + JSON.stringify({ rows }));
}

main();
