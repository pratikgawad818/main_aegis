# Aegis - Medical Fitness Verification API

Upload a candidate's medical certificate (PDF) and get an instant, structured
"fit / unfit" verdict. Powered by Google Gemini, which reads the document
visually so it can pick up stamps and signatures even on scanned pages.

Built with **FastAPI (Python)** and **Google Gemini**.

> The project lives in the [`aegis-certificate-verification/`](aegis-certificate-verification/) folder - run the commands below from there.

## What it checks

- Candidate name matches the name on the certificate (fuzzy match)
- Certificate is recent (within 6 months) and not future-dated
- General Physician stamp / signature is present
- Ophthalmologist (eye doctor) stamp / signature is present
- Candidate photo on the pre-employment form, stamped by the doctor
- Medical status from the certificate AND the pre-employment form (conflicts are flagged)

## Requirements

- Python 3.10+ (also runs on 3.9)
- A Google Gemini API key - get one free at https://aistudio.google.com/apikey

## Setup

```bash
cd aegis-certificate-verification
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then put your GEMINI_API_KEY in .env
uvicorn main:app --reload
```

Open http://127.0.0.1:8000 in your browser.

## Project structure

```
aegis-certificate-verification/
├── main.py                  # starts the app, adds CORS, includes routes
├── app/
│   ├── config.py            # all settings (read from .env)
│   ├── schemas.py           # request / response models
│   ├── security.py          # optional API-key auth
│   ├── routes/
│   │   └── verification.py  # the API endpoints
│   └── services/
│       ├── pdf.py           # keep the first pages of the PDF
│       ├── gemini.py        # call Gemini and parse its JSON
│       ├── rules.py         # date / name / decision checks
│       └── audit.py         # write the audit log
├── integrations/            # Gmail bot (email in -> verdict out)
├── templates/index.html     # web UI
├── tests/                   # pytest suite
├── requirements.txt
└── .env.example
```

## How it works

1. The PDF is received and its first few pages are kept (in memory).
2. Those pages are sent to Gemini, which returns the details as JSON.
3. Plain Python rules (`app/services/rules.py`) turn that into a decision.
4. The result is returned as JSON and recorded in `audit.log`.

## API

`POST /api/v1/verify` - multipart form:

| Field | Required | Description |
|---|---|---|
| `candidate_name` | yes | Full name from the application form |
| `file` | yes | The certificate PDF |

`GET /health` - status and the configured model.

Possible decisions: `APPROVED`, `APPROVED_WITH_REVIEW`, `REJECTED`, `MANUAL_REVIEW_REQUIRED`.

## Integrate into another app

Call the API from any system (HRMS / ATS, a script, etc.):

1. Set `API_KEY=your-secret-key` in `.env` and restart. (Empty = open, no key needed.)
2. Send the key as an `X-API-Key` header on each request.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/verify \
  -H "X-API-Key: your-secret-key" \
  -F "candidate_name=Ayan Panja" \
  -F "file=@certificate.pdf"
```

```python
import requests
resp = requests.post(
    "http://127.0.0.1:8000/api/v1/verify",
    headers={"X-API-Key": "your-secret-key"},
    data={"candidate_name": "Ayan Panja"},
    files={"file": open("certificate.pdf", "rb")},
)
print(resp.json()["verification_result"]["final_decision"])
```

## Gmail integration (optional)

Turn an inbox into a verification service: someone emails the candidate's name
plus the certificate PDF, and the result is emailed back automatically.

```
email in  ->  integrations/gmail_worker.py  ->  Aegis API  ->  email reply
```

The request email: **subject** = candidate's full name (or a `Name: ...` line in the body), with the certificate **PDF attached**.

1. Turn on 2-Step Verification on the Gmail account, then create an
   **App Password** (Google Account -> Security -> App passwords).
2. Add to `.env`:
   ```
   GMAIL_ADDRESS=hr-verify@gmail.com
   GMAIL_APP_PASSWORD=your-app-password
   ALLOWED_SENDERS=yourcompany.com
   ```
3. Run the worker next to the API:
   ```bash
   pip install -r integrations/requirements.txt
   python integrations/gmail_worker.py
   ```

Set `ALLOWED_SENDERS` so only trusted senders can get medical results back.

## Configuration (.env)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | - | Your Gemini key (required) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model to use |
| `GEMINI_THINKING_BUDGET` | `0` | 0 = off (cheaper); raise for harder docs |
| `GEMINI_TIMEOUT_SECONDS` | `60` | Max seconds to wait for Gemini |
| `MAX_PDF_PAGES` | `5` | Pages sent to the model |
| `MAX_FILE_SIZE_MB` | `10` | Max upload size |
| `CERTIFICATE_VALIDITY_DAYS` | `180` | How recent the certificate must be |
| `NAME_MATCH_THRESHOLD` | `75` | Name match score needed (0-100) |
| `API_KEY` | (empty) | If set, callers must send `X-API-Key`. Empty = open |
| `CORS_ORIGINS` | localhost | Comma-separated browser origins allowed |

## Tests

```bash
cd aegis-certificate-verification
pip install -r requirements-dev.txt
pytest
```

## Notes

- Certificates are processed in memory and never saved to disk.
- `.env` and `audit.log` hold sensitive data - they are git-ignored.
- Each scan uses roughly 1,000-2,000 Gemini tokens.
- AI-assisted screening - the final hiring decision stays with your HR team.
