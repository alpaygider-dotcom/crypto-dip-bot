import asyncio
import aiohttp
import time
import os
from statistics import mean, stdev

# =========================
# ENV
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BINANCE_KEY = os.getenv("BINANCE_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")

FAPI = "https://fapi.binance.com"

# =========================
# CONFIG
# =========================
COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","ADAUSDT","AVAXUSDT"]

SCAN_INTERVAL = 20
COOLDOWN = 300

MAX_RISK_PER_TRADE = 0.02   # %2 risk
DAILY_LOSS_LIMIT = 0.05     # %5 stop

last_signal = {}
trade_memory = []

sem = asyncio.Semaphore(10)

# =========================
# ACCOUNT SIMULATION (paper logic)
# =========================
equity = 1000
daily_pnl = 0

# =========================
# TELEGRAM
# =========================
async def send(session, msg):
    if not BOT_TOKEN:
        print(msg)
        return

    try:
        await session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        pass

# =========================
# FETCH
# =========================
async def fetch(session, url, params=None):
    try:
        async with sem:
            async with session.get(url, params=params, timeout=10) as r:
                return await r.json()
    except:
        return None

# =========================
# REGIME
# =========================
def regime(closes, vols):
    if len(closes) < 20:
        return "UNKNOWN"

    ret = (closes[-1] - closes[0]) / closes[0]
    vol = stdev(vols) if len(vols) > 1 else 0

    if abs(ret) < 0.002 and vol < mean(vols):
        return "RANGE"
    if abs(ret) > 0.01:
        return "TREND"
    return "MIXED"

# =========================
# RISK ENGINE (NEW)
# =========================
def position_size(score):
    base = equity * MAX_RISK_PER_TRADE
    multiplier = min(score / 10, 1.5)
    return base * multiplier

def risk_check():
    if abs(daily_pnl) > equity * DAILY_LOSS_LIMIT:
        return False
    return True

# =========================
# SCORING (SMART MONEY)
# =========================
def score(change, vol_z, taker, reg, sweep):
    L, S = 0, 0

    if change > 1: L += 2
    if change < -1: S += 2

    if vol_z > 1.5: L += 2
    if vol_z < -1.5: S += 2

    if taker > 0.6: L += 2
    if taker < 0.4: S += 2

    if reg == "TREND":
        L += 1; S += 1

    if sweep == "DOWN":
        L += 3
    if sweep == "UP":
        S += 3

    return L, S

# =========================
# EXECUTION ENGINE (PAPER / READY FOR LIVE)
# =========================
async def execute_trade(session, symbol, direction, size):
    global equity, daily_pnl

    # ⚠️ PAPER MODE (no real trade)
    pnl = size * 0.01  # fake outcome simulation

    if direction == "LONG":
        equity += pnl
    else:
        equity += pnl

    daily_pnl += pnl

    trade_memory.append({
        "symbol": symbol,
        "direction": direction,
        "pnl": pnl
    })

    msg = f"EXECUTED {symbol} {direction} | PnL: {pnl:.2f} | Equity: {equity:.2f}"
    await send(session, msg)

# =========================
# SCAN
# =========================
async def scan(session, symbol):
    try:
        kl = await fetch(session, f"{FAPI}/fapi/v1/klines",
                         {"symbol": symbol, "interval": "5m", "limit": 50})

        if not kl:
            return None

        closes = [float(k[4]) for k in kl]
        vols = [float(k[5]) for k in kl]
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]

        last = kl[-2]

        open_p = float(last[1])
        close_p = float(last[4])
        vol = float(last[5])
        taker = float(last[9])

        change = ((close_p - open_p) / open_p) * 100

        v_mean = mean(vols)
        v_std = stdev(vols) if len(vols) > 1 else 0
        vol_z = (vol - v_mean) / v_std if v_std else 0

        reg = regime(closes, vols)

        sweep_up = highs[-1] > max(highs[-10:-1]) and closes[-1] < highs[-1]
        sweep_down = lows[-1] < min(lows[-10:-1]) and closes[-1] > lows[-1]

        L, S = score(change, vol_z, taker/vol if vol else 0, reg,
                      "DOWN" if sweep_down else "UP" if sweep_up else "NONE")

        if max(L, S) < 7:
            return None

        direction = "LONG" if L > S else "SHORT"
        final_score = max(L, S)

        # cooldown
        now = time.time()
        if symbol in last_signal and now - last_signal[symbol] < COOLDOWN:
            return None

        last_signal[symbol] = now

        # RISK CHECK
        if not risk_check():
            return None

        size = position_size(final_score)

        # EXECUTE (paper)
        await execute_trade(session, symbol, direction, size)

        return {
            "symbol": symbol,
            "score": final_score,
            "direction": direction,
            "regime": reg
        }

    except:
        return None

# =========================
# MAIN LOOP
# =========================
async def main():
    print("V11 INSTITUTIONAL ENGINE STARTED")

    async with aiohttp.ClientSession() as session:
        while True:
            tasks = [scan(session, c) for c in COINS]
            res = await asyncio.gather(*tasks)

            signals = [r for r in res if r]

            for s in signals:
                msg = f"{s['symbol']} {s['direction']} | SCORE {s['score']} | REGIME {s['regime']}"
                print(msg)
                await send(session, msg)

            await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
