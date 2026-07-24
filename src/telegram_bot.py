"""Telegram bot chạy polling trong background thread.

Admin lưu bot token qua API web -> gọi start_bot(). Bot xử lý:
  /start        – chào + gửi link nhóm nếu có
  /link <code>  – liên kết telegram_id với tài khoản web
  /status       – xem quota còn lại hôm nay
  /help         – hướng dẫn

API check_membership(tg_id) dùng cho web để verify user đã join group.
"""
from __future__ import annotations
import threading
import time
import traceback
import requests

from . import storage

_state = {
    "thread": None,
    "stop": False,
    "token": "",
    "last_error": "",
    "started_at": 0,
}
_lock = threading.Lock()

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, **params):
    try:
        r = requests.post(API.format(token=token, method=method), json=params, timeout=35)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_membership(telegram_id: int) -> bool:
    cfg = storage.get_tg_config()
    token = cfg.get("bot_token") or ""
    chat = cfg.get("group_chat_id") or ""
    if not token or not chat:
        return False
    res = _call(token, "getChatMember", chat_id=chat, user_id=int(telegram_id))
    if not res.get("ok"): return False
    status = (res.get("result") or {}).get("status")
    return status in ("creator", "administrator", "member", "restricted")


def send_message(chat_id: int | str, text: str, **extra):
    cfg = storage.get_tg_config()
    token = cfg.get("bot_token") or ""
    if not token: return {"ok": False, "error": "no token"}
    return _call(token, "sendMessage", chat_id=chat_id, text=text,
                 parse_mode="HTML", disable_web_page_preview=True, **extra)


def _handle_update(upd: dict):
    msg = upd.get("message") or upd.get("edited_message")
    if not msg: return
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"): return
    chat_id = msg["chat"]["id"]
    from_user = msg.get("from", {}) or {}
    tg_id = from_user.get("id")
    tg_username = from_user.get("username") or ""

    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@", 1)[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    cfg = storage.get_tg_config()
    if cmd == "/start":
        welcome = cfg.get("welcome") or "Chào mừng đến TienBuff!"
        link = cfg.get("group_link") or ""
        msg_txt = welcome
        if link:
            msg_txt += f"\n\n👉 Nhóm chính thức: {link}"
        msg_txt += "\n\nDùng <b>/link MÃ</b> để liên kết với tài khoản web."
        send_message(chat_id, msg_txt)
    elif cmd == "/help":
        send_message(chat_id,
            "<b>Lệnh:</b>\n"
            "/start – Bắt đầu\n"
            "/link &lt;mã&gt; – Liên kết tài khoản web (lấy mã trong trang Buff)\n"
            "/status – Xem quota còn lại hôm nay\n"
            "/help – Trợ giúp")
    elif cmd == "/link":
        if not arg:
            send_message(chat_id, "Dùng: <code>/link MÃ_LIÊN_KẾT</code>")
            return
        code = arg.split()[0].upper()
        username = storage.bind_telegram(code, tg_id, tg_username)
        if username:
            send_message(chat_id,
                f"✅ Đã liên kết với tài khoản <b>{username}</b>.\n"
                "Quay lại web và bấm <b>Kiểm tra</b> để bắt đầu buff.")
        else:
            send_message(chat_id, "❌ Mã sai hoặc đã hết hạn (10 phút).")
    elif cmd == "/status":
        # tìm user theo telegram_id
        d = storage.read()
        u = next((x for x in d["users"] if x.get("telegram_id") == tg_id), None)
        if not u:
            send_message(chat_id, "Bạn chưa liên kết tài khoản. Dùng /link MÃ.")
            return
        import os as _os
        limit = int(_os.environ.get("FREE_DAILY_LIMIT", "10"))
        used = storage.get_today_count(u["username"])
        remaining = "∞" if u.get("role") == "admin" else max(0, limit - used)
        send_message(chat_id,
            f"👤 <b>{u['username']}</b>\nQuota hôm nay: <b>{used}</b> / {limit}\nCòn lại: <b>{remaining}</b>")


def _poll_loop(token: str):
    offset = 0
    while not _state["stop"]:
        # nếu admin đổi token, dừng vòng cũ
        cur = storage.get_tg_config().get("bot_token") or ""
        if cur != token:
            print("[bot] token changed, exiting loop", flush=True)
            return
        try:
            r = requests.get(
                API.format(token=token, method="getUpdates"),
                params={"timeout": 25, "offset": offset, "allowed_updates": '["message"]'},
                timeout=35,
            )
            data = r.json()
            if not data.get("ok"):
                _state["last_error"] = str(data)[:200]
                time.sleep(5)
                continue
            _state["last_error"] = ""
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    _handle_update(upd)
                except Exception:
                    print("[bot handler]", traceback.format_exc(), flush=True)
        except requests.exceptions.ReadTimeout:
            continue
        except Exception as e:
            _state["last_error"] = str(e)[:200]
            print("[bot loop]", e, flush=True)
            time.sleep(5)


def start_bot(token: str) -> dict:
    """Bắt đầu polling với token mới. Nếu đang chạy sẽ tự dừng vòng cũ."""
    with _lock:
        if not token:
            return {"ok": False, "error": "empty token"}
        # verify token
        me = _call(token, "getMe")
        if not me.get("ok"):
            return {"ok": False, "error": me.get("description") or "invalid token"}
        # stop old
        _state["stop"] = True
        old = _state["thread"]
        if old and old.is_alive():
            time.sleep(0.2)
        _state["stop"] = False
        _state["token"] = token
        _state["started_at"] = time.time()
        t = threading.Thread(target=_poll_loop, args=(token,), daemon=True, name="tg-bot")
        t.start()
        _state["thread"] = t
        return {"ok": True, "bot": me.get("result", {})}


def stop_bot():
    with _lock:
        _state["stop"] = True
        _state["token"] = ""
        _state["thread"] = None


def bot_status() -> dict:
    t = _state.get("thread")
    return {
        "running": bool(t and t.is_alive()),
        "started_at": _state.get("started_at", 0),
        "last_error": _state.get("last_error", ""),
        "has_token": bool(storage.get_tg_config().get("bot_token")),
    }


def start_bot_if_configured():
    tok = storage.get_tg_config().get("bot_token") or ""
    if tok:
        start_bot(tok)