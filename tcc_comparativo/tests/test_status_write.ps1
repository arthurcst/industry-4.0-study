. (Join-Path $PSScriptRoot '../scripts/resource_readiness.ps1')
$path = [System.IO.Path]::GetTempFileName()
try {
    Write-ExperimentStatus $path 'primeiro'
    if ((Get-Content -LiteralPath $path) -ne 'primeiro') { throw 'Falha ao gravar estado' }
    $file = [System.IO.File]::Open($path, 'Open', 'ReadWrite', 'None')
    try {
        $WarningPreference = 'SilentlyContinue'
        Write-ExperimentStatus $path 'bloqueado'
    } finally { $file.Dispose() }
    Write-ExperimentStatus $path 'recuperado'
    if ((Get-Content -LiteralPath $path) -ne 'recuperado') { throw 'Falha ao recuperar escrita do estado' }
    Write-Output 'Escrita de estado e recuperação verificadas'
} finally { Remove-Item -LiteralPath $path -ErrorAction SilentlyContinue }
