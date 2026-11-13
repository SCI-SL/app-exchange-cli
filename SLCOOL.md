# SL Cool CLI harness architecture

Source contract: bundled `cli_anything/slcool/data/openapi.json` (61 operations).
Source implementations: `../routes/api.php`, `../app/Http/Controllers/Api/SkillAppController.php`,
`../app/Services/AppProxyClient.php`, and `../../sl.cool-stock/app.py`.

The real backend is the SL Cool HTTP gateway, not a local simulation. The harness
serializes documented requests and preserves server JSON responses. It never
calculates scores, executes orders locally, signs transactions, or reads server
credentials. Public game `/api/game/*` APIs are included; App ticket use remains
App-side.

- Package: `cli-anything-slcool`; entry points: `cli-anything-slcool`, `sl-cool`.
- Runtime: Python >=3.10, Click, jsonschema, prompt-toolkit.
- `core/contract.py`: packaged OpenAPI snapshot, operation inventory, request validation.
- `utils/slcool_backend.py`: HTTP transport, environment-only credentials, errors.
- `slcool_cli.py`: named commands, operation-ID dispatch, JSON output and REPL.
- Default endpoint: `https://open.sl.cool`; credentials: `SL_COOL_API_KEY` and
  optional preferred game key `SL_COOL_GAME_KEY`.
- Stateless requests; no local account/game database, credential store or persistent
  session mutations. Undo/redo would misrepresent server transactions and is omitted.
- `--dry-run` validates and displays requests without credentials or network access.
- No redirects or automatic retries, especially for non-idempotent stock orders.
- No image/render preview: the native output is JSON or Markdown from the backend.
- Default REPL retains endpoint/output options in memory and disables disk history.
- Every contract operation has a named command and is callable by operation ID.

Tests distinguish transport fixtures (not a real gateway) from the real Python
stock backend with isolated files and a local test relay. Real authenticated
production requests require a user-provided Agent key and are not implied by
offline tests. Packaging is verified from an installed wheel outside the source tree.
