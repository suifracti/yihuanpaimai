"""Exercise the actual worker entry with bounded fake transport and frames."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import main
from current_match import CurrentMatch
from prediction_snapshot_holder import ActivePredictionSnapshotHolder


class ReplayWorkerLifecycleTests(unittest.TestCase):
    def run_worker(self, *, stop_after_first=False, disconnect=False, empty=False, missing=False):
        import vision_pipeline
        import auto_archiver
        import prediction_archive_transport

        current = CurrentMatch()
        signals = {}
        seen = []
        connections = []
        pipeline = Mock()
        pipeline.flush_settlement_for_shutdown.return_value = True
        pipeline.current_context = {"id": current.id, "isSettlement": True}
        archiver = Mock()
        archiver.archive_match.return_value = None

        def process(image, **kwargs):
            seen.append(int(image))
            if stop_after_first:
                next(iter(signals.values()))()
            return {"scene": "IN_AUCTION", "inAuction": True}

        pipeline.process_frame.side_effect = process

        class Socket:
            async def __aenter__(self):
                connections.append(self)
                # Bound the old endless reconnect loop so regression tests fail promptly.
                if len(connections) >= 3:
                    next(iter(signals.values()))()
                return self

            async def __aexit__(self, *args):
                return False

            async def recv(self):
                return main.json.dumps({"action": "worker_resume", "revision": 0,
                                        "snapshot": current.snapshot()})

            async def send(self, raw):
                payload = main.json.loads(raw)
                if disconnect and len(connections) == 1 and "visionState" in payload:
                    raise OSError("fixture transport disconnected after frame processing")

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Future()

        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            frames = root / "replay_frames"
            if not missing:
                frames.mkdir()
            if not empty and not missing:
                for number in (2, 1):
                    (frames / f"frame_{number:04}.jpg").write_bytes(b"fixture")
            for owner, name, value in (
                (main, "ASSETS_DIR", str(root)), (main, "BASE_DIR", str(root)),
                (main, "CONFIG", {"app": {"mode": "replay"}}),
                (main, "CANONICAL_DATABASE", None), (main, "CURRENT_MATCH", current),
                (main, "ACTIVE_SNAPSHOT_HOLDER", ActivePredictionSnapshotHolder()),
            ):
                stack.enter_context(patch.object(owner, name, value))
            stack.enter_context(patch("signal.signal", side_effect=lambda sig, fn: signals.setdefault(sig, fn)))
            stack.enter_context(patch.object(main.time, "sleep"))
            stack.enter_context(patch.object(main.asyncio, "sleep", new=AsyncMock()))
            stack.enter_context(patch.object(main.websockets, "connect", side_effect=lambda *a: Socket()))
            stack.enter_context(patch.object(vision_pipeline, "NTEVisionPipeline", return_value=pipeline))
            import keyboard_auction_pipeline
            stack.enter_context(patch.object(keyboard_auction_pipeline, "KeyboardAuctionPipeline", return_value=pipeline))
            stack.enter_context(patch.object(auto_archiver, "AutoArchiver", return_value=archiver))
            stack.enter_context(patch.object(prediction_archive_transport.PredictionArchiveTransport,
                                            "collect", new=AsyncMock(return_value=True)))
            stack.enter_context(patch.object(main.np, "fromfile", side_effect=lambda p, **kw: int(Path(p).stem.split("_")[1])))
            stack.enter_context(patch.object(main.cv2, "imdecode", side_effect=lambda value, *a: value))
            import frame_source
            def fake_provide(self):
                if self.index >= len(self.paths):
                    self.eof = True
                    if self.stop_flag is not None:
                        self.stop_flag["stop"] = True
                    return None, None, "EOF"
                path = self.paths[self.index]
                self.index += 1
                value = int(path.stem.split("_")[1])
                return 1, value, "fixture"
            stack.enter_context(patch.object(frame_source.KeyframeDirectorySource, "provide", fake_provide))
            stack.enter_context(patch.object(main, "sync_vision_to_current_match"))
            stack.enter_context(patch.object(main, "build_in_auction_hud_payload", return_value={"scene": "IN_AUCTION"}))
            live_capture = stack.enter_context(patch.object(main.mss, "mss", side_effect=RuntimeError("replay must not capture desktop")))
            main.vision_capture_worker()
        return seen, connections, pipeline, archiver, live_capture

    def test_eof_processes_each_frame_once_and_flushes_before_exit(self):
        seen, connections, pipeline, archiver, _ = self.run_worker()
        self.assertEqual(seen, [1, 2])
        self.assertEqual(len(connections), 1)
        pipeline.flush_settlement_for_shutdown.assert_called_once()
        archiver.archive_match.assert_called_once()

    def test_signal_stops_before_next_frame_and_flushes(self):
        seen, connections, pipeline, _, _ = self.run_worker(stop_after_first=True)
        self.assertEqual(seen, [1])
        self.assertEqual(len(connections), 1)
        pipeline.flush_settlement_for_shutdown.assert_called_once()

    def test_disconnect_does_not_reprocess_consumed_frames(self):
        seen, connections, pipeline, _, _ = self.run_worker(disconnect=True)
        self.assertEqual(seen, [1, 2])
        self.assertGreaterEqual(len(connections), 1)
        pipeline.flush_settlement_for_shutdown.assert_called_once()

    def test_empty_replay_exits_without_reconnect(self):
        seen, connections, _, _, live_capture = self.run_worker(empty=True)
        self.assertEqual(seen, [])
        self.assertLessEqual(len(connections), 1)
        live_capture.assert_not_called()

    def test_missing_replay_never_falls_through_to_live_capture(self):
        seen, connections, _, _, live_capture = self.run_worker(missing=True)
        self.assertEqual(seen, [])
        self.assertLessEqual(len(connections), 1)
        live_capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
