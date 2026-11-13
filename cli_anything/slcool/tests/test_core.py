import json
import os
import subprocess
import sys
from typing import ClassVar

import pytest
from click.testing import CliRunner

from cli_anything.slcool.core.contract import COMMANDS, InputError, operations, prepare
from cli_anything.slcool.slcool_cli import cli
from cli_anything.slcool.utils.slcool_backend import ApiError, base_url, execute


def test_all_openapi_operations_have_commands():
    assert len(operations()) == 29
    assert set(operations()) == set(COMMANDS)


@pytest.mark.parametrize(
    "operation_id,query",
    [
        ("gatewayStockLeaderboard", {"type": "daily", "limit": "10", "live": "false"}),
        (
            "gatewayPredictionLeaderboard",
            {"game_key": "stock_direction", "type": "daily", "limit": "20"},
        ),
        ("listPublishedApps", {"page": "1", "pageSize": "20"}),
    ],
)
def test_query_values_are_typed_and_encoded(operation_id, query):
    request = prepare(operation_id, query=query)
    assert request["method"] == "GET"
    assert "?" in request["path"]


def test_path_parameters_are_encoded_and_traversal_blocked():
    assert prepare("getPublishedApp", {"slug": "hello world"})["path"].endswith("hello%20world")
    with pytest.raises(InputError):
        prepare("proxyAppGet", {"appSlug": "stock-app", "proxyPath": "%252e%252e/private"})


def test_proxy_cannot_reach_internal_routes():
    for route in (
        "api/v1/public-game",
        "api/v1/storm-ticket-records",
        "api/v1/stock-games/statistics",
    ):
        with pytest.raises(InputError):
            prepare("proxyAppPost", {"appSlug": "stock-app", "proxyPath": route}, body={})


def test_order_validation_enforces_operation_specific_sizing():
    with pytest.raises(InputError):
        prepare("gatewayPlaceOrder", body={"symbol": "AAPL", "action": "buy"})
    with pytest.raises(InputError):
        prepare(
            "gatewayPlaceOrder",
            body={"symbol": "AAPL", "action": "buy", "cash_percent": 10, "quantity": 1},
        )
    assert (
        prepare("gatewayPlaceOrder", body={"symbol": "AAPL", "action": "buy", "cash_percent": 10})[
            "method"
        ]
        == "POST"
    )


def test_prediction_request_rejects_too_few_items():
    body = {
        "game_key": "stock_direction",
        "round_id": "2026-11-11",
        "predictions": [{"symbol": "AAPL", "value": "up"}],
    }
    with pytest.raises(InputError):
        prepare("gatewaySubmitPredictions", body=body)


def test_remote_http_and_insecure_origins_are_rejected():
    for origin in ("http://example.com", "https://example.com/path", "https://u:p@example.com"):
        with pytest.raises(InputError):
            base_url(origin)
    assert base_url("http://127.0.0.1:8089") == "http://127.0.0.1:8089"


def test_unauthenticated_operations_do_not_send_agent_key(monkeypatch):
    import cli_anything.slcool.utils.slcool_backend as backend

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok":true}'

    class Opener:
        def open(self, request, timeout):
            assert "Authorization" not in request.headers
            return Response()

    monkeypatch.setenv("SL_COOL_API_KEY", "sl_test_secret")
    monkeypatch.setattr(backend, "build_opener", lambda *_: Opener())
    request = prepare("listPublishedApps")
    assert execute(request, "https://open.sl.cool") == {"ok": True}


def test_auth_key_is_required_only_for_protected_operations(monkeypatch):
    monkeypatch.delenv("SL_COOL_API_KEY", raising=False)
    with pytest.raises(ApiError, match="SL_COOL_API_KEY"):
        execute(prepare("gatewayPortfolio"), "https://open.sl.cool")
    import cli_anything.slcool.utils.slcool_backend as backend
    from cli_anything.slcool.utils.slcool_backend import execute as perform

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {"Content-Type": "text/markdown"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"# Public skill"

    class Opener:
        def open(self, request, timeout):
            assert "Authorization" not in request.headers
            return Response()

    backend.build_opener = lambda *_: Opener()
    assert perform(prepare("getPublishedStockSkill"), "https://open.sl.cool") == "# Public skill"


def test_no_redirect_and_http_errors_are_structured(monkeypatch):
    from urllib.error import HTTPError

    import cli_anything.slcool.utils.slcool_backend as backend

    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "GET"
            raise HTTPError(request.full_url, 302, "redirect", {}, None)

    monkeypatch.setenv("SL_COOL_API_KEY", "sl_supersecret")
    monkeypatch.setattr(backend, "build_opener", lambda *_: Opener())
    with pytest.raises(ApiError) as error:
        execute(prepare("gatewayPortfolio"), "https://open.sl.cool")
    assert error.value.status == 302


def test_dry_run_needs_no_key_or_network(monkeypatch):
    monkeypatch.delenv("SL_COOL_API_KEY", raising=False)
    result = CliRunner().invoke(
        cli,
        [
            "--json",
            "orders",
            "place",
            "--symbol",
            "AAPL",
            "--action",
            "buy",
            "--cash-percent",
            "10",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["dry_run"] is True
    assert value["authentication_required"] is True


def test_json_cli_output_and_generic_url():
    runner = CliRunner()
    listing = runner.invoke(cli, ["--json", "api", "list"])
    assert listing.exit_code == 0, listing.output
    assert len(json.loads(listing.output)) == 29
    url = runner.invoke(
        cli,
        [
            "api",
            "url",
            "gatewayPredictionLeaderboard",
            "--query",
            "game_key=stock_direction",
            "--query",
            "type=daily",
            "--json",
        ],
    )
    assert url.exit_code == 0, url.output
    assert "game_key=stock_direction" in json.loads(url.output)["url"]


def test_installed_command_help_and_machine_output():
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED") == "1"
    import shutil

    executable = shutil.which("cli-anything-slcool")
    if force and not executable:
        pytest.fail("cli-anything-slcool is not installed in PATH")
    if executable:
        command = [executable]
    else:
        command = [sys.executable, "-m", "cli_anything.slcool.slcool_cli"]
    for args in (["--help"], ["--json", "api", "list"]):
        result = subprocess.run(
            command + list(args), check=False, cwd="/", capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        if args[-1] == "list":
            assert len(json.loads(result.stdout)) == 29
