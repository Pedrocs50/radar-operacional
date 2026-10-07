# Verificação rápida: só roda a consulta pesada se a tabela de origem foi atualizada.
# Uso: scripts\vigiar.ps1 cds_gfw_fora_da_area
param([Parameter(Mandatory)][string]$Tarefa)
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$logs = Join-Path $raiz "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs "vigia-$Tarefa-$(Get-Date -Format yyyy-MM-dd).log"
$py = Join-Path $raiz ".venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
"=== $(Get-Date -Format s) ===" | Out-File $log -Append -Encoding utf8
& $py -W ignore -m radar vigiar $Tarefa --forcar-inativa 2>&1 | Out-File $log -Append -Encoding utf8
& $py -m radar limpar 2>&1 | Out-Null
