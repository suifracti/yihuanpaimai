# 0.67 Product / UI Readiness Gap Audit v1

**Audit date:** 2026-08-22 (Asia/Shanghai)

**Initial code checkpoint:** `3bfc8614be9c0b89ed1bd9ace05ccd47068ab02a`

**Mode:** read-only product/runtime audit. No Solver, UI, history, capture, Vision/OCR, or product behavior was changed.
**Product verdict:** `ALPHA_PRODUCT_USABLE_V1 = FAIL`

## 1. Executive result

The native desktop shell is no longer the limiting factor. Source and fresh-package runtime evidence confirms one Main lifetime owner, one existing Overlay/Solver runtime, one Desktop Pet, same-HWND Overlay hide/show, and clean shutdown.

The product is nevertheless not ready to hand to a normal Alpha user. Six independent product blockers remain:

1. Venue/box facts have no verified current-game catalog authority. The product ships four hard-coded manual tiers including `顶级场`, while the business SOT and Vision enumerate a different three-venue model; the beginner box selector is also disconnected from the business SOT and contradicts saved real-session evidence. Venue tier changes Solver valuation and both tier/box are persisted, so this is a data-correctness blocker rather than copy debt.
2. The packaged app resolves its canonical history to the bundled `_internal/异环拍卖数据.json`, not a durable per-user data location. Source and package therefore do not share one runtime history authority, and package upgrades/install permissions can fork or lose user data.
3. Manual “新一局” flushes the old record as `DRAFT` and immediately creates a new `DRAFT`; it does not settle, finalize, or archive the previous match.
4. Manual Overlay executes the real `auction_engine_v06.js`, but calls it without admitted history or a production probability profile. The observed output is `structural_only`, with `rawShadow=null` and no formal bid recommendation. The UI displays its structural P20/P50/P80 but hides the engine’s degradation/action result.
5. Main still renders convincing mock values and percentages, including mislabeled “P20/P50/P80 accuracy”, although no frozen formal evaluation artifact exists.
6. Users cannot inspect even a minimal admitted-history list or single-match detail from Main.

No algorithm change is needed to address these gaps. They are catalog-truth, data ownership, lifecycle, adapter/presentation, and read-only product surface gaps.

## 2. Authority and repository facts

### FACT

| Question | Current authority / result |
|---|---|
| HEAD at audit start | `3bfc8614be9c0b89ed1bd9ace05ccd47068ab02a` |
| Tracked worktree at audit start | Clean |
| Untracked files | Numerous pre-existing user/experiment/design files; none were opened as authority for product behavior unless named in this report, modified, deleted, staged, or committed |
| Product version authority | `core/version.py`: `APP_PRODUCT_VERSION = "v0.67-alpha"`; Canonical schema authority is `7` |
| Stale version surfaces | `app/main.py` module docstring, `app/config.json`, `app/run.bat`, and `README.md` still say 0.65; the AppUserModelID also retains `v065` |
| Packaged entry point | `app/main.py`, declared by `app/异环拍卖助手.spec` |
| Main host | `app/main_window.py` + `core/main_window.html/css/js` |
| Overlay host | `DirectCompositionHudForm` + `core/overlay_alpha.html` |
| Desktop Pet host | `app/desktop_pet.py` |
| Application lifetime | `Application.Run(main_window)` on one GUI STA |
| Production Solver runtime | The single Overlay WebView loads `auction_engine_v06.js` and `v06_adapter.js` |
| Main Solver ownership | None; Main loads presentation assets only |

### INFERENCE

`core/version.py` is the correct version SOT, but the stale 0.65 labels create release/support ambiguity. This is not the reason the app is unusable, so it is below functional blockers.

## 3. Actual lifecycle and runtime ownership

```text
process start (app/main.py)
  -> optional WS daemon thread
  -> one GUI STA
     -> create native MainWindow
     -> create DirectComposition Overlay exactly once
     -> initialize one shared CoreWebView2Environment
        -> Overlay WebView: production Solver owner
        -> Main WebView: presentation-only consumer
     -> create one native Desktop Pet
     -> Application.Run(main_window)
  -> Main close
     -> idempotent ShutdownCoordinator
     -> flush manual DRAFT
     -> stop Vision / WS
     -> close Pet / Main WebView / Overlay resources
     -> message loop returns
     -> GUI STA and Python main return
```

Overlay close is redirected to `Hide()` unless shutdown is already in progress. Main’s Overlay toggle also calls `Hide()`/`Show()` on the same object. Runtime smoke confirmed the same Overlay HWND after the round trip.

## 4. CURRENT_ALPHA_USER_FLOW

### What a user can do now

1. Start `异环拍卖助手.exe`.
2. See Main, Overlay, and Desktop Pet.
3. Use Main’s header control to hide or restore the same Overlay.
4. Expand the Overlay.
5. Select venue tier, field condition, and box.
6. Enter `Q` and `goldAvg`; optionally enter `purpleCount` and known Gold/Red/Purple constraints.
7. See local P20/P50/P80 values update synchronously.
8. Click “新一局” to clear the visible inputs and receive a new `matchId`.
9. Close Main to exit all owned runtime components.

### Where the flow stops being a valid product loop

