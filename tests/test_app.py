"""Run:  python -m unittest discover -s tests -v   (uses a temporary SQLite database)"""
import io
import os
import re
import sys
import tempfile
import unittest

TMP = tempfile.mkdtemp()
os.environ.update(CIVICFIX_DB=os.path.join(TMP, "t.db"), CIVICFIX_UPLOADS=os.path.join(TMP, "up"),
                  CIVICFIX_DEMO="1", CIVICFIX_REQUIRE_VERIFY="1", CIVICFIX_SECRET="x" * 40)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app as A  # noqa: E402
import mailer  # noqa: E402
from PIL import Image  # noqa: E402

SENT = []
mailer.send_mail = lambda to, subject, body: SENT.append((to, subject, body)) or True
PW = "CivicFix@2026"


def q(sql, p=()):
    with A.db() as con:
        return [tuple(r) for r in con.execute(sql, p).fetchall()]


def csrf_from(html):
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def meta_csrf(cl, path="/dashboard"):
    return re.search(r'name="csrf" content="([^"]+)"', cl.get(path).get_data(as_text=True)).group(1)


def login(email, pw=PW):
    cl = A.app.test_client()
    t = csrf_from(cl.get("/login").get_data(as_text=True))
    r = cl.post("/login", data={"email": email, "password": pw, "_csrf": t})
    return cl, r


