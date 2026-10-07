# Cria a tarefa agendada do Windows (roda com o SEU usuário, quando logado, para
# usar o login do gcloud e o Credential Manager). Rode uma vez, no PowerShell.
# Uso: scripts\agendar.ps1 cds_novas_do_dia 08:00
param([Parameter(Mandatory)][string]$Tarefa, [string]$Hora = "08:00")
$script = Join-Path $PSScriptRoot "rodar.ps1"
$acao = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`" $Tarefa"
$gatilho = New-ScheduledTaskTrigger -Daily -At $Hora
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "Radar-$Tarefa" -Action $acao -Trigger $gatilho -Settings $cfg `
    -Description "Radar Operacional: $Tarefa" -Force
