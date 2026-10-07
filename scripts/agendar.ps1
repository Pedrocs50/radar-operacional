# Cria tarefas agendadas do Windows (rodam com o SEU usuário, quando logado, para usar o login do gcloud,
# o Credential Manager e o Outlook). Rode uma vez, no PowerShell.
#   Diário (boletim):          scripts\agendar.ps1 cds_novas_do_dia 08:00
#   Vigia (alerta quando a origem muda, a cada N min):
#                              scripts\agendar.ps1 cds_gfw_fora_da_area -VigiarACadaMin 5
#   Resumos nos horários:      scripts\agendar.ps1 cds_gfw_fora_da_area -ResumoHoras 07:00,12:00,14:00,18:00
param([Parameter(Mandatory)][string]$Tarefa, [string]$Hora = "08:00", [int]$VigiarACadaMin = 0,
      [string[]]$ResumoHoras = @())
$ResumoHoras = @($ResumoHoras | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
if ($ResumoHoras.Count -gt 0) {
    $script = Join-Path $PSScriptRoot "resumo.ps1"
    $gatilho = @($ResumoHoras | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
    $nome = "Radar-resumo-$Tarefa"
} elseif ($VigiarACadaMin -gt 0) {
    $script = Join-Path $PSScriptRoot "vigiar.ps1"
    $gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $VigiarACadaMin)
    $nome = "Radar-vigia-$Tarefa"
} else {
    $script = Join-Path $PSScriptRoot "rodar.ps1"
    $gatilho = New-ScheduledTaskTrigger -Daily -At $Hora
    $nome = "Radar-$Tarefa"
}
$acao = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" $Tarefa"
$cfg = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $cfg `
    -Description "Radar Operacional: $Tarefa" -Force
