# Proposal Atomicity Audit v1

## Scope and evidence

This audit is geometry-only. It uses the frozen source snapshot
`snapshots/source-c86e85c5712aea00ac7d.png`, the 66 records in
`proposal_artifact.json`, source-pixel bboxes, occupied cells, footprint
candidates, the reviewed single/multi grouping fixtures, and the production
implementation in `core/settlement_item_recognizer.py`.

No item name, canonical identity, quality, prediction, or catalog answer is
used. No code or fixture was changed.

## Operational distinction

- `ATOMIC_CLEAR`: the proposal visibly centers one complete small physical
  item. A narrow bbox edge may still touch a neighbor; that is separately
  flagged as bbox spillover.
- `FRAGMENT_OF_ONE_PARENT`: the proposal is assignable to one physical parent
  but represents only part of a larger parent tile/component.
- `MIXED_MULTI_PARENT`: member cells emitted as one production component have
  substantive regions belonging to multiple independent physical parents.
- `AMBIGUOUS`: current pixels do not support a reliable ownership decision.
- `BACKGROUND_OR_NOISE`: no reliable physical parent is present.

`bbox spillover` is an orthogonal diagnostic. It means the main proposal is
assignable to one parent, while a source-pixel cell bbox includes a smaller
edge/strip of a neighbor. Spillover does **not** make the production component
mixed. It is counted only for otherwise atomic/fragment proposals; the four
true mixed components are not double-counted as spillover.

## Summary

| Classification | Count | Denominator |
|---|---:|---:|
| `ATOMIC_CLEAR` | 9 | 66 |
| `FRAGMENT_OF_ONE_PARENT` | 53 | 66 |
| `MIXED_MULTI_PARENT` | 4 | 66 |
| `AMBIGUOUS` | 0 | 66 |
| `BACKGROUND_OR_NOISE` | 0 | 66 |

Separately, 33/66 proposals have visually confirmed A-type bbox spillover.
The spillover count excludes all four B-type true mixed components.

## Per-proposal classification

`A` in the spillover column means bbox spillover. `B` means true mixed
component and appears only with `MIXED_MULTI_PARENT`.

