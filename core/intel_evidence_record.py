"""Archive OCR evidence without assigning a free/paid source or solver authority."""

from copy import deepcopy
from public_intel_ledger import admit_public_card_events


def intel_evidence_record(context):
    facts = context.get('intelFacts')
    observations = context.get('intelObservations')
    readings = context.get('intelCardReadings')
    events = context.get('publicCardEvents')
    if not isinstance(facts, dict) and not isinstance(observations, list) and not isinstance(readings, list) and not isinstance(events, list):
        return None
    return {
        'version': 1,
        'costClassification': 'UNKNOWN',
        'facts': deepcopy(facts) if isinstance(facts, dict) else None,
        'observations': deepcopy(observations) if isinstance(observations, list) else [],
        'cardReadings': deepcopy(readings) if isinstance(readings, list) else [],
        'publicCardEvents': admit_public_card_events(events) if isinstance(events, list) else [],
    }


def restore_intel_evidence(record):
    evidence = record.get('intelCardEvidence')
    if not isinstance(evidence, dict) or type(evidence.get('version')) is not int or evidence['version'] != 1:
        return {}
    restored = {}
    if isinstance(evidence.get('facts'), dict) or evidence.get('facts') is None:
        restored['intelFacts'] = deepcopy(evidence.get('facts'))
    if isinstance(evidence.get('observations'), list):
        restored['intelObservations'] = deepcopy(evidence['observations'])
    if isinstance(evidence.get('cardReadings'), list):
        restored['intelCardReadings'] = deepcopy(evidence['cardReadings'])
    if isinstance(evidence.get('publicCardEvents'), list):
        restored['publicCardEvents'] = admit_public_card_events(evidence['publicCardEvents'])
    return restored
