# Venue / Box Catalog Contract v1 — Evidence, Authority and Migration Report

Audit date: 2026-08-22 (Asia/Shanghai)

Initial HEAD: `6dc9c9d20c9154df59e4daecb6681b5b8a3a2b14`

Scope: venue / tier / box / effect / entry-cost truth only
Verdict: **`NEEDS_CURRENT_GAME_EVIDENCE`**

## Executive decision

**FACT** — The repository does not contain a complete, versioned, provenance-complete current-game capture that proves the current selectable venue set and each venue's box options/effects. It contains two useful old full frames (`海贝场`, `珊瑚场`), two derived venue crops, four old external-stream box screenshots, and multiple code/design-derived lists.

**FACT** — `顶级场`, `密林`, `白夜`, `海沫`, `纸箱`, `铁皮箱`, and `金库保险箱` have no current-game authority in the audited repository. This does not prove that they do not exist in the game.

**FACT** — The existing production UI, business SOT, Vision observations, adapters, Solver compatibility keys, and history contain incompatible namespaces. Existing constants cannot be used as evidence for themselves.

**RECOMMENDATION** — Do not switch production Manual UI or Solver context yet. The schemas, validator, consumer boundary, and read-only legacy classifier in this cut make a future approved catalog fail-closed, but no production catalog instance is fabricated.

## 1. Evidence hierarchy and contract

### 1.1 Accepted hierarchy

| Rank | Evidence | Eligible for current game truth? |
|---|---|---:|
| A | Complete current-version game UI screenshot/video with build, timestamp, hash and review | Yes |
| B | Same-version, context-complete, hashable human session evidence | Yes |
| C | Saved old game capture with complete provenance | Legacy only unless build is shown current |
| D | Design docs, adapter enums, UI hardcodes, Solver constants, history frequency, external naming | No |

**FACT** — `docs/contracts/venue-box-catalog-evidence-v1.schema.json` freezes `VenueBoxCatalogEvidence v1`. Every formal evidence record requires game build, timezone-aware capture time, source path/hash, reviewer/status/classification, and one or more raw game-text claims.

**FACT** — `core/venue_box_catalog.py::validate_evidence` verifies source containment, file existence, SHA-256, timezone awareness, claims, and the stricter current-evidence gate. `CURRENT_GAME_VALID` requires approved review and a current full-UI/session evidence type.

**INFERENCE** — Local captures missing build/time/reviewer remain valuable audit inventory, but cannot safely be upgraded to formal current-game evidence after the fact.

## 2. Existing evidence inventory

The machine-readable inventory is `assets/venue_box_catalog_v1/evidence_inventory_v1.json`.

| Source | Hash prefix | Classification | What it supports | Why it cannot freeze current truth |
|---|---|---|---|---|
| `assets/ocr_study_frames/live_lobby2/t0022.jpg` | `0dd68d0dca57` | `LEGACY_GAME_EVIDENCE` | Game-like full frame visibly says `当前：海贝场` | No build/time/reviewer; not a complete option set |
| `assets/ocr_study_frames/live_lobby2/t0048.jpg` | `0ba60e71bad2` | `LEGACY_GAME_EVIDENCE` | Game-like full frame visibly says `当前：珊瑚场` | Same gaps |
| `assets/lobby_venues/海贝场.png` | `b934a342d705` | `DERIVED_ONLY` | Derived recognition crop | Full context/provenance removed |
| `assets/lobby_venues/珊瑚场.png` | `f45beaf4a089` | `DERIVED_ONLY` | Derived recognition crop | Full context/provenance removed |
| Four `我自己截图的一些资料/高级场箱子/*.png` files | `1f7a…`, `09e9…`, `8e03…`, `ed7e…` | `LEGACY_GAME_EVIDENCE` | Insurance-box names/effect text visible | Build and exact venue membership absent |
| `assets/business_sot_v06.json` | `a0a580e01c05` | `DERIVED_ONLY` | Repository's three-venue and box tables | Its declared source is `lab/index.html`, not game evidence |
| `docs/contracts/canonical-match-record-v7.md` | `844814fae649` | `DESIGN_ONLY` | Four-tier schema design | Design is not game authority |
| `craft/异环拍卖助手｜项目总文档.md` | `92016262281f` | `DERIVED_ONLY` | Reviewed text mentions `海贝场 + 浸水的包裹` | Referenced media and current-build provenance absent |
| `app/main.py` / `core/overlay_alpha.html` | `fe83…` / `b66a…` | `DERIVED_ONLY` | Current Manual hardcodes | Consumer code cannot prove its own truth |

No inventoried item meets `CURRENT_GAME_VALID`.

## 3. Venue-family provenance

