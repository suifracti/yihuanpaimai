# Durable Runtime Data Authority + Fail-soft Main Status v1

Date: 2026-08-22 (Asia/Shanghai)

Initial HEAD: `57e1e19dd46613ab324b2b6a1377dd2e6bcab2fc`

Final HEAD: `SELF` — the independent commit containing this report

Tracked status at start: clean

Pre-existing untracked files: preserved and excluded from this cut

## 1. Old runtime history path map

| Owner/call site | Old behavior | Classification |
|---|---|---|
| `app/main.py::CANONICAL_DATABASE` | source preferred `app/异环拍卖数据.json` then repo root; frozen preferred executable-adjacent then `_internal` | unsafe production runtime authority |
| `MainViewStateProvider` construction | consumed the above path | production reader |
| Main Manual `DRAFT_ARCHIVER` | consumed the above path | production writer |
| vision worker settlement `AutoArchiver` | consumed the above path | production writer |
| `core/live_shadow.py::default_history_path` | repo/bundle root | production reader fallback |
| `core/live_capture.py` | repo root | standalone production writer |
| `CanonicalHistoryStore()` default | repo root | shared writer default |
| `AutoArchiver()` default | repo root | shared writer default |
| PyInstaller spec | copied repo history into package `_internal` | bundled file could become writable SOT |
| `core/live_shadow_runtime.js` | has a repo-relative CLI fallback | offline/dev fallback only; production Python always supplies `--records <runtime authority>` |
| `lab/`, `tools/`, `experiments/`, data audits | explicitly select/read repo datasets | offline/dev consumers; intentionally unchanged |

The root cause was not one bad line: runtime readers/writers and the package spec independently encoded the same filename against different base directories.

## 2. RuntimeDataRoot v1 contract

`core/runtime_data.py` is the single Python authority.

```text
%LOCALAPPDATA%/异环拍卖助手/data/
  history/异环拍卖数据.json
  state/history_migration_v1.json
  logs/
```

Contract properties:

- `resolve_runtime_data_root()` and `resolve_runtime_history_path()` do not inspect cwd, executable location, repo root, `_MEIPASS`, or TEMP.
- `YIHUAN_DATA_ROOT` is the sole explicit test/dependency-injection override.
- Missing `LOCALAPPDATA` or directory/permission failure returns `UNAVAILABLE`; there is no unsafe fallback.
- source and packaged runs resolve the same logical per-user path.
- mutable runtime history and upper-tail experiment capture sidecars remain separate authorities.
- the approved venue/box catalog remains a read-only application asset and is not copied into this writable root.

## 3. Source and package defaults

- Source default: `%LOCALAPPDATA%\异环拍卖助手\data\history\异环拍卖数据.json`
- Package default: `%LOCALAPPDATA%\异环拍卖助手\data\history\异环拍卖数据.json`
- Test override example: `YIHUAN_DATA_ROOT=<isolated-root>` produces `<isolated-root>\history\异环拍卖数据.json`.

Changing cwd, `sys._MEIPASS`, executable directory, or installation directory does not change the live authority.

## 4. Repository dataset classification

`D:\yihuanpaimai\异环拍卖数据.json` is frozen as:

`READ_ONLY_RESEARCH_DATASET`

At this cut it contains 290 records and 34,801,239 bytes. It remains available to explicitly configured offline experiments, audits, and lab workflows. Production runtime does not default-read it, seed from it, migrate it, or write it.

## 5. Bundled dataset policy

`BUNDLED_HISTORY_POLICY = NOT_BUNDLED`

The fresh PyInstaller spec no longer includes the repository history. No runtime/reference feature required the 34 MB file in the packaged product; source-only offline tools retain explicit access to the repository copy. Old package `_internal` files are handled only as conservative migration candidates.

## 6. First-run behavior

When the per-user authority does not exist:

1. create `history/`, `state/`, and `logs/`;
2. inspect only known legacy runtime locations;
3. reject unchanged bundled baselines and corrupt candidates;
4. if no safe user-data candidate exists, atomically install a versioned empty store;
5. report `EMPTY`, admitted count `0`, today `0`, with no error.

The development dataset is never copied to a new profile.

## 7. Legacy migration policy

Known candidates are deliberately narrow:

- frozen: executable-adjacent history and packaged `_internal` history;
- source: old `app/`-adjacent history;
- excluded unconditionally: repo root and cwd-derived paths.

Baseline discrimination uses the frozen pre-cut reference SHA-256:

`6a9695f8ef44058f2c369ac1bd1407a6306a327b63d1c0a160631d5348ed699a`

Policy:

- same baseline hash → `SKIPPED_BUNDLED_REFERENCE`;
- changed, readable, structurally valid single candidate → `LEGACY_USER_DATA_CANDIDATE`, copy-first migration;
- corrupt/unreadable candidate → rejected, old source untouched;
- multiple valid changed candidates without destination → `MIGRATION_REQUIRED`, fail closed;
- destination already exists → destination wins; changed legacy candidate is reported as `MIGRATION_CONFLICT`; no merge/overwrite.

Migration metadata records migration version, timezone-aware time, path classification, filename, source/destination SHA-256, and result. It does not expose an absolute machine path.

## 8. Atomic write semantics

History writes continue through the existing `CanonicalHistoryStore` transaction authority:

`process lock → re-read → validate transition → same-directory temp → UTF-8 JSON → flush → fsync → os.replace → re-read verification`

The cut additionally made malformed roots/record arrays fail closed rather than silently treating them as empty. A failed temp write or replacement leaves the prior valid file byte-identical. Repeated/concurrent DRAFT updates remain valid JSON and do not truncate the store.

