"""Independent scene producer for offline content/scroll integration.

Semantic truth is the scene definition, not a detector result. OpenCV remap is
the independent Q5 bilinear fixture renderer. It is not a claim about the game.
Generated full originals remain under build; no capture/input APIs are used.
"""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
GRID = (1315, 214, 1877, 776)
REFERENCES = ((1180, 250, 1220, 290), (1200, 450, 1240, 490),
              (1150, 650, 1190, 690), (1210, 730, 1250, 770))


def scene(view=0, *, revealing=False):
    frame = np.full((1080, 1920, 3), 20, np.uint8)
    title = cv2.imread(str(ROOT/'assets/scene_anchors/settlement_title.png'))
    h, w = title.shape[:2]
    frame[130:130+h, 70:70+w] = title
    rng = np.random.RandomState(421)
    # Separated, texture-rich decorative references, outside the content.
    for x, y, r, b in REFERENCES:
        frame[y-1:b+1, x-1:r+1] = rng.randint(25, 230, (b-y+2, r-x+2, 3), dtype=np.uint8)
    # Exact content extent: 562px viewport + two 180px downward moves.
    # All bottom-clipped artworks in earlier views become fully visible later.
    canvas = np.full((922, 564, 3), (36, 30, 28), np.uint8)
    for y in range(0, 922, 56):
        canvas[y:y+2] = 75
    for x in range(0, 564, 56):
        canvas[:, x:x+2] = 75
    # Distinct disjoint artworks, including printed glyphs, a quantity corner,
    # rarity rim and an object crossing the viewport bottom. Empty cells remain.
    for row in range(7):
        for col in range(3):
            x, y = 18+col*166, 16+row*120
            color = (50+row*13, 155-col*25, 60+col*65)
            cv2.rectangle(canvas, (x, y), (x+91, y+77), color, -1)
            cv2.rectangle(canvas, (x, y), (x+91, y+77), (180, 50+row*8, 135), 2)
            cv2.circle(canvas, (x+45, y+31), 10+row%4, (70, 220-row*8, 175), -1)
            cv2.putText(canvas, f'{row}{col}', (x+8, y+63), cv2.FONT_HERSHEY_SIMPLEX,
                        .55, (230, 230, 230), 1, cv2.LINE_8)
            cv2.putText(canvas, '2', (x+74, y+74), cv2.FONT_HERSHEY_SIMPLEX,
                        .4, (250, 250, 250), 1, cv2.LINE_8)
    x, y, r, b = GRID
    offset = view*180
    frame[y:b, x:r] = canvas[offset:offset+b-y, :r-x]
    if revealing:
        # A physically unchanged dark neutral placeholder is not an empty slot.
        cv2.rectangle(frame, (1330, 225), (1435, 315), (30, 30, 30), -1)
        cv2.rectangle(frame, (1330, 225), (1435, 315), (230, 230, 230), 3)
    frame[214:776, 1882:1894] = 45
    thumb = (214, 410, 576)[view]
    frame[thumb:thumb+200, 1882:1894] = 210
    return frame


def render_phase(frame, x=2, y=1):
    yy, xx = np.indices(frame.shape[:2], dtype=np.float32)
    return cv2.remap(frame, xx+x/32, yy+y/32, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)
