# MedVerify - Medical Fitness Verification API

Upload a candidate's medical certificate (PDF) and get an instant, structured
"fit / unfit" verdict. Powered by Google Gemini, which reads the document
visually so it can pick up stamps and signatures even on scanned pages.

## What it checks

- Name on the form matches the name on the certificate (fuzzy match)
- Certificate is recent (within the last 6 months) and not future-dated
- General Physician stamp / signature is present
- Ophthalmologist (eye doctor) stamp / signature is present
- Medical status: FIT / UNFIT / FIT_WITH_RECOMMENDATION

## Requirements

- Python 3.10+ (also runs on 3.9)
- A Google Gemini API key - get one free at https://aistudio.google.com/apikey

## Setup

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then put your GEMINI_API_KEY in .env
uvicorn main:app --reload
```

Open http://127.0.0.1:8000 in your browser.

## Project structure

```
medical-fitness-api/
├── main.py                  # starts the app, adds CORS, includes routes
├── app/
│   ├── config.py            # all settings (read from .env)
│   ├── schemas.py           # request / response models
│   ├── routes/
│   │   └── verification.py  # the API endpoints
│   └── services/
│       ├── pdf.py           # keep the first pages of the PDF
│       ├── gemini.py        # call Gemini and parse its JSON
│       ├── rules.py         # date / name / decision checks
│       └── audit.py         # write the audit log
├── templates/index.html     # web UI
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
| `employee_id` | no | Your internal ID for the candidate |
| `file` | yes | The certificate PDF |

`GET /health` - status and the configured model.

Possible decisions: `APPROVED`, `APPROVED_WITH_REVIEW`, `REJECTED`, `MANUAL_REVIEW_REQUIRED`.

## Configuration (.env)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | - | Your Gemini key (required) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model to use |
| `GEMINI_THINKING_BUDGET` | `0` | 0 = off (cheaper); raise for harder docs |
| `MAX_PDF_PAGES` | `5` | Pages sent to the model |
| `MAX_FILE_SIZE_MB` | `10` | Max upload size |
| `CERTIFICATE_VALIDITY_DAYS` | `180` | How recent the certificate must be |
| `NAME_MATCH_THRESHOLD` | `75` | Name match score needed (0-100) |

## Notes

- Certificates are processed in memory and never saved to disk.
- `audit.log` and `.env` hold sensitive data - they are git-ignored.
- There is no login on the API yet; add authentication before deploying.
- Each scan uses roughly 1,000-2,000 Gemini tokens.
