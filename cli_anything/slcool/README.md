# SL Cool CLI

A CLI-Anything Python harness for the **SL Cool public gateway and stock app**.
Default gateway: `https://open.sl.cool`. Python **3.10+** is required.

Commands: `sl-cool` (short alias) and `cli-anything-slcool` (canonical name).
Both run the same client. No private service tokens or SLConsole backend are needed.

## Install

### Install from GitHub Releases

Repository: https://github.com/SCI-SL/app-exchange-cli

The repository is currently private. Organization members can install through
their existing GitHub SSH access:

```bash
pipx install "git+ssh://git@github.com/SCI-SL/app-exchange-cli.git@v1.0.0"
```

The anonymous download commands below require a public repository and a published
GitHub Release. They become available if the owner later makes this repository public.

macOS or Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/SCI-SL/app-exchange-cli/main/install.sh \
  | sh -s -- SCI-SL/app-exchange-cli
```

Windows PowerShell:

```powershell
$env:SLCOOL_CLI_REPOSITORY = 'SCI-SL/app-exchange-cli'
irm https://raw.githubusercontent.com/SCI-SL/app-exchange-cli/main/install.ps1 | iex
```

The installers download the latest universal wheel from GitHub Releases and
install it with `pipx`. Python 3.10+ and `pipx` are prerequisites. Install
`pipx` with `brew install pipx` on macOS, your package manager on Linux, or
`py -m pip install --user pipx` on Windows (then run `py -m pipx ensurepath` and
reopen PowerShell).

### Install a downloaded wheel

Install a specific release wheel into an isolated application environment:

```bash
pipx install ./cli_anything_slcool-1.0.0-py3-none-any.whl
sl-cool --help
```

Alternatively, use a virtual environment (macOS/Linux):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install ./cli_anything_slcool-1.0.0-py3-none-any.whl
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .\cli_anything_slcool-1.0.0-py3-none-any.whl
```

To install from this source directory: `python -m pip install .`.
The wheel works on macOS, Linux and Windows **with Python installed**; it is not a
standalone executable. Dependency packages are downloaded by pip during installation.
No package has been published to PyPI by this project.

### Publish a GitHub Release

Push a version tag matching `setup.py`, such as `v1.0.0`. The included GitHub
Actions workflow runs the standalone CLI tests, builds the wheel and source
archive, validates the installed wheel, generates `SHA256SUMS`, and attaches all
three files to a GitHub Release. The separate real-backend integration tests
require an authorized checkout of `sl.cool-stock`; they are run locally with
`SLCOOL_STOCK_SOURCE` and are not part of this standalone repository's CI. The installer scripts discover
the latest release through the GitHub API; no owner or repository name is
embedded in the package. The one-line install commands above need that name
because GitHub must know where to fetch the installer script.

## Authentication

Create an Agent key in your platform account. Set `SL_COOL_API_KEY` in your local
shell; the client never saves it or accepts a credential command-line option.

macOS zsh (hidden input; paste the key, then press Enter):

```zsh
read -s 'SL_COOL_API_KEY?Agent API key: '
export SL_COOL_API_KEY
echo
```

Linux bash:

```bash
read -rsp 'Agent API key: ' SL_COOL_API_KEY
export SL_COOL_API_KEY
echo
```

PowerShell 7:

```powershell
$env:SL_COOL_API_KEY = Read-Host 'Agent API key' -MaskInput
```

Use an `sl_` Agent key. Guest `slg_` keys belong to a different API and are not
supported by this contract. Public catalog and skill commands need no key.

```bash
sl-cool config --json
sl-cool apps list --page 1 --page-size 20 --json
sl-cool agent apps --json
sl-cool agent skill --slug stock-app --json
```

## Stock app

```bash
sl-cool stock quotes --json
sl-cool stock portfolio --json
sl-cool orders sessions --json
sl-cool orders list --status pending --limit 20 --json
sl-cool stock leaderboard --type daily --limit 10 --json
sl-cool stock rank --type daily --user-did 'did:example:your-did' --json
```

Prepare an order without sending it:

```bash
sl-cool orders place --symbol AAPL --action buy --cash-percent 10 \
  --execution next_open --dry-run --json
```

Remove `--dry-run` to place the virtual order. Buy requires exactly one of
`--cash-amount` / `--cash-percent`; sell requires exactly one of `--quantity` /
`--position-percent`. All numbers must be positive, percentages <=100.
Orders execute at a future open/close, lock before execution and are **not
automatically retried**. Immediate trading is retired.

```bash
sl-cool orders cancel --order-id 'ORDER_ID_FROM_RESPONSE' --json
```

