"""Audit replayed inventories against independent labels; partial is not PASS."""
import argparse
import hashlib
import json
from pathlib import Path


def audit(run_paths, annotations):
    return audit_with_sources(run_paths, annotations)


def _development_labels(manifest):
    labels = {}
    for record in (manifest or {}).get("records", []):
        acceptance = record.get("acceptanceSample") or {}
        fixture = acceptance.get("fixture")
        rect = acceptance.get("rect")
        if not fixture or not isinstance(rect, list) or len(rect) != 4:
            continue
        labels[(Path(fixture).name, tuple(rect))] = {
            "name": record.get("name"),
            "value": record.get("value"),
            "source": "video-development-reference",
            "catalogId": record.get("catalogId"),
            "imagePath": record.get("imagePath"),
            "imageSha256": record.get("imageSha256"),
            "sourceVideo": record.get("sourceVideo"),
            "sourceVideoSha256": record.get("sourceVideoSha256"),
            "sourceSeconds": record.get("sourceSeconds"),
            "sourceFrameIndex": record.get("sourceFrameIndex"),
            "acceptanceSample": acceptance,
        }
    return labels


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_development_evidence(item, expected, repository_root):
    evidence = item.get("identityEvidence") or {}
    errors = []
    if evidence.get("evidenceSource") != "VIDEO_DEVELOPMENT_REFERENCE_MATCH":
        errors.append("MISSING_VIDEO_DEVELOPMENT_REFERENCE_MATCH")
        return errors
    if evidence.get("candidateCatalogId") != expected.get("catalogId"):
        errors.append("DEVELOPMENT_REFERENCE_CATALOG_ID_MISMATCH")
    candidate = next((candidate for candidate in evidence.get("rankedCandidates", [])
                      if candidate.get("catalogId") == expected.get("catalogId")), None)
    reference = (candidate or {}).get("videoDevelopmentReference") or {}
    for field in ("imagePath", "imageSha256", "sourceVideo", "sourceVideoSha256",
                  "sourceSeconds", "sourceFrameIndex"):
        if reference.get(field) != expected.get(field):
            errors.append(f"DEVELOPMENT_REFERENCE_{field.upper()}_MISMATCH")
    image_path = repository_root / str(expected.get("imagePath") or "")
    if not image_path.is_file():
        errors.append("DEVELOPMENT_REFERENCE_IMAGE_MISSING")
    elif _sha256(image_path) != expected.get("imageSha256"):
        errors.append("DEVELOPMENT_REFERENCE_IMAGE_SHA_MISMATCH")
    acceptance = expected.get("acceptanceSample") or {}
    if expected.get("imagePath") == acceptance.get("fixture"):
        errors.append("DEVELOPMENT_REFERENCE_REUSES_ACCEPTANCE_FIXTURE")
    return errors


def _audit_identity_originals(run, settlement):
    errors = []
    truth = settlement.get("truthEvidence") or {}
    originals = {item.get("evidenceId"): item for item in truth.get("fileOriginals", [])}
    for item in settlement.get("settlementItems") or []:
        observation = item.get("identityObservation")
        if not observation:
            continue
        evidence_id = observation.get("parentEvidenceId")
        expected_sha = observation.get("parentSha256")
        original = originals.get(evidence_id)
        rect = tuple(item.get(key) for key in ("row", "col", "widthCells", "heightCells"))
        if not original:
            errors.append({"rect": rect, "reason": "IDENTITY_PARENT_ORIGINAL_MISSING",
                           "evidenceId": evidence_id})
            continue
        if original.get("sha256") != expected_sha:
            errors.append({"rect": rect, "reason": "IDENTITY_PARENT_SHA_MISMATCH",
                           "evidenceId": evidence_id})
        relative_path = original.get("relativePath")
        path = run / "data" / relative_path if relative_path else None
        if path is None or not path.is_file():
            errors.append({"rect": rect, "reason": "IDENTITY_PARENT_FILE_MISSING",
                           "evidenceId": evidence_id, "relativePath": relative_path})
        elif _sha256(path) != original.get("sha256"):
            errors.append({"rect": rect, "reason": "IDENTITY_PARENT_FILE_SHA_MISMATCH",
                           "evidenceId": evidence_id, "relativePath": relative_path})
    return errors