| Step | Finding | Severity |
|---|---|---|
| Solver output | Values are structural quantiles when no probability profile is supplied; the engine itself says “结构参考 · 无整仓 P50” | `P0_BLOCKER` |
| Advice | Overlay does not render `actionDirective`, degradation level, safe/recommended/chase lines, or a current-bid comparison | `P0_BLOCKER` |
| End of match | No Manual settlement/truth confirmation surface exists | `P0_BLOCKER` |
| “新一局” | Old match is only saved as DRAFT, then current holders and UI facts are cleared | `P0_BLOCKER` |
| Archive | No DRAFT -> FINALIZED transition occurs; admitted History and Shadow do not receive the match | `P0_BLOCKER` |
| Review | No Main History/Records page can show the old match or its exclusion reason | `P0_BLOCKER` |

The UI reset itself is real: `CurrentMatch.begin_next_match()` creates a new ID and clears venue/box/condition, counts, known items, totals, and character. That is not equivalent to a safe terminal match transition.

## 5. Main page readiness matrix

| Surface | Classification | Actual data / behavior | User impact |
|---|---|---|---|
| Overview page | `REAL_BUT_INCOMPLETE` | Only “今日对局数”, yesterday comparison, and 12-day count series come from `MainViewStateProvider` | One real card is surrounded by five fake business cards and a fake performance strip |
| Analysis page | `MOCK_PRESENTATION_ONLY` | Fixed 68/56/44%, MAE 2,420, direction 71%, extreme 31%, and B+ | Looks like formal model performance despite no publishable artifact |
| Records / History | `NOT_IMPLEMENTED` | Disabled navigation button | User cannot inspect admitted records, DRAFTs, exclusions, or one match |
| Match page | `NOT_IMPLEMENTED` | Disabled navigation button | No Main-side current-match or terminal-match workflow |
| Settings | `NOT_IMPLEMENTED` | Disabled navigation button | User cannot manage product settings from Main; not by itself an Alpha blocker |
| Overlay status/toggle | `REAL_AND_USABLE` | Narrow native bridge; same Overlay object is hidden/restored | Pass |
| Desktop Pet | `REAL_BUT_INCOMPLETE` | Real Pet and interactions; Main control exists only in the native title-bar system menu | Function works but discoverability is poor |
| Main loading | `REAL_BUT_INCOMPLETE` | Native “正在载入” label until WebView initialization | Adequate startup state; no retry/action on failure |
| Main history error | `BROKEN` | A missing/corrupt history file can throw out of `MainViewStateProvider.snapshot()` and prevent a complete `app_status` response | Overlay control/status can remain unavailable instead of degrading only the history card |

## 6. Overview real/mock boundary

### REAL_AND_ALLOWED

- Current history revision metadata.
- History admission totals/reason counts.
- Today/yesterday admitted match counts.
- Dated admitted count series.

At audit time the actual file contained **290** records: **155 admitted**, **135 excluded** (`DRAFT=110`, `INVALID_TIMESTAMP=21`, `LEGACY_WITHOUT_SETTLEMENT_EVIDENCE=4`). Today’s admitted count was `0`; one dated record today was excluded.

### NOT_AVAILABLE_YET

- Today total value.
- Average and highest settled value under one formal truth/admission contract.
- Net profit and spend under unified finance semantics.
- Any production prediction accuracy or model score.

The existing disclaimer correctly calls the data demo, but a disclaimer does not make realistic fake numbers acceptable in a distributable Alpha. Unavailable cards should show a single honest “尚未有正式数据/自然收集中” state, not invented values or deltas.

## 7. Analysis readiness

### FACT

- `core/main_window.js` owns `mockPredictionPerformanceState`.
- No frozen production Prediction Evaluation Summary artifact is read by Main.
- Natural upper-tail collection currently has `realValidPairCount = 0`.
- P20/P50/P80 produced by Solver are value-distribution quantiles, not three “accuracy” bands.

### Verdict

Analysis is `MOCK_PRESENTATION_ONLY` and must not publish any percentage, MAE, grade, trend, or interpretation as product data. The minimal Alpha state is:

- “尚无足够正式评估数据”；
- “正在自然收集 contract-valid prediction/truth pairs”；
- no percentages, no B+, no “较昨天”, and no fabricated interpretation.

Formal evaluation remains parked until a frozen artifact exists. Main must never replay Solver to synthesize these metrics.

## 8. History / Records readiness

### FACT

- `history_admission.py` and `MainViewStateProvider` already provide a versioned, fail-closed admission foundation.
- The provider deliberately discards raw records after count aggregation.
- Main receives no record list or record-detail projection.
- The legacy `lab/index.html` contains rich review/edit/import/export/settlement functions but is a separate browser-oriented lab, not the Main product page and not a safe substitute for a read-only History contract.

### Minimum trustworthy History product boundary

The first usable History page should show presentation-ready immutable projections only:

- played time (Asia/Shanghai normalized);
- lifecycle/admission badge and exclusion reason;
- environment: venue/box/field condition;
- core observed facts: Q, G/P/R counts when known, gold average, known constraints summary;
- prediction snapshot status/mode and frozen P20/P50/P80 when provenance-valid;
- settlement actual/clearing/acquired only when truth gate permits;
- explicit completeness/confidence/evidence label;
- no raw JSON, mutable record, OCR text, Solver input/result, or record-edit authority.

