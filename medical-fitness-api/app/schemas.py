"""Request and response models. FastAPI uses them to validate and document the API."""

from typing import Optional

from pydantic import BaseModel


class Remark(BaseModel):
    """A single note or flag about the certificate."""
    code: str
    message: str


class VerificationResult(BaseModel):
    """The detailed result of checking one certificate."""
    candidate_name_on_form: Optional[str] = None
    candidate_name_on_document: Optional[str] = None
    name_match: bool
    doctor_name: Optional[str] = None
    ophthalmologist_name: Optional[str] = None
    certificate_date: Optional[str] = None
    certificate_valid: bool
    doctor_present: bool
    ophthalmologist_present: bool
    candidate_photo_present: bool = False
    photo_stamped: bool = False
    certificate_status: Optional[str] = None
    pef_status: Optional[str] = None
    medical_status: str
    final_decision: str
    remarks: list[Remark]
    verified_at: str


class VerificationResponse(BaseModel):
    """The full response returned by the verify endpoint."""
    request_id: str
    filename: str
    employee_id: Optional[str] = None
    gemini_tokens: Optional[int] = None
    verification_result: VerificationResult
