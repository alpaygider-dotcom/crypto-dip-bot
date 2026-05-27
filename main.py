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

    requests.post(url, data=data)

def get_usdt_pairs():
    url = f"{BINANCE_FUTURES}/fapi/v1/exchangeInfo"
    data = requests.get(url).json()

    pairs = []

    for s in data["symbols"]:
        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING":
            pairs.append(s["symbol"])

    return pairs

def get_klines(symbol):
    url = f"{BINANCE_FUTURES}/fapi/v1/klines"

    params = {
        "symbol": symbol,
        "interval": "5m",
        "limit": 50
    }

    data = requests.get(url, params=params).json()

    return data

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

        change = ((new_oi - old_oi) / old_oi) * 100

        return round(change, 2)

    except:
        return 0

def analyze(symbol):
    try:
        klines = get_klines(symbol)

        volumes = [float(k[5]) for k in klines]

        current_volume = volumes[-1]

        avg_volume = mean(volumes[:-1])

        volume_ratio = current_volume / avg_volume

        closes = [float(k[4]) for k in klines]

        current_price = closes[-1]

        high_14d = max(closes)

        dip_distance = ((high_14d - current_price) / high_14d) * 100

        oi_change = get_open_interest(symbol)

        price_change = ((closes[-1] - closes[-4]) / closes[-4]) * 100

        if (
            volume_ratio > 3
            and dip_distance > 15
            and oi_change > 2
            and price_change < 6
        ):

            score = round(
                volume_ratio +
                (dip_distance / 10) +
                oi_change,
                2
            )

            return f'''
🔥 GÜÇLÜ SİNYAL

Coin: {symbol}

Skor: {score}

5m Hacim Artışı: {round(volume_ratio,2)}x
OI Artışı: %{oi_change}
Dipten Uzaklık: %{round(dip_distance,2)}
Son Hareket: %{round(price_change,2)}
'''

    except:
        return None

def main():
    sent = set()

    send_telegram("🤖 Dip Bot Aktif")

    while True:
        try:
            pairs = get_usdt_pairs()

            for symbol in pairs:

                result = analyze(symbol)

                if result and symbol not in sent:
                    send_telegram(result)
                    sent.add(symbol)

            time.sleep(300)

        except Exception as e:
            send_telegram(f"HATA: {e}")
            time.sleep(60)

main()
