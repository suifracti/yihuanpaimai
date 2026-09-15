const assert = require('assert/strict');
const engine = require('../core/auction_engine_v06.js');
const ctx = {q:27, avg:35280, purpleCount:15, playedAt:'2026-09-08', knownGold:'101554+60285', knownPurple:'5955+3675'};
const normalized = engine.normalizeKnownContext(ctx);
assert.deepEqual(normalized.knownGold.map(x=>x.name), ['赤色来电','澄空之眼']);
assert.equal(normalized.knownGoldRaw, ctx.knownGold);
assert.deepEqual(engine.normalizeKnownContext({...ctx,knownGold:normalized.knownGold}).knownGold,normalized.knownGold);
assert.throws(()=>engine.normalizeKnownContext({knownGold:'赤色来电*3'}));
assert.throws(()=>engine.normalizeKnownContext({knownGold:'不存在的藏品'}));
const constrained = engine.solveExactStatesSync({...normalized,knownGold:normalized.knownGoldRaw,knownPurple:normalized.knownPurpleRaw});
assert.deepEqual(constrained.candidateGs,[6,7,8,9,10,11,12]);
for(const state of constrained.states) {
  assert(state.sampleCombo.includes(101554)); assert(state.sampleCombo.includes(60285));
}
// Compare exact feasibility against exhaustive pairs, including duplicate clues.
const prices = engine.baseCatalogFor({}).gold.map(x=>x[1]);
for(const clue of [4975,60285,101554]) {
  for(const count of [1,2]) {
    for(const other of [4975,60285,101554]) {
      const avg = Math.floor((clue+other)/2);
      const expected = prices.some(a=>prices.some(b=>Math.floor((a+b)/2)===avg && [a,b].filter(x=>x===clue).length>=count));
      const result = engine.solveExactStatesSync({q:2,avg,purpleCount:0,knownGold:`${clue}*${count}`});
      assert.equal(result.states.length>0,expected,`${clue} x ${count}, avg ${avg}`);
    }
  }
}
console.log('manual known expressions, mandatory constraints and exhaustive pair feasibility: passed');
