"""Send the certificate PDF to Gemini and get the extracted fields back as JSON.

Thinking is off by default to keep token usage low (see GEMINI_THINKING_BUDGET).
"""

import asyncio
import json
import logging

from fastapi import HTTPException
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import (
    GEMINI_API_KEY,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
    GEMINI_THINKING_BUDGET,
    GEMINI_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is not set. Set it before verifying (e.g. in .env).")

# The client is created on first use (not at import) so the app still starts
# even without a key - you only get an error when you actually verify a document.
_client = None


def _get_client():
    global _client
    if _client is None:
        # http timeout (ms) so a hung Gemini request can't block forever.
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SECONDS * 1000),
        )
    return _client


# The instruction we send to Gemini. The candidate name is added separately
# (in analyze_with_gemini) so this stays a plain, easy-to-read string.
PROMPT = """You are a Medical Fitness Certificate Verification System.

You are given a candidate's medical document (often scanned images, up to a few
pages). It usually contains TWO parts you must check SEPARATELY:
  A) the Fitness Certificate - often a "TO WHOMSOEVER IT MAY CONCERN" letter
  B) the Pre-Employment Form (PEF) - a detailed medical examination report

Read the printed text AND look closely at stamps, seals, signatures and
handwriting across ALL pages. Important details are often inside stamps or on
later pages (the certificate and the PEF can be on different pages).

Fields to return:

1. certificate_date: the MAIN certificate date only. Ignore blood test / lab /
   sample collection dates.

2. certificate_status: the fitness verdict on the Fitness Certificate (A).
   EXACTLY one of: FIT | UNFIT | FIT_WITH_RECOMMENDATION | NOT_FOUND

3. pef_status: the fitness verdict / conclusion on the Pre-Employment Form or
   medical examination (B). EXACTLY one of:
   FIT | UNFIT | FIT_WITH_RECOMMENDATION | NOT_FOUND
   Use NOT_FOUND if there is no separate examination form.

4. doctor_present / doctor_name: true and the name if a General Physician
   (MBBS/MD) signature or stamp is visible.

5. ophthalmologist_present / ophthalmologist_name: look for a SECOND doctor or
   eye test anywhere (eye specialist, "Eye Fitness" / "Vision Test", a second
   stamp). true if any such second doctor or section exists.

6. candidate_name_on_document: the exact name printed on the document.

7. candidate_photo_present: true if a passport-style PHOTOGRAPH of the candidate
   appears on the document (usually pasted on the Pre-Employment Form).

8. photo_stamped: true ONLY if a doctor's stamp or seal is placed ON / across
   that photograph (the stamp overlaps the photo - a common anti-fraud measure).
   false if the photo has no stamp on it, or if there is no photo.

9. remarks: only real medical findings or notes (defects, conditions, advice).
   Do NOT invent remarks and do NOT add remarks about missing stamps.

Return ONLY this JSON, no markdown:
{
    "candidate_name_on_document": "",
    "doctor_name": "",
    "ophthalmologist_name": "",
    "certificate_date": "",
    "certificate_status": "",
    "pef_status": "",
    "doctor_present": true,
    "ophthalmologist_present": true,
    "candidate_photo_present": true,
    "photo_stamped": true,
    "remarks": []
}
"""


def _call_gemini(pdf_bytes: bytes, prompt: str) -> tuple[str, int]:
    """
    Low-level blocking Gemini call. Sends the prompt + PDF document and
    returns (response_text, total_tokens). Meant to be run inside a thread.
    """
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
    response = _get_client().models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt, pdf_part],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_budget=GEMINI_THINKING_BUDGET),
        ),
    )
    tokens = 0
    usage = getattr(response, "usage_metadata", None)
    if usage:
        tokens = usage.total_token_count or 0
        logger.info(f"Gemini tokens used: {tokens}")
    return (response.text or ""), tokens


async def analyze_with_gemini(pdf_bytes: bytes, candidate_name_on_form: str) -> tuple[dict, int]:
    """
    Ask Gemini to read the certificate and return (extracted_data, tokens).
    The blocking call runs in a thread so the server stays responsive.
    """
    prompt = (
        f'Candidate name provided on the application form: "{candidate_name_on_form}"\n\n'
        + PROMPT
    )

    try:
        raw, tokens = await asyncio.to_thread(_call_gemini, pdf_bytes, prompt)
    except genai_errors.APIError as e:
        code = getattr(e, "code", None)
        logger.error(f"Gemini API error ({code}): {e}")
        if code == 429:
            raise HTTPException(status_code=429, detail="AI rate limit or quota exceeded. Wait a moment and try again, or check your Gemini plan.")
        if code in (401, 403):
            raise HTTPException(status_code=502, detail="AI authentication failed. Check the server's GEMINI_API_KEY.")
        raise HTTPException(status_code=502, detail="The AI service returned an error. Please try again shortly.")
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        raise HTTPException(status_code=504, detail="The AI service timed out or was unreachable. Please try again.")

    # Gemini returns JSON text; pull out the {...} part and parse it.
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON found")
        return json.loads(raw[start:end]), tokens
    except Exception:
        logger.error(f"Gemini returned invalid JSON: {raw}")
        raise HTTPException(status_code=500, detail="AI returned an unexpected response. Please try again.")
