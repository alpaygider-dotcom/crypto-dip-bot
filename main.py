import requests
import time
from statistics import mean

# ==========================================
# AYARLAR & ENTEGRASYON
# ==========================================
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Accept": "application/json"
}

SPOT_URL = "https://api.binance.com"
FUTURES_URL = "https://fapi.binance.com"

# ESKİ ÇALIŞAN KODDAKİ GİBİ SABİT PARİTE LİSTEMİZ (Sunucuyu kilitlemez)
COINS = [
    "1000LUNC", "1000SHIB", "1000XEC", "ADA", "AGLD", "APE", "APT", "AR", "ARB", "ARKM",
    "ATOM", "AVAX", "BANANA", "BCH", "BLUR", "BNB", "BONK", "CELO", "CRV", "CYBER",
    "DOGE", "DOT", "DYDX", "EGLD", "ENS", "EOS", "ETC", "ETH", "FIL", "FLOW",
    "FTM", "FXS", "GALA", "GMT", "GRT", "ICP", "IMX", "INJ", "IOTA", "JUP",
    "LDO", "LINK", "LTC", "LUNA", "MAGIC", "MANA", "MATIC", "MINA", "MKR", "NEAR",
    "NEO", "OP", "ORDI", "PEPE", "PYTH", "RNDR", "RUNE", "SAND", "SEI", "SOL",
    "STX", "SUI", "TIA", "TRX", "UMA", "UNI", "WIF", "WORLD", "XLM", "XMR",
    "XRP", "YGG", "ZETA"
]

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except:
        pass

