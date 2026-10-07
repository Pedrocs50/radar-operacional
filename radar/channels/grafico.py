"""Gráfico de colunas agrupadas (entradas x resolvidas por semana) em PNG, para o e-mail.

Segue as regras do guia de visualização: duas séries categóricas validadas (azul = resolvidas, laranja = entraram,
CVD ΔE 24,7 e contraste >= 3:1 na superfície clara), colunas finas (<= 24 px) com topo arredondado de 4 px e base
reta, 2 px de respiro entre colunas vizinhas, grade hairline recessiva, legenda sempre presente, rótulo só na
semana corrente, texto sempre em tinta (nunca na cor da série).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .imagem import _fonte

SUPERFICIE, TINTA, TINTA_2, MUDO, GRADE = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
COR_ENTRADAS, COR_SAIDAS = "#eb6834", "#2a78d6"   # laranja = entraram, azul = resolvidas


def _teto(v: int) -> tuple[int, int]:
    """Maior valor do eixo e passo, em números redondos (1, 2, 5 x 10^k), no máximo ~5 marcas."""
    v = max(v, 1)
    for passo in (1, 2, 5, 10, 20, 50, 100, 200, 500):
        if v / passo <= 5:
            return -(-v // passo) * passo, passo
    return v, v


def renderizar(semanas: list[dict], largura: int = 760, altura: int = 300) -> Image.Image:
    f, f_neg, f_peq = _fonte(False, 13), _fonte(True, 13), _fonte(False, 12)
    img = Image.new("RGB", (largura, altura), SUPERFICIE)
    d = ImageDraw.Draw(img)
    esq, dir_, topo, base = 44, 16, 44, altura - 36
    teto, passo = _teto(max((max(s["entradas"], s["saidas"]) for s in semanas), default=1))

    def y(v):
        return base - (base - topo) * v / teto

    # grade e eixo Y (hairline, recessiva)
    for v in range(0, teto + 1, passo):
        d.line([esq, y(v), largura - dir_, y(v)], fill=GRADE, width=1)
        txt = str(v)
        d.text((esq - 8 - d.textlength(txt, font=f_peq), y(v) - 7), txt, font=f_peq, fill=MUDO)

    # legenda (sempre presente: 2 séries): marca colorida + texto em tinta
    x = esq
    for cor, nome in ((COR_ENTRADAS, "Entraram"), (COR_SAIDAS, "Resolvidas")):
        d.rounded_rectangle([x, 14, x + 12, 26], radius=3, fill=cor)
        d.text((x + 18, 12), nome, font=f, fill=TINTA_2)
        x += 18 + int(d.textlength(nome, font=f)) + 22

    n = len(semanas)
    grupo = (largura - dir_ - esq) / n
    larg_col = min(24, int(grupo * 0.28))
    respiro = 2
    for i, s in enumerate(semanas):
        centro = esq + grupo * (i + 0.5)
        for j, (chave, cor) in enumerate((("entradas", COR_ENTRADAS), ("saidas", COR_SAIDAS))):
            x0 = centro + (-larg_col - respiro / 2 if j == 0 else respiro / 2)
            x1 = x0 + larg_col
            v = s[chave]
            if v > 0:
                d.rounded_rectangle([x0, y(v), x1, base], radius=4, fill=cor, corners=(True, True, False, False))
                d.rectangle([x0, base - 4, x1, base], fill=cor)   # base reta, ancorada na linha de base
            if s.get("parcial"):  # rótulo seletivo: só a semana corrente
                txt = str(v)
                d.text(((x0 + x1) / 2 - d.textlength(txt, font=f_neg) / 2, y(v) - 17), txt, font=f_neg, fill=TINTA)
        rot = s["rotulo"] + ("*" if s.get("parcial") else "")
        d.text((centro - d.textlength(rot, font=f_peq) / 2, base + 8), rot, font=f_peq, fill=TINTA_2)
    d.line([esq, base, largura - dir_, base], fill=MUDO, width=1)
    nota = "* semana em andamento"
    d.text((largura - dir_ - d.textlength(nota, font=f_peq), 14), nota, font=f_peq, fill=MUDO)
    return img


def gerar(semanas: list[dict], destino: str | Path) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    renderizar(semanas).save(destino, optimize=True)
    return destino


# ---------------------------------------------------------------------------------------------------- painéis
COR_BARRA, COR_OUTROS = "#2a78d6", "#a8a7a1"   # um só matiz (magnitude); "Outros" em cinza recessivo


def _cortar(draw, texto: str, fonte, largura: int) -> str:
    if draw.textlength(texto, font=fonte) <= largura:
        return texto
    while texto and draw.textlength(texto + "…", font=fonte) > largura:
        texto = texto[:-1]
    return texto.rstrip() + "…"


def _desenhar_painel(d: ImageDraw.ImageDraw, x: int, y: int, largura: int, p: dict, fontes) -> int:
    """Barras horizontais ordenadas: rótulo à esquerda (tinta), valor na ponta da barra. Retorna a altura usada."""
    f, f_neg, f_peq = fontes
    d.text((x, y), p["titulo"], font=f_neg, fill=TINTA)
    sub = f"{p['total']} CD(s)"
    d.text((x + largura - d.textlength(sub, font=f_peq), y + 1), sub, font=f_peq, fill=MUDO)
    col_rotulo, passo, esp = 210, 26, 16
    x_barra = x + col_rotulo + 8
    max_v = max((n for _, n, _ in p["linhas"]), default=1)
    area = largura - col_rotulo - 8 - 34
    yy = y + 30
    for rotulo, n, outros in p["linhas"]:
        txt = _cortar(d, rotulo, f, col_rotulo)
        d.text((x + col_rotulo - d.textlength(txt, font=f), yy + 1), txt, font=f, fill=TINTA_2)
        comp = max(int(area * n / max_v), 4)
        cor = COR_OUTROS if outros else COR_BARRA
        d.rounded_rectangle([x_barra, yy + 2, x_barra + comp, yy + 2 + esp], radius=4, fill=cor,
                            corners=(False, True, True, False))   # ponta arredondada, base reta no eixo
        d.rectangle([x_barra, yy + 2, x_barra + 4, yy + 2 + esp], fill=cor)
        d.text((x_barra + comp + 6, yy + 1), str(n), font=f_neg, fill=TINTA)
        yy += passo
    d.line([x_barra, y + 28, x_barra, yy], fill=MUDO, width=1)
    return yy - y + 10


def renderizar_paineis(paineis: list[dict], largura: int = 1200) -> Image.Image:
    """Todos os painéis numa imagem só, em duas colunas."""
    fontes = (_fonte(False, 13), _fonte(True, 14), _fonte(False, 12))
    medida = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    margem, entre = 20, 36
    larg_p = (largura - 2 * margem - entre) // 2
    linhas_do_painel = [[p for p in paineis[i:i + 2]] for i in range(0, len(paineis), 2)]
    alturas = [max(30 + 26 * len(p["linhas"]) + 18 for p in par) for par in linhas_do_painel]
    img = Image.new("RGB", (largura, sum(alturas) + 2 * margem), SUPERFICIE)
    d = ImageDraw.Draw(img)
    y = margem
    for par, h in zip(linhas_do_painel, alturas):
        for j, p in enumerate(par):
            _desenhar_painel(d, margem + j * (larg_p + entre), y, larg_p, p, fontes)
        y += h
    return img


def gerar_paineis(paineis: list[dict], destino: str | Path) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    renderizar_paineis(paineis).save(destino, optimize=True)
    return destino
