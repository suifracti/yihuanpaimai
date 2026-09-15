# Warehouse outline regression frames

Extracted from the locally supplied `2026-08-17 14-11-56.mkv`, at 75 and 90 seconds using OpenCV frame seeking (`int(seconds * fps)`). Full 1920×1080 game frames; JPEG encoding as saved by OpenCV. No object annotations are painted into the input.

Both frames were visually reviewed on 2026-09-05. The board shows six separately bordered grey outlines, at zero-based `(col,row,width,height)`:

- `(2,0,1,1)` and `(2,1,1,1)`: two independent squares, with a dark horizontal gap and separate bright borders.
- `(6,0,3,2)`
- `(4,3,2,1)`
- `(5,4,1,2)`
- `(6,7,1,3)`

The public clue also says six outlines; the test expectations come from the visible object boundaries, not just that number. Rarity and item identity remain unknown. The board ends around y=775. The scene background below it is not another gold item.

Previously, one pair of squares was merged and one background patch was counted as gold. A total count of six therefore hid two separate defects. An older integration assertion expecting five likewise did not represent the visible object boundaries.
