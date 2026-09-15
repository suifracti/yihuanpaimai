"""
Neverness to Everness (异环) - 实时画面捕获与回放驱动器 (v0.65)
模式：
  1. 真实挂机模式: python live_capture.py (自动抓取游戏窗口并推流)
  2. 录像回放模式: python live_capture.py --replay (模拟回放 106 张实战关键帧)
"""

import sys
import os
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import time
import json
import argparse
import asyncio
from typing import Optional, List, Dict, Any
import cv2
import numpy as np
import mss
import websockets

from vision_pipeline import NTEVisionPipeline
from shape_matcher import ShapeMatcher
from auto_archiver import AutoArchiver
from grid_calibrator import GridCalibrator
from auction_brain import AuctionBrain
from window_tracker import GameWindowTracker
from window_capture import WindowCaptureManager
from runtime_data import initialize_runtime_data

WS_URI = "ws://127.0.0.1:8766"

async def send_hud_update(ws, payload: dict):
    if ws:
        try:
            await ws.send(json.dumps(payload))
        except Exception:
            pass

async def run_replay_mode(pipeline: NTEVisionPipeline, keyframe_dir: str, brain: AuctionBrain, calibrator: GridCalibrator):
    print("🎬 [回放模式] 正在连接本地战术 HUD WebSocket 网关...")
    frames = sorted([f for f in os.listdir(keyframe_dir) if f.startswith("frame_") and f.endswith(".jpg")])
    if not frames:
        print("❌ 未找到关键帧文件！")
        return

    print(f"🎬 [回放模式] 成功加载 {len(frames)} 张实战时间线切片，开始模拟实时对局...")
    
    async with websockets.connect(WS_URI) as ws:
        for idx, fname in enumerate(frames):
            p = os.path.join(keyframe_dir, fname)
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue

            # 1. 运行视觉解析生成 VisionObservation 契约对象
            obs = pipeline.process_frame_observation(img, frame_index=idx + 1)
            grid_res = calibrator.analyze_grid(img)

            # 2. 脑核综合决策与增量情报处理
            hud_payload = brain.process_observation(obs)
            hud_payload["gridCells"] = grid_res.get("flatCells", [0]*250)

            print(f"  [{idx+1}/{len(frames)}] 帧 {fname} -> 回合: {hud_payload['round']} | 估值: {hud_payload['valP50']} | 决策: {hud_payload['actionDirective']}")
            await send_hud_update(ws, hud_payload)
            await asyncio.sleep(0.5)

def _grab_game_or_desktop(sct, tracker: GameWindowTracker, desktop_mon):
    """Legacy entry point; return only client pixels, or no frame."""
    try:
        import win32gui
        from game_frame_capture import capture_tracked_game_frame
        _, img, _, _ = capture_tracked_game_frame(
            tracker, WindowCaptureManager(), sct, win32gui.IsWindow)
        return img
    except Exception:
        return None


async def run_live_capture_mode(pipeline: NTEVisionPipeline, brain: AuctionBrain, calibrator: GridCalibrator):
    print("🎥 [真机模式] 正在启动屏幕捕获引擎...")
    sct = mss.mss()
    mon = sct.monitors[1]
    tracker = GameWindowTracker()

    async with websockets.connect(WS_URI) as ws:
        print("🟢 [真机模式] 已连接 HUD 悬浮窗，开始 10 FPS 实时监控游戏...")
        frame_idx = 0
        while True:
            img = _grab_game_or_desktop(sct, tracker, mon)
            if img is None:
                await asyncio.sleep(0.1)
                continue
            frame_idx += 1

            obs = pipeline.process_frame_observation(img, frame_index=frame_idx)
            grid_res = calibrator.analyze_grid(img)

            hud_payload = brain.process_observation(obs)
            hud_payload["gridCells"] = grid_res.get("flatCells", [0]*250)

            await send_hud_update(ws, hud_payload)
            await asyncio.sleep(0.1)

def main():
    parser = argparse.ArgumentParser(description="异环拍卖视觉捕获驱动")
    parser.add_argument("--replay", action="store_true", help="使用真实录像样本帧进行模拟回放")
    args = parser.parse_args()

    core_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(core_dir, ".."))
    cat_path = os.path.join(project_root, "assets", "catalog_065.json")
    keyframe_dir = os.path.join(project_root, "assets", "replay_frames")

    pipeline = NTEVisionPipeline(catalog_path=cat_path)
    runtime_data = initialize_runtime_data()
    archiver = AutoArchiver(
        db_paths=(
            [str(runtime_data.paths.history_path)]
            if runtime_data.available and runtime_data.paths is not None
            else []
        )
    )
    calibrator = GridCalibrator(catalog_path=cat_path)
    brain = AuctionBrain(archiver=archiver)

    if args.replay:
        asyncio.run(run_replay_mode(pipeline, keyframe_dir, brain, calibrator))
    else:
        asyncio.run(run_live_capture_mode(pipeline, brain, calibrator))

if __name__ == "__main__":
    main()
