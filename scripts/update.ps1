$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (Test-Path ".git") {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Host "Fetching latest repo changes..."
        git pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Git update skipped or failed. Continuing with local files."
        }
    }
    else {
        Write-Host "Git not found. Skipping repo update."
    }
}

Remove-Item -Recurse -Force -LiteralPath "build", "dist", "src\huvcli.egg-info" -ErrorAction SilentlyContinue

Write-Host "Reinstalling Huv CLI..."
python -m pip install --upgrade .
Remove-Item -Recurse -Force -LiteralPath "build", "dist", "src\huvcli.egg-info" -ErrorAction SilentlyContinue

Write-Host ""
huv --version
Write-Host "Update done."
