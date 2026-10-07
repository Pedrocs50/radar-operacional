import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from radar.storage.crypto import Crypto, gerar_chaves  # noqa: E402
from radar.storage.db import Storage  # noqa: E402


@pytest.fixture
def crypto():
    enc, hm = gerar_chaves()
    return Crypto([enc], hm)


@pytest.fixture
def storage(tmp_path, crypto):
    st = Storage(tmp_path / "t.db", crypto)
    yield st
    st.close()


@pytest.fixture
def settings(tmp_path):
    return {
        "preview": {"dir": str(tmp_path / "prev"), "retencao_horas": 24},
        "sandbox": {"ativo": True, "destinatarios": ["pedro"]},
    }


@pytest.fixture
def task():
    return {
        "id": "t1",
        "modo": "novas",
        "fonte": {"tipo": "demo", "campo_chave": "Nota"},
        "mensagem": {
            "titulo": "Teste",
            "campos_exibidos": ["Nota", "Descricao_do_Problema"],
            "campo_data_referencia": "Data_da_CD",
        },
    }


class FonteFalsa:
    def __init__(self, linhas):
        self.linhas = linhas

    def fetch(self):
        return list(self.linhas)
