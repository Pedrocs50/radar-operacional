import sqlite3
from datetime import datetime, timedelta, timezone

from radar import __main__ as cli
from radar import config, manutencao, saude, vida
from radar.engine.runner import executar
from tests.conftest import FonteFalsa


def ambiente(tmp_path, monkeypatch, storage):
    monkeypatch.setattr(config, "RAIZ", tmp_path)
    return {"storage": {"db_path": "t.db"}, "backup": {"pasta": "bk", "manter": 3}}


def test_backup_copia_confere_integridade_e_aplica_retencao(tmp_path, monkeypatch, storage):
    settings = ambiente(tmp_path, monkeypatch, storage)
    # o fixture do storage cria tmp_path/t.db com as tabelas do robô; garante dados para copiar
    storage.registrar_verificacao("t1", True)
    inicio = datetime(2026, 10, 7, 12, 0, 0)
    for i in range(5):
        r = manutencao.fazer_backup(settings, inicio + timedelta(minutes=i))
    copias = sorted((tmp_path / "bk").glob("radar-*.db"))
    assert len(copias) == 3 and copias[-1] == r["arquivo"]                      # retenção: só as 3 mais novas
    ok = sqlite3.connect(str(r["arquivo"]))
    assert ok.execute("SELECT COUNT(*) FROM verificacoes").fetchone()[0] == 1     # a cópia tem os dados
    ok.close()
    assert manutencao.ultimo_backup(settings) is not None


def test_backup_com_copia_extra_e_banco_ausente(tmp_path, monkeypatch, storage):
    settings = ambiente(tmp_path, monkeypatch, storage)
    settings["backup"]["copiar_para"] = [str(tmp_path / "outro_disco")]
    r = manutencao.fazer_backup(settings)
    assert (tmp_path / "outro_disco" / r["arquivo"].name).exists() and len(r["copias"]) == 1
    settings["storage"]["db_path"] = "nao_existe.db"
    try:
        manutencao.fazer_backup(settings)
    except manutencao.ErroDeManutencao as e:
        assert e.codigo == "BANCO_NAO_ENCONTRADO"
    else:
        raise AssertionError("deveria falhar")


def test_atualizar_para_no_primeiro_erro_e_indica_a_versao_anterior(monkeypatch, capsys):
    chamadas = []

    class R:
        def __init__(self, cod, out="", err=""):
            self.returncode, self.stdout, self.stderr = cod, out, err

    def falso(args, **k):
        chamadas.append(args[1] if args[0] != "git" else " ".join(args[1:]))
        if args[:2] == ["git", "pull"]:
            return R(1, "", "conflito")
        return R(0, "abc1234\n")

    r = manutencao.atualizar(executar=falso)
    assert [x[1] for x in r] == [True, False] and r[1][2] == "conflito"
    assert not any("pytest" in c for c in chamadas)                              # parou antes dos testes
    monkeypatch.setattr(manutencao, "atualizar", lambda sem_testes=False: r)
    assert cli.cmd_atualizar(type("A", (), {"sem_testes": False})()) == 1
    assert "git checkout abc1234" in capsys.readouterr().out


def test_vida_ok_quando_tudo_em_dia_e_alerta_quando_para(storage, tmp_path, monkeypatch):
    settings = ambiente(tmp_path, monkeypatch, storage)
    manutencao.fazer_backup(settings)
    agora = datetime.now(timezone.utc)
    storage.registrar_verificacao("t1", True)
    info = vida.coletar(storage, "t1", settings, agora)
    assert vida.avaliar(info) == []
    titulo, texto, nivel = vida.montar(info, [])
    assert titulo.startswith("Estou vivo") and nivel == "info" and "Último backup" in texto
    # vigia parado há 2 horas, sem backup recente
    antigo = agora + timedelta(hours=2)
    problemas = vida.avaliar(vida.coletar(storage, "t1", settings, antigo))
    assert any("sem verificar" in p for p in problemas)
    titulo, _, nivel = vida.montar(vida.coletar(storage, "t1", settings, antigo), problemas)
    assert titulo.startswith("ATENÇÃO") and nivel == "atencao"
    # nunca verificou
    assert any("nunca" in p for p in vida.avaliar(vida.coletar(storage, "outra", settings, agora)))


def test_cmd_vida_so_envia_com_flag_e_usa_aviso_informativo(storage, tmp_path, monkeypatch):
    settings = ambiente(tmp_path, monkeypatch, storage)
    manutencao.fazer_backup(settings)
    storage.registrar_verificacao("t1", True)
    enviados = []
    monkeypatch.setattr(cli.config, "carregar_settings", lambda: settings)
    monkeypatch.setattr(cli.config, "carregar_tarefa", lambda t: {"id": "t1"})
    monkeypatch.setattr(cli, "_abrir", lambda s: (storage.crypto, storage))
    monkeypatch.setattr(saude, "montar_avisador", lambda s, t: lambda *a: enviados.append(a))
    args = lambda enviar: type("A", (), {"task": "t1", "enviar": enviar})()
    assert cli.cmd_vida(args(False)) == 0 and enviados == []
    assert cli.cmd_vida(args(True)) == 0 and enviados[0][0] == "dono" and enviados[0][3] == "info"


def test_estatisticas_contam_execucoes_reais_bytes_e_cargas(storage, crypto, settings):
    task = {"id": "t1", "modo": "novas", "canais": ["preview"], "fonte": {"campo_chave": "Nota"},
            "mensagem": {"titulo": "x", "campos_exibidos": ["Nota"]}}

    class Fonte(FonteFalsa):
        ultimo_bytes = 2_000_000_000

    executar(task, Fonte([{"Nota": "1"}]), storage, crypto, settings, dry_run=False)
    executar(task, Fonte([{"Nota": "1"}]), storage, crypto, settings, dry_run=True)   # dry-run não conta
    storage.registrar_atualizacao("t1", "2026-10-07T10:00:00+00:00")
    e = storage.estatisticas("t1", "2000-01-01T00:00:00+00:00")
    assert (e["execucoes"], e["novos"], e["bytes"], e["cargas"]) == (1, 1, 2_000_000_000, 1)
