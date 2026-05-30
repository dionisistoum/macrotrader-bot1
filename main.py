import asyncio
import schedule
import time
import os
from datetime import datetime
import pytz
from src.bot import run_daily_briefing

ATHENS_TZ = pytz.timezone("Europe/Athens")

def job():
    print(f"🚀 {datetime.now(ATHENS_TZ).strftime('%H:%M')} — Running briefing...")
    asyncio.run(run_daily_briefing())

# 08:00 Athens = 05:00 UTC (EEST καλοκαίρι)
schedule.every().day.at("05:00").do(job)

print(f"✅ Scheduler running. Athens: {datetime.now(ATHENS_TZ).strftime('%H:%M')}")

if os.getenv("RUN_ON_START", "false").lower() == "true":
    print("🔄 Running now (RUN_ON_START=true)...")
    job()

while True:
    schedule.run_pending()
    time.sleep(30)
