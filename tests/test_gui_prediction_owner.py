"""Production computation stays in GUI; its result is relayed to the archiver."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "app", ROOT / "core"):
    sys.path.insert(0, str(path))
import main
from current_match import CurrentMatch
from prediction_snapshot_holder import ActivePredictionSnapshotHolder


class GuiPredictionOwnerTests(unittest.TestCase):
    def test_busy_webview_cannot_block_fact_receiver(self):
        host = Mock()
        host.is_ready.side_effect = AssertionError('synchronous UI call on message receiver')
        current = CurrentMatch()
        current.apply_facts({'q': 21, 'goldAvg': 64836})
        with patch.object(main, 'CURRENT_MATCH', current), \
             patch('live_shadow.get_webview_host', return_value=host), \
             patch('live_shadow.load_history_snapshot'), \
             patch('live_shadow.attach_live_shadow', return_value={'shadowUpdating': True}) as schedule:
            payload, response = main.attach_gui_prediction({'scene': 'IN_AUCTION'})
        host.is_ready.assert_not_called()
        self.assertEqual(schedule.call_args.args[0]['q'], 21)
        self.assertTrue(payload['shadowUpdating'])
        self.assertIsNone(response)

    def test_worker_hud_does_not_request_a_second_solver(self):
        with patch("live_shadow.attach_live_shadow") as attach:
            main.build_in_auction_hud_payload({"scene": "IN_AUCTION", "round": 1}, compute_shadow=False)
            attach.assert_not_called()

    def test_gui_uses_webview_result_and_emits_bound_worker_message(self):
        current = CurrentMatch()
        current.apply_facts({"q": 12, "goldAvg": 30000})
        holder = ActivePredictionSnapshotHolder()
        snapshot = {"matchId": current.id, "forecast": {"value": 50000}}
        result = {"predictionSnapshot": snapshot, "frozenPrediction": {"value": 50000},
                  "probabilityProfile": {"sampleN": 3}, "shadowUpdating": False}
        with patch.object(main, "CURRENT_MATCH", current), \
             patch.object(main, "ACTIVE_SNAPSHOT_HOLDER", holder), \
             patch("live_shadow.get_webview_host", return_value=Mock(is_ready=lambda: True)), \
             patch("live_shadow.load_history_snapshot"), \
             patch("live_shadow.attach_live_shadow", return_value=result) as attach:
            payload, message = main.attach_gui_prediction({"scene": "IN_AUCTION"})
        self.assertEqual(attach.call_args.args[0]["matchId"], current.id)
        self.assertEqual(attach.call_args.args[0]["q"], 12)
        self.assertEqual(payload["probabilityProfile"], result["probabilityProfile"])
        self.assertEqual(message["action"], "prediction_snapshot")
        self.assertEqual(message["matchId"], current.id)
        self.assertEqual(holder.get_snapshot_for_match(current.id), snapshot)

    def test_no_webview_still_schedules_persistent_compute(self):
        current = CurrentMatch()
        current.apply_facts({"q": 21, "goldAvg": 64836})
        with patch.object(main, "CURRENT_MATCH", current), \
             patch("live_shadow.get_webview_host", return_value=None), \
             patch("live_shadow.load_history_snapshot"), \
             patch("live_shadow.attach_live_shadow", return_value={"shadowUpdating": True, "probabilityProfile": None}) as attach:
            payload, message = main.attach_gui_prediction({"scene": "IN_AUCTION"})
        attach.assert_called_once()
        self.assertTrue(payload["shadowUpdating"])
        self.assertIsNone(message)
