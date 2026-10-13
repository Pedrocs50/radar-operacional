"""Vigia do esquema da tabela de origem: avisa quando colunas somem, aparecem ou mudam de tipo.

Hoje só descobrimos que uma coluna mudou quando uma execução falha (SCHEMA_MUDOU). Comparar o esquema (só metadado do BigQuery,
custo zero) uma vez por dia permite avisar o dono antes. A comparação guarda o esquema anterior e só acusa cada mudança uma vez.
"""
from __future__ import annotations

import json


def comparar(atual: dict[str, str], anterior: dict[str, str] | None) -> dict:
    if anterior is None:
        return {"primeira_vez": True, "removidas": [], "adicionadas": [], "tipo_mudou": []}
    return {
        "primeira_vez": False,
        "removidas": sorted(set(anterior) - set(atual)),
        "adicionadas": sorted(set(atual) - set(anterior)),
        "tipo_mudou": sorted(c for c in set(atual) & set(anterior) if atual[c] != anterior[c]),
    }


def verificar(task: dict, fonte, storage) -> dict | None:
    """None se a tarefa/fonte não permite verificar. Atualiza a base de comparação."""
    if not hasattr(fonte, "esquema") or not task.get("fonte", {}).get("tabela_monitorada"):
        return None
    atual = fonte.esquema()
    chave = f"esquema:{task['id']}"
    guardado = storage.estado_get(chave)
    resultado = comparar(atual, json.loads(guardado) if guardado else None)
    storage.estado_set(chave, json.dumps(atual, sort_keys=True))
    resultado["colunas"] = len(atual)
    return resultado
