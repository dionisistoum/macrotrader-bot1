import os
import asyncio
import httpx
import json
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
ACTIVE_SETUP_FILE = "/tmp/active_setup.json"

# ─── SAVE / LOAD SETUP ────────────────────────────────────

def save_active_setup(setup):
    with open(ACTIVE_SETUP_FILE, "w") as f:
        json.dump(setup, f)

def load_active_setup():
    try:
        with open(ACTIVE_SETUP_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None

def clear_active_setup():
    try:
        os.remove(ACTIVE_SETUP_FILE)
    except Exception:
        pass

# ─── PRICES ───────────────────────────────────────────────

async def fetch_finnhub_quote(client, symbol):
    try:
        r = await client.get("https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": FINNHUB_KEY}, timeout=10)
        d = r.json()
        if d.get("c", 0) > 0:
            return {"price": d["c"], "change": d["d"], "pct": d["dp"], "high": d["h"], "low": d["l"]}
    except Exception:
        pass
    return None

async def fetch_td_quote(client, symbol):
    try:
        r = await client.get("https://api.twelvedata.com/price",
            params={"symbol": symbol, "apikey": TD_KEY}, timeout=10)
        d = r.json()
        if d.get("price"):
            return {"price": float(d["price"]), "change": None, "pct": None}
    except Exception:
        pass
    return None

async def fetch_price(symbol, td_symbol=None):
    async with httpx.AsyncClient() as client:
        if symbol:
            q = await fetch_finnhub_quote(client, symbol)
            if q:
                return q["price"]
        if td_symbol:
            q = await fetch_td_quote(client, td_symbol)
            if q:
                return q["price"]
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

# ─── INTRADAY ─────────────────────────────────────────────

async def fetch_intraday(symbol, interval="15min", bars=20):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.twelvedata.com/time_series",
                params={"symbol": symbol, "interval": interval,
                        "outputsize": bars, "apikey": TD_KEY},
                timeout=10
            )
            d = r.json()
            if d.get("values"):
                closes = [float(v["close"]) for v in reversed(d["values"])]
                highs  = [float(v["high"])  for v in reversed(d["values"])]
                lows   = [float(v["low"])   for v in reversed(d["values"])]
                vols   = [float(v.get("volume", 0)) for v in reversed(d["values"])]
                return {"closes": closes, "highs": highs, "lows": lows, "volumes": vols}
    except Exception:
        pass
    return None

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def calc_ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)

def calc_support_resistance(highs, lows):
    support    = round(min(lows[-10:]), 2)
    resistance = round(max(highs[-10:]), 2)
    return support, resistance

# ─── NEWS ─────────────────────────────────────────────────

async def fetch_news(client):
    try:
        r = await client.get("https://finnhub.io/api/v1/news",
            params={"category": "general", "token": FINNHUB_KEY}, timeout=10)
        items = r.json()
        if isinstance(items, list):
            return [i.get("headline", "") for i in items[:6] if i.get("headline")]
    except Exception:
        pass
    return []

# ─── FEAR & GREED ─────────────────────────────────────────

async def fetch_fear_greed(client):
    try:
        r = await client.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d = r.json()["data"][0]
        score = int(d["value"])
        label = d["value_classification"]
        emoji = "🟢" if score < 30 else "🔴" if score > 70 else "🟡"
        return f"{emoji} {score}/100 — {label}"
    except Exception:
        pass
    return "N/A"

# ─── ECONOMIC CALENDAR ────────────────────────────────────

async def fetch_economic_calendar(client):
    try:
        today    = datetime.now(ATHENS_TZ).strftime("%Y-%m-%d")
        week_end = (datetime.now(ATHENS_TZ) + timedelta(days=5)).strftime("%Y-%m-%d")
        r = await client.get("https://finnhub.io/api/v1/calendar/economic",
            params={"from": today, "to": week_end, "token": FINNHUB_KEY}, timeout=10)
        events = r.json().get("economicCalendar", [])
        keywords = ["NFP", "CPI", "FOMC", "Fed", "GDP", "Unemployment",
                   "Payroll", "Inflation", "Rate", "PMI", "Retail"]
        high_impact = []
        for e in events[:20]:
            name = e.get("event", "")
            date = e.get("time", "")[:10]
            if any(k.lower() in name.lower() for k in keywords):
                high_impact.append(f"  {date}: {name}")
        return high_impact[:6] if high_impact else ["  No major events this week"]
    except Exception:
        pass
    return ["  Calendar N/A"]

# ─── CLAUDE ANALYSIS ──────────────────────────────────────

