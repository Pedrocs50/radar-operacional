"""Tabela estilo Excel em PNG: uma linha por item, as linhas novas em vermelho com a marca NOVA."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .imagem import COR_FUNDO, COR_LINHA_PAR, COR_TITULO, _fonte, _quebrar, _valor


def renderizar_tabela(linhas: list[dict], colunas: list[str], rotulos: dict | None = None,
                      chaves_novas: set | None = None, campo_chave: str | None = None,
                      maximo: int = 60) -> Image.Image:
    rotulos, chaves_novas = rotulos or {}, chaves_novas or set()
    f_txt, f_neg = _fonte(False, 13), _fonte(True, 13)
    medida = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    mostradas = linhas[:maximo]
    larguras = []
    for c in colunas:
        w = medida.textlength(rotulos.get(c, c), font=f_neg)
        for l in mostradas[:50]:
            w = max(w, medida.textlength(_valor(l.get(c)), font=f_txt))
        larguras.append(int(min(max(w + 16, 60), 300)))
    larg_marca = 56
    largura = larg_marca + sum(larguras)

    def celula(texto, w, fonte):
        partes = _quebrar(medida, texto, fonte, w - 12)
        if len(partes) > 4:
            partes = partes[:4]
            partes[-1] = partes[-1][:-1] + "…"
        return partes

    cabecalho = [celula(rotulos.get(c, c), w, f_neg) for c, w in zip(colunas, larguras)]
    h_cab = max(len(p) for p in cabecalho) * 17 + 12
    corpo = [[celula(_valor(l.get(c)), w, f_txt) for c, w in zip(colunas, larguras)] for l in mostradas]
    alturas = [max(len(p) for p in linha) * 17 + 10 for linha in corpo]
    img = Image.new("RGB", (largura, h_cab + sum(alturas) + 28), COR_FUNDO)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, largura, h_cab], fill=COR_TITULO)
    x = larg_marca
    for partes, w in zip(cabecalho, larguras):
        for j, p in enumerate(partes):
            d.text((x + 6, 6 + j * 17), p, font=f_neg, fill="white")
        x += w

    y = h_cab
    for i, (l, linha, h) in enumerate(zip(mostradas, corpo, alturas)):
        nova = campo_chave is not None and str(l.get(campo_chave)) in chaves_novas
        atencao = bool(l.get("Atenção")) and not nova
        d.rectangle([0, y, largura, y + h], fill="#fde2e2" if nova else "#fff3cd" if atencao
                    else (COR_LINHA_PAR if i % 2 == 0 else COR_FUNDO))
        if nova:
            d.rectangle([0, y, larg_marca - 4, y + h], fill="#c53030")
            d.text((6, y + 5), "NOVA", font=f_neg, fill="white")
        x = larg_marca
        for partes, w in zip(linha, larguras):
            for j, p in enumerate(partes):
                d.text((x + 6, y + 5 + j * 17), p, font=f_neg if nova else f_txt,
                       fill="#9b1c1c" if nova else "#1f2933")
            x += w
        d.line([0, y + h, largura, y + h], fill="#d9e2ec")
        y += h

    resto = len(linhas) - len(mostradas)
    legenda = "Vermelho = chegou agora. Amarelo = pede atenção (ver coluna Atenção)." + (f"  +{resto} CD(s) só no Excel anexo." if resto > 0 else "")
    d.text((8, y + 6), legenda, font=_fonte(False, 12), fill="#52606d")
    return img


def gerar_tabela(linhas, colunas, destino: str | Path, rotulos=None, chaves_novas=None,
                 campo_chave=None, maximo: int = 60) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    renderizar_tabela(linhas, colunas, rotulos, chaves_novas, campo_chave, maximo).save(destino, optimize=True)
    return destino
