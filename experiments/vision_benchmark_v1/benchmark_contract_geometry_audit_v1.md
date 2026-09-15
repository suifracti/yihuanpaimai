# Vision Benchmark v1 Contract & Geometry Root-Cause Audit

- Audit date: 2026-08-20
- Audit type: read-only, post-unblinding contract and geometry audit
- Scope: Benchmark v1 generation artifacts, slot/crop geometry, Gemini observation contract, identifier namespaces, and metric validity
- Excluded actions: no pack regeneration, no prediction changes, no score recomputation, no pseudo-label/truth/solver/Main Window changes

## 0. Evidence boundary and audit limitations

**FACT** — The repository snapshot contains the Benchmark v1 artifacts (`manifest.json`, `dataset_inventory.json`, `pseudo_labels.json`, Gemini outputs, GPT queue/reviews, crops and audit outputs), but no Benchmark-specific representative-selection script, crop-generation script, Gemini request code, saved Gemini prompt, model/version record, or coordinate-transform configuration was found. The entire `experiments/vision_benchmark_v1/` directory is currently untracked and has no Git history in this repository.

**FACT** — `benchmark_integrity.json` records zero independent verified slots and classifies all 43 original annotations as Gemini-derived. `score.json` explicitly says `INSUFFICIENT_INDEPENDENT_TRUTH_DO_NOT_REPORT_ACCURACY`.

**INFERENCE** — Where this report describes how a crop was probably created or what Gemini probably received, it is an inference from artifact structure, timestamps, exact pixel geometry, and model-output behavior. It is not a recovered implementation trace.

**RECOMMENDATION** — Treat the missing generator, prompt, model version, input-payload manifest, and coordinate transform as a reproducibility defect in Benchmark v1. Do not retroactively describe inferred behavior as code fact.

## 1. Actual slot contract

### 1.1 Contract visible in stored artifacts

**FACT** — `manifest.json` defines image-level records only: `benchmarkId`, `imagePath`, `warehouseRegion`, counts and difficulty metadata. It does not define a slot schema.

**FACT** — The effective slot schema appears in `dataset_inventory.json` and `pseudo_labels.json`. Each slot contains a local ordinal (`sXX`), semantic `name/itemId/quality`, a rectangular `[x1,y1,x2,y2]` bbox, Top-K/confidence metadata, and later a crop path. It contains no grid row/column, segmentation mask, parent item, canonical catalog ID, stable physical-instance ID, bbox coordinate-space tag, source dimensions, viewport origin, scale, or transform.

**FACT** — REP-02 explicitly distinguishes spatially separate instances with the same semantic item ID, for example `律动单车A/B`, `霞红钻A/B`, and `幽灵态A/B`. Thus duplicate semantic identities are allowed when they are separate visible objects.

**FACT** — The queue contract says only: read `cropRelativePath` plus catalog/gallery and output Top-3 and quality. It does not say “identify the bbox-center parent item”, “identify the largest overlapping item”, or “identify a grid cell”.

**INFERENCE** — The intended Benchmark v1 slot is best described as: **one alleged visible item instance produced by the Gemini/representative extraction pass, represented by a model-authored bbox and semantic label**. It is not a physical inventory cell, not a segmentation region, and not formally a bbox-center-to-parent relation. It is also not a reliable detected object, because the stored label and bbox are sometimes bound to different objects.

### 1.2 Large-item duplicate slots

| Source | Slots | Geometry result | Interpretation |
|---|---|---|---|
| REP-01 | s03, s11, s12 | All bboxes/centers fall within different parts of the same 3×3 `新口味上市！` card | One parent instance was fragmented/re-labelled as multiple slots |
| REP-01 | s06, s13 | Both bboxes/centers fall within the same 4×5 `乔望尼金雕像` card | One parent instance was fragmented/re-labelled as multiple slots |
| REP-01 | s15 | Bbox center is inside `艺术画「深林」`; the adjacent table enters only at an edge | Label↔bbox/neighbor binding error |

**FACT** — The stored schema has no `parentInstanceId`, occupied-cell set, overlap ownership, non-maximum suppression result, or instance dedup key. Nothing prevents several small bboxes from being placed inside one large card.

**INFERENCE** — The repeated slots are **not** a contract-permitted decomposition of a large item. The other REP-02 `A/B` examples show how true multiple instances are represented. REP-01 instead mixes item-instance counting with local cell/feature-sized rectangles. This is a pack-construction/extraction defect enabled by missing parent-instance grouping and dedup/occupancy validation.

