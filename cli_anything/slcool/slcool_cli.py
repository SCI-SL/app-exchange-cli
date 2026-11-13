"""Click commands generated from the public SL Cool OpenAPI contract."""

import json
import os
import re
import secrets
import shlex
import sys
import uuid
from pathlib import Path

import click

from cli_anything.slcool import __version__
from cli_anything.slcool.core.contract import (
    COMMANDS,
    InputError,
    body_schema,
    convert,
    operation,
    operations,
    pairs,
    prepare,
)
from cli_anything.slcool.utils.slcool_backend import ApiError, base_url, execute, redact


def load_json(value):
    """Accept inline JSON, @path or @- (stdin). Never echo invalid input."""
    try:
        if value == "@-":
            value = sys.stdin.read()
        elif value.startswith("@"):
            value = Path(value[1:]).expanduser().read_text(encoding="utf-8")
        return json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (OSError, ValueError):
        raise InputError("Cannot read JSON; use valid inline JSON, @file.json, or @-") from None


def output(value, json_mode=False, *, show_credentials=False):
    value = redact(value, os.environ.get("SL_COOL_API_KEY", ""), show_credentials=show_credentials)
    if json_mode:
        click.echo(json.dumps(value, ensure_ascii=False, allow_nan=False))
    elif isinstance(value, str):
        click.echo(value)
    else:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


class JsonGroup(click.Group):
    """Recognize --json at any depth, including parser errors."""

    def main(self, args=None, **kwargs):
        args = list(sys.argv[1:] if args is None else args)
        wants_json = "--json" in args
        if wants_json:
            args = [arg for arg in args if arg != "--json"]
            # Click reads the flag once at the root; nested invocations also work.
            args.insert(0, "--json")
        try:
            kwargs["standalone_mode"] = False
            return super().main(args=args, **kwargs)
        except (click.ClickException, InputError, ApiError) as error:
            code = error.exit_code if isinstance(error, click.ClickException) else 1
            message = (
                error.format_message() if isinstance(error, click.ClickException) else str(error)
            )
            payload = {"error": {"type": getattr(error, "kind", "input"), "message": message}}
            if isinstance(error, ApiError):
                payload["error"].update(status=error.status, body=error.body)
            if wants_json:
                output(payload, True)
            else:
                click.echo(
                    "Error: " + str(redact(message, os.environ.get("SL_COOL_API_KEY", ""))),
                    err=True,
                )
                if isinstance(error, ApiError) and error.body:
                    click.echo(
                        json.dumps(redact(error.body), ensure_ascii=False, indent=2), err=True
                    )
            raise SystemExit(code) from None
        except (click.Abort, KeyboardInterrupt):
            if wants_json:
                output({"error": {"type": "aborted", "message": "Command aborted"}}, True)
            raise SystemExit(130) from None


@click.group(cls=JsonGroup, invoke_without_command=True)
@click.option(
    "--base-url",
    "origin",
    default="https://open.sl.cool",
    envvar="SL_COOL_BASE_URL",
    show_default=True,
    help="Gateway origin; HTTPS required except on loopback.",
)
@click.option("--timeout", type=click.FloatRange(min=0.1, max=300), default=20.0, show_default=True)
@click.option(
    "--json", "json_mode", is_flag=True, help="Machine-readable JSON output, including errors."
)
@click.option(
    "--dry-run", is_flag=True, help="Validate and display request; do not contact the gateway."
)
@click.version_option(__version__)
@click.pass_context
def cli(ctx, origin, timeout, json_mode, dry_run):
    """SL Cool Agent and guest game API. Keys: SL_COOL_API_KEY / SL_COOL_GAME_KEY.

    Start without a subcommand for an interactive REPL. Use --json before or after
    a subcommand. Use api list to discover all supported operations.
    """
    ctx.obj = {
        "origin": base_url(origin),
        "timeout": timeout,
        "json": json_mode,
        "dry_run": dry_run,
    }
    if ctx.invoked_subcommand is None:
        if json_mode:
            output(
                {
                    "version": __version__,
                    "operations": len(operations()),
                    "base_url": ctx.obj["origin"],
                    "hint": "Use api list for commands or repl for interactive mode",
                },
                True,
            )
        else:
            ctx.invoke(repl)


def dispatch(ctx, operation_id, paths=None, query=None, body=None, dry_run=False,
             show_credentials=False):
    req = prepare(operation_id, paths, query, body)
    if show_credentials and not req["issues_credentials"]:
        raise InputError("--show-credentials is only supported for enroll, recover and rotate")
    if dry_run or ctx.obj["dry_run"]:
        value = {
            "dry_run": True,
            "operation_id": operation_id,
            "method": req["method"],
            "url": ctx.obj["origin"] + req["path"],
            "body": req["body"],
            "authentication_required": req["authenticated"],
            "credential_policy": req["credential_policy"],
        }
    else:
        value = execute(req, ctx.obj["origin"], ctx.obj["timeout"], show_credentials=show_credentials)
    output(value, ctx.obj["json"], show_credentials=show_credentials and not value_is_dry_run(ctx, dry_run))


