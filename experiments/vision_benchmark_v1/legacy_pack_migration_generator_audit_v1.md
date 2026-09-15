# Legacy 57-Slot Migration & Generator Ownership Audit v1

- Audit date: 2026-08-20
- Mode: read-only structural migration and ownership audit
- Geometry contract baseline: commit `657e4b6d8b6d0bef7e8506ad58016d422227e50b`
- Scope: the 57 REP slots in `dataset_inventory.json` / `pseudo_labels.json`, saved source images/crops, and existing source/scene/ROI/item-segmentation components
- Excluded: no migration, crop generation, transform repair, model rerun, aliasing, production changes, or Benchmark score changes

## 0. Evidence rules

**FACT** — The legacy pack contains 57 slots across five representative sources: REP-01=15, REP-02=20, REP-03=8, REP-04=10, REP-05=4. Every saved crop has the same pixel width/height as its legacy bbox extent.

**FACT** — Geometry Contract v1 requires an eligible stored source, exact source dimensions, a `source_pixel` inventory ROI, one opaque physical `instanceId`, one source-relative bbox, an explicit crop-to-instance review state, and exactly one queue slot per physical instance.

**FACT** — No saved Benchmark-specific generator, Gemini prompt/request, coordinate transform, or authoritative BM1↔REP slot mapping exists. Semantic IDs such as `red_xxx` are observations, not physical instance identity.

**INFERENCE** — The classifications below use only the stored source, legacy bbox/crop, visible parent ownership, and known source/coordinate defects. `MIGRATABLE_*` means structurally salvageable into a new contract record; it does not promote canonical identity, quality, or truth.

**RECOMMENDATION** — A legacy slot is not counted as migratable merely because its semantic label sounds plausible or its crop dimensions match the bbox.

## 1. 57-slot migration classification

### 1.1 REP-01 — settlement source (15 slots)

Source: `assets/settlement_frames/sec_488.jpg`

**FACT** — The stored source is an eligible settlement inventory scene in source-pixel space. Several legacy bboxes, however, cut one large item into fragments or contain two neighboring cards.

| REP/slot | Legacy bbox | Classification | Physical parent group | Reason |
|---|---|---|---|---|
| REP-01/s01 | `[1408,256,1536,384]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown: small gray card / 九格小食 overlap | Crop contains more than one physical card; semantic agreement cannot make the bbox unique. |
| REP-01/s02 | `[1744,256,1872,448]` | `MIGRATABLE_AFTER_GROUPING` | `REP01-P-STATUE` | Main region of the same large gold statue also fragmented by s06/s13/s14. |
| REP-01/s03 | `[1744,480,1872,608]` | `MIGRATABLE_AFTER_GROUPING` | `REP01-P-NEW-FLAVOR` | Lower parent card plus three neighboring 1×1 cards; same large parent as s11/s12. |
| REP-01/s04 | `[1600,448,1728,576]` | `MIGRATABLE_AS_IS` | `REP01-P-SLIME` | One dominant, spatially distinct slime card; no other legacy slot maps to it. |
| REP-01/s05 | `[1424,384,1552,512]` | `MIGRATABLE_AS_IS` | `REP01-P-PAINTING` | One dominant painting card with clear source-relative placement. |
| REP-01/s06 | `[1664,288,1728,416]` | `MIGRATABLE_AFTER_GROUPING` | `REP01-P-STATUE` | Left rock fragment of the same large statue represented by s02/s13/s14. |
| REP-01/s07 | `[1632,576,1696,672]` | `MIGRATABLE_AS_IS` | `REP01-P-PHONE` | One narrow phone card; no duplicate parent representation. |
| REP-01/s08 | `[1776,448,1840,512]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown: gem / soap boundary | Crop contains two adjacent 1×1 items; parent ownership is not contract-grade. |
| REP-01/s09 | `[1440,528,1504,576]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown: trophy / blue ticket boundary | Bbox crosses the right edge of the trophy into the neighboring blue item. |
| REP-01/s10 | `[1408,496,1472,592]` | `MIGRATABLE_AS_IS` | `REP01-P-TROPHY` | One dominant narrow trophy card; independent from the ambiguous s09 mapping. |
| REP-01/s11 | `[1728,560,1792,624]` | `MIGRATABLE_AFTER_GROUPING` | `REP01-P-NEW-FLAVOR` | Interior fragment of the same 3×3 large parent as s03/s12. |
| REP-01/s12 | `[1744,608,1808,672]` | `MIGRATABLE_AFTER_GROUPING` | `REP01-P-NEW-FLAVOR` | Lower fragment of the same 3×3 large parent as s03/s11. |
| REP-01/s13 | `[1680,256,1744,320]` | `MIGRATABLE_AFTER_GROUPING` | `REP01-P-STATUE` | Upper-left fragment of the same 4×5 statue parent. |
| REP-01/s14 | `[1696,368,1760,432]` | `MIGRATABLE_AFTER_GROUPING` | `REP01-P-STATUE` | Rock/foot fragment of the same 4×5 statue parent. |
| REP-01/s15 | `[1472,480,1536,544]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown: painting / round-table boundary | Bbox center/majority and visible neighbor do not yield one unambiguous parent geometry. |

