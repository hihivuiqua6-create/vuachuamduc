"""
Zefoy Web API — Render-ready FastAPI wrapper (UPDATED with new logic)
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import random
import time
import uuid
import json
import urllib.parse
from string import ascii_letters, digits
from typing import Any, Optional
from urllib.parse import unquote
from datetime import datetime
import threading

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bs4 import BeautifulSoup
import requests

# ============== CONFIG ==============
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_BASE_URL = "https://zefoy.com"

app = FastAPI(title="Zefoy Web API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import traceback
from fastapi.responses import JSONResponse
from fastapi.requests import Request as _Req

@app.exception_handler(Exception)
async def _all_ex(request: _Req, exc: Exception):
    tb = traceback.format_exc()
    print("[UNHANDLED]", tb, flush=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc) or "unknown error",
        },
    )

# ─────────── session store ────────────
SESSIONS: dict[str, dict[str, Any]] = {}
SESSION_TTL = 60 * 30

def _new_session_state() -> dict[str, Any]:
    return {
        "session": requests.Session(),
        "created": time.time(),
        "last_used": time.time(),
        "user_agent": DEFAULT_USER_AGENT,
        "base_url": DEFAULT_BASE_URL,
        "services": [],
        "service_map": {},
        "video_key": None,
        "total_sent": 0,
        "captcha_b64": None,
        "captcha_encoded": None,
        "initialized": False,
        "cooldown_until": 0,  # timestamp when cooldown ends
        "last_run": 0,
    }

def _get(session_id: str) -> dict[str, Any]:
    _gc()
    st = SESSIONS.get(session_id)
    if not st:
        raise HTTPException(404, "session not found — bấm 'Bắt đầu' để tạo session mới")
    st["last_used"] = time.time()
    return st

def _gc():
    now = time.time()
    dead = [k for k, v in SESSIONS.items() if now - v["last_used"] > SESSION_TTL]
    for k in dead:
        SESSIONS.pop(k, None)

# ============== CORE LOGIC ==============

def _init_session(st: dict[str, Any]) -> None:
    """Initialize Zefoy session with cookies"""
    session = st["session"]
    session.verify = False
    session.headers.update({
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'accept-language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
        'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': st["user_agent"],
    })
    
    # Get homepage to establish session
    resp = session.get(f"{st['base_url']}/", timeout=30)
    resp.raise_for_status()
    
    # Set guard cookies
    zf = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()
    session.cookies.set("zf", zf, path="/")
    session.cookies.set("za", "200", path="/")
    
    st["initialized"] = True

def _get_captcha_image(st: dict[str, Any]) -> bytes:
    """Fetch captcha image from Zefoy"""
    session = st["session"]
    base_url = st["base_url"]
    user_agent = st["user_agent"]
    
    if not st.get("initialized"):
        _init_session(st)
    
    ts = int(time.time())
    url = f"{base_url}/?getcapthca={ts}"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{base_url}/",
    }
    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    
    data = resp.json()
    if not data:
        raise Exception("Empty captcha payload")
    
    # Find encoded value
    encoded = None
    key = hashlib.md5(user_agent.encode()).hexdigest()
    if key in data:
        encoded = data[key]
    elif len(data) == 1:
        encoded = next(iter(data.values()))
    else:
        raise Exception(f"Payload key {key} not found")
    
    # Decode image path
    once = base64.b64decode(encoded)
    twice = base64.b64decode(once)
    image_path = twice.decode('utf-8').strip()
    
    if not image_path.startswith("/"):
        image_path = "/" + image_path
    
    # Download image
    url = f"{base_url}{image_path}"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    
    if not resp.content:
        raise Exception("Empty image response")
    
    st["captcha_encoded"] = encoded
    
    return resp.content

def _build_captcha_encoded(st: dict[str, Any]) -> str:
    """Build captcha_encoded fingerprint"""
    user_agent = st["user_agent"]
    
    fingerprint = {
        "deviceInfo": {
            "cpuCores": 8,
            "deviceMemoryGB": 8,
            "platform": "Win32",
            "maxTouchPoints": 0,
        },
        "browserInfo": {
            "userAgent": user_agent,
            "timezone": "Asia/Saigon",
            "language": "vi",
            "languages": ["vi"],
            "cookieEnabled": True,
            "webdriver": False,
        },
        "screenInfo": {
            "width": 1920,
            "height": 1080,
            "colorDepth": 24,
        },
        "otherData": {},
        "storageInfo": {
            "localStorage": "Yes",
            "sessionStorage": "Yes",
            "indexedDB": "Yes",
        }
    }
    plaintext = json.dumps(fingerprint, separators=(',', ':'))
    return base64.b64encode(plaintext.encode()).decode()

def _submit_captcha(st: dict[str, Any], answer: str) -> bool:
    """Submit captcha answer to Zefoy"""
    session = st["session"]
    base_url = st["base_url"]
    
    answer = re.sub(r"[^a-zA-Z]", "", answer or "").lower()
    if not answer:
        return False
    
    encoded = st.get("captcha_encoded") or _build_captcha_encoded(st)
    
    data = {
        "captchalogin": answer,
        "captcha_encoded": encoded,
    }
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": base_url,
        "Referer": f"{base_url}/",
    }
    
    resp = session.post(
        f"{base_url}/",
        data=data,
        headers=headers,
        timeout=30
    )
    
    if resp.text.strip().lower() == "success":
        _refresh_services(st)
        return True
    return False

def _refresh_services(st: dict[str, Any]) -> None:
    """Refresh service list from Zefoy homepage"""
    session = st["session"]
    base_url = st["base_url"]
    
    resp = session.get(f"{base_url}/", timeout=30)
    html = resp.text or ""
    
    soup = BeautifulSoup(html, 'html.parser')
    services = []
    service_map = {}
    
    # Find all service cards
    for card in soup.find_all('div', class_='colsmenu'):
        title_tag = card.find('h5', class_='card-title')
        if not title_tag:
            continue
        title = title_tag.text.strip()
        
        btn = card.find('button')
        is_active = btn and 'disabled' not in btn.attrs
        
        status_tag = card.find(class_='badge') or card.find('small')
        status = status_tag.text.strip() if status_tag else ("ON" if is_active else "OFF")
        
        form = card.find('form')
        action = None
        input_name = None
        
        if form:
            action = form.get('action')
            search_input = form.find('input', type='search')
            if not search_input:
                search_input = form.find('input', class_='form-control')
            if search_input:
                input_name = search_input.get('name')
            
            if not input_name:
                for inp in form.find_all('input'):
                    if inp.get('name'):
                        input_name = inp.get('name')
                        break
        
        service_info = {
            'title': title,
            'available': is_active,
            'status': status,
            'action': action,
            'input_name': input_name,
            'form': form
        }
        
        services.append(service_info)
        
        if is_active and action and input_name:
            service_map[title] = service_info
            if input_name:
                st["video_key"] = input_name
        elif is_active:
            # Try to find hidden form for this service
            btn_class = ""
            if btn:
                for cls in btn.get('class', []):
                    if cls.startswith('t-') and cls.endswith('-button'):
                        btn_class = cls
                        break
            menu_class = btn_class.replace('-button', '-menu') if btn_class else ""
            
            if menu_class:
                menu_div = soup.find('div', class_=menu_class)
                if menu_div:
                    form2 = menu_div.find('form')
                    if form2:
                        action2 = form2.get('action')
                        inp2 = form2.find('input', type='search') or form2.find('input', class_='form-control')
                        input_name2 = inp2.get('name') if inp2 else None
                        if not input_name2:
                            for inp in form2.find_all('input'):
                                if inp.get('name'):
                                    input_name2 = inp.get('name')
                                    break
                        if action2 and input_name2:
                            service_info['action'] = action2
                            service_info['input_name'] = input_name2
                            service_info['form'] = form2
                            service_map[title] = service_info
    
    st["services"] = services
    st["service_map"] = service_map

def _decode_response(text: str) -> str:
    """Decode Zefoy response (multi-layer)"""
    text = text.strip()
    if not text:
        return text
    
    def try_decode(val):
        try:
            reversed_val = val[::-1]
            url_decoded = urllib.parse.unquote(reversed_val)
            decoded = base64.b64decode(url_decoded).decode('utf-8')
            if '<' in decoded or '{' in decoded or 'div' in decoded:
                return decoded
        except Exception:
            pass
        try:
            decoded = base64.b64decode(val).decode('utf-8')
            if '<' in decoded or '{' in decoded:
                return decoded
        except Exception:
            pass
        return val

    decoded = try_decode(text)
    if decoded != text:
        try:
            data = json.loads(decoded)
            if isinstance(data, dict) and 'html' in data:
                return try_decode(data['html'])
        except Exception:
            pass
        return decoded

    try:
        data = json.loads(text)
        if isinstance(data, dict) and 'html' in data:
            return try_decode(data['html'])
    except Exception:
        pass
        
    return text

def _extract_timer(html: str) -> Optional[int]:
    """Extract cooldown timer from HTML"""
    if not html:
        return None
    
    patterns = [
        r'var\s+ltm\s*=\s*(\d+)',
        r'ltm\s*=\s*(\d+)',
        r'ltimer\s*\(\s*(\d+)',
        r'timer\s*\(\s*(\d+)',
        r'startTimer\s*\(\s*(\d+)',
        r'var\s+k\s*=\s*(\d+)',
        r'var\s+time\s*=\s*(\d+)',
        r'var\s+timeleft\s*=\s*(\d+)',
        r'var\s+count\s*=\s*(\d+)',
        r'var\s+c\s*=\s*(\d+)',
        r'seconds\s*=\s*(\d+)',
        r'Please wait\s+(\d+)\s+seconds',
        r'(\d+)\s*minute\(s\)\s*(\d+)\s*second',
        r'wait\s+(\d+)\s*seconds',
        r'var\s+remainingTimelogin\s*=\s*(\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            if len(m.groups()) == 2:
                return int(m.group(1)) * 60 + int(m.group(2))
            return int(m.group(1))
    return None

def _parse_result(html: str) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """Parse amount from response"""
    if not html:
        return None, None, None
    
    patterns = [
        (r"Sent\s+(\d+)\s+([A-Za-z]+)", 1, 2),
        (r"Successfully\s+sent\s+(\d+)\s+([A-Za-z]+)", 1, 2),
        (r"\+\s*(\d+)\s+([A-Za-z]+)", 1, 2),
        (r"(\d+)\s+(views?|hearts?|followers?|shares?|likes?)", 1, 2),
        (r"Added\s+(\d+)\s+([A-Za-z]+)", 1, 2),
        (r"(\d+)\s+([A-Za-z]+)\s+added", 1, 2),
    ]
    for pat, ai, ki in patterns:
        m = re.search(pat, html, re.I)
        if m:
            try:
                return int(m.group(ai)), m.group(ki).lower(), m.group(0).strip()
            except:
                pass
    
    m = re.search(r'<div[^>]*class="[^"]*success[^"]*"[^>]*>([^<]+)', html, re.I)
    if m:
        return None, None, m.group(1).strip()
    
    m = re.search(r'color:\s*green;?[^>]*>([^<]+)', html, re.I)
    if m:
        return None, None, m.group(1).strip()
    
    return None, None, None

def _perform_action(st: dict[str, Any], service: str, url: str) -> dict[str, Any]:
    """Perform buff action with cooldown tracking"""
    session = st["session"]
    base_url = st["base_url"]
    service_map = st.get("service_map", {})
    
    # Check global cooldown
    now = time.time()
    if st.get("cooldown_until", 0) > now:
        remaining = int(st["cooldown_until"] - now)
        return {"success": False, "cooldown": remaining, "message": f"Đang chờ {remaining}s"}
    
    svc_info = service_map.get(service)
    if not svc_info:
        _refresh_services(st)
        svc_info = st.get("service_map", {}).get(service)
        if not svc_info:
            return {"success": False, "message": f"Service '{service}' không tồn tại"}
    
    if not svc_info.get("available"):
        return {"success": False, "message": f"Service '{service}' hiện không khả dụng"}
    
    action = svc_info.get('action')
    input_name = svc_info.get('input_name')
    
    if not action or not input_name:
        return {"success": False, "message": "Thiếu thông tin action/input. Đã refresh dịch vụ, thử lại!"}
    
    action_url = f"{base_url}/{action}" if not action.startswith('http') else action
    search_data = {input_name: url}
    
    ajax_headers = {
        'accept': '*/*',
        'accept-language': 'vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'origin': base_url,
        'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': st["user_agent"],
        'x-requested-with': 'XMLHttpRequest',
        'referer': f'{base_url}/'
    }
    
    decoded_response = None
    for attempt in range(3):
        try:
            r = session.post(action_url, headers=ajax_headers, data=search_data, timeout=45)
            decoded_response = _decode_response(r.text)
            
            timer = _extract_timer(decoded_response)
            if timer and timer > 0:
                st["cooldown_until"] = time.time() + timer
                return {"success": False, "cooldown": timer, "message": f"Đang chờ {timer}s"}
            
            soup = BeautifulSoup(decoded_response, 'html.parser')
            form = soup.find('form')
            submit_btn = soup.find('button', class_=re.compile(r'wbutton|btn|submit'))
            
            if form or submit_btn:
                break
            
            if attempt < 2:
                time.sleep(2.5)
        except Exception as e:
            if attempt == 2:
                return {"success": False, "message": f"Lỗi kết nối: {str(e)}"}
            time.sleep(2)
    
    if not decoded_response:
        return {"success": False, "message": "Không nhận được phản hồi"}
    
    soup = BeautifulSoup(decoded_response, 'html.parser')
    form = soup.find('form')
    submit_btn = soup.find('button', class_=re.compile(r'wbutton|btn|submit'))
    
    if form or submit_btn:
        target_form = form if form else (submit_btn.find_parent('form') if submit_btn else None)
        
        if target_form:
            submit_action = target_form.get('action')
            if not submit_action or submit_action.strip() == "" or submit_action == "/":
                submit_action = action
            
            submit_data = {}
            for inp in target_form.find_all('input'):
                name = inp.get('name')
                val = inp.get('value', '')
                if name:
                    submit_data[name] = val
            
            selects = target_form.find_all('select')
            for sel in selects:
                name = sel.get('name')
                if not name:
                    continue
                options = sel.find_all('option')
                max_val = None
                max_int = -1
                for opt in options:
                    val = opt.get('value', '').strip()
                    if not val:
                        continue
                    try:
                        val_int = int(val)
                        if val_int > max_int:
                            max_int = val_int
                            max_val = val
                    except ValueError:
                        if max_val is None:
                            max_val = val
                if max_val is not None:
                    submit_data[name] = max_val
            
            if input_name not in submit_data:
                submit_data[input_name] = url
            
            actual_btn = target_form.find('button', type='submit') if target_form else submit_btn
            if actual_btn and actual_btn.get('name'):
                submit_data[actual_btn.get('name')] = actual_btn.get('value', '')
            
            submit_url = f"{base_url}/{submit_action}" if not submit_action.startswith('http') else submit_action
            try:
                boost_r = session.post(submit_url, headers=ajax_headers, data=submit_data, timeout=45)
                decoded_boost = _decode_response(boost_r.text)
                
                amount, kind, msg = _parse_result(decoded_boost)
                
                if not msg:
                    soup_clean = BeautifulSoup(decoded_boost, 'html.parser')
                    msg = soup_clean.get_text(separator=' ').strip()[:200]
                
                timer = _extract_timer(decoded_boost)
                if timer and timer > 0:
                    st["cooldown_until"] = time.time() + timer
                
                return {
                    "success": True,
                    "amount": amount or 100,
                    "kind": kind or "unit",
                    "message": msg or "Thành công",
                    "cooldown": timer
                }
            except Exception as e:
                return {"success": False, "message": f"Lỗi submit: {str(e)}"}
    
    amount, kind, msg = _parse_result(decoded_response)
    timer = _extract_timer(decoded_response)
    if timer and timer > 0:
        st["cooldown_until"] = time.time() + timer
    
    return {
        "success": True,
        "amount": amount or 100,
        "kind": kind or "unit",
        "message": msg or "Thành công",
        "cooldown": timer
    }

# ============== Pydantic models ==============
class StartReq(BaseModel):
    pass

class SolveReq(BaseModel):
    session_id: str
    answer: str

class SidReq(BaseModel):
    session_id: str

class RunReq(BaseModel):
    session_id: str
    service: str
    url: str

# ============== Routes ==============
from fastapi.responses import FileResponse

@app.get("/")
def root():
    return FileResponse("index.html")

@app.get("/api")
def api_info():
    return {
        "endpoints": [
            "/api/start",
            "/api/solve",
            "/api/services",
            "/api/run",
            "/api/refresh_captcha"
        ],
        "sessions_active": len(SESSIONS),
        "version": "2.0.0"
    }

@app.get("/health")
def health():
    return {"ok": True, "sessions": len(SESSIONS)}

@app.post("/api/start")
def start(_: StartReq = StartReq()):
    """Tạo session mới + lấy captcha."""
    sid = uuid.uuid4().hex
    st = _new_session_state()
    
    try:
        _init_session(st)
        img_data = _get_captcha_image(st)
        st["captcha_b64"] = base64.b64encode(img_data).decode("ascii")
        SESSIONS[sid] = st
        return {
            "session_id": sid,
            "captcha_b64": st["captcha_b64"],
            "captcha_mime": "image/png",
        }
    except Exception as e:
        raise HTTPException(500, f"Khởi tạo thất bại: {str(e)}")

@app.post("/api/refresh_captcha")
def refresh_captcha(req: SidReq):
    st = _get(req.session_id)
    try:
        img_data = _get_captcha_image(st)
        st["captcha_b64"] = base64.b64encode(img_data).decode("ascii")
        return {"captcha_b64": st["captcha_b64"], "captcha_mime": "image/png"}
    except Exception as e:
        raise HTTPException(500, f"Refresh captcha thất bại: {str(e)}")

@app.post("/api/solve")
def solve(req: SolveReq):
    st = _get(req.session_id)
    ans = re.sub(r"[^a-zA-Z]", "", req.answer or "").lower()
    if not ans:
        raise HTTPException(400, "Captcha answer rỗng")
    
    try:
        result = _submit_captcha(st, ans)
        if not result:
            # Refresh captcha on fail
            img_data = _get_captcha_image(st)
            st["captcha_b64"] = base64.b64encode(img_data).decode("ascii")
            return {
                "ok": False,
                "message": "Captcha sai, thử lại",
                "captcha_b64": st.get("captcha_b64"),
            }
        
        _refresh_services(st)
        services = st.get("services", [])
        service_map = st.get("service_map", {})
        
        return {
            "ok": True,
            "answer": ans,
            "services": [
                {
                    "name": s.get("title", ""),
                    "status": s.get("status", ""),
                    "available": bool(s.get("available", False)),
                    "has_action": s.get("title", "") in service_map,
                }
                for s in services
            ],
        }
    except Exception as e:
        raise HTTPException(500, f"Giải captcha thất bại: {str(e)}")

@app.post("/api/services")
def services(req: SidReq):
    st = _get(req.session_id)
    try:
        _refresh_services(st)
        services = st.get("services", [])
        service_map = st.get("service_map", {})
        
        return {
            "services": [
                {
                    "name": s.get("title", ""),
                    "status": s.get("status", ""),
                    "available": bool(s.get("available", False)),
                    "has_action": s.get("title", "") in service_map,
                }
                for s in services
            ],
            "total_sent": st.get("total_sent", 0),
        }
    except Exception as e:
        raise HTTPException(500, f"Lấy services thất bại: {str(e)}")

@app.post("/api/run")
def run(req: RunReq):
    st = _get(req.session_id)
    
    try:
        # Check cooldown first
        now = time.time()
        if st.get("cooldown_until", 0) > now:
            remaining = int(st["cooldown_until"] - now)
            return {
                "ok": False,
                "cooldown": remaining,
                "message": f"Đang cooldown {remaining}s",
                "total_sent": st.get("total_sent", 0),
                "service": req.service,
            }
        
        result = _perform_action(st, req.service, req.url)
        
        if result.get("success"):
            amount = result.get("amount", 0)
            st["total_sent"] = st.get("total_sent", 0) + amount
            st["last_run"] = time.time()
            
            return {
                "ok": True,
                "amount": amount,
                "kind": result.get("kind", "unit"),
                "message": result.get("message", "Thành công"),
                "cooldown": result.get("cooldown"),
                "total_sent": st.get("total_sent", 0),
                "service": req.service,
            }
        else:
            return {
                "ok": False,
                "message": result.get("message", "Lỗi không xác định"),
                "cooldown": result.get("cooldown"),
                "total_sent": st.get("total_sent", 0),
                "service": req.service,
            }
    except Exception as e:
        raise HTTPException(500, f"Chạy buff thất bại: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
