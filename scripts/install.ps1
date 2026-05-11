param(
    [string]$ApiKey = "",
    [switch]$Editable
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

Require-Command python

Remove-Item -Recurse -Force -LiteralPath "build", "dist", "src\huvcli.egg-info" -ErrorAction SilentlyContinue

$InstallArgs = @("-m", "pip", "install")
if ($Editable) {
    $InstallArgs += "-e"
}
else {
    $InstallArgs += "--upgrade"
}
$InstallArgs += "."

Write-Host "Installing Huv CLI from $RepoRoot"
python @InstallArgs
Remove-Item -Recurse -Force -LiteralPath "build", "dist", "src\huvcli.egg-info" -ErrorAction SilentlyContinue

if ($ApiKey) {
    [Environment]::SetEnvironmentVariable("HUV_API_KEY", $ApiKey, "User")
    $env:HUV_API_KEY = $ApiKey
    Write-Host "Saved HUV_API_KEY for this Windows user."
}
elseif (-not $env:HUV_API_KEY) {
    Write-Host "HUV_API_KEY not set. Set it later with:"
    Write-Host '  setx HUV_API_KEY "your-key"'
}

Write-Host ""
huv --version
Write-Host ""
Write-Host "Try:"
Write-Host '  huv "explain this folder"'
Write-Host "  huv chat"
Write-Host "  huv assets"