**RECOMMENDATION** — Future slot contracts should make one physical item instance the atomic unit and bind it to one stable source-relative geometry record. Multi-cell size belongs to the item instance; it must not create child slots.

## 2. Root cause of the eight invalid crop-pack slots

### 2.1 Earliest failure in the chain

**FACT** — REP-04 maps to `BM1-08 / assets/video_frames/sec_210.jpg`. The stored image is a 1920×1080 full-desktop screenshot. The usable game inventory is in the game window on the far right, while the manifest declares `warehouseRegion={x:740,y:200,w:260,h:450}` and the ten REP-04 bboxes occupy x=780..940, y=255..450. Those coordinates point into the unrelated Codex/browser content in the stored full image, not the inventory.

**FACT** — REP-05 maps to `BM1-11 / build/live_fail/t004.jpg`. The stored 1920×1080 image is a match-entry confirmation/modal scene with the assistant HUD; it does not contain the claimed inventory object set. The four REP-05 bboxes occupy x=1400..1700, y=300..530 and therefore crop modal/HUD/background content.

**FACT** — All 57 saved crop dimensions exactly equal their recorded bbox extents (`cropWidth=x2-x1`, `cropHeight=y2-y1`). The eight known invalid queue crops are therefore faithful raw slices of invalid source/bbox pairs; the crop stage did not discover or correct targets.

**FACT** — The schemas contain no coordinate-space name, original inference image dimensions, viewport/window origin, resize factor, DPI factor, or transform matrix. They also contain no source eligibility check or `containsInventory` assertion.

**INFERENCE** — REP-04 is a coordinate-space/source-binding failure: a bbox/ROI generated in another view or local coordinate basis was reused directly against the saved full-desktop screenshot. The available artifacts do not prove whether the missing transform was window offset, resize, or both; there is no positive evidence that Windows DPI alone caused it.

**INFERENCE** — REP-05 fails even earlier: source selection admitted a non-inventory confirmation scene, after which semantic slots and bboxes were still manufactured/attached. Scaling a REP-05 bbox cannot recover an item that is absent from the source.

**INFERENCE** — The earliest common root is **absence of an enforced source-eligibility and source-relative geometry contract at representative admission**. REP-04 and REP-05 are two variants of that same missing gate: wrong coordinate basis versus wrong scene.

### 2.2 Minimal root-cause chain

1. **FACT — Source selection:** heterogeneous full-desktop, inventory-crop, game-window, settlement, and non-inventory modal images were accepted as equivalent representative inputs.
2. **FACT — Coordinate space:** only raw integer bboxes were stored; no transform/provenance was stored.
3. **INFERENCE — Bbox generation/binding:** semantic detections and rectangles were accepted without proving that each rectangle encloses the named item in the saved source.
4. **FACT — Crop extraction:** raw bbox coordinates were sliced directly; all 57 crops exactly match bbox dimensions.
5. **FACT — Manifest:** REP-04 is typed as an auction warehouse grid even though its ROI is wrong in the stored full-desktop source; REP-05 is admitted despite no inventory. The original manifest also has stale `hasIndependentGroundTruth` declarations contradicted by the later integrity audit.
6. **FACT — Blind queue:** source path, bbox and already-created crop were copied forward, with no geometry-validity field. Eight defects reached GPT unchanged.

**RECOMMENDATION** — The first correction point should be before bbox generation/cropping: reject a source unless the exact stored pixel image, inventory ROI, coordinate basis, dimensions, and transform are fixed and machine-validated.

## 3. Why Gemini frequently selected neighboring items

### 3.1 What input can actually be established

**FACT** — The saved `gemini_blind_predictions.json` contains `BM1-*/slot_*`, Top-1/Top-3 and confidence, but no source path, bbox, crop path, prompt, request payload, or model version. The later `pseudo_labels.json` adds REP source paths, bboxes and crop paths.

**FACT** — The saved REP crops were created at the same expansion timestamp as `dataset_inventory.json`/the updated `pseudo_labels.json`, after the original 43-slot Gemini blind file existed. No saved Gemini prompt or invocation log establishes that Gemini was shown those tight crops.

**FACT** — The GPT queue, in contrast, explicitly supplies the tight crop plus catalog/gallery. It supplies bbox/source metadata but its instruction does not define the target as the bbox-center parent.

