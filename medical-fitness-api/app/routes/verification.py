"""
API routes.

- GET  /              -> the web UI (index.html)
- GET  /health        -> simple status check
- POST /api/v1/verify -> verify a medical certificate
"""

import asyncio
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import config
from app.schemas import VerificationResponse, VerificationResult
from app.security import require_api_key
from app.services.audit import utcnow_iso, write_audit_log
from app.services.gemini import analyze_with_gemini
from app.services.pdf import build_pdf_for_vision
from app.services.rules import (
    build_decision,
    is_certificate_valid,
    names_match,
    normalize_medical_status,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
def home():
    """Serve the single-page web UI."""
    return FileResponse(config.TEMPLATE_FILE)


@router.get("/health")
def health_check():
    """Quick health check - also shows which model is configured."""
    return {
        "status": "ok",
        "timestamp": utcnow_iso(),
        "model": config.GEMINI_MODEL,
        "max_pages": config.MAX_PDF_PAGES,
    }


@router.post(
    "/api/v1/verify",
    response_model=VerificationResponse,
    dependencies=[Depends(require_api_key)],
)
async def verify_medical_certificate(
    # Sent in the form body (not the URL) so personal data stays out of logs.
    candidate_name: str = Form(..., min_length=2, max_length=100),
    employee_id: Optional[str] = Form(None, max_length=50),
    file: UploadFile = File(...),
):
    """Verify a candidate's medical fitness certificate from a PDF upload."""
    request_id = str(uuid.uuid4())
    verified_at = utcnow_iso()
    logger.info(f"[{request_id}] Request for: '{candidate_name}'")

    # 1) Basic file checks.
    filename = file.filename or "upload.pdf"
    ext = os.path.splitext(filename)[-1].lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Only PDF files are accepted. Got: '{ext}'")

    # Reject oversized files early, before reading them into memory.
    if file.size and file.size > config.MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {config.MAX_FILE_SIZE_MB}MB.")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > config.MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {config.MAX_FILE_SIZE_MB}MB.")

    # 2) Ask Gemini to read the first few pages (processed in memory).
    pdf_bytes = build_pdf_for_vision(content)
    ai_data, gemini_tokens = await analyze_with_gemini(pdf_bytes, candidate_name)

    # 3) Run our business rules on what Gemini returned.
    certificate_valid = is_certificate_valid(ai_data.get("certificate_date", ""))
    name_matched = names_match(candidate_name, ai_data.get("candidate_name_on_document", ""))
    certificate_status = normalize_medical_status(ai_data.get("certificate_status", ""))
    pef_status = normalize_medical_status(ai_data.get("pef_status", ""))
    final_decision, remarks, medical_status = build_decision(
        ai_data=ai_data,
        candidate_name_on_form=candidate_name,
        certificate_valid=certificate_valid,
        name_matched=name_matched,
    )
    logger.info(f"[{request_id}] Decision: {final_decision} (status: {medical_status})")

    # 4) Save an audit record (in a thread so file I/O does not block).
    await asyncio.to_thread(write_audit_log, {
        "timestamp": verified_at,
        "request_id": request_id,
        "candidate_name": candidate_name,
        "employee_id": employee_id,
        "filename": filename,
        "final_decision": final_decision,
        "medical_status": medical_status,
        "certificate_status": certificate_status,
        "pef_status": pef_status,
        "name_match": name_matched,
        "certificate_valid": certificate_valid,
        "doctor_present": bool(ai_data.get("doctor_present")),
        "ophtha_present": bool(ai_data.get("ophthalmologist_present")),
        "gemini_tokens": gemini_tokens,
        "remarks": [r.code for r in remarks],
    })

    # 5) Build and return the response.
    return VerificationResponse(
        request_id=request_id,
        filename=filename,
        employee_id=employee_id,
        gemini_tokens=gemini_tokens,
        verification_result=VerificationResult(
            candidate_name_on_form=candidate_name,
            candidate_name_on_document=ai_data.get("candidate_name_on_document") or None,
            name_match=name_matched,
            doctor_name=ai_data.get("doctor_name") or None,
            ophthalmologist_name=ai_data.get("ophthalmologist_name") or None,
            certificate_date=ai_data.get("certificate_date") or None,
            certificate_valid=certificate_valid,
            doctor_present=bool(ai_data.get("doctor_present", False)),
            ophthalmologist_present=bool(ai_data.get("ophthalmologist_present", False)),
            certificate_status=certificate_status,
            pef_status=pef_status,
            medical_status=medical_status,
            final_decision=final_decision,
            remarks=remarks,
            verified_at=verified_at,
        ),
    )
