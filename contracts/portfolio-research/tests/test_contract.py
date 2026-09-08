"""Validate portfolio-research.v1 fixtures against the canonical JSON Schema.

Run with an ephemeral jsonschema dependency (does not touch pyproject.toml/uv.lock):

    UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-project --with jsonschema \\
        python contracts/portfolio-research/tests/test_contract.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schema"
FIXTURES_DIR = ROOT / "fixtures"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


REQUEST_SCHEMA = load(SCHEMA_DIR / "request.schema.json")
RESPONSE_SCHEMA = load(SCHEMA_DIR / "response.schema.json")
ERROR_SCHEMA = load(SCHEMA_DIR / "error.schema.json")

REQUEST_VALIDATOR = Draft202012Validator(REQUEST_SCHEMA)
RESPONSE_VALIDATOR = Draft202012Validator(RESPONSE_SCHEMA)
ERROR_VALIDATOR = Draft202012Validator(ERROR_SCHEMA)

# (fixture filename, validator, expect_valid)
FIXTURE_CASES = [
    ("valid-request.json", REQUEST_VALIDATOR, True),
    ("valid-response-complete.json", RESPONSE_VALIDATOR, True),
    ("valid-response-partial.json", RESPONSE_VALIDATOR, True),
    ("valid-response-partial-degraded.json", RESPONSE_VALIDATOR, True),
    ("valid-response-unavailable.json", RESPONSE_VALIDATOR, True),
    ("valid-response-provider-disabled.json", RESPONSE_VALIDATOR, True),
    ("valid-error-auth-required.json", ERROR_VALIDATOR, True),
    ("valid-error-auth-invalid.json", ERROR_VALIDATOR, True),
    ("valid-error-invalid-request.json", ERROR_VALIDATOR, True),
    ("valid-error-unsupported-version.json", ERROR_VALIDATOR, True),
    ("valid-error-research-disabled.json", ERROR_VALIDATOR, True),
    ("valid-error-provider-unavailable.json", ERROR_VALIDATOR, True),
    ("valid-error-rate-limited.json", ERROR_VALIDATOR, True),
    ("valid-error-cost-limit-reached.json", ERROR_VALIDATOR, True),
    ("valid-error-internal-error.json", ERROR_VALIDATOR, True),
    ("valid-error-requestid-unavailable.json", ERROR_VALIDATOR, True),
    ("invalid-missing-required-field.json", REQUEST_VALIDATOR, False),
    ("invalid-wrong-type.json", REQUEST_VALIDATOR, False),
    ("invalid-forbidden-personal-data.json", REQUEST_VALIDATOR, False),
    ("invalid-forbidden-personal-data-riskprofile.json", REQUEST_VALIDATOR, False),
    ("invalid-unsupported-version.json", REQUEST_VALIDATOR, False),
    ("invalid-response-forbidden-recommendation.json", RESPONSE_VALIDATOR, False),
    ("invalid-response-missing-field.json", RESPONSE_VALIDATOR, False),
    ("invalid-error-forbidden-field.json", ERROR_VALIDATOR, False),
]

# All nine error codes must appear across the valid-error-*.json fixtures, and
# error.schema.json's closed enum must contain exactly these nine, no more,
# no fewer.
EXPECTED_ERROR_CODES = {
    "AUTH_REQUIRED",
    "AUTH_INVALID",
    "INVALID_REQUEST",
    "UNSUPPORTED_VERSION",
    "RESEARCH_DISABLED",
    "PROVIDER_UNAVAILABLE",
    "RATE_LIMITED",
    "COST_LIMIT_REACHED",
    "INTERNAL_ERROR",
}

EXPECTED_REASON_CODES = {
    "CONCENTRATION",
    "DRAWDOWN",
    "THESIS_REVIEW",
    "CATALYST_REVIEW",
    "DATA_STALE",
}


def run_fixture_cases() -> tuple[int, int, list[str]]:
    passed = 0
    failed = 0
    failures: list[str] = []

    for filename, validator, expect_valid in FIXTURE_CASES:
        path = FIXTURES_DIR / filename
        if not path.exists():
            failed += 1
            failures.append(f"{filename}: fixture file missing")
            continue

        instance = load(path)
        errors = list(validator.iter_errors(instance))
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
                failures.append(
                    f"{filename}: expected INVALID but schema accepted it"
                )

    return passed, failed, failures


def run_boundary_cases() -> tuple[int, int, list[str]]:
    """Programmatic edge cases not worth a dedicated fixture file each."""
    passed = 0
    failed = 0
    failures: list[str] = []

    base_request = load(FIXTURES_DIR / "valid-request.json")

    def check(name: str, instance: dict, expect_valid: bool) -> None:
        nonlocal passed, failed
        errors = list(REQUEST_VALIDATOR.iter_errors(instance))
        is_valid = not errors
        if is_valid == expect_valid:
            passed += 1
        else:
            failed += 1
            failures.append(
                f"[boundary] {name}: expected "
                f"{'VALID' if expect_valid else 'INVALID'} but got "
                f"{'VALID' if is_valid else 'INVALID'}"
            )

    # symbols: exactly 3 is allowed, 4 is not.
    three_symbols = copy.deepcopy(base_request)
    three_symbols["symbols"] = ["AAA", "BBB", "CCC"]
    check("symbols at max (3)", three_symbols, True)

    four_symbols = copy.deepcopy(base_request)
    four_symbols["symbols"] = ["AAA", "BBB", "CCC", "DDD"]
    check("symbols over max (4)", four_symbols, False)

    zero_symbols = copy.deepcopy(base_request)
    zero_symbols["symbols"] = []
    check("symbols under min (0)", zero_symbols, False)

    dup_symbols = copy.deepcopy(base_request)
    dup_symbols["symbols"] = ["AAA", "AAA"]
    check("duplicate symbols", dup_symbols, False)

    lowercase_symbol = copy.deepcopy(base_request)
    lowercase_symbol["symbols"] = ["aapl"]
    check("symbol format: lowercase rejected", lowercase_symbol, False)

    # reasonCodes: exactly 5 (all enum members) is allowed, 6 is not, and an
    # unknown code must be rejected by the closed enum.
    five_reason_codes = copy.deepcopy(base_request)
    five_reason_codes["reasonCodes"] = sorted(EXPECTED_REASON_CODES)
    check("reasonCodes at max (5, all enum members)", five_reason_codes, True)

    six_reason_codes = copy.deepcopy(base_request)
    six_reason_codes["reasonCodes"] = sorted(EXPECTED_REASON_CODES) + [
        "CONCENTRATION"
    ]
    # Six items but a duplicate -- construct a genuinely distinct 6th value
    # that is not in the enum to also prove the enum is closed.
    six_reason_codes["reasonCodes"][-1] = "PORTFOLIO_REBALANCE"
    check("reasonCodes over max (6) and includes unknown value", six_reason_codes, False)

    unknown_reason_code = copy.deepcopy(base_request)
    unknown_reason_code["reasonCodes"] = ["PORTFOLIO_REBALANCE"]
    check("reasonCode outside closed enum", unknown_reason_code, False)

    zero_reason_codes = copy.deepcopy(base_request)
    zero_reason_codes["reasonCodes"] = []
    check("reasonCodes under min (0)", zero_reason_codes, False)

    dup_reason_codes = copy.deepcopy(base_request)
    dup_reason_codes["reasonCodes"] = ["CONCENTRATION", "CONCENTRATION"]
    check("duplicate reasonCodes", dup_reason_codes, False)

    # reviewItemIds: optional, max 5.
    five_review_items = copy.deepcopy(base_request)
    five_review_items["reviewItemIds"] = [f"item-{i}" for i in range(5)]
    check("reviewItemIds at max (5)", five_review_items, True)

    six_review_items = copy.deepcopy(base_request)
    six_review_items["reviewItemIds"] = [f"item-{i}" for i in range(6)]
    check("reviewItemIds over max (6)", six_review_items, False)

    no_review_items = copy.deepcopy(base_request)
    del no_review_items["reviewItemIds"]
    check("reviewItemIds omitted (optional)", no_review_items, True)

    return passed, failed, failures


def check_error_enum_matches_fixtures() -> tuple[int, int, list[str]]:
    """The error schema's closed enum must exactly match the nine codes the
    architecture doc lists, and every code must be exercised by a fixture."""
    passed = 0
    failed = 0
    failures: list[str] = []

    schema_enum = set(
        ERROR_SCHEMA["properties"]["error"]["properties"]["code"]["enum"]
    )
    if schema_enum == EXPECTED_ERROR_CODES:
        passed += 1
    else:
        failed += 1
        failures.append(
            "error.schema.json code enum does not exactly match the nine "
            f"expected codes. schema={sorted(schema_enum)} "
            f"expected={sorted(EXPECTED_ERROR_CODES)}"
        )

    fixture_codes = set()
    for filename, validator, expect_valid in FIXTURE_CASES:
        if validator is ERROR_VALIDATOR and expect_valid:
            fixture_codes.add(load(FIXTURES_DIR / filename)["error"]["code"])

    if fixture_codes == EXPECTED_ERROR_CODES:
        passed += 1
    else:
        failed += 1
        failures.append(
            "valid-error-*.json fixtures do not cover exactly the nine "
            f"expected codes. covered={sorted(fixture_codes)} "
            f"expected={sorted(EXPECTED_ERROR_CODES)}"
        )

    return passed, failed, failures


def check_privacy_fixture_fails_only_on_forbidden_field() -> tuple[int, int, list[str]]:
    """Prove the two privacy-boundary fixtures are rejected specifically for
    carrying a forbidden field, not merely for missing unrelated required
    fields -- i.e. additionalProperties:false is doing the enforcing."""
    passed = 0
    failed = 0
    failures: list[str] = []

    for filename, forbidden_field in [
        ("invalid-forbidden-personal-data.json", "quantity"),
        ("invalid-forbidden-personal-data-riskprofile.json", "riskProfile"),
    ]:
        instance = load(FIXTURES_DIR / filename)
        errors = list(REQUEST_VALIDATOR.iter_errors(instance))
        if not errors:
            failed += 1
            failures.append(f"{filename}: expected schema rejection, got none")
            continue

        mentions_forbidden_field = any(
            forbidden_field in str(e.message)
            or (e.validator == "additionalProperties")
            for e in errors
        )
        if mentions_forbidden_field:
            passed += 1
        else:
            failed += 1
            failures.append(
                f"{filename}: rejected, but not clearly via additionalProperties "
                f"on '{forbidden_field}': {[e.message for e in errors]}"
            )

    return passed, failed, failures


def main() -> int:
    total_passed = 0
    total_failed = 0
    all_failures: list[str] = []

    for runner in (
        run_fixture_cases,
        run_boundary_cases,
        check_error_enum_matches_fixtures,
        check_privacy_fixture_fails_only_on_forbidden_field,
    ):
        passed, failed, failures = runner()
        total_passed += passed
        total_failed += failed
        all_failures.extend(failures)

    print(f"portfolio-research.v1 contract tests: {total_passed} passed, {total_failed} failed")
    if all_failures:
        print("\nFailures:")
        for f in all_failures:
            print(f"  - {f}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
