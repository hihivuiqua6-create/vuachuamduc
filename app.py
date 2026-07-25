# app.py - Version mới dùng logic từ TOOL SOUCRE.py
"""
Zefoy Web API - Dùng logic mới từ TOOL SOUCRE.py
Deploy lên Render.com
"""

from __future__ import annotations

import os
import re
import time
import json
import base64
import hashlib
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
from urllib.parse import unquote
from io import BytesIO

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup

# ============== CONFIG ==============
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_BASE_URL = "https://zefoy.com"

# ============== ZEFOY CLIENT (từ TOOL SOUCRE.py) ==============
class ZefoyClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.user_agent = DEFAULT_USER_AGENT
        self.base_url = DEFAULT_BASE_URL
        self._services = []
        self._service_map = {}
        self._video_key = None
        self._update_headers()
    
    def _update_headers(self):
        self.session.headers.update({
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
            'user-agent': self.user_agent,
        })
    
    def initialize(self) -> bool:
        """Khởi tạo session với zefoy.com"""
        try:
            resp = self.session.get(f"{self.base_url}/", timeout=30)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"Init error: {e}")
            return False
    
    def get_captcha_image(self) -> Optional[bytes]:
        """Lấy ảnh captcha từ zefoy.com"""
        try:
            # Lấy PHPSESSID trước
            if not self.session.cookies.get("PHPSESSID"):
                self.initialize()
            
            ts = int(time.time())
            url = f"{self.base_url}/?getcapthca={ts}"
            headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.base_url}/",
            }
            resp = self.session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            
            data = resp.json()
            if not data:
                return None
            
            # Lấy encoded path
            encoded = None
            key = hashlib.md5(self.user_agent.encode()).hexdigest()
            if key in data:
                encoded = data[key]
            elif len(data) == 1:
                encoded = next(iter(data.values()))
            else:
                return None
            
            # Decode path
            once = base64.b64decode(encoded)
            twice = base64.b64decode(once)
            image_path = twice.decode('utf-8').strip()
            
            if not image_path.startswith("/"):
                image_path = "/" + image_path
            
            # Download image
            img_url = f"{self.base_url}{image_path}"
            resp = self.session.get(img_url, timeout=30)
            resp.raise_for_status()
            
            return resp.content
            
        except Exception as e:
            print(f"Captcha error: {e}")
            return None
    
    def solve_captcha(self, answer: str) -> bool:
        """Gửi captcha answer lên zefoy"""
        try:
            answer = re.sub(r"[^a-zA-Z]", "", answer or "").lower()
            if not answer:
                return False
            
            # Build captcha_encoded (fingerprint)
            fingerprint = {
                "deviceInfo": {
                    "cpuCores": 8,
                    "deviceMemoryGB": 8,
                    "platform": "Win32",
                    "maxTouchPoints": 0,
                },
                "browserInfo": {
                    "userAgent": self.user_agent,
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
                "storageInfo": {
                    "localStorage": "Yes",
                    "sessionStorage": "Yes",
                    "indexedDB": "Yes",
                }
            }
            plaintext = json.dumps(fingerprint, separators=(',', ':'))
            encoded = base64.b64encode(plaintext.encode()).decode()
            
            data = {
                "captchalogin": answer,
                "captcha_encoded": encoded,
            }
            
            resp = self.session.post(
                f"{self.base_url}/",
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": self.base_url,
                    "Referer": f"{self.base_url}/",
                },
                timeout=30
            )
            
            if resp.text.strip().lower() == "success":
                self._refresh_services()
                return True
            return False
            
        except Exception as e:
            print(f"Solve error: {e}")
            return False
    
    def _refresh_services(self):
        """Lấy danh sách dịch vụ từ zefoy"""
        try:
            resp = self.session.get(f"{self.base_url}/", timeout=30)
            html = resp.text or ""
            
            soup = BeautifulSoup(html, 'html.parser')
            self._services = []
            self._service_map = {}
            
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
                }
                
                self._services.append(service_info)
                
                if is_active and action and input_name:
                    self._service_map[title] = service_info
                    if input_name:
                        self._video_key = input_name
                        
        except Exception as e:
            print(f"Refresh services error: {e}")
    
    def get_services(self) -> List[dict]:
        if not self._services:
            self._refresh_services()
        return self._services
    
    def perform_action(self, service: str, url: str) -> Dict[str, Any]:
        """Thực hiện buff cho 1 dịch vụ"""
        try:
            svc_info = self._service_map.get(service)
            if not svc_info:
                return {"success": False, "message": f"Service '{service}' không tồn tại"}
            
            if not svc_info.get("available"):
                return {"success": False, "message": f"Service '{service}' hiện không khả dụng"}
            
            action = svc_info.get('action')
            input_name = svc_info.get('input_name')
            
            if not action or not input_name:
                return {"success": False, "message": "Thiếu thông tin action/input. Đã refresh dịch vụ, thử lại!"}
            
            action_url = f"{self.base_url}/{action}" if not action.startswith('http') else action
            search_data = {input_name: url}
            
            # Headers cho AJAX
            ajax_headers = {
                'accept': '*/*',
                'accept-language': 'vi-VN,vi;q=0.9',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': self.base_url,
                'user-agent': self.user_agent,
                'x-requested-with': 'XMLHttpRequest',
                'referer': f'{self.base_url}/'
            }
            
            decoded_response = None
            for attempt in range(3):
                r = self.session.post(action_url, headers=ajax_headers, data=search_data, timeout=45)
                decoded_response = self._decode_response(r.text)
                
                timer = self._extract_timer(decoded_response)
                if timer and timer > 0:
                    return {"success": False, "cooldown": timer, "message": f"Đang chờ {timer}s"}
                
                soup = BeautifulSoup(decoded_response, 'html.parser')
                form = soup.find('form')
                submit_btn = soup.find('button', class_=re.compile(r'wbutton|btn|submit'))
                
                if form or submit_btn:
                    break
                
                if attempt < 2:
                    time.sleep(2.5)
            
            if not decoded_response:
                return {"success": False, "message": "Không nhận được phản hồi"}
            
            # Xử lý form confirm nếu có
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
                    
                    submit_url = f"{self.base_url}/{submit_action}" if not submit_action.startswith('http') else submit_action
                    boost_r = self.session.post(submit_url, headers=ajax_headers, data=submit_data, timeout=45)
                    
                    decoded_boost = self._decode_response(boost_r.text)
                    
                    amount, kind, msg = self._parse_result(decoded_boost)
                    
                    if not msg:
                        soup_clean = BeautifulSoup(decoded_boost, 'html.parser')
                        msg = soup_clean.get_text(separator=' ').strip()[:200]
                    
                    return {
                        "success": True,
                        "amount": amount or 100,
                        "kind": kind or "unit",
                        "message": msg or "Thành công",
                        "cooldown": self._extract_timer(decoded_boost)
                    }
            
            amount, kind, msg = self._parse_result(decoded_response)
            return {
                "success": True,
                "amount": amount or 100,
                "kind": kind or "unit",
                "message": msg or "Thành công",
                "cooldown": self._extract_timer(decoded_response)
            }
            
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    def _decode_response(self, text: str) -> str:
        """Decode response từ zefoy (base64 reversed)"""
        text = text.strip()
        if not text:
            return text
        
        def try_decode(val):
            try:
                reversed_val = val[::-1]
                url_decoded = unquote(reversed_val)
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
    
    def _extract_timer(self, html: str) -> Optional[int]:
        """Trích xuất cooldown timer từ HTML"""
        if not html:
            return None
        
        patterns = [
            r'var\s+ltm\s*=\s*(\d+)',
            r'ltm\s*=\s*(\d+)',
            r'var\s+time\s*=\s*(\d+)',
            r'var\s+timeleft\s*=\s*(\d+)',
            r'Please wait\s+(\d+)\s+seconds',
            r'(\d+)\s*minute\(s\)\s*(\d+)\s*second',
            r'wait\s+(\d+)\s*seconds',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                if len(m.groups()) == 2:
                    return int(m.group(1)) * 60 + int(m.group(2))
                return int(m.group(1))
        return None
    
    def _parse_result(self, html: str) -> tuple[Optional[int], Optional[str], Optional[str]]:
        """Parse số lượng đã gửi từ HTML"""
        if not html:
            return None, None, None
        
        patterns = [
            (r"Sent\s+(\d+)\s+([A-Za-z]+)", 1, 2),
            (r"Successfully\s+sent\s+(\d+)\s+([A-Za-z]+)", 1, 2),
            (r"\+\s*(\d+)\s+([A-Za-z]+)", 1, 2),
            (r"(\d+)\s+(views?|hearts?|followers?|shares?|likes?)", 1, 2),
            (r"Added\s+(\d+)\s+([A-Za-z]+)", 1, 2),
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
        
        return None, None, None


# ============== FASTAPI APP ==============
app = FastAPI(title="Zefoy Web API v2", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session store
SESSIONS: Dict[str, dict] = {}

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


@app.get("/")
def root():
    return {
        "name": "Zefoy Web API v2",
        "version": "2.0.0",
        "endpoints": [
            "/api/start",
            "/api/solve", 
            "/api/services",
            "/api/run"
        ]
    }


@app.post("/api/start")
def start(_: StartReq = StartReq()):
    """Tạo session mới + lấy captcha"""
    sid = uuid.uuid4().hex
    client = ZefoyClient()
    client.initialize()
    
    img_data = client.get_captcha_image()
    if not img_data:
        raise HTTPException(500, "Không thể lấy captcha từ Zefoy")
    
    SESSIONS[sid] = {
        "client": client,
        "created": time.time(),
        "last_used": time.time(),
        "total_sent": 0
    }
    
    return {
        "session_id": sid,
        "captcha_b64": base64.b64encode(img_data).decode("ascii")
    }


@app.post("/api/solve")
def solve(req: SolveReq):
    """Giải captcha"""
    session = SESSIONS.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session không tồn tại")
    
    client: ZefoyClient = session["client"]
    success = client.solve_captcha(req.answer)
    
    if success:
        services = client.get_services()
        return {
            "ok": True,
            "services": [
                {
                    "name": s["title"],
                    "available": s.get("available", False),
                    "status": s.get("status", "Unknown")
                }
                for s in services
            ]
        }
    else:
        # Lấy captcha mới
        img_data = client.get_captcha_image()
        return {
            "ok": False,
            "message": "Captcha sai, thử lại",
            "captcha_b64": base64.b64encode(img_data).decode("ascii") if img_data else None
        }


@app.post("/api/services")
def services(req: SidReq):
    """Lấy danh sách dịch vụ"""
    session = SESSIONS.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session không tồn tại")
    
    client: ZefoyClient = session["client"]
    services = client.get_services()
    
    return {
        "services": [
            {
                "name": s["title"],
                "available": s.get("available", False),
                "status": s.get("status", "Unknown")
            }
            for s in services
        ],
        "total_sent": session.get("total_sent", 0)
    }


@app.post("/api/run")
def run(req: RunReq):
    """Thực hiện buff"""
    session = SESSIONS.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session không tồn tại")
    
    client: ZefoyClient = session["client"]
    result = client.perform_action(req.service, req.url)
    
    if result.get("success"):
        amount = result.get("amount", 0)
        session["total_sent"] = session.get("total_sent", 0) + amount
        
        return {
            "ok": True,
            "amount": amount,
            "kind": result.get("kind", "unit"),
            "message": result.get("message", "Thành công"),
            "cooldown": result.get("cooldown"),
            "total_sent": session["total_sent"]
        }
    else:
        return {
            "ok": False,
            "message": result.get("message", "Lỗi không xác định"),
            "cooldown": result.get("cooldown")
        }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
