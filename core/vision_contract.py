"""
Neverness to Everness (异环) - 视觉观测契约 (Vision Observation Contract - v0.65)

规范化视觉管道向 Brain / Solver / Archiver 输出的标准化观测数据模型：
1. 元数据 (时间戳、分辨率、置信度)
2. 局况与规则 (Venue, BoxType, FieldCondition, Round, Timer)
3. 动态情报 (Q, Avg, Grids, 已知藏品)
4. 4人博弈叫价 (MyBid, LeaderBid, Opponents)
5. 终局结算 (ClearingPrice, ActualTotal, SettlementItems)
"""

import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple

@dataclass
class VisionIntel:
    type: str = "none" # "q", "goldAvg", "purpleAvg", "totalItems", "grids", "shape", "none"
    q: Optional[int] = None
    totalItems: Optional[int] = None
    goldAvg: Optional[int] = None
    purpleAvg: Optional[int] = None
    blueAvg: Optional[int] = None
    greenAvg: Optional[int] = None
    whiteAvg: Optional[int] = None
    redAvg: Optional[int] = None
    avg: Optional[int] = None
    purple: Optional[int] = None
    purpleCount: Optional[int] = None
    goldCount: Optional[int] = None
    blueCount: Optional[int] = None
    greenCount: Optional[int] = None
    whiteCount: Optional[int] = None
    redCount: Optional[int] = None
    currentEstimate: Optional[int] = None
    totalGrids: Optional[int] = None
    goldGrid: Optional[int] = None
    purpleGrid: Optional[int] = None
    blueGrid: Optional[int] = None
    greenGrid: Optional[int] = None
    whiteGrid: Optional[int] = None
    redGrid: Optional[int] = None
    knownGold: List[str] = field(default_factory=list)
    knownPurple: List[str] = field(default_factory=list)
    knownRed: List[str] = field(default_factory=list)
    rawText: str = ""
    confidence: float = 1.0

@dataclass
class VisionBids:
    myBid: int = 0
    myName: str = "玩家本人"
    leaderBid: int = 0
    leaderName: Optional[str] = None
    isMyLead: bool = False
    opponents: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class VisionSettlement:
    isSettlement: bool = False
    clearingPrice: Optional[int] = None
    actualTotal: Optional[int] = None
    profit: Optional[int] = None
    items: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0

@dataclass
class VisionObservation:
    timestamp: float = field(default_factory=time.time)
    frameIndex: int = 0
    sourceResolution: Tuple[int, int] = (1920, 1080)
    venue: str = "未知场地"
    box: str = "未知箱型"
    fieldCondition: str = "unknown"
    character: Optional[str] = None
    lobbyToolGroup: Optional[str] = None
    solverToolGroup: Optional[str] = None
    toolGroup: Optional[str] = None
    boxType: Optional[str] = None  # 兼容旧测试，不得作为 SoT
    round: int = 1
    timer: int = 15
    intel: VisionIntel = field(default_factory=VisionIntel)
    bids: VisionBids = field(default_factory=VisionBids)
    settlement: VisionSettlement = field(default_factory=VisionSettlement)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_pipeline_context(cls, ctx: Dict[str, Any], frame_index: int = 0, resolution: Tuple[int, int] = (1920, 1080)) -> 'VisionObservation':
        """将 NTEVisionPipeline 旧版 context 转换为标准化的 VisionObservation 契约对象"""
        intel_type = "none"
        if ctx.get("goldAvg") is not None or ctx.get("avg") is not None:
            intel_type = "goldAvg"
        elif ctx.get("purpleAvg") is not None:
            intel_type = "purpleAvg"
        elif ctx.get("totalItems") is not None:
            intel_type = "totalItems"
        elif ctx.get("q") is not None:
            intel_type = "q"
        elif ctx.get("totalGrids") is not None:
            intel_type = "grids"

        gold_avg = ctx.get("goldAvg")
        purple_cnt = ctx.get("purpleCount") if ctx.get("purpleCount") is not None else ctx.get("purple")

        intel = VisionIntel(
            type=intel_type,
            q=ctx.get("q"),
            totalItems=ctx.get("totalItems"),
            goldAvg=gold_avg,
            purpleAvg=ctx.get("purpleAvg"),
            blueAvg=ctx.get("blueAvg"),
            greenAvg=ctx.get("greenAvg"),
            whiteAvg=ctx.get("whiteAvg"),
            redAvg=ctx.get("redAvg"),
            avg=ctx.get("avg"),
            purple=purple_cnt,
            purpleCount=purple_cnt,
            goldCount=ctx.get("goldCount"),
            blueCount=ctx.get("blueCount"),
            currentEstimate=ctx.get("currentEstimate"),
            totalGrids=ctx.get("totalGrids"),
            knownGold=ctx.get("knownGold", []) or [],
            knownPurple=ctx.get("knownPurple", []) or [],
            knownRed=ctx.get("knownRed", []) or [],
            rawText=ctx.get("rawText", ""),
            confidence=1.0
        )

        bids = VisionBids(
            myBid=ctx.get("myBid", 0),
            myName=ctx.get("myName", "玩家本人"),
            leaderBid=ctx.get("currentLeaderBid", ctx.get("leaderBid", 0)),
            leaderName=ctx.get("leaderName"),
            isMyLead=ctx.get("isMyLead", False),
            opponents=ctx.get("opponents", []) or []
        )

        settlement_raw = ctx.get("settlementData") or {}
        settlement = VisionSettlement(
            isSettlement=bool(ctx.get("isSettlement") or settlement_raw.get("isSettlement")),
            clearingPrice=settlement_raw.get("clearingPrice"),
            actualTotal=settlement_raw.get("actualTotal"),
            profit=settlement_raw.get("profit"),
            items=settlement_raw.get("items", []) or [],
            confidence=1.0
        )

        solver_tool = ctx.get("solverToolGroup") or ctx.get("toolGroup")

        return cls(
            timestamp=time.time(),
            frameIndex=frame_index,
            sourceResolution=resolution,
            venue=ctx.get("venue") or "未知场地",
            box=ctx.get("box") or "未知箱型",
            fieldCondition=ctx.get("fieldCondition") or "unknown",
            character=ctx.get("character") or ctx.get("lobbyCharacter"),
            lobbyToolGroup=ctx.get("lobbyToolGroup"),
            solverToolGroup=solver_tool,
            toolGroup=solver_tool,
            boxType=ctx.get("boxType"),
            round=max(1, min(5, int(ctx.get("round", 1) or 1))),
            timer=max(0, int(ctx.get("timer", 15) or 0)),
            intel=intel,
            bids=bids,
            settlement=settlement,
            confidence=1.0
        )

    def validate(self) -> Tuple[bool, List[str]]:
        """契约完备性校验"""
        errors = []
        if not (1 <= self.round <= 5):
            errors.append(f"Invalid round: {self.round}")
        if self.timer < 0:
            errors.append(f"Invalid timer: {self.timer}")
        if self.bids.myBid < 0:
            errors.append(f"Invalid myBid: {self.bids.myBid}")
        if self.bids.leaderBid < 0:
            errors.append(f"Invalid leaderBid: {self.bids.leaderBid}")
        if self.settlement.isSettlement:
            if self.settlement.clearingPrice is None or self.settlement.clearingPrice <= 0:
                errors.append("Settlement must have positive clearingPrice")
            if self.settlement.actualTotal is None or self.settlement.actualTotal <= 0:
                errors.append("Settlement must have positive actualTotal")
        return (len(errors) == 0, errors)
