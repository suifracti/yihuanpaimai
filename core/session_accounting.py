"""Settlement-value net result; welfare receipts never modify inventory value."""
import math
import re

MAX_EXACT = 2**53 - 1


def accounting_from_facts(facts):
    from acquisition_authority import acquisition_from_context
    from session_costs import costs_from_facts
    st = facts.get('settlementData') or facts.get('settlement') or {}
    _, acquired = acquisition_from_context(facts)
    receipt = facts.get('welfareReceived') if 'welfareReceived' in facts else (st.get('welfare') or {}).get('received')
    return settlement_accounting({
        'fieldCondition': facts.get('fieldCondition'),
        'costs': facts.get('costs') if isinstance(facts.get('costs'), dict) else costs_from_facts(facts),
        'settlement': {'acquired': acquired,
            'actualTotal': facts.get('actualTotal', st.get('actualTotal')),
            'clearingPrice': facts.get('clearingPrice', st.get('clearingPrice')),
            'welfare': {'received': receipt}}})


def receipt_amount(value):
    return strict_nonnegative_integer(value, '福利金实际到账')


def strict_nonnegative_integer(value, label):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace(',', '').replace('，', '')
        if re.fullmatch(r'[0-9]+', cleaned):
            value = int(cleaned)
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 <= value <= MAX_EXACT or not math.isfinite(value) or value != int(value)):
        raise ValueError(f'{label}须为非负整数，未知请留空')
    return int(value)


def settlement_accounting(record):
    """Recompute from facts, ignoring stored realizedProfit/expected welfare.

    Net uses settlement inventory value, not proof of a completed item sale.
    Future planned costs are excluded; only paid entry/intel/other costs count.
    """
    st = record.get('settlement') or {}
    costs = record.get('costs') or {}
    env = record.get('environment') or {}
    welfare = st.get('welfare') or record.get('welfare') or {}
    condition = env.get('fieldCondition', record.get('fieldCondition'))
    missing = []
    def amount(value, label):
        try:
            result = receipt_amount(value)
        except ValueError:
            result = None
        if result is None:
            missing.append(label)
        return result
    raw_receipt = welfare.get('received')
    if raw_receipt is None and condition not in (None, '', 'unknown', 'welfare', '福利多多'):
        raw_receipt = 0
    received = amount(raw_receipt, '福利金实际到账')
    paid = [amount(costs.get('entry'), '已付入场费'),
            amount(costs.get('intel', 0), '已付情报费'), amount(costs.get('other', 0), '其他已付费用')]
    paid_total = sum(paid) if all(v is not None for v in paid) else None
    acquired = st.get('acquired')
    margin = None
    if acquired is False:
        margin = 0
    elif acquired is True:
        actual = amount(st.get('actualTotal'), '结算藏品总值')
        purchase = amount(st.get('clearingPrice'), '本人拍价')
        if actual is not None and purchase is not None:
            margin = actual - purchase
    else:
        missing.append('是否本人拍下')
    net = margin - paid_total + received if all(v is not None for v in (margin, paid_total, received)) else None
    if (paid_total is not None and paid_total > MAX_EXACT) or (net is not None and abs(net) > MAX_EXACT):
        missing.append('金额超出精确计算范围')
        net = None
    return {'basis': 'settlement-value', 'acquisitionMargin': margin, 'paidCosts': paid_total,
            'welfareReceived': received, 'sessionNet': net, 'complete': net is not None,
            'missingFacts': missing}
