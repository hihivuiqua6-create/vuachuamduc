"""
Zefoy Buff Web API v2 — Flask
- Modern MMO/gaming UI
- Background buff worker (per-key thread), tắt trình duyệt vẫn chạy tiếp
- Realtime job stream qua Server-Sent Events
- REST API JSON cho client ngoài (ví dụ panel PHP)
"""
import os
import base64
import secrets
import threading
import time
import json
import queue
from functools import wraps
from collections import defaultdict, deque
from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for, send_file, Response, abort
)
from io import BytesIO

from zefoy_core import ZefoyClient, FirebaseManager

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7,
)

# ---- Per-key state (persist across browser sessions; keyed by user KEY, not cookie) ----
# Each key gets its own ZefoyClient + background worker + job history.
STATE_LOCK = threading.Lock()
CLIENTS: dict = {}   # key -> ZefoyClient
WORKERS: dict = {}   # key -> {"queue": Queue, "thread": Thread, "jobs": deque, "events": list[Queue]}

# ---- Rate limiting (IP+path) ----
RL_LOCK = threading.Lock()
RL_HITS: dict = defaultdict(lambda: deque())
def rate_limit(max_hits=30, per_seconds=60):
    def deco(f):
        @wraps(f)
        def wrap(*a, **kw):
            ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
            bucket = f"{ip}:{request.path}"
            now = time.time()
            with RL_LOCK:
                dq = RL_HITS[bucket]
                while dq and now - dq[0] > per_seconds:
                    dq.popleft()
                if len(dq) >= max_hits:
                    return jsonify({"ok": False, "error": "rate_limited"}), 429
                dq.append(now)
            return f(*a, **kw)
        return wrap
    return deco


def _get_or_create_state(key: str):
    with STATE_LOCK:
        c = CLIENTS.get(key)
        if c is None:
            c = ZefoyClient()
            CLIENTS[key] = c
        w = WORKERS.get(key)
        if w is None:
            w = {
                "queue": queue.Queue(),
                "jobs": deque(maxlen=200),
                "events": [],
                "running": True,
                "thread": None,
            }
            t = threading.Thread(target=_worker_loop, args=(key, w), daemon=True)
            w["thread"] = t
            WORKERS[key] = w
            t.start()
    return c, w


def _push_event(w, ev: dict):
    ev["ts"] = int(time.time() * 1000)
    with STATE_LOCK:
        listeners = list(w["events"])
    for q in listeners:
        try:
            q.put_nowait(ev)
        except Exception:
            pass


def _worker_loop(key: str, w: dict):
    """Consumes buff jobs for a single key. Runs even after browser closes."""
    while w["running"]:
        try:
            job = w["queue"].get(timeout=1.0)
        except queue.Empty:
            continue
        job["status"] = "running"
        job["started_at"] = int(time.time())
        w["jobs"].appendleft(job)
        _push_event(w, {"type": "job_update", "job": _job_view(job)})
        try:
            c = CLIENTS.get(key)
            if not c:
                raise RuntimeError("client missing")
            result = c.perform_action(job["service"], job["url"])
            job["status"] = "done"
            job["result"] = result
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
        job["finished_at"] = int(time.time())
        _push_event(w, {"type": "job_update", "job": _job_view(job)})


def _job_view(j: dict) -> dict:
    return {k: v for k, v in j.items() if k in
            ("id", "service", "url", "status", "started_at",
             "finished_at", "result", "error", "created_at", "loops", "done_loops")}


def require_login(f):
    @wraps(f)
    def wrap(*a, **kw):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            return redirect(url_for("login_page"))
        return f(*a, **kw)
    return wrap


def _current_key() -> str:
    u = session.get("user") or {}
    return u.get("key") or ""


# ---------- Pages ----------
@app.route("/")
def home():
    return redirect(url_for("dashboard") if session.get("user") else "login_page")


@app.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")


@app.route("/dashboard")
@require_login
def dashboard():
    return render_template("dashboard.html", user=session.get("user"))


