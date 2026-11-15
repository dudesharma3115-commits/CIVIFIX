"""States, districts and per-state agency names. Stored in the database (editable by admins); seeded from data/india.json."""
import time

from constants import AGENCIES, INDIA, STATE_CENTER, STATES
from db import db, insert

_cache = {"t": 0, "geo": None}


def seed_geo(con):
    if con.execute("SELECT COUNT(*) FROM districts").fetchone()[0] == 0:
        for s in INDIA["states"]:
            for name in s["districts"]:
                con.execute("INSERT INTO districts(state,name,lat,lng) VALUES(?,?,NULL,NULL)", (s["code"], name))
    if con.execute("SELECT COUNT(*) FROM agency_names").fetchone()[0] == 0:
        for st, cats in INDIA["agency_names"].items():
            for cat, v in cats.items():
                con.execute("INSERT INTO agency_names(state,category,name,short) VALUES(?,?,?,?)", (st, cat, v["name"], v["short"]))


def invalidate():
    _cache["t"] = 0


def get_geo():
    """{states, districts:{code:[{n,lat,lng}]}, agencies:{code:{category:{name,short}}}}; cached for 60 seconds."""
    if _cache["geo"] is None or time.time() - _cache["t"] > 60:
        with db() as con:
            drows = con.execute("SELECT state, name, lat, lng FROM districts ORDER BY state, name").fetchall()
            arows = con.execute("SELECT state, category, name, short FROM agency_names").fetchall()
        districts, agencies = {}, {}
        for r in drows:
            districts.setdefault(r["state"], []).append({"n": r["name"], "lat": r["lat"], "lng": r["lng"]})
        for r in arows:
            agencies.setdefault(r["state"], {})[r["category"]] = {"name": r["name"], "short": r["short"]}
        _cache["geo"], _cache["t"] = {"states": STATES, "districts": districts, "agencies": agencies}, time.time()
    return _cache["geo"]


def district_names(state):
    return [d["n"] for d in get_geo()["districts"].get(state, [])]


def valid_pair(state, district):
    return district in district_names(state)


def center(state, district=None):
    """(lat, lng, zoom) for a district if known, else its state."""
    if state in STATE_CENTER:
        if district:
            for d in get_geo()["districts"].get(state, []):
                if d["n"] == district and d["lat"] is not None:
                    return (d["lat"], d["lng"], 12)
        return STATE_CENTER[state]
    return (22.9, 79.5, 5)


def agencies_for(state):
    """Generic agencies with this state's official names applied."""
    over = get_geo()["agencies"].get(state, {}) if state else {}
    return {k: {**v, **over.get(k, {})} for k, v in AGENCIES.items()}


def agency(state, category):
    return agencies_for(state).get(category, agencies_for(state)["Other"])
