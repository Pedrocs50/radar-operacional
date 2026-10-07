"""Mensagens de EXEMPLO para ver como ficam os cartões e o e-mail, sem usar dado operacional.

Usa as mesmas funções que montam as mensagens reais (sinais, movimentos, resumo, cartões do Teams), mas com um
estoque inventado. Todo título leva "[EXEMPLO]" e o aviso de sandbox/teste aparece no cartão.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .channels import email_conteudo, teams_webhook
from .engine import sinais
from .engine.resumo import montar_mensagem_resumo
from .engine.runner import montar_mensagem, montar_mensagem_movimentos


def _cd(nota, modelo, serial, origem, atual, dias, sem_fluxo, fim, resp, problema, area="Manutenção Hangar"):
    return {
        "Descricao_do_Tipo_de_Defeito": "Defeito de exemplo A" if int(nota) % 2 else "Defeito de exemplo B",
        "Nota_QM": nota, "Dias_em_Aberto": dias, "Dias_sem_Fluxo": sem_fluxo, "Faixa_de_Atraso": "x",
        "Modelo_Aeronave": modelo, "Serial_Exibicao": serial, "Descricao_CT_Origem": origem,
        "Descricao_CT_Atual": atual, "Descricao_Area_Responsavel": area,
        "Nome_do_Responsavel_Proxima_Acao": resp, "Responsavel_Proxima_Acao": resp, "PN": "PN-EXEMPLO",
        "Descricao_do_Problema": problema, "Fluxo": "Aguardando análise", "Data_Plan_Final": fim,
        "Hora_Plan_Final": time(17, 0), "Data_da_Nota": date.today(),
    }


def estoque_exemplo() -> list[dict]:
    hoje = date.today()
    return [
        _cd("900001", "EJETS E2", "19000123", "Junção", "Hangar de Entrega", 35, 15, hoje - timedelta(days=3), "Fulano de Tal",
            "Texto de exemplo do problema, longo o bastante para mostrar como o cartão quebra a linha e corta o excesso. " * 2),
        _cd("900002", "EJETS E1", "17000456", "Pré-Pintura", "Pintura Externa", 12, 2, None, "", "Outro problema de exemplo"),
        _cd("900003", "EJETS E2", "19000789", "Junção", "Hangar de Entrega", 6, 8, hoje + timedelta(days=5), "Beltrano",
            "Problema de exemplo com plano em dia"),
        _cd("900004", "EJETS E2", "19000800", "Pintura Final E2", "Hangar de Entrega", 1, 0, hoje + timedelta(days=9),
            "Sicrano", "CD que acabou de chegar (exemplo)"),
    ]


def exemplos(task: dict, settings: dict) -> dict[str, dict]:
    """{nome: mensagem}. Os cartões vêm da própria configuração da tarefa (campos, rótulos, sinais)."""
    agora = datetime.now(timezone.utc)
    est = estoque_exemplo()
    nova = est[-1]
    sandbox = settings.get("sandbox", {})
    cfg = task.get("sinais", {})
    s = sinais.calcular(est, cfg, "Nota_QM") if cfg else {}
    entradas = [{"quando": (agora - timedelta(days=d)).isoformat(timespec="seconds"), "chave": e["Nota_QM"],
                 cfg.get("vazamento", {}).get("origem", "Descricao_CT_Origem"): e["Descricao_CT_Origem"]}
                for d, e in zip((1, 4, 12, 25), est)]
    extra = {"sinais": s, "marcas": sinais.marcas(s)} if s else {}
    if cfg.get("vazamento", {}).get("ativo"):
        extra["vazamento"] = sinais.vazamento(est, entradas, [{"quando": entradas[0]["quando"], "origem": "Junção"}],
                                              cfg, "Nota_QM")

    def exemplo(m: dict, titulo: str) -> dict:
        m["titulo"] = f"[EXEMPLO] {titulo}"
        m["sandbox"] = True
        return m

    alerta = montar_mensagem(task, [nova], len(est), False, sandbox)
    alerta.update({"campo_chave": "Nota_QM", **extra})

    eventos = [
        {"tipo": "resolvida", "nota": "800010", "resumo": "EJETS E2 · 19000111", "dias": 21, "ct_antes": "Hangar de Entrega"},
        {"tipo": "voltou_gfw", "nota": "800011", "resumo": "EJETS E1 · 17000222", "ct_depois": "Junção"},
        {"tipo": "mudou_ct", "nota": "900001", "resumo": "EJETS E2 · 19000123", "ct_antes": "Pintura Externa",
         "ct_depois": "Hangar de Entrega"},
        {"tipo": "saiu_criterio", "nota": "800012", "resumo": "EJETS E2 · 19000333", "ct_depois": "Hangar de Entrega"},
        {"tipo": "nao_encontrada", "nota": "800013", "resumo": ""},
    ]
    movimentos = montar_mensagem_movimentos(task, eventos, sandbox)
    resumo = montar_mensagem_resumo(task, est, [nova], eventos, 4, "as 14h00 de ontem", agora, False, sandbox)
    resumo.update(extra)
    from .engine import paineis

    resumo.update(paineis.preparar(task, est))
    if task.get("indicadores", {}).get("ativo"):
        from .engine import indicadores

        def q(d):
            return (agora - timedelta(days=d)).isoformat(timespec="seconds")

        resumo.update({"indicadores": indicadores.calcular(
            [{"quando": q(d)} for d in (0, 1, 2, 3, 8, 9, 15, 16, 17, 22, 30, 31, 38, 45)],
            [{"quando": q(d), "dias": 5 + d} for d in (0, 2, 4, 9, 10, 18, 23, 29, 40, 41, 47)], agora)})
    resumo["email"] = task.get("email", {})

    falha = {"tipo": "sistema", "titulo": "Radar com instabilidade", "marca": "RADAR OPERACIONAL", "nivel": "atencao",
             "texto": "O robô de alertas está com um problema técnico e já está sendo verificado. "
                      "Alertas novos podem atrasar. Avisaremos quando voltar ao normal."}
    volta = {**falha, "titulo": "Radar voltou ao normal", "nivel": "ok",
             "texto": "O robô de alertas voltou a funcionar. Alertas que ficaram pendentes serão enviados."}
    return {
        "1_alerta_cd_nova": exemplo(alerta, "Nova CD da GFW fora da área"),
        "2_movimentacao": exemplo(movimentos, "Movimentação de CDs da GFW"),
        "3_resumo": exemplo(resumo, "Resumo das CDs da GFW fora da área"),
        "4_robo_com_problema": exemplo(falha, "Radar com instabilidade"),
        "5_robo_voltou": exemplo(volta, "Radar voltou ao normal"),
    }


def salvar(exemplos_: dict[str, dict], pasta: Path, task: dict) -> dict[str, str]:
    """Grava o JSON de cada cartão e o e-mail de exemplo (resumo)."""
    pasta.mkdir(parents=True, exist_ok=True)
    saida = {}
    for nome, m in exemplos_.items():
        payload = teams_webhook.montar_payload(m)
        cartao = payload["attachments"][0]["content"]
        destino = pasta / f"cartao_{nome}.json"
        destino.write_text(json.dumps(cartao, ensure_ascii=False, indent=2), encoding="utf-8")
        kb = len(json.dumps(payload, ensure_ascii=False).encode()) / 1024
        saida[f"cartão {nome} ({kb:.1f} KB de ~24 KB)"] = str(destino)
    saida["visualizador de cartões (abrir no navegador)"] = str(_visualizador(exemplos_, pasta))
    saida["e-mail de exemplo (resumo)"] = str(email_conteudo.gerar_previa(exemplos_["3_resumo"], pasta, "exemplo"))
    return saida


_PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Cartões de exemplo do Radar</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;background:#f3f2f1;margin:0;padding:16px}
h1{font-size:18px}h2{font-size:14px;color:#605e5c;margin:24px 0 6px}
.cartao{background:#fff;border:1px solid #e1dfdd;border-radius:6px;max-width:520px;padding:0;overflow:hidden}
.aviso{font-size:12px;color:#605e5c;max-width:520px}</style>
<script src="https://unpkg.com/adaptivecards@2.11.3/dist/adaptivecards.min.js"></script></head>
<body><h1>Cartões de exemplo (dados inventados)</h1>
<p class="aviso">Aproximação do que aparece no Teams: a fonte e os espaçamentos podem variar um pouco.
O tamanho de cada cartão (KB) está no terminal; o limite do webhook é ~28 KB.</p>
<div id="lista"></div>
<script>
const cartoes = __CARTOES__;
const lista = document.getElementById("lista");
for (const [nome, cartao] of Object.entries(cartoes)) {
  const h = document.createElement("h2"); h.textContent = nome; lista.appendChild(h);
  const caixa = document.createElement("div"); caixa.className = "cartao"; lista.appendChild(caixa);
  try {
    const ac = new AdaptiveCards.AdaptiveCard();
    const est = (bg) => ({backgroundColor: bg, foregroundColors: {default: {default: "#242424", subtle: "#616161"},
      accent: {default: "#0F6CBD", subtle: "#0F6CBD"}, good: {default: "#107C10", subtle: "#107C10"},
      warning: {default: "#BC4B09", subtle: "#BC4B09"}, attention: {default: "#C50F1F", subtle: "#C50F1F"}}});
    ac.hostConfig = new AdaptiveCards.HostConfig({fontFamily: "Segoe UI, Arial, sans-serif",
      containerStyles: {default: est("#FFFFFF"), emphasis: est("#F5F5F5"), accent: est("#E5F1FB"),
        good: est("#E6F4E6"), attention: est("#FDE7E9"), warning: est("#FFF4CE")}});
    ac.parse(cartao); caixa.appendChild(ac.render());
  } catch (e) { caixa.textContent = "Não foi possível desenhar este cartão: " + e; }
}
</script></body></html>"""


def _visualizador(exemplos_: dict[str, dict], pasta: Path) -> Path:
    cartoes = {n: teams_webhook.montar_payload(m)["attachments"][0]["content"] for n, m in exemplos_.items()}
    destino = pasta / "cartoes.html"
    destino.write_text(_PAGINA.replace("__CARTOES__", json.dumps(cartoes, ensure_ascii=False)), encoding="utf-8")
    return destino
