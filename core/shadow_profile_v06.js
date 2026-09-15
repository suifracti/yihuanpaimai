/**
 * Shared Historical Shadow Probability Profile (v0.6).
 *
 * Pure extraction of solver_core_v06.js redProbabilityProfile.
 * History must be injected via records. No DOM / localStorage / File Picker.
 */
(function (global, factory) {
  const api = factory(global);
  if (typeof exports === "object" && typeof module !== "undefined") {
    module.exports = api;
  }
  if (typeof globalThis !== "undefined") {
    globalThis.ShadowProfileV06 = api;
    if (globalThis.AuctionEngineV06) Object.assign(globalThis.AuctionEngineV06, api);
  }
  if (typeof window !== "undefined") {
    window.ShadowProfileV06 = api;
    if (window.AuctionEngineV06) Object.assign(window.AuctionEngineV06, api);
  }
}(typeof globalThis !== "undefined" ? globalThis : (typeof self !== "undefined" ? self : this), function (global) {
  "use strict";

  const engine = (global && global.AuctionEngineV06) || (typeof AuctionEngineV06 !== "undefined" ? AuctionEngineV06 : null) || (typeof require === "function" ? require("./auction_engine_v06.js") : null);
  if (!engine) {
    throw new Error("shadow_profile_v06.js requires auction_engine_v06.js to be loaded first");
  }

  const catalogVersionFor = engine.catalogVersionFor;
  const conditionRules = engine.conditionRules;
  const baseCatalogFor = engine.baseCatalogFor;
  const RED_ITEMS = engine.RED_ITEMS;
  const historyTimestamp = engine.historyTimestamp;
  const quantile = engine.quantile;
  const mean = engine.mean;
  const weightedQuantile = engine.weightedQuantile;
  const nonNegativeOrNull = engine.nonNegativeOrNull;

    function periodOf(value){return typeof value==="string"&&/^\d{4}-\d{2}/.test(value)?value.slice(0,7):"";}

    function explicitBoolean(value){return value===true||value==="true"?true:value===false||value==="false"?false:null;}

    function integerOrNull(value){const n=nonNegativeOrNull(value);return Number.isInteger(n)?n:null;}

    function hasNumber(value){return value!==null&&value!==undefined&&value!==""&&Number.isFinite(Number(value));}

    function boxIsUnknown(box){return !box||String(box).startsWith("未知");}

    function median(values) { if(!values.length)return null; const s=[...values].sort((a,b)=>a-b), m=Math.floor(s.length/2); return s.length%2?s[m]:(s[m-1]+s[m])/2; }

    function weightedStats(entries){
      const rows=(entries||[]).filter(x=>Number.isFinite(Number(x.value))&&Number(x.weight)>0).map(x=>({value:Number(x.value),weight:Number(x.weight)}));
      if(!rows.length)return null;
      // Avoid spreading a large bootstrap/state mixture into Math.min/max;
      // low-information progressive inference may legitimately produce many
      // candidate samples and should remain computable without stack overflow.
      let min=Infinity,max=-Infinity;for(const row of rows){if(row.value<min)min=row.value;if(row.value>max)max=row.value;}
      return {n:rows.length,p05:weightedQuantile(rows,.05),p10:weightedQuantile(rows,.10),p20:weightedQuantile(rows,.20),p25:weightedQuantile(rows,.25),p50:weightedQuantile(rows,.50),p75:weightedQuantile(rows,.75),p80:weightedQuantile(rows,.80),p90:weightedQuantile(rows,.90),p95:weightedQuantile(rows,.95),min,max,weight:rows.reduce((s,x)=>s+x.weight,0)};
    }

    function redValueTier(value){
      const v=Number(value);
      if(!Number.isFinite(v))return "未知";
      if(v<100000)return "普通红";
      if(v<500000)return "中高红";
      if(v<2000000)return "高尾红";
      return "Jackpot";
    }

    function redTierRange(tier){
      return ({"普通红":"<10W","中高红":"10–50W","高尾红":"50–200W",Jackpot:"≥200W"})[tier]||"未知";
    }

    function parseHistoricalRedItems(raw){
      const text=String(raw||"").trim();if(!text)return [];
      const out=[];
      for(const token of text.split(/[+,，、；;\n]/).map(x=>x.trim()).filter(Boolean)){
        const mult=Math.max(1,Number((token.match(/[*×x]\s*(\d+)/i)||[])[1])||1);
        const named=RED_ITEMS.find(item=>token.includes(item[0]));
        const numeric=(token.match(/\d[\d,]{3,}/g)||[]).map(x=>Number(x.replaceAll(",",""))).find(x=>RED_ITEMS.some(item=>item[1]===x));
        const item=named||(numeric?RED_ITEMS.find(x=>x[1]===numeric):null);
        if(item)for(let i=0;i<mult;i++)out.push({name:item[0],price:item[1]});
      }
      return out;
    }

    function verifiedRedItemsText(r){return String(r?.settlementVerifiedRedItems??r?.settlement?.verifiedRedItems??"").trim();}

    function historicalRedLabel(r){
      if(!r||explicitBoolean(r.redInventoryComplete??r.settlement?.redInventoryComplete)!==true)return null;
      // 迁移后的保守真值允许完整红清单与显式顶层 redCount 配对；
      // 这只建立红货标签，不会据此反推 realized G/P/R。
      const count=integerOrNull(r.settlement?.redCount??r.settlement?.realizedState?.red??r.redCount),raw=verifiedRedItemsText(r);
      if(count===null||/[\/／]/.test(raw))return null;
      if(count===0)return raw?null:{count:0,total:0,known:true,complete:true,items:[],source:r.settlement?.truthSource||"unknown",confidence:r.settlement?.truthConfidence||"unknown"};
      const items=parseHistoricalRedItems(raw);
      if(items.length!==count)return null;
      return {count,total:items.reduce((a,b)=>a+b.price,0),known:true,complete:true,items,source:r.settlement?.truthSource||"unknown",confidence:r.settlement?.truthConfidence||"unknown"};
    }

    function similarityFor(ctx,r){
      let score=8;const reasons=[],pi=ctx.publicInfo||{};
      if(ctx.venue&&ctx.venue!=="未知场地"){if(r.venue===ctx.venue){score+=36;reasons.push("同场地");}else score-=42;}
      if(ctx.box&&!ctx.box.startsWith("未知")){if(r.box===ctx.box){score+=30;reasons.push("同箱型");}else if(r.venue===ctx.venue)score-=4;}
      const period=ctx.periodKey||periodOf(ctx.playedAt);if(period&&(r.periodKey||periodOf(r.playedAt)||r.patch)===period){score+=4;reasons.push("同月份");}
      const numericNear=(a,b,exact,maxBonus,step,label)=>{if(!hasNumber(a)||!hasNumber(b))return;const diff=Math.abs(Number(a)-Number(b));score+=diff===0?exact:Math.max(-maxBonus*.4,maxBonus-diff*step);if(diff===0)reasons.push(label);else if(diff<=2)reasons.push(label+"近");};
      numericNear(ctx.q,r.q,24,18,3.5,"Q");numericNear(ctx.purple,r.purpleCount,14,11,2.8,"紫数");numericNear(ctx.goldCount,r.goldCount,11,9,2.8,"金数");numericNear(ctx.redCount,r.redCount,11,9,3.5,"红数");
      const avgNear=(a,b,bonus,label)=>{if(!hasNumber(a)||!hasNumber(b)||Number(a)<=0||Number(b)<=0)return;const rel=Math.abs(Math.log(Number(a)/Number(b)));score+=bonus*Math.max(-.3,1-rel/.7);if(rel<.1)reasons.push(label+"接近");};
      avgNear(ctx.avg,r.goldAvg,18,"金均");avgNear(ctx.purpleAvg,r.purpleAvg,10,"紫均");avgNear(ctx.goldTotal,r.goldTotal,20,"金总");
      avgNear(pi.blueAvg,r.blueAvg,4,"蓝均");avgNear(pi.greenAvg,r.greenAvg,3,"绿均");avgNear(pi.whiteAvg,r.whiteAvg,2,"白均");
      for(const key of ["totalItems","totalGrid","goldGrid","purpleGrid","blueCount","blueGrid","greenCount","greenGrid","whiteCount","whiteGrid"]){const a=pi[key]??ctx[key],b=r[key];if(hasNumber(a)&&hasNumber(b)){const diff=Math.abs(Number(a)-Number(b));score+=Math.max(-2.5,6-diff*1.1);if(diff===0)reasons.push(key.replace("totalItems","总件").replace("totalGrid","总格").replace("Grid","格").replace("Count","数"));}}
      if(r.legacy)score-=10;const similarity=Math.max(0,Math.min(99,Math.round(score)));return {score,similarity,reasons:[...new Set(reasons)].slice(0,5)};
    }

    function historyCompatible(ctx={},record={},purpose="wholeValue"){
      const currentCondition=conditionRules(ctx),pastCondition=conditionRules(record),currentCatalog=catalogVersionFor(ctx),pastCatalog=catalogVersionFor(record),sameCatalog=currentCatalog!=="unknown"&&pastCatalog!=="unknown"&&currentCatalog===pastCatalog;
      if(currentCondition.id==="unknown"||pastCondition.id==="unknown")return currentCondition.id===pastCondition.id&&(purpose==="state"||currentCatalog===pastCatalog);
      if(purpose==="state")return currentCondition.id==="sparkle"?pastCondition.id==="sparkle":pastCondition.id!=="sparkle";
      if(purpose==="redDistribution")return sameCatalog&&(currentCondition.id==="sparkle"?pastCondition.id==="sparkle":pastCondition.id!=="sparkle");
      if(purpose==="bidBehavior")return sameCatalog&&currentCondition.id===pastCondition.id;
      if(purpose==="cashflow")return sameCatalog&&((currentCondition.id==="welfare")===(pastCondition.id==="welfare"));
      return sameCatalog&&currentCondition.historyGroup===pastCondition.historyGroup;
    }

    function eligibleHistory(records,ctx={},purpose="wholeValue"){
      const cutoff=historyTimestamp(ctx.playedAt),excludeId=ctx.excludeRecordId||ctx.id||null;
      return (Array.isArray(records)?records:[]).filter(r=>{
        if(excludeId&&r.id===excludeId)return false;
        if(Array.isArray(ctx.allowedHistoryIds)&&!ctx.allowedHistoryIds.includes(r.id))return false;
        if(r.diagnosticOnly===true||r.rounds?.some(x=>x?.diagnosticOnly===true))return false;
        if(r.settlement?.status==="pending")return false;
        const actual=Number(r.actualTotal);if(!Number.isFinite(actual)||actual<=0)return false;
        if(!historyCompatible(ctx,r,purpose))return false;
        if(cutoff===null)return true;
        const rt=historyTimestamp(r.playedAt||r.date);
        // 严格时序：无法证明发生在本局之前的无日期旧样本，不参加预测/回测。
        return rt!==null&&rt<cutoff;
      });
    }

    function similarHistory(records,ctx,limit=8,purpose="wholeValue"){
      return eligibleHistory(records,ctx,purpose).map(r=>({record:r,...similarityFor(ctx,r)})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score||(historyTimestamp(b.record.playedAt)||0)-(historyTimestamp(a.record.playedAt)||0)).slice(0,limit).map(x=>({...x,weight:Math.max(.01,(x.similarity/100)**2.4)}));
    }

    function derivedRecordCounts(r){
      let g=hasNumber(r.goldCount)&&Number.isInteger(Number(r.goldCount))?Number(r.goldCount):null,p=hasNumber(r.purpleCount)&&Number.isInteger(Number(r.purpleCount))?Number(r.purpleCount):null,red=hasNumber(r.redCount)&&Number.isInteger(Number(r.redCount))?Number(r.redCount):null,q=hasNumber(r.q)&&Number.isInteger(Number(r.q))?Number(r.q):null;
      if(q!==null){if(g===null&&p!==null&&red!==null)g=q-p-red;if(p===null&&g!==null&&red!==null)p=q-g-red;if(red===null&&g!==null&&p!==null)red=q-g-p;}return {g,p,red};
    }

    function historicalCountPrior(records,ctx){
      if(ctx._historyCountPrior)return ctx._historyCountPrior;
      const q=hasNumber(ctx.q)?Number(ctx.q):null,rows=eligibleHistory(records,ctx,"state").filter(r=>r.venue===ctx.venue&&(boxIsUnknown(ctx.box)?!boxIsUnknown(r.box):r.box===ctx.box)&&(q===null||!hasNumber(r.q)||Math.abs(Number(r.q)-q)<=2)).map(r=>derivedRecordCounts(r)).filter(x=>Number.isInteger(x.g));
      const prior={n:rows.length,g:rows.length?median(rows.map(x=>x.g)):null};
      try{Object.defineProperty(ctx,"_historyCountPrior",{value:prior,configurable:true});}catch(_){ctx._historyCountPrior=prior;}
      return prior;
    }

    function valueStats(values){
      const v=values.map(Number).filter(x=>Number.isFinite(x)&&x>=0);
      return v.length?{n:v.length,p20:quantile(v,.2),p25:quantile(v,.25),p35:quantile(v,.35),p50:quantile(v,.5),p75:quantile(v,.75),p80:quantile(v,.8),mean:mean(v)}:null;
    }

    function historyBoxValue(records,ctx){
      const rows=eligibleHistory(records,ctx);
      if(!boxIsUnknown(ctx.box))return valueStats(rows.filter(r=>r.box===ctx.box).map(r=>r.actualTotal));
      // “未知箱型”不是一种真实箱型，而是同场地已知箱型的潜在混合。
      const q=hasNumber(ctx.q)?Number(ctx.q):null,mixed=rows.filter(r=>r.venue===ctx.venue&&!boxIsUnknown(r.box)&&(q===null||!hasNumber(r.q)||Math.abs(Number(r.q)-q)<=3));
      return valueStats(mixed.map(r=>r.actualTotal));
    }

    function maxPlausibleGoldCount(records,ctx){
      const q=hasNumber(ctx.q)?Number(ctx.q):null;
      const avg=Number(ctx.avg);
      if(hasNumber(ctx.goldCount)) return Number(ctx.goldCount);
      if(q==null) return null;
      const hardMax=Math.max(ctx.minGold||0, q-(ctx.minPurple||0)-(ctx.minRed||0));
      if(!Number.isFinite(avg)||avg<=0) return hardMax;
      let gMax=hardMax;
      // expensive golds are almost always few pieces
      if(avg>=200000) gMax=Math.min(gMax,2);
      else if(avg>=120000) gMax=Math.min(gMax,3);
      else if(avg>=80000) gMax=Math.min(gMax,4);
      else if(avg>=50000) gMax=Math.min(gMax,6);
      else if(avg>=35000) gMax=Math.min(gMax,8);
      const boxV=historyBoxValue(records,ctx);
      const ceiling=boxV&&boxV.n>=2 ? Math.max(boxV.p80*1.25, boxV.p50*2.0, avg*1.2) : avg*6;
      gMax=Math.min(gMax, Math.max(ctx.minGold||1, Math.floor(ceiling/avg + 0.25)));
      return Math.max(ctx.minGold||1, gMax);
    }

    function candidateStateWeight(records,state,ctx={}){
      let w=1;
      const r=Number(state.r), g=Number(state.g);
      if(Number.isInteger(r)){
        if(r===0) w*=1.35;
        else if(r===1) w*=1.0;
        else if(r===2) w*=0.55;
        else if(r===3) w*=0.28;
        else w*=Math.pow(0.18, r-3)*0.28;
      }
      // gold-avg-only: high unit price => few golds. Prevent G=7 * 15W gold avg exploding center.
      if(Number.isFinite(ctx.avg) && Number.isInteger(g)){
        const avg=Number(ctx.avg);
        let gDecay=1;
        if(avg>=120000) gDecay=Math.pow(0.22, Math.max(0,g-1));
        else if(avg>=80000) gDecay=Math.pow(0.34, Math.max(0,g-1));
        else if(avg>=50000) gDecay=Math.pow(0.48, Math.max(0,g-1));
        else if(avg>=35000) gDecay=Math.pow(0.62, Math.max(0,g-1));
        else gDecay=Math.pow(0.78, Math.max(0,g-1));
        w*=gDecay;
        const gCap=maxPlausibleGoldCount(records,ctx);
        if(gCap!=null && g>gCap) w*=0.02;
      }
      // 同场同箱且 Q 接近的历史若有结算金件数，只作温和先验；不能覆盖本局硬证据。
      if(Number.isInteger(g)){
        const countPrior=historicalCountPrior(records,ctx);
        if(countPrior.n&&Number.isFinite(countPrior.g)){
          const strength=Math.min(.55,.16+countPrior.n*.08);
          w*=Math.max(.18,Math.exp(-Math.abs(g-countPrior.g)*strength));
        }
      }
      // only-Q with unlocked red: don't let multi-red dominate working mid
      if(!Number.isFinite(ctx.avg) && !Number.isFinite(ctx.goldTotal) && !hasNumber(ctx.purple) && Number.isInteger(r) && r>=2){
        w*=0.65;
      }
      if(state.residualSplit) w*=0.85;
      if(state.gold&&state.gold.matches&&state.gold.matches.length) w*=1.1;
      if(hasNumber(ctx.redCount)&&Number(ctx.redCount)===0&&r===0) w*=1.5;
      return Math.max(w, 1e-6);
    }

    function redProbabilityProfile(ctx,states=[],componentRows=[],records=[],stateComponentsFn=null){
      const collectRows=(rows)=>rows.map(match=>{
        const label=historicalRedLabel(match.record||match);
        if(!label||!label.items?.length)return null;
        const weight=Number(match.weight)>0?Number(match.weight):1;
        const values=label.items.map(item=>({value:Number(item.price),weight})).filter(x=>Number.isFinite(x.value)&&x.value>0);
        return values.length?{record:match.record||match,label,weight,similarity:Number(match.similarity)||0,values,total:values.reduce((s,x)=>s+x.value,0)}:null;
      }).filter(Boolean);
      let rows=collectRows(similarHistory(records,ctx,32,"redDistribution").filter(x=>x.similarity>=35));
      let source="同场/同箱/Q近邻";
      if(rows.length<3){
        rows=collectRows(eligibleHistory(records,ctx,"redDistribution").filter(r=>r.venue===ctx.venue));
        source="同场地历史";
      }
      if(rows.length<3){
        rows=collectRows(eligibleHistory(records,ctx,"redDistribution"));
        source="全历史已验证红货";
      }
      // 当前近邻用于单件兜底；同 R 的完整红货列表另从全部“当时已发生”的历史中补齐，避免被 Top-32 相似度截掉。
      const directRanked=eligibleHistory(records,ctx,"redDistribution").map(record=>{const sim=similarityFor(ctx,record);return {record,similarity:sim.similarity,weight:Math.max(.01,(sim.similarity/100)**2.4)};});
      const directEvidence=collectRows(directRanked),evidenceMap=new Map([...rows,...directEvidence].map((x,i)=>[x.record?.id||x.record?.playedAt||`${x.record?.box||""}:${x.total}:${i}`,x])),completeEvidence=[...evidenceMap.values()];
      const distributionRows=directEvidence.length>=3?directEvidence:rows,distributionSource=directEvidence.length>=3?"前序全部已验证红货（相似度加权）":source;
      const items=distributionRows.flatMap(x=>x.values),weightedValues=items.map(x=>({value:x.value,weight:x.weight})),itemStats=weightedStats(weightedValues);
      const completeRows=completeEvidence.filter(x=>Number.isInteger(Number(x.label?.count))&&Number(x.label.count)>=0&&x.values.length===Number(x.label.count));
      const completeTotals=completeRows.map(x=>({value:x.total,weight:x.weight,r:Number(x.label.count)}));
      const totalStats=weightedStats(completeTotals.length?completeTotals:rows.map(x=>({value:x.total,weight:x.weight})));
      const byR=new Map();completeRows.forEach(x=>{const r=Number(x.label.count);if(!byR.has(r))byR.set(r,[]);byR.get(r).push({value:x.total,weight:x.weight,items:x.values.map(y=>y.value),record:x.record});});
      const tierNames=["普通红","中高红","高尾红","Jackpot"],tierCounts=Object.fromEntries(tierNames.map(x=>[x,0])),tierWeight=Object.fromEntries(tierNames.map(x=>[x,0]));
      items.forEach(x=>{const tier=redValueTier(x.value);if(tierCounts[tier]!==undefined){tierCounts[tier]++;tierWeight[tier]+=Math.max(.01,x.weight);}});
      const totalItemWeight=items.reduce((s,x)=>s+Math.max(.01,x.weight),0),smoothWeightedDen=totalItemWeight+tierNames.length;
      const historicalWeightedRate=tier=>totalItemWeight?tierWeight[tier]/totalItemWeight:null;
      const tiers=tierNames.map(tier=>({tier,range:redTierRange(tier),count:tierCounts[tier],rawObservationRate:items.length?tierCounts[tier]/items.length:null,smoothedRawRate:items.length?(tierCounts[tier]+1)/(items.length+tierNames.length):null,historicalWeightedRate:historicalWeightedRate(tier),smoothedWeightedRate:smoothWeightedDen?(tierWeight[tier]+1)/smoothWeightedDen:null,currentWeightedRate:null}));
      const knownRed=ctx.knownRed||[],knownPrices=knownRed.map(x=>Number(x.price)).filter(x=>Number.isFinite(x)&&x>0),knownTotal=knownPrices.reduce((s,x)=>s+x,0),knownCount=knownPrices.length;
      const countMap=values=>{const m=new Map();(values||[]).forEach(v=>m.set(v,(m.get(v)||0)+1));return m;};
      const canRemoveKnown=(values)=>{const have=countMap(values),need=countMap(knownPrices);for(const [price,n] of need)if((have.get(price)||0)<n)return null;const out=[...values];for(const price of knownPrices){const i=out.indexOf(price);if(i>=0)out.splice(i,1);else return null;}return out;};
      const itemPool=[...new Map(items.map(x=>[x.value,{value:x.value,weight:0}])).values()];items.forEach(x=>{const hit=itemPool.find(y=>y.value===x.value);if(hit)hit.weight+=Math.max(.01,x.weight);});
      const capacityByPrice=new Map();baseCatalogFor(ctx).red.forEach(x=>capacityByPrice.set(x[1],2));knownPrices.forEach(price=>capacityByPrice.set(price,Math.max(0,(capacityByPrice.get(price)||2)-1)));
      const eligiblePool=itemPool.filter(x=>(capacityByPrice.get(x.value)??2)>0);
      const makeRng=seed=>{let x=(seed>>>0)||0x9e3779b9;return ()=>{x=(Math.imul(1664525,x)+1013904223)>>>0;return x/4294967296;};};
      const bootstrapTotals=(remaining,seed)=>{
        if(!Number.isInteger(remaining)||remaining<0)return [];
        if(remaining===0)return [{value:0,weight:1,items:[]}];
        if(!eligiblePool.length)return [];
        const rng=makeRng(seed),out=[],limit=768,top=[...eligiblePool].sort((a,b)=>b.value-a.value).slice(0,Math.min(16,eligiblePool.length));
        const drawOne=(forced=null)=>{const used=new Map(),picked=[],pool=eligiblePool.slice();if(forced){picked.push(forced.value);used.set(forced.value,1);}while(picked.length<remaining){const candidates=pool.filter(x=>(capacityByPrice.get(x.value)||2)>(used.get(x.value)||0));if(!candidates.length)break;const total=candidates.reduce((s,x)=>s+x.weight,0),needle=rng()*total;let acc=0,choice=candidates.at(-1);for(const x of candidates){acc+=x.weight;if(acc>=needle){choice=x;break;}}picked.push(choice.value);used.set(choice.value,(used.get(choice.value)||0)+1);}return picked.length===remaining?{value:picked.reduce((s,x)=>s+x,0),weight:1,items:picked}:null;};
        top.forEach((item,i)=>{const row=drawOne(item);if(row)out.push(row);});
        while(out.length<limit){const row=drawOne();if(!row)break;out.push(row);}
        return out;
      };
      const residualForR=(r)=>{
        if(!Number.isInteger(r)||r<knownCount)return {samples:[],mode:"无可行红位置",directN:0,bootstrapN:0};
        const remaining=r-knownCount,exact=byR.get(r)||[],direct=[];
        if(exact.length){
          if(knownCount){exact.forEach(x=>{const rest=canRemoveKnown(x.items);if(rest)direct.push({value:rest.reduce((s,v)=>s+v,0),weight:x.weight,items:rest,origin:"direct",recordId:x.record?.id||x.record?.playedAt||null});});}
          else exact.forEach(x=>direct.push({value:x.value,weight:x.weight,items:x.items.slice(),origin:"direct",recordId:x.record?.id||x.record?.playedAt||null}));
        }
        if(direct.length>=2)return {samples:direct,mode:"同R完整红货总价",directN:direct.length,bootstrapN:0};
        const boot=bootstrapTotals(remaining,((r+1)*2654435761+knownCount*97)>>>0).map(x=>({...x,weight:x.weight*.75,origin:"bootstrap"}));
        const samples=[...direct,...boot];
        return {samples,mode:direct.length?"同R样本+单件组合兜底":"单件分布组合兜底",directN:direct.length,bootstrapN:boot.length};
      };
      const stateRows=[];
      (states||[]).forEach((s,i)=>{
        const w=Math.max(.01,candidateStateWeight(records,s,ctx)),min=Number.isInteger(s?.r)?Number(s.r):Number.isInteger(s?.rMin)?Number(s.rMin):null,max=Number.isInteger(s?.r)?Number(s.r):Number.isInteger(s?.rMax)?Number(s.rMax):null;
        if(min===null)return;
        const lo=Math.max(knownCount,min),hi=Math.max(lo,max??lo),n=Math.max(1,hi-lo+1);
        for(let r=lo;r<=hi;r++)stateRows.push({r,weight:w/n});
      });
      if(!stateRows.length&&hasNumber(ctx.redCount))stateRows.push({r:Number(ctx.redCount),weight:1});
      const totalRows=[],currentItemRows=[],usedModes=new Map(),perRRows=new Map();
      let currentDirectN=0,currentBootstrapN=0;
      const currentDirectGameIds=new Set();
      stateRows.forEach(s=>{
        const dist=residualForR(s.r);
        usedModes.set(dist.mode,(usedModes.get(dist.mode)||0)+1);
        const rBucket=perRRows.get(s.r)||{r:s.r,stateWeight:0,rows:[],directN:0,bootstrapN:0,directIds:new Set(),modeCounts:new Map()};
        rBucket.stateWeight+=s.weight;
        rBucket.directN+=Number(dist.directN)||0;
        rBucket.bootstrapN+=Number(dist.bootstrapN)||0;
        rBucket.modeCounts.set(dist.mode,(rBucket.modeCounts.get(dist.mode)||0)+1);
        dist.samples.forEach(sample=>{
          if(sample.origin==="direct"){
            currentDirectN++;
            if(sample.recordId)currentDirectGameIds.add(String(sample.recordId));
            if(sample.recordId)rBucket.directIds.add(String(sample.recordId));
          }else if(sample.origin==="bootstrap") currentBootstrapN++;
          const rowWeight=Math.max(.001,s.weight*(Number(sample.weight)||1));
          totalRows.push({value:knownTotal+sample.value,weight:rowWeight});
          rBucket.rows.push({value:knownTotal+sample.value,weight:Math.max(.001,Number(sample.weight)||1)});
          knownPrices.forEach(v=>currentItemRows.push({value:v,weight:rowWeight}));
          (sample.items||[]).forEach(v=>currentItemRows.push({value:v,weight:rowWeight}));
        });
        perRRows.set(s.r,rBucket);
      });
      const currentTotal=totalRows.length?weightedStats(totalRows):null,currentItemStats=currentItemRows.length?weightedStats(currentItemRows):null,currentTierWeight=Object.fromEntries(tierNames.map(x=>[x,0])),currentItemWeight=currentItemRows.reduce((s,x)=>s+x.weight,0);
      currentItemRows.forEach(x=>{const tier=redValueTier(x.value);if(currentTierWeight[tier]!==undefined)currentTierWeight[tier]+=x.weight;});
      tiers.forEach(x=>{x.currentWeightedRate=currentItemWeight?currentTierWeight[x.tier]/currentItemWeight:null;});
      const knownR=hasNumber(ctx.redCount)?Math.max(0,Number(ctx.redCount)-knownCount):null;
      const sameR=[...new Set(stateRows.map(x=>x.r))].map(r=>({r,n:(byR.get(r)||[]).length}));
      const sampleGames=distributionRows.length,sampleItems=items.length,sameRComplete=completeRows.length,fallbackUsed=[...usedModes.keys()].some(mode=>String(mode).includes("兜底")||String(mode).includes("样本+")),status=sampleItems>=12?(fallbackUsed?"同R样本不足，单件组合兜底":"可用于典型区间"):sampleItems>=3?"低样本，谨慎使用":"样本不足，不估概率";
      const currentDistributionN=totalRows.length,currentDistributionUniqueN=new Set(totalRows.map(x=>Number(x.value))).size;
      const currentDistributionMode=currentDirectN>0&&currentBootstrapN>0?"mixed":currentDirectN>0?"direct":currentBootstrapN>0?"bootstrap":"none";
      // 尾部分位必须看“当前局实际用到的分布样本”，不能因为全历史有很多红色 item 就伪装成充分样本。
      // bootstrap 生成的 768 条只是模拟抽样，不等同于 768 个独立对局，因此不开放精确尾部口径。
      const currentDirectGames=currentDirectGameIds.size||currentDirectN;
      const directTailP10Ready=currentDistributionMode==="direct"&&currentDirectGames>=10;
      const directTailP95Ready=currentDistributionMode==="direct"&&currentDirectGames>=20;
      const currentDistribution={n:currentDistributionN,uniqueN:currentDistributionUniqueN,directN:currentDirectN,directGames:currentDirectGames,bootstrapN:currentBootstrapN,mode:currentDistributionMode,tailP10Ready:directTailP10Ready,tailP95Ready:directTailP95Ready,label:currentDistributionMode==="direct"?"同R直接经验分布":currentDistributionMode==="bootstrap"?"bootstrap组合模拟分布":currentDistributionMode==="mixed"?"同R直接经验 + bootstrap组合":"无可用当前分布"};
      const profileStatus=currentDistributionMode==="bootstrap"?"探索性/低样本 · bootstrap组合":currentDistributionMode==="mixed"?"探索性/低样本 · 直接+bootstrap":currentDistributionMode==="direct"&&currentDirectGames<10?"低样本，谨慎使用":status;
      const redTailRelevant=knownCount>0||stateRows.some(x=>Number(x.r)>0),tailGuardLevel=!redTailRelevant?"none":directTailP95Ready?"calibrated":directTailP10Ready?"limited":"unverified",tailGuard={level:tailGuardLevel,relevant:redTailRelevant,directGames:currentDirectGames,directSamples:currentDirectN,bootstrapSamples:currentBootstrapN,p80Ready:directTailP10Ready,p95Ready:directTailP95Ready,reason:!redTailRelevant?"本局已锁定 R=0":directTailP95Ready?`已有 ${currentDirectGames} 个同 R 直接局，尾部可作有限参考`:directTailP10Ready?`只有 ${currentDirectGames} 个同 R 直接局，P80 仍不是最高价`:`同 R 直接样本不足（${currentDirectGames} 局）；当前分布${currentDistributionMode==="bootstrap"?"主要来自 bootstrap 组合模拟":"不足"}，P80 仅探索性参考`};
      const stateDistributions=[...perRRows.values()].sort((a,b)=>a.r-b.r).map(bucket=>{
        const stats=bucket.rows.length?weightedStats(bucket.rows):null,directGames=bucket.directIds?.size||bucket.directN,mode=bucket.directN>0&&bucket.bootstrapN>0?"mixed":bucket.directN>0?"direct":bucket.bootstrapN>0?"bootstrap":"none";
        return {r:bucket.r,stateWeight:bucket.stateWeight,stats,directN:bucket.directN,directGames,bootstrapN:bucket.bootstrapN,mode,tailP10Ready:mode==="direct"&&directGames>=10,tailP95Ready:mode==="direct"&&directGames>=20,modes:[...bucket.modeCounts].map(([mode,n])=>({mode,n}))};
      });
      const stateCandidateSource=(states||[]).map(s=>{
        const rMin=Number.isInteger(s?.r)?Number(s.r):Number.isInteger(s?.rMin)?Number(s.rMin):null,rMax=Number.isInteger(s?.r)?Number(s.r):Number.isInteger(s?.rMax)?Number(s.rMax):rMin;
        return {g:Number.isInteger(s?.g)?Number(s.g):null,p:Number.isInteger(s?.p)?Number(s.p):null,r:Number.isInteger(s?.r)?Number(s.r):null,rMin,rMax,weight:Math.max(.01,candidateStateWeight(records,s,ctx))};
      }).filter(x=>x.rMin!==null);
      const candidateWeightTotal=stateCandidateSource.reduce((sum,x)=>sum+x.weight,0)||1;
      const stateCandidates=stateCandidateSource.map(s=>{
        const redRows=stateDistributions.filter(x=>x.r>=s.rMin&&x.r<=s.rMax),exact=redRows.length===1&&s.rMin===s.rMax?redRows[0]:null;
        return {...s,relativeWeight:s.weight/candidateWeightTotal,red:exact?.stats||null,redMode:exact?.mode||null,redByR:redRows.map(x=>({r:x.r,stats:x.stats,mode:x.mode,directGames:x.directGames,bootstrapN:x.bootstrapN}))};
      });
      const componentForState=s=>{
        const hit=(componentRows||[]).find(row=>row?.state&&Number(row.state.g)===s.g&&Number(row.state.p)===s.p&&Number(row.state.r)===s.r);
        return hit?.component||(typeof stateComponentsFn==="function"?stateComponentsFn(ctx,s):null);
      };
      // Keep the same shadow construction for the whole distribution and for
      // each individual State.  This is presentation data only: it reuses the
      // existing fixed gold/purple/low-tier mids plus the existing red sample
      // rows, and never feeds back into the v0.3 center or bid calculation.
      const stateShadowKey=s=>`${s.g??"—"}/${s.p??"—"}/${s.r??s.rMin??"—"}`;
      const stateShadowStats=new Map(),stateComponentMap=new Map();
      const shadowRows=[];
      let supportedStateCount = 0;
      let supportedWeight = 0;
      const totalStateCount = stateCandidateSource.length;
      const totalWeight = candidateWeightTotal;

      stateCandidateSource.forEach(s=>{
        if(!Number.isInteger(s.g)||!Number.isInteger(s.p)||!Number.isInteger(s.r))return;
        const bucket=perRRows.get(s.r),component=componentForState(s);if(!bucket?.rows?.length||!component)return;
        supportedStateCount++;
        supportedWeight += s.weight;
        const fixed=(component.gold?.mid||0)+(component.purple?.mid||0)+(component.lowTier?.mid||0);
        stateComponentMap.set(stateShadowKey(s),component);
        const stateRows=[];
        bucket.rows.forEach(sample=>{
          const row={value:fixed+sample.value,weight:Math.max(.001,s.weight*(Number(sample.weight)||1))};
          stateRows.push(row);shadowRows.push(row);
        });
        if(stateRows.length)stateShadowStats.set(stateShadowKey(s),weightedStats(stateRows));
      });

      const coverageRatio = totalWeight > 0 ? (supportedWeight / totalWeight) : (totalStateCount > 0 ? supportedStateCount / totalStateCount : 0);
      const isFullShadow = coverageRatio >= 0.999999 && shadowRows.length > 0;
      const partialShadow = shadowRows.length ? weightedStats(shadowRows) : null;
      const shadowWhole = isFullShadow ? partialShadow : null;

      const shadowCoverage = {
        supportedStateCount,
        totalStateCount,
        supportedWeight,
        totalWeight,
        coverageRatio,
        isFull: isFullShadow
      };

      const stateCandidatesWithDetails=stateCandidates.map(s=>({...s,component:stateComponentMap.get(stateShadowKey(s))||componentForState(s)||null,shadow:stateShadowStats.get(stateShadowKey(s))||null}));
      const historyEvidence=completeEvidence.slice().sort((a,b)=>Number(b.similarity||0)-Number(a.similarity||0)||Number(b.weight||0)-Number(a.weight||0)).map(x=>({id:x.record?.id||x.record?.playedAt||null,playedAt:x.record?.playedAt||"",venue:x.record?.venue||"",box:x.record?.box||"未知箱型",r:Number(x.label?.count)||0,redItems:(x.label?.items||[]).map(item=>`${item.name||"红藏品"} ${item.price}`).join(" + "),redTotal:x.total,similarity:Number(x.similarity||0),weight:Number(x.weight||0)}));
      return {source:distributionSource,sampleGames,sampleItems,sameRComplete,status:profileStatus,itemStats,totalStats,currentTotal,currentItemStats,currentDistribution,tailGuard,tiers,knownTotal,knownCount,remainingR:knownR,currentModes:[...usedModes].map(([mode,n])=>({mode,n})),sameR,stateCandidates:stateCandidatesWithDetails,stateDistributions,shadowWhole,shadowCoverage,supportedStateCount,totalStateCount,supportedWeight,totalWeight,coverageRatio,partialShadow,partialShadowP20:partialShadow?.p20??null,partialShadowP50:partialShadow?.p50??null,partialShadowP80:partialShadow?.p80??null,historyEvidence,tail:{observedMax:itemStats?.max??null,sampledMax:currentItemStats?.max??null,totalObservedMax:totalStats?.max??null,jackpotN:tierCounts.Jackpot||0,jackpotRate:items.length?tierCounts.Jackpot/items.length:null},heuristicNote:"候选状态权重与红色固定衰减仍为 v0.3 旧 heuristic；本档只做历史分布对照，不改中心估值。当前局红总价优先使用同 R 完整红货总价；样本不足时才用带重复上限的单件经验组合。"};
    }


  function buildProbabilityProfile(ctx, states, options) {
    const opts = options || {};
    const records = Array.isArray(opts.records) ? opts.records : [];
    const componentRows = Array.isArray(opts.componentRows) ? opts.componentRows : [];
    const stateComponentsFn = typeof opts.stateComponentsFn === "function" ? opts.stateComponentsFn : null;
    return redProbabilityProfile(ctx, states || [], componentRows, records, stateComponentsFn);
  }

  return {
    buildProbabilityProfile,
    redProbabilityProfile,
    historicalRedLabel,
    parseHistoricalRedItems,
    eligibleHistory,
    similarHistory,
    historyCompatible,
    similarityFor,
    candidateStateWeight,
    historicalCountPrior
  };
}));
