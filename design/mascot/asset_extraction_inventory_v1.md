# Mascot Asset Extraction Inventory v1

Status: **AUDIT ONLY — no extraction performed**
Coordinate convention: source-relative pixels, `[x0, y0, x1, y1)`, with the right/bottom edge excluded.
The bboxes below are reviewed crop candidates, not final alpha masks. Small padding may be added during a later extraction pass without changing the referenced source pixels.

## 1. Source authority and provenance

### FACT

| Priority | Source | Dimensions / mode | SHA-256 | Authority role |
|---:|---|---|---|---|
| 1 | `source/mascot_design_master.png` | 1023×1537 RGB | `E26AE89DF12F46527A83AF389AEB0084EE83C53A0A582A712901EB5E36C2F6CB` | Highest visual authority for face, hair color, main hairstyle silhouette, primary costume design, accessories and overall tone. |
| 2 | `source/mascot_asset_character.png` | 1536×1024 RGBA | `0B3D0E56AA7FA2E50342280C1BED6EAFDA61607F05BC31B488786A3CB8B974FE` | Character-body extraction source: full, back, busts, expressions and avatars. |
| 3 | `source/mascot_asset_application.png` | 1536×1024 RGBA | `9B077F99258B8C3A5F0404F869E24428AE5E8C789AC866F3CC076726DFF6CD28` | Application extraction source: seated, chibi/status states, UI decoration and effects. |

The two asset sheets are RGBA, but both have alpha range `0..254` and contain a composed page background. Their embedded alpha is therefore **not** an authoritative per-asset matte.

### RECOMMENDATION

- Never merge or regenerate the three sources into a new character.
- Every extracted asset must keep a single `sourceFile + cropBbox` provenance.
- Use the master only as the conflict arbiter. Do not copy missing pixels from another sheet to “repair” an asset.
- If an asset-sheet face, hair color, costume or accessory conflicts with the master, reject or conservatively crop the conflicting region rather than blending sources.

## 2. Primary requested inventory

### FACT / extraction assessment

| Asset | Source file | Candidate crop bbox | Occlusion / truncation | Pure non-generative extraction? | Recommended final use |
|---|---|---:|---|---|---|
| `full` | `mascot_asset_character.png` | `[0, 0, 372, 790)` | Right-side hair/coat visually contacts the seated composition; main figure itself is complete. | **Yes, reviewed mask required.** Contact boundary must be cut conservatively. | Main Window character, full-height promotional figure, large empty-state art. |
| `full_turnaround_front` | `mascot_asset_character.png` | `[25, 790, 121, 1004)` | None; substantially lower resolution than the large full. | **Yes.** | Small reference, QA comparison, compact UI preview; not a replacement for the large full. |
| `back` | `mascot_asset_character.png` | `[648, 0, 982, 676)` | Left outer hair contacts the seated figure’s hair; lower ornaments are close to adjacent content. | **Yes, conservatively.** Main silhouette is usable; contact pixels require manual review. | Costume/back-detail view, character reference drawer. |
| `back_turnaround` | `mascot_asset_character.png` | `[225, 790, 338, 1004)` | None; low resolution. | **Yes.** | Small turnaround reference and back-view QA fallback. |
| `bust/default` | `mascot_asset_character.png` | `[968, 8, 1114, 202)` | No character overlap; hair approaches the card boundary. | **Yes.** | Default dialogue portrait, status portrait and notification card. |
| `thinking` | `mascot_asset_character.png` | `[1114, 8, 1256, 202)` | No overlap; hand is part of the intended pose. | **Yes.** | Thinking / analysis-in-progress portrait. |
| `smile/success` | `mascot_asset_character.png` | `[1254, 8, 1396, 202)` | No overlap. This is the normal-scale “smile” expression, not the chibi success state. | **Yes.** | Successful analysis, positive confirmation and welcome portrait. |
| `warning/serious` | `mascot_asset_character.png` | `[1392, 238, 1536, 431)` | Cropped by the source right boundary at the far-right hair edge. | **Yes, with source-edge truncation retained.** | Warning, serious confirmation and degraded-state portrait. |
| `round_avatar` | `mascot_asset_character.png` | `[1010, 463, 1224, 633)` | Circular framing is baked into the sheet; no other character overlaps. | **Yes.** | Round profile/avatar chip. Preserve the authored circular crop. |
| `square_avatar` | `mascot_asset_character.png` | `[1237, 463, 1445, 633)` | Square framing is baked into the sheet; no overlap. | **Yes.** | Square profile image, settings/about card and compact header portrait. |
| `seated` | `mascot_asset_application.png` | `[298, 202, 823, 803)` | Left hair contacts/underlaps the large full; right hair approaches the large bust. Chair and central body are complete. | **Yes for the reviewed central figure; no for reconstructing hidden outer hair.** | Main Window seated illustration, analysis waiting state and large assistant panel. |
| `chibi_idle` | `mascot_asset_character.png` | `[473, 657, 621, 801)` | None. This is the only sheet entry explicitly labeled `idle`. | **Yes.** | Neutral idle chibi. Use despite character-sheet source because the application sheet has no semantically exact neutral idle. |
| `chibi_thinking` | `mascot_asset_application.png` | `[1124, 345, 1259, 462)` | None; lightbulb/star effect is part of the authored state. | **Yes.** | Thinking / planning / analysis-running state. |
| `chibi_success` | `mascot_asset_application.png` | `[1257, 345, 1395, 462)` | None; laptop and completion accents are intentional. | **Yes.** | Analysis complete / success state. |
| `chibi_warning` | `mascot_asset_application.png` | `[1393, 345, 1536, 462)` | Rightmost effect is clipped by the source boundary only at page edge; character is complete. | **Yes, retaining source truncation.** | Warning / attention state. |
| `chibi_sleep` | `mascot_asset_application.png` | `[997, 469, 1128, 610)` | None; pillow and sleep marks are part of the state. | **Yes.** | Sleep / inactive / paused status. |
| `chibi_loading` | `mascot_asset_application.png` | `[1392, 469, 1536, 610)` | Right edge is source-bounded; character is complete. | **Yes, retaining source truncation.** | Loading / queued / long-running state. |

