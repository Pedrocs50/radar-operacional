"""Executor de tarefas: fonte -> índice cego -> novos? -> mensagem -> canais -> estado -> log.

Idempotência: rodar duas vezes não duplica avisos. O estado de "já avisei"
só é gravado em execução real (dry_run=False) e SÓ DEPOIS de os envios darem
certo. Se o envio falhar, nada é marcado como avisado e a próxima execução tenta de novo.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .. import config, segredos
from ..channels import preview, teams_webhook
from ..channels.base import ErroDeEnvio
from ..storage.crypto import Crypto
from ..storage.db import Storage


class ErroDeTarefa(Exception):
    """Erro com código curto, sem dado operacional (vai para o log em claro)."""

    def __init__(self, codigo: str, detalhe: str = ""):
        super().__init__(f"{codigo}: {detalhe}" if detalhe else codigo)
        self.codigo = codigo


def _validar_colunas(linhas: list[dict], obrigatorias: list[str]):
    if not linhas:
        return
    faltando = [c for c in obrigatorias if c not in linhas[0]]
    if faltando:
        # só nomes de coluna (não são dado operacional) vão na mensagem
        raise ErroDeTarefa("SCHEMA_MUDOU", "colunas ausentes: " + ", ".join(faltando))


def montar_mensagem(task: dict, itens_novos: list[dict], n_itens: int, dry_run: bool, sandbox: dict) -> dict:
    msg = task["mensagem"]
    campo_data = msg.get("campo_data_referencia")
    data_ref = None
    if campo_data and itens_novos:
        data_ref = str(itens_novos[0].get(campo_data, ""))
    return {
        "task_id": task["id"],
        "titulo": msg["titulo"],
        "dados_de": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "n_itens": n_itens,
        "n_novos": len(itens_novos),
        "data_referencia": data_ref,
        "colunas": msg["campos_exibidos"],
        "itens": itens_novos,
        "dry_run": dry_run,
        "sandbox": sandbox.get("ativo", True),
        "destinatarios": sandbox.get("destinatarios", []),
    }


def _resolver_enviador(canal: str):
    """Transforma o nome do canal (ex.: 'teams:teste') em uma função enviar(mensagem)."""
    if canal.startswith("teams:"):
        destino = canal.split(":", 1)[1]

        def _enviar(mensagem: dict):
            try:
                url = segredos.obter(f"teams_webhook_{destino}")
            except RuntimeError:
                raise ErroDeEnvio("SEGREDO_AUSENTE") from None
            teams_webhook.enviar(mensagem, url)

        return _enviar
    raise ErroDeTarefa("CANAL_DESCONHECIDO", canal)


def _entregar(task: dict, mensagem: dict, settings: dict, enviadores: dict) -> tuple[list[str], list[str]]:
    """Envia para os canais externos permitidos. Retorna (enviados, bloqueados_pelo_sandbox)."""
    sandbox = settings.get("sandbox", {})
    permitidos = set(sandbox.get("canais_permitidos", ["preview"]))
    enviados, bloqueados = [], []
    for canal in task.get("canais", ["preview"]):
        if canal == "preview":
            continue  # a prévia já foi gerada
        if sandbox.get("ativo", True) and canal not in permitidos:
            bloqueados.append(canal)
            continue
        enviar = enviadores.get(canal) or _resolver_enviador(canal)
        enviar(mensagem)  # ErroDeEnvio sobe para o executar()
        enviados.append(canal)
    return enviados, bloqueados


def executar(
    task: dict,
    fonte,
    storage: Storage,
    crypto: Crypto,
    settings: dict,
    dry_run: bool = True,
    forcar_todos: bool = False,
    enviadores: dict | None = None,
) -> dict:
    """Roda uma tarefa. Retorna um resumo (sem conteúdo sensível além do caminho do preview)."""
    exec_id = storage.iniciar_execucao(task["id"], dry_run)
    try:
        linhas = fonte.fetch()
        campo_chave = task["fonte"]["campo_chave"]
        _validar_colunas(linhas, [campo_chave] + task["mensagem"]["campos_exibidos"])

        # índice cego de cada item (chave inclui a tarefa: mesma nota em tarefas diferentes é independente)
        indexados = [(crypto.blind_index(task["id"], l[campo_chave]), l) for l in linhas]

        ja_avisados = storage.hashes_ja_avisados(task["id"]) if task.get("modo") == "novas" else set()
        if forcar_todos:
            novos = indexados
        else:
            vistos_nesta_leitura: set[str] = set()
            novos = []
            for h, l in indexados:
                if h in ja_avisados or h in vistos_nesta_leitura:
                    continue
                vistos_nesta_leitura.add(h)
                novos.append((h, l))

        itens_novos = [l for _, l in novos]
        mensagem = montar_mensagem(task, itens_novos, len(linhas), dry_run, settings.get("sandbox", {}))

        # prévia (HTML temporário) e cópia cifrada da mensagem
        pasta = config.RAIZ / settings["preview"]["dir"]  # relativo à raiz, não ao diretório atual
        arquivo = preview.enviar(mensagem, pasta, f"{task['id']}_exec{exec_id}")
        storage.salvar_mensagem(exec_id, mensagem)

        enviados: list[str] = []
        bloqueados: list[str] = []
        if not dry_run:
            # 1) entrega primeiro (só se há algo novo: sem novidade, sem mensagem)
            if itens_novos:
                enviados, bloqueados = _entregar(task, mensagem, settings, enviadores or {})
            # 2) só depois de entregar com sucesso é que o estado é gravado
            storage.salvar_snapshot(exec_id, [(h, {"chave": str(l[campo_chave])}) for h, l in indexados])
            externos = [c for c in task.get("canais", ["preview"]) if c != "preview"]
            if enviados or not externos or not itens_novos:
                storage.registrar_alertas(task["id"], exec_id, [(h, {"chave": str(l[campo_chave])}) for h, l in novos])
            # senão: o sandbox bloqueou todos os canais externos; não marca como avisado,
            # para o item ainda ser entregue quando o canal for liberado

        status = "sucesso" if itens_novos else "sem_novidade"
        storage.finalizar_execucao(exec_id, status, n_itens=len(linhas), n_novos=len(itens_novos))
        return {
            "execucao_id": exec_id,
            "status": status,
            "n_itens": len(linhas),
            "n_novos": len(itens_novos),
            "preview": str(arquivo),
            "dry_run": dry_run,
            "enviados": enviados,
            "bloqueados_sandbox": bloqueados,
        }
    except (ErroDeTarefa, ErroDeEnvio) as e:
        storage.finalizar_execucao(exec_id, "falha", codigo_erro=e.codigo)
        raise
    except Exception as e:
        # só o tipo da exceção vai para o log em claro, nunca a mensagem (pode citar dados)
        storage.finalizar_execucao(exec_id, "falha", codigo_erro=type(e).__name__)
        raise
