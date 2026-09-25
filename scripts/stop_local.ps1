$ErrorActionPreference = 'Stop'
$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$processFile = Join-Path $repo 'runtime\processes.json'
if (-not (Test-Path -LiteralPath $processFile)) { Write-Output 'No managed processes recorded.'; return }
$records = @(Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json)
foreach ($record in $records) {
    $process = Get-Process -Id $record.id -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if ($process.StartTime.ToUniversalTime().Ticks.ToString() -ne $record.started) { continue }
    $details = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.id)" -ErrorAction SilentlyContinue
    if ($details.CommandLine -notmatch 'jev_scout\.(cli|local_model)') { continue }
    Stop-Process -Id $process.Id
    Write-Output "Stopped Jev Scout $($record.kind)."
}
Set-Content -LiteralPath $processFile -Value '[]' -Encoding utf8
