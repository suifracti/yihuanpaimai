"""
Neverness to Everness (异环) - 2D 形状几何拓扑匹配引擎 (v0.65)
功能：
  1. 解析 227 藏品的 5x5 Shape Mask (如 '1100011000...')
  2. 根据网格连通块的 [品质] + [宽*高/掩码] 进行碰撞过滤
  3. 自动生成符合 v0.6 规范的极小 OR 互斥候选组 (knownGoldGroups / knownPurpleGroups)
"""

import json
import os
from typing import List, Dict, Any, Tuple, Optional

class ShapeMatcher:
    def __init__(self, catalog_path: str):
        self.catalog = []
        self.shape_index = {} # Key: (quality, width, height, cellCount) -> List[Item]
        
        if os.path.exists(catalog_path):
            with open(catalog_path, 'r', encoding='utf-8') as f:
                self.catalog = json.load(f)
            self._build_index()

    def _build_index(self):
        for item in self.catalog:
            q = item.get("Quality", "金")
            w = item.get("Width", 1)
            h = item.get("Height", 1)
            cells = item.get("Cells", w * h)
            key = (q, w, h, cells)
            if key not in self.shape_index:
                self.shape_index[key] = []
            self.shape_index[key].append(item)

    def match_candidates(self, quality: str, width: int, height: int, cell_count: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        根据品质和几何外框筛选可能的所有藏品
        """
        if cell_count is None:
            cell_count = width * height

        # 考虑旋转可能 (W x H 或 H x W)
        candidates = []
        for (w, h) in [(width, height), (height, width)]:
            key = (quality, w, h, cell_count)
            if key in self.shape_index:
                for it in self.shape_index[key]:
                    if it not in candidates:
                        candidates.append(it)

        # 如果没有严格匹配到 cell_count，放宽到长宽约束
        if not candidates:
            for it in self.catalog:
                if it.get("Quality") == quality:
                    if (it.get("Width") == width and it.get("Height") == height) or \
                       (it.get("Width") == height and it.get("Height") == width):
                        if it not in candidates:
                            candidates.append(it)

        return candidates

    def generate_or_group(self, quality: str, width: int, height: int) -> Dict[str, Any]:
        """
        生成送入 v0.6 求解器的 OR 互斥组结构:
        例如: { "prices": [38500, 51077], "count": 1, "names": ["金色单反相机", "大理石雕像"] }
        """
        items = self.match_candidates(quality, width, height)
        prices = sorted(list(set([it["Value"] for it in items if "Value" in it])))
        names = [it["Name"] for it in items]
        
        return {
            "quality": quality,
            "shape": f"{width}x{height}",
            "candidateCount": len(items),
            "prices": prices,
            "names": names,
            "isDeterministic": len(prices) == 1,
            "lockedValue": prices[0] if len(prices) == 1 else None
        }

if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cat_file = os.path.join(project_root, "assets", "catalog_065.json")
    matcher = ShapeMatcher(cat_file)
    
    print("=== 2D 形状几何拓扑匹配引擎自检 ===")
    # 测试 1: 金色 2x2 单反相机/大雕像
    res_gold_2x2 = matcher.generate_or_group("金", 2, 2)
    print("\n[测试 1: 金色 2x2 形状候选匹配]")
    print(f"  - 候选数量: {res_gold_2x2['candidateCount']} 件")
    print(f"  - 候选价格池: {res_gold_2x2['prices']}")
    print(f"  - 包含藏品: {res_gold_2x2['names']}")

    # 测试 2: 紫色 1x2 药水/随身听
    res_purple_1x2 = matcher.generate_or_group("紫", 1, 2)
    print("\n[测试 2: 紫色 1x2 形状候选匹配]")
    print(f"  - 候选数量: {res_purple_1x2['candidateCount']} 件")
    print(f"  - 候选价格池: {res_purple_1x2['prices']}")
