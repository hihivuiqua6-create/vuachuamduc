"""
TikTok Buff Tool - Zefoy Automation
Developed by Dev Auza
"""

import os
import re
import sys
import time
import json
import base64
import hashlib
import threading
import urllib.parse
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from io import BytesIO
import uuid
import platform

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Vui lòng cài đặt các thư viện cần thiết:")
    print("pip install requests beautifulsoup4 pillow sv-ttk")
    print(f"Lỗi: {e}")
    sys.exit(1)

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_BASE_URL = "https://zefoy.com"
AUTHOR = "Dev Auza"

# Firebase REST API Config
FIREBASE_CONFIG = {
    "apiKey": "AIzaSyAqrRYNWLMx0pVMwKVCc2G_c_SnY4hqqN4",
    "authDomain": "login-buff.firebaseapp.com",
    "projectId": "login-buff",
    "storageBucket": "login-buff.firebasestorage.app",
    "messagingSenderId": "42263720814",
    "appId": "1:42263720814:web:5ec8365aebe51cdacc877f",
    "measurementId": "G-Y7W2BCFE3R",
    "databaseURL": "https://login-buff-default-rtdb.firebaseio.com/"
}

# ============== ZEFOY CAPTCHA ==============
class ZefoyCaptchaError(Exception):
    pass

class CaptchaResult:
    def __init__(self, image_bytes: bytes, session_id: str = None, cookies: dict = None):
        self.image_bytes = image_bytes
        self.session_id = session_id
        self.cookies = cookies or {}

class ZefoyCaptcha:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, user_agent: str = DEFAULT_USER_AGENT, 
                 session: requests.Session = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.verify = False
        self._update_headers()
    
    def _update_headers(self):
        self.session.headers.update({
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': f'{self.base_url}/',
            'Origin': self.base_url,
        })
    
    @property
    def cookies(self) -> dict:
        return self.session.cookies.get_dict()
    
    @property
    def session_id(self) -> Optional[str]:
        return self.cookies.get("PHPSESSID")
    
    def ensure_session(self) -> str:
        resp = self.session.get(f"{self.base_url}/", timeout=self.timeout)
        resp.raise_for_status()
        self._apply_guard_cookies()
        sid = self.session_id
        if not sid:
            raise ZefoyCaptchaError("No PHPSESSID cookie")
        return sid
    
    def _apply_guard_cookies(self):
        zf = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()
        self.session.cookies.set("zf", zf, path="/")
        self.session.cookies.set("za", "200", path="/")
    
    def get(self) -> CaptchaResult:
        if not self.session_id:
            self.ensure_session()
        
        ts = int(time.time())
        url = f"{self.base_url}/?getcapthca={ts}"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.base_url}/",
        }
        resp = self.session.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        
        try:
            data = resp.json()
        except:
            raise ZefoyCaptchaError("Captcha endpoint did not return JSON")
        
        if not data:
            raise ZefoyCaptchaError("Empty captcha payload")
        
        encoded = None
        key = hashlib.md5(self.user_agent.encode()).hexdigest()
        if key in data:
            encoded = data[key]
        elif len(data) == 1:
            encoded = next(iter(data.values()))
        else:
            raise ZefoyCaptchaError(f"Payload key {key} not found")
        
        try:
            once = base64.b64decode(encoded)
            twice = base64.b64decode(once)
            image_path = twice.decode('utf-8').strip()
        except:
            raise ZefoyCaptchaError("Failed to decode image path")
        
        if not image_path.startswith("/"):
            image_path = "/" + image_path
        
        url = f"{self.base_url}{image_path}"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        
        if not resp.content:
            raise ZefoyCaptchaError("Empty image response")
        
        return CaptchaResult(
            image_bytes=resp.content,
            session_id=self.session_id,
            cookies=self.cookies
        )

