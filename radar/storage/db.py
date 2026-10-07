"""Única camada que fala SQL. O resto do sistema só vê objetos decifrados.

Em claro: ids internos, datas, status, contagens, código de erro.
Cifrado: conteúdo das mensagens e dos itens (payload).
Índice cego (HMAC): id_hash, para igualdade sem expor o valor.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .crypto import Crypto

SCHEMA = """
CREATE TABLE IF NOT EXISTS execucoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    inicio      TEXT NOT NULL,
    fim         TEXT,
    status      TEXT NOT NULL,          -- rodando | sucesso | sem_novidade | falha
    dry_run     INTEGER NOT NULL,
    n_itens     INTEGER,
    n_novos     INTEGER,
    codigo_erro TEXT
);
CREATE TABLE IF NOT EXISTS alertas (      -- estado anti-repetição
    task_id        TEXT NOT NULL,
    id_hash        TEXT NOT NULL,
    primeiro_em    TEXT NOT NULL,
    execucao_id    INTEGER NOT NULL,
    payload        BLOB NOT NULL,          -- cifrado
    PRIMARY KEY (task_id, id_hash)
);
CREATE TABLE IF NOT EXISTS snapshots (    -- base do "o que mudou?"
    execucao_id INTEGER NOT NULL,
    id_hash     TEXT NOT NULL,
    payload     BLOB NOT NULL,             -- cifrado (campos-chave)
    PRIMARY KEY (execucao_id, id_hash)
);
CREATE TABLE IF NOT EXISTS mensagens (
    execucao_id INTEGER PRIMARY KEY,
    criada_em   TEXT NOT NULL,
    conteudo    BLOB NOT NULL              -- cifrado
);
CREATE INDEX IF NOT EXISTS ix_exec_task ON execucoes(task_id, inicio);
"""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, caminho: str | Path, crypto: Crypto):
        self.crypto = crypto
        caminho = Path(caminho)
        if str(caminho) != ":memory:":
            caminho.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(caminho))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ------------------------------------------------------- execuções
    def iniciar_execucao(self, task_id: str, dry_run: bool) -> int:
        cur = self.conn.execute(
            "INSERT INTO execucoes (task_id, inicio, status, dry_run) VALUES (?,?,?,?)",
            (task_id, agora(), "rodando", int(dry_run)),
        )
        self.conn.commit()
        return cur.lastrowid

    def finalizar_execucao(self, exec_id: int, status: str, n_itens=None, n_novos=None, codigo_erro=None):
        self.conn.execute(
            "UPDATE execucoes SET fim=?, status=?, n_itens=?, n_novos=?, codigo_erro=? WHERE id=?",
            (agora(), status, n_itens, n_novos, codigo_erro, exec_id),
        )
        self.conn.commit()

    def listar_execucoes(self, task_id: str | None = None, limite: int = 20):
        sql = "SELECT * FROM execucoes"
        args: list = []
        if task_id:
            sql += " WHERE task_id=?"
            args.append(task_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limite)
        return [dict(r) for r in self.conn.execute(sql, args)]

    # ---------------------------------------------------------- alertas
    def hashes_ja_avisados(self, task_id: str) -> set[str]:
        rows = self.conn.execute("SELECT id_hash FROM alertas WHERE task_id=?", (task_id,))
        return {r["id_hash"] for r in rows}

    def registrar_alertas(self, task_id: str, exec_id: int, itens: list[tuple[str, dict]]):
        for id_hash, payload in itens:
            self.conn.execute(
                "INSERT OR IGNORE INTO alertas (task_id, id_hash, primeiro_em, execucao_id, payload) "
                "VALUES (?,?,?,?,?)",
                (task_id, id_hash, agora(), exec_id, self.crypto.encrypt(payload)),
            )
        self.conn.commit()

    # --------------------------------------------------------- snapshots
    def salvar_snapshot(self, exec_id: int, itens: list[tuple[str, dict]]):
        for id_hash, payload in itens:
            self.conn.execute(
                "INSERT OR REPLACE INTO snapshots (execucao_id, id_hash, payload) VALUES (?,?,?)",
                (exec_id, id_hash, self.crypto.encrypt(payload)),
            )
        self.conn.commit()

    def ultimo_snapshot(self, task_id: str, antes_de_exec_id: int) -> dict[str, dict]:
        """Snapshot da última execução real anterior (para diff)."""
        row = self.conn.execute(
            "SELECT e.id FROM execucoes e JOIN snapshots s ON s.execucao_id = e.id "
            "WHERE e.task_id=? AND e.id<? AND e.dry_run=0 GROUP BY e.id ORDER BY e.id DESC LIMIT 1",
            (task_id, antes_de_exec_id),
        ).fetchone()
        if not row:
            return {}
        rows = self.conn.execute("SELECT id_hash, payload FROM snapshots WHERE execucao_id=?", (row["id"],))
        return {r["id_hash"]: self.crypto.decrypt(r["payload"]) for r in rows}

    # --------------------------------------------------------- mensagens
    def salvar_mensagem(self, exec_id: int, mensagem: dict):
        self.conn.execute(
            "INSERT OR REPLACE INTO mensagens (execucao_id, criada_em, conteudo) VALUES (?,?,?)",
            (exec_id, agora(), self.crypto.encrypt(mensagem)),
        )
        self.conn.commit()

    def ler_mensagem(self, exec_id: int) -> dict | None:
        row = self.conn.execute("SELECT conteudo FROM mensagens WHERE execucao_id=?", (exec_id,)).fetchone()
        return self.crypto.decrypt(row["conteudo"]) if row else None

    # ---------------------------------------------------------- retenção
    def limpar_mensagens_antigas(self, dias: int) -> int:
        limite = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(timespec="seconds")
        cur = self.conn.execute("DELETE FROM mensagens WHERE criada_em < ?", (limite,))
        self.conn.commit()
        return cur.rowcount
