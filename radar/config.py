"""Carrega settings, tarefas e monta a fonte de cada tarefa."""
from __future__ import annotations

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


def carregar_settings(caminho: str | Path | None = None) -> dict:
    caminho = Path(caminho) if caminho else RAIZ / "config" / "settings.yaml"
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def carregar_tarefa(task_id: str, pasta: str | Path | None = None) -> dict:
    pasta = Path(pasta) if pasta else RAIZ / "tasks"
    arq = pasta / f"{task_id}.yaml"
    if not arq.exists():
        raise FileNotFoundError(f"tarefa não encontrada: {task_id}")
    return yaml.safe_load(arq.read_text(encoding="utf-8"))


def listar_tarefas(pasta: str | Path | None = None) -> list[dict]:
    pasta = Path(pasta) if pasta else RAIZ / "tasks"
    return [yaml.safe_load(a.read_text(encoding="utf-8")) for a in sorted(pasta.glob("*.yaml"))]


def montar_fonte(task: dict, settings: dict):
    tipo = task["fonte"]["tipo"]
    if tipo == "bigquery":
        from .sources.bigquery import BigQuerySource

        return BigQuerySource(settings["bigquery"]["job_project"], RAIZ / task["fonte"]["sql_file"])
    if tipo == "demo":
        from .sources.demo import DemoSource

        return DemoSource(RAIZ / task["fonte"]["arquivo"])
    raise ValueError(f"tipo de fonte desconhecido: {tipo}")
