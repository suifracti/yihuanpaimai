import copy
import unittest
from intel_evidence_presentation import intel_evidence_text


class IntelPresentationTests(unittest.TestCase):
    def test_status_conflicts_challengers_and_unique_sources(self):
        source = {'frameId': 'f1', 'rawText': '金色藏品总数量2'}
        for status, extra, expected in (
            ('UNKNOWN', {'tentative': 2}, '待确认 2'),
            ('OBSERVED', {'value': 2}, '识别已确认 2'),
            ('OBSERVED', {'value': 2, 'challenger': 3}, '另有待复核读数 3'),
            ('CONFLICT', {'candidates': [2, 3]}, '存在冲突；候选 2 / 3'),
        ):
            record = {'intelCardEvidence': {'version': 1, 'facts': {
                'goldCount': {'status': status, 'sources': [source, source], **extra}},
                'observations': []}}
            original = copy.deepcopy(record)
            text = intel_evidence_text(record)
            self.assertIn(expected, text)
            self.assertIn('记录来源 1 帧', text)
            self.assertEqual(text.count(source['rawText']), 1)
            self.assertIn('免费／付费来源未确认', text)
            self.assertEqual(record, original)

    def test_missing_unknown_version_malformed_and_bounded_text(self):
        self.assertEqual(intel_evidence_text({}), '未记录情报识别证据')
        for version in (True, None, 2, '1'):
            self.assertIn('暂不支持', intel_evidence_text({'intelCardEvidence': {'version': version}}))
        record = {'intelCardEvidence': {'version': 1, 'facts': {'goldCount': {
            'status': 'CONFLICT', 'candidates': [True, {}, 2], 'sources': [None, {'frameId': [], 'rawText': 'x'*10000}]}},
            'observations': [None, {'field': 'goldCount', 'rawText': '<img src=x onerror=alert(1)>'}]}}
        text = intel_evidence_text(record)
        self.assertIn('未知 / 未知 / 2', text)
        self.assertLess(len(text), 600)
        self.assertIn('<img', text)  # Renderer must use textContent, never HTML.
