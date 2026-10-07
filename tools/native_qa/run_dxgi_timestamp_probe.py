"""One authorized own-window DXGI experiment. No external HWND is accepted."""
import argparse
import hashlib
import json
from pathlib import Path
from run_timestamp_probe import EVIDENCE, HOST, ROOT, prepare, run_once

EXE = EVIDENCE / "dxgi-out/DxgiTimestampProbe.exe"

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()
    audited_sdk = "0ec371d93798852e36461c8adddbeadce0f963a04752f0b64e54fe19c1c834a7"
    if hashlib.sha256((HOST / "Microsoft.Windows.SDK.NET.dll").read_bytes()).hexdigest() != audited_sdk:
        raise RuntimeError("SDK layout changed; original-pointer ABI audit required")
    if (HOST / "NteHost.Protocol.dll").read_bytes() != (EXE.parent / "NteHost.Protocol.dll").read_bytes():
        raise RuntimeError("Protocol differs from production candidate")
    sources = [Path(__file__), Path(__file__).with_name("run_timestamp_probe.py"),
               Path(__file__).with_name("game_timestamp_probe") / "Program.cs",
               *sorted(Path(__file__).with_name("dxgi_timestamp_probe").glob("*.*"))]
    prepared = {**prepare(EXE), "experimentKind": "self-dxgi",
        "probeExeSha256": hashlib.sha256(EXE.read_bytes()).hexdigest(),
        "dependencyHashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EXE.parent.glob("*.dll"))},
        "sourceHashes": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "budget": {"attempts": 3, "workSeconds": 8, "exitSeconds": 10},
        "candidateScope": "self-generated HWND only; production gate unchanged"}
    (EVIDENCE / "dxgi-prepared.json").write_text(json.dumps(prepared, indent=2), encoding="utf-8")
    if not args.run_once:
        print(json.dumps({"preparedOnly": True, **prepared}, indent=2))
        return 0
    return run_once(prepared, executable=EXE)

if __name__ == "__main__":
    raise SystemExit(main())
