#!/usr/bin/env python3
"""Reproducible gate F for the ITCH/tkeep subset of Task 6."""

import argparse
import ast
import json
import re
from pathlib import Path


CAMPAIGNS = {
    "fase1-parser-rtl": {
        "tests": "verification/testbenches/parser",
        "ids": (
            "SEC-FRM-04", "SEC-FRM-05", "SEC-FRM-06", "SEC-FRM-07",
            "SEC-FRM-08", "REP-02",
        ),
    },
    "fase3-optimizacion": {
        "tests": "verification/testbenches/phase3",
        "ids": ("P32-01", "P32-02", "CHAIN-01"),
    },
    "fase3-uram": {
        "tests": "verification/testbenches/uram",
        "ids": ("ANX-01", "ANX-02", "CHAIN-01"),
    },
}

# CHAIN-01 belongs to both phase 3 contracts, but URAM deliberately reuses the
# end-to-end test of the chain. The rest of the IDs use the mirror directory
# declared by their campaign in specs/gherkin-espejos.json.
EXTERNAL_TESTS = {
    ("fase3-uram", "CHAIN-01"):
        "verification/testbenches/phase3/test_chain32.py",
}


def _contains_id(text, case):
    token = re.escape(case)
    return re.search(rf"(?<![A-Z0-9-]){token}(?![A-Z0-9-])", text, re.I)


SCENARIO = re.compile(
    r"^\s*(?:Escenario|Scenario)\s*:\s*"
    r"([A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)(?=\s|$)",
    re.I,
)


def _scenario_ids(path):
    ids = []
    for file in sorted(path.rglob("*.feature")):
        for line in file.read_text(encoding="utf-8").splitlines():
            match = SCENARIO.match(line)
            if match:
                ids.append(match.group(1).upper())
    return ids


def _test_names(path):
    files = [path] if path.is_file() else sorted(path.rglob("*.py"))
    names = []
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        names.extend(
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return names


def _matches_test(case, name):
    parts = (re.escape(part) for part in case.lower().split("-"))
    pattern = r"^test_?" + r"_?".join(parts) + r"(?:_|$)"
    return re.match(pattern, name.lower()) is not None


def check_repo(root):
    """Returns a stable list of failures; empty means PASS."""
    root = Path(root)
    errors = []
    manifest_path = root / "specs/gherkin-espejos.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"unreadable manifest: {exc}"]
    if not isinstance(manifest, dict) or not manifest:
        return ["empty manifest"]

    for gherkin, tests in manifest.items():
        if not isinstance(gherkin, str) or not isinstance(tests, str):
            errors.append("manifest: keys and mirrors must be text paths")
            continue
        if not (root / gherkin).is_dir():
            errors.append(f"{gherkin}: nonexistent Gherkin path")
        if not (root / tests).exists():
            errors.append(f"{gherkin}: nonexistent mirror path: {tests}")

    for campaign, contract in CAMPAIGNS.items():
        gherkin_rel = f"specs/{campaign}/gherkin"
        expected_tests = contract["tests"]
        if gherkin_rel not in manifest:
            errors.append(f"{gherkin_rel}: missing from the manifest")
        elif manifest[gherkin_rel] != expected_tests:
            errors.append(
                f"{gherkin_rel}: mirror {manifest[gherkin_rel]}, "
                f"expected {expected_tests}")

        feature_dir = root / gherkin_rel
        scenario_ids = _scenario_ids(feature_dir) if feature_dir.is_dir() else []
        spec_path = root / f"specs/{campaign}/spec.md"
        report_path = root / f"specs/{campaign}/verify-report.md"
        spec_text = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
        report_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""

        for case in contract["ids"]:
            count = scenario_ids.count(case)
            if count != 1:
                errors.append(
                    f"{campaign}/{case}: appears {count} times in its Gherkin corpus")
            if not _contains_id(spec_text, case):
                errors.append(f"{campaign}/{case}: missing from spec.md")
            if not _contains_id(report_text, case):
                errors.append(f"{campaign}/{case}: missing from verify-report.md")

            test_rel = EXTERNAL_TESTS.get((campaign, case), expected_tests)
            test_path = root / test_rel
            names = _test_names(test_path) if test_path.exists() else []
            if not any(_matches_test(case, name) for name in names):
                errors.append(
                    f"{campaign}/{case}: no explicit mirror test in {test_rel}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    errors = check_repo(args.root)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        raise SystemExit(1)
    print(
        "Gate F PASS: 12 IDs in 3 campaigns; unique Gherkin per campaign, "
        "spec/test/verify-report present and manifest paths existing")
    print(
        "External mirror verified: fase3-uram/CHAIN-01 -> "
        "verification/testbenches/phase3/test_chain32.py")


if __name__ == "__main__":
    main()
