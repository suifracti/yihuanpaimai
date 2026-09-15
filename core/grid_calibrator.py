"""
Neverness to Everness (异环) - 仓位网格连通域标定器 (v0.65)
功能：
  1. 定位仓库网格：横 10 列 × 竖 25 行（可滚动）
  2. HSV 颜色空间多品质切片 (绿/蓝/紫/金/红/轮廓)
  3. 4-连通域分析提取连通块形状
  4. 联动 ShapeMatcher 输出符合 v0.6 的 knownGoldGroups 数组
"""

import cv2
import numpy as np
import json
import os
from typing import List, Dict, Any, Tuple, Optional
from shape_matcher import ShapeMatcher

class GridCalibrator:
    def __init__(self, catalog_path: Optional[str] = None):
        self.matcher = None
        if catalog_path and os.path.exists(catalog_path):
            self.matcher = ShapeMatcher(catalog_path)

        # 1080P 右侧仓库可视区。完整仓库 10 列 × 25 行，当前窗口大约能看见前若干行。
        self.grid_bounds = (1420, 230, 1860, 980)
        self.rows = 25
        self.cols = 10

    def analyze_grid(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        输入游戏画面，输出 10x25 仓库状态矩阵与连通块 OR 候选组
        """
        h, w = frame.shape[:2]
        if (w, h) != (1920, 1080):
            frame = cv2.resize(frame, (1920, 1080))

        gx1, gy1, gx2, gy2 = self.grid_bounds
        grid_roi = frame[gy1:gy2, gx1:gx2]
        cell_w = (gx2 - gx1) / self.cols
        cell_h = (gy2 - gy1) / self.rows

        # 25 格分类状态: 0=未知/暗色, 1=绿, 2=紫, 3=金, 4=红, 5=轮廓橘黄
        grid_matrix = np.zeros((self.rows, self.cols), dtype=int)

        hsv = cv2.cvtColor(grid_roi, cv2.COLOR_BGR2HSV)

        for r in range(self.rows):
            for c in range(self.cols):
                cx1 = int(c * cell_w)
                cy1 = int(r * cell_h)
                cx2 = int((c + 1) * cell_w)
                cy2 = int((r + 1) * cell_h)
                
                # 采样中心 50% 区域避免边框干扰
                pad_x = int(cell_w * 0.25)
                pad_y = int(cell_h * 0.25)
                cell_hsv = hsv[cy1+pad_y:cy2-pad_y, cx1+pad_x:cx2-pad_x]

                state = self._classify_cell(cell_hsv)
                grid_matrix[r, c] = state

        # 连通域分析提取连通块 (Blobs)
        blobs = self._find_connected_blobs(grid_matrix)

        # 生成 v0.6 OR 候选组
        gold_groups = []
        purple_groups = []
        if self.matcher:
            for blob in blobs:
                q_tag = blob["quality"]
                w_b = blob["width"]
                h_b = blob["height"]
                if q_tag == "金":
                    og = self.matcher.generate_or_group("金", w_b, h_b)
                    if og["prices"]:
                        gold_groups.append([og["prices"], 1])
                elif q_tag == "紫":
                    og = self.matcher.generate_or_group("紫", w_b, h_b)
                    if og["prices"]:
                        purple_groups.append([og["prices"], 1])

        return {
            "matrix": grid_matrix.tolist(),
            "flatCells": grid_matrix.flatten().tolist(),
            "blobs": blobs,
            "goldGroups": gold_groups,
            "purpleGroups": purple_groups
        }

    def _classify_cell(self, cell_hsv: np.ndarray) -> int:
        if cell_hsv.size == 0:
            return 0
        mean_h = np.mean(cell_hsv[:, :, 0])
        mean_s = np.mean(cell_hsv[:, :, 1])
        mean_v = np.mean(cell_hsv[:, :, 2])

        if mean_v < 40 or mean_s < 30:
            return 0 # 暗色/未揭示
        
        # 绿色 (H: 35~85)
        if 35 <= mean_h <= 85:
            return 1
        # 紫色 (H: 125~165)
        elif 125 <= mean_h <= 165:
            return 2
        # 金色/橙黄 (H: 15~35)
        elif 15 <= mean_h <= 35:
            return 3
        # 红色 (H: 0~12 or 165~180)
        elif mean_h <= 12 or mean_h >= 165:
            return 4

        return 0

    def _find_connected_blobs(self, matrix: np.ndarray) -> List[Dict[str, Any]]:
        visited = np.zeros_like(matrix, dtype=bool)
        blobs = []
        quality_map = {1: "绿", 2: "紫", 3: "金", 4: "红"}

        for r in range(self.rows):
            for c in range(self.cols):
                val = matrix[r, c]
                if val in quality_map and not visited[r, c]:
                    # BFS 搜索连通分量
                    q = [(r, c)]
                    visited[r, c] = True
                    cells = [(r, c)]

                    while q:
                        cr, cc = q.pop(0)
                        for nr, nc in [(cr+1, cc), (cr-1, cc), (cr, cc+1), (cr, cc-1)]:
                            if 0 <= nr < self.rows and 0 <= nc < self.cols:
                                if not visited[nr, nc] and matrix[nr, nc] == val:
                                    visited[nr, nc] = True
                                    cells.append((nr, nc))
                                    q.append((nr, nc))

                    min_r = min(x[0] for x in cells)
                    max_r = max(x[0] for x in cells)
                    min_c = min(x[1] for x in cells)
                    max_c = max(x[1] for x in cells)
                    w = max_c - min_c + 1
                    h = max_r - min_r + 1

                    blobs.append({
                        "quality": quality_map[val],
                        "anchor": (min_r, min_c),
                        "width": w,
                        "height": h,
                        "cellCount": len(cells),
                        "cells": cells
                    })

        return blobs

if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    calibrator = GridCalibrator(os.path.join(project_root, "assets", "catalog_065.json"))
    print("=== 25 格网格连通域标定器测试 ===")
    
    # 构造一个 5x5 模拟网格 (左上 2x2 金单反相机)
    test_img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    gx1, gy1, gx2, gy2 = calibrator.grid_bounds
    cw = (gx2 - gx1) // 5
    ch = (gy2 - gy1) // 5
    # 填充 (0,2)~(1,3) 为金色
    test_img[gy1:gy1+2*ch, gx1+2*cw:gx1+4*cw] = (0, 200, 255) # BGR Yellow
    
    res = calibrator.analyze_grid(test_img)
    print("标定输出:")
    print(f"  - 识别连通块数量: {len(res['blobs'])} 个")
    for b in res['blobs']:
        print(f"    * 连通块: 品质={b['quality']} | 尺寸={b['width']}x{b['height']} | 占格={b['cellCount']} | 锚点={b['anchor']}")
    print(f"  - 自动生成 GoldGroups: {res['goldGroups']}")
