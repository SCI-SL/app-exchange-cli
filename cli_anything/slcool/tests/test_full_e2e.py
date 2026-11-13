"""Installed CLI -> local authenticated gateway adapter -> real Python stock service."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest


@pytest.fixture(scope="module")
def real_stock_stack(tmp_path_factory):
    source = Path(
        os.environ.get(
            "SLCOOL_STOCK_SOURCE",
            Path(__file__).resolve().parents[5] / "sl.cool-stock",
        )
    ).resolve()
    if not (source / "app.py").is_file():
        pytest.fail(f"Real stock backend not found at {source}; set SLCOOL_STOCK_SOURCE")

    storage = tmp_path_factory.mktemp("stock-db")
    paths = {
        "STOCK_DATA_FILE": storage / "stocks_db.json",
        "STOCK_DATA_BACKUP_FILE": storage / "stocks_db.json.bak",
        "STOCK_DATA_GUARD_FILE": storage / "stocks_db.json.guard.json",
        "STOCK_PREDICTION_DATA_FILE": storage / "stock_predictions_db.json",
        "STOCK_PREDICTION_DATA_BACKUP_FILE": storage / "stock_predictions_db.json.bak",
        "STOCK_PUBLIC_GAME_DATA_FILE": storage / "public_games_db.json",
    }
    previous = {key: os.environ.get(key) for key in paths}
    os.environ.update({key: str(value) for key, value in paths.items()})
    sys.path.insert(0, str(source))
    try:
        spec = importlib.util.spec_from_file_location("slcool_e2e_stock_app", source / "app.py")
        app = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = app
        spec.loader.exec_module(app)
    finally:
        sys.path.remove(str(source))
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    app.MARKET_DATA_CONFIGURED = False
    app.update_game_state = lambda db, *args, **kwargs: []
    app.initialize_leaderboard_snapshots()
    stock = app.StockHTTPServer(("127.0.0.1", 0), app.StockAppHandler)
    stock_thread = threading.Thread(target=stock.serve_forever, daemon=True)
    stock_thread.start()
    backend = (f"http://127.0.0.1:{stock.server_port}", app, storage)
    expected_key = "sl_local_fixture_key"

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.headers.get("Authorization") != f"Bearer {expected_key}":
                self.send_error(401)
                return
            prefix = "/api/skill/apps/stock-app/proxy/"
            if not self.path.startswith(prefix):
                self.send_error(404)
                return
            upstream = self.path[len(prefix) :]
            request = Request(
                backend[0] + "/" + upstream,
                headers={"X-SL-User-DID": "did:example:cli-test"},
            )
            try:
                with urlopen(request, timeout=10) as response:
                    data, status = response.read(), response.status
            except (HTTPError, URLError, OSError, TimeoutError) as error:
                data, status = json.dumps({"error": type(error).__name__}).encode(), 502
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(data)

    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    gateway_thread.start()
    yield f"http://127.0.0.1:{gateway.server_port}", expected_key, paths, stock
    gateway.shutdown()
    gateway.server_close()
    stock.shutdown()
    stock.server_close()
    stock_thread.join(timeout=5)
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _cli():
    executable = shutil.which("cli-anything-slcool")
    if executable:
        return [executable]
    if os.environ.get("CLI_ANYTHING_FORCE_INSTALLED") == "1":
        pytest.fail("cli-anything-slcool not installed in PATH")
    return [sys.executable, "-m", "cli_anything.slcool.slcool_cli"]


def test_installed_cli_calls_real_stock_backend_with_gateway_identity(real_stock_stack, tmp_path):
    origin, key, paths, _stock = real_stock_stack
    env = dict(os.environ, SL_COOL_API_KEY=key)
    result = subprocess.run(
        _cli() + ["--base-url", origin, "stock", "portfolio", "--json"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["res_code"] == 0
    assert "profit_rate" in response["data"]
    database = json.loads(paths["STOCK_DATA_FILE"].read_text())
    assert "did:example:cli-test" in database["users"]


def test_installed_cli_handles_real_stock_leaderboard_response(real_stock_stack, tmp_path):
    origin, key, _paths, _stock = real_stock_stack
    env = dict(os.environ, SL_COOL_API_KEY=key)
    result = subprocess.run(
        _cli() + ["--base-url", origin, "stock", "leaderboard", "--type", "all", "--json"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["res_code"] == 0


def test_actual_error_does_not_leak_key(real_stock_stack, tmp_path):
    origin, key, _paths, _stock = real_stock_stack
    env = dict(os.environ, SL_COOL_API_KEY=key)
    result = subprocess.run(
        _cli() + ["--base-url", origin, "stock", "portfolio", "--json"],
        cwd=tmp_path,
        env={**env, "SL_COOL_API_KEY": "wrong"},
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "wrong" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["status"] == 401
