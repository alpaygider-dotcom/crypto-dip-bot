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
