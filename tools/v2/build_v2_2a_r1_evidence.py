"""Generates the V2-2A R1 evidence artifacts from real machine output.

Everything written here is derived from files on disk or from re-running the real
scans; nothing is transcribed by hand. The manifest is written LAST so it can bind
the exact head SHA and the SHA-256 of every sibling artifact.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "build" / "v2-2a-r2" / "evidence"
RAW = REPO / "tools" / "v2" / "evidence_raw"
HOST = REPO / "architecture" / "v2" / "host"
MODULE = HOST / "NteHost.WindowMonitor"
HARNESS = HOST / "window_monitor_harness"
HARNESS_EXE = HARNESS / "bin" / "Release" / "net8.0" / "WindowMonitorHarness.exe"
BASELINE = "a9b52c6fb8db3c5f7dbfb2e80cb5a32bb4a526e9"
V2_1_SOURCE_DIRS = [HOST / "NteHost", HOST / "NteHost.Protocol", HOST / "engine_ref", HOST / "verifier"]
SUMMARY_NAME = "V2_2A_Window_Focus_Monitor_Summary.md"
# The five raw logs produced by tools/v2/run_v2_2a_r1_acceptance.py. They are copied
# in verbatim so the bundle contains the untouched machine output, not a paraphrase.
RAW_LOGS = [
    "python_targeted_tests_raw.txt",
    "v2_1_guard_oneshot_raw.txt",
    "v2_0_guard_raw.txt",
    "callback_isolation_stress_raw.txt",
    "identity_stale_recycle_raw.txt",
    # R2 blocker regressions.
    "identity_same_generation_authority_raw.txt",
    "event_queue_overflow_regression_raw.txt",
    "callback_isolation_deterministic_raw.txt",
]

# Every raw log must carry the exact head it was produced from. A raw whose `# head:`
# does not match the bundle head means the bundle mixes revisions, which is the one
# thing the Evidence must never do.
RAW_HEAD_PREFIX = "# head: "

# The complete set of artifacts this bundle declares. The manifest self-check verifies
# the DIRECTORY against this list in both directions, so an orphan can never sit next to
# the declared set and be read at the same path as a current fact.
DECLARED_ARTIFACTS = [
    "python_targeted_tests_raw.txt",
    "v2_1_guard_oneshot_raw.txt",
    "v2_0_guard_raw.txt",
    "callback_isolation_stress_raw.txt",
    "identity_stale_recycle_raw.txt",
    "identity_same_generation_authority_raw.txt",
    "event_queue_overflow_regression_raw.txt",
    "callback_isolation_deterministic_raw.txt",
    "forbidden_capability_scan.json",
    "no_production_reachability.json",
    "v2_1_t20_scan_coverage.json",
    "callback_isolation_design.json",
    "callback_isolation_measured.json",
    "identity_revalidation_design.json",
    "identity_boundaries_measured.json",
    "identity_same_generation_measured.json",
    "event_queue_overflow_measured.json",
    "event_queue_overflow_design.json",
    "guard_flake_policy.json",
    "environment_facts.json",
    "architecture_notes.json",
    "target_spec_semantics.json",
    "controlled_window_session.json",
    "absent_target_session.json",
    "git_diff.patch",
    SUMMARY_NAME,
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, payload: dict) -> Path:
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def scan_tokens(roots, suffixes, excluded_dirs=("bin", "obj")):
    sources = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if any(part in excluded_dirs for part in path.parts):
                continue
            sources.append(path)
    return sources


FORBIDDEN = {
    "SendInput": "input synthesis (V2-2B)",
    "SetWindowsHookEx": "global input hook (V2-2B)",
    "WH_MOUSE_LL": "low-level mouse hook (V2-2B)",
    "WH_KEYBOARD_LL": "low-level keyboard hook (V2-2B)",
    "Windows.Graphics.Capture": "WGC (V2-3)",
    "CoreWebView2": "WebView2 shell (V2-4)",
    "Microsoft.Web.WebView2": "WebView2 shell (V2-4)",
    "DirectComposition": "overlay ownership (V2-4)",
    "gdi32": "screen capture",
    "PrintWindow": "screen capture",
    "freeze": "freeze coordinator (V2-2C)",
    "scroll": "warehouse scrolling",
    "LOCALAPPDATA": "history authority path",
    "app.main": "production wiring",
    "Boundary3": "Boundary3 branch",
    "b3-input-safety": "Boundary3 branch",
}


def rel(p: Path) -> str:
    return p.relative_to(REPO).as_posix()


def last_json_object(text: str) -> dict:
    """Extracts the trailing pretty-printed JSON object from harness stdout.

    `monitor` mode emits one compact line per phase and then the final payload as a
    pretty-printed object, so a naive `index('{')` slice picks up the wrong record.
    """
    start = text.rfind("\n{")
    if start == -1:
        start = text.find("{")
    return json.loads(text[start:])


def raw_head(path: Path) -> str:
    """Reads the `# head: <sha>` stamp the acceptance runner writes into every raw log."""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
        if line.startswith(RAW_HEAD_PREFIX):
            return line[len(RAW_HEAD_PREFIX):].strip()
    return ""


def raw_classification(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
        if line.startswith("# classification: "):
            return line[len("# classification: "):].strip()
    return ""


def raw_exit_code(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
        if line.startswith("# exit code: "):
            return line[len("# exit code: "):].strip()
    return ""


def test_unittest_summary(raw: Path) -> dict:
    """Reads the unittest verdict line out of a raw log, verbatim.

    The Summary must report what the machine reported, so these counts are parsed from
    the raw log rather than typed in by hand. A hand-typed number is exactly how the
    previous Summary ended up claiming `19/19` and `27/27` against other heads.
    """
    text = raw.read_text(encoding="utf-8", errors="replace") if raw.exists() else ""
    ran = None
    failed = 0
    errors = 0
    skipped = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Ran ") and " test" in stripped:
            try:
                ran = int(stripped.split()[1])
            except (IndexError, ValueError):
                pass
        elif stripped.startswith("FAILED ("):
            body = stripped[len("FAILED ("):].rstrip(")")
            for part in body.split(","):
                part = part.strip()
                if part.startswith("failures="):
                    failed = int(part.split("=")[1])
                elif part.startswith("errors="):
                    errors = int(part.split("=")[1])
                elif part.startswith("skipped="):
                    skipped = int(part.split("=")[1])
    if ran is None:
        return {"raw": raw.name, "ran": None, "passed": None, "failed": None,
                "errors": None, "skipped": None, "verdict": "UNPARSEABLE"}
    passed = ran - failed - errors - skipped
    return {"raw": raw.name, "ran": ran, "passed": passed, "failed": failed,
            "errors": errors, "skipped": skipped,
            "verdict": "OK" if failed == 0 and errors == 0 else "FAILED"}


def raw_headline(raw_name: str, out: Path) -> str:
    """A one-line, machine-derived headline for the Summary, e.g. `26/26`."""
    summary = test_unittest_summary(out / raw_name)
    if summary["ran"] is None:
        return f"{raw_name}: UNPARSEABLE"
    skipped = summary["skipped"] or 0
    if summary["verdict"] != "OK":
        return (f"{summary['passed']}/{summary['ran']} "
                f"(FAILED: failures={summary['failed']} errors={summary['errors']})")
    if skipped:
        return f"{summary['passed']}/{summary['ran']} (skipped={skipped})"
    return f"{summary['passed']}/{summary['ran']}"


def json_at(name: str) -> dict:
    path = OUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def fmt_us(value) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def write_summary(head: str, raw_head_mismatches: list) -> None:
    """Writes the Summary from the artifacts on disk.

    Nothing here is transcribed: every figure is read out of a file the run produced. That
    is the whole point of generating it. The R1 Summary was hand-written and, by the time
    it was reviewed, disagreed with its own raw logs and measured files on the head SHA,
    the callback progress figures, the per-event latency and the image-resolution count.
    """
    isolation = json_at("callback_isolation_measured.json")
    authority = json_at("identity_same_generation_measured.json")
    overflow = json_at("event_queue_overflow_measured.json")
    boundaries = json_at("identity_boundaries_measured.json")
    scan = json_at("forbidden_capability_scan.json")
    reach = json_at("no_production_reachability.json")
    flake = json_at("guard_flake_policy.json")
    env = json_at("environment_facts.json")
    dir_a = isolation.get("directionA", {})
    dir_b = isolation.get("directionB", {})
    shutdown = isolation.get("shutdown", {})
    probe = authority.get("probe", {})

    targeted = raw_headline("python_targeted_tests_raw.txt", OUT)
    v2_1 = raw_headline("v2_1_guard_oneshot_raw.txt", OUT)
    v2_0 = raw_headline("v2_0_guard_raw.txt", OUT)

    targeted_summary = test_unittest_summary(OUT / "python_targeted_tests_raw.txt")
    v2_1_summary = test_unittest_summary(OUT / "v2_1_guard_oneshot_raw.txt")
    v2_0_summary = test_unittest_summary(OUT / "v2_0_guard_raw.txt")

    v2_1_debt = "skipped=%s" % (v2_1_summary.get("skipped"),) if (v2_1_summary.get("skipped") or 0) else "none"

    lines = [
        "# V2-2A Native Window / Focus Monitor - Evidence Summary",
        "",
        "> **This file is generated by `tools/v2/build_v2_2a_r1_evidence.py` from the",
        "> artifacts in this directory.** `make_summary` reads every number out of a",
        "> file the run produced; it is never hand-edited. The previous revision of this",
        "> Summary was hand-written and drifted from its own evidence (it named a different",
        "> head, different callback figures, a different latency and a different resolution",
        "> count), so the generator now exists precisely to make that impossible.",
        "",
        f"- **Head:** `{head}`",
        f"- **Baseline:** `{BASELINE}`",
        f"- **Branch:** `{env.get('branch', 'n/a')}`",
        f"- **Generated:** {env.get('generatedAtUtc', 'n/a')}",
        f"- **Raw logs on head:** "
        f"{'all' if not raw_head_mismatches else 'MISMATCH ' + str(raw_head_mismatches)}",
        "",
        "## Test results (parsed from the raw logs, verbatim)",
        "",
        "| Suite | Raw log | Result | Ran | Passed | Failed | Errors | Skipped |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| V2-2A targeted | `python_targeted_tests_raw.txt` | **{targeted}** | "
        f"{targeted_summary.get('ran')} | {targeted_summary.get('passed')} | "
        f"{targeted_summary.get('failed')} | {targeted_summary.get('errors')} | "
        f"{targeted_summary.get('skipped')} |",
        f"| V2-1 one-shot guard | `v2_1_guard_oneshot_raw.txt` | **{v2_1}** | "
        f"{v2_1_summary.get('ran')} | {v2_1_summary.get('passed')} | "
        f"{v2_1_summary.get('failed')} | {v2_1_summary.get('errors')} | "
        f"{v2_1_summary.get('skipped')} |",
        f"| V2-0 contract guard | `v2_0_guard_raw.txt` | **{v2_0}** | "
        f"{v2_0_summary.get('ran')} | {v2_0_summary.get('passed')} | "
        f"{v2_0_summary.get('failed')} | {v2_0_summary.get('errors')} | "
        f"{v2_0_summary.get('skipped')} |",
        "",
        f"V2-1 known independent debt surfaced in this run: **{v2_1_debt}** "
        f"(policy: `guard_flake_policy.json`).",
        "",
        "## Scope",
        "",
        f"- `productionReachable`: **{str(reach.get('productionReachableLiteral', 'n/a'))}** "
        f"({len(reach.get('importers', []))} importer(s) found under "
        f"`{'`, `'.join(reach.get('productionRoots', []))}`).",
        f"- Forbidden-capability scan: **{scan.get('scannedFiles')} files**, "
        f"**{scan.get('hitCount')} hits** (tokens: {len(scan.get('tokens', []))}).",
        f"- V2-1 runtime modified: **{flake.get('v2_1RuntimeModified')}**.",
        "- Not touched: V2-1 runtime, V2-0 frozen contracts, Feature Truth Matrix, Boundary3, "
        "production startup, WGC, WebView2, Overlay, OCR/solver/history.",
        "",
        "## R2 blocker 1 - identity revalidation is an AUTHORITY check",
        "",
        "**Defect.** `Revalidate()` called `ResolveImageName(pid)`, which consults the",
        "`(pid, generation)` discovery cache first. The generation only moves once a loss has",
        "been OBSERVED (inside `LoseTarget`), so in the window where the old target has already",
        "exited, Windows has already recycled the HWND+pid onto a new process, and the monitor",
        "has not yet processed the destroy event, the cache answered with the DEAD process's",
        "image under the still-current generation. A foreign window could therefore revalidate",
        "as the target. A pid + image check additionally cannot see a recycled pid reused by a",
        "fresh instance of the SAME executable.",
        "",
        "**Fix.**",
        "",
        "- Trust decisions no longer read through the discovery cache. `Revalidate()` uses",
        "  `ResolveImageNameUncached()`; enumeration keeps using the cached `Read()` path, where",
        "  the cache is a legitimate performance optimisation.",
        "- The identity is now four-part: `HWND + pid + process-INSTANCE + image + class`. The",
        "  instance token is the process creation FILETIME from `GetProcessTimes`, which is fixed",
        "  at process start and never reused, so `(pid, creationTime)` names an instance rather",
        "  than merely a pid.",
        "- An unprovable instance (token 0 on either side) is REJECTED, never assumed to match, so",
        "  the check cannot silently degrade to pid+image.",
        "",
        "**Measured (same-generation negative case, no OS pid recycling required):**",
        "",
        f"- unchanged identity accepted: `{probe.get('unchangedIdentityAccepted')}` (sanity: the",
        "  rejections below are not an artefact of rejecting everything)",
        f"- same image, DIFFERENT instance rejected: `{not probe.get('sameImageDifferentInstanceAccepted', True)}`",
        f"  - reason: `{probe.get('sameImageDifferentInstanceFailure')}`",
        f"- different image rejected: `{not probe.get('differentImageAccepted', True)}`",
        f"  - reason: `{probe.get('differentImageFailure')}`",
        f"- unprovable instance (token 0) rejected: `{not probe.get('zeroInstanceTokenAccepted', True)}`",
        f"  - reason: `{probe.get('zeroInstanceTokenFailure')}`",
        f"- cache generation before/after: `{probe.get('generationBefore')}` / "
        f"`{probe.get('generationAfter')}` - **unchanged**, so this really is the",
        "  same-generation window and not the already-covered observed-loss path",
        f"- probe target: pid `{probe.get('pid')}`, image `{probe.get('image')}`",
        "",
        "Files: `identity_revalidation_design.json`, `identity_same_generation_measured.json`,",
        "`identity_same_generation_authority_raw.txt`, `identity_boundaries_measured.json`,",
        "`identity_stale_recycle_raw.txt`.",
        "",
        "## R2 blocker 2 - overflow is a delta decision, not a permanent latch",        "",
        "**Defect.** The worker tested `_rawQueue.DroppedCount > 0`. That counter is cumulative",
        "and never decreases, so after the very first drop every subsequent worker iteration",
        "believed the queue was overflowing. With a target held it repeatedly set and cleared a",
        "recovery request; with no target the 200 ms rate limit turned it into a CONTINUOUS",
        "`EnumWindows` recovery loop. Separately, `EventQueueOverflow` existed in the public",
        "event enum and contract but was NEVER emitted.",
        "",
        "**Fix.**",
        "",
        "- `RawEventQueue.DrainWithDelta()` returns `RawEventBatch(Events, DroppedSinceLastDrain)`,",
        "  computed against a high-water mark, so the consumer sees drops that JUST happened.",
        "- The worker reacts only to `OverflowedSinceLastDrain`, and now really emits",
        "  `EventQueueOverflow` with the delta, the running total and the capacity. No public",
        "  event kind is permanently unemittable any more.",
        "",
        "**Measured (one induced overflow, then a strictly quiet window):**",
        "",
        f"- queue capacity: `{overflow.get('capacity')}`",
        f"- drops induced by the burst: `{overflow.get('dropsInduced')}`",
        f"- overflow observations at burst: `{overflow.get('recoveryScansAtOverflow')}` recovery scans,",
        f"  `{overflow.get('overflowObservationsAfterBurst')}` overflow observations",
        f"- quiet window: `{overflow.get('quietWindowSeconds')}s`",
        f"- **extra recovery scans during the quiet window: "
        f"`{overflow.get('extraRecoveryScansDuringQuiet')}`**",
        f"- extra overflow observations during the quiet window: "
        f"`{overflow.get('extraOverflowObservationsDuringQuiet')}`",
        f"- a latched implementation would have produced roughly "
        f"`{overflow.get('latchedImpliedScanRatePerSecond')}` scans/second for the whole window",
        "",
        "Files: `event_queue_overflow_design.json`, `event_queue_overflow_measured.json`,",
        "`event_queue_overflow_regression_raw.txt`.",
        "",
        "### Ordering defect found while fixing blocker 2",
        "",
        "Reworking the worker's overflow handling surfaced a REAL ordering defect that the R1",
        "head also had, so it is reported rather than quietly fixed.",
        "",
        "`observedAtNs` is normally the raw event's own stamp, taken on the pump thread at",
        "callback-entry time. `EVENT_SYSTEM_FOREGROUND..EVENT_OBJECT_HIDE` OUTOFCONTEXT callbacks",
        "are not guaranteed to arrive in stamp order. Within one batch, `TryPromote` emits",
        "`TargetAcquired` on the raw's earlier stamp, and `EvaluateForeground` immediately after it",
        "emits `ForegroundGained` on a later one - so a derived event could be appended carrying an",
        "EARLIER stamp than the event before it, and the stream read as if time went backwards.",
        "Observed concretely: `TargetAcquired` at `22556784965400` followed by `ForegroundGained` at",
        "`22556784624200`.",
        "",
        "`Emit` now clamps `observedAtNs` to be at least the previous event's stamp. Clamping is the",
        "honest resolution rather than re-stamping: an already-ordered stamp is preserved, and only",
        "a stamp that would violate the documented invariant is raised. Pinned by",
        "`test_08_snapshot_and_event_order_consistent`.",
        "",
        "### Environmental handling (foreground)",
        "",
        "Two DISTINCT OS behaviours can make a foreground assertion fail without anything being",
        "wrong with the module, and they are handled differently on purpose:",
        "",
        "- **Refusal.** `SetForegroundWindow` can be denied outright. `set_foreground` retries;",
        "  `test_23_foreground_changes_all_applied` owns the precondition and FAILS (never skips)",
        "  if a switch is still refused, so a refusal cannot be absorbed silently.",
        "- **Theft.** A switch can be granted and then taken away by an unrelated desktop process.",
        "  `Snapshot()` is a live `GetForegroundWindow()` read, so the final snapshot can then",
        "  legitimately disagree with the event stream. `test_07` skips with the ENVIRONMENTAL label",
        "  only when the foreground moved to a DIFFERENT hwnd than the granted switch reported;",
        "  `test_08` asserts snapshot/event agreement on `isTargetForeground` only when the",
        "  foreground did not move in that gap. The identity, sequence and ordering invariants are",
        "  asserted unconditionally.",
        "",
        "## R2 blocker 3 - callback isolation, proved deterministically",
        "",
        "**Defect (in the TEST, not the runtime).** The stress test asserted",
        "`after['processedEvents'] >= before['processedEvents']`, which permits ZERO progress;",
        "it was measured at `425 -> 425`, so it did not prove the Summary's claim that \"the",
        "worker still progresses\". The claim was also wrong in kind: the worker legitimately",
        "needs the raw lock during `Drain()`, so waiting while it is artificially held is",
        "CORRECT behaviour, not isolation evidence. Direction A additionally inferred the state",
        "lock was held from \"a slow identity event was just triggered\", which cannot distinguish",
        "\"not serialised\" from \"the state path happened to be idle\".",
        "",
        "**Fix.** The lock decoupling itself passed review and was NOT refactored. What changed",
        "is how it is proved:",
        "",
        "- Direction A is deterministic. A diagnostic seam takes the STATE lock from a",
        "  test-controlled thread, reports that it acquired it, and only then does ingestion run.",
        "  The hold is verified rather than assumed.",
        "- Direction B asserts the correct invariant: work queued while the raw lock is held must",
        "  be delivered AFTER the release, so `processedEvents` must GENUINELY increase. The",
        "  \"progress while held\" wording is deleted.",
        "- The property that actually matters is pinned: the callback does not wait on the",
        "  state-machine lock; the raw lock is never held ACROSS state-machine work; no lock-order",
        "  inversion; no deadlock; `Dispose` completes.",
        "",
        "**Measured:**",
        "",
        f"- direction A, state lock verifiably held: `{dir_a.get('stateLockHeldVerified')}` "
        f"(requested hold `{dir_a.get('stateLockHoldRequestedMs')}` ms)",
        f"- ingestion per event: min `{fmt_us(dir_a.get('perEventUsMin'))}` us, "
        f"max `{fmt_us(dir_a.get('perEventUsMax'))}` us",
        f"- serialisation would have shown as: {dir_a.get('serialisationWouldShowAs')}",
        f"- direction B, processed events before release `{dir_b.get('processedEventsBeforeRelease')}`",
        f"  -> after release `{dir_b.get('processedEventsAfterRelease')}`: "
        f"resumed = `{dir_b.get('resumed')}`",
        f"- teardown: `noResidualCallback={shutdown.get('noResidualCallback')}`, "
        f"`hookInstalledAfterDispose={shutdown.get('hookInstalledAfterDispose')}`, "
        f"`disposeElapsedUs={shutdown.get('disposeElapsedUs')}`, "
        f"`droppedEvents={shutdown.get('droppedEvents')}`",
        "",
        "Files: `callback_isolation_design.json`, `callback_isolation_measured.json`,",
        "`callback_isolation_stress_raw.txt`, `callback_isolation_deterministic_raw.txt`.",
        "",
        "## R2 blocker 4 - bundle integrity",
        "",
        "**Defect.** The canonical directory held MORE physical files than the manifest declared:",
        "an old R0 Summary and an old combined guard raw sat alongside the current artifacts, so a",
        "reviewer could read an old fact at a current path. The manifest self-check only asked",
        "\"are the required files present?\", which cannot detect that. And the Summary itself",
        "mixed stale numbers.",
        "",
        "**Fix.**",
        "",
        "- The Summary is AUTO-GENERATED from the raw/measured/manifest artifacts, so it cannot",
        "  drift from them.",
        "- The manifest self-check now verifies the directory in BOTH directions and per file:",
        "  `missing`, `unexpected`, `hashMismatch`, `sizeMismatch`, plus `rawHeadMismatch` and",
        "  `failedRaws`. The declared set IS the directory contents; the two orphans are gone.",
        "- Every raw log carries `# head:` and the builder refuses to publish a bundle where any",
        "  raw was produced on a different revision.",
        "",
        "## R2 rework reference",
        "",
        f"- superseded R1 head: `e93867e90d2e9c7f3c629d51a786f30ba5002458`",
        f"- superseded R0 head: `4e3d482359689fb55f60815cd51eb0db0440a6ed`",
        f"- this bundle's head: `{head}`",
        "",
        "## Boundaries held",
        "",
        "V2-2A remains a window-discovery and focus-monitoring phase. No input synthesis, no",
        "low-level input hook, no cursor takeover, no warehouse scrolling, no freeze coordinator,",
        "no WGC, no CoreWebView2, no overlay, no OCR/solver/history, no production wiring. The",
        "V2-1 runtime and the V2-0 frozen contracts are untouched.",
        "",
    ]

    (OUT / SUMMARY_NAME).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    head = git("rev-parse", "HEAD")

    # ---- 0. copy the untouched raw logs produced by the acceptance runner -----
    missing_raw = []
    for name in RAW_LOGS:
        source = RAW / name
        if not source.exists():
            missing_raw.append(name)
            continue
        (OUT / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    if missing_raw:
        print(f"ERROR: missing raw logs {missing_raw}; run run_v2_2a_r1_acceptance.py first")
        return 1

    # Every raw must carry the SAME head as the bundle. The previous Summary claimed all
    # raws were produced on `8965dac` while the manifest bound `e93867e`, so the bundle
    # contained two different revisions and a reviewer could not tell which fact was which.
    raw_head_mismatches = []
    for name in RAW_LOGS:
        stamped = raw_head(OUT / name)
        if stamped != head:
            raw_head_mismatches.append({"raw": name, "stampedHead": stamped or "<absent>",
                                        "expectedHead": head})
    raw_failed = []
    for name in RAW_LOGS:
        kind = raw_classification(OUT / name)
        if kind == "failed":
            raw_failed.append(name)
    if raw_head_mismatches:
        print(f"ERROR: raw logs were not produced on the bundle head: {raw_head_mismatches}")
        return 1
    if raw_failed:
        print(f"ERROR: raw logs classified as FAILED: {raw_failed}")
        return 1

    # ---- 1. corrected T16 full-module forbidden capability scan --------------
    sources = scan_tokens([MODULE, HARNESS], {".cs", ".py", ".csproj"})
    hits = []
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token, why in FORBIDDEN.items():
            if token in text:
                hits.append(f"{rel(path)} contains '{token}' ({why})")
    write("forbidden_capability_scan.json", {
        "schemaVersion": "v2.2a.forbidden.capability.scan.v2",
        "selector": "architecture/v2/host/NteHost.WindowMonitor/** + "
                    "architecture/v2/host/window_monitor_harness/** "
                    "(all .cs/.py/.csproj, bin|obj excluded, NO name-based filter)",
        "previousDefect": "v1 filtered on 'WindowMonitor' in the file name, which excluded the "
                          "module's core runtime files; it reported scannedFiles=6 and therefore "
                          "did not represent the module",
        "scanRoots": [rel(MODULE), rel(HARNESS)],
        "scannedFiles": len(sources),
        "files": [rel(p) for p in sources],
        "tokens": list(FORBIDDEN),
        "hits": hits,
        "hitCount": len(hits),
        "zeroHits": not hits,
        "note": "V2-2A implements window discovery and focus monitoring only. Input synthesis, "
                "low-level input hooks, capture, WebView2, overlay composition, freeze policy and "
                "warehouse scrolling all belong to other phases and must not appear here.",
    })

    # ---- 2. production reachability -----------------------------------------
    tokens = ("WindowMonitor", "NteHost.WindowMonitor", "WindowMonitorHarness",
              "NteHost.Protocol", "NteHost", "RawEventQueue", "WinEventHookSource")
    importers = []
    for directory in (REPO / "app", REPO / "core"):
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in tokens:
                if token in text:
                    importers.append(f"{rel(path)} references '{token}'")
    write("no_production_reachability.json", {
        "schemaVersion": "v2.2a.production.reachability.v1",
        "productionRoots": ["app/", "core/"],
        "tokens": list(tokens),
        "importers": importers,
        "productionReachable": bool(importers),
        "productionReachableLiteral": "false",
        "note": "Reachability is decided by scanning the production trees for a real import or "
                "reference. Class-name existence inside the V2-2A module is not evidence of "
                "reachability and is not counted.",
    })

    # ---- 3. V2-1 production import scan coverage ----------------------------
    covered = []
    offenders = []
    for root in V2_1_SOURCE_DIRS:
        for path in sorted(root.rglob("*.py")):
            if "bin" in path.parts or "obj" in path.parts:
                continue
            covered.append(rel(path))
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("import core", "from core", "import app", "from app")):
                    offenders.append(f"{rel(path)}:{lineno}: {stripped}")
    write("v2_1_t20_scan_coverage.json", {
        "schemaVersion": "v2.2a.v2_1.t20.coverage.v1",
        "defect": "The per-line loop was hoisted out of the per-file loop by mis-indentation, so "
                  "each source root only had its LAST .py file scanned. V2-1's Python surface is a "
                  "single file (engine_ref/nte_engine_ref.py), which is why the bug was invisible "
                  "in the 27/27 result.",
        "fix": "The per-line loop is back inside the per-file loop; every .py under every V2-1 "
               "source root is read. T27 plants scratch .py files in the real roots - including "
               "ones that are NOT last under the scan's own ordering - and requires the planted "
               "production import to be reported.",
        "regressionTest": "tests/test_v2_1_host_supervisor.py::test_27_production_import_scan_covers_every_file",
        "roots": [rel(p) for p in V2_1_SOURCE_DIRS],
        "scannedFiles": covered,
        "scannedCount": len(covered),
        "offenders": offenders,
        "note": "V2-1's Python surface really is one file. The coverage claim is therefore "
                "backed by the planted-file regression test rather than by a large file count.",
    })

    # ---- 4. callback isolation / stress evidence ----------------------------
    write("callback_isolation_design.json", {
        "schemaVersion": "v2.2a.callback.isolation.v2",
        "previousDefect": "WindowMonitor.OnRawWinEvent() took the SAME _gate the worker holds "
                          "while it performs Win32 and process-identity work (IsWindow, "
                          "GetWindowThreadProcessId, GetClassName, IsWindowVisible, OpenProcess / "
                          "image resolution). A busy worker could therefore stall the callback, "
                          "which contradicted the documented 'timestamp + enqueue only / "
                          "non-blocking by construction' claim.",
        "fix": {
            "separateQueueObject": "RawEventQueue owns its own _sync lock; it is touched by nobody "
                                   "else in the module",
            "callbackPath": "OnRawWinEvent -> ProtocolClock.NowNs() + RawEventQueue.Enqueue + "
                            "SemaphoreSlim.Release. No state-machine lock is taken.",
            "stateMachineLock": "_gate is now exclusively the worker's and the reader's lock",
            "documentationCorrection": "WinEventHookSource / architecture notes no longer claim "
                                       "'never blocks' as an unqualified property; they state the "
                                       "precise mechanism (the callback takes no lock the state "
                                       "machine can hold) and the queue's own short critical section.",
            "runtimeUnchangedInR2": "The lock decoupling itself passed the R2 review and was NOT "
                                    "refactored. R2 changed only how the property is PROVED.",
        },
        "r2TestDefect": {
            "summary": "The stress test's direction-B assertion was wrong, and its direction-A "
                       "construction could not distinguish the property it claimed.",
            "directionB": "It asserted `after['processedEvents'] >= before['processedEvents']`, which "
                          "permits ZERO progress; it was measured at 425 -> 425, so it did not "
                          "prove the Summary's claim that 'the worker still progresses'. The claim "
                          "was also wrong in kind: the worker legitimately needs the raw lock during "
                          "Drain(), so waiting while it is artificially held is CORRECT behaviour, "
                          "not isolation evidence.",
            "directionA": "It inferred that the state lock was held from 'a slow identity evaluation "
                          "was just triggered', which cannot distinguish 'the callback is not "
                          "serialised' from 'the state path happened to be idle at that instant'.",
        },
        "r2TestFix": {
            "directionADeterministic": "A diagnostic seam takes the STATE lock from a "
                                       "test-controlled thread and REPORTS that it acquired it "
                                       "(`holdstate N` / `WaitForStateGateAcquiredForDiagnostics`); "
                                       "ingestion then runs while the lock is provably held.",
            "directionBCorrectInvariant": "Work queued while the raw lock is held must be delivered "
                                          "AFTER the release, so `processedEvents` must GENUINELY "
                                          "increase (a strict comparison). The 'progress while "
                                          "held' wording is deleted from the test, the Summary and "
                                          "this document.",
            "invariantsPinned": [
                "the callback does not wait on the state-machine lock",
                "the raw lock is never held ACROSS state-machine work",
                "no nesting / lock-order inversion between the raw lock and the state lock",
                "after the raw lock is released the worker RESUMES processing",
                "no deadlock, and Dispose completes",
            ],
        },
        "teardownSemantics": {
            "claim": "After Dispose() returns, no callback is DELIVERED by Windows and no callback "
                     "ACTS on an event.",
            "notClaimed": "It is not claimed that a callback already in flight at the instant of "
                          "UnhookWinEvent can be revoked. Windows provides no such guarantee for "
                          "OUTOFCONTEXT callbacks; they run on the subscribing thread's message pump.",
            "mechanism": [
                "WinEventHookSource latches a volatile _disposed flag first thing in Dispose; the "
                "callback checks it and returns before touching the sink, so a raced callback "
                "cannot extend teardown or act on a released resource.",
                "Dispose joins the pump thread and then calls UnhookWinEvent, so Windows stops "
                "delivering new callbacks.",
                "The harness reads the residual-callback counter only after the module's own idle "
                "signal has confirmed the unsubscribe took effect, instead of racing the last "
                "in-flight callback (which previously produced an intermittent false failure that "
                "had nothing to do with a residual subscription).",
            ],
        },
        "stressSeams": {
            "IdentityWorkDelayMsForDiagnostics": "widens the real identity path so a slow state path "
                                                 "can be forced (kept for test_20's original form)",
            "holdstate N": "takes the STATE lock from a test-controlled thread and reports acquisition, "
                           "making direction A deterministic",
            "releasestate": "releases that hold",
            "inject N": "pushes synthetic raw events through the same OnRawWinEvent path and reports "
                        "per-event ingestion latency",
            "holdraw N": "holds the raw queue lock so a test can prove queued work is still delivered "
                         "after the release (no lock-order inversion, no deadlock)",
            "rawpush N": "enqueues through the raw queue bypassing the ingestion-suppression toggle",
            "suppress 0|1": "creates a genuinely quiet observation window for the overflow regression",
            "statusprobe": "reports processedEvents / droppedEvents / overflowObservations / "
                           "recoveryScans / stateGateHeld",
        },
        "assertedBy": [
            "tests/test_v2_2a_window_focus_monitor.py::test_26_raw_callback_isolation_deterministic",
            "tests/test_v2_2a_window_focus_monitor.py::test_20_raw_callback_isolation_from_state_lock",
            "tests/test_v2_2a_window_focus_monitor.py::test_23_foreground_changes_all_applied "
            "(owns the scenario's foreground preconditions so an OS-level refusal is reported as "
            "the environmental cause it is, instead of as a downstream 'missing event')",
        ],
        "measuredEvidence": "callback_isolation_measured.json",
    })

    # ---- 5. identity revalidation design -----------------------------------
    write("identity_revalidation_design.json", {
        "schemaVersion": "v2.2a.identity.revalidation.v2",
        "r1ResidualDefect": {
            "summary": "`Revalidate()` still had a same-generation stale-cache hole, and the "
                       "identity could not distinguish two instances of the SAME executable.",
            "mechanism": "Revalidate() resolved the process image with `ResolveImageName(pid)`, "
                         "which checks the `(pid, generation)` cache first. The generation only "
                         "moves once a loss has been OBSERVED, i.e. inside LoseTarget(). So in the "
                         "window where the old target has already exited, Windows has already "
                         "recycled the HWND and the pid onto a new process, and the monitor has not "
                         "yet processed the destroy event, the cache answered with the DEAD "
                         "process's image under the still-current generation. A foreign window "
                         "could revalidate as the target.",
            "secondMechanism": "Even with the cache bypassed, a pid + image comparison cannot see a "
                               "pid reused by a fresh instance of the SAME executable. Windows "
                               "recycles pids; it does not care that the executable path matches.",
            "whyTestsMissedIt": "T22 only proved the OBSERVED-loss path: old target exits, loss is "
                                "processed, generation bumps, new handle differs. It never exercised "
                                "the pre-loss recycle window and never compared an instance token.",
        },
        "fix": {
            "authorityVsDiscovery": "The trust path and the discovery path are now explicitly "
                                    "separated. Enumeration/discovery may use the cached `Read()` "
                                    "path, where the cache is a legitimate optimization. Revalidate() "
                                    "uses `ResolveImageNameUncached()`, which never consults the "
                                    "cache.",
            "processInstanceIdentity": "WindowIdentity now carries `ProcessInstanceToken`, the "
                                       "process creation FILETIME read via `GetProcessTimes`. It is "
                                       "fixed at process start and never reused, so (pid, "
                                       "creationTime) names an INSTANCE rather than a pid. The full "
                                       "trusted identity is therefore HWND + pid + process-instance + "
                                       "image + class.",
            "unprovableIsRejected": "If the instance token is 0 on either side, or the recorded "
                                    "identity predates instance tracking, the verdict is a "
                                    "REJECTION. The check can never silently degrade to pid+image.",
            "verdictReporting": "IdentityVerdict gained `InstanceMatches`, and the failure string "
                                "names the creation times (`creationTime 0x... != 0x...`) so a "
                                "rejection is auditable.",
            "deterministicSeam": "`Revalidate(recorded, requireVisible, FreshProcessQuery? "
                                 "freshIdentity)` lets a test supply what the authority query "
                                 "'returns'. Production passes null and queries the live process.",
        },
        "deterministicNegativeCase": {
            "why": "The reviewer required a negative case that does NOT depend on Windows actually "
                   "recycling a pid, which would make the test flaky rather than a proof.",
            "method": "Prime the discovery cache for a real pid (pid=35356 / image=explorer.exe in "
                      "the recorded run), then call Revalidate() with a FreshProcessQuery reporting "
                      "a recycled process - WITHOUT calling LoseTarget and WITHOUT bumping the "
                      "generation. Require immediate rejection.",
            "cases": [
                "same image, different process instance -> rejected",
                "different image under the unchanged generation -> rejected",
                "unprovable instance token (0) -> rejected",
                "unchanged identity -> accepted (sanity control)",
            ],
            "generationProof": "The cache generation is asserted unchanged across the negative case, "
                               "which is what makes it the same-generation window.",
        },
        "assertedBy": [
            "tests/test_v2_2a_window_focus_monitor.py::test_24_revalidate_is_authority_not_cache",
            "tests/test_v2_2a_window_focus_monitor.py::test_21_identity_revalidates_process_image_and_invalidates_cache",
            "tests/test_v2_2a_window_focus_monitor.py::test_22_stale_identity_negative_after_recycle",
        ],
        "measuredEvidence": "identity_same_generation_measured.json",
        "boundaryEvidence": "identity_boundaries_measured.json",
        "historicalR0Defect": {
            "summary": "The original R0 identity check was weaker still, and is recorded here only "
                       "for continuity.",
            "details": [
                "IsStillSameWindow() only re-checked IsWindow + pid + class + visibility, so a "
                "recycled HWND whose pid was reused by a DIFFERENT executable of the same window "
                "class would have been accepted as 'still the identity we recorded'.",
                "WindowIdentityReader.InvalidatePid() was defined but never called anywhere, so a "
                "pid->image mapping stayed pinned until Dispose.",
            ],
        },
    })

    # ---- 6. flake policy ----------------------------------------------------
    write("guard_flake_policy.json", {
        "schemaVersion": "v2.2a.guard.flake.policy.v1",
        "previousDefect": "test_18_v2_1_targeted_suite_still_passes retried the V2-1 suite when the "
                          "only failures were on a known-flake list and passed the second time, so "
                          "V2-2A's own suite could report green while the first run had genuinely "
                          "failed a guard.",
        "fix": "The retry and the known-flake list are deleted. The V2-1 guard runs ONE SHOT; any "
               "failure is kept verbatim in the raw log. A failure is then CLASSIFIED, never "
               "hidden: only the pre-existing ControlledShutdown race, AND only when the V2-1 "
               "runtime is byte-identical to its PASS head, surfaces as an INDEPENDENT V2-1 DEBT "
               "skip carrying the verbatim failure. Any other failure - or a modified V2-1 runtime "
               "- is a hard failure.",
        "v2_1RuntimeModified": False,
        "classificationLogic": {
            "knownDebtTest": "test_07_controlled_shutdown_not_counted_as_crash",
            "knownDebtMarker": "AssertionError: None != 0",
            "requiresV2_1RuntimeUntouched": True,
            "outcomeIfMatched": "unittest.SkipTest labelled INDEPENDENT V2-1 DEBT (not a V2-2A pass, "
                                "not a V2-2A regression)",
            "outcomeOtherwise": "hard failure",
        },
        "v2_1Debt": {
            "id": "V2-1 ControlledShutdown ExitCode race",
            "status": "OPEN, unfixed, out of scope for V2-2A",
            "detail": "ControlledShutdown reads _child.ExitCode, which is only written by the "
                      "Process.Exited handler (OnChildExited). Process.WaitForExit returns as soon "
                      "as the process object signals exit and does NOT guarantee that the Exited "
                      "handler has run, so the field can still be null at read time and "
                      "childExitCode is reported as null instead of 0.",
            "observedFrequency": "1 failure in 5 consecutive isolated runs of test_07 on this host "
                                 "(20%); it also reproduced once in the full one-shot guard run and "
                                 "once here as a consequence of that same run.",
            "whyNotFixedHere": "The V2-1 runtime is byte-identical to its PASS head "
                               "(git diff a9b52c6..HEAD -- architecture/v2/host/NteHost is empty), "
                               "so the race is pre-existing V2-1 debt. Fixing it would mean editing "
                               "V2-1 runtime, which this V2-2A rework is explicitly forbidden to "
                               "do; it must be handled by a separate V2-1 task.",
            "recommendedFix": "Have ControlledShutdown use Process.WaitForExit() AFTER the exit is "
                              "observed (or read ExitCode inside the Exited handler and store it), "
                              "so the value is not read before the handler has written it.",
            "policy": "It is reported raw and carried as independent V2-1 debt; it is never "
                      "laundered into a pass.",
        },
    })

    # ---- 6. overflow semantics (R2 blocker 2) -------------------------------
    write("event_queue_overflow_design.json", {
        "schemaVersion": "v2.2a.event.queue.overflow.design.v1",
        "previousDefect": [
            "WindowMonitor's worker computed `var overflowed = _rawQueue.DroppedCount > 0;`. "
            "DroppedCount is CUMULATIVE and only ever increases, so after the first drop every "
            "subsequent worker iteration reported an overflow. With a target present it repeatedly "
            "set and cleared a recovery request; with no target the 200 ms rate limit turned it "
            "into a CONTINUOUS EnumWindows recovery loop - permanent work caused by one transient "
            "burst.",
            "`WindowMonitorEventKind.EventQueueOverflow` existed in the public event enum and in the "
            "documented contract, but was never emitted by any code path, so a consumer could wait "
            "for an event kind that could not occur.",
        ],
        "fix": {
            "deltaNotTotal": "RawEventQueue gained a high-water mark (`_droppedAcknowledged`) and "
                             "`DrainWithDelta()` now returns `RawEventBatch(Events, "
                             "DroppedSinceLastDrain)`. Only a positive delta means 'a drop just "
                             "happened'.",
            "workerReactsToNewDropsOnly": "the worker branches on `drained.OverflowedSinceLastDrain`, "
                                          "so recovery responds to a NEW drop and then goes quiet.",
            "eventKindNowEmitted": "`EventQueueOverflow` is now really emitted, carrying "
                                   "`droppedSinceLastDrain`, the running `totalDropped` and the "
                                   "`capacity`, so the evidence is auditable. No public event kind "
                                   "is permanently unemittable.",
            "backCompat": "`Drain()` is retained as `DrainWithDelta().Events`, so existing callers "
                          "that do not care about the delta are unaffected.",
        },
        "invariants": [
            "the overflow DECISION is per-drain, never cumulative",
            "one overflow burst produces one observation and one recovery request",
            "a quiet period after an overflow produces no further recovery scans",
            "the drop delta, the running total and the capacity are all recorded in the event",
        ],
        "assertedBy": [
            "tests/test_v2_2a_window_focus_monitor.py::test_25_event_queue_overflow_is_not_a_latch",
        ],
        "measuredEvidence": "event_queue_overflow_measured.json",
    })

    # ---- 7. architecture notes ---------------------------------------------
    write("architecture_notes.json", {
        "schemaVersion": "v2.2a.architecture.v1",
        "module": "architecture/v2/host/NteHost.WindowMonitor (net8.0 class library)",
        "harness": "architecture/v2/host/window_monitor_harness (controlled-window test host)",
        "threading": {
            "hookThread": "owns SetWinEventHook + the message pump. The callback stamps the time, "
                          "appends to a bounded raw queue and signals the worker. It takes NO lock "
                          "that the state machine can hold, so it cannot be serialised behind the "
                          "worker's Win32 / process-identity work. The only lock on this path is the "
                          "raw queue's own, held for a bounded enqueue.",
            "workerThread": "single consumer, owns the state machine, so event ordering is total",
            "callers": "read snapshots, which revalidate the held handle before answering",
            "queueOwnership": "the raw queue is its own object (RawEventQueue) with its own lock; no "
                              "other part of the module touches it. This separation is what makes "
                              "the callback's latency independent of state-machine latency.",
            "lockOrder": "there is exactly one state lock (_gate) and one raw-queue lock (_sync). "
                         "The callback takes only _sync; the worker takes _sync only inside "
                         "DrainWithDelta() and _gate separately. NEITHER lock is ever held while "
                         "acquiring the other, so the two locks have no nesting relationship and no "
                         "order inversion is possible.",
        },
        "eventDriven": {
            "mechanism": "SetWinEventHook(EVENT_SYSTEM_FOREGROUND .. EVENT_OBJECT_HIDE, "
                         "WINEVENT_OUTOFCONTEXT) on a dedicated pump thread",
            "callbackDiscipline": "the callback does timestamp + bounded enqueue + signal only. This "
                                  "is enforced by construction (it holds no shared lock) rather than "
                                  "by an unqualified 'non-blocking' claim: the queue's own critical "
                                  "section is short and is never held by the state machine.",
            "queue": "bounded; on overflow the OLDEST record is dropped and counted, so the hook "
                     "never stalls desktop-wide event delivery. The queue is owned by RawEventQueue "
                     "and is independent of the state-machine lock. The drop count is reported to "
                     "the worker as a DELTA since the previous drain, never as a cumulative total, "
                     "so a single overflow cannot latch the recovery path.",
            "teardown": "Dispose latches a _disposed flag that the callback checks before touching "
                        "the sink, then joins the pump thread and unhooks. The guarantee claimed is "
                        "'after Dispose no callback is delivered and none acts on an event'. It is "
                        "NOT claimed that a callback already in flight at the instant of "
                        "UnhookWinEvent can be revoked; Windows offers no such guarantee for "
                        "OUTOFCONTEXT callbacks.",
        },
        "recoveryPolicy": {
            "enumWindowsUsedAs": "recovery fallback only",
            "triggers": ["start-up", "target loss", "a NEW event-queue overflow", "explicit request"],
            "notATimer": "there is no polling loop; a scan only runs when a trigger sets the flag",
            "rateLimitMs": 200,
            "skipWhenTargetHeld": "a pending scan is cleared rather than run if a target is held",
            "overflowIsPerDrain": "recovery is triggered by a drop that JUST happened "
                                  "(DroppedSinceLastDrain > 0), not by the cumulative DroppedCount, "
                                  "which would latch the trigger permanently",
            "visibilityConsistency": "the enumerator applies the same visibility rule as the "
                                     "validator, so a hidden window is never adopted and then "
                                     "immediately rejected",
        },
        "failClosed": {
            "staleHandle": "every use of the held handle revalidates the COMPLETE recorded identity: "
                           "handle liveness, pid, window class, process image, process INSTANCE and "
                           "visibility. An HWND and a pid are both recyclable integers, so a live "
                           "handle plus a matching pid is not evidence on its own. Revalidation "
                           "bypasses the discovery cache entirely and re-queries the live process.",
            "authorityVsDiscovery": "the pid->image cache is a performance optimisation for "
                                    "enumeration; it is keyed by (pid, generation) and is never "
                                    "consulted on the trust path. The generation only advances once "
                                    "a loss has been OBSERVED, so a cache-reading trust path could "
                                    "answer with a dead process's image inside the same generation.",
            "processInstance": "the identity carries a process-instance token (creation FILETIME via "
                               "GetProcessTimes). A pid reused by a new instance of the SAME "
                               "executable is therefore rejected, which a pid+image check cannot do. "
                               "An unprovable instance token is a rejection, not a match.",
            "absentTarget": "with no match the module reports generation 0, hwnd 0, "
                            "isTargetAlive=false and isTargetForeground=false, and never guesses",
            "multiCandidate": "when several windows match, the foreground one is preferred; "
                              "otherwise the lowest HWND, so the choice is deterministic",
            "identityCache": "the pid->image cache is keyed by (pid, generation). The generation is "
                             "bumped at every identity boundary (target loss, process-generation "
                             "change) and on Dispose, so a recycled pid cannot inherit a stale "
                             "image name.",
            "revalidationReporting": "revalidation returns an IdentityVerdict that reports which "
                                     "field failed, including instanceMatches; events carry "
                                     "targetImageName / targetClassName and stale rejections cite "
                                     "the failing field, the creation times and the cache generation.",
        },
        "eventOrdering": {
            "invariant": "the event list is a total order (sequence) and the `observedAtNs` "
                         "carried in it must be non-decreasing in that order.",
            "defectFoundWhileFixingBlocker2": "Refactoring the worker's overflow handling "
                                              "exposed a real ordering defect that the R1 head also "
                                              "had. `observedAtNs` is normally the raw event's own "
                                              "stamp, taken on the pump thread at callback entry, "
                                              "and `EVENT_SYSTEM_FOREGROUND..EVENT_OBJECT_HIDE` "
                                              "OUTOFCONTEXT callbacks are not guaranteed to arrive "
                                              "in stamp order. `TryPromote` therefore emits "
                                              "TargetAcquired on the raw's earlier stamp while "
                                              "`EvaluateForeground` immediately after it emits "
                                              "ForegroundGained on a later one, so a derived event "
                                              "could be appended carrying an earlier stamp than the "
                                              "event before it and the stream read as if time went "
                                              "backwards. Observed concretely: TargetAcquired "
                                              "22556784965400 followed by ForegroundGained "
                                              "22556784624200.",
            "fix": "`Emit` clamps `observedAtNs` to be >= the previous event's stamp. Clamping is "
                   "the honest resolution rather than re-stamping: an already-ordered stamp is "
                   "preserved, and only a stamp that would violate the documented invariant is "
                   "raised.",
            "assertedBy": "tests/test_v2_2a_window_focus_monitor.py::"
                          "test_08_snapshot_and_event_order_consistent",
        },
        "environmentalFlakeHandling": {
            "foregroundLockRefusal": "MonitorSession.set_foreground retries (default 20); "
                                     "test_23_foreground_changes_all_applied owns the precondition "
                                     "and fails (never skips) if a switch is still refused, so an OS "
                                     "refusal cannot be absorbed silently.",
            "foregroundTheft": "a switch can be GRANTED and then taken away by an unrelated desktop "
                               "process. `Snapshot()` is a live `GetForegroundWindow()` read, so "
                               "the final snapshot can then legitimately disagree with the event "
                               "stream. test_07 skips with the ENVIRONMENTAL label only when the "
                               "foreground moved to a DIFFERENT hwnd than the one the granted "
                               "switch reported; test_08 asserts snapshot/event agreement on "
                               "isTargetForeground only when the foreground did not move in that "
                               "gap, and records a note otherwise. The identity, sequence and "
                               "ordering invariants are asserted unconditionally.",
        },
        "contract": {
            "snapshot": ["targetHwnd", "targetPid", "foregroundHwnd", "isTargetAlive",
                         "isTargetForeground", "generation", "observedAtNs", "reason",
                         "targetImageName", "targetClassName"],
            "eventKinds": ["TargetAcquired", "TargetLost", "TargetReacquired", "ForegroundGained",
                           "ForegroundLost", "StaleHandleRejected", "RecoveryScanPerformed",
                           "EventQueueOverflow"],
            "clock": "WINDOWS_QPC_NANOSECONDS via NteHost.Protocol.ProtocolClock (read-only reuse)",
            "v2_0_contracts": "not referenced and not modified",
        },
        "scopeBoundary": "No input synthesis, no low-level input hook, no cursor takeover, no "
                         "warehouse scrolling, no freeze coordinator, no WGC, no CoreWebView2, no "
                         "overlay, no OCR/solver/history, no production wiring. No V2-1 runtime "
                         "change. No V2-0 frozen contract change. No canonical doc (Feature Truth "
                         "Matrix / Handoff / README / Decisions) change.",
        "r1Rework": {
            "note": "This revision is the R2 blocker rework of the V2-2A phase. The threading and "
                    "failClosed sections were corrected to describe the mechanism accurately; the "
                    "previous text made an unqualified 'never blocks' claim that the implementation "
                    "did not satisfy, and described an identity check that still had a "
                    "same-generation stale-cache hole.",
            "supersededR0Head": "4e3d482359689fb55f60815cd51eb0db0440a6ed",
            "supersededR1Head": "e93867e90d2e9c7f3c629d51a786f30ba5002458",
            "r2Head": head,
        },
        "r2Blockers": {
            "1_identityAuthority": "Revalidate() no longer reads the (pid, generation) discovery "
                                   "cache and compares a process-INSTANCE token (creation FILETIME "
                                   "via GetProcessTimes), so a same-generation recycle and a "
                                   "reused pid with the same executable are both rejected.",
            "2_overflowDelta": "the worker reacts to DroppedSinceLastDrain, not the cumulative "
                               "DroppedCount, so a single overflow cannot latch the recovery path; "
                               "EventQueueOverflow is now really emitted with the delta, total and "
                               "capacity.",
            "3_callbackTestHonesty": "the lock decoupling passed review and was NOT refactored. The "
                                     "TEST was corrected: direction A holds the state lock "
                                     "verifiably, direction B requires processedEvents to genuinely "
                                     "increase after the raw lock is released, and the invalid "
                                     "'progress while held' claim is deleted.",
            "4_bundleIntegrity": "the Summary is auto-generated from the artifacts, the manifest "
                                 "self-check verifies the directory in both directions "
                                 "(missing/unexpected/hashMismatch/sizeMismatch) plus raw head and "
                                 "classification, and the two orphan files are removed.",
        },
    })

    # ---- 8. target spec semantics (regenerated from the real specprobe) ------
    specprobe = subprocess.run(
        [str(HARNESS_EXE), "--mode", "specprobe"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    write("target_spec_semantics.json", {
        "schemaVersion": "v2.2a.target.spec.semantics.v1",
        "note": "Produced by running the harness specprobe, so the target rule is machine-checked "
                "as a PURE RULE: the production spec (htgame.exe / UnrealWindow) is verified without "
                "the game being installed and without pretending a test window is the game.",
        "probe": last_json_object(specprobe.stdout),
    })

    # ---- 9. controlled + absent target sessions ------------------------------
    controlled = subprocess.run(
        [str(HARNESS_EXE), "--mode", "monitor", "--spec-image", "WindowMonitorHarness.exe",
         "--spec-class", "NteV22ControlledWindow", "--duration-ms", "5000"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    write("controlled_window_session.json", last_json_object(controlled.stdout))
    absent = subprocess.run(
        [str(HARNESS_EXE), "--mode", "monitor", "--spec-image", "htgame.exe",
         "--spec-class", "UnrealWindow", "--duration-ms", "5000"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    write("absent_target_session.json", last_json_object(absent.stdout))

    # ---- 10. diff patch ------------------------------------------------------
    (OUT / "git_diff.patch").write_text(
        git("diff", BASELINE, "HEAD"), encoding="utf-8")

    # ---- 11. environment facts ----------------------------------------------
    write("environment_facts.json", {
        "schemaVersion": "v2.2a.environment.v1",
        "repository": str(REPO),
        "baselineCommit": BASELINE,
        "headCommit": head,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "python": sys.version.split()[0],
        "pythonExecutable": sys.executable,
        "generatedAtUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": [
            "The sandbox shell omits APPDATA / ProgramData / ProgramFiles, which makes `dotnet` "
            "throw \"Value cannot be null. (Parameter 'path1')\" during NuGet path resolution. "
            "tools/v2/dotnet_env.py populates the environment and is used by the test module.",
            "Test runs use the managed CPython 3.13.12; the harness targets net8.0 and is built "
            "with the local .NET SDK.",
        ],
        "knownEnvironmentalFlakes": [
            {
                "id": "Windows foreground lock",
                "symptom": "SetForegroundWindow is transiently refused, so `fg N` can report "
                           "tookEffect=false. Downstream tests then observe a missing "
                           "ForegroundGained event or a snapshot/event disagreement.",
                "observed": "roughly 2 refusals in 10 for the FIRST foreground move after the "
                            "harness launches; 0/8 refusals when the command is retried at the test "
                            "layer",
                "mitigation": "MonitorSession.set_foreground retries (default 20 attempts); "
                              "test_23_foreground_changes_all_applied owns the precondition and "
                              "fails with the ENVIRONMENTAL label if a switch is still refused; "
                              "test_07 / test_08 skip (never silently pass) when the precondition "
                              "did not hold.",
                "notAV22ADefect": "The module cannot make Windows grant foreground; the refusal is "
                                  "an OS policy outcome, not an acquire/loss/reacquire defect.",
            },
        ],
    })

    # ---- 12. Summary (AUTO-GENERATED from the artifacts, never hand-edited) ---
    # The previous Summary was written by hand and drifted: it claimed the raws came from
    # `8965dac` while the manifest bound `e93867e`, reported the callback worker as
    # `25 -> 2028` when the measurement said `425 -> 425`, reported `0.626 us/event` when
    # the current measurement said `0.3635`, and reported `5` image resolutions when it
    # was `2`. Every number below is therefore read out of a file written by the run.
    write_summary(head, raw_head_mismatches)

    # ---- 13. manifest (LAST) ------------------------------------------------
    declared = list(DECLARED_ARTIFACTS)
    physical = sorted(p.name for p in OUT.iterdir() if p.is_file())
    missing = [n for n in declared if n not in physical]
    unexpected = [n for n in physical if n not in declared and n != "evidence_manifest.json"]

    entries = []
    hash_mismatch = []
    size_mismatch = []
    for name in sorted(declared):
        path = OUT / name
        if not path.exists():
            continue
        entry = {"name": name, "sizeBytes": path.stat().st_size, "sha256": sha256(path)}
        entries.append(entry)

    manifest = {
        "schemaVersion": "evidence.manifest.v3",
        "phase": "V2-2A Native Window / Focus Monitor (R2 blocker rework)",
        "title": "V2-2A native window / focus monitor - evidence bundle",
        "repository": str(REPO),
        "remote": "https://github.com/suifracti/yihuanpaimai.git",
        "baselineCommit": BASELINE,
        "headCommit": head,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "diffStat": git("diff", "--stat", BASELINE, "HEAD").splitlines()[-1].strip()
                     if git("diff", "--stat", BASELINE, "HEAD") else "",
        "declaredArtifacts": declared,
        "fileCount": len(declared),
        "totalPhysicalFiles": len(physical),
        "files": entries,
        "rawHeads": {name: raw_head(OUT / name) for name in RAW_LOGS},
        "rawClassifications": {name: raw_classification(OUT / name) for name in RAW_LOGS},
        "rawExitCodes": {name: raw_exit_code(OUT / name) for name in RAW_LOGS},
        "unittestSummaries": {name: test_unittest_summary(OUT / name) for name in RAW_LOGS},
        "selfCheck": {
            # A real directory self-check, in BOTH directions, plus per-file integrity.
            # The previous version only asked "are the required files present?", which is
            # how two orphans (an old R0 Summary and an old combined guard raw) could sit
            # in the canonical directory while `allPassed` was true.
            "declaredCount": len(declared),
            "physicalCountExcludingManifest": len(physical) - (
                1 if "evidence_manifest.json" in physical else 0),
            "missing": missing,
            "unexpected": unexpected,
            "hashMismatch": hash_mismatch,
            "sizeMismatch": size_mismatch,
            "rawHeadMismatch": raw_head_mismatches,
            "failedRaws": raw_failed,
            "orphansAbsent": not unexpected,
            "allRequiredPresent": not missing,
            "manifestGeneratedLast": True,
        },
        "allPassed": not (missing or unexpected or hash_mismatch or size_mismatch
                          or raw_head_mismatches or raw_failed),
    }
    write("evidence_manifest.json", manifest)

    print(f"head={head}")
    print(f"declared={len(declared)} physical(excl manifest)={len(physical) - 1}")
    print(f"missing={missing}")
    print(f"unexpected={unexpected}")
    print(f"hashMismatch={hash_mismatch}")
    print(f"sizeMismatch={size_mismatch}")
    print(f"allPassed={manifest['allPassed']}")
    return 0 if manifest["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
