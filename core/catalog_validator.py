"""Strict validator for collection item names, catalog IDs, and source card bindings.

Rules:
- All formal names must strictly originate from the verified official catalog (catalog_065.json)
  or the independent verified source card registry (verified_source_card_registry.json).
- A manifest cannot grant authority to its own entries or generate authority to validate itself.
- Source card screenshots must be valid decodable images (not JSON/TXT or corrupt data).
- Source card bounding boxes must have strictly positive area (w > 0, h > 0) and remain
  strictly within image dimensions (0 <= x, y and x + w <= img_w, y + h <= img_h).
- Every source card (screenshot + bbox) has an immutable, authoritative 1-to-1 binding to a specific
  catalog ID and official name. Pairing a genuine source card with another name or ID is strictly rejected.
- Conflicting fields within the same record (name vs canonicalName, catalogId vs selectedCatalogId,
  contradictory confirmed vs unconfirmed status) are strictly rejected without masking.
- Unconfirmed visual items must keep canonicalName = None / null.
"""
from __future__ import annotations

import hashlib
import sys
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
CATALOG_065 = PROJECT_ROOT / "assets" / "catalog_065.json"
VERIFIED_SOURCE_CARD_REGISTRY = PROJECT_ROOT / "assets" / "items" / "verified_source_card_registry.json"

_OFFICIAL_CATALOG: Dict[str, Dict[str, Any]] = {}
_VALID_NAMES_TO_IDS: Dict[str, Set[str]] = {}
_CATALOG_065_IDS: Set[str] = set()
_VERIFIED_CARD_MAP: Dict[str, Dict[str, Any]] = {}
_VERIFIED_ID_TO_CARD: Dict[str, Dict[str, Any]] = {}
_IMMUTABLE_REGISTRY_ID_TO_NAME: Dict[str, str] = {}
_IMMUTABLE_VERIFIED_CARDS: List[Dict[str, Any]] = []


class AmbiguousCatalogIdentifierError(ValueError):
    """Raised when a catalog identifier requires unambiguous physical context but none or contradictory context is provided."""
    pass


def _normalize_quality_str(q: Optional[str]) -> str:
    if not q:
        return ""
    s = str(q).strip().lower()
    mapping = {
        "gold": "金",
        "golden": "金",
        "red": "红",
        "purple": "紫",
        "blue": "蓝",
        "green": "绿",
        "white": "白",
        "gray": "白",
        "grey": "白",
        "灰": "白",
    }
    return mapping.get(s, s)


def resolve_legacy_catalog_identity(
    raw_catalog_id: str,
    *,
    observed_quality: Optional[str] = None,
    observed_grid_w: Optional[int] = None,
    observed_grid_h: Optional[int] = None,
) -> str:
    """Resolve catalog ID with strict context gating (pure visual inputs only, non-circular)."""
    raw_id = str(raw_catalog_id or "").strip()
    if raw_id == "image3-0-2":
        norm_q = _normalize_quality_str(observed_quality)
        gw = int(observed_grid_w) if observed_grid_w is not None else None
        gh = int(observed_grid_h) if observed_grid_h is not None else None
        grid = {gw, gh} if (gw is not None and gh is not None) else set()

        if norm_q == "红" and grid == {1, 2}:
            return "visual-latiao-1x2"
        elif norm_q in ("白", "灰") and grid == {1}:
            return "image3-0-2"
        else:
            raise AmbiguousCatalogIdentifierError(
                f"Identifier 'image3-0-2' requires unambiguous visual physical context. "
                f"Provided: quality={observed_quality!r}, grid=({observed_grid_w}, {observed_grid_h})"
            )
    return raw_id


