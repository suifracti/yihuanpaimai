"""Bounded, read-only history text; OCR evidence never becomes a cost event."""

from intel_card_source import card_source
from public_intel_ledger import verified_public_event, public_event_identity

FIELD_LABELS = {
    'q': '紫金红总件数', 'goldAvg': '金品均价', 'purpleAvg': '紫品均价',
    'totalItems': '总件数', 'totalGrid': '总格数',
    **{color + suffix: label + unit for color, label in
       (('white', '白品'), ('green', '绿品'), ('blue', '蓝品'),
        ('purple', '紫品'), ('gold', '金品'), ('red', '红品'))
       for suffix, unit in (('Count', '件数'), ('Grid', '格数'))},
}


def _number(value):
    return str(value) if type(value) is int and 0 <= value <= 2**53 - 1 else '未知'


def intel_evidence_text(record):
    evidence = record.get('intelCardEvidence')
    if not isinstance(evidence, dict):
        return '未记录情报识别证据'
    if type(evidence.get('version')) is not int or evidence['version'] != 1:
        return '情报证据版本暂不支持回看'
    facts = evidence.get('facts')
    facts = facts if isinstance(facts, dict) else {}
    observations = evidence.get('observations')
    observations = observations if isinstance(observations, list) else []
    lines = []
    for field, label in FIELD_LABELS.items():
        fact = facts.get(field)
        fact = fact if isinstance(fact, dict) else {}
        sources = fact.get('sources')
        sources = sources if isinstance(sources, list) else []
        recent = [o for o in observations if isinstance(o, dict) and o.get('field') == field]
        if not sources and not recent and 'tentative' not in fact and fact.get('status') not in ('OBSERVED', 'CONFLICT'):
            continue
        status = fact.get('status')
        if status == 'CONFLICT':
            candidates = fact.get('candidates')
            candidates = candidates if isinstance(candidates, list) else []
            description = '存在冲突；候选 ' + ' / '.join(_number(v) for v in candidates[:8])
        elif status == 'OBSERVED':
            description = '识别已确认 ' + _number(fact.get('value'))
            if 'challenger' in fact:
                description += '；另有待复核读数 ' + _number(fact['challenger'])
        else:
            description = '待确认 ' + _number(fact.get('tentative'))
        # Repeated source frames and repeated text do not become extra evidence.
        frames = {s['frameId'] for s in sources + recent if isinstance(s, dict) and isinstance(s.get('frameId'), str) and s['frameId']}
        texts = []
        public_title_seen = False
        for source in sources + recent:
            if not isinstance(source, dict) or not isinstance(source.get('rawText'), str):
                continue
            text = ' '.join(source['rawText'].split())[:240]
            # Re-derive from saved raw text, not an unverified supplied label.
            public_title_seen = public_title_seen or card_source(source['rawText'])['kind'] == 'AUCTIONEER_PUBLIC'
            if text and text not in texts:
                texts.append(text)
        line = f'{label}：{description}；记录来源 {len(frames)} 帧'
        if public_title_seen:
            line += '；读到拍卖师公开情报标题（不代表新增免费事件）'
        if texts:
            line += '；原文：' + ' / '.join(texts[-3:])
        lines.append(line)
    readings = evidence.get('cardReadings')
    readings = readings if isinstance(readings, list) else []
    seen_readings = set()
    for reading in readings[:12]:
        if not isinstance(reading, dict) or not isinstance(reading.get('rawText'), str):
            continue
        text = ' '.join(reading['rawText'].split())[:240]
        if not text or text in seen_readings:
            continue
        seen_readings.add(text)
        source = '公开情报标题' if card_source(reading['rawText'])['kind'] == 'AUCTIONEER_PUBLIC' else '来源未确认'
        mode = '本次识别' if reading.get('is_physical_ocr') is True else '复用或来源待核实'
        lines.append(f'卡片原文（{source}，{mode}，不作为新增事实）：{text}')
    if len(readings) > 12:
        lines.append('仅显示前12条卡片原文；完整记录保存在本局证据中。')
    events = evidence.get('publicCardEvents')
    events = events if isinstance(events, list) else []
    displayed = set()
    for event in events:
        if not verified_public_event(event):
            continue
        ident = public_event_identity(event)
        if not ident or ident in displayed:
            continue
        displayed.add(ident)
        if len(displayed) <= 8:
            text = ' '.join(event['rawText'].split())[:240]
            lines.append(f'第{event["roundObserved"]}回合两次识别一致的公开内容（仅记录观察事实，不据此判定免费）：{text}')
    if len(displayed) > 8:
        lines.append('仅显示前8条已记录公开内容；完整记录保存在本局证据中。')
    if not lines:
        return '未记录可回看的情报内容'
    return '免费／付费来源未确认；以下仅为识别记录，不调整情报费用。\n' + '\n'.join(lines)