History is therefore `NOT_IMPLEMENTED`, although its admission foundation is `ALREADY_PASS`.

## 9. Overlay readiness

### ALREADY_PASS

- Compact and expanded modes render at the configured 560px width without a P0 clipping issue in source runtime.
- Q, purple count, gold average, known Gold/Red/Purple, venue tier, field condition, and box are editable.
- Known-item expressions have validation and suggestions.
- Partial/incomplete input has readable fallback copy.
- Changes are debounced to native DRAFT persistence.
- One Overlay WebView remains the only production Solver owner.
- Main hide/show does not recreate the Overlay or Solver runtime.

### Blocking or required gaps

1. `paintResult()` calls `solveAuctionPipeline(solverIn || {})` with one argument. The engine’s `records=[]` default is therefore used, and the manual input supplies no `probabilityProfile`.
2. A representative current input returned `solverStatus=valid` but `rawShadow=null`, `coverageRatio=0`, `degradationLevel=structural_only`, `recommendedMax=null`, and “结构参考 · 无整仓 P50”.
3. Overlay nevertheless labels and renders the structural median as “估值 (P50)” and does not expose the degradation/action reason.
4. Gold and Red exact counts are supported by `CurrentMatch`, Canonical v7, both adapters, and Solver, but have no Overlay inputs.
5. Costs/target profit/current bid have material decision semantics. Manual Canonical silently fixes costs to entry=5,000, other costs=0 and the adapter defaults target profit to 30,000, while Overlay exposes neither assumptions nor bid input.
6. The Screenshot button sends `capture_hud`; the DirectComposition message dispatcher only handles `capture_overlay_preview`. In normal packaged runtime the visible button therefore has no implemented native action.
7. WebSocket reconnect is silent. Persistence or host-sync failure can leave local values visible with stale “已保存草稿/自动保存中” copy.
8. A blank bootstrap reports `draftSaved=True`, so an untouched match can show “已保存草稿” even though no record was written.

## 10. Manual input completeness

| Fact / input | Solver role | Current manual UI | Classification |
|---|---|---|---|
| `q` | Minimum requirement for non-null structural value | Yes | `REQUIRED_INPUT / AVAILABLE_MANUAL_INPUT` |
| `goldAvg` | Minimum requirement for non-null structural value | Yes | `REQUIRED_INPUT / AVAILABLE_MANUAL_INPUT` |
| venue tier / venue | Prior/context | Tier yes; exact venue is not directly selected | `OPTIONAL_INFORMATION / PARTIAL` |
| box | Material prior/context | Yes | `AVAILABLE_MANUAL_INPUT` |
| field condition | Material multiplier/semantics | Yes | `AVAILABLE_MANUAL_INPUT` |
| `purpleCount` | Material candidate-state constraint | Yes | `AVAILABLE_MANUAL_INPUT` |
| known Gold/Red/Purple | Material value/state constraints | Yes | `AVAILABLE_MANUAL_INPUT` |
| `goldCount` | Strong exact-state lock | No | `MISSING_UI_INPUT / P1_REQUIRED` |
| `redCount` | Strong upper-tail lock, including explicit R=0 | No | `MISSING_UI_INPUT / P1_REQUIRED` |
| current/leader bid | Required to turn value into an actionable continue/stop comparison | No | `MISSING_UI_INPUT / P0 within formal-advice cut` |
| actual costs | Required for reliable recommendation lines | No; silently fixed/defaulted | `MISSING_UI_INPUT / P0 within formal-advice cut` |
| target profit | Decision policy input | No; defaults to 30,000 | `MISSING_UI_INPUT / P1_REQUIRED` |
| probability profile / admitted history support | Required for full/partial Historical Shadow decision mode | Not supplied to manual solve | `MISSING_ADAPTER_INPUT / P0_BLOCKER` |
| character | Canonical provenance; not currently material to engine value calculation | No | `OPTIONAL_INFORMATION / PARKED` |
| lobby/solver tool group | Canonical loadout provenance; current engine does not consume it as a live value constraint | No | `OPTIONAL_INFORMATION / PARKED` |
| total item/grid and lower-rarity details | Advanced structural/explainability facts | No | `OPTIONAL_INFORMATION / CAN_WAIT` |

Gold/Red count impact is not theoretical: the existing parity suite confirms that count locks materially collapse or reject candidate state sets.

## 10A. Venue / Box Catalog SOT audit

### Verdict

`VENUE_CATALOG_TRUTH_UNVERIFIED`

This is a `P0_BLOCKER / DATA_CORRECTNESS` candidate confirmed as a product blocker. The user report is treated as a defect signal, not as game truth; conversely, the repository's current constants are not allowed to prove themselves correct. The repository has no versioned, current-game evidence bundle that can authoritatively answer how many venues exist or which boxes belong to each venue.

### FACT — origin of `顶级场`

The earliest repository occurrence is not a game capture or catalog. Git history shows:

