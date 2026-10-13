import json
from datetime import datetime, timedelta, timezone

import pytest

from radar import __main__ as cli
from radar import canario, esquema, vida
from radar.channels.base import ErroDeEnvio
from radar.engine.runner import executar
from tests.conftest import FonteFalsa

AGORA = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def tarefa(canais):
    return {"id": "t1", "modo": "novas", "canais": list(canais), "fonte": {"campo_chave": "Nota"},
            "mensagem": {"titulo": "x", "campos_exibidos": ["Nota"], "campo_data_referencia": "Data_da_CD"}}


def linhas(*notas):
    return [{"Nota": n, "Data_da_CD": "x"} for n in notas]


def settings_com(settings, *canais):
    return {**settings, "sandbox": {"ativo": True, "canais_permitidos": ["preview", *canais]}}


class Canal:
    """Enviador falso que pode estar fora do ar e registra o que recebeu."""

    def __init__(self, fora=False):
        self.fora, self.recebido = fora, []

    def __call__(self, msg):
        if self.fora:
            raise ErroDeEnvio("TEAMS_HTTP_500")
        self.recebido.append([i["Nota"] for i in msg["itens"]])


# ------------------------------------------------------------------ entrega independente por canal
def test_teams_fora_do_ar_nao_impede_o_email(storage, crypto, settings):
    teams, email = Canal(fora=True), Canal()
    t, s = tarefa(["preview", "teams:a", "email:b"]), settings_com(settings, "teams:a", "email:b")
    env = {"teams:a": teams, "email:b": email}
    with pytest.raises(ErroDeEnvio):
        executar(t, FonteFalsa(linhas("1", "2")), storage, crypto, s, dry_run=False, enviadores=env)
    assert email.recebido == [["1", "2"]]                       # o e-mail saiu mesmo com o Teams fora
    assert storage.hashes_ja_avisados("t1") == set()            # mas o item continua pendente para o Teams


def test_na_nova_tentativa_so_o_canal_que_falhou_repete(storage, crypto, settings):
    teams, email = Canal(fora=True), Canal()
    t, s = tarefa(["preview", "teams:a", "email:b"]), settings_com(settings, "teams:a", "email:b")
    env = {"teams:a": teams, "email:b": email}
    with pytest.raises(ErroDeEnvio):
        executar(t, FonteFalsa(linhas("1")), storage, crypto, s, dry_run=False, enviadores=env)
    teams.fora = False                                          # o Teams volta
    r = executar(t, FonteFalsa(linhas("1")), storage, crypto, s, dry_run=False, enviadores=env)
    assert teams.recebido == [["1"]] and email.recebido == [["1"]]   # e-mail NÃO foi reenviado
    assert sorted(r["enviados"]) == ["email:b", "teams:a"] and len(storage.hashes_ja_avisados("t1")) == 1
    r2 = executar(t, FonteFalsa(linhas("1")), storage, crypto, s, dry_run=False, enviadores=env)
    assert r2["n_novos"] == 0 and teams.recebido == [["1"]]     # depois de tudo entregue, nada se repete


def test_item_novo_depois_da_falha_vai_junto_sem_duplicar_o_antigo(storage, crypto, settings):
    teams, email = Canal(fora=True), Canal()
    t, s = tarefa(["preview", "teams:a", "email:b"]), settings_com(settings, "teams:a", "email:b")
    env = {"teams:a": teams, "email:b": email}
    with pytest.raises(ErroDeEnvio):
        executar(t, FonteFalsa(linhas("1")), storage, crypto, s, dry_run=False, enviadores=env)
    teams.fora = False
    executar(t, FonteFalsa(linhas("1", "2")), storage, crypto, s, dry_run=False, enviadores=env)
    assert email.recebido == [["1"], ["2"]]                     # o e-mail só recebeu o que ainda não tinha
    assert teams.recebido == [["1", "2"]]


def test_todos_forca_o_reenvio_ignorando_as_entregas(storage, crypto, settings):
    email = Canal()
    t, s = tarefa(["preview", "email:b"]), settings_com(settings, "email:b")
    executar(t, FonteFalsa(linhas("1")), storage, crypto, s, dry_run=False, enviadores={"email:b": email})
    executar(t, FonteFalsa(linhas("1")), storage, crypto, s, dry_run=False, enviadores={"email:b": email},
             forcar_todos=True)
    assert email.recebido == [["1"], ["1"]]


# ------------------------------------------------------------------ teste semanal do Teams
def test_canario_ok_registra_e_nao_incomoda(storage, monkeypatch):
    monkeypatch.setattr(canario.segredos, "obter", lambda n: "https://exemplo.com/x")
    avisos, enviados = [], []
    t = {"id": "t1", "canais": ["preview", "teams:teste", "email:teste"]}
    s = {"sandbox": {"ativo": True, "canais_permitidos": ["teams:teste"]}}
    r = canario.executar(t, s, storage, lambda *a: avisos.append(a), enviar=lambda m, u: enviados.append(m), agora=AGORA)
    assert r["resultados"] == {"teams:teste": "ok"} and avisos == [] and enviados[0]["tipo"] == "sistema"
    assert enviados[0]["itens"] == [] and enviados[0]["n_itens"] == 0          # nenhum dado operacional no cartão
    assert json.loads(storage.estado_get("canario:t1"))["falhas"] == {}


