"""CivicFix India: civic issue reporting & resolution platform (Flask).

Workflow:  Citizen reports (photo + map pin) -> District admin approves/rejects -> forwards to the
           department (e.g. TNEB) -> officer works on it and resolves with proof -> citizen confirms or reopens.
Roles:     citizen · staff (department officer) · district_admin · superadmin
Run:       python app.py            (development)
           gunicorn wsgi:app        (production, see README)
"""
import json
import logging
import os
import random
import re
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps

import click
from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import mailer
import storage
from constants import (AGENCIES, DEPARTMENTS, DISTRICT_CENTERS, DISTRICTS, ICONS, PRIORITIES, ROLE_LABELS, STATUSES)
from db import BASE, IS_PG, IntegrityError, close_request_db, db, init_schema, insert, now_iso
from security import (audit, check_otp, client_ip, issue_otp, password_problem, rate_blocked, rate_hit)
from services import add_update, ids_of, notify, ticket_id

log = logging.getLogger("civicfix")

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
ENV = os.environ.get("CIVICFIX_ENV", "development").lower()
PROD = ENV == "production"
SECRET = os.environ.get("CIVICFIX_SECRET", "")
if PROD and len(SECRET) < 32:
    raise RuntimeError("Set CIVICFIX_SECRET to a random value of 32+ characters before running in production.")
DEMO_MODE = os.environ.get("CIVICFIX_DEMO", "0" if PROD else "1") == "1"
REQUIRE_VERIFY = os.environ.get("CIVICFIX_REQUIRE_VERIFY", "1" if mailer.configured() else "0") == "1"
SLA_HOURS = 72
REOPEN_DAYS = 14
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
DUMMY_HASH = generate_password_hash("not-a-real-password")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET or "dev-only-secret-change-me",
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SESSION_COOKIE_NAME="cf_session", SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=PROD, PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)
app.json.sort_keys = False
_proxies = int(os.environ.get("CIVICFIX_PROXIES", "1" if PROD else "0"))
if _proxies:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=_proxies, x_proto=_proxies, x_host=_proxies)
app.teardown_request(close_request_db)
logging.basicConfig(level=logging.INFO)


@app.template_global()
def icon(name, size=20):
    return Markup(
        f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true"><path d="{ICONS.get(name, ICONS["pin"])}"/></svg>')


@app.template_global()
def media(name):
    return url_for("media", name=name)


# --------------------------------------------------------------------------- #
# Auth, permissions, CSRF, security headers
# --------------------------------------------------------------------------- #
def current_user():
    if "_user" not in g:
        g._user = None
        uid = session.get("user_id")
        if uid:
            with db() as con:
                g._user = con.execute("SELECT * FROM users WHERE id=? AND deleted_at IS NULL", (uid,)).fetchone()
            if g._user is None:
                session.clear()
    return g._user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user()["role"] not in allowed:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def scope(user, alias=""):
    """SQL WHERE fragment limiting complaints to what this user may see."""
    p = alias + "." if alias else ""
    role = user["role"]
    if role == "superadmin":
        return "1=1", ()
    if role == "district_admin":
        return f"{p}district=?", (user["district"],)
    if role == "staff":
        return (f"{p}district=? AND ({p}forwarded_to=? OR {p}assigned_to=?)",
                (user["district"], user["department"], user["id"]))
    return f"{p}user_id=?", (user["id"],)


def can_view(user, c):
    role = user["role"]
    if role == "superadmin":
        return True
    if role == "district_admin":
        return user["district"] == c["district"]
    if role == "staff":
        return user["district"] == c["district"] and (
            c["forwarded_to"] == user["department"] or c["assigned_to"] == user["id"])
    return c["user_id"] == user["id"]


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.add_template_global(csrf_token, "csrf_token")


@app.template_global()
def csrf_input():
    return Markup(f'<input type="hidden" name="_csrf" value="{csrf_token()}">')


@app.before_request
def guard():
    g.nonce = secrets.token_urlsafe(16)
    if request.endpoint in ("static", "healthz"):
        return None
    if PROD and not request.is_secure and request.endpoint != "healthz":
        return redirect(request.url.replace("http://", "https://", 1), code=301)
    if request.method == "POST":
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("_csrf", "")
        if not sent or not expected or not secrets.compare_digest(sent, expected):
            abort(400)
    user = current_user()
    if user and user["must_change_password"] and request.endpoint not in ("account", "logout", "static", "healthz"):
        flash("For security, please set a new password before continuing.", "warn")
        return redirect(url_for("account"))


@app.after_request
def secure_headers(resp):
    nonce = g.get("nonce", "")
    resp.headers["Content-Security-Policy"] = "; ".join([
        "default-src 'self'", f"script-src 'self' 'nonce-{nonce}' https://unpkg.com",
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob: https://*.basemaps.cartocdn.com https://unpkg.com",
        "connect-src 'self'", "manifest-src 'self'", "worker-src 'self'",
        "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"])
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(self), camera=(self), microphone=(), payment=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if PROD:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.endpoint not in ("static", "media") and "Cache-Control" not in resp.headers:
        resp.headers["Cache-Control"] = "no-store"
    return resp


def safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


def pending_count(user):
    if not user or user["role"] not in ("district_admin", "superadmin"):
        return 0
    where, params = scope(user)
    with db() as con:
        return con.execute(f"SELECT COUNT(*) FROM complaints WHERE {where} AND status='Submitted'", params).fetchone()[0]


@app.context_processor
def inject_globals():
    user = current_user()
    unread = 0
    if user:
        with db() as con:
            unread = con.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user["id"],)).fetchone()[0]
    return {"me": user, "districts": DISTRICTS, "departments": DEPARTMENTS, "statuses": STATUSES,
            "agencies": AGENCIES, "role_labels": ROLE_LABELS, "icons": ICONS, "centers": DISTRICT_CENTERS,
            "unread": unread, "pending_badge": pending_count(user), "demo_mode": DEMO_MODE,
            "nonce": g.get("nonce", ""), "reopen_days": REOPEN_DAYS,
            "contact_email": os.environ.get("CIVICFIX_CONTACT_EMAIL", "contact@your-domain.in")}