1. `b74fd5de` (2026-08-16 15:38 +08:00) introduced design/audit documents that declared Canonical venue IDs `shanhu | milin | baiye | haimo` and described `haimo` as `顶级场 · 海沫场`. At that commit, `git grep` finds the concept only in `docs/audits/2026-08-16-v06-v065-contract-audit.md` and `docs/contracts/canonical-match-record-v7.md`.
2. `4ee1229c` (2026-08-16 19:16 +08:00) copied that document enum into `core/v06_adapter.py/js`.
3. `aefa09a2` (2026-08-19 23:15 +08:00) added the user-visible `dingji / 顶级场` tier and `金库保险箱` to `app/main.py` and `core/overlay_alpha.html` as hard-coded manual selector data.

The preserved v0.6 `lab/index.html` does **not** offer a top venue; it exposes only `初级场 · 海贝场`, `中级场 · 珊瑚场`, and `高级场 · 真珠场`. No evidence reference accompanies the top-tier document enum or the later `金库保险箱` UI entry. The trace therefore supports **historical contract/design carry-over**, not verified current-game truth.

### FACT — current definitions are split

| Layer | Current accepted/displayed values | Authority problem |
|---|---|---|
| Manual native payload (`app/main.py:_manual_options`) | tier IDs `chuji / zhongji / gaoji / dingji` | Hard-coded; duplicates HTML; not derived from business SOT |
| Manual Overlay (`VENUE_TIERS`, `BOXES_BY_TIER`) | `初级/中级/高级/顶级`; beginner boxes `纸箱/铁皮箱`; top box `金库保险箱` | This is the selector actually used. `manualOptions` sent by native is not consumed by Overlay |
| Business SOT (`assets/business_sot_v06.json`) | `初级场 · 海贝场`, `中级场 · 珊瑚场`, `高级场 · 真珠场`; no top venue | Its own provenance says it was copied from `lab/index.html`, not a versioned game catalog |
| Vision (`core/vision_pipeline.py`) | `haibei`, `shanhu`, `zhenzhu`; no top venue | Matches the three-entry business SOT, with only partial real template coverage |
| v0.6 adapters | `shanhu`, `milin`, `baiye`, `haimo` -> 珊瑚/密林/白夜/海沫 | Conflicts with `haibei/shanhu/zhenzhu`; originated from the unverified Canonical design document |
| Canonical v7 | Stores free scalar `environment.venueTier`, `venue`, `venueName`, `box`, `boxType` | Schema preserves values but does not validate membership or venue-box compatibility |
| Solver | `LOW_TIER_PRIOR` accepts four tier IDs plus both old exact names/IDs; `dingji` and `gaoji` both map to 30,000 | Solver compatibility constants are not catalog truth |

This is genuine four-way drift: **UI**, **business/vision SOT**, **adapter/Canonical enum**, and **history** do not share one closed, evidence-backed catalog.

### FACT — beginner box mismatch

The current business SOT says `初级场 · 海贝场` has four package variants: 破损、完整、浸水、无名. The project document's reviewed real-session evidence records `海贝场 + 浸水的包裹（低级藏品概率提升）`. The currently shipped manual UI instead offers only `纸箱`, `铁皮箱`, and `未知/其他`.

There is also a semantic conflict inside the retained evidence: the SOT canonicalizes the reviewed `低级藏品概率提升` wording to `浸水的包裹 · 紫色提升`. That may be an alias/migration convenience, but it is not sufficient proof that the effect is truly “紫色提升”. No value should be guessed until current-game evidence is frozen.

`纸箱`, `铁皮箱`, and `金库保险箱` first entered the production selector in `aefa09a2`; they are absent from `boxesByVenue` and have no local game-evidence reference. `canonicalize_box()` does not reject them: unknown nonblank text is passed through, so UI hard-code becomes persisted fact rather than failing closed.

### FACT — UI, Canonical, Solver, and persistence data flow

```text
Overlay VENUE_TIERS / BOXES_BY_TIER
  -> manualState.venueTier + manualState.box
  -> manual_facts WebMessage
  -> app/main.py:apply_manual_facts()
  -> CurrentMatch facts
  -> CurrentMatch.to_canonical().environment
  -> canonical_to_v06_solver_input()
  -> auction_engine_v06.js
  -> DRAFT persistence in 异环拍卖数据.json
```

- Selecting a tier does not select an exact venue. `manualState.venue` remains `null`; Canonical can therefore contain `venueTier=gaoji/dingji` with `venue=null`.
- `canonical_to_v06_solver_input()` forwards both `venueTier` and `box`.
- `auction_engine_v06.js:lowTierValue()` explicitly prioritizes `ctx.venueTier` over exact `venue`; therefore the UI tier is not presentation-only.
- A deterministic probe with identical `Q=9`, `goldAvg=40000`, `purpleCount=4` produced the same three candidate states for all tiers, but formal P50 changed from `265,735` (`chuji`) to `269,735` (`zhongji`) and `287,735` (`gaoji`/`dingji`). This isolates a value-prior effect; it does not validate any tier constant.
- In current exact-state generation, venue/box do not create or remove `(G,P,R)` candidate states. `fieldCondition` does affect valuation multipliers/semantics.
- In the production Historical Shadow path, `venue`/`box` are used to group historical support and influence box-value ceilings and state likelihood. The current Manual Overlay local call supplies neither admitted records nor a profile, so an A/B probe of only the box string left its structural quantiles unchanged. That current no-effect is path-specific and must not be mistaken for harmless persisted data.
- Manual Canonical also fixes entry cost to 5,000 independently of selected tier/exact venue, while business SOT says 0/5,000/20,000 for its three venue entries. The selected catalog context and stored cost can therefore contradict one another.

