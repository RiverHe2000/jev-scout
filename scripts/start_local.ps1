param(
    [int]$Port = 8765,
    [switch]$WithLocalModel,
    [string]$ModelPath = $env:JEV_SCOUT_LOCAL_MODEL_PATH,
    [string]$ModelPython = $env:JEV_SCOUT_MODEL_PYTHON,
    [int]$ModelPort = 8766
)
$ErrorActionPreference = 'Stop'
$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run .\scripts\bootstrap.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $repo 'frontend\dist\index.html'))) { throw 'Build the interface with pnpm --dir frontend build first.' }
$runtime = Join-Path $repo 'runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$processFile = Join-Path $runtime 'processes.json'
$records = @()
if (Test-Path -LiteralPath $processFile) {
    $records = @(Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json)
}
function Test-Service([string]$Url, [string]$ExpectedField, [string]$ExpectedValue) {
    try {
        $value = Invoke-RestMethod -Uri $Url -TimeoutSec 2
        return $value.$ExpectedField -eq $ExpectedValue
    } catch { return $false }
}
function Wait-Service([string]$Url, [string]$ExpectedField, [string]$ExpectedValue, [System.Diagnostics.Process]$Process, [int]$Seconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) { throw "Service exited. Check logs in $runtime" }
        if (Test-Service $Url $ExpectedField $ExpectedValue) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "Service did not become ready. Check logs in $runtime"
}
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $repo 'src'
# A desktop terminal may predate a key added to Windows user environment settings.
# Refresh only the named provider variable when this process has no value.
if ([string]::IsNullOrWhiteSpace($env:OPENROUTER_API_KEY)) {
    $env:OPENROUTER_API_KEY = [Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY', 'User')
}
try {
    if ($WithLocalModel) {
        if (-not $ModelPath) {
            $ModelPath = & $python -c "from dotenv import dotenv_values; from jev_scout.config import PROJECT_ROOT; print(dotenv_values(PROJECT_ROOT / '.env').get('JEV_SCOUT_LOCAL_MODEL_PATH') or '')"
            if ($LASTEXITCODE -ne 0) { throw 'Could not read the local model path configuration.' }
        }
        if (-not $ModelPath) { throw 'Provide -ModelPath pointing to existing Qwen weights.' }
        $modelResolved = (Resolve-Path -LiteralPath $ModelPath).Path
        if (-not $ModelPython) { $ModelPython = $python }
        if (-not (Test-Path -LiteralPath $ModelPython)) { throw 'ModelPython must point to a Python installation with CUDA PyTorch and Transformers.' }
        $env:JEV_SCOUT_LLM_BASE_URL = "http://127.0.0.1:$ModelPort/v1"
        $env:JEV_SCOUT_LLM_MODEL = 'qwen3-4b'
        $env:JEV_SCOUT_LLM_PRICE_PER_MILLION_INPUT = '0'
        if (-not (Test-Service "http://127.0.0.1:$ModelPort/health" 'model' 'qwen3-4b')) {
            $modelProcess = Start-Process -FilePath $ModelPython -ArgumentList @('-m', 'jev_scout.local_model', '--model-path', ('"{0}"' -f $modelResolved), '--port', "$ModelPort") -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'model.log') -RedirectStandardError (Join-Path $runtime 'model-error.log')
            $records += @{ kind='model'; id=$modelProcess.Id; started=$modelProcess.StartTime.ToUniversalTime().Ticks.ToString() }
            ConvertTo-Json -InputObject @($records) | Set-Content -LiteralPath $processFile -Encoding utf8
            Wait-Service "http://127.0.0.1:$ModelPort/health" 'model' 'qwen3-4b' $modelProcess 180
        }
    }
    $env:JEV_SCOUT_PORT = "$Port"
    if (Test-Service "http://127.0.0.1:$Port/api/health" 'version' '0.1.0') {
        Write-Output "Jev Scout is already running: http://127.0.0.1:$Port"
        Write-Output 'If you changed .env, stop and restart the application to reload it.'
        return
    }
    $appProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'jev_scout.cli', 'serve', '--port', "$Port") -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'app.log') -RedirectStandardError (Join-Path $runtime 'app-error.log')
    $records += @{ kind='app'; id=$appProcess.Id; started=$appProcess.StartTime.ToUniversalTime().Ticks.ToString() }
    ConvertTo-Json -InputObject @($records) | Set-Content -LiteralPath $processFile -Encoding utf8
    Wait-Service "http://127.0.0.1:$Port/api/health" 'version' '0.1.0' $appProcess 30
    Write-Output "Jev Scout is ready: http://127.0.0.1:$Port"
    Write-Output 'To stop: .\scripts\stop_local.ps1'
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
