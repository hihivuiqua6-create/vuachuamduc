"""
Zefoy Web API - Merge buff.py + source cũ + OCR tự động
FIX: Bỏ async def, dùng def thường
"""

from __future__ import annotations

import os
import re
import sys
import time
import html
import json
import base64
import uuid
import urllib.parse
from typing import Any, Optional, Dict, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
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
# EXCEPTION HANDLER - TRẢ JSON LUÔN
# ============================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": str(exc),
            "error_type": type(exc).__name__
        }
    )

@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "status_code": exc.status_code
        }
    )

# ============================================================
# LOGIC TỪ SOURCE CŨ (Captcha + Session)
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
    """GIỐNG buff.py decode"""
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
    """GIỐNG buff.py extract_cooldown_seconds"""
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

# ===== CAPTCHA TỪ SOURCE CŨ =====
def get_captcha_image(session: requests.Session) -> tuple:
    """Lấy ảnh captcha - TỪ SOURCE CŨ"""
    t = str(int(time.time()))
    params = {'getcapthca': t}
    try:
        r = session.get('https://zefoy.com/', params=params)
        html_content = decode_zefoy_response(r.text)
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        img_tag = soup.find('img', id='captcha-img')
        if not img_tag:
            img_tag = soup.find('img', src=re.compile(r'_CAPTCHA'))
            
        src = None
        if img_tag:
            src = img_tag.get('src')
        else:
            match = re.search(r'src="([^"]*_CAPTCHA=[^"]*)"', html_content)
            if match:
                src = match.group(1)
                
        if not src:
            return None, None
            
        src = html.unescape(src)
        if not src.startswith('http'):
            src = 'https://zefoy.com' + src
            
        form_data = {}
        form = soup.find('form')
        if form:
            for inp in form.find_all('input'):
                name = inp.get('name')
                val = inp.get('value', '')
                if name:
                    form_data[name] = val
                    
        return src, form_data
    except Exception as e:
        logger.error(f"Lỗi khi lấy ảnh Captcha: {e}")
        return None, None

def solve_captcha(session: requests.Session, captcha_text: str) -> bool:
    """Gửi captcha - TỪ SOURCE CŨ"""
    try:
        captcha_url, form_data = get_captcha_image(session)
        
        if not captcha_url:
            return False
            
        if not form_data:
            form_data = {}
        form_data['captchalogin'] = captcha_text.lower()
        
        logger.info(f"Đang gửi mã Captcha: {captcha_text}")
        post_resp = session.post('https://zefoy.com/', data=form_data)
        
        resp_text = post_resp.text
        if 'Captcha code is incorrect' in resp_text or 'zbcd' in resp_text:
            return False
        else:
            check_resp = session.get('https://zefoy.com/')
            if 't-followers-button' in check_resp.text or 't-hearts-button' in check_resp.text or 'colsmenu' in check_resp.text:
                return True
            else:
                return False
    except Exception as e:
        logger.error(f"Lỗi giải captcha: {e}")
        return False

# ============================================================
# OCR TỰ ĐỘNG (dùng newocr.com)
# ============================================================

def ocr_captcha(image_bytes: bytes) -> str:
    """OCR ảnh captcha tự động - dùng newocr.com"""
    try:
        files = {'userfile': ('captcha.png', image_bytes, 'image/png')}
        data = {'preview': '1'}
        
        ocr_session = requests.Session()
        ocr_session.headers.update({
            'User-Agent': DEFAULT_USER_AGENT,
            'Referer': 'https://www.newocr.com/',
        })
        
        resp = ocr_session.post('https://www.newocr.com/', data=data, files=files, timeout=30)
        html_content = resp.text
        
        file_id_match = re.search(r'name="u"\s+value="([a-f0-9]{32})"', html_content)
        if not file_id_match:
            file_id_match = re.search(r'name="u"[^>]*value="([^"]+)"', html_content)
        if not file_id_match:
            return ""
        
        file_id = file_id_match.group(1)
        
        ocr_data = {
            'u': file_id,
            'l2[]': 'eng',
            'psm': '6',
            'r': '0',
            'x1': '0',
            'y1': '0',
            'x2': '100',
            'y2': '100',
            'ocr': '1'
        }
        resp = ocr_session.post('https://www.newocr.com/', data=ocr_data, timeout=30)
        
        result_match = re.search(r'<textarea[^>]*id="ocr-result"[^>]*>([\s\S]*?)</textarea>', resp.text, re.I)
        if result_match:
            text = result_match.group(1).strip()
            text = re.sub(r'[^a-zA-Z]', '', text).lower()
            return text
        
        return ""
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return ""

