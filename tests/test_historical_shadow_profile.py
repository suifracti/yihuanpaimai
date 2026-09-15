# -*- coding: utf-8 -*-
"""Phase 0: Historical Shadow lives in one Shared Core and keeps old semantics."""
import json
import os
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "异环拍卖数据.json")
FIXTURE_PATH = os.path.join(PROJECT_ROOT, "tests", "fixtures", "shadow_1415_legacy.json")


def run_js(script: str, timeout=120):
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "") + "\n" + (proc.stdout or ""))
    text = proc.stdout
    start = text.find("{")
    if start < 0:
        raise RuntimeError("no JSON in stdout:\n" + text)
    return json.loads(text[start:])


BOOT = r"""
const fs = require('fs');
const path = require('path');
const engine = require('./core/auction_engine_v06.js');
const shared = require('./core/shadow_profile_v06.js');

function mockDom() {
  const el = () => ({
    value: '', options: [], children: [], dataset: {}, style: {},
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, appendChild(){}, closest(){ return null; }, reset(){}
  });
  global.window = global;
  global.addEventListener = () => {};
  global.localStorage = { getItem: () => null, setItem(){}, removeItem(){} };
  global.document = {
    documentElement: { dataset: {} },
    addEventListener(){},
    querySelector(){ return el(); },
    getElementById(){ return el(); },
    querySelectorAll(){ return []; }
  };
}

function loadSolverLegacy() {
  mockDom();
  let code = fs.readFileSync('./core/solver_core_v06.js', 'utf8');
  // Keep the original inlined algorithm for A/B; do not take the shared-core bridge.
  code = code.replace('if (shared) {', 'if (false && shared) {');
  code = code.replace('let state = loadState();', 'let state = loadState(); window.state = state;');
  code = code
    .replace('function redProbabilityProfile(ctx,states=[],componentRows=[]){',
             'window.redProbabilityProfile=function redProbabilityProfile(ctx,states=[],componentRows=[]){')
    .replace('function stateComponents(ctx,state){',
             'window.stateComponents=function stateComponents(ctx,state){')
    .replace('function candidateStateWeight(state,ctx={}){',
             'window.candidateStateWeight=function candidateStateWeight(state,ctx={}){')
    .replace('function expandStatesForValuation(ctx, states){',
             'window.expandStatesForValuation=function expandStatesForValuation(ctx, states){')
    .replace('function historicalRedLabel(r){',
             'window.historicalRedLabel=function historicalRedLabel(r){');
  eval(code);
  return {
    redProbabilityProfile: global.redProbabilityProfile,
    stateComponents: global.stateComponents,
    candidateStateWeight: global.candidateStateWeight,
    expandStatesForValuation: global.expandStatesForValuation,
    historicalRedLabel: global.historicalRedLabel,
    getState: () => global.state
  };
}

function slim(profile) {
  return {
    supportedStateCount: profile.supportedStateCount,
    totalStateCount: profile.totalStateCount,
    supportedWeight: profile.supportedWeight,
    totalWeight: profile.totalWeight,
    coverageRatio: profile.coverageRatio,
    isFullShadow: Boolean(profile.shadowCoverage && profile.shadowCoverage.isFull),
    shadowWhole: profile.shadowWhole ? {
      p20: profile.shadowWhole.p20, p50: profile.shadowWhole.p50, p80: profile.shadowWhole.p80
    } : null,
    partialShadowP20: profile.partialShadowP20,
    partialShadowP50: profile.partialShadowP50,
    partialShadowP80: profile.partialShadowP80,
    source: profile.source,
    status: profile.status,
    states: (profile.stateCandidates || []).map(s => ({
      g: s.g, p: s.p, r: s.r,
      weight: s.weight,
      relativeWeight: s.relativeWeight,
      supported: Boolean(s.shadow && Number.isFinite(Number(s.shadow.p50))),
      redMode: s.redMode || null,
      shadowP20: s.shadow ? s.shadow.p20 : null,
      shadowP50: s.shadow ? s.shadow.p50 : null,
      shadowP80: s.shadow ? s.shadow.p80 : null
    }))
  };
}

const CTX_1415 = {
  playedAt: '2026-08-17T14:15:59.030277',
  venue: '中级场 · 珊瑚场',
  box: '琉璃宝箱 · 宝石类概率提升',
  fieldCondition: 'standard',
  q: 12, avg: 74379, goldAvg: 74379, purple: 7, purpleCount: 7,
  costs: {entry:5000,intel:0,other:0,sunkCost:5000,futureIncrementalCost:0,total:5000},
  knownGold: [], knownPurple: [], knownRed: [], publicInfo: {}, roundingMode: 'floor'
};

function states1415() {
  const exact = engine.solveExactStatesSync({q:12, avg:74379, p:7, purple:7});
  return (exact.states || []).map(s => ({
    g: s.G, p: s.P, r: s.R, G: s.G, P: s.P, R: s.R,
    gold: {unconstrained:true, matches:[]},
    purple: {unconstrained:true, matches:[]}
  }));
}
"""


