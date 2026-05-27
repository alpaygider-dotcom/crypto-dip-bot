import requests
import time
from statistics import mean

BOT_TOKEN = "8728951395:AAHLIgnGKxddfAJFkfQxm8t0bsnTnAJNYZU"
CHAT_ID = "6637406938"

BASE_URL = "https://fapi.binance.com"

sent_early = {}
sent_elite = {}

# =========================
# TELEGRAM
# =========================

def send_telegram(message):

    try:

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=10
        )

    except:
        pass

# =========================
# GET PAIRS
# =========================

def get_pairs():

    try:

        url = f"{BASE_URL}/fapi/v1
