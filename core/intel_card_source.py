"""Classify an explicitly read card title, without assigning cost or entitlement."""
import re


def card_source(raw_text):
    compact = re.sub(r'\s+', '', raw_text) if isinstance(raw_text, str) else ''
    title = '拍卖师公开情报'
    # Require the complete leading title followed by the observed body prefix.
    # A title mentioned in an instrument's body or a partial OCR match is not enough.
    if compact.startswith(title + '本局') or compact.startswith(title + '随机'):
        return {'kind': 'AUCTIONEER_PUBLIC', 'title': title, 'basis': 'EXACT_OCR_TITLE'}
    return {'kind': 'UNKNOWN', 'title': None, 'basis': None}
