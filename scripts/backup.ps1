# Backup diario do banco do Radar (copia consistente e cifrada; as chaves NAO entram).
# Uso: scripts\backup.ps1
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$logs = Join-Path $raiz "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs "backup-$(Get-Date -Format yyyy-MM-dd).log"
$py = Join-Path $raiz ".venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}   # console padrao (OEM 850) estraga os acentos do log
"=== $(Get-Date -Format s) ===" | Out-File $log -Append -Encoding utf8
& $py -W ignore -m radar backup 2>&1 | Out-File $log -Append -Encoding utf8
"exit=$LASTEXITCODE" | Out-File $log -Append -Encoding utf8
