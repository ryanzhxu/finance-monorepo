# portfolio-research.v1 contract

Canonical JSON Schema and fixtures for the `portfolio-research.v1` contract
described in section 6 of `FINANCE_SYSTEM_ARCHITECTURE.md`.

- Producer: Research specialist (this repo).
- Consumer: Position Lens.
- Target endpoint: `POST /api/portfolio-research` (not implemented by this
  slice; schema and fixtures only).

Position Lens does not get a vote on the schema shape. This directory is the
pinned source of truth; the sha256 checksum below is what downstream
consumers pin against.

## Layout

```
contracts/portfolio-research/
  schema/
    request.schema.json    # request envelope (POST body)
    response.schema.json   # success response envelope
    error.schema.json      # error response envelope
  fixtures/
    valid-request.json
    valid-response-complete.json
    valid-response-partial.json
    valid-response-partial-degraded.json
    valid-response-unavailable.json
    valid-response-provider-disabled.json
    valid-error-*.json                       # one per error code (9 files)
    valid-error-requestid-unavailable.json   # requestId: null, body unparseable before it could be recovered
    invalid-missing-required-field.json
    invalid-wrong-type.json
    invalid-forbidden-personal-data.json            # verbatim doc example (quantity)
    invalid-forbidden-personal-data-riskprofile.json # verbatim doc example (riskProfile)
    invalid-unsupported-version.json                # verbatim doc example (v2)
    invalid-response-forbidden-recommendation.json  # response research[] item carrying a BUY/HOLD/SELL-style field
    invalid-response-missing-field.json             # response missing a required top-level field (status)
    invalid-error-forbidden-field.json              # error envelope carrying a forbidden top-level field
  tests/
    test_contract.py       # validates every fixture; also exercises
                            # symbol/reasonCode/reviewItemId boundary cases
                            # inline (not as separate fixture files)
```

Split into three files (request/response/error) rather than one `schema.json`
because the three envelopes are independently useful (a producer only needs
to validate what it emits; a consumer only needs to validate what it
receives) and none of them `$ref` into each other.

## Why not one schema.json

Each envelope is self-contained -- request, response, and error schemas do
not reference each other's definitions -- so splitting avoids a single file
mixing three independent validation concerns. If a future version needs
shared `$defs` (e.g. a common source-object shape), consider consolidating
then.

## Running the tests

The repo does not currently depend on a JSON Schema validator (`jsonschema`
is not in `pyproject.toml`/`uv.lock`, and neither is an equivalent Node
package). Rather than add a new pinned dependency for a schema/fixtures-only
slice, the test pulls `jsonschema` in as an ephemeral `uv` dependency that
does not touch `pyproject.toml` or `uv.lock`:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-project --with jsonschema \
  python contracts/portfolio-research/tests/test_contract.py