**INFERENCE** — The strongest artifact-consistent reconstruction is that the representative/Gemini pass saw a full source image or an inventory-context view, enumerated semantic objects and bboxes, and the pack builder subsequently materialized tight crops from those bboxes for GPT. Gemini probably did not classify the same saved tight crop later shown to GPT. Whether a bbox overlay or textual coordinates were included cannot be recovered.

### 3.2 Pattern among the eight true target/item conflicts

| Pattern | Slots | Evidence |
|---|---:|---|
| Bbox is a fragment inside a large parent; Gemini label points to another/adjacent small object | REP-01 s03, s06, s11, s12, s13 (5) | Centers remain inside `新口味上市！` or `乔望尼金雕像`; labels name Heart Hunter, potion, bowl, candy or 月白沙 |
| Bbox mixes a parent edge with a neighbor; Gemini selects the neighbor | REP-01 s09, s15; REP-02 s18 (3) | Center/majority belongs to `环的冥思`, `艺术画「深林」`, or `阿瑞斯动感单车`; the selected ticket/table/marble is adjacent |

**FACT** — Five of eight conflicts are repeated fragments of two large parent items. The remaining three contain neighbor spillover or lie within a larger card while an adjacent object is visually salient.

**INFERENCE** — The dominant cause is **multi-stage contract failure**, not an isolatable pure model-vision error:

- the Gemini semantic label and its bbox were not validated as one bound object instance;
- a “slot” did not have an archived center/overlap/parent selection rule;
- tight downstream crops preserved the wrong rectangle and often removed the context needed to recover the original intended object;
- GPT and Gemini consequently did not necessarily solve the same target-selection task.

**INFERENCE** — Prompt ambiguity is likely a contributor because no stored contract says which object owns an overlapping bbox. Crop construction is also a contributor because it blindly freezes that ambiguity. The current evidence cannot quantify an independent Gemini vision-error component because the actual Gemini input and prompt are absent.

**RECOMMENDATION** — Do not use these eight conflicts to rank the models. First make label↔instance↔bbox identity a validated invariant and archive the exact per-model payload.

## 4. Identity and slot namespaces

### 4.1 Namespace lineage

| Namespace | Created/recorded by | Intended layer | Audit classification |
|---|---|---|---|
| `imageN-R-C` | `assets/catalog_065.json` and catalog screenshots | Canonical catalog item identity, with official name, quality, footprint and value | **Required SOT** |
| `red_xxx`, `gold_xxx`, `purple_xxx`, etc. | Gemini pilot/reference-matching predictions; preserved in `gemini_blind_predictions.json` and `pseudo_labels.json` | Model semantic output whose prefix also encodes predicted quality | Observation-layer ID; currently design debt because it is called `itemId` and has no canonical mapping |
| `BM1-XX / slot_XX` | Original `manifest.json` + 43-slot Gemini blind run | Formal benchmark image ID plus per-image ordinal prediction slot | Legitimate historical/run-layer ID, but incomplete geometry/provenance |
| `REP-XX / sXX` | Later `representative_vision_expansion` (`dataset_inventory.json` / `pseudo_labels.json`) | Five representative images, 57 semantic slots, bboxes and crops | Legitimate pack-layer ID in principle; design debt without an explicit BM1 mapping |
| `BLIND_REP-XX_sXX` | `gpt_blind_queue.json` | Stable queue-row key joining REP and local slot | Legitimate queue-layer ID |

**FACT** — All five REP source images map by exact source path to prior BM1 records: REP-01→BM1-01, REP-02→BM1-04, REP-03→BM1-05, REP-04→BM1-08, REP-05→BM1-11.

**FACT** — The old and new slot namespaces have no stored authoritative mapping. REP-02/BM1-04 and REP-03/BM1-05 preserve all 20 and 8 Gemini prediction payloads at matching ordinals. REP-01/BM1-01 preserves only 9/15 at the same ordinal; the six semantic identities formerly at slots 08–13 are reordered under s08–s13. Therefore `slot_XX` and `sXX` cannot safely be joined by ordinal alone.

**FACT** — `catalog_065.json` contains 200 canonical `image*` IDs. None of the 47 unique REP pseudo-label Top-1 IDs, and none of the 37 unique original Gemini Top-1 IDs, equals a canonical catalog ID.

