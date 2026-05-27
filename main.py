import requests
import time
from statistics import mean

# REGULARY CONFIGURED CREDENTIALS
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_FUTURES = "https://fapi.binance.com"

# PROFESYONEL FİLTRE AYARLARI
MIN_DAILY_VOLUME = 10_000_000       # En az 10M$ hacmi olan ciddiye alınır coinler
LONG_SHORT_MAX_THRESHOLD = 1.25     # Long/Short oranı bu değerin altındaysa avantajlıdır
VOLUME_BOOM_THRESHOLD = 3.5         # Son 5dk hacmi, normalin en az 3.5 katı olmalı
DIP_MIN_PERCENT = 20.0              # Son 14 günün zirvesinden en az %20 düşmüş olmalı
MAX_ALLOWED_PUMP = 5.0              # Son 20 dakikada %5'ten fazla yükselmemiş olmalı

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
    try:
        # 1. Global Long/Short Oranı
        ls_url = f"{BINANCE_FUTURES}/futures/data/globalLongShortAccountRatio"
        ls_data = requests.get(ls_url, params={"symbol": symbol, "period": "5m", "limit": 1}).json()
        global_ls = float(ls_data[0]["longShortRatio"]) if ls_data else 1.5

        # 2. Open Interest
        oi_url = f"{BINANCE_FUTURES}/futures/data/openInterestHist"
        oi_data = requests.get(oi_url, params={"symbol": symbol, "period": "5m", "limit": 2}).json()
        oi_change = 0
        if len(oi_data) >= 2:
            old_oi = float(oi_data[0]["sumOpenInterest"])
            new_oi = float(oi_data[1]["sumOpenInterest"])
            oi_change = round(((new_oi - old_oi) / old_oi) * 100, 2) if old_oi > 0 else 0

        # 3. 24 Saatlik Genel Hacim
        ticker_url = f"{BINANCE_FUTURES}/fapi/v1/ticker/24hr"
        ticker_data = requests.get(ticker_url, params={"symbol": symbol}).json()
        daily_volume = float(ticker_data.get("quoteVolume", 0))
        funding_rate = float(ticker_data.get("lastFundingRate", 0)) * 100

        return global_ls, oi_change, daily_volume, funding_rate
    except:
        return 1.5, 0, 0, 0

def check_btc_trend():
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
    try:
        highs = [float(k[2]) for k in daily_klines]
        lows = [float(k[3]) for k in daily_klines]
        closes = [float(k[4]) for k in daily_klines]

        H = max(highs)
        L = min(lows)
        C = closes[-1]

        pivot = (H + L + C) / 3
        r1 = (2 * pivot) - L
        r2 = pivot + (H - L)

        if r1 <= current_price: r1 = current_price * 1.05
        if r2 <= r1: r2 = r1 * 1.08

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

        daily_klines = get_klines(symbol, interval="1d", limit=14)
        if not daily_klines or len(daily_klines) < 14: 
            return None
        high_14d = max([float(k[2]) for k in daily_klines])

        klines_5m = get_klines(symbol, interval="5m", limit=50)
        if not klines_5m or len(klines_5m) < 50: 
            return None

        volumes = [float(k[5]) for k in klines_5m]
        current_volume = volumes[-1]
        avg_volume = mean(volumes[:-1])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

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
            return None
        if price_change_5m <= 0: 
            return None

        target_1, target_2 = calculate_targets(daily_klines, current_price)

        score = 0
        score += min(volume_ratio * 1.2, 6)
        score += min((1.5 - global_ls) * 4, 4)
        score += min(
