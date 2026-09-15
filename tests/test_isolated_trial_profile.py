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


class IsolatedTrialTests(unittest.TestCase):
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