## Predictions

```bash
sl-cool predictions current --game-key stock_direction --json
sl-cool predictions current --game-key stock_range --json
```

Get the current `round_id`, allowed prediction values and **full symbol list** from
the current-round response. Fill the examples with that exact set; example symbols
are illustrative and may be stale. Do not reuse an old round or request ID for a
different prediction.

```bash
sl-cool predictions submit --body @examples/direction-prediction.json --dry-run --json
sl-cool predictions submit --body @examples/direction-prediction.json --json
sl-cool predictions leaderboard --game-key stock_direction --type daily --limit 20 --json
sl-cool predictions rank --game-key stock_direction --type daily --json
```

The sample contains five example symbols to satisfy the contract's minimum count;
the server may require more. `request_id` identifies one logical submission; an
intentional retry must send the **same body and ID**. The CLI does not auto-retry.

Legacy prediction and portfolio boards support `daily`, `weekly`, `monthly`, `all`.
They are separate from the public-game daily/proof boards (`/api/game/*`), which
are **not included in the supplied OpenAPI contract or this CLI**. Ticket use and
automatic evidence publication are also outside this package.

## All 29 operations

Every operation has a named command. Inspect the packaged contract without networking:

```bash
sl-cool api list --json
sl-cool api describe gatewayPlaceOrder --json
sl-cool api call gatewayGetPredictionRound --query game_key=stock_direction --json
```

| Group | Commands |
| --- | --- |
| `platform` | `manifest`, `stock-skill`, `agent-skill` |
| `apps` | `list`, `get`, `rankings` |
| `agent` | `apps`, `app`, `skill`, `available`, `actions` |
| `stock` | `quotes`, `portfolio`, `leaderboard`, `rank`, `retired-trade` (rejects locally) |
| `orders` | `sessions`, `list`, `place`, `cancel` |
| `predictions` | `current`, `submit`, `leaderboard`, `rank` |
| `proxy` | `get`, `post`, `put`, `patch`, `delete` |

Generic proxy commands support other published apps, with identity provided by the gateway:

```bash
sl-cool proxy get --app-slug stock-app --proxy-path api/v1/stock/list --json
sl-cool proxy post --app-slug YOUR_APP --proxy-path api/v1/action --body @request.json --dry-run --json
```

Use `--query NAME=VALUE` repeatedly for generic proxy queries; `api call` accepts
`--param NAME=VALUE` for path parameters. Request bodies accept inline JSON,
`@file.json` or `@-` for stdin. Internal stock-service routes are not public commands.
Never submit internal tokens or forged identity fields in proxy bodies.

## Output, errors and REPL

- `--json` before or after a command produces one JSON value on stdout; Markdown
  becomes a JSON string. Success preserves the response structure. Diagnostics
  redact key/token fields and the current Agent key.
- Errors exit nonzero; JSON errors use `{"error":{"type":"...","message":"..."}}`.
  HTTP errors also include `status` and a sanitized server `body`.
- `--dry-run` validates and prints method, URL and body. No key is required and no
  request is sent. API requests use a 20-second timeout; redirects and retries are disabled.
- `--base-url` (or `SL_COOL_BASE_URL`) overrides the gateway. Remote origins must
  use HTTPS; loopback HTTP is supported for tests. No TLS verification bypass exists.
- `sl-cool` starts an interactive REPL in a terminal. Type `help` / `exit`; command
  history stays in memory. There is no local account/session database or undo/redo
  for remote transactions. Non-interactive callers should always use subcommands.
- Global options `--base-url`, `--timeout` belong before the command. `--json`
  works at either position; `--dry-run` also works at the final request command.

## Developer build and verification

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
CLI_ANYTHING_FORCE_INSTALLED=1 python -m pytest cli_anything/slcool/tests/test_core.py -v --tb=no
python -m build
```

To run all tests including the real backend, set `SLCOOL_STOCK_SOURCE` to an
authorized `sl.cool-stock` source checkout and run `python -m pytest -v`. Tests use temporary data, synthetic credentials
and a local relay; they do not use production accounts. See
`cli_anything/slcool/tests/TEST.md` for measured results and coverage boundaries.

`dist/` contains the wheel and source distribution after building. For website
downloads, upload the wheel/source archive and README to the existing website's
static download directory and link to those files. The CLI still calls
`https://open.sl.cool`; the documentation site's address is not the API origin.

CLI-Anything skill: canonical `skills/cli-anything-slcool/SKILL.md`; the wheel
also includes `cli_anything/slcool/skills/SKILL.md`. The OpenAPI snapshot is bundled
and does not require downloading a specification at runtime.
