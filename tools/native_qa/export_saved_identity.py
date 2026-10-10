"""Export saved identity candidates and original crops; no matching or live capture."""
import argparse
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'app'),str(ROOT/'core')]
from native_trial_drafts import NativeTrialDraftStore
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from warehouse_auto_confirmation import export_warehouse_evidence_crops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial-root',type=Path,required=True)
    parser.add_argument('--record',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if not all(p.resolve().is_relative_to(ROOT/'build') for p in (args.trial_root,args.output)):
        parser.error('Trial and export must remain inside build/')
    record = NativeTrialDraftStore(args.trial_root/'canonical-history.json').lookup(args.record)
    if not record: parser.error('Saved DRAFT not found')
    settlement = record['settlement']; packet = settlement['warehouseReviewPacket']
    current_ids = {u['reviewUnitId'] for u in packet.get('reviewUnits',[])}
    current_units = [u for u in settlement['reviewUnits'] if u['reviewUnitId'] in current_ids]
    retained = len(settlement['reviewUnits'])-len(current_units)
    audit = {}
    for path in (args.trial_root/'warehouse-intake').glob('*.json'):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if manifest.get('scope',{}).get('recordStableKey') != args.record: continue
        result_path = (manifest.get('refinement') or {}).get('resultPath')
        if result_path:
            saved = json.loads((args.trial_root/result_path).read_text(encoding='utf-8'))
            audit = {q['observationId']:q for q in saved.get('queryAudit',[])}
    export = export_warehouse_evidence_crops(record_id=args.record,
        review_units=current_units,store=SettlementEvidenceStoreV2(args.trial_root.resolve()),
        output_dir=args.output.parent,segments=packet['segments'])
    escape = lambda value:html.escape(str(value))
    cards = []
    for sample in export['samples']:
        confirmed = sample['confirmationStatus']=='CONFIRMED'
        candidates = ' / '.join(c['name']+' ('+c['catalogId']+')' for c in sample['candidates']) or '没有合格机器候选'
        status = '通过现有多帧自动确证门槛（未人工核验）' if confirmed else '候选或未知，未确证'
        image = '<img src="'+escape(sample['cropPath'])+'" alt="保存原图裁图">' if sample['cropPath'] else '<p>原图裁图不可读</p>'
        unit = next(u for u in current_units if u['reviewUnitId']==sample['reviewUnitId'])
        full = [o for o in unit.get('observations',[]) if o.get('status')=='FULL']
        details = [audit[o['observationId']] for o in full if o['observationId'] in audit]
        cards.append('<article>'+image+'<div><h2>'+escape(sample['canonicalName'] or candidates)+'</h2><p>'+status+
            '</p><p>'+escape(sample['reviewUnitId'])+' · '+escape(sample['footprint'])+'</p><p>'+escape(candidates)+
            '</p><p>原因：'+escape(' / '.join(sample['reasons']))+'</p><details><summary>逐帧匹配诊断</summary><pre>'+escape(json.dumps(details,ensure_ascii=False,indent=2))+'</pre></details><small>来源 '+escape(sample['evidenceId'])+
            '<br>原图坐标 '+escape(sample['bbox'])+'<br>裁图 SHA256 '+escape(sample['cropSha256'])+'</small></div></article>')
    page = ('<!doctype html><html lang="zh"><meta charset="utf-8"><title>本局识别回看</title><style>body{font:16px system-ui;background:#f3f4f6;color:#18202b;margin:32px}article{display:flex;gap:24px;background:white;border-radius:12px;padding:20px;margin:16px 0}img{width:220px;object-fit:contain;image-rendering:auto}h2{font-size:19px}small{overflow-wrap:anywhere;color:#536075}</style><h1>本局部分仓库识别</h1><p>'+escape(args.record)+
        ' · DRAFT / PARTIAL · '+str(export['sampleCount'])+' 个审阅单元，'+str(export['confirmedCount'])+
        ' 个通过自动确证门槛，'+str(export['unresolvedCount'])+' 个未决。</p><p>审阅单元和轮廓轨迹不等于藏品总数；未到底。候选不是确证身份，自动确证不是人工真值。账本另保留 '+str(retained)+
        ' 个早先版本的未决提议，此页按当前证据包展示，不混作当前单元。</p>'+''.join(cards)+'</html>')
    args.output.write_text(page,encoding='utf-8')
    print(json.dumps({'path':str(args.output.resolve()),'crops':sum(bool(s['cropPath']) for s in export['samples']),
        'reviewUnits':export['sampleCount'],'autoConfirmed':export['confirmedCount'],'unresolved':export['unresolvedCount']},ensure_ascii=False))


if __name__ == '__main__': main()
