import subprocess
import sys

# Install dependencies
subprocess.check_call([sys.executable, "-m", "pip", "install", 
    "httpx==0.27.0", "schedule==1.2.2", "pytz==2024.1"])

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

schedule.every().day.at("05:00").do(job)

print(f"✅ Scheduler running. Athens: {datetime.now(ATHENS_TZ).strftime('%H:%M')}")

if os.getenv("RUN_ON_START", "false").lower() == "true":
    print("🔄 Running now...")
    job()

while True:
    schedule.run_pending()
    time.sleep(30)
