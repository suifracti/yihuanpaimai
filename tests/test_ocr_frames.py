import cv2
import numpy as np
import os
import sys
from rapidocr_onnxruntime import RapidOCR

def run_frame_ocr():
    ocr = RapidOCR()
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    frame_candidates = [
        os.path.join(project_root, "assets", "video_frames"),
        os.path.join(project_root, "assets", "replay_frames"),
    ]
    frame_dir = next((p for p in frame_candidates if os.path.isdir(p)), frame_candidates[0])
    out_txt = os.path.join(project_root, "tests", "ocr_results.txt")

    with open(out_txt, "w", encoding="utf-8") as out:
        for fname in ["sec_030.jpg", "sec_060.jpg", "sec_120.jpg", "sec_180.jpg", "sec_210.jpg", "sec_270.jpg", "sec_360.jpg", "sec_420.jpg", "sec_450.jpg", "sec_480.jpg"]:
            p = os.path.join(frame_dir, fname)
            if not os.path.exists(p):
                continue
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                out.write(f"Failed to load {fname}\n")
                continue
            h, w, _ = img.shape
            res, _ = ocr(img)
            out.write(f"\n================ 帧 {fname} ({w}x{h}) ================\n")
            if res:
                for box, text, score in res:
                    x_min = int(min(b[0] for b in box))
                    y_min = int(min(b[1] for b in box))
                    nx = x_min / w
                    ny = y_min / h
                    out.write(f"  [X: {nx:.3f}, Y: {ny:.3f}] (px: {x_min:4d},{y_min:4d}) text: \"{text}\"\n")

    print("OCR successfully executed and written to ocr_results.txt!")

if __name__ == "__main__":
    run_frame_ocr()
