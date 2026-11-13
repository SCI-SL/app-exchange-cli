#!/usr/bin/env sh
set -eu

repository="${1:-${SLCOOL_CLI_REPOSITORY:-}}"
if [ -z "$repository" ]; then
  echo "Usage: install.sh OWNER/REPOSITORY" >&2
  echo "Or set SLCOOL_CLI_REPOSITORY=OWNER/REPOSITORY." >&2
  exit 2
fi

case "$repository" in
  */*) ;;
  *) echo "Repository must be OWNER/REPOSITORY." >&2; exit 2 ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10 or newer is required. Install Python, then rerun this command." >&2
  exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  echo "Python 3.10 or newer is required." >&2
  exit 1
fi
if ! command -v pipx >/dev/null 2>&1; then
  echo "pipx is required. Install pipx, then rerun this command." >&2
  echo "See https://pipx.pypa.io/stable/installation/" >&2
  exit 1
fi

wheel_url="$(python3 - "$repository" <<'PY'
import json
import re
import sys
from urllib.request import Request, urlopen

repository = sys.argv[1]
if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
    raise SystemExit("Invalid GitHub repository name; expected OWNER/REPOSITORY.")
request = Request(
    f"https://api.github.com/repos/{repository}/releases/latest",
    headers={"Accept": "application/vnd.github+json", "User-Agent": "sl-cool-cli-installer"},
)
with urlopen(request, timeout=20) as response:
    release = json.load(response)
wheels = [asset["browser_download_url"] for asset in release.get("assets", [])
          if re.fullmatch(r"cli_anything_slcool-.+-py3-none-any\.whl", asset.get("name", ""))]
if len(wheels) != 1:
    raise SystemExit("Latest release must contain exactly one universal SL Cool CLI wheel.")
print(wheels[0])
PY
)"

echo "Installing SL Cool CLI from the latest GitHub Release..."
temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT HUP INT TERM
wheel_name="${wheel_url##*/}"
wheel_path="$temporary_directory/$wheel_name"
python3 - "$wheel_url" "$wheel_path" <<'PY'
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=60) as response, open(sys.argv[2], "wb") as wheel:
    while chunk := response.read(1024 * 1024):
        wheel.write(chunk)
PY
pipx install --force "$wheel_path"
echo "Installed. Run: sl-cool --help"