| # | proposalId | bbox / cells | Classification | Spill | Geometry basis |
|---:|---|---|---|:---:|---|
| 0 | `proposal-3f6968ebc9be50c2e62d` | `[0,0,31,33]` / `0:0` | `FRAGMENT_OF_ONE_PARENT` | — | Corner of the left tall parent tile. |
| 1 | `proposal-26fe77b641ff1cf7efa9` | `[31,0,61,33]` / `0:1` | `ATOMIC_CLEAR` | A | One small circular item; left edge includes the adjacent purple tile. |
| 2 | `proposal-a35f496a1b87ba304b7e` | `[61,0,92,33]` / `0:2` | `FRAGMENT_OF_ONE_PARENT` | A | Upper portion of one small gold parent; narrow adjacent-tile strip. |
| 3 | `proposal-7439879df6b916a00aea` | `[92,0,123,33]` / `0:3` | `FRAGMENT_OF_ONE_PARENT` | A | Left fragment of the long upper blue parent; gold-tile edge at left. |
| 4 | `proposal-1cfde6cb3957c5a74a51` | `[123,0,154,33]` / `0:4` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the same long upper blue parent. |
| 5 | `proposal-51edcfdcacbdf055489e` | `[154,0,184,33]` / `0:5` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the same long upper blue parent. |
| 6 | `proposal-e2c85dd8e1f3b6a2cfe6` | `[184,0,215,33]` / `0:6` | `FRAGMENT_OF_ONE_PARENT` | — | Right fragment of the same long upper blue parent. |
| 7 | `proposal-42f8be36ecf5587cce57` | `[215,0,246,33]` / `0:7` | `FRAGMENT_OF_ONE_PARENT` | A | Top-right large parent background with a narrow upper-blue-parent edge. |
| 8 | `proposal-7f75bfbaa2fa78bc7c87` | `[246,0,276,99]` / `0:8;1:8;2:8` | `FRAGMENT_OF_ONE_PARENT` | — | One 1×3 strip entirely inside the top-right framed parent. |
| 9 | `proposal-92e623cc46426424b524` | `[276,0,307,33]` / `0:9` | `FRAGMENT_OF_ONE_PARENT` | — | Top fragment of the same framed parent. |
| 10 | `proposal-44d473f3458cff319236` | `[0,33,31,132]` / `1:0;2:0;3:0` | `MIXED_MULTI_PARENT` | B | First two cells cover the left tall drink tile; third cell substantively covers the separate purple parent below. |
| 11 | `proposal-39a26907892f7bba51a6` | `[31,33,61,66]` / `1:1` | `ATOMIC_CLEAR` | A | One stacked small circular item; bbox touches the vertically adjacent small item. |
| 12 | `proposal-c4aed85c702a512aa226` | `[61,33,92,66]` / `1:2` | `ATOMIC_CLEAR` | A | One small gold circular item; green neighbor strips are included. |
| 13 | `proposal-6a5c52733134c803129a` | `[92,33,123,66]` / `1:3` | `FRAGMENT_OF_ONE_PARENT` | A | Left fragment of the large circular blue parent; adjacent edge at left/top. |
| 14 | `proposal-17cb35cd9c08e980c0e6` | `[123,33,154,66]` / `1:4` | `FRAGMENT_OF_ONE_PARENT` | A | Upper fragment of the same circular parent; upper long-tile strip. |
| 15 | `proposal-c700f67b2be29f2a288e` | `[154,33,184,66]` / `1:5` | `ATOMIC_CLEAR` | A | One small diamond item; bbox includes neighboring tile edges. |
| 16 | `proposal-5fcee11df94349a175a4` | `[184,33,215,132]` / `1:6;2:6;3:6` | `MIXED_MULTI_PARENT` | B | 1×3 component crosses the upper horizontal tile, the separate middle small-object tile, and the large center tile: three parents. |
| 17 | `proposal-ab6e10659fa202f3aba3` | `[215,33,246,132]` / `1:7;2:7;3:7` | `MIXED_MULTI_PARENT` | B | Upper cells belong to the top-right framed parent; bottom cell belongs to the separate large center parent. |
| 18 | `proposal-10cbca300c0d6f203c69` | `[276,33,307,66]` / `1:9` | `FRAGMENT_OF_ONE_PARENT` | — | Right fragment of the top-right framed parent. |
| 19 | `proposal-68f2e7e3150991fbec7b` | `[31,66,61,99]` / `2:1` | `ATOMIC_CLEAR` | A | One small purple circular item; vertical/side neighbor edges are present. |
| 20 | `proposal-388973a6aacf3de56f57` | `[61,66,92,99]` / `2:2` | `ATOMIC_CLEAR` | A | One small green circular item with an adjacent purple edge. |
| 21 | `proposal-66af90cd8e38302ddcd5` | `[92,66,123,99]` / `2:3` | `FRAGMENT_OF_ONE_PARENT` | A | Lower-left fragment of the large circular parent; neighbor edge at left. |
| 22 | `proposal-8bd190c9b718b168a694` | `[123,66,154,99]` / `2:4` | `FRAGMENT_OF_ONE_PARENT` | — | Lower fragment of the same circular parent. |
| 23 | `proposal-fbdead5dc893e8c4f419` | `[154,66,184,99]` / `2:5` | `ATOMIC_CLEAR` | A | One small diamond item; narrow neighbor edges remain in bbox. |
| 24 | `proposal-1b68b91599db03d3c32a` | `[276,66,307,164]` / `2:9;3:9;4:9` | `MIXED_MULTI_PARENT` | B | Top cell substantively covers the framed parent; lower cells cover the independent circular parent below. |
| 25 | `proposal-22db60995264fcd59d39` | `[31,99,61,132]` / `3:1` | `FRAGMENT_OF_ONE_PARENT` | A | Top fragment of the large left-middle purple parent; upper small-item edge. |
| 26 | `proposal-7bfda0f751c2008b4ad9` | `[61,99,92,132]` / `3:2` | `FRAGMENT_OF_ONE_PARENT` | A | Top-right fragment of that purple parent; upper small-item edge. |
| 27 | `proposal-78af733732eccc33714f` | `[92,99,123,132]` / `3:3` | `FRAGMENT_OF_ONE_PARENT` | A | Top-left fragment of the reviewed large center parent; left-parent edge. |
| 28 | `proposal-4294fb007503928869b1` | `[123,99,154,132]` / `3:4` | `FRAGMENT_OF_ONE_PARENT` | — | Top fragment of the large center parent. |
| 29 | `proposal-d8081139e14881a54f46` | `[154,99,184,132]` / `3:5` | `FRAGMENT_OF_ONE_PARENT` | — | Top fragment of the same center parent. |
| 30 | `proposal-e62ed642c1b4e844e34b` | `[246,99,276,132]` / `3:8` | `FRAGMENT_OF_ONE_PARENT` | A | Fragment of the right-middle circular parent; center-parent edge at left. |
| 31 | `proposal-b3bc5d0a319756c339b6` | `[0,132,31,164]` / `4:0` | `FRAGMENT_OF_ONE_PARENT` | — | Lower-left fragment of the large left-middle purple parent. |
| 32 | `proposal-9540e483fbb43d0e9fb3` | `[31,132,61,164]` / `4:1` | `FRAGMENT_OF_ONE_PARENT` | — | Lower fragment of the same purple parent. |
| 33 | `proposal-9daaa2e1b67a5b5473de` | `[61,132,92,164]` / `4:2` | `FRAGMENT_OF_ONE_PARENT` | A | Lower-right purple-parent fragment; narrow center-parent edge. |
| 34 | `proposal-cb32cb10f80543fbf46c` | `[92,132,123,164]` / `4:3` | `FRAGMENT_OF_ONE_PARENT` | A | Left fragment of the large center parent; purple-parent edge at left. |
| 35 | `proposal-0cca811ac3b016de81d9` | `[123,132,154,164]` / `4:4` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the large center parent. |
| 36 | `proposal-6466ce88f36565576c24` | `[154,132,184,164]` / `4:5` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the large center parent; rarity observation is non-authoritative. |
| 37 | `proposal-a14206bd4db19be3f104` | `[184,132,215,164]` / `4:6` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the large center parent. |
| 38 | `proposal-9024bee1fb047008467d` | `[215,132,246,164]` / `4:7` | `FRAGMENT_OF_ONE_PARENT` | — | Right fragment of the large center parent. |
| 39 | `proposal-62600c9c9b45210c31f8` | `[246,132,276,164]` / `4:8` | `FRAGMENT_OF_ONE_PARENT` | A | Lower fragment of the right-middle circular parent; center-parent edge. |
| 40 | `proposal-4a057e14bb49d8d9a6ca` | `[0,164,31,197]` / `5:0` | `FRAGMENT_OF_ONE_PARENT` | — | Left fragment of the white camera-like parent. |
| 41 | `proposal-50787b45ecb270fc552a` | `[31,164,61,197]` / `5:1` | `FRAGMENT_OF_ONE_PARENT` | — | Upper/middle fragment of that white parent. |
| 42 | `proposal-57f0e84c5467469bce38` | `[61,164,92,197]` / `5:2` | `ATOMIC_CLEAR` | A | Reviewed single small item; bbox includes a thin white-parent strip. |
| 43 | `proposal-1ce9c560bb170747b4bc` | `[92,164,123,197]` / `5:3` | `FRAGMENT_OF_ONE_PARENT` | A | Left fragment of the large center parent; small-item strip at left. |
| 44 | `proposal-643f656f5c67a9759dcb` | `[123,164,154,197]` / `5:4` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the large center parent. |
| 45 | `proposal-cf5a1011125ba9833e64` | `[154,164,184,197]` / `5:5` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the large center parent. |
| 46 | `proposal-41c72082eb5676c5cb4d` | `[184,164,215,197]` / `5:6` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the large center parent. |
| 47 | `proposal-4b4a67d66377dc176b31` | `[215,164,246,197]` / `5:7` | `FRAGMENT_OF_ONE_PARENT` | — | Right fragment of the large center parent. |
| 48 | `proposal-ab0548530ddf07334e23` | `[246,164,276,263]` / `5:8;6:8;7:8` | `FRAGMENT_OF_ONE_PARENT` | A | Main 1×3 strip belongs to the right gold drink tile; thin center/bottom-neighbor spillover, not a fused second component. |
| 49 | `proposal-42b04e25cf65f2010053` | `[276,164,307,263]` / `5:9;6:9;7:9` | `FRAGMENT_OF_ONE_PARENT` | A | Right strip of the same drink tile; bottom strip enters the next small tile. |
| 50 | `proposal-fed9c538fda981abd20c` | `[0,197,31,230]` / `6:0` | `FRAGMENT_OF_ONE_PARENT` | A | Lower white-parent fragment; bbox reaches the separate purple parent below. |
| 51 | `proposal-4f1d2323f20a56e14ab5` | `[31,197,61,230]` / `6:1` | `FRAGMENT_OF_ONE_PARENT` | A | Lower white-parent fragment with bottom-parent spillover. |
| 52 | `proposal-69e17bc320b5754c02a0` | `[61,197,92,230]` / `6:2` | `ATOMIC_CLEAR` | A | One small purple circular item; white/next-parent strips remain in bbox. |
| 53 | `proposal-4f4b8f809073855ed857` | `[92,197,123,230]` / `6:3` | `FRAGMENT_OF_ONE_PARENT` | A | Left fragment of the large center parent; small/bottom neighbor edge. |
| 54 | `proposal-a7d6a91229f4935c139b` | `[123,197,154,230]` / `6:4` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the large center parent. |
| 55 | `proposal-99ffee4f75a9bb602d7a` | `[154,197,184,230]` / `6:5` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the large center parent. |
| 56 | `proposal-f28ddd713184a1d3ff00` | `[184,197,215,230]` / `6:6` | `FRAGMENT_OF_ONE_PARENT` | — | Fragment of the large center parent. |
| 57 | `proposal-6c0f34068689cb1e5410` | `[215,197,246,230]` / `6:7` | `FRAGMENT_OF_ONE_PARENT` | — | Right fragment of the large center parent. |
| 58 | `proposal-1802df13bf9f65596ca3` | `[0,230,31,263]` / `7:0` | `FRAGMENT_OF_ONE_PARENT` | — | Left fragment of the large lower-left purple parent. |
| 59 | `proposal-b35740512967dcdd6510` | `[31,230,61,263]` / `7:1` | `FRAGMENT_OF_ONE_PARENT` | — | Middle fragment of that lower-left parent. |
| 60 | `proposal-90c567e697a0f910895f` | `[61,230,92,263]` / `7:2` | `FRAGMENT_OF_ONE_PARENT` | — | Right fragment of that lower-left parent. |
| 61 | `proposal-43a94e18c191c9268276` | `[92,230,123,263]` / `7:3` | `FRAGMENT_OF_ONE_PARENT` | A | Bottom center-parent fragment; left/lower neighboring tiles enter bbox. |
| 62 | `proposal-f647a67177f085529d0f` | `[123,230,154,263]` / `7:4` | `FRAGMENT_OF_ONE_PARENT` | A | Bottom center-parent fragment; next-row parent enters lower strip. |
| 63 | `proposal-031da3c8719343f83304` | `[154,230,184,263]` / `7:5` | `FRAGMENT_OF_ONE_PARENT` | A | Bottom center-parent fragment; lower strip crosses into adjacent next-row tiles. |
| 64 | `proposal-4f5a25c82b1c75408c72` | `[184,230,215,263]` / `7:6` | `FRAGMENT_OF_ONE_PARENT` | A | Bottom center-parent fragment; lower separate parent enters bbox. |
| 65 | `proposal-ec6fd5dc2c4f4c90e4a9` | `[215,230,246,263]` / `7:7` | `FRAGMENT_OF_ONE_PARENT` | A | Bottom center-parent fragment; lower separate parent enters bbox. |