# ============== ZEFOY CLIENT ==============
class ZefoyClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.user_agent = DEFAULT_USER_AGENT
        self.base_url = DEFAULT_BASE_URL
        self._captcha_client = None
        self._services = []
        self._service_map = {}
        self._video_key = None
        self._ajax_headers = {}
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
        
        self._ajax_headers = {
            'accept': '*/*',
            'accept-language': 'vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': self.base_url,
            'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.user_agent,
            'x-requested-with': 'XMLHttpRequest',
            'referer': f'{self.base_url}/'
        }
    
    def initialize(self) -> bool:
        try:
            self._captcha_client = ZefoyCaptcha(
                base_url=self.base_url,
                user_agent=self.user_agent,
                session=self.session
            )
            self._captcha_client.ensure_session()
            return True
        except Exception as e:
            print(f"Init error: {e}")
            return False
    
    def get_captcha_image(self) -> Optional[bytes]:
        try:
            if not self._captcha_client:
                self.initialize()
            result = self._captcha_client.get()
            return result.image_bytes
        except Exception as e:
            print(f"Captcha error: {e}")
            return None
    
    def solve_captcha(self, answer: str) -> bool:
        try:
            answer = re.sub(r"[^a-zA-Z]", "", answer or "").lower()
            if not answer:
                return False
            
            encoded = self._build_captcha_encoded()
            
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
    
    def _build_captcha_encoded(self) -> str:
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
            "otherData": {},
            "storageInfo": {
                "localStorage": "Yes",
                "sessionStorage": "Yes",
                "indexedDB": "Yes",
            }
        }
        try:
            plaintext = json.dumps(fingerprint, separators=(',', ':'))
            return base64.b64encode(plaintext.encode()).decode()
        except:
            return "dummy"
    
    def _refresh_services(self):
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
                    'form': form
                }
                
                self._services.append(service_info)
                
                if is_active and action and input_name:
                    self._service_map[title] = service_info
                    if input_name:
                        self._video_key = input_name
                elif is_active:
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
                                    self._service_map[title] = service_info
        except Exception as e:
            print(f"Refresh services error: {e}")
    
    def get_services(self) -> List[dict]:
        if not self._services:
            self._refresh_services()
        return self._services
    
    def perform_action(self, service: str, url: str) -> Dict[str, Any]:
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
            
            decoded_response = None
            for attempt in range(3):
                r = self.session.post(action_url, headers=self._ajax_headers, data=search_data, timeout=45)
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
                    boost_r = self.session.post(submit_url, headers=self._ajax_headers, data=submit_data, timeout=45)
                    
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
    
    def _extract_timer(self, html: str) -> Optional[int]:
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
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                if len(m.groups()) == 2:
                    return int(m.group(1)) * 60 + int(m.group(2))
                return int(m.group(1))
        return None
    
    def _parse_result(self, html: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
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

# ============== FIREBASE MANAGER (REST API) ==============
class FirebaseManager:
    def __init__(self):
        self.device_id = platform.node()
        self.database_url = FIREBASE_CONFIG['databaseURL']
        self.initialized = True
        print("✅ Firebase initialized (REST API)")
    
    def verify_key(self, key: str) -> bool:
        """Verify key với server"""
        try:
            url = "https://bucac.onrender.com/api/verify-key"
            data = {
                "key": key,
                "device_id": self.device_id
            }
            
            response = requests.post(url, json=data, timeout=30)
            if response.status_code == 200:
                result = response.json()
                return result.get("success", False)
            return False
        except Exception as e:
            print(f"Verify key error: {e}")
            return False
    
    def _get_ref(self, path: str) -> str:
        """Get Firebase reference URL"""
        return f"{self.database_url}/{path}.json"
    
    def save_session(self, user_data: dict):
        """Lưu session user vào Firebase"""
        try:
            user_id = user_data.get('user_id', str(uuid.uuid4()))
            url = self._get_ref(f"sessions/{user_id}")
            data = {
                'device_id': self.device_id,
                'login_time': datetime.now().isoformat(),
                'user_data': user_data,
                'active': True
            }
            requests.patch(url, json=data, timeout=10)
        except Exception as e:
            print(f"Save session error: {e}")
    
    def save_buff_log(self, user_id: str, data: dict):
        """Lưu log buff vào Firebase"""
        try:
            url = self._get_ref(f"buff_logs/{user_id}")
            # Get current logs
            resp = requests.get(url, timeout=10)
            logs = resp.json() if resp.status_code == 200 else {}
            
            # Generate new key
            timestamp = datetime.now().isoformat()
            key = timestamp.replace(':', '-').replace('.', '-')
            logs[key] = {
                **data,
                'timestamp': timestamp,
                'device_id': self.device_id
            }
            
            requests.put(url, json=logs, timeout=10)
        except Exception as e:
            print(f"Save buff log error: {e}")
    
    def get_user_stats(self, user_id: str) -> dict:
        """Lấy thống kê user từ Firebase"""
        try:
            url = self._get_ref(f"users/{user_id}")
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.json() or {}
            return {}
        except Exception as e:
            print(f"Get user stats error: {e}")
            return {}
    
    def update_user_stats(self, user_id: str, stats: dict):
        """Cập nhật thống kê user lên Firebase"""
        try:
            url = self._get_ref(f"users/{user_id}")
            # Get current stats first
            resp = requests.get(url, timeout=10)
            current = resp.json() if resp.status_code == 200 else {}
            current.update(stats)
            requests.put(url, json=current, timeout=10)
        except Exception as e:
            print(f"Update user stats error: {e}")

# ============== LOADING OVERLAY ==============