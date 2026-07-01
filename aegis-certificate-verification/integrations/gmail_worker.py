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
    """Turn the API response into a readable plain-text email body (fallback)."""
    r = data.get("verification_result", {})
    flags = [x["code"] for x in r.get("remarks", [])]

    # Summarise medical history: list ticked conditions if any.
    history = r.get("medical_history", [])
    ticked = [h["condition"] for h in history if h.get("ticked")]
    history_line = f"Ticked conditions: {', '.join(ticked)}" if ticked else "No conditions ticked"

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
        f"Medical history:  {history_line}\n"
        f"Flags:            {', '.join(flags) if flags else 'none'}\n"
        f"\nRequest ID: {data.get('request_id')}\n"
        "\n(Automated screening - the final decision rests with HR.)\n"
    )


# Colour and friendly label for each final decision.
DECISION_STYLES = {
    "APPROVED":               ("#16a34a", "Approved"),
    "APPROVED_WITH_REVIEW":   ("#d97706", "Approved with Review"),
    "REJECTED":               ("#dc2626", "Rejected"),
    "MANUAL_REVIEW_REQUIRED": ("#4f46e5", "Manual Review Required"),
    "TEMPORARY_UNFIT":        ("#92400e", "Temporary Unfit — Medical History Conflict"),
}


def _yes_no(value) -> str:
    """Render a boolean as a friendly Yes / No."""
    return "Yes" if value else "No"


def format_html(data: dict) -> str:
    """Build a polished, color-coded HTML version of the result email."""
    r = data.get("verification_result", {})
    decision = r.get("final_decision", "UNKNOWN")
    color, label = DECISION_STYLES.get(decision, ("#475569", decision.replace("_", " ").title()))

    # Detail rows shown in the table: (label, value).
    rows = [
        ("Candidate", r.get("candidate_name_on_document") or "-"),
        ("Medical status", r.get("medical_status") or "-"),
        ("Certificate verdict", r.get("certificate_status") or "-"),
        ("Pre-employment form", r.get("pef_status") or "-"),
        ("Name match", _yes_no(r.get("name_match"))),
        ("Certificate date", r.get("certificate_date") or "-"),
        ("Certificate valid", _yes_no(r.get("certificate_valid"))),
        ("Doctor stamp", _yes_no(r.get("doctor_present"))),
        ("Ophthalmologist stamp", _yes_no(r.get("ophthalmologist_present"))),
        ("Photo on form", _yes_no(r.get("candidate_photo_present"))),
        ("Photo stamped", _yes_no(r.get("photo_stamped"))),
    ]
    row_html = ""
    for i, (k, v) in enumerate(rows):
        bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
        row_html += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:10px 16px;color:#64748b;font-size:14px;">{k}</td>'
            f'<td style="padding:10px 16px;color:#0f172a;font-size:14px;font-weight:600;text-align:right;">{v}</td>'
            f'</tr>'
        )

    # Notes / flags list (or an all-clear line).
    remarks = r.get("remarks", [])
    if remarks:
        items = "".join(
            f'<li style="margin:6px 0;color:#334155;font-size:14px;">{x.get("message", "")}</li>'
            for x in remarks
        )
        flags_html = (
            '<p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#475569;'
            'text-transform:uppercase;letter-spacing:0.5px;">Notes &amp; flags</p>'
            f'<ul style="margin:0;padding-left:20px;">{items}</ul>'
        )
    else:
        flags_html = '<p style="margin:0;color:#16a34a;font-size:14px;">No issues detected.</p>'

    # Medical history table (only if items were found).
    history = r.get("medical_history", [])
    if history:
        conflict = r.get("history_conflict", False)
        conflict_banner = ""
        if conflict:
            conflict_banner = (
                '<tr><td colspan="2" style="padding:10px 16px;background:#fef3c7;'
                'color:#92400e;font-size:13px;font-weight:600;">'
                '⏸️ History conflict detected — ticked condition(s) disagree with the FIT verdict. '
                'HR must review before clearance.</td></tr>'
            )
        hist_rows = "".join(
            f'<tr style="background:{"#fef2f2" if item.get("ticked") else "#f8fafc"};">'
            f'<td style="padding:8px 16px;font-size:14px;color:#0f172a;">{item.get("condition","")}</td>'
            f'<td style="padding:8px 16px;font-size:14px;font-weight:700;text-align:right;'
            f'color:{"#dc2626" if item.get("ticked") else "#64748b"};">'
            f'{"✔ Yes" if item.get("ticked") else "No"}</td></tr>'
            for item in history
        )
        history_section = f"""
        <!-- Medical history -->
        <tr><td style="padding:16px 24px 0;">
          <p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#475569;
            text-transform:uppercase;letter-spacing:0.5px;">Medical History (Self-Reported)</p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
            style="border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
            {conflict_banner}
            <tr style="background:#f1f5f9;">
              <th style="padding:8px 16px;font-size:11px;font-weight:700;color:#64748b;
                text-transform:uppercase;letter-spacing:0.5px;text-align:left;">Condition</th>
              <th style="padding:8px 16px;font-size:11px;font-weight:700;color:#64748b;
                text-transform:uppercase;letter-spacing:0.5px;text-align:right;">Reported</th>
            </tr>
            {hist_rows}
          </table>
        </td></tr>"""
    else:
        history_section = ""

    request_id = data.get("request_id", "-")

    return f"""\
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <!-- Header -->
        <tr><td style="background:#1d4ed8;padding:20px 24px;">
          <span style="color:#ffffff;font-size:20px;font-weight:700;letter-spacing:0.5px;">Aegis</span>
          <span style="color:#bfdbfe;font-size:13px;">&nbsp; Certificate Verification</span>
        </td></tr>
        <!-- Verdict banner -->
        <tr><td style="background:{color};padding:22px 24px;text-align:center;">
          <div style="color:#ffffff;font-size:12px;text-transform:uppercase;letter-spacing:1px;opacity:0.85;">Final Decision</div>
          <div style="color:#ffffff;font-size:24px;font-weight:700;margin-top:4px;">{label}</div>
        </td></tr>
        <!-- Details table -->
        <tr><td style="padding:8px 8px 0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
            {row_html}
          </table>
        </td></tr>
        <!-- Notes / flags -->
        <tr><td style="padding:16px 24px;">{flags_html}</td></tr>
        {history_section}
        <!-- Footer -->
        <tr><td style="padding:16px 24px;border-top:1px solid #e2e8f0;">
          <p style="margin:0;color:#94a3b8;font-size:12px;line-height:1.5;">
            Automated screening &mdash; the final decision rests with HR.<br>
            Request ID: {request_id}
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_reply(to_addr, subject, body, in_reply_to=None, html=None):
    """Send a reply via Gmail SMTP: plain text, plus an optional HTML version."""
    msg = EmailMessage()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_addr
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
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
    html = None
    try:
        data = verify_pdf(name, filename, pdf_bytes)
        body = format_result(data)   # plain-text fallback
        html = format_html(data)     # polished HTML version
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        body = f"Sorry, verification could not be completed: {e}"
    send_reply(from_addr, f"Re: {subject}", body, msg_id, html=html)
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
