import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_replay_identities import audit


class ReplayIdentityAuditTests(unittest.TestCase):
    def test_incomplete_or_wrong_inventory_cannot_pass_correct_bill(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs, samples = [], []
            for n in range(5):
                run = Path(tmp) / str(n)
                (run / "data").mkdir(parents=True)
                (run / "report.json").write_text('{"status":"COMPLETE"}', encoding="utf-8")
                item = dict(row=0, col=0, widthCells=1, heightCells=1, name=f"item-{n}", price=n+1, status="exact")
                record = {"records": [{"settlement": {"actualTotal": n+1, "settlementItems": [item]}}]}
                (run / "data/history-1.json").write_text(json.dumps(record), encoding="utf-8")
                samples.append(dict(image=str(n), actualTotal=n+1, rectangles=[[0, 0, 1, 1]],
                                    identityAnnotations=[dict(rect=[0, 0, 1, 1], name=f"item-{n}", value=n+1)]))
                runs.append(run)
            self.assertEqual(audit(runs, samples)["status"], "PASS")
            # Agreement with labels is insufficient if their complete sum
            # contradicts the bill. This is unresolved ground truth, not PASS.
            changed = json.loads(json.dumps(samples))
            changed[-1]['identityAnnotations'][0]['value'] = 6
            last_path = runs[-1] / 'data/history-1.json'
            original = last_path.read_text(encoding='utf-8')
            changed_record = json.loads(original)
            changed_record['records'][0]['settlement']['settlementItems'][0]['price'] = 6
            last_path.write_text(json.dumps(changed_record), encoding='utf-8')
            self.assertEqual(audit(runs, changed)['status'], 'PARTIAL')
            last_path.write_text(original, encoding='utf-8')
            self.assertNotEqual(audit([runs[0]] * 5, samples)["status"], "PASS")
            path = runs[-1] / "data/history-1.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            item = record["records"][0]["settlement"]["settlementItems"][0]
            item["status"] = "unknown"
            path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(audit(runs, samples)["status"], "PARTIAL")
            item.update(status="exact", price=999)
            path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(audit(runs, samples)["status"], "FAIL")
            item.update(price=5, name="wrong item")
            path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(audit(runs, samples)["status"], "FAIL")
