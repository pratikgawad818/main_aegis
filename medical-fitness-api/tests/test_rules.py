"""Unit tests for the business rules (no AI, no network)."""

from datetime import datetime, timedelta

from app.services.rules import (
    build_decision,
    combine_statuses,
    is_certificate_valid,
    names_match,
    normalize_medical_status,
)


def _decide(cert, pef, doctor=True, ophth=True):
    ai = {
        "certificate_status": cert,
        "pef_status": pef,
        "doctor_present": doctor,
        "ophthalmologist_present": ophth,
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


def test_certificate_fit_pef_unfit_is_conflict():
    decision, status, codes = _decide("FIT", "UNFIT")
    assert decision == "MANUAL_REVIEW_REQUIRED"
    assert "STATUS_CONFLICT" in codes


def test_recommendation_needs_review():
    assert _decide("FIT_WITH_RECOMMENDATION", "FIT")[0] == "APPROVED_WITH_REVIEW"


def test_missing_physician_rejected():
    decision, status, codes = _decide("FIT", "FIT", doctor=False)
    assert decision == "REJECTED"
    assert "MISSING_PHYSICIAN_STAMP" in codes


def test_combine_statuses():
    assert combine_statuses("FIT", "UNFIT") == ("UNFIT", True)
    assert combine_statuses("FIT", "FIT") == ("FIT", False)
    assert combine_statuses("FIT", "NOT_FOUND") == ("FIT", False)


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
