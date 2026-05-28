import asyncio
import aiohttp
import os
import time
import logging
import traceback
from statistics import mean, stdev

# ==================================================
# CONFIG & GÜVENLİK
# ==================================================
BOT_TOKEN = os.getenv("BOT_TOKEN") 
CHAT_ID = os.getenv("CHAT_ID") 

# Binance Futures API (Sabah çalışan adres)
BASE_URL = "https://fapi.binance.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}

SCAN_INTERVAL = 40
COOLDOWN = 600
MAX_CONCURRENT_REQUESTS = 15

# Dinamik liste 451 hatası verdiği için sabahki sabit listeyi kullanıyoruz
COIN_LIST = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT"]

last_signal = {}

logging.basicConfig(level=logging.ERROR, filename='bot_errors.log')

# ==================================================
# TELEGRAM QUEUE
# ==================================================
telegram_queue = asyncio.Queue()

async def telegram_worker(session):
    while True:
        text = await telegram_queue.get()
        try:
            if BOT_TOKEN and CHAT_ID:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                await session.post(url, json={"chat_id": CHAT_ID, "text": text})
        except: pass
        finally: telegram_queue.task_done()
        await asyncio.sleep(0.5)

async def send_telegram(text):
    await telegram_queue.put(text)

# ==================================================
# FETCH ALTYAPISI
# ==================================================
async def fetch_json(session, endpoint, params=None):
    try:
        url = BASE_URL + endpoint
        async with session.get(url, params=params, headers=HEADERS, timeout=10) as resp:
            if resp.status == 200:
                return await resp.json()
    except: pass
    return None

# ==================================================
# İNDİKATÖRLER VE METRİKLER
# ==================================================
def atr(highs, lows, closes, period=14):
    if len(highs) < period + 1: return None
    tr = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(highs))]
    return mean(tr[-period:])

async def get_heavy_data(session, symbol):
    """Vadeli İşlem verileri: Fonlama ve OI (Open Interest)"""
    funding = 0.0; oi_change = 0.0
    f = await fetch_json(session, "/fapi/v1/premiumIndex", {"symbol": symbol})
    if f: funding = float(f.get("lastFundingRate", 0))
    
    oi = await fetch_json(session, "/futures/data/openInterestHist", {"symbol": symbol, "period": "5m", "limit": 2})
    if oi and len(oi) >= 2:
        prev = float(oi[-2]["sumOpenInterest"])
        curr = float(oi[-1]["sumOpenInterest"])
        if prev > 0: oi_change = (curr - prev) / prev * 100
        
    return funding, oi_change

async def check_7d_dip(session, symbol, current_price):
    """Acaba modu için 7 günlük dip seviyesi kontrolü"""
    kl = await fetch_json(session, "/fapi/v1/klines", {"symbol": symbol, "interval": "1d", "limit": 7})
    if not kl: return False
    lows = [float(k[3]) for k in kl]
    lowest_7d = min(lows)
    
    # Fiyat son 7 günün dibine %2 mesafedeyse bu bir "Dip/Toplanma" adayıdır
    if current_price <= lowest_7d * 1.02:
        return True
    return False

# ==================================================
# STRATEJİ MOTORU (ZIRHLI & ACABA)
# ==================================================
async def scan_coin(session, symbol, sem):
    async with sem:
        try:
            # 1. Temel Mum Verileri (5 Dakikalık)
            kl = await fetch_json(session, "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": 50})
            if not kl: return

            c = [float(k[4]) for k in kl]
            h = [float(k[2]) for k in kl]
            l = [float(k[3]) for k in kl]
            v = [float(k[5]) for k in kl]
            tb = [float(k[9]) for k in kl] # Taker buy volume

            last = kl[-2]
            open_p = float(last[1])
            close_p = float(last[4])
            vol = float(last[5])
            tbuy = float(last[9])
            
            change = (close_p - open_p) / open_p * 100
            
            # Hacim anomalisi kontrolü
            vm = mean(v)
            vol_spike = vol > (vm * 2.5) # Normalin 2.5 katı hacim
            taker_buy_ratio = tbuy / vol if vol > 0 else 0

            # Vadeli işlem ve Dip verilerini çek
            funding, oi_ch = await get_heavy_data(session, symbol)
            is_dip = await check_7d_dip(session, symbol, close_p)

            signal_type = None
            direction = None

            # --------------------------------------------------
            # 🛡️ ZIRHLI SİNYAL MANTIĞI (Yüksek Hacim, OI Artışı, Squeeze)
            # --------------------------------------------------
            if vol_spike and abs(change) > 1.0 and oi_ch > 2.0:
                if change > 0 and taker_buy_ratio > 0.6 and funding < 0:
                    signal_type = "🛡️ ZIRHLI SİNYAL"
                    direction = "LONG"
                elif change < 0 and taker_buy_ratio < 0.4 and funding > 0:
                    signal_type = "🛡️ ZIRHLI SİNYAL"
                    direction = "SHORT"

            # --------------------------------------------------
            # 🤔 ACABA MANTIĞI (Yatay Toplanma, Dip Yakalama)
            # --------------------------------------------------
            elif is_dip and vol_spike and change > 0.5:
                # Dipteyken aniden ufak bir hacim ve yeşil mum gelirse
                signal_type = "🤔 ACABA SİNYALİ (DİP/TOPLANMA)"
                direction = "LONG"

            # --------------------------------------------------
            # SİNYAL GÖNDERİMİ
            # --------------------------------------------------
            if signal_type:
                now = time.time()
                if symbol in last_signal and now - last_signal[symbol] < COOLDOWN:
                    return
                last_signal[symbol] = now

                atr_val = atr(h, l, c) or close_p * 0.005
                sl = close_p - atr_val * 1.5 if direction == "LONG" else close_p + atr_val * 1.5
                tp = close_p + atr_val * 2.0 if direction == "LONG" else close_p - atr_val * 2.0

                msg = f"{signal_type}\nCoin: #{symbol} | Yön: {direction}\nFiyat: {close_p}\nTP: {tp:.4f} | SL: {sl:.4f}\nOI Değişimi: %{oi_ch:.2f}"
                print(msg)
                await send_telegram(msg)

        except Exception as e:
            logging.error(f"SCAN {symbol}: {traceback.format_exc()}")

# ==================================================
# MAIN
# ==================================================
async def main():
    print("🚀 ZIRHLI & ACABA BOT BAŞLADI (Sabit Liste İle)")
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        asyncio.create_task(telegram_worker(session))
        await send_telegram("✅ BOT ONLINE: Zırhlı & Acaba Modları Aktif")
        
        sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        while True:
            tasks = [scan_coin(session, sym, sem) for sym in COIN_LIST]
            await asyncio.gather(*tasks)
            await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
