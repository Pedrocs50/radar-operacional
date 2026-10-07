"""`python -m radar doctor`: confere o ambiente inteiro sem enviar nada nem mostrar segredos.

Serve para validar uma máquina nova (servidor) antes de agendar. Cada verificação devolve
(nome, ok, detalhe); nenhum valor de segredo ou dado operacional entra no detalhe.
"""
from __future__ import annotations

import subprocess

from . import config, segredos
from .storage import crypto as cr
from .storage.db import Storage

SEGREDOS_ESPERADOS = ["teams_webhook_teste", "email_destinatarios_teste", "email_destinatarios_dono"]


def _powershell(comando: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-Command", comando],
                          capture_output=True, text=True, timeout=timeout)


def verificar(settings: dict, task: dict | None = None) -> list[tuple[str, bool, str]]:
    r: list[tuple[str, bool, str]] = []

    def checar(nome, fn):
        try:
            ok, detalhe = fn()
        except RuntimeError:  # segredo/chave ausente (as mensagens já são seguras)
            ok, detalhe = False, "não encontrado"
        except Exception as e:  # só o tipo: a mensagem pode citar dados
            ok, detalhe = False, type(e).__name__
        r.append((nome, ok, detalhe))

    def chaves():
        cr.carregar_crypto()
        return True, "chaves de cifragem e HMAC encontradas"

    def banco():
        st = Storage(config.RAIZ / settings["storage"]["db_path"], cr.carregar_crypto())
        ult = st.listar_execucoes(None, 1)
        st.close()
        return True, f"abre e decifra; última execução: #{ult[0]['id']} {ult[0]['status']}" if ult else "abre (vazio)"

    for nome in SEGREDOS_ESPERADOS:
        checar(f"segredo {nome}", lambda n=nome: (segredos.obter(n) is not None, "guardado"))

    def bigquery():
        from google.cloud import bigquery as bq

        cliente = bq.Client(project=settings["bigquery"]["job_project"])
        tabela = (task or {}).get("fonte", {}).get("tabela_monitorada")
        if not tabela:
            return True, "cliente criado (tarefa sem tabela monitorada)"
        return True, f"metadado lido; última carga {cliente.get_table(tabela).modified.isoformat()}"

    def outlook():
        p = _powershell("(New-Object -ComObject Outlook.Application).Session.Accounts | "
                        "ForEach-Object { $_.SmtpAddress }")
        contas = [l for l in p.stdout.split() if "@" in l]
        return bool(contas), f"Outlook clássico acessível ({len(contas)} conta(s))" if contas else "Outlook clássico indisponível"

    def agendadas():
        p = _powershell("Get-ScheduledTask | Where-Object TaskName -like 'Radar*' | ForEach-Object { $_.TaskName }")
        nomes = [l.strip() for l in p.stdout.splitlines() if l.strip()]
        return True, ("agendadas: " + ", ".join(nomes)) if nomes else "nenhuma tarefa agendada nesta máquina"

    def sandbox():
        sb = settings.get("sandbox", {})
        return True, f"sandbox {'ATIVO' if sb.get('ativo', True) else 'DESLIGADO'}; canais permitidos: " + \
            ", ".join(sb.get("canais_permitidos", []))

    checar("chaves", chaves)
    checar("banco de dados", banco)
    checar("BigQuery", bigquery)
    checar("Outlook", outlook)
    checar("tarefas agendadas", agendadas)
    checar("sandbox", sandbox)
    return r
