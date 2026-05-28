import asyncio
import aiohttp
import time
from datetime import datetime
from statistics import mean, median
from collections import defaultdict

# ==============================================================================
# AYARLAR (Sabah Sorunsuz Çalışan Spot API Altyapısı)
# ==============================================================================
BOT_TOKEN = "8728951395:AAHLiGnGKxddfAJFk..." # Kendi Telegram Token'ın
CHAT_ID = "6637406398"                         # Kendi Chat ID'n

# Railway IP engeline takılmayan güvenli Spot API adresi
BASE_URL = "https://api.binance.com"

# Görselde botun yakaladığı ve takip ettiğin güncel coin listesi
COIN_LIST = [
    "BTCUSDT", "ETHUSDT", "ICXUSDT", "PARTIUSDT", "SXTUSDT", 
    "OPENUSDT", "DOGSUSDT", "PLUMEUSDT", "USDEUSDT", "APTUSDT"
]

SCAN_INTERVAL = 40  # Kaç saniyede bir tarama yapacağı
COOLDOWN = 300      # Aynı coine üst üste sinyal atmaması için beklenecek süre (5 dakika)

# Sinyal sürelerini hafızada tutmak için
last_signal = {}

# ==============================================================================
# TELEGRAM MESAJ SIRA SİSTEMİ (Arka Arkaya Sinyallerde Donmayı Önler)
# ==============================================================================
telegram_queue = asyncio.Queue()

async def telegram_worker(session):
    while True:
        text = await telegram_queue.get()
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            await session.post(url, json={"chat_id": CHAT_ID, "text": text})
        except Exception as e:
            print(f"❌ Telegram Gönderim Hatası: {e}")
        finally:
            telegram_queue.task_done()
        await asyncio.sleep(0.5)

async def send_telegram(text):
    await telegram_queue.put(text)

# ==============================================================================
# API VERİ ÇEKME FONKSİYONU
# ==============================================================================
async def fetch_json(session, endpoint, params=None):
    try:
        async with session.get(BASE_URL + endpoint, params=params, timeout=10) as resp:
            if resp.status == 200:
                return await resp.json()
    except:
        pass
    return None

# ==============================================================================
# COIN TARAMA VE STRATEJİ MOTORU
# ==============================================================================
async def scan_coin(session, symbol, btc_change, sem):
    async with sem:
        try:
            # ⏱️ Hızlı sinyal yakalamak için 1 dakikalık mumları (1m) sorguluyoruz
            kl = await fetch_json(session, "/api/v3/klines", {"symbol": symbol, "interval": "1m", "limit": 50})
            if not kl: 
                return
            
            c = [float(k[4]) for k in kl]  # Kapanış fiyatları
            v = [float(k[5]) for k in kl]  # Hacim verileri
            
            close_p = c[-1]
            vol = v[-1]
            
            # Geçmiş mumların ortalama hacmini hesapla (Son mum hariç)
            vm = mean(v[:-1]) if len(v) > 1 else 1
            
            # Telegram'daki "Hacim Patlaması: X" katı hesabı
            vol_multiplier = vol / vm if vm > 0 else 0
            
            # 🔍 CANLI LOG: Botun çalıştığını terminalde görmek için
            print(f"🔄 Taranıyor: {symbol.ljust(9)} | Hacim: {vol_multiplier:.2f}x | Fiyat: {close_p}")
            
            # Fiyat değişim hesapları (Formasyon tespiti için)
            coin_change = (close_p - c[0]) / c[0] * 100
            
            # 1. Kriter: BTC'den Bağımsız Hareket (BTC'ye göre daha sert hareket)
            is_independent = abs(coin_change) > abs(btc_change) * 1.2
            
            # 2. Kriter: Dipte Yataydan Çıkış (Son 20 muma göre dip tespiti)
            lowest_recent = min(c[-20:])
            is_dip_breakout = close_p > lowest_recent * 1.005
            
            now = time.time()

            # --------------------------------------------------
            # 🤔 ACABA? SİNYAL MANTIĞI (Hacim Patlaması + Dip Kırılımı)
            # --------------------------------------------------
            if vol_multiplier > 2.0 and is_dip_breakout and is_independent:
                if symbol in last_signal and now - last_signal[symbol] < COOLDOWN:
                    return
                last_signal[symbol] = now
                
                msg = (
                    f"🤔 ACABA? #{symbol}\n"
                    f"• Hacim Patlaması: {vol_multiplier:.1f}x\n"
                    f"• Formasyon: Dipte Yataydan Çıkış\n"
                    f"• Veri: BTC'den Bağımsız Hareket"
                )
                await send_telegram(msg)
                
            # 🤔 ACABA? (Sadece Hacim Güçleniyor Durumu)
            elif vol_multiplier >= 2.0:
                if symbol in last_signal and now - last_signal[symbol] < COOLDOWN:
                    return
                last_signal[symbol] = now
                
                msg = (
                    f"🤔 ACABA? #{symbol}\n"
                    f"• Hacim: {vol_multiplier:.1f}x\n"
                    f"• Durum: Hacim Güçleniyor, Takibe Al!"
                )
                await send_telegram(msg)

            # --------------------------------------------------
            # 💎 ZIRHLI SİNYAL MANTIĞI (Olağanüstü Hacim ve Fiyat Artışı)
            # --------------------------------------------------
            if vol_multiplier > 5.0 and coin_change > 1.5:
                if symbol in last_signal and now - last_signal[symbol] < COOLDOWN:
                    return
                last_signal[symbol] = now
                
                msg = (
                    f"💎 ZIRHLI SİNYAL! #{symbol}\n"
                    f"• Durum: Olağanüstü Hacim Patlaması!"
                )
                await send_telegram(msg)

        except Exception as e:
            print(f"⚠️ {symbol} taranırken hata: {e}")

# ==============================================================================
# ANA DÖNGÜ (MAIN)
# ==============================================================================
async def main():
    print(f"🚀 HİBRİT BOT BAŞLATILDI ({BASE_URL})")
    print("--------------------------------------------------")
    
    async with aiohttp.ClientSession() as session:
        # Arka planda Telegram kuyruğunu çalıştır
        asyncio.create_task(telegram_worker(session))
        await send_telegram("✅ BOT ONLINE: Dip Hunter Aktif (Spot Altyapısı)")
        
        # Eşzamanlı istek sınırlandırıcı (Semafor)
        sem = asyncio.Semaphore(15)

        while True:
            # Korelasyon hesabı için önce BTC'nin son durumunu çekiyoruz
            btc_kl = await fetch_json(session, "/api/v3/klines", {"symbol": "BTCUSDT", "interval": "1m", "limit": 50})
            btc_change = 0
            if btc_kl:
                btc_c = [float(k[4]) for k in btc_kl]
                btc_change = (btc_c[-1] - btc_c[0]) / btc_c[0] * 100

            # Tüm coin listesini eşzamanlı olarak tara
            tasks = [scan_coin(session, sym, btc_change, sem) for sym in COIN_LIST]
            await asyncio.gather(*tasks)
            
            print("--------------------------------------------------")
            await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
