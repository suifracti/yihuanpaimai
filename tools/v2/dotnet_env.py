"""Build helper: runs `dotnet build` with a fully populated Windows environment.

The shell in this sandbox lacks APPDATA / ProgramData / ProgramFiles, which makes
`dotnet build` fail with "Value cannot be null. (Parameter 'path1')" while it
resolves NuGet paths. bash `export` does not reach the child process reliably, so
the environment is populated here and passed explicitly.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])

DEFAULTS = {
    "APPDATA": r"C:\Users\Administrator\AppData\Roaming",
    "LOCALAPPDATA": r"C:\Users\Administrator\AppData\Local",
    "ProgramData": r"C:\ProgramData",
    "ALLUSERSPROFILE": r"C:\ProgramData",
    "ProgramFiles": r"C:\Program Files",
    "ProgramFiles(x86)": r"C:\Program Files (x86)",
    "USERPROFILE": r"C:\Users\Administrator",
    "HOMEDRIVE": "C:",
    "HOMEPATH": r"\Users\Administrator",
    "SystemRoot": r"C:\Windows",
    "windir": r"C:\Windows",
    "TEMP": r"C:\Users\Administrator\AppData\Local\Temp",
    "TMP": r"C:\Users\Administrator\AppData\Local\Temp",
    "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    "DOTNET_NOLOGO": "1",
    "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
}


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    for key, value in DEFAULTS.items():
        if not env.get(key):
            env[key] = value
    return env


def run_dotnet(args: list[str], cwd: str = REPO, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["dotnet", *args], cwd=cwd, env=build_env(),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


if __name__ == "__main__":
    result = run_dotnet(["build", sys.argv[1], "-c", "Release", "--nologo", "-v", "q"])
    print("exit:", result.returncode)
    print(result.stdout[-8000:])
    print("STDERR:", result.stderr[-6000:])
    sys.exit(result.returncode)
