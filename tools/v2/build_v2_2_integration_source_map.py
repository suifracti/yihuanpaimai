# -*- coding: utf-8 -*-
"""Record accepted A/B/C import provenance and source hashes for I1."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


BASE = "a9b52c6fb8db3c5f7dbfb2e80cb5a32bb4a526e9"
HEADS = {
    "A": "934ce47e3dec223a8046dbca35452de8774f857c",
    "B": "b1334c6ac11a9873030ed67e7f6418b22f69ccc0",
    "C": "878435e96034caa130c622de0ab968162d65a595",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.as_posix(), "size": path.stat().st_size, "sha256": sha256(path)}


def bytes_record(path: str, data: bytes) -> dict[str, Any]:
    return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def git_blob(repo: Path, revision: str, relative: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{revision}:{relative}"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--a-repo", required=True)
    parser.add_argument("--b-repo", required=True)
    parser.add_argument("--c-repo", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    integration_head = git(repo, "rev-parse", "HEAD")
    source_repos = {
        "A": Path(args.a_repo).resolve(),
        "B": Path(args.b_repo).resolve(),
        "C": Path(args.c_repo).resolve(),
    }
    components: list[dict[str, Any]] = []
    missing: list[str] = []
    mismatches: list[str] = []

    for component, head in HEADS.items():
        source_repo = source_repos[component]
        changed = [
            line.replace("\\", "/")
            for line in git(source_repo, "diff", "--name-only", BASE, head).splitlines()
            if line.strip()
        ]
        files: list[dict[str, Any]] = []
        for relative in changed:
            source_path = source_repo / relative
            imported_path = repo / relative
            try:
                source_commit_data = git_blob(source_repo, head, relative)
                imported_commit_data = git_blob(repo, integration_head, relative)
            except subprocess.CalledProcessError:
                missing.append(f"{component}:{relative}")
                continue
            if not imported_path.exists():
                missing.append(f"{component}:{relative}")
                continue
            source_record = bytes_record(relative, source_commit_data)
            imported_record = bytes_record(relative, imported_commit_data)
            source_worktree_record = record(source_path) if source_path.exists() else None
            imported_worktree_record = record(imported_path)
            matches = (
                source_record["size"] == imported_record["size"]
                and source_record["sha256"] == imported_record["sha256"]
            )
            if not matches:
                mismatches.append(f"{component}:{relative}")
            files.append({
                "path": relative,
                "sourceHead": head,
                "sourceFile": source_record,
                "importedFile": imported_record,
                "sourceWorkingTreeFile": source_worktree_record,
                "importedWorkingTreeFile": imported_worktree_record,
                "matches": matches,
                "workingTreeMatches": (
                    source_worktree_record is not None
                    and source_worktree_record["size"] == imported_worktree_record["size"]
                    and source_worktree_record["sha256"] == imported_worktree_record["sha256"]
                ),
            })
        components.append({
            "component": component,
            "sourceRepository": str(source_repo),
            "sourceHead": head,
            "commonBase": BASE,
            "changedFileCount": len(changed),
            "files": files,
        })

    payload = {
        "schemaVersion": "v2.2.integration.i1.source-map.v1",
        "repository": str(repo),
        "branch": git(repo, "branch", "--show-current"),
        "integrationHead": integration_head,
        "commonBase": BASE,
        "components": components,
        "missingFiles": missing,
        "hashMismatches": mismatches,
        "allImportedFilesMatch": not missing and not mismatches,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "head": payload["integrationHead"],
        "files": sum(item["changedFileCount"] for item in components),
        "missing": len(missing),
        "mismatches": len(mismatches),
        "allImportedFilesMatch": payload["allImportedFilesMatch"],
    }, ensure_ascii=False))
    return 0 if payload["allImportedFilesMatch"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
