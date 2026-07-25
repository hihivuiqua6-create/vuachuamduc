"""
Telegram Bot for Zefoy Buff - Standalone
Chạy trên Render Worker
"""

import os
import re
import time
import json
import threading
import requests
from datetime import datetime
from typing import Optional

# ============== LẤY CONFIG TỪ ENVIRONMENT ==============
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8122755073:AAHrE1SxUJbG4-K55tw8f_yHH1DBDp2N-xg")
API_URL = os.environ.get("API_URL", "https://vuachuamduc.onrender.com")
CHANNEL_LINK = os.environ.get("TELEGRAM_CHANNEL_LINK", "https://t.me/+uH22KBhxe51jYjM1")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_IDS", "6214458926").split(",") if id.strip()]

# Database
DB_FILE = "telegram_users.json"

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
        self.channel_link = CHANNEL_LINK
        self.channel_username = self._extract_channel_username()
        self.running = False
        self.update_id = 0
        self.pending_sessions = {}
        self.API_URL = API_URL
        self.ADMIN_IDS = ADMIN_IDS
    
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
        except Exception as e:
            print(f"Check member error: {e}")
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
        
        print(f"📩 Received: {text[:50]} from @{username}")
        
        # Check channel membership (bỏ qua admin)
        if int(user_id) not in self.ADMIN_IDS and not self.is_member(chat_id):
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
                f"<b>Dịch vụ:</b> hearts, views, followers, shares\n"
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
        else:
            self.send_message(chat_id, f"❌ Lệnh không hợp lệ. Gửi /help")
    
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
                self.send_message(chat_id, f"❌ Lỗi kết nối server: {start_resp.status_code}")
                return
            
            session_data = start_resp.json()
            session_id = session_data.get("session_id")
            captcha_b64 = session_data.get("captcha_b64")
            
            if captcha_b64:
                # Gửi captcha cho user
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
        """Main loop - get updates"""
        self.running = True
        print(f"🤖 Bot started!")
        print(f"📢 Channel: {self.channel_link}")
        print(f"👑 Admins: {self.ADMIN_IDS}")
        print(f"🔗 API: {self.API_URL}")
        print(f"✅ Bot is running...")
        
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
                print(f"❌ Bot error: {e}")
                time.sleep(5)
    
    def stop(self):
        self.running = False

# ============== MAIN ==============
if __name__ == "__main__":
    print("=" * 50)
    print("🤖 Zefoy Telegram Bot")
    print("=" * 50)
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Vui lòng set TELEGRAM_BOT_TOKEN trong environment!")
        exit(1)
    
    bot = ZefoyTelegramBot(BOT_TOKEN)
    bot.run()