def fail_page(code, message):
    return render_template("error.html", code=code, message=message), code


# --------------------------------------------------------------------------- #
# Dashboard data (role-scoped)
# --------------------------------------------------------------------------- #
def parse_ts(s):
    return datetime.fromisoformat(s) if s else None


def hours_between(a, b):
    return (parse_ts(b) - parse_ts(a)).total_seconds() / 3600


def jitter(cid):
    r = random.Random(cid * 7919)
    return (r.uniform(-0.035, 0.035), r.uniform(-0.035, 0.035))


def markers_for(con, user):
    where, params = scope(user)
    if user["role"] == "citizen":
        rows = con.execute("SELECT * FROM complaints WHERE user_id=? OR (district=? AND status NOT IN ('Submitted','Rejected')) "
                           "ORDER BY created_at DESC LIMIT 400", (user["id"], user["district"])).fetchall()
    else:
        rows = con.execute(f"SELECT * FROM complaints WHERE {where} ORDER BY created_at DESC LIMIT 400", params).fetchall()
    out = []
    for r in rows:
        approx = r["latitude"] is None or r["longitude"] is None
        if approx:
            clat, clng = DISTRICT_CENTERS.get(r["district"], (11.1271, 78.6569))
            dlat, dlng = jitter(r["id"])
            lat, lng = clat + dlat, clng + dlng
        else:
            lat, lng = r["latitude"], r["longitude"]
        out.append({"id": r["id"], "ticket": r["ticket"], "title": r["title"], "lat": lat, "lng": lng,
                    "status": r["status"], "priority": r["priority"], "category": r["category"],
                    "area": r["area"], "district": r["district"], "approx": approx, "mine": r["user_id"] == user["id"],
                    "url": url_for("complaint_detail", complaint_id=r["id"]) if can_view(user, r) else None})
    return out


def dept_stats(con, user):
    where, params = scope(user)
    rows = con.execute(f"SELECT forwarded_to, status, priority, created_at, resolved_at FROM complaints "
                       f"WHERE {where} AND forwarded_to IS NOT NULL", params).fetchall()
    agg = {d: {"total": 0, "resolved": 0, "open": 0, "critical": 0, "hours": []} for d in DEPARTMENTS}
    for r in rows:
        a = agg.get(r["forwarded_to"])
        if not a:
            continue
        a["total"] += 1
        if r["status"] == "Resolved":
            a["resolved"] += 1
            if r["resolved_at"]:
                a["hours"].append(hours_between(r["created_at"], r["resolved_at"]))
        elif r["status"] in ("Forwarded", "In Progress"):
            a["open"] += 1
            a["critical"] += r["priority"] == "Critical"
    if user["role"] == "district_admin":
        orows = con.execute("SELECT department, COUNT(*) AS n FROM users WHERE role='staff' AND district=? AND deleted_at IS NULL GROUP BY department", (user["district"],)).fetchall()
    else:
        orows = con.execute("SELECT department, COUNT(*) AS n FROM users WHERE role='staff' AND deleted_at IS NULL GROUP BY department").fetchall()
    officers = {r["department"]: r["n"] for r in orows}
    out = []
    for d in DEPARTMENTS:
        a = agg[d]
        out.append({"dept": d, "short": AGENCIES[d]["short"], "name": AGENCIES[d]["name"], "icon": AGENCIES[d]["icon"],
                    "color": AGENCIES[d]["color"], "total": a["total"], "resolved": a["resolved"], "open": a["open"],
                    "critical": a["critical"], "officers": officers.get(d, 0),
                    "avg_hours": round(sum(a["hours"]) / len(a["hours"]), 1) if a["hours"] else None})
    return out


