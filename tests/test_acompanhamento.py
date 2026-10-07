from datetime import datetime, timedelta, timezone

from radar import saude
from radar.channels import teams_webhook
from radar.engine import movimentos as mov
from radar.engine.resumo import executar_resumo
from radar.engine.runner import executar
from tests.conftest import FonteFalsa

GFW = ["1", "2"]


def tarefa(canais=("preview",)):
    return {
        "id": "t1", "modo": "novas", "canais": list(canais),
        "fonte": {"campo_chave": "Nota_QM"},
        "mensagem": {"titulo": "x", "campos_exibidos": ["Nota_QM", "Descricao_CT_Atual"]},
        "acompanhamento": {"campos_criticos": ["Descricao_CT_Atual"], "campos_resumo": ["Modelo_Aeronave"],
                           "cts_gfw": GFW, "sql_resolucao_file": "x.sql"},
    }


def linha(nota, ct="HANGAR A", dias=3):
    return {"Nota_QM": nota, "Descricao_CT_Atual": ct, "Modelo_Aeronave": "EJETS E2", "Dias_em_Aberto": dias,
            "Faixa_de_Atraso": "1 a 3 dias"}


class FonteComResolucao(FonteFalsa):
    def __init__(self, linhas, resolucao=None):
        super().__init__(linhas)
        self.resolucao = resolucao or {}
        self.perguntou = []

    def resolver_notas(self, sql, notas):
        self.perguntou.append(list(notas))
        return {n: self.resolucao[n] for n in notas if n in self.resolucao}


def settings_com(settings, permitidos=("preview", "teams:teste")):
    return {**settings, "sandbox": {"ativo": True, "canais_permitidos": list(permitidos)}}


def test_detectar_saidas_e_mudancas():
    ant = {"h1": {"chave": "1", "Descricao_CT_Atual": "A"}, "h2": {"chave": "2", "Descricao_CT_Atual": "A"}}
    saidas, mud = mov.detectar(ant, {"h2": {"Descricao_CT_Atual": "B"}}, ["Descricao_CT_Atual"])
    assert [h for h, _ in saidas] == ["h1"]
    assert [m[0] for m in mud] == ["h2"] and mud[0][3] == ["Descricao_CT_Atual"]


def test_snapshot_antigo_sem_campos_nao_gera_mudanca():
    saidas, mud = mov.detectar({"h": {"chave": "1"}}, {"h": {"Descricao_CT_Atual": "B"}}, ["Descricao_CT_Atual"])
    assert saidas == [] and mud == []


def test_classificacao_das_saidas():
    cts = {"10"}
    assert mov.classificar_saida({"Status_do_Sistema_Nota": "I0072", "CT_Atual": "99"}, cts) == "resolvida"
    assert mov.classificar_saida({"Status_do_Sistema_Nota": "I0070", "CT_Atual": "10"}, cts) == "voltou_gfw"
    assert mov.classificar_saida({"Status_do_Sistema_Nota": "I0070", "CT_Atual": "99"}, cts) == "saiu_criterio"
    assert mov.classificar_saida(None, cts) == "nao_encontrada"


def test_primeira_execucao_nao_gera_movimento_e_segunda_detecta(storage, crypto, settings):
    t, s = tarefa(), settings_com(settings)
    f1 = FonteComResolucao([linha("10"), linha("20")])
    r1 = executar(t, f1, storage, crypto, s, dry_run=False)
    assert r1["n_movimentos"] == 0  # sem foto anterior: é só a base de referência
    f2 = FonteComResolucao([linha("20", ct="HANGAR B")],
                           {"10": {"Status_do_Sistema_Nota": "I0072", "CT_Atual": "99", "Desc_CT_Atual": "X"}})
    r2 = executar(t, f2, storage, crypto, s, dry_run=False)
    assert r2["n_movimentos"] == 2 and f2.perguntou == [["10"]]
    tipos = sorted(e["tipo"] for e in storage.listar_eventos("t1", "2000-01-01T00:00:00+00:00"))
    assert tipos == ["mudou_ct", "resolvida"]
    # terceira leitura igual à segunda: nada novo
    assert executar(t, FonteComResolucao([linha("20", ct="HANGAR B")]), storage, crypto, s,
                    dry_run=False)["n_movimentos"] == 0


def test_dry_run_calcula_mas_nao_grava(storage, crypto, settings):
    t, s = tarefa(), settings_com(settings)
    executar(t, FonteComResolucao([linha("10")]), storage, crypto, s, dry_run=False)
    r = executar(t, FonteComResolucao([]), storage, crypto, s, dry_run=True)
    assert r["n_movimentos"] == 1 and storage.listar_eventos("t1", "2000-01-01T00:00:00+00:00") == []


