"""Stage the fixed, already researched UE4SS build. Never installs or launches."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build/ue4ss"
ARCHIVE = ROOT / "build/research/20261023-local-auction-data/runtime-object-prototype/downloads/UE4SS_v3.0.1-1181-g83330635.zip"
EXPECTED = "b9a166a756605b21058a64cde93bcaab1a855dba3553e5c7e6ce0fa8fdfad7b9"


def main():
    if not ARCHIVE.exists():
        raise SystemExit("Fixed UE4SS archive missing: " + str(ARCHIVE) +
                         "\nSource: https://github.com/UE4SS-RE/RE-UE4SS/releases/download/experimental-latest/UE4SS_v3.0.1-1181-g83330635.zip")
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != EXPECTED:
        raise SystemExit("Fixed archive hash differs; no payload prepared.")
    payload = OUT / "payload"
    (OUT / "results").mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE) as z:
        for name in ("dwmapi.dll", "ue4ss/UE4SS.dll", "ue4ss/UE4SS-settings.ini", "ue4ss/LICENSE"):
            target = payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(name))
    scripts = payload / "ue4ss/Mods/NteObjectReadProbe/Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in ("main.lua", "reader.lua", "round.lua"):
        (scripts / name).write_bytes((Path(__file__).parent / "NteAuctionRead/Scripts" / name).read_bytes())
    (scripts / "config.lua").write_text("return {output_dir = " + json.dumps(OUT.as_posix()) + "}\n", encoding="utf-8")
    (payload / "ue4ss/Mods/mods.txt").write_text("NteObjectReadProbe : 1\n", encoding="utf-8")
    manifest = [{"path": p.relative_to(payload).as_posix(), "bytes": p.stat().st_size,
                 "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(payload.rglob("*")) if p.is_file()]
    (OUT / "payload-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Prepared fixed UE4SS payload under " + str(payload) + "; no game files touched.")


if __name__ == "__main__":
    main()
