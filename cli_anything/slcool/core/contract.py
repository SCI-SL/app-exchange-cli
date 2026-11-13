"""Build requests from a bundled, public-only OpenAPI contract."""

import copy
import json
import math
import re
from functools import lru_cache
from importlib.resources import files
from urllib.parse import quote, unquote, urlencode

from jsonschema import Draft202012Validator, FormatChecker

COMMANDS = {
    "getGatewaySkillJson": ("platform", "manifest"),
    "getPublishedStockSkill": ("platform", "stock-skill"),
    "getPlatformSkill": ("platform", "agent-skill"),
    "listPublishedApps": ("apps", "list"),
    "getPublishedApp": ("apps", "get"),
    "listAppRankings": ("apps", "rankings"),
    "listAgentApps": ("agent", "apps"),
    "getAgentApp": ("agent", "app"),
    "getAgentAppSkill": ("agent", "skill"),
    "listAvailableAppsAction": ("agent", "available"),
    "getAppSkillAction": ("agent", "actions"),
    "proxyAppGet": ("proxy", "get"),
    "proxyAppPost": ("proxy", "post"),
    "proxyAppPut": ("proxy", "put"),
    "proxyAppDelete": ("proxy", "delete"),
    "proxyAppPatch": ("proxy", "patch"),
    "gatewayStockList": ("stock", "quotes"),
    "gatewayPortfolio": ("stock", "portfolio"),
    "gatewayOrderSessions": ("orders", "sessions"),
    "gatewayListOrders": ("orders", "list"),
    "gatewayPlaceOrder": ("orders", "place"),
    "gatewayCancelOrder": ("orders", "cancel"),
    "gatewayStockLeaderboard": ("stock", "leaderboard"),
    "gatewayStockLeaderboardRank": ("stock", "rank"),
    "gatewayGetPredictionRound": ("predictions", "current"),
    "gatewaySubmitPredictions": ("predictions", "submit"),
    "gatewayPredictionLeaderboard": ("predictions", "leaderboard"),
    "gatewayPredictionRank": ("predictions", "rank"),
    "retiredGatewayTrade": ("stock", "retired-trade"),
}


class InputError(ValueError):
    """Invalid input; no request has been sent."""


@lru_cache(maxsize=1)
def specification():
    return json.loads(files("cli_anything.slcool").joinpath("data/openapi.json").read_text())


def resolve(schema):
    """Expand local schema references without loading external resources."""
    if isinstance(schema, list):
        return [resolve(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise InputError("Only local OpenAPI references are supported")
        target = specification()
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return resolve({**target, **{k: v for k, v in schema.items() if k != "$ref"}})
    return {key: resolve(value) for key, value in schema.items()}


@lru_cache(maxsize=1)
def operations():
    found = {}
    for path, item in specification()["paths"].items():
        for method in ("get", "post", "put", "patch", "delete"):
            if method not in item:
                continue
            op = copy.deepcopy(item[method])
            op.update(path=path, method=method.upper())
            op["parameters"] = resolve(item.get("parameters", []) + op.get("parameters", []))
            op["authenticated"] = bool(op.get("security", specification().get("security")))
            found[op["operationId"]] = op
    if set(found) != set(COMMANDS):
        raise RuntimeError("CLI command map and bundled OpenAPI operations differ")
    return found


def operation(operation_id):
    try:
        return operations()[operation_id]
    except KeyError:
        raise InputError(f"Unknown operation ID: {operation_id}; run api list") from None


def body_schema(op):
    body = op.get("requestBody", {})
    return resolve(body.get("content", {}).get("application/json", {}).get("schema", {}))


def validate(value, schema, label):
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: str(list(error.path)),
    )
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.path))
        # Do not echo arbitrary submitted values (which might include credentials).
        raise InputError(
            f"Invalid {label}{'.' + path if path else ''}: {error.validator} constraint"
        )


def convert(value, schema, label):
    kind = schema.get("type")
    try:
        if kind == "integer" and not isinstance(value, bool):
            value = int(value) if re.fullmatch(r"[+-]?\d+", str(value)) else value
        elif kind == "number" and not isinstance(value, bool):
            value = float(value)
            if not math.isfinite(value):
                raise ValueError()
        elif kind == "boolean" and isinstance(value, str):
            value = {"true": True, "false": False, "1": True, "0": False}[value.lower()]
    except (ValueError, TypeError, KeyError, OverflowError):
        raise InputError(f"Invalid {label}: expected {kind}") from None
    validate(value, schema, label)
    return value


def pairs(items):
    result = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise InputError("Parameters must use NAME=VALUE")
        if key in result:
            raise InputError(f"Duplicate parameter: {key}")
        result[key] = value
    return result


def _path_value(name, value):
    if not isinstance(value, str) or not value:
        raise InputError(f"Missing path parameter: {name}")
    decoded = value
    for _ in range(4):
        decoded = unquote(decoded)
    parts = decoded.split("/")
    if any(part in (".", "..") for part in parts) or any(c in decoded for c in "\\?#\r\n"):
        raise InputError(f"Invalid path parameter: {name}")
    if name == "proxyPath":
        return "/".join(quote(part, safe="") for part in value.strip("/").split("/"))
    return quote(value, safe="")


def prepare(operation_id, path_params=None, query=None, body=None):
    op = operation(operation_id)
    path_params, query = dict(path_params or {}), dict(query or {})
    path = op["path"]
    declared = {p["name"] for p in op["parameters"] if p["in"] == "path"}
    if set(path_params) - declared:
        raise InputError("Unknown path parameter")
    allowed = {p["name"] for p in op["parameters"] if p["in"] == "query"}
    is_proxy = operation_id.startswith("proxyApp")
    if not is_proxy and set(query) - allowed:
        raise InputError("Unknown query parameter; use api describe to inspect parameters")
    for param in op["parameters"]:
        name, schema = param["name"], param.get("schema", {})
        values = path_params if param["in"] == "path" else query
        if name not in values and param.get("required"):
            raise InputError(f"Missing {param['in']} parameter: {name}")
        if name in values:
            values[name] = convert(values[name], schema, name)
        if param["in"] == "path":
            path = path.replace("{" + name + "}", _path_value(name, values.get(name)))
    if is_proxy and path_params.get("appSlug") == "stock-app":
        upstream = "/" + path_params["proxyPath"].lstrip("/")
        if upstream.startswith(
            ("/api/v1/public-game", "/api/v1/storm-", "/api/v1/stock-games/statistics")
        ):
            raise InputError("This is an internal service route, outside the public API")
    if "requestBody" not in op and body is not None:
        raise InputError("This operation does not accept a JSON body")
    if "requestBody" in op:
        if body is None and op["requestBody"].get("required"):
            raise InputError("Missing JSON body; use --body @file.json or named body options")
        if body is not None:
            validate(body, body_schema(op), "body")
    if operation_id == "gatewayPlaceOrder" and body:
        expected = (
            ("cash_amount", "cash_percent")
            if body["action"] == "buy"
            else ("quantity", "position_percent")
        )
        other = (
            ("quantity", "position_percent")
            if body["action"] == "buy"
            else ("cash_amount", "cash_percent")
        )
        if sum(name in body for name in expected) != 1 or any(name in body for name in other):
            raise InputError(f"{body['action']} requires exactly one of {' / '.join(expected)}")
    encoded = {k: str(v).lower() if isinstance(v, bool) else v for k, v in query.items()}
    return {
        "method": op["method"],
        "path": path + ("?" + urlencode(encoded, doseq=True) if encoded else ""),
        "body": body,
        "authenticated": op["authenticated"],
        "operation_id": operation_id,
    }
