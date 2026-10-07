import pytest

from radar import __main__ as cli
from radar.channels import email_outlook
from radar.channels.base import ErroDeEnvio
from tests.test_email import mensagem

DOMINIOS = ["empresa.com.br", "amer.teams.ms"]


def test_dominio_corporativo_e_obrigatorio_quando_configurado(tmp_path):
    assert email_outlook.dominio_permitido("a@empresa.com.br", DOMINIOS)
    assert email_outlook.dominio_permitido("a@setor.empresa.com.br", DOMINIOS)      # subdomínio
    assert email_outlook.dominio_permitido("canal@amer.teams.ms", DOMINIOS)
    assert not email_outlook.dominio_permitido("a@gmail.com", DOMINIOS)
    assert not email_outlook.dominio_permitido("a@naoempresa.com.br", DOMINIOS)      # não confunde com sufixo
    assert email_outlook.dominio_permitido("a@qualquer.com", None)                   # sem lista: não restringe
    with pytest.raises(ErroDeEnvio) as e:
        email_outlook.enviar(mensagem(), "a@empresa.com.br; b@gmail.com", tmp_path, "t", dominios=DOMINIOS,
                             enviador=lambda *a: None)
    assert e.value.codigo == "EMAIL_DOMINIO_NAO_PERMITIDO"


def test_comando_destinatarios_adiciona_remove_e_nao_apaga_os_outros(monkeypatch):
    cofre = {"email_destinatarios_teste": "canal@amer.teams.ms; dono@empresa.com.br"}
    monkeypatch.setattr(cli.segredos, "obter", lambda n: cofre[n])
    monkeypatch.setattr(cli.segredos, "salvar", lambda n, v: cofre.__setitem__(n, v))
    monkeypatch.setattr(cli.config, "carregar_settings", lambda: {"email": {"dominios_permitidos": DOMINIOS}})

    def args(**k):
        return type("A", (), {"destino": "teste", "adicionar": None, "remover": None, **k})()

    assert cli.cmd_destinatarios(args(adicionar=["Maria@Empresa.com.br", "dono@empresa.com.br"])) is None
    assert cofre["email_destinatarios_teste"] == "canal@amer.teams.ms; dono@empresa.com.br; maria@empresa.com.br"
    assert cli.cmd_destinatarios(args(remover=["maria@empresa.com.br"])) is None
    assert "maria" not in cofre["email_destinatarios_teste"] and "canal@amer.teams.ms" in cofre["email_destinatarios_teste"]
    antes = cofre["email_destinatarios_teste"]
    assert cli.cmd_destinatarios(args(adicionar=["pessoa@gmail.com"])) == 2          # fora do domínio: recusa
    assert cli.cmd_destinatarios(args(adicionar=["sem-arroba"])) == 2
    assert cli.cmd_destinatarios(args(remover=["canal@amer.teams.ms", "dono@empresa.com.br"])) == 2  # não esvazia
    assert cofre["email_destinatarios_teste"] == antes
    assert cli.cmd_destinatarios(args()) is None and cofre["email_destinatarios_teste"] == antes   # só listar não altera
