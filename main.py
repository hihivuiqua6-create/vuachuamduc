"""Entrypoint. Chạy: uvicorn main:app --host 0.0.0.0 --port $PORT"""
import os
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api import api as api_router
from src.telegram_bot import start_bot_if_configured

app = FastAPI(title="TienBuff", version="3.0.0")
app.mount("/api", api_router)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.on_event("startup")
def _startup():
    # Nếu admin đã lưu token bot từ trước, tự bật lại polling.
    try:
        start_bot_if_configured()
    except Exception as e:
        print("[bot startup]", e, flush=True)


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")