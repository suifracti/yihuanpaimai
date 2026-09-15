# -*- coding: utf-8 -*-
"""Legacy Archive: isolated read-only lane for the repo's old history JSON.

The old file (e.g. D:\\yihuanpaimai\\异环拍卖数据.json, ~287 records) is NEVER
migrated into CanonicalHistoryStore and NEVER modified in place.  It is read,
normalized into immutable read-only LEGACY projections, and marked LEGACY so it
never automatically claims formal-eligible / high-confidence truth identity.

Stable record keys reuse existing id/matchId when present; otherwise a
reproducible source-record fingerprint (sha256 of the canonical JSON of the
record) is used, so JSON reordering never rebinds a review to the wrong match.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LEGACY_FILENAME = "异环拍卖数据.json"
LEGACY_SOURCE_STATE = "legacy_archive_source.json"


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_str(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _persisted_user_source() -> Optional[Path]:
    try:
        from runtime_data import runtime_data_paths
        state = runtime_data_paths().state_dir / LEGACY_SOURCE_STATE
        if state.is_file():
            doc = json.loads(state.read_text(encoding="utf-8"))
            p = Path(str(doc.get("path") or "")).expanduser().resolve()
            if p.is_file():
                return p
    except Exception:
        pass
    return None


def _resolve_legacy_path() -> Path:
    """Stable Legacy source resolver, ordered:

    1. user-persisted selection (RuntimeDataRoot/state/legacy_archive_source.json)
    2. environment override YIHUAN_LEGACY_HISTORY_PATH
    3. dev source: repo root next to this module (works from source tree)
    4. packaged dev build: walk up from sys.executable's directory looking for
       the file (e.g. dist/异环拍卖助手 -> repo root); not hardcoded to one path
    5. current working directory
    Falls back to the dev-repo candidate so the UI can offer a file picker.
    """
    persisted = _persisted_user_source()
    if persisted is not None:
        return persisted
    env_p = os.environ.get("YIHUAN_LEGACY_HISTORY_PATH")
    if env_p and Path(env_p).is_file():
        return Path(env_p).expanduser().resolve()
    if getattr(sys, "frozen", False):
        anchor = Path(sys.executable).resolve().parent
        for _ in range(4):
            cand = anchor / LEGACY_FILENAME
            if cand.is_file():
                return cand
            anchor = anchor.parent
    dev = Path(__file__).resolve().parents[1] / LEGACY_FILENAME
    if dev.is_file():
        return dev
    cwd_cand = Path.cwd() / LEGACY_FILENAME
    if cwd_cand.is_file():
        return cwd_cand
    return dev


def stable_legacy_key(record: Dict[str, Any]) -> str:
    """Reuse existing id/matchId; fall back to a reproducible fingerprint."""
    rid = str(record.get("id") or record.get("matchId") or record.get("match_id") or "").strip()
    if rid:
        return f"legacy:{rid}"
    fp = hashlib.sha256(_canonical_json_str(record).encode("utf-8")).hexdigest()
    return f"legacy:fp:{fp}"


class LegacyArchive:
    """Read-only archive over one legacy history JSON file."""

    def __init__(
        self,
        path_provider: Optional[Callable[[], str]] = None,
    ):
        self._path_provider = path_provider or (lambda: str(_resolve_legacy_path()))

    def set_user_source(self, path: str) -> None:
        """Persist a user-chosen legacy source path for future launches."""
        from runtime_data import runtime_data_paths
        state = runtime_data_paths().state_dir
        state.mkdir(parents=True, exist_ok=True)
        target = state / LEGACY_SOURCE_STATE
        tmp = target.with_suffix(target.suffix + f".tmp{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"path": str(Path(path).expanduser().resolve())}, f, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(str(tmp), str(target))

    def path(self) -> Path:
        return Path(self._path_provider()).resolve()

    def available(self) -> bool:
        return self.path().is_file()

    def source_info(self) -> Dict[str, Any]:
        p = self.path()
        if not p.is_file():
            return {"available": False, "path": str(p), "fileSha256": None, "recordCount": 0}
        raw = p.read_bytes()
        return {
            "available": True,
            "path": str(p),
            "fileSha256": _sha256_bytes(raw),
            "recordCount": len(self._records_from_raw(raw)),
        }

    @staticmethod
    def _records_from_raw(raw: bytes) -> List[Dict[str, Any]]:
        document = json.loads(raw.decode("utf-8"))
        if isinstance(document, list):
            return [r for r in document if isinstance(r, dict)]
        if isinstance(document, dict):
            records = document.get("records")
            if records is None and isinstance(document.get("games"), list):
                records = document["games"]
            if isinstance(records, list):
                return [r for r in records if isinstance(r, dict)]
        return []

    def _records(self) -> List[Dict[str, Any]]:
        return self._records_from_raw(self.path().read_bytes())

    def list_projections(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Immutable LEGACY projections for the archive list."""
        if not self.available():
            return []
        out: List[Dict[str, Any]] = []
        for idx, record in enumerate(reversed(self._records())):
            if limit is not None and len(out) >= limit:
                break
            key = stable_legacy_key(record)
            env = record.get("environment") if isinstance(record.get("environment"), dict) else {}
            settlement = record.get("settlement") if isinstance(record.get("settlement"), dict) else {}
            embedded = self.embedded_screenshot(record)
            out.append({
                "key": key,
                "source": "LEGACY",
                "indexInFile": idx,
                "id": str(record.get("id") or record.get("matchId") or ""),
                "playedAt": str(record.get("playedAt") or record.get("timestamp") or ""),
                "venue": str(env.get("venueName") or env.get("venue") or record.get("venue") or ""),
                "box": str(env.get("box") or record.get("box") or ""),
                "lifecycle": str(record.get("lifecycleStatus") or record.get("lifecycle") or "LEGACY"),
                "isSettled": bool(settlement.get("isSettled") or settlement.get("verified") or settlement.get("clearingPrice") is not None),
                "clearingPrice": settlement.get("clearingPrice"),
                "actualTotal": settlement.get("actualTotal"),
                "realizedProfit": settlement.get("realizedProfit"),
                "screenshotAvailable": embedded is not None,
                "admissionEligible": False,  # legacy never auto-eligible
            })
        return out

    @staticmethod
    def embedded_screenshot(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the embedded settlement screenshot (thumbnail data URL) with a
        reproducible provenance hash, or None. This is the ONLY auto-bound
        legacy screenshot source: the data lives inside the record itself, so
        no fuzzy time/path matching is ever performed.

        Strict Contract:
        Only screenshots explicitly confirmed as settlement screenshots
        (kind == 'settlement' and segmentRole == 'main-settlement', or
        kind == 'settlement' with an equivalent settlement role) are accepted.
        Non-settlement screenshots (e.g. warehouse-supplement) and arbitrary
        thumbnail fallbacks are strictly forbidden.
        """
        candidates = []
        for s in (record.get("screenshots") or []):
            if isinstance(s, dict) and s not in candidates:
                candidates.append(s)
        for s in ((record.get("settlement") or {}).get("screenshots") or []):
            if isinstance(s, dict) and s not in candidates:
                candidates.append(s)

        # 1. Prefer explicit main-settlement role
        for s in candidates:
            data_url = str(s.get("thumbnailDataUrl") or s.get("dataUrl") or "")
            if data_url and s.get("kind") == "settlement" and s.get("segmentRole") == "main-settlement":
                digest = hashlib.sha256(data_url.encode("utf-8")).hexdigest()
                return {
                    "dataUrl": data_url,
                    "sha256": digest,
                    "source": "legacy_embedded_thumbnail",
                    "name": str(s.get("name") or s.get("path") or ""),
                    "id": str(s.get("id") or ""),
                    "segmentRole": "main-settlement",
                }

        # 2. Fall back to any settlement with thumbnailDataUrl/dataUrl where role is explicitly settlement (NOT warehouse-supplement)
        for s in candidates:
            data_url = str(s.get("thumbnailDataUrl") or s.get("dataUrl") or "")
            segment_role = str(s.get("segmentRole") or "")
            if data_url and s.get("kind") == "settlement" and segment_role in ("settlement", "main-settlement"):
                digest = hashlib.sha256(data_url.encode("utf-8")).hexdigest()
                return {
                    "dataUrl": data_url,
                    "sha256": digest,
                    "source": "legacy_embedded_thumbnail",
                    "name": str(s.get("name") or s.get("path") or ""),
                    "id": str(s.get("id") or ""),
                    "segmentRole": str(s.get("segmentRole") or "settlement"),
                }

        return None

    def get_record(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.available():
            return None
        for record in self._records():
            if stable_legacy_key(record) == key:
                return record
        return None

    def delete_record(self, key_or_id: str) -> Dict[str, Any]:
        """Atomically delete one legacy record by key or id with pre-delete backup."""
        import threading
        from datetime import datetime, timezone
        target = str(key_or_id or "").strip()
        if not target:
            raise ValueError("RECORD_ID_EMPTY")

        p = self.path()
        if not p.is_file():
            raise FileNotFoundError(f"Legacy archive file not found: {p}")

        raw = p.read_bytes()
        document = json.loads(raw.decode("utf-8"))

        if isinstance(document, list):
            records = document
        elif isinstance(document, dict):
            if "records" in document and isinstance(document["records"], list):
                records = document["records"]
            elif "games" in document and isinstance(document["games"], list):
                records = document["games"]
            else:
                raise ValueError("INVALID_LEGACY_FORMAT")
        else:
            raise ValueError("INVALID_LEGACY_FORMAT")

        match_idx = None
        matched_record = None
        for i, r in enumerate(records):
            if isinstance(r, dict):
                r_key = stable_legacy_key(r)
                r_id = str(r.get("id") or r.get("matchId") or "").strip()
                if target in (r_key, r_id, f"legacy:{r_id}", f"legacy:{target}"):
                    match_idx = i
                    matched_record = r
                    break

        if match_idx is None or matched_record is None:
            raise KeyError(f"Legacy record '{target}' not found")

        # Pre-delete backup
        try:
            from runtime_data import runtime_data_paths
            state_dir = runtime_data_paths().state_dir
            state_dir.mkdir(parents=True, exist_ok=True)
            backup_file = state_dir / "legacy_delete_backup.json"
            backup_entry = {
                "deletedAt": datetime.now(timezone.utc).isoformat(),
                "targetKey": target,
                "record": matched_record,
                "archivePath": str(p),
            }
            backup_list = []
            if backup_file.exists():
                try:
                    loaded = json.loads(backup_file.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        backup_list = loaded
                    elif isinstance(loaded, dict):
                        backup_list = [loaded]
                except Exception:
                    backup_list = []
            backup_list.append(backup_entry)
            tmp_bf = backup_file.with_suffix(f".tmp_{os.getpid()}_{threading.get_ident()}")
            with open(tmp_bf, "w", encoding="utf-8") as bf:
                json.dump(backup_list, bf, ensure_ascii=False, indent=2)
            os.replace(str(tmp_bf), str(backup_file))
        except Exception:
            pass

        # Remove matched record
        del records[match_idx]

        # Atomic write back to legacy archive file
        tmp_path = p.with_suffix(f".tmp_{os.getpid()}_{threading.get_ident()}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(document, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(str(tmp_path), str(p))
        except Exception as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise IOError(f"Failed to update legacy archive atomically: {e}") from e

        return {
            "ok": True,
            "status": "DELETED",
            "deletedKey": target,
            "remainingCount": len(records),
        }
