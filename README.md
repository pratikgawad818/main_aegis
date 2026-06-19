# MedVerify - Medical Fitness Verification API

AI-powered tool that verifies a candidate's medical fitness certificate (PDF).
It uses Google Gemini's vision to read the document, including stamps and
signatures, and returns a clear verdict (APPROVED / REJECTED) with the reasons.

Built with **FastAPI (Python)** and **Google Gemini**.

## What it checks

- Candidate name matches the name on the certificate (fuzzy match)
- Certificate is recent (within 6 months) and not future-dated
- General Physician stamp / signature is present
- Ophthalmologist stamp / signature is present
- Medical status: FIT / UNFIT / FIT_WITH_RECOMMENDATION

## How to run

The application lives in the [`medical-fitness-api/`](medical-fitness-api/) folder.

```bash
cd medical-fitness-api
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then add your GEMINI_API_KEY
uvicorn main:app --reload
```

Then open http://127.0.0.1:8000 in your browser.

Full documentation: [medical-fitness-api/README.md](medical-fitness-api/README.md)
