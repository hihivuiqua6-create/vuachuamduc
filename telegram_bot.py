"""
Telegram Bot for Zefoy Buff - Render Worker (FIXED)
"""

import os
import re
import time
import json
import requests
from datetime import datetime

# ============== CONFIG MỚI ==============
BOT_TOKEN = "8704711376:AAHkrYeCYUoZkmSDHC5UjLHtJAc5XGC_ae4"
API_URL = "https://vuachuamduc.onrender.com"
CHANNEL_LINK = "https://t.me/auzachannel"
ADMIN_IDS = [8030294480]

DB_FILE = "telegram_users.json"

# ============== DATABASE ==============
class UserDB:
    def __init__(self):
        self.data = self._load()
    
    def _load(self) -> dict:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save(self):
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
        self.update(user_id, user)
        return user["daily_usage"]
    
    def is_admin(self, user_id: str) -> bool:
        return int(user_id) in ADMIN_IDS

db = UserDB()

# ============== TELEGRAM BOT ==============
class ZefoyTelegramBot:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
        self.channel_username = CHANNEL_LINK.replace("https://t.me/", "").strip()
        self.offset = 0
        self.pending = {}
    
    def _request(self, method: str, data: dict = None) -> dict:
        try:
            url = f"{self.base_url}/{method}"
            resp = requests.post(url, json=data, timeout=30)
            return resp.json()
        except Exception as e:
            print(f"❌ API Error: {e}")
            return {"ok": False}
    
    def send_message(self, chat_id: int, text: str) -> bool:
        try:
            result = self._request("sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            })
            return result.get("ok", False)
        except Exception as e:
            print(f"❌ Send error: {e}")
            return False
    
    def send_photo(self, chat_id: int, photo_base64: str, caption: str = ""):
        try:
            self._request("sendPhoto", {
                "chat_id": chat_id,
                "photo": f"data:image/png;base64,{photo_base64}",
                "caption": caption
            })
        except Exception as e:
            print(f"❌ Photo error: {e}")
    
    def is_member(self, user_id: int) -> bool:
        try:
            result = self._request("getChatMember", {
                "chat_id": f"@{self.channel_username}",
                "user_id": user_id
            })
            if result.get("ok"):
                status = result.get("result", {}).get("status", "")
                return status in ["member", "administrator", "creator"]
            return False
        except:
            return False
    
    def process(self, update: dict):
        if "message" not in update:
            return
        
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = str(msg["from"]["id"])
        username = msg["from"].get("username", "unknown")
        text = msg.get("text", "")
        
        print(f"📩 {text[:50]} from @{username} (ID: {user_id})")
        
        # Admin không cần check channel
        if int(user_id) not in ADMIN_IDS and not self.is_member(chat_id):
            self.send_message(chat_id, f"❌ Cần tham gia kênh {CHANNEL_LINK} để dùng bot!")
            return
        
        if text.startswith("/"):
            self._cmd(chat_id, user_id, username, text)
        else:
            self._buff(chat_id, user_id, username, text)
    
    def _cmd(self, chat_id: int, user_id: str, username: str, text: str):
        cmd = text.split()[0].lower()
        
        if cmd == "/start":
            daily = db.get_daily_usage(user_id)
            total = db.get(user_id).get("total_usage", 0)
            msg = f"""
🤖 <b>Zefoy Buff Bot</b>

👤 @{username}
📊 Hôm nay: {daily}/15
📈 Tổng: {total}

<b>Cách dùng:</b>
Gửi link TikTok + dịch vụ
Ví dụ: <code>https://tiktok.com/... hearts</code>

<b>Dịch vụ:</b> hearts, views, followers, shares
📌 Cần tham gia {CHANNEL_LINK} để dùng bot!
"""
            self.send_message(chat_id, msg)
        
        elif cmd == "/help":
            msg = """
📖 <b>Hướng dẫn</b>

/start - Xem thông tin
/help - Hướng dẫn này
/stats - Thống kê (admin)
/broadcast - Gửi tin (admin)
/reset - Reset user (admin)

<b>Buff:</b>
<code>https://tiktok.com/... hearts</code>
"""
            self.send_message(chat_id, msg)
        
        elif cmd == "/stats" and db.is_admin(user_id):
            total_users = len(db.data)
            total_usage = sum(u.get("total_usage", 0) for u in db.data.values())
            msg = f"""
📊 <b>Bot Stats</b>

👥 Users: {total_users}
📈 Total buffs: {total_usage}
🟢 Status: Online
"""
            self.send_message(chat_id, msg)
        
        elif cmd == "/broadcast" and db.is_admin(user_id):
            if len(text.split()) > 1:
                msg = text.split(" ", 1)[1]
                sent = 0
                for uid in db.data.keys():
                    try:
                        if self.send_message(int(uid), f"📢 {msg}"):
                            sent += 1
                        time.sleep(0.1)
                    except:
                        pass
                self.send_message(chat_id, f"✅ Đã gửi tới {sent} users")
            else:
                self.send_message(chat_id, "⚠️ /broadcast <nội dung>")
        
        elif cmd == "/reset" and db.is_admin(user_id):
            parts = text.split()
            if len(parts) == 2:
                target = parts[1]
                u = db.get(target)
                if u:
                    u["daily_usage"] = 0
                    u["last_date"] = ""
                    db.update(target, u)
                    self.send_message(chat_id, f"✅ Đã reset user {target}")
                else:
                    self.send_message(chat_id, f"❌ Không tìm thấy user {target}")
            else:
                self.send_message(chat_id, "⚠️ /reset <user_id>")
        
        elif cmd == "/captcha":
            self._captcha(chat_id, user_id, text)
        else:
            self.send_message(chat_id, "❌ Lệnh không hợp lệ. /help")
    
    def _captcha(self, chat_id: int, user_id: str, text: str):
        parts = text.split()
        if len(parts) < 2:
            self.send_message(chat_id, "⚠️ /captcha <mã>")
            return
        
        answer = parts[1]
        pending = self.pending.get(user_id)
        if not pending:
            self.send_message(chat_id, "❌ Không có session đang chờ")
            return
        
        try:
            solve = requests.post(
                f"{API_URL}/api/solve",
                json={"session_id": pending["session_id"], "answer": answer},
                timeout=30
            )
            if solve.status_code != 200:
                self.send_message(chat_id, "❌ Lỗi gửi captcha")
                return
            
            data = solve.json()
            if not data.get("ok"):
                self.send_message(chat_id, "❌ Captcha sai, thử lại!")
                return
            
            run = requests.post(
                f"{API_URL}/api/run",
                json={
                    "session_id": pending["session_id"],
                    "service": pending["service"].capitalize(),
                    "url": pending["url"]
                },
                timeout=60
            )
            if run.status_code == 200:
                result = run.json()
                if result.get("ok"):
                    amount = result.get("amount", 0)
                    db.increment_daily(user_id)
                    total = db.get(user_id).get("total_usage", 0)
                    msg = f"""
✅ <b>Buff thành công!</b>

📊 +{amount} {pending['service']}
📅 Hôm nay: {db.get_daily_usage(user_id)}/15
📈 Tổng: {total}
🔗 {pending['url']}
"""
                    self.send_message(chat_id, msg)
                    del self.pending[user_id]
                else:
                    self.send_message(chat_id, f"❌ {result.get('message', 'Lỗi')}")
            else:
                self.send_message(chat_id, "❌ Lỗi khi buff")
        except Exception as e:
            self.send_message(chat_id, f"❌ Lỗi: {str(e)}")
    
    def _buff(self, chat_id: int, user_id: str, username: str, text: str):
        daily = db.get_daily_usage(user_id)
        if daily >= 15:
            self.send_message(chat_id, f"❌ Hết 15 lượt hôm nay! {daily}/15")
            return
        
        services = ["hearts", "views", "followers", "shares", "comments"]
        service = None
        for s in services:
            if s in text.lower():
                service = s
                break
        
        if not service:
            self.send_message(chat_id, f"❌ Dịch vụ: {', '.join(services)}\nVí dụ: https://tiktok.com/... hearts")
            return
        
        url_match = re.search(r"https?://[^\s]+", text)
        if not url_match:
            self.send_message(chat_id, "❌ Không tìm thấy link TikTok")
            return
        
        url = url_match.group(0)
        self.send_message(chat_id, f"⏳ Đang buff {service}...")
        
        try:
            start = requests.post(f"{API_URL}/api/start", json={}, timeout=30)
            if start.status_code != 200:
                self.send_message(chat_id, f"❌ Lỗi server: {start.status_code}")
                return
            
            data = start.json()
            session_id = data.get("session_id")
            captcha_b64 = data.get("captcha_b64")
            
            if captcha_b64:
                self.send_photo(chat_id, captcha_b64, f"🔐 Nhập captcha cho {service}")
                self.send_message(chat_id, "📝 Gửi /captcha <mã> để tiếp tục")
                
                self.pending[user_id] = {
                    "session_id": session_id,
                    "service": service,
                    "url": url
                }
                return
            
            self.send_message(chat_id, "❌ Không lấy được captcha")
        except Exception as e:
            self.send_message(chat_id, f"❌ Lỗi: {str(e)}")
    
    def run(self):
        print("=" * 50)
        print("🤖 Zefoy Telegram Bot")
        print("=" * 50)
        print(f"📢 Channel: {CHANNEL_LINK}")
        print(f"👑 Admins: {ADMIN_IDS}")
        print(f"🔗 API: {API_URL}")
        print("✅ Bot is running...")
        print("=" * 50)
        print("⏳ Waiting for messages...")
        
        while True:
            try:
                resp = self._request("getUpdates", {
                    "offset": self.offset,
                    "timeout": 30,
                    "allowed_updates": ["message"]
                })
                
                if resp.get("ok"):
                    for update in resp.get("result", []):
                        self.offset = update["update_id"] + 1
                        self.process(update)
                else:
                    print(f"⚠️ API error: {resp}")
                    time.sleep(5)
            except Exception as e:
                print(f"❌ Error: {e}")
                time.sleep(5)

# ============== MAIN ==============
if __name__ == "__main__":
    bot = ZefoyTelegramBot()
    bot.run()
