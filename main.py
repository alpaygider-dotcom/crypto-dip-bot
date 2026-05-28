import requests
import time
from statistics import mean

# AYARLAR
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"

# Railway IP engellerini aşmak için Binance resmi yedek sunucu listesi
BINANCE_MIRRORS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com"
]

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def get_all_pairs_and_url():
    # Yedek sunucuları sırayla dener, çalışan sunucuyu ve coin listesini döner
    for base_url in BINANCE_MIRRORS:
        try:
            res = requests.get(f"{base_url}/api/v3/exchangeInfo", timeout=5)
            if res.status_code == 200:
                data = res.json()
                pairs = [s['symbol'] for s in data.get('symbols', []) if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
                if pairs:
                    return pairs, base_url
        except:
            continue
    return [], None

def main():
    print("🚀 BOT TÜM PİYASA + YEDEK SUNUCU DESTEĞİ İLE BAŞLADI...")
    sent_dict = {}
    
    while True:
        pairs, working_url = get_all_pairs_and_url()
        
        if not pairs:
            print("❌ Tüm Binance sunucuları isteği reddetti (IP Blok). 30 saniye sonra tekrar denenecek...")
            time.sleep(30)
            continue
            
        print(f"\n[{time.strftime('%H:%M:%S')}] TOPLAM {len(pairs)} COIN TARANIYOR ({working_url})...")
        
        for symbol in pairs:
            try:
                # Çalışan yedek sunucu üzerinden klines isteği atılır
                res = requests.get(f"{working_url}/api/v3/klines", 
                                   params={"symbol": symbol, "interval": "5m", "limit": 20}, timeout=4)
                
                if res.status_code != 200:
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
                        
            except:
                pass
            
            # Ban yememek için akıllı milisaniye gecikmesi
            time.sleep(0.1)
        
        print(f"[{time.strftime('%H:%M:%S')}] Tarama tamamlandı. 60 saniye dinleniliyor...")
        time.sleep(60)

if __name__ == "__main__":
    main()
