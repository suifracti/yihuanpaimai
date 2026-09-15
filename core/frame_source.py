# -*- coding: utf-8 -*-
"""Live and replay share one worker loop; only the frame source differs."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

FrameTuple = Tuple[Optional[int], Optional[np.ndarray], str]
FrameProvider = Callable[[], FrameTuple]


def _tz8() -> timezone:
    return timezone(timedelta(hours=8))


class KeyframeDirectorySource:
    """JPEG/PNG sequence used by CONFIG replay mode. Fake hwnd keeps the live loop.

    hold_last keeps the last file in view like a frozen camera so scene
    confirmation and settlement stability can finish. Repeating one still is
    the same physical frame, not a new capture.
    """

    def __init__(
        self,
        directory: str,
        stop_flag: Optional[Dict[str, bool]] = None,
        fake_hwnd: int = 1,
        hold_last: bool = False,
    ):
        root = Path(directory)
        suffixes = {".jpg", ".jpeg", ".png"}
        named = sorted(
            p for p in root.iterdir()
            if p.name.startswith("frame_") and p.suffix.lower() in suffixes
        ) if root.is_dir() else []
        self.paths: List[Path] = named or (
            sorted(p for p in root.iterdir() if p.suffix.lower() in suffixes) if root.is_dir() else []
        )
        self.index = 0
        self.stop_flag = stop_flag
        self.fake_hwnd = fake_hwnd
        self.hold_last = hold_last
        self.eof = False
        self._hold_stamp: Optional[str] = None

    def content_fingerprint(self) -> Optional[str]:
        """SHA-256 of unique file bytes. One still is one source, not N observations."""
        if not self.paths:
            return None
        seen = []
        found = set()
        for path in self.paths:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest not in found:
                found.add(digest)
                seen.append(digest)
        if len(seen) == 1:
            return seen[0]
        joined = hashlib.sha256()
        for digest in seen:
            joined.update(digest.encode("ascii"))
        return joined.hexdigest()

    def provide(self) -> FrameTuple:
        import cv2
        if self.stop_flag is not None and self.stop_flag.get("stop"):
            self.eof = True
            return None, None, "EOF"
        if self.index >= len(self.paths):
            if self.hold_last and self.paths:
                path = self.paths[-1]
                img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
                stamp = self._hold_stamp or datetime.now(tz=_tz8()).isoformat()
                self._hold_stamp = stamp
                return self.fake_hwnd, img, stamp
            self.eof = True
            if self.stop_flag is not None:
                self.stop_flag["stop"] = True
            return None, None, "EOF"
        path = self.paths[self.index]
        self.index += 1
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        stamp = datetime.now(tz=_tz8()).isoformat()
        if self.hold_last and self.paths and path == self.paths[-1]:
            self._hold_stamp = stamp
        return self.fake_hwnd, img, stamp


class VideoCaptureSource:
    """Decode a real match recording. Fake hwnd so replay never binds a live game window."""

    def __init__(
        self,
        video_path: str,
        *,
        stop_flag: Optional[Dict[str, bool]] = None,
        fake_hwnd: int = 1,
        min_interval_s: float = 1.0,
    ):
        import cv2
        self.path = Path(video_path)
        self.cap = cv2.VideoCapture(str(self.path))
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
        self.step = max(1, int(round(self.fps * min_interval_s)))
        self.frame_index = 0
        self.stop_flag = stop_flag
        self.fake_hwnd = fake_hwnd
        self.eof = False
        stem = self.path.stem
        try:
            self.origin = datetime.strptime(stem, "%Y-%m-%d %H-%M-%S").replace(tzinfo=_tz8())
        except ValueError:
            self.origin = datetime.now(tz=_tz8())

    def provide(self) -> FrameTuple:
        if self.eof:
            if self.stop_flag is not None:
                self.stop_flag["stop"] = True
            return None, None, "EOF"
        while True:
            ok = self.cap.grab()
            if not ok:
                self.eof = True
                self.cap.release()
                if self.stop_flag is not None:
                    self.stop_flag["stop"] = True
                return None, None, "EOF"
            if self.frame_index % self.step == 0:
                retrieved, frame = self.cap.retrieve()
                second = self.frame_index / self.fps
                self.frame_index += 1
                if not retrieved or frame is None:
                    continue
                stamp = (self.origin + timedelta(seconds=second)).isoformat(timespec="milliseconds")
                return self.fake_hwnd, frame, stamp
            self.frame_index += 1
