"""Canal preview: gera um HTML local. Não depende de nenhuma permissão externa.

O HTML contém dado operacional, então vai para uma pasta temporária com
retenção curta (limpar_antigos), e o conteúdo oficial fica cifrado no banco.
"""
from __future__ import annotations

import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def renderizar(mensagem: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    return env.get_template("preview.html.j2").render(m=mensagem)


def enviar(mensagem: dict, pasta: str | Path, nome_base: str) -> Path:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{nome_base}.html"
    destino.write_text(renderizar(mensagem), encoding="utf-8")
    return destino


def limpar_antigos(pasta: str | Path, retencao_horas: float) -> int:
    pasta = Path(pasta)
    if not pasta.exists():
        return 0
    limite = time.time() - retencao_horas * 3600
    apagados = 0
    for arq in [*pasta.glob("*.html"), *pasta.glob("*.png"), *pasta.glob("*.xlsx")]:
        if arq.stat().st_mtime < limite:
            arq.unlink()
            apagados += 1
    return apagados
