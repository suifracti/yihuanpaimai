"""Isolated tests for the cross-segment physical component ledger."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(CORE_DIR),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_grid_geometry import observe_warehouse_grid
from warehouse_physical_ledger import (
    CHAIN_ACTIVE,
    CHAIN_BROKEN,
    REASON_OBSERVATION_CONFLICT,
    STATUS_AMBIGUOUS,
    STATUS_CONFLICT,
    STATUS_OBSERVED,
    PhysicalComponentLedger,
)
from warehouse_segment_overlap import (
    DIR_DOWN,
    DIR_UP,
    STATUS_CONFLICT as OVERLAP_CONFLICT,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    align_warehouse_segments,
)

OVERLAP = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_overlap_v1"
EXPECT = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_physical_ledger_v1" / "expectations.json"
FORBIDDEN = ("rarity", "name", "price", "catalog", "knownItems", "itemId", "quality")


def _load(name: str) -> np.ndarray:
    path = OVERLAP / name
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return image


def _obs(name: str, timecode: float):
    frame = _load(name)
    return frame, observe_warehouse_grid(frame, already_cropped=True, source_id=name, timecode=timecode)


def _overlap(prev, nxt, prev_id, next_id):
    return align_warehouse_segments(prev, nxt, prev_id=prev_id, next_id=next_id, required_direction=DIR_DOWN)


class WarehousePhysicalLedgerV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expect = json.loads(EXPECT.read_text(encoding="utf-8"))
        cls.img8, cls.obs8 = _obs("pair_a_prev.png", 8.0)
        cls.img12, cls.obs12 = _obs("pair_a_next.png", 12.0)
        cls.img16, cls.obs16 = _obs("pair_b_next.png", 16.0)
        cls.img40, cls.obs40 = _obs("bottom.png", 40.0)
        cls.link_8_12 = _overlap(cls.img8, cls.img12, "8s", "12s")
        cls.link_12_16 = _overlap(cls.img12, cls.img16, "12s", "16s")

    def _seed_chain(self) -> PhysicalComponentLedger:
        ledger = PhysicalComponentLedger("recWHPhys01")
        ledger.add_segment(self.obs8, sequence_index=0, segment_id="seg8", scroll_state="TOP", frame=self.img8)
        ledger.add_segment(
            self.obs12,
            sequence_index=1,
            segment_id="seg12",
            overlap=self.link_8_12,
            scroll_state="MIDDLE",
            frame=self.img12,
        )
        ledger.add_segment(
            self.obs16,
            sequence_index=2,
            segment_id="seg16",
            overlap=self.link_12_16,
            scroll_state="MIDDLE",
            frame=self.img16,
        )
        return ledger

    def test_fixture_is_developer_expectation_only(self):
        self.assertEqual(self.expect["kind"], "DEVELOPER_FIXTURE_EXPECTATION")
        self.assertTrue(self.expect["notGroundTruth"])
        self.assertTrue(self.expect["notTrainingLabel"])
        self.assertEqual(self.link_8_12["status"], STATUS_VERIFIED)
        self.assertEqual(self.link_8_12["direction"], DIR_DOWN)
        self.assertEqual(self.link_8_12["verticalOffsetPx"], -90)
        self.assertEqual(self.link_12_16["verticalOffsetPx"], -120)
        self.assertLess(self.link_8_12["verticalOffsetPx"], 0)

    def test_verified_chain_does_not_duplicate_same_component(self):
        snap = self._seed_chain().snapshot()
        self.assertEqual(snap["chainStatus"], CHAIN_ACTIVE)
        self.assertEqual([item["originY"] for item in snap["segments"]], [0.0, 90.0, 210.0])
        shared = [
            track
            for track in snap["tracks"]
            if 5 in track["widthCandidates"]
            and any(obs["segmentId"] == "seg8" for obs in track["observations"])
            and any(obs["segmentId"] == "seg16" for obs in track["observations"])
        ]
        self.assertTrue(shared, [ (t["trackId"], t["widthCandidates"], [o["segmentId"] for o in t["observations"]]) for t in snap["tracks"] if 5 in t["widthCandidates"] ])
        self.assertGreaterEqual(len(shared[0]["observations"]), 3)
        self.assertEqual(len(shared), 1)
        ids = [obs["observationId"] for obs in shared[0]["observations"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_new_viewport_components_create_new_tracks(self):
        ledger = PhysicalComponentLedger("recWHPhys01")
        first = ledger.add_segment(self.obs8, sequence_index=0, segment_id="seg8", scroll_state="TOP", frame=self.img8)
        before = {track["trackId"] for track in first["tracks"]}
        second = ledger.add_segment(
            self.obs12,
            sequence_index=1,
            segment_id="seg12",
            overlap=self.link_8_12,
            scroll_state="MIDDLE",
            frame=self.img12,
        )
        after = {track["trackId"] for track in second["tracks"]}
        self.assertTrue(after - before)
        self.assertTrue(before & after)

    def test_same_shape_different_global_position_does_not_merge(self):
        ledger = PhysicalComponentLedger("recWHPhys02")
        ones = [item for item in self.obs8["components"] if item["widthCells"] == 1 and item["heightCells"] == 1]
        self.assertGreaterEqual(len(ones), 2)
        fake = {
            "grid": self.obs8["grid"],
            "components": ones[:2],
        }
        snap = ledger.add_segment(fake, sequence_index=0, segment_id="segA", scroll_state="TOP", frame=self.img8)
        tracks = [
            track for track in snap["tracks"]
            if track["widthCandidates"] == [1] and track["heightCandidates"] == [1]
        ]
        self.assertGreaterEqual(len(tracks), 2)

    def test_clipped_fragments_stay_ambiguous_until_complete_geometry(self):
        ledger = PhysicalComponentLedger("recWHPhys01")
        ledger.add_segment(self.obs8, sequence_index=0, segment_id="seg8", scroll_state="TOP", frame=self.img8)
        snap = ledger.snapshot()
        clipped = [track for track in snap["tracks"] if track["clipped"]]
        self.assertTrue(clipped)
        self.assertTrue(all(track["status"] == STATUS_AMBIGUOUS for track in clipped))
        full = next(item for item in self.obs8["components"] if item["status"] == "OBSERVED" and not item["clippedTop"] and not item["clippedBottom"])
        later = {
            "grid": self.obs8["grid"],
            "components": [full],
        }
        # A later complete view on a new unlinked chain must not invent identity fields.
        other = PhysicalComponentLedger("recWHPhys03")
        other.add_segment({"grid": self.obs8["grid"], "components": [
            {**full, "clippedTop": True, "clippedBottom": False, "status": "AMBIGUOUS", "observationId": "frag-1"}
        ]}, sequence_index=0, segment_id="s0", scroll_state="TOP", frame=self.img8)
        promoted = other.add_segment(
            {"grid": self.obs12["grid"], "components": [{**full, "observationId": "full-1", "sourceFrame": "later"}]},
            sequence_index=1,
            segment_id="s1",
            overlap=self.link_8_12,
            scroll_state="MIDDLE",
            frame=self.img12,
        )
        blob = json.dumps(promoted)
        for token in FORBIDDEN:
            self.assertNotIn(token, blob)

    def test_unverified_and_reverse_offsets_break_the_chain(self):
        ledger = PhysicalComponentLedger("recWHPhys04")
        ledger.add_segment(self.obs8, sequence_index=0, segment_id="seg8", scroll_state="TOP", frame=self.img8)
        before = len(ledger.snapshot()["tracks"])
        broken = ledger.add_segment(
            self.obs16,
            sequence_index=1,
            segment_id="seg16",
            overlap={"status": STATUS_UNVERIFIED, "direction": "UNKNOWN", "verticalOffsetPx": None},
            scroll_state="MIDDLE",
            frame=self.img16,
        )
        self.assertEqual(broken["chainStatus"], CHAIN_BROKEN)
        self.assertGreaterEqual(len(broken["tracks"]), before)
        # New observations after the break must not attach to pre-break tracks.
        pre_ids = {track["trackId"] for track in ledger.snapshot()["tracks"] if track["firstSeenSegment"] == "seg8"}
        for track in broken["tracks"]:
            segs = {obs["segmentId"] for obs in track["observations"]}
            if "seg16" in segs:
                self.assertNotIn("seg8", segs)

        reverse = PhysicalComponentLedger("recWHPhys05")
        reverse.add_segment(self.obs8, sequence_index=0, segment_id="seg8", scroll_state="TOP", frame=self.img8)
        rev = reverse.add_segment(
            self.obs12,
            sequence_index=1,
            segment_id="seg12",
            overlap={"status": OVERLAP_CONFLICT, "direction": DIR_UP, "verticalOffsetPx": 90},
            scroll_state="MIDDLE",
            frame=self.img12,
        )
        self.assertEqual(rev["chainStatus"], CHAIN_BROKEN)

    def test_empty_bottom_does_not_delete_tracks_and_duplicate_is_idempotent(self):
        ledger = self._seed_chain()
        before = ledger.snapshot()
        after_empty = ledger.add_segment(
            self.obs40,
            sequence_index=3,
            segment_id="seg40",
            overlap={"status": STATUS_UNVERIFIED, "direction": "UNKNOWN", "verticalOffsetPx": None},
            scroll_state="BOTTOM",
            frame=self.img40,
        )
        self.assertGreaterEqual(len(after_empty["tracks"]), len(before["tracks"]))
        again = ledger.add_segment(
            self.obs40,
            sequence_index=3,
            segment_id="seg40",
            overlap={"status": STATUS_UNVERIFIED, "direction": "UNKNOWN"},
            scroll_state="BOTTOM",
            frame=self.img40,
        )
        self.assertEqual(again, after_empty)
        replay = ledger.add_segment(self.obs8, sequence_index=0, segment_id="seg8", scroll_state="TOP", frame=self.img8)
        self.assertEqual(len(replay["segments"]), len(after_empty["segments"]))

    def test_same_observation_id_different_content_is_conflict(self):
        ledger = PhysicalComponentLedger("recWHPhys06")
        first = copy.deepcopy(self.obs8)
        first["components"] = first["components"][:1]
        ledger.add_segment(first, sequence_index=0, segment_id="seg8", scroll_state="TOP", frame=self.img8)
        mutated = copy.deepcopy(first)
        mutated["components"][0] = dict(mutated["components"][0])
        mutated["components"][0]["boundingBox"] = [10, 10, 80, 80]
        mutated["components"][0]["widthCells"] = 9
        snap = ledger.add_segment(
            mutated,
            sequence_index=1,
            segment_id="seg9",
            overlap=self.link_8_12,
            scroll_state="MIDDLE",
            frame=self.img12,
        )
        self.assertTrue(any(item["code"] == REASON_OBSERVATION_CONFLICT for item in snap["conflicts"]))
        self.assertTrue(any(track["status"] == STATUS_CONFLICT for track in snap["tracks"]))

    def test_output_is_deterministic_and_closed(self):
        first = self._seed_chain().snapshot()
        second = self._seed_chain().snapshot()
        self.assertEqual(first, second)
        self.assertEqual([track["trackId"] for track in first["tracks"]], [track["trackId"] for track in second["tracks"]])
        blob = json.dumps(first)
        for token in FORBIDDEN:
            self.assertNotIn(token, blob)
        for track in first["tracks"]:
            self.assertTrue(track["trackId"].startswith("pct1_recWHPhys01_"))
            self.assertTrue(track["observations"])
            self.assertIn(track["status"], {STATUS_OBSERVED, STATUS_AMBIGUOUS, STATUS_CONFLICT})


if __name__ == "__main__":
    unittest.main()
