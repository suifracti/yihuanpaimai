"""Durable per-user runtime data authority for mutable product data.

Repository datasets and packaged application assets are deliberately outside
this authority.  Production callers must use these resolvers instead of the
working directory, executable directory, or PyInstaller ``_MEIPASS``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple, Union


RUNTIME_DATA_CONTRACT_VERSION = 1
MIGRATION_VERSION = 1
DATA_ROOT_OVERRIDE_ENV = "YIHUAN_DATA_ROOT"
APP_DIRECTORY_NAME = "异环拍卖助手"
TRIAL_DIRECTORY_NAME = "异环拍卖助手试用"
HISTORY_FILENAME = "异环拍卖数据.json"
EMPTY_HISTORY_DOCUMENT = {
    "version": "v0.67-runtime",
    "schemaVersion": 6,
    "records": [],
}

# The development/reference dataset bundled by pre-v1 packages at the cut's
# initial checkpoint.  Equality means "installation baseline", not user data.
KNOWN_BUNDLED_REFERENCE_SHA256 = frozenset(
    {"6a9695f8ef44058f2c369ac1bd1407a6306a327b63d1c0a160631d5348ed699a"}
)

_INITIALIZE_LOCK = threading.RLock()


class RuntimeDataUnavailable(RuntimeError):
    """The durable user data root cannot be resolved or initialized."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RuntimeDataPaths:
    root: Path
    history_dir: Path
    state_dir: Path
    logs_dir: Path
    history_path: Path
    migration_metadata_path: Path


@dataclass(frozen=True)
class LegacyHistoryCandidate:
    path: Path
    classification: str


@dataclass(frozen=True)
class MigrationDecision:
    result: str
    source_classification: Optional[str] = None
    source_sha256: Optional[str] = None
    destination_sha256: Optional[str] = None


@dataclass(frozen=True)
class RuntimeDataInitialization:
    available: bool
    availability: str
    reason: Optional[str]
    paths: Optional[RuntimeDataPaths]
    migration: MigrationDecision


