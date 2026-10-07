"""Contrato comum dos canais de entrega."""
from __future__ import annotations


class ErroDeEnvio(Exception):
    """Falha ao entregar uma mensagem.

    Carrega só um código curto (ex.: TEAMS_HTTP_400). Nunca a URL do webhook
    nem o conteúdo da mensagem, porque o código vai para o log em claro.
    """

    def __init__(self, codigo: str):
        super().__init__(codigo)
        self.codigo = codigo
