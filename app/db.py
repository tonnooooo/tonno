"""Persistenza SQLite: transazionale, WAL, senza cancellazioni distruttive.

Scelte fatte apposta contro i bug segnalati:

1. SQLite in modalita' WAL invece di file JSON. Un JSON riscritto a ogni
   messaggio si tronca al primo crash/riavvio o alle scritture concorrenti:
   e' la causa numero uno del "la chat sparisce / non si apre piu'".
2. I messaggi non si cancellano MAI durante la compattazione: si marcano
   `archived_at`. Il riassunto e' un nuovo record. Se la compattazione va
   storta, la conversazione resta integra e si puo' fare rollback.
3. Ogni compattazione e' una singola transazione: o inserisce il riassunto
   e archivia, o non fa niente.
4. `seq` monotono per conversazione con vincolo UNIQUE: niente messaggi
   fuori ordine o duplicati da doppio invio.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

SCHEMA_VERSION = 1

# I `seq` avanzano a passi di 1000 invece che di 1: lascia spazio per
# inserire un riassunto ESATTAMENTE nel punto della cronologia da cui
# proviene, senza violare il vincolo UNIQUE(conversation_id, seq) e senza
# dover rinumerare i messaggi (rinumerare e' l'operazione che, sbagliata,
# fa "saltare" l'ordine della chat).
SEQ_STEP = 1000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL DEFAULT 'Nuova chat',
    system_prompt     TEXT NOT NULL DEFAULT '',
    model             TEXT,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL,
    deleted_at        REAL,
    next_seq          INTEGER NOT NULL DEFAULT 1000,
    compaction_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id        TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq                    INTEGER NOT NULL,
    role                   TEXT NOT NULL,
    content                TEXT NOT NULL DEFAULT '',
    name                   TEXT,
    tool_call_id           TEXT,
    tool_calls             TEXT,
    tokens                 INTEGER NOT NULL DEFAULT 0,
    kind                   TEXT NOT NULL DEFAULT 'chat',
    compaction_level       INTEGER NOT NULL DEFAULT 0,
    archived_at            REAL,
    archived_by            INTEGER,
    created_at             REAL NOT NULL,
    UNIQUE (conversation_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_active
    ON messages (conversation_id, archived_at, seq);
CREATE INDEX IF NOT EXISTS idx_messages_conv_seq
    ON messages (conversation_id, seq);

CREATE TABLE IF NOT EXISTS compactions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id    TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    summary_message_id INTEGER,
    from_seq           INTEGER NOT NULL,
    to_seq             INTEGER NOT NULL,
    archived_count     INTEGER NOT NULL DEFAULT 0,
    tokens_before      INTEGER NOT NULL DEFAULT 0,
    tokens_after       INTEGER NOT NULL DEFAULT 0,
    level              INTEGER NOT NULL DEFAULT 1,
    status             TEXT NOT NULL DEFAULT 'ok',
    detail             TEXT,
    created_at         REAL NOT NULL,
    reverted_at        REAL
);

CREATE INDEX IF NOT EXISTS idx_compactions_conv
    ON compactions (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    """Wrapper sincrono su SQLite. Le route async lo chiamano in threadpool."""

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        # check_same_thread=False + lock esplicito: una sola connessione,
        # serializzata da noi. Evita il "database is locked" dei pool naif.
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._configure()
        self._migrate()

    # ------------------------------------------------------------------ setup
    def _configure(self) -> None:
        cur = self._conn
        cur.execute("PRAGMA journal_mode=WAL")       # letture concorrenti alle scritture
        cur.execute("PRAGMA synchronous=NORMAL")     # durabilita' sufficiente, molto piu' veloce
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA wal_autocheckpoint=512")

    def _migrate(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            row = self._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
                )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transazione esplicita: commit in uscita, rollback su eccezione."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def integrity_check(self) -> str:
        with self._lock:
            row = self._conn.execute("PRAGMA integrity_check").fetchone()
            return row[0] if row else "unknown"

    # ---------------------------------------------------------- conversazioni
    def create_conversation(
        self, title: str = "Nuova chat", system_prompt: str = "", model: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
        cid = conversation_id or uuid.uuid4().hex
        now = time.time()
        with self.tx() as c:
            c.execute(
                "INSERT INTO conversations (id, title, system_prompt, model, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (cid, title, system_prompt, model, now, now),
            )
        return cid

    def get_conversation(self, cid: str, include_deleted: bool = False) -> dict[str, Any] | None:
        with self._lock:
            sql = "SELECT * FROM conversations WHERE id=?"
            if not include_deleted:
                sql += " AND deleted_at IS NULL"
            row = self._conn.execute(sql, (cid,)).fetchone()
        return dict(row) if row else None

    def list_conversations(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.*, "
                " (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id AND m.archived_at IS NULL) AS active_messages,"
                " (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS total_messages"
                " FROM conversations c WHERE c.deleted_at IS NULL"
                " ORDER BY c.updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_conversation(self, cid: str, **fields: Any) -> bool:
        allowed = {"title", "system_prompt", "model"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return False
        cols = ", ".join(f"{k}=?" for k in sets)
        with self.tx() as c:
            cur = c.execute(
                f"UPDATE conversations SET {cols}, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (*sets.values(), time.time(), cid),
            )
        return cur.rowcount > 0

    def soft_delete_conversation(self, cid: str) -> bool:
        """Cancellazione logica: i dati restano, la chat si puo' ripristinare."""
        with self.tx() as c:
            cur = c.execute(
                "UPDATE conversations SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (time.time(), time.time(), cid),
            )
        return cur.rowcount > 0

    def restore_conversation(self, cid: str) -> bool:
        with self.tx() as c:
            cur = c.execute(
                "UPDATE conversations SET deleted_at=NULL, updated_at=? WHERE id=?", (time.time(), cid)
            )
        return cur.rowcount > 0

    # -------------------------------------------------------------- messaggi
    def add_message(
        self,
        cid: str,
        role: str,
        content: str = "",
        *,
        tokens: int = 0,
        name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        kind: str = "chat",
        compaction_level: int = 0,
        seq: int | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Inserisce un messaggio assegnando `seq` in modo atomico."""

        def _insert(c: sqlite3.Connection) -> int:
            row = c.execute(
                "SELECT next_seq FROM conversations WHERE id=?", (cid,)
            ).fetchone()
            if row is None:
                raise KeyError(f"conversazione inesistente: {cid}")
            next_seq = int(row["next_seq"])
            explicit = seq is not None
            use_seq = int(seq) if explicit else next_seq
            cur = c.execute(
                "INSERT INTO messages (conversation_id, seq, role, content, name, tool_call_id,"
                " tool_calls, tokens, kind, compaction_level, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cid, use_seq, role, content or "", name, tool_call_id,
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    tokens, kind, compaction_level, time.time(),
                ),
            )
            c.execute(
                "UPDATE conversations SET next_seq=?, updated_at=? WHERE id=?",
                (max(next_seq, use_seq + 1) if explicit else next_seq + SEQ_STEP, time.time(), cid),
            )
            return int(cur.lastrowid)

        if conn is not None:  # gia' dentro una transazione del chiamante
            return _insert(conn)
        with self.tx() as c:
            return _insert(c)

    def free_seq_after(self, cid: str, after_seq: int, conn: sqlite3.Connection) -> int:
        """Primo `seq` libero subito dopo `after_seq`.

        Serve a inserire il riassunto nel punto giusto della cronologia.
        Grazie a SEQ_STEP c'e' sempre spazio; se per qualche motivo non ce
        n'e', si ripiega in coda invece di sollevare."""
        row = conn.execute(
            "SELECT MAX(seq) AS m FROM messages WHERE conversation_id=? AND seq>? AND seq<?",
            (cid, after_seq, after_seq + SEQ_STEP),
        ).fetchone()
        candidate = (int(row["m"]) + 1) if row and row["m"] is not None else after_seq + 1
        if candidate >= after_seq + SEQ_STEP:
            tail = conn.execute(
                "SELECT next_seq FROM conversations WHERE id=?", (cid,)
            ).fetchone()
            return int(tail["next_seq"]) if tail else after_seq + 1
        return candidate

    def get_messages(
        self, cid: str, *, active_only: bool = True, limit: int | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM messages WHERE conversation_id=?"
        params: list[Any] = [cid]
        if active_only:
            sql += " AND archived_at IS NULL"
        sql += " ORDER BY seq ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_message(r) for r in rows]

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if d.get("tool_calls"):
            try:
                d["tool_calls"] = json.loads(d["tool_calls"])
            except (TypeError, ValueError):
                d["tool_calls"] = None
        return d

    def archive_messages(
        self, cid: str, message_ids: list[int], summary_id: int, conn: sqlite3.Connection
    ) -> int:
        """Archivia (NON cancella) i messaggi assorbiti da un riassunto."""
        if not message_ids:
            return 0
        now = time.time()
        placeholders = ",".join("?" * len(message_ids))
        cur = conn.execute(
            f"UPDATE messages SET archived_at=?, archived_by=? "
            f"WHERE conversation_id=? AND archived_at IS NULL AND id IN ({placeholders})",
            (now, summary_id, cid, *message_ids),
        )
        return cur.rowcount

    def count_active_messages(self, cid: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE conversation_id=? AND archived_at IS NULL",
                (cid,),
            ).fetchone()
        return int(row["n"]) if row else 0

    # ---------------------------------------------------------- compattazioni
    def record_compaction(self, conn: sqlite3.Connection, **fields: Any) -> int:
        cur = conn.execute(
            "INSERT INTO compactions (conversation_id, summary_message_id, from_seq, to_seq,"
            " archived_count, tokens_before, tokens_after, level, status, detail, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                fields["conversation_id"], fields.get("summary_message_id"), fields["from_seq"],
                fields["to_seq"], fields.get("archived_count", 0), fields.get("tokens_before", 0),
                fields.get("tokens_after", 0), fields.get("level", 1), fields.get("status", "ok"),
                fields.get("detail"), time.time(),
            ),
        )
        if fields.get("status") == "ok":
            conn.execute(
                "UPDATE conversations SET compaction_count = compaction_count + 1, updated_at=? WHERE id=?",
                (time.time(), fields["conversation_id"]),
            )
        return int(cur.lastrowid)

    def list_compactions(self, cid: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM compactions WHERE conversation_id=? ORDER BY id ASC", (cid,)
            ).fetchall()
        return [dict(r) for r in rows]

    def revert_last_compaction(self, cid: str) -> dict[str, Any] | None:
        """Annulla l'ultima compattazione riuscita: e' possibile solo perche'
        i messaggi non vengono mai cancellati."""
        with self.tx() as c:
            row = c.execute(
                "SELECT * FROM compactions WHERE conversation_id=? AND status='ok'"
                " AND reverted_at IS NULL ORDER BY id DESC LIMIT 1",
                (cid,),
            ).fetchone()
            if row is None:
                return None
            comp = dict(row)
            restored = c.execute(
                "UPDATE messages SET archived_at=NULL, archived_by=NULL"
                " WHERE conversation_id=? AND archived_by=?",
                (cid, comp["summary_message_id"]),
            ).rowcount
            if comp["summary_message_id"]:
                # Il riassunto viene archiviato, non cancellato: resta lo storico.
                c.execute(
                    "UPDATE messages SET archived_at=? WHERE id=? AND conversation_id=?",
                    (time.time(), comp["summary_message_id"], cid),
                )
            c.execute("UPDATE compactions SET reverted_at=? WHERE id=?", (time.time(), comp["id"]))
            c.execute(
                "UPDATE conversations SET compaction_count = MAX(compaction_count - 1, 0), updated_at=?"
                " WHERE id=?",
                (time.time(), cid),
            )
            comp["restored_messages"] = restored
            return comp

    # ------------------------------------------------------------ diagnostica
    def stats(self) -> dict[str, Any]:
        with self._lock:
            q = self._conn.execute
            return {
                "conversations": q("SELECT COUNT(*) n FROM conversations WHERE deleted_at IS NULL").fetchone()["n"],
                "conversations_deleted": q("SELECT COUNT(*) n FROM conversations WHERE deleted_at IS NOT NULL").fetchone()["n"],
                "messages_total": q("SELECT COUNT(*) n FROM messages").fetchone()["n"],
                "messages_archived": q("SELECT COUNT(*) n FROM messages WHERE archived_at IS NOT NULL").fetchone()["n"],
                "compactions_ok": q("SELECT COUNT(*) n FROM compactions WHERE status='ok'").fetchone()["n"],
                "compactions_failed": q("SELECT COUNT(*) n FROM compactions WHERE status!='ok'").fetchone()["n"],
                "db_path": self.path,
                "db_size_bytes": os.path.getsize(self.path) if self.path != ":memory:" and os.path.exists(self.path) else 0,
            }


_db: Database | None = None
_db_lock = threading.Lock()


def get_db(path: str | None = None) -> Database:
    global _db
    with _db_lock:
        if _db is None:
            from app.config import get_settings

            _db = Database(path or get_settings().db_path)
        return _db


def set_db(db: Database | None) -> None:
    """Iniezione usata dai test."""
    global _db
    with _db_lock:
        _db = db
