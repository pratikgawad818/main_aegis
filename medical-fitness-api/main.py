"""Aegis entry point: create the app, add CORS, include the routes.

Run with: uvicorn main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.routes.verification import router

app = FastAPI(
    title="Aegis - Medical Fitness Verification API",
    description="AI-powered medical certificate verification for HR teams.",
    version="1.0.0",
)

# Allow the web UI to call the API. Origins come from CORS_ORIGINS in .env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# All endpoints live in app/routes/verification.py
app.include_router(router)
