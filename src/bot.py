import os
import asyncio
import httpx
from datetime import datetime
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

async def fetch_news(client):
    try:
        r = await client.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": FINNHUB_KEY},
            timeout=10
        )
        items = r.json()
        if isinstance(items, list):
            return [i.get("headline", "") for i in items[:8] if i.get("headline")]
    except Exception:
        pass
    return []

async def fetch_all_prices():
    async with httpx.AsyncClient() as client:
        tasks = []
        for asset in WATCHLIST:
            if asset["fh"]:
                tasks.append(fetch_finnhub_quote(client, asset["fh"]))
            else:
                tasks.append(fetch_td_quote(client, asset["td"]))
        news_coro = fetch_news(client)
        results = await asyncio.gather(*tasks)
        news = await news_coro
    prices = {}
    for i, asset in enumerate(WATCHLIST):
        prices[asset["sym"]] = results[i] if results[i] and results[i].get("price") else None
    return prices, news

async def get_claude_analysis(prices, news):
    now_athens = datetime.now(ATHENS_TZ).strftime("%A %d %B %Y, %H:%M")
    price_lines = []
    for asset in WATCHLIST:
        q = prices.get(asset["sym"])
        if q and q.get("price"):
            chg = f"{q['change']:+.2f} ({q['pct']:+.2f}%)" if q.get("change") else "N/A"
            price_lines.append(f"  {asset['sym']} ({asset['name']}): ${q['price']:.2f} | {chg}")
        else:
            price_lines.append(f"  {asset['sym']}: N/A")
    news_lines = "\n".join(f"  - {h}" for h in news[:6]) if news else "  No news"
    prompt = f"""You are a Senior Hedge Fund Analyst. Today is {now_athens} Athens time.

LIVE PRICES:
{chr(10).join(price_lines)}

NEWS:
{news_lines}

TRADER: eToro CFD, $5000 account, max risk $50/trade (1%), max leverage Gold x3 / ETFs x2.

Give ONE high-probability trade setup or say "No setup today."

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
        return f"⚠️ Error: {e}"

async def send_telegram(text):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=10
        )

async def run_daily_briefing():
    now = datetime.now(ATHENS_TZ).strftime("%d/%m/%Y %H:%M")
    await send_telegram(f"⏳ <b>MacroTrader</b> — Φορτώνω δεδομένα... ({now})")
    prices, news = await fetch_all_prices()
    analysis = await get_claude_analysis(prices, news)
    lines = []
    for asset in WATCHLIST:
        q = prices.get(asset["sym"])
        if q and q.get("price"):
            e = "🟢" if (q.get("change") or 0) >= 0 else "🔴"
            c = f"{q['pct']:+.1f}%" if q.get("pct") else ""
            lines.append(f"{e} <b>{asset['sym']}</b>: ${q['price']:.2f} {c}")
    msg = f"""📊 <b>MacroTrader Daily Briefing</b>
🕗 {now} (Athens)
━━━━━━━━━━━━━━━━━━━━

<b>LIVE PRICES</b>
{chr(10).join(lines) if lines else 'N/A'}

━━━━━━━━━━━━━━━━━━━━
<b>TODAY'S SETUP</b>

{analysis}

━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Not financial advice. Always use Stop Loss.</i>"""
    await send_telegram(msg)
    print(f"✅ Sent at {now}")

if __name__ == "__main__":
    asyncio.run(run_daily_briefing())
