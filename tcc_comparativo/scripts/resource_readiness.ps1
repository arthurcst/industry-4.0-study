function Test-ResourceReadiness([double]$AvailableMB, [double]$CommitHeadroomMB, [double]$CpuPercent) {
    return $AvailableMB -ge 512 -and $CommitHeadroomMB -ge 6144 -and $CpuPercent -le 50
}

function Write-ExperimentStatus([string]$Path, [string]$Message) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try { Set-Content -LiteralPath $Path -Value $Message -ErrorAction Stop; return }
        catch { if ($attempt -lt 5) { Start-Sleep -Milliseconds 300 } }
    }
    Write-Warning "Não foi possível atualizar o estado em $Path; veja o log do processo."
}
