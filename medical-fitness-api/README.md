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

## Integrate into another app

To call this API from another system (HRMS / ATS, a script, etc.):

1. Set an API key in `.env`: `API_KEY=your-secret-key` (then restart the server).
2. Send that key on every request as an `X-API-Key` header. If `API_KEY` is empty, the API stays open (no header needed) - handy for local dev.
3. If the caller is a browser on another domain, add that domain to `CORS_ORIGINS` in `.env`.

**curl**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/verify \
  -H "X-API-Key: your-secret-key" \
  -F "candidate_name=Ayan Panja" \
  -F "employee_id=EMP-2026-001" \
  -F "file=@certificate.pdf"
```

**Python**
```python
import requests

resp = requests.post(
    "http://127.0.0.1:8000/api/v1/verify",
    headers={"X-API-Key": "your-secret-key"},
    data={"candidate_name": "Ayan Panja", "employee_id": "EMP-2026-001"},
    files={"file": open("certificate.pdf", "rb")},
)
result = resp.json()["verification_result"]
print(result["final_decision"], result["medical_status"])
```

**JavaScript (fetch)**
```js
const fd = new FormData();
fd.append("candidate_name", "Ayan Panja");
fd.append("file", fileInput.files[0]);

const res = await fetch("http://127.0.0.1:8000/api/v1/verify", {
  method: "POST",
  headers: { "X-API-Key": "your-secret-key" },
  body: fd,
});
const data = await res.json();
```

A missing or wrong key returns `401`. The JSON response includes `final_decision`,
`medical_status`, `certificate_status`, `pef_status`, the doctor and photo checks,
and a `remarks` list explaining any flags.

## Configuration (.env)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | - | Your Gemini key (required) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model to use |
| `GEMINI_THINKING_BUDGET` | `0` | 0 = off (cheaper); raise for harder docs |
| `GEMINI_TIMEOUT_SECONDS` | `60` | Max seconds to wait for a Gemini reply |
| `MAX_PDF_PAGES` | `5` | Pages sent to the model |
| `MAX_FILE_SIZE_MB` | `10` | Max upload size |
| `CERTIFICATE_VALIDITY_DAYS` | `180` | How recent the certificate must be |
| `NAME_MATCH_THRESHOLD` | `75` | Name match score needed (0-100) |
| `API_KEY` | (empty) | If set, callers must send `X-API-Key`. Empty = open |
| `CORS_ORIGINS` | localhost | Comma-separated browser origins allowed |

## Notes

- Certificates are processed in memory and never saved to disk.
- `audit.log` and `.env` hold sensitive data - they are git-ignored.
- Set `API_KEY` in `.env` to require an `X-API-Key` header on the verify endpoint.
- Each scan uses roughly 1,000-2,000 Gemini tokens.
