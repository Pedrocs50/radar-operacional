import pytest

from radar.storage.crypto import Crypto, gerar_chaves


def test_roundtrip(crypto):
    obj = {"a": "ação", "n": 3}
    blob = crypto.encrypt(obj)
    assert "ação".encode("utf-8") not in blob
    assert crypto.decrypt(blob) == obj


def test_blind_index_normaliza(crypto):
    assert crypto.blind_index("t", "pr-xxx ") == crypto.blind_index("t", "PR-XXX")
    assert crypto.blind_index("t", "A") != crypto.blind_index("t", "B")


def test_blind_index_depende_da_chave():
    e1, h1 = gerar_chaves()
    e2, h2 = gerar_chaves()
    assert Crypto([e1], h1).blind_index("x") != Crypto([e1], h2).blind_index("x")


def test_rotacao_de_chave():
    velha, hm = gerar_chaves()
    nova, _ = gerar_chaves()
    antigo = Crypto([velha], hm).encrypt({"k": 1})
    c = Crypto([nova, velha], hm)  # nova cifra, ambas decifram
    assert c.decrypt(antigo) == {"k": 1}
    recifrado = c.rotacionar(antigo)
    assert Crypto([nova], hm).decrypt(recifrado) == {"k": 1}


def test_chaves_iguais_sao_recusadas():
    e, _ = gerar_chaves()
    with pytest.raises(ValueError):
        Crypto([e], e)
