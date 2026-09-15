"""
PHASE 1 (v0.6 Final) Automated Test Suite
验证：
  1. Expected ROI 严格定义与总支出 ROI / 购入成本 ROI 明确区分
  2. Sunk Cost（已沉没成本）与 Future Incremental Cost（未来新增成本）独立建模
     - Global Profit Line 扣除整局全成本 (sunk + future)
     - Marginal Chase Line 仅扣未来新增成本 (future)，已付沉没成本不再扣减
     - Target Profit Line 独立语义 (支持 targetProfit 与 targetROI)
  3. intelEvent 结构化数据持久化 (before/observed/after 状态与熵变记录)
  4. 15:53 经典对局永久硬约束回归 (G3/P5/R1 与 G4/P5/R0)
  5. 红色重复件数 R=2 硬约束回归
  6. AutoArchiver Schema 6 兼容性与持久化验证
"""

import os
import sys
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import json
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from auto_archiver import AutoArchiver

def test_roi_and_cost_modeling_in_js_engine():
    """验证 JS 引擎中的 ROI 计算、成本拆分与三条出价线语义独立性"""
    node_script = """
    const fs = require('fs');
    const code = fs.readFileSync('core/solver_core_v06.js', 'utf8');
    const window = global;
    window.addEventListener = () => {};
    window.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
    const createMockEl = () => ({
      value: '',
      options: [],
      children: [],
      dataset: {},
      style: {},
      classList: { add: ()=>{}, remove: ()=>{}, toggle: ()=>{}, contains: ()=>false },
      addEventListener: () => {},
      appendChild: () => {},
      closest: () => null
    });
    const document = {
      documentElement: { dataset: {} },
      addEventListener: () => {},
      querySelector: () => createMockEl(),
      getElementById: () => createMockEl(),
      querySelectorAll: () => []
    };
    eval(code);

    // 1. 成本拆分测试
    const ctx1 = {
      costs: { entry: 5000, intel: 45000, other: 0, sunkCost: 50000, futureIncrementalCost: 15000 }
    };
    const costs1 = window.resolveSessionCosts(ctx1);
    if (costs1.sunkCost !== 50000 || costs1.futureIncrementalCost !== 15000 || costs1.allCosts !== 65000) {
      throw new Error(`Cost resolution error: ${JSON.stringify(costs1)}`);
    }

    // 2. 三条线独立计算测试 (ValueP50 = 550,000, sunk=50,000, future=15,000, allCosts=65,000)
    const mockDecision = {
      center: 500000,
      low: 500000,
      probabilityProfile: { shadowWhole: { p20: 500000, p50: 550000, p80: 600000 } },
      shadowCalibrated: { calibrated: { p20: 500000, p50: 550000, p80: 600000 } }
    };
    const linesFixed = window.calculateV06DecisionLines(ctx1, mockDecision, 400000);
    
    // RecommendedMax (GlobalLine): 550,000 - 65,000 = 485,000
    if (linesFixed.recommendedMax !== 485000 || linesFixed.globalLine !== 485000) {
      throw new Error(`RecommendedMax mismatch: expected 485000, got ${linesFixed.recommendedMax}`);
    }
    // ChaseLimit (MarginalLine): 550,000 - 15,000 = 535,000 (仅扣未来新增成本，不重复扣 50,000 沉没成本)
    if (linesFixed.chaseLimit !== 535000 || linesFixed.marginalLine !== 535000) {
      throw new Error(`ChaseLimit mismatch: expected 535000, got ${linesFixed.chaseLimit}`);
    }
    // SafeBuy (TargetLine): floor(550,000 / 1.20 - 65,000) = 458,333 - 65,000 = 393,333
    if (linesFixed.safeBuy !== 393333 || linesFixed.targetLine !== 393333) {
      throw new Error(`SafeBuy mismatch: expected 393333, got ${linesFixed.safeBuy}`);
    }

    // 3. ROI on live bid 400,000 (ExpectedValue = 550,000, TotalSpend = 400k + 65k = 465k, NetProfit = 85k)
    // ROI on Total Spend: 85,000 / 465,000 = 18.2795%
    // ROI on Purchase: 85,000 / 400,000 = 21.25%
    const diffTotal = Math.abs(linesFixed.roiOnTotalSpend - (85000 / 465000));
    const diffPurchase = Math.abs(linesFixed.roiOnPurchase - (85000 / 400000));
    if (diffTotal > 1e-4 || diffPurchase > 1e-4) {
      throw new Error(`ROI mismatch: total=${linesFixed.roiOnTotalSpend}, purchase=${linesFixed.roiOnPurchase}`);
    }

    // 4. Target ROI 测试 (设置 targetROI = 0.25 即 25%)
    const ctxROI = { ...ctx1, targetROI: 0.25 };
    const linesROI = window.calculateV06DecisionLines(ctxROI, mockDecision);
    // targetLine = floor(550000 / 1.25 - 65000) = 440000 - 65000 = 375000
    if (linesROI.safeBuy !== 375000 || linesROI.targetLine !== 375000) {
      throw new Error(`Target ROI line mismatch: expected 375000, got ${linesROI.safeBuy}`);
    }

    // 5. 熵与 Shadow 宽度计算测试
    const mockStates = [{ weight: 1 }, { weight: 1 }, { weight: 1 }, { weight: 1 }];
    const entropy = window.calculateStateEntropy(mockStates);
    if (Math.abs(entropy - 2.0) > 0.01) {
      throw new Error(`Entropy calculation mismatch: expected 2.0, got ${entropy}`);
    }
    const shadowWidth = window.calculateShadowWidth(mockDecision);
    if (shadowWidth !== 100000) {
      throw new Error(`Shadow width mismatch: expected 100000, got ${shadowWidth}`);
    }

    // 6. intelEvent 创建测试
    const ev = window.createIntelEventRecord({
      round: 2,
      toolType: 'goldAvg',
      before: { candidateStateCount: 16, stateEntropy: 2.5, shadowWidth: 150000, decisionClass: 'worth-entering' },
      observed: { field: 'avg', value: 33538 },
      after: { candidateStateCount: 2, stateEntropy: 0.69, shadowWidth: 42000, decisionClass: 'worth-entering' },
      incrementalCost: 15000
    });
    if (ev.round !== 2 || ev.toolType !== 'goldAvg' || ev.incrementalCost !== 15000 || ev.decisionChanged !== false) {
      throw new Error(`intelEvent format error: ${JSON.stringify(ev)}`);
    }

    console.log('JS_ENGINE_TESTS_PASS');
    """

    res = subprocess.run(["node", "-e", node_script], cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"Node tests failed: {res.stderr}"
    assert "JS_ENGINE_TESTS_PASS" in res.stdout

def test_v06_reliability_self_tests_in_core():
    """运行 core/solver_core_v06.js 内置的 15:53、红重复等全套可靠性测试"""
    node_script = """
    const fs = require('fs');
    const code = fs.readFileSync('core/solver_core_v06.js', 'utf8');
    const window = global;
    window.addEventListener = () => {};
    window.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
    const createMockEl = () => ({
      value: '',
      options: [],
      children: [],
      dataset: {},
      style: {},
      classList: { add: ()=>{}, remove: ()=>{}, toggle: ()=>{}, contains: ()=>false },
      addEventListener: () => {},
      appendChild: () => {},
      closest: () => null,
      reset: () => {}
    });
    const document = {
      documentElement: { dataset: {} },
      addEventListener: () => {},
      querySelector: () => createMockEl(),
      getElementById: () => createMockEl(),
      querySelectorAll: () => []
    };
    eval(code);

    const res = window.runV06ReliabilitySelfTests();
    console.log('RESULT_JSON:' + JSON.stringify(res));
    if (!res.passed) {
      process.exit(1);
    }
    """
    res = subprocess.run(["node", "-e", node_script], cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"V06 reliability self tests failed: {res.stderr}"
    json_line = [line for line in res.stdout.splitlines() if line.startswith("RESULT_JSON:")][0]
    data = json.loads(json_line.replace("RESULT_JSON:", "", 1))
    assert data.get("passed") is True
    # 确认 15:53 关键测试存在且通过
    names = {t["name"]: t["passed"] for t in data.get("tests", [])}
    assert names.get("15:53-regression-not-no-match") is True
    assert names.get("15:53-regression-required-states") is True
    assert names.get("red-repeat-two-regression") is True

def test_auto_archiver_schema6_persistence():
    """验证 AutoArchiver 生成 Schema 6 标准对局记录 (包含 intelEvents 和 structured costs)"""
    archiver = AutoArchiver(db_paths=[])
    
    mock_ctx = {
        "venue": "shanhu",
        "boxType": "glass",
        "fieldCondition": "dark",
        "q": 15,
        "avg": 67571,
        "costs": {
            "entry": 5000,
            "intel": 45000,
            "sunkCost": 50000,
            "futureIncrementalCost": 0
        },
        "intelEvents": [
            {
                "round": 1,
                "toolType": "boxType",
                "timestamp": "2026-08-14T23:25:00.000Z",
                "before": {"candidateStateCount": 30, "stateEntropy": 3.2, "shadowWidth": 200000, "decisionClass": "unknown"},
                "observed": {"boxType": "glass"},
                "after": {"candidateStateCount": 18, "stateEntropy": 2.4, "shadowWidth": 150000, "decisionClass": "worth-entering"},
                "decisionChanged": True,
                "incrementalCost": 0
            }
        ],
        "box": "琉璃宝箱 · 宝石类概率提升",
        "settlementReady": True,
        "settlementData": {
            "isSettlement": True,
            "clearingPrice": 454444,
            "actualTotal": 972970,
            "profit": 518526
        }
    }
    
    # 内存归档提取
    record = archiver.archive_match(mock_ctx)
    assert record is not None
    assert record["productVersion"] == "v0.67-alpha"
    assert record["settlement"]["clearingPrice"] == 454444
    assert record["settlement"]["actualTotal"] == 972970
    assert record["settlement"]["realizedProfit"] == 518526
    assert record["costs"]["sunkCost"] == 50000
    assert record["costs"]["total"] == 50000

class TestV06Final(unittest.TestCase):
    def test_roi_and_cost_modeling_in_js_engine(self):
        test_roi_and_cost_modeling_in_js_engine()

    def test_v06_reliability_self_tests_in_core(self):
        test_v06_reliability_self_tests_in_core()

    def test_auto_archiver_schema6_persistence(self):
        test_auto_archiver_schema6_persistence()

if __name__ == "__main__":
    unittest.main()
