"""V2-1 Native Host Process Supervisor — targeted contract tests (T01-T23).

Scope discipline for this file:
  * It only runs the V2-1 minimal set plus the two V2-0 regression guards.
    `python -m unittest discover` over the whole repository is explicitly not used.
  * Every assertion is made against a machine-readable artifact produced by the
    real NteHost executable and the real Python reference engine. Nothing is
    asserted from a hand-written expectation of what the host "should" print.
  * Metrics are reported per-metric. There is no summed "recovery" headline, and
    mock readiness is never presented as real business readiness.

Run:
    python -m unittest tests.test_v2_1_host_supervisor -v
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_DIR = REPO_ROOT / "architecture" / "v2" / "host"
CONTRACTS_DIR = REPO_ROOT / "architecture" / "v2" / "contracts"
HOST_PROJECT = HOST_DIR / "NteHost" / "NteHost.csproj"
VERIFIER_PROJECT = HOST_DIR / "verifier" / "HostSupervisorVerifier.csproj"
ENGINE_SCRIPT = HOST_DIR / "engine_ref" / "nte_engine_ref.py"
HOST_EXE = HOST_DIR / "NteHost" / "bin" / "Release" / "net8.0" / "NteHost.exe"
VERIFIER_EXE = HOST_DIR / "verifier" / "bin" / "Release" / "net8.0" / "HostSupervisorVerifier.exe"
V2_0_CONTRACT_TESTS = REPO_ROOT / "tests" / "test_v2_host_engine_contracts.py"
V2_0_VERIFIER_PROJECT = REPO_ROOT / "architecture" / "v2" / "verifier" / "ContractVerifier.csproj"

# Windows-only native host: Named Pipe + Job Object + shared memory.
if sys.platform != "win32":  # pragma: no cover - V2-1 is a Windows phase
    raise unittest.SkipTest("V2-1 native host supervisor tests require Windows")

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]

_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WAIT_OBJECT_0 = 0


def pid_alive(pid: int) -> bool:
    handle = _k32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        return _k32.WaitForSingleObject(handle, 0) != _WAIT_OBJECT_0
    finally:
        _k32.CloseHandle(handle)


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


class HostSupervisorFixture:
    """Builds the V2-1 artifacts once and runs every scenario once."""

    _instance: "HostSupervisorFixture | None" = None

    def __init__(self) -> None:
        self.work_root = Path(tempfile.mkdtemp(prefix="v2_1_host_supervisor_"))
        self.build_log: list[str] = []
        self.scenarios: dict[str, dict] = {}
        self.verifier: dict = {}
        self.hold: dict = {}
        self.v2_0_contract_tests: subprocess.CompletedProcess | None = None
        self.v2_0_verifier: dict = {}
        self.build_ok = False
        self._build()
        if self.build_ok:
            self._run_scenarios()
            self._run_verifier()
            self._run_hold_kill()
            self._run_v2_0_regression()

    @classmethod
    def get(cls) -> "HostSupervisorFixture":
        if cls._instance is None:
            cls._instance = HostSupervisorFixture()
        return cls._instance

    # -- build ------------------------------------------------------------ #
    def _dotnet(self, *args: str) -> subprocess.CompletedProcess:
        result = run(["dotnet", *args], cwd=REPO_ROOT)
        self.build_log.append(f"dotnet {' '.join(args)} -> exit {result.returncode}")
        if result.returncode != 0:
            self.build_log.append((result.stdout or "")[-4000:])
            self.build_log.append((result.stderr or "")[-4000:])
        return result

    def _build(self) -> None:
        if not HOST_EXE.exists():
            self._dotnet("build", str(HOST_PROJECT), "-c", "Release", "--nologo", "-v", "q")
        if not VERIFIER_EXE.exists():
            self._dotnet("build", str(VERIFIER_PROJECT), "-c", "Release", "--nologo", "-v", "q")
        self.build_ok = HOST_EXE.exists() and VERIFIER_EXE.exists()

    # -- scenarios -------------------------------------------------------- #
    def _scenario(self, name: str, extra: list[str] | None = None, timeout: int = 180) -> dict:
        work_dir = self.work_root / name
        work_dir.mkdir(parents=True, exist_ok=True)
        out_path = work_dir / "result.json"
        cmd = [
            str(HOST_EXE),
            "--scenario", name,
            "--python", sys.executable,
            "--engine", str(ENGINE_SCRIPT),
            "--work-dir", str(work_dir),
            "--out", str(out_path),
            "--trace", str(work_dir / "host_trace.jsonl"),
        ]
        if extra:
            cmd.extend(extra)
        proc = run(cmd, timeout=timeout)
        payload: dict = {
            "scenario": name,
            "exitCode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        if out_path.exists():
            payload.update(json.loads(out_path.read_text(encoding="utf-8")))
        self.scenarios[name] = payload
        return payload

    def _run_scenarios(self) -> None:
        self._scenario("golden")
        self._scenario("coldboot")
        self._scenario("reconnect")
        self._scenario("generation")
        self._scenario("mmf")
        self._scenario("pipeatfail")
        self._scenario("heartbeat")
        self._scenario("resyncfault")
        self._scenario("capability", ["--engine-fault-missing-capability", "BitBlt"])
        self._scenario("faults", ["--engine-fault-hello-size", "12345"])
        self._scenario("metrics", ["--runs", "5"], timeout=420)

    def _run_verifier(self) -> None:
        metrics = self.work_root / "metrics" / "result.json"
        out_path = self.work_root / "dotnet_verifier_result.json"
        proc = run([
            str(VERIFIER_EXE),
            "--start-dir", str(VERIFIER_PROJECT.parent),
            "--metrics", str(metrics),
            "--out", str(out_path),
        ], timeout=180)
        self.verifier = {
            "exitCode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        if out_path.exists():
            self.verifier.update(json.loads(out_path.read_text(encoding="utf-8")))

    def _run_hold_kill(self) -> None:
        work_dir = self.work_root / "hold"
        work_dir.mkdir(parents=True, exist_ok=True)
        ready = work_dir / "host_ready.json"
        proc = subprocess.Popen(
            [
                str(HOST_EXE), "--scenario", "hold", "--hold-ms", "60000",
                "--python", sys.executable, "--engine", str(ENGINE_SCRIPT),
                "--work-dir", str(work_dir), "--out", str(work_dir / "result.json"),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and not ready.exists():
            time.sleep(0.02)

        if not ready.exists():
            proc.kill()
            self.hold = {"ready": False, "orphanPrevented": False}
            return

        info = json.loads(ready.read_text(encoding="utf-8"))
        child_pid = info["childPid"]
        child_alive_before = pid_alive(child_pid)

        started = time.monotonic()
        os.kill(proc.pid, signal.SIGTERM)   # TerminateProcess: no graceful cleanup path
        proc.wait(timeout=30)
        host_terminate_ms = (time.monotonic() - started) * 1000

        gone_at = None
        poll_started = time.monotonic()
        while time.monotonic() - poll_started < 20:
            if not pid_alive(child_pid):
                gone_at = (time.monotonic() - poll_started) * 1000
                break
            time.sleep(0.001)

        self.hold = {
            "ready": True,
            "hostPid": proc.pid,
            "childPid": child_pid,
            "childAliveBeforeKill": child_alive_before,
            "hostTerminateMs": host_terminate_ms,
            "childDisappearedMs": gone_at,
            "orphanPrevented": gone_at is not None,
            "mapName": info["mapName"],
            "killMethod": "TerminateProcess (SIGTERM, no graceful cleanup path)",
        }

    def _run_v2_0_regression(self) -> None:
        # The V2-0 contract test module runs the frozen ContractVerifier with
        # outputDir = contractsDir, which rewrites the committed
        # dotnet_contract_results.json (timestamp only). V2-1 must not modify any
        # V2-0 artifact, so the file is snapshotted and restored, and any change
        # beyond the timestamp is surfaced as a failure rather than hidden.
        guarded = CONTRACTS_DIR / "dotnet_contract_results.json"
        before = guarded.read_bytes() if guarded.exists() else None
        self.v2_0_artifact_guard: dict = {"path": str(guarded), "changed": False, "restored": False, "timestampOnly": None}

        if V2_0_CONTRACT_TESTS.exists():
            self.v2_0_contract_tests = run(
                [sys.executable, "-m", "unittest", "tests.test_v2_host_engine_contracts", "-v"],
                cwd=REPO_ROOT, timeout=600,
            )
        if V2_0_VERIFIER_PROJECT.exists():
            # The V2-0 verifier takes positional [contractsDir] [outputDir] and writes
            # its JSON reports there. The output dir is deliberately outside the
            # repository so this guard cannot dirty the V2-0 contracts tree.
            out_dir = self.work_root / "v2_0_verifier_out"
            out_dir.mkdir(parents=True, exist_ok=True)
            proc = run([
                "dotnet", "run", "--project", str(V2_0_VERIFIER_PROJECT), "-c", "Release",
                "--", str(CONTRACTS_DIR), str(out_dir),
            ], cwd=REPO_ROOT, timeout=600)
            self.v2_0_verifier = {"exitCode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
            results_path = out_dir / "dotnet_contract_results.json"
            if results_path.exists():
                try:
                    self.v2_0_verifier.update(json.loads(results_path.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    pass

        after = guarded.read_bytes() if guarded.exists() else None
        if before is not None and after is not None and before != after:
            self.v2_0_artifact_guard["changed"] = True
            import re

            def normalise(raw: bytes) -> bytes:
                return re.sub(rb'"timestamp":\s*"[^"]*"', b'"timestamp": "NORMALISED"', raw)

            if normalise(before) == normalise(after):
                guarded.write_bytes(before)
                self.v2_0_artifact_guard.update({"restored": True, "timestampOnly": True})
            else:
                self.v2_0_artifact_guard.update({"restored": False, "timestampOnly": False})

    def cleanup(self) -> None:
        shutil.rmtree(self.work_root, ignore_errors=True)


class V21HostSupervisorTests(unittest.TestCase):
    fixture: HostSupervisorFixture

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = HostSupervisorFixture.get()
        if not cls.fixture.build_ok:
            raise unittest.SkipTest(
                "V2-1 host/verifier could not be built:\n" + "\n".join(cls.fixture.build_log)
            )

    # -- helpers ---------------------------------------------------------- #
    def scenario(self, name: str) -> dict:
        payload = self.fixture.scenarios.get(name)
        self.assertIsNotNone(payload, f"scenario '{name}' was not executed")
        self.assertTrue(payload.get("ok"), f"scenario '{name}' did not succeed: {payload.get('exceptionMessage')}")
        return payload["run"]

    def metric(self, name: str) -> dict:
        run_payload = self.scenario("metrics")
        self.assertIn(name, run_payload["summary"], f"metric '{name}' missing from the summary")
        return run_payload["summary"][name]

    # -- T01 -------------------------------------------------------------- #
    def test_01_host_starts_pipe_and_spawns_child(self) -> None:
        run_payload = self.scenario("coldboot")
        generation = run_payload["generations"][0]
        self.assertGreater(generation["ChildPid"], 0, "no child process was spawned")
        self.assertTrue(generation["PipeAccepted"], "the named pipe was never accepted")
        self.assertTrue(generation["HelloAckValidated"], "the HELLO_ACK was never validated")
        self.assertEqual(run_payload["errors"], [])
        self.assertTrue(run_payload["pipe"]["AclReadBackSucceeded"], "pipe ACL could not be read back")

    # -- T02 -------------------------------------------------------------- #
    def test_02_hello_hello_ack_wire_bytes_match_golden(self) -> None:
        golden = self.scenario("golden")
        self.assertEqual(golden["totalVectors"], 14, "the frozen catalog declares 14 message types")
        self.assertEqual(
            golden["mismatchedVectors"], 0,
            f"golden mismatches: {json.dumps(golden['mismatches'], indent=1)[:2000]}",
        )
        self.assertTrue(golden["allMatched"])
        self.assertEqual(len(golden["matchedMessageTypes"]), 14)

        # The live HELLO / HELLO_ACK frames must carry the frozen 8-field envelope
        # with the exact catalog field order and a 4-byte little-endian length prefix.
        run_payload = self.scenario("coldboot")
        generation = run_payload["generations"][0]
        expected_order = [
            "protocolVersion", "sessionId", "messageType", "requestId",
            "correlationId", "sequence", "monotonicTimestampNs", "payload",
        ]
        for label, hex_payload in (("HELLO", generation["HelloWireHex"]), ("HELLO_ACK", generation["HelloAckWireHex"])):
            raw = bytes.fromhex(hex_payload)
            declared = int.from_bytes(raw[:4], "little")
            self.assertEqual(declared, len(raw) - 4, f"{label} length prefix does not match its payload")
            body = json.loads(raw[4:].decode("utf-8"))
            self.assertEqual(list(body.keys()), expected_order, f"{label} envelope field order drifted")
        self.assertEqual(generation["HelloAckStatus"], "ACCEPTED")

    # -- T03 -------------------------------------------------------------- #
    def test_03_capability_negotiation_mandatory_gate(self) -> None:
        run_payload = self.scenario("capability")
        self.assertEqual(run_payload["faultInjectedCapability"], "BitBlt")
        self.assertIn("BitBlt", run_payload["mandatoryCapabilities"])
        self.assertEqual(run_payload["helloAckStatus"], "REJECTED_CAPABILITY")
        self.assertFalse(run_payload["capabilitiesAccepted"], "capabilities were accepted despite a missing mandatory one")
        self.assertFalse(run_payload["protocolNegotiated"], "protocol was marked negotiated after a capability rejection")
        self.assertFalse(run_payload["engineBusinessReady"])
        self.assertTrue(run_payload["readyTransitionRejected"], "READY was reachable after a capability rejection")
        self.assertEqual(run_payload["readyTransitionErrorCode"], "ERR_INVALID_STATE_TRANSITION")

        # NOT_MEASURED / EXPERIMENTAL capabilities must be advertised but never activated.
        advertised = run_payload["advertisedCapabilities"]
        self.assertEqual(advertised["WGC"], "NOT_MEASURED")
        self.assertEqual(advertised["WebView2"], "EXPERIMENTAL")
        self.assertEqual(advertised["SendInput"], "UNAVAILABLE")

    # -- T04 -------------------------------------------------------------- #
    def test_04_lifecycle_cold_boot_path(self) -> None:
        run_payload = self.scenario("coldboot")
        transitions = [(t["from"], t["to"], t["outcome"]) for t in run_payload["lifecycleTrace"]]
        self.assertEqual(
            transitions[:3],
            [("ENGINE_DOWN", "STARTING", "ACCEPTED"),
             ("STARTING", "HANDSHAKING", "ACCEPTED"),
             ("HANDSHAKING", "READY", "ACCEPTED")],
        )
        self.assertEqual(run_payload["lifecycleFinalState"], "ENGINE_DOWN")

        guards = run_payload["lifecycleGuards"]
        self.assertTrue(
            guards["coldBootWithoutNoRecoverableStateRejected"],
            "cold boot reached READY without noRecoverableBusinessState == true",
        )
        self.assertEqual(guards["coldBootWithoutNoRecoverableStateErrorCode"], "ERR_INVALID_STATE_TRANSITION")

    # -- T05 -------------------------------------------------------------- #
    def test_05_reconnect_forbids_handshaking_to_ready(self) -> None:
        run_payload = self.scenario("reconnect")
        self.assertTrue(run_payload["reconnectDirectReadyRejected"])
        self.assertEqual(run_payload["reconnectDirectReadyErrorCode"], "ERR_INVALID_STATE_TRANSITION")

        outcomes = [(t["from"], t["to"], t["outcome"]) for t in run_payload["lifecycleTrace"]]
        self.assertIn(("HANDSHAKING", "READY", "REJECTED"), outcomes)
        self.assertIn(("HANDSHAKING", "SYNCING", "ACCEPTED"), outcomes)
        self.assertIn(("SYNCING", "READY", "ACCEPTED"), outcomes)
        self.assertLess(
            outcomes.index(("HANDSHAKING", "SYNCING", "ACCEPTED")),
            len(outcomes) - 1 - outcomes[::-1].index(("SYNCING", "READY", "ACCEPTED")),
            "the reconnect did not pass through SYNCING before READY",
        )

    # -- T06 -------------------------------------------------------------- #
    def test_06_heartbeat_miss_degrades_and_recovers(self) -> None:
        run_payload = self.scenario("heartbeat")
        self.assertTrue(run_payload["heartbeatHealthyBeforeFault"])
        self.assertTrue(run_payload["heartbeatMissDetected"])
        self.assertEqual(run_payload["heartbeatMissErrorCode"], "ERR_HEARTBEAT_TIMEOUT")
        self.assertTrue(run_payload["degradedTransitionAccepted"])
        self.assertTrue(run_payload["childAliveWhileDegraded"], "the child process was killed on a heartbeat miss")
        self.assertTrue(run_payload["pipeAliveWhileDegraded"], "the pipe was torn down on a heartbeat miss")
        self.assertTrue(run_payload["heartbeatRecovered"])
        self.assertTrue(run_payload["readyAfterResync"], "the session never returned to READY after recovery")
        self.assertGreater(run_payload["snapshotResyncMs"], 0)
        self.assertEqual(run_payload["errors"], [])

        outcomes = [(t["from"], t["to"], t["outcome"]) for t in run_payload["lifecycleTrace"]]
        self.assertIn(("READY", "DEGRADED", "ACCEPTED"), outcomes)
        self.assertIn(("DEGRADED", "SYNCING", "ACCEPTED"), outcomes)

    # -- T07 -------------------------------------------------------------- #
    def test_07_controlled_shutdown_not_counted_as_crash(self) -> None:
        run_payload = self.scenario("coldboot")
        shutdown = run_payload["shutdown"]
        self.assertTrue(shutdown["shutdownMessageSent"])
        self.assertFalse(shutdown["awaitedShutdownAck"], "the host waited for a shutdown ACK that protocol 1.0.0 does not define")
        self.assertTrue(shutdown["gracefulExitWithin2000ms"])
        self.assertFalse(shutdown["explicitTerminateUsed"], "the graceful exit path still needed a forced terminate")
        self.assertFalse(shutdown["countedAsCrash"], "a controlled shutdown was counted as a crash")
        self.assertTrue(shutdown["shutdownRequested"])
        self.assertEqual(shutdown["childExitCode"], 0)

        # No private ACK message may have been invented.
        catalog = json.loads((CONTRACTS_DIR / "message_catalog_v1.json").read_text(encoding="utf-8"))
        types = {m["messageType"] for m in catalog["messages"]}
        self.assertNotIn("ENGINE_SHUTDOWN_ACK", types)
        self.assertEqual(len(types), 14)

    # -- T08 -------------------------------------------------------------- #
    def test_08_crash_detection_reports_exit_detection_ms(self) -> None:
        stats = self.metric("processExitDetectionMs")
        self.assertGreaterEqual(stats["sampleCount"], 5, "fewer than 5 independent crash-detection samples")
        self.assertIsNotNone(stats["min"])
        self.assertLessEqual(stats["min"], stats["median"])
        self.assertLessEqual(stats["median"], stats["max"])
        self.assertGreater(stats["median"], 0)

        raw = self.scenario("metrics")["raw"]
        for sample in raw:
            self.assertIn("exitDetectionSignal", sample)
            self.assertIn(sample["exitDetectionSignal"], ("process_exited", "ERR_STREAM_EOF", "ERR_PIPE_BROKEN"))

    # -- T09 -------------------------------------------------------------- #
    def test_09_restart_uses_new_nonce_and_new_pipe(self) -> None:
        run_payload = self.scenario("reconnect")
        identity = run_payload["generationIdentity"]
        self.assertTrue(identity["nonceChanged"], "the replacement generation reused the nonce")
        self.assertTrue(identity["mapNameChanged"], "the replacement generation reused the shared-memory name")
        self.assertTrue(identity["pipeNameChanged"], "the replacement generation reused the pipe name")
        self.assertIn(identity["generation1Nonce"], identity["generation1PipeName"])
        self.assertIn(identity["generation2Nonce"], identity["generation2PipeName"])

        restart_stats = self.metric("processRestartMs")
        self.assertGreaterEqual(restart_stats["sampleCount"], 5)
        self.assertGreater(restart_stats["median"], 0)

    # -- T10 -------------------------------------------------------------- #
    def test_10_generation_reset_accepts_zero_and_rejects_stale(self) -> None:
        run_payload = self.scenario("generation")
        proof = run_payload["generationProof"]

        # (A) the new generation's sequence 0 must be accepted ...
        self.assertTrue(proof["newGenerationAccepted"], f"sequence 0 rejected: {proof['newGenerationErrorCode']}")
        self.assertEqual(proof["newGenerationHighWater"], 0)
        self.assertTrue(proof["newGenerationSequence1Accepted"])

        # ... and the live handshake itself must carry sequence 0 from the engine.
        self.assertTrue(
            proof["liveHandshakeAcceptedSequenceZero"],
            "the live replacement handshake did not carry sequence 0",
        )
        self.assertEqual(proof["liveHandshakeEngineFirstSequence"], 0)

        # (B) an old-generation packet must fail closed with ERR_STALE_GENERATION.
        self.assertFalse(proof["oldGenerationAccepted"], "an old-generation packet was accepted")
        self.assertEqual(proof["oldGenerationErrorCode"], "ERR_STALE_GENERATION")
        self.assertFalse(proof["liveTrackerOldGenerationAccepted"])

        # A different session id must fail closed too, and neither may move the high-water mark.
        self.assertFalse(proof["foreignSessionAccepted"], "a foreign-session packet was accepted")
        self.assertEqual(proof["foreignSessionErrorCode"], "ERR_STALE_SESSION")
        self.assertTrue(proof["highWaterUnchangedByStalePackets"], "a rejected packet moved the high-water mark")

    # -- T11 -------------------------------------------------------------- #
    def test_11_stale_sequence_within_generation_rejected(self) -> None:
        proof = self.scenario("generation")["generationProof"]
        self.assertTrue(proof["withinGenerationReplayRejected"], "a replayed in-generation sequence was accepted")
        self.assertEqual(proof["withinGenerationReplayErrorCode"], "ERR_STALE_SEQUENCE")

    # -- T12 -------------------------------------------------------------- #
    def test_12_snapshot_resync_reconnect_path(self) -> None:
        run_payload = self.scenario("reconnect")
        stats = self.metric("snapshotResyncMs")
        self.assertGreaterEqual(stats["sampleCount"], 5, "fewer than 5 snapshot-resync samples")
        self.assertGreater(stats["min"], 0)

        outcomes = [(t["from"], t["to"], t["outcome"]) for t in run_payload["lifecycleTrace"]]
        self.assertIn(("HANDSHAKING", "SYNCING", "ACCEPTED"), outcomes)
        self.assertIn(("SYNCING", "READY", "ACCEPTED"), outcomes)
        generation = run_payload["generations"][1]
        self.assertIsNotNone(generation["SnapshotResyncMs"])
        self.assertGreater(generation["SnapshotResyncMs"], 0)

    # -- T13 -------------------------------------------------------------- #
    def test_13_snapshot_wrong_session_fails_closed(self) -> None:
        run_payload = self.scenario("resyncfault")
        self.assertEqual(run_payload["wrongSessionErrorCode"], "ERR_STALE_SESSION")
        self.assertTrue(run_payload["staleSessionFailClosed"])
        self.assertFalse(run_payload["reachedReadyWithWrongSession"], "a mismatched snapshot still reached READY")
        self.assertFalse(run_payload["snapshotResynced"], "a mismatched snapshot was marked as applied")
        self.assertNotEqual(run_payload["finalState"], "READY")

    # -- T14 -------------------------------------------------------------- #
    def test_14_job_object_kills_child_on_host_hard_kill(self) -> None:
        hold = self.fixture.hold
        self.assertTrue(hold.get("ready"), "the hold scenario never signalled readiness")
        self.assertTrue(hold["childAliveBeforeKill"], "the child was already gone before the host was killed")
        self.assertTrue(hold["orphanPrevented"], "the child survived a hard kill of the host (orphan)")
        self.assertLess(hold["childDisappearedMs"], 5000, "the child took too long to disappear after the host was killed")
        self.assertIn("TerminateProcess", hold["killMethod"])

        # The controlled-shutdown path must not be reported as a crash.
        shutdown = self.scenario("coldboot")["shutdown"]
        self.assertFalse(shutdown["countedAsCrash"])
        self.assertTrue(shutdown["shutdownRequested"])

    # -- T15 -------------------------------------------------------------- #
    def test_15_trace_correlation_roundtrip(self) -> None:
        run_payload = self.scenario("reconnect")
        # The host asserts the STATE_SNAPSHOT correlationId echoes the requestId; a
        # mismatch would have failed the scenario outright. Re-check from the artifact.
        self.assertTrue(run_payload["generations"][1]["SnapshotResyncMs"] > 0)

        trace_path = self.fixture.work_root / "reconnect" / "host_trace.jsonl"
        self.assertTrue(trace_path.exists(), "the host trace log was not written")
        lines = [json.loads(l) for l in trace_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertTrue(lines)
        required = {"sessionId", "sessionNonceShort", "generationId", "requestId", "correlationId", "event"}
        for line in lines:
            self.assertTrue(required.issubset(line.keys()), f"trace line is missing correlation keys: {line.keys()}")

        sends = [l for l in lines if l["event"] == "pipe.send" and l["details"]["messageType"] == "STATE_SNAPSHOT_REQUEST"]
        receives = [l for l in lines if l["event"] == "pipe.receive" and l["details"]["messageType"] == "STATE_SNAPSHOT"]
        self.assertTrue(sends, "no STATE_SNAPSHOT_REQUEST was traced")
        self.assertTrue(receives, "no STATE_SNAPSHOT was traced")
        self.assertEqual(receives[0]["correlationId"], sends[0]["requestId"],
                         "the STATE_SNAPSHOT correlationId did not echo the request requestId")

    # -- T16 -------------------------------------------------------------- #
    def test_16_pipe_rejects_remote_and_uses_current_user_sid(self) -> None:
        run_payload = self.scenario("coldboot")
        pipe = run_payload["pipe"]
        self.assertTrue(pipe["AclReadBackSucceeded"], "the live pipe DACL could not be read back")
        self.assertTrue(
            pipe["AllowAceForCurrentUserWithFullAccess"],
            f"no allow ACE grants full access to the current user SID {pipe['CurrentUserSid']}",
        )
        self.assertEqual(pipe["AllowAcesForOtherPrincipals"], 0,
                         "the pipe DACL grants access to a principal other than the current user")
        self.assertFalse(pipe["OwnerRightsSidPresent"],
                         "the DACL uses the OWNER RIGHTS placeholder S-1-3-4 instead of the current user SID")
        self.assertEqual(pipe["MaxInstances"], 1)
        self.assertTrue(pipe["RejectRemoteClientsRequested"])
        self.assertTrue(pipe["ByteModeRequested"])
        self.assertIn("PIPE_REJECT_REMOTE_CLIENTS", pipe["CreationMode"])
        self.assertIn("FILE_FLAG_OVERLAPPED", pipe["CreationMode"])

        sids = [ace["Sid"] for ace in pipe["Aces"] if ace["IsAllow"]]
        self.assertIn(pipe["CurrentUserSid"], sids)

    # -- T17 -------------------------------------------------------------- #
    def test_17_mock_business_ready_naming_enforced(self) -> None:
        run_payload = self.scenario("metrics")
        summary = run_payload["summary"]
        self.assertIn("mockBusinessReadyMs", summary)
        self.assertIsNotNone(summary["mockBusinessReadyMs"]["median"])
        self.assertIsNone(summary["businessReadyMs"], "a numeric businessReadyMs was reported under a mock engine")
        self.assertEqual(summary["businessReadyStatus"], "NOT_MEASURED")
        self.assertTrue(summary["mockBusinessReadyMs_isMock"])
        for sample in run_payload["raw"]:
            self.assertNotIn("businessReadyMs", sample)

        # A mock engine cannot claim real OCR/model readiness in the source either.
        engine_source = ENGINE_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("businessReadyMs", engine_source)

    # -- T18 -------------------------------------------------------------- #
    def test_18_hello_frame_buffer_size_mismatch_fatal(self) -> None:
        geometry = self.scenario("faults")["geometry"]
        self.assertEqual(geometry["injectedFrameBufferSize"], "12345")
        self.assertEqual(geometry["declaredFrameBufferSize"], 33177856)
        self.assertEqual(geometry["errorCode"], "ERR_RING_GEOMETRY_MISMATCH")
        self.assertTrue(geometry["fatalFailClosed"], "a geometry mismatch did not terminate the session")
        self.assertFalse(geometry["helloAckValidated"], "the handshake was validated despite a geometry mismatch")

    # -- T19 -------------------------------------------------------------- #
    def test_19_forbidden_capability_source_scan(self) -> None:
        # The scan targets real API surfaces, not bare capability labels: "BitBlt"
        # is a legitimate capability NAME advertised in HELLO, and "WebView2" only
        # appears inside the catalog error code ERR_WEBVIEW2_UNAVAILABLE. What must
        # not exist is an implementation of those capabilities.
        forbidden = {
            "Windows.Graphics.Capture": "WGC capture integration",
            "Windows.Graphics.DirectX": "WGC / Direct3D interop",
            "gdi32": "GDI screen capture",
            "PrintWindow": "screen capture",
            "CreateCompatibleDC": "screen capture",
            "SendInput": "input synthesis",
            "SetWindowsHookEx": "global input hooks",
            "WH_MOUSE_LL": "low-level mouse hook",
            "WH_KEYBOARD_LL": "low-level keyboard hook",
            "GetForegroundWindow": "focus/TOCTOU input guard",
            "EnumWindows": "window management",
            "SetWinEventHook": "foreground event monitoring",
            "CoreWebView2": "WebView2 hosting",
            "Microsoft.Web.WebView2": "WebView2 hosting",
            "DirectComposition": "overlay ownership",
            "LOCALAPPDATA": "history authority path",
            "异环拍卖助手": "history authority path",
            "b3-input-safety": "Boundary3",
            "warehouse": "warehouse scrolling",
            "app.main": "production startup integration",
        }
        # Import-style boundaries are checked separately so the message is precise.
        forbidden_imports = ("import core", "from core", "import app", "from app")

        sources = [
            p for p in HOST_DIR.rglob("*")
            if p.is_file()
            and p.suffix.lower() in {".cs", ".py", ".csproj"}
            and "bin" not in p.parts and "obj" not in p.parts
        ]
        self.assertGreater(len(sources), 5, "the V2-1 source tree was not found")

        hits = []
        for path in sources:
            text = path.read_text(encoding="utf-8", errors="replace")
            for token, why in forbidden.items():
                if token in text:
                    hits.append(f"{path.relative_to(REPO_ROOT)} contains '{token}' ({why})")
            for line in text.splitlines():
                if line.strip().startswith(forbidden_imports):
                    hits.append(f"{path.relative_to(REPO_ROOT)} imports a production module: {line.strip()}")
        self.assertEqual(hits, [], "forbidden capability surfaces found in V2-1 sources:\n" + "\n".join(hits))

        # The advertised capability set must be data-driven: the host reads the
        # frozen contract, and no per-capability literal may appear in host source.
        capability_source = (HOST_DIR / "NteHost.Protocol" / "CapabilityContract.cs").read_text(encoding="utf-8")
        self.assertIn("capability_negotiation_v1.json", capability_source)
        hardcoded = [name for name in ("BitBlt", "SharedMemoryRing", "NamedPipeIpc", "LowLevelHooks", "WebView2", "SendInput")
                     if f'"{name}"' in capability_source]
        self.assertEqual(hardcoded, [], f"host hardcodes capability names instead of reading the contract: {hardcoded}")

        # V2-1 must not have touched the Boundary3 branch or the Truth Matrix.
        truth_matrix = (
            REPO_ROOT.parent / "ObsidianLiveSyncTestVault" / "03-项目与工程" / "异环拍卖助手" / "Feature Truth Matrix.md"
        )
        if truth_matrix.exists():
            self.assertNotIn("V2-1", truth_matrix.read_text(encoding="utf-8", errors="replace")[:200000])

    # -- T20 -------------------------------------------------------------- #
    def test_20_no_production_reachability(self) -> None:
        production_dirs = [REPO_ROOT / "app", REPO_ROOT / "core"]
        offenders = []
        for directory in production_dirs:
            if not directory.exists():
                continue
            for path in directory.rglob("*.py"):
                if "bin" in path.parts or "obj" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for token in ("NteHost", "architecture.v2.host", "nte_engine_ref", "NteHost.Protocol"):
                    if token in text:
                        offenders.append(f"{path.relative_to(REPO_ROOT)} references '{token}'")
        self.assertEqual(offenders, [], "V2-1 is reachable from production code:\n" + "\n".join(offenders))

        # The V2-1 tree must not import anything from the production packages.
        bad_imports = []
        for path in HOST_DIR.rglob("*.py"):
            if "bin" in path.parts or "obj" in path.parts:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("import core", "from core", "import app", "from app")):
                    bad_imports.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {stripped}")
        self.assertEqual(bad_imports, [], "V2-1 imports production modules:\n" + "\n".join(bad_imports))

    # -- T21 -------------------------------------------------------------- #
    def test_21_mmf_exists_size_acl_and_generation_lifecycle(self) -> None:
        run_payload = self.scenario("mmf")
        self.assertTrue(run_payload["mmfCreated"], "the fixed-v1 shared memory was not created")
        self.assertEqual(run_payload["mapTotalSizeBytes"], 33177856)
        self.assertEqual(run_payload["slotCount"], 4)
        self.assertEqual(run_payload["slotSizeBytes"], 8294464)
        self.assertTrue(run_payload["zeroInitialized"], "the fresh mapping was not zero-initialised")
        self.assertEqual(run_payload["nonZeroBytesFound"], 0)
        self.assertTrue(run_payload["exactSizeViewSucceeded"])
        self.assertTrue(run_payload["oversizeViewDenied"],
                        "mapping past the declared capacity succeeded, so the real size is larger than declared")

        self.assertTrue(run_payload["engineOpenSucceeded"], "the engine could not open the mapping")
        self.assertEqual(run_payload["engineOpenMode"], "FILE_MAP_READ (0x0004)")
        self.assertEqual(run_payload["writeDenialStatus"], "PASS_OS_DENIED",
                         "a writable view through the read-only handle was not denied by the OS")
        self.assertEqual(run_payload["writeDenialErrorCode"], 5)  # ERROR_ACCESS_DENIED

        self.assertTrue(run_payload["mapNameChanged"], "the replacement generation reused the map name")
        self.assertNotEqual(run_payload["generation1MapName"], run_payload["generation2MapName"])
        self.assertTrue(run_payload["oldGenerationDisposed"])
        self.assertTrue(run_payload["oldGenerationReopenFailed"],
                        "the old generation's mapping was still openable after every handle was released")
        self.assertEqual(run_payload["oldGenerationReopenErrorCode"], 2)  # ERROR_FILE_NOT_FOUND
        self.assertTrue(run_payload["generation2Disposed"])
        self.assertTrue(run_payload["generation2ReopenFailed"])

    # -- T22 -------------------------------------------------------------- #
    def test_22_named_pipe_failure_does_not_use_stdio_fallback(self) -> None:
        run_payload = self.scenario("pipeatfail")
        transport = run_payload["transport"]
        self.assertTrue(transport["namedPipeImplemented"])
        self.assertFalse(transport["stdioFallbackImplemented"], "V2-1 must not implement a stdio IPC fallback")
        self.assertFalse(transport["stdioFallbackAttempted"], "a stdio fallback was attempted")
        self.assertEqual(transport["transportUsedForProtocol"], "named_pipe")
        self.assertEqual(transport["childStdioPurpose"], "logs_only")
        self.assertTrue(transport["childStdoutStderrRedirected"])

        # Part A: the engine can never reach the pipe -> fail closed, no transport swap.
        self.assertEqual(transport["pipeConnectFailureAction"], "FAIL_CLOSED")
        self.assertEqual(transport["pipeConnectFailureCode"], "ERR_HANDSHAKE_TIMEOUT")
        self.assertTrue(run_payload["partA"]["failClosed"])
        self.assertFalse(run_payload["partA"]["stdioUsed"])

        # Part B: the pipe is torn down after READY -> degrade then reconnect, still no swap.
        self.assertTrue(run_payload["partB"]["pipeAbortObserved"])
        self.assertTrue(run_payload["partB"]["degradedTransitionAccepted"])
        self.assertTrue(run_payload["partB"]["engineDownTransitionAccepted"])
        self.assertFalse(run_payload["partB"]["stdioUsed"])
        self.assertEqual(transport["pipeAbortAfterReadyAction"], "DEGRADED_THEN_ENGINE_DOWN_RECONNECT")

    # -- T23 -------------------------------------------------------------- #
    def test_23_mmf_has_no_frame_production_side_effect(self) -> None:
        run_payload = self.scenario("mmf")
        self.assertEqual(run_payload["frameHeadersWritten"], 0, "V2-1 wrote a FrameHeaderV1 into the ring")
        self.assertEqual(run_payload["frameReadyMessagesSent"], 0, "V2-1 emitted FRAME_READY")

        # No V2-1 source may send FRAME_READY or write a frame header.
        offenders = []
        for path in HOST_DIR.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".cs", ".py"}:
                continue
            if "bin" in path.parts or "obj" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "MessageTypes.FrameReady" in text or "FrameHeaderV1.Pack" in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [], "V2-1 sources reference frame production: " + ", ".join(offenders))

    # -- .NET verifier ---------------------------------------------------- #
    def test_24_dotnet_verifier_all_passed(self) -> None:
        verifier = self.fixture.verifier
        self.assertTrue(verifier, "the .NET verifier did not run")
        self.assertEqual(verifier.get("failedTests"), 0,
                         f"verifier failures: {json.dumps([r for r in verifier.get('results', []) if not r['Passed']], indent=1)}")
        self.assertEqual(verifier.get("totalTests"), 10, "the verifier did not run D01-D10")
        self.assertEqual(verifier.get("passedTests"), 10)
        self.assertTrue(verifier.get("allPassed"))

    # -- V2-0 regression guards ------------------------------------------- #
    def test_25_v2_0_contract_tests_still_pass(self) -> None:
        result = self.fixture.v2_0_contract_tests
        self.assertIsNotNone(result, "the V2-0 contract test module was not found")
        self.assertEqual(result.returncode, 0, f"V2-0 contract tests regressed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
        self.assertIn("OK", result.stderr)

    def test_26_v2_0_verifier_still_passes(self) -> None:
        verifier = self.fixture.v2_0_verifier
        self.assertTrue(verifier, "the V2-0 verifier did not run")
        self.assertEqual(verifier.get("exitCode"), 0,
                         f"V2-0 verifier regressed:\n{verifier.get('stdout', '')[-3000:]}\n{verifier.get('stderr', '')[-3000:]}")
        self.assertTrue(verifier.get("allPassed"), "the V2-0 verifier no longer reports allPassed")
        self.assertGreaterEqual(verifier.get("totalTests", 0), 40, "the V2-0 verifier ran fewer than its 40 accepted tests")

        # The V2-0 contract tree must come out of this run byte-identical except for
        # the regenerated timestamp.
        guard = self.fixture.v2_0_artifact_guard
        self.assertIsNot(guard["timestampOnly"], False,
                         f"a V2-0 committed artifact changed beyond its timestamp: {guard['path']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
