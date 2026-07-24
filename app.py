import os
import re
import sys
import time
import html
import json
import base64
import urllib.parse
import logging
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Please install: pip install requests beautifulsoup4")
    sys.exit(1)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# FLASK APP
# ============================================================
app = Flask(__name__)
CORS(app)

# ============================================================
# CONFIG
# ============================================================
CONFIG_FILE = 'config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'cookie_string': '',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

CONFIG = load_config()

# ============================================================
# ZEFOY BOT LOGIC (GIỐNG HỆT buff.py GỐC)
# ============================================================

def parse_cookie_string(cookie_str):
    cookies = {}
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            k, v = item.split('=', 1)
            cookies[k.strip()] = v.strip()
    return cookies

def decode_zefoy_response(text):
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

def clean_html_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    return soup.get_text(separator=' ').strip()

def extract_cooldown_seconds(decoded_response):
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

def get_services(session):
    r = session.get('https://zefoy.com/')
    html_content = decode_zefoy_response(r.text)
    
    soup = BeautifulSoup(html_content, 'html.parser')
    cards = soup.find_all('div', class_='colsmenu')
    
    services = []
    for card in cards:
        title_tag = card.find('h5', class_='card-title')
        if not title_tag:
            continue
        title = title_tag.text.strip()
        btn = card.find('button')
        if not btn:
            continue
            
        is_active = 'disabled' not in btn.attrs
        
        btn_class = ""
        for cls in btn.get('class', []):
            if cls.startswith('t-') and cls.endswith('-button'):
                btn_class = cls
                break
                
        status_tag = card.find(class_='badge')
        if not status_tag:
            status_tag = card.find('small')
        status_text = status_tag.text.strip() if status_tag else ("ON" if is_active else "OFF")
        
        services.append({
            'name': title,
            'active': is_active,
            'status': status_text,
            'btn_class': btn_class,
            'menu_class': btn_class.replace('-button', '-menu') if btn_class else ""
        })
        
    return services, html_content

def get_service_form(html_content, menu_class):
    soup = BeautifulSoup(html_content, 'html.parser')
    menu_div = soup.find('div', class_=menu_class)
    if not menu_div:
        menu_div = soup.find(class_=re.compile(menu_class))
        
    if not menu_div:
        return None
        
    form = menu_div.find('form')
    if not form:
        return None
        
    action = form.get('action')
    search_input = form.find('input', type='search')
    if not search_input:
        search_input = form.find('input', class_='form-control')
        
    input_name = search_input.get('name') if search_input else None
    if not input_name:
        for inp in form.find_all('input'):
            inp_type = inp.get('type', 'text').lower()
            if inp_type in ['search', 'text'] and inp.get('name'):
                input_name = inp.get('name')
                break
    return {
        'action': action,
        'input_name': input_name
    }

