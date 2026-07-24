"""
Zefoy Web API - FastAPI với logic từ buff.py
Fix cho layout mới của Zefoy
"""

from __future__ import annotations

import os
import re
import sys
import time
import json
import base64
import uuid
import random
import urllib.parse
from typing import Any, Optional, Dict, List
from string import ascii_letters, digits

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup

# ============================================================
# LOGGING
# ============================================================
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(title="Zefoy Bot API", version="3.0.3")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# ZEFOY BOT LOGIC (TỪ buff.py)
# ============================================================

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
DEFAULT_BASE_URL = "https://zefoy.com"

def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    cookies = {}
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            k, v = item.split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies

def decode_zefoy_response(text: str) -> str:
    """Decode response từ Zefoy (base64 ngược) - GIỐNG buff.py"""
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

def clean_html_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, 'html.parser')
    return soup.get_text(separator=' ').strip()

def extract_cooldown_seconds(decoded_response: str) -> tuple:
    """Trích xuất thời gian chờ - GIỐNG buff.py"""
    soup = BeautifulSoup(decoded_response, 'html.parser')
    
    countdown_tag = soup.find(id='login-countdown') or soup.find(class_=re.compile(r'countdown'))
    countdown_text = countdown_tag.text.strip() if countdown_tag else ""
    
    text_clean = clean_html_text(decoded_response)
    if not countdown_text:
        countdown_text = text_clean

    min_match = re.search(r'(\d+)\s*minute', countdown_text, re.IGNORECASE)
    sec_match = re.search(r'(\d+)\s*second', countdown_text, re.IGNORECASE)
    
    if min_match or sec_match:
        minutes = int(min_match.group(1)) if min_match else 0
        seconds = int(sec_match.group(1)) if sec_match else 0
        total = (minutes * 60) + seconds
        if total > 0:
            return total, f"Please wait {minutes} minute(s) {seconds} second(s)"

    js_patterns = [
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
        r'seconds\s*=\s*(\d+)'
    ]
    for pattern in js_patterns:
        match = re.search(pattern, decoded_response, re.IGNORECASE)
        if match:
            secs = int(match.group(1))
            if secs > 0:
                mins = secs // 60
                rem_secs = secs % 60
                return secs, f"Please wait {mins} minute(s) {rem_secs} second(s)"

    if 'checking timer' in text_clean.lower() or 'timer' in text_clean.lower() or 'please wait' in text_clean.lower():
        return 120, "Checking Timer... (Mặc định 120s cooldown)"

    return 0, ""

def get_services(session: requests.Session) -> tuple:
    """Lấy danh sách dịch vụ - FIX cho layout mới của Zefoy"""
    try:
        r = session.get('https://zefoy.com/')
        html_content = decode_zefoy_response(r.text)
        
        soup = BeautifulSoup(html_content, 'html.parser')
        services = []
        
        # CÁCH 1: Tìm card service từ class chứa 'col-'
        cards = soup.find_all('div', class_=re.compile(r'col-(?:lg|md|sm|xs)-[0-9]+'))
        
        # CÁCH 2: Tìm div có chứa button t-*-button
        if not cards or len(cards) < 2:
            cards = []
            buttons = soup.find_all('button', class_=re.compile(r't-[a-z]+-button'))
            for btn in buttons:
                parent = btn.parent
                while parent and parent.name != 'div':
                    parent = parent.parent
                if parent and parent not in cards:
                    cards.append(parent)
        
        # CÁCH 3: Tìm div có class chứa 'service' hoặc 'menu'
        if not cards or len(cards) < 2:
            cards = soup.find_all('div', class_=re.compile(r'service|menu|widget|box|card'))
        
        # CÁCH 4: Quét tất cả div có class
        if not cards or len(cards) < 2:
            cards = soup.find_all('div', class_=True)
        
        seen_titles = set()
        for card in cards:
            try:
                title_tag = card.find('h5') or card.find('h4') or card.find('h3') or card.find('strong')
                if not title_tag:
                    continue
                
                title = title_tag.text.strip()
                if not title or len(title) < 2 or title in seen_titles:
                    continue
                
                if any(x in title.lower() for x in ['join', 'youtube', 'telegram', 'copyright', 'follow', 'soon', 'update', 'zefoy', 'home', 'welcome', 'terms', 'privacy', 'contact']):
                    continue
                
                seen_titles.add(title)
                
                btn = card.find('button')
                if not btn:
                    btn = card.find('input', type='submit')
                
                is_active = True
                if btn and hasattr(btn, 'attrs'):
                    is_active = 'disabled' not in btn.attrs
                
                btn_class = ""
                if btn and hasattr(btn, 'get'):
                    for cls in btn.get('class', []):
                        if isinstance(cls, str) and cls.startswith('t-') and cls.endswith('-button'):
                            btn_class = cls
                            break
                
                status_tag = card.find(class_='badge') or card.find('small') or card.find('span', class_=re.compile(r'status|badge|label|alert'))
                status_text = status_tag.text.strip() if status_tag else ("ON" if is_active else "OFF")
                
                menu_class = ""
                if btn_class:
                    menu_class = btn_class.replace('-button', '-menu')
                else:
                    form = card.find('form')
                    if form:
                        for cls in form.get('class', []):
                            if isinstance(cls, str) and 'menu' in cls:
                                menu_class = cls
                                break
                
                if not menu_class:
                    form = card.find('form')
                    if form:
                        parent = form.parent
                        while parent:
                            if parent.name == 'div' and parent.get('class'):
                                for cls in parent.get('class', []):
                                    if isinstance(cls, str) and ('menu' in cls or 'form' in cls):
                                        menu_class = cls
                                        break
                                if menu_class:
                                    break
                            parent = parent.parent
                
                services.append({
                    'name': title,
                    'active': is_active,
                    'status': status_text,
                    'btn_class': btn_class,
                    'menu_class': menu_class
                })
                
            except Exception as e:
                continue
        
        return services, html_content
        
    except Exception as e:
        logger.error(f"Error in get_services: {e}")
        return [], ""

