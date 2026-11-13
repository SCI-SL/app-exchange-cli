---
name: cli-anything-slcool
description: Call the public SL Cool APIs from a terminal. Use for guest enrollment, game records, proof URLs, predictions, daily leaderboards, orders, app discovery and proxies.
---

# SL Cool CLI

## Setup

Install the `cli-anything-slcool` wheel or use the `sl-cool` alias. Requires
Python 3.10+. Default API origin is `https://open.sl.cool`.

Set an SL Cool Agent key in `SL_COOL_API_KEY`. The client reads it only from the
environment and never saves or prints it. On macOS/Linux, enter it without
echoing it:

```bash
read -rsp 'Agent API key: ' SL_COOL_API_KEY
export SL_COOL_API_KEY
echo
```

Public catalog/skill documents and guest enrollment/recovery-code requests need no key. Agent routes require `sl_`; game routes accept `sl_` or `slg_` where allowed, and guest-only operations require `slg_`. `SL_COOL_GAME_KEY` takes precedence for game commands. Never substitute app secrets or service tokens.

## Safe request workflow

1. Inspect `sl-cool api list --json` or `sl-cool api describe OPERATION_ID --json`.
2. For writes, prepare with `--dry-run --json` and inspect the request.
3. Send once. No request is automatically retried and redirects are not followed.
4. Parse JSON stdout; check nonzero status and the `error` object on failure.

`--json` works before or after a command. `--base-url` changes the gateway;
remote origins require HTTPS. Never put a key in command history or arguments.

## Commands

```text
platform manifest|stock-skill|agent-skill
apps list|get|rankings
agent apps|app|skill|available|actions
proxy get|post|put|patch|delete
stock quotes|portfolio|leaderboard|rank|retired-trade
orders sessions|list|place|cancel
predictions current|submit|leaderboard|rank
game enroll|recovery|me|credentials|claim|list|rounds|predictions|scores|records|stock|orders|leaderboard|proofs|storm
api list|describe|call|url
config
```

Every operation in the supplied public OpenAPI contract has a command and can be
called by operation ID. The wheel's `README.md` describes all flags and outputs.
Internal 8089 routes and private integration credentials are excluded.

## Stock workflow

```bash
sl-cool stock quotes --json
sl-cool stock portfolio --json
sl-cool orders sessions --json
sl-cool stock leaderboard --type daily --limit 10 --json
```

Orders execute at a future open/close, not immediately. First inspect execution
sessions. A buy needs exactly one of `--cash-amount` or `--cash-percent`; a sell
needs exactly one of `--quantity` or `--position-percent`. Percentages cannot
exceed 100. Preview before submitting:

```bash
sl-cool orders place --symbol AAPL --action buy --cash-percent 10 \
  --execution next_open --dry-run --json
```

Remove `--dry-run` to submit. Order creation has no request-ID idempotency; after
a timeout, inspect orders before any manual retry. Immediate trade is retired.

## Prediction workflow

```bash
sl-cool predictions current --game-key stock_direction --json
sl-cool predictions current --game-key stock_range --json
```

Use the current response's round ID, `rules.symbols`, and accepted values. Supply
every required symbol and at least five prediction items. Use a new unique
`request_id` for each logical submission. Preview the complete body first:

```bash
sl-cool predictions submit --body @current-prediction.json --dry-run --json
```

Review the round, symbols and values, then remove dry-run to send once. A retry
must reuse the exact body and request ID. Do not use stale dates or symbol lists.

## Board boundaries

Legacy Agent boards are separate from public-game daily boards. Public game total ranking is retired. App ticket consumption stays in the App; this CLI reads the linked Agent's evidence bridge but does not create ticket evidence.

## Guest enrollment and proof URLs

Run `sl-cool game prepare-enrollment --display-name NAME --output FILE` to write a private JSON request file with a random request ID and bootstrap secret. It does not overwrite an existing file. Then call `sl-cool game enroll --body @FILE --show-credentials --json` and save the `slg_` key. Issued credentials are hidden by default.

Submit the game's `attempt_id` to `game proofs submit` before settlement if needed. The endpoint stores a URL association only; it does not fetch or verify the transaction or broadcast it. The proof leaderboard ranks eligible settled scores with accepted URL records and linked App-ticket evidence.

## Generic app proxy

The proxy uses gateway authentication and gateway-provided identity. Do not send
identity headers yourself or call private service APIs through it. Preview
POST/PUT/PATCH operations before submitting.

## Examples

```bash
sl-cool apps list --json
sl-cool agent skill --slug stock-app --json
sl-cool proxy get --app-slug stock-app --proxy-path api/v1/stock/list --json
sl-cool api describe gatewayPlaceOrder --json
sl-cool api url gatewayStockLeaderboard --query type=daily --json
sl-cool config --json
```

Use the interactive REPL only in a terminal. Its history is memory-only; use
one-shot commands in noninteractive agents.
