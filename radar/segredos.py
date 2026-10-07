"""Segredos operacionais (ex.: URL do webhook do Teams).

Nunca ficam em arquivo do projeto nem no banco. Ordem de busca:
1. variável de ambiente RADAR_SECRET_<NOME> (desenvolvimento e testes)
2. Windows Credential Manager, via keyring
"""
from __future__ import annotations

import os

SERVICE = "radar-operacional"


def _nome_env(nome: str) -> str:
    return "RADAR_SECRET_" + nome.upper()


def obter(nome: str) -> str:
    valor = os.environ.get(_nome_env(nome))
    if not valor:
        try:
            import keyring

            valor = keyring.get_password(SERVICE, nome)
        except Exception:  # keyring indisponível
            valor = None
    if not valor:
        raise RuntimeError(
            f"Segredo '{nome}' não encontrado. Use: python -m radar guardar-segredo {nome}"
        )
    return valor


def salvar(nome: str, valor: str) -> None:
    import keyring

    keyring.set_password(SERVICE, nome, valor)
