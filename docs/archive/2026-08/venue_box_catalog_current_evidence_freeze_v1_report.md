# Current-game Venue Evidence Freeze + Box Evidence Reconciliation v1

Audit date: 2026-08-22 (Asia/Shanghai)

Initial HEAD: `94c12216ad32a6c075ca528fc30845af6e73c698`

Verdict: **`VENUE_TRUTH_FROZEN_BOX_EVIDENCE_PENDING`**

## 1. Current-game primary evidence

**FACT** — The user-provided original screenshot was located at `C:\Users\Administrator\Pictures\Snow Shot\SnowShot_2026-08-22_14-15-49.png`, visually reviewed, and copied without pixel modification to:

`assets/venue_box_catalog_v1/current_game_evidence/2026-08-22/venue-selection-full.png`

- dimensions: `1719×1012`;
- SHA-256 at source and destination: `b397a7bd921aeba6ed165f8ba972641d864672dd9b43c5d04d39179bb1d3d8da`;
- capture time: `2026-08-22T14:15:49+08:00`, derived from the original SnowShot filename and filesystem timestamp;
- evidence ID: `current-game-2026-08-22-venue-selection-full`;
- evidence type: `CURRENT_GAME_FULL_UI`;
- classification: `CURRENT_GAME_VALID`;
- review status: `APPROVED`.

**FACT** — `live-build-observed-2026-08-22` is the project-local evidence cohort identifier. The screenshot does not display a vendor patch string, so this value must not be presented as an official game patch number.

## 2. Facts directly supported by the screen

| Exact venue | Shown selectable | Asset requirement | Entry cost |
|---|---:|---:|---:|
| 海贝场 | Yes | 0 | 0 |
| 珊瑚场 | Yes | 1,000,000 | 5,000 |
| 真珠场 | Yes, locked for the shown account | 5,000,000 | 20,000 |

**FACT** — The complete selection view contains exactly three venue cards: `海贝场`, `珊瑚场`, `真珠场`.

**FACT** — No `初级场/中级场/高级场/顶级场` label appears in the screen. The catalog candidate records `tier.status=NOT_GAME_AUTHORITY`, `tier.value=null` for all three venues.

**FACT** — The screen does not show box/package options or effects. It provides no direct venue-box membership evidence.

**INFERENCE** — The absence of a fourth card is sufficient to exclude `顶级场/海沫/haimo/dingji` from this current production selectable venue set. It does not prove those names never existed historically.

## 3. Evidence and catalog artifacts

- Primary pixels: `assets/venue_box_catalog_v1/current_game_evidence/2026-08-22/venue-selection-full.png`
- Evidence metadata and 13 raw claims: `venue-selection-full.evidence.json`
- Updated evidence inventory: `assets/venue_box_catalog_v1/evidence_inventory_v1.json`
- Venue catalog candidate: `assets/venue_box_catalog_v1/venue_box_catalog_candidate_v1.json`
- Box reconciliation: `assets/venue_box_catalog_v1/box_evidence_reconciliation_v1.json`

The candidate uses:

- schema: `venue-box-catalog.v1`;
- status: `DRAFT`;
- deterministic evidence-bundle SHA-256: `a01da8d92eee94178583ba17b4970c0b9c87252384c411fa1c8dd3865cdbcba2`;
- deterministic candidate SHA-256: `934d1d11b8653bbf78b28d1a6c487bc69db98f68fe1a17d874dc220d955c21e6`;
- exact venues only; no tier defaults, no box defaults, no unsupported aliases;
- three unresolved Solver compatibility translations.

The contract now includes an evidence-gated `assetRequirement` fact and a `VENUE_ASSET_REQUIREMENT` claim type. It also distinguishes `USER_PROVIDED_TRUTH_CLUE` from current, legacy, and derived evidence.

## 4. Box evidence reconciliation

### 4.1 海贝场

Known project/user clue set:

- 破损的包裹;
- 完整的包裹;
- 浸水的包裹;
- 无名包裹.

**FACT** — Existing business SOT and project review text contain these names. The project review text preserves `低级藏品概率提升` for `浸水的包裹`.

**FACT** — The existing `紫色提升/金色提升/红色提升` forms are derived normalizations, not current raw game text. They are not promoted.

**STATUS** — `USER_PROVIDED_TRUTH_CLUE` for venue membership; `DERIVED_ONLY` for the currently stored text table. Required current evidence: a complete 海贝场 box-option screen with exact raw effect text.

### 4.2 珊瑚场

Known project/user clue set:

- 机械宝箱 — 科技类概率提升;
- 美食宝箱 — 食品类概率提升;
- 实木宝箱 — 中级藏品概率提升;
- 琉璃宝箱 — 宝石类概率提升;
- 皮制宝箱 — 高级藏品概率提升;
- 螺钿宝箱 — 古董类概率提升.

