import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'core'))
sys.path.insert(0, str(PROJECT_ROOT / 'app'))
import runtime_data as runtime
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from current_match import CurrentMatch
from native_trial_drafts import NativeTrialDraftError, NativeTrialDraftStore
from settlement_review import SettlementReviewService


def _trial_draft(match_id, q=15):
    record = build_canonical_match_record_v7(
        match_id=match_id,
        played_at="2026-09-23T12:00:00+08:00",
        lifecycle_status="DRAFT",
        source="native-live-trial",
        environment={
            "venueTier": "zhongji",
            "venue": "shanhu",
            "box": "实木宝箱",
            "boxType": "wood",
            "fieldCondition": "standard",
        },
        public_intel={"q": q, "totalItems": 66, "totalGrid": 84},
        qualities={
            "purple": {"count": 5, "avg": 2007, "knownItems": []},
            "gold": {"count": 4, "avg": 33538, "knownItems": []},
        },
        settlement={
            "status": "pending",
            "verified": False,
            "clearingPrice": None,
            "actualTotal": None,
            "realizedProfit": None,
            "acquired": False,
            "winner": None,
            "settlementItems": [],
        },
    )
    record["dataOrigin"] = "live-trial"
    record["auctionEvidence"] = {"nativeObservation": {}}
    return record