### FACT — legacy/history contamination already exists

The 290-record snapshot contains:

| Field | Observed saved values |
|---|---|
| `venueTier` | null=250, `gaoji`=39, `dingji`=1 |
| exact/root `venue` | `中级场 · 珊瑚场`=158, `shanhu`=42, `初级场 · 海贝场`=16, `gaoji`=4, `haibei`=3, `未知场地`=1, null=66 |
| `box` | mixed canonical names, null/unknown, legacy `standard`, plus 39 `完整的保险箱（高级藏品概率提升）` DRAFTs |

All 40 records with `venueTier=gaoji/dingji` are current schema-7 Manual `DRAFT`s; the sole `dingji` record has no exact venue or box. They are excluded by today's History admission policy, but they prove that the old UI enum is already persisted. No backfill or rewrite is authorized in this audit.

### Effect matrix

| Selected datum | Candidate generation | Value prior / valuation | Probability profile | Persisted history |
|---|---|---|---|---|
| `venueTier` | No observed `(G,P,R)` support change in current exact generator | **Yes** — direct low-tier residual prior | Indirect/contextual where carried into Shadow | **Yes** |
| exact `venue` | Not in current exact enumeration | Used when tier is absent; also cost/business context | **Yes** — historical grouping/prior paths | **Yes** |
| `box` | No direct current exact-state change | No structural A/B change in the empty-record Manual call | **Yes** — historical box grouping/count/value support | **Yes** |
| `fieldCondition` | Does not define venue catalog | **Yes** — quality multipliers/special semantics | Cohort/history grouping | **Yes** |

Because a false tier changes displayed formal values and false tier/box facts are persisted for future history/profile use, the issue meets the requested `P0_BLOCKER` rule. Fixing only the Chinese label while retaining the mapping would be unsafe.

### Minimum evidence required before freezing a catalog

1. Exact current game build/patch identifier and capture timestamp.
2. Full venue-selection UI showing every selectable venue/tier in that build.
3. For each venue, a complete box/package list or repeatable selection/roll evidence, including the exact effect text.
4. Source screenshots/video with uncropped context and hashes, plus human review status.
5. Explicit distinction between venue **tier**, exact venue, box display name, box effect, and entry cost.
6. A versioned catalog artifact whose entries cite those evidence IDs; unknown remains unknown and fails closed.

### RECOMMENDATION

Freeze a minimal evidence-backed Venue/Box Catalog Contract before improving formal Manual advice or allowing Manual FINALIZED records. Make that contract the one input to UI options, Canonical validation, Vision normalization, cost lookup, adapter translation, Solver context, and History presentation. Preserve old history values as legacy/unverified observations; do not rewrite them and do not use their frequency as game truth.

## 11. Next-match / lifecycle verdict

**Verdict:** `UNSAFE_FOR_ALPHA_PRODUCT_LOOP`

### Exact current code path

`manual_next_match` -> `begin_next_manual_match()`:

1. `flush_draft_save_sync()`;
2. `ACTIVE_SNAPSHOT_HOLDER.clear()`;
3. `ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()`;
4. `CURRENT_MATCH.begin_next_match()`;
5. publish the new blank DRAFT.

### What is safe

- A new ID is created.
- Manual counts, known items, box, condition, totals, and character are cleared.
- Current snapshot/truth holders are cleared.
- DRAFT records do not ingest Historical Shadow.
- Existing Vision settlement flow separately tests archive-before-trunk-clear and stale-shadow rejection.

### What is not safe/complete

- No Manual settlement is collected or reviewed.
- The previous Manual record is not transitioned to `FINALIZED`.
- No admitted-history entry is produced.
- No exactly-once archive assertion applies to this action.
- No reviewed truth is linked to the prediction.
- No explicit user choice exists between finalize, intentionally discard/cancel, or keep as DRAFT.
- No confirmation/undo protects an accidental click.
- Manual local predictions do not currently produce the experiment capture sidecar, so clearing the holder does not establish a useful immutable prediction/truth pair.

The fact that the UI clears is therefore insufficient. The old match remains an excluded DRAFT and the product’s real history count does not increase.

## 12. Packaged history/data ownership

### FACT

Fresh build layout contains:

```text
<package>/异环拍卖助手.exe
<package>/_internal/异环拍卖数据.json
```

`app/main.py` first checks `<BASE_DIR>/异环拍卖数据.json`, then falls back to `<PROJECT_ROOT>/异环拍卖数据.json`; in a frozen onedir build `PROJECT_ROOT` resolves to `_internal`. Both `MainViewStateProvider` and all writers receive that path.

### User impact

- Source and package naturally fork into different history files.
- A package refresh can replace the bundled data snapshot.
- Installation under a protected directory can make DRAFT/final writes fail.
- Shipping the current 34.8MB developer history as each user’s live database exposes test/legacy data and produces misleading “real” counts.

### Recommendation

Use one explicit per-user runtime data root (for example `%LOCALAPPDATA%/异环拍卖助手/data/`) and a versioned first-run seed/migration policy. The packaged dataset may be a read-only seed/reference, never the live write target.