| Family | Earliest/relevant repository provenance | Classification | Current-game fact status |
|---|---|---|---|
| `海贝场` / `haibei` | Old full frame; derived template; business SOT/Vision alias | Legacy observation plus derived mappings | Exact name is historically observed; current selectable status, tier and cost unverified |
| `珊瑚场` / `shanhu` | Old full frame; derived template; business SOT/Vision alias; adapter | Legacy observation plus derived mappings | Exact name is historically observed; current selectable status, tier and cost unverified |
| `真珠场` / `zhenzhu` | Business SOT and Vision fallback/design data | `DERIVED_ONLY` | Unverified |
| `密林` / `milin` | v06 adapter enum/design chain | `DESIGN_ONLY` / `DERIVED_ONLY` | Unverified |
| `白夜` / `baiye` | v06 adapter enum/design chain | `DESIGN_ONLY` / `DERIVED_ONLY` | Unverified |
| `海沫` / `haimo` | v06 adapter enum/design chain | `DESIGN_ONLY` / `DERIVED_ONLY` | Unverified |
| `初级/中级/高级/顶级` | business/design tables and Manual hardcodes | `DESIGN_ONLY` / `DERIVED_ONLY` | Game-native tier concept itself is unverified; `顶级场` is neither accepted nor deleted |

**FACT** — The old venue templates' manifest assigns `海贝=0` and `珊瑚=5000`; business SOT assigns `真珠=20000`. None of those costs has current, direct game evidence in the repo.

## 4. Box-family provenance

| Family | Repository source | Classification | Unresolved boundary |
|---|---|---|---|
| `破损/完整/浸水/无名包裹` | business SOT/lab aliases; derived session note for `浸水` | Mostly `DERIVED_ONLY` | Exact current names, raw effects, membership, option completeness |
| `琉璃/实木/螺钿/机械/美食/皮制/黑铁宝箱` | business SOT and Manual hardcodes/history | `DERIVED_ONLY` | Exact current names/effects and venue membership |
| `完整/璀璨/古典/精工/奇趣/锈蚀保险箱` | Four old external-stream screenshots, then business SOT | `LEGACY_GAME_EVIDENCE` for visible text | Current build, exact venue membership, complete set |
| `纸箱/铁皮箱/金库保险箱` | Manual UI hardcode | `DERIVED_ONLY` | No game evidence found |
| generic `standard` / unknown strings | Legacy history/runtime defaults | `UNVERIFIED` semantics | No exact catalog identity |

**FACT** — A visible effect string is preserved as raw evidence only. It does not prove a normalized color/quality semantic. For example, `低级藏品概率提升` cannot be silently normalized to `紫色提升`.

## 5. Catalog contract

`docs/contracts/venue-box-catalog-v1.schema.json` defines:

- catalog: `schemaVersion`, `catalogVersion`, `catalogStatus`, `gameBuild`, `generatedAt`, `evidenceBundleSha256`, `venues[]`, `compatibilityTranslations[]`;
- venue: opaque `venueId`, exact `displayName`, `selectable`, evidence-bound nullable `tier`, evidence-bound nullable `entryCost`, `evidenceRefs`, explicit observation aliases, and owned `boxes[]`;
- box: opaque `boxId`, exact `displayName`, authoritative `effect.rawGameText`, optional independently evidenced `normalizedSemantic`, evidence refs and observation aliases;
- compatibility translation: consumer, catalog venue ID, status (`EXPLICIT` or `UNRESOLVED`), and legacy value.

`UNKNOWN`, `NOT_APPLICABLE`, and `NOT_GAME_AUTHORITY` use explicit statuses with `value: null`. Zero remains the numeric value `0`; null is never rewritten to a default.

**FACT** — A box is nested under exactly one venue. Validation rejects duplicate venue/box IDs, ambiguous aliases, orphan or cross-venue box pairs, unsupported evidence, hash mismatch, and normalized semantics without current evidence.

**FACT** — `catalogStatus=DRAFT` cannot reach any consumer. Production use requires `APPROVED_FOR_PRODUCTION`, at least one approved current-game evidence record, matching build, and a deterministic evidence-bundle hash.

## 6. Consumer authority paths

### 6.1 Manual UI

Intended path:

`approved catalog → validate_catalog(require_production=True) → manual_options() → exact venue selector → boxes owned by selected venue`

No tier-first selector is generated. Tier may be null/`NOT_GAME_AUTHORITY`.

**FACT** — Production `app/main.py::_manual_options` and Overlay `VENUE_TIERS/BOXES_BY_TIER` remain unchanged in this cut because no catalog is approved. Switching them now would replace one unverified mapping with another.

**RECOMMENDATION** — After evidence is supplied and catalog frozen, replace both lists through one generated/read artifact in one cut. Do not leave Overlay's independent list active.

### 6.2 Canonical MatchRecord

Intended future-record path:

`exact venueId + optional boxId → validate_environment() → record environment + canonical_catalog_provenance()`

Provenance contains catalog version, game build and deterministic catalog SHA-256. Unknown venue with unknown box is legal; box without venue and invalid venue-box pair fail closed.

**FACT** — Existing Canonical v7 and history records were not modified. No schema migration/backfill occurred.

