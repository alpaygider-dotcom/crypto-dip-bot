import requests
import time
from statistics import mean

# AYARLAR
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_SPOT = "https://api.binance.com"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def get_all_pairs():
    # Tüm Binance piyasasını çekiyoruz
    try:
        res = requests.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo", timeout=10)
        if res.status_code == 200:
            data = res.json()
            return [s['symbol'] for s in data.get('symbols', []) if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
        return []
    except Exception as e:
        print(f"Liste çekilemedi: {e}")
        return []

def main():
    print("🚀 BOT TÜM PİYASA İÇİN BAŞLATILDI (ANTI-BAN AKTİF)...")
    sent_dict = {}
    
    while True:
        pairs = get_all_pairs()
        
        if not pairs:
            print("API yanıt vermedi, 30 saniye sonra tekrar denenecek...")
            time.sleep(30)
            continue
            
        print(f"\n[{time.strftime('%H:%M:%S')}] TOPLAM {len(pairs)} COIN TARANIYOR...")
        
        for symbol in pairs:
            try:
                # Klines isteği
                res = requests.get(f"{BINANCE_SPOT}/api/v3/klines", 
                                   params={"symbol": symbol, "interval": "5m", "limit": 20}, timeout=5)
                
                if res.status_code != 200:
                    time.sleep(0.1) # Hata alırsak spam yapmamak için bekle
                    continue
                    
                klines = res.json()
                
                if not isinstance(klines, list) or len(klines) < 20: 
                    continue
                
                volumes = [float(k[5]) for k in klines]
                avg_vol = mean(volumes[:-2])
                
                if avg_vol == 0: 
                    continue
                
                ratio = volumes[-1] / avg_vol
                
                # 1. ZIRHLI SİNYAL (Büyük patlama)
                if ratio > 2.3:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\n• Hacim: {round(ratio,1)}x\n• Piyasa: Tüm Binance")
                        sent_dict[symbol] = time.time()
                
                # 2. ACABA SİNYALİ (Küçük kıpırdanma / Trade)
                elif ratio > 1.3:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 1800):
                        send_telegram(f"🤔 *ACABA?* #{symbol}\n• Hacim: {round(ratio,1)}x\n• Piyasa: Tüm Binance")
                        sent_dict[symbol] = time.time()
                        
            except Exception:
                pass
            
            # BİNANCE BİZİ BANLAMASIN DİYE ÇOK HAFİF GECİKME (Milisaniye)
            time.sleep(0.1)
        
        print(f"[{time.strftime('%H:%M:%S')}] Tarama tamamlandı. 60 saniye dinleniliyor...")
        time.sleep(60)

if __name__ == "__main__":
    main()
