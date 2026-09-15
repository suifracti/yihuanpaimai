"""Read-only, native-owned presentation aggregates for the Main Window."""

from __future__ import annotations

import hashlib
from session_costs import describe_costs
from session_accounting import settlement_accounting
from intel_evidence_presentation import intel_evidence_text
import json
import math
import os
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from history_admission import (
    HISTORY_ADMISSION_POLICY_VERSION,
    LOCAL_TIME_ZONE,
    TIME_ZONE_NAME,
    build_duplicate_index,
    evaluate_history_admission,
)


MAIN_VIEW_STATE_VERSION = 1
ADMISSION_POLICY_VERSION = HISTORY_ADMISSION_POLICY_VERSION
SOURCE_ID = "canonical_match_history"
SERIES_DAY_COUNT = 12
MAX_RECENT_RECORDS = 50


@dataclass(frozen=True)
class SourceRevision:
    source_id: str
    schema_version: Optional[int]
    sha256: Optional[str]
    record_count: Optional[int]
    admission_policy_version: int

    def to_payload(self) -> dict:
        return {
            "sourceId": self.source_id,
            "schemaVersion": self.schema_version,
            "sha256": self.sha256,
            "recordCount": self.record_count,
            "admissionPolicyVersion": self.admission_policy_version,
        }


@dataclass(frozen=True)
class AdmissionSummary:
    admitted_count: Optional[int]
    excluded_count: Optional[int]
    exclusion_reason_counts: Tuple[Tuple[str, int], ...]

    def to_payload(self) -> dict:
        return {
            "admittedCount": self.admitted_count,
            "excludedCount": self.excluded_count,
            "exclusionReasonCounts": {
                reason: count for reason, count in self.exclusion_reason_counts
            },
        }


@dataclass(frozen=True)
class MatchCountComparison:
    previous_value: Optional[int]
    absolute_delta: Optional[int]
    relative_delta: Optional[float]
    availability: str = "AVAILABLE"

    def to_payload(self) -> dict:
        return {
            "availability": self.availability,
            "previousValue": self.previous_value,
            "absoluteDelta": self.absolute_delta,
            "relativeDelta": self.relative_delta,
        }


@dataclass(frozen=True)
class DatedCount:
    date: str
    value: int

    def to_payload(self) -> dict:
        return {"date": self.date, "value": self.value}


@dataclass(frozen=True)
class MatchCountMetric:
    value: Optional[int]
    sample_n: Optional[int]
    excluded_n: Optional[int]
    comparison: MatchCountComparison
    series: Tuple[DatedCount, ...]
    availability: str = "AVAILABLE"

    def to_payload(self) -> dict:
        return {
            "availability": self.availability,
            "value": self.value,
            "unit": "match",
            "sampleN": self.sample_n,
            "excludedN": self.excluded_n,
            "comparison": self.comparison.to_payload(),
            "series": [point.to_payload() for point in self.series],
        }


