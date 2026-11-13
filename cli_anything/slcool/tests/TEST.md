# Test plan (written before test implementation)

## Inventory

- `test_core.py`: parameterized unit/CLI tests for all 61 operation mappings,
  local schema validation, path encoding, orders, prediction files, credentials,
  dry-run, JSON diagnostics, parameter errors, base URL validation and REPL.
- `test_full_e2e.py`: installed-command integration scenarios with a local
  HTTP contract fixture, plus a real Python stock-service workflow using isolated
  data files and a local relay. Every test must fail on missing dependencies.
- `test_guest.py`: guest-key selection, enrollment/recovery credential reveal,
  secret-safe failures, local input validation, and installed nested command tests.

## Workflows and verification

1. Discover contract -> inspect operation -> dry-run request. Verify complete operation
   coverage, encoded paths/query parameters and zero HTTP writes during dry-run.
2. Load predictions from a real JSON file -> installed CLI -> HTTP fixture -> JSON
   output file. Verify request content, bearer auth, request ID and response contents.
3. Order validation -> place -> cancel through HTTP fixture. Verify no retry of
   POST after HTTP/connection errors. This fixture does not simulate trading rules.
4. Redirect/error responses -> verify nonzero exit, JSON stdout, no traceback or
   credential disclosure, and no redirected request.
5. Launch real `sl.cool-stock/app.py` HTTP handler with temporary databases; relay
   authenticated CLI requests to it with a synthetic gateway identity. Read quotes
   and portfolio, verify actual response fields and the persisted user database.
   The relay is a test adapter, not the production PHP gateway. External market
   requests are disabled for isolation; no production account/order is changed.
6. Install the built wheel into a clean environment; invoke commands from outside
   the source tree, verify bundled OpenAPI/skill files and namespace packaging.

## Boundaries

No rendering or GUI format exists for this HTTP client. Native artifacts are JSON
responses, Markdown skill documents, prediction input files and backend JSON data.
Authenticated production behavior, market pricing, settlement, ticket use and proof
publication require real deployed services and credentials; offline tests cannot
establish their availability. Public live read checks, if performed, are reported
separately from fixture/backend tests.

## Results

2026-11-13 (1.1.0, Python 3.12.12, macOS arm64):

```text
PATH="/tmp/slcool-wheel-110/bin:$PATH" CLI_ANYTHING_FORCE_INSTALLED=1 \
  /tmp/slcool-wheel-110/bin/python -m pytest -v --tb=short
34 passed in 5.92s
```

The run installed the built 1.1.0 wheel into a clean virtual environment, forced
installed-command mode, and used subprocesses from outside the source working
directory. It verified all 61 OpenAPI operations, guest and Agent key selection,
enrollment-file permissions/non-overwrite, explicit one-time key reveal, OTP and
secret redaction, no-retry behavior, proof submission before settlement, validation,
and nested commands. It also exercised the actual Python stock service with
isolated databases for quotes, portfolio, leaderboard, and a persisted pending
game record. The gateway identity adapter was local; PHP enrollment, email and
proof database behavior were not executed.

Additional release checks:

```text
ruff check cli_anything/slcool: All checks passed.
python -m build: wheel and sdist built successfully.
Fresh virtualenv install from cli_anything_slcool-1.1.0-py3-none-any.whl: passed.
Installed cli-anything-slcool api list --json: 61 operations.
```

This does not verify production Agent credentials, public DNS/gateway availability,
live market conditions, settlement, orders on a real account, or ticket/evidence
publication. The local HTTP relay applies the identity injection that the deployed
PHP gateway performs; it is a test adapter, not a substitute implementation of
that gateway.

## Standalone GitHub repository CI

The release workflow runs `test_core.py` and validates the built wheel from a
temporary working directory. The three real-stock integration tests remain
unchanged and require a separate authorized backend checkout supplied through
`SLCOOL_STOCK_SOURCE`. Missing backend source is an error when running the full
suite; CI does not present its standalone checks as full backend verification.

## 1.1.0 refinement plan (before implementation)

- Preserve all 29 Agent operations and add 32 `/api/game/*` operations, including
  the retired total-board entry with a local migration error (61 total).
- Standalone guest contract workflows: enrollment request file permissions and
  no overwrite; anonymous requests never send credentials; guest/Agent credential
  selection; guest-only rotation/claim; opt-in issued-key output; secret-safe errors
  and dry runs; OTP/UUID/date/proof exclusivity validation; pre-score proof URLs;
  nested command help, installed subprocess discovery, and no automatic POST retry.
- Real backend workflow: installed CLI creates a public stock record, lists it and
  fetches its pending detail using the actual Python stock server and isolated
  JSON storage through a local identity adapter. This does not test PHP guest
  enrollment, email delivery or proof persistence; those use contract fixtures.
- Validate all generated documentation links/anchors, operation coverage and
  example request bodies against the bundled contract. Build and install the wheel
  outside the checkout, run full tests locally, and run standalone tests in CI.