def build_dashboard(user):
    where, params = scope(user)
    open_in = "('Submitted','Approved','Forwarded','In Progress')"
    with db() as con:
        by_status = {s: 0 for s in STATUSES}
        for r in con.execute(f"SELECT status, COUNT(*) AS n FROM complaints WHERE {where} GROUP BY status", params):
            by_status[r["status"]] = r["n"]
        total = sum(by_status.values())
        resolved = by_status["Resolved"]
        critical = con.execute(f"SELECT COUNT(*) FROM complaints WHERE {where} AND priority='Critical' AND status IN {open_in}", params).fetchone()[0]
        done = con.execute(f"SELECT created_at, resolved_at FROM complaints WHERE {where} AND status='Resolved' AND resolved_at IS NOT NULL "
                           f"ORDER BY resolved_at DESC LIMIT 3000", params).fetchall()
        hrs = [hours_between(r["created_at"], r["resolved_at"]) for r in done]
        avg_h = sum(hrs) / len(hrs) if hrs else None
        on_time = sum(1 for h in hrs if h <= SLA_HOURS)
        by_cat = {d: 0 for d in DEPARTMENTS}
        for r in con.execute(f"SELECT category, COUNT(*) AS n FROM complaints WHERE {where} GROUP BY category", params):
            by_cat[r["category"]] = r["n"]

        days = [(datetime.now().date() - timedelta(days=i)) for i in range(6, -1, -1)]
        since = days[0].isoformat()
        rep = {r["d"]: r["n"] for r in con.execute(f"SELECT substr(created_at,1,10) AS d, COUNT(*) AS n FROM complaints WHERE {where} AND created_at>=? GROUP BY substr(created_at,1,10)", params + (since,))}
        res = {r["d"]: r["n"] for r in con.execute(f"SELECT substr(resolved_at,1,10) AS d, COUNT(*) AS n FROM complaints WHERE {where} AND resolved_at>=? GROUP BY substr(resolved_at,1,10)", params + (since,))}
        trend = [{"day": d.strftime("%a"), "reported": rep.get(d.isoformat(), 0), "resolved": res.get(d.isoformat(), 0)} for d in days]
        hotspots = [dict(r) for r in con.execute(f"SELECT area, COUNT(*) AS n FROM complaints WHERE {where} AND status IN {open_in} GROUP BY area ORDER BY n DESC LIMIT 3", params)]
        alerts = [dict(r) for r in con.execute(
            f"SELECT id, ticket, title, area, priority, category, status, created_at FROM complaints WHERE {where} "
            f"AND priority IN ('Critical','High') AND status IN {open_in} ORDER BY CASE priority WHEN 'Critical' THEN 0 ELSE 1 END, created_at DESC LIMIT 4", params)]
        for a in alerts:
            a["url"] = url_for("complaint_detail", complaint_id=a["id"])
        awhere, aparams = scope(user, "c")
        activity = [dict(r) for r in con.execute(
            f"SELECT u.status, u.note, u.created_at, c.id AS cid, c.ticket, c.title, us.name AS actor FROM updates u "
            f"JOIN complaints c ON c.id=u.complaint_id LEFT JOIN users us ON us.id=u.actor_id WHERE {awhere} "
            f"ORDER BY u.created_at DESC, u.id DESC LIMIT 8", aparams)]
        for a in activity:
            a["url"] = url_for("complaint_detail", complaint_id=a["cid"])
        role = user["role"]
        if role in ("district_admin", "superadmin"):
            qsql, qtitle = "status='Submitted'", "Awaiting your approval"
        elif role == "staff":
            qsql, qtitle = "status IN ('Forwarded','In Progress')", "Forwarded to your department"
        else:
            qsql, qtitle = "1=1", "Your latest reports"
        order = ("CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, created_at DESC" if role != "citizen" else "created_at DESC")
        queue = [dict(r) for r in con.execute(
            f"SELECT id, ticket, title, area, district, priority, category, status, created_at FROM complaints WHERE {where} AND {qsql} ORDER BY {order} LIMIT 6", params)]
        for q in queue:
            q["url"] = url_for("complaint_detail", complaint_id=q["id"])
        departments = dept_stats(con, user) if role in ("district_admin", "superadmin") else []
        districts = []
        if role == "superadmin":
            districts = [dict(r) for r in con.execute("SELECT district, COUNT(*) AS total, SUM(CASE WHEN status='Resolved' THEN 1 ELSE 0 END) AS resolved FROM complaints GROUP BY district ORDER BY total DESC LIMIT 6")]
        markers = markers_for(con, user)
    return {"role": role, "district": user["district"], "total": total, "by_status": by_status,
            "pending": by_status["Submitted"], "active": by_status["Approved"] + by_status["Forwarded"] + by_status["In Progress"],
            "in_field": by_status["Forwarded"] + by_status["In Progress"], "resolved": resolved, "rejected": by_status["Rejected"],
            "critical": critical, "resolution_rate": round(resolved / total * 100) if total else 0,
            "on_time_rate": round(on_time / len(hrs) * 100) if hrs else 0,
            "avg_hours": round(avg_h, 1) if avg_h is not None else None, "sla_hours": SLA_HOURS,
            "by_category": by_cat, "trend": trend, "hotspots": hotspots, "alerts": alerts, "activity": activity,
            "queue": queue, "queue_title": qtitle, "departments": departments, "districts": districts,
            "markers": markers, "server_time": now_iso()}


# --------------------------------------------------------------------------- #
# Public pages
# --------------------------------------------------------------------------- #
@app.route("/healthz")
def healthz():
    with db() as con:
        con.execute("SELECT 1").fetchone()
    return jsonify({"status": "ok"})


@app.route("/")
def home():
    if current_user():
        return redirect(url_for("dashboard"))
    with db() as con:
        stats = {"reported": con.execute("SELECT COUNT(*) FROM complaints").fetchone()[0],
                 "resolved": con.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0],
                 "districts": len(DISTRICTS)}
    return render_template("index.html", stats=stats)


@app.route("/track")
def track():
    """Public status lookup by ticket number. Shows status and dates only, never personal details."""
    t = request.args.get("ticket", "").strip().upper()[:30]
    info = steps = None
    if t:
        if rate_blocked(f"track:{client_ip()}", 30, 600):
            flash("Too many lookups. Please wait a few minutes.", "warn")
        else:
            rate_hit(f"track:{client_ip()}")
            with db() as con:
                info = con.execute("SELECT id, ticket, category, district, area, status, forwarded_to, created_at, updated_at FROM complaints WHERE ticket=?", (t,)).fetchone()
                if info:
                    hist = con.execute("SELECT status, created_at FROM updates WHERE complaint_id=? ORDER BY created_at, id", (info["id"],)).fetchall()
                    steps = {}
                    for h in hist:
                        steps.setdefault(h["status"], {"at": h["created_at"], "by": None})
            if not info:
                flash("No report found with that ticket number. Check it and try again.", "error")
    return render_template("track.html", ticket=t, info=info, steps=steps)


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


# --------------------------------------------------------------------------- #
# Accounts: register, verify, login, reset, account page
# --------------------------------------------------------------------------- #
def send_code(email, purpose, subject, intro):
    code = issue_otp(email, purpose)
    mailer.send_mail(email, subject, f"{intro}\n\nYour CivicFix code is: {code}\n\nIt expires in 10 minutes. If you didn't ask for it, ignore this email.\n")


