"""Aviso diário "estou vivo": um e-mail curto ao dono com a situação do robô.

Como um robô desligado não consegue avisar que parou, o próprio aviso diário vira o alarme: se o e-mail das 6h45 não chegar,
algo parou (máquina, sessão, Outlook ou o agendador). Quando o robô está de pé mas com problema, o assunto vem com ATENÇÃO.
Só lê o banco e o disco: não consulta o BigQuery, então não custa nada.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

from . import config, manutencao

LIMITE_VERIFICACAO_MIN = 30      # vigia sem verificar há mais que isso = parado
LIMITE_BACKUP_H = 36
LIMITE_DISCO_GB = 2.0
LIMITE_CANARIO_DIAS = 10
LEMBRETE_CHAVES_DIAS = 90


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _versao() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(config.RAIZ), capture_output=True,
                           text=True, timeout=10)
        return r.stdout.strip() or "-"
    except Exception:
        return "-"


def coletar(storage, task_id: str, settings: dict, agora: datetime | None = None) -> dict:
    agora = (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    e = storage.estatisticas(task_id, _iso(agora - timedelta(hours=24)))
    ultima = datetime.fromisoformat(e["ultima_verificacao"]) if e["ultima_verificacao"] else None
    backup = manutencao.ultimo_backup(settings)
    try:
        livre = shutil.disk_usage(config.RAIZ).free / 1e9
    except OSError:
        livre = None
    resumo_ultimo = storage.estado_get(f"resumo_ultimo:{task_id}")
    canario = storage.estado_get(f"canario:{task_id}")
    chaves = storage.estado_get("chaves_confirmadas")
    return {
        "agora": agora, "tarefa": task_id, "verificacoes": e["verificacoes"], "falhas_vigia": e["verificacoes_falhas"],
        "minutos_sem_verificar": int((agora - ultima).total_seconds() // 60) if ultima else None,
        "execucoes": e["execucoes"], "novos": e["novos"], "falhas_execucao": e["execucoes_falhas"],
        "gb_lidos": round(e["bytes"] / 1e9, 1), "cargas": e["cargas"], "ultima_carga": e["ultima_carga"],
        "saude": storage.estado_get(f"saude:{task_id}", "ok"),
        "ultimo_resumo": datetime.fromisoformat(resumo_ultimo).astimezone() if resumo_ultimo else None,
        "horas_desde_backup": round((datetime.now() - backup).total_seconds() / 3600, 1) if backup else None,
        "disco_livre_gb": round(livre, 1) if livre is not None else None, "versao": _versao(),
        "canario": json.loads(canario) if canario else None,
        "chaves_confirmadas": datetime.fromisoformat(chaves).astimezone() if chaves else None,
    }


def avaliar(info: dict) -> list[str]:
    """Lista de problemas (vazia = tudo bem)."""
    p = []
    if info["minutos_sem_verificar"] is None:
        p.append("o vigia nunca registrou uma verificação")
    elif info["minutos_sem_verificar"] > LIMITE_VERIFICACAO_MIN:
        p.append(f"o vigia está há {info['minutos_sem_verificar']} min sem verificar (esperado: a cada 5 min)")
    if info["saude"] == "instavel":
        p.append("o robô está marcado como instável (falhas seguidas)")
    if info["falhas_execucao"]:
        p.append(f"{info['falhas_execucao']} execução(ões) com falha nas últimas 24 h")
    if info["horas_desde_backup"] is None:
        p.append("nenhum backup do banco foi feito ainda")
    elif info["horas_desde_backup"] > LIMITE_BACKUP_H:
        p.append(f"o último backup tem {info['horas_desde_backup']} h")
    if info["disco_livre_gb"] is not None and info["disco_livre_gb"] < LIMITE_DISCO_GB:
        p.append(f"pouco espaço em disco: {info['disco_livre_gb']} GB livres")
    c = info.get("canario")
    if c and c["falhas"]:
        p.append("o último teste semanal do Teams falhou: " + ", ".join(f"{k} ({v})" for k, v in c["falhas"].items()))
    elif c:
        dias = (info["agora"] - datetime.fromisoformat(c["em"])).days
        if dias > LIMITE_CANARIO_DIAS:
            p.append(f"o teste semanal do Teams não roda há {dias} dias")
    esq = info.get("esquema")
    if esq and not esq.get("erro") and not esq["primeira_vez"] and (esq["removidas"] or esq["tipo_mudou"]):
        partes = ([f"removidas: {', '.join(esq['removidas'][:5])}"] if esq["removidas"] else []) + \
                 ([f"tipo alterado: {', '.join(esq['tipo_mudou'][:5])}"] if esq["tipo_mudou"] else [])
        p.append("o esquema da tabela de origem mudou (" + "; ".join(partes) + "); confira se o SQL ainda funciona")
    return p


def montar(info: dict, problemas: list[str]) -> tuple[str, str, str]:
    """(título, texto, nível) do aviso. Nível "info" = tudo bem; "atencao" = há problema."""
    hora = info["agora"].astimezone().strftime("%d/%m %H:%M")
    titulo = f"Estou vivo · {hora} · OK" if not problemas else f"ATENÇÃO · {hora} · {problemas[0]}"
    ult = info["ultima_carga"][:16].replace("T", " ") + " UTC" if info["ultima_carga"] else "nenhuma detectada"
    linhas = [
        f"Tarefa: {info['tarefa']}   ·   versão: {info['versao']}",
        f"Vigia nas últimas 24 h: {info['verificacoes']} verificação(ões), {info['falhas_vigia']} com falha; "
        + (f"última há {info['minutos_sem_verificar']} min." if info["minutos_sem_verificar"] is not None else "nenhuma."),
        f"Cargas da origem detectadas em 24 h: {info['cargas']} (última: {ult}).",
        f"Execuções reais em 24 h: {info['execucoes']}, CDs novas avisadas: {info['novos']}, GB lidos no BigQuery: {info['gb_lidos']}.",
        "Último resumo enviado: " + (info["ultimo_resumo"].strftime("%d/%m %H:%M") if info["ultimo_resumo"] else "nenhum ainda") + ".",
        "Último backup: " + (f"há {info['horas_desde_backup']} h" if info["horas_desde_backup"] is not None else "nenhum")
        + ("; espaço livre em disco: " + str(info["disco_livre_gb"]) + " GB." if info["disco_livre_gb"] is not None else "."),
    ]
    c = info.get("canario")
    if c:
        quando = datetime.fromisoformat(c["em"]).astimezone().strftime("%d/%m %H:%M")
        linhas.append(f"Teste semanal do Teams: {'falhou' if c['falhas'] else 'ok'} em {quando}.")
    esq = info.get("esquema")
    if esq and esq.get("erro"):
        linhas.append(f"Esquema da tabela: não consegui conferir ({esq['erro']}).")
    elif esq and esq["primeira_vez"]:
        linhas.append(f"Esquema da tabela: base de comparação criada ({esq['colunas']} colunas).")
    elif esq:
        extra = f"; novas colunas: {', '.join(esq['adicionadas'][:5])}" if esq["adicionadas"] else ""
        linhas.append(f"Esquema da tabela: {'igual à última conferência' if not (esq['removidas'] or esq['tipo_mudou'] or esq['adicionadas']) else 'mudou'}{extra}.")
    ch = info.get("chaves_confirmadas")
    if ch is None or (datetime.now().astimezone() - ch).days > LEMBRETE_CHAVES_DIAS:
        linhas.append("LEMBRETE: confirme que as chaves de cifragem têm backup separado do banco (sem elas o histórico é "
                      "irrecuperável) e registre com: python -m radar chaves-ok. Última confirmação: "
                      + (ch.strftime("%d/%m/%Y") if ch else "nunca") + ".")
    if problemas:
        linhas = ["Pontos de atenção:"] + [f"- {p}" for p in problemas] + [""] + linhas
    return titulo, "\n".join(linhas), ("info" if not problemas else "atencao")