def get_service_form(html_content: str, menu_class: str) -> Optional[Dict]:
    """Lấy form cho dịch vụ - FIX cho layout mới"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        if menu_class:
            menu_div = soup.find('div', class_=menu_class)
            if menu_div:
                form = menu_div.find('form')
                if form:
                    return extract_form_data(form)
        
        forms = soup.find_all('form')
        for form in forms:
            title_tag = form.find_previous('h5') or form.find_previous('h4') or form.find_previous('h3')
            if title_tag:
                title = title_tag.text.strip()
                if menu_class and title.lower().replace(' ', '-') in menu_class.lower():
                    return extract_form_data(form)
        
        for form in forms:
            search_input = form.find('input', type='search') or form.find('input', class_=re.compile(r'search|form-control'))
            if search_input:
                return extract_form_data(form)
        
        for form in forms:
            action = form.get('action', '')
            if 'c2VuZ' in action:
                return extract_form_data(form)
        
        if forms:
            return extract_form_data(forms[0])
        
        return None
        
    except Exception as e:
        logger.error(f"Error in get_service_form: {e}")
        return None

def extract_form_data(form) -> Optional[Dict]:
    try:
        action = form.get('action', '')
        if action and not action.startswith('http'):
            action = action.lstrip('/')
        
        search_input = form.find('input', type='search') or form.find('input', class_=re.compile(r'search|form-control'))
        input_name = search_input.get('name') if search_input else None
        
        if not input_name:
            for inp in form.find_all('input'):
                inp_type = inp.get('type', 'text').lower()
                if inp_type in ['search', 'text'] and inp.get('name'):
                    input_name = inp.get('name')
                    break
        
        return {
            'action': action,
            'input_name': input_name,
            'form': form
        }
    except:
        return None

# ============================================================
# ZEFOY BOT CLASS
# ============================================================

class ZefoyBot:
    def __init__(self, cookie_string: str, user_agent: str = None):
        self.cookie_string = cookie_string
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.session = self._setup_session()
        self.services = []
        self.home_html = ""
        
    def _setup_session(self) -> requests.Session:
        session = requests.Session()
        cookies = parse_cookie_string(self.cookie_string)
        session.cookies.update(cookies)
        
        session.headers.update({
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.7',
            'sec-ch-ua': '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': self.user_agent,
        })
        return session
    
    def authenticate(self) -> bool:
        try:
            r = self.session.get('https://zefoy.com/')
            html_content = decode_zefoy_response(r.text)
            
            if 't-followers-button' in html_content or 't-hearts-button' in html_content or 'colsmenu' in html_content:
                return True
            
            if 'card-title' in html_content or 'col-' in html_content:
                soup = BeautifulSoup(html_content, 'html.parser')
                buttons = soup.find_all('button', class_=re.compile(r't-[a-z]+-button'))
                if buttons:
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return False
    
    def get_services_list(self) -> List[Dict]:
        services, home_html = get_services(self.session)
        self.services = services
        self.home_html = home_html
        return services
    
    def boost(self, video_url: str, service_name: str, max_runs: int = 10) -> Dict:
        results = {
            'success': False,
            'message': '',
            'runs': 0,
            'errors': []
        }
        
        try:
            if not self.services:
                self.get_services_list()
            
            selected_service = None
            for s in self.services:
                if service_name.lower() in s['name'].lower():
                    selected_service = s
                    break
                if any(word in s['name'].lower() for word in service_name.lower().split()):
                    selected_service = s
                    break
            
            if not selected_service:
                results['message'] = f'Không tìm thấy dịch vụ "{service_name}"'
                return results
            
            if not selected_service['active']:
                results['message'] = f'Dịch vụ "{selected_service["name"]}" đang bảo trì'
                return results
            
            form_info = get_service_form(self.home_html, selected_service.get('menu_class', ''))
            if not form_info or not form_info.get('action') or not form_info.get('input_name'):
                r = self.session.get('https://zefoy.com/')
                html_content = decode_zefoy_response(r.text)
                form_info = get_service_form(html_content, selected_service.get('menu_class', ''))
                
            if not form_info or not form_info.get('action') or not form_info.get('input_name'):
                results['message'] = f'Không tìm thấy form cho dịch vụ {selected_service["name"]}'
                return results
            
            action_url = f"https://zefoy.com/{form_info['action'].lstrip('/')}"
            input_name = form_info['input_name']
            
            ajax_headers = {
                'accept': '*/*',
                'accept-language': 'vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.7',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': 'https://zefoy.com',
                'referer': 'https://zefoy.com/',
                'x-requested-with': 'XMLHttpRequest',
                'user-agent': self.user_agent,
            }
            
            runs = 0
            while runs < max_runs:
                try:
                    search_data = {input_name: video_url}
                    
                    r = self.session.post(action_url, headers=ajax_headers, data=search_data)
                    decoded_response = decode_zefoy_response(r.text)
                    
                    soup = BeautifulSoup(decoded_response, 'html.parser')
                    total_wait, countdown_text = extract_cooldown_seconds(decoded_response)
                    
                    if total_wait > 0:
                        results['errors'].append(f"Cooldown: {countdown_text}")
                        results['message'] = f"Đang chờ cooldown: {countdown_text}"
                        return results
                    
                    submit_btn = soup.find('button', class_=re.compile(r'wbutton|btn|submit'))
                    if not submit_btn:
                        submit_btn = soup.find('input', type='submit')
                    
                    if submit_btn:
                        target_form = submit_btn.find_parent('form')
                        if not target_form:
                            target_form = soup.find('form')
                        
                        if target_form:
                            submit_action = target_form.get('action', '')
                            if submit_action and not submit_action.startswith('http'):
                                submit_action = f"https://zefoy.com/{submit_action.lstrip('/')}"
                            elif not submit_action:
                                submit_action = action_url
                            
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
                            
                            if submit_btn.get('name'):
                                submit_data[submit_btn.get('name')] = submit_btn.get('value', '')
                            
                            boost_r = self.session.post(submit_action, headers=ajax_headers, data=submit_data)
                            decoded_boost = decode_zefoy_response(boost_r.text)
                            result_text = clean_html_text(decoded_boost)
                            
                            if not result_text:
                                result_text = "Boost thành công!"
                            
                            runs += 1
                            results['runs'] = runs
                            results['message'] = result_text
                            results['success'] = True
                            
                            if runs < max_runs:
                                time.sleep(10)
                        else:
                            results['errors'].append("Không tìm thấy form submit")
                            break
                    else:
                        if 'please wait' in decoded_response.lower() or 'wait' in decoded_response.lower():
                            total_wait, _ = extract_cooldown_seconds(decoded_response)
                            if total_wait > 0:
                                results['errors'].append(f"Đang chờ cooldown: {total_wait}s")
                                results['message'] = f"Cooldown {total_wait}s"
                                return results
                        
                        results['errors'].append("Không tìm thấy nút submit")
                        break
                        
                except Exception as e:
                    results['errors'].append(str(e))
                    break
                    
        except Exception as e:
            results['message'] = f"Lỗi: {e}"
            results['errors'].append(str(e))
            
        return results

# ============================================================
# SESSION STORE
# ============================================================

SESSIONS: Dict[str, Dict] = {}
SESSION_TTL = 60 * 30

def _new_session_state(cookie_string: str = "", user_agent: str = "") -> Dict:
    return {
        "bot": ZefoyBot(cookie_string, user_agent or DEFAULT_USER_AGENT),
        "created": time.time(),
        "last_used": time.time(),
        "total_sent": 0,
        "services": []
    }

def _get_session(session_id: str) -> Dict:
    _gc()
    st = SESSIONS.get(session_id)
    if not st:
        raise HTTPException(404, "Session không tồn tại. Vui lòng tạo session mới.")
    st["last_used"] = time.time()
    return st

def _gc():
    now = time.time()
    dead = [k for k, v in SESSIONS.items() if now - v["last_used"] > SESSION_TTL]
    for k in dead:
        SESSIONS.pop(k, None)

# ============================================================
# PYDANTIC MODELS
# ============================================================

class StartRequest(BaseModel):
    cookie_string: str
    user_agent: Optional[str] = None

class SolveRequest(BaseModel):
    session_id: str
    answer: str

class SessionRequest(BaseModel):
    session_id: str

class BoostRequest(BaseModel):
    session_id: str
    video_url: str
    service: str
    max_runs: int = 10

# ============================================================
# API ROUTES
# ============================================================

@app.get("/")
async def root():
    return {
        "name": "Zefoy Bot API",
        "version": "3.0.3",
        "status": "online",
        "endpoints": [
            "/api/start",
            "/api/solve",
            "/api/services",
            "/api/boost",
            "/api/status"
        ]
    }

@app.post("/api/start")
async def start_session(req: StartRequest):
    """Tạo session mới với cookie"""
    if not req.cookie_string:
        raise HTTPException(400, "cookie_string không được để trống")
    
    session_id = uuid.uuid4().hex
    st = _new_session_state(req.cookie_string, req.user_agent)
    bot: ZefoyBot = st["bot"]
    
    # Kiểm tra auth
    if not bot.authenticate():
        raise HTTPException(401, "Cookie không hợp lệ hoặc đã hết hạn")
    
    # Lấy services
    services = bot.get_services_list()
    st["services"] = services
    
    SESSIONS[session_id] = st
    
    return {
        "session_id": session_id,
        "success": True,
        "services": [
            {
                "name": s["name"],
                "active": s["active"],
                "status": s["status"]
            }
            for s in services
        ]
    }

@app.post("/api/services")
async def get_services(req: SessionRequest):
    """Lấy danh sách dịch vụ"""
    st = _get_session(req.session_id)
    bot: ZefoyBot = st["bot"]
    
    services = bot.get_services_list()
    st["services"] = services
    
    return {
        "success": True,
        "services": [
            {
                "name": s["name"],
                "active": s["active"],
                "status": s["status"]
            }
            for s in services
        ]
    }

@app.post("/api/boost")
async def boost(req: BoostRequest):
    """Thực hiện boost"""
    st = _get_session(req.session_id)
    bot: ZefoyBot = st["bot"]
    
    # Kiểm tra auth
    if not bot.authenticate():
        raise HTTPException(401, "Session đã hết hạn. Vui lòng tạo session mới.")
    
    # Thực hiện boost
    result = bot.boost(req.video_url, req.service, req.max_runs)
    
    if result.get("success"):
        st["total_sent"] = st.get("total_sent", 0) + result.get("runs", 0)
        result["total_sent"] = st["total_sent"]
    
    return result

@app.post("/api/status")
async def get_status(req: SessionRequest):
    """Kiểm tra trạng thái session"""
    st = _get_session(req.session_id)
    bot: ZefoyBot = st["bot"]
    
    is_auth = bot.authenticate()
    
    return {
        "success": True,
        "authenticated": is_auth,
        "total_sent": st.get("total_sent", 0),
        "services": len(st.get("services", []))
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "sessions": len(SESSIONS)}

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
