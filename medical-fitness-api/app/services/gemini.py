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
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# The instruction we send to Gemini. The candidate name is added separately
# (in analyze_with_gemini) so this stays a plain, easy-to-read string.
PROMPT = """You are a Medical Fitness Certificate Verification System.

Carefully examine the attached medical certificate document (it may be scanned
images). Read the printed text AND look closely at stamps, round seals,
signatures and handwriting - important details are often inside stamps.

RULES:

1. certificate_date: the MAIN certificate date only. Ignore blood test / lab /
   sample collection dates. Look near "TO WHOMSOEVER IT MAY CONCERN", the
   doctor's signature, or "Date:".

2. medical_status must be EXACTLY one of: FIT | UNFIT | FIT_WITH_RECOMMENDATION

3. doctor_present: true if a General Physician / MBBS / MD signature or stamp
   is visible. doctor_name: that doctor's full name, or "" if not found.

4. ophthalmologist_present / ophthalmologist_name: look for a SECOND doctor
   anywhere (including inside stamps/seals) - an eye specialist, an "Eye
   Fitness" / "Vision Test" section, a second stamp, or any eye examination
   signed by a doctor. Set true if any such second doctor or section exists.

5. candidate_name_on_document: the exact name printed on the certificate.

6. remarks: only real medical findings or notes. Do NOT invent remarks and do
   NOT add remarks about missing stamps.

Return ONLY this JSON, no markdown:
{
    "candidate_name_on_document": "",
    "doctor_name": "",
    "ophthalmologist_name": "",
    "certificate_date": "",
    "medical_status": "",
    "doctor_present": true,
    "ophthalmologist_present": true,
    "remarks": []
}
"""


def _call_gemini(pdf_bytes: bytes, prompt: str) -> tuple[str, int]:
    """
    Low-level blocking Gemini call. Sends the prompt + PDF document and
    returns (response_text, total_tokens). Meant to be run inside a thread.
    """
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
    response = client.models.generate_content(
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
        logger.error(f"Gemini API error: {e}")
        raise HTTPException(status_code=503, detail="The AI service returned an error. Please try again shortly.")
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        raise HTTPException(status_code=503, detail="Could not reach the AI service. Please try again shortly.")

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
