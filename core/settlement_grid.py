"""Settlement viewport geometry and visible card boundaries.

Coordinates describe the ten square rows above the rarity filters, not the
scrollable warehouse's total size. A visible card is not an identified item.
"""
import cv2
import numpy as np


def settlement_grid_bounds(frame):
    h, w = frame.shape[:2]
    # Measured against the original 1920x1080 settlement client frames.
    return (round(w * 1315 / 1920), round(h * 214 / 1080),
            round(w * 1878 / 1920), round(h * 776 / 1080))


def visible_card_rectangles(crop, cell_w, cell_h):
    """Return grid-aligned, closed card silhouettes, independently of catalog.

    A narrow opening removes JPEG bridges across the gutters. Reject partial
    silhouettes and nonrectangular unions instead of snapping arbitrary icon
    fragments to plausible catalog footprints. All four sides must align.
    """
    if crop.size == 0 or min(cell_w, cell_h) < 8:
        return []
    # Normalize sampling so morphology has the same physical size at 720p/1440p.
    cols, rows = round(crop.shape[1] / cell_w), round(crop.shape[0] / cell_h)
    crop = cv2.resize(crop, (round(cols * 56.3), round(rows * 56.2)))
    cell_w, cell_h = crop.shape[1] / cols, crop.shape[0] / rows
    value = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2]
    kernel_size = max(1, round(min(cell_w, cell_h) * .085))
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    contours = []
    # Multiple exposure levels recover dark cards without relying on one JPEG
    # threshold. A union across a gutter loses to an enclosed card border below.
    for threshold in (45, 50, 55, 60, 65, 70, 75, 80, 85, 90):
        mask = cv2.morphologyEx((value > threshold).astype(np.uint8) * 255,
                                cv2.MORPH_OPEN, kernel)
        found, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours.extend(found)
    rectangles = []
    rows = round(crop.shape[0] / cell_h)
    cols = round(crop.shape[1] / cell_w)
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        col, row = round(x / cell_w), round(y / cell_h)
        right, bottom = round((x + width) / cell_w), round((y + height) / cell_h)
        if not (0 <= col < right <= cols and 0 <= row < bottom <= rows):
            continue
        errors = (abs(x / cell_w - col), abs(y / cell_h - row),
                  abs((x + width) / cell_w - right), abs((y + height) / cell_h - bottom))
        if max(errors) > .13:
            continue
        if cv2.contourArea(contour) < width * height * .80:
            continue
        # Each snapped side must have a continuous dark gutter. This rejects
        # icon contours that happen to occupy an integer number of cells.
        x1, x2 = round(col * cell_w), round(right * cell_w)
        y1, y2 = round(row * cell_h), round(bottom * cell_h)
        edges = []
        for cut in (x1, x2):
            if 4 <= cut < value.shape[1] - 4:
                edges.append(np.min(np.percentile(value[y1+8:y2-8, cut-3:cut+4], 85, axis=0)))
        for cut in (y1, y2):
            if 4 <= cut < value.shape[0] - 4:
                edges.append(np.min(np.percentile(value[cut-3:cut+4, x1+8:x2-8], 85, axis=1)))
        # Card interiors can fall below the silhouette thresholds (e.g. the
        # dark cord across a kite). Require a dark line over 85% of its span,
        # while tolerating the gutter brightness introduced by downsampling.
        if edges and max(edges) > 75:
            continue
        rectangles.append((row, col, right - col, bottom - row))
    rectangles = sorted(set(rectangles))
    def cells(rect):
        row, col, width, height = rect
        return {(r, c) for r in range(row, row + height) for c in range(col, col + width)}
    footprints = {rect: cells(rect) for rect in rectangles}
    leaves = []
    for rect, footprint in footprints.items():
        children = [other for other in footprints.values() if other < footprint]
        if children:
            continue
        leaves.append(rect)
    # A partially overlapping interpretation is not a proven boundary.
    return [rect for rect in leaves if not any(
        rect != other and footprints[rect] & footprints[other] for other in leaves)]
