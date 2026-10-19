"""Cheap text-shape anchors before weak navigation color heuristics."""
from functools import lru_cache
import hashlib
import json
import cv2
import numpy as np

from visual_catalog import asset_root
from roi_scaler import ROIScaler


@lru_cache(maxsize=1)
def _settlement_title():
    path = asset_root() / 'assets/scene_anchors/settlement_title.png'
    if not path.is_file():
        return None
    return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)


def settlement_title_visible(frame):
    template = _settlement_title()
    if template is None or frame is None or frame.size == 0:
        return False
    h, w = frame.shape[:2]
    crop = frame[round(h*125/1080):round(h*220/1080), round(w*60/1920):round(w*355/1920)]
    if crop.size == 0:
        return False
    gray = cv2.cvtColor(cv2.resize(crop, (295, 95)), cv2.COLOR_BGR2GRAY)
    score = cv2.minMaxLoc(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED))[1]
    return bool(np.isfinite(score) and score >= .88)


@lru_cache(maxsize=1)
def _settlement_controls():
    result = []
    for name in ('settlement_sale_label', 'settlement_exit_label'):
        path = asset_root() / ('assets/scene_anchors/' + name + '.png')
        result.append(cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)
                      if path.is_file() else None)
    return result


def settlement_controls_visible(frame):
    """Final sale/exit text layout; not a claim that item identities are known.

    Real saved sequences show these controls appear after the reveal sequence,
    including the last item below TOP. Skip text and a stable TOP alone don't.
    The templates contain only labels, excluding price/countdown digits.
    """
    if frame is None or frame.size == 0:
        return False
    vx, vy, vw, vh = ROIScaler.get_viewport_rect(frame.shape[1], frame.shape[0])
    boxes = ((1328, 851, 1465, 911), (1665, 969, 1750, 1032))
    for template, (x, y, r, b) in zip(_settlement_controls(), boxes):
        if template is None:
            return False
        crop = frame[vy+round(y*vh/1080):vy+round(b*vh/1080),
                     vx+round(x*vw/1920):vx+round(r*vw/1920)]
        if crop.size == 0:
            return False
        gray = cv2.cvtColor(cv2.resize(crop, (r-x, b-y)), cv2.COLOR_BGR2GRAY)
        score = cv2.minMaxLoc(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED))[1]
        if not np.isfinite(score) or score < .88:
            return False
    return True


def _bid_panel_visible(frame):
    """报价键盘加「确认出价」白钮。阈值来自 2026-09-08 13-40-43 的实机录像。"""
    h, w = frame.shape[:2]
    if h < 200 or w < 200:
        return False
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    pill = hsv[int(h * 0.83):int(h * 0.93), int(w * 0.46):int(w * 0.76)]
    if pill.size == 0:
        return False
    white = float(((pill[:, :, 2] > 200) & (pill[:, :, 1] < 50)).mean())
    keys = hsv[int(h * 0.48):int(h * 0.90), int(w * 0.12):int(w * 0.42)]
    mask = ((keys[:, :, 2] > 150) & (keys[:, :, 2] < 235) & (keys[:, :, 1] < 45)).astype(np.uint8) * 255
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    min_area = 200.0 * (w * h) / (1920 * 1080)
    squares = 0
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        if area < min_area or width < 20 or height < 20:
            continue
        if 0.6 <= width / max(height, 1) <= 1.7:
            squares += 1
    return white >= 0.28 and squares >= 10


def _seat_strip_bright(frame):
    h, w = frame.shape[:2]
    crop = frame[int(h * 0.15):int(h * 0.75), int(w * 0.02):int(w * 0.28)]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return float((hsv[:, :, 2] > 140).mean()) >= 0.20


def classify_auction_flow_frame(frame):
    """Label one video or capture frame: bid panel, settlement, return, lobby.

    Return is the settlement exit control (退出), not a second page. The lobby
    label reuses the existing fast navigation classifier.
    """
    if frame is None or getattr(frame, 'size', 0) == 0:
        return {'scene': 'UNKNOWN', 'labels': [], 'returnAvailable': False}
    if _bid_panel_visible(frame):
        return {'scene': 'BID_PANEL', 'labels': ['BID_PANEL'], 'returnAvailable': False}
    if settlement_title_visible(frame):
        back = bool(settlement_controls_visible(frame))
        labels = ['SETTLEMENT'] + (['RETURN'] if back else [])
        return {'scene': 'SETTLEMENT', 'labels': labels, 'returnAvailable': back}
    from vision_pipeline import NTEVisionPipeline
    fast = NTEVisionPipeline._classify_scene_fast(None, frame).get('scene') or 'UNKNOWN'
    if fast == 'AUCTION_LOBBY':
        return {'scene': 'AUCTION_LOBBY', 'labels': ['AUCTION_LOBBY'], 'returnAvailable': False}
    if fast not in ('UNKNOWN', ''):
        return {'scene': fast, 'labels': [fast], 'returnAvailable': False}
    if _seat_strip_bright(frame):
        return {'scene': 'IN_AUCTION', 'labels': ['IN_AUCTION'], 'returnAvailable': False}
    return {'scene': 'UNKNOWN', 'labels': [], 'returnAvailable': False}


def frame_digest(frame):
    return hashlib.sha256(np.ascontiguousarray(frame).tobytes()).hexdigest()


