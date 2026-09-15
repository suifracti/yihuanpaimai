# -*- coding: utf-8 -*-
"""Open source Main+Overlay on isolated video-replay history, then reopen.

Investigates and asserts:
1. Origin of 291 records: 1 isolated draft from current replay + 290 legacy records from legacy archive.
2. Selects record by exact replay matchId (draft_...) via DOM [data-record-id="..."], does not blind-pick item[0].
3. Verifies actual DOM elements in #history-detail-card and #history-auction-evidence for per-round bids and full intel.
4. Verifies filter stale card prevention and persistence across full app close and restart.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "app"), str(ROOT / "tools")]
from verify_p1_real_ui import (  # noqa: E402
    WS, eval_main, start_source, stop_source,
)

DATA = ROOT / "build" / "diagnosis_20260909" / "p2-video-recognition" / "data-root"
OUT = ROOT / "build" / "diagnosis_20260909" / "p2-video-recognition"


def get_target_match_id() -> str:
    hist_file = DATA / "history" / "异环拍卖数据.json"
    if not hist_file.is_file():
        raise FileNotFoundError(f"Missing replay history file: {hist_file}")
    data = json.loads(hist_file.read_text(encoding="utf-8"))
    records = data.get("records") or []
    if not records:
        raise ValueError(f"No records found in {hist_file}")
    return str(records[0].get("id"))


def get_source_breakdown() -> dict:
    hist_file = DATA / "history" / "异环拍卖数据.json"
    curr_count = 0
    if hist_file.is_file():
        d = json.loads(hist_file.read_text(encoding="utf-8"))
        curr_count = len(d.get("records") or [])

    legacy_file = ROOT / "异环拍卖数据.json"
    legacy_count = 0
    if legacy_file.is_file():
        d = json.loads(legacy_file.read_text(encoding="utf-8"))
        legacy_count = len(d.get("records") or [])

    return {
        "currentIsolatedRecords": curr_count,
        "legacyArchiveRecords": legacy_count,
        "totalExpectedDomItems": curr_count + legacy_count,
        "originExplanation": (
            f"core/main_window.js::buildHistoryItems() concatenates current records ({curr_count} from "
            f"isolated data-root history) and legacy archive records ({legacy_count} from repo-root "
            f"异环拍卖数据.json loaded via request_legacy_archive by app/legacy_archive.py). "
            f"Combined total rendered in DOM is {curr_count + legacy_count} items."
        ),
    }


async def read_history(target_match_id: str):
    import websockets
    async with websockets.connect(WS) as socket:
        await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
        await asyncio.sleep(0.5)
        view = await eval_main(socket, "showView('history'); dashboard.currentView")

        # Wait up to 8s for history items to appear in DOM
        dom_check = await eval_main(socket, f"""(async () => {{
            for (let i = 0; i < 40; i++) {{
                const items = document.querySelectorAll('#history-list .history-item');
                if (items.length > 0) break;
                await new Promise(r => setTimeout(r, 200));
            }}
            const items = document.querySelectorAll('#history-list .history-item');
            return items.length;
        }})()""")

        rec = await eval_main(socket, f"""JSON.stringify((() => {{
            const items = Array.from(document.querySelectorAll('#history-list .history-item'));
            const domCount = items.length;

            const targetMatchId = {json.dumps(target_match_id)};
            const targetItem = items.find(el => el.getAttribute('data-record-id') === targetMatchId);
            const foundTargetInDom = Boolean(targetItem);

            if (targetItem) {{
                targetItem.click();
            }}

            const detailCard = document.getElementById('history-detail-card');
            const placeholder = document.getElementById('history-detail-placeholder');
            const cardVisible = Boolean(detailCard && !detailCard.hidden);
            const placeholderVisible = Boolean(placeholder && !placeholder.hidden);

            const matchId = (document.getElementById('detail-match-id')?.textContent || '').trim();
            const matchTitle = (document.getElementById('detail-match-title')?.textContent || '').trim();
            const playedAt = (document.getElementById('detail-played-at')?.textContent || '').trim();
            const lifecycleBadge = (document.getElementById('detail-lifecycle-badge')?.textContent || '').trim();
            const qValue = (document.getElementById('detail-q')?.textContent || '').trim();
            const boxValue = (document.getElementById('detail-box')?.textContent || '').trim();

            // Read DOM evidence sections inside #history-auction-evidence
            const evidenceContainer = document.getElementById('history-auction-evidence');
            const evidenceParagraphs = Array.from(evidenceContainer ? evidenceContainer.querySelectorAll('p') : []).map(p => p.textContent);
            const evidenceGroups = Array.from(evidenceContainer ? evidenceContainer.querySelectorAll('.auction-evidence-group summary') : []).map(s => s.textContent);

            // Bids verification in DOM
            const round1BidText = evidenceParagraphs.find(t => t.includes('第 1 回合') || (t.includes('711111') && t.includes('555555')));
            const round2BidText = evidenceParagraphs.find(t => t.includes('第 2 回合') || (t.includes('1222222') && t.includes('666666')));

            // Intel verification in DOM
            const intel1Text = evidenceParagraphs.find(t => t.includes('千眼其一') || t.includes('17'));
            const intel2Text = evidenceParagraphs.find(t => t.includes('大型鉴定仪器') || t.includes('5件'));
            const intel3Text = evidenceParagraphs.find(t => t.includes('紫品计数仪器') || t.includes('4件'));

            // Verify filtering & stale card prevention
            dashboard.historyFilter.search = '__NONEXISTENT_KEYWORD__';
            applyHistoryFilters();
            const filteredItemsCount = document.querySelectorAll('#history-list .history-item').length;
            const staleCardHidden = Boolean(detailCard && detailCard.hidden);

            // Restore filter and re-click target
            dashboard.historyFilter.search = '';
            applyHistoryFilters();
            const restoredItemsCount = document.querySelectorAll('#history-list .history-item').length;
            const restoredTarget = Array.from(document.querySelectorAll('#history-list .history-item')).find(el => el.getAttribute('data-record-id') === targetMatchId);
            if (restoredTarget) restoredTarget.click();
            const restoredCardVisible = Boolean(detailCard && !detailCard.hidden);

            return {{
                view: dashboard.currentView,
                domCount,
                foundTargetInDom,
                targetMatchId,
                matchId,
                matchTitle,
                playedAt,
                lifecycleBadge,
                qValue,
                boxValue,
                evidenceGroupCount: evidenceGroups.length,
                evidenceParagraphsCount: evidenceParagraphs.length,
                domEvidence: {{
                    round1Present: Boolean(round1BidText),
                    round1Text: round1BidText || null,
                    round2Present: Boolean(round2BidText),
                    round2Text: round2BidText || null,
                    intelQPresent: Boolean(intel1Text),
                    intelQText: intel1Text || null,
                    intelDisplayPresent: Boolean(intel2Text),
                    intelDisplayText: intel2Text || null,
                    intelPurplePresent: Boolean(intel3Text),
                    intelPurpleText: intel3Text || null,
                }},
                stalePrevention: {{
                    filteredItemsCount,
                    staleCardHidden,
                    restoredItemsCount,
                    restoredCardVisible,
                }},
            }};
        }})())""")
        dom_count = rec.get("domCount", 0) if isinstance(rec, dict) else 0
        return {"historyView": view, "domCount": dom_count, "record": rec}


def one_open(tag: str, target_match_id: str) -> dict:
    log_path = OUT / f"ui-{tag}.log"
    env = os.environ.copy()
    python_path_parts = [
        str(ROOT / "core"),
        str(ROOT / "app"),
        "C:/Program Files/Python310/Lib/site-packages",
        "C:/Program Files/Python310/Lib/site-packages/win32",
        "C:/Program Files/Python310/Lib/site-packages/win32/lib",
        "C:/Program Files/Python310/Lib/site-packages/Pythonwin",
    ]
    env["PYTHONPATH"] = ";".join(python_path_parts)
    env.update({
        "YIHUAN_DATA_ROOT": str(DATA),
        "LOCALAPPDATA": str(OUT / f"local-app-data-{tag}"),
        "NTE_DISABLE_VISION": "1",
        "NTE_DISABLE_ICON": "1",
        "NTE_ALLOW_HUD_CAPTURE": "1",
        "NTE_DEBUG": "1",
        "NTE_LOG_FILE": str(log_path),
    })
    py = Path(sys.executable)
    command = [str(py), str(ROOT / "app" / "main.py")]
    process, probe, main_win, hud = start_source(command, env, log_path)
    try:
        payload = asyncio.run(read_history(target_match_id))
        stop_source(process, probe, main_win)
        process = None
        return {"ok": True, **payload}
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    target_match_id = get_target_match_id()
    breakdown = get_source_breakdown()
    print(f"Target replay matchId: {target_match_id}")
    print(f"Source breakdown: {breakdown}")

    first = one_open("open1", target_match_id)
    second = one_open("open2", target_match_id)

    f_rec = first.get("record") or {}
    s_rec = second.get("record") or {}

    retained = bool(
        f_rec.get("foundTargetInDom") and
        s_rec.get("foundTargetInDom") and
        f_rec.get("matchId") == target_match_id and
        s_rec.get("matchId") == target_match_id
    )

    f_ev = f_rec.get("domEvidence") or {}
    s_ev = s_rec.get("domEvidence") or {}

    bids_verified = bool(
        f_ev.get("round1Present") and f_ev.get("round2Present") and
        s_ev.get("round1Present") and s_ev.get("round2Present")
    )

    intel_verified = bool(
        f_ev.get("intelQPresent") and f_ev.get("intelDisplayPresent") and f_ev.get("intelPurplePresent") and
        s_ev.get("intelQPresent") and s_ev.get("intelDisplayPresent") and s_ev.get("intelPurplePresent")
    )

    dom_ok = bool(f_rec.get("domCount", 0) >= breakdown["totalExpectedDomItems"] and s_rec.get("domCount", 0) >= breakdown["totalExpectedDomItems"])
    stale_ok = bool(
        (f_rec.get("stalePrevention") or {}).get("staleCardHidden") and
        (s_rec.get("stalePrevention") or {}).get("staleCardHidden")
    )

    result = {
        "targetMatchId": target_match_id,
        "sourceBreakdown": breakdown,
        "first": first,
        "second": second,
        "domCountMatchesBreakdown": dom_ok,
        "retainedByExactMatchId": retained,
        "roundQuotesDomVerified": bids_verified,
        "intelSemanticsDomVerified": intel_verified,
        "stalePreventionOk": stale_ok,
    }

    result["status"] = "PASS" if retained and bids_verified and intel_verified and dom_ok and stale_ok else "PARTIAL"
    (OUT / "ui-reopen.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "retained": result["retainedByExactMatchId"],
        "domCount": f_rec.get("domCount"),
        "bidsDomVerified": result["roundQuotesDomVerified"],
        "intelDomVerified": result["intelSemanticsDomVerified"],
        "staleOk": result["stalePreventionOk"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
