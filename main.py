import requests
import time
from statistics import mean

BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

def get_pairs():
    res = requests.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo").json()
    return [s["symbol"] for s in res["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]

def get_klines(symbol, limit):
    return requests.get(f"{BINANCE_SPOT}/api/v3/klines", params={"symbol": symbol, "interval": "5m", "limit": limit}).json()

def check_zırhlı_tam(symbol, klines):
    # 1. Filtre: Hacim Patlaması (2.3x)
    volumes = [float(k[5]) for k in klines]
    if mean(volumes[:-2]) == 0: return False
    ratio = volumes[-1] / mean(volumes[:-2])
    
    # 2. Filtre: Fiyat aşırı şişmemiş mi? (Son 20dk değişim < %5)
    closes = [float(k[4]) for k in klines]
    pump_check = ((closes[-1] - closes[-4]) / closes[-4]) < 0.05
    
    # 3. Filtre: 10M$ Hacim şartı (24 saatlik)
    ticker = requests.get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", params={"symbol": symbol}).json()
    daily_vol = float(ticker.get("quoteVolume", 0))
    
    return ratio > 2.3 and pump_check and daily_vol > 10000000

def check_acaba_onaylı(symbol):
    # OI (Açık Pozisyon) kontrolü - Sadece Futures için
    try:
        oi = requests.get(f"{BINANCE_FUTURES}/futures/data/openInterestHist", params={"symbol": symbol, "period": "5m", "limit": 2}).json()
        if len(oi) >= 2 and float(oi[1]["sumOpenInterest"]) > float(oi[0]["sumOpenInterest"]):
            return "✅ ONAYLI (Balina girişi)"
        return "⚠️ ONAYLANMADI"
    except: return "❓ OI Verisi Yok"

def main():
    sent_dict = {}
    print("🚀 GÜÇLENDİRİLMİŞ TARAMA BAŞLADI...")
    
    while True:
        pairs = get_pairs()
        for symbol in pairs:
            try:
                klines = get_klines(symbol, 20)
                if len(klines) < 20: continue
                
                # ZIRHLI SİNYALİ
                if check_zırhlı_tam(symbol, klines):
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\nKurallar tamam: 2.3x Hacim + 10M$ Likidite.")
                        sent_dict[symbol] = time.time()
                
                # ACABA SİNYALİ
                else:
                    volumes = [float(k[5]) for k in klines]
                    ratio = volumes[-1] / mean(volumes[:-2])
                    if ratio > 1.5:
                        if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 1800):
                            conf = check_acaba_onaylı(symbol)
                            send_telegram(f"🤔 *ACABA?* #{symbol}\n• Hacim: {round(ratio,1)}x\n• Analiz: {conf}")
                            sent_dict[symbol] = time.time()
            except: continue
        time.sleep(180)

if __name__ == "__main__":
    main()