# ============================================================
# LOGIC TỪ buff.py (Lấy service + Boost)
# ============================================================

def get_services(session: requests.Session) -> tuple:
    """Lấy danh sách dịch vụ - FIX cho layout mới"""
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
    """Lấy form cho dịch vụ - GIỐNG buff.py"""
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
    def __init__(self, session: requests.Session = None, user_agent: str = None):
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.session = session or self._setup_session()
        self.services = []
        self.home_html = ""
        self.captcha_solved = False
        
    def _setup_session(self) -> requests.Session:
        session = requests.Session()
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
    
    def get_captcha(self) -> Optional[Dict]:
        """Lấy ảnh captcha - TỪ SOURCE CŨ"""
        captcha_url, form_data = get_captcha_image(self.session)
        
        if not captcha_url:
            r = self.session.get('https://zefoy.com/')
            if 't-followers-button' in r.text or 't-hearts-button' in r.text or 'colsmenu' in r.text:
                self.captcha_solved = True
                return {'solved': True, 'message': 'Đã đăng nhập, không cần captcha'}
            return None
        
        try:
            img_resp = self.session.get(captcha_url)
            img_b64 = base64.b64encode(img_resp.content).decode('ascii')
            return {
                'solved': False,
                'captcha_b64': img_b64,
                'image_bytes': img_resp.content,
                'form_data': form_data,
                'message': 'Vui lòng nhập mã captcha'
            }
        except Exception as e:
            logger.error(f"Lỗi tải captcha: {e}")
            return None
    
    def submit_captcha(self, captcha_text: str) -> bool:
        """Gửi captcha - TỪ SOURCE CŨ"""
        result = solve_captcha(self.session, captcha_text)
        if result:
            self.captcha_solved = True
        return result
    
    def auto_solve_captcha(self) -> bool:
        """Tự động giải captcha bằng OCR"""
        captcha_data = self.get_captcha()
        if not captcha_data:
            return False
        
        if captcha_data.get('solved'):
            return True
        
        image_bytes = captcha_data.get('image_bytes')
        if not image_bytes:
            return False
        
        logger.info("Đang OCR captcha...")
        captcha_text = ocr_captcha(image_bytes)
        if not captcha_text:
            logger.warning("OCR không đọc được captcha")
            return False
        
        logger.info(f"OCR kết quả: {captcha_text}")
        return self.submit_captcha(captcha_text)
    
    def authenticate(self) -> bool:
        """Kiểm tra đăng nhập - GIỐNG buff.py"""
        try:
            r = self.session.get('https://zefoy.com/')
            html_content = decode_zefoy_response(r.text)
            
            if 't-followers-button' in html_content or 't-hearts-button' in html_content or 'colsmenu' in html_content:
                self.captcha_solved = True
                return True
            
            if 'card-title' in html_content or 'col-' in html_content:
                soup = BeautifulSoup(html_content, 'html.parser')
                buttons = soup.find_all('button', class_=re.compile(r't-[a-z]+-button'))
                if buttons:
                    self.captcha_solved = True
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return False
    
    def get_services_list(self) -> List[Dict]:
        """Lấy dịch vụ - GIỐNG buff.py"""
        services, home_html = get_services(self.session)
        self.services = services
        self.home_html = home_html
        return services
    
    def boost(self, video_url: str, service_name: str, max_runs: int = 10) -> Dict:
        """Boost - GIỐNG HỆT buff.py main loop"""
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
                    
                    for attempt in range(3):
                        r = self.session.post(action_url, headers=ajax_headers, data=search_data)
                        decoded_response = decode_zefoy_response(r.text)
                        
                        soup = BeautifulSoup(decoded_response, 'html.parser')
                        total_wait, countdown_text = extract_cooldown_seconds(decoded_response)
                        
                        form = soup.find('form')
                        submit_btn = soup.find('button', class_=re.compile(r'wbutton|btn'))
                        
                        if (total_wait > 0 and "Mặc định 120s" not in countdown_text) or form or submit_btn:
                            break
                        
                        if attempt < 2:
                            time.sleep(2.5)
                    
                    if total_wait > 0:
                        results['errors'].append(f"Cooldown: {countdown_text}")
                        results['message'] = f"Đang chờ cooldown: {countdown_text}"
                        return results
                    
                    if form or submit_btn:
                        target_form = form if form else submit_btn.find_parent('form')
                        submit_action = target_form.get('action') if target_form else None
                        if not submit_action or submit_action.strip() == "" or submit_action == "/" or not submit_action.startswith('c2VuZ'):
                            submit_action = form_info['action']
                        submit_url = f"https://zefoy.com/{submit_action}"
                        
                        submit_data = {}
                        inputs = target_form.find_all('input') if target_form else soup.find_all('input')
                        for inp in inputs:
                            name = inp.get('name')
                            val = inp.get('value', '')
                            if name:
                                submit_data[name] = val
                        
                        selects = target_form.find_all('select') if target_form else soup.find_all('select')
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
                        
                        actual_btn = target_form.find('button', type='submit') if target_form else submit_btn
                        if actual_btn and actual_btn.get('name'):
                            submit_data[actual_btn.get('name')] = actual_btn.get('value', '')
                        
                        boost_r = self.session.post(submit_url, headers=ajax_headers, data=submit_data)
                        decoded_boost = decode_zefoy_response(boost_r.text)
                        result_text = clean_html_text(decoded_boost)
                        
                        if not result_text:
                            result_text = "Phản hồi không chứa thông báo văn bản."
                        
                        runs += 1
                        results['runs'] = runs
                        results['message'] = result_text
                        results['success'] = True
                        
                        if runs < max_runs:
                            time.sleep(10)
                    else:
                        err_text = clean_html_text(decoded_response)
                        results['errors'].append(f"Không tìm thấy nút Submit: {err_text}")
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

