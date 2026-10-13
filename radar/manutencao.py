"""Manutenção do robô: backup do banco e atualização do código.

O backup usa a API de backup do SQLite (cópia consistente mesmo com o robô rodando e o banco em modo WAL) e confere a
integridade da cópia. O banco já guarda os dados cifrados; **as chaves não vão no backup** (ficam no Credential Manager)
e precisam de backup próprio, separado.
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import config

PADRAO_PASTA = "data/backups"
PADRAO_MANTER = 14


class ErroDeManutencao(Exception):
    """Falha com código curto, sem conteúdo."""

    def __init__(self, codigo: str):
        super().__init__(codigo)
        self.codigo = codigo


def pasta_backup(settings: dict) -> Path:
    return config.RAIZ / settings.get("backup", {}).get("pasta", PADRAO_PASTA)


def _aplicar_retencao(pasta: Path, manter: int) -> int:
    arquivos = sorted(pasta.glob("radar-*.db"), reverse=True)  # o nome começa pela data: mais novo primeiro
    for velho in arquivos[manter:]:
        velho.unlink()
    return max(len(arquivos) - manter, 0)


def fazer_backup(settings: dict, agora: datetime | None = None) -> dict:
    """Copia o banco para a pasta de backup (e para as pastas extras), confere a integridade e aplica a retenção."""
    agora = agora or datetime.now()
    cfg = settings.get("backup", {})
    origem = config.RAIZ / settings["storage"]["db_path"]
    if not origem.exists():
        raise ErroDeManutencao("BANCO_NAO_ENCONTRADO")
    pasta = pasta_backup(settings)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"radar-{agora:%Y%m%d-%H%M%S}.db"

    src, dst = sqlite3.connect(str(origem)), sqlite3.connect(str(destino))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    conferir = sqlite3.connect(str(destino))
    try:
        resultado = conferir.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conferir.close()
    if resultado != "ok":
        destino.unlink(missing_ok=True)
        raise ErroDeManutencao("BACKUP_INTEGRIDADE")

    manter = cfg.get("manter", PADRAO_MANTER)
    removidos = _aplicar_retencao(pasta, manter)
    copias = []
    for extra in cfg.get("copiar_para", []):
        pasta_extra = Path(extra)
        pasta_extra.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destino, pasta_extra / destino.name)
        removidos += _aplicar_retencao(pasta_extra, manter)
        copias.append(str(pasta_extra / destino.name))
    return {"arquivo": destino, "tamanho": destino.stat().st_size, "copias": copias, "removidos": removidos}


def ultimo_backup(settings: dict) -> datetime | None:
    pasta = pasta_backup(settings)
    arquivos = sorted(pasta.glob("radar-*.db")) if pasta.exists() else []
    return datetime.fromtimestamp(arquivos[-1].stat().st_mtime) if arquivos else None


def atualizar(sem_testes: bool = False, executar=subprocess.run) -> list[tuple[str, bool, str]]:
    """git pull + dependências + testes. Retorna [(passo, ok, detalhe)]. Interrompe no primeiro erro."""
    py = sys.executable

    def rodar(args: list[str]) -> tuple[bool, str]:
        r = executar(args, cwd=str(config.RAIZ), capture_output=True, text=True, encoding="utf-8", errors="replace")
        saida, erro = (r.stdout or "").strip().splitlines(), (r.stderr or "").strip().splitlines()
        return r.returncode == 0, (saida[-1] if saida else (erro[-1] if erro else ""))

    passos = [("versão atual", ["git", "rev-parse", "--short", "HEAD"]),
              ("baixar atualização (git pull)", ["git", "pull", "--ff-only"]),
              ("instalar dependências", [py, "-m", "pip", "install", "-q", "-r", "requirements.txt"])]
    if not sem_testes:
        passos.append(("rodar os testes", [py, "-m", "pytest", "-q", "-p", "no:cacheprovider"]))
    passos.append(("nova versão", ["git", "rev-parse", "--short", "HEAD"]))
    resultados: list[tuple[str, bool, str]] = []
    for nome, args in passos:
        ok, detalhe = rodar(args)
        resultados.append((nome, ok, detalhe))
        if not ok:
            break
    return resultados
