"""Saúde do robô: avisa o dono (e-mail) e o grupo (Teams) quando o vigia falha de forma sustentada,
e quando volta ao normal. Também percebe quando o robô ficou fora do ar (PC desligado, por exemplo).

Regras:
- Cada checagem do vigia é registrada (ok ou código de erro).
- Falhas seguidas >= `limiar_falhas`  -> aviso de instabilidade (uma vez só) ao dono e ao grupo.
- Primeiro sucesso depois disso       -> aviso de que voltou, com o tempo fora.
- Lacuna entre checagens > `lacuna_min` (sem falha registrada) -> aviso só ao dono: "estive fora entre A e B".
Sem dado operacional: só códigos de erro e horários. Falha ao avisar nunca derruba o vigia.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from pathlib import Path

from . import config, segredos
from .channels import email_outlook, teams_webhook
from .storage.db import Storage

LIMIAR_FALHAS = 3
LACUNA_MIN = 30


def _dt(texto: str) -> datetime:
    return datetime.fromisoformat(texto)


def _fmt(texto: str) -> str:
    return _dt(texto).astimezone().strftime("%d/%m %H:%M")


def _minutos(a: str, b: str) -> int:
    return int((_dt(b) - _dt(a)).total_seconds() // 60)


def processar(storage: Storage, task_id: str, ok: bool, codigo: str | None, avisar, cfg: dict | None = None,
              agora: datetime | None = None) -> str | None:
    """Registra a checagem e dispara os avisos necessários. `avisar(destino, titulo, texto, nivel)` envia.

    destino: "dono" ou "grupo". Retorna o tipo de aviso disparado (ou None)."""
    cfg = cfg or {}
    limiar = cfg.get("limiar_falhas", LIMIAR_FALHAS)
    lacuna = cfg.get("lacuna_min", LACUNA_MIN)
    agora_iso = (agora or datetime.now(timezone.utc)).isoformat(timespec="seconds")

    anteriores = storage.ultimas_verificacoes(task_id, 50)
    storage.registrar_verificacao(task_id, ok, codigo)
    chave = f"saude:{task_id}"
    situacao = storage.estado_get(chave, "ok")

    if not ok:
        falhas = 1
        for v in anteriores:
            if v["ok"]:
                break
            falhas += 1
        if falhas >= limiar and situacao != "instavel":
            storage.estado_set(chave, "instavel")
            storage.estado_set(chave + ":desde", agora_iso)
            _seguro(avisar, "dono", "Radar com falha",
                    f"O robô falhou {falhas} verificações seguidas na tarefa '{task_id}'.\nÚltimo erro: {codigo}.\n"
                    f"Desde {_fmt(anteriores[falhas - 2]['em'] if falhas > 1 else agora_iso)}.",
                    "atencao")
            _seguro(avisar, "grupo", "Radar com instabilidade",
                    "O robô de alertas está com um problema técnico e já está sendo verificado. "
                    "Alertas novos podem atrasar. Avisaremos quando voltar ao normal.", "atencao")
            return "instabilidade"
        return None

    if situacao == "instavel":
        desde = storage.estado_get(chave + ":desde", agora_iso)
        storage.estado_set(chave, "ok")
        mins = _minutos(desde, agora_iso)
        _seguro(avisar, "dono", "Radar voltou ao normal", f"A tarefa '{task_id}' voltou a funcionar após ~{mins} min.", "ok")
        _seguro(avisar, "grupo", "Radar voltou ao normal",
                "O robô de alertas voltou a funcionar. Alertas que ficaram pendentes serão enviados.", "ok")
        return "recuperacao"

    if anteriores and _minutos(anteriores[0]["em"], agora_iso) > lacuna:
        _seguro(avisar, "dono", "Radar ficou fora do ar",
                f"Sem verificações entre {_fmt(anteriores[0]['em'])} e {_fmt(agora_iso)} "
                f"(~{_minutos(anteriores[0]['em'], agora_iso)} min). Possível PC desligado, reinício ou rede.\n"
                "CDs que chegaram nesse intervalo são alertadas agora.", "atencao")
        return "lacuna"
    return None


def _seguro(avisar, destino, titulo, texto, nivel):
    try:
        avisar(destino, titulo, texto, nivel)
    except Exception:  # aviso nunca derruba o vigia; só o tipo do erro importa
        pass


def html_simples(titulo: str, texto: str) -> str:
    corpo = "<br>".join(html.escape(l) for l in texto.splitlines())
    return (f"<html><body style='font-family:Arial,sans-serif;font-size:14px'><h3>{html.escape(titulo)}</h3>"
            f"<p>{corpo}</p><p style='color:#7b8794;font-size:11px'>Aviso técnico automático do Radar Operacional.</p>"
            "</body></html>")


def _cauda_do_log(task_id: str, linhas: int = 15) -> str:
    """Últimas linhas do log do vigia (só códigos e tipos de erro, nunca conteúdo)."""
    pasta = config.RAIZ / "data" / "logs"
    arquivos = sorted(pasta.glob(f"vigia-{task_id}-*.log")) if pasta.exists() else []
    if not arquivos:
        return ""
    return "\n".join(arquivos[-1].read_text(encoding="utf-8", errors="replace").splitlines()[-linhas:])


def montar_avisador(settings: dict, task: dict, enviar_email=email_outlook.enviar_html,
                    enviar_teams=teams_webhook.enviar):
    """Cria avisar(destino, titulo, texto, nivel): "dono" por e-mail, "grupo" por cartão no Teams.
    Respeita o sandbox (só canais em canais_permitidos)."""
    cfg = task.get("saude", {})
    sandbox = settings.get("sandbox", {})
    permitidos = set(sandbox.get("canais_permitidos", []))
    pasta = config.RAIZ / settings["preview"]["dir"]

    def liberado(canal: str) -> bool:
        return not sandbox.get("ativo", True) or canal in permitidos

    def avisar(destino: str, titulo: str, texto: str, nivel: str):
        if destino == "dono":
            canal = cfg.get("canal_dono", "email:dono")
            if not liberado(canal):
                return
            lista = segredos.obter("email_destinatarios_" + canal.split(":", 1)[1])
            info = nivel == "info"   # aviso informativo (ex.: "estou vivo"): sem prefixo de alerta e sem log
            cauda = "" if info else _cauda_do_log(task["id"])
            corpo = texto + ("\n\nÚltimas linhas do log:\n" + cauda if cauda else "")
            prefixo = "[Radar]" if info else "[Radar · alerta técnico]"
            enviar_email(lista, f"{prefixo} {titulo}", html_simples(titulo, corpo), pasta, "saude",
                         dominios=settings.get("email", {}).get("dominios_permitidos"))
        else:
            canal = cfg.get("canal_grupo", "teams:teste")
            if not liberado(canal):
                return
            url = segredos.obter("teams_webhook_" + canal.split(":", 1)[1])
            enviar_teams({"tipo": "sistema", "titulo": titulo, "texto": texto, "nivel": nivel,
                          "marca": "RADAR OPERACIONAL", "dados_de": "", "n_itens": 0, "n_novos": 0,
                          "colunas": [], "itens": [], "sandbox": sandbox.get("ativo", True)}, url)

    return avisar
