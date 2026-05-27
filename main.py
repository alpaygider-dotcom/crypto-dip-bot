import requests
import time
from statistics import mean

# CREDENTIALS
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_FUTURES = "https://fapi.binance.com"

# PROFESYONEL FİLTRE AYARLARI
MIN_DAILY_VOLUME = 10000000       # En az 10M$ hacim
LONG_SHORT_MAX_THRESHOLD = 1.25   # Long/Short oranı sınırı
VOLUME_BOOM_THRESHOLD = 3.5       # Son 5dk hacim katı
DIP_MIN_PERCENT = 20.0            # Zirveden en az %20 düşüş
MAX_ALLOWED_PUMP = 5.0            # Son 20dk maksimum pump oranı

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data)
    except:
        pass

def get_usdt_pairs():
    try:
        url = f"{BINANCE_FUTURES}/fapi/v1/exchangeInfo"
        res = requests.get(url).json()
        pairs = []
        for s in res["symbols"]:
            if s["quoteAsset"] == "USDT" and s["status"] == "TRADING":
                pairs.append(s["symbol"])
        return pairs
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
    try:
        ls_url = f"{BINANCE_FUTURES}/futures/data/globalLongShortAccountRatio"
        ls_res = requests.get(ls_url, params={"symbol": symbol, "period": "5m", "limit": 1}).json()
        global_ls = float(ls_res[0]["longShortRatio"]) if ls_res else 1.5

        oi_url = f"{BINANCE_FUTURES}/futures/data/openInterestHist"
        oi_res = requests.get(oi_url, params={"symbol": symbol, "period": "5m", "limit": 2}).json()
        oi_change = 0.0
        if oi_res and len(oi_res) >= 2:
            old_oi = float(oi_res[0]["sumOpenInterest"])
            new_oi = float(oi_res[1]["sumOpenInterest"])
            if old_oi > 0:
                oi_change = round(((new_oi - old_oi) / old_oi) * 100, 2)

        ticker_url = f"{BINANCE_FUTURES}/fapi/v1/ticker/24hr"
        tk_res = requests.get(ticker_url, params={"symbol": symbol}).json()
        daily_volume = float(tk_res.get("quoteVolume", 0))
        funding_rate = float(tk_res.get("lastFundingRate", 0)) * 100

        return global_ls, oi_change, daily_volume, funding_rate
    except:
        return 1.5, 0.0, 0.0, 0.0

def check_btc_trend():
    try:
        klines = get_klines("BTCUSDT", "5m", 4)
        if not klines or len(klines) < 4:
            return 0.0, 0.0
        closes = [float(k[4]) for k in klines]
        move_5m = ((closes[-1] - closes[-2]) / closes[-2]) * 100
        move_20m = ((closes[-1] - closes[-4]) / closes[-4]) * 100
        return move_5m, move_20m
    except:
        return 0.0, 0.0

def calculate_targets(daily_klines, current_price):
    try:
        highs = [float(k[2]) for k in daily_klines]
        lows = [float(k[3]) for k in daily_klines]
        closes = [float(k[4]) for k in daily_klines]

        H = max(highs)
        L = min(lows)
        C = closes[-1]

        pivot = (H + L + C) / 3.0
        r1 = (2.0 * pivot) - L
        r2 = pivot + (H - L)

        if r1 <= current_price:
            r1 = current_price * 1.05
        if r2 <= r1:
            r2 = r1 * 1.08

        return round(r1, 4), round(r2, 4)
    except:
        return round(current_price * 1.05, 4), round(current_price * 1.12, 4)

def analyze(symbol, btc_5m, btc_20m):
    try:
        global_ls, oi_change, daily_volume, funding_rate = get_market_indicators(symbol)
        
        if daily_volume < MIN_DAILY_VOLUME:
            return None
        if global_ls > LONG_SHORT_MAX_THRESHOLD:
            return None

        daily_klines = get_klines(symbol, "1d", 14)
        if not daily_klines or len(daily_klines) < 14:
            return None
        high_14d = max([float(k[2]) for k in daily_klines])

        klines_5m = get_klines(symbol, "5m", 50)
        if not klines_5m or len(klines_5m) < 50:
            return None

        volumes = [float(k[5]) for k in klines_5m]
        current_volume = volumes[-1]
        avg_volume = mean(volumes[:-1])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0.0

        closes = [float(k[4]) for k in klines_5m]
        current_price = closes[-1]
        
        dip_distance = ((high_14d - current_price) / high_14d) * 100
        price_change_5m = ((closes[-1] - closes[-2]) / closes[-2]) * 100
        price_change_20m = ((closes[-1] - closes[-4]) / closes[-4]) * 100

        btc_relative_strength = price_change_5m - btc_5m

        if volume_ratio < VOLUME_BOOM_THRESHOLD:
            return None
        if dip_distance < DIP_MIN_PERCENT:
            return None
        if price_change_20m > MAX_ALLOWED_PUMP:
            # Burası süzgeç: Zaten uçan kaçan coini eler
            return None
        if price_change_5m <= 0:
            return None

        target_1, target_2 = calculate_targets(daily_klines, current_price)

        # PARANTEZ HATALARINI ÖNLEMEK İÇİN SIFIRDAN YALIN HESAPLAMA SİSTEMİ
        score_vol = volume_ratio * 1.2
        if score_vol > 6.0:
            score_vol = 6.0

        score_ls = (1.5 - global_ls) * 4.0
        if score_ls > 4.0:
            score_ls = 4.0
        if score_ls < 0.0:
            score_ls = 0.0

        score_dip = dip_distance / 10.0
        if score_dip > 4.0:
            score_dip = 4.0

        score_oi = oi_change * 1.5
        if score_oi > 3.0:
            score_oi = 3.0
        if score_oi < 0.0:
            score_oi = 0.0

        score_btc = 0.0
        if btc_relative_strength > 0.5:
            score_btc = 3.0

        total_score = round(score_vol + score_ls + score_dip + score_oi + score_btc, 2)

        if total_score < 7.5:
            return None

        return {
            "symbol": symbol, "score": total_score, "price": current_price,
            "volume_ratio": round(volume_ratio, 2), "oi_change": oi_change,
            "dip_distance": round(dip_distance, 2), "price_change": round(price_change_20m, 2),
            "global_ls": round(global_ls, 2), "btc_rel": round(btc_relative_strength, 2),
            "target_1": target_1, "target_2": target_2, "funding": round(funding_rate, 4)
        }
    except:
        return None

def main():
    sent_dict = {}
    print("💎 PRO PLUS PLUS EXTRA SÜRÜM BAŞARIYLA ÇALIŞTIRILDI 💎")
    send_telegram("💎 *PRO PLUS PLUS EXTRA BOT AKTİF!* \n\n_Sistem sorunsuz şekilde ayağa kalktı. Dip taramaları ve matematiksel satış hedefleri devrede._")

    while True:
        try:
            pairs = get_usdt_pairs()
            btc_5m, btc_20m = check_btc_trend()
            current_time = time.time()
            
            current_time_str = time.strftime('%H:%M:%S')
            print(f"[{current_time_str}] Tarama Aktif. {len(pairs)} çift izleniyor...")
            
            for symbol in pairs:
                data = analyze(symbol, btc_5m, btc_20m)
                
                if data:
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
            
            time.sleep(300)
            
        except Exception as e:
            print(f"Sistem Hatası: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
