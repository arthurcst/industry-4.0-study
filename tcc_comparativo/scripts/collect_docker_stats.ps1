param(
    [double]$Interval = 0.5,
    [int]$ExtraSeconds = 600
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvFile = Join-Path $Root "docker.env"

function Read-DockerEnv {
    param([string]$Path)
    $vars = @{}
    if (Test-Path $Path) {
        Get-Content $Path | ForEach-Object {
            if ($_ -match '^\s*([^#=]+)=(.*)$') {
                $vars[$Matches[1].Trim()] = $Matches[2].Trim()
            }
        }
    }
    return $vars
}

$envVars = Read-DockerEnv $EnvFile
if ($envVars["METRICS_HOST"]) {
    $MetricsDir = Join-Path $Root ($envVars["METRICS_HOST"].TrimStart("./"))
} elseif ($envVars["EXPERIMENT_RUN_DIR"]) {
    $MetricsDir = Join-Path $Root (Join-Path $envVars["EXPERIMENT_RUN_DIR"] "metrics")
} else {
    $MetricsDir = Join-Path $Root "metrics"
}
$Label = if ($envVars["EXPERIMENT_LABEL"]) { $envVars["EXPERIMENT_LABEL"] } else { "1x" }
$ExecutionTime = if ($envVars["EXECUTION_TIME_SECONDS"]) { [int]$envVars["EXECUTION_TIME_SECONDS"] } else { 3600 }
$Duration = if ($env:COLLECT_DURATION_SECONDS) { [int]$env:COLLECT_DURATION_SECONDS } else { $ExecutionTime + $ExtraSeconds }
$OutFile = Join-Path $MetricsDir "docker_stats_$Label.csv"

New-Item -ItemType Directory -Force -Path $MetricsDir | Out-Null
"timestamp,experiment,container_id,name,cpu_perc,mem_usage,mem_perc,net_io,block_io,pids" | Set-Content $OutFile -Encoding utf8

Write-Host "📊 Coletando Docker stats → $OutFile"
Write-Host "   Perfil: $Label | Intervalo: ${Interval}s | Duração: ${Duration}s"
Write-Host "   Ctrl+C para parar antes do tempo"

$endTime = (Get-Date).AddSeconds($Duration)

while ((Get-Date) -lt $endTime) {
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

    Push-Location $Root
  try {
        $ids = (docker compose ps -q 2>$null)
    } finally {
        Pop-Location
    }

    if (-not $ids) {
        $ids = docker ps -q --filter "name=batch_consumer" --filter "name=stream_consumer" `
            --filter "name=sensor_generator" --filter "name=postgres" `
            --filter "name=influxdb" --filter "name=mosquitto" --filter "name=grafana"
    }

    if ($ids) {
        $stats = docker stats --no-stream --format "{{.Container}},{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}" $ids
        foreach ($line in $stats) {
            if ($line) {
                "$timestamp,$Label,$line" | Add-Content $OutFile -Encoding utf8
            }
        }
    }

    Start-Sleep -Seconds $Interval
}

Write-Host "✅ Coleta finalizada (${Duration}s)"
