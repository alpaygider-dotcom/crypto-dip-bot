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

FUTURES_URL = "https://fapi.binance.com"

# ASLA KİLİTLENMEYEN ESKİ STABİL PARİTE LİSTEMİZ
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
    print("🚀 BOT GÜVENLİ VE HAFİF MODDA BAŞLATILDI (YALNIZCA FUTURES VERİSİ) 🚀")
    sent_dict = {}
    
    while True:
        print(f"\n[{time.strftime('%H:%M:%S')}] {len(COINS)} Vadeli Parite Analiz Ediliyor...")
        
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
            print("⚠️ BTC tahtasında ani agresif hacim! Tarama 1 dk erteleniyor...")
            time.sleep(60)
            continue

        # PARİTE TARAMA DÖNGÜSÜ
        for coin in COINS:
            symbol = f"{coin}USDT"
            try:
                time.sleep(0.1) # İstek aralarında hafif es (Rate limit koruması)
                
                # 2. 5 DAKİKALIK VADELİ MUM VE TAKER BUY VERİLERİ
                res = requests.get(f"{FUTURES_URL}/fapi/v1/klines", params={"symbol": symbol, "interval": "5m", "limit": 20}, headers=HEADERS, timeout=3)
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
                
                # 🛡️ ESKİ ÇALIŞAN KODUN TEMEL FİLTRE KALKANLARI
                if current_close <= current_open:
                    continue
                if taker_buy_vol < (current_vol * 0.55): # Taker Buy Güç Filtresi
                    continue
                if current_close < mean(prices[:-1]):
                    continue

                # YATAYLIK FORMASYONU (Son 1.5 saat içinde sıkışma kontrolü)
                past_prices = prices[:-1]
                if (max(past_prices) - min(past_prices)) / min(past_prices) > 0.04:
                    continue 

                # Hacim Patlama Katsayısı Kontrolü
                avg_vol = mean(volumes[:-2])
                if avg_vol == 0:
                    continue
                ratio = volumes[-1] / avg_vol
                
                if ratio < 3.0:
                    continue 

                # ----------------=======================================----------------
                # BUKALEMUN ADIM: BURAYA KADAR GELEN COIN VARSA ÖZEL VERİLERİNİ ÇEKER 🌟
                # ----------------=======================================----------------
                try:
                    ticker_res = requests.get(f"{FUTURES_URL}/fapi/v1/ticker/24hr", params={"symbol": symbol}, headers=HEADERS, timeout=3).json()
                    price_change = float(ticker_res.get('priceChangePercent', 0))
                    quote_vol = float(ticker_res.get('quoteVolume', 0))
                except:
                    continue # Eğer veri çekilemezse hata vermez, bir sonrakine geçer.

                # Günlük %8'den fazla yükselenleri filtrele
                if price_change > 8.0:
                    continue
                
                score = 3
                stars = "⭐" * score

                # 💎 SINIF 1: ZIRHLI SİNYAL KONTROLÜ (Gelişmiş Vadeli Filtreleri)
                if ratio > 5.0 and quote_vol > 10000000:
                    
                    # 7 Günlük Gerçek Dip Kontrolü
                    try:
                        res_7d = requests.get(f"{FUTURES_URL}/fapi/v1/klines", params={"symbol": symbol, "interval": "1d", "limit": 7}, headers=HEADERS, timeout=3).json()
                        max_7d_high = max([float(k[2]) for k in res_7d])
                        if current_close > (max_7d_high * 0.85):
                            continue
                    except:
                        continue

                    # Open Interest (OI) Kontrolü
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

                    # L/S Divergansı
                    try:
                        ls_res = requests.get(f"{FUTURES_URL}/futures/data/globalLongShortAccountRatio", params={"symbol": symbol, "period": "5m", "limit": 2}, headers=HEADERS, timeout=3).json()
                        if len(ls_res) >= 2 and float(ls_res[1]['longAccount']) < float(ls_res[0]['longAccount']):
                            score += 1
                    except:
                        pass
                    
                    score += 1
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

                # 🤔 SINIF 2: ACABA SİNYALİ KONTROLÜ
                if ratio > 3.0 and quote_vol > 1000000:
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
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

        print(f"[{time.strftime('%H:%M:%S')}] Tarama sorunsuz bitti. 60 sn bekleniyor...")
        time.sleep(60)

if __name__ == "__main__":
    main()
