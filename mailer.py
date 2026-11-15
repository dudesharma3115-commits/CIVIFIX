"""Sends email. Pick ONE provider with environment variables:

  BREVO_API_KEY   (+ MAIL_FROM)  -> Brevo over HTTPS   [works on Render's free plan]
  RESEND_API_KEY  (+ MAIL_FROM)  -> Resend over HTTPS  [works on Render's free plan]
  SMTP_HOST ...   (+ MAIL_FROM)  -> classic SMTP        [Render FREE plans block SMTP ports; fine on paid plans / other hosts]

MAIL_FROM looks like:  CivicFix <no-reply@your-domain.in>   (the address must be verified with your provider)
With nothing configured, messages are printed to the log instead (development).
"""
import json
import logging
import os
import re
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

log = logging.getLogger("civicfix.mail")


def provider():
    if os.environ.get("BREVO_API_KEY") and os.environ.get("MAIL_FROM"):
        return "brevo"
    if os.environ.get("RESEND_API_KEY") and os.environ.get("MAIL_FROM"):
        return "resend"
    if os.environ.get("SMTP_HOST") and os.environ.get("MAIL_FROM"):
        return "smtp"
    return None


def configured():
    return provider() is not None


def _parse_from(value):
    m = re.match(r"^\s*(.*?)\s*<([^>]+)>\s*$", value)
    return (m.group(1).strip('" ') or "CivicFix", m.group(2)) if m else ("CivicFix", value.strip())


def _post_json(url, headers, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def send_mail(to, subject, body):
    prov = provider()
    if prov is None:
        log.warning("MAIL (not sent, no email provider configured) to=%s subject=%s\n%s", to, subject, body)
        print(f"\n--- EMAIL to {to}: {subject}\n{body}\n---", flush=True)
        return False
    name, addr = _parse_from(os.environ["MAIL_FROM"])
    try:
        if prov == "brevo":
            _post_json("https://api.brevo.com/v3/smtp/email", {"api-key": os.environ["BREVO_API_KEY"]},
                       {"sender": {"name": name, "email": addr}, "to": [{"email": to}], "subject": subject, "textContent": body})
        elif prov == "resend":
            _post_json("https://api.resend.com/emails", {"Authorization": "Bearer " + os.environ["RESEND_API_KEY"]},
                       {"from": f"{name} <{addr}>", "to": [to], "subject": subject, "text": body})
        else:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = os.environ["MAIL_FROM"], to, subject
            msg.set_content(body)
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=12) as s:
                s.starttls()
                if os.environ.get("SMTP_USER"):
                    s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
        return True
    except urllib.error.HTTPError as e:
        log.error("Email provider %s rejected the message (HTTP %s): %s", prov, e.code, e.read()[:300])
    except Exception:
        log.exception("Could not send email to %s via %s", to, prov)
    return False