## 13. Feature parity audit

| 0.65 / Lab capability | 0.67 status | Classification | Evidence / reason |
|---|---|---|---|
| Evidence-backed venue/box selector | Lab/business SOT has a three-venue mapping; 0.67 Manual UI ships a conflicting four-tier hard-code | `MUST_CORRECT_BEFORE_ALPHA_USABLE` | Wrong tier changes value prior; tier/box persist into history |
| Exact-state count constraints G/R | Canonical/Solver supported; UI absent | `MUST_RESTORE_BEFORE_ALPHA_USABLE` | Material state-set changes proven by parity tests |
| Full decision console / continue-stop advice | Engine output exists; Overlay hides it and lacks inputs/support | `MUST_RESTORE_BEFORE_ALPHA_USABLE` | Product criterion requires estimate/advice |
| Current bid and cost-aware lines | Lab has them; Overlay does not | `MUST_RESTORE_BEFORE_ALPHA_USABLE` | Recommendation cannot be personalized/reliable without semantics |
| Settlement + “保存并下一局” | Lab has a flow; Overlay only starts new DRAFT | `MUST_RESTORE_BEFORE_ALPHA_USABLE` | Required terminal lifecycle |
| History explorer / single-record review | Lab has browser-local/editor surface; Main disabled | `MUST_RESTORE_BEFORE_ALPHA_USABLE` | Basic traceability gate |
| Candidate coverage/degradation explanation | Engine has data; compact Overlay reduces it to generic status | `P1_REQUIRED` | User must distinguish structural reference from formal Shadow |
| Manual screenshot evidence | Visible Overlay button is disconnected | `P1_REQUIRED` if retained | Either wire a supported evidence action or remove the dead control |
| Automatic OCR/live refresh | Runtime code remains, current Alpha does not require it | `CAN_WAIT_FOR_BETA` | Explicit scope decision |
| Seats/bids/round timeline auto capture | Vision path remains, not in manual Overlay | `CAN_WAIT_FOR_BETA` | Beta automation, except manual current-bid input above |
| Settlement OCR / Warehouse / item recognition | Existing experimental/production primitives incomplete | `PARKED_BETA` | Must not contaminate truth |
| Full Lab calculator, import/export, catalog admin | Separate browser lab | `PARKED` | Not needed for first usable desktop Alpha and would broaden authority |
| Old `tactical_hud.html` as primary window | Superseded presentation host | `OBSOLETE_WITH_EVIDENCE` as a host only | Main + Overlay lifetime architecture is frozen; individual valuable capabilities are not deemed obsolete |

## 14. Empty, loading, and failure states

| State | Current UX | Readiness |
|---|---|---|
| No history | Match count can truthfully show 0 | `PASS` |
| History missing/corrupt | Status provider can throw and starve the whole Main status response | `P0/P1 boundary failure` |
| Overlay before input | Dashes + “信息不足” | `PASS`, except false “已保存草稿” |
| Solver recompute | Synchronous local calculation; no long spinner needed for normal structural solve | `PASS` for current local path |
| Shadow updating | Mascot may show thinking from presentation runtime; Overlay does not explain data mode | `P1_REQUIRED` |
| WS/native persistence unavailable | Silent reconnect; local result can remain visible | `P1_REQUIRED` |
| Solver JS initialization failure | Values can remain dashes; no user action/retry | `P1_REQUIRED` |
| Capture sidecar rejected | Correctly absent from normal product UI; internal experiment concern | `PARKED/DEBUG_ONLY` |
| No formal Analysis artifact | Fake metrics are shown | `P0_BLOCKER` |
| Shutdown | Main disables commands and cleanup is idempotent | `PASS` |

## 15. Visual and interaction readiness

### P0 visual/usability

- No observed clipping or invisible primary input in the 560x282 expanded Overlay.
- The P0 information problem is semantic: the most important decision/mode is not shown, while structural values are visually promoted as a normal P50.

### P1 interaction

- “新一局” is prominent but unsafe and has no terminal-state explanation.
- Screenshot is visible but inert.
- Desktop Pet restore control is hidden in the native system menu.
- Main disabled navigation gives no roadmap beyond “即将开放”.
- Save/sync failure is not visually distinguishable from local-only calculation.

### P2 polish

- Demo/Alpha badges and disabled sections can be refined after functional truthfulness.
- Spacing, animation, shadows, and further visual polish are not blocking.

## 16. User-visible developer/internal leakage

### PASS

- Main does not expose raw history, `CurrentMatch`, `LATEST_PAYLOAD`, OCR strings, candidate dumps, absolute paths, stack traces, or Solver input/results.
- Main DevTools and default context menus are disabled.
- Overlay shows compact product fields rather than raw JSON.

### Required cleanup

- Realistic mock business numbers/percentages are the largest product-trust leak.
- “结构参考/full or partial Shadow” should be translated into clear user copy, not hidden or replaced by a normal-looking estimate.
- Stale 0.65 metadata should be aligned before release/support, though it is not a P0 runtime problem.

## 17. Blocking matrix

### P0_BLOCKER

