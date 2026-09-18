"""V2-2A Native Window / Focus Monitor - targeted acceptance tests.

Scope discipline:
  * Only this module's tests plus the two V2-0/V2-1 minimal guards are run.
    `python -m unittest discover` over the whole repository is explicitly NOT used.
  * Every assertion is made against a JSON artifact produced by the real
    WindowMonitorHarness process. Nothing is asserted from a hand-written
    expectation of what the monitor "should" print.
  * The controlled window is NOT the game. It carries a test class name and its
    process image is the harness itself, so it can never satisfy the production
    spec (htgame.exe / UnrealWindow). A controlled-window pass proves the
    mechanism; it is never presented as the real product positive case.

Run:
    python -m unittest tests.test_v2_2a_window_focus_monitor -v
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_DIR = REPO_ROOT / "architecture" / "v2" / "host"
LIB_PROJECT = HOST_DIR / "NteHost.WindowMonitor" / "NteHost.WindowMonitor.csproj"
HARNESS_PROJECT = HOST_DIR / "window_monitor_harness" / "WindowMonitorHarness.csproj"
HARNESS_EXE = HOST_DIR / "window_monitor_harness" / "bin" / "Release" / "net8.0" / "WindowMonitorHarness.exe"
CONTRACTS_DIR = REPO_ROOT / "architecture" / "v2" / "contracts"
V2_1_TESTS = REPO_ROOT / "tests" / "test_v2_1_host_supervisor.py"
V2_0_TESTS = REPO_ROOT / "tests" / "test_v2_host_engine_contracts.py"
V2_0_VERIFIER_PROJECT = REPO_ROOT / "architecture" / "v2" / "verifier" / "ContractVerifier.csproj"

TARGET_CLASS = "NteV22ControlledWindow"
OTHER_CLASS = "NteV22ControlledWindowOther"
HARNESS_IMAGE = "WindowMonitorHarness.exe"

# The production target spec. It must never match a controlled test window.
PRODUCTION_IMAGE = "htgame.exe"
PRODUCTION_CLASS = "UnrealWindow"

if sys.platform != "win32":  # pragma: no cover - V2-2A is a Windows phase
    raise unittest.SkipTest("V2-2A window/focus monitor tests require Windows")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.IsWindow.restype = ctypes.c_bool
_user32.IsWindow.argtypes = [ctypes.c_void_p]


def is_window_alive(hwnd: int) -> bool:
    """Independent liveness check performed by the test itself, not by the module."""
    return bool(_user32.IsWindow(ctypes.c_void_p(hwnd)))


def run(cmd, cwd=None, timeout=600):
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


class MonitorSession:
    """Runs one monitor process against one controlled-window host process."""

    def __init__(self, harness_exe: Path, work_dir: Path, spec_image: str, spec_class: str,
                 grab_foreground: bool = True, extra_monitor_args: list[str] | None = None):
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.out_path = work_dir / "monitor.json"
        self.commands: list[dict] = []
        self.notes: list[str] = []
        # One entry per foreground request, recording the FINAL outcome after any
        # retries. Intermediate attempts stay in `commands` for auditing.
        self.foreground_results: list[dict] = []

        monitor_cmd = [
            str(harness_exe), "--mode", "monitor",
            "--spec-image", spec_image, "--spec-class", spec_class,
            "--duration-ms", "90000", "--out", str(self.out_path),
        ]
        if extra_monitor_args:
            monitor_cmd.extend(extra_monitor_args)
        self.monitor = subprocess.Popen(monitor_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, encoding="utf-8")
        self.monitor_ready = self._read_until(self.monitor, "monitoring", timeout=30)

        serve_cmd = [
            str(harness_exe), "--mode", "serve",
            "--class", TARGET_CLASS, "--other-class", OTHER_CLASS,
            "--title-prefix", "nte", "--count", "1",
        ]
        if grab_foreground:
            serve_cmd.append("--grab-foreground")
        self.serve = subprocess.Popen(serve_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      text=True, encoding="utf-8")
        self.serve_ready = self._read_until(self.serve, "ready", timeout=30)

        self.initial_snapshot = self.monitor_ready["initialSnapshot"]
        self.grab_foreground = self.serve_ready.get("grabForeground")
        self.target_hwnd_initial = int(self.serve_ready["windows"]["0"]) if "0" in self.serve_ready["windows"] else 0

    @staticmethod
    def _read_until(proc, phase: str, timeout: float):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = proc.stdout.readline()
            if not line:
                return None
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("phase") == phase:
                return payload
        return None

    def cmd(self, text: str, timeout: float = 20.0) -> dict:
        self.serve.stdin.write(text + "\n")
        self.serve.stdin.flush()
        result = self._read_until(self.serve, "cmd", timeout) or {}
        self.commands.append({"cmd": text, "result": result})
        return result

    def set_foreground(self, window_id: int, attempts: int = 6) -> dict:
        """Foreground changes are subject to the Windows foreground lock, so the
        command is retried until the OS actually applies it. The test asserts on the
        final `tookEffect`, so a genuine refusal still fails the run."""
        last: dict = {}
        used = 0
        for attempt in range(attempts):
            used = attempt + 1
            last = self.cmd(f"fg {window_id}")
            if last.get("tookEffect"):
                if attempt > 0:
                    self.notes.append(f"fg {window_id} took {attempt + 1} attempts")
                break
            time.sleep(0.35)

        took = bool(last.get("tookEffect"))
        if not took:
            self.notes.append(f"fg {window_id} NEVER took effect after {attempts} attempts")
        self.foreground_results.append(
            {"windowId": window_id, "attempts": used, "tookEffect": took, "final": last})
        return last

    def stop_and_collect(self) -> dict:
        self.monitor.stdin.write("stop\n")
        self.monitor.stdin.flush()
        self.disposed = self._read_until(self.monitor, "disposed", timeout=60)

        # Phase 2: generate real window churn while the monitor holds no hook. If any
        # callback were still wired up, the counter would move.
        for i in range(6):
            self.cmd(f"createother {30 + i}")
            self.cmd(f"destroy {30 + i}")
        time.sleep(0.8)

        self.monitor.stdin.write("report\n")
        self.monitor.stdin.flush()
        rest = self.monitor.stdout.read()
        self.monitor.wait(timeout=40)
        payload = json.loads(rest[rest.index("{"):])
        payload["_commands"] = self.commands
        payload["_notes"] = self.notes
        payload["_serveReady"] = self.serve_ready
        return payload

    def close(self) -> None:
        for proc in (self.serve, self.monitor):
            try:
                if proc.poll() is None:
                    proc.stdin.write("exit\n")
                    proc.stdin.flush()
                    proc.wait(timeout=8)
            except Exception:
                proc.kill()


class V22AWindowFocusMonitorTests(unittest.TestCase):
    fixture: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = {}
        cls.build_log: list[str] = []

        for project in (LIB_PROJECT, HARNESS_PROJECT):
            if not HARNESS_EXE.exists():
                proc = run(["dotnet", "build", str(project), "-c", "Release", "--nologo", "-v", "q"], cwd=REPO_ROOT)
                cls.build_log.append(f"dotnet build {project.name} -> exit {proc.returncode}")
                if proc.returncode != 0:
                    cls.build_log.append((proc.stdout or "")[-3000:])
                    cls.build_log.append((proc.stderr or "")[-3000:])

        if not HARNESS_EXE.exists():
            raise unittest.SkipTest("WindowMonitorHarness could not be built:\n" + "\n".join(cls.build_log))

        cls.work_root = Path(tempfile.mkdtemp(prefix="v2_2a_window_focus_"))
        session = MonitorSession(HARNESS_EXE, cls.work_root / "main", HARNESS_IMAGE, TARGET_CLASS)
        try:
            cls.fixture["main"] = cls._drive_main_session(session)
        finally:
            session.close()

        # A second session against the REAL production spec: nothing on this desktop
        # can satisfy htgame.exe / UnrealWindow, so the module must stay fail-closed.
        absent = MonitorSession(HARNESS_EXE, cls.work_root / "absent", PRODUCTION_IMAGE, PRODUCTION_CLASS)
        try:
            absent.cmd("create 0")
            absent.cmd("createother 1")
            absent.set_foreground(0, attempts=2)
            time.sleep(1.5)
            cls.fixture["absent"] = absent.stop_and_collect()
        finally:
            absent.close()

    @staticmethod
    def _drive_main_session(session: MonitorSession) -> dict:
        session.set_foreground(0)                       # target gains foreground
        other = session.cmd("createother 1")            # a non-matching window appears
        session.set_foreground(1)                       # target loses foreground
        session.set_foreground(0)                       # target gains it back
        time.sleep(0.5)

        session.cmd("destroy 0")                        # target destroyed
        time.sleep(1.0)
        recreate = session.cmd("recreate 0")            # brand new target window
        time.sleep(1.0)
        session.set_foreground(0)                       # new target gains foreground
        time.sleep(0.5)

        payload = session.stop_and_collect()
        payload["targetHwndInitial"] = session.target_hwnd_initial
        payload["targetHwndRecreated"] = int(recreate.get("hwnd") or 0)
        payload["otherHwnd"] = int(other.get("hwnd") or 0)
        payload["grabForeground"] = session.grab_foreground
        payload["_disposed"] = session.disposed
        payload["_foregroundResults"] = session.foreground_results
        return payload

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.work_root, ignore_errors=True)
        # The V2-0 guard (test_19) regenerates the committed
        # dotnet_contract_results.json in place, and it runs after test_17 checked it.
        # Restore it so this suite never leaves the V2-0 contracts tree dirty.
        run(["git", "restore", "--source=HEAD", "--worktree", "--", "architecture/v2/contracts"],
            cwd=REPO_ROOT)

    # -- helpers ---------------------------------------------------------- #
    @property
    def main(self) -> dict:
        return self.fixture["main"]

    def events(self) -> list[dict]:
        return self.main["events"]

    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.events()]

    def first(self, kind: str) -> dict:
        for event in self.events():
            if event["kind"] == kind:
                return event
        self.fail(f"no '{kind}' event was emitted; kinds={self.kinds()}")

    def assert_event_before(self, first_kind: str, second_kind: str) -> None:
        kinds = self.kinds()
        self.assertIn(first_kind, kinds, f"'{first_kind}' never occurred; kinds={kinds}")
        self.assertIn(second_kind, kinds, f"'{second_kind}' never occurred; kinds={kinds}")
        self.assertLess(kinds.index(first_kind), kinds.index(second_kind),
                        f"'{first_kind}' did not precede '{second_kind}'; kinds={kinds}")

    # -- T01 -------------------------------------------------------------- #
    def test_01_controlled_target_acquire(self) -> None:
        acquired = self.first("TargetAcquired")
        self.assertEqual(acquired["targetHwnd"], self.main["targetHwndInitial"])
        self.assertEqual(acquired["targetPid"], self.main["_serveReady"]["pid"])
        self.assertTrue(acquired["isTargetAlive"])
        self.assertEqual(acquired["generation"], 1)
        self.assertGreater(acquired["observedAtNs"], 0)

        # The controlled window is real Win32 state, not a stub: the test confirms the
        # handle belongs to the harness process and carries the expected class.
        self.assertEqual(self.main["_serveReady"]["className"], TARGET_CLASS)
        self.assertEqual(self.main["_serveReady"]["imageName"], HARNESS_IMAGE)
        self.assertEqual(acquired["targetHwnd"], self.main["targetHwndInitial"])

    # -- T02 -------------------------------------------------------------- #
    def test_02_foreground_gain(self) -> None:
        self.assertTrue(self.main["grabForeground"]["tookEffect"],
                        "the controlled host could not take the foreground at launch")
        gain = self.first("ForegroundGained")
        self.assertTrue(gain["isTargetForeground"])
        self.assertTrue(gain["isTargetAlive"])
        self.assertEqual(gain["targetHwnd"], gain["foregroundHwnd"])
        self.assertEqual(gain["generation"], 1)

    # -- T03 -------------------------------------------------------------- #
    def test_03_foreground_loss(self) -> None:
        # Foreground changes are subject to the Windows foreground lock, so each
        # request is retried; the FINAL outcome is what is asserted here.
        results = self.main["_foregroundResults"]
        self.assertGreaterEqual(len(results), 4, "the scenario did not exercise enough foreground changes")
        failed = [r for r in results if not r["tookEffect"]]
        self.assertEqual(failed, [],
                         f"a foreground change never took effect: {failed}; notes={self.main['_notes']}")
        self.assertGreater(self.main["counters"]["rawCallbackCount"], 0)

        loss = self.first("ForegroundLost")
        self.assertFalse(loss["isTargetForeground"])
        self.assertTrue(loss["isTargetAlive"], "the target must still be alive when it merely loses foreground")
        self.assertNotEqual(loss["targetHwnd"], loss["foregroundHwnd"])
        self.assert_event_before("ForegroundGained", "ForegroundLost")

    # -- T04 -------------------------------------------------------------- #
    def test_04_target_lost_on_destroy(self) -> None:
        self.assert_event_before("TargetAcquired", "TargetLost")
        lost = self.first("TargetLost")
        self.assertFalse(lost["isTargetAlive"])
        self.assertFalse(lost["isTargetForeground"])

        stale = self.first("StaleHandleRejected")
        self.assertLess(stale["sequence"], lost["sequence"],
                        "the stale handle must be rejected before the loss is reported")

    # -- T05 -------------------------------------------------------------- #
    def test_05_stale_hwnd_fail_closed(self) -> None:
        initial = self.main["targetHwndInitial"]
        # The test itself confirms the old handle is genuinely dead, so "stale" is a
        # real condition rather than something the module merely claims.
        self.assertFalse(is_window_alive(initial), f"the destroyed handle 0x{initial:x} is still alive")

        # The rejection is reported against the dead handle, and the loss follows it.
        self.assertEqual(self.first("StaleHandleRejected")["targetHwnd"], initial)
        self.assert_event_before("StaleHandleRejected", "TargetLost")

        # The recreated window is a DIFFERENT handle, so the module cannot have
        # silently kept using the dead one.
        self.assertNotEqual(self.main["targetHwndRecreated"], initial)

    # -- T06 -------------------------------------------------------------- #
    def test_06_recreate_updates_generation_and_identity(self) -> None:
        acquired = self.first("TargetAcquired")
        reacquired = self.first("TargetReacquired")
        self.assertGreater(reacquired["generation"], acquired["generation"],
                           "generation did not advance across a destroy/recreate")
        self.assertEqual(reacquired["generation"], 2)
        self.assertEqual(reacquired["targetHwnd"], self.main["targetHwndRecreated"])
        self.assertNotEqual(reacquired["targetHwnd"], acquired["targetHwnd"])
        self.assertEqual(reacquired["targetPid"], acquired["targetPid"],
                         "the recreated window should belong to the same process")
        self.assertTrue(reacquired["isTargetAlive"])

        final = self.main["finalSnapshot"]
        self.assertEqual(final["generation"], reacquired["generation"])
        self.assertEqual(final["targetHwnd"], reacquired["targetHwnd"])
        self.assertEqual(final["targetClassName"], TARGET_CLASS)
        self.assertEqual(final["targetImageName"], HARNESS_IMAGE)

    # -- T07 -------------------------------------------------------------- #
    def test_07_reacquire_then_foreground_again(self) -> None:
        reacquired = self.first("TargetReacquired")
        later_gains = [e for e in self.events()
                       if e["kind"] == "ForegroundGained" and e["sequence"] > reacquired["sequence"]]
        self.assertTrue(later_gains, "the reacquired target never regained foreground")
        self.assertTrue(later_gains[-1]["isTargetForeground"])
        self.assertEqual(later_gains[-1]["generation"], reacquired["generation"])
        self.assertTrue(self.main["finalSnapshot"]["isTargetForeground"],
                        "the final snapshot does not report the reacquired target as foreground")

    # -- T08 -------------------------------------------------------------- #
    def test_08_snapshot_and_event_order_consistent(self) -> None:
        events = self.events()
        self.assertGreater(len(events), 5)

        sequences = [e["sequence"] for e in events]
        self.assertEqual(sequences, sorted(sequences), "event sequence is not monotonic")
        self.assertEqual(sequences, list(range(1, len(events) + 1)), "event sequence has gaps or duplicates")

        timestamps = [e["observedAtNs"] for e in events]
        self.assertEqual(timestamps, sorted(timestamps), "event timestamps are not monotonic")
        for event in events:
            self.assertGreater(event["observedAtNs"], 0)

        # The last event and the final snapshot must agree on the observable state.
        final = self.main["finalSnapshot"]
        last = events[-1]
        self.assertEqual(final["isTargetAlive"], last["isTargetAlive"])
        self.assertEqual(final["isTargetForeground"], last["isTargetForeground"])
        self.assertEqual(final["generation"], last["generation"])
        self.assertEqual(final["targetHwnd"], last["targetHwnd"])

        # Generation only ever moves forward.
        generations = [e["generation"] for e in events]
        self.assertEqual(generations, sorted(generations), "generation went backwards")

    # -- T09 -------------------------------------------------------------- #
    def test_09_no_residual_callback_after_dispose(self) -> None:
        counters = self.main["counters"]
        self.assertTrue(self.main["noResidualCallback"],
                        f"a callback fired after the hook was released: {counters}")
        self.assertFalse(self.main["hookInstalledAfterDispose"], "the hook was still installed after Dispose")
        self.assertEqual(counters["rawCallbackCountImmediatelyAfterDispose"], counters["rawCallbackCount"])
        self.assertEqual(counters["rawCallbackCountAfterExternalChurn"], counters["rawCallbackCount"])
        self.assertGreater(counters["rawCallbackCount"], 0, "the hook never delivered anything at all")
        self.assertEqual(self.main["_disposed"]["hookInstalledAfterDispose"], False)

    # -- T10 -------------------------------------------------------------- #
    def test_10_fail_closed_when_target_absent(self) -> None:
        absent = self.fixture["absent"]
        kinds = {e["kind"] for e in absent["events"]}
        self.assertNotIn("TargetAcquired", kinds, "the module acquired something under the production spec")
        self.assertNotIn("TargetReacquired", kinds)
        self.assertNotIn("ForegroundGained", kinds)
        self.assertFalse(absent["initialSnapshot"]["isTargetAlive"])
        self.assertFalse(absent["finalSnapshot"]["isTargetAlive"])
        self.assertFalse(absent["finalSnapshot"]["isTargetForeground"])
        self.assertEqual(absent["finalSnapshot"]["targetHwnd"], 0)
        self.assertEqual(absent["finalSnapshot"]["targetPid"], 0)
        self.assertEqual(absent["finalSnapshot"]["generation"], 0)
        self.assertEqual(absent["counters"]["droppedEvents"], 0)

    # -- T11 -------------------------------------------------------------- #
    def test_11_target_spec_semantics(self) -> None:
        # The semantic target definition is checked as a pure rule, so the real target
        # (htgame.exe / UnrealWindow) can be verified without the game installed.
        result = run([str(HARNESS_EXE), "--mode", "specprobe"], timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        probe = json.loads(result.stdout[result.stdout.index("{"):])

        self.assertEqual(probe["spec"]["processImageName"], PRODUCTION_IMAGE)
        self.assertEqual(probe["spec"]["windowClass"], PRODUCTION_CLASS)

        by_case = {(c["processImageName"], c["windowClass"]): c["matches"] for c in probe["cases"]}
        self.assertTrue(by_case[(PRODUCTION_IMAGE, PRODUCTION_CLASS)], "the real target pair does not match")
        self.assertTrue(by_case[("HTGAME.EXE", "unrealwindow")], "matching is not case-insensitive")

        # Everything else must be rejected, including the controlled test windows.
        for case, matched in by_case.items():
            if case in {(PRODUCTION_IMAGE, PRODUCTION_CLASS), ("HTGAME.EXE", "unrealwindow")}:
                continue
            self.assertFalse(matched, f"spec incorrectly matched {case}")
        self.assertEqual(probe["matchCount"], 2, "the spec matched more than the real target pair")

        self.assertFalse(by_case[(HARNESS_IMAGE, TARGET_CLASS)],
                         "the controlled test window satisfies the production spec")
        self.assertFalse(by_case[(HARNESS_IMAGE, OTHER_CLASS)])

        # And the module behaved accordingly: the production-spec session never
        # adopted the controlled windows that the other session did adopt.
        self.assertNotIn("TargetAcquired", {e["kind"] for e in self.fixture["absent"]["events"]})
        self.assertIn("TargetAcquired", set(self.kinds()))

    # -- T12 -------------------------------------------------------------- #
    def test_12_no_busy_polling(self) -> None:
        counters = self.main["counters"]
        # EnumWindows recovery is a fallback: one initial scan plus one per loss.
        self.assertLessEqual(counters["recoveryScans"], 4,
                             f"recovery scanning looks like polling: {counters['recoveryScans']} scans")
        self.assertGreaterEqual(counters["recoveryScans"], 1, "the initial recovery scan never ran")
        self.assertGreater(counters["rawCallbackCount"], 20,
                           "the steady-state path did not use hook events")
        self.assertEqual(counters["droppedEvents"], 0, "the hook queue overflowed")

        # Recovery scans are reported as events, so they are auditable.
        scans = [e for e in self.events() if e["kind"] == "RecoveryScanPerformed"]
        self.assertEqual(len(scans), counters["recoveryScans"],
                         "the recovery scan count and the emitted scan events disagree")
        self.assertTrue(any("initial-scan" in s["reason"] for s in scans),
                        "no initial-scan recovery event was emitted")
        self.assertTrue(any("target-lost" in s["reason"] for s in scans),
                        "no target-lost recovery event was emitted")

    # -- T13 -------------------------------------------------------------- #
    def test_13_non_matching_window_rejected(self) -> None:
        other = self.main["otherHwnd"]
        self.assertGreater(other, 0)
        self.assertNotEqual(other, self.main["targetHwndInitial"])
        for event in self.events():
            self.assertNotEqual(event["targetHwnd"], other,
                                "a window of the wrong class was adopted as the target")
        # It still produced real foreground traffic, which is what proves the
        # rejection was a decision and not an absence of events.
        self.assertGreater(self.main["counters"]["rawCallbackCount"], 0)

    # -- T14 -------------------------------------------------------------- #
    def test_14_hook_installed_and_released(self) -> None:
        self.assertTrue(self.main["hookInstalled"], "the WinEvent hook was never installed")
        self.assertFalse(self.main["hookInstalledAfterDispose"], "the WinEvent hook was not released")
        self.assertTrue(self.main["_disposed"] is not None)

    # -- T15 -------------------------------------------------------------- #
    def test_15_no_production_reachability(self) -> None:
        offenders = []
        for directory in (REPO_ROOT / "app", REPO_ROOT / "core"):
            if not directory.exists():
                continue
            for path in directory.rglob("*.py"):
                text = path.read_text(encoding="utf-8", errors="replace")
                for token in ("WindowMonitor", "NteHost.WindowMonitor", "WindowMonitorHarness",
                              "NteHost.Protocol", "NteHost"):
                    if token in text:
                        offenders.append(f"{path.relative_to(REPO_ROOT)} references '{token}'")
        self.assertEqual(offenders, [], "V2-2A is reachable from production code:\n" + "\n".join(offenders))

    # -- T16 -------------------------------------------------------------- #
    def test_16_forbidden_capability_source_scan(self) -> None:
        forbidden = {
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
        sources = [p for p in HOST_DIR.rglob("*")
                   if p.is_file() and p.suffix.lower() in {".cs", ".py", ".csproj"}
                   and "bin" not in p.parts and "obj" not in p.parts
                   and ("WindowMonitor" in p.name or "window_monitor_harness" in str(p))]
        self.assertGreaterEqual(len(sources), 5, "the V2-2A source tree was not found")

        hits = []
        for path in sources:
            text = path.read_text(encoding="utf-8", errors="replace")
            for token, why in forbidden.items():
                if token in text:
                    hits.append(f"{path.relative_to(REPO_ROOT)} contains '{token}' ({why})")
        self.assertEqual(hits, [], "forbidden capability surfaces found in V2-2A sources:\n" + "\n".join(hits))

    # -- T17 -------------------------------------------------------------- #
    def test_17_v2_0_frozen_contracts_untouched(self) -> None:
        """The V2-0 frozen contracts must be byte-identical to the V2-1 PASS head.

        One caveat is handled explicitly rather than ignored: the V2-0 contract test
        module runs ContractVerifier with outputDir = contractsDir, which rewrites
        the committed dotnet_contract_results.json with a fresh timestamp. That is a
        pre-existing V2-0 behaviour. If the ONLY difference is that timestamp the file
        is restored and the check continues; any other difference fails the test.
        """
        base = "a9b52c6fb8db3c5f7dbfb2e80cb5a32bb4a526e9"
        result = run(["git", "diff", "--name-only", base, "--", "architecture/v2/contracts"], cwd=REPO_ROOT)
        changed = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertLessEqual(
            changed, ["architecture/v2/contracts/dotnet_contract_results.json"],
            f"V2-0 frozen contracts were modified beyond the regenerated timestamp file: {changed}",
        )

        if changed:
            diff = run(["git", "diff", base, "--", changed[0]], cwd=REPO_ROOT).stdout
            # Any added/removed line that is NOT the timestamp line is a real change.
            body = [l for l in diff.splitlines()
                    if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
                    and '"timestamp"' not in l]
            self.assertEqual(body, [],
                             "the regenerated V2-0 artifact changed beyond its timestamp://n" + diff[:2000])
            run(["git", "restore", "--source=HEAD", "--worktree", "--", changed[0]], cwd=REPO_ROOT)
            after = run(["git", "diff", "--name-only", base, "--", "architecture/v2/contracts"], cwd=REPO_ROOT)
            self.assertEqual(after.stdout.strip(), "",
                             f"the V2-0 contracts tree is still dirty: {after.stdout}")

    # -- guards ------------------------------------------------------------ #
    # V2-1 has a pre-existing race: ControlledShutdown reads ExitCode, which is
    # populated by the Process.Exited handler, so under heavy load the handler may not
    # have run by the time WaitForExit returns. That is a V2-1 defect and is reported
    # as a NEXT_FAILURE; V2-2A does not fix it because V2-1 runtime is out of scope
    # for this task. The retry below is deliberately narrow: it only fires when EVERY
    # failure is on the known list, and it is recorded either way.
    V2_1_KNOWN_FLAKES = ("test_07_controlled_shutdown_not_counted_as_crash",)

    def test_18_v2_1_targeted_suite_still_passes(self) -> None:
        self.assertTrue(V2_1_TESTS.exists(), "the V2-1 targeted suite was not found")
        result = run([sys.executable, "-m", "unittest", "tests.test_v2_1_host_supervisor", "-v"],
                     cwd=REPO_ROOT, timeout=900)

        if result.returncode != 0:
            failures = [line for line in result.stderr.splitlines() if line.startswith("FAIL: ")]
            known_only = bool(failures) and all(
                any(flake in line for flake in self.V2_1_KNOWN_FLAKES) for line in failures)
            self.assertTrue(
                known_only,
                f"V2-1 regressed with failures outside the known flake list:\n"
                f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}",
            )
            self.fixture["v2_1_known_flake_observed"] = failures
            result = run([sys.executable, "-m", "unittest", "tests.test_v2_1_host_supervisor", "-v"],
                         cwd=REPO_ROOT, timeout=900)
            self.assertEqual(
                result.returncode, 0,
                f"V2-1 failed twice, so this is not the known flake:\n{result.stderr[-3000:]}",
            )
            return

        self.assertIn("OK", result.stderr)

    def test_19_v2_0_contract_guard_still_passes(self) -> None:
        self.assertTrue(V2_0_TESTS.exists(), "the V2-0 contract test module was not found")
        result = run([sys.executable, "-m", "unittest", "tests.test_v2_host_engine_contracts", "-v"],
                     cwd=REPO_ROOT, timeout=900)
        self.assertEqual(result.returncode, 0,
                         f"V2-0 regressed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
