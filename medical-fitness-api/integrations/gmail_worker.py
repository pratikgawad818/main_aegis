"""
Gmail integration worker for Aegis.

Watches a Gmail inbox (IMAP). For every new unread email that has a PDF
attached, it sends the PDF to the Aegis API and emails the verification
result back to the sender.

See the project README for setup. Run with:
    python integrations/gmail_worker.py
"""

import email
import imaplib
import logging
import os
import smtplib
import time
from email.message import EmailMessage
from email.utils import parseaddr

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("gmail_worker")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
AEGIS_URL = os.environ.get("AEGIS_URL", "http://127.0.0.1:8000/api/v1/verify")
# Reuse the server's API_KEY by default so you only set the key once.
AEGIS_API_KEY = os.environ.get("AEGIS_API_KEY") or os.environ.get("API_KEY", "")
POLL_SECONDS = int(os.environ.get("EMAIL_POLL_SECONDS", 30))
# Safety: only reply to these senders/domains (comma-separated). Empty = anyone.
ALLOWED_SENDERS = [s.strip().lower() for s in os.environ.get("ALLOWED_SENDERS", "").split(",") if s.strip()]

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def sender_allowed(from_addr: str) -> bool:
    """If an allowlist is configured, only allow matching senders/domains."""
    if not ALLOWED_SENDERS:
        return True
    addr = from_addr.lower()
    domain = addr.split("@")[-1]
    return addr in ALLOWED_SENDERS or domain in ALLOWED_SENDERS


def get_candidate_name(msg) -> str:
    """Candidate name = a 'Name:' line in the body, else the email subject."""
    subject = msg.get("Subject", "").strip()
    body = ""
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            try:
                body = part.get_payload(decode=True).decode(errors="ignore")
            except Exception:
                body = ""
            break
    for line in body.splitlines():
        if line.lower().startswith("name:"):
            return line.split(":", 1)[1].strip()
    # Strip common reply / forward prefixes from the subject.
    for p in ("re:", "fwd:", "fw:"):
        if subject.lower().startswith(p):
            subject = subject[len(p):].strip()
    return subject


def get_pdf_attachment(msg):
    """Return (filename, bytes) of the first PDF attachment, or None."""
    for part in msg.walk():
        filename = part.get_filename() or ""
        if filename.lower().endswith(".pdf"):
            return filename, part.get_payload(decode=True)
    return None


def verify_pdf(name, filename, pdf_bytes) -> dict:
    """Call the Aegis API and return its JSON response."""
    headers = {"X-API-Key": AEGIS_API_KEY} if AEGIS_API_KEY else {}
    resp = requests.post(
        AEGIS_URL,
        headers=headers,
        data={"candidate_name": name},
        files={"file": (filename, pdf_bytes, "application/pdf")},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def format_result(data: dict) -> str:
    """Turn the API response into a readable email body."""
    r = data.get("verification_result", {})
    flags = [x["code"] for x in r.get("remarks", [])]
    return (
        "Aegis result\n"
        "----------------\n"
        f"Candidate:        {r.get('candidate_name_on_document') or '-'}\n"
        f"Final decision:   {r.get('final_decision')}\n"
        f"Medical status:   {r.get('medical_status')}\n"
        f"Certificate:      {r.get('certificate_status')}\n"
        f"Pre-employment:   {r.get('pef_status')}\n"
        f"Name match:       {r.get('name_match')}\n"
        f"Certificate date: {r.get('certificate_date') or '-'} (valid: {r.get('certificate_valid')})\n"
        f"Photo stamped:    {r.get('photo_stamped')}\n"
        f"Flags:            {', '.join(flags) if flags else 'none'}\n"
        f"\nRequest ID: {data.get('request_id')}\n"
        "\n(Automated screening - the final decision rests with HR.)\n"
    )


def send_reply(to_addr, subject, body, in_reply_to=None):
    """Send a plain-text reply via Gmail SMTP."""
    msg = EmailMessage()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_addr
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)


def handle_message(msg):
    """Process one email: verify its PDF and reply with the result."""
    from_addr = parseaddr(msg.get("From", ""))[1]
    subject = msg.get("Subject", "(no subject)")
    msg_id = msg.get("Message-ID")

    if not sender_allowed(from_addr):
        logger.info(f"Skipping email from non-allowed sender: {from_addr}")
        return

    attachment = get_pdf_attachment(msg)
    if not attachment:
        send_reply(from_addr, f"Re: {subject}",
                   "No PDF certificate was attached. Please reply with the PDF attached.", msg_id)
        return

    name = get_candidate_name(msg) or "Unknown"
    filename, pdf_bytes = attachment
    logger.info(f"Verifying '{name}' from {from_addr} ({filename})")
    try:
        data = verify_pdf(name, filename, pdf_bytes)
        body = format_result(data)
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        body = f"Sorry, verification could not be completed: {e}"
    send_reply(from_addr, f"Re: {subject}", body, msg_id)
    logger.info(f"Replied to {from_addr}")


def check_inbox():
    """Connect to Gmail, process all unread emails, then disconnect."""
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    imap.select("INBOX")
    _, data = imap.search(None, "UNSEEN")
    for num in data[0].split():
        _, raw = imap.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])
        try:
            handle_message(msg)
        except Exception as e:
            logger.error(f"Error handling message: {e}")
        imap.store(num, "+FLAGS", "\\Seen")
    imap.logout()


def main():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise SystemExit("Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env first.")
    if not ALLOWED_SENDERS:
        logger.warning("ALLOWED_SENDERS is empty - the worker will reply to ANYONE who "
                       "emails this inbox. Set ALLOWED_SENDERS in .env to restrict access "
                       "(strongly recommended for medical data).")
    logger.info(f"Watching {GMAIL_ADDRESS}, polling every {POLL_SECONDS}s. Press Ctrl+C to stop.")
    while True:
        try:
            check_inbox()
        except Exception as e:
            logger.error(f"Inbox check failed: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
