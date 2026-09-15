"""Phase 1+2 离线验收：角色模板延迟、刷新 generation、对比改造前 4.3–6.2s。"""

from __future__ import annotations

import os
import sys
import time
import statistics

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))

from character_matcher import CharacterMatcher, default_template_dir
from vision_pipeline import NTEVisionPipeline


def load(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def pct(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, max(0, int(round((p / 100.0) * (len(values) - 1)))))
    return values[idx]


def main():
    daf = load(os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby", "t0022.jpg"))
    han = load(os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby2", "t0048.jpg"))
    frames = [daf, han] * 6
    matcher = CharacterMatcher(template_dir=default_template_dir(os.path.join(PROJECT_ROOT, "assets", "catalog_065.json")))

    # warmup
    matcher.identify(daf)

    switch_ms = []
    scores = []
    wrong = 0
    expected = ["达芙蒂尔", "哈尼亚"] * 6
    for frame, name in zip(frames, expected):
        t0 = time.perf_counter()
        hit = matcher.identify(frame)
        dt = (time.perf_counter() - t0) * 1000
        switch_ms.append(dt)
        scores.append((hit.get("character"), hit.get("score"), hit.get("secondScore"), dt))
        if hit.get("character") != name:
            wrong += 1
        print(f"SWITCH {name}: {dt:.1f}ms char={hit.get('character')} score={hit.get('score'):.3f} second={hit.get('secondScore'):.3f} accepted={hit.get('accepted')}")

    pipe = NTEVisionPipeline()
    ocr0 = pipe.ocr_call_count
    scan0 = pipe.character_matcher.scan_count
    t0 = time.perf_counter()
    loops = 0
    while time.perf_counter() - t0 < 10.0:
        pipe.process_frame(daf)
        loops += 1
    idle_s = time.perf_counter() - t0
    ocr_calls = pipe.ocr_call_count - ocr0
    scans = pipe.character_matcher.scan_count - scan0

    refresh_ms = []
    ids = []
    from main import request_force_refresh, LATEST_PAYLOAD
    for i in range(10):
        t0 = time.perf_counter()
        rid = request_force_refresh()
        ids.append(rid)
        pipe.reset_session_state()
        ctx = pipe.process_frame(frames[i % 2], force_refresh=True)
        dt = (time.perf_counter() - t0) * 1000
        refresh_ms.append(dt)
        print(f"REFRESH {rid}: {dt:.1f}ms char={ctx.get('lobbyCharacter')} source={ctx.get('lobbyCharacterSource')} pending_label={LATEST_PAYLOAD.get('lobbyCharacterLabel')}")

    print("\n=== SUMMARY ===")
    print(f"idle_10s loops={loops} ocr_calls={ocr_calls} template_scans={scans} seconds={idle_s:.2f}")
    print(f"switch n={len(switch_ms)} wrong={wrong} p50={pct(switch_ms,50):.1f}ms p95={pct(switch_ms,95):.1f}ms mean={statistics.mean(switch_ms):.1f}ms")
    print(f"refresh n={len(refresh_ms)} unique_ids={len(set(ids))} p50={pct(refresh_ms,50):.1f}ms p95={pct(refresh_ms,95):.1f}ms")
    print("baseline_before=4300-6200ms character_ocr_path")
    print(f"baseline_after_p50={pct(switch_ms,50):.1f}ms baseline_after_p95={pct(switch_ms,95):.1f}ms")


if __name__ == "__main__":
    main()