@dataclass(frozen=True)
class HistoryRecordProjection:
    """Safe, immutable read-only projection of one match record for Main presentation."""

    id: str
    played_at: Optional[str]
    local_played_at: Optional[str]
    lifecycle: str
    admitted: bool
    exclusion_reason: Optional[str]
    venue: Optional[str]
    venue_tier: Optional[str]
    venue_name: Optional[str]
    box: Optional[str]
    box_type: Optional[str]
    field_condition: Optional[str]
    field_condition_name: Optional[str]
    q: Optional[int]
    gold_avg: Optional[int]
    purple_count: Optional[int]
    known_items_summary: Optional[str]
    # Prediction snapshot
    has_prediction: bool
    prediction_mode: Optional[str]
    prediction_support: Optional[str]
    prediction_p20: Optional[float]
    prediction_p50: Optional[float]
    prediction_p80: Optional[float]
    prediction_recommended_max: Optional[int]
    prediction_action_directive: Optional[str]
    prediction_action_reason: Optional[str]
    prediction_leader_bid: Optional[int]
    # Settlement truth
    is_settled: bool
    settlement_clearing_price: Optional[int]
    settlement_actual_total: Optional[int]
    settlement_realized_profit: Optional[int]
    settlement_acquired: Optional[bool]
    settlement_winner: Optional[str]
    settlement_result_reason: Optional[str]
    settlement_items: Tuple[dict, ...] = ()
    settlement_reviewed: bool = False
    settlement_reviewed_at: Optional[str] = None
    settlement_evidence_available: bool = False
    # Boundary 2: bounded six-color selection + per-color provenance must reach Main.
    settlement_quality_sell_selection: Optional[dict] = None
    settlement_quality_sell_selection_sources: Optional[dict] = None
    settlement_quality_sell_selection_source: Optional[str] = None
    warehouse_item_count: Optional[int] = None
    warehouse_unknown_count: Optional[int] = None
    purple_avg: Optional[int] = None
    advanced_facts_json: str = "{}"
    known_facts_json: str = "{}"
    sparkle_json: str = "null"
    accounting_json: str = "null"
    dark_controls_json: str = "{}"
    intel_evidence_summary: str = "未记录情报识别证据"
    match_summary: Optional[str] = None
    auction_evidence_json: Optional[str] = None
    cost_summary: Optional[str] = None

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "playedAt": self.played_at,
            "localPlayedAt": self.local_played_at,
            "lifecycle": self.lifecycle,
            "admitted": self.admitted,
            "exclusionReason": self.exclusion_reason,
            "matchSummary": self.match_summary,
            "costSummary": self.cost_summary,
            "auctionEvidence": json.loads(self.auction_evidence_json) if self.auction_evidence_json else None,
            "environment": {
                "venue": self.venue,
                "venueTier": self.venue_tier,
                "venueName": self.venue_name,
                "box": self.box,
                "boxType": self.box_type,
                "fieldCondition": self.field_condition,
                "fieldConditionName": self.field_condition_name,
            },
            "observedFacts": {
                **json.loads(self.dark_controls_json),
                "sessionAccounting": json.loads(self.accounting_json),
                "intelEvidenceSummary": self.intel_evidence_summary,
                "sparkle": json.loads(self.sparkle_json),
                "q": self.q,
                "goldAvg": self.gold_avg,
                "purpleCount": self.purple_count,
                "purpleAvg": self.purple_avg,
                **json.loads(self.advanced_facts_json),
                **json.loads(self.known_facts_json),
                "knownItemsSummary": self.known_items_summary,
            },
            "prediction": {
                "hasSnapshot": self.has_prediction,
                "mode": self.prediction_mode,
                "supportStatus": self.prediction_support,
                "p20": self.prediction_p20,
                "p50": self.prediction_p50,
                "p80": self.prediction_p80,
                "recommendedMax": self.prediction_recommended_max,
                "actionDirective": self.prediction_action_directive,
                "actionReason": self.prediction_action_reason,
                "leaderBid": self.prediction_leader_bid,
            },
            "settlement": {
                "isSettled": self.is_settled,
                "clearingPrice": self.settlement_clearing_price,
                "actualTotal": self.settlement_actual_total,
                "realizedProfit": self.settlement_realized_profit,
                "acquired": self.settlement_acquired,
                "winner": self.settlement_winner,
                "resultReason": self.settlement_result_reason,
                # Bounded presentation summary only: raw settlementItems /
                # candidate arrays / evidence objects never cross to Main.
                # The whitelisted review DTO (request_settlement_review) carries
                # the proposal-level detail on demand.
                "settlementItemCount": len(self.settlement_items),
                "settlementReviewed": self.settlement_reviewed,
                "settlementReviewedAt": self.settlement_reviewed_at,
                "settlementEvidenceAvailable": self.settlement_evidence_available,
                # Bounded six-color states + provenance (fixed-cardinality maps).
                "qualitySellSelection": dict(self.settlement_quality_sell_selection) if isinstance(self.settlement_quality_sell_selection, dict) else self.settlement_quality_sell_selection,
                "qualitySellSelectionSources": dict(self.settlement_quality_sell_selection_sources) if isinstance(self.settlement_quality_sell_selection_sources, dict) else self.settlement_quality_sell_selection_sources,
                "qualitySellSelectionSource": self.settlement_quality_sell_selection_source,
            },
            "warehouse": {
                "itemCount": self.warehouse_item_count,
                "unknownCount": self.warehouse_unknown_count,
            } if self.warehouse_item_count is not None else None,
        }


