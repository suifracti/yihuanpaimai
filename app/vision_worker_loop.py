"""Live Vision Worker Loop with Fault-Tolerant Liveness & Injection Seams.

Provides a robust, non-terminating capture/inference/publish loop that catches transient
per-frame exceptions, enforces bounded backoff, respects intentional shutdown, and
provides dependency injection seams for offline deterministic testing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import numpy as np
from live_match_transport import LiveMatchPublisher, LiveMatchSession

logger = logging.getLogger(__name__)


def apply_archive_lifecycle(saved: Dict[str, Any], pipeline: Any, current_match: Any) -> None:
    """A saved draft is not a finalized settlement."""
    status = str(saved.get("lifecycleStatus") or "").upper()
    if status not in {"DRAFT", "FINALIZED"}:
        return
    if current_match is not None:
        saved_id = str(saved.get("id") or "")
        if saved_id != str(getattr(current_match, "id", "") or ""):
            return
        current_match.lifecycle_status = status
        st = saved.get("settlement")
        if isinstance(st, dict):
            patch = {
                "settlementReady": True,
                "settlementFinalized": (status == "FINALIZED"),
                "clearingPrice": st.get("clearingPrice"),
                "actualTotal": st.get("actualTotal"),
                "realizedProfit": st.get("realizedProfit"),
                "winner": st.get("winner"),
                "settlementWinnerName": st.get("settlementWinnerName") or st.get("winner"),
                "isSelfWinner": st.get("isSelfWinner"),
                "isAcquired": st.get("acquired"),
                "didCurrentUserAcquire": st.get("acquired"),
                "settlementItems": st.get("settlementItems") or [],
            }
            if st.get("truthEvidence"):
                patch["settlementTruthEvidence"] = st.get("truthEvidence")
            if isinstance(st.get("welfare"), dict) and st["welfare"].get("received") is not None:
                patch["welfareReceived"] = st["welfare"]["received"]
            current_match.apply_facts(patch, source="vision", intent="confirm" if status == "FINALIZED" else "observe")
    if pipeline is not None and hasattr(pipeline, "mark_settlement_saved"):
        pipeline.mark_settlement_saved()
    if status == "FINALIZED" and pipeline is not None and hasattr(pipeline, "mark_settlement_finalized"):
        pipeline.mark_settlement_finalized()


async def run_vision_capture_loop(
    *,
    pipeline: Any,
    ws: Optional[Any] = None,
    stop_flag: Optional[Dict[str, bool]] = None,
    frame_provider: Optional[Callable[[], Tuple[Optional[int], Optional[np.ndarray], str]]] = None,
    process_frame_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    publish_fn: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    archiver: Optional[Any] = None,
    refresh_state: Optional[Dict[str, Any]] = None,
    run_refresh_transaction_fn: Optional[Callable[[str], Awaitable[bool]]] = None,
    fps: Optional[float] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
    debug_mode: bool = False,
    is_in_auction_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
    build_in_auction_hud_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    build_nav_hud_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    process_live_game_frame_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    early_process_live_game_frame_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
    auto_save_settlement: bool = True,
    current_match: Optional[Any] = None,
    state_publisher: Optional[Any] = None,
    match_session: Optional[Any] = None,
    live_control: Optional[Any] = None,
    sync_context_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
    before_archive_fn: Optional[Callable[[Dict[str, Any]], Awaitable[bool]]] = None,
) -> None:
    """Run the main vision inference loop with per-stage fault isolation."""
    def _log(tag: str, msg: str):
        if log_fn:
            try:
                log_fn(tag, msg)
            except Exception:
                pass
        else:
            logger.info(f"[{tag}] {msg}")

    target_fps = fps if (fps and fps > 0) else 10.0
    sleep_interval = 1.0 / target_fps
    state_publisher = state_publisher or LiveMatchPublisher()
    match_session = match_session or LiveMatchSession()

    async def report_failure(stage):
        payload = {'type': 'vision_health', 'visionHealth': {'status': 'ERROR', 'stage': stage}}
        try:
            if publish_fn:
                await publish_fn(payload)
            elif ws is not None:
                await ws.send(json.dumps(payload))
        except Exception:
            if ws is not None:
                raise ConnectionError('Vision health transport disconnected')

    while not (stop_flag and stop_flag.get("stop")):
        if stop_flag and stop_flag.get("stop"):
            break

        try:
            # 0. Check pending force_refresh transactions
            if refresh_state and run_refresh_transaction_fn:
                pending_id = refresh_state.get("latest_id")
                if pending_id and pending_id != refresh_state.get("committed_id"):
                    try:
                        await run_refresh_transaction_fn(pending_id)
                    except Exception as exc:
                        _log("WORKER:VISION", f"Refresh transaction error: {type(exc).__name__}: {exc}")
                    await asyncio.sleep(0)
                    continue

            # 1. Frame Capture Stage
            try:
                if frame_provider:
                    game_hwnd, img, shot_at = frame_provider()
                else:
                    game_hwnd, img, shot_at = None, None, ""
            except Exception as exc:
                _log("WORKER:VISION", f"Frame capture stage error: {type(exc).__name__}: {exc}")
                await report_failure('capture')
                await asyncio.sleep(0.2)
                continue

            if shot_at == "EOF":
                _log("WORKER:VISION", "frame source reached EOF")
                if stop_flag is not None:
                    stop_flag["stop"] = True
                break

            game_present = game_hwnd is not None
            if not game_present or img is None:
                standby_payload = {
                    "visionHealth": {"status": "WAITING", "stage": "capture"},
                    "solverStatus": "standby",
                    "inAuction": False,
                    "gameDetected": False,
                    "round": 0,
                    "timer": None,
                    "leaderBidFormatted": "-- W",
                    "leaderBidSub": "未检测到《异环》游戏",
                    "myBidFormatted": "-- W",
                    "myName": "玩家本人",
                    "opponents": [],
                    "biddingHistory": {},
                    "roundTimeline": {},
                    "isSettlement": False,
                    "gridCells": [0] * 250,
                }
                try:
                    if publish_fn:
                        await publish_fn(standby_payload)
                    elif ws is not None:
                        await ws.send(json.dumps(standby_payload))
                except Exception as exc:
                    _log("WORKER:VISION", f"Standby publish error: {type(exc).__name__}: {exc}")
                    if ws is not None:
                        raise ConnectionError("Vision transport disconnected") from exc
                await asyncio.sleep(0.5)
                continue

            # Geometry-only early publish. Warehouse/settlement identity must
            # not run here: it previously blocked auction OCR for 10-50s.
            if early_process_live_game_frame_fn is not None:
                try:
                    early_payload = early_process_live_game_frame_fn(
                        img,
                        game_hwnd=game_hwnd,
                        captured_at=shot_at,
                        pipeline_inst=pipeline,
                    )
                    if isinstance(early_payload, dict):
                        early_payload["settlementStable"] = bool(
                            early_payload.get("settlementReady")
                            or early_payload.get("settlementFinalized")
                        )
                        if current_match is not None:
                            if live_control is not None:
                                state_publisher.awaiting_exit = live_control.awaiting_exit
                            early_payload = state_publisher.attach(early_payload, current_match)
                        if publish_fn:
                            await publish_fn(early_payload)
                        elif ws is not None:
                            await ws.send(json.dumps(early_payload))
                except Exception as exc:
                    _log("WORKER:VISION", f"Early warehouse publish error: {type(exc).__name__}: {exc}")

            # 2. Vision Inference / Pipeline Process Stage
            current_key = str(getattr(current_match, "id", "") or "") if current_match is not None else None

            def _infer_ocr_only():
                if process_frame_fn:
                    try:
                        return process_frame_fn(
                            img,
                            captured_at=shot_at,
                            record_stable_key=current_key,
                            include_heavy_identity=False,
                        )
                    except TypeError:
                        try:
                            return process_frame_fn(img, captured_at=shot_at, record_stable_key=current_key)
                        except TypeError:
                            return process_frame_fn(img, captured_at=shot_at)
                if pipeline:
                    try:
                        return pipeline.process_frame(
                            img,
                            captured_at=shot_at,
                            record_stable_key=current_key,
                            include_heavy_identity=False,
                        )
                    except TypeError:
                        return pipeline.process_frame(img, captured_at=shot_at)
                return {}

            try:
                t_ocr = time.perf_counter()
                ctx = await asyncio.get_running_loop().run_in_executor(None, _infer_ocr_only)
                ocr_ms = (time.perf_counter() - t_ocr) * 1000.0
                if ocr_ms >= 200 or ctx.get("scene") in ("IN_AUCTION", "SETTLEMENT"):
                    _log(
                        "WORKER:VISION",
                        f"ocr_frame_ms={ocr_ms:.0f} scene={ctx.get('scene')} round={ctx.get('round')} "
                        f"q={ctx.get('q')} goldAvg={ctx.get('goldAvg')} bid={ctx.get('currentLeaderBid')}",
                    )
            except Exception as exc:
                _log("WORKER:VISION", f"Frame inference error: {type(exc).__name__}: {exc}")
                await report_failure('recognition')
                await asyncio.sleep(0.1)
                continue

            if current_match is not None:
                if live_control is not None:
                    ctx = live_control.apply_to_frame(ctx, current_match, match_session)
                else:
                    match_session.observe(ctx, current_match)
            ctx["settlementStable"] = bool(ctx.get("settlementReady") or ctx.get("settlementFinalized"))
            if sync_context_fn is not None:
                sync_context_fn(ctx)
            if img is not None:
                ctx["frame"] = img
                if pipeline is not None:
                    try:
                        pipeline.current_context["frame"] = img
                    except Exception:
                        pass

            # 3. Scene Signature Logging & Archiving (Safe)
            try:
                scene_sig = (
                    ctx.get("scene"),
                    ctx.get("inLobby"),
                    ctx.get("lobbyCharacter"),
                    ctx.get("lobbyToolGroup"),
                    ctx.get("lobbyVenue"),
                    ctx.get("round"),
                    ctx.get("box"),
                    ctx.get("fieldCondition"),
                    ctx.get("q"),
                    ctx.get("goldAvg"),
                    ctx.get("purpleAvg"),
                    ctx.get("purple"),
                    ctx.get("currentLeaderBid"),
                    ctx.get("settlementReady"),
                    (ctx.get("settlementData") or {}).get("actualTotal"),
                )
                if scene_sig != getattr(pipeline, "_last_logged_scene_sig", None):
                    if pipeline is not None:
                        try:
                            setattr(pipeline, "_last_logged_scene_sig", scene_sig)
                        except Exception:
                            pass
                    settle = ctx.get("settlementData") or {}
                    _log(
                        "WORKER:VISION",
                        f"scene={ctx.get('scene')} lobby={ctx.get('inLobby')} char={ctx.get('lobbyCharacter')} "
                        f"tool={ctx.get('lobbyToolGroup')} venue={ctx.get('lobbyVenue')} round={ctx.get('round')} "
                        f"box={ctx.get('box')} field={ctx.get('fieldCondition')} q={ctx.get('q')} "
                        f"goldAvg={ctx.get('goldAvg')} purpleAvg={ctx.get('purpleAvg')} purple={ctx.get('purple')} "
                        f"leader={ctx.get('leaderName')} bid={ctx.get('currentLeaderBid')} "
                        f"settleReady={ctx.get('settlementReady')} settle={settle.get('clearingPrice')}/{settle.get('actualTotal')}/{settle.get('profit')}",
                    )
                if debug_mode:
                    wh = ctx.get("warehouseVision") or {}
                    slots = wh.get("slots") or []
                    slot_sig = tuple(
                        (s.get("trackId"), s.get("size"), s.get("rarity"), s.get("evidenceLevel"), s.get("shapeLocked"), s.get("hasGlow"))
                        for s in slots
                    )
                    if slot_sig != getattr(pipeline, "_last_logged_slot_sig", None):
                        if pipeline is not None:
                            try:
                                setattr(pipeline, "_last_logged_slot_sig", slot_sig)
                            except Exception:
                                pass
                        brief = [
                            f"#{s.get('trackId')}:{s.get('rarity')}/{s.get('size')}/{s.get('evidenceLevel')}/glow={s.get('hasGlow')}/lock={s.get('shapeLocked')}"
                            for s in slots[:16]
                        ]
                        _log("WORKER:VISION", f"warehouse n={len(slots)} {brief}")

                if current_match is not None:
                    if hasattr(current_match, "id") and current_match.id:
                        ctx.setdefault("matchId", current_match.id)
                        ctx.setdefault("id", current_match.id)
                    if hasattr(current_match, "apply_facts"):
                        patch: Dict[str, Any] = {}
                    if ctx.get("isSettlement"):
                        st = ctx.get("settlementData") or {}
                        patch["settlementReady"] = bool(ctx.get("settlementReady"))
                        patch["settlementFinalized"] = bool(ctx.get("settlementFinalized"))
                        if st.get("clearingPrice") is not None:
                            patch["clearingPrice"] = st.get("clearingPrice")
                        if st.get("actualTotal") is not None:
                            patch["actualTotal"] = st.get("actualTotal")
                        if st.get("profit") is not None:
                            patch["realizedProfit"] = st.get("profit")
                        if ctx.get("settlementTruthEvidence"):
                            patch["settlementTruthEvidence"] = ctx.get("settlementTruthEvidence")
                        elif ctx.get("settlementEvidence"):
                            patch["settlementEvidence"] = ctx.get("settlementEvidence")
                    if patch:
                        current_match.apply_facts(patch, source="vision")

                if archiver and auto_save_settlement and ctx.get("isSettlement") and ctx.get("settlementReady"):
                    if pipeline is not None and hasattr(pipeline, "complete_heavy_identity"):
                        if getattr(pipeline, "_pending_heavy_identity", None):
                            try:
                                heavy_ctx = await asyncio.get_running_loop().run_in_executor(
                                    None, pipeline.complete_heavy_identity
                                )
                                if isinstance(heavy_ctx, dict):
                                    ctx = heavy_ctx
                            except Exception as h_err:
                                _log("WORKER:VISION", f"Pre-archive identity error: {h_err}")
                    archive_ctx = dict(ctx)
                    archive_ctx["frame"] = img
                    archive_allowed = await before_archive_fn(archive_ctx) if before_archive_fn else True
                    saved = archiver.archive_match(archive_ctx) if archive_allowed else None
                    if saved:
                        apply_archive_lifecycle(saved, pipeline, current_match)
                        st_log = saved.get("settlement") if isinstance(saved.get("settlement"), dict) else {}
                        _log(
                            "WORKER:VISION",
                            f"settlement finalize reason=stable price={st_log.get('clearingPrice') if st_log.get('clearingPrice') is not None else saved.get('clearingPrice')} "
                            f"actual={st_log.get('actualTotal') if st_log.get('actualTotal') is not None else saved.get('actualTotal')} "
                            f"profit={st_log.get('realizedProfit') if st_log.get('realizedProfit') is not None else saved.get('realizedProfit')} box={saved.get('box')}",
                        )
            except Exception as exc:
                _log("WORKER:VISION", f"Scene logging or settlement archiving error: {type(exc).__name__}: {exc}")

            # 4. HUD Payload Build Stage
            try:
                if process_live_game_frame_fn:
                    hud_payload = process_live_game_frame_fn(
                        img,
                        game_hwnd=game_hwnd,
                        captured_at=shot_at,
                        pipeline_inst=pipeline,
                        ctx=ctx,
                    )
                elif is_in_auction_fn and build_in_auction_hud_fn and build_nav_hud_fn:
                    if is_in_auction_fn(ctx):
                        hud_payload = build_in_auction_hud_fn(ctx)
                    else:
                        hud_payload = build_nav_hud_fn(ctx)
                else:
                    hud_payload = dict(ctx)
            except Exception as exc:
                _log("WORKER:VISION", f"Payload building error: {type(exc).__name__}: {exc}")
                await report_failure('presentation')
                await asyncio.sleep(0.1)
                continue

            # 5. Publish Stage
            try:
                hud_payload["settlementStable"] = ctx["settlementStable"]
                hud_payload['visionHealth'] = {'status': 'READY', 'stage': 'recognition'}
                if current_match is not None:
                    if live_control is not None:
                        state_publisher.awaiting_exit = live_control.awaiting_exit
                    hud_payload = state_publisher.attach(hud_payload, current_match)
                if publish_fn:
                    await publish_fn(hud_payload)
                elif ws is not None:
                    await ws.send(json.dumps(hud_payload))
            except Exception as exc:
                _log("WORKER:VISION", f"Payload publish error: {type(exc).__name__}: {exc}")
                if ws is not None:
                    raise ConnectionError("Vision transport disconnected") from exc
                await asyncio.sleep(0.2)
                continue

            # Yield so control/stop WS messages can run, then finish identity.
            await asyncio.sleep(0)
            if stop_flag and stop_flag.get("stop"):
                break
            if pipeline is not None and hasattr(pipeline, "complete_heavy_identity"):
                try:
                    t_id = time.perf_counter()
                    heavy_ctx = await asyncio.get_running_loop().run_in_executor(
                        None, pipeline.complete_heavy_identity
                    )
                    ident_ms = (time.perf_counter() - t_id) * 1000.0
                except Exception as exc:
                    _log("WORKER:VISION", f"Deferred identity error: {type(exc).__name__}: {exc}")
                    heavy_ctx = None
                    ident_ms = 0.0
                if isinstance(heavy_ctx, dict):
                    ctx = heavy_ctx
                    _log(
                        "WORKER:VISION",
                        f"identity_frame_ms={ident_ms:.0f} scene={ctx.get('scene')} "
                        f"slots={len(ctx.get('warehouseSlots') or [])} "
                        f"exact={ctx.get('settlementExactItemCount')}",
                    )
                    if current_match is not None:
                        if live_control is not None:
                            ctx = live_control.apply_to_frame(ctx, current_match, match_session)
                        else:
                            match_session.observe(ctx, current_match)
                    ctx["settlementStable"] = bool(ctx.get("settlementReady") or ctx.get("settlementFinalized"))
                    if sync_context_fn is not None:
                        sync_context_fn(ctx)
                    try:
                        if archiver and auto_save_settlement and ctx.get("isSettlement") and ctx.get("settlementReady"):
                            archive_ctx = dict(ctx)
                            archive_ctx["frame"] = img
                            archive_allowed = await before_archive_fn(archive_ctx) if before_archive_fn else True
                            saved = archiver.archive_match(archive_ctx) if archive_allowed else None
                            if saved:
                                apply_archive_lifecycle(saved, pipeline, current_match)
                                st_log = saved.get("settlement") if isinstance(saved.get("settlement"), dict) else {}
                                _log(
                                    "WORKER:VISION",
                                    f"settlement finalize reason=stable price={st_log.get('clearingPrice') if st_log.get('clearingPrice') is not None else saved.get('clearingPrice')} "
                                    f"actual={st_log.get('actualTotal') if st_log.get('actualTotal') is not None else saved.get('actualTotal')} "
                                    f"profit={st_log.get('realizedProfit') if st_log.get('realizedProfit') is not None else saved.get('realizedProfit')} box={saved.get('box')}",
                                )
                            elif archiver and hasattr(archiver, "append_finalized_evidence") and (ctx.get("settlementFinalized") or (current_match and getattr(current_match, "finalized", False))):
                                rec_id = str(ctx.get("id") or ctx.get("matchId") or (getattr(current_match, "id", "") or "")).strip()
                                s_items = ctx.get("settlementItems") or (ctx.get("settlementData") or {}).get("items") or []
                                if rec_id and s_items:
                                    r_units = []
                                    for idx, s in enumerate(s_items):
                                        if isinstance(s, dict):
                                            c_id = s.get("catalogId") or s.get("exactItemId")
                                            c_name = s.get("name") or s.get("identifiedName")
                                            r_units.append({
                                                "reviewUnitId": f"settlement_item_{idx}",
                                                "placementStatus": "ALIGNED",
                                                "worldAnchor": {"row": s.get("row", 0), "col": s.get("col", 0)},
                                                "footprint": {"widthCells": s.get("w", 1), "heightCells": s.get("h", 1)},
                                                "canonicalName": c_name,
                                                "selectedCatalogId": c_id,
                                                "confirmationStatus": "CONFIRMED" if c_name else "CANDIDATE_ONLY",
                                                "identityStatus": "EXACT_IDENTIFIED" if c_name else "REVIEW_REQUIRED",
                                                "candidates": [{"catalogId": c_id, "name": c_name}] if c_id else [],
                                            })
                                    if r_units:
                                        archiver.append_finalized_evidence(
                                            rec_id,
                                            review_update={
                                                "reviewUnits": r_units,
                                                "warehouseReviewUnits": r_units,
                                            },
                                            audit_reason="DEFERRED_HEAVY_IDENTITY_ENRICHMENT",
                                        )
                    except Exception as exc:
                        _log("WORKER:VISION", f"Scene logging or settlement archiving error: {type(exc).__name__}: {exc}")
                    try:
                        if process_live_game_frame_fn:
                            hud_payload = process_live_game_frame_fn(
                                img,
                                game_hwnd=game_hwnd,
                                captured_at=shot_at,
                                pipeline_inst=pipeline,
                                ctx=ctx,
                            )
                        else:
                            hud_payload = dict(ctx)
                        hud_payload["settlementStable"] = ctx["settlementStable"]
                        if current_match is not None:
                            if live_control is not None:
                                state_publisher.awaiting_exit = live_control.awaiting_exit
                            hud_payload = state_publisher.attach(hud_payload, current_match)
                        if publish_fn:
                            await publish_fn(hud_payload)
                        elif ws is not None:
                            await ws.send(json.dumps(hud_payload))
                    except Exception as exc:
                        _log("WORKER:VISION", f"Payload publish error: {type(exc).__name__}: {exc}")
                        if ws is not None:
                            raise ConnectionError("Vision transport disconnected") from exc

        except asyncio.CancelledError:
            break
        except ConnectionError:
            raise
        except Exception as loop_exc:
            _log("WORKER:VISION", f"Unexpected loop iteration error: {type(loop_exc).__name__}: {loop_exc}")
            await asyncio.sleep(0.2)

        # Frame pacing
        route = getattr(pipeline, '_route', None) or {}
        # Cheap scene groups must recover short transitions even while no OCR
        # facts are ready. Business OCR remains one job at a time.
        interval = min(sleep_interval, 1/30) if getattr(pipeline,'scene_roi_router',None) is not None and route.get('scene') not in ('IN_AUCTION','SETTLEMENT') else sleep_interval
        await asyncio.sleep(interval)
