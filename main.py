import asyncio
import aiohttp
import time
from datetime import datetime
from statistics import mean, median

# =========================================================
# AYARLAR (Tokenlar direkt)
# =========================================================
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"

# TEST İÇİN SADECE BTCUSDT
COIN_LIST = ["BTCUSDT"]

FAPI_URL = "https://fapi.binance.com"
SPOT_URL = "https://api.binance.com"

CACHE_DURATION = 30
COOLDOWN = 30
MAX_POSSIBLE_SCORE = 28
SEMAPHORE = asyncio.Semaphore(15)

cache = {"funding": {}, "atr": {}}
last_signals = {}
signal_memory = {}

# =========================================================
# TELEGRAM
# =========================================================
async def send_telegram(session, coin, signal_type):
    try:
        emoji = "🟢" if signal_type["direction"] == "LONG" else "🔴"
        squeeze_tag = "🔥 SQUEEZE " if signal_type.get("squeeze") else ""
        msg = (f"{emoji} *{squeeze_tag}{coin['symbol']} ({signal_type['direction']})*\n"
               f"⭐ Skor: {coin['score']} | Güven: %{coin['confidence']}\n"
               f"💵 Fiyat: {coin['price']} | %{coin['change']}")
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        await session.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Telegram hatası: {e}")

# =========================================================
# API
# =========================================================
async def fetch(session, url_type, endpoint, params=None):
    base = FAPI_URL if url_type == "fapi" else SPOT_URL
    try:
        print(f"🔄 API isteği atılıyor: {endpoint} {params}")
        async with SEMAPHORE:
            async with session.get(f"{base}{endpoint}", params=params, timeout=10) as resp:
                if resp.status != 200:
                    print(f"⚠️ API Hatası: {resp.status}")
                    return None
                return await resp.json()
    except Exception as e:
        print(f"❌ API Bağlantı Hatası: {e}")
        return None

async def get_cached(session, cache_name, symbol, endpoint, params):
    now = time.time()
    if symbol in cache[cache_name] and now - cache[cache_name][symbol]["time"] < CACHE_DURATION:
        return cache[cache_name][symbol]["data"]
    data = await fetch(session, "fapi", endpoint, params)
    if data:
        cache[cache_name][symbol] = {"time": now, "data": data}
    return data

def calculate_ema(prices, period):
    if len(prices) < period: return None
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]: ema = (p - ema) * multiplier + ema
    return ema

async def get_atr(session, symbol, period=14):
    now = time.time()
    if symbol in cache["atr"] and now - cache["atr"][symbol]["time"] < 60:
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
# SCAN COIN (Basitleştirilmiş, sadece BTCUSDT)
# =========================================================
async def scan_coin(session, symbol, market_median, min_score_atr):
    try:
        print(f"\n🔍 Taranıyor: {symbol}")
        if symbol in last_signals and time.time() - last_signals[symbol] < COOLDOWN:
            print("  -> Cooldown'da")
            return None

        # KLİNES ÇEKME (5m, 1h, 4h, 15m)
        kl_5m = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": 8})
        if not kl_5m: print("  -> 5m verisi yok!"); return None
        print(f"  -> 5m verisi alındı, mum sayısı: {len(kl_5m)}")

        kl_1h = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": 30})
        if not kl_1h: print("  -> 1h verisi yok!"); return None

        kl_4h = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "4h", "limit": 55})
        if not kl_4h: print("  -> 4h verisi yok!"); return None

        kl_15m = await fetch(session, "fapi", "/fapi/v1/klines", {"symbol": symbol, "interval": "15m", "limit": 6})
        if not kl_15m: print("  -> 15m verisi yok!"); return None

        # BURAYA KADAR GELDİYSE VERİ VAR DEMEKTİR
        print("✅ Tüm veriler alındı!")

        # Basit bir skor hesapla (Test için)
        last = kl_5m[-2]
        close_price = float(last[4])
        volume = float(last[5])
        taker_buy = float(last[9])
        change_pct = ((float(last[4]) - float(last[1])) / float(last[1])) * 100
        taker_ratio = taker_buy / volume if volume > 0 else 0

        # Skor (TEST - Çok düşük eşik)
        score = 0
        if taker_ratio > 0.50: score += 3
        if volume > 1000000: score += 2

        print(f"  -> Hesaplanan Skor: {score}")

        # EŞİK (TEST İÇİN 2)
        if score >= 2: # min_score_atr'yi 2 olarak varsay
            print("🎯 Eşik geçildi!")
            result = {"symbol": symbol, "direction": "LONG", "score": score, "confidence": 80,
                      "price": round(close_price, 4), "change": round(change_pct, 2), "oi": 0,
                      "funding": 0, "delta": 0, "rel_vol": 0, "trend": "Bullish", "risk": "LOW", "squeeze": False}
            return result
        else:
            print("  -> Skor eşiği geçemedi.")
            return None

    except Exception as e:
        print(f"❌ Scan coin hatası ({symbol}): {e}")
        return None

# =========================================================
# MAIN
# =========================================================
async def main():
    print("🚀 TEST MODU BAŞLATILDI (SADCE BTCUSDT)")
    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            try:
                print(f"\n--- {datetime.now().strftime('%H:%M:%S')} ---")

                # MARKET MEDIAN
                tasks = [fetch(session, "fapi", "/fapi/v1/klines", {"symbol": sym, "interval": "5m", "limit": 5}) for sym in COIN_LIST]
                responses = await asyncio.gather(*tasks)
                vols = [float(r[-1][5]) for r in responses if r]
                market_median = median(vols) if vols else 1

                # SCAN
                results = [r for r in await asyncio.gather(*[scan_coin(session, sym, market_median, 2) for sym in COIN_LIST]) if r]
                
                if results:
                    print(f"\n✅ BULUNDU! {results}")
                    await send_telegram(session, results[0], results[0])
                else:
                    print("\n❌ Sonuç yok.")

                await asyncio.sleep(12)

            except Exception as e:
                print(f"Kritik hata: {e}")
                await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
