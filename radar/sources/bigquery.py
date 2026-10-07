"""Fonte BigQuery. Executa o SQL do arquivo exatamente como está."""
from __future__ import annotations

from pathlib import Path


class BigQuerySource:
    def __init__(self, job_project: str, sql_path: str | Path, tabela_monitorada: str | None = None,
                 max_bytes_billed: int | None = None):
        self.job_project = job_project
        self.tabela_monitorada = tabela_monitorada
        self.max_bytes_billed = max_bytes_billed   # teto de segurança por consulta (a consulta falha se passar)
        self.ultimo_bytes: int | None = None       # bytes cobrados na última consulta (para acompanhar custo)
        self.sql = Path(sql_path).read_text(encoding="utf-8")

    def _client(self):
        from google.cloud import bigquery  # import tardio: testes não exigem credenciais

        return bigquery, bigquery.Client(project=self.job_project)

    def _config(self, bigquery, **extra):
        return bigquery.QueryJobConfig(maximum_bytes_billed=self.max_bytes_billed, **extra)

    def fetch(self) -> list[dict]:
        bigquery, client = self._client()
        job = client.query(self.sql, job_config=self._config(bigquery))
        resultado = job.result()
        self.ultimo_bytes = job.total_bytes_billed
        return [dict(linha.items()) for linha in resultado]

    def resolver_notas(self, sql_path: str | Path, notas: list[str]) -> dict[str, dict]:
        """Situação atual de algumas notas (para explicar por que saíram da lista). {nota: linha}"""
        if not notas:
            return {}
        bigquery, client = self._client()
        cfg = self._config(bigquery, query_parameters=[bigquery.ArrayQueryParameter("notas", "STRING", list(notas))])
        job = client.query(Path(sql_path).read_text(encoding="utf-8"), job_config=cfg)
        linhas = [dict(l.items()) for l in job.result()]
        return {str(l["Nota_QM"]): l for l in linhas}

    def ultima_atualizacao(self) -> str:
        """Carimbo (UTC, ISO) da última carga da tabela de origem. Só metadado: não lê dados, custo zero."""
        if not self.tabela_monitorada:
            raise ValueError("a tarefa não define fonte.tabela_monitorada")
        _, client = self._client()
        return client.get_table(self.tabela_monitorada).modified.isoformat()

    def estimar_custo(self) -> dict:
        """dry_run: não executa, só informa quantos bytes seriam lidos."""
        bigquery, client = self._client()
        cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        job = client.query(self.sql, job_config=cfg)
        return {"bytes_processados": job.total_bytes_processed}
