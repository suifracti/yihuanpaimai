"""Read-only reveal evidence on the verified original; never an input or pass gate."""
import hashlib
from pathlib import Path

import cv2
import numpy as np

from visual_catalog import asset_root


class RevealMarker:
    ROI = (1440, 984, 1558, 1011)

    def __init__(self, template=None):
        path = Path(template) if template is not None else asset_root() / 'assets/scene_anchors/skip_animation_text.png'
        raw = path.read_bytes()
        self.hash = hashlib.sha256(raw).hexdigest()
        self.template = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if self.template is None or self.template.shape != (27, 118) or self.template.std() < 8:
            raise ValueError('REVEAL_MARKER_ASSET_UNPROVEN')

    def observe(self, frame):
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
            raise ValueError('REVEAL_MARKER_GEOMETRY_UNPROVEN')
        h, w = frame.shape[:2]
        if abs(w / h - 16 / 9) >= .02:
            raise ValueError('REVEAL_MARKER_GEOMETRY_UNPROVEN')
        x1, y1, x2, y2 = [round(v * (w / 1920 if i % 2 == 0 else h / 1080))
            for i, v in enumerate(self.ROI)]
        if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
            raise ValueError('REVEAL_MARKER_GEOMETRY_UNPROVEN')
        gray = cv2.cvtColor(cv2.resize(frame[y1:y2, x1:x2], (118, 27)), cv2.COLOR_BGR2GRAY)
        score = float(cv2.matchTemplate(gray, self.template, cv2.TM_CCOEFF_NORMED)[0, 0])
        if not np.isfinite(score):
            raise ValueError('REVEAL_MARKER_READ_UNPROVEN')
        return {'status': 'PRESENT' if score >= .88 else 'NOT_DETECTED', 'score': score,
            'templateSha256': self.hash, 'roi': [x1, y1, x2, y2],
            'meaning': 'positive skip-animation text shape only; absence is not completion proof'}
