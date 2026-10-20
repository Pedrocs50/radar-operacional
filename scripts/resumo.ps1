# Envia o resumo periódico do estoque (e-mail completo + cartão no Teams) e registra o log.
# Uso: scripts\resumo.ps1 cds_gfw_fora_da_area -Destino teste
param([Parameter(Mandatory)][string]$Tarefa, [ValidateSet('teste','producao','operacional','real')][string]$Destino = 'teste')
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$logs = Join-Path $raiz "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs "resumo-$Tarefa-$(Get-Date -Format yyyy-MM-dd).log"
$py = Join-Path $raiz ".venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # console padrao (OEM 850) estraga os acentos do log
"=== $(Get-Date -Format s) ===" | Out-File $log -Append -Encoding utf8
& $py -W ignore -m radar resumo $Tarefa --real --forcar-inativa --destino $Destino 2>&1 | Out-File $log -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File $log -Append -Encoding utf8
