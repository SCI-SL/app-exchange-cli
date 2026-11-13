"""HTTP contract fixtures for guest flows; these do not implement/test PHP services."""

import json
import os
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from click.testing import CliRunner

from cli_anything.slcool.core.contract import InputError, prepare
from cli_anything.slcool.slcool_cli import cli
from cli_anything.slcool.tests.test_full_e2e import _cli
from cli_anything.slcool.utils.slcool_backend import ApiError, credential

UID = "12345678-1234-4123-8123-123456789abc"
GUEST = "slg_contract_fixture"
NEW_KEY = "slg_new_contract_fixture"
AGENT = "sl_agent_fixture"


@pytest.fixture
def guest_gateway():
    calls = []

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def handle_request(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else None
            auth = self.headers.get("Authorization")
            calls.append((self.command, self.path, auth, body))
            status = 200
            if self.path == "/api/game/players":
                result = {"player_id": "ply_fixture", "api_key": NEW_KEY,
                          "bootstrap_secret": body["bootstrap_secret"]}
            elif self.path == "/api/game/recovery":
                result = {"players": [{"api_key": NEW_KEY}]}
            elif self.path == "/api/game/credentials/rotate":
                result = {"api_key": NEW_KEY, "old_key_grace_seconds": 600}
            elif self.path == "/api/game/predictions":
                status = 503
                result = {"message": f"unavailable {GUEST}", "api_key": NEW_KEY}
            elif self.path == "/api/game/proofs":
                result = {"id": UID, "status": "pending", "url": body["url"]}
            else:
                result = {"credential_type": "guest" if auth == f"Bearer {GUEST}" else "agent"}
            data = json.dumps({"res_code": 0, "data": result}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_DELETE = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", calls
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def run_cli(origin, args, monkeypatch):
    monkeypatch.setenv("SL_COOL_API_KEY", AGENT)
    monkeypatch.setenv("SL_COOL_GAME_KEY", GUEST)
    return CliRunner().invoke(cli, ["--base-url", origin, "--json", *args])


def test_enroll_file_and_opt_in_credentials(guest_gateway, tmp_path, monkeypatch):
    origin, calls = guest_gateway
    path = tmp_path / "enroll.json"
    runner = CliRunner()
    prepared = runner.invoke(cli, ["game", "prepare-enrollment", "--display-name", "Guest",
                                  "--output", str(path), "--json"])
    assert prepared.exit_code == 0, prepared.output
    body = json.loads(path.read_text())
    assert len(body["bootstrap_secret"]) == 64
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = runner.invoke(cli, ["game", "prepare-enrollment", "--display-name", "Other",
                               "--output", str(path), "--json"])
    assert again.exit_code != 0
    assert json.loads(path.read_text()) == body
    hidden = run_cli(origin, ["game", "enroll", "--body", "@" + str(path)], monkeypatch)
    assert hidden.exit_code == 0, hidden.output
    assert NEW_KEY not in hidden.output and body["bootstrap_secret"] not in hidden.output
    shown = run_cli(origin, ["game", "enroll", "--body", "@" + str(path),
                             "--show-credentials"], monkeypatch)
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["data"]["api_key"] == NEW_KEY
    assert body["bootstrap_secret"] not in shown.output
    assert all(c[2] is None for c in calls)
    assert calls[0][3] == calls[1][3] == body


def test_credentials_select_guest_agent_and_reject_wrong_family(guest_gateway, monkeypatch):
    origin, calls = guest_gateway
    result = run_cli(origin, ["game", "me"], monkeypatch)
    assert result.exit_code == 0
    assert json.loads(result.output)["data"]["credential_type"] == "guest"
    assert calls[-1][2] == f"Bearer {GUEST}"
    monkeypatch.delenv("SL_COOL_GAME_KEY")
    result = CliRunner().invoke(cli, ["--base-url", origin, "game", "me", "--json"])
    assert result.exit_code == 0 and calls[-1][2] == f"Bearer {AGENT}"
    for op in ("rotateGuestCredential", "sendClaimCode"):
        with pytest.raises(ApiError, match="slg_"):
            credential({"authenticated": True, "credential_policy": "guest", "operation_id": op})
    monkeypatch.setenv("SL_COOL_API_KEY", GUEST)
    with pytest.raises(ApiError, match="sl_"):
        credential(prepare("gatewayPortfolio"))
    monkeypatch.setenv("SL_COOL_API_KEY", "sl_bad\nheader")
    with pytest.raises(ApiError, match="whitespace"):
        credential(prepare("gatewayPortfolio"))


@pytest.mark.parametrize("operation,args", [
    ("rotateGuestCredential", ["game", "credentials", "rotate", "--request-id", UID]),
    ("recoverGuestPlayers", ["game", "recovery", "recover", "--email", "guest@example.com",
                             "--code", "123456"]),
])
def test_rotate_and_recover_reveal_only_when_requested(guest_gateway, monkeypatch, operation, args):
    origin, calls = guest_gateway
    hidden = run_cli(origin, args, monkeypatch)
    assert hidden.exit_code == 0 and NEW_KEY not in hidden.output
    shown = run_cli(origin, args + ["--show-credentials"], monkeypatch)
    assert shown.exit_code == 0 and NEW_KEY in shown.output
    assert calls[-1][2] == (None if operation == "recoverGuestPlayers" else f"Bearer {GUEST}")


def test_proof_can_be_submitted_before_score_without_strict_www_filter(guest_gateway, monkeypatch):
    origin, calls = guest_gateway
    url = "https://www.bitgold.live/tx/0x" + "a" * 64 + "?source=cli"
    result = run_cli(origin, ["game", "proofs", "submit", "--attempt-id", UID,
                              "--url", url], monkeypatch)
    assert result.exit_code == 0, result.output
    assert calls[-1][3] == {"attempt_id": UID, "url": url}
    assert json.loads(result.output)["data"]["status"] == "pending"


def test_failed_post_not_retried_or_secret_leaked(guest_gateway, monkeypatch):
    origin, calls = guest_gateway
    body = {"game_key": "stock_direction", "round_id": "2026-11-13", "request_id": UID,
            "predictions": [{"symbol": "AAPL", "value": "up"}]}
    result = run_cli(origin, ["game", "predictions", "submit", "--body", json.dumps(body)], monkeypatch)
    assert result.exit_code != 0
    assert len(calls) == 1
    assert json.loads(result.output)["error"]["status"] == 503
    assert GUEST not in result.output and NEW_KEY not in result.output


@pytest.mark.parametrize("op,body", [
    ("claimGuestIdentity", {"email": "a@example.com", "code": "abc123"}),
    ("submitPredictions", {"game_key": "stock_direction", "round_id": "2026-02-30",
                           "request_id": UID, "predictions": [{"symbol": "AAPL", "value": "up"}]}),
    ("rotateGuestCredential", {"request_id": "not-a-uuid"}),
    ("submitProof", {"url": "https://bitgold.live/tx/x"}),
    ("submitProof", {"attempt_id": UID, "score_id": UID, "url": "https://bitgold.live/tx/x"}),
    ("submitProof", {"attempt_id": UID, "url": "javascript:alert(1)"}),
    ("placeOrder", {"request_id": UID, "symbol": "AAPL", "action": "sell",
                    "execution": "next_close", "cash_percent": 20}),
])
def test_invalid_guest_inputs_fail_locally(op, body):
    with pytest.raises(InputError):
        prepare(op, body=body)


def test_otp_and_dry_run_redact_and_do_not_send(guest_gateway, monkeypatch):
    origin, calls = guest_gateway
    result = run_cli(origin, ["game", "claim", "confirm", "--email", "a@example.com",
                              "--code", "123456", "--dry-run"], monkeypatch)
    assert result.exit_code == 0, result.output
    assert "123456" not in result.output
    assert not calls
    result = run_cli(origin, ["api", "call", "getGameIdentity", "--show-credentials"], monkeypatch)
    assert result.exit_code != 0 and not calls


def test_installed_nested_commands_and_guest_transport(guest_gateway, tmp_path):
    origin, calls = guest_gateway
    env = dict(os.environ, SL_COOL_API_KEY=AGENT, SL_COOL_GAME_KEY=GUEST)
    for args in (["game", "--help"], ["game", "proofs", "submit", "--help"], ["game", "me"]):
        result = subprocess.run(_cli() + ["--base-url", origin, *args, "--json"],
                                check=False, cwd=tmp_path, env=env, capture_output=True,
                                text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["data"]["credential_type"] == "guest"
    assert calls[-1][2] == f"Bearer {GUEST}"
    retired = CliRunner().invoke(cli, ["game", "leaderboard", "retired-total", "--json"])
    assert retired.exit_code != 0 and "410" in retired.output
