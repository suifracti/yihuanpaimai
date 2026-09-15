# -*- coding: utf-8 -*-
"""Runtime code revision authority.

Provides dynamic git / package / dev codeRevision resolution so solver provenance
is never hardcoded to a stale commit hash.

Authority rules:
1. Environment variable override (NTE_CODE_REVISION / GIT_COMMIT) has highest precedence
   (useful for tests and containerized deployments).
2. Frozen package mode (sys.frozen == True):
   - MUST read from immutable build metadata (build_info.json) bundled during build.
   - MUST NOT execute runtime git rev-parse (prevents stale/future repo HEAD contamination).
   - If build_info.json is missing or unparseable, falls back to "frozen-unversioned".
3. Source / Dev mode (sys.frozen == False):
   - First checks build_info.json in PROJECT_ROOT if present.
   - Executes dynamic git repository inspection (git rev-parse HEAD + git status --porcelain).
   - If working tree is dirty, appends "-dirty" (e.g. "<commit>-dirty").
   - If git is not available or not a git repository, falls back to "dev-unversioned".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_CACHED_REVISION: Optional[str] = None


def _find_build_info_file() -> Optional[Path]:
    """Find build_info.json according to current runtime environment."""
    if getattr(sys, "frozen", False):
        # 1. sys._MEIPASS (PyInstaller bundle root / _internal)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / "build_info.json"
            if p.is_file():
                return p
        # 2. EXE directory
        exe_dir = Path(sys.executable).resolve().parent
        p = exe_dir / "build_info.json"
        if p.is_file():
            return p
        # 3. _internal directory relative to EXE
        p = exe_dir / "_internal" / "build_info.json"
        if p.is_file():
            return p
        return None

    # Source mode
    project_root = Path(__file__).resolve().parents[1]
    p = project_root / "build_info.json"
    if p.is_file():
        return p
    app_dir = project_root / "app" / "build_info.json"
    if app_dir.is_file():
        return app_dir
    return None


def get_build_info() -> Optional[Dict[str, Any]]:
    """Return the parsed build metadata dictionary if available."""
    p = _find_build_info_file()
    if p is not None:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def get_code_revision(force_refresh: bool = False) -> str:
    """Return the authoritative code revision string for prediction provenance."""
    global _CACHED_REVISION
    if _CACHED_REVISION is not None and not force_refresh:
        return _CACHED_REVISION

    # 1. Environment variable override
    env_rev = os.environ.get("NTE_CODE_REVISION") or os.environ.get("GIT_COMMIT")
    if env_rev and env_rev.strip():
        _CACHED_REVISION = env_rev.strip()
        return _CACHED_REVISION

    # 2. Frozen packaged runtime
    if getattr(sys, "frozen", False):
        info = get_build_info()
        if info:
            rev = info.get("codeRevision") or info.get("commit") or info.get("revision")
            if rev and str(rev).strip():
                _CACHED_REVISION = str(rev).strip()
                return _CACHED_REVISION
        # Frozen builds MUST NEVER run git rev-parse against live workspace
        _CACHED_REVISION = "frozen-unversioned"
        return _CACHED_REVISION

    # 3. Source / Dev mode: live git repository has primary authority
    project_root = Path(__file__).resolve().parents[1]
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if proc.returncode == 0:
            commit = proc.stdout.strip()
            if commit:
                status_proc = subprocess.run(
                    ["git", "status", "--porcelain", "--untracked-files=no"],
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                dirty = bool(status_proc.stdout.strip())
                _CACHED_REVISION = f"{commit}-dirty" if dirty else commit
                return _CACHED_REVISION
    except Exception:
        pass

    # 4. Source archive fallback (e.g. tarball/zip without .git)
    info = get_build_info()
    if info:
        rev = info.get("codeRevision") or info.get("commit") or info.get("revision")
        if rev and str(rev).strip():
            _CACHED_REVISION = str(rev).strip()
            return _CACHED_REVISION

    _CACHED_REVISION = "dev-unversioned"
    return _CACHED_REVISION
