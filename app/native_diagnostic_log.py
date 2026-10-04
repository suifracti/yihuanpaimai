"""Bounded, best-effort text diagnostics for one new background session."""
from __future__ import annotations

from pathlib import Path
import queue
import threading


SESSION_DIAGNOSTIC_LIMIT_BYTES = 32 * 1024 * 1024
_FILES = frozenset({
    "ui-frame-events.jsonl", "host-status.jsonl", "ui-last-frame.json", "host-stderr.log",
})


class NativeDiagnosticLog:
    """Disk writes never run on the Host stdout consumer.

    Each allowed file gets one quarter of the session budget. Only these text
    diagnostics in the newly-created session may be truncated; originals and
    prior sessions are outside this writer's authority. A full queue drops
    diagnostics, never the business event delivered to Main.
    """

    def __init__(self, session_dir: Path, *, max_bytes: int = SESSION_DIAGNOSTIC_LIMIT_BYTES):
        if type(max_bytes) is not int or max_bytes < len(_FILES):
            raise ValueError("Diagnostic budget must allow all session text files")
        self.session_dir = Path(session_dir)
        self.file_limit = max_bytes // len(_FILES)
        self.dropped_entries = 0
        self.write_failures = 0
        self._queue = queue.Queue(maxsize=16)
        self._closed = threading.Event()
        self._sizes = {name: 0 for name in _FILES}
        self._worker = threading.Thread(
            target=self._write_loop, name="native-session-diagnostics", daemon=True,
        )
        self._worker.start()

    def submit(self, name: str, text: str, *, replace: bool = False) -> None:
        if name not in _FILES:
            raise ValueError("Not a session diagnostic text file")
        data = text.encode("utf-8", errors="replace")
        if self._closed.is_set() or len(data) > min(self.file_limit, 1024 * 1024):
            self.dropped_entries += 1
            return
        try:
            self._queue.put_nowait((name, data, replace))
        except queue.Full:
            self.dropped_entries += 1

    def close(self, timeout: float = 1.0) -> None:
        self._closed.set()
        if threading.current_thread() is not self._worker:
            self._worker.join(timeout=max(0.0, timeout))

    def _write_loop(self) -> None:
        while not self._closed.is_set() or not self._queue.empty():
            try:
                name, data, replace = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                reset = replace or self._sizes[name] + len(data) > self.file_limit
                path = self.session_dir / name
                with path.open("wb" if reset else "ab") as stream:
                    stream.write(data)
                self._sizes[name] = len(data) if reset else self._sizes[name] + len(data)
            except OSError:
                self.write_failures += 1
            finally:
                self._queue.task_done()
