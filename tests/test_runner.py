import pytest

from radar.engine.runner import ErroDeTarefa, executar
from tests.conftest import FonteFalsa

SEGREDO = "TEXTO-SENSIVEL-XYZ"


def linhas(*notas):
    return [{"Nota": n, "Descricao_do_Problema": f"{SEGREDO} {n}", "Data_da_CD": "2026-10-06"} for n in notas]


def test_dry_run_nao_grava_estado(task, storage, crypto, settings):
    f = FonteFalsa(linhas("1", "2"))
    r1 = executar(task, f, storage, crypto, settings, dry_run=True)
    r2 = executar(task, f, storage, crypto, settings, dry_run=True)
    assert r1["n_novos"] == 2 and r2["n_novos"] == 2  # nada foi marcado como avisado
    assert storage.hashes_ja_avisados("t1") == set()


def test_execucao_real_nao_repete(task, storage, crypto, settings):
    r1 = executar(task, FonteFalsa(linhas("1", "2")), storage, crypto, settings, dry_run=False)
    r2 = executar(task, FonteFalsa(linhas("1", "2")), storage, crypto, settings, dry_run=False)
    assert (r1["n_novos"], r2["n_novos"]) == (2, 0)
    assert r2["status"] == "sem_novidade"


def test_so_o_item_novo_aparece(task, storage, crypto, settings):
    executar(task, FonteFalsa(linhas("1")), storage, crypto, settings, dry_run=False)
    r = executar(task, FonteFalsa(linhas("1", "2")), storage, crypto, settings, dry_run=False)
    assert r["n_novos"] == 1


def test_duplicados_na_mesma_leitura(task, storage, crypto, settings):
    r = executar(task, FonteFalsa(linhas("1", "1", " 1")), storage, crypto, settings, dry_run=True)
    assert r["n_novos"] == 1


def test_flag_todos_ignora_estado(task, storage, crypto, settings):
    executar(task, FonteFalsa(linhas("1")), storage, crypto, settings, dry_run=False)
    r = executar(task, FonteFalsa(linhas("1")), storage, crypto, settings, dry_run=True, forcar_todos=True)
    assert r["n_novos"] == 1


def test_schema_mudou_gera_falha_com_codigo(task, storage, crypto, settings):
    f = FonteFalsa([{"Nota": "1", "Data_da_CD": "x"}])  # falta Descricao_do_Problema
    with pytest.raises(ErroDeTarefa):
        executar(task, f, storage, crypto, settings, dry_run=True)
    e = storage.listar_execucoes("t1")[0]
    assert e["status"] == "falha" and e["codigo_erro"] == "SCHEMA_MUDOU"


def test_banco_nao_guarda_dado_em_claro(task, storage, crypto, settings, tmp_path):
    executar(task, FonteFalsa(linhas("12345")), storage, crypto, settings, dry_run=False)
    storage.conn.execute("PRAGMA wal_checkpoint(FULL)")
    bruto = b"".join(p.read_bytes() for p in tmp_path.glob("t.db*"))
    assert SEGREDO.encode() not in bruto
    assert b"12345" not in bruto  # nem o identificador (só o índice cego)


def test_mensagem_cifrada_pode_ser_lida_de_volta(task, storage, crypto, settings):
    r = executar(task, FonteFalsa(linhas("7")), storage, crypto, settings, dry_run=True)
    msg = storage.ler_mensagem(r["execucao_id"])
    assert msg["itens"][0]["Nota"] == "7"


def test_preview_escapa_html(task, storage, crypto, settings):
    f = FonteFalsa([{"Nota": "1", "Descricao_do_Problema": "<script>alert(1)</script>", "Data_da_CD": "x"}])
    r = executar(task, f, storage, crypto, settings, dry_run=True)
    html = open(r["preview"], encoding="utf-8").read()
    assert "<script>alert(1)</script>" not in html


def test_sandbox_bloqueou_nao_marca_como_avisado(task, storage, crypto, settings):
    task = {**task, "canais": ["preview", "teams:teste"]}  # teams:teste fora de canais_permitidos
    r = executar(task, FonteFalsa(linhas("1")), storage, crypto, settings, dry_run=False)
    assert r["bloqueados_sandbox"] == ["teams:teste"] and r["enviados"] == []
    assert storage.hashes_ja_avisados("t1") == set()


def test_so_preview_marca_como_avisado(task, storage, crypto, settings):
    task = {**task, "canais": ["preview"]}
    executar(task, FonteFalsa(linhas("1")), storage, crypto, settings, dry_run=False)
    assert len(storage.hashes_ja_avisados("t1")) == 1


def test_pasta_de_preview_relativa_usa_a_raiz(task, storage, crypto, settings, tmp_path, monkeypatch):
    from radar import config

    monkeypatch.setattr(config, "RAIZ", tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    settings = {**settings, "preview": {"dir": "data/prev", "retencao_horas": 24}}
    r = executar(task, FonteFalsa(linhas("1")), storage, crypto, settings, dry_run=True)
    assert r["preview"].startswith(str(tmp_path / "data" / "prev"))


def test_limite_corta_os_itens(task, storage, crypto, settings):
    r = executar(task, FonteFalsa(linhas("1", "2", "3")), storage, crypto, settings, dry_run=True, limite=1)
    assert r["n_novos"] == 1 and r["n_itens"] == 3
