import requests
import time
from statistics import mean

# AYARLAR
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

BINANCE_MIRRORS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com"
]
FUTURES_URL = "https://fapi.binance.com"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def get_all_pairs_and_url():
    for base_url in BINANCE_MIRRORS:
        try:
            res = requests.get(f"{base_url}/api/v3/exchangeInfo", headers=HEADERS, timeout=5)
            if res.status_code == 200:
                data = res.json()
                pairs = [s['symbol'] for s in data.get('symbols', []) if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']
                if pairs: return pairs, base_url
        except: continue
    return [], None

def get_ls_dropped(symbol):
    try:
        res = requests.get(f"{FUTURES_URL}/futures/data/globalLongShortAccountRatio", 
                           params={"symbol": symbol, "period": "5m", "limit": 2}, 
                           headers=HEADERS, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if len(data) >= 2:
                prev_long = float(data[0]['longAccount'])
                curr_long = float(data[1]['longAccount'])
                return curr_long < prev_long 
    except: pass
    return True 

def main():
    print("🚀 BOT GÜNCELLENDİ: 'Düşüş/Dump Hacmi' Engeli Aktif...")
    sent_dict = {}
    
    while True:
        pairs, working_url = get_all_pairs_and_url()
        if not pairs:
            print("❌ Tüm kapılar kapalı. 30 sn sonra tekrar denenecek...")
            time.sleep(30)
            continue
            
        print(f"\n[{time.strftime('%H:%M:%S')}] Piyasaya bakılıyor ({working_url})...")
        
        # 1. BTC BAĞIMSIZLIK KONTROLÜ
        btc_is_pumping = False
        try:
            btc_k = requests.get(f"{working_url}/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "5m", "limit": 20}, headers=HEADERS, timeout=3).json()
            btc_vols = [float(k[5]) for k in btc_k]
            if (btc_vols[-1] / mean(btc_vols[:-2])) > 2.0:
                btc_is_pumping = True
        except: pass

        if btc_is_pumping:
            print("⚠️ BTC'de ani hacim var! Sahte altcoin sinyallerini önlemek için döngü atlanıyor...")
            time.sleep(60)
            continue

        # 2. GÜNLÜK VERİLERİ ÇEK
        ticker_dict = {}
        try:
            tickers = requests.get(f"{working_url}/api/v3/ticker/24hr", headers=HEADERS, timeout=5).json()
            for t in tickers: ticker_dict[t['symbol']] = t
        except: pass

        # Önce günlük %8'den fazla uçmuş coinleri ele
        filtered_pairs = [s for s in pairs if s in ticker_dict and float(ticker_dict[s].get('priceChangePercent', 0)) <= 8.0]
        
        print(f"[{time.strftime('%H:%M:%S')}] Uçmamış {len(filtered_pairs)} coin analiz ediliyor...")

        for symbol in filtered_pairs:
            try:
                res = requests.get(f"{working_url}/api/v3/klines", 
                                   params={"symbol": symbol, "interval": "5m", "limit": 20}, 
                                   headers=HEADERS, timeout=4)
                if res.status_code != 200: continue
                    
                klines = res.json()
                if not isinstance(klines, list) or len(klines) < 20: continue
                
                prices = [float(k[4]) for k in klines]
                volumes = [float(k[5]) for k in klines]
                
                # --- YENİ EKLENEN "GERÇEK ALIM" KONTROLLERİ ---
                current_open = float(klines[-1][1])
                current_close = float(klines[-1][4])
                current_vol = float(klines[-1][5])
                taker_buy_vol = float(klines[-1][9]) # Doğrudan alıcı hacmi
                
                # Şart 1: Mum kırmızıysa (Satış yiyorsa) kesinlikle pas geç!
                if current_close <= current_open:
                    continue
                    
                # Şart 2: Hacmin en az %55'i "Alım (Buy)" yönlü değilse pas geç!
                if taker_buy_vol < (current_vol * 0.55):
                    continue
                    
                # Şart 3: Düşüş sonrası yalancı tepkiyse (Fiyat hala ortalamanın altındaysa) pas geç!
                past_prices = prices[:-1]
                if current_close < mean(past_prices):
                    continue
                # ----------------------------------------------

                avg_vol = mean(volumes[:-2])
                if avg_vol == 0: continue
                ratio = volumes[-1] / avg_vol
                
                # YATAYLIK KONTROLÜ (Son 1.5 saatte fiyat max %4 oynamış olmalı)
                if (max(past_prices) - min(past_prices)) / min(past_prices) > 0.04:
                    continue 

                quote_vol = float(ticker_dict[symbol]['quoteVolume'])
                
                # 💎 ZIRHLI SİNYAL (Hacim > 5.0x | Hacim > 10M$ | L/S Düşüşü | Net Yükseliş)
                if ratio > 5.0 and quote_vol > 10000000:
                    if get_ls_dropped(symbol):
                        if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                            send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\n• Hacim Patlaması: {round(ratio,1)}x\n• Formasyon: Dipte Gerçek Alım\n• Veri: L/S Düşüşü & Alıcı Baskın")
                            sent_dict[symbol] = time.time()
                            continue 
                
                # 🤔 ACABA SİNYALİ (Hacim > 3.0x | Hacim > 1M$ | Net Yükseliş)
                if ratio > 3.0 and quote_vol > 1000000:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"🤔 *ACABA?* #{symbol}\n• Hacim Patlaması: {round(ratio,1)}x\n• Formasyon: Dipte Gerçek Alım\n• Veri: Alıcı Baskın")
                        sent_dict[symbol] = time.time()
                        
            except: pass
            time.sleep(0.1)
        
        print(f"[{time.strftime('%H:%M:%S')}] Tarama tamamlandı. 60 sn bekleniyor...")
        time.sleep(60)

if __name__ == "__main__":
    main()
