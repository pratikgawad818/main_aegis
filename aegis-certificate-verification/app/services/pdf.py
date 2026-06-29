"""PDF handling: turn an uploaded PDF into its first few pages, in memory."""

import logging

import fitz  # PyMuPDF

from fastapi import HTTPException

from app.config import MAX_PDF_PAGES

logger = logging.getLogger(__name__)


def build_pdf_for_vision(pdf_bytes: bytes) -> bytes:
    """
    Keep only the first MAX_PDF_PAGES pages and return them as PDF bytes.

    These pages are sent to Gemini as a document (images) so the model can
    SEE stamps, seals and signatures. Plain text extraction would miss them.
    Everything happens in memory - the upload is never written to disk.
    """
    try:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"PDF open failed: {e}")
        raise HTTPException(status_code=400, detail="Could not read PDF. The file may be corrupted or not a valid PDF.")

    try:
        if src.needs_pass:
            raise HTTPException(status_code=400, detail="Password-protected PDFs are not supported.")
        total = src.page_count
        if total == 0:
            raise HTTPException(status_code=400, detail="The PDF has no pages.")
        pages = min(total, MAX_PDF_PAGES)
        out = fitz.open()
        out.insert_pdf(src, from_page=0, to_page=pages - 1)
        data = out.tobytes()
        out.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PDF processing failed: {e}")
        raise HTTPException(status_code=400, detail="Could not process the PDF file.")
    finally:
        src.close()

    logger.info(f"Prepared {pages} of {total} page(s) for vision analysis")
    return data
