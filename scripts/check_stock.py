#!/usr/bin/env python3
import json
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timezone
import urllib.request

PRODUCT_URL = "https://maetpets.com/produkt/stop-madspil/"
STATE_FILE = Path("stock_state.json")

# Tweak these if the site text changes
OUT_OF_STOCK_PATTERNS = [
    r"Ikke på lager",
    r"Udsolgt",
]
IN_STOCK_HINTS = [
    r"På lager",
    r"Læg i kurv",
    r"Tilføj til kurv",
]

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (GitHub Actions stock checker)"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")

def detect_available(html: str) -> bool:
    # If explicit out-of-stock markers exist, treat as not available
    for pat in OUT_OF_STOCK_PATTERNS:
        if re.search(pat, html, re.IGNORECASE):
            return False
    # Otherwise, if any in-stock hints exist, treat as available
    for pat in IN_STOCK_HINTS:
        if re.search(pat, html, re.IGNORECASE):
            return True
    # Fallback: assume not available unless we saw a positive signal
    return False

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_available": None, "last_status_email_utc": None}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def parse_iso(dt: str):
    return datetime.fromisoformat(dt.replace("Z", "+00:00"))

def should_send_12h_status(last_sent_iso: str | None, now: datetime) -> bool:
    if not last_sent_iso:
        return True
    last = parse_iso(last_sent_iso)
    return (now - last).total_seconds() >= 12 * 3600

def send_email(subject: str, body: str):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USERNAME"]
    smtp_pass = os.environ["SMTP_PASSWORD"]
    mail_from = os.environ["MAIL_FROM"]
    recipients = [r.strip() for r in os.environ["MAIL_TO"].split(",") if r.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls(context=context)
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

def main():
    html = fetch_html(PRODUCT_URL)
    available = detect_available(html)

    state = load_state()
    last_available = state.get("last_available")
    now = datetime.now(timezone.utc)

    # 1) Restock alert on transition -> available
    if available and last_available is not True:
        send_email(
            subject="✅ Back in stock: Stop madspild (MÆT)",
            body=f"It looks AVAILABLE right now.\n\n{PRODUCT_URL}\n\nChecked (UTC): {utc_now_iso()}",
        )

    # 2) Status email every 12 hours
    if should_send_12h_status(state.get("last_status_email_utc"), now):
        send_email(
            subject="Stock status (12h): Stop madspild (MÆT)",
            body=(
                f"Current status: {'AVAILABLE ✅' if available else 'NOT available ❌'}\n\n"
                f"{PRODUCT_URL}\n\nChecked (UTC): {utc_now_iso()}"
            ),
        )
        state["last_status_email_utc"] = now.isoformat()

    state["last_available"] = available
    save_state(state)

    print(f"available={available} last_available={last_available}", file=sys.stderr)

if __name__ == "__main__":
    main()
