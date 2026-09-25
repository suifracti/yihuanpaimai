
    "use strict";

    // 图鉴快照必须按版本冻结：旧对局回放不能被 8.13 新价格“穿越”改写。
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
    const replaceCatalogItem=(items,name,next)=>items.map(item=>item[0]===name?next:item);
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
    const GOLD_PRICES = GOLD_ITEMS.map(x=>x[1]);
    const GOLD_GRIDS = GOLD_ITEMS.map(x=>{const [w,h]=String(x[2]).split("x").map(Number);return (w||0)*(h||0);});
    // 金色占格会进入二维离散求解。超过这个范围时，DP 表和组合搜索的
    // 规模会随 Q×格数膨胀；真实箱体远低于此值，超出则要求用户先核对抄录。
    const GRID_SOLVER_MAX=240, TOTAL_GRID_INPUT_MAX=2000;
    const GOLD_NAMES = Object.fromEntries(GOLD_ITEMS.map(x=>[x[1],x[0]]));
    const CATALOG_VERSION_PRE_0813="pre-2026-08-13",CATALOG_VERSION_0813="2026-08-13";
    const CATALOG_SNAPSHOTS={
      [CATALOG_VERSION_PRE_0813]:{gold:PRE_0813_GOLD_ITEMS,purple:PRE_0813_PURPLE_ITEMS,red:PRE_0813_RED_ITEMS,blue:PRE_0813_BLUE_ITEMS,green:PRE_0813_GREEN_ITEMS,white:PRE_0813_WHITE_ITEMS},
      [CATALOG_VERSION_0813]:{gold:GOLD_ITEMS,purple:PURPLE_ITEMS,red:RED_ITEMS,blue:BLUE_ITEMS,green:GREEN_ITEMS,white:WHITE_ITEMS}
    };
    const CATALOG_NAME_ALIASES={"觊觎钱币":"凯飒钱币","心猎铁骑L3--以当千":"心猎铁骑L3——以当千"};
    const FIELD_CONDITIONS={
      unknown:{id:"unknown",name:"未知场地条件",goldMultiplier:1,purpleMultiplier:1,historyGroup:"unknown"},
      standard:{id:"standard",name:"标准对局",goldMultiplier:1,purpleMultiplier:1,historyGroup:"base"},
      dark:{id:"dark",name:"天黑了",goldMultiplier:1,purpleMultiplier:1,historyGroup:"base",hiddenBids:true},
      extraIntel:{id:"extraIntel",name:"一手情报",goldMultiplier:1,purpleMultiplier:1,historyGroup:"base",freeIntelRounds:[1,3]},
      purpleDouble:{id:"purpleDouble",name:"加倍！！",goldMultiplier:1,purpleMultiplier:2,historyGroup:"purpleDouble"},
      goldDouble:{id:"goldDouble",name:"加倍！！！",goldMultiplier:2,purpleMultiplier:1,historyGroup:"goldDouble"},
      sparkle:{id:"sparkle",name:"闪耀之心",goldMultiplier:1,purpleMultiplier:1,historyGroup:"sparkle",sparkleEvidenceOnly:true},
      welfare:{id:"welfare",name:"福利多多",goldMultiplier:1,purpleMultiplier:1,historyGroup:"base",welfareRate:.30},
      gemMaze:{id:"gemMaze",name:"宝石迷阵",goldMultiplier:1,purpleMultiplier:1,historyGroup:"base"}
    };
    const FIELD_CONDITION_ALIASES={"":"unknown","unknown":"unknown","未知":"unknown","standard":"standard","标准":"standard","标准对局":"standard","dark":"dark","天黑了":"dark","extraIntel":"extraIntel","extra_intel":"extraIntel","first_intel":"extraIntel","一手情报":"extraIntel","purpleDouble":"purpleDouble","purple_double":"purpleDouble","紫色加倍":"purpleDouble","加倍！！":"purpleDouble","goldDouble":"goldDouble","gold_double":"goldDouble","金色加倍":"goldDouble","加倍！！！":"goldDouble","sparkle":"sparkle","shining_heart":"sparkle","闪耀之心":"sparkle","welfare":"welfare","福利多多":"welfare","gemMaze":"gemMaze","gem_maze":"gemMaze","宝石迷阵":"gemMaze","宝石迷宫":"gemMaze"};
    const GEM_1X1_NAMES=["「永恒之心」","「泪滴」","绯红宝石","桂冠","落日珍珠","饕目","月白沙","幽灵态","霞红钻","银铃","无梦果核","金月","肥皂","金色飞球","崭新的弹珠","绿林"];
    function normalizeFieldCondition(value){
      const raw=value&&typeof value==="object"?(value.id??value.name??value.type??value.value):value,key=FIELD_CONDITION_ALIASES[String(raw??"").trim()]||"unknown";
      return {...FIELD_CONDITIONS[key],raw:raw??null};
    }
    function catalogVersionFor(ctx={}){
      const explicit=ctx.catalogVersion??ctx.catalog?.version;if(explicit&&(CATALOG_SNAPSHOTS[explicit]||explicit==="unknown"))return explicit;
      if(ctx.legacy===true||/旧版本|旧版/.test(String(ctx.patch||ctx.productVersion||"")))return CATALOG_VERSION_PRE_0813;
      const raw=ctx.playedAt??ctx.date,stamp=raw?Date.parse(String(raw).includes("T")?String(raw):String(raw).replace(" ","T")):NaN;
      if(Number.isFinite(stamp))return stamp<Date.parse("2026-08-13T00:00:00+08:00")?CATALOG_VERSION_PRE_0813:CATALOG_VERSION_0813;
      return "unknown";
    }
    function conditionRules(ctx={}){return normalizeFieldCondition(ctx.fieldCondition??ctx.condition??ctx.fieldMode);}
    function baseCatalogFor(ctx={}){return CATALOG_SNAPSHOTS[catalogVersionFor(ctx)]||CATALOG_SNAPSHOTS[CATALOG_VERSION_0813];}
    function resolveKnownCatalogItem(ctx={},quality,name){
      const rarity=({gold:"gold",purple:"purple",red:"red"})[String(quality||"").trim().toLowerCase()];
      const inputName=String(name||"").trim();
      if(!rarity||!inputName)return null;
      const canonical=CATALOG_NAME_ALIASES[inputName]||inputName;
      const matches=(baseCatalogFor(ctx)[rarity]||[]).filter(item=>Array.isArray(item)&&(item[0]===inputName||item[0]===canonical));
      if(matches.length!==1)return null;
      const [resolvedName,rawPrice,rawSize]=matches[0],price=Number(rawPrice),size=String(rawSize||"");
      const dimensions=size.match(/^(\d+)x(\d+)$/i);
      if(!Number.isFinite(price)||price<=0||!dimensions||Number(dimensions[1])<=0||Number(dimensions[2])<=0)return null;
      return {inputName,name:resolvedName,quality:rarity,price,size,width:Number(dimensions[1]),height:Number(dimensions[2]),catalogVersion:catalogVersionFor(ctx)};
    }
    function conditionPriceMultiplier(ctx,rarity){const rules=conditionRules(ctx);return rarity==="gold"?rules.goldMultiplier:rarity==="purple"?rules.purpleMultiplier:1;}
    function effectiveCatalog(ctx={}){
      const base=baseCatalogFor(ctx),rules=conditionRules(ctx),scale=(items,m)=>items.map(x=>[x[0],Number(x[1])*m,x[2]]);
      return {version:catalogVersionFor(ctx),condition:rules,gold:scale(base.gold,rules.goldMultiplier),purple:scale(base.purple,rules.purpleMultiplier),red:scale(base.red,1),blue:scale(base.blue,1),green:scale(base.green,1),white:scale(base.white,1)};
    }
    function gemTargetPool(ctx={}){
      const base=baseCatalogFor(ctx),rarities=["red","gold","purple","blue","green","white"],wanted=new Set(GEM_1X1_NAMES),out=[];
      for(const rarity of rarities)for(const item of base[rarity]||[])if(wanted.has(item[0])&&item[2]==="1x1")out.push({name:item[0],price:Number(item[1]),size:item[2],rarity});
      return out;
    }
    function sparkleEvidenceBounds(ctx={}){
      const rules=conditionRules(ctx);if(!rules.sparkleEvidenceOnly)return null;
      const pool=gemTargetPool(ctx),prices=pool.map(x=>x.price),pi=ctx.publicInfo||{},countCandidates=[ctx.transformedOneByOneCount,ctx.oneByOneCount,ctx.sparkle?.transformedOneByOneCount,pi.transformedOneByOneCount,pi.oneByOneCount],countRaw=countCandidates.find(x=>hasNumber(x)&&Number.isInteger(Number(x))&&Number(x)>=0),count=countRaw===undefined?null:Number(countRaw),rawKnown=ctx.knownGemItems??ctx.verifiedGemItems??ctx.sparkle?.verifiedGemItems??[],tokens=Array.isArray(rawKnown)?rawKnown:String(rawKnown||"").split(/[+，,、；;\n]/).map(x=>x.trim()).filter(Boolean),known=[];
      const nameKey=value=>String(value||"").replace(/[「」『』【】\[\]()（）\s]/g,"").trim();
      for(const token of tokens){if(token&&typeof token==="object"&&Number.isFinite(Number(token.price))){known.push(Number(token.price));continue;}const text=String(token),tokenKey=nameKey(text.replace(/[*×x]\s*\d+/i,"")),mult=Math.max(1,Number((text.match(/[*×x]\s*(\d+)/i)||[])[1])||1),named=pool.find(x=>{const itemKey=nameKey(x.name);return tokenKey===itemKey||tokenKey.includes(itemKey)||itemKey.includes(tokenKey);}),numeric=(text.match(/\d[\d,]*/g)||[]).map(x=>Number(x.replaceAll(",",""))).find(x=>pool.some(item=>item.price===x)),price=named?.price??numeric;if(Number.isFinite(price))for(let i=0;i<mult;i++)known.push(price);}
      const knownTotal=known.reduce((s,x)=>s+x,0),unknown=count===null?null:Math.max(0,count-known.length),unitMin=prices.length?Math.min(...prices):null,unitMax=prices.length?Math.max(...prices):null;
      return {mode:"evidence-only",probabilityKnown:false,recommendationAllowed:false,targetPoolSize:pool.length,count,knownCount:known.length,knownTotal,unitMin,unitMax,lower:unknown===null?knownTotal:knownTotal+unknown*unitMin,upper:unknown===null?null:knownTotal+unknown*unitMax,pool};
    }
    function fieldConditionAnalysis(ctx={}){const rules=conditionRules(ctx);return {id:rules.id,name:rules.name,catalogVersion:catalogVersionFor(ctx),goldMultiplier:rules.goldMultiplier,purpleMultiplier:rules.purpleMultiplier,historyGroup:rules.historyGroup,welfareRate:rules.welfareRate??null,freeIntelRounds:rules.freeIntelRounds||[],hiddenBids:!!rules.hiddenBids,sparkleEvidence:sparkleEvidenceBounds(ctx)};}
    const ALL_ITEMS = [
      ...RED_ITEMS.map(x => ({id:`red:${x[0]}:${x[2]}`,name:x[0],price:x[1],size:x[2],rarity:"red"})),
      ...GOLD_ITEMS.map(x => ({id:`gold:${x[0]}:${x[2]}`,name:x[0],price:x[1],size:x[2],rarity:"gold"})),
      ...PURPLE_ITEMS.map(x => ({id:`purple:${x[0]}:${x[2]}`,name:x[0],price:x[1],size:x[2],rarity:"purple"})),
      ...BLUE_ITEMS.map(x => ({id:`blue:${x[0]}:${x[2]}`,name:x[0],price:x[1],size:x[2],rarity:"blue"})),
      ...GREEN_ITEMS.map(x => ({id:`green:${x[0]}:${x[2]}`,name:x[0],price:x[1],size:x[2],rarity:"green"})),
      ...WHITE_ITEMS.map(x => ({id:`white:${x[0]}:${x[2]}`,name:x[0],price:x[1],size:x[2],rarity:"white"}))
    ];
    const areaOf=size=>size.split("x").map(Number).reduce((a,b)=>a*b,1);
    const catalogMedian=items=>median(items.map(x=>x[1]));
    const catalogPerGridMedian=items=>median(items.map(x=>x[1]/areaOf(x[2])));
    const PURPLE_WORKING_AVG = PURPLE_ITEMS.reduce((s,x)=>s+x[1],0)/PURPLE_ITEMS.length;
    const RED_COMMON_ITEMS = RED_ITEMS.filter(x=>x[1] < 400000);
    const RED_JACKPOT_ITEMS = RED_ITEMS.filter(x=>x[1] >= 400000);
    const RED_COMMON_PRICES = RED_COMMON_ITEMS.map(x=>x[1]);
    const RED_WORKING_AVG = median(RED_COMMON_PRICES) ?? 61803;
    const RED_TYPICAL_LOW = quantile(RED_COMMON_PRICES,.25) ?? 31618;
    const RED_TYPICAL_HIGH = quantile(RED_COMMON_PRICES,.75) ?? 101860;
    const RED_JACKPOT_AVG = mean(RED_JACKPOT_ITEMS.map(x=>x[1])) || 5e6;
    const RED_PRESENCE_PRIOR = {"初级场 · 海贝场":0.18,"中级场 · 珊瑚场":0.28,"高级场 · 真珠场":0.40,"未知场地":0.25};
    const RED_BOOST_BOX_RE = /红色|高级藏品|古董|宝石|科技/;
    const LOW_TIER_GRID_RATE={blue:809,green:452,white:92}, LOW_TIER_ITEM_RATE={blue:2954,green:1189,white:203};
    const LOW_TIER_PRIOR = {"初级场 · 海贝场":8000,"中级场 · 珊瑚场":12000,"高级场 · 真珠场":30000,"未知场地":12000};
    const EMPTY_VENUE_PRIOR = {"初级场 · 海贝场":160000,"中级场 · 珊瑚场":500000,"高级场 · 真珠场":800000,"未知场地":300000};
    const VENUE_BOXES = {
      "未知场地": ["未知箱型"],
      "初级场 · 海贝场": ["破损的包裹 · 紫色提升","完整的包裹 · 金色提升","浸水的包裹 · 紫色提升","无名包裹 · 红色提升"],
      "中级场 · 珊瑚场": ["机械宝箱 · 科技类概率提升","美食宝箱 · 食品类概率提升","实木宝箱 · 中级藏品概率提升","琉璃宝箱 · 宝石类概率提升","皮制宝箱 · 高级藏品概率提升","螺钿宝箱 · 古董类概率提升"],
      "高级场 · 真珠场": ["未知高级场箱型"]
    };
    const VENUE_ALIASES = {"初级场":"初级场 · 海贝场","海贝场":"初级场 · 海贝场","中级场":"中级场 · 珊瑚场","珊瑚场":"中级场 · 珊瑚场","高级场":"高级场 · 真珠场","真珠场":"高级场 · 真珠场","珍珠场":"高级场 · 真珠场","终极场":"高级场 · 真珠场"};
    const BOX_ALIASES = {
      "破损":"破损的包裹 · 紫色提升","破损的包裹 · 低级提升":"破损的包裹 · 紫色提升",
      "完整":"完整的包裹 · 金色提升","完整（中级藏品提升）":"完整的包裹 · 金色提升","完整的包裹 · 中级提升":"完整的包裹 · 金色提升",
      "浸水":"浸水的包裹 · 紫色提升","浸水的包裹 · 低级提升":"浸水的包裹 · 紫色提升",
      "无名":"无名包裹 · 红色提升","无名包裹 · 高级提升":"无名包裹 · 红色提升",
      "机械宝箱":"机械宝箱 · 科技类概率提升","美食宝箱":"美食宝箱 · 食品类概率提升","实木宝箱":"实木宝箱 · 中级藏品概率提升",
      "琉璃宝箱":"琉璃宝箱 · 宝石类概率提升","皮制宝箱":"皮制宝箱 · 高级藏品概率提升","螺钿宝箱":"螺钿宝箱 · 古董类概率提升"
    };

    const LEGACY_HISTORY = [
      ["皮制宝箱",11,905617,null,"皮制局 57W手提箱+乔望尼"],["琉璃宝箱",8,1319934,null,"琉璃百万局"],["机械宝箱",8,655807,null,"机械乔望尼+大饼+随心泥"],["美食宝箱",13,503741,null,"美食条纹椰排雷"],["实木宝箱",11,135082,40670,"实木低金均价排雷"],["螺钿宝箱",26,1130661,63324,"高Q稀释旧样本"],["美食宝箱",9,149827,null,"0道具低值局"],["实木宝箱",9,336712,null,"轮椅假大件"],["皮制宝箱",8,325404,null,"皮制拒绝盲赌"],["皮制宝箱",19,572372,45827,"皮制80W盲秒亏损"],["实木宝箱",11,408098,null,"62格金雷"],["琉璃宝箱",6,391475,null,"Q6普通局"],["琉璃宝箱",19,920364,null,"三红叠加局"],["机械宝箱",13,337763,null,"0道具盲跟亏损"],["机械宝箱",11,762663,null,"高值但严重溢价"],["琉璃宝箱",12,341449,null,"0道具普通局"],["螺钿宝箱",9,391567,118400,"螺钿无红旧样本"],["皮制宝箱",11,458986,59600,"透视后放弃"],["皮制宝箱",11,1052006,null,"手提箱神局"],["琉璃宝箱",6,664421,null,"Q6三红局"],["螺钿宝箱",3,540998,140200,"Q3精算对齐"]
    ].map((x,i) => ({id:`legacy-${i+1}`,date:"",role:"历史补录",venue:"中级场 · 珊瑚场",box:BOX_ALIASES[x[0]]||x[0],patch:"旧版本·文档样本",q:x[1],goldAvg:x[3],purpleCount:null,actualTotal:x[2],bid:null,cost:0,outcome:"历史记录",redCount:null,redItems:"",notes:x[4],source:"manual",legacy:true,createdAt:0}));

    const CONFIRMED_RECORD_FIXES = {
      "r-mslhvzro-6qyfma": {goldCount:5,redCount:0,notes:"结算确认：5金、4紫、0红；实际总价334328。"},
      "r-msn1mav4-ns9diw": {screenshots:[{name:"{17A74E85-95FC-45EB-A727-44B09E68AF51}.png",path:"这里是16;54之后的对局/{17A74E85-95FC-45EB-A727-44B09E68AF51}.png",kind:"settlement",verifiedActual:2407773}],goldCount:4,redCount:6,notes:"结算图人工核对：Q16=P6+G4+R6；截图已绑定。"},
      "r-msn0mbpz-tfuy50": {screenshots:[{name:"{1E1C4C9B-8E27-49D6-9B7F-9AAF50557A68}.png",path:"这里是16;54之后的对局/{1E1C4C9B-8E27-49D6-9B7F-9AAF50557A68}.png",kind:"settlement",verifiedActual:852170}]},
      "r-msn1akx7-szuczl": {screenshots:[{name:"{24C4C8E0-C993-436F-B58B-026BF7D2B3C7}.png",path:"这里是16;54之后的对局/{24C4C8E0-C993-436F-B58B-026BF7D2B3C7}.png",kind:"settlement",verifiedActual:329913}],goldCount:2,redCount:1,notes:"结算图人工核对：Q7=P4+G2+R1；截图已绑定。"},
      "r-msn1dkde-mcankv": {screenshots:[{name:"{25997549-6A47-409D-A4C9-8DDA06F28079}.png",path:"这里是16;54之后的对局/{25997549-6A47-409D-A4C9-8DDA06F28079}.png",kind:"settlement",verifiedActual:842614}]},
      "r-msn0gsez-a9fwoq": {screenshots:[{name:"{A60A98D1-0B5C-47FF-9A24-6F6143E0C920}.png",path:"这里是16;54之后的对局/{A60A98D1-0B5C-47FF-9A24-6F6143E0C920}.png",kind:"settlement",verifiedActual:581594}],redCount:1,notes:"结算图人工核对：Q22=P13+G8+R1；截图已绑定。"},
      "r-msn0azoe-s9r2bp": {screenshots:[{name:"{D041F67C-A266-48EA-BDC0-E1264EDDA78B}.png",path:"这里是16;54之后的对局/{D041F67C-A266-48EA-BDC0-E1264EDDA78B}.png",kind:"settlement",verifiedActual:1073520}]},
      "r-msn2otfy-bg86i1": {screenshots:[{name:"{D9419FA2-4B4E-4982-B903-D1A43808094E}.png",path:"这里是16;54之后的对局/{D9419FA2-4B4E-4982-B903-D1A43808094E}.png",kind:"settlement",verifiedActual:1177472}]}
    };
    const APP_VERSION = "v0.6";
    const SCHEMA_VERSION = 6;
    const SOLVER_VERSION = "v0.6-reliability";
    const STORAGE_KEY = "yihuan-auction-lab-v1";
    let state = loadState();
    let currentAnalysis = null;
    let currentRoundSnapshots = [];
    let currentRoundEvidence = [];
    let currentGameEvidence = [];
    let currentOcrDataUrl = "";
    let activeWorker = null;
    let latestInferenceRequestId=0,latestInferenceInputHash="";
    let selectedRarity = "all";
    let roundingMode = "floor";
    let pendingConfirm = null;
    const CATALOG_SOURCE_KEY = "yihuan-auction-catalog-sources-v1";
    let catalogSourceEntries = [];
    try { const rawCatalog = JSON.parse(localStorage.getItem(CATALOG_SOURCE_KEY)||"[]"); if(Array.isArray(rawCatalog)) catalogSourceEntries=rawCatalog; } catch(_) { catalogSourceEntries=[]; }

    function onEl(id, event, handler){
      const el=document.getElementById(id);
      if(!el){ console.warn('missing #'+id); return null; }
      if(event&&handler) el.addEventListener(event, handler);
      return el;
    }
    // Invalidation is deliberately independent from Worker.terminate(): a late
    // message from a browser-queued Worker must fail the requestId/inputHash gate.
    function cancelActiveInference(){if(activeWorker){try{if(activeWorker.__v06Timer)clearTimeout(activeWorker.__v06Timer);activeWorker.terminate();}catch(_){}activeWorker=null;}latestInferenceRequestId++;latestInferenceInputHash="";}
    function loadState() {
      try {
        const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY));
        if (parsed && Array.isArray(parsed.records)) {parsed.records=parsed.records.map(normalizeRecord);parsed.screenshotInbox=Array.isArray(parsed.screenshotInbox)?parsed.screenshotInbox:[];parsed.version=APP_VERSION;parsed.schemaVersion=SCHEMA_VERSION;return parsed;}
      } catch (_) {}
      return {version:APP_VERSION,schemaVersion:SCHEMA_VERSION,records:[...LEGACY_HISTORY].map(normalizeRecord),screenshotInbox:[],createdAt:new Date().toISOString()};
    }
    function nowLocalInput(){const d=new Date(Date.now()-new Date().getTimezoneOffset()*60000);return d.toISOString().slice(0,16);}
    function periodOf(value){return typeof value==="string"&&/^\d{4}-\d{2}/.test(value)?value.slice(0,7):"";}
    function productVersionFor(record){
      const explicit=String(record?.productVersion||"");
      if(["v0.1","v0.2","v0.3","v0.4","v0.5","v0.6"].includes(explicit))return explicit;
      const prediction=record?.prediction||{},internal=String(prediction.modelVersion||""),source=String(prediction.estimateSource||"");
      if(internal.startsWith("v0.3"))return "v0.3";
      if(internal.startsWith("v0.2")||internal.startsWith("v7")||source.includes("v4"))return "v0.2";
      return "v0.1";
    }
    function nonNegativeOrNull(value){if(value===null||value===undefined||value==="")return null;const n=Number(value);return Number.isFinite(n)&&n>=0?n:null;}
    function integerOrNull(value){const n=nonNegativeOrNull(value);return Number.isInteger(n)?n:null;}
    function explicitBoolean(value){return value===true||value==="true"?true:value===false||value==="false"?false:null;}
    const FIELD_CONDITION_LABELS={unknown:"未知条件",standard:"标准对局",dark:"天黑了",extraIntel:"一手情报",purpleDouble:"加倍！！",goldDouble:"加倍！！！",sparkle:"闪耀之心",welfare:"福利多多",gemMaze:"宝石迷阵"};
    function canonicalFieldConditionId(value,fallback="unknown"){
      const raw=value&&typeof value==="object"?(value.id??value.name??value.type??value.value):value,key=String(raw??"").trim(),aliases={unknown:"unknown","未知":"unknown","未知条件":"unknown",standard:"standard","标准":"standard","标准对局":"standard",dark:"dark","天黑了":"dark",extraIntel:"extraIntel",extra_intel:"extraIntel",first_intel:"extraIntel","一手情报":"extraIntel",purpleDouble:"purpleDouble",purple_double:"purpleDouble","加倍！！":"purpleDouble",goldDouble:"goldDouble",gold_double:"goldDouble","加倍！！！":"goldDouble",sparkle:"sparkle",shining_heart:"sparkle","闪耀之心":"sparkle",welfare:"welfare","福利多多":"welfare",gemMaze:"gemMaze",gem_maze:"gemMaze","宝石迷阵":"gemMaze","宝石迷宫":"gemMaze"};
      return aliases[key]||fallback;
    }
    function migratedFieldConditionId(source,playedAt){
      const explicit=source?.fieldCondition??source?.condition??source?.fieldMode??source?.settlement?.fieldCondition;
      if(explicit!==null&&explicit!==undefined&&String(explicit).trim()!=="")return canonicalFieldConditionId(explicit,"unknown");
      return playedAt&&/^\d{4}-\d{2}-\d{2}/.test(playedAt)&&playedAt.slice(0,10)<"2026-08-13"?"standard":"unknown";
    }
    function normalizeAvgValueBasis(value){return ["effective","base"].includes(String(value))?String(value):"unknown";}
    function normalizeWelfare(source={},rawSettlement={},fieldCondition="unknown"){
      const raw=source.welfare&&typeof source.welfare==="object"?source.welfare:rawSettlement.welfare&&typeof rawSettlement.welfare==="object"?rawSettlement.welfare:{},base=nonNegativeOrNull(raw.base??source.welfareBase),rate=nonNegativeOrNull(raw.rate??source.welfareRate??(fieldCondition==="welfare"?.30:null)),received=nonNegativeOrNull(raw.received??source.welfareReceived),calculated=base!==null&&rate!==null?base*rate:null,expected=nonNegativeOrNull(raw.expected??source.welfareExpected??calculated);
      return {base,rate,expected,received,source:raw.source||"user-entry"};
    }
    function normalizeSparkle(source={},rawSettlement={}){
      const raw=source.sparkle&&typeof source.sparkle==="object"?source.sparkle:rawSettlement.sparkle&&typeof rawSettlement.sparkle==="object"?rawSettlement.sparkle:{},transformedOneByOneCount=integerOrNull(raw.transformedOneByOneCount??source.transformedOneByOneCount),verifiedGemItems=String(raw.verifiedGemItems??source.verifiedGemItems??"").trim(),complete=explicitBoolean(raw.complete??source.gemInventoryComplete)===true;
      const draft={transformedOneByOneCount,verifiedGemItems,complete},audit=sparkleTruthAudit(draft,{playedAt:source.playedAt??source.date,catalogVersion:source.catalogVersion});
      return {...draft,complete:complete&&audit.ok,parsedCount:audit.parsedCount,validationError:audit.error||null};
    }
    function normalizeIntelEvents(events=[]){return (Array.isArray(events)?events:[]).filter(Boolean).map(event=>{const explicitCost=nonNegativeOrNull(event.cost),source=event.source||"field-condition",free=event.free===true||source==="field-condition"||event.type==="public-intel";return {...event,round:integerOrNull(event.round),cost:explicitCost!==null?explicitCost:(free?0:null),free,source,before:event.before||null,after:event.after||null,stateReduction:nonNegativeOrNull(event.stateReduction),shadowWidthBefore:nonNegativeOrNull(event.shadowWidthBefore),shadowWidthAfter:nonNegativeOrNull(event.shadowWidthAfter),decisionBefore:event.decisionBefore??null,decisionAfter:event.decisionAfter??null};});}
    function sparkleTruthAudit(sparkle={},ctx={}){
      const count=integerOrNull(sparkle.transformedOneByOneCount),complete=sparkle.complete===true,pool=gemTargetPool(ctx),clean=text=>String(text||"").replace(/[「」『』“”\s]/g,"").toLowerCase(),tokens=String(sparkle.verifiedGemItems||"").split(/[+，,、；;\n]/).map(x=>x.trim()).filter(Boolean),unknownTokens=[];let parsedCount=0;
      for(const token of tokens){const mult=Math.max(1,Number((token.match(/[*×x]\s*(\d+)/i)||[])[1])||1),body=token.replace(/[*×x]\s*\d+/ig,"").trim(),bodyKey=clean(body),named=pool.find(item=>bodyKey.includes(clean(item.name))),numeric=(body.match(/\d[\d,]*/g)||[]).map(x=>Number(x.replaceAll(",",""))).find(price=>pool.some(item=>item.price===price));if(named||Number.isFinite(numeric))parsedCount+=mult;else unknownTokens.push(token);}
      let error="";if(count!==null&&parsedCount>count)error=`已确认宝石 ${parsedCount} 件，超过转换数量 ${count} 件`;else if(complete&&count===null)error="勾选宝石清单完整前，必须填写明确的转换 1×1 数量";else if(complete&&unknownTokens.length)error=`完整宝石清单含未识别项：${unknownTokens.join("、")}`;else if(complete&&parsedCount!==count)error=`完整宝石清单解析到 ${parsedCount} 件，必须与转换数量 ${count} 件一致`;
      return {ok:!error,error,count,parsedCount,unknownTokens};
    }
    function normalizeCostBreakdown(source,rawSettlement={}){
      const raw=(source?.costs&&typeof source.costs==="object"?source.costs:rawSettlement?.costs&&typeof rawSettlement.costs==="object"?rawSettlement.costs:{}),entry=nonNegativeOrNull(raw.entry??raw.entryCost),info=nonNegativeOrNull(raw.info??raw.infoCost),other=nonNegativeOrNull(raw.other??raw.otherCost),parts=[entry,info,other],hasParts=parts.some(x=>x!==null),legacyTotal=nonNegativeOrNull(raw.total??source?.cost??rawSettlement?.cost),total=hasParts?parts.reduce((s,x)=>s+(x||0),0):(legacyTotal??0);
      return {...raw,entry,info,other,total,complete:raw.complete===true||parts.every(x=>x!==null),source:raw.source||(hasParts?"v0.4-explicit":legacyTotal!==null?"legacy-total-only":"unknown")};
    }
    function normalizeRealizedState(source,rawSettlement={}){
      const raw=(rawSettlement.realizedState&&typeof rawSettlement.realizedState==="object"?rawSettlement.realizedState:source?.realizedState&&typeof source.realizedState==="object"?source.realizedState:null);
      if(!raw)return null;
      const gold=integerOrNull(raw.gold??raw.g),purple=integerOrNull(raw.purple??raw.p),red=integerOrNull(raw.red??raw.r),q=integerOrNull(source?.q),sumValid=[gold,purple,red].every(x=>x!==null)&&(q===null||gold+purple+red===q),complete=raw.complete===true&&sumValid;
      return {...raw,gold,purple,red,complete,source:raw.source||rawSettlement.truthSource||"unknown",confidence:raw.confidence||rawSettlement.truthConfidence||"unknown"};
    }
    function normalizeRecord(r){
      const fix=CONFIRMED_RECORD_FIXES[r.id]||{},source={...r,...fix,notes:[r.notes,fix.notes].filter(Boolean).join(" · "),screenshots:[...(Array.isArray(r.screenshots)?r.screenshots:[]),...(Array.isArray(fix.screenshots)?fix.screenshots:[])]},playedAt=source.playedAt||(source.date?`${source.date}T12:00`:"");
      const fieldCondition=migratedFieldConditionId(source,playedAt),avgValueBasis=normalizeAvgValueBasis(source.avgValueBasis??source.settlement?.avgValueBasis),blueMatch=`${source.publicNote||""} ${source.notes||""}`.match(/蓝色(?:品质)?(?:藏品)?(?:平均价值|均价)\s*([\d,]+)/),blueAvg=source.blueAvg??(blueMatch?Number(blueMatch[1].replaceAll(",","")):null),rounds=Array.isArray(source.rounds)?source.rounds.map(x=>{const roundCondition=canonicalFieldConditionId(x.fieldCondition??fieldCondition,fieldCondition),intelEvents=normalizeIntelEvents(x.intelEvents);return {...x,fieldCondition:roundCondition,avgValueBasis:normalizeAvgValueBasis(x.avgValueBasis??avgValueBasis),intelEvents,prediction:x.prediction?{...x.prediction,fieldCondition:canonicalFieldConditionId(x.prediction.fieldCondition??roundCondition,roundCondition),avgValueBasis:normalizeAvgValueBasis(x.prediction.avgValueBasis??x.avgValueBasis??avgValueBasis),intelEvents:normalizeIntelEvents(x.prediction.intelEvents??intelEvents)}:x.prediction,venue:VENUE_ALIASES[x.venue]||x.venue||source.venue,box:BOX_ALIASES[x.box]||x.box||source.box,roundEvidence:Array.isArray(x.roundEvidence)?x.roundEvidence.map((shot,j)=>({...shot,kind:"round-evidence",round:Number(x.round)||1,segmentIndex:shot.segmentIndex||j+1,coverageMode:shot.coverageMode||"round-viewport"})):[]};}):[];
      const screenshotMap=new Map();(Array.isArray(source.screenshots)?source.screenshots:[]).filter(Boolean).forEach(x=>{const shot=typeof x==="string"?{name:x.split(/[\\/]/).pop(),path:x,kind:"settlement"}:{...x};if(shot.dataUrl&&!shot.thumbnailDataUrl)shot.thumbnailDataUrl=shot.dataUrl;screenshotMap.set(shot.path||shot.name,shot);});const screenshots=[...screenshotMap.values()].map((shot,i)=>({...shot,segmentIndex:shot.segmentIndex||i+1,segmentRole:shot.segmentRole||(i===0?"main-settlement":"warehouse-supplement"),coverageMode:shot.coverageMode||"viewport-segment",overlapExpected:shot.overlapExpected??i>0,dedupeStatus:shot.dedupeStatus||"pending"}));
      const rawSettlement=source.settlement&&typeof source.settlement==="object"?source.settlement:{},settlementShots=new Map();[...(Array.isArray(rawSettlement.screenshots)?rawSettlement.screenshots:[]),...screenshots].filter(Boolean).forEach(x=>{const shot=typeof x==="string"?{name:x.split(/[\\/]/).pop(),path:x,kind:"settlement"}:{...x};if(shot.dataUrl&&!shot.thumbnailDataUrl)shot.thumbnailDataUrl=shot.dataUrl;settlementShots.set(shot.path||shot.name,shot);});
      const legacyActual=Number(source.actualTotal)>0?Number(source.actualTotal):null,status=rawSettlement.status==="verified"||legacyActual!==null?"verified":rawSettlement.status==="parsed"?"parsed":"pending",costs=normalizeCostBreakdown(source,rawSettlement),realizedState=normalizeRealizedState(source,rawSettlement),redInventoryComplete=explicitBoolean(source.redInventoryComplete??rawSettlement.redInventoryComplete),settlementVerifiedRedItems=String(source.settlementVerifiedRedItems??rawSettlement.verifiedRedItems??(redInventoryComplete===true?(rawSettlement.recognizedItems??source.redItems??""):"")).trim(),decisionKnownRed=String(source.decisionKnownRed??source.knownRed??"").trim(),highestPersonalBid=nonNegativeOrNull(source.highestPersonalBid??rawSettlement.highestPersonalBid),clearingPrice=nonNegativeOrNull(source.clearingPrice??rawSettlement.clearingPrice??rawSettlement.bid??source.bid),purchaseSpend=nonNegativeOrNull(source.purchaseSpend??rawSettlement.purchaseSpend),acquired=explicitBoolean(source.acquired??rawSettlement.acquired),resultReason=String(source.resultReason??source.noBidReason??rawSettlement.resultReason??"").trim(),privateBidCap=nonNegativeOrNull(source.privateBidCap??rawSettlement.privateBidCap),bidActionCount=integerOrNull(source.bidActionCount??rawSettlement.bidActionCount),welfare=normalizeWelfare(source,rawSettlement,fieldCondition),sparkle=normalizeSparkle(source,rawSettlement),intelEvents=normalizeIntelEvents(source.intelEvents??rawSettlement.intelEvents),settlement={...rawSettlement,status,screenshots:[...settlementShots.values()].map((shot,i)=>({...shot,segmentIndex:shot.segmentIndex||i+1,segmentRole:shot.segmentRole||(i===0?"main-settlement":"warehouse-supplement"),coverageMode:shot.coverageMode||"viewport-segment",overlapExpected:shot.overlapExpected??i>0,dedupeStatus:shot.dedupeStatus||"pending"})),coverage:rawSettlement.coverage||{mode:"viewport-segments",sameInventory:true,ordered:true,overlapExpected:true,overlapGuidance:"相邻截图建议保留约15%～30%重叠"},aggregationPolicy:rawSettlement.aggregationPolicy||{type:"inventory-union",deduplicateByOverlap:true,neverSumViewportCounts:true,uncertainDuplicateState:"possible-duplicate"},inventoryUnion:rawSettlement.inventoryUnion||{status:"pending",items:[],uncertainDuplicates:[],counts:null,grids:null},fieldCondition,avgValueBasis,privateBidCap,bidActionCount,welfare,sparkle,intelEvents,actualTotal:rawSettlement.actualTotal??legacyActual,bid:rawSettlement.bid??clearingPrice,highestPersonalBid,clearingPrice,purchaseSpend,acquired,resultReason,costs,realizedState,goldCount:integerOrNull(rawSettlement.goldCount??realizedState?.gold),purpleCount:integerOrNull(rawSettlement.purpleCount??realizedState?.purple),redCount:integerOrNull(rawSettlement.redCount??realizedState?.red),redInventoryComplete,verifiedRedItems:settlementVerifiedRedItems,recognizedItems:rawSettlement.recognizedItems??"",truthSource:rawSettlement.truthSource||realizedState?.source||"unknown",truthConfidence:rawSettlement.truthConfidence||realizedState?.confidence||"unknown",verified:status==="verified"},prediction=source.prediction?{...source.prediction,fieldCondition:canonicalFieldConditionId(source.prediction.fieldCondition??fieldCondition,fieldCondition),avgValueBasis:normalizeAvgValueBasis(source.prediction.avgValueBasis??avgValueBasis),privateBidCap:nonNegativeOrNull(source.prediction.privateBidCap??privateBidCap),bidActionCount:integerOrNull(source.prediction.bidActionCount??bidActionCount),welfare:normalizeWelfare(source.prediction,rawSettlement,fieldCondition),sparkle:normalizeSparkle(source.prediction,rawSettlement),intelEvents:normalizeIntelEvents(source.prediction.intelEvents??intelEvents)}:source.prediction;
      return {...source,productVersion:productVersionFor(source),blueAvg,fieldCondition,fieldConditionSource:source.fieldCondition?"explicit":playedAt&&playedAt.slice(0,10)<"2026-08-13"?"pre-0813-migration":"unknown-migration",avgValueBasis,privateBidCap,bidActionCount,welfare,sparkle,intelEvents,prediction,rounds,screenshots,costs,cost:costs.total,decisionKnownRed,settlementVerifiedRedItems,redInventoryComplete,highestPersonalBid,clearingPrice,purchaseSpend,acquired,resultReason,noBidReason:acquired===false?resultReason:"",diagnosticOnly:source.diagnosticOnly===true,diagnosticReport:source.diagnosticReport||null,settlement,winner:source.winner||settlement.winner||"",notes:source.notes||settlement.note||"",playedAt,periodKey:source.periodKey||periodOf(playedAt)||source.patch||"日期未知",venue:VENUE_ALIASES[source.venue]||source.venue||"未知场地",box:BOX_ALIASES[source.box]||source.box||"未知箱型",character:source.character||"未知助手"};
    }
    function compactScreenshotForStorage(shot){const {dataUrl,...rest}=shot||{};return {...rest,thumbnailDataUrl:rest.thumbnailDataUrl||dataUrl||null};}
    function stateForPersistence(){return {...state,version:APP_VERSION,schemaVersion:SCHEMA_VERSION,records:(state.records||[]).map(r=>({...r,screenshots:(r.screenshots||[]).map(compactScreenshotForStorage),rounds:(r.rounds||[]).map(round=>({...round,roundEvidence:(round.roundEvidence||[]).map(compactScreenshotForStorage)})),settlement:r.settlement?{...r.settlement,screenshots:(r.settlement.screenshots||r.screenshots||[]).map(compactScreenshotForStorage)}:undefined,ocrEvidence:(r.ocrEvidence||[]).map(({dataUrl,...x})=>x)}))};}
    function stripInlineImageForCache(shot){const {dataUrl,thumbnailDataUrl,...rest}=shot||{};return rest;}
    function stripProbabilityForCache(prediction){if(!prediction||typeof prediction!=="object")return prediction;const {probabilityProfile,...rest}=prediction;return rest;}
    function stateForLocalCache(){
      const persisted=stateForPersistence();
      return {...persisted,screenshotInbox:(persisted.screenshotInbox||[]).map(stripInlineImageForCache),records:(persisted.records||[]).map(r=>{
        const {migrationAudit,...record}=r;
        return {...record,screenshots:(record.screenshots||[]).map(stripInlineImageForCache),rounds:(record.rounds||[]).map(round=>({...round,roundEvidence:(round.roundEvidence||[]).map(stripInlineImageForCache),prediction:stripProbabilityForCache(round.prediction)})),settlement:record.settlement?{...record.settlement,screenshots:(record.settlement.screenshots||record.screenshots||[]).map(stripInlineImageForCache)}:record.settlement,ocrEvidence:(record.ocrEvidence||[]).map(stripInlineImageForCache)};
      })};
    }
    function stateForMinimalLocalCache(){
      const cached=stateForLocalCache();
      return {...cached,records:(cached.records||[]).map(r=>{const {rounds,screenshots,ocrEvidence,prediction,...record}=r;return {...record,rounds:[],screenshots:[],ocrEvidence:[],prediction:stripProbabilityForCache(prediction),settlement:record.settlement?{...record.settlement,screenshots:[]}:record.settlement};})};
    }
    function isQuotaError(error){return error?.name==="QuotaExceededError"||error?.code===22||error?.code===1014;}
    function persistLocalCache(options={}){
      const preferCompact=options.preferCompact===true||localCacheMode==="compact"||localCacheMode==="minimal",attempts=preferCompact?[["compact",stateForLocalCache],["minimal",stateForMinimalLocalCache]]:[["full",stateForPersistence],["compact",stateForLocalCache],["minimal",stateForMinimalLocalCache]];let lastError=null;
      for(const [mode,builder] of attempts){try{localStorage.setItem(STORAGE_KEY,JSON.stringify(builder()));localCacheMode=mode;return {ok:true,mode};}catch(error){lastError=error;if(!isQuotaError(error))break;}}
      localCacheMode="memory";console.warn("[storage] 浏览器缓存写入失败；完整数据仍保留在已连接 JSON 或当前页面内存中",lastError);return {ok:false,mode:"memory",error:lastError};
    }
    function flushDeferredLocalCache(){
      if(localCacheWriteTimer){clearTimeout(localCacheWriteTimer);localCacheWriteTimer=null;}
      if(!localCacheWritePending)return {ok:true,mode:"idle"};
      localCacheWritePending=false;
      const cache=persistLocalCache();
      if(!cache.ok&&!dataFileHandle&&!localCacheWarningShown){localCacheWarningShown=true;toast("浏览器缓存空间不足：完整数据仍在已连接 JSON 或当前页面内存中",true);}
      return cache;
    }
    function scheduleDeferredLocalCache(){
      localCacheWritePending=true;
      if(localCacheWriteTimer)clearTimeout(localCacheWriteTimer);
      localCacheWriteTimer=setTimeout(()=>{localCacheWriteTimer=null;flushDeferredLocalCache();},120);
    }
    if (typeof window !== "undefined" && window.addEventListener) {
      window.addEventListener("pagehide",()=>{try{flushDeferredLocalCache();}catch(error){console.warn("[storage] pagehide cache flush skipped",error);}});
    }
    if (typeof document !== "undefined" && document.addEventListener) {
      document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="hidden"&&localCacheWritePending){try{flushDeferredLocalCache();}catch(error){console.warn("[storage] visibility cache flush skipped",error);}}});
    }
    function saveState(options={}) {
      const deferCache=options.deferCache===true;
      const cache=deferCache?(scheduleDeferredLocalCache(),{ok:true,mode:"scheduled"}):persistLocalCache();
      // JSON 文件是权威存储；浏览器缓存失败不能阻断真正的文件写回。
      scheduleFileWrite();
      if(!cache.ok&&!dataFileHandle&&!localCacheWarningShown){localCacheWarningShown=true;toast("浏览器缓存空间不足：本页数据仍在内存中，请立即连接数据文件或导出 JSON",true);}
      else if(cache.ok&&cache.mode!=="full"&&cache.mode!=="scheduled"&&!dataFileHandle&&!localCacheWarningShown){localCacheWarningShown=true;toast("浏览器缓存已自动精简；建议连接数据文件保存完整回合明细",true);}
      return cache;
    }
    function uid() { return `r-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,8)}`; }
    function val(id) { return document.getElementById(id).value.trim(); }
    function num(id) { const raw=val(id); return raw==="" ? null : Number(raw); }
    function setVal(id,value) { document.getElementById(id).value = value ?? ""; }
    function costBreakdownFromInputs(prefix,source="user-entry"){
      const entry=nonNegativeOrNull(num(`${prefix}EntryCost`)),info=nonNegativeOrNull(num(`${prefix}InfoCost`)),other=nonNegativeOrNull(num(`${prefix}OtherCost`)),parts=[entry,info,other];
      return {entry,info,other,total:parts.reduce((s,x)=>s+(x||0),0),complete:parts.every(x=>x!==null),source};
    }
    function syncCostInputs(prefix){
      const costs=costBreakdownFromInputs(prefix),hidden=document.getElementById(`${prefix}Cost`),label=document.getElementById(`${prefix}CostTotal`);
      if(hidden)hidden.value=String(costs.total);
      if(label)label.textContent=`${fmt(costs.total)} 海贝${costs.complete?"":" · 分项未完整"}`;
      return costs;
    }
    function conditionIntelEvents(fieldCondition,round,note=""){
      return fieldCondition==="extraIntel"&&[1,3].includes(Number(round))?[{id:`field-extra-intel-r${round}`,round:Number(round),type:"public-intel",label:`R${round} 拍卖师公开情报`,note:String(note||"").trim(),free:true,cost:0,source:"field-condition"}]:[];
    }
    function welfareFromInputs(prefix,fieldCondition){
      if(fieldCondition!=="welfare")return {base:null,rate:null,expected:null,received:null,source:"not-applicable"};
      const base=nonNegativeOrNull(num(`${prefix}WelfareBase`)),rate=nonNegativeOrNull(num(`${prefix}WelfareRate`)??(fieldCondition==="welfare"?.30:null)),received=nonNegativeOrNull(num(`${prefix}WelfareReceived`)),expected=base!==null&&rate!==null?base*rate:nonNegativeOrNull(num(`${prefix}WelfareExpected`));
      return {base,rate,expected,received,source:"user-entry"};
    }
    function syncWelfareInputs(prefix){
      const condition=prefix==="record"?canonicalFieldConditionId(val("recordFieldCondition")):canonicalFieldConditionId(val("calcFieldCondition")),base=nonNegativeOrNull(num(`${prefix}WelfareBase`)),rate=nonNegativeOrNull(num(`${prefix}WelfareRate`)??(condition==="welfare"?.30:null)),expected=base!==null&&rate!==null?base*rate:null,el=document.getElementById(`${prefix}WelfareExpected`);
      if(el)el.value=condition!=="welfare"||expected===null?"":String(Math.round(expected));
      return condition==="welfare"?expected:null;
    }
    function liveConditionPayload(round=Number(val("calcRound"))||1){
      const fieldCondition=canonicalFieldConditionId(val("calcFieldCondition")),avgValueBasis=normalizeAvgValueBasis(val("calcAvgValueBasis")),sparkle={transformedOneByOneCount:integerOrNull(num("calcTransformedOneByOneCount")),verifiedGemItems:val("calcVerifiedGemItems"),complete:document.getElementById("calcGemInventoryComplete")?.checked===true},intelEvents=conditionIntelEvents(fieldCondition,round,val("calcPublicNote"));
      return {fieldCondition,avgValueBasis,privateBidCap:nonNegativeOrNull(num("calcPrivateBidCap")),bidActionCount:integerOrNull(num("calcBidActionCount")),sparkle,intelEvents};
    }
    function renderDoublePriceMap(fieldCondition=canonicalFieldConditionId(val("calcFieldCondition"))){
      const el=document.getElementById("calcDoublePriceMap");if(!el)return;
      const rules=conditionRules({fieldCondition}),rows=[];
      for(const [rarity,label,items,multiplier] of [["gold","金色",GOLD_ITEMS,rules.goldMultiplier],["purple","紫色",PURPLE_ITEMS,rules.purpleMultiplier]]){
        if(multiplier!==2)continue;
        rows.push(`<details class="double-price-map-detail"><summary>${label}图鉴 · 原价 → 局内显示价（${items.length} 件）</summary><table class="dash-table"><thead><tr><th>藏品</th><th>尺寸</th><th>图鉴原价</th><th>双倍显示</th></tr></thead><tbody>${items.map(x=>`<tr><td>${escapeHtml(x[0])}</td><td>${escapeHtml(x[2])}</td><td class="num">${fmt(x[1])}</td><td class="num"><strong>${fmt(Number(x[1])*2)}</strong></td></tr>`).join("")}</tbody></table></details>`);
      }
      if(!rows.length){el.hidden=true;el.innerHTML="";return;}
      el.hidden=false;el.innerHTML=`<strong>双倍价格对应：</strong>截图里如果出现翻倍后的数字，直接填原数字即可；选择“截图已包含场地翻倍”时，名称和数字约束会自动还原到图鉴原价再求解。${rows.join("")}`;
    }
    function syncFieldConditionUi(){
      const fieldCondition=canonicalFieldConditionId(val("calcFieldCondition")),round=Number(val("calcRound"))||1,label=FIELD_CONDITION_LABELS[fieldCondition]||FIELD_CONDITION_LABELS.unknown,hints={unknown:"不对倍率、情报回合、福利金或 1×1 转换作假设。",standard:"按标准规则记录，本局不附加场地修正。",dark:"具体出价不可见；请记录自己的私人上限和画面可见出价次数。",extraIntel:[1,3].includes(round)?`R${round} 有一条免费拍卖师公开情报；保存快照时自动写入 intelEvents，cost=0。`:`R${round} 没有额外免费情报；R1、R3 会自动提示。`,purpleDouble:"紫色藏品在局内直接显示为原价×2；例如焰火海鲜饭双倍显示 4070、图鉴原价 2035，可直接填进已知紫色约束。",goldDouble:"金色藏品在局内直接显示为原价×2；例如罐装随心泥双倍显示 249632、图鉴原价 124816，可直接填进金色约束。",sparkle:"所有 1×1 转为随机宝石；当前只记录数量与已确认宝石，不伪造概率。",welfare:"福利金倍率 30%；实际收到额外进入本局现金流，但不改变整箱实际总价。"},hint=document.getElementById("calcFieldConditionHint");
      if(hint)hint.innerHTML=`<strong>${escapeHtml(label)}：</strong>${escapeHtml(hints[fieldCondition]||hints.unknown)}`;
      const status=document.getElementById("coreConditionStatus");if(status){status.classList.toggle("known",fieldCondition!=="unknown");status.innerHTML=`<span>${fieldCondition==="unknown"?"⚠ ":"✓ "}场地条件：${escapeHtml(label)}</span><small>点击${fieldCondition==="unknown"?"设置":"查看"}</small>`;}
      const toggle=(id,on)=>{const el=document.getElementById(id);if(el)el.hidden=!on;};toggle("calcDarkFields",fieldCondition==="dark");toggle("calcMultiplierFields",["purpleDouble","goldDouble"].includes(fieldCondition));toggle("calcShiningFields",fieldCondition==="sparkle");toggle("resultWelfareFields",fieldCondition==="welfare");toggle("resultShiningFields",fieldCondition==="sparkle");
      if(["purpleDouble","goldDouble"].includes(fieldCondition)&&val("calcAvgValueBasis")==="unknown")setVal("calcAvgValueBasis","effective");
      renderDoublePriceMap(fieldCondition);
      if(fieldCondition==="welfare"&&!val("resultWelfareRate"))setVal("resultWelfareRate",.30);syncWelfareInputs("result");
    }
    function fillBoxOptions(venueId,boxId,desired=null){const venueEl=document.getElementById(venueId),el=document.getElementById(boxId);if(!venueEl||!el)return;const venue=venueEl.value.trim(),raw=desired??el.value,keep=BOX_ALIASES[raw]||raw,boxes=VENUE_BOXES[venue]||["未知箱型"];el.innerHTML='<option>未知箱型</option>'+boxes.filter(x=>x!=="未知箱型").map(x=>`<option>${escapeHtml(x)}</option>`).join("");el.value=boxes.includes(keep)||keep==="未知箱型"?keep:"未知箱型";}
    function setupVenueBoxPair(venueId,boxId){const v=document.getElementById(venueId),b=document.getElementById(boxId);if(!v||!b)return;fillBoxOptions(venueId,boxId);v.addEventListener("change",()=>fillBoxOptions(venueId,boxId));}
    function fmt(value) { return value==null || !Number.isFinite(value) ? "—" : Math.round(value).toLocaleString("zh-CN"); }
    function fmtWan(value) { return value==null || !Number.isFinite(value) ? "—" : `${(value/10000).toFixed(value>=1000000?1:2)}W`; }
    function escapeHtml(value="") { return String(value).replace(/[&<>'"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[ch]); }
    function debounce(fn,delay=120){let timer=null;return function(...args){clearTimeout(timer);timer=setTimeout(()=>fn.apply(this,args),delay);};}
    function median(values) { if(!values.length)return null; const s=[...values].sort((a,b)=>a-b), m=Math.floor(s.length/2); return s.length%2?s[m]:(s[m-1]+s[m])/2; }
    function quantile(values,q) { if(!values.length)return null; const s=[...values].sort((a,b)=>a-b), pos=(s.length-1)*q, base=Math.floor(pos), rest=pos-base; return s[base+1]!==undefined?s[base]+rest*(s[base+1]-s[base]):s[base]; }
    function mean(values) { return values.length ? values.reduce((a,b)=>a+b,0)/values.length : null; }

    // v0.6 reliability: every frozen prediction is tied to the exact draft that
    // produced it.  This deliberately uses a tiny deterministic hash instead of
    // crypto.subtle so it also works from a file:// page and inside the worker.
    function stableHashValue(value){
      if(value===undefined)return "__undefined__";
      if(value===null)return null;
      if(typeof value!=='object')return value;
      if(Array.isArray(value))return value.map(stableHashValue);
      return Object.keys(value).sort().reduce((out,key)=>{out[key]=stableHashValue(value[key]);return out;},{});
    }
    function fastHash(text){let h=2166136261;for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619);}return (h>>>0).toString(16).padStart(8,"0");}
    function solverInputPayload(ctx={}){
      const p=ctx.publicInfo||{};
      return {q:ctx.q,goldCount:ctx.goldCount,purple:ctx.purple,redCount:ctx.redCount,minGold:ctx.minGold,minPurple:ctx.minPurple,minRed:ctx.minRed,avg:ctx.avg,purpleAvg:ctx.purpleAvg,goldTotal:ctx.goldTotal,cost:ctx.cost??0,knownGold:ctx.knownGoldRaw??ctx.knownGold??"",knownPurple:ctx.knownPurpleRaw??ctx.knownPurple??"",knownRed:ctx.knownRedRaw??ctx.knownRed??"",goldGroups:ctx.goldGroups||[],purpleGroups:ctx.purpleGroups||[],redGroups:ctx.redGroups||[],totalItems:p.totalItems,totalGrid:p.totalGrid,goldGrid:p.goldGrid,purpleGrid:p.purpleGrid,blueCount:p.blueCount,blueGrid:p.blueGrid,blueAvg:p.blueAvg,greenCount:p.greenCount,greenGrid:p.greenGrid,greenAvg:p.greenAvg,whiteCount:p.whiteCount,whiteGrid:p.whiteGrid,whiteAvg:p.whiteAvg,systemEstimate:p.systemEstimate,singleAvg:p.singleAvg,nineAvg:p.nineAvg,publicNote:p.note||"",fieldCondition:ctx.fieldCondition||"unknown",avgValueBasis:ctx.avgValueBasis||"unknown",totalValueBasis:ctx.totalValueBasis||null,roundingMode:ctx.roundingMode||"floor",catalogVersion:catalogVersionFor(ctx),toolGroup:ctx.toolGroup||"group1",round:ctx.round||1,targetProfit:ctx.targetProfit??30000,sparkle:ctx.sparkle||null,privateBidCap:ctx.privateBidCap??null,bidActionCount:ctx.bidActionCount??null};
    }
    function solverInputHash(ctx={}){return `sha1-${fastHash(JSON.stringify(stableHashValue(solverInputPayload(ctx))))}`;}
    function solverStatusFromResult(result={}){
      if(result.solverStatus)return result.solverStatus;
      if(result.searchCompleted===false)return result.states?.length?"incomplete":"timeout";
      return result.states?.length?"valid":"no-match";
    }
    function predictionStatusLabel(status){return ({valid:"可用于决策",incomplete:"候选未完整",fallback:"低信息基线","no-match":"严格无解",timeout:"计算超时",stale:"输入已变化"}[status]||status||"未知");}

    /*
     * v0.6 Diagnostic Solver
     *
     * This is deliberately a separate, bounded explanation path.  It only
     * runs after the strict solver has returned no-match, and its candidates
     * are never passed to workingDecision(), Shadow, State Prior, Market, or
     * a saved prediction.  The purpose is to tell the operator whether the
     * contradiction is likely rounding, a tiny display transcription error,
     * a catalog-version mismatch, or a special-field price-basis mismatch.
     */
    function diagnosticSolverV06(ctx={},strictResult={}){
      if(solverStatusFromResult(strictResult)!=="no-match"||ctx?._diagnosticChecked===true)return null;
      const attempts=[],seen=new Set(),base={...ctx,diagnosticOnly:true,_diagnosticChecked:true,solverTimeBudgetMs:Math.min(450,Math.max(180,Number(ctx.solverTimeBudgetMs)||450))};
      const stateCount=result=>result?.goldOnly?((result.states||[]).length+(result.purpleStates||[]).length):(result?.states||[]).length;
      const recordAttempt=(label,kind,patch)=>{
        if(attempts.length>=8)return null;
        const attemptCtx={...base,...patch,_diagnosticChecked:true,diagnosticOnly:true};
        const key=JSON.stringify(stableHashValue({kind,roundingMode:attemptCtx.roundingMode,avg:attemptCtx.avg,goldTotal:attemptCtx.goldTotal,catalogVersion:attemptCtx.catalogVersion,avgValueBasis:attemptCtx.avgValueBasis,fieldCondition:attemptCtx.fieldCondition}));
        if(seen.has(key))return null;seen.add(key);
        let result=null,error=null;
        try{attemptCtx.inputHash=solverInputHash(attemptCtx);result=solveStateInferenceSync(attemptCtx,8);}catch(ex){error=String(ex?.message||ex);}
        const status=error?"error":solverStatusFromResult(result),count=error?0:stateCount(result),entry={label,kind,status,candidateCount:count,chosenRoundingMode:result?.chosenRoundingMode||attemptCtx.roundingMode||null,catalogVersion:catalogVersionFor(attemptCtx),avgValueBasis:attemptCtx.avgValueBasis||null,delta:patch.avg!==undefined&&Number.isFinite(Number(base.avg))?Number(patch.avg)-Number(base.avg):null,error:error||null};attempts.push(entry);
        return count>0&&status==="valid"?{entry,result,attemptCtx}:null;
      };
      // 1. Strict floor is recorded for the report; it is not re-used as a
      // formal candidate because the caller already proved it has no match.
      attempts.push({label:"严格向下取整",kind:"strict-floor",status:"no-match",candidateCount:0,chosenRoundingMode:"floor",catalogVersion:catalogVersionFor(base),avgValueBasis:base.avgValueBasis||null,delta:null,error:null});
      const candidates=[];
      candidates.push(["四舍五入", "nearest-rounding", {roundingMode:"nearest"}]);
      candidates.push(["兼容取整区间", "compatible-rounding", {roundingMode:"either"}]);
      if(Number.isFinite(Number(base.avg))){
        candidates.push(["均价显示误差 -1", "avg-display-tolerance", {avg:Number(base.avg)-1,roundingMode:"floor"}]);
        candidates.push(["均价显示误差 +1", "avg-display-tolerance", {avg:Number(base.avg)+1,roundingMode:"floor"}]);
      }
      const currentCatalog=catalogVersionFor(base),catalogAlternatives=[CATALOG_VERSION_PRE_0813,CATALOG_VERSION_0813].filter(x=>x!==currentCatalog);
      for(const version of catalogAlternatives)candidates.push([`图鉴版本 ${version}`,"catalog-version",{catalogVersion:version,roundingMode:base.roundingMode||"floor"}]);
      const doubleMode=["purpleDouble","goldDouble"].includes(canonicalFieldConditionId(base.fieldCondition||"unknown"));
      if(doubleMode&&String(base.avgValueBasis||"unknown")==="unknown"){
        candidates.push(["特殊场地 base 口径","field-price-basis",{avgValueBasis:"base"}]);
        candidates.push(["特殊场地 effective 口径","field-price-basis",{avgValueBasis:"effective"}]);
      }
      let resolution=null;
      for(const [label,kind,patch] of candidates){const found=recordAttempt(label,kind,patch);if(found){resolution=found;break;}}
      return {version:"v0.6-diagnostic",diagnosticOnly:true,status:resolution?"diagnostic-match":"diagnostic-no-match",resolution:resolution?.entry||null,candidateStates:resolution?.result?.states||[],attempts,strictStatus:"no-match",note:resolution?"仅用于解释严格矛盾；候选不会生成正式估值。":"未找到有限容错下的候选；仍需检查抄录、数量、价格口径或图鉴版本。"};
    }
    function diagnosticReportHtml(report){
      if(!report)return "";
      const rows=(report.attempts||[]).map(x=>`<div class="diagnostic-attempt"><span>${escapeHtml(x.label||x.kind||"诊断")}</span><b>${x.status==="valid"?`找到 ${x.candidateCount} 个候选`:x.status==="incomplete"?"候选未完整":x.status==="error"?"执行失败":"无候选"}</b><small>${escapeHtml([x.catalogVersion,x.chosenRoundingMode,x.delta===null?"":`Δ均价 ${x.delta>0?"+":""}${x.delta}`].filter(Boolean).join(" · "))}</small></div>`).join("");
      const headline=report.resolution?`诊断找到“${escapeHtml(report.resolution.label)}”路径可行，但这不是正式解。`:`有限诊断仍未找到候选，不能把它当成正式无解证明。`;
      return `<details class="diagnostic-report" open><summary><strong>诊断容错 · ${report.resolution?"发现可能原因":"未发现有限容错原因"}</strong><span>只作解释，不进入估值/训练</span></summary><div class="diagnostic-report-body"><p>${headline}</p><div class="diagnostic-attempts">${rows}</div><div class="field-help">${escapeHtml(report.note||"")} 诊断 State 固定标记为 <code>diagnosticOnly=true</code>，保存后不会生成 prediction，也不会进入 Shadow、State Prior 或 walk-forward 训练。</div></div></details>`;
    }

    let dataFileHandle=null,fileWriteTimer=null,writingFile=false,writeRequested=false,writeLoopPromise=null,localCacheMode="unknown",localCacheWarningShown=false,localCacheWriteTimer=null,localCacheWritePending=false;
    function setStorageStatus(text,mode="",detail=""){const el=document.getElementById("dataFileBtn");if(!el)return;el.textContent=text;el.title=detail||"选择异环拍卖数据.json；成功连接后每次保存都会自动写回";el.classList.toggle("syncing",mode==="syncing");el.classList.toggle("error",mode==="error");}
    function openHandleDb(){return new Promise((resolve,reject)=>{if(!window.indexedDB){reject(new Error("indexedDB unavailable"));return;}const req=indexedDB.open("yihuan-auction-file",1);req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains("handles"))req.result.createObjectStore("handles");};req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
    function openScreenshotDb(){return new Promise((resolve,reject)=>{if(!window.indexedDB){reject(new Error("indexedDB unavailable"));return;}const req=indexedDB.open("yihuan-auction-screenshots",1);req.onupgradeneeded=()=>req.result.createObjectStore("screenshots");req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
    async function persistScreenshotBlob(key,file){const db=await openScreenshotDb();await new Promise((resolve,reject)=>{const tx=db.transaction("screenshots","readwrite");tx.objectStore("screenshots").put({blob:file,name:file?.name||"截图",type:file?.type||"image/*",savedAt:new Date().toISOString()},key);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();}
    async function readScreenshotBlob(key){if(!key)return null;const db=await openScreenshotDb();try{return await new Promise((resolve,reject)=>{const tx=db.transaction("screenshots","readonly"),req=tx.objectStore("screenshots").get(key);req.onsuccess=()=>resolve(req.result||null);req.onerror=()=>reject(req.error);});}finally{db.close();}}
    async function deleteScreenshotBlob(key){if(!key)return;try{const db=await openScreenshotDb();await new Promise((resolve,reject)=>{const tx=db.transaction("screenshots","readwrite");tx.objectStore("screenshots").delete(key);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});db.close();}catch(_){} }
    async function storeDataHandle(handle){const db=await openHandleDb();try{await new Promise((resolve,reject)=>{const tx=db.transaction("handles","readwrite");tx.objectStore("handles").put(handle,"main");tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}finally{db.close();}}
    async function restoreDataHandle(){
      try{
        const db=await openHandleDb(),handle=await new Promise((resolve,reject)=>{const tx=db.transaction("handles","readonly"),req=tx.objectStore("handles").get("main");req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});db.close();if(!handle)return;
        dataFileHandle=handle;const permission=typeof handle.queryPermission==="function"?await handle.queryPermission({mode:"readwrite"}):"prompt";
        if(permission==="granted"){const result=await mergeFromDataFile();if(result.write.ok)setStorageStatus("数据文件已同步");else setStorageStatus("写回失败 · 点击重试","error",describeDataFileError(result.write.error));}
        else setStorageStatus(permission==="denied"?"重新连接数据文件":"点击恢复数据同步",permission==="denied"?"error":"syncing",permission==="denied"?"上次文件的写入权限已被拒绝，请重新选择":"点击后重新授权写入");
      }catch(error){console.warn("[data-file] 无法恢复上次文件句柄；本次可重新选择",error);dataFileHandle=null;setStorageStatus("连接数据文件","", "未恢复上次连接，请重新选择正式 JSON");}
    }
    function mergeSavedShadowIntoRecord(externalRecord,localRecord){
      const external=normalizeRecord(externalRecord||{}),local=normalizeRecord(localRecord||{}),merged={...external,...local};
      // 本地明确编辑仍优先；本地“未知/空白”不得冲掉数据文件中已经审计过的
      // v0.4 真值、成本或证据。这对首次把旧 localStorage 接到迁移文件尤其重要。
      const present=(value)=>value!==null&&value!==undefined&&!(typeof value==="string"&&!value.trim());
      const evidenceUnion=(a,b)=>{const map=new Map();[...(Array.isArray(a)?a:[]),...(Array.isArray(b)?b:[])].filter(Boolean).forEach((x,i)=>{const key=x.path||x.name||x.id||`evidence-${i}`;map.set(key,{...(map.get(key)||{}),...x});});return [...map.values()];};
      merged.screenshots=evidenceUnion(external.screenshots,local.screenshots);
      merged.ocrEvidence=evidenceUnion(external.ocrEvidence,local.ocrEvidence);
      const es=external.settlement||{},ls=local.settlement||{},localComplete=explicitBoolean(local.redInventoryComplete??ls.redInventoryComplete),externalComplete=explicitBoolean(external.redInventoryComplete??es.redInventoryComplete),settlement={...es,...ls,screenshots:evidenceUnion(es.screenshots,ls.screenshots)};
      for(const key of ["highestPersonalBid","clearingPrice","purchaseSpend","goldCount","purpleCount","redCount","actualTotal"])if(!present(ls[key])&&present(es[key]))settlement[key]=es[key];
      for(const key of ["resultReason","winner","truthSource","truthConfidence","note"])if(!present(ls[key])&&present(es[key]))settlement[key]=es[key];
      const localAcquired=explicitBoolean(local.acquired??ls.acquired),externalAcquired=explicitBoolean(external.acquired??es.acquired);
      settlement.acquired=localAcquired!==null?localAcquired:externalAcquired;
      merged.acquired=settlement.acquired;
      for(const key of ["actualTotal","goldCount","purpleCount","redCount","bid","highestPersonalBid","clearingPrice","purchaseSpend","resultReason"])merged[key]=present(local[key])?local[key]:external[key];
      const localState=ls.realizedState?.complete===true?ls.realizedState:local.realizedState?.complete===true?local.realizedState:null,externalState=es.realizedState?.complete===true?es.realizedState:external.realizedState?.complete===true?external.realizedState:null;
      settlement.realizedState=localState||externalState||null;merged.realizedState=settlement.realizedState;
      const useLocalRedTruth=localComplete!==null,chosenComplete=useLocalRedTruth?localComplete:externalComplete,chosenVerified=useLocalRedTruth?(local.settlementVerifiedRedItems??ls.verifiedRedItems??""):(external.settlementVerifiedRedItems??es.verifiedRedItems??"");
      merged.redInventoryComplete=chosenComplete;merged.settlementVerifiedRedItems=chosenVerified??"";settlement.redInventoryComplete=chosenComplete;settlement.verifiedRedItems=chosenVerified??"";
      const localCosts=local.costs||{},externalCosts=external.costs||{};merged.costs=localCosts.complete===true?localCosts:externalCosts.complete===true?externalCosts:Number(localCosts.total)>0?localCosts:externalCosts;merged.cost=merged.costs.total;settlement.costs=merged.costs;
      merged.settlement=settlement;
      // 同样保全“当时保存”的 Probability Shadow 与回合快照。
      if(external.prediction&&local.prediction){
        const ep=external.prediction,lp=local.prediction,epf=ep.probabilityProfile,lpf=lp.probabilityProfile;
        merged.prediction={...ep,...lp};
        if(epf&&(!lpf||!epf.shadowWhole||!lpf.shadowWhole)) merged.prediction.probabilityProfile={...epf,...(lpf||{}),shadowWhole:lpf?.shadowWhole||epf.shadowWhole};
      }else if(external.prediction&&!local.prediction) merged.prediction=external.prediction;
      const extRounds=new Map((external.rounds||[]).map(x=>[Number(x.round)||0,x])),localRounds=new Map((local.rounds||[]).map(x=>[Number(x.round)||0,x])),roundKeys=new Set([...extRounds.keys(),...localRounds.keys()]);
      merged.rounds=[...roundKeys].sort((a,b)=>a-b).map(key=>{
        const er=extRounds.get(key),lr=localRounds.get(key);if(!er)return lr;if(!lr)return er;
        const out={...er,...lr},ep=er.prediction,lp=lr.prediction;
        if(ep&&lp){out.prediction={...ep,...lp};const epf=ep.probabilityProfile,lpf=lp.probabilityProfile;if(epf&&(!lpf||!lpf.shadowWhole))out.prediction.probabilityProfile={...epf,...(lpf||{}),shadowWhole:lpf?.shadowWhole||epf.shadowWhole};}
        else if(ep&&!lp)out.prediction=ep;
        return out;
      });
      return normalizeRecord(merged);
    }
    function makeDataFileError(name,message){const error=new Error(message);error.name=name;return error;}
    function describeDataFileError(error){
      if(!error)return "未知文件错误";
      if(error.name==="DataFileFormatError")return error.message||"所选 JSON 不是有效的异环拍卖数据文件";
      if(error.name==="DataFileTooLargeError")return error.message;
      if(error.name==="NotAllowedError"&&/picker already active/i.test(String(error.message||"")))return "文件选择窗口已经打开；请在窗口中选择 JSON，或先关闭后重试";
      if(error.name==="NotAllowedError"||error.name==="SecurityError")return "没有获得该文件的读写权限；请重新选择并允许写入";
      if(error.name==="NotReadableError")return "所选文件当前无法读取；请确认它没有被其他程序锁定";
      if(error.name==="NoModificationAllowedError")return "所选文件或目录为只读，无法自动写回";
      if(isQuotaError(error))return "浏览器缓存空间不足；完整数据仍可保存到正式 JSON";
      return error.message?`数据文件操作失败：${error.message}`:"数据文件操作失败";
    }
    function parseExternalDataFile(text){
      const clean=String(text??"").replace(/^\uFEFF/,"").trim();if(!clean)throw makeDataFileError("DataFileFormatError","所选文件是空文件，没有可合并的 records");
      let external;try{external=JSON.parse(clean);}catch(_){throw makeDataFileError("DataFileFormatError","JSON 格式无效；原文件未被修改");}
      if(!external||typeof external!=="object"||Array.isArray(external)||!Array.isArray(external.records))throw makeDataFileError("DataFileFormatError","所选文件缺少 records 数组；原文件未被修改");
      const ids=new Set();for(const record of external.records){if(!record||typeof record!=="object"||!String(record.id||"").trim())throw makeDataFileError("DataFileFormatError","数据中存在缺少 id 的记录；原文件未被修改");if(ids.has(record.id))throw makeDataFileError("DataFileFormatError",`数据中存在重复 id：${record.id}；原文件未被修改`);ids.add(record.id);}
      return external;
    }
    async function mergeFromDataFile(){
      if(!dataFileHandle)throw makeDataFileError("DataFileConnectionError","尚未选择数据文件");
      const file=await dataFileHandle.getFile();if(Number(file.size)>64*1024*1024)throw makeDataFileError("DataFileTooLargeError",`数据文件 ${(file.size/1024/1024).toFixed(1)} MB，超过 64 MB 安全上限`);
      const external=parseExternalDataFile(await file.text()),map=new Map(external.records.map(r=>[r.id,normalizeRecord(r)]));
      state.records.forEach(r=>{const local=normalizeRecord(r),old=map.get(r.id);map.set(r.id,old?mergeSavedShadowIntoRecord(old,local):local);});
      const inbox=[...(Array.isArray(external.screenshotInbox)?external.screenshotInbox:[]),...(Array.isArray(state.screenshotInbox)?state.screenshotInbox:[])].filter(Boolean),inboxMap=new Map();inbox.forEach((x,i)=>{const key=x.path||x.name||x.id||`inbox-${i}`;inboxMap.set(key,{...(inboxMap.get(key)||{}),...x});});
      state={...external,...state,version:APP_VERSION,schemaVersion:SCHEMA_VERSION,records:[...map.values()],screenshotInbox:[...inboxMap.values()]};
      // 本地缓存只是加速启动；即使配额不足，也必须继续写回权威 JSON。
      const cache=persistLocalCache({preferCompact:true});renderScreenshotInbox();renderReview();
      const write=await writeDataFile();return {ok:write.ok,records:state.records.length,cache,write};
    }
    async function writeDataFileOnce(){
      if(!dataFileHandle)return {ok:false,error:makeDataFileError("DataFileConnectionError","尚未选择数据文件")};
      setStorageStatus("正在写入数据…","syncing");let writable=null;
      try{
        const snapshot=JSON.stringify({...stateForPersistence(),version:APP_VERSION,schemaVersion:SCHEMA_VERSION,savedAt:new Date().toISOString()},null,2);writable=await dataFileHandle.createWritable();await writable.write(snapshot);await writable.close();setStorageStatus("数据文件已同步","","完整 JSON 已写回；浏览器仅保留精简启动缓存");return {ok:true};
      }catch(error){try{await writable?.abort?.();}catch(_){}console.error("[data-file] 写回失败",error);setStorageStatus("写回失败 · 点击重试","error",describeDataFileError(error));return {ok:false,error};}
    }
    function writeDataFile(){
      if(!dataFileHandle)return Promise.resolve({ok:false,error:makeDataFileError("DataFileConnectionError","尚未选择数据文件")});
      writeRequested=true;if(writeLoopPromise)return writeLoopPromise;writingFile=true;
      writeLoopPromise=(async()=>{let result={ok:true};try{while(writeRequested){writeRequested=false;result=await writeDataFileOnce();if(!result.ok){writeRequested=false;break;}}return result;}finally{writingFile=false;writeLoopPromise=null;}})();return writeLoopPromise;
    }
    function scheduleFileWrite(){if(!dataFileHandle)return;clearTimeout(fileWriteTimer);fileWriteTimer=setTimeout(()=>{fileWriteTimer=null;void writeDataFile();},220);}
    async function requestWritePermission(handle){let permission=typeof handle.queryPermission==="function"?await handle.queryPermission({mode:"readwrite"}):"prompt";if(permission==="prompt"&&typeof handle.requestPermission==="function")permission=await handle.requestPermission({mode:"readwrite"});return permission;}
    async function finishDataFileConnection(handle,recovered=false){
      dataFileHandle=handle;const result=await mergeFromDataFile();if(!result.write.ok){const message=describeDataFileError(result.write.error);setStorageStatus("写回失败 · 点击重试","error",message);toast(message,true);return false;}
      let remembered=true;try{await storeDataHandle(handle);}catch(error){remembered=false;console.warn("[data-file] 本次已连接，但无法记住文件句柄",error);}
      const notes=[];if(result.cache.mode!=="full")notes.push("浏览器缓存已精简");if(!remembered)notes.push("刷新后需重新选择文件");setStorageStatus("数据文件已同步","",`已加载 ${result.records} 条记录；完整数据写回正式 JSON`);toast(`${recovered?"已恢复":"已连接"}数据文件并同步 ${result.records} 条记录${notes.length?`；${notes.join("，")}`:""}`);return true;
    }
    async function connectDataFile(){
      if(!window.showOpenFilePicker){setStorageStatus("改用导入 / 导出","error","当前页面环境不能直接写回本地文件");toast("当前页面环境不能直接写回文件；请用 Chromium/Edge 打开 HTML，或在复盘页使用导入/导出 JSON",true);return;}
      try{
        if(dataFileHandle){const permission=await requestWritePermission(dataFileHandle);if(permission==="granted"){await finishDataFileConnection(dataFileHandle,true);return;}dataFileHandle=null;}
        const [handle]=await showOpenFilePicker({multiple:false,types:[{description:"异环拍卖数据",accept:{"application/json":[".json"]}}]});if(!handle)return;
        const permission=await requestWritePermission(handle);if(permission!=="granted"){setStorageStatus("未授权写回 · 重试","error","没有获得所选 JSON 的写权限");toast("没有获得文件写入权限；请重新连接并允许写入",true);return;}
        try{await finishDataFileConnection(handle,false);}catch(error){dataFileHandle=null;throw error;}
      }catch(error){if(error?.name==="AbortError")return;console.error("[data-file] 连接失败",error);const message=describeDataFileError(error);setStorageStatus("连接失败 · 重试","error",message);toast(message,true);}
    }
    document.getElementById("dataFileBtn").addEventListener("click",connectDataFile);
    window.runDataFileV04SelfTest=function(){
      const valid=parseExternalDataFile('\uFEFF {"records":[{"id":"a"}]}').records.length===1;let invalidRejected=false,duplicateRejected=false;
      try{parseExternalDataFile('{"records":null}');}catch(error){invalidRejected=error.name==="DataFileFormatError";}
      try{parseExternalDataFile('{"records":[{"id":"a"},{"id":"a"}]}');}catch(error){duplicateRejected=error.name==="DataFileFormatError";}
      const full=JSON.stringify(stateForPersistence()).length,compact=JSON.stringify(stateForLocalCache()).length,compactState=stateForLocalCache(),cacheStripped=compactState.records.every(r=>(r.screenshots||[]).every(x=>!Object.hasOwn(x,"thumbnailDataUrl")&&!Object.hasOwn(x,"dataUrl"))&&(r.rounds||[]).every(round=>!round.prediction?.probabilityProfile));
      return {pass:valid&&invalidRejected&&duplicateRejected&&compact<=full&&cacheStripped,checks:{validBomJson:valid,invalidRejected,duplicateRejected,compactNotLarger:compact<=full,cacheStripped,fullChars:full,compactChars:compact}};
    };

    function toast(message,error=false) {
      const el=document.getElementById("toast");
      if(!el){ if(error) console.error(message); else console.log(message); return; }
      el.textContent=message; el.className=`toast show${error?" error":""}`;
      clearTimeout(toast.timer); toast.timer=setTimeout(()=>el.className="toast",2600);
    }

    document.querySelectorAll(".nav button").forEach(btn => btn.addEventListener("click",()=>{ if(btn.dataset.page) showPage(btn.dataset.page); }));
    function showPage(name) {
      document.querySelectorAll(".nav button").forEach(b=>b.classList.toggle("active",b.dataset.page===name));
      document.querySelectorAll(".page").forEach(p=>p.classList.toggle("active",p.id===`page-${name}`));
      if(name==="review") renderReview();
      if(name==="intel") renderCatalog();
      if(name==="capture") updateQuality();
      window.scrollTo({top:0,behavior:"smooth"});
    }

    document.querySelectorAll("#roundingMode button").forEach(btn=>btn.addEventListener("click",()=>{
      document.querySelectorAll("#roundingMode button").forEach(x=>x.classList.remove("active")); btn.classList.add("active"); roundingMode=btn.dataset.value;
    }));

    // 每个“+”分组都是独立看见的一件（或 *n 件）藏品；“/”只表示该
    // 槽位的候选。这里用最小费用流给槽位分配不同的图鉴实例，避免两个
    // 相交 OR 分组复用同一件藏品。图鉴中每个条目仍遵守全局 repeat=2。
    function minimumConstraintAssignment(groups,items,repeat=2){
      const slots=[];
      for(const group of groups||[]){
        const prices=[...new Set((Array.isArray(group?.[0])?group[0]:[]).map(Number).filter(Number.isFinite))],required=Math.max(0,Math.trunc(Number(group?.[1])||0));
        for(let i=0;i<required;i++)slots.push(prices);
      }
      if(!slots.length)return {feasible:true,floor:0,assigned:0,required:0};
      const catalogCapacity=new Map();
      for(const item of items||[]){const price=Number(item?.[1]);if(Number.isFinite(price))catalogCapacity.set(price,(catalogCapacity.get(price)||0)+repeat);}
      const priceList=[...new Set(slots.flat())].filter(price=>catalogCapacity.has(price)).sort((a,b)=>a-b);
      const source=0,slotOffset=1,priceOffset=slotOffset+slots.length,sink=priceOffset+priceList.length,nodeCount=sink+1,graph=Array.from({length:nodeCount},()=>[]);
      const addEdge=(from,to,capacity,cost)=>{const f={to,rev:graph[to].length,capacity,cost},r={to:from,rev:graph[from].length,capacity:0,cost:-cost};graph[from].push(f);graph[to].push(r);};
      slots.forEach((allowed,index)=>{addEdge(source,slotOffset+index,1,0);const allowedSet=new Set(allowed);priceList.forEach((price,priceIndex)=>{if(allowedSet.has(price))addEdge(slotOffset+index,priceOffset+priceIndex,1,price);});});
      priceList.forEach((price,index)=>addEdge(priceOffset+index,sink,catalogCapacity.get(price)||0,0));
      let flow=0,cost=0;
      while(flow<slots.length){
        const dist=Array(nodeCount).fill(Infinity),prevNode=Array(nodeCount).fill(-1),prevEdge=Array(nodeCount).fill(-1),queued=Array(nodeCount).fill(false),queue=[source];dist[source]=0;queued[source]=true;
        for(let head=0;head<queue.length;head++){
          const node=queue[head];queued[node]=false;
          graph[node].forEach((edge,index)=>{if(edge.capacity<=0||dist[node]+edge.cost>=dist[edge.to])return;dist[edge.to]=dist[node]+edge.cost;prevNode[edge.to]=node;prevEdge[edge.to]=index;if(!queued[edge.to]){queued[edge.to]=true;queue.push(edge.to);}});
        }
        if(!Number.isFinite(dist[sink]))break;
        for(let node=sink;node!==source;node=prevNode[node]){const edge=graph[prevNode[node]][prevEdge[node]];edge.capacity--;graph[node][edge.rev].capacity++;}
        flow++;cost+=dist[sink];
      }
      return {feasible:flow===slots.length,floor:flow===slots.length?cost:null,assigned:flow,required:slots.length};
    }
    // 金 / 紫 / 红共用同一套“名称或价格 + / 候选 + *n 数量”语法。
    function parseFlexibleKnown(raw,items,label,options={}){
      const text=String(raw||"").trim();
      if(!text||text==="0")return {known:[],groups:[],constraintCount:0};
      const multiplier=Math.max(1,Number(options.multiplier)||1),basis=["base","effective","unknown"].includes(String(options.basis||"").toLowerCase())?String(options.basis).toLowerCase():"unknown";
      const resolveItem=(part)=>{
        const numeric=Number(String(part).replaceAll(",","")),canonical=CATALOG_NAME_ALIASES[part]||part;
        const named=items.find(x=>x[0]===canonical||x[0]===part);if(named)return named;
        if(!Number.isFinite(numeric)||numeric<=0)return null;
        const direct=items.find(x=>Number(x[1])===numeric),effective=multiplier>1&&Number.isInteger(numeric/multiplier)?items.find(x=>Number(x[1])===numeric/multiplier):null;
        // 双倍场截图通常直接显示翻倍后的价格。把它还原成图鉴原价，
        // 后续统一由 effectiveCatalog / conditionAdjustedGroups 再应用倍率。
        if(basis==="effective")return effective||direct;
        if(basis==="base")return direct;
        return direct||effective;
      };
      const groups=[],known=[];
      for(const token of text.split(/[+；;\n]/).map(x=>x.trim()).filter(Boolean)){
        const match=token.match(/^(.*?)(?:\*(\d+))?$/),key=match?.[1]?.trim(),count=match?.[2]?Number(match[2]):1;
        if(!key||!Number.isInteger(count)||count<1)throw new Error(`${label}已知藏品格式错误：${token}`);
        const candidates=key.split("/").map(part=>part.trim()).filter(Boolean);
        if(!candidates.length)throw new Error(`${label}已知藏品格式错误：${token}`);
        let singleResolvedItem=null;
        const prices=[...new Set(candidates.map(part=>{
          const item=resolveItem(part);
          if(!item)throw new Error(`${label}图鉴中找不到：${part}`);if(candidates.length===1)singleResolvedItem=item;return Number(item[1]);
        }))].sort((a,b)=>a-b);
        groups.push([prices,count]);
        if(prices.length===1){const item=singleResolvedItem||items.find(x=>Number(x[1])===prices[0]);for(let i=0;i<count;i++)known.push({name:item[0],price:Number(item[1]),size:item[2]});}
      }
      const assignment=minimumConstraintAssignment(groups,items,2);
      if(!assignment.feasible)throw new Error(`${label}约束需要 ${assignment.required} 件独立藏品，但候选价格在 repeat=2 下只能分配 ${assignment.assigned} 件`);
      return {known,groups,constraintCount:groups.reduce((sum,x)=>sum+Number(x[1]||0),0),constraintFloor:assignment.floor,inputBasis:basis,multiplier};
    }
    function parseOr(raw,options={}){return parseFlexibleKnown(raw,GOLD_ITEMS,"金色",options).groups;}
    function parseKnownItems(raw,items,label,options={}){return parseFlexibleKnown(raw,items,label,options).known;}
    function constraintEvidenceFloor(known,groups,items,repeat=2){
      const named=(known||[]).reduce((sum,item)=>sum+(Number(item?.price)||0),0),assignment=minimumConstraintAssignment(groups||[],items,repeat),grouped=assignment.feasible?(assignment.floor||0):0;
      // exact knownItems are also represented by singleton groups. max() keeps the
      // evidence once; the capacity-aware assignment accounts for overlapping ORs.
      return {named,grouped,total:Math.max(named,grouped),feasible:assignment.feasible};
    }
    function knownGroups(known){const counts=new Map();known.forEach(x=>counts.set(x.price,(counts.get(x.price)||0)+1));return [...counts].map(([price,count])=>[[price],count]);}

    const WORKER_SOURCE = `
      const INF=Number.POSITIVE_INFINITY, NEG=Number.NEGATIVE_INFINITY;
      let deadlineAt=0, timedOut=false, walkTicks=0;
      function bounds(avg,count,mode){
        const floor=[count*avg,count*(avg+1)-1];
        const near=[Math.ceil(count*(avg-.5)),Math.ceil(count*(avg+.5))-1];
        if(mode==='floor')return floor;
        if(mode==='nearest')return near;
        return [Math.min(floor[0],near[0]),Math.max(floor[1],near[1])];
      }
      function tables(prices,maxCount,repeat){
        const m=prices.length, mn=Array.from({length:m+1},()=>Array(maxCount+1).fill(INF)), mx=Array.from({length:m+1},()=>Array(maxCount+1).fill(NEG));
        mn[m][0]=mx[m][0]=0;
        for(let i=m-1;i>=0;i--){mn[i][0]=mx[i][0]=0; for(let need=1;need<=maxCount;need++){for(let take=0;take<=Math.min(repeat,need);take++){const rem=need-take;if(mn[i+1][rem]!==INF)mn[i][need]=Math.min(mn[i][need],take*prices[i]+mn[i+1][rem]);if(mx[i+1][rem]!==NEG)mx[i][need]=Math.max(mx[i][need],take*prices[i]+mx[i+1][rem]);}}}
        return [mn,mx];
      }
      function jointTables(prices,grids,maxCount,maxGrid,repeat){
        const m=prices.length,mn=Array.from({length:m+1},()=>Array.from({length:maxCount+1},()=>{const row=new Float64Array(maxGrid+1);row.fill(INF);return row;})),mx=Array.from({length:m+1},()=>Array.from({length:maxCount+1},()=>{const row=new Float64Array(maxGrid+1);row.fill(NEG);return row;}));
        mn[m][0][0]=mx[m][0][0]=0;
        for(let i=m-1;i>=0;i--){
          const price=prices[i],grid=grids[i];
          for(let need=0;need<=maxCount;need++)for(let cells=0;cells<=maxGrid;cells++)for(let take=0;take<=Math.min(repeat,need);take++){
            const usedGrid=take*grid;if(usedGrid>cells)break;const remNeed=need-take,remGrid=cells-usedGrid;
            if(mn[i+1][remNeed][remGrid]!==INF)mn[i][need][cells]=Math.min(mn[i][need][cells],take*price+mn[i+1][remNeed][remGrid]);
            if(mx[i+1][remNeed][remGrid]!==NEG)mx[i][need][cells]=Math.max(mx[i][need][cells],take*price+mx[i+1][remNeed][remGrid]);
          }
        }
        return [mn,mx];
      }
      function groupsSatisfiedWithCapacity(combo,groups){
        const slots=[];
        for(const group of groups||[]){const allowed=new Set(group[0]||[]),required=Math.max(0,Math.trunc(Number(group[1])||0));for(let i=0;i<required;i++)slots.push(allowed);}
        if(!slots.length)return true;if(slots.length>combo.length)return false;
        slots.sort((a,b)=>a.size-b.size);
        const owner=Array(combo.length).fill(-1);
        function assign(slotIndex,seen){
          const allowed=slots[slotIndex];
          for(let itemIndex=0;itemIndex<combo.length;itemIndex++){
            if(seen[itemIndex]||!allowed.has(combo[itemIndex]))continue;
            seen[itemIndex]=true;
            if(owner[itemIndex]===-1||assign(owner[itemIndex],seen)){owner[itemIndex]=slotIndex;return true;}
          }
          return false;
        }
        for(let slotIndex=0;slotIndex<slots.length;slotIndex++)if(!assign(slotIndex,Array(combo.length).fill(false)))return false;
        return true;
      }
      function search(prices,count,low,high,repeat,groups,limit,precomputed,itemGrids=null,gridTarget=null,jointPrecomputed=null,countAll=false){
        prices=[...prices].sort((a,b)=>a-b); if(count===0){const ok=low<=0&&high>=0&&(gridTarget===null||gridTarget===0)&&!groups.length;return ok?{matches:[[]],truncated:false,matchCount:1,matchCountExact:true}: {matches:[],truncated:false,matchCount:0,matchCountExact:true};} if(count<0||count>prices.length*repeat)return {matches:[],truncated:false,matchCount:0,matchCountExact:true};
        const [mn,mx]=precomputed||tables(prices,count,repeat),[jmn,jmx]=gridTarget===null?[null,null]:(jointPrecomputed||jointTables(prices,itemGrids,count,gridTarget,repeat)); if(mn[0][count]>high||mx[0][count]<low)return {matches:[],truncated:false,matchCount:0,matchCountExact:true};
        if(gridTarget!==null&&(jmn[0][count][gridTarget]===INF||jmn[0][count][gridTarget]>high||jmx[0][count][gridTarget]<low))return {matches:[],truncated:false,matchCount:0,matchCountExact:true};
        const caps=groups.map(()=>Array(prices.length+1).fill(0));
        groups.forEach((g,gi)=>{const allowed=new Set(g[0]);for(let i=prices.length-1;i>=0;i--)caps[gi][i]=caps[gi][i+1]+(allowed.has(prices[i])?repeat:0);});
        const memberships=prices.map(p=>groups.map((g,i)=>g[0].includes(p)?i:-1).filter(i=>i>=0));
        const counts=groups.map(()=>0), combo=[], results=[], seen=new Set(); let truncated=false,matchCount=0,matchCountExact=true;
        const countLimit=countAll?25000:limit+1;
        function walk(index,sum,gridSum,remaining){
          if((++walkTicks&1023)===0&&deadlineAt&&performance.now()>deadlineAt){timedOut=true;return;}
          if(matchCount>=countLimit){truncated=true;matchCountExact=false;return;}
          if(remaining===0){if(sum>=low&&sum<=high&&(gridTarget===null||gridSum===gridTarget)&&groupsSatisfiedWithCapacity(combo,groups)){const key=combo.join(',');if(!seen.has(key)){seen.add(key);matchCount++;if(results.length<limit)results.push([...combo]);}}return;}
          if(index>=prices.length||mn[index][remaining]===INF||sum+mn[index][remaining]>high||sum+mx[index][remaining]<low)return;
          if(gridTarget!==null){const cells=gridTarget-gridSum;if(cells<0||jmn[index][remaining][cells]===INF||sum+jmn[index][remaining][cells]>high||sum+jmx[index][remaining][cells]<low)return;}
          if(groups.some((g,i)=>counts[i]+caps[i][index]<g[1]))return;
          const price=prices[index],grid=gridTarget===null?0:itemGrids[index];
          for(let take=0;take<=Math.min(repeat,remaining);take++){
            const ns=sum+take*price,ng=gridSum+take*grid,nr=remaining-take;
            if(mn[index+1][nr]===INF||ns+mn[index+1][nr]>high||ns+mx[index+1][nr]<low)continue;
            if(gridTarget!==null){const cells=gridTarget-ng;if(cells<0||jmn[index+1][nr][cells]===INF||ns+jmn[index+1][nr][cells]>high||ns+jmx[index+1][nr][cells]<low)continue;}
            for(let x=0;x<take;x++)combo.push(price); memberships[index].forEach(i=>counts[i]+=take);
            walk(index+1,ns,ng,nr);
            memberships[index].forEach(i=>counts[i]-=take); if(take)combo.splice(combo.length-take,take);
            if(truncated||timedOut)return;
          }
        }
        walk(0,0,0,count); return {matches:results,truncated,matchCount,matchCountExact,timedOut};
      }
      function extreme(prices,count,maximize,repeat){if(count<0||count>prices.length*repeat)return null;if(count===0)return 0;const expanded=[];prices.forEach(p=>{for(let i=0;i<repeat;i++)expanded.push(p);});expanded.sort((a,b)=>maximize?b-a:a-b);return expanded.slice(0,count).reduce((a,b)=>a+b,0);}
      function poolSolutions(prices,maxCount,minCount,avg,total,mode,groups,repeat,limit,progress,grids=null,gridTotal=null){
        const out=[];
        if(avg===null&&total===null&&!groups.length&&gridTotal===null){for(let count=minCount;count<=maxCount;count++)out.push({count,matches:[],truncated:true,matchCount:0,matchCountExact:false,low:extreme(prices,count,false,repeat),high:extreme(prices,count,true,repeat),unconstrained:true});return out;}
      const pairs=prices.map((price,i)=>({price,grid:grids?.[i]??0})).sort((a,b)=>a.price-b.price),sortedPrices=pairs.map(x=>x.price),sortedGrids=pairs.map(x=>x.grid),precomputed=tables(sortedPrices,maxCount,repeat),jointPrecomputed=gridTotal===null?null:jointTables(sortedPrices,sortedGrids,maxCount,gridTotal,repeat);
        // 占格约束只需要返回少量可行组合供 State Inference 估值；
        // 过去为了计算“精确组合总数”把 countLimit 放大到 25,000，
        // 在 Q 较大、格数较宽时会把浏览器拖到像“卡死”。
        // search 默认只保留 limit+1 个匹配，并用 truncated 标记“还有更多”，
        // 不影响格数硬约束本身，也不影响候选状态的合法性。
        const countAll=false;
        for(let count=Math.max(minCount,(avg!==null||total!==null||groups.length)?1:0);count<=maxCount;count++){
          let low=0,high=Number.MAX_SAFE_INTEGER;
          if(avg!==null){const b=bounds(avg,count,mode);low=Math.max(low,b[0]);high=Math.min(high,b[1]);}
          if(total!==null){low=Math.max(low,total);high=Math.min(high,total);}
          if(avg===null&&total===null){low=extreme(prices,count,false,repeat);high=extreme(prices,count,true,repeat);}
              if(low<=high){const result=search(sortedPrices,count,low,high,repeat,groups,limit,precomputed,sortedGrids,gridTotal,jointPrecomputed,countAll);if(result.matches.length||result.matchCount){const sums=result.matches.map(c=>c.reduce((a,b)=>a+b,0)),groupOnly=avg===null&&total===null&&groups.length>0;out.push({count,matches:result.matches,truncated:result.truncated,matchCount:result.matchCount,matchCountExact:result.matchCountExact,grid:gridTotal,low:groupOnly&&sums.length?Math.min(...sums):low,high:groupOnly&&sums.length?Math.max(...sums):high,unconstrained:avg===null&&total===null&&!groups.length,groupOnly});}if(result.timedOut)out.timedOut=true;}
          if(progress)progress();
          if(timedOut)break;
        }
        return out;
      }
      function compactStates(states){
        const seen=new Set(),out=[];
        for(const s of states||[]){
          const key=[s.g,s.p,s.r,s.rMin,s.rMax].join('/');
          if(seen.has(key))continue;
          seen.add(key);out.push({G:s.g,P:s.p,R:s.r,Rmin:s.rMin??null,Rmax:s.rMax??null});
        }
        return out;
      }
      function summarizeGold(goldSolutions,q,fixedPurple,minRed=0,fixedRed=null){
        // 诊断表也必须遵守同一条数量关系：Q=P+G+R。过去这里直接
        // 展开全部金色 G，导致 P 已知时把 R=-1、-2…渲染出来。
        // 这只过滤不合法的展示行，不改变金色组合的求解或价格边界。
        const rows=(goldSolutions||[]).map(s=>({G:s.count,combinationCount:s.matchCount??s.matches?.length??0,combinationCountExact:s.matchCountExact!==false&&!s.truncated,combinations:(s.matches||[]).map(combo=>({prices:[...combo],total:combo.reduce((a,b)=>a+b,0)}))})).filter(row=>{
          if(q===null||q===undefined)return true;
          const r=fixedPurple===null||fixedPurple===undefined?null:Number(q)-Number(row.G)-Number(fixedPurple);
          if(fixedPurple!==null&&fixedPurple!==undefined&&(!Number.isFinite(r)||r<Number(minRed)|| (fixedRed!==null&&fixedRed!==undefined&&r!==Number(fixedRed))))return false;
          return true;
        });
        const candidateGs=rows.map(x=>x.G),totalCount=rows.reduce((sum,x)=>sum+x.combinationCount,0),uniqueG=candidateGs.length===1,uniqueCombination=uniqueG&&rows[0].combinationCount===1&&rows[0].combinationCountExact;
        return {goldMatchCount:totalCount,goldMatchCountExact:rows.every(x=>x.combinationCountExact),candidateGs,byG:rows,uniqueG,uniqueCombination,q:q??null,fixedPurple:fixedPurple??null,remainingByG:q===null?[]:rows.map(x=>({G:x.G,PplusR:q-x.G,P:fixedPurple??null,R:fixedPurple===null?null:q-x.G-fixedPurple}))};
      }
      self.onmessage=e=>{
        const {goldPrices,goldGrids,purplePrices,redPrices,q,goldAvg,goldAvgCandidates,goldTotal,goldTotalCandidates,goldGrid,purpleAvg,purpleAvgCandidates,fixedGold,fixedPurple,fixedRed,minGold,minPurple,minRed,mode,groups,purpleGroups,redGroups,repeat,limit,goldOnly}=e.data;
        const purpleConstrained=purpleAvg!==null||purpleGroups.length>0||fixedPurple!==null,redConstrained=redGroups.length>0||fixedRed!==null, started=performance.now(), maxG=Math.min(fixedGold!==null?fixedGold:q,goldPrices.length*repeat), maxP=Math.min(fixedPurple!==null?fixedPurple:q,purplePrices.length*repeat), maxR=Math.min(fixedRed!==null?fixedRed:q,redPrices.length*repeat),gCandidateN=Math.max(1,(goldAvgCandidates||[]).length)*Math.max(1,(goldTotalCandidates||[]).length),pCandidateN=Math.max(1,(purpleAvgCandidates||[]).length),totalSteps=(goldAvg!==null||goldTotal!==null||groups.length||goldGrid!==null||fixedGold!==null?maxG*gCandidateN:0)+(purpleConstrained?maxP*pCandidateN:0)+(redConstrained?maxR:0);let step=0;
        const progress=()=>{step++;self.postMessage({type:'progress',step,maxSteps:Math.max(totalSteps,1),requestId:e.data.requestId??null,inputHash:e.data.inputHash||null,startedAt:e.data.startedAt||null});};
        const mergeAverageSolutions=collections=>{const map=new Map();for(const list of collections||[])for(const s of list||[]){const prev=map.get(s.count);if(!prev)map.set(s.count,{...s,matches:[...(s.matches||[])]});else{const matches=[...(prev.matches||[]),...(s.matches||[])],seen=new Set();prev.matches=matches.filter(combo=>{const key=combo.join(',');if(seen.has(key))return false;seen.add(key);return true;}).slice(0,limit);prev.low=Math.min(prev.low,s.low);prev.high=Math.max(prev.high,s.high);prev.truncated=prev.truncated||s.truncated;prev.matchCount=Math.max(prev.matchCount||0,s.matchCount||0);prev.matchCountExact=prev.matchCountExact&&s.matchCountExact;prev.avgBasisAmbiguous=true;}}return [...map.values()].sort((a,b)=>a.count-b.count);};
        const solvePools=(roundMode,reportProgress)=>{
          const solveLimit=reportProgress?limit:1;
          const gAvgs=Array.isArray(goldAvgCandidates)&&goldAvgCandidates.length?goldAvgCandidates:[goldAvg],gTotals=Array.isArray(goldTotalCandidates)&&goldTotalCandidates.length?goldTotalCandidates:[goldTotal],pAvgs=Array.isArray(purpleAvgCandidates)&&purpleAvgCandidates.length?purpleAvgCandidates:[purpleAvg];
          const goldSolutions=mergeAverageSolutions(gAvgs.flatMap(avg=>gTotals.map(total=>poolSolutions(goldPrices,maxG,fixedGold!==null?fixedGold:minGold,avg,total,roundMode,groups,repeat,solveLimit,(avg!==null||total!==null||groups.length||goldGrid!==null)?(reportProgress?progress:null):null,goldGrids||null,goldGrid))));
          const purpleSolutions=purpleConstrained?mergeAverageSolutions(pAvgs.map(avg=>poolSolutions(purplePrices,maxP,fixedPurple!==null?fixedPurple:minPurple,avg,null,roundMode,purpleGroups,repeat,solveLimit,reportProgress?progress:null))):[];
          return {goldSolutions,purpleSolutions,timedOut:!!(goldSolutions.timedOut||purpleSolutions.timedOut||timedOut)};
        };
        const buildStates=(goldSolutions,purpleSolutions,redSolutions)=>{
          const purpleByCount=new Map(purpleSolutions.map(x=>[x.count,x])),redByCount=new Map(redSolutions.map(x=>[x.count,x])),states=[];
          for(const gold of goldSolutions){
            const g=gold.count;let pValues;
            if(fixedPurple!==null)pValues=[fixedPurple];
            else if(fixedRed!==null)pValues=[q-g-fixedRed];
            else if(purpleConstrained)pValues=purpleSolutions.map(x=>x.count).filter(p=>p<=q-g);
            else pValues=[null];
            for(const p of pValues){
              if(p===null){const rest=q-g;if(rest<minPurple+minRed)continue;let validR=null;if(redConstrained){validR=redSolutions.map(x=>x.count).filter(r=>r>=minRed&&r<=rest-minPurple);if(!validR.length)continue;}const rMin=validR?Math.min(...validR):minRed,rMax=validR?Math.max(...validR):rest-minPurple;states.push({g,p:null,r:null,rMin,rMax,gold,purple:null,red:validR?.length===1?redByCount.get(validR[0]):null});continue;}
              const r=fixedRed!==null?fixedRed:q-g-p;if(p<minPurple||r<minRed||g+p+r!==q)continue;if(redConstrained&&!redByCount.has(r))continue;
              const purple=purpleConstrained?purpleByCount.get(p):null;if(purpleConstrained&&!purple)continue;
              states.push({g,p,r,rMin:r,rMax:r,gold,purple,red:redConstrained?redByCount.get(r):null});
            }
          }
          return states;
        };
        deadlineAt=started+Math.max(250,Number(e.data.timeBudgetMs)||8000);timedOut=false;walkTicks=0;
        const redSolutions=redConstrained?poolSolutions(redPrices,maxR,fixedRed!==null?fixedRed:minRed,null,null,'floor',redGroups,repeat,limit,progress):[];
        const needsAudit=goldAvg!==null||purpleAvg!==null;
        const selected=solvePools(mode,true);
        if(goldOnly){
          const mergePoolSolutions=(a,b)=>{const map=new Map();for(const s of [...(a||[]),...(b||[])]){const prev=map.get(s.count);if(!prev)map.set(s.count,{...s,matches:(s.matches||[]).slice(0,1)});else map.set(s.count,{...prev,low:Math.min(prev.low,s.low),high:Math.max(prev.high,s.high),matches:[...(prev.matches||[]),...(s.matches||[])].slice(0,1),truncated:prev.truncated||s.truncated});}return [...map.values()].sort((x,y)=>x.count-y.count);};
          const floor=mode==='floor'?selected:solvePools('floor',false),nearest=mode==='nearest'?selected:solvePools('nearest',false),compatible=mode==='either'?selected:{goldSolutions:mergePoolSolutions(floor.goldSolutions,nearest.goldSolutions),purpleSolutions:mergePoolSolutions(floor.purpleSolutions,nearest.purpleSolutions)},modes={floor,nearest,compatible};
          const goldRequired=goldAvg!==null||goldTotal!==null||groups.length||fixedGold!==null,purpleRequired=purpleAvg!==null||purpleGroups.length||fixedPurple!==null;
          const poolValid=x=>(!goldRequired||x.goldSolutions.length>0)&&(!purpleRequired||x.purpleSolutions.length>0);
          let chosenPools=selected,chosenMode=mode,fallbackReason=null;
          if(mode==='floor'&&!poolValid(selected)&&poolValid(nearest)){chosenPools=nearest;chosenMode='nearest';fallbackReason='floor-no-match-nearest-match';}
          else if(mode==='floor'&&!poolValid(selected)&&!poolValid(nearest)&&poolValid(compatible)){chosenPools=compatible;chosenMode='either';fallbackReason='floor-and-nearest-no-match-compatible-match';}
          const summarizePools=x=>({gold:x.goldSolutions.map(s=>({G:s.count,low:s.low,high:s.high,matchCount:s.matches?.length||0})),purple:x.purpleSolutions.map(s=>({P:s.count,low:s.low,high:s.high,matchCount:s.matches?.length||0}))});
          const roundingAudit=needsAudit?{hasAverage:true,stateType:'independent-pools',floorMatchCount:modes.floor.goldSolutions.length+modes.floor.purpleSolutions.length,nearestMatchCount:modes.nearest.goldSolutions.length+modes.nearest.purpleSolutions.length,compatibleMatchCount:modes.compatible.goldSolutions.length+modes.compatible.purpleSolutions.length,floorStates:[],nearestStates:[],compatibleStates:[],floorPools:summarizePools(modes.floor),nearestPools:summarizePools(modes.nearest),compatiblePools:summarizePools(modes.compatible),requestedRoundingMode:mode,chosenRoundingMode:chosenMode,fallbackReason}:null;
          const partialStates=chosenPools.goldSolutions.length>0||chosenPools.purpleSolutions.length>0,solverStatus=timedOut?(partialStates?'incomplete':'timeout'):(partialStates?'valid':'no-match');
          self.postMessage({type:'done',goldOnly:true,states:chosenPools.goldSolutions,purpleStates:chosenPools.purpleSolutions,redStates:redSolutions,goldInference:summarizeGold(chosenPools.goldSolutions,goldOnly?null:q,fixedPurple,minRed,fixedRed),chosenRoundingMode:chosenMode,roundingAudit,solverStatus,searchCompleted:!timedOut,truncated:timedOut||chosenPools.goldSolutions.some(x=>x.truncated)||chosenPools.purpleSolutions.some(x=>x.truncated),requestId:e.data.requestId??null,inputHash:e.data.inputHash||null,startedAt:e.data.startedAt||null,elapsed:performance.now()-started});return;
        }
        const mergePoolSolutions=(a,b)=>{const map=new Map();for(const s of [...(a||[]),...(b||[])]){const prev=map.get(s.count);if(!prev)map.set(s.count,{...s,matches:(s.matches||[]).slice(0,1)});else map.set(s.count,{...prev,low:Math.min(prev.low,s.low),high:Math.max(prev.high,s.high),matches:[...(prev.matches||[]),...(s.matches||[])].slice(0,1),truncated:prev.truncated||s.truncated});}return [...map.values()].sort((x,y)=>x.count-y.count);};
        const floor=needsAudit?(mode==='floor'?selected:solvePools('floor',false)):null,nearest=needsAudit?(mode==='nearest'?selected:solvePools('nearest',false)):null,compatible=needsAudit?(mode==='either'?selected:{goldSolutions:mergePoolSolutions(floor.goldSolutions,nearest.goldSolutions),purpleSolutions:mergePoolSolutions(floor.purpleSolutions,nearest.purpleSolutions)}):null;
        const selectedRed=redSolutions;
        const selectedStates=buildStates(selected.goldSolutions,selected.purpleSolutions,selectedRed);
        let audit=null,chosenMode=mode,chosenStates=selectedStates,chosenPools=selected;
        if(needsAudit){
          const floorStates=buildStates(floor.goldSolutions,floor.purpleSolutions,selectedRed),nearestStates=buildStates(nearest.goldSolutions,nearest.purpleSolutions,selectedRed),compatibleStates=buildStates(compatible.goldSolutions,compatible.purpleSolutions,selectedRed);
          const fKeys=new Set(floorStates.map(s=>[s.g,s.p,s.r,s.rMin,s.rMax].join('/'))),nKeys=new Set(nearestStates.map(s=>[s.g,s.p,s.r,s.rMin,s.rMax].join('/'))),intersection=nearestStates.filter(s=>fKeys.has([s.g,s.p,s.r,s.rMin,s.rMax].join('/')));
          audit={hasAverage:true,stateType:'GPR',floorMatchCount:floorStates.length,nearestMatchCount:nearestStates.length,compatibleMatchCount:compatibleStates.length,floorStates:compactStates(floorStates),nearestStates:compactStates(nearestStates),compatibleStates:compactStates(compatibleStates),intersectionStates:compactStates(intersection),floorOnlyStates:compactStates(floorStates.filter(s=>!new Set(nearestStates.map(x=>[x.g,x.p,x.r,x.rMin,x.rMax].join('/'))).has([s.g,s.p,s.r,s.rMin,s.rMax].join('/')))),nearestOnlyStates:compactStates(nearestStates.filter(s=>!fKeys.has([s.g,s.p,s.r,s.rMin,s.rMax].join('/')))),requestedRoundingMode:mode,chosenRoundingMode:mode,fallbackReason:null};
          if(mode==='floor'&&floorStates.length===0&&nearestStates.length>0){chosenMode='nearest';chosenStates=nearestStates;chosenPools=nearest;audit.chosenRoundingMode='nearest';audit.fallbackReason='floor-no-match-nearest-match';}
          else if(mode==='floor'&&floorStates.length===0&&nearestStates.length===0&&compatibleStates.length>0){chosenMode='either';chosenStates=compatibleStates;chosenPools=compatible;audit.chosenRoundingMode='either';audit.fallbackReason='floor-and-nearest-no-match-compatible-match';}
          else if(floorStates.length>0&&nearestStates.length>0&&floorStates.length===nearestStates.length&&intersection.length===floorStates.length){audit.fallbackReason='same-structure-under-floor-and-nearest';}
        }
        const solverStatus=timedOut?(chosenStates.length?'incomplete':'timeout'):(chosenStates.length?'valid':'no-match');
        self.postMessage({type:'done',states:chosenStates,goldInference:summarizeGold(chosenPools.goldSolutions,goldOnly?null:q,fixedPurple,minRed,fixedRed),roundingAudit:audit,chosenRoundingMode:chosenMode,solverStatus,searchCompleted:!timedOut,truncated:timedOut||chosenStates.some(x=>x.gold?.truncated||x.purple?.truncated||x.red?.truncated),requestId:e.data.requestId??null,inputHash:e.data.inputHash||null,startedAt:e.data.startedAt||null,elapsed:performance.now()-started});
      };
    `;

    let inferenceCoreRuntime=null;
    function averageValueBasis(ctx={},rarity){
      const raw=ctx.avgValueBasis??ctx.intelPriceBasis,basis=raw&&typeof raw==="object"?(raw[rarity]??raw.default):raw,normalized=String(basis||"").toLowerCase();
      if(["base","effective","unknown"].includes(normalized))return normalized;
      return conditionPriceMultiplier(ctx,rarity)===1?"effective":"unknown";
    }
    function effectiveAverageCandidates(ctx,rarity,value){
      if(value===null||value===undefined||value===""||!Number.isFinite(Number(value)))return [null];
      const n=Number(value),m=conditionPriceMultiplier(ctx,rarity),basis=averageValueBasis(ctx,rarity);
      return basis==="base"?[n*m]:basis==="effective"||m===1?[n]:[...new Set([n,n*m])];
    }
    function effectiveTotalCandidates(ctx,rarity,value){
      if(value===null||value===undefined||value===""||!Number.isFinite(Number(value)))return [null];
      const basisRaw=ctx.totalValueBasis??ctx.avgValueBasis??ctx.intelPriceBasis,basisValue=basisRaw&&typeof basisRaw==="object"?(basisRaw[rarity]??basisRaw.default):basisRaw,basis=["base","effective","unknown"].includes(String(basisValue||"").toLowerCase())?String(basisValue).toLowerCase():averageValueBasis(ctx,rarity),n=Number(value),m=conditionPriceMultiplier(ctx,rarity);
      return basis==="base"?[n*m]:basis==="effective"||m===1?[n]:[...new Set([n,n*m])];
    }
    function conditionAdjustedGroups(groups,multiplier){return (groups||[]).map(group=>[(group?.[0]||[]).map(x=>Number(x)*multiplier),Number(group?.[1])||0]);}
    function stateInferencePayload(ctx,limit=10){
      const groupSize=groups=>(groups||[]).reduce((sum,group)=>sum+Math.max(0,Math.trunc(Number(group?.[1])||0)),0),goldGroups=(ctx.goldGroups||[]).length?ctx.goldGroups:knownGroups(ctx.knownGold||[]),purpleGroups=(ctx.purpleGroups||[]).length?ctx.purpleGroups:knownGroups(ctx.knownPurple||[]),redGroups=(ctx.redGroups||[]).length?ctx.redGroups:knownGroups(ctx.knownRed||[]),minGold=Math.max(Number(ctx.minGold)||0,groupSize(goldGroups)),minPurple=Math.max(Number(ctx.minPurple)||0,groupSize(purpleGroups)),minRed=Math.max(Number(ctx.minRed)||0,groupSize(redGroups));
      const goldOnly=ctx.q===null,qForSolver=goldOnly?Math.max(20,ctx.goldCount??0,ctx.purple??0,ctx.redCount??0,minGold,minPurple,minRed):ctx.q;
      const rawGoldGrid=ctx.publicInfo?.goldGrid??null,goldGrid=rawGoldGrid!==null&&Number.isInteger(Number(rawGoldGrid))&&Number(rawGoldGrid)>=0&&Number(rawGoldGrid)<=GRID_SOLVER_MAX?Number(rawGoldGrid):null,goldHasCombinationEquation=ctx.avg!==null||ctx.goldTotal!==null||goldGrid!==null||goldGroups.length>0,purpleHasCombinationEquation=ctx.purpleAvg!==null||purpleGroups.length>0;
      // 只有“看见某件藏品”时，具体名称只增加最低件数与硬价值下限；没有均价/总价/占格方程时枚举其余全池不会淘汰任何 G/P/R，反而会指数爆炸。
      // 已知红色价格与已知紫色/金色一样是增量硬约束：它只固定已知
      // 红货必须出现在候选组合中，不会替未知红货强行补成某个数量。
      const catalog=effectiveCatalog(ctx),rules=conditionRules(ctx),goldAvgCandidates=effectiveAverageCandidates(ctx,"gold",ctx.avg),purpleAvgCandidates=effectiveAverageCandidates(ctx,"purple",ctx.purpleAvg),goldTotalCandidates=effectiveTotalCandidates(ctx,"gold",ctx.goldTotal),goldAvg=goldAvgCandidates[0],purpleAvg=purpleAvgCandidates[0],goldTotal=goldTotalCandidates[0],goldMultiplier=rules.goldMultiplier,purpleMultiplier=rules.purpleMultiplier;
      return {goldPrices:catalog.gold.map(x=>x[1]),goldGrids:catalog.gold.map(x=>areaOf(x[2])),purplePrices:catalog.purple.map(x=>x[1]),redPrices:catalog.red.map(x=>x[1]),q:qForSolver,goldAvg,goldAvgCandidates,goldTotal,goldTotalCandidates,goldGrid,goldGridInput:rawGoldGrid,goldGridIgnored:rawGoldGrid!==null&&goldGrid===null,purpleAvg,purpleAvgCandidates,fixedGold:ctx.goldCount,fixedPurple:ctx.purple,fixedRed:ctx.redCount,minGold,minPurple,minRed,mode:ctx.roundingMode||"floor",groups:goldHasCombinationEquation?conditionAdjustedGroups(goldGroups,goldMultiplier):[],purpleGroups:purpleHasCombinationEquation?conditionAdjustedGroups(purpleGroups,purpleMultiplier):[],redGroups,repeat:2,limit,goldOnly,catalogVersion:catalog.version,fieldCondition:rules.id,avgValueBasis:{gold:averageValueBasis(ctx,"gold"),purple:averageValueBasis(ctx,"purple")},inputHash:ctx.inputHash||solverInputHash(ctx),requestId:ctx.requestId??null,startedAt:ctx.startedAt||null,timeBudgetMs:Math.max(250,Number(ctx.solverTimeBudgetMs)||8000)};
    }
    function ensureInferenceCoreRuntime(){
      if(inferenceCoreRuntime)return inferenceCoreRuntime;
      const runtime={postMessage:()=>{}};
      // 历史审计直接执行与实时 Web Worker 完全相同的源码；不维护第二套近似求解器。
      new Function("self",WORKER_SOURCE)(runtime);
      inferenceCoreRuntime=runtime;return runtime;
    }
    function solveStateInferenceSync(ctx,limit=10){
      const runtime=ensureInferenceCoreRuntime(),messages=[];runtime.postMessage=message=>messages.push(message);runtime.onmessage({data:stateInferencePayload(ctx,limit)});const done=messages.findLast(x=>x?.type==="done");if(!done)throw new Error("State Inference 未返回结果");return done;
    }
    function startStateInferenceWorker(ctx,{onProgress,onDone,onError}={},limit=10){
      const budget=Math.max(250,Number(ctx?.solverTimeBudgetMs)||8000),hardTimeout=Math.max(budget+2500,12000),blob=new Blob([WORKER_SOURCE],{type:"text/javascript"}),url=URL.createObjectURL(blob),worker=new Worker(url);let finished=false,timer=null;
      const finish=(fn,payload)=>{if(finished)return;finished=true;if(timer)clearTimeout(timer);URL.revokeObjectURL(url);worker.terminate();fn?.(payload);};
      worker.onmessage=e=>{if(e.data.type==="progress")onProgress?.(e.data);if(e.data.type==="done")finish(onDone,e.data);};
      worker.onerror=error=>finish(onError,error);
      timer=setTimeout(()=>finish(onDone,{type:"done",states:[],solverStatus:"timeout",searchCompleted:false,truncated:false,requestId:ctx?.requestId??null,inputHash:ctx?.inputHash||solverInputHash(ctx),startedAt:ctx?.startedAt||null,elapsed:hardTimeout}),hardTimeout);
      worker.postMessage(stateInferencePayload(ctx,limit));worker.__v06Timer=timer;return worker;
    }
    function solveStateInferenceAsync(ctx,limit=10){
      return new Promise((resolve,reject)=>startStateInferenceWorker(ctx,{onDone:resolve,onError:reject},limit));
    }
    function runConstraintV04SelfTests(){
      const tests=[],record=(name,passed,details={})=>tests.push({name,passed:Boolean(passed),...details});
      try{
        const parsed=parseFlexibleKnown("乔望尼金雕像/202,798 + 罐装随心泥*2",GOLD_ITEMS,"金色");
        record("gold-name-price-shared-grammar",parsed.constraintCount===3&&parsed.groups.length===2&&parsed.known.length===2,{constraintCount:parsed.constraintCount,groups:parsed.groups});
      }catch(error){record("gold-name-price-shared-grammar",false,{error:String(error?.message||error)});}
      try{parseFlexibleKnown("白龙王*3",RED_ITEMS,"红色");record("repeat-two-parser-capacity",false,{error:"expected rejection"});}catch(error){record("repeat-two-parser-capacity",/repeat=2/.test(String(error?.message||error)),{message:String(error?.message||error)});}
      try{
        const parsed=parseFlexibleKnown("莹碧翡翠*2 + 莹碧翡翠/细颈莲纹瓶",RED_ITEMS,"红色"),evidence=constraintEvidenceFloor(parsed.known,parsed.groups,RED_ITEMS,2),expected=81088*2+101860;
        record("capacity-aware-overlap-floor",evidence.total===expected&&evidence.grouped===expected&&evidence.named===81088*2,{expected,evidence});
      }catch(error){record("capacity-aware-overlap-floor",false,{error:String(error?.message||error)});}
      const overlapGroups=[[[81088,101860],1],[[101860,200201],1]],base={avg:null,goldTotal:null,goldCount:0,purple:0,purpleAvg:null,minGold:0,minPurple:0,minRed:0,knownGold:[],goldGroups:[],knownPurple:[],purpleGroups:[],knownRed:[],publicInfo:{goldGrid:null},roundingMode:"floor"};
      try{const result=solveStateInferenceSync({...base,q:1,redCount:1,redGroups:overlapGroups},20);record("overlapping-or-cannot-reuse-one-instance",result.states.length===0,{states:result.states});}catch(error){record("overlapping-or-cannot-reuse-one-instance",false,{error:String(error?.message||error)});}
      try{const result=solveStateInferenceSync({...base,q:2,redCount:2,redGroups:overlapGroups},20);record("overlapping-or-accepts-two-distinct-instances",result.states.some(x=>x.g===0&&x.p===0&&x.r===2),{states:result.states.map(x=>({g:x.g,p:x.p,r:x.r}))});}catch(error){record("overlapping-or-accepts-two-distinct-instances",false,{error:String(error?.message||error)});}
      try{const result=solveStateInferenceSync({...base,q:2,redCount:2,redGroups:[[[300000],2]]},20);record("red-repeat-two-remains-valid",result.states.some(x=>x.r===2),{states:result.states.map(x=>({g:x.g,p:x.p,r:x.r}))});}catch(error){record("red-repeat-two-remains-valid",false,{error:String(error?.message||error)});}
      try{const safe=stateInferencePayload({...base,q:2,publicInfo:{goldGrid:20}},5),guarded=stateInferencePayload({...base,q:2,publicInfo:{goldGrid:GRID_SOLVER_MAX+1}},5);record("gold-grid-boundary-guard",safe.goldGrid===20&&safe.goldGridIgnored!==true&&guarded.goldGrid===null&&guarded.goldGridIgnored===true,{safe:safe.goldGrid,guarded:guarded.goldGrid,ignored:guarded.goldGridIgnored});}catch(error){record("gold-grid-boundary-guard",false,{error:String(error?.message||error)});}
      return {passed:tests.every(x=>x.passed),tested:tests.length,tests};
    }
    window.runConstraintV04SelfTests=runConstraintV04SelfTests;
    function runFieldConditionV05SelfTests(){
      const tests=[],record=(name,passed,details={})=>tests.push({name,passed:Boolean(passed),...details}),prices=items=>items.map(x=>x[1]),same=(a,b)=>JSON.stringify(a)===JSON.stringify(b),pre={catalogVersion:CATALOG_VERSION_PRE_0813,fieldCondition:"standard"},current={catalogVersion:CATALOG_VERSION_0813,fieldCondition:"standard"};
      const preEffective=effectiveCatalog(pre),purpleDouble=effectiveCatalog({...current,fieldCondition:"purple_double"}),goldDouble=effectiveCatalog({...current,fieldCondition:"gold_double"});
      record("pre0813-standard-exact-snapshot",same(preEffective.gold,PRE_0813_GOLD_ITEMS)&&same(preEffective.purple,PRE_0813_PURPLE_ITEMS)&&same(preEffective.red,PRE_0813_RED_ITEMS));
      record("purple-double-only-purple",same(prices(purpleDouble.purple),prices(PURPLE_ITEMS).map(x=>x*2))&&same(prices(purpleDouble.gold),prices(GOLD_ITEMS))&&same(prices(purpleDouble.red),prices(RED_ITEMS)));
      record("gold-double-only-gold",same(prices(goldDouble.gold),prices(GOLD_ITEMS).map(x=>x*2))&&same(prices(goldDouble.purple),prices(PURPLE_ITEMS))&&same(prices(goldDouble.red),prices(RED_ITEMS)));
      try{const purpleShown=parseFlexibleKnown("4070",PURPLE_ITEMS,"紫色",{multiplier:2,basis:"effective"}),goldShown=parseFlexibleKnown("249632",GOLD_ITEMS,"金色",{multiplier:2,basis:"effective"});record("double-visible-price-normalizes",purpleShown.known[0]?.price===2035&&goldShown.known[0]?.price===124816,{purpleBase:purpleShown.known[0]?.price,goldBase:goldShown.known[0]?.price});}catch(error){record("double-visible-price-normalizes",false,{error:String(error?.message||error)});}
      const unknownCtx={...current,fieldCondition:"unknown"},standardRecord={...current,fieldCondition:"standard",actualTotal:1};
      record("unknown-isolated-from-standard",conditionRules(unknownCtx).id==="unknown"&&conditionRules(unknownCtx).goldMultiplier===1&&!historyCompatible(unknownCtx,standardRecord,"wholeValue"));
      const gems=gemTargetPool(current),gemPrices=gems.map(x=>x.price);
      record("gem-pool-evidence-bounds",gems.length===16&&Math.min(...gemPrices)===99&&Math.max(...gemPrices)===1314520,{count:gems.length,min:Math.min(...gemPrices),max:Math.max(...gemPrices)});
      const sparkle=fieldConditionAnalysis({...current,fieldCondition:"shining_heart",oneByOneCount:2});
      record("sparkle-no-fake-probability",sparkle.sparkleEvidence?.recommendationAllowed===false&&sparkle.sparkleEvidence?.probabilityKnown===false&&sparkle.sparkleEvidence?.lower===198&&sparkle.sparkleEvidence?.upper===2629040);
      const nestedSparkle=fieldConditionAnalysis({...current,fieldCondition:"sparkle",sparkle:{transformedOneByOneCount:2,verifiedGemItems:"绿林*2"}}).sparkleEvidence;
      record("sparkle-nested-schema-evidence",nestedSparkle?.knownCount===2&&nestedSparkle?.knownTotal===198&&nestedSparkle?.lower===198&&nestedSparkle?.upper===198,{knownCount:nestedSparkle?.knownCount,knownTotal:nestedSparkle?.knownTotal});
      const liveSparkle=fieldConditionAnalysis({...current,fieldCondition:"sparkle",sparkle:{transformedOneByOneCount:2,verifiedGemItems:"泪滴"}}).sparkleEvidence;
      record("sparkle-live-unquoted-name",liveSparkle?.knownCount===1&&liveSparkle?.knownTotal===50000&&liveSparkle?.lower===50099&&liveSparkle?.upper===1364520,{knownCount:liveSparkle?.knownCount,knownTotal:liveSparkle?.knownTotal,lower:liveSparkle?.lower,upper:liveSparkle?.upper});
      try{const sparkleCtx={...current,playedAt:"2099-01-01T00:00:00",fieldCondition:"shining_heart",oneByOneCount:2,venue:"未知场地",box:"未知箱型",q:1,avg:null,goldTotal:null,goldCount:0,purple:0,purpleAvg:null,redCount:1,cost:0,minGold:0,minPurple:0,minRed:1,knownGold:[],goldGroups:[],knownPurple:[],purpleGroups:[],knownRed:[],redGroups:[],publicInfo:{},roundingMode:"floor"},decision=workingDecision(sparkleCtx,[{g:0,p:0,r:1,rMin:1,rMax:1,gold:{unconstrained:true,matches:[]},purple:{unconstrained:true,matches:[]}}]),html=decisionMetrics(decision);record("sparkle-decision-suppressed",decision.recommendationSuppressed===true&&decision.recommendedMaxBid===null&&decision.probabilityProfile===null&&decision.center===null&&decision.breakdown===null&&!html.includes("liveBidInput")&&!html.includes("Probability Shadow"),{recommendationSuppressed:decision.recommendationSuppressed,recommendedMaxBid:decision.recommendedMaxBid});}catch(error){record("sparkle-decision-suppressed",false,{error:String(error?.message||error)});}
      try{const parsed=parseFlexibleKnown("霞红钻",PURPLE_ITEMS,"紫色");record("same-price-name-preserved",parsed.known.length===1&&parsed.known[0].name==="霞红钻",{known:parsed.known});}catch(error){record("same-price-name-preserved",false,{error:String(error?.message||error)});}
      record("0813-catalog-counts",GOLD_ITEMS.length===50&&RED_ITEMS.length===30&&WHITE_ITEMS.length===20,{gold:GOLD_ITEMS.length,red:RED_ITEMS.length,white:WHITE_ITEMS.length});
      const unknownAvgPayload=stateInferencePayload({...current,fieldCondition:"gold_double",avgValueBasis:"unknown",q:2,avg:60040,goldTotal:60040,goldCount:1,purple:1,redCount:0,minGold:1,minPurple:1,minRed:0,knownGold:[],goldGroups:[],knownPurple:[],purpleGroups:[],knownRed:[],redGroups:[],publicInfo:{goldGrid:null},roundingMode:"floor"},5);
      record("double-average-and-total-dual-basis",same(unknownAvgPayload.goldAvgCandidates,[60040,120080])&&same(unknownAvgPayload.goldTotalCandidates,[60040,120080]),{goldAvgCandidates:unknownAvgPayload.goldAvgCandidates,goldTotalCandidates:unknownAvgPayload.goldTotalCandidates});
      try{const result=solveStateInferenceSync({...current,fieldCondition:"gold_double",avgValueBasis:"base",q:1,avg:60040,goldTotal:null,goldCount:1,purple:0,redCount:0,minGold:1,minPurple:0,minRed:0,knownGold:[],goldGroups:[],knownPurple:[],purpleGroups:[],knownRed:[],redGroups:[],publicInfo:{goldGrid:null},roundingMode:"floor"},5),combo=result.states?.[0]?.gold?.matches?.[0]||[];record("double-worker-uses-effective-pool",result.states?.some(x=>x.g===1&&x.p===0&&x.r===0)&&combo.includes(120080),{combo,states:result.states?.length});}catch(error){record("double-worker-uses-effective-pool",false,{error:String(error?.message||error)});}
      return {passed:tests.every(x=>x.passed),tested:tests.length,tests};
    }
    window.runFieldConditionV05SelfTests=runFieldConditionV05SelfTests;

    /* v0.5.1 reliability gates. These tests deliberately exercise the same
       synchronous Worker source used by the browser Worker; they do not alter
       the formal value model or any legacy State weights. */
    function runV06ReliabilitySelfTests(){
      const tests=[],record=(name,passed,details={})=>tests.push({name,passed:Boolean(passed),...details});
      try{
        const knownGoldGroup=[[[51077],1]],knownPurpleGroups=[[[18075],1],[[8128],1]],ctx={
          playedAt:"2026-08-13T15:53:00+08:00",catalogVersion:CATALOG_VERSION_0813,fieldCondition:"standard",avgValueBasis:"base",roundingMode:"floor",
          q:9,avg:33538,goldTotal:null,goldCount:null,purple:5,purpleAvg:null,redCount:null,minGold:1,minPurple:0,minRed:0,
          knownGold:[{name:"已知金",price:51077}],knownGoldRaw:"51077",goldGroups:knownGoldGroup,knownPurple:[{name:"已知紫1",price:18075},{name:"已知紫2",price:8128}],knownPurpleRaw:"18075+8128",purpleGroups:knownPurpleGroups,knownRed:[],knownRedRaw:"",redGroups:[],publicInfo:{},solverTimeBudgetMs:8000
        },result=solveStateInferenceSync(ctx,50),keys=new Set((result.states||[]).map(x=>`${x.g}/${x.p}/${x.r}`));
        record("15:53-regression-not-no-match",solverStatusFromResult(result)==="valid"&&result.states?.length>0,{solverStatus:result.solverStatus,states:result.states?.length});
        record("15:53-regression-required-states",keys.has("3/5/1")&&keys.has("4/5/0"),{states:[...keys]});
      }catch(error){record("15:53-regression-not-no-match",false,{error:String(error?.message||error)});record("15:53-regression-required-states",false,{error:String(error?.message||error)});}
      try{
        const base={catalogVersion:CATALOG_VERSION_0813,fieldCondition:"standard",roundingMode:"floor",q:2,avg:null,goldTotal:null,goldCount:0,purple:0,redCount:2,minGold:0,minPurple:0,minRed:0,knownGold:[],knownPurple:[],knownRed:[{price:300000},{price:300000}],goldGroups:[],purpleGroups:[],redGroups:[[[300000],2]],publicInfo:{}};
        const result=solveStateInferenceSync(base,20);record("red-repeat-two-regression",solverStatusFromResult(result)==="valid"&&result.states.some(x=>x.r===2),{solverStatus:result.solverStatus,states:result.states?.map(x=>[x.g,x.p,x.r])});
      }catch(error){record("red-repeat-two-regression",false,{error:String(error?.message||error)});}
      try{
        const a={q:9,avg:100,cost:5000,targetProfit:30000,knownGoldRaw:"51077",goldGroups:[[[51077],1]],publicInfo:{}},b={...a,avg:101},c={...a,cost:55000},ha=solverInputHash(a),hb=solverInputHash(b),hc=solverInputHash(c);record("input-hash-changes-with-input",ha!==hb&&ha!==hc,{ha,hb,hc});
      }catch(error){record("input-hash-changes-with-input",false,{error:String(error?.message||error)});}
      try{
        const latest={requestId:"B",inputHash:"hash-B"},responses=[{requestId:"A",inputHash:"hash-A",delay:3000},{requestId:"B",inputHash:"hash-B",delay:100}].sort((x,y)=>x.delay-y.delay);let applied=null;for(const response of responses)if(response.requestId===latest.requestId&&response.inputHash===latest.inputHash)applied=response.requestId;record("async-race-keeps-latest",applied==="B",{applied,latest});
      }catch(error){record("async-race-keeps-latest",false,{error:String(error?.message||error)});}
      try{record("timeout-is-not-no-match",solverStatusFromResult({states:[],searchCompleted:false})==="timeout",{});record("incomplete-is-not-no-match",solverStatusFromResult({states:[{g:1,p:1,r:0}],searchCompleted:false})==="incomplete",{});}catch(error){record("timeout-and-incomplete-classification",false,{error:String(error?.message||error)});}
      try{const analysis={solverStatus:"no-match",workingDecision:{center:999},frozenPrediction:undefined},stale={solverStatus:"stale",workingDecision:{center:999},frozenPrediction:undefined};record("no-match-freezes-null-prediction",predictionSnapshot(analysis)===null,{});record("stale-freezes-null-prediction",predictionSnapshot(stale)===null,{});}catch(error){record("prediction-freeze-null-guards",false,{error:String(error?.message||error)});}
      try{const diagnosticCtx={catalogVersion:CATALOG_VERSION_0813,fieldCondition:"standard",avgValueBasis:"base",roundingMode:"floor",q:1,avg:9938.5,goldTotal:null,goldCount:1,purple:0,purpleAvg:null,redCount:0,minGold:1,minPurple:0,minRed:0,knownGold:[],knownPurple:[],knownRed:[],goldGroups:[],purpleGroups:[],redGroups:[],publicInfo:{},solverTimeBudgetMs:300},strict={solverStatus:"no-match",states:[],searchCompleted:true},report=diagnosticSolverV06(diagnosticCtx,strict);record("diagnostic-nearest-rounding-explains-no-match",report?.diagnosticOnly===true&&report.resolution?.kind==="nearest-rounding"&&report.resolution.candidateCount>0,{strict:strict.solverStatus,resolution:report?.resolution,attempts:report?.attempts?.map(x=>[x.kind,x.status,x.candidateCount])});record("diagnostic-never-enters-training",predictionSnapshot({diagnosticOnly:true,solverStatus:"valid",workingDecision:{center:100}})===null&&!solverStatusEligibleForTraining("diagnostic"),{});}catch(error){record("diagnostic-solver-regression",false,{error:String(error?.message||error)});}
      return {passed:tests.every(x=>x.passed),tested:tests.length,tests};
    }
    window.runV06ReliabilitySelfTests=runV06ReliabilitySelfTests;
    async function runV06AsyncRaceSelfTest({slowMs=3000,fastMs=100}={}){
      const latest={requestId:"B",inputHash:"hash-B"};let applied=[];
      const deliver=(response,delay)=>new Promise(resolve=>setTimeout(()=>{if(response.requestId===latest.requestId&&response.inputHash===latest.inputHash)applied.push(response.requestId);resolve();},delay));
      await Promise.all([deliver({requestId:"A",inputHash:"hash-A",solverStatus:"valid"},slowMs),deliver({requestId:"B",inputHash:"hash-B",solverStatus:"valid"},fastMs)]);
      return {passed:applied.length===1&&applied[0]==="B",applied,latest,delays:{A:slowMs,B:fastMs}};
    }
    window.runV06AsyncRaceSelfTest=runV06AsyncRaceSelfTest;
    function runV052BacktestSelfTests(){
      const tests=[],record=(name,passed,details={})=>tests.push({name,passed:Boolean(passed),...details});
      try{const miss=staticCounterfactual({actualTotal:600000,clearingPrice:400000,costs:{total:50000}},300000);record("clearing-price-gate-missed-opportunity",miss.status==="known"&&!miss.acquired&&miss.missedOpportunity&&miss.profit===-50000,{miss});}catch(error){record("clearing-price-gate-missed-opportunity",false,{error:String(error?.message||error)});}
      try{const bad=staticCounterfactual({actualTotal:403298,clearingPrice:400000,costs:{total:55000}},450000);record("clearing-price-gate-bad-buy",bad.status==="known"&&bad.acquired&&bad.badBuy&&bad.profit===-51702,{bad});}catch(error){record("clearing-price-gate-bad-buy",false,{error:String(error?.message||error)});}
      try{const unknown=staticCounterfactual({actualTotal:403298,costs:{total:55000}},450000);record("missing-clearing-is-unknown",unknown.status==="unknown"&&unknown.profit===null,{unknown});}catch(error){record("missing-clearing-is-unknown",false,{error:String(error?.message||error)});}
      return {passed:tests.every(x=>x.passed),tested:tests.length,tests};
    }
    window.runV052BacktestSelfTests=runV052BacktestSelfTests;
    function runV06ShadowSelfTests(){
      const tests=[],record=(name,passed,details={})=>tests.push({name,passed:Boolean(passed),...details}),original=state.records;
      try{
        state.records=[
          {id:"__shadow-a",playedAt:"2099-01-01T00:00:00",venue:"V",box:"B",fieldCondition:"standard",q:9,actualTotal:100,solverStatus:"valid",settlement:{status:"verified",realizedState:{gold:3,purple:5,red:1,complete:true}}},
          {id:"__shadow-b",playedAt:"2099-01-02T00:00:00",venue:"V",box:"B",fieldCondition:"standard",q:9,actualTotal:101,solverStatus:"valid",settlement:{status:"verified",realizedState:{gold:4,purple:5,red:0,complete:true}}}
        ];
        const prior=empiricalStatePriorV06({playedAt:"2099-01-03T00:00:00",venue:"V",box:"B",fieldCondition:"standard",q:9},[{g:3,p:5,r:1,weight:1},{g:4,p:5,r:0,weight:1}]);
        record("empirical-state-prior-sidecar",prior.status==="sidecar-only"&&prior.localN===2&&prior.candidateWeights.every(x=>Number.isFinite(x.empiricalWeight))&&prior.levels.some(x=>x.level==="q-bucket"),{status:prior.status,localN:prior.localN,fallbackLevel:prior.fallbackLevel,qBucket:prior.qBucket});
        const evalResult=statePriorEvaluationV06([{id:"__state-eval",round:1,realizedState:{g:3,p:5,r:1},empiricalStatePrior:{candidateWeights:[{g:3,p:5,r:1,empiricalWeight:.7},{g:4,p:5,r:0,empiricalWeight:.3}]}}]);
        record("state-prior-oos-metrics",evalResult.status==="oos"&&evalResult.candidateRecall===1&&evalResult.top1Accuracy===1&&evalResult.logLoss>=0&&evalResult.brierScore>=0,{n:evalResult.n,recall:evalResult.candidateRecall,brier:evalResult.brierScore,logLoss:evalResult.logLoss,rank:evalResult.meanRank});
      }catch(error){record("empirical-state-prior-sidecar",false,{error:String(error?.message||error)});}
      try{
        state.records=[0,1,2,3,4,5].map((i)=>({id:`__shadow-cal-${i}`,playedAt:`2099-02-0${i+1}T00:00:00`,actualTotal:110+i,solverStatus:"valid",prediction:{estimate:100,probabilityProfile:{shadowWhole:{p20:80,p50:100,p80:120}}}}));
        const side=shadowCalibrationSidecarV06({playedAt:"2099-03-01T00:00:00"},{probabilityProfile:{shadowWhole:{p20:80,p50:100,p80:120}}});record("shadow-calibration-widens-oos-range",side?.status==="calibrated-sidecar"&&side.calibrated.p20<=side.raw.p20&&side.calibrated.p80>=side.raw.p80&&side.calibrated.p50===100&&side.rawCoverage===1&&side.calibratedCoverage===1,{status:side?.status,rawCoverage:side?.rawCoverage,calibratedCoverage:side?.calibratedCoverage,calibrated:side?.calibrated});
        const shadowEval=shadowOosEvaluationV06([{id:"__shadow-eval",actual:110,shadowRaw:{p20:80,p80:120},shadowCalibrated:side}]);record("shadow-real-interval-coverage",shadowEval.status==="oos"&&shadowEval.rawCoverage===1&&shadowEval.calibratedCoverage===1,{shadowEval});
      }catch(error){record("shadow-calibration-widens-oos-range",false,{error:String(error?.message||error)});}
      state.records=original;return {passed:tests.every(x=>x.passed),tested:tests.length,tests};
    }
    window.runV06ShadowSelfTests=runV06ShadowSelfTests;
    function runV06MarketSelfTests(){
      const tests=[],record=(name,passed,details={})=>tests.push({name,passed:Boolean(passed),...details}),original=state.records;
      try{
        state.records=[0,1,2,3,4,5,6,7,8,9].map((i)=>({id:`__market-${i}`,playedAt:`2099-04-${String(i+1).padStart(2,"0")}T00:00:00`,venue:"V",box:i===9?"Other":"B",fieldCondition:"standard",q:9,clearingPrice:80000+i*1000,prediction:{estimate:100000,solverStatus:"valid"},actualTotal:0}));
        const result=marketPredictionV06({playedAt:"2099-05-01T00:00:00",venue:"V",box:"B",fieldCondition:"standard",q:9},100000);record("market-hierarchical-shrinkage",result.status==="shrunk"&&result.localN===9&&result.parentN>=9&&result.fallbackLevel==="exact-condition-box-q"&&result.qBucket==="Q1-9"&&result.p50>0,{status:result.status,localN:result.localN,parentN:result.parentN,weight:result.shrinkageWeight,fallbackLevel:result.fallbackLevel,qBucket:result.qBucket,p50:result.p50});
      }catch(error){record("market-hierarchical-shrinkage",false,{error:String(error?.message||error)});}
      try{state.records=[];const empty=marketPredictionV06({playedAt:"2099-05-01T00:00:00",venue:"none",box:"none",fieldCondition:"unknown",q:9},100000);record("market-no-sample-explicit",empty.status==="no-sample"&&empty.p50===null&&empty.fallbackLevel==="global",{empty});}catch(error){record("market-no-sample-explicit",false,{error:String(error?.message||error)});}
      try{const oos=marketOosEvaluationV06([{id:"__market-oos-a",q:9,estimate:100000,clearingPrice:90000,marketPrediction:{p20:70000,p50:100000,p80:120000,marketRatio:{p50:1},fallbackLevel:"q-bucket"}},{id:"__market-oos-b",q:16,estimate:100000,clearingPrice:150000,marketPrediction:{p20:80000,p50:120000,p80:140000,marketRatio:{p50:1.2},fallbackLevel:"global",lowSample:true}}]);record("market-strict-oos-metrics",oos.status==="oos"&&oos.n===2&&oos.p20p80Coverage===0.5&&oos.p50Mae===20000&&oos.byQ.length===2,{n:oos.n,coverage:oos.p20p80Coverage,p50Mae:oos.p50Mae,byQ:oos.byQ});}catch(error){record("market-strict-oos-metrics",false,{error:String(error?.message||error)});}
      state.records=original;return {passed:tests.every(x=>x.passed),tested:tests.length,tests};
    }
    window.runV06MarketSelfTests=runV06MarketSelfTests;
    function runV06AnalyticsSelfTests(){
      const tests=[],record=(name,passed,details={})=>tests.push({name,passed:Boolean(passed),...details});
      try{
        const info=informationValueStatsV06([{id:"__info",rounds:[{round:1,prediction:{probabilityProfile:{stateCandidates:[1,2,3,4],shadowWhole:{p20:10,p50:30,p80:50}},entryDecision:{status:"worth-entering"}},intelEvents:[]},{round:2,prediction:{probabilityProfile:{stateCandidates:[1,2],shadowWhole:{p20:20,p50:30,p80:40}},entryDecision:{status:"thin-entry"}},intelEvents:[{type:"public-intel",cost:0,free:true}]}]}]);
        record("information-value-round-delta",info.status==="oos"&&info.n===1&&info.stateReduction===2&&info.shadowWidthReduction===20&&info.decisionChangedRate===1,{info});
      }catch(error){record("information-value-round-delta",false,{error:String(error?.message||error)});}
      try{
        const finance=financeStatsV06([{id:"__fin-a",playedAt:"2026-01-01T00:00:00",actualTotal:150000,acquired:true,purchaseSpend:100000,costs:{total:10000}},{id:"__fin-b",playedAt:"2026-01-02T00:00:00",actualTotal:120000,acquired:true,purchaseSpend:130000,costs:{total:10000}}]);
        record("roi-and-drawdown",finance.totalNet===20000&&finance.investedBase===250000&&finance.maxDrawdown===20000&&finance.roi===.08,{totalNet:finance.totalNet,investedBase:finance.investedBase,maxDrawdown:finance.maxDrawdown,roi:finance.roi});
      }catch(error){record("roi-and-drawdown",false,{error:String(error?.message||error)});}
      return {passed:tests.every(x=>x.passed),tested:tests.length,tests};
    }
    window.runV06AnalyticsSelfTests=runV06AnalyticsSelfTests;

    const _calcBtn=document.getElementById("calculateBtn"); if(_calcBtn)_calcBtn.addEventListener("click",runCalculation);
    ["calcEntryCost","calcInfoCost","calcOtherCost"].forEach(id=>document.getElementById(id)?.addEventListener("input",()=>syncCostInputs("calc")));
    ["recordEntryCost","recordInfoCost","recordOtherCost"].forEach(id=>document.getElementById(id)?.addEventListener("input",()=>syncCostInputs("record")));
    syncCostInputs("calc");syncCostInputs("record");
    function renderCalcRedState(){const value=num("calcRedCount"),minimum=num("calcMinRedQuick"),el=document.getElementById("calcRedState");if(!el)return;el.textContent=value===0?"已确认无红":minimum!==null&&minimum>0?`至少 ${minimum} 件红`:"未知红数";el.classList.toggle("locked",value===0);}
    const _rz=document.getElementById("calcRedZeroBtn"); if(_rz)_rz.addEventListener("click",()=>{ setVal("calcRedCount",0); setVal("calcMinRed",0); setVal("calcMinRedQuick",0); renderCalcRedState(); toast("已明确确认无红；否则请保持未知"); });
    const _rc=document.getElementById("calcRedClearBtn"); if(_rc)_rc.addEventListener("click",()=>{ setVal("calcRedCount",""); setVal("calcMinRed",""); setVal("calcMinRedQuick",""); renderCalcRedState(); toast("红数已恢复为未知"); });
    const _rm=document.getElementById("calcMinRedQuick"); if(_rm)_rm.addEventListener("input",()=>{const n=num("calcMinRedQuick");setVal("calcMinRed",n===null?"":n);if(n!==0&&num("calcRedCount")===0)setVal("calcRedCount","");renderCalcRedState();});
    document.getElementById("resetCalcBtn").addEventListener("click",()=>resetCalculatorDraft());
    const shownIntelFields=new Set();
    function refreshIntelFields(){
      document.querySelectorAll("#intelFieldGrid .intel-field").forEach(wrapper=>{
        const key=wrapper.dataset.intelField,input=wrapper.querySelector("input,textarea,select"),hasValue=input&&String(input.value??"").trim()!=="";
        wrapper.classList.toggle("visible",shownIntelFields.has(key)||hasValue);
      });
      document.querySelectorAll("#intelFieldChips [data-intel-target]").forEach(chip=>{const key=chip.dataset.intelTarget,wrapper=document.querySelector(`#intelFieldGrid [data-intel-field="${key}"]`),input=wrapper?.querySelector("input,textarea,select"),hasValue=input&&String(input.value??"").trim()!=="";chip.classList.toggle("active",shownIntelFields.has(key)||hasValue);});
    }
    document.querySelectorAll("#intelFieldChips [data-intel-target]").forEach(chip=>chip.addEventListener("click",()=>{shownIntelFields.add(chip.dataset.intelTarget);refreshIntelFields();document.querySelector(`#intelFieldGrid [data-intel-field="${chip.dataset.intelTarget}"] input, #intelFieldGrid [data-intel-field="${chip.dataset.intelTarget}"] textarea`)?.focus();}));
    document.querySelectorAll("#intelFieldGrid input,#intelFieldGrid textarea,#intelFieldGrid select").forEach(input=>input.addEventListener("input",refreshIntelFields));
    function showCalcSection(name){
      if(!name) return;
      const targetId="calcSection"+name.charAt(0).toUpperCase()+name.slice(1);
      document.querySelectorAll(".calc-tab").forEach(button=>button.classList.toggle("active",button.dataset.calcSection===name));
      document.querySelectorAll(".calc-section").forEach(section=>{
        const on=section.id===targetId;
        section.classList.toggle("active", on);
        // inline fallback if CSS cache stale
        section.style.display = on ? "block" : "none";
      });
      if(name==="public")refreshIntelFields();
    }
    document.querySelectorAll(".calc-tab").forEach(button=>button.addEventListener("click",()=>showCalcSection(button.dataset.calcSection)));
    /* TAB DELEGATION */
    document.addEventListener("click",(ev)=>{
      const tab=ev.target.closest && ev.target.closest(".calc-tab");
      if(tab && tab.dataset.calcSection) showCalcSection(tab.dataset.calcSection);
    });
    function markCurrentAnalysisStale(){
      if(activeWorker)cancelActiveInference();
      if(!currentAnalysis||["no-match","timeout","stale"].includes(currentAnalysis.solverStatus))return;
      currentAnalysis.solverStatus="stale";currentAnalysis.frozenPrediction=null;currentAnalysis.staleAt=new Date().toISOString();
      const panel=document.getElementById("resultPanel");if(!panel)return;panel.classList.add("solver-stale");let notice=panel.querySelector(".solver-stale-notice");if(!notice){notice=document.createElement("div");notice.className="solver-stale-notice callout";notice.innerHTML='<span class="dot"></span><div><strong>当前结果已过期：</strong>输入发生变化，请重新推演；保存时不会把旧结果冒充最新预测。</div>';panel.prepend(notice);}
    }
    document.querySelectorAll("#calcSectionCore input,#calcSectionCore textarea,#calcSectionCore select,#calcSectionSetup input,#calcSectionSetup textarea,#calcSectionSetup select,#calcSectionPublic input,#calcSectionPublic textarea,#calcSectionPublic select").forEach(el=>{el.addEventListener("input",markCurrentAnalysisStale);el.addEventListener("change",markCurrentAnalysisStale);});
    function setCalcRound(round,mode="next"){
      const value=Math.max(1,Math.min(5,Number(round)||1)),display=document.getElementById("calcRoundDisplay"),button=document.getElementById("calculateBtn");
      setVal("calcRound",value);
      if(display)display.innerHTML=`<strong>R${value}</strong><span>${mode==="retry"?"本回合再次推演":value===1?"首次推演":"只补充新增情报"}</span>`;
      if(button)button.textContent=mode==="retry"?`再次推演 R${value}`:value===1?"开始推演 R1":`推演下一回合 R${value}`;const evidenceBtn=document.getElementById("roundEvidenceBtn");if(evidenceBtn)evidenceBtn.textContent=`添加 R${value} 截图`;renderRoundEvidence();syncFieldConditionUi();
    }
    function discardUnsavedEvidenceBlobs(preserveKeys=new Set()){
      const keys=new Set([...currentGameEvidence,...currentRoundEvidence].map(x=>x?.storageKey).filter(key=>key&&!preserveKeys.has(key)));
      if(keys.size)void Promise.all([...keys].map(deleteScreenshotBlob));
    }
    function resetCalculatorDraft(context=null,options={}){
      const keep=context||{character:val("calcCharacter"),venue:val("calcVenue"),box:val("calcBox"),toolGroup:val("calcToolGroup")||"group1"};
      discardUnsavedEvidenceBlobs(options.preserveKeys||new Set());
      cancelActiveInference();document.getElementById("calculateBtn").disabled=false;
      ["calcQ","calcGoldAvg","calcGoldCount","calcPurple","calcRedCount","calcPurpleAvg","calcGoldTotal","calcOr","calcMinPurple","calcMinGold","calcMinRed","calcMinRedQuick","calcKnownPurple","calcKnownRed","calcTotalItems","calcTotalGrid","calcGoldGrid","calcPurpleGrid","calcBlueGrid","calcBlueCount","calcBlueAvg","calcGreenGrid","calcGreenCount","calcGreenAvg","calcWhiteGrid","calcWhiteCount","calcWhiteAvg","calcSystemEstimate","calcSingleAvg","calcNineAvg","calcPublicNote","calcPrivateBidCap","calcBidActionCount","calcTargetProfit","calcTransformedOneByOneCount","calcVerifiedGemItems"].forEach(id=>setVal(id,""));
      setVal("calcEntryCost",5000);setVal("calcInfoCost",50000);setVal("calcOtherCost",0);setVal("calcTargetProfit",30000);syncCostInputs("calc");setVal("calcToolGroup",keep.toolGroup||"group1");
      setVal("calcCharacter",keep.character&&keep.character!=="未知助手"?keep.character:"达芙蒂尔");setVal("calcVenue",keep.venue||"中级场 · 珊瑚场");fillBoxOptions("calcVenue","calcBox",keep.box||"未知箱型");setVal("calcFieldCondition","unknown");setVal("calcAvgValueBasis","unknown");const calcGemComplete=document.getElementById("calcGemInventoryComplete");if(calcGemComplete)calcGemComplete.checked=false;setCalcRound(1);setVal("calcPlayedAt",nowLocalInput());roundingMode="floor";document.querySelectorAll("#roundingMode button").forEach(x=>x.classList.toggle("active",x.dataset.value==="floor"));currentRoundSnapshots=[];currentRoundEvidence=[];currentAnalysis=null;window.__liveBidValue=null;currentGameEvidence=[];shownIntelFields.clear();["resultHighestPersonalBid","resultFinalBid","resultActualTotal","resultPurchaseSpend","resultGoldCount","resultPurpleCount","resultRedCount","resultFinalRed","resultNote","resultWinner","resultAcquired","resultReason","resultWelfareBase","resultWelfareExpected","resultWelfareReceived","resultTransformedOneByOneCount","resultVerifiedGemItems"].forEach(id=>{setVal(id,"");const el=document.getElementById(id);if(el)delete el.dataset.userEdited;});setVal("resultWelfareRate",.30);setVal("resultTruthSource","manual-settlement");setVal("resultTruthConfidence","high");for(const id of ["resultRedInventoryComplete","resultGemInventoryComplete"]){const el=document.getElementById(id);if(el)el.checked=false;}clearSettlementOcrMarks();const settlement=document.getElementById("settlementCapture");if(settlement)settlement.open=false;if(typeof syncSettlementDockState==="function")syncSettlementDockState(false);renderCurrentGameEvidence();renderRoundEvidence();renderCalcRedState();refreshIntelFields();syncFieldConditionUi();showCalcSection("core");renderEmptyResult();
    }

    function runCalculation() {
      let q=num("calcQ"), avg=num("calcGoldAvg"), goldCount=num("calcGoldCount"), purple=num("calcPurple"), redCount=num("calcRedCount"), purpleAvg=num("calcPurpleAvg"), goldTotal=num("calcGoldTotal"),cost=num("calcCost")??55000,targetProfit=num("calcTargetProfit")??30000,totalGrid=num("calcTotalGrid"),goldGrid=num("calcGoldGrid"),purpleGrid=num("calcPurpleGrid"),blueGrid=num("calcBlueGrid"),blueCount=num("calcBlueCount"),blueAvg=num("calcBlueAvg"),greenGrid=num("calcGreenGrid"),greenCount=num("calcGreenCount"),greenAvg=num("calcGreenAvg"),whiteGrid=num("calcWhiteGrid"),whiteCount=num("calcWhiteCount"),whiteAvg=num("calcWhiteAvg");
      if(q!==null&&(!Number.isInteger(q)||q<1||q>80)){toast("Q 必须是 1～80 的整数；不知道可以留空",true);return;}
      for(const [value,label] of [[goldCount,"金色"],[purple,"紫色"],[redCount,"红色"]])if(value!==null&&(!Number.isInteger(value)||value<0||value>80)){toast(`${label}数量必须是 0～80 的整数`,true);return;}
      if(q!==null&&[goldCount,purple,redCount].filter(x=>x!==null).reduce((a,b)=>a+b,0)>q){toast("已知精确数量之和不能超过 Q",true);return;}
      if(avg!==null&&(!Number.isInteger(avg)||avg<=0)){toast("金色均价必须是正整数",true);return;}
      if(purpleAvg!==null&&(!Number.isInteger(purpleAvg)||purpleAvg<=0)){toast("紫色均价必须是正整数",true);return;}
      if(goldTotal!==null&&(!Number.isInteger(goldTotal)||goldTotal<=0)){toast("金色总价必须是正整数",true);return;}
      if(!Number.isInteger(cost)||cost<0){toast("本局分摊成本必须是非负整数",true);return;}if(!Number.isInteger(targetProfit)||targetProfit<0){toast("目标利润必须是非负整数",true);return;}
      if(totalGrid!==null&&(!Number.isInteger(totalGrid)||totalGrid<1||totalGrid>TOTAL_GRID_INPUT_MAX)){toast(`总格数必须是 1～${TOTAL_GRID_INPUT_MAX} 的整数；无法确认时请留空`,true);return;}
      if(goldGrid!==null&&(!Number.isInteger(goldGrid)||goldGrid<0||goldGrid>GRID_SOLVER_MAX)){toast(`金色占格目前支持 0～${GRID_SOLVER_MAX} 格；超过范围请先核对截图或暂时留空，避免组合求解过慢`,true);return;}
      if(canonicalFieldConditionId(val("calcFieldCondition"))==="sparkle"){const draftSparkle={transformedOneByOneCount:integerOrNull(num("calcTransformedOneByOneCount")),verifiedGemItems:val("calcVerifiedGemItems"),complete:document.getElementById("calcGemInventoryComplete")?.checked===true},audit=sparkleTruthAudit(draftSparkle,{playedAt:val("calcPlayedAt")});if(!audit.ok){toast(audit.error,true);return;}}
      for(const [value,label] of [[blueAvg,"蓝色"],[greenAvg,"绿色"],[whiteAvg,"白色"]])if(value!==null&&(!Number.isInteger(value)||value<=0)){toast(`${label}均价必须是正整数`,true);return;}
      for(const [value,label] of [[goldGrid,"金色占格"],[purpleGrid,"紫色占格"],[blueGrid,"蓝色占格"],[greenGrid,"绿色占格"],[whiteGrid,"白色占格"],[blueCount,"蓝色数量"],[greenCount,"绿色数量"],[whiteCount,"白色数量"]])if(value!==null&&(!Number.isInteger(value)||value<0)){toast(`${label}必须是非负整数`,true);return;}
      let knownPurple,knownGold,knownRed,purpleGroups,redGroups,groups;try{const priceFieldCondition=canonicalFieldConditionId(val("calcFieldCondition")),priceBasis=normalizeAvgValueBasis(val("calcAvgValueBasis")),purplePriceOptions={multiplier:conditionPriceMultiplier({fieldCondition:priceFieldCondition},"purple"),basis:priceBasis},goldPriceOptions={multiplier:conditionPriceMultiplier({fieldCondition:priceFieldCondition},"gold"),basis:priceBasis},purpleParsed=parseFlexibleKnown(val("calcKnownPurple"),PURPLE_ITEMS,"紫色",purplePriceOptions),redParsed=parseFlexibleKnown(val("calcKnownRed"),RED_ITEMS,"红色",{multiplier:1,basis:"base"});knownPurple=purpleParsed.known;purpleGroups=purpleParsed.groups;knownRed=redParsed.known;redGroups=redParsed.groups;groups=parseOr(val("calcOr"),goldPriceOptions);knownGold=groups.flatMap(([prices,require])=>prices.length===1?Array.from({length:require},()=>{const item=GOLD_ITEMS.find(x=>x[1]===prices[0]);return {name:item[0],price:item[1],size:item[2]};}):[]);}catch(error){toast(error.message,true);return;}
      const quickMinRed=num("calcMinRedQuick");if(quickMinRed!==null)setVal("calcMinRed",quickMinRed);
      const rawMins={purple:num("calcMinPurple")??0,gold:num("calcMinGold")??0,red:Math.max(num("calcMinRed")??0,quickMinRed??0)};
      if(Object.values(rawMins).some(x=>!Number.isInteger(x)||x<0||x>80)){toast("紫/金/红最低数量必须是 0～80 的整数",true);return;}
      let minPurple=Math.max(rawMins.purple,knownPurple.length,purpleGroups.reduce((s,x)=>s+x[1],0)),minGold=Math.max(rawMins.gold,knownGold.length,groups.reduce((s,x)=>s+x[1],0),(avg!==null||goldTotal!==null)?1:0),minRed=Math.max(rawMins.red,knownRed.length,redGroups.reduce((s,x)=>s+x[1],0));
      if(q!==null&&minPurple+minGold+minRed>q){toast("三个最低数量之和不能超过 Q",true);return;}
      if(goldCount!==null&&goldCount<minGold){toast("金色精确数量不能小于最低数量/已知件数",true);return;}
      if(purple!==null&&purple<minPurple){toast("紫色精确数量不能小于最低数量/已知件数",true);return;}
      if(redCount!==null&&redCount<minRed){toast("红色精确数量不能小于最低数量/已知件数",true);return;}
      const playedAt=val("calcPlayedAt")||nowLocalInput(), publicInfo={totalItems:num("calcTotalItems"),totalGrid:num("calcTotalGrid"),goldGrid,purpleGrid,blueGrid,blueCount,blueAvg,greenGrid,greenCount,greenAvg,whiteGrid,whiteCount,whiteAvg,systemEstimate:num("calcSystemEstimate"),singleAvg:num("calcSingleAvg"),nineAvg:num("calcNineAvg"),note:val("calcPublicNote")};
      cancelActiveInference();
      const liveCondition=liveConditionPayload(Number(val("calcRound"))||1);
      let context={q,avg,goldCount,purple,redCount,purpleAvg,goldTotal,cost,targetProfit,minPurple,minGold,minRed,knownPurple,knownGold,knownRed,goldGroups:groups,purpleGroups,redGroups,toolGroup:val("calcToolGroup")||"group1",knownPurpleRaw:val("calcKnownPurple"),knownGoldRaw:val("calcOr"),knownRedRaw:val("calcKnownRed"),strategy:"profit",publicInfo,character:val("calcCharacter"),venue:val("calcVenue"),box:val("calcBox"),playedAt,periodKey:periodOf(playedAt)||"日期未知",round:Number(val("calcRound")),roundingMode,solverTimeBudgetMs:8000,solverStatus:"running",...liveCondition};
      context=enrichContextFromIntel(maybeLockRedZero(context));
      // if text intel found reds and form field empty, keep enriched knownRed
      if((!context.knownRed||!context.knownRed.length) && knownRed.length) context.knownRed=knownRed;
      if(context.knownRed&&context.knownRed.length && !knownRed.length) knownRed=context.knownRed;
      else context.knownRed=knownRed;
      redCount=context.redCount; minRed=Math.max(context.minRed||0, knownRed.length);
      context.minRed=minRed; context.redCount=redCount; context.inputHash=solverInputHash(context);context.requestId=++latestInferenceRequestId;context.startedAt=new Date().toISOString();latestInferenceInputHash=context.inputHash;
      // sync known red from text enrichment into worker groups path via context.knownRed
      const hasPriceInfo=avg!==null||goldTotal!==null||goldGrid!==null||purpleAvg!==null||groups.length||purpleGroups.length||redGroups.length||knownPurple.length||knownRed.length;
      if(q===null&&!hasPriceInfo){renderLowInfoEstimate(context,"没有 Q 或道具情报，先使用相近历史样本给低置信度估算；补充任意一条可靠情报后会继续收缩候选。");return;}
      // 有 Q 时始终进入共享 State Inference。Q-only 也是合法的渐进式输入，不能退回另一套手写枚举。
      document.getElementById("calculateBtn").disabled=true;renderLoading(context);
      activeWorker=startStateInferenceWorker(context,{onProgress:data=>{if(data.requestId!==context.requestId||data.inputHash!==context.inputHash||latestInferenceRequestId!==context.requestId||latestInferenceInputHash!==context.inputHash)return;const bar=document.querySelector("#resultPanel .solver-update-overlay .progress span")||document.querySelector("#resultPanel .progress span");if(bar)bar.style.width=`${Math.min(100,Math.max(0,data.step/data.maxSteps*100))}%`;},onDone:data=>{const currentHash=latestInferenceInputHash;if(data.requestId!==context.requestId||data.requestId!==latestInferenceRequestId||data.inputHash!==context.inputHash||currentHash!==context.inputHash){console.info("[solver] 丢弃过期 Worker 结果",{requestId:data.requestId,latestRequestId:latestInferenceRequestId,inputHash:data.inputHash,currentHash});return;}document.getElementById("calculateBtn").disabled=false;activeWorker=null;const status=solverStatusFromResult(data),chosenContext={...context,solverStatus:status,solverElapsedMs:data.elapsed??null,solverSearchCompleted:data.searchCompleted!==false,solverTruncated:data.truncated===true,roundingMode:data.chosenRoundingMode||context.roundingMode,requestedRoundingMode:context.roundingMode,roundingAudit:data.roundingAudit||null,goldInference:data.goldInference||null};data.goldOnly?renderGoldOnly(chosenContext,data.states,data.purpleStates||[]):renderAnalysis(chosenContext,data.states);},onError:error=>{if(context.requestId!==latestInferenceRequestId||context.inputHash!==latestInferenceInputHash)return;document.getElementById("calculateBtn").disabled=false;activeWorker=null;const timeout={...context,solverStatus:"timeout",solverSearchCompleted:false,solverElapsedMs:null};currentAnalysis={...timeout,predictedMin:null,predictedMax:null,candidates:[],observationOnly:false,timeout:true,frozenPrediction:null};toast("组合计算超时或被浏览器中断；这不等于输入无解",true);renderSolverFailure(timeout,"计算超时：没有证据证明当前输入矛盾。", "timeout");}});
    }

    function renderEmptyResult(){document.getElementById("resultPanel").innerHTML='<div class="result-empty"><div><div class="orb"><span>◇</span></div><h3>填多少都能估</h3><p>只有场地和箱型也会给历史低置信度基线；有金色均价时先反推可能的金色数量；再加 Q、紫色/金色/红色数量后才进入严格组合求解。</p></div></div>';}
    function renderLoading(ctx){
      const panel=document.getElementById("resultPanel"),preserve=currentAnalysis?.solverStatus==="stale"&&panel?.querySelector(".decision-summary");
      if(preserve){
        panel.classList.add("solver-stale","solver-updating");
        let notice=panel.querySelector(".solver-stale-notice");
        if(!notice){notice=document.createElement("div");notice.className="solver-stale-notice callout";panel.prepend(notice);}
        notice.innerHTML='<span class="dot"></span><div><strong>旧结果 · 正在根据新情报更新…</strong><br><small>旧数字已降权；新结果回来前不要依据它继续追价。</small></div>';
        const old=panel.querySelector(".solver-update-overlay");if(old)old.remove();
        panel.insertAdjacentHTML("afterbegin",`<div class="solver-update-overlay"><strong>正在重新求解 G / P / R…</strong><span>输入 hash ${escapeHtml(ctx.inputHash||"—")}</span><div class="progress"><span></span></div></div>`);
        return;
      }
      panel?.classList.remove("solver-stale","solver-updating");
      if(panel)panel.innerHTML=`<div class="result-top"><div class="eyebrow">Calculating</div><div class="result-status"><div class="status-copy"><h2>${ctx.q===null?'正在反推金色组合…':'正在联合求解 G / P / R…'}</h2><p>Q=${ctx.q??'未知'} · 金色均价=${fmt(ctx.avg)} · 金色总价=${fmt(ctx.goldTotal)} · 紫色均价=${fmt(ctx.purpleAvg)} · P=${ctx.purple??`≥${ctx.minPurple}`} · G=${ctx.goldCount??`≥${ctx.minGold}`} · R=${ctx.redCount??`≥${ctx.minRed}`}</p></div><div class="signal gold"><span>状态</span><strong>求解中</strong></div></div><div class="progress"><span></span></div></div><div class="result-empty" style="min-height:270px"><p>组合计算在浏览器后台进行；金额 OCR 仅在你上传截图时按需联网。</p></div>`;
    }
    function clearSolverStaleVisual(){const panel=document.getElementById("resultPanel");if(!panel)return;panel.classList.remove("solver-stale","solver-updating");panel.querySelector(".solver-stale-notice")?.remove();panel.querySelector(".solver-update-overlay")?.remove();}
    function focusV06DecisionSummary(){const target=document.querySelector("#resultPanel .v06-decision-panel");if(!target)return;const top=Math.max(0,Math.round(target.getBoundingClientRect().top+window.scrollY-78));window.scrollTo({top,behavior:"smooth"});}
    function renderSolverFailure(ctx,message,status="no-match"){
      const panel=document.getElementById("resultPanel"),wasUpdating=status==="timeout"&&panel?.classList.contains("solver-updating");
      const report=ctx.diagnosticReport||(status==="no-match"&&!ctx._diagnosticChecked?diagnosticSolverV06({...ctx,_diagnosticChecked:true},{solverStatus:"no-match",states:[]}):null),analysis={...ctx,inputHash:ctx.inputHash||solverInputHash(ctx),solverStatus:status,solverSearchCompleted:status!=="timeout",frozenPrediction:null,solvedAt:new Date().toISOString(),noMatch:status==='no-match',timeout:status==='timeout',diagnosticOnly:status==='no-match'||ctx.diagnosticOnly===true,diagnosticReport:report||null,_diagnosticChecked:true};currentAnalysis=analysis;upsertCurrentRoundSnapshot(false);
      const title=status==='timeout'?'计算超时':status==='incomplete'?'候选搜索未完成':status==='stale'?'当前结果已过期':'公开情报严格无解',detail=status==='timeout'?'没有证据证明当前输入矛盾；可以缩小格数/数量范围后重算。':status==='incomplete'?'已找到部分合法结构，但候选集合不完整；仅作预览，不生成正式推荐。':status==='stale'?'输入已变化，请重新推演后再保存当前回合预测。':message;
      if(wasUpdating&&panel){
        panel.classList.add("solver-stale");panel.classList.remove("solver-updating");
        let notice=panel.querySelector(".solver-stale-notice");if(!notice){notice=document.createElement("div");notice.className="solver-stale-notice callout";panel.prepend(notice);}
        notice.innerHTML='<span class="dot"></span><div><strong>上一结果已过期 · 最新情报计算超时</strong><br><small>禁止依据旧结果追价；缩小格数/数量范围后可再次推演。</small></div>';
        const overlay=panel.querySelector(".solver-update-overlay");if(overlay){overlay.innerHTML='<strong>计算超时 · 未证明输入无解</strong><span>上一结果仅作历史参考，不是当前预测。</span>';overlay.style.borderColor="#f59e0b";overlay.style.background="#fffbeb";overlay.style.color="#92400e";}
        return;
      }
      panel?.classList.remove("solver-stale","solver-updating");
      if(panel)panel.innerHTML=`<div class="result-top"><div class="eyebrow">v0.6 · ${escapeHtml(status)}</div><div class="result-status"><div class="status-copy"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(detail)}</p></div><div class="signal ${status==='timeout'?'gold':'red'}"><span>状态</span><strong>${escapeHtml(predictionStatusLabel(status))}</strong></div></div>${ctx.roundingAudit?roundingAuditHtml(ctx.roundingAudit):''}</div><div class="result-body"><div class="callout"><span class="dot"></span><div><strong>本次不会生成正式估值或推荐上限。</strong>保存时只保留输入、solverStatus、inputHash 和诊断快照；不会在保存层偷偷重新调用估值模型。</div></div>${message?`<div class="field-help">${escapeHtml(message)}</div>`:""}${report?diagnosticReportHtml(report):""}${settlementActions()}</div>`;
    }
    // 只解释当前硬约束与共享 State Inference 结果，不参与任何估值/概率/出价计算。
    function practicalNextIntel(ctx,analysis){
      const round=Math.max(1,Math.min(5,Number(ctx?.round)||Number(analysis?.round)||1)),next=Math.min(5,round+1),randomMode=(ctx?.toolGroup||"group1")==="group2",hasAvg=hasNumber(ctx?.avg),hasPurple=hasNumber(ctx?.purple),states=Array.isArray(analysis?.candidates)?analysis.candidates:[],stateCount=states.length||null,shadow=analysis?.workingDecision?.probabilityProfile?.shadowWhole||null,wideShadow=shadow&&Number.isFinite(shadow.p20)&&Number.isFinite(shadow.p80)&&shadow.p80-shadow.p20>Math.max(150000,(shadow.p50||0)*.45),structureWide=(stateCount||0)>2;
      if(!randomMode&&next===2)return {main:"R2：紫色数量",detail:"常用流程；紫数会把剩余结构接成 G + R = Q − P。",theory:hasAvg?"若可自由选，道具应优先区分当前 G/R 分叉":"若 R1 未拿到金均，先补金均"};
      if(!randomMode&&next===3)return {main:"R3：随机展示 5 件藏品",detail:"看到具体藏品就把金 / 紫 / 红加入对应约束；不把“没抽到某品质”当成整箱没有。",theory:"具体藏品能同时提供品质、价格和轮廓，是当前流程的信息密度最高项"};
      if(next<=5){
        if(structureWide)return {main:`R${next}：优先随机展示 8 件品质`,detail:`当前仍有 ${stateCount} 个 G/P/R 结构；品质信息最可能先缩小 State 集合。若本轮没有该道具，再用随机 5 件具体藏品。`,theory:"结构分叉大时，先减少 State 数量；不要为了尾部价值先看轮廓"};
        if(wideShadow)return {main:`R${next}：优先随机展示 5 件具体藏品`,detail:"结构已较集中，但整仓价值区间仍宽；具体藏品比单看品质更能改变本局可接受价格。",theory:"State 锁定后，应优先压缩 State 内部价值误差"};
        if(!hasPurple)return {main:`R${next}：若可用，补随机展示 8 件品质`,detail:"紫色数量尚未确认；品质样本可先缩小 P 与剩余 G/R 结构。",theory:"当前最大缺口是品质结构"};
        return {main:`R${next}：优先随机展示 10 件轮廓；否则可停买情报`,detail:"结构和价值区间已较集中。轮廓只用于识别高价值大件；若预期不会改变你的跟价，保留这轮成本。",theory:"当新增情报的预期出价变化小于道具成本时，停止购买信息"};
      }
      return {main:"本局已到最后回合",detail:"补录出现的新公开信息即可。",theory:""};
    }
    function progressiveInferenceHtml(ctx,analysis,inference=null){
      const a=analysis||ctx||{},states=Array.isArray(a.candidates)?a.candidates:[],gs=[...new Set((a.candidateGs||[]).filter(Number.isInteger))].sort((x,y)=>x-y),ps=[...new Set((a.candidatePs||[]).filter(Number.isInteger))].sort((x,y)=>x-y),hasQ=Number.isInteger(ctx?.q),stateCount=states.length||((inference?.states||[]).length||null);
      const locked=[];
      if(Number.isInteger(ctx?.goldCount))locked.push(`G=${ctx.goldCount}`);else if(gs.length===1)locked.push(`G=${gs[0]}`);else locked.push(`G 未锁（${gs.length?gs.join("/"):"?"}）`);
      if(Number.isInteger(ctx?.purple))locked.push(`P=${ctx.purple}`);else if(ps.length===1&&!a.stateInferencePartial)locked.push(`P=${ps[0]}`);else locked.push("P 未锁");
      const rMin=Number.isFinite(a.redMin)?a.redMin:(Number.isInteger(ctx?.redCount)?ctx.redCount:ctx?.minRed??0),rMax=Number.isFinite(a.redMax)?a.redMax:(Number.isInteger(ctx?.redCount)?ctx.redCount:null);locked.push(rMax!==null&&rMin===rMax?`R=${rMin}`:`R 未锁（${rMax===null?`${rMin}+`:`${rMin}–${rMax}`}）`);
      const practical=practicalNextIntel(ctx,analysis),next=practical.main;
      const stateLabel=stateCount===null?"尚未形成 G/P/R 状态集合":`${stateCount} 个候选状态（共享 State Inference）${Number(a.fullStateCount)>stateCount?` · 完整硬候选 ${a.fullStateCount} 个`:""}`;
      const note=!hasQ&&ctx.avg!==null?"当前只有独立金色价格池；P/R 没有 Q 方程，保持未知，不按历史比例硬拆。":hasQ?"每条新情报都叠加到同一候选集合；未知 P/R 只显示范围，不伪造精确数量。":"当前没有可连接结构的硬情报；先记录低置信度基线，补 Q 或任一价格证据即可继续收缩。";
      return `<div class="progressive-inference-panel"><div class="progressive-head"><strong>渐进式推演</strong><span class="badge ${hasQ?"blue":"muted"}">${stateLabel}</span></div><div class="progressive-locks">${locked.map(x=>`<span class="progressive-lock">${escapeHtml(x)}</span>`).join("")}</div><div class="progressive-next"><span>下一回合实际可获得</span><strong>${escapeHtml(next)}</strong><small>${escapeHtml(practical.detail)}</small></div><details class="progressive-theory"><summary>理论上最能压缩候选</summary><span>${escapeHtml(practical.theory||"暂无")}</span></details><p class="progressive-note">${escapeHtml(note)}</p></div>`;
    }
    function settlementActions(){const round=Number(currentAnalysis?.round)||1;return `<div class="result-save-row"><div class="result-quick-actions"><button class="btn" title="不增加回合，下一次推演会覆盖当前回合快照" onclick="redoCurrentRound()">本回合再算</button><span id="autoRoundStatus" class="round-snapshot"><strong>R${round}</strong><span>自动记录中</span></span><button class="btn primary" onclick="openSettlementCapture()">本局结束 · 结算并保存</button></div><div id="roundTimeline" class="round-timeline">${roundTimelineHtml()}</div></div>`;}
    function syncSettlementDockState(open){
      const result=document.getElementById("resultPanel");
      if(result)result.classList.toggle("settlement-docked", !!open);
    }
    window.openSettlementCapture=function(){
      const panel=document.getElementById("settlementCapture");
      if(!panel)return;
      panel.open=true;
      syncSettlementDockState(true);
      panel.scrollIntoView({behavior:"smooth",block:"nearest"});
      setTimeout(()=>document.getElementById("resultActualTotal")?.focus(),320);
    };
    function readResultAmount(id){const el=document.getElementById(id);if(!el||el.value.trim()==="")return null;const amount=Number(el.value);return Number.isFinite(amount)&&amount>=0?amount:undefined;}
    function readResultFinalBid(){return readResultAmount("resultFinalBid");}
    function readResultActualTotal(){return readResultAmount("resultActualTotal");}
    function readResultFinalRed(){const el=document.getElementById("resultFinalRed");return el?el.value.trim():"";}

    function renderLowInfoEstimate(ctx,message){
      const d=workingDecision(ctx);d.solverStatus="fallback";d.inputHash=ctx.inputHash||solverInputHash(ctx);const analysis={...ctx,inputHash:ctx.inputHash||solverInputHash(ctx),solverStatus:"fallback",solverSearchCompleted:true,candidateGs:ctx.goldCount!==null?[ctx.goldCount]:[],candidatePs:ctx.purple!==null?[ctx.purple]:[],predictedMin:d.low,predictedMax:d.high,redMin:ctx.redCount??ctx.minRed,redMax:ctx.redCount??null,observationOnly:true,lowInfo:true,workingDecision:d,solvedAt:new Date().toISOString()};analysis.frozenPrediction=buildPredictionSnapshot(analysis,d,"fallback");currentAnalysis=analysis;clearSolverStaleVisual();
      document.getElementById("resultPanel").innerHTML=`<div class="result-top"><div class="eyebrow">low-information baseline</div><div class="result-status"><div class="status-copy"><h2>低信息基线 ${fmtWan(d.center)}</h2><p>${escapeHtml(message)}</p></div><span class="decision-tag medium">结构不确定性 · 高</span></div>${decisionMetrics(d)}${roundingAuditHtml(ctx.roundingAudit)}</div><div class="result-body"><div class="callout"><span class="dot"></span><div>没有价格硬证据时，页面只使用本局之前、同场地/箱型/Q 的加权近邻低分位；这适合“纯看客”记账，不适合为了秒杀追价。</div></div>${progressiveInferenceHtml(ctx,currentAnalysis)}${similarHistoryHtml(d)}${settlementActions()}<div id="empiricalHint" style="margin-top:14px"></div></div>`;
      renderEmpiricalHint(currentAnalysis);
      completeSuccessfulRound();
    }

    function analyzeGoldOnly(ctx,solutions,purpleSolutions=[]){
      const hasGold=ctx.avg!==null||ctx.goldTotal!==null||hasNumber(ctx.publicInfo?.goldGrid)||(ctx.knownGold||[]).length||(ctx.goldGroups||[]).length||ctx.goldCount!==null,hasPurple=ctx.purpleAvg!==null||(ctx.knownPurple||[]).length||(ctx.purpleGroups||[]).length||ctx.purple!==null;
      const goldPool=hasGold?solutions:[],purplePool=hasPurple?purpleSolutions:[];
      if((hasGold&&!goldPool.length)||(ctx.purpleAvg!==null&&!purplePool.length))return {error:"no-match"};
      // 无 Q 时只能独立反推金/紫价格池；P/R 没有合法的数量方程，禁止构造一个代表 State 再送入估值。
      const d=workingDecision(ctx,[],{sourceSuffix:" · 无Q分池估算"}),gs=goldPool.map(x=>x.count),ps=purplePool.map(x=>x.count);d.confidence="低";const analysis={...ctx,inputHash:ctx.inputHash||solverInputHash(ctx),solverStatus:ctx.solverStatus||"valid",solverSearchCompleted:ctx.solverSearchCompleted!==false,solvedAt:new Date().toISOString(),candidateGs:gs,candidatePs:ps,predictedMin:d.low,predictedMax:d.high,redMin:ctx.minRed,redMax:null,candidates:[],observationOnly:true,goldOnly:true,stateInferencePartial:true,workingDecision:d};d.solverStatus=analysis.solverStatus;d.inputHash=analysis.inputHash;analysis.frozenPrediction=buildPredictionSnapshot(analysis,d,analysis.solverStatus);return {analysis,d,goldPool,purplePool,gs,ps};
    }
    function renderGoldOnly(ctx,solutions,purpleSolutions=[]){
      const solved=analyzeGoldOnly(ctx,solutions,purpleSolutions);if(solved.error){renderSolverFailure({...ctx,solverStatus:ctx.solverStatus||"no-match",frozenPrediction:null},"严格价格池没有匹配组合；请检查取整、价格口径或图鉴版本。",ctx.solverStatus||"no-match");return;}const {analysis,d,goldPool,purplePool,gs,ps}=solved;currentAnalysis=analysis;clearSolverStaleVisual();
      const poolHtml=(title,pool,color,formatter)=>pool.length?`<div><h3 style="font-size:13px">${title}</h3><div class="candidate-list">${pool.slice(0,20).map(s=>`<details class="candidate"><summary><div class="candidate-title"><strong>${color}=${s.count}</strong><small>${s.truncated?`候选≥${s.matchCount??s.matches.length}`:`${s.matchCount??s.matches.length} 个离散组合`}</small></div><div class="candidate-range"><strong>${fmtWan(s.low)} — ${fmtWan(s.high)}</strong><small>${title}</small></div></summary><div class="candidate-content">${s.matches.slice(0,5).map(formatter).join("")||'<div class="combo"><div>仅能给出图鉴边界。</div></div>'}</div></details>`).join("")}</div></div>`:"";
      document.getElementById("resultPanel").innerHTML=`<div class="result-top"><div class="eyebrow">independent price pools</div><div class="result-status"><div class="status-copy"><h2>整仓价值地图</h2><p>无 Q：金色/紫色价格池独立估算，P/R 结构仍未连接。</p></div><span class="decision-tag medium">结构不确定性 · 低</span></div>${decisionMetrics(d)} </div><div class="result-body"><div class="callout"><span class="dot"></span><div><strong>无 Q 渐进推演：</strong>每条价格情报仍会收缩对应候选，但不要把独立金/紫池当成完整箱价。</div></div>${progressiveInferenceHtml(ctx,currentAnalysis)}${similarHistoryHtml(d)}<details class="algorithm-details"><summary>算法详情 / 调试信息 · 独立金紫价格池</summary><div class="algorithm-details-body">${roundingAuditHtml(ctx.roundingAudit)}${goldInferenceHtml(ctx,ctx.goldInference)}<div class="result-details-body">${poolHtml("金色部分",goldPool,"G",c=>`<div class="combo"><div>${escapeHtml(comboName(c,ctx))}</div><small>总价 ${fmt(c.reduce((a,b)=>a+b,0))}</small></div>`)}${poolHtml("紫色部分",purplePool,"P",c=>`<div class="combo"><div class="purple-text">${c.join(" + ")}</div><small>总价 ${fmt(c.reduce((a,b)=>a+b,0))}</small></div>`)}</div></div></details>${settlementActions()}<div id="empiricalHint" style="margin-top:14px"></div></div>`;
      const inferenceMount=document.querySelector("#resultPanel .result-top");if(inferenceMount&&ctx.goldInference)inferenceMount.insertAdjacentHTML("beforeend",goldInferenceHtml(ctx,ctx.goldInference));
      renderEmpiricalHint(currentAnalysis);
      completeSuccessfulRound();
    }

    function analyzeObservationOnly(ctx){
      ctx=maybeLockRedZero(ctx);
      const states=[];for(let g=0;g<=ctx.q;g++)for(let p=0;p<=ctx.q-g;p++){const r=ctx.q-g-p;if(g<ctx.minGold||p<ctx.minPurple||r<ctx.minRed)continue;if(ctx.goldCount!==null&&g!==ctx.goldCount)continue;if(ctx.purple!==null&&p!==ctx.purple)continue;if(ctx.redCount!==null&&r!==ctx.redCount)continue;states.push({g,p,r,gold:{unconstrained:true,matches:[]},purple:{unconstrained:true,matches:[]}});}
      if(!states.length)return {error:"no-match",analysis:{...ctx,observationOnly:true,noMatch:true}};
      let useStates=states;
      if(states.length>120){
        const pick=new Map();
        for(const s of states){ const key=s.g+","+s.p; if(!pick.has(key)) pick.set(key,s); }
        useStates=[...pick.values()].sort((a,b)=>a.r-b.r);
        const low=useStates.filter(s=>s.r<=2).slice(0,80);
        const high=useStates.slice(-20);
        useStates=[...new Map([...low,...high].map(s=>[s.g+":"+s.p+":"+s.r,s])).values()];
      }
      const gs=[...new Set(useStates.map(x=>x.g))],ps=[...new Set(useStates.map(x=>x.p))],rs=[...new Set(useStates.map(x=>x.r))],gMin=Math.min(...gs),gMax=Math.max(...gs),redMin=Math.min(...rs),redMax=Math.max(...rs),publicCount=Object.values(ctx.publicInfo||{}).filter(x=>x!==null&&x!=="").length,knownValue=[...ctx.knownPurple,...ctx.knownGold,...ctx.knownRed].reduce((sum,x)=>sum+x.price,0);
      const d=workingDecision(ctx,useStates),analysis={...ctx,candidateGs:gs,candidatePs:ps,predictedMin:d.low,predictedMax:d.high,redMin,redMax,candidates:useStates,observationOnly:true,workingDecision:d};return {analysis,d,states,useStates,gs,ps,rs,gMin,gMax,redMin,redMax,publicCount,knownValue};
    }
    function renderObservationOnly(ctx){
      const solved=analyzeObservationOnly(ctx);if(solved.error){toast("Q、精确数量和最低数量互相矛盾",true);return;}const {analysis,d,states,gs,ps,gMin,gMax,redMin,redMax,publicCount}=solved;ctx=analysis;currentAnalysis=analysis;clearSolverStaleVisual();
      document.getElementById("resultPanel").innerHTML=`<div class="result-top"><div class="eyebrow">legacy quantity baseline</div><div class="result-status"><div class="status-copy"><h2>数量先验 ${fmtWan(d.center)}</h2><p>兼容旧记录展示；当前新推演会优先走共享 State Inference。</p></div><span class="decision-tag ${redMin>=1?'high':'medium'}">结构不确定性 · ${redMin>=1?'中':'高'}</span></div>${decisionMetrics(d)}</div><div class="result-body"><div class="callout"><span class="dot"></span><div><strong>数量结论：</strong>Q=${ctx.q}，P=${ps.length===1?ps[0]:`${Math.min(...ps)}–${Math.max(...ps)}`}，G=${gMin===gMax?gMin:`${gMin}–${gMax}`}，R=${redMin===redMax?redMin:`${redMin}–${redMax}`}。</div></div>${progressiveInferenceHtml(ctx,currentAnalysis)}${similarHistoryHtml(d)}${settlementActions()}<div id="empiricalHint" style="margin-top:14px"></div></div>`;
      renderEmpiricalHint({...currentAnalysis,candidates:states});
      completeSuccessfulRound();
    }

    function extreme(items,count,maximize,repeat=2){if(count<0)return null;if(count===0)return 0;const arr=[];items.forEach(x=>{for(let i=0;i<repeat;i++)arr.push(x[1]);});if(count>arr.length)return null;arr.sort((a,b)=>maximize?b-a:a-b);return arr.slice(0,count).reduce((a,b)=>a+b,0);}
    function constrainedExtreme(items,count,known,maximize,repeat=2){if(count<known.length)return null;const capacities=new Map();items.forEach(x=>capacities.set(x[1],(capacities.get(x[1])||0)+repeat));let fixed=0;for(const x of known){const left=capacities.get(x.price)||0;if(left<1)return null;capacities.set(x.price,left-1);fixed+=x.price;}const pool=[];for(const [price,n] of capacities)for(let i=0;i<n;i++)pool.push(price);const need=count-known.length;if(need>pool.length)return null;pool.sort((a,b)=>maximize?b-a:a-b);return fixed+pool.slice(0,need).reduce((a,b)=>a+b,0);}
    function unknownRestExtreme(ctx,rest,maximize){const catalog=effectiveCatalog(ctx),knownPurple=adjustedKnownItems(ctx,"purple",ctx.knownPurple);let best=maximize?-Infinity:Infinity;for(let r=ctx.minRed;r<=rest-ctx.minPurple;r++){const p=rest-r,pv=constrainedExtreme(catalog.purple,p,knownPurple,maximize),rv=constrainedExtreme(catalog.red,r,ctx.knownRed,maximize);if(pv===null||rv===null)continue;const total=pv+rv;best=maximize?Math.max(best,total):Math.min(best,total);}return Number.isFinite(best)?best:null;}
    function comboName(combo,ctx={}){const names=Object.fromEntries(effectiveCatalog(ctx).gold.map(x=>[x[1],x[0]]));return combo.map(p=>names[p]?`${names[p]}(${p})`:String(p)).join(" + ");}

    function goldInferenceHtml(ctx,info){
      if(!info||!Array.isArray(info.byG)||!info.byG.length)return "";
      const grid=ctx.publicInfo?.goldGrid,gridLabel=hasNumber(grid)?`金总价 + 金占格（${fmt(grid)} 格）`:hasNumber(ctx.goldTotal)?"金总价硬约束":hasNumber(ctx.avg)?"金均取整约束":"金色离散组合";
      const totalLabel=`${info.goldMatchCountExact?fmt(info.goldMatchCount):`≥${fmt(info.goldMatchCount)}`}`;
      const minRed=Math.max(0,Number(ctx.minRed)||0),legalRows=info.byG.filter(row=>{
        if(info.q===null||info.q===undefined||info.fixedPurple===null||info.fixedPurple===undefined)return true;
        return Number(info.q)-Number(row.G)-Number(info.fixedPurple)>=minRed;
      }),rows=legalRows.map(row=>{
        const rest=info.q===null?"":` · P+R=${info.q-row.G}`;
        const pr=info.fixedPurple!==null?`P=${info.fixedPurple} · R=${info.q===null?"?":info.q-row.G-info.fixedPurple}`:"P/R 未拆开";
        const combos=(row.combinations||[]).slice(0,4).map(c=>`<div class="combo"><div>${escapeHtml(comboName(c.prices,ctx))}</div><small>总价 ${fmt(c.total)}${hasNumber(grid)?` · 格数 ${fmt(grid)}`:""}</small></div>`).join("");
        return `<details class="candidate gold-inference-row"><summary><div class="candidate-title"><strong>G=${row.G}</strong><small>${row.combinationCountExact?`${fmt(row.combinationCount)} 个组合`:`≥${fmt(row.combinationCount)} 个组合`} · ${pr}</small></div><div class="candidate-range"><strong>${escapeHtml(rest.replace(" · ",""))}</strong><small>剩余紫/红关系</small></div></summary><div class="candidate-content">${combos||'<div class="combo"><div>组合示例未保留。</div></div>'}</div></details>`;
       });
      const legalGs=legalRows.map(row=>row.G),status=info.uniqueCombination?"唯一具体金色组合":legalGs.length===1?"G 唯一，但具体金色组合仍多解":"G 仍有多个候选",relation=info.q===null?"没有 Q，不能推出 P/R。":info.fixedPurple!==null?"每个合法 G 都满足 P+R=Q−G；当前 P 已知，因此可继续算出 R。":"每个 G 都满足 P+R=Q−G；当前没有紫数，所以未知 P/R 不会被历史比例自动拆分。";
      return `<details class="result-details gold-inference"><summary>金色 State Inference · ${escapeHtml(gridLabel)} · ${status}</summary><div class="result-details-body"><div class="callout"><span class="dot"></span><div><strong>goldMatchCount：</strong>${totalLabel}；<strong>candidateGs：</strong>${legalGs.join(" / ")||"无"}。${relation}${info.q!==null&&info.fixedPurple!==null?` <small>已过滤 R&lt;${minRed} 的不合法 G。</small>`:""}</div></div><div class="candidate-list">${rows.join("")}</div></div></details>`;
    }

    function theoreticalMinimumBreakdown(ctx,candidates){
      const catalog=effectiveCatalog(ctx),knownGold=adjustedKnownItems(ctx,"gold",ctx.knownGold||[]),knownPurple=adjustedKnownItems(ctx,"purple",ctx.knownPurple||[]);let best=null;
      for(const state of candidates||[]){
        if(![state.g,state.p,state.r].every(Number.isInteger))continue;
        const gold=Number.isFinite(state.goldMin)?state.goldMin:constrainedExtreme(catalog.gold,state.g,knownGold,false),purple=Number.isFinite(state.purpleMin)?state.purpleMin:constrainedExtreme(catalog.purple,state.p,knownPurple,false),red=constrainedExtreme(catalog.red,state.r,ctx.knownRed||[],false);
        if(![gold,purple,red].every(Number.isFinite))continue;
        const total=gold+purple+red,row={g:state.g,p:state.p,r:state.r,gold,purple,red,total,knownGold:(ctx.knownGold||[]).map(x=>x.price),knownPurple:(ctx.knownPurple||[]).map(x=>x.price),knownRed:(ctx.knownRed||[]).map(x=>x.price),repeatLimit:2};if(!best||row.total<best.total)best=row;
      }
      return best;
    }

    function analyzeSolvedStateInference(ctx,states){
      if(!states.length)return {error:"no-match",analysis:{...ctx,roundingAudit:ctx.roundingAudit||null,observationOnly:false,noMatch:true}};
      const catalog=effectiveCatalog(ctx),knownGold=adjustedKnownItems(ctx,"gold",ctx.knownGold||[]),knownPurple=adjustedKnownItems(ctx,"purple",ctx.knownPurple||[]);let globalMin=Infinity,globalMax=-Infinity,redMin=Infinity,redMax=-Infinity;
      const enriched=states.map(c=>{
        const goldSums=c.gold.matches.map(x=>x.reduce((a,b)=>a+b,0));
        const goldUsesExactPriceBand=Number.isFinite(ctx.avg)||Number.isFinite(ctx.goldTotal),goldMin=c.gold.unconstrained||c.gold.groupOnly||!goldUsesExactPriceBand?constrainedExtreme(catalog.gold,c.g,knownGold,false):(c.gold.truncated?c.gold.low:Math.min(...goldSums)),goldMax=c.gold.unconstrained||c.gold.groupOnly||!goldUsesExactPriceBand?constrainedExtreme(catalog.gold,c.g,knownGold,true):(c.gold.truncated?c.gold.high:Math.max(...goldSums));
        let restMin,restMax,rRange=[c.rMin,c.rMax],purpleMin=null,purpleMax=null;
        if(c.p!==null){
          if(c.purple){const sums=c.purple.matches.map(x=>x.reduce((a,b)=>a+b,0)),purpleUsesExactPriceBand=Number.isFinite(ctx.purpleAvg);purpleMin=c.purple.unconstrained||c.purple.groupOnly||!purpleUsesExactPriceBand?constrainedExtreme(catalog.purple,c.p,knownPurple,false):(c.purple.truncated?c.purple.low:Math.min(...sums));purpleMax=c.purple.unconstrained||c.purple.groupOnly||!purpleUsesExactPriceBand?constrainedExtreme(catalog.purple,c.p,knownPurple,true):(c.purple.truncated?c.purple.high:Math.max(...sums));}
          else {purpleMin=constrainedExtreme(catalog.purple,c.p,knownPurple,false);purpleMax=constrainedExtreme(catalog.purple,c.p,knownPurple,true);}
          const rLo=constrainedExtreme(catalog.red,c.r,ctx.knownRed,false),rHi=constrainedExtreme(catalog.red,c.r,ctx.knownRed,true);if([purpleMin,purpleMax,rLo,rHi,goldMin,goldMax].some(x=>x===null))return null;restMin=purpleMin+rLo;restMax=purpleMax+rHi;
        } else {const rest=ctx.q-c.g;restMin=unknownRestExtreme(ctx,rest,false);restMax=unknownRestExtreme(ctx,rest,true);}
        if(restMin===null||restMax===null)return null;
        const totalMin=goldMin+restMin,totalMax=goldMax+restMax;globalMin=Math.min(globalMin,totalMin);globalMax=Math.max(globalMax,totalMax);redMin=Math.min(redMin,rRange[0]);redMax=Math.max(redMax,rRange[1]);
        return {...c,goldMin,goldMax,purpleMin,purpleMax,restMin,restMax,totalMin,totalMax,red:rRange[0]===rRange[1]?rRange[0]:null};
      }).filter(Boolean);
      if(!enriched.length)return {error:"invalid-extremes",analysis:{...ctx,observationOnly:false,noMatch:true}};
      const ctx2=maybeLockRedZero(ctx),hasPriceEvidence=Number.isFinite(ctx2.avg)||Number.isFinite(ctx2.goldTotal)||Number.isFinite(ctx2.purpleAvg)||hasNumber(ctx2.publicInfo?.goldGrid)||(ctx2.knownGold||[]).length>0||(ctx2.goldGroups||[]).length>0||(ctx2.knownPurple||[]).length>0||(ctx2.purpleGroups||[]).length>0||(ctx2.knownRed||[]).length>0||(ctx2.redGroups||[]).length>0;
      // Q-only/数量-only 仍保留完整硬候选与 Feasible Range；价值/概率展开只取
      // 首端、中段、尾端代表 State，避免低信息局把每个未知 P/R 拆分成数百个
      // bootstrap 组合。这里是展示性能保护，不改变 State 硬约束或 v0.3 参数。
      const valuationInput=!hasPriceEvidence&&enriched.length>12?[...new Map([...enriched.slice(0,4),...enriched.slice(Math.max(4,Math.floor(enriched.length/2)-2),Math.floor(enriched.length/2)+2),...enriched.slice(-4)].map(x=>[`${x.g}/${x.p??"?"}/${x.rMin}/${x.rMax}`,x])).values()]:enriched;
      let expanded=expandStatesForValuation(ctx2, valuationInput);
      // Q-only/quantity-only 状态可以很多；完整硬候选仍保留在 enriched，
      // 这里只给旧 v0.3/旁路概率做少量代表状态，避免低信息局在浏览器主线程
      // 展开数百个 P/R 组合后长时间无响应。这个是展示/计算预算，不是约束或权重。
      if(!hasPriceEvidence&&expanded.length>12){
        const ordered=expanded.slice().sort((a,b)=>Number(a.g)-Number(b.g)||Number(a.p)-Number(b.p)||Number(a.r)-Number(b.r));
        const middle=Math.floor(ordered.length/2),picked=[...ordered.slice(0,4),...ordered.slice(Math.max(4,middle-2),middle+2),...ordered.slice(-4)];
        expanded=[...new Map(picked.map(x=>[`${x.g}/${x.p}/${x.r}`,x])).values()];
      }
      const d=workingDecision(ctx2,expanded,{theoreticalMax:globalMax});
      // v0.6-shadow sidecars are observational only. They are saved beside
      // the legacy heuristic and never replace its weights or center value.
      d.empiricalStatePrior=empiricalStatePriorV06(ctx2,expanded);
      d.shadowCalibrated=shadowCalibrationSidecarV06(ctx2,d);
      d.marketPrediction=marketPredictionV06(ctx2,d.center);
      d.entryDecision=entryDecisionV06(ctx2,d);
      const gs2=[...new Set(expanded.map(x=>x.g))].sort((a,b)=>a-b);
      const ps2=[...new Set(expanded.map(x=>x.p).filter(x=>x!=null))].sort((a,b)=>a-b);
      const rs2=expanded.map(x=>x.r).filter(Number.isInteger);
      const redMin2=rs2.length?Math.min(...rs2):redMin, redMax2=rs2.length?Math.max(...rs2):redMax;
      const redStatus2=redMin2===0&&redMax2===0?"确认无红":redMin2>=1&&redMin2===redMax2?"确认有红":redMax2>=1?"可能有红":"确认无红";
      const signalClass2=redMin2>=1?"red":redMax2>=1?"gold":"muted";
      const minimumBreakdown=theoreticalMinimumBreakdown(ctx2,expanded);if(minimumBreakdown&&minimumBreakdown.total<globalMin)globalMin=minimumBreakdown.total;
      const fullGs=[...new Set(enriched.map(x=>x.g).filter(Number.isInteger))].sort((a,b)=>a-b),fullPs=new Set();
      if(Number.isInteger(ctx2.purple))fullPs.add(ctx2.purple);else for(const c of enriched){const lo=Math.max(ctx2.minPurple||0,0),hi=Math.max(lo,ctx2.q-c.g-(ctx2.minRed||0));for(let p=lo;p<=hi;p++)fullPs.add(p);}
      const fullPsList=[...fullPs].sort((a,b)=>a-b);
      const analysis={...ctx2,inputHash:ctx2.inputHash||solverInputHash(ctx2),solverStatus:ctx2.solverStatus||"valid",solverSearchCompleted:ctx2.solverSearchCompleted!==false,solvedAt:new Date().toISOString(),candidateGs:fullGs,candidatePs:fullPsList,predictedMin:d.low,predictedMax:d.high,theoreticalMin:globalMin,theoreticalMax:globalMax,theoreticalMinimumBreakdown:minimumBreakdown,redMin:redMin2,redMax:redMax2,candidates:expanded,fullStateCount:enriched.length,valuationStateCount:expanded.length,valuationStateCompressed:expanded.length<enriched.length,empiricalStatePrior:d.empiricalStatePrior||null,shadowCalibrated:d.shadowCalibrated||null,marketPrediction:d.marketPrediction||null,entryDecision:d.entryDecision||null,observationOnly:false,workingDecision:d};d.solverStatus=analysis.solverStatus;d.inputHash=analysis.inputHash;d.solverTruncated=analysis.solverTruncated===true;if(analysis.solverStatus==="incomplete"){d.recommendationSuppressed=true;d.recommendationSuppressedReason="候选搜索未完成：仅作预览，不生成正式推荐";d.recommendedMaxBid=d.balancedCap=d.cap=d.conservativeLossLine=d.highRiskTrialLine=null;d.entryDecision=null;analysis.entryDecision=null;}analysis.frozenPrediction=buildPredictionSnapshot(analysis,d,analysis.solverStatus);
      return {analysis,d,enriched,expanded,globalMin,globalMax,redMin:redMin2,redMax:redMax2,redStatus:redStatus2,signalClass:signalClass2,gs:fullGs,ps:fullPsList};
    }

    function renderAnalysis(ctx,states){
      if(ctx.solverStatus==="timeout"){renderSolverFailure({...ctx,frozenPrediction:null},"计算超时：没有证据证明当前输入矛盾。","timeout");return;}
      const solved=analyzeSolvedStateInference(ctx,states);
      if(solved.error==="no-match"){const retry=ctx.roundingAudit?.nearestMatchCount>0?"可改用四舍五入重算":ctx.roundingAudit?.compatibleMatchCount>0?"可改用兼容取整重算":"",diagnosticReport=diagnosticSolverV06({...solved.analysis,solverStatus:"no-match",inputHash:ctx.inputHash},{solverStatus:"no-match",states:[]});renderSolverFailure({...solved.analysis,solverStatus:"no-match",inputHash:ctx.inputHash,frozenPrediction:null,diagnosticOnly:true,diagnosticReport,_diagnosticChecked:true},"当前所选规则没有任何 G/P/R 与价格组合能同时满足输入。"+(retry?`取整审计提示：${retry}；也请检查抄录、价格版本、重复上限或数量约束。`:"请检查抄录、价格版本、重复上限或数量约束。"),"no-match");return;}
      if(solved.error){toast("公开数量与价格组合不成立",true);return;}
      const {analysis,d,enriched,expanded,globalMin,globalMax,redStatus: redStatus2,signalClass: signalClass2,gs:gs2,ps:ps2}=solved,ctx2=analysis;currentAnalysis=analysis;clearSolverStaleVisual();
      const goldStateText=gs2.length?(gs2.length===1?`G=${gs2[0]}`:`G∈{${gs2.join(" / ")}}`):"G 未锁定（离散组合无精确解，已退回分项+历史）";
      const candidatePreviewLimit=36;
      document.getElementById("resultPanel").innerHTML=`
         <div class="result-top"><div class="eyebrow">v0.3 · walk-forward</div><div class="result-status"><div class="status-copy"><h2>整仓价值地图</h2><p>${redStatus2}；${goldStateText}${ps2.length?` · ${ps2.length===1?`P=${ps2[0]}`:`P∈{${ps2.slice(0,8).join(" / ")}${ps2.length>8?"…":""}}`}`:""}${ctx2.redCount===0?" · R=0":""}。${expanded.length?`当前 ${expanded.length} 个合法结构。`:"当前结构仍待情报收敛。"}</p></div><span class="decision-tag ${signalClass2==="red"?"high":signalClass2==="green"?"low":"medium"}">结构不确定性 · ${escapeHtml(d.confidence)}</span></div>${decisionMetrics(d)}</div>
         <div class="result-body">${progressiveInferenceHtml(ctx2,analysis)}${similarHistoryHtml(d)}<details class="algorithm-details"><summary>算法详情 / 调试信息 · 理论边界 ${fmtWan(globalMin)}—${fmtWan(globalMax)}${globalMax>1000000?" · 含极端 Jackpot":""}</summary><div class="algorithm-details-body">${roundingAuditHtml(ctx2.roundingAudit)}${ctx2.goldInference?goldInferenceHtml(ctx2,ctx2.goldInference):""}${decisionExplanationHtml(d)}${jackpotRiskHtml(d)}<details class="result-details"><summary>Feasible Range · 候选预览与公式</summary><div class="result-details-body"><div class="candidate-list">${enriched.slice(0,candidatePreviewLimit).map(c=>candidateHtml(c,false,ctx)).join("")}${enriched.length>candidatePreviewLimit?`<div class="hint">另有 ${enriched.length-candidatePreviewLimit} 个数量状态未展开，但已计入红件数与价值边界；State/概率面板保留压缩后的整体结构。</div>`:""}</div></div></details></div></details>${settlementActions()}<div id="empiricalHint" style="margin-top:14px"></div></div>`;
      renderEmpiricalHint(currentAnalysis);
      // Locator clicks can leave the long left input pane at the viewport.
      // Once a result exists, bring the compact v0.6 action summary under the
      // sticky header so the main decision is visible at 1280×720.
      requestAnimationFrame(()=>focusV06DecisionSummary());
      completeSuccessfulRound();
    }

    function analyzeContextWithSharedCore(ctx){
      const hasPriceInfo=ctx.avg!==null||ctx.goldTotal!==null||hasNumber(ctx.publicInfo?.goldGrid)||ctx.purpleAvg!==null||(ctx.goldGroups||[]).length||(ctx.knownPurple||[]).length||(ctx.purpleGroups||[]).length||(ctx.knownRed||[]).length||(ctx.redGroups||[]).length;
      if(ctx.q===null&&!hasPriceInfo){const d=workingDecision(ctx);return {analysis:{...ctx,candidateGs:ctx.goldCount!==null?[ctx.goldCount]:[],candidatePs:ctx.purple!==null?[ctx.purple]:[],predictedMin:d.low,predictedMax:d.high,redMin:ctx.redCount??ctx.minRed,redMax:ctx.redCount??null,observationOnly:true,lowInfo:true,workingDecision:d},inference:null};}
      const inference=solveStateInferenceSync(ctx,10),solverStatus=solverStatusFromResult(inference),chosenContext={...ctx,solverStatus,solverElapsedMs:inference.elapsed??null,solverSearchCompleted:inference.searchCompleted!==false,solverTruncated:inference.truncated===true,roundingMode:inference.chosenRoundingMode||ctx.roundingMode,requestedRoundingMode:ctx.roundingMode,roundingAudit:inference.roundingAudit||null,goldInference:inference.goldInference||null};
      if(solverStatus==="timeout")return {error:"timeout",analysis:{...chosenContext,timeout:true,frozenPrediction:null}};
      if(inference.goldOnly)return {...analyzeGoldOnly(chosenContext,inference.states,inference.purpleStates||[]),inference};
      return {...analyzeSolvedStateInference(chosenContext,inference.states),inference};
    }
    async function analyzeContextWithSharedCoreAsync(ctx){
      const hasPriceInfo=ctx.avg!==null||ctx.goldTotal!==null||hasNumber(ctx.publicInfo?.goldGrid)||ctx.purpleAvg!==null||(ctx.goldGroups||[]).length||(ctx.knownPurple||[]).length||(ctx.purpleGroups||[]).length||(ctx.knownRed||[]).length||(ctx.redGroups||[]).length;
      if(ctx.q===null&&!hasPriceInfo){const d=workingDecision(ctx);return {analysis:{...ctx,candidateGs:ctx.goldCount!==null?[ctx.goldCount]:[],candidatePs:ctx.purple!==null?[ctx.purple]:[],predictedMin:d.low,predictedMax:d.high,redMin:ctx.redCount??ctx.minRed,redMax:ctx.redCount??null,observationOnly:true,lowInfo:true,workingDecision:d},inference:null};}
      const inference=await solveStateInferenceAsync(ctx,10),solverStatus=solverStatusFromResult(inference),chosenContext={...ctx,solverStatus,solverElapsedMs:inference.elapsed??null,solverSearchCompleted:inference.searchCompleted!==false,solverTruncated:inference.truncated===true,roundingMode:inference.chosenRoundingMode||ctx.roundingMode,requestedRoundingMode:ctx.roundingMode,roundingAudit:inference.roundingAudit||null,goldInference:inference.goldInference||null};
      if(solverStatus==="timeout")return {error:"timeout",analysis:{...chosenContext,timeout:true,frozenPrediction:null}};
      if(inference.goldOnly)return {...analyzeGoldOnly(chosenContext,inference.states,inference.purpleStates||[]),inference};
      return {...analyzeSolvedStateInference(chosenContext,inference.states),inference};
    }

    function redCandidatesHtml(c,ctx){
      const redMin=c.red===null?c.rMin:c.red,redMax=c.red===null?c.rMax:c.red,known=ctx.knownRed||[];
      if(redMax===0)return '<aside class="candidate-red"><div class="candidate-red-head"><strong>红色藏品候选</strong><small>R=0</small></div><div class="red-candidate-note">该数量状态确认无红色藏品。</div></aside>';
      const used=new Map();known.forEach(x=>used.set(x.price,(used.get(x.price)||0)+1));
      const remainingMax=Math.max(0,redMax-known.length),possible=remainingMax?RED_ITEMS.filter(x=>(used.get(x[1])||0)<2):[];
      const knownHtml=known.length?`<div class="red-known"><strong>已知红色价格约束：</strong>${escapeHtml(known.map(x=>`${x.name}（${fmt(x.price)}）`).join(" + "))}</div>`:"";
      const previewLimit=18,preview=possible.slice(0,previewLimit),list=preview.map(x=>`<div class="red-candidate-item"><span>${escapeHtml(x[0])}</span><span>${fmt(x[1])}</span></div>`).join(""),omitted=possible.length>preview.length?`<div class="red-candidate-note">另有 ${possible.length-preview.length} 件图鉴候选已计入算法，详情列表仅展示前 ${preview.length} 件以保持页面流畅。</div>`:"";
      const countText=redMin===redMax?`R=${redMin}`:`R=${redMin}–${redMax}`,slotText=known.length>=redMax?"红色位置已由已知藏品填满。":`除已知件外，每个剩余红色位置都可能是下列藏品；同名最多按 2 件计算。`;
      return `<aside class="candidate-red"><div class="candidate-red-head"><strong>红色藏品可能为</strong><small>${countText}</small></div>${knownHtml}${list?`<div class="red-candidate-list">${list}</div>`:""}${omitted}<div class="red-candidate-note">${slotText} 这是图鉴可行集合，不代表概率排序。</div></aside>`;
    }
    function candidateHtml(c,open,ctx){
      const redPart=c.red===null?`R=${c.rMin}–${c.rMax}`:`R=${c.red}`,goldCountLabel=c.gold.matchCount??c.gold.matches.length,goldLabel=c.gold.unconstrained?(c.gold.matches.length?"金已知件约束":"金结构未测"):c.gold.truncated?`金候选≥${goldCountLabel}`:`金候选 ${goldCountLabel}`, purpleLabel=c.purple?(c.purple.unconstrained?"紫已知件约束":c.purple.truncated?"紫候选≥10":`紫候选 ${c.purple.matches.length}`):"";
      const goldCombos=c.gold.matches.slice(0,5).map(combo=>`<div class="combo"><div>${escapeHtml(comboName(combo,ctx))}</div><small>金色总价 ${fmt(combo.reduce((a,b)=>a+b,0))}${c.g?` · 均价 ${(combo.reduce((a,b)=>a+b,0)/c.g).toFixed(4)}`:""}</small></div>`).join("");
      const purpleCombos=c.purple?c.purple.matches.slice(0,4).map(combo=>`<div class="combo"><div class="purple-text">紫色价格：${combo.join(" + ")}</div><small>紫色总价 ${fmt(combo.reduce((a,b)=>a+b,0))} · 均价 ${(combo.reduce((a,b)=>a+b,0)/c.p).toFixed(4)}</small></div>`).join(""):"";
      return `<details class="candidate" ${open?"open":""}><summary><div class="candidate-title"><strong>G=${c.g}</strong><span class="badge purple">P=${c.p??"?"}</span><span class="badge red">${redPart}</span><small>${goldLabel}${purpleLabel?` · ${purpleLabel}`:""}</small></div><div class="candidate-range"><strong>${fmtWan(c.totalMin)} — ${fmtWan(c.totalMax)}</strong><small>紫金红理论范围</small></div></summary><div class="candidate-content"><div class="candidate-columns"><div class="candidate-main">${c.gold.truncated||c.purple?.truncated?'<p class="muted" style="font-size:11px">组合样本已为实战速度截断，不能用交集证明“必有”。</p>':""}${goldCombos||'<div class="combo"><div>未使用金色价格情报，仅保留数量与价格池边界。</div></div>'}${purpleCombos}</div>${redCandidatesHtml(c,ctx)}</div></div></details>`;
    }

    function weightedQuantile(entries,q=.5){
      const rows=entries.filter(x=>Number.isFinite(x.value)&&Number.isFinite(x.weight)&&x.weight>0).sort((a,b)=>a.value-b.value);if(!rows.length)return null;
      const total=rows.reduce((s,x)=>s+x.weight,0),target=total*q;let seen=0;for(const row of rows){seen+=row.weight;if(seen>=target)return row.value;}return rows.at(-1).value;
    }
    function hasNumber(value){return value!==null&&value!==undefined&&value!==""&&Number.isFinite(Number(value));}
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
    function historyTimestamp(value){
      if(value==null||value==="")return null;
      const raw=String(value).trim(), parsed=Date.parse(raw.includes("T")?raw:raw.replace(" ","T"));
      return Number.isFinite(parsed)?parsed:null;
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
    function eligibleHistory(ctx={},purpose="wholeValue"){
      const cutoff=historyTimestamp(ctx.playedAt),excludeId=ctx.excludeRecordId||ctx.id||null;
      return state.records.filter(r=>{
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
    function similarHistory(ctx,limit=8,purpose="wholeValue"){
      return eligibleHistory(ctx,purpose).map(r=>({record:r,...similarityFor(ctx,r)})).filter(x=>x.score>0).sort((a,b)=>b.score-a.score||(historyTimestamp(b.record.playedAt)||0)-(historyTimestamp(a.record.playedAt)||0)).slice(0,limit).map(x=>({...x,weight:Math.max(.01,(x.similarity/100)**2.4)}));
    }
    function boxIsUnknown(box){return !box||String(box).startsWith("未知");}
    function analogHistoryBundle(ctx,matches=similarHistory(ctx,12)){
      const rows=matches.filter(x=>x.similarity>=42&&Number(x.record.actualTotal)>0).map(x=>({value:Number(x.record.actualTotal),weight:x.weight,match:x}));
      if(!rows.length)return {n:0,effectiveN:0,p20:null,p50:null,p80:null,anchor:null,topSimilarity:0,exactBoxN:0,rows:[]};
      const sumW=rows.reduce((s,x)=>s+x.weight,0),sumW2=rows.reduce((s,x)=>s+x.weight*x.weight,0),exactBoxN=boxIsUnknown(ctx.box)?0:rows.filter(x=>x.match.record.box===ctx.box).length;
      const p20=weightedQuantile(rows,.2),p50=weightedQuantile(rows,.5),p80=weightedQuantile(rows,.8),topSimilarity=rows[0]?.match.similarity||0,topValue=rows[0]?.value;
      // 近乎同局的样本（同场/同箱/Q及主要仪器接近）比大组中位更有解释力，但最多占校准目标的 65%。
      const anchor=topSimilarity>=94&&Number.isFinite(topValue)?topValue*.65+p50*.35:p50;
      return {n:rows.length,effectiveN:sumW2?sumW*sumW/sumW2:0,p20,p50,p80,anchor,topSimilarity,exactBoxN,rows};
    }
    function chooseCohort(ctx){const matches=similarHistory(ctx,8);return {label:matches.length?"场地/箱型/Q 加权近邻":"无可用近邻",records:matches.map(x=>x.record),matches,confidence:matches.length>=5&&matches[0].similarity>=70?"初步":"低",level:matches.length?3:8};}
    function cohortStats(records){const v=records.map(r=>Number(r.actualTotal)).filter(x=>Number.isFinite(x)&&x>0);return v.length?{n:v.length,mean:mean(v),median:median(v),p25:quantile(v,.25),p75:quantile(v,.75),min:Math.min(...v),max:Math.max(...v)}:{n:0,mean:null,median:null,p25:null,p75:null,min:null,max:null};}
    function expectedPoolValue(count,known=[],average){if(!Number.isInteger(count)||count<known.length)return null;return known.reduce((s,x)=>s+x.price,0)+(count-known.length)*average;}
    function safeKnown(raw,items){try{return parseKnownItems(String(raw||""),items,"历史");}catch(_){return [];}}
    function derivedRecordCounts(r){
      let g=hasNumber(r.goldCount)&&Number.isInteger(Number(r.goldCount))?Number(r.goldCount):null,p=hasNumber(r.purpleCount)&&Number.isInteger(Number(r.purpleCount))?Number(r.purpleCount):null,red=hasNumber(r.redCount)&&Number.isInteger(Number(r.redCount))?Number(r.redCount):null,q=hasNumber(r.q)&&Number.isInteger(Number(r.q))?Number(r.q):null;
      if(q!==null){if(g===null&&p!==null&&red!==null)g=q-p-red;if(p===null&&g!==null&&red!==null)p=q-g-red;if(red===null&&g!==null&&p!==null)red=q-g-p;}return {g,p,red};
    }
    function historicalCountPrior(ctx){
      if(ctx._historyCountPrior)return ctx._historyCountPrior;
      const q=hasNumber(ctx.q)?Number(ctx.q):null,rows=eligibleHistory(ctx,"state").filter(r=>r.venue===ctx.venue&&(boxIsUnknown(ctx.box)?!boxIsUnknown(r.box):r.box===ctx.box)&&(q===null||!hasNumber(r.q)||Math.abs(Number(r.q)-q)<=2)).map(r=>derivedRecordCounts(r)).filter(x=>Number.isInteger(x.g));
      const prior={n:rows.length,g:rows.length?median(rows.map(x=>x.g)):null};
      try{Object.defineProperty(ctx,"_historyCountPrior",{value:prior,configurable:true});}catch(_){ctx._historyCountPrior=prior;}
      return prior;
    }
    function estimateRecordGoldPurple(r){
      const {g,p}=derivedRecordCounts(r),catalog=effectiveCatalog(r),goldTotal=scalarEffectiveTotal(r,"gold",r.goldTotal),goldAvg=scalarEffectiveAverage(r,"gold",r.goldAvg),purpleAvg=scalarEffectiveAverage(r,"purple",r.purpleAvg);let gold=null,purple=null;
      if(Number.isFinite(goldTotal)&&goldTotal>0)gold=goldTotal;
      else if(Number.isFinite(goldAvg)&&goldAvg>0&&Number.isInteger(g))gold=goldAvg*g;
      else if(Number.isInteger(g))gold=expectedPoolValue(g,adjustedKnownItems(r,"gold",safeKnown(r.knownGold,baseCatalogFor(r).gold)),catalogMedian(catalog.gold));
      if(Number.isFinite(purpleAvg)&&purpleAvg>0&&Number.isInteger(p))purple=purpleAvg*p;
      else if(Number.isInteger(p))purple=expectedPoolValue(p,adjustedKnownItems(r,"purple",safeKnown(r.knownPurple,baseCatalogFor(r).purple)),mean(catalog.purple.map(x=>Number(x[1]))));
      return {g,p,gold,purple};
    }
    function reconstructRecordResidual(r){
      if(!hasNumber(r.actualTotal)||Number(r.actualTotal)<=0)return null;
      const {gold,purple}=estimateRecordGoldPurple(r);if(gold===null||purple===null)return null;
      const residual=Number(r.actualTotal)-gold-purple;return residual>=-2500?Math.max(0,residual):null;
    }
    function boxBoostFactor(box=""){return RED_BOOST_BOX_RE.test(String(box||""))?1.25:1;}
    function softRedWorkingValue(r,boost=1,unit=RED_WORKING_AVG){
      // 工作估值里：第1件红按常见中位，后续件数快速衰减，避免“R=5就按50W红货”把整箱抬飞
      if(!Number.isInteger(r)||r<=0)return 0;
      let v=0; for(let i=1;i<=r;i++){ v += unit*boost*Math.pow(0.24, i-1); }
      return v;
    }
    function softRedTypical(r,boost=1,which="low",unitOverride=null){
      if(!Number.isInteger(r)||r<=0)return 0;
      const unit=unitOverride??(which==="high"?RED_TYPICAL_HIGH:RED_TYPICAL_LOW);
      let v=0; for(let i=1;i<=r;i++){ v += unit*boost*Math.pow(which==="high"?0.35:0.2, i-1); }
      return v;
    }
    function redPresenceRate(ctx){
      const base=RED_PRESENCE_PRIOR[ctx.venue]??RED_PRESENCE_PRIOR["未知场地"];
      return Math.min(.72, base*boxBoostFactor(ctx.box));
    }

    function valueStats(values){
      const v=values.map(Number).filter(x=>Number.isFinite(x)&&x>=0);
      return v.length?{n:v.length,p20:quantile(v,.2),p25:quantile(v,.25),p35:quantile(v,.35),p50:quantile(v,.5),p75:quantile(v,.75),p80:quantile(v,.8),mean:mean(v)}:null;
    }
    function historyBoxValue(ctx){
      const rows=eligibleHistory(ctx);
      if(!boxIsUnknown(ctx.box))return valueStats(rows.filter(r=>r.box===ctx.box).map(r=>r.actualTotal));
      // “未知箱型”不是一种真实箱型，而是同场地已知箱型的潜在混合。
      const q=hasNumber(ctx.q)?Number(ctx.q):null,mixed=rows.filter(r=>r.venue===ctx.venue&&!boxIsUnknown(r.box)&&(q===null||!hasNumber(r.q)||Math.abs(Number(r.q)-q)<=3));
      return valueStats(mixed.map(r=>r.actualTotal));
    }
    function historyVenueValue(ctx){return valueStats(eligibleHistory(ctx).filter(r=>r.venue===ctx.venue).map(r=>r.actualTotal));}
    function historyVenueQ(ctx){
      if(!hasNumber(ctx.q))return null;
      return valueStats(eligibleHistory(ctx).filter(r=>r.venue===ctx.venue&&Number(r.q)===Number(ctx.q)).map(r=>r.actualTotal));
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
    function redItemsText(r){return verifiedRedItemsText(r)||String(r?.redItems||r?.settlement?.recognizedItems||"").trim();}
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
    function historyBoxRed(ctx){
      const labels=eligibleHistory(ctx,"redDistribution").filter(r=>boxIsUnknown(ctx.box)?r.venue===ctx.venue&&!boxIsUnknown(r.box):r.box===ctx.box).map(historicalRedLabel).filter(Boolean);
      if(labels.length<2)return null;
      const totals=labels.map(x=>x.total).filter(Number.isFinite),positive=totals.filter(x=>x>0),p=valueStats(positive),zeroN=labels.filter(x=>x.count===0).length;
      return {n:labels.length,rawP0:zeroN/labels.length,jackpotRate:positive.length?positive.filter(x=>x>=500000).length/labels.length:0,meanCount:mean(labels.map(x=>x.count)),workRed:p?Math.min(160000,p.p35):0,lowRed:p?Math.min(72000,p.p20):0,highRed:p?Math.min(550000,p.p80):0};
    }
    function historySoftResidual(ctx){
      const all=eligibleHistory(ctx),stats=rows=>valueStats(rows.map(reconstructRecordResidual).filter(Number.isFinite));
      const box=stats(all.filter(r=>r.box===ctx.box));if(box&&box.n>=3)return box;
      const venue=stats(all.filter(r=>r.venue===ctx.venue));if(venue&&venue.n>=3)return venue;
      return stats(all);
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
    function weightedStats(entries){
      const rows=(entries||[]).filter(x=>Number.isFinite(Number(x.value))&&Number(x.weight)>0).map(x=>({value:Number(x.value),weight:Number(x.weight)}));
      if(!rows.length)return null;
      // Avoid spreading a large bootstrap/state mixture into Math.min/max;
      // low-information progressive inference may legitimately produce many
      // candidate samples and should remain computable without stack overflow.
      let min=Infinity,max=-Infinity;for(const row of rows){if(row.value<min)min=row.value;if(row.value>max)max=row.value;}
      return {n:rows.length,p05:weightedQuantile(rows,.05),p10:weightedQuantile(rows,.10),p20:weightedQuantile(rows,.20),p25:weightedQuantile(rows,.25),p50:weightedQuantile(rows,.50),p75:weightedQuantile(rows,.75),p80:weightedQuantile(rows,.80),p90:weightedQuantile(rows,.90),p95:weightedQuantile(rows,.95),min,max,weight:rows.reduce((s,x)=>s+x.weight,0)};
    }
    function redProbabilityProfile(ctx,states=[],componentRows=[]){
      const shared = (typeof AuctionEngineV06 !== "undefined" && AuctionEngineV06.buildProbabilityProfile)
        || (typeof ShadowProfileV06 !== "undefined" && ShadowProfileV06.buildProbabilityProfile)
        || null;
      if (shared) {
        return shared(ctx, states, {
          records: state.records,
          componentRows,
          stateComponentsFn: stateComponents
        });
      }
      const collectRows=(rows)=>rows.map(match=>{
        const label=historicalRedLabel(match.record||match);
        if(!label||!label.items?.length)return null;
        const weight=Number(match.weight)>0?Number(match.weight):1;
        const values=label.items.map(item=>({value:Number(item.price),weight})).filter(x=>Number.isFinite(x.value)&&x.value>0);
        return values.length?{record:match.record||match,label,weight,similarity:Number(match.similarity)||0,values,total:values.reduce((s,x)=>s+x.value,0)}:null;
      }).filter(Boolean);
      let rows=collectRows(similarHistory(ctx,32,"redDistribution").filter(x=>x.similarity>=35));
      let source="同场/同箱/Q近邻";
      if(rows.length<3){
        rows=collectRows(eligibleHistory(ctx,"redDistribution").filter(r=>r.venue===ctx.venue));
        source="同场地历史";
      }
      if(rows.length<3){
        rows=collectRows(eligibleHistory(ctx,"redDistribution"));
        source="全历史已验证红货";
      }
      // 当前近邻用于单件兜底；同 R 的完整红货列表另从全部“当时已发生”的历史中补齐，避免被 Top-32 相似度截掉。
      const directRanked=eligibleHistory(ctx,"redDistribution").map(record=>{const sim=similarityFor(ctx,record);return {record,similarity:sim.similarity,weight:Math.max(.01,(sim.similarity/100)**2.4)};});
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
        const w=Math.max(.01,candidateStateWeight(s,ctx)),min=Number.isInteger(s?.r)?Number(s.r):Number.isInteger(s?.rMin)?Number(s.rMin):null,max=Number.isInteger(s?.r)?Number(s.r):Number.isInteger(s?.rMax)?Number(s.rMax):null;
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
        return {g:Number.isInteger(s?.g)?Number(s.g):null,p:Number.isInteger(s?.p)?Number(s.p):null,r:Number.isInteger(s?.r)?Number(s.r):null,rMin,rMax,weight:Math.max(.01,candidateStateWeight(s,ctx))};
      }).filter(x=>x.rMin!==null);
      const candidateWeightTotal=stateCandidateSource.reduce((sum,x)=>sum+x.weight,0)||1;
      const stateCandidates=stateCandidateSource.map(s=>{
        const redRows=stateDistributions.filter(x=>x.r>=s.rMin&&x.r<=s.rMax),exact=redRows.length===1&&s.rMin===s.rMax?redRows[0]:null;
        return {...s,relativeWeight:s.weight/candidateWeightTotal,red:exact?.stats||null,redMode:exact?.mode||null,redByR:redRows.map(x=>({r:x.r,stats:x.stats,mode:x.mode,directGames:x.directGames,bootstrapN:x.bootstrapN}))};
      });
      const componentForState=s=>{
        const hit=(componentRows||[]).find(row=>row?.state&&Number(row.state.g)===s.g&&Number(row.state.p)===s.p&&Number(row.state.r)===s.r);
        return hit?.component||stateComponents(ctx,s);
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
    function detectInfoMode(ctx){
      const hasQ=hasNumber(ctx.q), hasGAvg=hasNumber(ctx.avg), hasGTot=hasNumber(ctx.goldTotal), hasP=hasNumber(ctx.purple), hasPAvg=hasNumber(ctx.purpleAvg),hasNamedGold=(ctx.knownGold||[]).length>0||(ctx.goldGroups||[]).length>0,hasNamedPurple=(ctx.knownPurple||[]).length>0||(ctx.purpleGroups||[]).length>0,hasNamedRed=(ctx.knownRed||[]).length>0||(ctx.redGroups||[]).length>0;
      if(hasGTot) return {id:"goldTotal", title:"金总硬约束模式", desc:"金色总价是铁下限；估值与保本都不得逻辑上低于它。", tone:"gold"};
      if(hasGAvg&&hasP&&hasQ) return {id:"goldAvgPurple", title:"主路径：Q + 紫数 + 金均", desc:"当前信息最稳的组合。工作估值看分项，保守防亏线优先防亏；推荐上限与高风险尝试线只说明追价代价。", tone:"mint"};
      if(hasGAvg&&hasQ) return {id:"goldAvgOnly", title:"金均模式（紫数未知）", desc:"只能锁金色池，紫色/红色靠箱型历史与残值，保本会更保守。", tone:"blue"};
      if(hasQ&&hasNamedGold) return {id:"knownGold", title:"已知金藏品模式", desc:"名称/二选一只形成价值下限；金件数未知时，组合中心必须接受同箱历史校准。", tone:"gold"};
      if(hasQ&&hasNamedRed) return {id:"knownRed", title:"已知红藏品模式", desc:"看见的红货进入硬下限；其余红数仍保持未知。", tone:"red"};
      if(hasPAvg&&hasGAvg) return {id:"dualAvg", title:"双均价模式", desc:"金均+紫均可估两池，红仍靠历史箱型。", tone:"purple"};
      if(hasQ&&!hasGAvg&&!hasGTot) return {id:"onlyQ", title:hasP||hasPAvg||hasNamedGold||hasNamedPurple||hasNamedRed?"低信息：Q / 数量情报（无金价）":"低信息：只有 Q", desc:"Q、紫数、最低数量和已见藏品都会使用；但没有金色价格证据，仍主要靠场地/箱型历史分位，宁可不拍。", tone:"warn"};
      if(!hasQ&&(hasGAvg||hasGTot||hasPAvg)) return {id:"noQ", title:"无 Q 分池模式", desc:"没有总数时只分池估，整箱合成置信度低。", tone:"warn"};
      return {id:"mixed", title:"混合情报", desc:"按已给字段强弱融合；缺的用历史先验补，不把单局极端总价硬灌进来。", tone:"muted"};
    }
    function infoModeHtml(mode){
      if(!mode) return "";
      return `<div class="info-mode ${mode.tone||""}"><div class="info-mode-kicker">当前情报模式</div><strong>${escapeHtml(mode.title)}</strong><p>${escapeHtml(mode.desc)}</p></div>`;
    }

    function lowTierEstimate(ctx){
      const pi=ctx.publicInfo||{},venuePrior=LOW_TIER_PRIOR[ctx.venue]??LOW_TIER_PRIOR["未知场地"],parts=[],exactParts=[];let observedColors=0;
      for(const [key,label,rateGrid,rateItem] of [["blue","蓝",LOW_TIER_GRID_RATE.blue,LOW_TIER_ITEM_RATE.blue],["green","绿",LOW_TIER_GRID_RATE.green,LOW_TIER_ITEM_RATE.green],["white","白",LOW_TIER_GRID_RATE.white,LOW_TIER_ITEM_RATE.white]]){
        const countRaw=pi[key+"Count"],gridRaw=pi[key+"Grid"],avgRaw=pi[key+"Avg"],count=hasNumber(countRaw)?Number(countRaw):null,grid=hasNumber(gridRaw)?Number(gridRaw):null,avg=hasNumber(avgRaw)?Number(avgRaw):null;
        if(count!==null&&count>=0&&avg!==null&&avg>0){parts.push(count*avg);exactParts.push(count*avg);observedColors++;continue;}
        if(grid!==null&&grid>=0){parts.push(grid*rateGrid);observedColors++;continue;}
        if(count!==null&&count>=0){parts.push(count*rateItem);observedColors++;continue;}
      }
      let direct=parts.length?parts.reduce((a,b)=>a+b,0):null;
      const totalItems=hasNumber(pi.totalItems)?Number(pi.totalItems):null,q=hasNumber(ctx.q)?Number(ctx.q):null,knownLow=[pi.blueCount,pi.greenCount,pi.whiteCount].filter(hasNumber).map(Number).reduce((a,b)=>a+b,0);
      const totalGrid=hasNumber(pi.totalGrid)?Number(pi.totalGrid):null;
      const usedGrid=[pi.goldGrid,pi.purpleGrid,pi.blueGrid,pi.greenGrid,pi.whiteGrid].filter(hasNumber).map(Number).reduce((a,b)=>a+b,0);
      const singleAvg=hasNumber(pi.singleAvg)?Number(pi.singleAvg):null;
      const nineAvg=hasNumber(pi.nineAvg)?Number(pi.nineAvg):null;
      if(totalItems!==null&&q!==null&&totalItems>=q){const remaining=Math.max(0,totalItems-q-knownLow),pooled=(40*LOW_TIER_ITEM_RATE.blue+30*LOW_TIER_ITEM_RATE.green+20*LOW_TIER_ITEM_RATE.white)/90;direct=(direct??0)+remaining*pooled;}
      else if(direct!==null&&observedColors<3)direct+=venuePrior*(3-observedColors)/3*.55;
      if(singleAvg!=null && totalGrid!=null){
        const restGrid=Math.max(0, totalGrid - usedGrid);
        const gridResidual=restGrid>0 ? restGrid*singleAvg*0.55 : totalGrid*singleAvg*0.12;
        direct = direct==null ? gridResidual : Math.max(direct, direct*0.65 + gridResidual*0.35);
      } else if(nineAvg!=null){
        const weak=nineAvg*1.1;
        direct = direct==null ? Math.min(venuePrior*1.3, weak) : (direct*0.8 + Math.min(weak, venuePrior*1.5)*0.2);
      }
      const residualRows=similarHistory(ctx,24).map(x=>({value:reconstructRecordResidual(x.record),weight:x.weight})).filter(x=>Number.isFinite(x.value));
      const residualMedian=weightedQuantile(residualRows,.45),n=residualRows.length;
      const base=direct??venuePrior;
      let estimate=base;
      if(direct===null&&residualMedian!==null){const shrink=Math.min(.55,n/(n+10));estimate=base*(1-shrink)+Math.min(residualMedian*.22,venuePrior*2.8)*shrink;}
      const hardLower=exactParts.reduce((a,b)=>a+b,0);
      return {mid:Math.max(0,estimate),lower:Math.max(0,hardLower),upper:Math.max(estimate*1.8,hardLower),typicalLow:Math.max(0,estimate*.6),typicalHigh:estimate*1.45,source:direct!==null?(exactParts.length?"蓝绿白件数×均价/格数":"蓝绿白格数/件数"):n?("历史残值收缩校准("+n+")"):"场地低品质先验",residualMedian,residualN:n};
    }
    function historyResidualBundle(ctx){
      const rows=similarHistory(ctx,16).map(x=>{
        const residual=reconstructRecordResidual(x.record);
        return residual===null?null:{value:residual,weight:x.weight,actual:Number(x.record.actualTotal),sim:x.similarity};
      }).filter(Boolean);
      if(!rows.length)return {n:0,mid:null,p20:null,p50:null,p80:null};
      return {n:rows.length,mid:weightedQuantile(rows,.5),p20:weightedQuantile(rows,.2),p50:weightedQuantile(rows,.5),p80:weightedQuantile(rows,.8),rows};
    }
    function adjustedKnownItems(ctx,rarity,known=[]){const multiplier=conditionPriceMultiplier(ctx,rarity);return (known||[]).map(item=>({...item,price:Number(item.price)*multiplier}));}
    function scalarEffectiveAverage(ctx,rarity,value){const candidates=effectiveAverageCandidates(ctx,rarity,value);return candidates.length===1&&Number.isFinite(candidates[0])?candidates[0]:null;}
    function scalarEffectiveTotal(ctx,rarity,value){const candidates=effectiveTotalCandidates(ctx,rarity,value);return candidates.length===1&&Number.isFinite(candidates[0])?candidates[0]:null;}
    function redCatalogPrior(ctx){const items=baseCatalogFor(ctx).red||RED_ITEMS,common=items.filter(x=>Number(x[1])<400000),jackpot=items.filter(x=>Number(x[1])>=400000),prices=common.map(x=>Number(x[1]));return {working:median(prices)??RED_WORKING_AVG,low:quantile(prices,.25)??RED_TYPICAL_LOW,high:quantile(prices,.75)??RED_TYPICAL_HIGH,jackpotAvg:mean(jackpot.map(x=>Number(x[1])))||RED_JACKPOT_AVG};}
    function stateComponents(ctx,state){
      const catalog=effectiveCatalog(ctx),knownGold=adjustedKnownItems(ctx,"gold",ctx.knownGold||[]),knownPurple=adjustedKnownItems(ctx,"purple",ctx.knownPurple||[]),knownRed=ctx.knownRed||[],rawG=state.g??ctx.goldCount,rawP=state.p??ctx.purple,rawR=state.r??ctx.redCount;
      if(![rawG,rawP,rawR].every(hasNumber))return null;
      const g=Number(rawG),p=Number(rawP),r=Number(rawR);
      if(![g,p,r].every(Number.isInteger)||[g,p,r].some(x=>x<0))return null;
      const sumMatches=s=>s?.matches?.map(c=>c.reduce((a,b)=>a+b,0))||[],goldMatches=sumMatches(state.gold),purpleMatches=sumMatches(state.purple),pi=ctx.publicInfo||{};
      const effectiveGoldAvg=scalarEffectiveAverage(ctx,"gold",ctx.avg),effectivePurpleAvg=scalarEffectiveAverage(ctx,"purple",ctx.purpleAvg),effectiveGoldTotal=scalarEffectiveTotal(ctx,"gold",ctx.goldTotal);
      let goldMid,goldLower,goldUpper,goldSource;
      if(Number.isFinite(effectiveGoldTotal)){goldMid=goldLower=goldUpper=effectiveGoldTotal;goldSource="金色总价(条件后硬约束)";}
      else if(goldMatches.length&&!state.gold?.unconstrained&&!state.gold?.groupOnly){goldMid=median(goldMatches);goldLower=state.goldMin??Math.min(...goldMatches);goldUpper=state.goldMax??Math.max(...goldMatches);goldSource="v4离散组合";}
      else if(Number.isFinite(effectiveGoldAvg)){goldMid=effectiveGoldAvg*g;goldLower=state.goldMin??state.gold?.low??Math.max(0,g*(effectiveGoldAvg-.5));goldUpper=state.goldMax??state.gold?.high??g*(effectiveGoldAvg+.5);goldSource="金色条件后均价×件数";}
      else {const itemPrior=expectedPoolValue(g,knownGold,catalogMedian(catalog.gold)),gridPrior=hasNumber(pi.goldGrid)?Number(pi.goldGrid)*catalogPerGridMedian(catalog.gold):null;goldMid=gridPrior===null?itemPrior:(itemPrior*0.62+gridPrior*0.38);goldLower=state.goldMin??constrainedExtreme(catalog.gold,g,knownGold,false);goldUpper=state.goldMax??constrainedExtreme(catalog.gold,g,knownGold,true);goldSource=gridPrior===null?"金色有效图鉴中位先验":"金件数+金格数有效先验";}
      let purpleMid,purpleLower,purpleUpper,purpleSource;
      if(purpleMatches.length&&!state.purple?.unconstrained&&!state.purple?.groupOnly){purpleMid=median(purpleMatches);purpleLower=state.purpleMin??Math.min(...purpleMatches);purpleUpper=state.purpleMax??Math.max(...purpleMatches);purpleSource="紫色均价离散组合";}
      else if(Number.isFinite(effectivePurpleAvg)){purpleMid=effectivePurpleAvg*p;purpleLower=state.purpleMin??state.purple?.low??Math.max(0,p*(effectivePurpleAvg-.5));purpleUpper=state.purpleMax??state.purple?.high??p*(effectivePurpleAvg+.5);purpleSource="紫色条件后均价×件数";}
      else {const effectivePurpleMean=mean(catalog.purple.map(x=>Number(x[1]))),itemPrior=expectedPoolValue(p,knownPurple,effectivePurpleMean),gridPrior=hasNumber(pi.purpleGrid)?Number(pi.purpleGrid)*catalogPerGridMedian(catalog.purple):null;purpleMid=gridPrior===null?itemPrior:(itemPrior*0.65+gridPrior*0.35);purpleLower=state.purpleMin??constrainedExtreme(catalog.purple,p,knownPurple,false);purpleUpper=state.purpleMax??constrainedExtreme(catalog.purple,p,knownPurple,true);purpleSource=knownPurple.length===p?"已知紫色条件后合计":gridPrior===null?"紫色有效图鉴均值先验":"紫件数+紫格数有效先验";if(knownPurple.length===p)purpleMid=knownPurple.reduce((s,x)=>s+x.price,0);}
      const knownRedTotal=knownRed.reduce((s,x)=>s+x.price,0),redRemaining=Math.max(0,r-knownRed.length);
      const redHardLower=knownRedTotal;
      const boost=boxBoostFactor(ctx.box),redPrior=redCatalogPrior(ctx);
      const redLocked=hasNumber(ctx.redCount)&&Number.isInteger(Number(ctx.redCount));
      const boxRed=historyBoxRed(ctx);
      const softRes=historySoftResidual(ctx);
      let redMid, redTypicalLow, redTypicalHigh, redUpper, redSourceExtra="";
      if(redLocked){
        redMid=knownRedTotal+redRemaining*redPrior.working*boost;
        redTypicalLow=knownRedTotal+redRemaining*redPrior.low;
        redTypicalHigh=knownRedTotal+redRemaining*redPrior.high*boost;
        redUpper=knownRedTotal+redRemaining*Math.min(redPrior.high*boost*1.8+redPrior.jackpotAvg*0.05,1.5e6);
        redSourceExtra="红数已锁定";
      } else {
        const soft=softRedWorkingValue(redRemaining,boost,redPrior.working);
        const boxWork=boxRed?boxRed.workRed*boost:null;
        const resMid=softRes?softRes.p50:null;
        const fromRes=resMid!=null?resMid*0.70:null;
        const cands=[soft];
        if(boxWork!=null) cands.push(boxWork);
        if(fromRes!=null) cands.push(fromRes);
        redMid=knownRedTotal + cands.reduce((a,b)=>a+b,0)/cands.length;
        redTypicalLow=knownRedTotal + Math.min(soft*0.55, boxRed?boxRed.lowRed:soft*0.5, fromRes!=null?fromRes*0.45:soft*0.5);
        redTypicalHigh=knownRedTotal + Math.max(soft*1.35, boxRed?boxRed.highRed:soft*1.5, fromRes!=null?fromRes*1.25:soft*1.3);
        redUpper=knownRedTotal + Math.min(Math.max(redTypicalHigh*1.3, (boxRed?.highRed||0)*1.1), 1.8e6);
        redSourceExtra=boxRed?("箱型红先验n="+boxRed.n):(softRes?("残值校准n="+softRes.n):"软红衰减");
      }
      const redLower=redHardLower;
      const lowTier=lowTierEstimate(ctx);
      if([goldMid,goldLower,goldUpper,purpleMid,purpleLower,purpleUpper,redMid].some(x=>!Number.isFinite(x)))return null;
      const systemFloor=(hasNumber(pi.systemEstimate)&&Number(pi.systemEstimate)>0)?Number(pi.systemEstimate):0;
      const hardLower=Math.max(systemFloor, goldLower + Math.max(0,purpleLower) + redHardLower + lowTier.lower);
      const total=goldMid+purpleMid+redMid+lowTier.mid;
      return {
        total:Math.max(total,hardLower),
        hardLower,
        typicalLow:Math.max(hardLower, goldLower+Math.max(0,purpleLower)*.85+redTypicalLow+lowTier.typicalLow),
        typicalHigh:Math.max(total, goldUpper+purpleUpper+redTypicalHigh+lowTier.typicalHigh),
        gold:{mid:goldMid,lower:goldLower,upper:goldUpper,source:goldSource},
        purple:{mid:purpleMid,lower:purpleLower,upper:purpleUpper,source:purpleSource},
        red:{mid:redMid,lower:redLower,upper:redUpper,typicalLow:redTypicalLow,typicalHigh:redTypicalHigh,source:redLocked&&knownRed.length===r?"已知红色合计":(redSourceExtra||(redRemaining?("常见红×"+redRemaining):"红数未知"))},
        lowTier
      };
    }
    function stateWorkingValue(ctx,state){return stateComponents(ctx,state)?.total??null;}
    function maxPlausibleGoldCount(ctx){
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
      const boxV=historyBoxValue(ctx);
      const ceiling=boxV&&boxV.n>=2 ? Math.max(boxV.p80*1.25, boxV.p50*2.0, avg*1.2) : avg*6;
      gMax=Math.min(gMax, Math.max(ctx.minGold||1, Math.floor(ceiling/avg + 0.25)));
      return Math.max(ctx.minGold||1, gMax);
    }
    function candidateStateWeight(state,ctx={}){
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
        const gCap=maxPlausibleGoldCount(ctx);
        if(gCap!=null && g>gCap) w*=0.02;
      }
      // 同场同箱且 Q 接近的历史若有结算金件数，只作温和先验；不能覆盖本局硬证据。
      if(Number.isInteger(g)){
        const countPrior=historicalCountPrior(ctx);
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
    function summarizeBreakdown(componentRows){
      const part=key=>{const rows=componentRows.map(x=>({part:x.component[key],weight:x.weight})).filter(x=>x.part);if(!rows.length)return null;return {
        mid:weightedQuantile(rows.map(x=>({value:x.part.mid,weight:x.weight})),.5),
        lower:Math.min(...rows.map(x=>x.part.lower)),
        upper:Math.max(...rows.map(x=>x.part.upper)),
        typicalLow:weightedQuantile(rows.map(x=>({value:x.part.typicalLow??x.part.lower,weight:x.weight})),.35),
        typicalHigh:weightedQuantile(rows.map(x=>({value:x.part.typicalHigh??x.part.upper,weight:x.weight})),.7),
        source:rows[0].part.source
      };};
      return {gold:part("gold"),purple:part("purple"),red:part("red"),lowTier:part("lowTier")};
    }
        function textImpliesRedZero(text=""){
      const t=String(text||"");
      if(!t.trim()) return false;
      if(/(确认)?无红|没有红|红\s*[=:：]?\s*0|R\s*[=:：]?\s*0|一个没有\s*[,，]?\s*0|红货\s*0|0\s*红/.test(t)) return true;
      if(/红色\s*(没有|为0|是0)/.test(t)) return true;
      return false;
    }
    function maybeLockRedZero(ctx){
      if(!ctx||hasNumber(ctx.redCount)) return ctx;
      const blob=[ctx.knownRedRaw, ctx.publicInfo&&ctx.publicInfo.note, ctx.publicNote].filter(Boolean).join(" ");
      if(textImpliesRedZero(blob)) return Object.assign({}, ctx, {redCount:0, minRed:0});
      return ctx;
    }
    function parsePriceTokens(raw){
      // "76008*2+50000*2+101860" or "76008 ×2 , 50000"
      if(!raw||!String(raw).trim()) return [];
      const s=String(raw).replace(/[×xX]/g,"*").replace(/,/g,"");
      const out=[];
      for(const m of s.matchAll(/(\d{3,9})(?:\s*\*\s*(\d{1,2}))?/g)){
        const price=Number(m[1]), n=m[2]?Number(m[2]):1;
        if(!Number.isFinite(price)||price<=0||!Number.isInteger(n)||n<1) continue;
        for(let i=0;i<n;i++) out.push(price);
      }
      return out;
    }
    function lookupCatalog(price, items){
      const hit=items.find(x=>x[1]===price);
      return hit?{name:hit[0],price:hit[1],size:hit[2]}:{name:String(price),price,size:"?"};
    }
    /** 只从本局推演时已公开的文本提取情报；结算 redItems/notes 永远不能反向进入预测。 */
    function enrichContextFromIntel(ctx){
      if(!ctx) return ctx;
      let c=Object.assign({}, ctx);
      c.knownRed=Array.isArray(c.knownRed)?c.knownRed.slice():[];
      c.knownPurple=Array.isArray(c.knownPurple)?c.knownPurple.slice():[];
      c.knownGold=Array.isArray(c.knownGold)?c.knownGold.slice():[];
      c.publicInfo=Object.assign({}, c.publicInfo||{});
      const blob=[c.knownRedRaw, c.publicInfo.note, c.publicNote].filter(Boolean).join(" | ");

      // 1) explicit no-red
      if(!hasNumber(c.redCount) && textImpliesRedZero(blob)){
        c.redCount=0; c.minRed=0;
      }

      // 2) parse red price tokens from free text (ignore tiny numbers)
      const redRawHasAmbiguity=/\//.test(String(c.knownRedRaw||""));
      if(c.knownRed.length===0&&!redRawHasAmbiguity){
        const prices=parsePriceTokens(blob).filter(p=>p>=20000); // reds are high; filter noise
        // prefer prices that exist in RED catalog OR are >= min common red
        const redLike=prices.filter(p=>{
          if(RED_ITEMS.some(x=>x[1]===p)) return true;
          const commonMin=Math.min(...RED_COMMON_PRICES);
          return p>=commonMin*0.85;
        });
        if(redLike.length){
          c.knownRed=redLike.map(p=>lookupCatalog(p, RED_ITEMS));
          if(!hasNumber(c.redCount)) c.redCount=c.knownRed.length;
          c.minRed=Math.max(c.minRed||0, c.knownRed.length);
        }
      }

      // 3) if redCount locked 0, drop soft known red
      if(hasNumber(c.redCount) && Number(c.redCount)===0){
        c.knownRed=[]; c.minRed=0;
      }

      // 4) gold total from avg*count if both present and no goldTotal
      if(!hasNumber(c.goldTotal) && hasNumber(c.avg) && hasNumber(c.goldCount)){
        // not set as hard total (avg*count is soft); leave goldTotal empty
      }

      // 5) mark enrichment
      c._enriched=true;
      c._enrichNote=[
        hasNumber(c.redCount)?("R="+c.redCount):null,
        c.knownRed.length?("knownRed="+c.knownRed.length):null
      ].filter(Boolean).join(",");
      return c;
    }
    function expandStatesForValuation(ctx, states){
      if(!Array.isArray(states)||!states.length) return [];
      const q=hasNumber(ctx.q)?Number(ctx.q):null;
      const out=[];
      const pushUnique=(s)=>{
        if(!Number.isInteger(s.g)||!Number.isInteger(s.p)||!Number.isInteger(s.r)) return;
        if(q!=null && s.g+s.p+s.r!==q) return;
        if(s.g<0||s.p<0||s.r<0) return;
        if(hasNumber(ctx.goldCount)&&s.g!==Number(ctx.goldCount)) return;
        if(hasNumber(ctx.purple)&&s.p!==Number(ctx.purple)) return;
        if(hasNumber(ctx.redCount)&&s.r!==Number(ctx.redCount)) return;
        if(s.g<(ctx.minGold||0)||s.p<(ctx.minPurple||0)||s.r<(ctx.minRed||0)) return;
        out.push(s);
      };
      for(const s of states){
        if(Number.isInteger(s.p)&&Number.isInteger(s.r)&&Number.isInteger(s.g)){
          pushUnique(Object.assign({}, s, {rMin:s.r, rMax:s.r}));
          continue;
        }
        if(!Number.isInteger(s.g) || q==null) continue;
        if(Number.isFinite(ctx.avg)){
          const gCap=maxPlausibleGoldCount(ctx);
          if(gCap!=null && s.g>gCap) continue;
        }
        const rest=q-s.g;
        if(rest<0) continue;
        const pMin=Math.max(ctx.minPurple||0,0);
        const rMin=Math.max(ctx.minRed||0,0);
        const pFixed=hasNumber(ctx.purple)?Number(ctx.purple):null;
        const rFixed=hasNumber(ctx.redCount)?Number(ctx.redCount):null;
        const gold=s.gold||{unconstrained:true,matches:[],low:null,high:null};
        if(pFixed!=null){
          const r=rest-pFixed;
          if(r>=rMin) pushUnique(Object.assign({}, s, {g:s.g,p:pFixed,r,rMin:r,rMax:r,gold,purple:s.purple||{unconstrained:true,matches:[]},red:null}));
          continue;
        }
        if(rFixed!=null){
          const p=rest-rFixed;
          if(p>=pMin) pushUnique(Object.assign({}, s, {g:s.g,p,r:rFixed,rMin:rFixed,rMax:rFixed,gold,purple:{unconstrained:true,matches:[]},red:null}));
          continue;
        }
        const maxP=rest-rMin;
        if(maxP<pMin) continue;
        const boxRed=historyBoxRed(ctx);
        const expR=boxRed&&Number.isFinite(boxRed.meanCount)?Math.round(boxRed.meanCount):1;
        const candP=new Set();
        for(let r=rMin;r<=Math.min(rest-pMin, rMin+4);r++) candP.add(rest-r);
        candP.add(pMin); candP.add(maxP); candP.add(Math.round((pMin+maxP)/2));
        candP.add(rest-Math.min(Math.max(rMin,expR), rest-pMin));
        candP.add(rest-Math.min(Math.max(rMin,0), rest-pMin));
        for(const p of candP){
          if(!Number.isInteger(p)||p<pMin||p>maxP) continue;
          const r=rest-p;
          if(r<rMin) continue;
          pushUnique(Object.assign({}, s, {g:s.g,p,r,rMin:r,rMax:r,gold,purple:{unconstrained:true,matches:[]},red:null, residualSplit:true}));
        }
      }
      if(out.length) return out;
      return states.filter(s=>Number.isInteger(s.g)&&Number.isInteger(s.p)&&Number.isInteger(s.r));
    }
    function syntheticGoldAvgBreakdown(ctx, states){
      const avg=scalarEffectiveAverage(ctx,"gold",ctx.avg);if(!Number.isFinite(avg)||!hasNumber(ctx.q)) return null;
      const q=Number(ctx.q),catalog=effectiveCatalog(ctx),purpleMean=mean(catalog.purple.map(x=>Number(x[1]))),purpleMin=Math.min(...catalog.purple.map(x=>Number(x[1]))),purpleMax=Math.max(...catalog.purple.map(x=>Number(x[1])));
      const gMin=Math.max(ctx.minGold||1, hasNumber(ctx.goldCount)?Number(ctx.goldCount):1);
      const gCap=maxPlausibleGoldCount(ctx);
      const gMax=hasNumber(ctx.goldCount)?Number(ctx.goldCount):Math.min(q-(ctx.minPurple||0)-(ctx.minRed||0), gCap!=null?gCap:8, 12);
      if(gMax<gMin) return null;
      const gs=states&&states.length?[...new Set(states.map(s=>s.g).filter(Number.isInteger))]:null;
      const gList=(gs&&gs.length)?gs:Array.from({length:gMax-gMin+1},(_,i)=>gMin+i);
      const goldMids=gList.map(g=>avg*g);
      const goldMid=median(goldMids);
      const goldLower=Math.min(...gList.map(g=>Math.max(0,g*(avg-0.5))));
      const goldUpper=Math.max(...gList.map(g=>g*(avg+0.5)));
      const restMed=median(gList.map(g=>q-g));
      const p=Math.max(ctx.minPurple||0, Math.round(restMed*0.62));
      const r=Math.max(ctx.minRed||0, Math.round(restMed-p));
      const boost=boxBoostFactor(ctx.box);
      const redPrior=redCatalogPrior(ctx),redMid=hasNumber(ctx.redCount)&&Number(ctx.redCount)===0?0:softRedWorkingValue(Math.max(r, ctx.minRed||0), boost,redPrior.working);
      const low=lowTierEstimate(ctx);
      return {
        gold:{mid:goldMid,lower:Math.max(0,goldLower),upper:goldUpper,typicalLow:goldMid*0.92,typicalHigh:goldMid*1.08,source:"金均×候选G（结构展开）"},
        purple:{mid:p*purpleMean,lower:p*purpleMin,upper:p*purpleMax,typicalLow:p*purpleMin,typicalHigh:p*quantile(catalog.purple.map(x=>Number(x[1])),.7),source:"条件后残值紫份额先验"},
        red:{mid:redMid,lower:0,upper:Math.max(softRedTypical(Math.max(r,1),boost,"high",redPrior.high)*8, 5e5),typicalLow:softRedTypical(Math.max(r,0),boost,"low",redPrior.low),typicalHigh:softRedTypical(Math.max(r,0),boost,"high",redPrior.high),source:redMid===0?"已锁 R=0":"残值软红（常见，不含大奖）"},
        lowTier:low
      };
    }
    function jackpotRiskHtml(d){
      const red=d&&d.breakdown&&d.breakdown.red;
      const center=d&&d.center, high=d&&d.high;
      const jackpotish=(red&&Number.isFinite(red.upper)&&Number.isFinite(red.mid)&&red.upper>Math.max(red.mid*10, 2e6)) || (Number.isFinite(high)&&Number.isFinite(center)&&high>center*2.8);
      if(!jackpotish) return "";
      return `<div class="callout" style="margin-top:10px;border-color:#fecdd3;background:#fff1f2"><span class="dot" style="background:#e11d48"></span><div><strong>红货长尾警告：</strong>工作估值里的红色是<strong>常见红</strong>，不含千万级大奖期望。若相似历史出现超高实际总价，那是尾部事件——要追奖别拿中心价当真值；防守线请展开<strong>决策细节</strong>查看。</div></div>`;
    }

    function qBucketV06(q){const n=Number(q);return !Number.isFinite(n)?"unknown":n<=9?"Q1-9":n<=15?"Q10-15":n<=25?"Q16-25":"Q26+";}
    function empiricalStatePriorV06(ctx,states=[]){
      const candidateStates=(states||[]).filter(s=>Number.isInteger(s?.g)&&Number.isInteger(s?.p)&&(Number.isInteger(s?.r)||Number.isInteger(s?.rMin))),now=historyTimestamp(ctx?.playedAt),condition=canonicalFieldConditionId(ctx?.fieldCondition||"unknown"),box=String(ctx?.box||"未知箱型"),venue=String(ctx?.venue||"未知场地"),qBucket=qBucketV06;
      if(now===null)return {version:"v0.6-shadow",status:"no-date",localN:0,parentN:0,shrinkageWeight:0,fallbackLevel:"global",candidateWeights:[],rQuantity:{domain:[],probabilities:[],localN:0,parentN:0,shrinkageWeight:0,fallbackLevel:"global"}};
      const allowed=Array.isArray(ctx?.allowedHistoryIds)?new Set(ctx.allowedHistoryIds):null,history=state.records.map(r=>{const t=historyTimestamp(r.playedAt),truth=realizedStateTruth(r);return {record:r,time:t,truth};}).filter(x=>(!allowed||allowed.has(x.record.id))&&x.time!==null&&x.time<now&&x.truth&&solverStatusEligibleForTraining(solverStatusForRecord(x.record,null)));
      const stateKey=(g,p,r)=>`${g}/${p}/${r}`,candidateKeys=candidateStates.flatMap(s=>{const rLo=Number.isInteger(s.r)?s.r:s.rMin,rHi=Number.isInteger(s.r)?s.r:s.rMax??rLo;return Array.from({length:Math.max(0,rHi-rLo+1)},(_,i)=>stateKey(s.g,s.p,rLo+i));}),observedKeys=history.map(x=>stateKey(x.truth.g,x.truth.p,x.truth.r)),domain=[...new Set([...candidateKeys,...observedKeys])];
      if(!domain.length)return {version:"v0.6-shadow",status:"no-sample",localN:0,parentN:0,shrinkageWeight:0,fallbackLevel:"global",candidateWeights:candidateStates.map(s=>({...s,legacyWeight:null,empiricalWeight:null})),rQuantity:{domain:[],probabilities:[],localN:0,parentN:0,shrinkageWeight:0,fallbackLevel:"global"}};
      const groupOf=x=>({condition:canonicalFieldConditionId(x.record?.fieldCondition||x.record?.settlement?.fieldCondition||"unknown"),box:String(x.record?.box||"未知箱型"),venue:String(x.record?.venue||"未知场地"),q:qBucket(x.record?.q)}),currentGroup={condition,box,venue,q:qBucket(ctx?.q)};
      const countRows=(rows,keyFn,domainKeys)=>{const counts=new Map(domainKeys.map(k=>[k,0]));for(const row of rows){const k=keyFn(row);if(counts.has(k))counts.set(k,counts.get(k)+1);}return counts;};
      const blendCategorical=(prior,rows,keyFn,domainKeys)=>{const n=rows.length,k=domainKeys.length,counts=countRows(rows,keyFn,domainKeys),den=n+k,local=new Map(domainKeys.map(key=>[key,((counts.get(key)||0)+1)/Math.max(1,den)])),weight=n/(n+8);return {probs:new Map(domainKeys.map(key=>[key,(prior.get(key)||0)*(1-weight)+(local.get(key)||0)*weight])),n,weight};};
      let prior=new Map(domain.map(k=>[k,1/domain.length])),parentN=0,best={level:"global",n:0,parentN:0,weight:0};
      const levels=[{id:"global",rows:history},{id:"venue",rows:history.filter(x=>groupOf(x).venue===currentGroup.venue)},{id:"box",rows:history.filter(x=>groupOf(x).box===currentGroup.box)},{id:"condition",rows:history.filter(x=>groupOf(x).condition===currentGroup.condition)},{id:"q-bucket",rows:history.filter(x=>groupOf(x).q===currentGroup.q)},{id:"exact-condition-box-q",rows:history.filter(x=>{const g=groupOf(x);return g.condition===currentGroup.condition&&g.box===currentGroup.box&&g.q===currentGroup.q;})}];
      for(const level of levels){const blended=blendCategorical(prior,level.rows,x=>stateKey(x.truth.g,x.truth.p,x.truth.r),domain);if(blended.n){prior=blended.probs;best={level:level.id,n:blended.n,parentN,weight:blended.weight};parentN=blended.n;}}
      const candidateWeights=candidateStates.map(s=>{const rLo=Number.isInteger(s.r)?s.r:s.rMin,rHi=Number.isInteger(s.r)?s.r:s.rMax??rLo,mass=Array.from({length:Math.max(0,rHi-rLo+1)},(_,i)=>prior.get(stateKey(s.g,s.p,rLo+i))||0).reduce((a,b)=>a+b,0),legacyWeight=Number.isFinite(Number(s.weight))?Number(s.weight):null;return {...s,legacyWeight,empiricalWeight:mass};}),massTotal=candidateWeights.reduce((s,x)=>s+(x.empiricalWeight||0),0)||1;
      candidateWeights.forEach(x=>{x.empiricalWeight/=massTotal;});
      const rDomain=Array.from({length:Math.max(1,Math.min(80,Number(ctx?.q)||Math.max(...history.map(x=>x.truth.r),0)))+1},(_,i)=>i),rLevels=levels.map(level=>({id:level.id,rows:level.rows})),rPrior=new Map(rDomain.map(r=>[r,1/rDomain.length]));let rParentN=0,rBest={level:"global",n:0,parentN:0,weight:0};
      for(const level of rLevels){const blended=blendCategorical(rPrior,level.rows,x=>Number(x.truth.r),rDomain);if(blended.n){for(const r of rDomain)rPrior.set(r,blended.probs.get(r)||0);rBest={level:level.id,n:blended.n,parentN:rParentN,weight:blended.weight};rParentN=blended.n;}}
      return {version:"v0.6-shadow",status:"sidecar-only",localN:best.n,parentN:best.parentN,shrinkageWeight:best.weight,fallbackLevel:best.level,qBucket:currentGroup.q,levels:levels.map(x=>({level:x.id,n:x.rows.length})),candidateWeights,rQuantity:{domain:rDomain,probabilities:rDomain.map(r=>rPrior.get(r)||0),localN:rBest.n,parentN:rBest.parentN,shrinkageWeight:rBest.weight,fallbackLevel:rBest.level,qBucket:currentGroup.q}};
    }
    function statePriorEvaluationV06(rows=[]){
      const latest=new Map();for(const row of rows||[]){if(!row?.id)continue;const prev=latest.get(row.id);if(!prev||Number(row.round||0)>=Number(prev.round||0))latest.set(row.id,row);}const usable=[...latest.values()].filter(row=>{const truth=row.realizedState,prior=row.empiricalStatePrior;return truth&&truth.complete!==false&&Number.isInteger(truth.g)&&Number.isInteger(truth.p)&&Number.isInteger(truth.r)&&Array.isArray(prior?.candidateWeights)&&prior.candidateWeights.length>0;});
      if(!usable.length)return {status:"no-sample",n:0,candidateRecall:null,top1Accuracy:null,meanAssignedProbability:null,medianAssignedProbability:null,meanRank:null,brierScore:null,logLoss:null,fallbackLevels:{}};
      const eps=1e-12,rowsOut=usable.map(row=>{const truth=row.realizedState,weights=row.empiricalStatePrior.candidateWeights.map(x=>{const lo=Number.isInteger(x.r)?x.r:x.rMin,hi=Number.isInteger(x.r)?x.r:x.rMax??lo;return {...x,g:Number(x.g),p:Number(x.p),rLo:Number(lo),rHi:Number(hi),prob:Math.max(0,Number(x.empiricalWeight)||0)};}).filter(x=>Number.isInteger(x.g)&&Number.isInteger(x.p)&&Number.isInteger(x.rLo));const total=weights.reduce((s,x)=>s+x.prob,0)||1;weights.forEach(x=>x.prob/=total);const hit=x=>x.g===truth.g&&x.p===truth.p&&truth.r>=x.rLo&&truth.r<=x.rHi,assigned=weights.filter(hit).reduce((s,x)=>s+x.prob,0),sorted=weights.slice().sort((a,b)=>b.prob-a.prob),rank=sorted.findIndex(hit),top=sorted[0],recall=rank>=0,classes=weights.length+1,otherProb=0,brier=(weights.reduce((s,x)=>s+(x.prob-(hit(x)?1:0))**2,0)+(otherProb-(recall?0:1))**2)/classes,logLoss=-Math.log(Math.max(eps,assigned));return {id:row.id,recall,top1:!!top&&hit(top),assignedProbability:assigned,rank:rank>=0?rank+1:null,brier,logLoss,fallbackLevel:row.empiricalStatePrior.fallbackLevel||"global"};});
      const meanValue=key=>{const x=rowsOut.map(r=>r[key]).filter(v=>v!==null&&v!==undefined).map(Number).filter(Number.isFinite);return x.length?mean(x):null;},sortedAssigned=rowsOut.map(x=>x.assignedProbability).sort((a,b)=>a-b),fallbackLevels=rowsOut.reduce((m,x)=>(m[x.fallbackLevel]=(m[x.fallbackLevel]||0)+1,m),{});
      return {status:"oos",n:rowsOut.length,candidateRecall:rowsOut.filter(x=>x.recall).length/rowsOut.length,top1Accuracy:rowsOut.filter(x=>x.top1).length/rowsOut.length,meanAssignedProbability:meanValue("assignedProbability"),medianAssignedProbability:sortedAssigned.length?quantile(sortedAssigned,.5):null,meanRank:meanValue("rank"),brierScore:meanValue("brier"),logLoss:meanValue("logLoss"),fallbackLevels,rows:rowsOut};
    }
    function statePriorEvaluationHtml(summary){if(!summary||summary.status==="no-sample")return `<div class="v06-state-prior-eval"><h3 class="prob-calibration-subhead">State Prior OOS 评估</h3><div class="empty-list">暂无可评估样本：需要完整 realizedState、当时快照和经验先验。</div></div>`;const pct=v=>v==null?"—":`${(v*100).toFixed(1)}%`,num=v=>v==null?"—":Number(v).toFixed(2);return `<div class="v06-state-prior-eval"><h3 class="prob-calibration-subhead">State Prior OOS 评估 · n=${summary.n}</h3><div class="shadow-ab-grid"><div class="shadow-ab-cell shadow"><span>Candidate Recall</span><strong>${pct(summary.candidateRecall)}</strong><small>真实 State 是否仍在候选集合</small></div><div class="shadow-ab-cell shadow"><span>Top1 Accuracy</span><strong>${pct(summary.top1Accuracy)}</strong><small>经验先验最高概率命中</small></div><div class="shadow-ab-cell shadow"><span>Assigned Probability</span><strong>${pct(summary.meanAssignedProbability)}</strong><small>真实 State 平均分配概率</small></div><div class="shadow-ab-cell shadow"><span>Realized State Rank</span><strong>${num(summary.meanRank)}</strong><small>越低越好；未召回不计 rank</small></div><div class="shadow-ab-cell shadow"><span>Brier Score</span><strong>${num(summary.brierScore)}</strong><small>多分类，越低越好</small></div><div class="shadow-ab-cell shadow"><span>Log Loss</span><strong>${num(summary.logLoss)}</strong><small>越低越好；未召回按极小概率惩罚</small></div></div><div class="field-help">严格按每局当时可见历史计算；Q bucket 已纳入 State Prior 分层。该结果只用于旁路评估，不替换 v0.5 heuristic 权重。</div></div>`;}
    function shadowCalibrationSidecarV06(ctx,d){
      const raw=d?.probabilityProfile?.shadowWhole;if(!raw||!Number.isFinite(Number(raw.p50)))return null;const now=historyTimestamp(ctx?.playedAt);if(now===null)return {version:"v0.6-shadow",status:"no-date",raw};
      const allowed=Array.isArray(ctx?.allowedHistoryIds)?new Set(ctx.allowedHistoryIds):null,entries=state.records.map(r=>{const t=historyTimestamp(r.playedAt),p=savedPredictionForHistory(r),shadow=shadowWholeFromPrediction(p),actual=nonNegativeOrNull(r.actualTotal);if(allowed&&!allowed.has(r.id)||t===null||t>=now||!shadow||actual===null||!Number.isFinite(Number(shadow.p50))||!Number.isFinite(Number(shadow.p20))||!Number.isFinite(Number(shadow.p80))||!solverStatusEligibleForTraining(solverStatusForRecord(r,null)))return null;return {actual,shadow,residual:(actual-Number(shadow.p50))/Math.max(1,Number(shadow.p50))};}).filter(Boolean),residuals=entries.map(x=>x.residual).filter(Number.isFinite),p10=quantile(residuals,.10),p90=quantile(residuals,.90),n=residuals.length,low=n>=5?Math.min(Number(raw.p20),Math.max(0,Number(raw.p50)*(1+(p10??-.25)))):Number(raw.p20),high=n>=5?Math.max(Number(raw.p80),Number(raw.p50)*(1+(p90??.25))):Number(raw.p80),rawCoverage=entries.length?entries.filter(x=>actualInRange(x.actual,raw.p20,raw.p80)).length/entries.length:null,calibratedCoverage=entries.length?entries.filter(x=>actualInRange(x.actual,low,high)).length/entries.length:null;
      return {version:"v0.6-shadow",status:n>=5?"calibrated-sidecar":"low-sample",residualN:n,residualP10:p10,residualP90:p90,raw:{p20:Number(raw.p20),p50:Number(raw.p50),p80:Number(raw.p80)},calibrated:{p20:low,p50:Number(raw.p50),p80:high},coverage:calibratedCoverage,rawCoverage,calibratedCoverage,coverageN:entries.length,nominalTarget:"真实 OOS P20/P80 区间覆盖；残差 P10/P90 仅用于旁路扩宽，中心不变"};
    }
    function marketPredictionV06(ctx,valueEstimate){
      const estimate=Number(valueEstimate),now=historyTimestamp(ctx?.playedAt);if(!Number.isFinite(estimate)||estimate<=0||now===null)return {version:"v0.6-market",status:"no-data",marketRatio:null,p20:null,p50:null,p80:null,localN:0,parentN:0,shrinkageWeight:0,fallbackLevel:"none",competition:"未知"};
      const allowed=Array.isArray(ctx?.allowedHistoryIds)?new Set(ctx.allowedHistoryIds):null,condition=canonicalFieldConditionId(ctx?.fieldCondition||"unknown"),box=String(ctx?.box||"未知箱型"),venue=String(ctx?.venue||"未知场地"),qBucket=qBucketV06(ctx?.q),rows=state.records.map(r=>{const t=historyTimestamp(r.playedAt),p=savedPredictionForHistory(r),status=solverStatusForRecord(r,null),clearing=nonNegativeOrNull(r.clearingPrice??r.settlement?.clearingPrice),base=Number(p?.estimate);if(allowed&&!allowed.has(r.id)||t===null||t>=now||!solverStatusEligibleForTraining(status)||clearing===null||!Number.isFinite(base)||base<=0)return null;const c=canonicalFieldConditionId(r.fieldCondition||r.settlement?.fieldCondition||"unknown"),rb=qBucketV06(r.q);return {record:r,ratio:clearing/base,condition:c,box:String(r.box||"未知箱型"),venue:String(r.venue||"未知场地"),qBucket:rb};}).filter(x=>x&&Number.isFinite(x.ratio)&&x.ratio>0&&x.ratio<5),stats=items=>items.length?{n:items.length,p20:quantile(items.map(x=>x.ratio),.2),p50:quantile(items.map(x=>x.ratio),.5),p80:quantile(items.map(x=>x.ratio),.8)}:{n:0,p20:null,p50:null,p80:null};
      if(!rows.length)return {version:"v0.6-market",status:"no-sample",marketRatio:null,p20:null,p50:null,p80:null,localN:0,parentN:0,shrinkageWeight:0,fallbackLevel:"global",competition:"未知",availableN:0};
      const levels=[{id:"global",items:rows},{id:"venue",items:rows.filter(x=>x.venue===venue)},{id:"box",items:rows.filter(x=>x.box===box)},{id:"condition",items:rows.filter(x=>x.condition===condition)},{id:"q-bucket",items:rows.filter(x=>x.qBucket===qBucket)},{id:"exact-condition-box-q",items:rows.filter(x=>x.condition===condition&&x.box===box&&x.qBucket===qBucket)}];let parent=stats(rows),parentN=rows.length,best={level:"global",n:rows.length,parentN:0,weight:rows.length/(rows.length+8)};
      for(const level of levels.slice(1)){const local=stats(level.items);if(!local.n)continue;const weight=local.n/(local.n+8),blend=(key)=>parent[key]+(local[key]-parent[key])*weight;parent={n:local.n,p20:blend("p20"),p50:blend("p50"),p80:blend("p80")};best={level:level.id,n:local.n,parentN,weight};parentN=local.n;}
      const toValue=ratio=>Number.isFinite(ratio)?Math.max(0,ratio*estimate):null,p20=toValue(parent.p20),p50=toValue(parent.p50),p80=toValue(parent.p80),competition=parent.p50<.75?"冷":parent.p50<.95?"正常":parent.p50<1.10?"偏紧":"疯狂";
      return {version:"v0.6-market",status:best.n<5?"low-sample":"shrunk",marketRatio:{p20:parent.p20,p50:parent.p50,p80:parent.p80},p20,p50,p80,localN:best.n,parentN:best.parentN,shrinkageWeight:best.weight,fallbackLevel:best.level,qBucket,competition,availableN:rows.length,lowSample:best.n<5,uses:"clearingPrice / 当时冻结 estimate；不读取 actualTotal；严格回放优先使用 allowedHistoryIds"};
    }
    function entryDecisionV06(ctx,d){
      const market=d?.marketPrediction||{},value=Number(d?.center),marketP50=Number(market.p50),cost=Math.max(0,Number(decisionSessionCost(d??ctx))||0),targetProfit=Math.max(0,Number(ctx?.targetProfit??d?.targetProfit??30000)||30000);
      if(!Number.isFinite(value)||value<=0||!Number.isFinite(marketP50)||marketP50<=0)return {version:"v0.6-decision",status:"no-market",valueEstimate:Number.isFinite(value)?value:null,marketP50:null,cost,targetProfit,edge:null};
      const edge=value-marketP50-cost,status=edge>=targetProfit?"worth-entering":edge>0?"thin-entry":"not-worth-entering";
      return {version:"v0.6-decision",status,valueEstimate:value,marketP50,cost,targetProfit,edge,marketStatus:market.status||"unknown",fallbackLevel:market.fallbackLevel||"global"};
    }
    function workingDecision(ctx,states=[],options={}){
      ctx=enrichContextFromIntel(maybeLockRedZero(ctx));
      let boxV=null,venQ=null,venV=null,infoMode=detectInfoMode(ctx);
      const similar=similarHistory(ctx,8),analog=analogHistoryBundle(ctx,similar),historyEntries=similar.map(x=>({value:Number(x.record.actualTotal),weight:x.weight})),historyCenter=weightedQuantile(historyEntries,.5),history=cohortStats(similar.map(x=>x.record));
      const expandedStates=expandStatesForValuation(ctx, states);
      const componentRows=expandedStates.map(state=>{const component=stateComponents(ctx,state);return component?{state,component,weight:candidateStateWeight(state,ctx)}:null;}).filter(Boolean);
      const components=componentRows.map(x=>x.component);
      const structural=componentRows.map(x=>({value:x.component.total,weight:x.weight}));
      let structuralCenter=weightedQuantile(structural,.5);
      const typicalCenters=componentRows.map(x=>({value:(x.component.typicalLow*0.45+x.component.total*0.35+x.component.typicalHigh*0.2),weight:x.weight}));
      const robustCenter=weightedQuantile(typicalCenters,.5);
      if(Number.isFinite(robustCenter)) structuralCenter=structuralCenter===null?robustCenter:(structuralCenter*0.35+robustCenter*0.65);
      const pi=ctx.publicInfo||{};
      const effectivePools=effectiveCatalog(ctx),goldTotalCandidates=effectiveTotalCandidates(ctx,"gold",ctx.goldTotal).filter(Number.isFinite),goldAvgCandidates=effectiveAverageCandidates(ctx,"gold",ctx.avg).filter(Number.isFinite),purpleAvgCandidates=effectiveAverageCandidates(ctx,"purple",ctx.purpleAvg).filter(Number.isFinite),effectiveKnownGold=adjustedKnownItems(ctx,"gold",ctx.knownGold),effectiveKnownPurple=adjustedKnownItems(ctx,"purple",ctx.knownPurple),goldMultiplier=conditionPriceMultiplier(ctx,"gold"),purpleMultiplier=conditionPriceMultiplier(ctx,"purple");
      const exactGoldFloor=goldTotalCandidates.length?Math.min(...goldTotalCandidates):(goldAvgCandidates.length&&hasNumber(ctx.goldCount)&&Number.isInteger(Number(ctx.goldCount))?Math.min(...goldAvgCandidates)*Number(ctx.goldCount):0);
      const minimumAverageGoldFloor=goldAvgCandidates.length?Math.min(...goldAvgCandidates)*Math.max(1,Number(ctx.minGold)||1):0;
      const goldEvidence=constraintEvidenceFloor(effectiveKnownGold,conditionAdjustedGroups(ctx.goldGroups,goldMultiplier),effectivePools.gold,2),knownGoldFloor=Math.max(exactGoldFloor,minimumAverageGoldFloor,goldEvidence.total);
      const minimumAveragePurpleFloor=purpleAvgCandidates.length?Math.min(...purpleAvgCandidates)*Math.max(1,hasNumber(ctx.purple)?Number(ctx.purple):(Number(ctx.minPurple)||1)):0,purpleEvidence=constraintEvidenceFloor(effectiveKnownPurple,conditionAdjustedGroups(ctx.purpleGroups,purpleMultiplier),effectivePools.purple,2),knownPurpleFloor=Math.max(minimumAveragePurpleFloor,purpleEvidence.total);
      const redEvidence=constraintEvidenceFloor(ctx.knownRed,ctx.redGroups,effectivePools.red,2),knownRedFloor=redEvidence.total;
      const catalogFloor=components.length?Math.min(...components.map(x=>x.hardLower)):0;
      const quantitiesExplicit=hasNumber(ctx.goldCount)&&hasNumber(ctx.purple)&&hasNumber(ctx.redCount);
      // 金均价但 G 未知时，v4 组合只能算候选，不能冒充铁下限；历史里已有反例。
      let hardFloor=quantitiesExplicit?catalogFloor:0;
      hardFloor=Math.max(hardFloor, hasNumber(options.centerFloor)?Number(options.centerFloor):0, hasNumber(pi.systemEstimate)?Number(pi.systemEstimate):0, knownGoldFloor+knownPurpleFloor+knownRedFloor);
      if(hasNumber(options.hardFloor) && options.trustTheoreticalFloor) hardFloor=Math.max(hardFloor, Number(options.hardFloor));
      const hasPriceEvidence=Number.isFinite(ctx.goldTotal)||Number.isFinite(ctx.avg)||Number.isFinite(ctx.purpleAvg)||hasNumber(pi.goldGrid)||(ctx.knownGold||[]).length>0||(ctx.goldGroups||[]).length>0||(ctx.knownPurple||[]).length>0||(ctx.purpleGroups||[]).length>0||(ctx.knownRed||[]).length>0||(ctx.redGroups||[]).length>0;
      const hasSystemOnly=!hasPriceEvidence && (hasNumber(pi.systemEstimate)&&Number(pi.systemEstimate)>0);
      const hasHardPrice=hasPriceEvidence || hasSystemOnly;
      const uniqueInts=(arr)=>{const u=[...new Set(arr.filter(x=>Number.isInteger(x)))]; return u.length===1?u[0]:null;};
      const canInferSplit=hasNumber(ctx.q);
      const lockedG=hasNumber(ctx.goldCount)&&Number.isInteger(Number(ctx.goldCount))?Number(ctx.goldCount):(canInferSplit?uniqueInts(expandedStates.map(s=>Number(s.g))):null);
      const lockedP=hasNumber(ctx.purple)&&Number.isInteger(Number(ctx.purple))?Number(ctx.purple):(canInferSplit?uniqueInts(expandedStates.map(s=>Number(s.p))):null);
      const lockedR=hasNumber(ctx.redCount)&&Number.isInteger(Number(ctx.redCount))?Number(ctx.redCount):(canInferSplit?uniqueInts(expandedStates.map(s=>Number(s.r))):null);
      const quantitiesResolved=components.length>0 && canInferSplit && lockedG!==null && lockedP!==null && lockedR!==null;
      const residual=historyResidualBundle(ctx);
      let center=structuralCenter;
      let usedSynthetic=false;
      let syntheticBd=null;
      if(!Number.isFinite(center) && Number.isFinite(ctx.avg) && hasNumber(ctx.q)){
        syntheticBd=syntheticGoldAvgBreakdown(ctx, expandedStates);
        if(syntheticBd){
          center=(syntheticBd.gold.mid||0)+(syntheticBd.purple.mid||0)+(syntheticBd.red.mid||0)+(syntheticBd.lowTier&&syntheticBd.lowTier.mid||0);
          usedSynthetic=true;
          hardFloor=Math.max(hardFloor, syntheticBd.gold.lower||0);
        }
      }
      if(!Number.isFinite(center)) center=historyCenter??EMPTY_VENUE_PRIOR[ctx.venue]??EMPTY_VENUE_PRIOR["未知场地"];
      else if(!hasHardPrice && residual.n>=4 && Number.isFinite(historyCenter)){
        const shrink=Math.min(.28,residual.n/(residual.n+18));
        center=center*(1-shrink)+historyCenter*shrink;
      }
      center=Math.max(center, hardFloor, knownGoldFloor);
      boxV=historyBoxValue(ctx); venQ=historyVenueQ(ctx); venV=historyVenueValue(ctx); infoMode=detectInfoMode(ctx);
      let analogWeight=0,analogTargetValue=null,preAnalogCenter=center;
      if(!hasHardPrice && !usedSynthetic){
        // 低信息工作值优先使用“本局之前”的同场/同箱/Q近邻中位；低分位仍只用于保命线。
        if(analog.n&&Number.isFinite(analog.p50)){
          analogWeight=analog.topSimilarity>=90?.64:analog.topSimilarity>=75?.54:.42;
          if(boxIsUnknown(ctx.box))analogWeight=Math.min(analogWeight,.48);
          analogTargetValue=analog.anchor??analog.p50;center=center*(1-analogWeight)+analogTargetValue*analogWeight;
        }else{
          const histHints=[];
          if(boxV&&boxV.n>=3) histHints.push(boxV.p35??boxV.p50);
          if(venQ&&venQ.n>=2) histHints.push(venQ.p35??venQ.p50);
          if(!histHints.length && venV&&venV.n>=5) histHints.push(venV.p35??venV.p50);
          if(histHints.length){const hMed=histHints.reduce((a,b)=>a+b,0)/histHints.length;analogWeight=Math.min(.46,.28+histHints.length*.08);analogTargetValue=hMed;center=center*(1-analogWeight)+hMed*analogWeight;}
        }
        // no locked red: shave soft-red optimism from structural mid
        if(!hasNumber(ctx.redCount) && components.length){
          center=center*0.96;
        }
      // unknownBoxDamp
      if(boxIsUnknown(ctx.box) && !hasHardPrice && !analog.n){
        if(venQ&&venQ.n>=2) center=center*0.45+(venQ.p35??venQ.p50)*0.55;
        else center*=0.82;
      }
      } else if(hasHardPrice && !quantitiesResolved && (infoMode.id==="goldAvgOnly"||infoMode.id==="goldAvgPurple")){
        // 金均单独模式：低 G 金池 + 薄残值，避免高 G 候选把中心抬爆。
        if(infoMode.id==="goldAvgOnly" && Number.isFinite(ctx.avg) && components.length){
          const rows=componentRows.map(x=>({g:x.state.g, total:x.component.total, gold:x.component.gold.mid, rest:x.component.total-x.component.gold.mid, weight:x.weight}));
          const gHat=weightedQuantile(rows.map(x=>({value:x.g,weight:x.weight})),.35);
          const gUse=Math.max(ctx.minGold||1, Math.round(gHat||1));
          const near=rows.filter(x=>x.g===gUse);
          const pick=near.length?near:rows;
          const goldPart=weightedQuantile(pick.map(x=>({value:x.gold,weight:x.weight})),.5);
          const restPart=weightedQuantile(pick.map(x=>({value:x.rest,weight:x.weight})),.35);
          if(Number.isFinite(goldPart)){
            const thin=Number.isFinite(restPart)?restPart: (historyBoxRed(ctx)?.workRed||0)*0.5 + (LOW_TIER_PRIOR[ctx.venue]||12000);
            center=Math.max(hardFloor, goldPart + thin*0.85);
          }
        }

        const soft=historySoftResidual(ctx);
        if(soft&&soft.n>=3 && !components.length){ center=Math.max(center, soft.p25*0.55 + (historyBoxRed(ctx)?.workRed||0)*0.35); }
        if(Number.isFinite(ctx.avg) && components.length){
          const gOnly=weightedQuantile(componentRows.map(x=>({value:x.component.gold.mid,weight:x.weight})),.5);
          const restOnly=weightedQuantile(componentRows.map(x=>({value:x.component.total-x.component.gold.mid,weight:x.weight})),.4);
          if(Number.isFinite(gOnly)) center=Math.max(center, gOnly+(Number.isFinite(restOnly)?restOnly:0));
        }
      }
      if(hasHardPrice&&!quantitiesResolved&&analog.n&&Number.isFinite(analog.p50)){
        // 有价格但件数没锁定时，结构候选容易被高 G/多红抬偏；相似历史只做有上限的稳健校准。
        // Q+金均但 G 未知时，结构低-G假设比“同箱+同Q+近金均”的前序实局更脆弱；
        // 只在相似度极高且金均低于9W时提高近邻权重；超高金均常由单件大金造成，不能据此追高。
        // 主路径 Q+紫+金均仍保留原权重，避免全面追涨。
        analogWeight=infoMode.id==="goldAvgOnly"&&analog.topSimilarity>=94&&Number(ctx.avg)<90000?.70:(analog.topSimilarity>=92?.52:analog.topSimilarity>=78?.42:.30);
        if(analog.exactBoxN===0&&!boxIsUnknown(ctx.box))analogWeight=Math.min(analogWeight,.28);
        if(Number.isFinite(ctx.goldTotal))analogWeight=Math.min(analogWeight,.18);
        preAnalogCenter=center;
        const rawTarget=infoMode.id==="goldAvgPurple"?analog.p50:(analog.anchor??analog.p50),analogTarget=Math.max(hardFloor,rawTarget);analogTargetValue=analogTarget;
        center=center*(1-analogWeight)+analogTarget*analogWeight;
      }
      center=Math.max(center, hardFloor, knownGoldFloor);
      if(goldTotalCandidates.length){
        const bd=summarizeBreakdown(componentRows);
        const add=(bd?.purple?.mid||knownPurpleFloor||0)+(bd?.red?.mid||0)*.55+(bd?.lowTier?.mid||LOW_TIER_PRIOR[ctx.venue]||12000);
        center=Math.max(center, Math.min(...goldTotalCandidates)+add*0.85);
      }
      let low,high;
      if(components.length){
        low=Math.max(hardFloor, weightedQuantile(componentRows.map(x=>({value:x.component.typicalLow,weight:x.weight})),.28));
        high=Math.max(center, weightedQuantile(componentRows.map(x=>({value:x.component.typicalHigh,weight:x.weight})),.72));
        if(!hasHardPrice){low=Math.max(hardFloor,Math.min(low,center*.72));high=Math.max(high,center*1.32);}
      } else {
        low=Math.max(hardFloor, history.p25??center*.58);
        high=Math.max(center, history.p75??center*1.48);
      }
      if(analogWeight>0&&analog.n){
        if(Number.isFinite(analog.p20))low=Math.max(hardFloor,Math.min(low,analog.p20));
        if(Number.isFinite(analog.p80))high=Math.max(high,analog.p80);
      }
      const typicalLowCenter=components.length?weightedQuantile(componentRows.map(x=>({value:x.component.typicalLow,weight:x.weight})),.35):null;
      const historyRisk=weightedQuantile(historyEntries,.22);
      let riskAnchor;
      if(hasHardPrice && components.length){
        riskAnchor=Math.min(center, Math.max(hardFloor, typicalLowCenter??hardFloor));
        if(!quantitiesResolved){
          // 件数未锁定：保本更贴 common-low，并进一步向硬下限靠
          riskAnchor=Math.min(riskAnchor, (typicalLowCenter??center)*0.78 + hardFloor*0.22);
          if(Number.isFinite(ctx.avg) && ctx.goldCount==null) riskAnchor=Math.min(riskAnchor, (typicalLowCenter??riskAnchor)*0.9);
          if(Number.isFinite(ctx.avg) && ctx.avg>=90000) riskAnchor=Math.min(riskAnchor, center*0.52, (typicalLowCenter??center)*0.66);
          if(Number.isFinite(ctx.avg) && ctx.avg>=130000) riskAnchor=Math.min(riskAnchor, center*0.45, (typicalLowCenter??center)*0.58, hardFloor>0?hardFloor*1.35:riskAnchor);
        }
      } else if(Number.isFinite(historyRisk)){
        riskAnchor=Math.min(center, historyRisk);
      } else {
        riskAnchor=Math.min(center, Math.max(hardFloor, center*.58));
      }
      let safety=quantitiesResolved&&hasHardPrice?0.88: hasHardPrice?0.80: 0.68;
      if(similar.length && similar[0].similarity>=75) safety+=0.02;
      if(!quantitiesResolved) safety-=0.05;
      if(!hasHardPrice) safety-=0.08; // only-Q / pure history: caps must stay under thin actuals
      if(infoMode&&infoMode.id==="goldAvgOnly") safety-=0.04;
      if((ctx.box||"").includes("红色")) safety-=0.03;
      if(boxV&&boxV.n>=3){ riskAnchor=Math.min(riskAnchor, boxV.p20); }
      if(venQ&&venQ.n>=2){ riskAnchor=Math.min(riskAnchor, venQ.p20); }
      if(!hasHardPrice && venV&&venV.n>=5){ riskAnchor=Math.min(riskAnchor, venV.p20); }
      // gold-avg-only: risk anchor prefer low-G gold floor + thin residual
      if(hasHardPrice && infoMode&&infoMode.id==="goldAvgOnly" && Number.isFinite(ctx.avg)){
        const gLo=Math.max(ctx.minGold||1,1);
        const goldFloor=Number(ctx.avg)*gLo;
        riskAnchor=Math.min(riskAnchor, goldFloor*1.05 + (historyBoxRed(ctx)?.lowRed||8000));
      }
      riskAnchor=Math.min(riskAnchor, center);
      // 已知金总价：保本至少贴近硬证据（否则 43.5W 金总会被压成 13W 保本）
      if(goldTotalCandidates.length&&Math.min(...goldTotalCandidates)>0){
        riskAnchor=Math.max(riskAnchor, Math.min(...goldTotalCandidates)*0.92);
      } else if(hasHardPrice&&hardFloor>0&&quantitiesResolved){
        riskAnchor=Math.max(riskAnchor, hardFloor*0.85);
      }
      let cap=Math.max(0, Math.floor((riskAnchor*Math.max(0.50,Math.min(0.92,safety)))/1000)*1000);
      if(!hasHardPrice){
        // final only-Q guard against thin actuals just under old caps
        const guard=Math.min(center*0.48, (boxV&&boxV.n>=3?boxV.p20:Infinity), (venQ&&venQ.n>=2?venQ.p20:Infinity));
        if(Number.isFinite(guard)) cap=Math.min(cap, Math.floor(guard/1000)*1000);
      }
      if((!ctx.box||String(ctx.box).startsWith("未知")) && !hasHardPrice){
        cap=Math.min(cap, Math.floor(center*0.40/1000)*1000);
      }
      if(!hasNumber(ctx.q) && !hasHardPrice){
        // no-Q mixed: extremely low confidence — keep under thin package actuals
        cap=Math.min(cap, Math.floor(center*0.25/1000)*1000);
        if(venV&&venV.n>=3) cap=Math.min(cap, Math.floor((venV.p20||center*0.25)/1000)*1000);
        if(boxV&&boxV.n>=2) cap=Math.min(cap, Math.floor((boxV.p20||center*0.25)/1000)*1000);
        cap=Math.min(cap, 90000); // absolute soft ceiling for no-Q sightseeing
      }
      if((hasSystemOnly || !hasNumber(ctx.q)) && !Number.isFinite(ctx.avg) && !Number.isFinite(ctx.goldTotal)){
        // system estimate alone is not enough to bid aggressively
        const sys=hasSystemOnly?Number(pi.systemEstimate):0;
        const weakCeil=Math.max(sys*1.15, (boxV&&boxV.p20)||0, (venQ&&venQ.p20)||0, (venV&&venV.p20)||0, center*0.22);
        // if all zeros, fall back
        const ceil=weakCeil>0?weakCeil:center*0.22;
        cap=Math.min(cap, Math.floor(ceil/1000)*1000);
        // never let system-only cap exceed center*0.55 either
        cap=Math.min(cap, Math.floor(center*0.55/1000)*1000);
      }
      if(goldTotalCandidates.length&&Math.min(...goldTotalCandidates)>0){
        cap=Math.max(cap, Math.floor(Math.min(...goldTotalCandidates)*0.90/1000)*1000);
      }
      const cost=Math.max(0,Number(ctx.cost)||0),safeCalibration=infoMode.id==="onlyQ"?0.90:infoMode.id==="goldAvgOnly"?0.95:1;
      cap=Math.max(0,Math.floor((cap*safeCalibration-cost)/1000)*1000);
      const balancedMultiplier=infoMode.id==="noQ"?0.45:
        quantitiesResolved&&hasHardPrice?0.82:
        infoMode.id==="goldAvgPurple"?0.80:
        infoMode.id==="goldTotal"?0.82:
        infoMode.id==="dualAvg"?0.72:
        infoMode.id==="goldAvgOnly"?0.45:0.20;
      const evidenceBidFloor=hasHardPrice&&hardFloor>0?(quantitiesResolved?hardFloor*.92:hardFloor*.82):0;
      const balancedRaw=Math.max(center*balancedMultiplier,evidenceBidFloor);
      let balancedCap=Math.max(cap,Math.max(0,Math.floor((Math.min(center*.90,balancedRaw)-cost)/1000)*1000));
      // 四条线语义分离：hardFloor 是证据下限；cap 保留原数值但只叫“保守防亏线”；
      // balancedCap 是原有平衡/证据线，v0.4 仅保留为“v0.3 平衡参考线”；workingHigh 只作为高风险尝试参考。
      // 这里不改变任何倍率，只把已有输出改成可解释的决策层名称。
      let conservativeLossLine=cap,recommendedMaxBid=balancedCap,highRiskTrialLine=Math.max(recommendedMaxBid,Math.floor(Math.max(0,high)/1000)*1000),probabilityProfile=redProbabilityProfile(ctx,expandedStates,componentRows);
      const conditionAnalysis=fieldConditionAnalysis(ctx),sparkleBlocked=conditionAnalysis.id==="sparkle";
      if(sparkleBlocked){cap=null;balancedCap=null;conservativeLossLine=null;recommendedMaxBid=null;highRiskTrialLine=null;probabilityProfile=null;}
      let breakdown=summarizeBreakdown(componentRows);
      if((!breakdown||!breakdown.gold) && syntheticBd) breakdown=syntheticBd;
      if((!breakdown||!breakdown.gold) && Number.isFinite(ctx.avg) && hasNumber(ctx.q)) breakdown=syntheticGoldAvgBreakdown(ctx, expandedStates)||breakdown;
      if(!breakdown||!breakdown.gold){
        const bv=boxV||historyBoxValue(ctx);
        const lowT=lowTierEstimate(ctx);
        const mid=center;
        breakdown={
          gold:{mid:mid*0.45,lower:0,upper:mid*0.9,typicalLow:mid*0.3,typicalHigh:mid*0.6,source:bv?("箱型历史分拆（p50="+fmtWan(bv.p50)+"）"):"历史近邻分拆"},
          purple:{mid:mid*0.2,lower:0,upper:mid*0.4,typicalLow:mid*0.1,typicalHigh:mid*0.3,source:"历史近邻分拆"},
          red:{mid:mid*0.3,lower:0,upper:Math.max(mid*2,1e6),typicalLow:mid*0.1,typicalHigh:mid*0.7,source:"历史近邻分拆（中心≠大奖）"},
          lowTier:lowT||{mid:mid*0.05,lower:0,upper:mid*0.12,typicalLow:0,typicalHigh:mid*0.08,source:"场地低品质先验"}
        };
      }
      const confidence=hasHardPrice&&quantitiesResolved?(components.length<=2?"中高":"中"):components.length?(hasHardPrice?"中低":"低"):usedSynthetic?"中低":similar.length>=5?"低":"很低";
      let source;
      if(components.length) source=(infoMode&&infoMode.id==="onlyQ"?"v0.3低信息结构":"v0.3结构分项")+(infoMode&&infoMode.id==="goldAvgOnly"?" · 金均×G展开":"");
      else if(usedSynthetic) source="v0.3金均结构合成";
      else source="v0.3时序相似历史（真低信息）";
      if(breakdown.lowTier&&breakdown.lowTier.source) source+=" + "+breakdown.lowTier.source;
      if(analogWeight>0)source+=` + 时序近邻${Math.round(analogWeight*100)}%`;
      if(options.sourceSuffix) source+=options.sourceSuffix;
      if(lockedR===0) source+=" · R=0";
      const cohort={label:(components.length||usedSynthetic)?"结构/金均路径":"场地/箱型/Q 加权近邻",records:similar.map(x=>x.record),matches:similar,level:(components.length||usedSynthetic)?1:5};
      return {modelVersion:"v0.5-field-conditions",center:sparkleBlocked?null:center,low:sparkleBlocked?(conditionAnalysis.sparkleEvidence?.lower??null):low,high:sparkleBlocked?(conditionAnalysis.sparkleEvidence?.upper??null):high,cap,balancedCap,conservativeLossLine,recommendedMaxBid,highRiskTrialLine,recommendationSuppressed:sparkleBlocked,recommendationSuppressedReason:sparkleBlocked?"闪耀之心宝石概率未知：仅提供证据边界，不生成概率或推荐价":null,fieldConditionAnalysis:conditionAnalysis,avgValueBasis:{gold:averageValueBasis(ctx,"gold"),purple:averageValueBasis(ctx,"purple")},balancedMultiplier,riskAnchor:sparkleBlocked?null:riskAnchor,hardFloor:sparkleBlocked?(conditionAnalysis.sparkleEvidence?.lower??hardFloor):hardFloor,cost,safeCalibration,confidence:sparkleBlocked?"证据边界":confidence,source:sparkleBlocked?"闪耀之心·无概率证据边界":source,history,structuralCenter:sparkleBlocked?null:structuralCenter,historyCenter,cohort,similar,analog,analogWeight:sparkleBlocked?0:analogWeight,analogTarget:analogTargetValue,preAnalogCenter:sparkleBlocked?null:preAnalogCenter,components:sparkleBlocked?[]:components,componentRows:sparkleBlocked?[]:componentRows,breakdown:sparkleBlocked?null:breakdown,probabilityProfile,hasHardPrice,quantitiesResolved,residual,infoMode,boxValue:boxV||null,venueQ:venQ||null,usedSynthetic,lockedR,blindSpots:{goldCount:!hasNumber(ctx.goldCount),redCount:!hasNumber(ctx.redCount),box:boxIsUnknown(ctx.box)}};
    }
    function decisionExplanationHtml(d){
      const a=d.analog||{},w=Number(d.analogWeight)||0,structural=Number.isFinite(d.preAnalogCenter)?d.preAnalogCenter:d.structuralCenter,closest=(d.similar||[]).slice(0,3),blind=[];
      if(d.blindSpots?.goldCount)blind.push("金件数未知");
      if(d.blindSpots?.redCount)blind.push("红件数未知：大奖无法由当前情报识别");
      if(d.blindSpots?.box)blind.push("箱型未知：按同场已知箱型混合");
      if(!d.hasHardPrice)blind.push("没有价格硬证据");
      const historyTarget=Number.isFinite(d.analogTarget)?d.analogTarget:(Number.isFinite(a.anchor)?a.anchor:a.p50),equation=w>0&&Number.isFinite(historyTarget)?`结构 ${fmtWan(structural)} × ${Math.round((1-w)*100)}% + 历史 ${fmtWan(historyTarget)} × ${Math.round(w*100)}% → ${fmtWan(d.center)}`:`结构 ${fmtWan(d.center)} · 历史不足，未校准中心`;
      const quickTags=[...blind.slice(0,2),w>0?`历史权重${Math.round(w*100)}%`:"未使用历史校准"];
      return `<details class="decision-explain"><summary><span class="decision-explain-summary"><strong>估值构成：${escapeHtml(equation)}</strong><span>展开解释</span></span><span class="blind-spot-list compact">${quickTags.map(x=>`<i class="blind-spot">${escapeHtml(x)}</i>`).join("")}</span></summary><div class="decision-explain-body"><div class="explain-grid"><div class="explain-cell"><span>结构/图鉴工作值</span><strong>${fmtWan(structural)}</strong><small>金、紫、常见红、蓝绿白相加</small></div><div class="explain-cell"><span>历史典型区间</span><strong>${a.n?`${fmtWan(a.p20)}—${fmtWan(a.p80)}`:"样本不足"}</strong><small>${a.n?`${a.n} 局 · 最高相似 ${a.topSimilarity}% · 有效样本 ${a.effectiveN.toFixed(1)}`:"不会拿全库平均数冒充近邻"}</small></div><div class="explain-cell"><span>硬下限 / 防亏线 / 推荐上限</span><strong>${fmtWan(d.hardFloor)} / ${fmtWan(d.conservativeLossLine??d.cap)} / ${fmtWan(d.recommendedMaxBid??d.balancedCap)}</strong><small>硬下限是证据边界；防亏线是极保守线；推荐上限不等于保证盈利</small></div></div>${closest.length?`<div class="field-help">最近参考：${closest.map(x=>`${escapeHtml(x.record.box||"未知箱型")} ${fmtWan(x.record.actualTotal)}（${x.similarity}%）`).join(" · ")}</div>`:""}${blind.length?`<div class="blind-spot-list">${blind.map(x=>`<span class="blind-spot">${escapeHtml(x)}</span>`).join("")}</div>`:""}</div></details>`;
    }
    function probabilityProfileHtml(d){
      const p=d?.probabilityProfile;if(!p)return "";
      const finite=value=>Number.isFinite(Number(value)),total=p.currentTotal||null,dist=p.currentDistribution||{};
      const directN=Number(dist.directN)||0,directGames=Number(dist.directGames)||directN,bootstrapN=Number(dist.bootstrapN)||0,mode=String(dist.mode||"none");
      const fmt=value=>finite(value)?fmtWan(Number(value)):"—";
      const hasTypical=total&&finite(total.p20)&&finite(total.p50)&&finite(total.p80);
      const tail=p.tail||{};
      const rangeLow=finite(total?.p10)?Number(total.p10):(finite(total?.min)?Number(total.min):hasTypical?Number(total.p20):0);
      const rangeHigh=finite(total?.p90)?Number(total.p90):(finite(total?.max)?Number(total.max):hasTypical?Number(total.p80):1);
      const span=Math.max(1,rangeHigh-rangeLow);
      const marker=(label,value,cls="")=>finite(value)&&rangeHigh>rangeLow?`<span class="probability-marker ${cls}" style="left:${Math.max(0,Math.min(100,(Number(value)-rangeLow)/span*100)).toFixed(2)}%"><i>${label} ${fmt(value)}</i></span>`:"";
      const markers=hasTypical?`${marker("P20",total.p20)}${marker("P50",total.p50,"p50")}${marker("P80",total.p80)}`:"";
      const stateCandidates=(p.stateCandidates||[]).slice().sort((a,b)=>Number(b.relativeWeight||0)-Number(a.relativeWeight||0)||Number(a.r??a.rMin)-Number(b.r??b.rMin)||Number(a.g)-Number(b.g)||Number(a.p)-Number(b.p));
      const statesWithShadow=stateCandidates.filter(s=>s.shadow&&finite(s.shadow.p50)).length;
      const statesStructuralOnly=stateCandidates.length-statesWithShadow;
      const zeroRedOnly=stateCandidates.length>0&&stateCandidates.every(x=>Number(x.r??x.rMin)===0);
      const modeText=(p.currentModes||[]).map(x=>`${x.mode}×${x.n}`).join(" · ")||"无可用红数量状态";
      const distributionText=zeroRedOnly?"R=0 已确定 · 红货总价为 0":dist.label?`${dist.label} · 当前 ${dist.n||0} 条（直接样本 ${directN} · 独立直接局 ${directGames} / bootstrap ${bootstrapN}）`:`当前分布样本不足`;
      const typicalNote=zeroRedOnly?"R=0 已锁定 · 红总价=0":hasTypical?`${dist.mode==="direct"?"同 R 直接经验":"探索性组合分布"} · ${directGames||0} 个独立直接局`:`当前没有足够的红货分布样本`;
      const maxStateWeight=Math.max(0,...stateCandidates.map(x=>Number(x.relativeWeight)||0));
      const stateRows=stateCandidates.map(s=>{
        const rLabel=s.rMin!==s.rMax?`R=${s.rMin}–${s.rMax}`:`R=${s.r??s.rMin}`;
        const red=s.red,redText=red&&finite(red.p20)?`P20 ${fmt(red.p20)} · P50 ${fmt(red.p50)} · P80 ${fmt(red.p80)}`:(s.redByR||[]).length?`按 R 分布：${s.redByR.map(x=>`R${x.r} P20 ${fmt(x.stats?.p20)} · P50 ${fmt(x.stats?.p50)} · P80 ${fmt(x.stats?.p80)}`).join("；")}`:"结构约束（待补分布）";
         const stateModeRows=s.redByR||[],stateModes=stateModeRows.length?stateModeRows.map(x=>x.mode==="direct"?"同R直接历史":"探索性组合分布").join(" / "):(s.redMode==="direct"?"同R直接历史":"探索性组合分布");
        const component=s.component||{},gold=component.gold||{},purple=component.purple||{},lowTier=component.lowTier||{},shadow=s.shadow;
        const range3=x=>x&&finite(x.lower)&&finite(x.mid)&&finite(x.upper)?`下限 ${fmt(x.lower)} · 中值 ${fmt(x.mid)} · 上限 ${fmt(x.upper)}`:"当前无可用分项";
         const shadow3=shadow&&finite(shadow.p20)&&finite(shadow.p50)&&finite(shadow.p80)?`P20 ${fmt(shadow.p20)} · P50 ${fmt(shadow.p50)} · P80 ${fmt(shadow.p80)}`:"结构约束（待补分布）";
         const shortRange=x=>x&&finite(x.lower)&&finite(x.mid)&&finite(x.upper)?`${fmt(x.lower)} / ${fmt(x.mid)} / ${fmt(x.upper)}`:"—",shortRed=red&&finite(red.p20)?`${fmt(red.p20)} / ${fmt(red.p50)} / ${fmt(red.p80)}`:"—";
         const pct=(Number(s.relativeWeight)||0)*100,width=maxStateWeight>0?(Number(s.relativeWeight)||0)/maxStateWeight*100:0;
         const liveBid=currentLiveBid(),stateProfit=finite(shadow?.p50)&&liveBid!==null?Number(shadow.p50)-liveBid:null;
         return `<details class="probability-state-row state-row-v04"><summary><div class="probability-state-label">G=${s.g??"—"} · P=${s.p??"—"} · ${rLabel}<small>合法结构 · 权重仅为旧 heuristic</small></div><div class="probability-state-weight" style="--state-weight:${width.toFixed(1)}%"><span><span>相对权重（未校准）</span><b>${pct.toFixed(1)}%</b></span><i></i></div><div class="state-shadow-compact">${escapeHtml(shadow3)}</div></summary><div class="probability-state-grid"><div class="probability-state-value gold" title="${escapeHtml(range3(gold))}"><span>金 · 下/中/上</span><b>${escapeHtml(shortRange(gold))}</b></div><div class="probability-state-value purple" title="${escapeHtml(range3(purple))}"><span>紫 · 下/中/上</span><b>${escapeHtml(shortRange(purple))}</b></div><div class="probability-state-value red" title="${escapeHtml(redText)} · ${escapeHtml(stateModes)}"><span>红 · P20/P50/P80</span><b>${escapeHtml(shortRed)}</b></div><div class="probability-state-value low" title="${escapeHtml(range3(lowTier))}"><span>蓝绿白 · 下/中/上</span><b>${escapeHtml(shortRange(lowTier))}</b></div><div class="probability-state-value whole" title="${escapeHtml(shadow3)}"><span>整仓 Shadow</span><b>${escapeHtml(shadow3.replaceAll(" · "," / ").replaceAll("P20 ","").replaceAll("P50 ","").replaceAll("P80 ",""))}</b></div><div class="state-profit-line"><span>当前价下的 State P50 购入价差</span><b class="state-bid-profit" data-state-p50="${finite(shadow?.p50)?Number(shadow.p50):""}">${stateProfit===null?"输入当前价":formatSignedWan(stateProfit)}</b></div></div></details>`;
      }).join("");
      const historyRows=(p.historyEvidence||[]).slice().sort((a,b)=>Number(b.similarity||0)-Number(a.similarity||0));
      const evidenceRow=x=>`<div class="probability-evidence-row"><strong title="${escapeHtml(x.playedAt||"")}">${escapeHtml(String(x.playedAt||"—").replace("T"," ").slice(0,16))} · ${escapeHtml(x.box||"未知箱型")}</strong><span>R=${Number.isFinite(Number(x.r))?x.r:"—"}</span><span title="${escapeHtml(x.redItems||"未记录红列表")}">${escapeHtml(x.redItems||"未记录红列表")}</span><span class="probability-evidence-total">${fmt(x.redTotal)} · 相似 ${Number(x.similarity||0)}%</span></div>`;
      const evidenceTop=historyRows.slice(0,3).map(evidenceRow).join("")||`<div class="probability-empty">前序没有可核验的完整红货列表；当前分布可能使用 bootstrap 组合模拟。</div>`;
      const evidenceMore=historyRows.length>3?`<details class="probability-evidence-more"><summary>展开全部历史证据（${historyRows.length} 条）</summary><div class="probability-evidence-list">${historyRows.slice(3).map(evidenceRow).join("")}</div></details>`:"";
      const tiers=(p.tiers||[]).map(x=>`<span class="prob-tier"><b>${escapeHtml(x.tier)}</b><small>${escapeHtml(x.range||redTierRange(x.tier))} · 暂定 value bucket</small><strong>${x.count}件</strong><small>原始 ${(Number(x.rawObservationRate||0)*100).toFixed(0)}% · 原始平滑 ${x.smoothedRawRate==null?"—":(x.smoothedRawRate*100).toFixed(0)+"%"}</small><small>历史加权 ${x.historicalWeightedRate==null?"—":(x.historicalWeightedRate*100).toFixed(0)+"%"} · 当前局 ${x.currentWeightedRate==null?"—":(x.currentWeightedRate*100).toFixed(0)+"%"}</small></span>`).join("");
      const p10p90=dist.tailP10Ready&&finite(total?.p10)&&finite(total?.p90)?`${fmt(total.p10)}—${fmt(total.p90)}`:"探索性/低样本";
      const p5p95=dist.tailP95Ready&&finite(total?.p05)&&finite(total?.p95)?`${fmt(total.p05)}—${fmt(total.p95)}`:"探索性/低样本";
      const tailText=tail.observedMax!=null?`最高已观察单件 ${fmt(tail.observedMax)} · 当前抽样最高 ${fmt(tail.sampledMax)} · Jackpot ${tail.jackpotN||0}件`:`未观察到可核验大奖红`;
      const details=`<details class="probability-details"><summary>展开概率细节 · ${escapeHtml(p.status||"当前分布")}</summary><div class="probability-details-body"><div class="probability-tiers">${tiers||`<div class="probability-empty">暂无足够的红货分档样本</div>`}</div><div class="probability-tail"><b>尾部分位：</b>P10—P90 ${p10p90} · P5—P95 ${p5p95}。<b>当前样本：</b>${escapeHtml(distributionText)}。<b>状态口径：</b>${escapeHtml(modeText)}。<b>尾部：</b>${escapeHtml(tailText)}。分档区间是暂定 value bucket，原始观察占比与当前局加权概率参考分开显示。理论大奖仍保留在 Feasible Range，不进入旧 v0.3 工作中心。${escapeHtml(p.heuristicNote||"")}</div></div></details>`;
      const coverageSummary=stateCandidates.length>0?`${stateCandidates.length} 个候选结构（${statesWithShadow} 个具备价值分布，${statesStructuralOnly} 个仅保留结构约束）`:"无可用候选结构";
      const stateDetail=stateCandidates.length?`<section class="state-value-map-live"><div class="state-value-map-live-head"><strong>G/P/R结构 → 整仓总价值</strong><span>${escapeHtml(coverageSummary)}</span></div><div class="probability-state-map">${stateRows}</div></section>`:`<div class="probability-empty">当前没有可用 G/P/R 候选，无法把结构映射到整仓价值。</div>`;
       const empirical=p.empiricalStatePrior||null,calibrated=p.shadowCalibrated||null,shadowSidecarHtml=`<details class="algorithm-inline-details"><summary>v0.6 Shadow 旁路 · State先验与区间校准</summary><div class="algorithm-inline-details-body"><div class="field-help">正式 v0.5 / Legacy heuristic 未被替换；这里仅记录分层经验先验和 OOS 残差校准，样本不足时明确回退。</div>${empirical?`<div class="probability-guard"><b>Empirical State Prior：</b>${escapeHtml(empirical.status||"—")} · 回退层 ${escapeHtml(empirical.fallbackLevel||"global")} · localN ${empirical.localN||0} · parentN ${empirical.parentN||0} · 收缩权重 ${((Number(empirical.shrinkageWeight)||0)*100).toFixed(0)}%<br><span>R数量模型：${escapeHtml(empirical.rQuantity?.fallbackLevel||"global")} · localN ${empirical.rQuantity?.localN||0} · parentN ${empirical.rQuantity?.parentN||0}</span></div>`:"<div class=\"probability-empty\">暂无可用 realized State 先验样本</div>"}${calibrated?`<div class="probability-guard"><b>Calibrated Shadow：</b>${escapeHtml(calibrated.status||"—")} · residualN ${calibrated.residualN||0} · Raw ${fmt(calibrated.raw?.p20)} / ${fmt(calibrated.raw?.p50)} / ${fmt(calibrated.raw?.p80)} → Calibrated ${fmt(calibrated.calibrated?.p20)} / ${fmt(calibrated.calibrated?.p50)} / ${fmt(calibrated.calibrated?.p80)}<br><span>中心保持 Raw P50；只校准区间宽度，不反馈正式推荐。</span></div>`:"<div class=\"probability-empty\">暂无 Raw Shadow 或 OOS 残差不足</div>"}</div></details>`,probabilityDetails=`<details class="algorithm-inline-details"><summary>展开概率细节 / 历史证据 / 尾部说明</summary><div class="algorithm-inline-details-body"><div class="probability-guard"><b>概率旁路：</b>红货典型分布不等于 Feasible Range，不会修改旧 v0.3 工作估值或出价。${escapeHtml(typicalNote)}</div><div class="probability-section"><div class="probability-section-head"><strong>历史证据 · 这次分布由哪些真实红货支撑</strong><span>Top 3 · 相似度仅说明来源</span></div><div class="probability-evidence-list">${evidenceTop}</div>${evidenceMore}</div>${details}${shadowSidecarHtml}</div></details>`;
      return `<section class="probability-summary probability-live probability-compact"><div class="probability-live-intro"><div class="probability-kicker">PROBABILITY SHADOW · STATE LINK</div><span>${escapeHtml(p.status||"样本状态未知")}</span></div>${stateDetail}${probabilityDetails}</section>`;
    }
    /**
     * Small, deterministic linkage probe for the live Probability view.
     * It intentionally runs against temporary in-memory records only: no
     * history, center, or persisted data is changed.  Run from the console as
     * window.runProbabilityLinkageSelfTest() when auditing a build.
     */
    function probabilityLinkageSelfTest(){
      const itemA=RED_ITEMS.find(x=>x[1]===81088)||RED_ITEMS[0],itemB=RED_ITEMS.find(x=>x[1]===76008)||RED_ITEMS[1],itemKnown=RED_ITEMS.find(x=>x[1]===200201)||RED_ITEMS[9];
      const redText=`${itemA[0]} ${itemA[1]} + ${itemB[0]} ${itemB[1]}`;
      const synthetic=[1,2,3].map(i=>({id:`__probability_self_test_${i}`,playedAt:`2099-01-0${i}T00:00:00`,date:`2099-01-0${i}`,venue:"自测场地",box:"自测箱型",q:5,purpleCount:1,goldCount:2,redCount:2,redInventoryComplete:true,settlementVerifiedRedItems:redText,redItems:redText,actualTotal:itemA[1]+itemB[1]+i*1000,settlement:{status:"verified",redInventoryComplete:true,verifiedRedItems:redText,redCount:2,realizedState:{gold:2,purple:1,red:2,complete:true,source:"self-test",confidence:"high"}}}));
      const originalRecords=state.records;
      const base={playedAt:"2100-01-01T00:00:00",venue:"自测场地",box:"自测箱型",q:5,avg:null,purpleAvg:null,goldTotal:null,goldGrid:null,purple:3,goldCount:null,redCount:null,minGold:0,minPurple:0,minRed:0,knownGold:[],knownPurple:[],knownRed:[],publicInfo:{},roundingMode:"floor"};
      const stateR0=[{g:2,p:3,r:0,gold:{unconstrained:true,matches:[]},purple:{unconstrained:true,matches:[]}}];
      const stateR2=[{g:2,p:1,r:2,gold:{unconstrained:true,matches:[]},purple:{unconstrained:true,matches:[]}}];
      let profiles;
      try{
        state.records=[...originalRecords,...synthetic];
        profiles={r0:redProbabilityProfile({...base,redCount:0,purple:3},stateR0,[]),r2:redProbabilityProfile({...base,redCount:2,purple:1},stateR2,[]),known:redProbabilityProfile({...base,redCount:2,purple:1,knownRed:[{name:itemKnown[0],price:itemKnown[1],size:itemKnown[2]}]},stateR2,[])};
      }finally{state.records=originalRecords;}
      const r0=profiles.r0,r2=profiles.r2,known=profiles.known;
      const r0Values=[r0?.currentTotal?.p20,r0?.currentTotal?.p50,r0?.currentTotal?.p80],r0Ok=!!r0?.currentTotal&&r0Values.every(x=>Number(x)===0);
      const r2Buckets=(r2?.stateDistributions||[]).map(x=>x.r),r2Ok=r2Buckets.length>0&&r2Buckets.every(x=>x===2);
      const knownFloor=Number(known?.currentTotal?.min);const knownOk=Number.isFinite(knownFloor)&&knownFloor>=Number(itemKnown[1]);
      return {ok:r0Ok&&r2Ok&&knownOk,cases:{R0:{ok:r0Ok,p20:r0Values[0]??null,p50:r0Values[1]??null,p80:r0Values[2]??null},R2:{ok:r2Ok,buckets:r2Buckets,p20:r2?.currentTotal?.p20??null,p50:r2?.currentTotal?.p50??null,p80:r2?.currentTotal?.p80??null},R2KnownRed:{ok:knownOk,knownRed:itemKnown[1],min:knownFloor,p20:known?.currentTotal?.p20??null,p50:known?.currentTotal?.p50??null,p80:known?.currentTotal?.p80??null}}};
    }
    window.runProbabilityLinkageSelfTest=probabilityLinkageSelfTest;
    function resolveSessionCosts(ctx={}, d={}){
      const costObj = ctx.costs || ctx.costBreakdown || d?.costs || d?.costBreakdown || {};
      const entry = Math.max(0, Number(costObj.entry ?? ctx.costEntry ?? 5000) || 0);
      const intel = Math.max(0, Number(costObj.intel ?? costObj.info ?? ctx.costIntel ?? ctx.costInfo ?? 0) || 0);
      const other = Math.max(0, Number(costObj.other ?? ctx.costOther ?? 0) || 0);
      const sunkExplicit = Number(costObj.sunkCost ?? ctx.sunkCost ?? d?.sunkCost);
      const sunkCost = Number.isFinite(sunkExplicit) && sunkExplicit >= 0 ? sunkExplicit : (entry + intel + other);
      const futureExplicit = Number(costObj.futureIncrementalCost ?? ctx.futureIncrementalCost ?? d?.futureIncrementalCost);
      const futureIncrementalCost = Number.isFinite(futureExplicit) && futureExplicit >= 0 ? futureExplicit : 0;
      const allCosts = sunkCost + futureIncrementalCost;
      return { entry, intel, other, sunkCost, futureIncrementalCost, allCosts };
    }
    window.resolveSessionCosts = resolveSessionCosts;

    function calculateStateEntropy(states=[]){
      if(!states || !states.length) return 0;
      const totalWeight = states.reduce((sum, s) => sum + (Number(s.weight ?? s.priorProbability ?? 1) || 1), 0);
      if(totalWeight <= 0) return 0;
      let entropy = 0;
      for(const s of states){
        const w = (Number(s.weight ?? s.priorProbability ?? 1) || 1) / totalWeight;
        if(w > 0) entropy -= w * Math.log2(w);
      }
      return Number(entropy.toFixed(3));
    }
    window.calculateStateEntropy = calculateStateEntropy;

    function calculateShadowWidth(profile){
      const source = profile?.shadowCalibrated?.calibrated || profile?.probabilityProfile?.shadowWhole || profile?.shadowWhole;
      if(source && Number.isFinite(Number(source.p80)) && Number.isFinite(Number(source.p20))){
        return Math.max(0, Math.round(Number(source.p80) - Number(source.p20)));
      }
      return 0;
    }
    window.calculateShadowWidth = calculateShadowWidth;

    function createIntelEventRecord({
      round=1,
      toolType="unknown",
      timestamp=new Date().toISOString(),
      before={ candidateStateCount: 0, stateEntropy: 0, shadowWidth: 0, decisionClass: "unknown" },
      observed={},
      after={ candidateStateCount: 0, stateEntropy: 0, shadowWidth: 0, decisionClass: "unknown" },
      incrementalCost=0
    }={}){
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
    window.createIntelEventRecord = createIntelEventRecord;

    function calculateV06DecisionLines(ctx={}, d={}, liveBid=null){
      if (typeof AuctionEngineV06 !== "undefined" && typeof AuctionEngineV06.calculateV06DecisionLines === "function") {
        return AuctionEngineV06.calculateV06DecisionLines(ctx, d, liveBid);
      }
      ctx = ctx || {};
      d = d || {};
      const costInfo = resolveSessionCosts(ctx, d);
      const solverStatus = String(d?.solverStatus || ctx?.solverStatus || "valid");
      const finite = v => Number.isFinite(Number(v)) && Number(v) > 0;

      const calibrated = d?.shadowCalibrated?.calibrated || null;
      const raw = d?.probabilityProfile?.shadowWhole || d?.rawShadow || null;

      const candidateStates = d?.probabilityProfile?.stateCandidates || d?.states || [];
      const stateCount = Array.isArray(candidateStates) ? candidateStates.length : (Array.isArray(d?.candidateGs) ? d.candidateGs.length : 0);
      const hasCandidateStates = stateCount > 0;

      let statesWithShadow = 0;
      let statesStructuralOnly = 0;
      if (Array.isArray(d?.probabilityProfile?.stateCandidates)) {
        statesWithShadow = d.probabilityProfile.stateCandidates.filter(s => s.shadow && finite(s.shadow.p50)).length;
        statesStructuralOnly = d.probabilityProfile.stateCandidates.length - statesWithShadow;
      } else if (hasCandidateStates) {
        statesStructuralOnly = stateCount;
      }

      const hardFloor = finite(d?.hardFloor) ? Number(d.hardFloor) : finite(d?.formalValue?.theoreticalMin) ? Number(d.formalValue.theoreticalMin) : finite(d?.low) ? Number(d.low) : null;
      const theoreticalMin = finite(d?.formalValue?.theoreticalMin) ? Number(d.formalValue.theoreticalMin) : finite(d?.low) ? Number(d.low) : null;
      const theoreticalMax = finite(d?.formalValue?.theoreticalMax) ? Number(d.formalValue.theoreticalMax) : finite(d?.high) ? Number(d.high) : null;
      const structuralCenter = finite(d?.structuralCenter) ? Number(d.structuralCenter) : finite(d?.formalValue?.ev) ? Number(d.formalValue.ev) : finite(d?.center) ? Number(d.center) : null;
      const hasStructuralEvidence = hasCandidateStates || hardFloor !== null || theoreticalMin !== null || structuralCenter !== null;

      const isExplicitlySuppressed = d?.recommendationSuppressed || ["incomplete", "fallback", "timeout", "no-match", "stale"].includes(solverStatus);

      let degradationLevel = "insufficient";
      let isSuppressed = false;
      let valueP50 = null;
      let valueSource = "none";

      if (isExplicitlySuppressed) {
        degradationLevel = "insufficient";
        isSuppressed = true;
      } else if (finite(raw?.p50) || finite(calibrated?.p50)) {
        degradationLevel = "full_shadow";
        valueP50 = finite(raw?.p50) ? Number(raw.p50) : Number(calibrated.p50);
        valueSource = "shadow";
        isSuppressed = false;
      } else if (hasStructuralEvidence) {
        degradationLevel = "structural_only";
        valueP50 = null;
        valueSource = "structural-only";
        isSuppressed = false;
      } else {
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

      let safeBuy = null;
      let recommendedMax = null;
      let chaseLimit = null;

      if (degradationLevel === "full_shadow" && valueP50 !== null) {
        const profitCap = valueP50 - costInfo.allCosts - targetProfit;
        const roiCap = hasTargetROI ? valueP50 / (1 + effectiveROI) - costInfo.allCosts : Infinity;
        safeBuy = Math.max(0, Math.floor(Math.min(profitCap, roiCap)));
        recommendedMax = Math.max(0, Math.floor(valueP50 - costInfo.allCosts));
        chaseLimit = Math.max(0, Math.floor(valueP50 - costInfo.futureIncrementalCost));
      }

      const structuralReferenceBid = (degradationLevel === "structural_only" && structuralCenter !== null) ? Math.max(0, Math.floor(structuralCenter - costInfo.allCosts)) : null;

      const targetLine = safeBuy;
      const globalLine = recommendedMax;
      const marginalLine = chaseLimit;

      const bid = liveBid !== null && liveBid !== undefined && liveBid !== "" && typeof liveBid !== "boolean" && Number.isFinite(Number(liveBid)) && Number(liveBid) >= 0 ? Number(liveBid) : null;
      const expectedProfit = bid !== null && valueP50 !== null && costInfo.allCosts !== null ? Math.floor(valueP50 - costInfo.allCosts - bid) : null;
      let roiOnTotalSpend = null;
      let roiOnPurchase = null;
      if (bid !== null && valueP50 !== null) {
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

      // 候选状态实际推导范围
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
      if (statesWithShadow > 0 && statesStructuralOnly > 0) {
        missingReason = `${stateCount} 个候选结构中仅 ${statesWithShadow} 个具备历史分布，${statesStructuralOnly} 个仅保留结构约束，整体置信不足以生成整仓 P50`;
      } else if (stateCount > 0 && statesWithShadow === 0) {
        if (redMin !== null && redMin > 0 && redMin === redMax) {
          missingReason = `当前 R=${redMin} 缺少同 R 真实历史对局样本，无法生成整仓 P50`;
        } else {
          missingReason = `当前 ${stateCount} 个候选结构均缺少直接历史样本，仅保留确定性整数拆分与藏品上下界约束`;
        }
      }

      // Level 3 缺失情报诊断清单
      const missingClues = [];
      const hasQ = ctx.q !== null && ctx.q !== undefined && ctx.q !== "" && Number.isFinite(Number(ctx.q)) && Number(ctx.q) > 0;
      const hasGoldPrice = (ctx.avg !== null && ctx.avg !== undefined && ctx.avg !== "" && Number.isFinite(Number(ctx.avg)) && Number(ctx.avg) > 0) ||
                           (ctx.goldTotal !== null && ctx.goldTotal !== undefined && ctx.goldTotal !== "" && Number.isFinite(Number(ctx.goldTotal)) && Number(ctx.goldTotal) > 0) ||
                           (ctx.publicInfo?.goldGrid !== null && ctx.publicInfo?.goldGrid !== undefined && ctx.publicInfo?.goldGrid !== "");
      const hasPurple = ctx.purple !== null && ctx.purple !== undefined && ctx.purple !== "" && Number.isFinite(Number(ctx.purple)) && Number(ctx.purple) >= 0;
      const hasKnown = (ctx.knownGold || []).length > 0 || (ctx.knownPurple || []).length > 0 || (ctx.knownRed || []).length > 0;
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
        stateCount,
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
    window.calculateV06DecisionLines = calculateV06DecisionLines;

    function currentLiveBid(){
      const raw=window.__liveBidValue;
      return raw!==null&&raw!==undefined&&raw!==""&&Number.isFinite(Number(raw))?Math.max(0,Math.round(Number(raw))):null;
    }
    function decisionSessionCost(d=currentAnalysis?.workingDecision){
      return resolveSessionCosts(currentAnalysis, d).allCosts;
    }
    function formatSignedWan(value){
      const n=Number(value);if(!Number.isFinite(n))return "—";
      return `${n>0?"+":n<0?"−":""}${fmtWan(Math.abs(n))}`;
    }
    function interpolatedLossPercent(stats,bid){
      const b=Number(bid);if(!stats||!Number.isFinite(b))return null;
      const min=Number(stats.min),max=Number(stats.max);if(Number.isFinite(min)&&Number.isFinite(max)&&min===max)return b<min?0:b>max?100:50;
      const anchors=[{value:stats.min,p:0},{value:stats.p20,p:20},{value:stats.p50,p:50},{value:stats.p80,p:80},{value:stats.max,p:100}].filter(x=>Number.isFinite(Number(x.value))).map(x=>({...x,value:Number(x.value)})).sort((a,b)=>a.value-b.value||a.p-b.p);
      if(anchors.length<2)return null;if(b<=anchors[0].value)return 0;if(b>=anchors.at(-1).value)return 100;
      for(let i=1;i<anchors.length;i++){const a=anchors[i-1],z=anchors[i];if(b<=z.value){if(z.value===a.value)return Math.max(a.p,z.p);return a.p+(z.p-a.p)*(b-a.value)/(z.value-a.value);}}
      return null;
    }
    function wholeValueAxisHtml(d){
      const liveBid = currentLiveBid();
      const lines = calculateV06DecisionLines(currentAnalysis, d, liveBid);
      const market = d?.marketPrediction || {};
      const finite = value => Number.isFinite(Number(value));
      let points = [];
      if (lines.degradationLevel === "full_shadow") {
        points = [
          { label: "稳健买入", value: lines.safeBuy, cls: "target" },
          { label: "建议最高", value: lines.recommendedMax, cls: "global" },
          { label: "极限追价", value: lines.chaseLimit, cls: "marginal" },
          { label: "市场 P50", value: market.p50, cls: "market" },
          { label: "整仓 P50", value: lines.valueP50, cls: "p50" },
        ];
      } else if (lines.degradationLevel === "structural_only") {
        points = [
          { label: "已确认下限", value: lines.hardFloor, cls: "target" },
          { label: "结构参考", value: lines.structuralReferenceBid, cls: "global" },
          { label: "理论上限", value: lines.theoreticalMax, cls: "marginal" },
          { label: "市场 P50", value: market.p50, cls: "market" },
        ];
      }
      points = points.filter(x => finite(x.value) && Number(x.value) >= 0).map(x => ({ ...x, value: Number(x.value) }));
      if(!points.length) return "";
      const max = Math.max(1, ...points.map(x => x.value), liveBid ?? 0) * 1.08;
      const marker = x => `<span class="whole-value-axis-marker ${x.cls || ""}" style="left:${Math.max(0, Math.min(100, x.value / max * 100)).toFixed(2)}%"><i>${escapeHtml(x.label)} ${fmtWan(x.value)}</i></span>`;
      const title = lines.degradationLevel === "full_shadow" ? "统一金额坐标系标定轴" : "结构价值约束标定轴 (低置信参考)";
      return `<section class="whole-value-axis"><div class="whole-value-axis-head"><strong>${title}</strong><span>${points.map(x => x.label).join(" · ")} 并列标定</span></div><div class="whole-value-axis-track" id="liveBidAxis" data-axis-max="${max}">${points.map(marker).join("")}<span id="liveBidAxisMarker" class="whole-value-axis-marker current" style="${liveBid === null ? "display:none;" : ""}left:${liveBid === null ? 0 : Math.max(0, Math.min(100, liveBid / max * 100)).toFixed(2)}%"></span></div><div class="whole-value-axis-legend">${points.map(x => `<span class="${x.cls}">${escapeHtml(x.label)} <b>${fmtWan(x.value)}</b></span>`).join("")}<span id="liveBidAxisLegend" class="current" style="${liveBid === null ? "display:none" : ""}">当前叫价 <b>${liveBid === null ? "—" : fmtWan(liveBid)}</b></span></div></section>`;
    }
    function updateLiveBid(raw){
      const parsed=String(raw??"").trim()===""?null:Math.max(0,Math.round(Number(raw)||0));window.__liveBidValue=parsed;
      const input=document.getElementById("liveBidInput"),v06Input=document.getElementById("v06LiveBidInput");if(input&&parsed!==null&&Number(input.value)!==parsed)input.value=parsed;if(input&&parsed===null)input.value="";if(v06Input&&parsed!==null&&Number(v06Input.value)!==parsed)v06Input.value=parsed;if(v06Input&&parsed===null)v06Input.value="";
      const d=currentAnalysis?.workingDecision;if(!d)return;
      const lines=calculateV06DecisionLines(currentAnalysis, d, parsed);
      const v06Panel=document.querySelector("#resultPanel .v06-decision-panel");
      if(v06Panel){
        const safeBuy=Number(v06Panel.dataset.targetLine),recMax=Number(v06Panel.dataset.globalLine),chaseLimit=Number(v06Panel.dataset.marginalLine);
        const solverStatus=v06Panel.dataset.solverStatus||"valid",stale=document.getElementById("resultPanel")?.classList.contains("solver-stale");
        const within=line=>Number.isFinite(line)&&parsed!==null&&parsed<=line;
        let action="等待输入当前叫价";
        if(stale){
          action="旧结果已过期 · 禁止依据追价";
        }else if(lines.degradationLevel==="insufficient"){
          action=solverStatus==="incomplete"?"等待完整求解 · 不生成正式推荐":"当前信息不足 · 暂不报价";
        }else if(lines.degradationLevel==="partial_shadow"||lines.degradationLevel==="structural_only"){
          action=parsed===null?"等待输入当前叫价":
                 lines.hardFloor!==null&&parsed<=lines.hardFloor?"🟢 当前价低于已确认下限 · 确定盈利":
                 lines.structuralReferenceBid!==null&&parsed<=lines.structuralReferenceBid?"🟡 在低置信参考出价内 · 请自行评估":
                 lines.theoreticalMax!==null&&parsed>lines.theoreticalMax?"🔴 超过理论价值上限 · 确定亏损":
                 "🟡 结构价值区间内 · 缺少完整概率分布";
        }else{
          action=parsed===null?"等待输入当前叫价":
                 within(safeBuy)?"🟢 稳健买入区 · 空间充足":
                 within(recMax)?"🟢 建议出价内 · 仍有保本空间":
                 within(chaseLimit)?"🟡 已超建议最高价 · 仅剩边际追价空间":
                 "🔴 超过极限追价线 · 建议停止";
        }
        const statusEl=document.getElementById("v06DecisionStatus"),actionEl=document.getElementById("v06DecisionActionText");
        if(statusEl){statusEl.textContent=action;statusEl.classList.toggle("stop",action.includes("停止")||action.includes("暂停")||action.includes("过期")||action.includes("亏损"));}
        if(actionEl)actionEl.textContent=action;
      }
      const marginEl=document.getElementById("v06MarginRemain"),summaryEl=document.getElementById("v06ProfitSummary"),marginBox=marginEl?.closest(".margin-kpi");
      if(marginEl){
        if(lines.degradationLevel==="full_shadow"&&lines.recommendedMax!==null){
          const rem=parsed===null?null:(lines.recommendedMax-parsed);
          marginEl.textContent=rem===null?"输入当前价":formatSignedWan(rem);
          if(marginBox){
            marginBox.classList.toggle("positive",rem!==null&&rem>=0);
            marginBox.classList.toggle("negative",rem!==null&&rem<0);
            marginBox.classList.toggle("caution",rem===null);
          }
        }else if(lines.degradationLevel==="partial_shadow"||lines.degradationLevel==="structural_only"){
          const refBid=lines.structuralReferenceBid;
          const rem=parsed===null?null:(refBid!==null?refBid-parsed:(lines.hardFloor!==null?lines.hardFloor-parsed:null));
          marginEl.textContent=refBid!==null?fmtWan(refBid):(lines.hardFloor!==null?fmtWan(lines.hardFloor):"—");
          if(summaryEl){
            summaryEl.textContent=parsed===null?`扣总成本 ${fmtWan(lines.costInfo.allCosts)} · 仅供参考`:`距结构参考 ${formatSignedWan(rem)}`;
          }
          if(marginBox){
            marginBox.classList.toggle("positive",rem!==null&&rem>=0);
            marginBox.classList.toggle("negative",rem!==null&&rem<0);
            marginBox.classList.toggle("caution",rem===null);
          }
        }
      }
      if(summaryEl&&lines.degradationLevel==="full_shadow"&&lines.valueP50!==null){
        const gross=parsed===null?null:(lines.valueP50-parsed),net=parsed===null?null:(lines.recommendedMax-parsed);
        summaryEl.textContent=`预计竞得价差 ${gross===null?"—":formatSignedWan(gross)} · 距建议最高价 ${net===null?"—":formatSignedWan(net)}`;
      }
      const purchaseLabel=document.getElementById("livePurchaseProfit")?.closest(".v04-outcome")?.querySelector("span"),allInLabel=document.getElementById("liveAllInProfit")?.closest(".v04-outcome")?.querySelector("span"),riskLabel=document.getElementById("liveLossRisk")?.closest(".v04-outcome")?.querySelector("span"),hasShadow=Number.isFinite(Number(d.probabilityProfile?.shadowWhole?.p50)),anchorLabel=hasShadow?"Shadow P50":"工作估值（Shadow不足）";if(purchaseLabel)purchaseLabel.textContent=`${anchorLabel}购入价差`;if(allInLabel)allInLabel.textContent=`${anchorLabel}全成本结果`;if(riskLabel)riskLabel.textContent=hasShadow?"低于当前价的粗略比例":"亏损风险";
      const shadow=d.probabilityProfile?.shadowWhole||{},anchor=Number.isFinite(Number(shadow.p50))?Number(shadow.p50):Number(d.center)||0,cost=lines.costInfo.allCosts,purchase=parsed===null?null:anchor-parsed,allIn=parsed===null?null:anchor-parsed-cost,risk=parsed===null?null:interpolatedLossPercent(shadow,parsed),legacy=Number(d.recommendedMaxBid??d.balancedCap);
      const paint=(id,value)=>{const el=document.getElementById(id);if(!el)return;el.textContent=value===null?"输入当前价":formatSignedWan(value);const box=el.closest(".v04-outcome");if(box){box.classList.toggle("positive",value!==null&&value>=0);box.classList.toggle("negative",value!==null&&value<0);box.classList.toggle("caution",value===null);}};
      paint("livePurchaseProfit",purchase);paint("liveAllInProfit",allIn);
      const riskEl=document.getElementById("liveLossRisk");if(riskEl)riskEl.textContent=risk===null?"样本不足":`约 ${Math.round(risk)}%`;
      const roiTotalEl=document.getElementById("liveRoiTotalSpend");if(roiTotalEl)roiTotalEl.textContent=lines.roiOnTotalSpend===null?"—":`${(lines.roiOnTotalSpend*100).toFixed(1)}%`;
      document.querySelectorAll(".state-bid-profit").forEach(el=>{const p50=Number(el.dataset.stateP50);el.textContent=parsed!==null&&Number.isFinite(p50)?formatSignedWan(p50-parsed):"输入当前价";});
      const axis=document.getElementById("liveBidAxis"),marker=document.getElementById("liveBidAxisMarker"),legend=document.getElementById("liveBidAxisLegend");if(marker){marker.style.display=parsed===null?"none":"";if(parsed!==null)marker.style.left=`${Math.max(0,Math.min(100,parsed/Math.max(1,Number(axis?.dataset.axisMax)||1)*100)).toFixed(2)}%`;}if(legend){legend.style.display=parsed===null?"none":"";legend.innerHTML=parsed===null?"":`当前价 <b>${fmtWan(parsed)}</b>`;}
      const warning=document.getElementById("liveBidWarning");if(warning){const over=parsed!==null&&Number.isFinite(legacy)&&parsed>legacy;warning.classList.toggle("visible",over);warning.textContent=over?`当前价比 v0.3 平衡参考线高 ${fmtWan(parsed-legacy)}。这不是强制拦截，但请明确记录你为何继续跟价。`:"";}
    }
    window.updateLiveBid=updateLiveBid;
    window.bumpLiveBid=function(delta){updateLiveBid((currentLiveBid()??0)+Number(delta||0));};
    window.useLiveBidReference=function(value){updateLiveBid(Number(value)||0);};
    function decisionMetrics(d){
      if(d?.recommendationSuppressed&&d.fieldConditionAnalysis?.sparkleEvidence){const evidence=d.fieldConditionAnalysis?.sparkleEvidence||{},count=Number.isInteger(evidence.count)?`${evidence.count} 件`:`数量未知`,range=Number.isFinite(evidence.lower)&&Number.isFinite(evidence.upper)?`${fmtWan(evidence.lower)} — ${fmtWan(evidence.upper)}`:"待补 1×1 转换数量",known=Number(evidence.knownCount)||0;return `<section class="decision-summary"><div class="v04-decision-console"><div class="v04-decision-head"><div><h3>闪耀之心 · 证据边界模式</h3><p>宝石抽取概率未知，普通图鉴分项、Shadow、推荐价和出价模拟器已停用。</p></div><span class="v04-data-grade low">禁止伪概率推荐</span></div><div class="v04-kpi-grid"><div class="v04-kpi guard"><span>转换数量</span><strong>${escapeHtml(count)}</strong><small>需要轮廓/结算证据</small></div><div class="v04-kpi"><span>证据价值范围</span><strong>${escapeHtml(range)}</strong><small>不是概率区间</small></div><div class="v04-kpi"><span>已确认宝石</span><strong>${known} 件</strong><small>合计 ${fmtWan(evidence.knownTotal??0)}</small></div><div class="v04-kpi"><span>单件理论边界</span><strong>${fmtWan(evidence.unitMin)} — ${fmtWan(evidence.unitMax)}</strong><small>${Number(evidence.targetPoolSize)||0} 件官方宝石目标池</small></div></div><div class="callout" style="margin-top:12px"><span class="dot"></span><div><strong>本模式暂不生成最高出价。</strong>只有补齐转换件数与真实宝石清单后，才把已知合计和未知件理论上下界写入证据；不会把等概率假设当成结果。</div></div></div></section>`;}
      const uncertainty=String(d.confidence).includes("低")||(!d.hasHardPrice&&d.blindSpots?.redCount)?"高":String(d.confidence).includes("高")?"低":"中",unresolved=d.infoMode?.id==="goldAvgPurple"&&((d.candidateGs?.length||0)>1||d.quantitiesResolved===false),modeTitle=`${d.infoMode?.title||"混合情报"}${unresolved?" · 仍缺金/红拆分":""}`;
      const legacy=Number(d.recommendedMaxBid??d.balancedCap)||0,guard=Number(d.conservativeLossLine??d.cap)||0,shadow=d.probabilityProfile?.shadowWhole||{},anchor=Number.isFinite(Number(shadow.p50))?Number(shadow.p50):Number(d.center)||0,cost=decisionSessionCost(d),allInBreakEven=Math.max(0,anchor-cost),liveBid=currentLiveBid(),purchase=liveBid===null?null:anchor-liveBid,allIn=liveBid===null?null:anchor-liveBid-cost,risk=liveBid===null?null:interpolatedLossPercent(shadow,liveBid),states=d.probabilityProfile?.stateCandidates||[],directGames=Number(d.probabilityProfile?.currentDistribution?.directGames)||0,grade=d.quantitiesResolved&&directGames>=3?"good":states.length>4||!directGames?"low":"",gradeText=d.quantitiesResolved?`结构已锁 · 直接样本 ${directGames} 局`:`候选 ${states.length||"—"} · 直接样本 ${directGames} 局`;
      const tailGuard=d.probabilityProfile?.tailGuard||{},tailGuardHtml=tailGuard.relevant&&tailGuard.level!=="calibrated"?`<div class="callout" style="margin-top:10px"><span class="dot"></span><div><strong>红色尾部尚未校准：</strong>${escapeHtml(tailGuard.reason||"同 R 直接样本不足")}。Shadow P80 只是“约 80% 样本不超过此值”的分位数，绝不是最高价；红色极端尾部仍可能把实际整箱价推到 P80 之上。</div></div>`:"",solverNote=d.solverStatus==="incomplete"?`<div class="callout" style="margin-top:10px"><span class="dot"></span><div><strong>候选搜索未完成：</strong>已找到的结构只作预览；正式推荐线已暂停，等完整求解返回后再决定。</div></div>`:"";
      const outcomeClass=value=>value===null?"caution":value>=0?"positive":"negative",splitNote=unresolved?`<div class="decision-note compact"><strong>主路径 ≠ 已经精确</strong> · Q − P = G + R；金均价只能筛选金色候选，仍缺金/红拆分。</div>`:"";
      const anchorName=Number.isFinite(Number(shadow.p50))?"Shadow P50":"工作估值（Shadow不足）",roughRiskName=Number.isFinite(Number(shadow.p50))?"低于当前价的粗略比例":"亏损风险";
      return `<section class="decision-summary"><div class="v04-decision-console"><div class="v04-decision-head"><div><h3>旧版实战决策台 · v0.5 对照</h3><p>保留历史 Heuristic 参考；主决策已收敛至上方 Release Candidate 控制台。</p></div><span class="v04-data-grade ${grade}">${escapeHtml(gradeText)}</span></div><div class="v04-kpi-grid"><div class="v04-kpi"><span>v0.5 工作估值</span><strong>${fmtWan(d.center)}</strong><small>结构与历史的旧中心</small></div><div class="v04-kpi shadow"><span>Shadow P50</span><strong>${Number.isFinite(Number(shadow.p50))?fmtWan(shadow.p50):"—"}</strong><small>概率分布中位</small></div><div class="v04-kpi balance"><span>v0.3 平衡参考线</span><strong>${fmtWan(legacy)}</strong><small>heuristic · 非保证</small></div><div class="v04-kpi guard"><span>保守防亏参考</span><strong>${fmtWan(guard)}</strong><small>仍非保证防亏</small></div><div class="v04-kpi"><span>边际盈亏平衡</span><strong>${fmtWan(anchor)}</strong><small>${escapeHtml(anchorName)} · 不追偿已花成本</small></div><div class="v04-kpi"><span>全成本回收</span><strong>${fmtWan(allInBreakEven)}</strong><small>已扣本局成本 ${fmtWan(cost)}</small></div></div><div class="v04-bid-simulator"><div class="v04-bid-entry"><label for="liveBidInput"><span>游戏当前价 / 我的最高跟价</span><small>只做模拟，不替你出价</small></label><div class="v04-bid-row"><input id="liveBidInput" type="number" min="0" step="1000" value="${liveBid??""}" placeholder="输入当前价" oninput="updateLiveBid(this.value)"></div><div class="v04-bid-quick"><button type="button" onclick="bumpLiveBid(10000)">+1W</button><button type="button" onclick="bumpLiveBid(50000)">+5W</button><button type="button" onclick="bumpLiveBid(100000)">+10W</button><button type="button" onclick="useLiveBidReference(${legacy})">用旧平衡线</button></div></div><div class="v04-bid-outcomes"><div class="v04-outcome ${outcomeClass(purchase)}"><span>${escapeHtml(anchorName)}购入价差</span><strong id="livePurchaseProfit">${purchase===null?"输入当前价":formatSignedWan(purchase)}</strong><small>${escapeHtml(anchorName)} − 当前价</small></div><div class="v04-outcome ${outcomeClass(allIn)}"><span>${escapeHtml(anchorName)}全成本结果</span><strong id="liveAllInProfit">${allIn===null?"输入当前价":formatSignedWan(allIn)}</strong><small>再扣本局已记录成本</small></div><div class="v04-outcome caution"><span>${escapeHtml(roughRiskName)}</span><strong id="liveLossRisk">${risk===null?"样本不足":`约 ${Math.round(risk)}%`}</strong><small>${risk===null?"没有完整 Shadow 分布，拒绝伪造比例":"仅分位插值 · 未校准亏损概率"}</small></div></div></div><div id="liveBidWarning" class="v04-warning ${liveBid!==null&&liveBid>legacy?"visible":""}">${liveBid!==null&&liveBid>legacy?`当前价比 v0.3 平衡参考线高 ${fmtWan(liveBid-legacy)}。这不是强制拦截，但请明确记录你为何继续跟价。`:""}</div></div><div class="decision-tags"><span class="decision-tag ${uncertainty==="高"?"high":uncertainty==="低"?"low":"medium"}">结构不确定性：${escapeHtml(uncertainty)}</span><span class="decision-tag">置信度：${escapeHtml(d.confidence)}</span><span class="decision-tag">当前情报档：${escapeHtml(modeTitle)}</span></div>${tailGuardHtml}${solverNote}${wholeValueAxisHtml(d)}${splitNote}</section>${probabilityProfileHtml(d)}${componentBreakdownHtml(d)}`;
    }
    const decisionMetricsV04Baseline=decisionMetrics;
    function v06DecisionHtml(d){
      if(d?.fieldConditionAnalysis?.sparkleEvidence)return "";
      const live = currentLiveBid();
      const lines = calculateV06DecisionLines(currentAnalysis, d, live);
      const status = d?.solverStatus || "valid";

      // Level 3: Insufficient (信息不足，不报价)
      if(lines.degradationLevel === "insufficient"){
        const clues = lines.missingClues || [];
        const cluesHtml = clues.length > 0 ? `
          <div style="margin-top:6px;padding-top:6px;border-top:1px dashed #fcd34d">
            <b style="color:#92400e">下一步最有效的情报补充建议：</b>
            <ul style="margin:4px 0 0 16px;padding:0;color:#78350f;font-size:9px;line-height:1.45">
              ${clues.map(c => `<li><b>[${escapeHtml(c.label)}]</b> ${escapeHtml(c.text)}</li>`).join("")}
            </ul>
          </div>` : "";

        return `<section class="v06-decision-panel low-info" data-solver-status="${escapeHtml(status)}">
          <div class="v06-decision-head">
            <div>
              <strong>实战决策台 · 信息不足 (Level 3)</strong>
              <small>未形成有效结构或分布 · 严禁在低信息状态下使用固定场地先验虚假报价</small>
            </div>
            <span class="v06-decision-status stop">当前信息不足 · 暂不报价</span>
          </div>
          <div class="callout" style="margin-top:8px;border-color:#fde68a;background:#fffbeb">
            <span class="dot" style="background:#d97706"></span>
            <div>
              <strong>当前信息不足，暂不报价：</strong>
              未形成有效候选结构或可信价值边界。系统已拒绝使用场地固定先验（如 20W/30W）假装精确估值。
              ${cluesHtml}
            </div>
          </div>
        </section>`;
      }

      // Level 2: Partial Shadow & Structural Only (Shadow 不可用或覆盖不足，但 Exact State / 结构约束有效)
      if(lines.degradationLevel === "partial_shadow" || lines.degradationLevel === "structural_only"){
        const isPartial = lines.degradationLevel === "partial_shadow";
        const hardFloorText = lines.hardFloor !== null ? `≥ ${fmtWan(lines.hardFloor)}` : "—";
        const candidateCount = lines.stateCount || 0;
        const costInfo = lines.costInfo;

        // 区分候选范围与理论极端范围
        const hasCandBounds = lines.candidateBoundsMin !== null && lines.candidateBoundsMax !== null;
        const hasTheoryBounds = lines.theoreticalMin !== null && lines.theoreticalMax !== null;
        let rangeMainText = "—";
        let rangeSubText = "结构约束推导";
        if (hasCandBounds) {
          rangeMainText = `${fmtWan(lines.candidateBoundsMin)} — ${fmtWan(lines.candidateBoundsMax)}`;
          if (hasTheoryBounds) {
            rangeSubText = `候选状态范围 · 理论极限 ${fmtWan(lines.theoreticalMin)}—${fmtWan(lines.theoreticalMax)}${lines.theoreticalMax > 1000000 ? " (含大奖)" : ""}`;
          } else {
            rangeSubText = `候选状态实际推导范围 · ${candidateCount} 个候选结构`;
          }
        } else if (hasTheoryBounds) {
          rangeMainText = `${fmtWan(lines.theoreticalMin)} — ${fmtWan(lines.theoreticalMax)}`;
          rangeSubText = `理论约束范围 · ${candidateCount} 个候选结构`;
        }

        const refBid = lines.structuralReferenceBid;
        const marginRemain = live === null ? null : (refBid !== null ? refBid - live : (lines.hardFloor !== null ? lines.hardFloor - live : null));

        const stale = document.getElementById("resultPanel")?.classList.contains("solver-stale");
        let action = stale ? "旧结果已过期 · 禁止依据追价" :
                     live === null ? "等待输入当前叫价" :
                     lines.hardFloor !== null && live <= lines.hardFloor ? "🟢 当前价低于已确认下限 · 确定盈利" :
                     refBid !== null && live <= refBid ? "🟡 在低置信参考出价内 · 请自行评估" :
                     lines.theoreticalMax !== null && live > lines.theoreticalMax ? "🔴 超过理论价值上限 · 确定亏损" :
                     "🟡 结构价值区间内 · 缺少完整概率分布";
        const stop = action.includes("停止") || action.includes("过期") || action.includes("亏损");

        const badgeHtml = isPartial ?
          `<span class="v06-data-badge partial">部分概率覆盖 · 非完整整仓分布 (${(lines.coverageRatio * 100).toFixed(0)}%)</span>` :
          `<span class="v06-data-badge structural">结构参考 · 非概率估值</span>`;

        const titleText = isPartial ? "实战决策台 · 结构估值与条件参考 (Partial Shadow)" : "实战决策台 · 结构估值模式";
        const subTitleText = isPartial ?
          `历史分布仅覆盖部分结构 · 严禁将条件 P50 (${fmtWan(lines.partialShadowP50)}) 包装成整仓 P50` :
          "历史概率分布不足 · 严禁伪造 P50 · 仅基于结构约束与真实证据推导";

        const partialEvidenceRow = isPartial && lines.partialShadowP50 !== null ? `
          <div class="v06-structural-evidence-item" style="color:#c2410c">
            <span>📊 已覆盖状态条件 P50：</span>
            <strong>${fmtWan(lines.partialShadowP50)}</strong>
            <small style="color:#9a3412">（覆盖率 ${(lines.coverageRatio * 100).toFixed(1)}% · 覆盖 ${lines.supportedStateCount}/${lines.totalStateCount} 候选结构 · 权重 ${lines.supportedWeight.toFixed(2)}/${lines.totalWeight.toFixed(2)}）</small>
          </div>` : "";

        const calloutHtml = isPartial ? `
          <div class="callout" style="margin-top:8px;border-color:#fed7aa;background:#fff7ed">
            <span class="dot" style="background:#ea580c"></span>
            <div>
              <strong>已覆盖状态条件 P50 为 ${fmtWan(lines.partialShadowP50)}（当前概率质量覆盖率：${(lines.coverageRatio * 100).toFixed(1)}%）：</strong>
              仅基于当前已覆盖的 ${lines.supportedStateCount}/${lines.totalStateCount} 个候选状态，未覆盖状态未进入概率聚合，因此不能代表完整整仓 P50。系统已拦截正式建议最高价，请依据已确认下限与结构范围审慎决策。
            </div>
          </div>` : `
          <div class="callout" style="margin-top:8px;border-color:#fde68a;background:#fffbeb">
            <span class="dot" style="background:#d97706"></span>
            <div>
              <strong>历史分布不足，当前无法生成整仓 P50：</strong>
              ${escapeHtml(lines.missingReason || "缺少同 R 真实历史对局分布")}。系统已拒绝使用场地固定 20W/30W 假先验补齐，亦不输出正式建议最高价；请依据已确认下限与理论范围审慎跟价。
            </div>
          </div>`;

        return `<section class="v06-decision-panel structural" data-degradation-level="${lines.degradationLevel}" data-target-line="${lines.hardFloor ?? ""}" data-global-line="${refBid ?? ""}" data-solver-status="${escapeHtml(status)}">
          <div class="v06-decision-head">
            <div>
              <strong>${escapeHtml(titleText)}</strong>
              <small>${escapeHtml(subTitleText)}</small>
            </div>
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;justify-content:flex-end;">
              ${badgeHtml}
              <span id="v06DecisionStatus" class="v06-decision-status ${stop ? "stop" : ""}">${escapeHtml(action)}</span>
            </div>
          </div>

          <div class="v06-decision-grid four-col">
            <div class="v06-decision-kpi value">
              <span>① 已确认价值下限 (Hard Floor)</span>
              <strong>${hardFloorText}</strong>
              <small>已确认藏品/保底约束</small>
            </div>
            <div class="v06-decision-kpi">
              <span>② 可行结构价值范围</span>
              <strong>${escapeHtml(rangeMainText)}</strong>
              <small>${escapeHtml(rangeSubText)}</small>
            </div>
            <div class="v06-decision-kpi current">
              <span>③ 游戏当前叫价</span>
              <input id="v06LiveBidInput" class="v06-live-bid-input" type="number" min="0" step="1000" value="${live ?? ""}" placeholder="输入当前价" oninput="updateLiveBid(this.value)">
              <div class="v06-quick-btns">
                <button type="button" onclick="bumpLiveBid(10000)">+1W</button>
                <button type="button" onclick="bumpLiveBid(50000)">+5W</button>
                <button type="button" onclick="bumpLiveBid(100000)">+10W</button>
              </div>
            </div>
            <div class="v06-decision-kpi structural-ref margin-kpi ${marginRemain === null ? "caution" : marginRemain >= 0 ? "positive" : "negative"}">
              <span>④ 低置信参考出价 (非正式)</span>
              <strong id="v06MarginRemain">${refBid !== null ? fmtWan(refBid) : (lines.hardFloor !== null ? fmtWan(lines.hardFloor) : "—")}</strong>
              <small id="v06ProfitSummary">${marginRemain === null ? `扣总成本 ${fmtWan(costInfo.allCosts)} · 仅供参考` : `距结构参考 ${formatSignedWan(marginRemain)}`}</small>
            </div>
          </div>

          <div class="v06-structural-evidence-bar">
            <div class="v06-structural-evidence-item">
              <span>🧩 当前结构候选：</span>
              <strong>${escapeHtml(lines.structureCandidateSummary || "分析中")}</strong>
            </div>
            <div class="v06-structural-evidence-item">
              <span>💎 已确认价值组成：</span>
              <strong>${escapeHtml(lines.confirmedValuesSummary || "图鉴保底")}</strong>
            </div>
            ${partialEvidenceRow}
          </div>

          ${calloutHtml}

          <div class="v06-decision-foot">
            <span><b>决策提示：</b><span id="v06DecisionActionText">${escapeHtml(action)}</span></span>
            <span class="v06-decision-uncertainty">主要不确定来源：${isPartial ? "部分候选结构缺少历史分布" : "缺少同 R 真实历史对局分布"}</span>
          </div>
        </section>`;
      }

      // Level 1: Full Shadow (主价值层)
      const p = d?.probabilityProfile || {};
      const cd = p.currentDistribution || {};
      const directGames = Number(cd.directGames || cd.directN || 0);
      const probMode = String(cd.mode || (directGames > 0 && Number(cd.bootstrapN || 0) > 0 ? "mixed" : directGames > 0 ? "direct" : "bootstrap"));

      const modeBadgeText = probMode === "direct" && directGames >= 3 ? `同 R 直接经验 · 高置信 (${directGames}局)` :
                            probMode === "mixed" ? `混合经验分布 · 中置信 (${directGames}局直接+模拟)` :
                            `Bootstrap 组合模拟 · 中低置信`;
      const modeBadgeClass = probMode === "direct" ? "direct" : probMode === "mixed" ? "mixed" : "bootstrap";

      const valueP50 = lines.valueP50;
      const recMax = lines.recommendedMax;
      const safeBuy = lines.safeBuy;
      const chaseLimit = lines.chaseLimit;
      const costInfo = lines.costInfo;

      const rangeText = (lines.valueP20 !== null && lines.valueP80 !== null) ? `${fmtWan(lines.valueP20)} — ${fmtWan(lines.valueP80)}` : "—";
      const marginRemain = live === null ? null : (recMax - live);
      const grossProfit = live === null ? null : (valueP50 - live);
      const allinCashflow = live === null ? null : (recMax - live);

      const stale = document.getElementById("resultPanel")?.classList.contains("solver-stale");
      const within = line => Number.isFinite(line) && live !== null && live <= line;
      let action = stale ? "旧结果已过期 · 禁止依据追价" :
                   live === null ? "等待输入当前叫价" :
                   within(safeBuy) ? "🟢 稳健买入区 · 空间充足" :
                   within(recMax) ? "🟢 建议出价内 · 仍有保本空间" :
                   within(chaseLimit) ? "🟡 已超建议最高价 · 仅剩边际追价空间" :
                   "🔴 超过极限追价线 · 建议停止";
      const stop = action.includes("停止") || action.includes("过期");

      const uncertainty = d?.blindSpots?.redCount ? "红货数量未锁定 (R=0~2) · 红色身份未知" :
                          d?.blindSpots?.goldCount ? "金件数尚未锁定 · G 候选仍有多个" :
                          probMode === "bootstrap" ? "单件重采样组合模拟 · 尾部可能低估" :
                          "State 内部离散价值区间";

      const coverageNote = lines.statesStructuralOnly > 0 ? 
        `<div class="field-help" style="margin-top:4px;font-size:8px;color:#64748b">${escapeHtml(`${lines.stateCount} 个候选结构中 ${lines.statesWithShadow} 个具备价值分布；${lines.statesStructuralOnly} 个仅保留结构约束。`)}</div>` : "";

      return `<section class="v06-decision-panel rc-panel" data-target-line="${safeBuy ?? ""}" data-global-line="${recMax ?? ""}" data-marginal-line="${chaseLimit ?? ""}" data-solver-status="${escapeHtml(status)}">
        <div class="v06-decision-head">
          <div>
            <strong>实战决策台 · HTML v0.6 Release Candidate</strong>
            <small>以 Shadow P50 为主价值锚点 · 建议最高价扣除全成本 · 三价独立分层</small>
          </div>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;justify-content:flex-end;">
            <span class="v06-data-badge ${modeBadgeClass}">${escapeHtml(modeBadgeText)}</span>
            <span id="v06DecisionStatus" class="v06-decision-status ${stop ? "stop" : ""}">${escapeHtml(action)}</span>
          </div>
        </div>

        <div class="v06-decision-grid four-col">
          <div class="v06-decision-kpi value">
            <span>① 预计整仓价值 (P50)</span>
            <strong>${fmtWan(valueP50)}</strong>
            <small>合理区间 ${escapeHtml(rangeText)} (P20–P80)</small>
          </div>
          <div class="v06-decision-kpi recommended-max">
            <span>② 🎯 建议最高价 (正式建议)</span>
            <strong>${fmtWan(recMax)}</strong>
            <small>全成本保本线 · 扣总成本 ${fmtWan(costInfo.allCosts)}</small>
          </div>
          <div class="v06-decision-kpi current">
            <span>③ 游戏当前叫价</span>
            <input id="v06LiveBidInput" class="v06-live-bid-input" type="number" min="0" step="1000" value="${live ?? ""}" placeholder="输入当前价" oninput="updateLiveBid(this.value)">
            <div class="v06-quick-btns">
              <button type="button" onclick="bumpLiveBid(10000)">+1W</button>
              <button type="button" onclick="bumpLiveBid(50000)">+5W</button>
              <button type="button" onclick="bumpLiveBid(100000)">+10W</button>
            </div>
          </div>
          <div class="v06-decision-kpi margin-kpi ${marginRemain === null ? "caution" : marginRemain >= 0 ? "positive" : "negative"}">
            <span>④ 剩余出价空间</span>
            <strong id="v06MarginRemain">${marginRemain === null ? "输入当前价" : formatSignedWan(marginRemain)}</strong>
            <small id="v06ProfitSummary">预计竞得价差 ${grossProfit === null ? "—" : formatSignedWan(grossProfit)} · 距建议最高价 ${allinCashflow === null ? "—" : formatSignedWan(allinCashflow)}</small>
          </div>
        </div>

        <div class="v06-decision-secondary-row">
          <div class="v06-secondary-price safe">
            <span>🛡️ 稳健买入价</span>
            <strong>${fmtWan(safeBuy)}</strong>
            <small>留足约 20% 目标回报空间</small>
          </div>
          <div class="v06-secondary-price chase">
            <span>🛑 极限追价线 <i class="badge-tag">薄利/高风险·非日常建议</i></span>
            <strong>${fmtWan(chaseLimit)}</strong>
            <small>仅扣未来新增成本 ${fmtWan(costInfo.futureIncrementalCost)}</small>
          </div>
        </div>

        ${coverageNote}

        <div class="v06-decision-foot">
          <span><b>决策提示：</b><span id="v06DecisionActionText">${escapeHtml(action)}</span></span>
          <span class="v06-decision-uncertainty">主要不确定来源：${escapeHtml(uncertainty)}</span>
        </div>
        ${probMode === "bootstrap" ? `<div class="callout" style="margin-top:6px;padding:5px 8px;font-size:8px;border-color:#fde68a;background:#fffbeb"><span class="dot" style="background:#d97706"></span><div><strong>组合模拟提示：</strong>当前缺少同 R 直接样本，分布基于单件重采样组合；区间可能低估极端尾部风险。</div></div>` : ""}
      </section>`;
    }
    window.v06DecisionHtml = v06DecisionHtml;
    decisionMetrics=function(d){
      const legacy=decisionMetricsV04Baseline(d)
        .replace("实战决策台 · v0.4","旧版基准对照 · v0.5 / Legacy Heuristic")
        .replace("v0.4 工作估值","v0.5 工作估值 (Legacy Heuristic)");
      return `${v06DecisionHtml(d)}
      <details class="v06-legacy-details">
        <summary>展开推演依据与算法详情（State Inference / 离散状态 / 概率证据 / 旧版对照）</summary>
        ${legacy}
      </details>`;
    };
    function roundingAuditHtml(audit){
      if(!audit?.hasAverage)return "";
      const labels={floor:"向下取整",nearest:"四舍五入",either:"兼容区间"},mode=labels[audit.chosenRoundingMode]||audit.chosenRoundingMode||"—",requested=labels[audit.requestedRoundingMode]||audit.requestedRoundingMode||"—";
      const showState=s=>s&&s.length?s.slice(0,8).map(x=>`G=${x.G??"—"}/P=${x.P??"—"}/R=${x.R??(x.Rmin!=null?`${x.Rmin}–${x.Rmax}`:"—")}`).join(" · ")+(s.length>8?` · …（共 ${s.length}）`:""):"无";
      const poolText=p=>p&&((p.gold?.length||p.purple?.length)?`G=${p.gold?.map(x=>x.G).join("/")||"—"} · P=${p.purple?.map(x=>x.P).join("/")||"—"}`:"无");
      const f=audit.floorStates||[],n=audit.nearestStates||[],c=audit.compatibleStates||[],same=(audit.floorMatchCount>0&&audit.floorMatchCount===audit.nearestMatchCount&&(audit.floorOnlyStates||[]).length===0&&(audit.nearestOnlyStates||[]).length===0);
      let note=audit.fallbackReason==="floor-no-match-nearest-match"?"严格向下取整无解，已临时降级到四舍五入；这只影响本局，不会改变全局默认规则。":audit.fallbackReason==="floor-and-nearest-no-match-compatible-match"?"向下取整与四舍五入都无解，兼容区间找到候选；请把它视为取整不确定，而不是自动认定抄录正确。":same?"向下取整与四舍五入得到相同结构，本局取整规则对 G/P/R 没有影响。":"两种规则都已并行计算；当前仍按所选规则出值，差异只作为审计信息保存。";
      return `<details class="rounding-audit"><summary><strong>取整审计 · 当前采用${escapeHtml(mode)}</strong><span>展开查看规则差异</span></summary><div class="rounding-audit-body"><p>${escapeHtml(note)}</p><div class="rounding-counts"><span>向下取整 <b>${audit.floorMatchCount??0}</b></span><span>四舍五入 <b>${audit.nearestMatchCount??0}</b></span><span>兼容区间 <b>${audit.compatibleMatchCount??0}</b></span><span>请求规则 <b>${escapeHtml(requested)}</b></span></div>${audit.stateType==="independent-pools"?`<div class="field-help">无 Q 时为独立价格池：向下取整 ${escapeHtml(poolText(audit.floorPools))}；四舍五入 ${escapeHtml(poolText(audit.nearestPools))}；兼容 ${escapeHtml(poolText(audit.compatiblePools))}。</div>`:`<div class="rounding-states"><div><strong>向下取整</strong><small>${escapeHtml(showState(f))}</small></div><div><strong>四舍五入</strong><small>${escapeHtml(showState(n))}</small></div><div><strong>兼容区间</strong><small>${escapeHtml(showState(c))}</small></div>${(audit.floorOnlyStates||[]).length||(audit.nearestOnlyStates||[]).length?`<div class="field-help">仅向下：${escapeHtml(showState(audit.floorOnlyStates))}；仅四舍五入：${escapeHtml(showState(audit.nearestOnlyStates))}</div>`:""}</div>`}</div></details>`;
    }
    function componentBreakdownHtml(d){
      const finite=value=>Number.isFinite(Number(value)),p=d?.probabilityProfile||{},redDist=p.currentTotal||null;
      const gold=d.breakdown?.gold||{},purple=d.breakdown?.purple||{},red=d.breakdown?.red||{},low=d.breakdown?.lowTier||{};
      const stateGs=[...new Set((d.componentRows||[]).map(row=>Number(row?.state?.g)).filter(Number.isInteger))],statePs=[...new Set((d.componentRows||[]).map(row=>Number(row?.state?.p)).filter(Number.isInteger))];
      const gLocked=(Array.isArray(d.candidateGs)&&d.candidateGs.length===1)||stateGs.length===1,pLocked=(Array.isArray(d.candidatePs)&&d.candidatePs.length===1)||statePs.length===1||["goldAvgPurple","dualAvg"].includes(d.infoMode?.id)||String(purple.source||"").includes("已知紫色");
      const directGames=Number(p.currentDistribution?.directGames)||0,bootstrapN=Number(p.currentDistribution?.bootstrapN)||0,probMode=String(p.currentDistribution?.mode||"none");
      const redEvidence=probMode==="direct"&&directGames?`Probability · ${directGames} 独立历史局`:probMode==="mixed"?`Probability 探索性 · ${directGames} 独立历史局 + bootstrap`:probMode==="bootstrap"?`Probability 探索性 · bootstrap 组合`:"Probability · 当前样本不足";
      const sourceFor=(key,x)=>{
        if(key==="gold")return `${(d.infoMode?.id==="goldAvgPurple"||d.infoMode?.id==="goldAvgOnly")?"金均+离散组合":(x.source||"金色图鉴")} · ${gLocked?"G已锁":"G未锁"}`;
        if(key==="purple")return `${x.source||"紫色价格范围"} · ${pLocked?"P已锁":"P未锁"}`;
        if(key==="red")return redEvidence;
        return `${x.source||"场地低品质先验"}${x.residualN?` · ${x.residualN}局残值样本`:""}`;
      };
      const rows=[
        {key:"gold",label:"金",cls:"gold",x:gold,lo:gold.lower,mid:gold.mid,hi:gold.upper},
        {key:"purple",label:"紫",cls:"purple",x:purple,lo:purple.lower,mid:purple.mid,hi:purple.upper},
        {key:"red",label:"红",cls:"red",x:red,lo:redDist?.p20??red.typicalLow,mid:redDist?.p50??red.mid,hi:redDist?.p80??red.typicalHigh},
        {key:"lowTier",label:"蓝绿白残值",cls:"low",x:low,lo:low.lower,mid:low.mid,hi:low.upper}
      ].map(row=>{const lo=finite(row.lo)?Math.max(0,Number(row.lo)):0,mid=finite(row.mid)?Math.max(lo,Number(row.mid)):lo,hi=finite(row.hi)?Math.max(mid,Number(row.hi)):mid;return {...row,lo,mid,hi,source:sourceFor(row.key,row.x)};});
      const marker=(row)=>{const span=row.hi-row.lo,pos=span>0?Math.max(0,Math.min(100,(row.mid-row.lo)/span*100)):0;return `<div class="component-range-track" aria-label="${escapeHtml(row.label)}价值范围"><i class="component-range-fill" style="width:${Math.max(0,pos).toFixed(1)}%"></i><b class="component-range-marker" style="left:${pos.toFixed(1)}%"></b></div>`;};
      const track=(row)=>`<div class="component-range-row"><div class="component-range-label"><strong>${row.label}</strong><span>${escapeHtml(row.source)}</span></div><div class="component-range-values"><span>下限 <b>${fmtWan(row.lo)}</b></span><span>中值 <b>${fmtWan(row.mid)}</b></span><span>上限 <b>${fmtWan(row.hi)}</b></span></div>${marker(row)}</div>`;
      const widest=rows.slice().sort((a,b)=>(b.hi-b.lo)-(a.hi-a.lo))[0];
      return `<section class="whole-value-map"><div class="whole-value-map-head"><div><div class="whole-value-map-kicker">VALUE SOURCES</div><h3>价值来源</h3><p>四条分项轨道解释价值来自哪里；整仓 Shadow 仍按联合 State 分布计算，四个中值不能直接相加。</p></div><span class="decision-tag medium">最大不确定来源：${escapeHtml(widest?.label||"—")}</span></div><div class="whole-value-tracks">${rows.map(track).join("")}</div><div class="whole-value-map-note"><b>Probability Shadow 当前不参与推荐出价。</b> 证据标签只表示来源类型与样本量，不代表伪造的可靠率。</div></section>`;
    }
    let currentSimilarRows=[];
    function similarPriority(x){const rs=x.reasons||[],box=rs.includes("同箱型"),venue=rs.includes("同场地"),q=rs.includes("Q"),near=rs.includes("Q近");if(box&&venue&&q)return 60;if(box&&q)return 50;if(box&&near)return 40;if(venue&&q)return 30;if(venue&&near)return 20;return 10;}
    function similarReason(x){return (x.reasons||[]).filter(y=>y!=="同月份").slice(0,3).map(y=>y==="Q"?"Q同":y).join(" · ")||"低信息近邻";}
    function similarHistoryCard(x){const r=x.record,estimate=r.prediction?.estimate??(Array.isArray(r.rounds)&&r.rounds.length?r.rounds.slice().sort((a,b)=>a.round-b.round).at(-1)?.prediction?.estimate:null),box=String(r.box||"未知箱型").replace(/宝箱|概率提升/g,"").replace(/\s*·\s*/g," · ");return `<article class="similar-card"><div class="similar-compact-top"><strong>${escapeHtml(box)} · Q${r.q??"—"}</strong><b>${fmtWan(r.actualTotal)}</b></div><span class="similar-compact-line">${hasNumber(estimate)?`估 ${fmtWan(estimate)} → 实际 ${fmtWan(r.actualTotal)}`:"当时未保存估值"}</span><span class="similar-compact-reason">${escapeHtml(similarReason(x))}</span></article>`;}
    function similarHistoryHtml(d){
      if(!d.similar?.length){currentSimilarRows=[];return `<div class="similar-history"><div class="similar-head"><div><h3>相似历史</h3><p>还没有能比较的已结算样本</p></div></div></div>`;}
      const rows=d.similar.slice().sort((a,b)=>similarPriority(b)-similarPriority(a)||b.similarity-a.similarity||String(b.record.playedAt||"").localeCompare(String(a.record.playedAt||"")));
      currentSimilarRows=rows;
      const best=rows[0],bestActual=best?.record?.actualTotal;
      return `<details class="similar-history similar-history-compact"><summary><span>参考历史 ${rows.length} 局 · 最相似实际 ${hasNumber(bestActual)?fmtWan(bestActual):"—"}</span><b>展开相关历史</b></summary><div class="similar-history-body"><div class="similar-head"><div><h3>最接近的已结算对局</h3><p>结构优先：同箱型 / 同场地 / 同 Q 高于月份</p></div><span class="badge mint">Top ${Math.min(4,rows.length)}</span></div><div class="similar-grid compact">${rows.slice(0,4).map(similarHistoryCard).join("")}</div><button type="button" class="similar-browse-btn" onclick="openSimilarHistoryDialog()">浏览全部相似历史 ${rows.length}</button></div></details>`;
    }
    function renderSimilarHistoryDialog(){const list=document.getElementById("similarDialogList"),count=document.getElementById("similarDialogCount");if(!list)return;const sort=val("similarSort"),q=num("similarQFilter"),box=val("similarBoxFilter"),currentBox=val("calcBox"),currentVenue=val("calcVenue");let rows=currentSimilarRows.filter(x=>(q==null||Number(x.record.q)===q)&&(box==="all"||x.record.box===box));if(sort==="box")rows.sort((a,b)=>Number(b.record.box===currentBox)-Number(a.record.box===currentBox)||similarPriority(b)-similarPriority(a)||b.similarity-a.similarity);else if(sort==="venue")rows.sort((a,b)=>Number(b.record.venue===currentVenue)-Number(a.record.venue===currentVenue)||similarPriority(b)-similarPriority(a)||b.similarity-a.similarity);else if(sort==="recent")rows.sort((a,b)=>(historyTimestamp(b.record.playedAt)||0)-(historyTimestamp(a.record.playedAt)||0));else rows.sort((a,b)=>similarPriority(b)-similarPriority(a)||b.similarity-a.similarity);count.textContent=`${rows.length} / ${currentSimilarRows.length} 局`;list.innerHTML=rows.length?rows.map(similarHistoryCard).join(""):'<div class="empty-list">当前筛选下没有相似历史</div>';}
    window.openSimilarHistoryDialog=function(){const dialog=document.getElementById("similarHistoryDialog"),select=document.getElementById("similarBoxFilter"),current=select.value;select.innerHTML='<option value="all">全部箱型</option>'+[...new Set(currentSimilarRows.map(x=>x.record.box).filter(Boolean))].sort().map(x=>`<option value="${escapeHtml(x)}">${escapeHtml(x)}</option>`).join("");if([...select.options].some(x=>x.value===current))select.value=current;renderSimilarHistoryDialog();dialog.showModal();};
    ["similarSort","similarQFilter","similarBoxFilter"].forEach(id=>document.getElementById(id)?.addEventListener(id==="similarQFilter"?"input":"change",renderSimilarHistoryDialog));
    document.getElementById("closeSimilarDialog")?.addEventListener("click",()=>document.getElementById("similarHistoryDialog")?.close());
    document.getElementById("similarHistoryDialog")?.addEventListener("click",e=>{if(e.target===e.currentTarget)e.currentTarget.close();});
    function renderEmpiricalHint(ctx){
      const targetEl=document.getElementById("empiricalHint");if(!targetEl)return;const d=ctx.workingDecision||workingDecision(ctx,ctx.candidates||[]);
      targetEl.innerHTML=`<div class="callout"><span class="dot"></span><div><strong>完整历史：</strong>金/紫/常见红/蓝绿白分项相加；高红状态降权；工作估值强制 ≥ ${fmtWan(d.hardFloor)}（含三色已知与分组约束的安全下限）。相似历史只取本局之前的记录并轻量校准残值，不把单局极端总价硬灌进中心。硬下限、保守防亏参考、v0.3 平衡参考线和高风险尝试线分开显示；蓝绿白有件数/格数/均价就使用，没有则用场地先验。</div></div>`;
    }

    function buildPredictionSnapshot(analysis,d,status=null){
      if(!d||analysis?.diagnosticOnly===true||["no-match","timeout","stale"].includes(status||analysis?.solverStatus))return null;
      const solverStatus=status||analysis?.solverStatus||"valid",inputHash=analysis.inputHash||solverInputHash(analysis);
      const condition={fieldCondition:canonicalFieldConditionId(analysis.fieldCondition||"unknown"),avgValueBasis:analysis.avgValueBasis||"unknown",privateBidCap:analysis.privateBidCap??null,bidActionCount:analysis.bidActionCount??null,sparkle:analysis.sparkle||null,intelEvents:normalizeIntelEvents(analysis.intelEvents)};
      const provisional=solverStatus==="incomplete";
      return {modelVersion:d.modelVersion,solverVersion:SOLVER_VERSION,solverStatus,inputHash:analysis.inputHash||solverInputHash(analysis),catalogVersion:catalogVersionFor(analysis),solvedAt:analysis.solvedAt||new Date().toISOString(),round:Number(analysis.round)||1,...condition,theoreticalMin:analysis.theoreticalMin??null,theoreticalMax:analysis.theoreticalMax??null,highTierMin:analysis.theoreticalMin??analysis.predictedMin,highTierMax:analysis.theoreticalMax??analysis.predictedMax,redMin:analysis.redMin,redMax:analysis.redMax,candidateGs:analysis.candidateGs,candidatePs:analysis.candidatePs,goldInference:analysis.goldInference||null,estimate:d.center,recommendedCap:provisional?null:d.cap,balancedCap:provisional?null:d.balancedCap,conservativeLossLine:provisional?null:(d.conservativeLossLine??d.cap),recommendedMaxBid:provisional?null:(d.recommendedMaxBid??d.balancedCap),highRiskTrialLine:provisional?null:(d.highRiskTrialLine??d.high),hardFloor:d.hardFloor,riskAnchor:d.riskAnchor,componentBreakdown:d.breakdown,probabilityProfile:d.probabilityProfile||null,empiricalStatePrior:d.empiricalStatePrior||null,shadowCalibrated:d.shadowCalibrated||null,structuralCenter:d.structuralCenter,historyRecordIds:d.similar?.map(x=>x.record.id)||[],historySimilarities:d.similar?.map(x=>x.similarity)||[],workingLow:d.low,workingHigh:d.high,estimateSource:d.source,estimateSampleSize:d.history?.n||0,estimateConfidence:provisional?"候选未完整":d.confidence,estimateFallbackLevel:d.cohort?.level??4,recommendationSuppressed:provisional||d.recommendationSuppressed===true,recommendationSuppressedReason:provisional?"候选搜索未完成：不生成正式推荐价":d.recommendationSuppressedReason||null,roundingAudit:analysis.roundingAudit||null,requestedRoundingMode:analysis.requestedRoundingMode||analysis.roundingMode||null,chosenRoundingMode:analysis.roundingMode||null};
    }
    const buildPredictionSnapshotV06Base=buildPredictionSnapshot;
    buildPredictionSnapshot=function(analysis,d,status=null){const out=buildPredictionSnapshotV06Base(analysis,d,status);if(out){out.empiricalStatePrior=d?.empiricalStatePrior||analysis?.empiricalStatePrior||null;out.shadowCalibrated=d?.shadowCalibrated||analysis?.shadowCalibrated||null;out.marketPrediction=d?.marketPrediction||analysis?.marketPrediction||null;out.entryDecision=d?.entryDecision||analysis?.entryDecision||null;}return out;};
    function predictionSnapshot(analysis){
      if(!analysis)return null;
      if(analysis.frozenPrediction!==undefined)return analysis.frozenPrediction;
      if(analysis.diagnosticOnly===true||["no-match","timeout","stale"].includes(analysis.solverStatus))return null;
      return buildPredictionSnapshot(analysis,analysis.workingDecision,analysis.solverStatus||"valid");
    }
    function analysisFields(a){const p=a.publicInfo||{};return {goldAvg:a.avg,goldCount:a.goldCount,purpleCount:a.purple,purpleAvg:a.purpleAvg,goldTotal:a.goldTotal,cost:a.cost??0,targetProfit:a.targetProfit??30000,minPurple:a.minPurple??0,minGold:a.minGold??0,minRed:a.minRed??0,knownPurple:a.knownPurpleRaw||"",knownGold:a.knownGoldRaw||"",knownRed:a.knownRedRaw||"",totalItems:p.totalItems,totalGrid:p.totalGrid,goldGrid:p.goldGrid,purpleGrid:p.purpleGrid,blueGrid:p.blueGrid,blueCount:p.blueCount,blueAvg:p.blueAvg,greenGrid:p.greenGrid,greenCount:p.greenCount,greenAvg:p.greenAvg,whiteGrid:p.whiteGrid,whiteCount:p.whiteCount,whiteAvg:p.whiteAvg,systemEstimate:p.systemEstimate,singleAvg:p.singleAvg,nineAvg:p.nineAvg,publicNote:p.note||""};}
    function roundEvidenceForSnapshot(analysis){return currentRoundEvidence.map((x,i)=>{const {dataUrl,...rest}=x;return {...rest,round:Number(analysis.round)||1,segmentIndex:i+1,kind:"round-evidence",coverageMode:"round-viewport"};});}
    function makeRoundSnapshot(analysis){const condition={fieldCondition:canonicalFieldConditionId(analysis.fieldCondition||"unknown"),avgValueBasis:analysis.avgValueBasis||"unknown",privateBidCap:analysis.privateBidCap??null,bidActionCount:analysis.bidActionCount??null,sparkle:analysis.sparkle||null,intelEvents:normalizeIntelEvents(analysis.intelEvents)};return {round:Number(analysis.round)||1,capturedAt:new Date().toISOString(),q:analysis.q,character:analysis.character,venue:analysis.venue,box:analysis.box,...condition,toolGroup:analysis.toolGroup||"group1",strategy:analysis.strategy,roundingMode:analysis.roundingMode,requestedRoundingMode:analysis.requestedRoundingMode||analysis.roundingMode,roundingAudit:analysis.roundingAudit||null,diagnosticOnly:analysis.diagnosticOnly===true,diagnosticReport:analysis.diagnosticReport||null,solverVersion:SOLVER_VERSION,solverStatus:analysis.solverStatus||"unknown",inputHash:analysis.inputHash||null,solverElapsedMs:analysis.solverElapsedMs??null,solverSearchCompleted:analysis.solverSearchCompleted!==false,solverTruncated:analysis.solverTruncated===true,conflictSnapshot:analysis.conflictSnapshot||null,...analysisFields(analysis),redCount:analysis.redCount,roundEvidence:roundEvidenceForSnapshot(analysis),prediction:predictionSnapshot(analysis)};}
    const ROUND_DIFF_FIELDS=[["q","Q"],["purpleCount","紫色数量"],["goldCount","金色数量"],["redCount","红色数量"],["goldAvg","金色均价"],["purpleAvg","紫色均价"],["goldTotal","金色总价"],["fieldCondition","场地条件"],["avgValueBasis","均价口径"],["privateBidCap","私人上限"],["bidActionCount","出价次数"],["cost","本局分摊成本"],["targetProfit","目标利润"],["minPurple","紫色至少"],["minGold","金色至少"],["minRed","红色至少"],["knownPurple","已知紫色价格约束"],["knownGold","已知金色价格约束"],["knownRed","已知红色价格约束"],["totalItems","总件数"],["totalGrid","总格数"],["goldGrid","金色格数"],["purpleGrid","紫色占格数"],["blueCount","蓝色数量"],["blueGrid","蓝色占格数"],["blueAvg","蓝色均价"],["greenCount","绿色数量"],["greenGrid","绿色占格数"],["greenAvg","绿色均价"],["whiteCount","白色数量"],["whiteGrid","白色占格数"],["whiteAvg","白色均价"],["systemEstimate","公开估价"],["singleAvg","单格均价"],["nineAvg","九格均价"],["publicNote","公开时间线"],["character","竞拍助手"],["venue","场地"],["box","箱型"],["toolGroup","道具组"],["roundingMode","取整规则"]];
    function emptyRoundField(key,value){return value==null||value===""||(["minPurple","minGold","minRed"].includes(key)&&Number(value)===0);}
    function roundChanges(current,previous=null){return ROUND_DIFF_FIELDS.flatMap(([key,label])=>{const before=previous?.[key]??null,after=current?.[key]??null,beforeEmpty=emptyRoundField(key,before),afterEmpty=emptyRoundField(key,after);if(beforeEmpty&&afterEmpty)return [];if(String(before)===String(after))return [];return [{key,label,before:beforeEmpty?null:before,after:afterEmpty?null:after,type:beforeEmpty?"added":afterEmpty?"removed":"changed"}];});}
    function roundChangeText(change){if(change.type==="added")return `${change.label} ${change.after}`;if(change.type==="removed")return `${change.label} 已移除`;return `${change.label} ${change.before} → ${change.after}`;}
    function roundTimelineHtml(){if(!currentRoundSnapshots.length)return '<span class="round-snapshot empty">首次推演将自动记录为 R1</span>';return currentRoundSnapshots.slice().sort((a,b)=>a.round-b.round).map(x=>{const shadow=shadowWholeFromPrediction(x.prediction);return `<span class="round-snapshot"><strong>R${x.round}</strong><span>${x.changes?.length??0} 项变化 · v0.3 ${fmtWan(x.prediction?.estimate)}${shadow?` · Shadow P50 ${fmtWan(shadow.p50)}`:""}</span></span>`;}).join("");}
    function renderRoundTimeline(){const el=document.getElementById("roundTimeline");if(el)el.innerHTML=roundTimelineHtml();}
    function upsertCurrentRoundSnapshot(announce=true){if(!currentAnalysis)return null;const snapshot=makeRoundSnapshot(currentAnalysis),index=currentRoundSnapshots.findIndex(x=>x.round===snapshot.round),previous=currentRoundSnapshots.filter(x=>x.round<snapshot.round).sort((a,b)=>b.round-a.round)[0]||null;snapshot.changes=roundChanges(snapshot,previous);if(index>=0)currentRoundSnapshots[index]=snapshot;else currentRoundSnapshots.push(snapshot);currentRoundSnapshots.sort((a,b)=>a.round-b.round);renderRoundTimeline();if(announce)toast(index>=0?`R${snapshot.round} 情报已更新`:`R${snapshot.round} 情报已记录`);return snapshot;}
    function completeSuccessfulRound(){
      const snapshot=upsertCurrentRoundSnapshot(false);if(!snapshot)return;
      const finished=snapshot.round,next=Math.min(5,finished+1),status=document.getElementById("autoRoundStatus");
      if(status)status.innerHTML=`<strong>R${finished}</strong><span>已记录 ${snapshot.changes.length} 项变化</span>`;
      currentRoundEvidence=[];renderRoundEvidence();
      setCalcRound(next);
      toast(finished<5?`R${finished} 已记录 ${snapshot.changes.length} 项变化；原有信息已保留，只需补充新情报后推演 R${next}`:`R5 已记录 ${snapshot.changes.length} 项变化；结算后可直接保存对局`);
    }
    window.redoCurrentRound=function(){
      if(!currentAnalysis)return;
      const round=Number(currentAnalysis.round)||1;
      setCalcRound(round,"retry");
      runCalculation();
    };
    let savingCurrentGame=false;
    window.saveCurrentGame=async function(){
      if(savingCurrentGame)return;
      savingCurrentGame=true;
      const saveButton=document.getElementById("saveCurrentGameBtn"),saveHint=document.getElementById("settlementSaveHint"),oldButtonText=saveButton?.textContent||"保存并下一局",oldHint=saveHint?.textContent||"";
      if(saveButton){saveButton.disabled=true;saveButton.classList.add("is-saving");saveButton.textContent="保存中…";}
      if(saveHint)saveHint.textContent="正在保存本局数据…";
      try{
      if(!currentAnalysis){toast("请先完成至少一次推演，再保存本局",true);return;}
      if(currentAnalysis.solverStatus==="stale"){toast("当前输入已变化，请先重新推演；旧结果不会冒充最新预测",true);return;}
      const frozenCurrentPrediction=predictionSnapshot(currentAnalysis);
      const clearingPrice=readResultFinalBid(),highestPersonalBid=readResultAmount("resultHighestPersonalBid"),purchaseSpend=readResultAmount("resultPurchaseSpend"),actualTotal=readResultActualTotal(),finalRed=readResultFinalRed(),redInventoryComplete=document.getElementById("resultRedInventoryComplete")?.checked===true,settlementGold=readResultAmount("resultGoldCount"),settlementPurple=readResultAmount("resultPurpleCount"),settlementRedCount=readResultAmount("resultRedCount"),truthSource=val("resultTruthSource")||"manual-settlement",truthConfidence=val("resultTruthConfidence")||"unknown",acquired=explicitBoolean(val("resultAcquired")),resultReason=val("resultReason"),condition=liveConditionPayload(Number(currentAnalysis.round)||1),fieldCondition=condition.fieldCondition,avgValueBasis=condition.avgValueBasis,welfare=welfareFromInputs("result",fieldCondition),resultGemCount=num("resultTransformedOneByOneCount"),sparkle={transformedOneByOneCount:integerOrNull(resultGemCount??condition.sparkle.transformedOneByOneCount),verifiedGemItems:val("resultVerifiedGemItems")||condition.sparkle.verifiedGemItems,complete:document.getElementById("resultGemInventoryComplete")?.checked===true||condition.sparkle.complete};
      if([clearingPrice,highestPersonalBid,purchaseSpend].some(x=>x===undefined)){toast("出价、成交价与本人支付都必须是非负数",true);return;}
      if(actualTotal===undefined){toast("最后实际总价不能为负数",true);return;}
      if(resultGemCount!==null&&(!Number.isInteger(resultGemCount)||resultGemCount<0)){toast("转换 1×1 数量必须是非负整数",true);return;}
      if(fieldCondition==="sparkle"){const audit=sparkleTruthAudit(sparkle,{playedAt:currentAnalysis.playedAt});if(!audit.ok){toast(audit.error,true);return;}}
      const countValues=[settlementGold,settlementPurple,settlementRedCount],hasSettlementCounts=countValues.some(x=>x!==null);
      if(countValues.some(x=>x===undefined)||(hasSettlementCounts&&!countValues.every(x=>Number.isInteger(x)&&x>=0))){toast("结算 G / P / R 要么全部留空，要么全部填写非负整数",true);return;}
      if(hasSettlementCounts&&(!Number.isInteger(Number(currentAnalysis.q))||settlementGold+settlementPurple+settlementRedCount!==Number(currentAnalysis.q))){toast(`结算数量必须满足 G + P + R = Q（当前 Q=${currentAnalysis.q??"未知"}）`,true);return;}
      const realizedState=hasSettlementCounts?{gold:settlementGold,purple:settlementPurple,red:settlementRedCount,complete:true,source:truthSource,confidence:truthConfidence}:null;
      if(redInventoryComplete&&!realizedState){toast("确认完整红货清单前，请先填写完整的结算 G / P / R",true);return;}
      if(redInventoryComplete&&/[\/／]/.test(finalRed)){toast("完整红货清单不能包含 / 歧义项；不确定时请取消“清单完整”",true);return;}
      const verifiedRedItems=redInventoryComplete?parseHistoricalRedItems(finalRed):[];
      if(redInventoryComplete&&((settlementRedCount===0&&finalRed)||(settlementRedCount>0&&verifiedRedItems.length!==settlementRedCount))){toast(`完整红货清单必须与 R=${settlementRedCount} 一致，并且每件都能在红色图鉴中识别`,true);return;}
      if(acquired===true&&purchaseSpend===null){toast("确认本人拍下时，请填写本人实际支付",true);return;}
      if(acquired===false&&purchaseSpend!==null&&purchaseSpend>0){toast("未拍下的对局不应填写本人实际支付",true);return;}
      // 只等待缩略图完成，不等待 OCR；这样快速保存不会丢掉刚粘贴的截图。
      for(let i=0;i<80&&currentGameEvidence.some(x=>x.status==="processing"&&!x.thumbnailDataUrl);i++)await new Promise(resolve=>setTimeout(resolve,25));
      const playedAt=currentAnalysis.playedAt||nowLocalInput(),periodKey=periodOf(playedAt)||"日期未知",calcContext={character:currentAnalysis.character,venue:currentAnalysis.venue,box:currentAnalysis.box,toolGroup:currentAnalysis.toolGroup},recordContext={role:"参与竞拍",character:currentAnalysis.character,venue:currentAnalysis.venue,box:currentAnalysis.box};
      const evidence=aggregateCurrentGameEvidence(),base=analysisFields(currentAnalysis),status=actualTotal!==null&&actualTotal>0?"verified":"pending",coverageGroup=currentGameEvidence[0]?.coverageGroup||uid(),settlementScreenshots=currentGameEvidence.map((x,i)=>{const {dataUrl,...rest}=x;return {...rest,thumbnailDataUrl:x.thumbnailDataUrl||dataUrl||null,kind:"settlement",segmentIndex:i+1,segmentRole:i===0?"main-settlement":"warehouse-supplement",coverageGroup,coverageMode:"viewport-segment",overlapExpected:i>0,overlapGuidance:"相邻截图建议保留约15%～30%重叠",dedupeStatus:"pending"};}),screenshots=settlementScreenshots.map(x=>({...x})),rounds=currentRoundSnapshots.map(x=>({...x,changes:(x.changes||[]).map(change=>({...change})),roundEvidence:(x.roundEvidence||[]).map(y=>({...y})),prediction:{...x.prediction}})),intelEvents=normalizeIntelEvents(rounds.flatMap(x=>x.intelEvents||[]));
      const ocrSuggestions=currentGameEvidence.map((x,i)=>({name:x.name,path:x.path||x.name,segmentIndex:i+1,segmentRole:i===0?"main-settlement":"warehouse-supplement",actual:x.actual??null,bid:x.bid??null,winner:Number(x.ocrNumbers?.winnerConfidence||0)>=52?winnerFromOcrText(x.ocrNumbers?.winnerText):null,confidence:x.confidence??null,scan:x.scan||null,source:x.source||"clipboard",importedAt:x.importedAt}));
      const winner=val("resultWinner")|| (ocrSuggestions.some(x=>x.winner==="本人拍下")?"本人拍下":ocrSuggestions.some(x=>x.winner==="其他人拍下")?"其他人拍下":""),note=val("resultNote");
      if((acquired===true&&winner==="其他人拍下")||(acquired===false&&winner==="本人拍下")){toast("“是否本人拍下”与“拍下方”互相冲突，请核对",true);return;}
      const costs=costBreakdownFromInputs("calc","live-session"),verifiedRedText=redInventoryComplete?finalRed:"",decisionKnownRed=String(currentAnalysis.knownRedRaw||val("calcKnownRed")||"").trim();
      const settlement={status,fieldCondition,avgValueBasis,privateBidCap:condition.privateBidCap,bidActionCount:condition.bidActionCount,welfare,sparkle,intelEvents,screenshots:settlementScreenshots,coverage:{mode:"viewport-segments",sameInventory:true,ordered:true,overlapExpected:true,overlapGuidance:"相邻截图建议保留约15%～30%重叠"},aggregationPolicy:{type:"inventory-union",deduplicateByOverlap:true,neverSumViewportCounts:true,uncertainDuplicateState:"possible-duplicate"},inventoryUnion:{status:"pending",items:[],uncertainDuplicates:[],counts:null,grids:null},actualTotal:actualTotal??null,bid:clearingPrice??null,highestPersonalBid:highestPersonalBid??null,clearingPrice:clearingPrice??null,purchaseSpend:purchaseSpend??null,acquired,resultReason:resultReason||null,costs,winner:winner||null,note:note||"",goldCount:realizedState?.gold??null,purpleCount:realizedState?.purple??null,redMin:Math.max(evidence.minRed||0,finalRed?1:0),redCount:realizedState?.red??null,realizedState,redInventoryComplete,verifiedRedItems:verifiedRedText,recognizedItems:"",redInventoryDraft:redInventoryComplete?"":finalRed,truthSource,truthConfidence,lowTier:{blueMin:evidence.minBlue||0,greenMin:evidence.minGreen||0,whiteMin:evidence.minWhite||0},source:"live-settlement",confidence:ocrSuggestions.length?Math.max(...ocrSuggestions.map(x=>Number(x.confidence)||0)):0,verified:status==="verified",ocrSuggestions};
      const outcome=acquired===true?"中标":status!=="verified"?"待识别":resultReason==="active-pass"?"放弃":resultReason==="early-close"?"被提前秒杀":resultReason==="observation-only"?"仅观察":"已结算";
      const r={id:uid(),productVersion:APP_VERSION,playedAt,periodKey,date:playedAt.slice(0,10),role:"参与竞拍",character:currentAnalysis.character,venue:currentAnalysis.venue,box:currentAnalysis.box,fieldCondition,avgValueBasis,privateBidCap:condition.privateBidCap,bidActionCount:condition.bidActionCount,welfare,sparkle,intelEvents,toolGroup:currentAnalysis.toolGroup||"group1",patch:periodKey,q:currentAnalysis.q,...base,decisionKnownRed,actualTotal:actualTotal??null,bid:highestPersonalBid??null,highestPersonalBid:highestPersonalBid??null,clearingPrice:clearingPrice??null,purchaseSpend:purchaseSpend??null,acquired,resultReason:resultReason||"",noBidReason:acquired===false?resultReason||"":"",costs,cost:costs.total,outcome,winner,notes:note,realizedState,redInventoryComplete,settlementVerifiedRedItems:verifiedRedText,redItems:verifiedRedText,rounds,screenshots,settlement,ocrEvidence:ocrSuggestions,source:"calculator",legacy:false,createdAt:Date.now(),solverVersion:SOLVER_VERSION,solverStatus:currentAnalysis.solverStatus||"unknown",inputHash:currentAnalysis.inputHash||null,diagnosticOnly:currentAnalysis.diagnosticOnly===true,diagnosticReport:currentAnalysis.diagnosticReport||null,conflictSnapshot:currentAnalysis.conflictSnapshot||null,prediction:frozenCurrentPrediction?{...frozenCurrentPrediction,fieldCondition,avgValueBasis,privateBidCap:condition.privateBidCap,bidActionCount:condition.bidActionCount,welfare,sparkle,intelEvents}:null};
      state.records.unshift(normalizeRecord(r));saveState({deferCache:true});const savedEvidenceKeys=new Set([...settlementScreenshots,...rounds.flatMap(x=>x.roundEvidence||[])].map(x=>x?.storageKey).filter(Boolean));resetCalculatorDraft(calcContext,{preserveKeys:savedEvidenceKeys});resetRecordForm(recordContext);resetOcrDraft();updateQuality();window.scrollTo({top:0,behavior:"smooth"});toast(status==="verified"?`对局已保存（${rounds.length} 个回合），实际总价 ${fmt(actualTotal)}；已准备下一局`:`对局已保存为待识别（${rounds.length} 个回合）；已准备下一局`);
      }catch(error){
        console.error("[saveCurrentGame] 保存失败",error);
        if(saveHint)saveHint.textContent=`保存失败：${error?.message||"未知错误"}；草稿仍保留`;
        toast(`保存失败：${error?.message||"未知错误"}；草稿仍保留`,true);
      }finally{
        savingCurrentGame=false;
        if(saveButton){saveButton.disabled=false;saveButton.classList.remove("is-saving");saveButton.textContent=oldButtonText;}
        if(saveHint&&saveHint.textContent==="正在保存本局数据…")saveHint.textContent=oldHint;
      }
    };

    // 保存按钮：直接绑定 + 事件委托双保险；并在展开结算时解除右侧 sticky 遮挡。
    function bindSaveCurrentGameButton(){
      const btn=document.getElementById("saveCurrentGameBtn");
      if(!btn || btn.dataset.boundSave==="1")return;
      btn.dataset.boundSave="1";
      btn.addEventListener("click",event=>{
        event.preventDefault();
        event.stopPropagation();
        void window.saveCurrentGame();
      });
    }
    bindSaveCurrentGameButton();
    const settlementPanel=document.getElementById("settlementCapture");
    if(settlementPanel){
      syncSettlementDockState(settlementPanel.open);
      settlementPanel.addEventListener("toggle",()=>syncSettlementDockState(settlementPanel.open));
    }

    

    let ocrWorker=null,ocrScriptPromise=null,ocrStatusOwner=null;
    function setOcrStatus(text,error=false){const el=document.getElementById("ocrStatus");el.textContent=text;el.style.color=error?"#b42318":"";}
    function resetOcrDraft(){
      document.getElementById("ocrPreview").classList.remove("show");const image=document.getElementById("ocrImage");image.removeAttribute("src");for(const key of ["rarityScan","fileName","filePath","fileSize","ocrConfidence","ocrNumbers"])delete image.dataset[key];currentOcrDataUrl="";document.getElementById("ocrFile").value="";["ocrActual","ocrBid","ocrTotalItems","ocrPurple","ocrGold","ocrRed","ocrBlue","ocrGreen","ocrWhite","ocrBlueGrid","ocrGreenGrid","ocrWhiteGrid"].forEach(id=>setVal(id,""));document.getElementById("ocrAllVisible").checked=false;setOcrStatus(currentGameEvidence.length?`本局已保留 ${currentGameEvidence.length} 张截图；可继续粘贴下一张`:"尚未粘贴截图");
    }
    function compactScreenshotData(img){const max=520,scale=Math.min(1,max/Math.max(img.naturalWidth,img.naturalHeight)),canvas=document.createElement("canvas");canvas.width=Math.max(1,Math.round(img.naturalWidth*scale));canvas.height=Math.max(1,Math.round(img.naturalHeight*scale));canvas.getContext("2d").drawImage(img,0,0,canvas.width,canvas.height);return canvas.toDataURL("image/jpeg",.52);}
    let evidenceDialogObjectUrl="";
    async function openEvidencePreview(shot){if(!shot)return;const dialog=document.getElementById("evidenceDialog"),img=document.getElementById("evidenceDialogImage"),title=document.getElementById("evidenceDialogTitle"),download=document.getElementById("evidenceDialogDownload");if(!dialog||!img)return;if(evidenceDialogObjectUrl){URL.revokeObjectURL(evidenceDialogObjectUrl);evidenceDialogObjectUrl="";}let src="",downloadName=shot.name||"异环拍卖截图.png",isOriginal=false;try{const stored=await readScreenshotBlob(shot.storageKey);if(stored?.blob){evidenceDialogObjectUrl=URL.createObjectURL(stored.blob);src=evidenceDialogObjectUrl;downloadName=stored.name||downloadName;isOriginal=true;}}catch(_){}if(!src)src=shot.thumbnailDataUrl||shot.dataUrl||safeScreenshotSrc(shot.path||shot.name);if(!src){toast("这张旧记录没有可读取的图片；请重新绑定原图",true);return;}img.src=src;title.textContent=`${shot.segmentIndex?`截图 ${shot.segmentIndex} · `:""}${downloadName}${isOriginal?" · 原图":" · 缩略图回退"}`;download.href=src;download.download=downloadName;download.textContent=isOriginal?"下载原图":"下载现有图片";if(!dialog.open)dialog.showModal();}
    function closeEvidenceDialog(){const dialog=document.getElementById("evidenceDialog"),img=document.getElementById("evidenceDialogImage");if(dialog?.open)dialog.close();if(img)img.removeAttribute("src");if(evidenceDialogObjectUrl){URL.revokeObjectURL(evidenceDialogObjectUrl);evidenceDialogObjectUrl="";}}
    document.getElementById("evidenceDialogClose")?.addEventListener("click",closeEvidenceDialog);document.getElementById("evidenceDialog")?.addEventListener("click",e=>{if(e.target===e.currentTarget)closeEvidenceDialog();});
    window.openCurrentEvidence=index=>openEvidencePreview(currentGameEvidence[index]);
    window.openRoundEvidence=index=>openEvidencePreview(currentRoundEvidence[index]);
    window.openHistoryEvidence=(recordId,index)=>{const record=state.records.find(x=>x.id===recordId);return openEvidencePreview(record?.screenshots?.[index]||record?.settlement?.screenshots?.[index]);};
    function renderCurrentGameEvidence(){const list=document.getElementById("currentGameEvidenceList"),count=document.getElementById("currentEvidenceCount");if(count)count.textContent=currentGameEvidence.length+" 张";if(!list)return;list.innerHTML=currentGameEvidence.length?currentGameEvidence.map((x,i)=>{const t=x.thumbnailDataUrl||x.dataUrl,image=t?"<button class=\"evidence-preview-button\" type=\"button\" title=\"查看原图\" onclick=\"openCurrentEvidence("+i+")\"><img class=\"current-evidence-thumb\" src=\""+escapeHtml(t)+"\" alt=\"截图 "+(i+1)+" 缩略图\"></button>":"",detail=x.status==="processing"?"原图已保存 · 金额识别后台进行中":x.actual!=null||x.bid!=null?"原图已保存 · 金额建议：实际 "+fmt(x.actual)+" · 成交 "+fmt(x.bid):"原图已保存 · 等待后续识别",label=i===0?"主结算图":"仓库补图";return "<div class=\"current-evidence-item\">"+image+"<span><strong>截图 "+(i+1)+" · "+label+"</strong><small>"+detail+"</small></span><div class=\"evidence-actions\"><button class=\"icon-btn\" type=\"button\" title=\"查看原图\" onclick=\"openCurrentEvidence("+i+")\">↗</button><button class=\"icon-btn\" type=\"button\" title=\"上移\" onclick=\"moveCurrentEvidence("+i+",-1)\" "+(i===0?"disabled":"")+">↑</button><button class=\"icon-btn\" type=\"button\" title=\"下移\" onclick=\"moveCurrentEvidence("+i+",1)\" "+(i===currentGameEvidence.length-1?"disabled":"")+">↓</button><button class=\"icon-btn\" type=\"button\" title=\"移除\" onclick=\"removeCurrentEvidence("+i+")\">×</button></div></div>";}).join(""):"<span class=\"muted\">尚未粘贴截图</span>";}
    window.moveCurrentEvidence=function(index,delta){const next=index+delta;if(next<0||next>=currentGameEvidence.length)return;[currentGameEvidence[index],currentGameEvidence[next]]=[currentGameEvidence[next],currentGameEvidence[index]];renderCurrentGameEvidence();};
    window.removeCurrentEvidence=function(index){const shot=currentGameEvidence[index];if(shot?.storageKey)void deleteScreenshotBlob(shot.storageKey);currentGameEvidence.splice(index,1);renderCurrentGameEvidence();toast("已从本局移除这张截图");};
    function renderRoundEvidence(){const list=document.getElementById("roundEvidenceList"),btn=document.getElementById("roundEvidenceBtn"),round=Number(val("calcRound"))||1;if(btn)btn.textContent=`添加 R${round} 截图`;if(!list)return;list.innerHTML=currentRoundEvidence.length?currentRoundEvidence.map((x,i)=>{const t=x.thumbnailDataUrl||x.dataUrl,image=t?`<button class="evidence-preview-button" type="button" title="查看原图" onclick="openRoundEvidence(${i})"><img src="${escapeHtml(t)}" alt="R${round}截图 ${i+1}"></button>`:"";return `<div class="round-evidence-item">${image}<span title="${escapeHtml(x.name||x.path||"")}">R${round} · 截图 ${i+1} · 原图已保存</span><div class="evidence-actions"><button class="icon-btn" type="button" title="查看原图" onclick="openRoundEvidence(${i})">↗</button><button class="icon-btn" type="button" title="上移" onclick="moveRoundEvidence(${i},-1)" ${i===0?"disabled":""}>↑</button><button class="icon-btn" type="button" title="下移" onclick="moveRoundEvidence(${i},1)" ${i===currentRoundEvidence.length-1?"disabled":""}>↓</button><button class="icon-btn" type="button" title="移除" onclick="removeRoundEvidence(${i})">×</button></div></div>`;}).join(""):"<span class=\"muted\">不需要截图也可以继续推演</span>";}
    window.moveRoundEvidence=function(index,delta){const next=index+delta;if(next<0||next>=currentRoundEvidence.length)return;[currentRoundEvidence[index],currentRoundEvidence[next]]=[currentRoundEvidence[next],currentRoundEvidence[index]];renderRoundEvidence();if(currentAnalysis)upsertCurrentRoundSnapshot(false);};
    window.removeRoundEvidence=function(index){const shot=currentRoundEvidence[index];if(shot?.storageKey)void deleteScreenshotBlob(shot.storageKey);currentRoundEvidence.splice(index,1);renderRoundEvidence();if(currentAnalysis)upsertCurrentRoundSnapshot(false);};
    function aggregateCurrentGameEvidence(){const out={minPurple:0,minGold:0,minRed:0,minBlue:0,minGreen:0,minWhite:0,exactPurple:null,exactGold:null,exactBlue:null,exactGreen:null,exactWhite:null,blueGrid:null,greenGrid:null,whiteGrid:null};for(const x of currentGameEvidence){const s=x.scan||{};/* 结算截图是同一仓库的 viewport 段：这里只取可见下界的最大值，绝不把重叠画面逐张相加。 */for(const [target,key] of [["minPurple","purple"],["minGold","gold"],["minRed","red"],["minBlue","blue"],["minGreen","green"],["minWhite","white"]])out[target]=Math.max(out[target],Number(s[key])||0);if(x.allVisible){out.exactPurple=Number.isFinite(Number(s.purple))?Number(s.purple):out.exactPurple;out.exactGold=Number.isFinite(Number(s.gold))?Number(s.gold):out.exactGold;out.exactBlue=Number.isFinite(Number(s.blue))?Number(s.blue):out.exactBlue;out.exactGreen=Number.isFinite(Number(s.green))?Number(s.green):out.exactGreen;out.exactWhite=Number.isFinite(Number(s.white))?Number(s.white):out.exactWhite;out.blueGrid=Number.isFinite(Number(s.blueGrid))?Number(s.blueGrid):out.blueGrid;out.greenGrid=Number.isFinite(Number(s.greenGrid))?Number(s.greenGrid):out.greenGrid;out.whiteGrid=Number.isFinite(Number(s.whiteGrid))?Number(s.whiteGrid):out.whiteGrid;}}return out;}
    function loadTesseract(){
      if(window.Tesseract)return Promise.resolve(window.Tesseract);if(ocrScriptPromise)return ocrScriptPromise;
      ocrScriptPromise=new Promise((resolve,reject)=>{const s=document.createElement("script");s.src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js";s.onload=()=>resolve(window.Tesseract);s.onerror=()=>reject(new Error("OCR 组件加载失败"));document.head.appendChild(s);});return ocrScriptPromise;
    }
    function hsvClass(r,g,b){
      r/=255;g/=255;b/=255;const mx=Math.max(r,g,b),mn=Math.min(r,g,b),d=mx-mn,s=mx?d/mx:0,v=mx;let h=0;
      if(d){if(mx===r)h=60*(((g-b)/d)%6);else if(mx===g)h=60*((b-r)/d+2);else h=60*((r-g)/d+4);if(h<0)h+=360;}
      if(v<.14)return -1;if(h>=250&&h<=325&&s>.22)return 0;if(h>=14&&h<=52&&s>.22)return 1;if((h<13||h>=326)&&s>.40)return 2;if(h>=175&&h<250&&s>.20)return 3;if(h>=58&&h<175&&s>.20)return 4;if(s<.18&&v>.26&&v<.92)return 5;return -1;
    }
    function colorComponents(mask,w,h){
      const seen=new Uint8Array(mask.length),out=[];
      for(let start=0;start<mask.length;start++){
        if(!mask[start]||seen[start])continue;
        const stack=[start];seen[start]=1;let area=0,minX=w,minY=h,maxX=0,maxY=0;
        while(stack.length){const i=stack.pop(),x=i%w,y=(i/w)|0;area++;minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);
          for(const n of [i-1,i+1,i-w,i+w]){if(n<0||n>=mask.length||seen[n]||!mask[n])continue;const nx=n%w;if(Math.abs(nx-x)>1)continue;seen[n]=1;stack.push(n);}
        }
        if(area>=120)out.push({area,minX,minY,maxX,maxY,bw:maxX-minX+1,bh:maxY-minY+1});
      }
      return out;
    }
    function alignedCardCount(mask,w,h,items,baseX,baseY){
      const dims=new Set(items.flatMap(x=>{const [a,b]=x[2].split("x").map(Number);return [`${a}x${b}`,`${b}x${a}`];})),components=colorComponents(mask,w,h),cellArea=baseX*baseY;let count=0,grid=0,partial=0,exact=0,split=0,rejected=0,fitScore=0;
      for(const c of components){
        const cols=Math.max(1,Math.round(c.bw/baseX)),rows=Math.max(1,Math.round(c.bh/baseY)),fitW=Math.abs(c.bw/baseX-cols),fitH=Math.abs(c.bh/baseY-rows),ax=Math.abs((c.minX-2)/baseX-Math.round((c.minX-2)/baseX)),ay=Math.abs(c.minY/baseY-Math.round(c.minY/baseY)),fill=c.area/(c.bw*c.bh),touch=c.maxX>=w-2||c.maxY>=h-2;
        // 卡片底色的外框与填充会形成接近整数格的矩形；图标本身通常不满足这个几何条件。
        if(ax>.24||ay>.24||fitW>.28||fitH>.28||fill<.30||c.area<cellArea*.12){rejected++;continue;}
        const key=`${cols}x${rows}`;
        if(dims.has(key)){count++;exact++;grid+=cols*rows;fitScore+=Math.max(0,1-(ax+ay+fitW+fitH)/1.04);continue;}
        // 滚动条截断的卡片不再硬套尺寸，只记作当前画面的一个下界。
        if(touch&&c.bw>=baseX*.65&&c.bh>=baseY*.35){partial++;grid+=Math.max(1,Math.floor(c.bw/baseX)*Math.max(1,Math.floor(c.bh/baseY)));continue;}
        // 同色相邻卡片偶尔会连成一个组件：按可用尺寸做保守拆分，宁可少报也不把图标算进去。
        const cells=Math.max(1,cols*rows),areas=[...new Set(items.map(x=>{const [a,b]=x[2].split("x").map(Number);return a*b;}))],dp=Array(cells+1).fill(99);dp[0]=0;
        for(let i=1;i<=cells;i++)for(const a of areas)if(i>=a)dp[i]=Math.min(dp[i],dp[i-a]+1);
        if(dp[cells]<99){const n=Math.min(dp[cells],6);count+=n;split+=n;grid+=cells;fitScore+=.55;}
      }
      const accepted=exact+split+partial,confidence=accepted?Math.max(.30,Math.min(.92,(fitScore+exact*.88+split*.48+partial*.22)/(accepted*1.1)-Math.min(.18,rejected*.015))):.30;
      return {count:count+partial,grid,partial,exact,split,rejected,confidence};
    }
    function detectRarityCounts(img){
      const sx=Math.round(img.naturalWidth*.682),sy=Math.round(img.naturalHeight*.201),sw=Math.round(img.naturalWidth*.290),sh=Math.round(img.naturalHeight*.517),scale=Math.min(1,900/Math.max(sw,sh)),canvas=document.createElement("canvas");canvas.width=Math.max(120,Math.round(sw*scale));canvas.height=Math.max(120,Math.round(sh*scale));const ctx=canvas.getContext("2d",{willReadFrequently:true});ctx.drawImage(img,sx,sy,sw,sh,0,0,canvas.width,canvas.height);const data=ctx.getImageData(0,0,canvas.width,canvas.height).data,masks=Array.from({length:6},()=>new Uint8Array(canvas.width*canvas.height));
      for(let i=0,p=0;i<data.length;i+=4,p++){const c=hsvClass(data[i],data[i+1],data[i+2]);if(c>=0)masks[c][p]=1;}
      const baseX=canvas.width/10,baseY=canvas.height/10,purple=alignedCardCount(masks[0],canvas.width,canvas.height,PURPLE_ITEMS,baseX,baseY),gold=alignedCardCount(masks[1],canvas.width,canvas.height,GOLD_ITEMS,baseX,baseY),red=alignedCardCount(masks[2],canvas.width,canvas.height,RED_ITEMS,baseX,baseY),blue=alignedCardCount(masks[3],canvas.width,canvas.height,BLUE_ITEMS,baseX,baseY),green=alignedCardCount(masks[4],canvas.width,canvas.height,GREEN_ITEMS,baseX,baseY),white=alignedCardCount(masks[5],canvas.width,canvas.height,WHITE_ITEMS,baseX,baseY),parts=[purple,gold,red,blue,green,white],visible=parts.reduce((s,x)=>s+x.count,0),confidence=visible?parts.reduce((s,x)=>s+x.confidence*Math.max(1,x.count),0)/parts.reduce((s,x)=>s+Math.max(1,x.count),0):.25;return {purple:purple.count,gold:gold.count,red:red.count,blue:blue.count,green:green.count,white:white.count,purpleGrid:purple.grid,goldGrid:gold.grid,redGrid:red.grid,blueGrid:blue.grid,greenGrid:green.grid,whiteGrid:white.grid,q:purple.count+gold.count+red.count,total:visible,totalGrid:purple.grid+gold.grid+red.grid+blue.grid+green.grid+white.grid,partial:parts.reduce((s,x)=>s+x.partial,0),split:parts.reduce((s,x)=>s+x.split,0),confidence:Math.max(.2,Math.min(.9,confidence))};
    }
    function cropForOcr(img,rel){const c=document.createElement("canvas"),scale=2,[x,y,w,h]=rel;c.width=Math.round(img.naturalWidth*w*scale);c.height=Math.round(img.naturalHeight*h*scale);const cx=c.getContext("2d");cx.drawImage(img,img.naturalWidth*x,img.naturalHeight*y,img.naturalWidth*w,img.naturalHeight*h,0,0,c.width,c.height);const d=cx.getImageData(0,0,c.width,c.height);for(let i=0;i<d.data.length;i+=4){const lum=.299*d.data[i]+.587*d.data[i+1]+.114*d.data[i+2],v=lum>135?255:0;d.data[i]=d.data[i+1]=d.data[i+2]=v;}cx.putImageData(d,0,0);return c;}
    function parseOcrNumber(text){const matches=String(text).match(/[\d,]{3,}/g)||[];const nums=matches.map(x=>Number(x.replaceAll(",",""))).filter(x=>Number.isFinite(x));return nums.length?Math.max(...nums):null;}
    let ocrTextWorker=null,ocrTextWorkerPromise=null;
    function markSettlementField(id,level,message){const el=document.getElementById(id);if(!el)return;const wrap=el.closest(".ocr-result");if(wrap){wrap.classList.remove("ocr-autofill-high","ocr-autofill-medium");if(level)wrap.classList.add(`ocr-autofill-${level}`);if(message)wrap.title=message;}el.dataset.ocrSuggested=level||"";}
    function settlementFieldTouched(id){const el=document.getElementById(id);return !!el?.dataset.userEdited;}
    function winnerFromOcrText(text){const normalized=String(text||"").replace(/[\s\u3000]/g,"");if(!normalized)return null;return normalized.startsWith("秋星祭")?"本人拍下":/[\u4e00-\u9fffA-Za-z0-9]{2,}/.test(normalized)?"其他人拍下":null;}
    function applySettlementOcrSuggestion(n,evidence){
      if(!n)return;
      const apply=(id,value,confidence,label)=>{if(!Number.isFinite(Number(value))||settlementFieldTouched(id))return null;const score=Math.max(0,Math.min(1,(Number(confidence)||0)/100)),level=score>=.78?"high":score>=.52?"medium":null;if(!level)return null;setVal(id,Number(value));markSettlementField(id,level,`${label} OCR ${Math.round(score*100)}%`);return level;};
      const actualLevel=apply("resultActualTotal",n.actual,n.actualConfidence,"实际总价"),bidLevel=apply("resultFinalBid",n.bid,n.bidConfidence,"成交价");
      const detectedWinner=winnerFromOcrText(n.winnerText);if(!settlementFieldTouched("resultWinner")&&detectedWinner&&Number(n.winnerConfidence||0)>=52){setVal("resultWinner",detectedWinner);markSettlementField("resultWinner",Number(n.winnerConfidence)>=78?"high":"medium",`赢家 OCR：${detectedWinner}`);}
      const levels=[actualLevel,bidLevel].filter(Boolean);if(levels.length&&evidence) evidence.ocrAutofill={actual:actualLevel,bid:bidLevel,winner:n.winnerText||null,at:new Date().toISOString()};
      if(levels.length)setOcrStatus(`截图已保留；${actualLevel?`实际总价 ${fmt(n.actual)}（${actualLevel==="high"?"高":"中"}置信）` :""}${bidLevel?` · 成交价 ${fmt(n.bid)}（${bidLevel==="high"?"高":"中"}置信）`:""}，可直接确认后保存。`);
    }
    function clearSettlementOcrMarks(){["resultFinalBid","resultActualTotal","resultWinner"].forEach(id=>{const el=document.getElementById(id),wrap=el?.closest(".ocr-result");if(wrap)wrap.classList.remove("ocr-autofill-high","ocr-autofill-medium");if(el)delete el.dataset.ocrSuggested;});}
    async function recognizeWinnerText(img){
      try{
        const T=await loadTesseract();
        if(!ocrTextWorkerPromise)ocrTextWorkerPromise=T.createWorker("chi_sim+eng",1).then(async worker=>{ocrTextWorker=worker;await worker.setParameters({preserve_interword_spaces:"1"});return worker;});
        const worker=await ocrTextWorkerPromise,box=cropForOcr(img,[.035,.16,.27,.30]),result=await worker.recognize(box),text=String(result?.data?.text||"").replace(/\s+/g,""),confidence=Number(result?.data?.confidence)||0;
        return {winnerText:text,winnerConfidence:confidence};
      }catch(_){return {winnerText:"",winnerConfidence:0};}
    }
    async function recognizeSettlementNumbers(img,owner=null){
      ocrStatusOwner=owner||null;const T=await loadTesseract();if(!ocrWorker){ocrWorker=await T.createWorker("eng",1,{logger:m=>{if(m.status==="recognizing text"&&(!ocrStatusOwner||currentGameEvidence.includes(ocrStatusOwner)))setOcrStatus(`正在识别金额 ${Math.round((m.progress||0)*100)}%…`);}});await ocrWorker.setParameters({tessedit_char_whitelist:"0123456789,",preserve_interword_spaces:"1"});}
      const actual=await ocrWorker.recognize(cropForOcr(img,[.245,.43,.175,.13])),bid=await ocrWorker.recognize(cropForOcr(img,[.045,.43,.195,.13])),winner=await recognizeWinnerText(img);return {actual:parseOcrNumber(actual.data.text),bid:parseOcrNumber(bid.data.text),actualConfidence:Number(actual.data.confidence)||0,bidConfidence:Number(bid.data.confidence)||0,...winner};
    }
    function screenshotPathForFile(file){return String(file?.webkitRelativePath||file?.name||"").replaceAll("\\","/");}
    function confidenceLevel(score){return score>=.72?"high":score>=.48?"medium":"low";}
    ["resultHighestPersonalBid","resultFinalBid","resultActualTotal","resultPurchaseSpend","resultGoldCount","resultPurpleCount","resultRedCount","resultWinner","resultAcquired","resultReason","resultFinalRed","resultRedInventoryComplete","resultTruthSource","resultTruthConfidence","resultNote"].forEach(id=>["input","change"].forEach(type=>document.getElementById(id)?.addEventListener(type,()=>{const el=document.getElementById(id);if(el)el.dataset.userEdited="1";})));
    document.getElementById("resultWinner")?.addEventListener("change",e=>{if(e.target.value==="本人拍下")setVal("resultAcquired","true");else if(e.target.value==="其他人拍下")setVal("resultAcquired","false");});
    document.getElementById("resultAcquired")?.addEventListener("change",e=>{if(e.target.value==="true"){if(!val("resultWinner"))setVal("resultWinner","本人拍下");if(!val("resultReason"))setVal("resultReason","acquired");if(!val("resultPurchaseSpend")&&val("resultFinalBid"))setVal("resultPurchaseSpend",val("resultFinalBid"));}});
    async function legacyProcessScreenshot(file){
      if(!file||!file.type.startsWith("image/")){setOcrStatus("请选择图片文件",true);return;}const url=URL.createObjectURL(file),img=document.getElementById("ocrImage");img.src=url;img.dataset.fileName=file.name||"截图";img.dataset.filePath=screenshotPathForFile(file);img.dataset.fileSize=String(file.size||0);document.getElementById("ocrPreview").classList.add("show");setOcrStatus("正在分析藏品卡片颜色…");
      await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject;});try{currentOcrDataUrl=compactScreenshotData(img);}catch(_){currentOcrDataUrl="";}let colorScore=.2;try{const c=detectRarityCounts(img);colorScore=c.confidence;setVal("ocrPurple",c.purple);setVal("ocrGold",c.gold);setVal("ocrRed",c.red);setVal("ocrBlue",c.blue);setVal("ocrGreen",c.green);setVal("ocrWhite",c.white);setVal("ocrBlueGrid",c.blueGrid);setVal("ocrGreenGrid",c.greenGrid);setVal("ocrWhiteGrid",c.whiteGrid);setVal("ocrTotalItems",c.q);img.dataset.rarityScan=JSON.stringify(c);setOcrStatus(`颜色草稿 ${Math.round(colorScore*100)}%：白 ${c.white} / 绿 ${c.green} / 蓝 ${c.blue} / 紫 ${c.purple} / 金 ${c.gold} / 红至少 ${c.red}${c.partial?`；边缘截断 ${c.partial} 件`:""}。继续识别金额…`);}catch(_){delete img.dataset.rarityScan;setOcrStatus("颜色识别失败，仍可手动填写金额和数量",true);}
      try{const n=await recognizeSettlementNumbers(img);setVal("ocrActual",n.actual);setVal("ocrBid",n.bid);const amountScore=Math.max(0,Math.min(1,Math.min(n.actualConfidence,n.bidConfidence)/100)),score=colorScore*.45+amountScore*.55;img.dataset.ocrConfidence=String(score);img.dataset.ocrNumbers=JSON.stringify(n);setOcrStatus(`识别完成 · 综合置信 ${Math.round(score*100)}%。请核对金额，尤其核对金色数量，再确认填入。${n.actual===null||n.bid===null?' 有金额未识别，请手动补上。':''}`);}catch(error){img.dataset.ocrConfidence=String(colorScore*.45);setOcrStatus("金额 OCR 未能加载；颜色数量已保留，可手动填写两个金额。",true);}finally{URL.revokeObjectURL(url);}
    }
    async function processScreenshot(file){if(currentGameEvidence.length>=3){setOcrStatus("本局最多保存 3 张结算截图；可先删除错误截图再补图。",true);return;}if(!file||!file.type.startsWith("image/")){setOcrStatus("请选择图片文件",true);return;}const evidence={id:uid(),name:file.name||"截图",path:screenshotPathForFile(file),thumbnailDataUrl:null,dataUrl:null,actual:null,bid:null,scan:null,confidence:0,status:"processing",source:"clipboard",originalStorage:"indexeddb",storageKey:uid(),originalBytes:file.size||null,originalMime:file.type||"image/*",importedAt:new Date().toISOString()};currentGameEvidence.push(evidence);void persistScreenshotBlob(evidence.storageKey,file).catch(()=>{evidence.originalStorage="metadata-only";});renderCurrentGameEvidence();setOcrStatus("截图 "+currentGameEvidence.length+" 原图已保存；后台尝试识别金额…");const url=URL.createObjectURL(file),img=new Image();try{await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject;img.src=url;});evidence.originalWidth=img.naturalWidth;evidence.originalHeight=img.naturalHeight;evidence.thumbnailDataUrl=compactScreenshotData(img);evidence.dataUrl=evidence.thumbnailDataUrl;currentOcrDataUrl=evidence.dataUrl;renderCurrentGameEvidence();void (async()=>{let colorScore=.2;try{const c=detectRarityCounts(img);evidence.scan=c;colorScore=c.confidence;}catch(_){evidence.scan=null;}try{const n=await recognizeSettlementNumbers(img,evidence);evidence.actual=n.actual;evidence.bid=n.bid;const amountScore=Math.max(0,Math.min(1,Math.min(n.actualConfidence,n.bidConfidence)/100));evidence.confidence=colorScore*.45+amountScore*.55;evidence.ocrNumbers=n;evidence.status="parsed";applySettlementOcrSuggestion(n,evidence);if(currentGameEvidence.includes(evidence)&&!evidence.ocrAutofill)setOcrStatus("截图已保留；金额识别建议 "+(n.actual==null?"未识别":fmt(n.actual))+" / "+(n.bid==null?"未识别":fmt(n.bid))+"，请确认后填入结算。");}catch(_){evidence.confidence=colorScore*.45;evidence.status="parsed";if(currentGameEvidence.includes(evidence))setOcrStatus("截图已保留；金额 OCR 未完成，不影响保存。",true);}if(currentGameEvidence.includes(evidence))renderCurrentGameEvidence();})();}catch(_){evidence.status="error";if(currentGameEvidence.includes(evidence))setOcrStatus("截图已加入，但无法读取预览；仍可保存本局。",true);if(currentGameEvidence.includes(evidence))renderCurrentGameEvidence();}finally{URL.revokeObjectURL(url);}}
    const ocrDrop=document.getElementById("ocrDropZone"),ocrFile=document.getElementById("ocrFile"),roundEvidenceBtn=document.getElementById("roundEvidenceBtn"),roundEvidenceFile=document.getElementById("roundEvidenceFile");ocrDrop.addEventListener("click",()=>ocrFile.click());ocrDrop.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();ocrFile.click();}});ocrFile.addEventListener("change",e=>{processScreenshot(e.target.files[0]);e.target.value="";});if(roundEvidenceBtn&&roundEvidenceFile){roundEvidenceBtn.addEventListener("click",()=>roundEvidenceFile.click());roundEvidenceFile.addEventListener("change",e=>{processRoundEvidence(e.target.files[0]);e.target.value="";});}["dragenter","dragover"].forEach(t=>ocrDrop.addEventListener(t,e=>{e.preventDefault();ocrDrop.classList.add("dragover");}));["dragleave","drop"].forEach(t=>ocrDrop.addEventListener(t,e=>{e.preventDefault();ocrDrop.classList.remove("dragover");}));ocrDrop.addEventListener("drop",e=>processScreenshot(e.dataTransfer.files[0]));document.addEventListener("paste",e=>{if(!document.getElementById("page-calculator").classList.contains("active"))return;const file=[...e.clipboardData.items].find(x=>x.type.startsWith("image/"))?.getAsFile();if(file){e.preventDefault();const settlement=document.getElementById("settlementCapture");if(settlement?.open)processScreenshot(file);else processRoundEvidence(file);}});document.getElementById("clearOcrBtn").addEventListener("click",resetOcrDraft);
    function imageFromFile(file){return new Promise((resolve,reject)=>{const url=URL.createObjectURL(file),img=new Image();img.onload=()=>resolve({img,url});img.onerror=()=>{URL.revokeObjectURL(url);reject(new Error("图片读取失败"));};img.src=url;});}
    async function processRoundEvidence(file){if(!file||!file.type.startsWith("image/")){toast("请选择图片文件",true);return;}const round=Number(val("calcRound"))||1,evidence={id:uid(),name:file.name||"本回合截图",path:screenshotPathForFile(file),round,thumbnailDataUrl:null,dataUrl:null,status:"processing",source:"round-evidence",originalStorage:"indexeddb",storageKey:uid(),originalBytes:file.size||null,originalMime:file.type||"image/*",importedAt:new Date().toISOString()};currentRoundEvidence.push(evidence);void persistScreenshotBlob(evidence.storageKey,file).catch(()=>{evidence.originalStorage="metadata-only";});renderRoundEvidence();try{const loaded=await imageFromFile(file);evidence.originalWidth=loaded.img.naturalWidth;evidence.originalHeight=loaded.img.naturalHeight;evidence.thumbnailDataUrl=compactScreenshotData(loaded.img);evidence.dataUrl=evidence.thumbnailDataUrl;evidence.status="saved";URL.revokeObjectURL(loaded.url);renderRoundEvidence();if(currentAnalysis)upsertCurrentRoundSnapshot(false);}catch(_){evidence.status="metadata-only";renderRoundEvidence();} }
    function mergeScreenshotEvidence(record,evidence){
      const shots=new Map((record.screenshots||[]).map(x=>[x.path||x.name,x])),shot={name:evidence.name,path:evidence.path,kind:"settlement",ocrConfidence:evidence.confidence,verifiedActual:evidence.actual||null,addedAt:evidence.importedAt};shots.set(shot.path||shot.name,shot);
      const prior=record.settlement||{},status=prior.status|| (Number(record.actualTotal)>0?"verified":"pending"),settlement={...prior,status,screenshots:[...shots.values()],actualTotal:prior.actualTotal??(Number(record.actualTotal)>0?Number(record.actualTotal):null),bid:prior.bid??(Number(record.bid)>0?Number(record.bid):null),ocrSuggestions:[...(prior.ocrSuggestions||[]).filter(x=>(x.path||x.name)!==(evidence.path||evidence.name)),evidence],source:prior.source||"post-settlement",verified:status==="verified"};
      // 后处理 OCR 只能进入 settlement/T2，不回写推演输入或任何 round snapshot。
      const next={...record,screenshots:[...shots.values()],settlement,ocrEvidence:[...(record.ocrEvidence||[]).filter(x=>(x.path||x.name)!==(evidence.path||evidence.name)),evidence],updatedAt:Date.now()};
      return normalizeRecord(next);
    }
    function renderScreenshotInbox(){
      const el=document.getElementById("screenshotInbox"),items=Array.isArray(state.screenshotInbox)?state.screenshotInbox:[];if(!el)return;
      el.innerHTML=items.length?items.map((x,i)=>`<div class="inbox-item"><div><strong>${escapeHtml(x.name||x.path||"未命名截图")}</strong><small>实际 ${fmt(x.actual)} · 成交 ${fmt(x.bid)} · 可见紫/金/红 ${x.scan?.purple??"?"}/${x.scan?.gold??"?"}/${x.scan?.red??"?"} · <span class="confidence-pill ${confidenceLevel(x.confidence||0)}">置信 ${Math.round((x.confidence||0)*100)}%</span></small></div><button class="btn small" type="button" onclick="useScreenshotInbox(${i})">填入表单</button></div>`).join(""):"";
      const bound=state.records.reduce((n,r)=>n+(r.screenshots?.length||0),0),status=document.getElementById("batchScreenshotStatus");if(status)status.textContent=`已绑定 ${bound} 张历史截图；待人工核对 ${items.length} 张。批量识别只补最低数量，不覆盖人工精确值。`;
    }
    window.useScreenshotInbox=function(index){const x=state.screenshotInbox?.[index];if(!x)return;resetRecordForm({role:"纯看客",character:"达芙蒂尔",venue:"中级场 · 珊瑚场",box:"未知箱型"});setVal("recordActual",x.actual);setVal("recordBid",x.bid);setVal("recordScreenshotPath",x.path);setVal("recordScreenshotName",x.name);setVal("recordOcrConfidence",x.confidence);for(const [to,key] of [["recordMinPurple","purple"],["recordMinGold","gold"],["recordMinRed","red"],["recordMinBlue","blue"],["recordMinGreen","green"],["recordMinWhite","white"]])if(Number(x.scan?.[key])>0)setVal(to,x.scan[key]);setVal("recordMinRedQuick",val("recordMinRed"));renderRecordScreenshotSummary();updateQuality();showPage("capture");document.getElementById("recordForm").scrollIntoView({behavior:"smooth",block:"start"});};
    async function batchProcessScreenshots(files){
      const list=[...files].filter(f=>f.type.startsWith("image/"));if(!list.length){toast("文件夹里没有图片",true);return;}let matched=0,pending=0,failed=0;const status=document.getElementById("batchScreenshotStatus");
      for(let i=0;i<list.length;i++){
        const file=list[i],path=screenshotPathForFile(file),name=file.name;status.textContent=`正在处理 ${i+1}/${list.length}：${name}`;
        try{const loaded=await imageFromFile(file);let scan=null,numbers={actual:null,bid:null,actualConfidence:0,bidConfidence:0};try{scan=detectRarityCounts(loaded.img);}catch(_){}try{numbers=await recognizeSettlementNumbers(loaded.img);}catch(_){}URL.revokeObjectURL(loaded.url);const amountScore=Math.max(0,Math.min(1,Math.min(numbers.actualConfidence||0,numbers.bidConfidence||0)/100)),confidence=(scan?.confidence||.2)*.45+amountScore*.55,evidence={name,path,actual:numbers.actual,bid:numbers.bid,scan,confidence,importedAt:new Date().toISOString()};
          let index=state.records.findIndex(r=>(r.screenshots||[]).some(x=>(x.path||x.name)===(path||name)));if(index<0&&numbers.actual!=null){const hits=state.records.map((r,j)=>({r,j})).filter(x=>Number(x.r.actualTotal)===Number(numbers.actual));if(hits.length===1)index=hits[0].j;}
          if(index>=0){state.records[index]=mergeScreenshotEvidence(state.records[index],evidence);matched++;}else{const inbox=Array.isArray(state.screenshotInbox)?state.screenshotInbox:[];state.screenshotInbox=[...inbox.filter(x=>(x.path||x.name)!==(path||name)),evidence];pending++;}
        }catch(_){failed++;}
      }
      saveState();renderScreenshotInbox();renderReview();status.textContent=`批量完成：匹配历史 ${matched}，待核对 ${pending}，失败 ${failed}。金色识别仍需人工抽查。`;toast(`截图批量处理完成：匹配 ${matched} / 待核对 ${pending}`);
    }
    document.getElementById("batchScreenshotBtn").addEventListener("click",()=>document.getElementById("batchScreenshotFiles").click());
    document.getElementById("batchScreenshotFiles").addEventListener("change",e=>{batchProcessScreenshots(e.target.files);e.target.value="";});
    document.getElementById("clearScreenshotInboxBtn").addEventListener("click",()=>{state.screenshotInbox=[];saveState();renderScreenshotInbox();toast("待核对截图已清空；已绑定历史不受影响");});

    /* 实时结算已自动追加截图；保留旧校对实现但不再挂载，避免 T2 事实写回推演字段。 */
    if(false)document.getElementById("applyOcrBtn").addEventListener("click",()=>{
      const image=document.getElementById("ocrImage");if(!image.getAttribute("src")){toast("请先粘贴或选择截图",true);return;}
      const baseScan=JSON.parse(image.dataset.rarityScan||"{}");
      const read=id=>val(id)===""?null:Number(val(id));
      const all=document.getElementById("ocrAllVisible").checked;
      const scan={...baseScan,purple:read("ocrPurple"),gold:read("ocrGold"),red:read("ocrRed"),blue:read("ocrBlue"),green:read("ocrGreen"),white:read("ocrWhite"),blueGrid:read("ocrBlueGrid"),greenGrid:read("ocrGreenGrid"),whiteGrid:read("ocrWhiteGrid")};
      const importedAt=new Date().toISOString();
      const name=image.dataset.fileName||`粘贴截图-${importedAt.replaceAll(":","-")}.jpg`;
      const evidencePath=image.dataset.filePath||name;
      const priorEvidence=currentGameEvidence.at(-1)||{};
      const evidence={name,path:evidencePath,dataUrl:currentOcrDataUrl||null,actual:read("ocrActual")??priorEvidence.actual??null,bid:read("ocrBid")??priorEvidence.bid??null,scan,allVisible:all,confidence:Number(image.dataset.ocrConfidence)||0,importedAt};
      currentGameEvidence.push(evidence);renderCurrentGameEvidence();
      for(const [key,target] of [["purple","calcMinPurple"],["gold","calcMinGold"],["red","calcMinRed"]])if(Number(scan[key])>0)setVal(target,Math.max(Number(val(target))||0,Number(scan[key])));
      if(all){if(scan.purple!=null)setVal("calcPurple",scan.purple);if(scan.gold!=null)setVal("calcGoldCount",scan.gold);for(const [key,target] of [["blue","calcBlueCount"],["green","calcGreenCount"],["white","calcWhiteCount"],["blueGrid","calcBlueGrid"],["greenGrid","calcGreenGrid"],["whiteGrid","calcWhiteGrid"]])if(scan[key]!=null)setVal(target,scan[key]);}
      const resultActual=document.getElementById("resultActualTotal"),resultBid=document.getElementById("resultFinalBid");if(resultActual&&evidence.actual!=null)resultActual.value=evidence.actual;if(resultBid&&evidence.bid!=null)resultBid.value=evidence.bid;
      resetOcrDraft();toast(`已加入本局第 ${currentGameEvidence.length} 张截图${all?"；紫/金按完整画面记录，红仍只记至少":"；所有颜色只记当前画面下界"}`);
    });

const recordInputs=["recordQ","recordGoldAvg","recordGoldTotal","recordGoldCount","recordPurple","recordPurpleAvg","recordMinPurple","recordMinGold","recordMinRed","recordMinRedQuick","recordMinBlue","recordMinGreen","recordMinWhite","recordKnownPurple","recordKnownGold","recordKnownRed","recordActual","recordCharacter","recordVenue","recordBox","recordPlayedAt","recordWinner","recordAcquired","recordResultReason","recordRedCount","recordRedItems","recordRedInventoryComplete","recordTotalItems","recordTotalGrid","recordGoldGrid","recordPurpleGrid","recordBlueCount","recordBlueGrid","recordBlueAvg","recordGreenCount","recordGreenGrid","recordGreenAvg","recordWhiteCount","recordWhiteGrid","recordWhiteAvg","recordSystemEstimate","recordSingleAvg","recordNineAvg","recordPublicNote"];
    recordInputs.forEach(id=>document.getElementById(id)?.addEventListener("input",updateQuality));
    document.getElementById("recordMinRedQuick").addEventListener("input",()=>{setVal("recordMinRed",val("recordMinRedQuick"));updateQuality();});
    document.getElementById("recordWinner")?.addEventListener("change",e=>{if(e.target.value==="本人拍下")setVal("recordAcquired","true");else if(e.target.value==="其他人拍下")setVal("recordAcquired","false");});
    document.getElementById("recordAcquired")?.addEventListener("change",e=>{if(e.target.value==="true"){if(!val("recordWinner"))setVal("recordWinner","本人拍下");if(!val("recordResultReason"))setVal("recordResultReason","acquired");if(!val("recordPurchaseSpend")&&val("recordClearingPrice"))setVal("recordPurchaseSpend",val("recordClearingPrice"));}});
    ["recordPurple","recordGoldCount","recordRedCount"].forEach(id=>document.getElementById(id).addEventListener("input",()=>{const parts=[num("recordPurple"),num("recordGoldCount"),num("recordRedCount")];if(parts.every(x=>Number.isInteger(x)&&x>=0))setVal("recordQ",parts.reduce((a,b)=>a+b,0));updateQuality();}));
    function updateQuality(){
      const q=num("recordQ"), actual=num("recordActual"), gold=num("recordGoldAvg"), goldTotal=num("recordGoldTotal"), goldCount=num("recordGoldCount"), purple=num("recordPurple"), purpleAvg=num("recordPurpleAvg"), red=num("recordRedCount"), redItems=val("recordRedItems"), context=val("recordCharacter")!=="未知助手"&&val("recordVenue")!=="未知场地"&&!val("recordBox").startsWith("未知")&&!!val("recordPlayedAt"), publicFeature=num("recordTotalItems")!==null||num("recordTotalGrid")!==null||num("recordPurpleGrid")!==null||num("recordBlueCount")!==null||num("recordBlueGrid")!==null||num("recordBlueAvg")!==null||num("recordGreenCount")!==null||num("recordGreenGrid")!==null||num("recordGreenAvg")!==null||num("recordWhiteCount")!==null||num("recordWhiteGrid")!==null||num("recordWhiteAvg")!==null||num("recordMinBlue")!==null||num("recordMinGreen")!==null||num("recordMinWhite")!==null||num("recordSystemEstimate")!==null||!!val("recordPublicNote");
      const flags={q:Number.isInteger(q)&&q>0,context,actual:actual!==null&&actual>0,gold:(goldCount!==null&&goldCount>=0)||(gold!==null&&gold>0)||(goldTotal!==null&&goldTotal>0)||(num("recordMinGold")??0)>0||!!val("recordKnownGold"),purple:(purple!==null&&purple>=0)||(purpleAvg!==null&&purpleAvg>0)||(num("recordMinPurple")??0)>0||!!val("recordKnownPurple"),red:(red!==null&&red>=0)||(num("recordMinRed")??0)>0||!!val("recordKnownRed")||!!redItems,public:publicFeature};
      const weights={q:10,context:20,actual:30,gold:15,purple:10,red:10,public:5};let score=0;Object.entries(flags).forEach(([k,v])=>{document.querySelector(`[data-quality=${k}]`).classList.toggle("done",v);if(v)score+=weights[k];});
      document.getElementById("qualityScore").textContent=score;document.getElementById("qualityLabel").textContent=score>=85?"高信息样本 · 可校准追红":score>=65?"可训练样本":score>=45?"基础监督样本":"信息不足";
    }

    onEl("recordForm") && document.getElementById("recordForm").addEventListener("submit",e=>{
      e.preventDefault(); let q=num("recordQ");const actual=num("recordActual"),highestPersonalBid=num("recordBid"),clearingPrice=num("recordClearingPrice"),purchaseSpend=num("recordPurchaseSpend"),acquired=explicitBoolean(val("recordAcquired")),resultReason=val("recordResultReason"),recordTotalGrid=num("recordTotalGrid"),recordGoldGrid=num("recordGoldGrid"),purpleGrid=num("recordPurpleGrid"),blueCount=num("recordBlueCount"),blueGrid=num("recordBlueGrid"),blueAvg=num("recordBlueAvg"),greenCount=num("recordGreenCount"),greenGrid=num("recordGreenGrid"),greenAvg=num("recordGreenAvg"),whiteCount=num("recordWhiteCount"),whiteGrid=num("recordWhiteGrid"),whiteAvg=num("recordWhiteAvg"),exactGold=num("recordGoldCount"),exactPurple=num("recordPurple"),exactRed=num("recordRedCount"),minBlue=num("recordMinBlue")??0,minGreen=num("recordMinGreen")??0,minWhite=num("recordMinWhite")??0,fieldCondition=canonicalFieldConditionId(val("recordFieldCondition")),avgValueBasis=normalizeAvgValueBasis(val("recordAvgValueBasis")),privateBidCap=num("recordPrivateBidCap"),bidActionCount=num("recordBidActionCount"),gemCount=num("recordTransformedOneByOneCount"),sparkle={transformedOneByOneCount:integerOrNull(gemCount),verifiedGemItems:val("recordVerifiedGemItems"),complete:document.getElementById("recordGemInventoryComplete")?.checked===true},welfare=welfareFromInputs("record",fieldCondition),intelEvents=normalizeIntelEvents(fieldCondition==="extraIntel"?[...conditionIntelEvents(fieldCondition,1,val("recordPublicNote")),...conditionIntelEvents(fieldCondition,3,val("recordPublicNote"))]:[]);
      if([exactGold,exactPurple,exactRed].every(x=>x!==null)&&q===null){q=exactGold+exactPurple+exactRed;setVal("recordQ",q);}
      if(q!==null&&(!Number.isInteger(q)||q<1)){toast("Q 无效；不知道可以留空",true);return;}if(recordTotalGrid!==null&&(!Number.isInteger(recordTotalGrid)||recordTotalGrid<1||recordTotalGrid>TOTAL_GRID_INPUT_MAX)){toast(`全部总格数必须是 1～${TOTAL_GRID_INPUT_MAX} 的整数`,true);return;}if(recordGoldGrid!==null&&(!Number.isInteger(recordGoldGrid)||recordGoldGrid<0||recordGoldGrid>GRID_SOLVER_MAX)){toast(`金色占格目前支持 0～${GRID_SOLVER_MAX} 格`,true);return;} if(actual!==null&&actual<0){toast("实际总价不能为负数",true);return;}for(const [value,label] of [[highestPersonalBid,"我的最高出价"],[clearingPrice,"最终成交价"],[purchaseSpend,"本人实际支付"]])if(value!==null&&(!Number.isFinite(value)||value<0)){toast(`${label}不能为负数`,true);return;}if(acquired===true&&purchaseSpend===null){toast("确认本人拍下时，请填写本人实际支付",true);return;}if(acquired===false&&purchaseSpend!==null&&purchaseSpend>0){toast("未拍下的对局不应填写本人实际支付",true);return;}for(const [value,label] of [[purpleGrid,"紫色占格数"],[blueCount,"蓝色数量"],[blueGrid,"蓝色占格数"],[greenCount,"绿色数量"],[greenGrid,"绿色占格数"],[whiteCount,"白色数量"],[whiteGrid,"白色占格数"],[minBlue,"蓝色最低数量"],[minGreen,"绿色最低数量"],[minWhite,"白色最低数量"]])if(value!==null&&(!Number.isInteger(value)||value<0)){toast(`${label}必须是非负整数`,true);return;}for(const [value,label] of [[blueAvg,"蓝色"],[greenAvg,"绿色"],[whiteAvg,"白色"]])if(value!==null&&(!Number.isInteger(value)||value<=0)){toast(`${label}均价必须是正整数`,true);return;}if((blueCount!==null&&blueCount<minBlue)||(greenCount!==null&&greenCount<minGreen)||(whiteCount!==null&&whiteCount<minWhite)){toast("蓝/绿/白精确数量不能小于对应最低数量",true);return;}
      for(const [value,label] of [[privateBidCap,"私人出价上限"],[bidActionCount,"出价次数"],[gemCount,"转换 1×1 数量"]])if(value!==null&&(!Number.isInteger(value)||value<0)){toast(`${label}必须是非负整数`,true);return;}
      if(fieldCondition==="sparkle"){const audit=sparkleTruthAudit(sparkle,{playedAt:val("recordPlayedAt")});if(!audit.ok){toast(audit.error,true);return;}}
      let kp,kg,kr,kgGroups=[],kpGroups=[],krGroups=[];try{const purplePriceOptions={multiplier:conditionPriceMultiplier({fieldCondition},"purple"),basis:avgValueBasis},goldPriceOptions={multiplier:conditionPriceMultiplier({fieldCondition},"gold"),basis:avgValueBasis},purpleParsed=parseFlexibleKnown(val("recordKnownPurple"),PURPLE_ITEMS,"紫色",purplePriceOptions);kp=purpleParsed.known;kpGroups=purpleParsed.groups;const goldParsed=parseFlexibleKnown(val("recordKnownGold"),GOLD_ITEMS,"金色",goldPriceOptions);kg=goldParsed.known;kgGroups=goldParsed.groups;const redParsed=parseFlexibleKnown(val("recordKnownRed"),RED_ITEMS,"红色",{multiplier:1,basis:"base"});kr=redParsed.known;krGroups=redParsed.groups;}catch(error){toast(error.message,true);return;}
      const goldGroupFloor=kgGroups.length?Math.max(...kgGroups.map(x=>x[1])):0,minPurple=Math.max(num("recordMinPurple")??0,kp.length,kpGroups.reduce((s,x)=>s+x[1],0)),minGold=Math.max(num("recordMinGold")??0,kg.length,goldGroupFloor),minRed=Math.max(num("recordMinRed")??0,kr.length,krGroups.reduce((s,x)=>s+x[1],0));
      if([minPurple,minGold,minRed].some(x=>!Number.isInteger(x)||x<0)||(q!==null&&minPurple+minGold+minRed>q)){toast("最低数量无效或总和超过 Q",true);return;}
      if(exactGold!==null&&exactGold<minGold){toast("金色精确数量不能小于最低数量",true);return;}if(exactPurple!==null&&exactPurple<minPurple){toast("紫色精确数量不能小于最低数量",true);return;}if(exactRed!==null&&exactRed<minRed){toast("红色精确数量不能小于最低数量",true);return;}
      if(q!==null&&[exactGold,exactPurple,exactRed].filter(x=>x!==null).reduce((a,b)=>a+b,0)>q){toast("精确数量之和不能超过 Q",true);return;}
      const hasAllCounts=[exactGold,exactPurple,exactRed].every(x=>Number.isInteger(x)&&x>=0),realizedState=hasAllCounts&&q!==null&&exactGold+exactPurple+exactRed===q?{gold:exactGold,purple:exactPurple,red:exactRed,complete:true,source:val("recordTruthSource")||"manual-settlement",confidence:val("recordTruthConfidence")||"unknown"}:null;
      if(hasAllCounts&&q!==null&&!realizedState){toast(`结算数量必须满足 G + P + R = Q（当前 Q=${q}）`,true);return;}
      const redInventoryComplete=document.getElementById("recordRedInventoryComplete")?.checked===true,finalRed=val("recordRedItems");if(redInventoryComplete&&!realizedState){toast("确认完整红货清单前，请先填写完整的 G / P / R",true);return;}if(redInventoryComplete&&/[\/／]/.test(finalRed)){toast("完整红货清单不能包含 / 歧义项",true);return;}const parsedFinalRed=redInventoryComplete?parseHistoricalRedItems(finalRed):[];if(redInventoryComplete&&((exactRed===0&&finalRed)||(exactRed>0&&parsedFinalRed.length!==exactRed))){toast(`完整红货清单必须与 R=${exactRed} 一致，并且每件都能在红色图鉴中识别`,true);return;}
      const existingId=val("recordId"), existing=state.records.find(r=>r.id===existingId), prediction=document.getElementById("recordForm").dataset.prediction?JSON.parse(document.getElementById("recordForm").dataset.prediction):(existing?.prediction||null);
      const shotPath=val("recordScreenshotPath"),shotName=val("recordScreenshotName"),shotConfidence=num("recordOcrConfidence"),shot=shotPath||shotName?{name:shotName||shotPath.split("/").pop(),path:shotPath||shotName,kind:"settlement",ocrConfidence:shotConfidence,verifiedActual:actual||null,addedAt:new Date().toISOString()}:null,shotMap=new Map((existing?.screenshots||[]).map(x=>[x.path||x.name,x]));if(shot)shotMap.set(shot.path||shot.name,shot);const screenshots=[...shotMap.values()];
      const winner=val("recordWinner")||"",costs=costBreakdownFromInputs("record","manual-record"),truthSource=val("recordTruthSource")||"manual-settlement",truthConfidence=val("recordTruthConfidence")||"unknown",verifiedRedText=redInventoryComplete?finalRed:"",playedAt=val("recordPlayedAt")||nowLocalInput(),periodKey=periodOf(playedAt)||"日期未知",settlement={...(existing?.settlement||{}),status:actual!==null&&actual>0?"verified":"pending",fieldCondition,avgValueBasis,privateBidCap,bidActionCount,welfare,sparkle,intelEvents,actualTotal:actual??null,bid:clearingPrice??null,highestPersonalBid:highestPersonalBid??null,clearingPrice:clearingPrice??null,purchaseSpend:purchaseSpend??null,acquired,resultReason:resultReason||null,costs,winner:winner||existing?.settlement?.winner||null,note:val("recordNotes")||existing?.settlement?.note||"",realizedState,goldCount:realizedState?.gold??null,purpleCount:realizedState?.purple??null,redCount:realizedState?.red??null,redInventoryComplete,verifiedRedItems:verifiedRedText,truthSource,truthConfidence,verified:actual!==null&&actual>0,screenshots};const normalizedPrediction=prediction?{...prediction,fieldCondition,avgValueBasis,privateBidCap,bidActionCount,welfare,sparkle,intelEvents}:prediction,record={id:existingId||uid(),productVersion:existing?productVersionFor(existing):APP_VERSION,playedAt,periodKey,date:playedAt.slice(0,10),role:val("recordRole"),character:val("recordCharacter"),venue:val("recordVenue"),box:val("recordBox"),fieldCondition,avgValueBasis,privateBidCap,bidActionCount,welfare,sparkle,intelEvents,patch:periodKey,q,goldAvg:num("recordGoldAvg"),goldCount:exactGold,purpleCount:exactPurple,purpleAvg:num("recordPurpleAvg"),goldTotal:num("recordGoldTotal"),minPurple,minGold,minRed,minBlue,minGreen,minWhite,knownPurple:val("recordKnownPurple"),knownGold:val("recordKnownGold"),knownRed:val("recordKnownRed"),decisionKnownRed:val("recordKnownRed"),actualTotal:actual,bid:highestPersonalBid,highestPersonalBid,clearingPrice,purchaseSpend,acquired,resultReason,noBidReason:acquired===false?resultReason:"",costs,cost:costs.total,outcome:val("recordOutcome"),winner,redCount:exactRed,realizedState,redInventoryComplete,settlementVerifiedRedItems:verifiedRedText,redItems:verifiedRedText,totalItems:num("recordTotalItems"),totalGrid:num("recordTotalGrid"),goldGrid:num("recordGoldGrid"),purpleGrid,blueCount,blueGrid,blueAvg,greenCount,greenGrid,greenAvg,whiteCount,whiteGrid,whiteAvg,systemEstimate:num("recordSystemEstimate"),singleAvg:num("recordSingleAvg"),nineAvg:num("recordNineAvg"),publicNote:val("recordPublicNote"),notes:val("recordNotes"),screenshots,settlement,ocrConfidence:shotConfidence??existing?.ocrConfidence??null,rounds:existing?.rounds||[],source:existing?.source||"user",legacy:existing?.legacy||false,createdAt:existing?.createdAt||Date.now(),updatedAt:Date.now(),prediction:normalizedPrediction};
      if(existing){state.records=state.records.map(r=>r.id===existingId?record:r);}else state.records.unshift(record);
      saveState();toast(existing?"样本已更新":"样本已保存");resetRecordForm({role:record.role,character:record.character,venue:record.venue,box:record.box});resetOcrDraft();updateQuality();
    });
    document.getElementById("cancelEditBtn").addEventListener("click",resetRecordForm);
    function resetRecordForm(context=null){document.getElementById("recordForm").reset();setVal("recordId","");setVal("recordScreenshotPath","");setVal("recordScreenshotName","");setVal("recordOcrConfidence","");setVal("recordMinRedQuick","");setVal("recordPlayedAt",nowLocalInput());setVal("recordRole",context?.role||"纯看客");setVal("recordCharacter",context?.character&&context.character!=="未知助手"?context.character:"达芙蒂尔");setVal("recordVenue",context?.venue||"中级场 · 珊瑚场");fillBoxOptions("recordVenue","recordBox",context?.box||"未知箱型");setVal("recordFieldCondition","unknown");setVal("recordAvgValueBasis","unknown");setVal("recordEntryCost",5000);setVal("recordInfoCost",50000);setVal("recordOtherCost",0);syncCostInputs("record");setVal("recordWinner","");setVal("recordAcquired","");setVal("recordResultReason","");setVal("recordWelfareRate","");syncWelfareInputs("record");setVal("recordTruthSource","manual-settlement");setVal("recordTruthConfidence","high");for(const id of ["recordRedInventoryComplete","recordGemInventoryComplete"]){const el=document.getElementById(id);if(el)el.checked=false;}document.getElementById("recordForm").dataset.prediction="";document.getElementById("recordFormTitle").textContent="历史补录";document.getElementById("recordModeBadge").textContent="新样本";document.getElementById("cancelEditBtn").classList.add("hidden");renderRecordScreenshotSummary();}
    function startNewRound(){
      const calcContext={character:"达芙蒂尔",venue:val("calcVenue"),box:val("calcBox"),toolGroup:val("calcToolGroup")||"group1"},recordContext={role:val("recordRole")||"纯看客",character:"达芙蒂尔",venue:val("recordVenue"),box:val("recordBox")};
      resetCalculatorDraft(calcContext);resetRecordForm(recordContext);resetOcrDraft();updateQuality();window.scrollTo({top:0,behavior:"smooth"});toast("本局草稿已清除；历史、数据连接和场地设置已保留");
    }
    const _newRound=document.getElementById("newRoundBtn"); if(_newRound)_newRound.addEventListener("click",startNewRound);
    function historyInference(r){
      if(!r) return "";
      const input=predictionInputRecord(r);
      const bits=[];
      if(input.goldTotal!=null) bits.push("金总已锁定");
      else if(input.goldAvg!=null && input.goldCount!=null) bits.push("金均×件数");
      else if(input.goldAvg!=null) bits.push("仅金均");
      if(input.purpleCount!=null) bits.push("紫数P="+input.purpleCount);
      if(input.redCount!=null) bits.push("红R="+input.redCount);
      else if(String(input.knownRed||"").trim()||Number(input.minRed)>0) bits.push("有红货下限");
      if(input.systemEstimate!=null) bits.push("系统估"+fmtWan(input.systemEstimate));
      if(!bits.length) return "";
      return `<div class="history-intel muted">当时情报：${escapeHtml(bits.join(" · "))}</div>`;
    }
    function shadowWholeFromPrediction(prediction){
      // 保存快照挂在 prediction.probabilityProfile；strict replay 行则直接挂在
      // row.probabilityProfile。两者都只读取当时的 Shadow，不现场重算。
      const shadow=prediction?.probabilityProfile?.shadowWhole||prediction?.shadowWhole;
      if(!shadow)return null;
      const values={p20:Number(shadow.p20),p50:Number(shadow.p50),p80:Number(shadow.p80)};
      return [values.p20,values.p50,values.p80].every(Number.isFinite)?values:null;
    }
    function savedPredictionWithShadow(r){
      const savedCandidates=[];
      if(r?.prediction)savedCandidates.push(r.prediction);
      if(Array.isArray(r?.rounds))r.rounds.slice().sort((a,b)=>Number(b.round||0)-Number(a.round||0)).forEach(x=>{if(x?.prediction)savedCandidates.push(x.prediction);});
      return savedCandidates.find(p=>shadowWholeFromPrediction(p))||null;
    }
    function savedShadowForHistory(r){
      const saved=savedPredictionWithShadow(r);
      const savedShadow=shadowWholeFromPrediction(saved);
      return savedShadow?{...savedShadow,source:"保存时快照"}:null;
    }
    function comparisonShadowForHistory(r,replay=null){
      const saved=savedShadowForHistory(r);
      if(saved)return saved;
      const replayShadow=shadowWholeFromPrediction(replay);
      return replayShadow?{ ...replayShadow,source:"strict walk-forward" }:null;
    }
    function signedModelError(actual,prediction){
      if(!hasNumber(actual)||!hasNumber(prediction))return null;
      const delta=Number(actual)-Number(prediction),relative=Number(actual)!==0?delta/Number(actual):null;
      return {delta,relative,label:delta>=0?"少估":"多估"};
    }
    function shadowComparisonHtml(actual,shadow,compact=false){
      if(!shadow)return compact?`<span class="ab-shadow">Shadow 未保存</span>`:`<div class="history-shadow-note"><strong>Probability Shadow</strong>：未保存 Shadow</div>`;
      const err=signedModelError(actual,shadow.p50),errorText=err?`${err.label} ${fmtWan(Math.abs(err.delta))} · ${err.relative==null?"—":`${Math.abs(err.relative*100).toFixed(1)}%`}`:"—";
      if(compact)return `<span class="ab-shadow" title="Shadow P20 ${fmtWan(shadow.p20)} · P50 ${fmtWan(shadow.p50)} · P80 ${fmtWan(shadow.p80)} · P50→实际 ${fmtWan(actual)} · ${errorText}">Shadow P20 ${fmtWan(shadow.p20)} · P50 ${fmtWan(shadow.p50)} · P80 ${fmtWan(shadow.p80)} · ${errorText}</span>`;
      const detailError=err?`${err.label} · 绝对误差 ${fmtWan(Math.abs(err.delta))} · 相对误差 ${err.relative==null?"—":`${Math.abs(err.relative*100).toFixed(1)}%`}`:"无法计算误差";
      return `<div class="history-shadow-note"><strong>Probability Shadow · ${escapeHtml(shadow.source||"历史快照")}</strong><br>P20 / P50 / P80：${fmtWan(shadow.p20)} / ${fmtWan(shadow.p50)} / ${fmtWan(shadow.p80)}<br>Shadow P50 → 实际：${fmtWan(shadow.p50)} → ${fmtWan(actual)} · ${detailError}</div>`;
    }
    function historyRoundDetails(r){
      const rounds=Array.isArray(r?.rounds)?r.rounds.slice().sort((a,b)=>(a.round||0)-(b.round||0)):[];
      if(!rounds.length) return "";
      const text=rounds.map(x=>{
        const est=x.prediction?.estimate ?? x.estimate;
        const cap=x.prediction?.recommendedCap ?? x.cap;
        const shadow=shadowWholeFromPrediction(x.prediction);
        const parts=[`R${x.round||"?"}`];
        if(est!=null) parts.push("v0.3 "+fmtWan(est));
        if(cap!=null) parts.push("保命"+fmtWan(cap));
        const balanced=x.prediction?.balancedCap;
        if(balanced!=null) parts.push("平衡"+fmtWan(balanced));
        if(shadow) parts.push("Shadow P50 "+fmtWan(shadow.p50));
        return parts.join(" ");
      }).join(" · ");
      return `<div class="history-intel">回合：${escapeHtml(text)}</div>`;
    }
    function askDelete(id){
      openConfirm("删除这条历史？","删除后可从导出备份再导入。",()=>{
        state.records=state.records.filter(x=>x.id!==id);
        saveState(); renderReview(); toast("已删除");
      });
    }

    function editRecord(id){const r=state.records.find(x=>x.id===id);if(!r)return;setVal("recordId",r.id);setVal("recordPlayedAt",r.playedAt||(r.date?`${r.date}T12:00`:nowLocalInput()));setVal("recordRole",r.role);setVal("recordCharacter",r.character||"达芙蒂尔");setVal("recordVenue",r.venue);fillBoxOptions("recordVenue","recordBox",r.box);setVal("recordFieldCondition",r.fieldCondition||"unknown");setVal("recordAvgValueBasis",r.avgValueBasis||"unknown");setVal("recordPrivateBidCap",r.privateBidCap??r.settlement?.privateBidCap);setVal("recordBidActionCount",r.bidActionCount??r.settlement?.bidActionCount);setVal("recordQ",r.q);setVal("recordGoldAvg",r.goldAvg);setVal("recordGoldCount",r.settlement?.realizedState?.gold??r.settlement?.goldCount??r.goldCount);setVal("recordPurple",r.settlement?.realizedState?.purple??r.settlement?.purpleCount??r.purpleCount);setVal("recordPurpleAvg",r.purpleAvg);setVal("recordGoldTotal",r.goldTotal);setVal("recordMinPurple",r.minPurple??0);setVal("recordMinGold",r.minGold??0);setVal("recordMinRed",r.minRed??0);setVal("recordMinRedQuick",r.minRed??0);setVal("recordMinBlue",r.minBlue??0);setVal("recordMinGreen",r.minGreen??0);setVal("recordMinWhite",r.minWhite??0);setVal("recordKnownPurple",r.knownPurple);setVal("recordKnownGold",r.knownGold);setVal("recordKnownRed",r.knownRed);setVal("recordActual",r.actualTotal);setVal("recordBid",r.highestPersonalBid??r.bid);setVal("recordClearingPrice",r.clearingPrice??r.settlement?.clearingPrice);setVal("recordPurchaseSpend",r.purchaseSpend??r.settlement?.purchaseSpend);setVal("recordAcquired",r.acquired===true?"true":r.acquired===false?"false":"");setVal("recordResultReason",r.resultReason||r.noBidReason||"");const legacyCostOnly=r.costs?.entry==null&&r.costs?.info==null&&r.costs?.other==null&&recordTotalCost(r)>0;setVal("recordEntryCost",r.costs?.entry);setVal("recordInfoCost",r.costs?.info);setVal("recordOtherCost",legacyCostOnly?recordTotalCost(r):r.costs?.other);syncCostInputs("record");setVal("recordWelfareBase",r.welfare?.base);setVal("recordWelfareRate",r.welfare?.rate);setVal("recordWelfareReceived",r.welfare?.received);syncWelfareInputs("record");setVal("recordTransformedOneByOneCount",r.sparkle?.transformedOneByOneCount);setVal("recordVerifiedGemItems",r.sparkle?.verifiedGemItems);document.getElementById("recordGemInventoryComplete").checked=r.sparkle?.complete===true;setVal("recordWinner",r.winner||r.settlement?.winner||"");setVal("recordOutcome",r.outcome);setVal("recordRedCount",r.settlement?.realizedState?.red??r.settlement?.redCount);setVal("recordRedItems",verifiedRedItemsText(r));document.getElementById("recordRedInventoryComplete").checked=r.redInventoryComplete===true;setVal("recordTruthSource",r.settlement?.truthSource||r.settlement?.realizedState?.source||"manual-settlement");setVal("recordTruthConfidence",r.settlement?.truthConfidence||r.settlement?.realizedState?.confidence||"unknown");setVal("recordTotalItems",r.totalItems);setVal("recordTotalGrid",r.totalGrid);setVal("recordGoldGrid",r.goldGrid);setVal("recordPurpleGrid",r.purpleGrid);setVal("recordBlueCount",r.blueCount);setVal("recordBlueGrid",r.blueGrid);setVal("recordBlueAvg",r.blueAvg);setVal("recordGreenCount",r.greenCount);setVal("recordGreenGrid",r.greenGrid);setVal("recordGreenAvg",r.greenAvg);setVal("recordWhiteCount",r.whiteCount);setVal("recordWhiteGrid",r.whiteGrid);setVal("recordWhiteAvg",r.whiteAvg);setVal("recordSystemEstimate",r.systemEstimate);setVal("recordSingleAvg",r.singleAvg);setVal("recordNineAvg",r.nineAvg);setVal("recordPublicNote",r.publicNote);setVal("recordNotes",r.notes||r.settlement?.note||"");document.getElementById("recordForm").dataset.prediction=r.prediction?JSON.stringify(r.prediction):"";document.getElementById("recordFormTitle").textContent="编辑样本";document.getElementById("recordModeBadge").textContent=r.legacy?"旧版样本":"编辑中";document.getElementById("cancelEditBtn").classList.remove("hidden");showPage("capture");updateQuality();}

    let reviewRenderToken=0,reviewHeavyTimer=null,reviewHeavyIdle=null;
    function scheduleReviewHeavyRender(){
      const token=++reviewRenderToken;
      if(reviewHeavyTimer){clearTimeout(reviewHeavyTimer);reviewHeavyTimer=null;}
      if(reviewHeavyIdle!==null&&typeof window.cancelIdleCallback==="function"){window.cancelIdleCallback(reviewHeavyIdle);reviewHeavyIdle=null;}
      const run=()=>{
        reviewHeavyIdle=null;
        if(token!==reviewRenderToken||!document.getElementById("page-review")?.classList.contains("active"))return;
        try{renderStats();renderShadowAbPanel();}catch(error){console.error(error);}
        requestAnimationFrame(()=>{
          if(token!==reviewRenderToken||!document.getElementById("page-review")?.classList.contains("active"))return;
          try{renderModelPanel();drawReviewScatters();}catch(error){console.error(error);}
        });
        reviewHeavyTimer=setTimeout(()=>{
          reviewHeavyTimer=null;
          if(token!==reviewRenderToken||!document.getElementById("page-review")?.classList.contains("active"))return;
          try{renderHistoryDashboard();renderHistory();}catch(error){console.error(error);}
        },0);
      };
      if(typeof window.requestIdleCallback==="function")reviewHeavyIdle=window.requestIdleCallback(run,{timeout:600});
      else reviewHeavyTimer=setTimeout(run,0);
    }
    function renderReview(){
      // Keep the first paint cheap: strict replay, charts, model cards and dashboard
      // can all wait for idle time without changing the saved data or the decision.
      try{ populateFilters(); }catch(e){ console.error(e); }
      try{ renderLegacyAudit(); }catch(e){ console.error(e); }
      try{ renderV04ValidationPanel(); }catch(e){ console.error(e); }
      try{ renderHistory({skipAudit:true}); }catch(e){ console.error(e); }
      scheduleReviewHeavyRender();
      const token=reviewRenderToken;
      requestAnimationFrame(()=>{ if(token!==reviewRenderToken)return; try{ drawChart(); }catch(e){ console.error(e); } });
    }
    function renderLegacyAudit(){
      const el=document.getElementById("legacyAudit"); if(!el) return;
      const legacy=state.records.filter(r=>r.legacy), n=state.records.length, settled=state.records.filter(r=>r.actualTotal>0).length;
      const timed=state.records.filter(r=>Number(r.actualTotal)>0&&historyTimestamp(r.playedAt)!==null).length;
      el.innerHTML='<div class="callout"><span class="dot"></span><div><strong>样本库：</strong>共 '+n+' 条，已结算 '+settled+'，其中旧版补录 '+legacy.length+'。总价分布使用全部结算记录；严格预测回测只使用有日期且当局之前可见的 '+timed+' 条，结算后信息不会倒灌。</div></div>';
    }
    
    function filteredRecords(){const p=val("historyPatchFilter"),v=val("historyVenueFilter"),c=val("historyConditionFilter"),b=val("historyBoxFilter"),s=val("historySearch").toLowerCase();return state.records.filter(r=>(p==="all"||(r.periodKey||periodOf(r.playedAt)||r.patch)===p)&&(v==="all"||r.venue===v)&&(c==="all"||r.fieldCondition===c)&&(b==="all"||r.box===b)&&(!s||`${r.notes} ${redItemsText(r)} ${r.box} ${r.character} ${FIELD_CONDITION_LABELS[r.fieldCondition]||""}`.toLowerCase().includes(s)));}
    function populateFilters(){const fill=(id,values,label,display=x=>x)=>{const el=document.getElementById(id),current=el.value;el.innerHTML=`<option value="all">全部${label}</option>`+[...new Set(values.filter(Boolean))].sort().map(x=>`<option value="${escapeHtml(x)}">${escapeHtml(display(x))}</option>`).join("");if([...el.options].some(o=>o.value===current))el.value=current;};fill("historyPatchFilter",state.records.map(r=>r.periodKey||periodOf(r.playedAt)||r.patch),"月份");fill("historyVenueFilter",state.records.map(r=>r.venue),"场地");fill("historyConditionFilter",state.records.map(r=>r.fieldCondition),"条件",x=>FIELD_CONDITION_LABELS[x]||x);fill("historyBoxFilter",state.records.map(r=>r.box),"箱型");}
    ["historyPatchFilter","historyVenueFilter","historyConditionFilter","historyBoxFilter"].forEach(id=>{const el=document.getElementById(id); if(el) el.addEventListener("change",()=>{historyVisibleCount=15;renderReview();});});
    const _historySearch=document.getElementById("historySearch");if(_historySearch)_historySearch.addEventListener("input",debounce(()=>{historyVisibleCount=15;renderHistory({skipAudit:true});scheduleReviewHeavyRender();},140));
    function recordTotalCost(r){return normalizeCostBreakdown(r,r?.settlement).total;}
    function recordAcquisitionMargin(r){const acquired=explicitBoolean(r?.acquired??r?.settlement?.acquired),actual=nonNegativeOrNull(r?.actualTotal??r?.settlement?.actualTotal),spend=nonNegativeOrNull(r?.purchaseSpend??r?.settlement?.purchaseSpend);return acquired===true&&actual!==null&&spend!==null?actual-spend:null;}
    function recordSessionCashflow(r){const margin=recordAcquisitionMargin(r),cost=recordTotalCost(r),welfareReceived=nonNegativeOrNull(r?.welfare?.received??r?.settlement?.welfare?.received)??0;return (margin??0)-cost+welfareReceived;}
    function recordProfit(r){return recordAcquisitionMargin(r);}
    window.runV04DataModelSelfTest=function(){
      const partial=normalizeRecord({id:"test-partial",q:5,knownRed:"300000",redItems:"300000",redCount:1,cost:55000}),complete=normalizeRecord({id:"test-complete",q:5,knownRed:"300000",redItems:"300000",redCount:1,redInventoryComplete:true,settlementVerifiedRedItems:"300000",costs:{entry:5000,info:50000,other:0},acquired:true,purchaseSpend:200000,actualTotal:300000,settlement:{redInventoryComplete:true,verifiedRedItems:"300000",redCount:1,realizedState:{gold:2,purple:2,red:1,complete:true,source:"test",confidence:"high"}}}),migratedShape=normalizeRecord({id:"test-migrated",q:5,redCount:1,redInventoryComplete:true,settlementVerifiedRedItems:[300000],actualTotal:300000,cost:55000,settlement:{status:"verified"}}),mergedWithStaleLocal=mergeSavedShadowIntoRecord(migratedShape,{id:"test-migrated",q:5,redCount:1,redItems:"300000",cost:0}),externalTruth=normalizeRecord({id:"test-external",q:5,actualTotal:123456,goldCount:2,purpleCount:2,redCount:1,screenshots:[{path:"same.png",thumbnailDataUrl:"data:image/png;base64,ok"}],settlement:{actualTotal:123456,goldCount:2,purpleCount:2,redCount:1}}),truthMerge=mergeSavedShadowIntoRecord(externalTruth,{id:"test-external",q:5,screenshots:[{path:"same.png"}]}),cacheStripsHeavy=!Object.hasOwn(stripProbabilityForCache({estimate:1,probabilityProfile:{p50:1}}),"probabilityProfile")&&!Object.hasOwn(stripInlineImageForCache({path:"x",thumbnailDataUrl:"data:image/png;base64,x"}),"thumbnailDataUrl"),externalTruthSurvives=truthMerge.actualTotal===123456&&truthMerge.settlement.actualTotal===123456&&truthMerge.goldCount===2&&truthMerge.screenshots?.[0]?.thumbnailDataUrl==="data:image/png;base64,ok",pass=historicalRedLabel(partial)===null&&historicalRedLabel(complete)?.total===300000&&historicalRedLabel(migratedShape)?.total===300000&&migratedShape.settlement.realizedState===null&&historicalRedLabel(mergedWithStaleLocal)?.total===300000&&recordTotalCost(mergedWithStaleLocal)===55000&&externalTruthSurvives&&cacheStripsHeavy&&recordAcquisitionMargin(complete)===100000&&recordSessionCashflow(complete)===45000&&normalizeRecord({id:"legacy",actualTotal:300000,bid:200000,cost:55000}).acquired===null&&recordAcquisitionMargin(normalizeRecord({id:"legacy2",actualTotal:300000,bid:200000,cost:55000}))===null;
      return {pass,checks:{partialDecisionRedRejected:historicalRedLabel(partial)===null,completeRedAccepted:historicalRedLabel(complete)?.total===300000,migratedRedAcceptedWithoutStateInference:historicalRedLabel(migratedShape)?.total===300000&&migratedShape.settlement.realizedState===null,staleLocalCannotEraseMigratedTruthAndCost:historicalRedLabel(mergedWithStaleLocal)?.total===300000&&recordTotalCost(mergedWithStaleLocal)===55000,externalTruthAndEvidenceSurviveBlankLocal:externalTruthSurvives,cacheStripsHeavy,acquisitionMargin:recordAcquisitionMargin(complete),sessionCashflow:recordSessionCashflow(complete),legacyAcquiredUnknown:normalizeRecord({id:"legacy",actualTotal:300000,bid:200000,cost:55000}).acquired===null}};
    };
    function actualInRange(actual,low,high){return Number.isFinite(Number(actual))&&Number.isFinite(Number(low))&&Number.isFinite(Number(high))&&Number(actual)>=Number(low)&&Number(actual)<=Number(high);}
    function shadowAbRows(records,replayById=new Map()){
      return (records||[]).map(r=>{
        const replay=replayById.get(r.id)||null,p=savedPredictionForHistory(r),savedShadowPrediction=savedPredictionWithShadow(r),shadow=comparisonShadowForHistory(r,replay),formalPrediction=savedShadowPrediction||replay||p,formal=hasNumber(formalPrediction?.estimate)?Number(formalPrediction.estimate):null,actual=Number(r.actualTotal);
        if(!shadow||!Number.isFinite(actual)||actual<=0||!Number.isFinite(formal))return null;
        return {r,actual,formal,shadow,formalErr:Math.abs(formal-actual)/actual,shadowErr:Math.abs(shadow.p50-actual)/actual,formalAbs:Math.abs(formal-actual),shadowAbs:Math.abs(shadow.p50-actual)};
      }).filter(Boolean);
    }
    function renderShadowAbPanel(){
      const el=document.querySelector("#shadowAbPanel .panel-body");if(!el)return;
      const audit=runDynamicWalkForwardAudit(),replayById=new Map((audit?.rows||[]).map(x=>[x.id,x])),rows=shadowAbRows(filteredRecords(),replayById);
      if(!rows.length){el.innerHTML='<div class="empty-list">暂无同时保存 v0.3 与 Probability Shadow 的已结算样本；旧记录不会事后补算 Shadow。</div>';return;}
      const medianFormalApe=median(rows.map(x=>x.formalErr)),medianShadowApe=median(rows.map(x=>x.shadowErr)),formalMae=mean(rows.map(x=>x.formalAbs)),shadowMae=mean(rows.map(x=>x.shadowAbs)),coverage=rows.filter(x=>actualInRange(x.actual,x.shadow.p20,x.shadow.p80)).length/rows.length,formalWins=rows.filter(x=>x.formalErr<x.shadowErr).length,shadowWins=rows.filter(x=>x.shadowErr<x.formalErr).length,savedN=rows.filter(x=>x.shadow.source==="保存时快照").length,replayN=rows.length-savedN;
      const f=v=>v==null?"—":`${(v*100).toFixed(1)}%`,cell=(label,value,note,cls="")=>`<div class="shadow-ab-cell ${cls}"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`;
      el.innerHTML=`<div class="shadow-ab-grid">${cell("v0.3 median APE",f(medianFormalApe),`${rows.length} 局可比较样本`)}${cell("Shadow P50 median APE",f(medianShadowApe),"只用保存/严格回放 P50","shadow")}${cell("v0.3 MAE",fmtWan(formalMae),"绝对误差")}${cell("Shadow P50 MAE",fmtWan(shadowMae),"绝对误差","shadow")}${cell("Shadow P20–P80 coverage",f(coverage),`${rows.filter(x=>actualInRange(x.actual,x.shadow.p20,x.shadow.p80)).length}/${rows.length} 局`,`shadow`)}${cell("各自胜出",`v0.3 ${formalWins} · Shadow ${shadowWins}`,"按相对误差逐局比较")}</div><p class="shadow-ab-note">Shadow P20–P80 覆盖只在完整 Shadow 样本中统计；本次分母 ${rows.length} 局，其中保存时快照 ${savedN} 局、严格时序回放 ${replayN} 局。没有保存 Shadow 且无法严格回放的记录不进入 A/B，也不会使用未来历史补算。</p>`;
    }
    function renderStats(){
      const el=document.getElementById("statsStrip"); if(!el) return;
      const ids=new Set(filteredRecords().map(r=>r.id)),rows=runDynamicWalkForwardAudit().rows.filter(x=>ids.has(x.id)),s=auditStats(rows),captures=rows.map(x=>Number(x.cap)/Number(x.actual)).filter(Number.isFinite),p25=quantile(captures,.25),p50=quantile(captures,.5),p75=quantile(captures,.75);
      el.innerHTML=`<div class="stat-pill"><span>严格时序样本</span><strong>${s.n}</strong><small>只读取该局之前的历史</small></div>
        <div class="stat-pill"><span>中位误差</span><strong>${s.n?(s.medianApe*100).toFixed(1)+'%':'—'}</strong><small>${s.n?`平均 ${(s.meanApe*100).toFixed(1)}%`:'当前筛选无样本'}</small></div>
        <div class="stat-pill"><span>Bad Buy（静态）</span><strong class="${s.safeBreach?'profit-negative':'profit-positive'}">${s.safeBreach}/${s.n}</strong><small>策略上限覆盖成交价但买下亏损</small></div>
        <div class="stat-pill"><span>防亏线 capture</span><strong>${captures.length?(p50*100).toFixed(0)+'%':'—'}</strong><small>${captures.length?`P25 ${(p25*100).toFixed(0)}% · P75 ${(p75*100).toFixed(0)}%`:'防亏线 / 实际价值'}</small></div>`;
    }
    function realizedStateTruth(r){
      const raw=r?.settlement?.realizedState||r?.realizedState;if(!raw||raw.complete!==true)return null;
      const g=integerOrNull(raw.gold??raw.g),p=integerOrNull(raw.purple??raw.p),red=integerOrNull(raw.red??raw.r),q=integerOrNull(r?.q);
      return [g,p,red].every(x=>x!==null)&&(q===null||g+p+red===q)?{g,p,r:red,source:raw.source||"unknown",confidence:raw.confidence||"unknown"}:null;
    }
    function savedCandidateStates(r){
      const prediction=savedPredictionForHistory(r),profile=prediction?.probabilityProfile||{},raw=Array.isArray(profile.stateCandidates)?profile.stateCandidates:[];
      const rows=raw.map(x=>({g:integerOrNull(x.g),p:integerOrNull(x.p),r:integerOrNull(x.r??(x.rMin===x.rMax?x.rMin:null)),weight:Number(x.relativeWeight),shadow:x.shadow||null})).filter(x=>[x.g,x.p,x.r].every(v=>v!==null));
      if(rows.length)return rows;
      const round=(r?.rounds||[]).slice().sort((a,b)=>Number(b.round||0)-Number(a.round||0)).find(x=>Array.isArray(x?.prediction?.probabilityProfile?.stateCandidates));
      return (round?.prediction?.probabilityProfile?.stateCandidates||[]).map(x=>({g:integerOrNull(x.g),p:integerOrNull(x.p),r:integerOrNull(x.r??(x.rMin===x.rMax?x.rMin:null)),weight:Number(x.relativeWeight),shadow:x.shadow||null})).filter(x=>[x.g,x.p,x.r].every(v=>v!==null));
    }
    function renderV04ValidationPanel(){
      const body=document.querySelector("#v04ValidationPanel .panel-body");if(!body)return;
       const records=filteredRecords(),allSettled=records.filter(r=>Number(r.actualTotal)>0),qualityExcluded=allSettled.filter(r=>!solverStatusEligibleForTraining(solverStatusForRecord(r,null))),settled=allSettled.filter(r=>solverStatusEligibleForTraining(solverStatusForRecord(r,null))),truthRows=settled.map(r=>({r,truth:realizedStateTruth(r),states:savedCandidateStates(r)})).filter(x=>x.truth),candidateRows=truthRows.filter(x=>x.states.length),recalled=candidateRows.filter(x=>x.states.some(s=>s.g===x.truth.g&&s.p===x.truth.p&&s.r===x.truth.r)),top1=candidateRows.filter(x=>{const top=x.states.slice().sort((a,b)=>(Number(b.weight)||0)-(Number(a.weight)||0))[0];return top&&top.g===x.truth.g&&top.p===x.truth.p&&top.r===x.truth.r;});
      const realizedShadow=candidateRows.map(x=>{const hit=x.states.find(s=>s.g===x.truth.g&&s.p===x.truth.p&&s.r===x.truth.r),actual=Number(x.r.actualTotal),shadow=hit?.shadow;return shadow&&Number.isFinite(Number(shadow.p50))?{actual,shadow,ape:Math.abs(Number(shadow.p50)-actual)/actual}:null;}).filter(Boolean),stateShadowCoverage=realizedShadow.length?realizedShadow.filter(x=>actualInRange(x.actual,x.shadow.p20,x.shadow.p80)).length/realizedShadow.length:null,stateShadowApe=median(realizedShadow.map(x=>x.ape));
       const discipline=settled.map(r=>{const p=savedPredictionForHistory(r),bid=nonNegativeOrNull(r.highestPersonalBid??r.bid),line=nonNegativeOrNull(p?.recommendedMaxBid??p?.balancedCap);if(bid===null||line===null||line<=0)return null;const margin=recordAcquisitionMargin(r);return {ratio:bid/line,margin};}).filter(Boolean),counterfactuals=settled.map(staticCounterfactualForRecord).filter(x=>x.status==="known"),bands=[{label:"≤0.8×旧平衡线",lo:0,hi:.8},{label:"0.8–1.0×",lo:.8,hi:1},{label:"1.0–1.2×",lo:1,hi:1.2},{label:">1.2×",lo:1.2,hi:Infinity}].map(b=>{const rows=discipline.filter(x=>x.ratio>b.lo-(b.lo===0?0:1e-9)&&x.ratio<=b.hi),known=rows.filter(x=>x.margin!==null);return {...b,n:rows.length,known:known.length,avg:known.length?mean(known.map(x=>x.margin)):null,lossRate:known.length?known.filter(x=>x.margin<0).length/known.length:null};});
      const completeRed=settled.filter(r=>historicalRedLabel(r)).length,reasonKnown=records.filter(r=>String(r.resultReason||r.noBidReason||"").trim()).length,costKnown=records.filter(r=>r.costs?.complete===true).length,acquiredKnown=records.filter(r=>explicitBoolean(r.acquired??r.settlement?.acquired)!==null).length,totalCosts=records.reduce((s,r)=>s+recordTotalCost(r),0),sessionCash=records.reduce((s,r)=>s+recordSessionCashflow(r),0),knownAcquisition=records.map(recordAcquisitionMargin).filter(x=>x!==null),acqTotal=knownAcquisition.reduce((s,x)=>s+x,0),fmtPct=x=>x===null?"—":`${(x*100).toFixed(1)}%`,cell=(label,value,note,cls="")=>`<div class="shadow-ab-cell ${cls}"><span>${escapeHtml(label)}</span><strong>${value}</strong><small>${escapeHtml(note)}</small></div>`;
       const bandRows=bands.map(x=>`<div class="prob-calibration-row"><span>${escapeHtml(x.label)}</span><b>${x.n} 条出价 · ${x.known} 条胜负/支付可核</b><span>${x.avg===null?"真实 ROI 未知":`平均购入价差 ${formatSignedWan(x.avg)} · 亏损率 ${fmtPct(x.lossRate)}`}</span></div>`).join(""),missed=counterfactuals.filter(x=>x.missedOpportunity),badBuy=counterfactuals.filter(x=>x.badBuy),regret=counterfactuals.reduce((s,x)=>s+(x.decisionRegret||0),0),counterfactualHtml=`<div class="prob-calibration-summary v06-counterfactual"><div><span>静态反事实样本</span><strong>${counterfactuals.length}/${settled.length}</strong><small>需要冻结上限、成交价、实际总价</small></div><div><span>Missed Opportunity</span><strong>${missed.length}</strong><small>上限低于成交价但买下能盈利</small></div><div><span>Bad Buy</span><strong>${badBuy.length}</strong><small>上限覆盖成交价但买下亏损</small></div><div><span>Decision Regret</span><strong>${formatSignedWan(-regret)}</strong><small>只按静态“买/不买”反事实</small></div></div>`;
       body.innerHTML=`<div class="shadow-ab-grid">${cell("realized State 真值",String(truthRows.length),`${settled.length} 条可训练结算；${qualityExcluded.length} 条因 solverStatus 排除`)}${cell("候选集合召回",candidateRows.length?`${recalled.length}/${candidateRows.length}`:"—","真实 State 是否在当时候选内","shadow")}${cell("Top1 heuristic 命中",candidateRows.length?`${top1.length}/${candidateRows.length}`:"—","旧权重排序，不是已校准概率","shadow")}${cell("选对 State 后 median APE",stateShadowApe===null?"—":fmtPct(stateShadowApe),`${realizedShadow.length} 条可比`)}${cell("选对 State 后 P20–P80",stateShadowCoverage===null?"—":fmtPct(stateShadowCoverage),"用于拆分权重误差与 State 内估值误差")}${cell("完整红标签",`${completeRed}/${settled.length}`,"仅 explicit complete 清单")}</div>${counterfactualHtml}<div class="prob-calibration-summary" style="margin-top:10px"><div><span>全场现金流</span><strong class="${sessionCash>=0?"profit-positive":"profit-negative"}">${formatSignedWan(sessionCash)}</strong><small>只使用已记录成本 ${fmtWan(totalCosts)}；不把旧 bid 当支付</small></div><div><span>已确认购入价差</span><strong class="${acqTotal>=0?"profit-positive":"profit-negative"}">${formatSignedWan(acqTotal)}</strong><small>${knownAcquisition.length} 局胜负、支付、实际价值齐全</small></div><div><span>胜负 / 结果原因</span><strong>${acquiredKnown}/${records.length} · ${reasonKnown}/${records.length}</strong><small>未知不叫“观望”</small></div><div><span>完整成本分项</span><strong>${costKnown}/${records.length}</strong><small>旧 0 成本不自动视为可信 0</small></div></div><h3 class="prob-calibration-subhead">出价纪律分档</h3><div class="prob-calibration-groups">${bandRows||'<div class="empty-list">没有同时保存旧平衡线和本人出价的样本</div>'}</div><div class="field-help">静态反事实规则：上限低于成交价视为未买到，利润为 −成本；上限覆盖成交价才用“实际总价 − 成交价 − 成本”。这不是保证真实执行结果，不能再用 actual − recommendedCap − cost 冒充策略胜率。分档先展示样本量；只有 acquired、purchaseSpend 和 actualTotal 都明确的局才计算购入价差与亏损率。</div>`;
    }
    
    function drawChart(){const canvas=document.getElementById("historyChart"); if(!canvas) return; const rect=canvas.getBoundingClientRect(); if(rect.width<10||rect.height<10){ requestAnimationFrame(()=>{const r=canvas.getBoundingClientRect(); if(r.width<10) return; drawChart(); }); return; } const dpr=devicePixelRatio||1; canvas.width=rect.width*dpr; canvas.height=rect.height*dpr;const ctx=canvas.getContext("2d");ctx.scale(dpr,dpr);const records=filteredRecords().filter(r=>r.actualTotal>0).slice().reverse();ctx.clearRect(0,0,rect.width,rect.height);if(records.length<2){ctx.fillStyle="#8da8a5";ctx.font="12px sans-serif";ctx.fillText("至少需要 2 条结算记录",20,30);return;}const pad={l:42,r:16,t:18,b:28},w=rect.width-pad.l-pad.r,h=rect.height-pad.t-pad.b,max=Math.max(...records.map(r=>r.actualTotal))*1.08,min=0;ctx.strokeStyle="rgba(191,222,217,.10)";ctx.lineWidth=1;for(let i=0;i<4;i++){const y=pad.t+h*i/3;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(pad.l+w,y);ctx.stroke();ctx.fillStyle="#607a78";ctx.font="10px monospace";ctx.fillText(fmtWan(max*(1-i/3)),2,y+3);}const points=records.map((r,i)=>({x:pad.l+w*i/(records.length-1),y:pad.t+h-(r.actualTotal-min)/(max-min)*h,r}));ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.strokeStyle="#6fe2c1";ctx.lineWidth=2;ctx.stroke();points.forEach(p=>{ctx.beginPath();ctx.arc(p.x,p.y,3.5,0,Math.PI*2);ctx.fillStyle=p.r.legacy?"#607a78":"#ff7165";ctx.fill();});ctx.fillStyle="#607a78";ctx.font="10px sans-serif";ctx.fillText("旧版灰 · 当前红",pad.l,rect.height-6);}
    function drawReviewScatter(canvasId,rows,valueKey,kind){
      const canvas=document.getElementById(canvasId);if(!canvas)return;const rect=canvas.getBoundingClientRect();if(rect.width<10||rect.height<10)return;const dpr=devicePixelRatio||1;canvas.width=rect.width*dpr;canvas.height=rect.height*dpr;const c=canvas.getContext("2d");c.scale(dpr,dpr);c.clearRect(0,0,rect.width,rect.height);const pts=rows.filter(x=>hasNumber(x.actual)&&hasNumber(x[valueKey])&&x.actual>0);if(!pts.length){c.fillStyle="#64748b";c.font="12px sans-serif";c.fillText("当前筛选没有可比较样本",18,28);return;}const pad={l:48,r:18,t:16,b:34},w=rect.width-pad.l-pad.r,h=rect.height-pad.t-pad.b,max=Math.max(...pts.flatMap(x=>[Number(x.actual),Number(x[valueKey])]))*1.06||1,xy=v=>({x:pad.l+Number(v)/max*w,y:pad.t+h-Number(v)/max*h});c.strokeStyle="#e2e8f0";c.lineWidth=1;for(let i=0;i<=4;i++){const v=max*i/4,p=xy(v);c.beginPath();c.moveTo(p.x,pad.t);c.lineTo(p.x,pad.t+h);c.stroke();c.beginPath();c.moveTo(pad.l,p.y);c.lineTo(pad.l+w,p.y);c.stroke();c.fillStyle="#64748b";c.font="9px monospace";c.fillText(fmtWan(v),Math.max(0,p.x-16),rect.height-12);if(i)c.fillText(fmtWan(v),2,p.y+3);}c.setLineDash([5,4]);c.strokeStyle="#94a3b8";c.beginPath();c.moveTo(pad.l,pad.t+h);c.lineTo(pad.l+w,pad.t);c.stroke();c.setLineDash([]);pts.forEach(x=>{const p=xy(x.actual),y=xy(x[valueKey]).y,bad=kind==="cap"?Number(x[valueKey])>Number(x.actual):Math.abs(Number(x[valueKey])-Number(x.actual))/Number(x.actual)>.4;c.beginPath();c.arc(p.x,y,4,0,Math.PI*2);c.fillStyle=bad?"#ef4444":kind==="cap"?"#2563eb":"#0d9488";c.globalAlpha=.78;c.fill();c.globalAlpha=1;});c.fillStyle="#64748b";c.font="10px sans-serif";c.fillText("实际价值 →",Math.max(pad.l,rect.width-78),rect.height-3);c.save();c.translate(10,pad.t+70);c.rotate(-Math.PI/2);c.fillText(kind==="cap"?"保命线":"预测值",0,0);c.restore();
    }
    function drawReviewScatters(){const ids=new Set(filteredRecords().map(r=>r.id)),rows=runDynamicWalkForwardAudit().rows.filter(x=>ids.has(x.id));drawReviewScatter("predictionScatter",rows,"estimate","estimate");drawReviewScatter("capScatter",rows,"cap","cap");}
    window.addEventListener("resize",()=>{if(document.getElementById("page-review").classList.contains("active")){drawChart();drawReviewScatters();}});
    
    function fmtWanNum(v){ if(v==null||!Number.isFinite(v)) return '—'; return (v/10000).toFixed(v>=1000000?1:2)+'W'; }
    function historicalErrorExplanation(r,estimate){
      if(!hasNumber(estimate)||!hasNumber(r.actualTotal))return "没有保存可比较的当时估值";
      const input=predictionInputRecord(r),error=Number(r.actualTotal)-Number(estimate),finalR=hasNumber(r.redCount)&&Number.isInteger(Number(r.redCount))?Number(r.redCount):null,visibleR=hasNumber(input.redCount)&&Number.isInteger(Number(input.redCount))?Number(input.redCount):null;
      if(error>0){
        if(visibleR===null&&finalR!==null&&finalR>=2)return `推演时红数未知，结算确认 ${finalR} 红；这是当前情报无法分辨的多红尾部`;
        if(String(input.knownGold||"").includes("/"))return "二选一只锁定一件高价金的下限，不能证明剩余金件数或红货；前序同箱薄局会把工作中心拉低";
        if(!hasNumber(input.goldCount)&&hasNumber(input.goldAvg))return "金均价已知但金件数未知；低 G 工作假设低估了实际金池/剩余红池";
        if(!hasNumber(input.goldAvg)&&!hasNumber(input.goldTotal))return `推演时只有 ${hasNumber(input.q)?"Q/数量":"场地箱型"}，无法识别高价金与红货落点`;
        return "实际高价藏品组合落在历史典型区间上方；保命线不会为这种上尾追价";
      }
      if(String(input.knownGold||"").includes("/"))return "二选一只证明至少一个高价金；旧 v4 把较高 G 组合的中位数抬得过高";
      if(!hasNumber(input.goldCount))return "金件数未锁定，候选金池偏高；新版会用同箱时序近邻限制其权重";
      return "该局实际组合偏薄，低于结构/历史中位；应看保命线而不是中心价下注";
    }
    let historyVisibleCount=15;
    // 复盘列表不能依赖异步 strict replay 才有数字：保存时的 prediction
    // 以及最后一个 round snapshot 都是该局当时真正看到的信息，应作为稳定回退。
    function savedPredictionForHistory(r){
      const candidates=[];
      if(r?.prediction)candidates.push(r.prediction);
      if(Array.isArray(r?.rounds))r.rounds.slice().sort((a,b)=>Number(b.round||0)-Number(a.round||0)).forEach(x=>{if(x?.prediction)candidates.push(x.prediction);});
      return candidates.find(p=>hasNumber(p?.estimate)||hasNumber(p?.recommendedCap)||hasNumber(p?.conservativeLossLine)||hasNumber(p?.balancedCap))||null;
    }
    function infoModeIdForHistory(r,input,prediction=null){
      const explicit=prediction?.infoModeId||prediction?.mode||r?.infoModeId;
      if(explicit)return String(explicit);
      try{
        const mode=detectInfoMode({q:input?.q,avg:input?.goldAvg,goldTotal:input?.goldTotal,purple:input?.purpleCount,purpleAvg:input?.purpleAvg,knownGold:input?.knownGold||"",knownRed:input?.knownRed||""});
        if(mode?.id)return mode.id;
      }catch(_){/* 旧记录字段不完整时继续使用混合情报 */}
      return "mixed";
    }
    function renderHistory(options={}){
      const allRecords=filteredRecords(),records=allRecords.slice(0,historyVisibleCount);
      const _hl=document.getElementById("historyList"); if(!_hl) return;
      const replayRows=options.skipAudit?[]:runDynamicWalkForwardAudit().rows,replayById=new Map(replayRows.map(x=>[x.id,x]));
      const rowsHtml=records.length?records.map(r=>{
        const input=predictionInputRecord(r);
        const savedPrediction=savedPredictionForHistory(r),savedShadowPrediction=savedPredictionWithShadow(r),replay=replayById.get(r.id)||null;
        // 严格回放完成后优先显示回放；回放尚未完成/旧记录无回放行时，
        // 回退到保存时 prediction，避免用户看到一整列“—”。
        // 若同一保存快照同时包含 Shadow 与 v0.3，列表必须使用这对当时快照；
        // 只有没有保存 Shadow 时才回退到 strict walk-forward v0.3。
        const estimate=hasNumber(savedShadowPrediction?.estimate)?Number(savedShadowPrediction.estimate):hasNumber(replay?.estimate)?Number(replay.estimate):hasNumber(savedPrediction?.estimate)?Number(savedPrediction.estimate):null;
        // 历史列表严格显示“当时保存”的 Shadow；旧记录没有保存就不事后补算。
        // strict walk-forward Shadow 只进入独立 A/B 对照面板。
        const shadow=savedShadowForHistory(r);
        const error=hasNumber(estimate)&&hasNumber(r.actualTotal)?Number(r.actualTotal)-estimate:null;
        const replayError=error;
        const cap=hasNumber(replay?.conservativeLossLine)?Number(replay.conservativeLossLine):hasNumber(replay?.cap)?Number(replay.cap):hasNumber(savedPrediction?.conservativeLossLine)?Number(savedPrediction.conservativeLossLine):hasNumber(savedPrediction?.recommendedCap)?Number(savedPrediction.recommendedCap):hasNumber(savedPrediction?.cap)?Number(savedPrediction.cap):null;
        const acquisitionMargin=recordAcquisitionMargin(r),sessionCash=recordSessionCashflow(r);
        const profit=acquisitionMargin;
        const profitText=acquisitionMargin==null?`场次 ${sessionCash>=0?'+':''}${fmtWan(sessionCash)}`:acquisitionMargin>0?`获取毛利 +${fmtWan(acquisitionMargin)}`:acquisitionMargin<0?`获取毛利 −${fmtWan(Math.abs(acquisitionMargin))}`:'获取毛利持平';
        const rounds=Array.isArray(r.rounds)&&r.rounds.length?r.rounds.slice().sort((a,b)=>a.round-b.round).map(x=>`R${x.round}`).join("/"):null;
        const redFeature=input.redCount!=null?["红",input.redCount]:["红至少",input.minRed],features=[["紫",input.purpleCount],["金",input.goldCount],redFeature,["紫均",input.purpleAvg],["金均",input.goldAvg],["金总",input.goldTotal],["总件",input.totalItems],["总格",input.totalGrid],["蓝",input.blueCount],["蓝格",input.blueGrid],["绿",input.greenCount],["绿格",input.greenGrid],["白",input.whiteCount],["白格",input.whiteGrid],["回合",rounds]].filter(x=>x[1]!=null&&x[1]!==""&&x[1]!==0);
      const period=r.periodKey||periodOf(r.playedAt)||r.patch||"日期未知";
        const when=r.playedAt?r.playedAt.replace("T"," "):(r.date||"日期未知");
        const winnerText=r.winner||r.settlement?.winner||"";
        const winnerLabel=winnerText||"未确认";
        const errorText=error===null?'—':error>=0?`少估 ${fmtWan(error)}`:`多估 ${fmtWan(Math.abs(error))}`;
        const replayErrorText=replayError===null?'—':replayError>=0?`少估 ${fmtWan(replayError)}`:`多估 ${fmtWan(Math.abs(replayError))}`;
        const modeLabels={onlyQ:"只有Q",goldAvgOnly:"Q+金均",goldAvgPurple:"Q+紫+金均",goldTotal:"金总",knownGold:"已知金藏品",knownRed:"已知红藏品",dualAvg:"双均价",noQ:"无Q",mixed:"混合情报"},pendingSettlement=r.settlement?.status==="pending"||!hasNumber(r.actualTotal),modeId=infoModeIdForHistory(r,input,savedPrediction),modeText=pendingSettlement?"待识别":modeLabels[replay?.mode||modeId]||replay?.mode||modeId||"混合情报",apeText=hasNumber(estimate)&&hasNumber(r.actualTotal)&&Number(r.actualTotal)>0?`${(Math.abs(Number(r.actualTotal)-estimate)/Number(r.actualTotal)*100).toFixed(1)}%`:"—";
        const featureHtml=features.map(([k,v])=>`<span class="similar-tag">${escapeHtml(k)}=${escapeHtml(String(typeof v==='number'?fmt(v):v))}</span>`).join("");
        const bd=savedPrediction?.componentBreakdown||r.prediction?.componentBreakdown,settledCounts=[["紫",r.purpleCount,input.purpleCount],["金",r.goldCount,input.goldCount],["红",r.redCount,input.redCount]].filter(x=>x[1]!=null&&String(x[1])!==String(x[2])).map(x=>`${x[0]}${x[1]}`);
        const intel=bd?`<div class="history-intel"><strong>当时模型分项：</strong>金 ${fmtWan(bd.gold?.mid)} · 紫 ${fmtWan(bd.purple?.mid)} · 红 ${fmtWan(bd.red?.mid)} · 低品质 ${fmtWan(bd.lowTier?.mid)} · 保守防亏 ${fmtWan(savedPrediction?.conservativeLossLine??savedPrediction?.recommendedCap??cap)}${savedPrediction?.recommendedMaxBid!=null||savedPrediction?.balancedCap!=null?` · 推荐上限 ${fmtWan(savedPrediction?.recommendedMaxBid??savedPrediction?.balancedCap)}`:""}</div>`:(verifiedRedItemsText(r)?`<div class="history-intel red-text">结算确认红货：${escapeHtml(verifiedRedItemsText(r))}</div>`:"");
        const settledFacts=settledCounts.length?`<div class="history-intel muted"><strong>结算后才确认：</strong>${escapeHtml(settledCounts.join(" · "))}</div>`:"";
        const replayFormula=replay&&Number(replay.analogWeight)>0&&hasNumber(replay.preAnalogCenter)&&hasNumber(replay.analogTarget)?`结构 ${fmtWan(replay.preAnalogCenter)} × ${Math.round((1-replay.analogWeight)*100)}% + 前序历史 ${fmtWan(replay.analogTarget)} × ${Math.round(replay.analogWeight*100)}% = ${fmtWan(replay.estimate)}`:replay?`结构/历史工作值 ${fmtWan(replay.estimate)}；前序近邻不足以单独校准中心`:savedPrediction?`保存时工作估值 ${fmtWan(estimate)}；严格回放完成后将以历史无泄漏结果替换`:"";
        const estimateSourceLabel=savedShadowPrediction?.estimate!=null?"保存时预测":replay?"v0.3 严格复放":"保存时预测";
        const why=`<div class="history-explain"><strong>v0.3 严格时序解释：</strong>${escapeHtml(historicalErrorExplanation(r,estimate))}${savedShadowPrediction?`<br><small>当前 v0.3 与 Shadow 均来自同一保存时快照；不使用结算后的未来历史。</small>`:replay?`<br><small>${escapeHtml(replayFormula)}。只读该局之前的历史；不使用本局结算结果或未来对局。</small>`:savedPrediction?`<br><small>${escapeHtml(replayFormula)}。当前显示保存时快照；严格回放仍在生成或该旧记录没有可复放行。</small>`:"<br><small>没有保存可比较的当时估值。</small>"}</div>`;
        const shots=(r.screenshots||[]).slice(0,4),shotHtml=shots.length?`<div class="history-shots">${shots.map((shot,i)=>{const src=shot.thumbnailDataUrl||shot.dataUrl||safeScreenshotSrc(shot.path||shot.name),quality=shot.storageKey&&shot.originalStorage!=="metadata-only"?"原图可用":"缩略图/路径";return `<a class="history-shot" href="${src}" onclick="openHistoryEvidence('${escapeHtml(r.id)}',${i});return false"><img src="${src}" alt="结算截图 ${i+1}" loading="lazy"><span><strong>截图 ${i+1} · ${quality}</strong><br>${escapeHtml(shot.name||shot.path)}${shot.ocrConfidence!=null?` · OCR ${Math.round(shot.ocrConfidence*100)}%`:""}</span></a>`;}).join("")}</div>`:"";
        return `<details class="history-compact">
          <summary>
            <span>${escapeHtml(when.slice(0,10))}</span><span title="${escapeHtml(r.box||"未知箱型")}">${escapeHtml(r.box||"未知箱型")} · Q${r.q??"—"}</span><span>${escapeHtml(modeText)}${winnerText?` · ${escapeHtml(winnerText)}`:""}</span>
            <span class="history-ab-compact"><span class="ab-formal">v0.3 ${fmtWan(estimate)}${error===null?'':` · ${error>=0?'少估':'多估'} ${fmtWan(Math.abs(error))}`}</span>${shadowComparisonHtml(r.actualTotal,shadow,true)}</span><span class="num">${fmtWan(r.actualTotal)}</span><span class="history-ab-compact"><span class="${replayError!==null&&replayError<0?'profit-negative':replayError!==null&&replayError>0?'profit-positive':''}">${apeText}${error===null?'':' · '+(error>=0?'少估':'多估')}</span></span><span class="num">${fmtWan(cap)}</span><span class="num ${profit==null?'':profit>=0?'profit-positive':'profit-negative'}">${profitText}</span><span class="history-caret"></span>
          </summary>
          <div class="history-detail">
          <div class="history-main">
            <strong>${escapeHtml(r.box||"未知箱型")} · Q=${r.q??"—"} <span class="badge ${r.legacy?'muted':'mint'}">${escapeHtml(period)}</span></strong>
            <small>${escapeHtml(when)} · ${escapeHtml(r.venue||"")} · ${escapeHtml(r.role||"")} <span class="condition-badge">${escapeHtml(FIELD_CONDITION_LABELS[r.fieldCondition]||"未知条件")}</span></small>
            <div class="history-intel"><strong>拍下方：</strong>${escapeHtml(winnerLabel)}${r.notes?` · ${escapeHtml(r.notes)}`:""}</div>
            <div class="similar-tags" style="margin-top:8px">${featureHtml}</div>
            <div class="field-help">预测输入：${escapeHtml(input._inputSource||"历史字段")}</div>
            ${intel}${settledFacts}${why}
            ${shotHtml}
            ${(typeof historyInference==='function'?historyInference(r):'')}
            ${(typeof historyRoundDetails==='function'?historyRoundDetails(r):'')}
          </div>
          <div class="history-detail-side">
            <div class="history-actual"><span>实际整箱总价</span><strong>${pendingSettlement?"待识别":fmtWan(r.actualTotal)}</strong><small>${pendingSettlement?"结算截图已保存，等待 AI / 人工确认":fmt(r.actualTotal)+" 海贝"}</small></div>
            <div class="history-metrics">
            <div class="history-value"><span>本人最高出价</span><strong>${fmtWan(r.highestPersonalBid??r.bid)}</strong></div>
            <div class="history-value"><span>最终成交价</span><strong>${fmtWan(r.clearingPrice??r.settlement?.clearingPrice)}</strong></div>
            <div class="history-value"><span>本人实际支付</span><strong>${fmtWan(r.purchaseSpend??r.settlement?.purchaseSpend)}</strong></div>
            <div class="history-value"><span>拍下方</span><strong>${escapeHtml(winnerLabel)}</strong></div>
            <div class="history-value"><span>获取毛利（价值−支付）</span><strong class="${profit==null?'':profit>=0?'profit-positive':'profit-negative'}">${profit==null?'未确认':profitText}</strong></div>
            <div class="history-value"><span>场次现金流（含成本）</span><strong class="${sessionCash>=0?'profit-positive':'profit-negative'}">${sessionCash>=0?'+':''}${fmtWan(sessionCash)}</strong></div>
            <div class="history-value"><span>${estimateSourceLabel}</span><strong>${fmtWan(estimate)}</strong></div>
            <div class="history-value"><span>v0.3 → 实际</span><strong class="${replayError!==null&&replayError<0?'profit-negative':replayError!==null&&replayError>0?'profit-positive':''}">${replayErrorText}</strong></div>
            <div class="history-value"><span>${escapeHtml(r.productVersion||productVersionFor(r))} 当时估值</span><strong>${fmtWan(estimate)}</strong></div>
            <div class="history-value"><span>旧估值 → 实际</span><strong class="${error!==null&&error<0?'profit-negative':error!==null&&error>0?'profit-positive':''}">${errorText}</strong></div>
            ${shadowComparisonHtml(r.actualTotal,shadow)}
            </div>
          <div class="history-detail-actions">
            <button class="icon-btn" title="编辑" onclick="editRecord('${r.id}')">✎</button>
            <button class="icon-btn" title="删除" onclick="askDelete('${r.id}')">×</button>
          </div>
          </div></div>
        </details>`;
      }).join(""):'<div class="empty-list">当前筛选下没有样本</div>';
      const remaining=Math.max(0,allRecords.length-records.length),more=remaining?`<div class="history-load-more"><span>已显示 ${records.length} / ${allRecords.length}</span><button type="button" class="btn small" onclick="loadMoreHistory()">再加载 ${Math.min(15,remaining)} 条</button></div>`:"";
      _hl.innerHTML=rowsHtml+more;
    }
    window.loadMoreHistory=function(){historyVisibleCount+=15;renderHistory();};
    function safeScreenshotSrc(path){return String(path||"").split("/").map(encodeURIComponent).join("/");}
    function renderRecordScreenshotSummary(){const el=document.getElementById("recordScreenshotSummary");if(!el)return;const path=val("recordScreenshotPath"),name=val("recordScreenshotName"),score=num("recordOcrConfidence");el.innerHTML=path||name?`<strong>${escapeHtml(name||path.split("/").pop())}</strong><br>路径：${escapeHtml(path||name)}${score!=null?` · OCR ${Math.round(score*100)}%`:""}`:"尚未绑定截图；历史截图可从推演页的“批量补历史”导入。";}
    window.editRecord=editRecord;
    const editRecordBase=window.editRecord;
    window.editRecord=function(id){editRecordBase(id);const r=state.records.find(x=>x.id===id),shot=(r?.screenshots||[])[0]||null;setVal("recordScreenshotPath",shot?.path||"");setVal("recordScreenshotName",shot?.name||"");setVal("recordOcrConfidence",shot?.ocrConfidence??r?.ocrConfidence??"");renderRecordScreenshotSummary();};
    window.askDelete=id=>openConfirm("删除这条样本？","删除后只能通过之前导出的 JSON 恢复。",()=>{const target=state.records.find(r=>r.id===id),keys=new Set([...(target?.screenshots||[]),...(target?.settlement?.screenshots||[]),...(target?.rounds||[]).flatMap(x=>x.roundEvidence||[])].map(x=>x?.storageKey).filter(Boolean));state.records=state.records.filter(r=>r.id!==id);saveState();void Promise.all([...keys].map(deleteScreenshotBlob));renderReview();toast("样本已删除");});

    function renderHistoryDashboard(){
      const els=[document.getElementById('historyDashboard'),document.getElementById('historyDashboardReview')].filter(Boolean);
      if(!els.length) return;
      const paint=(htmlStr)=>{ els.forEach(node=>{ node.innerHTML=htmlStr; }); };
      const actual=state.records.filter(r=>Number(r.actualTotal)>0);
      if(!actual.length){ paint('<div class="empty-list">还没有足够结算样本</div>'); return; }
      const groupStats=(rows,keyFn)=>[...rows.reduce((m,r)=>{const k=keyFn(r);if(!k)return m;if(!m.has(k))m.set(k,[]);m.get(k).push(Number(r.actualTotal));return m;},new Map())].map(([name,vals])=>({name,...valueStats(vals)}));
      const boxRank=groupStats(actual,r=>r.box||"未知箱型").sort((a,b)=>b.n-a.n).slice(0,10);
      const redRows=[...actual.reduce((m,r)=>{const label=historicalRedLabel(r);if(!label)return m;const k=r.box||"未知箱型";if(!m.has(k))m.set(k,[]);m.get(k).push(label);return m;},new Map())].map(([name,rows])=>{const positive=rows.map(x=>x.total).filter(x=>Number.isFinite(x)&&x>0),s=valueStats(positive);return {name,n:rows.length,workRed:s?Math.min(160000,s.p35):0,jackpotRate:positive.filter(x=>x>=500000).length/rows.length};}).sort((a,b)=>b.n-a.n).slice(0,8);
      const modeOf=r=>{const i=predictionInputRecord(r);return i.goldTotal!=null?'goldTotal':i.q!=null&&i.goldAvg!=null&&i.purpleCount!=null?'goldAvgPurple':i.q!=null&&i.goldAvg!=null?'goldAvgOnly':i.q!=null?'onlyQ':'other';};
      const modeRows=groupStats(actual,modeOf).map(s=>{const id=s.name;
        const label={onlyQ:'Q/数量（无金价）',goldAvgOnly:'Q+金均',goldAvgPurple:'Q+紫+金均',goldTotal:'有金总',knownGold:'已知金藏品',knownRed:'已知红藏品',other:'其他'}[id]||id;
        return {id,label,...s};
      }).sort((a,b)=>b.n-a.n);
      const bids=actual.filter(r=>nonNegativeOrNull(r.highestPersonalBid??r.bid)!==null),acquisitions=actual.filter(r=>recordAcquisitionMargin(r)!==null),acquisitionMargins=acquisitions.map(recordAcquisitionMargin),win=acquisitionMargins.filter(x=>x>=0),loss=acquisitionMargins.filter(x=>x<0),profitStats=valueStats(win),lossStats=valueStats(loss.map(Math.abs)),allCostRecords=state.records.filter(r=>recordTotalCost(r)>0);
      const audit=runDynamicWalkForwardAudit(),auditRows=audit.rows.filter(x=>actual.some(r=>r.id===x.id)),auditSummary=auditStats(auditRows),modeErrorRows=[...auditRows.reduce((m,x)=>{const k=x.mode||"mixed";if(!m.has(k))m.set(k,[]);m.get(k).push(x);return m;},new Map())].map(([mode,list])=>({mode,...auditStats(list)})).sort((a,b)=>b.medianApe-a.medianApe),recordById=new Map(actual.map(r=>[r.id,r])),worstRows=auditRows.slice().sort((a,b)=>b.ape-a.ape).slice(0,6),recentRows=actual.slice().sort((a,b)=>(historyTimestamp(b.playedAt)||0)-(historyTimestamp(a.playedAt)||0)).slice(0,8),redFrequency=[...actual.reduce((m,r)=>{const label=historicalRedLabel(r);if(!label)return m;for(const item of label.items){const x=m.get(item.name)||{name:item.name,n:0,total:0};x.n++;x.total+=item.price;m.set(item.name,x);}return m;},new Map()).values()].sort((a,b)=>b.n-a.n||b.total-a.total).slice(0,10);
      const orderedCash=state.records.slice().sort((a,b)=>(historyTimestamp(a.playedAt)||0)-(historyTimestamp(b.playedAt)||0)),bankroll=[];let running=0;for(const r of orderedCash){running+=recordSessionCashflow(r);bankroll.push(running);}const totalAcquisitionMargin=acquisitionMargins.reduce((s,x)=>s+x,0),totalSessionCost=state.records.reduce((s,r)=>s+recordTotalCost(r),0),minBank=Math.min(0,...bankroll),maxBank=Math.max(1,...bankroll),sparkPoints=bankroll.length>1?bankroll.map((v,i)=>`${(i/(bankroll.length-1)*100).toFixed(2)},${(84-(v-minBank)/(maxBank-minBank||1)*72).toFixed(2)}`).join(" "):"0,84 100,84";
      const inputs=actual.map(predictionInputRecord),coverage=[{label:"Q",n:inputs.filter(r=>r.q!=null).length},{label:"金均",n:inputs.filter(r=>r.goldAvg!=null).length},{label:"紫数",n:inputs.filter(r=>r.purpleCount!=null).length},{label:"金数",n:inputs.filter(r=>r.goldCount!=null).length},{label:"红情报",n:inputs.filter(r=>r.redCount!=null||Number(r.minRed)>0||String(r.knownRed||"").trim()).length},{label:"蓝绿白",n:inputs.filter(r=>r.blueCount!=null||r.greenCount!=null||r.whiteCount!=null||r.blueGrid!=null||r.greenGrid!=null||r.whiteGrid!=null).length},{label:"截图",n:actual.filter(r=>r.screenshots?.length).length},{label:"回合",n:actual.filter(r=>r.rounds?.length).length}];
      const shortName=(s)=>String(s||'').replace(/\s*·\s*/g,' · ').replace(/概率提升/g,'').replace(/藏品/g,'').trim();
      const boxMax=Math.max(1,...boxRank.map(x=>x.p80||0)),redMax=Math.max(1,...redFrequency.map(x=>x.n||0)),modeNames={onlyQ:"只有Q",goldAvgOnly:"Q+金均",goldAvgPurple:"Q+紫+金均",goldTotal:"有金总",knownGold:"已知金藏品",knownRed:"已知红藏品",dualAvg:"双均价",noQ:"无Q",mixed:"混合"};
      const hero=document.getElementById("intelHeroStats");if(hero)hero.textContent=`${actual.length} 局 · ${auditSummary.n} 局严格时序回测 · ${bids.length} 局真实出价`;
      paint(`
        <div class="dash-kpis">
          <div class="dash-kpi"><span>动态回测中位误差</span><strong>${auditSummary.n?(auditSummary.medianApe*100).toFixed(1)+"%":"—"}</strong></div>
          <div class="dash-kpi"><span>Bad Buy（静态）</span><strong>${auditSummary.safeBreach}/${auditSummary.n}</strong></div>
          <div class="dash-kpi"><span>全局现金流（含所有已记成本）</span><strong class="${running>=0?'profit-positive':'profit-negative'}">${running>=0?'+':''}${fmtWan(running)}</strong></div>
          <div class="dash-kpi"><span>截图证据覆盖</span><strong>${coverage.find(x=>x.label==="截图").n}/${actual.length}</strong></div>
        </div>
        <div class="grid two">
          <div class="dash-panel">
            <h3>箱型总价</h3>
            <div class="interval-bars">${boxRank.map(b=>`<div class="interval-row"><span title="${escapeHtml(b.name)}">${escapeHtml(shortName(b.name))} · n=${b.n}</span><div class="interval-track"><i style="left:${(b.p20/boxMax*100).toFixed(1)}%;width:${Math.max(2,(b.p80-b.p20)/boxMax*100).toFixed(1)}%"></i><b style="left:${(b.p50/boxMax*100).toFixed(1)}%"></b></div><strong>${fmtWanNum(b.p50)}</strong></div>`).join("")}</div>
            <details class="dashboard-table-detail"><summary>查看 P20 / P50 / P80 精确表格</summary><table class="dash-table"><thead><tr><th>箱型</th><th>n</th><th>中位</th><th>P20</th><th>P80</th></tr></thead><tbody>
              ${boxRank.map(b=>`<tr><td title="${escapeHtml(b.name)}">${escapeHtml(shortName(b.name))}</td><td class="num">${b.n}</td><td class="num">${fmtWanNum(b.p50)}</td><td class="num">${fmtWanNum(b.p20)}</td><td class="num">${fmtWanNum(b.p80)}</td></tr>`).join('')}
            </tbody></table></details>
          </div>
          <div class="dash-panel">
            <h3>情报档误差 · 高到低</h3>
            <div class="rank-bars">${modeErrorRows.map(m=>`<div class="rank-bar"><span>${escapeHtml(modeNames[m.mode]||m.mode)} · n=${m.n}</span><div class="rank-track"><i style="width:${Math.min(100,m.medianApe*125).toFixed(1)}%"></i></div><b>${(m.medianApe*100).toFixed(1)}%</b></div>`).join("")}</div>
            <p style="margin:10px 0 0;color:var(--muted);font-size:12px;line-height:1.5">已确认本人拍下 ${acquisitions.length} 局：藏品价值−实际支付共 ${fmtWanNum(totalAcquisitionMargin)}；赚 ${win.length} / 亏 ${loss.length} · 赚钱中位 ${fmtWanNum(profitStats?.p50)} · 亏损中位 ${fmtWanNum(lossStats?.p50)}。旧记录赢家/支付未知时不计入。</p>
          </div>
        </div>
        <div class="grid two" style="margin-top:12px">
          <div class="dash-panel">
            <h3>红藏品出现频率</h3>
            <div class="frequency-bars">${redFrequency.length?redFrequency.map(x=>`<div class="frequency-row"><span>${escapeHtml(x.name)}</span><div class="frequency-track"><i style="width:${Math.round(x.n/redMax*100)}%"></i></div><b>${x.n}</b></div>`).join(""):'<div class="empty-list">红藏品名称样本不足</div>'}</div>
            <details class="dashboard-table-detail"><summary>查看累计价值</summary><table class="dash-table"><thead><tr><th>藏品</th><th>出现</th><th>累计价值</th></tr></thead><tbody>${redFrequency.map(x=>`<tr><td>${escapeHtml(x.name)}</td><td>${x.n}</td><td>${fmtWanNum(x.total)}</td></tr>`).join("")}</tbody></table></details>
          </div>
          <div class="dash-panel">
            <h3>全局现金流曲线</h3>
            <svg class="sparkline" viewBox="0 0 100 92" preserveAspectRatio="none" aria-label="累计盈亏曲线"><line x1="0" y1="84" x2="100" y2="84" stroke="#cbd5e1" stroke-width="1"/><polyline points="${sparkPoints}" fill="none" stroke="${running>=0?'#0d9488':'#e11d48'}" stroke-width="2.2" vector-effect="non-scaling-stroke"/></svg>
            <p style="margin:8px 0 0;color:var(--muted);font-size:11px">按日期累计全部 ${orderedCash.length} 局：本人拍下的获取毛利 ${fmtWanNum(totalAcquisitionMargin)} − 所有已记录场次成本 ${fmtWanNum(totalSessionCost)} = ${fmtWanNum(running)}；最低 ${fmtWanNum(minBank)}。未出价局的成本也计入。</p>
          </div>
        </div>
        <div class="grid two dashboard-action-grid" style="margin-top:12px">
          <div class="dash-panel">
            <h3>模型最容易看错的局</h3>
            <div class="risk-list">${worstRows.map(x=>{const r=recordById.get(x.id)||{};return `<div class="risk-row"><span><strong>${escapeHtml(shortName(r.box||x.box||"未知箱型"))}</strong><small>${escapeHtml((r.playedAt||x.playedAt||"").slice(0,16).replace("T"," "))} · ${escapeHtml(x.mode)}</small><small>${escapeHtml(historicalErrorExplanation(r,x.estimate))}</small></span><span class="risk-values"><b>${fmtWan(x.estimate)} → ${fmtWan(x.actual)}</b><small class="${x.bias>0?'profit-negative':'profit-positive'}">${x.bias>0?'多估':'少估'} ${Math.abs(x.bias*100).toFixed(1)}%</small></span></div>`;}).join("")||'<div class="empty-list">可回测样本不足</div>'}</div>
          </div>
          <div class="dash-panel">
            <h3>最近 8 局 · 价值与场次现金流</h3>
            <div class="recent-game-list">${recentRows.map(r=>{const cash=recordSessionCashflow(r),margin=recordAcquisitionMargin(r);return `<div class="recent-game"><span><strong>${escapeHtml(shortName(r.box||"未知箱型"))}</strong><small>${escapeHtml((r.playedAt||"").slice(5,16).replace("T"," "))} · ${margin==null?'未确认获取毛利':`获取毛利 ${fmtWan(margin)}`}</small></span><b>${fmtWan(r.actualTotal)}</b><em class="${cash>=0?'profit-positive':'profit-negative'}">${cash>=0?`+${fmtWan(cash)}`:`-${fmtWan(Math.abs(cash))}`}</em></div>`;}).join("")}</div>
          </div>
        </div>
        <div class="dash-panel" style="margin-top:12px"><h3>数据覆盖率</h3><div class="calibration-list">${coverage.map(x=>`<div class="calibration-row"><span>${escapeHtml(x.label)}</span><div class="calibration-track"><i style="width:${Math.round(x.n/actual.length*100)}%"></i></div><b>${x.n}/${actual.length}</b></div>`).join("")}</div><p style="margin:10px 0 0;color:var(--muted);font-size:11px">蓝绿白数据覆盖不足时只用图鉴先验，不会伪装成“历史训练结果”。</p></div>`);
    }


    let modelAuditCache={signature:"",rows:[],roundRows:[],failures:[],status:"idle",generatedAt:null},modelAuditPromise=null;
    function predictionInputRecord(r,selectedSnapshot=null){
      const rounds=Array.isArray(r.rounds)?r.rounds.filter(x=>Number.isInteger(Number(x.round))).slice().sort((a,b)=>Number(a.round)-Number(b.round)):[];
      if(!selectedSnapshot&&!rounds.length)return {...r,_inputSource:"历史字段（无回合快照）",_inputRound:null};
      const snap=selectedSnapshot||rounds.at(-1),keys=["q","goldAvg","goldTotal","goldCount","purpleCount","purpleAvg","redCount","cost","targetProfit","minPurple","minGold","minRed","knownPurple","knownGold","knownRed","totalItems","totalGrid","goldGrid","purpleGrid","blueCount","blueGrid","blueAvg","greenCount","greenGrid","greenAvg","whiteCount","whiteGrid","whiteAvg","systemEstimate","singleAvg","nineAvg","publicNote","toolGroup","roundingMode","requestedRoundingMode","fieldCondition","avgValueBasis","privateBidCap","bidActionCount","sparkle","intelEvents"];
      const input={...r};for(const key of keys)input[key]=Object.prototype.hasOwnProperty.call(snap,key)?snap[key]:null;
      input.toolGroup=Object.prototype.hasOwnProperty.call(snap,"toolGroup")?snap.toolGroup:(r.toolGroup||"group1");
      input.venue=snap.venue||r.venue;input.box=snap.box||r.box;input.character=snap.character||r.character;input._inputSource=`推演 R${snap.round} 快照`;input._inputRound=Number(snap.round);return input;
    }
    function replayContextFromRecord(r,snapshot=null,allowedHistoryIds=null){
      const input=predictionInputRecord(r,snapshot),priceBasis=normalizeAvgValueBasis(input.avgValueBasis||r.avgValueBasis||"unknown"),priceFieldCondition=canonicalFieldConditionId(input.fieldCondition||r.fieldCondition||"unknown"),goldPriceOptions={multiplier:conditionPriceMultiplier({fieldCondition:priceFieldCondition},"gold"),basis:priceBasis},purplePriceOptions={multiplier:conditionPriceMultiplier({fieldCondition:priceFieldCondition},"purple"),basis:priceBasis};let knownGold=[],goldGroups=[],knownPurple=[],purpleGroups=[],knownRed=[],redGroups=[];try{goldGroups=parseOr(String(input.knownGold||""),goldPriceOptions);knownGold=goldGroups.flatMap(([prices,n])=>prices.length===1?Array.from({length:n},()=>{const item=GOLD_ITEMS.find(x=>x[1]===prices[0]);return item?{name:item[0],price:item[1],size:item[2]}:null;}).filter(Boolean):[]);}catch(_){}try{const parsed=parseFlexibleKnown(String(input.knownPurple||""),PURPLE_ITEMS,"紫色",purplePriceOptions);knownPurple=parsed.known;purpleGroups=parsed.groups;}catch(_){}try{const parsed=parseFlexibleKnown(String(input.knownRed||""),RED_ITEMS,"红色",{multiplier:1,basis:"base"});knownRed=parsed.known;redGroups=parsed.groups;}catch(_){}
      const valueOrNull=value=>hasNumber(value)?Number(value):null,publicInfo={totalItems:valueOrNull(input.totalItems),totalGrid:valueOrNull(input.totalGrid),goldGrid:valueOrNull(input.goldGrid),purpleGrid:valueOrNull(input.purpleGrid),blueCount:valueOrNull(input.blueCount),blueGrid:valueOrNull(input.blueGrid),blueAvg:valueOrNull(input.blueAvg),greenCount:valueOrNull(input.greenCount),greenGrid:valueOrNull(input.greenGrid),greenAvg:valueOrNull(input.greenAvg),whiteCount:valueOrNull(input.whiteCount),whiteGrid:valueOrNull(input.whiteGrid),whiteAvg:valueOrNull(input.whiteAvg),systemEstimate:valueOrNull(input.systemEstimate),singleAvg:valueOrNull(input.singleAvg),nineAvg:valueOrNull(input.nineAvg),note:input.publicNote||""};
      const exactInt=value=>hasNumber(value)&&Number.isInteger(Number(value))?Number(value):null;
      const targetProfitValue=hasNumber(input.targetProfit)?Math.max(0,Number(input.targetProfit)):30000;
      let context={q:exactInt(input.q),avg:valueOrNull(input.goldAvg),goldTotal:valueOrNull(input.goldTotal),goldCount:exactInt(input.goldCount),purple:exactInt(input.purpleCount),purpleAvg:valueOrNull(input.purpleAvg),redCount:exactInt(input.redCount),cost:Math.max(0,Number(input.cost)||0),targetProfit:targetProfitValue,minGold:Math.max(Number(input.minGold)||0,(hasNumber(input.goldAvg)||hasNumber(input.goldTotal))?1:0,knownGold.length,goldGroups.reduce((s,x)=>s+x[1],0)),minPurple:Math.max(Number(input.minPurple)||0,knownPurple.length,purpleGroups.reduce((s,x)=>s+x[1],0)),minRed:Math.max(Number(input.minRed)||0,knownRed.length,redGroups.reduce((s,x)=>s+x[1],0)),knownGold,goldGroups,knownPurple,purpleGroups,knownRed,redGroups,toolGroup:input.toolGroup||r.toolGroup||"group1",knownGoldRaw:input.knownGold||"",knownPurpleRaw:input.knownPurple||"",knownRedRaw:input.knownRed||"",venue:input.venue,box:input.box,character:input.character,playedAt:r.playedAt,periodKey:r.periodKey,fieldCondition:input.fieldCondition||r.fieldCondition||"unknown",avgValueBasis:input.avgValueBasis||r.avgValueBasis||"unknown",privateBidCap:valueOrNull(input.privateBidCap),bidActionCount:exactInt(input.bidActionCount),sparkle:input.sparkle||r.sparkle||null,intelEvents:normalizeIntelEvents(input.intelEvents??r.intelEvents),excludeRecordId:r.id,allowedHistoryIds:allowedHistoryIds?[...allowedHistoryIds]:null,publicInfo,round:input._inputRound||1,roundingMode:input.requestedRoundingMode||input.roundingMode||"floor",_inputSource:input._inputSource,_inputRound:input._inputRound};
      context=enrichContextFromIntel(maybeLockRedZero(context));if((!context.knownRed||!context.knownRed.length)&&knownRed.length)context.knownRed=knownRed;context.minRed=Math.max(context.minRed||0,(context.knownRed||[]).length);return context;
    }
    function auditSignature(){
      const keys=["round","q","goldAvg","goldTotal","goldCount","purpleCount","purpleAvg","redCount","cost","targetProfit","minGold","minPurple","minRed","knownGold","knownPurple","knownRed","totalItems","totalGrid","goldGrid","purpleGrid","blueCount","blueGrid","blueAvg","greenCount","greenGrid","greenAvg","whiteCount","whiteGrid","whiteAvg","systemEstimate","singleAvg","nineAvg","publicNote","venue","box","character","roundingMode","requestedRoundingMode","fieldCondition","avgValueBasis","privateBidCap","bidActionCount","sparkle","intelEvents"];
      return state.records.map(r=>`${r.id}:${r.updatedAt||r.createdAt||0}:${r.actualTotal||0}:${r.redCount??""}:${r.redItems||r.settlement?.recognizedItems||""}:${r.settlement?.status||""}:${JSON.stringify((r.rounds||[]).map(x=>keys.map(k=>x[k]??null)))}`).sort().join("|");
    }
    function auditRowFromAnalysis(r,snapshot,ctx,analysis){
      const d=analysis?.workingDecision,actual=Number(r.actualTotal);if(!d||!Number.isFinite(d.center))return null;
      const candidateStates=(analysis.candidates||[]).map(x=>({g:x.g,p:x.p,r:x.r,rMin:x.rMin??x.r,rMax:x.rMax??x.r}));
      const theoryMin=analysis.theoreticalMin??null,theoryMax=analysis.theoreticalMax??null,stateIssue=Number.isFinite(theoryMin)&&actual<theoryMin||Number.isFinite(theoryMax)&&actual>theoryMax;
      const historyIssue=Number.isFinite(d.structuralCenter)&&Number.isFinite(d.center)&&Math.abs(d.center-actual)>Math.abs(d.structuralCenter-actual)+Math.max(10000,actual*.05);
      const probabilityIssue=!stateIssue&&(actual<d.low||actual>d.high),capCapture=Number.isFinite(d.cap)&&actual>0?d.cap/actual:null;
      const decisionIssue=Number.isFinite(d.cap)&&(d.cap>actual||(!stateIssue&&Math.abs(d.center-actual)/actual<=.2&&capCapture<.35));
      const diagnostic={state:stateIssue,probability:probabilityIssue,history:historyIssue,decision:decisionIssue};
      const diagnosticPriority=stateIssue?"State":probabilityIssue?"Probability":historyIssue?"History":decisionIssue?"Decision":"Normal",strategyCap=d.recommendedMaxBid??d.balancedCap??d.cap,counterfactual=staticCounterfactual(r,strategyCap);
      return {id:r.id,round:Number(snapshot.round),inputSource:ctx._inputSource,q:ctx.q,purple:ctx.purple,goldCount:ctx.goldCount,redCount:ctx.redCount,goldAvg:ctx.avg,goldTotal:ctx.goldTotal,goldGrid:ctx.publicInfo?.goldGrid??null,knownGoldRaw:ctx.knownGoldRaw||"",knownPurpleRaw:ctx.knownPurpleRaw||"",knownRedRaw:ctx.knownRedRaw||"",actual,estimate:d.center,low:d.low,high:d.high,cap:d.cap,balancedCap:d.balancedCap,conservativeLossLine:d.conservativeLossLine??d.cap,recommendedMaxBid:d.recommendedMaxBid??d.balancedCap,highRiskTrialLine:d.highRiskTrialLine??d.high,capCapture,hardFloor:d.hardFloor,structuralCenter:d.structuralCenter,preAnalogCenter:d.preAnalogCenter,analogTarget:d.analogTarget,analogWeight:d.analogWeight,componentBreakdown:d.breakdown||null,probabilityProfile:d.probabilityProfile||null,empiricalStatePrior:d.empiricalStatePrior||null,shadowRaw:d.probabilityProfile?.shadowWhole||null,shadowCalibrated:d.shadowCalibrated||null,marketPrediction:d.marketPrediction||null,entryDecision:d.entryDecision||null,realizedState:realizedStateTruth(r),theoreticalMin:theoryMin,theoreticalMax:theoryMax,theoreticalMinimumBreakdown:analysis.theoreticalMinimumBreakdown||null,source:d.source,ape:Math.abs(d.center-actual)/actual,bias:(d.center-actual)/actual,mode:d.infoMode?.id||detectInfoMode(ctx).id,venue:r.venue,box:r.box,bid:Number(r.bid)>0?Number(r.bid):null,cost:Number(r.cost)||0,totalCost:recordTotalCost(r),clearingPrice:counterfactual.clearingPrice,counterfactual,profit:Number(r.bid)>0?actual-Number(r.bid)-(Number(r.cost)||0):null,playedAt:r.playedAt,candidateGs:analysis.candidateGs||[],candidatePs:analysis.candidatePs||[],redMin:analysis.redMin,redMax:analysis.redMax,stateCount:candidateStates.length,candidateStates,goldMatchCount:analysis.goldInference?.goldMatchCount??null,goldInference:analysis.goldInference||null,confidence:d.confidence,solverStatus:analysis.solverStatus||"valid",roundingMode:analysis.roundingMode,historyRecordIds:d.similar?.map(x=>x.record.id)||[],diagnostic,diagnosticPriority};
    }
    function solverStatusForRecord(record,snapshot=null){return String(snapshot?.solverStatus||snapshot?.prediction?.solverStatus||record?.solverStatus||record?.prediction?.solverStatus||"").toLowerCase()||"legacy";}
    function solverStatusEligibleForTraining(status){return ["legacy","unknown","valid","fallback"].includes(String(status||"legacy").toLowerCase())&&!String(status||"").toLowerCase().startsWith("diagnostic");}
    function staticCounterfactual(source,strategyCap,options={}){
      const actual=nonNegativeOrNull(source?.actualTotal),clearing=nonNegativeOrNull(source?.clearingPrice??source?.settlement?.clearingPrice),cap=nonNegativeOrNull(strategyCap),cost=options.cost===undefined?recordTotalCost(source):Math.max(0,Number(options.cost)||0);
      if(actual===null||clearing===null||cap===null)return {status:"unknown",actual,clearingPrice:clearing,strategyCap:cap,cost,acquired:null,profit:null,decisionRegret:null,missedOpportunity:false,badBuy:false};
      const buyProfit=actual-clearing-cost,noBuyProfit=-cost,acquired=cap>=clearing,profit=acquired?buyProfit:noBuyProfit,bestProfit=Math.max(noBuyProfit,buyProfit),decisionRegret=Math.max(0,bestProfit-profit),missedOpportunity=!acquired&&buyProfit>0,badBuy=acquired&&buyProfit<0;
      return {status:"known",actual,clearingPrice:clearing,strategyCap:cap,cost,acquired,profit,buyProfit,noBuyProfit,bestProfit,decisionRegret,missedOpportunity,badBuy,missedProfit:missedOpportunity?buyProfit:0,badBuyLoss:badBuy?buyProfit:0};
    }
    function savedStrategyCap(record){const prediction=savedPredictionForHistory(record);return nonNegativeOrNull(prediction?.recommendedMaxBid??prediction?.balancedCap??prediction?.recommendedCap??prediction?.conservativeLossLine);}
    function staticCounterfactualForRecord(record){return staticCounterfactual(record,savedStrategyCap(record));}
    function strictAuditRecords(){return state.records.filter(r=>r.diagnosticOnly!==true&&!r.rounds?.some(x=>x?.diagnosticOnly===true)&&Number(r.actualTotal)>0&&r.settlement?.status!=="pending"&&historyTimestamp(r.playedAt)!==null&&solverStatusEligibleForTraining(solverStatusForRecord(r,null))).slice().sort((a,b)=>historyTimestamp(a.playedAt)-historyTimestamp(b.playedAt)||(Number(a.createdAt)||0)-(Number(b.createdAt)||0)||String(a.id).localeCompare(String(b.id)));}
    async function computeDynamicWalkForwardAudit(signature){
      const records=strictAuditRecords(),rows=[],roundRows=[],failures=[],priorIds=new Set();let solvedSnapshots=0;
      modelAuditCache={signature,rows:[],roundRows:[],failures:[],status:"running",verifiedRecords:records.length,snapshotRecords:0,generatedAt:null};
      for(const r of records){
        const snapshots=Array.isArray(r.rounds)?r.rounds.filter(x=>Number.isInteger(Number(x.round))).slice().sort((a,b)=>Number(a.round)-Number(b.round)):[];
        const thisRows=[];
        for(const snapshot of snapshots){
          const savedStatus=solverStatusForRecord(r,snapshot);
          if(!solverStatusEligibleForTraining(savedStatus)){failures.push({id:r.id,round:Number(snapshot.round),error:`data-quality:${savedStatus}`});continue;}
          try{
            document.documentElement.dataset.strictAuditCurrent=`${r.id}:R${snapshot.round}`;
            const ctx=replayContextFromRecord(r,snapshot,priorIds),solved=await analyzeContextWithSharedCoreAsync(ctx),analysis=solved.analysis;
            if(solved.error){failures.push({id:r.id,round:Number(snapshot.round),error:solved.error});continue;}
            if(!solverStatusEligibleForTraining(analysis?.solverStatus||"valid")){failures.push({id:r.id,round:Number(snapshot.round),error:`replay-status:${analysis?.solverStatus||"unknown"}`});continue;}
            const row=auditRowFromAnalysis(r,snapshot,ctx,analysis);if(!row){failures.push({id:r.id,round:Number(snapshot.round),error:"no-decision"});continue;}
            roundRows.push(row);thisRows.push(row);
          }catch(error){failures.push({id:r.id,round:Number(snapshot.round),error:String(error?.message||error)});console.warn("audit skip",r.id,snapshot.round,error);}
          solvedSnapshots++;modelAuditCache.progress={recordsDone:rows.length,recordsTotal:records.length,snapshotsDone:solvedSnapshots,roundRows:roundRows.length,failures:failures.length};document.documentElement.dataset.strictAuditProgress=JSON.stringify(modelAuditCache.progress);if(solvedSnapshots%4===0)await new Promise(resolve=>setTimeout(resolve,0));
        }
        if(thisRows.length)rows.push(thisRows.at(-1));
        // 结算答案只在该局所有 T1 快照评分完成后，才进入后续局的历史先验。
        priorIds.add(r.id);
      }
      return {signature,rows,roundRows,failures,status:"complete",verifiedRecords:records.length,snapshotRecords:rows.length,generatedAt:new Date().toISOString()};
    }
    function notifyAuditReady(){
      if(!document.getElementById("page-review")?.classList.contains("active"))return;
      scheduleReviewHeavyRender();
    }
    function publishAuditProbe(result){
      let el=document.getElementById("strictAuditProbe");if(!el){el=document.createElement("pre");el.id="strictAuditProbe";el.hidden=true;document.body.appendChild(el);}
       const slimRow=row=>({id:row.id,round:row.round,q:row.q,purple:row.purple,goldCount:row.goldCount,redCount:row.redCount,goldAvg:row.goldAvg,goldTotal:row.goldTotal,goldGrid:row.goldGrid,knownGoldRaw:row.knownGoldRaw,knownPurpleRaw:row.knownPurpleRaw,knownRedRaw:row.knownRedRaw,actual:row.actual,estimate:row.estimate,low:row.low,high:row.high,cap:row.cap,conservativeLossLine:row.conservativeLossLine,recommendedMaxBid:row.recommendedMaxBid,highRiskTrialLine:row.highRiskTrialLine,capCapture:row.capCapture,hardFloor:row.hardFloor,structuralCenter:row.structuralCenter,analogTarget:row.analogTarget,analogWeight:row.analogWeight,componentBreakdown:row.componentBreakdown,probabilityProfile:row.probabilityProfile,theoreticalMin:row.theoreticalMin,theoreticalMax:row.theoreticalMax,theoreticalMinimumBreakdown:row.theoreticalMinimumBreakdown,candidateGs:row.candidateGs,candidatePs:row.candidatePs,redMin:row.redMin,redMax:row.redMax,stateCount:row.stateCount,goldMatchCount:row.goldMatchCount,confidence:row.confidence,solverStatus:row.solverStatus,clearingPrice:row.clearingPrice,totalCost:row.totalCost,counterfactual:row.counterfactual,mode:row.mode,venue:row.venue,box:row.box,playedAt:row.playedAt,diagnostic:row.diagnostic,diagnosticPriority:row.diagnosticPriority});
      el.textContent=JSON.stringify({status:result.status,verifiedRecords:result.verifiedRecords,snapshotRecords:result.snapshotRecords,generatedAt:result.generatedAt,failures:result.failures,rows:(result.rows||[]).map(slimRow),roundRows:(result.roundRows||[]).map(slimRow)});
    }
    function runDynamicWalkForwardAudit(){
      const signature=auditSignature();
      if(modelAuditCache.signature===signature&&modelAuditCache.status==="complete")return modelAuditCache;
      if(!modelAuditPromise||modelAuditCache.signature!==signature){modelAuditPromise=computeDynamicWalkForwardAudit(signature).then(result=>{modelAuditCache=result;publishAuditProbe(result);modelAuditPromise=null;notifyAuditReady();void runInferenceConsistencyTests(3).then(test=>{let el=document.getElementById("inferenceConsistencyProbe");if(!el){el=document.createElement("pre");el.id="inferenceConsistencyProbe";el.hidden=true;document.body.appendChild(el);}el.textContent=JSON.stringify(test);});return result;}).catch(error=>{modelAuditCache={signature,rows:[],roundRows:[],failures:[{error:String(error?.message||error)}],status:"error",generatedAt:new Date().toISOString()};publishAuditProbe(modelAuditCache);modelAuditPromise=null;console.error(error);return modelAuditCache;});}
      return modelAuditCache.signature===signature?modelAuditCache:{signature,rows:[],roundRows:[],failures:[],status:"running",generatedAt:null};
    }
    async function runDynamicWalkForwardAuditAsync(force=false){
      const signature=auditSignature();if(force){modelAuditCache={signature:"",rows:[],roundRows:[],failures:[],status:"idle",generatedAt:null};modelAuditPromise=null;}
      runDynamicWalkForwardAudit();return modelAuditPromise?await modelAuditPromise:modelAuditCache;
    }
    function inferenceConsistencySignature(analysis){
      const d=analysis?.workingDecision,roundNumber=value=>Number.isFinite(value)?Math.round(value*1e6)/1e6:value??null,states=(analysis?.candidates||[]).map(x=>[x.g,x.p,x.r,x.rMin??x.r,x.rMax??x.r].join("/")).sort();
      return {candidateGPR:states,stateCount:states.length,candidateGs:[...(analysis?.candidateGs||[])].sort((a,b)=>a-b),candidatePs:[...(analysis?.candidatePs||[])].sort((a,b)=>a-b),goldMatchCount:analysis?.goldInference?.goldMatchCount??null,theoreticalMin:roundNumber(analysis?.theoreticalMin),theoreticalMax:roundNumber(analysis?.theoreticalMax),structuralCenter:roundNumber(d?.structuralCenter),workingCenter:roundNumber(d?.center),workingLow:roundNumber(d?.low),workingHigh:roundNumber(d?.high),hardFloor:roundNumber(d?.hardFloor),cap:roundNumber(d?.cap),confidence:d?.confidence??null};
    }
    async function runInferenceConsistencyTests(limit=3){
      const records=strictAuditRecords(),targets=records.filter(r=>Array.isArray(r.rounds)&&r.rounds.length).slice(-Math.max(1,limit)),results=[];
      for(const r of targets){
        const index=records.findIndex(x=>x.id===r.id),priorIds=new Set(records.slice(0,index).map(x=>x.id)),snapshot=r.rounds.filter(x=>Number.isInteger(Number(x.round))).slice().sort((a,b)=>Number(a.round)-Number(b.round)).at(-1);if(!snapshot)continue;
        const syncCtx=replayContextFromRecord(r,snapshot,priorIds),asyncCtx=replayContextFromRecord(r,snapshot,priorIds),syncSolved=analyzeContextWithSharedCore(syncCtx),asyncSolved=await analyzeContextWithSharedCoreAsync(asyncCtx),syncSignature=inferenceConsistencySignature(syncSolved.analysis),asyncSignature=inferenceConsistencySignature(asyncSolved.analysis),same=JSON.stringify(syncSignature)===JSON.stringify(asyncSignature);
        results.push({id:r.id,round:Number(snapshot.round),same,sync:syncSignature,async:asyncSignature});
      }
      return {passed:results.every(x=>x.same),tested:results.length,results};
    }
    window.runInferenceConsistencyTests=runInferenceConsistencyTests;
    window.runStrictWalkForwardAudit=runDynamicWalkForwardAuditAsync;
    function auditStats(rows){const apes=rows.map(x=>x.ape).filter(Number.isFinite),bias=rows.map(x=>x.bias).filter(Number.isFinite),outcomes=rows.map(x=>x.counterfactual).filter(x=>x?.status==="known");return {n:rows.length,medianApe:median(apes),meanApe:mean(apes),medianBias:median(bias),safeBreach:outcomes.filter(x=>x.badBuy).length,balancedBreach:outcomes.filter(x=>x.strategyCap>=x.clearingPrice&&x.profit<0).length,missedOpportunity:outcomes.filter(x=>x.missedOpportunity).length,badBuy:outcomes.filter(x=>x.badBuy).length,decisionRegret:outcomes.reduce((s,x)=>s+(x.decisionRegret||0),0),counterfactualN:outcomes.length};}
    function marketOosEvaluationV06(rows=[]){
      const usable=(rows||[]).filter(row=>{const m=row?.marketPrediction,c=Number(row?.clearingPrice??row?.counterfactual?.clearingPrice);return row?.id&&m&&Number.isFinite(c)&&c>0&&[m.p20,m.p50,m.p80].every(v=>Number.isFinite(Number(v)));});
      if(!usable.length)return {status:"no-sample",n:0,p50Mae:null,p50Bias:null,ratioMae:null,ratioBias:null,p20p80Coverage:null,lowSampleN:0,fallbackLevels:{},byQ:[]};
      const scored=usable.map(row=>{const m=row.marketPrediction,c=Number(row.clearingPrice??row.counterfactual?.clearingPrice),est=Number(row.estimate),ratioActual=Number.isFinite(est)&&est>0?c/est:null,ratioPred=Number.isFinite(Number(m.marketRatio?.p50))?Number(m.marketRatio.p50):null;return {id:row.id,qBucket:qBucketV06(row.q),actual:c,p20:Number(m.p20),p50:Number(m.p50),p80:Number(m.p80),absError:Math.abs(Number(m.p50)-c),bias:Number(m.p50)-c,ratioActual,ratioPred,ratioAbsError:ratioActual!==null&&ratioPred!==null?Math.abs(ratioPred-ratioActual):null,ratioBias:ratioActual!==null&&ratioPred!==null?ratioPred-ratioActual:null,covered:actualInRange(c,m.p20,m.p80),fallbackLevel:m.fallbackLevel||"global",lowSample:m.lowSample===true};});
      const avg=key=>{const vals=scored.map(x=>x[key]).filter(Number.isFinite);return vals.length?mean(vals):null;},fallbackLevels=scored.reduce((acc,x)=>(acc[x.fallbackLevel]=(acc[x.fallbackLevel]||0)+1,acc),{}),summarize=list=>{const n=list.length;if(!n)return {n:0,p50Mae:null,p50Bias:null,ratioMae:null,ratioBias:null,p20p80Coverage:null};const v=key=>{const vals=list.map(x=>x[key]).filter(Number.isFinite);return vals.length?mean(vals):null;};return {n,p50Mae:v("absError"),p50Bias:v("bias"),ratioMae:v("ratioAbsError"),ratioBias:v("ratioBias"),p20p80Coverage:list.filter(x=>x.covered).length/n};};
      const byQ=[...scored.reduce((map,row)=>{if(!map.has(row.qBucket))map.set(row.qBucket,[]);map.get(row.qBucket).push(row);return map;},new Map())].sort((a,b)=>a[0].localeCompare(b[0],"zh-CN")).map(([q,list])=>({q,...summarize(list)}));
      return {status:"oos",n:scored.length,p50Mae:avg("absError"),p50Bias:avg("bias"),ratioMae:avg("ratioAbsError"),ratioBias:avg("ratioBias"),p20p80Coverage:scored.filter(x=>x.covered).length/scored.length,lowSampleN:scored.filter(x=>x.lowSample).length,fallbackLevels,byQ,rows:scored};
    }
    function marketOosEvaluationHtml(summary){
      if(!summary||summary.status==="no-sample")return `<div class="v06-market-oos-eval"><h3 class="prob-calibration-subhead">Market OOS 评估</h3><div class="empty-list">暂无严格 OOS 市场样本：需要当局之前冻结的 marketPrediction 和已知清算价。</div></div>`;
      const fmtMoney=v=>v==null?"—":fmtWan(v),fmtPct=v=>v==null?"—":`${(v*100).toFixed(1)}%`,fmtRatio=v=>v==null?"—":Number(v).toFixed(3),rows=(summary.byQ||[]).map(x=>`<div class="prob-cal-row"><span><strong>${escapeHtml(x.q)}</strong> · n=${x.n}</span><b>P50 MAE ${fmtMoney(x.p50Mae)}</b><b>Ratio MAE ${fmtRatio(x.ratioMae)}</b><b>区间覆盖 ${fmtPct(x.p20p80Coverage)}</b></div>`).join("");
      return `<div class="v06-market-oos-eval"><h3 class="prob-calibration-subhead">Market OOS 评估 · n=${summary.n}</h3><div class="shadow-ab-grid"><div class="shadow-ab-cell shadow"><span>清算价 P50 MAE</span><strong>${fmtMoney(summary.p50Mae)}</strong><small>严格时序预测 vs clearingPrice</small></div><div class="shadow-ab-cell shadow"><span>P50 Bias</span><strong>${fmtMoney(summary.p50Bias)}</strong><small>正数=市场预测偏高</small></div><div class="shadow-ab-cell shadow"><span>marketRatio MAE</span><strong>${fmtRatio(summary.ratioMae)}</strong><small>连续比例误差</small></div><div class="shadow-ab-cell shadow"><span>P20–P80 覆盖</span><strong>${fmtPct(summary.p20p80Coverage)}</strong><small>真实清算价落入区间</small></div><div class="shadow-ab-cell shadow"><span>低样本局</span><strong>${summary.lowSampleN}</strong><small>市场层级样本不足5</small></div><div class="shadow-ab-cell shadow"><span>回退层</span><strong>${escapeHtml(Object.entries(summary.fallbackLevels||{}).map(([k,n])=>`${k} ${n}`).join(" · ")||"—")}</strong><small>exact-condition-box-q → global</small></div></div><h4 class="prob-calibration-subhead">按 Q bucket</h4><div class="prob-calibration-groups">${rows||'<div class="empty-list">暂无 Q 分层样本</div>'}</div><div class="field-help">严格 OOS：每行只使用该局之前可用的 clearingPrice/冻结估值；不读取 actualTotal 反推市场，不把同局或未来记录倒灌。市场层级为 global → venue → box → condition → Q bucket → exact condition + box + Q。</div></div>`;
    }
    function shadowOosEvaluationV06(rows=[]){
      const usable=(rows||[]).filter(row=>{const raw=row?.shadowRaw,cal=row?.shadowCalibrated?.calibrated;return Number.isFinite(Number(row?.actual))&&Number(row.actual)>0&&raw&&cal&&[raw.p20,raw.p80,cal.p20,cal.p80].every(v=>Number.isFinite(Number(v)));});
      if(!usable.length)return {status:"no-sample",n:0,rawCoverage:null,calibratedCoverage:null,rawWidth:null,calibratedWidth:null};
      const rawHits=usable.filter(row=>actualInRange(Number(row.actual),row.shadowRaw.p20,row.shadowRaw.p80)).length,calHits=usable.filter(row=>actualInRange(Number(row.actual),row.shadowCalibrated.calibrated.p20,row.shadowCalibrated.calibrated.p80)).length;
      return {status:"oos",n:usable.length,rawCoverage:rawHits/usable.length,calibratedCoverage:calHits/usable.length,rawWidth:mean(usable.map(row=>Number(row.shadowRaw.p80)-Number(row.shadowRaw.p20))),calibratedWidth:mean(usable.map(row=>Number(row.shadowCalibrated.calibrated.p80)-Number(row.shadowCalibrated.calibrated.p20)))};
    }
    function shadowOosEvaluationHtml(summary){
      if(!summary||summary.status==="no-sample")return `<div class="v06-shadow-oos-eval"><h3 class="prob-calibration-subhead">Shadow 区间 OOS 覆盖</h3><div class="empty-list">暂无同时具备 Raw Shadow、校准区间和实际结算价的严格 OOS 样本。</div></div>`;
      const pct=v=>v==null?"—":`${(v*100).toFixed(1)}%`,money=v=>v==null?"—":fmtWan(v);
      return `<div class="v06-shadow-oos-eval"><h3 class="prob-calibration-subhead">Shadow 区间 OOS 覆盖 · n=${summary.n}</h3><div class="shadow-ab-grid"><div class="shadow-ab-cell shadow"><span>Raw P20–P80</span><strong>${pct(summary.rawCoverage)}</strong><small>未校准真实覆盖</small></div><div class="shadow-ab-cell shadow"><span>Calibrated P20–P80</span><strong>${pct(summary.calibratedCoverage)}</strong><small>真实 OOS 区间覆盖</small></div><div class="shadow-ab-cell shadow"><span>Raw 区间宽度</span><strong>${money(summary.rawWidth)}</strong><small>平均 P80 − P20</small></div><div class="shadow-ab-cell shadow"><span>Calibrated 宽度</span><strong>${money(summary.calibratedWidth)}</strong><small>旁路扩宽，不改正式中心</small></div></div><div class="field-help">覆盖分母是严格时序回放样本；校准区间只使用当时可见历史残差得到，不能把事后实际值用于当局决策。</div></div>`;
    }
    function predictionInfoMetricsV06(prediction){
      const profile=prediction?.probabilityProfile||{},candidates=Array.isArray(profile.stateCandidates)?profile.stateCandidates:[],raw=prediction?.shadowCalibrated?.calibrated||profile.shadowWhole||null,width=raw&&Number.isFinite(Number(raw.p20))&&Number.isFinite(Number(raw.p80))?Math.max(0,Number(raw.p80)-Number(raw.p20)):null,decision=prediction?.entryDecision?.status||null;
      return {stateCount:candidates.length||null,shadowWidth:width,decision};
    }
    function informationValueStatsV06(records=[]){
      const events=[];
      for(const record of records||[]){
        const rounds=(record.rounds||[]).filter(x=>Number.isInteger(Number(x.round))).slice().sort((a,b)=>Number(a.round)-Number(b.round));
        for(let i=0;i<rounds.length;i++){
          const round=rounds[i],previous=rounds[i-1]||null,after=predictionInfoMetricsV06(round.prediction),before=predictionInfoMetricsV06(previous?.prediction),roundEvents=normalizeIntelEvents(round.intelEvents||[]);
          for(const event of roundEvents){
            const explicitBefore=event.before&&typeof event.before==="object"?event.before:null,explicitAfter=event.after&&typeof event.after==="object"?event.after:null;
            const stateBefore=Number.isFinite(Number(explicitBefore?.stateCount))?Number(explicitBefore.stateCount):before.stateCount,stateAfter=Number.isFinite(Number(explicitAfter?.stateCount))?Number(explicitAfter.stateCount):after.stateCount,widthBefore=Number.isFinite(Number(explicitBefore?.shadowWidth))?Number(explicitBefore.shadowWidth):before.shadowWidth,widthAfter=Number.isFinite(Number(explicitAfter?.shadowWidth))?Number(explicitAfter.shadowWidth):after.shadowWidth,decisionBefore=explicitBefore?.decision??before.decision,decisionAfter=explicitAfter?.decision??after.decision,stateReduction=stateBefore!==null&&stateAfter!==null?Math.max(0,stateBefore-stateAfter):null,shadowWidthReduction=widthBefore!==null&&widthAfter!==null?Math.max(0,widthBefore-widthAfter):null,cost=nonNegativeOrNull(event.cost),decisionChanged=decisionBefore!==null&&decisionAfter!==null&&decisionBefore!==decisionAfter;
            events.push({recordId:record.id,round:Number(round.round)||null,toolType:event.toolType||event.toolGroup||event.type||event.source||"unknown",label:event.label||event.note||event.type||"情报",cost,stateBefore,stateAfter,widthBefore,widthAfter,stateReduction,shadowWidthReduction,decisionBefore,decisionAfter,decisionChanged,free:event.free===true});
          }
        }
      }
      const summarize=list=>{const n=list.length,avg=key=>{const values=list.map(x=>x[key]).filter(Number.isFinite);return values.length?mean(values):null;},knownCost=list.map(x=>x.cost).filter(Number.isFinite),changed=list.filter(x=>x.decisionChanged).length;return {n,stateReduction:avg("stateReduction"),shadowWidthReduction:avg("shadowWidthReduction"),decisionChangedRate:n?changed/n:null,totalCost:knownCost.length?knownCost.reduce((s,x)=>s+x,0):null,knownCostN:knownCost.length,freeN:list.filter(x=>x.free).length,events:list};};
      const groups=[...events.reduce((map,event)=>{if(!map.has(event.toolType))map.set(event.toolType,[]);map.get(event.toolType).push(event);return map;},new Map())].map(([toolType,list])=>({toolType,...summarize(list)}));
      return {status:events.length?"oos":"no-sample",n:events.length,...summarize(events),groups};
    }
    function informationValueHtml(summary){
      if(!summary||summary.status==="no-sample")return `<div class="v06-information-value"><h3 class="prob-calibration-subhead">信息价值 / ROI</h3><div class="empty-list">暂无带回合情报事件的样本；保存 R1/R3 等道具后会统计 State 收缩、Shadow 变窄和决策变化。</div></div>`;
      const money=v=>v==null?"—":fmtWan(v),num=v=>v==null?"—":Number(v).toFixed(2),pct=v=>v==null?"—":`${(v*100).toFixed(1)}%`,groupRows=summary.groups.map(g=>`<div class="prob-cal-row"><span><strong>${escapeHtml(g.toolType)}</strong> · n=${g.n}</span><b>State − ${num(g.stateReduction)}</b><b>Shadow − ${money(g.shadowWidthReduction)}</b><b>决策变化 ${pct(g.decisionChangedRate)}</b><small>成本 ${money(g.totalCost)} · 免费 ${g.freeN}</small></div>`).join("");
      return `<div class="v06-information-value"><h3 class="prob-calibration-subhead">信息价值 · n=${summary.n}</h3><div class="shadow-ab-grid"><div class="shadow-ab-cell shadow"><span>平均 State 收缩</span><strong>${num(summary.stateReduction)}</strong><small>事件前候选数 − 事件后候选数</small></div><div class="shadow-ab-cell shadow"><span>平均 Shadow 变窄</span><strong>${money(summary.shadowWidthReduction)}</strong><small>只统计能取得前后区间的样本</small></div><div class="shadow-ab-cell shadow"><span>决策变化率</span><strong>${pct(summary.decisionChangedRate)}</strong><small>Entry Decision 状态发生变化</small></div><div class="shadow-ab-cell shadow"><span>情报成本</span><strong>${money(summary.totalCost)}</strong><small>已明确成本 ${summary.knownCostN}/${summary.n} 条</small></div></div><h4 class="prob-calibration-subhead">按情报类型</h4><div class="prob-calibration-groups">${groupRows}</div><div class="field-help">信息价值是旁路诊断：它衡量新情报带来的候选收缩、区间收窄和决策翻转，不把“看到了信息”直接当成利润。</div></div>`;
    }
    function financeStatsV06(records=[]){
      const ordered=(records||[]).slice().sort((a,b)=>(historyTimestamp(a.playedAt)??Infinity)-(historyTimestamp(b.playedAt)??Infinity)||(Number(a.createdAt)||0)-(Number(b.createdAt)||0)),rows=[];let cumulative=0,peak=0,maxDrawdown=0,totalCosts=0,totalNet=0,knownCashflowN=0,investedBase=0,investedN=0;
      for(const record of ordered){const cost=recordTotalCost(record),margin=recordAcquisitionMargin(record),acquired=explicitBoolean(record?.acquired??record?.settlement?.acquired),spend=nonNegativeOrNull(record?.purchaseSpend??record?.settlement?.purchaseSpend),welfare=nonNegativeOrNull(record?.welfare?.received??record?.settlement?.welfare?.received)??0,cashflow=(margin??0)-cost+welfare;totalCosts+=cost;totalNet+=cashflow;knownCashflowN+=margin!==null||acquired===false?1:0;cumulative+=cashflow;peak=Math.max(peak,cumulative);maxDrawdown=Math.max(maxDrawdown,peak-cumulative);if(acquired===true&&spend!==null){investedBase+=spend+cost;investedN++;}else if(acquired===false&&cost>0){investedBase+=cost;investedN++;}rows.push({id:record.id,cashflow,cumulative,margin,cost,acquired});}
      const outcomes=ordered.map(r=>explicitBoolean(r?.acquired??r?.settlement?.acquired)).filter(v=>v!==null),acquiredRows=ordered.filter(r=>explicitBoolean(r?.acquired??r?.settlement?.acquired)===true),winRows=acquiredRows.filter(r=>{const m=recordAcquisitionMargin(r);return m!==null&&m>0;}),roi=investedBase>0?totalNet/investedBase:null;
      return {status:ordered.length?"ok":"no-sample",n:ordered.length,totalNet,totalCosts,knownCashflowN,investedBase,investedN,roi,maxDrawdown,cumulative,peak,acquisitionRate:outcomes.length?acquiredRows.length/outcomes.length:null,winRate:acquiredRows.length?winRows.length/acquiredRows.length:null,knownOutcomeN:outcomes.length,rows};
    }
    function financeStatsHtml(summary){
      if(!summary||summary.status==="no-sample")return `<div class="v06-finance-stats"><h3 class="prob-calibration-subhead">ROI / 最大回撤</h3><div class="empty-list">暂无可统计对局。</div></div>`;
      const money=v=>v==null?"—":fmtWan(v),pct=v=>v==null?"—":`${(v*100).toFixed(1)}%`;
      return `<div class="v06-finance-stats"><h3 class="prob-calibration-subhead">ROI / 资金曲线 · n=${summary.n}</h3><div class="shadow-ab-grid"><div class="shadow-ab-cell shadow"><span>累计场次现金流</span><strong>${money(summary.totalNet)}</strong><small>获取毛利 − 全部场次成本 + 福利实收</small></div><div class="shadow-ab-cell shadow"><span>ROI</span><strong>${pct(summary.roi)}</strong><small>净现金流 / 已知投入 ${money(summary.investedBase)}</small></div><div class="shadow-ab-cell shadow"><span>最大回撤</span><strong>${money(summary.maxDrawdown)}</strong><small>按时间累计现金流峰值回落</small></div><div class="shadow-ab-cell shadow"><span>成交率</span><strong>${pct(summary.acquisitionRate)}</strong><small>仅在明确是否拍下的样本中统计</small></div><div class="shadow-ab-cell shadow"><span>已拍胜率</span><strong>${pct(summary.winRate)}</strong><small>实际价值 − 支付价 &gt; 0</small></div><div class="shadow-ab-cell shadow"><span>成本覆盖</span><strong>${money(summary.totalCosts)}</strong><small>已知现金流口径 ${summary.knownCashflowN}/${summary.n}</small></div></div><div class="field-help">旧记录若没有明确“是否拍下/实际支付”，不会伪造获取毛利；其已记录成本仍进入现金流和最大回撤，因此 ROI 可能暂时偏保守。</div></div>`;
    }
    function renderAuditLabelSummary(rows){
      const el=document.getElementById("auditLabelPanel");if(!el)return;
      const labels=["State","Probability","History","Decision"],priority=["State","Probability","History","Decision","Normal"],counts=Object.fromEntries(priority.map(x=>[x,0]));
      rows.forEach(row=>{(row.diagnosticPriority||"Normal") in counts?counts[row.diagnosticPriority||"Normal"]++:counts.Normal++;});
      const tagged=rows.filter(row=>Object.values(row.diagnostic||{}).some(Boolean)).length;
      el.innerHTML=`<span class="dot"></span><div><strong>问题标签统计：</strong>${labels.map(label=>`${label} ${counts[label]}`).join(" · ")} · 正常/区间内 ${counts.Normal}。<small>这是诊断标签，不是互斥事实；若一局同时命中多个标签，独占归类优先级为 State → Probability → History → Decision → Normal。</small>${tagged?`<small>同时命中多个标签的局仍保留在各标签的非独占统计中；上面的数字是独占优先级归类。</small>`:""}</div>`;
    }
    function uniqueCalibrationGames(rows){
      const map=new Map();
      for(const row of rows||[]){
        const key=String(row.gameKey||row.id||`${row.playedAt||""}|${row.actualRedTotal||0}`),round=Number(row.round)||0,previous=map.get(key);
        // 同一局多回合使用最新可用快照作为“独立对局”代表；按 R 的明细仍单独保留。
        if(!previous||round>Number(previous.round||0))map.set(key,row);
      }
      return [...map.values()];
    }
    function probabilityCalibrationStats(rows){
      const eligible=(rows||[]).filter(x=>Number.isFinite(x.actualRedTotal)&&x.profile?.currentTotal&&Number.isFinite(x.profile.currentTotal.p20)&&Number.isFinite(x.profile.currentTotal.p80));
      const summarize=items=>{
        const list=uniqueCalibrationGames(items),n=list.length;if(!n)return {n:0,uniqueGames:0,p20p80:null,p10p90:null,p05p95:null,p10Games:0,p05Games:0,medianRank:null,medianP50Error:null,rows:[]};
        const coverage=(subset,lo,hi)=>subset.length?subset.filter(x=>x.actualRedTotal>=x.profile.currentTotal[lo]&&x.actualRedTotal<=x.profile.currentTotal[hi]).length/subset.length:null;
        const tail10=list.filter(x=>x.profile.currentDistribution?.tailP10Ready===true&&Number.isFinite(x.profile.currentTotal.p10)&&Number.isFinite(x.profile.currentTotal.p90)),tail05=list.filter(x=>x.profile.currentDistribution?.tailP95Ready===true&&Number.isFinite(x.profile.currentTotal.p05)&&Number.isFinite(x.profile.currentTotal.p95));
        const ranks=list.map(x=>{const p=x.profile.currentTotal,a=x.actualRedTotal;if(a<=p.p20)return .2;if(a<=p.p50)return .5;if(a<=p.p80)return .8;if(Number.isFinite(p.p90)&&a<=p.p90)return .9;return 1;}),modeCounts={};list.forEach(x=>{const mode=x.profile.currentDistribution?.mode||"unknown";modeCounts[mode]=(modeCounts[mode]||0)+1;});
        return {n,uniqueGames:n,p20p80:coverage(list,"p20","p80"),p10p90:n>=10&&tail10.length>=10?coverage(tail10,"p10","p90"):null,p05p95:n>=20&&tail05.length>=20?coverage(tail05,"p05","p95"):null,p10Games:tail10.length,p05Games:tail05.length,medianRank:median(ranks),medianP50Error:median(list.map(x=>x.actualRedTotal-(x.profile.currentTotal.p50??x.profile.currentTotal.p20))),distributionModes:modeCounts,rows:list};
      };
      const gameRows=uniqueCalibrationGames(eligible),groups=[{id:"R=1",test:x=>x.actualRedCount===1},{id:"R=2",test:x=>x.actualRedCount===2},{id:"R≥3",test:x=>x.actualRedCount>=3}].map(g=>({id:g.id,...summarize(gameRows.filter(g.test))}));
      const rounds=[1,2,3,4,5].map(round=>({id:`R${round}`,...summarize(eligible.filter(x=>Number(x.round)===round))}));
      return {all:summarize(gameRows),groups,rounds,uniqueGames:gameRows.length,roundRows:eligible.length,eligibleRaw:(rows||[]).length,rows:gameRows,rawRows:eligible};
    }
    function probabilityCalibrationRows(audit){
      const recordById=new Map(state.records.map(r=>[r.id,r])),out=[];
      for(const row of audit?.roundRows||[]){
        const record=recordById.get(row.id),label=historicalRedLabel(record),profile=row.probabilityProfile;
        if(!record||!label||!Number.isInteger(label.count)||!profile?.currentTotal)continue;
        // R>0 必须有与 R 完全一致的已识别红货列表；R=0 的红总价可由明确的 0 直接确认。
        if(label.count>0&&(!label.items?.length||label.items.length!==label.count||!Number.isFinite(label.total)))continue;
        const actualRedTotal=Number(label.total)||0;
        out.push({id:row.id,gameKey:row.id,round:row.round,actualRedTotal,actualRedCount:label.count,profile,source:profile.source||"",sampleItems:profile.sampleItems||0});
      }
      return out;
    }
    function renderProbabilityCalibration(audit){
      const el=document.getElementById("probabilityCalibrationPanel");if(!el)return;
      const rows=probabilityCalibrationRows(audit),summary=probabilityCalibrationStats(rows),fmtPct=v=>v==null?"—":`${(v*100).toFixed(0)}%`,fmtErr=v=>v==null?"—":`${v>=0?"+":"−"}${fmtWan(Math.abs(v))}`;
      if(!summary.uniqueGames){el.querySelector(".panel-body").innerHTML='<div class="empty-list">暂无可校准样本：需要结算后确认 R，并且红货名称/价格列表完整（R=0 可直接计入）。</div>';return;}
      const tailLabel=(g,key,threshold)=>{const available=key==="p10p90"?g.p10Games:g.p05Games;return g.n>=threshold&&available>=threshold&&g[key]!=null?fmtPct(g[key]):`样本不足（${available}/${threshold} 局）`;};
      const modeLabel={direct:"同R直接",bootstrap:"bootstrap组合",mixed:"直接+bootstrap",none:"无分布",unknown:"旧记录/未知"},modeSummary=g=>Object.entries(g.distributionModes||{}).map(([mode,n])=>`${modeLabel[mode]||mode} ${n}`).join(" · ")||"来源未知";
      const rowHtml=g=>`<div class="prob-cal-row"><span><strong>${g.id}</strong> · n=${g.n} 独立局</span><b>P20–P80 ${fmtPct(g.p20p80)}</b><b>P10–P90 ${tailLabel(g,"p10p90",10)}</b><b>P5–P95 ${tailLabel(g,"p05p95",20)}</b><small>${escapeHtml(modeSummary(g))} · 中位实际−P50 ${fmtErr(g.medianP50Error)}</small></div>`;
      el.querySelector(".panel-body").innerHTML=`<div class="prob-calibration-summary"><div><span>独立对局</span><strong>${summary.uniqueGames}</strong><small>逐回合可校准样本 ${summary.roundRows} · 原始回放行 ${summary.eligibleRaw}</small></div><div><span>红货 P20–P80 覆盖</span><strong>${fmtPct(summary.all.p20p80)}</strong><small>按独立对局去重，目标不是 100%</small></div><div><span>中位分位位置</span><strong>${summary.all.medianRank==null?"—":summary.all.medianRank.toFixed(2)}</strong><small>0.50 附近更平衡</small></div><div><span>中位实际−P50</span><strong>${fmtErr(summary.all.medianP50Error)}</strong><small>红总价口径，未改中心</small></div></div><h3 class="prob-calibration-subhead">按红数量（独立对局）</h3><div class="prob-calibration-groups">${summary.groups.map(rowHtml).join("")}</div><h3 class="prob-calibration-subhead">按 Round（每局每回合单独统计）</h3><div class="prob-calibration-groups prob-calibration-rounds">${summary.rounds.map(rowHtml).join("")||'<div class="empty-list">暂无按回合样本</div>'}</div><div class="field-help">总体独立对局取每局最新可用快照；R1–R5 明细保留逐回合视角。P10–P90 需要该分组至少 10 个独立对局，P5–P95 至少 20 个独立对局，并且这些对局的当前分布本身已经达到直接同 R 样本门槛；bootstrap/混合分布不冒充精确尾部。只统计可由结算证据可靠重建红总价的样本；不会反写预测，也不会参与 v0.3 中心/历史权重/倍率。</div>`;
    }
    function renderStatePriorEvaluationPanel(rows=[]){const el=document.getElementById("probabilityCalibrationPanel"),body=el?.querySelector(".panel-body");if(!body)return;body.querySelector(".v06-state-prior-eval")?.remove();body.insertAdjacentHTML("beforeend",statePriorEvaluationHtml(statePriorEvaluationV06(rows)));}
    function renderMarketOosEvaluationPanel(rows=[]){const el=document.getElementById("probabilityCalibrationPanel"),body=el?.querySelector(".panel-body");if(!body)return;body.querySelector(".v06-market-oos-eval")?.remove();body.insertAdjacentHTML("beforeend",marketOosEvaluationHtml(marketOosEvaluationV06(rows)));}
    function renderShadowOosEvaluationPanel(rows=[]){const el=document.getElementById("probabilityCalibrationPanel"),body=el?.querySelector(".panel-body");if(!body)return;body.querySelector(".v06-shadow-oos-eval")?.remove();body.insertAdjacentHTML("beforeend",shadowOosEvaluationHtml(shadowOosEvaluationV06(rows)));}
    const renderV04ValidationPanelV06Base=renderV04ValidationPanel;
    renderV04ValidationPanel=function(){renderV04ValidationPanelV06Base();const body=document.querySelector("#v04ValidationPanel .panel-body");if(!body)return;body.querySelector(".v06-information-value")?.remove();body.querySelector(".v06-finance-stats")?.remove();body.insertAdjacentHTML("beforeend",informationValueHtml(informationValueStatsV06(filteredRecords())));body.insertAdjacentHTML("beforeend",financeStatsHtml(financeStatsV06(filteredRecords())));};
    const renderStatePriorEvaluationPanelV06Base=renderStatePriorEvaluationPanel;
    renderStatePriorEvaluationPanel=function(rows=[]){renderStatePriorEvaluationPanelV06Base(rows);renderMarketOosEvaluationPanel(rows);renderShadowOosEvaluationPanel(rows);};
    const renderProbabilityCalibrationV06Base=renderProbabilityCalibration;
    renderProbabilityCalibration=function(audit={}){renderProbabilityCalibrationV06Base(audit);renderStatePriorEvaluationPanel(audit?.roundRows||[]);};
    function renderModelPanel(){
      const modeEl=document.getElementById("modeErrorPanel"),boxEl=document.getElementById("boxErrorPanel"),worstEl=document.getElementById("worstCasePanel");if(!modeEl||!boxEl||!worstEl)return;const audit=runDynamicWalkForwardAudit(),ids=new Set(filteredRecords().map(r=>r.id)),rows=audit.rows.filter(x=>ids.has(x.id));if(!rows.length){modeEl.innerHTML=boxEl.innerHTML=worstEl.innerHTML='<div class="empty-list">当前筛选没有可时序复放的结算样本</div>';renderAuditLabelSummary([]);renderProbabilityCalibration({roundRows:[]});return;}renderAuditLabelSummary(rows);renderProbabilityCalibration({roundRows:(audit.roundRows||[]).filter(x=>ids.has(x.id))});
      const modeLabels={onlyQ:"只有Q",goldAvgOnly:"Q+金均",goldAvgPurple:"Q+紫+金均",goldTotal:"金总",knownGold:"已知金藏品",knownRed:"已知红藏品",dualAvg:"双均价",noQ:"无Q",mixed:"混合"},modes=[...new Set(rows.map(x=>x.mode))].map(mode=>({mode,...auditStats(rows.filter(x=>x.mode===mode))})).sort((a,b)=>b.medianApe-a.medianApe),boxGroups=[...rows.reduce((m,x)=>{const key=x.box||"未知箱型";if(!m.has(key))m.set(key,[]);m.get(key).push(x);return m;},new Map())].map(([box,list])=>({box,...auditStats(list)})).filter(x=>x.n>=2).sort((a,b)=>b.medianApe-a.medianApe).slice(0,10),recordById=new Map(state.records.map(r=>[r.id,r])),worstRows=rows.slice().sort((a,b)=>b.ape-a.ape).slice(0,6),bar=(label,n,value)=>`<div class="rank-bar"><span title="${escapeHtml(label)}">${escapeHtml(label)} · n=${n}</span><div class="rank-track"><i style="width:${Math.min(100,Math.max(2,value*125)).toFixed(1)}%"></i></div><b>${(value*100).toFixed(1)}%</b></div>`;
      modeEl.innerHTML=`<div class="rank-bars">${modes.map(m=>bar(modeLabels[m.mode]||m.mode,m.n,m.medianApe)).join("")}</div>`;
      boxEl.innerHTML=`<div class="rank-bars">${boxGroups.map(m=>bar(m.box,m.n,m.medianApe)).join("")||'<div class="empty-list">同箱样本不足 2 局</div>'}</div>`;
      worstEl.innerHTML=`<div class="risk-list">${worstRows.map(x=>{const r=recordById.get(x.id)||{};return `<div class="risk-row"><span><strong>${escapeHtml(r.box||x.box||"未知箱型")}</strong><small>${escapeHtml((r.playedAt||x.playedAt||"").slice(0,16).replace("T"," "))} · ${escapeHtml(modeLabels[x.mode]||x.mode)}</small><small>${escapeHtml(historicalErrorExplanation(r,x.estimate))}</small></span><span class="risk-values"><b>${fmtWan(x.estimate)} → ${fmtWan(x.actual)}</b><small class="${x.bias>0?'profit-negative':'profit-positive'}">${x.bias>0?'多估':'少估'} ${Math.abs(x.bias*100).toFixed(1)}%</small></span></div>`;}).join("")}</div>`;
    }
    document.getElementById("exportJsonBtn").addEventListener("click",()=>download(`异环拍卖历史_${new Date().toISOString().slice(0,10)}.json`,JSON.stringify({...stateForPersistence(),exportedAt:new Date().toISOString()},null,2),"application/json"));
    const exportCsvCurrent=document.getElementById("exportCsvBtn");
    exportCsvCurrent.addEventListener("click",()=>{
      // 待识别结算只属于收件箱，不得混入训练/回测数据。
      const exportRecords=state.records.filter(r=>Number(r.actualTotal)>0&&r.settlement?.status!=="pending");
      const fields=["id","productVersion","playedAt","periodKey","role","character","venue","box","fieldCondition","avgValueBasis","privateBidCap","bidActionCount","q","goldAvg","goldTotal","goldCount","purpleCount","purpleAvg","minPurple","minGold","minRed","minBlue","minGreen","minWhite","knownPurple","knownGold","knownRed","decisionKnownRed","totalItems","totalGrid","goldGrid","purpleGrid","blueCount","blueGrid","blueAvg","greenCount","greenGrid","greenAvg","whiteCount","whiteGrid","whiteAvg","systemEstimate","singleAvg","nineAvg","publicNote","actualTotal","bid","highestPersonalBid","clearingPrice","purchaseSpend","acquired","resultReason","noBidReason","cost","targetProfit","outcome","winner","redCount","redInventoryComplete","settlementVerifiedRedItems","redItems","notes","source","legacy","solverVersion","solverStatus","inputHash","diagnosticOnly"],predictionFields=["modelVersion","solverStatus","inputHash","estimate","hardFloor","recommendedCap","balancedCap","conservativeLossLine","recommendedMaxBid","highRiskTrialLine","workingLow","workingHigh","estimateSource","estimateSampleSize","estimateConfidence","estimateFallbackLevel","highTierMin","highTierMax","redMin","redMax","goldInference","empiricalStatePrior","shadowCalibrated","marketPrediction","entryDecision","roundingMode","requestedRoundingMode","chosenRoundingMode","roundingAudit"],cols=[...fields,"acquisitionMargin","sessionCashflow","welfare","sparkle","intelEvents","settlementFieldCondition","settlementAvgValueBasis","costs","realizedState","counterfactual","roundCount","roundTimeline","screenshotCount","screenshotPaths","ocrEvidence","settlementWinner","settlementNote",...predictionFields,"componentBreakdown","candidateGs","candidatePs"],rows=exportRecords.map(r=>{const p=r.prediction||{};return [...fields.map(k=>r[k]),recordAcquisitionMargin(r),recordSessionCashflow(r),JSON.stringify(r.welfare||null),JSON.stringify(r.sparkle||null),JSON.stringify(r.intelEvents||[]),r.settlement?.fieldCondition||"",r.settlement?.avgValueBasis||"",JSON.stringify(r.costs||null),JSON.stringify(r.settlement?.realizedState||r.realizedState||null),JSON.stringify(staticCounterfactualForRecord(r)),r.rounds?.length||0,JSON.stringify(r.rounds||[]),r.screenshots?.length||0,(r.screenshots||[]).map(x=>x.path||x.name).join("|"),JSON.stringify(r.ocrEvidence||[]),r.settlement?.winner||"",r.settlement?.note||"",...predictionFields.map(k=>["roundingAudit","goldInference","empiricalStatePrior","shadowCalibrated","marketPrediction","entryDecision"].includes(k)?JSON.stringify(p[k]||null):p[k]),JSON.stringify(p.componentBreakdown||{}),(p.candidateGs||[]).join("|"),(p.candidatePs||[]).join("|")];}),csv=[cols,...rows].map(row=>row.map(x=>`"${String(x??"").replaceAll('"','""')}"`).join(",")).join("\n");download(`异环拍卖训练数据_v0.6_${new Date().toISOString().slice(0,10)}.csv`,`\ufeff${csv}`,"text/csv;charset=utf-8");
    });
    function download(name,content,type){const a=document.createElement("a"),url=URL.createObjectURL(new Blob([content],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    document.getElementById("importBtn").addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();document.getElementById("importFile").click();}});
    document.getElementById("importFile").addEventListener("change",async e=>{const file=e.target.files[0];if(!file)return;try{const clean=(await file.text()).replace(/^\uFEFF/,"").trim(),data=JSON.parse(clean),incoming=Array.isArray(data)?data:data.records;if(!Array.isArray(incoming))throw new Error("缺少 records 数组");const map=new Map(state.records.map(r=>[r.id,r]));incoming.forEach(r=>{if(r&&r.id){const old=map.get(r.id),next=normalizeRecord(r),shots=[...(old?.screenshots||[]),...(next.screenshots||[])],shotMap=new Map(shots.map(x=>[x.path||x.name,x]));map.set(r.id,normalizeRecord({...old,...next,screenshots:[...shotMap.values()]}));}});const inbox=[...(state.screenshotInbox||[]),...(Array.isArray(data?.screenshotInbox)?data.screenshotInbox:[])].filter(Boolean),inboxMap=new Map(inbox.map((x,i)=>[x.path||x.name||x.id||`inbox-${i}`,x]));state={...state,version:APP_VERSION,schemaVersion:SCHEMA_VERSION,records:[...map.values()],screenshotInbox:[...inboxMap.values()]};const cache=saveState();renderScreenshotInbox();renderReview();if(dataFileHandle)toast(`已合并 ${incoming.length} 条记录，正在写回已连接的数据文件`);else{setStorageStatus("已导入副本 · 未连接","syncing","导入不会自动覆盖原文件；请导出 JSON 或连接正式数据文件");toast(`已导入 ${incoming.length} 条记录；当前是浏览器副本，修改后请导出 JSON${cache.ok?"":"（本页内存模式）"}`);}}catch(error){console.warn("[import] JSON 导入失败",error);toast("导入失败：JSON 格式无效或缺少 records",true);}e.target.value="";});
    document.getElementById("clearHistoryBtn").addEventListener("click",()=>openConfirm("清空全部历史？","包括内置的旧版文档样本。建议先导出 JSON 备份。",()=>{state.records=[];saveState();renderReview();toast("历史已清空");}));

    function openConfirm(title,message,action){const t=document.getElementById("confirmTitle"),m=document.getElementById("confirmMessage"),d=document.getElementById("confirmDialog");if(!d){if(confirm(title+"\n"+message)&&action)action();return;}if(t)t.textContent=title;if(m)m.textContent=message;pendingConfirm=action;d.showModal();}
    (()=>{const ca=document.getElementById("confirmAction"),cd=document.getElementById("confirmDialog");if(ca&&cd){ca.addEventListener("click",()=>{cd.close();if(pendingConfirm)pendingConfirm();pendingConfirm=null;});}document.querySelectorAll("[data-close-dialog]").forEach(x=>x.addEventListener("click",()=>{const d=document.getElementById("confirmDialog");if(d)d.close();}));})();

    const _catSearch=document.getElementById("catalogSearch"); if(_catSearch)_catSearch.addEventListener("input",debounce(renderCatalog,100));
    document.querySelectorAll("#rarityChips .chip").forEach(btn=>btn.addEventListener("click",()=>{selectedRarity=btn.dataset.rarity;document.querySelectorAll("#rarityChips .chip").forEach(x=>x.classList.toggle("active",x===btn));renderCatalog();}));
    function renderCatalog(){const s=val("catalogSearch").toLowerCase(),items=ALL_ITEMS.filter(x=>(selectedRarity==="all"||x.rarity===selectedRarity)&&(!s||`${x.name} ${x.price} ${x.size}`.toLowerCase().includes(s))).sort((a,b)=>b.price-a.price);document.getElementById("catalogGrid").innerHTML=items.map(x=>`<article class="item-card ${x.rarity}"><h4 title="${escapeHtml(x.name)}">${escapeHtml(x.name)}</h4><strong>${fmt(x.price)}</strong><small>${x.size}</small></article>`).join("");}

    /* Local catalog source -> pending visual templates. This layer is deliberately
       separate from ALL_ITEMS/State Inference: uncertain OCR never changes the
       formal price catalog or a frozen settlement snapshot. */
    function catalogQualityFromPath(path=""){
      const p=String(path).toLowerCase();
      if(/(^|[\\/._-])(red|hong|红)([\\/._-]|$)/.test(p)||p.includes("红色"))return "red";
      if(/(^|[\\/._-])(gold|jin|金)([\\/._-]|$)/.test(p)||p.includes("金色"))return "gold";
      if(/(^|[\\/._-])(purple|zi|紫)([\\/._-]|$)/.test(p)||p.includes("紫色"))return "purple";
      if(/(^|[\\/._-])(blue|lan|蓝)([\\/._-]|$)/.test(p)||p.includes("蓝色"))return "blue";
      if(/(^|[\\/._-])(green|lv|绿)([\\/._-]|$)/.test(p)||p.includes("绿色"))return "green";
      if(/(^|[\\/._-])(white|bai|白)([\\/._-]|$)/.test(p)||p.includes("白色"))return "white";
      return "unknown";
    }
    function catalogHash(text="") { let h=2166136261; for(const ch of String(text)){h^=ch.charCodeAt(0);h=Math.imul(h,16777619);} return (h>>>0).toString(16).padStart(8,"0"); }
    function catalogFilenameFacts(path=""){
      const base=String(path).split(/[\\/]/).pop().replace(/\.[^.]+$/i,"").trim(),priceMatch=base.match(/(?:^|[^\d])(\d{3,9})(?:[^\d]|$)/),price=priceMatch?Number(priceMatch[1]):null;
      const cleaned=base.replace(/(?:^|[^\d])\d{3,9}(?:[^\d]|$)/g," ").replace(/[【】\[\]\(\)_-]+/g," ").trim();
      const generic=!cleaned||/^(screenshot|image|img|截图|图鉴|卡片|未命名|微信图片|pxl)/i.test(cleaned);
      return {name:generic?null:cleaned,price:Number.isFinite(price)?price:null};
    }
    function catalogImageDescriptor(canvas,size=16){
      const small=document.createElement("canvas");small.width=size;small.height=size;const c=small.getContext("2d");c.drawImage(canvas,0,0,size,size);const data=c.getImageData(0,0,size,size).data,out=[];for(let i=0;i<data.length;i+=4){out.push(data[i],data[i+1],data[i+2]);}return out;
    }
    function catalogDescriptorDistance(a,b){if(!Array.isArray(a)||!Array.isArray(b)||!a.length||a.length!==b.length)return Infinity;let sum=0;for(let i=0;i<a.length;i++)sum+=Math.abs(Number(a[i])-Number(b[i]));return sum/(a.length*255);}
    function loadCatalogImage(file){return new Promise((resolve,reject)=>{const url=URL.createObjectURL(file),img=new Image();img.onload=()=>{URL.revokeObjectURL(url);resolve(img);};img.onerror=()=>{URL.revokeObjectURL(url);reject(new Error("图片读取失败"));};img.src=url;});}
    function canvasFromImage(img,x=0,y=0,w=img.naturalWidth||img.width,h=img.naturalHeight||img.height,maxSide=240){const scale=Math.min(1,maxSide/Math.max(w,h));const canvas=document.createElement("canvas");canvas.width=Math.max(1,Math.round(w*scale));canvas.height=Math.max(1,Math.round(h*scale));canvas.getContext("2d").drawImage(img,x,y,w,h,0,0,canvas.width,canvas.height);return canvas;}
    function cropCatalogSource(img,path=""){
      const w=img.naturalWidth||img.width,h=img.naturalHeight||img.height,base=String(path).split(/[\\/]/).pop(),facts=catalogFilenameFacts(path);
      // 文件名已带藏品名/价格时，整张图往往就是单卡；否则保守切 2×N 候选并全部待确认。
      if(facts.name||facts.price)return [{canvas:canvasFromImage(img,0,0,w,h),index:1}];
      const cols=w>=h*1.15?2:1,rows=Math.max(1,Math.min(10,Math.round(h/(w/cols*.62)))),out=[];
      for(let row=0;row<rows;row++)for(let col=0;col<cols;col++){const x=Math.round(col*w/cols),y=Math.round(row*h/rows),cw=Math.round(w/cols),ch=Math.round(h/rows),mx=Math.round(cw*.04),my=Math.round(ch*.04);out.push({canvas:canvasFromImage(img,x+mx,y+my,Math.max(1,cw-2*mx),Math.max(1,ch-2*my)),index:row*cols+col+1});}
      return out.slice(0,24);
    }
    function saveCatalogSources(){try{localStorage.setItem(CATALOG_SOURCE_KEY,JSON.stringify(catalogSourceEntries));}catch(error){toast("图鉴待确认模板过多，浏览器空间不足；请先导出 catalog.json",true);}}
    let catalogOcrWorker=null,catalogOcrPromise=null,catalogOcrJobs=0,catalogOcrBudget=24;
    async function catalogBestEffortOcr(canvas){
      // OCR is deliberately advisory. The existing settlement OCR worker is
      // number-only; catalog OCR may try chi_sim+eng when the language pack is
      // available, but failures simply leave the entry in pending review.
      try{
        const T=await loadTesseract();
        if(!catalogOcrWorker){if(catalogOcrPromise)return catalogOcrPromise.then(()=>catalogBestEffortOcr(canvas));catalogOcrPromise=(async()=>{catalogOcrWorker=await T.createWorker("chi_sim+eng",1);await catalogOcrWorker.setParameters({preserve_interword_spaces:"1"});})();try{await catalogOcrPromise;}finally{catalogOcrPromise=null;}}
        const result=await catalogOcrWorker.recognize(canvas),text=String(result?.data?.text||"").replace(/\s+/g," ").trim(),confidence=Math.max(0,Math.min(1,Number(result?.data?.confidence||0)/100)),priceMatch=text.match(/(?:^|[^\d])(\d{3,9})(?:[^\d]|$)/),price=priceMatch?Number(priceMatch[1]):null,name=text.replace(/\b\d{3,9}\b/g," ").replace(/\s+/g," ").trim();
        return {text,name:name||null,price:Number.isFinite(price)?price:null,confidence};
      }catch(error){return {text:"",name:null,price:null,confidence:0,error:String(error?.message||error)};}
    }
    async function catalogEnrichOcr(entry,canvas){
      if(entry.name&&entry.price)return;
      // A folder can contain dozens of source screenshots.  OCR is advisory
      // and may load a language model, so keep the import bounded; entries
      // beyond the budget remain pending instead of blocking the live page.
      if(catalogOcrJobs>=catalogOcrBudget){entry.ocrStatus="OCR budget reached · 待人工";return;}
      catalogOcrJobs++;
      try{
      const ocr=await catalogBestEffortOcr(canvas);if(!ocr)return;const live=catalogSourceEntries.find(x=>x.id===entry.id);if(!live)return;
      if(ocr.name&&ocr.confidence>=.45&&!live.name)live.name=ocr.name;if(Number.isFinite(ocr.price)&&!live.price)live.price=ocr.price;live.ocrText=ocr.text||null;live.ocrConfidence=Math.max(Number(live.ocrConfidence)||0,ocr.confidence);live.ocrStatus=ocr.error?"OCR unavailable · 待人工":"OCR best-effort · 待人工确认";saveCatalogSources();renderCatalogSources();
      }finally{catalogOcrJobs=Math.max(0,catalogOcrJobs-1);}
    }
    function renderCatalogSources(){
      const status=document.getElementById("catalogSourceStatus"),list=document.getElementById("catalogPendingList");if(!status||!list)return;const pending=catalogSourceEntries.filter(x=>x.status!=="verified"),verified=catalogSourceEntries.filter(x=>x.status==="verified");status.innerHTML=`<span class="dot"></span><div>待确认 ${pending.length} 条 · 已确认视觉模板 ${verified.length} 条。${pending.length?"待确认条目不会进入正式图鉴/结算自动填写。":"可导入新的源截图继续扩充。"}</div>`;
      list.innerHTML=pending.slice(-80).reverse().map(entry=>`<article class="catalog-pending-card"><img src="${entry.templateDataUrl||""}" alt="待确认模板"><h4 title="${escapeHtml(entry.sourceScreenshot||entry.id)}">${escapeHtml(entry.name||"名称待 OCR / 人工确认")}</h4><p>${escapeHtml(entry.quality||"unknown")} · ${entry.price?fmt(entry.price):"价格待 OCR"} · OCR ${Math.round(Number(entry.ocrConfidence||0)*100)}% · ${escapeHtml(entry.sourceScreenshot||"")}</p><p>${entry.footprint?`尺寸 ${escapeHtml(entry.footprint)}`:"尺寸待确认"} · ${entry.autoCrop?"自动裁卡候选":"源图"}</p><button type="button" class="btn" data-catalog-verify="${entry.id}">确认加入视觉图鉴</button></article>`).join("")||'<div class="empty-list">暂无待确认条目</div>';
    }
    async function scanCatalogSourceFiles(files){
      const status=document.getElementById("catalogSourceStatus"),list=[...files||[]].filter(f=>/^image\//.test(f.type));if(!list.length){toast("请选择图鉴截图文件或文件夹",true);return;}
      if(status)status.innerHTML='<span class="dot"></span><div>正在裁卡并建立本地视觉描述… OCR 只做最佳努力，结果会先进入待确认。</div>';
      const added=[];catalogOcrBudget=24;const entryCap=240;
      for(const file of list.slice(0,80)){
        if(added.length>=entryCap)break;
        try{const img=await loadCatalogImage(file),path=file.webkitRelativePath||file.name,quality=catalogQualityFromPath(path),facts=catalogFilenameFacts(path),crops=cropCatalogSource(img,path);for(const crop of crops){if(added.length>=entryCap)break;const id=`cat-${catalogHash(`${quality}|${path}|${crop.index}`)}`,templateDataUrl=crop.canvas.toDataURL("image/jpeg",.78),entry={id,name:facts.name||null,quality,price:facts.price||null,grid:null,footprint:null,sourceScreenshot:path,sourceFileName:file.name,templateDataUrl,descriptor:catalogImageDescriptor(crop.canvas),ocrConfidence:facts.name||facts.price?.toString()?0.45:0.08,ocrStatus:"best-effort-pending",autoCrop:crops.length>1,sourceWidth:img.naturalWidth||img.width,sourceHeight:img.naturalHeight||img.height,status:"pending",createdAt:new Date().toISOString()};const existing=catalogSourceEntries.findIndex(x=>x.id===id);if(existing>=0)catalogSourceEntries[existing]={...catalogSourceEntries[existing],...entry};else{catalogSourceEntries.push(entry);added.push(entry);}if(!facts.name||!facts.price)void catalogEnrichOcr(entry,crop.canvas);}}catch(error){console.warn("catalog source",file.name,error);}}
      saveCatalogSources();renderCatalogSources();if(status&&added.length)toast(`已生成 ${added.length} 条待确认视觉模板；未自动写入正式图鉴`);else if(status)status.innerHTML='<span class="dot"></span><div>没有生成可用候选，请检查图片格式或文件夹品质命名。</div>';
    }
    function exportCatalogJson(){const strip=({descriptor,...x})=>({...x,descriptor:descriptor||null}),entries=catalogSourceEntries.filter(x=>x.status==="verified").map(strip),pending=catalogSourceEntries.filter(x=>x.status!=="verified").map(strip),payload={version:"v0.4-visual-catalog",generatedAt:new Date().toISOString(),entries,pending};download("catalog.json",JSON.stringify(payload,null,2),"application/json");toast(`已导出 catalog.json：正式 ${entries.length} 条 · 待确认 ${pending.length} 条`);}
    function verifyCatalogEntry(id){const entry=catalogSourceEntries.find(x=>x.id===id);if(!entry)return;entry.status="verified";entry.verifiedAt=new Date().toISOString();saveCatalogSources();renderCatalogSources();toast("已加入本地视觉图鉴；不会改变价格/State Inference");}
    function warehouseInventoryTiles(img){const w=img.naturalWidth||img.width,h=img.naturalHeight||img.height,x0=Math.round(w*.54),y0=Math.round(h*.14),rw=w-x0,rh=Math.round(h*.68),cols=10,rows=8,out=[];for(let row=0;row<rows;row++)for(let col=0;col<cols;col++){const x=x0+Math.round(col*rw/cols),y=y0+Math.round(row*rh/rows),cw=Math.round(rw/cols),ch=Math.round(rh/rows),canvas=canvasFromImage(img,x,y,cw,ch,120),d=canvas.getContext("2d").getImageData(0,0,canvas.width,canvas.height).data;let sum=0,variance=0;for(let i=0;i<d.length;i+=4){const v=(d[i]+d[i+1]+d[i+2])/3;sum+=v;}const mean=sum/(d.length/4);if(mean<13)continue;out.push({canvas,descriptor:catalogImageDescriptor(canvas),row,col,mean});}return out;}
    async function runWarehouseVisualMatch(file){const mount=document.getElementById("warehouseMatchResults");if(!mount||!file)return;const templates=catalogSourceEntries.filter(x=>x.status==="verified"&&Array.isArray(x.descriptor)&&x.descriptor.length);if(!templates.length){mount.innerHTML='<div class="probability-empty">尚无已确认视觉模板。先扫描源截图并点击“确认加入视觉图鉴”；当前不会猜名称，也不会写入 settlement。</div>';return;}mount.innerHTML='<div class="probability-empty">正在按仓库 viewport 网格提取候选…</div>';try{const img=await loadCatalogImage(file),tiles=warehouseInventoryTiles(img),matches=[];for(const tile of tiles){const top=templates.map(t=>({...t,distance:catalogDescriptorDistance(tile.descriptor,t.descriptor)})).sort((a,b)=>a.distance-b.distance).slice(0,3);if(top[0]&&top[0].distance<.48)matches.push({tile,top});}matches.sort((a,b)=>a.top[0].distance-b.top[0].distance);mount.innerHTML=matches.slice(0,12).map((m,i)=>{const best=m.top[0],confidence=Math.max(0,1-best.distance),cands=m.top.map(x=>`${escapeHtml(x.name||"待确认卡片")}（${escapeHtml(x.quality)} · ${Math.round(Math.max(0,1-x.distance)*100)}%）`).join(" / ");return `<div class="warehouse-match-card"><strong>仓库候选 ${i+1} · ${escapeHtml(best.quality)} · ${confidence>=.72?"可供人工确认":"低置信度"}</strong><small>Top-K：${cands}<br>这是 T2 识别预览；重复 viewport、数量和 settlement 均不自动写入。</small></div>`;}).join("")||'<div class="probability-empty">未找到足够相似的非空仓库格；可先确认更多模板，或保留截图交给后续 AI/人工复核。</div>';}catch(error){console.error(error);mount.innerHTML=`<div class="probability-empty">视觉匹配失败：${escapeHtml(error.message||error)}</div>`;}}
    const catalogScanBtn=document.getElementById("catalogScanBtn");if(catalogScanBtn)catalogScanBtn.addEventListener("click",()=>scanCatalogSourceFiles(document.getElementById("catalogSourceFiles")?.files));
    const catalogExportBtn=document.getElementById("catalogExportBtn");if(catalogExportBtn)catalogExportBtn.addEventListener("click",exportCatalogJson);
    const catalogSourceFiles=document.getElementById("catalogSourceFiles");if(catalogSourceFiles)catalogSourceFiles.addEventListener("change",()=>{if(catalogSourceFiles.files?.length)scanCatalogSourceFiles(catalogSourceFiles.files);});
    document.addEventListener("click",ev=>{const btn=ev.target.closest?.("[data-catalog-verify]");if(btn)verifyCatalogEntry(btn.dataset.catalogVerify);});
    const warehouseMatchBtn=document.getElementById("warehouseMatchBtn");if(warehouseMatchBtn)warehouseMatchBtn.addEventListener("click",()=>runWarehouseVisualMatch(document.getElementById("warehouseMatchFile")?.files?.[0]));

    onEl("calcFieldCondition","change",syncFieldConditionUi);
    onEl("coreConditionStatus","click",()=>{showCalcSection("setup");document.getElementById("calcFieldCondition")?.focus();});
    for(const id of ["resultWelfareBase","resultWelfareRate"])onEl(id,"input",()=>syncWelfareInputs("result"));
    onEl("recordFieldCondition","change",()=>{const fieldCondition=canonicalFieldConditionId(val("recordFieldCondition"));if(["purpleDouble","goldDouble"].includes(fieldCondition)&&val("recordAvgValueBasis")==="unknown")setVal("recordAvgValueBasis","effective");if(fieldCondition==="welfare"&&!val("recordWelfareRate"))setVal("recordWelfareRate",.30);syncWelfareInputs("record");});
    for(const id of ["recordWelfareBase","recordWelfareRate"])onEl(id,"input",()=>syncWelfareInputs("record"));
    window.runV05ConditionDataSelfTest=function(){
      const before=normalizeRecord({id:"v05-before",playedAt:"2026-08-12T12:00",actualTotal:100});
      const after=normalizeRecord({id:"v05-after",playedAt:"2026-08-13T12:00",actualTotal:100});
      const undated=normalizeRecord({id:"v05-undated",actualTotal:100});
      const events=conditionIntelEvents("extraIntel",1,"测试情报");
      const source={id:"v05-roundtrip",productVersion:"v0.5",playedAt:"2026-08-14T12:00",fieldCondition:"goldDouble",avgValueBasis:"base",privateBidCap:321000,bidActionCount:4,actualTotal:500000,acquired:true,purchaseSpend:300000,costs:{entry:5000,info:50000,other:0},welfare:{base:100000,rate:.3,expected:30000,received:24000},sparkle:{transformedOneByOneCount:3,verifiedGemItems:"泪滴*2 + 永恒之心",complete:true},intelEvents:events,rounds:[{round:1,fieldCondition:"goldDouble",avgValueBasis:"base",privateBidCap:321000,bidActionCount:4,intelEvents:events,prediction:{fieldCondition:"goldDouble",avgValueBasis:"base",intelEvents:events}}],prediction:{fieldCondition:"goldDouble",avgValueBasis:"base",intelEvents:events},settlement:{fieldCondition:"goldDouble",avgValueBasis:"base",privateBidCap:321000,bidActionCount:4,welfare:{base:100000,rate:.3,expected:30000,received:24000},sparkle:{transformedOneByOneCount:3,verifiedGemItems:"泪滴*2 + 永恒之心",complete:true},intelEvents:events}};
      const roundtrip=normalizeRecord(JSON.parse(JSON.stringify(source))),actualBefore=roundtrip.actualTotal,cash=recordSessionCashflow(roundtrip),badSparkle=normalizeRecord({id:"v05-bad-sparkle",playedAt:"2026-08-14T12:00",fieldCondition:"sparkle",sparkle:{transformedOneByOneCount:2,verifiedGemItems:"泪滴 + 不存在宝石",complete:true}});
      const checks={pre0813Standard:before.fieldCondition==="standard",post0813Unknown:after.fieldCondition==="unknown",undatedUnknown:undated.fieldCondition==="unknown",freeIntel:events.length===1&&events[0].free===true&&events[0].cost===0,conditionRoundtrip:roundtrip.fieldCondition==="goldDouble"&&roundtrip.rounds[0].fieldCondition==="goldDouble"&&roundtrip.prediction.fieldCondition==="goldDouble"&&roundtrip.settlement.fieldCondition==="goldDouble",avgBasisRoundtrip:roundtrip.avgValueBasis==="base"&&roundtrip.rounds[0].avgValueBasis==="base"&&roundtrip.settlement.avgValueBasis==="base",darkFields:roundtrip.privateBidCap===321000&&roundtrip.bidActionCount===4,welfareCashflowOnce:cash===169000&&roundtrip.actualTotal===actualBefore&&actualBefore===500000,sparkleRoundtrip:roundtrip.sparkle.transformedOneByOneCount===3&&roundtrip.sparkle.complete===true,sparkleInvalidDowngraded:badSparkle.sparkle.complete===false&&!!badSparkle.sparkle.validationError};
      return {pass:Object.values(checks).every(Boolean),checks};
    };

    /* SAFE BOOT: browser Lab only. Node compute requires the exports below and must not touch DOM. */
    const __solverCoreIsNode = typeof process !== "undefined" && !!(process.versions && process.versions.node);
    if (!__solverCoreIsNode) try {
      setupVenueBoxPair("calcVenue","calcBox");
      setupVenueBoxPair("recordVenue","recordBox");
      // force middle venue boxes if still empty
      const box=document.getElementById("calcBox");
      const venue=document.getElementById("calcVenue");
      if(venue){
        if(!venue.value || venue.value==="未知场地") venue.value="中级场 · 珊瑚场";
        fillBoxOptions("calcVenue","calcBox");
      }
      const rVenue=document.getElementById("recordVenue");
      if(rVenue){
        if(!rVenue.value || rVenue.value==="未知场地") rVenue.value="中级场 · 珊瑚场";
        fillBoxOptions("recordVenue","recordBox");
      }
      if(box) console.log("[boot] calcBox options", box.options.length, Array.from(box.options).map(o=>o.value));
      setVal("calcPlayedAt",nowLocalInput());
      setCalcRound(1);
      syncFieldConditionUi();
      renderCalcRedState();
      renderCurrentGameEvidence();
      resetRecordForm();
      renderScreenshotInbox();
      renderRecordScreenshotSummary();
      restoreDataHandle();
      renderCatalog();
      renderCatalogSources();
      showCalcSection("core");
      // Keep a non-visual, read-only probe on the document so a browser QA
      // pass can verify State -> Probability linkage without adding another
      // control to the live workflow. The probe uses temporary in-memory rows
      // and restores the user's history before returning.
      try{document.documentElement.dataset.probabilityLinkageSelfTest=JSON.stringify(probabilityLinkageSelfTest());}catch(probeError){console.warn("probability linkage self-test",probeError);}
      try{document.documentElement.dataset.constraintV04SelfTest=JSON.stringify(runConstraintV04SelfTests());}catch(probeError){console.warn("constraint v0.4 self-test",probeError);}
      try{document.documentElement.dataset.fieldConditionV05SelfTest=JSON.stringify(runFieldConditionV05SelfTests());}catch(probeError){console.warn("field condition v0.5 self-test",probeError);}
      try{document.documentElement.dataset.dataModelV04SelfTest=JSON.stringify(window.runV04DataModelSelfTest());}catch(probeError){console.warn("data model v0.4 self-test",probeError);}
      try{document.documentElement.dataset.dataFileV04SelfTest=JSON.stringify(window.runDataFileV04SelfTest());}catch(probeError){console.warn("data file v0.4 self-test",probeError);}
      try{document.documentElement.dataset.conditionDataV05SelfTest=JSON.stringify(window.runV05ConditionDataSelfTest());}catch(probeError){console.warn("condition data v0.5 self-test",probeError);}
      try{document.documentElement.dataset.v06ReliabilitySelfTest=JSON.stringify(window.runV06ReliabilitySelfTests());}catch(probeError){console.warn("v0.6 reliability self-test",probeError);}
      void window.runV06AsyncRaceSelfTest().then(result=>{document.documentElement.dataset.v06AsyncRaceSelfTest=JSON.stringify(result);}).catch(probeError=>console.warn("v0.6 async race self-test",probeError));
      try{document.documentElement.dataset.v052BacktestSelfTest=JSON.stringify(window.runV052BacktestSelfTests());}catch(probeError){console.warn("v0.5.2 backtest self-test",probeError);}
      try{document.documentElement.dataset.v06ShadowSelfTest=JSON.stringify(window.runV06ShadowSelfTests());}catch(probeError){console.warn("v0.6 shadow self-test",probeError);}
      try{document.documentElement.dataset.v06MarketSelfTest=JSON.stringify(window.runV06MarketSelfTests());}catch(probeError){console.warn("v0.6 market self-test",probeError);}
      try{document.documentElement.dataset.v06AnalyticsSelfTest=JSON.stringify(window.runV06AnalyticsSelfTests());}catch(probeError){console.warn("v0.6 analytics self-test",probeError);}
    } catch(err) {
      console.error(err);
      try{toast("初始化部分失败: "+err.message,true);}catch(_){alert("初始化失败: "+err.message);}
    }

    (function exportSolverCoreApi(){
      const api = {
        redProbabilityProfile,
        stateComponents,
        candidateStateWeight,
        expandStatesForValuation,
        resolveKnownCatalogItem,
        getState: function(){ return state; }
      };
      if (typeof globalThis !== "undefined") {
        globalThis.redProbabilityProfile = redProbabilityProfile;
        globalThis.stateComponents = stateComponents;
        globalThis.candidateStateWeight = candidateStateWeight;
        globalThis.expandStatesForValuation = expandStatesForValuation;
        globalThis.state = state;
      }
      if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
      }
    })();
