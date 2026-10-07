"""Prepare only by default; one explicitly authorized, pinned-window ABI take."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from run_timestamp_probe import EVIDENCE, HOST, ROOT, prepare, run_once

EXE = EVIDENCE / "game-abi-out/GameTimestampProbe.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--game-ready", action="store_true")
    parser.add_argument("--hwnd", type=int)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--instance", type=int)
    args = parser.parse_args()
    # The original-interface slot-7 read is safe only for the SDK layout audited here.
    audited_sdk = "0ec371d93798852e36461c8adddbeadce0f963a04752f0b64e54fe19c1c834a7"
    if hashlib.sha256((HOST / "Microsoft.Windows.SDK.NET.dll").read_bytes()).hexdigest() != audited_sdk:
        raise RuntimeError("SDK layout changed; audit required before direct original-pointer ABI read")
    # Verify the protocol conversion used by this probe is exactly the existing candidate's.
    if hashlib.sha256((HOST / "NteHost.Protocol.dll").read_bytes()).digest() != hashlib.sha256((EXE.parent / "NteHost.Protocol.dll").read_bytes()).digest():
        raise RuntimeError("Probe protocol differs from production candidate")
    prepared = {**prepare(EXE), "probeExeSha256": hashlib.sha256(EXE.read_bytes()).hexdigest(),
                "hostDependencyHashes": {name: hashlib.sha256((HOST / name).read_bytes()).hexdigest()
                                         for name in ("WgcLiveHarness.dll", "NteHost.WindowMonitor.dll", "NteHost.Protocol.dll")},
                "sourceHashes": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in [Path(__file__), Path(__file__).with_name("run_timestamp_probe.py"),
                                              *sorted(Path(__file__).with_name("game_timestamp_probe").glob("*.*"))]},
                "candidateScope": "independent-game-ABI-evidence; production unchanged"}
    if not args.run_once:
        print(json.dumps({"preparedOnly": True, **prepared}, indent=2))
        return 0
    if not args.game_ready or not all(value is not None and value > 0 for value in (args.hwnd, args.pid, args.instance)):
        parser.error("--run-once requires explicit --game-ready --hwnd --pid --instance after authorization")
    return run_once(prepared, executable=EXE, target={"hwnd": args.hwnd, "pid": args.pid, "instance": args.instance})


if __name__ == "__main__":
    raise SystemExit(main())
