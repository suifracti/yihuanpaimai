"""Native window lifecycle without loading WebView or sending input."""
import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core')]


class AutoRunWindowTests(unittest.TestCase):
    def window(self, queued=False):
        source = ast.parse((ROOT / 'app/main_window.py').read_text(encoding='utf-8-sig'))
        cls = next(n for n in ast.walk(source) if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and
                   n.name in {'prepare_game_input', 'finish_game_input'}]
        scope = {'WinForms': SimpleNamespace(FormWindowState=SimpleNamespace(Minimized=1, Normal=0))}
        exec(compile(ast.Module(body=methods, type_ignores=[]), '<window>', 'exec'), scope)
        calls, pending = [], []
        form = SimpleNamespace(_game_input_session=None, _game_input_ready=False,
            _game_input_finished=False, _game_input_previous_state=None, WindowState=2,
            InvokeRequired=queued, BeginInvoke=pending.append,
            Show=lambda: calls.append('show'), Activate=lambda: calls.append('activate'),
            post_status=lambda *args: calls.append(args))
        for name in ('prepare_game_input', 'finish_game_input'):
            setattr(form, name, scope[name].__get__(form))
        return form, calls, pending

    def test_once_per_run_then_restore_first_reason_and_new_run(self):
        form, calls, _ = self.window()
        self.assertTrue(form.prepare_game_input('one'))
        self.assertEqual(form.WindowState, 1)
        form.WindowState = 0  # Even a manual restore does not trigger another minimize.
        for _ in range(10): self.assertTrue(form.prepare_game_input('one'))
        self.assertEqual(form.WindowState, 0)
        form.finish_game_input('UNKNOWN')
        form.finish_game_input('USER_STOP')
        self.assertEqual(form.WindowState, 2)
        self.assertIn('UNKNOWN', form.Text)
        self.assertEqual(calls.count('show'), 1)
        self.assertFalse(form.prepare_game_input('one'))
        self.assertTrue(form.prepare_game_input('two'))
        self.assertEqual(form.WindowState, 1)

    def test_stop_before_ui_queue_drains_cannot_minimize_late(self):
        form, calls, pending = self.window(queued=True)
        with mock.patch.dict(sys.modules, {'System': SimpleNamespace(Action=lambda fn: fn)}):
            self.assertFalse(form.prepare_game_input('one'))
            self.assertFalse(form.prepare_game_input('one'))
            self.assertEqual(len(pending), 1)
            form.finish_game_input('USER_STOP')
            for fn in pending: fn()
        self.assertEqual(form.WindowState, 0)
        self.assertEqual(calls.count('show'), 1)
        self.assertFalse(form._game_input_ready)

    def test_no_dispatch_before_main_is_minimized_and_stop_restores(self):
        import main
        form = SimpleNamespace(prepare_game_input=mock.Mock(return_value=False),
                               finish_game_input=mock.Mock())
        with mock.patch.dict('os.environ', {'NTE_DOMAIN_LIVE_LOOP': '1'}), \
             mock.patch.multiple(main, _LIVE_DOMAIN_LOOP=None, _MAIN_WINDOW_HOLDER=[form], LATEST_PAYLOAD={}), \
             mock.patch.object(main, '_live_loop_view') as view:
            main._advance_authorized_live_domain_loop({'observationSessionId': 'one'}, {})
            view.assert_not_called()
            main._stop_authorized_live_domain_loop('HOST_ERROR')
            main._stop_authorized_live_domain_loop('USER_STOP')
            self.assertEqual(main._LIVE_DOMAIN_LOOP['reason'], 'HOST_ERROR')
            form.finish_game_input.assert_called_with('HOST_ERROR')
            main._advance_authorized_live_domain_loop({'observationSessionId': 'one'}, {})
            self.assertEqual(form.prepare_game_input.call_count, 1)


if __name__ == '__main__': unittest.main()
