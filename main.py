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

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except:
        pass

def get_all_market_pairs():
    """Hem Spot hem de Futures evrenindeki tüm benzersiz USDT çiftlerini toplar."""
    pairs = set()
    # 1. Vadeli Çiftleri Çek
    try:
        f_res = requests.get(f"{FUTURES_URL}/fapi/v1/exchangeInfo", headers=HEADERS, timeout=5).json()
        for s in f_res.get('symbols', []):
            if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING':
                pairs.add((s['symbol'], "Futures"))
    except:
        pass
    
    # 2. Spot Çiftleri Çek
    try:
        s_res = requests.get(f"{SPOT_URL}/api/v3/exchangeInfo", headers=HEADERS, timeout=5).json()
        for s in s_res.get('symbols', []):
            if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING':
                pairs.add((s['symbol'], "Spot"))
    except:
        pass
    
    return list(pairs)

def main():
    print("🔥 BOT HİBRİT MODDA BAŞLATILDI: ZIRHLI (VADELİ) | ACABA (SPOT & VADELİ) 🔥")
    sent_dict = {}
    
    while True:
        market_pairs = get_all_market_pairs()
        if not market_pairs:
            print("⚠️ Çiftler çekilemedi, 30 saniye sonra tekrar denenecek...")
            time.sleep(30)
            continue
            
        print(f"\n[{time.strftime('%H:%M:%S')}] {len(market_pairs)} Hibrit Parite Analiz Ediliyor...")
        
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
            print("⚠️ BTC tahtasında ani agresif hacim! Tarama güvenlik için 1 dk erteleniyor...")
            time.sleep(60)
            continue

        # 2. 24s TICKER VERİLERİNİ TEK SEFERDE ÇEK (Spot ve Vadeli için ayrı ayrı)
        f_ticker_dict, s_ticker_dict = {}, {}
        try:
            f_tickers = requests.get(f"{FUTURES_URL}/fapi/v1/ticker/24hr", headers=HEADERS, timeout=4).json()
            for t in f_tickers:
                f_ticker_dict[t['symbol']] = t
        except:
            pass
        try:
            s_tickers = requests.get(f"{SPOT_URL}/api/v3/ticker/24hr", headers=HEADERS, timeout=4).json()
            for t in s_tickers:
                s_ticker_dict[t['symbol']] = t
        except:
            pass

        for symbol, market_type in market_pairs:
            try:
                time.sleep(0.04) # API Rate Limit Dostu Gecikme
                
                # Coinin işlem gördüğü piyasaya göre baz URL ve veri havuzunu seç
                if market_type == "Futures":
                    base_url = FUTURES_URL
                    endpoint = "/fapi/v1/klines"
                    ticker_pool = f_ticker_dict
                else:
                    base_url = SPOT_URL
                    endpoint = "/api/v3/klines"
                    ticker_pool = s_ticker_dict
                
                if symbol not in ticker_pool:
                    continue
                
                # Günlük %8'den fazla fırlamışları doğrudan ele
                if float(ticker_pool[symbol].get('priceChangePercent', 0)) > 8.0:
                    continue
                
                # 3. 5 DAKİKALIK MUM VE TAKER BUY VERİLERİ
                res = requests.get(f"{base_url}{endpoint}", params={"symbol": symbol, "interval": "5m", "limit": 20}, headers=HEADERS, timeout=4)
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
                
                # ORTAK KRİTİK KALKANLAR
                if current_close <= current_open:
                    continue
                if taker_buy_vol < (current_vol * 0.55):
                    continue
                if current_close < mean(prices[:-1]):
                    continue

                # YATAYLIK FORMASYONU (Son 1.5 saat içinde fiyat max %4 oynamış olmalı)
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

                quote_vol = float(ticker_pool[symbol].get('quoteVolume', 0))
                score = 3
                stars = "⭐" * score

                # --------------------------------------------------------
                # 💎 SINIF 1: ZIRHLI SİNYAL KONTROLÜ (YALNIZCA VADELİ PİYASA)
                # --------------------------------------------------------
                if market_type == "Futures" and ratio > 5.0 and quote_vol > 10000000:
                    # 7 Günlük Gerçek Dip Kontrolü
                    try:
                        res_7d = requests.get(f"{FUTURES_URL}/fapi/v1/klines", params={"symbol": symbol, "interval": "1d", "limit": 7}, headers=HEADERS, timeout=4).json()
                        if current_close > (max([float(k[2]) for k in res
