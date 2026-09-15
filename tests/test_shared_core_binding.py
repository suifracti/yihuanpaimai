import os, sys, json, subprocess
import unittest

PROJECT_ROOT = r"D:\yihuanpaimai"
CORE_DIR = os.path.join(PROJECT_ROOT, "core")

class TestSharedCoreBindingRegression(unittest.TestCase):
    def test_shared_core_pipeline_pure_calculation(self):
        """测试 Shared Core solveAuctionPipeline 纯算法求解与输出结构"""
        js_code = """
        const engine = require('./core/auction_engine_v06.js');
        
        // 1. 15:53 经典测试对局 (低出价在目标利润区)
        const res1 = engine.solveAuctionPipeline({
            q: 9, avg: 33538, p: 5, roundingMode: "floor",
            knownPurple: "拈花小像+金角月芒", knownGold: "万有星仪",
            leaderBid: 50000
        });

        // 2. 超过边际追价线对局 (高出价超 marginalLine)
        const resOver = engine.solveAuctionPipeline({
            q: 9, avg: 33538, p: 5, roundingMode: "floor",
            knownPurple: "拈花小像+金角月芒", knownGold: "万有星仪",
            leaderBid: 200000
        });

        // 3. 无可行解冲突对局
        const resConflict = engine.solveAuctionPipeline({
            q: 9, avg: 999999999
        });

        // 4. 降级对局 (缺少 avg)
        const resFallback = engine.solveAuctionPipeline({
            q: 9
        });

        console.log(JSON.stringify({
            valid: {
                status: res1.solverStatus,
                ev: res1.formalValue.ev,
                p20: res1.formalValue.p20,
                p80: res1.formalValue.p80,
                targetLine: res1.decision.targetLine,
                globalLine: res1.decision.globalLine,
                marginalLine: res1.decision.marginalLine,
                marketPrice: res1.marketPrediction ? res1.marketPrediction.expectedPrice : null,
                actionDirective: res1.decision.actionDirective,
                entryGrade: res1.decision.entryGrade,
                isFold: res1.decision.isFold
            },
            over: {
                status: resOver.solverStatus,
                actionDirective: resOver.decision.actionDirective,
                isFold: resOver.decision.isFold
            },
            conflict: {
                status: resConflict.solverStatus,
                actionDirective: resConflict.decision.actionDirective,
                isFold: resConflict.decision.isFold
            },
            fallback: {
                status: resFallback.solverStatus,
                actionDirective: resFallback.decision.actionDirective
            }
        }));
        """
        out = subprocess.check_output(["node", "-e", js_code], cwd=PROJECT_ROOT, encoding="utf-8")
        data = json.loads(out)

        # 1. 验证目标区对局输出
        valid = data["valid"]
        self.assertEqual(valid["status"], "valid")
        self.assertIsNotNone(valid["ev"])
        self.assertGreater(valid["ev"], 100000)
        # 无真实 Shadow 时不得产出正式三线 / 追价指令
        self.assertIsNone(valid["targetLine"])
        self.assertIsNone(valid["marginalLine"])
        self.assertIn("结构参考", valid["actionDirective"])
        self.assertFalse(valid["isFold"])

        # 2. 无 Full Shadow 时高叫价也不得包装成正式「建议停止」
        over = data["over"]
        self.assertEqual(over["status"], "valid")
        self.assertIn("结构参考", over["actionDirective"])
        self.assertFalse(over["isFold"])

        # 3. 验证冲突对局输出
        conflict = data["conflict"]
        self.assertEqual(conflict["status"], "no-match")
        self.assertIn("无可行解", conflict["actionDirective"])
        self.assertTrue(conflict["isFold"])

        # 4. 验证降级对局输出
        fallback = data["fallback"]
        self.assertEqual(fallback["status"], "fallback")
        self.assertIn("等待完整求解", fallback["actionDirective"])

    def test_tool_advice_semantics(self):
        """测试道具使用建议语义：严禁按轮次盲猜，严格基于装备组与可用性"""
        js_code = """
        const fs = require('fs');
        const html = fs.readFileSync('./core/tactical_hud.html', 'utf-8');
        
        // 提取 resolveToolAdvice 函数并在 Node 环境中执行
        const match = html.match(/function resolveToolAdvice\\([\\s\\S]*?\\n    \\}/);
        if (!match) throw new Error('resolveToolAdvice not found in HTML');
        
        eval(match[0]);

        const rUnknown = resolveToolAdvice({ inAuction: true, round: 2 }); // 未识别道具组
        const rStatusUnknown = resolveToolAdvice({ inAuction: true, round: 2, loadout: ['品质透视'], toolStatusKnown: false });
        const rQuality = resolveToolAdvice({ inAuction: true, round: 2, availableToolActions: ['品质透视'], avg: 33538 });
        const rItem = resolveToolAdvice({ inAuction: true, round: 3, availableToolActions: ['藏品透视'], knownGold: ['万有星仪'] });
        const rExhausted = resolveToolAdvice({ inAuction: true, round: 4, availableToolActions: ['品质透视'], usedToolActions: ['品质透视'] });
        const rNoAuction = resolveToolAdvice({ inAuction: false, round: 0 });

        console.log(JSON.stringify({
            rUnknown,
            rStatusUnknown,
            rQuality,
            rItem,
            rExhausted,
            rNoAuction
        }));
        """
        out = subprocess.check_output(["node", "-e", js_code], cwd=PROJECT_ROOT, encoding="utf-8")
        data = json.loads(out)

        self.assertIn("未确认装备", data["rUnknown"])
        self.assertIn("道具状态未知", data["rStatusUnknown"])
        self.assertIn("品质透视", data["rQuality"])
        self.assertIn("藏品透视", data["rItem"])
        self.assertIn("全部消耗", data["rExhausted"])
        self.assertIn("等待进入对局", data["rNoAuction"])

    def test_main_py_contains_no_tactical_magic_numbers(self):
        """严格审计 app/main.py，断言零硬编码估值与出价线"""
        main_py = os.path.join(PROJECT_ROOT, "app", "main.py")
        with open(main_py, "r", encoding="utf-8") as f:
            content = f.read()

        forbidden_patterns = [
            "232972",
            "est_val = ",
            "target_line = ",
            "chase_line = ",
            "target_line =",
            "chase_line =",
            "int(est_val",
            "format_val_w(int(est_val",
        ]
        for pat in forbidden_patterns:
            self.assertNotIn(pat, content, f"app/main.py contains forbidden hardcoded pattern: {pat}")

    def test_tactical_hud_shared_core_field_binding(self):
        """审计 core/tactical_hud.html，断言所有决策与估值字段来自 engineResult"""
        hud_html = os.path.join(PROJECT_ROOT, "core", "tactical_hud.html")
        with open(hud_html, "r", encoding="utf-8") as f:
            content = f.read()

        required_bindings = [
            'window.AuctionEngineV06.solveAuctionPipeline(d)',
            'document.getElementById("valP50").innerText = evStr',
            'document.getElementById("targetProfitLine")',
            'document.getElementById("globalProfitLine")',
            'document.getElementById("marginalChaseLine")',
            'document.getElementById("actionText").innerText = dec.actionDirective',
            'document.getElementById("actionReason").innerText = dec.actionReason',
            'isFullShadow',
            'document.getElementById("intelItemAdvice").innerText = resolveToolAdvice(d)',
        ]
        for req in required_bindings:
            self.assertIn(req, content, f"core/tactical_hud.html is missing required binding: {req}")

if __name__ == "__main__":
    unittest.main()
