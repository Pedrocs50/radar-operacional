"""Indicadores de resultado: quanto entrou, quanto saiu, saldo e tempo até resolver.

Respondem "o projeto está dando resultado?" com número. Funções puras sobre os registros que o robô já grava:
- entradas = CDs avisadas pela primeira vez (tabela de alertas), sem as da base de referência (as que já
  estavam fora da GFW quando o robô começou não contam como "entrada")
- saídas   = eventos de resolução (resolvida ou voltou para a GFW)
- tempo até resolver = dias em aberto da CD no momento em que saiu da lista
Semanas de segunda a domingo, no fuso da máquina; a semana corrente é parcial.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from statistics import median

TIPOS_SAIDA = ("resolvida", "voltou_gfw")


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone()


def _inicio_semana(dt: datetime) -> datetime:
    return datetime.combine(dt.date() - timedelta(days=dt.weekday()), time.min, tzinfo=dt.tzinfo)


def _dias(e: dict):
    try:
        return int(float(e.get("dias")))
    except (TypeError, ValueError):
        return None


def calcular(entradas: list[dict], saidas: list[dict], agora: datetime | None = None, semanas: int = 8) -> dict:
    """entradas/saidas: registros com "quando" (ISO). Retorna janelas de 7 e 30 dias e a série semanal."""
    agora = (agora or datetime.now().astimezone()).astimezone()
    atual = _inicio_semana(agora)
    serie = {(atual - timedelta(weeks=k)).date(): {"inicio": (atual - timedelta(weeks=k)).date(),
                                                   "rotulo": (atual - timedelta(weeks=k)).strftime("%d/%m"),
                                                   "entradas": 0, "saidas": 0, "parcial": k == 0}
             for k in range(semanas - 1, -1, -1)}
    for chave, lista in (("entradas", entradas), ("saidas", saidas)):
        for e in lista:
            semana = _inicio_semana(_local(e["quando"])).date()
            if semana in serie:
                serie[semana][chave] += 1

    janelas = {}
    for dias in (7, 30):
        corte = agora - timedelta(days=dias)
        ent = sum(1 for e in entradas if _local(e["quando"]) >= corte)
        sai = [e for e in saidas if _local(e["quando"]) >= corte]
        tempos = [d for d in (_dias(e) for e in sai) if d is not None]
        janelas[f"{dias}d"] = {
            "entradas": ent, "saidas": len(sai), "saldo": ent - len(sai),
            "tempo_medio": round(sum(tempos) / len(tempos), 1) if tempos else None,
            "tempo_mediano": median(tempos) if tempos else None, "amostra": len(tempos),
        }
    lista = list(serie.values())
    return {"janelas": janelas, "semanas": lista, "tem_dados": any(s["entradas"] or s["saidas"] for s in lista)}


def preparar(task: dict, storage, agora: datetime | None = None) -> dict:
    """Indicadores da tarefa a partir do banco. {} se `indicadores:` não estiver ligado no YAML."""
    cfg = task.get("indicadores")
    if not cfg or not cfg.get("ativo"):
        return {}
    semanas = cfg.get("semanas", 8)
    desde = (datetime.now(timezone.utc) - timedelta(days=semanas * 7 + 7)).isoformat(timespec="seconds")
    base = storage.primeira_execucao_real(task["id"])
    entradas = [a for a in storage.alertas_desde(task["id"], desde) if a.get("execucao_id") != base]
    saidas = [e for e in storage.listar_eventos(task["id"], desde) if e["tipo"] in TIPOS_SAIDA]
    return {"indicadores": calcular(entradas, saidas, agora, semanas)}
