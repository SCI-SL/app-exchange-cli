# Test plan (written before test implementation)

## Inventory

- `test_core.py`: about 30 parameterized unit/CLI tests for all 29 operation mappings,
  local schema validation, path encoding, orders, prediction files, credentials,
  dry-run, JSON diagnostics, parameter errors, base URL validation and REPL.
- `test_full_e2e.py`: about 10 installed-command integration scenarios with a local
  HTTP contract fixture, plus a real Python stock-service workflow using isolated
  data files and a local relay. Every test must fail on missing dependencies.

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

2026-11-11 (local build runtime: Python 3.12.12, macOS arm64):

```text
PATH="/tmp/slcool-cli-wheel-check/bin:$PATH" CLI_ANYTHING_FORCE_INSTALLED=1 \
  /tmp/slcool-cli-wheel-check/bin/python -m pytest -v --tb=short
18 passed in 1.38s
```

The run used the cleanly installed, built wheel command, forced-installed mode,
and ran outside the source working directory for command subprocesses. It verified
all 29 OpenAPI operations, named CLI inputs, query/path validation, prohibited
internal routes, JSON and dry-run modes, credentials and secret redaction, redirect
and error handling, plus real local stock quotes/portfolio/leaderboard handlers
through an authenticated test relay and isolated temporary data files.

Additional release checks:

```text
ruff check cli_anything/slcool: All checks passed.
python -m build: wheel and sdist built successfully.
Fresh virtualenv install from dist/cli_anything_slcool-1.0.0-py3-none-any.whl: passed.
Installed cli-anything-slcool api list --json: 29 operations.
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
