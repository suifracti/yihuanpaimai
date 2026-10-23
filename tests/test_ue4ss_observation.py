"""Structured UI -> existing Engine/CurrentMatch -> Main/HUD/history (offline)."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from ue4ss_observation import apply_snapshot, read_snapshot, text_facts
from current_match import CurrentMatch
from live_match_transport import LiveMatchPublisher, LiveMatchReceiver

ROOT = Path(__file__).resolve().parents[1]


def observation():
    return {"source": "ue4ss_ui", "sampledAt": time.time(), "readUtc": "2026-10-23T09:00:00Z",
            "session": "SYNTHETIC", "scene": "IN_AUCTION", "instance": "SYNTHETIC_UI", "curRoundIndex": 1,
            "texts": [{"text": "珊瑚场"}, {"text": "标准对局"}, {"text": "螺钿宝箱"}],
            "cards": [{"instance": "SYNTHETIC_CARD", "title": "金品均价仪器",
                       "content": "本局内所有金色品质藏品的平均价值为64，836。",
                       "cacheMatches": [{"params": [7, 123]}]},
                      {"content": "本局内所有紫色品质藏品的总数量为12。"},
                      {"content": "本局内所有紫色、金色和红色品质藏品的总件数为21。"}],
            "seats": [{"slot": 1, "name": "SYNTHETIC_PLAYER", "bidText": "120,000"}]}


class Ue4ssObservationTests(unittest.TestCase):
    def test_data_enters_engine_main_projection_and_same_record(self):
        from test_native_viewport_observation import NativeViewportObservationTests
        from venue_box_catalog import load_catalog, canonical_catalog_provenance
        from main import build_canonical_overlay_state, _native_solver_admission
        engine = NativeViewportObservationTests().engine()
        engine.venue_catalog = load_catalog()
        engine.venue_catalog_provenance = canonical_catalog_provenance(engine.venue_catalog)
        context = {"scene": "IN_AUCTION", "inAuction": True, "recordStableKey": engine.current_match.id}
        apply_snapshot(context, observation())
        engine._apply_pipeline_context(context, "2026-10-23T09:00:00Z")
        main_match = CurrentMatch()
        state = LiveMatchPublisher().attach({}, engine.current_match)["visionState"]
        self.assertTrue(LiveMatchReceiver().apply(state, main_match))
        view = build_canonical_overlay_state(main_match)
        self.assertEqual(view["goldAvg"], 64836)
        self.assertEqual(view["purpleCount"], 12)
        self.assertEqual(view["q"], 21)
        mapped, reason = _native_solver_admission(main_match.facts)
        self.assertIsNone(reason)
        self.assertTrue(mapped)
        self.assertEqual(main_match.facts["roundNo"], 2)
        self.assertEqual(main_match.facts["seats"][0]["currentBid"], 120000)
        record = main_match.to_canonical()
        self.assertEqual(record["auctionEvidence"]["ue4ss"][0]["data"]["curRoundIndex"], 1)
        self.assertEqual(record["qualities"]["gold"]["avg"], 64836)
        self.assertTrue(record["bidding"]["rounds"])

    def test_unknown_and_shortened_values_never_erase_facts_or_guess_params(self):
        context = {"goldAvg": 87654, "purpleCount": 4, "warehouseCoverage": {"status": "PARTIAL"}}
        data = observation()
        data["cards"] = [{"content": "金色品质藏品平均价值为64.8K。", "cacheMatches": [{"params": [64800]}]}]
        apply_snapshot(context, data)
        self.assertEqual(context["goldAvg"], 87654)
        self.assertEqual(context["purpleCount"], 4)
        self.assertEqual(context["warehouseCoverage"]["status"], "PARTIAL")
        self.assertNotIn("goldAvg", text_facts(data))
        before = copy.deepcopy(context["auctionEvidence"])
        data["readUtc"] = "2026-10-23T09:00:01Z"
        data["texts"].append({"text": "00:29"})
        apply_snapshot(context, data)
        self.assertEqual(before["ue4ss"], context["auctionEvidence"]["ue4ss"])

    def test_closed_channel_is_fallback_and_direct_round_does_not_ocr(self):
        from vision_pipeline import NTEVisionPipeline
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as folder:
            path = Path(folder) / "auction.json"
            self.assertIsNone(read_snapshot(path))
            path.write_text('{"unfinished":', encoding="utf-8")
            self.assertIsNone(read_snapshot(path))
            data = observation(); path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(read_snapshot(path)["curRoundIndex"], 1)
            data["sampledAt"] -= 60; path.write_text(json.dumps(data), encoding="utf-8")
            self.assertIsNone(read_snapshot(path))
        pipeline = NTEVisionPipeline.__new__(NTEVisionPipeline)
        pipeline._ue4ss_snapshot = observation()
        self.assertEqual(pipeline._read_df_auction_round_title(None), 2)

    def test_bill_and_list_keep_existing_truth_and_coverage(self):
        context = {"settlementData": {"animationComplete": False}, "warehouseCoverage": {"status": "PARTIAL"}}
        data = observation(); data.update(scene="SETTLEMENT", cards=[], seats=[],
            bill={"winner": "SYNTHETIC_PLAYER", "bidText": "100,000", "valueText": "120,000", "incomeText": "+20,000"},
            settlementList={"completeness": "UNKNOWN", "slots": [{"name": "SYNTHETIC_ITEM"}]})
        apply_snapshot(context, data)
        self.assertEqual(context["actualTotal"], 120000)
        self.assertFalse(context["settlementData"]["animationComplete"])
        self.assertEqual(context["warehouseCoverage"]["status"], "PARTIAL")
        self.assertNotIn("settlementItems", context)
        self.assertNotIn("isAcquired", context)


if __name__ == "__main__":
    unittest.main()
