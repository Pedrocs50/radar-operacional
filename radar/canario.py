"""Teste semanal do Teams ("canário"): confirma que o robô ainda consegue publicar no canal.

O fluxo do Teams está ligado à conta de quem o criou: se a conta for desativada, o fluxo apagado ou a URL trocada, o robô
passaria a falhar **sem ninguém perceber** até a próxima CD nova. Uma verificação semanal descobre isso cedo e avisa o dono
por e-mail. O cartão é discreto e não leva nenhum dado operacional.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import segredos
from .channels import teams_webhook
from .channels.base import ErroDeEnvio


def mensagem() -> dict:
    return {"tipo": "sistema", "titulo": "Verificação semanal de conexão", "marca": "RADAR OPERACIONAL", "nivel": "ok",
            "texto": "O Radar confirmou que consegue publicar neste canal. Nenhuma ação necessária.",
            "dados_de": "", "n_itens": 0, "n_novos": 0, "colunas": [], "itens": []}


def canais_a_testar(task: dict, settings: dict) -> list[str]:
    """Canais do Teams da tarefa que o sandbox permite."""
    sandbox = settings.get("sandbox", {})
    permitidos = set(sandbox.get("canais_permitidos", []))
    return [c for c in task.get("canais", []) if c.startswith("teams:")
            and (not sandbox.get("ativo", True) or c in permitidos)]


def executar(task: dict, settings: dict, storage, avisar, enviar=teams_webhook.enviar, enviar_de_verdade: bool = True,
             agora: datetime | None = None) -> dict:
    """Posta o cartão de teste em cada canal do Teams e registra o resultado. Falha avisa o dono."""
    resultados: dict[str, str] = {}
    for canal in canais_a_testar(task, settings):
        if not enviar_de_verdade:
            resultados[canal] = "não enviado (simulação)"
            continue
        try:
            enviar(mensagem(), segredos.obter("teams_webhook_" + canal.split(":", 1)[1]))
            resultados[canal] = "ok"
        except RuntimeError:
            resultados[canal] = "SEGREDO_AUSENTE"
        except ErroDeEnvio as e:
            resultados[canal] = e.codigo
    falhas = {c: r for c, r in resultados.items() if r != "ok" and enviar_de_verdade}
    if enviar_de_verdade:
        storage.estado_set(f"canario:{task['id']}", json.dumps(
            {"em": (agora or datetime.now(timezone.utc)).isoformat(timespec="seconds"), "falhas": falhas}))
    if falhas:
        texto = ("O teste semanal de publicação no Teams falhou:\n" + "\n".join(f"- {c}: {r}" for c, r in falhas.items())
                 + "\n\nCausas comuns: o fluxo foi apagado ou desativado, a conta dona do fluxo foi desativada ou mudou a "
                   "senha, ou a URL guardada é de outro fluxo. Recriar o fluxo no canal e guardar a URL nova "
                   "(guardar-segredo). Enquanto isso, o alerta de CD nova continua saindo por e-mail.")
        try:
            avisar("dono", "Teste semanal do Teams falhou", texto, "atencao")
        except Exception:  # aviso nunca derruba o teste
            pass
    return {"resultados": resultados, "falhas": falhas}
