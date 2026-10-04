"""Single known settlement frame, isolated ROI, no capture/history/label writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--algorithm-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_root, algorithm_root, output = (p.resolve() for p in
                                           (args.source_root, args.algorithm_root, args.output))
    output.relative_to(source_root / "build")
    if output.exists():
        raise FileExistsError(output)
    provenance = json.loads((ROOT / "tests/fixtures/warehouse_white_frames_v1/provenance.json")
                            .read_text(encoding="utf-8"))
    source = source_root / provenance["source"]
    if sha(source) != provenance["sourceSha256"]:
        raise ValueError("Source hash mismatch")
    sys.path.insert(0, str(algorithm_root / "core"))
    import cv2
    from warehouse_vision import WarehouseVisionV1
    image = cv2.imread(str(source))
    if image is None:
        raise ValueError("Unreadable source")
    height, width = image.shape[:2]
    x1, y1, x2, y2 = provenance["cropXYXY"]
    vision = WarehouseVisionV1()
    actual = vision.process_frame(image, grid_roi_norm=(x1/width, y1/height, x2/width, y2/height))
    target_cells = {(5, 5), (5, 6), (6, 5)}
    selected = [s for s in actual["slots"] if any(
        (r, c) in target_cells for r in range(s["row"], s["row"]+s["h"])
        for c in range(s["col"], s["col"]+s["w"]))]
    expected = {(t["col"], t["row"], t["wCells"], t["hCells"], "white")
                for t in provenance["expectedVisibleFrames"]}
    observed = {(s["col"], s["row"], s["w"], s["h"], s["rarity"]) for s in selected}
    issues = [] if observed == expected else [{"group": "分件或误合并", "expected": sorted(expected),
                                              "actual": sorted(observed)}]
    output.mkdir(parents=True)
    overlay = image[y1:y2, x1:x2].copy()
    for s in actual["slots"]:
        x, y, w, h = s["box"]
        colour = (0, 255, 0) if s in selected else (0, 0, 255)
        cv2.rectangle(overlay, (x-x1, y-y1), (x-x1+w-1, y-y1+h-1), colour, 1)
        cv2.putText(overlay, f'{s["trackId"]}:{s["size"]}:{s["rarity"]}', (x-x1+2,y-y1+11),
                    cv2.FONT_HERSHEY_SIMPLEX, .26, (255,255,255), 1, cv2.LINE_AA)
    cv2.imwrite(str(output / "viewport-overlay.png"), overlay)
    hashes = {rel: sha(algorithm_root / rel) for rel in
              ["core/warehouse_vision.py", "core/roi_scaler.py", "assets/catalog_065.json",
               "assets/items/catalog_reference_manifest_v2.json",
               "assets/items/verified_source_card_registry.json"]}
    record = dict(scope="Single known settlement scene, targeted white geometry; not full warehouse accuracy",
                  source=str(source), sourceFileSha256=sha(source), algorithmRoot=str(algorithm_root),
                  inputVersionHashes=hashes, scene=provenance["scene"], sceneBasis="Original visual review",
                  boardCropXYXY=provenance["cropXYXY"], expected=provenance["expectedVisibleFrames"],
                  selectedActual=selected, raw=actual, issues=issues, independentUnseenImages=0,
                  temporalObservations=1, identityTruth=None, quantityTruth=None,
                  liveCaptureRequested=False, formalHistoryTouched=False, formalLabelsTouched=False,
                  sourceUnchanged=(sha(source) == provenance["sourceSha256"]))
    (output / "result.json").write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(algorithmSha256=hashes["core/warehouse_vision.py"],grid=actual["grid"],
                         selected=[dict(box=s["box"],size=s["size"],identity=s["identifiedName"])
                                   for s in selected],issues=issues),ensure_ascii=False))


if __name__ == "__main__":
    main()
