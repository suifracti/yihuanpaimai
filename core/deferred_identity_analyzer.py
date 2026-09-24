"""Bounded computation-only worker for deferred warehouse/settlement identity.

It owns copied pixels and private recognizers. Results are advisory payloads;
the Native business worker must validate their tags before committing facts.
"""

from __future__ import annotations

import copy
import queue
import threading
from typing import Any, Optional

import numpy as np


def deferred_identity_result_is_current(result: dict[str, Any], current: dict[str, Any]) -> bool:
    """Fail-closed scope gate for a completed background identity computation."""
    if not isinstance(result, dict) or not isinstance(current, dict) or result.get("error"):
        return False
    fields = (
        "sessionId", "generationId", "matchId", "matchSequence",
        "pipelineMatchGeneration", "pipelineSessionGeneration", "invalidationGeneration",
        "recognitionMode",
    )
    if any(result.get(key) != current.get(key) for key in fields):
        return False
    try:
        if int(current.get("factsRevision", -1)) < int(result.get("factsRevisionAtDispatch", 0)):
            return False
        if int(result.get("frameSequence", -1)) <= int(current.get("lastCommittedFrameSequence", -1)):
            return False
    except (TypeError, ValueError):
        return False
    kind = result.get("kind")
    if kind == "warehouse":
        return (result.get("scene") == "IN_AUCTION" and current.get("scene") == "IN_AUCTION"
                and current.get("round") == result.get("round"))
    if kind == "settlement":
        return result.get("scene") == "SETTLEMENT" and current.get("scene") == "SETTLEMENT"
    return False


class DeferredIdentityAnalyzer:
    def __init__(self, result_capacity: int = 2) -> None:
        self._condition = threading.Condition()
        self._pending: Optional[dict[str, Any]] = None
        self._results: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max(1, int(result_capacity)))
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="nte-deferred-identity", daemon=True)
        self._thread.start()

    def submit(self, descriptor: dict[str, Any], frame_bgr: np.ndarray) -> bool:
        """Queue the newest copied frame, replacing an unstarted older frame."""
        if not isinstance(descriptor, dict) or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0:
            return False
        task = copy.deepcopy(descriptor)
        task["frame"] = np.ascontiguousarray(frame_bgr.copy())
        with self._condition:
            if self._stopping:
                return False
            self._pending = task
            self._condition.notify()
        return True

    def invalidate_pending(self) -> None:
        """Drop work which has not started; running work is rejected by its owner."""
        with self._condition:
            self._pending = None

    def poll(self, limit: int = 2) -> list[dict[str, Any]]:
        output = []
        for _ in range(max(1, int(limit))):
            try:
                output.append(self._results.get_nowait())
            except queue.Empty:
                break
        return output

    def close(self, timeout: float = 0.5) -> None:
        with self._condition:
            self._stopping = True
            self._pending = None
            self._condition.notify_all()
        self._thread.join(timeout=max(0.0, float(timeout)))

    def _publish(self, result: dict[str, Any]) -> None:
        try:
            self._results.put_nowait(result)
            return
        except queue.Full:
            pass
        try:
            self._results.get_nowait()
        except queue.Empty:
            pass
        try:
            self._results.put_nowait(result)
        except queue.Full:
            pass

    def _run(self) -> None:
        warehouse = None
        settlement = None
        owner_key = None
        while True:
            with self._condition:
                while self._pending is None and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                task = self._pending
                self._pending = None

            try:
                task_key = (
                    task.get("sessionId"), task.get("generationId"), task.get("matchId"),
                    task.get("matchSequence"), task.get("pipelineMatchGeneration"),
                    task.get("invalidationGeneration"), task.get("round"),
                )
                if task_key != owner_key:
                    warehouse = None
                    settlement = None
                    owner_key = task_key

                kind = task.get("kind")
                frame = task.pop("frame")
                if kind == "warehouse":
                    if warehouse is None:
                        from warehouse_vision import WarehouseVisionV1
                        warehouse = WarehouseVisionV1()
                    payload = {"warehouseVision": warehouse.process_frame(frame)}
                elif kind == "settlement":
                    from settlement_item_recognizer import SettlementItemRecognizer
                    if settlement is None:
                        settlement = SettlementItemRecognizer()
                    actual_total = task.get("actualTotal")
                    payload = settlement.parse_settlement_ledger(frame, actual_total=actual_total)
                else:
                    continue
                self._publish({**task, **payload})
            except Exception as exc:
                self._publish({**task, "error": f"{type(exc).__name__}: {exc}"})
