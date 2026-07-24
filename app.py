"""
TIENDEV Buff API — FastAPI wrapper cho buff_core (logic từ buff.py).

- Không cần cookie / user-agent do người dùng nhập: session tự lấy từ Zefoy.
- Có endpoint tự giải captcha (OCR) hoặc trả ảnh base64 để user nhập tay.
- Toàn bộ state trong RAM theo session_id (đủ dùng 1 instance Render free).
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.buff_core import (
    do_buff_once,
    get_captcha,
    get_service_form,
    get_services,
    new_session,
    submit_captcha,
)
from app.ocr_solver import solve_captcha_image

app = FastAPI(title="TIENDEV Buff API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS: dict[str, dict[str, Any]] = {}
TTL = 60 * 30


def _new_state() -> dict[str, Any]:
    return {
        "session": new_session(),
        "created": time.time(),
        "last": time.time(),
        "form_data": {},
        "captcha_url": None,
        "captcha_b64": None,
        "services": [],
        "home_html": "",
        "total_sent": 0,
        "logged_in": False,
    }


def _gc() -> None:
    now = time.time()
    for k in [k for k, v in SESSIONS.items() if now - v["last"] > TTL]:
        SESSIONS.pop(k, None)


def _get(sid: str) -> dict[str, Any]:
    _gc()
    st = SESSIONS.get(sid)
    if not st:
        raise HTTPException(404, "Session hết hạn hoặc chưa tạo — bấm 'Bắt đầu' lại.")
    st["last"] = time.time()
    return st


def _serialize_services(st: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": s["name"],
            "status": s["status"],
            "active": s["active"],
            "menu_class": s["menu_class"],
        }
        for s in st.get("services", [])
    ]


def _load_captcha(st: dict[str, Any]) -> None:
    url, form_data, img = get_captcha(st["session"])
    if url is None and not img:
        # có thể đã đăng nhập rồi
        st["logged_in"] = True
        st["captcha_url"] = None
        st["captcha_b64"] = None
        st["form_data"] = {}
        return
    st["captcha_url"] = url
    st["form_data"] = form_data or {}
    st["captcha_b64"] = base64.b64encode(img).decode("ascii") if img else None
    st["logged_in"] = False


def _refresh_services(st: dict[str, Any]) -> None:
    services, home_html = get_services(st["session"])
    st["services"] = services
    st["home_html"] = home_html


# ─────────── models ───────────
class Empty(BaseModel):
    pass


class Sid(BaseModel):
    session_id: str


class SolveReq(BaseModel):
    session_id: str
    answer: str | None = None  # nếu bỏ trống -> server tự giải bằng OCR


class RunReq(BaseModel):
    session_id: str
    service: str  # name của dịch vụ
    url: str


# ─────────── routes ───────────
@app.exception_handler(Exception)
async def _all_ex(_req, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": type(exc).__name__, "message": str(exc) or "unknown"},
    )


@app.post("/api/start")
def api_start(_: Empty = Empty()):
    sid = uuid.uuid4().hex
    st = _new_state()
    _load_captcha(st)
    if st["logged_in"]:
        _refresh_services(st)
    SESSIONS[sid] = st
    return {
        "session_id": sid,
        "logged_in": st["logged_in"],
        "captcha_b64": st["captcha_b64"],
        "services": _serialize_services(st) if st["logged_in"] else [],
    }


@app.post("/api/refresh_captcha")
def api_refresh_captcha(req: Sid):
    st = _get(req.session_id)
    _load_captcha(st)
    return {"captcha_b64": st["captcha_b64"], "logged_in": st["logged_in"]}


@app.post("/api/auto_solve")
def api_auto_solve(req: Sid):
    """Tự giải captcha bằng OCR rồi submit luôn. Trả kết quả tương tự /api/solve."""
    st = _get(req.session_id)
    if not st.get("captcha_b64"):
        _load_captcha(st)
    if st["logged_in"]:
        _refresh_services(st)
        return {"ok": True, "auto": True, "answer": "", "services": _serialize_services(st)}

    if not st.get("captcha_b64"):
        raise HTTPException(500, "Không tải được ảnh captcha")
    img = base64.b64decode(st["captcha_b64"])
    try:
        answer = solve_captcha_image(img)
    except Exception as e:
        # OCR fail -> reload ảnh mới, báo cho client
        _load_captcha(st)
        return {
            "ok": False,
            "auto": True,
            "message": f"OCR không giải được ({e}). Nhập tay hoặc thử lại.",
            "captcha_b64": st.get("captcha_b64"),
        }

    ok = submit_captcha(st["session"], answer, st["form_data"])
    if not ok:
        _load_captcha(st)
        return {
            "ok": False,
            "auto": True,
            "answer": answer,
            "message": f"OCR đoán '{answer}' — Zefoy báo sai. Đã tải ảnh mới.",
            "captcha_b64": st.get("captcha_b64"),
        }
    st["logged_in"] = True
    _refresh_services(st)
    return {
        "ok": True,
        "auto": True,
        "answer": answer,
        "services": _serialize_services(st),
    }


@app.post("/api/solve")
def api_solve(req: SolveReq):
    st = _get(req.session_id)
    if not (req.answer or "").strip():
        raise HTTPException(400, "Thiếu 'answer'. Dùng /api/auto_solve nếu muốn tự giải.")
    ok = submit_captcha(st["session"], req.answer, st["form_data"])
    if not ok:
        _load_captcha(st)
        return {
            "ok": False,
            "message": "Captcha sai, đã tải ảnh mới.",
            "captcha_b64": st.get("captcha_b64"),
        }
    st["logged_in"] = True
    _refresh_services(st)
    return {"ok": True, "services": _serialize_services(st)}


@app.post("/api/services")
def api_services(req: Sid):
    st = _get(req.session_id)
    if not st["logged_in"]:
        raise HTTPException(401, "Chưa giải captcha")
    _refresh_services(st)
    return {"services": _serialize_services(st), "total_sent": st.get("total_sent", 0)}


@app.post("/api/run")
def api_run(req: RunReq):
    st = _get(req.session_id)
    if not st["logged_in"]:
        raise HTTPException(401, "Chưa giải captcha")
    if not st.get("home_html"):
        _refresh_services(st)

    svc = next((s for s in st["services"] if s["name"] == req.service), None)
    if not svc:
        raise HTTPException(404, f"Không có dịch vụ: {req.service}")
    if not svc["active"]:
        return {"status": "error", "message": f"{req.service} đang OFF/bảo trì"}

    form = get_service_form(st["home_html"], svc["menu_class"])
    if not form or not form.get("action") or not form.get("input_name"):
        raise HTTPException(500, f"Không lấy được form cho {req.service}")
    action_url = f"https://zefoy.com/{form['action']}"

    result = do_buff_once(st["session"], action_url, form["input_name"], req.url)
    if result.get("status") == "ok" and result.get("amount"):
        st["total_sent"] += int(result["amount"])
    result["total_sent"] = st.get("total_sent", 0)
    result["service"] = req.service
    return result


# ─────────── static UI ───────────
_STATIC = os.path.join(os.path.dirname(__file__), "static")


@app.get("/")
def root():
    idx = os.path.join(_STATIC, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return {"ok": True, "msg": "TIENDEV Buff API"}


@app.get("/health")
def health():
    return {"ok": True, "sessions": len(SESSIONS), "ts": int(time.time())}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))