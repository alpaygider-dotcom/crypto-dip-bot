import requests
import time
from statistics import mean

BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_SPOT = "https://api.binance.com"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def main():
    print("🚀 BOT BAŞLATILDI...")
    sent_dict = {}
    
    while True:
        try:
            # Önce aktif USDT paritelerini al
            res = requests.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo", timeout=10).json()
            pairs = [s['symbol'] for s in res.get('symbols', []) if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
            
            print(f"[{time.strftime('%H:%M:%S')}] {len(pairs)} parite taranıyor...")

            for symbol in pairs:
                try:
                    # Klines al
                    klines = requests.get(f"{BINANCE_SPOT}/api/v3/klines", 
                                         params={"symbol": symbol, "interval": "5m", "limit": 20}, timeout=2).json()
                    
                    if not isinstance(klines, list) or len(klines) < 20: continue
                    
                    volumes = [float(k[5]) for k in klines]
                    avg_vol = mean(volumes[:-2])
                    if avg_vol == 0: continue
                    
                    ratio = volumes[-1] / avg_vol
                    
                    # Sinyal Kontrolü
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
            
        except Exception as e:
            print(f"Hata: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
