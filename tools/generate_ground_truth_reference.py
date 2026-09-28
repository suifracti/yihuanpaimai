# -*- coding: utf-8 -*-
"""Generate independent ground truth reference from raw video frames and stitched canvas."""
import json
from pathlib import Path
import sys
import cv2

ROOT = Path(__file__).resolve().parents[1]
stitched_path = ROOT / "build" / "diagnosis_20260909" / "p3-warehouse" / "video_audit" / "stitched_warehouse.png"
canvas = cv2.imread(str(stitched_path))
cell_w = 75.0
cell_h = 75.0

crop_dir = ROOT / "assets" / "items" / "ground_truth_reference_144037"
crop_dir.mkdir(parents=True, exist_ok=True)

items = [
    # Row 0
    {'id': 'ref_144037_01', 'r': 0, 'c': 0, 'w': 2, 'h': 3, 'desc': '蓝色品质 2x3 纵向矩形单元', 'quality': 'blue', 't': 158.0, 'basis': 'Distinct blue border, 2 cols by 3 rows, visible at top position'},
    {'id': 'ref_144037_02', 'r': 0, 'c': 2, 'w': 1, 'h': 3, 'desc': '蓝色品质 1x3 纵向条形单元', 'quality': 'blue', 't': 158.0, 'basis': 'Vertical crystal spanning 1 col by 3 rows, blue border'},
    {'id': 'ref_144037_03', 'r': 0, 'c': 3, 'w': 1, 'h': 1, 'desc': '绿色品质 1x1 单格单元', 'quality': 'green', 't': 158.0, 'basis': 'Single cell 1x1 green background'},
    {'id': 'ref_144037_04', 'r': 0, 'c': 4, 'w': 1, 'h': 1, 'desc': '绿色品质 1x1 单格单元', 'quality': 'green', 't': 158.0, 'basis': 'Single cell 1x1 green background'},
    {'id': 'ref_144037_05', 'r': 0, 'c': 5, 'w': 2, 'h': 1, 'desc': '蓝色品质 2x1 横向双格单元', 'quality': 'blue', 't': 158.0, 'basis': 'Horizontal 2x1 cell blue background'},
    {'id': 'ref_144037_06', 'r': 0, 'c': 7, 'w': 1, 'h': 1, 'desc': '蓝色品质 1x1 单格单元', 'quality': 'blue', 't': 158.0, 'basis': 'Single cell 1x1 blue background'},
    {'id': 'ref_144037_07', 'r': 0, 'c': 8, 'w': 2, 'h': 1, 'desc': '绿色品质 2x1 横向双格单元', 'quality': 'green', 't': 158.0, 'basis': 'Horizontal 2x1 cell green background'},
    # Row 1-3
    {'id': 'ref_144037_08', 'r': 1, 'c': 3, 'w': 3, 'h': 3, 'desc': '蓝色品质 3x3 方形单元', 'quality': 'blue', 't': 158.0, 'basis': 'Large 3x3 square framed object with blue border'},
    {'id': 'ref_144037_09', 'r': 1, 'c': 6, 'w': 3, 'h': 3, 'desc': '红色品质 3x3 方形复合单元', 'quality': 'red', 't': 158.0, 'basis': '3x3 square structure with internal compartments, red border'},
    {'id': 'ref_144037_10', 'r': 1, 'c': 9, 'w': 1, 'h': 1, 'desc': '紫色品质 1x1 单格单元', 'quality': 'purple', 't': 158.0, 'basis': 'Single cell 1x1 purple border'},
    {'id': 'ref_144037_11', 'r': 2, 'c': 9, 'w': 1, 'h': 2, 'desc': '红色品质 1x2 纵向双格单元', 'quality': 'red', 't': 158.0, 'basis': 'Vertical 1x2 package with red border'},
    {'id': 'ref_144037_12', 'r': 3, 'c': 0, 'w': 2, 'h': 2, 'desc': '紫色品质 2x2 方形单元', 'quality': 'purple', 't': 158.0, 'basis': '2x2 purple border unit'},
    {'id': 'ref_144037_13', 'r': 3, 'c': 2, 'w': 1, 'h': 1, 'desc': '绿色品质 1x1 单格单元', 'quality': 'green', 't': 158.0, 'basis': 'Single cell 1x1 green border'},
    # Row 4-5
    {'id': 'ref_144037_14', 'r': 4, 'c': 2, 'w': 2, 'h': 2, 'desc': '金色品质 2x2 方形单元', 'quality': 'gold', 't': 158.0, 'basis': '2x2 gold border unit'},
    {'id': 'ref_144037_15', 'r': 4, 'c': 4, 'w': 3, 'h': 1, 'desc': '绿色品质 3x1 横向三格单元', 'quality': 'green', 't': 158.0, 'basis': 'Horizontal 3x1 green border'},
    {'id': 'ref_144037_16', 'r': 4, 'c': 7, 'w': 2, 'h': 1, 'desc': '金色品质 2x1 横向双格单元', 'quality': 'gold', 't': 158.0, 'basis': 'Horizontal 2x1 gold border'},
    {'id': 'ref_144037_17', 'r': 4, 'c': 9, 'w': 1, 'h': 1, 'desc': '蓝色品质 1x1 单格单元', 'quality': 'blue', 't': 158.0, 'basis': 'Single cell 1x1 blue border'},
    {'id': 'ref_144037_18', 'r': 5, 'c': 0, 'w': 2, 'h': 1, 'desc': '紫色品质 2x1 横向双格单元', 'quality': 'purple', 't': 158.0, 'basis': 'Horizontal 2x1 purple border'},
    {'id': 'ref_144037_19', 'r': 5, 'c': 4, 'w': 2, 'h': 2, 'desc': '金色品质 2x2 方形单元', 'quality': 'gold', 't': 160.0, 'basis': '2x2 gold border unit'},
    {'id': 'ref_144037_20', 'r': 5, 'c': 6, 'w': 1, 'h': 1, 'desc': '灰色品质 1x1 单格单元', 'quality': 'grey', 't': 160.0, 'basis': 'Single cell 1x1 grey border'},
    {'id': 'ref_144037_21', 'r': 5, 'c': 7, 'w': 1, 'h': 1, 'desc': '金色品质 1x1 单格单元', 'quality': 'gold', 't': 160.0, 'basis': 'Single cell 1x1 gold border'},
    {'id': 'ref_144037_22', 'r': 5, 'c': 8, 'w': 2, 'h': 3, 'desc': '灰色品质 2x3 纵向矩形单元', 'quality': 'grey', 't': 160.0, 'basis': '2x3 grey border unit'},
    # Row 6-7
    {'id': 'ref_144037_23', 'r': 6, 'c': 0, 'w': 4, 'h': 4, 'desc': '绿色品质 4x4 大型方形单元', 'quality': 'green', 't': 160.0, 'basis': 'Large 4x4 green border occupying cols 0-3, rows 6-9'},
    {'id': 'ref_144037_24', 'r': 6, 'c': 6, 'w': 1, 'h': 1, 'desc': '紫色品质 1x1 单格单元', 'quality': 'purple', 't': 160.0, 'basis': 'Single cell 1x1 purple border'},
    {'id': 'ref_144037_25', 'r': 6, 'c': 7, 'w': 1, 'h': 2, 'desc': '金色品质 1x2 纵向双格单元', 'quality': 'gold', 't': 160.0, 'basis': 'Vertical 1x2 gold border unit'},
    {'id': 'ref_144037_26', 'r': 7, 'c': 4, 'w': 2, 'h': 1, 'desc': '金色品质 2x1 横向双格单元', 'quality': 'gold', 't': 162.0, 'basis': 'Horizontal 2x1 gold border'},
    {'id': 'ref_144037_27', 'r': 7, 'c': 6, 'w': 1, 'h': 1, 'desc': '蓝色品质 1x1 单格单元', 'quality': 'blue', 't': 162.0, 'basis': 'Single cell 1x1 blue border'},
    # Row 8-12
    {'id': 'ref_144037_28', 'r': 8, 'c': 4, 'w': 5, 'h': 5, 'desc': '红色品质 5x5 巨型方形单元', 'quality': 'red', 't': 164.0, 'basis': 'Massive 5x5 red border unit spanning cols 4-8, rows 8-12'},
    {'id': 'ref_144037_29', 'r': 8, 'c': 9, 'w': 1, 'h': 3, 'desc': '蓝色品质 1x3 纵向条形单元', 'quality': 'blue', 't': 164.0, 'basis': 'Vertical 1x3 blue border unit spanning col 9, rows 8-10'},
    {'id': 'ref_144037_30', 'r': 10, 'c': 0, 'w': 4, 'h': 3, 'desc': '金色品质 4x3 横向矩形单元', 'quality': 'gold', 't': 164.0, 'basis': 'Wide 4x3 gold border unit spanning cols 0-3, rows 10-12'},
    {'id': 'ref_144037_31', 'r': 11, 'c': 9, 'w': 1, 'h': 5, 'desc': '金色品质 1x5 纵向长条单元', 'quality': 'gold', 't': 166.0, 'basis': 'Vertical 1x5 gold border unit spanning col 9, rows 11-15'},
    # Row 13-17
    {'id': 'ref_144037_32', 'r': 13, 'c': 0, 'w': 4, 'h': 1, 'desc': '金色品质 4x1 横向长条单元', 'quality': 'gold', 't': 166.0, 'basis': 'Long horizontal 4x1 gold border spanning cols 0-3, row 13'},
    {'id': 'ref_144037_33', 'r': 13, 'c': 4, 'w': 2, 'h': 2, 'desc': '蓝色品质 2x2 方形单元', 'quality': 'blue', 't': 166.0, 'basis': '2x2 blue border spanning cols 4-5, rows 13-14'},
    {'id': 'ref_144037_34', 'r': 13, 'c': 6, 'w': 3, 'h': 2, 'desc': '蓝色品质 3x2 横向矩形单元', 'quality': 'blue', 't': 166.0, 'basis': '3x2 blue border spanning cols 6-8, rows 13-14'},
    {'id': 'ref_144037_35', 'r': 14, 'c': 0, 'w': 2, 'h': 2, 'desc': '灰色品质 2x2 方形单元', 'quality': 'grey', 't': 168.0, 'basis': '2x2 grey border unit spanning cols 0-1, rows 14-15'},
    {'id': 'ref_144037_36', 'r': 14, 'c': 2, 'w': 2, 'h': 1, 'desc': '蓝色品质 2x1 横向双格单元', 'quality': 'blue', 't': 168.0, 'basis': 'Horizontal 2x1 blue border spanning cols 2-3, row 14'},
    {'id': 'ref_144037_37', 'r': 15, 'c': 2, 'w': 3, 'h': 3, 'desc': '红色品质 3x3 方形复合单元', 'quality': 'red', 't': 168.0, 'basis': '3x3 red border spanning cols 2-4, rows 15-17'},
    {'id': 'ref_144037_38', 'r': 15, 'c': 5, 'w': 2, 'h': 2, 'desc': '绿色品质 2x2 方形单元', 'quality': 'green', 't': 168.0, 'basis': '2x2 green border spanning cols 5-6, rows 15-16'},
    {'id': 'ref_144037_39', 'r': 15, 'c': 7, 'w': 2, 'h': 1, 'desc': '蓝色品质 2x1 横向双格单元', 'quality': 'blue', 't': 168.0, 'basis': 'Horizontal 2x1 blue border ticket card spanning cols 7-8, row 15'},
]

