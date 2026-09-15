# -*- coding: utf-8 -*-
"""
Tests for HUD incomplete status wording and AUCTION_LOADING directional semantics.
"""
import os
import sys
import json
import unittest
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from main import build_nav_hud_payload, build_in_auction_hud_payload


class TestHudWordingAndLoadingDirection(unittest.TestCase):
    def test_main_py_nav_payload_loading_direction(self):
        # Ingress loading
        ctx_ingress = {
            "scene": "AUCTION_LOADING",
            "isLoading": True,
            "loadingPercent": 45,
            "loadingVenue": "中级场 · 珊瑚场",
            "hadSettlement": False,
            "loadingDirection": "to_auction",
            "lobbyVenue": "中级场 · 珊瑚场",
            "lobbyToolGroup": "高级品鉴仪器组",
            "lobbyCharacter": "达芙蒂尔"
        }
        p_in = build_nav_hud_payload(ctx_ingress)
        self.assertEqual(p_in["solverStatus"], "loading")
        self.assertIn("正在载入拍卖 · 即将开槌", p_in["actionDirective"])
        self.assertIn("对局加载中", p_in["leaderBidSub"])
        self.assertEqual(p_in["loadingDirection"], "to_auction")

        # Egress loading
        ctx_egress = {
            "scene": "AUCTION_LOADING",
            "isLoading": True,
            "loadingPercent": 100,
            "hadSettlement": True,
            "loadingDirection": "to_lobby"
        }
        p_out = build_nav_hud_payload(ctx_egress)
        self.assertEqual(p_out["solverStatus"], "loading")
        self.assertIn("正在返回大厅", p_out["actionDirective"])
        self.assertNotIn("即将开槌", p_out["actionDirective"])
        self.assertIn("返回大厅中", p_out["leaderBidSub"])
        self.assertEqual(p_out["loadingDirection"], "to_lobby")

    def test_hud_html_renders_accurate_incomplete_and_loading(self):
        js_code = """
        const fs = require('fs');
        const html = fs.readFileSync('./core/tactical_hud.html', 'utf-8');
        
        let domState = {};
        function createDummyElement() {
            return {
                innerText: '',
                innerHTML: '',
                className: '',
                style: {},
                appendChild: () => {}
            };
        }
        global.document = {
            getElementById: (id) => {
                if (!domState[id]) domState[id] = createDummyElement();
                return domState[id];
            },
            createElement: () => createDummyElement(),
            querySelectorAll: () => []
        };
        global.window = {
            AuctionEngineV06: require('./core/auction_engine_v06.js'),
            addEventListener: () => {}
        };
        global.formatW = (v) => (v/10000).toFixed(1) + ' W';
        global.updateGrid = () => {};
        global.clearWarehouseGrid = () => {};
        global.updateWarehouseSlots = () => {};
        global.characterLabel = (d) => d.lobbyCharacter || "待识别";

        const matchTool = html.match(/function resolveToolAdvice\\([\\s\\S]*?\\n    \\}/);
        eval(matchTool[0]);
        global.resolveToolAdvice = resolveToolAdvice;

        const matchRender = html.match(/function renderHudState\\([\\s\\S]*?\\n    \\}/);
        eval(matchRender[0]);

        function runTest(payload) {
            domState = {};
            renderHudState(payload);
            return {
                badge: domState["hudStatus"]?.innerText || '',
                actionText: domState["actionText"]?.innerText || '',
                actionReason: domState["actionReason"]?.innerText || '',
                timer: domState["hudRoundTimer"]?.innerText || '',
                grade: domState["entryGrade"]?.innerText || ''
            };
        }

        // 1. Ingress loading
        const ingress = runTest({
            scene: "AUCTION_LOADING",
            isLoading: true,
            loadingPercent: 50,
            loadingVenue: "中级场 · 珊瑚场",
            hadSettlement: false,
            loadingDirection: "to_auction"
        });

        // 2. Incomplete missing avg (Q=6, no avg)
        const missingAvg = runTest({
            scene: "IN_AUCTION",
            inAuction: true,
            round: 1,
            timer: 50,
            q: 6,
            avg: null,
            totalGrids: 60,
            box: "机械宝箱 · 科技类概率提升",
            venue: "中级场 · 珊瑚场"
        });

        // 3. Valid (Q=6, goldAvg=44317)
        const validMatch = runTest({
            scene: "IN_AUCTION",
            inAuction: true,
            round: 1,
            timer: 10,
            q: 6,
            avg: 44317,
            goldAvg: 44317,
            totalGrids: 60,
            box: "机械宝箱 · 科技类概率提升",
            venue: "中级场 · 珊瑚场",
            fieldCondition: "standard"
        });

        // 4. Egress loading
        const egress = runTest({
            scene: "AUCTION_LOADING",
            isLoading: true,
            loadingPercent: 100,
            hadSettlement: true,
            loadingDirection: "to_lobby"
        });

        console.log(JSON.stringify({ ingress, missingAvg, validMatch, egress }));
        """
        out = subprocess.check_output(["node", "-e", js_code], cwd=PROJECT_ROOT, encoding="utf-8")
        data = json.loads(out)

        # 1. Ingress
        self.assertIn("载入中", data["ingress"]["badge"])
        self.assertIn("即将开槌", data["ingress"]["actionText"])

        # 2. Missing Avg
        self.assertNotIn("正在求解", data["missingAvg"]["badge"])
        self.assertIn("等待均价情报", data["missingAvg"]["badge"])
        self.assertIn("等待完整求解", data["missingAvg"]["actionText"])
        self.assertIn("不生成正式推荐", data["missingAvg"]["actionText"])

        # 3. Valid
        self.assertIn("严格求解有效", data["validMatch"]["badge"])
        self.assertIn("结构参考", data["validMatch"]["actionText"])

        # 4. Egress
        self.assertIn("返回大厅", data["egress"]["badge"])
        self.assertIn("正在返回大厅", data["egress"]["actionText"])
        self.assertNotIn("即将开槌", data["egress"]["actionText"])


if __name__ == "__main__":
    unittest.main()
