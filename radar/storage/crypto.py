"""Criptografia por campo + índice cego (HMAC).

- encrypt/decrypt: Fernet (AES + HMAC). MultiFernet permite rotacionar chaves:
  a primeira chave cifra, todas decifram.
- blind_index: HMAC-SHA256 com chave própria, para comparar igualdade
  (anti-repetição, diff) sem expor o valor.

As chaves vêm do Windows Credential Manager (keyring) ou, só em
desenvolvimento, de variáveis de ambiente. Nunca ficam no código nem no banco.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets

from cryptography.fernet import Fernet, MultiFernet

SERVICE = "radar-operacional"
ENV_ENC = "RADAR_ENC_KEYS"
ENV_HMAC = "RADAR_HMAC_KEY"


def normalizar(valor) -> str:
    """Normaliza antes do hash: 'pr-xxx ' e 'PR-XXX' devem dar o mesmo índice."""
    return " ".join(str(valor).strip().upper().split())


class Crypto:
    def __init__(self, enc_keys: list[str], hmac_key: str):
        if not enc_keys or not hmac_key:
            raise ValueError("chaves de cifragem e de HMAC são obrigatórias")
        if hmac_key in enc_keys:
            raise ValueError("a chave de HMAC deve ser diferente da de cifragem")
        self._fernet = MultiFernet([Fernet(k.encode()) for k in enc_keys])
        self._hmac_key = hmac_key.encode()

    def encrypt(self, obj) -> bytes:
        dados = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        return self._fernet.encrypt(dados)

    def decrypt(self, blob: bytes):
        return json.loads(self._fernet.decrypt(blob).decode("utf-8"))

    def blind_index(self, *partes) -> str:
        texto = "|".join(normalizar(p) for p in partes)
        return hmac.new(self._hmac_key, texto.encode("utf-8"), hashlib.sha256).hexdigest()

    def rotacionar(self, blob: bytes) -> bytes:
        """Recifra com a chave mais nova (usar após adicionar uma chave nova)."""
        return self._fernet.rotate(blob)


# ---------------------------------------------------------------- chaves
def gerar_chaves() -> tuple[str, str]:
    return Fernet.generate_key().decode(), secrets.token_urlsafe(32)


def salvar_no_keyring(enc_key: str, hmac_key: str) -> None:
    import keyring

    keyring.set_password(SERVICE, "enc_keys", enc_key)
    keyring.set_password(SERVICE, "hmac_key", hmac_key)


def carregar_crypto() -> Crypto:
    enc = os.environ.get(ENV_ENC)
    hm = os.environ.get(ENV_HMAC)
    if not (enc and hm):
        try:
            import keyring

            enc = enc or keyring.get_password(SERVICE, "enc_keys")
            hm = hm or keyring.get_password(SERVICE, "hmac_key")
        except Exception:  # keyring indisponível
            pass
    if not (enc and hm):
        raise RuntimeError(
            "Chaves não encontradas. Rode `python -m radar init-keys` "
            f"(ou defina {ENV_ENC} e {ENV_HMAC} apenas em desenvolvimento)."
        )
    return Crypto([k.strip() for k in enc.split(",") if k.strip()], hm)
