"""Build a fresh, self-checking R4 evidence bundle without touching R3/R2."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(r"D:\yihuanpaimai-v2-2a")
EVIDENCE = Path(os.environ.get("V2_2A_R4_EVIDENCE_OUT",
                             str(REPO / "build" / "v2-2a-r4" / "evidence")))
RAW = Path(os.environ.get("V2_2A_R4_RAW_OUT",
                         str(REPO / "build" / "v2-2a-r4" / "raw")))
sys.path.insert(0, str(REPO / "tools" / "v2"))
import build_v2_2a_r1_evidence as base  # noqa: E402


RAW_LOGS = [
    "python_targeted_tests_raw.txt",
    "raw_queue_drain_regression_raw.txt",
    "callback_isolation_deterministic_raw.txt",
    "event_queue_overflow_regression_raw.txt",
    "v2_1_guard_oneshot_raw.txt",
    "v2_0_guard_raw.txt",
]

DECLARED = RAW_LOGS + [
    "measure_v2_2a_r4_raw.txt",
    "callback_isolation_measured.json",
    "event_queue_overflow_measured.json",
    "raw_queue_drain_measured.json",
    "forbidden_capability_scan.json",
    "no_production_reachability.json",
    "v2_1_t20_scan_coverage.json",
    "callback_isolation_design.json",
    "identity_revalidation_design.json",
    "guard_flake_policy.json",
    "event_queue_overflow_design.json",
    "architecture_notes.json",
    "target_spec_semantics.json",
    "controlled_window_session.json",
    "absent_target_session.json",
    "environment_facts.json",
    "git_diff.patch",
    "V2_2A_Window_Focus_Monitor_R4_Summary.md",
]


def r4_summary(head: str, raw_head_mismatches: list[dict]) -> None:
    def summary(name: str) -> dict:
        return base.test_unittest_summary(EVIDENCE / name)

    isolation = json.loads((EVIDENCE / "callback_isolation_measured.json").read_text(
        encoding="utf-8"))
    overflow = json.loads((EVIDENCE / "event_queue_overflow_measured.json").read_text(
        encoding="utf-8"))
    queue = json.loads((EVIDENCE / "raw_queue_drain_measured.json").read_text(
        encoding="utf-8"))
    direction_b = isolation.get("directionB", {})
    queue_probe = queue.get("probe", {})

    lines = [
        "# V2-2A Native Window / Focus Monitor - R4 Evidence Summary",
        "",
        "> Generated from the independent R4 directory. R3/R2 evidence directories are",
        "> retained and are not overwritten or reused as current raw output.",
        "",
        f"- Head: `{head}`",
        f"- Branch: `{base.git('rev-parse', '--abbrev-ref', 'HEAD')}`",
        "- Scope: one runtime blocker closure: atomic raw-event drain; no Boundary3, "
        "production wiring, V2-1 runtime, V2-0 contracts, merge, or tag.",
        f"- Raw head mismatches: `{raw_head_mismatches}`",
        "",
        "## Raw results",
        "",
        "| Run | Raw | Result | Ran | Passed | Failed | Errors | Skipped |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label, name in (
        ("V2-2A targeted", "python_targeted_tests_raw.txt"),
        ("double-drain regression", "raw_queue_drain_regression_raw.txt"),
        ("callback Direction-B", "callback_isolation_deterministic_raw.txt"),
        ("overflow regression", "event_queue_overflow_regression_raw.txt"),
        ("V2-1 one-shot", "v2_1_guard_oneshot_raw.txt"),
        ("V2-0 guard", "v2_0_guard_raw.txt"),
    ):
        item = summary(name)
        lines.append(
            f"| {label} | `{name}` | **{item.get('verdict')}** | {item.get('ran')} | "
            f"{item.get('passed')} | {item.get('failed')} | {item.get('errors')} | "
            f"{item.get('skipped')} |"
        )

    lines.extend([
        "",
        "## Measured runtime evidence",
        "",
        f"- Direction-B known N: `{direction_b.get('knownN')}`; baseline stable: "
        f"`{direction_b.get('baselineStable')}`; raw lock acquired: "
        f"`{direction_b.get('holdRawAcquired')}`; producer completed before release: "
        f"`{direction_b.get('producerCompletedBeforeRelease')}`.",
        f"- Direction-B processed events: `{direction_b.get('processedEventsBeforeRelease')}` "
        f"→ `{direction_b.get('processedEventsAfterRelease')}`; exact delta N: "
        f"`{direction_b.get('processedDeltaExactlyN')}`; second quiet interval delta: "
        f"`{direction_b.get('quietIntervalDelta')}`; queue after quiet: "
        f"`{direction_b.get('queueCountAfterQuiet')}`.",
        f"- Raw queue first batch: `{queue_probe.get('firstBatchSize')}` events, content/order "
        f"match: `{queue_probe.get('firstEvents') == queue_probe.get('expectedEvents')}`, "
        f"Count after first drain: `{queue_probe.get('countAfterFirstDrain')}`; second batch: "
        f"`{queue_probe.get('secondBatchSize')}`, drop delta: `{queue_probe.get('secondDropDelta')}`.",
        f"- Raw queue overflow: first drop delta `{queue_probe.get('overflowFirstDropDelta')}`, "
        f"Count after first drain `{queue_probe.get('overflowCountAfterFirstDrain')}`, second "
        f"batch/drop delta `{queue_probe.get('overflowSecondBatchSize')}/"
        f"{queue_probe.get('overflowSecondDropDelta')}`.",
        f"- Overflow quiet-window extra scans: `{overflow.get('extraRecoveryScansDuringQuiet')}`; "
        f"extra overflow observations: `{overflow.get('extraOverflowObservationsDuringQuiet')}`.",
        "",
        "The complete machine-readable measurements are `callback_isolation_measured.json`,",
        "`raw_queue_drain_measured.json`, and `event_queue_overflow_measured.json`.",
        "",
    ])
    (EVIDENCE / base.SUMMARY_NAME).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    base.OUT = EVIDENCE
    base.RAW = RAW
    base.RAW_LOGS = RAW_LOGS
    base.DECLARED_ARTIFACTS = DECLARED
    base.SUMMARY_NAME = "V2_2A_Window_Focus_Monitor_R4_Summary.md"
    base.write_summary = r4_summary
    result = base.main()
    manifest_path = EVIDENCE / "evidence_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["phase"] = "V2-2A Native Window / Focus Monitor (R4 drain closure)"
        manifest["title"] = "V2-2A native window / focus monitor - R4 evidence bundle"
        manifest["r4Closure"] = {
            "runtimeBlocker": "RawEventQueue.DrainWithDelta did not clear the queue",
            "fix": "snapshot -> clear -> return inside the same _sync critical section",
            "historicalEvidencePreserved": True,
            "historicalDirectories": ["build/v2-2a-r1", "build/v2-2a-r2"],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
