import asyncio
import aiohttp
import os
import time
from statistics import mean, stdev

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

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

last_signal = {}

# ==========================================
# TELEGRAM
# ==========================================
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

# ==========================================
# FETCH
# ==========================================
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

    except:
        return None

# ==========================================
# REGIME
# ==========================================
def detect_regime(closes, volumes):

    move = (closes[-1] - closes[0]) / closes[0]

    vol_mean = mean(volumes)

    if len(volumes) > 1:
        vol_std = stdev(volumes)
    else:
        vol_std = 0

    vol_z = 0

    if vol_std > 0:
        vol_z = (volumes[-1] - vol_mean) / vol_std

    if abs(move) < 0.004:
        return "RANGE"

    if abs(move) > 0.012 and vol_z > 1:
        return "TREND"

    return "MIXED"

# ==========================================
# SWEEP
# ==========================================
def detect_sweep(highs, lows, closes):

    sweep_up = False
    sweep_down = False

    if highs[-1] > max(highs[-10:-1]):
        if closes[-1] < highs[-1]:
            sweep_up = True

    if lows[-1] < min(lows[-10:-1]):
        if closes[-1] > lows[-1]:
            sweep_down = True

    return sweep_up, sweep_down

# ==========================================
# SIDEWAYS BREAKOUT
# ==========================================
def sideways_breakout(closes):

    recent = closes[-15:]

    highest = max(recent)
    lowest = min(recent)

    range_pct = ((highest - lowest) / lowest) * 100

    breakout_up = False
    breakout_down = False

    if closes[-1] > highest * 0.998:
        breakout_up = True

    if closes[-1] < lowest * 1.002:
        breakout_down = True

    compressed = False

    if range_pct < 2.5:
        compressed = True

    return compressed, breakout_up, breakout_down

# ==========================================
# HEAVY DATA
# ==========================================
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

    if oi_data:

        if len(oi_data) >= 2:

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

# ==========================================
# SCORE
# ==========================================
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

    # TREND
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

    # BREAKOUT
    if compressed and breakout_up:
        long_score += 3

    if compressed and breakout_down:
        short_score += 3

    return long_score, short_score

# ==========================================
# SIGNAL CLASS
# ==========================================
def classify_signal(score):

    if score >= 12:
        return "🔥 GÜÇLÜ AL"

    if score >= 8:
        return "🟡 ORTA AL"

    if score >= 6:
        return "🟢 AZ AL"

    return None

# ==========================================
# SCAN COIN
# ==========================================
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

        closes = []
        highs = []
        lows = []
        volumes = []

        for k in klines:

            closes.append(float(k[4]))
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            volumes.append(float(k[5]))

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

        if len(volumes) > 1:
            vol_std = stdev(volumes)
        else:
            vol_std = 0

        vol_z = 0

        if vol_std > 0:
            vol_z = (
                (volume - vol_mean)
                / vol_std
            )

        # FAST FILTER
        if abs(change) < 0.4 and vol_z < 1.2:
            return

        regime = detect_regime(
            closes,
            volumes
        )

        sweep_up, sweep_down = detect_sweep(
            highs,
            lows,
            closes
        )

        compressed, breakout_up, breakout_down = sideways_breakout(
            closes
        )

        funding, oi_change, long_short = await get_heavy_data(
            session,
            symbol
        )

        long_score, short_score = calculate_score(
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
        )

        best_score = max(
            long_score,
            short_score
        )

        signal_type = classify_signal(
            best_score
        )

        if not signal_type:
            return

        direction = "LONG"

        if short_score > long_score:
            direction = "SHORT"

        now = time.time()

        if symbol in last_signal:

            if now - last_signal[symbol] < COOLDOWN:
                return

        last_signal[symbol] = now

        confidence = min(
            95,
            int(best_score * 7)
        )

        icon = "🟢"

        if direction == "SHORT":
            icon = "🔴"

        expected_move = "%1-3"

        if best_score >= 8:
            expected_move = "%3-6"

        if best_score >= 12:
            expected_move = "%5-10"

        reasons = []

        if vol_z > 2:
            reasons.append("Hacim Patlaması")

        if oi_change > 3:
            reasons.append("OI Yükselişi")

        if funding < -0.01 and direction == "LONG":
            reasons.append("Short Squeeze")

        if funding > 0.01 and direction == "SHORT":
            reasons.append("Long Squeeze")

        if compressed:
            reasons.append("Yatay Kırılım")

        if sweep_down and direction == "LONG":
            reasons.append("Dip Sweep")

        if sweep_up and direction == "SHORT":
            reasons.append("Tepe Sweep")

        if len(reasons) == 0:
            reasons.append("Momentum")

        reason_text = ""

        for r in reasons:
            reason_text += "• " + r + "\n"

        msg = (
            signal_type + "\n\n" +
            icon + " " + symbol + "\n\n" +
            "Yön: " + direction + "\n" +
            "Güven: %" + str(confidence) + "\n\n" +
            "Tahmini Hareket: " + expected_move + "\n\n" +
            "Sebep:\n" +
            reason_text
        )

        print(msg)

        await send_telegram(
            session,
            msg
        )

    except Exception as e:

        print("SCAN ERROR:", symbol, e)

# ==========================================
# MAIN
# ==========================================
async def main():

    print("🚀 BOT STARTED")

    async with aiohttp.ClientSession() as session:

        await send_telegram(
            session,
            "✅ BOT ONLINE"
        )

        while True:

            tasks = []

            for coin in COINS:

                tasks.append(
                    scan_coin(
                        session,
                        coin
                    )
                )

            await asyncio.gather(*tasks)

            await asyncio.sleep(
                SCAN_INTERVAL
            )

# ==========================================
# START
# ==========================================
if __name__ == "__main__":
    asyncio.run(main())
