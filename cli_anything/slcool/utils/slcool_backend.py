"""Call the real gateway without redirects, implicit retries or credential storage."""

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cli_anything.slcool import __version__
from cli_anything.slcool.core.contract import InputError


class ApiError(Exception):
    def __init__(self, message, *, status=None, body=None, kind="api"):
        super().__init__(message)
        self.status, self.body, self.kind = status, body, kind


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def redact(value, secret="", *, show_credentials=False):
    if isinstance(value, dict):
        return {
            k: v
            if show_credentials and k == "api_key" and isinstance(v, str) and v.startswith("slg_")
            else "[REDACTED]"
            if re.search(r"token|secret|password|authorization|api.?key", k, re.IGNORECASE)
            or (k == "code" and isinstance(v, str) and re.fullmatch(r"[0-9]{6}", v))
            else redact(v, secret, show_credentials=show_credentials)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secret, show_credentials=show_credentials) for item in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, "[REDACTED]")
        for env in ("SL_COOL_API_KEY", "SL_COOL_GAME_KEY"):
            if os.environ.get(env):
                value = value.replace(os.environ[env], "[REDACTED]")
        return re.sub(r"\bslg?_[A-Za-z0-9_-]+", "[REDACTED]", value)
    return value


def base_url(value):
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise InputError(
            "Base URL must be an HTTP(S) origin without credentials, path, query or fragment"
        )
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise InputError("Use HTTPS for remote gateways; HTTP is allowed only for loopback testing")
    try:
        _ = parts.port
    except ValueError:
        raise InputError("Invalid gateway port") from None
    return value.rstrip("/")


def credential(request):
    policy = request.get("credential_policy", "agent" if request["authenticated"] else "anonymous")
    if policy == "anonymous":
        return ""
    token = (
        os.environ.get("SL_COOL_GAME_KEY") or os.environ.get("SL_COOL_API_KEY", "")
        if policy in ("game", "guest") else os.environ.get("SL_COOL_API_KEY", "")
    )
    if not token:
        raise ApiError(
            "Set SL_COOL_GAME_KEY or SL_COOL_API_KEY for game commands"
            if policy in ("game", "guest") else "Set SL_COOL_API_KEY to your sl_ Agent API key",
            kind="authentication",
        )
    if token and (token != token.strip() or any(ord(c) < 33 or ord(c) > 126 for c in token)):
        raise ApiError(
            "Credential contains whitespace or invalid header characters",
            kind="authentication",
        )
    prefixes = ("slg_",) if policy == "guest" else ("sl_",) if policy == "agent" else ("sl_", "slg_")
    if not token.startswith(prefixes):
        raise ApiError(
            "This operation requires " + " or ".join(prefixes) + " credentials",
            kind="authentication",
        )
    return token


def execute(request, origin, timeout=20.0, *, show_credentials=False):
    origin = base_url(origin)
    token = credential(request)
    headers = {
        "Accept": "application/json, text/markdown;q=0.9",
        "User-Agent": f"cli-anything-slcool/{__version__}",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if request["body"] is not None:
        data = json.dumps(request["body"], ensure_ascii=False, allow_nan=False).encode()
        headers["Content-Type"] = "application/json"
    req = Request(origin + request["path"], data=data, headers=headers, method=request["method"])
    try:
        with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(raw)
            except ValueError:
                if "json" in response.headers.get("Content-Type", ""):
                    raise ApiError(
                        "Gateway returned invalid JSON", status=response.status, kind="protocol"
                    ) from None
                result = raw
    except HTTPError as error:
        raw = error.read(65536).decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"message": "Non-JSON error response; inspect the gateway server logs"}
        raise ApiError(
            f"Gateway returned HTTP {error.code}",
            status=error.code,
            body=redact(body, token),
            kind="http",
        ) from None
    except (URLError, TimeoutError, OSError):
        raise ApiError(
            "Cannot reach the gateway or request timed out; no automatic retry was made",
            kind="connection",
        ) from None
    if isinstance(result, dict):
        code = result.get("res_code", 0)
        if result.get("success") is False or code not in (0, "0", None):
            raise ApiError(
                "Gateway reported an application error",
                body=redact(result, token),
                kind="application",
            )
    return redact(result, token, show_credentials=show_credentials and request.get("issues_credentials", False))
