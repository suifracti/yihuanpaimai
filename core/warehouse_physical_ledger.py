"""Cross-segment physical component ledger.

Maps viewport observations onto one warehouse coordinate system using only
VERIFIED DOWN overlap offsets. Same entity becomes one deterministic track.
Does not name items, query catalog, or decide warehouse COMPLETE.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from settlement_truth_evidence_contract import RECORD_KEY_RE

SCHEMA_VERSION = "warehouse-physical-ledger.v1"

STATUS_OBSERVED = "OBSERVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_CONFLICT = "CONFLICT"

CHAIN_UNANCHORED = "UNANCHORED"
CHAIN_ACTIVE = "ACTIVE"
CHAIN_BROKEN = "BROKEN"

REASON_UNVERIFIED_OVERLAP = "UNVERIFIED_OVERLAP"
REASON_OVERLAP_CONFLICT = "OVERLAP_CONFLICT"
REASON_SEQUENCE_GAP = "SEQUENCE_GAP"
REASON_STABLE_KEY_CHANGED = "STABLE_KEY_CHANGED"
REASON_GRID_PHASE_MISALIGNED = "GRID_PHASE_MISALIGNED"
REASON_DIRECTION_REVERSED = "DIRECTION_REVERSED"
REASON_CLIPPED_ONLY = "CLIPPED_ONLY"
REASON_PIXEL_ONLY = "PIXEL_ONLY"
REASON_AMBIGUOUS_CANDIDATE = "AMBIGUOUS_CANDIDATE"
REASON_OBSERVATION_CONFLICT = "OBSERVATION_CONFLICT"
REASON_UNANCHORED = "UNANCHORED"

DIR_DOWN = "DOWN"
DIR_UP = "UP"
DIR_NONE = "NONE"
REASON_NO_MOVEMENT = "NO_MOVEMENT"
STATUS_VERIFIED = "VERIFIED"

LEDGER_KEYS = (
    "schemaVersion",
    "recordStableKey",
    "chainStatus",
    "segments",
    "tracks",
    "conflicts",
)
TRACK_KEYS = (
    "trackId",
    "status",
    "globalBoundingBox",
    "globalCellMaskCandidates",
    "widthCandidates",
    "heightCandidates",
    "spanCandidates",
    "clipped",
    "observations",
    "firstSeenSegment",
    "lastSeenSegment",
    "confidence",
    "reasons",
)

MIN_SPATIAL = 0.35
MIN_SIGNATURE = 0.55
SECOND_CANDIDATE_GAP = 0.08
PERIOD_TOL = 0.08
PHASE_SOFT = 0.22
PHASE_HARD = 0.38


class PhysicalComponentLedgerError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _box(values: Sequence[Any]) -> Tuple[float, float, float, float]:
    x1, y1, x2, y2 = (float(values[0]), float(values[1]), float(values[2]), float(values[3]))
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def _shift_box(box: Sequence[float], dx: float, dy: float) -> List[float]:
    return [float(box[0]) + dx, float(box[1]) + dy, float(box[2]) + dx, float(box[3]) + dy]


def _inter_min(a: Sequence[float], b: Sequence[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / min(area_a, area_b)


def _signature(frame: Any, box: Sequence[float]) -> Optional[List[float]]:
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    height, width = frame.shape[:2]
    x1 = max(0, min(width - 1, int(box[0])))
    y1 = max(0, min(height - 1, int(box[1])))
    x2 = max(x1 + 1, min(width, int(round(box[2]))))
    y2 = max(y1 + 1, min(height, int(round(box[3]))))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    if crop.ndim == 3:
        gray = crop.mean(axis=2)
    else:
        gray = crop
    small = _resize_area(gray, 8, 8)
    centered = small - float(small.mean())
    norm = float((centered ** 2).sum()) ** 0.5
    if norm < 1e-6:
        return [0.0] * 64
    return [float(value) / norm for value in centered.ravel()]


def _resize_area(gray: Any, width: int, height: int):
    import cv2
    import numpy as np

    array = np.asarray(gray, dtype=np.float32)
    return cv2.resize(array, (width, height), interpolation=cv2.INTER_AREA)


def _ncc(left: Optional[Sequence[float]], right: Optional[Sequence[float]]) -> Optional[float]:
    if not left or not right or len(left) != len(right):
        return None
    return float(sum(a * b for a, b in zip(left, right)))


def _mask_key(mask: Any) -> Tuple[Tuple[int, ...], ...]:
    if not isinstance(mask, list):
        return tuple()
    return tuple(tuple(int(cell) for cell in row) for row in mask)


def _complete(obs: Mapping[str, Any]) -> bool:
    return (
        str(obs.get("status") or "") == STATUS_OBSERVED
        and not obs.get("clippedTop")
        and not obs.get("clippedBottom")
    )


def _grid_period(grid: Mapping[str, Any]) -> Optional[Tuple[float, float]]:
    if str(grid.get("status") or "") != "OK":
        return None
    width = grid.get("cellWidth")
    height = grid.get("cellHeight")
    if width is None or height is None:
        return None
    return float(width), float(height)


def _phase_error(prev: Mapping[str, Any], curr: Mapping[str, Any]) -> Optional[float]:
    periods = _grid_period(prev)
    other = _grid_period(curr)
    if periods is None or other is None:
        return None
    if abs(periods[0] - other[0]) / max(periods[0], other[0]) > PERIOD_TOL:
        return None
    if abs(periods[1] - other[1]) / max(periods[1], other[1]) > PERIOD_TOL:
        return None
    prev_x = list(prev.get("xLines") or [])
    curr_x = list(curr.get("xLines") or [])
    if not prev_x or not curr_x:
        return None
    cell = periods[0]
    delta = abs(float(curr_x[0]) - float(prev_x[0])) % cell
    return float(min(delta, cell - delta)) / cell


class PhysicalComponentLedger:
    def __init__(self, record_stable_key: str):
        key = str(record_stable_key or "").strip()
        if not RECORD_KEY_RE.fullmatch(key):
            raise PhysicalComponentLedgerError("INVALID_RECORD_KEY", "recordStableKey rejected")
        self.record_stable_key = key
        self._segments: List[Dict[str, Any]] = []
        self._tracks: List[Dict[str, Any]] = []
        self._conflicts: List[Dict[str, Any]] = []
        self._obs_index: Dict[str, Dict[str, Any]] = {}
        self._chain_id = 0
        self._chain_open = False
        self._anchored = False
        self._broken = False

    def add_segment(
        self,
        observation: Mapping[str, Any],
        *,
        sequence_index: int,
        segment_id: str,
        overlap: Optional[Mapping[str, Any]] = None,
        scroll_state: str = "",
        frame: Any = None,
        record_stable_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(sequence_index, int) or isinstance(sequence_index, bool):
            raise PhysicalComponentLedgerError("INVALID_SEQUENCE_INDEX", "sequenceIndex must be an integer")
        if record_stable_key and str(record_stable_key).strip() != self.record_stable_key:
            self._broken = True
            self._chain_open = False
            self._conflicts.append({"code": REASON_STABLE_KEY_CHANGED, "segmentId": segment_id})
            return self.snapshot()

        payload = _as_mapping(observation)
        components = [item for item in (payload.get("components") or []) if isinstance(item, Mapping)]
        grid = _as_mapping(payload.get("grid"))
        digest = _observation_digest(payload, components)

        for existing in self._segments:
            if existing["segmentId"] == segment_id or (
                existing["sequenceIndex"] == sequence_index and existing["digest"] == digest
            ):
                return self.snapshot()

        origin_y = 0.0
        chain_ok = True
        reasons: List[str] = []
        if self._segments:
            previous = self._segments[-1]
            if sequence_index <= previous["sequenceIndex"]:
                self._conflicts.append({"code": "ORDER_CONFLICT", "segmentId": segment_id})
                return self.snapshot()
            if sequence_index != previous["sequenceIndex"] + 1:
                chain_ok = False
                reasons.append(REASON_SEQUENCE_GAP)
            link = _as_mapping(overlap)
            status = str(link.get("status") or ("VERIFIED" if link.get("aligned") and link.get("trusted") else ""))
            offset = link.get("verticalOffsetPx") if link.get("verticalOffsetPx") is not None else (-float(link["offsetY"]) if "offsetY" in link else None)
            direction = str(link.get("direction") or (DIR_DOWN if (offset is not None and offset < 0) else (DIR_UP if (offset is not None and offset > 0) else "")))
            is_no_movement = (
                direction == DIR_NONE
                or link.get("reason") == REASON_NO_MOVEMENT
                or (offset is not None and abs(float(offset)) <= 3.0)
            )

            if status == STATUS_CONFLICT:
                chain_ok = False
                reasons.append(REASON_OVERLAP_CONFLICT)
            elif is_no_movement:
                origin_y = float(previous["originY"])
                phase = _phase_error(previous["grid"], grid)
                if phase is None or phase > PHASE_HARD:
                    chain_ok = False
                    reasons.append(REASON_GRID_PHASE_MISALIGNED)
                elif phase > PHASE_SOFT:
                    reasons.append(REASON_PIXEL_ONLY)
            elif status == STATUS_VERIFIED and offset is not None and direction in {DIR_DOWN, DIR_UP}:
                origin_y = float(previous["originY"]) - float(offset)
                if origin_y < -15.0:
                    chain_ok = False
                    reasons.append(REASON_DIRECTION_REVERSED)
                else:
                    phase = _phase_error(previous["grid"], grid)
                    if phase is None or phase > PHASE_HARD:
                        chain_ok = False
                        reasons.append(REASON_GRID_PHASE_MISALIGNED)
                    elif phase > PHASE_SOFT:
                        reasons.append(REASON_PIXEL_ONLY)
            else:
                chain_ok = False
                reasons.append(REASON_UNVERIFIED_OVERLAP)
            if not chain_ok:
                self._broken = True
                self._chain_open = False
                self._chain_id += 1
                origin_y = float(previous["originY"])
        else:
            if str(scroll_state or "").upper() in {"TOP", "NO_SCROLL"}:
                self._anchored = True
            else:
                reasons.append(REASON_UNANCHORED)
            self._chain_open = True

        if chain_ok and self._segments:
            self._chain_open = True

        cell_aligned = REASON_PIXEL_ONLY not in reasons and chain_ok and _grid_period(grid) is not None
        if not self._anchored:
            reasons.append(REASON_UNANCHORED)

        segment = {
            "segmentId": str(segment_id),
            "sequenceIndex": sequence_index,
            "scrollState": str(scroll_state or ""),
            "originY": float(origin_y),
            "chainId": self._chain_id,
            "chainOk": bool(chain_ok and (self._anchored or not self._segments)),
            "cellAligned": bool(cell_aligned),
            "grid": dict(grid),
            "digest": digest,
            "observationIds": [],
        }

        for raw in components:
            obs = self._materialize_observation(raw, segment, frame, reasons)
            if obs is None:
                continue
            existing = self._obs_index.get(obs["observationId"])
            if existing is not None:
                if existing["contentDigest"] != obs["contentDigest"]:
                    self._conflicts.append({
                        "code": REASON_OBSERVATION_CONFLICT,
                        "observationId": obs["observationId"],
                    })
                    track = self._track_by_id(existing.get("trackId"))
                    if track is not None:
                        track["status"] = STATUS_CONFLICT
                        self._add_reason(track, REASON_OBSERVATION_CONFLICT)
                continue
            self._obs_index[obs["observationId"]] = obs
            segment["observationIds"].append(obs["observationId"])
            self._assign_track(obs, segment)

        self._segments.append(segment)
        return self.snapshot()

    def _materialize_observation(
        self,
        raw: Mapping[str, Any],
        segment: Mapping[str, Any],
        frame: Any,
        segment_reasons: Sequence[str],
    ) -> Optional[Dict[str, Any]]:
        obs_id = str(raw.get("observationId") or "").strip()
        box = raw.get("boundingBox")
        if not obs_id or not isinstance(box, (list, tuple)) or len(box) != 4:
            return None
        local = _box(box)
        global_box = _shift_box(local, 0.0, float(segment["originY"]))
        signature = _signature(frame, local)
        clipped = bool(raw.get("clippedTop") or raw.get("clippedBottom"))
        digest_src = {
            "box": [round(float(v), 4) for v in local],
            "mask": raw.get("cellMask"),
            "w": raw.get("widthCells"),
            "h": raw.get("heightCells"),
            "span": raw.get("spanCells"),
        }
        return {
            "observationId": obs_id,
            "segmentId": segment["segmentId"],
            "sequenceIndex": segment["sequenceIndex"],
            "chainId": segment["chainId"],
            "sourceFrame": raw.get("sourceFrame"),
            "timecode": raw.get("timecode"),
            "localBox": list(local),
            "globalBox": global_box,
            "cellMask": raw.get("cellMask"),
            "widthCells": raw.get("widthCells"),
            "heightCells": raw.get("heightCells"),
            "spanCells": raw.get("spanCells"),
            "clippedTop": bool(raw.get("clippedTop")),
            "clippedBottom": bool(raw.get("clippedBottom")),
            "clipped": clipped,
            "status": str(raw.get("status") or STATUS_AMBIGUOUS),
            "complete": _complete(raw),
            "signature": signature,
            "contentDigest": hashlib.sha256(
                json.dumps(digest_src, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
            "pixelOnly": REASON_PIXEL_ONLY in segment_reasons,
            "trackId": None,
        }

    def _assign_track(self, obs: Dict[str, Any], segment: Mapping[str, Any]) -> None:
        candidates: List[Tuple[float, Dict[str, Any]]] = []
        if segment["chainOk"]:
            for track in self._tracks:
                if track["_chainId"] != segment["chainId"]:
                    continue
                score = self._match_score(track, obs)
                if score is not None:
                    candidates.append((score, track))
        candidates.sort(key=lambda item: item[0], reverse=True)
        chosen = None
        if candidates:
            best_score, best = candidates[0]
            second = candidates[1][0] if len(candidates) > 1 else -1.0
            if second >= 0 and best_score - second < SECOND_CANDIDATE_GAP:
                self._add_reason(best, REASON_AMBIGUOUS_CANDIDATE)
            else:
                chosen = best
        if chosen is None:
            chosen = self._new_track(obs, segment)
            self._tracks.append(chosen)
        self._attach(chosen, obs, segment)

    def _match_score(self, track: Mapping[str, Any], obs: Mapping[str, Any]) -> Optional[float]:
        spatial = _inter_min(track["_searchBox"], obs["globalBox"])
        if spatial < MIN_SPATIAL:
            return None
        width_ok = self._width_compatible(track, obs)
        height_ok = self._height_compatible(track, obs)
        if not width_ok and not height_ok:
            return None
        if not width_ok and obs.get("widthCells") == track.get("_width") and not spatial:
            return None
        if width_ok is False:
            return None
        signature = _ncc(track.get("_signature"), obs.get("signature"))
        if signature is not None and signature < MIN_SIGNATURE:
            return None
        score = spatial
        if width_ok:
            score += 0.15
        if height_ok:
            score += 0.08
        if signature is not None:
            score += 0.25 * signature
        mask_a = _mask_key(track.get("_mask"))
        mask_b = _mask_key(obs.get("cellMask"))
        if mask_a and mask_b and mask_a == mask_b:
            score += 0.05
        return score

    def _width_compatible(self, track: Mapping[str, Any], obs: Mapping[str, Any]) -> bool:
        left = track.get("_width")
        right = obs.get("widthCells")
        if left is None or right is None:
            return True
        return int(left) == int(right)

    def _height_compatible(self, track: Mapping[str, Any], obs: Mapping[str, Any]) -> Optional[bool]:
        left = track.get("_height")
        right = obs.get("heightCells")
        if left is None or right is None:
            return True
        if track.get("_clipped") or obs.get("clipped"):
            return True
        return int(left) == int(right)

    def _new_track(self, obs: Mapping[str, Any], segment: Mapping[str, Any]) -> Dict[str, Any]:
        track_id = f"pct1_{self.record_stable_key}_{obs['observationId']}"
        return {
            "trackId": track_id,
            "status": STATUS_AMBIGUOUS,
            "globalBoundingBox": list(obs["globalBox"]),
            "globalCellMaskCandidates": [],
            "widthCandidates": [],
            "heightCandidates": [],
            "spanCandidates": [],
            "clipped": bool(obs["clipped"]),
            "observations": [],
            "firstSeenSegment": segment["segmentId"],
            "lastSeenSegment": segment["segmentId"],
            "confidence": 0.4,
            "reasons": [REASON_UNANCHORED] if not self._anchored else [],
            "_chainId": segment["chainId"],
            "_searchBox": list(obs["globalBox"]),
            "_width": obs.get("widthCells"),
            "_height": obs.get("heightCells"),
            "_span": obs.get("spanCells"),
            "_mask": obs.get("cellMask"),
            "_signature": obs.get("signature"),
            "_clipped": bool(obs["clipped"]),
            "_complete": False,
        }

    def _attach(self, track: Dict[str, Any], obs: Dict[str, Any], segment: Mapping[str, Any]) -> None:
        obs["trackId"] = track["trackId"]
        track["observations"].append({
            "observationId": obs["observationId"],
            "segmentId": obs["segmentId"],
            "sourceFrame": obs.get("sourceFrame"),
            "timecode": obs.get("timecode"),
            "globalBox": [float(v) for v in obs["globalBox"]],
            "widthCells": obs.get("widthCells"),
            "heightCells": obs.get("heightCells"),
            "spanCells": obs.get("spanCells"),
            "clippedTop": obs.get("clippedTop"),
            "clippedBottom": obs.get("clippedBottom"),
            "status": obs.get("status"),
        })
        track["lastSeenSegment"] = segment["segmentId"]
        track["_searchBox"] = _union_box(track["_searchBox"], obs["globalBox"])
        track["_clipped"] = bool(track["_clipped"] or obs["clipped"])
        self._push_unique(track["widthCandidates"], obs.get("widthCells"))
        self._push_unique(track["heightCandidates"], obs.get("heightCells"))
        self._push_unique(track["spanCandidates"], obs.get("spanCells"))
        if obs.get("cellMask") is not None:
            candidate = {
                "segmentId": segment["segmentId"],
                "viewportRow": None,
                "originY": float(segment["originY"]),
                "cellMask": obs.get("cellMask"),
            }
            if candidate not in track["globalCellMaskCandidates"]:
                track["globalCellMaskCandidates"].append(candidate)
        if obs["complete"] and not track["_complete"]:
            track["_complete"] = True
            track["_width"] = obs.get("widthCells")
            track["_height"] = obs.get("heightCells")
            track["_span"] = obs.get("spanCells")
            track["_mask"] = obs.get("cellMask")
            track["globalBoundingBox"] = list(obs["globalBox"])
            if obs.get("signature") is not None:
                track["_signature"] = obs.get("signature")
        elif not track["_complete"]:
            track["globalBoundingBox"] = list(track["_searchBox"])
            if track["_width"] is None:
                track["_width"] = obs.get("widthCells")
            if track["_height"] is None:
                track["_height"] = obs.get("heightCells")
        if obs.get("signature") is not None and track.get("_signature") is None:
            track["_signature"] = obs.get("signature")
        if track["_complete"]:
            track["status"] = STATUS_OBSERVED
            track["clipped"] = False
            track["confidence"] = 0.86
        else:
            track["status"] = STATUS_AMBIGUOUS
            track["clipped"] = True
            track["confidence"] = 0.52
            self._add_reason(track, REASON_CLIPPED_ONLY)
        if obs.get("pixelOnly") or not segment.get("cellAligned"):
            self._add_reason(track, REASON_PIXEL_ONLY)
            if track["status"] == STATUS_OBSERVED:
                track["status"] = STATUS_AMBIGUOUS
        if not self._anchored:
            track["status"] = STATUS_AMBIGUOUS
            self._add_reason(track, REASON_UNANCHORED)

    def _push_unique(self, values: List[Any], item: Any) -> None:
        if item is None:
            return
        if item not in values:
            values.append(item)

    def _add_reason(self, track: Dict[str, Any], reason: str) -> None:
        if reason not in track["reasons"]:
            track["reasons"].append(reason)

    def _track_by_id(self, track_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not track_id:
            return None
        for track in self._tracks:
            if track["trackId"] == track_id:
                return track
        return None

    def snapshot(self) -> Dict[str, Any]:
        if self._broken and not self._chain_open:
            chain = CHAIN_BROKEN
        elif self._anchored:
            chain = CHAIN_ACTIVE
        else:
            chain = CHAIN_UNANCHORED
        tracks = []
        for track in sorted(
            self._tracks,
            key=lambda item: (
                item["observations"][0]["segmentId"] if item["observations"] else "",
                item["globalBoundingBox"][1] if item["globalBoundingBox"] else 0.0,
                item["globalBoundingBox"][0] if item["globalBoundingBox"] else 0.0,
                item["trackId"],
            ),
        ):
            public = {key: track[key] for key in TRACK_KEYS}
            public["observations"] = [dict(item) for item in track["observations"]]
            public["globalCellMaskCandidates"] = [dict(item) for item in track["globalCellMaskCandidates"]]
            public["widthCandidates"] = list(track["widthCandidates"])
            public["heightCandidates"] = list(track["heightCandidates"])
            public["spanCandidates"] = list(track["spanCandidates"])
            public["reasons"] = list(track["reasons"])
            public["globalBoundingBox"] = [float(v) for v in track["globalBoundingBox"]]
            tracks.append(public)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "recordStableKey": self.record_stable_key,
            "chainStatus": chain,
            "segments": [
                {
                    "segmentId": item["segmentId"],
                    "sequenceIndex": item["sequenceIndex"],
                    "scrollState": item["scrollState"],
                    "originY": item["originY"],
                    "chainId": item["chainId"],
                    "observationCount": len(item["observationIds"]),
                }
                for item in self._segments
            ],
            "tracks": tracks,
            "conflicts": [dict(item) for item in self._conflicts],
        }


def _union_box(left: Sequence[float], right: Sequence[float]) -> List[float]:
    return [
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    ]


def _observation_digest(payload: Mapping[str, Any], components: Sequence[Mapping[str, Any]]) -> str:
    body = {
        "ids": [str(item.get("observationId") or "") for item in components],
        "boxes": [item.get("boundingBox") for item in components],
        "masks": [item.get("cellMask") for item in components],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()
