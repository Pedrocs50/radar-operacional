"""Sinais de atenção sobre o estoque de CDs: o que exige ação, além de "chegou uma nova".

Tudo calculado a partir das colunas que o SQL já devolve. Funções puras (sem I/O), configuradas em
`sinais:` no YAML da tarefa. Cada sinal vira, no mesmo formato, itens para o resumo, o e-mail, o Excel,
a tabela em imagem e o Teams:

- parada          CD sem movimento há X dias (`Dias_sem_Fluxo`), diferente de "aberta há X dias"
- plano_vencido   data final planejada já passou
- sem_plano       sem data final planejada
- sem_responsavel ninguém é dono da próxima ação
- vazamento       de quais CTs da GFW as CDs mais saem (estoque, entradas e resolvidas por CT de origem)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

ATENCAO = "Atenção"   # nome da coluna de marcas na tabela/Excel
ORDEM = ["parada", "plano_vencido", "sem_plano", "sem_responsavel"]
TITULOS = {
    "parada": "Paradas (sem movimento)",
    "plano_vencido": "Plano vencido",
    "sem_plano": "Sem data planejada",
    "sem_responsavel": "Sem responsável pela próxima ação",
}
ICONES = {"parada": "⏸", "plano_vencido": "📅", "sem_plano": "∅", "sem_responsavel": "👤"}


# ------------------------------------------------------------------ leitura tolerante dos dados do SAP
def _num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _data(v) -> date | None:
    """Datas vazias do SAP (0000-00-00, 0001-01-01, 9999-12-31) valem como ausentes."""
    if isinstance(v, datetime):
        v = v.date()
    if isinstance(v, str):
        try:
            v = date.fromisoformat(v.strip()[:10])
        except ValueError:
            return None
    if not isinstance(v, date) or not (2000 <= v.year <= 2100):
        return None
    return v


def _hora(v) -> time:
    if isinstance(v, datetime):
        return v.time()
    if isinstance(v, time):
        return v
    if isinstance(v, str):
        try:
            return time.fromisoformat(v.strip())
        except ValueError:
            pass
    return time(23, 59, 59)  # sem hora: o plano vale até o fim do dia


def _vazio(v) -> bool:
    return v is None or str(v).strip() == "" or str(v).strip() in ("0", "00000000")


def agora_local(fuso: str = "America/Sao_Paulo") -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(fuso)).replace(tzinfo=None)
    except Exception:  # sem base de fusos no Windows: usa o relógio local
        return datetime.now()


# ------------------------------------------------------------------ configuração
def ativo(cfg: dict, nome: str) -> bool:
    return bool(cfg.get(nome, {}).get("ativo", False))


def colunas_necessarias(cfg: dict) -> list[str]:
    cols: list[str] = []
    if ativo(cfg, "parada"):
        cols.append(cfg["parada"]["campo"])
    if ativo(cfg, "plano") or ativo(cfg, "sem_plano"):
        cols.append(cfg["plano"]["campo_fim"])
    if ativo(cfg, "sem_responsavel"):
        cols += cfg["sem_responsavel"]["campos"]
    if ativo(cfg, "vazamento"):
        cols.append(cfg["vazamento"]["origem"])
    return cols


def _resumo(l: dict, cfg: dict) -> str:
    campos = cfg.get("campos_resumo", [])
    return " · ".join(str(l[c]) for c in campos if not _vazio(l.get(c)))


# ------------------------------------------------------------------ sinais por CD
def calcular(estoque: list[dict], cfg: dict, chave: str, agora: datetime | None = None) -> dict[str, dict]:
    """Retorna {sinal: {"titulo", "icone", "itens": [...], "total"}} só para os sinais ativos."""
    agora = agora or agora_local(cfg.get("fuso", "America/Sao_Paulo"))
    saida: dict[str, dict] = {}

    def item(l, detalhe, tag, ordem):
        return {"nota": str(l.get(chave)), "resumo": _resumo(l, cfg), "detalhe": detalhe, "tag": tag,
                "dias_aberto": _num(l.get("Dias_em_Aberto")), "ordem": ordem}

    def fechar(nome, itens):
        itens.sort(key=lambda i: -i["ordem"])
        saida[nome] = {"titulo": TITULOS[nome], "icone": ICONES[nome], "itens": itens, "total": len(itens)}

    if ativo(cfg, "parada"):
        c, limite = cfg["parada"]["campo"], cfg["parada"].get("limite_dias", 7)
        itens = []
        for l in estoque:
            d = _num(l.get(c))
            if d is not None and d >= limite:
                itens.append(item(l, f"{d} dia(s) sem movimento", f"PARADA {d}d", d))
        fechar("parada", itens)
        saida["parada"]["limite"] = limite

    if ativo(cfg, "plano"):
        p = cfg["plano"]
        vencidos, sem = [], []
        for l in estoque:
            fim = _data(l.get(p["campo_fim"]))
            if fim is None:
                sem.append(item(l, "sem data final planejada", "SEM PLANO", _num(l.get("Dias_em_Aberto")) or 0))
                continue
            limite = datetime.combine(fim, _hora(l.get(p.get("campo_hora_fim", ""))))
            if limite < agora:
                atraso = (agora.date() - fim).days
                texto = "venceu hoje" if atraso == 0 else f"venceu há {atraso} dia(s)"
                vencidos.append(item(l, f"plano {texto} ({fim:%d/%m})", "PLANO VENCIDO", atraso))
        fechar("plano_vencido", vencidos)
        fechar("sem_plano", sem)

    if ativo(cfg, "sem_responsavel"):
        itens = [item(l, "sem responsável", "SEM RESP.", _num(l.get("Dias_em_Aberto")) or 0)
                 for l in estoque if all(_vazio(l.get(c)) for c in cfg["sem_responsavel"]["campos"])]
        fechar("sem_responsavel", itens)
    return saida


def marcas(sinais: dict[str, dict]) -> dict[str, list[str]]:
    """{nota: [tags]} para a coluna "Atenção" da tabela e do Excel."""
    m: dict[str, list[str]] = defaultdict(list)
    for nome in ORDEM:
        for i in sinais.get(nome, {}).get("itens", []):
            m[i["nota"]].append(i["tag"])
    return dict(m)


# ------------------------------------------------------------------ vazamento por CT de origem
def vazamento(estoque: list[dict], entradas: list[dict], resolvidas: list[dict], cfg: dict, chave: str,
              agora: datetime | None = None) -> list[dict]:
    """Por CT de origem: abertas agora, média de dias, entradas (7 e 30 dias) e resolvidas (30 dias).

    entradas   = alertas registrados [{"quando": ISO, "chave": nota, <campos do snapshot>}]
    resolvidas = eventos de resolução [{"quando": ISO, "origem": CT}]
    A origem de uma entrada vem do próprio registro; se não tiver (registros antigos), vem do estoque atual.
    """
    campo = cfg["vazamento"]["origem"]
    agora = (agora or datetime.now().astimezone()).astimezone()
    corte7, corte30 = agora - timedelta(days=7), agora - timedelta(days=30)
    origem_atual = {str(l.get(chave)): str(l.get(campo) or "n/d") for l in estoque}

    linhas: dict[str, dict] = {}

    def ct(nome):
        return linhas.setdefault(nome, {"ct": nome, "abertas": 0, "soma_dias": 0, "com_dias": 0,
                                        "entraram_7d": 0, "entraram_30d": 0, "resolvidas_30d": 0})

    for l in estoque:
        r = ct(str(l.get(campo) or "n/d"))
        r["abertas"] += 1
        d = _num(l.get("Dias_em_Aberto"))
        if d is not None:
            r["soma_dias"] += d
            r["com_dias"] += 1
    for e in entradas:
        quando = datetime.fromisoformat(e["quando"]).astimezone()
        nome = e.get(campo) or origem_atual.get(str(e.get("chave")), "n/d")
        if quando >= corte30:
            ct(nome)["entraram_30d"] += 1
        if quando >= corte7:
            ct(nome)["entraram_7d"] += 1
    for e in resolvidas:
        if datetime.fromisoformat(e["quando"]).astimezone() >= corte30:
            ct(e.get("origem") or "n/d")["resolvidas_30d"] += 1

    total = sum(r["abertas"] for r in linhas.values()) or 1
    saida = []
    for r in linhas.values():
        r["media_dias"] = round(r["soma_dias"] / r["com_dias"], 1) if r["com_dias"] else None
        r["percentual"] = round(100 * r["abertas"] / total)
        saida.append({k: v for k, v in r.items() if k not in ("soma_dias", "com_dias")})
    return sorted(saida, key=lambda r: (-r["abertas"], -r["entraram_30d"], r["ct"]))


def preparar(task: dict, estoque: list[dict], storage, chave: str, agora: datetime | None = None) -> dict:
    """Tudo que o resumo, o e-mail e o Teams precisam: sinais, marcas por CD e vazamento por CT de origem.
    Devolve {} se a tarefa não configura `sinais:`."""
    from datetime import timezone

    cfg = task.get("sinais")
    if not cfg:
        return {}
    s = calcular(estoque, cfg, chave, agora)
    saida = {"sinais": s, "marcas": marcas(s)}
    if ativo(cfg, "vazamento"):
        desde = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
        resolvidas = [e for e in storage.listar_eventos(task["id"], desde) if e["tipo"] in ("resolvida", "voltou_gfw")]
        saida["vazamento"] = vazamento(estoque, storage.alertas_desde(task["id"], desde), resolvidas, cfg, chave)
    return saida
