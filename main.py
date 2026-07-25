"""Deployment entrypoint for Render.

The FastAPI application lives in the flat root module app.py, not an app/ package.
Use: uvicorn main:app --host 0.0.0.0 --port $PORT
"""

from app import app  # noqa: F401
