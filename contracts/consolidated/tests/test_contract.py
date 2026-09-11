"""Validate consolidated.v1 fixtures against the canonical JSON Schema.

Run with an ephemeral jsonschema dependency (does not touch pyproject.toml/uv.lock):

    UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-project --with jsonschema \\
        python contracts/consolidated/tests/test_contract.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schema"
FIXTURES_DIR = ROOT / "fixtures"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


SCHEMA = load(SCHEMA_DIR / "consolidated.schema.json")
VALIDATOR = Draft202012Validator(SCHEMA)

# (fixture filename, expect_valid)
FIXTURE_CASES = [
    ("valid-pass-with-buy.json", True),
    ("valid-fail-holds-buy.json", True),
    ("valid-engine-failure.json", True),
    ("invalid-buy-with-failed-hurdle.json", False),
    ("invalid-unknown-action.json", False),
    ("invalid-missing-horizon.json", False),
]


def run_fixture_cases() -> tuple[int, int, list[str]]:
    passed = 0
    failed = 0
    failures: list[str] = []

    for filename, expect_valid in FIXTURE_CASES:
        path = FIXTURES_DIR / filename
        if not path.exists():
            failed += 1
            failures.append(f"{filename}: fixture file missing")
            continue

        instance = load(path)
        errors = list(VALIDATOR.iter_errors(instance))
        is_valid = not errors

        if is_valid == expect_valid:
            passed += 1
        else:
            failed += 1
            if expect_valid:
                failures.append(
                    f"{filename}: expected VALID but schema rejected it: "
                    f"{errors[0].message if errors else 'unknown'}"
                )
            else:
                failures.append(f"{filename}: expected INVALID but schema accepted it")

    return passed, failed, failures


def check_buy_with_failed_hurdle_rejected_for_the_right_reason() -> tuple[int, int, list[str]]:
    """Prove invalid-buy-with-failed-hurdle.json is rejected specifically for
    the buy-requires-hurdle-pass invariant, not some unrelated typo."""
    passed = 0
    failed = 0
    failures: list[str] = []

    instance = load(FIXTURES_DIR / "invalid-buy-with-failed-hurdle.json")
    errors = list(VALIDATOR.iter_errors(instance))
    if not errors:
        failed += 1
        failures.append("invalid-buy-with-failed-hurdle.json: expected schema rejection, got none")
    else:
        mentions_adjustments = any(
            "adjustments" in list(e.path) or "adjustments" in str(e.schema_path)
            for e in errors
        )
        if mentions_adjustments:
            passed += 1
        else:
            failed += 1
            failures.append(
                "invalid-buy-with-failed-hurdle.json: rejected, but not clearly via "
                f"the horizonDecision adjustments invariant: {[e.message for e in errors]}"
            )

    return passed, failed, failures


def main() -> int:
    total_passed = 0
    total_failed = 0
    all_failures: list[str] = []

    for runner in (
        run_fixture_cases,
        check_buy_with_failed_hurdle_rejected_for_the_right_reason,
    ):
        passed, failed, failures = runner()
        total_passed += passed
        total_failed += failed
        all_failures.extend(failures)

    print(f"consolidated.v1 contract tests: {total_passed} passed, {total_failed} failed")
    if all_failures:
        print("\nFailures:")
        for f in all_failures:
            print(f"  - {f}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
