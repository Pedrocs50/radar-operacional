"""Canal Teams via webhook do Workflows.

O Python monta um Adaptive Card e faz um POST na URL do workflow
("Postar em um canal quando uma solicitação de webhook for recebida").
Toda a lógica fica no código; o workflow só publica o que recebe.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime

from .base import ErroDeEnvio

LIMITE_BYTES = 24_000   # o Teams recusa cartões acima de ~28 KB; ficamos abaixo
MAX_ITENS = 10          # itens detalhados no cartão; o resto vira "+N não exibidos"
MAX_TEXTO = 140         # corta textos longos para o cartão ficar legível
AVISO = ("Aviso auxiliar gerado automaticamente. Não substitui o controle oficial "
         "nem o SAP. Em caso de divergência, vale o sistema oficial.")


def _cortar(valor, limite: int = MAX_TEXTO) -> str:
    texto = " ".join(str(valor).split())
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def _bloco(texto: str, **extra) -> dict:
    return {"type": "TextBlock", "text": texto, "wrap": True, **extra}


def _corpo_alerta(m: dict, max_itens: int) -> list[dict]:
    colunas = m["colunas"]
    rotulos = m.get("rotulos", {})
    itens = m["itens"]
    corpo = [{
        "type": "Container", "style": "attention", "bleed": True,
        "items": [
            _bloco(m.get("marca", "RADAR OPERACIONAL"), size="Small", weight="Bolder", spacing="None"),
            _bloco(m["titulo"], size="Large", weight="Bolder", spacing="Small"),
        ],
    }, _bloco(
        f"Dados de {m['dados_de']} · {m['n_novos']} novo(s) de {m['n_itens']} na leitura",
        isSubtle=True, spacing="Small",
    )]
    if m.get("sandbox"):
        corpo.append(_bloco("SANDBOX: mensagem de teste", color="Warning", size="Small"))

    for item in itens[:max_itens]:
        # as 3 primeiras colunas viram o título do item; as demais, pares nome/valor
        cabecalho = " · ".join(_cortar(item.get(c, ""), 40) for c in colunas[:3])
        fatos = [
            {"title": rotulos.get(c, c), "value": _cortar(item.get(c, ""))}
            for c in colunas[3:] if str(item.get(c, "")).strip()
        ]
        conteudo = [_bloco(cabecalho, weight="Bolder")]
        tags = m.get("marcas", {}).get(str(item.get(m.get("campo_chave"))), [])
        if tags:
            fatos.append({"title": "Atenção", "value": " · ".join(tags)})
        if fatos:
            conteudo.append({"type": "FactSet", "facts": fatos})
        corpo.append({"type": "Container", "separator": True, "spacing": "Medium", "items": conteudo})

    ocultos = len(itens) - max_itens
    if ocultos > 0:
        corpo.append(_bloco(f"+ {ocultos} item(ns) não exibido(s).", isSubtle=True))
    corpo.append(_bloco(AVISO, size="Small", isSubtle=True, separator=True))
    return corpo


def _faixa(m: dict, estilo: str) -> dict:
    return {"type": "Container", "style": estilo, "bleed": True, "items": [
        _bloco(m.get("marca", "RADAR OPERACIONAL"), size="Small", weight="Bolder", spacing="None"),
        _bloco(m["titulo"], size="Large", weight="Bolder", spacing="Small"),
    ]}


GRUPOS_MOVIMENTO = [
    ("resolvida", "✅ Resolvidas"),
    ("voltou_gfw", "↩️ Voltaram para a GFW"),
    ("mudou_ct", "🔄 Mudaram de CT"),
    ("saiu_criterio", "⚠️ Continuam abertas, mas saíram das premissas do TURNBACK"),
    ("nao_encontrada", "❓ Não localizadas na base"),
]


def _linha_evento(e: dict) -> str:
    base = f"Nota {e['nota']}" + (f" · {e['resumo']}" if e.get("resumo") else "")
    if e["tipo"] == "mudou_ct":
        return base + f" — {e.get('ct_antes') or '?'} → {e.get('ct_depois') or '?'}"
    if e["tipo"] == "resolvida" and e.get("dias"):
        return base + f" — ficou {e['dias']} dia(s) em aberto"
    if e["tipo"] in ("voltou_gfw", "saiu_criterio") and e.get("ct_depois"):
        return base + f" — agora em {e['ct_depois']}"
    return base


def _corpo_movimentos(m: dict, max_itens: int) -> list[dict]:
    resolvidas = any(e["tipo"] in ("resolvida", "voltou_gfw") for e in m["eventos"])
    corpo = [_faixa(m, "good" if resolvidas else "warning"),
             _bloco(f"Dados de {m['dados_de']}", isSubtle=True, spacing="Small")]
    if m.get("sandbox"):
        corpo.append(_bloco("SANDBOX: mensagem de teste", color="Warning", size="Small"))
    restante = max_itens
    for tipo, rotulo in GRUPOS_MOVIMENTO:
        grupo = [e for e in m["eventos"] if e["tipo"] == tipo]
        if not grupo:
            continue
        linhas = [_linha_evento(e) for e in grupo[:restante]]
        restante = max(restante - len(linhas), 0)
        itens = [_bloco(f"{rotulo} ({len(grupo)})", weight="Bolder")] + [_bloco(l) for l in linhas]
        if len(grupo) > len(linhas):
            itens.append(_bloco(f"+ {len(grupo) - len(linhas)} não exibida(s).", isSubtle=True))
        corpo.append({"type": "Container", "separator": True, "spacing": "Medium", "items": itens})
    corpo.append(_bloco(AVISO, size="Small", isSubtle=True, separator=True))
    return corpo


def _blocos_sinais(m: dict, max_itens: int) -> list[dict]:
    """Pontos de atenção (paradas, plano, responsável) e CTs de origem que mais geram pendência."""
    blocos = []
    sinais = m.get("sinais") or {}
    ativos = [(nome, sinais[nome]) for nome in ("parada", "plano_vencido", "sem_plano", "sem_responsavel")
              if nome in sinais]
    if ativos:
        linhas = [_bloco("Pontos de atenção", weight="Bolder")]
        for nome, s in ativos:
            extra = f" há {s['limite']}+ dias" if nome == "parada" else ""
            linhas.append(_bloco(f"{s['icone']} {s['titulo']}{extra}: {s['total']}"))
            for i in s["itens"][:max(1, max_itens // 3)]:
                linhas.append(_bloco(f"Nota {i['nota']} · {i['resumo']} — {i['detalhe']}", size="Small", isSubtle=True,
                                     spacing="None"))
            if s["total"] > max(1, max_itens // 3):
                linhas.append(_bloco(f"+ {s['total'] - max(1, max_itens // 3)} no e-mail e no Excel.", size="Small",
                                     isSubtle=True, spacing="None"))
        blocos.append({"type": "Container", "separator": True, "items": linhas})
    if m.get("vazamento"):
        linhas = [_bloco("De quais CTs da GFW as CDs mais saem", weight="Bolder")]
        for v in m["vazamento"][:6]:
            linhas.append(_bloco(f"{v['ct']}: {v['abertas']} aberta(s) · entraram {v['entraram_7d']} em 7d e "
                                 f"{v['entraram_30d']} em 30d · {v['resolvidas_30d']} resolvida(s) em 30d",
                                 size="Small", spacing="None"))
        blocos.append({"type": "Container", "separator": True, "items": linhas})
    return blocos


def _corpo_resumo(m: dict, max_itens: int) -> list[dict]:
    g, p = m["geral"], m["periodo"]
    fatos = [{"title": "CDs abertas fora da GFW", "value": str(g["total"])}]
    if g.get("mais_antiga_dias") is not None:
        fatos.append({"title": "Mais antiga", "value": f"{g['mais_antiga_dias']} dias (nota {g['mais_antiga_nota']})"})
    if g.get("media_dias") is not None:
        fatos.append({"title": "Média em aberto", "value": f"{g['media_dias']} dias"})
    if g.get("faixas"):
        fatos.append({"title": "Por faixa", "value": " · ".join(f"{f}: {n}" for f, n in g["faixas"])})
    if g.get("modelos"):
        fatos.append({"title": "Por modelo", "value": " · ".join(f"{mo}: {n}" for mo, n in g["modelos"])})
    desde = [{"title": "Novas", "value": str(p["novas"])},
             {"title": "Resolvidas", "value": str(p["resolvida"] + p["voltou_gfw"])},
             {"title": "Mudaram de CT", "value": str(p["mudou_ct"])}]
    corpo = [_faixa(m, "accent"),
             _bloco(f"Dados de {m['dados_de']} · desde {m['desde_texto']}", isSubtle=True, spacing="Small")]
    if m.get("sandbox"):
        corpo.append(_bloco("SANDBOX: mensagem de teste", color="Warning", size="Small"))
    corpo.append({"type": "FactSet", "facts": fatos})
    corpo.append({"type": "Container", "separator": True, "items": [
        _bloco("Desde o último resumo", weight="Bolder"), {"type": "FactSet", "facts": desde}]})
    if m.get("resolvidas_7d") is not None:
        corpo.append(_bloco(f"Resolvidas nos últimos 7 dias: {m['resolvidas_7d']}", isSubtle=True))
    for p in (m.get("paineis") or [])[:1]:   # só o primeiro painel (onde estão): imagem não cabe no webhook
        corpo.append({"type": "Container", "separator": True, "items": [_bloco(p["titulo"], weight="Bolder")] + [
            _bloco(f"{r}: {n}", size="Small", spacing="None") for r, n, _ in p["linhas"][:5]]})
    ind = m.get("indicadores")
    if ind:
        j7, j30 = ind["janelas"]["7d"], ind["janelas"]["30d"]
        tempo = f"{j30['tempo_medio']} dias" if j30["tempo_medio"] is not None else "-"
        corpo.append({"type": "Container", "separator": True, "items": [
            _bloco("Resultados", weight="Bolder"),
            {"type": "FactSet", "facts": [
                {"title": "Últimos 7 dias", "value": f"entraram {j7['entradas']} · resolvidas {j7['saidas']} · saldo {j7['saldo']:+d}"},
                {"title": "Últimos 30 dias", "value": f"entraram {j30['entradas']} · resolvidas {j30['saidas']} · saldo {j30['saldo']:+d}"},
                {"title": "Tempo para resolver", "value": f"{tempo} em média (30 dias)"}]}]})
    corpo.extend(_blocos_sinais(m, max_itens))
    antigas = m.get("mais_antigas", [])[:max_itens]
    if antigas:
        corpo.append({"type": "Container", "separator": True, "items": [_bloco("Mais antigas", weight="Bolder")] + [
            _bloco(f"Nota {a['nota']} · {a['resumo']} — {a['dias']} dia(s)") for a in antigas]})
    corpo.append(_bloco("A tabela completa e o Excel foram enviados por e-mail.", size="Small", isSubtle=True))
    corpo.append(_bloco(AVISO, size="Small", isSubtle=True, separator=True))
    return corpo


def _corpo_sistema(m: dict, max_itens: int) -> list[dict]:
    corpo = [_faixa(m, "good" if m.get("nivel") == "ok" else "warning"),
             _bloco(m["texto"], spacing="Medium")]
    if m.get("sandbox"):
        corpo.append(_bloco("SANDBOX: mensagem de teste", color="Warning", size="Small"))
    return corpo


_CORPOS = {"movimentos": _corpo_movimentos, "resumo": _corpo_resumo, "sistema": _corpo_sistema}


def _corpo_do_cartao(m: dict, max_itens: int) -> list[dict]:
    return _CORPOS.get(m.get("tipo"), _corpo_alerta)(m, max_itens)


def montar_payload(m: dict) -> dict:
    """Payload no formato aceito pelo webhook do Workflows."""
    max_itens = MAX_ITENS
    while True:
        cartao = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": _corpo_do_cartao(m, max_itens),
        }
        payload = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": cartao,
            }],
        }
        tamanho = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if tamanho <= LIMITE_BYTES or max_itens <= 1:
            return payload
        max_itens -= 1  # cartão grande demais: mostra menos itens


def mensagem_de_teste() -> dict:
    """Mensagem sem nenhum dado operacional, só para validar a conexão."""
    return {
        "titulo": "Radar Operacional: teste de conexão",
        "dados_de": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "n_itens": 1, "n_novos": 1,
        "colunas": ["Item"],
        "itens": [{"Item": "Se você está lendo isto, o webhook funciona."}],
        "sandbox": True,
    }


def url_bem_formada(url: str) -> bool:
    """Uma única URL, sem espaços nem caracteres de controle (colagem duplicada, Ctrl+A etc.)."""
    if not url or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return False
    return url.count("://") == 1


def _url_permitida(url: str) -> bool:
    # http só é aceito para loopback (testes locais)
    if not url_bem_formada(url):
        return False
    return url.startswith("https://") or url.startswith(("http://127.0.0.1", "http://localhost"))


def enviar(mensagem: dict, url: str, timeout: float = 15, tentativas: int = 2) -> None:
    if not _url_permitida(url):
        raise ErroDeEnvio("TEAMS_URL_INVALIDA")
    corpo = json.dumps(montar_payload(mensagem), ensure_ascii=False).encode("utf-8")
    pedido = urllib.request.Request(
        url, data=corpo, method="POST", headers={"Content-Type": "application/json"}
    )
    codigo = "TEAMS_ERRO_REDE"
    for tentativa in range(tentativas):
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as resp:
                if 200 <= resp.status < 300:
                    return
                codigo = f"TEAMS_HTTP_{resp.status}"
        except urllib.error.HTTPError as e:
            codigo = f"TEAMS_HTTP_{e.code}"
            if e.code not in (429, 500, 502, 503, 504):
                break  # erro do nosso lado (400, 401, 403, 404...): repetir não adianta
        except ValueError:  # inclui http.client.InvalidURL; a mensagem citaria a URL (segredo)
            raise ErroDeEnvio("TEAMS_URL_INVALIDA") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            codigo = "TEAMS_ERRO_REDE"
        if tentativa + 1 < tentativas:
            time.sleep(2 * (tentativa + 1))
    # "from None" evita que a URL (segredo) apareça num traceback
    raise ErroDeEnvio(codigo) from None
