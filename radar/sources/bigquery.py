"""Fonte BigQuery. Executa o SQL do arquivo exatamente como está."""
from __future__ import annotations

from pathlib import Path


class BigQuerySource:
    def __init__(self, job_project: str, sql_path: str | Path):
        self.job_project = job_project
        self.sql = Path(sql_path).read_text(encoding="utf-8")

    def _client(self):
        from google.cloud import bigquery  # import tardio: testes não exigem credenciais

        return bigquery, bigquery.Client(project=self.job_project)

    def fetch(self) -> list[dict]:
        _, client = self._client()
        resultado = client.query(self.sql).result()
        return [dict(linha.items()) for linha in resultado]

    def estimar_custo(self) -> dict:
        """dry_run: não executa, só informa quantos bytes seriam lidos."""
        bigquery, client = self._client()
        cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        job = client.query(self.sql, job_config=cfg)
        return {"bytes_processados": job.total_bytes_processed}
