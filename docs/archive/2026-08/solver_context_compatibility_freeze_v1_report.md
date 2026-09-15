# Solver Context Compatibility Freeze v1

## 1–3. Repository state

- Initial HEAD: `5678e4aa4f04e92ec739297ed06ac89058723467`
- Final HEAD: the independent commit reported at handoff; its parent is the Initial HEAD above.
- Tracked tree was clean at start. Existing untracked user files were preserved and excluded.

## 4–5. Exact v0.6 venue authority and identifiers

The primary authority is the real v0.6 production implementation in `lab/index.html`:

- `VENUE_ALIASES` maps exact short venue names to combined Solver identifiers;
- `LOW_TIER_PRIOR` consumes those combined identifiers;
- `VENUE_BOXES` and `BOX_ALIASES` provide the old box identifiers/effects.

The frozen supporting authority is `assets/business_sot_v06.json`, whose declared source is those same production symbols. Source hashes are frozen in the compatibility artifact:

- `lab/index.html`: `7159027a60481de576593704629d543fb52b49e857a758492a07b5b439155627`
- `assets/business_sot_v06.json`: `a0a580e01c050d88070cb206c64d395b3b0c1afbdbb3e2703e3b5642af4c8e0b`

The old identifiers are exactly:

| Current ID | Current display | v0.6 identifier | Prior |
|---|---|---|---:|
| `venue-haibei` | 海贝场 | `初级场 · 海贝场` | 8,000 |
| `venue-shanhu` | 珊瑚场 | `中级场 · 珊瑚场` | 12,000 |
| `venue-zhenzhu` | 真珠场 | `高级场 · 真珠场` | 30,000 |

## 6–9. Frozen venue translation and prior parity

All three `v06_solver` catalog rows changed from `UNRESOLVED` to `COMPATIBILITY_TRANSLATION`. Each row records catalog/current IDs, legacy identifier, source authority/reference, translation version, and artifact reference.

Direct engine verification through `AuctionEngineV06.lowTierValue` produces exactly `8000 / 12000 / 30000`. Three paired fixtures compare:

`old v0.6 identifier → engine`

with:

`current catalog ID → compatibility translation → same engine`.

Effective context, low-tier prior, candidate state output, P20/P50/P80, and structural center are byte/value equal for 海贝、珊瑚、真珠. There is no floating-point delta.

## 10–11. v0.6 box authority and per-box mapping

海贝/珊瑚 use `lab/index.html::VENUE_BOXES + BOX_ALIASES` as primary authority. 真珠 uses the v0.6 business SOT `observedBoxes.gaoji`, which preserves screenshot-backed legacy names and effect text.

| Current boxId | v0.6 legacy identifier | Solver semantic |
|---|---|---|
| `box-haibei-damaged-package` | `破损的包裹 · 紫色提升` | 紫色提升 |
| `box-haibei-complete-package` | `完整的包裹 · 金色提升` | 金色提升 |
| `box-haibei-waterlogged-package` | `浸水的包裹 · 紫色提升` | 紫色提升 |
| `box-haibei-unnamed-package` | `无名包裹 · 红色提升` | 红色提升 |
| `box-shanhu-mechanical` | `机械宝箱 · 科技类概率提升` | 科技类概率提升 |
| `box-shanhu-food` | `美食宝箱 · 食品类概率提升` | 食品类概率提升 |
| `box-shanhu-wood` | `实木宝箱 · 中级藏品概率提升` | 中级藏品概率提升 |
| `box-shanhu-glass` | `琉璃宝箱 · 宝石类概率提升` | 宝石类概率提升 |
| `box-shanhu-leather` | `皮制宝箱 · 高级藏品概率提升` | 高级藏品概率提升 |
| `box-shanhu-mother-of-pearl` | `螺钿宝箱 · 古董类概率提升` | 古董类概率提升 |
| `box-zhenzhu-complete-safe` | `完整的保险箱（高级藏品概率提升）` | 高级藏品概率提升 |
| `box-zhenzhu-brilliant-safe` | `璀璨的保险箱（宝石类概率提升）` | 宝石类概率提升 |
| `box-zhenzhu-classical-safe` | `古典的保险箱（古董类概率提升）` | 古董类概率提升 |
| `box-zhenzhu-precision-safe` | `精工的保险箱（科技类概率提升）` | 科技类概率提升 |
| `box-zhenzhu-whimsical-safe` | `奇趣的保险箱（食品类概率提升）` | 食品类概率提升 |
| `box-zhenzhu-rusted-safe` | `锈蚀的保险箱（中级藏品概率提升）` | 中级藏品概率提升 |