@dataclass(frozen=True)
class MainViewStateSnapshot:
    generated_at: str
    history_revision: SourceRevision
    admission: AdmissionSummary
    match_count: MatchCountMetric
    history_records: Tuple[HistoryRecordProjection, ...] = ()
    history_availability: str = "AVAILABLE"
    history_reason: Optional[str] = None
    total_record_count: Optional[int] = None

    def to_payload(self) -> dict:
        """Return fresh JSON primitives without leaking cached object references."""
        total_count = (
            self.total_record_count
            if self.total_record_count is not None
            else self.history_revision.record_count
        )
        return {
            "mainViewStateVersion": MAIN_VIEW_STATE_VERSION,
            "generatedAt": self.generated_at,
            "timeZone": TIME_ZONE_NAME,
            "sourceRevisions": {"history": self.history_revision.to_payload()},
            "history": {
                "availability": self.history_availability,
                "reason": self.history_reason,
                "totalCount": total_count,
                "admittedCount": self.admission.admitted_count,
                "excludedCount": self.admission.excluded_count,
                "recentRecords": [r.to_payload() for r in self.history_records],
                "boundedLimit": MAX_RECENT_RECORDS,
            },
            "admission": self.admission.to_payload(),
            "overview": {
                "metrics": {
                    "matchCount": self.match_count.to_payload(),
                    "totalRecords": {
                        "value": total_count,
                        "admittedCount": self.admission.admitted_count,
                        "excludedCount": self.admission.excluded_count,
                    },
                }
            },
            "analysis": {
                "availability": "INSUFFICIENT_SAMPLES",
                "status": "COLLECTING",
                "title": "暂无足够正式评估数据",
                "description": "当前尚未积累足够符合正式评估条件的实战对局样本。完成更多完整对局后，系统将自动呈现估值误差分布与分位数区间校准分析。",
            },
        }


