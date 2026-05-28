import asyncio
import aiohttp
import os
import time
from statistics import mean, stdev

# =====================================
# ENV
# =====================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# =====================================
# CONFIG
# =====================================
BASE_URL = "https://fapi.binance.com"

COINS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "WIFUSDT",
    "SEIUSDT",
    "SUIUSDT"
]

INTERVAL = "5m"

SCAN_INTERVAL = 40
COOLDOWN = 600

# =====================================
# GLOBALS
# =====================================
last_signal = {}

# =====================================
# TELEGRAM
# =====================================
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
        print("TELEGRAM ERROR:", e)

# =====================================
# FETCH
# =====================================
async def fetch_json(session, endpoint, params=None):

    try:

        url = BASE_URL + endpoint

        async with session.get(
            url,
            params=params,
            timeout=10
        ) as response:

            if response.status != 200:
                return None

            return await response.json()

    except Exception:
        return None

# =====================================
# REGIME
# =====================================
def detect_regime(closes, volumes):

    move = (closes[-1] - closes[0]) / closes[0]

    vol_mean = mean(volumes)

    vol_std = stdev(volumes) if len(volumes) > 1 else 0

    vol_z = 0

    if vol_std > 0:
        vol_z = (volumes[-1] - vol_mean) / vol_std

    if abs(move) < 0.004:
        return "RANGE"

    if abs(move) > 0.012 and vol_z > 1:
        return "TREND"

    return "MIXED"

# =====================================
# SWEEP
# =====================================
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

# =====================================
# SIDEWAYS
# =====================================
def sideways_breakout(closes):

    recent = closes[-15:]

    highest = max(recent)
    lowest = min(recent)

    range_pct = ((highest - lowest) / lowest) * 100

    breakout_up = closes[-1] > highest * 0.998
    breakout_down = closes[-1] < lowest * 1.002

    compressed = range_pct < 2.5

    return compressed, breakout_up, breakout_down

# =====================================
# HEAVY DATA
# =====================================
async def get_heavy_data(session, symbol):

    funding = 0
    oi_change = 0
    long_short = 1

    # FUNDING
    funding_data = await fetch_json(
        session,
        "/fapi/v1/premiumIndex",
        {"symbol": symbol}
    )

    if funding_data:
        funding = float(
            funding_data.get(
                "lastFundingRate",
                0
            )
        )

    # OI
    oi_data = await fetch_json(
        session,
        "/futures/data/openInterestHist",
        {
            "symbol": symbol,
            "period": "5m",
            "limit": 2
        }
    )

    if oi_data and len(oi_data) >= 2:

        prev_oi = float(
            oi_data[-2]["sumOpenInterest"]
        )

        curr_oi = float(
            oi_data[-1]["sumOpenInterest"]
        )

        if prev_oi > 0:

            oi_change = (
                (curr_oi - prev_oi)
                / prev_oi
            ) * 100

    # LONG SHORT
    ratio_data = await fetch_json(
        session,
        "/futures/data/topLongShortPositionRatio",
        {
            "symbol": symbol,
            "period": "5m",
            "limit": 1
        }
    )

    if ratio_data:

        try:
            long_short = float(
                ratio_data[-1]["longShortRatio"]
            )
        except:
            pass

    return funding, oi_change, long_short

# =====================================
# SCORE
# =====================================
def calculate_score(
    change,
    taker_ratio,
    vol_z,
    regime,
    sweep_up,
    sweep_down,
    funding,
    oi_change,
    long_short,
    compressed,
    breakout_up,
    breakout_down
):

    long_score = 0
    short_score = 0

    # MOMENTUM
    if change > 1:
        long_score += 2

    if change < -1:
        short_score += 2

    # TAKER
    if taker_ratio > 0.60:
        long_score += 2

    if taker_ratio < 0.40:
        short_score += 2

    # VOLUME
    if vol_z > 2:
        long_score += 2
        short_score += 2

    # REGIME
    if regime == "TREND":
        long_score += 1
        short_score += 1

    # SWEEP
    if sweep_down:
        long_score += 3

    if sweep_up:
        short_score += 3

    # OI
    if oi_change > 3:
        long_score += 2
        short_score += 2

    # FUNDING
    if funding < -0.01 and change > 0:
        long_score += 3

    if funding > 0.01 and change < 0:
        short_score += 3

    # LONG SHORT
    if long_short > 1.5:
        short_score += 1

    if long_short < 0.7:
        long_score += 1

    # SIDEWAYS
    if compressed and breakout_up:
        long_score += 3

    if compressed and breakout_down:
        short_score += 3

    return long_score, short_score

# =====================================
# SIGNAL CLASS
# =====================================
def classify_signal(score):

    if score >= 11:
        return "ZIRHLI"

    if score >= 7:
        return "ACABA"

    return None

# =====================================
# SCAN
# =====================================
async def scan_coin(session, symbol):

    try:

        klines = await fetch_json(
            session,
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": INTERVAL,
                "limit": 50
            }
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

        taker_ratio = 0

        if volume > 0:
            taker_ratio = taker_buy / volume

        vol_mean = mean(volumes)

        vol_std = stdev(volumes) if len(volumes) > 1 else 0

        vol_z = 0

        if vol_std > 0:
