"""Opt-in retained M4 originals; no game, input or edits to original records."""
import hashlib
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

from tests.test_native_half_viewport_flow import ROOT, LiveRun
from warehouse_segment_overlap import TerminalContinuity, align_warehouse_segments
from warehouse_scrollbar_observation import warehouse_search_roi
from warehouse_capture_host import WarehouseCaptureHost

DATA = ROOT / 'build/m4-20261021/run-8/runtime-data/native-live-trial'
LOG = ROOT / 'build/native-observation/session-1d6537dc25bc4a3cad521b3081c72718/main-diagnostic.log'


@unittest.skipUnless(LOG.is_file() and DATA.is_dir(), 'requires retained private M4 run-8 originals')
class M4SparseContinuityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games = []
        events = [json.loads(line.split('[WAREHOUSE:NATIVE_AUTO] ', 1)[1])
                  for line in LOG.read_text(encoding='utf-8').splitlines()
                  if '[WAREHOUSE:NATIVE_AUTO] ' in line]
        for path in sorted((DATA / 'warehouse-intake').glob('*.json')):
            document = json.loads(path.read_text(encoding='utf-8'))
            cls.games.append((document, [e['alignment'] for e in events
                if e['kind'] == 'image-overlap'
                and e['alignment']['prevId'] in {p['descriptor']['evidenceId'] for p in document['pages']}]))

    def frame(self, page):
        raw = (DATA / page['nativeSource']['relativePath']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), page['nativeSource']['sha256'])
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def crop(self, page):
        frame = self.frame(page)
        x, y, r, b = warehouse_search_roi(frame.shape[1], frame.shape[0])
        return frame[y:b, x:r]

    def test_all_three_actual_chains_measure_pixels_and_reject_missing_views(self):
        for document, motions in self.games:
            pages = {p['descriptor']['evidenceId']: p for p in document['pages']}
            chain = TerminalContinuity()
            for old in motions:
                a, b = self.crop(pages[old['prevId']]), self.crop(pages[old['nextId']])
                result = align_warehouse_segments(a, b, prev_id=old['prevId'], next_id=old['nextId'],
                    required_direction='DOWN', terminal_continuity=chain)
                if old['reason'] == 'SPARSE_PROGRESSION_VERIFIED':
                    self.assertEqual(result['status'], 'VERIFIED', result)
                    self.assertAlmostEqual(result['verticalOffsetPx'], -30, delta=1,
                                           msg='retained single-notch raster motion is about 30 pixels')
                    self.assertGreaterEqual(result['confidence'], .80)
                elif result['reason'] != 'NO_MOVEMENT':
                    self.assertEqual(result['status'], 'VERIFIED', result)
            # Rebuild the same calibrated chain, then omit multiple real views.
            chain = TerminalContinuity()
            for old in motions[:2]:
                align_warehouse_segments(self.crop(pages[old['prevId']]), self.crop(pages[old['nextId']]),
                    prev_id=old['prevId'], next_id=old['nextId'], required_direction='DOWN', terminal_continuity=chain)
            first, last = motions[2], motions[-1]
            a, b = self.crop(pages[first['prevId']]), self.crop(pages[last['nextId']])
            self.assertFalse(chain.terminal(a, b, 320), 'a skipped real range cannot borrow the small-step proof')
            fake_bottom = self.crop(pages[first['nextId']]).copy()
            # Leave the physical scrollbar movement but replace the grid with
            # stationary pixels. A scrollbar alone must never establish motion.
            fake_bottom[:, :int(.88 * a.shape[1])] = a[:, :int(.88 * a.shape[1])]
            self.assertFalse(chain.terminal(a, fake_bottom, 320))

    def test_real_collector_and_saved_host_ledger_finish_all_three(self):
        summaries = []
        for document, motions in self.games:
            pages = document['pages']
            first_id = motions[0]['prevId']
            first_index = next(i for i, p in enumerate(pages) if p['descriptor']['evidenceId'] == first_id)
            f = LiveRun(output=ROOT / 'build/m4b-20261021/coverage-flow', capture_first=True)
            try:
                f.deliver(self.frame(pages[first_index-1])); f.tick(); f.deliver(self.frame(pages[first_index]))
                for i in range(first_index+1, len(pages)-1, 2):
                    self.assertEqual(f.auto._phase, 'WAIT_SCROLL', f.logs[-2:])
                    f.scroll_ack(); f.tick(); f.deliver(self.frame(pages[i]))
                    f.tick(); f.deliver(self.frame(pages[i+1]))
                self.assertEqual(f.auto._reason, 'COMPLETE', f.logs[-3:])
                final = f.finalizations[-1]
                ids = set(final['coverage_evidence_ids'])
                descriptors = [p['descriptor'] for p in f.source.pages_copy() if p['descriptor']['evidenceId'] in ids]
                class History:
                    def persist_warehouse_evidence(self, key, **kwargs):
                        return {'id': key}
                host = WarehouseCaptureHost(store_factory=lambda: f.intake.evidence_store, driver_available=False)
                result = host._process_saved_pages('match', descriptors, history_store=History(),
                    resolve_placements=False, identity_evidence_ids=[])
                self.assertEqual(result['coverageStatus'], 'COMPLETE',
                                 (result.get('coverage') or {}).get('gaps'))
                missing = host._process_saved_pages('match', descriptors[:2] + descriptors[-2:],
                    history_store=History(), resolve_placements=False, identity_evidence_ids=[])
                self.assertEqual(missing['coverageStatus'], 'PARTIAL')
                summaries.append({'matchId': document['scope']['recordStableKey'], 'savedOriginals': len(pages),
                    'collector': f.auto._reason, 'hostCoverage': result['coverageStatus'],
                    'missingRange': missing['coverageStatus'], 'realInput': False})
            finally:
                f.close()
        output = ROOT / 'build/m4b-20261021/coverage-replay.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