All 16 approved Alpha boxes have exactly one mapping and retain venue ownership. Cross-venue lookup is rejected.

## 12. Unknown-box behavior

`boxId = null` translates to:

- legacy identifier: `null`;
- semantic: `NO_BOX_EFFECT`;
- status: `UNKNOWN_NO_BOX_EFFECT`.

It never defaults to the first box, a normal box, or a damaged package. Unsupported venues and invalid venue/box pairs return `SOLVER_CONTEXT_MAPPING_UNRESOLVED`. Corrupt, stale, or source-hash-mismatched artifacts return `SOLVER_CONTEXT_COMPATIBILITY_INVALID`.

## 13. Game truth versus compatibility

The combined `初级/中级/高级` labels exist only as v0.6 compatibility identifiers. Current catalog truth remains:

- exact venues: 海贝场 / 珊瑚场 / 真珠场;
- every `tier.status = NOT_GAME_AUTHORITY`, `tier.value = null`;
- entry costs: 0 / 5,000 / 20,000;
- asset requirements: 0 / 1,000,000 / 5,000,000.

Current box `rawGameText`, evidence classes, membership, aliases, and `normalizedSemantic = null` are unchanged. A legacy semantic never overwrites raw game truth.

## 14. Catalog and helper changes

- `venue_box_catalog_v1.json`: only the three Solver compatibility rows changed, with provenance.
- `v06_solver_compatibility_v1.json`: new catalog-versioned mapping artifact with 3 venues, 16 boxes, and fail-closed unknown behavior.
- `core/venue_box_catalog.py`: validates catalog/artifact versions, source hashes, provenance, full coverage, box ownership, and unknown semantics; returns immutable translations.
- `venue-box-catalog-v1.schema.json`: admits versioned/provenanced `COMPATIBILITY_TRANSLATION` rows.
- PyInstaller spec includes the compatibility artifact for future runtime consumption.

Catalog file SHA changed only because those three compatibility rows were frozen:

- before: `321a0bd7851d30aaff40022621e4b4c0a1157a25873de28e50dcdaae7cbf01d3`
- after: `bb6ab1de152b1e86f539cbc86bb62b7968f7b3322d3ed16cd16132dae7c991df`

No Advice consumer was connected in this cut.

## 15–16. Integrity

Unchanged before/after hashes:

- `core/auction_engine_v06.js`: `8f31258f73b22ce978a61555ad6765e231305588f0b8239609ce8a8230f98862`
- `core/solver_core_v06.js`: `1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f`
- `core/shadow_profile_v06.js`: `9967f269f5c5b66dc8a010e3077ce014700c0b94333d93acf25a4021f9c886a5`
- repo research history: `6a9695f8ef44058f2c369ac1bd1407a6306a327b63d1c0a160631d5348ed699a`

No history backfill or rewrite occurred.

## 17–18. Parity fixtures and tests

Three minimum v0.6 parity fixtures passed:

- A: 海贝 + 浸水的包裹;
- B: 珊瑚 + 琉璃宝箱;
- C: 真珠 + 璀璨的保险箱.

Focused results:

- compatibility/catalog/parity suites: `38/38 PASS`;
- durable data + Main read-only state + terminal lifecycle suites: `41/41 PASS`;
- total relevant regression: `79/79 PASS`.

A broader legacy run separately reproduced the already-known `tests.test_manual_alpha` fixture debt: current Canonical `knownItems` is a structured list while the old test expects a string. This cut did not touch that producer or fixture.

## 19. Final verdict

`SOLVER_CONTEXT_COMPATIBILITY_FROZEN`

The sole previous Advice blocker is now frozen as a standalone, reversible compatibility cut. Advice/live-shadow/current-bid/target-profit/UI wiring remains intentionally untouched.

## 20. Commit

The independent commit hash is reported in the final handoff.
