from pathlib import Path

from radar import config

RAIZ = Path(__file__).resolve().parent.parent


def test_sql_mantem_filtros_originais():
    sql = (RAIZ / "sql" / "cds_novas_do_dia.sql").read_text(encoding="utf-8")
    for trecho in [
        "emb-prd-it-data-lakehouse-d8ff.opp_intermediate.consolidated_zqlrqm150_medidas",
        "Centro = 'SJK1'",
        "Tipo_de_Nota = 'CD'",
        "'10024696'", "'10015205'", "'10010172'", "'10010866'", "'10015208'",
        "'ESCAPE'", "'I0070'", "'I0072'",
        "WHERE n.Data_da_Nota = u.data_mais_recente",
    ]:
        assert trecho in sql
    assert "@" not in sql  # consulta mantida exatamente sem parâmetros


def test_todas_as_tarefas_tem_campos_obrigatorios():
    for t in config.listar_tarefas():
        for campo in ["id", "nome", "ativa", "modo", "fonte", "mensagem", "audiencia", "canais"]:
            assert campo in t, f"{t.get('id')} sem {campo}"
        assert t["fonte"]["campo_chave"] in t["mensagem"]["campos_exibidos"] or t["fonte"]["campo_chave"]


def test_tarefa_bigquery_aponta_para_sql_existente():
    t = config.carregar_tarefa("cds_novas_do_dia")
    assert (RAIZ / t["fonte"]["sql_file"]).exists()
    assert t["ativa"] is False  # nasce desligada


def test_status_heartbeat(tmp_path, monkeypatch, capsys):
    from radar import __main__ as cli
    from radar.engine.runner import executar
    from radar.storage.crypto import Crypto, gerar_chaves
    from radar.storage.db import Storage
    from tests.conftest import FonteFalsa

    enc, hm = gerar_chaves()
    st = Storage(tmp_path / "s.db", Crypto([enc], hm))
    monkeypatch.setattr(cli, "_abrir", lambda settings: (None, st))
    monkeypatch.setattr(cli.config, "carregar_settings", lambda: {})
    args = type("A", (), {"task": "t1", "max_horas": 26})()
    assert cli.cmd_status(args) == 1  # nunca rodou
    task = {"id": "t1", "modo": "novas", "fonte": {"campo_chave": "Nota"},
            "mensagem": {"titulo": "x", "campos_exibidos": ["Nota"]}}
    settings = {"preview": {"dir": str(tmp_path / "p")}, "sandbox": {}}
    executar(task, FonteFalsa([{"Nota": "1"}]), st, st.crypto, settings, dry_run=False)
    assert not cli.cmd_status(args)  # rodou agora: OK