def value_is_dry_run(ctx, dry_run):
    return dry_run or ctx.obj["dry_run"]


def reject_retired(op):
    if op.get("deprecated"):
        if op["operationId"] == "retiredTotalLeaderboard":
            raise InputError("Public total leaderboard is retired (410); use game leaderboard daily")
        raise InputError("Immediate trade is retired; use orders place with next_open or next_close")


def flag_name(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).replace("_", "-").lower()


def named_command(operation_id, name):
    op = operation(operation_id)
    params = [click.Option(["--dry-run"], is_flag=True, help="Validate without sending a request.")]
    if op.get("x-issues-credentials"):
        params.append(click.Option(["--show-credentials"], is_flag=True,
                                   help="Print newly issued guest keys. Keep stdout private."))
    bindings = []
    for param in op["parameters"]:
        key = "p_" + param["name"]
        schema = param.get("schema", {})
        help_text = ("Required. " if param.get("required") else "") + param.get("description", "")
        if "enum" in schema:
            help_text += " Choices: " + ", ".join(map(str, schema["enum"]))
        if "default" in schema:
            help_text += f" Server default: {schema['default']}."
        # Coercion/validation uses OpenAPI centrally; keeping strings also supports api call.
        params.append(click.Option(["--" + flag_name(param["name"]), key], help=help_text))
        bindings.append((key, param["in"], param["name"], schema))
    if operation_id.startswith("proxyApp"):
        params.append(
            click.Option(["--query"], multiple=True, help="Upstream query NAME=VALUE; repeatable.")
        )
    if "requestBody" in op:
        params.append(click.Option(["--body"], help="JSON object, @file.json, or @- for stdin."))
        for prop, schema in body_schema(op).get("properties", {}).items():
            key = "b_" + prop
            params.append(
                click.Option(
                    ["--" + flag_name(prop), key],
                    help="JSON array or @file.json."
                    if schema.get("type") == "array"
                    else f"Body field: {prop}.",
                )
            )
            bindings.append((key, "body", prop, schema))

    @click.pass_context
    def invoke(ctx, **values):
        body_input = values.pop("body", None)
        body = load_json(body_input) if body_input is not None else None
        if body is not None and not isinstance(body, dict):
            raise InputError("JSON body must be an object")
        query = pairs(values.pop("query", ()))
        paths = {}
        dry_run = values.pop("dry_run", False)
        show_credentials = values.pop("show_credentials", False)
        for key, location, prop, schema in bindings:
            value = values.pop(key, None)
            if value is None:
                continue
            if schema.get("type") in ("array", "object"):
                value = load_json(value)
            value = convert(value, schema, prop)
            if location == "body":
                if body is None:
                    body = {}
                if prop in body:
                    raise InputError(
                        f"Duplicate body field: {prop}; choose --body or its named option"
                    )
                body[prop] = value
            else:
                (paths if location == "path" else query)[prop] = value
        reject_retired(op)
        dispatch(ctx, operation_id, paths, query, body, dry_run, show_credentials)

    help_text = op["summary"] + ".\n\nOperation ID: " + operation_id
    if op.get("description"):
        help_text += "\n\n" + op["description"]
    return click.Command(
        name, callback=invoke, params=params, help=help_text, deprecated=op.get("deprecated", False)
    )


for _operation_id, _parts in COMMANDS.items():
    _parent = cli
    for _group_name in _parts[:-1]:
        if _group_name not in _parent.commands:
            group_help = (
                "Public game " + _group_name + " operations."
                if _parts[0] == "game"
                else {
                    "platform": "Public skill documents and manifest (no key required).",
                    "apps": "Public application catalog and rankings (no key required).",
                    "agent": "Authenticated application discovery and skills.",
                    "proxy": "Call another published app through the authenticated gateway.",
                    "stock": "Quotes, portfolio and legacy portfolio leaderboards.",
                    "orders": "Virtual stock orders; writes are never retried automatically.",
                    "predictions": "Legacy prediction rounds, submissions and leaderboards.",
                    "game": "Public games for guests (slg_) and Agents (sl_).",
                }.get(_group_name, "Public API operations."))
            _parent.add_command(click.Group(_group_name, help=group_help))
        _parent = _parent.commands[_group_name]
    _parent.add_command(named_command(_operation_id, _parts[-1]))


