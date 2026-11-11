param(
    [ValidateSet("reduzida", "intermediaria", "completa")]
    [string]$Profile = "completa"
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Timestamp = Get-Date -Format "yyyy_MM_dd_HH_mm_ss"
$RunRoot = if ($env:EXPERIMENT_RUN_ROOT) { $env:EXPERIMENT_RUN_ROOT } else { 'runs' }
if ($RunRoot -notmatch '^runs(/[a-zA-Z0-9_]+)*$') { throw 'Diretório de execuções inválido' }
$ExperimentRunDir = "${RunRoot}/experimento_${Profile}_${Timestamp}"
$RunSuffix = $Timestamp.Replace('_', '')
New-Item -ItemType Directory -Force -Path (Join-Path $Root $RunRoot) | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Root $ExperimentRunDir) -ErrorAction Stop | Out-Null

$BatchOutputHost = "./${ExperimentRunDir}/batches_output_${Profile}"
$BatchProcessedHost = "./${ExperimentRunDir}/batches_processed_${Profile}"
$MetricsHost = "./${ExperimentRunDir}/metrics"

New-Item -ItemType Directory -Force -Path (Join-Path $Root ($BatchOutputHost.TrimStart("./"))) | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root ($BatchProcessedHost.TrimStart("./"))) | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root ($MetricsHost.TrimStart("./"))) | Out-Null

foreach ($name in @("latency_batch.csv", "latency_stream.csv")) {
    $path = Join-Path $Root ($MetricsHost.TrimStart("./")) $name
    if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType File -Path $path | Out-Null }
}

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
    Set-EnvVar $path "PG_TABLE" "sensor_data_${Profile}_${RunSuffix}"
    Set-EnvVar $path "INFLUXDB_BUCKET" "iot_stream_${Profile}_${RunSuffix}"
    Set-EnvVar $path "MQTT_DATA_VOLUME" "tcc_mqtt_${Profile}_${RunSuffix}"
}

Write-Host "📁 Run: $ExperimentRunDir"
Write-Host "   batches → $BatchOutputHost"
Write-Host "   processed → $BatchProcessedHost"
Write-Host "   metrics → $MetricsHost"
