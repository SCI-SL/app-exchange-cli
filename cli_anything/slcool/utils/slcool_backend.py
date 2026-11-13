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


def redact(value, secret=""):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if re.search(r"token|secret|password|authorization|api.?key", k, re.IGNORECASE)
            else redact(v, secret)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"\bsl_[A-Za-z0-9_-]+", "[REDACTED]", value)
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


def execute(request, origin, timeout=20.0):
    origin = base_url(origin)
    token = os.environ.get("SL_COOL_API_KEY", "") if request["authenticated"] else ""
    if request["authenticated"] and not token:
        raise ApiError("Set SL_COOL_API_KEY to your sl_ Agent API key", kind="authentication")
    if token and (token != token.strip() or any(ord(c) < 33 or ord(c) > 126 for c in token)):
        raise ApiError(
            "SL_COOL_API_KEY contains whitespace or invalid header characters",
            kind="authentication",
        )
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
    return redact(result, token)
