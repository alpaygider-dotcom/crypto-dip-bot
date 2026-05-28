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
    "SUIUSDT",
    "ARBUSDT",
    "OPUSDT",
    "TIAUSDT",
    "RNDRUSDT"
]

INTERVAL = "5m"

SCAN_INTERVAL = 40
COOLDOWN = 600

last_signal = {}

# ==================================================
# TELEGRAM
# ==================================================
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

# ==================================================
# FETCH
# ==================================================
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

# ==================================================
# EMA
# ==================================================
def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema_value = mean(values[:period])

    for price in values[period:]:
        ema_value = (
            (price - ema_value) * multiplier
        ) + ema_value

    return ema_value

# ==================================================
# BTC FILTER
# ==================================================
async def get_btc_bias(session):

    klines = await fetch_json(
        session,
        "/fapi/v1/klines",
        {
            "symbol": "BTCUSDT",
            "interval": "15m",
            "limit": 50
        }
    )

    if not klines:
        return "NEUTRAL"

    closes = []

    for k in klines:
        closes.append(float(k[4]))

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    last_price = closes[-1]

    if ema20 and ema50:

        if last_price > ema20 and ema20 > ema50:
            return "BULLISH"

        if last_price < ema20 and ema20 < ema50:
            return "BEARISH"

    return "NEUTRAL"

# ==================================================
# REGIME
# ==================================================
def detect_regime(closes, volumes):

    move = (
        closes[-1] - closes[0]
    ) / closes[0]

    vol_mean = mean(volumes)

    if len(volumes) > 1:
        vol_std = stdev(volumes)
    else:
        vol_std = 0

    vol_z = 0

    if vol_std > 0:
        vol_z = (
            volumes[-1] - vol_mean
        ) / vol_std

    if abs(move) < 0.004:
        return "RANGE"

    if abs(move) > 0.012 and vol_z > 1:
        return "TREND"

    return "MIXED"

# ==================================================
# SWEEP
# ==================================================
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

# ==================================================
# SIDEWAYS BREAKOUT
# ==================================================
def sideways_breakout(closes):

    recent = closes[-15:]

    highest = max(recent)
    lowest = min(recent)

    range_pct = (
        (highest - lowest)
        / lowest
    ) * 100

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

# ==================================================
# ORDERFLOW
# ==================================================
def orderflow_strength(volume, taker_buy):

    if volume <= 0:
        return 0

    taker_ratio = taker_buy / volume

    delta = taker_buy - (
        volume - taker_buy
    )

    delta_ratio = delta / volume

    score = 0

    if taker_ratio > 0.62:
        score += 2

    if taker_ratio < 0.38:
        score -= 2

    if delta_ratio > 0.18:
        score += 2

    if delta_ratio < -0.18:
        score -= 2

    return score

# ==================================================
# HEAVY DATA
# ==================================================
async def get_heavy_data(session, symbol):

    funding = 0
    oi_change = 0
    long_short = 1

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

# ==================================================
# SIGNAL CLASS
# ==================================================
def classify_signal(score):

    if score >= 13:
        return "🔥 GÜÇLÜ AL"

    if score >= 8:
        return "🟡 ORTA AL"

    if score >= 5:
        return "🟢 AZ AL"

    return None

# ==================================================
# SCAN
# ==================================================
async def scan_coin(session, symbol, btc_bias):

    try:

        klines_5m = await fetch_json(
            session,
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": "5m",
                "limit": 80
            }
        )

        klines_1h = await fetch_json(
            session,
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": "1h",
                "limit": 80
            }
        )

        if not klines_5m:
            return

        closes = []
        highs = []
        lows = []
        volumes = []

        for k in klines_5m:

            closes.append(float(k[4]))
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            volumes.append(float(k[5]))

        last = klines_5m[-2]

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

        # GEVŞETİLMİŞ AZ AL FİLTRESİ
        if abs(change) < 0.25 and vol_z < 0.8:
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

        orderflow = orderflow_strength(
            volume,
            taker_buy
        )

        # ======================================
        # MULTI TIMEFRAME
        # ======================================
        trend_bonus_long = 0
        trend_bonus_short = 0

        if klines_1h:

            closes_1h = []

            for k in klines_1h:
                closes_1h.append(float(k[4]))

            ema20_1h = ema(closes_1h, 20)
            ema50_1h = ema(closes_1h, 50)

            last_1h = closes_1h[-1]

            if ema20_1h and ema50_1h:

                if last_1h > ema20_1h and ema20_1h > ema50_1h:
                    trend_bonus_long += 3

                if last_1h < ema20_1h and ema20_1h < ema50_1h:
                    trend_bonus_short += 3

        # ======================================
        # SCORE
        # ======================================
        long_score = 0
        short_score = 0

        # PRICE MOMENTUM
        if change > 1:
            long_score += 2

        if change < -1:
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
        if oi_change > 4:
            long_score += 3
            short_score += 3

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

        # ORDERFLOW
        if orderflow > 0:
            long_score += orderflow

        if orderflow < 0:
            short_score += abs(orderflow)

        # MULTI TF
        long_score += trend_bonus_long
        short_score += trend_bonus_short

        # BTC FILTER
        if btc_bias == "BULLISH":
            long_score += 2
            short_score -= 1

        if btc_bias == "BEARISH":
            short_score += 2
            long_score -= 1

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

        # BTC KORUMA
        if btc_bias == "BULLISH" and direction == "SHORT":
            if best_score < 11:
                return

        if btc_bias == "BEARISH" and direction == "LONG":
            if best_score < 11:
                return

        now = time.time()

        if symbol in last_signal:

            if now - last_signal[symbol] < COOLDOWN:
                return

        last_signal[symbol] = now

        confidence = min(
            95,
            int(best_score * 6)
        )

        icon = "🟢"

        if direction == "SHORT":
            icon = "🔴"

        expected_move = "%1-3"

        if best_score >= 8:
            expected_move = "%3-6"

        if best_score >= 13:
            expected_move = "%5-10"

        reasons = []

        if vol_z > 2:
            reasons.append("Hacim Patlaması")

        if oi_change > 4:
            reasons.append("OI Yükselişi")

        if compressed:
            reasons.append("Yatay Kırılım")

        if sweep_down and direction == "LONG":
            reasons.append("Dip Sweep")

        if sweep_up and direction == "SHORT":
            reasons.append("Tepe Sweep")

        if funding < -0.01 and direction == "LONG":
            reasons.append("Short Squeeze")

        if funding > 0.01 and direction == "SHORT":
            reasons.append("Long Squeeze")

        if trend_bonus_long > 0 and direction == "LONG":
            reasons.append("1H Trend Güçlü")

        if trend_bonus_short > 0 and direction == "SHORT":
            reasons.append("1H Trend Güçlü")

        if btc_bias == "BULLISH":
            reasons.append("BTC Güçlü")

        if btc_bias == "BEARISH":
            reasons.append("BTC Zayıf")

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

# ==================================================
# MAIN
# ==================================================
async def main():

    print("🚀 PROFESSIONAL BOT STARTED")

    async with aiohttp.ClientSession() as session:

        await send_telegram(
            session,
            "✅ PROFESSIONAL BOT ONLINE"
        )

        while True:

            btc_bias = await get_btc_bias(
                session
            )

            tasks = []

            for coin in COINS:

                tasks.append(
                    scan_coin(
                        session,
                        coin,
                        btc_bias
                    )
                )

            await asyncio.gather(*tasks)

            await asyncio.sleep(
                SCAN_INTERVAL
            )

# ==================================================
# START
# ==================================================
if __name__ == "__main__":
    asyncio.run(main())