class MainViewStateProvider:
    """Aggregate one immutable Main snapshot from an atomically persisted file."""

    def __init__(
        self,
        history_path: Optional[os.PathLike[str] | str],
        *,
        authority_availability: Optional[str] = None,
        authority_reason: Optional[str] = None,
    ):
        self._history_path = Path(history_path).resolve() if history_path else None
        self._authority_availability = authority_availability
        self._authority_reason = authority_reason
        self._lock = threading.Lock()
        self._cached_key: Optional[Tuple[int, int, str]] = None
        self._cached_snapshot: Optional[MainViewStateSnapshot] = None

    def snapshot(self, now: Optional[datetime] = None) -> MainViewStateSnapshot:
        local_now = _as_local_time(now or datetime.now(LOCAL_TIME_ZONE))
        if self._history_path is None:
            return unavailable_main_view_state_snapshot(
                self._authority_availability or "UNAVAILABLE",
                self._authority_reason or "HISTORY_AUTHORITY_UNAVAILABLE",
                local_now,
            )
        try:
            stat = self._history_path.stat()
        except FileNotFoundError:
            return unavailable_main_view_state_snapshot(
                "UNAVAILABLE", "HISTORY_NOT_FOUND", local_now
            )
        except PermissionError:
            return unavailable_main_view_state_snapshot(
                "UNAVAILABLE", "HISTORY_PERMISSION_DENIED", local_now
            )
        except OSError:
            return unavailable_main_view_state_snapshot(
                "UNAVAILABLE", "HISTORY_STAT_FAILED", local_now
            )
        cache_key = (stat.st_mtime_ns, stat.st_size, local_now.date().isoformat())
        with self._lock:
            if cache_key == self._cached_key and self._cached_snapshot is not None:
                return self._cached_snapshot

            try:
                raw_bytes, stable_stat = self._read_stable_bytes()
            except FileNotFoundError:
                return unavailable_main_view_state_snapshot(
                    "UNAVAILABLE", "HISTORY_NOT_FOUND", local_now
                )
            except PermissionError:
                return unavailable_main_view_state_snapshot(
                    "UNAVAILABLE", "HISTORY_PERMISSION_DENIED", local_now
                )
            except OSError:
                return unavailable_main_view_state_snapshot(
                    "UNAVAILABLE", "HISTORY_READ_FAILED", local_now
                )
            except RuntimeError:
                return unavailable_main_view_state_snapshot(
                    "UNAVAILABLE", "HISTORY_CHANGED_DURING_READ", local_now
                )
            stable_key = (
                stable_stat.st_mtime_ns,
                stable_stat.st_size,
                local_now.date().isoformat(),
            )
            if stable_key == self._cached_key and self._cached_snapshot is not None:
                return self._cached_snapshot

            try:
                snapshot = self._aggregate(raw_bytes, local_now)
            except (json.JSONDecodeError, UnicodeError):
                snapshot = unavailable_main_view_state_snapshot(
                    "CORRUPT", "HISTORY_PARSE_FAILED", local_now
                )
                self._cached_key = stable_key
                self._cached_snapshot = snapshot
                return snapshot
            except ValueError:
                snapshot = unavailable_main_view_state_snapshot(
                    "CORRUPT", "HISTORY_SCHEMA_INVALID", local_now
                )
                self._cached_key = stable_key
                self._cached_snapshot = snapshot
                return snapshot
            if self._authority_availability in {
                "MIGRATION_REQUIRED",
                "MIGRATION_CONFLICT",
            }:
                snapshot = MainViewStateSnapshot(
                    generated_at=snapshot.generated_at,
                    history_revision=snapshot.history_revision,
                    admission=snapshot.admission,
                    match_count=snapshot.match_count,
                    history_records=snapshot.history_records,
                    history_availability=self._authority_availability,
                    history_reason=self._authority_reason,
                    total_record_count=snapshot.total_record_count,
                )
            self._cached_key = stable_key
            self._cached_snapshot = snapshot
            return snapshot

    def _read_stable_bytes(self) -> tuple[bytes, os.stat_result]:
        for _ in range(3):
            assert self._history_path is not None
            before = self._history_path.stat()
            payload = self._history_path.read_bytes()
            after = self._history_path.stat()
            if (
                before.st_mtime_ns == after.st_mtime_ns
                and before.st_size == after.st_size
                and len(payload) == after.st_size
            ):
                return payload, after
        raise RuntimeError("Canonical history changed repeatedly during snapshot read")

    @classmethod
    def _aggregate(cls, raw_bytes: bytes, local_now: datetime) -> MainViewStateSnapshot:
        document = json.loads(raw_bytes.decode("utf-8"))
        if isinstance(document, list):
            records = document
            schema_version = None
        elif isinstance(document, dict):
            records = document.get("records", [])
            schema_version = document.get("schemaVersion")
        else:
            raise ValueError("Canonical history must be a JSON object or array")
        if not isinstance(records, list):
            raise ValueError("Canonical history records must be an array")

        duplicate_index = build_duplicate_index(records)

        admitted_dates: Counter[str] = Counter()
        excluded_dates: Counter[str] = Counter()
        exclusion_reasons: Counter[str] = Counter()
        admitted_count = 0

        valid_records = [r for r in records if isinstance(r, dict)]

        for record in valid_records:
            decision = evaluate_history_admission(record, duplicate_index)
            normalized_time = (
                decision.normalized_time.local_time
                if decision.normalized_time is not None
                else None
            )
            if decision.admitted:
                admitted_count += 1
                if normalized_time is not None:
                    admitted_dates[normalized_time.date().isoformat()] += 1
            else:
                exclusion_reasons[decision.exclusion_reason] += 1
                if normalized_time is not None:
                    excluded_dates[normalized_time.date().isoformat()] += 1

        # Project up to MAX_RECENT_RECORDS in reverse chronological order (newest first)
        projected_recent: list[HistoryRecordProjection] = []
        for record in reversed(valid_records):
            if len(projected_recent) >= MAX_RECENT_RECORDS:
                break
            decision = evaluate_history_admission(record, duplicate_index)
            projection = cls._project_record(record, decision)
            projected_recent.append(projection)

        today = local_now.date()
        yesterday = today - timedelta(days=1)
        today_key = today.isoformat()
        yesterday_key = yesterday.isoformat()
        today_count = admitted_dates[today_key]
        yesterday_count = admitted_dates[yesterday_key]
        absolute_delta = today_count - yesterday_count
        relative_delta = (
            absolute_delta / yesterday_count if yesterday_count != 0 else None
        )
        series_start = today - timedelta(days=SERIES_DAY_COUNT - 1)
        series = tuple(
            DatedCount(
                date=(series_start + timedelta(days=offset)).isoformat(),
                value=admitted_dates[
                    (series_start + timedelta(days=offset)).isoformat()
                ],
            )
            for offset in range(SERIES_DAY_COUNT)
        )

        return MainViewStateSnapshot(
            generated_at=local_now.isoformat(timespec="seconds"),
            history_revision=SourceRevision(
                source_id=SOURCE_ID,
                schema_version=(
                    int(schema_version)
                    if isinstance(schema_version, int)
                    and not isinstance(schema_version, bool)
                    else None
                ),
                sha256=hashlib.sha256(raw_bytes).hexdigest(),
                record_count=len(records),
                admission_policy_version=ADMISSION_POLICY_VERSION,
            ),
            admission=AdmissionSummary(
                admitted_count=admitted_count,
                excluded_count=len(records) - admitted_count,
                exclusion_reason_counts=tuple(sorted(exclusion_reasons.items())),
            ),
            match_count=MatchCountMetric(
                value=today_count,
                sample_n=today_count,
                excluded_n=excluded_dates[today_key],
                comparison=MatchCountComparison(
                    previous_value=yesterday_count,
                    absolute_delta=absolute_delta,
                    relative_delta=relative_delta,
                ),
                series=series,
            ),
            history_records=tuple(projected_recent),
            history_availability="EMPTY" if not records else "AVAILABLE",
            total_record_count=len(records),
        )

    @staticmethod
    def _project_record(
        record: Mapping[str, Any],
        decision: Any,
    ) -> HistoryRecordProjection:
        """Create a clean, read-only projection of a single match record."""
        rid = str(record.get("id") or "").strip()
        norm_time = decision.normalized_time
        played_at = (
            norm_time.utc_time.isoformat().replace("+00:00", "Z")
            if norm_time is not None
            else str(record.get("playedAt") or record.get("timestamp") or "") or None
        )
        local_played_at = (
            norm_time.local_time.strftime("%Y-%m-%d %H:%M:%S")
            if norm_time is not None
            else None
        )

        lifecycle = str(decision.lifecycle or "LEGACY_UNSPECIFIED")
        admitted = bool(decision.admitted)
        exclusion_reason = decision.exclusion_reason

        # Environment facts - strict: venue is game authority (海贝场 / 珊瑚场 / 真珠场), tier is NOT game fact
        env = record.get("environment") if isinstance(record.get("environment"), dict) else {}
        venue = record.get("venue") or env.get("venue")
        venue_name = env.get("venueName") or record.get("venueName") or (str(venue) if venue else None)
        box = record.get("box") or env.get("box")
        box_type = env.get("boxType") or record.get("boxType")
        field_condition = env.get("fieldCondition") or record.get("fieldCondition")
        field_condition_name = (
            env.get("fieldConditionName")
            or record.get("fieldConditionName")
            or (str(field_condition) if field_condition else None)
        )

        # Core observed facts
        pub = record.get("publicIntel") if isinstance(record.get("publicIntel"), dict) else {}
        qualities = record.get("qualities") if isinstance(record.get("qualities"), dict) else {}

        q_val = pub.get("q") if pub.get("q") is not None else record.get("q")
        q = int(q_val) if isinstance(q_val, (int, float)) and not isinstance(q_val, bool) and math.isfinite(q_val) else None

        gold_q = qualities.get("gold") if isinstance(qualities.get("gold"), dict) else {}
        gold_avg_val = gold_q.get("avg") if gold_q.get("avg") is not None else record.get("goldAvg")
        gold_avg = int(round(gold_avg_val)) if isinstance(gold_avg_val, (int, float)) and not isinstance(gold_avg_val, bool) and math.isfinite(gold_avg_val) else None

        purple_q = qualities.get("purple") if isinstance(qualities.get("purple"), dict) else {}
        purple_count_val = purple_q.get("count") if purple_q.get("count") is not None else record.get("purpleCount")
        purple_count = int(purple_count_val) if isinstance(purple_count_val, (int, float)) and not isinstance(purple_count_val, bool) and math.isfinite(purple_count_val) else None
        purple_avg_val = purple_q.get("avg") if purple_q.get("avg") is not None else record.get("purpleAvg")
        purple_avg = int(round(purple_avg_val)) if isinstance(purple_avg_val, (int, float)) and not isinstance(purple_avg_val, bool) and math.isfinite(purple_avg_val) else None

        advanced_facts = {"totalItems": pub.get("totalItems"), "totalGrid": pub.get("totalGrid")}
        for field, quality, member in (("blueCount","blue","count"),("goldCount","gold","count"),
                                        ("redCount","red","count"),("goldGrid","gold","grid"),
                                        ("purpleGrid","purple","grid"),("whiteCount","white","count"),("whiteAvg","white","avg"),("whiteGrid","white","grid"),("greenCount","green","count"),("greenAvg","green","avg"),("greenGrid","green","grid"),("blueAvg","blue","avg"),("blueGrid","blue","grid"),("redGrid","red","grid")):
            sub = qualities.get(quality)
            advanced_facts[field] = sub.get(member) if isinstance(sub, dict) else None
        advanced_facts = {key: int(value) if isinstance(value,(int,float)) and not isinstance(value,bool)
                          and math.isfinite(value) and value >= 0 and int(value) == value else None
                          for key,value in advanced_facts.items()}

        from v06_adapter import format_known_items
        known_facts = {}
        for color in ("gold", "purple", "red", "blue", "green", "white"):
            sub = qualities.get(color)
            key = "known" + color.title()
            raw = sub.get("knownItems") if isinstance(sub, dict) and "knownItems" in sub else record.get(key)
            known_facts[key] = format_known_items(raw)
        known_items_count = 0
        for q_key in ("gold", "purple", "red", "blue", "green", "white"):
            sub_q = qualities.get(q_key)
            if isinstance(sub_q, dict):
                items = sub_q.get("knownItems")
                if isinstance(items, list):
                    known_items_count += len(items)
        known_summary = f"{known_items_count} 件已知藏品" if known_items_count > 0 else None

        # Prediction snapshot - strictly reflect persisted data, never recompute!
        snap = record.get("predictionSnapshot")
        solver_res = record.get("solverResult")
        has_prediction = False
        pred_mode = None
        pred_support = None
        pred_p20 = None
        pred_p50 = None
        pred_p80 = None
        pred_rec_max = None
        pred_directive = None
        pred_reason = None
        pred_bid = None

        if isinstance(snap, dict):
            has_prediction = True
            forecast = snap.get("forecast") if isinstance(snap.get("forecast"), dict) else {}
            quantiles = forecast.get("quantiles") if isinstance(forecast.get("quantiles"), dict) else snap.get("quantiles") or {}
            decisions = snap.get("decisions") if isinstance(snap.get("decisions"), dict) else {}
            snap_input = snap.get("input") if isinstance(snap.get("input"), dict) else {}

            pred_mode = forecast.get("mode") or snap.get("mode")
            pred_support = forecast.get("supportStatus") or snap.get("supportStatus")
            pred_p20 = quantiles.get("p20")
            pred_p50 = quantiles.get("p50")
            pred_p80 = quantiles.get("p80")
            rec_max_raw = decisions.get("recommendedMax") if decisions.get("recommendedMax") is not None else snap.get("recommendedMax")
            pred_rec_max = int(round(rec_max_raw)) if isinstance(rec_max_raw, (int, float)) and not isinstance(rec_max_raw, bool) and math.isfinite(rec_max_raw) else None
            pred_directive = decisions.get("actionDirective") or snap.get("actionDirective")
            pred_reason = decisions.get("actionReason") or snap.get("actionReason")
            bid_raw = snap_input.get("leaderBid") if snap_input.get("leaderBid") is not None else snap.get("leaderBid")
            pred_bid = int(bid_raw) if isinstance(bid_raw, (int, float)) and not isinstance(bid_raw, bool) and math.isfinite(bid_raw) else None
        elif isinstance(solver_res, dict):
            has_prediction = True
            decisions = solver_res.get("decisions") if isinstance(solver_res.get("decisions"), dict) else {}
            pred_mode = solver_res.get("mode") or "structural_only"
            pred_support = solver_res.get("supportStatus")
            pred_p20 = decisions.get("valP20")
            pred_p50 = decisions.get("valP50")
            pred_p80 = decisions.get("valP80")
            rec_max_raw = decisions.get("targetLine") or decisions.get("marginalLine")
            pred_rec_max = int(round(rec_max_raw)) if isinstance(rec_max_raw, (int, float)) and not isinstance(rec_max_raw, bool) and math.isfinite(rec_max_raw) else None
            pred_directive = decisions.get("actionDirective")
            pred_reason = decisions.get("actionReason")

        # Settlement truth - safe bounded summary only, no raw array leakage
        settlement = record.get("settlement") if isinstance(record.get("settlement"), dict) else {}
        clearing_price_val = settlement.get("clearingPrice") if settlement.get("clearingPrice") is not None else record.get("clearingPrice")
        actual_total_val = settlement.get("actualTotal") if settlement.get("actualTotal") is not None else record.get("actualTotal")
        realized_profit_val = settlement.get("realizedProfit") if settlement.get("realizedProfit") is not None else record.get("realizedProfit")

        clearing_price = int(clearing_price_val) if isinstance(clearing_price_val, (int, float)) and not isinstance(clearing_price_val, bool) and math.isfinite(clearing_price_val) else None
        actual_total = int(actual_total_val) if isinstance(actual_total_val, (int, float)) and not isinstance(actual_total_val, bool) and math.isfinite(actual_total_val) else None
        realized_profit = int(realized_profit_val) if isinstance(realized_profit_val, (int, float)) and not isinstance(realized_profit_val, bool) and math.isfinite(realized_profit_val) else None

        is_settled = bool(
            settlement.get("isSettled")
            or str(settlement.get("status") or "").strip().lower() == "verified"
            or (actual_total is not None and actual_total > 0)
            or (clearing_price is not None and clearing_price > 0)
        )

        raw_acquired = settlement.get("acquired")
        if raw_acquired is None and "acquired" not in settlement:
            raw_acquired = record.get("acquired")
        acquired = raw_acquired if isinstance(raw_acquired, bool) else None

        winner = settlement.get("winner") or record.get("winner")
        result_reason = settlement.get("resultReason") or record.get("resultReason")

        items_raw = settlement.get("settlementItems") or record.get("settlementItems") or []
        items_list = []
        if isinstance(items_raw, list):
            for item in items_raw[:10]:
                if isinstance(item, dict):
                    price_val = item.get("price")
                    price_int = int(price_val) if isinstance(price_val, (int, float)) and not isinstance(price_val, bool) and math.isfinite(price_val) else None
                    items_list.append({
                        "name": str(item.get("name") or "未知藏品"),
                        "price": price_int,
                        "rarity": str(item.get("rarity") or ""),
                    })

        # Warehouse summary projection (Phase 10: bounded canonical summary)
        warehouse_fact = record.get("warehouse")
        warehouse_item_count = None
        warehouse_unknown_count = None
        wh_units = record.get("settlement", {}).get("reviewUnits")
        if isinstance(wh_units, list) and wh_units:
            warehouse_item_count = len(wh_units)
            warehouse_unknown_count = sum(
                1 for u in wh_units
                if isinstance(u, dict) and (
                    u.get("confirmationStatus") != "CONFIRMED"
                    or not u.get("canonicalName")
                )
            )
        elif isinstance(warehouse_fact, dict) and isinstance(warehouse_fact.get("itemCount"), int):
            warehouse_item_count = warehouse_fact.get("itemCount")
            warehouse_unknown_count = warehouse_fact.get("unknownCount") or 0
        elif isinstance(warehouse_fact, dict) and "slots" in warehouse_fact:
            wh_slots = warehouse_fact.get("slots")
            if isinstance(wh_slots, list):
                warehouse_item_count = len(wh_slots)
                warehouse_unknown_count = sum(
                    1 for s in wh_slots
                    if isinstance(s, dict) and (s.get("rarity") == "unknown" or s.get("evidenceLevel") == "OUTLINE_ONLY")
                )
        if warehouse_item_count is None:
            wir = record.get("warehouseIdentityReview")
            if isinstance(wir, dict) and "summary" in wir:
                summary = wir.get("summary") or {}
                warehouse_item_count = summary.get("trackCount")
                warehouse_unknown_count = summary.get("unresolvedTrackCount") or 0

        # Match summary projection (Phase 18: runtime deterministic presentation text)
        from match_summary import format_match_summary
        match_summary = format_match_summary(record)

        # Boundary 2: bounded six-color selection + per-color provenance.
        q_sel_raw = settlement.get("qualitySellSelection")
        q_sources_raw = settlement.get("qualitySellSelectionSources")
        q_src_raw = settlement.get("qualitySellSelectionSource")
        q_sel_proj = None
        if isinstance(q_sel_raw, Mapping):
            from quality_sell_selection import normalize_quality_sell_selection
            q_sel_proj = normalize_quality_sell_selection(q_sel_raw)
        q_sources_proj = None
        if isinstance(q_sources_raw, Mapping):
            from quality_sell_selection import normalize_quality_sell_selection_sources
            q_sources_proj = normalize_quality_sell_selection_sources(q_sources_raw)
        q_src_proj = str(q_src_raw) if q_src_raw else None

        return HistoryRecordProjection(
            id=rid,
            played_at=played_at,
            local_played_at=local_played_at,
            lifecycle=lifecycle,
            admitted=admitted,
            exclusion_reason=exclusion_reason,
            venue=str(venue) if venue else None,
            venue_tier=None,
            venue_name=venue_name,
            box=str(box) if box else None,
            box_type=str(box_type) if box_type else None,
            field_condition=str(field_condition) if field_condition else None,
            field_condition_name=field_condition_name,
            q=q,
            gold_avg=gold_avg,
            purple_count=purple_count,
            purple_avg=purple_avg,
            advanced_facts_json=json.dumps(advanced_facts),
            known_facts_json=json.dumps(known_facts, ensure_ascii=False),
            sparkle_json=json.dumps(record.get("sparkle"), ensure_ascii=False),
            accounting_json=json.dumps(settlement_accounting(record), ensure_ascii=False),
            intel_evidence_summary=intel_evidence_text(record),
            dark_controls_json=json.dumps({key: (record.get('bidding') or {}).get(key) for key in ('privateBidCap', 'bidActionCount')}),
            known_items_summary=known_summary,
            has_prediction=has_prediction,
            prediction_mode=pred_mode,
            prediction_support=pred_support,
            prediction_p20=pred_p20,
            prediction_p50=pred_p50,
            prediction_p80=pred_p80,
            prediction_recommended_max=pred_rec_max,
            prediction_action_directive=pred_directive,
            prediction_action_reason=pred_reason,
            prediction_leader_bid=pred_bid,
            is_settled=is_settled,
            settlement_clearing_price=clearing_price,
            settlement_actual_total=actual_total,
            settlement_realized_profit=realized_profit,
            settlement_acquired=acquired,
            settlement_winner=str(winner) if winner else None,
            settlement_result_reason=str(result_reason) if result_reason else None,
            settlement_items=tuple(items_list),
            settlement_reviewed=bool(settlement.get("reviewedItems")),
            settlement_reviewed_at=settlement.get("reviewedAt"),
            settlement_evidence_available=bool(
                (settlement.get("truthEvidence") or {}).get("evidenceReferences")
                or (settlement.get("evidenceAttachments") or {}).get("captures")
            ),
            settlement_quality_sell_selection=q_sel_proj,
            settlement_quality_sell_selection_sources=q_sources_proj,
            settlement_quality_sell_selection_source=q_src_proj,
            warehouse_item_count=warehouse_item_count,
            warehouse_unknown_count=warehouse_unknown_count,
            match_summary=match_summary,
            cost_summary=describe_costs(record.get("costs")),
            auction_evidence_json=json.dumps(record['auctionEvidence'],ensure_ascii=False) if isinstance(record.get('auctionEvidence'),dict) else None,
        )


