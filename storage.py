"""JSON storage đơn giản cho cookie/UA + telegram users."""
import json, os, threading, time
from datetime import datetime, timezone

DATA_FILE = os.environ.get("DATA_FILE", "data.json")
_lock = threading.Lock()

_DEFAULT = {
    "cookie": "",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "telegram_users": {},   # tid -> {"verified_at": iso, "day": "YYYY-MM-DD", "count": int, "username": str}
    "stats": {"total_buffs": 0}
}

def _load():
    if not os.path.exists(DATA_FILE):
        return dict(_DEFAULT)
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        for k, v in _DEFAULT.items():
            d.setdefault(k, v)
        return d
    except Exception:
        return dict(_DEFAULT)

def _save(d):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def get_all():
    with _lock:
        return _load()

def update(**kwargs):
    with _lock:
        d = _load()
        d.update(kwargs)
        _save(d)
        return d

def get_config():
    d = get_all()
    return d.get("cookie", ""), d.get("user_agent", "")

def inc_stat():
    with _lock:
        d = _load()
        d["stats"]["total_buffs"] = d["stats"].get("total_buffs", 0) + 1
        _save(d)

def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def tg_verify(tid: str, username: str = ""):
    with _lock:
        d = _load()
        u = d["telegram_users"].get(str(tid), {})
        u["verified_at"] = datetime.now(timezone.utc).isoformat()
        u["username"] = username or u.get("username", "")
        u.setdefault("day", today_str())
        u.setdefault("count", 0)
        d["telegram_users"][str(tid)] = u
        _save(d)

def tg_can_buff(tid: str, daily_limit: int = 10):
    """Trả (ok, msg, remaining)."""
    d = get_all()
    u = d["telegram_users"].get(str(tid))
    if not u or not u.get("verified_at"):
        return False, "Bạn chưa verify. Vào /start để lấy link web admin.", 0
    # yêu cầu verify lại mỗi 24h
    try:
        va = datetime.fromisoformat(u["verified_at"])
        if (datetime.now(timezone.utc) - va).total_seconds() > 86400:
            return False, "Verify đã hết hạn (24h). Vào lại link web để verify.", 0
    except Exception:
        return False, "Verify không hợp lệ, verify lại.", 0
    today = today_str()
    if u.get("day") != today:
        u["day"] = today; u["count"] = 0
    if u["count"] >= daily_limit:
        return False, f"Đã dùng hết {daily_limit} lượt buff hôm nay.", 0
    return True, "ok", daily_limit - u["count"]

def tg_inc(tid: str):
    with _lock:
        d = _load()
        u = d["telegram_users"].get(str(tid))
        if not u:
            return
        today = today_str()
        if u.get("day") != today:
            u["day"] = today; u["count"] = 0
        u["count"] = u.get("count", 0) + 1
        d["telegram_users"][str(tid)] = u
        _save(d)
