"""Re-read the real-once-10 match valuation without rerunning recognition."""

import copy
import json
import unittest
from pathlib import Path

from core.match_remaining_valuation import (
    apply_remaining_valuation,
    build_remaining_valuation,
    write_remaining_valuation,
)


HISTORY = Path(
    r"D:\yihuanpaimai\build\t1-20261012\real-once-10\runtime-data"
    r"\native-live-trial\canonical-history.json"
)


class MatchRemainingValuationTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(HISTORY.read_text(encoding="utf-8"))
        self.record = self.document["records"][0]

    def test_same_match_reread_is_stable_and_uses_saved_prices(self):
        resolved = self.record["settlement"]["warehouseIdentityReview"]["resolvedItems"]
        oracle_items = [item for item in resolved if isinstance(item.get("catalogValue"), int)]
        oracle_subtotal = sum(item["catalogValue"] for item in oracle_items)
        unconfirmed = [
            unit for unit in self.record["settlement"]["reviewUnits"]
            if unit.get("confirmationStatus") != "CONFIRMED"
        ]

        first_record = copy.deepcopy(self.record)
        first = apply_remaining_valuation(first_record)
        second = apply_remaining_valuation(first_record)

        self.assertEqual(second, first)
        self.assertEqual(first["confirmedItems"]["count"], len(oracle_items))
        self.assertEqual(first["confirmedItems"]["catalogSubtotal"], oracle_subtotal)
        self.assertEqual(
            first["wholeWarehouse"]["lower"],
            oracle_subtotal + first["remainingRange"]["lower"],
        )
        self.assertEqual(
            first["wholeWarehouse"]["upper"],
            oracle_subtotal + first["remainingRange"]["upper"],
        )
        self.assertLessEqual(first["remainingRange"]["lower"], first["remainingRange"]["upper"])
        if not unconfirmed:
            self.assertEqual(first["remainingRange"], {"lower": 0, "upper": 0})
        reasons = {item["name"]: item["disposition"] for item in first["unrecognizedReasons"] if item.get("name")}
        self.assertEqual(reasons["梦中萤"], "缺素材")
        self.assertIn(reasons["梦中茧"], {"METADATA", "缺素材"})
        self.assertEqual(build_remaining_valuation(first_record), first)

    def test_disk_reread_matches_the_first_write(self):
        written = write_remaining_valuation(str(HISTORY))
        reread = json.loads(HISTORY.read_text(encoding="utf-8"))
        stored = reread["records"][0]["settlement"]["remainingValuation"]
        self.assertEqual(stored, written)
        self.assertEqual(apply_remaining_valuation(reread["records"][0]), stored)


if __name__ == "__main__":
    unittest.main()