| Item | Current code/state | User impact | Minimal fix | User validation needed? |
|---|---|---|---|---|
| Venue/Box catalog truth and mapping | UI exposes unverified `顶级场`, beginner boxes differ from business SOT/real-session evidence, and adapter/Vision enums conflict | Wrong selection changes value prior and persists false facts; future Shadow cohorts can be contaminated | Freeze versioned evidence-backed catalog; derive all consumers from it; fail closed unknown; preserve legacy values as unverified | **Yes** — current-game venue and box UI evidence is required |
| Durable canonical data root | Frozen app writes/reads `_internal/异环拍卖数据.json` | History can fork, fail to write, or be overwritten | Per-user data SOT + explicit seed/migration + fail-soft status | Automated source/package fixture; no real match |
| Manual terminal lifecycle | `begin_next_manual_match()` saves DRAFT then clears | No finalized/archive history; prior match silently excluded | Explicit finish/review -> exactly-once FINALIZED or explicit discard -> reset | Fixture + one UI smoke; no real match |
| Formal Manual estimate/advice | Overlay supplies no history/profile and hides decision | User sees structural numbers but no formal recommendation | Supply immutable approved support profile, render degradation/action/caps, keep Overlay sole Solver owner | Deterministic fixture + source/package smoke |
| Main fake metrics | JS renders fixed business and performance numbers | Product presents invented results | Replace with honest unavailable/collecting states | Screenshot/UI assertion |
| Basic History | Records nav disabled | User cannot inspect what was saved/excluded | Read-only immutable list/detail projection | Fixture + page smoke |
| History failure containment | Provider exception can break all Main status | Overlay control can be disabled by history corruption | Isolate provider error; publish availability/reason without raw exception | Missing/corrupt-file tests |

### P1_REQUIRED

| Item | Current state | Minimal fix |
|---|---|---|
| Gold/Red count inputs | Material fields supported but absent | Add exact-count/unknown controls; preserve null vs explicit zero |
| Bid/cost/target semantics | Defaults are silent; bid absent | Expose or clearly freeze product policy; show assumptions |
| Decision-mode explanation | Generic status copy | Display “结构参考/部分覆盖/完整估值” and missing clues |
| Persistence/WS state | Silent retry and stale save copy | Native acknowledgement/correlation and readable unsaved/error state |
| Screenshot button | `capture_hud` has no DirectComposition handler | Wire a product evidence action or remove button |
| Desktop Pet discoverability | Main system menu only | Add a narrow visible show/hide entry without new business authority |
| Version consistency | Several 0.65 strings remain | Route display/build metadata to `core/version.py` |
| Accidental next match | No confirmation/undo | Terminal workflow confirmation or recoverable DRAFT action |

### P2_POLISH

- Main disabled-nav copy and roadmap treatment.
- Dashboard/demo badges after fake values are removed.
- Fine spacing/hover/transition refinements.
- More discoverable but nonessential mascot presentation controls.
- README/run.bat wording after product entry docs are consolidated.

### PARKED_BETA

- Automatic OCR and Live Vision reconnect/productization.
- Lobby scene/character/tool recognition.
- Automatic bid/seat/round timeline capture.
- Settlement OCR and Warehouse/item identity recognition.
- Automatic screenshot ingestion.
- Prediction Evaluation publication until natural contract-valid pairs exist.
- Automatic success/warning mascot binding.
- Lab catalog administration, bulk import/export, algorithm dashboards.

### ALREADY_PASS

- Fresh packaged build completes.
- Main is the `Application.Run` owner.
- Main presentation does not load Solver JS.
- Overlay remains exactly one production Solver runtime.
- Overlay hide/show reuses the same HWND/runtime.
- Desktop Pet is exactly one native layered window and does not affect Overlay.
- Main/Overlay Unicode titles are correct.
- Clean shutdown leaves no audited source/package process.
- Main bridge remains narrow and presentation-only.
- History admission/count aggregation is immutable and whitelist-only.
- Current-match field reset and Vision-path archive-before-reset protections have tests.

## 18. ALPHA_PRODUCT_USABLE_V1 gate

| Gate | Result |
|---|---|
| Packaged launch | `PASS` |
| Main/Overlay lifecycle | `PASS` |
| Manual input chain complete | `FAIL` — missing material inputs and terminal flow |
| Venue/box facts verified and consistent | `FAIL` — unverified catalog plus UI/Canonical/Solver/history drift |
| Formal Solver result/advice visible | `FAIL` — structural-only values; advice hidden/unavailable |
| No fake metrics | `FAIL` |
| Next-match lifecycle safe | `FAIL` |
| Basic history inspectable | `FAIL` |
| Errors user-readable/fail-soft | `FAIL` |
| Clean shutdown | `PASS` |
| No second Solver runtime | `PASS` |

**Final:** `ALPHA_PRODUCT_USABLE_V1 = FAIL`. The app is a functioning desktop shell and Manual structural-estimate prototype, not yet a complete playable Alpha product loop.

## 19. Recommended minimal implementation order

No cut changes Solver algorithms.

### Cut 1 — Venue/Box Catalog truth freeze and one contract

**Goal:** capture minimum current-game evidence; publish one versioned venue/tier/box/effect/cost contract; derive Manual options and normalization from it; reject unknown/mismatched pairs without rewriting legacy history.

**Regression:** evidence references/hash, closed enum parity across UI/Canonical/Vision/adapter/Solver inputs, unknown fail-closed behavior, incorrect venue-box pair rejection, no history rewrite.
**Independent commit:** yes.

