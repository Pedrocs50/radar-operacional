from radar import __main__ as cli
from radar.channels import imagem, teams_webhook
from radar.engine.runner import executar
from tests.conftest import FonteFalsa

ITEM = {"Nota_QM": "999", "Modelo_Aeronave": "EJETS E2", "Descricao_do_Problema": "texto longo " * 40,
        "Fluxo": None, "PN": ""}


class FonteComCarimbo(FonteFalsa):
    def __init__(self, linhas, carimbo):
        super().__init__(linhas)
        self.carimbo = carimbo
        self.consultas = 0

    def fetch(self):
        self.consultas += 1
        return super().fetch()

    def ultima_atualizacao(self):
        return self.carimbo


def _preparar(monkeypatch, tmp_path, storage, fonte):
    task = {"id": "t1", "ativa": True, "modo": "novas", "canais": ["preview"],
            "fonte": {"campo_chave": "Nota_QM"},
            "mensagem": {"titulo": "x", "campos_exibidos": ["Nota_QM"]}}
    settings = {"preview": {"dir": str(tmp_path / "p")}, "sandbox": {}}
    monkeypatch.setattr(cli.config, "carregar_settings", lambda: settings)
    monkeypatch.setattr(cli.config, "carregar_tarefa", lambda t: task)
    monkeypatch.setattr(cli.config, "montar_fonte", lambda t, s: fonte)
    monkeypatch.setattr(cli, "_abrir", lambda s: (storage.crypto, storage))
    return type("A", (), {"task": "t1", "forcar": False, "forcar_inativa": False})()


def test_vigiar_so_roda_a_consulta_quando_a_origem_muda(monkeypatch, tmp_path, storage):
    fonte = FonteComCarimbo([{"Nota_QM": "1"}], "2026-10-07T16:00:00+00:00")
    args = _preparar(monkeypatch, tmp_path, storage, fonte)
    cli.cmd_vigiar(args)
    cli.cmd_vigiar(args)                       # mesma carga: não consulta de novo
    assert fonte.consultas == 1
    fonte.carimbo = "2026-10-07T17:00:00+00:00"  # origem atualizada
    cli.cmd_vigiar(args)
    assert fonte.consultas == 2
    assert len(storage.listar_atualizacoes("t1")) == 2


def test_vigiar_falha_nao_marca_a_atualizacao(monkeypatch, tmp_path, storage):
    class Quebrada(FonteComCarimbo):
        def fetch(self):
            raise ConnectionError("rede")

    fonte = Quebrada([], "2026-10-07T16:00:00+00:00")
    args = _preparar(monkeypatch, tmp_path, storage, fonte)
    try:
        cli.cmd_vigiar(args)
    except ConnectionError:
        pass
    assert not storage.atualizacao_ja_tratada("t1", "2026-10-07T16:00:00+00:00")


def test_imagem_traz_todas_as_colunas_e_gera_png(tmp_path):
    caminhos = imagem.gerar([ITEM, ITEM], tmp_path, "exec1", "Titulo", {"Nota_QM": "Nota QM"}, "Nota_QM")
    assert [c.name for c in caminhos] == ["exec1_1.png", "exec1_2.png"]
    assert caminhos[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert "999" not in caminhos[0].name  # nome do arquivo não carrega dado operacional


def test_runner_gera_imagem_so_se_configurado(task, storage, crypto, settings):
    task["mensagem"]["imagem"] = True
    r = executar(task, FonteFalsa([{"Nota": "1", "Descricao_do_Problema": "a", "Data_da_CD": "x"}]),
                 storage, crypto, settings, dry_run=True)
    assert len(r["imagens"]) == 1


def test_cartao_usa_rotulos():
    m = {"titulo": "T", "dados_de": "x", "n_itens": 1, "n_novos": 1,
         "colunas": ["A", "B", "C", "Dias"], "rotulos": {"Dias": "Dias em aberto"},
         "itens": [{"A": "1", "B": "2", "C": "3", "Dias": "9"}]}
    fatos = str(teams_webhook.montar_payload(m))
    assert "Dias em aberto" in fatos


def test_base_de_referencia_nao_envia_e_evita_alerta_em_massa(monkeypatch, tmp_path, storage):
    enviados = []
    fonte = FonteComCarimbo([{"Nota_QM": "1"}, {"Nota_QM": "2"}], "2026-10-07T16:00:00+00:00")
    args = _preparar(monkeypatch, tmp_path, storage, fonte)
    task = cli.config.carregar_tarefa("x")
    task["canais"] = ["preview", "teams:teste"]  # a tarefa tem canal externo, mas a base não pode usá-lo
    monkeypatch.setattr(cli.config, "carregar_tarefa", lambda t: task)
    monkeypatch.setattr("radar.engine.runner._resolver_enviador", lambda *a, **k: enviados.append(a) or (lambda m: None))
    cli.cmd_base_referencia(args)
    assert enviados == [] and len(storage.hashes_ja_avisados("t1")) == 2
    # a base já registrou a carga atual: a primeira verificação do vigia não consulta nem alerta nada
    cli.cmd_vigiar(args)
    assert enviados == [] and fonte.consultas == 1
