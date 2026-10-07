"""Movimentação das CDs entre uma leitura e outra: saiu da lista (resolvida?) ou mudou de CT.

Compara a foto (snapshot) da última execução real com a leitura atual. Funções puras, sem I/O,
para ficarem fáceis de testar. O que fica guardado (cifrado) é só o conjunto de campos configurado
em `acompanhamento.campos_snapshot`.
"""
from __future__ import annotations

TIPOS = ("resolvida", "voltou_gfw", "saiu_criterio", "nao_encontrada", "mudou_ct")


def campos_snapshot(task: dict) -> list[str]:
    ac = task.get("acompanhamento", {})
    campos = list(ac.get("campos_snapshot") or task["mensagem"]["campos_exibidos"])
    for c in ac.get("campos_criticos", []):
        if c not in campos:
            campos.append(c)
    return campos


def payload_snapshot(linha: dict, campo_chave: str, campos: list[str]) -> dict:
    p = {"chave": str(linha[campo_chave])}
    for c in campos:
        v = linha.get(c)
        p[c] = None if v is None else str(v)
    return p


def detectar(anterior: dict[str, dict], atuais: dict[str, dict], criticos: list[str]):
    """anterior: {hash: payload do snapshot}; atuais: {hash: linha}. Retorna (saidas, mudancas).

    saidas   = [(hash, payload_anterior)]
    mudancas = [(hash, payload_anterior, linha_atual, [campos que mudaram])]
    Campos que o snapshot antigo não tinha são ignorados (não dá para comparar).
    """
    saidas = [(h, p) for h, p in anterior.items() if h not in atuais]
    mudancas = []
    for h, linha in atuais.items():
        antes = anterior.get(h)
        if not antes:
            continue
        mudou = [c for c in criticos if c in antes and antes[c] != (None if linha.get(c) is None else str(linha.get(c)))]
        if mudou:
            mudancas.append((h, antes, linha, mudou))
    return saidas, mudancas


def classificar_saida(resolucao: dict | None, cts_gfw: set[str]) -> str:
    """resolucao = última medida da nota no SAP/BigQuery (ou None se não achou)."""
    if resolucao is None:
        return "nao_encontrada"
    if str(resolucao.get("Status_do_Sistema_Nota")) == "I0072":
        return "resolvida"
    if str(resolucao.get("CT_Atual")) in cts_gfw:
        return "voltou_gfw"
    return "saiu_criterio"


def _resumo_item(p: dict, campos_resumo: list[str]) -> str:
    partes = [str(p[c]) for c in campos_resumo if p.get(c)]
    return " · ".join(partes)


def montar_eventos(task: dict, saidas, mudancas, resolucoes: dict[str, dict]) -> list[dict]:
    """Eventos prontos para o cartão e para o banco. `resolucoes` é indexado pela chave (nota)."""
    ac = task.get("acompanhamento", {})
    cts_gfw = {str(c) for c in ac.get("cts_gfw", [])}
    campos_resumo = ac.get("campos_resumo", [])
    campo_ct = (ac.get("campos_criticos") or [None])[0]
    campo_origem = task.get("sinais", {}).get("vazamento", {}).get("origem")
    eventos = []
    for h, p in saidas:
        res = (resolucoes or {}).get(p["chave"])
        tipo = classificar_saida(res, cts_gfw)
        ev = {"tipo": tipo, "hash": h, "nota": p["chave"], "resumo": _resumo_item(p, campos_resumo),
              "origem": p.get(campo_origem) if campo_origem else None,
              "dias": p.get("Dias_em_Aberto"), "ct_antes": p.get(campo_ct) if campo_ct else None}
        if res:
            ev["ct_depois"] = res.get("Desc_CT_Atual")
        eventos.append(ev)
    for h, antes, linha, mudou in mudancas:
        eventos.append({"tipo": "mudou_ct", "hash": h, "nota": antes["chave"],
                        "origem": antes.get(campo_origem) if campo_origem else None,
                        "resumo": _resumo_item(antes, campos_resumo), "dias": linha.get("Dias_em_Aberto"),
                        "ct_antes": antes.get(campo_ct) if campo_ct else None,
                        "ct_depois": linha.get(campo_ct) if campo_ct else None})
    return eventos