def start_session(user):
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    csrf_token()


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if rate_blocked(f"reg:{client_ip()}", 5, 3600):
            return fail_page(429, "Too many sign-ups from this network. Please try again later.")
        rate_hit(f"reg:{client_ip()}")
        f = request.form
        name, email = f.get("name", "").strip(), f.get("email", "").strip().lower()
        password, district = f.get("password", ""), f.get("district", "")
        problem = (None if 2 <= len(name) <= 100 else "Enter your full name.") or \
                  (None if EMAIL_RE.match(email) else "Enter a valid email address.") or \
                  (None if district in DISTRICTS else "Choose your district.") or \
                  password_problem(password, email, name) or \
                  (None if f.get("agree") else "Please accept the Terms and Privacy Policy to continue.")
        if problem:
            flash(problem, "error")
            return render_template("register.html")
        with db() as con:
            existing = con.execute("SELECT id, email_verified FROM users WHERE email=?", (email,)).fetchone()
            if existing:
                if REQUIRE_VERIFY and not existing["email_verified"]:
                    send_code(email, "verify", "Verify your CivicFix account", "Welcome back to CivicFix.")
                    return redirect(url_for("verify", email=email))
                flash("That email is already registered. Please sign in.", "error")
                return render_template("register.html")
            try:
                uid = insert(con, "INSERT INTO users(name,email,password_hash,role,district,created_at,email_verified) VALUES(?,?,?,'citizen',?,?,?)",
                             (name, email, generate_password_hash(password), district, now_iso(), 0 if REQUIRE_VERIFY else 1))
            except IntegrityError:
                con.rollback()
                flash("That email is already registered. Please sign in.", "error")
                return render_template("register.html")
        audit("register", email, actor={"id": uid, "name": name})
        if REQUIRE_VERIFY:
            send_code(email, "verify", "Verify your CivicFix account", "Thanks for joining CivicFix.")
            return redirect(url_for("verify", email=email))
        start_session({"id": uid})
        flash("Your CivicFix account is ready.", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/verify", methods=["GET", "POST"])
def verify():
    email = (request.values.get("email") or "").strip().lower()
    if request.method == "POST":
        if rate_blocked(f"verify:{client_ip()}", 20, 900):
            return fail_page(429, "Too many attempts. Please wait a few minutes.")
        rate_hit(f"verify:{client_ip()}")
        if check_otp(email, "verify", request.form.get("code")):
            with db() as con:
                con.execute("UPDATE users SET email_verified=1 WHERE email=?", (email,))
                user = con.execute("SELECT * FROM users WHERE email=? AND deleted_at IS NULL", (email,)).fetchone()
            if user:
                audit("email_verified", email, actor=user)
                start_session(user)
                flash("Email verified. Welcome to CivicFix.", "success")
                return redirect(url_for("dashboard"))
        flash("That code is wrong or has expired.", "error")
    return render_template("verify.html", email=email)


@app.route("/verify/resend", methods=["POST"])
def verify_resend():
    email = request.form.get("email", "").strip().lower()
    if not rate_blocked(f"otp:{email}", 3, 3600) and not rate_blocked(f"otp:ip:{client_ip()}", 10, 3600):
        rate_hit(f"otp:{email}"); rate_hit(f"otp:ip:{client_ip()}")
        with db() as con:
            u = con.execute("SELECT id FROM users WHERE email=? AND email_verified=0 AND deleted_at IS NULL", (email,)).fetchone()
        if u:
            send_code(email, "verify", "Your CivicFix verification code", "Here is a new code.")
    flash("If that account needs verifying, a new code is on its way.", "success")
    return redirect(url_for("verify", email=email))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email, password = request.form.get("email", "").strip().lower(), request.form.get("password", "")
        ip_key, em_key = f"loginfail:ip:{client_ip()}", f"loginfail:{email}"
        if rate_blocked(ip_key, 30, 900) or rate_blocked(em_key, 5, 900):
            audit("login_blocked", email)
            return fail_page(429, "Too many failed sign-in attempts. Please wait 15 minutes, or reset your password.")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE email=? AND deleted_at IS NULL", (email,)).fetchone()
        ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password) and user is not None
        if ok:
            if not user["email_verified"]:
                send_code(email, "verify", "Verify your CivicFix account", "Please verify your email to sign in.")
                flash("Please verify your email first. We sent you a code.", "warn")
                return redirect(url_for("verify", email=email))
            start_session(user)
            audit("login", email, actor=user)
            return redirect(safe_next(request.args.get("next")) or url_for("dashboard"))
        rate_hit(em_key); rate_hit(ip_key)
        audit("login_failed", email)
        flash("Email or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    if current_user():
        audit("logout", current_user()["email"])
    session.clear()
    return redirect(url_for("home"))


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not rate_blocked(f"forgot:{email}", 3, 3600) and not rate_blocked(f"forgot:ip:{client_ip()}", 8, 3600):
            rate_hit(f"forgot:{email}"); rate_hit(f"forgot:ip:{client_ip()}")
            with db() as con:
                u = con.execute("SELECT id FROM users WHERE email=? AND deleted_at IS NULL", (email,)).fetchone()
            if u:
                send_code(email, "reset", "Reset your CivicFix password", "We received a request to reset your password.")
                audit("password_reset_requested", email)
        flash("If that email has an account, we've sent a reset code.", "success")
        return redirect(url_for("reset", email=email))
    return render_template("forgot.html")


@app.route("/reset", methods=["GET", "POST"])
def reset():
    email = (request.values.get("email") or "").strip().lower()
    if request.method == "POST":
        if rate_blocked(f"reset:{client_ip()}", 20, 900):
            return fail_page(429, "Too many attempts. Please wait a few minutes.")
        rate_hit(f"reset:{client_ip()}")
        pw = request.form.get("password", "")
        problem = password_problem(pw, email)
        if problem:
            flash(problem, "error")
        elif check_otp(email, "reset", request.form.get("code")):
            with db() as con:
                con.execute("UPDATE users SET password_hash=?, must_change_password=0, email_verified=1 WHERE email=? AND deleted_at IS NULL",
                            (generate_password_hash(pw), email))
            audit("password_reset", email)
            flash("Password updated. You can sign in now.", "success")
            return redirect(url_for("login"))
        else:
            flash("That code is wrong or has expired.", "error")
    return render_template("reset.html", email=email)


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    user = current_user()
    if request.method == "POST":
        cur, new = request.form.get("current", ""), request.form.get("password", "")
        if rate_blocked(f"pw:{user['id']}", 8, 900):
            return fail_page(429, "Too many attempts. Please wait a few minutes.")
        rate_hit(f"pw:{user['id']}")
        problem = password_problem(new, user["email"], user["name"])
        if not check_password_hash(user["password_hash"], cur):
            flash("Your current password is incorrect.", "error")
        elif problem:
            flash(problem, "error")
        elif cur == new:
            flash("Choose a password different from the current one.", "error")
        else:
            with db() as con:
                con.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?", (generate_password_hash(new), user["id"]))
            audit("password_changed", user["email"])
            start_session(user)
            flash("Password changed.", "success")
            return redirect(url_for("account"))
    return render_template("account.html")


@app.route("/account/export")
@login_required
def account_export():
    user = current_user()
    with db() as con:
        cases = [dict(r) for r in con.execute("SELECT ticket,title,description,category,district,area,address,latitude,longitude,status,priority,created_at,resolved_at FROM complaints WHERE user_id=? ORDER BY id", (user["id"],))]
        notes = [dict(r) for r in con.execute("SELECT message,created_at FROM notifications WHERE user_id=? ORDER BY id", (user["id"],))]
    data = {"account": {"name": user["name"], "email": user["email"], "role": user["role"], "district": user["district"], "created_at": user["created_at"]},
            "reports": cases, "notifications": notes}
    audit("data_export", user["email"])
    return Response(json.dumps(data, indent=2, default=str), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=civicfix-my-data.json"})


@app.route("/account/delete", methods=["POST"])
@roles("citizen")
def account_delete():
    user = current_user()
    if not check_password_hash(user["password_hash"], request.form.get("password", "")):
        flash("Password incorrect. Your account was not deleted.", "error")
        return redirect(url_for("account"))
    with db() as con:
        con.execute("UPDATE users SET name='Deleted user', email=?, password_hash=?, deleted_at=? WHERE id=?",
                    (f"deleted-{user['id']}@civicfix.invalid", generate_password_hash(secrets.token_hex(16)), now_iso(), user["id"]))
        con.execute("DELETE FROM notifications WHERE user_id=?", (user["id"],))
        con.execute("UPDATE complaints SET address=NULL WHERE user_id=?", (user["id"],))
    audit("account_deleted", user["id"], actor=user)
    session.clear()
    flash("Your account was deleted. Past reports stay on record without your name.", "success")
    return redirect(url_for("home"))


# --------------------------------------------------------------------------- #
# Command center, map, APIs, media
# --------------------------------------------------------------------------- #
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", data=build_dashboard(current_user()))


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    return jsonify(build_dashboard(current_user()))


@app.route("/map")
@login_required
def live_map():
    return render_template("map.html")


@app.route("/api/markers")
@login_required
def api_markers():
    with db() as con:
        return jsonify(markers_for(con, current_user()))


@app.route("/api/notifications")
@login_required
def api_notifications():
    user = current_user()
    with db() as con:
        rows = con.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 8", (user["id"],)).fetchall()
        unread = con.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user["id"],)).fetchone()[0]
    return jsonify({"unread": unread, "items": [{
        "id": r["id"], "message": r["message"], "kind": r["kind"], "read": bool(r["is_read"]), "created_at": r["created_at"],
        "url": url_for("complaint_detail", complaint_id=r["complaint_id"]) if r["complaint_id"] else None} for r in rows]})


