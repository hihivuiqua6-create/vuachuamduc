"""
Zefoy Web API — Render-ready FastAPI wrapper (UPDATED with new logic + Telegram Bot)
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import time
import uuid
import json
import urllib.parse
from typing import Any, Optional
from datetime import datetime
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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

# Telegram Config
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_LINK = os.environ.get("TELEGRAM_CHANNEL_LINK", "https://t.me/your_channel")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]

# Database files
DB_FILE = "telegram_users.json"
TELECONFIG_FILE = "telegram_config.json"

app = FastAPI(title="Zefoy Web API + Telegram Bot", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import traceback

@app.exception_handler(Exception)
async def _all_ex(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print("[UNHANDLED]", tb, flush=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc) or "unknown error",
        },
    )

# ============== DATABASE ==============
class UserDB:
    def __init__(self):
        self.data = self._load()
        self._lock = threading.Lock()
    
    def _load(self) -> dict:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save(self):
        with self._lock:
            with open(DB_FILE, 'w') as f:
                json.dump(self.data, f, indent=2)
    
    def get(self, user_id: str) -> dict:
        return self.data.get(user_id, {})
    
    def update(self, user_id: str, data: dict):
        self.data[user_id] = data
        self._save()
    
    def get_daily_usage(self, user_id: str) -> int:
        user = self.get(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        if user.get("last_date") != today:
            return 0
        return user.get("daily_usage", 0)
    
    def increment_daily(self, user_id: str) -> int:
        user = self.get(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        if user.get("last_date") != today:
            user["daily_usage"] = 0
            user["last_date"] = today
        user["daily_usage"] = user.get("daily_usage", 0) + 1
        user["total_usage"] = user.get("total_usage", 0) + 1
        user["last_used"] = datetime.now().isoformat()
        self.update(user_id, user)
        return user["daily_usage"]
    
    def is_admin(self, user_id: str) -> bool:
        return int(user_id) in ADMIN_IDS

db = UserDB()

# ============== TELEGRAM BOT ==============
class ZefoyTelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.channel_link = TELEGRAM_CHANNEL_LINK
        self.channel_username = self._extract_channel_username()
        self.running = False
        self.update_id = 0
        self.pending_sessions = {}
        self._handlers = {}
        self.API_URL = os.environ.get("API_URL", "https://your-app.onrender.com")
    
    def _extract_channel_username(self) -> str:
        match = re.search(r"t\.me/([^/\s?]+)", self.channel_link)
        if match:
            return match.group(1)
        return self.channel_link.replace("https://t.me/", "").strip()
    
    def _request(self, method: str, data: dict = None) -> dict:
        try:
            url = f"{self.base_url}/{method}"
            resp = requests.post(url, json=data, timeout=30)
            return resp.json()
        except Exception as e:
            print(f"Telegram API error: {e}")
            return {"ok": False}
    
    def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML") -> bool:
        data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        result = self._request("sendMessage", data)
        return result.get("ok", False)
    
    def send_photo(self, chat_id: int, photo_base64: str, caption: str = "") -> bool:
        try:
            data = {
                "chat_id": chat_id,
                "photo": photo_base64,
                "caption": caption,
                "parse_mode": "HTML"
            }
            result = self._request("sendPhoto", data)
            return result.get("ok", False)
        except:
            return False
    
    def is_member(self, user_id: int) -> bool:
        try:
            data = {"chat_id": f"@{self.channel_username}", "user_id": user_id}
            result = self._request("getChatMember", data)
            if result.get("ok"):
                status = result.get("result", {}).get("status", "")
                return status in ["member", "administrator", "creator"]
            return False
        except:
            return False
    
    def broadcast(self, text: str) -> int:
        sent = 0
        for uid in db.data.keys():
            try:
                if self.send_message(int(uid), f"📢 {text}"):
                    sent += 1
                time.sleep(0.1)
            except:
                pass
        return sent
    
    def process_update(self, update: dict):
        if "message" not in update:
            return
        
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = str(msg["from"]["id"])
        username = msg["from"].get("username", "unknown")
        text = msg.get("text", "")
        
        if not self.is_member(chat_id):
            self.send_message(
                chat_id,
                f"❌ Bạn cần tham gia kênh {self.channel_link} để dùng bot!\n"
                f"📌 Sau khi tham gia, gửi /start lại."
            )
            return
        
        if text.startswith("/"):
            self._handle_command(chat_id, user_id, username, text)
        else:
            self._handle_buff(chat_id, user_id, username, text)
    
    def _handle_command(self, chat_id: int, user_id: str, username: str, text: str):
        cmd = text.split()[0].lower()
        
        if cmd == "/start":
            daily = db.get_daily_usage(user_id)
            total = db.get(user_id).get("total_usage", 0)
            msg = (
                f"🤖 <b>Zefoy Buff Bot</b>\n\n"
                f"👤 User: @{username}\n"
                f"📊 Hôm nay: {daily}/15 lượt\n"
                f"📈 Tổng: {total} lượt\n\n"
                f"<b>Cách dùng:</b>\n"
                f"Gửi link TikTok + dịch vụ\n"
                f"Ví dụ: <code>https://tiktok.com/... hearts</code>\n\n"
                f"<b>Dịch vụ:</b> hearts, views, followers, shares, comments\n"
                f"📌 Cần tham gia {self.channel_link} để dùng bot!"
            )
            self.send_message(chat_id, msg)
            
        elif cmd == "/help":
            msg = (
                f"📖 <b>Hướng dẫn</b>\n\n"
                f"/start - Xem thông tin\n"
                f"/help - Hướng dẫn này\n"
                f"/stats - Thống kê (admin)\n"
                f"/broadcast - Gửi tin (admin)\n"
                f"/reset - Reset user (admin)\n\n"
                f"<b>Buff:</b>\n"
                f"<code>https://tiktok.com/... hearts</code>"
            )
            self.send_message(chat_id, msg)
            
        elif cmd == "/stats" and db.is_admin(user_id):
            total_users = len(db.data)
            total_usage = sum(u.get("total_usage", 0) for u in db.data.values())
            today_usage = sum(1 for u in db.data.values() if u.get("last_date") == datetime.now().strftime("%Y-%m-%d"))
            msg = (
                f"📊 <b>Bot Stats</b>\n\n"
                f"👥 Users: {total_users}\n"
                f"📈 Total buffs: {total_usage}\n"
                f"📅 Today: {today_usage}\n"
                f"🟢 Status: Online"
            )
            self.send_message(chat_id, msg)
            
        elif cmd == "/broadcast" and db.is_admin(user_id):
            if len(text.split()) > 1:
                broadcast_text = text.split(" ", 1)[1]
                sent = self.broadcast(broadcast_text)
                self.send_message(chat_id, f"✅ Đã gửi broadcast tới {sent} users")
            else:
                self.send_message(chat_id, "⚠️ /broadcast <nội dung>")
        
        elif cmd == "/reset" and db.is_admin(user_id):
            parts = text.split()
            if len(parts) == 2:
                target = parts[1]
                user_data = db.get(target)
                if user_data:
                    user_data["daily_usage"] = 0
                    user_data["last_date"] = ""
                    db.update(target, user_data)
                    self.send_message(chat_id, f"✅ Đã reset user {target}")
                else:
                    self.send_message(chat_id, f"❌ Không tìm thấy user {target}")
            else:
                self.send_message(chat_id, "⚠️ /reset <user_id>")
        
        elif cmd == "/captcha":
            self._handle_captcha(chat_id, user_id, text)
        else:
            self.send_message(chat_id, f"❌ Lệnh không hợp lệ. Gửi /help")
    
    def _handle_captcha(self, chat_id: int, user_id: str, text: str):
        parts = text.split()
        if len(parts) < 2:
            self.send_message(chat_id, "⚠️ /captcha <mã>")
            return
        
        answer = parts[1]
        pending = self.pending_sessions.get(user_id)
        if not pending:
            self.send_message(chat_id, "❌ Không có session đang chờ")
            return
        
        session_id = pending["session_id"]
        service = pending["service"]
        url = pending["url"]
        
        try:
            solve_resp = requests.post(
                f"{self.API_URL}/api/solve",
                json={"session_id": session_id, "answer": answer},
                timeout=30
            )
            if solve_resp.status_code != 200:
                self.send_message(chat_id, "❌ Lỗi gửi captcha")
                return
            
            solve_data = solve_resp.json()
            if not solve_data.get("ok"):
                self.send_message(chat_id, "❌ Captcha sai, thử lại!")
                return
            
            run_resp = requests.post(
                f"{self.API_URL}/api/run",
                json={"session_id": session_id, "service": service.capitalize(), "url": url},
                timeout=60
            )
            if run_resp.status_code == 200:
                result = run_resp.json()
                if result.get("ok"):
                    amount = result.get("amount", 0)
                    db.increment_daily(user_id)
                    total = db.get(user_id).get("total_usage", 0)
                    msg = (
                        f"✅ <b>Buff thành công!</b>\n\n"
                        f"📊 +{amount} {service}\n"
                        f"📅 Hôm nay: {db.get_daily_usage(user_id)}/15\n"
                        f"📈 Tổng: {total}\n"
                        f"🔗 {url}"
                    )
                    self.send_message(chat_id, msg)
                    del self.pending_sessions[user_id]
                else:
                    cooldown = result.get("cooldown")
                    if cooldown:
                        self.send_message(chat_id, f"⏳ Cooldown {cooldown}s")
                    else:
                        self.send_message(chat_id, f"❌ {result.get('message', 'Lỗi')}")
            else:
                self.send_message(chat_id, "❌ Lỗi khi buff")
        except Exception as e:
            self.send_message(chat_id, f"❌ Lỗi: {str(e)}")
    
    def _handle_buff(self, chat_id: int, user_id: str, username: str, text: str):
        daily = db.get_daily_usage(user_id)
        if daily >= 15:
            self.send_message(
                chat_id,
                f"❌ Hết 15 lượt hôm nay!\n"
                f"📊 {daily}/15 - Đợi ngày mai nhé!"
            )
            return
        
        services = ["hearts", "views", "followers", "shares", "comments", "favorites"]
        service = None
        for svc in services:
            if svc in text.lower():
                service = svc
                break
        
        if not service:
            self.send_message(
                chat_id,
                f"❌ Không tìm thấy dịch vụ.\n"
                f"Dịch vụ: {', '.join(services)}\n"
                f"Ví dụ: <code>https://tiktok.com/... hearts</code>"
            )
            return
        
        url_match = re.search(r"https?://[^\s]+", text)
        if not url_match:
            self.send_message(chat_id, "❌ Không tìm thấy link TikTok")
            return
        
        url = url_match.group(0)
        self.send_message(chat_id, f"⏳ Đang buff {service}...")
        
        try:
            start_resp = requests.post(f"{self.API_URL}/api/start", json={}, timeout=30)
            if start_resp.status_code != 200:
                self.send_message(chat_id, "❌ Lỗi kết nối server")
                return
            
            session_data = start_resp.json()
            session_id = session_data.get("session_id")
            captcha_b64 = session_data.get("captcha_b64")
            
            if captcha_b64:
                # Try auto OCR
                try:
                    from zefoy.ocr import solve_with_fallbacks
                    import base64 as b64
                    img_bytes = b64.b64decode(captcha_b64)
                    answer = solve_with_fallbacks(img_bytes)
                    
                    solve_resp = requests.post(
                        f"{self.API_URL}/api/solve",
                        json={"session_id": session_id, "answer": answer},
                        timeout=30
                    )
                    if solve_resp.status_code == 200:
                        solve_data = solve_resp.json()
                        if solve_data.get("ok"):
                            run_resp = requests.post(
                                f"{self.API_URL}/api/run",
                                json={"session_id": session_id, "service": service.capitalize(), "url": url},
                                timeout=60
                            )
                            if run_resp.status_code == 200:
                                result = run_resp.json()
                                if result.get("ok"):
                                    amount = result.get("amount", 0)
                                    db.increment_daily(user_id)
                                    total = db.get(user_id).get("total_usage", 0)
                                    msg = (
                                        f"✅ <b>Buff thành công!</b>\n\n"
                                        f"📊 +{amount} {service}\n"
                                        f"📅 Hôm nay: {db.get_daily_usage(user_id)}/15\n"
                                        f"📈 Tổng: {total}\n"
                                        f"🔗 {url}"
                                    )
                                    self.send_message(chat_id, msg)
                                else:
                                    cooldown = result.get("cooldown")
                                    if cooldown:
                                        self.send_message(chat_id, f"⏳ Cooldown {cooldown}s")
                                    else:
                                        self.send_message(chat_id, f"❌ {result.get('message', 'Lỗi')}")
                            else:
                                self.send_message(chat_id, "❌ Lỗi khi buff")
                            return
                except Exception as e:
                    print(f"OCR error: {e}")
                    pass
                
                # Send captcha to user
                self.send_photo(
                    chat_id,
                    f"data:image/png;base64,{captcha_b64}",
                    f"🔐 Nhập captcha này:\nGửi /captcha <mã> để tiếp tục"
                )
                self.pending_sessions[user_id] = {
                    "session_id": session_id,
                    "service": service,
                    "url": url
                }
                return
            
            self.send_message(chat_id, "❌ Không lấy được captcha")
        except Exception as e:
            self.send_message(chat_id, f"❌ Lỗi: {str(e)}")
    
    def run(self):
        self.running = True
        print(f"🤖 Bot started! Channel: {self.channel_link}")
        print(f"👑 Admins: {ADMIN_IDS}")
        print(f"🔗 API: {self.API_URL}")
        
        while self.running:
            try:
                data = {"offset": self.update_id, "timeout": 30}
                resp = self._request("getUpdates", data)
                
                if resp.get("ok"):
                    for update in resp.get("result", []):
                        self.update_id = update["update_id"] + 1
                        self.process_update(update)
                else:
                    time.sleep(5)
            except Exception as e:
                print(f"Bot error: {e}")
                time.sleep(5)
    
    def stop(self):
        self.running = False

# Start bot instance
_bot_instance = None

def get_bot():
    global _bot_instance
    if _bot_instance is None and TELEGRAM_BOT_TOKEN:
        _bot_instance = ZefoyTelegramBot(TELEGRAM_BOT_TOKEN)
    return _bot_instance

# ============== SESSION STORE ==============
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
        "cooldown_until": 0,
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
    
    resp = session.get(f"{st['base_url']}/", timeout=30)
    resp.raise_for_status()
    
    zf = hashlib.md5(str(int(time.time() * 1000)).encode()).hexdigest()
    session.cookies.set("zf", zf, path="/")
    session.cookies.set("za", "200", path="/")
    
    st["initialized"] = True

def _get_captcha_image(st: dict[str, Any]) -> bytes:
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
    
    encoded = None
    key = hashlib.md5(user_agent.encode()).hexdigest()
    if key in data:
        encoded = data[key]
    elif len(data) == 1:
        encoded = next(iter(data.values()))
    else:
        raise Exception(f"Payload key {key} not found")
    
    once = base64.b64decode(encoded)
    twice = base64.b64decode(once)
    image_path = twice.decode('utf-8').strip()
    
    if not image_path.startswith("/"):
        image_path = "/" + image_path
    
    url = f"{base_url}{image_path}"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    
    if not resp.content:
        raise Exception("Empty image response")
    
    st["captcha_encoded"] = encoded
    
    return resp.content

def _build_captcha_encoded(st: dict[str, Any]) -> str:
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
    session = st["session"]
    base_url = st["base_url"]
    
    resp = session.get(f"{base_url}/", timeout=30)
    html = resp.text or ""
    
    soup = BeautifulSoup(html, 'html.parser')
    services = []
    service_map = {}
    
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
    session = st["session"]
    base_url = st["base_url"]
    service_map = st.get("service_map", {})
    
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

class TelegramConfigReq(BaseModel):
    bot_token: str
    channel_link: str
    admin_ids: str

# ============== HTML ==============
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Zefoy Buff Panel Pro</title>
<style>
:root{--bg:#0a0a1a;--card:#12122a;--fg:#e8ecff;--mut:#9aa3c7;--pri:#6c8cff;--ok:#37d67a;--err:#ff5c7a;--bd:#2a2f4f;--gold:#ffd700}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
.wrap{max-width:840px;margin:24px auto;padding:0 16px}
h1{font-size:22px;margin:0 0 16px;background:linear-gradient(135deg,#6c8cff,#ff6b6b);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
h2{font-size:15px;margin:0 0 10px;color:var(--pri)}
.card{background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:20px;margin-bottom:14px;transition:all .3s}
.card:hover{border-color:var(--pri)}
.btn{background:var(--pri);color:#fff;border:0;padding:10px 18px;border-radius:10px;cursor:pointer;font-weight:600;transition:all .2s}
.btn:hover{transform:translateY(-2px);box-shadow:0 4px 20px rgba(108,140,255,.3)}
.btn.ghost{background:transparent;border:1px solid var(--bd);color:var(--fg)}
.btn.ghost:hover{background:var(--bd)}
.btn.ok{background:var(--ok)}
.btn.ok:hover{box-shadow:0 4px 20px rgba(55,214,122,.3)}
.btn.gold{background:var(--gold);color:#000}
.btn.gold:hover{box-shadow:0 4px 20px rgba(255,215,0,.4)}
.btn.danger{background:var(--err)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none!important}
input,select{background:#0f1220;color:var(--fg);border:1px solid var(--bd);padding:10px 14px;border-radius:10px;width:100%;font-size:14px;transition:border .3s}
input:focus,select:focus{outline:none;border-color:var(--pri)}
.row{display:flex;gap:8px;margin:8px 0}.row>*{flex:1}
.captcha{background:#fff;padding:10px;border-radius:12px;display:inline-block}
.captcha img{display:block;max-width:220px;border-radius:6px}
.mut{color:var(--mut);font-size:13px}.hidden{display:none}
.stat{display:inline-block;background:#0f1220;border:1px solid var(--bd);padding:10px 16px;border-radius:10px;margin:4px 6px 0 0}
.stat b{color:var(--pri)}
.stat.gold b{color:var(--gold)}
#log{max-height:260px;overflow:auto;font-size:12px;background:#0a0a1a;padding:10px;border-radius:10px;border:1px solid var(--bd);white-space:pre-wrap;font-family:monospace}
#log .err{color:var(--err)}#log .ok{color:var(--ok)}#log .info{color:var(--mut)}#log .gold{color:var(--gold)}
.telegram-card{background:linear-gradient(135deg,#1a2a4a,#0a1a3a);border:2px solid #0088cc}
.telegram-card h2{color:#0088cc}
.status-badge{display:inline-block;padding:3px 12px;border-radius:20px;font-size:12px;font-weight:600}
.status-badge.on{background:#37d67a20;color:#37d67a;border:1px solid #37d67a}
.status-badge.off{background:#ff5c7a20;color:#ff5c7a;border:1px solid #ff5c7a}
.admin-panel{background:#1a0a2a;border:1px solid #6c3cff}
.admin-panel h3{color:#9b6cff;margin:0 0 10px}
@media(max-width:600px){.row{flex-direction:column}.stat{display:block;margin:4px 0}}
</style>
</head>
<body>
<div class="wrap">
<h1>⚡ Zefoy Buff Panel Pro</h1>

<!-- Telegram Card -->
<div class="card telegram-card">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <h2>🤖 Telegram Bot</h2>
    <span class="status-badge" id="botStatus">● Đang tải...</span>
  </div>
  <div class="row" style="margin-top:10px">
    <input id="botToken" placeholder="Bot Token (lấy từ @BotFather)" />
    <input id="channelLink" placeholder="Channel Link (vd: https://t.me/your_channel)" />
  </div>
  <div class="row">
    <input id="adminIds" placeholder="Admin IDs (vd: 123456789,987654321)" />
    <button class="btn gold" onclick="saveBotConfig()">💾 Lưu cấu hình</button>
  </div>
  <div class="mut" style="margin-top:8px">
    📌 Bot sẽ check user đã join channel chưa. Mỗi ngày 15 lượt buff.
    <br/>🔑 Lấy Bot Token từ <a href="https://t.me/BotFather" target="_blank" style="color:#6c8cff">@BotFather</a>
    <br/>📌 Cần set API_URL trong environment: <code>https://your-app.onrender.com</code>
  </div>
</div>

<!-- Admin Panel -->
<div class="card admin-panel hidden" id="adminPanel">
  <h3>🔐 Admin Panel</h3>
  <div class="row">
    <input id="adminBroadcast" placeholder="Tin nhắn broadcast..." />
    <button class="btn" onclick="sendBroadcast()">📢 Gửi broadcast</button>
  </div>
  <div class="row">
    <input id="adminResetUser" placeholder="User ID cần reset" />
    <button class="btn danger" onclick="resetUser()">🔄 Reset user</button>
  </div>
  <div class="mut" style="margin-top:8px">📊 <span id="adminStats">Đang tải...</span></div>
</div>

<!-- Captcha -->
<div class="card">
  <h2>1. 🔐 Lấy captcha</h2>
  <button class="btn" id="btnStart">▶ Bắt đầu / Lấy captcha</button>
  <div id="capBox" class="hidden" style="margin-top:12px">
    <div class="captcha"><img id="capImg" alt="captcha"/></div>
    <button class="btn ghost" id="btnRefresh">🔄 Ảnh khác</button>
    <div class="row"><input id="capAns" placeholder="Nhập chữ (chỉ chữ cái)" autocomplete="off"/><button class="btn ok" id="btnSolve">✔ Gửi</button></div>
    <div class="mut">session: <code id="sid"></code></div>
  </div>
</div>

<!-- Services -->
<div class="card hidden" id="svcCard">
  <h2>2. 📋 Chọn service & link</h2>
  <div class="row"><select id="svc"></select><button class="btn ghost" id="btnReload">↻</button></div>
  <input id="vurl" placeholder="https://www.tiktok.com/@user/video/..."/>
  <div class="row"><button class="btn" id="btnRun">🚀 Buff</button><label style="display:flex;align-items:center;gap:6px;padding-left:8px"><input type="checkbox" id="loop"/>Lặp</label></div>
</div>

<!-- Stats -->
<div class="card hidden" id="statCard">
  <h2>3. 📊 Kết quả</h2>
  <div>
    <span class="stat">Tổng: <b id="tot">0</b></span>
    <span class="stat">Lượt gần nhất: <b id="lst">–</b></span>
    <span class="stat gold">Cooldown: <b id="cd">–</b></span>
  </div>
  <div id="log" style="margin-top:10px"></div>
</div>
</div>

<script>
// ============== MAIN ==============
const API = location.origin;
let SID = null;
let cooldownInterval = null;

function log(m, cls) {
  const d = document.createElement('div');
  if (cls) d.className = cls;
  d.textContent = '[' + new Date().toLocaleTimeString() + '] ' + m;
  document.getElementById('log').prepend(d);
  while (document.getElementById('log').children.length > 100) {
    document.getElementById('log').removeChild(document.getElementById('log').lastChild);
  }
}

async function call(path, body) {
  const r = await fetch(API + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})
  });
  let j;
  try { j = await r.json(); } catch(e) {
    throw new Error('Server trả về không phải JSON (HTTP ' + r.status + ')');
  }
  if (!r.ok) throw new Error(j.message || j.error || ('HTTP ' + r.status));
  return j;
}

function showCap(b64) {
  document.getElementById('capBox').classList.remove('hidden');
  document.getElementById('capImg').src = 'data:image/png;base64,' + b64;
}

function renderSvc(list) {
  const sel = document.getElementById('svc');
  sel.innerHTML = '';
  list.forEach(s => {
    const o = document.createElement('option');
    o.value = s.name;
    o.textContent = (s.available ? '🟢 ' : '🔴 ') + s.name + ' — ' + s.status;
    if (!s.available || !s.has_action) o.disabled = true;
    sel.appendChild(o);
  });
  document.getElementById('svcCard').classList.remove('hidden');
  document.getElementById('statCard').classList.remove('hidden');
}

function updateCooldown(seconds) {
  const cdEl = document.getElementById('cd');
  if (cooldownInterval) { clearInterval(cooldownInterval); cooldownInterval = null; }
  if (!seconds || seconds <= 0) { cdEl.textContent = '–'; return; }
  let remaining = seconds;
  cdEl.textContent = remaining + 's';
  cooldownInterval = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      cdEl.textContent = '–';
      clearInterval(cooldownInterval);
      cooldownInterval = null;
    } else {
      cdEl.textContent = remaining + 's';
    }
  }, 1000);
}

// ============== BUTTONS ==============
document.getElementById('btnStart').onclick = async () => {
  try {
    log('Đang lấy captcha...', 'info');
    const j = await call('/api/start');
    SID = j.session_id;
    document.getElementById('sid').textContent = SID.slice(0, 8);
    showCap(j.captcha_b64);
    log('OK — nhập captcha', 'ok');
  } catch(e) {
    log('❌ ' + e.message, 'err');
  }
};

document.getElementById('btnRefresh').onclick = async () => {
  try {
    const j = await call('/api/refresh_captcha', {session_id: SID});
    showCap(j.captcha_b64);
    log('🔄 Đã refresh captcha', 'info');
  } catch(e) {
    log('❌ ' + e.message, 'err');
  }
};

document.getElementById('btnSolve').onclick = async () => {
  const a = document.getElementById('capAns').value.trim();
  if (!a) return;
  try {
    const j = await call('/api/solve', {session_id: SID, answer: a});
    if (!j.ok) {
      log('❌ Captcha sai, thử lại', 'err');
      if (j.captcha_b64) showCap(j.captcha_b64);
      return;
    }
    log('✅ Captcha OK', 'ok');
    renderSvc(j.services);
  } catch(e) {
    log('❌ ' + e.message, 'err');
  }
};

document.getElementById('btnReload').onclick = async () => {
  try {
    const j = await call('/api/services', {session_id: SID});
    renderSvc(j.services);
    document.getElementById('tot').textContent = j.total_sent || 0;
    log('🔄 Đã reload services', 'info');
  } catch(e) {
    log('❌ ' + e.message, 'err');
  }
};

async function runOnce() {
  const svc = document.getElementById('svc').value;
  const url = document.getElementById('vurl').value.trim();
  if (!url) { log('❌ Thiếu link', 'err'); return; }
  try {
    const j = await call('/api/run', {session_id: SID, service: svc, url: url});
    if (j.cooldown) {
      updateCooldown(j.cooldown);
      log('⏳ Cooldown ' + j.cooldown + 's', 'err');
    }
    if (j.amount) {
      document.getElementById('lst').textContent = j.amount + ' ' + (j.kind || '');
      document.getElementById('tot').textContent = j.total_sent || '0';
      log('✅ +' + j.amount + ' ' + (j.kind || ''), 'ok');
    } else if (j.message) {
      log('ℹ️ ' + j.message, 'info');
    }
  } catch(e) {
    log('❌ ' + e.message, 'err');
  }
}

document.getElementById('btnRun').onclick = async () => {
  await runOnce();
  if (document.getElementById('loop').checked) {
    const t = setInterval(async () => {
      if (!document.getElementById('loop').checked) { clearInterval(t); return; }
      await runOnce();
    }, 15000);
  }
};

// ============== TELEGRAM BOT ==============
async function saveBotConfig() {
  const token = document.getElementById('botToken').value.trim();
  const channel = document.getElementById('channelLink').value.trim();
  const admins = document.getElementById('adminIds').value.trim();
  
  if (!token) { log('❌ Vui lòng nhập Bot Token!', 'err'); return; }
  if (!channel) { log('❌ Vui lòng nhập Channel Link!', 'err'); return; }
  
  try {
    const r = await fetch('/api/telegram/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ bot_token: token, channel_link: channel, admin_ids: admins })
    });
    const j = await r.json();
    if (j.ok) {
      log('✅ Đã lưu cấu hình bot!', 'ok');
      document.getElementById('botStatus').textContent = '● Online';
      document.getElementById('botStatus').className = 'status-badge on';
      checkAdmin();
    } else {
      log('❌ Lỗi lưu config: ' + (j.message || ''), 'err');
    }
  } catch(e) {
    log('❌ ' + e.message, 'err');
  }
}

async function checkAdmin() {
  const adminIds = document.getElementById('adminIds').value;
  if (!adminIds) return;
  const admins = adminIds.split(',').map(id => id.trim()).filter(id => id);
  if (admins.length > 0) {
    document.getElementById('adminPanel').classList.remove('hidden');
    loadAdminStats();
  }
}

async function loadAdminStats() {
  try {
    const adminId = document.getElementById('adminIds').value.split(',')[0] || '0';
    const r = await fetch('/api/telegram/stats?admin_id=' + adminId);
    const j = await r.json();
    if (j.total_users !== undefined) {
      document.getElementById('adminStats').textContent = 
        '👥 ' + j.total_users + ' users | 📈 ' + j.total_usage + ' total | 📅 ' + j.today_usage + ' today';
    }
  } catch(e) {
    document.getElementById('adminStats').textContent = 'Lỗi tải stats';
  }
}

async function sendBroadcast() {
  const msg = document.getElementById('adminBroadcast').value.trim();
  if (!msg) { log('❌ Nhập nội dung broadcast!', 'err'); return; }
  try {
    const r = await fetch('/api/telegram/broadcast', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ admin_id: document.getElementById('adminIds').value.split(',')[0] || '0', message: msg })
    });
    const j = await r.json();
    if (j.ok) {
      log('📢 Đã gửi broadcast tới ' + (j.sent || 0) + ' users', 'ok');
      document.getElementById('adminBroadcast').value = '';
    } else {
      log('❌ Lỗi gửi broadcast: ' + (j.message || ''), 'err');
    }
  } catch(e) {
    log('❌ ' + e.message, 'err');
  }
}

async function resetUser() {
  const userId = document.getElementById('adminResetUser').value.trim();
  if (!userId) { log('❌ Nhập User ID!', 'err'); return; }
  try {
    const r = await fetch('/api/telegram/reset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ admin_id: document.getElementById('adminIds').value.split(',')[0] || '0', user_id: userId })
    });
    const j = await r.json();
    if (j.ok) {
      log('✅ Đã reset user ' + userId, 'ok');
      document.getElementById('adminResetUser').value = '';
      loadAdminStats();
    } else {
      log('❌ Lỗi reset: ' + (j.message || ''), 'err');
    }
  } catch(e) {
    log('❌ ' + e.message, 'err');
  }
}

async function loadTelegramConfig() {
  try {
    const r = await fetch('/api/telegram/config');
    const j = await r.json();
    if (j.bot_token) {
      document.getElementById('botToken').value = j.bot_token;
      document.getElementById('channelLink').value = j.channel_link || '';
      document.getElementById('adminIds').value = j.admin_ids || '';
      if (j.bot_token && j.bot_token !== 'YOUR_BOT_TOKEN_HERE') {
        document.getElementById('botStatus').textContent = '● Online';
        document.getElementById('botStatus').className = 'status-badge on';
        checkAdmin();
      } else {
        document.getElementById('botStatus').textContent = '● Offline';
        document.getElementById('botStatus').className = 'status-badge off';
      }
    }
  } catch(e) {}
}

// Load khi trang load
document.addEventListener('DOMContentLoaded', loadTelegramConfig);

// Auto refresh cooldown display
setInterval(() => {
  const cdEl = document.getElementById('cd');
  if (cdEl.textContent !== '–' && cdEl.textContent !== '') {
    const match = cdEl.textContent.match(/(\\d+)/);
    if (match) {
      const val = parseInt(match[1]);
      if (val > 0) {
        // Don't auto-decrement here, let updateCooldown handle it
      }
    }
  }
}, 1000);
</script>
</body>
</html>
"""

