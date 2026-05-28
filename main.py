import asyncio
import aiohttp
import time
import os
from datetime import datetime
from statistics import mean, median

# =========================================================
# AYARLAR
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

COIN_LIST = [
    "BTCUSDT","ETHUSDT","SOLUSDT","DOGEUSDT","XRPUSDT","ADAUSDT",
    "AVAXUSDT","LINKUSDT","DOTUSDT","LTCUSDT","BCHUSDT","ATOMUSDT",
    "UNIUSDT","XLMUSDT","ALGOUSDT","VETUSDT","TRXUSDT","FILUSDT",
    "NEARUSDT","APTUSDT","ARBUSDT","OPUSDT","STXUSDT","RNDRUSDT",
    "SEIUSDT","WIFUSDT","SUIUSDT","TIAUSDT"
]

FAPI_URL = "https://fapi.binance.com"
SPOT_URL = "https://api.binance.com"

CACHE_DURATION = 180
COOLDOWN = 600
MAX_POSSIBLE_SCORE = 28  # Bu skor sistemindeki maksimum puan

SEMAPHORE = asyncio.Semaphore(15)  # Rate limit koruması

# =========================================================
# CACHE & HAFIZA
# =========================================================
cache = {"funding": {}, "atr": {}}
last_signals = {}
signal_memory = {}

# =========================================================
# TELEGRAM (COMPACT PROFESSIONAL ALERT)
# =========================================================
async def send_telegram(session, coin, signal_type):
    try:
        emoji = "🟢" if signal_type["direction"] == "LONG" else "🔴"
        squeeze_tag = "🔥 SQUEEZE " if signal_type.get("squeeze") else ""
        
        msg = (
            f"{emoji} *{squeeze_tag}{coin['symbol']} ({signal_type['direction']})*\n"
            f"⭐ Skor: {coin['score']} | Güven: %{coin['confidence']}\n"
            f"💵 Fiyat: {coin['price']} | %{coin['change']}\n"
            f"📊 OI: %{coin['oi']} | Funding: {coin['funding']}\n"
            f"📉 Delta: {coin['delta']} | RelVol: {coin['rel_vol']}\n"
            f"⚡ Trend: {coin['trend']} | Risk: {coin['risk']}"
        )
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        await session.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Telegram hatası: {e}")

# =========================================================
# API & CACHE & EMA & ATR (Senin yazdığın güzel fonksiyonlar)
# =========================================================
async def fetch(session, url_type, endpoint, params=None):
    base = FAPI_URL if url_type == "fapi" else SPOT_URL
    try:
        async with SEMAPHORE:
            async with session.get(f"{base}{endpoint}", params=params, timeout=10) as resp:
                if resp.status != 200: return None
                return await resp.json()
    except: return None

async def get_cached(session, cache_name, symbol, endpoint, params):
    now = time.time()
    if symbol in cache[cache_name]:
        item = cache[cache_name][symbol]
        if now - item["time"] < CACHE_DURATION: return item["data"]
    data = await fetch(session, "fapi", endpoint, params)
    if data: cache[cache_name][symbol] = {"time": now, "data": data}
    return data

def calculate_ema(prices, period):
    if len(prices) < period: return None
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]: ema = (p - ema) * multiplier + ema
    return ema

async def get_atr(session, symbol, period=14):
    now = time.time()
    if symbol in cache["atr"]:
        if now - cache["atr"][symbol]["time"] < 60:
            return cache["atr"][symbol]["data"]
    klines = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": period + 1})
    if not klines: return 0.001
    tr_values = []
    for i in range(1, len(klines)):
        high, low, prev_close = float(klines[i][2]), float(klines[i][3]), float(klines[i-1][4])
        tr_values.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    atr = mean(tr_values) if tr_values else 0.001
    cache["atr"][symbol] = {"time": now, "data": atr}
    return atr

