param(
    [ValidateSet("1x", "2x", "4x")]
    [string]$Profile = "1x"
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Timestamp = Get-Date -Format "yyyy_MM_dd_HH_mm"
$ExperimentRunDir = "runs/experimento_${Profile}_${Timestamp}"

$BatchOutputHost = "./${ExperimentRunDir}/batches_output_${Profile}"
$BatchProcessedHost = "./${ExperimentRunDir}/batches_processed_${Profile}"
$MetricsHost = "./${ExperimentRunDir}/metrics"

New-Item -ItemType Directory -Force -Path (Join-Path $Root ($BatchOutputHost.TrimStart("./"))) | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root ($BatchProcessedHost.TrimStart("./"))) | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root ($MetricsHost.TrimStart("./"))) | Out-Null

function Set-EnvVar {
    param([string]$File, [string]$Key, [string]$Value)
    $lines = @()
    $found = $false
    if (Test-Path $File) {
        foreach ($line in Get-Content $File) {
            if ($line -match "^${Key}=") {
                $lines += "${Key}=${Value}"
                $found = $true
            } else {
                $lines += $line
            }
        }
    }
    if (-not $found) { $lines += "${Key}=${Value}" }
    $lines | Set-Content $File -Encoding utf8
}

foreach ($envFile in @("docker.env", ".env")) {
    $path = Join-Path $Root $envFile
    Set-EnvVar $path "EXPERIMENT_RUN_DIR" $ExperimentRunDir
    Set-EnvVar $path "BATCH_OUTPUT_HOST" $BatchOutputHost
    Set-EnvVar $path "BATCH_PROCESSED_HOST" $BatchProcessedHost
    Set-EnvVar $path "METRICS_HOST" $MetricsHost
}

Write-Host "📁 Run: $ExperimentRunDir"
Write-Host "   batches → $BatchOutputHost"
Write-Host "   processed → $BatchProcessedHost"
Write-Host "   metrics → $MetricsHost"
