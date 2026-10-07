import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from radar.channels import teams_webhook as tw
from radar.channels.base import ErroDeEnvio
from radar.engine.runner import executar
from tests.conftest import FonteFalsa


# ------------------------------------------------------------ servidor local falso
@pytest.fixture
def servidor():
    estado = {"status": 202, "recebidos": []}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            estado["recebidos"].append(json.loads(self.rfile.read(n)))
            self.send_response(estado["status"])
            self.end_headers()

        def log_message(self, *a):  # silencia o log
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    estado["url"] = f"http://127.0.0.1:{srv.server_port}/hook"
    yield estado
    srv.shutdown()


def msg(n_itens=3):
    return {
        "titulo": "Teste", "dados_de": "06/10/2026 13:00", "n_itens": n_itens, "n_novos": n_itens,
        "colunas": ["Nota", "NS_Aviao", "CT", "Defeito", "Problema"],
        "itens": [{"Nota": str(i), "NS_Aviao": f"AV-{i}", "CT": "CT1", "Defeito": "D", "Problema": "P" * 500}
                  for i in range(n_itens)],
        "sandbox": True,
    }


# ------------------------------------------------------------------- cartão
def test_formato_do_payload():
    p = tw.montar_payload(msg())
    assert p["type"] == "message"
    anexo = p["attachments"][0]
    assert anexo["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert anexo["content"]["type"] == "AdaptiveCard"


def test_textos_longos_sao_cortados():
    texto = json.dumps(tw.montar_payload(msg(1)), ensure_ascii=False)
    assert "P" * 200 not in texto


def test_limite_de_itens_e_de_tamanho():
    p = tw.montar_payload(msg(200))
    assert len(json.dumps(p, ensure_ascii=False).encode()) <= tw.LIMITE_BYTES
    assert "não exibido" in json.dumps(p, ensure_ascii=False)


# --------------------------------------------------------------------- envio
def test_envio_ok(servidor):
    tw.enviar(msg(), servidor["url"])
    assert len(servidor["recebidos"]) == 1


def test_erro_400_nao_repete_e_vira_codigo(servidor):
    servidor["status"] = 400
    with pytest.raises(ErroDeEnvio) as e:
        tw.enviar(msg(), servidor["url"], tentativas=3)
    assert e.value.codigo == "TEAMS_HTTP_400"
    assert len(servidor["recebidos"]) == 1  # 400 não adianta tentar de novo


def test_erro_503_tenta_de_novo(servidor, monkeypatch):
    monkeypatch.setattr(tw.time, "sleep", lambda s: None)
    servidor["status"] = 503
    with pytest.raises(ErroDeEnvio) as e:
        tw.enviar(msg(), servidor["url"], tentativas=2)
    assert e.value.codigo == "TEAMS_HTTP_503"
    assert len(servidor["recebidos"]) == 2


def test_url_nao_https_e_recusada():
    with pytest.raises(ErroDeEnvio) as e:
        tw.enviar(msg(), "http://exemplo.com/hook")
    assert e.value.codigo == "TEAMS_URL_INVALIDA"


# ------------------------------------------------------ integração com o motor
def linhas(*notas):
    return [{"Nota": n, "Descricao_do_Problema": "x", "Data_da_CD": "2026-10-06"} for n in notas]


@pytest.fixture
def task_teams(task):
    task = dict(task, canais=["preview", "teams:x"])
    return task


@pytest.fixture
def settings_teams(settings):
    settings["sandbox"] = {"ativo": True, "destinatarios": ["pedro"], "canais_permitidos": ["preview", "teams:x"]}
    return settings


def test_dry_run_nao_envia(task_teams, storage, crypto, settings_teams):
    enviados = []
    executar(task_teams, FonteFalsa(linhas("1")), storage, crypto, settings_teams,
             dry_run=True, enviadores={"teams:x": enviados.append})
    assert enviados == []


def test_real_envia_uma_vez_so(task_teams, storage, crypto, settings_teams):
    enviados = []
    env = {"teams:x": enviados.append}
    executar(task_teams, FonteFalsa(linhas("1")), storage, crypto, settings_teams, dry_run=False, enviadores=env)
    executar(task_teams, FonteFalsa(linhas("1")), storage, crypto, settings_teams, dry_run=False, enviadores=env)
    assert len(enviados) == 1  # a segunda execução não tinha novidade


def test_falha_de_envio_nao_marca_como_avisado(task_teams, storage, crypto, settings_teams):
    def quebra(_):
        raise ErroDeEnvio("TEAMS_HTTP_500")

    with pytest.raises(ErroDeEnvio):
        executar(task_teams, FonteFalsa(linhas("1")), storage, crypto, settings_teams,
                 dry_run=False, enviadores={"teams:x": quebra})
    assert storage.hashes_ja_avisados("t1") == set()
    assert storage.listar_execucoes("t1")[0]["codigo_erro"] == "TEAMS_HTTP_500"

    enviados = []  # próxima execução tenta de novo e agora funciona
    r = executar(task_teams, FonteFalsa(linhas("1")), storage, crypto, settings_teams,
                 dry_run=False, enviadores={"teams:x": enviados.append})
    assert r["n_novos"] == 1 and len(enviados) == 1


def test_sandbox_bloqueia_canal_nao_permitido(task, storage, crypto, settings):
    task = dict(task, canais=["preview", "teams:producao"])
    enviados = []
    r = executar(task, FonteFalsa(linhas("1")), storage, crypto, settings,
                 dry_run=False, enviadores={"teams:producao": enviados.append})
    assert enviados == []
    assert r["bloqueados_sandbox"] == ["teams:producao"]


def test_sem_novidade_nao_envia(task_teams, storage, crypto, settings_teams):
    enviados = []
    env = {"teams:x": enviados.append}
    executar(task_teams, FonteFalsa([]), storage, crypto, settings_teams, dry_run=False, enviadores=env)
    assert enviados == []