def _new_session_state() -> Dict:
    return {
        "bot": ZefoyBot(),
        "created": time.time(),
        "last_used": time.time(),
        "total_sent": 0,
        "services": [],
        "captcha_data": None
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
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
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
        .status-item .label { color: var(--text-muted); font-size: 0.8em; }
        .status-item .value { color: var(--primary); font-weight: bold; font-size: 0.9em; }
        .status-item .value.offline { color: var(--danger); }
        .status-item .value.online { color: var(--primary); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
        
        .card {
            background: var(--bg-card);
            padding: 18px;
            border-radius: 10px;
            border: 1px solid rgba(0,255,80,0.08);
            margin-bottom: 14px;
        }
        .card h3 {
            color: var(--secondary);
            font-family: 'Orbitron', monospace;
            font-size: 0.95em;
            margin-bottom: 12px;
            text-shadow: 0 0 20px rgba(0,229,255,0.2);
        }
        
        .form-group { margin-bottom: 12px; }
        .form-group label {
            display: block;
            color: var(--text-color);
            font-weight: bold;
            margin-bottom: 4px;
            font-size: 0.85em;
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
        .form-group textarea { resize: vertical; min-height: 50px; }
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
            font-size: 0.7em;
            margin-top: 3px;
        }
        
        .btn-group {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 8px;
        }
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.85em;
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
        .btn-warning { background: var(--warning); color: #000; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none !important; }
        
        .result-box {
            margin-top: 10px;
            padding: 10px;
            border-radius: 6px;
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(0,255,80,0.1);
            min-height: 35px;
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
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 8px;
            margin: 10px 0;
        }
        .service-item {
            background: rgba(0,0,0,0.3);
            padding: 8px;
            border-radius: 6px;
            border: 1px solid rgba(0,255,80,0.08);
            text-align: center;
        }
        .service-item .name { font-size: 0.85em; color: var(--text-color); }
        .service-item .status { font-size: 0.75em; margin-top: 3px; }
        .service-item .status.online { color: var(--primary); }
        .service-item .status.offline { color: var(--danger); }
        
        .progress-box {
            margin-top: 10px;
            padding: 10px;
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
            font-size: 0.8em;
            margin-top: 5px;
            text-align: center;
        }
        
        .logs-container {
            background: rgba(0,0,0,0.5);
            border-radius: 6px;
            padding: 10px;
            max-height: 250px;
            overflow-y: auto;
            font-size: 0.78em;
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
            margin-top: 18px;
            padding-top: 12px;
            border-top: 1px solid rgba(0,255,80,0.08);
            text-align: center;
            color: var(--text-muted);
            font-size: 0.7em;
            display: flex;
            justify-content: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .footer strong { color: var(--primary); }
        
        .row { display: flex; gap: 8px; flex-wrap: wrap; }
        .row > * { flex: 1; min-width: 120px; }
        
        @media (max-width: 600px) {
            .container { margin: 8px; padding: 12px; }
            .glitch { font-size: 1.6em; }
            .status-bar { grid-template-columns: 1fr; gap: 3px; }
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

        <div class="card">
            <h3>🚀 Khởi tạo Session (Tự động captcha)</h3>
            <p style="color:var(--text-muted);font-size:0.85em;margin-bottom:12px;">
                Không cần nhập Cookie hay User-Agent. Hệ thống tự động lấy captcha và giải bằng OCR.
            </p>
            <div class="btn-group">
                <button class="btn btn-primary" onclick="startSession()">🚀 Khởi tạo</button>
                <button class="btn btn-secondary" onclick="loadServices()">📋 Lấy dịch vụ</button>
            </div>
            <div id="resultBox" class="result-box"></div>
        </div>

        <div class="card" id="servicesCard" style="display:none;">
            <h3>📋 Danh sách dịch vụ</h3>
            <div id="servicesContainer">
                <div style="color:var(--text-muted);text-align:center;padding:8px;">
                    Chưa có dữ liệu
                </div>
            </div>
        </div>

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

        <div class="card">
            <h3>📊 Logs System</h3>
            <div class="logs-container" id="logsContainer">
                <div class="log-entry system"><span class="time">[SYSTEM]</span> 🔮 Zefoy Bot v3.0.3 đã sẵn sàng</div>
                <div class="log-entry system"><span class="time">[SYSTEM]</span> 👋 Bấm "Khởi tạo" để bắt đầu</div>
            </div>
        </div>

        <div class="footer">
            <span>🔒 Bản quyền thuộc về <strong>TIENDEV</strong></span>
            <span>|</span>
            <span>⚡ Tool siêu VIP Pro</span>
        </div>
    </div>

    <script>
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

        let SESSION_ID = null;
        let isRunning = false;
        let totalRuns = 0;

        const $ = id => document.getElementById(id);
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

        function addLog(message, type = 'system') {
            const time = new Date().toLocaleTimeString();
            const entry = document.createElement('div');
            entry.className = 'log-entry ' + type;
            entry.innerHTML = '<span class="time">[' + time + ']</span> ' + message;
            logsContainer.appendChild(entry);
            logsContainer.scrollTop = logsContainer.scrollHeight;
        }

        function showResult(el, msg, type = 'info') {
            el.textContent = msg;
            el.className = 'result-box show ' + type;
            el.style.display = 'block';
        }
        function hideResult(el) {
            el.className = 'result-box';
            el.textContent = '';
            el.style.display = 'none';
        }

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

        function renderServices(services) {
            if (!services || services.length === 0) {
                servicesContainer.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:8px;">Không có dịch vụ nào</div>';
                return;
            }
            
            serviceSelect.innerHTML = '<option value="">-- Chọn dịch vụ --</option>';
            let html = '<div class="services-grid">';
            services.forEach(s => {
                const statusClass = s.active ? 'online' : 'offline';
                const statusText = s.active ? '🟢 ONLINE' : '🔴 OFFLINE';
                html += '<div class="service-item">';
                html += '<div class="name">' + s.name + '</div>';
                html += '<div class="status ' + statusClass + '">' + statusText + ' (' + s.status + ')</div>';
                html += '</div>';
                
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

        async function callAPI(endpoint, data = {}) {
            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                const text = await response.text();
                let result;
                try {
                    result = JSON.parse(text);
                } catch (e) {
                    return {
                        success: false,
                        message: 'Server trả về lỗi: ' + text.substring(0, 200),
                        raw: text
                    };
                }
                
                return result;
            } catch (e) {
                return {
                    success: false,
                    message: 'Lỗi kết nối: ' + e.message
                };
            }
        }

        async function startSession() {
            showResult(resultBox, '⏳ Đang khởi tạo session + tự động giải captcha...', 'info');
            addLog('⏳ Đang khởi tạo session...', 'system');
            
            const result = await callAPI('/api/start', {});
            
            if (result.success) {
                SESSION_ID = result.session_id;
                updateStatus(true, result.services ? result.services.length : 0);
                showResult(resultBox, '✅ Session khởi tạo thành công! Captcha tự động giải.', 'success');
                addLog('✅ Session ID: ' + SESSION_ID.slice(0, 16) + '...', 'success');
                
                if (result.services && result.services.length > 0) {
                    renderServices(result.services);
                    addLog('📋 Đã tải ' + result.services.length + ' dịch vụ', 'system');
                }
            } else {
                showResult(resultBox, '❌ ' + (result.message || 'Lỗi không xác định'), 'error');
                addLog('❌ Lỗi: ' + (result.message || 'Không xác định'), 'error');
            }
        }

        async function loadServices() {
            if (!SESSION_ID) {
                showResult(resultBox, '⚠️ Vui lòng khởi tạo session trước!', 'error');
                return;
            }
            
            showResult(resultBox, '⏳ Đang tải dịch vụ...', 'info');
            addLog('⏳ Đang tải dịch vụ...', 'system');
            
            const result = await callAPI('/api/services', { session_id: SESSION_ID });
            
            if (result.success) {
                renderServices(result.services);
                updateStatus(true, result.services.length);
                showResult(resultBox, '✅ Đã tải ' + result.services.length + ' dịch vụ', 'success');
                addLog('✅ Đã tải ' + result.services.length + ' dịch vụ', 'success');
            } else {
                showResult(resultBox, '❌ ' + (result.message || 'Lỗi không xác định'), 'error');
                addLog('❌ Lỗi: ' + (result.message || 'Không xác định'), 'error');
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
            
            const result = await callAPI('/api/boost', {
                session_id: SESSION_ID,
                video_url: url,
                service: service,
                max_runs: runs
            });
            
            progressFill.style.width = '100%';
            progressText.textContent = 'Hoàn tất!';
            
            if (result.success) {
                totalRuns += result.runs || 0;
                runCount.textContent = totalRuns;
                
                let msg = '✅ ' + (result.message || 'Boost thành công!');
                if (result.runs) msg += ' (' + result.runs + ' lượt)';
                if (result.errors && result.errors.length) {
                    msg += '\\n⚠️ Lỗi: ' + result.errors.join('\\n');
                }
                showResult(boostResult, msg, 'success');
                addLog('✅ Boost thành công: ' + (result.runs || 0) + ' lượt', 'success');
            } else {
                let msg = '❌ ' + (result.message || 'Lỗi không xác định');
                if (result.errors && result.errors.length) {
                    msg += '\\n⚠️ ' + result.errors.join('\\n');
                }
                showResult(boostResult, msg, 'error');
                addLog('❌ Boost thất bại: ' + (result.message || ''), 'error');
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
    </script>
</body>
</html>
"""

# ============================================================
# API ROUTES - DÙNG def THAY VÌ async def
# ============================================================

@app.get("/", response_class=HTMLResponse)
def root():
    return HTML_TEMPLATE

@app.get("/api")
def api_info():
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
def start_session():
    """Khởi tạo session mới - tự động giải captcha bằng OCR"""
    session_id = uuid.uuid4().hex
    bot = ZefoyBot()
    
    # Thử authenticate - nếu chưa login thì tự động giải captcha
    if not bot.authenticate():
        logger.info("Đang tự động giải captcha...")
        if not bot.auto_solve_captcha():
            raise HTTPException(500, "Không thể giải captcha tự động. Vui lòng thử lại.")
        
        if not bot.authenticate():
            raise HTTPException(500, "Captcha giải nhưng không đăng nhập được. Vui lòng thử lại.")
    
    # Lấy services
    services = bot.get_services_list()
    
    # Lưu session
    SESSIONS[session_id] = {
        "bot": bot,
        "created": time.time(),
        "last_used": time.time(),
        "total_sent": 0,
        "services": services
    }
    
    return {
        "session_id": session_id,
        "success": True,
        "services": [
            {"name": s["name"], "active": s["active"], "status": s["status"]}
            for s in services
        ]
    }

@app.post("/api/services")
def get_services(req: SessionRequest):
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
def boost(req: BoostRequest):
    st = _get_session(req.session_id)
    bot: ZefoyBot = st["bot"]
    
    # Kiểm tra auth - nếu hết hạn thì auto login lại
    if not bot.authenticate():
        logger.info("Session hết hạn, đang tự động login lại...")
        if bot.auto_solve_captcha():
            bot.authenticate()
        else:
            raise HTTPException(401, "Session hết hạn và không thể tự động đăng nhập lại.")
    
    result = bot.boost(req.video_url, req.service, req.max_runs)
    
    if result.get("success"):
        st["total_sent"] = st.get("total_sent", 0) + result.get("runs", 0)
        result["total_sent"] = st["total_sent"]
    
    return result

@app.post("/api/status")
def get_status(req: SessionRequest):
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
def health():
    return {"status": "healthy", "sessions": len(SESSIONS)}

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