## 3. Additional reliable character/status assets

### FACT

| Asset | Source file | Candidate crop bbox | Occlusion / truncation | Pure non-generative extraction? | Recommended final use |
|---|---|---:|---|---|---|
| `expression_focus` | `mascot_asset_character.png` | `[1393, 8, 1536, 202)` | Source-right hair truncation. | **Yes, with truncation retained.** | Focused/working portrait distinct from warning/serious. |
| `expression_doubt` | `mascot_asset_character.png` | `[968, 238, 1114, 431)` | None. | **Yes.** | Uncertain/low-confidence result. |
| `expression_blink` | `mascot_asset_character.png` | `[1114, 238, 1256, 431)` | None. | **Yes.** | Blink / gentle acknowledgement. |
| `expression_happy` | `mascot_asset_character.png` | `[1254, 238, 1396, 431)` | None. | **Yes.** | Strong positive/happy state. |
| `chibi_working` | `mascot_asset_application.png` | `[997, 345, 1128, 462)` | None; device is intentional. | **Yes.** | Active processing state; must not be mislabeled as neutral idle. |
| `chibi_angry` | `mascot_asset_application.png` | `[1124, 469, 1259, 610)` | None. | **Yes.** | Error/frustrated state where appropriate. |
| `chibi_collect` | `mascot_asset_application.png` | `[1257, 469, 1395, 610)` | None; surrounding objects are part of the authored effect. | **Yes.** | Reward/result collection state. |
| `front_turnaround_small` | `mascot_asset_application.png` | `[18, 721, 116, 1007)` | None; low resolution. | **Yes.** | Application-sheet QA and compact character reference. |
| `side_turnaround_small` | `mascot_asset_application.png` | `[116, 721, 224, 1007)` | None; low resolution. | **Yes.** | Side silhouette reference. |
| `back_turnaround_small` | `mascot_asset_application.png` | `[222, 721, 344, 1007)` | None; low resolution. | **Yes.** | Back silhouette reference. |

## 4. Moon / star / crystal / UI decoration inventory

### FACT

| Asset | Source file | Candidate crop bbox | Occlusion / truncation | Pure non-generative extraction? | Recommended final use |
|---|---|---:|---|---|---|
| `brand_moon_large` | `mascot_asset_application.png` | `[360, 17, 451, 113)` | None; glow is baked into the authored asset. | **Yes.** | Brand mark, empty-state accent, large section decoration. |
| `moon_small` | `mascot_asset_application.png` | `[373, 145, 426, 207)` | None. | **Yes.** | Small UI decoration and badge accent. |
| `star_compass` | `mascot_asset_application.png` | `[425, 143, 480, 207)` | None. | **Yes.** | Section marker, prediction/analysis accent. |
| `crystal` | `mascot_asset_application.png` | `[474, 140, 523, 211)` | None; glow should remain part of alpha refinement. | **Yes.** | Loading indicator accent, metric highlight, reward marker. |
| `butterfly` | `mascot_asset_application.png` | `[518, 149, 568, 208)` | None. | **Yes.** | Lightweight success/transition decoration. |
| `constellation_small` | `mascot_asset_application.png` | `[558, 145, 627, 219)` | Fine 1–2px lines. | **Yes, manual line-preserving alpha required.** | Background constellation accent. |
| `id_tag` | `mascot_asset_application.png` | `[617, 95, 702, 231)` | None; chain and tag are one authored asset. | **Yes, manual chain refinement required.** | ID/status decoration, profile/about card. |
| `purple_ribbon_fx` | `mascot_asset_application.png` | `[760, 774, 1038, 1024)` | Bottom edge is source-truncated; effect is semi-transparent. | **Yes, with soft alpha and source truncation.** | Panel transition/effect layer; never recolor to stronger purple. |
| `star_constellation_fx` | `mascot_asset_application.png` | `[986, 776, 1218, 1024)` | Bottom edge source-truncated; many 1–2px lines and points. | **Yes, manual fine-line mask required.** | Low-opacity dashboard background/effect layer. |
| `analysis_status_strip` | `mascot_asset_application.png` | `[858, 641, 1265, 752)` | Contains portrait, moon, text and panel as one composite. | **Yes as a complete composite; no clean separation of every internal layer.** | Read-only visual reference or whole status strip. Do not treat text as live UI data. |
| `rest_status_strip` | `mascot_asset_application.png` | `[884, 735, 1263, 830)` | Contains sleeping portrait and authored text. | **Yes as a complete composite.** | Rest/paused presentation reference. |
| `loading_status_strip` | `mascot_asset_application.png` | `[1092, 829, 1268, 915)` | None. | **Yes as a complete composite.** | Small loading/status chip reference. |
| `assistant_status_panel` | `mascot_asset_application.png` | `[1260, 617, 1536, 939)` | Cropped by the source-right edge; text/checkmarks/character are composited. | **Yes as a visual composite; not suitable as a functional UI layer.** | Layout reference for a future native status panel. |
| `cursor_set` | `mascot_asset_application.png` | `[1160, 924, 1536, 1024)` | Bottom/source-right truncation on some cursor glow. | **Yes, per-cursor reviewed crops required.** | Optional cursor/theme decoration; separate product decision required. |