def jpeg_with_exif():
    im = Image.new("RGB", (2400, 1800), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "TestCamera"                     # Make
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    buf.seek(0)
    return buf


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cit = login("citizen@civicfix.in")[0]
        cls.adm = login("chennai.admin@civicfix.in")[0]
        cls.tneb = login("tneb.staff@civicfix.in")[0]
        cls.roads = login("roads.staff@civicfix.in")[0]
        cls.sup = login("admin@civicfix.in")[0]
        cls.cbe = login("cbe.admin@civicfix.in")[0]
        cls.tnstate = login("tn.state@civicfix.in")[0]
        cls.upstate = login("up.state@civicfix.in")[0]
        cls.upadm = login("lucknow.admin@civicfix.in")[0]
        cls.upcit = login("aman@civicfix.in")[0]
        cls.upstaff = login("uppcl.staff@civicfix.in")[0]

    def test_01_public_and_headers(self):
        c = A.app.test_client()
        for p in ["/", "/login", "/register", "/privacy", "/terms", "/track", "/forgot", "/healthz"]:
            self.assertEqual(c.get(p).status_code, 200, p)
        r = c.get("/login")
        self.assertIn("nonce-", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertNotIn("<script>window", r.get_data(as_text=True))   # all inline scripts carry a nonce
        self.assertEqual(c.get("/dashboard").status_code, 302)
        self.assertEqual(c.get("/nope").status_code, 404)

    def test_02_csrf(self):
        self.assertEqual(A.app.test_client().post("/login", data={"email": "a", "password": "b"}).status_code, 400)

    def test_03_all_role_pages(self):
        for cl in (self.cit, self.adm, self.tneb, self.sup, self.cbe, self.tnstate, self.upstate, self.upadm, self.upcit, self.upstaff):
            for p in ["/dashboard", "/api/dashboard", "/map", "/api/markers", "/complaints", "/api/notifications", "/notifications", "/account", "/account/export"]:
                self.assertEqual(cl.get(p).status_code, 200, p)
        for cl in (self.adm, self.sup, self.tnstate, self.upstate, self.upadm):
            for p in ["/admin/departments", "/admin/users"]:
                self.assertEqual(cl.get(p).status_code, 200, p)
        self.assertEqual(self.sup.get("/admin/audit").status_code, 200)
        for cl in (self.cit, self.adm, self.tneb):
            self.assertEqual(cl.get("/admin/audit").status_code, 403)
        self.assertEqual(self.cit.get("/admin/users").status_code, 403)

    def test_04_dashboard_numbers(self):
        d = self.adm.get("/api/dashboard").get_json()
        self.assertEqual(d["total"], 12)
        self.assertEqual(d["by_status"]["Resolved"], 3)
        self.assertIsNotNone(d["avg_hours"])
        self.assertEqual(len(d["departments"]), 7)
        self.assertEqual(self.sup.get("/api/dashboard").get_json()["total"], 18)

    def test_05_scoping(self):
        url = self.adm.get("/api/dashboard").get_json()["queue"][0]["url"]
        self.assertEqual(self.cbe.get(url).status_code, 403)        # other district
        self.assertEqual(self.cit.get(url).status_code, 200)        # same citizen owns Chennai demo cases
        self.assertEqual(self.sup.get(url).status_code, 200)

    def test_06_full_workflow_and_photo_privacy(self):
        t = meta_csrf(self.cit, "/complaints/new")
        r = self.cit.post("/complaints/new", content_type="multipart/form-data", data={
            "_csrf": t, "category": "Electricity", "title": "Pole sparking", "description": "Sparks at night",
            "state": "TN", "district": "Chennai", "area": "Adyar", "latitude": "13.0067", "longitude": "80.2570",
            "photo": (jpeg_with_exif(), "x.jpg")})
        self.assertEqual(r.status_code, 302)
        loc = r.headers["Location"]
        cid = int(loc.rsplit("/", 1)[1])
        photo = q("SELECT photo FROM complaints WHERE id=?", (cid,))[0][0]
        self.assertRegex(photo, r"^[a-f0-9]{24}\.jpg$")
        path = os.path.join(TMP, "up", photo)
        im = Image.open(path)
        self.assertLessEqual(max(im.size), 1600)                    # resized
        self.assertNotIn(0x010F, im.getexif())                      # metadata stripped
        # photo privacy
        self.assertEqual(self.cit.get(f"/media/{photo}").status_code, 200)
        self.assertEqual(self.adm.get(f"/media/{photo}").status_code, 200)
        self.assertEqual(self.cbe.get(f"/media/{photo}").status_code, 404)
        self.assertEqual(self.tneb.get(f"/media/{photo}").status_code, 404)      # not forwarded yet
        self.assertEqual(self.tneb.get(loc).status_code, 403)
        self.assertEqual(A.app.test_client().get(f"/media/{photo}").status_code, 302)
        # citizen cannot approve
        self.assertEqual(self.cit.post(f"/complaints/{cid}/approve", data={"_csrf": t}).status_code, 403)
        ta = meta_csrf(self.adm, loc)
        self.assertEqual(self.adm.post(f"/complaints/{cid}/approve", data={"_csrf": ta, "priority": "Critical", "forward_to": "Electricity"}).status_code, 302)
        self.assertEqual(self.tneb.get(loc).status_code, 200)
        self.assertEqual(self.tneb.get(f"/media/{photo}").status_code, 200)
        self.assertEqual(self.roads.get(loc).status_code, 403)                  # other department
        tt = meta_csrf(self.tneb, loc)
        self.assertEqual(self.tneb.post(f"/complaints/{cid}/progress", data={"_csrf": tt}).status_code, 302)
        r = self.tneb.post(f"/complaints/{cid}/resolve", content_type="multipart/form-data",
                           data={"_csrf": tt, "note": "Fuse replaced", "proof": (jpeg_with_exif(), "p.jpg")})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(q("SELECT status FROM complaints WHERE id=?", (cid,))[0][0], "Resolved")
        page = self.cit.get(loc).get_data(as_text=True)
        self.assertIn("Is it fixed?", page)
        self.assertIn("After the fix", page)
        # citizen reopens, then department resolves again, citizen confirms
        self.assertEqual(self.cit.post(f"/complaints/{cid}/reopen", data={"_csrf": t, "note": ""}).status_code, 302)
        self.assertEqual(q("SELECT status FROM complaints WHERE id=?", (cid,))[0][0], "Resolved")   # reason required
        self.cit.post(f"/complaints/{cid}/reopen", data={"_csrf": t, "note": "Still sparking"})
        self.assertEqual(q("SELECT status FROM complaints WHERE id=?", (cid,))[0][0], "Forwarded")
        self.tneb.post(f"/complaints/{cid}/resolve", data={"_csrf": tt, "note": "Replaced transformer"})
        self.cit.post(f"/complaints/{cid}/confirm", data={"_csrf": t})
        self.assertIsNotNone(q("SELECT confirmed_at FROM complaints WHERE id=?", (cid,))[0][0])
        actions = [r[0] for r in q("SELECT action FROM audit_log WHERE target=(SELECT ticket FROM complaints WHERE id=?)", (cid,))]
        for a in ("case_approved", "case_forwarded", "case_resolved", "case_reopened", "case_confirmed"):
            self.assertIn(a, actions)
        # public tracking shows no personal details
        ticket = q("SELECT ticket FROM complaints WHERE id=?", (cid,))[0][0]
        html = A.app.test_client().get(f"/track?ticket={ticket.lower()}").get_data(as_text=True)
        self.assertIn(ticket, html)
        self.assertNotIn("Pole sparking", html)
        self.assertNotIn("Demo Citizen", html)

    def test_07_bad_uploads(self):
        t = meta_csrf(self.cit, "/complaints/new")
        base = {"_csrf": t, "category": "Roads & Highways", "title": "x", "description": "y", "state": "TN", "district": "Chennai", "area": "A"}
        for name, blob in (("a.png", b"not an image at all"), ("a.jpg", b"<?php echo 1; ?>" * 50), ("a.exe", b"MZ" + b"0" * 50)):
            r = self.cit.post("/complaints/new", content_type="multipart/form-data", data={**base, "photo": (io.BytesIO(blob), name)})
            self.assertEqual(r.status_code, 200, name)
            self.assertIn("valid image", r.get_data(as_text=True))

    def test_08_reject_requires_reason(self):
        t = meta_csrf(self.cit, "/complaints/new")
        r = self.cit.post("/complaints/new", data={"_csrf": t, "category": "Roads & Highways", "title": "dup", "description": "dup", "state": "TN", "district": "Chennai", "area": "Guindy"})
        cid = int(r.headers["Location"].rsplit("/", 1)[1])
        ta = meta_csrf(self.adm, "/dashboard")
        self.adm.post(f"/complaints/{cid}/reject", data={"_csrf": ta, "note": ""})
        self.assertEqual(q("SELECT status FROM complaints WHERE id=?", (cid,))[0][0], "Submitted")
        self.adm.post(f"/complaints/{cid}/reject", data={"_csrf": ta, "note": "Duplicate"})
        self.assertEqual(q("SELECT status FROM complaints WHERE id=?", (cid,))[0][0], "Rejected")

    def test_09_register_otp_and_login_lockout(self):
        c = A.app.test_client()
        t = csrf_from(c.get("/register").get_data(as_text=True))
        form = {"_csrf": t, "name": "Ravi Kumar", "email": "ravi@example.com", "state": "TN", "district": "Chennai", "password": "short", "agree": "on"}
        self.assertIn("at least 8", c.post("/register", data=form).get_data(as_text=True))
        form["password"] = "password123"
        self.assertIn("too easy", c.post("/register", data=form).get_data(as_text=True))
        form["password"] = "Tr1cky-Pass"
        del form["agree"]
        self.assertIn("Terms", c.post("/register", data=form).get_data(as_text=True))
        form["agree"] = "on"
        r = c.post("/register", data=form)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/verify", r.headers["Location"])
        self.assertEqual(c.get("/dashboard").status_code, 302)                       # not signed in yet
        c2, r = login("ravi@example.com", "Tr1cky-Pass")
        self.assertIn("/verify", r.headers["Location"])                               # blocked until verified
        code = re.search(r"code is: (\d{6})", SENT[-1][2]).group(1)                   # sign-in attempt sent a fresh code
        t = csrf_from(c.get("/verify?email=ravi@example.com").get_data(as_text=True))
        wrong = c.post("/verify", data={"_csrf": t, "email": "ravi@example.com", "code": "000000"})
        self.assertIn("wrong or has expired", wrong.get_data(as_text=True))
        ok = c.post("/verify", data={"_csrf": t, "email": "ravi@example.com", "code": code})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(c.get("/dashboard").status_code, 200)
        # lockout after repeated failures (even with the right password afterwards)
        for _ in range(5):
            login("ravi@example.com", "wrong-password-1")
        _, r = login("ravi@example.com", "Tr1cky-Pass")
        self.assertEqual(r.status_code, 429)

    def test_10_otp_limits_and_reset(self):
        c = A.app.test_client()
        t = csrf_from(c.get("/forgot").get_data(as_text=True))
        c.post("/forgot", data={"_csrf": t, "email": "arjun@civicfix.in"})
        code = re.search(r"code is: (\d{6})", SENT[-1][2]).group(1)
        # 5 wrong guesses burn the code
        t = csrf_from(c.get("/reset?email=arjun@civicfix.in").get_data(as_text=True))
        for _ in range(5):
            c.post("/reset", data={"_csrf": t, "email": "arjun@civicfix.in", "code": "111111", "password": "Brand-New-9x"})
        c.post("/reset", data={"_csrf": t, "email": "arjun@civicfix.in", "code": code, "password": "Brand-New-9x"})
        self.assertEqual(login("arjun@civicfix.in", "Brand-New-9x")[1].status_code, 200)   # burnt code: password NOT changed
        _, r = login("arjun@civicfix.in", PW)
        self.assertEqual(r.status_code, 302)
        # unknown email gives the same generic answer (no account enumeration)
        r = c.post("/forgot", data={"_csrf": t, "email": "nobody@example.com"}, follow_redirects=True)
        self.assertIn("If that email has an account", r.get_data(as_text=True))
        # fresh code works
        c.post("/forgot", data={"_csrf": t, "email": "arjun@civicfix.in"})
        code = re.search(r"code is: (\d{6})", SENT[-1][2]).group(1)
        c.post("/reset", data={"_csrf": t, "email": "arjun@civicfix.in", "code": code, "password": "Brand-New-9x"})
        self.assertEqual(login("arjun@civicfix.in", "Brand-New-9x")[1].status_code, 302)

    def test_11_admin_created_user_must_change_password(self):
        t = meta_csrf(self.sup, "/admin/users")
        self.sup.post("/admin/users", data={"_csrf": t, "name": "Water Officer", "email": "w2@example.com", "password": "Temp-Pass-77",
                                           "role": "staff", "state": "TN", "district": "Chennai", "department": "Water Supply"})
        cl, r = login("w2@example.com", "Temp-Pass-77")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/account", cl.get("/dashboard").headers["Location"])           # forced to change it
        t = meta_csrf(cl, "/account")
        cl.post("/account", data={"_csrf": t, "current": "Temp-Pass-77", "password": "Final-Pass-88"})
        self.assertEqual(cl.get("/dashboard").status_code, 200)
        # district admin can only add officers to their own district
        t = meta_csrf(self.adm, "/admin/users")
        self.adm.post("/admin/users", data={"_csrf": t, "name": "Sneaky", "email": "s@example.com", "password": "Sneaky-Pass-1", "role": "superadmin", "state": "TN", "district": "Madurai"})
        self.assertEqual(q("SELECT role, district FROM users WHERE email='s@example.com'"), [])
        self.adm.post("/admin/users", data={"_csrf": t, "name": "Ok Officer", "email": "o@example.com", "password": "Okay-Pass-123", "department": "Sanitation"})
        self.assertEqual(q("SELECT role, district FROM users WHERE email='o@example.com'"), [("staff", "Chennai")])

    def test_12_account_export_and_delete(self):
        cl, _ = login("arjun@civicfix.in", "Brand-New-9x")
        data = cl.get("/account/export").get_json()
        self.assertEqual(data["account"]["email"], "arjun@civicfix.in")
        t = meta_csrf(cl, "/account")
        cl.post("/account/delete", data={"_csrf": t, "password": "wrong"})
        self.assertEqual(cl.get("/dashboard").status_code, 200)
        cl.post("/account/delete", data={"_csrf": t, "password": "Brand-New-9x"})
        self.assertEqual(cl.get("/dashboard").status_code, 302)
        self.assertEqual(login("arjun@civicfix.in", "Brand-New-9x")[1].status_code, 200)   # can't sign in any more
        self.assertEqual(q("SELECT name FROM users WHERE deleted_at IS NOT NULL")[0][0], "Deleted user")

    def test_13_open_redirect(self):
        c = A.app.test_client()
        t = csrf_from(c.get("/login").get_data(as_text=True))
        r = c.post("/login?next=//evil.com", data={"email": "citizen@civicfix.in", "password": PW, "_csrf": t})
        self.assertEqual(r.headers["Location"], "/dashboard")

    # ------------------------------------------------------------------ multi-state
    def test_20_geography_data(self):
        d = A.geo.get_geo()
        self.assertEqual(len(d["states"]), 36)
        self.assertGreater(sum(len(v) for v in d["districts"].values()), 700)
        self.assertIn("Lucknow", A.geo.district_names("UP"))
        self.assertNotIn("Lucknow", A.geo.district_names("TN"))
        self.assertTrue(A.geo.valid_pair("TN", "Chennai"))
        self.assertFalse(A.geo.valid_pair("UP", "Chennai"))
        self.assertEqual(A.geo.agency("TN", "Electricity")["short"], "TNEB")
        self.assertEqual(A.geo.agency("UP", "Electricity")["short"], "UPPCL")
        self.assertEqual(A.geo.agency("BR", "Electricity")["short"], "Electricity")     # generic fallback
        self.assertEqual(A.geo.center("UP", "Lucknow")[2], 7)                            # state zoom (no district centre stored)

    def test_21_state_isolation(self):
        up = self.upadm.get("/api/dashboard").get_json()
        self.assertEqual(up["total"], 3)
        self.assertEqual(up["state"], "UP")
        self.assertEqual(round(up["center"][0]), 27)
        tn_url = self.adm.get("/api/dashboard").get_json()["queue"][0]["url"]
        self.assertEqual(self.upadm.get(tn_url).status_code, 403)
        self.assertEqual(self.upstate.get(tn_url).status_code, 403)
        self.assertEqual(self.upcit.get(tn_url).status_code, 403)
        self.assertEqual(self.tnstate.get(tn_url).status_code, 200)
        self.assertEqual(self.tnstate.get("/api/dashboard").get_json()["total"], q("SELECT COUNT(*) FROM complaints WHERE state='TN'")[0][0])
        self.assertEqual(self.upstate.get("/api/dashboard").get_json()["total"], 3)
        self.assertEqual(self.tneb.get("/api/dashboard").get_json()["role"], "staff")
        # the officer in UP never sees TN cases
        self.assertEqual(self.upstaff.get("/api/dashboard").get_json()["total"], 2)

    def test_22_super_admin_state_filter(self):
        self.assertEqual(self.sup.get("/api/dashboard?state=UP").get_json()["total"], 3)
        self.assertEqual(self.sup.get("/api/dashboard?state=TN").get_json()["total"], q("SELECT COUNT(*) FROM complaints WHERE state='TN'")[0][0])
        self.assertEqual(self.sup.get("/api/dashboard?state=ZZ").get_json()["total"], q("SELECT COUNT(*) FROM complaints")[0][0])       # unknown -> all
        self.assertEqual(self.adm.get("/api/dashboard?state=UP").get_json()["total"], q("SELECT COUNT(*) FROM complaints WHERE district='Chennai'")[0][0])       # filter ignored for others
        self.assertEqual(self.sup.get("/dashboard?state=UP").status_code, 200)
        self.assertEqual(self.sup.get("/admin/departments?state=UP").status_code, 200)

    def test_23_state_specific_agency_names(self):
        up_page = self.upadm.get(self.upadm.get("/api/dashboard").get_json()["queue"][0]["url"]).get_data(as_text=True)
        self.assertIn("UPPCL", up_page)
        self.assertNotIn("TNEB", up_page)
        tn_page = self.adm.get(self.adm.get("/api/dashboard").get_json()["queue"][0]["url"]).get_data(as_text=True)
        self.assertIn("TNEB", tn_page)

    def test_24_report_must_match_state_and_notifies_local_admin(self):
        t = meta_csrf(self.upcit, "/complaints/new")
        base = {"_csrf": t, "category": "Electricity", "title": "Broken pole", "description": "Leaning pole", "area": "Hazratganj"}
        r = self.upcit.post("/complaints/new", data={**base, "state": "UP", "district": "Chennai"})        # wrong pair
        self.assertEqual(r.status_code, 200)
        r = self.upcit.post("/complaints/new", data={**base, "state": "UP", "district": "Lucknow"})
        self.assertEqual(r.status_code, 302)
        cid = int(r.headers["Location"].rsplit("/", 1)[1])
        self.assertEqual(q("SELECT state FROM complaints WHERE id=?", (cid,))[0][0], "UP")
        notes = self.upadm.get("/api/notifications").get_json()["items"]
        self.assertTrue(any("UPPCL" in n["message"] and "Hazratganj" in n["message"] for n in notes))
        self.assertFalse(any("Hazratganj" in n["message"] for n in self.adm.get("/api/notifications").get_json()["items"]))
        # forward within UP -> UP officer notified, not the TN one
        ta = meta_csrf(self.upadm, f"/complaints/{cid}")
        self.upadm.post(f"/complaints/{cid}/approve", data={"_csrf": ta, "forward_to": "Electricity"})
        self.assertTrue(any("Hazratganj" in n["message"] or "Broken pole" in n["message"] for n in self.upstaff.get("/api/notifications").get_json()["items"]))
        self.assertFalse(any("Broken pole" in n["message"] for n in self.tneb.get("/api/notifications").get_json()["items"]))

    def test_25_same_district_name_in_two_states(self):
        self.assertIn("Bilaspur", A.geo.district_names("HP"))
        self.assertIn("Bilaspur", A.geo.district_names("CG"))
        # an officer in Bilaspur (HP) must not see a Bilaspur (CG) case
        with A.db() as con:
            A.insert(con, "INSERT INTO users(name,email,password_hash,role,state,district,created_at,email_verified,must_change_password) VALUES('HP Admin','hp@x.in',?,'district_admin','HP','Bilaspur',?,1,0)", (A.generate_password_hash(PW), A.now_iso()))
            cg = A.insert(con, "INSERT INTO users(name,email,password_hash,role,state,district,created_at,email_verified,must_change_password) VALUES('CG Citizen','cg@x.in',?,'citizen','CG','Bilaspur',?,1,0)", (A.generate_password_hash(PW), A.now_iso()))
        t = meta_csrf(login("cg@x.in")[0], "/complaints/new") if False else None
        cl = login("cg@x.in")[0]
        t = meta_csrf(cl, "/complaints/new")
        r = cl.post("/complaints/new", data={"_csrf": t, "category": "Roads & Highways", "title": "Pothole", "description": "d", "state": "CG", "district": "Bilaspur", "area": "Sarkanda"})
        url = r.headers["Location"]
        hp = login("hp@x.in")[0]
        self.assertEqual(hp.get(url).status_code, 403)
        self.assertEqual(hp.get("/api/dashboard").get_json()["total"], 0)

    def test_26_state_admin_user_creation_rules(self):
        t = meta_csrf(self.tnstate, "/admin/users")
        # creates a district admin in own state
        self.tnstate.post("/admin/users", data={"_csrf": t, "name": "Madurai Admin", "email": "mdu@x.in", "password": "Madurai-Pass-1", "role": "district_admin", "district": "Madurai"})
        self.assertEqual(q("SELECT role,state,district FROM users WHERE email='mdu@x.in'"), [("district_admin", "TN", "Madurai")])
        # cannot create a super admin, nor cross into another state or an invalid district
        self.tnstate.post("/admin/users", data={"_csrf": t, "name": "Evil", "email": "evil@x.in", "password": "Evil-Pass-123", "role": "superadmin"})
        self.tnstate.post("/admin/users", data={"_csrf": t, "name": "Cross", "email": "cross@x.in", "password": "Cross-Pass-123", "role": "district_admin", "state": "UP", "district": "Lucknow"})
        self.tnstate.post("/admin/users", data={"_csrf": t, "name": "Bad", "email": "bad@x.in", "password": "Bad-Pass-12345", "role": "district_admin", "district": "Lucknow"})
        self.assertEqual(q("SELECT email FROM users WHERE email IN ('evil@x.in','cross@x.in','bad@x.in')"), [])
        # super admin creates a state admin for Kerala
        ts = meta_csrf(self.sup, "/admin/users")
        self.sup.post("/admin/users", data={"_csrf": ts, "name": "Kerala Admin", "email": "kl@x.in", "password": "Kerala-Pass-1", "role": "state_admin", "state": "KL"})
        self.assertEqual(q("SELECT role,state,district FROM users WHERE email='kl@x.in'"), [("state_admin", "KL", None)])
        # citizens and officers cannot reach admin pages
        for cl in (self.upcit, self.upstaff):
            self.assertEqual(cl.get("/admin/users").status_code, 403)
            self.assertEqual(cl.get("/admin/regions").status_code, 403)
        self.assertEqual(self.upadm.get("/admin/regions").status_code, 403)               # district admins don't manage regions

    def test_27_regions_admin(self):
        t = meta_csrf(self.upstate, "/admin/regions")
        self.assertEqual(self.upstate.get("/admin/regions").status_code, 200)
        self.upstate.post("/admin/regions", data={"_csrf": t, "state": "TN", "action": "add_district", "name": "Hacked"})   # state param ignored for state admins
        self.assertNotIn("Hacked", A.geo.district_names("TN"))
        self.upstate.post("/admin/regions", data={"_csrf": t, "action": "add_district", "name": "Test Nagar", "lat": "26.9", "lng": "80.9"})
        self.assertIn("Test Nagar", A.geo.district_names("UP"))
        self.assertEqual(A.geo.center("UP", "Test Nagar")[2], 12)
        self.upstate.post("/admin/regions", data={"_csrf": t, "action": "delete_district", "name": "Lucknow"})          # in use -> refused
        self.assertIn("Lucknow", A.geo.district_names("UP"))
        self.upstate.post("/admin/regions", data={"_csrf": t, "action": "delete_district", "name": "Test Nagar"})
        self.assertNotIn("Test Nagar", A.geo.district_names("UP"))
        form = {"_csrf": t, "action": "save_agencies"}
        form.update({f"name_{c}": "" for c in A.DEPARTMENTS}); form.update({f"short_{c}": "" for c in A.DEPARTMENTS})
        form.update({"name_Electricity": "Madhyanchal Vidyut Vitran Nigam", "short_Electricity": "MVVNL"})
        self.upstate.post("/admin/regions", data=form)
        self.assertEqual(A.geo.agency("UP", "Electricity")["short"], "MVVNL")
        self.assertEqual(A.geo.agency("TN", "Electricity")["short"], "TNEB")             # other states untouched
        self.assertEqual(self.sup.get("/admin/regions?state=KL").status_code, 200)

    def test_28_register_requires_valid_state_district(self):
        with A.db() as con:
            con.execute("DELETE FROM rate_events")          # earlier tests used up this network's sign-up allowance
        c = A.app.test_client()
        t = csrf_from(c.get("/register").get_data(as_text=True))
        form = {"_csrf": t, "name": "Sita Devi", "email": "sita@example.com", "state": "UP", "district": "Chennai", "password": "Good-Pass-2026", "agree": "on"}
        self.assertIn("state and district", c.post("/register", data=form).get_data(as_text=True))
        form["district"] = "Varanasi"
        self.assertEqual(c.post("/register", data=form).status_code, 302)
        self.assertEqual(q("SELECT state,district FROM users WHERE email='sita@example.com'"), [("UP", "Varanasi")])
        page = A.app.test_client().get("/register").get_data(as_text=True)
        self.assertIn("window.__GEO__", page)
        self.assertEqual(page.count("window.__GEO__"), 1)

    def test_29_legacy_database_upgrade(self):
        import sqlite3
        path = os.path.join(TMP, "legacy.db")
        con = sqlite3.connect(path)
        con.executescript("""CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT UNIQUE, password_hash TEXT, role TEXT, district TEXT, department TEXT, created_at TEXT);
        CREATE TABLE complaints (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket TEXT UNIQUE, user_id INTEGER, title TEXT, description TEXT, category TEXT, district TEXT, area TEXT, address TEXT, latitude REAL, longitude REAL, photo TEXT, status TEXT, priority TEXT, assigned_to INTEGER, resolution_note TEXT, created_at TEXT, updated_at TEXT);
        INSERT INTO users VALUES (1,'Old User','old@x.in','h','citizen','Madurai',NULL,'2025-01-01');
        INSERT INTO complaints VALUES (1,'CF-OLD',1,'t','d','Electricity','Madurai','Anna Nagar',NULL,NULL,NULL,NULL,'Under Review','Medium',NULL,NULL,'2025-01-01T10:00:00','2025-01-01T10:00:00');""")
        con.commit(); con.close()
        import db as D
        old = D.DB_PATH
        D.DB_PATH = __import__("pathlib").Path(path)
        try:
            D.init_schema()
            with D.db() as c2:
                self.assertEqual(tuple(c2.execute("SELECT state, status FROM complaints WHERE id=1").fetchone()), ("TN", "Submitted"))
                self.assertEqual(c2.execute("SELECT state FROM users WHERE id=1").fetchone()[0], "TN")
        finally:
            D.DB_PATH = old


if __name__ == "__main__":
    unittest.main()
