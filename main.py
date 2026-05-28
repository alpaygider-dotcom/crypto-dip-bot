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
    print("🚀 BOT GÜÇLENDİRİLMİŞ MODDA BAŞLADI...")
    sent_dict = {}
    
    while True:
        try:
            print(f"[{time.strftime('%H:%M:%S')}] Piyasalar taranıyor...")
            
            # 1. TÜM VERİYİ TEK SEFERDE ÇEK (Hız için)
            all_tickers = requests.get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", timeout=10).json()
            # USDT paritelerini filtrele
            pairs = [t['symbol'] for t in all_tickers if t['symbol'].endswith('USDT') and float(t['quoteVolume']) > 1000000]
            
            print(f"Toplam {len(pairs)} coin kontrol ediliyor...")

            for symbol in pairs:
                # 2. SADECE 1 İSTEK YAP (API limitini aşmamak için)
                klines = requests.get(f"{BINANCE_SPOT}/api/v3/klines", 
                                     params={"symbol": symbol, "interval": "5m", "limit": 20}, timeout=3).json()
                
                if len(klines) < 20: continue
                
                volumes = [float(k[5]) for k in klines]
                avg_vol = mean(volumes[:-2])
                if avg_vol == 0: continue
                ratio = volumes[-1] / avg_vol
                
                # ZIRHLI SİNYAL
                if ratio > 2.3:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\nHacim: {round(ratio,1)}x")
                        sent_dict[symbol] = time.time()
                
                # ACABA SİNYALİ
                elif ratio > 1.3:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 1800):
                        send_telegram(f"🤔 *ACABA?* #{symbol}\nHacim: {round(ratio,1)}x")
                        sent_dict[symbol] = time.time()
            
            print("Döngü bitti, 60 saniye dinleniliyor...")
            time.sleep(60)
            
        except Exception as e:
            print(f"Hata oluştu: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
