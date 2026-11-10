"""Security helpers: rate limiting, audit log, password policy, one-time codes."""
import hashlib
import hmac
import random
import secrets
import time

from flask import current_app, g, request

from db import db, now_iso

COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890", "qwerty123", "iloveyou",
    "admin123", "welcome1", "letmein123", "abc12345", "india123", "chennai123", "tamilnadu1", "civicfix123",
}


def client_ip():
    return request.remote_addr or "unknown"


# ---------------- rate limiting (stored in the database, so it works across workers) ----------------
def rate_hit(key):
    with db() as con:
        con.execute("INSERT INTO rate_events(k, ts) VALUES(?,?)", (key, time.time()))
        if random.random() < 0.02:                     # occasional cleanup of old events
            con.execute("DELETE FROM rate_events WHERE ts < ?", (time.time() - 172800,))


def rate_count(key, window):
    with db() as con:
        return con.execute("SELECT COUNT(*) FROM rate_events WHERE k=? AND ts>?", (key, time.time() - window)).fetchone()[0]


def rate_blocked(key, limit, window):
    return rate_count(key, window) >= limit


# ---------------- audit log ----------------
def audit(action, target="", detail="", actor=None):
    actor = actor if actor is not None else g.get("_user")
    with db() as con:
        con.execute("INSERT INTO audit_log(ts,actor_id,actor_name,action,target,detail,ip) VALUES(?,?,?,?,?,?,?)",
                    (now_iso(), actor["id"] if actor else None, actor["name"] if actor else None,
                     action, str(target)[:200], str(detail)[:500], client_ip()))


# ---------------- passwords ----------------
def password_problem(pw, email="", name=""):
    if len(pw) < 8:
        return "Password must be at least 8 characters."
    if len(pw) > 128:
        return "Password is too long."
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        return "Use at least one letter and one number."
    low = pw.lower()
    if low in COMMON_PASSWORDS or (email and low == email.lower()) or (name and low == name.lower()):
        return "That password is too easy to guess. Choose another."
    return None


# ---------------- one-time codes (email verification, password reset) ----------------
def _hash(email, purpose, code):
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{email}|{purpose}|{code}".encode(), hashlib.sha256).hexdigest()


def issue_otp(email, purpose, ttl=600):
    code = f"{secrets.randbelow(1_000_000):06d}"
    with db() as con:
        con.execute("DELETE FROM otp_codes WHERE email=? AND purpose=?", (email, purpose))
        con.execute("INSERT INTO otp_codes(email,purpose,code_hash,expires,attempts) VALUES(?,?,?,?,0)",
                    (email, purpose, _hash(email, purpose, code), time.time() + ttl))
    return code


def check_otp(email, purpose, code):
    """True if the code is right. Max 5 tries per code; a code works once."""
    code = (code or "").strip()
    with db() as con:
        row = con.execute("SELECT * FROM otp_codes WHERE email=? AND purpose=?", (email, purpose)).fetchone()
        if not row or row["expires"] < time.time() or row["attempts"] >= 5:
            return False
        if not hmac.compare_digest(row["code_hash"], _hash(email, purpose, code)):
            con.execute("UPDATE otp_codes SET attempts=attempts+1 WHERE id=?", (row["id"],))
            return False
        con.execute("DELETE FROM otp_codes WHERE id=?", (row["id"],))
        return True