def audit_with_sources(run_paths, annotations, development_manifest=None,
                       repository_root=None):
    development_labels = _development_labels(development_manifest)
    repository_root = Path(repository_root or Path(__file__).resolve().parents[1])
    results = []
    for run in run_paths:
        replay = json.loads((run / "report.json").read_text(encoding="utf-8"))
        for history in sorted((run / "data").glob("history-*.json")):
            for record in json.loads(history.read_text(encoding="utf-8"))["records"]:
                settlement = record.get("settlement") or {}
                total = settlement.get("actualTotal")
                # Totals identify the fixture only; never generate an item label.
                samples = [s for s in annotations if s.get("actualTotal") == total]
                if len(samples) != 1:
                    raise ValueError(f"No unique independent fixture for {run}: {total}")
                sample = samples[0]
                labels = {tuple(i["rect"]): i for i in sample.get("identityAnnotations", [])}
                development_for_sample = {
                    rect: label for (fixture, rect), label in development_labels.items()
                    if fixture == sample["image"] or Path(fixture).name == Path(sample["image"]).name
                }
                expected_rects = {tuple(r) for r in sample["rectangles"]}
                items = settlement.get("settlementItems") or []
                seen, wrong, unknown, unlabelled_exact = set(), [], [], []
                development_matches, development_errors = [], []
                matched = 0
                for item in items:
                    rect = tuple(item[k] for k in ("row", "col", "widthCells", "heightCells"))
                    if rect in seen:
                        wrong.append({"rect": rect, "reason": "DUPLICATE_PHYSICAL_ITEM"})
                    seen.add(rect)
                    if item.get("status") != "exact":
                        unknown.append(rect)
                        continue
                    label = labels.get(rect)
                    if label is None:
                        label = development_for_sample.get(rect)
                        if label is not None:
                            errors = _audit_development_evidence(item, label, repository_root)
                            development_matches.append(rect)
                            development_errors.extend({"rect": rect, "reason": reason}
                                                      for reason in errors)
                    if label is None or "value" not in label:
                        unlabelled_exact.append(rect)
                    elif item.get("name") != label["name"] or item.get("price") != label["value"]:
                        wrong.append({"rect": rect, "expected": label,
                                      "actual": {k: item.get(k) for k in ("name", "price")}})
                    else:
                        matched += 1
                geometry_ok = seen == expected_rects and len(items) == len(expected_rects)
                labels_complete = (set(labels) == expected_rects
                                   and all('value' in label for label in labels.values()))
                all_labels = {**labels, **development_for_sample}
                labels_complete = (set(all_labels) == expected_rects
                                   and all('value' in label for label in all_labels.values()))
                label_sum = sum(label['value'] for label in all_labels.values()) if labels_complete else None
                original_errors = _audit_identity_originals(run, settlement)
                passed = (replay["status"] == "COMPLETE" and geometry_ok and not wrong
                          and not unknown and not unlabelled_exact
                          and not development_errors and not original_errors
                          and labels_complete and label_sum == total)
                failed = bool(wrong) or not geometry_ok or replay["status"] != "COMPLETE"
                results.append({"run": str(run), "fixture": sample["image"], "actualTotal": total,
                                "visibleCount": len(expected_rects), "independentLabelCount": len(labels),
                                "developmentReferenceCount": len(development_for_sample),
                                "completeLabelValueSum": label_sum,
                                "labelValueSumMatchesBill": label_sum == total if labels_complete else None,
                                "matchedNameAndValueCount": matched,
                                "developmentReferenceMatches": development_matches,
                                "developmentReferenceErrors": development_errors,
                                "identityOriginalErrors": original_errors,
                                "unknownRectangles": unknown,
                                "unlabelledExactRectangles": unlabelled_exact, "wrongItems": wrong,
                                "geometryCorrect": geometry_ok,
                                "status": "FAIL" if failed else "PASS" if passed else "PARTIAL"})
    complete = len(results) == len({r["fixture"] for r in results}) == 5 and all(r["status"] == "PASS" for r in results)
    return {"status": "FAIL" if any(r["status"] == "FAIL" for r in results) else "PASS" if complete else "PARTIAL",
            "scope": "Five settlement inventories; excludes live warehouse acceptance", "matches": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--annotations", type=Path, default=Path("tests/fixtures/settlement_cards_v2/annotations.json"))
    parser.add_argument("--development-references", type=Path,
                        help="Optional development-only reference manifest; never merged into visual_catalog_v2.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    development_manifest = (json.loads(args.development_references.read_text(encoding="utf-8"))
                            if args.development_references else None)
    result = audit_with_sources(args.runs,
                                json.loads(args.annotations.read_text(encoding="utf-8")),
                                development_manifest=development_manifest)
    result["annotationSha256"] = hashlib.sha256(args.annotations.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result["status"])
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
