# worker.py
"""
Telegram Bot Worker cho Render
"""

import os
import sys
import time

# Import bot từ telegram_bot.py
try:
    from telegram_bot import ZefoyTelegramBot
except ImportError:
    print("❌ Không tìm thấy telegram_bot.py")
    sys.exit(1)

# Lấy token từ environment
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8122755073:AAHrE1SxUJbG4-K55tw8f_yHH1DBDp2N-xg")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("❌ Chưa set TELEGRAM_BOT_TOKEN trong environment!")
    sys.exit(1)

print("=" * 50)
print("🤖 Starting Telegram Bot Worker...")
print("=" * 50)

try:
    bot = ZefoyTelegramBot(BOT_TOKEN)
    bot.run()
except KeyboardInterrupt:
    print("\n🛑 Bot stopped")
except Exception as e:
    print(f"❌ Bot error: {e}")
    sys.exit(1)
