import requests
import time
from statistics import mean

# CREDENTIALS
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
        response = requests.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo", timeout=10)
        data = response.json()
        if "symbols" in data:
            return [s["symbol"] for s in data["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]
        return []
    except:
        return []

def get_klines(symbol):
    try:
        url = f"{BINANCE_SPOT}/api/v3/klines"
        params = {"symbol": symbol, "interval": "5m", "limit": 20}
        res = requests.get(url, params=params, timeout=5)
        return res.json() if res.status_code == 200 else []
    except: return []

def check_zırhlı_tam(symbol, klines):
    try:
        volumes = [float(k[5]) for k in klines]
        if len(volumes) < 20 or mean(volumes[:-2]) == 0: return False
        ratio = volumes[-1] / mean(volumes[:-2])
        
        ticker = requests.get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=5).json()
        daily_vol = float(ticker.get("quoteVolume", 0))
        
        # LS Oranı
        ls_res = requests.get(f"{BINANCE_FUTURES}/futures/data/globalLongShortAccountRatio", 
                              params={"symbol": symbol, "period": "5m", "limit": 1}, timeout=5).json()
        ls_ratio = float(ls_res[0]["longShortRatio"])
        
        return ratio > 2.3 and daily_vol > 10000000 and ls_ratio < 1.25
    except: return False

def main():
    print("🚀 SİSTEM GÜVENLİ MODDA BAŞLADI...")
    send_telegram("✅ Sistem güvenli modda başlatıldı.")
    sent_dict = {}
    
    while True:
        pairs = get_pairs()
        if not pairs:
            time.sleep(60)
            continue
            
        for symbol in pairs:
            try:
                klines = get_klines(symbol)
                if len(klines) < 20: continue
                
                # Zırhlı Sinyal
                if check_zırhlı_tam(symbol, klines):
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\n• Hacim: 2.3x+\n• 10M$ Hacim onaylı.")
                        sent_dict[symbol] = time.time()
                
                # Acaba Sinyali
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
