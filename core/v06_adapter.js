/**
 * v0.6 Solver Adapter (Canonical MatchRecord v7 -> 0.6 Solver Input)
 *
 * 唯一职责：
 * 1. 字段映射与解耦 (loadout.solverToolGroup -> toolGroup, qualities.gold.avg -> goldAvg/avg)
 * 2. legacy flatten 与类型转换 (qualities.*.knownItems -> legacy string '51077+18031' 或 '万有星仪')
 * 3. canonical enum / alias 转换 (venue / box / fieldCondition)
 * 4. unknown/null 语义保持 (未观测字段严格保持 null，绝不写 0)
 * 5. 事实与推断完全分离 (不把旧 solver 推演结果当做事实反喂)
 */

(function(global, factory) {
  const adapter = factory();
  if (typeof exports === 'object' && typeof module !== 'undefined') {
    module.exports = adapter;
  }
  if (typeof define === 'function' && define.amd) {
    define(function() { return adapter; });
  }
  if (typeof globalThis !== 'undefined') {
    globalThis.V06Adapter = adapter;
  }
  if (typeof window !== 'undefined') {
    window.V06Adapter = adapter;
  }
  if (typeof global !== 'undefined') {
    global.V06Adapter = adapter;
  }
}(typeof self !== 'undefined' ? self : this, function() {
  "use strict";

  const VENUE_CANONICAL_TO_NAME = {
    "shanhu": "中级场 · 珊瑚场",
    "milin": "高级场 · 密林场",
    "baiye": "高级场 · 白夜场",
    "haimo": "顶级场 · 海沫场"
  };

  const VENUE_NAME_TO_CANONICAL = {
    "中级场 · 珊瑚场": "shanhu",
    "珊瑚场": "shanhu",
    "中级场·珊瑚场": "shanhu",
    "高级场 · 密林场": "milin",
    "密林场": "milin",
    "高级场·密林场": "milin",
    "高级场 · 白夜场": "baiye",
    "白夜场": "baiye",
    "高级场·白夜场": "baiye",
    "顶级场 · 海沫场": "haimo",
    "海沫场": "haimo",
    "顶级场·海沫场": "haimo"
  };

  function formatKnownItems(items) {
    if (items === null || items === undefined || items === "" || (Array.isArray(items) && items.length === 0)) {
      return "";
    }
    if (typeof items === "string") {
      return items.trim();
    }
    if (!Array.isArray(items)) {
      return String(items).trim();
    }

    const parts = [];
    for (const it of items) {
      if (it === null || it === undefined) continue;
      if (typeof it === "string") {
        const s = it.trim();
        if (s) parts.append ? parts.append(s) : parts.push(s);
      } else if (typeof it === "number") {
        parts.push(String(Math.floor(it)));
      } else if (typeof it === "object") {
        const name = it.name;
        const price = it.price;
        const count = Number(it.count) || 1;
        let token = null;
        if (name) {
          token = String(name).trim();
        } else if (price !== null && price !== undefined) {
          token = String(Math.floor(Number(price)));
        }
        if (token) {
          if (count > 1) {
            token = `${token}*${count}`;
          }
          parts.push(token);
        }
      }
    }
    return parts.join("+");
  }

  function canonicalizeVenueName(venueVal, fillDefault = true) {
    if (!venueVal || venueVal === "未知场地" || venueVal === "unknown") {
      return fillDefault ? "中级场 · 珊瑚场" : null;
    }
    if (VENUE_CANONICAL_TO_NAME[venueVal]) {
      return VENUE_CANONICAL_TO_NAME[venueVal];
    }
    for (const [k, v] of Object.entries(VENUE_NAME_TO_CANONICAL)) {
      if (k.includes(venueVal) || venueVal.includes(k)) {
        return VENUE_CANONICAL_TO_NAME[v] || venueVal;
      }
    }
    return venueVal;
  }

  function canonicalizeFieldConditionId(condVal, fillDefault = true) {
    if (!condVal) {
      return fillDefault ? "standard" : null;
    }
    if (condVal === "未知场地条件" || condVal === "unknown") {
      return fillDefault ? "standard" : condVal;
    }
    const aliasMap = {
      "标准对局": "standard",
      "标准规则": "standard",
      "天黑了": "dark",
      "一手情报": "extraIntel",
      "加倍！！": "purpleDouble",
      "加倍！！！": "goldDouble",
      "闪耀之心": "sparkle",
      "福利多多": "welfare",
      "宝石迷阵": "gemMaze",
      "宝石迷宫": "gemMaze",
      "gem_maze": "gemMaze"
    };
    return aliasMap[condVal] || condVal;
  }

  function canonicalToV06SolverInput(data = {}) {
    if (!data || typeof data !== "object") return {};

    let fillDefault = true;
    if (data.fillDefaults === false || data.source === "manual") fillDefault = false;
    const envProbe = data.environment || {};
    if (envProbe.fieldConditionSource === "user_override") fillDefault = false;

    const isV7Schema = !!(data.qualities || data.environment || data.schemaVersion === 7);

    let venue, box, fieldCondition, character, toolGroup;
    let q, totalItems, totalGrid, avgValueBasis;
    let goldAvg, goldCount, minGold, goldTotal, goldGrid, knownGold;
    let purpleAvg, purpleCount, minPurple, purpleGrid, knownPurple;
    let redGrid, redCount, minRed, knownRed, redInventoryComplete, settlementVerifiedRedItems;
    let blueCount, blueAvg, blueGrid;
    let greenCount, greenAvg, greenGrid;
    let whiteCount, whiteAvg, whiteGrid;
    let cost, costs, targetProfit, roundNo, leaderBid;

    if (isV7Schema) {
      const env = data.environment || {};
      const loadout = data.loadout || {};
      const costsObj = data.costs || {};
      const pub = data.publicIntel || {};
      const quals = data.qualities || {};
      const bidding = data.bidding || {};

      const venueTier = env.venueTier || null;
      venue = canonicalizeVenueName(env.venueName || env.venue, fillDefault);
      box = env.box || (fillDefault ? "琉璃宝箱（宝石类概率提升）" : null);
      fieldCondition = canonicalizeFieldConditionId(env.fieldCondition, fillDefault);
      character = loadout.character || (fillDefault ? "达芙蒂尔" : null);
      toolGroup = loadout.solverToolGroup;
      if (toolGroup !== "group1" && toolGroup !== "group2") {
        toolGroup = fillDefault ? "group1" : null;
      }

      q = pub.q ?? null;
      totalItems = pub.totalItems ?? null;
      totalGrid = pub.totalGrid ?? null;
      avgValueBasis = pub.avgValueBasis || "unknown";

      const g = quals.gold || {};
      const p = quals.purple || {};
      const r = quals.red || {};
      const b = quals.blue || {};
      const gr = quals.green || {};
      const w = quals.white || {};

      goldAvg = g.avg ?? null;
      goldCount = g.count ?? null;
      minGold = g.minCount ?? null;
      goldTotal = g.total ?? null;
      goldGrid = g.grid ?? null;
      knownGold = formatKnownItems(g.knownItems);

      purpleAvg = p.avg ?? null;
      purpleCount = p.count ?? null;
      minPurple = p.minCount ?? null;
      purpleGrid = p.grid ?? null;
      knownPurple = formatKnownItems(p.knownItems);

      redCount = r.count ?? null;
      redGrid = r.grid ?? null;
      minRed = r.minCount ?? null;
      knownRed = formatKnownItems(r.knownItems);
      redInventoryComplete = r.redInventoryComplete === true;
      settlementVerifiedRedItems = r.settlementVerifiedRedItems || "";

      blueCount = b.count ?? null;
      blueAvg = b.avg ?? null;
      blueGrid = b.grid ?? null;

      greenCount = gr.count ?? null;
      greenAvg = gr.avg ?? null;
      greenGrid = gr.grid ?? null;

      whiteCount = w.count ?? null;
      whiteAvg = w.avg ?? null;
      whiteGrid = w.grid ?? null;

      cost = costsObj.total ?? costsObj.sunkCost ?? 5000;
      costs = costsObj;
      targetProfit = data.targetProfit ?? (fillDefault ? 30000 : null);
      roundNo = bidding.round ?? data.round ?? 1;
      leaderBid = bidding.leaderBid ?? bidding.myFinalBid ?? data.leaderBid ?? (fillDefault ? 0 : null);
    } else {
      venue = canonicalizeVenueName(data.venue, fillDefault);
      box = data.box || data.boxType || (fillDefault ? "琉璃宝箱（宝石类概率提升）" : null);
      fieldCondition = canonicalizeFieldConditionId(data.fieldCondition, fillDefault);
      character = data.character || data.lobbyCharacter || (fillDefault ? "达芙蒂尔" : null);

      const stg = data.solverToolGroup;
      const tg = data.toolGroup;
      if (stg === "group1" || stg === "group2") {
        toolGroup = stg;
      } else if (tg === "group1" || tg === "group2") {
        toolGroup = tg;
      } else {
        toolGroup = fillDefault ? "group1" : null;
      }

      q = data.q ?? null;
      totalItems = data.totalItems ?? null;
      totalGrid = data.totalGrids ?? data.totalGrid ?? null;
      avgValueBasis = data.avgValueBasis || "unknown";

      goldAvg = data.goldAvg ?? null;
      purpleAvg = data.purpleAvg ?? null;
      blueAvg = data.blueAvg ?? null;
      greenAvg = data.greenAvg ?? null;
      whiteAvg = data.whiteAvg ?? null;

      goldCount = data.goldCount ?? null;
      minGold = data.minGold ?? null;
      goldTotal = data.goldTotal ?? null;
      goldGrid = data.goldGrid ?? null;

      purpleCount = data.purpleCount ?? data.purple ?? null;
      minPurple = data.minPurple ?? null;
      purpleGrid = data.purpleGrid ?? null;

      redCount = data.redCount ?? null;
      redGrid = data.redGrid ?? null;
      minRed = data.minRed ?? null;
      redInventoryComplete = data.redInventoryComplete === true;
      settlementVerifiedRedItems = data.settlementVerifiedRedItems || data.redItems || "";

      blueCount = data.blueCount ?? null;
      blueGrid = data.blueGrid ?? null;

      greenCount = data.greenCount ?? null;
      greenGrid = data.greenGrid ?? null;

      whiteCount = data.whiteCount ?? null;
      whiteGrid = data.whiteGrid ?? null;

      const shapes = data.identifiedShapes || {};
      const rawKg = shapes.knownGold || data.knownGold;
      const rawKp = shapes.knownPurple || data.knownPurple;
      const rawKr = shapes.knownRed || data.knownRed || data.decisionKnownRed;

      knownGold = formatKnownItems(rawKg);
      knownPurple = formatKnownItems(rawKp);
      knownRed = formatKnownItems(rawKr);

      const costsRaw = data.costs || {};
      cost = data.cost ?? costsRaw.total ?? costsRaw.sunkCost ?? 5000;
      costs = costsRaw && Object.keys(costsRaw).length ? costsRaw : {
        entry: 5000,
        intel: Number(cost) > 5000 ? Number(cost) - 5000 : 0,
        other: 0,
        sunkCost: Number(cost),
        futureIncrementalCost: 0,
        total: Number(cost)
      };
      targetProfit = data.targetProfit ?? (fillDefault ? 30000 : null);
      roundNo = data.round ?? 1;
      leaderBid = data.currentLeaderBid ?? data.leaderBid ?? data.myBid ?? (fillDefault ? 0 : null);
    }

    return {
      q,
      sparkle: data.sparkle == null ? null : JSON.parse(JSON.stringify(data.sparkle)),
      privateBidCap: Object.hasOwn(data, 'privateBidCap') ? data.privateBidCap : (data.bidding?.privateBidCap ?? null),
      bidActionCount: Object.hasOwn(data, 'bidActionCount') ? data.bidActionCount : (data.bidding?.bidActionCount ?? null),
      p: purpleCount,
      purple: purpleCount,
      purpleCount,
      goldCount,
      redCount,
      minGold,
      minPurple,
      minRed,
      avg: goldAvg, // 0.6 internal gold avg parameter
      goldAvg,
      purpleAvg,
      blueAvg,
      greenAvg,
      whiteAvg,
      goldTotal,
      goldGrid,
      purpleGrid,
      redGrid,
      blueCount,
      blueGrid,
      greenCount,
      greenGrid,
      whiteCount,
      whiteGrid,
      totalItems,
      totalGrid,
      cost: Number(cost) || 0,
      costs,
      targetProfit: targetProfit === null || targetProfit === undefined || targetProfit === "" ? null : Number(targetProfit),
      knownGold,
      ...Object.fromEntries(["blue","green","white"].map(color=>{
        const key="known"+color[0].toUpperCase()+color.slice(1);
        return [key,formatKnownItems(isV7Schema?data.qualities?.[color]?.knownItems:data[key])];
      })),
      knownPurple,
      knownRed,
      knownGoldRaw: knownGold,
      knownPurpleRaw: knownPurple,
      knownRedRaw: knownRed,
      goldGroups: [],
      purpleGroups: [],
      redGroups: [],
      venueTier: isV7Schema ? (data.environment && data.environment.venueTier) : data.venueTier,
      venue,
      box,
      fieldCondition,
      avgValueBasis,
      roundingMode: "floor",
      toolGroup,
      character,
      round: Number(roundNo) || 1,
      leaderBid: leaderBid === null || leaderBid === undefined || leaderBid === "" ? null : Number(leaderBid),
      matchId: data.id || data.matchId || null,
      redInventoryComplete,
      settlementVerifiedRedItems,
      publicInfo: {
        totalItems,
        totalGrid,
        goldGrid,
        purpleGrid,
        redGrid,
        blueCount,
        blueGrid,
        blueAvg,
        greenCount,
        greenGrid,
        greenAvg,
        whiteCount,
        whiteGrid,
        whiteAvg,
        systemEstimate: null,
        singleAvg: null,
        nineAvg: null,
        publicNote: ""
      }
    };
  }

  function v06RecordToCanonical(legacy = {}) {
    if (!legacy || typeof legacy !== "object") return {};

    const venueName = legacy.venue || "中级场 · 珊瑚场";
    const canonicalVenue = VENUE_NAME_TO_CANONICAL[venueName] || "shanhu";

    function parseLegacyKnown(rawText) {
      if (!rawText || typeof rawText !== "string") return [];
      const items = [];
      const tokens = rawText.split("+");
      for (let t of tokens) {
        t = t.trim();
        if (!t) continue;
        if (/^\d+$/.test(t)) {
          items.push({ name: null, price: Number(t) });
        } else {
          items.push({ name: t, price: null });
        }
      }
      return items;
    }

    const costsRaw = legacy.costs || {};
    const costTotal = legacy.cost ?? costsRaw.total ?? 5000;
    const costs = {
      entry: costsRaw.entry ?? 5000,
      intel: costsRaw.intel ?? costsRaw.info ?? (Number(costTotal) > 5000 ? Number(costTotal) - 5000 : 0),
      other: costsRaw.other ?? 0,
      sunkCost: costsRaw.sunkCost ?? Number(costTotal),
      futureIncrementalCost: costsRaw.futureIncrementalCost ?? 0,
      total: Number(costTotal)
    };

    const pred = legacy.prediction;
    let solverResult = null;
    if (pred && typeof pred === "object") {
      solverResult = {
        solverVersion: "v0.6",
        solverStatus: pred.solverStatus || "valid",
        inputHash: pred.inputHash || "",
        solvedAt: legacy.playedAt || "",
        round: pred.round || 1,
        decisions: {
          targetLine: pred.targetLine ?? null,
          globalLine: pred.globalLine ?? null,
          marginalLine: pred.marginalLine ?? null,
          valP20: pred.rawShadow?.p20 ?? pred.workingLow ?? null,
          valP50: pred.estimate ?? null,
          valP80: pred.rawShadow?.p80 ?? pred.workingHigh ?? null,
          theoreticalMin: pred.theoreticalMin ?? null,
          theoreticalMax: pred.theoreticalMax ?? null
        },
        goldInference: pred.goldInference || null,
        candidateGs: pred.candidateGs || [],
        candidatePs: pred.candidatePs || [],
        componentBreakdown: pred.componentBreakdown || null,
        probabilityProfile: pred.rawShadow || null
      };
    }

    return {
      schemaVersion: 7,
      productVersion: legacy.productVersion || "v0.6",
      id: legacy.id || "",
      playedAt: legacy.playedAt || legacy.date || "",
      periodKey: legacy.periodKey || legacy.patch || "",
      environment: {
        venue: canonicalVenue,
        venueName,
        box: legacy.box || "未知箱型",
        boxType: String(legacy.box || "").includes("实木") ? "wood" : (String(legacy.box || "").includes("琉璃") ? "glass" : "standard"),
        fieldCondition: legacy.fieldCondition || "standard",
        fieldConditionName: "标准对局",
        fieldConditionSource: legacy.fieldConditionSource || "explicit"
      },
      loadout: {
        character: legacy.character || "达芙蒂尔",
        lobbyToolGroup: null,
        solverToolGroup: legacy.toolGroup || "group1"
      },
      costs,
      publicIntel: {
        q: legacy.q ?? null,
        totalItems: legacy.totalItems ?? null,
        totalGrid: legacy.totalGrid ?? null,
        avgValueBasis: legacy.avgValueBasis || "unknown"
      },
      qualities: {
        white: {
          count: legacy.whiteCount ?? null,
          avg: legacy.whiteAvg ?? null,
          grid: legacy.whiteGrid ?? null
        },
        green: {
          count: legacy.greenCount ?? null,
          avg: legacy.greenAvg ?? null,
          grid: legacy.greenGrid ?? null
        },
        blue: {
          count: legacy.blueCount ?? null,
          avg: legacy.blueAvg ?? null,
          grid: legacy.blueGrid ?? null
        },
        purple: {
          count: legacy.purpleCount ?? legacy.purple ?? null,
          minCount: legacy.minPurple ?? 0,
          avg: legacy.purpleAvg ?? null,
          grid: legacy.purpleGrid ?? null,
          knownItems: parseLegacyKnown(legacy.knownPurple)
        },
        gold: {
          count: legacy.goldCount ?? null,
          minCount: legacy.minGold ?? 0,
          avg: legacy.goldAvg ?? null,
          total: legacy.goldTotal ?? null,
          grid: legacy.goldGrid ?? null,
          knownItems: parseLegacyKnown(legacy.knownGold)
        },
        red: {
          count: legacy.redCount ?? null,
          minCount: legacy.minRed ?? 0,
          maxCount: null,
          knownItems: parseLegacyKnown(legacy.knownRed || legacy.decisionKnownRed),
          redInventoryComplete: legacy.redInventoryComplete === true,
          settlementVerifiedRedItems: legacy.settlementVerifiedRedItems || ""
        }
      },
      bidding: {
        seats: [],
        myName: legacy.myName || "秋星祭02",
        myFinalBid: legacy.highestPersonalBid ?? legacy.bid ?? null,
        leaderName: legacy.winner || "",
        leaderBid: legacy.clearingPrice ?? null,
        leaderTies: [],
        isMyLead: legacy.acquired === true,
        historicalBids: legacy.historicalBids || {},
        finalBids: legacy.finalBids || {},
        rounds: legacy.rounds || []
      },
      settlement: {
        isSettled: legacy.actualTotal !== null && legacy.actualTotal !== undefined,
        clearingPrice: legacy.clearingPrice ?? legacy.bid ?? null,
        actualTotal: legacy.actualTotal ?? null,
        realizedProfit: legacy.realizedProfit ?? null,
        acquired: legacy.acquired === true,
        winner: legacy.winner || "",
        resultReason: legacy.resultReason || legacy.noBidReason || "",
        settlementItems: [],
        realizedState: legacy.realizedState || null
      },
      solverResult
    };
  }

  function v065RecordToCanonical(rec = {}) {
    if (!rec || typeof rec !== "object") return {};

    const venueRaw = rec.venue || "shanhu";
    const canonicalVenue = VENUE_NAME_TO_CANONICAL[venueRaw] || venueRaw;
    const venueName = VENUE_CANONICAL_TO_NAME[canonicalVenue] || venueRaw;

    const shapes = rec.identifiedShapes || {};
    const kg = shapes.knownGold || rec.knownGold || [];
    const kp = shapes.knownPurple || rec.knownPurple || [];
    const kr = shapes.knownRed || rec.knownRed || [];

    function toItemObjects(arr) {
      if (!arr) return [];
      if (typeof arr === "string") {
        return arr.split("+").filter(t => t.trim()).map(t => {
          const s = t.trim();
          return /^\d+$/.test(s) ? { name: null, price: Number(s) } : { name: s, price: null };
        });
      }
      if (Array.isArray(arr)) {
        return arr.map(x => {
          if (typeof x === "object" && x !== null) return x;
          if (typeof x === "number") return { name: null, price: Math.floor(x) };
          if (typeof x === "string") return { name: x.trim(), price: null };
          return null;
        }).filter(Boolean);
      }
      return [];
    }

    const costsRaw = rec.costs || {};
    const costTotal = rec.cost ?? costsRaw.total ?? 5000;
    const costs = {
      entry: costsRaw.entry ?? 5000,
      intel: costsRaw.intel ?? costsRaw.info ?? (Number(costTotal) > 5000 ? Number(costTotal) - 5000 : 0),
      other: costsRaw.other ?? 0,
      sunkCost: costsRaw.sunkCost ?? Number(costTotal),
      futureIncrementalCost: costsRaw.futureIncrementalCost ?? 0,
      total: Number(costTotal)
    };

    let solverTg = rec.solverToolGroup;
    let lobbyTg = rec.lobbyToolGroup;
    const rawTg = rec.toolGroup;
    if (!solverTg) {
      if (rawTg === "group1" || rawTg === "group2") {
        solverTg = rawTg;
      } else {
        solverTg = "group1";
        if (!lobbyTg && rawTg) lobbyTg = rawTg;
      }
    }

    return {
      schemaVersion: 7,
      productVersion: rec.productVersion || "v0.65",
      id: rec.id || "",
      playedAt: rec.playedAt || rec.timestamp || "",
      periodKey: rec.periodKey || "",
      environment: {
        venue: canonicalVenue,
        venueName,
        box: rec.box || rec.boxType || "未知箱型",
        boxType: rec.boxType || (String(rec.box || "").includes("实木") ? "wood" : (String(rec.box || "").includes("琉璃") ? "glass" : "standard")),
        fieldCondition: rec.fieldCondition || "standard",
        fieldConditionName: "标准对局",
        fieldConditionSource: "vision_ocr"
      },
      loadout: {
        character: rec.character || "达芙蒂尔",
        lobbyToolGroup: lobbyTg || null,
        solverToolGroup: solverTg || "group1"
      },
      costs,
      publicIntel: {
        q: rec.q ?? null,
        totalItems: rec.totalItems ?? null,
        totalGrid: rec.totalGrids ?? rec.totalGrid ?? null,
        avgValueBasis: rec.avgValueBasis || "unknown"
      },
      qualities: {
        white: {
          count: rec.whiteCount ?? null,
          avg: rec.whiteAvg ?? null,
          grid: rec.whiteGrid ?? null
        },
        green: {
          count: rec.greenCount ?? null,
          avg: rec.greenAvg ?? null,
          grid: rec.greenGrid ?? null
        },
        blue: {
          count: rec.blueCount ?? null,
          avg: rec.blueAvg ?? null,
          grid: rec.blueGrid ?? null
        },
        purple: {
          count: rec.purpleCount ?? rec.purple ?? null,
          minCount: rec.minPurple ?? null,
          avg: rec.purpleAvg ?? null,
          grid: rec.purpleGrid ?? null,
          knownItems: toItemObjects(kp)
        },
        gold: {
          count: rec.goldCount ?? null,
          minCount: rec.minGold ?? null,
          avg: rec.goldAvg ?? null,
          total: rec.goldTotal ?? null,
          grid: rec.goldGrid ?? null,
          knownItems: toItemObjects(kg)
        },
        red: {
          count: rec.redCount ?? null,
          minCount: rec.minRed ?? null,
          maxCount: null,
          knownItems: toItemObjects(kr),
          redInventoryComplete: rec.redInventoryComplete === true,
          settlementVerifiedRedItems: rec.settlementVerifiedRedItems || ""
        }
      },
      bidding: {
        seats: rec.opponents || [],
        myName: rec.myName || "秋星祭02",
        myFinalBid: rec.myFinalBid ?? rec.myBid ?? null,
        leaderName: rec.winnerName || rec.leaderName || "",
        leaderBid: rec.clearingPrice ?? rec.currentLeaderBid ?? null,
        leaderTies: rec.leaderTies || [],
        isMyLead: rec.isAcquired === true,
        historicalBids: rec.historicalBids || {},
        finalBids: rec.finalBids || {},
        rounds: rec.roundTimeline || rec.rounds || []
      },
      settlement: {
        isSettled: rec.actualTotal !== null && rec.actualTotal !== undefined,
        clearingPrice: rec.clearingPrice ?? null,
        actualTotal: rec.actualTotal ?? null,
        realizedProfit: rec.realizedProfit ?? null,
        acquired: rec.isAcquired ?? rec.acquired ?? false,
        winner: rec.winnerName || rec.winner || "",
        resultReason: rec.resultReason || "",
        settlementItems: rec.settlementItems || [],
        realizedState: rec.realizedState || null
      },
      solverResult: null
    };
  }

  return {
    formatKnownItems,
    canonicalizeVenueName,
    canonicalizeFieldConditionId,
    canonicalToV06SolverInput,
    v06RecordToCanonical,
    v065RecordToCanonical
  };
}));
