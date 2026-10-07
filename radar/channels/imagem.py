"""Imagem com TODAS as colunas de cada item (uma imagem por item, campo | valor).

Contém dado operacional em claro: vai para a mesma pasta temporária das prévias
(retenção curta, apagada por `radar limpar`).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LARGURA = 1200
COL_ROTULO = 330
MARGEM = 16
COR_FUNDO, COR_TITULO, COR_LINHA_PAR = "#ffffff", "#1f3a5f", "#f0f4f8"


def _fonte(negrito: bool, tamanho: int):
    for nome in (("arialbd.ttf" if negrito else "arial.ttf"), ("segoeuib.ttf" if negrito else "segoeui.ttf")):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(tamanho)


def _quebrar(draw, texto: str, fonte, largura: int) -> list[str]:
    linhas, atual = [], ""
    for palavra in " ".join(texto.split()).split(" "):
        teste = f"{atual} {palavra}".strip()
        if draw.textlength(teste, font=fonte) <= largura or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    linhas.append(atual)
    return linhas


def _valor(v) -> str:
    return "-" if v is None or str(v).strip() == "" else str(v)


def renderizar_item(item: dict, titulo: str, rotulos: dict | None = None) -> Image.Image:
    rotulos = rotulos or {}
    f_txt, f_neg, f_tit = _fonte(False, 15), _fonte(True, 15), _fonte(True, 20)
    medida = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    larg_valor = LARGURA - COL_ROTULO - 3 * MARGEM

    linhas = []
    for campo, valor in item.items():
        partes = _quebrar(medida, _valor(valor), f_txt, larg_valor)
        linhas.append((rotulos.get(campo, campo), partes))

    altura_tit = 44
    altura = altura_tit + sum(len(p) * 20 + 10 for _, p in linhas) + MARGEM
    img = Image.new("RGB", (LARGURA, altura), COR_FUNDO)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, LARGURA, altura_tit], fill=COR_TITULO)
    d.text((MARGEM, 10), titulo, font=f_tit, fill="white")
    y = altura_tit
    for i, (rotulo, partes) in enumerate(linhas):
        h = len(partes) * 20 + 10
        if i % 2 == 0:
            d.rectangle([0, y, LARGURA, y + h], fill=COR_LINHA_PAR)
        d.text((MARGEM, y + 5), rotulo, font=f_neg, fill="#1f2933")
        for j, parte in enumerate(partes):
            d.text((COL_ROTULO + 2 * MARGEM, y + 5 + j * 20), parte, font=f_txt, fill="#1f2933")
        y += h
    return img


def gerar(itens: list[dict], pasta: str | Path, nome_base: str, titulo: str,
          rotulos: dict | None = None, campo_titulo: str | None = None, maximo: int = 10) -> list[Path]:
    """Gera um PNG por item (até `maximo`). Nomes sem dado operacional: só execução e posição."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    caminhos = []
    for i, item in enumerate(itens[:maximo], start=1):
        sufixo = f" {item.get(campo_titulo, '')}" if campo_titulo else ""
        img = renderizar_item(item, f"{titulo}{sufixo}", rotulos)
        destino = pasta / f"{nome_base}_{i}.png"
        img.save(destino, optimize=True)
        caminhos.append(destino)
    return caminhos