# =========================================================
# BTC MARKET FILTER
# =========================================================
async def btc_market_safe(session):
    btc_klines = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "15m", "limit": 50})
    if not btc_klines: return False
    last = btc_klines[-2]
    change_pct = ((float(last[4]) - float(last[1])) / float(last[1])) * 100
    closes = [float(k[4]) for k in btc_klines]
    ema20, ema50 = calculate_ema(closes, 20), calculate_ema(closes, 50)
    if ema20 and ema50 and ema20 < ema50: print("⚠️ BTC Bearish Trend"); return False
    highs, lows = [float(k[2]) for k in btc_klines[-10:]], [float(k[3]) for k in btc_klines[-10:]]
    volatility = ((max(highs) - min(lows)) / min(lows)) * 100
    if change_pct < -2: print("⚠️ BTC Dump"); return False
    if volatility > 4: print("⚠️ BTC Volatility High"); return False
    ethbtc = await fetch(session, "spot", "/api/v3/klines", {"symbol": "ETHBTC", "interval": "15m", "limit": 2})
    if ethbtc:
        try:
            if ((float(ethbtc[-1][4]) - float(ethbtc[-1][1])) / float(ethbtc[-1][1])) * 100 < -0.8:
                print("⚠️ ETHBTC Weak"); return False
        except: pass
    return True

# =========================================================
# ORDERBOOK & TOP TRADER & RISK
# =========================================================
async def get_orderbook_bias(session, symbol):
    depth = await fetch(session, "fapi", "/fapi/v1/depth", {"symbol": symbol, "limit": 20})
    if not depth: return 0
    try:
        bids = sum(float(x[0]) * float(x[1]) for x in depth["bids"][:10])
        asks = sum(float(x[0]) * float(x[1]) for x in depth["asks"][:10])
        return bids / asks if asks > 0 else 0
    except: return 0

async def get_top_trader_bias(session, symbol):
    data = await fetch(session, "fapi", "/futures/data/topLongShortPositionRatio", {"symbol": symbol, "period": "5m", "limit": 2})
    if not data: return 0
    try: return float(data[-1]["longShortRatio"])
    except: return 0

def estimate_liquidation_risk(change_pct, oi_change):
    if abs(change_pct) > 3 and oi_change > 3: return "HIGH"
    if abs(change_pct) > 2 and oi_change > 1: return "MEDIUM"
    return "LOW"

