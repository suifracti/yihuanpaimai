"""Warehouse grid geometry and visible occupancy evidence.

Recovers cell lines from a single warehouse ROI and groups occupied cells
into viewport components. Does not identify items, rarity, names, or prices.
Does not stitch across segments.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

import cv2
import numpy as np

from warehouse_scrollbar_observation import warehouse_search_roi, observe_warehouse_scrollbar

SCHEMA_VERSION = "warehouse-grid-geometry.v1"

STATUS_OK = "OK"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_OBSERVED = "OBSERVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"

REASON_EMPTY_FRAME = "EMPTY_FRAME"
REASON_INSUFFICIENT_STRUCTURE = "INSUFFICIENT_STRUCTURE"
REASON_PERIOD_INCONSISTENT = "PERIOD_INCONSISTENT"
REASON_LINE_INCONSISTENT = "LINE_INCONSISTENT"
REASON_REVEAL_OR_BLUR = "REVEAL_OR_BLUR"

MIN_CELL = 28.0
MAX_CELL = 96.0
MIN_PERIOD_SCORE = 0.20
MAX_PERIOD_REL_DIFF = 0.10
MIN_COLUMNS = 3
MAX_COLUMNS = 12
MIN_ROWS = 3
MAX_ROWS = 16

GRID_KEYS = (
    "columnCount",
    "visibleRowCount",
    "xLines",
    "yLines",
    "cellWidth",
    "cellHeight",
    "confidence",
    "status",
    "reason",
)
COMPONENT_KEYS = (
    "observationId",
    "boundingBox",
    "cellMask",
    "viewportRow",
    "viewportColumn",
    "widthCells",
    "heightCells",
    "spanCells",
    "clippedTop",
    "clippedBottom",
    "confidence",
    "status",
    "sourceFrame",
    "timecode",
)


def observe_warehouse_grid(
    frame: Optional[np.ndarray],
    *,
    already_cropped: bool = False,
    source_id: str = "",
    timecode: Any = None,
) -> Dict[str, Any]:
    empty = {
        "schemaVersion": SCHEMA_VERSION,
        "grid": _unknown_grid(REASON_EMPTY_FRAME),
        "components": [],
        "sourceId": source_id,
        "timecode": timecode,
    }
    if frame is None or getattr(frame, "size", 0) == 0:
        return empty
    board = _isolate_board(frame, already_cropped=already_cropped)
    if board is None:
        return {**empty, "grid": _unknown_grid(REASON_INSUFFICIENT_STRUCTURE)}
    crop, origin = board
    grid = _measure_grid(crop)
    if grid["status"] != STATUS_OK:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "grid": grid,
            "components": [],
            "sourceId": source_id,
            "timecode": timecode,
        }
    if already_cropped:
        # Measure the original search image first: trimming it before phase
        # estimation can change the period/phase and break cross-frame linking.
        # The observed track only bounds extrapolation into lower UI padding.
        observed = observe_warehouse_scrollbar(crop, already_cropped=True)
        track = observed.get("trackBox")
        if observed.get("scrollState") in {"TOP", "MIDDLE", "BOTTOM"} and observed.get("confidence", 0) >= 0.75 and track:
            x1, _, x2, y2 = track
            bottom = min(crop.shape[0], int(y2 + max(2, x2 - x1)))
            lines = [line for line in grid["yLines"] if line <= bottom]
            if len(lines) >= MIN_ROWS + 1:
                grid = {**grid, "yLines": lines, "visibleRowCount": len(lines) - 1}
    components = _extract_components(crop, grid, origin, source_id, timecode)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "grid": grid,
        "components": components,
        "sourceId": source_id,
        "timecode": timecode,
    }


def _unknown_grid(reason: str) -> Dict[str, Any]:
    return {
        "columnCount": None,
        "visibleRowCount": None,
        "xLines": None,
        "yLines": None,
        "cellWidth": None,
        "cellHeight": None,
        "confidence": 0.0,
        "status": STATUS_UNKNOWN,
        "reason": reason,
    }


def _isolate_board(frame: np.ndarray, *, already_cropped: bool) -> Optional[Tuple[np.ndarray, Tuple[int, int]]]:
    if already_cropped:
        if frame.shape[0] < 80 or frame.shape[1] < 80:
            return None
        return frame, (0, 0)
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = warehouse_search_roi(width, height)
    image = frame[y1:y2, x1:x2]
    origin = (x1, y1)
    if image.size == 0:
        return None
    height, width = image.shape[:2]
    if height < 80 or width < 80:
        return None
    right = max(28, int(round(0.07 * width)))
    bottom = int(round(0.88 * height))
    crop = image[: max(40, bottom), : max(40, width - right)]
    if crop.shape[0] < 80 or crop.shape[1] < 80:
        return None
    return crop, origin


def _acf_period(profile: np.ndarray, lo: int, hi: int) -> Tuple[float, float]:
    series = profile.astype(np.float32)
    series = series - float(series.mean())
    if float(np.linalg.norm(series)) < 1e-3 or profile.size < lo + 2:
        return 0.0, 0.0
    corr = np.correlate(series, series, mode="full")[len(series) - 1 :]
    if float(corr[0]) <= 1e-6:
        return 0.0, 0.0
    corr = corr / corr[0]
    hi = min(hi, len(corr) - 1)
    if hi <= lo:
        return 0.0, 0.0
    window = corr[lo : hi + 1]
    peaks: List[Tuple[float, float]] = []
    for i in range(1, len(window) - 1):
        if window[i] >= window[i - 1] and window[i] >= window[i + 1] and window[i] >= MIN_PERIOD_SCORE:
            peaks.append((float(window[i]), float(lo + i)))
    if not peaks:
        peak_i = int(np.argmax(window))
        return float(lo + peak_i), float(window[peak_i])
    peaks.sort(reverse=True)
    best_score, best_period = peaks[0]
    for score, period in sorted(peaks, key=lambda item: item[1]):
        if period >= best_period * 0.72 or score < MIN_PERIOD_SCORE:
            continue
        ratio = best_period / period
        nearest = round(ratio)
        if 2 <= nearest <= 4 and abs(ratio - nearest) <= 0.18:
            best_score, best_period = score, period
            break
    return best_period, best_score


def _phase(profile: np.ndarray, period: float) -> float:
    if period < 8 or profile.size < int(period) * 2:
        return 0.0
    length = len(profile)
    step = float(period)
    best_origin, best_score = 0.0, -1.0
    samples = max(8, int(period))
    for index in range(samples):
        origin = step * index / samples
        positions = np.clip(np.round(np.arange(origin, length, step)).astype(int), 0, length - 1)
        score = float(profile[positions].mean()) if positions.size else 0.0
        if score > best_score:
            best_score, best_origin = score, float(origin)
    return best_origin


def _measure_grid(crop: np.ndarray) -> Dict[str, Any]:
    height, width = crop.shape[:2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    col_edge = np.abs(grad_x).mean(axis=0)
    row_edge = np.abs(grad_y).mean(axis=1)
    span = float(min(width, height))
    lo = max(int(MIN_CELL), int(span * 0.05))
    hi = max(lo + 8, min(int(MAX_CELL), int(span * 0.28)))
    cell_w, score_w = _acf_period(col_edge, lo, hi)
    cell_h, score_h = _acf_period(row_edge, lo, hi)
    if score_w < MIN_PERIOD_SCORE and score_h < MIN_PERIOD_SCORE:
        return _unknown_grid(REASON_INSUFFICIENT_STRUCTURE)
    if score_w >= MIN_PERIOD_SCORE and score_h >= MIN_PERIOD_SCORE:
        if abs(cell_w - cell_h) / max(cell_w, cell_h) > MAX_PERIOD_REL_DIFF:
            return _unknown_grid(REASON_PERIOD_INCONSISTENT)
    elif score_w >= MIN_PERIOD_SCORE:
        cell_h = cell_w
        score_h = score_w * 0.85
    else:
        cell_w = cell_h
        score_w = score_h * 0.85
    if not (MIN_CELL <= cell_w <= MAX_CELL and MIN_CELL <= cell_h <= MAX_CELL):
        return _unknown_grid(REASON_PERIOD_INCONSISTENT)

    origin_x = _phase(col_edge, cell_w)
    smoothed_row_edge = np.convolve(row_edge, np.ones(5) / 5.0, mode="same")
    origin_y = _phase(smoothed_row_edge, cell_h)
    if origin_x > 0.35 * cell_w:
        origin_x = max(0.0, origin_x - cell_w)
    clipped_top = False
    if origin_y > 0.45 * cell_h:
        origin_y = origin_y - cell_h
        clipped_top = True

    columns = int((width - origin_x + 0.25 * cell_w) / cell_w)
    rows = int((height - origin_y + 0.25 * cell_h) / cell_h)
    if columns < MIN_COLUMNS or columns > MAX_COLUMNS or rows < MIN_ROWS or rows > MAX_ROWS:
        return _unknown_grid(REASON_LINE_INCONSISTENT)

    x_lines = [int(round(origin_x + index * cell_w)) for index in range(columns + 1)]
    y_lines = [max(0, int(round(origin_y + index * cell_h))) for index in range(rows + 1)]
    if x_lines[0] < -2 or y_lines[0] < -2:
        return _unknown_grid(REASON_LINE_INCONSISTENT)
    if x_lines[-1] > width + int(0.45 * cell_w) or y_lines[-1] > height + int(0.45 * cell_h):
        return _unknown_grid(REASON_LINE_INCONSISTENT)
    x_span = np.diff(x_lines)
    y_span = np.diff(y_lines)
    if x_span.size == 0 or y_span.size == 0:
        return _unknown_grid(REASON_LINE_INCONSISTENT)
    y_check_span = y_span[1:] if (clipped_top and y_span.size > 2) else y_span
    if float(np.std(x_span)) > 0.12 * cell_w or float(np.std(y_check_span)) > 0.12 * cell_h:
        return _unknown_grid(REASON_LINE_INCONSISTENT)
    if abs(float(np.median(x_span)) - cell_w) > 0.12 * cell_w:
        return _unknown_grid(REASON_LINE_INCONSISTENT)
    if abs(float(np.median(y_check_span)) - cell_h) > 0.12 * cell_h:
        return _unknown_grid(REASON_LINE_INCONSISTENT)

    confidence = float(min(1.0, 0.35 + 0.4 * min(score_w, score_h) + 0.15 * (columns / 10.0)))
    return {
        "columnCount": columns,
        "visibleRowCount": rows,
        "xLines": x_lines,
        "yLines": y_lines,
        "cellWidth": round(float(cell_w), 3),
        "cellHeight": round(float(cell_h), 3),
        "confidence": round(confidence, 3),
        "status": STATUS_OK,
        "reason": None,
    }


def _cell_feature(hsv: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> Optional[np.ndarray]:
    pad_x = max(4, int(0.16 * (x2 - x1)))
    pad_y = max(4, int(0.16 * (y2 - y1)))
    patch = hsv[y1 + pad_y : y2 - pad_y, x1 + pad_x : x2 - pad_x]
    if patch.size == 0:
        return None
    hue = patch[:, :, 0].astype(np.float32)
    sat = patch[:, :, 1].astype(np.float32)
    val = patch[:, :, 2].astype(np.float32)
    return np.array(
        [float(np.median(hue)), float(np.median(sat)), float(np.median(val)), float(sat.mean()), float(val.mean())],
        dtype=np.float32,
    )


def _occupied(feature: Optional[np.ndarray]) -> bool:
    if feature is None:
        return False
    sat_mean, val_mean = float(feature[3]), float(feature[4])
    return (sat_mean > 30 and val_mean > 40) or (val_mean > 85 and sat_mean > 16)


def _hue_delta(left: float, right: float) -> float:
    delta = abs(left - right)
    return min(delta, 180.0 - delta)


def _color_distance(a: np.ndarray, b: np.ndarray) -> float:
    return _hue_delta(float(a[0]), float(b[0])) * 1.1 + abs(float(a[1]) - float(b[1])) * 0.45 + abs(float(a[2]) - float(b[2])) * 0.35


def _boundary_edge(grad: np.ndarray, axis: str, pos: int, start: int, end: int) -> float:
    if axis == "v":
        patch = grad[start + 8 : end - 8, max(0, pos - 2) : pos + 3]
    else:
        patch = grad[max(0, pos - 2) : pos + 3, start + 8 : end - 8]
    if patch.size == 0:
        return 0.0
    return float(patch.mean())


def _has_trench_separation(gray: np.ndarray, axis: str, pos: int, start: int, end: int) -> bool:
    pad = 8
    start_p = start + pad
    end_p = end - pad
    if start_p >= end_p:
        return True
    if axis == "v":
        strip = gray[start_p:end_p, max(0, pos - 8) : min(gray.shape[1], pos + 9)].astype(np.float32)
        prof = np.percentile(strip, 60, axis=0)
        center_idx = pos - max(0, pos - 8)
    else:
        strip = gray[max(0, pos - 8) : min(gray.shape[0], pos + 9), start_p:end_p].astype(np.float32)
        prof = np.percentile(strip, 60, axis=1)
        center_idx = pos - max(0, pos - 8)

    win = prof[max(0, center_idx - 3) : min(len(prof), center_idx + 4)]
    trench_min = float(win.min()) if win.size else 0.0
    min_idx = int(np.argmin(win)) + max(0, center_idx - 3)

    lf_idx = max(0, min_idx - 5)
    left_flank = float(prof[lf_idx : max(1, min_idx - 2)].mean()) if min_idx >= 3 else trench_min
    rf_idx = min(len(prof), min_idx + 6)
    right_flank = float(prof[min(len(prof) - 1, min_idx + 3) : rf_idx].mean()) if min_idx + 3 < len(prof) else trench_min

    valley_depth = min(left_flank, right_flank) - trench_min
    return (trench_min <= 28.5) or (valley_depth >= 15.0 and trench_min <= 65.0)


def _extract_components(
    crop: np.ndarray,
    grid: Mapping[str, Any],
    origin: Tuple[int, int],
    source_id: str,
    timecode: Any,
) -> List[Dict[str, Any]]:
    columns = min(int(grid["columnCount"]), 10)
    rows = min(int(grid["visibleRowCount"]), 10)
    x_lines = [int(value) for value in grid["xLines"]]
    y_lines = [int(value) for value in grid["yLines"]]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    grad_x = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    grad_y = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))

    features: Dict[Tuple[int, int], np.ndarray] = {}
    occupied = np.zeros((rows, columns), dtype=np.uint8)
    for row in range(rows):
        for col in range(columns):
            feature = _cell_feature(hsv, x_lines[col], y_lines[row], x_lines[col + 1], y_lines[row + 1])
            if feature is None:
                continue
            features[(row, col)] = feature
            sat_mean, val_mean = float(feature[3]), float(feature[4])
            occupied[row, col] = 1 if (_occupied(feature) or val_mean > 85.0) else 0

    parent = list(range(rows * columns))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_l, root_r = find(left), find(right)
        if root_l != root_r:
            parent[root_r] = root_l

    for row in range(rows):
        for col in range(columns):
            if not occupied[row, col]:
                continue
            neighbors = (
                (row, col + 1, "v", x_lines[col + 1], y_lines[row], y_lines[row + 1]) if col + 1 < columns else None,
                (row + 1, col, "h", y_lines[row + 1], x_lines[col], x_lines[col + 1]) if row + 1 < rows else None,
            )
            for neighbor in neighbors:
                if neighbor is None:
                    continue
                nrow, ncol, axis, pos, start, end = neighbor
                if not occupied[nrow, ncol]:
                    continue
                if not _has_trench_separation(gray, axis, pos, start, end):
                    union(row * columns + col, nrow * columns + ncol)


    # Targeted linear 1x2 / 2x1 merge for single 1x1 cells across lattice trench lines
    group_sizes: Dict[int, int] = {}
    for r in range(rows):
        for c in range(columns):
            if occupied[r, c]:
                root = find(r * columns + c)
                group_sizes[root] = group_sizes.get(root, 0) + 1

    for row in range(rows):
        for col in range(columns):
            if not occupied[row, col] or group_sizes[find(row * columns + col)] != 1:
                continue
            neighbors = (
                (row, col + 1, "v", x_lines[col + 1], y_lines[row], y_lines[row + 1]) if col + 1 < columns else None,
                (row + 1, col, "h", y_lines[row + 1], x_lines[col], x_lines[col + 1]) if row + 1 < rows else None,
            )
            for neighbor in neighbors:
                if neighbor is None:
                    continue
                nrow, ncol, axis, pos, start, end = neighbor
                if not occupied[nrow, ncol]:
                    continue
                root_curr = find(row * columns + col)
                root_next = find(nrow * columns + ncol)
                if root_curr == root_next:
                    continue
                if group_sizes[root_curr] != 1 or group_sizes[root_next] != 1:
                    continue

                feat1 = features[(row, col)]
                feat2 = features[(nrow, ncol)]
                dh = _hue_delta(float(feat1[0]), float(feat2[0]))
                dv = abs(float(feat1[2]) - float(feat2[2]))
                edge = _boundary_edge(grad_x if axis == "v" else grad_y, axis, pos, start, end)
                color = _color_distance(feat1, feat2)

                linear_match = (
                    dh <= 3.0
                    and dv <= 15.0
                    and (
                        (edge < 100.0 and (color < 20.0 or (dh <= 2.0 and dv <= 5.0)))
                        or (edge < 180.0 and color < 3.0 and dv <= 2.0)
                    )
                )
                if linear_match:
                    union(row * columns + col, nrow * columns + ncol)
                    new_root = find(row * columns + col)
                    group_sizes[new_root] = 2
                    group_sizes[root_curr] = 2
                    group_sizes[root_next] = 2

    groups: Dict[int, List[Tuple[int, int]]] = {}
    for row in range(rows):
        for col in range(columns):
            if not occupied[row, col]:
                continue
            groups.setdefault(find(row * columns + col), []).append((row, col))

    components: List[Dict[str, Any]] = []
    for index, cells in enumerate(sorted(groups.values(), key=lambda item: (item[0][0], item[0][1], -len(item)))):
        rows_i = [cell[0] for cell in cells]
        cols_i = [cell[1] for cell in cells]
        row0, row1 = min(rows_i), max(rows_i)
        col0, col1 = min(cols_i), max(cols_i)
        mask = [[0 for _ in range(col1 - col0 + 1)] for _ in range(row1 - row0 + 1)]
        for row, col in cells:
            mask[row - row0][col - col0] = 1
        width = col1 - col0 + 1
        height = row1 - row0 + 1
        span = len(cells)
        if width >= 2 and height >= 2 and span >= int(0.84 * width * height):
            mask = [[1 for _ in range(width)] for _ in range(height)]
            span = width * height
        clipped_top = row0 == 0
        clipped_bottom = row1 == rows - 1
        rectangular = all(all(value == 1 for value in line) for line in mask)
        status = STATUS_AMBIGUOUS
        if rectangular and not clipped_top and not clipped_bottom:
            status = STATUS_OBSERVED
        x1 = x_lines[col0] + origin[0]
        y1 = y_lines[row0] + origin[1]
        x2 = x_lines[col1 + 1] + origin[0]
        y2 = y_lines[row1 + 1] + origin[1]
        confidence = 0.86 if status == STATUS_OBSERVED else 0.52
        if not rectangular:
            confidence = 0.40
        components.append(
            {
                "observationId": f"whg1_{source_id or 'frame'}_{index:03d}",
                "boundingBox": [int(x1), int(y1), int(x2), int(y2)],
                "cellMask": mask,
                "viewportRow": int(row0),
                "viewportColumn": int(col0),
                "widthCells": int(width),
                "heightCells": int(height),
                "spanCells": int(span),
                "clippedTop": bool(clipped_top),
                "clippedBottom": bool(clipped_bottom),
                "confidence": round(float(confidence), 3),
                "status": status,
                "sourceFrame": source_id or None,
                "timecode": timecode,
            }
        )
    return components
