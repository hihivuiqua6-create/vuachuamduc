"""
Flask app: landing + admin + API + Telegram bot (background thread).
Env:
  ADMIN_KEY (mặc định 'mducdeptrai')
  TELEGRAM_BOT_TOKEN (optional)
  PUBLIC_BASE_URL   (optional, để verify link)
"""
import os, threading, time, traceback, requests
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash

import storage
from buff_engine import run_buff_once, get_services, build_session

ADMIN_KEY = os.environ.get("ADMIN_KEY", "mducdeptrai")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "10"))

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "buff-api-secret-" + ADMIN_KEY)

# ---------- helpers ----------
def is_admin():
    return session.get("is_admin") is True

def base_url():
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    return request.host_url.rstrip("/")

# ---------- public pages ----------
@app.route("/")
def index():
    cookie, ua = storage.get_config()
    d = storage.get_all()
    services = []
    if cookie:
        try:
            s = build_session(cookie, ua)
            services, _ = get_services(s)
        except Exception:
            services = []
    return render_template("index.html",
        api_base=base_url(),
        configured=bool(cookie),
        services=services,
        total_buffs=d["stats"].get("total_buffs", 0),
        tg_users=len(d.get("telegram_users", {})),
        bot_enabled=bool(BOT_TOKEN),
        daily_limit=DAILY_LIMIT,
    )

# ---------- API (không cần key) ----------
@app.route("/api/services")
def api_services():
    cookie, ua = storage.get_config()
    if not cookie:
        return jsonify({"ok": False, "message": "Chưa cấu hình cookie"}), 503
    try:
        s = build_session(cookie, ua)
        svcs, _ = get_services(s)
        return jsonify({"ok": True, "services": [
            {"id": x["id"], "name": x["name"], "active": x["active"], "status": x["status"]}
            for x in svcs
        ]})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

@app.route("/api/buff", methods=["POST"])
def api_buff():
    data = request.get_json(silent=True) or request.form.to_dict()
    svc = (data.get("service") or "").strip()
    url = (data.get("url") or "").strip()
    if not svc or not url:
        return jsonify({"ok": False, "message": "Thiếu service hoặc url"}), 400
    cookie, ua = storage.get_config()
    try:
        res = run_buff_once(cookie, ua, svc, url)
        if res.get("ok"):
            storage.inc_stat()
        return jsonify(res), (200 if res.get("ok") else 400)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "message": str(e)}), 500

# ---------- admin ----------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not is_admin():
        if request.method == "POST":
            if request.form.get("key", "").strip() == ADMIN_KEY:
                session["is_admin"] = True
                return redirect(url_for("admin"))
            flash("Sai key!", "error")
        return render_template("admin_login.html")
    d = storage.get_all()
    return render_template("admin.html", cookie=d["cookie"], ua=d["user_agent"],
                           tg_users=d["telegram_users"], stats=d["stats"],
                           api_base=base_url(), bot_enabled=bool(BOT_TOKEN))

@app.route("/admin/save", methods=["POST"])
def admin_save():
    if not is_admin():
        return redirect(url_for("admin"))
    storage.update(cookie=request.form.get("cookie", "").strip(),
                   user_agent=request.form.get("user_agent", "").strip())
    flash("Đã lưu cấu hình!", "ok")
    return redirect(url_for("admin"))

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))

# ---------- Telegram verify endpoint ----------
@app.route("/verify/<tid>")
def verify(tid):
    username = request.args.get("u", "")
    storage.tg_verify(tid, username)
    return render_template("verify.html", tid=tid)

# ---------- Telegram bot polling ----------
def tg_send(chat_id, text, reply_markup=None):
    if not BOT_TOKEN:
        return
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup:
            import json as _j
            payload["reply_markup"] = _j.dumps(reply_markup)
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=15)
    except Exception:
        pass

