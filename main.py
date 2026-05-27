import requests
import time
from statistics import mean

# REGULARY CONFIGURED CREDENTIALS
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_FUTURES = "https://fapi.binance.com"

# PROFESYONEL FİLTRE AYARLARI
MIN_DAILY_VOLUME = 10_000_000       # En az 10M$ hacmi olan ciddiye alınır coinler
LONG_SHORT_MAX_THRESHOLD = 1.25     # Long/Short oranı bu değerin altındaysa (Longlar baskı altında/dökülmüş) avantajlıdır
VOLUME_BOOM_THRESHOLD = 3.5         # Son 5dk hacmi, normalin en az 3.5 katı olmalı
DIP_MIN_PERCENT = 20.0              # Son 14 günün zirvesinden en az %20 düşmüş olmalı (Tam dip arayışı)
MAX_ALLOWED_PUMP = 5.0              # Son 20 dakikada %5'ten fazla yükselmemiş olmalı (Geç kalmamak için)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"Telegram Bağlantı Hatası: {e}")

def get_usdt_pairs():
    try:
        url = f"{BINANCE_FUTURES}/fapi/v1/exchangeInfo"
        data = requests.get(url).json()
        return [s["symbol"] for s in data["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]
    except:
        return []

def get_klines(symbol, interval, limit):
    try:
        url = f"{BINANCE_FUTURES}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return requests.get(url, params=params).json()
    except:
        return []

def get_market_indicators(symbol):
    """Long/Short Oranı, OI ve Günlük Hacmi Tek Seferde Çeker"""
    try:
        # 1. Global Long/Short Oranı
        ls_url = f"{BINANCE_FUTURES}/futures/data/globalLongShortAccountRatio"
        ls_data = requests.get(ls_url, params={"symbol": symbol, "period": "5m", "limit": 1}).json()
        global_ls = float(ls_data[0]["longShortRatio"]) if ls_data else 1.5

        # 2. Open Interest (Açık Pozisyon Değişimi)
        oi_url = f"{BINANCE_FUTURES}/futures/data/openInterestHist"
        oi_data = requests.get(oi_url, params={"symbol": symbol, "period": "5m", "limit": 2}).json()
        oi_change = 0
        if len(oi_data) >= 2:
            old_oi = float(oi_data[0]["sumOpenInterest"])
            new_oi = float(oi_data[1]["sumOpenInterest"])
            oi_change = round(((new_oi - old_oi) / old_oi) * 100, 2) if old_oi > 0 else 0

        # 3. 24 Saatlik Genel Hacim ve Anlık Fiyat
        ticker_url = f"{BINANCE_FUTURES}/fapi/v1/ticker/24hr"
        ticker_data = requests.get(ticker_url, params={"symbol": symbol}).json()
        daily_volume = float(ticker_data.get("quoteVolume", 0))
        funding_rate = float(ticker_data.get("lastFundingRate", 0)) * 100

        return global_ls, oi_change, daily_volume, funding_rate
    except:
        return 1.5, 0, 0, 0

def check_btc_trend():
    """Bitcoin'in son 5 dakikalık ve 20 dakikalık değişimini izler"""
    try:
        klines = get_klines("BTCUSDT", "5m", 4)
        if not klines: return 0.0, 0.0
        closes = [float(k[4]) for k in klines]
        move_5m = ((closes[-1] - closes[-2]) / closes[-2]) * 100
        move_20m = ((closes[-1] - closes[-4]) / closes[-4]) * 100
        return move_5m, move_20m
    except:
        return 0.0, 0.0

def calculate_targets(daily_klines, current_price):
    """
    Matematiksel Pivot ve Direnç Hesaplaması (Satış Noktalarını Belirler)
    Son 14 günün High, Low ve Close değerlerine göre direnç seviyelerini bulur.
    """
    try:
        highs = [float(k[2]) for k in daily_klines]
        lows = [float(k[3]) for k in daily_klines]
        closes = [float(k[4]) for k in daily_klines]

        H = max(highs)
        L = min(lows)
        C = closes[-1]

        # Klasik Pivot Noktası Hesabı
        pivot = (H + L + C) / 3
        
        # Direnç Seviyeleri (Satış Hedefleri)
        r1 = (2 * pivot) - L  # İlk direnç (Hedef 1)
        r2 = pivot + (H - L)  # İkinci güçlü direnç (Hedef 2)

        # Eğer hesaplanan hedefler fiyattan küçükse mantıklı bir yüzde ekle
        if r1 <= current_price: r1 = current_price * 1.05
        if r2 <= r1: r2 = r1 * 1.08

        return round(r1, 4), round(r2, 4)
    except:
        return round(current_price * 1.05, 4), round(current_price * 1.12, 4)

def analyze(symbol, btc_5m, btc_20m):
    try:
        # 1. Piyasa Verilerini Tek Seferde Sorgula (Hız ve Performans İçin)
        global_ls, oi_change, daily_volume, funding_rate = get_market_indicators(symbol)
        
        # Kalite ve Hacim Barajı
        if daily_volume < MIN_DAILY_VOLUME: return None
        
        # CRITICAL FILTER: Long/Short Oranı Düşük Olmalı (Senin istediğin: Longçular ezilmiş/temizlenmiş olacak)
        if global_ls > LONG_SHORT_MAX_THRESHOLD: return None

        # 2. 14 Günlük Tarihsel Dip Analizi
        daily_klines = get_klines(symbol, interval="1d", limit=14)
        if not daily_klines or len(daily_klines) < 14: return None
        high_14d = max([float(k[2]) for k in daily_klines])

        # 3. 5M Mikro Hacim ve Fiyat Analizi
        klines_5m = get_klines(symbol, interval="5m", limit=50)
        if not klines_5m or len(klines_5m) < 50: return None

        volumes = [float(k[5]) for k in klines_5m]
        current_volume = volumes[-1]
        avg_volume = mean(volumes[:-1])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        closes = [float(k[4]) for k in klines_5m]
        current_price = closes[-1]
        
        # Dipten Uzaklık & Pump Kontrolü
        dip_distance = ((high_14d - current_price) / high_14d) * 100
        price_change_5m = ((closes[-1] - closes[-2]) / closes[-2]) * 100
        price_change_20m = ((closes[-1] - closes[-4]) / closes[-4]) * 100

        # BTC'DEN BAĞIMSIZ HAREKET ETME GÜCÜ (ALFA ETKİSİ)
        # BTC düşerken veya sabitken bu coinin kafayı yukarı kaldırma oranı
        btc_relative_strength = price_change_5m - btc_5m

        # KATIDIR FİLTRELER (SPAM VE TEPE ALIMLARINI SIFIRLAR)
        if volume_ratio < VOLUME_BOOM_THRESHOLD: return None  # Güçlü hacim girişi şart
        if dip_distance < DIP_MIN_PERCENT: return None        # Kesinlikle dip bölgede olmalı
        if price_change_20m > MAX_ALLOWED_PUMP: return None   # Zaten %5+ uçmuşsa es geç
        if price_change_5m <= 0: return None                   # En son 5dk mumu yeşil olmalı (aksiyon başlamış)

        # 🎯 SATIŞ NOKTALARINI HESAPLA (MANTIKLI TAKE PROFIT)
        target_1, target_2 = calculate_targets(daily_klines, current_price)

        # 🌟 YAPAY ZEKA SKORLAMA FORMÜLÜ (MAX 20 PUAN)
        score = 0
        score += min(volume_ratio * 1.2, 6)             # Hacim Patlaması (Max 6)
        score += min((1.5 - global_ls) * 4, 4)          # Temiz Long/Short Dengesi (Max 4)
        score += min(dip_distance / 10, 4)              # Dipten Uzaklık / İndirim Oranı (Max 4)
        score += min(oi_change * 1.5, 3)                # OI Para Girişi (Max 3)
        if btc_relative_strength > 0.5: score += 3      # BTC'ye Meydan Okuma Bonusu (+3)

        score = round(score, 2)

        # Pro Sürüm Barajı: Sadece 7.5 ve üzeri alan Elit Sinyalleri yayınla
        if score < 7.5: return None

        return {
            "symbol": symbol, "score": score, "price": current_price,
            "volume_ratio": round(volume_ratio, 2), "oi_change": oi_change,
            "dip_distance": round(dip_distance, 2), "price_change": round(price_change_20m, 2),
            "global_ls": round(global_ls, 2), "btc_rel": round(btc_relative_strength, 2),
            "target_1": target_1, "target_2": target_2, "funding": round(funding_rate, 4)
        }
    except:
        return None

def main():
    sent_dict = {}
    print("💎 PRO PLUS PLUS EXTRA SÜRÜM AYAĞA KALKTI 💎")
    send_telegram("💎 *PRO PLUS PLUS EXTRA BOT AKTİF!* \n\n_Sistem şu andan itibaren hem dip taraması yapıyor hem de matematiksel satış hedeflerini hesaplıyor._")

    while True:
        try:
            pairs = get_usdt_pairs()
            btc_5m, btc_20m = check_btc_trend()
            current_time = time.time()
            
            print(f"[{time.strftime('%H('%M:%S')')}] Tarama Aktif. {len(pairs)} çift izleniyor...")
            
            for symbol in pairs:
                data = analyze(symbol, btc_5m, btc_20m)
                
                if data:
                    # Aynı coinden 1 saat boyunca tek sinyal (Spam engelleme)
                    if symbol not in sent_dict or (current_time - sent_dict[symbol] > 3600):
                        
                        msg = f"""🚨 *PRO PLUS PLUS EXTRA SİNYAL*

🔹 *Coin:* #{data['symbol']}
🌟 *Yapay Zeka Puanı:* `{data['score']} / 20`
💵 *Güncel Giriş Fiyatı:* `{data['price']}`
-----------------------------------------
🎯 *MATEMATİKSEL SATIŞ HEDEFLERİ:*
📌 *Hedef 1 (Kâr Al):* `{data['target_1']}` (İlk Güçlü Direnç)
📌 *Hedef 2 (Ana Hedef):* `{data['target_2']}` (14 Günlük Pivot Zirvesi)
-----------------------------------------
📊 *Algoritmik Metrikler:*
• 📉 Long/Short Ratio: `{data['global_ls']}` *(Longçular dökülmüş)*
• 🔥 5m Hacim Artışı: `{data['volume_ratio']}x`
• 🐳 Open Interest Değişimi: `%{data['oi_change']}`
• 🧗 Zirveden Düşüş Oranı: `%{data['dip_distance']}`
• ⚡ Son 20dk Fiyat Aksiyonu: `%{data['price_change']}`
• 🦁 BTC Bağımsız Güç (Alfa): `{data['btc_rel']}`
-----------------------------------------
⚠️ _Bot, hacim kırılımını ve long temizliğini onayladı._"""
                        
                        send_telegram(msg)
                        sent_dict[symbol] = current_time
            
            time.sleep(300) # 5 Dakika Bekleme Periyodu
            
        except Exception as e:
            print(f"Sistem Hatası: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
