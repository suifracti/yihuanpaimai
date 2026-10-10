"""Resume a saved intake using production analysis; no game, Host, capture or input."""
import argparse
import json
from pathlib import Path
import sys
import faulthandler

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'app'), str(ROOT/'core')]
from native_trial_drafts import NativeTrialDraftStore
from native_warehouse_intake import NativeWarehouseIntake

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial-root', type=Path, required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refine-placements', action='store_true', help='Run the existing optional catalog placement refinement')
    args = parser.parse_args()
    if not all(p.resolve().is_relative_to(ROOT/'build') for p in (args.trial_root,args.output)):
        parser.error('Saved trial and output must be inside build/')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    store = NativeTrialDraftStore(args.trial_root/'canonical-history.json')
    intake = NativeWarehouseIntake(draft_store=store, scope_provider=lambda:None, source_provider=lambda:None)
    reply = intake.recover_saved_capture(args.session, refine_placements=args.refine_placements)
    if reply['ok']:
        with (args.output.parent/'recovery-stack.log').open('w') as diagnostic:
            faulthandler.dump_traceback_later(45,repeat=False,file=diagnostic)
            try:
                intake.wait_processing(180)
            except TimeoutError:
                intake.fail_processing('PLACEMENT_REFINEMENT_TIMEOUT' if args.refine_placements else 'PROCESSING_TIMEOUT')
            finally:
                faulthandler.cancel_dump_traceback_later()
        if intake._refiner:
            try:
                intake.wait_refinement(130)
            except (TimeoutError, KeyboardInterrupt):
                intake.cancel_refinement(args.session)
                intake.wait_refinement(3)
    packet = intake.review_packet_copy() or {}
    record = store.lookup(intake._binding['recordStableKey']) if intake._binding else None
    units = ((record or {}).get('settlement') or {}).get('reviewUnits',[])
    result = {'reply':reply,'state':intake._state,'coverage':intake._coverage,'reason':intake._reason,
        'recordStableKey':(record or {}).get('id'),'lifecycleStatus':(record or {}).get('lifecycleStatus'),
        'savedOriginals':len(intake.pages_copy()),'processingEvidenceIds':intake._processing_evidence_ids,
        'sourceFingerprint':packet.get('sourceFingerprint'),'segmentCount':len(packet.get('segments',[])),
        'trackSummary':packet.get('summary'),
        'warehouseCoverage':packet.get('warehouseCoverage'), 'reviewUnitCount':len(units),
        'currentPacketReviewUnitCount':len(packet.get('reviewUnits',[])),
        'confirmedCount':sum(u.get('confirmationStatus')=='CONFIRMED' for u in units),
        'historyPath':str(store.history_path),'noLiveObservation':True}
    result['refinement'] = intake.refinement_payload()
    result['placementRefinementPending'] = bool((result['refinement'] or {}).get('pending',not args.refine_placements))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if intake._state in ('PARTIAL','COMPLETE') else 1

if __name__=='__main__':
    raise SystemExit(main())
