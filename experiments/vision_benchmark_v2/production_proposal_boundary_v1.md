# Production Proposal Boundary v1

This document records the read-only primitive audit and the ownership boundary used by the Benchmark v2 single-source slice.

## Production primitive audit

### `core/vision_pipeline.py` — `NTEVisionPipeline`

- **FACT — Input:** full BGR frames plus mutable pipeline/session state and optional refresh control.
- **FACT — Geometry:** calls `ROIScaler` to obtain source-frame pixel ROIs; downstream settlement and warehouse records also use source-frame geometry.
- **FACT — State:** scene hysteresis, OCR scheduling, match generation, bid history, settlement stabilization, and warehouse lifetime all depend on prior frames and mutable state.
- **FACT — Run-local IDs:** match-generation and warehouse tracking values are runtime-local.
- **INFERENCE — Determinism/replay:** a single fixed snapshot is insufficient to reproduce the complete pipeline result; replay would also require ordered prior frames, reset state, timing/scheduler inputs, OCR/runtime versions, and loaded assets.
- **RECOMMENDATION — Boundary use:** do not use the pipeline object or `current_context` as Proposal Contract v1 input. A future sequence contract may retain explicit state inputs as provenance.

### `core/roi_scaler.py` — `ROIScaler`

- **FACT — Input:** ROI key plus source dimensions, or an image for `crop_roi`.
- **FACT — Geometry:** normalized 16:9 ROI definitions are converted to bounded source-pixel `(x1,y1,x2,y2)` coordinates after viewport compensation.
- **FACT — State/IDs:** stateless and has no runtime ID.
- **INFERENCE — Determinism/replay:** deterministic for fixed dimensions, ROI table, and implementation version; replayable from a fixed snapshot.
- **RECOMMENDATION — Safe provenance:** ROI key, normalized definition, viewport rectangle, resolved pixel bbox, and implementation hash are safe proposal provenance. It is not an item-instance or benchmark-identity owner.

### `core/warehouse_vision.py` — `WarehouseVisionV1`

- **FACT — Input:** full BGR frames, optional normalized board ROI, catalog/templates, configuration, and the engine's existing tracking state.
- **FACT — Geometry:** detection uses source-frame pixel `global_box` values plus viewport row/column/cell candidates. Public tracked `box` is `(x,y,width,height)`.
- **FACT — State/IDs:** `frame_index`, `tracked_blobs`, confirmation counters, loss tolerance, and incrementing `trackId` are stateful and run-local.
- **INFERENCE — Determinism/replay:** reproducible only from an explicitly reset engine and the same ordered frame sequence, config, catalog, templates, and dependency versions. A single snapshot is not an honest replay boundary for its confirmed output.
- **RECOMMENDATION — Boundary use:** geometry/cell observations could later be exported with full sequence provenance. `trackId`, candidate identity, evidence level, and confirmation state may be retained only as observations and must never become `instanceId` or truth.

### `core/settlement_item_recognizer.py` — `SettlementItemRecognizer`

- **FACT — Public input:** `parse_settlement_ledger` accepts a full BGR frame, applies a fixed settlement inventory ROI, segments cells, and may consult catalog/templates for identity candidates.
- **FACT — Selected primitive input:** `_segment_occupied_components` accepts one already-resolved inventory crop plus cell width/height. It reads only the supplied pixels and immutable recognizer assets; it has no temporal state or run-local ID.
- **FACT — Selected primitive output:** occupied cells, row/column, footprint candidate, rarity observation, score, shape, and occupied count. It does not create a physical benchmark instance.
- **FACT — Coordinate conversion:** raw components are cell-relative. The experiment exporter projects their cell rectangles through production `_cell_rect` and records the resulting bbox as `source_pixel` relative to the fixed crop snapshot.
- **INFERENCE — Determinism/replay:** for this fixed snapshot, implementation hash, OpenCV/Numpy versions, and exporter invocation version, repeated export is byte-equivalent after canonical JSON serialization.
- **RECOMMENDATION — Boundary use:** this stateless component primitive is the narrowest honest Proposal Contract v1 producer. Rarity and footprint remain non-authoritative observations; parent resolution stays in the experiment adapter.

### Capture/source primitives

- **FACT:** live/window capture depends on external window, viewport, and operating-system state.
- **RECOMMENDATION:** capture output is never replay authority. The SHA-256-addressed stored snapshot is the geometry source of truth.

## Contract and authority boundary

The artifact contains:

- `schemaVersion`
- `source`: stored path, SHA-256, width, height, `source_pixel`
- `sceneProposal`: proposed type, optional confidence, primitive/version, raw evidence
- `roiProposal`: source-relative bbox, coordinate space, primitive/version, raw evidence
- `itemProposals`: proposal ID, source-relative bbox, occupied cells, optional footprint, optional provenance-only `trackId`, primitive/version, raw evidence

The scene and ROI records in this slice are explicit fixed-input-role proposals. They state that automatic scene classification and automatic ROI detection were **not** performed. Only item/cell observations come from the selected production primitive.

The validator rejects Proposal Contract fields that claim benchmark authority, including `instanceId`, `benchmarkInstanceId`, authoritative parent grouping, `canonicalItemId`, verified identity/truth, truth status, and `queueId`.

## Replay and ownership

1. The exporter verifies the fixed snapshot hash/dimensions and the production implementation hash.
2. It runs the stateless production component primitive once and canonicalizes the observations into `proposal_artifact.json`.
3. The artifact is persisted without a generation timestamp, so time cannot affect deterministic identity or artifact bytes.
4. Admission later loads and validates only the saved artifact and fixed source bytes; it does not recreate or retain a production runtime object.
5. A reviewed experiment fixture selects `proposalId` and confirms proposal geometry.
6. The experiment adapter owns parent resolution, opaque `instanceId`, content review, Geometry Contract, crop, and queue admission.

Production observations can inform a benchmark decision, but they cannot make that decision authoritative.