**FACT** — These mappings exist in project/user-derived SOT and history vocabulary, but no current complete 珊瑚场 box-option screenshot is present.

**STATUS** — `USER_PROVIDED_TRUTH_CLUE` for membership and `DERIVED_ONLY` for text. Required current evidence: one complete 珊瑚场 option screen confirming membership and current raw effect wording.

### 4.3 真珠场 / insurance boxes

The four old stream screenshots visibly support these old text observations:

- 完整的保险箱 — 高级藏品概率提升;
- 璀璨的保险箱 — 宝石类概率提升;
- 古典的保险箱 — 古董类概率提升;
- 精工的保险箱 — 科技类概率提升;
- 奇趣的保险箱 — 食品类概率提升;
- 锈蚀的保险箱 — 中级藏品概率提升.

**FACT** — The screenshots show the names/effects in a game UI, but do not show the containing venue. Their date/build is not provenance-complete.

**STATUS** — `LEGACY_GAME_EVIDENCE` for name/effect text at capture time; `VENUE_MEMBERSHIP_UNVERIFIED` for 真珠场; not current production box truth.

## 5. Production approval gate

The candidate passes structural/evidence validation as `DRAFT`.

It fails `require_production=True` with:

- `CATALOG_NOT_APPROVED_FOR_PRODUCTION`;
- `CATALOG_PRODUCTION_BOX_SET_EMPTY:venue-haibei`;
- `CATALOG_PRODUCTION_BOX_SET_EMPTY:venue-shanhu`;
- `CATALOG_PRODUCTION_BOX_SET_EMPTY:venue-zhenzhu`.

The validator also requires raw effect text for every production-admitted box. Thus a venue list with empty/default boxes cannot be silently approved.

## 6. Old top-tier handling

**FACT** — `顶级场/海沫/haimo/dingji` do not appear anywhere in the new current catalog candidate.

**FACT** — Existing history remains unchanged. The single observed `dingji` history value remains a legacy namespace value under `LEGACY_ALIAS` / `LEGACY_UNVERIFIED_CATALOG_VALUE` interpretation.

**FACT** — Current production Manual code still contains the old hardcode because switching a consumer to a DRAFT catalog is forbidden. It is not endorsed by this contract and remains a product blocker until box evidence allows one atomic consumer-convergence cut.

## 7. UI, Canonical, Vision and Solver boundaries

### UI

No production consumer was switched. When the catalog becomes approved, Manual options must be generated as:

`海贝场 / 珊瑚场 / 真珠场 → boxes owned by selected exact venue`

`纸箱/铁皮箱/金库保险箱/顶级场` cannot survive as independent current-game UI constants.

### Canonical

No history or Canonical schema was rewritten. The contract is ready to attach catalog version/build/hash to future validated records, but this is not activated by a DRAFT catalog.

### Vision

No OCR/Vision model changed. `haibei/shanhu/zhenzhu` remain observation labels, not authority. Future normalization must use explicit approved catalog aliases.

### Adapter/Solver

All three candidate compatibility translations remain `UNRESOLVED`. Mapping exact venues to `chuji/zhongji/gaoji` merely to reuse current low-tier priors would assume the unverified tier/business semantics this cut explicitly removed.

No Solver formula, candidate generation, prior number, or output changed.

## 8. Verification

- Current evidence validates with `require_current=True`.
- Candidate validates as a deterministic DRAFT.
- Production gate rejects all three empty box sets.
- Three exact venue names, asset requirements and costs are asserted from the real screenshot.
- Unsupported current top-tier values are absent from the candidate.
- Tier is `NOT_GAME_AUTHORITY/null` for every venue.
- Unknown box remains legal; box-without-venue and invalid venue-box pair fail closed.
- Legacy history is byte-for-byte unchanged.
- Solver/Shadow sources are byte-for-byte unchanged.
- Production Manual UI and adapters have no diff.

Because the catalog is not `APPROVED_FOR_PRODUCTION`, source/fresh-package Manual-option smoke is intentionally not run: production consumer switching is outside the evidence-safe boundary of this cut.

## 9. Exact remaining evidence request

Venue evidence is complete for this observed current build. Do not request the venue-selection screen again.

Only box evidence remains:

1. One current complete box/package option screen after selecting 海贝场.
2. One current complete box option screen after selecting 珊瑚场.
3. One current complete box/insurance option screen after selecting 真珠场.

Each screen must keep the selected venue context, all options and exact effect wording visible. No played match is required.

## Final verdict

**`VENUE_TRUTH_FROZEN_BOX_EVIDENCE_PENDING`**

The current three-venue set, asset requirements and entry costs are frozen. Production approval and consumer convergence remain blocked only by current venue-box membership/option/effect evidence.
