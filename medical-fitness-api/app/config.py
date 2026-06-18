"""All settings, read from environment variables (.env) with safe defaults."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # read .env

# Project root, so file paths work no matter where the server is started.
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Upload rules ---
ALLOWED_EXTENSIONS = {".pdf"}
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", 10))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_PDF_PAGES = int(os.environ.get("MAX_PDF_PAGES", 5))

# --- Verification rules ---
CERTIFICATE_VALIDITY_DAYS = int(os.environ.get("CERTIFICATE_VALIDITY_DAYS", 180))
NAME_MATCH_THRESHOLD = int(os.environ.get("NAME_MATCH_THRESHOLD", 75))
VALID_STATUSES = {"FIT", "UNFIT", "FIT_WITH_RECOMMENDATION"}

# --- Google Gemini ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", 1024))
GEMINI_THINKING_BUDGET = int(os.environ.get("GEMINI_THINKING_BUDGET", 0))

# --- File locations ---
AUDIT_LOG_FILE = str(BASE_DIR / "audit.log")
TEMPLATE_FILE = str(BASE_DIR / "templates" / "index.html")