**INFERENCE** — Two slot namespaces coexist because a later representative/crop expansion was layered over an earlier BM1 prediction run without preserving a first-class mapping. This is partly legitimate layer separation and partly historical/design debt. Two item namespaces coexist because Gemini emitted descriptive semantic labels instead of canonical candidates, and the result was stored in an `itemId` field without a canonical-ID resolution stage.

**RECOMMENDATION** — Do not collapse all layer IDs into one string namespace. Keep run/queue IDs as provenance keys, but make the canonical catalog ID the only item-identity SOT. Separately introduce a stable physical `itemInstanceId` plus a versioned, explicit mapping from BM1/REP/queue rows. Semantic model labels should remain observations, not identities.

## 5. Can Benchmark v1 currently measure model capability?

| Metric | Verdict | What remains usable |
|---|---|---|
| Item identity accuracy | `NOT_VALID_FOR_MODEL_ACCURACY` | Model-agreement and failure-mode diagnostics only. There is no independent truth; targets/geometry and identity namespaces are inconsistent. |
| Quality accuracy | `NOT_VALID_FOR_MODEL_ACCURACY` | Quality-agreement diagnostics only. Gemini semantic IDs embed predicted quality, some aliases have canonical-quality conflicts, and there is no independent truth. |
| Red detection | `NOT_VALID_FOR_MODEL_ACCURACY` | Candidate discovery/human-review prioritization only. The six Red slots are Gemini-derived pseudo labels, two are invalid-pack slots, and priority is a side channel. |
| Crop/slot extraction quality | `VALID_WITH_FILTERS` | Pack-level QA on the explicitly audited 19-slot queue: eight known invalid rows can be reported as defects of this queue. It is not a general extraction-accuracy estimate because the queue is priority-selected, only 19/57 crops were audited, and the generator is not reproducible. |

**FACT** — Eight of the 19 queue rows are invalid source/bbox/crop packages. This defect count must remain outside identity/quality/Red model denominators.

**INFERENCE** — Even after filtering those eight, the remaining 11 rows do not produce model “accuracy”: they lack ground truth and include target-contract and namespace inconsistencies. Agreement remains a diagnostic, not correctness.

**RECOMMENDATION** — Overall Benchmark v1 should currently be labeled `NOT_VALID_FOR_MODEL_ACCURACY`. Preserve the artifacts as a valuable contract/geometry failure corpus and human-review queue, not as an accuracy leaderboard.

## 6. Root-cause verdict and single highest-leverage next cut

**FACT** — The failure modes occur before scoring: heterogeneous/unvalidated sources, untyped coordinates, unbound label↔bbox pairs, raw crop propagation, and divergent item namespaces.

**INFERENCE** — The common highest-leverage defect is the absence of a **machine-verifiable source-relative item-instance geometry contract**. It explains how a non-inventory scene entered the pack, how another source used incompatible coordinates, how one large object became several slots, and why label/crop targets drifted toward neighbors.

**RECOMMENDATION** — If the next cut may address only one root cause, fix the slot/source geometry boundary first: one eligible stored source image, explicit pixel dimensions and inventory ROI, one declared coordinate space/transform, one physical item instance, one bbox/occupied-region, and validation that the generated crop contains that same instance. Identity alias work should follow; it cannot rescue invalid geometry.

## 7. Final answers

1. **Slot contract:** one alleged visible item instance from the representative/Gemini extraction pass, encoded as a semantic label plus model-authored bbox. It is not formally a grid cell, segmentation region, or bbox-center parent contract.
2. **Earliest common root of eight invalid packs:** missing representative admission and source-relative geometry contract. REP-04 uses a bbox coordinate basis incompatible with the saved desktop source; REP-05 is a non-inventory source selected as inventory. Raw cropping merely propagates both failures.
3. **Large-item repeated slots:** a pack-construction/extraction defect, not intended contract behavior. It combines item-instance/cell-feature semantics and lacks parent grouping/dedup.
4. **Gemini neighbor selection:** mainly label↔bbox/slot-contract ambiguity plus raw tight-crop propagation; the missing Gemini prompt prevents isolating a pure vision-error rate.
5. **Namespace root:** a later REP geometry/crop layer was added over the earlier BM1 run without an authoritative slot map, while Gemini semantic labels were stored as `itemId` without resolving to canonical catalog IDs.
6. **Accuracy suitability:** overall `NOT_VALID_FOR_MODEL_ACCURACY`; only filtered pack-level crop/slot QA is presently valid.
7. **Single next root cause:** establish and validate the source-relative physical item-instance geometry contract before any crop or identity comparison.
