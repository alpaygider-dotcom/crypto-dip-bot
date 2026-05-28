import asyncio
import aiohttp
import os
import time
import logging
import traceback
from statistics import mean, stdev
from datetime import datetime

# ==================================================
# MODE SEÇİMİ
# LOW = az sinyal, çok filtre
# BALANCED = önerilen
# HIGH = daha fazla sinyal (pump kaçırmaz)
# ==================================================
MODE = "BALANCED"

# ==================================================
# LOG AYARLARI
# ==================================================
logging.basicConfig(
    filename='bot_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY")

BASE_URL = "https://fapi.binance.com"

SCAN_INTERVAL = 40
COOLDOWN = 600
MAX_CONCURRENT_REQUESTS = 20

last_signal = {}
telegram_queue = asyncio.Queue()

# ==================================================
# MODE PARAMS
# ==================================================
def get_params():
    if MODE == "LOW":
        return dict(min_change=0.25, min_vol=0.8, score_mult=1.2)
    if MODE == "HIGH":
        return dict(min_change=0.12, min_vol=0.5, score_mult=0.8)
    return dict(min_change=0.18, min_vol=0.6, score_mult=1.0)

# ==================================================
# TELEGRAM
# ==================================================
async def telegram_worker(session):
    while True:
        text = await telegram_queue.get()
        try:
            if not BOT_TOKEN or not CHAT_ID:
                print(text)
            else:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                payload = {"chat_id": CHAT_ID, "text": text}
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(1)
                        await telegram_queue.put(text)
        except Exception:
            logging.error(traceback.format_exc())
        finally:
            telegram_queue.task_done()
        await asyncio.sleep(0.25)

async def send_telegram(text):
    await telegram_queue.put(text)

# ==================================================
# FETCH
# ==================================================
async def fetch_json(session, endpoint, params=None):
    try:
        url = BASE_URL + endpoint
        async with session.get(url, params=params, timeout=10) as r:
            if r.status != 200:
                return None
            return await r.json()
    except:
        return None

# ==================================================
# EMA
# ==================================================
def ema(values, period):
    if len(values) < period:
        return None
    m = 2 / (period + 1)
    e = mean(values[:period])
    for p in values[period:]:
        e = ((p - e) * m) + e
    return e

# ==================================================
# ATR
# ==================================================
def atr(h, l, c, period=14):
    if len(h) < period + 1:
        return None
    trs = []
    for i in range(1, len(h)):
        trs.append(max(
            h[i]-l[i],
            abs(h[i]-c[i-1]),
            abs(l[i]-c[i-1])
        ))
    return mean(trs[-period:]) if len(trs) >= period else None

# ==================================================
# REGIME
# ==================================================
def regime(closes, vols):
    move = (closes[-1]-closes[0])/closes[0]
    v = stdev(vols) if len(vols) > 1 else 0
    z = (vols[-1]-mean(vols))/v if v > 0 else 0

    if abs(move) < 0.004:
        return "RANGE"
    if abs(move) > 0.01 and z > 1:
        return "TREND"
    return "MIXED"

# ==================================================
# SWEEP (erken pump yakalama güçlendirildi)
# ==================================================
def sweep(h, l, c):
    up = h[-1] > max(h[-10:-1]) and c[-1] < h[-1]
    down = l[-1] < min(l[-10:-1]) and c[-1] > l[-1]
    return up, down

# ==================================================
# ORDERFLOW
# ==================================================
def orderflow(v, tb, hist_tb=None, hist_v=None):
