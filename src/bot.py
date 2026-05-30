import os
import asyncio
import httpx
from datetime import datetime, timedelta
import pytz

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_CHAT_ID")
FINNHUB_KEY     = os.getenv("FINNHUB_KEY")
TD_KEY          = os.getenv("TD_KEY")
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_KEY")

WATCHLIST = [
    {"sym": "XAUUSD", "name": "Gold",        "fh": None,   "td": "XAU/USD"},
    {"sym": "SPY",    "name": "S&P 500 ETF", "fh": "SPY",  "td": "SPY"},
    {"sym": "QQQ",    "name": "Nasdaq ETF",  "fh": "QQQ",  "td": "QQQ"},
    {"sym": "NVDA",   "name": "Nvidia",      "fh": "NVDA", "td": "NVDA"},
    {"sym": "GLD",    "name": "Gold ETF",    "fh": "GLD",  "td": "GLD"},
    {"sym": "TLT",    "name": "Bonds ETF",   "fh": "TLT",  "td": "TLT"},
    {"sym": "DXY",    "name": "US Dollar",   "fh": "UUP",  "td": "DX/Y"},
]

ATHENS_TZ = pytz.timezone("Europe/Athens")

# ─── PRICES ───────────────────────────────────────────────

async def fetch_finnhub_quote(client, symbol):
    try:
        r = await client.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": FINNHUB_KEY},
            timeout=10
        )
        d = r.json()
        if d.get("c", 0) > 0:
            return {"price": d["c"], "change": d["d"], "pct": d["dp"], "high": d["h"], "low": d["l"]}
    except Exception:
        pass
    return None

async def fetch_td_quote(client, symbol):
    try:
        r = await client.get(
            "https://api.twelvedata.com/price",
            params={"symbol": symbol, "apikey": TD_KEY},
            timeout=10
        )
        d = r.json()
        if d.get("price"):
            return {"price": float(d["price"]), "change": None, "pct": None}
    except Exception:
        pass
    return None

async def fetch_all_prices(client):
    tasks = []
    for asset in WATCHLIST:
        if asset["fh"]:
            tasks.append(fetch_finnhub_quote(client, asset["fh"]))
        else:
            tasks.append(fetch_td_quote(client, asset["td"]))
    results = await asyncio.gather(*tasks)
    prices = {}
    for i, asset in enumerate(WATCHLIST):
        prices[asset["sym"]] = results[i] if results[i] and results[i].get("price") else None
    return prices

# ─── NEWS ─────────────────────────────────────────────────

async def fetch_news(client):
    try:
        r = await client.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": FINNHUB_KEY},
            timeout=10
        )
        items = r.json()
        if isinstance(items, list):
            return [i.get("headline", "") for i in items[:6] if i.get("headline")]
    except Exception:
        pass
    return []

# ─── FEAR & GREED ─────────────────────────────────────────

async def fetch_fear_greed(client):
    try:
        r = await client.get(
            "https://api.alternative.me/fng/?limit=1",
            timeout=10
        )
        d = r.json()
        data = d["data"][0]
        score = int(data["value"])
        label = data["value_classification"]
        emoji = "🟢" if score < 30 else "🔴" if score > 70 else "🟡"
        return f"{emoji} {score}/100 — {label}"
    except Exception:
        pass
    return "N/A"

# ─── ECONOMIC CALENDAR ────────────────────────────────────

async def fetch_economic_calendar(client):
    try:
        today = datetime.now(ATHENS_TZ).strftime("%Y-%m-%d")
        week_end = (datetime.now(ATHENS_TZ) + timedelta(days=5)).strftime("%Y-%m-%d")
        r = await client.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": today, "to": week_end, "token": FINNHUB_KEY},
            timeout=10
        )
        d = r.json()
        events = d.get("economicCalendar", [])
        # Φιλτράρισε μόνο high impact
        high_impact = []
        keywords = ["NFP", "CPI", "FOMC", "Fed", "GDP", "Unemployment", 
                   "Payroll", "Inflation", "Rate", "PMI", "Retail"]
        for e in events[:20]:
            name = e.get("event", "")
            date = e.get("time", "")[:10]
            if any(k.lower() in name.lower() for k in keywords):
                high_impact.append(f"  📅 {date}: {name}")
        return high_impact[:6] if high_impact else ["  Δεν υπάρχουν major events αυτή την εβδομάδα"]
    except Exception as e:
        pass
    return ["  Calendar N/A"]

# ─── CLAUDE ANALYSIS ──────────────────────────────────────

