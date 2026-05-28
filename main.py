import asyncio
import aiohttp
import os
import time
from statistics import mean, stdev
from binance import AsyncClient
from binance.enums import *

# =========================================
# ENV
# =========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BINANCE_KEY = os.getenv("BINANCE_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")

# =========================================
# CONFIG
# =========================================
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

# FALSE = paper mode
# TRUE = real trade
USE_LIVE_TRADING = False

# =========================================
# GLOBALS
# =========================================
last_signal = {}

# =========================================
# TELEGRAM
# =========================================
async def send_telegram(session, text):
    try:
        if not BOT_TOKEN or not CHAT_ID:
            print(text)
            return

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        payload = {
            "chat_id": CHAT_ID,
            "text": text
        }

        await session.post(url, json=payload)

    except Exception as e:
        print("Telegram Error:", e)

# =========================================
# MARKET REGIME
# =========================================
def detect_regime(closes, vols):

    if len(closes) < 20:
        return "UNKNOWN"

    ret = (closes[-1] - closes[0]) / closes[0]

    vol_mean = mean(vols)

    vol_std = stdev(vols) if len(vols) > 1 else 0

    vol_z = (
        (vols[-1] - vol_mean) / vol_std
        if vol_std > 0 else 0
    )

    if abs(ret) < 0.003:
        return "RANGE"

    if abs(ret) > 0.01 and vol_z > 1:
        return "TREND"

    return "MIXED"

# =========================================
# LIQUIDITY SWEEP
# =========================================
def detect_sweep(highs, lows, closes):

    sweep_up = (
        highs[-1] > max(highs[-10:-1])
        and closes[-1] < highs[-1]
    )

    sweep_down = (
        lows[-1] < min(lows[-10:-1])
        and closes[-1] > lows[-1]
    )

    return sweep_up, sweep_down

# =========================================
# SCORE ENGINE
# =========================================
def calculate_score(
    change,
    taker_ratio,
    vol_z,
    regime,
    sweep_up,
    sweep_down
):

    long_score = 0
    short_score = 0

    # momentum
    if change > 1:
        long_score += 2

    if change < -1:
        short_score += 2

    # taker pressure
    if taker_ratio > 0.60:
        long_score += 2

    if taker_ratio < 0.40:
        short_score += 2

    # volume anomaly
    if vol_z > 1.5:
        long_score += 2

    # regime
    if regime == "TREND":
        long_score += 1
        short_score += 1

    if regime == "RANGE":
        long_score -= 1
        short_score -= 1

    # liquidity sweep
    if sweep_down:
        long_score += 3

    if sweep_up:
        short_score += 3

    return long_score, short_score

# =========================================
# POSITION SIZE
# =========================================
def calculate_qty(balance, price):

    risk_amount = balance * RISK_PER_TRADE

    qty = (risk_amount * LEVERAGE) / price

    return round(qty, 3)

# =========================================
# EXECUTE TRADE
# =========================================
async def execute_trade(
    client,
    symbol,
    direction,
    qty
):

    try:

        if not USE_LIVE_TRADING:
            print(f"[PAPER] {symbol} {direction}")
            return True

        side = (
            SIDE_BUY
            if direction == "LONG"
            else SIDE_SELL
        )

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

        print(order)

        return True

    except Exception as e:
        print("ORDER ERROR:", e)
        return False

# =========================================
# SCAN COIN
# =========================================
async def scan_coin(
    client,
    session,
    symbol
):

    try:

        klines = await client.futures_klines(
            symbol=symbol,
            interval=INTERVAL,
            limit=50
        )

        if not klines:
            return

        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        vols = [float(k[5]) for k in klines]

        last = klines[-2]

        open_price = float(last[1])
        close_price = float(last[4])

        volume = float(last[5])

        taker_buy = float(last[9])

        change = (
            (close_price - open_price)
            / open_price
        ) * 100

        taker_ratio = (
            taker_buy / volume
            if volume > 0 else 0
        )

        vol_mean = mean(vols)

        vol_std = (
            stdev(vols)
            if len(vols) > 1 else 0
        )

        vol_z = (
            (volume - vol_mean) / vol_std
            if vol_std > 0 else 0
        )

        regime = detect_regime(
            closes,
            vols
        )

        sweep_up, sweep_down = detect_sweep(
            highs,
            lows,
            closes
        )

        long_score, short_score = calculate_score(
            change,
            taker_ratio,
            vol_z,
            regime,
            sweep_up,
            sweep_down
        )

        best_score = max(
            long_score,
            short_score
        )

        if best_score < 7:
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

        fake_balance = 1000

        qty = calculate_qty(
            fake_balance,
            close_price
        )

        ok = await execute_trade(
            client,
            symbol,
            direction,
            qty
        )

        if not ok:
            return

        msg = (
            f"{'🟢' if direction == 'LONG' else '🔴'} "
            f"{symbol}\n"
            f"Direction: {direction}\n"
            f"Score: {best_score}\n"
            f"Change: %{round(change,2)}\n"
            f"Vol Z: {round(vol_z,2)}\n"
            f"Regime: {regime}\n"
            f"Qty: {qty}"
        )

        print(msg)

        await send_telegram(
            session,
            msg
        )

    except Exception as e:
        print("SCAN ERROR:", symbol, e)

# =========================================
# MAIN
# =========================================
async def main():

    print("🚀 FINAL AI BOT STARTED")

    client = await AsyncClient.create(
        BINANCE_KEY,
        BINANCE_SECRET
    )

    async with aiohttp.ClientSession() as session:

        while True:

            tasks = [
                scan_coin(
                    client,
                    session,
                    coin
                )
                for coin in COINS
            ]

            await asyncio.gather(*tasks)

            await asyncio.sleep(
                SCAN_INTERVAL
            )

# =========================================
# START
# =========================================
if __name__ == "__main__":
    asyncio.run(main())
