# CivicFix India

Citizens report civic issues with a photo and map pin. District admins approve and forward them to the right department (TNEB, Water Board, Highways…). Officers are notified, fix the issue and close it with proof. The citizen confirms the fix or reopens the case.

## 1. Try it on your PC (2 minutes)

```powershell
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000. Demo accounts (password `CivicFix@2026`) appear on the login page. Emails (OTP codes) print in the terminal when SMTP isn't set up.

Run the tests: `python -m unittest discover -s tests -v`

## 2. Put it online for free (Render + Supabase)

Render's free disk is wiped on every restart, so data and photos live in Supabase instead.

**A. Supabase (database + photo storage)**
1. Create a project at supabase.com. Save the database password.
2. *Project Settings → Database → Connection string*: copy the URI (use the **Session pooler** one) and put your password in it. This is `DATABASE_URL`.
3. *Storage → New bucket*: name `civicfix-media`, **leave "Public bucket" OFF** (photos stay private).
4. *Project Settings → API*: copy the Project URL (`SUPABASE_URL`) and the **service_role / secret** key (`SUPABASE_SERVICE_KEY`). Keep this key secret; it only goes in Render's environment settings.

**B. Email for OTP codes (free SMTP)**: create a free account at an SMTP provider such as Brevo or Zoho, or use a Gmail app password. You need host, port, user, password, and a sender address (`MAIL_FROM`).

**C. Render**
1. Push this folder to a **private GitHub repo** (`.env` and `civicfix.db` are already in `.gitignore`).
2. Render → *New → Blueprint* → pick the repo. It reads `render.yaml`.
3. Fill in the environment variables it asks for: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, SMTP settings, `CIVICFIX_CONTACT_EMAIL`, and the first admin: `CIVICFIX_ADMIN_EMAIL` + `CIVICFIX_ADMIN_PASSWORD`. (`CIVICFIX_SECRET` is generated for you.)
4. Deploy. Open the URL, sign in as that admin, set a new password when asked, then **delete `CIVICFIX_ADMIN_PASSWORD`** from Render.
5. Optional: a free uptime monitor (e.g. UptimeRobot) pinging `/healthz` every 5 minutes reduces cold starts.

**D. First setup in the app**: as super admin go to *Users & roles* and create district admins, then each district admin adds department officers (TNEB, Water, Highways…). New accounts must change their temporary password at first sign-in.

## Security built in
HTTPS-only with HSTS, strict Content-Security-Policy (script nonces), CSRF tokens, secure/HttpOnly/SameSite cookies, hashed passwords, password rules, login lockout and rate limits (database-backed, works across workers), email OTP verification and password reset, forced password change for admin-created accounts, role-based access checked on every request, **private photos** served only to people allowed to see the case, photos re-encoded to strip GPS/EXIF and any hidden payload, audit log of all sign-ins and case actions (Super admin → Audit log), account data export and deletion, public ticket tracking that never shows personal details.

## Settings (environment variables)
See `.env.example`. Production refuses to start without a 32+ character `CIVICFIX_SECRET`. `CIVICFIX_DEMO` must stay `0` in production (it is by default).

## Still needed before a government launch (not code)
- An independent **security audit** (most departments require one by an empanelled agency) and basic load test.
- Lawyer-reviewed **Privacy Policy and Terms** (drafts are included, with placeholders), DPDP Act compliance, a named grievance officer, data-retention rules.
- Real **officer accounts** from each department; agreement on who receives which cases.
- **SMS/WhatsApp alerts** to officers (needs a paid provider) so they are reached outside the app.
- Tamil (and other languages) for citizens; accessibility review against GIGW.
- Paid hosting or government-cloud hosting once traffic grows (free tiers sleep and have no uptime guarantee).

## Notes
- The Postgres and Supabase Storage code paths could not be run against live services while this was built (only SQLite was exercised by the tests). Deploy first to a staging copy, create a test report with a photo, and check the *Audit log* and `/healthz` before announcing publicly.
- Leaflet map scripts load from unpkg and fonts from Google, map tiles from CARTO's free service (fair-use limits). For heavy traffic, self-host Leaflet and use a paid tile provider.
