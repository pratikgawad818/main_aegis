"""Plain checks (no AI) that turn the extracted data into a final decision."""

import logging
from datetime import datetime, timedelta

from rapidfuzz import fuzz

from app.config import CERTIFICATE_VALIDITY_DAYS, NAME_MATCH_THRESHOLD, VALID_STATUSES
from app.schemas import Remark

logger = logging.getLogger(__name__)


def is_certificate_valid(date_string: str) -> bool:
    """True if the certificate date is recent enough and not in the future."""
    if not date_string or not date_string.strip():
        return False
    date_formats = [
        "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d",
        "%d %B %Y", "%B %d, %Y", "%d-%b-%Y", "%d/%b/%Y",
    ]
    now = datetime.now()
    cutoff = now - timedelta(days=CERTIFICATE_VALIDITY_DAYS)
    for fmt in date_formats:
        try:
            cert_date = datetime.strptime(date_string.strip(), fmt)
        except ValueError:
            continue
        # Must be recent AND not in the future (1-day grace for time zones).
        return cutoff <= cert_date <= now + timedelta(days=1)
    logger.warning(f"Could not parse certificate date: '{date_string}'")
    return False


def normalize_name(name: str) -> str:
    """Lowercase, collapse spaces, and strip titles (Mr./Dr.) and suffixes."""
    name = " ".join(name.lower().split())
    prefixes = ["mr.", "mrs.", "ms.", "miss.", "dr.", "prof.", "mr ", "mrs ", "ms ", "dr "]
    changed = True
    while changed:
        changed = False
        for p in prefixes:
            if name.startswith(p):
                name = name[len(p):].strip()
                changed = True
    for suffix in [" jr.", " sr.", " jr", " sr", " ii", " iii"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    return name


def names_match(name_on_form: str, name_on_document: str) -> bool:
    """Fuzzy, case-insensitive name comparison. True if similar enough."""
    if not name_on_form or not name_on_document:
        return False
    a = normalize_name(name_on_form)
    b = normalize_name(name_on_document)
    if not a or not b:
        return False
    score = max(
        fuzz.token_sort_ratio(a, b),
        fuzz.partial_ratio(a, b),
        fuzz.token_set_ratio(a, b),
    )
    logger.info(f"Name match score: {score} | '{a}' vs '{b}'")
    return score >= NAME_MATCH_THRESHOLD


def normalize_medical_status(raw: str) -> str:
    """Map Gemini's status text to FIT / UNFIT / FIT_WITH_RECOMMENDATION."""
    if not raw:
        return "UNKNOWN"
    s = raw.strip().upper().replace(" ", "_").replace("-", "_")
    if s in VALID_STATUSES:
        return s
    if "UNFIT" in s:
        return "UNFIT"
    if "RECOMMENDATION" in s or "CONDITIONAL" in s:
        return "FIT_WITH_RECOMMENDATION"
    if "FIT" in s:
        return "FIT"
    return "UNKNOWN"


def combine_statuses(certificate_status, pef_status):
    """
    Combine the certificate verdict and the pre-employment-form (PEF) verdict
    into one effective status, and flag a conflict if they disagree
    (e.g. the certificate says FIT but the PEF says UNFIT).

    Returns (effective_status, conflict). The stricter verdict wins:
    UNFIT > FIT_WITH_RECOMMENDATION > FIT.
    """
    cert = normalize_medical_status(certificate_status)
    pef = normalize_medical_status(pef_status)
    known = [s for s in (cert, pef) if s in VALID_STATUSES]
    if not known:
        return "UNKNOWN", False
    order = {"FIT": 1, "FIT_WITH_RECOMMENDATION": 2, "UNFIT": 3}
    effective = max(known, key=lambda s: order[s])
    conflict = "UNFIT" in known and any(s in ("FIT", "FIT_WITH_RECOMMENDATION") for s in known)
    return effective, conflict


# Problems that cause an automatic REJECTED decision.
HARD_FAILURES = {
    "MEDICAL_STATUS_UNFIT",
    "CERTIFICATE_EXPIRED",
    "NAME_MISMATCH",
    "MISSING_PHYSICIAN_STAMP",
}

# Problems that need a human to look - not auto-approved, not auto-rejected.
REVIEW_FLAGS = {
    "STATUS_CONFLICT",
    "MISSING_CANDIDATE_PHOTO",
    "PHOTO_NOT_STAMPED",
}


def build_decision(ai_data, candidate_name_on_form, certificate_valid, name_matched):
    """
    Apply the business rules and return (final_decision, remarks, medical_status).

    The certificate verdict and the pre-employment-form verdict are combined.
    Each failed check adds a Remark. A "hard failure" means REJECTED; a
    disagreement between the two verdicts means MANUAL_REVIEW_REQUIRED.
    """
    remarks = []

    # Combine the certificate verdict with the pre-employment-form verdict.
    cert_status = ai_data.get("certificate_status") or ai_data.get("medical_status", "")
    pef_status = ai_data.get("pef_status", "")
    status, conflict = combine_statuses(cert_status, pef_status)

    if conflict:
        remarks.append(Remark(
            code="STATUS_CONFLICT",
            message=(
                f"Certificate says {normalize_medical_status(cert_status)} but the "
                f"pre-employment form says {normalize_medical_status(pef_status)} - "
                f"the two disagree and need manual review."
            ),
        ))
    elif status == "UNFIT":
        remarks.append(Remark(
            code="MEDICAL_STATUS_UNFIT",
            message="The document states the candidate is medically UNFIT.",
        ))

    if not certificate_valid:
        cert_date = ai_data.get("certificate_date") or "unknown"
        remarks.append(Remark(
            code="CERTIFICATE_EXPIRED",
            message=f"Certificate date '{cert_date}' is older than 6 months or could not be read.",
        ))

    if not name_matched:
        remarks.append(Remark(
            code="NAME_MISMATCH",
            message=(
                f"Name on form ('{candidate_name_on_form}') does not match the certificate "
                f"name ('{ai_data.get('candidate_name_on_document', 'not found')}')."
            ),
        ))

    if not ai_data.get("doctor_present", False):
        remarks.append(Remark(
            code="MISSING_PHYSICIAN_STAMP",
            message="General Physician (MBBS/MD) stamp or signature not found.",
        ))

    # Soft warning only - does NOT cause rejection.
    if not ai_data.get("ophthalmologist_present", False):
        remarks.append(Remark(
            code="MISSING_OPHTHALMOLOGIST_STAMP",
            message="Ophthalmologist stamp not detected. Please verify manually.",
        ))

    # The pre-employment form should carry the candidate's photo, stamped by the doctor.
    if not ai_data.get("candidate_photo_present", False):
        remarks.append(Remark(
            code="MISSING_CANDIDATE_PHOTO",
            message="No candidate photograph found on the pre-employment form.",
        ))
    elif not ai_data.get("photo_stamped", False):
        remarks.append(Remark(
            code="PHOTO_NOT_STAMPED",
            message="The candidate's photograph is not stamped by the doctor.",
        ))

    # Copy across any medical notes Gemini extracted.
    ai_remarks = ai_data.get("remarks", [])
    if not isinstance(ai_remarks, list):
        ai_remarks = [ai_remarks]
    for r in ai_remarks:
        if str(r).strip():
            remarks.append(Remark(code="MEDICAL_REMARK", message=str(r).strip()))

    # Decide the final outcome.
    failed_codes = {r.code for r in remarks}
    if failed_codes & HARD_FAILURES:
        final_decision = "REJECTED"
    elif failed_codes & REVIEW_FLAGS:
        final_decision = "MANUAL_REVIEW_REQUIRED"
    elif status == "FIT_WITH_RECOMMENDATION":
        final_decision = "APPROVED_WITH_REVIEW"
    elif status == "FIT":
        final_decision = "APPROVED"
    else:
        final_decision = "MANUAL_REVIEW_REQUIRED"

    return final_decision, remarks, status
