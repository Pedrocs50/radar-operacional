"""Fonte de demonstração: dados FICTÍCIOS, para testar sem BigQuery."""
from __future__ import annotations

import json
from pathlib import Path


class DemoSource:
    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)

    def fetch(self) -> list[dict]:
        return json.loads(self.caminho.read_text(encoding="utf-8"))