## 5. Detail-reference tiles (not standalone character states)

### FACT

| Detail | Source file | Candidate crop bbox | Occlusion | Pure non-generative extraction? | Recommended final use |
|---|---|---:|---|---|---|
| `chest_crystal_detail` | `mascot_asset_application.png` | `[350, 799, 454, 902)` | Deliberately close-cropped. | **Yes.** | Mask/RGB QA for the chest crystal only. |
| `crescent_chain_detail` | `mascot_asset_application.png` | `[454, 799, 558, 902)` | Deliberately close-cropped. | **Yes.** | Fine-chain alpha reference. |
| `sleeve_hardware_detail` | `mascot_asset_application.png` | `[558, 799, 660, 902)` | Deliberately close-cropped. | **Yes.** | Costume/hardware QA. |
| `hanging_crystal_detail` | `mascot_asset_application.png` | `[660, 799, 761, 902)` | Deliberately close-cropped. | **Yes.** | Crystal and chain alpha reference. |
| `fabric_detail` | `mascot_asset_application.png` | `[350, 902, 454, 1002)` | Bottom-close crop. | **Yes.** | Coat/fabric edge and color QA. |
| `boot_hardware_detail` | `mascot_asset_application.png` | `[454, 902, 558, 1002)` | Bottom-close crop. | **Yes.** | Boot/metal color QA. |
| `id_tag_detail` | `mascot_asset_application.png` | `[558, 902, 660, 1002)` | Bottom-close crop. | **Yes.** | Tag and clear-material QA. |

## 6. Master authority reference crops

These are reference/adjudication regions, not alternative pixels to merge into another source.

| Reference | Master bbox | Structural issue | Recommended use |
|---|---:|---|---|
| Full-body authority | `[0, 48, 612, 1292)` | Text/background at left; large bust overlaps at upper-right. | Judge face, hair color, costume, crescent/star chain and sheer-fabric appearance. |
| Bust authority | `[530, 0, 1023, 573)` | Full figure contaminates lower-left; hair is clipped by top/right source edges. | Judge face shape, eye treatment, hair tone and chest/crescent details. |
| Expression authority strip | `[594, 622, 1008, 775)` | Small and lower resolution. | Check expression identity; do not upscale as the primary portrait source. |
| Back authority | `[568, 835, 761, 1278)` | Small but visually isolated. | Judge back hairstyle, chain placement and coat silhouette. |
| Theme-icon authority | `[20, 1345, 405, 1518)` | Embedded labels and background. | Judge moon/star/crystal/constellation motif shape and color. |

## 7. Conflict and admission findings

### INFERENCE

1. The large full, seated and back figures on both asset sheets are presentation composites, not isolated layers. Their contact regions cannot be assumed to contain recoverable hidden pixels.
2. Expression cards, avatar cards and chibi states have substantially cleaner admission geometry than the three large overlapping figures.
3. Fine chains, constellation lines, hair wisps and transparent ribbon effects are technically extractable without generation, but require manual 1–3px alpha refinement; generic GrabCut alone is not sufficient.
4. `chibi_idle` and `chibi_working` are distinct authored states. The application sheet does not contain a semantically exact neutral idle, so the character-sheet idle is the correct source for that one asset.
5. The status strips/panel include authored Chinese text and visual metrics. They can be extracted only as static presentation composites and must not become live product state or canonical data.

### RECOMMENDATION

Suggested later extraction order, if separately authorized:

1. Clean expression portraits and round/square avatars.
2. Independent chibi/status states.
3. Moon/star/crystal decorations and detail-reference tiles.
4. Large full/back with manual contact-boundary review.
5. Seated figure last, because its outer hair has the highest overlap risk.

No asset should be admitted without a review composite on white, black and the product deep-blue-gray background. No cross-source pixel repair or generative completion is permitted.
