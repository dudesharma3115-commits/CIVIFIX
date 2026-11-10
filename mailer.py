"""Sends email through any SMTP service (Brevo, Gmail app password, Zoho, your own server).

Set SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD and MAIL_FROM.
In development with no SMTP configured, messages are printed to the console instead.
"""
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("civicfix.mail")


def configured():
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("MAIL_FROM"))


def send_mail(to, subject, body):
    if not configured():
        log.warning("MAIL (not sent, SMTP not configured) to=%s subject=%s\n%s", to, subject, body)
        print(f"\n--- EMAIL to {to}: {subject}\n{body}\n---", flush=True)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.environ["MAIL_FROM"], to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=12) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except Exception:
        log.exception("Could not send email to %s", to)
        return False
