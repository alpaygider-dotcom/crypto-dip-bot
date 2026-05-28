import requests
import time
from statistics import mean

BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_SPOT = "https://api.binance.com"

# API listesini beklemeden doğrudan tarayacağımız liste
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "NEARUSDT", "ATOMUSDT", "UNIUSDT", "FTMUSDT", "ARBUSDT", "OPUSDT", "APTUSDT", "PEPEUSDT", "SHIBUSDT", "LTCUSDT", "BCHUSDT", "FILUSDT", "SANDUSDT", "MANAUSDT", "EGLDUSDT", "AAVEUSDT", "GRTUSDT", "RENDERUSDT", "SUIUSDT"]

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def main():
    print("🚀 SABİT LİSTE İLE BOT BAŞLATILDI...")
    sent_dict = {}
    
    while True:
        print(f"[{time.strftime('%H:%M:%S')}] {len(SYMBOLS)} parite taranıyor...")
        
        for symbol in SYMBOLS:
            try:
                klines = requests.get(f"{BINANCE_SPOT}/api/v3/klines", 
                                     params={"symbol": symbol, "interval": "5m", "limit": 20}, timeout=5).json()
                
                if not isinstance(klines, list) or len(klines) < 20: continue
                
                volumes = [float(k[5]) for k in klines]
                avg_vol = mean(volumes[:-2])
                if avg_vol == 0: continue
                
                ratio = volumes[-1] / avg_vol
                
                if ratio > 2.3:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\nHacim: {round(ratio,1)}x")
                        sent_dict[symbol] = time.time()
                elif ratio > 1.3:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 1800):
                        send_telegram(f"🤔 *ACABA?* #{symbol}\nHacim: {round(ratio,1)}x")
                        sent_dict[symbol] = time.time()
            except: continue
        
        time.sleep(60)

if __name__ == "__main__":
    main()
