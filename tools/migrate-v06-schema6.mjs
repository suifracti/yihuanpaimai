import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const inputPath = path.resolve(process.argv[2] || "D:/yihuanpaimai/异环拍卖数据.json");
const backupPath = path.resolve(process.argv[3] || inputPath.replace(/\.json$/i, ".schema5.before-v06.json"));
const outputTemp = `${inputPath}.schema6.tmp`;
const TARGET_VERSION = "v0.6";
const TARGET_SCHEMA = 6;

function sha256(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

function readJson(file) {
  const raw = fs.readFileSync(file, "utf8").replace(/^\uFEFF/, "");
  return { raw, value: JSON.parse(raw) };
}

function latestRound(record) {
  return (Array.isArray(record?.rounds) ? record.rounds : [])
    .filter(x => Number.isInteger(Number(x?.round)))
    .slice()
    .sort((a, b) => Number(b.round) - Number(a.round))[0] || null;
}

function migrateRound(round, record, index) {
  const out = { ...round };
  const prediction = out.prediction && typeof out.prediction === "object" ? out.prediction : null;
  if (!Object.hasOwn(out, "solverVersion")) out.solverVersion = prediction?.solverVersion ?? record.solverVersion ?? null;
  if (!Object.hasOwn(out, "solverStatus")) out.solverStatus = prediction?.solverStatus ?? record.solverStatus ?? "legacy";
  if (!Object.hasOwn(out, "inputHash")) out.inputHash = prediction?.inputHash ?? record.inputHash ?? null;
  if (!Object.hasOwn(out, "diagnosticOnly")) out.diagnosticOnly = out.solverStatus === "diagnostic" || out.solverStatus === "diagnostic-no-match" || record.diagnosticOnly === true;
  if (out.diagnosticOnly && !Object.hasOwn(out, "diagnosticReport")) out.diagnosticReport = record.diagnosticReport || null;
  out.migrationAuditV06 = {
    ...(out.migrationAuditV06 || {}),
    index,
    sourcePreserved: true,
    predictionRecomputed: false,
  };
  return out;
}

function migrateRecord(record, index) {
  const out = { ...record };
  const latest = latestRound(record);
  const prediction = out.prediction && typeof out.prediction === "object" ? out.prediction : null;
  const roundStatus = latest?.solverStatus ?? latest?.prediction?.solverStatus ?? null;
  const roundHash = latest?.inputHash ?? latest?.prediction?.inputHash ?? null;

  // These are provenance/solver fields, not auction truth.  Missing legacy
  // solver metadata is explicitly marked legacy; no value, winner, payment,
  // or realized G/P/R field is inferred here.
  if (!Object.hasOwn(out, "solverVersion")) out.solverVersion = prediction?.solverVersion ?? latest?.solverVersion ?? null;
  if (!Object.hasOwn(out, "solverStatus")) out.solverStatus = prediction?.solverStatus ?? roundStatus ?? "legacy";
  if (!Object.hasOwn(out, "inputHash")) out.inputHash = prediction?.inputHash ?? roundHash ?? null;
  if (!Object.hasOwn(out, "targetProfit")) out.targetProfit = latest?.targetProfit ?? null;
  if (!Object.hasOwn(out, "diagnosticOnly")) out.diagnosticOnly = out.solverStatus === "diagnostic" || out.solverStatus === "diagnostic-no-match" || (Array.isArray(out.rounds) && out.rounds.some(x => x?.diagnosticOnly === true));
  if (out.diagnosticOnly && !Object.hasOwn(out, "diagnosticReport")) out.diagnosticReport = null;

  if (Array.isArray(out.rounds)) out.rounds = out.rounds.map((round, i) => migrateRound(round, out, i));
  if (prediction) {
    out.prediction = { ...prediction };
    if (!Object.hasOwn(out.prediction, "solverVersion")) out.prediction.solverVersion = out.solverVersion;
    if (!Object.hasOwn(out.prediction, "solverStatus")) out.prediction.solverStatus = out.solverStatus;
    if (!Object.hasOwn(out.prediction, "inputHash")) out.prediction.inputHash = out.inputHash;
    if (!Object.hasOwn(out.prediction, "diagnosticOnly")) out.prediction.diagnosticOnly = out.diagnosticOnly === true;
  }
  out.migrationAuditV06 = {
    ...(out.migrationAuditV06 || {}),
    sourceVersion: record.productVersion || "unknown",
    sourceSchemaVersion: 5,
    targetSchemaVersion: TARGET_SCHEMA,
    sourceTruthPreserved: true,
    predictionRecomputed: false,
    index,
  };
  return out;
}

const { raw: sourceRaw, value: source } = readJson(inputPath);
if (!source || typeof source !== "object" || Array.isArray(source) || !Array.isArray(source.records)) {
  throw new Error("输入文件必须是包含 records 数组的 JSON 对象");
}
const ids = source.records.map(x => x?.id).filter(Boolean);
if (ids.length !== source.records.length || new Set(ids).size !== ids.length) {
  throw new Error("records 存在缺失或重复 id；为保护数据，迁移已停止");
}

if (source.schemaVersion === TARGET_SCHEMA && source.version === TARGET_VERSION && source.migrationAuditV06?.targetSchemaVersion === TARGET_SCHEMA) {
  console.log(JSON.stringify({ status: "already-schema6", input: inputPath, records: source.records.length }, null, 2));
  process.exit(0);
}

const migrated = {
  ...source,
  version: TARGET_VERSION,
  schemaVersion: TARGET_SCHEMA,
  records: source.records.map(migrateRecord),
  screenshotInbox: Array.isArray(source.screenshotInbox) ? source.screenshotInbox.filter(Boolean) : [],
  migrationAuditV06: {
    tool: "auction-lab-v06-schema6-migration",
    toolVersion: "1.0.0",
    sourceVersion: source.version ?? "unknown",
    sourceSchemaVersion: source.schemaVersion ?? null,
    targetVersion: TARGET_VERSION,
    targetSchemaVersion: TARGET_SCHEMA,
    recordCount: source.records.length,
    deterministic: true,
    sourceTruthPreserved: true,
    predictionRecomputed: false,
    diagnosticOnlyExcludedFromTraining: true,
    policy: [
      "保留旧字段与原始截图，不重算 prediction。",
      "不推断 winner、acquired、clearingPrice、purchaseSpend、成本真值或 realized G/P/R。",
      "缺失 solver 元数据只标记 legacy，不代表求解成功。",
      "diagnosticOnly 仅作解释，不进入正式训练。",
    ],
    sourceSha256: sha256(sourceRaw),
    migratedAt: new Date().toISOString(),
    backupPath,
  },
};

const outputText = `${JSON.stringify(migrated, null, 2)}\n`;
const outputParsed = JSON.parse(outputText);
if (outputParsed.schemaVersion !== TARGET_SCHEMA || outputParsed.version !== TARGET_VERSION || outputParsed.records.length !== source.records.length) {
  throw new Error("迁移后结构校验失败，未写回原文件");
}
fs.writeFileSync(outputTemp, outputText, "utf8");
if (!fs.existsSync(backupPath)) fs.copyFileSync(inputPath, backupPath);
try {
  fs.renameSync(inputPath, `${inputPath}.schema5.migration-source.tmp`);
  try {
    fs.renameSync(outputTemp, inputPath);
  } catch (error) {
    fs.renameSync(`${inputPath}.schema5.migration-source.tmp`, inputPath);
    throw error;
  }
  fs.unlinkSync(`${inputPath}.schema5.migration-source.tmp`);
} catch (error) {
  if (fs.existsSync(outputTemp)) fs.unlinkSync(outputTemp);
  throw error;
}

const final = readJson(inputPath).value;
console.log(JSON.stringify({
  status: "migrated",
  input: inputPath,
  backup: backupPath,
  sourceSchemaVersion: source.schemaVersion ?? null,
  targetSchemaVersion: final.schemaVersion,
  records: final.records.length,
  sourceSha256: sha256(sourceRaw),
  outputSha256: sha256(JSON.stringify(final)),
}, null, 2));
