"""Bounded, saved-material-only refinement. Child analysis never writes history."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

REFINEMENT_SECONDS = 120
ROOT = Path(__file__).resolve().parents[1]


def fingerprint(manifest):
    return hashlib.sha256(json.dumps({k:manifest.get(k) for k in (
        'sessionId','generation','scope','processingEvidenceIds','pages')},
        sort_keys=True,separators=(',',':')).encode()).hexdigest()


def write_manifest(path, manifest):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    os.replace(temp,path)


class SavedWarehouseRefinement:
    def __init__(self, intake):
        self.intake = intake
        self._queue, self._events = [], {}
        self._thread = None

    def _path(self, session):
        import re
        if not re.fullmatch('[0-9a-f]{32}',str(session)):
            raise ValueError('INVALID_INTAKE_SESSION')
        return self.intake.draft_store.root/'warehouse-intake'/(session+'.json')

    def enqueue(self, session, *, resume=False):
        with self.intake._scope_lock, self.intake._lock:
            path = self._path(session)
            manifest = json.loads(path.read_text(encoding='utf-8'))
            previous = manifest.get('refinement') or {}
            if manifest['state'] not in {'PARTIAL','COMPLETE'} or not manifest.get('processingEvidenceIds'):
                return {'ok':False,'reason':'NO_ARCHIVED_SUPPORT_PAGES'}
            if session in self._events:
                return {'ok':not self._events[session].is_set(),
                    'reason':'REFINEMENT_CANCEL_PENDING' if self._events[session].is_set() else 'REFINEMENT_ALREADY_QUEUED'}
            if previous.get('state') in {'COMPLETE','CANCELLED','FAILED'} and not resume:
                return {'ok':True,'reason':'REFINEMENT_'+previous['state']}
            if len(self._events) >= 16:
                return {'ok':False,'reason':'REFINEMENT_QUEUE_LIMIT'}
            event = threading.Event(); token = uuid.uuid4().hex
            manifest['refinement'] = {'state':'QUEUED','jobId':token,
                'inputFingerprint':fingerprint(manifest),'budgetSeconds':REFINEMENT_SECONDS}
            manifest['placementRefinementPending'] = True
            write_manifest(path,manifest)
            self._events[session] = event
            self._queue.append((session,token,event))
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run,name='saved-warehouse-refinement',daemon=True)
                self._thread.start()
            return {'ok':True,'reason':'REFINEMENT_QUEUED','sessionId':session}

    def cancel(self, session):
        with self.intake._scope_lock, self.intake._lock:
            event = self._events.get(session)
            if event: event.set()
            path = self._path(session)
            manifest = json.loads(path.read_text(encoding='utf-8'))
            state = manifest.get('refinement') or {}
            if state.get('state') == 'COMPLETE':
                return {'ok':True,'reason':'REFINEMENT_ALREADY_COMPLETE','sessionId':session}
            if state.get('state') != 'COMPLETE':
                state.update(state='CANCELLED',reason='USER_CANCEL')
                manifest['refinement'] = state
                write_manifest(path,manifest)
            return {'ok':True,'reason':'REFINEMENT_CANCELLED','sessionId':session}

    def wait(self, timeout):
        thread = self._thread
        if thread:
            thread.join(timeout)
            if thread.is_alive(): raise TimeoutError('Saved refinement still running')

    def _run(self):
        while True:
            with self.intake._scope_lock, self.intake._lock:
                if not self._queue:
                    # Clear while locked so enqueue cannot miss an exiting worker.
                    self._thread = None
                    return
                session,token,event = self._queue.pop(0)
            try:
                if not event.is_set(): self._one(session,token,event)
            except Exception as exc:
                with self.intake._scope_lock, self.intake._lock:
                    path = self._path(session)
                    manifest = json.loads(path.read_text(encoding='utf-8'))
                    state = manifest.get('refinement') or {}
                    if state.get('jobId') == token and not event.is_set():
                        state.update(state='FAILED',reason=f'{type(exc).__name__}:{exc}'[:180])
                        manifest['refinement'] = state
                        write_manifest(path,manifest)
            finally:
                with self.intake._scope_lock, self.intake._lock:
                    self._events.pop(session,None)

    def _one(self, session, token, event):
        path = self._path(session)
        with self.intake._scope_lock, self.intake._lock:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if event.is_set() or manifest['refinement']['jobId'] != token: return
            state = manifest['refinement']; state['state'] = 'RUNNING'
            write_manifest(path,manifest)
        work = self.intake.draft_store.root/'warehouse-refinement'/session
        work.mkdir(parents=True,exist_ok=True)
        output = work/(token+'.json')
        started = time.perf_counter()
        env = os.environ.copy(); env['PYTHONIOENCODING'] = 'utf-8'
        command = [sys.executable,str(Path(__file__).resolve()),'--worker',
            str(self.intake.draft_store.root),session,token]
        with (work/'worker.log').open('w',encoding='utf-8') as log:
            process = subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                while process.poll() is None:
                    if event.wait(.1):
                        return
                    if time.perf_counter()-started > REFINEMENT_SECONDS:
                        raise TimeoutError('REFINEMENT_TIME_LIMIT')
                if process.returncode != 0:
                    raise RuntimeError('REFINEMENT_WORKER_FAILED:'+str(process.returncode))
            finally:
                if process.poll() is None: process.kill()
                process.wait()
        if output.stat().st_size > 16*1024*1024: raise ValueError('REFINEMENT_RESULT_LIMIT')
        result = json.loads(output.read_text(encoding='utf-8'))
        with self.intake._scope_lock, self.intake._lock:
            current = json.loads(path.read_text(encoding='utf-8'))
            if (event.is_set() or current['refinement']['state'] != 'RUNNING'
                    or current['refinement']['jobId'] != token):
                return
            if (fingerprint(current) != state['inputFingerprint'] or result.get('jobId') != token
                    or result.get('inputFingerprint') != state['inputFingerprint']):
                raise ValueError('STALE_REFINEMENT_RESULT')
            key = current['scope']['recordStableKey']
            if self.intake.draft_store.lookup(key) is None: raise ValueError('OLD_DRAFT_UNAVAILABLE')
            evidence = result['evidence']; packet = evidence['review_packet']
            if packet.get('recordStableKey') != key: raise ValueError('REFINEMENT_RECORD_MISMATCH')
            self.intake._verify_saved_pages(current['pages'],binding=current['scope'])
            saved = self.intake.history_store.persist_warehouse_evidence(key,record_stable_key=key,**evidence)
            if saved is None: raise ValueError('REFINEMENT_HISTORY_REJECTED')
            current['refinement'].update(state='COMPLETE',elapsedSeconds=time.perf_counter()-started,
                resultPath=str(output.relative_to(self.intake.draft_store.root)),summary=result['summary'])
            current['placementRefinementPending'] = False
            current['resultSourceFingerprint'] = packet['sourceFingerprint']
            coverage = packet['warehouseCoverage']['status']
            current['state'] = 'COMPLETE' if coverage == 'COMPLETE' else 'PARTIAL'
            write_manifest(path,current)
            if self.intake._session_id == session and self.intake._generation == current['generation']:
                self.intake._packet, self.intake._resolve_placements = packet, True
                self.intake._coverage, self.intake._state = coverage,current['state']


def analyze_saved(root, session, token):
    sys.path[:0] = [str(ROOT/'app'),str(ROOT/'core')]
    from native_trial_drafts import NativeTrialDraftStore
    from native_warehouse_intake import NativeWarehouseIntake, _anchor
    from warehouse_capture_host import WarehouseCaptureHost
    from warehouse_capture_production import get_production_placement_resolver
    store = NativeTrialDraftStore(root/'canonical-history.json')
    intake = NativeWarehouseIntake(draft_store=store,scope_provider=lambda:None,
        source_provider=lambda:None,auto_refine=False)
    path = SavedWarehouseRefinement(intake)._path(session)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest['refinement']['jobId'] != token or manifest['refinement']['state'] != 'RUNNING':
        raise ValueError('STALE_REFINEMENT_JOB')
    intake._binding = _anchor(manifest['scope'])
    intake._session_id, intake._generation, intake._pages = session,manifest['generation'],manifest['pages']
    support_ids = intake._saved_support_ids() if intake._binding.get('capturePolicy') else [p['descriptor']['evidenceId'] for p in intake._pages]
    if support_ids != manifest['processingEvidenceIds']: raise ValueError('QUALIFIED_PAGE_SELECTION_UNPROVEN')
    ids = intake._saved_identity_ids() if intake._binding.get('capturePolicy') else support_ids
    intake._verify_saved_pages(intake._pages)
    pages = [p['descriptor'] for eid in ids for p in intake._pages if p['descriptor']['evidenceId']==eid]
    class Collector:
        evidence = None
        def persist_warehouse_evidence(self, key, **kwargs):
            self.evidence = copy.deepcopy(kwargs)
            return {'id':key}
    collector = Collector(); started = time.perf_counter()
    processor = WarehouseCaptureHost(store_factory=lambda:intake.evidence_store,driver_available=False)
    result = processor._process_saved_pages(intake._binding['recordStableKey'],pages,
        history_store=collector,finalization_reason=manifest['terminationReason'],resolve_placements=True)
    if not result['ok'] or collector.evidence is None: raise ValueError('REFINEMENT_ANALYSIS_FAILED')
    resolver = get_production_placement_resolver()
    summary = {'analysisSeconds':time.perf_counter()-started,'matchMetrics':resolver.match_metrics,
        'identitySourceEvidenceIds':ids,
        'reviewUnitCount':result['totalSlots'],'confirmedCount':result['confirmedCount'],
        'coverage':result['coverageStatus']}
    import cv2
    import numpy as np
    from collections import Counter
    units = collector.evidence['review_units']
    summary['candidateUnitCount'] = sum(bool(u.get('candidates')) for u in units)
    summary['unconfirmedReasons'] = dict(Counter(reason for u in units for reason in u.get('unconfirmedReasons',[])))
    frames = {p['evidenceId']:cv2.imdecode(np.frombuffer(intake.evidence_store.load_original(p),np.uint8),cv2.IMREAD_COLOR)
              for p in pages}
    audit = []
    for unit in units:
        for observation in unit.get('observations',[]):
            if observation.get('status') != 'FULL': continue
            image = frames[observation['evidenceId']]
            x,y,r,b = map(int,observation['bbox'])
            roi = image[y:b,x:r]
            footprint = unit['footprint']
            audit.append({'reviewUnitId':unit['reviewUnitId'],'observationId':observation['observationId'],
                'roiPixelSha256':hashlib.sha256(roi.tobytes()).hexdigest(),
                **resolver.query_diagnostic(roi,footprint['widthCells'],footprint['heightCells'])})
    output = root/'warehouse-refinement'/session/(token+'.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    temp = output.with_suffix('.tmp')
    temp.write_text(json.dumps({'jobId':token,'inputFingerprint':fingerprint(manifest),
        'evidence':collector.evidence,'summary':summary,'queryAudit':audit},ensure_ascii=False),encoding='utf-8')
    os.replace(temp,output)


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != '--worker': raise SystemExit('Saved worker arguments required')
    analyze_saved(Path(sys.argv[2]),sys.argv[3],sys.argv[4])
