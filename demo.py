"""Demo accounts + sample reports (development / pilot only)."""
import random
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from constants import AGENCIES
from db import insert
from services import add_update, notify, ticket_id


def seed_demo(con):
    pw = generate_password_hash("CivicFix@2026")
    now = datetime.now()

    def mk_user(name, email, role, district=None, department=None):
        return insert(con, "INSERT INTO users(name,email,password_hash,role,district,department,created_at,email_verified,must_change_password) VALUES(?,?,?,?,?,?,?,1,0)",
                      (name, email, pw, role, district, department, now.isoformat(timespec="seconds")))

    mk_user("CivicFix Super Admin", "admin@civicfix.in", "superadmin")
    adm = {"Chennai": mk_user("Chennai District Admin", "chennai.admin@civicfix.in", "district_admin", "Chennai"),
           "Coimbatore": mk_user("Coimbatore District Admin", "cbe.admin@civicfix.in", "district_admin", "Coimbatore")}
    staff = {
        ("Chennai", "Roads & Highways"): mk_user("Chennai Roads Team", "roads.staff@civicfix.in", "staff", "Chennai", "Roads & Highways"),
        ("Chennai", "Electricity"): mk_user("TNEB Chennai Officer", "tneb.staff@civicfix.in", "staff", "Chennai", "Electricity"),
        ("Chennai", "Water Supply"): mk_user("Metro Water Chennai", "water.staff@civicfix.in", "staff", "Chennai", "Water Supply"),
        ("Chennai", "Sanitation"): mk_user("Chennai Sanitation Team", "sanitation.staff@civicfix.in", "staff", "Chennai", "Sanitation"),
        ("Coimbatore", "Electricity"): mk_user("TNEB Coimbatore Officer", "cbe.tneb@civicfix.in", "staff", "Coimbatore", "Electricity"),
    }
    cit = {"Chennai": mk_user("Demo Citizen", "citizen@civicfix.in", "citizen", "Chennai"),
           "Coimbatore": mk_user("Arjun Kumar", "arjun@civicfix.in", "citizen", "Coimbatore")}

    # (title, description, category, district, area, lat, lng, final status, priority, days ago)
    S = [
        ("Live wire hanging near school gate", "A snapped service line is hanging at head height next to the school entrance. Children pass here every morning.", "Electricity", "Chennai", "Adyar", 13.0067, 80.2570, "Submitted", "Critical", 0),
        ("Transformer sparking after rain", "The pole transformer sparks every time it drizzles. Smell of burning insulation.", "Electricity", "Chennai", "Velachery", 12.9815, 80.2180, "Forwarded", "Critical", 1),
        ("Street lights dark for a week", "Entire stretch of 3rd Main Road has no street lights. Chain snatching reported.", "Electricity", "Chennai", "Anna Nagar", 13.0850, 80.2101, "In Progress", "High", 2),
        ("Pothole outside metro station", "Deep pothole swallowing two-wheelers near the pillar 23 entrance.", "Roads & Highways", "Chennai", "Guindy", 13.0067, 80.2206, "Forwarded", "High", 1),
        ("Broken footpath slabs", "Footpath slabs are cracked and tilting, dangerous for elderly walkers.", "Roads & Highways", "Chennai", "T. Nagar", 13.0418, 80.2341, "Approved", "Medium", 1),
        ("Water main leaking on the street", "Potable water gushing out for two days, road is flooded.", "Water Supply", "Chennai", "Mylapore", 13.0368, 80.2676, "In Progress", "High", 3),
        ("No water supply since Monday", "Our lane has had zero supply for 3 days. Lorry water is costly.", "Water Supply", "Chennai", "Perambur", 13.1143, 80.2329, "Resolved", "High", 5),
        ("Garbage overflowing near market", "Bins have not been cleared for 4 days. Stray dogs and a heavy smell.", "Sanitation", "Chennai", "Kodambakkam", 13.0521, 80.2255, "Resolved", "Medium", 4),
        ("Blocked storm drain", "Drain choked with plastic, water stagnates after every shower.", "Sanitation", "Chennai", "Besant Nagar", 13.0003, 80.2667, "Submitted", "Medium", 0),
        ("Stagnant water breeding mosquitoes", "Open plot has stagnant water. Three dengue cases in our lane.", "Public Health", "Chennai", "Royapuram", 13.1130, 80.2950, "Forwarded", "High", 2),
        ("Broken swings in the park", "Two swings are broken and sharp edges are exposed.", "Parks & Public Spaces", "Chennai", "Porur", 13.0382, 80.1565, "Rejected", "Low", 3),
        ("Pothole cluster on arterial road", "Series of potholes causing jams during peak hours.", "Roads & Highways", "Chennai", "Egmore", 13.0732, 80.2609, "Resolved", "Medium", 6),
        ("Street light flickering", "Light flickers all night, wrecking sleep for the whole lane.", "Electricity", "Coimbatore", "RS Puram", 11.0089, 76.9500, "Resolved", "Low", 4),
        ("Exposed junction box", "Open junction box with wires at ground level near the bus stop.", "Electricity", "Coimbatore", "Gandhipuram", 11.0183, 76.9725, "Forwarded", "Critical", 1),
        ("Garbage dumped on the roadside", "People are dumping waste at the corner, nobody collects it.", "Sanitation", "Coimbatore", "Peelamedu", 11.0250, 77.0020, "Submitted", "Medium", 0),
    ]
    rnd = random.Random(11)
    for title, desc, cat, dist, area, lat, lng, final, prio, days in S:
        created = now - timedelta(days=days, hours=rnd.randint(1, 9), minutes=rnd.randint(0, 59))

        def t(h, created=created):
            return (created + timedelta(hours=h)).isoformat(timespec="seconds")

        officer = staff.get((dist, cat))
        admin = adm[dist]
        cid = insert(con,
            """INSERT INTO complaints(ticket,user_id,title,description,category,district,area,latitude,longitude,
               status,priority,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ticket_id(), cit[dist], title, desc, cat, dist, area, lat, lng, "Submitted", prio, t(0), t(0)))
        add_update(con, cid, cit[dist], "Submitted", "Report submitted by citizen. Waiting for district approval.", t(0))
        if final == "Rejected":
            why = "Duplicate of an existing report already being handled."
            con.execute("UPDATE complaints SET status='Rejected', resolution_note=?, updated_at=? WHERE id=?", (why, t(2), cid))
            add_update(con, cid, admin, "Rejected", why, t(2))
            continue
        if final in ("Approved", "Forwarded", "In Progress", "Resolved"):
            con.execute("UPDATE complaints SET status='Approved', approved_by=?, approved_at=?, updated_at=? WHERE id=?", (admin, t(1), t(1), cid))
            add_update(con, cid, admin, "Approved", "Report verified and approved by the district admin.", t(1))
        if final in ("Forwarded", "In Progress", "Resolved"):
            con.execute("UPDATE complaints SET status='Forwarded', forwarded_to=?, assigned_to=?, updated_at=? WHERE id=?",
                        (cat, officer, t(1.5), cid))
            add_update(con, cid, admin, "Forwarded", f"Forwarded to {AGENCIES[cat]['name']}.", t(1.5))
            if officer:
                notify(con, [officer], cid, f"{AGENCIES[cat]['short']}: new case — {title[:60]}", "action", t(1.5))
        if final in ("In Progress", "Resolved"):
            con.execute("UPDATE complaints SET status='In Progress', updated_at=? WHERE id=?", (t(4), cid))
            add_update(con, cid, officer or admin, "In Progress", "Team is on site and working on it.", t(4))
        if final == "Resolved":
            hrs = rnd.choice([9, 14, 22, 30, 41, 55])
            done = "Issue fixed and site inspected. Closing the case."
            con.execute("UPDATE complaints SET status='Resolved', resolved_at=?, resolution_note=?, updated_at=? WHERE id=?",
                        (t(hrs), done, t(hrs), cid))
            add_update(con, cid, officer or admin, "Resolved", done, t(hrs))
    notify(con, [adm["Chennai"]], None, "2 new reports are waiting for your approval.", "action")
    notify(con, [cit["Chennai"]], None, "Welcome to CivicFix. Report an issue with a photo to get started.", "info")