@app.route("/notifications")
@login_required
def notifications():
    with db() as con:
        rows = con.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 60", (current_user()["id"],)).fetchall()
    return render_template("notifications.html", rows=rows)


@app.route("/notifications/read", methods=["POST"])
@login_required
def notifications_read():
    with db() as con:
        con.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (current_user()["id"],))
    if request.headers.get("X-CSRF-Token"):
        return jsonify({"ok": True})
    return redirect(request.referrer or url_for("notifications"))


@app.route("/media/<name>", endpoint="media")
@login_required
def media_file(name):
    """Photos are private: only people who may view the case can see its images."""
    user = current_user()
    with db() as con:
        c = con.execute("SELECT * FROM complaints WHERE photo=? OR resolution_photo=?", (name, name)).fetchone()
    if not c or not can_view(user, c):
        abort(404)
    found = storage.load(name)
    if not found:
        abort(404)
    resp = Response(found[0], mimetype=found[1])
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


# --------------------------------------------------------------------------- #
# Complaints
# --------------------------------------------------------------------------- #
@app.route("/complaints")
@login_required
def complaints():
    user = current_user()
    where, params = scope(user)
    status = request.args.get("status", "")
    with db() as con:
        counts = {r["status"]: r["n"] for r in con.execute(f"SELECT status, COUNT(*) AS n FROM complaints WHERE {where} GROUP BY status", params)}
        sql, p = f"SELECT * FROM complaints WHERE {where}", params
        if status in STATUSES:
            sql += " AND status=?"
            p += (status,)
        rows = con.execute(sql + " ORDER BY created_at DESC LIMIT 500", p).fetchall()
    return render_template("complaints.html", rows=rows, counts=counts, active_status=status, total=sum(counts.values()))


