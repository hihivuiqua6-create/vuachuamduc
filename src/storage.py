"""JSON-file storage cho users, cookie pool, telegram config, quota."""
import json
import os
import threading
import time
import uuid
from typing import Any

_LOCK = threading.RLock()
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "db.json")

_DEFAULT: dict[str, Any] = {
    "users": [],
    # users: [{username, password_hash, role, created_at,
    #          telegram_id, telegram_username, link_code,
    #          usage: {"date": "YYYY-MM-DD", "count": int}}]
    "cookies": [],
    "stats": {"total_runs": 0, "total_success": 0},
    "history": [],
    "telegram": {
        "bot_token": "",
        "group_chat_id": "",       # e.g. -1001234567890
        "group_link": "",          # https://t.me/xxx
        "require_join": True,
        "welcome": "Chào mừng đến TienBuff! Dùng /link <mã> để liên kết tài khoản.",
    },
}


def _load() -> dict[str, Any]:
    if not os.path.exists(DB_PATH):
        return json.loads(json.dumps(_DEFAULT))
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in _DEFAULT.items():
            if k not in data:
                data[k] = json.loads(json.dumps(v))
            elif isinstance(v, dict):
                for kk, vv in v.items():
                    data[k].setdefault(kk, vv)
        return data
    except Exception:
        return json.loads(json.dumps(_DEFAULT))


def _save(data: dict[str, Any]) -> None:
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_PATH)


def read() -> dict[str, Any]:
    with _LOCK:
        return _load()


def write(mut) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        mut(data)
        _save(data)
        return data


# ── cookies ──
def add_cookie(label: str, cookie_string: str, user_agent: str) -> dict:
    entry = {
        "id": uuid.uuid4().hex[:10],
        "label": label or f"Cookie-{int(time.time())}",
        "cookie_string": cookie_string,
        "user_agent": user_agent,
        "created_at": time.time(),
        "active": True,
    }
    def _m(d): d["cookies"].append(entry)
    write(_m)
    return entry


def delete_cookie(cid: str) -> bool:
    found = {"v": False}
    def _m(d):
        b = len(d["cookies"])
        d["cookies"] = [c for c in d["cookies"] if c["id"] != cid]
        found["v"] = len(d["cookies"]) < b
    write(_m); return found["v"]


def toggle_cookie(cid: str) -> bool:
    found = {"v": False}
    def _m(d):
        for c in d["cookies"]:
            if c["id"] == cid:
                c["active"] = not c.get("active", True); found["v"] = True; break
    write(_m); return found["v"]


def pick_active_cookie() -> dict | None:
    data = read()
    actives = [c for c in data["cookies"] if c.get("active", True)]
    if not actives: return None
    actives.sort(key=lambda c: c.get("last_used", 0))
    chosen = actives[0]
    def _m(d):
        for c in d["cookies"]:
            if c["id"] == chosen["id"]:
                c["last_used"] = time.time(); break
    write(_m); return chosen


def push_history(entry: dict) -> None:
    def _m(d):
        d["history"].insert(0, entry)
        d["history"] = d["history"][:200]
        d["stats"]["total_runs"] = d["stats"].get("total_runs", 0) + 1
        if entry.get("ok"):
            d["stats"]["total_success"] = d["stats"].get("total_success", 0) + 1
    write(_m)


# ── users ──
def find_user(username: str) -> dict | None:
    for u in read().get("users", []):
        if u["username"] == username: return u
    return None


def update_user(username: str, patch: dict) -> None:
    def _m(d):
        for u in d["users"]:
            if u["username"] == username:
                u.update(patch); break
    write(_m)


def set_link_code(username: str) -> str:
    code = uuid.uuid4().hex[:8].upper()
    update_user(username, {"link_code": code, "link_code_exp": time.time() + 600})
    return code


def bind_telegram(link_code: str, telegram_id: int, telegram_username: str) -> str | None:
    found = {"u": None}
    def _m(d):
        for u in d["users"]:
            if u.get("link_code") == link_code and u.get("link_code_exp", 0) > time.time():
                u["telegram_id"] = telegram_id
                u["telegram_username"] = telegram_username
                u["link_code"] = ""; u["link_code_exp"] = 0
                found["u"] = u["username"]; break
    write(_m)
    return found["u"]


def today() -> str:
    return time.strftime("%Y-%m-%d")


def get_today_count(username: str) -> int:
    u = find_user(username) or {}
    usage = u.get("usage") or {}
    return usage.get("count", 0) if usage.get("date") == today() else 0


def bump_usage(username: str) -> int:
    n = {"v": 0}
    def _m(d):
        for u in d["users"]:
            if u["username"] == username:
                usage = u.get("usage") or {}
                if usage.get("date") != today():
                    usage = {"date": today(), "count": 0}
                usage["count"] = usage.get("count", 0) + 1
                u["usage"] = usage
                n["v"] = usage["count"]; break
    write(_m); return n["v"]


# ── telegram config ──
def get_tg_config() -> dict:
    return read().get("telegram", {})


def set_tg_config(patch: dict) -> dict:
    def _m(d):
        d.setdefault("telegram", {}).update(patch)
    write(_m)
    return get_tg_config()