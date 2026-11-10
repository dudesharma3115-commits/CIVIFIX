"""Small shared helpers: ticket ids, case history, notifications."""
import secrets
from datetime import datetime

from db import now_iso


def ticket_id():
    return "CF-" + datetime.now().strftime("%y%m%d") + "-" + secrets.token_hex(3).upper()


def add_update(con, cid, actor_id, status, note, when=None):
    con.execute("INSERT INTO updates(complaint_id,actor_id,status,note,created_at) VALUES(?,?,?,?,?)",
                (cid, actor_id, status, note, when or now_iso()))


def notify(con, user_ids, cid, message, kind="info", when=None):
    for uid in {u for u in user_ids if u}:
        con.execute("INSERT INTO notifications(user_id,complaint_id,message,kind,created_at) VALUES(?,?,?,?,?)",
                    (uid, cid, message, kind, when or now_iso()))


def ids_of(con, sql, params=()):
    return [r[0] for r in con.execute(sql, params).fetchall()]
