. (Join-Path $PSScriptRoot '../scripts/resource_readiness.ps1')
if (-not (Test-ResourceReadiness 512 6144 50)) { throw 'Limites aceitáveis foram rejeitados' }
if (Test-ResourceReadiness 511 6144 50) { throw 'Memória física insuficiente foi aceita' }
if (Test-ResourceReadiness 512 6143 50) { throw 'Margem virtual insuficiente foi aceita' }
if (Test-ResourceReadiness 512 6144 51) { throw 'CPU acima do limite foi aceita' }
Write-Output 'Verificação das condições de início passou'
