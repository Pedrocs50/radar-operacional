# Envia um e-mail pelo Outlook clássico (automação COM), descrito em um JSON.
# Chamado pelo Radar; não é para uso manual. Não imprime conteúdo, só o código de saída.
param([Parameter(Mandatory)][string]$Json)
try {
    $c = Get-Content -LiteralPath $Json -Raw -Encoding UTF8 | ConvertFrom-Json
    $ol = New-Object -ComObject Outlook.Application
    $m = $ol.CreateItem(0)
    $m.To = (@($c.para) -join ";")
    $m.Subject = $c.assunto
    if ($c.de) { $m.SentOnBehalfOfName = $c.de }   # caixa compartilhada (exige permissão Enviar como)
    $m.BodyFormat = 2
    foreach ($a in @($c.anexos)) { if ($a) { [void]$m.Attachments.Add($a) } }
    foreach ($i in @($c.inline)) {
        if ($i) {
            $att = $m.Attachments.Add($i.caminho)
            $att.PropertyAccessor.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F", $i.cid)
        }
    }
    $m.HTMLBody = Get-Content -LiteralPath $c.html -Raw -Encoding UTF8
    if ($c.modo -eq "rascunho") { $m.Save(); $m.Display() } else { $m.Send() }
    exit 0
} catch {
    exit 2
}
