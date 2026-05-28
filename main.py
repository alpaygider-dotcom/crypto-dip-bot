import asyncio
import aiohttp
import os
import time
from statistics import mean, stdev
from binance import AsyncClient
from binance.enums import *

# ==================================================
# ENV
# ==================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BINANCE_KEY = os.getenv("BINANCE_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")

# ==================================================
# CONFIG
# ==================================================
COINS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "ADAUSDT"
]

INTERVAL = "5m"

SCAN_INTERVAL = 20
COOLDOWN = 300

LEVERAGE = 5
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS = 0.05

USE_LIVE_TRADING = False   # ⚠️ TRUE yaparsan gerçek emir açar

# ==================================================
# GLOBALS
# ==================================================
last_signal = {}
daily_pnl = 0
sem = asyncio.Semaphore(10)

# ==================================================
# TELEGRAM
# ==================================================
async def send_telegram(session, text):
    if not BOT_TOKEN or not CHAT_ID:
        print(text)
        return

    try:
        await session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text
            }
        )
    except Exception as e:
        print("Telegram Error:", e)

# ==================================================
# FETCH
# ==================================================
async def fetch_klines(client, symbol):
    try:
        return await client.futures_klines(
            symbol=symbol,
            interval=INTERVAL,
            limit=50
        )
    except:
        return None

# ==================================================
# MARKET REGIME
# ==================================================
def regime(closes, vols):
    ret = (closes[-1] - closes[0]) / closes[0]

    vol_mean = mean(vols)
    vol_std = stdev(vols) if len(vols) > 1 else 0

    vol_z = (vols[-1] - vol_mean) / vol_std if vol_std else 0

    if abs(ret) < 0.003:
        return "RANGE"

    if abs(ret) > 0.01 and vol_z > 1:
        return "TREND"

    return "MIXED"

# ==================================================
# LIQUIDITY SWEEP
# ==================================================
def liquidity_sweep(highs, lows, closes):
    sweep_up = (
        highs[-1] > max(highs[-10:-1])
        and closes[-1] < highs[-1]
    )

    sweep_down = (
        lows[-1] < min(lows[-10:-1])
        and closes[-1] > lows[-1]
    )

    return sweep_up, sweep_down

# ==================================================
# SCORE ENGINE
# ==================================================
def calculate_score(change, taker_ratio, vol_z,
                    reg, sweep_up, sweep_down):

    long_score = 0
    short_score = 0

    # momentum
    if change > 1:
        long_score += 2

    if change < -1:
        short_score += 2

    # taker pressure
    if taker_ratio > 0.6:
        long_score += 2

    if taker_ratio < 0.4:
        short_score += 2

    # anomaly volume
    if vol_z > 1.5:
        long_score += 2

    # regime
    if reg == "TREND":
        long_score += 1
        short_score += 1

    if reg == "RANGE":
        long_score -= 1
        short_score -= 1

    # liquidity
    if sweep_down:
        long_score += 3

    if sweep_up:
        short_score += 3

    return long_score, short_score

# ==================================================
# POSITION SIZE
# ==================================================
def calculate_qty(balance, price):
    risk_amount = balance * RISK_PER_TRADE
    qty = (risk_amount * LEVERAGE) / price
    return round(qty, 3)

# ==================================================
# EXECUTE TRADE
# ==================================================
async def execute_trade(client, symbol, direction,
                        qty, entry_price):

    if not USE_LIVE_TRADING:
        print(f"[PAPER] {symbol} {direction}")
        return True

    try:
        side = SIDE_BUY if direction == "LONG" else SIDE_SELL

        await client.futures_change_leverage(
            symbol=symbol,
            leverage=LEVERAGE
        )

        order = await client.futures_create_order(
            symbol=symbol,
            side=side,
            type=FUTURE_ORDER_TYPE_MARKET,
            quantity=qty
        )

        print("ORDER:", order)
        return True

    except Exception as e:
        print("ORDER ERROR:", e)
        return False

# ==================================================
# SCAN
# ==================================================
async def scan(client, session, symbol):

    global daily_pnl

    try:
        kl = await fetch_klines(client, symbol)

        if not kl:
            return

        closes = [float(k[4]) for k in kl]
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]
        vols = [float(k[5]) for k in kl]

        last = kl[-2]

        open_p = float(last[1])
        close_p = float(last[4])
        vol = float(last[5])
        taker_buy = float(last[9])

        change = ((close_p - open_p) / open_p) * 100

        taker_ratio = taker_buy / vol if vol else 0

        vol_mean = mean(vols)
        vol_std = stdev(vols) if len(vols) > 1 else 0

        vol_z = (vol - vol_mean) / vol_std if vol_std else 0

        reg = regime(closes, vols)

        sweep_up, sweep_down = liquidity_sweep(
            highs, lows, closes
        )

        long_score, short_score = calculate_score(
            change,
            taker_ratio,
            vol_z,
            reg,
            sweep_up,
            sweep_down
        )

        if max(long_score, short_score) < 7:
            return

        direction = (
            "LONG"
            if long_score > short_score
            else "SHORT"
        )

        now = time.time()

        if symbol in last_signal:
            if now - last_signal[symbol] < COOLDOWN:
                return

        last_signal[symbol] = now

        # fake balance
        fake_balance = 1000

        qty = calculate_qty(fake_balance, close_p)

        ok = await execute_trade(
            client,
            symbol,
            direction,
            qty,
            close_p
        )

        if not ok:
            return

        msg = (
            f"{'🟢' if direction=='LONG' else '🔴'} "
            f"{symbol}\n"
            f"Direction: {direction}\n"
            f"Score: {max(long_score, short_score)}\n"
            f"Change: %{round(change,2)}\n"
            f"Vol Z: {round(vol_z,2)}\n"
            f"Regime: {reg}\n"
            f"Qty: {qty}"
        )

        print(msg)

        await send_telegram(session, msg)

    except Exception as e:
        print("SCAN ERROR:", symbol, e)

# ==================================================
# MAIN
# ==================================================
async def main():

    print("🚀 FINAL AI BOT STARTED")

    client = await AsyncClient.create(
        BINANCE_KEY,
        BINANCE_SECRET
    )

    async with aiohttp.ClientSession() as session:

        while True:

            tasks = [
                scan(client, session, c)
                for c in COINS
            ]

            await asyncio.gather(*tasks)

            await asyncio.sleep(SCAN_INTERVAL)

# ==================================================
# START
# ==================================================
if __name__ == "__main__":
    asyncio.run(main())
``
