"""Entrypoint. Chạy: uvicorn main:app --host 0.0.0.0 --port $PORT"""
import os
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api import api as api_router

app = FastAPI(title="TienBuff", version="2.0.0")

# Mount API dưới /api
app.mount("/api", api_router)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Static assets (nếu sau này có thêm)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
