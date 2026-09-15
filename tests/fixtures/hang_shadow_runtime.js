/**
 * Test double: never answers compute. Used to prove timeout/kill/recovery.
 */
function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}
emit({ ok: true, ready: true, nRecords: 0, hang: true });
const rl = require("readline").createInterface({ input: process.stdin });
rl.on("line", (line) => {
  const text = String(line || "").trim();
  if (!text) return;
  try {
    const req = JSON.parse(text);
    if (req && req.action === "setRecords") {
      emit({ ok: true, updated: true, nRecords: (req.records || []).length });
      return;
    }
  } catch (_) {}
  // Hang: no compute JSON forever.
});
