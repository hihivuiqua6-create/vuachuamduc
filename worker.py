# worker.py
import os
import sys
from telegram_bot import ZefoyTelegramBot

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8704711376:AAHkrYeCYUoZkmSDHC5UjLHtJAc5XGC_ae4")

print("=" * 50)
print("🤖 Starting Telegram Bot Worker...")
print("=" * 50)

try:
    bot = ZefoyTelegramBot()
    bot.run()
except KeyboardInterrupt:
    print("\n🛑 Bot stopped")
except Exception as e:
    print(f"❌ Bot error: {e}")
    sys.exit(1)