def unavailable_main_view_state_snapshot(
    availability: str,
    reason: str,
    now: Optional[datetime] = None,
) -> MainViewStateSnapshot:
    """Build a safe immutable failure snapshot without path/exception leakage."""
    local_now = _as_local_time(now or datetime.now(LOCAL_TIME_ZONE))
    return MainViewStateSnapshot(
        generated_at=local_now.isoformat(timespec="seconds"),
        history_revision=SourceRevision(
            source_id=SOURCE_ID,
            schema_version=None,
            sha256=None,
            record_count=None,
            admission_policy_version=ADMISSION_POLICY_VERSION,
        ),
        admission=AdmissionSummary(
            admitted_count=None,
            excluded_count=None,
            exclusion_reason_counts=(),
        ),
        match_count=MatchCountMetric(
            value=None,
            sample_n=None,
            excluded_n=None,
            comparison=MatchCountComparison(
                previous_value=None,
                absolute_delta=None,
                relative_delta=None,
                availability="UNAVAILABLE",
            ),
            series=(),
            availability="UNAVAILABLE",
        ),
        history_records=(),
        history_availability=availability,
        history_reason=reason,
        total_record_count=None,
    )


def _as_local_time(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TIME_ZONE)
    return value.astimezone(LOCAL_TIME_ZONE)
