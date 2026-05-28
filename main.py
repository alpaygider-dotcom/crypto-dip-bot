import asyncio
import aiohttp
import os
import time
import logging
import traceback
from statistics import mean, stdev

# ==================================================
# CONFIG
# ==================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY")

# 🚨 DİKKAT: Futures API adresi mutlaka bu olmalı
BASE_URL = "https://fapi.binance.com"

SCAN_INTERVAL = 40
COOLDOWN = 600
MAX_CONCURRENT_REQUESTS = 15 # İstek limitini korumak için düşürüldü

last_signal = {}
trading_paused = False
weights = {"trend": 1.0, "volume": 1.0, "breakout": 1.0, "whale": 1.0, "regime": 1.0}

logging.basicConfig(level=logging.ERROR, filename='bot.log')

# ==================================================
# TELEGRAM QUEUE
# ==================================================
telegram_queue = asyncio.Queue(maxsize=50)

async def telegram_worker(session):
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

async def send_telegram(text):
    try: await telegram_queue.put(text)
    except: pass

# ==================================================
# FETCH (GÜNCEL)
# ==================================================
async def fetch_json(session, endpoint, params=None):
    try:
        async with session.get(BASE_URL + endpoint, params=params, timeout=8) as resp:
            if resp.status == 200: return await resp.json()
    except: return None
    return None

# ==================================================
# INDICATORS (Kısaltılmış)
# ==================================================
def ema(values, p):
    if len(values) < p: return None
    m = 2/(p+1); e = mean(values[:p])
    for x in values[p:]: e = (x-e)*m + e
    return e

def atr(h, l, c, p=14):
    if len(h) < p+1: return None
    tr = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(h))]
    return mean(tr[-p:])

# ==================================================
# SCAN & ENGINE (TÜM MANTIK)
# ==================================================
async def scan_coin(session, symbol, btc_bias, sem):
    global trading_paused
    async with sem:
        try:
            kl = await fetch_json(session, "/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": 50})
            if not kl: return

            c = [float(k[4]) for k in kl]; h = [float(k[2]) for k in kl]
            l = [float(k[3]) for k in kl]; v = [float(k[5]) for k in kl]
            
            last = kl[-2]
            change = (float(last[4]) - float(last[1])) / float(last[1]) * 100
            
            # Basit Skorlama
            long = short = 0
            if change > 1.5: long += 5
            elif change < -1.5: short += 5
            
            best = max(long, short)
            if best < 5: return

            direction = "LONG" if long > short else "SHORT"
            
            # Sinyal Gönderimi
            if symbol not in last_signal or time.time() - last_signal[symbol] > COOLDOWN:
                last_signal[symbol] = time.time()
                await send_telegram(f"🚀 {symbol} {direction} Sinyali! %{change:.2f}")

        except Exception as e:
            logging.error(f"Hata {symbol}: {e}")

async def get_all_symbols(session):
    data = await fetch_json(session, "/fapi/v1/exchangeInfo")
    if not data: return ["BTCUSDT", "ETHUSDT", "SOLUSDT"] # Fallback
    return [s["symbol"] for s in data["symbols"] if s["quoteAsset"] == "USDT"]

# ==================================================
# MAIN
# ==================================================
async def main():
    print("🚀 BOT BAŞLADI - FAPI AKTİF")
    async with aiohttp.ClientSession() as session:
        asyncio.create_task(telegram_worker(session))
        sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        while True:
            syms = await get_all_symbols(session)
            bias = "NEUTRAL" # Basitleştirildi
            
            tasks = [scan_coin(session, s, bias, sem) for s in syms]
            await asyncio.gather(*tasks)
            await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
