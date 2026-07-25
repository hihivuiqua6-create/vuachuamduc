# worker.py
"""
Telegram Bot Worker cho Render
"""

import os
import sys
import time

try:
    from telegram_bot import ZefoyTelegramBot
except ImportError as e:
    print(f"❌ Không tìm thấy telegram_bot.py: {e}")
    sys.exit(1)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8122755073:AAHrE1SxUJbG4-K55tw8f_yHH1DBDp2N-xg")

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
