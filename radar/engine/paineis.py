"""Painéis do relatório diário: contagem das CDs abertas por uma coluna (CT atual, CT de origem, tipo de defeito,
responsável...). Funções puras; o desenho da imagem fica em `channels/grafico.py`.

Configurados em `graficos:` no YAML da tarefa. Valores vazios viram "(sem informação)"; além de `top` categorias,
o restante é somado em "Outros".
"""
from __future__ import annotations

from collections import Counter

SEM_INFO = "(sem informação)"


def _rotulo(v) -> str:
    texto = " ".join(str(v).split()) if v is not None else ""
    return texto if texto and texto != "0" else SEM_INFO


def contar(estoque: list[dict], campo: str, top: int = 8) -> list[tuple[str, int, bool]]:
    """[(rotulo, quantidade, é_outros)] em ordem decrescente; o excedente de `top` vira uma linha "Outros (k)"."""
    contagem = Counter(_rotulo(l.get(campo)) for l in estoque)
    ordenado = sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0] == SEM_INFO, kv[0]))
    if len(ordenado) <= top:
        return [(r, n, False) for r, n in ordenado]
    resto = ordenado[top:]
    linhas = [(r, n, False) for r, n in ordenado[:top]]
    linhas.append((f"Outros ({len(resto)})", sum(n for _, n in resto), True))
    return linhas


def colunas_necessarias(cfg: dict | None) -> list[str]:
    if not cfg or not cfg.get("ativo"):
        return []
    return [p["campo"] for p in cfg.get("paineis", [])]


def preparar(task: dict, estoque: list[dict]) -> dict:
    """{"paineis": [{"titulo", "campo", "total", "linhas": [(rotulo, n, outros)]}]} ou {} se não configurado."""
    cfg = task.get("graficos")
    if not cfg or not cfg.get("ativo") or not estoque:
        return {}
    top = cfg.get("top", 8)
    return {"paineis": [{"titulo": p["titulo"], "campo": p["campo"], "total": len(estoque),
                         "linhas": contar(estoque, p["campo"], top)} for p in cfg.get("paineis", [])]}


def texto_alternativo(paineis: list[dict]) -> str:
    """Descrição em texto do painel, para leitores de tela e clientes que bloqueiam imagens."""
    partes = []
    for p in paineis:
        if p["linhas"]:
            r, n, _ = p["linhas"][0]
            partes.append(f"{p['titulo']}: maior grupo {r} com {n} de {p['total']}")
    return "Painel das CDs abertas. " + "; ".join(partes)
