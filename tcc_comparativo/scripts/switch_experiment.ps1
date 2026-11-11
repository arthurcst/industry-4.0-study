param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("reduzida", "intermediaria", "completa")]
    [string]$Profile
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Source = Join-Path $Root "docker.env.$Profile"
$DockerEnv = Join-Path $Root "docker.env"
$DotEnv = Join-Path $Root ".env"

if (-not (Test-Path $Source)) {
    Write-Error "Arquivo não encontrado: $Source"
    exit 1
}

Copy-Item -Path $Source -Destination $DockerEnv -Force
Copy-Item -Path $Source -Destination $DotEnv -Force

Write-Host "✅ Experimento $Profile ativado"
Write-Host "   docker.env e .env atualizados"
Write-Host ""
Write-Host "Próximos passos:"
Write-Host "  1. docker compose up -d postgres influxdb mosquitto grafana batch-consumer stream-consumer"
Write-Host "  2. python scripts/setup_experiment.py   (cria tabela PG + bucket Influx)"
Write-Host "  4. docker compose up -d --force-recreate batch-consumer stream-consumer"
Write-Host "  5. docker compose up sensor-generator"
Write-Host ""
Write-Host "Destinos:"
Select-String -Path $DockerEnv -Pattern "^(EXPERIMENT_LABEL|PG_TABLE|INFLUXDB_BUCKET|ACTIVE_ASSET_COUNT|EXPERIMENT_SEED|BATCH_OUTPUT_HOST)=" | ForEach-Object { Write-Host "   $($_.Line)" }