def test_movimento_bloqueado_pelo_sandbox_nao_perde_o_evento(storage, crypto, settings):
    t = tarefa(("preview", "teams:teste"))
    liberado = settings_com(settings)
    executar(t, FonteComResolucao([linha("10")]), storage, crypto, liberado, dry_run=False,
             enviadores={"teams:teste": lambda m: None})
    bloqueado = settings_com(settings, permitidos=("preview",))
    executar(t, FonteComResolucao([]), storage, crypto, bloqueado, dry_run=False)
    assert storage.listar_eventos("t1", "2000-01-01T00:00:00+00:00") == []  # ainda pendente
    enviados = []
    r = executar(t, FonteComResolucao([]), storage, crypto, liberado, dry_run=False,
                 enviadores={"teams:teste": enviados.append})
    assert enviados and enviados[0]["tipo"] == "movimentos" and r["n_movimentos"] == 1


def test_cartoes_do_teams_cabem_no_limite():
    eventos = [{"tipo": t, "nota": str(i), "resumo": "EJETS E2 · 123", "ct_antes": "A", "ct_depois": "B", "dias": 5}
               for i in range(40) for t in ("resolvida", "mudou_ct")]
    m = {"tipo": "movimentos", "titulo": "T", "dados_de": "x", "eventos": eventos, "marca": "R", "sandbox": False}
    import json
    assert len(json.dumps(teams_webhook.montar_payload(m)).encode()) <= 24_500
    s = {"tipo": "sistema", "titulo": "T", "texto": "texto", "nivel": "ok", "marca": "R"}
    assert "texto" in str(teams_webhook.montar_payload(s))


def test_resumo_dry_run_e_real(storage, crypto, settings):
    t = tarefa(("preview", "teams:teste", "email:teste"))
    t["email"] = {}
    s = settings_com(settings, ("preview", "teams:teste", "email:teste"))
    executar({**t, "canais": ["preview"]}, FonteComResolucao([linha("10", dias=40), linha("20")]), storage, crypto, s,
             dry_run=False)
    enviados = {}
    r = executar_resumo(t, FonteFalsa([linha("10", dias=40), linha("20")]), storage, crypto, s, dry_run=False,
                        enviadores={"teams:teste": lambda m: enviados.update(teams=m),
                                    "email:teste": lambda m: enviados.update(email=m)})
    assert sorted(r["enviados"]) == ["email:teste", "teams:teste"]
    assert enviados["teams"]["tipo"] == "resumo" and enviados["teams"]["geral"]["mais_antiga_dias"] == 40
    assert storage.estado_get("resumo_ultimo:t1")  # marcou como feito depois de entregar
    # dry-run não marca
    storage.conn.execute("DELETE FROM estado")
    executar_resumo(t, FonteFalsa([linha("10")]), storage, crypto, s, dry_run=True)
    assert storage.estado_get("resumo_ultimo:t1") is None


# ------------------------------------------------------------------ saúde
class Avisos:
    def __init__(self):
        self.lista = []

    def __call__(self, destino, titulo, texto, nivel):
        self.lista.append((destino, titulo))


def test_saude_instabilidade_e_recuperacao(storage):
    av = Avisos()
    t0 = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    assert saude.processar(storage, "t1", True, None, av, agora=t0) is None
    assert saude.processar(storage, "t1", False, "ConnectionError", av, agora=t0 + timedelta(minutes=5)) is None
    assert saude.processar(storage, "t1", False, "ConnectionError", av, agora=t0 + timedelta(minutes=10)) is None
    assert saude.processar(storage, "t1", False, "ConnectionError", av, agora=t0 + timedelta(minutes=15)) == "instabilidade"
    assert {d for d, _ in av.lista} == {"dono", "grupo"}
    av.lista.clear()
    # mais falhas não repetem o aviso
    assert saude.processar(storage, "t1", False, "ConnectionError", av, agora=t0 + timedelta(minutes=20)) is None
    assert av.lista == []
    assert saude.processar(storage, "t1", True, None, av, agora=t0 + timedelta(minutes=25)) == "recuperacao"
    assert {d for d, _ in av.lista} == {"dono", "grupo"}


def test_saude_lacuna_avisa_so_o_dono(storage):
    av = Avisos()
    t0 = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    saude.processar(storage, "t1", True, None, av, agora=t0)
    # a verificação anterior foi registrada "agora" real; força lacuna com relógio no futuro
    r = saude.processar(storage, "t1", True, None, av, agora=datetime.now(timezone.utc) + timedelta(hours=2))
    assert r == "lacuna" and [d for d, _ in av.lista] == ["dono"]


