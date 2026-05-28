import requests
import time
from statistics import mean

# AYARLAR
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
        res = requests.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo", timeout=10).json()
        return [s["symbol"] for s in res["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]
    except: return []

def get_klines(symbol):
    try:
        url = f"{BINANCE_SPOT}/api/v3/klines"
        params = {"symbol": symbol, "interval": "5m", "limit": 20}
        res = requests.get(url, params=params, timeout=5)
        return res.json() if res.status_code == 200 else []
    except: return []

def main():
    print("🚀 BOT BAŞLATILDI: ZIRHLI VE ACABA MODLARI AKTİF")
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
                
                volumes = [float(k[5]) for k in klines]
                avg_vol = mean(volumes[:-2])
                if avg_vol == 0: continue
                ratio = volumes[-1] / avg_vol
                
                # ZIRHLI SİNYAL (KATI KURALLAR)
                # 2.3x Hacim + 10M$ Likidite
                ticker = requests.get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=3).json()
                daily_vol = float(ticker.get("quoteVolume", 0))
                
                if ratio > 2.3 and daily_vol > 10000000:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\n• Hacim: {round(ratio,1)}x\n• Likidite: 10M$+")
                        sent_dict[symbol] = time.time()
                
                # ACABA SİNYALİ (DAHA ESNEK)
                # Sadece 1.3x hacim artışı yeterli, likidite şartı yok
                elif ratio > 1.3:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 1800):
                        send_telegram(f"🤔 *ACABA?* #{symbol}\n• Hacim: {round(ratio,1)}x\n• Kıpırdanma tespit edildi.")
                        sent_dict[symbol] = time.time()
                        
            except: continue
        time.sleep(60)

if __name__ == "__main__":
    main()
