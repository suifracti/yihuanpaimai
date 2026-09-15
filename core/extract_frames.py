import os
import cv2
import numpy as np

video_path = r"C:\Users\Administrator\Videos\2026-08-14 18-12-48.mkv"
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
out_dir = os.path.join(project_root, "assets", "replay_frames")
os.makedirs(out_dir, exist_ok=True)

cap = cv2.VideoCapture(video_path)
fps = cap.get(cv2.CAP_PROP_FPS)
print(f"Video FPS: {fps}")

# 抽取关键帧: 30s(备战), 60s(第1轮), 120s(第2轮), 180s(第3轮出价), 210s(第3轮结束), 240s(第4轮), 270s(第5轮结算), 450s(第2局第4轮), 480s(第2局结算)
for sec in [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 360, 420, 450, 480]:
    frame_no = int(sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
    ret, frame = cap.read()
    if ret:
        out_p = os.path.join(out_dir, f"sec_{sec:03d}.jpg")
        # 兼容 Windows 中文路径写入
        success, encoded = cv2.imencode(".jpg", frame)
        if success:
            encoded.tofile(out_p)
            print(f"Extracted and saved {out_p}")

cap.release()
print("All frames extracted successfully!")