def test_canario_falha_avisa_o_dono_com_a_causa(storage, monkeypatch):
    monkeypatch.setattr(canario.segredos, "obter", lambda n: "https://exemplo.com/x")

    def quebra(m, u):
        raise ErroDeEnvio("TEAMS_HTTP_404")

    avisos = []
    t = {"id": "t1", "canais": ["teams:teste"]}
    r = canario.executar(t, {"sandbox": {"ativo": False}}, storage, lambda *a: avisos.append(a), enviar=quebra)
    assert r["falhas"] == {"teams:teste": "TEAMS_HTTP_404"}
    assert avisos[0][0] == "dono" and "TEAMS_HTTP_404" in avisos[0][2] and avisos[0][3] == "atencao"


def test_canario_respeita_o_sandbox_e_a_simulacao(storage):
    t = {"id": "t1", "canais": ["teams:teste", "teams:outro"]}
    s = {"sandbox": {"ativo": True, "canais_permitidos": ["teams:teste"]}}
    assert canario.canais_a_testar(t, s) == ["teams:teste"]
    r = canario.executar(t, s, storage, lambda *a: None, enviar_de_verdade=False)
    assert "simulação" in r["resultados"]["teams:teste"] and storage.estado_get("canario:t1") is None


# ------------------------------------------------------------------ esquema da tabela
def test_comparar_esquema():
    antes = {"a": "STRING", "b": "INTEGER", "c": "DATE"}
    r = esquema.comparar({"a": "STRING", "b": "STRING", "d": "DATE"}, antes)
    assert r["removidas"] == ["c"] and r["adicionadas"] == ["d"] and r["tipo_mudou"] == ["b"]
    assert esquema.comparar(antes, None)["primeira_vez"] and esquema.comparar(antes, antes)["removidas"] == []


def test_verificar_esquema_acusa_cada_mudanca_uma_vez(storage):
    class Fonte:
        def __init__(self, esq):
            self.esq = esq

        def esquema(self):
            return self.esq

    t = {"id": "t1", "fonte": {"tabela_monitorada": "p.d.t"}}
    assert esquema.verificar(t, Fonte({"a": "STRING"}), storage)["primeira_vez"]
    assert esquema.verificar(t, Fonte({"a": "STRING", "b": "DATE"}), storage)["adicionadas"] == ["b"]
    assert esquema.verificar(t, Fonte({"a": "STRING", "b": "DATE"}), storage)["adicionadas"] == []   # já acusada
    assert esquema.verificar({"id": "t1", "fonte": {}}, Fonte({}), storage) is None


# ------------------------------------------------------------------ aviso diário
def info_base(storage, settings, **extra):
    storage.registrar_verificacao("t1", True)
    info = vida.coletar(storage, "t1", settings)
    info.update(extra)
    return info


def test_vida_alerta_teams_falhando_esquema_mudado_e_lembra_das_chaves(storage, tmp_path, monkeypatch):
    from radar import config, manutencao

    monkeypatch.setattr(config, "RAIZ", tmp_path)
    settings = {"storage": {"db_path": "t.db"}, "backup": {"pasta": "bk"}}
    manutencao.fazer_backup(settings)
    info = info_base(storage, settings)
    assert vida.avaliar(info) == []
    titulo, texto, nivel = vida.montar(info, [])
    assert "LEMBRETE" in texto and "chaves-ok" in texto and nivel == "info"      # nunca confirmou as chaves
    info["canario"] = {"em": info["agora"].isoformat(timespec="seconds"), "falhas": {"teams:teste": "TEAMS_HTTP_404"}}
    info["esquema"] = {"primeira_vez": False, "removidas": ["Dias_sem_Fluxo"], "adicionadas": [], "tipo_mudou": [], "colunas": 50}
    problemas = vida.avaliar(info)
    assert any("teste semanal do Teams falhou" in p for p in problemas) and any("Dias_sem_Fluxo" in p for p in problemas)
    info["canario"] = {"em": (info["agora"] - timedelta(days=12)).isoformat(timespec="seconds"), "falhas": {}}
    assert any("não roda há 12 dias" in p for p in vida.avaliar({**info, "esquema": None}))
    info["chaves_confirmadas"] = datetime.now().astimezone()
    assert "LEMBRETE" not in vida.montar(info, [])[1]


def test_chaves_ok_silencia_o_lembrete(storage, monkeypatch):
    monkeypatch.setattr(cli, "_abrir", lambda s: (None, storage))
    monkeypatch.setattr(cli.config, "carregar_settings", lambda: {})
    cli.cmd_chaves_ok(None)
    assert storage.estado_get("chaves_confirmadas")
