"""MedVerify entry point: create the app, add CORS, include the routes.

Run with: uvicorn main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.verification import router

app = FastAPI(
    title="Medical Fitness Verification API",
    description="AI-powered medical certificate verification for HR teams.",
    version="1.0.0",
)

# Allow the local web UI to call the API. Tighten these origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# All endpoints live in app/routes/verification.py
app.include_router(router)