async def get_claude_analysis(prices, news, fear_greed, calendar, intraday_data=None):
    now_athens = datetime.now(ATHENS_TZ).strftime("%A %d %B %Y, %H:%M")

    price_lines = []
    for asset in WATCHLIST:
        q = prices.get(asset["sym"])
        if q and q.get("price"):
            chg = f"{q['change']:+.2f} ({q['pct']:+.2f}%)" if q.get("change") else "N/A"
            price_lines.append(f"  {asset['sym']}: ${q['price']:.2f} | {chg}")
        else:
            price_lines.append(f"  {asset['sym']}: N/A")

    intraday_text = ""
    if intraday_data:
        closes = intraday_data["closes"]
        rsi    = calc_rsi(closes)
        ema20  = calc_ema(closes, 20)
        ema50  = calc_ema(closes, 50) if len(closes) >= 50 else None
        sup, res = calc_support_resistance(intraday_data["highs"], intraday_data["lows"])
        avg_vol  = sum(intraday_data["volumes"]) / len(intraday_data["volumes"]) if intraday_data["volumes"] else 0
        last_vol = intraday_data["volumes"][-1] if intraday_data["volumes"] else 0
        vol_status = "HIGH" if last_vol > avg_vol * 1.5 else "Normal"

        intraday_text = f"""
INTRADAY TECHNICALS (15min):
  RSI(14): {rsi}
  EMA20: {ema20}
  EMA50: {ema50 if ema50 else 'N/A (need more data)'}
  Support: {sup}
  Resistance: {res}
  Volume: {vol_status}
  Last close: {closes[-1] if closes else 'N/A'}
  Trend: {'BULLISH' if ema20 and closes[-1] > ema20 else 'BEARISH'}"""

    news_text     = "\n".join(f"  - {h}" for h in news) if news else "  No news"
    calendar_text = "\n".join(calendar)

    prompt = f"""You are a Senior Hedge Fund Analyst. Today is {now_athens} Athens time.

LIVE PRICES:
{chr(10).join(price_lines)}
{intraday_text}

FEAR & GREED: {fear_greed}

ECONOMIC CALENDAR (next 5 days):
{calendar_text}

NEWS:
{news_text}

TRADER: eToro CFD, $5000, max risk $50/trade, Gold x3 / ETFs x2.
RULES: No SELL in Extreme Fear. No BUY in Extreme Greed. No trade on NFP/CPI/FOMC day.

Give ONE setup or say: No setup today.

RESPOND IN THIS EXACT FORMAT — plain text only, no markdown:

ASSET: [symbol]
DIRECTION: BUY or SELL
CONVICTION: High or Medium-High

REASON:
[2-3 sentences]

LEVELS:
Entry: [price]
Stop Loss: [price]
TP1: [price]
TP2: [price]
RR: 1:[x]

POSITION:
eToro amount: $[x]
Leverage: x[n]
Max loss: $[x]

ENTRY TIME: [Athens time]
INVALIDATION: [one sentence]

IMPORTANT: Also output these 3 lines at the very end for system parsing:
PARSE_ASSET: [symbol e.g. GLD]
PARSE_ENTRY: [number only e.g. 417.50]
PARSE_SL: [number only e.g. 412.80]
PARSE_TP1: [number only e.g. 423.00]
PARSE_TP2: [number only e.g. 428.50]"""

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
        return f"Analysis error: {e}"

def parse_setup_from_analysis(analysis, asset_map):
    setup = {}
    for line in analysis.split("\n"):
        if line.startswith("PARSE_ASSET:"):
            sym = line.split(":", 1)[1].strip()
            setup["symbol"] = sym
            setup["fh"]  = asset_map.get(sym, {}).get("fh")
            setup["td"]  = asset_map.get(sym, {}).get("td")
        elif line.startswith("PARSE_ENTRY:"):
            try: setup["entry"] = float(line.split(":", 1)[1].strip())
            except: pass
        elif line.startswith("PARSE_SL:"):
            try: setup["sl"] = float(line.split(":", 1)[1].strip())
            except: pass
        elif line.startswith("PARSE_TP1:"):
            try: setup["tp1"] = float(line.split(":", 1)[1].strip())
            except: pass
        elif line.startswith("PARSE_TP2:"):
            try: setup["tp2"] = float(line.split(":", 1)[1].strip())
            except: pass
    setup["alerted_entry"] = False
    setup["alerted_sl"]    = False
    setup["alerted_tp1"]   = False
    setup["alerted_tp2"]   = False
    return setup if "entry" in setup else None

# ─── PRICE ALERT MONITOR ──────────────────────────────────