ref_data = {
    'metadata': {
        'videoPath': r'D:\yihuanpaimai\data\videos\2026-09-08 14-40-37.mkv',
        'annotatedBy': 'independent_visual_inspection_with_stitched_cross_check',
        'provenanceNote': (
            'Items and boundaries established from raw video frames and stitched 10x25 canvas. '
            'Algorithm candidate lists were reviewed previously, so canonicalName is kept as null / None '
            'to avoid unconfirmed identity bias. Visual descriptions and exact cell borders '
            'were independently verified against raw pixel grid.'
        ),
        'boardDimensions': {'columns': 10, 'rows': 25, 'cellWidthPx': 75, 'cellHeightPx': 75},
        'totalItemsGroundTruth': len(items),
        'totalOccupiedCells': sum(it['w'] * it['h'] for it in items),
        'totalEmptyCells': 250 - sum(it['w'] * it['h'] for it in items),
    },
    'items': []
}

for it in items:
    r, c, w, h = it['r'], it['c'], it['w'], it['h']
    y1 = int(round(r * cell_h))
    y2 = int(round((r + h) * cell_h))
    x1 = int(round(c * cell_w))
    x2 = int(round((c + w) * cell_w))

    crop = canvas[y1:y2, x1:x2]
    crop_filename = f"{it['id']}.png"
    crop_file_path = crop_dir / crop_filename
    cv2.imwrite(str(crop_file_path), crop)

    ref_data['items'].append({
        'referenceId': it['id'],
        'gridBoundingBox': {
            'row': r,
            'col': c,
            'width': w,
            'height': h,
            'shape': f"{w}x{h}",
        },
        'pixelBboxOnCanvas': [x1, y1, x2, y2],
        'quality': it['quality'],
        'visualDescription': it['desc'],
        'canonicalName': None,
        'identityStatus': 'UNKNOWN_OR_CANDIDATE_UNCONFIRMED',
        'videoSourceFrameTimeSec': it['t'],
        'observationBasis': it['basis'],
        'localCropPath': str(crop_file_path.relative_to(ROOT)).replace('\\', '/'),
    })

sys.path.insert(0, str(ROOT / "core"))
from catalog_validator import validate_catalog_record
for item_record in ref_data['items']:
    validate_catalog_record(item_record)

out_json = ROOT / "assets" / "items" / "video_ground_truth_reference_144037.json"
out_json.parent.mkdir(parents=True, exist_ok=True)
out_json.write_text(json.dumps(ref_data, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"Validated and generated {len(items)} reference items and saved to {out_json}")
