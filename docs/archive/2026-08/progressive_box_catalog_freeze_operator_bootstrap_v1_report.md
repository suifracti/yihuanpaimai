# Progressive Box Catalog Freeze / Operator-Asserted Bootstrap v1

## Verdict

`ALPHA_CATALOG_APPROVED_PROGRESSIVE_VERIFICATION`

The current-game venue facts remain screenshot-verified. Box membership is usable for the 0.67 Alpha under a separately labelled operator assertion; it is **not** promoted to current-game verified truth. Production-grade box verification remains progressive and passive.

## 1. Initial HEAD

`32f1d025f000951a8dc62aff0f8efe8eebd99dc4`

## 2. Final HEAD

The independent commit containing this report is the final HEAD reported in item 25 and in the task hand-off. A Git commit cannot embed its own object ID without changing that ID.

## 3. Tracked status

The cut stages only the contract, catalog/evidence artifacts, four already-supplied legacy evidence screenshots, minimal consumers, tests, and this report. Existing unrelated untracked workspace files remain untouched. Post-commit tracked status is clean.

## 4. v0.6 box authority source

FACT — `assets/business_sot_v06.json` declares its source as `lab/index.html VENUE_ALIASES / VENUE_BOXES / BOX_ALIASES / FIELD_CONDITIONS`. `lab/index.html` is the retained v0.6 mapping authority. It also proves that the sea-package color labels were derived canonical aliases: inputs such as `低级提升` were normalized to `紫色提升`; those colors are not frozen as raw game text.

## 5. 海贝 box baseline

Operator confidence `CONFIRMED`, membership `OPERATOR_ASSERTED_CURRENT`:

- 破损的包裹 — retained source wording `低级提升`, text class `DERIVED_ONLY`;
- 完整的包裹 — retained source wording `中级提升`, text class `DERIVED_ONLY`;
- 浸水的包裹 — retained reviewed wording `低级藏品概率提升`, text class `DERIVED_ONLY`;
- 无名包裹 — retained source wording `高级提升`, text class `DERIVED_ONLY`.

No `紫色/金色/红色提升` alias is promoted to raw game text.

## 6. 珊瑚 box baseline

Operator confidence `CONFIRMED`, membership and retained v0.6 effect text `OPERATOR_ASSERTED_CURRENT`:

- 机械宝箱 — 科技类概率提升;
- 美食宝箱 — 食品类概率提升;
- 实木宝箱 — 中级藏品概率提升;
- 琉璃宝箱 — 宝石类概率提升;
- 皮制宝箱 — 高级藏品概率提升;
- 螺钿宝箱 — 古董类概率提升.

## 7. 真珠 insurance baseline

Membership is `OPERATOR_ASSERTED_CURRENT`, confidence `PROBABLE`. Names/effect wording remain `LEGACY_GAME_EVIDENCE`:

- 完整的保险箱 — 高级藏品概率提升;
- 璀璨的保险箱 — 宝石类概率提升;
- 古典的保险箱 — 古董类概率提升;
- 精工的保险箱 — 科技类概率提升;
- 奇趣的保险箱 — 食品类概率提升;
- 锈蚀的保险箱 — 中级藏品概率提升.

The four evidence screenshot SHA-256 values are frozen in `progressive_box_bootstrap_v1.json`. They prove visible legacy name/effect text, not current 真珠 membership.

## 8. Operator assertion semantics

`OPERATOR_ASSERTED_CURRENT` is stronger than derived-only project material but weaker than `CURRENT_GAME_VALID`. It requires an approved `OPERATOR_ASSERTION`, a timezone-aware source record, and `operatorConfidence = CONFIRMED | PROBABLE`. The validator rejects an assertion that tries to pass the current-evidence gate.

## 9. Evidence class per box

The catalog stores `membershipEvidenceClass`, `textEvidenceClass`, and `operatorConfidence` independently on every box. Catalog-level Alpha approval never rewrites these per-fact classes. Current venue facts remain `CURRENT_GAME_VALID`.

## 10. APPROVED_FOR_ALPHA gate

The gate requires approved current venue evidence, non-empty per-venue box bootstrap sets, valid box ownership, explicit per-box evidence classes, and valid operator evidence for operator-owned membership. The resulting catalog is `venue-box-catalog.alpha.2026-08-22.v1`, status `APPROVED_FOR_ALPHA`.

## 11. APPROVED_FOR_PRODUCTION remaining gate

Production approval still fails closed because every box membership/text fact is not yet `CURRENT_GAME_VALID`. The validator emits production membership/text failures; Alpha approval does not waive them.

## 12. Unknown / Other behavior