# =========================================================
# SCAN COIN (WHALE & SQUEEZE LOGIC + CONFIDENCE DAHİL)
# =========================================================
async def scan_coin(session, symbol, market_median, min_score_atr):
    try:
        if symbol in last_signals and time.time() - last_signals[symbol] < COOLDOWN: return None
        kl_5m = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": 8})
        kl_1h = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": 30})
        kl_4h = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "4h", "limit": 55})
        kl_15m = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "15m", "limit": 6})
        if not kl_5m: return None

        last = kl_5m[-2]
        open_price, close_price, high, low, volume, taker_buy = float(last[1]), float(last[4]), float(last[2]), float(last[3]), float(last[5]), float(last[9])
        change_pct = ((close_price - open_price) / open_price) * 100
        taker_ratio = taker_buy / volume if volume > 0 else 0

        # RELATIVE VOLUME & SPEED
        prev_vols = [float(k[5]) for k in kl_5m[-6:-1]]
        avg_vol = mean(prev_vols)
        speed_ratio = volume / avg_vol if avg_vol > 0 else 0
        rel_vol = volume / market_median if market_median > 0 else 0

        # HEAVY CHECK
        heavy_check = speed_ratio > 1.3 or abs(change_pct) > 0.5 or rel_vol > 1.2

        # DELTA & WICK
        delta = taker_buy - (volume - taker_buy)
        delta_ratio = delta / volume if volume > 0 else 0
        wick_ratio = abs(close_price - open_price) / (high - low) if (high - low) > 0 else 0

        # EMA & STRUCTURE
        closes_1h = [float(k[4]) for k in kl_1h] if kl_1h else []
        closes_4h = [float(k[4]) for k in kl_4h] if kl_4h else []
        ema20_1h, ema50_4h = calculate_ema(closes_1h, 20), calculate_ema(closes_4h, 50)

        bullish_structure = bearish_structure = False
        if kl_15m and len(kl_15m) >= 4:
            h_list = [float(k[2]) for k in kl_15m[-4:]]
            l_list = [float(k[3]) for k in kl_15m[-4:]]
            if h_list[-1] > h_list[-2] and l_list[-1] > l_list[-2]: bullish_structure = True
            if h_list[-1] < h_list[-2] and l_list[-1] < l_list[-2]: bearish_structure = True

        # OI
        oi_change = 0
        if heavy_check:
            oi_data = await fetch(session, "fapi", "/fapi/v1/openInterestHist", {"symbol": symbol, "period": "5m", "limit": 2})
            if oi_data and len(oi_data) >= 2:
                prev_oi = float(oi_data[-2]["sumOpenInterestValue"])
                curr_oi = float(oi_data[-1]["sumOpenInterestValue"])
                if prev_oi > 0: oi_change = ((curr_oi - prev_oi) / prev_oi) * 100

        # FUNDING
        funding_rate = 0
        funding = await get_cached(session, "funding", symbol, "/fapi/v1/premiumIndex", {"symbol": symbol})
        if funding: funding_rate = float(funding.get("lastFundingRate", 0))

        # ORDERBOOK & TOP TRADER
        ob_ratio = await get_orderbook_bias(session, symbol) if heavy_check else 0
        top_ratio = await get_top_trader_bias(session, symbol) if heavy_check else 0

        # ATR NORMALIZATION
        atr_val = await get_atr(session, symbol)
        atr_percent = (atr_val / close_price) * 100 if close_price > 0 else 0
        normalized_change = change_pct / atr_percent if atr_percent > 0 else 0

        # ===== SKOR SİSTEMİ (WHALE & SQUEEZE LOGIC DAHİL) =====
        long_score, short_score = 0, 0
        squeeze = False

        if speed_ratio > 1.8: long_score += 2; short_score += 2
        if speed_ratio > 2.5: long_score += 1; short_score += 1
        if 0.8 < normalized_change < 5: long_score += 2
        if -5 < normalized_change < -0.8: short_score += 2
        if taker_ratio > 0.55: long_score += 2
        if taker_ratio < 0.45: short_score += 2
        if delta_ratio > 0.15: long_score += 2
        if delta_ratio < -0.15: short_score += 2
        if change_pct > 0: long_score += 1
        else: short_score += 1

        # WHALE MOMENTUM DETECTION (ANORMAL OI ARTIŞI veya TAKER BUY)
        if oi_change > 10: long_score += 3; short_score += 3
        if taker_ratio > 0.65: long_score += 2

        # FUNDING SQUEEZE LOGIC
        if funding_rate < -0.01 and oi_change > 5 and change_pct > 1:
            squeeze = True
            long_score += 3

        if oi_change > 1: long_score += 2; short_score += 2
        if funding_rate < 0: long_score += 1
        if ema20_1h and close_price > ema20_1h: long_score += 1
        if ema20_1h and close_price < ema20_1h: short_score += 1
        if ema50_4h and close_price > ema50_4h: long_score += 1
        if ema50_4h and close_price < ema50_4h: short_score += 1
        if bullish_structure: long_score += 2
        if bearish_structure: short_score += 2
        if rel_vol > 1.5: long_score += 2; short_score += 2
        if ob_ratio > 1.3: long_score += 1
        if ob_ratio < 0.7: short_score += 1
        if top_ratio > 1.1: long_score += 1
        if top_ratio < 0.9: short_score += 1
        if wick_ratio > 0.5: long_score -= 1; short_score -= 1

        # RESULT
        result = None
        if long_score >= min_score_atr:
            confidence = round((long_score / MAX_POSSIBLE_SCORE) * 100)
            result = {"symbol": symbol, "direction": "LONG", "score": long_score, "confidence": confidence,
                      "price": round(close_price, 4), "change": round(change_pct, 2), "oi": round(oi_change, 2),
                      "funding": round(funding_rate, 6), "delta": round(delta_ratio, 3), "rel_vol": round(rel_vol, 2),
                      "trend": "Bullish", "risk": estimate_liquidation_risk(change_pct, oi_change), "squeeze": squeeze}
        elif short_score >= min_score_atr:
            confidence = round((short_score / MAX_POSSIBLE_SCORE) * 100)
            result = {"symbol": symbol, "direction": "SHORT", "score": short_score, "confidence": confidence,
                      "price": round(close_price, 4), "change": round(change_pct, 2), "oi": round(oi_change, 2),
                      "funding": round(funding_rate, 6), "delta": round(delta_ratio, 3), "rel_vol": round(rel_vol, 2),
                      "trend": "Bearish", "risk": estimate_liquidation_risk(change_pct, oi_change), "squeeze": False} # Short squeeze var ama long için

        if result: last_signals[symbol] = time.time()
        return result
    except Exception as e:
        print(f"Hata ({symbol}): {e}")
        return None

