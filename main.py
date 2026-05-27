import requests
import time
from statistics import mean

# CREDENTIALS
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_FUTURES = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

# FİLTRELER
MIN_DAILY_VOLUME = 10000000 
VOLUME_BOOM_THRESHOLD = 2.3

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try: requests.post(url, data=data)
    except: pass

def get_futures_pairs():
    try:
        url = f"{BINANCE_FUTURES}/fapi/v1/exchangeInfo"
        res = requests.get(url).json()
        return [s["symbol"] for s in res["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]
    except: return []

def get_klines(symbol, interval, limit, is_futures=True):
    try:
        base = BINANCE_FUTURES if is_futures else BINANCE_SPOT
        endpoint = "/fapi/v1/klines" if is_futures else "/api/v3/klines"
        url = f"{base}{endpoint}"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return requests.get(url, params=params).json()
    except: return []

def check_acaba_confirmation(symbol):
    try:
        oi_url = f"{BINANCE_FUTURES}/futures/data/openInterestHist"
        oi_res = requests.get(oi_url, params={"symbol": symbol, "period": "5m", "limit": 2}).json()
        if len(oi_res) >= 2:
            if float(oi_res[1]["sumOpenInterest"]) > float(oi_res[0]["sumOpenInterest"]):
                return "✅ ONAYLI (OI Artışı: Balina girişi)"
            return "⚠️ ONAYLANMADI (Hacim var ama OI zayıf)"
        return "❓ BELİRSİZ"
    except: return "❌ ANALİZ EDİLEMEDİ"

def analyze_acaba(symbol):
    try:
        klines = get_klines(symbol, "5m", 20, True)
        if len(klines) < 20: return None
        volumes = [float(k[5]) for k in klines]
        ratio = volumes[-1] / mean(volumes[:-2])
        closes = [float(k[4]) for k in klines]
        price_change = ((closes[-1] - closes[-4]) / closes[-4]) * 100
        
        if ratio > 2.5 and -2.0 < price_change < 2.0:
            return {"symbol": symbol, "vol": round(ratio, 1), "price": closes[-1]}
        return None
    except: return None

def main():
    print("🛡️ SİSTEM BAŞLATILDI: ACABA GÖZCÜSÜ AKTİF 🛡️")
    send_telegram("💎 *Sistem Güncellendi:* Artık 'ACABA?' modülü aktif, hacim anormalliklerini OI verisiyle onaylıyorum.")
    
    sent_dict = {}
    while True:
        try:
            f_pairs = get_futures_pairs()
            print("Taramalar yapılıyor...")
            
            for symbol in f_pairs[:50]: # Hız için ilk 50
                # 1. ACABA TARAMASI
                data_acaba = analyze_acaba(symbol)
                if data_acaba:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        conf = check_acaba_confirmation(symbol)
                        msg = f"🤔 *ACABA?* #{data_acaba['symbol']}\n• Hacim: {data_acaba['vol']}x\n• Analiz: {conf}"
                        send_telegram(msg)
                        sent_dict[symbol] = time.time()
            
            time.sleep(300)
        except Exception as e:
            print(f"Hata: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
