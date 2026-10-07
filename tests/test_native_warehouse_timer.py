"""Continuation uses the production timer callback; inert SOURCE, no game IO."""
import copy
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core'), str(ROOT)]
from tests import test_native_warehouse_restability as restability_fixture
silhouette = restability_fixture.silhouette

TRACES = []


class ScheduledWake:
    """Inject early/late delivery of a one-shot wake, not collector decisions."""
    def __init__(self, interval, function):
        self.interval, self.function = interval, function
        self.cancelled = self.started = False
        self.daemon = False
    def start(self):
        self.started = True
    def cancel(self):
        self.cancelled = True
    def fire(self):
        self.function()  # A cancelled callback can already have entered: authority must reject it.


class TimerTests(unittest.TestCase):
    def start_fifth(self):
        fixture = restability_fixture.RecheckTests('runTest')
        fixture.start()
        self.addCleanup(fixture.doCleanups)
        self.f = fixture
        self.wakes = []
        def timer(interval, callback):
            wake = ScheduledWake(interval, callback)
            self.wakes.append(wake)
            return wake
        patched = patch('native_warehouse_auto_capture.threading.Timer', side_effect=timer)
        patched.start(); self.addCleanup(patched.stop)
        fixture.auto._timers = True
        fixture.frame(silhouette(), 'PRESENT')
        for n in range(4):
            fixture.now[0] = fixture.auto._due + .05
            self.wakes[-1].fire()
            fixture.frame(silhouette(), 'PRESENT')
        self.assertEqual(fixture.source._ordinal, 5)
        self.assertEqual(len(fixture.source.pages), 5)
        self.assertEqual(fixture.auto._phase, 'WAIT_STABLE')
        self.addCleanup(lambda: TRACES.append({'test':self.id(), 'actions':copy.deepcopy(fixture.source.actions),
            'requests':fixture.source._ordinal,'deadline':fixture.auto._deadline,
            'reason':fixture.auto._reason,'diagnostics':copy.deepcopy(fixture.logs)}))
        return fixture

    def test_early_fifth_wake_keeps_due_and_eventually_enqueues_sixth_once(self):
        f = self.start_fifth()
        due, deadline = f.auto._due, f.auto._deadline
        wake = self.wakes[-1]
        f.now[0] = due - .001  # Native coarse clock still reports before the fractional due.
        wake.fire()
        self.assertEqual(f.source._ordinal, 5, 'early wake must not make an early request')
        f.now[0] = due + .02
        if self.wakes[-1] is not wake:
            self.wakes[-1].fire()
        self.assertEqual(f.source._ordinal, 6, 'one-shot early wake must not lose the sixth request')
        self.assertEqual((f.auto._due, f.auto._deadline), (due, deadline))
        f.auto.poll(); wake.fire()
        self.assertEqual(f.source._ordinal, 6, 'pending request and obsolete callback cannot double enqueue')
        self.assertEqual(f.wheels(), 0)

    def test_slow_processing_checks_deadline_after_lock_wait_before_enqueue(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                f=self.start_fifth(); due, deadline=f.auto._due, f.auto._deadline
                entered=threading.Event()
                def log(text):
                    row=json.loads(text); f.logs.append(row)
                    if row['kind']=='page-timer-entered': entered.set()
                f.auto._diagnostic_log=log
                with f.auto._lock:  # Simulate the real OCR/business scope lock being held.
                    f.now[0]=due+.02
                    callback=threading.Thread(target=self.wakes[-1].fire)
                    callback.start()
                    self.assertTrue(entered.wait(1))
                    self.assertEqual(f.source._ordinal,5)
                    f.now[0]=deadline if expired else due+3
                callback.join(1); self.assertFalse(callback.is_alive())
                self.assertEqual(f.source._ordinal,5 if expired else 6)
                self.assertEqual(f.auto._deadline,deadline)
                if expired:
                    self.assertEqual(f.auto._reason,'ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
                self.assertEqual(f.wheels(),0)

    def test_duplicate_status_and_cancelled_callback_do_not_replace_current_wait(self):
        f=self.start_fifth(); old=self.wakes[-1]; due=f.auto._due
        f.auto.on_event({'state':'OPEN','reason':'SAVED'})
        self.assertEqual(f.auto._due,due)
        self.assertIs(self.wakes[-1],old)
        f.now[0]=due+.02; old.fire()
        f.frame(silhouette(),'PRESENT')  # Sixth page replaces the wait within this same generation.
        current=self.wakes[-1]; current_due=f.auto._due
        old.fire(); old.fire()
        self.assertIs(self.wakes[-1],current)
        self.assertEqual(f.auto._due,current_due)
        self.assertEqual(f.source._ordinal,6)
        f.now[0]=current_due+.02; current.fire()
        self.assertEqual(f.source._ordinal,7)

    def test_stop_cross_match_and_lease_loss_reject_early_and_late_callbacks(self):
        for reason in ('USER_STOP','SOURCE_SCOPE_CHANGED','SOURCE_GEOMETRY_CHANGED'):
            with self.subTest(reason=reason):
                f=self.start_fifth(); wake=self.wakes[-1]
                f.now[0]=f.auto._due-.001
                if reason=='USER_STOP': f.auto.stop()
                elif reason=='SOURCE_SCOPE_CHANGED': f.source.scope.update(recordStableKey='next',matchGeneration=2)
                else: f.source.on_event({'state':'CLOSED','reason':reason})
                wake.fire()
                self.assertEqual(f.auto._reason,reason)
                self.assertEqual(f.source._ordinal,5)
                self.assertIsNone(f.auto._anchor); self.assertIsNone(f.auto._timer)
                actions=copy.deepcopy(f.source.actions)
                f.now[0]=170; wake.fire(); f.auto.poll()
                self.assertEqual(f.source.actions,actions)

    def test_callback_and_registration_exceptions_stop_without_silent_retry(self):
        f=self.start_fifth(); f.now[0]=f.auto._due+.02
        with patch.object(f.source,'capture_manual_page',side_effect=RuntimeError('inert callback fault')):
            self.wakes[-1].fire()
        self.assertEqual(f.auto._reason,'STABILITY_TIMER_CALLBACK_FAILED:RuntimeError')
        self.assertEqual(f.source._ordinal,5)
        self.assertIsNone(f.auto._timer); self.assertIsNone(f.auto._anchor)
        f=self.start_fifth(); f.now[0]=f.auto._due-.001
        with patch.object(ScheduledWake,'start',side_effect=RuntimeError('inert registration fault')):
            self.wakes[-1].fire()
        self.assertEqual(f.auto._reason,'STABILITY_TIMER_START_FAILED:RuntimeError')
        self.assertEqual(f.source._ordinal,5)
        self.assertIsNone(f.auto._timer); self.assertIsNone(f.auto._anchor)

    def test_early_wake_rearm_cannot_reset_deadline_or_exhausted_request_budget(self):
        f=self.start_fifth(); deadline=f.auto._deadline
        f.now[0]=f.auto._due-.001; self.wakes[-1].fire()
        f.source._ordinal=32  # SOURCE's existing charged-attempt counter, no new counter.
        f.now[0]=f.auto._due+.02; self.wakes[-1].fire()
        self.assertEqual(f.source._ordinal,32)
        self.assertEqual(f.auto._reason,'SOURCE_REQUEST_LIMIT_REACHED')
        self.assertEqual(f.auto._deadline,deadline)
        self.assertEqual(f.wheels(),0)


if __name__ == '__main__':
    out = ROOT / 'build/native-restability-timer-20261007'
    out.mkdir(parents=True, exist_ok=True)
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TimerTests))
    (out/'timer-results.json').write_text(json.dumps({'passed':result.wasSuccessful(),'methods':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'traces':TRACES,'gameCapture':False},indent=2),encoding='utf-8')
    sys.exit(not result.wasSuccessful())
