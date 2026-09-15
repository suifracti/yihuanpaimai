"""Real process contention over one isolated history database."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from canonical_history_store import CanonicalHistoryStore
from current_match import CurrentMatch
from history_file_lock import history_file_lock


def write_records(db, prefix, ready, go, done):
    Path(ready).touch()
    deadline = time.monotonic() + 20
    while not Path(go).exists():
        if time.monotonic() > deadline:
            raise TimeoutError("test start signal")
        time.sleep(0.01)
    store = CanonicalHistoryStore(db)
    for index in range(12):
        current = CurrentMatch()
        current.id = f"{prefix}_{index}"
        current.apply_facts({"q": index})
        store.persist_record_transactional(current.to_canonical(), is_finalized=False)
    Path(done).touch()


class HistoryMultiprocessTests(unittest.TestCase):
    def test_two_process_writers_wait_for_lock_and_preserve_every_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "history.json"
            children = []
            try:
                with history_file_lock(db):
                    for prefix in ("main", "vision"):
                        args = [sys.executable, __file__, "--writer", str(db), prefix,
                                str(root / f"{prefix}.ready"), str(root / "go"),
                                str(root / f"{prefix}.done")]
                        children.append(subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                    deadline = time.monotonic() + 15
                    while not all((root / f"{p}.ready").exists() for p in ("main", "vision")):
                        self.assertLess(time.monotonic(), deadline, "children failed to start")
                        time.sleep(0.01)
                    (root / "go").touch()
                    time.sleep(0.25)
                    self.assertFalse(db.exists(), "a child wrote while another process held the lock")
                for child in children:
                    stdout, stderr = child.communicate(timeout=20)
                    self.assertEqual(child.returncode, 0, stderr.decode(errors="replace"))
                rows = CanonicalHistoryStore(db).read_database()["records"]
                self.assertEqual({r["id"] for r in rows},
                                 {f"{p}_{i}" for p in ("main", "vision") for i in range(12)})
                self.assertEqual(len(rows), 24)
                for row in rows:
                    self.assertEqual(row["publicIntel"]["q"], int(row["id"].split("_")[-1]))
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.communicate()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--writer":
        write_records(*sys.argv[2:])
    else:
        unittest.main()
