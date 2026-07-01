"""Unit tests for the business rules (no AI, no network)."""

from datetime import datetime, timedelta

from app.services.rules import (
    build_decision,
    combine_statuses,
    is_certificate_valid,
    names_match,
    normalize_medical_status,
)


def _decide(cert, pef, doctor=True, ophth=True, photo=True, photo_stamped=True):
    ai = {
        "certificate_status": cert,
        "pef_status": pef,
        "doctor_present": doctor,
        "ophthalmologist_present": ophth,
        "candidate_photo_present": photo,
        "photo_stamped": photo_stamped,
        "candidate_name_on_document": "Ravi Kumar",
        "remarks": [],
    }
    decision, remarks, status = build_decision(ai, "Ravi Kumar", True, True)
    return decision, status, {r.code for r in remarks}


def test_both_fit_approved():
    assert _decide("FIT", "FIT")[0] == "APPROVED"


def test_both_unfit_rejected():
    decision, status, codes = _decide("UNFIT", "UNFIT")
    assert decision == "REJECTED"
    assert "MEDICAL_STATUS_UNFIT" in codes


def test_certificate_fit_pef_unfit_is_rejected():
    # PEF says UNFIT → hard failure regardless of certificate → REJECTED
    decision, status, codes = _decide("FIT", "UNFIT")
    assert decision == "REJECTED"
    assert "MEDICAL_STATUS_UNFIT" in codes


def test_certificate_unfit_pef_fit_is_conflict():
    # Certificate says UNFIT but PEF says FIT → unusual, needs manual review
    decision, status, codes = _decide("UNFIT", "FIT")
    assert decision == "MANUAL_REVIEW_REQUIRED"
    assert "STATUS_CONFLICT" in codes


def test_recommendation_needs_review():
    assert _decide("FIT_WITH_RECOMMENDATION", "FIT")[0] == "APPROVED_WITH_REVIEW"


def test_missing_physician_rejected():
    decision, status, codes = _decide("FIT", "FIT", doctor=False)
    assert decision == "REJECTED"
    assert "MISSING_PHYSICIAN_STAMP" in codes


def test_combine_statuses():
    # PEF UNFIT + cert FIT → PEF_UNFIT conflict type
    assert combine_statuses("FIT", "UNFIT") == ("UNFIT", "PEF_UNFIT")
    # cert UNFIT + PEF FIT → CERT_UNFIT conflict type
    assert combine_statuses("UNFIT", "FIT") == ("UNFIT", "CERT_UNFIT")
    # both FIT → no conflict
    assert combine_statuses("FIT", "FIT") == ("FIT", None)
    # PEF not found → no conflict
    assert combine_statuses("FIT", "NOT_FOUND") == ("FIT", None)


def test_names_match():
    assert names_match("Ravi Kumar", "Mr. Ravi Kumar") is True
    assert names_match("Ravi Kumar", "Sunil Mehta") is False


def test_normalize_medical_status():
    assert normalize_medical_status("Fit") == "FIT"
    assert normalize_medical_status("Unfit") == "UNFIT"
    assert normalize_medical_status("") == "UNKNOWN"


def test_certificate_validity():
    today = datetime.now().strftime("%d-%m-%Y")
    old = (datetime.now() - timedelta(days=400)).strftime("%d-%m-%Y")
    future = (datetime.now() + timedelta(days=30)).strftime("%d-%m-%Y")
    assert is_certificate_valid(today) is True
    assert is_certificate_valid(old) is False
    assert is_certificate_valid(future) is False
    assert is_certificate_valid("garbage") is False


def test_missing_candidate_photo_needs_review():
    decision, status, codes = _decide("FIT", "FIT", photo=False)
    assert decision == "MANUAL_REVIEW_REQUIRED"
    assert "MISSING_CANDIDATE_PHOTO" in codes


def test_photo_present_but_not_stamped_needs_review():
    decision, status, codes = _decide("FIT", "FIT", photo_stamped=False)
    assert decision == "MANUAL_REVIEW_REQUIRED"
    assert "PHOTO_NOT_STAMPED" in codes