def main():
    print("🚀 SABİT LİSTE VE YENİ GÜÇLÜ FİLTRELERLE BOT BAŞLATILDI... 🚀")
    sent_dict = {}
    
    while True:
        print(f"\n[{time.strftime('%H:%M:%S')}] {len(COINS)} Parite Taranıyor...")
        
        # 1. BTC VADELİ HACİM KONTROLÜ (Piyasa Güvenliği)
        btc_is_pumping = False
        try:
            btc_k = requests.get(f"{FUTURES_URL}/fapi/v1/klines", params={"symbol": "BTCUSDT", "interval": "5m", "limit": 20}, headers=HEADERS, timeout=3).json()
            btc_vols = [float(k[5]) for k in btc_k]
            if (btc_vols[-1] / mean(btc_vols[:-2])) > 2.2:
                btc_is_pumping = True
        except:
            pass

        if btc_is_pumping:
            print("⚠️ BTC tahtasında agresif hacim! Güvenlik için 1 dakika erteleniyor...")
            time.sleep(60)
            continue

        # 2. 24s TICKER VERİLERİNİ TEK SEFERDE ÇEK (Piyasa Hacmi İçin tek istek)
        f_ticker_dict = {}
        try:
            f_tickers = requests.get(f"{FUTURES_URL}/fapi/v1/ticker/24hr", headers=HEADERS, timeout=4).json()
            for t in f_tickers:
                f_ticker_dict[t['symbol']] = t
        except:
            print("⚠️ 24s Ticker verisi çekilemedi, bir sonraki döngüde denenecek.")
            time.sleep(10)
            continue

        for coin in COINS:
            symbol = f"{coin}USDT"
            try:
                time.sleep(0.2) # Rate limit yememek için güvenli bekleme süresi artırıldı
                
                if symbol not in f_ticker_dict:
                    continue
                
                # Günlük %8'den fazla fırlamışları doğrudan ele
                if float(f_ticker_dict[symbol].get('priceChangePercent', 0)) > 8.0:
                    continue
                
                # 3. 5 DAKİKALIK MUM VE TAKER BUY VERİLERİ (Vadeli Tahtadan)
                res = requests.get(f"{FUTURES_URL}/fapi/v1/klines", params={"symbol": symbol, "interval": "5m", "limit": 20}, headers=HEADERS, timeout=4)
                if res.status_code != 200:
                    continue
                klines = res.json()
                if len(klines) < 20:
                    continue
                
                prices = [float(k[4]) for k in klines]
                volumes = [float(k[5]) for k in klines]
                
                current_open = float(klines[-1][1])
                current_close = float(klines[-1][4])
                current_vol = float(klines[-1][5])
                taker_buy_vol = float(klines[-1][9])
                
                # 🛡️ KRİTİK KALKANLAR (Senin en çok verim aldığın yerler)
                if current_close <= current_open:
                    continue
                if taker_buy_vol < (current_vol * 0.55): # Taker Buy Filtresi
                    continue
                if current_close < mean(prices[:-1]):
                    continue

                # YATAYLIK FORMASYONU (Sıkışma Kontrolü)
                past_prices = prices[:-1]
                if (max(past_prices) - min(past_prices)) / min(past_prices) > 0.04:
                    continue 

                # Hacim Patlama Katsayısı
                avg_vol = mean(volumes[:-2])
                if avg_vol == 0:
                    continue
                ratio = volumes[-1] / avg_vol
                
                if ratio < 3.0:
                    continue 

                quote_vol = float(f_ticker_dict[symbol].get('quoteVolume', 0))
                
                # --------------------------------------------------------
                # 💎 SINIF 1: ZIRHLI SİNYAL KONTROLÜ (VADELİ DESTEKLİ)
                # --------------------------------------------------------
                if ratio > 5.0 and quote_vol > 10000000:
                    
                    # 7 Günlük Gerçek Dip Kontrolü
                    try:
                        res_7d = requests.get(f"{FUTURES_URL}/fapi/v1/klines", params={"symbol": symbol, "interval": "1d", "limit": 7}, headers=HEADERS, timeout=4).json()
                        max_7d_high = max([float(k[2]) for k in res_7d])
                        if current_close > (max_7d_high * 0.85):
                            continue
                    except:
                        continue

                    # Open Interest Kontrolü
                    try:
                        oi_res = requests.get(f"{FUTURES_URL}/fapi/v1/openInterestHist", params={"symbol": symbol, "period": "5m", "limit": 2}, headers=HEADERS, timeout=3).json()
                        if len(oi_res) >= 2:
                            prev_oi = float(oi_res[0]['sumOpenInterest'])
                            curr_oi = float(oi_res[1]['sumOpenInterest'])
                            oi_change = ((curr_oi - prev_oi) / prev_oi) * 100 if prev_oi > 0 else 0
                            if oi_change < 1.5:
                                continue
                        else:
                            continue
                    except:
                        continue

                    # Funding Rate Kontrolü
                    try:
                        funding_res = requests.get(f"{FUTURES_URL}/fapi/v1/premiumIndex", params={"symbol": symbol}, headers=HEADERS, timeout=3).json()
                        funding_rate = float(funding_res.get('lastFundingRate', 0))
                        if funding_rate > 0.015:
                            continue
                    except:
                        continue

                    # L/S Divergansı & Yıldız Skorlama
                    score = 4
                    try:
                        ls_res = requests.get(f"{FUTURES_URL}/futures/data/globalLongShortAccountRatio", params={"symbol": symbol, "period": "5m", "limit": 2}, headers=HEADERS, timeout=3).json()
                        if len(ls_res) >= 2 and float(ls_res[1]['longAccount']) < float(ls_res[0]['longAccount']):
                            score += 1
                    except:
                        pass
                    
                    stars = "⭐" * score

                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        send_telegram(f"💎 *ZIRHLI VADELİ SİNYAL* #{symbol}\n\n"
                                      f"• *Güven Skoru:* {stars}\n"
                                      f"• Hacim Patlaması: {round(ratio,1)}x\n"
                                      f"• Para Girişi (OI): +%{round(oi_change,2)}\n"
                                      f"• Fonlama Oranı: %{round(funding_rate*100,3)}\n"
                                      f"• Durum: 7 Günlük Dipte Sıkışma Kırılımı\n"
                                      f"• Detay: Küçük Yatırımcı Eleniyor (L/S Düşüşü)")
                        sent_dict[symbol] = time.time()
                        continue

                # --------------------------------------------------------
                # 🤔 SINIF 2: ACABA SİNYALİ KONTROLÜ
                # --------------------------------------------------------
                if ratio > 3.0 and quote_vol > 1000000:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        stars = "⭐" * 3
                        if ratio > 5.0:
                            stars += "⭐"
                        
                        send_telegram(f"🤔 *ACABA SİNYALİ* #{symbol}\n\n"
                                      f"• *Güven Skoru:* {stars}\n"
                                      f"• Hacim Patlaması: {round(ratio,1)}x\n"
                                      f"• Konum: Dip Bölgesi Gerçek Alıcı Baskısı\n"
                                      f"• Not: Sabırlı Akümülasyondan Çıkış")
                        sent_dict[symbol] = time.time()

            except:
                pass

        print(f"[{time.strftime('%H:%M:%S')}] Tarama başarıyla bitti. 60 sn bekleniyor...")
        time.sleep(60)

if __name__ == "__main__":
    main()