# ---------- Auth API ----------
@app.route("/api/login", methods=["POST"])
@rate_limit(max_hits=8, per_seconds=60)
def api_login():
    data = request.get_json(force=True, silent=True) or request.form
    key = (data.get("key") or "").strip()
    if not key or len(key) > 128:
        return jsonify({"ok": False, "error": "missing key"}), 400
    fb = FirebaseManager()
    try:
        ok = fb.verify_key(key)
    except Exception as e:
        return jsonify({"ok": False, "error": f"firebase: {e}"}), 500
    if not ok:
        return jsonify({"ok": False, "error": "Key không hợp lệ hoặc đã hết hạn"}), 401
    session.clear()
    session["user"] = {"key": key, "id": key[:12]}
    session.permanent = True
    _get_or_create_state(key)  # spawn worker immediately
    return jsonify({"ok": True, "user": {"key": key, "id": key[:12]}})


@app.route("/api/logout", methods=["POST"])
def api_logout():
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
    c, _ = _get_or_create_state(_current_key())
    try:
        return jsonify({"ok": bool(c.initialize())})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/captcha")
@require_login
def api_captcha():
    c, _ = _get_or_create_state(_current_key())
    img = c.get_captcha_image()
    if not img:
        return jsonify({"ok": False, "error": "no captcha"}), 404
    if request.args.get("format") == "image":
        return send_file(BytesIO(img), mimetype="image/png")
    return jsonify({"ok": True, "image": "data:image/png;base64," + base64.b64encode(img).decode()})


@app.route("/api/solve", methods=["POST"])
@require_login
def api_solve():
    data = request.get_json(force=True, silent=True) or {}
    answer = (data.get("answer") or "").strip()
    if not answer:
        return jsonify({"ok": False, "error": "missing answer"}), 400
    c, _ = _get_or_create_state(_current_key())
    try:
        return jsonify({"ok": bool(c.solve_captcha(answer))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _serialize_service(s: dict) -> dict:
    return {
        "key": s.get("title"),
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
    c, _ = _get_or_create_state(_current_key())
    try:
        raw = c.get_services() or []
        return jsonify({"ok": True, "services": [_serialize_service(s) for s in raw]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------- Background jobs ("treo buff") ----------
@app.route("/api/buff", methods=["POST"])
@require_login
@rate_limit(max_hits=20, per_seconds=60)
def api_buff():
    data = request.get_json(force=True, silent=True) or {}
    service = (data.get("service") or "").strip()
    url = (data.get("url") or "").strip()
    loops = int(data.get("loops") or 1)
    loops = max(1, min(loops, 500))
    if not service or not url:
        return jsonify({"ok": False, "error": "service and url required"}), 400
    key = _current_key()
    _, w = _get_or_create_state(key)
    job_ids = []
    for _ in range(loops):
        jid = secrets.token_hex(6)
        job = {
            "id": jid, "service": service, "url": url,
            "status": "queued", "created_at": int(time.time()),
            "loops": loops, "done_loops": 0,
        }
        w["queue"].put(job)
        w["jobs"].appendleft(job)
        job_ids.append(jid)
        _push_event(w, {"type": "job_queued", "job": _job_view(job)})
    return jsonify({"ok": True, "queued": len(job_ids), "ids": job_ids})


@app.route("/api/jobs")
@require_login
def api_jobs():
    key = _current_key()
    _, w = _get_or_create_state(key)
    with STATE_LOCK:
        jobs = [_job_view(j) for j in list(w["jobs"])]
    return jsonify({"ok": True, "jobs": jobs})


@app.route("/api/jobs/clear", methods=["POST"])
@require_login
def api_jobs_clear():
    _, w = _get_or_create_state(_current_key())
    with STATE_LOCK:
        w["jobs"].clear()
    return jsonify({"ok": True})


@app.route("/api/stream")
@require_login
def api_stream():
    key = _current_key()
    _, w = _get_or_create_state(key)
    q: queue.Queue = queue.Queue(maxsize=100)
    with STATE_LOCK:
        w["events"].append(q)

    def gen():
        try:
            yield f"event: hello\ndata: {json.dumps({'ok':True})}\n\n"
            last_ping = time.time()
            while True:
                try:
                    ev = q.get(timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
                    if time.time() - last_ping > 300:
                        break
        finally:
            with STATE_LOCK:
                try: w["events"].remove(q)
                except ValueError: pass

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "zefoy-buff-api", "version": "2.0"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
