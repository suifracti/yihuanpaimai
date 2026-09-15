# -*- coding: utf-8 -*-
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("audit.py")
SPEC = importlib.util.spec_from_file_location("upper_tail_state_support_audit", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(audit)


class UpperTailStateSupportAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = audit.build_audit()

    def test_uses_same_global_oos_population(self):
        self.assertEqual(self.payload["selection"]["oosN"], 48)
        self.assertEqual(len(set(self.payload["selection"]["oosRecordIds"])), 48)

    def test_extreme_selection_is_pre_registered(self):
        self.assertEqual(self.payload["extremeUpperTail"]["selectedN"], 7)
        for row in self.payload["extremeUpperTail"]["records"]:
            self.assertGreaterEqual(row["actualTotal"], audit.EXTREME_ACTUAL_FLOOR)
            self.assertGreater(row["actualTotal"], row["savedP80"])

    def test_verified_extreme_state_recall(self):
        extreme = self.payload["extremeUpperTail"]
        self.assertEqual(extreme["truthEligibleN"], 3)
        self.assertEqual(extreme["truthStateRecalledN"], 3)

    def test_gold_cap_not_observed_as_loss(self):
        gold = self.payload["goldCountSupport"]
        self.assertEqual(gold["observedGoldCapLossN"], 0)
        self.assertEqual(gold["truthGInFullCandidateN"], 19)
        self.assertEqual(gold["truthEligibleN"], 20)

    def test_likelihood_suppression_is_mass_based(self):
        rows = {row["recordId"]: row for row in self.payload["extremeUpperTail"]["records"]}
        row = rows["r-mspvjp1i-kpyt6n"]
        self.assertEqual(row["classification"], "B_STATE_LIKELIHOOD_SUPPRESSION")
        self.assertGreaterEqual(row["uniformMassOfP80CapableStates"], audit.P80_TAIL_MASS)
        self.assertLess(row["weightedMassOfP80CapableStates"], audit.P80_TAIL_MASS)

    def test_verified_value_support_failures_exist(self):
        rows = [row for row in self.payload["extremeUpperTail"]["records"] if row["classification"] == "C_VALUE_MODEL_ERROR"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIsNotNone(row["realizedState"])
            self.assertLess(row["truthOrLockedStateMax"], row["actualTotal"])

    def test_current_head_replay_is_geometry_only_and_complete(self):
        replay = self.payload["currentHeadReplay"]
        self.assertEqual(replay["status"], "PASS")
        self.assertEqual(replay["replayedN"], 7)
        self.assertEqual(replay["errorN"], 0)
        self.assertEqual(replay["candidateGeometryMatchN"], 7)
        self.assertLess(replay["predictionDistributionReproducedN"], 7)

    def test_integrity_hashes_are_unchanged(self):
        integrity = self.payload["integrity"]
        self.assertEqual(integrity["databaseSha256Before"], integrity["databaseSha256After"])
        self.assertEqual(integrity["solverSha256Before"], integrity["solverSha256After"])
        self.assertEqual(integrity["shadowSha256Before"], integrity["shadowSha256After"])
        self.assertFalse(integrity["productionFilesModified"])

    def test_final_verdict_is_conservative(self):
        self.assertEqual(self.payload["verdict"]["primaryBottleneck"], "INCONCLUSIVE")
        self.assertFalse(self.payload["verdict"]["productionChangeRecommended"])


if __name__ == "__main__":
    unittest.main()