## 9. History availability and safe reason codes

Presentation-visible states:

- `AVAILABLE`
- `EMPTY`
- `UNAVAILABLE`
- `CORRUPT`
- `MIGRATION_REQUIRED`
- `MIGRATION_CONFLICT`

Stable reason examples include `HISTORY_NOT_FOUND`, `HISTORY_PARSE_FAILED`, `HISTORY_SCHEMA_INVALID`, `HISTORY_PERMISSION_DENIED`, `HISTORY_READ_FAILED`, and `LEGACY_DATA_CONFLICT`.

The bridge never emits absolute paths, raw exception messages, or tracebacks. Internal logging may retain diagnostic detail.

## 10. Fail-soft app_status behavior

`MainViewStateProvider` now returns an immutable failure snapshot instead of throwing for missing, corrupt, invalid-schema, permission, stat, read, or unstable-read failures. Unchanged corrupt content is revision-cached so the 750 ms poll does not repeatedly parse it.

`MainWindowBridge` has a second fail-soft boundary: an unexpected provider exception or invalid provider result becomes `HISTORY_PROVIDER_FAILED` / `HISTORY_PROVIDER_INVALID`. The same `app_status` still returns:

- Overlay visibility/control state;
- presentation runtime state;
- mascot/Pet presentation state;
- product application state and `solverOwner=overlay_runtime`.

Main displays only minimal honest copy: history normal, history empty, temporarily unavailable/corrupt, or migration conflict/required. No History page or error center was added.

## 11. History admission authority

`History Admission Policy v1` is unchanged. Moving the file does not relax DRAFT, cancelled, diagnostic, duplicate, timestamp, settlement, or truth gates. `EMPTY` is a valid zero-record source, not an admission error.

## 12. Shadow and Solver boundary

- Production Shadow receives the same runtime history path explicitly.
- If runtime history is unavailable, the vision worker skips history load/warmup and retains the existing no-history/degraded path instead of crashing.
- Node Shadow production launches still receive `--records <runtime authority>`.
- No Solver, Shadow profile, weight, filtering, prior, or model formula changed.

## 13. Source smoke

Against the same isolated `YIHUAN_DATA_ROOT` used by the package:

- Main and Overlay started;
- Main presentation bridge initialized;
- source read the package-created one-record history;
- revision SHA, record count, admission summary, and availability matched package exactly;
- clean shutdown passed.

## 14. Fresh package smoke

Fresh PyInstaller 6.22.0 build passed. Isolated smoke sequence:

1. package first run created an empty per-user store;
2. `_internal/异环拍卖数据.json` was absent;
3. one real Manual DRAFT was sent through the existing WebSocket action;
4. DRAFT persisted under the isolated per-user root;
5. package closed cleanly;
6. package restarted and retained exactly one DRAFT;
7. source opened the same authority and produced the same presentation revision;
8. package directory file-count/content/mtime fingerprint was unchanged;
9. no process lingered.

Observed parity signature after DRAFT:

- `recordCount=1`
- `admittedCount=0`
- `excludedCount=1`
- availability `AVAILABLE`
- source/package history SHA-256 identical

## 15. Integrity hashes

Before and after this cut:

| Artifact | SHA-256 |
|---|---|
| repository research history | `6a9695f8ef44058f2c369ac1bd1407a6306a327b63d1c0a160631d5348ed699a` |
| `auction_engine_v06.js` | `8f31258f73b22ce978a61555ad6765e231305588f0b8239609ce8a8230f98862` |
| `solver_core_v06.js` | `1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f` |
| `shadow_profile_v06.js` | `9967f269f5c5b66dc8a010e3077ce014700c0b94333d93acf25a4021f9c886a5` |
| approved Alpha venue/box catalog | `321a0bd7851d30aaff40022621e4b4c0a1157a25873de28e50dcdaae7cbf01d3` |

All are unchanged.

## 16. Validation

Focused runtime/lifecycle suite: **74/74 PASS**.

Covered:

- source/package resolver parity and explicit override;
- cwd, `_MEIPASS`, executable-location independence;
- no unsafe fallback;
- first run and empty semantics;
- baseline discrimination;
- valid/corrupt/conflicting migration and idempotent second launch;
- migration failure preserving old source;
- atomic failure preserving current authority;
- concurrent/repeated DRAFT writes;
- missing/corrupt/permission/schema/read failures;
- sanitized bridge payload and retained Overlay/runtime/Pet status;
- Main lifecycle, Desktop Pet lifecycle, presentation runtime, Manual debounce/flush, and canonical transactional storage.

Full repository discovery run: 440 tests executed. It exposed pre-existing legacy/fixture debt outside this cut (old Schema-6 top-level archive assertions against current Canonical v7, old business-SOT/OCR fixtures, obsolete product version/wording assumptions, and an evaluation fixture count pinned to 289 while the immutable repository dataset contains 290). No Solver/OCR/fixture repair was included. The cut-specific and directly affected suites are green.

## 17. Files in this cut

- New: `core/runtime_data.py`
- New: `tests/test_runtime_data_authority.py`
- New: `tests/runtime_data_smoke.py`
- Modified: `app/main.py`, `app/main_view_state.py`, `app/main_window.py`, `app/config.json`, PyInstaller spec
- Modified: `core/auto_archiver.py`, `core/canonical_history_store.py`, `core/live_capture.py`, `core/live_shadow.py`, `core/main_window.js`
- Modified tests/docs: Main view-state tests, Manual import isolation, README, canonical source note

## 18. Final verdict

`DURABLE_DATA_AUTHORITY_READY`

Commit: `SELF` — resolve to the Git commit containing this report.

Cut 3 is not started.
