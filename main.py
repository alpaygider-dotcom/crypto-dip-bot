import asyncio
import aiohttp
import time
from datetime import datetime
from statistics import mean, median
from collections import defaultdict

# ==============================================================================
# AYARLAR (Sabahki Çalışan Spot Piyasası)
# ==============================================================================
BOT_TOKEN = "8728951395:AAHLiGnGKxddfAJFk..." # Kendi token'ın
CHAT_ID = "6637406398"

# Sabah sorunsuz veri çekmeni sağlayan SPOT API adresi
BASE_URL = "https://api.binance.com"

# Görselde botun yakaladığı altcoinlerin de olduğu liste
COIN_LIST = ["BTCUSDT", "ETHUSDT", "ICXUSDT", "PARTIUSDT", "SXTUSDT", "OPENUSDT", "DOGSUSDT", "PLUMEUSDT", "USDEUSDT", "APTUSDT"]

telegram_queue = asyncio.Queue()

async def telegram_worker(session):
    while True:
        text = await telegram_queue.get()
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            await session.post(url, json={"chat_id": CHAT_ID, "text": text})
        except: pass
        finally: telegram_queue.task_done()
        await asyncio.sleep(0.5)

async def send_telegram(text):
    await telegram_queue.put(text)

async def fetch_json(session, endpoint, params=None):
    try:
        async with session.get(BASE_URL + endpoint, params=params, timeout=10) as resp:
            if resp.status == 200:
                return await resp.json()
    except: pass
    return None

# ==============================================================================
# DİP & HACİM İNDİKATÖRÜ (Sabahki Mantık)
# ==============================================================================
async def scan_coin(session, symbol, btc_change, sem):
    async with sem:
        try:
            # SPOT üzerinden mum verisi çekimi
            kl = await fetch_json(session, "/api/v3/klines", {"symbol": symbol, "interval": "15m", "limit": 50})
            if not kl: return
            
            c = [float(k[4]) for k in kl]
            v = [float(k[5]) for k in kl]
            
            close_p = c[-1]
            vol = v[-1]
            vm = mean(v[:-1]) if len(v) > 1 else 1
            
            # Telegram'daki "Hacim Patlaması: X" mantığı
            vol_multiplier = vol / vm if vm > 0 else 0
            
            # Telegram'daki "Formasyon ve Veri" kontrolleri
            coin_change = (close_p - c[0]) / c[0] * 100
            is_independent = abs(coin_change) > abs(btc_change) * 1.5  # BTC'den Bağımsız Hareket
            
            lowest_recent = min(c[-20:])
            is_dip_breakout = close_p > lowest_recent * 1.01 and c[-2] <= lowest_recent * 1.03 # Dipte Yataydan Çıkış
            
            # --------------------------------------------------
            # SİNYAL ÇIKTILARI (Görseldeki Birebir Format)
            # --------------------------------------------------
            if vol_multiplier > 3.0 and is_dip_breakout and is_independent:
                msg = (
                    f"🤔 ACABA? #{symbol}\n"
                    f"• Hacim Patlaması: {vol_multiplier:.1f}x\n"
                    f"• Formasyon: Dipte Yataydan Çıkış\n"
                    f"• Veri: BTC'den Bağımsız Hareket"
                )
                print(msg)
                await send_telegram(msg)
                
            elif vol_multiplier >= 3.0 and not is_dip_breakout:
                msg = (
                    f"🤔 ACABA? #{symbol}\n"
                    f"• Hacim: {vol_multiplier:.1f}x\n"
                    f"• Durum: Hacim Güçleniyor, Takibe Al!"
                )
                print(msg)
                await send_telegram(msg)

            # Görselin en altındaki Zırhlı sinyali
            if vol_multiplier > 8.0 and coin_change > 3.0:
                msg = f"💎 ZIRHLI SİNYAL! #{symbol}\n• Durum: Olağanüstü Hacim Patlaması!"
                await send_telegram(msg)

        except Exception as e:
            pass

async def main():
    print(f"🚀 HİBRİT BOT ({BASE_URL})")
    async with aiohttp.ClientSession() as session:
        asyncio.create_task(telegram_worker(session))
        sem = asyncio.Semaphore(15)

        while True:
            # Basit BTC değişimi (Korelasyon için)
            btc_kl = await fetch_json(session, "/api/v3/klines", {"symbol": "BTCUSDT", "interval": "15m", "limit": 50})
            btc_change = 0
            if btc_kl:
                btc_c = [float(k[4]) for k in btc_kl]
                btc_change = (btc_c[-1] - btc_c[0]) / btc_c[0] * 100

            tasks = [scan_coin(session, sym, btc_change, sem) for sym in COIN_LIST]
            await asyncio.gather(*tasks)
            await asyncio.sleep(40)

if __name__ == "__main__":
    asyncio.run(main())
