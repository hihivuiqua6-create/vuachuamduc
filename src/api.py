"""TienBuff API — FastAPI backend v3.

Điểm mới:
  - Đăng ký mở cho mọi người (user thường). Người ĐẦU TIÊN đăng ký = admin.
  - Free user: cần liên kết Telegram + join nhóm admin cấu hình + giới hạn 10 lần/ngày.
  - Admin quản lý cookie pool, bot Telegram, nhóm bắt buộc.
"""
from __future__ import annotations
import os
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
from . import telegram_bot as tg


FREE_DAILY_LIMIT = int(os.environ.get("FREE_DAILY_LIMIT", "10"))

api = FastAPI(title="TienBuff API", version="3.0.0")
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

class TgConfigIn(BaseModel):
    bot_token: str | None = None
    group_chat_id: str | None = None
    group_link: str | None = None
    require_join: bool | None = None
    welcome: str | None = None


# ─────────── public ────────────
@api.get("/status")
def status():
    d = storage.read()
    users = d.get("users", [])
    tg_cfg = d.get("telegram", {})
    return {
        "has_admin": any(u.get("role") == "admin" for u in users),
        "registration_open": True,
        "user_count": len(users),
        "cookie_count": len(d.get("cookies", [])),
        "active_cookie_count": sum(1 for c in d.get("cookies", []) if c.get("active", True)),
        "stats": d.get("stats", {}),
        "free_daily_limit": FREE_DAILY_LIMIT,
        "telegram": {
            "group_link": tg_cfg.get("group_link", ""),
            "require_join": bool(tg_cfg.get("require_join") and tg_cfg.get("group_chat_id")),
            "bot_active": tg.bot_status()["running"],
        },
    }


# ─────────── auth ────────────
@api.post("/register")
def register(inp: RegisterIn):
    d = storage.read()
    users = d.get("users", [])
    if any(u["username"] == inp.username for u in users):
        raise HTTPException(409, "Tên đăng nhập đã tồn tại")
    role = "admin" if len(users) == 0 else "user"
    def _m(dd):
        dd.setdefault("users", []).append({
            "username": inp.username,
            "password_hash": hash_password(inp.password),
            "role": role,
            "created_at": time.time(),
        })
    storage.write(_m)
    return {"ok": True, "token": make_token(inp.username, role),
            "role": role, "username": inp.username}


@api.post("/login")
def login(inp: LoginIn):
    u = storage.find_user(inp.username)
    if not u or not verify_password(inp.password, u["password_hash"]):
        raise HTTPException(401, "Sai tài khoản hoặc mật khẩu")
    role = u.get("role", "user")
    return {"ok": True, "token": make_token(inp.username, role),
            "role": role, "username": inp.username}


@api.get("/me")
def me(claims: dict = Depends(require_user)):
    u = storage.find_user(claims["sub"]) or {}
    used = storage.get_today_count(claims["sub"])
    return {
        "username": claims["sub"],
        "role": claims.get("role", "user"),
        "telegram_id": u.get("telegram_id"),
        "telegram_username": u.get("telegram_username"),
        "used_today": used,
        "remaining": None if claims.get("role") == "admin" else max(0, FREE_DAILY_LIMIT - used),
    }


# ─────────── telegram linking ────────────
@api.post("/telegram/link-code")
def request_link_code(claims: dict = Depends(require_user)):
    if not tg.bot_status()["has_token"]:
        raise HTTPException(400, "Admin chưa cấu hình bot Telegram.")
    code = storage.set_link_code(claims["sub"])
    return {"code": code, "expires_in": 600}


@api.get("/telegram/check")
def check_telegram(claims: dict = Depends(require_user)):
    """Check user đã liên kết + đã join group chưa."""
    if claims.get("role") == "admin":
        return {"linked": True, "in_group": True, "role": "admin"}
    u = storage.find_user(claims["sub"]) or {}
    tg_id = u.get("telegram_id")
    cfg = storage.get_tg_config()
    require_join = bool(cfg.get("require_join") and cfg.get("group_chat_id"))
    if not tg_id:
        return {"linked": False, "in_group": False, "require_join": require_join,
                "group_link": cfg.get("group_link", "")}
    in_group = True
    if require_join:
        in_group = tg.check_membership(tg_id)
    return {"linked": True, "in_group": in_group, "require_join": require_join,
            "group_link": cfg.get("group_link", ""),
            "telegram_username": u.get("telegram_username", "")}


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


