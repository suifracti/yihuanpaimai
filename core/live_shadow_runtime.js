/**
 * Live Historical Shadow runtime.
 * Loads history once, reuses Lab expand/stateComponents, then calls Shared Core.
 * HUD must never load this file.
 *
 * Persistent protocol: one JSON request per stdin line, one JSON response per stdout line.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const engine = require(path.join(__dirname, "auction_engine_v06.js"));
const shared = require(path.join(__dirname, "shadow_profile_v06.js"));
const computeModule = require(path.join(__dirname, "live_shadow_compute.js"));
let solverCore = null;

function installHeadlessHost() {
  if (typeof global.document !== "undefined") return;
  const el = () => ({
    value: "", options: [], children: [], dataset: {}, style: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, appendChild() {}, closest() { return null; }, reset() {}
  });
  global.window = global;
  global.addEventListener = () => {};
  global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  global.document = {
    documentElement: { dataset: {} },
    addEventListener() {},
    querySelector() { return el(); },
    getElementById() { return el(); },
    querySelectorAll() { return []; }
  };
}

function loadSolver() {
  installHeadlessHost();
  const core = require(path.join(__dirname, "solver_core_v06.js"));
  global.redProbabilityProfile = core.redProbabilityProfile;
  global.stateComponents = core.stateComponents;
  global.candidateStateWeight = core.candidateStateWeight;
  global.expandStatesForValuation = core.expandStatesForValuation;
  global.state = typeof core.getState === "function" ? core.getState() : global.state;
  return core;
}

function compute(req, records) {
  return computeModule.compute(req, records, global, engine, shared, "live_shadow_runtime");
}

function resolveKnownIdentity(req) {
  const item = solverCore && typeof solverCore.resolveKnownCatalogItem === "function"
    ? solverCore.resolveKnownCatalogItem(req.ctx || {}, req.quality, req.name)
    : null;
  return { ok: true, available: Boolean(item), item: item || null };
}

function loadRecords(dbPath) {
  if (!dbPath || !fs.existsSync(dbPath)) return [];
  const raw = JSON.parse(fs.readFileSync(dbPath, "utf8"));
  return Array.isArray(raw) ? raw : (raw.records || []);
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

const args = process.argv.slice(2);
let dbPath = path.join(ROOT, "异环拍卖数据.json");
let once = false;
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--records" && args[i + 1]) dbPath = args[++i];
  if (args[i] === "--once") once = true;
}

solverCore = loadSolver();
let records = loadRecords(dbPath);

if (once) {
  const chunks = [];
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (c) => chunks.push(c));
  process.stdin.on("end", () => {
    try {
      const req = JSON.parse(chunks.join("") || "{}");
      emit(req && req.action === "resolveKnownIdentity" ? resolveKnownIdentity(req) : compute(req, records));
    } catch (error) {
      emit({ ok: false, error: String(error && error.message || error) });
      process.exitCode = 1;
    }
  });
} else {
  emit({ ok: true, ready: true, nRecords: records.length });
  const rl = require("readline").createInterface({ input: process.stdin });
  rl.on("line", (line) => {
    const text = String(line || "").trim();
    if (!text) return;
    try {
      const req = JSON.parse(text);
      if (req && req.action === "setRecords") {
        records = Array.isArray(req.records) ? req.records : [];
        emit({ ok: true, updated: true, nRecords: records.length });
        return;
      }
      if (req && req.action === "resolveKnownIdentity") {
        emit(resolveKnownIdentity(req));
        return;
      }
      emit(compute(req, records));
    } catch (error) {
      emit({ ok: false, error: String(error && error.message || error) });
    }
  });
}