async def check_price_alerts():
    setup = load_active_setup()
    if not setup or "entry" not in setup:
        return

    symbol = setup.get("symbol", "")
    fh_sym = setup.get("fh")
    td_sym = setup.get("td")
    price  = await fetch_price(fh_sym, td_sym)

    if not price:
        return

    entry = setup["entry"]
    sl    = setup["sl"]
    tp1   = setup["tp1"]
    tp2   = setup["tp2"]

    msg = None

    # Entry reached
    if not setup["alerted_entry"] and abs(price - entry) / entry < 0.002:
        msg = f"""🟡 <b>ENTRY ALERT — {symbol}</b>
Price: ${price:.2f}
Entry zone: ${entry:.2f}
⚡ Consider entering now!
SL: ${sl:.2f} | TP1: ${tp1:.2f} | TP2: ${tp2:.2f}"""
        setup["alerted_entry"] = True

    # SL hit
    elif not setup["alerted_sl"] and price <= sl:
        msg = f"""🔴 <b>STOP LOSS HIT — {symbol}</b>
Price: ${price:.2f}
SL was: ${sl:.2f}
❌ Trade invalidated. Setup closed."""
        setup["alerted_sl"] = True
        clear_active_setup()
        await send_telegram(msg)
        return

    # TP1 hit
    elif not setup["alerted_tp1"] and price >= tp1:
        msg = f"""🟢 <b>TP1 HIT — {symbol}</b>
Price: ${price:.2f}
TP1: ${tp1:.2f}
✅ Close 50% of position. Move SL to Break-Even (${entry:.2f})"""
        setup["alerted_tp1"] = True

    # TP2 hit
    elif not setup["alerted_tp2"] and price >= tp2:
        msg = f"""💰 <b>TP2 HIT — {symbol}</b>
Price: ${price:.2f}
TP2: ${tp2:.2f}
🎯 Close remaining position. Full target reached!"""
        setup["alerted_tp2"] = True
        save_active_setup(setup)
        await send_telegram(msg)
        clear_active_setup()
        return

    if msg:
        save_active_setup(setup)
        await send_telegram(msg)

# ─── TELEGRAM ─────────────────────────────────────────────

async def send_telegram(text):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=10
        )

# ─── MAIN BRIEFING ────────────────────────────────────────

async def run_daily_briefing(session="morning"):
    now = datetime.now(ATHENS_TZ).strftime("%d/%m/%Y %H:%M")
    session_label = "🌅 Morning (London)" if session == "morning" else "🌆 Afternoon (NY)"
    await send_telegram(f"⏳ <b>MacroTrader {session_label}</b> — Loading... ({now})")

    async with httpx.AsyncClient() as client:
        prices, news, fear_greed, calendar = await asyncio.gather(
            fetch_all_prices(client),
            fetch_news(client),
            fetch_fear_greed(client),
            fetch_economic_calendar(client)
        )

    # Fetch intraday for GLD (primary asset)
    intraday = await fetch_intraday("GLD", interval="15min", bars=50)

    analysis = await get_claude_analysis(prices, news, fear_greed, calendar, intraday)

    # Parse and save setup for price alerts
    asset_map = {a["sym"]: {"fh": a["fh"], "td": a["td"]} for a in WATCHLIST}
    setup = parse_setup_from_analysis(analysis, asset_map)
    if setup:
        save_active_setup(setup)
        print(f"✅ Active setup saved: {setup}")

    # Clean analysis (remove PARSE_ lines)
    clean = "\n".join(l for l in analysis.split("\n") if not l.startswith("PARSE_"))

    lines = []
    for asset in WATCHLIST:
        q = prices.get(asset["sym"])
        if q and q.get("price"):
            e = "🟢" if (q.get("change") or 0) >= 0 else "🔴"
            c = f"{q['pct']:+.1f}%" if q.get("pct") else ""
            lines.append(f"{e} <b>{asset['sym']}</b>: ${q['price']:.2f} {c}")

    # Intraday summary
    intraday_summary = ""
    if intraday:
        closes = intraday["closes"]
        rsi    = calc_rsi(closes)
        ema20  = calc_ema(closes, 20)
        sup, res = calc_support_resistance(intraday["highs"], intraday["lows"])
        intraday_summary = f"""
<b>GLD INTRADAY (15min)</b>
RSI: {rsi} | EMA20: {ema20}
Support: {sup} | Resistance: {res}"""

    calendar_text = "\n".join(calendar)

    msg1 = f"""📊 <b>MacroTrader {session_label}</b>
🕗 {now} (Athens)
━━━━━━━━━━━━━━━━━━━━

<b>LIVE PRICES</b>
{chr(10).join(lines) if lines else 'N/A'}
{intraday_summary}

<b>SENTIMENT</b>
Fear &amp; Greed: {fear_greed}

<b>UPCOMING EVENTS</b>
{calendar_text}"""

    msg2 = f"""🎯 <b>TODAY'S SETUP</b>
━━━━━━━━━━━━━━━━━━━━

{clean}

━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Not financial advice. Always use Stop Loss.</i>"""

    await send_telegram(msg1)
    await asyncio.sleep(1)
    await send_telegram(msg2)
    print(f"✅ Briefing sent at {now}")

if __name__ == "__main__":
    asyncio.run(run_daily_briefing())
