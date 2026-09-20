# -*- coding: utf-8 -*-
"""Stepwise Python/native comparison for the V2-2C offline evidence run.

The Python file is imported and executed as the reference; this script only compares the
recorded outputs. PYTHON_PARITY scenarios must agree on the safety surface at every step.
NATIVE_EXTENSION scenarios are checked for native support and fail-closed actuator accounting,
while their Python unsupported steps are recorded as an expected contract difference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


SURFACE_FIELDS = (
    "isFrozen",
    "scanPermitted",
    "blockedCount",
    "executedCount",
    "wheelEmissionCount",
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def surface(value: dict[str, Any]) -> dict[str, Any]:
    return {field: value.get(field) for field in SURFACE_FIELDS}


def state_from_step(step: dict[str, Any]) -> dict[str, Any] | None:
    state = step.get("state")
    return state if isinstance(state, dict) else None


def compare_parity(
    scenario: dict[str, Any],
    python_result: dict[str, Any],
    native_result: dict[str, Any],
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    scenario_id = scenario["id"]

    if not python_result.get("supportedByPython"):
        differences.append({
            "scenarioId": scenario_id,
            "kind": "unexpected_python_unsupported",
            "detail": python_result.get("unsupportedSteps", []),
        })
    if not native_result.get("supportedByNative"):
        differences.append({
            "scenarioId": scenario_id,
            "kind": "unexpected_native_unsupported",
            "detail": native_result.get("unsupportedSteps", []),
        })

    python_steps = python_result.get("steps", [])
    native_steps = native_result.get("steps", [])
    if len(python_steps) != len(native_steps):
        differences.append({
            "scenarioId": scenario_id,
            "kind": "step_count",
            "python": len(python_steps),
            "native": len(native_steps),
        })

    for index, (python_step, native_step) in enumerate(zip(python_steps, native_steps)):
        python_state = state_from_step(python_step)
        native_state = state_from_step(native_step)
        if python_state is None or native_state is None:
            differences.append({
                "scenarioId": scenario_id,
                "step": index,
                "kind": "missing_step_state",
            })
            continue
        python_surface = surface(python_state)
        native_surface = surface(native_state)
        if python_surface != native_surface:
            differences.append({
                "scenarioId": scenario_id,
                "step": index,
                "kind": "safety_surface",
                "python": python_surface,
                "native": native_surface,
            })

        if python_step.get("kind") == "ScanRequest":
            if python_step.get("actuatorCalled") != native_step.get("actuatorCalled"):
                differences.append({
                    "scenarioId": scenario_id,
                    "step": index,
                    "kind": "actual_actuator_call",
                    "python": python_step.get("actuatorCalled"),
                    "native": native_step.get("actuatorCalled"),
                })

    python_final = python_result.get("final", {})
    native_final = native_result.get("final", {})
    if surface(python_final) != surface(native_final):
        differences.append({
            "scenarioId": scenario_id,
            "kind": "final_safety_surface",
            "python": surface(python_final),
            "native": surface(native_final),
        })

    if python_final.get("actuatorCallCount") != python_final.get("wheelEmissionCount"):
        differences.append({
            "scenarioId": scenario_id,
            "kind": "python_call_counter_inconsistent",
            "actuatorCallCount": python_final.get("actuatorCallCount"),
            "wheelEmissionCount": python_final.get("wheelEmissionCount"),
        })
    if native_final.get("actuatorCallCount") != native_final.get("wheelEmissionCount"):
        differences.append({
            "scenarioId": scenario_id,
            "kind": "native_call_counter_inconsistent",
            "actuatorCallCount": native_final.get("actuatorCallCount"),
            "wheelEmissionCount": native_final.get("wheelEmissionCount"),
        })
    return differences


def check_native_extension(scenario: dict[str, Any], native_result: dict[str, Any]) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    scenario_id = scenario["id"]
    if not native_result.get("supportedByNative") or native_result.get("unsupportedSteps"):
        differences.append({
            "scenarioId": scenario_id,
            "kind": "native_extension_unsupported",
            "detail": native_result.get("unsupportedSteps", []),
        })
    final = native_result.get("final", {})
    if final.get("actuatorCallCount") != final.get("wheelEmissionCount"):
        differences.append({
            "scenarioId": scenario_id,
            "kind": "native_call_counter_inconsistent",
            "actuatorCallCount": final.get("actuatorCallCount"),
            "wheelEmissionCount": final.get("wheelEmissionCount"),
        })
    return differences


def check_expected_assertions(
    scenario: dict[str, Any],
    native_result: dict[str, Any],
    expectation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    scenario_id = scenario["id"]
    if expectation is None:
        return [{
            "scenarioId": scenario_id,
            "kind": "missing_native_extension_expectation",
        }]

    differences: list[dict[str, Any]] = []
    steps = native_result.get("steps", [])

    def check_value(actual: Any, expected: Any, location: str) -> None:
        if actual != expected:
            differences.append({
                "scenarioId": scenario_id,
                "kind": "native_expectation_mismatch",
                "location": location,
                "expected": expected,
                "actual": actual,
            })

    for assertion in expectation.get("assertions", []):
        index = assertion["step"]
        if index >= len(steps):
            differences.append({
                "scenarioId": scenario_id,
                "kind": "native_expectation_missing_step",
                "step": index,
            })
            continue
        actual_step = steps[index]
        for key, expected in assertion.items():
            if key in {"step", "state"}:
                continue
            check_value(actual_step.get(key), expected, f"steps[{index}].{key}")
        for key, expected in assertion.get("state", {}).items():
            check_value(
                actual_step.get("state", {}).get(key),
                expected,
                f"steps[{index}].state.{key}",
            )

    final = native_result.get("final", {})
    for key, expected in expectation.get("final", {}).items():
        check_value(final.get(key), expected, f"final.{key}")
    return differences


def mutate_native_allow(native_items: list[dict[str, Any]], scenario_id: str) -> None:
    """Apply an adversarial in-memory mutation for the comparator negative test.

    This never changes the recorded native result file. It deliberately makes one native
    extension claim that N01 reached ALLOW and sent a wheel, so its expectation contract
    must reject the tampered result with a non-zero exit.
    """
    target = next((item for item in native_items if item.get("scenarioId") == scenario_id), None)
    if target is None:
        raise ValueError(f"native scenario not found for mutation: {scenario_id}")

    allow_state = {
        "isFrozen": False,
        "scanPermitted": True,
        "activeReasons": [],
        "primaryReason": None,
        "awaitingRearm": False,
        "blockedCount": 0,
        "executedCount": 1,
        "wheelEmissionCount": 1,
        "actuatorCallCount": 1,
    }
    target.setdefault("final", {}).update(allow_state)
    for step in target.get("steps", []):
        if step.get("kind") != "ScanRequest":
            continue
        step["executed"] = True
        step["actuatorCalled"] = True
        step.setdefault("state", {}).update(allow_state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", required=True)
    parser.add_argument("--python", required=True, dest="python_path")
    parser.add_argument("--native", required=True, dest="native_path")
    parser.add_argument("--native-expectations", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--raw-out")
    parser.add_argument(
        "--mutate-native-allow",
        help="adversarial in-memory mutation for the negative comparator test",
    )
    args = parser.parse_args()

    scenarios_path = Path(args.scenarios)
    python_path = Path(args.python_path)
    native_path = Path(args.native_path)
    expectations_path = Path(args.native_expectations)
    scenarios = load(scenarios_path)
    python_results = load(python_path)
    native_results = load(native_path)
    native_expectations = load(expectations_path)
    python_by_id = {item["scenarioId"]: item for item in python_results["results"]}
    native_items = native_results.get("results", native_results.get("Results", []))
    if args.mutate_native_allow:
        mutate_native_allow(native_items, args.mutate_native_allow)
    native_by_id = {item["scenarioId"]: item for item in native_items}
    expectation_by_id = {
        item["scenarioId"]: item for item in native_expectations["expectations"]
    }

    unexpected: list[dict[str, Any]] = []
    scenario_reports: list[dict[str, Any]] = []
    parity_count = 0
    extension_count = 0
    divergence_count = 0
    expected_observed_count = 0

    for scenario in scenarios["scenarios"]:
        scenario_id = scenario["id"]
        python_result = python_by_id.get(scenario_id)
        native_result = native_by_id.get(scenario_id)
        if python_result is None or native_result is None:
            unexpected.append({
                "scenarioId": scenario_id,
                "kind": "missing_result",
                "pythonPresent": python_result is not None,
                "nativePresent": native_result is not None,
            })
            continue

        if scenario["surface"] == "PYTHON_PARITY":
            parity_count += 1
            differences = compare_parity(scenario, python_result, native_result)
            observed_expected: list[dict[str, Any]] = []
        elif scenario["surface"] == "NATIVE_EXTENSION":
            extension_count += 1
            differences = check_native_extension(scenario, native_result)
            differences.extend(check_expected_assertions(
                scenario, native_result, expectation_by_id.get(scenario_id)
            ))
            observed_expected = []
        elif scenario["surface"] == "DIVERGENCE":
            divergence_count += 1
            observed = compare_parity(scenario, python_result, native_result)
            expected_contract = scenario.get("expectedDivergence")
            if not expected_contract:
                differences = [{
                    "scenarioId": scenario_id,
                    "kind": "missing_expected_divergence_contract",
                }]
                observed_expected = []
            elif not observed:
                differences = [{
                    "scenarioId": scenario_id,
                    "kind": "expected_divergence_not_observed",
                }]
                observed_expected = []
            else:
                allowed_kinds = set(expected_contract.get("allowedKinds", []))
                observed_expected = [
                    difference for difference in observed
                    if difference.get("kind") in allowed_kinds
                ]
                differences = [
                    difference for difference in observed
                    if difference.get("kind") not in allowed_kinds
                ]
                expected_observed_count += len(observed_expected)
        else:
            differences = [{
                "scenarioId": scenario_id,
                "kind": "unknown_surface",
                "surface": scenario.get("surface"),
            }]
            observed_expected = []
        unexpected.extend(differences)
        scenario_reports.append({
            "scenarioId": scenario_id,
            "surface": scenario["surface"],
            "passed": not differences,
            "observedExpectedDifferences": observed_expected,
            "unexpectedDifferences": differences,
        })

    native_extension_ids = {
        scenario["id"]
        for scenario in scenarios["scenarios"]
        if scenario["surface"] == "NATIVE_EXTENSION"
    }
    expectation_ids = set(expectation_by_id)
    for missing_id in sorted(native_extension_ids - expectation_ids):
        unexpected.append({
            "scenarioId": missing_id,
            "kind": "missing_native_extension_expectation",
        })
    for extra_id in sorted(expectation_ids - native_extension_ids):
        unexpected.append({
            "scenarioId": extra_id,
            "kind": "expectation_for_non_native_extension",
        })

    expected = [
        {
            "id": item["id"],
            "contractGap": item.get("contractGap"),
            "description": item.get("description"),
            "resolution": item.get("resolution"),
        }
        for item in scenarios.get("divergenceScenarios", [])
    ]

    payload: dict[str, Any] = {
        "schemaVersion": "v2.2c.freeze.parity.compare.v2",
        "scenarioSchemaVersion": scenarios.get("schemaVersion"),
        "pythonResults": str(python_path),
        "nativeResults": str(native_path),
        "nativeExpectations": str(expectations_path),
        "parityScenarioCount": parity_count,
        "nativeExtensionScenarioCount": extension_count,
        "divergenceScenarioCount": divergence_count,
        "scenarioCount": len(scenarios["scenarios"]),
        "expectedDifferences": expected,
        "expectedDifferenceCount": len(expected),
        "expectedObservedDifferenceCount": expected_observed_count,
        "unexpectedDifferences": unexpected,
        "unexpectedDifferenceCount": len(unexpected),
        "allPassed": not unexpected,
        "scenarioReports": scenario_reports,
        "mutation": (
            {"nativeScenarioId": args.mutate_native_allow, "mode": "ALLOW_SCAN"}
            if args.mutate_native_allow else None
        ),
        "sourceSha256": {
            "scenarios": hashlib.sha256(scenarios_path.read_bytes()).hexdigest(),
            "pythonResults": hashlib.sha256(python_path.read_bytes()).hexdigest(),
            "nativeResults": hashlib.sha256(native_path.read_bytes()).hexdigest(),
            "nativeExpectations": hashlib.sha256(expectations_path.read_bytes()).hexdigest(),
        },
    }
    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.raw_out:
        raw_path = Path(args.raw_out)
        with raw_path.open("w", encoding="utf-8", newline="\n") as raw:
            raw.write(json.dumps({
                "kind": "comparison_header",
                "scenarioCount": payload["scenarioCount"],
                "expectedDifferenceCount": payload["expectedDifferenceCount"],
                "expectedObservedDifferenceCount": payload["expectedObservedDifferenceCount"],
            }, ensure_ascii=False) + "\n")
            for report in scenario_reports:
                raw.write(json.dumps({"kind": "comparison_scenario", **report}, ensure_ascii=False) + "\n")
                for difference in report["observedExpectedDifferences"]:
                    raw.write(json.dumps({
                        "kind": "expected_divergence_observed",
                        **difference,
                    }, ensure_ascii=False) + "\n")
            for difference in unexpected:
                raw.write(json.dumps({"kind": "unexpected_difference", **difference}, ensure_ascii=False) + "\n")
    print(
        f"comparison: {parity_count} parity + {extension_count} native-extension + "
        f"{divergence_count} divergence scenarios; expectedDifferences={len(expected)} "
        f"observedExpected={expected_observed_count} unexpectedDifferences={len(unexpected)}"
    )
    return 0 if not unexpected else 1


if __name__ == "__main__":
    sys.exit(main())