## True mixed components

| proposalId | bbox / occupiedCells | Physical parents | Evidence | Type |
|---|---|---:|---|---|
| `proposal-44d473f3458cff319236` | `[0,33,31,132]` / `(1,0),(2,0),(3,0)` | 2 | Two cells cover the left tall parent; the third covers a separate purple parent below, with a visible tile boundary between them. | B: true 1×3 component fusion |
| `proposal-5fcee11df94349a175a4` | `[184,33,215,132]` / `(1,6),(2,6),(3,6)` | 3 | The strip crosses an upper horizontal tile, a distinct middle small-object tile, and the large center tile below. | B: true 1×3 component fusion |
| `proposal-ab6e10659fa202f3aba3` | `[215,33,246,132]` / `(1,7),(2,7),(3,7)` | 2 | Upper cells are inside the framed parent region; the bottom cell is inside the separate center parent. | B: true 1×3 component fusion |
| `proposal-1b68b91599db03d3c32a` | `[276,66,307,164]` / `(2,9),(3,9),(4,9)` | 2 | Top cell covers the framed parent; lower cells cover the independent circular parent. The one-pixel lower neighbor edge is incidental spillover. | B: true 1×3 component fusion |

These are not cases where a correct single-parent component merely has a loose
bbox. The member cells used to emit each proposal cross visible physical tile
boundaries and contain substantive regions of more than one parent.