@lru_cache(maxsize=1)
def _bid_ocr():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def published_domain_scene(frame):
    """Scene the ticketed host can act on, using the published control templates.

    Priority matches SceneAnchorGameDecoder: settlement witness and exit,
    otherwise the lobby start control, otherwise the bid confirm control.
    Search boxes are not click coordinates. A frame that is not the catalog
    size returns None so a scaled mismatch cannot authorize a send.
    """
    if frame is None or getattr(frame, "size", 0) == 0 or frame.shape[1] != 1920 or frame.shape[0] != 1080:
        return None
    catalog, templates = _domain_control_catalog()
    if catalog is None:
        return None
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    scenes = {row["scene"]: row for row in catalog["scenes"]}
    threshold = float(catalog["threshold"])

    def hit(name, box):
        template = templates.get(name)
        return template is not None and _template_in_box(gray, template, box, threshold)

    settlement = scenes.get("SETTLEMENT") or {}
    if (all(hit(row["template"], row["search"]) for row in settlement.get("witnesses") or [])
            and all(hit(row["template"], row["search"]) for row in settlement.get("controls") or [])
            and (settlement.get("witnesses") or settlement.get("controls"))):
        return "SETTLEMENT"
    lobby = scenes.get("LOBBY") or {}
    if lobby.get("controls") and all(hit(row["template"], row["search"]) for row in lobby["controls"]):
        return "LOBBY"
    auction = scenes.get("AUCTION") or {}
    if auction.get("controls") and all(hit(row["template"], row["search"]) for row in auction["controls"]):
        return "AUCTION"
    return None


def fee_confirm_pixel(red, green, blue):
    """The entry-fee confirm pill is pink. Gray dialog fill is not that control.

    The live pill sampled RGB (242, 81, 145). A cream or gray gate at the same
    client point accepts the dialog body and does not dismiss it.
    """
    if type(red) is not int or type(green) is not int or type(blue) is not int:
        return False
    return red >= 180 and green <= 140 and red - green >= 60


def one_asset_integer(texts):
    """The current-funds gate: exactly one non-negative integer, or nothing."""
    import re
    found = []
    for text in texts or []:
        for token in re.findall(r"\d[\d,，]*", str(text)):
            found.append(int(token.replace(",", "").replace("，", "")))
    if len(found) != 1 or found[0] < 0:
        return None
    return found[0]


def read_asset_funds(frame):
    """Read 我的资产 from the top-right of a 1920x1080 frame.

    Zero integers or more than one integer refuses the send. This does not
    invent a balance from the Solver suggestion.
    """
    if frame is None or getattr(frame, "size", 0) == 0 or frame.shape[1] != 1920 or frame.shape[0] != 1080:
        return None
    crop = frame[0:86, 1380:1920]
    if crop.size == 0:
        return None
    rows, _ = _bid_ocr()(crop)
    return one_asset_integer(str(row[1]) for row in (rows or []))


@lru_cache(maxsize=1)
def _domain_control_catalog():
    path = asset_root() / "assets/scene_anchors/domain_controls.json"
    if not path.is_file():
        return None, {}
    catalog = json.loads(path.read_text(encoding="utf-8"))
    templates = {}
    for scene in catalog.get("scenes") or []:
        for row in list(scene.get("witnesses") or []) + list(scene.get("controls") or []):
            name = row.get("template")
            if not name or name in templates:
                continue
            image = asset_root() / "assets/scene_anchors" / name
            decoded = cv2.imdecode(np.fromfile(image, np.uint8), cv2.IMREAD_GRAYSCALE) if image.is_file() else None
            templates[name] = decoded
    return catalog, templates


def _template_in_box(gray, template, box, threshold):
    x, y, right, bottom = (int(v) for v in box)
    if template is None or right <= x or bottom <= y:
        return False
    crop = gray[y:bottom, x:right]
    if crop.size == 0 or crop.shape[0] < template.shape[0] or crop.shape[1] < template.shape[1]:
        return False
    score = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    best = float(score.max()) if score.size else 0.0
    return bool(np.isfinite(best) and best >= threshold)


def committed_bid_amounts(frame):
    """Integers on the bid control after the quote panel has closed."""
    import re
    h, w = frame.shape[:2]
    crop = frame[int(h * 0.80):int(h * 0.99), int(w * 0.72):int(w * 0.99)]
    if crop.size == 0:
        return []
    rows, _ = _bid_ocr()(crop)
    amounts = []
    for row in rows or []:
        for token in re.findall(r'\d[\d,，]*', str(row[1])):
            amounts.append(int(token.replace(',', '').replace('，', '')))
    return amounts


def settlement_reveal_progress(frame):
    """Visible value glyphs for bounded no-progress recovery, never OCR facts."""
    vx, vy, vw, vh = ROIScaler.get_viewport_rect(frame.shape[1], frame.shape[0])
    crop = frame[vy+round(143*vh/1080):vy+round(185*vh/1080),
                 vx+round(1620*vw/1920):vx+round(1880*vw/1920)]
    bgr = cv2.resize(crop, (260,42)).astype(np.int16)
    ink = (bgr[:,:,2] >= 180) & (bgr[:,:,2]-bgr[:,:,1] > 30) & (bgr[:,:,2]-bgr[:,:,0] > 80)
    return hashlib.sha256(ink.tobytes()).hexdigest()
