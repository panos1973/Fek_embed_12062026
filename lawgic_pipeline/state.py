"""state.py — local SQLite state store (stdlib sqlite3, no deps).

Tracks each document through the pipeline for resume, dedup (content_hash),
idempotency and a human-review queue.
"""
from __future__ import annotations
import sqlite3
import time
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,   -- instrument_key or path-hash
    path          TEXT NOT NULL,
    content_hash  TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|done|review|error
    stage         TEXT,               -- last completed stage
    confidence    REAL,
    error         TEXT,
    created_at    REAL,
    updated_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_hash   ON documents(content_hash);
"""


class State:
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def seen_hash(self, content_hash: str) -> bool:
        cur = self.db.execute(
            "SELECT 1 FROM documents WHERE content_hash=? AND status='done'",
            (content_hash,))
        return cur.fetchone() is not None

    def upsert(self, doc_id: str, path: str, content_hash: str = "") -> None:
        now = time.time()
        self.db.execute(
            """INSERT INTO documents(doc_id,path,content_hash,status,created_at,updated_at)
               VALUES(?,?,?,'pending',?,?)
               ON CONFLICT(doc_id) DO UPDATE SET path=excluded.path,
                 content_hash=excluded.content_hash, updated_at=excluded.updated_at""",
            (doc_id, path, content_hash, now, now))
        self.db.commit()

    def set_status(self, doc_id: str, status: str, stage: str = None,
                   confidence: float = None, error: str = None) -> None:
        self.db.execute(
            """UPDATE documents SET status=?, stage=COALESCE(?,stage),
                 confidence=COALESCE(?,confidence), error=?, updated_at=?
               WHERE doc_id=?""",
            (status, stage, confidence, error, time.time(), doc_id))
        self.db.commit()

    def by_status(self, status: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM documents WHERE status=?", (status,)).fetchall()

    def pending(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM documents WHERE status IN ('pending','error')").fetchall()

    def counts(self) -> dict:
        rows = self.db.execute(
            "SELECT status, COUNT(*) c FROM documents GROUP BY status").fetchall()
        return {r["status"]: r["c"] for r in rows}

    def close(self):
        self.db.close()