def test_falha_ao_avisar_nao_derruba(storage):
    def quebrado(*a):
        raise RuntimeError("sem rede")

    for i in range(3):
        saude.processar(storage, "t1", False, "X", quebrado)
    assert storage.estado_get("saude:t1") == "instavel"


def test_limpeza_tecnica_preserva_a_ultima_foto(storage, crypto, settings):
    t, s = tarefa(), settings_com(settings)
    executar(t, FonteComResolucao([linha("10")]), storage, crypto, s, dry_run=False)
    storage.conn.execute("UPDATE execucoes SET inicio='2020-01-01T00:00:00+00:00'")
    storage.limpar_historico_tecnico(14)
    assert storage.ultimo_snapshot("t1", 999)  # a última execução real continua com a foto


def test_leitura_vazia_suspeita_exige_confirmacao(storage, crypto, settings):
    t, s = tarefa(), settings_com(settings)
    base = FonteComResolucao([linha("1"), linha("2"), linha("3")])
    executar(t, base, storage, crypto, s, dry_run=False)
    # 1ª leitura vazia: pode ser carga incompleta da origem, não afirma que as CDs foram resolvidas
    r1 = executar(t, FonteComResolucao([]), storage, crypto, s, dry_run=False)
    assert r1["n_movimentos"] == 0 and storage.listar_eventos("t1", "2000-01-01T00:00:00+00:00") == []
    assert len(storage.ultimo_snapshot("t1", 999)) == 3  # a foto antiga continua valendo
    # 2ª leitura vazia seguida: confirma
    r2 = executar(t, FonteComResolucao([]), storage, crypto, s, dry_run=False)
    assert r2["n_movimentos"] == 3


def test_leitura_normal_zera_a_suspeita(storage, crypto, settings):
    t, s = tarefa(), settings_com(settings)
    executar(t, FonteComResolucao([linha("1"), linha("2"), linha("3")]), storage, crypto, s, dry_run=False)
    executar(t, FonteComResolucao([]), storage, crypto, s, dry_run=False)           # suspeita
    executar(t, FonteComResolucao([linha("1"), linha("2"), linha("3")]), storage, crypto, s, dry_run=False)
    r = executar(t, FonteComResolucao([]), storage, crypto, s, dry_run=False)       # volta a ser a 1ª
    assert r["n_movimentos"] == 0


def test_doctor_nao_vaza_e_nao_derruba(monkeypatch):
    from radar import doctor, segredos

    def sem_segredo(nome):
        raise RuntimeError("Segredo 'x' não encontrado")

    monkeypatch.setattr(segredos, "obter", sem_segredo)
    monkeypatch.setattr(doctor, "_powershell", lambda *a, **k: type("P", (), {"stdout": ""})())
    itens = doctor.verificar({"storage": {"db_path": "x.db"}, "bigquery": {"job_project": "p"}, "sandbox": {}})
    nomes = {n for n, _, _ in itens}
    assert "segredo teams_webhook_teste" in nomes and "Outlook" in nomes
    assert dict((n, d) for n, _, d in itens)["segredo teams_webhook_teste"] == "não encontrado"


def test_simulacao_gera_todos_os_cartoes_dentro_do_limite(tmp_path):
    import json

    from radar import config, simulacao

    task = config.carregar_tarefa("cds_gfw_fora_da_area")
    ex = simulacao.exemplos(task, {"sandbox": {"ativo": True}})
    assert len(ex) == 5 and all(m["titulo"].startswith("[EXEMPLO]") for m in ex.values())
    for m in ex.values():
        assert len(json.dumps(teams_webhook.montar_payload(m), ensure_ascii=False).encode()) <= 24_500
    saida = simulacao.salvar(ex, tmp_path, task)
    assert (tmp_path / "cartoes.html").exists() and (tmp_path / "exemplo_email.html").exists() and saida


def test_resumo_so_por_email_nao_posta_no_teams_nem_marca_como_feito(storage, crypto, settings):
    t = tarefa(("preview", "teams:teste", "email:teste"))
    t["email"] = {}
    s = settings_com(settings, ("preview", "teams:teste", "email:teste", "email:dono"))
    enviados = {}
    r = executar_resumo(t, FonteFalsa([linha("10")]), storage, crypto, s, dry_run=False, canais=["email:dono"],
                        enviadores={"teams:teste": lambda m: enviados.update(teams=m),
                                    "email:dono": lambda m: enviados.update(email=m)})
    assert r["enviados"] == ["email:dono"] and "teams" not in enviados and "email" in enviados
    assert storage.estado_get("resumo_ultimo:t1") is None  # envio parcial: o resumo "oficial" ainda vale
