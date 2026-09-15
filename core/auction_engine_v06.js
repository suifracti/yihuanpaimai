/**
 * Neverness to Everness (异环) - 共享纯净拍卖核心引擎 (v0.6 Final / v0.65)
 * 
 * 纯数学与算法模块，零 DOM 依赖：
 * 1. 冻结图鉴快照与场地规则 (Catalog & Venue Rules)
 * 2. 约束图分配与精细离散组合求解器 (Bipartite Assignment & Exact DP Inversion)
 * 3. Shadow 分布统计推演与经验校准器 (Shadow Probability & Calibration)
 * 4. 市场成交预测与准入博弈模型 (Market Prediction & Entry Model)
 * 5. 边际成本与三线决策引擎 (Sunk/Marginal Cost & 3 Independent Decision Lines)
 * 6. 熵变、情报事件与诊断自测套件 (Entropy, Intel Events & Pure Self-Tests)
 */

(function(global, factory) {
  const req = typeof require === 'function' ? require : (global && global.require);
  const engine = factory(req);
  if (typeof exports === 'object' && typeof module !== 'undefined') {
    module.exports = engine;
  }
  if (typeof define === 'function' && define.amd) {
    define(function() { return engine; });
  }
  if (typeof globalThis !== 'undefined') {
    globalThis.AuctionEngineV06 = engine;
    Object.assign(globalThis, engine);
  }
  if (typeof window !== 'undefined') {
    window.AuctionEngineV06 = engine;
    Object.assign(window, engine);
  }
  if (typeof global !== 'undefined') {
    global.AuctionEngineV06 = engine;
    Object.assign(global, engine);
  }
}(typeof self !== 'undefined' ? self : this, function(req) {
  "use strict";

  // ==========================================
  // 1. 冻结图鉴快照与场地规则
  // ==========================================

  const PRE_0813_GOLD_ITEMS = [
    ["乔望尼金雕像",271827,"4x5"],["大饼",202798,"4x5"],["罐装随心泥",124816,"4x3"],["金龙鱼",111111,"4x1"],["条纹椰",101537,"4x3"],["片刻驻足",88888,"2x3"],["名为显赫的权杖",77777,"1x3"],["青花花瓶",62456,"1x4"],["万有星仪",51077,"5x5"],["浅绯祈手办",30264,"3x2"],
    ["海盐心迷宫",30211,"2x3"],["「强身好伙伴！」",27246,"1x5"],["轮椅模型",27159,"3x3"],["心猎铁骑L1-必杀一击",22847,"2x3"],["心猎铁骑L2-闪焰冲锋",22770,"2x3"],["絮语之种",22336,"2x3"],["心猎铁骑L3--以当千",22297,"2x3"],["万花筒",21012,"1x3"],["缠枝花纹筷",20238,"3x1"],["凝华海露",19926,"2x2"],
    ["「截云」",18288,"1x5"],["名为尊贵的冠冕",18193,"3x1"],["万能适配器",18031,"2x2"],["生春鞘",15309,"1x4"],["蓝焰火花塞",15108,"2x2"],["盈雪点翠",15037,"2x2"],["气象指南",15024,"3x1"],["骑士车贴",12164,"3x1"],["「方盒科技」电容笔",12116,"1x3"],["「方盒科技」充电宝",11981,"2x2"],
    ["自由数据线",11974,"3x1"],["绯红宝石",9938,"1x1"],["桂冠",7648,"1x1"],["大满贯手握",7610,"2x1"],["绒默花瓣",7547,"2x1"],["「方盒科技」智能手表",7500,"1x2"],["海星",5555,"1x1"],["第23页",5047,"1x1"],["光之方",5041,"1x1"],["落日珍珠",4975,"1x1"]
  ];
  const PRE_0813_PURPLE_ITEMS = [
    ["阿瑞斯跑步机",24180,"4x3"],["数码相机",18363,"3x2"],["寻星者望远镜",18317,"3x2"],["拈花小像",18075,"3x2"],["阿瑞斯动感单车",17847,"3x2"],["落雪水晶球",15257,"2x3"],["囿于窠巢",14934,"2x3"],["「方盒科技」平板",11038,"2x3"],["杯装日出",10743,"3x2"],["纳库佩达模型",10029,"2x2"],["留声机",9946,"2x2"],["智能笔筒",8177,"2x2"],["金角月芒",8128,"2x2"],["雀蓝簪",8065,"1x3"],["角斗士之歌",8019,"1x3"],["青花碗",7996,"2x2"],["奇异引火石",7639,"2x1"],["黄金薯饼",7463,"1x2"],["洄游的一旗",7225,"1x3"],["跳跳兔盒",7222,"2x2"],["「切玉」",6011,"2x1"],["半翼战队",6005,"1x3"],["红釉花瓶",5997,"1x2"],["「方盒科技」耳机",5997,"2x2"],["青釉花瓶",5959,"1x2"],["四角魔方",5955,"2x2"],["笼残羽",5096,"1x1"],["海水蓝",4590,"1x2"],["万能遥控器",4557,"2x1"],["随身感应灯",4484,"2x1"],["圣聆晶石",4481,"1x2"],["秋枫镇纸",3675,"2x1"],["大将军章鱼烧",3667,"2x1"],["双色冰棍",3666,"2x1"],["结的艺术",3652,"1x2"],["环的冥思",3644,"1x2"],["春花镇纸",3584,"1x2"],["饕目",3060,"1x1"],["蔚蓝旋律",3037,"1x1"],["月白沙",2441,"1x1"],["幽灵态",2040,"1x1"],["海中栗",2036,"1x1"],["霞红钻",2036,"1x1"],["焰火海鲜饭",2035,"1x1"],["压缩纸盒",2028,"1x1"],["炫彩扭蛋",2011,"1x1"],["棉花心",2001,"1x1"],["鎏金坠",1997,"1x1"],["弹性球",1992,"1x1"],["闪闪金平糖",1988,"1x1"]
  ];
  const PRE_0813_RED_ITEMS = [
    ["金锦鲤雕像",22668888,"4x4"],["Pendragon模型",20171210,"5x5"],["「永恒之心」",1314520,"1x1"],["古旧手提箱",577777,"3x2"],["未知门禁卡",366112,"3x2"],["白龙王",300000,"1x4"],["一簇幽火",260423,"3x2"],["九格小食",240208,"3x2"],["便携式折叠屏",239342,"3x2"],["永生花环",200201,"2x2"],["细颈莲纹瓶",101860,"1x3"],["莹碧翡翠",81088,"2x4"],["图特U盘",76008,"2x1"],["「几何」摆件",61803,"1x1"],["混沌谜核",61740,"1x1"],["K01模型",59440,"4x4"],["鲸歌",52000,"4x4"],["「泪滴」",50000,"1x1"],["「摇星」",31618,"2x2"],["酥酥酥天丼",29977,"2x1"]
  ];
  const PRE_0813_BLUE_ITEMS = [
    ["无梦果核",1012,"1x1"],["（未来的）大师飞镖",996,"1x1"],["复古暖灯",995,"1x1"],["噗卡好梦棉花糖",995,"1x1"],["毛茸茸的应答",993,"1x1"],["蓝釉瓶",1616,"1x1"],["漫画书",1114,"1x1"],["银铃",1094,"1x1"],["扭扭饼干",1021,"1x1"],["拳王的战意",1012,"1x1"],["VitalMax能量棒",1012,"1x1"],
    ["心猎铁骑L1-星影狩猎",3232,"1x2"],["心猎铁骑L2-获胜法则",2439,"1x2"],["心猎铁骑L3-骑士飞踢",2432,"1x2"],["断落的剑柄",2139,"1x2"],["Tayge空气清新剂",1795,"1x2"],["沸腾之火",1642,"1x2"],["专属客服",1632,"1x2"],
    ["灯塔",4034,"1x3"],["烟紫水晶",3987,"1x3"],["断落的剑刃",3665,"1x3"],["柠檬气泡水",2224,"1x3"],
    ["断落的剑格",2139,"2x1"],["棉绒绒手办",2101,"2x1"],["观蝶纪念章",2095,"2x1"],["清凉凉止痛药",1815,"2x1"],["复古圆桌",1682,"2x1"],
    ["「方盒科技」手机",8848,"2x2"],["鳞纹",3677,"2x2"],["觊觎钱币",3618,"2x2"],["番茄百分百果冻",3185,"2x2"],
    ["清晨的痛击",4843,"2x3"],["销魂挠挠爪",3598,"2x3"],["褪色谜",3351,"2x3"],["引航者望远镜",4840,"3x2"],["艺术画「深林」",6069,"3x3"],["失落的甲胄",3626,"3x3"],["涂鸦板",3502,"4x1"],["液晶视屏",8135,"4x3"],["绝对是亲手钓的鱼",9952,"5x5"]
  ];
  const PRE_0813_GREEN_ITEMS = [
    ["毛茸茸的肯定",813,"1x1"],["金月",610,"1x1"],["毛毛球",602,"1x1"],["几何灯",561,"1x1"],["炭火脆皮烤肉",557,"1x1"],["拍拍球",548,"1x1"],["肥皂",509,"1x1"],["金色飞球",498,"1x1"],["鎏金盏",496,"1x1"],
    ["「烘焙伴侣」抹茶粉",1353,"1x2"],["团三郎玩偶",1220,"1x2"],["断线之筝",1072,"1x2"],["千代家自酿生啤",1046,"1x2"],["一挥即碎的锈刀",1046,"1x2"],["梦中萤",918,"1x2"],["小小麻雀",911,"1x2"],["墨染瓶",909,"1x2"],
    ["游戏机",1216,"2x1"],["巡弋轮滑",1210,"2x1"],["多彩暴龙",1197,"2x1"],["斑斓的一尾",1070,"2x1"],["惠比寿宫廷小塔",1056,"2x1"],["轨道之心",1055,"2x1"],["吃薯片专用洗指机",1040,"2x1"],["炭烤青花鱼",893,"2x1"],
    ["「莲-C198」唱片机",1624,"2x2"],["黛绿花瓶",2993,"2x3"],["炫动三角铁",1822,"3x1"],["新口味上市！",2745,"3x3"],["M1000模型",4081,"4x4"]
  ];
  const PRE_0813_WHITE_ITEMS = [
    ["花雕碗",110,"1x1"],["扫晴微尘",110,"1x1"],["绵绵云",101,"1x1"],["酷辣辣辣条",100,"1x1"],["崭新的弹珠",100,"1x1"],["布妮果实",99,"1x1"],["劲爽「冰川」",99,"1x1"],["咕比奇原味薯片",99,"1x1"],["绿林",99,"1x1"],
    ["艺术画「花原」",241,"1x2"],["艺术画「解构」",240,"1x2"],["纸牌",183,"1x2"],["生鸡蛋",178,"1x2"],["床单",239,"1x3"],["锻刀石",167,"2x1"],["起司",366,"2x2"],["澄蓝之贝",356,"2x2"],["蟑螂！蟑螂！",278,"2x2"],["极点",277,"2x2"],["方盒随身听",611,"2x3"]
  ];

  const replaceCatalogItem = (items, name, next) => items.map(item => item[0] === name ? next : item);
  const GOLD_ITEMS = [
    ...replaceCatalogItem(replaceCatalogItem(PRE_0813_GOLD_ITEMS,"浅绯祈手办",["浅绯祈手办",30264,"3x3"]),"心猎铁骑L3--以当千",["心猎铁骑L3——以当千",22297,"2x3"]),
    ["算力面包",60040,"1x2"],["灿金环",38316,"1x2"],["黄釉雅器",13632,"1x2"],["澄空之眼",60285,"2x1"],["巡哨一干练精英",37558,"2x1"],["双颈玉瓶-白",80754,"2x2"],["赤色来电",101554,"4x4"],["猫丸秘制豚骨拉面",9040,"1x1"],["映像机",76591,"2x3"],["琉璃尾",101403,"4x1"]
  ];
  const PURPLE_ITEMS = PRE_0813_PURPLE_ITEMS.map(x=>[...x]);
  const RED_ITEMS = [
    ...replaceCatalogItem(replaceCatalogItem(PRE_0813_RED_ITEMS,"一簇幽火",["一簇幽火",260423,"3x3"]),"九格小食",["九格小食",240208,"3x3"]),
    ["酷辣辣辣条",280000,"1x2"],["他山之石",150051,"1x2"],["超级存储盘",5121024,"2x1"],["鸣佩",78800,"2x1"],["碧波天垂",11235813,"2x2"],["崭新限量排球",88600,"2x2"],["霜铁交响",80608,"2x3"],["咚咚锤",100000,"3x3"],["曜目权柄",288888,"5x1"],["储钱小啰",500001,"5x5"]
  ];
  const BLUE_ITEMS = replaceCatalogItem(PRE_0813_BLUE_ITEMS,"心猎铁骑L1-星影狩猎",["心猎铁骑L1-星影狩猎",3252,"1x2"]);
  const GREEN_ITEMS = replaceCatalogItem(PRE_0813_GREEN_ITEMS,"觊觎钱币",["凯飒钱币",3618,"2x2"]);
  const WHITE_ITEMS = PRE_0813_WHITE_ITEMS.map(x=>[...x]);

  const CATALOG_VERSION_PRE_0813 = "pre-2026-08-13";
  const CATALOG_VERSION_0813 = "2026-08-13";
  const CATALOG_SNAPSHOTS = {
    [CATALOG_VERSION_PRE_0813]: { gold: PRE_0813_GOLD_ITEMS, purple: PRE_0813_PURPLE_ITEMS, red: PRE_0813_RED_ITEMS, blue: PRE_0813_BLUE_ITEMS, green: PRE_0813_GREEN_ITEMS, white: PRE_0813_WHITE_ITEMS },
    [CATALOG_VERSION_0813]: { gold: GOLD_ITEMS, purple: PURPLE_ITEMS, red: RED_ITEMS, blue: BLUE_ITEMS, green: GREEN_ITEMS, white: WHITE_ITEMS }
  };
  const CATALOG_NAME_ALIASES = { "觊觎钱币": "凯飒钱币", "心猎铁骑L3--以当千": "心猎铁骑L3——以当千" };

  const FIELD_CONDITIONS = {
    unknown: { id: "unknown", name: "未知场地条件", goldMultiplier: 1, purpleMultiplier: 1, historyGroup: "unknown" },
    standard: { id: "standard", name: "标准对局", goldMultiplier: 1, purpleMultiplier: 1, historyGroup: "base" },
    dark: { id: "dark", name: "天黑了", goldMultiplier: 1, purpleMultiplier: 1, historyGroup: "base", hiddenBids: true },
    extraIntel: { id: "extraIntel", name: "一手情报", goldMultiplier: 1, purpleMultiplier: 1, historyGroup: "base", freeIntelRounds: [1, 3] },
    purpleDouble: { id: "purpleDouble", name: "加倍！！", goldMultiplier: 1, purpleMultiplier: 2, historyGroup: "purpleDouble" },
    goldDouble: { id: "goldDouble", name: "加倍！！！", goldMultiplier: 2, purpleMultiplier: 1, historyGroup: "goldDouble" },
    sparkle: { id: "sparkle", name: "闪耀之心", goldMultiplier: 1, purpleMultiplier: 1, historyGroup: "sparkle", sparkleEvidenceOnly: true },
    welfare: { id: "welfare", name: "福利多多", goldMultiplier: 1, purpleMultiplier: 1, historyGroup: "base", welfareRate: .30 },
    gemMaze: { id: "gemMaze", name: "宝石迷阵", goldMultiplier: 1, purpleMultiplier: 1, historyGroup: "base" }
  };

  const FIELD_CONDITION_ALIASES = {
    "": "unknown", "unknown": "unknown", "未知": "unknown",
    "standard": "standard", "标准": "standard", "标准对局": "standard",
    "dark": "dark", "天黑了": "dark",
    "extraIntel": "extraIntel", "extra_intel": "extraIntel", "first_intel": "extraIntel", "一手情报": "extraIntel",
    "purpleDouble": "purpleDouble", "purple_double": "purpleDouble", "紫色加倍": "purpleDouble", "加倍！！": "purpleDouble",
    "goldDouble": "goldDouble", "gold_double": "goldDouble", "金色加倍": "goldDouble", "加倍！！！": "goldDouble",
    "sparkle": "sparkle", "shining_heart": "sparkle", "闪耀之心": "sparkle",
    "welfare": "welfare", "福利多多": "welfare",
    "gemMaze": "gemMaze", "gem_maze": "gemMaze", "宝石迷阵": "gemMaze", "宝石迷宫": "gemMaze"
  };

  const SPARKLE_GEM_NAMES = ["「永恒之心」","「泪滴」","绯红宝石","桂冠","落日珍珠","饕目","月白沙","幽灵态","霞红钻","银铃","无梦果核","金月","肥皂","金色飞球","崭新的弹珠","绿林"];
  function sparkleEvidenceBounds(ctx = {}) {
    if (!conditionRules(ctx).sparkleEvidenceOnly) return null;
    const unavailable = reason => ({status:"invalid", reason, scope:"transformed-gems-only", probabilityKnown:false, recommendationAllowed:false, lower:null, upper:null});
    const integer = value => {
      if (typeof value === "string" && /^\d+$/.test(value.trim())) value = Number(value.trim());
      if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw Error("数量必须为非负整数");
      return value;
    };
    try {
      const input = ctx.sparkle ?? {};
      if (!input || typeof input !== "object" || Array.isArray(input)) return unavailable("证据格式无效");
      const count = input.transformedOneByOneCount == null || input.transformedOneByOneCount === "" ? null : integer(input.transformedOneByOneCount);
      const base = baseCatalogFor(ctx);
      const pool = Object.values(base).flat().filter(x => SPARKLE_GEM_NAMES.includes(x[0]) && x[2] === "1x1");
      if (!pool.length) return unavailable("没有可核验的宝石图鉴");
      const nameKey = name => String(name).trim().replace(/[「」]/g, "");
      const raw = input.verifiedGemItems ?? [];
      if (typeof raw !== "string" && !Array.isArray(raw)) return unavailable("已确认宝石格式无效");
      const tokens = Array.isArray(raw) ? raw : raw.split(/[+；;\n]/).map(x=>x.trim()).filter(Boolean);
      let knownCount = 0, knownTotal = 0;
      const knownItems = [];
      for (const token of tokens) {
        let name, copies = 1, suppliedPrice;
        if (typeof token === "string") {
          const match = token.trim().match(/^(.*?)(?:\*(\d+))?$/);
          name = match[1]; copies = match[2] == null ? 1 : integer(match[2]);
        } else if (token && typeof token === "object" && !Array.isArray(token)) {
          name = token.name; copies = token.count == null ? 1 : integer(token.count); suppliedPrice = token.price;
        } else return unavailable("请使用图鉴宝石名称");
        const item = typeof name === "string" ? pool.find(x=>nameKey(x[0])===nameKey(name)) : null;
        if (!item || copies < 1) return unavailable("名称不在1×1宝石池或重复数量无效");
        if (suppliedPrice !== undefined && suppliedPrice !== item[1]) return unavailable("价格与图鉴不一致");
        knownCount += copies; knownTotal += copies * item[1];
        if (!Number.isSafeInteger(knownCount) || !Number.isSafeInteger(knownTotal)) return unavailable("数量或价值超出精确计算范围");
        knownItems.push({name:item[0],count:copies,unitPrice:item[1]});
      }
      if (count !== null && knownCount > count) return unavailable("已确认件数超过转换总数");
      const unitMin = Math.min(...pool.map(x=>x[1])), unitMax = Math.max(...pool.map(x=>x[1]));
      const remaining = count === null ? null : count-knownCount;
      const lower = knownTotal + (remaining ?? 0) * unitMin;
      const upper = remaining === null ? null : knownTotal + remaining * unitMax;
      if (!Number.isSafeInteger(lower) || (upper !== null && !Number.isSafeInteger(upper))) return unavailable("价值超出精确计算范围");
      return {status:"valid",scope:"transformed-gems-only",probabilityKnown:false,recommendationAllowed:false,
        count,knownCount,knownTotal,knownItems,unitMin,unitMax,poolSize:pool.length,lower,upper};
    } catch (error) { return unavailable(error.message); }
  }

  function normalizeFieldCondition(value) {
    const raw = value && typeof value === "object" ? (value.id ?? value.name ?? value.type ?? value.value) : value;
    const key = FIELD_CONDITION_ALIASES[String(raw ?? "").trim()] || "unknown";
    return { ...FIELD_CONDITIONS[key], raw: raw ?? null };
  }

  function catalogVersionFor(ctx = {}) {
    const explicit = ctx.catalogVersion ?? ctx.catalog?.version;
    if (explicit && (CATALOG_SNAPSHOTS[explicit] || explicit === "unknown")) return explicit;
    if (ctx.legacy === true || /旧版本|旧版/.test(String(ctx.patch || ctx.productVersion || ""))) return CATALOG_VERSION_PRE_0813;
    const raw = ctx.playedAt ?? ctx.date;
    const stamp = raw ? Date.parse(String(raw).includes("T") ? String(raw) : String(raw).replace(" ", "T")) : NaN;
    if (Number.isFinite(stamp)) return stamp < Date.parse("2026-08-13T00:00:00+08:00") ? CATALOG_VERSION_PRE_0813 : CATALOG_VERSION_0813;
    return "unknown";
  }

  function conditionRules(ctx = {}) {
    return normalizeFieldCondition(ctx.fieldCondition ?? ctx.condition ?? ctx.fieldMode);
  }

  function baseCatalogFor(ctx = {}) {
    return CATALOG_SNAPSHOTS[catalogVersionFor(ctx)] || CATALOG_SNAPSHOTS[CATALOG_VERSION_0813];
  }

  function effectiveCatalog(ctx = {}) {
    const base = baseCatalogFor(ctx);
    const rules = conditionRules(ctx);
    const scale = (items, m) => items.map(x => [x[0], Number(x[1]) * m, x[2]]);
    return {
      version: catalogVersionFor(ctx),
      condition: rules,
      gold: scale(base.gold, rules.goldMultiplier),
      purple: scale(base.purple, rules.purpleMultiplier),
      red: scale(base.red, 1),
      blue: scale(base.blue, 1),
      green: scale(base.green, 1),
      white: scale(base.white, 1)
    };
  }

  // ==========================================
  // 2. 约束图分配与精细离散组合求解器
  // ==========================================

  function minimumConstraintAssignment(groups, items, repeat = 2) {
    const slots = [];
    for (const group of groups || []) {
      const prices = [...new Set((Array.isArray(group?.[0]) ? group[0] : []).map(Number).filter(Number.isFinite))];
      const required = Math.max(0, Math.trunc(Number(group?.[1]) || 0));
      for (let i = 0; i < required; i++) slots.push(prices);
    }
    if (!slots.length) return { feasible: true, floor: 0, assigned: 0, required: 0 };
    const catalogCapacity = new Map();
    for (const item of items || []) {
      const price = Number(item?.[1]);
      if (Number.isFinite(price)) catalogCapacity.set(price, (catalogCapacity.get(price) || 0) + repeat);
    }
    const priceList = [...new Set(slots.flat())].filter(price => catalogCapacity.has(price)).sort((a, b) => a - b);
    const source = 0, slotOffset = 1, priceOffset = slotOffset + slots.length, sink = priceOffset + priceList.length, nodeCount = sink + 1, graph = Array.from({ length: nodeCount }, () => []);
    const addEdge = (from, to, capacity, cost) => {
      const f = { to, rev: graph[to].length, capacity, cost }, r = { to: from, rev: graph[from].length, capacity: 0, cost: -cost };
      graph[from].push(f); graph[to].push(r);
    };
    slots.forEach((allowed, index) => {
      addEdge(source, slotOffset + index, 1, 0);
      const allowedSet = new Set(allowed);
      priceList.forEach((price, priceIndex) => {
        if (allowedSet.has(price)) addEdge(slotOffset + index, priceOffset + priceIndex, 1, price);
      });
    });
    priceList.forEach((price, index) => addEdge(priceOffset + index, sink, catalogCapacity.get(price) || 0, 0));
    let flow = 0, cost = 0;
    while (flow < slots.length) {
      const dist = Array(nodeCount).fill(Infinity), prevNode = Array(nodeCount).fill(-1), prevEdge = Array(nodeCount).fill(-1), queued = Array(nodeCount).fill(false), queue = [source];
      dist[source] = 0; queued[source] = true;
      for (let head = 0; head < queue.length; head++) {
        const node = queue[head]; queued[node] = false;
        graph[node].forEach((edge, index) => {
          if (edge.capacity <= 0 || dist[node] + edge.cost >= dist[edge.to]) return;
          dist[edge.to] = dist[node] + edge.cost;
          prevNode[edge.to] = node;
          prevEdge[edge.to] = index;
          if (!queued[edge.to]) { queued[edge.to] = true; queue.push(edge.to); }
        });
      }
      if (!Number.isFinite(dist[sink])) break;
      for (let node = sink; node !== source; node = prevNode[node]) {
        const edge = graph[prevNode[node]][prevEdge[node]];
        edge.capacity--;
        graph[node][edge.rev].capacity++;
      }
      flow++; cost += dist[sink];
    }
    return { feasible: flow === slots.length, floor: flow === slots.length ? cost : null, assigned: flow, required: slots.length };
  }

  function parseFlexibleKnown(raw, items, label, options = {}) {
    const text = String(raw || "").trim();
    if (!text || text === "0") return { known: [], groups: [], constraintCount: 0 };
    const multiplier = Math.max(1, Number(options.multiplier) || 1);
    const basis = ["base", "effective", "unknown"].includes(String(options.basis || "").toLowerCase()) ? String(options.basis).toLowerCase() : "unknown";
    const resolveItem = (part) => {
      const numeric = Number(String(part).replaceAll(",", ""));
      const canonical = CATALOG_NAME_ALIASES[part] || part;
      const named = items.find(x => x[0] === canonical || x[0] === part);
      if (named) return named;
      if (!Number.isFinite(numeric) || numeric <= 0) return null;
      const direct = items.find(x => Number(x[1]) === numeric);
      const effective = multiplier > 1 && Number.isInteger(numeric / multiplier) ? items.find(x => Number(x[1]) === numeric / multiplier) : null;
      if (basis === "effective") return effective || direct;
      if (basis === "base") return direct;
      return direct || effective;
    };
    const groups = [], known = [];
    const tokens = Array.isArray(raw) ? raw : String(raw || "").split(/[+；;\n,，]/);
    for (const tokenRaw of tokens.map(x => typeof x === "object" && x !== null ? String(x.name || x.price || "").trim() : String(x).trim()).filter(Boolean)) {
      const match = tokenRaw.match(/^(.*?)(?:\*(\d+))?$/);
      const key = match?.[1]?.trim(), count = match?.[2] ? Number(match[2]) : 1;
      if (!key || !Number.isInteger(count) || count < 1) throw new Error(`${label}已知藏品格式错误：${tokenRaw}`);
      const candidates = key.split("/").map(part => part.trim()).filter(Boolean);
      if (!candidates.length) throw new Error(`${label}已知藏品格式错误：${tokenRaw}`);
      let singleResolvedItem = null;
      const prices = [...new Set(candidates.map(part => {
        const item = resolveItem(part);
        if (!item) throw new Error(`${label}图鉴中找不到：${part}`);
        if (candidates.length === 1) singleResolvedItem = item;
        return Number(item[1]);
      }))].sort((a, b) => a - b);
      groups.push([prices, count]);
      if (prices.length === 1) {
        const item = singleResolvedItem || items.find(x => Number(x[1]) === prices[0]);
        for (let i = 0; i < count; i++) known.push({ name: item[0], price: Number(item[1]), size: item[2] });
      }
    }
    const assignment = minimumConstraintAssignment(groups, items, 2);
    if (!assignment.feasible) throw new Error(`${label}约束需要 ${assignment.required} 件独立藏品，但候选价格在 repeat=2 下只能分配 ${assignment.assigned} 件`);
    return { known, groups, constraintCount: groups.reduce((sum, x) => sum + Number(x[1] || 0), 0), constraintFloor: assignment.floor, inputBasis: basis, multiplier };
  }

  function parseOr(raw, options = {}) { return parseFlexibleKnown(raw, GOLD_ITEMS, "金色", options).groups; }
  function parseKnownItems(raw, items, label, options = {}) { return parseFlexibleKnown(raw, items, label, options).known; }

  // The old component evaluator consumes objects, while exact search and the
  // audit snapshot consume the original expression. Keep both representations.
  function normalizeKnownContext(raw = {}) {
    const ctx = { ...raw }, catalog = baseCatalogFor(ctx), rules = conditionRules(ctx);
    for (const [rarity, title] of [["gold", "金色"], ["purple", "紫色"], ["red", "红色"]]) {
      const key = `known${rarity[0].toUpperCase()}${rarity.slice(1)}`;
      const input = ctx[`${key}Raw`] ?? ctx[key] ?? "";
      const expression = Array.isArray(input) ? input.map(x => typeof x === "object" && x !== null ? String(x.name || x.price || "") : String(x)).filter(Boolean).join("+") : String(input).trim();
      const multiplier = rarity === "gold" ? rules.goldMultiplier : rarity === "purple" ? rules.purpleMultiplier : 1;
      const parsed = parseFlexibleKnown(expression, catalog[rarity], title, { basis: ctx.avgValueBasis, multiplier });
      ctx[`${key}Raw`] = expression;
      ctx[key] = parsed.known;
      ctx[`${rarity}Groups`] = parsed.groups;
      ctx[`${key}Groups`] = parsed.groups.map(([prices, count]) => [prices.map(p => p * multiplier), count]);
    }
    return ctx;
  }

  function validateKnownInput(raw = {}) {
    const ctx = normalizeKnownContext(raw), catalog = baseCatalogFor(ctx);
    for (const rarity of ["blue", "green", "white"]) {
      const key = `known${rarity[0].toUpperCase()}${rarity.slice(1)}`;
      try { lowIdentityGroups(ctx[key], catalog[rarity]); }
      catch (_) { throw new Error("请填写图鉴中的名称或价格；重复数量必须是正整数"); }
    }
    return ctx;
  }

  const INF = Number.POSITIVE_INFINITY, NEG = Number.NEGATIVE_INFINITY;
  function bounds(avg, count, mode) {
    const floor = [count * avg, count * (avg + 1) - 1];
    const near = [Math.ceil(count * (avg - .5)), Math.ceil(count * (avg + .5)) - 1];
    if (mode === 'floor') return floor;
    if (mode === 'nearest') return near;
    return [Math.min(floor[0], near[0]), Math.max(floor[1], near[1])];
  }

  function tables(prices, maxCount, repeat) {
    const m = prices.length, mn = Array.from({ length: m + 1 }, () => Array(maxCount + 1).fill(INF)), mx = Array.from({ length: m + 1 }, () => Array(maxCount + 1).fill(NEG));
    mn[m][0] = mx[m][0] = 0;
    for (let i = m - 1; i >= 0; i--) {
      mn[i][0] = mx[i][0] = 0;
      for (let need = 1; need <= maxCount; need++) {
        for (let take = 0; take <= Math.min(Array.isArray(repeat) ? repeat[i] : repeat, need); take++) {
          const rem = need - take;
          if (mn[i + 1][rem] !== INF) mn[i][need] = Math.min(mn[i][need], take * prices[i] + mn[i + 1][rem]);
          if (mx[i + 1][rem] !== NEG) mx[i][need] = Math.max(mx[i][need], take * prices[i] + mx[i + 1][rem]);
        }
      }
    }
    return [mn, mx];
  }

  function jointTables(prices, grids, maxCount, maxGrid, repeat) {
    const m = prices.length;
    const mn = Array.from({ length: m + 1 }, () => Array.from({ length: maxCount + 1 }, () => { const row = new Float64Array(maxGrid + 1); row.fill(INF); return row; }));
    const mx = Array.from({ length: m + 1 }, () => Array.from({ length: maxCount + 1 }, () => { const row = new Float64Array(maxGrid + 1); row.fill(NEG); return row; }));
    mn[m][0][0] = mx[m][0][0] = 0;
    for (let i = m - 1; i >= 0; i--) {
      const price = prices[i], grid = grids[i];
      for (let need = 0; need <= maxCount; need++) {
        for (let cells = 0; cells <= maxGrid; cells++) {
          for (let take = 0; take <= Math.min(repeat, need); take++) {
            const usedGrid = take * grid;
            if (usedGrid > cells) break;
            const remNeed = need - take, remGrid = cells - usedGrid;
            if (mn[i + 1][remNeed][remGrid] !== INF) mn[i][need][cells] = Math.min(mn[i][need][cells], take * price + mn[i + 1][remNeed][remGrid]);
            if (mx[i + 1][remNeed][remGrid] !== NEG) mx[i][need][cells] = Math.max(mx[i][need][cells], take * price + mx[i + 1][remNeed][remGrid]);
          }
        }
      }
    }
    return [mn, mx];
  }

  function groupsSatisfiedWithCapacity(combo, groups) {
    const slots = [];
    for (const group of groups || []) {
      const allowed = new Set(group[0] || []);
      const required = Math.max(0, Math.trunc(Number(group[1]) || 0));
      for (let i = 0; i < required; i++) slots.push(allowed);
    }
    if (!slots.length) return true;
    if (slots.length > combo.length) return false;
    slots.sort((a, b) => a.size - b.size);
    const owner = Array(combo.length).fill(-1);
    function match(slotIdx, visited) {
      const allowed = slots[slotIdx];
      for (let i = 0; i < combo.length; i++) {
        if (!allowed.has(combo[i]) || visited[i]) continue;
        visited[i] = true;
        if (owner[i] === -1 || match(owner[i], visited)) {
          owner[i] = slotIdx;
          return true;
        }
      }
      return false;
    }
    for (let s = 0; s < slots.length; s++) {
      const visited = Array(combo.length).fill(false);
      if (!match(s, visited)) return false;
    }
    return true;
  }

  function purpleValueForState(state, ctx = {}, cat = null) {
    const effectiveCat = cat || effectiveCatalog(ctx);
    const p = Number.isInteger(Number(state?.P)) && Number(state?.P) >= 0 ? Number(state.P) : 0;
    if (p === 0) {
      return { mid: 0, lower: 0, source: "purple_count_zero" };
    }

    const purpleItems = effectiveCat.purple || [];
    const parsed = ctx.knownPurple ? parseFlexibleKnown(ctx.knownPurple, purpleItems, "紫色", { basis: ctx.avgValueBasis, multiplier: effectiveCat.condition.purpleMultiplier }) : { known: [] };
    const knownItems = parsed.known || parsed.items || [];
    const knownTotal = knownItems.reduce((sum, item) => sum + Number(item.price || 0), 0);
    const knownCount = Math.min(p, knownItems.length);

    const purplePrices = purpleItems.map(x => Number(x[1])).filter(v => Number.isFinite(v) && v > 0);
    const poolMean = purplePrices.length > 0 ? (purplePrices.reduce((a, b) => a + b, 0) / purplePrices.length) : 6968;

    const remainingCount = Math.max(0, p - knownCount);
    const mid = knownTotal + remainingCount * poolMean;
    const lower = knownTotal;

    return {
      mid: Math.round(mid),
      lower: Math.round(lower),
      knownCount,
      remainingCount,
      source: knownCount === p ? "known_purple_total" : knownCount > 0 ? "known_purple_plus_catalog_mean" : "catalog_mean_prior"
    };
  }

  function redValueForState(state, ctx = {}, cat = null) {
    const effectiveCat = cat || effectiveCatalog(ctx);
    const r = Number.isInteger(Number(state?.R)) && Number(state?.R) >= 0 ? Number(state.R) : 0;
    if (r === 0) {
      return { mid: 0, lower: 0, source: "red_count_zero" };
    }

    const redItems = effectiveCat.red || [];
    const parsed = ctx.knownRed ? parseFlexibleKnown(ctx.knownRed, redItems, "红色") : { known: [] };
    const knownItems = parsed.known || parsed.items || [];
    const knownTotal = knownItems.reduce((sum, item) => sum + Number(item.price || 0), 0);
    const knownCount = Math.min(r, knownItems.length);

    const commonPrices = redItems.map(x => Number(x[1])).filter(v => Number.isFinite(v) && v > 0 && v < 400000).sort((a, b) => a - b);
    const workingPrior = commonPrices.length > 0 ? commonPrices[Math.floor(commonPrices.length / 2)] : 88600;

    const remainingCount = Math.max(0, r - knownCount);
    const rawR = ctx.redCount ?? ctx.red ?? ctx.r;
    const isLocked = rawR !== undefined && rawR !== null && rawR !== "" && Number.isInteger(Number(rawR));

    let unknownRedMid = 0;
    if (isLocked) {
      // 0.6 语义：当 redCount 锁定时，已知红货之外的剩余红货按线性图鉴中位计价
      unknownRedMid = remainingCount * workingPrior;
    } else {
      // 0.6 语义：当 redCount 未锁定时（纯 candidate 状态），后续红货快速衰减 (0.24^(i-1))，防止大 R 高估
      for (let i = 1; i <= remainingCount; i++) {
        unknownRedMid += workingPrior * Math.pow(0.24, i - 1);
      }
    }

    const mid = knownTotal + unknownRedMid;
    const lower = knownTotal;

    return {
      mid: Math.round(mid),
      lower: Math.round(lower),
      knownCount,
      remainingCount,
      isLocked,
      source: knownCount === r ? "known_red_total" : isLocked ? "locked_red_linear_prior" : "unlocked_red_soft_attenuation"
    };
  }

  const LOW_TIER_ITEM_RATE = { blue: 2954, green: 1189, white: 203 };
  const LOW_TIER_GRID_RATE = { blue: 809, green: 452, white: 92 };
  const LOW_TIER_PRIOR = {
    "初级场 · 海贝场": 8000,
    "中级场 · 珊瑚场": 12000,
    "高级场 · 真珠场": 30000,
    "未知场地": 12000,
    "chuji": 8000,
    "zhongji": 12000,
    "gaoji": 30000,
    "dingji": 30000,
    "shanhu": 12000,
    "milin": 30000,
    "baiye": 30000,
    "haimo": 30000
  };

  function hasNumber(v) {
    return v !== null && v !== undefined && v !== "" && !Number.isNaN(Number(v));
  }

  function lowTierValue(ctx = {}) {
    const pi = ctx.publicInfo || ctx;
    const venueKey = String(ctx.venueTier || ctx.venue || pi.venue || "未知场地").trim();
    const venuePrior = LOW_TIER_PRIOR[venueKey] ?? (LOW_TIER_PRIOR[venueKey.split(" ")[0]] ?? 12000);

    const parts = [];
    const exactParts = [];
    const breakdown = { blue: 0, green: 0, white: 0, residual: 0 };
    let observedColors = 0;

    for (const [key, label, rateGrid, rateItem] of [
      ["blue", "蓝", LOW_TIER_GRID_RATE.blue, LOW_TIER_ITEM_RATE.blue],
      ["green", "绿", LOW_TIER_GRID_RATE.green, LOW_TIER_ITEM_RATE.green],
      ["white", "白", LOW_TIER_GRID_RATE.white, LOW_TIER_ITEM_RATE.white]
    ]) {
      const countRaw = pi[key + "Count"] ?? ctx[key + "Count"];
      const gridRaw = pi[key + "Grid"] ?? ctx[key + "Grid"];
      const avgRaw = pi[key + "Avg"] ?? ctx[key + "Avg"];
      const count = hasNumber(countRaw) ? Number(countRaw) : null;
      const grid = hasNumber(gridRaw) ? Number(gridRaw) : null;
      const avg = hasNumber(avgRaw) ? Number(avgRaw) : null;

      if (count !== null && count >= 0 && avg !== null && avg > 0) {
        const val = Math.round(count * avg);
        parts.push(val);
        exactParts.push(val);
        breakdown[key] = val;
        observedColors++;
        continue;
      }
      if (grid !== null && grid >= 0) {
        const val = Math.round(grid * rateGrid);
        parts.push(val);
        breakdown[key] = val;
        observedColors++;
        continue;
      }
      if (count !== null && count >= 0) {
        const val = Math.round(count * rateItem);
        parts.push(val);
        breakdown[key] = val;
        observedColors++;
        continue;
      }
    }

    let direct = parts.length ? parts.reduce((a, b) => a + b, 0) : null;
    const totalItems = hasNumber(pi.totalItems) ? Number(pi.totalItems) : (hasNumber(ctx.totalItems) ? Number(ctx.totalItems) : null);
    const q = hasNumber(ctx.q) ? Number(ctx.q) : (hasNumber(pi.q) ? Number(pi.q) : null);
    const knownLow = [pi.blueCount ?? ctx.blueCount, pi.greenCount ?? ctx.greenCount, pi.whiteCount ?? ctx.whiteCount].filter(hasNumber).map(Number).reduce((a, b) => a + b, 0);

    const totalGrid = hasNumber(pi.totalGrid) ? Number(pi.totalGrid) : (hasNumber(ctx.totalGrid) ? Number(ctx.totalGrid) : null);
    const usedGrid = [pi.goldGrid ?? ctx.goldGrid, pi.purpleGrid ?? ctx.purpleGrid, pi.blueGrid ?? ctx.blueGrid, pi.greenGrid ?? ctx.greenGrid, pi.whiteGrid ?? ctx.whiteGrid].filter(hasNumber).map(Number).reduce((a, b) => a + b, 0);
    const singleAvg = hasNumber(pi.singleAvg) ? Number(pi.singleAvg) : (hasNumber(ctx.singleAvg) ? Number(ctx.singleAvg) : null);
    const nineAvg = hasNumber(pi.nineAvg) ? Number(pi.nineAvg) : (hasNumber(ctx.nineAvg) ? Number(ctx.nineAvg) : null);

    if (totalItems !== null && q !== null && totalItems >= q) {
      const remaining = Math.max(0, totalItems - q - knownLow);
      const pooled = (40 * LOW_TIER_ITEM_RATE.blue + 30 * LOW_TIER_ITEM_RATE.green + 20 * LOW_TIER_ITEM_RATE.white) / 90;
      const remVal = Math.round(remaining * pooled);
      breakdown.residual = remVal;
      direct = (direct ?? 0) + remVal;
    } else if (direct !== null && observedColors < 3) {
      const unobservedPrior = Math.round(venuePrior * ((3 - observedColors) / 3) * 0.55);
      breakdown.residual = unobservedPrior;
      direct += unobservedPrior;
    }

    if (singleAvg !== null && totalGrid !== null) {
      const restGrid = Math.max(0, totalGrid - usedGrid);
      const gridResidual = restGrid > 0 ? (restGrid * singleAvg * 0.55) : (totalGrid * singleAvg * 0.12);
      direct = direct === null ? Math.round(gridResidual) : Math.round(Math.max(direct, direct * 0.65 + gridResidual * 0.35));
    } else if (nineAvg !== null) {
      const weak = nineAvg * 1.1;
      direct = direct === null ? Math.round(Math.min(venuePrior * 1.3, weak)) : Math.round(direct * 0.8 + Math.min(weak, venuePrior * 1.5) * 0.2);
    }

    const base = direct ?? venuePrior;
    const hardLower = exactParts.reduce((a, b) => a + b, 0);

    const source = direct !== null
      ? (exactParts.length ? "low_tier_count_and_avg" : (totalItems !== null && totalItems >= q ? "low_tier_total_items_residual" : "low_tier_rates"))
      : "venue_low_tier_prior";

    return {
      mid: Math.round(Math.max(0, base)),
      lower: Math.round(Math.max(0, hardLower)),
      source,
      breakdown,
      observedColors
    };
  }

  // Match required known-price slots to distinct physical copies, then fill
  // the remaining count/area with bounded catalog copies (same repeat cap as gold).
  function lowIdentityGroups(raw,items) {
    const tokens=Array.isArray(raw)?raw:String(raw??"").split(/[+；;\n]/);
    const groups=[];
    for(const value of tokens) {
      const token=String(value && typeof value==="object" ? value.name ?? value.price ?? "" : value).trim();
      if(!token) continue;
      const match=token.match(/^(.*?)(?:\*(\d+))?$/),count=match?.[2]?Number(match[2]):1;
      if(!match?.[1] || !Number.isSafeInteger(count) || count<1) throw new Error("Invalid known low-tier item");
      const indexes=new Set();
      for(const candidate of match[1].split("/")) {
        const name=candidate.trim(),canonical=CATALOG_NAME_ALIASES[name]||name;
        const named=items.findIndex(x=>x[0]===canonical);
        if(named>=0) { indexes.add(named); continue; }
        const price=Number(name.replaceAll(",",""));
        const matches=Number.isFinite(price)&&price>0?items.map((x,i)=>x[1]===price?i:-1).filter(i=>i>=0):[];
        if(!matches.length) throw new Error("Unknown low-tier catalog item");
        for(const i of matches) indexes.add(i);
      }
      groups.push([[...new Set([...indexes].map(i=>items[i][1]))],count,[...indexes]]);
    }
    return groups;
  }

  function catalogGridPossible(items, count, target, groups, priceRange = null, repeatLimit = 2) {
    if (!Number.isInteger(count) || count < 0 || target < 0) return false;
    const area = items.map(x => String(x[2]).split("x").map(Number).reduce((a,b)=>a*b,1));
    const slots = [];
    for (const [prices, n, indexes] of groups) for (let i=0;i<n;i++)
      slots.push({prices:new Set(prices),indexes:indexes?new Set(indexes):null});
    if (slots.length > count) return false;
    const used = items.map(()=>0), failed = new Set();
    function assign(slot, sum, price) {
      if (target !== null && sum > target) return false;
      const key = slot+":"+used.join(",");
      if (failed.has(key)) return false;
      if (slot === slots.length) {
        const remaining = count-slot, need=target === null ? null : target-sum;
        if (priceRange !== null) {
          const prices=items.map(x=>x[1]), capacities=used.map(n=>repeatLimit-n);
          const [minPrice,maxPrice]=tables(prices,remaining,capacities);
          const [minArea,maxArea]=tables(area,remaining,capacities);
          const misses=new Set();
          function fill(index,n,cells,value) {
            if (n===0) return (need===null || cells===need) && value>=priceRange[0] && value<=priceRange[1];
            if (index>=items.length || value+minPrice[index][n]>priceRange[1] || value+maxPrice[index][n]<priceRange[0]) return false;
            if (need!==null && (cells+minArea[index][n]>need || cells+maxArea[index][n]<need)) return false;
            const stamp=[index,n,cells,value].join(":");if(misses.has(stamp))return false;
            for(let take=Math.min(n,capacities[index]);take>=0;take--)
              if(fill(index+1,n-take,cells+take*area[index],value+take*prices[index])) return true;
            misses.add(stamp);return false;
          }
          return fill(0,remaining,0,price);
        }
        if (need === null) return remaining <= used.reduce((sum,n)=>sum+repeatLimit-n,0);
        let sums=Array.from({length:remaining+1},()=>new Set());sums[0].add(0);
        for(let j=0;j<items.length;j++) for(let copy=used[j];copy<repeatLimit;copy++)
          for(let n=remaining;n>=1;n--) for(const previous of sums[n-1])
            if(previous+area[j]<=need) sums[n].add(previous+area[j]);
        return sums[remaining].has(need);
      }
      for(let j=0;j<items.length;j++) if(used[j]<repeatLimit && (slots[slot].indexes ? slots[slot].indexes.has(j) : slots[slot].prices.has(items[j][1]))) {
        used[j]++;
        const ok=assign(slot+1,sum+area[j],price+items[j][1]);
        used[j]--;
        if(ok) return true;
      }
      failed.add(key);return false;
    }
    return assign(0,0,0);
  }

  function solveExactStatesSync(ctx = {}) {
    const cat = effectiveCatalog(ctx);
    const goldItems = cat.gold;
    const purpleItems = cat.purple;
    const redItems = cat.red;

    const goldPrices = goldItems.map(x => x[1]);
    const goldGrids = goldItems.map(x => { const [w, h] = String(x[2]).split("x").map(Number); return (w || 0) * (h || 0); });

    const q = Number(ctx.q) || 0;
    const avg = Number(ctx.avg ?? ctx.goldAvg) || 0;
    const rounding = ctx.roundingMode || "floor";
    const gridInput = ctx.publicInfo?.goldGrid ?? ctx.goldGrid;
    const totalInput = ctx.publicInfo?.totalGrid ?? ctx.totalGrid ?? ctx.totalGrids;
    const parseGrid = value => value == null || value === "" ? null :
      (typeof value !== "boolean" && Number.isInteger(Number(value)) && Number(value) >= 0 ? Number(value) : NaN);
    const goldGrid = parseGrid(gridInput), totalGrids = parseGrid(totalInput);
    const purpleGrid = parseGrid(ctx.publicInfo?.purpleGrid ?? ctx.purpleGrid);
    const purpleAvg = parseGrid(ctx.purpleAvg);
    if (Number.isNaN(goldGrid) || Number.isNaN(totalGrids) || Number.isNaN(purpleGrid) || Number.isNaN(purpleAvg)) return {states:[],solverStatus:"no-match",candidateGs:[],candidatePs:[]};

    const detail = key => parseGrid(ctx.publicInfo?.[key] ?? ctx[key]);
    const totalItems = detail("totalItems"), redGrid = detail("redGrid");
    const low = ["blue", "green", "white"].map(color => ({color,count:detail(color+"Count"),grid:detail(color+"Grid"),avg:detail(color+"Avg")}));
    const invalid = value => Number.isNaN(value);
    const noMatch = () => ({states:[],solverStatus:"no-match",candidateGs:[],candidatePs:[]});
    try {
      for(const item of low) {
        const key="known"+item.color[0].toUpperCase()+item.color.slice(1);
        item.groups=lowIdentityGroups(ctx[key] ?? ctx.publicInfo?.[key],cat[item.color]);
        item.minimum=item.groups.reduce((n,g)=>n+g[1],0);
        if(item.count!==null && item.count<item.minimum) return noMatch();
      }
    } catch (_) { return noMatch(); }

    if (invalid(totalItems) || invalid(redGrid) || low.some(x => invalid(x.count) || invalid(x.grid) || invalid(x.avg))) return noMatch();
    if (low.some(x => x.grid !== null && x.count !== null &&
        (x.grid < x.count || (x.count === 0 && x.grid !== 0)))) return noMatch();
    const knownLowCount = low.reduce((sum,x)=>sum+(x.count ?? x.minimum),0);
    if (totalItems !== null && (totalItems < q+knownLowCount ||
        (low.every(x=>x.count!==null) && totalItems !== q+knownLowCount))) return noMatch();
    if (totalItems !== null && totalItems === q+knownLowCount) {
      for (const item of low) if (item.count === null) item.count = item.minimum;
      if (low.some(x=>x.count===0 && x.grid!==null && x.grid!==0)) return noMatch();
    }
    const lowCountDomains = [];
    for (const item of low) {
      const minArea = Math.min(...cat[item.color].map(x => String(x[2]).split("x").map(Number).reduce((a,b)=>a*b,1)));
      let maximum = item.count;
      if (maximum === null && totalItems !== null) maximum = totalItems-q-knownLowCount+item.minimum;
      if (item.grid !== null) maximum = Math.min(maximum ?? Infinity, Math.floor(item.grid/minArea));
      if (maximum === null && totalGrids !== null) maximum = Math.floor(totalGrids/minArea);
      // Without a finite count bound, retain uncertainty rather than invent
      // a maximum quantity or turn a guessed count into an observation.
      if (maximum === null) { lowCountDomains.push(null); continue; }
      const possible = [];
      for (let count=item.count ?? item.minimum; count<=maximum; count++) {
        if (count===0) {
          if ((item.grid===null || item.grid===0) && (item.avg===null || item.avg===0)) possible.push(0);
        } else if ((item.grid===null && item.avg===null && !item.groups.length) ||
            catalogGridPossible(cat[item.color],count,item.grid,item.groups,
              item.avg===null ? null : bounds(item.avg,count,rounding),count)) possible.push(count);
      }
      if (!possible.length) return noMatch();
      lowCountDomains.push(possible);
    }
    if (totalItems !== null) {
      const target=totalItems-q;
      let sums=new Set([0]);
      for (const domain of lowCountDomains) {
        const next=new Set();
        for (const sum of sums) for (const count of domain) if (sum+count<=target) next.add(sum+count);
        sums=next;
      }
      if (!sums.has(target)) return noMatch();
    }
    let lowCountAreaSums = null;
    function lowJointAreaPossible(targetArea) {
      if (lowCountAreaSums === null) {
        let combined = new Set(["0:0"]);
        for (let index=0;index<low.length;index++) {
          const item=low[index],counts=lowCountDomains[index],items=cat[item.color];
          const sizes=[...new Set(items.map(x=>String(x[2]).split("x").map(Number).reduce((a,b)=>a*b,1)))];
          const maxCount=Math.max(...counts),reachable=Array.from({length:maxCount+1},()=>new Set());
          reachable[0].add(0);
          for(let n=1;n<=maxCount;n++) for(const cells of reachable[n-1]) for(const size of sizes)
            if(cells+size<=totalGrids) reachable[n].add(cells+size);
          const options=[];
          for(const count of counts) for(const cells of reachable[count]) {
            if(item.grid!==null && cells!==item.grid) continue;
            if((item.avg!==null || item.groups.length) && count>0 && !catalogGridPossible(items,count,cells,item.groups,item.avg===null?null:bounds(item.avg,count,rounding),count)) continue;
            options.push([count,cells]);
          }
          const next=new Set();
          for(const stamp of combined) {
            const [n,cells]=stamp.split(":").map(Number);
            for(const [addN,addArea] of options)
              if(cells+addArea<=totalGrids && (totalItems===null || n+addN<=totalItems-q)) next.add((n+addN)+":"+(cells+addArea));
          }
          combined=next;
        }
        lowCountAreaSums=combined;
      }
      for(const stamp of lowCountAreaSums) {
        const [n,area]=stamp.split(":").map(Number);
        if(area===targetArea && (totalItems===null || n===totalItems-q)) return true;
      }
      return false;
    }
    const highAreaCache = new Map();
    function highAreaDomain(color,count,explicit,groups,average) {
      const key=color+":"+count;
      if(highAreaCache.has(key)) return highAreaCache.get(key);
      const items=cat[color],sizes=items.map(x=>String(x[2]).split("x").map(Number).reduce((a,b)=>a*b,1));
      const from=explicit ?? count*Math.min(...sizes),to=explicit ?? Math.min(totalGrids,count*Math.max(...sizes));
      const domain=[];
      for(let area=from;area<=to;area++)
        if(catalogGridPossible(items,count,area,groups,average===null?null:bounds(average,count,rounding))) domain.push(area);
      highAreaCache.set(key,domain);return domain;
    }
    function wholeGridPossible(goldArea, P, R) {
      if ((P === 0 && purpleGrid !== null && purpleGrid !== 0) ||
          (purpleGrid !== null && purpleGrid < P) ||
          (R === 0 && redGrid !== null && redGrid !== 0) ||
          (redGrid !== null && redGrid < R)) return false;
      if (totalGrids === null) return true;
      const areas = [goldArea, purpleGrid ?? (P === 0 ? 0 : null), redGrid ?? (R === 0 ? 0 : null),
                     ...low.map(x=>x.grid ?? (x.count === 0 ? 0 : null))];
      const minimum = goldArea+(purpleGrid ?? P)+(redGrid ?? R)+
        low.reduce((sum,x)=>sum+(x.grid ?? x.count ?? 0),0);
      if (minimum > totalGrids || (totalItems !== null && totalItems > totalGrids)) return false;
      const purpleAreas=highAreaDomain("purple",P,purpleGrid,purpleGroups,purpleAvg);
      const redAreas=highAreaDomain("red",R,redGrid,redGroups,null);
      for(const pa of purpleAreas) for(const ra of redAreas) {
        const remaining=totalGrids-goldArea-pa-ra;
        if(remaining>=0 && lowJointAreaPossible(remaining)) return true;
      }
      return false;
    }

    const goldGroups = ctx.knownGoldGroups || (ctx.knownGold ? parseOr(ctx.knownGold, { basis: ctx.avgValueBasis, multiplier: cat.condition.goldMultiplier }) : []);
    const purpleGroups = ctx.knownPurpleGroups || (ctx.knownPurple ? parseFlexibleKnown(ctx.knownPurple, purpleItems, "紫色", { basis: ctx.avgValueBasis, multiplier: cat.condition.purpleMultiplier }).groups : []);
    const redGroups = ctx.knownRedGroups || (ctx.knownRed ? parseFlexibleKnown(ctx.knownRed, redItems, "红色").groups : []);

    const states = [];
    if (!q || !avg) return { states: [], solverStatus: "incomplete", candidateGs: [], candidatePs: [] };

    const minGoldKnown = goldGroups.reduce((s, g) => s + (g[1] || 0), 0);
    const minGold = Math.max(minGoldKnown, Number(ctx.minGold) || 0);

    const minPKnown = purpleGroups.reduce((s, g) => s + (g[1] || 0), 0);
    const minP = Math.max(minPKnown, Number(ctx.minPurple) || 0);

    const minRKnown = redGroups.reduce((s, g) => s + (g[1] || 0), 0);
    const minRed = Math.max(minRKnown, Number(ctx.minRed) || 0);

    const rawP = ctx.p ?? ctx.purple ?? ctx.purpleCount;
    const explicitP = rawP !== undefined && rawP !== null && rawP !== "" && Number.isInteger(Number(rawP)) ? Number(rawP) : null;

    const rawG = ctx.goldCount ?? ctx.g;
    const explicitG = rawG !== undefined && rawG !== null && rawG !== "" && Number.isInteger(Number(rawG)) ? Number(rawG) : null;

    const rawR = ctx.redCount ?? ctx.red ?? ctx.r;
    const explicitR = rawR !== undefined && rawR !== null && rawR !== "" && Number.isInteger(Number(rawR)) ? Number(rawR) : null;

    // Explicit constraint validation
    if (explicitP !== null && explicitP < minP) return { states: [], solverStatus: "no-match", candidateGs: [], candidatePs: [] };
    if (explicitG !== null && explicitG < minGold) return { states: [], solverStatus: "no-match", candidateGs: [], candidatePs: [] };
    if (explicitR !== null && explicitR < minRed) return { states: [], solverStatus: "no-match", candidateGs: [], candidatePs: [] };

    const pCandidates = explicitP !== null ? [explicitP] : Array.from({ length: q + 1 }, (_, i) => i).filter(p => p >= minP);
    const lowTierComp = lowTierValue(ctx);

    // Reserve mandatory single-price clues before enumerating the remainder.
    // Testing them only at a leaf explores millions of impossible combinations.
    const mandatory = new Map();
    for (const [prices, count] of goldGroups) {
      if (prices.length === 1) mandatory.set(prices[0], (mandatory.get(prices[0]) || 0) + count);
    }
    const remainingMandatory = new Map(mandatory), seed = [];
    let seedGrid = 0;
    const capacities = goldPrices.map((price, index) => {
      const reserved = Math.min(2, remainingMandatory.get(price) || 0);
      remainingMandatory.set(price, (remainingMandatory.get(price) || 0) - reserved);
      seedGrid += reserved * goldGrids[index];
      for (let i = 0; i < reserved; i++) seed.push(price);
      return 2 - reserved;
    });
    if ([...remainingMandatory.values()].some(n => n > 0)) return { states: [], solverStatus: "no-match", candidateGs: [], candidatePs: [] };
    const seedSum = seed.reduce((sum, price) => sum + price, 0);

    for (const P of pCandidates) {
      if ((purpleGrid !== null || purpleAvg !== null) &&
          !catalogGridPossible(purpleItems, P, purpleGrid, purpleGroups, purpleAvg === null ? null : bounds(purpleAvg,P,rounding))) continue;
      const maxGold = q - P;
      const gMin = Math.max(1, minGold);
      const gList = explicitG !== null ? [explicitG].filter(g => g >= gMin && g <= maxGold) : Array.from({ length: maxGold - gMin + 1 }, (_, i) => gMin + i);

      for (const G of gList) {
        const R = q - P - G;
        if (R < minRed) continue;
        if (explicitR !== null && R !== explicitR) continue;

        const b = bounds(avg, G, rounding);
        const remainingG = G - seed.length;
        if (remainingG < 0) continue;
        const [mn, mx] = tables(goldPrices, remainingG, capacities);

        if (seedSum + mn[0][remainingG] > b[1] || seedSum + mx[0][remainingG] < b[0]) continue;

        // 搜索具体可行解
        let found = false;
        function dfs(idx, count, sum, combo, grid) {
          if (found) return;
          if ((goldGrid !== null && grid > goldGrid) || (totalGrids !== null && grid + (purpleGrid ?? P) + R > totalGrids)) return;
          if (count === G) {
            if (goldGrid !== null && grid !== goldGrid) return;
            if (!wholeGridPossible(grid, P, R)) return;
            if (sum >= b[0] && sum <= b[1]) {
              if (groupsSatisfiedWithCapacity(combo, goldGroups)) {
                found = true;
                const goldMid = sum;
                const goldLower = sum;
                const pComp = purpleValueForState({ G, P, R }, ctx, cat);
                const rComp = redValueForState({ G, P, R }, ctx, cat);
                const stateValue = goldMid + pComp.mid + rComp.mid + lowTierComp.mid;
                const stateLower = goldLower + pComp.lower + rComp.lower + lowTierComp.lower;

                states.push({
                  G,
                  P,
                  R,
                  sampleCombo: combo,
                  minVal: sum,
                  maxVal: sum,
                  weight: 1,
                  goldValue: goldMid,
                  purpleValue: pComp.mid,
                  redValue: rComp.mid,
                  lowTierValue: lowTierComp.mid,
                  stateValue,
                  stateLower,
                  components: {
                    gold: { mid: goldMid, lower: goldLower, source: "exact_gold_dfs_combo" },
                    purple: pComp,
                    red: rComp,
                    lowTier: lowTierComp
                  }
                });
              }
            }
            return;
          }
          if (idx >= goldPrices.length) return;
          for (let take = Math.min(capacities[idx], G - count); take >= 0; take--) {
            const nextSum = sum + take * goldPrices[idx];
            const remNeed = G - count - take;
            if (nextSum + mn[idx + 1][remNeed] <= b[1] && nextSum + mx[idx + 1][remNeed] >= b[0]) {
              const nextCombo = [...combo];
              for (let k = 0; k < take; k++) nextCombo.push(goldPrices[idx]);
              dfs(idx + 1, count + take, nextSum, nextCombo, grid + take * goldGrids[idx]);
            }
          }
        }
        dfs(0, seed.length, seedSum, seed, seedGrid);
      }
    }

    const candidateGs = Array.from(new Set(states.map(s => s.G))).sort((a, b) => a - b);
    const candidatePs = Array.from(new Set(states.map(s => s.P))).sort((a, b) => a - b);

    return {
      states,
      candidateGs,
      candidatePs,
      solverStatus: states.length > 0 ? "valid" : "no-match"
    };
  }

  // ==========================================
  // 3. 成本拆分、ROI 与三线决策计算
  // ==========================================

  function resolveSessionCosts(ctx = {}, d = {}) {
    const costObj = ctx.costs || ctx.costBreakdown || d?.costs || d?.costBreakdown || {};
    const hasOwn = (obj, key) => obj && Object.prototype.hasOwnProperty.call(obj, key) && obj[key] !== undefined;
    const parseKnown = (value) => {
      if (value === null || value === undefined || value === "") return null;
      const n = Number(value);
      return Number.isFinite(n) && n >= 0 ? n : null;
    };
    const entry = hasOwn(costObj, "entry") ? parseKnown(costObj.entry) : parseKnown(ctx.costEntry);
    const intel = parseKnown(costObj.intel ?? costObj.info ?? ctx.costIntel ?? ctx.costInfo) ?? 0;
    const other = parseKnown(costObj.other ?? ctx.costOther) ?? 0;
    const sunkExplicit = parseKnown(costObj.sunkCost ?? ctx.sunkCost ?? d?.sunkCost);
    const sunkCost = sunkExplicit !== null ? sunkExplicit : (entry === null ? null : entry + intel + other);
    const futureExplicit = parseKnown(costObj.futureIncrementalCost ?? ctx.futureIncrementalCost ?? d?.futureIncrementalCost);
    const futureIncrementalCost = futureExplicit !== null ? futureExplicit : 0;
    const allCosts = sunkCost === null ? null : sunkCost + futureIncrementalCost;
    return {
      entry,
      intel,
      other,
      sunkCost,
      futureIncrementalCost,
      allCosts,
      complete: entry !== null && sunkCost !== null && allCosts !== null
    };
  }

  function calculateStateEntropy(states = []) {
    if (!states || !states.length) return 0;
    const totalWeight = states.reduce((sum, s) => sum + (Number(s.weight ?? s.priorProbability ?? 1) || 1), 0);
    if (totalWeight <= 0) return 0;
    let entropy = 0;
    for (const s of states) {
      const w = (Number(s.weight ?? s.priorProbability ?? 1) || 1) / totalWeight;
      if (w > 0) entropy -= w * Math.log2(w);
    }
    return Number(entropy.toFixed(3));
  }

  function calculateShadowWidth(profile) {
    const source = profile?.shadowCalibrated?.calibrated || profile?.probabilityProfile?.shadowWhole || profile?.shadowWhole;
    if (source && Number.isFinite(Number(source.p80)) && Number.isFinite(Number(source.p20))) {
      return Math.max(0, Math.round(Number(source.p80) - Number(source.p20)));
    }
    return 0;
  }

  function createIntelEventRecord({
    round = 1,
    toolType = "unknown",
    timestamp = new Date().toISOString(),
    before = { candidateStateCount: 0, stateEntropy: 0, shadowWidth: 0, decisionClass: "unknown" },
    observed = {},
    after = { candidateStateCount: 0, stateEntropy: 0, shadowWidth: 0, decisionClass: "unknown" },
    incrementalCost = 0
  } = {}) {
    return {
      round: Number(round) || 1,
      toolType: String(toolType || "unknown"),
      timestamp: String(timestamp || new Date().toISOString()),
      before: {
        candidateStateCount: Number(before.candidateStateCount) || 0,
        stateEntropy: Number(before.stateEntropy) || 0,
        shadowWidth: Number(before.shadowWidth) || 0,
        decisionClass: String(before.decisionClass || "unknown")
      },
      observed: observed || {},
      after: {
        candidateStateCount: Number(after.candidateStateCount) || 0,
        stateEntropy: Number(after.stateEntropy) || 0,
        shadowWidth: Number(after.shadowWidth) || 0,
        decisionClass: String(after.decisionClass || "unknown")
      },
      decisionChanged: String(before.decisionClass) !== String(after.decisionClass),
      incrementalCost: Math.max(0, Number(incrementalCost) || 0)
    };
  }

  function calculateV06DecisionLines(ctx = {}, d = {}, liveBid = null) {
    ctx = ctx || {};
    if (conditionRules(ctx).hiddenBids) liveBid = null;
    d = d || {};
    const costInfo = resolveSessionCosts(ctx, d);
    const solverStatus = String(d?.solverStatus || ctx?.solverStatus || "valid");
    const finite = v => Number.isFinite(Number(v)) && Number(v) > 0;

    const calibrated = d?.shadowCalibrated?.calibrated || null;
    const raw = d?.probabilityProfile?.shadowWhole || d?.rawShadow || null;

    // 候选结构统计与 Shadow 覆盖率
    const candidateStates = d?.probabilityProfile?.stateCandidates || d?.states || [];
    const totalStateCount = Number.isFinite(Number(d?.probabilityProfile?.totalStateCount)) ? Number(d.probabilityProfile.totalStateCount) :
                            (Array.isArray(candidateStates) ? candidateStates.length : (Array.isArray(d?.candidateGs) ? d.candidateGs.length : 0));
    const stateCount = totalStateCount;
    const hasCandidateStates = stateCount > 0;

    let supportedStateCount = Number.isFinite(Number(d?.probabilityProfile?.supportedStateCount)) ? Number(d.probabilityProfile.supportedStateCount) : 0;
    let supportedWeight = Number.isFinite(Number(d?.probabilityProfile?.supportedWeight)) ? Number(d.probabilityProfile.supportedWeight) : 0;
    let totalWeight = Number.isFinite(Number(d?.probabilityProfile?.totalWeight)) ? Number(d.probabilityProfile.totalWeight) : 0;

    const coverageProvided = d?.probabilityProfile?.coverageRatio !== undefined || d?.coverageRatio !== undefined;

    if (coverageProvided) {
      // 只消费显式 coverage，缺省不得当成 100%
    } else if (Array.isArray(d?.probabilityProfile?.stateCandidates) && d.probabilityProfile.stateCandidates.length > 0) {
      let calcSuppWeight = 0;
      let calcTotWeight = 0;
      let calcSuppCount = 0;
      d.probabilityProfile.stateCandidates.forEach(s => {
        const w = Number(s.weight) || (Number(s.relativeWeight) || 1);
        calcTotWeight += w;
        const hasShadow = s.shadow && finite(s.shadow.p50);
        if (hasShadow) {
          calcSuppWeight += w;
          calcSuppCount++;
        }
      });
      if (totalWeight === 0) totalWeight = calcTotWeight;
      if (supportedWeight === 0) supportedWeight = calcSuppWeight;
      if (supportedStateCount === 0) supportedStateCount = calcSuppCount;
    }

    const statesWithShadow = supportedStateCount;
    const statesStructuralOnly = Math.max(0, totalStateCount - statesWithShadow);

    const coverageRatio = coverageProvided ? Number(d?.probabilityProfile?.coverageRatio ?? d?.coverageRatio) :
                          (totalWeight > 0 ? (supportedWeight / totalWeight) : 0.0);

    const isFullShadowCoverage = coverageRatio >= 0.999999;
    const partialShadowP50 = finite(d?.probabilityProfile?.partialShadowP50) ? Number(d.probabilityProfile.partialShadowP50) : (finite(raw?.p50) ? Number(raw.p50) : (finite(calibrated?.p50) ? Number(calibrated.p50) : null));
    const partialShadowP20 = finite(d?.probabilityProfile?.partialShadowP20) ? Number(d.probabilityProfile.partialShadowP20) : (finite(raw?.p20) ? Number(raw.p20) : (finite(calibrated?.p20) ? Number(calibrated.p20) : null));
    const partialShadowP80 = finite(d?.probabilityProfile?.partialShadowP80) ? Number(d.probabilityProfile.partialShadowP80) : (finite(raw?.p80) ? Number(raw.p80) : (finite(calibrated?.p80) ? Number(calibrated.p80) : null));
    const hasAnyShadow = (statesWithShadow > 0) || (partialShadowP50 !== null);

    const hardFloor = finite(d?.hardFloor) ? Number(d.hardFloor) : finite(d?.formalValue?.theoreticalMin) ? Number(d.formalValue.theoreticalMin) : finite(d?.low) ? Number(d.low) : null;
    const theoreticalMin = finite(d?.formalValue?.theoreticalMin) ? Number(d.formalValue.theoreticalMin) : finite(d?.low) ? Number(d.low) : null;
    const theoreticalMax = finite(d?.formalValue?.theoreticalMax) ? Number(d.formalValue.theoreticalMax) : finite(d?.high) ? Number(d.high) : null;
    const structuralCenter = finite(d?.structuralCenter) ? Number(d.structuralCenter) : finite(d?.formalValue?.ev) ? Number(d.formalValue.ev) : finite(d?.center) ? Number(d.center) : null;
    const hasStructuralEvidence = hasCandidateStates || hardFloor !== null || theoreticalMin !== null || structuralCenter !== null;

    // 四级模式判定 (Full Shadow 严格 100% Coverage Gate)
    const isExplicitlySuppressed = d?.recommendationSuppressed || ["incomplete", "fallback", "timeout", "no-match", "stale"].includes(solverStatus);

    let degradationLevel = "insufficient";
    let isSuppressed = false;
    let valueP50 = null;
    let valueSource = "none";

    if (isExplicitlySuppressed) {
      // 4. Insufficient
      degradationLevel = "insufficient";
      isSuppressed = true;
    } else if (isFullShadowCoverage && (finite(raw?.p50) || finite(calibrated?.p50))) {
      // 1. FULL SHADOW (100% 覆盖率且有分布)
      degradationLevel = "full_shadow";
      valueP50 = finite(raw?.p50) ? Number(raw.p50) : Number(calibrated.p50);
      valueSource = "shadow";
      isSuppressed = false;
    } else if (hasAnyShadow && coverageRatio > 0) {
      // 2. PARTIAL SHADOW (0 < coverageRatio < 1)
      degradationLevel = "partial_shadow";
      valueP50 = null; // 严禁伪造整仓 P50
      valueSource = "partial-shadow";
      isSuppressed = false;
    } else if (hasStructuralEvidence) {
      // 3. STRUCTURAL ONLY (coverageRatio == 0 但有结构)
      degradationLevel = "structural_only";
      valueP50 = null;
      valueSource = "structural-only";
      isSuppressed = false;
    } else {
      // 4. Insufficient
      degradationLevel = "insufficient";
      isSuppressed = true;
    }

    const valueP20 = (degradationLevel === "full_shadow") ? (finite(calibrated?.p20) ? Number(calibrated.p20) : finite(raw?.p20) ? Number(raw.p20) : null) : null;
    const valueP80 = (degradationLevel === "full_shadow") ? (finite(calibrated?.p80) ? Number(calibrated.p80) : finite(raw?.p80) ? Number(raw.p80) : null) : null;

    const targetROIRaw = ctx?.targetROI ?? d?.targetROI;
    const targetROI = Number(targetROIRaw);
    const hasTargetROI = targetROIRaw !== null && targetROIRaw !== undefined && targetROIRaw !== "" && typeof targetROIRaw !== "boolean" && Number.isFinite(targetROI) && targetROI >= 0;
    const effectiveROI = hasTargetROI ? targetROI : null;
    const targetProfit = Math.max(0, Number.isFinite(Number(ctx?.targetProfit ?? d?.targetProfit ?? 30000)) ? Number(ctx?.targetProfit ?? d?.targetProfit ?? 30000) : 30000);

    // Level 1 决策三价 (仅在 Full Shadow 时生成)
    let safeBuy = null;
    let recommendedMax = null;
    let chaseLimit = null;

    if (degradationLevel === "full_shadow" && valueP50 !== null && costInfo.allCosts !== null) {
      const profitCap = valueP50 - costInfo.allCosts - targetProfit;
        const roiCap = hasTargetROI ? valueP50 / (1 + effectiveROI) - costInfo.allCosts : Infinity;
        safeBuy = Math.max(0, Math.floor(Math.min(profitCap, roiCap)));
      recommendedMax = Math.max(0, Math.floor(valueP50 - costInfo.allCosts));
      chaseLimit = Math.max(0, Math.floor(valueP50 - costInfo.futureIncrementalCost));
    }

    // Level 2 / Partial Shadow 低置信结构参考出价 (非正式建议最高价)
    const structuralReferenceBid = (degradationLevel === "partial_shadow" || degradationLevel === "structural_only") && costInfo.allCosts !== null ?
      (structuralCenter !== null ? Math.max(0, Math.floor(structuralCenter - costInfo.allCosts)) : (partialShadowP50 !== null ? Math.max(0, Math.floor(partialShadowP50 - costInfo.allCosts)) : null)) : null;

    // 保持别名兼容
    const targetLine = safeBuy;
    const globalLine = recommendedMax;
    const marginalLine = chaseLimit;

    // ROI on live bid
    const bid = liveBid !== null && liveBid !== undefined && liveBid !== "" && typeof liveBid !== "boolean" && Number.isFinite(Number(liveBid)) && Number(liveBid) >= 0 ? Number(liveBid) : null;
    const expectedProfit = bid !== null && valueP50 !== null && costInfo.allCosts !== null ? Math.floor(valueP50 - costInfo.allCosts - bid) : null;
      let roiOnTotalSpend = null;
    let roiOnPurchase = null;
    if (bid !== null && valueP50 !== null && costInfo.allCosts !== null) {
      const totalSpend = bid + costInfo.allCosts;
      const netProfit = valueP50 - totalSpend;
      roiOnTotalSpend = totalSpend > 0 ? (netProfit / totalSpend) : 0;
      roiOnPurchase = bid > 0 ? (netProfit / bid) : 0;
    }

    // 结构候选与藏品已知明细
    const candidateGs = Array.isArray(d?.candidateGs) && d.candidateGs.length ? d.candidateGs : (Array.isArray(ctx?.candidateGs) && ctx.candidateGs.length ? ctx.candidateGs : (Array.isArray(candidateStates) ? [...new Set(candidateStates.map(s => s.g ?? s.G).filter(Number.isInteger))].sort((a,b)=>a-b) : []));
    const candidatePs = Array.isArray(d?.candidatePs) && d.candidatePs.length ? d.candidatePs : (Array.isArray(ctx?.candidatePs) && ctx.candidatePs.length ? ctx.candidatePs : (Array.isArray(candidateStates) ? [...new Set(candidateStates.map(s => s.p ?? s.P).filter(Number.isInteger))].sort((a,b)=>a-b) : (ctx?.purple !== null && ctx?.purple !== undefined ? [ctx.purple] : [])));
    const redMin = d?.redMin ?? ctx?.redMin ?? (Array.isArray(candidateStates) && candidateStates.length ? Math.min(...candidateStates.map(s => s.r ?? s.R ?? s.rMin ?? 0).filter(Number.isInteger)) : null);
    const redMax = d?.redMax ?? ctx?.redMax ?? (Array.isArray(candidateStates) && candidateStates.length ? Math.max(...candidateStates.map(s => s.r ?? s.R ?? s.rMax ?? 0).filter(Number.isInteger)) : null);

    // 候选状态实际推导范围 (不混同于极端 Jackpot 理论边界)
    let candidateBoundsMin = null;
    let candidateBoundsMax = null;
    if (Array.isArray(candidateStates) && candidateStates.length > 0) {
      const mins = candidateStates.map(s => s.totalMin ?? (s.component ? (s.component.gold?.lower || 0) + (s.component.purple?.lower || 0) + (s.component.lowTier?.lower || 0) : null) ?? s.shadow?.p20 ?? s.shadow?.min).filter(v => Number.isFinite(Number(v)) && Number(v) > 0);
      const maxs = candidateStates.map(s => s.totalMax ?? (s.component ? (s.component.gold?.upper || 0) + (s.component.purple?.upper || 0) + (s.component.lowTier?.upper || 0) : null) ?? s.shadow?.p80 ?? s.shadow?.max).filter(v => Number.isFinite(Number(v)) && Number(v) > 0);
      if (mins.length > 0) candidateBoundsMin = Math.min(...mins);
      if (maxs.length > 0) candidateBoundsMax = Math.max(...maxs);
    }

    // 已确认藏品价值
    const breakdown = d?.breakdown || d?.componentBreakdown || {};
    const rawKnownGold = Array.isArray(ctx?.knownGold) ? ctx.knownGold : [];
    const rawKnownPurple = Array.isArray(ctx?.knownPurple) ? ctx.knownPurple : [];
    const rawKnownRed = Array.isArray(ctx?.knownRed) ? ctx.knownRed : [];

    const knownGoldVal = Number(breakdown?.gold?.knownTotal || d?.knownGoldTotal || ctx?.knownGoldTotal || rawKnownGold.reduce((acc, x) => acc + Number(x?.price || x?.[1] || 0), 0) || 0);
    const knownPurpleVal = Number(breakdown?.purple?.knownTotal || d?.knownPurpleTotal || ctx?.knownPurpleTotal || rawKnownPurple.reduce((acc, x) => acc + Number(x?.price || x?.[1] || 0), 0) || 0);
    const knownRedVal = Number(breakdown?.red?.knownTotal || d?.knownRedTotal || ctx?.knownRedTotal || rawKnownRed.reduce((acc, x) => acc + Number(x?.price || x?.[1] || 0), 0) || 0);
    const knownTotalVal = knownGoldVal + knownPurpleVal + knownRedVal;

    // 结构候选描述
    const gStr = candidateGs.length > 0 ? (candidateGs.length === 1 ? `G = ${candidateGs[0]}` : `G ∈ {${candidateGs.join(" / ")}}`) : "G 未定";
    const pStr = candidatePs.length > 0 ? (candidatePs.length === 1 ? `P = ${candidatePs[0]}` : `P ∈ {${candidatePs.join(" / ")}}`) : "P 未定";
    const rStr = redMin !== null && redMax !== null ? (redMin === redMax ? `R = ${redMin}` : `R = ${redMin}~${redMax}`) : "R 未定";
    const stateCountStr = stateCount > 0 ? `共 ${stateCount} 个候选结构` : "结构分析中";
    const structureCandidateSummary = `${gStr} · ${pStr} · ${rStr} · ${stateCountStr}`;

    // 已确认价值组成描述
    const confirmedParts = [];
    if (knownGoldVal > 0) confirmedParts.push(`已确认金色 ≥ ${(knownGoldVal / 10000).toFixed(1)}W`);
    if (knownPurpleVal > 0) confirmedParts.push(`已确认紫色 ≥ ${(knownPurpleVal / 10000).toFixed(1)}W`);
    if (knownRedVal > 0) confirmedParts.push(`已确认红色 ≥ ${(knownRedVal / 10000).toFixed(1)}W`);
    if (knownTotalVal > 0) confirmedParts.push(`已确认藏品总值 ≥ ${(knownTotalVal / 10000).toFixed(1)}W`);
    const confirmedValuesSummary = confirmedParts.length > 0 ? confirmedParts.join(" · ") : "暂无特定藏品录入，由图鉴保底";

    // 缺失 Shadow 原因说明
    let missingReason = "历史分布样本不足，当前无法生成整仓 P50";
    if (degradationLevel === "partial_shadow") {
      missingReason = `${totalStateCount} 个候选结构中仅 ${statesWithShadow} 个具备历史分布（概率质量覆盖率 ${(coverageRatio * 100).toFixed(1)}%），${statesStructuralOnly} 个未覆盖状态未进入概率聚合，因此不能代表完整整仓 P50`;
    } else if (statesWithShadow > 0 && statesStructuralOnly > 0) {
      missingReason = `${totalStateCount} 个候选结构中仅 ${statesWithShadow} 个具备历史分布，${statesStructuralOnly} 个仅保留结构约束，整体置信不足以生成整仓 P50`;
    } else if (totalStateCount > 0 && statesWithShadow === 0) {
      if (redMin !== null && redMin > 0 && redMin === redMax) {
        missingReason = `当前 R=${redMin} 缺少同 R 真实历史对局样本，无法生成整仓 P50`;
      } else {
        missingReason = `当前 ${totalStateCount} 个候选结构均缺少直接历史样本，仅保留确定性整数拆分与藏品上下界约束`;
      }
    }

    // Level 3 缺失情报诊断清单
    const missingClues = [];
    const hasQ = ctx.q !== null && ctx.q !== undefined && ctx.q !== "" && Number.isFinite(Number(ctx.q)) && Number(ctx.q) > 0;
    const hasGoldPrice = (ctx.avg !== null && ctx.avg !== undefined && ctx.avg !== "" && Number.isFinite(Number(ctx.avg)) && Number(ctx.avg) > 0) ||
                         (ctx.goldTotal !== null && ctx.goldTotal !== undefined && ctx.goldTotal !== "" && Number.isFinite(Number(ctx.goldTotal)) && Number(ctx.goldTotal) > 0) ||
                         (ctx.publicInfo?.goldGrid !== null && ctx.publicInfo?.goldGrid !== undefined && ctx.publicInfo?.goldGrid !== "");
    const hasPurple = ctx.purple !== null && ctx.purple !== undefined && ctx.purple !== "" && Number.isFinite(Number(ctx.purple)) && Number(ctx.purple) >= 0;
    const hasKnown = rawKnownGold.length > 0 || rawKnownPurple.length > 0 || rawKnownRed.length > 0;
    const hasRed = ctx.redCount !== null && ctx.redCount !== undefined && ctx.redCount !== "" && Number.isFinite(Number(ctx.redCount)) && Number(ctx.redCount) >= 0;

    if (!hasQ) missingClues.push({ priority: "high", label: "格数 Q", text: "需补齐格数 Q（当前总格数未知，无法确定总件数与 G/P/R 关系）" });
    if (!hasGoldPrice) missingClues.push({ priority: "medium", label: "金均价/金总价", text: "需补齐金均价或金总价（以计算金色价格池匹配并锁定 G 候选）" });
    if (!hasPurple) missingClues.push({ priority: "medium", label: "紫件数 P", text: "需补齐紫色藏品数量 P（或录入紫色价格以缩小紫件组合）" });
    if (!hasKnown) missingClues.push({ priority: "low", label: "已知藏品", text: "建议录入已见金色/紫色藏品（以建立确定性的已确认价值下限）" });
    if (!hasRed) missingClues.push({ priority: "low", label: "红货数量", text: "建议确认红货数量（若确认 R=0 可完全排除红色尾部不确定性）" });

    return {
      degradationLevel,
      valueP20,
      valueP50,
      valueP80,
      expectedValue: valueP50,
      riskValue: valueP20 ?? valueP50,
      valueSource,
      isSuppressed,
      safeBuy,
      recommendedMax,
      chaseLimit,
      hardFloor,
      theoreticalMin,
      theoreticalMax,
      candidateBoundsMin,
      candidateBoundsMax,
      candidateGs,
      candidatePs,
      redMin,
      redMax,
      knownGoldVal,
      knownPurpleVal,
      knownRedVal,
      knownTotalVal,
      structureCandidateSummary,
      confirmedValuesSummary,
      missingReason,
      missingClues,
      structuralCenter,
      structuralReferenceBid,
      statesWithShadow,
      statesStructuralOnly,
      stateCount: totalStateCount,
      supportedStateCount,
      totalStateCount,
      supportedWeight,
      totalWeight,
      coverageRatio,
      isFullShadow: isFullShadowCoverage,
      partialShadowP20,
      partialShadowP50,
      partialShadowP80,
      targetLine,
      globalLine,
      marginalLine,
      costInfo,
      targetProfit,
      targetROI: effectiveROI,
      expectedProfit,
      roiOnTotalSpend,
      roiOnPurchase
    };
  }

  // ==========================================
  // 3. 统计学与历史评估辅助函数 (Statistical & Calibration Helpers)
  // ==========================================

  function quantile(values, q) {
    if (!values || !values.length) return null;
    const s = [...values].sort((a, b) => a - b);
    const pos = (s.length - 1) * q;
    const base = Math.floor(pos);
    const rest = pos - base;
    return s[base + 1] !== undefined ? s[base] + rest * (s[base + 1] - s[base]) : s[base];
  }

  function weightedQuantile(entries, q) {
    const valid = (entries || []).filter(x => x && Number.isFinite(Number(x.value)) && Number(x.weight) > 0);
    if (!valid.length) return null;
    valid.sort((a, b) => Number(a.value) - Number(b.value));
    const total = valid.reduce((sum, x) => sum + Number(x.weight), 0);
    if (total <= 0) return null;
    const target = total * q;
    let running = 0;
    for (const item of valid) {
      running += Number(item.weight);
      if (running >= target) return Number(item.value);
    }
    return Number(valid[valid.length - 1].value);
  }

  function mean(values) {
    if (!values || !values.length) return null;
    return values.reduce((a, b) => a + b, 0) / values.length;
  }

  function historyTimestamp(value) {
    if (value === null || value === undefined || value === "") return null;
    const raw = String(value).trim();
    const parsed = Date.parse(raw.includes("T") ? raw : raw.replace(" ", "T"));
    return Number.isFinite(parsed) ? parsed : null;
  }

  function nonNegativeOrNull(value) {
    if (value === null || value === undefined || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }

  function actualInRange(actual, low, high) {
    return Number.isFinite(Number(actual)) &&
           Number.isFinite(Number(low)) &&
           Number.isFinite(Number(high)) &&
           Number(actual) >= Number(low) &&
           Number(actual) <= Number(high);
  }

  function stableHashValue(value) {
    if (value === undefined) return "__undefined__";
    if (value === null) return null;
    if (typeof value !== "object") return value;
    if (Array.isArray(value)) return value.map(stableHashValue);
    return Object.keys(value).sort().reduce((out, key) => {
      out[key] = stableHashValue(value[key]);
      return out;
    }, {});
  }

  function canonicalJson(value) {
    if (value === null || typeof value !== "object") {
      return JSON.stringify(value);
    }
    if (Array.isArray(value)) {
      return "[" + value.map(v => v === undefined ? "null" : canonicalJson(v)).join(",") + "]";
    }
    const keys = Object.keys(value).filter(k => value[k] !== undefined).sort();
    return "{" + keys.map(k => JSON.stringify(k) + ":" + canonicalJson(value[k])).join(",") + "}";
  }

  const SHA256_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];

  function sha256Hex(text) {
    if (req && typeof req === "function") {
      try {
        const crypto = req("crypto");
        if (crypto && typeof crypto.createHash === "function") {
          return crypto.createHash("sha256").update(String(text), "utf8").digest("hex");
        }
      } catch (_) {}
    }
    const str = String(text);
    const bytes = [];
    if (typeof TextEncoder !== "undefined") {
      const encoded = new TextEncoder().encode(str);
      for (let i = 0; i < encoded.length; i++) bytes.push(encoded[i]);
    } else {
      for (let i = 0; i < str.length; i++) {
        let c = str.charCodeAt(i);
        if (c < 128) {
          bytes.push(c);
        } else if (c < 2048) {
          bytes.push((c >> 6) | 192, (c & 63) | 128);
        } else if ((c & 0xFC00) === 0xD800 && i + 1 < str.length && (str.charCodeAt(i + 1) & 0xFC00) === 0xDC00) {
          c = 0x10000 + ((c & 0x03FF) << 10) + (str.charCodeAt(++i) & 0x03FF);
          bytes.push((c >> 18) | 240, ((c >> 12) & 63) | 128, ((c >> 6) & 63) | 128, (c & 63) | 128);
        } else {
          bytes.push((c >> 12) | 224, ((c >> 6) & 63) | 128, (c & 63) | 128);
        }
      }
    }

    const bitLength = bytes.length * 8;
    bytes.push(0x80);
    while ((bytes.length + 8) % 64 !== 0) {
      bytes.push(0);
    }
    const highBits = Math.floor(bitLength / 0x100000000);
    const lowBits = bitLength >>> 0;
    bytes.push((highBits >>> 24) & 255, (highBits >>> 16) & 255, (highBits >>> 8) & 255, highBits & 255);
    bytes.push((lowBits >>> 24) & 255, (lowBits >>> 16) & 255, (lowBits >>> 8) & 255, lowBits & 255);

    let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
    let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;

    const w = new Uint32Array(64);
    for (let chunk = 0; chunk < bytes.length; chunk += 64) {
      for (let i = 0; i < 16; i++) {
        const j = chunk + (i * 4);
        w[i] = ((bytes[j] << 24) | (bytes[j + 1] << 16) | (bytes[j + 2] << 8) | bytes[j + 3]) >>> 0;
      }
      for (let i = 16; i < 64; i++) {
        const s0 = ((w[i - 15] >>> 7) | (w[i - 15] << 25)) ^ ((w[i - 15] >>> 18) | (w[i - 15] << 14)) ^ (w[i - 15] >>> 3);
        const s1 = ((w[i - 2] >>> 17) | (w[i - 2] << 15)) ^ ((w[i - 2] >>> 19) | (w[i - 2] << 13)) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
      }

      let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
      for (let i = 0; i < 64; i++) {
        const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        const ch = (e & f) ^ ((~e) & g);
        const temp1 = (h + S1 + ch + SHA256_K[i] + w[i]) >>> 0;
        const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        const maj = (a & b) ^ (a & c) ^ (b & c);
        const temp2 = (S0 + maj) >>> 0;

        h = g;
        g = f;
        f = e;
        e = (d + temp1) >>> 0;
        d = c;
        c = b;
        b = a;
        a = (temp1 + temp2) >>> 0;
      }

      h0 = (h0 + a) >>> 0;
      h1 = (h1 + b) >>> 0;
      h2 = (h2 + c) >>> 0;
      h3 = (h3 + d) >>> 0;
      h4 = (h4 + e) >>> 0;
      h5 = (h5 + f) >>> 0;
      h6 = (h6 + g) >>> 0;
      h7 = (h7 + h) >>> 0;
    }

    const hex = (v) => ("00000000" + (v >>> 0).toString(16)).slice(-8);
    return hex(h0) + hex(h1) + hex(h2) + hex(h3) + hex(h4) + hex(h5) + hex(h6) + hex(h7);
  }

  function sha256Json(value) {
    return sha256Hex(canonicalJson(value));
  }

  const ALLOWED_FACT_KEYS = new Set([
    "q", "goldCount", "purpleCount", "redCount", "minGold", "minPurple", "minRed",
    "goldAvg", "purpleAvg", "goldTotal", "costs", "knownGold", "knownPurple", "knownRed",
    "fieldCondition", "avgValueBasis", "roundingMode", "catalogVersion", "round",
    "targetProfit", "sparkle", "privateBidCap", "bidActionCount", "venue", "box",
    "character", "totalItems", "totalGrid", "qualities"
  ]);

  const FORBIDDEN_FRAGMENTS = [
    "ocr", "latestpayload", "currentmatch", "solverresult", "settlement", "actualtotal", "truth"
  ];

  function normalizeFactsForSnapshot(raw = {}) {
    const ctx = raw || {};
    const out = {};

    if (ctx.sparkle != null) out.sparkle = JSON.parse(JSON.stringify(ctx.sparkle));

    function cleanString(v) {
      if (v === null || v === undefined) return null;
      const s = String(v).trim();
      return s.length > 0 ? s : null;
    }
    function cleanInt(v) {
      if (v === null || v === undefined || v === "") return null;
      const n = Number(v);
      return Number.isInteger(n) ? n : (Number.isFinite(n) ? Math.floor(n) : null);
    }
    function cleanNumber(v) {
      if (v === null || v === undefined || v === "") return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    }

    if (cleanInt(ctx.q) !== null) out.q = cleanInt(ctx.q);
    if (cleanInt(ctx.goldCount ?? ctx.g) !== null) out.goldCount = cleanInt(ctx.goldCount ?? ctx.g);
    if (cleanInt(ctx.purpleCount ?? ctx.purple ?? ctx.p) !== null) out.purpleCount = cleanInt(ctx.purpleCount ?? ctx.purple ?? ctx.p);
    if (cleanInt(ctx.redCount ?? ctx.red ?? ctx.r) !== null) out.redCount = cleanInt(ctx.redCount ?? ctx.red ?? ctx.r);
    if (cleanInt(ctx.minGold) !== null) out.minGold = cleanInt(ctx.minGold);
    if (cleanInt(ctx.minPurple) !== null) out.minPurple = cleanInt(ctx.minPurple);
    if (cleanInt(ctx.minRed) !== null) out.minRed = cleanInt(ctx.minRed);
    if (cleanNumber(ctx.goldAvg ?? ctx.avg) !== null) out.goldAvg = cleanNumber(ctx.goldAvg ?? ctx.avg);
    if (cleanNumber(ctx.purpleAvg) !== null) out.purpleAvg = cleanNumber(ctx.purpleAvg);
    if (cleanNumber(ctx.goldTotal) !== null) out.goldTotal = cleanNumber(ctx.goldTotal);
    if (cleanInt(ctx.round) !== null) out.round = cleanInt(ctx.round);
    if (cleanInt(ctx.totalItems) !== null) out.totalItems = cleanInt(ctx.totalItems);
    if (cleanInt(ctx.totalGrid ?? ctx.totalGrids) !== null) out.totalGrid = cleanInt(ctx.totalGrid ?? ctx.totalGrids);

    const kg = cleanString(ctx.knownGoldRaw ?? ctx.knownGold);
    if (kg !== null) out.knownGold = kg;
    const kp = cleanString(ctx.knownPurpleRaw ?? ctx.knownPurple);
    if (kp !== null) out.knownPurple = kp;
    const kr = cleanString(ctx.knownRedRaw ?? ctx.knownRed);
    if (kr !== null) out.knownRed = kr;

    out.fieldCondition = normalizeFieldCondition(ctx.fieldCondition || "unknown").id;
    out.avgValueBasis = cleanString(ctx.avgValueBasis) || "unknown";
    out.roundingMode = cleanString(ctx.roundingMode) || "floor";
    out.catalogVersion = catalogVersionFor(ctx);
    out.targetProfit = cleanNumber(ctx.targetProfit) ?? 30000;

    const v = cleanString(ctx.venue ?? ctx.lobbyVenue);
    if (v !== null) out.venue = v;
    const b = cleanString(ctx.box);
    if (b !== null) out.box = b;
    const ch = cleanString(ctx.character ?? ctx.lobbyCharacter);
    if (ch !== null) out.character = ch;

    if (cleanInt(ctx.privateBidCap) !== null) out.privateBidCap = cleanInt(ctx.privateBidCap);
    if (cleanInt(ctx.bidActionCount) !== null) out.bidActionCount = cleanInt(ctx.bidActionCount);

    const cInfo = resolveSessionCosts(ctx, {});
    const costsObj = {};
    if (cInfo.entryCost !== undefined) costsObj.entry = cInfo.entryCost;
    if (cInfo.intelCost !== undefined) costsObj.intel = cInfo.intelCost;
    if (cInfo.otherCost !== undefined) costsObj.other = cInfo.otherCost;
    if (cInfo.sunkCost !== undefined) costsObj.sunkCost = cInfo.sunkCost;
    if (cInfo.futureCost !== undefined) costsObj.futureIncrementalCost = cInfo.futureCost;
    if (cInfo.allCosts !== undefined) costsObj.total = cInfo.allCosts;
    if (Object.keys(costsObj).length > 0) out.costs = costsObj;

    const sanitized = {};
    for (const key of Object.keys(out).sort()) {
      if (!ALLOWED_FACT_KEYS.has(key)) continue;
      const lower = key.replace(/_/g, "").toLowerCase();
      if (FORBIDDEN_FRAGMENTS.some(frag => lower.includes(frag))) continue;
      sanitized[key] = out[key];
    }
    return sanitized;
  }

  function fastHash(text) {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0).toString(16).padStart(8, "0");
  }

  function solverInputPayload(ctx = {}) {
    return {
      q: ctx.q,
      goldCount: ctx.goldCount,
      purple: ctx.purple,
      redCount: ctx.redCount,
      minGold: ctx.minGold,
      minPurple: ctx.minPurple,
      minRed: ctx.minRed,
      avg: ctx.avg,
      purpleAvg: ctx.purpleAvg,
      goldTotal: ctx.goldTotal,
      cost: ctx.cost ?? 0,
      knownGold: ctx.knownGoldRaw ?? ctx.knownGold ?? "",
      knownPurple: ctx.knownPurpleRaw ?? ctx.knownPurple ?? "",
      knownRed: ctx.knownRedRaw ?? ctx.knownRed ?? "",
      goldGroups: ctx.goldGroups || [],
      purpleGroups: ctx.purpleGroups || [],
      redGroups: ctx.redGroups || [],
      fieldCondition: ctx.fieldCondition || "unknown",
      avgValueBasis: ctx.avgValueBasis || "unknown",
      roundingMode: ctx.roundingMode || "floor",
      catalogVersion: catalogVersionFor(ctx),
      round: ctx.round || 1,
      targetProfit: ctx.targetProfit ?? 30000,
      sparkle: ctx.sparkle || null,
      privateBidCap: ctx.privateBidCap ?? null,
      bidActionCount: ctx.bidActionCount ?? null
    };
  }

  function solverInputHash(ctx = {}) {
    return `sha1-${fastHash(JSON.stringify(stableHashValue(solverInputPayload(ctx))))}`;
  }

  function qBucketV06(q) {
    const n = Number(q);
    return !Number.isFinite(n) ? "unknown" : n <= 9 ? "Q1-9" : n <= 15 ? "Q10-15" : n <= 25 ? "Q16-25" : "Q26+";
  }

  // ==========================================
  // 4. 正式 Market Model (Hierarchical Shrinkage)
  // ==========================================

  function marketPredictionV06(ctx = {}, valueEstimate = null, records = []) {
    const estimate = Number(valueEstimate);
    if (!Number.isFinite(estimate) || estimate <= 0) {
      return {
        version: "v0.6-market",
        status: "no-data",
        marketRatio: null,
        p20: null,
        p50: null,
        p80: null,
        localN: 0,
        parentN: 0,
        shrinkageWeight: 0,
        fallbackLevel: "none",
        competition: "未知",
        availableN: 0
      };
    }

    const now = historyTimestamp(ctx?.playedAt);
    const allowed = Array.isArray(ctx?.allowedHistoryIds) ? new Set(ctx.allowedHistoryIds) : null;
    const condition = normalizeFieldCondition(ctx?.fieldCondition || "unknown").id;
    const box = String(ctx?.box || "未知箱型");
    const venue = String(ctx?.venue || "未知场地");
    const qBucket = qBucketV06(ctx?.q);

    const historyList = Array.isArray(records) && records.length ? records : [];
    const rows = historyList.map(r => {
      const t = historyTimestamp(r.playedAt);
      const p = r.prediction || {};
      const clearing = nonNegativeOrNull(r.clearingPrice ?? r.settlement?.clearingPrice);
      const base = Number(p?.estimate || r.estimate);
      if (allowed && !allowed.has(r.id)) return null;
      if (now !== null && t !== null && t >= now) return null;
      if (clearing === null || !Number.isFinite(base) || base <= 0) return null;
      const c = normalizeFieldCondition(r.fieldCondition || r.settlement?.fieldCondition || "unknown").id;
      const rb = qBucketV06(r.q);
      return {
        record: r,
        ratio: clearing / base,
        condition: c,
        box: String(r.box || "未知箱型"),
        venue: String(r.venue || "未知场地"),
        qBucket: rb
      };
    }).filter(x => x && Number.isFinite(x.ratio) && x.ratio > 0 && x.ratio < 5);

    const stats = items => {
      if (!items || !items.length) return { n: 0, p20: null, p50: null, p80: null };
      const ratios = items.map(x => x.ratio).filter(Number.isFinite);
      return {
        n: ratios.length,
        p20: quantile(ratios, 0.2),
        p50: quantile(ratios, 0.5),
        p80: quantile(ratios, 0.8)
      };
    };

    if (!rows.length) {
      return {
        version: "v0.6-market",
        status: "no-sample",
        marketRatio: null,
        p20: null,
        p50: null,
        p80: null,
        localN: 0,
        parentN: 0,
        shrinkageWeight: 0,
        fallbackLevel: "global",
        competition: "未知",
        availableN: 0
      };
    }

    const levels = [
      { id: "global", items: rows },
      { id: "venue", items: rows.filter(x => x.venue === venue) },
      { id: "box", items: rows.filter(x => x.box === box) },
      { id: "condition", items: rows.filter(x => x.condition === condition) },
      { id: "q-bucket", items: rows.filter(x => x.qBucket === qBucket) },
      { id: "exact-condition-box-q", items: rows.filter(x => x.condition === condition && x.box === box && x.qBucket === qBucket) }
    ];

    let parent = stats(rows);
    let parentN = rows.length;
    let best = { level: "global", n: rows.length, parentN: 0, weight: rows.length / (rows.length + 8) };

    for (const level of levels.slice(1)) {
      const local = stats(level.items);
      if (!local.n) continue;
      const weight = local.n / (local.n + 8);
      const blend = key => parent[key] + (local[key] - parent[key]) * weight;
      parent = {
        n: local.n,
        p20: blend("p20"),
        p50: blend("p50"),
        p80: blend("p80")
      };
      best = { level: level.id, n: local.n, parentN, weight };
      parentN = local.n;
    }

    const toValue = ratio => Number.isFinite(ratio) ? Math.max(0, Math.floor(ratio * estimate)) : null;
    const p20 = toValue(parent.p20);
    const p50 = toValue(parent.p50);
    const p80 = toValue(parent.p80);
    const competition = parent.p50 < 0.75 ? "冷" : parent.p50 < 0.95 ? "正常" : parent.p50 < 1.10 ? "偏紧" : "疯狂";

    return {
      version: "v0.6-market",
      status: best.n < 5 ? "low-sample" : "shrunk",
      marketRatio: { p20: parent.p20, p50: parent.p50, p80: parent.p80 },
      p20,
      p50,
      p80,
      localN: best.n,
      parentN: best.parentN,
      shrinkageWeight: best.weight,
      fallbackLevel: best.level,
      qBucket,
      competition,
      availableN: rows.length,
      lowSample: best.n < 5,
      uses: "clearingPrice / 当时冻结 estimate；不读取 actualTotal；严格回放优先使用 allowedHistoryIds"
    };
  }

  // ==========================================
  // 5. 正式 Shadow & OOS 校准 (Sidecar Calibration)
  // ==========================================

  function shadowCalibrationSidecarV06(ctx = {}, d = {}, records = []) {
    const raw = d?.rawShadow || d?.probabilityProfile?.shadowWhole || (Number.isFinite(Number(d?.low)) && Number.isFinite(Number(d?.high)) ? { p20: Number(d.low), p50: Number(d.center), p80: Number(d.high) } : null);
    if (!raw || !Number.isFinite(Number(raw.p50))) return null;

    const rawP20 = Number(raw.p20);
    const rawP50 = Number(raw.p50);
    const rawP80 = Number(raw.p80);

    const now = historyTimestamp(ctx?.playedAt);
    const allowed = Array.isArray(ctx?.allowedHistoryIds) ? new Set(ctx.allowedHistoryIds) : null;
    const historyList = Array.isArray(records) && records.length ? records : [];

    const entries = historyList.map(r => {
      const t = historyTimestamp(r.playedAt);
      const p = r.prediction || {};
      const shadow = p.rawShadow || p.probabilityProfile?.shadowWhole || (Number.isFinite(Number(p.estimate)) ? { p20: p.workingLow || p.estimate * 0.8, p50: p.estimate, p80: p.workingHigh || p.estimate * 1.2 } : null);
      const actual = nonNegativeOrNull(r.actualTotal);
      if (allowed && !allowed.has(r.id)) return null;
      if (now !== null && t !== null && t >= now) return null;
      if (!shadow || actual === null || !Number.isFinite(Number(shadow.p50)) || !Number.isFinite(Number(shadow.p20)) || !Number.isFinite(Number(shadow.p80))) return null;
      return {
        actual,
        shadow,
        residual: (actual - Number(shadow.p50)) / Math.max(1, Number(shadow.p50))
      };
    }).filter(Boolean);

    const residuals = entries.map(x => x.residual).filter(Number.isFinite);
    const n = residuals.length;
    const p10 = quantile(residuals, 0.10);
    const p90 = quantile(residuals, 0.90);

    const low = n >= 5 ? Math.min(rawP20, Math.max(0, Math.floor(rawP50 * (1 + (p10 ?? -0.25))))) : rawP20;
    const high = n >= 5 ? Math.max(rawP80, Math.floor(rawP50 * (1 + (p90 ?? 0.25)))) : rawP80;

    const rawCoverage = entries.length ? entries.filter(x => actualInRange(x.actual, rawP20, rawP80)).length / entries.length : null;
    const calibratedCoverage = entries.length ? entries.filter(x => actualInRange(x.actual, low, high)).length / entries.length : null;

    return {
      version: "v0.6-shadow",
      status: n >= 5 ? "calibrated-sidecar" : "low-sample",
      calibrationSource: n >= 5 ? "residual-p10-p90" : "uncalibrated",
      residualN: n,
      residualP10: p10,
      residualP90: p90,
      raw: { p20: rawP20, p50: rawP50, p80: rawP80 },
      calibrated: { p20: low, p50: rawP50, p80: high },
      coverage: calibratedCoverage,
      rawCoverage,
      calibratedCoverage,
      coverageN: entries.length,
      nominalTarget: "真实 OOS P20/P80 区间覆盖；残差 P10/P90 仅用于旁路扩宽，中心不变"
    };
  }

  // ==========================================
  // 6. 正式 State Prior (Categorical Shrinkage)
  // ==========================================

  function empiricalStatePriorV06(ctx = {}, states = [], records = []) {
    const candidateStates = (states || []).filter(s => Number.isInteger(s?.G ?? s?.g) && Number.isInteger(s?.P ?? s?.p));
    const now = historyTimestamp(ctx?.playedAt);
    const condition = normalizeFieldCondition(ctx?.fieldCondition || "unknown").id;
    const box = String(ctx?.box || "未知箱型");
    const venue = String(ctx?.venue || "未知场地");
    const qBucket = qBucketV06(ctx?.q);

    const stateKey = (g, p, r) => `${g}/${p}/${r}`;
    const candidateKeys = candidateStates.map(s => stateKey(s.G ?? s.g, s.P ?? s.p, s.R ?? s.r ?? 0));

    const historyList = Array.isArray(records) && records.length ? records : [];
    const history = historyList.map(r => {
      const t = historyTimestamp(r.playedAt);
      const truth = r.settlement?.realizedState || r.realizedState || null;
      return { record: r, time: t, truth };
    }).filter(x => {
      if (now !== null && x.time !== null && x.time >= now) return false;
      return x.truth && Number.isInteger(x.truth.g) && Number.isInteger(x.truth.p) && Number.isInteger(x.truth.r);
    });

    const observedKeys = history.map(x => stateKey(x.truth.g, x.truth.p, x.truth.r));
    const domain = [...new Set([...candidateKeys, ...observedKeys])];

    if (!domain.length || !history.length) {
      return {
        version: "v0.6-shadow",
        status: "no-sample",
        localN: 0,
        parentN: 0,
        shrinkageWeight: 0,
        fallbackLevel: "global",
        candidateWeights: candidateStates.map(s => ({
          ...s,
          legacyWeight: Number.isFinite(Number(s.weight)) ? Number(s.weight) : 1,
          empiricalWeight: 1 / Math.max(1, candidateStates.length)
        })),
        rQuantity: { domain: [], probabilities: [], localN: 0, parentN: 0, shrinkageWeight: 0, fallbackLevel: "global" }
      };
    }

    const groupOf = x => ({
      condition: normalizeFieldCondition(x.record?.fieldCondition || x.record?.settlement?.fieldCondition || "unknown").id,
      box: String(x.record?.box || "未知箱型"),
      venue: String(x.record?.venue || "未知场地"),
      q: qBucketV06(x.record?.q)
    });
    const currentGroup = { condition, box, venue, q: qBucket };

    const countRows = (rows, keyFn, domainKeys) => {
      const counts = new Map(domainKeys.map(k => [k, 0]));
      for (const row of rows) {
        const k = keyFn(row);
        if (counts.has(k)) counts.set(k, counts.get(k) + 1);
      }
      return counts;
    };

    const blendCategorical = (prior, rows, keyFn, domainKeys) => {
      const n = rows.length;
      const k = domainKeys.length;
      const counts = countRows(rows, keyFn, domainKeys);
      const den = n + k;
      const local = new Map(domainKeys.map(key => [key, ((counts.get(key) || 0) + 1) / Math.max(1, den)]));
      const weight = n / (n + 8);
      return {
        probs: new Map(domainKeys.map(key => [key, (prior.get(key) || 0) * (1 - weight) + (local.get(key) || 0) * weight])),
        n,
        weight
      };
    };

    let prior = new Map(domain.map(k => [k, 1 / domain.length]));
    let parentN = 0;
    let best = { level: "global", n: 0, parentN: 0, weight: 0 };

    const levels = [
      { id: "global", rows: history },
      { id: "venue", rows: history.filter(x => groupOf(x).venue === currentGroup.venue) },
      { id: "box", rows: history.filter(x => groupOf(x).box === currentGroup.box) },
      { id: "condition", rows: history.filter(x => groupOf(x).condition === currentGroup.condition) },
      { id: "q-bucket", rows: history.filter(x => groupOf(x).q === currentGroup.q) },
      { id: "exact-condition-box-q", rows: history.filter(x => {
        const g = groupOf(x);
        return g.condition === currentGroup.condition && g.box === currentGroup.box && g.q === currentGroup.q;
      })}
    ];

    for (const level of levels) {
      const blended = blendCategorical(prior, level.rows, x => stateKey(x.truth.g, x.truth.p, x.truth.r), domain);
      if (blended.n) {
        prior = blended.probs;
        best = { level: level.id, n: blended.n, parentN, weight: blended.weight };
        parentN = blended.n;
      }
    }

    const candidateWeights = candidateStates.map(s => {
      const key = stateKey(s.G ?? s.g, s.P ?? s.p, s.R ?? s.r ?? 0);
      const mass = prior.get(key) || 0;
      const legacyWeight = Number.isFinite(Number(s.weight)) ? Number(s.weight) : 1;
      return { ...s, legacyWeight, empiricalWeight: mass };
    });
    const massTotal = candidateWeights.reduce((sum, x) => sum + (x.empiricalWeight || 0), 0) || 1;
    candidateWeights.forEach(x => { x.empiricalWeight /= massTotal; });

    return {
      version: "v0.6-shadow",
      status: "sidecar-only",
      localN: best.n,
      parentN: best.parentN,
      shrinkageWeight: best.weight,
      fallbackLevel: best.level,
      qBucket: currentGroup.q,
      candidateWeights
    };
  }

  // ==========================================
  // 7. 正式 Entry Decision
  // ==========================================

  function entryDecisionV06(ctx = {}, d = {}) {
    const market = d?.marketPrediction || {};
    const value = Number(d?.center ?? d?.formalValue?.ev);
    const marketP50 = Number(market.p50);
    const costInfo = resolveSessionCosts(ctx, d);
    const cost = costInfo.allCosts;
    const targetProfit = Math.max(0, Number.isFinite(Number(ctx?.targetProfit ?? d?.targetProfit ?? 30000)) ? Number(ctx?.targetProfit ?? d?.targetProfit ?? 30000) : 30000);

    if (!Number.isFinite(value) || value <= 0 || !Number.isFinite(marketP50) || marketP50 <= 0 || !Number.isFinite(cost)) {
      return {
        version: "v0.6-decision",
        status: "no-market",
        valueEstimate: Number.isFinite(value) ? value : null,
        marketP50: Number.isFinite(marketP50) && marketP50 > 0 ? marketP50 : null,
        cost: Number.isFinite(cost) ? cost : null,
        targetProfit,
        edge: null
      };
    }

    const edge = value - marketP50 - cost;
    const status = edge >= targetProfit ? "worth-entering" : edge > 0 ? "thin-entry" : "not-worth-entering";

    return {
      version: "v0.6-decision",
      status,
      valueEstimate: value,
      marketP50,
      cost,
      targetProfit,
      edge,
      marketStatus: market.status || "unknown",
      fallbackLevel: market.fallbackLevel || "global"
    };
  }

  // ==========================================
  // 8. 弱信息历史先验 (Weak Information Empirical Ground-Truth Prior)
  // Level 1: Q + P (N >= 5) -> Level 2: Q (N >= 5) -> Fallback: no-data
  // 严格基于历史 FINALIZED 的实际结算总值 actualTotal，杜绝未来泄露
  // ==========================================

  function weakValuePriorV06(ctx = {}, records = []) {
    const rawQ = ctx?.q;
    const rawP = ctx?.purpleCount ?? ctx?.purple ?? ctx?.p;
    const q = Number.isInteger(Number(rawQ)) && Number(rawQ) > 0 ? Number(rawQ) : null;
    const p = Number.isInteger(Number(rawP)) && Number(rawP) >= 0 ? Number(rawP) : null;

    if (q === null) {
      return {
        status: "no-data",
        level: null,
        sampleN: 0,
        p20: null,
        p50: null,
        p80: null,
        q: null,
        purpleCount: p,
        fallbackReason: "missing_q",
        source: "historical_actual_total"
      };
    }

    const now = historyTimestamp(ctx?.playedAt ?? ctx?.asOf ?? ctx?.targetPlayedAt);
    const allowed = Array.isArray(ctx?.allowedHistoryIds) ? new Set(ctx.allowedHistoryIds) : null;
    const historyList = Array.isArray(records) ? records : (records?.records || records?.matches || []);

    const validRows = [];
    for (const r of historyList) {
      if (!r || typeof r !== "object") continue;
      if (allowed && !allowed.has(r.id)) continue;

      // 1. Explicit exclusion of DRAFTs or cancelled records
      if (r.lifecycleStatus === "DRAFT" || r.lifecycleStatus === "CANCELLED" || r.status === "draft") continue;
      if (String(r.id || "").startsWith("draft_")) continue;

      // 2. Explicit truth qualification:
      // Canonical v7 requires lifecycleStatus === 'FINALIZED'.
      // Legacy 0.6 records lack lifecycleStatus, qualified if marked legacy/historical or containing verified settlement data.
      let isTruth = false;
      if (r.lifecycleStatus === "FINALIZED") {
        isTruth = true;
      } else if (r.lifecycleStatus === undefined || r.lifecycleStatus === null) {
        const isLegacySource = r.legacy === true || r.source === "historical" || r.source === "archive" || r.source === "manual" || r.source === "ocr";
        const hasSettlementEvidence = r.settlement !== undefined || r.outcome !== undefined || r.realizedState !== undefined || r.winner !== undefined;
        if (isLegacySource || hasSettlementEvidence) {
          isTruth = true;
        }
      }
      if (!isTruth) continue;

      // 3. Time safety: when now is specified, record MUST have a valid timestamp AND t < now. Undated records are excluded.
      const t = historyTimestamp(r.playedAt ?? r.date ?? r.createdAt);
      if (now !== null && (t === null || t >= now)) continue;

      // 4. Ground truth actualTotal must be positive finite number
      const actRaw = r.settlement?.actualTotal ?? r.actualTotal;
      const actualTotal = Number(actRaw);
      if (!Number.isFinite(actualTotal) || actualTotal <= 0) continue;

      const rqRaw = r.publicIntel?.q ?? r.q;
      const rq = Number.isInteger(Number(rqRaw)) ? Number(rqRaw) : null;
      if (rq === null) continue;

      const rpRaw = r.qualities?.purple?.count ?? r.purpleCount ?? r.purple ?? r.p;
      const rp = Number.isInteger(Number(rpRaw)) ? Number(rpRaw) : null;

      validRows.push({
        q: rq,
        p: rp,
        actualTotal
      });
    }

    let fallbackReason = null;
    if (p !== null) {
      const qpRows = validRows.filter(x => x.q === q && x.p === p);
      if (qpRows.length >= 5) {
        const values = qpRows.map(x => x.actualTotal);
        return {
          status: "valid",
          level: "q-purple",
          sampleN: values.length,
          p20: quantile(values, 0.2),
          p50: quantile(values, 0.5),
          p80: quantile(values, 0.8),
          q,
          purpleCount: p,
          fallbackReason: null,
          source: "historical_actual_total"
        };
      } else {
        fallbackReason = `purple_sample_insufficient_${qpRows.length}`;
      }
    }

    const qRows = validRows.filter(x => x.q === q);
    if (qRows.length >= 5) {
      const values = qRows.map(x => x.actualTotal);
      return {
        status: "valid",
        level: "q",
        sampleN: values.length,
        p20: quantile(values, 0.2),
        p50: quantile(values, 0.5),
        p80: quantile(values, 0.8),
        q,
        purpleCount: p,
        fallbackReason,
        source: "historical_actual_total"
      };
    }

    return {
      status: "no-data",
      level: null,
      sampleN: qRows.length,
      p20: null,
      p50: null,
      p80: null,
      q,
      purpleCount: p,
      fallbackReason: fallbackReason ? `${fallbackReason}_q_sample_insufficient_${qRows.length}` : `q_sample_insufficient_${qRows.length}`,
      source: "historical_actual_total"
    };
  }

  // ==========================================
  // 9. 冻结快照生成器 (Frozen Prediction Snapshot)
  // ==========================================

  const SOLVER_NAME = "auction_engine_v06";
  const SOLVER_VERSION = "v0.6-reliability";
  const MODEL_VERSION = "v0.6-shadow";

  function buildPredictionSnapshot(analysis = {}, d = {}, status = null) {
    const solverStatus = status || analysis.solverStatus || "valid";
    const inputHash = analysis.inputHash || solverInputHash(analysis);
    const round = Number(analysis.round) || 1;
    const condition = {
      fieldCondition: normalizeFieldCondition(analysis.fieldCondition || "unknown").id,
      avgValueBasis: analysis.avgValueBasis || "unknown",
      privateBidCap: analysis.privateBidCap ?? null,
      bidActionCount: analysis.bidActionCount ?? null,
      sparkle: analysis.sparkle || null,
      intelEvents: analysis.intelEvents || []
    };

    const provisional = solverStatus === "incomplete" || solverStatus === "fallback";

    return {
      ...(d.evidenceBounds ? {evidenceBounds:d.evidenceBounds} : {}),
      modelVersion: "v0.65",
      solverVersion: "v0.65",
      solverStatus,
      inputHash,
      catalogVersion: catalogVersionFor(analysis),
      solvedAt: analysis.solvedAt || new Date().toISOString(),
      round,
      ...condition,
      estimate: d.center != null && d.center !== "" && typeof d.center !== "boolean" && Number.isFinite(Number(d.center)) ? Number(d.center) : null,
      targetLine: provisional ? null : d.decision?.targetLine ?? null,
      globalLine: provisional ? null : d.decision?.globalLine ?? null,
      marginalLine: provisional ? null : d.decision?.marginalLine ?? null,
      workingLow: d.rawShadow?.p20 ?? d.low ?? null,
      workingHigh: d.rawShadow?.p80 ?? d.high ?? null,
      formalValue: d.formalValue || null,
      decision: d.decision ? JSON.parse(JSON.stringify(d.decision)) : null,
      rawShadow: d.rawShadow || null,
      shadowCalibrated: d.shadowCalibrated || null,
      empiricalStatePrior: d.empiricalStatePrior || null,
      marketPrediction: d.marketPrediction || null,
      entryDecision: d.entryDecision || null,
      roiOnTotalSpend: d.decision?.roiOnTotalSpend ?? null,
      roiOnPurchase: d.decision?.roiOnPurchase ?? null,
      costInfo: d.decision?.costInfo || resolveSessionCosts(analysis, d)
    };
  }

  function buildPredictionSnapshotV1(analysis = {}, d = {}, status = null, options = {}) {
    const solverStatus = status || analysis.solverStatus || "valid";
    const provisional = solverStatus === "incomplete" || solverStatus === "fallback";
    const diagnosticOnly = Boolean(analysis.diagnosticOnly || options.diagnosticOnly);

    const normalizedFacts = normalizeFactsForSnapshot(analysis);
    const inputHash = sha256Json(normalizedFacts);

    const solvedAt = analysis.solvedAt || options.solvedAt || new Date().toISOString();
    const informationCutoffAt = analysis.informationCutoffAt || options.informationCutoffAt || solvedAt;

    const matchId = String(analysis.matchId || analysis.id || options.matchId || "unknown_match").trim();
    const round = Number(normalizedFacts.round || analysis.round) || 1;

    const producer = {
      runtime: String(options.runtime || analysis.runtime || "overlay_runtime").trim(),
      solverName: SOLVER_NAME,
      solverVersion: SOLVER_VERSION,
      modelVersion: MODEL_VERSION,
      catalogVersion: catalogVersionFor(analysis),
      codeRevision: String(options.codeRevision || analysis.codeRevision || "dev-unversioned").trim()
    };

    const datasetRevision = options.datasetRevision || analysis.datasetRevision || null;

    const dec = d?.decision || {};
    const rawShadow = d?.rawShadow || null;
    const formalValue = d?.formalValue || {};
    const probProfile = analysis?.probabilityProfile || d?.probabilityProfile || {};

    const degradationLevel = d?.degradationLevel || dec?.degradationLevel || "structural_only";
    const coverageRatio = Number.isFinite(Number(dec.coverageRatio ?? probProfile.coverageRatio))
      ? Number(dec.coverageRatio ?? probProfile.coverageRatio)
      : (degradationLevel === "full_shadow" ? 1.0 : 0.0);

    let infoMode = "structural_only";
    if (degradationLevel === "full_shadow" && coverageRatio >= 0.999999) {
      infoMode = "full_shadow";
    } else if (degradationLevel === "partial_shadow" || (coverageRatio > 0 && coverageRatio < 0.999999)) {
      infoMode = "partial_shadow";
    } else {
      infoMode = "structural_only";
    }

    const supportedStateCount = Number(probProfile.supportedStateCount ?? dec.supportedStateCount) || (infoMode === "full_shadow" ? (analysis.stateCount || (d?.states ? d.states.length : 1)) : 0);
    const totalStateCount = Number(probProfile.totalStateCount ?? dec.totalStateCount) || (analysis.stateCount || (d?.states ? d.states.length : 1));

    const mode = {
      informationMode: infoMode,
      coverageRatio,
      supportedStateCount,
      totalStateCount
    };

    const stat = {
      solverStatus: diagnosticOnly ? "diagnostic" : solverStatus,
      provisional,
      diagnosticOnly
    };

    let forecast;
    if (infoMode === "full_shadow") {
      const p20 = Number(rawShadow?.p20 ?? dec.valueP20 ?? formalValue.p20 ?? 0);
      const p50 = Number(rawShadow?.p50 ?? dec.valueP50 ?? formalValue.p50 ?? 0);
      const p80 = Number(rawShadow?.p80 ?? dec.valueP80 ?? formalValue.p80 ?? 0);
      forecast = {
        target: "full_inventory_actual_total",
        scope: "full_inventory",
        quantiles: { p20, p50, p80 }
      };
    } else if (infoMode === "partial_shadow") {
      forecast = {
        target: "partial_inventory_conditional_total",
        scope: "partial_inventory_conditional",
        quantiles: null
      };
    } else {
      const sCenter = Number.isFinite(Number(formalValue?.ev)) ? Number(formalValue.ev) : (Number.isFinite(Number(dec?.structuralCenter)) ? Number(dec.structuralCenter) : null);
      const sMin = Number.isFinite(Number(formalValue?.candidateBounds?.min)) ? Number(formalValue.candidateBounds.min) : (Number.isFinite(Number(dec?.candidateBoundsMin)) ? Number(dec.candidateBoundsMin) : null);
      const sMax = Number.isFinite(Number(formalValue?.candidateBounds?.max)) ? Number(formalValue.candidateBounds.max) : (Number.isFinite(Number(dec?.candidateBoundsMax)) ? Number(dec.candidateBoundsMax) : null);
      const sRefBid = Number.isFinite(Number(dec?.structuralReferenceBid)) ? Number(dec.structuralReferenceBid) : null;
      forecast = {
        target: "structural_feasible_range",
        scope: "structural_inventory",
        quantiles: null,
        structural: {
          center: sCenter,
          feasibleRange: (sMin !== null && sMax !== null) ? [sMin, sMax] : null,
          candidateBoundsMin: sMin,
          candidateBoundsMax: sMax,
          recommendedMax: sRefBid
        }
      };
    }

    const identityPayload = {
      matchId,
      round,
      inputHash,
      datasetSha256: datasetRevision?.sha256 || "no-dataset",
      datasetCutoff: datasetRevision?.cutoffExclusive || "no-cutoff",
      solverName: producer.solverName,
      solverVersion: producer.solverVersion,
      modelVersion: producer.modelVersion,
      catalogVersion: producer.catalogVersion,
      codeRevision: producer.codeRevision,
      informationMode: mode.informationMode
    };
    const predictionId = `pred_${sha256Json(identityPayload)}`;

    const snapshot = {
      schemaVersion: "prediction-snapshot.v1",
      predictionId,
      matchId,
      solvedAt,
      informationCutoffAt,
      snapshotRole: "latest_valid_pre_settlement",
      producer,
      input: {
        contractVersion: 1,
        normalizedFacts,
        hashAlgorithm: "sha256",
        inputHash,
        datasetRevision: datasetRevision || {
          sourceId: "canonical_match_history",
          sha256: "0".repeat(64),
          recordCount: 0,
          admissionPolicyVersion: 1,
          cutoffExclusive: solvedAt,
          eligibleRecordIdsSha256: "0".repeat(64)
        }
      },
      mode,
      status: stat,
      forecast,
      frozen: true
    };

    if (d.evidenceBounds) snapshot.evidenceBounds = JSON.parse(JSON.stringify(d.evidenceBounds));
    return Object.freeze ? Object.freeze(JSON.parse(JSON.stringify(snapshot))) : snapshot;
  }

  // ==========================================
  // 10. 完整 v0.6 流水线 (Formal Pipeline Coordinator)
  // State Probability -> Formal Value -> Shadow -> Market -> Decision -> Snapshot
  // ==========================================

  function solveAuctionPipeline(rawCtx = {}, records = [], options = {}) {
    const ctx = {
      ...rawCtx,
      avg: rawCtx.avg ?? rawCtx.goldAvg,
      p: rawCtx.p ?? rawCtx.purple ?? rawCtx.purpleCount,
      goldCount: rawCtx.goldCount ?? rawCtx.g,
      redCount: rawCtx.redCount ?? rawCtx.red ?? rawCtx.r
    };
    const q = Number(ctx.q) || 0;
    const avg = Number(ctx.avg) || 0;
    const diagnosticOnly = Boolean(ctx.diagnosticOnly);
    const weakPrior = weakValuePriorV06(ctx, records);

    const sparkleLimited = conditionRules(ctx).sparkleEvidenceOnly === true;
    if (!q || !avg || sparkleLimited) {
      const fallbackWorking = {
        ...(sparkleLimited ? {evidenceBounds:sparkleEvidenceBounds(ctx)} : {}),
        center: null,
        low: null,
        high: null,
        rawShadow: null,
        shadowCalibrated: null,
        marketPrediction: marketPredictionV06(ctx, null, records),
        entryDecision: null,
        decision: {
          targetLine: null,
          globalLine: null,
          marginalLine: null,
          roiOnTotalSpend: null,
          roiOnPurchase: null,
          costInfo: resolveSessionCosts(ctx, {}),
          actionDirective: "🟡 等待完整求解 · 不生成正式推荐",
          actionReason: sparkleLimited ? "闪耀之心的宝石概率尚未确认，暂不生成整仓概率估值或出价建议" : "箱体件数 Q 或均价仍未揭晓，进入降级估算模式",
          entryGrade: "— 待定",
          isFold: false
        }
      };

      const frozenPrediction = buildPredictionSnapshot(ctx, fallbackWorking, "fallback");
      const predictionSnapshot = buildPredictionSnapshotV1(ctx, fallbackWorking, "fallback", options);

      return {
        solverStatus: "fallback",
        diagnosticOnly,
        stateCount: 0,
        states: [],
        candidateGs: [],
        candidatePs: [],
        stateProbabilities: [],
        empiricalStatePrior: empiricalStatePriorV06(ctx, [], records),
        weakValuePrior: weakPrior,
        formalValue: { p20: null, p50: null, p80: null, ev: null, rv: null },
        rawShadow: null,
        shadowCalibrated: null,
        market: fallbackWorking.marketPrediction,
        marketPrediction: fallbackWorking.marketPrediction,
        entryDecision: null,
        decision: fallbackWorking.decision,
        frozenPrediction,
        predictionSnapshot
      };
    }

    const sol = solveExactStatesSync(ctx);
    const states = sol.states || [];
    let status = sol.solverStatus || "valid";

    if (sol.searchCompleted === false) {
      status = states.length > 0 ? "incomplete" : "timeout";
    } else if (states.length === 0) {
      status = "no-match";
    } else {
      status = "valid";
    }

    if (states.length === 0) {
      const conflictWorking = {
        center: null,
        low: null,
        high: null,
        rawShadow: null,
        shadowCalibrated: null,
        marketPrediction: marketPredictionV06(ctx, null, records),
        entryDecision: null,
        decision: {
          targetLine: null,
          globalLine: null,
          marginalLine: null,
          roiOnTotalSpend: null,
          roiOnPurchase: null,
          costInfo: resolveSessionCosts(ctx, {}),
          actionDirective: "⚠️ 输入无可行解 · 暂停追价",
          actionReason: "当前输入条件与图鉴/场地倍率存在严格冲突，请核对抄录",
          entryGrade: "— 冲突",
          isFold: true
        }
      };

      const frozenPrediction = buildPredictionSnapshot(ctx, conflictWorking, status);
      const predictionSnapshot = buildPredictionSnapshotV1(ctx, conflictWorking, status, options);

      return {
        solverStatus: status,
        diagnosticOnly,
        stateCount: 0,
        states: [],
        candidateGs: [],
        candidatePs: [],
        stateProbabilities: [],
        empiricalStatePrior: empiricalStatePriorV06(ctx, [], records),
        weakValuePrior: weakPrior,
        formalValue: { p20: null, p50: null, p80: null, ev: null, rv: null },
        rawShadow: null,
        shadowCalibrated: null,
        market: conflictWorking.marketPrediction,
        marketPrediction: conflictWorking.marketPrediction,
        entryDecision: null,
        decision: conflictWorking.decision,
        frozenPrediction,
        predictionSnapshot
      };
    }

    // 1. State Probability (严格可行状态分布 & Empirical State Prior)
    const totalWeight = states.reduce((sum, s) => sum + (s.weight || 1), 0);
    const stateProbabilities = states.map(s => ({
      state: `${s.G}/${s.P}/${s.R}`,
      prob: (s.weight || 1) / totalWeight,
      value: s.stateValue ?? (s.minVal || (s.G * avg)),
      G: s.G,
      P: s.P,
      R: s.R
    }));
    const empiricalStatePrior = empiricalStatePriorV06(ctx, states, records);

    // 2. Structural value stats (NOT Shadow). These stay on structural fields only.
    const values = states.map(s => s.stateValue ?? (s.minVal || (s.G * avg))).sort((a, b) => a - b);
    const p20 = quantile(values, 0.2) ?? values[0];
    const p50 = quantile(values, 0.5) ?? values[Math.floor(values.length / 2)];
    const p80 = quantile(values, 0.8) ?? values[values.length - 1];
    const ev = Math.floor(stateProbabilities.reduce((sum, sp) => sum + sp.prob * sp.value, 0));
    const rv = p20;
    const hardLower = states.length > 0 ? Math.min(...states.map(s => s.stateLower ?? 0)) : 0;
    const formalValue = {
      p20, p50, p80, ev, rv,
      hardLower,
      theoreticalMin: hardLower > 0 ? hardLower : p20,
      theoreticalMax: p80,
      valueScope: "full-inventory-estimate"
    };

    // 3. True Shadow only if caller supplied a real probabilityProfile / shadowWhole.
    // Structural quantiles must never be copied into rawShadow.
    const incomingProfile = ctx.probabilityProfile || {};
    const trueShadowWhole = incomingProfile.shadowWhole || ctx.shadowWhole || null;
    const coverageProvided = incomingProfile.coverageRatio !== undefined || ctx.coverageRatio !== undefined;
    const coverageRatio = coverageProvided ? Number(incomingProfile.coverageRatio ?? ctx.coverageRatio) : 0;
    const hasTrueShadow = trueShadowWhole && Number.isFinite(Number(trueShadowWhole.p50)) && Number(trueShadowWhole.p50) > 0;
    const rawShadow = hasTrueShadow ? {
      p20: trueShadowWhole.p20 ?? null,
      p50: Number(trueShadowWhole.p50),
      p80: trueShadowWhole.p80 ?? null,
      width: Math.max(0, Number(trueShadowWhole.p80 || 0) - Number(trueShadowWhole.p20 || 0)),
      entropy: trueShadowWhole.entropy ?? null
    } : null;
    const shadowCalibrated = rawShadow ? shadowCalibrationSidecarV06(ctx, { rawShadow, center: ev, low: p20, high: p80 }, records) : null;

    const probabilityProfile = {
      ...incomingProfile,
      coverageRatio,
      supportedStateCount: Number(incomingProfile.supportedStateCount) || (hasTrueShadow && coverageRatio >= 0.999999 ? states.length : 0),
      totalStateCount: Number(incomingProfile.totalStateCount) || states.length,
      supportedWeight: Number(incomingProfile.supportedWeight) || 0,
      totalWeight: Number(incomingProfile.totalWeight) || 0,
      shadowWhole: hasTrueShadow && coverageRatio >= 0.999999 ? trueShadowWhole : null,
      partialShadowP20: incomingProfile.partialShadowP20 ?? (hasTrueShadow && coverageRatio > 0 && coverageRatio < 1 ? trueShadowWhole.p20 : null),
      partialShadowP50: incomingProfile.partialShadowP50 ?? (hasTrueShadow && coverageRatio > 0 && coverageRatio < 1 ? trueShadowWhole.p50 : null),
      partialShadowP80: incomingProfile.partialShadowP80 ?? (hasTrueShadow && coverageRatio > 0 && coverageRatio < 1 ? trueShadowWhole.p80 : null),
      stateCandidates: incomingProfile.stateCandidates || states
    };

    // 4. Market Model (Hierarchical Shrinkage)
    const marketPrediction = marketPredictionV06(ctx, ev, records);

    // 5. Entry Decision
    const entryDecision = entryDecisionV06(ctx, { marketPrediction, center: ev, formalValue });

    // 6. Decision Lines — coverage 缺省为 0，走 STRUCTURAL_ONLY
    const decLines = calculateV06DecisionLines(ctx, {
      solverStatus: status,
      center: ev,
      low: p20,
      high: p80,
      formalValue,
      structuralCenter: ev,
      hardFloor: p20,
      states,
      shadowCalibrated,
      rawShadow,
      marketPrediction,
      probabilityProfile,
      coverageRatio
    }, ctx.leaderBid ?? null);

    const candidateBoundsMin = decLines.candidateBoundsMin ?? (values.length > 0 ? Math.min(...values) : null);
    const candidateBoundsMax = decLines.candidateBoundsMax ?? (values.length > 0 ? Math.max(...values) : null);
    formalValue.candidateBounds = (candidateBoundsMin !== null && candidateBoundsMax !== null) ? {
      min: candidateBoundsMin,
      max: candidateBoundsMax
    } : null;
    formalValue.structuralCenter = ev;
    formalValue.structuralReferenceBid = decLines.structuralReferenceBid;

    const hiddenBids = conditionRules(ctx).hiddenBids === true;
    const leaderBid = hiddenBids ? 0 : Number(ctx.leaderBid) || 0;
    const isFull = decLines.degradationLevel === "full_shadow" && decLines.valueP50 != null;
    const isPartial = decLines.degradationLevel === "partial_shadow";
    const isStructural = decLines.degradationLevel === "structural_only";
    const isFold = isFull && decLines.marginalLine !== null && leaderBid > 0 ? leaderBid > decLines.marginalLine : false;
    const isThin = isFull && decLines.globalLine !== null && leaderBid > 0 ? leaderBid > decLines.globalLine : false;

    let action, reason, grade;
    if (isFull) {
      action = "🟢 预期仍有盈余 · 可参考";
      reason = "按整仓P50与当前叫价扣除整局成本后仍有预期盈余";
      grade = "A+ 推荐";
      if (decLines.expectedProfit === null) {
        action = "等待当前叫价 · 暂无盈亏判断";
        reason = "保本价已就绪，填写当前叫价后显示预期盈亏";
        grade = "— 待定";
        if (hiddenBids) {
          action = "出价隐藏 · 暂无追价盈亏判断";
          reason = "本词条出价金额不可见；保本线仅作私人出价参考，不使用旧叫价判断追价盈亏";
        }
      } else if (decLines.expectedProfit === 0) {
        action = "🟡 预期刚好保本";
        reason = "按整仓P50扣除叫价和整局成本后为0，没有预期盈余";
        grade = "B 保本";
      } else if (isFold) {
        action = "🔴 超过边际追价线 · 建议停止";
        reason = "当前叫价已超过边际保本线，继续跟价将产生纯亏损";
        grade = "D 放弃";
      } else if (isThin) {
        action = "🟡 已进入薄利区 · 谨慎跟价";
        reason = "当前叫价已超出全局全成本线，仅剩边际利润";
        grade = "B 薄利";
      } else if (decLines.safeBuy !== null && leaderBid > decLines.safeBuy) {
        action = "🟡 已超目标利润价 · 谨慎跟价";
        reason = "当前叫价仍在全成本保本线内，但已不满足设定的利润目标";
        grade = "B 未达目标";
      }
    } else if (isPartial) {
      action = "🟡 部分历史覆盖 · 非正式整仓估值";
      reason = `仅覆盖部分结构（${((decLines.coverageRatio || 0) * 100).toFixed(1)}%），条件 P50 不能当作整仓 P50`;
      grade = "结构/条件";
    } else if (isStructural) {
      action = "🟡 结构参考 · 无整仓 P50";
      reason = "当前只有可行状态结构，没有真实历史 Shadow，不生成正式三线";
      grade = "结构参考";
    } else {
      action = "🟡 等待完整求解 · 不生成正式推荐";
      reason = "缺少足够结构或概率事实";
      grade = "— 待定";
    }

    if (diagnosticOnly) {
      action = `[诊断模式] ${action}`;
    }

    const workingDecision = {
      center: ev,
      low: p20,
      high: p80,
      formalValue,
      rawShadow,
      shadowCalibrated,
      empiricalStatePrior,
      marketPrediction,
      entryDecision,
      degradationLevel: decLines.degradationLevel,
      decision: {
        hiddenBids,
        targetLine: decLines.targetLine,
        globalLine: decLines.globalLine,
        marginalLine: decLines.marginalLine,
        expectedProfit: decLines.expectedProfit,
        roiOnTotalSpend: decLines.roiOnTotalSpend,
        roiOnPurchase: decLines.roiOnPurchase,
        costInfo: decLines.costInfo,
        actionDirective: action,
        actionReason: reason,
        entryGrade: grade,
        isFold,
        degradationLevel: decLines.degradationLevel,
        valueP50: decLines.valueP50,
        safeBuy: decLines.safeBuy,
        recommendedMax: decLines.recommendedMax,
        chaseLimit: decLines.chaseLimit,
        hardFloor: decLines.hardFloor,
        theoreticalMin: decLines.theoreticalMin,
        theoreticalMax: decLines.theoreticalMax,
        structuralCenter: decLines.structuralCenter,
        candidateBoundsMin,
        candidateBoundsMax,
        structuralReferenceBid: decLines.structuralReferenceBid,
        coverageRatio: decLines.coverageRatio,
        isFullShadow: decLines.isFullShadow,
        partialShadowP20: decLines.partialShadowP20,
        partialShadowP50: decLines.partialShadowP50,
        partialShadowP80: decLines.partialShadowP80,
        supportedStateCount: decLines.supportedStateCount,
        totalStateCount: decLines.totalStateCount,
        missingReason: decLines.missingReason,
        missingClues: decLines.missingClues
      }
    };

    const frozenPrediction = buildPredictionSnapshot(ctx, workingDecision, status);
    const predictionSnapshot = buildPredictionSnapshotV1(ctx, workingDecision, status, options);

    return {
      solverStatus: status,
      diagnosticOnly,
      degradationLevel: decLines.degradationLevel,
      stateCount: states.length,
      states,
      candidateGs: sol.candidateGs || [],
      candidatePs: sol.candidatePs || [],
      stateProbabilities,
      empiricalStatePrior,
      weakValuePrior: weakPrior,
      formalValue,
      rawShadow,
      shadowCalibrated,
      probabilityProfile,
      market: marketPrediction,
      marketPrediction,
      entryDecision,
      decision: workingDecision.decision,
      frozenPrediction,
      predictionSnapshot
    };
  }

  // ==========================================
  // 10. 可靠性自测套件 (Zero DOM Dependencies)
  // ==========================================

  function runV06ReliabilitySelfTests() {
    const tests = [];

    // 1. 15:53 经典回归测试 (Q=9, P=5, GoldAvg=33538, KnownPurple=18075+8128, KnownGold=51077, rounding=floor)
    const test1553 = solveExactStatesSync({
      q: 9,
      p: 5,
      avg: 33538,
      roundingMode: "floor",
      knownPurple: "拈花小像+金角月芒",
      knownGold: "万有星仪"
    });
    const states1553 = test1553.states.map(s => `${s.G}/${s.P}/${s.R}`);
    const hasG3P5R1 = states1553.includes("3/5/1");
    const hasG4P5R0 = states1553.includes("4/5/0");

    tests.push({
      name: "15:53-regression-not-no-match",
      passed: test1553.solverStatus === "valid" && test1553.states.length > 0,
      solverStatus: test1553.solverStatus,
      states: test1553.states.length
    });

    tests.push({
      name: "15:53-regression-required-states",
      passed: hasG3P5R1 && hasG4P5R0,
      states: states1553
    });

    // 2. 红色重复 R=2 回归测试
    const testRedRepeat = minimumConstraintAssignment([[redItemsPriceList(), 2]], RED_ITEMS, 2);
    tests.push({
      name: "red-repeat-two-regression",
      passed: testRedRepeat.feasible && testRedRepeat.assigned === 2
    });

    // 3. 成本独立性与 ROI 计算测试 (Level 1 Full Shadow)
    const testCosts = resolveSessionCosts({ costs: { entry: 5000, intel: 45000, sunkCost: 50000, futureIncrementalCost: 10000 } });
    const testLines = calculateV06DecisionLines({ costs: testCosts }, { center: 400000, low: 350000, coverageRatio: 1, rawShadow: { p50: 400000 } }, 300000);
    const costPass = testCosts.allCosts === 60000 &&
                     testLines.degradationLevel === "full_shadow" &&
                     testLines.globalLine === (400000 - 60000) &&
                     testLines.marginalLine === (400000 - 10000) &&
                     testLines.globalLine < testLines.marginalLine;

    tests.push({
      name: "sunk-cost-marginal-line-independence",
      passed: costPass,
      globalLine: testLines.globalLine,
      marginalLine: testLines.marginalLine
    });

    // 4. Market Hierarchical Shrinkage 回归测试
    const testMarketRecords = [0, 1, 2, 3, 4, 5, 6, 7, 8].map(i => ({
      id: `__market_${i}`,
      playedAt: `2026-08-10T00:0${i}:00`,
      venue: "V",
      box: "B",
      fieldCondition: "standard",
      q: 9,
      clearingPrice: 80000 + i * 2000,
      prediction: { estimate: 100000 }
    }));
    const testMarket = marketPredictionV06({ playedAt: "2026-08-12T00:00:00", venue: "V", box: "B", fieldCondition: "standard", q: 9 }, 100000, testMarketRecords);
    tests.push({
      name: "market-hierarchical-shrinkage",
      passed: testMarket.status === "shrunk" && testMarket.localN === 9 && testMarket.fallbackLevel === "exact-condition-box-q" && testMarket.p50 > 0,
      status: testMarket.status,
      fallbackLevel: testMarket.fallbackLevel,
      p50: testMarket.p50
    });

    // 5. Shadow Calibration Sidecar 回归测试
    const testShadowRecords = [0, 1, 2, 3, 4, 5].map(i => ({
      id: `__shadow_${i}`,
      playedAt: `2026-08-10T00:0${i}:00`,
      actualTotal: 110000 + i * 1000,
      prediction: { estimate: 100000, rawShadow: { p20: 80000, p50: 100000, p80: 120000 } }
    }));
    const testShadow = shadowCalibrationSidecarV06({ playedAt: "2026-08-12T00:00:00" }, { rawShadow: { p20: 80000, p50: 100000, p80: 120000 }, center: 100000 }, testShadowRecords);
    tests.push({
      name: "shadow-calibration-widens-oos-range",
      passed: testShadow?.status === "calibrated-sidecar" && testShadow.calibrated.p50 === 100000 && testShadow.residualN === 6,
      status: testShadow?.status,
      residualN: testShadow?.residualN
    });

    // 6. solverStatus 语义测试
    const testFallback = solveAuctionPipeline({ q: 9 }); // missing avg
    const testValid = solveAuctionPipeline({ q: 9, avg: 33538, p: 5, knownPurple: "拈花小像+金角月芒", knownGold: "万有星仪" });
    const testNoMatch = solveAuctionPipeline({ q: 9, avg: 999999999 });

    tests.push({
      name: "solver-status-semantics",
      passed: testFallback.solverStatus === "fallback" && testValid.solverStatus === "valid" && testNoMatch.solverStatus === "no-match",
      fallbackStatus: testFallback.solverStatus,
      validStatus: testValid.solverStatus,
      noMatchStatus: testNoMatch.solverStatus
    });

    // 7. Graceful Degradation 三级降级自测
    const lvl1 = calculateV06DecisionLines({ costs: { entry: 5000 } }, { solverStatus: "valid", states: [{ G: 3, P: 5, R: 1 }], coverageRatio: 1, rawShadow: { p50: 500000 } });
    const lvl2 = calculateV06DecisionLines({ costs: { entry: 5000 } }, { solverStatus: "valid", states: [{ G: 3, P: 5, R: 1 }], formalValue: { theoreticalMin: 300000, theoreticalMax: 800000, ev: 450000 } });
    const lvl3 = calculateV06DecisionLines({ costs: { entry: 5000 } }, { solverStatus: "incomplete" });

    const degradationPass = lvl1.degradationLevel === "full_shadow" && lvl1.valueP50 === 500000 && lvl1.recommendedMax === 495000 &&
                           lvl2.degradationLevel === "structural_only" && lvl2.valueP50 === null && lvl2.recommendedMax === null && lvl2.structuralReferenceBid === 445000 &&
                           lvl3.degradationLevel === "insufficient" && lvl3.isSuppressed === true && lvl3.valueP50 === null;

    tests.push({
      name: "graceful-degradation-levels",
      passed: degradationPass,
      lvl1: lvl1.degradationLevel,
      lvl2: lvl2.degradationLevel,
      lvl3: lvl3.degradationLevel
    });

    const passedAll = tests.every(t => t.passed);
    return {
      passed: passedAll,
      tested: tests.length,
      tests
    };
  }

  function redItemsPriceList() {
    return RED_ITEMS.map(x => Number(x[1]));
  }

  return {
    PRE_0813_GOLD_ITEMS,
    PRE_0813_PURPLE_ITEMS,
    PRE_0813_RED_ITEMS,
    PRE_0813_BLUE_ITEMS,
    PRE_0813_GREEN_ITEMS,
    PRE_0813_WHITE_ITEMS,
    GOLD_ITEMS,
    PURPLE_ITEMS,
    RED_ITEMS,
    BLUE_ITEMS,
    GREEN_ITEMS,
    WHITE_ITEMS,
    CATALOG_SNAPSHOTS,
    FIELD_CONDITIONS,
    FIELD_CONDITION_ALIASES,
    normalizeFieldCondition,
    sparkleEvidenceBounds,
    catalogVersionFor,
    conditionRules,
    baseCatalogFor,
    effectiveCatalog,
    minimumConstraintAssignment,
    parseFlexibleKnown,
    parseOr,
    parseKnownItems,
    normalizeKnownContext,
    validateKnownInput,
    bounds,
    tables,
    jointTables,
    groupsSatisfiedWithCapacity,
    solveExactStatesSync,
    resolveSessionCosts,
    calculateStateEntropy,
    calculateShadowWidth,
    createIntelEventRecord,
    calculateV06DecisionLines,
    quantile,
    weightedQuantile,
    mean,
    historyTimestamp,
    nonNegativeOrNull,
    actualInRange,
    fastHash,
    stableHashValue,
    solverInputPayload,
    solverInputHash,
    qBucketV06,
    marketPredictionV06,
    shadowCalibrationSidecarV06,
    empiricalStatePriorV06,
    weakValuePriorV06,
    purpleValueForState,
    redValueForState,
    lowTierValue,
    LOW_TIER_ITEM_RATE,
    LOW_TIER_GRID_RATE,
    LOW_TIER_PRIOR,
    entryDecisionV06,
    buildPredictionSnapshot,
    buildPredictionSnapshotV1,
    normalizeFactsForSnapshot,
    canonicalJson,
    sha256Hex,
    sha256Json,
    SOLVER_NAME,
    SOLVER_VERSION,
    MODEL_VERSION,
    solveAuctionPipeline,
    runV06ReliabilitySelfTests
  };
}));