def tg_handle(update):
    msg = update.get("message") or update.get("edited_message")
    if not msg or "text" not in msg:
        return
    chat_id = msg["chat"]["id"]
    tid = str(msg["from"]["id"])
    username = msg["from"].get("username", "")
    text = msg["text"].strip()
    parts = text.split()
    cmd = parts[0].lower()

    if cmd in ("/start", "/verify"):
        link = f"{base_url()}/verify/{tid}?u={username}"
        tg_send(chat_id,
            f"👋 <b>Buff MXH Bot</b>\n\n"
            f"Bấm link sau để verify (mở web admin), sau đó quay lại đây dùng bot:\n"
            f"👉 {link}\n\n"
            f"Mỗi ngày <b>{DAILY_LIMIT} lượt</b> buff miễn phí.\n"
            f"Verify hết hạn sau 24h.\n\n"
            f"<b>Lệnh:</b>\n"
            f"/services — xem dịch vụ\n"
            f"/buff &lt;service&gt; &lt;url&gt; — buff\n"
            f"/me — xem lượt còn lại"
        )
        return

    if cmd == "/services":
        cookie, ua = storage.get_config()
        if not cookie:
            tg_send(chat_id, "⚠️ Admin chưa cấu hình cookie.")
            return
        try:
            s = build_session(cookie, ua)
            svcs, _ = get_services(s)
            lines = ["<b>Dịch vụ khả dụng:</b>"]
            for x in svcs:
                mark = "🟢" if x["active"] else "🔴"
                lines.append(f"{mark} <code>{x['id']}</code> — {x['name']}")
            tg_send(chat_id, "\n".join(lines))
        except Exception as e:
            tg_send(chat_id, f"Lỗi: {e}")
        return

    if cmd == "/me":
        d = storage.get_all()
        u = d["telegram_users"].get(tid)
        if not u:
            tg_send(chat_id, "Bạn chưa /start.")
            return
        today = storage.today_str()
        count = u.get("count", 0) if u.get("day") == today else 0
        tg_send(chat_id, f"Đã buff hôm nay: <b>{count}/{DAILY_LIMIT}</b>\nVerify: {u.get('verified_at','—')}")
        return

    if cmd == "/buff":
        if len(parts) < 3:
            tg_send(chat_id, "Cú pháp: <code>/buff &lt;service&gt; &lt;url&gt;</code>\nVD: <code>/buff followers https://tiktok.com/@x</code>")
            return
        ok, m, remain = storage.tg_can_buff(tid, DAILY_LIMIT)
        if not ok:
            tg_send(chat_id, f"❌ {m}")
            return
        svc, url = parts[1], parts[2]
        cookie, ua = storage.get_config()
        try:
            res = run_buff_once(cookie, ua, svc, url)
        except Exception as e:
            res = {"ok": False, "message": str(e)}
        if res.get("ok"):
            storage.tg_inc(tid); storage.inc_stat()
            tg_send(chat_id, f"✅ {res['message']}\nCòn lại: <b>{remain-1}/{DAILY_LIMIT}</b>")
        else:
            tg_send(chat_id, f"⚠️ {res.get('message','Thất bại')}")
        return

    tg_send(chat_id, "Không hiểu lệnh. Gõ /start.")

def tg_poll_loop():
    if not BOT_TOKEN:
        print("[bot] TELEGRAM_BOT_TOKEN chưa cấu hình — bot tắt.")
        return
    print("[bot] Đang chạy Telegram bot polling…")
    offset = 0
    # xoá webhook để chắc dùng long polling
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
    except Exception:
        pass
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                             params={"timeout": 25, "offset": offset}, timeout=35)
            data = r.json()
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    tg_handle(upd)
                except Exception:
                    traceback.print_exc()
        except Exception:
            time.sleep(3)

_bot_started = False
_bot_lock = threading.Lock()

def _start_bot_once():
    global _bot_started
    with _bot_lock:
        if _bot_started or not BOT_TOKEN:
            return
        _bot_started = True
        t = threading.Thread(target=tg_poll_loop, daemon=True)
        t.start()

@app.before_request
def _boot():
    _start_bot_once()

if __name__ == "__main__":
    _start_bot_once()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
