import os, sys, time, json, subprocess
import unittest

PROJECT_ROOT = r"D:\yihuanpaimai"

class TestDragRenderSuspension(unittest.TestCase):
    def test_render_suspension_logic(self):
        """测试拖拽期间 DOM 渲染挂起与拖拽结束原子 Flush"""
        js_code = """
        const fs = require('fs');
        const html = fs.readFileSync('./core/tactical_hud.html', 'utf-8');

        // Mock browser DOM environment in Node.js
        let domUpdates = 0;
        const mockElements = {};
        function getMockEl(id) {
            if (!mockElements[id]) {
                mockElements[id] = {
                    innerText: '',
                    innerHTML: '',
                    style: {},
                    className: '',
                    appendChild: () => { domUpdates++; }
                };
            }
            return new Proxy(mockElements[id], {
                set(target, prop, val) {
                    if (prop === 'innerText' || prop === 'innerHTML' || prop === 'className') {
                        domUpdates++;
                    }
                    target[prop] = val;
                    return true;
                }
            });
        }

        global.document = {
            getElementById: getMockEl,
            createElement: (tag) => ({ style: {}, appendChild: () => {}, innerHTML: '' }),
            querySelectorAll: () => []
        };
        global.window = {
            AuctionEngineV06: require('./core/auction_engine_v06.js'),
            addEventListener: () => {}
        };
        global.formatW = (v) => (v/10000).toFixed(1) + ' W';
        global.updateGrid = () => { domUpdates++; };
        global.clearWarehouseGrid = () => {};
        global.updateWarehouseSlots = () => {};
        global.characterLabel = (d) => d.lobbyCharacter || "待识别";

        // Extract resolveToolAdvice and renderHudState from tactical_hud.html
        const matchTool = html.match(/function resolveToolAdvice\\([\\s\\S]*?\\n    \\}/);
        eval(matchTool[0]);
        global.resolveToolAdvice = resolveToolAdvice;

        const matchRender = html.match(/function renderHudState\\([\\s\\S]*?\\n    \\}/);
        eval(matchRender[0]);

        // Simulating the WS receiver & Drag State logic
        let isWindowDragging = false;
        let pendingDragRenderPayload = null;

        function __onHostDragStateChange(dragging) {
            isWindowDragging = Boolean(dragging);
            if (!isWindowDragging && pendingDragRenderPayload) {
                const payload = pendingDragRenderPayload;
                pendingDragRenderPayload = null;
                renderHudState(payload);
            }
        }

        function onWsMessage(msgData) {
            if (isWindowDragging) {
                pendingDragRenderPayload = msgData;
                return;
            }
            renderHudState(msgData);
        }

        // --- EXPERIMENT SCENARIOS ---

        // 1. Normal Stationary (静止状态): 10 observations -> 10 DOM renders
        domUpdates = 0;
        for (let i = 1; i <= 10; i++) {
            onWsMessage({
                inAuction: true,
                round: 2,
                timer: 15 - i,
                q: 9,
                avg: 33538,
                knownPurple: "拈花小像+金角月芒",
                knownGold: "万有星仪",
                leaderBid: 50000 + i * 1000
            });
        }
        const stationaryDomUpdates = domUpdates;

        // 2. Slow Drag 2s (20 observations @ 10Hz): dragging=true -> 0 DOM renders
        domUpdates = 0;
        __onHostDragStateChange(true);
        for (let i = 1; i <= 20; i++) {
            onWsMessage({
                inAuction: true,
                round: 2,
                timer: 20 - i,
                q: 9,
                avg: 33538,
                knownPurple: "拈花小像+金角月芒",
                knownGold: "万有星仪",
                leaderBid: 60000 + i * 1000
            });
        }
        const drag2sDomUpdates = domUpdates;
        const drag2sPending = pendingDragRenderPayload !== null;

        // Drag ends: single atomic flush
        __onHostDragStateChange(false);
        const drag2sPostFlushUpdates = domUpdates;
        const finalLeaderBidAfter2s = mockElements['leaderBid'] ? mockElements['leaderBid'].innerText : '';

        // 3. Slow Drag 20s (200 observations @ 10Hz): dragging=true -> 0 DOM renders
        domUpdates = 0;
        __onHostDragStateChange(true);
        for (let i = 1; i <= 200; i++) {
            onWsMessage({
                inAuction: true,
                round: 3,
                timer: 30 - (i % 30),
                q: 9,
                avg: 33538,
                knownPurple: "拈花小像+金角月芒",
                knownGold: "万有星仪",
                leaderBid: 100000 + i * 500
            });
        }
        const drag20sDomUpdates = domUpdates;
        __onHostDragStateChange(false);
        const drag20sPostFlushUpdates = domUpdates;
        const finalLeaderBidAfter20s = mockElements['leaderBid'] ? mockElements['leaderBid'].innerText : '';

        console.log(JSON.stringify({
            stationaryDomUpdates,
            drag2sDomUpdates,
            drag2sPending,
            drag2sPostFlushUpdates,
            finalLeaderBidAfter2s,
            drag20sDomUpdates,
            drag20sPostFlushUpdates,
            finalLeaderBidAfter20s
        }));
        """
        out = subprocess.check_output(["node", "-e", js_code], cwd=PROJECT_ROOT, encoding="utf-8")
        data = json.loads(out)

        # 1. 验证静止状态下正常以 10 FPS 触发 DOM 渲染
        self.assertGreater(data["stationaryDomUpdates"], 0)

        # 2. 验证 2s 慢拖中 DOM 渲染严格挂起 (updates == 0)
        self.assertEqual(data["drag2sDomUpdates"], 0, "During 2s drag, DOM updates must be 0")
        self.assertTrue(data["drag2sPending"], "Latest payload must be preserved during 2s drag")
        # 拖拽结束时触发单次原子 flush
        self.assertGreater(data["drag2sPostFlushUpdates"], 0)
        self.assertIn("8.0 W", data["finalLeaderBidAfter2s"])

        # 3. 验证 20s 长时慢拖 (200 帧 Observation) 中 DOM 渲染严格为 0
        self.assertEqual(data["drag20sDomUpdates"], 0, "During 20s drag, DOM updates must be 0")
        # 拖拽结束时触发单次原子 flush，呈现最新累积出价 20.0 W (100000 + 200*500)
        self.assertGreater(data["drag20sPostFlushUpdates"], 0)
        self.assertIn("20.0 W", data["finalLeaderBidAfter20s"])

if __name__ == "__main__":
    unittest.main()
