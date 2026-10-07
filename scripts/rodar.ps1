# Executa uma tarefa do Radar de forma real e registra a saída em data\logs.
# Uso: scripts\rodar.ps1 cds_novas_do_dia
param([Parameter(Mandatory)][string]$Tarefa)
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$logs = Join-Path $raiz "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs "$Tarefa-$(Get-Date -Format yyyy-MM-dd).log"
$py = Join-Path $raiz ".venv\Scripts\python.exe"
"=== $(Get-Date -Format s) run ===" | Out-File $log -Append -Encoding utf8
& $py -W ignore -m radar run $Tarefa --real --forcar-inativa *>> $log
"exit=$LASTEXITCODE" | Out-File $log -Append -Encoding utf8
& $py -m radar limpar *>> $log
