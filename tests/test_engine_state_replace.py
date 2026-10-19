"""engine_state.json replace must survive one Windows sharing refusal."""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "architecture/v2/host/engine_v22"))
engine = importlib.import_module("nte_engine_v22")


class EngineStateReplaceTests(unittest.TestCase):
    def test_one_permission_error_then_the_same_file_lands(self):
        calls = {"n": 0}
        original = engine.os.replace

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("denied")
            return original(src, dst)

        engine.os.replace = flaky
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "engine_state.json"
                engine._atomic_json(path, {"ready": True})
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ready": True})
                self.assertEqual(calls["n"], 2)
                self.assertFalse(path.with_name(path.name + ".tmp").exists())
        finally:
            engine.os.replace = original

    def test_repeated_permission_error_stays_an_error(self):
        original = engine.os.replace

        def denied(src, dst):
            raise PermissionError("denied")

        engine.os.replace = denied
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "engine_state.json"
                with self.assertRaises(PermissionError):
                    engine._atomic_json(path, {"ready": False})
                self.assertFalse(path.exists())
        finally:
            engine.os.replace = original

    def test_live_bid_loop_skips_warehouse_identity_and_keeps_settlement(self):
        seen = []

        class Host:
            _identity_analyzer = None

            def __init__(self, kind):
                self.kind = kind

            def _identity_scope_kind(self, context):
                return self.kind

            def _identity_generation(self):
                seen.append(self.kind)
                return 3

            def log(self, *args, **kwargs):
                seen.append("log")

            @property
            def pipeline(self):
                kind = self.kind
                return type("Pipe", (), {
                    "take_deferred_identity": staticmethod(lambda: {"kind": kind, "round": 1}),
                })()

        Host._submit_deferred_identity = engine.RealEngine._submit_deferred_identity
        previous = os.environ.get("NTE_DOMAIN_LIVE_LOOP")
        os.environ["NTE_DOMAIN_LIVE_LOOP"] = "1"
        try:
            Host("warehouse")._submit_deferred_identity({}, {"scene": "IN_AUCTION"})
            self.assertEqual(seen, [])
            Host("settlement")._submit_deferred_identity({}, {"scene": "SETTLEMENT"})
            self.assertEqual(seen[:2], ["settlement", "log"])
        finally:
            if previous is None:
                os.environ.pop("NTE_DOMAIN_LIVE_LOOP", None)
            else:
                os.environ["NTE_DOMAIN_LIVE_LOOP"] = previous
        seen.clear()
        Host("warehouse")._submit_deferred_identity({}, {"scene": "IN_AUCTION"})
        self.assertEqual(seen[:2], ["warehouse", "log"])


if __name__ == "__main__":
    unittest.main()