async def get_claude_analysis(prices, news, fear_greed, calendar):
    now_athens = datetime.now(ATHENS_TZ).strftime("%A %d %B %Y, %H:%M")

    price_lines = []
    for asset in WATCHLIST:
        q = prices.get(asset["sym"])
        if q and q.get("price"):
            chg = f"{q['change']:+.2f} ({q['pct']:+.2f}%)" if q.get("change") else "N/A"
            price_lines.append(f"  {asset['sym']} ({asset['name']}): ${q['price']:.2f} | {chg}")
        else:
            price_lines.append(f"  {asset['sym']}: N/A")

    news_text = "\n".join(f"  - {h}" for h in news) if news else "  No news"
    calendar_text = "\n".join(calendar)

    prompt = f"""You are a Senior Hedge Fund Analyst. Today is {now_athens} Athens time.

LIVE PRICES:
{chr(10).join(price_lines)}

MARKET SENTIMENT (Fear & Greed Index):
  {fear_greed}

ECONOMIC CALENDAR (next 5 days):
{calendar_text}

LATEST NEWS:
{news_text}

TRADER PROFILE:
- Platform: eToro CFD
- Account: $5,000
- Max risk: $50/trade (1%)
- Max leverage: Gold x3 / ETFs x2
- Style: Day trade / Swing 1-3 days

RULES:
- If a HIGH IMPACT event (NFP, CPI, FOMC) is TODAY → say "No trade today — major event risk"
- If Fear & Greed > 80 (Extreme Greed) → avoid BUY setups
- If Fear & Greed < 20 (Extreme Fear) → avoid SELL setups
- Only give a trade if there is CLEAR edge

Give ONE setup or "No setup today."

FORMAT:
🎯 ASSET: [name]
📈 DIRECTION: BUY or SELL
💪 CONVICTION: High / Medium-High

📊 REASON: [2-3 sentences]

⚙️ LEVELS:
- Entry: $[x]
- Stop Loss: $[x]
- TP1: $[x]
- TP2: $[x]
- R:R: 1:[x]

💰 POSITION:
- eToro amount: $[x]
- Leverage: x[n]
- Max loss: $[x]

⏰ ENTRY TIME: [Athens time]
🚫 INVALIDATION: [one sentence]"""

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 600,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=30
            )
            return r.json()["content"][0]["text"]
    except Exception as e:
        return f"⚠️ Analysis error: {e}"

# ─── TELEGRAM ─────────────────────────────────────────────

async def send_telegram(text):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=10
        )

# ─── MAIN ─────────────────────────────────────────────────

async def run_daily_briefing():
    now = datetime.now(ATHENS_TZ).strftime("%d/%m/%Y %H:%M")
    await send_telegram(f"⏳ <b>MacroTrader</b> — Φορτώνω δεδομένα... ({now})")

    async with httpx.AsyncClient() as client:
        prices, news, fear_greed, calendar = await asyncio.gather(
            fetch_all_prices(client),
            fetch_news(client),
            fetch_fear_greed(client),
            fetch_economic_calendar(client)
        )

    analysis = await get_claude_analysis(prices, news, fear_greed, calendar)

    # Price summary
    lines = []
    for asset in WATCHLIST:
        q = prices.get(asset["sym"])
        if q and q.get("price"):
            e = "🟢" if (q.get("change") or 0) >= 0 else "🔴"
            c = f"{q['pct']:+.1f}%" if q.get("pct") else ""
            lines.append(f"{e} <b>{asset['sym']}</b>: ${q['price']:.2f} {c}")

    calendar_text = "\n".join(calendar)

    msg = f"""📊 <b>MacroTrader Daily Briefing</b>
🕗 {now} (Athens)
━━━━━━━━━━━━━━━━━━━━

<b>LIVE PRICES</b>
{chr(10).join(lines) if lines else 'N/A'}

<b>SENTIMENT</b>
Fear &amp; Greed: {fear_greed}

<b>UPCOMING EVENTS</b>
{calendar_text}

━━━━━━━━━━━━━━━━━━━━
<b>TODAY'S SETUP</b>

{analysis}

━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Not financial advice. Always use Stop Loss.</i>"""

    # Split σε 2 μηνύματα
    msg1 = f"""📊 <b>MacroTrader Daily Briefing</b>
🕗 {now} (Athens)
━━━━━━━━━━━━━━━━━━━━

<b>LIVE PRICES</b>
{chr(10).join(lines) if lines else 'N/A'}

<b>SENTIMENT</b>
Fear &amp; Greed: {fear_greed}

<b>UPCOMING EVENTS</b>
{calendar_text}"""

    msg2 = f"""🎯 <b>TODAY'S SETUP</b>
━━━━━━━━━━━━━━━━━━━━

{analysis[:3500]}

━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Not financial advice. Always use Stop Loss.</i>"""

    await send_telegram(msg1)
    await asyncio.sleep(1)
    await send_telegram(msg2)
    print(f"✅ Sent at {now}")

if __name__ == "__main__":
    asyncio.run(run_daily_briefing())