### 6.3 Vision normalization

Intended path:

`Vision observation string → normalize_vision_venue() → exactly one explicit catalog alias or UNKNOWN/REJECTED`

`haibei/shanhu/zhenzhu` are observation outputs, not authority. An observation absent from the approved catalog cannot create a venue.

### 6.4 Adapter/Solver compatibility

Intended path:

`catalog-validated venue/box → explicit compatibilityTranslations row → Solver context`

The result is labelled `COMPATIBILITY_TRANSLATION`. Missing/ambiguous mappings return `SOLVER_CONTEXT_MAPPING_UNRESOLVED`.

**FACT** — `core/v06_adapter.py` and `.js` still carry `shanhu/milin/baiye/haimo`; `core/auction_engine_v06.js` still consumes mixed `venueTier || venue` keys. They were not modified because mapping truth is unresolved.

**FACT** — No Solver formula, prior, candidate generation, or output source changed.

## 7. Legacy history classification

The read-only classifier is `tools/venue_box_catalog_audit.py`; frozen aggregate output is `assets/venue_box_catalog_v1/legacy_history_classification_v1.json`.

| Classification | Count / 290 | Meaning |
|---|---:|---|
| `CATALOG_VALID_CURRENT` | 0 | Impossible before a current approved catalog exists |
| `LEGACY_ALIAS` | 286 | Matches a known repository namespace only; no game-truth claim |
| `UNVERIFIED` | 0 | Nonempty value outside the audit's legacy registry |
| `CONFLICT` | 0 | No top-level/environment duplicate-value contradiction detected |
| `UNKNOWN` | 4 | No usable venue/tier/box observation |

Reason occurrences are non-exclusive: legacy venue namespace 223, tier namespace 40, box namespace 225. Historical raw counts include 40 non-null tiers (`gaoji=39`, `dingji=1`) and mixed exact/display/legacy venue strings.

**FACT** — History SHA-256 before and after the audit is `6a9695f8ef44058f2c369ac1bd1407a6306a327b63d1c0a160631d5348ed699a`.

**INFERENCE** — `LEGACY_ALIAS` means “recognizable historical vocabulary,” not “safe to migrate.” Frequency did not participate in truth selection.

## 8. Regression and verification

Focused contract tests cover:

- required current evidence, game build, timezone, file/hash and claims;
- deterministic evidence bundle/catalog hashing;
- UI venue/box derivation from the catalog only;
- draft catalog rejection;
- invalid venue, orphan box and cross-venue box rejection;
- explicit unknown/null and exact zero semantics;
- evidence-gated normalized effects;
- explicit Vision normalization;
- explicit legacy adapter translation and unresolved fail-closed behavior;
- Canonical catalog version/hash provenance;
- legacy classifier read-only behavior;
- no Solver/CurrentMatch/Vision runtime imports in the contract module.

Validation result: `15/15 PASS` for the new contract suite; `9/9 PASS` for the existing v06-adapter and Vision-contract suites. Two pre-existing `tests.test_business_sot` image/fixture cases still fail on their legacy expected extraction values; no touched file is in that execution path, and this cut deliberately does not repair those frozen legacy fixtures.

Production-source guard:

- no diff in `app/main.py`, `core/overlay_alpha.html`, adapters, Vision, Solver or history;
- `core/auction_engine_v06.js`: `8f31258f73b22ce978a61555ad6765e231305588f0b8239609ce8a8230f98862`;
- `core/solver_core_v06.js`: `1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f`;
- `core/shadow_profile_v06.js`: `9967f269f5c5b66dc8a010e3077ce014700c0b94333d93acf25a4021f9c886a5`;
- `core/live_shadow_runtime.js`: `c025083b8f9ab5d9c13abcaff0962a8fefc754eae6fcb6fc22e4a09801ba09af`.

Source smoke is limited to schema import/contract fixture and read-only history audit. Fresh-package UI smoke is intentionally not applicable: there is no approved catalog artifact to package or expose, and production UI was deliberately not switched.

## 9. Evidence gap and next gate

Minimum user evidence needed—no batch of played matches is required:

1. Current game build/patch identifier plus one complete venue-selection UI screenshot showing the whole selectable venue list.
2. For each selectable venue, one box/package selection screenshot showing all options, exact names, raw effect wording, and entry cost if visible.

Each source should retain original pixels, have a timezone-aware capture time and SHA-256, and receive an approved review record. Once these exist, the next cut can create an actual `APPROVED_FOR_PRODUCTION` catalog, resolve compatibility translations, then converge Manual UI/Canonical/Vision/adapter consumers and run source/fresh-package smoke.

## Final verdict

**`NEEDS_CURRENT_GAME_EVIDENCE`**

The authority boundary is implemented and fail-closed. The game catalog itself is not frozen, production consumers are not switched, `顶级场` is neither accepted nor deleted, and no legacy record is rewritten.
