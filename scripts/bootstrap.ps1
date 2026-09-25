param([switch]$Dev)
$ErrorActionPreference = 'Stop'
$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $repo
$python = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' }
}
$lock = if ($Dev) { 'requirements-dev.lock' } else { 'requirements.lock' }
& $python -m pip install -r $lock
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
& $python -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }
pnpm --dir frontend install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
pnpm --dir frontend build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
Write-Output 'Ready. Run .\scripts\start_local.ps1 and open http://127.0.0.1:8765'