class ZefoyBot:
    """Class giống logic buff.py gốc"""
    
    def __init__(self, cookie_string, user_agent=None):
        self.cookie_string = cookie_string
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.session = self._setup_session()
        self.services = []
        self.home_html = ""
        
    def _setup_session(self):
        session = requests.Session()
        cookies = parse_cookie_string(self.cookie_string)
        session.cookies.update(cookies)
        
        session.headers.update({
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5',
            'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
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
    
    def authenticate(self):
        """Kiểm tra đăng nhập giống buff.py"""
        try:
            r = self.session.get('https://zefoy.com/')
            html_content = decode_zefoy_response(r.text)
            
            if 't-followers-button' in html_content or 't-hearts-button' in html_content or 'colsmenu' in html_content:
                return True
            return False
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return False
    
    def get_services_list(self):
        """Lấy danh sách dịch vụ giống buff.py"""
        services, home_html = get_services(self.session)
        self.services = services
        self.home_html = home_html
        return services
    
    def boost(self, video_url, service_name, max_runs=10):
        """Thực hiện boost giống hệt buff.py"""
        results = {
            'success': False,
            'message': '',
            'runs': 0,
            'errors': []
        }
        
        try:
            # Lấy services nếu chưa có
            if not self.services:
                self.get_services_list()
            
            # Tìm service
            selected_service = None
            for s in self.services:
                if service_name.lower() in s['name'].lower():
                    selected_service = s
                    break
            
            if not selected_service:
                results['message'] = f'Không tìm thấy dịch vụ "{service_name}"'
                return results
            
            if not selected_service['active']:
                results['message'] = f'Dịch vụ "{selected_service["name"]}" đang bảo trì'
                return results
            
            # Lấy form giống buff.py
            form_info = get_service_form(self.home_html, selected_service['menu_class'])
            if not form_info or not form_info['action'] or not form_info['input_name']:
                results['message'] = f'Không tìm thấy form cho dịch vụ {selected_service["name"]}'
                return results
            
            action_url = f"https://zefoy.com/{form_info['action']}"
            input_name = form_info['input_name']
            
            # AJAX headers giống buff.py
            ajax_headers = {
                'accept': '*/*',
                'accept-language': 'vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': 'https://zefoy.com',
                'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': self.user_agent,
                'x-requested-with': 'XMLHttpRequest',
                'referer': 'https://zefoy.com/'
            }
            
            runs = 0
            while runs < max_runs:
                try:
                    # Gửi request tìm kiếm - giống buff.py
                    search_data = {input_name: video_url}
                    
                    # Thử tối đa 3 lần nếu gặp Checking Timer
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
                    
                    # Kiểm tra cooldown
                    if total_wait > 0:
                        results['errors'].append(f"Cooldown: {countdown_text}")
                        results['message'] = f"Đang chờ cooldown: {countdown_text}"
                        return results
                    
                    # Tìm form submit - giống buff.py
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
                        
                        # Chọn option cao nhất - giống buff.py
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
                        
                        # Gửi boost request
                        boost_r = self.session.post(submit_url, headers=ajax_headers, data=submit_data)
                        decoded_boost = decode_zefoy_response(boost_r.text)
                        result_text = clean_html_text(decoded_boost)
                        
                        if not result_text:
                            result_text = "Phản hồi không chứa thông báo văn bản."
                        
                        runs += 1
                        results['runs'] = runs
                        results['message'] = result_text
                        results['success'] = True
                        
                        # Chờ 10 giây trước lần tiếp theo - giống buff.py
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
# HTML TEMPLATE - GIAO DIỆN GIỐNG BUFF.PY
# ============================================================
INDEX_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔮 Zefoy Bot - TikTok Tool</title>
    <style>
        /* ===== RESET ===== */
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
            max-width: 1100px;
            margin: 20px auto;
            padding: 30px;
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
            padding-bottom: 25px;
            border-bottom: 1px solid rgba(0,255,80,0.15);
            margin-bottom: 25px;
        }
        .glitch {
            font-family: 'Orbitron', monospace;
            font-size: 3em;
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
            font-size: 1.1em;
            color: var(--secondary);
            margin-top: 8px;
            text-shadow: 0 0 20px rgba(0,229,255,0.2);
            letter-spacing: 2px;
        }
        .version {
            font-size: 0.85em;
            color: var(--text-muted);
            margin-top: 5px;
        }
        
        .status-bar {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            padding: 15px 20px;
            background: var(--bg-card);
            border-radius: 8px;
            border: 1px solid rgba(0,255,80,0.1);
            margin-bottom: 25px;
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 5px 0;
        }
        .status-item .label { color: var(--text-muted); font-size: 0.9em; }
        .status-item .value { color: var(--primary); font-weight: bold; }
        .status-item .value.offline { color: var(--danger); }
        .status-item .value.online { color: var(--primary); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
        
        .tabs {
            display: flex;
            gap: 5px;
            margin-bottom: 25px;
            border-bottom: 1px solid rgba(0,255,80,0.1);
            padding-bottom: 5px;
            flex-wrap: wrap;
        }
        .tab-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 10px 25px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.95em;
            cursor: pointer;
            transition: all 0.3s ease;
            border-radius: 6px 6px 0 0;
            position: relative;
        }
        .tab-btn:hover { color: var(--text-color); background: rgba(0,255,80,0.05); }
        .tab-btn.active {
            color: var(--primary);
            background: rgba(0,255,80,0.08);
        }
        .tab-btn.active::after {
            content: '';
            position: absolute;
            bottom: -6px;
            left: 0;
            width: 100%;
            height: 2px;
            background: var(--primary);
            box-shadow: 0 0 20px rgba(0,255,80,0.5);
        }
        .tab-content { display: none; animation: fadeIn 0.4s ease; }
        .tab-content.active { display: block; }
        
        .config-section, .boost-section, .logs-section {
            background: var(--bg-card);
            padding: 25px;
            border-radius: 10px;
            border: 1px solid rgba(0,255,80,0.08);
            margin-bottom: 20px;
        }
        .config-section h3, .boost-section h3, .logs-section h3 {
            color: var(--secondary);
            font-family: 'Orbitron', monospace;
            font-size: 1.1em;
            margin-bottom: 20px;
            text-shadow: 0 0 20px rgba(0,229,255,0.2);
        }
        
        .form-group { margin-bottom: 18px; }
        .form-group label {
            display: block;
            color: var(--text-color);
            font-weight: bold;
            margin-bottom: 6px;
            font-size: 0.95em;
        }
        .form-group input, .form-group textarea, .form-group select {
            width: 100%;
            padding: 12px 15px;
            background: var(--bg-input);
            border: 1px solid rgba(0,255,80,0.15);
            border-radius: 6px;
            color: var(--text-color);
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.95em;
            transition: all 0.3s ease;
        }
        .form-group input:focus, .form-group textarea:focus, .form-group select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 20px rgba(0,255,80,0.1);
        }
        .form-group textarea { resize: vertical; min-height: 80px; }
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
            font-size: 0.8em;
            margin-top: 4px;
        }
        
        .btn-group {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 10px;
        }
        .btn {
            padding: 10px 25px;
            border: none;
            border-radius: 6px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 0.95em;
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
        .btn-sm { padding: 6px 15px; font-size: 0.8em; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none !important; }
        
        .result-box {
            margin-top: 15px;
            padding: 15px;
            border-radius: 6px;
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(0,255,80,0.1);
            min-height: 50px;
            display: none;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .result-box.show { display: block; animation: fadeIn 0.4s ease; }
        .result-box.success { border-color: var(--primary); color: var(--primary); }
        .result-box.error { border-color: var(--danger); color: var(--danger); }
        .result-box.info { border-color: var(--secondary); color: var(--secondary); }
        .result-box.warning { border-color: var(--warning); color: var(--warning); }
        
        .services-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 15px;
            margin: 15px 0;
        }
        .service-card {
            background: rgba(0,0,0,0.3);
            padding: 15px;
            border-radius: 8px;
            border: 1px solid rgba(0,255,80,0.08);
            text-align: center;
        }
        .service-card .name { font-size: 1em; color: var(--text-color); }
        .service-card .status {
            font-size: 0.85em;
            margin-top: 5px;
        }
        .service-card .status.online { color: var(--primary); }
        .service-card .status.offline { color: var(--danger); }
        
        .progress-box {
            margin-top: 15px;
            padding: 15px;
            background: rgba(0,0,0,0.3);
            border-radius: 6px;
            border: 1px solid rgba(0,255,80,0.1);
            display: none;
        }
        .progress-box.show { display: block; }
        .progress-bar {
            width: 100%;
            height: 6px;
            background: rgba(255,255,255,0.05);
            border-radius: 3px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            border-radius: 3px;
            transition: width 0.5s ease;
            width: 0%;
        }
        .progress-text {
            color: var(--text-muted);
            font-size: 0.9em;
            margin-top: 8px;
            text-align: center;
        }
        
        .logs-container {
            background: rgba(0,0,0,0.5);
            border-radius: 6px;
            padding: 15px;
            max-height: 400px;
            overflow-y: auto;
            font-size: 0.85em;
            border: 1px solid rgba(0,255,80,0.05);
        }
        .logs-container::-webkit-scrollbar { width: 4px; }
        .logs-container::-webkit-scrollbar-track { background: rgba(0,0,0,0.3); }
        .logs-container::-webkit-scrollbar-thumb { background: var(--primary); border-radius: 2px; }
        .log-entry {
            padding: 4px 0;
            border-bottom: 1px solid rgba(255,255,255,0.02);
            line-height: 1.6;
        }
        .log-entry.system { color: var(--secondary); }
        .log-entry.success { color: var(--primary); }
        .log-entry.error { color: var(--danger); }
        .log-entry.warning { color: var(--warning); }
        .log-entry .time { color: var(--text-muted); margin-right: 10px; }
        
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid rgba(0,255,80,0.08);
            text-align: center;
            color: var(--text-muted);
            font-size: 0.8em;
            display: flex;
            justify-content: center;
            gap: 15px;
            flex-wrap: wrap;
        }
        .footer strong { color: var(--primary); }
        
        .guide { color: var(--text-muted); font-size: 0.9em; line-height: 1.8; }
        .guide ol { padding-left: 20px; margin-bottom: 10px; }
        .guide a { color: var(--secondary); text-decoration: none; }
        .guide a:hover { text-decoration: underline; }
        .code-block {
            background: rgba(0,0,0,0.5);
            padding: 12px;
            border-radius: 4px;
            color: var(--secondary);
            font-size: 0.85em;
            overflow-x: auto;
            border: 1px solid rgba(0,229,255,0.1);
            margin-top: 8px;
        }
        
        .logs-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }
        .logs-actions { display: flex; gap: 8px; }
        
        @media (max-width: 768px) {
            .container { margin: 10px; padding: 15px; }
            .glitch { font-size: 2em; }
            .status-bar { grid-template-columns: 1fr; gap: 5px; }
            .tab-btn { flex: 1; text-align: center; padding: 8px 10px; font-size: 0.8em; }
            .btn-group { flex-direction: column; }
            .btn { width: 100%; text-align: center; }
            .services-grid { grid-template-columns: 1fr; }
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

        <div class="status-bar" id="statusBar">
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

        <div class="tabs">
            <button class="tab-btn active" data-tab="config">⚙️ Cấu hình</button>
            <button class="tab-btn" data-tab="services">📋 Dịch vụ</button>
            <button class="tab-btn" data-tab="boost">🚀 Boost</button>
            <button class="tab-btn" data-tab="logs">📊 Logs</button>
        </div>

        <!-- TAB CONFIG -->
        <div class="tab-content active" id="tab-config">
            <div class="config-section">
                <h3>🔑 Cookie & User-Agent</h3>
                <div class="form-group">
                    <label for="cookieInput">🍪 Cookie String</label>
                    <textarea id="cookieInput" placeholder="PHPSESSID=xxx; cf_clearance=xxx; ..." rows="4"></textarea>
                    <small>Lấy cookie từ trình duyệt sau khi đăng nhập zefoy.com</small>
                </div>
                <div class="form-group">
                    <label for="uaInput">🖥️ User-Agent</label>
                    <input type="text" id="uaInput" placeholder="Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...">
                    <small>Để trống dùng User-Agent mặc định</small>
                </div>
                <div class="btn-group">
                    <button class="btn btn-primary" onclick="saveConfig()">💾 Lưu cấu hình</button>
                    <button class="btn btn-secondary" onclick="testConnection()">🔌 Kiểm tra kết nối</button>
                    <button class="btn btn-danger" onclick="clearConfig()">🗑️ Xóa</button>
                </div>
                <div id="configResult" class="result-box"></div>
            </div>
            <div class="config-section">
                <h3>📋 Hướng dẫn lấy Cookie</h3>
                <div class="guide">
                    <ol>
                        <li>Đăng nhập vào <a href="https://zefoy.com" target="_blank">zefoy.com</a></li>
                        <li>Mở DevTools (F12) → Tab Application → Cookies</li>
                        <li>Sao chép toàn bộ cookie string</li>
                        <li>Dán vào ô Cookie String bên trên</li>
                    </ol>
                    <div class="code-block">
                        // Ví dụ cookie string<br>
                        PHPSESSID=xxx; cf_clearance=xxx; zf=xxx; za=200
                    </div>
                </div>
            </div>
        </div>

        <!-- TAB SERVICES -->
        <div class="tab-content" id="tab-services">
            <div class="config-section">
                <h3>📋 Danh sách dịch vụ</h3>
                <button class="btn btn-secondary" onclick="loadServices()" style="margin-bottom:15px;">🔄 Tải danh sách</button>
                <div id="servicesContainer">
                    <div style="color:var(--text-muted);text-align:center;padding:20px;">
                        Nhấn "Tải danh sách" để xem các dịch vụ có sẵn
                    </div>
                </div>
            </div>
        </div>

        <!-- TAB BOOST -->
        <div class="tab-content" id="tab-boost">
            <div class="boost-section">
                <h3>🚀 Thực hiện Boost</h3>
                <div class="form-group">
                    <label for="videoUrl">📹 Link TikTok</label>
                    <input type="text" id="videoUrl" placeholder="https://www.tiktok.com/@username/video/123456789">
                    <small>Link video hoặc profile TikTok</small>
                </div>
                <div class="form-group">
                    <label for="serviceSelect">🎯 Dịch vụ</label>
                    <select id="serviceSelect">
                        <option value="followers">👥 Followers</option>
                        <option value="hearts">❤️ Hearts (Likes)</option>
                        <option value="views">👁️ Views</option>
                        <option value="comments">💬 Comments</option>
                        <option value="shares">🔄 Shares</option>
                        <option value="favorites">⭐ Favorites</option>
                        <option value="live">🔴 Live Stream</option>
                    </select>
                    <small>Chọn dịch vụ muốn tăng (phải khớp với tên trên Zefoy)</small>
                </div>
                <div class="form-group">
                    <label for="maxRuns">🔢 Số lượt chạy</label>
                    <input type="number" id="maxRuns" value="10" min="1" max="100">
                    <small>Mỗi lượt sẽ tăng tương tác, tối đa 100</small>
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
        </div>

        <!-- TAB LOGS -->
        <div class="tab-content" id="tab-logs">
            <div class="logs-section">
                <div class="logs-header">
                    <h3>📊 Logs System</h3>
                    <div class="logs-actions">
                        <button class="btn btn-sm btn-secondary" onclick="clearLogs()">🗑️ Clear</button>
                        <button class="btn btn-sm btn-primary" onclick="exportLogs()">📥 Export</button>
                    </div>
                </div>
                <div class="logs-container" id="logsContainer">
                    <div class="log-entry system"><span class="time">[SYSTEM]</span> 🔮 Zefoy Bot v3.0.3 đã sẵn sàng</div>
                    <div class="log-entry system"><span class="time">[SYSTEM]</span> 👋 Chào mừng bạn đến với tool TikTok</div>
                </div>
            </div>
        </div>

        <div class="footer">
            <span>🔒 Bản quyền thuộc về <strong>TIENDEV</strong></span>
            <span>|</span>
            <span>⚡ Tool siêu VIP Pro</span>
            <span>|</span>
            <span>💀 Hacker Style</span>
        </div>
    </div>

    <script>
        // ===== MATRIX =====
        (function() {
            const c = document.getElementById('matrix');
            const ctx = c.getContext('2d');
            c.width = window.innerWidth;
            c.height = window.innerHeight;
            const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
            const fontSize = 14;
            const columns = Math.floor(c.width / fontSize);
            const drops = Array(columns).fill(1);
            function draw() {
                ctx.fillStyle = 'rgba(0,0,0,0.05)';
                ctx.fillRect(0, 0, c.width, c.height);
                ctx.fillStyle = '#00ff50';
                ctx.font = fontSize + 'px monospace';
                for (let i = 0; i < drops.length; i++) {
                    ctx.fillText(chars[Math.floor(Math.random() * chars.length)], i * fontSize, drops[i] * fontSize);
                    if (drops[i] * fontSize > c.height && Math.random() > 0.975) drops[i] = 0;
                    drops[i]++;
                }
            }
            setInterval(draw, 60);
            window.addEventListener('resize', () => {
                c.width = window.innerWidth;
                c.height = window.innerHeight;
            });
        })();

        // ===== STATE =====
        const state = {
            isRunning: false,
            totalRuns: 0,
            successRuns: 0,
            failRuns: 0,
            logs: []
        };
        
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
        const configResult = $('configResult');
        const boostResult = $('boostResult');
        const boostProgress = $('boostProgress');
        const progressFill = $('progressFill');
        const progressText = $('progressText');
        const servicesContainer = $('servicesContainer');

        // ===== TABS =====
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                this.classList.add('active');
                document.getElementById('tab-' + this.dataset.tab).classList.add('active');
            });
        });

        // ===== LOGS =====
        function addLog(message, type = 'system') {
            const time = new Date().toLocaleTimeString();
            const entry = document.createElement('div');
            entry.className = 'log-entry ' + type;
            entry.innerHTML = '<span class="time">[' + time + ']</span> ' + message;
            logsContainer.appendChild(entry);
            logsContainer.scrollTop = logsContainer.scrollHeight;
            state.logs.push({ time, message, type });
        }
        
        function clearLogs() {
            logsContainer.innerHTML = '';
            state.logs = [];
            addLog('🗑️ Logs đã được xóa', 'system');
        }
        
        function exportLogs() {
            const text = state.logs.map(l => '[' + l.time + '] ' + l.message).join('\\n');
            const blob = new Blob([text], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'zefoy-logs-' + Date.now() + '.txt';
            a.click();
            URL.revokeObjectURL(url);
            addLog('📥 Đã export logs', 'system');
        }

        function showResult(el, msg, type = 'info') {
            el.textContent = msg;
            el.className = 'result-box show ' + type;
        }
        
        function hideResult(el) {
            el.className = 'result-box';
            el.textContent = '';
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
        
        function updateStats() {
            runCount.textContent = state.totalRuns;
        }

        // ===== API =====
        async function saveConfig() {
            const cookie = cookieInput.value.trim();
            const ua = uaInput.value.trim();
            if (!cookie) {
                showResult(configResult, '⚠️ Vui lòng nhập Cookie String!', 'error');
                return;
            }
            showResult(configResult, '⏳ Đang lưu cấu hình...', 'info');
            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cookie_string: cookie, user_agent: ua })
                });
                const data = await res.json();
                if (data.success) {
                    showResult(configResult, '✅ Lưu cấu hình thành công!', 'success');
                    addLog('✅ Đã lưu cấu hình mới', 'success');
                    await testConnection();
                } else {
                    showResult(configResult, '❌ ' + data.message, 'error');
                    addLog('❌ Lỗi lưu config: ' + data.message, 'error');
                }
            } catch (e) {
                showResult(configResult, '❌ Lỗi: ' + e.message, 'error');
                addLog('❌ Lỗi: ' + e.message, 'error');
            }
        }

        async function testConnection() {
            const cookie = cookieInput.value.trim();
            const ua = uaInput.value.trim();
            if (!cookie) {
                showResult(configResult, '⚠️ Vui lòng nhập Cookie String trước!', 'error');
                return;
            }
            showResult(configResult, '⏳ Đang kiểm tra kết nối...', 'info');
            try {
                const res = await fetch('/api/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cookie_string: cookie, user_agent: ua })
                });
                const data = await res.json();
                if (data.success) {
                    updateStatus(true, data.services || 0);
                    showResult(configResult, '✅ Kết nối thành công! ' + (data.services || 0) + ' dịch vụ.', 'success');
                    addLog('✅ Kết nối thành công, ' + (data.services || 0) + ' dịch vụ', 'success');
                    if (data.services_list) {
                        renderServices(data.services_list);
                    }
                } else {
                    updateStatus(false);
                    showResult(configResult, '❌ ' + data.message, 'error');
                    addLog('❌ Kết nối thất bại: ' + data.message, 'error');
                }
            } catch (e) {
                updateStatus(false);
                showResult(configResult, '❌ Lỗi: ' + e.message, 'error');
                addLog('❌ Lỗi: ' + e.message, 'error');
            }
        }

        function clearConfig() {
            if (!confirm('Xóa cấu hình?')) return;
            cookieInput.value = '';
            uaInput.value = '';
            hideResult(configResult);
            updateStatus(false);
            addLog('🗑️ Đã xóa cấu hình', 'system');
        }

        async function loadServices() {
            const cookie = cookieInput.value.trim();
            if (!cookie) {
                showResult(configResult, '⚠️ Vui lòng nhập Cookie trước!', 'error');
                document.querySelector('[data-tab="config"]').click();
                return;
            }
            showResult(configResult, '⏳ Đang tải danh sách dịch vụ...', 'info');
            try {
                const res = await fetch('/api/services', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cookie_string: cookie,
                        user_agent: uaInput.value.trim()
                    })
                });
                const data = await res.json();
                if (data.success) {
                    renderServices(data.data);
                    updateStatus(true, data.data.length);
                    showResult(configResult, '✅ Đã tải ' + data.data.length + ' dịch vụ', 'success');
                    addLog('✅ Đã tải ' + data.data.length + ' dịch vụ', 'success');
                } else {
                    showResult(configResult, '❌ ' + data.message, 'error');
                    addLog('❌ Lỗi tải services: ' + data.message, 'error');
                }
            } catch (e) {
                showResult(configResult, '❌ Lỗi: ' + e.message, 'error');
                addLog('❌ Lỗi: ' + e.message, 'error');
            }
        }

        function renderServices(services) {
            if (!services || services.length === 0) {
                servicesContainer.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:20px;">Không có dịch vụ nào</div>';
                return;
            }
            let html = '<div class="services-grid">';
            services.forEach(s => {
                const statusClass = s.active ? 'online' : 'offline';
                const statusText = s.active ? '🟢 ONLINE' : '🔴 OFFLINE';
                html += '<div class="service-card">';
                html += '<div class="name">' + s.name + '</div>';
                html += '<div class="status ' + statusClass + '">' + statusText + ' (' + s.status + ')</div>';
                html += '</div>';
            });
            html += '</div>';
            servicesContainer.innerHTML = html;
        }

        async function startBoost() {
            if (state.isRunning) {
                addLog('⚠️ Bot đang chạy!', 'warning');
                return;
            }
            
            const url = videoUrl.value.trim();
            if (!url) {
                showResult(boostResult, '⚠️ Nhập link TikTok!', 'error');
                return;
            }
            
            const cookie = cookieInput.value.trim();
            if (!cookie) {
                showResult(boostResult, '⚠️ Cấu hình Cookie trước!', 'error');
                document.querySelector('[data-tab="config"]').click();
                return;
            }
            
            const service = serviceSelect.value;
            const runs = parseInt(maxRuns.value) || 10;
            
            state.isRunning = true;
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
                        video_url: url,
                        service: service,
                        max_runs: runs,
                        cookie_string: cookie,
                        user_agent: uaInput.value.trim()
                    })
                });
                const data = await res.json();
                
                progressFill.style.width = '100%';
                progressText.textContent = 'Hoàn tất!';
                
                if (data.success) {
                    state.totalRuns += data.runs || 0;
                    state.successRuns += data.runs || 0;
                    let msg = '✅ ' + (data.message || 'Boost thành công!');
                    if (data.runs) msg += ' (' + data.runs + ' lượt)';
                    if (data.errors && data.errors.length) {
                        msg += '\\n⚠️ Lỗi: ' + data.errors.join('\\n');
                    }
                    showResult(boostResult, msg, 'success');
                    addLog('✅ Boost thành công: ' + (data.runs || 0) + ' lượt', 'success');
                } else {
                    state.failRuns += 1;
                    let msg = '❌ ' + (data.message || 'Lỗi không xác định');
                    if (data.errors && data.errors.length) {
                        msg += '\\n⚠️ ' + data.errors.join('\\n');
                    }
                    showResult(boostResult, msg, 'error');
                    addLog('❌ Boost thất bại: ' + (data.message || ''), 'error');
                }
            } catch (e) {
                state.failRuns += 1;
                showResult(boostResult, '❌ Lỗi: ' + e.message, 'error');
                addLog('❌ Lỗi boost: ' + e.message, 'error');
            }
            
            setTimeout(() => {
                boostProgress.classList.remove('show');
                progressFill.style.width = '0%';
            }, 3000);
            
            state.isRunning = false;
            updateStats();
        }

        function stopBoost() {
            if (!state.isRunning) {
                addLog('⚠️ Bot không đang chạy', 'warning');
                return;
            }
            state.isRunning = false;
            addLog('⏹️ Đã dừng boost', 'warning');
            showResult(boostResult, '⏹️ Đã dừng boost', 'warning');
        }

        // ===== LOAD CONFIG =====
        window.onload = function() {
            fetch('/api/config')
                .then(res => res.json())
                .then(data => {
                    if (data.cookie_string) {
                        cookieInput.value = data.cookie_string;
                        addLog('📂 Đã tải cấu hình từ server', 'system');
                    }
                    if (data.user_agent) uaInput.value = data.user_agent;
                    if (data.cookie_string) testConnection();
                })
                .catch(() => {});
        };
    </script>
