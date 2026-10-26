"""Resumo periódico (ex.: 7h, 12h, 14h, 18h): estado geral do estoque + o que se movimentou desde o último.

Não depende de CD nova: é o retrato do momento. Vai por e-mail (tabela completa e Excel) e por um cartão
compacto no Teams. O "desde o último resumo" vem da tabela de eventos e dos alertas já gravados.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .. import config
from ..channels import email_conteudo, preview
from ..channels.email_conteudo import visao_geral
from ..channels.base import ErroDeEnvio
from ..storage.crypto import Crypto
from ..storage.db import Storage
from . import indicadores, paineis, sinais
from .runner import _entregar, _validar_colunas, montar_mensagem

TIPOS_PERIODO = ("resolvida", "voltou_gfw", "mudou_ct", "saiu_criterio", "nao_encontrada")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def montar_mensagem_resumo(task: dict, linhas: list[dict], novas: list[dict], eventos: list[dict],
                           resolvidas_7d: int, desde_texto: str, agora: datetime, dry_run: bool, sandbox: dict) -> dict:
    """Mensagem do resumo (e-mail e Teams). Separada para ser reaproveitada pelo comando `simular`."""
    campo_chave = task["fonte"]["campo_chave"]
    mensagem = montar_mensagem(task, novas, len(linhas), dry_run, sandbox)
    c = email_conteudo._cfg({"email": task.get("email", {})})
    periodo = {"novas": len(novas), **{t: sum(1 for e in eventos if e["tipo"] == t) for t in TIPOS_PERIODO}}
    mensagem.update({
        "tipo": "resumo",
        "titulo": task.get("resumo", {}).get("titulo", "Resumo das CDs da GFW fora da área")
                  + f" · {agora.astimezone().strftime('%Hh%M')}",
        "estoque": linhas, "campo_chave": campo_chave, "email": task.get("email", {}),
        "geral": email_conteudo.visao_geral(linhas, c, campo_chave), "periodo": periodo, "eventos": eventos,
        "rotulos": task["mensagem"].get("rotulos", {}), "desde_texto": desde_texto, "resolvidas_7d": resolvidas_7d,
        "mais_antigas": sorted(
            ({"nota": l[campo_chave], "dias": int(l.get("Dias_em_Aberto") or 0),
              "resumo": " · ".join(str(l.get(k)) for k in ("Modelo_Aeronave", "Descricao_CT_Atual") if l.get(k))}
             for l in linhas), key=lambda a: -a["dias"])[:5],
    })
    return mensagem


def executar_resumo(task: dict, fonte, storage: Storage, crypto: Crypto, settings: dict,
                    dry_run: bool = True, enviadores: dict | None = None, agora: datetime | None = None,
                    canais: list[str] | None = None) -> dict:
    agora = agora or datetime.now(timezone.utc)
    rid = f"{task['id']}:resumo"
    exec_id = storage.iniciar_execucao(rid, dry_run)
    try:
        linhas = fonte.fetch()
        storage.definir_bytes(exec_id, getattr(fonte, "ultimo_bytes", None))
        campo_chave = task["fonte"]["campo_chave"]
        _validar_colunas(linhas, [campo_chave] + task["mensagem"]["campos_exibidos"]
                         + sinais.colunas_necessarias(task.get("sinais", {}))
                         + paineis.colunas_necessarias(task.get("graficos")))

        chave_estado = f"resumo_ultimo:{task['id']}"
        ultimo = storage.estado_get(chave_estado)
        desde = ultimo or _iso(agora - timedelta(hours=24))
        desde_dt = datetime.fromisoformat(desde)

        # CDs que chegaram desde o último resumo ficam em vermelho na tabela
        novos_hash = storage.hashes_avisados_desde(task["id"], desde)
        novas = [l for l in linhas if crypto.blind_index(task["id"], l[campo_chave]) in novos_hash]

        eventos = storage.listar_eventos(task["id"], desde)
        mensagem = montar_mensagem_resumo(
            task, linhas, novas, eventos,
            sum(storage.contar_eventos(task["id"], t, _iso(agora - timedelta(days=7))) for t in ("resolvida", "voltou_gfw")),
            desde_dt.astimezone().strftime("%d/%m %H:%M") if ultimo else "as últimas 24 h",
            agora, dry_run, settings.get("sandbox", {}))
        responsaveis = task.get("resumo", {}).get("responsaveis")
        if responsaveis:
            mensagem["geral"] = visao_geral(linhas, email_conteudo._cfg({"email": task.get("email", {})}), campo_chave, responsaveis)
        periodo = mensagem["periodo"]

        mensagem.update(sinais.preparar(task, linhas, storage, campo_chave))
        mensagem.update(indicadores.preparar(task, storage))
        mensagem.update(paineis.preparar(task, linhas))  # gráficos só no resumo (7h, 12h, 14h, 18h)
        pasta = config.RAIZ / settings["preview"]["dir"]
        base = f"{task['id']}_resumo{exec_id}"
        previa = email_conteudo.gerar_previa(mensagem, pasta, base)

        enviados: list[str] = []
        bloqueados: list[str] = []
        if not dry_run:
            # canais=[...] limita o envio (ex.: só o e-mail do dono, para testar); envio parcial não marca o resumo como feito
            task_envio = {**task, "canais": canais} if canais else task
            enviados, bloqueados = _entregar(task_envio, mensagem, settings, enviadores or {},
                                             {"pasta": pasta, "nome_base": base, "task": task,
                                              "dominios": settings.get("email", {}).get("dominios_permitidos")})
            if not canais and (enviados or not [c for c in task.get("canais", []) if c != "preview"]):
                storage.estado_set(chave_estado, _iso(agora))  # só marca o resumo como feito após entregar
        storage.finalizar_execucao(exec_id, "sucesso", n_itens=len(linhas), n_novos=len(novas))
        return {"execucao_id": exec_id, "n_itens": len(linhas), "periodo": periodo, "previa": str(previa),
                "enviados": enviados, "bloqueados_sandbox": bloqueados, "dry_run": dry_run}
    except ErroDeEnvio as e:
        storage.finalizar_execucao(exec_id, "falha", codigo_erro=e.codigo)
        raise
    except Exception as e:
        storage.finalizar_execucao(exec_id, "falha", codigo_erro=type(e).__name__)
        raise
