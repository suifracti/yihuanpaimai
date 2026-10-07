"""Bounded same-viewport admission; never infer global warehouse coordinates.

One stationary image/scrollbar anchor per match can support local identity facts.
Different or unprovable views remain observations, not an additive item ledger.
Returning to a proved anchor is permitted. This is evidence scope, not lifecycle.
"""
import hashlib
import numpy as np
from warehouse_scrollbar_observation import observe_warehouse_scrollbar, warehouse_search_roi
from warehouse_support_frame import stationary_support_proof


class WarehouseViewportScope:
    def __init__(self):
        self.match_id = None
        self.anchor = self.previous = None
        self.key = None
        self.current_key = None

    @staticmethod
    def _same(a, b):
        if a is None or b is None or a[0].shape != b[0].shape:
            return False
        if a[1] != b[1]:
            return False
        # Fresh transport sequences already distinguish an identical stationary
        # image from reusing an old frame. Textured equality is valid here.
        if np.array_equal(a[0], b[0]):
            return float(a[0].std()) >= 8
        return stationary_support_proof(a[0], b[0]) is not None

    def observe(self, match_id, frame, *, scrollbar=None):
        if self.match_id != match_id:
            self.__init__()
            self.match_id = match_id
        self.current_key = None
        bar = scrollbar if scrollbar is not None else observe_warehouse_scrollbar(frame)
        if bar.get("scrollState") == "UNKNOWN" or bar.get("thumbPosition") is None:
            self.previous = None
            return None
        x1, y1, x2, y2 = warehouse_search_roi(frame.shape[1], frame.shape[0])
        # Keep grid pixels, excluding the right-edge slider and panel controls.
        crop = frame[y1:y2, x1:x1 + max(1, int((x2-x1)*.75))]
        if crop.size == 0:
            self.previous = None
            return None
        sample = (crop.copy(), (bar.get("trackBox"), bar.get("thumbBox"),
                               bar.get("thumbPosition"), bar.get("thumbLength")))
        if self.anchor is None and self._same(self.previous, sample):
            self.anchor = sample
            self.key = f"{match_id}:viewport:{hashlib.sha256(crop.tobytes()).hexdigest()}"
        if self._same(self.anchor, sample):
            self.current_key = self.key
        self.previous = sample
        return self.current_key

    def permits(self, key):
        return bool(key and key == self.key and key == self.current_key)
