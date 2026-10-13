# Aviso diario "estou vivo" ao dono. Se este e-mail nao chegar, algo parou (maquina, sessao, Outlook ou agendador).
# Uso: scripts\vida.ps1 cds_gfw_fora_da_area
param([Parameter(Mandatory)][string]$Tarefa)
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$logs = Join-Path $raiz "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs "vida-$Tarefa-$(Get-Date -Format yyyy-MM-dd).log"
$py = Join-Path $raiz ".venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # console padrao (OEM 850) estraga os acentos do log
"=== $(Get-Date -Format s) ===" | Out-File $log -Append -Encoding utf8
& $py -W ignore -m radar vida $Tarefa --enviar 2>&1 | Out-File $log -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File $log -Append -Encoding utf8
