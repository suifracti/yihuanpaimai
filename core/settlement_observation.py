"""Keep one coherent, strongest stable viewport for a settlement bill.

Scrolling into empty warehouse rows must not replace the recorded item list.
This does not join different viewports or claim complete warehouse coverage.
"""
import copy


class SettlementObservation:
    def __init__(self):
        self.key = None
        self.best = None

    def select(self, *, key, ledger, frame, captured_at):
        if self.key != key:
            self.key, self.best = key, None
        items = ledger.get('settlementItems') or []
        closed = [i for i in items if not i.get('groupingAmbiguous')]
        area = lambda i: int(i.get('occupiedCount') or
                             (i.get('widthCells') or 1) * (i.get('heightCells') or 1))
        score = (sum(map(area, closed)), sum(area(i) for i in closed if i.get('status') == 'exact'),
                 sum(i.get('status') == 'exact' for i in closed), -len(items) + len(closed))
        if self.best is None or score > self.best['score']:
            self.best = {'score': score, 'ledger': copy.deepcopy(ledger),
                         'frame': frame.copy(), 'capturedAt': captured_at}
        return self.best