**INFERENCE** — REP-01 contributes four directly migratable instances plus two known grouped parents. Seven legacy slots collapse to two parents, producing five known duplicate fragments.

### 1.2 REP-02 — fixed inventory crop (20 slots)

Source: `core/settlement_items_crop.png`

**FACT** — The stored source is a 307×329 inventory crop with source-local bboxes. It visibly contains distinct repeated instances: s03/s04 are separate black bike-like objects; s12/s13 are separate diamond cells; s14/s15 are separate orb cells. Equal semantic labels do not make these duplicates.

| REP/slot | Legacy bbox | Classification | Physical parent group | Reason |
|---|---|---|---|---|
| REP-02/s01 | `[92,100,230,230]` | `MIGRATABLE_AS_IS` | `REP02-P-FISH` | Complete, unique large fish card. |
| REP-02/s02 | `[200,10,275,80]` | `MIGRATABLE_AS_IS` | `REP02-P-PAINTING` | Unique painting card; minor neighbor edge does not obscure ownership. |
| REP-02/s03 | `[10,100,85,155]` | `MIGRATABLE_AS_IS` | `REP02-P-BIKE-A` | Complete first black bike-like physical instance. |
| REP-02/s04 | `[170,240,245,295]` | `MIGRATABLE_AS_IS` | `REP02-P-BIKE-B` | Spatially separate second bike-like instance; legitimate multiplicity. |
| REP-02/s05 | `[95,45,145,85]` | `MIGRATABLE_AS_IS` | `REP02-P-DISC-UPPER` | One dominant round item; semantic name may remain only an observation. |
| REP-02/s06 | `[10,210,85,265]` | `MIGRATABLE_AS_IS` | `REP02-P-COCKTAIL-LEFT` | One distinct cocktail card. |
| REP-02/s07 | `[225,155,275,220]` | `MIGRATABLE_AS_IS` | `REP02-P-COCKTAIL-RIGHT` | Separate cocktail card on the right. |
| REP-02/s08 | `[95,240,145,295]` | `MIGRATABLE_AS_IS` | `REP02-P-DRONE` | One distinct round mechanical item. |
| REP-02/s09 | `[10,155,60,205]` | `MIGRATABLE_AS_IS` | `REP02-P-CAMERA` | One distinct camera/polaroid card. |
| REP-02/s10 | `[225,105,275,150]` | `MIGRATABLE_AS_IS` | `REP02-P-DISC-RIGHT` | One distinct right-side round item. |
| REP-02/s11 | `[65,155,90,180]` | `MIGRATABLE_AS_IS` | `REP02-P-TEARDROP` | Single 1×1 parent is unambiguous in the fixed source; Geometry Contract fixture already validates this structural binding without claiming identity truth. |
| REP-02/s12 | `[145,45,170,70]` | `MIGRATABLE_AS_IS` | `REP02-P-DIAMOND-A` | First of two visibly separate diamond cells. |
| REP-02/s13 | `[145,70,170,95]` | `MIGRATABLE_AS_IS` | `REP02-P-DIAMOND-B` | Second diamond cell at a different source position. |
| REP-02/s14 | `[65,180,90,205]` | `MIGRATABLE_AS_IS` | `REP02-P-ORB-A` | First distinct orb cell. |
| REP-02/s15 | `[35,75,60,100]` | `MIGRATABLE_AS_IS` | `REP02-P-ORB-B` | Second orb cell at a different source position. |
| REP-02/s16 | `[10,265,40,295]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown bottom-left parent | Crop retains only a small edge/fragment; complete parent geometry is not established. |
| REP-02/s17 | `[250,240,275,265]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown lower-right parent A | Crop is essentially card background and does not bind the described item. |
| REP-02/s18 | `[250,265,275,295]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown lower-right parent B | Crop is essentially purple background; the physical parent cannot be admitted from this bbox. |
| REP-02/s19 | `[65,265,90,295]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown lower-row parent | Crop is background/edge content rather than a reviewable instance. |
| REP-02/s20 | `[115,10,175,30]` | `MIGRATABLE_AS_IS` | `REP02-P-TOP-BOARD` | Thin but uniquely bound top-row board-like instance. |

