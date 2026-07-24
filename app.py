"""
Zefoy Web API + Giao diện Web - FastAPI
Logic từ buff.py gốc, fix layout mới của Zefoy
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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
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
    try:
        r = session.get('https://zefoy.com/')
        html_content = decode_zefoy_response(r.text)
        
        soup = BeautifulSoup(html_content, 'html.parser')
        services = []
        
        cards = soup.find_all('div', class_=re.compile(r'col-(?:lg|md|sm|xs)-[0-9]+'))
        
        if not cards or len(cards) < 2:
            cards = []
            buttons = soup.find_all('button', class_=re.compile(r't-[a-z]+-button'))
            for btn in buttons:
                parent = btn.parent
                while parent and parent.name != 'div':
                    parent = parent.parent
                if parent and parent not in cards:
                    cards.append(parent)
        
        if not cards or len(cards) < 2:
            cards = soup.find_all('div', class_=re.compile(r'service|menu|widget|box|card'))
        
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

class SessionRequest(BaseModel):
    session_id: str

class BoostRequest(BaseModel):
    session_id: str
    video_url: str
    service: str
    max_runs: int = 10

# ============================================================
# GIAO DIỆN WEB HTML
# ============================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔮 Zefoy Bot - TikTok Tool</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap');
        
        :root {
            --primary: #00ff50;
            --secondary: #00e5ff;
            --danger: #ff2e63;
            --warning: #ffaa00;
            --bg-dark: #0a0a0a;
            --bg-card: #111111;
            --bg-input: #1a1a1a;
            --border-color: #00ff50;
            --text-color: #00ff50;
            --text-muted: #888888;
        }
        
        body {
            font-family: 'Share Tech Mono', monospace;
            background: var(--bg-dark);
            color: var(--text-color);
            min-height: 100vh;
            overflow-x: hidden;
        }
        
        #matrix {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
            opacity: 0.06;
            pointer-events: none;
        }
        
        .container {
            position: relative;
            z-index: 1;
            max-width: 900px;
            margin: 20px auto;
            padding: 25px;
            background: rgba(10, 10, 10, 0.92);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            box-shadow: 0 0 20px rgba(0,255,80,0.1);
            backdrop-filter: blur(10px);
            animation: fadeIn 0.8s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .header {
            text-align: center;
            padding-bottom: 20px;
            border-bottom: 1px solid rgba(0,255,80,0.15);
            margin-bottom: 20px;
        }
        .glitch {
            font-family: 'Orbitron', monospace;
            font-size: 2.5em;
            font-weight: 900;
            color: var(--primary);
            text-shadow: 0 0 30px rgba(0,255,80,0.3);
            letter-spacing: 4px;
            position: relative;
            display: inline-block;
        }
        .glitch::before, .glitch::after {
            content: attr(data-text);
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0.7;
        }
        .glitch::before { color: var(--danger); z-index: -1; animation: glitch1 3s infinite; }
        .glitch::after { color: var(--secondary); z-index: -2; animation: glitch2 3s infinite; }
        @keyframes glitch1 {
            0%,100%{transform:translate(0)}
            20%{transform:translate(-2px,2px)}
            40%{transform:translate(2px,-2px)}
            60%{transform:translate(-1px,1px)}
            80%{transform:translate(1px,-1px)}
        }
        @keyframes glitch2 {
            0%,100%{transform:translate(0)}
            20%{transform:translate(2px,-2px)}
            40%{transform:translate(-2px,2px)}
            60%{transform:translate(1px,-1px)}
            80%{transform:translate(-1px,1px)}
        }
        .subtitle {
            font-size: 1em;
            color: var(--secondary);
            margin-top: 5px;
            text-shadow: 0 0 20px rgba(0,229,255,0.2);
            letter-spacing: 2px;
        }
        .version {
            font-size: 0.8em;
            color: var(--text-muted);
            margin-top: 3px;
        }
        
        .status-bar {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            padding: 12px 15px;
            background: var(--bg-card);
            border-radius: 8px;
            border: 1px solid rgba(0,255,80,0.1);
            margin-bottom: 20px;
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 4px 0;
        }
        .status-item .label { color: var(--text-muted); font-size: 0.85em; }
        .status-item .value { color: var(--primary); font-weight: bold; font-size: 0.95em; }
        .status-item .value.offline { color: var(--danger); }
        .status-item .value.online { color: var(--primary); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
        
        .card {
            background: var(--bg-card);
            padding: 20px;
            border-radius: 10px;
            border: 1px solid rgba(0,255,80,0.08);
            margin-bottom: 16px;
        }
        .card h3 {
            color: var(--secondary);
            font-family: 'Orbitron', monospace;
            font-size: 1em;
            margin-bottom: 15px;
            text-shadow: 0 0 20px rgba(0,229,255,0.2);
        }
        
        .form-group { margin-bottom: 14px; }
        .form-group label {
            display: block;
            color: var(--text-color);
            font-weight: bold;
            margin-bottom: 5px;
            font-size: 0.9em;
        }
        .form-group input, .form-group textarea, .form-group select {
            width: 100%;
            padding: 10px 14px;
            background: var(--bg-input);
            border: 1px solid rgba(0,255,80,0.15);
            border-radius: 6px;
            color: var(--text-color);
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.9em;
            transition: all 0.3s ease;
        }
        .form-group input:focus, .form-group textarea:focus, .form-group select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 20px rgba(0,255,80,0.1);
        }
        .form-group textarea { resize: vertical; min-height: 60px; }
        .form-group select {
            cursor: pointer;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2300ff50' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 15px center;
        }
        .form-group select option { background: var(--bg-dark); color: var(--text-color); }
        .form-group small {
            display: block;
            color: var(--text-muted);
            font-size: 0.75em;
            margin-top: 3px;
        }
        
        .btn-group {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 8px;
        }
        .btn {
            padding: 10px 22px;
            border: none;
            border-radius: 6px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.9em;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 25px rgba(0,0,0,0.4); }
        .btn:active { transform: translateY(0); }
        .btn-primary { background: var(--primary); color: var(--bg-dark); }
        .btn-primary:hover { box-shadow: 0 0 30px rgba(0,255,80,0.3); }
        .btn-secondary { background: var(--secondary); color: var(--bg-dark); }
        .btn-secondary:hover { box-shadow: 0 0 30px rgba(0,229,255,0.3); }
        .btn-success { background: var(--primary); color: var(--bg-dark); }
        .btn-success:hover { box-shadow: 0 0 30px rgba(0,255,80,0.3); }
        .btn-danger { background: var(--danger); color: #fff; }
        .btn-danger:hover { box-shadow: 0 0 30px rgba(255,46,99,0.3); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none !important; }
        
        .result-box {
            margin-top: 12px;
            padding: 12px;
            border-radius: 6px;
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(0,255,80,0.1);
            min-height: 40px;
            display: none;
            white-space: pre-wrap;
            word-break: break-all;
            font-size: 0.85em;
        }
        .result-box.show { display: block; animation: fadeIn 0.4s ease; }
        .result-box.success { border-color: var(--primary); color: var(--primary); }
        .result-box.error { border-color: var(--danger); color: var(--danger); }
        .result-box.info { border-color: var(--secondary); color: var(--secondary); }
        .result-box.warning { border-color: var(--warning); color: var(--warning); }
        
        .services-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 10px;
            margin: 10px 0;
        }
        .service-item {
            background: rgba(0,0,0,0.3);
            padding: 10px;
            border-radius: 6px;
            border: 1px solid rgba(0,255,80,0.08);
            text-align: center;
        }
        .service-item .name { font-size: 0.9em; color: var(--text-color); }
        .service-item .status { font-size: 0.8em; margin-top: 3px; }
        .service-item .status.online { color: var(--primary); }
        .service-item .status.offline { color: var(--danger); }
        
        .progress-box {
            margin-top: 12px;
            padding: 12px;
            background: rgba(0,0,0,0.3);
            border-radius: 6px;
            border: 1px solid rgba(0,255,80,0.1);
            display: none;
        }
        .progress-box.show { display: block; }
        .progress-bar {
            width: 100%;
            height: 4px;
            background: rgba(255,255,255,0.05);
            border-radius: 2px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            border-radius: 2px;
            transition: width 0.5s ease;
            width: 0%;
        }
        .progress-text {
            color: var(--text-muted);
            font-size: 0.85em;
            margin-top: 6px;
            text-align: center;
        }
        
        .logs-container {
            background: rgba(0,0,0,0.5);
            border-radius: 6px;
            padding: 12px;
            max-height: 300px;
            overflow-y: auto;
            font-size: 0.8em;
            border: 1px solid rgba(0,255,80,0.05);
        }
        .logs-container::-webkit-scrollbar { width: 3px; }
        .logs-container::-webkit-scrollbar-track { background: rgba(0,0,0,0.3); }
        .logs-container::-webkit-scrollbar-thumb { background: var(--primary); border-radius: 2px; }
        .log-entry {
            padding: 3px 0;
            border-bottom: 1px solid rgba(255,255,255,0.02);
            line-height: 1.5;
        }
        .log-entry.system { color: var(--secondary); }
        .log-entry.success { color: var(--primary); }
        .log-entry.error { color: var(--danger); }
        .log-entry.warning { color: var(--warning); }
        .log-entry .time { color: var(--text-muted); margin-right: 8px; }
        
        .footer {
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid rgba(0,255,80,0.08);
            text-align: center;
            color: var(--text-muted);
            font-size: 0.75em;
            display: flex;
            justify-content: center;
            gap: 12px;
            flex-wrap: wrap;
        }
        .footer strong { color: var(--primary); }
        
        .row { display: flex; gap: 8px; flex-wrap: wrap; }
        .row > * { flex: 1; min-width: 150px; }
        
        @media (max-width: 600px) {
            .container { margin: 10px; padding: 15px; }
            .glitch { font-size: 1.8em; }
            .status-bar { grid-template-columns: 1fr; gap: 5px; }
            .btn-group { flex-direction: column; }
            .btn { width: 100%; text-align: center; }
            .services-grid { grid-template-columns: 1fr; }
            .row { flex-direction: column; }
            .row > * { min-width: unset; }
        }
    </style>
</head>
<body>
    <canvas id="matrix"></canvas>
    
    <div class="container">
        <div class="header">
            <div class="glitch" data-text="ZEFOY BOT">ZEFOY BOT</div>
            <div class="subtitle">⚡ Tự động tăng tương tác TikTok ⚡</div>
            <div class="version">v3.0.3 Premium | Made by TIENDEV</div>
        </div>

        <div class="status-bar">
            <div class="status-item">
                <span class="label">🔐 Trạng thái:</span>
                <span class="value offline" id="authStatus">Chưa kết nối</span>
            </div>
            <div class="status-item">
                <span class="label">📦 Dịch vụ:</span>
                <span class="value" id="serviceCount">0</span>
            </div>
            <div class="status-item">
                <span class="label">🔄 Lượt chạy:</span>
                <span class="value" id="runCount">0</span>
            </div>
        </div>

        <!-- CẤU HÌNH -->
        <div class="card">
            <h3>🔑 Cookie & User-Agent</h3>
            <div class="form-group">
                <label>🍪 Cookie String</label>
                <textarea id="cookieInput" placeholder="PHPSESSID=xxx; cf_clearance=xxx; ..." rows="3"></textarea>
                <small>Lấy cookie từ trình duyệt sau khi đăng nhập zefoy.com</small>
            </div>
            <div class="form-group">
                <label>🖥️ User-Agent</label>
                <input type="text" id="uaInput" placeholder="Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...">
                <small>Để trống dùng User-Agent mặc định</small>
            </div>
            <div class="btn-group">
                <button class="btn btn-primary" onclick="startSession()">🚀 Khởi tạo</button>
                <button class="btn btn-secondary" onclick="loadServices()">📋 Lấy dịch vụ</button>
            </div>
            <div id="resultBox" class="result-box"></div>
        </div>

        <!-- DỊCH VỤ -->
        <div class="card" id="servicesCard" style="display:none;">
            <h3>📋 Danh sách dịch vụ</h3>
            <div id="servicesContainer">
                <div style="color:var(--text-muted);text-align:center;padding:10px;">
                    Chưa có dữ liệu
                </div>
            </div>
        </div>

        <!-- BOOST -->
        <div class="card" id="boostCard" style="display:none;">
            <h3>🚀 Thực hiện Boost</h3>
            <div class="form-group">
                <label>📹 Link TikTok</label>
                <input type="text" id="videoUrl" placeholder="https://www.tiktok.com/@username/video/123456789">
            </div>
            <div class="form-group">
                <label>🎯 Dịch vụ</label>
                <select id="serviceSelect">
                    <option value="">-- Chọn dịch vụ --</option>
                </select>
            </div>
            <div class="form-group">
                <label>🔢 Số lượt chạy</label>
                <input type="number" id="maxRuns" value="10" min="1" max="100">
            </div>
            <div class="btn-group">
                <button class="btn btn-success" onclick="startBoost()">▶️ Bắt đầu Boost</button>
                <button class="btn btn-danger" onclick="stopBoost()">⏹️ Dừng</button>
            </div>
            <div id="boostResult" class="result-box"></div>
            <div class="progress-box" id="boostProgress">
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill" style="width: 0%"></div>
                </div>
                <div class="progress-text" id="progressText">Đang xử lý...</div>
            </div>
        </div>

        <!-- LOGS -->
        <div class="card">
            <h3>📊 Logs System</h3>
            <div class="logs-container" id="logsContainer">
                <div class="log-entry system"><span class="time">[SYSTEM]</span> 🔮 Zefoy Bot v3.0.3 đã sẵn sàng</div>
                <div class="log-entry system"><span class="time">[SYSTEM]</span> 👋 Nhập Cookie và bấm "Khởi tạo"</div>
            </div>
        </div>

        <div class="footer">
            <span>🔒 Bản quyền thuộc về <strong>TIENDEV</strong></span>
            <span>|</span>
            <span>⚡ Tool siêu VIP Pro</span>
        </div>
    </div>

    <script>
        // ===== MATRIX RAIN =====
        (function() {
            const canvas = document.getElementById('matrix');
            const ctx = canvas.getContext('2d');
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
            const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
            const fontSize = 14;
            const columns = Math.floor(canvas.width / fontSize);
            const drops = Array(columns).fill(1);
            
            function draw() {
                ctx.fillStyle = 'rgba(0,0,0,0.05)';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = '#00ff50';
                ctx.font = fontSize + 'px monospace';
                for (let i = 0; i < drops.length; i++) {
                    ctx.fillText(chars[Math.floor(Math.random() * chars.length)], i * fontSize, drops[i] * fontSize);
                    if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) drops[i] = 0;
                    drops[i]++;
                }
            }
            setInterval(draw, 60);
            window.addEventListener('resize', () => {
                canvas.width = window.innerWidth;
                canvas.height = window.innerHeight;
            });
        })();

        // ===== STATE =====
        let SESSION_ID = null;
        let isRunning = false;
        let totalRuns = 0;

        const $ = id => document.getElementById(id);
        const cookieInput = $('cookieInput');
        const uaInput = $('uaInput');
        const videoUrl = $('videoUrl');
        const serviceSelect = $('serviceSelect');
        const maxRuns = $('maxRuns');
        const authStatus = $('authStatus');
        const serviceCount = $('serviceCount');
        const runCount = $('runCount');
        const logsContainer = $('logsContainer');
        const resultBox = $('resultBox');
        const boostResult = $('boostResult');
        const boostProgress = $('boostProgress');
        const progressFill = $('progressFill');
        const progressText = $('progressText');
        const servicesContainer = $('servicesContainer');
        const servicesCard = $('servicesCard');
        const boostCard = $('boostCard');

        // ===== LOGS =====
        function addLog(message, type = 'system') {
            const time = new Date().toLocaleTimeString();
            const entry = document.createElement('div');
            entry.className = 'log-entry ' + type;
            entry.innerHTML = '<span class="time">[' + time + ']</span> ' + message;
            logsContainer.appendChild(entry);
            logsContainer.scrollTop = logsContainer.scrollHeight;
        }

        // ===== SHOW RESULT =====
        function showResult(el, msg, type = 'info') {
            el.textContent = msg;
            el.className = 'result-box show ' + type;
        }
        function hideResult(el) {
            el.className = 'result-box';
            el.textContent = '';
        }

        // ===== UPDATE STATUS =====
        function updateStatus(authenticated, services = 0) {
            if (authenticated) {
                authStatus.textContent = '🟢 Đã kết nối';
                authStatus.className = 'value online';
            } else {
                authStatus.textContent = '🔴 Chưa kết nối';
                authStatus.className = 'value offline';
            }
            serviceCount.textContent = services;
        }

        // ===== RENDER SERVICES =====
        function renderServices(services) {
            if (!services || services.length === 0) {
                servicesContainer.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:10px;">Không có dịch vụ nào</div>';
                return;
            }
            
            // Cập nhật select
            serviceSelect.innerHTML = '<option value="">-- Chọn dịch vụ --</option>';
            let html = '<div class="services-grid">';
            services.forEach(s => {
                const statusClass = s.active ? 'online' : 'offline';
                const statusText = s.active ? '🟢 ONLINE' : '🔴 OFFLINE';
                html += '<div class="service-item">';
                html += '<div class="name">' + s.name + '</div>';
                html += '<div class="status ' + statusClass + '">' + statusText + ' (' + s.status + ')</div>';
                html += '</div>';
                
                // Thêm vào select
                if (s.active) {
                    const opt = document.createElement('option');
                    opt.value = s.name;
                    opt.textContent = '🟢 ' + s.name;
                    serviceSelect.appendChild(opt);
                }
            });
            html += '</div>';
            servicesContainer.innerHTML = html;
            
            servicesCard.style.display = 'block';
            boostCard.style.display = 'block';
        }

        // ===== API CALLS =====
        async function startSession() {
            const cookie = cookieInput.value.trim();
            if (!cookie) {
                showResult(resultBox, '⚠️ Vui lòng nhập Cookie String!', 'error');
                return;
            }
            
            showResult(resultBox, '⏳ Đang khởi tạo session...', 'info');
            addLog('⏳ Đang khởi tạo session...', 'system');
            
            try {
                const res = await fetch('/api/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cookie_string: cookie,
                        user_agent: uaInput.value.trim()
                    })
                });
                const data = await res.json();
                
                if (data.success) {
                    SESSION_ID = data.session_id;
                    updateStatus(true, data.services ? data.services.length : 0);
                    showResult(resultBox, '✅ Session khởi tạo thành công!', 'success');
                    addLog('✅ Session ID: ' + SESSION_ID.slice(0, 16) + '...', 'success');
                    
                    if (data.services && data.services.length > 0) {
                        renderServices(data.services);
                        addLog('📋 Đã tải ' + data.services.length + ' dịch vụ', 'system');
                    } else {
                        addLog('⚠️ Không tìm thấy dịch vụ nào', 'warning');
                    }
                } else {
                    showResult(resultBox, '❌ ' + (data.detail || 'Lỗi không xác định'), 'error');
                    addLog('❌ Lỗi: ' + (data.detail || 'Không xác định'), 'error');
                }
            } catch (e) {
                showResult(resultBox, '❌ Lỗi: ' + e.message, 'error');
                addLog('❌ Lỗi: ' + e.message, 'error');
            }
        }

        async function loadServices() {
            if (!SESSION_ID) {
                showResult(resultBox, '⚠️ Vui lòng khởi tạo session trước!', 'error');
                return;
            }
            
            showResult(resultBox, '⏳ Đang tải dịch vụ...', 'info');
            addLog('⏳ Đang tải dịch vụ...', 'system');
            
            try {
                const res = await fetch('/api/services', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: SESSION_ID })
                });
                const data = await res.json();
                
                if (data.success) {
                    renderServices(data.services);
                    updateStatus(true, data.services.length);
                    showResult(resultBox, '✅ Đã tải ' + data.services.length + ' dịch vụ', 'success');
                    addLog('✅ Đã tải ' + data.services.length + ' dịch vụ', 'success');
                } else {
                    showResult(resultBox, '❌ ' + (data.detail || 'Lỗi không xác định'), 'error');
                    addLog('❌ Lỗi: ' + (data.detail || 'Không xác định'), 'error');
                }
            } catch (e) {
                showResult(resultBox, '❌ Lỗi: ' + e.message, 'error');
                addLog('❌ Lỗi: ' + e.message, 'error');
            }
        }

        async function startBoost() {
            if (isRunning) {
                addLog('⚠️ Bot đang chạy!', 'warning');
                return;
            }
            
            if (!SESSION_ID) {
                showResult(boostResult, '⚠️ Vui lòng khởi tạo session trước!', 'error');
                return;
            }
            
            const url = videoUrl.value.trim();
            if (!url) {
                showResult(boostResult, '⚠️ Nhập link TikTok!', 'error');
                return;
            }
            
            const service = serviceSelect.value;
            if (!service) {
                showResult(boostResult, '⚠️ Chọn dịch vụ!', 'error');
                return;
            }
            
            const runs = parseInt(maxRuns.value) || 10;
            
            isRunning = true;
            boostProgress.classList.add('show');
            progressFill.style.width = '0%';
            progressText.textContent = 'Đang bắt đầu...';
            hideResult(boostResult);
            addLog('🚀 Bắt đầu boost: ' + service + ' - ' + runs + ' lượt', 'system');
            
            try {
                const res = await fetch('/api/boost', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: SESSION_ID,
                        video_url: url,
                        service: service,
                        max_runs: runs
                    })
                });
                const data = await res.json();
                
                progressFill.style.width = '100%';
                progressText.textContent = 'Hoàn tất!';
                
                if (data.success) {
                    totalRuns += data.runs || 0;
                    runCount.textContent = totalRuns;
                    
                    let msg = '✅ ' + (data.message || 'Boost thành công!');
                    if (data.runs) msg += ' (' + data.runs + ' lượt)';
                    if (data.errors && data.errors.length) {
                        msg += '\\n⚠️ Lỗi: ' + data.errors.join('\\n');
                    }
                    showResult(boostResult, msg, 'success');
                    addLog('✅ Boost thành công: ' + (data.runs || 0) + ' lượt', 'success');
                } else {
                    let msg = '❌ ' + (data.message || 'Lỗi không xác định');
                    if (data.errors && data.errors.length) {
                        msg += '\\n⚠️ ' + data.errors.join('\\n');
                    }
                    showResult(boostResult, msg, 'error');
                    addLog('❌ Boost thất bại: ' + (data.message || ''), 'error');
                }
            } catch (e) {
                showResult(boostResult, '❌ Lỗi: ' + e.message, 'error');
                addLog('❌ Lỗi boost: ' + e.message, 'error');
            }
            
            setTimeout(() => {
                boostProgress.classList.remove('show');
                progressFill.style.width = '0%';
            }, 3000);
            
            isRunning = false;
        }

        function stopBoost() {
            if (!isRunning) {
                addLog('⚠️ Bot không đang chạy', 'warning');
                return;
            }
            isRunning = false;
            addLog('⏹️ Đã dừng boost', 'warning');
            showResult(boostResult, '⏹️ Đã dừng boost', 'warning');
        }

        // ===== LOAD CONFIG FROM LOCALSTORAGE =====
        window.onload = function() {
            const savedCookie = localStorage.getItem('zefoy_cookie');
            const savedUA = localStorage.getItem('zefoy_ua');
            if (savedCookie) {
                cookieInput.value = savedCookie;
                addLog('📂 Đã tải cookie từ localStorage', 'system');
            }
            if (savedUA) uaInput.value = savedUA;
        };
        
        // Save config when starting session
        const origStart = startSession;
        startSession = async function() {
            localStorage.setItem('zefoy_cookie', cookieInput.value.trim());
            localStorage.setItem('zefoy_ua', uaInput.value.trim());
            await origStart();
        };
    </script>
</body>
</html>
"""

