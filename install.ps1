$ErrorActionPreference = "Stop"

$Repository = $env:SLCOOL_CLI_REPOSITORY
if ([string]::IsNullOrWhiteSpace($Repository) -or $Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw "Set SLCOOL_CLI_REPOSITORY to OWNER/REPOSITORY before running the installer."
}

$Python = Get-Command py -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $Python) {
    throw "Python 3.10 or newer is required. Install Python, then rerun this installer."
}
$PythonVersion = (& $Python.Source --version 2>&1 | Out-String).Trim()
if ($PythonVersion -notmatch 'Python (\d+)\.(\d+)') {
    throw "Could not determine the Python version from '$PythonVersion'."
}
if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 10)) {
    throw "Python 3.10 or newer is required; found '$PythonVersion'."
}
if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
    throw "pipx is required. Install it with 'py -m pip install --user pipx', then run 'py -m pipx ensurepath' and reopen PowerShell."
}

$Release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/latest" -Headers @{ "User-Agent" = "sl-cool-cli-installer" }
$Wheels = @($Release.assets | Where-Object { $_.name -match '^cli_anything_slcool-.+-py3-none-any\.whl$' })
if ($Wheels.Count -ne 1) {
    throw "Latest release must contain exactly one universal SL Cool CLI wheel."
}

Write-Host "Installing SL Cool CLI from the latest GitHub Release..."
$TemporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("slcool-cli-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $TemporaryDirectory | Out-Null
$WheelPath = Join-Path $TemporaryDirectory $Wheels[0].name
try {
    Invoke-WebRequest -Uri $Wheels[0].browser_download_url -OutFile $WheelPath
    pipx install --force $WheelPath
    if ($LASTEXITCODE -ne 0) {
        throw "pipx installation failed with exit code $LASTEXITCODE."
    }
} finally {
    Remove-Item -LiteralPath $TemporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "Installed. Run: sl-cool --help"
