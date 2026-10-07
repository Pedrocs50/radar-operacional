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
CREATE TABLE IF NOT EXISTS atualizacoes_tabela (   -- vigia: quando a origem mudou
    task_id       TEXT NOT NULL,
    modificada_em TEXT NOT NULL,           -- carimbo da tabela de origem (UTC)
    detectada_em  TEXT NOT NULL,
    PRIMARY KEY (task_id, modificada_em)
);
CREATE TABLE IF NOT EXISTS eventos (          -- movimentação: resolvida, mudou de CT, etc.
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    id_hash     TEXT NOT NULL,
    tipo        TEXT NOT NULL,             -- resolvida | voltou_gfw | saiu_criterio | nao_encontrada | mudou_ct
    quando      TEXT NOT NULL,
    execucao_id INTEGER NOT NULL,
    payload     BLOB NOT NULL              -- cifrado
);
CREATE TABLE IF NOT EXISTS verificacoes (     -- saúde do robô: cada checagem do vigia
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    em          TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    codigo_erro TEXT
);
CREATE TABLE IF NOT EXISTS estado (           -- chave/valor simples (situação do robô, último resumo)
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eventos_task ON eventos(task_id, quando);
CREATE INDEX IF NOT EXISTS ix_verif_task ON verificacoes(task_id, id);
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
        self.conn = sqlite3.connect(str(caminho), timeout=60)  # vigia e resumo podem coincidir
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        colunas = {r["name"] for r in self.conn.execute("PRAGMA table_info(execucoes)")}
        if "bytes_processados" not in colunas:  # migração: custo de cada execução
            self.conn.execute("ALTER TABLE execucoes ADD COLUMN bytes_processados INTEGER")
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

    def definir_bytes(self, exec_id: int, bytes_processados: int | None):
        if bytes_processados is not None:
            self.conn.execute("UPDATE execucoes SET bytes_processados=? WHERE id=?", (bytes_processados, exec_id))
            self.conn.commit()

    # --------------------------------------------------- movimentação (eventos)
    def registrar_evento(self, task_id: str, id_hash: str, tipo: str, exec_id: int, payload: dict):
        self.conn.execute(
            "INSERT INTO eventos (task_id, id_hash, tipo, quando, execucao_id, payload) VALUES (?,?,?,?,?,?)",
            (task_id, id_hash, tipo, agora(), exec_id, self.crypto.encrypt(payload)),
        )
        self.conn.commit()

    def listar_eventos(self, task_id: str, desde: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT tipo, quando, payload FROM eventos WHERE task_id=? AND quando>=? ORDER BY id", (task_id, desde))
        return [{"tipo": r["tipo"], "quando": r["quando"], **self.crypto.decrypt(r["payload"])} for r in rows]

    def contar_eventos(self, task_id: str, tipo: str, desde: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM eventos WHERE task_id=? AND tipo=? AND quando>=?", (task_id, tipo, desde)
        ).fetchone()[0]

    def alertas_desde(self, task_id: str, desde: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT primeiro_em, execucao_id, payload FROM alertas WHERE task_id=? AND primeiro_em>=?",
            (task_id, desde))
        return [{"quando": r["primeiro_em"], "execucao_id": r["execucao_id"], **self.crypto.decrypt(r["payload"])}
                for r in rows]

    def primeira_execucao_real(self, task_id: str) -> int | None:
        """Primeira execução real da tarefa = a base de referência (o que já existia não conta como entrada)."""
        return self.conn.execute("SELECT MIN(id) FROM execucoes WHERE task_id=? AND dry_run=0",
                                 (task_id,)).fetchone()[0]

    def hashes_avisados_desde(self, task_id: str, desde: str) -> set[str]:
        rows = self.conn.execute("SELECT id_hash FROM alertas WHERE task_id=? AND primeiro_em>=?", (task_id, desde))
        return {r["id_hash"] for r in rows}

    # --------------------------------------------------------- saúde do robô
    def registrar_verificacao(self, task_id: str, ok: bool, codigo_erro: str | None = None):
        self.conn.execute("INSERT INTO verificacoes (task_id, em, ok, codigo_erro) VALUES (?,?,?,?)",
                          (task_id, agora(), int(ok), codigo_erro))
        self.conn.commit()

    def ultimas_verificacoes(self, task_id: str, n: int = 10) -> list[dict]:
        rows = self.conn.execute("SELECT em, ok, codigo_erro FROM verificacoes WHERE task_id=? ORDER BY id DESC LIMIT ?",
                                 (task_id, n))
        return [dict(r) for r in rows]

    def estado_get(self, chave: str, padrao: str | None = None) -> str | None:
        row = self.conn.execute("SELECT valor FROM estado WHERE chave=?", (chave,)).fetchone()
        return row["valor"] if row else padrao

    def estado_set(self, chave: str, valor: str):
        self.conn.execute("INSERT INTO estado (chave, valor) VALUES (?,?) "
                          "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (chave, valor))
        self.conn.commit()

    # ------------------------------------------------------------- vigia
    def atualizacao_ja_tratada(self, task_id: str, modificada_em: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM atualizacoes_tabela WHERE task_id=? AND modificada_em=?", (task_id, modificada_em)
        ).fetchone()
        return row is not None

    def registrar_atualizacao(self, task_id: str, modificada_em: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO atualizacoes_tabela (task_id, modificada_em, detectada_em) VALUES (?,?,?)",
            (task_id, modificada_em, agora()),
        )
        self.conn.commit()

    def listar_atualizacoes(self, task_id: str, limite: int = 30):
        rows = self.conn.execute(
            "SELECT modificada_em, detectada_em FROM atualizacoes_tabela WHERE task_id=? "
            "ORDER BY modificada_em DESC LIMIT ?", (task_id, limite))
        return [dict(r) for r in rows]

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
    def limpar_historico_tecnico(self, dias: int) -> int:
        """Apaga snapshots e verificações antigos (o estado "já avisei" e os eventos ficam)."""
        limite = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(timespec="seconds")
        ids = [r["id"] for r in self.conn.execute(
            "SELECT id FROM execucoes WHERE inicio < ? AND id NOT IN "
            "(SELECT MAX(id) FROM execucoes WHERE dry_run=0 GROUP BY task_id)", (limite,))]
        for i in ids:
            self.conn.execute("DELETE FROM snapshots WHERE execucao_id=?", (i,))
        cur = self.conn.execute("DELETE FROM verificacoes WHERE em < ?", (limite,))
        self.conn.commit()
        return len(ids) + cur.rowcount

    def limpar_mensagens_antigas(self, dias: int) -> int:
        limite = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(timespec="seconds")
        cur = self.conn.execute("DELETE FROM mensagens WHERE criada_em < ?", (limite,))
        self.conn.commit()
        return cur.rowcount
