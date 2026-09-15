import cv2
import numpy as np
import os
import re
from pathlib import Path
from rapidocr_onnxruntime import RapidOCR

ocr = RapidOCR()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
frame_candidates = [
    PROJECT_ROOT / "assets" / "video_frames",
    PROJECT_ROOT / "assets" / "replay_frames",
]
frame_dir = next((str(p) for p in frame_candidates if p.is_dir()), str(frame_candidates[0]))

def parse_bid_value(text: str) -> int:
    text = text.strip().replace(",", "").replace(" ", "").upper()
    if text.endswith("K"):
        num_part = text[:-1]
        try:
            return int(float(num_part) * 1000)
        except Exception:
            return 0
    elif text.endswith("W"):
        num_part = text[:-1]
        try:
            return int(float(num_part) * 10000)
        except Exception:
            return 0
    else:
        # 纯数字
        cleaned = re.sub(r"[^\d]", "", text)
        if cleaned.isdigit():
            return int(cleaned)
    return 0

def extract_bids_from_frame(img):
    h, w, _ = img.shape
    res, _ = ocr(img)
    if not res:
        return {}

    # 左侧出价区域: X: [0.25, 0.38], Y: [0.20, 0.70]
    # 4 个玩家槽位大约在 Y: [0.22~0.32], [0.33~0.43], [0.44~0.54], [0.55~0.65]
    slots = [
        {"slot": 1, "isMe": True, "name": "玩家本人", "bid": 0, "y_range": (0.20, 0.32)},
        {"slot": 2, "isMe": False, "name": "对手1", "bid": 0, "y_range": (0.33, 0.43)},
        {"slot": 3, "isMe": False, "name": "对手2", "bid": 0, "y_range": (0.44, 0.54)},
        {"slot": 4, "isMe": False, "name": "对手3", "bid": 0, "y_range": (0.55, 0.66)}
    ]

    for box, text, score in res:
        x_min = min(b[0] for b in box)
        y_min = min(b[1] for b in box)
        nx = x_min / w
        ny = y_min / h

        # 检查是否在出价区域 (X: 0.25 ~ 0.38)
        if 0.24 <= nx <= 0.38:
            for s in slots:
                if s["y_range"][0] <= ny <= s["y_range"][1]:
                    # 识别姓名
                    if not re.search(r"[\dKk]", text) and len(text) >= 1 and s["name"].startswith("对手") or (s["isMe"] and s["name"] == "玩家本人"):
                        s["name"] = text.strip()
                    # 识别叫价
                    bid_val = parse_bid_value(text)
                    if bid_val > 0 and bid_val != s["bid"]:
                        s["bid"] = bid_val

    return slots

if __name__ == "__main__":
    for fname in ["sec_120.jpg", "sec_180.jpg", "sec_450.jpg"]:
        p = os.path.join(frame_dir, fname)
        if os.path.exists(p):
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            slots = extract_bids_from_frame(img)
            print(f"\n--- {fname} 4人出价识别结果 ---")
            for s in slots:
                print(f"  Slot {s['slot']} ({'我' if s['isMe'] else '对手'} - {s['name']}): 叫价 = {s['bid']:,}")
