import asyncio
import aiohttp
import os
import time
from statistics import mean, stdev

# ======================================
# ENV
# ======================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ======================================
# CONFIG
# ======================================
COINS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "ADAUSDT"
]

BASE_URL = "https://fapi.binance.com"

INTERVAL = "5m"

SCAN_INTERVAL = 30
COOLDOWN = 300

USE_LIVE_TRADING = False

# ======================================
# GLOBALS
# ======================================
last_signal = {}

# ======================================
# TELEGRAM
# ======================================
async def send_telegram(session, text):

    if not BOT_TOKEN or not CHAT_ID:
        print(text)
        return

    try:

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        payload = {
            "chat_id": CHAT_ID,
            "text": text
        }

        await session.post(
            url,
            json=payload
        )

    except Exception as e:
        print("Telegram Error:", e)

# ======================================
# FETCH KLINES
# ======================================
async def fetch_klines(
    session,
    symbol
):

    try:

        url = f"{BASE_URL}/fapi/v1/klines"

        params = {
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": 50
        }

        async with session.get(
            url,
            params=params,
            timeout=10
        ) as response:

            if response.status != 200:
                return None

            return await response.json()

    except Exception as e:
        print("Fetch Error:", symbol, e)
        return None

# ======================================
# REGIME
# ======================================
def detect_regime(
    closes,
    volumes
):

    if len(closes) < 20:
        return "UNKNOWN"

    move = (
        closes[-1] - closes[0]
    ) / closes[0]

    vol_mean = mean(volumes)

    vol_std = (
        stdev(volumes)
        if len(volumes) > 1 else 0
    )

    vol_z = (
        (volumes[-1] - vol_mean) / vol_std
        if vol_std > 0 else 0
    )

    if abs(move) < 0.003:
        return "RANGE"

    if abs(move) > 0.01 and vol_z > 1:
        return "TREND"

    return "MIXED"

# ======================================
# LIQUIDITY SWEEP
# ======================================
def detect_sweep(
    highs,
    lows,
    closes
):

    sweep_up = (
        highs[-1] > max(highs[-10:-1])
        and closes[-1] < highs[-1]
    )

    sweep_down = (
        lows[-1] < min(lows[-10:-1])
        and closes[-1] > lows[-1]
    )

    return sweep_up, sweep_down

# ======================================
# SCORE ENGINE
# ======================================
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

    # liquidity
    if sweep_down:
        long_score += 3

    if sweep_up:
        short_score += 3

    return long_score, short_score

# ======================================
# SCAN COIN
# ======================================
async def scan_coin(
    session,
    symbol
):

    try:

        klines = await fetch_klines(
            session,
            symbol
        )

        if not klines:
            return

        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        volumes = [float(k[5]) for k in klines]

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

        vol_mean = mean(volumes)

        vol_std = (
            stdev(volumes)
            if len(volumes) > 1 else 0
        )

        vol_z = (
            (volume - vol_mean) / vol_std
            if vol_std > 0 else 0
        )

        regime = detect_regime(
            closes,
            volumes
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

        msg = (
            f"{'🟢' if direction == 'LONG' else '🔴'} "
            f"{symbol}\n"
            f"Direction: {direction}\n"
            f"Score: {best_score}\n"
            f"Change: %{round(change,2)}\n"
            f"Vol Z: {round(vol_z,2)}\n"
            f"Regime: {regime}\n"
            f"Mode: PAPER"
        )

        print(msg)

        await send_telegram(
            session,
            msg
        )

    except Exception as e:
        print("SCAN ERROR:", symbol, e)

# ======================================
# MAIN
# ======================================
async def main():

    print("🚀 BOT STARTED")

    async with aiohttp.ClientSession() as session:

        while True:

            tasks = [
                scan_coin(
                    session,
                    coin
                )
                for coin in COINS
            ]

            await asyncio.gather(*tasks)

            await asyncio.sleep(
                SCAN_INTERVAL
            )

# ======================================
# START
# ======================================
if __name__ == "__main__":
    asyncio.run(main())
