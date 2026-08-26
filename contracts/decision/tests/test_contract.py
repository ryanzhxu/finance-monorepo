"""Validate decision.v1 fixtures against the canonical JSON Schema.

Run with an ephemeral jsonschema dependency (does not touch pyproject.toml/uv.lock):

    UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-project --with jsonschema \\
        python contracts/decision/tests/test_contract.py

Scope: schema validation only. The two numeric invariants JSON Schema cannot
express -- priceRange.low < priceRange.high, and opportunityRange.high <
reduceRange.low -- are deliberately NOT checked here. They belong to the
invariant layer. Keeping the layers in separate runners is what lets
invalid-overlapping-ranges.json demonstrate that the invariant layer does real
work rather than restating the schema: that fixture is schema-VALID and fails
only the invariant check.
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


DECISION_SCHEMA = load(SCHEMA_DIR / "decision.schema.json")
DECISION_VALIDATOR = Draft202012Validator(DECISION_SCHEMA)

# (fixture filename, expect_schema_valid)
#
# Note invalid-overlapping-ranges.json is expected SCHEMA-VALID. Its violation
# is a cross-field numeric comparison, which draft 2020-12 cannot express. It is
# the invariant layer's job to reject it, not this file's.
FIXTURE_CASES: list[tuple[str, bool]] = [
    ("valid-three-horizon.json", True),
    ("valid-unavailable-landscape.json", True),
    ("valid-technical-only.json", True),
    ("invalid-overlapping-ranges.json", True),
    ("invalid-action-for-price-state.json", False),
    ("invalid-unknown-enum.json", False),
    ("invalid-missing-required-field.json", False),
    ("invalid-unsupported-version.json", False),
]

# (fixture filename, expected json_path of the single validation error)
#
# Assert on json_path, never on message text. jsonschema reports the offending
# VALUE ("'buy' is not one of ['trim', 'sell']"), not the field name, and the
# wording is version-dependent. A message-matching assertion looks correct and
# silently rots.
INVALID_ERROR_PATHS: list[tuple[str, str]] = [
    ("invalid-action-for-price-state.json", "$.horizons.long.action"),
    ("invalid-unknown-enum.json", "$.horizons.short.executionIntent"),
    ("invalid-missing-required-field.json", "$.horizons.mid"),
    ("invalid-unsupported-version.json", "$.contractVersion"),
]


def run_fixture_cases() -> tuple[int, int, list[str]]:
    """Every fixture matches its expected schema-valid/invalid outcome."""
    passed = failed = 0
    failures: list[str] = []

    for filename, expect_valid in FIXTURE_CASES:
        path = FIXTURES_DIR / filename
        if not path.exists():
            failed += 1
            failures.append(f"{filename}: fixture file is missing")
            continue

        errors = list(DECISION_VALIDATOR.iter_errors(load(path)))
        is_valid = not errors

        if is_valid == expect_valid:
            passed += 1
        else:
            failed += 1
            if expect_valid:
                failures.append(
                    f"{filename}: expected schema-valid, rejected with "
                    f"{[e.message for e in errors]}"
                )
            else:
                failures.append(f"{filename}: expected schema rejection, got none")

    return passed, failed, failures


def run_invalid_error_paths() -> tuple[int, int, list[str]]:
    """Each invalid fixture fails once, at the exact field it was mutated at.

    One mutation per fixture means one error. More than one means the fixture
    drifted and is now passing for a reason it was not written to test.
    """
    passed = failed = 0
    failures: list[str] = []

    for filename, expected_path in INVALID_ERROR_PATHS:
        path = FIXTURES_DIR / filename
        if not path.exists():
            failed += 1
            failures.append(f"{filename}: fixture file is missing")
            continue

        errors = list(DECISION_VALIDATOR.iter_errors(load(path)))
        if len(errors) != 1:
            failed += 1
            failures.append(
                f"{filename}: expected exactly 1 error, got {len(errors)} at "
                f"{[e.json_path for e in errors]}"
            )
            continue

        actual_path = errors[0].json_path
        if actual_path == expected_path:
            passed += 1
        else:
            failed += 1
            failures.append(
                f"{filename}: error at {actual_path}, expected {expected_path}"
            )

    return passed, failed, failures


def check_every_fixture_is_declared() -> tuple[int, int, list[str]]:
    """No fixture on disk goes untested.

    Without this, adding a fixture file and forgetting to list it in
    FIXTURE_CASES leaves it silently unvalidated, which is worse than not
    having written it.
    """
    on_disk = {p.name for p in FIXTURES_DIR.glob("*.json")}
    declared = {name for name, _ in FIXTURE_CASES}

    undeclared = sorted(on_disk - declared)
    missing = sorted(declared - on_disk)

    failures = []
    if undeclared:
        failures.append(f"fixtures on disk but not in FIXTURE_CASES: {undeclared}")
    if missing:
        failures.append(f"fixtures in FIXTURE_CASES but not on disk: {missing}")

    return (0, len(failures), failures) if failures else (1, 0, [])


def check_invalid_fixtures_are_named_invalid() -> tuple[int, int, list[str]]:
    """Filename prefix matches intent, so the directory listing does not lie.

    invalid-overlapping-ranges.json is the deliberate exception: it is named
    invalid- because it violates the contract, while being schema-valid.
    """
    schema_valid_exceptions = {"invalid-overlapping-ranges.json"}
    passed = failed = 0
    failures: list[str] = []

    for filename, expect_valid in FIXTURE_CASES:
        if filename in schema_valid_exceptions:
            passed += 1
            continue
        prefix_says_valid = filename.startswith("valid-")
        if prefix_says_valid == expect_valid:
            passed += 1
        else:
            failed += 1
            failures.append(
                f"{filename}: filename prefix disagrees with expected outcome "
                f"(expect_valid={expect_valid})"
            )

    return passed, failed, failures


def main() -> int:
    total_passed = 0
    total_failed = 0
    all_failures: list[str] = []

    for runner in (
        run_fixture_cases,
        run_invalid_error_paths,
        check_every_fixture_is_declared,
        check_invalid_fixtures_are_named_invalid,
    ):
        passed, failed, failures = runner()
        total_passed += passed
        total_failed += failed
        all_failures.extend(failures)

    print(f"decision.v1 contract tests: {total_passed} passed, {total_failed} failed")
    if all_failures:
        print("\nFailures:")
        for f in all_failures:
            print(f"  - {f}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