# =========================================================
# MAIN (RAILWAY OPTIMIZED LOOP)
# =========================================================
async def main():
    print("🚀 ULTRA SCANNER (FINAL - ALL FEATURES) BAŞLATILDI")
    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            try:
                print(f"\n--- {datetime.now().strftime('%H:%M:%S')} ---")

                if not await btc_market_safe(session):
                    print("⚠️ Market unsafe")
                    await asyncio.sleep(30)
                    continue

                # CLEANUP
                now = time.time()
                for k in list(last_signals.keys()):
                    if now - last_signals[k] > 86400: del last_signals[k]
                for k in list(signal_memory.keys()):
                    if now - signal_memory[k]["time"] > 86400: del signal_memory[k]

                # MARKET MEDIAN
                tasks = [fetch(session, "fapi", "/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": 5}) for sym in COIN_LIST]
                responses = await asyncio.gather(*tasks)
                vols = [float(r[-1][5]) for r in responses if r]
                market_median = median(sorted(vols)[2:-2]) if len(vols) > 4 else median(vols) if vols else 1

                # BTC VOL (Adaptive Score)
                btc_klines = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "15m", "limit": 10})
                if btc_klines:
                    btc_vol = mean([(float(k[2]) - float(k[3])) / float(k[3]) for k in btc_klines]) * 100
                    if btc_vol < 1.0: min_score_atr = 5
                    elif btc_vol > 2.5: min_score_atr = 8
                    else: min_score_atr = 6
                else: min_score_atr = 6

                # SCAN
                results = [r for r in await asyncio.gather(*[scan_coin(session, sym, market_median, min_score_atr) for sym in COIN_LIST]) if r]
                results.sort(key=lambda x: x["score"], reverse=True)

                # TELEGRAM
                new_signals = []
                for coin in results[:3]:
                    sym = coin['symbol']
                    old_score = signal_memory.get(sym, {'score': 0, 'time': 0})['score']
                    if sym not in signal_memory or coin['score'] > old_score + 2:
                        new_signals.append(coin)
                        signal_memory[sym] = {'score': coin['score'], 'time': now}

                for coin in new_signals:
                    await send_telegram(session, coin, coin)
                    print(f"✅ Sinyal gönderildi: {coin['symbol']} (Puan: {coin['score']})")

                print(f"🔍 Toplam {len(results)} coin eşiği geçti (Min Score: {min_score_atr})")
                await asyncio.sleep(12)  # Railway optimized loop system

            except Exception as e:
                print(f"Kritik hata: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