**INFERENCE** — REP-02 contributes 16 contract-grade physical instances. The four remaining source-visible candidates may be reconstructable from the source, but their legacy bboxes are not migration evidence and are not counted.

### 1.3 REP-03 — fixed live-auction grid crop (8 slots)

Source: `build/live_auc/t078_grid.png`

**FACT** — The 580×374 stored source is already an inventory grid crop. All eight bboxes are source-local, remain within the source, and each has one dominant physical parent. Neighbor edges in s02/s03 do not create duplicate parent ownership.

| REP/slot | Legacy bbox | Classification | Physical parent group | Reason |
|---|---|---|---|---|
| REP-03/s01 | `[15,30,175,190]` | `MIGRATABLE_AS_IS` | `REP03-P-ARMOR` | Unique large armor instance. |
| REP-03/s02 | `[345,15,500,85]` | `MIGRATABLE_AS_IS` | `REP03-P-MOTORCYCLE` | One dominant horizontal motorcycle-like instance. |
| REP-03/s03 | `[235,90,390,160]` | `MIGRATABLE_AS_IS` | `REP03-P-CHARGER` | One dominant horizontal charger-like instance. |
| REP-03/s04 | `[180,15,235,140]` | `MIGRATABLE_AS_IS` | `REP03-P-TROPHY` | One narrow trophy instance. |
| REP-03/s05 | `[235,15,290,85]` | `MIGRATABLE_AS_IS` | `REP03-P-ORB-A` | One distinct 1×1 orb. |
| REP-03/s06 | `[290,15,345,85]` | `MIGRATABLE_AS_IS` | `REP03-P-ORB-B` | Separate adjacent 1×1 orb. |
| REP-03/s07 | `[405,90,455,160]` | `MIGRATABLE_AS_IS` | `REP03-P-BOTTLE` | One distinct bottle instance. |
| REP-03/s08 | `[515,15,565,85]` | `MIGRATABLE_AS_IS` | `REP03-P-WRAPPED-ITEM` | One distinct wrapped-item instance. |

### 1.4 REP-04 — valid scene, invalid coordinate provenance (10 slots)

Source: `assets/video_frames/sec_210.jpg`

**FACT** — The stored 1920×1080 desktop source contains an inventory in the game window, but all legacy REP-04 bboxes occupy x=780..940 and point into unrelated desktop content when applied as source pixels. No saved transform identifies their true coordinate basis.

