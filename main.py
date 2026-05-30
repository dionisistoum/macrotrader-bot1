import subprocess
import sys

subprocess.check_call([sys.executable, "-m", "pip", "install",
    "httpx==0.27.0", "schedule==1.2.2", "pytz==2024.1",
    "--root-user-action=ignore", "--quiet"])

import asyncio
import schedule
import time
import os
from datetime import datetime
import pytz
from src.bot import run_daily_briefing, check_price_alerts

ATHENS_TZ = pytz.timezone("Europe/Athens")

def morning_job():
    print(f"🌅 {datetime.now(ATHENS_TZ).strftime('%H:%M')} — Morning briefing...")
    asyncio.run(run_daily_briefing("morning"))

def afternoon_job():
    print(f"🌆 {datetime.now(ATHENS_TZ).strftime('%H:%M')} — Afternoon briefing...")
    asyncio.run(run_daily_briefing("afternoon"))

def alert_job():
    asyncio.run(check_price_alerts())

# 08:00 Athens = 05:00 UTC
schedule.every().day.at("05:00").do(morning_job)
# 15:30 Athens = 12:30 UTC
schedule.every().day.at("12:30").do(afternoon_job)
# Price alerts κάθε 15 λεπτά
schedule.every(15).minutes.do(alert_job)

print(f"✅ MacroTrader running. Athens: {datetime.now(ATHENS_TZ).strftime('%H:%M')}")
print("   🌅 Morning: 08:00 | 🌆 Afternoon: 15:30 | ⚡ Alerts: every 15min")

if os.getenv("RUN_ON_START", "false").lower() == "true":
    session = os.getenv("TEST_SESSION", "morning")
    print(f"🔄 Running {session} session now...")
    if session == "afternoon":
        afternoon_job()
    else:
        morning_job()

while True:
    schedule.run_pending()
    time.sleep(30)
