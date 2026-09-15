"""Read only whole current-price tokens inside the four known bid bands."""
import re


def visible_seat_bids(rows, width, height, *, allow_zero=False):
    bids = [None] * 4
    for box, raw, confidence in rows or []:
        if float(confidence or 0) < .8 or not box:
            continue
        x = sum(p[0] for p in box) / len(box) / width
        y = sum(p[1] for p in box) / len(box) / height
        token = str(raw).strip().replace('，', ',').replace(' ', '')
        pattern = r'(?:\d{1,3}(?:,\d{3})+|\d{4,}|0)' if allow_zero else r'(?:\d{1,3}(?:,\d{3})+|\d{4,})'
        if not .10 <= x <= .23 or not re.fullmatch(pattern, token):
            continue
        for index, (low, high) in enumerate(((.225,.28),(.372,.43),(.520,.575),(.668,.725))):
            if low <= y <= high:
                value = int(token.replace(',', ''))
                if value > 0 or allow_zero:
                    bids[index] = max(value, bids[index] or 0)
    return bids
