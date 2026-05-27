import requests
import time
from statistics import mean

# CREDENTIALS
BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"
BINANCE_FUTURES = "https://fapi.binance.com"
BINANCE_SPOT = "https://api.binance.com"

# PROFESYONEL OPTİMİZE FİLTRE AYARLARI
MIN_DAILY_VOLUME = 10000000       # En az 10M$ hacim (Likidite filtresi)
LONG_SHORT_MAX_THRESHOLD = 1.25   # Sadece Futures için Long/Short oranı üst sınırı
VOLUME_BOOM_THRESHOLD = 2.3       # Son 5dk hacim katı (Dengeli hassasiyet: 2.3 katı yeterli)
DIP_MIN_PERCENT = 20.0            # Son 14 günün zirvesinden en az %20 düşmüş olmalı
MAX_ALLOWED_PUMP = 5.0            # Son 20dk maksimum pump oranı (Trene geç kalmama filtresi)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data)
    except:
        pass

def get_futures_pairs():
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

def get_spot_only_pairs(futures_pairs):
    try:
        url = f"{BINANCE_SPOT}/api/v3/exchangeInfo"
        res = requests.get(url).json()
        spot_pairs = []
        for s in res["symbols"]:
            if s["quoteAsset"] == "USDT" and s["status"] == "TRADING":
                symbol = s["symbol"]
                if symbol not in futures_pairs:
                    spot_pairs.append(symbol)
        return spot_pairs
    except:
        return []

def get_klines(symbol, interval, limit, is_futures=True):
    try:
        base_url = BINANCE_FUTURES if is_futures else BINANCE_SPOT
        endpoint = "/fapi/v1/klines" if is_futures else "/api/v3/klines"
        url = f"{base_url}{endpoint}"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return requests.get(url, params=params).json()
    except:
        return []

def get_futures_indicators(symbol):
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

        return global_ls, oi_change
    except:
        return 1.5, 0.0

def get_base_ticker(symbol, is_futures=True):
    try:
        if is_futures:
            url = f"{BINANCE_FUTURES}/fapi/v1/ticker/24hr"
            res = requests.get(url, params={"symbol": symbol}).json()
            daily_volume = float(res.get("quoteVolume", 0))
            funding_rate = float(res.get("lastFundingRate", 0)) * 100
            return daily_volume, funding_rate
        else:
            url = f"{BINANCE_SPOT}/api/v3/ticker/24hr"
            res = requests.get(url, params={"symbol": symbol}).json()
            daily_volume = float(res.get("quoteVolume", 0))
            return daily_volume, 0.0
    except:
        return 0.0, 0.0

def check_btc_trend():
    try:
        klines = get_klines("BTCUSDT", "5m", 4, is_futures=True)
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

        if r1 <= current_price: r1 = current_price * 1.05
        if r2 <= r1: r2 = r1 * 1.08

        return round(r1, 4), round(r2, 4)
    except:
        return round(current_price * 1.05, 4), round(current_price * 1.12, 4)

def analyze(symbol, btc_5m, btc_20m, is_futures=True):
    try:
        daily_volume, funding_rate = get_base_ticker(symbol, is_futures)
        if daily_volume < MIN_DAILY_VOLUME:
            return None

        global_ls = 1.0
        oi_change = 0.0
        if is_futures:
            global_ls, oi_change = get_futures