# ============== ROUTES ==============

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
async def root():
    return HTMLResponse(HTML_TEMPLATE)

@app.get("/api")
def api_info():
    return {
        "endpoints": [
            "/api/start",
            "/api/solve",
            "/api/services",
            "/api/run",
            "/api/refresh_captcha",
            "/api/telegram/config",
            "/api/telegram/stats",
            "/api/telegram/broadcast",
            "/api/telegram/reset"
        ],
        "sessions_active": len(SESSIONS),
        "version": "3.0.0",
        "telegram_bot": bool(TELEGRAM_BOT_TOKEN)
    }

@app.get("/health")
def health():
    return {"ok": True, "sessions": len(SESSIONS)}

@app.post("/api/start")
def start(_: StartReq = StartReq()):
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

# ============== TELEGRAM ROUTES ==============

@app.post("/api/telegram/config")
def telegram_config(req: TelegramConfigReq):
    """Cập nhật config bot Telegram"""
    config = {
        "bot_token": req.bot_token,
        "channel_link": req.channel_link,
        "admin_ids": req.admin_ids
    }
    with open(TELECONFIG_FILE, "w") as f:
        json.dump(config, f)
    
    os.environ["TELEGRAM_BOT_TOKEN"] = req.bot_token
    os.environ["TELEGRAM_CHANNEL_LINK"] = req.channel_link
    os.environ["ADMIN_IDS"] = req.admin_ids
    
    return {"ok": True, "message": "Đã lưu cấu hình bot"}