Every venue derives a final `未知 / 其他` option with `boxId = null`, evidence/reason class `UNRECOGNIZED_CURRENT_BOX`. It never aliases to the first box and remains legal for normal estimation. Cross-venue box IDs fail closed.

## 13. Progressive observation contract

`BoxObservation v1` records timezone-aware observation time, exact venue, raw display/effect text, optional screenshot hash/reference and match ID, reviewer, catalog version, and `PASSIVE_NATURAL_COLLECTION`. An approved observation may move operator assertion to `CURRENT_GAME_OBSERVED`. Promotion to `CURRENT_GAME_VALID` requires a separate explicit versioned review decision; no arbitrary fixed-N rule exists. Dedicated box grinding is explicitly not required.

## 14. UI convergence

Manual options are now derived from `venue_box_catalog_v1.json`: 海贝场 / 珊瑚场 / 真珠场. Overlay no longer owns `VENUE_TIERS` or `BOXES_BY_TIER`, and no production Manual hardcode for 顶级场 / 纸箱 / 铁皮箱 / 金库保险箱 remains. Box options are derived from the selected exact venue plus Unknown/Other.

## 15. Entry-cost convergence

Future Manual facts resolve entry cost from the exact current-game venue: `0 / 5000 / 20000`. `CurrentMatch.to_canonical()` no longer silently writes 5000; unknown venue preserves unknown cost.

## 16. Canonical provenance

Future Manual canonical environment records carry exact `venueId`, `boxId`, catalog version/status/hash, game evidence cohort, and separate venue/box evidence classes. Unknown boxes remain null with `UNRECOGNIZED_CURRENT_BOX`. Existing history is byte-for-byte unchanged.

## 17. Shadow admission protection

A new pre-runtime admission guard supplies `allowedHistoryIds` and excludes only records explicitly marked `boxEvidenceClass = OPERATOR_ASSERTED_CURRENT`. Missing legacy provenance remains legacy-compatible; `CURRENT_GAME_OBSERVED` is not falsely relabelled. No Shadow formula/profile source changed.

## 18. Vision normalization

Catalog helpers normalize explicit venue/box aliases only and label their result `VISION_OBSERVATION`. Unknown observations remain unknown. No OCR/Vision model or inference behavior changed, and observation provenance never becomes catalog truth.

## 19. Solver compatibility

`SOLVER_CONTEXT_MAPPING_UNRESOLVED` remains the safe boundary. The retained v0.6 names do not prove that current exact venues semantically match the present Solver's legacy context keys. Manual supplies exact venue/box facts; no inferred `chuji/zhongji/gaoji` game tier or compatibility translation was added.

## 20. Solver hashes before / after

Unchanged:

- `auction_engine_v06.js`: `8f31258f73b22ce978a61555ad6765e231305588f0b8239609ce8a8230f98862`
- `solver_core_v06.js`: `1ec8dca270a8219eb00133421723a114f3649b81cd07c769c765ac2c7afed07f`
- `shadow_profile_v06.js`: `9967f269f5c5b66dc8a010e3077ce014700c0b94333d93acf25a4021f9c886a5`

## 21. History hash before / after

Unchanged: `6a9695f8ef44058f2c369ac1bd1407a6306a327b63d1c0a160631d5348ed699a`.

## 22. Source / package smoke

- Source native smoke: Main presentation, Overlay bridge, same Overlay HWND/Solver runtime, clean exit — PASS.
- Fresh PyInstaller build — PASS.
- Fresh packaged native smoke: Main presentation, Overlay bridge, same Overlay HWND/Solver runtime, clean exit — PASS.
- Source/package catalog SHA parity — PASS (`321a0bd7851d30aaff40022621e4b4c0a1157a25873de28e50dcdaae7cbf01d3`).
- The pre-existing desktop-pet drag smoke had one local opaque-pixel drag timeout; the independent native lifecycle smoke passed, and this cut does not modify desktop-pet code.

## 23. Tests

- Focused catalog/manual/lifecycle/presentation suite: `81/81 PASS` at integration checkpoint; final catalog-specific suite includes the additional Vision provenance case.
- Overlay inline script parse: PASS.
- Python compileall: PASS.
- Existing unrelated `test_manual_alpha` legacy expectation (`knownItems` raw string vs canonical list) remains pre-existing debt and was not changed.
- Existing business-SOT legacy fixture debt was not rewritten.

## 24. Final verdict

`ALPHA_CATALOG_APPROVED_PROGRESSIVE_VERIFICATION`

## 25. Commit

Independent commit message: `feat(catalog): approve progressive alpha box catalog`. The concrete commit hash is reported after Git creates the object.