@app.route("/complaints/new", methods=["GET", "POST"])
@roles("citizen")
def new_complaint():
    user = current_user()
    if request.method == "POST":
        f = request.form
        if rate_blocked(f"report:{user['id']}", 10, 86400):
            return fail_page(429, "You've reached today's limit of 10 reports. Please try again tomorrow.")
        title, description = f.get("title", "").strip()[:140], f.get("description", "").strip()[:2000]
        category, district = f.get("category", ""), f.get("district", "")
        area, address = f.get("area", "").strip()[:100], f.get("address", "").strip()[:200]
        if not title or not description or category not in DEPARTMENTS or district not in DISTRICTS or not area:
            flash("Please complete all required fields (including the category).", "error")
            return render_template("complaint_new.html")
        try:
            photo_name = storage.save_upload(request.files.get("photo"))
        except ValueError as e:
            flash(str(e), "error")
            return render_template("complaint_new.html")
        except Exception:
            log.exception("photo storage failed")
            flash("We couldn't save the photo right now. Try again, or submit without a photo.", "error")
            return render_template("complaint_new.html")
        lat, lng = clean_coord(f.get("latitude"), 6, 38), clean_coord(f.get("longitude"), 67, 98)
        if lat is None or lng is None:
            lat = lng = None
        now = now_iso()
        with db() as con:
            cid = insert(con, """INSERT INTO complaints(ticket,user_id,title,description,category,district,area,address,latitude,longitude,photo,created_at,updated_at)
                                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (ticket_id(), user["id"], title, description, category, district, area, address, lat, lng, photo_name, now, now))
            add_update(con, cid, user["id"], "Submitted", "Report submitted by citizen. Waiting for district approval.", now)
            notify(con, ids_of(con, "SELECT id FROM users WHERE role='district_admin' AND district=? AND deleted_at IS NULL", (district,)),
                   cid, f"New {AGENCIES[category]['short']} report in {area}: {title[:60]}", "action")
        rate_hit(f"report:{user['id']}")
        flash("Report submitted. Your district admin has been notified.", "success")
        return redirect(url_for("complaint_detail", complaint_id=cid))
    return render_template("complaint_new.html")


def clean_coord(value, lo, hi):
    try:
        v = float(value)
        return v if lo <= v <= hi else None
    except (TypeError, ValueError):
        return None


def step_times(history):
    out = {}
    for h in reversed(history):
        out.setdefault(h["status"], {"at": h["created_at"], "by": h["actor_name"]})
    return out


@app.route("/complaints/<int:complaint_id>")
@login_required
def complaint_detail(complaint_id):
    user = current_user()
    with db() as con:
        item = con.execute("SELECT * FROM complaints WHERE id=?", (complaint_id,)).fetchone()
        if not item:
            abort(404)
        if not can_view(user, item):
            abort(403)
        owner = con.execute("SELECT name FROM users WHERE id=?", (item["user_id"],)).fetchone()
        assigned = con.execute("SELECT name FROM users WHERE id=?", (item["assigned_to"],)).fetchone() if item["assigned_to"] else None
        approver = con.execute("SELECT name FROM users WHERE id=?", (item["approved_by"],)).fetchone() if item["approved_by"] else None
        history = con.execute("SELECT updates.*, users.name AS actor_name FROM updates LEFT JOIN users ON users.id=updates.actor_id "
                              "WHERE complaint_id=? ORDER BY updates.created_at DESC, updates.id DESC", (complaint_id,)).fetchall()
        staff = []
        if user["role"] in ("district_admin", "superadmin"):
            staff = con.execute("SELECT id,name,department FROM users WHERE role='staff' AND district=? AND deleted_at IS NULL ORDER BY name", (item["district"],)).fetchall()
    can_reopen = (user["id"] == item["user_id"] and item["status"] == "Resolved" and item["resolved_at"]
                  and (datetime.now() - parse_ts(item["resolved_at"])).days < REOPEN_DAYS)
    return render_template("complaint_detail.html", item=item, history=history, owner=owner, assigned=assigned, approver=approver,
                           staff=staff, steps=step_times(history), is_admin=user["role"] in ("district_admin", "superadmin"),
                           can_reopen=bool(can_reopen), is_owner=user["id"] == item["user_id"])


def load_case(con, cid):
    user = current_user()
    item = con.execute("SELECT * FROM complaints WHERE id=?", (cid,)).fetchone()
    if not item:
        abort(404)
    if not can_view(user, item):
        abort(403)
    return user, item


def back(cid):
    return redirect(url_for("complaint_detail", complaint_id=cid))


def do_forward(con, user, item, dept, officer_id, note):
    officer = None
    if officer_id:
        officer = con.execute("SELECT id FROM users WHERE id=? AND role='staff' AND district=? AND department=? AND deleted_at IS NULL",
                              (officer_id, item["district"], dept)).fetchone()
    now = now_iso()
    con.execute("UPDATE complaints SET status='Forwarded', forwarded_to=?, assigned_to=?, updated_at=? WHERE id=?",
                (dept, officer["id"] if officer else None, now, item["id"]))
    ag = AGENCIES[dept]
    add_update(con, item["id"], user["id"], "Forwarded", f"Forwarded to {ag['name']}." + (f" {note}" if note else ""), now)
    targets = [officer["id"]] if officer else ids_of(con, "SELECT id FROM users WHERE role='staff' AND district=? AND department=? AND deleted_at IS NULL", (item["district"], dept))
    notify(con, targets, item["id"], f"{ag['short']}: new case {item['ticket']}: {item['title'][:60]}", "action", now)
    notify(con, [item["user_id"]], item["id"], f"Your report {item['ticket']} was sent to {ag['name']}.", "success", now)
    audit("case_forwarded", item["ticket"], dept)
    return len(targets)


@app.route("/complaints/<int:cid>/approve", methods=["POST"])
@roles("district_admin", "superadmin")
def approve_complaint(cid):
    with db() as con:
        user, item = load_case(con, cid)
        if item["status"] != "Submitted":
            flash("This report has already been reviewed.", "error")
            return back(cid)
        priority = request.form.get("priority", item["priority"])
        priority = priority if priority in PRIORITIES else item["priority"]
        forward_to, note = request.form.get("forward_to", ""), request.form.get("note", "").strip()[:500]
        now = now_iso()
        con.execute("UPDATE complaints SET status='Approved', priority=?, approved_by=?, approved_at=?, updated_at=? WHERE id=?", (priority, user["id"], now, now, cid))
        add_update(con, cid, user["id"], "Approved", note or "Report verified and approved by the district admin.", now)
        notify(con, [item["user_id"]], cid, f"Your report {item['ticket']} was approved.", "success", now)
        audit("case_approved", item["ticket"], priority)
        if forward_to in DEPARTMENTS:
            n = do_forward(con, user, item, forward_to, request.form.get("assigned_to"), "")
            flash(f"Approved and forwarded to {AGENCIES[forward_to]['name']}." + ("" if n else " No officer is registered for that department in this district yet; it is queued for them."), "success" if n else "warn")
        else:
            flash("Report approved. Forward it to a department next.", "success")
    return back(cid)


@app.route("/complaints/<int:cid>/reject", methods=["POST"])
@roles("district_admin", "superadmin")
def reject_complaint(cid):
    reason = request.form.get("note", "").strip()[:500]
    with db() as con:
        user, item = load_case(con, cid)
        if item["status"] != "Submitted":
            flash("Only new reports can be rejected.", "error")
            return back(cid)
        if not reason:
            flash("Please give the citizen a reason for rejecting.", "error")
            return back(cid)
        now = now_iso()
        con.execute("UPDATE complaints SET status='Rejected', resolution_note=?, updated_at=? WHERE id=?", (reason, now, cid))
        add_update(con, cid, user["id"], "Rejected", reason, now)
        notify(con, [item["user_id"]], cid, f"Your report {item['ticket']} was rejected: {reason[:80]}", "warn", now)
        audit("case_rejected", item["ticket"], reason)
    flash("Report rejected and the citizen was notified.", "success")
    return back(cid)


@app.route("/complaints/<int:cid>/forward", methods=["POST"])
@roles("district_admin", "superadmin")
def forward_complaint(cid):
    dept = request.form.get("forward_to", "")
    with db() as con:
        user, item = load_case(con, cid)
        if item["status"] not in ("Approved", "Forwarded"):
            flash("Approve the report before forwarding it.", "error")
            return back(cid)
        if dept not in DEPARTMENTS:
            flash("Choose a department.", "error")
            return back(cid)
        n = do_forward(con, user, item, dept, request.form.get("assigned_to"), request.form.get("note", "").strip()[:500])
    flash(f"Forwarded to {AGENCIES[dept]['name']}." + ("" if n else " No officer is registered there yet; it is queued."), "success" if n else "warn")
    return back(cid)


@app.route("/complaints/<int:cid>/progress", methods=["POST"])
@roles("staff", "district_admin", "superadmin")
def progress_complaint(cid):
    note = request.form.get("note", "").strip()[:500] or "Team is on site and working on it."
    with db() as con:
        user, item = load_case(con, cid)
        if item["status"] not in ("Forwarded", "In Progress"):
            flash("This case isn't in the field queue.", "error")
            return back(cid)
        now = now_iso()
        assigned = item["assigned_to"] or (user["id"] if user["role"] == "staff" else None)
        con.execute("UPDATE complaints SET status='In Progress', assigned_to=?, updated_at=? WHERE id=?", (assigned, now, cid))
        add_update(con, cid, user["id"], "In Progress", note, now)
        notify(con, [item["user_id"]], cid, f"Work has started on {item['ticket']}.", "info", now)
        audit("case_progress", item["ticket"], note)
    flash("Marked as in progress. The citizen has been told.", "success")
    return back(cid)


@app.route("/complaints/<int:cid>/resolve", methods=["POST"])
@roles("staff", "district_admin", "superadmin")
def resolve_complaint(cid):
    note = request.form.get("note", "").strip()[:1000]
    with db() as con:
        user, item = load_case(con, cid)
        if item["status"] not in ("Forwarded", "In Progress"):
            flash("Only cases in the field queue can be resolved.", "error")
            return back(cid)
        if not note:
            flash("Describe what was done to fix the issue.", "error")
            return back(cid)
        try:
            proof = storage.save_upload(request.files.get("proof"))
        except ValueError as e:
            flash(str(e), "error")
            return back(cid)
        except Exception:
            log.exception("proof upload failed")
            flash("Couldn't save the proof photo. Try again.", "error")
            return back(cid)
        now = now_iso()
        con.execute("UPDATE complaints SET status='Resolved', resolution_note=?, resolution_photo=?, resolved_at=?, updated_at=?, "
                    "assigned_to=COALESCE(assigned_to, ?), confirmed_at=NULL WHERE id=?",
                    (note, proof, now, now, user["id"] if user["role"] == "staff" else None, cid))
        add_update(con, cid, user["id"], "Resolved", note, now)
        notify(con, [item["user_id"]], cid, f"Fixed! {item['ticket']} was resolved. Please confirm it looks good.", "success", now)
        short = AGENCIES.get(item["forwarded_to"] or "Other", AGENCIES["Other"])["short"]
        notify(con, ids_of(con, "SELECT id FROM users WHERE role='district_admin' AND district=? AND deleted_at IS NULL", (item["district"],)), cid, f"{item['ticket']} resolved by {short}.", "success", now)
        audit("case_resolved", item["ticket"])
    flash("Case resolved. Nice work.", "success")
    return back(cid)


@app.route("/complaints/<int:cid>/confirm", methods=["POST"])
@roles("citizen")
def confirm_fixed(cid):
    with db() as con:
        user, item = load_case(con, cid)
        if item["status"] != "Resolved" or item["confirmed_at"]:
            return back(cid)
        now = now_iso()
        con.execute("UPDATE complaints SET confirmed_at=?, updated_at=? WHERE id=?", (now, now, cid))
        add_update(con, cid, user["id"], "Resolved", "Citizen confirmed the issue is fixed.", now)
        audit("case_confirmed", item["ticket"])
    flash("Thanks for confirming. Glad it's sorted.", "success")
    return back(cid)


@app.route("/complaints/<int:cid>/reopen", methods=["POST"])
@roles("citizen")
def reopen_complaint(cid):
    reason = request.form.get("note", "").strip()[:500]
    with db() as con:
        user, item = load_case(con, cid)
        recent = item["resolved_at"] and (datetime.now() - parse_ts(item["resolved_at"])).days < REOPEN_DAYS
        if item["status"] != "Resolved" or not recent:
            flash("This case can't be reopened any more. Please file a new report.", "error")
            return back(cid)
        if not reason:
            flash("Tell us what's still wrong so the team can act on it.", "error")
            return back(cid)
        now = now_iso()
        con.execute("UPDATE complaints SET status='Forwarded', resolved_at=NULL, confirmed_at=NULL, updated_at=? WHERE id=?", (now, cid))
        add_update(con, cid, user["id"], "Forwarded", f"Reopened by citizen: {reason}", now)
        targets = ids_of(con, "SELECT id FROM users WHERE role='staff' AND district=? AND department=? AND deleted_at IS NULL", (item["district"], item["forwarded_to"] or item["category"]))
        targets += [item["assigned_to"]] + ids_of(con, "SELECT id FROM users WHERE role='district_admin' AND district=? AND deleted_at IS NULL", (item["district"],))
        notify(con, targets, cid, f"{item['ticket']} was reopened by the citizen: {reason[:70]}", "warn", now)
        audit("case_reopened", item["ticket"], reason)
    flash("Case reopened and sent back to the department.", "success")
    return back(cid)


# --------------------------------------------------------------------------- #
# Admin: departments, users, audit log
# --------------------------------------------------------------------------- #
@app.route("/admin/departments")
@roles("district_admin", "superadmin")
def admin_departments():
    with db() as con:
        stats = dept_stats(con, current_user())
    return render_template("departments.html", stats=stats)


@app.route("/admin/users", methods=["GET", "POST"])
@roles("district_admin", "superadmin")
def admin_users():
    user = current_user()
    if request.method == "POST":
        f = request.form
        name, email, password = f.get("name", "").strip()[:100], f.get("email", "").strip().lower(), f.get("password", "")
        role, district, department = f.get("role", "staff"), f.get("district", "") or None, f.get("department", "") or None
        if user["role"] == "district_admin":
            role, district = "staff", user["district"]
        problems = []
        if not name or not EMAIL_RE.match(email):
            problems.append("Enter a name and a valid email.")
        pp = password_problem(password, email, name)
        if pp:
            problems.append(pp)
        if role not in ("staff", "district_admin", "superadmin"):
            problems.append("Invalid role.")
        if role in ("staff", "district_admin") and district not in DISTRICTS:
            problems.append("Choose a district.")
        if role == "staff" and department not in DEPARTMENTS:
            problems.append("Choose a department for the officer.")
        if problems:
            flash(" ".join(problems), "error")
        else:
            try:
                with db() as con:
                    insert(con, "INSERT INTO users(name,email,password_hash,role,district,department,created_at,email_verified,must_change_password) VALUES(?,?,?,?,?,?,?,1,1)",
                           (name, email, generate_password_hash(password), role, district if role != "superadmin" else None,
                            department if role == "staff" else None, now_iso()))
                audit("user_created", email, f"{role} {district or ''} {department or ''}")
                flash(f"{ROLE_LABELS[role]} account created for {name}. They must set a new password at first sign-in.", "success")
            except IntegrityError:
                db_rollback()
                flash("That email is already registered.", "error")
        return redirect(url_for("admin_users"))
    with db() as con:
        if user["role"] == "superadmin":
            rows = con.execute("SELECT * FROM users WHERE deleted_at IS NULL ORDER BY CASE role WHEN 'superadmin' THEN 0 WHEN 'district_admin' THEN 1 WHEN 'staff' THEN 2 ELSE 3 END, name").fetchall()
        else:
            rows = con.execute("SELECT * FROM users WHERE district=? AND role IN ('staff','district_admin') AND deleted_at IS NULL ORDER BY role, name", (user["district"],)).fetchall()
    return render_template("users.html", rows=rows)


def db_rollback():
    with db() as con:
        con.rollback()


@app.route("/admin/audit")
@roles("superadmin")
def admin_audit():
    with db() as con:
        rows = con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 300").fetchall()
    return render_template("audit.html", rows=rows)


# --------------------------------------------------------------------------- #
# PWA + errors
# --------------------------------------------------------------------------- #
@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "CivicFix India", "short_name": "CivicFix", "start_url": "/dashboard", "display": "standalone",
                    "background_color": "#050b1e", "theme_color": "#0a1330",
                    "icons": [{"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml"}]})


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(BASE / "static", "service-worker.js", mimetype="application/javascript")


@app.errorhandler(400)
def e400(_):
    return fail_page(400, "That request expired. Go back, refresh the page and try again.")


@app.errorhandler(403)
def e403(_):
    return fail_page(403, "You don't have permission to view this.")


@app.errorhandler(404)
def e404(_):
    return fail_page(404, "The page you're looking for doesn't exist.")


@app.errorhandler(413)
def e413(_):
    return fail_page(413, "That photo is too large. Please upload an image under 8 MB.")


@app.errorhandler(500)
def e500(_):
    return fail_page(500, "Something went wrong on our side. Please try again in a moment.")


# --------------------------------------------------------------------------- #
# Startup + CLI
# --------------------------------------------------------------------------- #
def bootstrap():
    init_schema()
    with db() as con:
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        if DEMO_MODE:
            from demo import seed_demo
            seed_demo(con)
            log.warning("Demo accounts created (password CivicFix@2026). Never enable CIVICFIX_DEMO in production.")
        elif os.environ.get("CIVICFIX_ADMIN_EMAIL") and os.environ.get("CIVICFIX_ADMIN_PASSWORD"):
            insert(con, "INSERT INTO users(name,email,password_hash,role,created_at,email_verified,must_change_password) VALUES(?,?,?,'superadmin',?,1,1)",
                   (os.environ.get("CIVICFIX_ADMIN_NAME", "Super Admin"), os.environ["CIVICFIX_ADMIN_EMAIL"].lower(),
                    generate_password_hash(os.environ["CIVICFIX_ADMIN_PASSWORD"]), now_iso()))
            log.warning("First super admin created from environment variables. Remove CIVICFIX_ADMIN_PASSWORD now.")
        else:
            log.warning("No users exist. Set CIVICFIX_ADMIN_EMAIL + CIVICFIX_ADMIN_PASSWORD or run: flask --app app create-admin")


@app.cli.command("create-admin")
@click.option("--name", prompt=True)
@click.option("--email", prompt=True)
@click.password_option()
def create_admin(name, email, password):
    """Create a super admin account."""
    problem = password_problem(password, email, name)
    if problem:
        raise click.ClickException(problem)
    with db() as con:
        insert(con, "INSERT INTO users(name,email,password_hash,role,created_at,email_verified,must_change_password) VALUES(?,?,?,'superadmin',?,1,0)",
               (name, email.lower(), generate_password_hash(password), now_iso()))
    click.echo("Super admin created.")


bootstrap()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)
