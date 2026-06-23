"""API tests using FastAPI's TestClient (no real AI calls)."""

from fastapi.testclient import TestClient

from app import config
import main

client = TestClient(main.app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_verify_rejects_non_pdf():
    files = {"file": ("note.txt", b"hello", "text/plain")}
    r = client.post("/api/v1/verify", data={"candidate_name": "Ravi Kumar"}, files=files)
    assert r.status_code == 400


def test_verify_rejects_short_name():
    files = {"file": ("c.pdf", b"%PDF-1.4", "application/pdf")}
    r = client.post("/api/v1/verify", data={"candidate_name": "A"}, files=files)
    assert r.status_code == 422


def test_api_key_enforced(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "secret123")
    files = {"file": ("note.txt", b"hello", "text/plain")}
    blocked = client.post("/api/v1/verify", data={"candidate_name": "Ravi Kumar"}, files=files)
    assert blocked.status_code == 401
    allowed = client.post(
        "/api/v1/verify",
        data={"candidate_name": "Ravi Kumar"},
        files=files,
        headers={"X-API-Key": "secret123"},
    )
    assert allowed.status_code == 400  # passes auth, then fails on non-PDF