| REP/slot | Legacy bbox | Classification | Physical parent group | Reason |
|---|---|---|---|---|
| REP-04/s01 | `[830,275,875,365]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Bbox coordinate basis is not the stored source-pixel space. |
| REP-04/s02 | `[780,380,825,440]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Same source/coordinate mismatch. |
| REP-04/s03 | `[790,255,830,295]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Same source/coordinate mismatch. |
| REP-04/s04 | `[790,305,830,365]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Same source/coordinate mismatch; known queue defect. |
| REP-04/s05 | `[875,255,895,295]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Same source/coordinate mismatch; known queue defect. |
| REP-04/s06 | `[900,255,940,320]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Same source/coordinate mismatch. |
| REP-04/s07 | `[900,355,940,420]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Same source/coordinate mismatch. |
| REP-04/s08 | `[875,365,900,410]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Same source/coordinate mismatch; known queue defect. |
| REP-04/s09 | `[875,410,900,450]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Same source/coordinate mismatch; known queue defect. |
| REP-04/s10 | `[875,305,900,365]` | `NEEDS_GEOMETRY_RECONSTRUCTION` | unknown | Same source/coordinate mismatch. |

**RECOMMENDATION** — Do not infer a window offset, scale, or DPI transform. If this source is reused in a future pack, detect/review fresh source-pixel instances and treat them as new v2 records.

### 1.5 REP-05 — ineligible source (4 slots)

Source: `build/live_fail/t004.jpg`

**FACT** — The source is a match-entry confirmation/modal scene, not a legal inventory scene. No physical inventory instance exists at the four bboxes.

| REP/slot | Legacy bbox | Classification | Physical parent group | Reason |
|---|---|---|---|---|
| REP-05/s01 | `[1400,300,1550,450]` | `SOURCE_INELIGIBLE` | none | Source eligibility fails before bbox/crop review. |
| REP-05/s02 | `[1550,300,1700,450]` | `SOURCE_INELIGIBLE` | none | Source eligibility fails before bbox/crop review. |
| REP-05/s03 | `[1400,450,1480,530]` | `SOURCE_INELIGIBLE` | none | Source eligibility fails before bbox/crop review. |
| REP-05/s04 | `[1480,450,1560,530]` | `SOURCE_INELIGIBLE` | none | Source eligibility fails before bbox/crop review. |

### 1.6 Classification totals

| Classification | Count | Denominator | Meaning |
|---|---:|---:|---|
| `MIGRATABLE_AS_IS` | 28 | 57 | Structurally one source-relative parent per legacy slot; identity remains nullable/unverified. |
| `MIGRATABLE_AFTER_GROUPING` | 7 | 57 | Seven slots belong to two known large parent instances. |
| `NEEDS_GEOMETRY_RECONSTRUCTION` | 18 | 57 | Legal or potentially legal source, but legacy bbox/coordinate evidence cannot be admitted. |
| `SOURCE_INELIGIBLE` | 4 | 57 | No legal inventory scene. |
| `INSUFFICIENT_EVIDENCE` | 0 | 57 | All rows can be assigned to a stronger structural category; this does not mean their identities are known. |

## 2. Physical item-instance count

### 2.1 Known duplicate fragments

| Parent group | Member slots | Legacy row count | Physical instances | Known surplus fragments |
|---|---|---:|---:|---:|
| `REP01-P-NEW-FLAVOR` | s03, s11, s12 | 3 | 1 | 2 |
| `REP01-P-STATUE` | s02, s06, s13, s14 | 4 | 1 | 3 |
| **Total** |  | **7** | **2** | **5** |

**FACT** — Geometry Contract v1 rejects multiple queue slots that reference the same physical `instanceId`.

**INFERENCE** — The known duplicate-fragment count is five, defined as surplus legacy rows beyond one row per known parent. It is a lower bound: ambiguous NGR rows such as REP-01/s09 or s15 might also overlap already represented parents, but the saved evidence is insufficient to count them as duplicates.

### 2.2 Legitimate repeated instances

**FACT** — REP-02/s03 and s04 are spatially separate physical objects despite sharing one semantic ID. The same is true for s12/s13 and s14/s15. These are legitimate multiple instances and must receive different future `instanceId` values.

### 2.3 Count result

- **FACT:** legacy slots = 57.
- **INFERENCE:** contract-grade confirmable physical instances = 30: 28 direct instances plus 2 grouped parents.
- **INFERENCE:** known duplicate fragments = 5 surplus rows within the two parent groups.
- **FACT/INFERENCE:** 22 rows cannot use their legacy geometry: 18 require fresh geometry reconstruction and 4 have an ineligible source.
- **INFERENCE:** the total physical-instance contribution behind those 22 rows is unknown and is intentionally not guessed.

## 3. Generator ownership audit

### 3.1 Existing components

| Component | What it can provide | Ownership limitation |
|---|---|---|
| `core/live_capture.py` + `core/window_capture.py` | Game-client capture primitive and fallback desktop capture | `_grab_game_or_desktop` returns only pixels, discards the `printwindow/mss` source label, and makes desktop fallback indistinguishable downstream. It does not freeze a benchmark snapshot/hash/provenance record. |
| `core/vision_pipeline.py` | Scene lifecycle, settlement detection, in-auction gate, and a board-readiness edge-density gate | Stateful/hysteretic runtime orchestration; results depend on previous frames and OCR state. It does not persist exact model input or create stable physical instance identity. |
| `core/roi_scaler.py` | Deterministic normalized ROI resolved through a 16:9 viewport into current-frame pixels | Good proposal primitive, but Benchmark must persist the resolved source-pixel ROI, source dimensions and primitive version; normalized coordinates alone are not provenance. |
| `core/warehouse_vision.py` | Grid measurement, occupied-cell grouping, source-frame `(x,y,w,h)` boxes, temporal track proposals and candidate evidence | `trackId` is a run-local counter, not a stable benchmark `instanceId`; grouping is heuristic/stateful and cannot be authoritative without admission review. Output bbox format also differs from Contract v1 xyxy. |
| `core/settlement_item_recognizer.py` | Settlement ROI, cell occupancy, rarity and source-relative geometry proposals | Current segmentation deliberately allows only `(4×4)` and `(1×3)` merges, then emits other occupied cells separately. Its own regression prints 56 predictions versus 23 GT items with 41 splits while only forbidding merges. It would reproduce large-parent fragmentation if used directly as owner. |
| `experiments/vision_benchmark_v1/` | Geometry schema, validator, fixtures and legacy artifacts | No candidate-source selector, snapshot owner, instance generator, crop materializer or exact model-input recorder exists. |

**FACT** — Production provides useful primitives but no component currently satisfies the full Benchmark ownership contract.

### 3.2 Ownership options

| Option | Reproducibility | Production pollution/coupling | Geometry provenance | Instance semantics | Exact model input | Testability | Verdict |
|---|---|---|---|---|---|---|---|
| A. Direct production vision output | Medium/low: stateful and version-sensitive | High; benchmark becomes coupled to the system under test | Partial | Heuristic `trackId`/cell blobs, not authoritative | Not currently persisted | Existing tests, but runtime state complicates replay | Reject as sole owner |
| B. Production primitive + independent experiment adapter | High if all inputs/versions are frozen | Low; production remains proposal-only | Strong: adapter resolves/persists source pixels | Adapter can own stable parent grouping | Yes, adapter can save exact payloads | High: deterministic fixtures and replayable snapshots | **Recommended** |
| C. Completely independent benchmark generator | Potentially high | None | Must be rebuilt from scratch | Risks duplicating segmentation bugs differently | Yes | High in isolation | Reject as primary; duplicates production primitives and drifts |
| D. Manual-only generator | High provenance per reviewed case | None | Strong but expensive | Strong with trained review | Yes | Low throughput | Use as a review gate, not the generator |

**RECOMMENDATION** — Choose **B: production primitive + independent experiment adapter**. Production components may propose scene, ROI and item regions; a standalone experiment adapter must own snapshot freezing, stable instance creation, parent grouping, contract emission, validation, deterministic crop materialization and queue admission.

## 4. Minimal future admission pipeline and owners

| Step | Owner | Output and authority |
|---|---|---|
| 1. Candidate source | Benchmark experiment adapter, optionally consuming capture primitives | Candidate pixels plus capture-mode/window metadata; no admission yet. |
| 2. Scene eligibility | Adapter admission gate; production scene pipeline supplies evidence | Explicit eligible/ineligible decision. Ambiguous scenes require manual/independent review; fail closed otherwise. |
| 3. Fixed source snapshot | Adapter | Immutable image bytes, content hash, source dimensions, capture provenance and source ID. This becomes the coordinate SOT. |
| 4. Inventory ROI | Production `ROIScaler`/scene-specific primitive proposes; adapter resolves and persists | One reviewed `source_pixel` ROI bound to the fixed snapshot. No normalized/window/DPI coordinate leaks into the contract. |
| 5. Physical item proposals | Warehouse or settlement segmentation primitives | Candidate cell sets/bboxes only; run-local `trackId` is retained as proposal provenance, never instance identity. |
| 6. Parent-instance resolution | Adapter physical-instance resolver plus review gate | Decides which cells/bboxes are one physical item. This is the only authority allowed to collapse or separate proposals. |
| 7. Geometry contract draft | Adapter | Creates opaque `instanceId`, source-relative bbox, optional footprint, nullable canonical ID and observation provenance. |
| 8. Structural/provenance validation | Standalone Geometry Contract validator | Fail closed before crop work on source existence/dimensions, eligibility, coordinate space, ROI, bbox, uniqueness and one-parent semantics. |
| 9. Crop materialization | Adapter | Deterministic `fixed_source[bbox]`; records exact crop bytes/hash and materializer version. |
| 10. Final admission validation | Standalone validator + content review gate | Verifies crop dimensions, explicit queue→instance reference, one instance→one queue slot, and reviewed crop-instance binding. |
| 11. Benchmark queue | Adapter pack builder | Publishes only fully admitted instances and archives the exact per-model payload. |

### 4.1 Direct ownership answers

**RECOMMENDATION — Who creates `instanceId`?** The independent experiment adapter, only after the physical parent has been resolved. It must not reuse a local ordinal, semantic label, canonical item ID, or production `trackId`.

**RECOMMENDATION — Who decides that two bboxes belong to one physical instance?** The adapter's parent-instance resolver/admission reviewer. Production segmentation supplies proposals; the validator enforces the declared result but does not infer grouping from pixels.

**RECOMMENDATION — Who owns `canonicalItemId`?** A separate catalog-resolution stage backed by human or independent reliable evidence. It remains `null` when not proven. The geometry generator has no authority to infer it from rarity, shape, model text or a unique-looking label.

**RECOMMENDATION — Who owns `observationLabel`?** Each model/observer writes its own observation record. Observation text never creates or joins a physical instance.

**RECOMMENDATION — Where does the validator fail closed?** Twice: a structural/provenance preflight before crop materialization, then the full crop/queue admission check before queue publication. The current validator already contains the relevant hard gates; a future adapter must expose the preflight/final sequencing without changing legacy data in place.

## 5. Legacy 57-slot disposition

### 5.1 Strategy decision

**RECOMMENDATION — `FREEZE_V1_BUILD_V2`.**

Reasons:

1. Benchmark v1 is already `NOT_VALID_FOR_MODEL_ACCURACY`; mutating its slot topology would destroy the provenance needed to understand previous GPT/Gemini audits.
2. Only 28 rows are direct structural candidates, and seven more require a topology change from seven slots to two instances.
3. Eighteen rows require new geometry rather than migration, and four sources are ineligible.
4. The v1 semantic namespace, prompt/input provenance and BM1↔REP mapping remain non-authoritative even when geometry is salvageable.
5. The 30 contract-grade instance candidates can be re-admitted as v2 candidates using the new owner/pipeline, but that is a new audited build—not an in-place migration or automatic truth promotion.

**RECOMMENDATION** — Preserve v1 byte-for-byte as a forensic/model-agreement artifact. Build v2 from fixed sources through the independent adapter; allow v1 source/slot references only as provenance links.

## 6. Final summary

1. 57-slot classes: `MIGRATABLE_AS_IS=28`, `MIGRATABLE_AFTER_GROUPING=7`, `NEEDS_GEOMETRY_RECONSTRUCTION=18`, `SOURCE_INELIGIBLE=4`, `INSUFFICIENT_EVIDENCE=0`.
2. Confirmable physical instances: 30 known; the contribution behind the remaining 22 rows is unknown and not guessed.
3. Known duplicate fragments: 5 surplus legacy rows across two large REP-01 parents.
4. Legacy source/geometry that cannot be admitted directly: 22 rows—18 require fresh geometry, 4 are permanently source-ineligible.
5. Generator owner: option B, production primitives plus a standalone experiment admission adapter; production outputs are proposal evidence only.
6. Owner split: adapter freezes source/creates instance IDs/resolves parents/builds crops and queues; production proposes scene/ROI/segments; catalog review owns canonical ID; model runners own observation labels; validator fails closed pre-crop and pre-queue.
7. Legacy strategy: `FREEZE_V1_BUILD_V2`.
8. If only one next action is allowed: implement one vertical slice of the independent experiment adapter—one known-good source snapshot through scene/ROI/parent resolution into a validated v2 contract—without importing or rewriting the 57-slot pack.
