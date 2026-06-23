"""
Optional API-key authentication.

If API_KEY is set in the environment, every protected request must include a
matching "X-API-Key" header. If API_KEY is empty, the API stays open - handy
for local development and the bundled web UI.
"""

from fastapi import Header, HTTPException

from app import config


def require_api_key(x_api_key: str = Header(default="")):
    """Allow the request only when the API is open or the right key is sent."""
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
