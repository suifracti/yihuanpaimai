# -*- coding: utf-8 -*-
"""Deterministic Replay Frame Source Harness.

Feeds pre-recorded video frames / screenshot sequence into the production
vision_worker_loop and binds AsyncTriggeredSnapshotController to the current replay frame.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np


class ReplayFrameSource:
    """Sequential deterministic frame provider for vision worker loop."""

    def __init__(
        self,
        frame_paths: List[Path | str],
        *,
        fake_hwnd: int = 1001,
        loop: bool = False,
    ):
        self.frame_paths = [Path(p) for p in frame_paths]
        self.fake_hwnd = fake_hwnd
        self.loop = loop
        self.current_index = 0
        self._current_frame: Optional[np.ndarray] = None
        self._current_path: Optional[Path] = None
        self._current_timestamp: str = "2026-08-31T21:54:00+08:00"
        self._hooks: Dict[int, List[Callable[[ReplayFrameSource], None]]] = {}
        self._name_hooks: Dict[str, List[Callable[[ReplayFrameSource], None]]] = {}

    @classmethod
    def from_directory(
        cls,
        directory: Path | str,
        pattern: str = "*.jpg",
        *,
        fake_hwnd: int = 1001,
        loop: bool = False,
    ) -> "ReplayFrameSource":
        dir_path = Path(directory)
        paths = sorted(dir_path.glob(pattern))
        return cls(paths, fake_hwnd=fake_hwnd, loop=loop)

    def on_frame_index(self, index: int, callback: Callable[[ReplayFrameSource], None]) -> None:
        self._hooks.setdefault(index, []).append(callback)

    def on_frame_name(self, name_substr: str, callback: Callable[[ReplayFrameSource], None]) -> None:
        self._name_hooks.setdefault(name_substr, []).append(callback)

    def get_current_frame(self) -> Optional[np.ndarray]:
        return self._current_frame

    @property
    def current_path(self) -> Optional[Path]:
        return self._current_path

    @property
    def current_frame_name(self) -> str:
        return self._current_path.name if self._current_path else ""

    def provide_frame(self) -> Tuple[Optional[int], Optional[np.ndarray], str]:
        """Contract matching worker frame_provider -> (hwnd, img_bgr, timestamp)."""
        if self.current_index >= len(self.frame_paths):
            if self.loop and self.frame_paths:
                self.current_index = 0
            else:
                return None, None, ""

        frame_path = self.frame_paths[self.current_index]
        self._current_path = frame_path

        # Load image safely across unicode paths on Windows
        img = cv2.imdecode(np.fromfile(str(frame_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            img = cv2.imread(str(frame_path))
        self._current_frame = img

        idx = self.current_index
        self.current_index += 1

        # Execute hooks for current frame
        for cb in self._hooks.get(idx, []):
            try:
                cb(self)
            except Exception as e:
                print(f"[ReplayFrameSource] Hook error at index {idx}: {e}")

        for name_sub, cbs in self._name_hooks.items():
            if name_sub in frame_path.name:
                for cb in cbs:
                    try:
                        cb(self)
                    except Exception as e:
                        print(f"[ReplayFrameSource] Hook error on '{name_sub}': {e}")

        return self.fake_hwnd, img, self._current_timestamp


class ReplayCaptureManager:
    """Mock WindowCaptureManager returning the active replay frame."""

    def __init__(self, replay_source: ReplayFrameSource):
        self.replay_source = replay_source

    def capture_game_client(self, hwnd: Optional[int] = None, sct: Any = None) -> Tuple[Optional[np.ndarray], str]:
        frame = self.replay_source.get_current_frame()
        return frame, "replay_frame_source"


class ReplayWindowTracker:
    """Mock WindowTracker returning fake window handle for replay."""

    def __init__(self, hwnd: int = 1001):
        self.hwnd = hwnd

    def find_game_window(self) -> int:
        return self.hwnd


def bind_triggered_snapshot_to_replay(
    controller: Any, replay_source: ReplayFrameSource, fake_hwnd: int = 1001
) -> None:
    """Dynamically bind AsyncTriggeredSnapshotController to capture from replay source with 0 production code edits."""
    controller._tracker_factory = lambda: ReplayWindowTracker(fake_hwnd)
    controller._window_validator = lambda hwnd: True
    controller._capture_manager_factory = lambda: ReplayCaptureManager(replay_source)
