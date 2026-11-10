"""Database layer: SQLite for local development, PostgreSQL in production.

Set DATABASE_URL=postgresql://... to use Postgres. Without it, a local SQLite file is used.
Code elsewhere writes SQL with `?` placeholders; this module adapts them for Postgres.
One connection is used per request and committed (or rolled back) when the request ends.
"""
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from flask import g, has_request_context

BASE = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
DB_PATH = Path(os.environ.get("CIVICFIX_DB", BASE / "civicfix.db"))

if IS_PG:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
    IntegrityError = psycopg2.IntegrityError
    _pool = None
else:
    IntegrityError = sqlite3.IntegrityError


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


class Conn:
    """Tiny wrapper so the rest of the app can call con.execute(sql, params) on either database."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        if IS_PG:
            cur = self.raw.cursor()
            cur.execute(sql.replace("?", "%s"), params)
            return cur
        return self.raw.execute(sql, params)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


def _connect():
    global _pool
    if IS_PG:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                1, int(os.environ.get("CIVICFIX_DB_POOL", "8")), DATABASE_URL,
                cursor_factory=psycopg2.extras.DictCursor, connect_timeout=10)
        for _ in range(3):
            raw = _pool.getconn()
            try:                                   # free-tier databases drop idle connections
                with raw.cursor() as cur:
                    cur.execute("SELECT 1")
                raw.rollback()
                return raw
            except Exception:
                _pool.putconn(raw, close=True)
        raise RuntimeError("Could not connect to the database")
    raw = sqlite3.connect(DB_PATH, timeout=10)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return raw


def _release(raw, ok):
    try:
        (raw.commit if ok else raw.rollback)()
    finally:
        if IS_PG:
            _pool.putconn(raw)
        else:
            raw.close()


@contextmanager
def db():
    """Inside a web request: the request's shared connection. Outside (startup, CLI): its own."""
    if has_request_context():
        if "_db" not in g:
            g._db = Conn(_connect())
        yield g._db
        return
    raw = _connect()
    ok = False
    try:
        yield Conn(raw)
        ok = True
    finally:
        _release(raw, ok)


def close_request_db(exc):
    con = g.pop("_db", None)
    if con is not None:
        _release(con.raw, exc is None)


def insert(con, sql, params=()):
    """INSERT and return the new row id on both databases."""
    if IS_PG:
        return con.execute(sql + " RETURNING id", params).fetchone()[0]
    return con.execute(sql, params).lastrowid


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
PK = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
INT = "BIGINT" if IS_PG else "INTEGER"
REAL = "DOUBLE PRECISION" if IS_PG else "REAL"

SCHEMA = [
    f"""CREATE TABLE IF NOT EXISTS users (
        id {PK}, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'citizen', district TEXT, department TEXT, created_at TEXT NOT NULL,
        email_verified INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0,
        deleted_at TEXT)""",
    f"""CREATE TABLE IF NOT EXISTS complaints (
        id {PK}, ticket TEXT NOT NULL UNIQUE, user_id {INT} NOT NULL REFERENCES users(id),
        title TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL,
        district TEXT NOT NULL, area TEXT NOT NULL, address TEXT,
        latitude {REAL}, longitude {REAL}, photo TEXT,
        status TEXT NOT NULL DEFAULT 'Submitted', priority TEXT NOT NULL DEFAULT 'Medium',
        assigned_to {INT} REFERENCES users(id), resolution_note TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        forwarded_to TEXT, approved_by {INT}, approved_at TEXT, resolved_at TEXT,
        resolution_photo TEXT, confirmed_at TEXT)""",
    f"""CREATE TABLE IF NOT EXISTS updates (
        id {PK}, complaint_id {INT} NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
        actor_id {INT} REFERENCES users(id), status TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL)""",
    f"""CREATE TABLE IF NOT EXISTS notifications (
        id {PK}, user_id {INT} NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        complaint_id {INT} REFERENCES complaints(id) ON DELETE CASCADE,
        message TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'info',
        is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""",
    f"""CREATE TABLE IF NOT EXISTS rate_events (id {PK}, k TEXT NOT NULL, ts {REAL} NOT NULL)""",
    f"""CREATE TABLE IF NOT EXISTS audit_log (
        id {PK}, ts TEXT NOT NULL, actor_id {INT}, actor_name TEXT, action TEXT NOT NULL,
        target TEXT, detail TEXT, ip TEXT)""",
    f"""CREATE TABLE IF NOT EXISTS otp_codes (
        id {PK}, email TEXT NOT NULL, purpose TEXT NOT NULL, code_hash TEXT NOT NULL,
        expires {REAL} NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS idx_c_district ON complaints(district, status)",
    "CREATE INDEX IF NOT EXISTS idx_c_user ON complaints(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_n_user ON notifications(user_id, is_read)",
    "CREATE INDEX IF NOT EXISTS idx_rate ON rate_events(k, ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(id)",
    "CREATE INDEX IF NOT EXISTS idx_otp ON otp_codes(email, purpose)",
]

# Columns added after the first release (old databases are upgraded automatically).
MIGRATIONS = {
    "complaints": [("forwarded_to", "TEXT"), ("approved_by", INT), ("approved_at", "TEXT"), ("resolved_at", "TEXT"),
                   ("resolution_photo", "TEXT"), ("confirmed_at", "TEXT")],
    "users": [("email_verified", "INTEGER NOT NULL DEFAULT 1"), ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
              ("deleted_at", "TEXT")],
}


def _columns(con, table):
    if IS_PG:
        rows = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", (table,)).fetchall()
        return {r[0] for r in rows}
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def init_schema():
    with db() as con:
        if IS_PG:
            con.execute("SELECT pg_advisory_xact_lock(7351)")   # several workers may start at once
        for stmt in SCHEMA:
            con.execute(stmt)
        for table, cols in MIGRATIONS.items():
            have = _columns(con, table)
            for name, decl in cols:
                if name not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        con.execute("UPDATE complaints SET status='Submitted' WHERE status='Under Review'")
        con.execute("UPDATE complaints SET status='Forwarded', forwarded_to=COALESCE(forwarded_to, category) WHERE status='Assigned'")