@cli.commands["game"].command("prepare-enrollment")
@click.option("--display-name", required=True, help="Guest display name (1-50 characters).")
@click.option("--output", "path", required=True, type=click.Path(path_type=Path))
@click.pass_context
def prepare_enrollment(ctx, display_name, path):
    """Create a private, reusable enrollment JSON file locally; no HTTP request."""
    if not 1 <= len(display_name) <= 50:
        raise InputError("Display name must contain 1-50 characters")
    if ctx.obj["dry_run"]:
        raise InputError("prepare-enrollment writes a local file; omit --dry-run to create it")
    body = {"request_id": str(uuid.uuid4()), "bootstrap_secret": secrets.token_hex(32),
            "display_name": display_name}
    try:
        fd = os.open(path.expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(body, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except OSError:
        raise InputError("Cannot create enrollment file; choose a new path in an existing directory") from None
    output({"file": str(path.expanduser().resolve()), "request_id": body["request_id"]}, ctx.obj["json"])


@cli.group()
def api():
    """Inspect the contract or invoke an operation by its operation ID."""


@api.command("list")
@click.pass_context
def api_list(ctx):
    output(
        [
            {
                "operation_id": key,
                "command": " ".join(COMMANDS[key]),
                "method": op["method"],
                "path": op["path"],
                "authenticated": op["authenticated"],
                "credential_policy": op["credential_policy"],
                "deprecated": op.get("deprecated", False),
            }
            for key, op in operations().items()
        ],
        ctx.obj["json"],
    )


@api.command("describe")
@click.argument("operation_id")
@click.pass_context
def api_describe(ctx, operation_id):
    op = dict(operation(operation_id))
    op["body_schema"] = body_schema(op)
    op["command"] = " ".join(COMMANDS[operation_id])
    output(op, ctx.obj["json"])


@api.command("call")
@click.argument("operation_id")
@click.option("--param", multiple=True, help="Path NAME=VALUE; repeatable.")
@click.option("--query", multiple=True, help="Query NAME=VALUE; repeatable.")
@click.option("--body", help="JSON object, @file.json, or @-.")
@click.option("--dry-run", is_flag=True)
@click.option("--show-credentials", is_flag=True, help="Reveal issued guest keys (issuance only).")
@click.pass_context
def api_call(ctx, operation_id, param, query, body, dry_run, show_credentials):
    reject_retired(operation(operation_id))
    dispatch(
        ctx, operation_id, pairs(param), pairs(query), load_json(body) if body else None, dry_run,
        show_credentials,
    )


@api.command("url")
@click.argument("operation_id")
@click.option("--param", multiple=True, help="Path NAME=VALUE; repeatable.")
@click.option("--query", multiple=True, help="Query NAME=VALUE; repeatable.")
@click.pass_context
def api_url(ctx, operation_id, param, query):
    """Print the exact gateway URL for an operation (no request or credentials)."""
    req = prepare(operation_id, pairs(param), pairs(query))
    output({"method": req["method"], "url": ctx.obj["origin"] + req["path"]}, ctx.obj["json"])


@cli.command()
@click.pass_context
def config(ctx):
    """Show endpoint/options and whether a key is present; never print credentials."""
    output(
        {
            "base_url": ctx.obj["origin"],
            "timeout": ctx.obj["timeout"],
            "api_key_configured": bool(os.environ.get("SL_COOL_API_KEY")),
            "game_key_configured": bool(os.environ.get("SL_COOL_GAME_KEY")),
            "credential_source": "SL_COOL_API_KEY for Agent routes; SL_COOL_GAME_KEY then SL_COOL_API_KEY for games",
            "version": __version__,
        },
        ctx.obj["json"],
    )


@cli.command()
@click.pass_context
def repl(ctx):
    """Interactive mode using the same commands. Type help or exit. No disk history."""
    if not sys.stdin.isatty():
        raise InputError("REPL requires an interactive terminal; use subcommands or --json")
    from prompt_toolkit.history import InMemoryHistory

    from cli_anything.slcool.utils.repl_skin import ReplSkin

    # /dev/null is never opened for history: replace FileHistory before the first prompt.
    skin = ReplSkin("slcool", version=__version__, history_file=os.devnull)
    session = skin.create_prompt_session()
    if session is not None:
        session.history = InMemoryHistory()
    if not ctx.obj["json"]:
        skin.print_banner()
        skin.info("Commands use the SL Cool gateway. Type help or exit. History is kept in memory.")
    while True:
        try:
            line = skin.get_input(session)
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("exit", "quit"):
            break
        if not line:
            continue
        if line == "help":
            line = "--help"
        prefix = ["--base-url", ctx.obj["origin"], "--timeout", str(ctx.obj["timeout"])]
        if ctx.obj["json"]:
            prefix += ["--json"]
        if ctx.obj["dry_run"]:
            prefix += ["--dry-run"]
        try:
            args = shlex.split(line)
            if not args or args[0] == "repl":
                skin.error("Already in the REPL")
                continue
            args = prefix + args
            cli.main(args=args, prog_name="sl-cool")
        except ValueError:
            skin.error("Unclosed quote; use help for command syntax")
        except SystemExit:
            pass
    if not ctx.obj["json"]:
        skin.print_goodbye()


def main():
    cli.main(prog_name="sl-cool")


if __name__ == "__main__":
    main()
