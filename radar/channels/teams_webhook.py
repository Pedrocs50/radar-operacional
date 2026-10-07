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


def _corpo_do_cartao(m: dict, max_itens: int) -> list[dict]:
    colunas = m["colunas"]
    itens = m["itens"]
    corpo = [
        _bloco(m["titulo"], size="Large", weight="Bolder"),
        _bloco(
            f"Dados de {m['dados_de']} · {m['n_novos']} novo(s) de {m['n_itens']} na leitura",
            isSubtle=True, spacing="None",
        ),
    ]
    if m.get("sandbox"):
        corpo.append(_bloco("SANDBOX: mensagem de teste", color="Warning", size="Small"))

    for item in itens[:max_itens]:
        # as 3 primeiras colunas viram o título do item; as demais, pares nome/valor
        cabecalho = " · ".join(_cortar(item.get(c, ""), 40) for c in colunas[:3])
        fatos = [
            {"title": c, "value": _cortar(item.get(c, ""))}
            for c in colunas[3:] if str(item.get(c, "")).strip()
        ]
        conteudo = [_bloco(cabecalho, weight="Bolder")]
        if fatos:
            conteudo.append({"type": "FactSet", "facts": fatos})
        corpo.append({"type": "Container", "separator": True, "spacing": "Medium", "items": conteudo})

    ocultos = len(itens) - max_itens
    if ocultos > 0:
        corpo.append(_bloco(f"+ {ocultos} item(ns) não exibido(s).", isSubtle=True))
    corpo.append(_bloco(AVISO, size="Small", isSubtle=True, separator=True))
    return corpo


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


def _url_permitida(url: str) -> bool:
    # http só é aceito para loopback (testes locais)
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
        except (urllib.error.URLError, TimeoutError, OSError):
            codigo = "TEAMS_ERRO_REDE"
        if tentativa + 1 < tentativas:
            time.sleep(2 * (tentativa + 1))
    # "from None" evita que a URL (segredo) apareça num traceback
    raise ErroDeEnvio(codigo) from None