def resolve_build_trial_marker(
    output_dir: Union[str, Path],
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Determine whether to emit isolated_trial.json during build.

    Normal spec builds default to production:
    - If NTE_BUILD_ISOLATED_TRIAL is not explicitly set to '1', no marker is generated
      and any stale marker in output_dir is removed. Returns None.
    - Only explicit NTE_BUILD_ISOLATED_TRIAL=1 triggers isolated trial marker generation
      with profile='isolated-trial-v1'. Returns the Path to the generated marker.
    """
    env_dict = os.environ if env is None else env
    out_path = Path(output_dir)
    marker_path = out_path / "isolated_trial.json"
    if str(env_dict.get("NTE_BUILD_ISOLATED_TRIAL", "")).strip() == "1":
        payload = {
            "profile": "isolated-trial-v1",
            "codeRevision": str(env_dict.get("NTE_BUILD_REVISION") or ""),
            "builtAt": datetime.now(timezone.utc).isoformat(),
        }
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return marker_path
    else:
        if marker_path.exists():
            try:
                marker_path.unlink()
            except OSError:
                pass
        return None


def is_isolated_trial() -> bool:
    if not getattr(sys, 'frozen', False):
        return False
    candidates = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(Path(meipass) / 'isolated_trial.json')
    exe_dir = Path(sys.executable).parent
    candidates.append(exe_dir / '_internal' / 'isolated_trial.json')
    candidates.append(exe_dir / 'isolated_trial.json')
    marker = next((c for c in candidates if c.exists()), None)
    if not marker:
        return False
    try:
        data = json.loads(marker.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('profile') != 'isolated-trial-v1':
            raise ValueError('Unknown trial profile')
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeDataUnavailable('TRIAL_PROFILE_INVALID') from exc
    return True


def resolve_runtime_data_root(env: Optional[dict] = None) -> Path:
    """Resolve the sole mutable product root without unsafe fallbacks."""
    values = os.environ if env is None else env
    override = str(values.get(DATA_ROOT_OVERRIDE_ENV) or "").strip()
    if override:
        return Path(override).expanduser().resolve()

    local_app_data = str(values.get("LOCALAPPDATA") or "").strip()
    if not local_app_data:
        raise RuntimeDataUnavailable("LOCALAPPDATA_UNAVAILABLE")
    directory = TRIAL_DIRECTORY_NAME if is_isolated_trial() else APP_DIRECTORY_NAME
    return (Path(local_app_data) / directory / "data").resolve()


def runtime_data_paths(env: Optional[dict] = None) -> RuntimeDataPaths:
    root = resolve_runtime_data_root(env)
    history_dir = root / "history"
    state_dir = root / "state"
    return RuntimeDataPaths(
        root=root,
        history_dir=history_dir,
        state_dir=state_dir,
        logs_dir=root / "logs",
        history_path=history_dir / HISTORY_FILENAME,
        migration_metadata_path=state_dir / "history_migration_v1.json",
    )


def resolve_runtime_history_path(env: Optional[dict] = None) -> Path:
    return runtime_data_paths(env).history_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_history_bytes(path: Path) -> bytes:
    raw_bytes = path.read_bytes()
    document = json.loads(raw_bytes.decode("utf-8"))
    if isinstance(document, list):
        records = document
    elif isinstance(document, dict):
        records = document.get("records")
        if records is None and isinstance(document.get("games"), list):
            records = document["games"]
    else:
        raise ValueError("history root must be an object or array")
    if not isinstance(records, list):
        raise ValueError("history records must be an array")
    return raw_bytes


def _atomic_write_bytes(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{threading.get_ident()}"
    )
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(destination))
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def _atomic_write_json(destination: Path, payload: dict) -> None:
    serialized = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    _atomic_write_bytes(destination, serialized)


def _migration_payload(
    decision: MigrationDecision,
    source_path: Optional[Path],
) -> dict:
    return {
        "migrationVersion": MIGRATION_VERSION,
        "migratedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sourcePathClassification": decision.source_classification,
        # Do not persist the machine-specific absolute source path.
        "sourceFileName": source_path.name if source_path is not None else None,
        "sourceSha256": decision.source_sha256,
        "destinationSha256": decision.destination_sha256,
        "result": decision.result,
    }


def discover_legacy_history_candidates(
    *,
    executable_dir: os.PathLike[str] | str,
    bundle_dir: os.PathLike[str] | str,
    frozen: bool,
) -> Tuple[LegacyHistoryCandidate, ...]:
    """Return only historically known runtime locations.

    The repository root and current working directory are intentionally never
    discovered.  Source mode only considers the old app-adjacent location.
    """
    executable_dir = Path(executable_dir).resolve()
    bundle_dir = Path(bundle_dir).resolve()
    candidates = []
    if frozen:
        candidates.extend(
            (
                LegacyHistoryCandidate(
                    executable_dir / HISTORY_FILENAME,
                    "LEGACY_EXECUTABLE_ADJACENT",
                ),
                LegacyHistoryCandidate(
                    bundle_dir / HISTORY_FILENAME,
                    "LEGACY_PACKAGED_INTERNAL",
                ),
            )
        )
    else:
        candidates.append(
            LegacyHistoryCandidate(
                executable_dir / HISTORY_FILENAME,
                "LEGACY_SOURCE_APP_ADJACENT",
            )
        )
    deduplicated = {}
    for candidate in candidates:
        deduplicated[str(candidate.path).casefold()] = candidate
    return tuple(deduplicated.values())


def _classify_candidates(
    candidates: Iterable[LegacyHistoryCandidate],
) -> tuple[list[tuple[LegacyHistoryCandidate, bytes, str]], list[MigrationDecision]]:
    user_candidates = []
    rejected = []
    for candidate in candidates:
        if not candidate.path.is_file():
            continue
        try:
            digest = _sha256(candidate.path)
        except OSError:
            rejected.append(
                MigrationDecision(
                    "REJECTED_UNREADABLE", candidate.classification
                )
            )
            continue
        if digest in KNOWN_BUNDLED_REFERENCE_SHA256:
            rejected.append(
                MigrationDecision(
                    "SKIPPED_BUNDLED_REFERENCE",
                    candidate.classification,
                    digest,
                )
            )
            continue
        try:
            payload = _validated_history_bytes(candidate.path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            rejected.append(
                MigrationDecision(
                    "REJECTED_CORRUPT", candidate.classification, digest
                )
            )
            continue
        user_candidates.append((candidate, payload, digest))
    return user_candidates, rejected


def initialize_runtime_data(
    *,
    env: Optional[dict] = None,
    legacy_candidates: Iterable[LegacyHistoryCandidate] = (),
) -> RuntimeDataInitialization:
    """Initialize directories, conservatively migrate, or create an empty store."""
    with _INITIALIZE_LOCK:
        legacy_candidates = tuple(legacy_candidates)
        try:
            paths = runtime_data_paths(env)
            if is_isolated_trial():
                # A trial begins with its own records; never imports daily history.
                legacy_candidates = ()
            for directory in (
                paths.root,
                paths.history_dir,
                paths.state_dir,
                paths.logs_dir,
            ):
                directory.mkdir(parents=True, exist_ok=True)
        except (RuntimeDataUnavailable, OSError) as exc:
            reason = (
                exc.reason
                if isinstance(exc, RuntimeDataUnavailable)
                else "DATA_ROOT_CREATE_FAILED"
            )
            return RuntimeDataInitialization(
                False,
                "UNAVAILABLE",
                reason,
                None,
                MigrationDecision("NOT_ATTEMPTED"),
            )

        user_candidates, rejected = _classify_candidates(legacy_candidates)

        if paths.history_path.exists():
            try:
                existing_bytes = _validated_history_bytes(paths.history_path)
                existing_sha = hashlib.sha256(existing_bytes).hexdigest()
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                return RuntimeDataInitialization(
                    False,
                    "CORRUPT",
                    "HISTORY_PARSE_FAILED",
                    paths,
                    MigrationDecision("DESTINATION_CORRUPT"),
                )
            if user_candidates:
                candidate, _, digest = user_candidates[0]
                decision = MigrationDecision(
                    "LEGACY_DATA_CONFLICT",
                    candidate.classification,
                    digest,
                    existing_sha,
                )
                try:
                    _atomic_write_json(
                        paths.migration_metadata_path,
                        _migration_payload(decision, candidate.path),
                    )
                except OSError:
                    pass
                return RuntimeDataInitialization(
                    True,
                    "MIGRATION_CONFLICT",
                    "LEGACY_DATA_CONFLICT",
                    paths,
                    decision,
                )
            document = json.loads(existing_bytes.decode("utf-8"))
            records = document if isinstance(document, list) else document.get("records", [])
            return RuntimeDataInitialization(
                True,
                "EMPTY" if not records else "AVAILABLE",
                None,
                paths,
                MigrationDecision("NOT_REQUIRED", destination_sha256=existing_sha),
            )

        if len(user_candidates) > 1:
            decision = MigrationDecision("MULTIPLE_LEGACY_USER_DATA_CANDIDATES")
            try:
                _atomic_write_json(
                    paths.migration_metadata_path,
                    _migration_payload(decision, None),
                )
            except OSError:
                pass
            return RuntimeDataInitialization(
                False,
                "MIGRATION_REQUIRED",
                "MULTIPLE_LEGACY_USER_DATA_CANDIDATES",
                paths,
                decision,
            )

        if len(user_candidates) == 1:
            candidate, payload, digest = user_candidates[0]
            try:
                _atomic_write_bytes(paths.history_path, payload)
                installed = _validated_history_bytes(paths.history_path)
                destination_sha = hashlib.sha256(installed).hexdigest()
                if destination_sha != digest:
                    raise OSError("migrated history hash mismatch")
                decision = MigrationDecision(
                    "MIGRATED",
                    candidate.classification,
                    digest,
                    destination_sha,
                )
                _atomic_write_json(
                    paths.migration_metadata_path,
                    _migration_payload(decision, candidate.path),
                )
                document = json.loads(installed.decode("utf-8"))
                records = document if isinstance(document, list) else document.get("records", [])
                return RuntimeDataInitialization(
                    True,
                    "EMPTY" if not records else "AVAILABLE",
                    None,
                    paths,
                    decision,
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                failed = MigrationDecision(
                    "MIGRATION_FAILED",
                    candidate.classification,
                    digest,
                )
                try:
                    _atomic_write_json(
                        paths.migration_metadata_path,
                        _migration_payload(failed, candidate.path),
                    )
                except OSError:
                    pass
                return RuntimeDataInitialization(
                    False,
                    "UNAVAILABLE",
                    "HISTORY_MIGRATION_WRITE_FAILED",
                    paths,
                    failed,
                )

        try:
            _atomic_write_json(paths.history_path, EMPTY_HISTORY_DOCUMENT)
            installed = _validated_history_bytes(paths.history_path)
            destination_sha = hashlib.sha256(installed).hexdigest()
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return RuntimeDataInitialization(
                False,
                "UNAVAILABLE",
                "EMPTY_HISTORY_CREATE_FAILED",
                paths,
                MigrationDecision("FIRST_RUN_CREATE_FAILED"),
            )
        decision = MigrationDecision(
            "EMPTY_STORE_CREATED",
            destination_sha256=destination_sha,
        )
        # Rejected baselines/corrupt candidates remain observable without
        # preventing a clean first run.  No source file is ever changed.
        if rejected:
            decision = MigrationDecision(
                rejected[0].result,
                rejected[0].source_classification,
                rejected[0].source_sha256,
                destination_sha,
            )
            try:
                source = next(
                    (
                        candidate.path
                        for candidate in legacy_candidates
                        if candidate.classification == decision.source_classification
                    ),
                    None,
                )
                _atomic_write_json(
                    paths.migration_metadata_path,
                    _migration_payload(decision, source),
                )
            except OSError:
                pass
        return RuntimeDataInitialization(
            True,
            "EMPTY",
            None,
            paths,
            decision,
        )
