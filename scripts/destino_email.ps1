# Script de conveniência para rodar o Radar em ambiente de teste ou produção sem mexer no YAML.
# Uso:
#   .\scripts\destino_email.ps1 -Task cds_gfw_fora_da_area -Destino teste -Comando run -Real
#   .\scripts\destino_email.ps1 -Task cds_gfw_fora_da_area -Destino producao -Comando resumo -Real -Canais "email:dono"
param(
    [Parameter(Mandatory = $true)][string]$Task,
    [ValidateSet("teste", "producao", "operacional", "real")][string]$Destino = "teste",
    [ValidateSet("run", "resumo")][string]$Comando = "run",
    [switch]$Real,
    [string]$Canais
)

$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$py = Join-Path $raiz ".venv\Scripts\python.exe"

$args = @("-W", "ignore", "-m", "radar", $Comando, $Task)
if ($Real) { $args += "--real" }
$args += "--destino"
$args += $Destino
if ($Canais) {
    $args += "--canais"
    $args += $Canais
}

& $py @args
exit $LASTEXITCODE
