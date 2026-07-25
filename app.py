"""
Python Guard Web - FastAPI service
Obfuscate Python source code (PyArmor) & package as downloadable ZIP.
Ready to deploy on Render.com
"""
import os
import io
import uuid
import json
import shutil
import zipfile
import tempfile
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ---------- Config ----------
APP_TITLE = "Python Guard Web"
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-render-env")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")
API_TOKEN = os.getenv("API_TOKEN", "demo-api-token-change-me")
JOB_DIR = Path(os.getenv("JOB_DIR", tempfile.gettempdir())) / "pyguard_jobs"
JOB_DIR.mkdir(parents=True, exist_ok=True)

serializer = URLSafeTimedSerializer(SECRET_KEY, salt="pyguard-session")

app = FastAPI(title=APP_TITLE)
BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))

# In-memory job registry (fine for single-instance Render service)
JOBS: dict[str, dict] = {}


# ---------- Auth helpers ----------
def get_session_user(request: Request) -> Optional[str]:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        data = serializer.loads(token, max_age=60 * 60 * 12)
        return data.get("u")
    except (BadSignature, SignatureExpired):
        return None


def require_web(request: Request) -> str:
    u = get_session_user(request)
    if not u:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return u


def require_api(request: Request) -> str:
    # Accept either logged-in session OR API token (for PHP/other clients)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth.split(" ", 1)[1] == API_TOKEN:
        return "api"
    u = get_session_user(request)
    if u:
        return u
    raise HTTPException(status_code=401, detail="Unauthorized")


# ---------- Routes: pages ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not get_session_user(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": get_session_user(request), "api_token": API_TOKEN})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.post("/login")
def login_submit(username: str = Form(...), password: str = Form(...)):
    if username != ADMIN_USER or password != ADMIN_PASS:
        return RedirectResponse("/login?error=1", status_code=303)
    token = serializer.dumps({"u": username})
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 12)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("session")
    return resp


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}


# ---------- Core: obfuscate + package ----------
def run_obfuscate(job_id: str, source_path: Path, app_name: str, level: str, obfuscate_strings: bool):
    work = JOB_DIR / job_id
    out = work / "obfuscated"
    out.mkdir(parents=True, exist_ok=True)

    level_map = {"low": "1", "medium": "2", "high": "3"}
    lv = level_map.get(level, "2")

    # Try PyArmor v8+ (`pyarmor gen`) then fallback to v7 (`pyarmor obfuscate`)
    cmd_v8 = ["pyarmor", "gen", "-O", str(out), str(source_path)]
    cmd_v7 = ["pyarmor", "obfuscate", f"--obfuscate-level={lv}", "--output", str(out), str(source_path)]
    if obfuscate_strings:
        cmd_v7.append("--obfuscate-string=1")

    logs = []
    for cmd in (cmd_v8, cmd_v7):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            logs.append(f"$ {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
            if r.returncode == 0:
                break
        except FileNotFoundError:
            logs.append("pyarmor not installed")
            break
        except Exception as e:
            logs.append(f"error: {e}")
    else:
        # fallback: copy raw + a marker so the zip is at least produced
        shutil.copy(source_path, out / source_path.name)
        (out / "OBFUSCATION_FAILED.txt").write_text("PyArmor is not available. Falling back to raw copy.\n\n" + "\n".join(logs))

    # Zip result
    zip_path = work / f"{app_name}_protected.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(out):
            for f in files:
                p = Path(root) / f
                z.write(p, p.relative_to(out))
        z.writestr("BUILD_LOG.txt", "\n".join(logs))
        z.writestr("README.txt",
                   f"{app_name}\nBuilt: {datetime.utcnow().isoformat()}\n\n"
                   "To turn this into a Windows .exe run locally:\n"
                   "  pip install pyinstaller\n"
                   f"  pyinstaller --onefile --windowed --name {app_name} {source_path.name}\n")

    JOBS[job_id].update({
        "status": "done",
        "zip": str(zip_path),
        "size": zip_path.stat().st_size,
        "finished_at": datetime.utcnow().isoformat(),
    })


# ---------- API ----------
@app.post("/api/obfuscate")
async def api_obfuscate(
    request: Request,
    file: UploadFile = File(...),
    app_name: str = Form("ProtectedApp"),
    level: str = Form("high"),
    obfuscate_strings: bool = Form(True),
    _user: str = Depends(require_api),
):
    if not file.filename.endswith(".py"):
        raise HTTPException(400, "Only .py files are accepted")

    job_id = uuid.uuid4().hex[:12]
    work = JOB_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)
    src = work / file.filename
    src.write_bytes(await file.read())

    JOBS[job_id] = {
        "id": job_id,
        "status": "running",
        "app_name": app_name,
        "level": level,
        "file": file.filename,
        "created_at": datetime.utcnow().isoformat(),
    }
    # synchronous run — small files, keeps Render free-tier simple
    try:
        run_obfuscate(job_id, src, app_name, level, obfuscate_strings)
    except Exception as e:
        JOBS[job_id].update({"status": "error", "error": str(e)})
        raise HTTPException(500, str(e))

    return {
        "job_id": job_id,
        "status": JOBS[job_id]["status"],
        "download_url": f"/api/download/{job_id}",
        "size": JOBS[job_id].get("size"),
    }


@app.get("/api/status/{job_id}")
def api_status(job_id: str, request: Request, _user: str = Depends(require_api)):
    if job_id not in JOBS:
        raise HTTPException(404, "job not found")
    return JOBS[job_id]


@app.get("/api/download/{job_id}")
def api_download(job_id: str, request: Request, _user: str = Depends(require_api)):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(404, "not ready")
    return FileResponse(job["zip"], filename=Path(job["zip"]).name, media_type="application/zip")


@app.get("/api/jobs")
def api_jobs(request: Request, _user: str = Depends(require_api)):
    return {"jobs": list(JOBS.values())[-50:]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
