param([switch]$RetomarCompleta, [ValidateRange(1, 3)][int]$PrimeiraReplica = 1, [switch]$AguardarRecursos,
      [switch]$NovaSerie, [string]$SeriesId, [string]$ManifestPath)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$status = Join-Path $root $(if ($NovaSerie) { 'logs/nova_serie_status.txt' } elseif ($RetomarCompleta -and $PrimeiraReplica -eq 3) { 'logs/repeticao_terceira_status.txt' } elseif ($RetomarCompleta -and $PrimeiraReplica -gt 1) { 'logs/retomada_restantes_status.txt' } elseif ($RetomarCompleta) { 'logs/retomada_status.txt' } else { 'logs/ciclo_status.txt' })
$bash = 'C:\Program Files\Git\bin\bash.exe'
. (Join-Path $PSScriptRoot 'resource_readiness.ps1')

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ExperimentPower {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
'@
if ([ExperimentPower]::SetThreadExecutionState([uint32]2147483649) -eq 0) {
    throw 'Nao foi possivel evitar a suspensao durante o ciclo.'
}

try {
    if ($AguardarRecursos) {
        $timer = [System.Diagnostics.Stopwatch]::StartNew()
        $stable = 0
        while ($timer.Elapsed.TotalMinutes -lt 30) {
            $memory = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
            $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
            $headroom = ($memory.CommitLimit - $memory.CommittedBytes) / 1MB
            if (Test-ResourceReadiness $memory.AvailableMBytes $headroom $cpu.LoadPercentage) { $stable++ } else { $stable = 0 }
            $message = "$(Get-Date -Format o) Aguardando recursos: CPU=$($cpu.LoadPercentage)% disponivel=$($memory.AvailableMBytes)MB margem_virtual=$([math]::Round($headroom))MB amostras_estaveis=$stable/3"
            Write-ExperimentStatus $status $message
            Write-Output $message
            if ($stable -ge 3) { break }
            Start-Sleep -Seconds 15
        }
        if ($stable -lt 3) { throw 'Replica nao iniciada: recursos permaneceram abaixo dos limites por 30 minutos.' }
    }
    if ($NovaSerie) {
        if ($SeriesId -notmatch '^serie_[a-zA-Z0-9_]+$' -or -not (Test-Path -LiteralPath $ManifestPath)) { throw 'Série ou manifesto inválido' }
        $env:EXPERIMENT_MANIFEST = $ManifestPath
        $env:EXPERIMENT_REUSE_IMAGES = '1'
        $env:EXPERIMENT_RUN_ROOT = "runs/$SeriesId/validacoes"
        $env:EXPERIMENT_TEST_DURATION_SECONDS = '60'
        $env:COLLECT_EXTRA_SECONDS = '360'
        $env:COLLECT_INTERVAL = '2'
        Remove-Item Env:COLLECT_DURATION_SECONDS -ErrorAction SilentlyContinue
        foreach ($profile in @('reduzida', 'intermediaria', 'completa')) {
            Write-ExperimentStatus $status "$(Get-Date -Format o) Validando planta $profile"
            & $bash start_experiment.sh $profile --seed 20261101
            if ($LASTEXITCODE -ne 0) { throw "Validacao de $profile falhou (codigo $LASTEXITCODE)." }
        }
        Remove-Item Env:EXPERIMENT_TEST_DURATION_SECONDS, Env:COLLECT_EXTRA_SECONDS, Env:COLLECT_INTERVAL
        $env:EXPERIMENT_RUN_ROOT = "runs/$SeriesId/replicas"
        Write-ExperimentStatus $status "$(Get-Date -Format o) Validacoes concluidas; iniciando as nove replicas"
        & $bash run_all_experiments.sh
    } elseif ($RetomarCompleta) {
        Remove-Item Env:EXPERIMENT_TEST_DURATION_SECONDS, Env:COLLECT_EXTRA_SECONDS, Env:COLLECT_INTERVAL -ErrorAction SilentlyContinue
        $env:EXPERIMENT_REUSE_IMAGES = '1'
        Write-ExperimentStatus $status "$(Get-Date -Format o) Iniciando planta completa a partir da replica $PrimeiraReplica"
        & $bash run_all_experiments.sh --workloads completa --start-run $PrimeiraReplica
    } else {
        $env:EXPERIMENT_TEST_DURATION_SECONDS = '60'
        $env:COLLECT_EXTRA_SECONDS = '360'
        $env:COLLECT_INTERVAL = '2'
        foreach ($profile in @('intermediaria', 'completa')) {
            Write-ExperimentStatus $status "$(Get-Date -Format o) Validando planta $profile"
            & $bash start_experiment.sh $profile --seed 20261101
            if ($LASTEXITCODE -ne 0) { throw "Validacao de $profile falhou (codigo $LASTEXITCODE)." }
        }
        Remove-Item Env:EXPERIMENT_TEST_DURATION_SECONDS, Env:COLLECT_EXTRA_SECONDS, Env:COLLECT_INTERVAL
        Write-ExperimentStatus $status "$(Get-Date -Format o) Validacoes concluidas; iniciando as nove execucoes"
        & $bash run_all_experiments.sh
    }
    if ($LASTEXITCODE -ne 0) { throw "Ciclo interrompido (codigo $LASTEXITCODE)." }
    Write-ExperimentStatus $status "$(Get-Date -Format o) Ciclo concluido e validado"
} catch {
    Write-ExperimentStatus $status "$(Get-Date -Format o) FALHA: $_"
    Write-Error $_
    exit 1
} finally {
    [void][ExperimentPower]::SetThreadExecutionState([uint32]2147483648)
}
