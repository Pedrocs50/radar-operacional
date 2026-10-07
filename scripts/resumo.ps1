# Envia o resumo periódico do estoque (e-mail completo + cartão no Teams) e registra o log.
# Uso: scripts\resumo.ps1 cds_gfw_fora_da_area
param([Parameter(Mandatory)][string]$Tarefa)
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$logs = Join-Path $raiz "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs "resumo-$Tarefa-$(Get-Date -Format yyyy-MM-dd).log"
$py = Join-Path $raiz ".venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
"=== $(Get-Date -Format s) ===" | Out-File $log -Append -Encoding utf8
& $py -W ignore -m radar resumo $Tarefa --real --forcar-inativa 2>&1 | Out-File $log -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File $log -Append -Encoding utf8
