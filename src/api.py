"""TienBuff API — FastAPI backend.

Auth model:
  - Người ĐĂNG KÝ ĐẦU TIÊN trở thành ADMIN.
  - Sau đó khoá đăng ký, chỉ có thể ĐĂNG NHẬP.
  - Admin quản lý pool cookie + user-agent.
"""
from __future__ import annotations
import time
import traceback

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import storage
from .auth import (
    hash_password, make_token, require_admin, require_user, verify_password,
)
from .zefoy_core import build_session, get_services, run_boost


api = FastAPI(title="TienBuff API", version="2.0.0")
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@api.exception_handler(Exception)
async def _err(request, exc):
    if isinstance(exc, HTTPException):
        raise exc
    print("[UNHANDLED]", traceback.format_exc(), flush=True)
    return JSONResponse({"error": type(exc).__name__, "message": str(exc)}, status_code=500)


# ─────────── models ────────────
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class CookieIn(BaseModel):
    label: str = ""
    cookie_string: str = Field(min_length=10)
    user_agent: str = Field(min_length=10)


class RunIn(BaseModel):
    service: str
    video_url: str = Field(min_length=8)


# ─────────── public ────────────
@api.get("/status")
def status():
    d = storage.read()
    users = d.get("users", [])
    return {
        "has_admin": any(u.get("role") == "admin" for u in users),
        "registration_open": len(users) == 0,
        "user_count": len(users),
        "cookie_count": len(d.get("cookies", [])),
        "active_cookie_count": sum(1 for c in d.get("cookies", []) if c.get("active", True)),
        "stats": d.get("stats", {}),
    }


# ─────────── auth ────────────
@api.post("/register")
def register(inp: RegisterIn):
    d = storage.read()
    users = d.get("users", [])
    if len(users) > 0:
        raise HTTPException(403, "Đăng ký đã đóng. Admin đã được tạo trước đó.")

    def _m(dd):
        dd.setdefault("users", []).append({
            "username": inp.username,
            "password_hash": hash_password(inp.password),
            "role": "admin",  # first user = admin
            "created_at": time.time(),
        })
    storage.write(_m)
    return {"ok": True, "token": make_token(inp.username, "admin"),
            "role": "admin", "username": inp.username}


@api.post("/login")
def login(inp: LoginIn):
    d = storage.read()
    users = d.get("users", [])
    u = next((x for x in users if x["username"] == inp.username), None)
    if not u or not verify_password(inp.password, u["password_hash"]):
        raise HTTPException(401, "Sai tài khoản hoặc mật khẩu")
    role = u.get("role", "user")
    return {"ok": True, "token": make_token(inp.username, role),
            "role": role, "username": inp.username}


@api.get("/me")
def me(claims: dict = Depends(require_user)):
    return {"username": claims["sub"], "role": claims.get("role", "user")}


# ─────────── admin: cookies ────────────
@api.get("/admin/cookies")
def list_cookies(_: dict = Depends(require_admin)):
    d = storage.read()
    out = []
    for c in d["cookies"]:
        cs = c["cookie_string"]
        out.append({
            "id": c["id"], "label": c["label"], "active": c.get("active", True),
            "created_at": c.get("created_at"), "last_used": c.get("last_used", 0),
            "user_agent": c["user_agent"],
            "cookie_preview": (cs[:40] + "…" + cs[-20:]) if len(cs) > 65 else cs,
        })
    return {"cookies": out}


@api.post("/admin/cookies")
def add_cookie(inp: CookieIn, _: dict = Depends(require_admin)):
    entry = storage.add_cookie(inp.label, inp.cookie_string, inp.user_agent)
    return {"ok": True, "id": entry["id"]}


@api.delete("/admin/cookies/{cid}")
def del_cookie(cid: str, _: dict = Depends(require_admin)):
    if not storage.delete_cookie(cid):
        raise HTTPException(404, "Không tìm thấy cookie")
    return {"ok": True}


@api.post("/admin/cookies/{cid}/toggle")
def toggle_cookie(cid: str, _: dict = Depends(require_admin)):
    if not storage.toggle_cookie(cid):
        raise HTTPException(404, "Không tìm thấy cookie")
    return {"ok": True}


@api.get("/admin/history")
def history(_: dict = Depends(require_admin)):
    d = storage.read()
    return {"history": d.get("history", [])[:100], "stats": d.get("stats", {})}


@api.delete("/admin/reset-users")
def reset_users(_: dict = Depends(require_admin)):
    def _m(d):
        d["users"] = []
    storage.write(_m)
    return {"ok": True, "message": "Đã reset. Người đăng ký kế tiếp sẽ là admin mới."}


# ─────────── buff endpoints ────────────
def _pick_session():
    c = storage.pick_active_cookie()
    if not c:
        raise HTTPException(400, "Admin chưa thêm cookie nào.")
    return c, build_session(c["cookie_string"], c["user_agent"])


@api.get("/services")
def api_services(claims: dict = Depends(require_user)):
    c, s = _pick_session()
    services, _ = get_services(s)
    if not services:
        raise HTTPException(502, "Không lấy được dịch vụ. Cookie có thể hết hạn.")
    return {
        "cookie_id": c["id"], "cookie_label": c["label"],
        "services": [{"name": x["name"], "active": x["active"], "status": x["status"]}
                     for x in services],
    }


@api.post("/run")
def api_run(inp: RunIn, claims: dict = Depends(require_user)):
    c, s = _pick_session()
    services, home_html = get_services(s)
    target = next((x for x in services if x["name"] == inp.service), None)
    if not target:
        raise HTTPException(400, f"Không tìm thấy dịch vụ '{inp.service}'")
    if not target["active"]:
        raise HTTPException(400, f"Dịch vụ '{inp.service}' đang bảo trì")

    result = run_boost(s, target, home_html, inp.video_url)
    storage.push_history({
        "at": time.time(), "by": claims["sub"], "service": inp.service,
        "url": inp.video_url[:120], "ok": result["ok"],
        "message": result["message"], "cooldown": result.get("cooldown", 0),
        "amount": result.get("amount"), "cookie_label": c["label"],
    })
    return {
        "ok": result["ok"], "message": result["message"],
        "cooldown": result.get("cooldown", 0), "amount": result.get("amount"),
        "service": inp.service, "cookie": c["label"],
    }
