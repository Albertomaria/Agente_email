"""
SQLite persistence for analysis results and pending actions.

We store the full SenderInfo list after Phase 1 so Phase 2 can serve it
instantly without re-querying the mail server, and Phase 3 can fetch
message_ids without another scan.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

import config
from models import SenderInfo, SenderAction, ExecutionResult, ActionType

_DB = str(config.DB_PATH)


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS senders (
            account_id  TEXT NOT NULL,
            email       TEXT NOT NULL,
            data        TEXT NOT NULL,   -- JSON of SenderInfo
            PRIMARY KEY (account_id, email)
        );

        CREATE TABLE IF NOT EXISTS actions (
            account_id    TEXT NOT NULL,
            sender_email  TEXT NOT NULL,
            action        TEXT NOT NULL,
            PRIMARY KEY (account_id, sender_email)
        );

        CREATE TABLE IF NOT EXISTS execution_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id      TEXT NOT NULL,
            sender_email    TEXT NOT NULL,
            action          TEXT NOT NULL,
            emails_deleted  INTEGER DEFAULT 0,
            unsubscribed    INTEGER DEFAULT 0,
            success         INTEGER DEFAULT 1,
            error           TEXT,
            ts              DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS analysis_meta (
            account_id      TEXT PRIMARY KEY,
            total_emails    INTEGER DEFAULT 0,
            total_senders   INTEGER DEFAULT 0,
            completed       INTEGER DEFAULT 0,
            error           TEXT,
            ts              DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)


class Database:
    """Synchronous SQLite wrapper (run in executor for async contexts)."""

    def __init__(self):
        init_db()

    # ── Senders ─────────────────────────────────────────────────────────────

    def upsert_sender(self, account_id: str, sender: SenderInfo) -> None:
        with _conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO senders (account_id, email, data) VALUES (?,?,?)",
                (account_id, sender.email, sender.model_dump_json()),
            )

    def get_senders(self, account_id: str) -> list[SenderInfo]:
        with _conn() as con:
            rows = con.execute(
                "SELECT data FROM senders WHERE account_id=? ORDER BY json_extract(data,'$.total_count') DESC",
                (account_id,),
            ).fetchall()
        return [SenderInfo(**json.loads(r["data"])) for r in rows]

    def clear_senders(self, account_id: str) -> None:
        with _conn() as con:
            con.execute("DELETE FROM senders WHERE account_id=?", (account_id,))

    # ── Analysis meta ────────────────────────────────────────────────────────

    def set_analysis_meta(
        self,
        account_id: str,
        total_emails: int,
        total_senders: int,
        completed: bool,
        error: Optional[str] = None,
    ) -> None:
        with _conn() as con:
            con.execute(
                """INSERT OR REPLACE INTO analysis_meta
                   (account_id, total_emails, total_senders, completed, error)
                   VALUES (?,?,?,?,?)""",
                (account_id, total_emails, total_senders, int(completed), error),
            )

    def get_analysis_meta(self, account_id: str) -> Optional[dict]:
        with _conn() as con:
            row = con.execute(
                "SELECT * FROM analysis_meta WHERE account_id=?", (account_id,)
            ).fetchone()
        return dict(row) if row else None

    # ── Actions ──────────────────────────────────────────────────────────────

    def set_action(self, action: SenderAction) -> None:
        with _conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO actions (account_id, sender_email, action) VALUES (?,?,?)",
                (action.account_id, action.sender_email, action.action.value),
            )

    def set_actions_bulk(self, actions: list[SenderAction]) -> None:
        with _conn() as con:
            con.executemany(
                "INSERT OR REPLACE INTO actions (account_id, sender_email, action) VALUES (?,?,?)",
                [(a.account_id, a.sender_email, a.action.value) for a in actions],
            )

    def get_actions(self, account_id: str) -> list[SenderAction]:
        with _conn() as con:
            rows = con.execute(
                "SELECT * FROM actions WHERE account_id=?", (account_id,)
            ).fetchall()
        return [
            SenderAction(
                account_id=r["account_id"],
                sender_email=r["sender_email"],
                action=ActionType(r["action"]),
            )
            for r in rows
        ]

    def clear_actions(self, account_id: str) -> None:
        with _conn() as con:
            con.execute("DELETE FROM actions WHERE account_id=?", (account_id,))

    # ── Execution log ────────────────────────────────────────────────────────

    def log_execution(self, result: ExecutionResult) -> None:
        with _conn() as con:
            con.execute(
                """INSERT INTO execution_log
                   (account_id, sender_email, action, emails_deleted, unsubscribed, success, error)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    result.account_id,
                    result.sender_email,
                    result.action.value,
                    result.emails_deleted,
                    int(result.unsubscribed),
                    int(result.success),
                    result.error,
                ),
            )

    def get_execution_log(self, account_id: str) -> list[dict]:
        with _conn() as con:
            rows = con.execute(
                "SELECT * FROM execution_log WHERE account_id=? ORDER BY ts DESC",
                (account_id,),
            ).fetchall()
        return [dict(r) for r in rows]
