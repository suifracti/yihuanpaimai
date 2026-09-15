# -*- coding: utf-8 -*-
"""Manual terminal lifecycle built on Canonical MatchRecord v7.

This is deliberately a thin coordinator.  CanonicalHistoryStore remains the
only persistence/transition authority; this module only validates the explicit
operator intent and projects an existing Manual DRAFT into a terminal record.
"""

from __future__ import annotations

import copy
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from canonical_history_store import CanonicalHistoryStore, HistoryStoreError
from canonical_match_record import (
    FORBIDDEN_ROOT_LEGACY_FIELDS,
    validate_canonical_match_record_v7,
    validate_finalized_match_record_v7,
)
from evaluation_eligibility import validate_prediction_snapshot_for_storage
from current_match import FORBIDDEN_WINNER_PLACEHOLDERS


ASIA_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
TERMINAL_VERSION = 1


class ManualTerminalError(Exception):
    """Stable, user-presentable terminal error with no raw path leakage."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _finite_number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ManualTerminalError("SETTLEMENT_INVALID", f"{field} 必须是数字")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ManualTerminalError("SETTLEMENT_INCOMPLETE", f"请填写{field}") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ManualTerminalError("SETTLEMENT_INVALID", f"{field}必须大于 0")
    return result


def _timezone_aware(value: Any) -> str:
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ASIA_SHANGHAI)
            return parsed.isoformat()
        except ValueError:
            pass
    return datetime.now(ASIA_SHANGHAI).isoformat()


def _clean_terminal_record(draft: Mapping[str, Any]) -> Dict[str, Any]:
    record = copy.deepcopy(dict(draft))
    for field in FORBIDDEN_ROOT_LEGACY_FIELDS:
        record.pop(field, None)
    # Manual DRAFT compatibility projections are intentionally not copied into
    # FINALIZED Canonical v7.  Their canonical values already live in namespaces.
    record.pop("fillDefaults", None)
    record.pop("updatedAt", None)
    return record


class ManualTerminalCoordinator:
    """Exactly-once Manual terminal transitions over one history store."""

    def __init__(self, history_path: Optional[str | Path]):
        self.history_path = Path(history_path).resolve() if history_path else None

    @property
    def available(self) -> bool:
        return self.history_path is not None

    def _store(self) -> CanonicalHistoryStore:
        if self.history_path is None:
            raise ManualTerminalError(
                "HISTORY_UNAVAILABLE", "历史数据暂时不可用，当前局仍保留为草稿"
            )
        return CanonicalHistoryStore(self.history_path)

    @staticmethod
    def _find(records: list[Any], match_id: str) -> Optional[Dict[str, Any]]:
        for record in records:
            if isinstance(record, dict) and str(record.get("id") or "").strip() == match_id:
                return record
        return None

    def lookup(self, match_id: str) -> Optional[Dict[str, Any]]:
        store = self._store()
        return self._find(store.read_database().get("records") or [], match_id)

    def stale_result(self, expected_match_id: str, active_match_id: str) -> Dict[str, Any]:
        expected = str(expected_match_id or "").strip()
        if not expected:
            return self._result(False, "EXPECTED_MATCH_ID_REQUIRED", active_match_id)
        try:
            existing = self.lookup(expected)
        except (HistoryStoreError, ManualTerminalError):
            existing = None
        if existing and str(existing.get("lifecycleStatus") or "").upper() == "FINALIZED":
            return self._result(True, "ALREADY_FINALIZED", expected, record=existing)
        return self._result(False, "STALE_MATCH", active_match_id)

    def finalize(
        self,
        draft_record: Mapping[str, Any],
        settlement_input: Mapping[str, Any],
        *,
        prediction_snapshot: Optional[Mapping[str, Any]] = None,
        played_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        match_id = str(draft_record.get("id") or "").strip()
        if not match_id:
            raise ManualTerminalError("MATCH_ID_MISSING", "当前局缺少 matchId")

        clearing = _finite_number(
            settlement_input.get("clearingPrice"), "最终成交价", positive=True
        )
        actual = _finite_number(
            settlement_input.get("actualTotal"), "最后实际总价", positive=True
        )
        acquired = settlement_input.get("acquired")
        if not isinstance(acquired, bool):
            raise ManualTerminalError("SETTLEMENT_INCOMPLETE", "请选择是否由本人拍下")
        winner = str(settlement_input.get("winner") or "").strip()
        if not winner or winner in FORBIDDEN_WINNER_PLACEHOLDERS:
            raise ManualTerminalError("SETTLEMENT_INCOMPLETE", "请填写结算画面中的竞得者名称；身份未知时请保留草稿")

        record = _clean_terminal_record(draft_record)
        record["lifecycleStatus"] = "FINALIZED"
        record["source"] = "manual"
        record["playedAt"] = _timezone_aware(played_at or record.get("playedAt"))

        costs = record.get("costs") if isinstance(record.get("costs"), dict) else {}
        cost_total_raw = costs.get("total")
        cost_total = 0.0 if cost_total_raw is None else _finite_number(cost_total_raw, "成本")
        derived_profit = actual - clearing - cost_total if acquired else -cost_total
        realized = settlement_input.get("realizedProfit")
        if realized is None:
            realized = derived_profit
        else:
            realized = _finite_number(realized, "净收益")

        record["settlement"] = {
            "status": "verified",
            "verified": True,
            "clearingPrice": clearing,
            "actualTotal": actual,
            "realizedProfit": realized,
            "acquired": acquired,
            "winner": winner,
            "settlementItems": list(settlement_input.get("settlementItems") or []),
        }
        bidding = record.get("bidding") if isinstance(record.get("bidding"), dict) else {}
        bidding = copy.deepcopy(bidding)
        bidding["leaderName"] = winner
        bidding["leaderBid"] = clearing
        bidding["isMyLead"] = acquired
        if acquired:
            bidding["myFinalBid"] = clearing
        record["bidding"] = bidding

        if prediction_snapshot is not None:
            valid, _ = validate_prediction_snapshot_for_storage(prediction_snapshot, match_id=match_id)
            if valid:
                record["predictionSnapshot"] = copy.deepcopy(dict(prediction_snapshot))
            else:
                raise ManualTerminalError(
                    "PREDICTION_SNAPSHOT_INVALID",
                    "预测快照校验失败，当前局仍保留为草稿",
                )

        valid, reasons = validate_finalized_match_record_v7(record, match_id=match_id)
        if not valid:
            labels = {
                "FINALIZED_PROFILE_BOX_MISSING": "宝箱类型",
                "FINALIZED_PROFILE_FIELD_CONDITION_MISSING": "对局规则",
            }
            missing = [labels[reason] for reason in reasons if reason in labels]
            message = ("请先返回对局页补全" + "、".join(missing) + "，再保存结算。已填写内容会保留。"
                       if missing else "本局记录校验未通过，当前局和结算输入已保留，请检查对局信息后重试。")
            raise ManualTerminalError(
                "FINALIZED_VALIDATION_FAILED",
                message,
            )

        try:
            existing = self.lookup(match_id)
            if existing and str(existing.get("lifecycleStatus") or "").upper() == "FINALIZED":
                ex_st = existing.get("settlement") or {}
                if (
                    ex_st.get("clearingPrice") == clearing
                    and ex_st.get("actualTotal") == actual
                    and ex_st.get("acquired") == acquired
                ):
                    return self._result(True, "FINALIZED", match_id, record=existing)
            written = self._store().persist_record_transactional(record, is_finalized=True)
            verified = self.lookup(match_id)
        except (HistoryStoreError, OSError) as exc:
            raise ManualTerminalError(
                "FINALIZE_WRITE_FAILED", "保存失败，当前局与结算输入均已保留"
            ) from exc
        if not verified or str(verified.get("lifecycleStatus") or "").upper() != "FINALIZED":
            raise ManualTerminalError(
                "FINALIZE_VERIFY_FAILED", "保存校验失败，当前局与结算输入均已保留"
            )
        return self._result(True, "FINALIZED", match_id, record=written)

    def keep_draft(self, draft_record: Mapping[str, Any]) -> Dict[str, Any]:
        match_id = str(draft_record.get("id") or "").strip()
        existing = self.lookup(match_id)
        if existing and str(existing.get("lifecycleStatus") or "").upper() == "FINALIZED":
            return self._result(True, "ALREADY_FINALIZED", match_id, record=existing)
        valid, reasons = validate_canonical_match_record_v7(draft_record, match_id=match_id)
        if not valid:
            raise ManualTerminalError(
                "DRAFT_VALIDATION_FAILED", "草稿校验失败：" + ",".join(reasons)
            )
        try:
            written = self._store().persist_record_transactional(draft_record, is_finalized=False)
            verified = self.lookup(match_id)
        except (HistoryStoreError, OSError) as exc:
            raise ManualTerminalError(
                "DRAFT_WRITE_FAILED", "草稿保存失败，当前局未清空"
            ) from exc
        if not verified or str(verified.get("lifecycleStatus") or "").upper() not in {"DRAFT", "FINALIZED"}:
            raise ManualTerminalError("DRAFT_VERIFY_FAILED", "草稿校验失败，当前局未清空")
        if str(verified.get("lifecycleStatus") or "").upper() == "FINALIZED":
            return self._result(True, "ALREADY_FINALIZED", match_id, record=verified)
        return self._result(True, "DRAFT_KEPT", match_id, record=verified)

    def discard(self, draft_record: Mapping[str, Any]) -> Dict[str, Any]:
        record = copy.deepcopy(dict(draft_record))
        match_id = str(record.get("id") or "").strip()
        record["lifecycleStatus"] = "CANCELLED"
        record["source"] = "manual"
        valid, reasons = validate_canonical_match_record_v7(record, match_id=match_id)
        if not valid:
            raise ManualTerminalError(
                "CANCEL_VALIDATION_FAILED", "放弃当前局失败：" + ",".join(reasons)
            )
        try:
            written = self._store().persist_record_transactional(record, is_finalized=False)
            verified = self.lookup(match_id)
        except (HistoryStoreError, OSError) as exc:
            raise ManualTerminalError("CANCEL_WRITE_FAILED", "放弃状态保存失败，当前局未清空") from exc
        if not verified or str(verified.get("lifecycleStatus") or "").upper() not in {
            "CANCELLED",
            "CANCELED",
        }:
            raise ManualTerminalError("CANCEL_VERIFY_FAILED", "放弃状态校验失败，当前局未清空")
        return self._result(True, "DRAFT_DISCARDED", match_id, record=written)

    @staticmethod
    def _result(
        ok: bool,
        status: str,
        match_id: str,
        *,
        record: Optional[Mapping[str, Any]] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = {
            "terminalVersion": TERMINAL_VERSION,
            "ok": bool(ok),
            "status": status,
            "matchId": str(match_id or ""),
        }
        if record is not None:
            result["lifecycleStatus"] = record.get("lifecycleStatus")
        if message:
            result["message"] = message
        return result