class TestHistoricalShadowProfile(unittest.TestCase):
    def test_shared_is_the_only_live_source_in_lab_and_solver(self):
        with open(os.path.join(PROJECT_ROOT, "lab", "index.html"), encoding="utf-8") as fh:
            lab = fh.read()
        with open(os.path.join(PROJECT_ROOT, "core", "solver_core_v06.js"), encoding="utf-8") as fh:
            core = fh.read()
        self.assertIn("shadow_profile_v06.js", lab)
        self.assertIn("buildProbabilityProfile", lab)
        self.assertIn("buildProbabilityProfile", core)
        wrap = core[core.find("function redProbabilityProfile"):core.find("function redProbabilityProfile") + 700]
        self.assertIn("state.records", wrap)
        self.assertIn("if (shared)", wrap)

    def test_red_inventory_complete_filter(self):
        res = run_js(
            BOOT
            + r"""
            const incomplete = {
              id: 'inc', redInventoryComplete: false, redCount: 1,
              settlementVerifiedRedItems: '「泪滴」 50000',
              settlement: {redInventoryComplete: false, redCount: 1, verifiedRedItems: '「泪滴」 50000'}
            };
            const complete = {
              id: 'ok', redInventoryComplete: true, redCount: 1,
              settlementVerifiedRedItems: '「泪滴」 50000',
              settlement: {status:'verified', redInventoryComplete: true, redCount: 1, verifiedRedItems: '「泪滴」 50000'}
            };
            console.log(JSON.stringify({
              incomplete: shared.historicalRedLabel(incomplete),
              complete: shared.historicalRedLabel(complete)
            }));
            """
        )
        self.assertIsNone(res["incomplete"])
        self.assertEqual(res["complete"]["count"], 1)
        self.assertEqual(res["complete"]["total"], 50000)

    def test_zero_coverage_has_no_official_shadow(self):
        res = run_js(
            BOOT
            + r"""
            const states = [{g:4,p:7,r:1,gold:{unconstrained:true,matches:[]},purple:{unconstrained:true,matches:[]}}];
            const profile = shared.buildProbabilityProfile(
              {...CTX_1415, playedAt: '2099-01-01T00:00:00'},
              states,
              {records: [], componentRows: []}
            );
            const lines = engine.calculateV06DecisionLines(
              {costs:{entry:5000}},
              {solverStatus:'valid', states, probabilityProfile: profile, formalValue:{ev:334707,theoreticalMin:297517,theoreticalMax:371898}}
            );
            console.log(JSON.stringify({
              coverageRatio: profile.coverageRatio,
              isFullShadow: Boolean(profile.shadowCoverage && profile.shadowCoverage.isFull),
              shadowWhole: profile.shadowWhole,
              partialShadowP50: profile.partialShadowP50,
              supportedStateCount: profile.supportedStateCount,
              totalStateCount: profile.totalStateCount,
              mode: lines.degradationLevel,
              valueP50: lines.valueP50
            }));
            """
        )
        self.assertEqual(res["coverageRatio"], 0)
        self.assertFalse(res["isFullShadow"])
        self.assertIsNone(res["shadowWhole"])
        self.assertIsNone(res["partialShadowP50"])
        self.assertEqual(res["supportedStateCount"], 0)
        self.assertEqual(res["mode"], "structural_only")
        self.assertIsNone(res["valueP50"])

    def test_full_coverage_emits_shadow_whole(self):
        res = run_js(
            BOOT
            + r"""
            const states = [{g:5,p:7,r:0,gold:{unconstrained:true,matches:[]},purple:{unconstrained:true,matches:[]}}];
            const componentRows = [{
              state: states[0],
              component: {gold:{mid:371895}, purple:{mid:48773.9}, lowTier:{mid:12000}},
              weight: 1
            }];
            const profile = shared.buildProbabilityProfile(
              {...CTX_1415, playedAt: '2099-01-01T00:00:00'},
              states,
              {records: [], componentRows}
            );
            const lines = engine.calculateV06DecisionLines(
              {costs:{entry:5000}},
              {solverStatus:'valid', states, probabilityProfile: profile, formalValue:{ev:432668.9}}
            );
            console.log(JSON.stringify({
              coverageRatio: profile.coverageRatio,
              isFullShadow: Boolean(profile.shadowCoverage && profile.shadowCoverage.isFull),
              shadowWhole: profile.shadowWhole && {p20:profile.shadowWhole.p20,p50:profile.shadowWhole.p50,p80:profile.shadowWhole.p80},
              partialShadowP50: profile.partialShadowP50,
              supportedStateCount: profile.supportedStateCount,
              totalStateCount: profile.totalStateCount,
              mode: lines.degradationLevel,
              valueP50: lines.valueP50
            }));
            """
        )
        self.assertGreaterEqual(res["coverageRatio"], 0.999999)
        self.assertTrue(res["isFullShadow"])
        self.assertIsNotNone(res["shadowWhole"])
        self.assertAlmostEqual(res["shadowWhole"]["p50"], 432668.9, places=4)
        self.assertEqual(res["supportedStateCount"], 1)
        self.assertEqual(res["totalStateCount"], 1)
        self.assertEqual(res["mode"], "full_shadow")
        self.assertAlmostEqual(res["valueP50"], 432668.9, places=4)

    def test_partial_fixture_keeps_only_conditional_quantiles(self):
        res = run_js(
            BOOT
            + r"""
            const states = [
              {g:4,p:7,r:1,gold:{unconstrained:true,matches:[]},purple:{unconstrained:true,matches:[]}},
              {g:5,p:7,r:0,gold:{unconstrained:true,matches:[]},purple:{unconstrained:true,matches:[]}}
            ];
            const componentRows = [
              {state: states[0], component: {gold:{mid:297516}, purple:{mid:48773.9}, lowTier:{mid:12000}}, weight: 1},
              {state: states[1], component: {gold:{mid:371895}, purple:{mid:48773.9}, lowTier:{mid:12000}}, weight: 1}
            ];
            const profile = shared.buildProbabilityProfile(
              {...CTX_1415, playedAt: '2099-01-01T00:00:00'},
              states,
              {records: [], componentRows}
            );
            const lines = engine.calculateV06DecisionLines(
              {costs:{entry:5000}},
              {solverStatus:'valid', states, probabilityProfile: profile, formalValue:{ev:334707}}
            );
            console.log(JSON.stringify({
              coverageRatio: profile.coverageRatio,
              isFullShadow: Boolean(profile.shadowCoverage && profile.shadowCoverage.isFull),
              shadowWhole: profile.shadowWhole,
              partialShadowP50: profile.partialShadowP50,
              supportedStateCount: profile.supportedStateCount,
              totalStateCount: profile.totalStateCount,
              mode: lines.degradationLevel,
              valueP50: lines.valueP50
            }));
            """
        )
        self.assertGreater(res["coverageRatio"], 0)
        self.assertLess(res["coverageRatio"], 0.999999)
        self.assertFalse(res["isFullShadow"])
        self.assertIsNone(res["shadowWhole"])
        self.assertIsNotNone(res["partialShadowP50"])
        self.assertEqual(res["supportedStateCount"], 1)
        self.assertEqual(res["totalStateCount"], 2)
        self.assertEqual(res["mode"], "partial_shadow")
        self.assertIsNone(res["valueP50"])

    def test_real_1415_dry_run_and_old_new_parity(self):
        if not os.path.exists(DB_PATH):
            self.skipTest("异环拍卖数据.json missing")
        with open(FIXTURE_PATH, encoding="utf-8") as fh:
            fixture = json.load(fh)
        res = run_js(
            BOOT
            + r"""
            const db = JSON.parse(fs.readFileSync('./异环拍卖数据.json','utf8'));
            const recs = db.records || [];
            const solver = loadSolverLegacy();
            if (solver.getState()) solver.getState().records = recs;
            const expanded = solver.expandStatesForValuation(CTX_1415, states1415());
            const componentRows = expanded.map(state => {
              const component = solver.stateComponents(CTX_1415, state);
              return component ? {state, component, weight: solver.candidateStateWeight(state, CTX_1415)} : null;
            }).filter(Boolean);
            const oldProfile = solver.redProbabilityProfile(CTX_1415, expanded, componentRows);
            const newProfile = shared.buildProbabilityProfile(CTX_1415, expanded, {
              records: recs,
              componentRows,
              stateComponentsFn: solver.stateComponents
            });
            const lines = engine.calculateV06DecisionLines(
              {costs: CTX_1415.costs},
              {solverStatus:'valid', states: expanded, probabilityProfile: newProfile, formalValue:{ev:334707,theoreticalMin:297517,theoreticalMax:371898}}
            );
            console.log(JSON.stringify({
              nRecords: recs.length,
              exact: states1415().map(s => ({G:s.g,P:s.p,R:s.r})),
              expanded: expanded.map(s => ({G:s.g,P:s.p,R:s.r})),
              old: slim(oldProfile),
              neu: slim(newProfile),
              mode: lines.degradationLevel,
              valueP50: lines.valueP50,
              labBridge: String(solver.redProbabilityProfile).includes('buildProbabilityProfile')
            }));
            """,
            timeout=180,
        )
        self.assertGreaterEqual(res["nRecords"], 178)
        self.assertEqual(res["exact"], fixture["exactStates"])
        self.assertEqual(res["expanded"], fixture["expandedStates"])
        self.assertAlmostEqual(res["neu"]["coverageRatio"], fixture["coverageRatio"], places=10)
        self.assertEqual(res["neu"]["supportedStateCount"], fixture["supportedStateCount"])
        self.assertEqual(res["neu"]["totalStateCount"], fixture["totalStateCount"])
        self.assertTrue(res["neu"]["isFullShadow"])
        self.assertIsNotNone(res["neu"]["shadowWhole"])
        self.assertAlmostEqual(res["neu"]["shadowWhole"]["p20"], fixture["shadowWhole"]["p20"], places=4)
        self.assertAlmostEqual(res["neu"]["shadowWhole"]["p50"], fixture["shadowWhole"]["p50"], places=4)
        self.assertAlmostEqual(res["neu"]["shadowWhole"]["p80"], fixture["shadowWhole"]["p80"], places=4)
        self.assertAlmostEqual(res["neu"]["partialShadowP20"], fixture["partialShadowP20"], places=4)
        self.assertAlmostEqual(res["neu"]["partialShadowP50"], fixture["partialShadowP50"], places=4)
        self.assertAlmostEqual(res["neu"]["partialShadowP80"], fixture["partialShadowP80"], places=4)
        self.assertEqual(res["mode"], "full_shadow")
        self.assertAlmostEqual(res["valueP50"], fixture["shadowWhole"]["p50"], places=4)
        self.assertEqual(res["old"], res["neu"])
        # loadSolverLegacy hid shared; the Lab/solver source itself still has the bridge.
        with open(os.path.join(PROJECT_ROOT, "lab", "index.html"), encoding="utf-8") as fh:
            lab = fh.read()
        self.assertIn("AuctionEngineV06.buildProbabilityProfile", lab)


if __name__ == "__main__":
    unittest.main()
