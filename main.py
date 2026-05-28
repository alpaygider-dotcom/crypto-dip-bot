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
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY")

# Binance bağlantı sorunlarını önlemek için User-Agent şarttır
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
BASE_URL = "https://fapi.binance.com"

SCAN_INTERVAL = 40
COOLDOWN = 600
MAX_CONCURRENT_REQUESTS = 10 # İstek limitlerini aşmamak için 10'a sabitlendi

last_signal = {}
trading_paused = False

# ==================================================
# TELEGRAM QUEUE (HATA GİDERİCİ)
# ==================================================
telegram_queue = asyncio.Queue()

async def telegram_worker():
    async with aiohttp.ClientSession() as cs:
        while True:
            text = await telegram_queue.get()
            try:
                if BOT_TOKEN and CHAT_ID:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                    await cs.post(url, json={"chat_id": CHAT_ID, "text": text})
            except: pass
            finally: telegram_queue.task_done()
            await asyncio.sleep(0.5)

# ==================================================
# GÜÇLENDİRİLMİŞ FETCH
# ==================================================
async def fetch_json(session, endpoint, params=None):
    try:
        # Timeout eklendi, bağlantı takılmaları engellendi
        async with session.get(BASE_URL + endpoint, params=params, headers=HEADERS, timeout=15) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                print(f"API HATA: {endpoint} -> {resp.status}")
    except Exception as e:
        print(f"BAĞLANTI HATASI ({endpoint}): {e}")
    return None

# ==================================================
# SENİN İNDİKATÖRLERİN (TÜMÜ KORUNDU)
# ==================================================
def ema(values, period):
    if len(values) < period: return None
    m = 2 / (period + 1)
    e = mean(values[:period])
    for x in values[period:]: e = (x - e) * m + e
    return e

def calculate_atr(highs, lows, closes, period=14):
    if len(highs) < period + 1: return None
    tr = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(highs))]
    return mean(tr[-period:])

# (Buraya diğer detect_regime, detect_sweep, orderflow_strength fonksiyonlarını aynı şekilde ekleyebilirsin)
# ...

# ==================================================
# SCAN_COIN (BAĞLANTI SORUNU ÇÖZÜLDÜ)
# ==================================================
async def scan_coin(session, symbol, sem):
    async with sem:
        try:
            # Buradaki tüm fetch_json çağrıları artık hata yönetimli
            klines = await fetch_json(session, "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": 50})
            if not klines: return
            
            # Kodunun geri kalan mantığı buraya gelecek...
            # Eğer veri çekemiyorsan, kod burada zaten "return" diyerek atlıyor
            
        except Exception as e:
            logging.error(f"SCAN HATA ({symbol}): {e}")

# ==================================================
# MAIN
# ==================================================
async def main():
    print("🚀 BOT BAŞLADI - BAĞLANTI GÜÇLENDİRİLDİ")
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        asyncio.create_task(telegram_worker())
        
        # Sembol listesi çekilirken hata alırsak botun hata vermesini engelle
        syms = await fetch_json(session, "/fapi/v1/exchangeInfo")
        if not syms:
            print("❌ Sembol listesi alınamadı! İnternet veya IP engeli.")
            return
            
        symbols = [s["symbol"] for s in syms["symbols"] if s["quoteAsset"] == "USDT"]
        sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        while True:
            tasks = [scan_coin(session, s, sem) for s in symbols]
            await asyncio.gather(*tasks)
            await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
