import requests
import time
from statistics import mean

# CREDENTIALS
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_FUTURES = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try: requests.post(url, data=data)
    except: pass

def get_all_pairs():
    try:
        # Hem Spot hem Futures'u tara
        res_spot = requests.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo").json()
        pairs = [s["symbol"] for s in res_spot["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]
        return list(set(pairs)) # Tekrar edenleri temizle
    except: return []

def get_klines(symbol, interval, limit):
    try:
        # Spot endpointi daha genel olduğu için onu kullanıyoruz
        url = f"{BINANCE_SPOT}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return requests.get(url, params=params).json()
    except: return []

def check_oi_status(symbol):
    # OI sadece Futures için geçerli, Spot'ta pasif
    try:
        oi_url = f"{BINANCE_FUTURES}/futures/data/openInterestHist"
        oi_res = requests.get(oi_url, params={"symbol": symbol, "period": "5m", "limit": 2}).json()
        if len(oi_res) >= 2:
            if float(oi_res[1]["sumOpenInterest"]) > float(oi_res[0]["sumOpenInterest"]):
                return "✅ ONAYLI (Balina girişi)"
            return "⚠️ ONAYLANMADI (Hacim var, OI zayıf)"
        return "❓ (Spot Coin - OI verisi yok)"
    except: return "❌ Analiz edilemedi"

def analyze(symbol):
    try:
        klines = get_klines(symbol, "5m", 20)
        if len(klines) < 20: return None
        
        volumes = [float(k[5]) for k in klines]
        avg_vol = mean(volumes[:-2])
        if avg_vol == 0: return None
        ratio = volumes[-1] / avg_vol
        
        closes = [float(k[4]) for k in klines]
        price_change = ((closes[-1] - closes[-4]) / closes[-4]) * 100
        
        # 1.5x Hacim ve +/- 3% fiyat değişimi filtresi
        if ratio > 1.5 and -3.0 < price_change < 3.0:
            return {"symbol": symbol, "vol": round(ratio, 1), "price": closes[-1]}
        return None
    except: return None

def main():
    print("🚀 BOT BAŞLATILDI: TÜM PİYASA TARANIYOR...")
    send_telegram("💎 *Sistem Güncellendi:* Tüm Binance (Spot+Futures) taranıyor. 'ACABA' gözcüsü aktif.")
    
    sent_dict = {}
    while True:
        try:
            pairs = get_all_pairs()
            print(f"Tarama başlıyor, toplam {len(pairs)} çift kontrol ediliyor...")
            
            for symbol in pairs:
                data = analyze(symbol)
                if data:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 1800): # 30 dk spam koruması
                        conf = check_oi_status(symbol)
                        msg = f"🤔 *ACABA?* #{data['symbol']}\n• Hacim: {data['vol']}x\n• Analiz: {conf}\n• Fiyat: `{data['price']}`"
                        send_telegram(msg)
                        sent_dict[symbol] = time.time()
            
            print("Tarama döngüsü bitti, kısa ara...")
            time.sleep(120)
        except Exception as e:
            print(f"Hata: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
