"""
Zefoy Buff Web API - Flask
Wraps the original ZefoyClient/FirebaseManager into a web service
with login, modern web UI, and JSON API for external clients (e.g. PHP).
"""
import os
import base64
import secrets
import threading
import time
from functools import wraps
from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for, send_file, abort
)
from io import BytesIO

from zefoy_core import ZefoyClient, FirebaseManager

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# In-memory per-session state. For production use Redis.
CLIENTS: dict = {}
JOBS: dict = {}
LOCK = threading.Lock()


def get_client() -> ZefoyClient:
    sid = session.get("sid")
    if not sid:
        sid = secrets.token_hex(16)
        session["sid"] = sid
    with LOCK:
        c = CLIENTS.get(sid)
        if c is None:
            c = ZefoyClient()
            CLIENTS[sid] = c
    return c


def require_login(f):
    @wraps(f)
    def wrap(*a, **kw):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            return redirect(url_for("login_page"))
        return f(*a, **kw)
    return wrap


# ---------- Pages ----------
@app.route("/")
def home():
    if session.get("user"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login_page"))


@app.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")


@app.route("/dashboard")
@require_login
def dashboard():
    return render_template("dashboard.html", user=session.get("user"))


# ---------- Auth API ----------
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True) or request.form
    key = (data.get("key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "missing key"}), 400
    fb = FirebaseManager()
    try:
        ok = fb.verify_key(key)
    except Exception as e:
        return jsonify({"ok": False, "error": f"firebase: {e}"}), 500
    if not ok:
        return jsonify({"ok": False, "error": "Key không hợp lệ hoặc đã hết hạn"}), 401
    user = {"key": key, "id": key[:12]}
    session["user"] = user
    session.permanent = True
    return jsonify({"ok": True, "user": user})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = session.get("sid")
    with LOCK:
        CLIENTS.pop(sid, None)
        JOBS.pop(sid, None)
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
@require_login
def api_me():
    return jsonify({"ok": True, "user": session.get("user")})


# ---------- Zefoy API ----------
@app.route("/api/init", methods=["POST"])
@require_login
def api_init():
    c = get_client()
    try:
        ok = c.initialize()
        return jsonify({"ok": bool(ok)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/captcha")
@require_login
def api_captcha():
    c = get_client()
    img = c.get_captcha_image()
    if not img:
        return jsonify({"ok": False, "error": "no captcha"}), 404
    fmt = request.args.get("format", "json")
    if fmt == "image":
        return send_file(BytesIO(img), mimetype="image/png")
    b64 = base64.b64encode(img).decode()
    return jsonify({"ok": True, "image": f"data:image/png;base64,{b64}"})


@app.route("/api/solve", methods=["POST"])
@require_login
def api_solve():
    data = request.get_json(force=True, silent=True) or {}
    answer = (data.get("answer") or "").strip()
    if not answer:
        return jsonify({"ok": False, "error": "missing answer"}), 400
    c = get_client()
    try:
        ok = c.solve_captcha(answer)
        return jsonify({"ok": bool(ok)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _serialize_service(s: dict) -> dict:
    # Strip BeautifulSoup Tag ('form') — not JSON serializable.
    return {
        "key": s.get("title"),          # frontend uses this as service id
        "title": s.get("title"),
        "name": s.get("title"),
        "available": bool(s.get("available")),
        "status": s.get("status"),
        "action": s.get("action"),
        "input_name": s.get("input_name"),
    }


@app.route("/api/services")
@require_login
def api_services():
    c = get_client()
    try:
        raw = c.get_services() or []
        return jsonify({"ok": True, "services": [_serialize_service(s) for s in raw]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/buff", methods=["POST"])
@require_login
def api_buff():
    data = request.get_json(force=True, silent=True) or {}
    service = data.get("service")
    url = data.get("url")
    if not service or not url:
        return jsonify({"ok": False, "error": "service and url required"}), 400
    c = get_client()
    try:
        result = c.perform_action(service, url)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "zefoy-buff-api"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