@api.get("/admin/users")
def list_users(_: dict = Depends(require_admin)):
    d = storage.read()
    out = []
    for u in d.get("users", []):
        used = storage.get_today_count(u["username"])
        out.append({
            "username": u["username"], "role": u.get("role", "user"),
            "created_at": u.get("created_at"),
            "telegram_id": u.get("telegram_id"),
            "telegram_username": u.get("telegram_username"),
            "used_today": used,
        })
    return {"users": out}


# ─────────── admin: telegram config ────────────
@api.get("/admin/telegram")
def get_tg(_: dict = Depends(require_admin)):
    cfg = dict(storage.get_tg_config())
    tok = cfg.get("bot_token", "")
    cfg["bot_token_preview"] = (tok[:6] + "…" + tok[-4:]) if len(tok) > 12 else ""
    cfg.pop("bot_token", None)
    cfg["bot_status"] = tg.bot_status()
    return cfg


@api.post("/admin/telegram")
def set_tg(inp: TgConfigIn, _: dict = Depends(require_admin)):
    patch = {k: v for k, v in inp.model_dump(exclude_none=True).items()}
    if not patch:
        raise HTTPException(400, "Không có thay đổi")
    storage.set_tg_config(patch)
    started = None
    if "bot_token" in patch:
        if patch["bot_token"]:
            started = tg.start_bot(patch["bot_token"])
            if not started.get("ok"):
                raise HTTPException(400, f"Bot token không hợp lệ: {started.get('error')}")
        else:
            tg.stop_bot()
    return {"ok": True, "bot": started, "status": tg.bot_status()}


@api.post("/admin/telegram/test")
def test_tg(_: dict = Depends(require_admin)):
    cfg = storage.get_tg_config()
    tok = cfg.get("bot_token", "")
    if not tok:
        raise HTTPException(400, "Chưa có token")
    import requests as rq
    r = rq.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15).json()
    return r


# ─────────── buff endpoints ────────────
def _pick_session():
    c = storage.pick_active_cookie()
    if not c:
        raise HTTPException(400, "Admin chưa thêm cookie Zefoy nào.")
    return c, build_session(c["cookie_string"], c["user_agent"])


def _gate_free_user(claims: dict):
    if claims.get("role") == "admin":
        return
    u = storage.find_user(claims["sub"]) or {}
    cfg = storage.get_tg_config()
    require_join = bool(cfg.get("require_join") and cfg.get("group_chat_id"))
    if require_join:
        tg_id = u.get("telegram_id")
        if not tg_id:
            raise HTTPException(403, "Bạn cần liên kết Telegram và tham gia nhóm trước khi buff.")
        if not tg.check_membership(tg_id):
            raise HTTPException(403, "Bạn chưa vào nhóm Telegram bắt buộc. Vui lòng join rồi thử lại.")
    used = storage.get_today_count(claims["sub"])
    if used >= FREE_DAILY_LIMIT:
        raise HTTPException(429, f"Bạn đã hết lượt buff free hôm nay ({FREE_DAILY_LIMIT} lần).")


@api.get("/services")
def api_services(claims: dict = Depends(require_user)):
    _gate_free_user(claims)
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
    _gate_free_user(claims)
    c, s = _pick_session()
    services, home_html = get_services(s)
    target = next((x for x in services if x["name"] == inp.service), None)
    if not target:
        raise HTTPException(400, f"Không tìm thấy dịch vụ '{inp.service}'")
    if not target["active"]:
        raise HTTPException(400, f"Dịch vụ '{inp.service}' đang bảo trì")

    result = run_boost(s, target, home_html, inp.video_url)
    new_count = None
    if claims.get("role") != "admin":
        new_count = storage.bump_usage(claims["sub"])
    storage.push_history({
        "at": time.time(), "by": claims["sub"], "service": inp.service,
        "url": inp.video_url[:120], "ok": result["ok"],
        "message": result["message"], "cooldown": result.get("cooldown", 0),
        "amount": result.get("amount"), "cookie_label": c["label"],
    })
    remaining = None
    if claims.get("role") != "admin":
        remaining = max(0, FREE_DAILY_LIMIT - (new_count or 0))
    return {
        "ok": result["ok"], "message": result["message"],
        "cooldown": result.get("cooldown", 0), "amount": result.get("amount"),
        "service": inp.service, "cookie": c["label"],
        "used_today": new_count, "remaining": remaining,
    }