### Cut 2 — Durable runtime data authority and fail-soft Main status

**Goal:** make source/package use one explicit per-user canonical history root; treat bundled history only as a versioned read-only seed; isolate missing/corrupt history from Overlay controls.

**Regression:** path resolution, first-run seed, update preservation, read/write permissions, source/package parity, corrupt/missing status, clean shutdown.
**Independent commit:** yes.

### Cut 3 — Manual terminal lifecycle vertical slice

**Goal:** add an explicit end-match review with the minimum trusted settlement facts; atomically choose FINALIZED or explicit discard/keep-DRAFT; archive exactly once; only then reset current holders/UI/match ID.

**Regression:** DRAFT -> FINALIZED transition, duplicate click idempotency, failed archive blocks reset, explicit discard reason, snapshot/truth link, no field inheritance.
**Independent commit:** yes.

### Cut 4 — Formal Manual support/advice presentation

**Goal:** feed Manual Overlay the existing immutable historical support/probability profile without moving Solver ownership, add material Gold/Red count and bid/cost policy inputs, and render decision mode/action/recommendation instead of promoting structural P50 as formal.

**Regression:** structural/partial/full mode fixtures, count-lock parity, costs/bid semantics, same Solver/runtime identity, source/package.
**Independent commit:** yes.

### Cut 5 — Truthful read-only Main data surfaces

**Goal:** first remove all fake Overview/Analysis values; then add the smallest native-owned immutable admitted/excluded History list/detail projections. No edit/import/delete/Solver replay.

**Regression:** no mock numeric metric in shipped assets, no evaluation artifact -> unavailable, admission parity, pagination/empty/error, DRAFT/finalized/excluded labels, forbidden-field scan, history failure isolation, Overlay toggle remains active, source/package.
**Independent commit:** yes.

## 20. Runtime and test evidence

### Fresh package

- PyInstaller `6.22.0`, Python `3.10.11`.
- Clean onedir build to `%TEMP%/nte-product-readiness-fresh`: `PASS`.
- Packaged Main/Overlay Unicode-title and bridge smoke: `PASS`.
- Packaged Solver startup self-test: `PASS`.
- Packaged same-Overlay-HWND hide/show: `PASS`.
- Packaged Desktop Pet smoke: first run observed a one-pixel native drag rounding variance (`[-24,-17]` vs strict `[-24,-16]`); immediate rerun passed all checks. This is test tolerance/flakiness evidence, not a product blocker.
- Packaged clean exit/no lingering audited process: `PASS`.

### Source runtime

- Source Main presentation/Solver startup: `PASS`.
- Source same-Overlay-HWND hide/show: `PASS`.
- Source Desktop Pet rerun: `PASS`.
- Source clean exit/no lingering audited process: `PASS`.
- Actual expanded Overlay accessibility/visual inspection: controls visible, no P0 clipping; decision/advice absent as described.

### Focused source tests

Command covered Main lifecycle, Desktop Pet, MainViewStateProvider/admission, Manual Alpha, count parity, match reset, HUD wording, in-auction payload, costs, Historical Shadow, and shared-core binding.

- **80 tests run: 78 passed, 2 failed.**
- Failure 1: `test_manual_alpha` expects legacy raw-string `knownItems`; current Canonical v7 intentionally stores a structured list and both adapters flatten it for Solver. This is a stale fixture assertion.
- Failure 2: `test_hud_wording_and_loading_direction` contains a legacy/encoding-sensitive expected text that does not match the current user-facing action copy.
- These two failures were present at the audited checkpoint; no attempt was made to fix the explicitly out-of-scope legacy fixture debt.
- Manual DRAFT exclusion and next-match field reset tests passed.
- Vision settlement archive-before-reset and stale-shadow rejection tests passed.
- Main history admission/cache/forbidden-boundary tests passed.

### Venue/box read-only audit evidence

- Git provenance traced the top-venue concept from documentation (`b74fd5de`) to adapters (`4ee1229c`) to the Manual UI hard-code (`aefa09a2`); no current-game evidence reference was found for that chain.
- Current business SOT, Vision aliases, adapters, Manual selectors, Canonical records, Solver constants, and the 290-record history were enumerated independently.
- A deterministic, read-only Solver probe confirmed identical candidate-state count but tier-dependent formal quantiles; a box-only probe in the current empty-record Manual path confirmed no structural change.
- No history file, catalog, Solver source, UI source, or runtime state was modified by these probes.

### Data integrity during audit

- Root history SHA-256 after all runtime checks: `6a9695f8ef44058f2c369ac1bd1407a6306a327b63d1c0a160631d5348ed699a`.
- No product source or tracked data file was modified by runtime tests.

## 21. Final verdict

`NOT_READY_FOR_PRODUCT_ALPHA_HANDOFF`

The correct next action is **Cut 1: freeze an evidence-backed Venue/Box Catalog Contract and make it the only mapping authority**. Do not delete `顶级场`, invent beginner boxes, rewrite history, or change Solver constants until current-game evidence has resolved the catalog. After that, proceed to durable data ownership and Manual lifecycle; do not resume algorithm work, OCR, Prediction Evaluation publication, or visual redesign first.