```

Exit code is `0` on success, `1` if any fixture (or inline boundary case)
does not match its expected valid/invalid outcome.

## Checksum (what Position Lens pins against)

Computed as the sha256 of the byte-concatenation of the three schema files,
in this exact order: `request.schema.json`, `response.schema.json`,
`error.schema.json`. Reproduce with:

```bash
cat schema/request.schema.json schema/response.schema.json schema/error.schema.json | shasum -a 256
```

```
e3da6a0278740d85b8530da763b695199f5e9e23b7dd6e36de05bbcde2013bed
```

Individual file checksums (for pinning a single envelope independently):

```
9faed86e77b498e1ee7c68078a997c44c6a580902a716163ea66dc1269177083  request.schema.json
5f07c0df9dd60a3c2876c3ea871aa923bd9c257167374f981d3a920bd965d3a1  response.schema.json
9fd0012f4d8be995790d14922547f2f29541f2664ceb55e273fd11483ace8dfd  error.schema.json
```

`error.schema.json` changed (`requestId` now accepts `null`, see "Judgment calls" below) after this checksum was first published; `request.schema.json` and `response.schema.json` are unchanged.

## Enforced boundaries

- `symbols`: 1-3 unique normalized listed-equity symbols.
- `reasonCodes`: 1-5 unique values from the closed enum `CONCENTRATION`,
  `DRAWDOWN`, `THESIS_REVIEW`, `CATALYST_REVIEW`, `DATA_STALE`.
- `reviewItemIds`: optional, maximum 5 opaque strings.
- Every top-level object (`additionalProperties: false` on request,
  response, and error, and on the nested `research[]`, `sources[]`,
  `freshness`, and `error` objects) rejects unknown fields. This is what
  enforces the privacy boundary at the schema level, not just by convention
  -- see `fixtures/invalid-forbidden-personal-data*.json`.
- `contractVersion` is a `const` exact-match on `"portfolio-research.v1"` in
  all three envelopes; any other value (including `portfolio-research.v2`)
  is rejected outright, never best-effort parsed as v1 -- see
  `fixtures/invalid-unsupported-version.json`.
- Maximum request body size is **16 KiB**. JSON Schema cannot enforce byte
  size directly; this is documented in `request.schema.json`'s top-level
  `description` and must be enforced by the transport/endpoint layer
  independently of this schema (out of scope for this slice, which is
  schema-and-fixtures only).

## Judgment calls made in this slice

FINANCE_SYSTEM_ARCHITECTURE.md section 6 does not fully specify the
following; each was resolved conservatively and is called out here so a
reviewer can override:

- **Symbol format**: the doc gives no regex for "normalized listed-equity
  symbol." Used `^[A-Z]{1,10}([.-][A-Z]{1,4})?$` to allow plain tickers and
  common share-class suffixes (e.g. `BRK.B`). Applied to both request
  `symbols[]` and response `research[].symbol`.
- **Timestamp strictness**: the doc's examples are all UTC `Z`-suffixed. Used
  a regex pattern requiring the `Z` suffix (not just `format: date-time`,
  which `jsonschema` does not enforce without an explicit format checker) for
  `requestedAt`, `generatedAt`, and all source/freshness timestamps.
- **`sources[].sourceType`**: the doc shows only the example value
  `"primary"` and does not give a closed enum. Left as a non-empty string
  rather than inventing a closed set (e.g. adding `"secondary"` as an enum
  member would be a guess).
- **Response `research[]` cardinality**: no explicit max is stated. Left
  unbounded in the schema rather than inferring a cap from the request's
  1-3 symbol limit, since the doc does not state that inference explicitly.
- **`providerStatus: "disabled"` combined with `status: "unavailable"`**:
  the doc doesn't give a worked example of this combination in the response
  envelope (as opposed to the `RESEARCH_DISABLED` *error* envelope, which is
  for the endpoint being fully gated off). Included
  `fixtures/valid-response-provider-disabled.json` as a plausible case for a
  provider-level (not endpoint-level) disablement that still returns a
  bounded response, per the "Stale and degraded behavior" section's note
  that disabled/unavailable states still render a bounded availability
  message. Flagging in case the intended design is that any `disabled`
  provider state always surfaces as the `RESEARCH_DISABLED` error instead.
- **Error envelope retryable values**: the doc doesn't specify which codes
  are retryable. Set `retryable: true` for `PROVIDER_UNAVAILABLE`,
  `RATE_LIMITED`, and `INTERNAL_ERROR`; `false` for the rest. This is a
  fixture-content choice, not a schema constraint (the schema only requires
  `retryable` to be a boolean).
- **`reviewItemIds` uniqueness**: the doc states only a maximum of 5; it does
  not say items must be unique. Did not add `uniqueItems` to avoid inventing
  a constraint not stated in the doc. Note this is not quite symmetric with
  `reasonCodes` below: only `symbols` is explicitly called "unique" in the
  doc's field table; `reasonCodes`' `uniqueItems: true` is this slice's own
  reasonable-by-analogy inference, not a literal doc requirement either.
- **Error envelope `requestId` can be `null`**: the doc's request envelope
  requires `requestId`, but a producer that fails before it can parse the
  request body (e.g. malformed JSON) has nothing to echo. The field's own
  description already said "when one was available to echo," which was in
  tension with the schema requiring a non-empty string. Resolved by allowing
  `requestId: null` specifically for that case -- see
  `fixtures/valid-error-requestid-unavailable.json` -- rather than requiring
  a placeholder string or silently omitting the field.
- **Source-provenance requirement is not schema-enforceable**: like the 16
  KiB body-size limit above, the doc's rule that "every material research
  claim must point to source entries... uncited claims become unknowns, not
  conclusions" is a semantic judgment JSON Schema cannot check (it can't tell
  a sourced claim from an unsourced one within free-text `thesis`/`summary`
  fields). Out of scope for this slice; would need a producer-side review
  step, not a schema constraint.