class IsolatedTrialTests(unittest.TestCase):
    def test_native_trial_save_retry_and_duplicate_keep_one_isolated_draft_and_original(self):
        frame = PROJECT_ROOT / "tests" / "alpha_live_shots" / "204207_04_full.bmp"
        self.assertTrue(frame.is_file(), "existing P1/P2 frame should be available for the offline save path")
        original = frame.read_bytes()
        with tempfile.TemporaryDirectory(dir=str(PROJECT_ROOT / "build")) as folder:
            root = Path(folder)
            store = NativeTrialDraftStore(root / "trial-drafts" / "canonical-history.json")
            match_id = "p4-native-trial-retry"
            record = _trial_draft(match_id)
            descriptor = store.capture_frame(frame, {
                "capturedAtUtc": "2026-09-23T04:00:00Z",
                "frameSequence": 1,
                "observationSessionId": "p4-session",
                "targetInstance": {"targetPid": 123},
            })

            with patch.object(CanonicalHistoryStore, "persist_record_transactional", side_effect=OSError("disk full")):
                with self.assertRaises(NativeTrialDraftError):
                    store.save_draft(record, source_frames=[descriptor])

            saved_original = store.root / descriptor["relativePath"]
            self.assertEqual(saved_original.read_bytes(), original)
            self.assertIsNone(store.lookup(match_id))

            first = store.save_draft(record, source_frames=[descriptor])
            second = store.save_draft(record, source_frames=[descriptor])
            self.assertEqual(first["id"], match_id)
            self.assertEqual(second["id"], match_id)
            self.assertEqual(len(store.list_drafts()), 1)
            self.assertEqual(store.source_images(match_id)[0]["data"], original)
            self.assertEqual(
                CanonicalHistoryStore(root / "formal-history.json").read_database()["records"],
                [],
            )

            self.assertTrue(store.discard_draft(match_id))
            self.assertEqual(store.list_drafts(), [])
            self.assertTrue(saved_original.is_file())
            self.assertFalse((store.root / "history_delete_backup_v1.json").exists())

    def test_live_trial_review_edits_only_the_selected_draft(self):
        frame = PROJECT_ROOT / "tests" / "alpha_live_shots" / "204207_04_full.bmp"
        with tempfile.TemporaryDirectory(dir=str(PROJECT_ROOT / "build")) as folder:
            root = Path(folder)
            match_id = "p4-review-source-isolation"
            trial_store = NativeTrialDraftStore(root / "native-live-trial" / "canonical-history.json")
            trial_record = _trial_draft(match_id, q=15)
            source = trial_store.capture_frame(frame, {"frameSequence": 1})
            trial_store.save_draft(trial_record, source_frames=[source])

            formal_store = CanonicalHistoryStore(root / "formal-history.json")
            formal_record = _trial_draft(match_id, q=8)
            formal_record["dataOrigin"] = "manual"
            formal_store.persist_record_transactional(formal_record, is_finalized=False)
            formal_before = formal_store.lookup(match_id)

            current_live_match = CurrentMatch()
            current_live_match.apply_facts({"q": 22}, source="vision")
            service = SettlementReviewService(
                history_path_provider=lambda: str(formal_store.db_path),
                data_root_provider=lambda: str(root / "formal-data"),
                native_trial_store=trial_store,
            )
            result = service.save_reviewed_settlement(
                match_id,
                [{"slotIndex": 0, "name": "复核保留"}],
                source="live-trial",
            )

            self.assertTrue(result["ok"], result)
            reviewed_trial = trial_store.lookup(match_id)
            self.assertEqual(reviewed_trial["lifecycleStatus"], "DRAFT")
            self.assertEqual(reviewed_trial["dataOrigin"], "live-trial")
            self.assertEqual(reviewed_trial["settlement"]["reviewedItems"][0]["name"], "复核保留")
            self.assertEqual(formal_store.lookup(match_id), formal_before)
            self.assertEqual(current_live_match.facts["q"], 22)

    def test_default_data_and_legacy_are_separate_and_restart_keeps_records(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'isolated_trial.json').write_text(json.dumps({'profile': 'isolated-trial-v1'}))
            legacy = root / 'daily.json'
            legacy.write_text(json.dumps({'records': [{'id': 'daily'}]}))
            original = legacy.read_bytes()
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(root), create=True):
                env = {'LOCALAPPDATA': str(root / 'local')}
                from desktop_pet import DesktopPetPositionStore
                with patch.dict('os.environ', env, clear=True):
                    self.assertEqual(DesktopPetPositionStore.default_path(),
                                     (root / 'local/异环拍卖助手试用/data/state/desktop_pet_state_v1.json').resolve())
                initialized = runtime.initialize_runtime_data(env=env, legacy_candidates=[runtime.LegacyHistoryCandidate(legacy, 'USER_DATA')])
                self.assertTrue(initialized.available)
                self.assertEqual(initialized.paths.root, (root / 'local/异环拍卖助手试用/data').resolve())
                self.assertEqual(json.loads(initialized.paths.history_path.read_text(encoding='utf-8'))['records'], [])
                initialized.paths.history_path.write_text(json.dumps({'records': [{'id': 'trial'}]}))
                reopened = runtime.initialize_runtime_data(env=env)
                self.assertTrue(reopened.available)
                self.assertEqual(json.loads(reopened.paths.history_path.read_text(encoding='utf-8'))['records'][0]['id'], 'trial')
                self.assertEqual(legacy.read_bytes(), original)
                self.assertEqual(runtime.resolve_runtime_data_root({**env, 'YIHUAN_DATA_ROOT': str(root/'override')}), (root/'override').resolve())

    def test_missing_marker_preserves_daily_and_bad_marker_never_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(root), create=True):
                env = {'LOCALAPPDATA': str(root/'local')}
                self.assertEqual(runtime.resolve_runtime_data_root(env), (root/'local/异环拍卖助手/data').resolve())
                (root/'isolated_trial.json').write_text('{bad')
                result = runtime.initialize_runtime_data(env=env)
                self.assertFalse(result.available)
                self.assertEqual(result.reason, 'TRIAL_PROFILE_INVALID')
                self.assertFalse((root/'local').exists())

    def test_build_marker_without_env_defaults_to_production(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # 1. Without env var -> no marker generated
            marker = runtime.resolve_build_trial_marker(root, env={})
            self.assertIsNone(marker)
            self.assertFalse((root / 'isolated_trial.json').exists())

            # 2. When packaged without marker -> production profile
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(root), create=True):
                self.assertFalse(runtime.is_isolated_trial())
                env = {'LOCALAPPDATA': str(root / 'local')}
                self.assertEqual(runtime.resolve_runtime_data_root(env), (root / 'local/异环拍卖助手/data').resolve())

            # 3. Fail-safe: if a stale marker existed, resolve_build_trial_marker deletes it when env is absent
            stale_marker = root / 'isolated_trial.json'
            stale_marker.write_text(json.dumps({'profile': 'isolated-trial-v1'}), encoding='utf-8')
            marker_cleaned = runtime.resolve_build_trial_marker(root, env={})
            self.assertIsNone(marker_cleaned)
            self.assertFalse(stale_marker.exists())

    def test_build_marker_with_env_generates_isolated_trial(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # 1. With NTE_BUILD_ISOLATED_TRIAL=1 -> marker generated with isolated-trial-v1
            marker = runtime.resolve_build_trial_marker(root, env={'NTE_BUILD_ISOLATED_TRIAL': '1', 'NTE_BUILD_REVISION': 'abc1234'})
            self.assertIsNotNone(marker)
            self.assertTrue(marker.exists())
            payload = json.loads(marker.read_text(encoding='utf-8'))
            self.assertEqual(payload.get('profile'), 'isolated-trial-v1')
            self.assertEqual(payload.get('codeRevision'), 'abc1234')

            # 2. When packaged with marker -> isolated-trial profile
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(root), create=True):
                self.assertTrue(runtime.is_isolated_trial())
                env = {'LOCALAPPDATA': str(root / 'local')}
                self.assertEqual(runtime.resolve_runtime_data_root(env), (root / 'local/异环拍卖助手试用/data').resolve())

    def test_build_marker_with_other_env_values_still_production(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for bad_val in ('0', 'false', 'no', 'isolated'):
                marker = runtime.resolve_build_trial_marker(root, env={'NTE_BUILD_ISOLATED_TRIAL': bad_val})
                self.assertIsNone(marker)
                self.assertFalse((root / 'isolated_trial.json').exists())


if __name__ == '__main__':
    unittest.main()