# ============================================================
# API ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Trang chủ - Giao diện Web"""
    return HTML_TEMPLATE

@app.get("/api")
async def api_info():
    return {
        "name": "Zefoy Bot API",
        "version": "3.0.3",
        "status": "online",
        "endpoints": [
            "/api/start",
            "/api/services",
            "/api/boost",
            "/api/status"
        ]
    }

@app.post("/api/start")
async def start_session(req: StartRequest):
    if not req.cookie_string:
        raise HTTPException(400, "cookie_string không được để trống")
    
    session_id = uuid.uuid4().hex
    st = _new_session_state(req.cookie_string, req.user_agent)
    bot: ZefoyBot = st["bot"]
    
    if not bot.authenticate():
        raise HTTPException(401, "Cookie không hợp lệ hoặc đã hết hạn")
    
    services = bot.get_services_list()
    st["services"] = services
    
    SESSIONS[session_id] = st
    
    return {
        "session_id": session_id,
        "success": True,
        "services": [
            {"name": s["name"], "active": s["active"], "status": s["status"]}
            for s in services
        ]
    }

@app.post("/api/services")
async def get_services(req: SessionRequest):
    st = _get_session(req.session_id)
    bot: ZefoyBot = st["bot"]
    
    services = bot.get_services_list()
    st["services"] = services
    
    return {
        "success": True,
        "services": [
            {"name": s["name"], "active": s["active"], "status": s["status"]}
            for s in services
        ]
    }

@app.post("/api/boost")
async def boost(req: BoostRequest):
    st = _get_session(req.session_id)
    bot: ZefoyBot = st["bot"]
    
    if not bot.authenticate():
        raise HTTPException(401, "Session đã hết hạn. Vui lòng tạo session mới.")
    
    result = bot.boost(req.video_url, req.service, req.max_runs)
    
    if result.get("success"):
        st["total_sent"] = st.get("total_sent", 0) + result.get("runs", 0)
        result["total_sent"] = st["total_sent"]
    
    return result

@app.post("/api/status")
async def get_status(req: SessionRequest):
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
