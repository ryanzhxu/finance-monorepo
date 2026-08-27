"""Enforce the decision.v1 invariants that JSON Schema cannot express.

Run:

    UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-project \\
        python contracts/decision/tests/test_invariants.py

No third-party dependency: this layer is pure arithmetic on a parsed payload.

Why this file exists separately from test_contract.py
-----------------------------------------------------
Draft 2020-12 cannot compare two numeric fields to each other, so every rule
below is invisible to the schema. `invalid-overlapping-ranges.json` is the
proof: it passes schema validation cleanly and is rejected only here. Keeping
the layers in separate files makes it obvious which one rejects what, and lets
either run alone.

`check_invariants` is the committed home for these rules. Do not re-derive them
inline in a script; four earlier cycles did that and threw the result away each
time, which meant the guarantee never actually existed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "fixtures"

# Rule identifiers. Tests assert on these, never on message text, so wording can
# be improved without breaking assertions.
RANGE_ORDER = "range_order"
ZONE_SEPARATION = "zone_separation"
INVALID_LANDSCAPE_NULL_RANGES = "invalid_landscape_null_ranges"
OPPORTUNITY_PRICE_INSIDE = "opportunity_price_inside"
REDUCE_PRICE_INSIDE = "reduce_price_inside"
NEUTRAL_PRICE_BETWEEN = "neutral_price_between"

NEUTRAL_STATES = ("NEUTRAL_ZONE", "NEAR_OPPORTUNITY_ZONE", "NEAR_REDUCE_ZONE")


class Violation(NamedTuple):
    rule: str
    horizon: str
    detail: str


def check_invariants(payload: dict) -> list[Violation]:
    """Return every invariant violation in a decision.v1 payload.

    Assumes the payload already passed schema validation; this layer checks
    only the relationships between fields, not their presence or type.
    """
    violations: list[Violation] = []
    price = payload.get("currentPrice")

    for horizon, decision in payload.get("horizons", {}).items():
        state = decision.get("priceState")
        opportunity = decision.get("opportunityRange")
        reduce_ = decision.get("reduceRange")

        # 1. A band's low must be below its high.
        for name, band in (("opportunityRange", opportunity), ("reduceRange", reduce_)):
            if band and not band["low"] < band["high"]:
                violations.append(Violation(
                    RANGE_ORDER, horizon,
                    f"{name}.low {band['low']} is not below .high {band['high']}",
                ))

        # 2. The two bands must not touch or overlap. Overlapping bands make the
        #    price-state action legality table ambiguous: one price would sit in
        #    two mutually exclusive states at once.
        if opportunity and reduce_ and not opportunity["high"] < reduce_["low"]:
            violations.append(Violation(
                ZONE_SEPARATION, horizon,
                f"opportunityRange.high {opportunity['high']} is not below "
                f"reduceRange.low {reduce_['low']}",
            ))

        # 3. No landscape means no bands. A producer must not claim it could not
        #    form a landscape while still emitting fake-precision numbers.
        if state == "INVALID_LANDSCAPE" and (opportunity or reduce_):
            violations.append(Violation(
                INVALID_LANDSCAPE_NULL_RANGES, horizon,
                "INVALID_LANDSCAPE requires opportunityRange and reduceRange to be null",
            ))

        # Rules 4-6 position currentPrice. Skip when the producer had no quote.
        if price is None:
            continue

        # 4. Claiming to be in the opportunity band means being in it.
        if state == "IN_OPPORTUNITY_ZONE":
            if not (opportunity and opportunity["low"] <= price <= opportunity["high"]):
                violations.append(Violation(
                    OPPORTUNITY_PRICE_INSIDE, horizon,
                    f"currentPrice {price} is not inside opportunityRange {opportunity}",
                ))

        # 5. Same for the reduce band.
        if state == "IN_REDUCE_ZONE":
            if not (reduce_ and reduce_["low"] <= price <= reduce_["high"]):
                violations.append(Violation(
                    REDUCE_PRICE_INSIDE, horizon,
                    f"currentPrice {price} is not inside reduceRange {reduce_}",
                ))

        # 6. The neutral band and both near-states sit strictly between the two
        #    bands. How near counts as "near" is producer-defined and
        #    ATR-normalized, so only the containment is checkable here.
        if state in NEUTRAL_STATES:
            if not (opportunity and reduce_
                    and opportunity["high"] < price < reduce_["low"]):
                violations.append(Violation(
                    NEUTRAL_PRICE_BETWEEN, horizon,
                    f"currentPrice {price} is not strictly between "
                    f"opportunityRange.high and reduceRange.low for state {state}",
                ))

    return violations


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def run_valid_fixtures_are_clean() -> tuple[int, int, list[str]]:
    """Every valid-*.json fixture satisfies every invariant."""
    passed = failed = 0
    failures: list[str] = []

    fixtures = sorted(FIXTURES_DIR.glob("valid-*.json"))
    if not fixtures:
        return 0, 1, ["no valid-*.json fixtures found"]

    for path in fixtures:
        violations = check_invariants(load(path))
        if violations:
            failed += 1
            failures.append(
                f"{path.name}: expected no violations, got "
                f"{[(v.rule, v.horizon) for v in violations]}"
            )
        else:
            passed += 1

    return passed, failed, failures


def run_overlapping_ranges_is_rejected() -> tuple[int, int, list[str]]:
    """The fixture that proves this layer does work the schema cannot.

    It is schema-valid. If this layer stops rejecting it, the contract silently
    permits overlapping zones and the legality table becomes ambiguous.
    """
    name = "invalid-overlapping-ranges.json"
    path = FIXTURES_DIR / name
    if not path.exists():
        return 0, 1, [f"{name}: fixture file is missing"]

    violations = check_invariants(load(path))
    rules = [v.rule for v in violations]

    if rules == [ZONE_SEPARATION]:
        return 1, 0, []
    return 0, 1, [
        f"{name}: expected exactly [{ZONE_SEPARATION}], got {rules}"
    ]


def run_each_rule_fires() -> tuple[int, int, list[str]]:
    """Every rule must be reachable.

    A rule that no input can trigger is dead code that looks like a guarantee.
    Each case below is a minimal payload built to violate exactly one rule.
    """
    def payload(price, horizon_decision):
        return {"currentPrice": price, "horizons": {"short": horizon_decision}}

    band = lambda lo, hi: {"low": lo, "high": hi}

    cases = [
        (RANGE_ORDER, payload(100.0, {
            "priceState": "NEUTRAL_ZONE",
            "opportunityRange": band(90.0, 80.0), "reduceRange": band(120.0, 130.0)})),
        # BREAKDOWN_ZONE has no price-position rule, which is what lets this
        # case isolate zone separation. Under any neutral or in-zone state,
        # overlapping bands necessarily trip a position rule too, because no
        # price can sit strictly between bands that overlap.
        (ZONE_SEPARATION, payload(100.0, {
            "priceState": "BREAKDOWN_ZONE",
            "opportunityRange": band(90.0, 125.0), "reduceRange": band(120.0, 130.0)})),
        (INVALID_LANDSCAPE_NULL_RANGES, payload(100.0, {
            "priceState": "INVALID_LANDSCAPE",
            "opportunityRange": band(90.0, 95.0), "reduceRange": None})),
        (OPPORTUNITY_PRICE_INSIDE, payload(100.0, {
            "priceState": "IN_OPPORTUNITY_ZONE",
            "opportunityRange": band(80.0, 90.0), "reduceRange": band(120.0, 130.0)})),
        (REDUCE_PRICE_INSIDE, payload(100.0, {
            "priceState": "IN_REDUCE_ZONE",
            "opportunityRange": band(80.0, 90.0), "reduceRange": band(120.0, 130.0)})),
        (NEUTRAL_PRICE_BETWEEN, payload(150.0, {
            "priceState": "NEUTRAL_ZONE",
            "opportunityRange": band(80.0, 90.0), "reduceRange": band(120.0, 130.0)})),
    ]

    passed = failed = 0
    failures: list[str] = []
    for expected_rule, doc in cases:
        rules = [v.rule for v in check_invariants(doc)]
        if rules == [expected_rule]:
            passed += 1
        else:
            failed += 1
            failures.append(f"{expected_rule}: expected exactly that rule, got {rules}")

    return passed, failed, failures


def run_null_price_skips_position_rules() -> tuple[int, int, list[str]]:
    """A producer with no quote is not punished by the price-position rules.

    The structural rules 1-3 still apply; only 4-6 are skipped.
    """
    doc = {"currentPrice": None, "horizons": {"short": {
        "priceState": "IN_OPPORTUNITY_ZONE",
        "opportunityRange": {"low": 80.0, "high": 90.0},
        "reduceRange": {"low": 120.0, "high": 130.0}}}}
    rules = [v.rule for v in check_invariants(doc)]
    if rules:
        return 0, 1, [f"null currentPrice should skip position rules, got {rules}"]

    structural = {"currentPrice": None, "horizons": {"short": {
        "priceState": "IN_OPPORTUNITY_ZONE",
        "opportunityRange": {"low": 90.0, "high": 80.0},
        "reduceRange": {"low": 120.0, "high": 130.0}}}}
    if [v.rule for v in check_invariants(structural)] != [RANGE_ORDER]:
        return 0, 1, ["null currentPrice should still enforce structural rules"]

    return 2, 0, []


def main() -> int:
    total_passed = 0
    total_failed = 0
    all_failures: list[str] = []

    for runner in (
        run_valid_fixtures_are_clean,
        run_overlapping_ranges_is_rejected,
        run_each_rule_fires,
        run_null_price_skips_position_rules,
    ):
        passed, failed, failures = runner()
        total_passed += passed
        total_failed += failed
        all_failures.extend(failures)

    print(f"decision.v1 invariant tests: {total_passed} passed, {total_failed} failed")
    if all_failures:
        print("\nFailures:")
        for f in all_failures:
            print(f"  - {f}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