def _get_immutable_verified_cards(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    global _IMMUTABLE_VERIFIED_CARDS
    if _IMMUTABLE_VERIFIED_CARDS:
        return _IMMUTABLE_VERIFIED_CARDS
    base_dir = root or PROJECT_ROOT
    reg_path = base_dir / "assets" / "items" / "verified_source_card_registry.json"
    if reg_path.is_file():
        try:
            rdata = json.loads(reg_path.read_text(encoding="utf-8"))
            cards: List[Dict[str, Any]] = []
            for c in rdata.get("cards", []):
                cid = str(c.get("catalogId") or "").strip()
                name = str(c.get("name") or "").strip()
                src = Path(str(c.get("sourceScreenshot") or "")).as_posix().lower()
                sha = str(c.get("sourceScreenshotSha256") or c.get("sourceSha256") or "").strip().lower()
                bbox = c.get("bbox") or c.get("cardBbox")
                if not (cid and name and src and len(sha) == 64 and bbox and len(bbox) == 4):
                    continue
                ibbox = (int(round(bbox[0])), int(round(bbox[1])), int(round(bbox[2])), int(round(bbox[3])))
                alts = frozenset(str(x).strip() for x in c.get("alternateCatalogIds", []) if str(x).strip())
                w_cells = int(c.get("widthCells") or c.get("width") or 0) or None
                h_cells = int(c.get("heightCells") or c.get("height") or 0) or None
                q_val = _normalize_quality_str(c.get("quality") or c.get("rarity"))
                cards.append({
                    "catalogId": cid,
                    "alternateCatalogIds": alts,
                    "allCatalogIds": frozenset({cid} | alts),
                    "name": name,
                    "sourceScreenshot": src,
                    "sourceScreenshotSha256": sha,
                    "bbox": ibbox,
                    "widthCells": w_cells,
                    "heightCells": h_cells,
                    "quality": q_val,
                    "value": c.get("value"),
                })
            _IMMUTABLE_VERIFIED_CARDS = cards
        except Exception as exc:
            logger.error("Failed to load immutable verified registry cards: %s", exc)
    return _IMMUTABLE_VERIFIED_CARDS


def _get_immutable_registry_id_to_name(root: Optional[Path] = None) -> Dict[str, str]:
    global _IMMUTABLE_REGISTRY_ID_TO_NAME
    if _IMMUTABLE_REGISTRY_ID_TO_NAME:
        return _IMMUTABLE_REGISTRY_ID_TO_NAME
    cards = _get_immutable_verified_cards(root)
    mapping: Dict[str, str] = {}
    for c in cards:
        rcid = c["catalogId"]
        rname = c["name"]
        if rcid and rname:
            mapping[rcid] = rname
        for alt in c["alternateCatalogIds"]:
            if alt and rname:
                mapping[alt] = rname
    _IMMUTABLE_REGISTRY_ID_TO_NAME = mapping
    return _IMMUTABLE_REGISTRY_ID_TO_NAME

# Confirmed identity statuses that REQUIRE a verified non-null catalogId and official name
_CONFIRMED_STATUSES: Set[str] = {
    "CONFIRMED",
    "EXACT_IDENTIFIED",
    "UNIQUE_IN_CATALOG",
    "VISUALLY_CHECKED_SOURCE_CARD",
    "RECOVERED_DETERMINISTIC",
}

# Unconfirmed identity statuses that represent pending / unresolved / candidate state
_UNCONFIRMED_STATUSES: Set[str] = {
    "UNCONFIRMED",
    "UNCONFIRMED_VISUAL_ITEM",
    "UNKNOWN_OR_CANDIDATE_UNCONFIRMED",
    "REVIEW_REQUIRED",
    "CANDIDATE_ONLY",
    "MISSING_UNRESOLVED",
    "UNKNOWN",
    "AMBIGUOUS",
    "AMBIGUOUS_REGION",
    "UNALIGNED",
}


def _normalize_screenshot_path(src: str | Path) -> str:
    s = str(src).replace("\\", "/").strip()
    if s.startswith("./"):
        s = s[2:]
    return s


def _make_card_key(src: str | Path, bbox: Sequence[int | float]) -> str:
    norm_src = _normalize_screenshot_path(src)
    return f"{norm_src}:{int(bbox[0])},{int(bbox[1])},{int(bbox[2])},{int(bbox[3])}"


def validate_card_image_and_bbox(
    record_or_item: Dict[str, Any],
    root: Optional[Path] = None,
    auth_sha: Optional[str] = None,
) -> Tuple[bool, str, Optional[Tuple[int, int]]]:
    """Validates that a source card screenshot is a decodable image and bbox has positive area within bounds."""
    base_dir = root or PROJECT_ROOT
    src = record_or_item.get("sourceScreenshot") or record_or_item.get("sourcePath")
    bbox = record_or_item.get("bbox") or record_or_item.get("cardBbox")

    if not src and bbox is None:
        return True, "NO_CARD", None

    if not src or bbox is None:
        return False, "Incomplete source card evidence: sourceScreenshot and bbox must both be provided together.", None

    src_path = base_dir / str(src)
    if not src_path.is_file():
        return False, f"Source screenshot file not found: {src_path}", None

    try:
        raw_bytes = src_path.read_bytes()
    except OSError as err:
        return False, f"Failed to read source screenshot file: {err}", None

    actual_sha = hashlib.sha256(raw_bytes).hexdigest()

    # Look up authoritative SHA from independent registry if not explicitly provided
    if auth_sha is None:
        _init_catalog()
        card_key = _make_card_key(src, bbox)
        auth_card = _VERIFIED_CARD_MAP.get(card_key)
        if auth_card:
            auth_sha = auth_card.get("sourceScreenshotSha256")

    # Authoritative registry SHA comparison: NEVER trust only the record's self-claimed hash!
    if auth_sha:
        if actual_sha != auth_sha:
            return (
                False,
                f"Source screenshot SHA256 mismatch against authoritative registry for '{src}': "
                f"expected authoritative {auth_sha}, got actual file {actual_sha}",
                None,
            )
        claimed_sha = record_or_item.get("sourceScreenshotSha256") or record_or_item.get("sourceSha256")
        if claimed_sha and claimed_sha != auth_sha:
            return (
                False,
                f"Record claimed source screenshot SHA256 mismatch against authoritative registry for '{src}': "
                f"expected authoritative {auth_sha}, got record claimed {claimed_sha}",
                None,
            )
    else:
        # Fallback if card is not in authoritative registry: check record's self-claimed hash
        expected_sha = record_or_item.get("sourceScreenshotSha256") or record_or_item.get("sourceSha256")
        if expected_sha and actual_sha != expected_sha:
            return (
                False,
                f"Source screenshot SHA256 mismatch for '{src}': expected {expected_sha}, got {actual_sha}",
                None,
            )

    # Check image decodability
    try:
        img = cv2.imdecode(np.frombuffer(raw_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception as ex:
        return False, f"Failed to decode source screenshot image '{src}': {ex}", None

    if img is None or len(img.shape) < 2 or img.shape[0] <= 0 or img.shape[1] <= 0:
        return False, f"Source screenshot is not a valid decodable image: '{src}'", None

    img_h, img_w = img.shape[:2]

    # Check bbox format
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False, f"Card bbox must be a 4-element sequence [x, y, w, h], got: {bbox}", None

    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or v != v or abs(v) == float("inf") for v in bbox):
        return False, f"Card bbox coordinates must be finite real numbers, got: {bbox}", None

    bx, by, bw, bh = bbox
    if bx < 0 or by < 0:
        return False, f"Card bbox coordinates cannot be negative: x={bx}, y={by}", None

    if bw <= 0 or bh <= 0:
        return False, f"Card bbox area must be strictly positive (w > 0, h > 0): got w={bw}, h={bh}", None

    if bx + bw > img_w or by + bh > img_h:
        return False, f"Card bbox [{bx}, {by}, {bw}, {bh}] extends beyond image dimensions ({img_w}x{img_h})", None

    return True, "OK", (img_w, img_h)


def has_verifiable_source_evidence(record_or_item: Dict[str, Any], root: Optional[Path] = None) -> bool:
    """Verifies that an item has traceable, decodable source card evidence bound to its identity."""
    _init_catalog()
    src = record_or_item.get("sourceScreenshot") or record_or_item.get("sourcePath")
    bbox = record_or_item.get("bbox") or record_or_item.get("cardBbox")
    if not src or bbox is None:
        return False

    card_key = _make_card_key(src, bbox)
    auth_card = _VERIFIED_CARD_MAP.get(card_key)
    if not auth_card:
        return False

    auth_sha = auth_card.get("sourceScreenshotSha256")
    valid, _, _ = validate_card_image_and_bbox(record_or_item, root=root, auth_sha=auth_sha)
    if not valid:
        return False

    cid = record_or_item.get("catalogId") or record_or_item.get("selectedCatalogId")
    allowed_cids = {auth_card["catalogId"]}
    if "alternateCatalogIds" in auth_card:
        allowed_cids.update(auth_card["alternateCatalogIds"])
    if cid and str(cid).strip() not in allowed_cids:
        return False

    name = record_or_item.get("name") or record_or_item.get("canonicalName")
    if name and str(name).strip() != auth_card["name"]:
        return False

    claimed_sha = record_or_item.get("sourceScreenshotSha256") or record_or_item.get("sourceSha256")
    if claimed_sha and auth_sha and claimed_sha != auth_sha:
        return False

    return True


def validate_verified_registry_card(
    card: Dict[str, Any], root: Optional[Path] = None
) -> Tuple[bool, str]:
    """Strictly validates an independent verified source card registry entry.

    Verifies:
    1. catalogId: non-empty string, no whitespace, cannot equal name.
    2. name: non-empty string, cannot equal catalogId.
    3. dimensions: widthCells and heightCells are integers in [1, 5].
    4. bbox: integer/finite list of length 4, non-negative coordinates, strictly positive area (w > 0, h > 0).
    5. sourceScreenshot: non-empty path, real file existing on disk.
    6. sourceScreenshotSha256: 64-char hex string, strictly matches actual disk file SHA-256.
    7. Image decodability: file must decode to a valid image with shape.
    8. bbox within bounds: x + w <= img_w, y + h <= img_h.
    9. cropSha256: if provided in card, cut exact crop from image and verify sha256.
    """
    if not isinstance(card, dict):
        return False, f"Expected dict card, got {type(card).__name__}"

    cid = str(card.get("catalogId") or "").strip()
    if not cid:
        return False, "Missing catalogId"
    if any(ch in " \t\r\n" for ch in cid):
        return False, f"catalogId cannot contain whitespace: {cid!r}"

    name = str(card.get("name") or "").strip()
    if not name:
        return False, "Missing name"
    if name == cid:
        return False, f"name cannot equal catalogId: {name!r}"

    width = card.get("widthCells")
    height = card.get("heightCells")
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1 or width > 5 or height > 5:
        return False, f"Invalid dimensions widthCells={width}, heightCells={height}"

    src = card.get("sourceScreenshot") or card.get("sourcePath")
    if not src:
        return False, "Missing sourceScreenshot"

    auth_sha = str(card.get("sourceScreenshotSha256") or card.get("sourceSha256") or "").strip().lower()
    if len(auth_sha) != 64 or any(c not in "0123456789abcdef" for c in auth_sha):
        return False, f"Invalid sourceScreenshotSha256: {auth_sha!r}"

    base_dir = root or PROJECT_ROOT
    src_path = base_dir / str(src)
    if not src_path.is_file():
        return False, f"Source screenshot file not found: {src_path}"

    try:
        raw_bytes = src_path.read_bytes()
    except OSError as err:
        return False, f"Failed to read source screenshot file: {err}"

    actual_sha = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha != auth_sha:
        return (
            False,
            f"Source screenshot SHA256 mismatch for '{src}': expected {auth_sha}, got {actual_sha}",
        )

    try:
        img = cv2.imdecode(np.frombuffer(raw_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception as ex:
        return False, f"Failed to decode image '{src}': {ex}"

    if img is None or len(img.shape) < 2 or img.shape[0] <= 0 or img.shape[1] <= 0:
        return False, f"Source screenshot is not a valid image: '{src}'"

    img_h, img_w = img.shape[:2]

    bbox = card.get("bbox") or card.get("cardBbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False, f"Card bbox must be [x, y, w, h], got: {bbox}"

    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or v != v or abs(v) == float("inf") for v in bbox):
        return False, f"Card bbox coordinates must be finite real numbers, got: {bbox}"

    bx, by, bw, bh = bbox
    if bx < 0 or by < 0:
        return False, f"Card bbox coordinates cannot be negative: x={bx}, y={by}"
    if bw <= 0 or bh <= 0:
        return False, f"Card bbox area must be strictly positive: w={bw}, h={bh}"
    if bx + bw > img_w or by + bh > img_h:
        return False, f"Card bbox [{bx}, {by}, {bw}, {bh}] extends beyond image dimensions ({img_w}x{img_h})"

    if "cropSha256" in card and card.get("cropSha256"):
        expected_crop_sha = str(card["cropSha256"]).strip().lower()
        crop_img = img[int(round(by)):int(round(by + bh)), int(round(bx)):int(round(bx + bw))]
        actual_crop_sha = hashlib.sha256(cv2.imencode(".png", crop_img)[1].tobytes()).hexdigest()
        if actual_crop_sha != expected_crop_sha:
            return False, f"Crop SHA256 mismatch: expected {expected_crop_sha}, got {actual_crop_sha}"

    global _CATALOG_065_IDS, _OFFICIAL_CATALOG
    if not _CATALOG_065_IDS:
        _init_catalog()

    if _CATALOG_065_IDS and cid in _CATALOG_065_IDS:
        official_item = _OFFICIAL_CATALOG.get(cid)
        if official_item and name != official_item.get("name"):
            return False, f"Card name {name!r} matches official catalog_065 ID {cid!r} but differs from official name {official_item.get('name')!r}"

    # Complete source card binding verification:
    # Official ID and true name MUST match a verified source card's exact (screenshot, sha256, bbox, shape, quality)
    verified_cards = _get_immutable_verified_cards(root)
    matching_by_id = [vc for vc in verified_cards if cid in vc["allCatalogIds"]]
    if not matching_by_id:
        return False, f"Unofficial card ID {cid!r} is not registered in immutable verified registry"

    matching_by_name = [vc for vc in matching_by_id if vc["name"] == name]
    if not matching_by_name:
        expected_names = sorted(set(vc["name"] for vc in matching_by_id))
        return False, f"Card name {name!r} does not match verified registered name {expected_names} for ID {cid!r}"

    src_norm = Path(str(src)).as_posix().lower()
    ibbox = (int(round(bx)), int(round(by)), int(round(bw)), int(round(bh)))
    card_w = int(card.get("widthCells") or card.get("width") or 0) or None
    card_h = int(card.get("heightCells") or card.get("height") or 0) or None
    card_q = _normalize_quality_str(card.get("quality") or card.get("rarity"))

    matched_card = None
    for vc in matching_by_name:
        if vc["sourceScreenshot"] != src_norm:
            continue
        if vc["sourceScreenshotSha256"] != auth_sha:
            continue
        if vc["bbox"] != ibbox:
            continue
        if card_w is not None and vc["widthCells"] is not None and card_w != vc["widthCells"]:
            continue
        if card_h is not None and vc["heightCells"] is not None and card_h != vc["heightCells"]:
            continue
        if card_q and vc["quality"] and card_q != vc["quality"]:
            continue
        matched_card = vc
        break

    if matched_card is None:
        other_owner = [vc for vc in verified_cards if vc["sourceScreenshotSha256"] == auth_sha and vc["bbox"] == ibbox]
        if other_owner:
            owner_desc = ", ".join(f"{vc['catalogId']} ({vc['name']})" for vc in other_owner)
            return False, f"Card source screenshot and bbox belong to verified card {owner_desc}, cross-binding rejected for {cid!r} ({name!r})"
        return False, f"Card source screenshot/bbox/hash does not match verified ground truth binding for {cid!r} ({name!r})"

    return True, "OK"


def _init_catalog() -> None:
    global _OFFICIAL_CATALOG, _VALID_NAMES_TO_IDS, _CATALOG_065_IDS, _VERIFIED_CARD_MAP, _VERIFIED_ID_TO_CARD
    if _OFFICIAL_CATALOG:
        return

    # 1. Load official catalog_065.json (200 records) as primary ground truth authority
    if CATALOG_065.is_file():
        data = json.loads(CATALOG_065.read_text(encoding="utf-8"))
        for item in data:
            cid = str(item.get("Id") or "").strip()
            name = str(item.get("Name") or "").strip()
            if cid and name:
                _CATALOG_065_IDS.add(cid)
                _OFFICIAL_CATALOG[cid] = {
                    "catalogId": cid,
                    "name": name,
                    "widthCells": int(item.get("Width") or 1),
                    "heightCells": int(item.get("Height") or 1),
                    "quality": item.get("Quality"),
                    "value": item.get("Value"),
                    "source": "catalog_065",
                    "hasVerifiedEvidence": True,
                }
                _VALID_NAMES_TO_IDS.setdefault(name, set()).add(cid)

    # 2. Load independent verified source card registry (249 verified cards)
    # Never read a manifest under test to establish authority!
    if VERIFIED_SOURCE_CARD_REGISTRY.is_file():
        rdata = json.loads(VERIFIED_SOURCE_CARD_REGISTRY.read_text(encoding="utf-8"))
        for card in rdata.get("cards", []):
            is_valid, reason = validate_verified_registry_card(card, root=PROJECT_ROOT)
            if not is_valid:
                logger.warning("catalog_validator: rejecting unverified registry card %s: %s", card.get("catalogId"), reason)
                continue

            cid = str(card.get("catalogId") or "").strip()
            name = str(card.get("name") or "").strip()
            src = card.get("sourceScreenshot")
            bbox = card.get("bbox")

            card_key = _make_card_key(src, bbox)
            _VERIFIED_CARD_MAP[card_key] = card
            _VERIFIED_ID_TO_CARD[cid] = card

            # Register verified visual-* items not in catalog_065
            if cid not in _OFFICIAL_CATALOG:
                _OFFICIAL_CATALOG[cid] = {
                    "catalogId": cid,
                    "name": name,
                    "widthCells": int(card.get("widthCells") or 1),
                    "heightCells": int(card.get("heightCells") or 1),
                    "quality": card.get("quality"),
                    "value": card.get("value"),
                    "source": "verified_source_card_registry",
                    "hasVerifiedEvidence": True,
                }
                _VALID_NAMES_TO_IDS.setdefault(name, set()).add(cid)


def reset_catalog_cache() -> None:
    """Resets in-memory catalog cache (primarily for tests)."""
    global _OFFICIAL_CATALOG, _VALID_NAMES_TO_IDS, _CATALOG_065_IDS, _VERIFIED_CARD_MAP, _VERIFIED_ID_TO_CARD, _IMMUTABLE_REGISTRY_ID_TO_NAME, _IMMUTABLE_VERIFIED_CARDS
    _OFFICIAL_CATALOG = {}
    _VALID_NAMES_TO_IDS = {}
    _CATALOG_065_IDS = set()
    _VERIFIED_CARD_MAP = {}
    _VERIFIED_ID_TO_CARD = {}
    _IMMUTABLE_REGISTRY_ID_TO_NAME = {}
    _IMMUTABLE_VERIFIED_CARDS = []


def get_official_item(catalog_id: str) -> Optional[Dict[str, Any]]:
    _init_catalog()
    return _OFFICIAL_CATALOG.get(catalog_id)


def is_valid_catalog_id(catalog_id: str) -> bool:
    _init_catalog()
    return catalog_id in _OFFICIAL_CATALOG


def get_official_name(catalog_id: str) -> Optional[str]:
    item = get_official_item(catalog_id)
    return item["name"] if item else None


def is_official_name(name: str) -> bool:
    _init_catalog()
    return name in _VALID_NAMES_TO_IDS


def get_valid_names() -> Set[str]:
    _init_catalog()
    return set(_VALID_NAMES_TO_IDS.keys())


def get_valid_ids() -> Set[str]:
    _init_catalog()
    return set(_OFFICIAL_CATALOG.keys())


def validate_item_identity(
    catalog_id: Optional[str],
    canonical_name: Optional[str],
    identity_status: str = "UNSPECIFIED",
) -> bool:
    """Validates that an item identity strictly matches official catalog provenance.

    Raises:
        ValueError: If a name is not in the catalog, ID-name mismatch, or status contradiction.
    """
    _init_catalog()

    clean_cid = str(catalog_id).strip() if catalog_id is not None else None
    clean_name = str(canonical_name).strip() if canonical_name is not None else None

    # Case 1: Unconfirmed / null canonical name
    if clean_name is None or clean_name == "":
        if identity_status in _CONFIRMED_STATUSES:
            raise ValueError(
                f"Status contradiction: item marked as confirmed status '{identity_status}' "
                f"but canonicalName is null or empty. Unconfirmed items must use an unconfirmed status."
            )
        return True

    # Case 2: Name is provided - MUST originate from verified catalog
    if clean_name not in _VALID_NAMES_TO_IDS:
        raise ValueError(
            f"Unrecognized item name: '{clean_name}' does not exist in the verified official catalog."
        )

    # Case 3: Name is provided - MUST have valid catalog_id
    if not clean_cid or not is_valid_catalog_id(clean_cid):
        raise ValueError(
            f"Illegal item identity: name '{clean_name}' provided without valid catalogId '{clean_cid}'. "
            f"All formal item names must originate strictly from the verified catalog."
        )

    # Case 4: Catalog ID-Name pair consistency check
    expected_name = get_official_name(clean_cid)
    if clean_name != expected_name:
        raise ValueError(
            f"Catalog ID-name mismatch: catalogId '{clean_cid}' expects official name '{expected_name}', "
            f"but got '{clean_name}'."
        )

    return True


def validate_catalog_record(record: Dict[str, Any], root: Optional[Path] = None) -> bool:
    """Validates a complete catalog or review record dictionary, checking field consistency.

    Detects and rejects:
    - Differing 'name' vs 'canonicalName' within the same record
    - Differing 'catalogId' vs 'selectedCatalogId' within the same record
    - Contradictory confirmed vs unconfirmed status fields
    - Confirmed status with missing/empty name or missing/empty catalogId
    - Non-catalog_065 catalogId lacking independent verifiable source screenshot card evidence
    - ID-name mismatch against official catalog definitions
    """
    _init_catalog()
    if not isinstance(record, dict):
        raise TypeError(f"Expected dict record, got {type(record).__name__}")

    # 1. Check 'name' vs 'canonicalName' consistency
    has_name = "name" in record
    has_canonical = "canonicalName" in record
    raw_name = record.get("name")
    raw_canonical = record.get("canonicalName")
    val_name = str(raw_name).strip() if raw_name is not None else None
    val_canonical = str(raw_canonical).strip() if raw_canonical is not None else None

    if has_name and has_canonical:
        if val_name != val_canonical:
            raise ValueError(
                f"Field conflict: record contains contradictory 'name' ({val_name!r}) "
                f"and 'canonicalName' ({val_canonical!r})."
            )
        effective_name = val_name
    elif has_name:
        effective_name = val_name
    elif has_canonical:
        effective_name = val_canonical
    else:
        effective_name = None

    # 2. Check 'catalogId' vs 'selectedCatalogId' consistency
    has_cid = "catalogId" in record
    has_sel_cid = "selectedCatalogId" in record
    raw_cid = record.get("catalogId")
    raw_sel_cid = record.get("selectedCatalogId")
    val_cid = str(raw_cid).strip() if raw_cid is not None else None
    val_sel_cid = str(raw_sel_cid).strip() if raw_sel_cid is not None else None

    if has_cid and has_sel_cid:
        if val_cid and val_sel_cid and val_cid != val_sel_cid:
            raise ValueError(
                f"Field conflict: record contains contradictory 'catalogId' ({val_cid!r}) "
                f"and 'selectedCatalogId' ({val_sel_cid!r})."
            )
        effective_cid = val_cid or val_sel_cid
    elif has_cid:
        effective_cid = val_cid
    elif has_sel_cid:
        effective_cid = val_sel_cid
    else:
        effective_cid = None

    # 3. Check status fields consistency
    statuses: Dict[str, str] = {}
    for key in ("status", "identityStatus", "candidateStatus", "reviewStatus"):
        if key in record and record[key] is not None:
            s_val = str(record[key]).strip()
            if s_val:
                statuses[key] = s_val

    confirmed_statuses = {k: v for k, v in statuses.items() if v in _CONFIRMED_STATUSES}
    unconfirmed_statuses = {k: v for k, v in statuses.items() if v in _UNCONFIRMED_STATUSES}

    # Conflict: record has both a confirmed status and an unconfirmed status
    if confirmed_statuses and unconfirmed_statuses:
        raise ValueError(
            f"Field conflict: record contains contradictory confirmed status {confirmed_statuses} "
            f"and unconfirmed status {unconfirmed_statuses}."
        )

    # Status contradiction: confirmed status but missing name or missing ID
    if confirmed_statuses:
        if not effective_name:
            raise ValueError(
                f"Status contradiction: record has confirmed status {confirmed_statuses} "
                f"but item name is null or empty."
            )
        if not effective_cid:
            raise ValueError(
                f"Status contradiction: record has confirmed status {confirmed_statuses} "
                f"but catalogId is null or empty."
            )

    # 4. Source card physical & geometry validation (if provided)
    has_src = bool(record.get("sourceScreenshot") or record.get("sourcePath"))
    has_bbox = (record.get("bbox") is not None) or (record.get("cardBbox") is not None)

    if has_src or has_bbox:
        src = record.get("sourceScreenshot") or record.get("sourcePath")
        bbox = record.get("bbox") or record.get("cardBbox")
        card_key = _make_card_key(src, bbox) if (src and bbox is not None) else None
        auth_card = _VERIFIED_CARD_MAP.get(card_key) if card_key else None
        auth_sha = auth_card.get("sourceScreenshotSha256") if auth_card else None

        valid_card, err_msg, _ = validate_card_image_and_bbox(record, root=root, auth_sha=auth_sha)
        if not valid_card:
            raise ValueError(f"Card validation failure: {err_msg}")

        if auth_card:
            # Card is registered: must match official registered name and ID
            if effective_name and effective_name != auth_card["name"]:
                raise ValueError(
                    f"Source card identity mismatch: card '{card_key}' belongs to official item "
                    f"'{auth_card['name']}', but record claims '{effective_name}'."
                )
            allowed_cids = {auth_card["catalogId"]}
            if "alternateCatalogIds" in auth_card:
                allowed_cids.update(auth_card["alternateCatalogIds"])
            if effective_cid and effective_cid not in allowed_cids:
                raise ValueError(
                    f"Source card catalogId mismatch: card '{card_key}' belongs to catalogId "
                    f"'{auth_card['catalogId']}', but record claims '{effective_cid}'."
                )
        else:
            # Card does not exist in independent verified registry
            raise ValueError(
                f"Unverified source card: card '{card_key}' does not exist in the verified source card registry."
            )

    # 5. Non-catalog_065 items MUST possess verified source card evidence
    if effective_cid and effective_cid not in _CATALOG_065_IDS:
        official_item = get_official_item(effective_cid)
        is_registered_with_evidence = bool(official_item and official_item.get("hasVerifiedEvidence"))
        has_card = has_src and has_bbox and has_verifiable_source_evidence(record, root=root)
        if not is_registered_with_evidence and not has_card:
            raise ValueError(
                f"Unverified catalog item: catalogId '{effective_cid}' is not in catalog_065.json "
                f"and lacks independent verifiable source screenshot card evidence."
            )

    # 6. Physical consistency check (cross-mismatch validation of dimensions and quality)
    if effective_cid:
        rec_w = record.get("widthCells") or record.get("width") or record.get("w")
        rec_h = record.get("heightCells") or record.get("height") or record.get("h")
        rec_q = record.get("quality") or record.get("rarity")
        if (rec_w is not None and rec_h is not None) or rec_q is not None:
            w_val = int(rec_w) if rec_w is not None else None
            h_val = int(rec_h) if rec_h is not None else None
            validate_item_physical_consistency(
                effective_cid,
                name=effective_name,
                quality=rec_q,
                width=w_val,
                height=h_val,
                root=root,
            )

    # 7. Delegate to validate_item_identity
    representative_status = (
        next(iter(confirmed_statuses.values()), None)
        or next(iter(unconfirmed_statuses.values()), None)
        or next(iter(statuses.values()), "UNSPECIFIED")
    )
    validate_item_identity(effective_cid, effective_name, representative_status)
    return True


def get_valid_physical_profiles(catalog_id: str, root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return all verified physical profiles (dimensions, quality, name) for catalog_id."""
    _init_catalog()
    cid = str(catalog_id or "").strip()
    if not cid:
        return []
    profiles: List[Dict[str, Any]] = []

    # 1. From immutable verified cards
    cards = _get_immutable_verified_cards(root)
    for c in cards:
        if cid == c.get("catalogId") or cid in c.get("alternateCatalogIds", set()):
            w = int(c.get("widthCells") or 1)
            h = int(c.get("heightCells") or 1)
            profiles.append({
                "name": c.get("name"),
                "widthCells": w,
                "heightCells": h,
                "shapes": {(w, h), (h, w)},
                "quality": _normalize_quality_str(c.get("quality")),
                "source": "verified_source_card_registry",
            })

    # 2. From official catalog_065
    if cid in _CATALOG_065_IDS:
        off = _OFFICIAL_CATALOG[cid]
        w = int(off.get("widthCells") or 1)
        h = int(off.get("heightCells") or 1)
        profiles.append({
            "name": off.get("name"),
            "widthCells": w,
            "heightCells": h,
            "shapes": {(w, h), (h, w)},
            "quality": _normalize_quality_str(off.get("quality")),
            "source": "catalog_065",
        })
    return profiles


def get_authoritative_item_metadata(catalog_id: str, root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Return authoritative metadata for catalog_id, preferring verified source card registry over legacy catalog_065."""
    _init_catalog()
    cid = str(catalog_id or "").strip()
    if not cid:
        return None
    cards = _get_immutable_verified_cards(root)
    for c in cards:
        if cid == c.get("catalogId"):
            return {
                "catalogId": cid,
                "name": c.get("name"),
                "widthCells": int(c.get("widthCells") or 1),
                "heightCells": int(c.get("heightCells") or 1),
                "quality": c.get("quality"),
                "value": c.get("value"),
                "source": "verified_source_card_registry",
            }
    if cid in _OFFICIAL_CATALOG:
        return _OFFICIAL_CATALOG[cid]
    return None


def validate_item_physical_consistency(
    catalog_id: str,
    *,
    name: Optional[str] = None,
    quality: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    root: Optional[Path] = None,
) -> bool:
    """Validates that an item's physical observations strictly match at least one verified catalog profile."""
    _init_catalog()
    cid = str(catalog_id or "").strip()
    if not cid or not is_valid_catalog_id(cid):
        raise ValueError(f"Invalid or unrecognized catalogId: {cid!r}")

    profiles = get_valid_physical_profiles(cid, root=root)
    if not profiles:
        raise ValueError(f"No physical profiles found for catalogId: {cid!r}")

    # Name check
    if name is not None:
        clean_name = str(name).strip()
        matching_name = [p for p in profiles if p.get("name") == clean_name]
        if not matching_name:
            valid_names = sorted(set(p["name"] for p in profiles if p.get("name")))
            raise ValueError(
                f"Name mismatch for catalogId {cid!r}: record specifies {clean_name!r}, "
                f"expected {valid_names}."
            )
        profiles = matching_name

    # Dimension check
    if width is not None and height is not None:
        rw, rh = int(width), int(height)
        matching_dim = [p for p in profiles if (rw, rh) in p["shapes"]]
        if not matching_dim:
            valid_dims = sorted(set(f"{p['widthCells']}x{p['heightCells']}" for p in profiles))
            raise ValueError(
                f"Physical dimension mismatch for catalogId {cid!r}: record specifies {rw}x{rh}, "
                f"but catalog requires one of {valid_dims}."
            )
        profiles = matching_dim

    # Quality check
    if quality is not None:
        norm_q = _normalize_quality_str(quality)
        matching_q = [p for p in profiles if p.get("quality") == norm_q]
        if not matching_q:
            valid_quals = sorted(set(str(p.get("quality")) for p in profiles if p.get("quality")))
            raise ValueError(
                f"Physical quality mismatch for catalogId {cid!r}: record specifies {quality!r}, "
                f"but catalog requires one of {valid_quals}."
            )

    return True


def validate_manifest_records(records: Sequence[Dict[str, Any]], root: Optional[Path] = None) -> List[str]:
    """Validates a sequence of manifest records and returns all error descriptions."""
    errors: List[str] = []
    for idx, r in enumerate(records):
        try:
            validate_catalog_record(r, root=root)
        except Exception as ex:
            cid = r.get("catalogId", f"index-{idx}")
            errors.append(f"Record {cid}: {ex}")
    return errors
