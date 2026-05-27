import requests
import time
from statistics import mean

BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def get_pairs():
    try:
        # Hata yönetimi eklenmiş istek
        response = requests.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo", timeout=10)
        data = response.json()
        if "symbols" in data:
            return [s["symbol"] for s in data["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]
        return []
    except Exception as e:
        print(f"Hata (get_pairs): {e}")
        return []

def get_klines(symbol):
    try:
        # Hata yönetimi eklenmiş istek
        url = f"{BINANCE_SPOT}/api/v3/klines"
        params = {"symbol": symbol, "interval": "5m", "limit": 20}
        res = requests.get(url, params=params, timeout=5)
        return res.json() if res.status_code == 200 else []
    except: return []

def check_zırhlı_tam(symbol, klines):
    try:
        volumes = [float(k[5]) for k in klines]
        if mean(volumes[:-2]) == 0: return False
        ratio = volumes[-1] / mean(volumes[:-2])
        
        ticker = requests.get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=5).json()
        daily_vol = float(ticker.get("quoteVolume", 0))
        
        # LS Kontrolü
        ls_res = requests.get(f"{BINANCE_FUTURES}/futures/data/globalLongShortAccountRatio", 
                              params={"symbol": symbol, "period": "5m", "limit": 1}, timeout=5).json()
        ls_ratio = float(ls_res[0]["longShortRatio"])
        
        return ratio > 2.3 and daily_vol > 10000000 and ls_ratio < 1.25
    except: return False

def main():
    print("🚀 GÜVENLİ BAŞLATILDI...")
    send_telegram("✅ Sistem güvenli modda başlatıldı.")
    sent_dict = {}
    
    while True:
        pairs = get_pairs()
        if not pairs:
            print("Veri alınamadı, 60 saniye bekleniyor...")
            time.sleep(60)
            continue
            
        for symbol in pairs:
            try:
                klines = get_klines(symbol)
                if len(klines) < 20: continue
                
                if check_zırhlı_tam(symbol, klines):
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\n• Hacim: 2.3x+\n• 10M$ Hacim onaylı.")
                        sent_dict[symbol] = time.time()
                
                else:
                    volumes = [float(k[5]) for k in klines]
                    if volumes[-1] / mean(volumes[:-2]) > 1.5:
                        if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 1800):
                            send_telegram(f"🤔 *ACABA?* #{symbol}\nHacim patladı, takibe al.")
                            sent_dict[symbol] = time.time()
            except: continue
        time.sleep(60)

if __name__ == "__main__":
    main()
