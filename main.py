import requests
import time
from statistics import mean

BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

def get_pairs():
    res = requests.get(f"{BINANCE_SPOT}/api/v3/exchangeInfo").json()
    return [s["symbol"] for s in res["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]

def check_zırhlı_tam(symbol, klines):
    # 1. Hacim Patlaması (2.3x)
    volumes = [float(k[5]) for k in klines]
    if mean(volumes[:-2]) == 0: return False
    ratio = volumes[-1] / mean(volumes[:-2])
    
    # 2. Likidite Kontrolü (10M$ Hacim)
    ticker = requests.get(f"{BINANCE_SPOT}/api/v3/ticker/24hr", params={"symbol": symbol}).json()
    daily_vol = float(ticker.get("quoteVolume", 0))
    
    # 3. LS Oranı (1.25 Altı - Balina baskısı yok)
    try:
        ls_res = requests.get(f"{BINANCE_FUTURES}/futures/data/globalLongShortAccountRatio", 
                              params={"symbol": symbol, "period": "5m", "limit": 1}).json()
        ls_ratio = float(ls_res[0]["longShortRatio"])
    except: ls_ratio = 1.0

    return ratio > 2.3 and daily_vol > 10000000 and ls_ratio < 1.25

def main():
    sent_dict = {}
    print("🚀 DİPSİZ, SAF AVCI MODU AKTİF...")
    
    while True:
        pairs = get_pairs()
        for symbol in pairs:
            try:
                klines = requests.get(f"{BINANCE_SPOT}/api/v3/klines", 
                                     params={"symbol": symbol, "interval": "5m", "limit": 20}).json()
                if len(klines) < 20: continue
                
                # ZIRHLI SİNYAL (Dip filtresi yok)
                if check_zırhlı_tam(symbol, klines):
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\n• Hacim: 2.3x+\n• Likidite: 10M$+\n• LS Oranı: Balina temiz.")
                        sent_dict[symbol] = time.time()
                
                # ACABA SİNYALİ (Dip filtresi yok)
                else:
                    volumes = [float(k[5]) for k in klines]
                    if volumes[-1] / mean(volumes[:-2]) > 1.5:
                        if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 1800):
                            send_telegram(f"🤔 *ACABA?* #{symbol}\nHacim patladı, takibe al.")
                            sent_dict[symbol] = time.time()
            except: continue
        time.sleep(180)

if __name__ == "__main__":
    main()
