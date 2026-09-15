"""
End-to-End Pipeline Verification Test (端到端视觉流水线测试)
自动遍历录像关键帧，验证：
  1. 均价与 Q 值识别
  2. 宝箱与天黑环境识别
  3. 最终结算大屏数据提取
  4. 生成符合 v0.6 格式的推演输入 payload
"""

import os
import sys
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import cv2
import numpy as np
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))
from vision_pipeline import NTEVisionPipeline

def run_tests():
    print("=== 开始运行 0.65 视觉流水线端到端实操测试 ===")
    keyframe_dir = os.path.join(PROJECT_ROOT, "assets", "replay_frames")
    pipeline = NTEVisionPipeline(catalog_path=os.path.join(PROJECT_ROOT, "assets", "catalog_065.json"))

    # 测试 1: 03:00 帧（机械宝箱 + 均价 67571 局）
    p1 = os.path.join(keyframe_dir, "frame_0180s_03m00s.jpg")
    img1 = cv2.imdecode(np.fromfile(p1, dtype=np.uint8), cv2.IMREAD_COLOR)
    ctx1 = pipeline.process_frame(img1)
    
    print("\n[测试 1: 03:00 机械宝箱帧结果]")
    print(f"  - 识别回合: 第 {ctx1['round']} 回合 (倒计时: {ctx1['timer']}s)")
    print(f"  - 金色均价 avg: {ctx1['avg']} (预期: 67571)")
    print(f"  - 宝箱类型: {ctx1.get('box')} (预期: 机械宝箱 · 科技类概率提升)")
    assert ctx1['round'] == 3, f"回合预期 3, 实际: {ctx1['round']}"
    assert ctx1['avg'] == 67571, f"均价预期 67571, 实际: {ctx1['avg']}"
    assert ctx1.get('box') == "机械宝箱 · 科技类概率提升", f"宝箱预期机械宝箱, 实际: {ctx1.get('box')}"
    print("  [PASS] 测试 1 成功通过！")

    # 测试 2: 07:00 帧（琉璃宝箱 + 天黑了 + Q=15 局）
    pipeline2 = NTEVisionPipeline()
    p2 = os.path.join(keyframe_dir, "frame_0420s_07m00s.jpg")
    img2 = cv2.imdecode(np.fromfile(p2, dtype=np.uint8), cv2.IMREAD_COLOR)
    ctx2 = pipeline2.process_frame(img2)
    
    print("\n[测试 2: 07:00 琉璃宝箱+天黑+Q=15 帧结果]")
    print(f"  - 识别回合: 第 {ctx2['round']} 回合 (倒计时: {ctx2['timer']}s)")
    print(f"  - Q 件数: {ctx2['q']} (预期: 15)")
    print(f"  - 总格数: {ctx2['totalGrids']} (预期: 122)")
    print(f"  - 场地词条: {ctx2['fieldCondition']} (预期: dark)")
    print(f"  - 宝箱类型: {ctx2.get('box')} (预期: 琉璃宝箱 · 宝石类概率提升)")
    assert ctx2['round'] == 4, f"回合预期 4, 实际: {ctx2['round']}"
    assert ctx2['q'] == 15, f"Q预期 15, 实际: {ctx2['q']}"
    assert ctx2['totalGrids'] == 122, f"总格数预期 122, 实际: {ctx2['totalGrids']}"
    assert ctx2['fieldCondition'] == "dark", f"词条预期 dark, 实际: {ctx2['fieldCondition']}"
    assert ctx2.get('box') == "琉璃宝箱 · 宝石类概率提升", f"宝箱预期琉璃宝箱, 实际: {ctx2.get('box')}"
    print("  [PASS] 测试 2 成功通过！")

    # 测试 3: 08:00 帧（最终结算大屏）
    pipeline3 = NTEVisionPipeline()
    p3 = os.path.join(keyframe_dir, "frame_0480s_08m00s.jpg")
    img3 = cv2.imdecode(np.fromfile(p3, dtype=np.uint8), cv2.IMREAD_COLOR)
    ctx3 = pipeline3.process_frame(img3)
    
    print("\n[测试 3: 08:00 最终结算大屏账单结果]")
    s = ctx3["settlementData"]
    print(f"  - 判定结算界面: {s['isSettlement']}")
    print(f"  - 最终成交价 Clearing: {s['clearingPrice']} (预期: 454444)")
    print(f"  - 实际总价值 Actual: {s['actualTotal']} (预期: 972970)")
    print(f"  - 实际净收益 Profit: {s['profit']} (预期: 518526)")
    assert s['isSettlement'] == True, "未识别到结算界面"
    assert s['clearingPrice'] == 454444, f"成交价预期 454444, 实际: {s['clearingPrice']}"
    assert s['actualTotal'] == 972970, f"总值预期 972970, 实际: {s['actualTotal']}"
    assert s['profit'] == 518526, f"收益预期 518526, 实际: {s['profit']}"
    print("  [PASS] 测试 3 成功通过！")

    # 输出打包给 v0.6 求解器的 Context
    v06_payload = ctx2
    print("\n[生成的 v0.6 求解器输入 Context Payload (以第2局为例)]:")
    print(json.dumps(pipeline2.to_v06_context(), ensure_ascii=False, indent=2))
    print("\n=======================================================")
    print("🎉 恭喜！0.65 视觉流水线 3 大核心测试全部 100% 验证通过！")
    print("=======================================================")

if __name__ == "__main__":
    run_tests()
