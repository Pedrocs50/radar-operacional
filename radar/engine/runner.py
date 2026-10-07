"""Executor de tarefas: fonte -> índice cego -> novos? -> mensagem -> canais -> estado -> log.

Idempotência: rodar duas vezes não duplica avisos. O estado de "já avisei"
só é gravado em execução real (dry_run=False) e SÓ DEPOIS de os envios darem
certo. Se o envio falhar, nada é marcado como avisado e a próxima execução tenta de novo.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .. import config, segredos
from ..channels import email_conteudo, email_outlook, imagem, preview, teams_webhook
from ..channels.base import ErroDeEnvio
from . import movimentos as mov
from . import sinais
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
        "rotulos": msg.get("rotulos", {}),
        "marca": msg.get("marca", "RADAR OPERACIONAL"),
        "itens": itens_novos,
        "dry_run": dry_run,
        "sandbox": sandbox.get("ativo", True),
        "destinatarios": sandbox.get("destinatarios", []),
    }


def montar_mensagem_movimentos(task: dict, eventos: list[dict], sandbox: dict) -> dict:
    ac = task.get("acompanhamento", {})
    return {
        "tipo": "movimentos", "task_id": task["id"], "titulo": ac.get("titulo", "Movimentação de CDs da GFW"),
        "marca": task["mensagem"].get("marca", "RADAR OPERACIONAL"),
        "dados_de": datetime.now().strftime("%d/%m/%Y %H:%M"), "eventos": eventos,
        "sandbox": sandbox.get("ativo", True),
    }


def _calcular_movimentos(task: dict, fonte, storage: Storage, exec_id: int, indexados: list) -> list[dict]:
    """Compara a leitura atual com a foto da última execução real. Sem foto anterior, não há movimento."""
    ac = task.get("acompanhamento")
    if not ac:
        return []
    anterior = storage.ultimo_snapshot(task["id"], exec_id)
    if not anterior:
        return []
    saidas, mudancas = mov.detectar(anterior, dict(indexados), ac.get("campos_criticos", []))
    resolucoes = {}
    if saidas and hasattr(fonte, "resolver_notas") and ac.get("sql_resolucao_file"):
        resolucoes = fonte.resolver_notas(config.RAIZ / ac["sql_resolucao_file"], [p["chave"] for _, p in saidas])
    return mov.montar_eventos(task, saidas, mudancas, resolucoes)


def _resolver_enviador(canal: str, ctx: dict | None = None):
    """Transforma o nome do canal (ex.: 'teams:teste') em uma função enviar(mensagem)."""
    if canal.startswith("email:"):
        destino = canal.split(":", 1)[1]
        ctx = ctx or {}

        def _enviar_email(mensagem: dict):
            try:
                lista = segredos.obter(f"email_destinatarios_{destino}")
            except RuntimeError:
                raise ErroDeEnvio("SEGREDO_AUSENTE") from None
            email_outlook.enviar(mensagem, lista, ctx["pasta"], ctx["nome_base"],
                                 modo=ctx["task"].get("email", {}).get("modo", "enviar"),
                                 remetente=ctx["task"].get("email", {}).get("remetente"))

        return _enviar_email

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


def _entregar(task: dict, mensagem: dict, settings: dict, enviadores: dict,
              ctx: dict | None = None) -> tuple[list[str], list[str]]:
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
        enviar = enviadores.get(canal) or _resolver_enviador(canal, ctx)
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
    limite: int | None = None,
) -> dict:
    """Roda uma tarefa. Retorna um resumo (sem conteúdo sensível além do caminho do preview)."""
    exec_id = storage.iniciar_execucao(task["id"], dry_run)
    try:
        linhas = fonte.fetch()
        storage.definir_bytes(exec_id, getattr(fonte, "ultimo_bytes", None))
        campo_chave = task["fonte"]["campo_chave"]
        _validar_colunas(linhas, [campo_chave] + task["mensagem"]["campos_exibidos"]
                         + sinais.colunas_necessarias(task.get("sinais", {})))

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

        eventos = _calcular_movimentos(task, fonte, storage, exec_id, indexados)
        suspeita = False  # leitura vazia depois de um estoque grande pode ser carga incompleta da origem
        if task.get("acompanhamento") and not dry_run:
            chave_vazio = f"leitura_vazia:{task['id']}"
            if not linhas and len(storage.ultimo_snapshot(task["id"], exec_id)) >= 3:
                suspeita = storage.estado_get(chave_vazio) != "1"
                storage.estado_set(chave_vazio, "1")
            elif linhas:
                storage.estado_set(chave_vazio, "0")
            if suspeita:
                eventos = []
        if limite:
            novos = novos[:limite]
        itens_novos = [l for _, l in novos]
        mensagem = montar_mensagem(task, itens_novos, len(linhas), dry_run, settings.get("sandbox", {}))
        mensagem["campo_chave"] = campo_chave
        usa_email = any(c.startswith("email:") for c in task.get("canais", []))
        if usa_email:  # o e-mail mostra o estoque inteiro e destaca as CDs novas
            mensagem["estoque"] = linhas
            mensagem["email"] = task.get("email", {})
        mensagem.update(sinais.preparar(task, linhas, storage, campo_chave))  # paradas, plano, responsável, vazamento

        # prévia (HTML temporário) e cópia cifrada da mensagem
        pasta = config.RAIZ / settings["preview"]["dir"]  # relativo à raiz, não ao diretório atual
        arquivo = preview.enviar(mensagem, pasta, f"{task['id']}_exec{exec_id}")
        storage.salvar_mensagem(exec_id, mensagem)
        imagens: list[Path] = []
        if task["mensagem"].get("imagem") and itens_novos:  # tabela com TODAS as colunas, uma imagem por item
            imagens = imagem.gerar(itens_novos, pasta, f"{task['id']}_exec{exec_id}", task["mensagem"]["titulo"],
                                   task["mensagem"].get("rotulos"), campo_chave)

        email_previa = None
        if usa_email and itens_novos:  # prévia local do e-mail (HTML + tabela PNG + Excel), sem enviar
            email_previa = email_conteudo.gerar_previa(mensagem, pasta, f"{task['id']}_exec{exec_id}")

        enviados: list[str] = []
        bloqueados: list[str] = []
        if not dry_run:
            # 1) entrega primeiro (só se há algo novo: sem novidade, sem mensagem)
            if itens_novos:
                enviados, bloqueados = _entregar(task, mensagem, settings, enviadores or {},
                                              {"pasta": pasta, "nome_base": f"{task['id']}_exec{exec_id}", "task": task})
            # 2) só depois de entregar com sucesso é que o estado é gravado
            externos = [c for c in task.get("canais", ["preview"]) if c != "preview"]
            if enviados or not externos or not itens_novos:
                campos_alerta = mov.campos_snapshot(task) if task.get("acompanhamento") else []
                storage.registrar_alertas(task["id"], exec_id, [
                    (h, mov.payload_snapshot(l, campo_chave, campos_alerta)) for h, l in novos])
            # senão: o sandbox bloqueou todos os canais externos; não marca como avisado,
            # para o item ainda ser entregue quando o canal for liberado

            # 3) movimentação (resolvida / mudou de CT): entrega, e só então grava eventos e a nova foto.
            #    Se falhar, a foto antiga continua valendo e a próxima execução tenta de novo.
            canais_teams = [c for c in task.get("canais", []) if c.startswith("teams:")]
            entregue_mov = not suspeita  # 1ª leitura vazia suspeita: não mexe na foto nem nos eventos
            if eventos and canais_teams:
                msg_mov = montar_mensagem_movimentos(task, eventos, settings.get("sandbox", {}))
                env_mov, _ = _entregar({**task, "canais": canais_teams}, msg_mov, settings, enviadores or {}, None)
                entregue_mov = bool(env_mov)
            if entregue_mov:
                for e in eventos:
                    storage.registrar_evento(task["id"], e["hash"], e["tipo"], exec_id, e)
                campos = mov.campos_snapshot(task) if task.get("acompanhamento") else []
                storage.salvar_snapshot(exec_id, [
                    (h, mov.payload_snapshot(l, campo_chave, campos) if campos else {"chave": str(l[campo_chave])})
                    for h, l in indexados])

        status = "sucesso" if itens_novos else "sem_novidade"
        storage.finalizar_execucao(exec_id, status, n_itens=len(linhas), n_novos=len(itens_novos))
        return {
            "execucao_id": exec_id,
            "status": status,
            "n_itens": len(linhas),
            "n_novos": len(itens_novos),
            "preview": str(arquivo),
            "n_movimentos": len(eventos),
            "movimentos": [{k: v for k, v in e.items() if k != "hash"} for e in eventos] if dry_run else [],
            "email_previa": str(email_previa) if email_previa else None,
            "imagens": [str(p) for p in imagens],
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
