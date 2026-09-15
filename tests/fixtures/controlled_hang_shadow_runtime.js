/**
 * Controlled hang shadow runtime fixture for timeout & recovery testing.
 * 
 * If process.env.YIHUAN_HANG_TRIGGER_FILE exists on disk:
 *   Hangs on compute requests (never answers on stdout).
 * If the trigger file does not exist:
 *   Executes normal live shadow computation and emits valid prediction JSON.
 */
const fs = require("fs");
const path = require("path");

const CORE = path.resolve(__dirname, "..", "..", "core");
const engine = require(path.join(CORE, "auction_engine_v06.js"));
const shared = require(path.join(CORE, "shadow_profile_v06.js"));
const computeModule = require(path.join(CORE, "live_shadow_compute.js"));

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

installHeadlessHost();
const solverCore = require(path.join(CORE, "solver_core_v06.js"));
global.redProbabilityProfile = solverCore.redProbabilityProfile;
global.stateComponents = solverCore.stateComponents;
global.candidateStateWeight = solverCore.candidateStateWeight;
global.expandStatesForValuation = solverCore.expandStatesForValuation;
global.state = typeof solverCore.getState === "function" ? solverCore.getState() : global.state;

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function loadRecords(p) {
  if (!p || !fs.existsSync(p)) return [];
  try {
    const raw = JSON.parse(fs.readFileSync(p, "utf8"));
    return Array.isArray(raw) ? raw : (raw.records || []);
  } catch (e) {
    return [];
  }
}

const args = process.argv.slice(2);
let dbPath = path.join(CORE, "..", "异环拍卖数据.json");
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--records" && args[i + 1]) dbPath = args[++i];
}

let dbRecords = loadRecords(dbPath);
const triggerFile = process.env.YIHUAN_HANG_TRIGGER_FILE;

function shouldHang() {
  return Boolean(triggerFile && fs.existsSync(triggerFile));
}

emit({ ok: true, ready: true, nRecords: dbRecords.length });

const rl = require("readline").createInterface({ input: process.stdin });
rl.on("line", (line) => {
  const text = String(line || "").trim();
  if (!text) return;
  try {
    const req = JSON.parse(text);
    if (req.action === "setRecords") {
      dbRecords = Array.isArray(req.records) ? req.records : dbRecords;
      emit({ ok: true, updated: true, nRecords: dbRecords.length });
      return;
    }
    if (shouldHang()) {
      // Hang: deliberately emit nothing on stdout so caller experiences compute timeout
      return;
    }
    const delayMs = parseInt(process.env.YIHUAN_COMPUTE_DELAY_MS || "0", 10);
    if (delayMs > 0) {
      setTimeout(() => {
        try {
          const result = computeModule.compute(req, dbRecords, global, engine, shared, "controlled_hang_runtime");
          emit(result);
        } catch (err) {
          emit({ ok: false, error: String(err && err.message ? err.message : err) });
        }
      }, delayMs);
      return;
    }
    const result = computeModule.compute(req, dbRecords, global, engine, shared, "controlled_hang_runtime");
    emit(result);
  } catch (err) {
    emit({ ok: false, error: String(err && err.message ? err.message : err) });
  }
});