## Bbox spillover diagnostic

The 33 A-type spillover proposals are indices:

`1, 2, 3, 7, 11, 12, 13, 14, 15, 19, 20, 21, 23, 25, 26, 27, 30, 33, 34, 39, 42, 43, 48, 49, 50, 51, 52, 53, 61, 62, 63, 64, 65`.

Typical spillover is proposal `proposal-57f0e84c5467469bce38`: the proposal
clearly centers one small physical item, while its left edge includes a thin
strip of the neighboring white tile. This is not a mixed component and does
not require component splitting.

## Production cause

### FACT

`_segment_occupied_components` first classifies a fixed 8×10 cell grid as
occupied/empty and assigns optional rarity evidence. It does not run pixel
connected-component labeling or morphology. It then considers only the
allowed rectangle shapes `(4,4)` and `(1,3)`.

For each candidate rectangle, `filled_rect_ok` accepts the merge when:

1. every member cell is classified occupied;
2. cell rarity is compatible with the start-cell rarity or unknown; and
3. each shared edge passes `_shared_edge_allows_merge`.

The shared-edge test rejects a sufficiently dark gutter, then requires enough
same-rarity fill and brightness. Remaining occupied cells are emitted as
singletons.

### INFERENCE

The stored 307×329 inventory crop is not phase-aligned to the primitive's
uniform 10-column/10-row cell projection. Several real physical tile
boundaries therefore fall inside a projected cell or on a bright colored
border rather than a dark gutter. Neighboring parents with compatible blue or
purple backgrounds can satisfy the occupancy, rarity, and bright shared-edge
tests across an allowed 1×3 strip.

That combination—not morphology and not arbitrary bbox padding—created the
four true mixed components. All four are 1×3 merges produced by the explicit
allowed-shape path.

## Verdict

`SPLITTING_CONTRACT_NEEDED`

Four of 66 frozen production proposals contain true multi-parent component
fusion. Grouping alone cannot safely assign one such proposal to either parent
without losing or contaminating geometry.

The minimum next cut should be one experiment-only reviewed split contract for
one real mixed proposal (preferably `proposal-44d473f3458cff319236`). It should
bind the exact proposal artifact hash and proposalId, record reviewed child
source-pixel bboxes/cells, require non-overlap plus explicit coverage/discard
provenance, and leave canonical identity/quality/truth null. It should not
change production segmentation or generalize into an automatic splitter.
