import requests
import time
from statistics import mean

BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_FUTURES = "https://fapi.binance.com"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message
    }
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"Telegram mesajı gönderilemedi: {e}")

def get_usdt_pairs():
    try:
        url = f"{BINANCE_FUTURES}/fapi/v1/exchangeInfo"
        response = requests.get(url)
        data = response.json()
        
        if "symbols" not in data:
            return []
            
        pairs = [s["symbol"] for s in data["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"]
        return pairs
    except Exception as e:
        print(f"Coin listesi alınamadı: {e}")
        return []

def get_klines(symbol, interval="5m", limit=50):
    try:
        url = f"{BINANCE_FUTURES}/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        return requests.get(url, params=params).json()
    except:
        return []

def get_open_interest(symbol):
    try:
        url = f"{BINANCE_FUTURES}/futures/data/openInterestHist"
        params = {
            "symbol": symbol,
            "period": "5m",
            "limit": 2
        }
        data = requests.get(url, params=params).json()
        
        if len(data) < 2:
            return 0
            
        old_oi = float(data[0]["sumOpenInterest"])
        new_oi = float(data[1]["sumOpenInterest"])
        
        if old_oi == 0: return 0
        
        change = ((new_oi - old_oi) / old_oi) * 100
        return round(change, 2)
    except:
        return 0

def analyze(symbol):
    try:
        # 1. 14 Günlük Zirve Tespiti (1 günlük mumlardan 14 tane)
        daily_klines = get_klines(symbol, interval="1d", limit=14)
        if not daily_klines or len(daily_klines) < 14:
            return None
            
        # Index 2 mumun 'High' (En Yüksek) fiyatıdır
        high_14d = max([float(k[2]) for k in daily_klines]) 

        # 2. 5 Dakikalık Veriler (Hacim ve Anlık Fiyat)
        klines_5m = get_klines(symbol, interval="5m", limit=50)
        if not klines_5m or len(klines_5m) < 50:
            return None

        # Hacim Analizi
        volumes = [float(k[5]) for k in klines_5m]
        current_volume = volumes[-1]
        avg_volume = mean(volumes[:-1])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        # Fiyat Analizi
        closes = [float(k[4]) for k in klines_5m]
        current_price = closes[-1]
        
        # Dipten Uzaklık (14 Günlük zirveye göre düşüş oranı)
        dip_distance = ((high_14d - current_price) / high_14d) * 100

        # OI Değişimi
        oi_change = get_open_interest(symbol)

        # Son Hareket (Son 4 muma, yani 20 dakikaya göre fiyat değişimi)
        price_change = ((closes[-1] - closes[-4]) / closes[-4]) * 100

        # Strateji Filtreleri
        if (volume_ratio > 3 and dip_distance > 15 and oi_change > 2 and price_change < 6):
            score = round(volume_ratio + (dip_distance / 10) + oi_change, 2)
            
            return f'''🔥 GÜÇLÜ SİNYAL

Coin: {symbol}
Skor: {score}

5m Hacim Artışı: {round(volume_ratio,2)}x
OI Artışı: %{oi_change}
Zirveden Düşüş: %{round(dip_distance,2)}
Son 20dk Fiyat Hareketi: %{round(price_change,2)}'''

    except Exception as e:
        # Tekil coin hatalarını ekrana basma ki konsol kirlenmesin, sadece geç
        return None

def main():
    sent_dict = {} # Sinyalleri kalıcı engellememek için sözlük yapısına geçtik
    
    msg = "🤖 Dip Bot Aktif - Tarama Başlıyor"
    send_telegram(msg)
    print(msg)

    while True:
        try:
            pairs = get_usdt_pairs()
            print(f"[{time.strftime('%H:%M:%S')}] {len(pairs)} adet USDT paritesi taranıyor...")
            
            for symbol in pairs:
                result = analyze(symbol)
                
                if result:
                    # Coinden daha önce sinyal gelmediyse VEYA son sinyalin üzerinden 1 saat (3600 sn) geçtiyse
                    if symbol not in sent_dict or (time.time() - sent_dict[symbol] > 3600):
                        print(f"SİNYAL BULUNDU: {symbol}")
                        send_telegram(result)
                        sent_dict[symbol] = time.time()
            
            print("Tarama bitti. 5 dakika bekleniyor...")
            time.sleep(300)
            
        except Exception as e:
            err_msg = f"HATA: Ana Döngü Çöktü -> {e}"
            print(err_msg)
            send_telegram(err_msg)
            time.sleep(60)

if __name__ == "__main__":
    main()
    
