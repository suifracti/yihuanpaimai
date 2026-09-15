"""Rule availability is distinct from observed intel and paid cost events."""


def free_intel_status(facts):
    condition = facts.get('fieldCondition')
    if isinstance(condition, dict):
        condition = condition.get('id') or condition.get('name')
    if condition not in ('extraIntel', 'extra_intel', 'first_intel', '一手情报'):
        return None
    raw_round = facts.get('roundNo') if 'roundNo' in facts else facts.get('round')
    round_no = raw_round if type(raw_round) is int and 1 <= raw_round <= 4 else None
    settled = facts.get('isSettlement') is True or facts.get('scene') == 'SETTLEMENT' or facts.get('lifecycleStatus') == 'FINALIZED' or facts.get('settlementFinalized') is True
    available = round_no in (1, 3) if round_no is not None else None
    if settled:
        status, message = 'SETTLED', '本局已结算；第1、3回合的免费公开情报请按已记录内容回看。'
    elif round_no is None:
        status, message = 'ROUND_UNKNOWN', '回合待识别；本词条第1、3回合有免费公开情报，当前不推定已经获得。'
    elif available:
        status, message = 'RULE_AVAILABLE', f'第{round_no}回合有一条免费公开情报；具体内容以已识别记录为准，不代表本回合其他情报也免费。'
    else:
        status, message = 'NOT_SCHEDULED', f'第{round_no}回合没有本词条额外免费情报；免费公开情报在第1、3回合。'
    return {'condition':'extraIntel', 'round':round_no, 'status':status,
            'scheduledRounds':[1,3], 'availableByRule':available,
            'observed':False, 'message':message}
