"""Click commands generated from the public SL Cool OpenAPI contract."""

import json
import os
import re
import shlex
import sys
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


def output(value, json_mode=False):
    value = redact(value, os.environ.get("SL_COOL_API_KEY", ""))
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
    """SL Cool public Agent API. Credentials: SL_COOL_API_KEY (never stored).

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


def dispatch(ctx, operation_id, paths=None, query=None, body=None, dry_run=False):
    req = prepare(operation_id, paths, query, body)
    if dry_run or ctx.obj["dry_run"]:
        value = {
            "dry_run": True,
            "operation_id": operation_id,
            "method": req["method"],
            "url": ctx.obj["origin"] + req["path"],
            "body": req["body"],
            "authentication_required": req["authenticated"],
        }
    else:
        value = execute(req, ctx.obj["origin"], ctx.obj["timeout"])
    output(value, ctx.obj["json"])


def flag_name(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).replace("_", "-").lower()


def named_command(operation_id, name):
    op = operation(operation_id)
    params = [click.Option(["--dry-run"], is_flag=True, help="Validate without sending a request.")]
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
        if op.get("deprecated"):
            raise InputError(
                "Immediate trade is retired; use orders place with next_open or next_close"
            )
        dispatch(ctx, operation_id, paths, query, body, dry_run)

    help_text = op["summary"] + ".\n\nOperation ID: " + operation_id
    if op.get("description"):
        help_text += "\n\n" + op["description"]
    return click.Command(
        name, callback=invoke, params=params, help=help_text, deprecated=op.get("deprecated", False)
    )


for _operation_id, (_group_name, _name) in COMMANDS.items():
    if _group_name not in cli.commands:
        cli.add_command(
            click.Group(
                _group_name,
                help={
                    "platform": "Public skill documents and manifest (no key required).",
                    "apps": "Public application catalog and rankings (no key required).",
                    "agent": "Authenticated application discovery and skills.",
                    "proxy": "Call another published app through the authenticated gateway.",
                    "stock": "Quotes, portfolio and legacy portfolio leaderboards.",
                    "orders": "Virtual stock orders; writes are never retried automatically.",
                    "predictions": "Legacy prediction rounds, submissions and leaderboards.",
                }[_group_name],
            )
        )
    cli.commands[_group_name].add_command(named_command(_operation_id, _name))


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
@click.pass_context
def api_call(ctx, operation_id, param, query, body, dry_run):
    if operation(operation_id).get("deprecated"):
        raise InputError("Immediate trade is retired; use gatewayPlaceOrder")
    dispatch(
        ctx, operation_id, pairs(param), pairs(query), load_json(body) if body else None, dry_run
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
            "credential_source": "SL_COOL_API_KEY",
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
            if args[0] in cli.commands:
                first = cli.commands[args[0]]
                if isinstance(first, click.Group) and len(args) > 1 and args[1] in first.commands:
                    args = args[:2] + prefix + args[2:]
                else:
                    args = args[:1] + prefix + args[1:]
            else:
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
