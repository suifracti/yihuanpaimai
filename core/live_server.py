"""
Neverness to Everness (异环) - 战术 HUD 实时通信网关 (v0.65)
功能：
  1. 托管 tactical_hud.html 静态 Web 页面 (HTTP: 127.0.0.1:8765)
  2. 提供 WebSocket 实时数据管道 (WS: 127.0.0.1:8766)
  3. 接收视觉引擎识别出的最新 context，毫秒级广播给前端悬浮窗
"""

import asyncio
import json
import os
import sys
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
from http.server import SimpleHTTPRequestHandler
import socketserver
import threading
from typing import Set
import websockets

HTTP_PORT = 8765
WS_PORT = 8766

# 保存所有活跃的 HUD WebSocket 客户端连接
CONNECTED_CLIENTS: Set[websockets.WebSocketServerProtocol] = set()

# 当前最新状态快照
LATEST_PAYLOAD = {
    "round": 1,
    "timer": 15,
    "valP50": "97.3 W",
    "valRange": "85.0W ~ 110.0W",
    "leaderBid": "45.4 W",
    "targetProfitLine": "48.0 W",
    "marginalChaseLine": "52.0 W",
    "marketRatioEst": "50.5 W (正常竞争)",
    "actionDirective": "🟢 建议跟拍",
    "actionReason": "毛利空间充足 · 领先 45.4W < 边际线 52.0W",
    "entryGrade": "A+ 准入",
    "isFold": False,
    "gridCells": [0] * 250
}

async def ws_handler(websocket):
    CONNECTED_CLIENTS.add(websocket)
    try:
        # 连接建立时立即推送最新快照
        await websocket.send(json.dumps(LATEST_PAYLOAD))
        async for message in websocket:
            pass # 接收客户端指令（若有）
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        CONNECTED_CLIENTS.remove(websocket)

async def broadcast_update(payload: dict):
    global LATEST_PAYLOAD
    LATEST_PAYLOAD.update(payload)
    if CONNECTED_CLIENTS:
        msg = json.dumps(LATEST_PAYLOAD)
        await asyncio.gather(*[client.send(msg) for client in CONNECTED_CLIENTS], return_exceptions=True)

def start_http_server(web_dir: str):
    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=web_dir, **kwargs)
        def log_message(self, format, *args):
            pass # 静默无干扰日志

    with socketserver.TCPServer(("127.0.0.1", HTTP_PORT), QuietHandler) as httpd:
        httpd.serve_forever()

async def run_server():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 启动 HTTP 静态服务线程
    http_thread = threading.Thread(target=start_http_server, args=(base_dir,), daemon=True)
    http_thread.start()
    print(f"⚡ [HTTP] 战术 HUD 悬浮窗地址: http://127.0.0.1:{HTTP_PORT}/tactical_hud.html")
    print(f"⚡ [WS]   实时数据总线已就绪: ws://127.0.0.1:{WS_PORT}")

    # 启动 WebSocket 服务
    async with websockets.serve(ws_handler, "127.0.0.1", WS_PORT):
        await asyncio.Future() # 永久运行

if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\n网关已平稳关闭。")