@app.get("/api/telegram/config")
def get_telegram_config():
    if os.path.exists(TELECONFIG_FILE):
        with open(TELECONFIG_FILE, "r") as f:
            return json.load(f)
    return {
        "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "channel_link": os.environ.get("TELEGRAM_CHANNEL_LINK", ""),
        "admin_ids": os.environ.get("ADMIN_IDS", "")
    }

@app.get("/api/telegram/stats")
def telegram_stats(admin_id: str):
    admin_ids = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]
    if int(admin_id) not in admin_ids:
        raise HTTPException(403, "Không phải admin")
    
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            total_users = len(data)
            total_usage = sum(u.get("total_usage", 0) for u in data.values())
            today = datetime.now().strftime("%Y-%m-%d")
            today_usage = sum(1 for u in data.values() if u.get("last_date") == today)
            return {
                "total_users": total_users,
                "total_usage": total_usage,
                "today_usage": today_usage
            }
    return {"total_users": 0, "total_usage": 0, "today_usage": 0}

@app.post("/api/telegram/broadcast")
def telegram_broadcast(admin_id: str, message: str):
    admin_ids = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]
    if int(admin_id) not in admin_ids:
        raise HTTPException(403, "Không phải admin")
    
    bot = get_bot()
    if not bot:
        return {"ok": False, "message": "Bot chưa được khởi tạo"}
    
    sent = bot.broadcast(message)
    return {"ok": True, "sent": sent}

@app.post("/api/telegram/reset")
def telegram_reset(admin_id: str, user_id: str):
    admin_ids = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "").split(",") if id.strip()]
    if int(admin_id) not in admin_ids:
        raise HTTPException(403, "Không phải admin")
    
    user_data = db.get(user_id)
    if user_data:
        user_data["daily_usage"] = 0
        user_data["last_date"] = ""
        db.update(user_id, user_data)
        return {"ok": True, "message": f"Đã reset user {user_id}"}
    return {"ok": False, "message": f"Không tìm thấy user {user_id}"}

# ============== START BOT THREAD ==============
def start_bot_thread():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token and token != "YOUR_BOT_TOKEN_HERE":
        try:
            bot = ZefoyTelegramBot(token)
            bot.run()
        except Exception as e:
            print(f"Bot thread error: {e}")

# Start bot in background if running standalone
if __name__ == "__main__":
    bot_thread = threading.Thread(target=start_bot_thread, daemon=True)
    bot_thread.start()
    
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