</body>
</html>
"""

# ============================================================
# FLASK ROUTES
# ============================================================

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(CONFIG)

@app.route('/api/config', methods=['POST'])
def save_config_api():
    try:
        data = request.json
        cookie = data.get('cookie_string', '').strip()
        ua = data.get('user_agent', '').strip()
        
        if not cookie:
            return jsonify({'success': False, 'message': 'Cookie không được để trống'}), 400
        
        CONFIG['cookie_string'] = cookie
        if ua:
            CONFIG['user_agent'] = ua
        save_config(CONFIG)
        return jsonify({'success': True, 'message': 'Đã lưu cấu hình'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/test', methods=['POST'])
def test_connection():
    try:
        data = request.json
        cookie = data.get('cookie_string', '').strip()
        ua = data.get('user_agent', '').strip()
        
        if not cookie:
            return jsonify({'success': False, 'message': 'Cookie không được để trống'}), 400
        
        bot = ZefoyBot(cookie, ua or CONFIG.get('user_agent', ''))
        
        if bot.authenticate():
            services = bot.get_services_list()
            return jsonify({
                'success': True,
                'services': len(services),
                'services_list': services,
                'message': 'Kết nối thành công'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Cookie hết hạn hoặc không hợp lệ. Vui lòng cập nhật cookie mới.'
            }), 401
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/services', methods=['POST'])
def get_services_api():
    try:
        data = request.json or {}
        cookie = data.get('cookie_string', '').strip()
        ua = data.get('user_agent', '').strip()
        
        if not cookie:
            cookie = CONFIG.get('cookie_string', '')
        
        if not cookie:
            return jsonify({'success': False, 'message': 'Cookie không được để trống'}), 400
        
        bot = ZefoyBot(cookie, ua or CONFIG.get('user_agent', ''))
        
        if not bot.authenticate():
            return jsonify({'success': False, 'message': 'Cookie hết hạn hoặc không hợp lệ'}), 401
        
        services = bot.get_services_list()
        return jsonify({
            'success': True,
            'data': services,
            'message': f'Found {len(services)} services'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/boost', methods=['POST'])
def boost_api():
    try:
        data = request.json
        video_url = data.get('video_url', '').strip()
        service = data.get('service', 'followers')
        max_runs = int(data.get('max_runs', 10))
        cookie = data.get('cookie_string', '').strip()
        ua = data.get('user_agent', '').strip()
        
        if not video_url:
            return jsonify({'success': False, 'message': 'video_url không được để trống'}), 400
        
        if not cookie:
            return jsonify({'success': False, 'message': 'Cookie không được để trống'}), 400
        
        bot = ZefoyBot(cookie, ua or CONFIG.get('user_agent', ''))
        result = bot.boost(video_url, service, max_runs)
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'runs': 0, 'errors': [str(e)]}), 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'service': 'Zefoy Bot API'})

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    
    if os.environ.get('COOKIE_STRING'):
        CONFIG['cookie_string'] = os.environ.get('COOKIE_STRING')
    if os.environ.get('USER_AGENT'):
        CONFIG['user_agent'] = os.environ.get('USER_AGENT')
    save_config(CONFIG)
    
    app.run(host='0.0.0.0', port=port, debug=debug)
