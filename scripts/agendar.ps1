# Cria tarefas agendadas do Windows (rodam com o SEU usuario, quando logado, para usar o login do gcloud,
# o Credential Manager e o Outlook). Rode uma vez por tipo, no PowerShell.
#   Diario (boletim):          scripts\agendar.ps1 cds_novas_do_dia 08:00
#   Vigia (alerta quando a origem muda, a cada N min):
#                              scripts\agendar.ps1 cds_gfw_fora_da_area -VigiarACadaMin 5
#   Resumos nos horarios:      scripts\agendar.ps1 cds_gfw_fora_da_area -ResumoHoras 07:00,12:00,14:00,18:00
#   Aviso diario "estou vivo": scripts\agendar.ps1 cds_gfw_fora_da_area -VidaHora 06:45
#   Backup diario do banco:    scripts\agendar.ps1 cds_gfw_fora_da_area -BackupHora 03:00
#   Teste semanal do Teams:    scripts\agendar.ps1 cds_gfw_fora_da_area -CanarioHora 06:50   (segundas-feiras)
param([Parameter(Mandatory)][string]$Tarefa, [string]$Hora = "08:00", [int]$VigiarACadaMin = 0,
      [string[]]$ResumoHoras = @(), [string]$VidaHora = "", [string]$BackupHora = "", [string]$CanarioHora = "",
      [ValidateSet('teste','producao','operacional','real')][string]$Destino = 'teste')
$ResumoHoras = @($ResumoHoras | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
$argumento = "$Tarefa --destino $Destino"
if ($ResumoHoras.Count -gt 0) {
    $script = Join-Path $PSScriptRoot "resumo.ps1"
    $gatilho = @($ResumoHoras | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
    $nome = "Radar-resumo-$Tarefa"
} elseif ($VigiarACadaMin -gt 0) {
    $script = Join-Path $PSScriptRoot "vigiar.ps1"
    $gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $VigiarACadaMin)
    $nome = "Radar-vigia-$Tarefa"
} elseif ($VidaHora -ne "") {
    $script = Join-Path $PSScriptRoot "vida.ps1"
    $gatilho = New-ScheduledTaskTrigger -Daily -At $VidaHora
    $nome = "Radar-vida-$Tarefa"
} elseif ($CanarioHora -ne "") {
    $script = Join-Path $PSScriptRoot "canario.ps1"
    $gatilho = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At $CanarioHora
    $nome = "Radar-canario-$Tarefa"
} elseif ($BackupHora -ne "") {
    $script = Join-Path $PSScriptRoot "backup.ps1"
    $gatilho = New-ScheduledTaskTrigger -Daily -At $BackupHora
    $nome = "Radar-backup"
    $argumento = ""
} else {
    $script = Join-Path $PSScriptRoot "rodar.ps1"
    $gatilho = New-ScheduledTaskTrigger -Daily -At $Hora
    $nome = "Radar-$Tarefa"
}
$acao = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" $argumento"
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $cfg `
    -Description "Radar Operacional: $nome" -Force
