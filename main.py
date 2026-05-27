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

def get_klines(symbol, limit):
    return requests.get(f"{BINANCE_SPOT}/api/v3/klines", params={"symbol": symbol, "interval": "5m", "limit": limit}).json()

def check_zırhlı(symbol, klines):
    # Zırhlı kriterler: Hacim patlaması + Dipte olma + Fiyatın çok şişmemiş olması
    volumes = [float(k[5]) for k in klines]
    avg_vol = mean(volumes[:-2])
    if avg_vol == 0: return False
    
    ratio = volumes[-1] / avg_vol
    closes = [float(k[4]) for k in klines]
    
    # Kriter: 2.3x Hacim ve son 20dk pump yapmamış olması
    return ratio > 2.3 and ((closes[-1] - closes[-4]) / closes[-4]) < 0.05

def main():
    print("🚀 ÇİFT KATMANLI TARAMA AKTİF...")
    sent_dict = {}
    
    while True:
        pairs = get_pairs()
        for symbol in pairs:
            try:
                klines = get_klines(symbol, 20)
                if len(klines) < 20: continue
                
                # 1. ZIRHLI SİNYAL KONTROLÜ
                if check_zırhlı(symbol, klines):
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI SİNYAL!* #{symbol}\nKuralları tam karşıladı, hacim patladı ve dipte.")
                        sent_dict[symbol] = time.time()
                        continue # Zırhlı yakaladıysa Acaba'ya bakma

                # 2. ACABA? GÖZCÜSÜ (Hacim var ama Zırhlı kriterine tam uymuyor)
                volumes = [float(k[5]) for k in klines]
                ratio = volumes[-1] / mean(volumes[:-2])
                if ratio > 1.5:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 1800):
                        send_telegram(f"🤔 *ACABA?* #{symbol}\nHacim {round(ratio,1)}x arttı, takibe al.")
                        sent_dict[symbol] = time.time()

            except: continue
        time.sleep(180)

if __name__ == "__main__":
    main()
