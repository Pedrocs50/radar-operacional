"""Canal e-mail via Outlook clássico (automação COM, por PowerShell).

Envia como o usuário logado no Outlook, sem app registration e sem pedir nada à TI. Limites: precisa do
Outlook clássico instalado e do usuário logado. A versão definitiva (servidor) troca este módulo por
Microsoft Graph (`Mail.Send`) mantendo a mesma interface: enviar(mensagem, destinatarios, ...).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import email_conteudo as ec
from .base import ErroDeEnvio

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "enviar_email.ps1"


def dominio_permitido(email: str, dominios: list[str] | None) -> bool:
    """Sem lista configurada, qualquer domínio vale. Com lista, o domínio (ou um subdomínio) precisa estar nela."""
    if not dominios:
        return True
    dominio = email.rsplit("@", 1)[-1].lower()
    return any(dominio == d.lower() or dominio.endswith("." + d.lower()) for d in dominios)


def parse_destinatarios(texto: str, dominios: list[str] | None = None) -> list[str]:
    lista = [d for d in re.split(r"[;,\s]+", texto.strip()) if d]
    if not lista or any("@" not in d or any(ord(ch) < 32 for ch in d) for d in lista):
        raise ErroDeEnvio("EMAIL_DESTINATARIO_INVALIDO")
    if any(not dominio_permitido(d, dominios) for d in lista):  # dado operacional só para contas corporativas
        raise ErroDeEnvio("EMAIL_DOMINIO_NAO_PERMITIDO")
    return lista


def _enviar_pelo_outlook(descricao: dict, pasta: Path, nome_base: str) -> None:
    arq_json = pasta / f"{nome_base}_envio.json"
    arq_json.write_text(json.dumps(descricao, ensure_ascii=False), encoding="utf-8")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-Json", str(arq_json)],
            capture_output=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        raise ErroDeEnvio("EMAIL_TIMEOUT") from None
    finally:
        arq_json.unlink(missing_ok=True)  # tem endereços de e-mail
    if r.returncode != 0:
        raise ErroDeEnvio("EMAIL_OUTLOOK_ERRO")


def enviar_html(destinatarios: str, assunto: str, html: str, pasta: str | Path, nome_base: str,
                anexos: tuple = (), remetente: str | None = None, modo: str = "enviar",
                enviador=_enviar_pelo_outlook, dominios: list[str] | None = None) -> None:
    """E-mail simples (HTML pronto), usado para avisos técnicos."""
    para = parse_destinatarios(destinatarios, dominios)
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"{nome_base}_email.html"
    arq.write_text(html, encoding="utf-8")
    enviador({"para": para, "assunto": assunto, "html": str(arq), "anexos": [str(a) for a in anexos],
              "inline": [], "modo": modo, "de": remetente}, pasta, nome_base)


def enviar(mensagem: dict, destinatarios: str, pasta: str | Path, nome_base: str,
           modo: str = "enviar", remetente: str | None = None, enviador=_enviar_pelo_outlook,
           dominios: list[str] | None = None) -> None:
    para = parse_destinatarios(destinatarios, dominios)
    pasta = Path(pasta)
    arq = ec.gerar_arquivos(mensagem, pasta, nome_base)
    html = pasta / f"{nome_base}_email.html"
    html.write_text(ec.renderizar_html(mensagem, "cid:tabela", "cid:grafico" if "grafico" in arq else None,
                                       "cid:painel" if "painel" in arq else None), encoding="utf-8")
    inline = [{"caminho": str(arq["png"]), "cid": "tabela"}]
    if "grafico" in arq:
        inline.append({"caminho": str(arq["grafico"]), "cid": "grafico"})
    if "painel" in arq:
        inline.append({"caminho": str(arq["painel"]), "cid": "painel"})
    enviador({
        "para": para,
        "assunto": ec.assunto(mensagem),
        "html": str(html),
        "anexos": [str(arq["xlsx"])],
        "inline": inline,
        "modo": modo,
        "de": remetente,
    }, pasta, nome_base)
